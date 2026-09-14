$ErrorActionPreference="Stop"
$Script = Join-Path $PSScriptRoot "export_web_data.py"
python $Script
if ($LASTEXITCODE -ne 0) { throw "Web data export failed" }
