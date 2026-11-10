# Calculation method

Both public commands start from monthly mean temperature and monthly precipitation:

- `station-indices`: a station climate table, fitted separately for each station.
- `indices`: climate NetCDF files, fitted separately for each grid cell.

Each sequence contains complete Gregorian years in monthly order. Station latitude is required to calculate potential evapotranspiration (PET).

## SPEI and STI

Temperature is converted to Celsius and precipitation to millimetres per month. SPEI uses `climate-indices==2.4.0`, Thornthwaite PET and a Gamma distribution fitted by calendar month. `spei_scale` selects one or three months of backward accumulation. The output variable is `SPEI_1` or `SPEI_3`.

STI follows the project's SPIGenerator-compatible monthly Gamma implementation, including its handling of non-positive temperatures and its inverse-normal approximation. `sti_scale` defaults to 3. Station and grid calculations use the same numerical functions and preserve floating-point output precision.

SPEI calibration defaults to each input sequence's years. `calibration_year_initial` and `calibration_year_final` can select a period within those years. These settings control SPEI fitting; PET uses the supplied temperature series, and STI is fitted over the full input period.

For a scale of N months, the first N−1 months have no accumulated index. Missing observations propagate through the calculation. Fully missing sequences remain missing.

## BDHEI

STI and SPEI use the full monthly sequence. BDHEI uses January–December by default, so it is calculated for every month with valid paired inputs. The `months` setting can select a season, such as `[6, 7, 8]`. Each station or grid cell fits one pair of Gaussian KDE marginal distributions and one selected bivariate copula using all valid observations in the selected months:

```text
u = F_SPEI(x)
v = F_STI(y)
P = 1 - v + C(u, v)
BDHEI = Φ⁻¹(P)
```

Marginal probabilities are clipped to `[1e-6, 1−1e-6]`; the joint probability is clipped to `[0.0001, 0.9999]` before the normal transformation. Lower BDHEI values indicate stronger compound hot-dry conditions under this construction. Failed BDHEI fits are recorded in the diagnostic table.

## Precipitation units

| Input unit | Conversion to monthly mm |
| --- | --- |
| `mm/month` | unchanged |
| `m/month` | × 1000 |
| `mm/day` | × days in month |
| `m/day` | × 1000 × days in month |
| `kg m-2 s-1` | × 86400 × days in month |

For ERA5 monthly averaged reanalysis, `tp` represents a monthly mean daily accumulation. Use `m/day`, following the [ECMWF conversion table](https://confluence.ecmwf.int/pages/viewpage.action?pageId=212460134). Files already converted to monthly totals use `m/month` or `mm/month`.
