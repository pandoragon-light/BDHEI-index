from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import xarray as xr
import yaml

from bdhei.batch import BatchConfig, process_station
from bdhei.cli import main
from bdhei.core import calculate_bdhei
from test_climate import synthetic_climate


class CLITests(unittest.TestCase):
    def test_raw_netcdf_cli_uses_scale_from_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "climate.nc"
            synthetic_climate().to_netcdf(source, engine="scipy")
            config = {"spei_scale": 1, "input": str(source), "output": str(root / "result.nc"),
                "temperature_variable": "tas", "precipitation_variable": "pr",
                "time_dimension": "date", "latitude_dimension": "lat", "longitude_dimension": "lon",
                "input_engine": "scipy", "output_engine": "netcdf4", "output_format": "NETCDF4"}
            config_path = root / "climate.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["indices", "--config", str(config_path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["spei_variable"], "SPEI_1")
            with xr.open_dataset(root / "result.nc") as output:
                self.assertIn("SPEI_1", output)
                self.assertEqual(output.attrs["spei_scale"], 1)

    def test_existing_indices_cli_selects_spei1_in_grid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dates = pd.date_range("1980-01-01", periods=240, freq="MS")
            index = np.arange(len(dates), dtype=float)
            drought = np.sin(index / 5)[:, None, None]
            heat = (np.cos(index / 7) + index / 80)[:, None, None]
            source = xr.Dataset({"SPEI_1": (("time", "latitude", "longitude"), drought),
                "STI": (("time", "latitude", "longitude"), heat)},
                coords={"time": dates, "latitude": [30.0], "longitude": [110.0]})
            source.to_netcdf(root / "indices.nc", engine="scipy")
            config = {"spei_scale": 1, "mode": "grid", "input": str(root / "indices.nc"),
                "output": str(root / "bdhei.nc")}
            path = root / "indices.yaml"
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["compute", "--config", str(path)]), 0)
            selected = dates.month.isin([6, 7, 8])
            expected = calculate_bdhei(pd.DataFrame({"SPEI_3": drought[selected, 0, 0], "STI": heat[selected, 0, 0]}))
            with xr.open_dataset(root / "bdhei.nc", engine="scipy") as actual:
                np.testing.assert_allclose(actual.BDHEI.values[selected, 0, 0], expected.data.BDHEI)

    def test_original_batch_arguments_and_single_scale_switch(self):
        project = Path(__file__).resolve().parents[1]
        spei = project / "examples/sample_spei/SYNTHETIC_SITE_001_SPEI.csv"
        sti = project / "examples/sample_sti/SYNTHETIC_SITE_001_STI_M_03.csv"
        expected, _ = process_station(spei, sti, BatchConfig(spei.parent, sti.parent, Path(".")))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with redirect_stdout(io.StringIO()):
                code = main(["compute", "--spei-dir", str(spei.parent), "--sti-dir", str(sti.parent),
                    "--output-dir", str(root / "scale3"), "--spei-glob", "*.csv", "--sti-suffix", "_STI_M_03.csv"])
            self.assertEqual(code, 0)
            actual = pd.read_excel(root / "scale3/SYNTHETIC_SITE_001_BDHEI_BestCopula.xlsx", sheet_name="BDHEI")
            np.testing.assert_allclose(actual.BDHEI, expected.BDHEI)
            source1 = root / "spei1"
            source1.mkdir()
            pd.read_csv(spei).rename(columns={"SPEI_3": "SPEI_1"}).to_csv(source1 / spei.name, index=False)
            with redirect_stdout(io.StringIO()):
                code = main(["compute", "--spei-dir", str(source1), "--sti-dir", str(sti.parent),
                    "--output-dir", str(root / "scale1"), "--spei-glob", "*.csv", "--sti-suffix", "_STI_M_03.csv", "--spei-scale", "1"])
            self.assertEqual(code, 0)
            actual1 = pd.read_excel(root / "scale1/SYNTHETIC_SITE_001_BDHEI_BestCopula.xlsx", sheet_name="BDHEI")
            self.assertIn("SPEI_1", actual1)
            self.assertNotIn("SPEI_3", actual1)
            np.testing.assert_allclose(actual1.BDHEI, expected.BDHEI)

    def test_bad_config_exits_with_clear_message(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.yaml"
            path.write_text("spei_scale: 2\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["indices", "--config", str(path)]), 1)
            self.assertIn("spei_scale", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
