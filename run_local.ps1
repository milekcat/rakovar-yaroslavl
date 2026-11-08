$ErrorActionPreference = "Stop"
if (!(Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Создан .env. Заполните MAX_BOT_TOKEN, FLASK_SECRET_KEY и ADMIN_PASSWORD_HASH, затем запустите скрипт снова." -ForegroundColor Yellow
  exit 1
}
if (Select-String -Path '.env' -Pattern '^\s*MAX_BOT_TOKEN\s*=\s*$' -Quiet) {
  Write-Host "MAX_BOT_TOKEN пуст. Добавьте токен локально в .env; не отправляйте его в чат и не коммитьте файл." -ForegroundColor Yellow
  exit 1
}
if (Select-String -Path '.env' -Pattern '^\s*ADMIN_PASSWORD_HASH\s*=\s*$' -Quiet) {
  Write-Host "ADMIN_PASSWORD_HASH пуст. Сгенерируйте хеш пароля командой из docs/MAX_LOCAL_SETUP.md." -ForegroundColor Yellow
  exit 1
}
if (Select-String -Path '.env' -Pattern '^\s*FLASK_SECRET_KEY\s*=\s*replace-with-a-long-random-value\s*$' -Quiet) {
  Write-Host "Замените тестовый FLASK_SECRET_KEY случайной длинной строкой." -ForegroundColor Yellow
  exit 1
}
if (!(Test-Path ".venv")) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
$projectPath = (Get-Location).Path
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
Start-Process powershell -ArgumentList @('-NoExit','-Command', "Set-Location -LiteralPath '$projectPath'; & '$pythonPath' app.py")
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList @('-NoExit','-Command', "Set-Location -LiteralPath '$projectPath'; & '$pythonPath' max_bot.py")
Write-Host "Web: http://127.0.0.1:8080" -ForegroundColor Green
Write-Host "MAX bot polling started in a separate window. For Mini App use an HTTPS tunnel (cloudflared)." -ForegroundColor Cyan
