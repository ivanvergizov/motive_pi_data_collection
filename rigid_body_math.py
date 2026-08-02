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

def quaternion_xyzw_to_motive_rotation_matrix(
        qx: float,
        qy: float,
        qz: float,
        qw: float) -> np.ndarray:

    norm = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)

    if norm == 0.0:
        return np.eye(3)

    qx = qx / norm
    qy = qy / norm
    qz = qz / norm
    qw = qw / norm

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
        qw: float) -> np.ndarray:

    rotation_matrix_motive = (
        quaternion_xyzw_to_motive_rotation_matrix(
            qx,
            qy,
            qz,
            qw,
        )
    )

    motive_to_display = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=float,
    )

    return (
        motive_to_display
        @ rotation_matrix_motive
        @ motive_to_display.T
    )

def xyz_degrees_to_quaternion_xyzw(
        xyz_degrees: np.ndarray) -> np.ndarray:

    xyz_degrees = np.asarray(xyz_degrees, dtype=float)

    if xyz_degrees.ndim != 2 or xyz_degrees.shape[1] != 3:
        raise ValueError(
            "xyz_degrees must have shape (N, 3)."
        )

    half_angles = np.deg2rad(xyz_degrees) * 0.5

    sin_x = np.sin(half_angles[:, 0])
    cos_x = np.cos(half_angles[:, 0])

    sin_y = np.sin(half_angles[:, 1])
    cos_y = np.cos(half_angles[:, 1])

    sin_z = np.sin(half_angles[:, 2])
    cos_z = np.cos(half_angles[:, 2])

    quaternion_x = (
        sin_x * cos_y * cos_z
        + cos_x * sin_y * sin_z
    )

    quaternion_y = (
        -sin_x * cos_y * sin_z
        + cos_x * sin_y * cos_z
    )

    quaternion_z = (
        cos_x * cos_y * sin_z
        + sin_x * sin_y * cos_z
    )

    quaternion_w = (
        cos_x * cos_y * cos_z
        - sin_x * sin_y * sin_z
    )

    return np.column_stack(
        [
            quaternion_x,
            quaternion_y,
            quaternion_z,
            quaternion_w,
        ]
    )

def quaternion_xyzw_to_xyz_degrees(
        quaternion_xyzw: np.ndarray) -> np.ndarray:

    quaternion_xyzw = np.asarray(
        quaternion_xyzw,
        dtype=float,
    )

    if (
        quaternion_xyzw.ndim != 2
        or quaternion_xyzw.shape[1] != 4
    ):
        raise ValueError(
            "quaternion_xyzw must have shape (N, 4)."
        )

    xyz_radians = np.empty(
        (len(quaternion_xyzw), 3),
        dtype=float,
    )

    gimbal_lock_tolerance = 1.0e-10

    for sample_index, quaternion in enumerate(quaternion_xyzw):
        qx = quaternion[0]
        qy = quaternion[1]
        qz = quaternion[2]
        qw = quaternion[3]

        rotation_matrix = (
            quaternion_xyzw_to_motive_rotation_matrix(
                qx,
                qy,
                qz,
                qw,
            )
        )

        sin_y = np.clip(
            rotation_matrix[0, 2],
            -1.0,
            1.0,
        )

        y_angle = np.arcsin(sin_y)
        cos_y = np.cos(y_angle)

        if abs(cos_y) > gimbal_lock_tolerance:
            x_angle = np.arctan2(
                -rotation_matrix[1, 2],
                rotation_matrix[2, 2],
            )

            z_angle = np.arctan2(
                -rotation_matrix[0, 1],
                rotation_matrix[0, 0],
            )

        else:
            z_angle = 0.0

            if sin_y >= 0.0:
                x_angle = np.arctan2(
                    rotation_matrix[1, 0],
                    rotation_matrix[1, 1],
                )

            else:
                x_angle = np.arctan2(
                    -rotation_matrix[1, 0],
                    rotation_matrix[1, 1],
                )

        xyz_radians[sample_index] = [
            x_angle,
            y_angle,
            z_angle,
        ]

    return np.rad2deg(xyz_radians)