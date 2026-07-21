from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from signal_processing import fill_missing_values

@dataclass
class RigidBodyData:
    name: str

    rotation_x: np.ndarray
    rotation_y: np.ndarray
    rotation_z: np.ndarray
    rotation_w: np.ndarray

    position_x: np.ndarray
    position_y: np.ndarray
    position_z: np.ndarray

@dataclass
class TrackingSession:
    frames: np.ndarray
    time: np.ndarray
    bodies: dict[str, RigidBodyData]

def load_motive_rigid_body_csv(csv_path: str | Path) -> TrackingSession:
    csv_path = Path(csv_path)

    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    with csv_path.open("r", encoding="utf-8-sig") as file:
        header_lines = [file.readline().rstrip("\n") for _ in range(7)]

    header_rows = [line.split(",") for line in header_lines]

    type_row = header_rows[2]
    object_name_row = header_rows[3]
    transform_type_row = header_rows[5]
    dimension_row = header_rows[6]

    numeric_data = pd.read_csv(csv_path, skiprows=7, header=None).to_numpy(dtype=float)
    numeric_data = numeric_data[~np.all(np.isnan(numeric_data), axis=1)]

    frames = numeric_data[:, 0]
    time = numeric_data[:, 1]

    rigid_body_columns: dict[str, dict[str, int]] = {} #{"RigidBody" : {RotationX : 2}}

    num_columns = len(transform_type_row)

    for col in range(2, num_columns):
        data_type = type_row[col].strip()
        object_name = object_name_row[col].strip()
        transform_type = transform_type_row[col].strip()
        dimension = dimension_row[col].strip()
        if data_type != "Rigid Body":
            continue

        if transform_type not in {"Rotation", "Position"}:
            continue

        if dimension not in {"X", "Y", "Z", "W"}:
            continue

        if object_name not in rigid_body_columns:
            rigid_body_columns[object_name] = {}

        transform_dimension = transform_type+dimension
        rigid_body_columns[object_name][transform_dimension] = col

    bodies: dict[str, RigidBodyData] = {}

    for body_name, columns in rigid_body_columns.items():
        body = RigidBodyData(
            name = body_name,
            rotation_x = fill_missing_values(numeric_data[:, columns["RotationX"]]),
            rotation_y = fill_missing_values(numeric_data[:, columns["RotationY"]]),
            rotation_z = fill_missing_values(numeric_data[:, columns["RotationZ"]]),
            rotation_w = fill_missing_values(numeric_data[:, columns["RotationW"]]),
            position_x = fill_missing_values(numeric_data[:, columns["PositionX"]]),
            position_y = fill_missing_values(numeric_data[:, columns["PositionY"]]),
            position_z = fill_missing_values(numeric_data[:, columns["PositionZ"]])
        )

        bodies[body_name] = body

    session = TrackingSession(
        frames = frames,
        time = time,
        bodies = bodies
    )

    return session
