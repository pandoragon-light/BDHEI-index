# BDHEI Calculator

Clean Python implementation of the Blended Drought and High-temperature Evapotranspiration Index (BDHEI).

This repository provides a reusable implementation of the BDHEI calculation workflow and a small synthetic example for checking that the command-line interface works.

## NetCDF 温度、降水计算与 SPEI 选择

程序支持从**月平均温度和月总降水 NetCDF** 直接计算 STI、SPEI 和 BDHEI。
先修改 [configs/netcdf_climate.example.yaml](configs/netcdf_climate.example.yaml) 中的数据路径、变量名和单位，然后运行：

```powershell
bdhei indices --config configs\netcdf_climate.example.yaml
```

**SPEI 的选项在配置文件第一项，只需修改一个参数：**

```yaml
spei_scale: 3  # 1 = SPEI-1；3 = SPEI-3
```

程序会同步选择计算尺度、输出变量 `SPEI_1` / `SPEI_3`、文件名中的尺度和结果元数据。
STI 默认保持 3 个月；BDHEI 默认计算 6、7、8 月，STI/SPEI 使用完整月序列。

ERA5 月平均产品可使用 [configs/era5_climate.example.yaml](configs/era5_climate.example.yaml)：

```powershell
bdhei indices --config configs\era5_climate.example.yaml
```

ERA5 的月平均日累计 `tp` 选择 `precipitation_unit: m/day`，程序按实际月天数换算为月毫米。
已汇总为月总量的数据选择 `m/month` 或 `mm/month`。依据见 [ECMWF 降水换算说明](https://confluence.ecmwf.int/pages/viewpage.action?pageId=212460134)。

输入支持同一文件中的两个变量，也支持 `temperature_input`、`precipitation_input` 两个文件。
三个维度名可配置，例如 `time/latitude/longitude` 或 `valid_time/lat/lon`；两个文件应具有完全一致的日期和空间坐标。
输入为公历逐月数据，每年从 1 月到 12 月，年份自动读取。日尺度、小时尺度数据应先汇总为月数据。
支持 °C/K，以及月降水量、平均日降水量和 `kg m-2 s-1` 降水通量。

结果 NC 包含 `temperature_celsius`、`precipitation_mm`、`STI`、所选 `SPEI_1` / `SPEI_3` 和 `BDHEI`，同时生成逐格诊断 CSV 与运行摘要 JSON。
网格全缺测位置保留缺测；BDHEI 拟合失败的网格在诊断表中记录原因。
当前实现逐格计算并将网格载入内存，适合先裁剪研究区域后运行。
默认 `overwrite: false`；输入文件保持只读。

已有 SPEI/STI 网格可用 [configs/grid_indices.example.yaml](configs/grid_indices.example.yaml)，同样在顶部设置 `spei_scale`：

```powershell
bdhei compute --config configs\grid_indices.example.yaml
```

原站点命令可直接增加 `--spei-scale 1` 或 `--spei-scale 3`，自动读取 `SPEI_1` 或 `SPEI_3` 列；默认仍为 SPEI-3。
该参数选择已有站点指数列，温度、降水的实际 SPEI 计算由 `indices` 命令完成。
相对路径均以运行命令时的当前目录为基准。可从仓库目录运行，也可安装后在自己的工作目录使用绝对配置路径。

## Associated Paper

Huang, J., Li, X., Wang, L., Wang, X., Li, S., and Zhang, F. (2026). Construction and performance evaluation of a compound high-temperature and drought index for summer in Southwest China. *Natural Hazards*, 122, Article 475.

DOI: <https://doi.org/10.1007/s11069-026-08252-0>

## Method

For paired SPEI-3 and STI observations, the program:

1. estimates marginal cumulative probabilities with Gaussian KDE;
2. selects and fits a bivariate copula;
3. computes the BDHEI joint probability as `1 - F_STI(y) + C(F_SPEI(x), F_STI(y))`;
4. applies the standard normal quantile transformation.

The core BDHEI formula is kept consistent with the original research script. The public-facing output column is named `BDHEI`.

For details, see [docs/method.md](docs/method.md).

## Install

```powershell
git clone https://github.com/pandoragon-light/BDHEI-index.git
cd BDHEI-index
python -m pip install -r requirements.txt
python -m pip install -e .
```

If you prefer to run directly from source without installing the package:

```powershell
$env:PYTHONPATH = "$PWD\src"
```

The dependency versions are pinned in [requirements.txt](requirements.txt) to support reproducible local verification.
Use Python 3.11–3.13; the tested environment is Python 3.12. All NetCDF workflows are included in the installed package.

## Quick Start With Example Data

The repository includes a tiny CSV example for checking the command-line workflow:

```powershell
bdhei compute `
  --spei-dir "examples\sample_spei" `
  --sti-dir "examples\sample_sti" `
  --output-dir "examples\output" `
  --spei-glob "*.csv" `
  --sti-suffix "_STI_M_03.csv" `
  --months 6 7 8
```

The same command is available as [configs/example_run.ps1](configs/example_run.ps1).

If `python` is not available on your command line, set `BDHEI_PYTHON` to your Python executable path before running the PowerShell scripts.

The example data are fully synthetic toy data created only to demonstrate file format and command-line usage. They do not represent any real weather station or observation record.

## Run With Your Own Data

```powershell
bdhei compute `
  --spei-dir "path\to\spei_files" `
  --sti-dir "path\to\sti_files" `
  --output-dir "path\to\output" `
  --months 6 7 8
```

For private research paths, copy [configs/research.template.ps1](configs/research.template.ps1) to a script under `local/` and edit the paths there. The `local/` directory is ignored by Git so machine-specific paths are not published.

## Input Format

Each SPEI file should contain:

- `date`
- `SPEI_3`

Each STI file should contain:

- `date`
- `STI`

Supported input file types are `.xlsx`, `.xls`, and `.csv`. The pinned environment includes `openpyxl` for `.xlsx` and `xlrd` for `.xls`.

By default, the batch command searches for SPEI Excel files with `--spei-glob "*.xlsx"` and matches each station to an STI file ending in `_STI_M_03.xlsx`. For example:

```text
STATION_ID_SPEI.xlsx
STATION_ID_STI_M_03.xlsx
```

For CSV inputs, set `--spei-glob "*.csv"` and `--sti-suffix "_STI_M_03.csv"` as shown in the synthetic example.

## Example Data

A tiny CSV example is available under [examples](examples). It is only for checking input format and command-line behavior, not for scientific analysis.

## Output

For each station, the program writes an Excel workbook named like:

```text
SYNTHETIC_SITE_001_BDHEI_BestCopula.xlsx
```

The workbook contains:

- `BDHEI`: date, SPEI-3, STI, calculated BDHEI, selected copula type, selected copula parameters;
- `Copula_Compare`: candidate copula parameters and goodness-of-fit statistics.

The batch run also writes:

```text
Copula_scores_allstations.xlsx
```

## Development Checks

Current development checks:

- Public synthetic example run: passed.
- Release preflight check: passed.
- Local regression checks against private reference outputs: passed on the development machine. The private data and generated outputs are not included in this repository.

The automated synthetic tests cover both SPEI scales, agreement with direct `climate-indices` calls and the BDHEI core, ERA5 precipitation conversion including leap years, separate input files, coordinate/time checks, missing grid cells, Chinese NetCDF paths, and the original station CLI:

```powershell
python -m unittest discover -s tests -v
```

Run the directory comparison with:

```powershell
python tests\compare_directory_outputs.py `
  --reference-dir "path\to\legacy_reference_outputs" `
  --reference-pattern "{station_id}_legacy_reference.xlsx" `
  --reference-sheet "reference_sheet_name" `
  --reference-column "reference_column_name" `
  --new-dir "path\to\new_BDHEI_outputs" `
  --tolerance 0.001
```

For release-file checks before updating the repository, creating a release, or pushing a tag, see [docs/release.md](docs/release.md) and run:

```powershell
python tools\preflight_release.py
```

## Citation

Please cite the paper above when using this code. A machine-readable citation file is provided in [CITATION.cff](CITATION.cff).

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
