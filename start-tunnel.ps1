# Запуск COFI с публичным https-адресом через туннель cloudflared.
# Адрес туннеля меняется при каждом запуске: скрипт сам записывает новый в .env (BASE_URL),
# а сервер при старте обновляет кнопку мини-приложения в Telegram-боте. Остановить: Ctrl+C.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$cf = @("$PSScriptRoot\cloudflared.exe", "$HOME\Downloads\cloudflared-windows-amd64.exe", "$HOME\Downloads\cloudflared.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $cf) {
  Write-Host "Не найден cloudflared. Скачайте https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  Write-Host "и положите в папку проекта под именем cloudflared.exe (или оставьте в «Загрузках»)."
  exit 1
}

$log = Join-Path $env:TEMP "cofi-tunnel.log"
Remove-Item $log -ErrorAction SilentlyContinue
Write-Host "Запускаю туннель..."
$tunnel = Start-Process -FilePath $cf -ArgumentList "tunnel", "--url", "http://localhost:8000" `
  -RedirectStandardError $log -PassThru -NoNewWindow

$url = $null
for ($i = 0; $i -lt 40 -and -not $url; $i++) {
  Start-Sleep -Seconds 1
  if (Test-Path $log) {
    $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
  }
}
if (-not $url) {
  Write-Host "Туннель не выдал адрес за 40 секунд. Журнал: $log"
  Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
  exit 1
}

# BASE_URL в .env (файл в UTF-8 без BOM, как его читает приложение)
$envPath = Join-Path $PSScriptRoot ".env"
$lines = @()
if (Test-Path $envPath) { $lines = [IO.File]::ReadAllLines($envPath, [Text.Encoding]::UTF8) }
if ($lines -match "^BASE_URL=") { $lines = $lines -replace "^BASE_URL=.*", "BASE_URL=$url" } else { $lines += "BASE_URL=$url" }
[IO.File]::WriteAllLines($envPath, $lines, (New-Object Text.UTF8Encoding $false))

Write-Host ""
Write-Host "  Публичный адрес: $url"
Write-Host "  Он записан в .env, кнопка мини-приложения в боте обновится сама."
Write-Host ""

$python = if (Test-Path "$PSScriptRoot\venv\Scripts\python.exe") { "$PSScriptRoot\venv\Scripts\python.exe" } else { "python" }
try {
  & $python run.py
} finally {
  Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
  Write-Host "Туннель остановлен."
}
