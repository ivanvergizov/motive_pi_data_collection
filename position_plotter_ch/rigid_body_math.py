from __future__ import annotations

import numpy as np


MOTIVE_TO_DISPLAY = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=float,
)


def motive_position_to_display(position_motive: np.ndarray) -> np.ndarray:
    position_motive = np.asarray(position_motive, dtype=float)

    if position_motive.shape != (3,):
        raise ValueError(
            "position_motive must contain exactly three values in X, Y, Z order."
        )

    return MOTIVE_TO_DISPLAY @ position_motive


def motive_positions_to_display(
    x_motive: np.ndarray,
    y_motive: np.ndarray,
    z_motive: np.ndarray,
) -> np.ndarray:
    x_motive = np.asarray(x_motive, dtype=float)
    y_motive = np.asarray(y_motive, dtype=float)
    z_motive = np.asarray(z_motive, dtype=float)

    if not (x_motive.shape == y_motive.shape == z_motive.shape):
        raise ValueError("Position component arrays must have matching shapes.")

    motive_positions = np.column_stack([x_motive, y_motive, z_motive])
    return motive_positions @ MOTIVE_TO_DISPLAY.T


def normalize_quaternion_xyzw(quaternion: np.ndarray) -> np.ndarray:
    quaternion = np.asarray(quaternion, dtype=float)

    if quaternion.shape != (4,):
        raise ValueError("A quaternion must contain exactly four X, Y, Z, W values.")

    norm = float(np.linalg.norm(quaternion))

    if norm == 0.0:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=float)

    return quaternion / norm


def normalize_quaternions_xyzw(quaternions: np.ndarray) -> np.ndarray:
    quaternions = np.asarray(quaternions, dtype=float)

    if quaternions.ndim != 2 or quaternions.shape[1] != 4:
        raise ValueError("quaternions must have shape (N, 4) in X, Y, Z, W order.")

    norms = np.linalg.norm(quaternions, axis=1)
    safe_norms = np.where(norms == 0.0, 1.0, norms)
    normalized = quaternions / safe_norms[:, np.newaxis]

    zero_norm_mask = norms == 0.0
    if np.any(zero_norm_mask):
        normalized[zero_norm_mask] = np.array(
            [0.0, 0.0, 0.0, 1.0],
            dtype=float,
        )

    return normalized


def quaternion_xyzw_to_motive_rotation_matrix(
    qx: float,
    qy: float,
    qz: float,
    qw: float,
) -> np.ndarray:
    qx, qy, qz, qw = normalize_quaternion_xyzw(
        np.array([qx, qy, qz, qw], dtype=float)
    )

    return np.array(
        [
            [
                1.0 - 2.0 * (qy * qy + qz * qz),
                2.0 * (qx * qy - qw * qz),
                2.0 * (qx * qz + qw * qy),
            ],
            [
                2.0 * (qx * qy + qw * qz),
                1.0 - 2.0 * (qx * qx + qz * qz),
                2.0 * (qy * qz - qw * qx),
            ],
            [
                2.0 * (qx * qz - qw * qy),
                2.0 * (qy * qz + qw * qx),
                1.0 - 2.0 * (qx * qx + qy * qy),
            ],
        ],
        dtype=float,
    )


def quaternion_xyzw_to_rotation_matrix(
    qx: float,
    qy: float,
    qz: float,
    qw: float,
) -> np.ndarray:
    rotation_matrix_motive = quaternion_xyzw_to_motive_rotation_matrix(
        qx,
        qy,
        qz,
        qw,
    )

    return MOTIVE_TO_DISPLAY @ rotation_matrix_motive @ MOTIVE_TO_DISPLAY.T


def xyz_degrees_to_quaternions_xyzw(xyz_degrees: np.ndarray) -> np.ndarray:
    """Convert Motive XYZ Euler angles in degrees to X, Y, Z, W quaternions.

    The rotation convention is intrinsic XYZ, equivalent to the active rotation
    matrix Rx(x) @ Ry(y) @ Rz(z). This is the XYZ order used by Motive CSV
    Euler-angle exports.
    """

    xyz_degrees = np.asarray(xyz_degrees, dtype=float)

    if xyz_degrees.ndim != 2 or xyz_degrees.shape[1] != 3:
        raise ValueError("xyz_degrees must have shape (N, 3).")

    half_angles = np.deg2rad(xyz_degrees) * 0.5

    sx = np.sin(half_angles[:, 0])
    cx = np.cos(half_angles[:, 0])
    sy = np.sin(half_angles[:, 1])
    cy = np.cos(half_angles[:, 1])
    sz = np.sin(half_angles[:, 2])
    cz = np.cos(half_angles[:, 2])

    quaternions = np.column_stack(
        [
            sx * cy * cz + cx * sy * sz,
            -sx * cy * sz + cx * sy * cz,
            cx * cy * sz + sx * sy * cz,
            cx * cy * cz - sx * sy * sz,
        ]
    )

    return normalize_quaternions_xyzw(quaternions)


def quaternions_xyzw_to_xyz_degrees(quaternions: np.ndarray) -> np.ndarray:
    """Convert X, Y, Z, W quaternions to Motive XYZ Euler angles in degrees."""

    quaternions = normalize_quaternions_xyzw(quaternions)
    xyz_radians = np.empty((len(quaternions), 3), dtype=float)

    gimbal_lock_tolerance = 1.0e-10

    for index, (qx, qy, qz, qw) in enumerate(quaternions):
        rotation_matrix = quaternion_xyzw_to_motive_rotation_matrix(
            qx,
            qy,
            qz,
            qw,
        )

        sin_y = float(np.clip(rotation_matrix[0, 2], -1.0, 1.0))
        y_angle = float(np.arcsin(sin_y))
        cos_y = float(np.cos(y_angle))

        if abs(cos_y) > gimbal_lock_tolerance:
            x_angle = float(
                np.arctan2(-rotation_matrix[1, 2], rotation_matrix[2, 2])
            )
            z_angle = float(
                np.arctan2(-rotation_matrix[0, 1], rotation_matrix[0, 0])
            )
        else:
            z_angle = 0.0

            if sin_y >= 0.0:
                x_angle = float(
                    np.arctan2(rotation_matrix[1, 0], rotation_matrix[1, 1])
                )
            else:
                x_angle = float(
                    np.arctan2(-rotation_matrix[1, 0], rotation_matrix[1, 1])
                )

        xyz_radians[index] = np.array(
            [x_angle, y_angle, z_angle],
            dtype=float,
        )

    return np.rad2deg(xyz_radians)
