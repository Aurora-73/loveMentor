# WCD 开机自启动脚本
# 将此脚本快捷方式放入 shell:startup 文件夹
# 或注册为 Windows 计划任务（触发器：登录时）

param(
    [string]$ProjectRoot = "<project_root>"
)

$ErrorActionPreference = "SilentlyContinue"

# 检查 WCD 是否已运行
$wcdRunning = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "WeChatDataAnalysis"
}

if ($wcdRunning) {
    Write-Host "WCD 已在运行中，无需重复启动"
    exit 0
}

$wcdPath = Join-Path $ProjectRoot "_reference\WeChatDataAnalysis"
if (-not (Test-Path $wcdPath)) {
    Write-Host "WCD 路径不存在: $wcdPath"
    exit 1
}

Write-Host "启动 WCD 后端..."
Start-Process -FilePath "uv" -ArgumentList "run", "main.py" -WorkingDirectory $wcdPath -WindowStyle Hidden

# 等待启动
Start-Sleep -Seconds 10

# 验证启动
$wcdRunning = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "WeChatDataAnalysis"
}

if ($wcdRunning) {
    Write-Host "WCD 启动成功 (PID: $($wcdRunning.Id))"
} else {
    Write-Host "WARN: WCD 启动可能失败，请手动检查"
}
