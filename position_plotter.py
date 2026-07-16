#%%

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import Qt
from Pyside6.QtWidgets import(
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget
)

import pyqtgraph as pg

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

def unique_stable(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []

    for value in values:
        value = value.strip()

        if value == "":
            continue

        if value not in seen:
            seen.add(value)
            output.append(value)

    return output

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

        frames = numeric_data[:,0]
        time = numeric_data[:,1]

        rigid_body_columns: dict[str, dict[tuple[str, str], int]] = {}

        num_columns = len(transform_type_row)

        for col in range(2,num_columns):
            data_type = type_row[col].strip()
            object_name = object_name_row[col].strip()
            transform_type = transform_type_row[col].strip()
            dimension = dimension_row[col].strip()
            if data_type != "Rigid Body":
                continue

            if object_name == "":
                continue

            if transform_type not in {"Rotation", "Position"}:
                continue

            if dimension not in {"X", "Y", "Z", "W"}:
                continue

            if object_name not in rigid_body_columns:
                rigid_body_columns[object_name] = {}

            rigid_body_columns[object_name][(transform_type, dimension)] = col

            
