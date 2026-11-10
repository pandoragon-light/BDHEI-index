from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import xarray as xr

from bdhei.climate import calculate_climate_from_config
from bdhei.station import calculate_station_from_config
from test_climate import synthetic_climate


def synthetic_stations() -> pd.DataFrame:
    grid = synthetic_climate()
    return pd.concat([
        pd.DataFrame({"station_id": station, "date": pd.to_datetime(grid.date.values),
            "temperature": grid.tas.values[:, lat, lon], "precipitation": grid.pr.values[:, lat, lon],
            "latitude": float(grid.lat.values[lat]), "longitude": float(grid.lon.values[lon])})
        for lat, lon, station in [(0, 0, "001"), (0, 1, "002"), (1, 1, "EMPTY")]
    ], ignore_index=True)


class StationClimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "station.csv"
        self.data = synthetic_stations()
        self.data.iloc[::-1].to_csv(self.source, index=False)
        self.config = {"input": "station.csv", "output": "station_spei{spei_scale}.csv"}

    def test_both_scales_match_equivalent_grid_and_preserve_station_ids(self):
        grid_source = self.root / "climate.nc"
        synthetic_climate().to_netcdf(grid_source, engine="scipy")
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        previous_sti = None
        for scale in (3, 1):
            with self.subTest(scale=scale):
                station_result = calculate_station_from_config({**self.config, "spei_scale": scale}, base_dir=self.root)
                grid_result = calculate_climate_from_config({"input": str(grid_source), "output": f"grid{scale}.nc",
                    "spei_scale": scale, "temperature_variable": "tas", "precipitation_variable": "pr",
                    "time_dimension": "date", "latitude_dimension": "lat", "longitude_dimension": "lon",
                    "input_engine": "scipy", "output_engine": "scipy", "output_format": "NETCDF3_64BIT", "compression_level": None}, base_dir=self.root)
                table = pd.read_csv(self.root / station_result["output"], dtype={"station_id": str})
                self.assertEqual(station_result["status_counts"], {"ok": 2, "no_valid_data": 1})
                self.assertEqual(station_result["station_count"], 3)
                self.assertEqual(station_result["valid_bdhei_count"], 478 * 2)
                self.assertEqual(station_result["months"], list(range(1, 13)))
                self.assertEqual(station_result["valid_spei_count"], (480 - scale + 1) * 2)
                self.assertEqual(set(table.station_id), {"001", "002", "EMPTY"})
                valid_months = pd.to_datetime(table.loc[table.BDHEI.notna(), "date"]).dt.month
                self.assertEqual(set(valid_months), set(range(1, 13)))
                name = f"SPEI_{scale}"
                self.assertNotIn(f"SPEI_{4-scale}", table)
                with xr.open_dataset(self.root / grid_result["output"], engine="scipy") as grid:
                    for station, lat, lon in [("001", 0, 0), ("002", 0, 1), ("EMPTY", 1, 1)]:
                        rows = table[table.station_id == station]
                        for variable in ("temperature_celsius", "precipitation_mm", "STI", name, "BDHEI"):
                            np.testing.assert_allclose(rows[variable], grid[variable].values[:, lat, lon], atol=1e-12, equal_nan=True)
                if previous_sti is not None:
                    np.testing.assert_array_equal(previous_sti, table.STI)
                previous_sti = table.STI.copy()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_custom_bdhei_months_preserve_full_year_spei_and_sti(self):
        annual = calculate_station_from_config(self.config, base_dir=self.root)
        seasonal = calculate_station_from_config({**self.config, "months": [6, 7, 8], "output": "summer.csv"}, base_dir=self.root)
        self.assertEqual(seasonal["valid_bdhei_count"], 240)
        a = pd.read_csv(self.root / annual["output"])
        b = pd.read_csv(self.root / seasonal["output"])
        for name in ("SPEI_3", "STI"):
            np.testing.assert_array_equal(a[name], b[name])
        selected = pd.to_datetime(b.date).dt.month.isin([6, 7, 8])
        self.assertTrue(b.loc[~selected, "BDHEI"].isna().all())

    def test_excel_year_month_and_separate_coordinates_match_csv(self):
        expected = calculate_station_from_config(self.config, base_dir=self.root)
        raw = self.data.copy()
        raw["year"], raw["month"] = raw.date.dt.year, raw.date.dt.month
        raw["temperature"] += 273.15
        raw["precipitation"] = raw.precipitation / 1000 / raw.date.dt.days_in_month
        raw = raw.rename(columns={"station_id": "station", "temperature": "tas", "precipitation": "tp"})
        raw.drop(columns=["date", "latitude", "longitude"]).to_excel(self.root / "station.xlsx", index=False)
        self.data[["station_id", "latitude", "longitude"]].drop_duplicates().to_csv(self.root / "coordinates.csv", index=False)
        actual = calculate_station_from_config({**self.config, "input": "station.xlsx", "output": "excel_result.xlsx",
            "coordinate_file": "coordinates.csv", "coordinate_station_id_column": "station_id",
            "station_id_column": "station", "temperature_column": "tas", "precipitation_column": "tp",
            "temperature_unit": "kelvin", "precipitation_unit": "m/day"}, base_dir=self.root)
        a = pd.read_excel(self.root / actual["output"], dtype={"station_id": str})
        b = pd.read_csv(self.root / expected["output"], dtype={"station_id": str})
        self.assertEqual(a.station_id.tolist(), b.station_id.tolist())
        for name in ("temperature_celsius", "precipitation_mm", "STI", "SPEI_3", "BDHEI"):
            np.testing.assert_allclose(a[name], b[name], atol=1e-10)

    def test_rejects_bad_input_before_writing_results(self):
        bad_cases = []
        bad_cases.append((self.data.drop(columns="temperature"), "missing station climate"))
        bad_cases.append((pd.concat([self.data, self.data.iloc[:1]]), "duplicate station/month"))
        bad_cases.append((self.data.drop(index=5), "consecutive monthly"))
        bad_cases.append((self.data.drop(columns="latitude"), "latitude"))
        invalid = self.data.copy()
        invalid.loc[0, "latitude"] = 95
        bad_cases.append((invalid, "latitude"))
        invalid = self.data.copy()
        invalid.loc[0, "precipitation"] = -1
        bad_cases.append((invalid, "non-negative"))
        invalid = self.data.copy()
        invalid["temperature"] = invalid.temperature.astype(object)
        invalid.loc[0, "temperature"] = "invalid"
        bad_cases.append((invalid, "non-numeric"))
        for frame, error in bad_cases:
            with self.subTest(error=error):
                frame.to_csv(self.root / "bad.csv", index=False)
                with self.assertRaisesRegex(ValueError, error):
                    calculate_station_from_config({**self.config, "input": "bad.csv"}, base_dir=self.root)
                self.assertFalse((self.root / "station_spei3.csv").exists())
        with self.assertRaisesRegex(ValueError, "different"):
            calculate_station_from_config({**self.config, "output": "station.csv"}, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, "within"):
            calculate_station_from_config({**self.config, "calibration_year_final": 2021}, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, "spei_scale"):
            calculate_station_from_config({**self.config, "spei_scale": 2}, base_dir=self.root)

    def test_existing_outputs_require_explicit_overwrite(self):
        result = calculate_station_from_config(self.config, base_dir=self.root)
        with self.assertRaises(FileExistsError):
            calculate_station_from_config(self.config, base_dir=self.root)
        again = calculate_station_from_config({**self.config, "overwrite": True}, base_dir=self.root)
        self.assertEqual(result["valid_bdhei_count"], again["valid_bdhei_count"])


if __name__ == "__main__":
    unittest.main()
