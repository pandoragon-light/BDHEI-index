"""Shared settings and unit conversion for monthly station and grid workflows."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np


DEFAULT_MONTHS: tuple[int, ...] = tuple(range(1, 13))


def _resolve_path(value: str | Path, base_dir: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else Path(base_dir) / path).resolve()


def _validate_months(months: Sequence[int]) -> tuple[int, ...]:
    if not months or any(isinstance(m, bool) or not isinstance(m, (int, np.integer)) or not 1 <= m <= 12 for m in months):
        raise ValueError("months must contain calendar months from 1 to 12")
    return tuple(int(m) for m in months)


def _unit(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "").replace("°", "degree_")


def temperature_to_celsius(values: np.ndarray, unit: str) -> np.ndarray:
    normalized = _unit(unit)
    if normalized in {"c", "celsius", "degree_c", "degree_celsius", "degrees_celsius"}:
        return values.copy()
    if normalized in {"k", "kelvin", "degree_kelvin", "degrees_kelvin"}:
        return values - 273.15
    raise ValueError("temperature_unit must be celsius or kelvin (or provide recognized NetCDF units)")


def precipitation_to_mm(values: np.ndarray, unit: str, days_in_month: np.ndarray) -> np.ndarray:
    normalized = _unit(unit)
    days = np.asarray(days_in_month, dtype=float).reshape((-1,) + (1,) * (values.ndim - 1))
    if normalized in {"mm", "mm/month", "mmmonth-1", "kgm-2"}:
        return values.copy()
    if normalized in {"m/month", "mmonth-1"}:
        return values * 1000.0
    if normalized in {"mm/day", "mmday-1", "mmd-1"}:
        return values * days
    if normalized in {"m/day", "mday-1", "md-1"}:
        return values * 1000.0 * days
    if normalized in {"kgm-2s-1", "kgm**-2s**-1", "mm/s"}:
        return values * 86400.0 * days
    raise ValueError(
        "precipitation_unit must be mm/month, m/month, mm/day, m/day or kg m-2 s-1; "
        "for NetCDF units='m', explicitly select m/day (ERA5 monthly averaged) or m/month"
    )


def _monthly_years(time: Any) -> tuple[int, int]:
    dates = np.asarray(time)
    if dates.ndim != 1 or not np.issubdtype(dates.dtype, np.datetime64):
        raise ValueError("time must be a one-dimensional Gregorian monthly date coordinate")
    if not dates.size or np.isnat(dates).any():
        raise ValueError("time contains missing dates or is empty")
    months = dates.astype("datetime64[M]").astype(int)
    if months[0] % 12 != 0 or months[-1] % 12 != 11 or np.any(np.diff(months) != 1):
        raise ValueError("input must contain consecutive monthly data from January through December of complete years")
    return int(months[0] // 12 + 1970), int(months[-1] // 12 + 1970)
