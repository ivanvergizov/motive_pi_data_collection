from __future__ import annotations

import numpy as np

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

    # Normalize every sample together, then calculate only the matrix entries
    # needed for XYZ Euler angles. Zero quaternions still represent identity.
    qx, qy, qz, qw = quaternion_xyzw.T
    norms = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    safe_norms = np.where(norms == 0.0, 1.0, norms)
    qx, qy, qz, qw = (component / safe_norms for component in (qx, qy, qz, qw))

    r00 = 1.0 - 2.0 * (qy * qy + qz * qz)
    r01 = 2.0 * (qx * qy - qw * qz)
    r02 = 2.0 * (qx * qz + qw * qy)
    r10 = 2.0 * (qx * qy + qw * qz)
    r11 = 1.0 - 2.0 * (qx * qx + qz * qz)
    r12 = 2.0 * (qy * qz - qw * qx)
    r22 = 1.0 - 2.0 * (qx * qx + qy * qy)

    sin_y = np.clip(r02, -1.0, 1.0)
    y_angle = np.arcsin(sin_y)
    x_angle = np.arctan2(-r12, r22)
    z_angle = np.arctan2(-r01, r00)

    # At gimbal lock, choose Z = 0 and solve the remaining X rotation.
    gimbal_lock = ~(np.abs(np.cos(y_angle)) > 1.0e-10)
    x_angle[gimbal_lock] = np.arctan2(
        np.where(sin_y[gimbal_lock] >= 0.0, r10[gimbal_lock], -r10[gimbal_lock]),
        r11[gimbal_lock],
    )
    z_angle[gimbal_lock] = 0.0

    return np.rad2deg(np.column_stack([x_angle, y_angle, z_angle]))
