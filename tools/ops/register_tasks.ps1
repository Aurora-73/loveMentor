# 注册 Windows 计划任务
# 以管理员身份运行此脚本

param(
    [string]$ProjectRoot = "<project_root>"
)

$ErrorActionPreference = "Stop"

Write-Host "=== LoveMentor 计划任务注册 ==="
Write-Host ""

# Task 1: WCD 开机自启动
$taskName1 = "LoveMentor_WCD_AutoStart"
$scriptPath1 = Join-Path $ProjectRoot "scripts\start_wcd.ps1"

Write-Host "注册任务 1: $taskName1 (WCD 开机自启)"
try {
    Unregister-ScheduledTask -TaskName $taskName1 -Confirm:$false -ErrorAction SilentlyContinue
    $action1 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$scriptPath1`" -ProjectRoot `"$ProjectRoot`""
    $trigger1 = New-ScheduledTaskTrigger -AtLogOn
    $settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName1 -Action $action1 -Trigger $trigger1 -Settings $settings1 -Description "LoveMentor WCD 后端开机自启动" -Force
    Write-Host "  [OK] $taskName1 注册成功"
} catch {
    Write-Host "  [ERROR] $taskName1 注册失败: $_"
}

# Task 2: 每日全量同步
$taskName2 = "LoveMentor_DailySync"
$scriptPath2 = Join-Path $ProjectRoot "scripts\daily_sync.ps1"

Write-Host "注册任务 2: $taskName2 (每日 03:00 全量同步)"
try {
    Unregister-ScheduledTask -TaskName $taskName2 -Confirm:$false -ErrorAction SilentlyContinue
    $action2 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$scriptPath2`" -ProjectRoot `"$ProjectRoot`""
    $trigger2 = New-ScheduledTaskTrigger -Daily -At "03:00"
    $settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $taskName2 -Action $action2 -Trigger $trigger2 -Settings $settings2 -Description "LoveMentor 每日全量数据同步" -Force
    Write-Host "  [OK] $taskName2 注册成功"
} catch {
    Write-Host "  [ERROR] $taskName2 注册失败: $_"
}

Write-Host ""
Write-Host "=== 计划任务注册完成 ==="
Write-Host ""
Write-Host "已注册任务："
Write-Host "  1. $taskName1 — 登录时自动启动 WCD 后端"
Write-Host "  2. $taskName2 — 每天 03:00 执行全量同步"
Write-Host ""
Write-Host "管理命令："
Write-Host "  查看任务: Get-ScheduledTask -TaskName 'LoveMentor_*'"
Write-Host "  手动运行: Start-ScheduledTask -TaskName '$taskName2'"
Write-Host "  删除任务: Unregister-ScheduledTask -TaskName '$taskName2' -Confirm:`$false"
