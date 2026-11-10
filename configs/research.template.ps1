# Copy this file to a script under local/ and edit the paths for your own computer.
# The local/ directory is ignored by Git so private machine paths are not published.

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:BDHEI_PYTHON) { $env:BDHEI_PYTHON } else { "python" }

$env:PYTHONPATH = "$projectRoot\.deps;$projectRoot\src"

# Change only this value: 1 = SPEI_1; 3 = SPEI_3.
$speiScale = 3
$speiDir = "path\to\your\SPEI-files"
$stiDir = "path\to\your\STI-files"
$outputDir = "$projectRoot\output\research-run"

& $python -m bdhei.cli compute `
  --spei-scale $speiScale `
  --spei-dir $speiDir `
  --sti-dir $stiDir `
  --output-dir $outputDir `
  --months 6 7 8
