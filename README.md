# BDHEI Calculator

**English** | [中文](README.zh-CN.md)

BDHEI is a Python tool for studying compound drought and heat.

This project supports both station climate data and gridded NetCDF (NC) climate data, using monthly temperature and precipitation to calculate SPEI, STI and BDHEI for every month of the year.

The three indices describe:

- **SPEI** describes dry and wet conditions.
- **STI** describes temperature conditions.
- **BDHEI** combines drought and heat into one index.

Both input types follow the same workflow:

```text
Monthly temperature + precipitation → SPEI, STI and BDHEI
```

## Install

Use Python 3.11–3.13. Python 3.12 is tested.

```powershell
git clone https://github.com/pandoragon-light/BDHEI-index.git
cd BDHEI-index
python -m pip install .
```

## Run

For **station data**, try the included synthetic monthly climate table:

```powershell
bdhei station-indices --config configs/station_climate.example.yaml
```

For your own data, edit that configuration to set the path and column names. CSV and Excel tables are supported. Each row contains a station ID, date, monthly mean temperature, monthly total precipitation and latitude. Longitude is optional; coordinates can also come from a separate table. Dates may be supplied as separate year and month columns.

For **gridded NetCDF data**, set the paths, variable names and units in [the grid configuration](configs/netcdf_climate.example.yaml), then run:

```powershell
bdhei indices --config configs/netcdf_climate.example.yaml
```

An [ERA5 configuration](configs/era5_climate.example.yaml) is also provided. Temperature and precipitation may be in one file or separate files.

## Choose SPEI-1 or SPEI-3

Change the first setting in either configuration:

```yaml
spei_scale: 3  # 1 = SPEI-1; 3 = SPEI-3
```

STI defaults to a three-month scale. SPEI, STI and BDHEI are calculated for all 12 calendar months by default. A three-month index has two missing records at the start of the sequence while its accumulation window fills.

To select a season for BDHEI, change `months` in the configuration, for example `months: [6, 7, 8]`. SPEI and STI continue to use the full monthly sequence.

## Input and output

Use consecutive monthly records covering complete Gregorian years. Set temperature units to Celsius or kelvin, and specify precipitation units in the configuration. For ERA5 monthly averaged precipitation, use `m/day` so the program converts it to monthly totals using each month's length.

Station results are written as CSV or Excel; grid results as NetCDF. Both include temperature, precipitation, SPEI, STI and BDHEI, with a diagnostic CSV and a summary JSON. Results go to `output/` by default. Relative paths start from the directory where you run the command.

The station example is generated synthetic data. See [method details](docs/method.md) and [example notes](examples/README.md).

## Tests

```powershell
python -m unittest discover -s tests -v
python tools/preflight_release.py
```

## Paper and license

Associated paper: [Huang et al. (2026), Natural Hazards](https://doi.org/10.1007/s11069-026-08252-0). Citation: [CITATION.cff](CITATION.cff). Code license: [MIT](LICENSE).
