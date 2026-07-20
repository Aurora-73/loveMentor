"""WeFlow CDP（Chrome DevTools Protocol）基础设施。

提供 CDP 底层通信能力，供上层业务模块调用：
  - WebSocket 握手与帧收发（纯 Python 标准库实现，无新依赖）
  - Runtime.evaluate 封装
  - 头像缓存清理（通过 CDP 调用 WeFlow IPC）

设计要点：
  - 每次调用都是独立的 WebSocket 连接（无状态，便于外部并发调用）
  - 自动检测 CDP 是否开启
  - 错误信息包含 CDP 状态、WeFlow 构建提示等诊断信息

迁移自 mcp_server/tools_read.py L526-L924，让 tools_read.py 成为薄包装。
"""
import base64
import json
import os
import socket
import struct
import urllib.parse
import urllib.request


# WeFlow CDP 端口（固定为 9222，用于不重启清缓存）
WEFLOW_CDP_PORT = 9222


def _check_cdp_enabled(port: int = WEFLOW_CDP_PORT) -> tuple[bool, dict]:
    """检查 WeFlow 是否开启了 CDP（Chrome DevTools Protocol）端口。

    用于不重启 WeFlow 清缓存的方案：
    通过 CDP 调用 ipcRenderer.invoke('cache:clearAll') 清头像缓存。

    Args:
        port: CDP 端口号，默认 9222

    Returns:
        tuple (enabled: bool, info: dict)
        - enabled: CDP 是否可用
        - info: 包含 Browser/Protocol-Version 等信息（enabled=True 时）或错误信息
    """
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                return False, {"error": f"HTTP {resp.status}"}
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return False, {"error": "invalid JSON"}
            if "Browser" in data or "webSocketDebuggerUrl" in data:
                return True, data
            return False, {"error": "not CDP response", "body": body[:200]}
    except Exception as e:
        return False, {"error": str(e)}


# ── CDP WebSocket 客户端（纯 Python 标准库实现，无新依赖） ──


def _cdp_ws_call(ws_url: str, method: str, params: dict | None = None,
                 timeout: float = 10.0) -> dict:
    """通过 WebSocket 调用 CDP 命令（纯 Python 标准库实现）。

    Args:
        ws_url: ws://127.0.0.1:9222/... 格式的 WebSocket URL
        method: CDP 方法名，如 "Runtime.evaluate"
        params: 方法参数 dict
        timeout: 超时秒数

    Returns:
        dict: CDP 响应的 result 字段

    Raises:
        RuntimeError: 握手失败 / 连接关闭 / CDP 返回 error
    """
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)

        # 1. WebSocket 握手
        ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(handshake.encode("ascii"))

        # 读取握手响应
        resp_buf = b""
        while b"\r\n\r\n" not in resp_buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP handshake closed before completion")
            resp_buf += chunk

        status_line = resp_buf.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise RuntimeError(f"CDP handshake failed: {status_line.decode('ascii', errors='replace')}")

        # 多读的字节作为后续帧的 buffer
        leftover = resp_buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in resp_buf else b""

        # 2. 发送 CDP 命令
        # 注意：CDP 协议要求 id 为数字（Chrome 实测字符串 id 会无响应）
        # 每次调用都是新连接，固定用 1 不会冲突
        msg_id = 1
        cmd_payload = json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        _cdp_ws_send_frame(sock, cmd_payload, opcode=0x1)  # text frame

        # 3. 接收响应（最多等 timeout 秒）
        buffer = bytearray(leftover)
        import time
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise RuntimeError(f"CDP response timeout after {timeout}s")
            payload, buffer = _cdp_ws_recv_frame(sock, buffer)
            if payload is None:
                continue  # ping/pong/fragment header

            try:
                msg = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            if msg.get("id") != msg_id:
                continue  # 其他 id 的消息（如事件通知），跳过

            if "error" in msg:
                raise RuntimeError(f"CDP error: {msg['error']}")
            return msg.get("result", {})
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _cdp_ws_send_frame(sock, payload: bytes, opcode: int = 0x1):
    """发送 WebSocket frame（masked，客户端必须 mask）。"""
    mask_key = os.urandom(4)

    first_byte = 0x80 | opcode  # FIN=1
    payload_len = len(payload)

    if payload_len < 126:
        header = struct.pack("!BB", first_byte, 0x80 | payload_len)
    elif payload_len < 65536:
        header = struct.pack("!BBH", first_byte, 0x80 | 126, payload_len)
    else:
        header = struct.pack("!BBQ", first_byte, 0x80 | 127, payload_len)

    masked = bytearray(payload_len)
    for i in range(payload_len):
        masked[i] = payload[i] ^ mask_key[i % 4]

    sock.sendall(header + mask_key + bytes(masked))


def _cdp_ws_recv_frame(sock, buffer: bytearray) -> tuple[bytes | None, bytearray]:
    """接收 WebSocket frame。返回 (payload, new_buffer)。

    payload 为 None 表示非数据帧（ping/pong/close）或分片延续帧（暂不支持）。
    """
    # 至少 2 字节
    while len(buffer) < 2:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("CDP connection closed")
        buffer += chunk

    first_byte = buffer[0]
    second_byte = buffer[1]

    opcode = first_byte & 0x0F
    masked = (second_byte & 0x80) != 0
    payload_len = second_byte & 0x7F

    offset = 2

    if payload_len == 126:
        while len(buffer) < offset + 2:
            buffer += sock.recv(4096)
        payload_len = struct.unpack("!H", buffer[offset:offset + 2])[0]
        offset += 2
    elif payload_len == 127:
        while len(buffer) < offset + 8:
            buffer += sock.recv(4096)
        payload_len = struct.unpack("!Q", buffer[offset:offset + 8])[0]
        offset += 8

    mask_key = b""
    if masked:
        while len(buffer) < offset + 4:
            buffer += sock.recv(4096)
        mask_key = bytes(buffer[offset:offset + 4])
        offset += 4

    # 读取 payload
    while len(buffer) < offset + payload_len:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("CDP connection closed")
        buffer += chunk

    payload = bytes(buffer[offset:offset + payload_len])
    new_buffer = bytearray(buffer[offset + payload_len:])

    if masked:
        payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(len(payload)))

    # 控制帧处理
    if opcode == 0x9:  # ping -> 自动回 pong
        _cdp_ws_send_frame(sock, payload, opcode=0xA)
        return None, new_buffer
    elif opcode == 0xA:  # pong
        return None, new_buffer
    elif opcode == 0x8:  # close
        return None, new_buffer
    elif opcode == 0x0:  # continuation（暂不支持分片）
        return None, new_buffer

    return payload, new_buffer


def _cdp_runtime_evaluate(ws_url: str, expression: str,
                          await_promise: bool = True,
                          timeout: float = 15.0) -> dict:
    """通过 CDP Runtime.evaluate 执行 JavaScript 表达式。

    Args:
        ws_url: WebSocket 调试 URL
        expression: JavaScript 表达式（如果是 Promise，需设 await_promise=True）
        await_promise: 是否等待 Promise 完成
        timeout: 超时秒数

    Returns:
        dict: 包含 success/value/error 字段
    """
    try:
        result = _cdp_ws_call(
            ws_url,
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        # result 结构：{"result": {"type": ..., "value": ..., "subtype": ...}}
        inner = result.get("result", {})
        if inner.get("subtype") == "error" or "exceptionDetails" in result:
            exception = result.get("exceptionDetails", {})
            return {
                "success": False,
                "error": "JavaScript exception",
                "details": exception,
            }
        return {
            "success": True,
            "value": inner.get("value"),
            "type": inner.get("type"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _refresh_weflow_avatar_cache_via_cdp() -> dict:
    """通过 CDP 调用 WeFlow 的 cache:clearAvatarCache IPC，清头像缓存（不重启 WeFlow）。

    前置条件：
      - WeFlow 以 --remote-debugging-port=9222 启动（CDP 已开启）
      - WeFlow 源码已修改并重新构建（包含 cache:clearAvatarCache IPC handler）

    清理范围：
      L2: chatService.avatarCache（主进程内存）
      L3: contactCacheService -> contacts.json（持久化）
      L4: avatarFileCacheService PNG 文件 LRU
    不清 L1（wcdbCore.avatarUrlCache worker 内存），等 10 分钟 TTL 自动失效。

    什么时候用：wechat_send 获取头像前调用，确保拿到最新头像。
    返回什么：dict 含 success/message/cdp_used/eval_result 字段。
    边界是什么：仅清头像缓存，不关闭 DB，不清消息/emoji。
    """
    # 1. 检查 CDP 是否开启
    cdp_enabled, cdp_info = _check_cdp_enabled()
    if not cdp_enabled:
        return {
            "success": False,
            "message": f"WeFlow CDP 未开启（端口 {WEFLOW_CDP_PORT}），无法通过 CDP 清缓存",
            "cdp_used": False,
            "eval_result": None,
            "cdp_error": cdp_info.get("error", "unknown"),
            "suggestion": (
                f"调 weflow_start 自动开启 CDP（端口 {WEFLOW_CDP_PORT}）后重试，"
                f"或手动用 WeFlow.exe --remote-debugging-port=9222 启动"
            ),
        }

    # 2. 获取 WeFlow renderer 页面列表
    try:
        url = f"http://127.0.0.1:{WEFLOW_CDP_PORT}/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            pages = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {
            "success": False,
            "message": f"获取 CDP 页面列表失败: {e}",
            "cdp_used": False,
            "eval_result": None,
        }

    # 3. 找一个 type=page 的页面（WeFlow 主窗口）
    target_page = None
    for page in pages:
        if page.get("type") == "page":
            target_page = page
            break

    if not target_page:
        return {
            "success": False,
            "message": f"CDP 未找到 type=page 的页面（pages={len(pages)}）",
            "cdp_used": False,
            "eval_result": None,
            "pages": [{"type": p.get("type"), "url": p.get("url", "")[:100]} for p in pages],
        }

    ws_url = target_page.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "success": False,
            "message": "CDP 页面缺少 webSocketDebuggerUrl",
            "cdp_used": False,
            "eval_result": None,
        }

    # 4. 通过 CDP Runtime.evaluate 调用 window.electronAPI.cache.clearAvatarCache()
    #    先检查 API 是否存在（WeFlow 是否已重新构建包含新 IPC）
    js_expr = (
        "(function() {"
        "  if (!window.electronAPI || !window.electronAPI.cache "
        "      || typeof window.electronAPI.cache.clearAvatarCache !== 'function') {"
        "    return { success: false, error: 'clearAvatarCache API not available', "
        "             hint: 'WeFlow 需重新构建以包含 cache:clearAvatarCache IPC' };"
        "  }"
        "  return window.electronAPI.cache.clearAvatarCache().then(function(r) {"
        "    return { success: true, raw: r };"
        "  }).catch(function(e) {"
        "    return { success: false, error: String(e) };"
        "  });"
        "})()"
    )

    eval_result = _cdp_runtime_evaluate(ws_url, js_expr, await_promise=True, timeout=15.0)

    if not eval_result.get("success"):
        return {
            "success": False,
            "message": f"CDP Runtime.evaluate 失败: {eval_result.get('error', 'unknown')}",
            "cdp_used": True,
            "eval_result": eval_result,
            "ws_url": ws_url,
        }

    inner_value = eval_result.get("value") or {}
    if not inner_value.get("success"):
        return {
            "success": False,
            "message": f"WeFlow clearAvatarCache 调用失败: {inner_value.get('error', 'unknown')}",
            "cdp_used": True,
            "eval_result": eval_result,
            "ws_url": ws_url,
            "hint": inner_value.get("hint", ""),
        }

    return {
        "success": True,
        "message": "已通过 CDP 调用 clearAvatarCache 清头像缓存（L2/L3/L4）",
        "cdp_used": True,
        "eval_result": eval_result,
        "ws_url": ws_url,
        "raw": inner_value.get("raw"),
    }
