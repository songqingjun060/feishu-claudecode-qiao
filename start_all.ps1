param(
    [string]$Config = "config.realtest.toml",
    [string]$Profile = "qiao-test",
    [switch]$Restart,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Body
    )
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & $Body
}

function Assert-Ok {
    param([string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

function Get-BridgePidFile {
    param([string]$ConfigPath)
    $code = @"
from pathlib import Path
from feishu_claudecode_qiao.config import load_config
cfg = load_config(r'''$ConfigPath''')
print(Path(cfg.bridge_data_dir).resolve() / 'bridge.pid')
"@
    return (python -c $code).Trim()
}

function Test-PidRunning {
    param([string]$PidFile)
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $false
    }
    $pidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $pidValue = 0
    if (-not [int]::TryParse($pidText, [ref]$pidValue)) {
        return $false
    }
    return [bool](Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
}

Invoke-Step "Config" {
    Write-Host "Project : $PSScriptRoot"
    Write-Host "Config  : $Config"
    Write-Host "Profile : $Profile"
    Write-Host "Mode    : $(if ($Restart) { 'restart' } else { 'start-if-needed' })"
}

$bridgePidFile = Get-BridgePidFile -ConfigPath $Config

if ($Restart) {
    Invoke-Step "Stop bridge" {
        python -m feishu_claudecode_qiao --config $Config --stop
    }
    Invoke-Step "Restart WebSocket subscriber" {
        python start_ws.py restart --config $Config --profile $Profile --force
        Assert-Ok "WebSocket subscriber restart failed"
    }
} else {
    Invoke-Step "Ensure WebSocket subscriber" {
        python start_ws.py status --config $Config
        if ($LASTEXITCODE -ne 0) {
            throw "WebSocket subscriber status failed"
        }
        $wsPidFile = Join-Path (Split-Path -Parent $bridgePidFile) "feishu_ws.pid"
        if (-not (Test-PidRunning -PidFile $wsPidFile)) {
            python start_ws.py start --config $Config --profile $Profile --force
            Assert-Ok "WebSocket subscriber start failed"
        }
    }
}

Invoke-Step "WebSocket status" {
    python start_ws.py status --config $Config
    Assert-Ok "WebSocket subscriber status failed"
}

if ($Foreground) {
    Invoke-Step "Start bridge in foreground" {
        Write-Host "Press Ctrl+C to stop the bridge. The WebSocket subscriber stays managed by start_ws.py." -ForegroundColor Gray
        python -m feishu_claudecode_qiao --config $Config
    }
    exit $LASTEXITCODE
}

Invoke-Step "Ensure bridge process" {
    if ($Restart -or -not (Test-PidRunning -PidFile $bridgePidFile)) {
        Start-Process -FilePath python `
            -ArgumentList "-m","feishu_claudecode_qiao","--config",$Config `
            -WorkingDirectory $PSScriptRoot `
            -WindowStyle Hidden
        Start-Sleep -Seconds 2
    }
    python -m feishu_claudecode_qiao --config $Config --status
    Assert-Ok "Bridge status failed"
}

Invoke-Step "Done" {
    Write-Host "New bridge is ready." -ForegroundColor Green
    Write-Host "Use this to restart everything:"
    Write-Host "  .\start_all.ps1 -Restart"
    Write-Host "Use this for visible foreground logs:"
    Write-Host "  .\start_all.ps1 -Restart -Foreground"
}
