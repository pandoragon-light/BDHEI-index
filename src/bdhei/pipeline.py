"""File-level station and grid pipelines for the unified BDHEI tool.

The numerical contracts live in :mod:`bdhei.sti`, :mod:`bdhei.spei`, and
:mod:`bdhei.core`.  This module only handles files, grouping, coordinates,
diagnostics, and reproducible output.  It deliberately does not alter the
reference calculation formulas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .netcdf_io import open_netcdf, resolve_netcdf_engine, write_netcdf
from .path_safety import privacy_safe_path, sanitize_metadata, validate_io_paths
from .spei import validate_spei_scale


DEFAULT_MONTHS: tuple[int, ...] = (6, 7, 8)


def _resolve_path(value: str | Path, base_dir: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path(base_dir) / path
    return path.resolve()


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gbk")
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("station input must be CSV, XLSX, XLSM, or XLS")


def _write_table(table: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        table.to_csv(path, index=False, encoding="utf-8-sig")
    elif suffix in {".xlsx", ".xlsm"}:
        table.to_excel(path, index=False)
    else:
        raise ValueError("station output must be CSV, XLSX, or XLSM")


def _validate_months(months: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(int(month) for month in months)
    if not normalized or not set(normalized).issubset(set(range(1, 13))):
        raise ValueError("months must contain calendar months from 1 to 12")
    return normalized


def _finite_count(values: pd.Series) -> int:
    return int(np.isfinite(pd.to_numeric(values, errors="coerce")).sum())


def calculate_station_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    diagnostics_path: str | Path | None = None,
    date_column: str = "date",
    drought_column: str = "SPEI_3",
    heat_column: str = "STI",
    station_id_column: str | None = None,
    output_column: str = "BDHEI",
    months: Sequence[int] = DEFAULT_MONTHS,
    eps: float = 1e-6,
    ppf_clip: tuple[float, float] = (0.0001, 0.9999),
    overwrite: bool = False,
) -> dict[str, Any]:
    """Calculate BDHEI independently for one or more station groups.

    The input table must contain a date column and paired SPEI/STI columns.
    If ``station_id_column`` is supplied, each station is fitted separately;
    without it, the entire table is treated as one station sequence.  Rows
    outside ``months`` are preserved and receive a missing BDHEI value.
    """

    from .core import calculate_bdhei

    source = Path(input_path).resolve()
    destination = Path(output_path).resolve()
    diagnostics_file = Path(diagnostics_path).resolve() if diagnostics_path else destination.with_name(destination.stem + "_diagnostics.csv")
    if not source.exists():
        raise FileNotFoundError(source)
    validate_io_paths(
        inputs={"station": source},
        outputs={"result": destination, "diagnostics": diagnostics_file},
        overwrite=overwrite,
    )
    months = _validate_months(months)

    table = _read_table(source).copy()
    required = {date_column, drought_column, heat_column}
    missing = sorted(required.difference(table.columns))
    if missing:
        raise KeyError(f"missing station columns: {missing}")
    if station_id_column is not None and station_id_column not in table.columns:
        raise KeyError(f"missing station id column: {station_id_column}")

    table[date_column] = pd.to_datetime(table[date_column], errors="coerce")
    if table[date_column].isna().any():
        raise ValueError(f"{date_column} contains invalid dates")
    table[drought_column] = pd.to_numeric(table[drought_column], errors="coerce")
    table[heat_column] = pd.to_numeric(table[heat_column], errors="coerce")

    duplicate_subset = [date_column] if station_id_column is None else [station_id_column, date_column]
    if table.duplicated(subset=duplicate_subset).any():
        raise ValueError("station input contains duplicate dates within a station group")

    if station_id_column is None:
        group_values: list[tuple[str, pd.Index]] = [("__single_station__", table.index)]
    else:
        if table[station_id_column].isna().any():
            raise ValueError(f"{station_id_column} contains missing station ids")
        group_values = [
            (str(station_id), index)
            for station_id, index in table.groupby(station_id_column, sort=True).groups.items()
        ]

    # A chronological series is required by the reference core.  Sorting is
    # stable and deterministic; the output is written in station/date order.
    table = table.sort_values(
        [station_id_column, date_column] if station_id_column else [date_column],
        kind="mergesort",
    ).reset_index(drop=True)
    if station_id_column is None:
        group_values = [("__single_station__", table.index)]
    else:
        group_values = [
            (str(station_id), group.index)
            for station_id, group in table.groupby(station_id_column, sort=True)
        ]

    table[output_column] = np.nan
    table["BDHEI_Copula_Type"] = None
    table["BDHEI_Copula_Params"] = None
    diagnostics: list[dict[str, Any]] = []

    for station_id, indices in group_values:
        group = table.loc[indices]
        selected = group[date_column].dt.month.isin(months)
        valid = selected & group[drought_column].notna() & group[heat_column].notna()
        if not valid.any():
            diagnostics.append(
                {
                    "station_id": None if station_id == "__single_station__" else station_id,
                    "status": "no_valid_data",
                    "selected_n": int(selected.sum()),
                    "valid_n": 0,
                    "copula_type": None,
                    "copula_params": None,
                }
            )
            continue

        valid_indices = group.index[valid.to_numpy(dtype=bool)]
        frame = group.loc[valid_indices, [drought_column, heat_column]].rename(
            columns={drought_column: "SPEI", heat_column: "STI"}
        )
        result = calculate_bdhei(frame, drought_col="SPEI", eps=eps, ppf_clip=ppf_clip)
        table.loc[valid_indices, output_column] = result.data["BDHEI"].to_numpy(dtype=float)
        table.loc[valid_indices, "BDHEI_Copula_Type"] = result.copula_type
        table.loc[valid_indices, "BDHEI_Copula_Params"] = str(result.copula_params)
        diagnostics.append(
            {
                "station_id": None if station_id == "__single_station__" else station_id,
                "status": "ok",
                "selected_n": int(selected.sum()),
                "valid_n": int(valid.sum()),
                "copula_type": result.copula_type,
                "copula_params": result.copula_params,
                "analysis_start": group.loc[selected, date_column].min().strftime("%Y-%m-%d") if selected.any() else None,
                "analysis_end": group.loc[selected, date_column].max().strftime("%Y-%m-%d") if selected.any() else None,
            }
        )

    _write_table(table, destination)
    diagnostics_file.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_frame = pd.DataFrame(diagnostics)
    if "copula_params" in diagnostics_frame.columns:
        diagnostics_frame["copula_params"] = diagnostics_frame["copula_params"].map(
            lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
        )
    diagnostics_frame.to_csv(diagnostics_file, index=False, encoding="utf-8-sig")

    return {
        "status": "OK" if all(row["status"] == "ok" for row in diagnostics) else "OK_WITH_EMPTY_STATIONS",
        "input": privacy_safe_path(source),
        "output": privacy_safe_path(destination),
        "diagnostics": privacy_safe_path(diagnostics_file),
        "station_count": len(diagnostics),
        "row_count": len(table),
        "selected_months": list(months),
        "selected_row_count": int(table[date_column].dt.month.isin(months).sum()),
        "valid_bdhei_row_count": int(table[output_column].notna().sum()),
        "station_diagnostics": diagnostics,
    }


def calculate_grid_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    diagnostics_path: str | Path | None = None,
    spei_variable: str = "SPEI_3",
    sti_variable: str = "STI",
    time_dimension: str = "time",
    latitude_dimension: str = "latitude",
    longitude_dimension: str = "longitude",
    months: Sequence[int] = DEFAULT_MONTHS,
    eps: float = 1e-6,
    ppf_clip: tuple[float, float] = (0.0001, 0.9999),
    input_engine: str = "scipy",
    output_engine: str = "scipy",
    output_format: str = "NETCDF3_64BIT",
    output_chunks: Mapping[str, int] | None = None,
    compression_level: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Calculate BDHEI from a paired SPEI/STI NetCDF grid."""

    import xarray as xr

    from .grid_bdhei import calculate_bdhei_grid

    source_path = Path(input_path).resolve()
    destination_path = Path(output_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    months = _validate_months(months)
    diagnostics_file = Path(diagnostics_path).resolve() if diagnostics_path else destination_path.with_name(destination_path.stem + "_diagnostics.csv")
    validate_io_paths(
        inputs={"grid": source_path},
        outputs={"result": destination_path, "diagnostics": diagnostics_file},
        overwrite=overwrite,
    )

    actual_output_engine = resolve_netcdf_engine(output_engine, output_format)
    with open_netcdf(source_path, engine=input_engine) as source:
        required = {spei_variable, sti_variable, time_dimension, latitude_dimension, longitude_dimension}
        missing = sorted(required.difference(source.variables))
        if missing:
            raise KeyError(f"missing grid variables or coordinates: {missing}")
        spei = np.asarray(
            source[spei_variable].transpose(time_dimension, latitude_dimension, longitude_dimension).values,
            dtype=float,
        )
        sti = np.asarray(
            source[sti_variable].transpose(time_dimension, latitude_dimension, longitude_dimension).values,
            dtype=float,
        )
        time = np.asarray(source[time_dimension].values)
        latitude = np.asarray(source[latitude_dimension].values, dtype=float)
        longitude = np.asarray(source[longitude_dimension].values, dtype=float)
        if spei.shape != sti.shape or spei.ndim != 3:
            raise ValueError(f"paired grid arrays must have equal 3D shapes, got {spei.shape} and {sti.shape}")

        grid_result = calculate_bdhei_grid(
            spei,
            sti,
            time,
            latitude,
            longitude,
            months=months,
            eps=eps,
            ppf_clip=ppf_clip,
        )
        diagnostics = grid_result.diagnostics.copy()
        status_codes = {"ok": 0, "no_valid_data": 1, "fit_failed": 2}
        copula_names = sorted(name for name in diagnostics["copula_type"].dropna().unique().tolist())
        copula_codes = {name: index + 1 for index, name in enumerate(copula_names)}
        diagnostics["status_code"] = diagnostics["status"].map(status_codes).astype(int)
        diagnostics["copula_code"] = diagnostics["copula_type"].map(copula_codes).fillna(0).astype(int)
        shape = (len(latitude), len(longitude))
        valid_n = diagnostics["valid_n"].to_numpy(dtype=np.int32).reshape(shape)
        status_code = diagnostics["status_code"].to_numpy(dtype=np.int16).reshape(shape)
        copula_code = diagnostics["copula_code"].to_numpy(dtype=np.int16).reshape(shape)

        result = xr.Dataset(
            {
                "BDHEI": xr.DataArray(
                    grid_result.values,
                    dims=(time_dimension, latitude_dimension, longitude_dimension),
                    coords={time_dimension: time, latitude_dimension: latitude, longitude_dimension: longitude},
                    attrs={
                        "long_name": "Blended Drought and High-temperature Evapotranspiration Index",
                        "units": "1",
                        "method": "reference BDHEI core; independent KDE/Copula fit per grid cell",
                        "formula": "P = 1 - F_STI + C(F_SPEI, F_STI); BDHEI = norm.ppf(P)",
                        "spei_variable": spei_variable,
                        "calculation_months": ",".join(str(month) for month in months),
                        "missing_value": "NaN",
                    },
                ),
                spei_variable: ((time_dimension, latitude_dimension, longitude_dimension), spei),
                sti_variable: ((time_dimension, latitude_dimension, longitude_dimension), sti),
                "valid_n": ((latitude_dimension, longitude_dimension), valid_n),
                "copula_code": ((latitude_dimension, longitude_dimension), copula_code),
                "status_code": ((latitude_dimension, longitude_dimension), status_code),
            },
            attrs={
                "title": "BDHEI grid calculation",
                "source_file": privacy_safe_path(source_path),
                "calculation_months": ",".join(str(month) for month in months),
                "copula_code_mapping": json.dumps(copula_codes, ensure_ascii=False),
                "status_code_mapping": json.dumps(status_codes, ensure_ascii=False),
                "diagnostics_file": privacy_safe_path(diagnostics_file),
                "netcdf_engine": actual_output_engine,
                "netcdf_format": str(output_format).upper(),
                "netcdf_chunks": json.dumps(dict(output_chunks), ensure_ascii=False) if output_chunks else "{}",
            },
        )
        result[spei_variable].attrs.update(dict(source[spei_variable].attrs))
        result[sti_variable].attrs.update(dict(source[sti_variable].attrs))
        result["valid_n"].attrs.update({"long_name": "valid paired observations used per grid cell", "units": "1"})
        result["copula_code"].attrs.update({"long_name": "selected copula code; see copula_code_mapping", "units": "1"})
        result["status_code"].attrs.update({"long_name": "grid calculation status code; see status_code_mapping", "units": "1"})
        if time_dimension in result:
            result[time_dimension].attrs.pop("calendar", None)
            result[time_dimension].encoding["calendar"] = "proleptic_gregorian"
        if latitude_dimension in source:
            result[latitude_dimension].attrs.update(dict(source[latitude_dimension].attrs))
        if longitude_dimension in source:
            result[longitude_dimension].attrs.update(dict(source[longitude_dimension].attrs))
        io_settings = write_netcdf(
            result,
            destination_path,
            engine=output_engine,
            output_format=output_format,
            chunks=output_chunks,
            compression_level=compression_level,
        )
        result.close()

    diagnostics_file.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(diagnostics_file, index=False, encoding="utf-8-sig")
    selected_mask = np.isin(time.astype("datetime64[M]").astype(int) % 12 + 1, months)
    finite_bdhei = np.isfinite(grid_result.values[selected_mask])
    status_counts = {str(key): int(value) for key, value in diagnostics["status"].value_counts().to_dict().items()}
    finite_values = grid_result.values[np.isfinite(grid_result.values)]
    return {
        "status": "OK" if status_counts.get("fit_failed", 0) == 0 else "OK_WITH_FAILED_CELLS",
        "input": privacy_safe_path(source_path),
        "output": privacy_safe_path(destination_path),
        "diagnostics": privacy_safe_path(diagnostics_file),
        "dimensions": {"time": int(grid_result.values.shape[0]), "latitude": int(grid_result.values.shape[1]), "longitude": int(grid_result.values.shape[2])},
        "calculation_months": list(months),
        "selected_observations_per_cell": int(selected_mask.sum()),
        "finite_bdhei_count": int(finite_bdhei.sum()),
        "status_counts": status_counts,
        "copula_counts": {str(key): int(value) for key, value in diagnostics["copula_type"].dropna().value_counts().to_dict().items()},
        "bdhei_range": [float(np.min(finite_values)), float(np.max(finite_values))] if finite_values.size else [None, None],
        "netcdf_io": io_settings,
    }


def calculate_from_config(config: Mapping[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    """Dispatch a flat station/grid configuration dictionary."""

    mode = str(config.get("mode", "")).lower()
    spei_scale = validate_spei_scale(config.get("spei_scale", 3))
    spei_name = f"SPEI_{spei_scale}"
    for key in ("drought_column", "spei_variable"):
        if config.get(key) in {"SPEI_1", "SPEI_3"} and config[key] != spei_name:
            raise ValueError(f"{key} conflicts with spei_scale")
    overwrite_value = config.get("overwrite", False)
    if not isinstance(overwrite_value, bool):
        raise ValueError("overwrite must be true or false")
    overwrite = overwrite_value
    summary_path = _resolve_path(config["summary"], base_dir) if config.get("summary") else None
    if mode == "station":
        source_path = _resolve_path(config["input"], base_dir)
        destination_path = _resolve_path(config["output"], base_dir)
        diagnostics_path = (
            _resolve_path(config["diagnostics"], base_dir)
            if config.get("diagnostics")
            else destination_path.with_name(destination_path.stem + "_diagnostics.csv")
        )
        validate_io_paths(
            inputs={"station": source_path},
            outputs={
                "result": destination_path,
                "diagnostics": diagnostics_path,
                "summary": summary_path,
            },
            overwrite=overwrite,
        )
        result = calculate_station_file(
            source_path,
            destination_path,
            diagnostics_path=diagnostics_path,
            date_column=str(config.get("date_column", "date")),
            drought_column=str(config.get("drought_column", spei_name)),
            heat_column=str(config.get("heat_column", "STI")),
            station_id_column=str(config["station_id_column"]) if config.get("station_id_column") else None,
            output_column=str(config.get("output_column", "BDHEI")),
            months=config.get("months", DEFAULT_MONTHS),
            eps=float(config.get("eps", 1e-6)),
            ppf_clip=tuple(float(value) for value in config.get("ppf_clip", (0.0001, 0.9999))),
            overwrite=overwrite,
        )
    elif mode == "grid":
        source_path = _resolve_path(config["input"], base_dir)
        destination_path = _resolve_path(config["output"], base_dir)
        diagnostics_path = (
            _resolve_path(config["diagnostics"], base_dir)
            if config.get("diagnostics")
            else destination_path.with_name(destination_path.stem + "_diagnostics.csv")
        )
        validate_io_paths(
            inputs={"grid": source_path},
            outputs={
                "result": destination_path,
                "diagnostics": diagnostics_path,
                "summary": summary_path,
            },
            overwrite=overwrite,
        )
        result = calculate_grid_file(
            source_path,
            destination_path,
            diagnostics_path=diagnostics_path,
            spei_variable=str(config.get("spei_variable", spei_name)),
            sti_variable=str(config.get("sti_variable", "STI")),
            time_dimension=str(config.get("time_dimension", "time")),
            latitude_dimension=str(config.get("latitude_dimension", "latitude")),
            longitude_dimension=str(config.get("longitude_dimension", "longitude")),
            months=config.get("months", DEFAULT_MONTHS),
            eps=float(config.get("eps", 1e-6)),
            ppf_clip=tuple(float(value) for value in config.get("ppf_clip", (0.0001, 0.9999))),
            input_engine=str(config.get("input_engine", "scipy")),
            output_engine=str(config.get("output_engine", "scipy")),
            output_format=str(config.get("output_format", "NETCDF3_64BIT")),
            output_chunks=config.get("output_chunks", config.get("chunks")),
            compression_level=(
                int(config["compression_level"])
                if config.get("compression_level") is not None
                else None
            ),
            overwrite=overwrite,
        )
    else:
        raise ValueError("config mode must be 'station' or 'grid'")

    result["spei_scale"] = spei_scale
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_payload = sanitize_metadata(result, base_dir=base_dir)
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        result["summary"] = privacy_safe_path(summary_path, base_dir=base_dir)
    return result
