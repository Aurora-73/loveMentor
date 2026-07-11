"""MCP 服务器配置模块。

复用 engine.config 的配置加载逻辑。
"""

from engine.config import load_config, Config

config: Config = load_config()
