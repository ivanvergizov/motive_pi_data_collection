from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .natnet.NatNetClient import NatNetClient
from .testbed import MotivePlan


@dataclass(frozen=True)
class RigidBodySample:
    rigid_body_id: int
    name: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    tracking_valid: bool
    mean_error: float


@dataclass(frozen=True)
class MotiveFrame:
    frame_number: int
    received_time_ns: int
    motive_timestamp: float
    bodies: dict[int, RigidBodySample]


class MotiveReceiver:
    """Receive NatNet frames and keep the newest complete rigid-body frame."""

    def __init__(
        self,
        plan: MotivePlan,
        frame_callback: Callable[[MotiveFrame], None] | None = None,
    ) -> None:
        self.plan = plan
        self.frame_callback = frame_callback
        self._lock = threading.Lock()
        self._latest: MotiveFrame | None = None
        self.frames_received = 0
        self._client = NatNetClient()
        self._client.set_server_address(plan.server_ip)
        self._client.set_client_address(plan.client_ip)
        self._client.set_use_multicast(plan.use_multicast)
        # Use the complete-frame callback internally so tracking_valid and frame timing
        # are already decoded. The project-level handler name describes our use.
        self._client.new_frame_with_data_listener = self.rigid_body_listener

    def rigid_body_listener(self, frame_data: dict[str, object]) -> None:
        mocap_data = frame_data.get("mocap_data")
        if mocap_data is None or mocap_data.rigid_body_data is None:
            return
        bodies: dict[int, RigidBodySample] = {}
        for rigid_body in mocap_data.rigid_body_data.rigid_body_list:
            body_id = int(rigid_body.id_num)
            bodies[body_id] = RigidBodySample(
                rigid_body_id=body_id,
                name=self.plan.body_names.get(body_id, f"Rigid Body {body_id}"),
                position=tuple(float(value) for value in rigid_body.pos),
                rotation=tuple(float(value) for value in rigid_body.rot),
                tracking_valid=bool(rigid_body.tracking_valid),
                mean_error=float(rigid_body.error),
            )
        frame = MotiveFrame(
            frame_number=int(frame_data.get("frame_number", 0)),
            received_time_ns=time.time_ns(),
            motive_timestamp=float(frame_data.get("timestamp", -1.0)),
            bodies=bodies,
        )
        with self._lock:
            self._latest = frame
            self.frames_received += 1
        if self.frame_callback is not None:
            self.frame_callback(frame)

    def start(self) -> None:
        if not self._client.run():
            raise RuntimeError(
                f"Could not start NatNet client (server={self.plan.server_ip}, client={self.plan.client_ip})"
            )

    def stop(self) -> None:
        self._client.shutdown()

    def latest_frame(self) -> MotiveFrame | None:
        with self._lock:
            return self._latest
