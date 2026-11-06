from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pyvista as pv
from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D

from motion_app.core.app_types import BodyDisplaySettings, RoomBounds, SceneFrame
from motion_app.core.rigid_body_math import quaternion_xyzw_to_rotation_matrix
from motion_app.geometry.body_geometry import body_dimensions, create_body_geometry
from motion_app.rendering.scene_style import (
    AXIS_COLOR,
    AXIS_LABEL_OFFSET_DIP_AT_REFERENCE,
    AXIS_TEXT_HEIGHT_DIP_AT_REFERENCE,
    AXIS_TITLE_OFFSET_DIP_AT_REFERENCE,
    BODY_LABEL_FONT_SIZE_PT_AT_REFERENCE,
    BODY_LABEL_OFFSET_DIP_AT_REFERENCE,
    DEFAULT_CAMERA_VIEW_ANGLE,
    GRID_COLOR,
    REFERENCE_DPI,
    REFERENCE_VIEWPORT_HEIGHT_DIP,
    ROOM_VERTICAL_CAMERA_SHIFT_FRACTION,
)


@dataclass
class RoomActors:
    axes: object
    box: object


def sync_interactive_dpi(target, display_widget=None) -> tuple[int, float]:
    """Keep VTK DPI aligned with QtInteractor's device-pixel-ratio model."""
    widget = display_widget if display_widget is not None else target

    window = widget.window() if hasattr(widget, "window") else None
    window_handle = window.windowHandle() if window is not None else None

    dpr_getter = getattr(window_handle, "devicePixelRatio", None)
    if callable(dpr_getter):
        device_pixel_ratio = max(0.01, float(dpr_getter()))
    else:
        dpr_getter = getattr(widget, "devicePixelRatioF", None)
        device_pixel_ratio = max(0.01, float(dpr_getter())) if callable(dpr_getter) else 1.0

    # VTK's Python QVTKRenderWindowInteractor uses 72 DPI as its unscaled
    # reference and multiplies it by Qt's device-pixel ratio on resize. Keep
    # the same value here so monitor changes and annotation updates cannot drift
    # away from the render window's own HiDPI convention.
    dpi = max(1, round(REFERENCE_DPI * device_pixel_ratio))
    if int(target.render_window.GetDPI()) != dpi:
        target.render_window.SetDPI(dpi)
    return dpi, device_pixel_ratio


def export_render_dpi(height: int) -> int:
    """Return a monitor-independent virtual DPI for an exported frame."""
    return max(1, round(REFERENCE_DPI * max(1, height) / REFERENCE_VIEWPORT_HEIGHT_DIP))


def _viewport_scale(
    target,
    viewport_height_dip: float | None,
    device_pixel_ratio: float | None,
) -> tuple[float, float]:
    """Return viewport and device-pixel scales used by annotation actors."""
    if device_pixel_ratio is None:
        # Offscreen export uses REFERENCE_DPI multiplied by its virtual DPR.
        device_pixel_ratio = max(1, int(target.render_window.GetDPI())) / REFERENCE_DPI

    if viewport_height_dip is None:
        physical_height = max(1, int(target.render_window.GetSize()[1]))
        viewport_height_dip = physical_height / max(device_pixel_ratio, 0.01)

    viewport_scale = max(1.0, float(viewport_height_dip)) / REFERENCE_VIEWPORT_HEIGHT_DIP
    return viewport_scale, max(0.01, float(device_pixel_ratio))


def apply_annotation_viewport_style(
    target,
    room_actor,
    labels,
    viewport_height_dip: float | None = None,
    device_pixel_ratio: float | None = None,
) -> None:
    """Scale annotations with viewport size and actual device-pixel density."""
    viewport_scale, device_pixel_ratio = _viewport_scale(
        target,
        viewport_height_dip,
        device_pixel_ratio,
    )
    pixel_scale = viewport_scale * device_pixel_ratio

    if room_actor is not None:
        axes = room_actor.axes
        axes.SetScreenSize(max(1.0, AXIS_TEXT_HEIGHT_DIP_AT_REFERENCE * pixel_scale))
        axes.SetLabelOffset(max(1.0, AXIS_LABEL_OFFSET_DIP_AT_REFERENCE * pixel_scale))
        title_offset = max(1.0, AXIS_TITLE_OFFSET_DIP_AT_REFERENCE * pixel_scale)
        axes.SetTitleOffset((title_offset, title_offset))

    body_font_points = max(1, round(BODY_LABEL_FONT_SIZE_PT_AT_REFERENCE * viewport_scale))
    body_offset = max(1, round(BODY_LABEL_OFFSET_DIP_AT_REFERENCE * pixel_scale))
    for label in labels.values():
        # vtkTextProperty uses points. Render-window DPI converts the point size
        # to physical pixels; viewport_scale keeps its proportion in the view.
        label.GetTextProperty().SetFontSize(body_font_points)
        label.SetDisplayOffset(0, body_offset)


def _default_camera_values(bounds: RoomBounds) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    cx, cy, cz = bounds.center()
    x_span, y_span, z_span = bounds.spans()
    diagonal = max(math.sqrt(x_span * x_span + y_span * y_span + z_span * z_span), 1.0)
    vertical_shift = z_span * ROOM_VERTICAL_CAMERA_SHIFT_FRACTION

    focal_point = (cx, cy, cz - vertical_shift)
    position = (cx + diagonal, cy + diagonal, cz + diagonal * 0.65 - vertical_shift)
    return position, focal_point


def _add_body_label(target, name: str) -> vtkBillboardTextActor3D:
    label = vtkBillboardTextActor3D()
    label.SetInput(name)
    label.SetDisplayOffset(0, round(BODY_LABEL_OFFSET_DIP_AT_REFERENCE))
    label.SetVisibility(False)
    text = label.GetTextProperty()
    text.SetColor(0.08, 0.08, 0.08)
    text.SetFontSize(round(BODY_LABEL_FONT_SIZE_PT_AT_REFERENCE))
    text.SetJustificationToCentered()
    text.SetVerticalJustificationToBottom()
    target.add_actor(label, reset_camera=False, name=f"label:{name}", pickable=False, render=False)
    return label

def add_body_labels(
    target,
    settings: dict[str, BodyDisplaySettings],
) -> dict[str, vtkBillboardTextActor3D]:
    return {name: _add_body_label(target, name) for name in settings}


def add_body_actors(
    plotter,
    settings: dict[str, BodyDisplaySettings],
    line_scale: float = 1.0,
) -> dict[str, pv.Actor]:
    actors: dict[str, pv.Actor] = {}

    for name, setting in settings.items():
        vertices, faces = create_body_geometry(setting.body_type)
        vtk_faces = np.column_stack([np.full(len(faces), 3, dtype=np.int64), faces]).reshape(-1)
        mesh = pv.PolyData(np.asarray(vertices, dtype=float), vtk_faces)

        actor = plotter.add_mesh(
            mesh,
            color=setting.color,
            opacity=0.6,
            show_edges=True,
            edge_color="#262626",
            line_width=line_scale,
            smooth_shading=False,
            reset_camera=False,
            render=False,
            name=f"body:{name}",
        )
        actor.visibility = False
        actor.use_bounds = False
        actors[name] = actor

    return actors


def add_room_bounds(plotter, bounds: RoomBounds, line_scale: float = 1.0) -> RoomActors:
    x_span, y_span, z_span = bounds.spans()
    axes = plotter.show_bounds(
        bounds=list(bounds.as_sequence()),
        grid="back",
        location="outer",
        ticks="both",
        all_edges=False,
        xtitle="X (m)",
        ytitle="Y (m)",
        ztitle="Z (m)",
        n_xlabels=max(2, round(x_span / bounds.x_tick) + 1),
        n_ylabels=max(2, round(y_span / bounds.y_tick) + 1),
        n_zlabels=max(2, round(z_span / bounds.z_tick) + 1),
        color="#4c4c4c",
        bold=False,
        font_size=round(AXIS_TEXT_HEIGHT_DIP_AT_REFERENCE),
        use_3d_text=False,
        render=False,
    )

    for getter in (
        axes.GetXAxesLinesProperty,
        axes.GetYAxesLinesProperty,
        axes.GetZAxesLinesProperty,
    ):
        prop = getter()
        prop.SetColor(*AXIS_COLOR)
        prop.SetLineWidth(1.5 * line_scale)

    for getter in (
        axes.GetXAxesGridlinesProperty,
        axes.GetYAxesGridlinesProperty,
        axes.GetZAxesGridlinesProperty,
    ):
        prop = getter()
        prop.SetColor(*GRID_COLOR)
        prop.SetOpacity(0.55)
        prop.SetLineWidth(line_scale)

    box = plotter.add_mesh(
        pv.Cube(bounds=bounds.as_sequence()),
        style="wireframe",
        color="#4c4c4c",
        line_width=1.5 * line_scale,
        lighting=False,
        reset_camera=False,
        render=False,
        name="room:box",
    )
    box.use_bounds = False
    return RoomActors(axes=axes, box=box)


def set_room_components(room: RoomActors, *, axes: bool, grid: bool, text: bool) -> None:
    actor = room.axes
    room.box.visibility = grid

    for getter in (
        actor.GetXAxesLinesProperty,
        actor.GetYAxesLinesProperty,
        actor.GetZAxesLinesProperty,
    ):
        getter().SetOpacity(1.0 if axes else 0.0)

    for getter in (
        actor.GetXAxesGridlinesProperty,
        actor.GetYAxesGridlinesProperty,
        actor.GetZAxesGridlinesProperty,
    ):
        getter().SetOpacity(0.55 if grid else 0.0)

    for getter in (
        actor.GetXAxesTitleProperty,
        actor.GetYAxesTitleProperty,
        actor.GetZAxesTitleProperty,
        actor.GetXAxesLabelProperty,
        actor.GetYAxesLabelProperty,
        actor.GetZAxesLabelProperty,
    ):
        getter().SetOpacity(1.0 if text else 0.0)

    if not axes:
        actor.XAxisTickVisibilityOff()
        actor.YAxisTickVisibilityOff()
        actor.ZAxisTickVisibilityOff()
        actor.XAxisMinorTickVisibilityOff()
        actor.YAxisMinorTickVisibilityOff()
        actor.ZAxisMinorTickVisibilityOff()


def update_body_actors(actors, frame: SceneFrame | None) -> None:
    for name, actor in actors.items():
        pose = None if frame is None else frame.poses.get(name)
        if pose is None:
            actor.visibility = False
            continue

        transform = np.eye(4, dtype=float)
        transform[:3, :3] = quaternion_xyzw_to_rotation_matrix(*map(float, pose.quaternion_xyzw))
        transform[:3, 3] = np.asarray(pose.position, dtype=float)
        actor.user_matrix = transform
        actor.visibility = True


def update_body_labels(
    labels,
    settings: dict[str, BodyDisplaySettings],
    frame: SceneFrame | None,
) -> None:
    for name, label in labels.items():
        pose = None if frame is None else frame.poses.get(name)
        if pose is None:
            label.SetVisibility(False)
            continue

        label_position = np.asarray(pose.position, dtype=float).copy()
        label_position[2] += max(body_dimensions(settings[name].body_type).max_dimension * 0.75, 0.03)
        label.SetPosition(*map(float, label_position))
        label.SetVisibility(True)


def frame_camera(plotter, bounds: RoomBounds) -> None:
    position, focal_point = _default_camera_values(bounds)
    plotter.camera.focal_point = focal_point
    plotter.camera.position = position
    plotter.camera.up = (0.0, 0.0, 1.0)
    plotter.camera.view_angle = DEFAULT_CAMERA_VIEW_ANGLE
    plotter.camera.SetWindowCenter(0.0, 0.0)
    plotter.camera.reset_clipping_range()


def camera_state(plotter) -> dict:
    camera = plotter.camera
    return {
        "position": list(map(float, camera.position)),
        "focal_point": list(map(float, camera.focal_point)),
        "up": list(map(float, camera.up)),
        "view_angle": float(camera.view_angle),
    }


def apply_camera_state(plotter, state: dict) -> None:
    plotter.camera.position = tuple(state["position"])
    plotter.camera.focal_point = tuple(state["focal_point"])
    plotter.camera.up = tuple(state["up"])
    plotter.camera.view_angle = float(state["view_angle"])
    plotter.camera.SetWindowCenter(0.0, 0.0)
    plotter.camera.reset_clipping_range()
