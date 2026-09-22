import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = PROJECT_ROOT / "selected_full.json"
OUTPUT_FILE = PROJECT_ROOT / "selected_full.json"

CORE_SELECTIONS = {
    "【A01】各大情感导师\\A04、林老头": "林老头私教体系(P0)",
    
    "【A05】私密-空间操作课程": "私密空间操作(P1)",
    
    "【A01】各大情感导师\\A06、simon情感": "simon情感升温体系",
    "【A01】各大情感导师\\A06、simon情感\\2、Simon情感升温核心": "关系升温核心",
    "【A01】各大情感导师\\A06、simon情感\\Simon2023课程【升温核心】": "2023升温核心",
    
    "【A01】各大情感导师\\A03、男魅情感魅男": "男魅情感体系",
    "【A01】各大情感导师\\A03、男魅情感魅男\\魅男私教【魅男方法】": "魅男方法",
    "【A01】各大情感导师\\A03、男魅情感魅男\\魅男《撩术》": "撩术课程",
    "【A01】各大情感导师\\A03、男魅情感魅男\\男魅情感教育《魅惑术》-楚王": "魅惑术体系",
    "【A01】各大情感导师\\A03、男魅情感魅男\\讲义": "魅男讲义",
    
    "【A01】各大情感导师\\A01、梵公子\\梵公子·约会加速器": "约会加速器",
    "【A01】各大情感导师\\A01、梵公子\\梵公子外卖方法3.0": "外卖方法",
    "【A01】各大情感导师\\A01、梵公子\\讲义": "梵公子讲义",
    
    "【A01】各大情感导师\\A08、乌鸦课程": "乌鸦课程体系",
    "【A01】各大情感导师\\A08、乌鸦课程\\女性性格分类": "女性性格分类",
    "【A01】各大情感导师\\A08、乌鸦课程\\乌家门火箭班": "乌鸦火箭班",
    "【A01】各大情感导师\\A08、乌鸦课程\\实战技巧": "实战技巧",
    "【A01】各大情感导师\\A08、乌鸦课程\\乌鸦香火传承": "香火传承",
    "【A01】各大情感导师\\A08、乌鸦课程\\乌鸦课程\\强切": "强切技巧",
    "【A01】各大情感导师\\A08、乌鸦课程\\乌鸦课程\\推拉技巧": "推拉技巧",
    
    "【A01】各大情感导师\\A05、嘉琪学长": "嘉琪学长体系",
    "【A01】各大情感导师\\A05、嘉琪学长\\嘉琪新时代聊天黑科技—猎心法则": "猎心法则",
    
    "【A07】几百套聊天案例合集": "聊天案例合集",
    
    "[REDACTED]\\泡妞356本": "泡妞356本书籍",
    "[REDACTED]\\泡妞250本": "泡妞250本书籍",
    
    "[REDACTED]\\泡妞356本\\I 女性": "女性相关书籍",
    "[REDACTED]\\泡妞231本\\I 女性": "女性相关书籍(231)",
    
    "浪迹情感专区": "浪迹情感专区",
}


def main():
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for item in data['selected']:
        item['selected'] = False
        item['priority'] = None
    
    matched = 0
    not_found = []
    
    for rel_path, reason in CORE_SELECTIONS.items():
        full_path = str(PROJECT_ROOT / "docs" / "文档" / rel_path)
        found = False
        for item in data['selected']:
            if item['path'] == full_path:
                item['selected'] = True
                item['priority'] = 1
                matched += 1
                found = True
                break
        if not found:
            not_found.append(full_path)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"匹配成功: {matched} 个")
    print(f"未找到: {len(not_found)} 个")
    
    if not_found:
        print("\n未找到的路径:")
        for path in not_found:
            print(f"  {path}")
    
    print(f"\n已更新 {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
