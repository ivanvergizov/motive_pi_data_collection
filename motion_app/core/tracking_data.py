from __future__ import annotations

from dataclasses import replace

import numpy as np

from motion_app.core.app_types import BodyDisplaySettings, BodyPose, BodyType, SceneFrame, SignalDataType, SignalMode
from motion_app.core.body_config import DEFAULT_BODY_TYPE, load_body_type_map
from motion_app.core.constants import SIGNAL_DEFINITIONS, color_for_curve
from motion_app.core.motive_io import RigidBodyData, TrackingSession
from motion_app.core.rigid_body_math import motive_positions_to_display, quaternion_xyzw_to_xyz_degrees
from motion_app.core.room_geometry import calculate_room_bounds
from motion_app.core.signal_processing import smooth_tracking_positions_and_rotations
from motion_app.geometry.body_geometry import body_dimensions


def nearest_sample_index(times: np.ndarray, time_s: float) -> int:
    right = int(np.searchsorted(times, time_s, side="left"))
    if right <= 0:
        return 0
    if right >= len(times):
        return len(times) - 1
    left = right - 1
    return left if abs(time_s - times[left]) <= abs(times[right] - time_s) else right


class TrackingDataProvider:
    def __init__(self, session: TrackingSession | None = None) -> None:
        self.session: TrackingSession | None = None
        self.display_positions: dict[str, np.ndarray] = {}
        self.display_rotations: dict[str, np.ndarray] = {}
        self.body_display_settings: dict[str, BodyDisplaySettings] = {}
        self._smoothed_source_positions: dict[str, np.ndarray] = {}
        self._smoothed_display_positions: dict[str, np.ndarray] = {}
        self._smoothed_rotations: dict[str, np.ndarray] = {}
        self._smoothed_euler: dict[str, np.ndarray] = {}
        self._smoothing_seconds: float | None = None
        if session is not None:
            self.set_session(session)

    def set_session(self, session: TrackingSession) -> None:
        self.session = session
        self.display_positions.clear()
        self.display_rotations.clear()
        self.body_display_settings.clear()
        self.clear_smoothing_cache()

        configured_body_types = load_body_type_map()
        for body_index, (body_name, body) in enumerate(session.bodies.items()):
            self.display_positions[body_name] = motive_positions_to_display(
                body.position_x, body.position_y, body.position_z
            )
            self.display_rotations[body_name] = np.column_stack(
                [body.rotation_x, body.rotation_y, body.rotation_z, body.rotation_w]
            )
            self.body_display_settings[body_name] = BodyDisplaySettings(
                body_type=configured_body_types.get(body_name, DEFAULT_BODY_TYPE),
                color=color_for_curve(body_index),
            )

    def set_body_type(self, body_name: str, body_type: BodyType) -> None:
        self.body_display_settings[body_name] = replace(
            self.body_display_settings[body_name],
            body_type=body_type,
        )

    def clear_smoothing_cache(self) -> None:
        self._smoothed_source_positions.clear()
        self._smoothed_display_positions.clear()
        self._smoothed_rotations.clear()
        self._smoothed_euler.clear()
        self._smoothing_seconds = None

    def ensure_smoothed(self, smoothing_seconds: float) -> None:
        session = self._require_session()
        if self._smoothing_seconds == float(smoothing_seconds) and self._smoothed_source_positions:
            return

        self.clear_smoothing_cache()
        for body_name, body in session.bodies.items():
            source_positions = np.column_stack([body.position_x, body.position_y, body.position_z])
            source_positions, rotations = smooth_tracking_positions_and_rotations(
                time_s=session.time,
                positions=source_positions,
                rotations=self.display_rotations[body_name],
                smoothing_seconds=smoothing_seconds,
            )
            self._smoothed_source_positions[body_name] = source_positions
            self._smoothed_display_positions[body_name] = motive_positions_to_display(
                source_positions[:, 0], source_positions[:, 1], source_positions[:, 2]
            )
            self._smoothed_rotations[body_name] = rotations
            self._smoothed_euler[body_name] = quaternion_xyzw_to_xyz_degrees(rotations)
        self._smoothing_seconds = float(smoothing_seconds)

    def positions(self, body_name: str, smoothed: bool, smoothing_seconds: float) -> np.ndarray:
        if smoothed:
            self.ensure_smoothed(smoothing_seconds)
            return self._smoothed_display_positions[body_name]
        return self.display_positions[body_name]

    def rotations(self, body_name: str, smoothed: bool, smoothing_seconds: float) -> np.ndarray:
        if smoothed:
            self.ensure_smoothed(smoothing_seconds)
            return self._smoothed_rotations[body_name]
        return self.display_rotations[body_name]

    def room_bounds(self):
        maximum_dimension = max(
            (body_dimensions(settings.body_type).max_dimension for settings in self.body_display_settings.values()),
            default=0.10,
        )
        return calculate_room_bounds(self.display_positions, minimum_padding=maximum_dimension)

    def scene_frame(
        self,
        time_s: float,
        frame_idx: int,
        selected_bodies: list[str] | set[str],
        smoothed: bool,
        smoothing_seconds: float,
    ) -> SceneFrame:
        session = self._require_session()
        if len(session.time) == 0:
            return SceneFrame(time_s, 0.0, 0, {})

        frame_idx = min(max(int(frame_idx), 0), len(session.time) - 1)
        poses: dict[str, BodyPose] = {}
        for body_name in selected_bodies:
            if body_name not in session.bodies:
                continue
            positions = self.positions(body_name, smoothed, smoothing_seconds)
            rotations = self.rotations(body_name, smoothed, smoothing_seconds)
            poses[body_name] = BodyPose(
                position=np.asarray(positions[frame_idx], dtype=float),
                quaternion_xyzw=np.asarray(rotations[frame_idx], dtype=float),
            )

        return SceneFrame(
            time_s=float(time_s),
            sample_time_s=float(session.time[frame_idx]),
            frame_number=int(session.frames[frame_idx]),
            poses=poses,
        )

    def signal_values(
        self,
        body_name: str,
        signal_label: str,
        mode: SignalMode,
        smoothing_seconds: float,
    ) -> np.ndarray:
        session = self._require_session()
        body = session.bodies[body_name]
        data_type, index = SIGNAL_DEFINITIONS[signal_label]

        if mode == "raw":
            return self._raw_signal(body, data_type, index)
        if mode == "smoothed":
            self.ensure_smoothed(smoothing_seconds)
            if data_type == "position":
                return self._smoothed_source_positions[body_name][:, index]
            if data_type == "euler":
                return self._smoothed_euler[body_name][:, index]
            return self._smoothed_rotations[body_name][:, index]
        return self._interpolated_signal(body, data_type, index)

    @staticmethod
    def _interpolated_signal(body: RigidBodyData, data_type: SignalDataType, index: int) -> np.ndarray:
        if data_type == "position":
            signals = (body.position_x, body.position_y, body.position_z)
        elif data_type == "euler":
            signals = (body.rotation_xyz_x, body.rotation_xyz_y, body.rotation_xyz_z)
        else:
            signals = (body.rotation_x, body.rotation_y, body.rotation_z, body.rotation_w)
        return signals[index]

    @staticmethod
    def _raw_signal(body: RigidBodyData, data_type: SignalDataType, index: int) -> np.ndarray:
        if data_type == "position":
            signals = (
                body.pre_interpolation_position_x,
                body.pre_interpolation_position_y,
                body.pre_interpolation_position_z,
            )
        elif data_type == "euler":
            signals = (
                body.pre_interpolation_rotation_xyz_x,
                body.pre_interpolation_rotation_xyz_y,
                body.pre_interpolation_rotation_xyz_z,
            )
        else:
            signals = (
                body.pre_interpolation_rotation_x,
                body.pre_interpolation_rotation_y,
                body.pre_interpolation_rotation_z,
                body.pre_interpolation_rotation_w,
            )
        return signals[index]

    def _require_session(self) -> TrackingSession:
        if self.session is None:
            raise RuntimeError("A tracking session has not been assigned.")
        return self.session
