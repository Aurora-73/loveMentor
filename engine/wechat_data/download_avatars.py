"""从 WeFlow contacts.json 读取联系人头像 URL 并下载保存到 data/avatars/。

WeFlow 运行时会把联系人信息缓存到：
  %APPDATA%/weflow/cache/contacts.json

格式：{ "wxid_xxx": { "displayName": "名字", "avatarUrl": "https://wx.qlogo.cn/...", "updatedAt": 1234567890 } }

头像下载用微信 CDN 特定的 HTTP Headers（参考 WeFlow avatarFileCacheService.ts）。
"""
import json
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error

# WeFlow contacts.json 路径
CONTACTS_JSON = os.path.join(os.environ['APPDATA'], 'weflow', 'cache', 'contacts.json')

# 头像保存目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AVATARS_DIR = os.path.join(PROJECT_ROOT, 'data', 'avatars')

# 微信 CDN 下载 Headers（来自 WeFlow avatarFileCacheService.ts）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090719) XWEB/8351',
    'Referer': 'https://servicewechat.com/',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
}

# 下载超时（秒）
TIMEOUT = 10


def download_avatar(url, save_path):
    """下载头像到指定路径。

    Args:
        url: 头像 URL
        save_path: 保存路径

    Returns:
        bool: 是否成功
    """
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            if response.status == 200:
                data = response.read()
                with open(save_path, 'wb') as f:
                    f.write(data)
                return True
            else:
                print(f"   ❌ HTTP {response.status}")
                return False
    except urllib.error.HTTPError as e:
        print(f"   ❌ HTTPError {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def safe_filename(name):
    """将联系人名转为安全的文件名"""
    # 替换不安全字符
    safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)
    return safe[:50]  # 限制长度


def main():
    # 1. 读取 contacts.json
    print(f"读取 WeFlow contacts.json: {CONTACTS_JSON}")
    if not os.path.exists(CONTACTS_JSON):
        print("❌ contacts.json 不存在，请确保 WeFlow 已运行过")
        sys.exit(1)

    with open(CONTACTS_JSON, 'r', encoding='utf-8') as f:
        contacts = json.load(f)

    contact_count = len(contacts)
    print(f"✅ 共 {contact_count} 个联系人")

    # 2. 创建头像目录
    os.makedirs(AVATARS_DIR, exist_ok=True)
    print(f"头像保存目录: {AVATARS_DIR}")

    # 3. 下载头像
    # 跳过群聊（@chatroom）和系统账号
    skip_keywords = ['@chatroom', 'filehelper', 'exmail_tool', 'openim']

    success_count = 0
    skip_count = 0
    fail_count = 0
    already_exist = 0

    for wxid, info in contacts.items():
        # 跳过群聊和系统账号
        if any(kw in wxid for kw in skip_keywords):
            skip_count += 1
            continue

        display_name = info.get('displayName', '')
        avatar_url = info.get('avatarUrl', '')

        if not avatar_url:
            skip_count += 1
            continue

        # 生成文件名：displayName_wxid.png
        safe_name = safe_filename(display_name) if display_name else wxid
        filename = f"{safe_name}.png"
        save_path = os.path.join(AVATARS_DIR, filename)

        # 如果已存在则跳过
        if os.path.exists(save_path):
            already_exist += 1
            continue

        print(f"\n[{success_count + fail_count + 1}] 下载 {display_name} ({wxid})")
        print(f"   URL: {avatar_url[:80]}...")

        if download_avatar(avatar_url, save_path):
            size = os.path.getsize(save_path)
            print(f"   ✅ 保存: {filename} ({size//1024} KB)")
            success_count += 1
            time.sleep(0.2)  # 避免请求过快
        else:
            fail_count += 1

    # 4. 统计
    print(f"\n{'='*60}")
    print(f"  下载完成")
    print(f"{'='*60}")
    print(f"  总联系人数: {contact_count}")
    print(f"  跳过（群聊/系统/无头像）: {skip_count}")
    print(f"  已存在: {already_exist}")
    print(f"  成功下载: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  头像目录: {AVATARS_DIR}")

    # 列出目录中的头像文件
    avatar_files = [f for f in os.listdir(AVATARS_DIR) if f.endswith('.png')]
    print(f"\n  当前头像文件数: {len(avatar_files)}")


if __name__ == "__main__":
    main()
