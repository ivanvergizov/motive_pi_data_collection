from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject

from motion_app.core.tracking_data import nearest_sample_index


class PlaybackController(QObject):
    """Tracks playback time from the wall clock; rendering is scheduled elsewhere."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._time = np.asarray([], dtype=float)
        self.current_time_s = 0.0
        self.current_frame_idx = 0
        self.speed = 1.0
        self._playing = False
        self._start_wall_s = 0.0
        self._start_data_s = 0.0

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def duration_s(self) -> float:
        return float(self._time[-1]) if self._time.size else 0.0

    def set_time_array(self, time_s: np.ndarray) -> None:
        self._playing = False
        self._time = np.asarray(time_s, dtype=float)
        self.current_time_s = 0.0
        self.current_frame_idx = 0

    def set_speed(self, speed: float) -> None:
        if self._playing:
            self.sample()
        self.speed = float(speed)
        if self._playing:
            self._restart_origin()

    def play(self) -> None:
        if not self._time.size or self._playing:
            return
        self._playing = True
        self._restart_origin()

    def pause(self) -> None:
        if self._playing:
            self.sample()
        self._playing = False

    def seek(self, time_s: float) -> None:
        if not self._time.size:
            return
        duration = self.duration_s
        self.current_time_s = 0.0 if duration <= 0.0 else max(0.0, min(float(time_s), duration))
        self.current_frame_idx = nearest_sample_index(self._time, self.current_time_s)
        if self._playing:
            self._restart_origin()

    def sample(self) -> tuple[float, int]:
        """Return the playback position at the current wall-clock instant."""
        if not self._time.size:
            return 0.0, 0
        if self._playing:
            self._update_from_wall_clock()
        return self.current_time_s, self.current_frame_idx

    def _restart_origin(self) -> None:
        self._start_wall_s = time.perf_counter()
        self._start_data_s = self.current_time_s

    def _update_from_wall_clock(self) -> None:
        duration = self.duration_s
        if duration <= 0.0:
            self.current_time_s = 0.0
            self.current_frame_idx = 0
            return

        now = time.perf_counter()
        target = self._start_data_s + (now - self._start_wall_s) * self.speed
        if target > duration:
            target %= duration
            self._start_wall_s = now
            self._start_data_s = target

        self.current_time_s = target
        self.current_frame_idx = nearest_sample_index(self._time, target)
