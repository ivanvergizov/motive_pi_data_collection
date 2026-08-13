from __future__ import annotations

from collections import deque
import os
import time

os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from motion_app.core.app_types import BodyDisplaySettings, RoomBounds, SceneFrame
from motion_app.core.constants import parse_preview_aa
from motion_app.rendering.pyvista_helpers import (
    add_body_actors,
    add_body_labels,
    add_room_bounds,
    apply_annotation_viewport_style,
    apply_camera_state,
    camera_state,
    frame_camera,
    sync_interactive_dpi,
    update_body_actors,
    update_body_labels,
)


class PyVistaRigidBodyScene(QWidget):
    def __init__(self, anti_aliasing: str) -> None:
        super().__init__()
        self.anti_aliasing = anti_aliasing
        self.settings: dict[str, BodyDisplaySettings] = {}
        self.actors = {}
        self.labels = {}
        self.room_actor = None
        self.bounds: RoomBounds | None = None
        self.last_frame: SceneFrame | None = None
        self.update_ms: deque[float] = deque(maxlen=240)
        self.update_times: deque[float] = deque(maxlen=240)
        self.render_ms: deque[float] = deque(maxlen=240)
        self.render_times: deque[float] = deque(maxlen=240)
        self._annotation_signature: tuple[int, int, float] | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = self._create_plotter()
        self._layout.addWidget(self.plotter)

    def _create_plotter(self) -> QtInteractor:
        mode, samples = parse_preview_aa(self.anti_aliasing)
        plotter = QtInteractor(
            parent=self,
            multi_samples=samples if mode == "msaa" else 0,
            auto_update=False,
        )
        sync_interactive_dpi(plotter, self)
        plotter.set_background("white")
        plotter.enable_terrain_style(mouse_wheel_zooms=True, shift_pans=True)

        # Preview AA is deliberately renderer-wide.  Bodies, room geometry,
        # axes, and labels all live in this one plotter and receive the same AA.
        if mode == "off":
            plotter.disable_anti_aliasing(all_renderers=True)
        elif mode == "ssaa":
            plotter.enable_anti_aliasing("ssaa", all_renderers=True)
        else:
            # VTK's order-independent translucency pass does not support
            # hardware multisampling.  Bodies are intentionally translucent,
            # so use traditional translucency sorting while MSAA is selected.
            # This lets MSAA cover body faces/edges as well as room geometry.
            plotter.renderer.SetUseOIT(False)
            plotter.enable_anti_aliasing("msaa", multi_samples=samples, all_renderers=True)
        return plotter

    def _sync_annotation_style(self, force: bool = False) -> None:
        """Keep text proportional to the stable Qt viewport and current DPI."""
        dpi, device_pixel_ratio = sync_interactive_dpi(self.plotter, self)
        viewport_height = max(1, self.height())
        signature = (viewport_height, dpi, round(device_pixel_ratio, 4))
        if not force and signature == self._annotation_signature:
            return

        apply_annotation_viewport_style(
            self.plotter,
            self.room_actor,
            self.labels,
            viewport_height_dip=viewport_height,
            device_pixel_ratio=device_pixel_ratio,
        )
        self._annotation_signature = signature

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "plotter"):
            self._sync_annotation_style()

    def configure_bodies(self, settings: dict[str, BodyDisplaySettings]) -> None:
        self._remove_bodies()
        self.settings = dict(settings)
        self.actors = add_body_actors(self.plotter, self.settings)
        self.labels = add_body_labels(self.plotter, self.settings)
        update_body_actors(self.actors, self.last_frame)
        update_body_labels(self.labels, self.settings, self.last_frame)
        self._sync_annotation_style(force=True)

    def set_room_bounds(self, bounds: RoomBounds) -> None:
        self.bounds = bounds
        self.plotter.remove_bounds_axes()
        self.room_actor = add_room_bounds(self.plotter, bounds)
        frame_camera(self.plotter, bounds)
        self._sync_annotation_style(force=True)

    def set_frame(self, frame: SceneFrame | None) -> None:
        start = time.perf_counter()
        self.last_frame = frame
        update_body_actors(self.actors, frame)
        update_body_labels(self.labels, self.settings, frame)
        self.update_ms.append((time.perf_counter() - start) * 1000.0)
        self.update_times.append(time.perf_counter())

    def request_render(self) -> None:
        self._sync_annotation_style()
        start = time.perf_counter()
        self.plotter.render()
        self.render_ms.append((time.perf_counter() - start) * 1000.0)
        self.render_times.append(time.perf_counter())

    def set_anti_aliasing(self, anti_aliasing: str) -> None:
        if anti_aliasing == self.anti_aliasing:
            return

        camera = camera_state(self.plotter)
        old_plotter = self.plotter
        self.anti_aliasing = anti_aliasing
        self.actors = {}
        self.labels = {}
        self.room_actor = None

        # MSAA sample count belongs to the render-window context, so changing
        # preview AA rebuilds one complete scene rather than patching individual
        # actors or render passes in place.
        self._layout.removeWidget(old_plotter)
        self.plotter = self._create_plotter()
        self._layout.addWidget(self.plotter)
        self._annotation_signature = None

        self.actors = add_body_actors(self.plotter, self.settings)
        self.labels = add_body_labels(self.plotter, self.settings)
        if self.bounds is not None:
            self.room_actor = add_room_bounds(self.plotter, self.bounds)
        update_body_actors(self.actors, self.last_frame)
        update_body_labels(self.labels, self.settings, self.last_frame)
        apply_camera_state(self.plotter, camera)
        self._sync_annotation_style(force=True)

        old_plotter.close()
        old_plotter.deleteLater()
        self.reset_metrics()

    def actual_anti_aliasing_text(self) -> str:
        mode, _ = parse_preview_aa(self.anti_aliasing)
        if mode == "ssaa":
            return "SSAA"
        samples = int(self.plotter.render_window.GetMultiSamples())
        return "Off" if samples <= 1 else f"MSAA {samples}x"

    def export_camera_state(self) -> dict:
        return camera_state(self.plotter)

    def reset_metrics(self) -> None:
        self.update_ms.clear()
        self.update_times.clear()
        self.render_ms.clear()
        self.render_times.clear()

    @staticmethod
    def _rate(timestamps) -> float:
        if len(timestamps) < 2:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        return (len(timestamps) - 1) / elapsed if elapsed > 0.0 else 0.0

    def metrics_text(self, target_fps: int, timer_times=None) -> str:
        average_update = sum(self.update_ms) / len(self.update_ms) if self.update_ms else 0.0
        average_render = sum(self.render_ms) / len(self.render_ms) if self.render_ms else 0.0
        lines = [f"Requested render rate: {target_fps} FPS"]
        if timer_times is not None:
            lines.append(f"Render timer callbacks: {self._rate(timer_times):.1f}/s")
        lines.extend([
            f"Scene update: {self._rate(self.update_times):.1f}/s | avg {average_update:.3f} ms",
            f"Completed render: {self._rate(self.render_times):.1f} FPS | avg {average_render:.3f} ms",
        ])

        width = self.plotter.width()
        height = self.plotter.height()
        dpr = self.plotter.devicePixelRatioF()
        vtk_width, vtk_height = self.plotter.render_window.GetSize()
        lines.extend([
            f"Preview: {width}x{height} @ {dpr:.2f}x DPR | VTK {vtk_width}x{vtk_height}",
            f"AA: {self.actual_anti_aliasing_text()}",
        ])
        return "\n".join(lines)

    def shutdown(self) -> None:
        self.plotter.close()

    def _remove_bodies(self) -> None:
        for actor in [*self.actors.values(), *self.labels.values()]:
            self.plotter.remove_actor(actor, render=False)
        self.actors.clear()
        self.labels.clear()
