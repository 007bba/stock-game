. "$PSScriptRoot/load_env.ps1"

if (-not $env:DATABASE_URL) {
  Write-Error "DATABASE_URL is not set. Load .env first or export env vars in current shell."
  exit 1
}

if (-not $env:TUSHARE_TOKEN) {
  Write-Error "TUSHARE_TOKEN is not set. Load .env first or export env vars in current shell."
  exit 1
}

python scripts/etl/tushare_pipeline.py @args
