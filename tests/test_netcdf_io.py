from __future__ import annotations

from pathlib import Path
import importlib.util
import tempfile
import unittest

import numpy as np
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bdhei.netcdf_io import write_netcdf  # noqa: E402


class NetCDFIOTests(unittest.TestCase):
    @staticmethod
    def _dataset() -> xr.Dataset:
        return xr.Dataset(
            {
                "field": (
                    ("time", "latitude", "longitude"),
                    np.array(
                        [
                            [[1.0, 2.0], [3.0, np.nan]],
                            [[5.0, 6.0], [7.0, 8.0]],
                        ],
                        dtype=float,
                    ),
                ),
                "valid_n": (
                    ("latitude", "longitude"),
                    np.array([[1, 2], [3, 4]], dtype=np.int32),
                ),
            },
            coords={
                "time": np.array(["2000-01-01", "2000-02-01"], dtype="datetime64[ns]"),
                "latitude": [30.0, 29.75],
                "longitude": [105.0, 105.25],
            },
        )

    def test_netcdf3_compatibility_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "compatibility.nc"
            settings = write_netcdf(self._dataset(), path)
            self.assertEqual(settings["engine"], "scipy")
            self.assertEqual(settings["format"], "NETCDF3_64BIT")
            with xr.open_dataset(path, engine="scipy") as result:
                np.testing.assert_allclose(
                    result["field"].values,
                    self._dataset()["field"].values,
                    equal_nan=True,
                )

    @unittest.skipUnless(importlib.util.find_spec("netCDF4"), "netCDF4 is required")
    def test_netcdf4_chunked_compressed_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "optimized.nc"
            settings = write_netcdf(
                self._dataset(),
                path,
                engine="netcdf4",
                output_format="NETCDF4",
                chunks={"time": 1, "latitude": 1, "longitude": 2},
                compression_level=4,
            )
            self.assertEqual(settings["engine"], "netcdf4")
            self.assertEqual(settings["format"], "NETCDF4")
            with xr.open_dataset(path, engine="netcdf4") as result:
                np.testing.assert_allclose(
                    result["field"].values,
                    self._dataset()["field"].values,
                    equal_nan=True,
                )
                self.assertEqual(result["field"].encoding["chunksizes"], (1, 1, 2))
                self.assertTrue(result["field"].encoding["zlib"])
                self.assertEqual(result["field"].encoding["complevel"], 4)
                np.testing.assert_array_equal(result["valid_n"].values, [[1, 2], [3, 4]])

    def test_scipy_rejects_compression_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "chunks/compression"):
                write_netcdf(
                    self._dataset(),
                    Path(temporary_directory) / "invalid.nc",
                    engine="scipy",
                    output_format="NETCDF3_64BIT",
                    chunks={"time": 1},
                )


if __name__ == "__main__":
    unittest.main()
