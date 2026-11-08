$ErrorActionPreference = "Stop"
if (!(Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared не найден. Установите его по официальной инструкции:" -ForegroundColor Yellow
  Write-Host "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/"
  exit 1
}
Write-Host "Открываем временный HTTPS Quick Tunnel к http://127.0.0.1:8080" -ForegroundColor Cyan
Write-Host "Скопируйте адрес https://....trycloudflare.com из вывода cloudflared." -ForegroundColor Green
cloudflared tunnel --url http://127.0.0.1:8080
