from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from rigid_body_math import (
    quaternion_xyzw_to_xyz_degrees,
    xyz_degrees_to_quaternion_xyzw
)
from signal_processing import fill_missing_values


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
    for column_index, cell_value in enumerate(metadata_row[:-1]):
        if cell_value.strip().casefold() != "rotation type":
            continue

        encoding_value = metadata_row[column_index + 1].strip()

        if encoding_value.casefold() == "xyz":
            return "XYZ"

        if encoding_value.casefold() == "quaternion":
            return "Quaternion"

        raise ValueError(
            "The value after 'Rotation Type' must be "
            f"'XYZ' or 'Quaternion', not {encoding_value!r}."
        )

    raise ValueError(
        "The first CSV row does not contain a 'Rotation Type' cell."
    )


def load_motive_rigid_body_csv(
        csv_path: str | Path) -> TrackingSession:

    csv_path = Path(csv_path)

    if not csv_path.is_file():
        raise FileNotFoundError(
            f"CSV file not found: {csv_path}"
        )

    with csv_path.open(
            "r",
            encoding="utf-8-sig") as file:

        header_lines = [
            file.readline().rstrip("\n")
            for _ in range(7)
        ]

    header_rows = [
        line.split(",")
        for line in header_lines
    ]

    metadata_row = header_rows[0]
    type_row = header_rows[2]
    object_name_row = header_rows[3]
    transform_type_row = header_rows[5]
    dimension_row = header_rows[6]

    source_rotation_encoding = find_rotation_encoding(
        metadata_row
    )

    numeric_data = pd.read_csv(
        csv_path,
        skiprows=7,
        header=None
    ).to_numpy(dtype=float)

    numeric_data = numeric_data[
        ~np.all(np.isnan(numeric_data), axis=1)
    ]

    frames = numeric_data[:, 0]
    time = numeric_data[:, 1]

    rigid_body_columns: dict[
        str,
        dict[str, int]
    ] = {}

    num_columns = len(transform_type_row)

    for column_index in range(2, num_columns):
        data_type = type_row[column_index].strip()
        object_name = object_name_row[column_index].strip()
        transform_type = transform_type_row[column_index].strip()
        dimension = dimension_row[column_index].strip()

        if data_type != "Rigid Body":
            continue

        if transform_type not in {"Rotation", "Position"}:
            continue

        if dimension not in {"X", "Y", "Z", "W"}:
            continue

        if object_name not in rigid_body_columns:
            rigid_body_columns[object_name] = {}

        transform_dimension = (
            transform_type + dimension
        )

        rigid_body_columns[object_name][
            transform_dimension
        ] = column_index

    bodies: dict[str, RigidBodyData] = {}

    for body_name, columns in rigid_body_columns.items():
        required_columns = {
            "RotationX",
            "RotationY",
            "RotationZ",
            "PositionX",
            "PositionY",
            "PositionZ"
        }

        if source_rotation_encoding == "Quaternion":
            required_columns.add("RotationW")

        missing_columns = (
            required_columns - columns.keys()
        )

        if missing_columns:
            missing_text = ", ".join(
                sorted(missing_columns)
            )

            raise ValueError(
                f"Rigid body {body_name!r} is missing "
                f"required columns: {missing_text}."
            )

        body_has_any_samples = any(
            np.any(
                np.isfinite(
                    numeric_data[
                        :,
                        columns[column_name]
                    ]
                )
            )
            for column_name in required_columns
        )

        if not body_has_any_samples:
            continue

        def load_signal(
                column_name: str
        ) -> tuple[np.ndarray, np.ndarray]:

            pre_interpolation_values = numeric_data[
                :,
                columns[column_name]
            ].astype(float, copy=True)

            if not np.any(
                    np.isfinite(
                        pre_interpolation_values
                    )
            ):
                raise ValueError(
                    f"Rigid body {body_name!r} signal "
                    f"{column_name!r} contains no finite "
                    "values."
                )

            interpolated_values = fill_missing_values(
                pre_interpolation_values
            )

            return (
                pre_interpolation_values,
                interpolated_values
            )

        (
            pre_interpolation_position_x,
            position_x
        ) = load_signal("PositionX")

        (
            pre_interpolation_position_y,
            position_y
        ) = load_signal("PositionY")

        (
            pre_interpolation_position_z,
            position_z
        ) = load_signal("PositionZ")

        (
            pre_interpolation_source_rotation_x,
            source_rotation_x
        ) = load_signal("RotationX")

        (
            pre_interpolation_source_rotation_y,
            source_rotation_y
        ) = load_signal("RotationY")

        (
            pre_interpolation_source_rotation_z,
            source_rotation_z
        ) = load_signal("RotationZ")

        if source_rotation_encoding == "Quaternion":
            (
                pre_interpolation_quaternion_w,
                quaternion_w
            ) = load_signal("RotationW")

            pre_interpolation_quaternion_x = (
                pre_interpolation_source_rotation_x
            )
            pre_interpolation_quaternion_y = (
                pre_interpolation_source_rotation_y
            )
            pre_interpolation_quaternion_z = (
                pre_interpolation_source_rotation_z
            )

            quaternion_x = source_rotation_x
            quaternion_y = source_rotation_y
            quaternion_z = source_rotation_z

            pre_interpolation_quaternion_xyzw = (
                np.column_stack(
                    [
                        pre_interpolation_quaternion_x,
                        pre_interpolation_quaternion_y,
                        pre_interpolation_quaternion_z,
                        pre_interpolation_quaternion_w
                    ]
                )
            )

            quaternion_xyzw = np.column_stack(
                [
                    quaternion_x,
                    quaternion_y,
                    quaternion_z,
                    quaternion_w
                ]
            )

            pre_interpolation_rotation_xyz_degrees = (
                quaternion_xyzw_to_xyz_degrees(
                    pre_interpolation_quaternion_xyzw
                )
            )

            rotation_xyz_degrees = (
                quaternion_xyzw_to_xyz_degrees(
                    quaternion_xyzw
                )
            )

            pre_interpolation_rotation_xyz_x = (
                pre_interpolation_rotation_xyz_degrees[
                    :,
                    0
                ]
            )
            pre_interpolation_rotation_xyz_y = (
                pre_interpolation_rotation_xyz_degrees[
                    :,
                    1
                ]
            )
            pre_interpolation_rotation_xyz_z = (
                pre_interpolation_rotation_xyz_degrees[
                    :,
                    2
                ]
            )

            rotation_xyz_x = rotation_xyz_degrees[:, 0]
            rotation_xyz_y = rotation_xyz_degrees[:, 1]
            rotation_xyz_z = rotation_xyz_degrees[:, 2]

        else:
            pre_interpolation_rotation_xyz_x = (
                pre_interpolation_source_rotation_x
            )
            pre_interpolation_rotation_xyz_y = (
                pre_interpolation_source_rotation_y
            )
            pre_interpolation_rotation_xyz_z = (
                pre_interpolation_source_rotation_z
            )

            rotation_xyz_x = source_rotation_x
            rotation_xyz_y = source_rotation_y
            rotation_xyz_z = source_rotation_z

            pre_interpolation_rotation_xyz_degrees = (
                np.column_stack(
                    [
                        pre_interpolation_rotation_xyz_x,
                        pre_interpolation_rotation_xyz_y,
                        pre_interpolation_rotation_xyz_z
                    ]
                )
            )

            rotation_xyz_degrees = np.column_stack(
                [
                    rotation_xyz_x,
                    rotation_xyz_y,
                    rotation_xyz_z
                ]
            )

            pre_interpolation_quaternion_xyzw = (
                xyz_degrees_to_quaternion_xyzw(
                    pre_interpolation_rotation_xyz_degrees
                )
            )

            quaternion_xyzw = (
                xyz_degrees_to_quaternion_xyzw(
                    rotation_xyz_degrees
                )
            )

            pre_interpolation_quaternion_x = (
                pre_interpolation_quaternion_xyzw[:, 0]
            )
            pre_interpolation_quaternion_y = (
                pre_interpolation_quaternion_xyzw[:, 1]
            )
            pre_interpolation_quaternion_z = (
                pre_interpolation_quaternion_xyzw[:, 2]
            )
            pre_interpolation_quaternion_w = (
                pre_interpolation_quaternion_xyzw[:, 3]
            )

            quaternion_x = quaternion_xyzw[:, 0]
            quaternion_y = quaternion_xyzw[:, 1]
            quaternion_z = quaternion_xyzw[:, 2]
            quaternion_w = quaternion_xyzw[:, 3]

        body = RigidBodyData(
            name=body_name,
            rotation_x=quaternion_x,
            rotation_y=quaternion_y,
            rotation_z=quaternion_z,
            rotation_w=quaternion_w,
            rotation_xyz_x=rotation_xyz_x,
            rotation_xyz_y=rotation_xyz_y,
            rotation_xyz_z=rotation_xyz_z,
            position_x=position_x,
            position_y=position_y,
            position_z=position_z,
            pre_interpolation_rotation_x=(
                pre_interpolation_quaternion_x
            ),
            pre_interpolation_rotation_y=(
                pre_interpolation_quaternion_y
            ),
            pre_interpolation_rotation_z=(
                pre_interpolation_quaternion_z
            ),
            pre_interpolation_rotation_w=(
                pre_interpolation_quaternion_w
            ),
            pre_interpolation_rotation_xyz_x=(
                pre_interpolation_rotation_xyz_x
            ),
            pre_interpolation_rotation_xyz_y=(
                pre_interpolation_rotation_xyz_y
            ),
            pre_interpolation_rotation_xyz_z=(
                pre_interpolation_rotation_xyz_z
            ),
            pre_interpolation_position_x=(
                pre_interpolation_position_x
            ),
            pre_interpolation_position_y=(
                pre_interpolation_position_y
            ),
            pre_interpolation_position_z=(
                pre_interpolation_position_z
            )
        )

        bodies[body_name] = body

    return TrackingSession(
        frames=frames,
        time=time,
        bodies=bodies,
        source_rotation_encoding=(
            source_rotation_encoding
        )
    )