from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
import xarray as xr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import copulas  # noqa: F401
except ImportError:  # pragma: no cover - depends on selected runtime
    COPULAS_AVAILABLE = False
else:
    COPULAS_AVAILABLE = True

from bdhei.pipeline import calculate_grid_file, calculate_station_file  # noqa: E402


def _synthetic_indices() -> pd.DataFrame:
    dates = pd.date_range("1961-06-01", periods=45, freq="12MS")
    index = np.arange(len(dates), dtype=float)
    rows = []
    for station_id, offset in (("A", 0.0), ("B", 0.4)):
        for date, value in zip(dates, index):
            rows.append(
                {
                    "station_id": station_id,
                    "date": date,
                    "SPEI_3": np.sin(value / 5.0) + offset,
                    "STI": np.cos(value / 7.0) + value / 80.0 + offset,
                }
            )
    return pd.DataFrame(rows)


@unittest.skipUnless(COPULAS_AVAILABLE, "copulas is required for pipeline tests")
class PipelineTests(unittest.TestCase):
    def test_station_pipeline_fits_each_station_group(self) -> None:
        from bdhei.core import calculate_bdhei

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            input_path = directory / "station_indices.csv"
            output_path = directory / "station_bdhei.csv"
            diagnostics_path = directory / "station_diagnostics.csv"
            _synthetic_indices().to_csv(input_path, index=False)

            result = calculate_station_file(
                input_path,
                output_path,
                diagnostics_path=diagnostics_path,
                station_id_column="station_id",
            )

            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["station_count"], 2)
            output = pd.read_csv(output_path)
            diagnostics = pd.read_csv(diagnostics_path)
            self.assertEqual(len(output), 90)
            self.assertEqual(output["station_id"].tolist(), sorted(output["station_id"].tolist()))
            for _, group in output.groupby("station_id", sort=False):
                self.assertEqual(group["date"].tolist(), sorted(group["date"].tolist()))
            self.assertEqual(len(diagnostics), 2)
            self.assertTrue(np.isfinite(output["BDHEI"]).all())
            self.assertTrue(diagnostics["copula_type"].notna().all())
            self.assertTrue(set(diagnostics["copula_type"]).issubset({"Frank", "Clayton", "Gumbel"}))

            source = _synthetic_indices()
            for station_id, group in source.groupby("station_id", sort=True):
                expected = calculate_bdhei(group[["SPEI_3", "STI"]]).data["BDHEI"].to_numpy()
                actual = output.loc[output["station_id"] == station_id, "BDHEI"].to_numpy()
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)

    def test_station_pipeline_reports_no_valid_data_without_filling_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = _synthetic_indices()
            source.loc[source["station_id"] == "B", ["SPEI_3", "STI"]] = np.nan
            input_path = directory / "station_indices.csv"
            output_path = directory / "station_bdhei.csv"
            diagnostics_path = directory / "station_diagnostics.csv"
            source.to_csv(input_path, index=False)

            result = calculate_station_file(
                input_path,
                output_path,
                diagnostics_path=diagnostics_path,
                station_id_column="station_id",
            )

            self.assertEqual(result["status"], "OK_WITH_EMPTY_STATIONS")
            output = pd.read_csv(output_path)
            diagnostics = pd.read_csv(diagnostics_path)
            self.assertEqual(int(output.loc[output["station_id"] == "A", "BDHEI"].notna().sum()), 45)
            self.assertEqual(int(output.loc[output["station_id"] == "B", "BDHEI"].notna().sum()), 0)
            self.assertEqual(diagnostics.set_index("station_id").loc["B", "status"], "no_valid_data")

    def test_station_pipeline_rejects_duplicate_invalid_and_missing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            source = _synthetic_indices()

            missing_path = directory / "missing.csv"
            source.drop(columns=["STI"]).to_csv(missing_path, index=False)
            with self.assertRaisesRegex(KeyError, "missing station columns"):
                calculate_station_file(missing_path, directory / "missing_output.csv", station_id_column="station_id")

            invalid_date = source.copy()
            invalid_date["date"] = invalid_date["date"].dt.strftime("%Y-%m-%d").astype(object)
            invalid_date.loc[0, "date"] = "not-a-date"
            invalid_date_path = directory / "invalid_date.csv"
            invalid_date.to_csv(invalid_date_path, index=False)
            with self.assertRaisesRegex(ValueError, "date contains invalid dates"):
                calculate_station_file(
                    invalid_date_path,
                    directory / "invalid_date_output.csv",
                    station_id_column="station_id",
                )

            duplicate = pd.concat([source, source.iloc[[0]]], ignore_index=True)
            duplicate_path = directory / "duplicate.csv"
            duplicate.to_csv(duplicate_path, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate dates within a station group"):
                calculate_station_file(
                    duplicate_path,
                    directory / "duplicate_output.csv",
                    station_id_column="station_id",
                )

    def test_station_pipeline_constant_sequence_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            dates = pd.date_range("1961-06-01", periods=45, freq="12MS")
            source = pd.DataFrame(
                {
                    "station_id": "CONSTANT",
                    "date": dates,
                    "SPEI_3": 1.0,
                    "STI": 2.0,
                }
            )
            input_path = directory / "constant.csv"
            source.to_csv(input_path, index=False)
            with self.assertRaisesRegex(ValueError, "Constant column"):
                calculate_station_file(
                    input_path,
                    directory / "constant_output.csv",
                    station_id_column="station_id",
                )

    def test_grid_pipeline_writes_netcdf_and_status_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            input_path = directory / "indices.nc"
            output_path = directory / "bdhei.nc"
            diagnostics_path = directory / "diagnostics.csv"
            time = pd.date_range("1961-01-01", periods=180, freq="MS")
            index = np.arange(len(time), dtype=float)
            source = xr.Dataset(
                {
                    "SPEI_3": (("time", "latitude", "longitude"), np.sin(index[:, None, None] / 5.0)),
                    "STI": (("time", "latitude", "longitude"), np.cos(index[:, None, None] / 7.0) + index[:, None, None] / 80.0),
                },
                coords={"time": time, "latitude": [30.0], "longitude": [105.0]},
            )
            source.to_netcdf(input_path, engine="scipy", format="NETCDF3_64BIT")
            source.close()

            result = calculate_grid_file(input_path, output_path, diagnostics_path=diagnostics_path)

            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["dimensions"], {"time": 180, "latitude": 1, "longitude": 1})
            with xr.open_dataset(output_path, engine="scipy") as output:
                self.assertEqual(output["BDHEI"].dims, ("time", "latitude", "longitude"))
                self.assertEqual(int(np.isfinite(output["BDHEI"].values).sum()), 45)
                self.assertEqual(int(output["status_code"].values[0, 0]), 0)
            diagnostics = pd.read_csv(diagnostics_path)
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics.loc[0, "status"], "ok")


if __name__ == "__main__":
    unittest.main()
