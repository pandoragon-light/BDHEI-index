from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

try:
    import copulas  # noqa: F401
except ImportError:  # pragma: no cover - depends on the selected environment
    COPULAS_AVAILABLE = False
else:
    COPULAS_AVAILABLE = True

from bdhei.grid_bdhei import bilinear_interpolate_grid, calculate_bdhei_grid  # noqa: E402

if COPULAS_AVAILABLE:
    from bdhei.core import calculate_bdhei  # noqa: E402


class BilinearInterpolationTests(unittest.TestCase):
    def test_bilinear_interpolation_handles_descending_latitude(self) -> None:
        latitudes = np.asarray([31.0, 30.0])
        longitudes = np.asarray([100.0, 101.0])
        time = np.arange(3, dtype=float)
        field = np.empty((3, 2, 2), dtype=float)
        for index in range(3):
            field[index] = 2.0 * latitudes[:, None] + 3.0 * longitudes[None, :] + index
        output = bilinear_interpolate_grid(field, latitudes, longitudes, 30.25, 100.25)
        np.testing.assert_allclose(output, 2.0 * 30.25 + 3.0 * 100.25 + time)


@unittest.skipUnless(COPULAS_AVAILABLE, "copulas is required for BDHEI tests")
class GridBDHEITests(unittest.TestCase):
    def test_one_cell_grid_matches_station_core_on_same_inputs(self) -> None:
        time = np.arange(
            np.datetime64("1961-01", "M"),
            np.datetime64("1976-01", "M"),
            dtype="datetime64[M]",
        ).astype("datetime64[ns]")
        index = np.arange(len(time), dtype=float)
        spei = np.sin(index / 5.0) + index / 100.0
        sti = np.cos(index / 7.0) + index / 80.0
        months = np.isin(time.astype("datetime64[M]").astype(int) % 12 + 1, [6, 7, 8])
        station = calculate_bdhei(
            pd.DataFrame({"SPEI_3": spei[months], "STI": sti[months]})
        )
        grid = calculate_bdhei_grid(
            spei[:, None, None],
            sti[:, None, None],
            time,
            [30.0],
            [105.0],
        )
        np.testing.assert_allclose(
            grid.values[months, 0, 0],
            station.data["BDHEI"].to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(grid.diagnostics.loc[0, "status"], "ok")
        self.assertEqual(grid.diagnostics.loc[0, "copula_type"], station.copula_type)

    def test_grid_writes_bdhei_only_for_requested_months(self) -> None:
        time = np.arange(
            np.datetime64("1961-01", "M"),
            np.datetime64("1976-01", "M"),
            dtype="datetime64[M]",
        ).astype("datetime64[ns]")
        index = np.arange(len(time), dtype=float)
        spei = np.sin(index / 5.0) + index / 100.0
        sti = np.cos(index / 7.0) + index / 80.0
        result = calculate_bdhei_grid(
            spei[:, None, None],
            sti[:, None, None],
            time,
            [30.0],
            [105.0],
        )
        month_numbers = time.astype("datetime64[M]").astype(int) % 12 + 1
        self.assertTrue(np.isnan(result.values[~np.isin(month_numbers, [6, 7, 8])]).all())
        self.assertEqual(int(np.isfinite(result.values).sum()), 45)


if __name__ == "__main__":
    unittest.main()
