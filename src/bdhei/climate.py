"""Monthly temperature/precipitation NetCDF to STI, SPEI and BDHEI."""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import xarray as xr

from .grid_bdhei import calculate_bdhei_grid
from .grid_sti import calculate_sti_grid
from .netcdf_io import open_netcdf, write_netcdf
from .path_safety import privacy_safe_path, sanitize_metadata, validate_io_paths
from .common import _resolve_path, _validate_months, _monthly_years, temperature_to_celsius, precipitation_to_mm
from .spei import calculate_spei_grid, validate_spei_scale


def _coordinate(array: xr.DataArray, dimension: str) -> np.ndarray:
    if dimension not in array.coords or array[dimension].dims != (dimension,):
        raise ValueError(f"{dimension} must be a one-dimensional coordinate")
    values = np.asarray(array[dimension].values, dtype=float)
    if not values.size or not np.isfinite(values).all() or np.unique(values).size != values.size:
        raise ValueError(f"{dimension} must contain unique finite coordinates")
    return values


def calculate_climate_from_config(config: Mapping[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    """Read a flat YAML configuration and calculate each grid cell independently.

    Paths are relative to base_dir (the working directory for the CLI).
    Input contains one monthly value per Gregorian month, in complete years.
    The full monthly series is used for STI/SPEI; months selects BDHEI output.
    """
    spei_scale = validate_spei_scale(config.get("spei_scale", 3))
    spei_name = f"SPEI_{spei_scale}"
    sti_scale = config.get("sti_scale", 3)
    if isinstance(sti_scale, bool) or not isinstance(sti_scale, int) or not 1 <= sti_scale <= 12:
        raise ValueError("sti_scale must be an integer from 1 to 12")
    months = _validate_months(config.get("months", (6, 7, 8)))
    overwrite = config.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be true or false")
    temperature_input = config.get("temperature_input", config.get("input"))
    precipitation_input = config.get("precipitation_input", config.get("input"))
    if not temperature_input or not precipitation_input or not config.get("output"):
        raise ValueError("provide input (or temperature_input and precipitation_input) and output")
    t_path = _resolve_path(temperature_input, base_dir)
    p_path = _resolve_path(precipitation_input, base_dir)
    # An optional placeholder keeps scale-specific output names a one-setting choice.
    def output_path(value: str | Path) -> Path:
        return _resolve_path(str(value).replace("{spei_scale}", str(spei_scale)), base_dir)

    destination = output_path(config["output"])
    diagnostics = output_path(config["diagnostics"]) if config.get("diagnostics") else destination.with_name(destination.stem + "_diagnostics.csv")
    summary = output_path(config["summary"]) if config.get("summary") else destination.with_suffix(".json")
    inputs = {"temperature": t_path}
    if p_path != t_path:
        inputs["precipitation"] = p_path
    validate_io_paths(inputs=inputs, outputs={"result": destination, "diagnostics": diagnostics, "summary": summary}, overwrite=overwrite)

    time_dim = str(config.get("time_dimension", "time"))
    lat_dim = str(config.get("latitude_dimension", "latitude"))
    lon_dim = str(config.get("longitude_dimension", "longitude"))
    dimensions = (time_dim, lat_dim, lon_dim)
    if len(set(dimensions)) != 3:
        raise ValueError("time, latitude and longitude dimensions must be different")
    t_name = str(config.get("temperature_variable", "t2m"))
    p_name = str(config.get("precipitation_variable", "tp"))
    engine = str(config.get("input_engine", "auto"))
    with ExitStack() as stack:
        t_source = stack.enter_context(open_netcdf(t_path, engine=engine))
        p_source = t_source if t_path == p_path else stack.enter_context(open_netcdf(p_path, engine=engine))
        for source, name in ((t_source, t_name), (p_source, p_name)):
            if name not in source:
                raise KeyError(f"missing climate variable: {name}")
            if set(source[name].dims) != set(dimensions):
                raise ValueError(f"{name} must have exactly the dimensions {dimensions}")
        temperature = t_source[t_name].transpose(*dimensions)
        precipitation = p_source[p_name].transpose(*dimensions)
        # Exact alignment also checks ordering, month labels and spatial support.
        temperature, precipitation = xr.align(temperature, precipitation, join="exact")
        start_year, end_year = _monthly_years(temperature[time_dim])
        _monthly_years(precipitation[time_dim])
        latitudes = _coordinate(temperature, lat_dim)
        longitudes = _coordinate(temperature, lon_dim)
        _coordinate(precipitation, lat_dim)
        _coordinate(precipitation, lon_dim)
        if np.any(np.abs(latitudes) > 90):
            raise ValueError("latitude coordinates must be between -90 and 90 degrees")
        t_unit = str(config.get("temperature_unit", temperature.attrs.get("units", "")))
        p_unit = str(config.get("precipitation_unit", precipitation.attrs.get("units", "")))
        t_values = np.array(temperature.values, dtype=float, copy=True)
        p_values = np.array(precipitation.values, dtype=float, copy=True)
        for values in (t_values, p_values):
            values[np.isin(values, config.get("missing_values", [-99.0, -9999.0]))] = np.nan
            values[~np.isfinite(values)] = np.nan
        t_celsius = temperature_to_celsius(t_values, t_unit)
        p_mm = precipitation_to_mm(p_values, p_unit, temperature[time_dim].dt.days_in_month.values)
        if np.any(p_mm[np.isfinite(p_mm)] < 0):
            raise ValueError("monthly precipitation must be non-negative")
        coords = {dim: temperature[dim].load().copy(deep=True) for dim in dimensions}
        dates = np.array(temperature[time_dim].values, copy=True)

    calibration_start = int(config.get("calibration_year_initial", start_year))
    calibration_end = int(config.get("calibration_year_final", end_year))
    if not start_year <= calibration_start <= calibration_end <= end_year:
        raise ValueError("SPEI calibration years must lie within the input years")
    sti = calculate_sti_grid(t_celsius, scale=sti_scale, start_year=start_year)
    spei = calculate_spei_grid(p_mm, t_celsius, latitudes, scale=spei_scale, data_start_year=start_year,
                               calibration_year_initial=calibration_start, calibration_year_final=calibration_end)
    grid = calculate_bdhei_grid(spei, sti, dates, latitudes, longitudes, months=months)
    variables = {
        "temperature_celsius": (dimensions, t_celsius, {"units": "degree_Celsius", "long_name": "Monthly mean temperature"}),
        "precipitation_mm": (dimensions, p_mm, {"units": "mm", "long_name": "Monthly total precipitation"}),
        "STI": (dimensions, sti, {"units": "1", "time_scale_months": sti_scale, "method": "SPIGenerator-compatible Gamma STI; full input-period fit"}),
        spei_name: (dimensions, spei, {"units": "1", "time_scale_months": spei_scale, "distribution": "gamma", "pet_method": "Thornthwaite",
                                    "calibration_year_initial": calibration_start, "calibration_year_final": calibration_end}),
        "BDHEI": (dimensions, grid.values, {"units": "1", "spei_variable": spei_name, "sti_variable": "STI", "calculation_months": ",".join(map(str, months))}),
    }
    with xr.Dataset(variables, coords=coords, attrs={
        "title": f"STI-{sti_scale}, SPEI-{spei_scale} and BDHEI from monthly climate data",
        "spei_scale": spei_scale, "sti_scale": sti_scale,
        "analysis_start_year": start_year, "analysis_end_year": end_year,
        "temperature_source": privacy_safe_path(t_path, base_dir=base_dir),
        "precipitation_source": privacy_safe_path(p_path, base_dir=base_dir),
        "source_temperature_unit": t_unit, "source_precipitation_unit": p_unit,
    }) as dataset:
        io_settings = write_netcdf(dataset, destination, engine=str(config.get("output_engine", "auto")),
                                   output_format=str(config.get("output_format", "NETCDF4")),
                                   chunks=config.get("output_chunks"), compression_level=config.get("compression_level", 4))
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_table = grid.diagnostics.copy()
    diagnostic_table["spei_scale"] = spei_scale
    diagnostic_table.to_csv(diagnostics, index=False, encoding="utf-8-sig")
    counts = {str(key): int(value) for key, value in diagnostic_table["status"].value_counts().items()}
    result = {
        "status": "OK_WITH_FAILED_CELLS" if counts.get("fit_failed", 0) else "OK",
        "output": privacy_safe_path(destination, base_dir=base_dir),
        "diagnostics": privacy_safe_path(diagnostics, base_dir=base_dir),
        "summary": privacy_safe_path(summary, base_dir=base_dir),
        "spei_scale": spei_scale, "spei_variable": spei_name, "sti_scale": sti_scale,
        "analysis_start_year": start_year, "analysis_end_year": end_year,
        "calibration_year_initial": calibration_start, "calibration_year_final": calibration_end,
        "dimensions": dict(zip(dimensions, spei.shape)), "months": list(months),
        "valid_spei_count": int(np.isfinite(spei).sum()), "valid_bdhei_count": int(np.isfinite(grid.values).sum()),
        "status_counts": counts, "netcdf_io": io_settings,
    }
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(sanitize_metadata(result, base_dir=base_dir), ensure_ascii=False, indent=2), encoding="utf-8")
    return result
