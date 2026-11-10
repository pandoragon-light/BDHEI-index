# Release checks

Run from the repository directory:

```powershell
python -m unittest discover -s tests -v
python tools/preflight_release.py
```

Tests cover station and grid temperature/precipitation input, both SPEI scales, agreement between station and grid calculations, unit conversion, missing values, invalid inputs and command-line usage.

Private inputs belong in `local/`; generated results belong in `output/`. The release check verifies required public files and checks for local paths and generated Excel/NetCDF files. The GitHub workflow also checks installation and dependency consistency on Windows with Python 3.12.
