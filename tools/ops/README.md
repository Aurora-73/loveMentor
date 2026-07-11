# Tools Ops 运维脚本

## 概述

运维脚本工具集，包括数据导出、定时任务、服务启动等操作。

## 文件列表

| 文件 | 职责 | 使用场景 |
|------|------|---------|
| `export_chats.py` | 导出聊天记录 | 将聊天记录导出为文件 |
| `extract_audio.py` | 提取音频 | 从消息中提取音频文件 |
| `extract_scheduler.py` | 提取调度器数据 | 提取调度器相关数据 |
| `picker_folder.py` | 文件夹选择器 | 选择文件夹的辅助工具 |
| `daily_sync.ps1` | 每日同步 | 每日数据同步任务 |
| `register_tasks.ps1` | 注册任务 | 注册定时任务 |
| `start_wcd.ps1` | 启动 WCD | 启动 WeChatDataAnalysis |

## 使用示例

```bash
# 导出聊天记录
python tools/ops/export_chats.py

# 提取音频
python tools/ops/extract_audio.py

# 启动 WCD（PowerShell）
.\tools\ops\start_wcd.ps1

# 设置每日同步任务（PowerShell）
.\tools\ops\register_tasks.ps1
```