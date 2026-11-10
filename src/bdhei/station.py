"""Calculate SPEI, STI and BDHEI directly from station monthly climate tables."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .common import DEFAULT_MONTHS, _monthly_years, _resolve_path, _validate_months, precipitation_to_mm, temperature_to_celsius
from .grid_bdhei import calculate_bdhei_grid
from .grid_sti import calculate_sti_grid
from .path_safety import privacy_safe_path, sanitize_metadata, validate_io_paths
from .spei import calculate_spei_grid, validate_spei_scale


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=object)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gbk", dtype=object)
    if path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}:
        return pd.read_excel(path, dtype=object)
    raise ValueError("station input must be CSV, XLSX, XLS or XLSM")


def _ids(values: pd.Series) -> pd.Series:
    if values.isna().any():
        raise ValueError("station ids must be present")
    # Treat spreadsheet station numbers such as 12345.0 as 12345.
    return values.map(lambda x: str(int(x)) if isinstance(x, (float, np.floating)) and np.isfinite(x) and x.is_integer() else str(x).strip())


def _numeric(values: pd.Series, name: str, missing_values: list[float] | None = None) -> np.ndarray:
    numbers = pd.to_numeric(values, errors="coerce")
    if (values.notna() & numbers.isna()).any():
        raise ValueError(f"{name} contains non-numeric values")
    array = numbers.to_numpy(dtype=float)
    if missing_values is not None:
        array[np.isin(array, missing_values)] = np.nan
    if np.isinf(array).any():
        raise ValueError(f"{name} contains infinite values")
    return array


def calculate_station_from_config(config: Mapping[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    """Fit each station separately, retaining the full monthly output sequence."""
    scale = validate_spei_scale(config.get("spei_scale", 3))
    spei_name = f"SPEI_{scale}"
    sti_scale = config.get("sti_scale", 3)
    if isinstance(sti_scale, bool) or not isinstance(sti_scale, int) or not 1 <= sti_scale <= 12:
        raise ValueError("sti_scale must be an integer from 1 to 12")
    months = _validate_months(config.get("months", DEFAULT_MONTHS))
    overwrite = config.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be true or false")
    if not config.get("input") or not config.get("output"):
        raise ValueError("station configuration requires input and output")
    source = _resolve_path(config["input"], base_dir)
    destination = _resolve_path(str(config["output"]).replace("{spei_scale}", str(scale)), base_dir)
    if destination.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValueError("station output must be CSV or XLSX")
    def auxiliary_path(key: str, default: Path) -> Path:
        value = str(config[key]).replace("{spei_scale}", str(scale)) if config.get(key) else default
        return _resolve_path(value, base_dir)
    diagnostics = auxiliary_path("diagnostics", destination.with_name(destination.stem + "_diagnostics.csv"))
    summary = auxiliary_path("summary", destination.with_suffix(".json"))
    coordinate_file = _resolve_path(config["coordinate_file"], base_dir) if config.get("coordinate_file") else None
    inputs = {"station": source}
    if coordinate_file and coordinate_file != source:
        inputs["coordinates"] = coordinate_file
    validate_io_paths(inputs=inputs, outputs={"result": destination, "diagnostics": diagnostics, "summary": summary}, overwrite=overwrite)
    raw = _read_table(source)
    id_name = str(config.get("station_id_column", "station_id"))
    t_name = str(config.get("temperature_column", "temperature"))
    p_name = str(config.get("precipitation_column", "precipitation"))
    required = {id_name, t_name, p_name}
    if not required.issubset(raw.columns):
        raise ValueError(f"missing station climate columns: {sorted(required - set(raw.columns))}")
    table = pd.DataFrame({"station_id": _ids(raw[id_name])})
    if table.station_id.eq("").any():
        raise ValueError("station ids must be present")
    date_name = str(config.get("date_column", "date"))
    if date_name in raw:
        dates = pd.to_datetime(raw[date_name], errors="coerce")
    else:
        year_name, month_name = str(config.get("year_column", "year")), str(config.get("month_column", "month"))
        if year_name not in raw or month_name not in raw:
            raise ValueError("provide a date column or year and month columns")
        years = _numeric(raw[year_name], year_name)
        month_numbers = _numeric(raw[month_name], month_name)
        if not np.isfinite(years).all() or not np.isfinite(month_numbers).all() or np.any(years != np.floor(years)) or np.any(month_numbers != np.floor(month_numbers)):
            raise ValueError("year and month must be finite integers")
        dates = pd.to_datetime({"year": years, "month": month_numbers, "day": 1}, errors="coerce")
    if dates.isna().any():
        raise ValueError("station input contains invalid dates")
    table["date"] = dates.dt.to_period("M").dt.to_timestamp()
    if table.duplicated(["station_id", "date"]).any():
        raise ValueError("duplicate station/month rows")
    missing_values = config.get("missing_values", [-99.0, -9999.0])
    table["temperature_celsius"] = temperature_to_celsius(_numeric(raw[t_name], t_name, missing_values), str(config.get("temperature_unit", "celsius")))
    table["precipitation_mm"] = precipitation_to_mm(_numeric(raw[p_name], p_name, missing_values), str(config.get("precipitation_unit", "mm/month")), table.date.dt.days_in_month.to_numpy())
    if (table.precipitation_mm.dropna() < 0).any():
        raise ValueError("monthly precipitation must be non-negative")
    lat_name, lon_name = str(config.get("latitude_column", "latitude")), str(config.get("longitude_column", "longitude"))
    if coordinate_file:
        coordinates = raw if coordinate_file == source else _read_table(coordinate_file)
        coordinate_id = str(config.get("coordinate_station_id_column", id_name))
        coordinate_lat = str(config.get("coordinate_latitude_column", lat_name))
        coordinate_lon = str(config.get("coordinate_longitude_column", lon_name))
        if coordinate_id not in coordinates or coordinate_lat not in coordinates:
            raise ValueError("coordinate table requires station id and latitude columns")
        coords = pd.DataFrame({"station_id": _ids(coordinates[coordinate_id]), "latitude": _numeric(coordinates[coordinate_lat], coordinate_lat)})
        if coordinate_lon in coordinates:
            coords["longitude"] = _numeric(coordinates[coordinate_lon], coordinate_lon)
        if coords.station_id.duplicated().any():
            raise ValueError("coordinate table must contain one row per station")
        table = table.merge(coords, on="station_id", how="left", validate="many_to_one")
    else:
        if lat_name not in raw:
            raise ValueError("station latitude is required for Thornthwaite PET; provide latitude_column or coordinate_file")
        table["latitude"] = _numeric(raw[lat_name], lat_name)
        if lon_name in raw:
            table["longitude"] = _numeric(raw[lon_name], lon_name)
    if table.empty:
        raise ValueError("station climate input is empty")
    if table.latitude.isna().any() or (table.latitude.abs() > 90).any():
        raise ValueError("each station requires a latitude between -90 and 90")
    if "longitude" not in table:
        table["longitude"] = np.nan
    for name in ("latitude", "longitude"):
        if table.groupby("station_id")[name].nunique(dropna=False).gt(1).any():
            raise ValueError(f"{name} must be constant within each station")
    table = table.sort_values(["station_id", "date"], kind="stable").reset_index(drop=True)
    # Validate every station before beginning calculations or writing outputs.
    groups = []
    for station_id, group in table.groupby("station_id", sort=True):
        start, end = _monthly_years(group.date.to_numpy())
        calibration_start = int(config.get("calibration_year_initial", start))
        calibration_end = int(config.get("calibration_year_final", end))
        if not start <= calibration_start <= calibration_end <= end:
            raise ValueError(f"station {station_id}: SPEI calibration years must lie within the input years")
        groups.append((station_id, group, start, end, calibration_start, calibration_end))
    table["STI"], table[spei_name], table["BDHEI"] = np.nan, np.nan, np.nan
    rows = []
    for station_id, group, start, end, calibration_start, calibration_end in groups:
        t = group.temperature_celsius.to_numpy()[:, None, None]
        p = group.precipitation_mm.to_numpy()[:, None, None]
        latitude, longitude = float(group.latitude.iloc[0]), float(group.longitude.iloc[0])
        sti = calculate_sti_grid(t, scale=sti_scale, start_year=start)
        spei = calculate_spei_grid(p, t, [latitude], scale=scale, data_start_year=start,
            calibration_year_initial=calibration_start, calibration_year_final=calibration_end)
        result = calculate_bdhei_grid(spei, sti, group.date.to_numpy(), [latitude], [longitude], months=months)
        table.loc[group.index, ["STI", spei_name, "BDHEI"]] = np.column_stack([sti[:, 0, 0], spei[:, 0, 0], result.values[:, 0, 0]])
        row = result.diagnostics.iloc[0].to_dict()
        row.pop("latitude_index", None)
        row.pop("longitude_index", None)
        row.update(station_id=str(station_id), spei_scale=scale, sti_scale=sti_scale, analysis_start_year=start,
            analysis_end_year=end, calibration_year_initial=calibration_start, calibration_year_final=calibration_end)
        rows.append(row)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".csv":
        table.to_csv(destination, index=False, encoding="utf-8-sig")
    else:
        table.to_excel(destination, index=False)
    diagnostic_table = pd.DataFrame(rows)
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_table.to_csv(diagnostics, index=False, encoding="utf-8-sig")
    counts = {str(key): int(value) for key, value in diagnostic_table.status.value_counts().items()}
    payload = {"status": "OK_WITH_FAILED_STATIONS" if counts.get("fit_failed", 0) else "OK", "mode": "station",
        "input": privacy_safe_path(source, base_dir=base_dir), "output": privacy_safe_path(destination, base_dir=base_dir),
        "diagnostics": privacy_safe_path(diagnostics, base_dir=base_dir), "summary": privacy_safe_path(summary, base_dir=base_dir),
        "station_count": len(groups), "row_count": len(table), "spei_scale": scale, "spei_variable": spei_name,
        "sti_scale": sti_scale, "months": list(months), "status_counts": counts,
        "valid_spei_count": int(table[spei_name].notna().sum()), "valid_bdhei_count": int(table.BDHEI.notna().sum())}
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(sanitize_metadata(payload, base_dir=base_dir), ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
