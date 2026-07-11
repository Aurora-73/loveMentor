# LoveMentor 每日全量同步脚本
# 配合 Windows Task Scheduler 使用，每天凌晨执行
# 用法：注册为计划任务，每天 03:00 执行

param(
    [string]$ProjectRoot = "<project_root>",
    [string]$LogFile = "<project_root>\data\system\sync_log.txt"
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "=== LoveMentor 每日同步开始 ==="

# Step 1: 检查 WCD 后端是否运行，未启动则尝试启动
Write-Log "Step 1: 检查 WCD 后端..."
$wcdProcess = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "WeChatDataAnalysis"
}

if (-not $wcdProcess) {
    Write-Log "WCD 未运行，尝试启动..."
    $wcdPath = Join-Path $ProjectRoot "_reference\WeChatDataAnalysis"
    if (Test-Path $wcdPath) {
        Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $wcdPath -WindowStyle Hidden
        Write-Log "WCD 启动命令已发送，等待 15 秒..."
        Start-Sleep -Seconds 15
    } else {
        Write-Log "WARN: WCD 路径不存在: $wcdPath"
    }
} else {
    Write-Log "WCD 已在运行中"
}

# Step 2: 执行全量同步
Write-Log "Step 2: 执行全量同步..."
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $ProjectRoot

try {
    $syncScript = @"
import sys
sys.path.insert(0, r'$ProjectRoot')
from engine.tools import sync
result = sync(mode='full')
print(result)
"@
    $result = $syncScript | python -
    Write-Log "同步结果: $result"
} catch {
    Write-Log "ERROR: 同步失败 - $_"
}

# Step 3: 同步朋友圈互动
Write-Log "Step 3: 同步朋友圈互动..."
try {
    $momentsScript = @"
import sys
sys.path.insert(0, r'$ProjectRoot')
from engine.tools import sync
result = sync(mode='incremental', meta_only=False)
print(result)
"@
    $result = $momentsScript | python -
    Write-Log "朋友圈同步结果: $result"
} catch {
    Write-Log "WARN: 朋友圈同步失败 - $_"
}

Write-Log "=== LoveMentor 每日同步完成 ==="
