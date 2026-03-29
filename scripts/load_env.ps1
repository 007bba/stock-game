param(
  [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) ".env")
)

if (-not (Test-Path $EnvFile)) {
  Write-Host "[load_env] .env not found at $EnvFile, skip."
  return
}

$loaded = 0
Get-Content -Path $EnvFile | ForEach-Object {
  $line = $_.Trim()
  if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
    return
  }

  $pair = $line.Split("=", 2)
  if ($pair.Count -ne 2) {
    return
  }

  $key = $pair[0].Trim()
  $value = $pair[1].Trim()
  if ($value.Length -ge 2) {
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
  }

  # Keep explicit shell env vars as highest priority.
  if (-not (Test-Path "Env:$key")) {
    Set-Item -Path "Env:$key" -Value $value
    $loaded += 1
  }
}

Write-Host "[load_env] loaded $loaded env vars from $EnvFile"