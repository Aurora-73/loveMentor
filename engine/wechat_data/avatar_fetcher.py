"""头像获取模块 — 通过主系统的 WeFlow/WCD 客户端获取联系人头像。

参考主系统 sync.py 的客户端初始化方式，支持：
1. 按名称/标识符获取单个头像（多级查询：本地缓存 → DB → API → contacts.json 缓存）
2. 批量下载所有联系人头像

数据源优先级：
  1. 本地缓存 data/avatars/（最快）
  2. 本地 core.db 的 contacts 表（有 avatar_url，可能是 CDN 或代理 URL）
  3. WeFlow/WCD HTTP API（需要服务运行中）
  4. WeFlow contacts.json 缓存（CDN 直链，不需要服务运行）

用法：
    from engine.wechat_data.avatar_fetcher import get_avatar
    path = get_avatar("小鱼儿")
    print(path)  # data/avatars/小鱼儿.png

    # 批量下载
    from engine.wechat_data.avatar_fetcher import batch_download_avatars
    batch_download_avatars()
"""
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from engine.config import Config, load_config
from engine.importers.db_init import get_db

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 头像保存目录
AVATARS_DIR = _PROJECT_ROOT / "data" / "avatars"
# WeFlow contacts.json 缓存路径
_WEFLOW_CONTACTS_JSON = Path(os.environ.get("APPDATA", "")) / "weflow" / "cache" / "contacts.json"

# 微信 CDN 下载 Headers（来自 WeFlow avatarFileCacheService.ts）
_CDN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090719) XWEB/8351"
    ),
    "Referer": "https://servicewechat.com/",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

_DOWNLOAD_TIMEOUT = 15

# 头像文件格式（.jpg 兼容 wechat_send 模板匹配）
_AVATAR_EXT = ".jpg"

# 头像元数据文件（记录 URL → 用于变化检测）
_META_FILE = AVATARS_DIR / ".avatar_meta.json"


# ── 工具函数 ──────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """将联系人名转为安全的文件名。"""
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe[:50] if safe else "unknown"


def _avatar_local_path(identifier: str, wxid: str = "") -> Path:
    """根据标识符生成头像本地路径。

    优先用 wxid（唯一），其次用 identifier。
    """
    if wxid:
        return AVATARS_DIR / f"{_safe_filename(wxid)}{_AVATAR_EXT}"
    return AVATARS_DIR / f"{_safe_filename(identifier)}{_AVATAR_EXT}"


def _find_cached_avatar(identifier: str, wxid: str = "") -> Path | None:
    """在本地缓存中查找头像，仅按 wxid 和 alias(微信号) 查找（不再用 display_name）。

    查找顺序：wxid.jpg → identifier.jpg → wxid.png → identifier.png

    注意：identifier 应为微信号（alias），不再支持 display_name 模糊匹配，
          避免同名联系人（display_name 相同）导致头像错配。
    """
    # 优先查找 .jpg 格式（wechat_send 需要）
    if wxid:
        for ext in (_AVATAR_EXT, ".png"):
            p = AVATARS_DIR / f"{_safe_filename(wxid)}{ext}"
            if p.exists():
                return p

    # 按 identifier（微信号）查找
    if identifier:
        for ext in (_AVATAR_EXT, ".png"):
            p = AVATARS_DIR / f"{_safe_filename(identifier)}{ext}"
            if p.exists():
                return p

    return None


# ── 头像变化检测 ──────────────────────────────────────────────────────

def _load_avatar_meta() -> dict:
    """加载头像元数据（URL → 文件映射，用于变化检测）。"""
    if not _META_FILE.is_file():
        return {}
    try:
        return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_avatar_meta(meta: dict) -> None:
    """保存头像元数据。"""
    try:
        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        _META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"保存头像元数据失败: {e}")


def _check_avatar_changed(wxid: str, avatar_url: str) -> bool:
    """检查头像 URL 是否变化（快速判断，不需要下载）。

    Args:
        wxid: 联系人 wxid
        avatar_url: 当前头像 URL

    Returns:
        bool: True 表示头像已变化（需要重新下载），False 表示未变化
    """
    meta = _load_avatar_meta()
    record = meta.get(wxid, {})
    stored_url = record.get("url", "")
    # URL 相同则认为头像未变化（CDN URL 含版本信息）
    return stored_url != avatar_url


def _update_avatar_meta(wxid: str, display_name: str, avatar_url: str, file_path: Path) -> None:
    """更新头像元数据记录。"""
    meta = _load_avatar_meta()
    meta[wxid] = {
        "display_name": display_name,
        "url": avatar_url,
        "file": file_path.name,
        "downloaded_at": int(__import__("time").time()),
    }
    _save_avatar_meta(meta)


def _is_cdn_url(url: str) -> bool:
    """判断 URL 是否为微信 CDN 直链（不需要本地服务）。"""
    return "qlogo.cn" in url or "qlogo" in url


def _is_proxy_url(url: str) -> bool:
    """判断 URL 是否为本地代理 URL（需要 WeFlow/WCD 服务运行）。"""
    return "127.0.0.1" in url or "localhost" in url


def _is_data_url(url: str) -> bool:
    """判断是否为 base64 data URL。"""
    return url.startswith("data:")


def _download_avatar(url: str, save_path: Path) -> bool:
    """下载头像到本地。支持 CDN URL 和 base64 data URL。

    Args:
        url: 头像 URL（CDN 直链 / WCD 代理 / base64 data URL）
        save_path: 本地保存路径

    Returns:
        bool: 是否下载成功
    """
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # 处理 base64 data URL
    if _is_data_url(url):
        try:
            import base64
            # 格式: data:image/jpeg;base64,/9j/4AAQ...
            header, data = url.split(",", 1)
            data_bytes = base64.b64decode(data)
            save_path.write_bytes(data_bytes)
            return True
        except Exception as e:
            logger.warning(f"解析 data URL 失败: {e}")
            return False

    # 处理 HTTP/HTTPS URL
    try:
        req = urllib.request.Request(url, headers=_CDN_HEADERS)
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            if resp.status == 200:
                data = resp.read()
                save_path.write_bytes(data)
                return True
            logger.warning(f"下载头像 HTTP {resp.status}: {url[:80]}")
            return False
    except urllib.error.HTTPError as e:
        logger.warning(f"下载头像 HTTPError {e.code}: {e.reason} | {url[:80]}")
        return False
    except Exception as e:
        logger.warning(f"下载头像失败: {e} | {url[:80]}")
        return False


# ── 客户端创建 ────────────────────────────────────────────────────────

def _create_client(config: Config):
    """根据 config.weflow.backend 创建 WeFlowClient 或 WCDClient。

    参考 sync.py 的初始化方式。
    """
    if config.weflow.backend == "wcd":
        from engine.importers.wcd_client import WCDClient
        return WCDClient(
            base_url=config.weflow.base_url,
            token=config.weflow.token,
            timeout=config.weflow.timeout,
            decrypted_db_dir=config.weflow.decrypted_db_dir or None,
        )
    else:
        from engine.importers.weflow_client import WeFlowClient
        return WeFlowClient(
            base_url=config.weflow.base_url,
            token=config.weflow.token,
            timeout=config.weflow.timeout,
        )


# ── 本地 DB 查询 ──────────────────────────────────────────────────────

def _query_local_avatar(conn: sqlite3.Connection, identifier: str) -> dict | None:
    """从本地 core.db 查询联系人信息（即使 avatar_url 为空也返回）。

    匹配顺序：alias > id(wxid) > display_name > remark > nickname
    （alias 和 wxid 唯一，优先匹配；display_name 可能重名，靠后）

    重要：即使 avatar_url 为空也会返回，调用方需要根据 wxid 进一步查询
    contacts.json 等其他数据源获取 avatarUrl。

    Returns:
        {"wxid": ..., "display_name": ..., "alias": ..., "avatar_url": ...} 或 None
        avatar_url 可能为空字符串
    """
    # 精确匹配（不要求 avatar_url 非空）
    for field in ("alias", "id", "display_name", "remark", "nickname"):
        row = conn.execute(
            f"SELECT id, display_name, alias, avatar_url FROM contacts "
            f"WHERE {field} = ?",
            (identifier,),
        ).fetchone()
        if row:
            return {
                "wxid": row["id"],
                "display_name": row["display_name"],
                "alias": row["alias"] if row["alias"] else "",
                "avatar_url": row["avatar_url"] if row["avatar_url"] else "",
            }

    # 模糊匹配（LIKE）— 仅在 display_name/remark/nickname/alias 中查找
    for field in ("alias", "display_name", "remark", "nickname"):
        row = conn.execute(
            f"SELECT id, display_name, alias, avatar_url FROM contacts "
            f"WHERE {field} LIKE ?",
            (f"%{identifier}%",),
        ).fetchone()
        if row:
            return {
                "wxid": row["id"],
                "display_name": row["display_name"],
                "alias": row["alias"] if row["alias"] else "",
                "avatar_url": row["avatar_url"] if row["avatar_url"] else "",
            }

    return None


# ── API 查询 ──────────────────────────────────────────────────────────

def _query_api_avatar(client, keyword: str) -> dict | None:
    """通过 WeFlow/WCD API 按关键词搜索联系人头像。

    Returns:
        {"wxid": ..., "display_name": ..., "alias": ..., "avatar_url": ...} 或 None
    """
    try:
        contacts = client.list_contacts(keyword=keyword, limit=20)
    except Exception as e:
        logger.warning(f"API 查询联系人失败: {e}")
        return None

    if not contacts:
        return None

    # 精确匹配优先
    for c in contacts:
        for field in ("displayName", "remark", "nickname", "alias", "username"):
            val = c.get(field, "")
            if val and val == keyword:
                return {
                    "wxid": c.get("username", ""),
                    "display_name": c.get("displayName", ""),
                    "alias": c.get("alias", "") or "",
                    "avatar_url": c.get("avatarUrl", ""),
                }

    # 模糊匹配
    for c in contacts:
        for field in ("displayName", "remark", "nickname", "alias"):
            val = c.get(field, "")
            if val and keyword in val:
                return {
                    "wxid": c.get("username", ""),
                    "display_name": c.get("displayName", ""),
                    "alias": c.get("alias", "") or "",
                    "avatar_url": c.get("avatarUrl", ""),
                }

    # 如果只有一个结果，直接用
    if len(contacts) == 1:
        c = contacts[0]
        return {
            "wxid": c.get("username", ""),
            "display_name": c.get("displayName", ""),
            "alias": c.get("alias", "") or "",
            "avatar_url": c.get("avatarUrl", ""),
        }

    return None


# ── WeFlow contacts.json 缓存查询 ─────────────────────────────────────

_weflow_cache: dict | None = None
_weflow_cache_loaded = False


def _load_weflow_cache() -> dict:
    """加载 WeFlow contacts.json 缓存（带模块级缓存）。

    contacts.json 格式：
      { "wxid_xxx": { "displayName": "名字", "avatarUrl": "https://wx.qlogo.cn/...", ... } }
    """
    global _weflow_cache, _weflow_cache_loaded
    if _weflow_cache_loaded:
        return _weflow_cache or {}

    _weflow_cache_loaded = True
    if not _WEFLOW_CONTACTS_JSON.is_file():
        _weflow_cache = {}
        return {}

    try:
        _weflow_cache = json.loads(_WEFLOW_CONTACTS_JSON.read_text(encoding="utf-8"))
        logger.info(f"加载 WeFlow contacts.json: {len(_weflow_cache)} 个联系人")
    except Exception as e:
        logger.warning(f"加载 contacts.json 失败: {e}")
        _weflow_cache = {}
    return _weflow_cache or {}


def _url_priority(url: str) -> int:
    """URL 类型优先级：数字越大优先级越高。

    CDN URL（qlogo.cn）是微信实时头像，优先级最高。
    代理 URL（127.0.0.1）需要本地服务，优先级中。
    data URL（base64）通常是从本地 DB 导出的过时缓存，优先级最低。
    其他 HTTP URL 按代理 URL 级别处理。
    """
    if not url:
        return 0
    if "qlogo.cn" in url or "qlogo" in url:  # CDN URL
        return 3
    if url.startswith("data:"):  # data URL（可能是过时缓存）
        return 1
    return 2  # 代理 URL 或其他 HTTP URL


def _query_weflow_cache(identifier: str) -> dict | None:
    """从 WeFlow contacts.json 缓存中查找联系人头像。

    按 URL 类型优先级返回：CDN URL > 代理 URL > data URL。

    当存在多个同名联系人时（例如用户删好友重新添加导致 wxid 变化），
    旧 wxid 的 data URL 会被新 wxid 的 CDN URL 取代，避免取到过时头像。

    Returns:
        {"wxid": ..., "display_name": ..., "alias": ..., "avatar_url": ...} 或 None
    """
    cache = _load_weflow_cache()
    if not cache:
        return None

    # 精确匹配：收集所有匹配项，按 URL 优先级排序
    exact_matches = []
    for wxid, info in cache.items():
        display_name = info.get("displayName", "")
        alias = info.get("alias", "") or ""
        if identifier in (wxid, display_name, alias, info.get("remark", ""), info.get("nickname", "")):
            url = info.get("avatarUrl", "")
            if url:
                exact_matches.append({
                    "wxid": wxid,
                    "display_name": display_name,
                    "alias": alias,
                    "avatar_url": url,
                    "_priority": _url_priority(url),
                })

    if exact_matches:
        exact_matches.sort(key=lambda x: x["_priority"], reverse=True)
        best = exact_matches[0]
        if len(exact_matches) > 1:
            url_type = {3: "CDN", 2: "代理/HTTP", 1: "data"}.get(best["_priority"], "?")
            logger.info(
                f"contacts.json 精确匹配 {len(exact_matches)} 条，"
                f"选择优先级最高的: wxid={best['wxid']} URL类型={url_type}"
            )
        return {
            "wxid": best["wxid"],
            "display_name": best["display_name"],
            "alias": best["alias"],
            "avatar_url": best["avatar_url"],
        }

    # 模糊匹配：同样收集所有匹配项，按 URL 优先级排序
    fuzzy_matches = []
    for wxid, info in cache.items():
        display_name = info.get("displayName", "")
        alias = info.get("alias", "") or ""
        if display_name and identifier in display_name:
            url = info.get("avatarUrl", "")
            if url:
                fuzzy_matches.append({
                    "wxid": wxid,
                    "display_name": display_name,
                    "alias": alias,
                    "avatar_url": url,
                    "_priority": _url_priority(url),
                })

    if fuzzy_matches:
        fuzzy_matches.sort(key=lambda x: x["_priority"], reverse=True)
        best = fuzzy_matches[0]
        if len(fuzzy_matches) > 1:
            url_type = {3: "CDN", 2: "代理/HTTP", 1: "data"}.get(best["_priority"], "?")
            logger.info(
                f"contacts.json 模糊匹配 {len(fuzzy_matches)} 条，"
                f"选择优先级最高的: wxid={best['wxid']} URL类型={url_type}"
            )
        return {
            "wxid": best["wxid"],
            "display_name": best["display_name"],
            "alias": best["alias"],
            "avatar_url": best["avatar_url"],
        }

    return None


# ── WeFlow CDP 数据源（强制刷新单个联系人头像 URL） ────────────────────

def _query_avatar_via_weflow_cdp(
    identifier: str,
    wxid_hint: str = "",
    *,
    force_refresh: bool = True,
) -> dict | None:
    """通过 CDP 调用 WeFlow 的 refreshContactAvatar 拿最新头像 URL。

    数据源优先级最高的"实时"查询：绕过 WeFlow L1/L2 TTL 缓存，
    直接从 wcdb 数据库读取最新 avatarUrl，并增量写回 contacts.json。

    Args:
        identifier: 联系人标识符（display_name / alias / wxid）
        wxid_hint: 已知的 wxid（如果有，直接用；没有则用 search_contact 反查）
        force_refresh: True=强制调 refreshContactAvatar 绕过 WeFlow 缓存；
                       False=仅当其他数据源都没拿到 URL 时才用

    Returns:
        dict: { wxid, display_name, alias, avatar_url } 或 None
    """
    try:
        # 延迟导入，避免在 WeFlow 未启动时报错
        import os
        import sys
        # 把项目根目录加到 sys.path（确保能 import mcp_server.weflow_cdp）
        project_root = _PROJECT_ROOT.parent if hasattr(_PROJECT_ROOT, "parent") else _PROJECT_ROOT
        # _PROJECT_ROOT 是 Path，是 loveMentor 根目录
        project_root_str = str(_PROJECT_ROOT)
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        from mcp_server.weflow_cdp import refresh_contact_avatar, search_contact
    except ImportError as e:
        logger.debug(f"weflow_cdp 模块不可用: {e}")
        return None
    except Exception as e:
        logger.debug(f"导入 weflow_cdp 异常: {e}")
        return None

    wxid = wxid_hint or ""
    if not wxid:
        # 用 search_contact 反查 wxid
        search_result = search_contact(identifier, limit=5)
        if not search_result.get("success") or not search_result.get("contacts"):
            logger.debug(f"CDP search_contact('{identifier}') 无结果")
            return None
        # 取第一个匹配
        first = search_result["contacts"][0]
        wxid = first.get("username", "")
        if not wxid:
            return None
        logger.info(f"CDP search_contact 反查到 wxid={wxid} (displayName={first.get('displayName', '')})")

    # 调用 refreshContactAvatar 强制刷新
    refresh_result = refresh_contact_avatar(wxid)
    if not refresh_result.get("success"):
        # CDP 未开启 / WeFlow 后端未响应 → 自动启动 WeFlow 后重试一次
        err = refresh_result.get("error", "unknown")
        if (not refresh_result.get("cdp_used")) or "CDP" in err or "WeFlow" in err:
            logger.info(
                f"WeFlow CDP 不可用（{err}），自动启动 WeFlow 后重试..."
            )
            try:
                from mcp_server.tools_read import weflow_start
                start_result = weflow_start(timeout=60, force_restart_without_cdp=True)
                if start_result.get("success"):
                    logger.info(f"WeFlow 已启动，重试 refreshContactAvatar...")
                    refresh_result = refresh_contact_avatar(wxid)
                else:
                    logger.warning(
                        f"WeFlow 启动失败: {start_result.get('message', 'unknown')}"
                    )
            except Exception as e:
                logger.warning(f"自动启动 WeFlow 异常: {e}")
        if not refresh_result.get("success"):
            logger.warning(
                f"CDP refreshContactAvatar('{wxid}') 失败: {refresh_result.get('error', 'unknown')}"
            )
            return None

    avatar_url = refresh_result.get("avatarUrl", "")
    display_name = refresh_result.get("displayName", "") or identifier
    # alias 不能从 refresh_result 拿到，先用空字符串（不强制需要）
    if not avatar_url:
        logger.warning(f"CDP refreshContactAvatar('{wxid}') 返回空 avatarUrl")
        return None

    logger.info(f"CDP refreshContactAvatar 命中: {display_name} ({wxid}) url={avatar_url[:60]}...")
    return {
        "wxid": wxid,
        "display_name": display_name,
        "alias": "",  # refreshContactAvatar 不返回 alias
        "avatar_url": avatar_url,
    }


# ── 公开接口 ──────────────────────────────────────────────────────────

def get_avatar(
    identifier: str,
    *,
    config: Config | None = None,
    force_refresh: bool = False,
    check_update: bool = True,
) -> str | None:
    """根据名称或标识符获取联系人头像。

    查询顺序：
    1. 查询头像 URL（本地 DB → WeFlow API → contacts.json 缓存）
    2. URL 变化检测：如果 URL 未变化且本地有缓存，直接返回（check_update=True 时）
    3. 下载头像到本地（.jpg 格式）

    头像更新策略：
    - force_refresh=True: 强制重新下载，忽略缓存
    - check_update=True（默认）: 比较 URL，变化才下载
    - check_update=False: 有缓存就返回，不检查更新

    头像文件命名规则（重要）：
    - 主文件：data/avatars/<wxid>.jpg（wxid 唯一）
    - 副本：data/avatars/<alias>.jpg（微信号唯一，供 wechat_send 用微信号定位头像）
    - 不再用 display_name 作为文件名，避免同名联系人头像互相覆盖

    Args:
        identifier: 联系人名称或标识符（display_name / remark / nickname / alias / wxid）
        config: 全局配置（None 时自动加载）
        force_refresh: 为 True 时跳过本地缓存，强制重新下载
        check_update: 为 True 时检查头像 URL 是否变化（默认 True）

    Returns:
        头像本地文件路径，失败返回 None
    """
    if config is None:
        config = load_config()

    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 查询头像 URL（先查 DB，再查 API，最后 contacts.json）
    avatar_url = None
    wxid = ""
    display_name = identifier
    alias = ""

    # 1a. 查询本地 DB
    conn = get_db(config.db_path)
    try:
        local_result = _query_local_avatar(conn, identifier)
    finally:
        conn.close()

    if local_result:
        avatar_url = local_result["avatar_url"]
        wxid = local_result["wxid"]
        display_name = local_result["display_name"] or identifier
        alias = local_result.get("alias", "") or ""
        logger.info(f"本地 DB 命中: {display_name} ({wxid}) alias={alias or 'N/A'}")

        # 联邦查询：DB 提供身份（wxid/alias），contacts.json 提供 avatarUrl
        # 场景1: DB 中 avatar_url 为空（未同步）→ 用 wxid 查 contacts.json 兜底
        # 场景2: DB 中是代理 URL → 用 wxid 查 contacts.json 获取 CDN URL
        if not avatar_url:
            # 场景1: DB 无 avatar_url，用 wxid 查 contacts.json
            if wxid:
                cache_result = _query_weflow_cache(wxid)
                if cache_result:
                    avatar_url = cache_result["avatar_url"]
                    if not alias and cache_result.get("alias"):
                        alias = cache_result["alias"]
                    logger.info(f"DB 无 avatar_url，从 contacts.json 兜底 (wxid={wxid})")
        elif _is_proxy_url(avatar_url):
            # 场景2: 代理 URL，尝试用 contacts.json 获取 CDN URL
            cache_result = _query_weflow_cache(wxid) or _query_weflow_cache(alias) or _query_weflow_cache(display_name)
            if cache_result and _is_cdn_url(cache_result["avatar_url"]):
                avatar_url = cache_result["avatar_url"]
                if not alias and cache_result.get("alias"):
                    alias = cache_result["alias"]
                logger.info(f"代理 URL → CDN URL: {display_name}")

    # 1b. API 查询（如果 DB 没找到）
    if not avatar_url:
        client = _create_client(config)
        if client.health():
            api_result = _query_api_avatar(client, identifier)
            if api_result:
                avatar_url = api_result["avatar_url"]
                wxid = api_result["wxid"]
                display_name = api_result["display_name"] or identifier
                alias = api_result.get("alias", "") or ""
                logger.info(f"API 命中: {display_name} ({wxid}) alias={alias or 'N/A'}")
        else:
            logger.info(f"WeFlow API 不可用: {config.weflow.base_url}，尝试 contacts.json 缓存...")

    # 1c. WeFlow contacts.json 缓存兜底
    if not avatar_url:
        cache_result = _query_weflow_cache(identifier)
        if cache_result:
            avatar_url = cache_result["avatar_url"]
            wxid = cache_result["wxid"]
            display_name = cache_result["display_name"] or identifier
            alias = cache_result.get("alias", "") or ""
            logger.info(f"contacts.json 命中: {display_name} ({wxid}) alias={alias or 'N/A'}")

    # 1d. WeFlow CDP 强制刷新（force_refresh=True 时优先使用，覆盖之前数据源的 URL）
    # 这是最可靠的数据源：直接从 wcdb 数据库读最新 avatarUrl，绕过 L1/L2 TTL 缓存
    # 场景1: force_refresh=True → 即使用其他数据源已拿到 URL，也调 CDP 拿真正最新的
    # 场景2: 其他数据源都没拿到 URL → 用 CDP 兜底（用 identifier 反查 wxid）
    if force_refresh and wxid:
        cdp_result = _query_avatar_via_weflow_cdp(identifier, wxid_hint=wxid, force_refresh=True)
        if cdp_result:
            avatar_url = cdp_result["avatar_url"]
            if cdp_result.get("display_name"):
                display_name = cdp_result["display_name"]
            # alias 保留之前的值（CDP 不返回 alias）
            logger.info(f"force_refresh=True，已通过 CDP 强制刷新 {display_name} ({wxid}) 的头像 URL")
    elif not avatar_url:
        # 兜底：用 identifier 反查 wxid，再调 CDP 强制刷新
        cdp_result = _query_avatar_via_weflow_cdp(identifier, wxid_hint=wxid, force_refresh=True)
        if cdp_result:
            avatar_url = cdp_result["avatar_url"]
            wxid = cdp_result["wxid"]
            display_name = cdp_result["display_name"] or identifier
            logger.info(f"CDP 兜底命中: {display_name} ({wxid})")

    if not avatar_url:
        logger.warning(f"未找到联系人 {identifier} 的头像 URL")
        return None

    # 2. 检查本地缓存 + URL 变化检测
    # 注意：用 alias（而不是 display_name）作为 identifier 查找缓存
    cached = _find_cached_avatar(alias, wxid)
    if cached and not force_refresh:
        if not check_update:
            # 不检查更新，直接返回缓存
            logger.info(f"头像已缓存（跳过更新检查）: {cached.name}")
            return str(cached)

        # URL 变化检测：比较当前 URL 与元数据中记录的 URL
        if wxid and not _check_avatar_changed(wxid, avatar_url):
            logger.info(f"头像未变化（URL 一致）: {cached.name}")
            return str(cached)

        logger.info(f"头像 URL 已变化，重新下载: {display_name} (alias={alias or 'N/A'})")

    # 3. 如果是代理 URL 且没有 CDN URL，直接尝试下载代理 URL
    if avatar_url and _is_proxy_url(avatar_url):
        save_path = _avatar_local_path(alias or display_name, wxid)
        if _download_avatar(avatar_url, save_path):
            size_kb = save_path.stat().st_size // 1024
            logger.info(f"头像保存成功（代理）: {save_path.name} ({size_kb} KB)")
            if wxid:
                _update_avatar_meta(wxid, display_name, avatar_url, save_path)
            return str(save_path)
        logger.warning(f"代理 URL 下载失败: {display_name}")
        return None

    # 4. 下载头像（CDN URL 或 data URL）
    save_path = _avatar_local_path(alias or display_name, wxid)
    logger.info(f"下载头像: {display_name} (alias={alias or 'N/A'}) -> {save_path.name}")

    if _download_avatar(avatar_url, save_path):
        size_kb = save_path.stat().st_size // 1024
        logger.info(f"头像保存成功: {save_path.name} ({size_kb} KB)")
        # 更新元数据
        if wxid:
            _update_avatar_meta(wxid, display_name, avatar_url, save_path)
        return str(save_path)

    logger.warning(f"头像下载失败: {display_name}")
    return None


def get_avatar_url(
    identifier: str,
    *,
    config: Config | None = None,
) -> str | None:
    """根据名称或标识符获取联系人头像 URL（不下载）。

    查询顺序：本地 DB → WeFlow API → contacts.json 缓存

    Args:
        identifier: 联系人名称或标识符
        config: 全局配置（None 时自动加载）

    Returns:
        头像 CDN URL，失败返回 None
    """
    if config is None:
        config = load_config()

    # 1. 查询本地 DB
    conn = get_db(config.db_path)
    try:
        local_result = _query_local_avatar(conn, identifier)
    finally:
        conn.close()

    if local_result:
        url = local_result["avatar_url"]
        # 优先返回 CDN URL；代理 URL 也返回（调用方自行判断是否可用）
        return url

    # 2. API 查询
    client = _create_client(config)
    if client.health():
        api_result = _query_api_avatar(client, identifier)
        if api_result:
            return api_result["avatar_url"]

    # 3. contacts.json 缓存兜底
    cache_result = _query_weflow_cache(identifier)
    if cache_result:
        return cache_result["avatar_url"]

    return None


def batch_download_avatars(
    *,
    config: Config | None = None,
    force_refresh: bool = False,
    limit: int = 10000,
) -> dict:
    """批量下载所有联系人头像。

    数据源优先级：
    1. WeFlow/WCD API（如果服务运行中）
    2. WeFlow contacts.json 缓存（CDN 直链，不需要服务运行）

    Args:
        config: 全局配置（None 时自动加载）
        force_refresh: 为 True 时强制重新下载所有头像
        limit: 联系人数量上限

    Returns:
        {"total": ..., "downloaded": ..., "skipped": ..., "failed": ..., "no_url": ..., "source": ...}
    """
    if config is None:
        config = load_config()

    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # 跳过群聊和系统账号
    skip_keywords = ("@chatroom", "filehelper", "exmail_tool", "openim", "gh_")

    total = 0
    downloaded = 0
    skipped = 0
    failed = 0
    no_url = 0
    source = "none"

    # 尝试 API 拉取
    contacts = None
    client = _create_client(config)
    if client.health():
        try:
            contacts = client.list_contacts(limit=limit)
            source = "api"
        except Exception as e:
            logger.warning(f"API 拉取联系人列表失败: {e}")

    # API 不可用时，用 contacts.json 缓存
    if not contacts:
        cache = _load_weflow_cache()
        if cache:
            contacts = []
            for wxid, info in cache.items():
                contacts.append({
                    "username": wxid,
                    "displayName": info.get("displayName", ""),
                    "alias": info.get("alias", "") or "",
                    "avatarUrl": info.get("avatarUrl", ""),
                })
            source = "contacts.json"
            logger.info(f"使用 contacts.json 缓存: {len(contacts)} 个联系人")

    if not contacts:
        logger.warning("无可用数据源（API 和 contacts.json 均不可用）")
        return {"error": "无可用数据源", "total": 0, "downloaded": 0, "source": "none"}

    for c in contacts:
        wxid = c.get("username", c.get("id", ""))
        if any(kw in wxid for kw in skip_keywords):
            skipped += 1
            continue

        total += 1
        display_name = c.get("displayName", "") or wxid
        alias = c.get("alias", "") or ""
        avatar_url = c.get("avatarUrl", "")

        if not avatar_url:
            no_url += 1
            continue

        # 主文件用 wxid 命名
        save_path = _avatar_local_path(alias or display_name, wxid)

        if not force_refresh and save_path.exists():
            skipped += 1
            continue

        if _download_avatar(avatar_url, save_path):
            downloaded += 1
        else:
            failed += 1

    result = {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "no_url": no_url,
        "source": source,
        "avatars_dir": str(AVATARS_DIR),
    }
    logger.info(
        f"批量下载完成 [{source}]: 总计 {total}, 下载 {downloaded}, "
        f"跳过 {skipped}, 失败 {failed}, 无URL {no_url}"
    )
    return result


def list_local_avatars() -> list[dict]:
    """列出本地已缓存的头像文件。

    Returns:
        [{"filename": ..., "path": ..., "size_kb": ...}, ...]
    """
    if not AVATARS_DIR.exists():
        return []

    result = []
    for f in sorted(AVATARS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            result.append({
                "filename": f.name,
                "path": str(f),
                "size_kb": f.stat().st_size // 1024,
            })
    return result


def get_avatar_with_meta(
    name: str,
    force_refresh: bool = False,
    check_update: bool = True,
) -> dict:
    """获取联系人头像并返回完整元信息（MCP 工具 person_avatar 的业务实现）。

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
    import os as _os
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
    if not _os.path.exists(avatar_path):
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

    size_kb = _os.path.getsize(avatar_path) // 1024
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


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m engine.wechat_data.avatar_fetcher <联系人名称>  # 获取单个头像")
        print("  python -m engine.wechat_data.avatar_fetcher --batch      # 批量下载所有头像")
        print("  python -m engine.wechat_data.avatar_fetcher --list       # 列出本地缓存")
        sys.exit(0)

    if sys.argv[1] == "--batch":
        result = batch_download_avatars()
        print(f"\n批量下载结果: {result}")
    elif sys.argv[1] == "--list":
        avatars = list_local_avatars()
        print(f"\n本地缓存头像 ({len(avatars)} 个):")
        for a in avatars:
            print(f"  {a['filename']:<40} {a['size_kb']} KB")
    else:
        name = sys.argv[1]
        path = get_avatar(name)
        if path:
            print(f"\n头像路径: {path}")
        else:
            print(f"\n未找到 {name} 的头像")
