from __future__ import annotations

import numpy as np
import pandas as pd

def fill_missing_values(values: np.ndarray) -> np.ndarray:
    values_series = pd.Series(values)

    values_series = values_series.interpolate(
        method="linear",
        limit_direction="both"
    )

    return values_series.to_numpy(dtype=float)

def estimate_sample_rate_hz(time_s: np.ndarray) -> float:
    duration_s = float(time_s[-1] - time_s[0])
    frame_intervals = len(time_s) - 1

    return round(frame_intervals / duration_s, 4)

def smoothing_seconds_to_window_size(
        time_s: np.ndarray,
        smoothing_seconds: float) -> int:
    if smoothing_seconds <= 0.0:
        return 1

    sample_rate_hz = estimate_sample_rate_hz(time_s)

    window_size = int(round(smoothing_seconds * sample_rate_hz))

    if window_size % 2 == 0:
        window_size += 1

    return window_size

def smooth_values_centered(
        values: np.ndarray,
        window_size: int) -> np.ndarray:
    if window_size <= 1:
        return values.astype(float, copy=True)

    values_series = pd.Series(values)

    smoothed_series = values_series.rolling(
        window=window_size,
        center=True,
        min_periods=1).median()

    smoothed_series = smoothed_series.rolling(
            window=window_size,
            center=True,
            min_periods=1).mean()

    return smoothed_series.to_numpy(dtype=float)


def smooth_positions_centered(
        positions: np.ndarray,
        window_size: int) -> np.ndarray:
    smoothed_x = smooth_values_centered(positions[:, 0], window_size)
    smoothed_y = smooth_values_centered(positions[:, 1], window_size)
    smoothed_z = smooth_values_centered(positions[:, 2], window_size)

    return np.column_stack(
        [
            smoothed_x,
            smoothed_y,
            smoothed_z
        ]
    )

def normalize_quaternion(quaternion: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(quaternion))

    if norm == 0.0:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=float)

    return quaternion / norm

def normalize_quaternions(quaternions: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(quaternions, axis=1)

    safe_norms = np.where(norms == 0.0, 1.0, norms)

    normalized_quaternions = quaternions / safe_norms[:, np.newaxis]

    zero_norm_mask = norms == 0.0

    if np.any(zero_norm_mask):
        normalized_quaternions[zero_norm_mask] = np.array(
            [0.0, 0.0, 0.0, 1.0],
            dtype=float
        )

    return normalized_quaternions

def make_quaternion_signs_continuous(quaternions: np.ndarray) -> np.ndarray:
    continuous_quaternions = quaternions.astype(float, copy=True)

    for idx in range(1, len(continuous_quaternions)):
        previous_quaternion = continuous_quaternions[idx - 1]
        current_quaternion = continuous_quaternions[idx]

        dot_product = float(np.dot(previous_quaternion, current_quaternion))

        if dot_product < 0.0:
            continuous_quaternions[idx] = -current_quaternion

    return continuous_quaternions

def smooth_quaternions_centered(
        quaternions: np.ndarray,
        window_size: int) -> np.ndarray:
    normalized_quaternions = normalize_quaternions(quaternions)

    continuous_quaternions = make_quaternion_signs_continuous(normalized_quaternions)

    if window_size <= 1:
        return continuous_quaternions

    smoothed_qx = smooth_values_centered(
        continuous_quaternions[:, 0],
        window_size
    )

    smoothed_qy = smooth_values_centered(
            continuous_quaternions[:, 1],
            window_size
        )

    smoothed_qz = smooth_values_centered(
            continuous_quaternions[:, 2],
            window_size
        )

    smoothed_qw = smooth_values_centered(
            continuous_quaternions[:, 3],
            window_size
        )

    smoothed_quaternions = np.column_stack(
        [
            smoothed_qx,
            smoothed_qy,
            smoothed_qz,
            smoothed_qw
        ]
    )

    return normalize_quaternions(smoothed_quaternions)

def smooth_tracking_positions_and_rotations(
        time_s: np.ndarray,
        positions: np.ndarray,
        rotations: np.ndarray,
        smoothing_seconds: float) -> tuple[np.ndarray, np.ndarray]:
    window_size = smoothing_seconds_to_window_size(time_s, smoothing_seconds)

    smoothed_positions = smooth_positions_centered(positions, window_size)

    smoothed_rotations = smooth_quaternions_centered(rotations, window_size)

    return smoothed_positions, smoothed_rotations