"""Grid BDHEI calculation using the validated station core independently per cell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .common import DEFAULT_MONTHS

@dataclass(frozen=True)
class GridBDHEIResult:
    """BDHEI grid values and one diagnostics row per spatial cell."""

    values: np.ndarray
    diagnostics: pd.DataFrame


def _bracket_coordinate(coordinates: np.ndarray, value: float) -> tuple[int, int, float]:
    """Return lower/upper coordinate indices and the linear weight."""

    if coordinates.ndim != 1 or len(coordinates) < 2:
        raise ValueError("each coordinate axis must contain at least two values")
    if value < float(np.min(coordinates)) or value > float(np.max(coordinates)):
        raise ValueError(f"coordinate {value} is outside the grid bounds")
    order = np.argsort(coordinates)
    ascending = coordinates[order]
    upper_position = int(np.searchsorted(ascending, value, side="right"))
    upper_position = min(max(upper_position, 1), len(ascending) - 1)
    lower_position = upper_position - 1
    lower_index = int(order[lower_position])
    upper_index = int(order[upper_position])
    denominator = float(ascending[upper_position] - ascending[lower_position])
    weight = 0.0 if denominator == 0.0 else float(
        (value - ascending[lower_position]) / denominator
    )
    return lower_index, upper_index, weight


def bilinear_interpolate_grid(
    values: Any,
    latitudes: Sequence[float],
    longitudes: Sequence[float],
    latitude: float,
    longitude: float,
) -> np.ndarray:
    """Bilinearly interpolate a ``time x latitude x longitude`` field."""

    field = np.asarray(values, dtype=float)
    if field.ndim != 3:
        raise ValueError("values must have shape time x latitude x longitude")
    latitude_axis = np.asarray(latitudes, dtype=float)
    longitude_axis = np.asarray(longitudes, dtype=float)
    if field.shape[1:] != (len(latitude_axis), len(longitude_axis)):
        raise ValueError("coordinate lengths do not match field dimensions")
    lat0, lat1, lat_weight = _bracket_coordinate(latitude_axis, float(latitude))
    lon0, lon1, lon_weight = _bracket_coordinate(longitude_axis, float(longitude))
    q00 = field[:, lat0, lon0]
    q01 = field[:, lat0, lon1]
    q10 = field[:, lat1, lon0]
    q11 = field[:, lat1, lon1]
    return (
        (1.0 - lat_weight) * (1.0 - lon_weight) * q00
        + (1.0 - lat_weight) * lon_weight * q01
        + lat_weight * (1.0 - lon_weight) * q10
        + lat_weight * lon_weight * q11
    )


def _month_numbers(time_values: Any) -> np.ndarray:
    values = np.asarray(time_values)
    if not np.issubdtype(values.dtype, np.datetime64):
        raise ValueError("time_values must be a datetime64 array")
    return values.astype("datetime64[M]").astype(int) % 12 + 1


def calculate_bdhei_grid(
    spei_values: Any,
    sti_values: Any,
    time_values: Any,
    latitudes: Sequence[float],
    longitudes: Sequence[float],
    *,
    months: Sequence[int] = DEFAULT_MONTHS,
    eps: float = 1e-6,
    ppf_clip: tuple[float, float] = (0.0001, 0.9999),
) -> GridBDHEIResult:
    """Fit and evaluate BDHEI independently for each grid cell.

    The output keeps the full input time axis but writes BDHEI values only for
    the requested calendar months (January–December by default). The Copula and KDE are fitted separately
    for each cell using all valid selected-month observations.
    """

    drought = np.asarray(spei_values, dtype=float)
    heat = np.asarray(sti_values, dtype=float)
    if drought.shape != heat.shape or drought.ndim != 3:
        raise ValueError("spei_values and sti_values must have the same 3D shape")
    time = np.asarray(time_values)
    if drought.shape[0] != len(time):
        raise ValueError("time_values length does not match the time dimension")
    latitudes = np.asarray(latitudes, dtype=float)
    longitudes = np.asarray(longitudes, dtype=float)
    if drought.shape[1:] != (len(latitudes), len(longitudes)):
        raise ValueError("latitude/longitude lengths do not match spatial dimensions")
    month_set = tuple(int(month) for month in months)
    if not month_set or not set(month_set).issubset(set(range(1, 13))):
        raise ValueError("months must contain calendar months from 1 to 12")

    selected_time_mask = np.isin(_month_numbers(time), month_set)
    # Keep the lightweight STI/SPEI modules importable in environments that
    # do not install the optional Copula dependency.  BDHEI callers receive a
    # direct import error only when they actually request BDHEI calculation.
    from .core import calculate_bdhei

    # Select the requested calendar months once and flatten the spatial axes.
    # The previous implementation re-created a 1D time slice through the 3D
    # array for every cell.  The fit is still independent per cell, but the
    # data movement now happens once for the whole selected block.
    selected_indices = np.flatnonzero(selected_time_mask)
    selected_drought = drought[selected_indices].reshape(len(selected_indices), -1)
    selected_heat = heat[selected_indices].reshape(len(selected_indices), -1)
    selected_output = np.full(selected_drought.shape, np.nan, dtype=float)
    rows: list[dict[str, Any]] = []

    for latitude_index, latitude in enumerate(latitudes):
        for longitude_index, longitude in enumerate(longitudes):
            cell_index = latitude_index * len(longitudes) + longitude_index
            drought_series = selected_drought[:, cell_index]
            heat_series = selected_heat[:, cell_index]
            paired_mask = np.isfinite(drought_series) & np.isfinite(heat_series)
            valid_n = int(paired_mask.sum())
            row: dict[str, Any] = {
                "latitude_index": latitude_index,
                "longitude_index": longitude_index,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "selected_n": int(selected_time_mask.sum()),
                "valid_n": valid_n,
                "status": "ok",
                "copula_type": None,
                "copula_params": None,
                "error": None,
            }
            if valid_n == 0:
                row["status"] = "no_valid_data"
                rows.append(row)
                continue

            frame = pd.DataFrame(
                {
                    "SPEI": drought_series[paired_mask],
                    "STI": heat_series[paired_mask],
                }
            )
            try:
                result = calculate_bdhei(
                    frame,
                    drought_col="SPEI",
                    eps=eps,
                    ppf_clip=ppf_clip,
                )
                selected_output[paired_mask, cell_index] = result.data["BDHEI"].to_numpy(dtype=float)
                row["copula_type"] = result.copula_type
                row["copula_params"] = result.copula_params
            except Exception as exc:  # diagnostics must preserve a failed cell
                row["status"] = "fit_failed"
                row["error"] = str(exc)
            rows.append(row)

    output = np.full(drought.shape, np.nan, dtype=float)
    output[selected_indices] = selected_output.reshape(
        len(selected_indices), len(latitudes), len(longitudes)
    )
    return GridBDHEIResult(values=output, diagnostics=pd.DataFrame(rows))
