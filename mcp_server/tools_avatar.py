"""头像获取 MCP 工具（薄包装层）。

通过主系统的 WeFlow/WCD 客户端获取联系人头像，
支持任意标识符（昵称、wxid、微信号、备注名），
保存为 .jpg 格式（兼容 wechat_send 模板匹配）。

业务实现已迁移到 engine/wechat_data/avatar_fetcher.py:get_avatar_with_meta。
"""

import traceback


def person_avatar(
    name: str,
    force_refresh: bool = False,
    check_update: bool = True,
) -> dict:
    """获取联系人头像并保存到本地。

    支持任意标识符：昵称、wxid、微信号、备注名、alias 均可。
    头像保存为 data/avatars/<name>.jpg，兼容 wechat_send 工具。

    头像更新策略：
    - 默认（check_update=True）: 比较头像 URL，变化才重新下载
    - force_refresh=True: 强制重新下载
    - check_update=False: 有缓存就返回，不检查更新

    数据源优先级：
    1. 本地缓存 data/avatars/（最快）
    2. 本地 core.db contacts 表
    3. WeFlow/WCD HTTP API（需要服务运行）
    4. WeFlow contacts.json 缓存（CDN 直链，不需要服务运行）

    Args:
        name: 联系人标识符（昵称/wxid/微信号/备注名/alias 均可）
        force_refresh: 为 True 时强制重新下载（默认 False）
        check_update: 为 True 时检查头像 URL 是否变化（默认 True）

    Returns:
        dict: {
            "success": bool,
            "message": str,          # 结果描述
            "identifier": str,       # 输入的标识符
            "avatar_path": str,      # 头像本地路径
            "avatar_url": str,       # 头像来源 URL
            "display_name": str,     # 解析到的显示名
            "wxid": str,             # 解析到的 wxid
            "updated": bool,         # 是否重新下载了头像
            "error": str|None,       # 失败原因
        }
    """
    try:
        from engine.wechat_data.avatar_fetcher import get_avatar_with_meta
        return get_avatar_with_meta(
            name,
            force_refresh=force_refresh,
            check_update=check_update,
        )
    except ImportError as e:
        return {
            "success": False,
            "message": f"依赖模块导入失败: {e}",
            "identifier": name,
            "avatar_path": "",
            "avatar_url": "",
            "display_name": "",
            "wxid": "",
            "updated": False,
            "error": f"IMPORT_ERROR: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行异常: {e}",
            "identifier": name,
            "avatar_path": "",
            "avatar_url": "",
            "display_name": "",
            "wxid": "",
            "updated": False,
            "error": f"RUNTIME_ERROR: {traceback.format_exc()}",
        }
