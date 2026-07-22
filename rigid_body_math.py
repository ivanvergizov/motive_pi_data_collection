from __future__ import annotations

import numpy as np

def motive_position_to_display(position_motive: np.ndarray) -> np.ndarray:
    x_motive = position_motive[0]
    y_motive = position_motive[1]
    z_motive = position_motive[2]

    return np.array([x_motive, z_motive, y_motive], dtype=float)

def motive_positions_to_display(x_motive: np.ndarray,
        y_motive: np.ndarray, z_motive: np.ndarray) -> np.ndarray:
    return np.column_stack([x_motive, z_motive, y_motive])

def quaternion_xyzw_to_rotation_matrix(
        qx: float, qy: float, qz: float, qw: float) -> np.ndarray:

    norm = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)

    if norm == 0:
        return np.eye(3)

    qx = qx / norm
    qy = qy / norm
    qz = qz / norm
    qw = qw / norm

    rotation_matrix_motive = np.array(
        [
            [
                1 - 2 * (qy * qy + qz * qz),
                2 * (qx * qy - qw * qz),
                2 * (qx * qz + qw * qy),
            ],
            [
                2 * (qx * qy + qw * qz),
                1 - 2 * (qx * qx + qz * qz),
                2 * (qy * qz - qw * qx),
            ],
            [
                2 * (qx * qz - qw * qy),
                2 * (qy * qz + qw * qx),
                1 - 2 * (qx * qx + qy * qy),
            ],
        ],
        dtype=float,
    )

    motive_to_display = np.array(
        [
            [1, 0, 0],
            [0, 0, 1],
            [0, 1, 0]
        ],
        dtype=float)

    return motive_to_display @ rotation_matrix_motive @ motive_to_display.T