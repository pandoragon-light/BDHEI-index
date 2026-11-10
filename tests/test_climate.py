from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import xarray as xr

from bdhei.climate import calculate_climate_from_config, precipitation_to_mm
from bdhei.netcdf_io import open_netcdf, write_netcdf
from bdhei.spei import calculate_spei, validate_spei_scale
from bdhei.core import calculate_bdhei


def synthetic_climate() -> xr.Dataset:
    rng = np.random.default_rng(20261110)
    dates = pd.date_range("1980-01-31", periods=40 * 12, freq="ME")
    season = np.sin(np.arange(len(dates)) * 2 * np.pi / 12)
    temperature = 19 + 9 * season[:, None, None] + rng.normal(0, 2, (len(dates), 2, 2))
    precipitation = rng.gamma(3, 25, (len(dates), 2, 2))
    temperature[:, 1, 1] = np.nan
    precipitation[:, 1, 1] = np.nan
    return xr.Dataset(
        {"tas": (("date", "lat", "lon"), temperature, {"units": "degree_Celsius"}),
         "pr": (("date", "lat", "lon"), precipitation, {"units": "mm/month"})},
        coords={"date": dates, "lat": [31.0, 30.0], "lon": [110.0, 111.0]},
    )


class ClimatePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "climate.nc"
        self.data = synthetic_climate()
        self.data.to_netcdf(self.source, engine="scipy")
        self.config = {
            "input": "climate.nc", "output": "result_spei{spei_scale}.nc",
            "temperature_variable": "tas", "precipitation_variable": "pr",
            "time_dimension": "date", "latitude_dimension": "lat", "longitude_dimension": "lon",
            "input_engine": "scipy", "output_engine": "scipy", "output_format": "NETCDF3_64BIT",
            "compression_level": None,
        }

    def test_both_scales_match_library_and_bdhei_core(self):
        from climate_indices import compute, indices

        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        t = self.data.tas.values[:, 0, 0]
        p = self.data.pr.values[:, 0, 0]
        pet = indices.pet(temperature_celsius=t.copy(), latitude_degrees=31.0, data_start_year=1980)
        previous_sti = None
        for scale in (3, 1):
            with self.subTest(scale=scale):
                result = calculate_climate_from_config({**self.config, "spei_scale": scale}, base_dir=self.root)
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["status_counts"], {"ok": 3, "no_valid_data": 1})
                self.assertEqual(result["valid_spei_count"], (480 - scale + 1) * 3)
                self.assertEqual(result["valid_bdhei_count"], 120 * 3)
                with xr.open_dataset(self.root / result["output"], engine="scipy") as output:
                    name = f"SPEI_{scale}"
                    self.assertEqual(output[name].attrs["time_scale_months"], scale)
                    self.assertEqual(output.BDHEI.attrs["spei_variable"], name)
                    self.assertNotIn(f"SPEI_{4-scale}", output)
                    expected = indices.spei(precips_mm=p.copy(), pet_mm=pet.copy(), scale=scale,
                        distribution=indices.Distribution.gamma, periodicity=compute.Periodicity.monthly,
                        data_start_year=1980, calibration_year_initial=1980, calibration_year_final=2019)
                    np.testing.assert_allclose(output[name].values[:, 0, 0], expected, atol=1e-12)
                    if previous_sti is not None:
                        np.testing.assert_array_equal(output.STI.values, previous_sti)
                    previous_sti = output.STI.values.copy()
                    summer = output.date.dt.month.isin([6, 7, 8]).values
                    frame = pd.DataFrame({"dry": output[name].values[summer, 0, 0], "heat": output.STI.values[summer, 0, 0]})
                    reference = calculate_bdhei(frame, drought_col="dry", heat_col="heat")
                    np.testing.assert_allclose(output.BDHEI.values[summer, 0, 0], reference.data.BDHEI, atol=1e-12)
                    self.assertTrue(np.isnan(output.BDHEI.values[~summer]).all())
                    self.assertTrue(np.isnan(output[name].values[:, 1, 1]).all())
                payload = json.loads((self.root / result["summary"]).read_text())
                self.assertEqual(payload["spei_scale"], scale)
                self.assertNotIn(str(self.root), json.dumps(payload))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_kelvin_era5_daily_means_equal_monthly_totals_in_separate_files(self):
        expected = calculate_climate_from_config(self.config, base_dir=self.root)
        kelvin = self.data[["tas"]].copy(deep=True)
        kelvin["tas"] = kelvin.tas + 273.15
        daily = self.data[["pr"]].copy(deep=True)
        daily["pr"] = daily.pr / daily.date.dt.days_in_month / 1000
        kelvin.to_netcdf(self.root / "temperature.nc", engine="scipy")
        daily.to_netcdf(self.root / "precipitation.nc", engine="scipy")
        actual = calculate_climate_from_config({**self.config, "temperature_input": "temperature.nc",
            "precipitation_input": "precipitation.nc", "temperature_unit": "kelvin", "precipitation_unit": "m/day",
            "output": "converted.nc"}, base_dir=self.root)
        with xr.open_dataset(self.root / actual["output"]) as a, xr.open_dataset(self.root / expected["output"]) as b:
            for name in ("temperature_celsius", "precipitation_mm", "STI", "SPEI_3", "BDHEI"):
                np.testing.assert_allclose(a[name], b[name], atol=1e-10)

    def test_invalid_scale_time_alignment_and_output_collisions(self):
        for scale in (0, 2, 4, True, 1.0, "3"):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "spei_scale"):
                calculate_climate_from_config({**self.config, "spei_scale": scale}, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, "different"):
            calculate_climate_from_config({**self.config, "output": "climate.nc"}, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, "within"):
            calculate_climate_from_config({**self.config, "calibration_year_final": 2020}, base_dir=self.root)
        for selection in (slice(1, None), [0, 0, *range(2, 480)], [*range(5), *range(6, 480)]):
            self.data.isel(date=selection).to_netcdf(self.root / "bad.nc", engine="scipy")
            with self.assertRaisesRegex(ValueError, "consecutive monthly"):
                calculate_climate_from_config({**self.config, "input": "bad.nc"}, base_dir=self.root)
        shifted = self.data[["pr"]].assign_coords(lon=[110.5, 111.5])
        shifted.to_netcdf(self.root / "shifted.nc", engine="scipy")
        with self.assertRaises(ValueError):
            calculate_climate_from_config({**self.config, "precipitation_input": "shifted.nc"}, base_dir=self.root)
        self.assertFalse((self.root / "result_spei3.nc").exists())

    def test_netcdf4_round_trip_with_unicode_path(self):
        folder = self.root / "\u6c14\u8c61\u8f93\u51fa"
        folder.mkdir()
        path = folder / "\u7ed3\u679c.nc"
        write_netcdf(self.data, path, engine="netcdf4", output_format="NETCDF4", compression_level=4)
        with open_netcdf(path, engine="netcdf4") as actual:
            xr.testing.assert_allclose(actual, self.data)


class SPEIScaleTests(unittest.TestCase):
    def test_leap_year_precipitation_conversions(self):
        values = np.ones((3, 1, 1))
        days = np.array([31, 29, 31])
        np.testing.assert_array_equal(precipitation_to_mm(values, "m/day", days).ravel(), days * 1000)
        np.testing.assert_array_equal(precipitation_to_mm(values, "kg m-2 s-1", days).ravel(), days * 86400)
        with self.assertRaisesRegex(ValueError, "explicitly select"):
            precipitation_to_mm(values, "m", days)

    def test_valid_scales(self):
        self.assertEqual(validate_spei_scale(1), 1)
        self.assertEqual(validate_spei_scale(3), 3)


if __name__ == "__main__":
    unittest.main()
