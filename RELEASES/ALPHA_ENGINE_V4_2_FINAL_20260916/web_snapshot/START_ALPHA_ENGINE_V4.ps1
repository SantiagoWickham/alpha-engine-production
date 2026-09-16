$ErrorActionPreference = "Stop"
$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$SERVER = Join-Path $ROOT "web\run_alpha_engine_v4.py"
$LOG = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1\outputs\data_recovery_v1\web_v4_runtime.log"
Set-Location $ROOT
python $SERVER *>> $LOG
