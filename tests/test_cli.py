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

from bdhei.cli import main
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

    def test_station_cli_and_public_example(self):
        project = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((project / "configs/station_climate.example.yaml").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config["input"] = str(project / config["input"])
            config["output"] = str(root / "station_spei{spei_scale}.csv")
            for scale in (1, 3):
                config["spei_scale"] = scale
                path = root / "station.yaml"
                path.write_text(yaml.safe_dump(config), encoding="utf-8")
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(main(["station-indices", "--config", str(path)]), 0)
                result = json.loads(stdout.getvalue())
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["station_count"], 2)
                self.assertEqual(result["valid_bdhei_count"], 180)
                output = pd.read_csv(root / f"station_spei{scale}.csv")
                self.assertIn(f"SPEI_{scale}", output)
                self.assertIn("temperature_celsius", output)
                self.assertIn("precipitation_mm", output)

    def test_precomputed_index_command_is_removed(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["compute", "--spei-dir", "unused", "--sti-dir", "unused"])
        self.assertEqual(error.exception.code, 2)

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
