from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from motion_app.core.rigid_body_math import quaternion_xyzw_to_xyz_degrees, xyz_degrees_to_quaternion_xyzw
from motion_app.core.signal_processing import fill_missing_values


@dataclass
class RigidBodyData:
    name: str
    rotation_x: np.ndarray
    rotation_y: np.ndarray
    rotation_z: np.ndarray
    rotation_w: np.ndarray
    rotation_xyz_x: np.ndarray
    rotation_xyz_y: np.ndarray
    rotation_xyz_z: np.ndarray
    position_x: np.ndarray
    position_y: np.ndarray
    position_z: np.ndarray
    pre_interpolation_rotation_x: np.ndarray
    pre_interpolation_rotation_y: np.ndarray
    pre_interpolation_rotation_z: np.ndarray
    pre_interpolation_rotation_w: np.ndarray
    pre_interpolation_rotation_xyz_x: np.ndarray
    pre_interpolation_rotation_xyz_y: np.ndarray
    pre_interpolation_rotation_xyz_z: np.ndarray
    pre_interpolation_position_x: np.ndarray
    pre_interpolation_position_y: np.ndarray
    pre_interpolation_position_z: np.ndarray


@dataclass
class TrackingSession:
    frames: np.ndarray
    time: np.ndarray
    bodies: dict[str, RigidBodyData]
    source_rotation_encoding: str


def find_rotation_encoding(metadata_row: list[str]) -> str:
    for index, value in enumerate(metadata_row[:-1]):
        if value.strip().casefold() != "rotation type":
            continue
        encoding = metadata_row[index + 1].strip()
        if encoding.casefold() == "xyz":
            return "XYZ"
        if encoding.casefold() == "quaternion":
            return "Quaternion"
        raise ValueError(f"Rotation Type must be 'XYZ' or 'Quaternion', not {encoding!r}.")
    raise ValueError("The first CSV row does not contain a 'Rotation Type' cell.")


def load_motive_rigid_body_csv(csv_path: str | Path) -> TrackingSession:
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig") as file:
        header_rows = [file.readline().rstrip("\n").split(",") for _ in range(7)]

    metadata_row = header_rows[0]
    type_row = header_rows[2]
    object_name_row = header_rows[3]
    transform_type_row = header_rows[5]
    dimension_row = header_rows[6]
    source_rotation_encoding = find_rotation_encoding(metadata_row)

    numeric_data = pd.read_csv(csv_path, skiprows=7, header=None).to_numpy(dtype=float)
    numeric_data = numeric_data[~np.all(np.isnan(numeric_data), axis=1)]
    frames = numeric_data[:, 0]
    time = numeric_data[:, 1]

    body_columns: dict[str, dict[str, int]] = {}
    for column in range(2, len(transform_type_row)):
        if type_row[column].strip() != "Rigid Body":
            continue
        transform = transform_type_row[column].strip()
        dimension = dimension_row[column].strip()
        if transform not in {"Rotation", "Position"} or dimension not in {"X", "Y", "Z", "W"}:
            continue
        body_name = object_name_row[column].strip()
        body_columns.setdefault(body_name, {})[transform + dimension] = column

    bodies: dict[str, RigidBodyData] = {}
    for body_name, columns in body_columns.items():
        required = {"RotationX", "RotationY", "RotationZ", "PositionX", "PositionY", "PositionZ"}
        if source_rotation_encoding == "Quaternion":
            required.add("RotationW")

        missing = required - columns.keys()
        if missing:
            raise ValueError(f"Rigid body {body_name!r} is missing required columns: {', '.join(sorted(missing))}.")

        if not any(np.any(np.isfinite(numeric_data[:, columns[name]])) for name in required):
            continue

        def load_signal(name: str) -> tuple[np.ndarray, np.ndarray]:
            raw = numeric_data[:, columns[name]].astype(float, copy=True)
            if not np.any(np.isfinite(raw)):
                raise ValueError(f"Rigid body {body_name!r} signal {name!r} contains no finite values.")
            return raw, fill_missing_values(raw)

        raw_px, px = load_signal("PositionX")
        raw_py, py = load_signal("PositionY")
        raw_pz, pz = load_signal("PositionZ")
        raw_rx, rx = load_signal("RotationX")
        raw_ry, ry = load_signal("RotationY")
        raw_rz, rz = load_signal("RotationZ")

        source_euler_raw = np.column_stack([raw_rx, raw_ry, raw_rz])
        source_euler = np.column_stack([rx, ry, rz])

        if source_rotation_encoding == "Quaternion":
            raw_rw, rw = load_signal("RotationW")
            quaternion_raw = np.column_stack([raw_rx, raw_ry, raw_rz, raw_rw])
            quaternion = np.column_stack([rx, ry, rz, rw])
            euler_raw = quaternion_xyzw_to_xyz_degrees(quaternion_raw)
            euler = quaternion_xyzw_to_xyz_degrees(quaternion)
        else:
            euler_raw = source_euler_raw
            euler = source_euler
            quaternion_raw = xyz_degrees_to_quaternion_xyzw(euler_raw)
            quaternion = xyz_degrees_to_quaternion_xyzw(euler)

        bodies[body_name] = RigidBodyData(
            name=body_name,
            rotation_x=quaternion[:, 0],
            rotation_y=quaternion[:, 1],
            rotation_z=quaternion[:, 2],
            rotation_w=quaternion[:, 3],
            rotation_xyz_x=euler[:, 0],
            rotation_xyz_y=euler[:, 1],
            rotation_xyz_z=euler[:, 2],
            position_x=px,
            position_y=py,
            position_z=pz,
            pre_interpolation_rotation_x=quaternion_raw[:, 0],
            pre_interpolation_rotation_y=quaternion_raw[:, 1],
            pre_interpolation_rotation_z=quaternion_raw[:, 2],
            pre_interpolation_rotation_w=quaternion_raw[:, 3],
            pre_interpolation_rotation_xyz_x=euler_raw[:, 0],
            pre_interpolation_rotation_xyz_y=euler_raw[:, 1],
            pre_interpolation_rotation_xyz_z=euler_raw[:, 2],
            pre_interpolation_position_x=raw_px,
            pre_interpolation_position_y=raw_py,
            pre_interpolation_position_z=raw_pz,
        )

    return TrackingSession(
        frames=frames,
        time=time,
        bodies=bodies,
        source_rotation_encoding=source_rotation_encoding,
    )
