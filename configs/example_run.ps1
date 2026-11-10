$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:BDHEI_PYTHON) { $env:BDHEI_PYTHON } else { "python" }
$env:PYTHONPATH = "$projectRoot\src"
Push-Location $projectRoot
try {
    & $python -m bdhei.cli station-indices --config configs/station_climate.example.yaml
} finally {
    Pop-Location
}
