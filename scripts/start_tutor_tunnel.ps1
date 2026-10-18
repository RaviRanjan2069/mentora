# Start the free AI-tutor link for the live Mentora site (docs/deploy.md, "Ollama"):
#   Ollama (127.0.0.1:11434) -> token gateway (127.0.0.1:11435) -> ngrok permanent domain.
# Reads OLLAMA_GATEWAY_TOKEN and NGROK_DOMAIN from the git-ignored .env. Safe to run twice:
# parts that are already running are left alone.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start_tutor_tunnel.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$vars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') { $vars[$Matches[1]] = $Matches[2] }
}
foreach ($k in "OLLAMA_GATEWAY_TOKEN", "NGROK_DOMAIN") {
    if (-not $vars[$k]) { throw "$k is missing in $envFile" }
}

function Test-Up([string]$url, [hashtable]$headers = @{}) {
    try {
        Invoke-WebRequest $url -Headers $headers -UseBasicParsing -TimeoutSec 20 | Out-Null
        return $true
    } catch { return $false }
}

# 1. Ollama (normally already running from the tray)
if (-not (Test-Up "http://127.0.0.1:11434/api/tags")) {
    Write-Host "Starting Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 2. Token gateway (never expose Ollama itself: its API can pull and delete models)
if (-not (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "Starting the token gateway..."
    $env:OLLAMA_GATEWAY_TOKEN = $vars.OLLAMA_GATEWAY_TOKEN
    $python = Join-Path $root ".venv\Scripts\python.exe"
    Start-Process $python -ArgumentList "scripts\ollama_gateway.py" -WorkingDirectory $root -WindowStyle Minimized
    Start-Sleep -Seconds 4
}

# 3. ngrok on the permanent domain
if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "Starting ngrok..."
    $ngrok = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.exe"
    Start-Process $ngrok -ArgumentList "http", "11435", "--url=$($vars.NGROK_DOMAIN)" -WindowStyle Minimized
    Start-Sleep -Seconds 6
}

# 4. Check the whole path the live site uses
$auth = @{ Authorization = "Bearer $($vars.OLLAMA_GATEWAY_TOKEN)" }
if (Test-Up "https://$($vars.NGROK_DOMAIN)/v1/models" $auth) {
    Write-Host "OK: the live tutor can reach Ollama at https://$($vars.NGROK_DOMAIN)" -ForegroundColor Green
} else {
    Write-Host "Not reachable yet: https://$($vars.NGROK_DOMAIN) (wait a few seconds and run again)" -ForegroundColor Yellow
}
Write-Host "Keep this computer awake; closing the minimized gateway or ngrok windows stops the tutor."
