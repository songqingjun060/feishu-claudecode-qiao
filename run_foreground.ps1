param(
    [string]$Config = "config.realtest.toml",
    [string]$Profile = "qiao-test"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[1/4] Checking lark-cli subscriber..." -ForegroundColor Cyan
$qiaoSubs = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "--profile $([regex]::Escape($Profile)) event \+subscribe" }

if ($qiaoSubs.Count -gt 1) {
    Write-Host "[WARN] Found multiple $Profile subscribers; cleaning them up." -ForegroundColor Yellow
    foreach ($proc in $qiaoSubs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $PSScriptRoot "data-test\feishu_ws.pid") -Force -ErrorAction SilentlyContinue
}

Write-Host "[2/4] Ensuring subscriber is running in background..." -ForegroundColor Cyan
python start_ws.py status --config $Config
if ($LASTEXITCODE -ne 0) {
    throw "start_ws.py status failed"
}

$pidFile = Join-Path $PSScriptRoot "data-test\feishu_ws.pid"
$needStart = $true
if (Test-Path -LiteralPath $pidFile) {
    $pidText = Get-Content -LiteralPath $pidFile -Raw
    $pidValue = 0
    if ([int]::TryParse($pidText.Trim(), [ref]$pidValue)) {
        $needStart = -not [bool](Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
    }
}

if ($needStart) {
    python start_ws.py start --config $Config --profile $Profile --force
    if ($LASTEXITCODE -ne 0) {
        throw "start_ws.py start failed"
    }
}

Write-Host "[3/4] Final subscriber status..." -ForegroundColor Cyan
python start_ws.py status --config $Config

Write-Host "[4/4] Starting bridge in this foreground window..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the bridge. The lark subscriber remains managed by start_ws.py." -ForegroundColor Gray
python -m feishu_claudecode_qiao --config $Config
