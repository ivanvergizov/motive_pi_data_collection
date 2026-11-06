from __future__ import annotations

import math

import numpy as np

from motion_app.core.app_types import RoomBounds


def nice_tick_spacing(span: float, target_tick_count: int = 8) -> float:
    safe_span = max(float(span), 1.0e-9)
    raw_spacing = safe_span / max(target_tick_count, 1)
    exponent = math.floor(math.log10(raw_spacing))
    magnitude = 10.0 ** exponent
    normalized = raw_spacing / magnitude
    multiplier = 1.0 if normalized <= 1.0 else 2.0 if normalized <= 2.0 else 5.0 if normalized <= 5.0 else 10.0
    return float(multiplier * magnitude)


def calculate_room_axis_bounds(values: np.ndarray, minimum_padding: float) -> tuple[float, float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return -1.0, 1.0, 0.25

    data_min, data_max = float(np.min(finite)), float(np.max(finite))
    data_span = data_max - data_min
    if data_span <= 1.0e-9:
        half_span = max(abs(data_min) * 0.1, minimum_padding, 0.25)
        data_min -= half_span
        data_max += half_span
        data_span = data_max - data_min

    padding = max(minimum_padding, data_span * 0.08, 0.05)
    tick = nice_tick_spacing(data_span + 2.0 * padding)
    axis_min = math.floor((data_min - padding) / tick) * tick
    axis_max = math.ceil((data_max + padding) / tick) * tick
    if axis_max <= axis_min:
        axis_max = axis_min + tick
    return float(axis_min), float(axis_max), float(tick)


def calculate_room_bounds(positions_by_body: dict[str, np.ndarray], minimum_padding: float) -> RoomBounds:
    valid = []
    for positions in positions_by_body.values():
        array = np.asarray(positions, dtype=float)
        if array.ndim == 2 and array.shape[1] == 3 and array.size:
            valid.append(array)
    if not valid:
        return RoomBounds(-1, 1, -1, 1, -1, 1, 0.25, 0.25, 0.25)

    combined = np.vstack(valid)
    x_min, x_max, x_tick = calculate_room_axis_bounds(combined[:, 0], minimum_padding)
    y_min, y_max, y_tick = calculate_room_axis_bounds(combined[:, 1], minimum_padding)
    z_min, z_max, z_tick = calculate_room_axis_bounds(combined[:, 2], minimum_padding)
    return RoomBounds(x_min, x_max, y_min, y_max, z_min, z_max, x_tick, y_tick, z_tick)
