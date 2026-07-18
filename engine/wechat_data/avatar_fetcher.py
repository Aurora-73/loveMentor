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
    """在本地缓存中查找头像，支持多种命名和格式（.jpg 优先，.png 兼容）。

    查找顺序：wxid.jpg → identifier.jpg → wxid.png → identifier.png → 模糊匹配
    """
    # 优先查找 .jpg 格式（wechat_send 需要）
    if wxid:
        for ext in (_AVATAR_EXT, ".png"):
            p = AVATARS_DIR / f"{_safe_filename(wxid)}{ext}"
            if p.exists():
                return p

    # 按 identifier 查找
    if identifier:
        for ext in (_AVATAR_EXT, ".png"):
            p = AVATARS_DIR / f"{_safe_filename(identifier)}{ext}"
            if p.exists():
                return p

    # 模糊匹配（identifier 可能是 displayName，缓存文件可能是旧格式）
    if identifier:
        safe = _safe_filename(identifier)
        for f in AVATARS_DIR.iterdir():
            if f.suffix.lower() in (".jpg", ".png") and safe in f.stem:
                return f

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


def _create_display_name_copy(wxid_path: Path, display_name: str, wxid: str) -> Path | None:
    """创建按 display_name 命名的头像副本（供 wechat_send 模板匹配使用）。

    wechat_send 需要 data/avatars/<name>.jpg，而主文件按 wxid 命名。
    此函数创建 display_name.jpg 副本。

    Returns:
        副本路径，失败返回 None
    """
    if not wxid_path.exists() or not display_name or display_name == wxid:
        return None

    # 如果 display_name 和 wxid 相同，不需要副本
    safe_name = _safe_filename(display_name)
    if safe_name == _safe_filename(wxid):
        return None

    copy_path = AVATARS_DIR / f"{safe_name}{_AVATAR_EXT}"

    # 如果副本已存在且与源文件相同，跳过
    if copy_path.exists():
        if copy_path.stat().st_size == wxid_path.stat().st_size:
            return copy_path

    try:
        import shutil
        shutil.copy2(wxid_path, copy_path)
        return copy_path
    except Exception as e:
        logger.warning(f"创建 display_name 副本失败: {e}")
        return None


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
    """从本地 core.db 查询联系人头像 URL。

    匹配顺序：display_name > remark > nickname > alias > id(wxid)

    Returns:
        {"wxid": ..., "display_name": ..., "avatar_url": ...} 或 None
    """
    # 先精确匹配
    for field in ("display_name", "remark", "nickname", "alias", "id"):
        row = conn.execute(
            f"SELECT id, display_name, avatar_url FROM contacts "
            f"WHERE {field} = ? AND avatar_url IS NOT NULL AND avatar_url != ''",
            (identifier,),
        ).fetchone()
        if row:
            return {"wxid": row["id"], "display_name": row["display_name"], "avatar_url": row["avatar_url"]}

    # 模糊匹配（LIKE）
    for field in ("display_name", "remark", "nickname", "alias"):
        row = conn.execute(
            f"SELECT id, display_name, avatar_url FROM contacts "
            f"WHERE {field} LIKE ? AND avatar_url IS NOT NULL AND avatar_url != ''",
            (f"%{identifier}%",),
        ).fetchone()
        if row:
            return {"wxid": row["id"], "display_name": row["display_name"], "avatar_url": row["avatar_url"]}

    return None


# ── API 查询 ──────────────────────────────────────────────────────────

def _query_api_avatar(client, keyword: str) -> dict | None:
    """通过 WeFlow/WCD API 按关键词搜索联系人头像。

    Returns:
        {"wxid": ..., "display_name": ..., "avatar_url": ...} 或 None
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
                    "avatar_url": c.get("avatarUrl", ""),
                }

    # 如果只有一个结果，直接用
    if len(contacts) == 1:
        c = contacts[0]
        return {
            "wxid": c.get("username", ""),
            "display_name": c.get("displayName", ""),
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


def _query_weflow_cache(identifier: str) -> dict | None:
    """从 WeFlow contacts.json 缓存中查找联系人头像（CDN 直链）。

    优先返回 CDN URL，跳过本地代理 URL。

    Returns:
        {"wxid": ..., "display_name": ..., "avatar_url": ...} 或 None
    """
    cache = _load_weflow_cache()
    if not cache:
        return None

    # 精确匹配
    for wxid, info in cache.items():
        display_name = info.get("displayName", "")
        if identifier in (wxid, display_name, info.get("remark", ""), info.get("nickname", "")):
            url = info.get("avatarUrl", "")
            if url:
                return {"wxid": wxid, "display_name": display_name, "avatar_url": url}

    # 模糊匹配
    for wxid, info in cache.items():
        display_name = info.get("displayName", "")
        if display_name and identifier in display_name:
            url = info.get("avatarUrl", "")
            if url:
                return {"wxid": wxid, "display_name": display_name, "avatar_url": url}

    return None


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
        logger.info(f"本地 DB 命中: {display_name} ({wxid})")

        # 如果 DB 中的 URL 是代理 URL，尝试用 contacts.json 获取 CDN URL
        if avatar_url and _is_proxy_url(avatar_url):
            cache_result = _query_weflow_cache(wxid) or _query_weflow_cache(display_name)
            if cache_result and _is_cdn_url(cache_result["avatar_url"]):
                avatar_url = cache_result["avatar_url"]
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
                logger.info(f"API 命中: {display_name} ({wxid})")
        else:
            logger.info(f"WeFlow API 不可用: {config.weflow.base_url}，尝试 contacts.json 缓存...")

    # 1c. WeFlow contacts.json 缓存兜底
    if not avatar_url:
        cache_result = _query_weflow_cache(identifier)
        if cache_result:
            avatar_url = cache_result["avatar_url"]
            wxid = cache_result["wxid"]
            display_name = cache_result["display_name"] or identifier
            logger.info(f"contacts.json 命中: {display_name} ({wxid})")

    if not avatar_url:
        logger.warning(f"未找到联系人 {identifier} 的头像 URL")
        return None

    # 2. 检查本地缓存 + URL 变化检测
    cached = _find_cached_avatar(display_name, wxid)
    if cached and not force_refresh:
        if not check_update:
            # 不检查更新，直接返回缓存
            logger.info(f"头像已缓存（跳过更新检查）: {cached.name}")
            return str(cached)

        # URL 变化检测：比较当前 URL 与元数据中记录的 URL
        if wxid and not _check_avatar_changed(wxid, avatar_url):
            logger.info(f"头像未变化（URL 一致）: {cached.name}")
            return str(cached)

        logger.info(f"头像 URL 已变化，重新下载: {display_name}")

    # 3. 如果是代理 URL 且没有 CDN URL，直接尝试下载代理 URL
    if avatar_url and _is_proxy_url(avatar_url):
        save_path = _avatar_local_path(display_name, wxid)
        if _download_avatar(avatar_url, save_path):
            size_kb = save_path.stat().st_size // 1024
            logger.info(f"头像保存成功（代理）: {save_path.name} ({size_kb} KB)")
            if wxid:
                _update_avatar_meta(wxid, display_name, avatar_url, save_path)
            # 创建按 display_name 命名的副本（供 wechat_send 使用）
            if display_name and display_name != wxid:
                _create_display_name_copy(save_path, display_name, wxid)
            return str(save_path)
        logger.warning(f"代理 URL 下载失败: {display_name}")
        return None

    # 4. 下载头像（CDN URL 或 data URL）
    save_path = _avatar_local_path(display_name, wxid)
    logger.info(f"下载头像: {display_name} -> {save_path.name}")

    if _download_avatar(avatar_url, save_path):
        size_kb = save_path.stat().st_size // 1024
        logger.info(f"头像保存成功: {save_path.name} ({size_kb} KB)")
        # 更新元数据
        if wxid:
            _update_avatar_meta(wxid, display_name, avatar_url, save_path)
        # 创建按 display_name 命名的副本（供 wechat_send 使用）
        if display_name and display_name != wxid:
            _create_display_name_copy(save_path, display_name, wxid)
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
        avatar_url = c.get("avatarUrl", "")

        if not avatar_url:
            no_url += 1
            continue

        save_path = _avatar_local_path(display_name, wxid)

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
