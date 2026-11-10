# BDHEI 计算工具

[English](README.md) | **中文**

BDHEI 是一个研究干旱与高温复合事件的 Python 工具。

本项目同时支持站点气象数据和 NetCDF（NC）网格气象数据，可由月温度、降水计算全年逐月的 SPEI、STI 和 BDHEI。

三个指数分别表示：

- **SPEI**：描述干湿状况。
- **STI**：描述温度状况。
- **BDHEI**：综合反映干旱与高温的复合状况。

站点和网格使用相同的计算流程：

```text
月温度、降水 → SPEI、STI、BDHEI
```

## 安装

使用 Python 3.11–3.13，已在 Python 3.12 上测试。

```powershell
git clone https://github.com/pandoragon-light/BDHEI-index.git
cd BDHEI-index
python -m pip install .
```

## 使用

**站点数据**可以先运行仓库自带的合成月气象示例：

```powershell
bdhei station-indices --config configs/station_climate.example.yaml
```

使用自己的数据时，修改[站点配置文件](configs/station_climate.example.yaml)中的路径和列名。支持 CSV 和 Excel，每行包含站号、日期、月平均温度、月总降水和纬度。经度为可选项，坐标也可从单独的站点坐标表读取；日期可以使用独立的年份、月份两列。

**网格 NC 数据**先在[网格配置文件](configs/netcdf_climate.example.yaml)中设置路径、变量名和单位，再运行：

```powershell
bdhei indices --config configs/netcdf_climate.example.yaml
```

仓库也提供了 [ERA5 配置文件](configs/era5_climate.example.yaml)。温度和降水可以放在同一文件中，也可以分别存放。

## 选择 SPEI1 或 SPEI3

两种配置文件的第一项都是这个参数，只需修改数值：

```yaml
spei_scale: 3  # 1：SPEI1；3：SPEI3
```

STI 默认使用 3 个月尺度。SPEI、STI 和 BDHEI 默认计算全年 1—12 月。3 个月尺度的序列起始两个月因累计窗口尚未完整而保留缺测。

如需计算特定季节的 BDHEI，可修改配置中的 `months`，例如 `months: [6, 7, 8]`。SPEI 和 STI 始终使用完整月序列。

## 数据与结果

输入采用公历逐月记录，每个年份包含 1—12 月。温度可使用摄氏度或开尔文，降水单位在配置文件中指定。ERA5 月平均日累计降水选择 `m/day`，程序会按实际月天数换算为月总量。

站点结果保存为 CSV 或 Excel，网格结果保存为 NC，均包含温度、降水、SPEI、STI 和 BDHEI，并附带诊断 CSV 和摘要 JSON。结果默认放在 `output/` 目录；相对路径以运行命令时的目录为起点。

仓库自带的站点示例为程序生成的合成数据。具体算法见[方法说明](docs/method.md)，样例数据见[示例说明](examples/README.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
python tools/preflight_release.py
```

## 论文与许可

相关论文：[Huang 等（2026），Natural Hazards](https://doi.org/10.1007/s11069-026-08252-0)。引用信息见 [CITATION.cff](CITATION.cff)，代码采用 [MIT 许可](LICENSE)。
