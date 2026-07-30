from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from motive_io import load_motive_rigid_body_csv
from rigid_body_math import (
    quaternions_xyzw_to_xyz_degrees,
    xyz_degrees_to_quaternions_xyzw,
)


def assert_quaternion_orientations_equal(
    first: np.ndarray,
    second: np.ndarray,
    tolerance: float = 1.0e-10,
) -> None:
    alignment = np.abs(np.sum(first * second, axis=1))

    if not np.allclose(alignment, 1.0, atol=tolerance):
        raise AssertionError(
            f"Quaternion orientation mismatch; minimum alignment is {alignment.min()}."
        )


def test_xyz_quaternion_round_trip() -> None:
    random_generator = np.random.default_rng(42)
    xyz_degrees = np.column_stack(
        [
            random_generator.uniform(-170.0, 170.0, 1000),
            random_generator.uniform(-85.0, 85.0, 1000),
            random_generator.uniform(-170.0, 170.0, 1000),
        ]
    )

    quaternions = xyz_degrees_to_quaternions_xyzw(xyz_degrees)
    converted_xyz = quaternions_xyzw_to_xyz_degrees(quaternions)
    converted_quaternions = xyz_degrees_to_quaternions_xyzw(converted_xyz)

    assert_quaternion_orientations_equal(quaternions, converted_quaternions)


def write_synthetic_motive_csv(path: Path, rotation_encoding: str) -> None:
    header_rows = [[""] * 20 for _ in range(7)]
    header_rows[0][19] = rotation_encoding

    if rotation_encoding == "Quaternion":
        columns = [
            ("Rotation", "X"),
            ("Rotation", "Y"),
            ("Rotation", "Z"),
            ("Rotation", "W"),
            ("Position", "X"),
            ("Position", "Y"),
            ("Position", "Z"),
        ]
        numeric_rows = [
            [0, 0.00, 0, 0, 0, 1, 1, 2, 3],
            [1, 0.01, 0, 0, np.sqrt(0.5), np.sqrt(0.5), 2, 3, 4],
        ]
    else:
        columns = [
            ("Rotation", "X"),
            ("Rotation", "Y"),
            ("Rotation", "Z"),
            ("Position", "X"),
            ("Position", "Y"),
            ("Position", "Z"),
        ]
        numeric_rows = [
            [0, 0.00, 0, 0, 0, 1, 2, 3],
            [1, 0.01, 10, 20, 30, 2, 3, 4],
        ]

    for column_index, (transform_type, dimension) in enumerate(columns, start=2):
        header_rows[2][column_index] = "Rigid Body"
        header_rows[3][column_index] = "BodyA"
        header_rows[5][column_index] = transform_type
        header_rows[6][column_index] = dimension

    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerows(header_rows)
        writer.writerows(numeric_rows)


def test_loader_for_both_rotation_encodings() -> None:
    with TemporaryDirectory() as temporary_directory:
        temporary_path = Path(temporary_directory)

        for rotation_encoding in ("Quaternion", "XYZ"):
            csv_path = temporary_path / f"{rotation_encoding}.csv"
            write_synthetic_motive_csv(csv_path, rotation_encoding)

            session = load_motive_rigid_body_csv(csv_path)
            body = session.bodies["BodyA"]

            if session.source_rotation_encoding != rotation_encoding:
                raise AssertionError("Rotation metadata was not read correctly.")

            if body.rotation_quaternion_xyzw.shape != (2, 4):
                raise AssertionError("Quaternion data has the wrong shape.")

            if body.rotation_xyz_degrees.shape != (2, 3):
                raise AssertionError("XYZ data has the wrong shape.")

            quaternion_norms = np.linalg.norm(
                body.rotation_quaternion_xyzw,
                axis=1,
            )

            if not np.allclose(quaternion_norms, 1.0):
                raise AssertionError("Loaded quaternions are not normalized.")


def main() -> None:
    test_xyz_quaternion_round_trip()
    test_loader_for_both_rotation_encodings()
    print("All core tests passed.")


if __name__ == "__main__":
    main()
