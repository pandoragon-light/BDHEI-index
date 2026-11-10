"""Monthly Gamma SPEI at a selectable one- or three-month scale."""

from __future__ import annotations

import os
from typing import Any
import warnings

import numpy as np


def validate_spei_scale(scale: Any) -> int:
    if isinstance(scale, (bool, np.bool_)) or not isinstance(scale, (int, np.integer)) or scale not in (1, 3):
        raise ValueError("spei_scale must be the integer 1 (SPEI-1) or 3 (SPEI-3)")
    return int(scale)


def _climate_indices() -> tuple[Any, Any]:
    # climate-indices 2.4 defaults to one INFO log block per calculation,
    # which becomes thousands of lines for a grid.  Keep normal tool output
    # concise while still allowing users to opt into INFO/DEBUG explicitly.
    os.environ.setdefault("CLIMATE_INDICES_LOG_LEVEL", "WARNING")
    try:
        from climate_indices import compute, indices
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "SPEI requires climate-indices; install the project's declared "
            "dependencies before running this workflow"
        ) from exc
    return compute, indices


def calculate_spei(
    precipitation_mm: Any,
    temperature_celsius: Any,
    latitude_degrees: float,
    *,
    scale: int = 3,
    data_start_year: int = 1961,
    calibration_year_initial: int = 1961,
    calibration_year_final: int = 2023,
) -> np.ndarray:
    """Calculate a monthly SPEI series using Thornthwaite PET and Gamma.

    Inputs must be complete monthly arrays in chronological order.  Missing
    values are returned as NaN at the Python/grid boundary; the historical
    station workbook conversion to ``-99`` is handled only by its validator.
    """

    # climate-indices normalizes some values in place.  Always pass private
    # writable copies so a caller's array/dataframe cannot be modified and
    # read-only NumPy views remain supported.
    precipitation = np.array(precipitation_mm, dtype=float, copy=True)
    temperature = np.array(temperature_celsius, dtype=float, copy=True)
    if precipitation.ndim != 1 or temperature.ndim != 1:
        raise ValueError("precipitation_mm and temperature_celsius must be 1D")
    if precipitation.shape != temperature.shape:
        raise ValueError("precipitation and temperature lengths must match")
    if precipitation.size == 0 or precipitation.size % 12 != 0:
        raise ValueError("monthly inputs must contain a non-zero multiple of 12 values")
    scale = validate_spei_scale(scale)
    end_year = int(data_start_year) + precipitation.size // 12 - 1
    if not int(data_start_year) <= int(calibration_year_initial) <= int(calibration_year_final) <= end_year:
        raise ValueError("SPEI calibration years must lie within the input years")
    if not np.isfinite(latitude_degrees) or not -90 <= latitude_degrees <= 90:
        raise ValueError("latitude_degrees must be between -90 and 90")
    if np.any(precipitation[np.isfinite(precipitation)] < 0):
        raise ValueError("monthly precipitation must be non-negative")
    if not np.isfinite(precipitation).any() or not np.isfinite(temperature).any():
        return np.full(precipitation.shape, np.nan)

    compute, indices = _climate_indices()
    pet = indices.pet(
        temperature_celsius=temperature,
        latitude_degrees=float(latitude_degrees),
        data_start_year=int(data_start_year),
    )
    with warnings.catch_warnings():
        try:
            from climate_indices.exceptions import GoodnessOfFitWarning
        except ImportError:  # climate-indices 2.0 compatibility runtime
            pass
        else:
            # The historical BDHEI workflow deliberately fixes SPEI to the
            # Gamma distribution. Per-cell fit warnings are therefore noisy
            # diagnostics rather than an automatic method switch.
            warnings.simplefilter("ignore", GoodnessOfFitWarning)
        spei = indices.spei(
            precips_mm=precipitation,
            pet_mm=pet,
            scale=int(scale),
            distribution=indices.Distribution.gamma,
            periodicity=compute.Periodicity.monthly,
            data_start_year=int(data_start_year),
            calibration_year_initial=int(calibration_year_initial),
            calibration_year_final=int(calibration_year_final),
        )
    result = np.asarray(spei, dtype=float)
    result[~np.isfinite(result)] = np.nan
    result[np.isin(result, (-99.0, -9999.0))] = np.nan
    return result


def calculate_spei_grid(
    precipitation_mm: Any,
    temperature_celsius: Any,
    latitude_degrees: Any,
    *,
    scale: int = 3,
    data_start_year: int = 1961,
    calibration_year_initial: int = 1961,
    calibration_year_final: int = 2023,
) -> np.ndarray:
    """Calculate SPEI independently for every ``time, latitude, longitude`` cell."""

    scale = validate_spei_scale(scale)
    precipitation = np.asarray(precipitation_mm, dtype=float)
    temperature = np.asarray(temperature_celsius, dtype=float)
    latitude = np.asarray(latitude_degrees, dtype=float)
    if precipitation.ndim != 3 or temperature.ndim != 3:
        raise ValueError("grid inputs must have shape time, latitude, longitude")
    if precipitation.shape != temperature.shape:
        raise ValueError("precipitation and temperature grid shapes must match")
    if latitude.ndim != 1 or latitude.size != precipitation.shape[1]:
        raise ValueError("latitude_degrees must have one value per latitude row")

    output = np.full(precipitation.shape, np.nan, dtype=float)
    for latitude_index, latitude_value in enumerate(latitude):
        for longitude_index in range(precipitation.shape[2]):
            output[:, latitude_index, longitude_index] = calculate_spei(
                precipitation[:, latitude_index, longitude_index],
                temperature[:, latitude_index, longitude_index],
                float(latitude_value),
                scale=scale,
                data_start_year=data_start_year,
                calibration_year_initial=calibration_year_initial,
                calibration_year_final=calibration_year_final,
            )
    return output


# Keep the existing development API available; new callers use scale-neutral names.
calculate_spei3 = calculate_spei
calculate_spei3_grid = calculate_spei_grid
