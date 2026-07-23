"""WeFlow CDP 调用封装。

通过 Chrome DevTools Protocol (CDP) 调用 WeFlow 暴露的 electronAPI，
实现对 WeFlow 内部状态的查询和操作（不重启 WeFlow）。

前置条件：
  - WeFlow 以 --remote-debugging-port=9222 启动（CDP 已开启）
  - WeFlow 源码已修改并重新构建（包含新增的 6 个 IPC handler）

封装的接口（对应 WeFlow preload.ts 暴露的 API）：
  1. cache.refreshContactAvatar(wxid)         — 强制刷新单个联系人头像 URL
  2. cache.refreshAvatarsBatch(wxids)         — 批量刷新多个联系人头像 URL
  3. cache.repairContactsJson()               — 修复被破坏的 contacts.json
  4. cache.getAvatarFile(wxid)                — 获取头像 PNG 文件路径（WeFlow 内部下载）
  5. contact.getDetail(wxid)                  — 按 wxid 查询联系人完整信息
  6. contact.search(keyword, limit)           — 按关键词搜索联系人

设计要点：
  - 复用 tools_read.py 中的 _check_cdp_enabled / _cdp_runtime_evaluate
  - 每次调用都是独立的 WebSocket 连接（无状态，便于外部并发调用）
  - 自动检测 CDP 是否开启、自动查找 type=page 的 WeFlow 主窗口
  - 错误信息包含 CDP 状态、WeFlow 构建提示等诊断信息

用法：
    from mcp_server.weflow_cdp import refresh_contact_avatar
    result = refresh_contact_avatar("wxid_test_example")
    if result["success"]:
        print(result["avatarUrl"], result["displayName"])
"""
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# 复用 engine.importers.weflow_cdp 的 CDP 基础设施
# （迁移自 tools_read.py，让 tools_read.py 成为薄包装）
from engine.importers.weflow_cdp import (
    WEFLOW_CDP_PORT,
    _check_cdp_enabled,
    _cdp_runtime_evaluate,
)


# ── 内部工具 ────────────────────────────────────────────────────

def _get_weflow_page_ws_url() -> tuple[str | None, dict]:
    """获取 WeFlow 主窗口（type=page）的 WebSocket 调试 URL。

    Returns:
        tuple (ws_url, info)
        - ws_url: WebSocket URL，失败时为 None
        - info: 诊断信息（成功时含 pages 数量，失败时含错误）
    """
    try:
        url = f"http://127.0.0.1:{WEFLOW_CDP_PORT}/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            pages = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None, {"error": f"获取 CDP 页面列表失败: {e}"}

    for page in pages:
        if page.get("type") == "page":
            ws_url = page.get("webSocketDebuggerUrl")
            if ws_url:
                return ws_url, {"pages_count": len(pages), "page_url": page.get("url", "")[:100]}

    return None, {
        "error": f"CDP 未找到 type=page 的页面",
        "pages_count": len(pages),
        "pages": [{"type": p.get("type"), "url": p.get("url", "")[:100]} for p in pages],
    }


def _call_weflow_api(api_expr: str, timeout: float = 30.0) -> dict:
    """通过 CDP Runtime.evaluate 调用 WeFlow 的 electronAPI。

    Args:
        api_expr: JavaScript 表达式（应返回 Promise，最终 resolve 为 dict）
                  例如：`window.electronAPI.cache.refreshContactAvatar("wxid_xxx")`
        timeout: 超时秒数（默认 30 秒，批量操作可能需要更长）

    Returns:
        dict: WeFlow API 返回的结果（success/avatarUrl/displayName/error 等字段）
              如果 CDP 调用本身失败，返回 {"success": False, "error": ..., "cdp_used": False}
    """
    # 1. 检查 CDP 是否开启
    cdp_enabled, cdp_info = _check_cdp_enabled()
    if not cdp_enabled:
        return {
            "success": False,
            "error": f"WeFlow CDP 未开启（端口 {WEFLOW_CDP_PORT}）",
            "cdp_used": False,
            "cdp_error": cdp_info.get("error", "unknown"),
            "suggestion": (
                f"调 weflow_start 自动开启 CDP（端口 {WEFLOW_CDP_PORT}）后重试，"
                f"或手动用 WeFlow.exe --remote-debugging-port=9222 启动"
            ),
        }

    # 2. 获取 WeFlow 主窗口 ws_url
    ws_url, page_info = _get_weflow_page_ws_url()
    if not ws_url:
        return {
            "success": False,
            "error": page_info.get("error", "未找到 WeFlow 页面"),
            "cdp_used": False,
            "pages_info": page_info,
        }

    # 3. 包装 JS 表达式（统一处理 API 不存在/异常/Promise reject）
    wrapped = (
        "(function() {"
        "  try {"
        f"    var promise = {api_expr};"
        "    if (!promise || typeof promise.then !== 'function') {"
        "      return { success: false, error: 'API 返回值不是 Promise', raw: String(promise) };"
        "    }"
        "    return promise.then(function(r) {"
        "      return { success: true, raw: r };"
        "    }).catch(function(e) {"
        "      return { success: false, error: String(e) };"
        "    });"
        "  } catch (e) {"
        "    return { success: false, error: 'JS exception: ' + String(e) };"
        "  }"
        "})()"
    )

    eval_result = _cdp_runtime_evaluate(ws_url, wrapped, await_promise=True, timeout=timeout)

    if not eval_result.get("success"):
        return {
            "success": False,
            "error": f"CDP Runtime.evaluate 失败: {eval_result.get('error', 'unknown')}",
            "cdp_used": True,
            "eval_result": eval_result,
            "ws_url": ws_url,
        }

    inner_value = eval_result.get("value") or {}
    if not inner_value.get("success"):
        # API 调用本身失败（API 不存在/异常/Promise reject）
        return {
            "success": False,
            "error": inner_value.get("error", "WeFlow API 调用失败"),
            "cdp_used": True,
            "ws_url": ws_url,
            "hint": (
                "若提示 API 不存在，请确认 WeFlow 已重新构建包含新 IPC"
                "（cache:refreshContactAvatar / cache:refreshAvatarsBatch / "
                "cache:repairContactsJson / cache:getAvatarFile / "
                "contact:getDetail / contact:search）"
            ),
        }

    # 4. 成功：返回 WeFlow API 的原始结果
    raw = inner_value.get("raw") or {}
    if isinstance(raw, dict):
        # 透传 WeFlow 返回的所有字段（success/avatarUrl/displayName/contact/contacts 等）
        return {**raw, "cdp_used": True}
    # raw 不是 dict（异常情况）
    return {
        "success": True,
        "cdp_used": True,
        "raw": raw,
        "ws_url": ws_url,
        "warning": "WeFlow API 返回值不是 dict",
    }


# ── 公开 API（6 个接口） ────────────────────────────────────────

def refresh_contact_avatar(wxid: str, timeout: float = 30.0) -> dict:
    """强制刷新单个联系人的头像 URL（绕过 L1/L2 TTL 缓存）。

    流程：
      1. 清除 WeFlow L2 (chatService.avatarCache) 中该 wxid 的条目
      2. 清除 WeFlow L1 (wcdbCore.avatarUrlCache) 中该 wxid 的条目
      3. 从 wcdb 数据库读取最新 avatarUrl
      4. 增量写回 L2/L3 (contacts.json)，不清空整个 contacts.json
      5. 返回 { avatarUrl, displayName }

    Args:
        wxid: 联系人 wxid（如 wxid_test_example）
        timeout: 超时秒数

    Returns:
        dict: {
            success: bool,
            avatarUrl: str,        # 成功时为最新头像 URL
            displayName: str,      # 成功时为联系人显示名
            error: str,            # 失败时为错误信息
            cdp_used: bool,        # 是否通过 CDP 调用
        }
    """
    if not wxid or not wxid.strip():
        return {"success": False, "error": "wxid 不能为空"}
    # 注意：JS 字符串需要转义双引号和反斜杠
    safe_wxid = wxid.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    js_expr = f'window.electronAPI.cache.refreshContactAvatar("{safe_wxid}")'
    return _call_weflow_api(js_expr, timeout=timeout)


def refresh_avatars_batch(wxids: list[str], timeout: float = 120.0) -> dict:
    """批量强制刷新多个联系人的头像 URL。

    Args:
        wxids: wxid 列表
        timeout: 超时秒数（批量操作默认 120 秒）

    Returns:
        dict: {
            success: bool,
            results: { "<wxid>": { avatarUrl, displayName, error? }, ... },
            error: str,
        }
    """
    if not wxids:
        return {"success": True, "results": {}}
    # 构造 JS 数组字符串
    items_js = ",".join(
        '"' + str(w).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"') + '"'
        for w in wxids if w
    )
    js_expr = f'window.electronAPI.cache.refreshAvatarsBatch([{items_js}])'
    return _call_weflow_api(js_expr, timeout=timeout)


def repair_contacts_json(timeout: float = 120.0) -> dict:
    """修复被破坏的 contacts.json（从 wcdb 重新读取所有联系人重建）。

    用于 contacts.json 被 clearCaches({includeContacts:true}) 误清空后的恢复。

    Returns:
        dict: {
            success: bool,
            repaired: int,    # 修复的联系人数量
            error: str,
        }
    """
    js_expr = 'window.electronAPI.cache.repairContactsJson()'
    return _call_weflow_api(js_expr, timeout=timeout)


def get_avatar_file(wxid: str, timeout: float = 30.0) -> dict:
    """获取联系人头像 PNG 文件路径（WeFlow 内部下载，复用 L4 缓存）。

    比 Python 端 urllib 下载更稳定（WeFlow 内部有正确的 UA/Referer + LRU 缓存）。

    Args:
        wxid: 联系人 wxid

    Returns:
        dict: {
            success: bool,
            localPath: str,    # 本地 PNG 文件路径（WeFlow 进程可访问）
            avatarUrl: str,    # 头像 URL
            error: str,
        }
    """
    if not wxid or not wxid.strip():
        return {"success": False, "error": "wxid 不能为空"}
    safe_wxid = wxid.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    js_expr = f'window.electronAPI.cache.getAvatarFile("{safe_wxid}")'
    return _call_weflow_api(js_expr, timeout=timeout)


def get_contact_detail(wxid: str, timeout: float = 30.0) -> dict:
    """按 wxid 查询联系人完整信息（alias/displayName/remark/avatarUrl）。

    用于 Python 端通过 wxid 反查微信号（alias）和显示名。

    Args:
        wxid: 联系人 wxid

    Returns:
        dict: {
            success: bool,
            contact: {
                username: str,    # wxid
                alias: str,       # 微信号
                displayName: str, # 显示名（remark > nickName > alias > wxid）
                remark: str,      # 备注名
                avatarUrl: str,   # 头像 URL
            },
            error: str,
        }
    """
    if not wxid or not wxid.strip():
        return {"success": False, "error": "wxid 不能为空"}
    safe_wxid = wxid.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    js_expr = f'window.electronAPI.contact.getDetail("{safe_wxid}")'
    return _call_weflow_api(js_expr, timeout=timeout)


def search_contact(keyword: str, limit: int = 20, timeout: float = 30.0) -> dict:
    """按关键词搜索联系人（支持 wxid/alias/displayName/remark/nickname 模糊匹配）。

    用于 Python 端按名称反查 wxid。

    Args:
        keyword: 搜索关键词
        limit: 返回最大数量（默认 20，最大 100）

    Returns:
        dict: {
            success: bool,
            contacts: [
                { username, alias, displayName, remark, avatarUrl },
                ...
            ],
            error: str,
        }
    """
    if not keyword or not keyword.strip():
        return {"success": True, "contacts": []}
    safe_kw = keyword.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    js_expr = (
        f'window.electronAPI.contact.search("{safe_kw}", {int(limit)})'
    )
    return _call_weflow_api(js_expr, timeout=timeout)


# ── 自检 ────────────────────────────────────────────────────────

def self_check() -> dict:
    """自检：检查 CDP 是否可用、WeFlow 是否暴露新 API。

    用法：
        python -X utf8 mcp_server/weflow_cdp.py
    """
    result = {
        "cdp_port": WEFLOW_CDP_PORT,
        "cdp_enabled": False,
        "api_available": False,
        "test_result": None,
    }

    # 1. 检查 CDP 端口
    cdp_enabled, cdp_info = _check_cdp_enabled()
    result["cdp_enabled"] = cdp_enabled
    result["cdp_info"] = cdp_info
    if not cdp_enabled:
        result["error"] = "CDP 未开启"
        return result

    # 2. 检查 refreshContactAvatar API 是否存在
    ws_url, page_info = _get_weflow_page_ws_url()
    if not ws_url:
        result["error"] = page_info.get("error", "未找到 WeFlow 页面")
        result["pages_info"] = page_info
        return result

    result["ws_url"] = ws_url
    result["page_info"] = page_info

    # 用一个简单的 evaluate 测试 API 是否存在
    test_js = (
        "(function() {"
        "  if (!window.electronAPI || !window.electronAPI.cache) return { available: false, reason: 'electronAPI.cache 不存在' };"
        "  var missing = [];"
        "  ['refreshContactAvatar', 'refreshAvatarsBatch', 'repairContactsJson', 'getAvatarFile'].forEach(function(name) {"
        "    if (typeof window.electronAPI.cache[name] !== 'function') missing.push('cache.' + name);"
        "  });"
        "  if (!window.electronAPI.contact) missing.push('contact.*');"
        "  else ['getDetail', 'search'].forEach(function(name) {"
        "    if (typeof window.electronAPI.contact[name] !== 'function') missing.push('contact.' + name);"
        "  });"
        "  return { available: missing.length === 0, missing: missing };"
        "})()"
    )
    eval_result = _cdp_runtime_evaluate(ws_url, test_js, await_promise=False, timeout=5.0)
    result["test_result"] = eval_result
    if eval_result.get("success"):
        value = eval_result.get("value") or {}
        result["api_available"] = value.get("available", False)
        result["missing_apis"] = value.get("missing", [])
    return result


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
