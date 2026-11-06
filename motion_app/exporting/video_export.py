from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from motion_app.core.constants import H264_RGB_LOSSLESS, H265_HIGH_QUALITY

_ENCODERS = {
    H264_RGB_LOSSLESS: "libx264rgb",
    H265_HIGH_QUALITY: "libx265",
}


@dataclass(frozen=True)
class VideoEncodingSettings:
    codec_name: str
    fps: int
    width: int
    height: int


def export_frame_count(start_s: float, end_s: float, fps: int) -> int:
    """Return the inclusive number of output frames for an export time range."""
    duration_s = max(0.0, float(end_s) - float(start_s))
    return max(1, round(duration_s * int(fps)) + 1)


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_ffmpeg_executable(path: str | Path) -> bool:
    if not path or not Path(path).is_file():
        return False
    try:
        probe = subprocess.run(
            [str(path), "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def find_ffmpeg() -> str | None:
    candidate = shutil.which("ffmpeg")
    return candidate if candidate and is_ffmpeg_executable(candidate) else None


def validate_ffmpeg(ffmpeg_path: str, codec_name: str) -> None:
    encoder = _ENCODERS[codec_name]
    try:
        probe = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-h", f"encoder={encoder}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            creationflags=_creation_flags(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"FFmpeg executable not found: {ffmpeg_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"FFmpeg is not a runnable Windows executable: {ffmpeg_path}\n{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg did not respond: {ffmpeg_path}") from exc

    if probe.returncode or f"Encoder {encoder} " not in probe.stdout:
        raise RuntimeError(f"This FFmpeg build does not provide {encoder}.")


def build_ffmpeg_command(
    ffmpeg_path: str,
    output_path: str | Path,
    settings: VideoEncodingSettings,
) -> list[str]:
    command = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{settings.width}x{settings.height}",
        "-r", str(settings.fps),
        "-i", "-",
        "-an",
    ]

    if settings.codec_name == H264_RGB_LOSSLESS:
        command += [
            "-c:v", "libx264rgb",
            "-crf", "0",
            "-preset", "medium",
            "-pix_fmt", "rgb24",
            "-movflags", "+faststart",
        ]
    elif settings.codec_name == H265_HIGH_QUALITY:
        command += [
            "-c:v", "libx265",
            "-crf", "14",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            "-tag:v", "hvc1",
            "-movflags", "+faststart",
        ]
    else:
        raise ValueError(f"Unknown codec preset: {settings.codec_name!r}")

    command.append(str(output_path))
    return command


def start_ffmpeg(
    ffmpeg_path: str,
    output_path: str | Path,
    settings: VideoEncodingSettings,
) -> subprocess.Popen:
    return subprocess.Popen(
        build_ffmpeg_command(ffmpeg_path, output_path, settings),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
        creationflags=_creation_flags(),
    )


def ffmpeg_error_text(process: subprocess.Popen) -> str:
    return process.stderr.read().decode("utf-8", errors="replace").strip()


def write_frame_bytes(process: subprocess.Popen, frame_buffer) -> None:
    if process.poll() is not None:
        message = ffmpeg_error_text(process)
        raise RuntimeError(
            f"FFmpeg exited before accepting the next frame (code {process.returncode})."
            + (f"\n{message}" if message else "")
        )

    view = memoryview(frame_buffer).cast("B")
    written = 0
    while written < len(view):
        count = process.stdin.write(view[written:])
        if not count:
            raise RuntimeError("FFmpeg stopped accepting frame data.")
        written += count


def finalize_ffmpeg(process: subprocess.Popen) -> tuple[int, str]:
    process.stdin.close()
    return_code = process.wait()
    return return_code, ffmpeg_error_text(process)
