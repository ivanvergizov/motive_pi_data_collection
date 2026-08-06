from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from rigid_body_math import (
    normalize_quaternions_xyzw,
    quaternions_xyzw_to_xyz_degrees,
    xyz_degrees_to_quaternions_xyzw,
)
from signal_processing import fill_missing_values


RotationEncoding = Literal["Quaternion", "XYZ"]

CSV_HEADER_ROW_COUNT = 7
ROTATION_METADATA_LABEL = "Rotation Type"


@dataclass
class RigidBodyData:
    name: str
    rotation_quaternion_xyzw: np.ndarray
    rotation_xyz_degrees: np.ndarray
    position_x: np.ndarray
    position_y: np.ndarray
    position_z: np.ndarray


@dataclass
class TrackingSession:
    frames: np.ndarray
    time: np.ndarray
    bodies: dict[str, RigidBodyData]
    source_rotation_encoding: RotationEncoding


def parse_rotation_encoding(metadata_value: str) -> RotationEncoding:
    normalized_value = metadata_value.strip().lower()

    if "quaternion" in normalized_value:
        return "Quaternion"

    if normalized_value == "xyz" or "euler" in normalized_value:
        return "XYZ"

    raise ValueError(
        "The CSV rotation metadata must identify either Quaternion or XYZ, "
        f"but it contains {metadata_value!r}."
    )


def _metadata_value_after_label(
    metadata_row: list[str],
    label: str,
) -> str:
    normalized_label = label.strip().casefold()

    for column_index, cell_value in enumerate(metadata_row[:-1]):
        if cell_value.strip().casefold() != normalized_label:
            continue

        metadata_value = metadata_row[column_index + 1].strip()

        if not metadata_value:
            raise ValueError(
                f"The cell after {label!r} in the first CSV row is empty."
            )

        return metadata_value

    raise ValueError(
        f"The first CSV row does not contain the metadata label {label!r}."
    )


def _read_header_rows(csv_path: Path) -> list[list[str]]:
    header_rows: list[list[str]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)

        for row_index in range(CSV_HEADER_ROW_COUNT):
            row = next(reader, None)

            if row is None:
                raise ValueError(
                    f"CSV ended before header row {row_index + 1}; "
                    f"expected {CSV_HEADER_ROW_COUNT} header rows."
                )

            header_rows.append(row)

    return header_rows


def _require_columns(
    body_name: str,
    columns: dict[str, int],
    required_columns: set[str],
) -> None:
    missing_columns = sorted(required_columns - columns.keys())

    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(
            f"Rigid body {body_name!r} is missing required CSV columns: "
            f"{missing_text}."
        )


def load_motive_rigid_body_csv(csv_path: str | Path) -> TrackingSession:
    csv_path = Path(csv_path)

    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    header_rows = _read_header_rows(csv_path)

    metadata_row = header_rows[0]
    rotation_metadata_value = _metadata_value_after_label(
        metadata_row,
        ROTATION_METADATA_LABEL,
    )
    source_rotation_encoding = parse_rotation_encoding(rotation_metadata_value)

    type_row = header_rows[2]
    object_name_row = header_rows[3]
    transform_type_row = header_rows[5]
    dimension_row = header_rows[6]

    numeric_frame = pd.read_csv(
        csv_path,
        skiprows=CSV_HEADER_ROW_COUNT,
        header=None,
    )

    if numeric_frame.empty:
        raise ValueError("CSV contains no numeric tracking rows.")

    numeric_data = numeric_frame.apply(pd.to_numeric, errors="coerce").to_numpy(
        dtype=float
    )
    numeric_data = numeric_data[~np.all(np.isnan(numeric_data), axis=1)]

    if len(numeric_data) == 0:
        raise ValueError("CSV contains no usable numeric tracking rows.")

    if numeric_data.shape[1] < 2:
        raise ValueError("CSV numeric data must include frame and time columns.")

    frames = numeric_data[:, 0]
    time = numeric_data[:, 1]

    if not np.all(np.isfinite(frames)):
        raise ValueError("Frame numbers must all be finite.")

    if not np.all(np.isfinite(time)):
        raise ValueError("Time samples must all be finite.")

    if len(time) > 1 and np.any(np.diff(time) < 0.0):
        raise ValueError("Time samples must be in nondecreasing order.")

    rigid_body_columns: dict[str, dict[str, int]] = {}

    num_columns = min(
        len(type_row),
        len(object_name_row),
        len(transform_type_row),
        len(dimension_row),
        numeric_data.shape[1],
    )

    for column_index in range(2, num_columns):
        data_type = type_row[column_index].strip()
        object_name = object_name_row[column_index].strip()
        transform_type = transform_type_row[column_index].strip()
        dimension = dimension_row[column_index].strip().upper()

        if data_type != "Rigid Body" or not object_name:
            continue

        if transform_type not in {"Rotation", "Position"}:
            continue

        if dimension not in {"X", "Y", "Z", "W"}:
            continue

        rigid_body_columns.setdefault(object_name, {})[
            f"{transform_type}{dimension}"
        ] = column_index

    if not rigid_body_columns:
        raise ValueError("No rigid-body position or rotation columns were found.")

    bodies: dict[str, RigidBodyData] = {}

    position_columns = {"PositionX", "PositionY", "PositionZ"}
    xyz_rotation_columns = {"RotationX", "RotationY", "RotationZ"}

    for body_name, columns in rigid_body_columns.items():
        required_columns = position_columns | xyz_rotation_columns

        if source_rotation_encoding == "Quaternion":
            required_columns = required_columns | {"RotationW"}

        _require_columns(body_name, columns, required_columns)

        body_has_any_samples = any(
            np.any(np.isfinite(numeric_data[:, columns[column_name]]))
            for column_name in required_columns
        )

        if not body_has_any_samples:
            continue

        def filled_signal(column_name: str) -> np.ndarray:
            signal_values = numeric_data[:, columns[column_name]]

            if not np.any(np.isfinite(signal_values)):
                raise ValueError(
                    f"Rigid body {body_name!r} signal {column_name!r} "
                    "contains no finite samples."
                )

            return fill_missing_values(signal_values)

        position_x = filled_signal("PositionX")
        position_y = filled_signal("PositionY")
        position_z = filled_signal("PositionZ")

        rotation_xyz_source = np.column_stack(
            [
                filled_signal("RotationX"),
                filled_signal("RotationY"),
                filled_signal("RotationZ"),
            ]
        )

        if source_rotation_encoding == "Quaternion":
            rotation_quaternion_xyzw = np.column_stack(
                [
                    rotation_xyz_source[:, 0],
                    rotation_xyz_source[:, 1],
                    rotation_xyz_source[:, 2],
                    filled_signal("RotationW"),
                ]
            )
            rotation_quaternion_xyzw = normalize_quaternions_xyzw(
                rotation_quaternion_xyzw
            )
            rotation_xyz_degrees = quaternions_xyzw_to_xyz_degrees(
                rotation_quaternion_xyzw
            )
        else:
            rotation_xyz_degrees = rotation_xyz_source
            rotation_quaternion_xyzw = xyz_degrees_to_quaternions_xyzw(
                rotation_xyz_degrees
            )

        bodies[body_name] = RigidBodyData(
            name=body_name,
            rotation_quaternion_xyzw=rotation_quaternion_xyzw,
            rotation_xyz_degrees=rotation_xyz_degrees,
            position_x=position_x,
            position_y=position_y,
            position_z=position_z,
        )

    if not bodies:
        raise ValueError(
            "Rigid-body columns were found, but no rigid body contains tracking samples."
        )

    return TrackingSession(
        frames=frames,
        time=time,
        bodies=bodies,
        source_rotation_encoding=source_rotation_encoding,
    )
