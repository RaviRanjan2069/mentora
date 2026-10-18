# Start (or repair) the free AI-tutor link for the live Mentora site (docs/deploy.md, "Ollama"):
#   Ollama (127.0.0.1:11434) -> token gateway (127.0.0.1:11435) -> ngrok permanent domain.
# Reads OLLAMA_GATEWAY_TOKEN, NGROK_DOMAIN and (optional) SITE_URL from the git-ignored .env.
# Everything runs hidden; logs go to %LOCALAPPDATA%\Mentora\logs. Safe to run again at any
# time: parts that are already running are left alone, so a scheduled task can run it every
# few minutes to restart anything that stopped (scripts/install_tutor_autostart.ps1).
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
$logs = Join-Path $env:LOCALAPPDATA "Mentora\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

function Test-Up([string]$url, [hashtable]$headers = @{}) {
    try {
        Invoke-WebRequest $url -Headers $headers -UseBasicParsing -TimeoutSec 20 | Out-Null
        return $true
    } catch { return $false }
}

function Say([string]$text, [string]$color = "Gray") {
    Write-Host $text -ForegroundColor $color
    Add-Content -Path (Join-Path $logs "status.log") -Value "$(Get-Date -Format s)  $text"
}

# 1. Ollama (normally already running from the tray)
if (-not (Test-Up "http://127.0.0.1:11434/api/tags")) {
    Say "Starting Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 2. Token gateway (never expose Ollama itself: its API can pull and delete models)
if (-not (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)) {
    Say "Starting the token gateway..."
    $env:OLLAMA_GATEWAY_TOKEN = $vars.OLLAMA_GATEWAY_TOKEN
    $python = Join-Path $root ".venv\Scripts\python.exe"
    Start-Process $python -ArgumentList "scripts\ollama_gateway.py" -WorkingDirectory $root `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "gateway.out.log") `
        -RedirectStandardError (Join-Path $logs "gateway.log")
    Start-Sleep -Seconds 4
}

# 3. ngrok on the permanent domain
if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
    Say "Starting ngrok..."
    $ngrok = Join-Path $env:LOCALAPPDATA "ngrok\ngrok.exe"
    Start-Process $ngrok -WindowStyle Hidden -ArgumentList "http", "11435", `
        "--url=$($vars.NGROK_DOMAIN)", "--log", (Join-Path $logs "ngrok.log")
    Start-Sleep -Seconds 6
}

# 4. Check the whole path the live site uses
$auth = @{ Authorization = "Bearer $($vars.OLLAMA_GATEWAY_TOKEN)" }
if (Test-Up "https://$($vars.NGROK_DOMAIN)/v1/models" $auth) {
    Say "OK: the live tutor can reach Ollama at https://$($vars.NGROK_DOMAIN)" "Green"
} else {
    Say "Not reachable yet: https://$($vars.NGROK_DOMAIN) (the next run retries)" "Yellow"
}

# 5. While this computer is on, also keep the free web service awake.
if ($vars.SITE_URL) { [void](Test-Up "$($vars.SITE_URL)/health") }
