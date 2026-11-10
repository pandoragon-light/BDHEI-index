# BDHEI Method

This document explains the calculation implemented by this repository and how the code maps to the associated Natural Hazards paper:

Huang, J., Li, X., Wang, L., Wang, X., Li, S., and Zhang, F. (2026). Construction and performance evaluation of a compound high-temperature and drought index for summer in Southwest China. Natural Hazards, 122, Article 475. https://doi.org/10.1007/s11069-026-08252-0

## Variables

The paper defines a drought-index variable and an STI variable. In the default code:

- `X` is the drought index observation, read from the `SPEI_3` column.
- `Y` is the high-temperature index observation, read from the `STI` column.
- `x` and `y` are paired observed values at the same station and date.
- `u = F_DI(x)` is the marginal cumulative probability of the drought index.
- `v = F_STI(y)` is the marginal cumulative probability of STI.
- `C(u, v)` is the fitted bivariate copula cumulative distribution.

The default batch workflow filters records to June-August with `--months 6 7 8`, matching the summer application in the paper. Other months can be supplied through the command line when appropriate.

## Monthly NetCDF preprocessing and SPEI scale

`bdhei indices --config ...` calculates the input indices from monthly mean
temperature and monthly total precipitation. The top-level `spei_scale` setting
selects 1 or 3 months. The output drought variable is `SPEI_1` or `SPEI_3`, and
BDHEI uses that selected variable. `sti_scale` is independent and defaults to 3.

Temperature is converted to Celsius and precipitation to millimetres per month.
For ERA5 monthly averaged reanalysis, `precipitation_unit: m/day` applies
`tp * 1000 * days_in_month`, including leap years, following the
[ECMWF conversion table](https://confluence.ecmwf.int/pages/viewpage.action?pageId=212460134).
Monthly totals use `m/month` or `mm/month`; precipitation fluxes in
`kg m-2 s-1` use `flux * 86400 * days_in_month`.

The SPEI implementation uses `climate-indices==2.4.0`, Thornthwaite PET at each
grid latitude, Gamma fitting by calendar month, and backward accumulation over
the selected scale. Inputs span complete Gregorian monthly years. The first
`scale - 1` months of SPEI are missing because the accumulation window is
incomplete. Calibration years default to the full input period and can be set
through `calibration_year_initial` and `calibration_year_final`.
These settings control SPEI fitting; Thornthwaite PET uses the supplied
temperature series, and STI uses the full input-period fit.

STI follows the project's SPIGenerator-compatible monthly Gamma implementation,
including its handling of non-positive temperatures and inverse-normal
approximation. STI and SPEI are calculated over the full monthly sequence
before the requested BDHEI months are selected. Each grid cell then uses the
same KDE, copula selection, joint probability and normal transformation as the
station core. Fully missing cells remain missing; failed BDHEI fits are listed
in the diagnostics CSV.

For existing station files, `--spei-scale 1` selects the `SPEI_1` column and
`--spei-scale 3` selects `SPEI_3`. A custom `--spei-column` takes precedence.
For existing grid or station YAML inputs, `spei_scale` supplies the default
variable or column name. These existing-index commands consume the supplied
SPEI values; the `indices` command performs the climate-to-SPEI calculation.

## Marginal Distributions

For each station, the program estimates the two marginal cumulative probabilities with Gaussian KDE:

```text
u = F_DI(x)
v = F_STI(y)
```

In the code, this step is implemented in `calculate_bdhei()` in `src/bdhei/core.py` through `GaussianKDE().cdf(...)`.

The calculated probabilities are clipped to avoid exact 0 or 1 values:

```text
eps <= u, v <= 1 - eps
```

The default is `eps = 1e-6`.

## Copula Selection

The paired marginal probabilities are combined as:

```text
X_copula = [u, v]
```

The program calls `select_copula(X_copula)` from the `copulas` package, then fits the selected copula to the station-level data. The fitted copula gives:

```text
C(u, v) = P(X <= x, Y <= y)
```

This corresponds to the paper's copula joint distribution expression, where `u` and `v` are the two marginal cumulative probabilities.

## Paper Formula To Code Mapping

| Paper step | Mathematical expression | Code variable or statement |
| --- | --- | --- |
| Marginal probability for DI | `u = F_DI(x)` | `drought_cdf` |
| Marginal probability for STI | `v = F_STI(y)` | `heat_cdf` |
| Copula joint distribution | `P(X <= x, Y <= y) = C(u, v)` | `joint_cdf = best_copula.cumulative_distribution(x)` |
| BDHEI probability | `P_BDHEI = 1 - v + C(u, v)` | `joint_prob = 1 - heat_cdf + joint_cdf` |
| Normal quantile transform | `BDHEI = Phi^-1(P_BDHEI)` | `norm.ppf(np.clip(joint_prob, 0.0001, 0.9999))` |

## BDHEI Joint Probability

The paper's BDHEI probability is the probability of the union event:

```text
P(X <= x or Y > y)
```

Using the paper's notation, this becomes:

```text
P_BDHEI = 1 - P(Y <= y) + P(X <= x, Y <= y)
        = 1 - v + C(u, v)
```

In the code:

```python
joint_prob = 1 - heat_cdf + joint_cdf
```

where:

- `heat_cdf` is `v = F_STI(y)`;
- `joint_cdf` is `C(u, v)`.

This is the same computation that was used for the legacy internal research output. The public output column is now named `BDHEI`.

## Normal Quantile Transformation

The paper applies an inverse standard-normal cumulative distribution function to standardize the joint probability:

```text
BDHEI = Phi^-1(P_BDHEI)
```

In the code:

```python
BDHEI = norm.ppf(clip(joint_prob, 0.0001, 0.9999))
```

The default clipping range is `0.0001` to `0.9999`, matching the original script's protective clipping before the normal quantile transformation.

Because the event definition combines low drought-index values with high STI values, lower BDHEI values generally indicate stronger compound hot-dry conditions under this construction.

## Input Fields

Each SPEI file must include:

- `date`: observation date;
- `SPEI_3`: drought index value, unless changed with `--spei-column`.

Each STI file must include:

- `date`: observation date;
- `STI`: high-temperature index value, unless changed with `--sti-column`.

Supported input formats are `.xlsx`, `.xls`, and `.csv`.

By default, station matching uses filenames:

```text
SYNTHETIC_SITE_001_SPEI.csv
SYNTHETIC_SITE_001_STI_M_03.csv
```

The station identifier is the text before the first underscore in the SPEI filename.

## Output Fields

Each station workbook contains a `BDHEI` sheet with:

- `date`: matched observation date;
- `SPEI_3`: drought index value;
- `STI`: high-temperature index value;
- `BDHEI`: calculated BDHEI value;
- `Copula_Type`: selected copula family;
- `Copula_Params`: selected copula parameters.

The optional `Copula_Compare` sheet contains candidate copula diagnostics:

- `copula`;
- `dependence_param`;
- `kendall_tau`;
- `loglik`;
- `AIC`;
- `BIC`;
- `GOF_RMSE_grid`;
- `selected_by_select_copula`;
- `best_by_AIC`;
- `best_by_BIC`.

The diagnostics table is intended to document model fitting and does not change the BDHEI values.
