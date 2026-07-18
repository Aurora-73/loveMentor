"""头像获取 MCP 工具。

通过主系统的 WeFlow/WCD 客户端获取联系人头像，
支持任意标识符（昵称、wxid、微信号、备注名），
保存为 .jpg 格式（兼容 wechat_send 模板匹配）。

底层调用 engine/wechat_data/avatar_fetcher.py。
"""

import os
import sys
import traceback

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


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
        from engine.wechat_data.avatar_fetcher import (
            get_avatar,
            get_avatar_url,
            _find_cached_avatar,
            _query_local_avatar,
            _query_weflow_cache,
            _load_avatar_meta,
            _check_avatar_changed,
        )
        from engine.config import load_config
        from engine.importers.db_init import get_db

        config = load_config()

        # 先检查是否已有缓存（用于判断是否 updated）
        cached_before = _find_cached_avatar(name)

        # 获取头像
        avatar_path = get_avatar(
            name,
            force_refresh=force_refresh,
            check_update=check_update,
        )

        if not avatar_path:
            return {
                "success": False,
                "message": f"未找到联系人 '{name}' 的头像",
                "identifier": name,
                "avatar_path": "",
                "avatar_url": "",
                "display_name": "",
                "wxid": "",
                "updated": False,
                "error": "AVATAR_NOT_FOUND",
            }

        # 获取头像 URL 和元信息
        avatar_url = get_avatar_url(name) or ""

        # 尝试解析 wxid 和 display_name
        wxid = ""
        display_name = name

        conn = get_db(config.db_path)
        try:
            local_result = _query_local_avatar(conn, name)
            if local_result:
                wxid = local_result["wxid"]
                display_name = local_result["display_name"] or name
        finally:
            conn.close()

        if not wxid:
            cache_result = _query_weflow_cache(name)
            if cache_result:
                wxid = cache_result["wxid"]
                display_name = cache_result["display_name"] or name

        # 判断是否重新下载了
        cached_after = _find_cached_avatar(name)
        updated = (not cached_before) or (cached_before != cached_after)

        # 如果是 .png 旧格式，转换为 .jpg
        if avatar_path.endswith(".png"):
            jpg_path = avatar_path.rsplit(".", 1)[0] + ".jpg"
            try:
                from PIL import Image
                img = Image.open(avatar_path)
                img.convert("RGB").save(jpg_path, "JPEG", quality=95)
                avatar_path = jpg_path
                updated = True
            except Exception:
                # 如果转换失败，保留 .png
                pass

        # 检查文件是否存在
        if not os.path.exists(avatar_path):
            return {
                "success": False,
                "message": f"头像文件不存在: {avatar_path}",
                "identifier": name,
                "avatar_path": avatar_path,
                "avatar_url": avatar_url,
                "display_name": display_name,
                "wxid": wxid,
                "updated": False,
                "error": "FILE_NOT_FOUND",
            }

        size_kb = os.path.getsize(avatar_path) // 1024
        msg = f"头像已就绪: {display_name}"
        if updated:
            msg += f"（已更新，{size_kb} KB）"
        else:
            msg += f"（未变化，{size_kb} KB）"

        return {
            "success": True,
            "message": msg,
            "identifier": name,
            "avatar_path": avatar_path,
            "avatar_url": avatar_url[:100] + "..." if len(avatar_url) > 100 else avatar_url,
            "display_name": display_name,
            "wxid": wxid,
            "updated": updated,
            "error": None,
        }

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
