from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

SignalDataType = Literal["position", "euler", "quaternion"]
SignalMode = Literal["interpolated", "raw", "smoothed"]
BodyType = Literal["tetrahedron", "raspberry_pi", "tablet", "mobile"]
WorkspaceType = Literal["signals", "recorded_3d", "live", "export"]


@dataclass(frozen=True)
class PlotSignalSelection:
    body_name: str
    signal_label: str


@dataclass(frozen=True)
class CurveSpec:
    data_type: SignalDataType
    name: str
    color: str
    x: np.ndarray
    y: np.ndarray


@dataclass(frozen=True)
class BodyDisplaySettings:
    body_type: BodyType
    color: str = "#e31212"


@dataclass(frozen=True)
class BodyPose:
    position: np.ndarray
    quaternion_xyzw: np.ndarray


@dataclass(frozen=True)
class SceneFrame:
    time_s: float
    sample_time_s: float
    frame_number: int
    poses: dict[str, BodyPose]


@dataclass(frozen=True)
class RoomBounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    x_tick: float
    y_tick: float
    z_tick: float

    def center(self) -> tuple[float, float, float]:
        return (
            (self.x_min + self.x_max) / 2.0,
            (self.y_min + self.y_max) / 2.0,
            (self.z_min + self.z_max) / 2.0,
        )

    def spans(self) -> tuple[float, float, float]:
        return self.x_max - self.x_min, self.y_max - self.y_min, self.z_max - self.z_min

    def as_sequence(self) -> tuple[float, float, float, float, float, float]:
        return self.x_min, self.x_max, self.y_min, self.y_max, self.z_min, self.z_max
