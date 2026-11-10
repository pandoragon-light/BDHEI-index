"""Python implementation of the original SPIGenerator monthly STI path.

The implementation intentionally follows the supplied C# source rather than
using a generic temperature z-score.  The compatibility contract is:

* aggregate the input monthly series with a backward-looking ``scale`` month
  sum;
* fit one Gamma distribution per calendar month;
* count non-positive values in ``pzero``;
* transform the Gamma CDF with the original Abramowitz--Stegun normal inverse;
* treat -99 and -9999 as missing values; and
* round only at the output boundary when requested.

The core functions use only the Python standard library.  This keeps the
single-station reference implementation independent of pandas/scipy and
leaves room for a separate NumPy/xarray adapter for the grid implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence


MISSING_VALUES: tuple[float, float] = (-99.0, -9999.0)
_GAMMA_MAX_ITERATIONS = 100
_GAMMA_EPSILON = 3.0e-7


@dataclass(frozen=True)
class GammaParameters:
    """Parameters returned by the SPIGenerator Gamma fitting routine."""

    alpha: float
    beta: float
    gamma: float
    pzero: float
    positive_count: int
    sample_count: int


@dataclass(frozen=True)
class STIResult:
    """Full monthly STI result and diagnostics for one time series."""

    values: tuple[float, ...]
    aggregated_values: tuple[float, ...]
    dates: tuple[date, ...]
    monthly_parameters: Mapping[int, GammaParameters]


def _is_missing(value: float, missing_values: Sequence[float]) -> bool:
    """Return whether a value uses an original sentinel or is NaN.

    The C# program explicitly recognizes -99 and -9999.  NaN is also treated
    as missing at this Python boundary so that NetCDF/xarray adapters can map
    masked values safely before entering the compatibility algorithm.
    """

    return math.isnan(value) or any(value == marker for marker in missing_values)


def _validate_and_convert_values(
    values: Iterable[float],
) -> list[float]:
    converted: list[float] = []
    for index, raw_value in enumerate(values):
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"monthly value at index {index} is not numeric") from exc
        if math.isinf(value):
            raise ValueError(f"monthly value at index {index} is infinite")
        converted.append(value)
    return converted


def aggregate_monthly_values(
    values: Iterable[float],
    *,
    scale: int = 3,
    missing_values: Sequence[float] = MISSING_VALUES,
    missing_output: float = -99.0,
) -> list[float]:
    """Reproduce ``SPI.AggregateByTimeScale`` for a monthly series.

    The first ``scale - 1`` values are missing.  A window containing either
    original missing sentinel (or NaN at the Python input boundary) is also
    missing.  Negative values are valid and are included in the sum.
    """

    if scale < 1:
        raise ValueError("scale must be at least 1")

    converted = _validate_and_convert_values(values)
    aggregated = [missing_output] * len(converted)
    for index in range(scale - 1, len(converted)):
        window = converted[index - scale + 1 : index + 1]
        if any(_is_missing(value, missing_values) for value in window):
            continue
        aggregated[index] = sum(window)
    return aggregated


def _lgamma(gmm: float) -> float:
    """Port the legacy ``lgamma`` approximation from the supplied C# code."""

    coefficients = (
        76.18009173,
        -86.50532033,
        24.01409822,
        -1.231739516,
        0.120858003e-2,
        -0.536382e-5,
    )
    x = gmm
    y = gmm
    tmp = x + 5.5
    tmp = tmp - (x + 0.5) * math.log(tmp)
    series = 1.00000000019005
    for coefficient in coefficients:
        y += 1.0
        series += coefficient / y
    return -tmp + math.log(2.50662827465 * series / x)


def _gammser(a: float, x: float) -> float:
    """Port the legacy lower incomplete Gamma series approximation."""

    gln = _lgamma(a)
    if x == 0.0:
        return 0.0

    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(_GAMMA_MAX_ITERATIONS):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < _GAMMA_EPSILON * abs(total):
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _gammcf(a: float, x: float) -> float:
    """Port the legacy continued-fraction incomplete Gamma approximation."""

    gln = _lgamma(a)
    g = 0.0
    gold = 0.0
    a0 = 1.0
    a1 = x
    b0 = 0.0
    b1 = 1.0
    factor = 1.0

    for iteration in range(1, _GAMMA_MAX_ITERATIONS + 1):
        an = float(iteration)
        ana = an - a
        a0 = (a1 + a0 * ana) * factor
        b0 = (b1 + b0 * ana) * factor
        anf = an * factor
        a1 = x * a0 + anf * a1
        b1 = x * b0 + anf * b1
        if a1 != 0.0:
            factor = 1.0 / a1
            g = b1 * factor
            if abs((g - gold) / g) < _GAMMA_EPSILON:
                break
            gold = g

    return g * math.exp(-x + a * math.log(x) - gln)


def _gammap(a: float, x: float) -> float:
    if x < a + 1.0:
        return _gammser(a, x)
    return 1.0 - _gammcf(a, x)


def _gamma_fit(values: Sequence[float]) -> GammaParameters:
    """Port ``GammaDistributionEstimatedProbabilities.gamma_fit``."""

    if not values:
        raise ValueError("cannot fit Gamma distribution to an empty sample")

    total = 0.0
    sum_log = 0.0
    positive_count = 0
    non_positive_count = 0
    for value in values:
        if value > 0.0:
            total += value
            sum_log += math.log(value)
            positive_count += 1
        else:
            non_positive_count += 1

    pzero = non_positive_count / len(values)
    mean_positive = total / positive_count if positive_count else 0.0

    if positive_count == 1:
        return GammaParameters(
            alpha=0.0,
            beta=mean_positive,
            gamma=1.0,
            pzero=pzero,
            positive_count=positive_count,
            sample_count=len(values),
        )

    if pzero == 1.0:
        return GammaParameters(
            alpha=0.0,
            beta=mean_positive,
            gamma=1.0,
            pzero=pzero,
            positive_count=positive_count,
            sample_count=len(values),
        )

    alpha = math.log(mean_positive) - sum_log / positive_count
    gamma = (1.0 + math.sqrt(1.0 + 4.0 * alpha / 3.0)) / (4.0 * alpha)
    beta = mean_positive / gamma
    return GammaParameters(
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        pzero=pzero,
        positive_count=positive_count,
        sample_count=len(values),
    )


def _gamma_cdf(parameters: GammaParameters, value: float) -> float:
    if value <= 0.0:
        return parameters.pzero
    return parameters.pzero + (1.0 - parameters.pzero) * _gammap(
        parameters.gamma, value / parameters.beta
    )


def _inv_normal(probability: float) -> float:
    """Port the A&S approximation used by SPIGenerator."""

    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308

    if probability > 0.5:
        minus = 1.0
        probability = 1.0 - probability
    else:
        minus = -1.0

    if probability < 0.0 or probability > 1.0:
        raise ValueError("probability must be in [0, 1]")
    if probability == 0.0:
        return 9999.0 * minus

    t = math.sqrt(math.log(1.0 / (probability * probability)))
    return minus * (
        t
        - (((c2 * t + c1) * t) + c0)
        / (((((d3 * t + d2) * t) + d1) * t) + 1.0)
    )


def calculate_sti_result(
    monthly_values: Iterable[float],
    *,
    scale: int = 3,
    start_year: int = 1961,
    missing_values: Sequence[float] = MISSING_VALUES,
    missing_output: float = -99.0,
    round_output: bool = False,
    output_decimals: int = 2,
) -> STIResult:
    """Calculate one chronological monthly STI series.

    ``round_output=False`` preserves the unrounded Python result for
    diagnostics.  Set it to ``True`` to reproduce the Excel boundary written
    by SPIGenerator, which uses two decimal places in the supplied workflow.
    """

    if start_year < 1:
        raise ValueError("start_year must be a positive year")
    if output_decimals < 0:
        raise ValueError("output_decimals must be non-negative")

    converted = _validate_and_convert_values(monthly_values)
    if len(converted) == 0:
        raise ValueError("monthly_values must not be empty")
    if len(converted) % 12 != 0:
        raise ValueError("monthly_values length must be a multiple of 12")

    aggregated = aggregate_monthly_values(
        converted,
        scale=scale,
        missing_values=missing_values,
        missing_output=missing_output,
    )

    monthly_parameters: dict[int, GammaParameters] = {}
    for month in range(1, 13):
        samples = [
            value
            for index, value in enumerate(aggregated)
            if index % 12 + 1 == month
            and not _is_missing(value, (missing_output, *missing_values))
        ]
        if not samples:
            raise ValueError(f"calendar month {month} has no valid samples")
        monthly_parameters[month] = _gamma_fit(samples)

    result_values: list[float] = []
    result_dates: list[date] = []
    for index, value in enumerate(aggregated):
        month = index % 12 + 1
        year = start_year + index // 12
        result_dates.append(date(year, month, 1))
        if _is_missing(value, (missing_output, *missing_values)):
            result_values.append(missing_output)
            continue
        spi_value = _inv_normal(_gamma_cdf(monthly_parameters[month], value))
        if round_output:
            spi_value = round(spi_value, output_decimals)
        result_values.append(spi_value)

    return STIResult(
        values=tuple(result_values),
        aggregated_values=tuple(aggregated),
        dates=tuple(result_dates),
        monthly_parameters=monthly_parameters,
    )


def calculate_sti(
    monthly_values: Iterable[float],
    *,
    scale: int = 3,
    start_year: int = 1961,
    missing_values: Sequence[float] = MISSING_VALUES,
    missing_output: float = -99.0,
    round_output: bool = False,
    output_decimals: int = 2,
) -> list[float]:
    """Convenience wrapper returning only the full monthly STI values."""

    return list(
        calculate_sti_result(
            monthly_values,
            scale=scale,
            start_year=start_year,
            missing_values=missing_values,
            missing_output=missing_output,
            round_output=round_output,
            output_decimals=output_decimals,
        ).values
    )


def extract_summer_records(
    result: STIResult | Sequence[float],
    *,
    start_year: int = 1961,
    months: Sequence[int] = (6, 7, 8),
) -> list[tuple[date, float]]:
    """Extract June-August records after full monthly calculation."""

    if isinstance(result, STIResult):
        values = result.values
        dates = result.dates
    else:
        values = tuple(float(value) for value in result)
        if len(values) % 12 != 0:
            raise ValueError("result length must be a multiple of 12")
        dates = tuple(
            date(start_year + index // 12, index % 12 + 1, 1)
            for index in range(len(values))
        )

    month_set = set(months)
    if not month_set.issubset(set(range(1, 13))):
        raise ValueError("months must contain calendar months from 1 to 12")
    return [(record_date, value) for record_date, value in zip(dates, values) if record_date.month in month_set]


def read_station_temperature_txt(
    path: str | Path,
    *,
    start_year: int = 1961,
    end_year: int = 2023,
) -> list[float]:
    """Read the supplied ``year + 12 monthly values`` station TXT format."""

    file_path = Path(path)
    lines = file_path.read_text(encoding="utf-8").splitlines()
    expected_years = list(range(start_year, end_year + 1))
    if len(lines) != len(expected_years):
        raise ValueError(
            f"{file_path.name}: expected {len(expected_years)} rows, got {len(lines)}"
        )

    values: list[float] = []
    for line_number, (line, expected_year) in enumerate(
        zip(lines, expected_years), start=1
    ):
        fields = line.split()
        if len(fields) != 13:
            raise ValueError(
                f"{file_path.name}: line {line_number} must contain year plus 12 values"
            )
        try:
            year = int(fields[0])
        except ValueError as exc:
            raise ValueError(f"{file_path.name}: invalid year on line {line_number}") from exc
        if year != expected_year:
            raise ValueError(
                f"{file_path.name}: expected year {expected_year}, got {year}"
            )
        try:
            values.extend(float(field) for field in fields[1:])
        except ValueError as exc:
            raise ValueError(f"{file_path.name}: non-numeric value on line {line_number}") from exc
    return values
