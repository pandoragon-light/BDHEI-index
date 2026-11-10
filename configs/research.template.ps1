# Copy to local/ and point to your station or grid climate YAML configuration.
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:BDHEI_PYTHON) { $env:BDHEI_PYTHON } else { "python" }
$env:PYTHONPATH = "$projectRoot\src"
Push-Location $projectRoot
try {
    & $python -m bdhei.cli station-indices --config local/station_climate.yaml
    # For a grid configuration use: indices --config local/grid_climate.yaml
} finally {
    Pop-Location
}
