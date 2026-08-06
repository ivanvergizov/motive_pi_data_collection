from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl

from rigid_body_math import quaternion_xyzw_to_rotation_matrix


BODY_SHAPES = {"tetra", "rect"}


def create_tetra_vertices(
    length: float = 0.09,
    width: float = 0.065,
    height: float = 0.025,
) -> np.ndarray:
    nose_x = length / 2.0
    base_x = -length / 2.0
    half_width = width / 2.0
    half_height = height / 2.0

    return np.array(
        [
            [nose_x, 0.0, 0.0],
            [base_x, -half_width, -half_height],
            [base_x, half_width, -half_height],
            [base_x, 0.0, half_height],
        ],
        dtype=float,
    )


def create_tetra_faces() -> np.ndarray:
    return np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
            [0, 3, 1],
            [1, 2, 3],
        ],
        dtype=int,
    )


def create_rect_vertices(
    length: float = 0.09,
    width: float = 0.065,
    height: float = 0.025,
) -> np.ndarray:
    half_length = length / 2.0
    half_width = width / 2.0
    half_height = height / 2.0

    return np.array(
        [
            [-half_length, -half_width, -half_height],
            [half_length, -half_width, -half_height],
            [half_length, half_width, -half_height],
            [-half_length, half_width, -half_height],
            [-half_length, -half_width, half_height],
            [half_length, -half_width, half_height],
            [half_length, half_width, half_height],
            [-half_length, half_width, half_height],
        ],
        dtype=float,
    )


def create_rect_faces() -> np.ndarray:
    return np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [1, 5, 6],
            [1, 6, 2],
            [2, 6, 7],
            [2, 7, 3],
            [3, 7, 4],
            [3, 4, 0],
        ],
        dtype=int,
    )


def create_body_vertices(
    shape: str = "tetra",
    length: float = 0.09,
    width: float = 0.065,
    height: float = 0.025,
) -> np.ndarray:
    if length <= 0.0 or width <= 0.0 or height <= 0.0:
        raise ValueError("Body dimensions must all be positive.")

    if shape == "tetra":
        return create_tetra_vertices(
            length=length,
            width=width,
            height=height,
        )

    if shape == "rect":
        return create_rect_vertices(
            length=length,
            width=width,
            height=height,
        )

    raise ValueError(f"Unknown body shape: {shape}")


def create_body_faces(shape: str = "tetra") -> np.ndarray:
    if shape == "tetra":
        return create_tetra_faces()

    if shape == "rect":
        return create_rect_faces()

    raise ValueError(f"Unknown body shape: {shape}")


def transform_body_vertices(
    base_vertices: np.ndarray,
    position_transform: np.ndarray,
    qx: float,
    qy: float,
    qz: float,
    qw: float,
) -> np.ndarray:
    base_vertices = np.asarray(base_vertices, dtype=float)
    position_transform = np.asarray(position_transform, dtype=float)

    if base_vertices.ndim != 2 or base_vertices.shape[1] != 3:
        raise ValueError("base_vertices must have shape (N, 3).")

    if position_transform.shape != (3,):
        raise ValueError("position_transform must contain exactly three values.")

    rotation_matrix = quaternion_xyzw_to_rotation_matrix(qx, qy, qz, qw)
    return base_vertices @ rotation_matrix.T + position_transform


def make_gl_color(
    hex_color: str,
    alpha: float = 1.0,
) -> tuple[float, float, float, float]:
    normalized_color = hex_color.lstrip("#")

    if len(normalized_color) != 6:
        raise ValueError("A GL color must use a six-digit hexadecimal string.")

    red = int(normalized_color[0:2], 16) / 255.0
    green = int(normalized_color[2:4], 16) / 255.0
    blue = int(normalized_color[4:6], 16) / 255.0

    return red, green, blue, alpha


def make_body_mesh_item(
    vertices: np.ndarray,
    color: str,
    shape: str = "tetra",
) -> gl.GLMeshItem:
    mesh_data = gl.MeshData(
        vertexes=vertices,
        faces=create_body_faces(shape),
    )

    return gl.GLMeshItem(
        meshdata=mesh_data,
        color=make_gl_color(color, alpha=0.7),
        smooth=False,
        computeNormals=False,
        drawEdges=True,
        edgeColor=(0.0, 0.0, 0.0, 1.0),
    )


def update_body_mesh_item(
    mesh_item: gl.GLMeshItem,
    vertices: np.ndarray,
    shape: str = "tetra",
) -> None:
    mesh_item.setMeshData(
        vertexes=np.asarray(vertices, dtype=float),
        faces=create_body_faces(shape),
    )
