from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from bdhei.spei import calculate_spei3


class _MutatingIndices:
    class Distribution:
        gamma = "gamma"

    @staticmethod
    def pet(*, temperature_celsius, latitude_degrees, data_start_year):
        temperature_celsius[:] = 999.0
        return np.ones_like(temperature_celsius)

    @staticmethod
    def spei(**kwargs):
        return np.arange(kwargs["precips_mm"].size, dtype=float)


class _Compute:
    class Periodicity:
        monthly = "monthly"


class SPEIInputSafetyTests(unittest.TestCase):
    def test_read_only_inputs_are_copied_before_external_library_call(self) -> None:
        precipitation = np.arange(12.0)
        temperature = np.linspace(-5.0, 15.0, 12)
        precipitation.setflags(write=False)
        temperature.setflags(write=False)
        precipitation_before = precipitation.copy()
        temperature_before = temperature.copy()

        with patch("bdhei.spei._climate_indices", return_value=(_Compute, _MutatingIndices)):
            result = calculate_spei3(
                precipitation,
                temperature,
                30.0,
                data_start_year=2000,
                calibration_year_initial=2000,
                calibration_year_final=2000,
            )

        np.testing.assert_array_equal(precipitation, precipitation_before)
        np.testing.assert_array_equal(temperature, temperature_before)
        np.testing.assert_array_equal(result, np.arange(12.0))


if __name__ == "__main__":
    unittest.main()
