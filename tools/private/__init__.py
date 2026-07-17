"""隐私排查工具包。

提供从数据库/配置导出隐私字典、扫描文件与 git 历史、
以及重写 git 历史去除隐私的能力。

脚本入口（从项目根目录运行）：
    python -X utf8 tools/private/build_dictionary.py
    python -X utf8 tools/private/scan_files.py
    python -X utf8 tools/private/scan_git_history.py
    python -X utf8 tools/private/rewrite_git_history.py --dry-run
"""
