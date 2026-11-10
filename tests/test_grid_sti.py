from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bdhei.grid_sti import calculate_sti_grid, calculate_sti_netcdf  # noqa: E402
from bdhei.sti import calculate_sti_result  # noqa: E402


def synthetic_temperature_grid() -> np.ndarray:
    base = np.asarray(
        [float((month + 1) * (year + 1)) for year in range(3) for month in range(12)]
    )
    grid = np.empty((36, 2, 2), dtype=float)
    grid[:, 0, 0] = base
    grid[:, 0, 1] = base * 1.1 + 0.5
    grid[:, 1, 0] = base * 0.8 + 2.0
    grid[:, 1, 1] = base
    grid[5, 1, 1] = np.nan
    return grid


class GridSTITests(unittest.TestCase):
    def test_grid_cells_match_one_dimensional_core(self) -> None:
        grid = synthetic_temperature_grid()
        output = calculate_sti_grid(grid, start_year=1961)
        expected = np.asarray(
            calculate_sti_result(grid[:, 0, 0], start_year=1961).values,
            dtype=float,
        )
        expected[expected == -99.0] = np.nan
        np.testing.assert_allclose(output[:, 0, 0], expected, equal_nan=True)
        self.assertTrue(np.isnan(output[5, 1, 1]))
        self.assertTrue(np.isnan(output[6, 1, 1]))
        self.assertTrue(np.isnan(output[7, 1, 1]))
        self.assertFalse(np.isnan(output[8, 1, 1]))

    def test_grid_preserves_nonzero_time_axis(self) -> None:
        grid = synthetic_temperature_grid()
        transposed = np.moveaxis(grid, 0, 2)
        output = calculate_sti_grid(transposed, time_axis=2, start_year=1961)
        np.testing.assert_allclose(
            np.moveaxis(output, 2, 0),
            calculate_sti_grid(grid, start_year=1961),
            equal_nan=True,
        )

    def test_netcdf_adapter_copies_coordinates_and_writes_nan_missing(self) -> None:
        grid = synthetic_temperature_grid()
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "temperature.nc"
            output_path = Path(temporary_directory) / "sti.nc"
            source = xr.Dataset(
                {
                    "t2m": (("time", "latitude", "longitude"), grid),
                },
                coords={
                    "time": np.arange(36),
                    "latitude": [30.0, 31.0],
                    "longitude": [100.0, 101.0],
                },
            )
            source.to_netcdf(input_path, engine="scipy", format="NETCDF3_64BIT")
            source.close()

            returned_path = calculate_sti_netcdf(
                input_path,
                output_path,
                temperature_variable="t2m",
                output_variable="STI",
                start_year=1961,
            )
            self.assertEqual(returned_path, output_path.resolve())
            with xr.open_dataset(output_path, engine="scipy") as dataset:
                self.assertEqual(dataset["STI"].dims, ("time", "latitude", "longitude"))
                np.testing.assert_allclose(dataset["latitude"].values, [30.0, 31.0])
                result = dataset["STI"].values
                self.assertTrue(np.isnan(result[5, 1, 1]))
                self.assertEqual(dataset["STI"].attrs["method"], "spigenerator_compatible")

    def test_legacy_infinite_z_sentinels_become_grid_nan(self) -> None:
        grid = np.ones((36, 1, 1), dtype=float)
        legacy_values = (9999.0, -9999.0, -99.0) + (1.0,) * 33
        with patch(
            "bdhei.grid_sti.calculate_sti_result",
            return_value=SimpleNamespace(values=legacy_values),
        ):
            output = calculate_sti_grid(grid, start_year=1961)
        self.assertTrue(np.isnan(output[0, 0, 0]))
        self.assertTrue(np.isnan(output[1, 0, 0]))
        self.assertTrue(np.isnan(output[2, 0, 0]))
        self.assertEqual(output[3, 0, 0], 1.0)


if __name__ == "__main__":
    unittest.main()
