"""用 wcdb_api.dll 直接读取微信数据库（需要 key）。

WeFlow 的 wcdb_api.dll 封装了 WCDB（SQLCipher）的操作。
key 从 WeFlow config 解密获得（或从 _db_key.tmp 读取）。

流程：
1. 获取 key（从 _db_key.tmp 或 WeFlow config）
2. 找到微信数据库路径
3. 用 wcdb_api.dll 打开数据库
4. 查询 contact 表获取头像 URL
5. 下载头像保存到 data/avatars/
"""
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import json
import time

# DLL 路径
DLL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dll")
WCDB_API_DLL = os.path.join(DLL_DIR, "wcdb_api.dll")
WCDB_DLL = os.path.join(DLL_DIR, "WCDB.dll")

# 微信数据库路径
def find_wechat_db_path():
    """查找微信数据库路径"""
    # 新版微信：xwechat_files
    xwechat_path = os.path.join(os.environ['USERPROFILE'], 'Documents', 'xwechat_files')
    if os.path.exists(xwechat_path):
        for item in os.listdir(xwechat_path):
            account_dir = os.path.join(xwechat_path, item)
            db_storage = os.path.join(account_dir, 'db_storage')
            if os.path.exists(db_storage):
                # 查找 session.db
                for root, dirs, files in os.walk(db_storage):
                    for f in files:
                        if f == 'session.db':
                            return db_storage, account_dir
        # 没有 session.db 但有 db_storage
        for item in os.listdir(xwechat_path):
            account_dir = os.path.join(xwechat_path, item)
            db_storage = os.path.join(account_dir, 'db_storage')
            if os.path.exists(db_storage):
                return db_storage, account_dir

    # 旧版微信：WeChat Files
    wechat_path = os.path.join(os.environ['USERPROFILE'], 'Documents', 'WeChat Files')
    if os.path.exists(wechat_path):
        for item in os.listdir(wechat_path):
            account_dir = os.path.join(wechat_path, item)
            db_path = os.path.join(account_dir, 'db')
            if os.path.exists(db_path):
                return db_path, account_dir

    return None, None


def get_key():
    """获取数据库 key"""
    # 方法1: 从 _db_key.tmp 读取
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_db_key.tmp")
    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            key = f.read().strip()
            if len(key) == 64:
                print(f"✅ 从 _db_key.tmp 读取 key: {key[:16]}...")
                return key

    # 方法2: 从 WeFlow config 解密
    try:
        from decrypt_weflow_key import decrypt_safestorage
        config_path = os.path.join(os.environ['APPDATA'], 'weflow', 'WeFlow-config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        decrypt_key = config.get('decryptKey', '')
        if decrypt_key:
            key = decrypt_safestorage(decrypt_key)
            if key and len(key) == 64:
                print(f"✅ 从 WeFlow config 解密 key: {key[:16]}...")
                # 保存到临时文件
                with open(key_file, 'w') as f:
                    f.write(key)
                return key
    except Exception as e:
        print(f"⚠️ WeFlow config 解密失败: {e}")

    print("❌ 未找到 key")
    print("   请先运行 get_db_key.py（管理员权限）获取 key")
    return None


def main():
    # 1. 获取 key
    key = get_key()
    if not key:
        sys.exit(1)

    # 2. 找数据库路径
    db_path, account_dir = find_wechat_db_path()
    if not db_path:
        print("❌ 未找到微信数据库路径")
        print("   请确保微信已安装并登录过")
        sys.exit(1)

    print(f"\n✅ 微信账号目录: {account_dir}")
    print(f"✅ 数据库目录: {db_path}")

    # 3. 列出数据库文件
    print(f"\n=== 数据库文件 ===")
    if os.path.exists(db_path):
        for root, dirs, files in os.walk(db_path):
            for f in files:
                if f.endswith('.db'):
                    full_path = os.path.join(root, f)
                    size = os.path.getsize(full_path)
                    print(f"  {os.path.relpath(full_path, db_path)} ({size//1024} KB)")


if __name__ == "__main__":
    main()
