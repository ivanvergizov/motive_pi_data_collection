from __future__ import annotations

import numpy as np
import pandas as pd

from rigid_body_math import normalize_quaternions_xyzw


def fill_missing_values(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)

    if values.ndim != 1:
        raise ValueError("fill_missing_values expects a one-dimensional array.")

    if len(values) == 0:
        return values.copy()

    values_series = pd.Series(values)
    values_series = values_series.interpolate(
        method="linear",
        limit_direction="both",
    )

    filled_values = values_series.to_numpy(dtype=float)

    if np.any(np.isnan(filled_values)):
        raise ValueError("The signal contains no finite values that can fill its NaNs.")

    return filled_values


def estimate_sample_rate_hz(time_s: np.ndarray) -> float:
    time_s = np.asarray(time_s, dtype=float)

    if time_s.ndim != 1 or len(time_s) < 2:
        raise ValueError("At least two time samples are required.")

    if not np.all(np.isfinite(time_s)):
        raise ValueError("Time samples must all be finite.")

    duration_s = float(time_s[-1] - time_s[0])

    if duration_s <= 0.0:
        raise ValueError("Time samples must span a positive duration.")

    frame_intervals = len(time_s) - 1
    return frame_intervals / duration_s


def smoothing_seconds_to_window_size(
    time_s: np.ndarray,
    smoothing_seconds: float,
) -> int:
    time_s = np.asarray(time_s, dtype=float)

    if len(time_s) == 0:
        return 1

    if smoothing_seconds <= 0.0 or len(time_s) == 1:
        return 1

    sample_rate_hz = estimate_sample_rate_hz(time_s)
    window_size = max(1, int(round(smoothing_seconds * sample_rate_hz)))
    window_size = min(window_size, len(time_s))

    if window_size % 2 == 0:
        if window_size < len(time_s):
            window_size += 1
        else:
            window_size -= 1

    return max(1, window_size)


def smooth_values_centered(
    values: np.ndarray,
    window_size: int,
) -> np.ndarray:
    values = np.asarray(values, dtype=float)

    if values.ndim != 1:
        raise ValueError("smooth_values_centered expects a one-dimensional array.")

    if window_size <= 1 or len(values) <= 1:
        return values.copy()

    values_series = pd.Series(values)

    smoothed_series = values_series.rolling(
        window=window_size,
        center=True,
        min_periods=1,
    ).median()

    smoothed_series = smoothed_series.rolling(
        window=window_size,
        center=True,
        min_periods=1,
    ).mean()

    return smoothed_series.to_numpy(dtype=float)


def smooth_positions_centered(
    positions: np.ndarray,
    window_size: int,
) -> np.ndarray:
    positions = np.asarray(positions, dtype=float)

    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("positions must have shape (N, 3).")

    return np.column_stack(
        [
            smooth_values_centered(positions[:, 0], window_size),
            smooth_values_centered(positions[:, 1], window_size),
            smooth_values_centered(positions[:, 2], window_size),
        ]
    )


def make_quaternion_signs_continuous(quaternions: np.ndarray) -> np.ndarray:
    continuous_quaternions = normalize_quaternions_xyzw(quaternions)

    for index in range(1, len(continuous_quaternions)):
        previous_quaternion = continuous_quaternions[index - 1]
        current_quaternion = continuous_quaternions[index]

        if float(np.dot(previous_quaternion, current_quaternion)) < 0.0:
            continuous_quaternions[index] = -current_quaternion

    return continuous_quaternions


def smooth_quaternions_centered(
    quaternions: np.ndarray,
    window_size: int,
) -> np.ndarray:
    continuous_quaternions = make_quaternion_signs_continuous(quaternions)

    if window_size <= 1 or len(continuous_quaternions) <= 1:
        return continuous_quaternions

    smoothed_quaternions = np.column_stack(
        [
            smooth_values_centered(continuous_quaternions[:, 0], window_size),
            smooth_values_centered(continuous_quaternions[:, 1], window_size),
            smooth_values_centered(continuous_quaternions[:, 2], window_size),
            smooth_values_centered(continuous_quaternions[:, 3], window_size),
        ]
    )

    return normalize_quaternions_xyzw(smoothed_quaternions)


def smooth_tracking_positions_and_rotations(
    time_s: np.ndarray,
    positions: np.ndarray,
    rotations: np.ndarray,
    smoothing_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    positions = np.asarray(positions, dtype=float)
    rotations = np.asarray(rotations, dtype=float)

    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("positions must have shape (N, 3).")

    if rotations.ndim != 2 or rotations.shape[1] != 4:
        raise ValueError("rotations must have shape (N, 4) in quaternion XYZW order.")

    if len(positions) != len(rotations) or len(positions) != len(time_s):
        raise ValueError("Time, position, and rotation arrays must have equal lengths.")

    window_size = smoothing_seconds_to_window_size(time_s, smoothing_seconds)

    return (
        smooth_positions_centered(positions, window_size),
        smooth_quaternions_centered(rotations, window_size),
    )
