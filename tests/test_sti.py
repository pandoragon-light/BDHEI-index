from __future__ import annotations

from datetime import date
import unittest

from bdhei.sti import (
    aggregate_monthly_values,
    calculate_sti_result,
    extract_summer_records,
)


class STIUnitTests(unittest.TestCase):
    def test_three_month_aggregation_preserves_negative_values(self) -> None:
        values = [1.0, -2.0, 3.0, 4.0, 5.0, 6.0]
        self.assertEqual(
            aggregate_monthly_values(values, scale=3),
            [-99.0, -99.0, 2.0, 5.0, 12.0, 15.0],
        )

    def test_missing_value_propagates_through_window(self) -> None:
        values = [1.0, 2.0, 3.0, -99.0, 5.0, 6.0, 7.0]
        self.assertEqual(
            aggregate_monthly_values(values, scale=3),
            [-99.0, -99.0, 6.0, -99.0, -99.0, -99.0, 18.0],
        )

    def test_nan_is_treated_as_missing_at_python_boundary(self) -> None:
        values = [1.0, 2.0, 3.0, float("nan"), 5.0, 6.0, 7.0]
        self.assertEqual(
            aggregate_monthly_values(values, scale=3),
            [-99.0, -99.0, 6.0, -99.0, -99.0, -99.0, 18.0],
        )

    def test_negative_temperature_is_not_missing(self) -> None:
        negative_result = calculate_sti_result(
            [-10.0 + month * 0.2 for _year in range(3) for month in range(12)],
            scale=3,
        )
        self.assertEqual(negative_result.monthly_parameters[1].positive_count, 0)
        self.assertEqual(negative_result.monthly_parameters[1].pzero, 1.0)
        self.assertNotEqual(negative_result.values[2], -99.0)
        self.assertNotIn(-99.0, calculate_sti_result(
            [float((month + 1) * (year + 1)) for year in range(3) for month in range(12)],
            scale=3,
        ).values[2:])

    def test_summer_extraction_is_after_full_monthly_calculation(self) -> None:
        result = calculate_sti_result(
            [float((month + 1) * (year + 1)) for year in range(3) for month in range(12)],
            scale=3,
            start_year=1961,
        )
        summer = extract_summer_records(result)
        self.assertEqual(len(summer), 9)
        self.assertEqual(summer[0][0], date(1961, 6, 1))
        self.assertEqual(summer[-1][0], date(1963, 8, 1))

if __name__ == "__main__":
    unittest.main()
