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

def smooth_values(values: np.ndarray, window_size: int) -> np.ndarray:
    if window_size <=1:
        return values
    
    values_series = pd.Series(values)

    smoothed_series = values_series.rolling(
        window=window_size,
        center=True,
        min_periods=1
    ).mean()

    return smoothed_series.to_numpy(dtype=float)