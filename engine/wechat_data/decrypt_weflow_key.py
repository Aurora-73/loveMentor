"""解密 WeFlow 配置中的 decryptKey（Electron safeStorage / Windows DPAPI）。

Electron safeStorage 在 Windows 上用 DPAPI 加密：
- 数据格式：base64("djEw" + DPAPI加密数据)
- "djEw" 是 Electron 的版本前缀（v10）
- 解密需要用当前用户的 DPAPI（CryptUnprotectData）

WeFlow config 中 decryptKey 格式：
  safe:djEwlX/0XBc+Akij+gAdpnPHCNw15KcfB2BJi+AViaVL52cwM2LpLBLmnXLLY0w7yaOpIzp2NgOc38tXzSiB3M+StxfYEZZ29dkv5y5Bupl1nb48QrWL+93VUow71hk=

步骤：
1. 去掉 "safe:" 前缀
2. base64 解码
3. 去掉前 4 字节（"djEw" = v10）
4. 用 DPAPI CryptUnprotectData 解密
5. 得到 64 字符 hex key
"""
import ctypes
import ctypes.wintypes as wintypes
import base64
import json
import os

# WeFlow 配置路径
CONFIG_PATH = os.path.join(os.environ['APPDATA'], 'weflow', 'WeFlow-config.json')


def dpapi_decrypt(encrypted_bytes):
    """用 Windows DPAPI (CryptUnprotectData) 解密数据。

    Args:
        encrypted_bytes: DPAPI 加密的字节数据

    Returns:
        bytes: 解密后的数据
    """
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    # 输入
    in_blob = DATA_BLOB(len(encrypted_bytes), ctypes.cast(
        ctypes.c_char_p(encrypted_bytes), ctypes.POINTER(ctypes.c_char)
    ))
    # 输出
    out_blob = DATA_BLOB()

    # 调用 CryptUnprotectData
    crypt32 = ctypes.windll.crypt32
    success = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,  # 描述
        None,  # 可选 entropy
        None,  # 保留
        None,  # 提示
        0,     # flags
        ctypes.byref(out_blob),
    )

    if not success:
        err = ctypes.get_last_error()
        raise OSError(f"CryptUnprotectData 失败，错误码: {err}")

    # 提取解密数据
    decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)

    # 释放内存
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    return decrypted


def decrypt_safestorage(safe_value):
    """解密 Electron safeStorage 加密的值。

    Args:
        safe_value: "safe:djEw..." 格式的字符串

    Returns:
        str: 解密后的明文字符串
    """
    # 去掉 "safe:" 前缀
    if safe_value.startswith('safe:'):
        b64_data = safe_value[5:]
    else:
        b64_data = safe_value

    # base64 解码
    raw_bytes = base64.b64decode(b64_data)

    # 去掉前 4 字节（"v10" 版本标识）
    # Electron safeStorage: "v10" + DPAPI加密数据
    if len(raw_bytes) < 4:
        raise ValueError(f"数据太短: {len(raw_bytes)} bytes")

    prefix = raw_bytes[:4]
    encrypted = raw_bytes[4:]

    print(f"  版本前缀: {prefix} (ascii: {prefix.decode('ascii', errors='ignore')})")
    print(f"  加密数据长度: {len(encrypted)} bytes")

    # DPAPI 解密
    decrypted = dpapi_decrypt(encrypted)
    return decrypted.decode('utf-8')


def main():
    # 1. 读取 WeFlow 配置
    print(f"读取配置: {CONFIG_PATH}")
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 2. 检查是否有 decryptKey
    decrypt_key = config.get('decryptKey', '')
    if not decrypt_key:
        print("❌ 配置中没有 decryptKey")
        return None

    print(f"decryptKey: {decrypt_key[:30]}...")

    # 3. 解密
    print("\n解密中...")
    try:
        key = decrypt_safestorage(decrypt_key)
        print(f"\n✅ 解密成功!")
        print(f"Key: {key}")
        print(f"Key 长度: {len(key)} 字符")
        if len(key) == 64:
            print("✅ Key 长度正确（64字符 hex = 32字节 raw key）")

        # 保存 key 到临时文件
        key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_db_key.tmp")
        with open(key_file, 'w') as f:
            f.write(key)
        print(f"\n已保存到: {key_file}")

        return key
    except Exception as e:
        print(f"❌ 解密失败: {e}")
        return None


if __name__ == "__main__":
    main()
