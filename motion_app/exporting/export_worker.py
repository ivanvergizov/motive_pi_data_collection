from __future__ import annotations

import argparse
from collections import deque
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
from queue import Full, Queue
import threading
import time
import traceback

import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader
from OpenGL.raw.GL.VERSION.GL_1_1 import glReadPixels as raw_glReadPixels
import pyvista as pv

from motion_app.core.motive_io import load_motive_rigid_body_csv
from motion_app.rendering.pyvista_helpers import (
    add_body_actors,
    add_body_labels,
    add_room_bounds,
    apply_camera_state,
    frame_camera,
    set_room_components,
    apply_annotation_viewport_style,
    export_render_dpi,
    update_body_actors,
    update_body_labels,
)
from motion_app.core.tracking_data import TrackingDataProvider, nearest_sample_index
from motion_app.exporting.video_export import (
    VideoEncodingSettings,
    export_frame_count,
    finalize_ffmpeg,
    start_ffmpeg,
    validate_ffmpeg,
    write_frame_bytes,
)


class EventEmitter:
    def __init__(self) -> None:
        self.lock = threading.Lock()

    def emit(self, event_type: str, **fields) -> None:
        line = json.dumps({"type": event_type, **fields}, ensure_ascii=False)
        with self.lock:
            print(line, flush=True)


class WindowsExecutionState:
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __enter__(self):
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(
                self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED
            )
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)


VERTEX_SHADER = r"""
#version 330 core
void main()
{
    vec2 position;
    if (gl_VertexID == 0)
        position = vec2(-1.0, -1.0);
    else if (gl_VertexID == 1)
        position = vec2(3.0, -1.0);
    else
        position = vec2(-1.0, 3.0);
    gl_Position = vec4(position, 0.0, 1.0);
}
"""


class GpuGeometryResolve:
    """Resolve SSAA to one final-size texture and synchronize within the geometry context."""

    FRAGMENT_SHADER = r"""
#version 330 core
uniform sampler2D source_texture;
uniform int factor;
out vec4 output_color;

void main()
{
    ivec2 base_pixel = ivec2(gl_FragCoord.xy) * factor;
    vec3 sum = vec3(0.0);

    for (int y = 0; y < 4; ++y)
    {
        for (int x = 0; x < 4; ++x)
        {
            if (x < factor && y < factor)
                sum += texelFetch(source_texture, base_pixel + ivec2(x, y), 0).rgb;
        }
    }

    output_color = vec4(sum / float(factor * factor), 1.0);
}
"""

    def __init__(self, render_window, width: int, height: int, factor: int) -> None:
        if factor not in (1, 2, 3, 4):
            raise ValueError("GPU SSAA resolve supports factors 1x through 4x.")

        self.render_window = render_window
        self.width = width
        self.height = height
        self.factor = factor

        render_window.MakeCurrent()
        state = render_window.GetState()
        state.Reset()
        state.Push()
        try:
            self.texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
            GL.glTexImage2D(
                GL.GL_TEXTURE_2D,
                0,
                GL.GL_RGBA8,
                width,
                height,
                0,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                None,
            )
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)

            self.framebuffer = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
            GL.glFramebufferTexture2D(
                GL.GL_FRAMEBUFFER,
                GL.GL_COLOR_ATTACHMENT0,
                GL.GL_TEXTURE_2D,
                self.texture,
                0,
            )
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("The GPU geometry resolve framebuffer is incomplete.")

            self.program = compileProgram(
                compileShader(VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                compileShader(self.FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER),
            )
            self.vao = GL.glGenVertexArrays(1)
        finally:
            state.Pop()

    def resolve(self) -> None:
        render_window = self.render_window
        render_window.MakeCurrent()
        source_texture = render_window.GetDisplayFramebuffer().GetColorAttachmentAsTextureObject(0)
        if source_texture is None or not source_texture.GetHandle():
            raise RuntimeError("VTK did not expose the rendered geometry color texture.")

        state = render_window.GetState()
        state.Reset()
        state.Push()
        try:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
            GL.glDrawBuffer(GL.GL_COLOR_ATTACHMENT0)
            GL.glViewport(0, 0, self.width, self.height)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glDisable(GL.GL_BLEND)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            GL.glDisable(GL.GL_CULL_FACE)
            if hasattr(GL, "GL_FRAMEBUFFER_SRGB"):
                GL.glDisable(GL.GL_FRAMEBUFFER_SRGB)

            GL.glUseProgram(self.program)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "source_texture"), 0)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "factor"), self.factor)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, source_texture.GetHandle())
            GL.glBindVertexArray(self.vao)

            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
            # The next stage runs in a separate VTK/WGL context. Complete the
            # resolve locally instead of passing a GLsync object across contexts.
            GL.glFinish()
        finally:
            state.Pop()

    def close(self) -> None:
        self.render_window.MakeCurrent()
        GL.glFinish()
        state = self.render_window.GetState()
        state.Reset()
        state.Push()
        try:
            GL.glDeleteVertexArrays(1, [self.vao])
            GL.glDeleteProgram(self.program)
            GL.glDeleteFramebuffers(1, [self.framebuffer])
            GL.glDeleteTextures(1, [self.texture])
        finally:
            state.Pop()


@dataclass
class _ReadbackSlot:
    pbo: int
    frame_number: int = 0
    fence: object | None = None


class AsyncGpuCompositor:
    """Composite on the GPU and asynchronously read final RGB frames through a PBO ring."""

    FRAGMENT_SHADER = r"""
#version 330 core
uniform sampler2D geometry_texture;
uniform sampler2D annotation_texture;
uniform int image_height;
out vec4 output_color;

void main()
{
    ivec2 output_pixel = ivec2(gl_FragCoord.xy);
    ivec2 source_pixel = ivec2(output_pixel.x, image_height - 1 - output_pixel.y);
    vec3 geometry = texelFetch(geometry_texture, source_pixel, 0).rgb;
    vec3 annotation = texelFetch(annotation_texture, source_pixel, 0).rgb;
    output_color = vec4(min(geometry, annotation), 1.0);
}
"""

    def __init__(
        self,
        render_window,
        geometry_texture: int,
        width: int,
        height: int,
        slot_count: int = 3,
    ) -> None:
        self.render_window = render_window
        self.geometry_texture = int(geometry_texture)
        self.width = width
        self.height = height
        self.byte_count = width * height * 3
        self.pending: deque[_ReadbackSlot] = deque()

        render_window.MakeCurrent()
        state = render_window.GetState()
        state.Reset()
        state.Push()
        try:
            self.output_texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.output_texture)
            GL.glTexImage2D(
                GL.GL_TEXTURE_2D,
                0,
                GL.GL_RGBA8,
                width,
                height,
                0,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                None,
            )
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)

            self.framebuffer = GL.glGenFramebuffers(1)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
            GL.glFramebufferTexture2D(
                GL.GL_FRAMEBUFFER,
                GL.GL_COLOR_ATTACHMENT0,
                GL.GL_TEXTURE_2D,
                self.output_texture,
                0,
            )
            if GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("The GPU composite framebuffer is incomplete.")

            self.program = compileProgram(
                compileShader(VERTEX_SHADER, GL.GL_VERTEX_SHADER),
                compileShader(self.FRAGMENT_SHADER, GL.GL_FRAGMENT_SHADER),
            )
            self.vao = GL.glGenVertexArrays(1)

            generated = GL.glGenBuffers(slot_count)
            if slot_count == 1:
                pbo_ids = [int(generated)]
            else:
                pbo_ids = [int(value) for value in generated]

            self.free_slots = deque(_ReadbackSlot(pbo) for pbo in pbo_ids)
            for slot in self.free_slots:
                GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, slot.pbo)
                GL.glBufferData(
                    GL.GL_PIXEL_PACK_BUFFER,
                    self.byte_count,
                    None,
                    GL.GL_STREAM_READ,
                )
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
        finally:
            state.Pop()

    @staticmethod
    def _pointer_address(mapped) -> int:
        if isinstance(mapped, int):
            return mapped
        value = getattr(mapped, "value", None)
        if value is not None:
            return int(value)
        address = ctypes.cast(mapped, ctypes.c_void_p).value
        if address is None:
            raise RuntimeError("OpenGL returned a null PBO mapping.")
        return int(address)

    def _wait_for_slot(self, slot: _ReadbackSlot, block: bool) -> bool:
        flags = GL.GL_SYNC_FLUSH_COMMANDS_BIT if block else 0
        timeout = 100_000_000 if block else 0

        while True:
            status = GL.glClientWaitSync(slot.fence, flags, timeout)
            if status in (GL.GL_ALREADY_SIGNALED, GL.GL_CONDITION_SATISFIED):
                return True
            if status == GL.GL_WAIT_FAILED:
                raise RuntimeError("OpenGL failed while waiting for asynchronous frame readback.")
            if not block:
                return False
            flags = 0

    def _collect_oldest(self, block: bool) -> tuple[int, np.ndarray] | None:
        if not self.pending:
            return None

        self.render_window.MakeCurrent()
        slot = self.pending[0]
        if not self._wait_for_slot(slot, block):
            return None

        GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, slot.pbo)
        mapped = GL.glMapBufferRange(
            GL.GL_PIXEL_PACK_BUFFER,
            0,
            self.byte_count,
            GL.GL_MAP_READ_BIT,
        )
        if not mapped:
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
            raise RuntimeError("OpenGL could not map the completed PBO readback.")

        image = np.empty((self.height, self.width, 3), dtype=np.uint8)
        ctypes.memmove(image.ctypes.data, self._pointer_address(mapped), self.byte_count)
        if not GL.glUnmapBuffer(GL.GL_PIXEL_PACK_BUFFER):
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
            raise RuntimeError("OpenGL reported corrupted PBO data while unmapping.")
        GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
        GL.glDeleteSync(slot.fence)

        self.pending.popleft()
        frame_number = slot.frame_number
        slot.frame_number = 0
        slot.fence = None
        self.free_slots.append(slot)
        return frame_number, image

    def collect_ready(self) -> list[tuple[int, np.ndarray]]:
        completed = []
        while True:
            item = self._collect_oldest(block=False)
            if item is None:
                return completed
            completed.append(item)

    def submit(self, frame_number: int) -> list[tuple[int, np.ndarray]]:
        completed = []
        if not self.free_slots:
            completed.append(self._collect_oldest(block=True))

        slot = self.free_slots.popleft()
        self.render_window.MakeCurrent()
        annotation_texture = (
            self.render_window.GetDisplayFramebuffer().GetColorAttachmentAsTextureObject(0)
        )
        if annotation_texture is None or not annotation_texture.GetHandle():
            raise RuntimeError("VTK did not expose the rendered annotation color texture.")

        state = self.render_window.GetState()
        state.Reset()
        state.Push()
        try:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.framebuffer)
            GL.glDrawBuffer(GL.GL_COLOR_ATTACHMENT0)
            GL.glViewport(0, 0, self.width, self.height)
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glDisable(GL.GL_BLEND)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            GL.glDisable(GL.GL_CULL_FACE)
            if hasattr(GL, "GL_FRAMEBUFFER_SRGB"):
                GL.glDisable(GL.GL_FRAMEBUFFER_SRGB)

            GL.glUseProgram(self.program)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "geometry_texture"), 0)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "annotation_texture"), 1)
            GL.glUniform1i(GL.glGetUniformLocation(self.program, "image_height"), self.height)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.geometry_texture)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, annotation_texture.GetHandle())
            GL.glBindVertexArray(self.vao)

            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
            # Finish only inside this context so the shared geometry texture is no
            # longer being sampled when the geometry context reuses it next frame.
            # The following PBO transfer remains asynchronous.
            GL.glFinish()

            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, slot.pbo)
            raw_glReadPixels(
                0,
                0,
                self.width,
                self.height,
                GL.GL_RGB,
                GL.GL_UNSIGNED_BYTE,
                ctypes.c_void_p(0),
            )
            slot.fence = GL.glFenceSync(GL.GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
            GL.glBindBuffer(GL.GL_PIXEL_PACK_BUFFER, 0)
            GL.glFlush()
        finally:
            state.Pop()

        slot.frame_number = frame_number
        self.pending.append(slot)
        return completed

    def flush(self) -> list[tuple[int, np.ndarray]]:
        completed = []
        while self.pending:
            completed.append(self._collect_oldest(block=True))
        return completed

    def close(self) -> None:
        self.render_window.MakeCurrent()
        GL.glFinish()
        all_slots = list(self.free_slots) + list(self.pending)
        for slot in self.pending:
            if slot.fence is not None:
                GL.glDeleteSync(slot.fence)
        self.pending.clear()
        self.free_slots.clear()

        state = self.render_window.GetState()
        state.Reset()
        state.Push()
        try:
            pbo_ids = [slot.pbo for slot in all_slots]
            if pbo_ids:
                GL.glDeleteBuffers(len(pbo_ids), pbo_ids)
            GL.glDeleteVertexArrays(1, [self.vao])
            GL.glDeleteProgram(self.program)
            GL.glDeleteFramebuffers(1, [self.framebuffer])
            GL.glDeleteTextures(1, [self.output_texture])
        finally:
            state.Pop()


class OffscreenRenderer:
    def __init__(self, data: TrackingDataProvider, config: dict) -> None:
        self.width = int(config["width"])
        self.height = int(config["height"])
        self.ssaa = int(config["ssaa"])
        self.body_settings = data.body_display_settings
        room_bounds = data.room_bounds()
        self.geometry_size = (self.width * self.ssaa, self.height * self.ssaa)
        requested_msaa = int(config["msaa"])
        geometry_msaa = requested_msaa if self.ssaa == 1 else 0
        annotation_msaa = requested_msaa
        dpi = export_render_dpi(self.height)
        camera = config.get("camera")

        self.geometry_plotter = self._create_plotter(self.geometry_size, dpi, geometry_msaa)
        self.geometry_actors = add_body_actors(
            self.geometry_plotter,
            self.body_settings,
            line_scale=self.ssaa,
        )
        geometry_bounds = add_room_bounds(
            self.geometry_plotter,
            room_bounds,
            line_scale=self.ssaa,
        )
        set_room_components(geometry_bounds, axes=False, grid=True, text=False)
        self._set_camera(self.geometry_plotter, room_bounds, camera)
        self.geometry_plotter.show(auto_close=False)

        geometry_window = self.geometry_plotter.render_window
        if not geometry_window.GetPlatformSupportsRenderWindowSharing():
            raise RuntimeError(
                "This VTK/OpenGL backend does not support shared render-window resources, "
                "which are required by the asynchronous GPU export pipeline."
            )

        self.geometry_resolve = GpuGeometryResolve(
            geometry_window,
            self.width,
            self.height,
            self.ssaa,
        )

        self.annotation_plotter = self._create_plotter(
            (self.width, self.height),
            dpi,
            annotation_msaa,
        )
        annotation_window = self.annotation_plotter.render_window
        annotation_window.SetSharedRenderWindow(geometry_window)
        self.annotation_labels = add_body_labels(self.annotation_plotter, self.body_settings)
        annotation_bounds = add_room_bounds(self.annotation_plotter, room_bounds)
        set_room_components(annotation_bounds, axes=True, grid=False, text=True)
        self._set_camera(self.annotation_plotter, room_bounds, camera)
        self.annotation_plotter.show(auto_close=False)
        apply_annotation_viewport_style(
            self.annotation_plotter,
            annotation_bounds,
            self.annotation_labels,
        )

        self.compositor = AsyncGpuCompositor(
            annotation_window,
            self.geometry_resolve.texture,
            self.width,
            self.height,
            slot_count=3,
        )


    @staticmethod
    def _create_plotter(size: tuple[int, int], dpi: int, msaa: int) -> pv.Plotter:
        plotter = pv.Plotter(off_screen=True, window_size=size)
        plotter.render_window.SetDPI(dpi)
        plotter.set_background("white")
        if msaa > 1:
            # OIT does not support hardware MSAA in VTK.  Disabling it keeps
            # multisampling active for the translucent rigid-body meshes.
            plotter.renderer.SetUseOIT(False)
            plotter.enable_anti_aliasing("msaa", multi_samples=msaa)
        else:
            plotter.disable_anti_aliasing()
        return plotter

    @staticmethod
    def _set_camera(plotter, room_bounds, camera) -> None:
        if camera is None:
            frame_camera(plotter, room_bounds)
        else:
            apply_camera_state(plotter, camera)

    def set_frame(self, frame) -> None:
        update_body_actors(self.geometry_actors, frame)
        update_body_labels(self.annotation_labels, self.body_settings, frame)

    def submit_frame(self, frame_number: int) -> list[tuple[int, np.ndarray]]:
        self.geometry_plotter.render_window.Render()
        self.geometry_resolve.resolve()
        self.annotation_plotter.render_window.Render()
        completed = self.compositor.submit(frame_number)
        completed.extend(self.compositor.collect_ready())
        return completed

    def flush(self) -> list[tuple[int, np.ndarray]]:
        return self.compositor.flush()

    def close(self) -> None:
        try:
            self.compositor.close()
        finally:
            self.geometry_resolve.close()
            self.annotation_plotter.close()
            self.geometry_plotter.close()


class QueuedFFmpegWriter:
    def __init__(
        self,
        ffmpeg_path: str,
        output_path: Path,
        settings: VideoEncodingSettings,
        logger: EventEmitter,
        total_frames: int,
        queue_size: int = 3,
    ) -> None:
        self.logger = logger
        self.total_frames = total_frames
        self.process = start_ffmpeg(ffmpeg_path, output_path, settings)
        self.queue: Queue[tuple[int, np.ndarray] | None] = Queue(maxsize=queue_size)
        self.error: Exception | None = None
        self.started_at = time.perf_counter()
        self.completed_times: deque[float] = deque(maxlen=30)
        self.thread = threading.Thread(target=self._run, name="ffmpeg-writer", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break

                frame_number, frame = item
                write_frame_bytes(self.process, frame)

                now = time.perf_counter()
                self.completed_times.append(now)
                if len(self.completed_times) >= 2:
                    intervals = np.diff(np.asarray(self.completed_times))
                    seconds_per_frame = float(np.mean(intervals))
                else:
                    seconds_per_frame = now - self.started_at

                self.logger.emit(
                    "frame",
                    current=frame_number,
                    total=self.total_frames,
                    eta=seconds_per_frame * (self.total_frames - frame_number),
                )

            return_code, stderr_text = finalize_ffmpeg(self.process)
            if return_code:
                raise RuntimeError(f"FFmpeg exited with code {return_code}.\n{stderr_text}")
        except Exception as exc:
            self.error = exc

    def submit(self, frame_number: int, frame: np.ndarray, cancel_path: Path) -> None:
        while True:
            if self.error is not None:
                raise self.error
            if cancel_path.exists():
                raise InterruptedError
            try:
                self.queue.put((frame_number, frame), timeout=0.1)
                return
            except Full:
                continue

    def finish(self) -> None:
        while self.thread.is_alive() and self.error is None:
            try:
                self.queue.put(None, timeout=0.1)
                break
            except Full:
                continue

        self.thread.join()
        if self.error is not None:
            raise self.error

    def abort(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        if self.thread.is_alive():
            try:
                self.queue.put_nowait(None)
            except Full:
                pass
            self.thread.join(timeout=2.0)


def run_export(config: dict, logger: EventEmitter) -> None:
    export_started = time.perf_counter()
    output_path = Path(config["output_path"])
    cancel_path = Path(config["cancel_path"])
    ffmpeg_path = config["ffmpeg_path"]
    codec = config["codec"]
    width = int(config["width"])
    height = int(config["height"])
    fps = int(config["fps"])
    start_s = float(config["start_s"])
    end_s = float(config["end_s"])

    validate_ffmpeg(ffmpeg_path, codec)

    session = load_motive_rigid_body_csv(config["csv_path"])
    if not len(session.time):
        raise RuntimeError("The source CSV contains no samples.")

    data = TrackingDataProvider(session)
    if config["smoothing_enabled"]:
        data.ensure_smoothed(float(config["smoothing_seconds"]))

    frame_count = export_frame_count(start_s, end_s, fps)
    renderer = OffscreenRenderer(data, config)
    writer = None
    settings = VideoEncodingSettings(codec, fps, width, height)

    def deliver(completed) -> None:
        nonlocal writer
        for frame_number, image in completed:
            if writer is None:
                writer = QueuedFFmpegWriter(
                    ffmpeg_path,
                    output_path,
                    settings,
                    logger,
                    total_frames=frame_count,
                    queue_size=3,
                )
            writer.submit(frame_number, image, cancel_path)

    try:
        selected_bodies = config["selected_bodies"]
        smoothing_enabled = bool(config["smoothing_enabled"])
        smoothing_seconds = float(config["smoothing_seconds"])

        for frame_number in range(frame_count):
            if cancel_path.exists():
                raise InterruptedError

            time_s = min(start_s + frame_number / fps, end_s)
            frame = data.scene_frame(
                time_s,
                nearest_sample_index(session.time, time_s),
                selected_bodies,
                smoothing_enabled,
                smoothing_seconds,
            )
            renderer.set_frame(frame)
            deliver(renderer.submit_frame(frame_number + 1))

        deliver(renderer.flush())
        if writer is None:
            raise RuntimeError("The renderer completed without producing a video frame.")
        writer.finish()

        logger.emit(
            "complete",
            current=frame_count,
            total=frame_count,
            elapsed_seconds=round(time.perf_counter() - export_started, 3),
        )

    except InterruptedError:
        if writer is not None:
            writer.abort()
        output_path.unlink(missing_ok=True)
        logger.emit("cancelled", current=0, total=frame_count)
    except Exception:
        if writer is not None:
            writer.abort()
        output_path.unlink(missing_ok=True)
        raise
    finally:
        renderer.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    logger = EventEmitter()

    try:
        with WindowsExecutionState():
            run_export(config, logger)
        return 0
    except Exception as exc:
        logger.emit(
            "error",
            message=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
