"""Initial NumPy and NetCDF adapter for the compatible STI core.

The first grid implementation prioritizes traceability: each spatial cell is
passed through the already validated ``spigenerator_compatible`` one-dimensional
algorithm.  It is intentionally not vectorized yet.  This provides a safe
correctness baseline before performance optimization or xarray integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .sti import MISSING_VALUES, calculate_sti_result
from .netcdf_io import open_netcdf, resolve_netcdf_engine, write_netcdf
from .path_safety import sanitize_metadata, validate_io_paths


# The legacy inverse-normal routine returns +/-9999 when a probability is
# exactly 0 or 1.  These are finite sentinel values for an infinite z-score,
# not usable grid index values.  Keep the 1D core compatible with the legacy
# program, but normalize these sentinels to NaN at the NetCDF/grid boundary.
OUTPUT_INVALID_VALUES: tuple[float, ...] = (-99.0, -9999.0, 9999.0)


def _as_float_array(values: Any) -> np.ndarray:
    if np.ma.isMaskedArray(values):
        return np.asarray(values.filled(np.nan), dtype=float)
    return np.asarray(values, dtype=float)


def calculate_sti_grid(
    monthly_temperature: Any,
    *,
    time_axis: int = 0,
    scale: int = 3,
    start_year: int = 1961,
    missing_values: Sequence[float] = MISSING_VALUES,
    round_output: bool = False,
    output_decimals: int = 2,
) -> np.ndarray:
    """Calculate STI independently for every non-time grid cell.

    Parameters
    ----------
    monthly_temperature:
        Numeric array with a time dimension and one or more spatial
        dimensions. NaN, -99 and -9999 are treated as missing.
    time_axis:
        Position of the monthly time dimension in the input array.

    Returns
    -------
    numpy.ndarray
        An array with the same shape and dimension order as the input. Missing
        STI values are represented as NaN in the grid boundary.
    """

    array = _as_float_array(monthly_temperature)
    if array.ndim < 2:
        raise ValueError("monthly_temperature must have a time and spatial dimension")
    if not -array.ndim <= time_axis < array.ndim:
        raise ValueError("time_axis is outside the input array dimensions")
    normalized_time_axis = time_axis % array.ndim

    time_first = np.moveaxis(array, normalized_time_axis, 0)
    if time_first.shape[0] == 0 or time_first.shape[0] % 12 != 0:
        raise ValueError("the time dimension must contain a non-zero multiple of 12 months")

    output_first = np.full(time_first.shape, np.nan, dtype=float)
    input_flat = time_first.reshape(time_first.shape[0], -1)
    output_flat = output_first.reshape(output_first.shape[0], -1)

    for cell_index in range(input_flat.shape[1]):
        series = input_flat[:, cell_index]
        if not np.any(np.isfinite(series) & ~np.isin(series, missing_values)):
            continue
        result = calculate_sti_result(
            series,
            scale=scale,
            start_year=start_year,
            missing_values=missing_values,
            missing_output=-99.0,
            round_output=round_output,
            output_decimals=output_decimals,
        )
        values = np.asarray(result.values, dtype=float)
        values[np.isin(values, np.asarray(OUTPUT_INVALID_VALUES))] = np.nan
        output_flat[:, cell_index] = values

    return np.moveaxis(output_first, 0, normalized_time_axis)


def calculate_sti_netcdf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    temperature_variable: str = "t2m",
    output_variable: str = "STI",
    time_dimension: str = "time",
    scale: int = 3,
    start_year: int = 1961,
    missing_values: Sequence[float] = MISSING_VALUES,
    round_output: bool = False,
    output_decimals: int = 2,
    input_engine: str = "scipy",
    output_engine: str = "scipy",
    output_format: str = "NETCDF3_64BIT",
    output_chunks: Mapping[str, int] | None = None,
    compression_level: int | None = None,
    overwrite: bool = False,
) -> Path:
    """Read a temperature variable, calculate grid STI, and write NetCDF.

    The current prototype uses xarray's SciPy NetCDF3 backend.  This avoids a
    Windows Unicode-path limitation observed with the netCDF4 native writer on
    the Chinese project directory, while the resulting NetCDF3 64-bit file is
    readable by netCDF4 and xarray.  The source temperature file is not
    modified.
    """

    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("calculate_sti_netcdf requires xarray") from exc

    source_path = Path(input_path).resolve()
    destination_path = Path(output_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    validate_io_paths(
        inputs={"temperature": source_path},
        outputs={"sti": destination_path},
        overwrite=overwrite,
    )

    actual_output_engine = resolve_netcdf_engine(output_engine, output_format)
    with open_netcdf(source_path, engine=input_engine) as source:
        if temperature_variable not in source.data_vars:
            raise KeyError(f"temperature variable not found: {temperature_variable}")
        source_temperature = source[temperature_variable]
        if time_dimension not in source_temperature.dims:
            raise ValueError(
                f"{temperature_variable} does not contain time dimension {time_dimension}"
            )
        source_dimensions = tuple(source_temperature.dims)
        time_axis = source_dimensions.index(time_dimension)
        temperature = source_temperature.values
        output = calculate_sti_grid(
            temperature,
            time_axis=time_axis,
            scale=scale,
            start_year=start_year,
            missing_values=missing_values,
            round_output=round_output,
            output_decimals=output_decimals,
        )

        coordinates = {
            dimension_name: source[dimension_name]
            for dimension_name in source_dimensions
            if dimension_name in source.coords
        }
        result_data = xr.DataArray(
            output,
            dims=source_dimensions,
            coords=coordinates,
            name=output_variable,
        )
        result_dataset = xr.Dataset(
            {output_variable: result_data},
            attrs=sanitize_metadata(dict(source.attrs)),
        )
        result_dataset[output_variable].attrs.update(
            {
                "long_name": "Standardized Temperature Index",
                "method": "spigenerator_compatible",
                "time_scale_months": int(scale),
                "calculation_start_year": int(start_year),
                "missing_value": np.nan,
                "netcdf_engine": actual_output_engine,
                "netcdf_format": str(output_format).upper(),
                "netcdf_chunks": str(dict(output_chunks)) if output_chunks else "{}",
            }
        )
        result_dataset[time_dimension].attrs.pop("calendar", None)
        result_dataset[time_dimension].encoding["calendar"] = "proleptic_gregorian"

    write_netcdf(
        result_dataset,
        destination_path,
        engine=output_engine,
        output_format=output_format,
        chunks=output_chunks,
        compression_level=compression_level,
    )
    result_dataset.close()

    return destination_path
