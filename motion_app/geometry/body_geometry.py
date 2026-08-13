from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motion_app.core.app_types import BodyType


@dataclass(frozen=True)
class BodyDimensions:
    length: float
    width: float
    height: float

    @property
    def max_dimension(self) -> float:
        return max(self.length, self.width, self.height)


_BODY_DIMENSIONS: dict[BodyType, BodyDimensions] = {
    "tetrahedron": BodyDimensions(length=0.09, width=0.065, height=0.025),
    "raspberry_pi": BodyDimensions(length=0.09, width=0.065, height=0.025),
    "tablet": BodyDimensions(length=0.27, width=0.195, height=0.0125),
    "mobile": BodyDimensions(length=0.135, width=0.0975, height=0.0125),
}


def body_dimensions(body_type: BodyType) -> BodyDimensions:
    return _BODY_DIMENSIONS[body_type]


def create_body_geometry(body_type: BodyType) -> tuple[np.ndarray, np.ndarray]:
    dimensions = body_dimensions(body_type)
    length = dimensions.length
    width = dimensions.width
    height = dimensions.height

    if body_type == "tetrahedron":
        nose_x, base_x = length / 2.0, -length / 2.0
        half_width, half_height = width / 2.0, height / 2.0
        vertices = [
            [nose_x, 0.0, 0.0],
            [base_x, -half_width, -half_height],
            [base_x, half_width, -half_height],
            [base_x, 0.0, half_height],
        ]
        faces = [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 2, 3]]
    else:
        x, y, z = length / 2.0, width / 2.0, height / 2.0
        vertices = [
            [-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],
            [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z],
        ]
        faces = [
            [0, 2, 1], [0, 3, 2],
            [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4],
            [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6],
            [3, 0, 4], [3, 4, 7],
        ]

    return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=int)
