"""微信自动化模块的日志工具。

提供分级日志功能：
- DEBUG: 详细调试信息（匹配点、坐标计算等）
- INFO: 正常流程信息（阶段开始、完成）
- WARNING: 警告（低置信度、回退等）
- ERROR: 错误（失败、异常）

使用方式:
    from logger import get_logger
    logger = get_logger(__name__)
    logger.info("开始执行")
    logger.debug(f"坐标: ({x}, {y})")
    logger.warning("置信度较低")
    logger.error("执行失败")

日志同时输出到控制台和文件（data/outputs/wechat_sender.log）
"""

import logging
import os
import sys
from datetime import datetime

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "data", "outputs")
os.makedirs(_LOG_DIR, exist_ok=True)

# 日志文件路径（按日期轮转）
_LOG_FILE = os.path.join(_LOG_DIR, f"wechat_sender_{datetime.now().strftime('%Y%m%d')}.log")

# 日志格式
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"

# 已配置的 logger 名称集合
_configured_loggers = set()


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取指定名称的 logger。

    首次调用会配置控制台和文件输出，后续调用直接返回已配置的 logger。

    Args:
        name: logger 名称（通常用 __name__）
        level: 日志级别（默认 INFO）

    Returns:
        logging.Logger 实例
    """
    logger = logging.getLogger(name)

    if name in _configured_loggers:
        return logger

    logger.setLevel(level)

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    logger.addHandler(console_handler)

    # 文件输出
    try:
        file_handler = logging.FileHandler(_LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        logger.addHandler(file_handler)
    except Exception:
        pass  # 文件写入失败不影响控制台输出

    _configured_loggers.add(name)
    return logger


def set_global_level(level: int):
    """设置所有已创建 logger 的日志级别。

    Args:
        level: 日志级别（logging.DEBUG / INFO / WARNING / ERROR）
    """
    for name in _configured_loggers:
        logging.getLogger(name).setLevel(level)
    # 同时设置控制台 handler 级别
    for name in _configured_loggers:
        for handler in logging.getLogger(name).handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(level)
