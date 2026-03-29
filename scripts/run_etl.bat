@echo off
setlocal

if "%DATABASE_URL%"=="" (
  echo DATABASE_URL is not set.
  echo Please load .env first or set env vars in current shell.
  exit /b 1
)

if "%TUSHARE_TOKEN%"=="" (
  echo TUSHARE_TOKEN is not set.
  echo Please load .env first or set env vars in current shell.
  exit /b 1
)

python scripts/etl/tushare_pipeline.py %*
