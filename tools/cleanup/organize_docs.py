import os
import shutil
import json
import hashlib
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(r"<project_root>\docs\文档")
BACKUP_DIR = BASE_DIR.parent / "_整理备份"
LOG_FILE = BASE_DIR.parent / "整理操作日志.json"
UNDO_FILE = BASE_DIR.parent / "整理撤销日志.json"

MIGRATION_MAP = [
    {
        "source": "【A01】各大情感导师/A04、林老头",
        "target": "导师专区/林老头",
        "type": "folder"
    },
    {
        "source": "1、林老头《lin系统认知方法论》",
        "target": "导师专区/林老头/《lin系统认知方法论》",
        "type": "folder"
    },
    {
        "source": "13、林老头《精华直播案例内部完整版》2023",
        "target": "导师专区/林老头/《精华直播案例内部完整版》2023",
        "type": "folder"
    },
    {
        "source": "浪迹情感",
        "target": "导师专区/浪迹",
        "type": "folder"
    },
    {
        "source": "浪迹汇总",
        "target": "导师专区/浪迹/浪迹汇总",
        "type": "folder"
    },
    {
        "source": "浪迹（5月1日蓉城计划）",
        "target": "导师专区/浪迹/蓉城计划",
        "type": "folder"
    },
    {
        "source": "乐福佬佟《新私教》",
        "target": "导师专区/老佟/《新私教》",
        "type": "folder"
    },
    {
        "source": "乐福老佟《私密空间》",
        "target": "导师专区/老佟/《私密空间》",
        "type": "folder"
    },
    {
        "source": "老佟419《一ye.情缘》",
        "target": "导师专区/老佟/《一ye.情缘》",
        "type": "folder"
    },
    {
        "source": "老佟《短期关系》",
        "target": "导师专区/老佟/《短期关系》",
        "type": "folder"
    },
    {
        "source": "荔枝新老佟私教",
        "target": "导师专区/老佟/荔枝私教",
        "type": "folder"
    },
    {
        "source": "老佟《一次约会追到女神 实战约会方法》",
        "target": "导师专区/老佟/《实战约会方法》",
        "type": "folder"
    },
    {
        "source": "老佟《低成本速推》",
        "target": "导师专区/老佟/《低成本速推》",
        "type": "folder"
    },
    {
        "source": "【A02】RSD国外顶尖合集",
        "target": "导师专区/RSD",
        "type": "folder"
    },
    {
        "source": "RSD德里克-游戏十诫",
        "target": "导师专区/RSD/德里克《游戏十诫》",
        "type": "folder"
    },
    {
        "source": "RSD朱利安《高共振沟通》",
        "target": "导师专区/RSD/朱利安《高共振沟通》",
        "type": "folder"
    },
    {
        "source": "RSD瓦伦蒂诺《隐型游戏》",
        "target": "导师专区/RSD/瓦伦蒂诺《隐型游戏》",
        "type": "folder"
    },
    {
        "source": "前RSD导师托德（言语游戏）",
        "target": "导师专区/RSD/托德《言语游戏》",
        "type": "folder"
    },
    {
        "source": "泰勒基础与高级游戏RSD",
        "target": "导师专区/RSD/泰勒《基础与高级游戏》",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A15、柯李思团队全套课程",
        "target": "导师专区/柯李思",
        "type": "folder"
    },
    {
        "source": "柯李思Chris、良叔专区",
        "target": "导师专区/柯李思/良叔专区",
        "type": "folder"
    },
    {
        "source": "瑞恩RYAN专区",
        "target": "导师专区/瑞恩",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A09、加藤非",
        "target": "导师专区/加藤非",
        "type": "folder"
    },
    {
        "source": "加藤非《肉体TD》",
        "target": "导师专区/加藤非/《肉体TD》",
        "type": "folder"
    },
    {
        "source": "加藤飞大尧《心肾全能速成课》",
        "target": "导师专区/加藤非/大尧《心肾全能速成课》",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A08、乌鸦课程",
        "target": "导师专区/乌鸦",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A01、梵公子",
        "target": "导师专区/梵公子",
        "type": "folder"
    },
    {
        "source": "朱利安《高频沟通》",
        "target": "导师专区/朱利安/《高频沟通》",
        "type": "folder"
    },
    {
        "source": "朱利安ten game",
        "target": "导师专区/朱利安/ten game",
        "type": "folder"
    },
    {
        "source": "朱利安《满分游戏》",
        "target": "导师专区/朱利安/《满分游戏》",
        "type": "folder"
    },
    {
        "source": "【社交光谱】泰勒《最后一搏计划》人工翻译版",
        "target": "导师专区/泰勒/《最后一搏计划》",
        "type": "folder"
    },
    {
        "source": "【社交光谱】泰勒《蓝图解码2.0重铸蓝图》初级班",
        "target": "导师专区/泰勒/《蓝图解码2.0》初级班",
        "type": "folder"
    },
    {
        "source": "【社交光谱】泰勒《蓝图解码2.0重铸蓝图》标准班",
        "target": "导师专区/泰勒/《蓝图解码2.0》标准班",
        "type": "folder"
    },
    {
        "source": "泰勒 高状态沟通【演讲 说服力 营销】",
        "target": "导师专区/泰勒/《高状态沟通》",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A03、男魅情感魅男",
        "target": "导师专区/魅男",
        "type": "folder"
    },
    {
        "source": "魅男+幸福余生情感课",
        "target": "导师专区/魅男/幸福余生情感课",
        "type": "folder"
    },
    {
        "source": "阿龙《夜店高手》",
        "target": "导师专区/阿龙/《夜店高手》",
        "type": "folder"
    },
    {
        "source": "乐涛《速约课》",
        "target": "导师专区/乐涛/《速约课》",
        "type": "folder"
    },
    {
        "source": "情叔叔《入房术》",
        "target": "导师专区/情叔叔/《入房术》",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A02、Leon情感全集无",
        "target": "导师专区/Leon",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A05、嘉琪学长",
        "target": "导师专区/嘉琪学长",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A06、simon情感",
        "target": "导师专区/simon",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A10、新船长私教2.0系统体系",
        "target": "导师专区/新船长",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A11、朕哥情感合集",
        "target": "导师专区/朕哥",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A12、爱情光谱",
        "target": "导师专区/爱情光谱",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A13、抖音校长谈恋爱",
        "target": "导师专区/抖音校长",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A14、飞哥撩妹课程",
        "target": "导师专区/飞哥",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A16、老景《强大心态合集》",
        "target": "导师专区/老景",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A17、郑匡宇全集",
        "target": "导师专区/郑匡宇",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A18、Q帝全系",
        "target": "导师专区/Q帝",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A19、鸭哥",
        "target": "导师专区/鸭哥",
        "type": "folder"
    },
    {
        "source": "【A01】各大情感导师/A《五步陷阱最新最全课程》",
        "target": "导师专区/五步陷阱",
        "type": "folder"
    },
    {
        "source": "【A05】私密-空间操作课程",
        "target": "主题专区/私密空间操作",
        "type": "folder"
    },
    {
        "source": "《如何带妹子去k房》",
        "target": "主题专区/私密空间操作/《如何带妹子去k房》",
        "type": "folder"
    },
    {
        "source": "如何带入房间",
        "target": "主题专区/私密空间操作/如何带入房间",
        "type": "folder"
    },
    {
        "source": "小鹿坏男孩《亲密阶段-私密空间》",
        "target": "主题专区/私密空间操作/小鹿坏男孩《亲密阶段》",
        "type": "folder"
    },
    {
        "source": "2、朋友圈黑科技",
        "target": "主题专区/形象建设/朋友圈黑科技",
        "type": "folder"
    },
    {
        "source": "【A18】朋友圈高逼格照片＋文案",
        "target": "主题专区/形象建设/朋友圈高逼格照片文案",
        "type": "folder"
    },
    {
        "source": "【A17】手机摄影合集",
        "target": "主题专区/形象建设/手机摄影合集",
        "type": "folder"
    },
    {
        "source": "《把妹地图1.0》",
        "target": "主题专区/约会实战/《把妹地图1.0》",
        "type": "folder"
    },
    {
        "source": "《新把妹地图2.0》",
        "target": "主题专区/约会实战/《新把妹地图2.0》",
        "type": "folder"
    },
    {
        "source": "全流程约会攻略——让她爱上和你约",
        "target": "主题专区/约会实战/全流程约会攻略",
        "type": "folder"
    },
    {
        "source": "【A04】实z视频搭讪",
        "target": "主题专区/搭讪实战",
        "type": "folder"
    },
    {
        "source": "搭讪大师TV",
        "target": "主题专区/搭讪实战/搭讪大师TV",
        "type": "folder"
    },
    {
        "source": "【A07】几百套聊天案例合集",
        "target": "案例合集/聊天案例",
        "type": "folder"
    },
    {
        "source": "[REDACTED]/150套案例",
        "target": "案例合集/聊天案例/150套案例",
        "type": "folder"
    },
    {
        "source": "【A08】《一千多本情感书籍》合集",
        "target": "书籍资料/一千多本情感书籍",
        "type": "folder"
    },
    {
        "source": "[REDACTED]",
        "target": "书籍资料/七囍L",
        "type": "folder"
    },
    {
        "source": "麦克斯 女朋友游戏（关系管理）",
        "target": "主题专区/长期关系/麦克斯《女朋友游戏》",
        "type": "folder"
    },
    {
        "source": "【A06】女杏情感专属",
        "target": "主题专区/女性心理/女杏情感专属",
        "type": "folder"
    },
    {
        "source": "【A19】高端私教专区",
        "target": "导师专区/高端私教专区",
        "type": "folder"
    },
    {
        "source": "【A09】2026年课程上新中……",
        "target": "其他资料/2026年课程上新",
        "type": "folder"
    },
    {
        "source": "【A15】2025年课程",
        "target": "其他资料/2025年课程",
        "type": "folder"
    },
    {
        "source": "【6】社交吸引力训练营",
        "target": "主题专区/社交吸引力训练营",
        "type": "folder"
    },
    {
        "source": "高效赋能课——未满18岁禁止学习",
        "target": "其他资料/高效赋能课",
        "type": "folder"
    },
    {
        "source": "宣宣情感399VIP终身会员",
        "target": "其他资料/宣宣情感",
        "type": "folder"
    },
    {
        "source": "15、宅男宝典2023最新版本(加一情感）",
        "target": "其他资料/宅男宝典",
        "type": "folder"
    },
    {
        "source": "蒂姆（无暇自然）中文字幕",
        "target": "导师专区/蒂姆",
        "type": "folder"
    },
    {
        "source": "皮卡游戏",
        "target": "主题专区/互动游戏/皮卡游戏",
        "type": "folder"
    },
    {
        "source": "热度排序1",
        "target": "其他资料/热度排序1",
        "type": "folder"
    },
    {
        "source": "热度排序2",
        "target": "其他资料/热度排序2",
        "type": "folder"
    },
    {
        "source": "热度排序3",
        "target": "其他资料/热度排序3",
        "type": "folder"
    },
    {
        "source": "热度排序4",
        "target": "其他资料/热度排序4",
        "type": "folder"
    },
]


def get_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def scan_directory(base_path):
    files = []
    for root, dirs, filenames in os.walk(base_path):
        for filename in filenames:
            file_path = Path(root) / filename
            rel_path = file_path.relative_to(base_path)
            files.append({
                "path": str(rel_path),
                "full_path": str(file_path),
                "size": file_path.stat().st_size,
                "hash": get_file_hash(file_path) if file_path.is_file() else ""
            })
    return files


def dry_run():
    print("=" * 60)
    print("整理脚本 - 模拟运行模式")
    print("=" * 60)
    
    source_files = scan_directory(BASE_DIR)
    print(f"\n当前目录文件总数: {len(source_files)}")
    
    created_folders = []
    moved_items = []
    skipped_items = []
    
    for item in MIGRATION_MAP:
        source_path = BASE_DIR / item["source"]
        target_path = BASE_DIR / item["target"]
        
        if not source_path.exists():
            skipped_items.append({
                "source": str(source_path),
                "reason": "源路径不存在"
            })
            continue
        
        if target_path.exists():
            skipped_items.append({
                "source": str(source_path),
                "target": str(target_path),
                "reason": "目标路径已存在"
            })
            continue
        
        created_folders.append(str(target_path))
        moved_items.append({
            "source": str(source_path),
            "target": str(target_path)
        })
    
    print(f"\n将创建 {len(created_folders)} 个新文件夹")
    print(f"将移动 {len(moved_items)} 个项目")
    print(f"将跳过 {len(skipped_items)} 个项目")
    
    if skipped_items:
        print("\n跳过的项目:")
        for item in skipped_items:
            print(f"  - {item['source']}: {item['reason']}")
    
    return moved_items, skipped_items


def execute():
    print("=" * 60)
    print("整理脚本 - 执行模式")
    print("=" * 60)
    
    start_time = datetime.now()
    undo_log = []
    operation_log = []
    
    for item in MIGRATION_MAP:
        source_path = BASE_DIR / item["source"]
        target_path = BASE_DIR / item["target"]
        
        if not source_path.exists():
            operation_log.append({
                "type": "skip",
                "source": str(source_path),
                "reason": "源路径不存在"
            })
            continue
        
        if target_path.exists():
            operation_log.append({
                "type": "skip",
                "source": str(source_path),
                "target": str(target_path),
                "reason": "目标路径已存在"
            })
            continue
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(target_path))
            
            undo_log.append({
                "source": str(target_path),
                "target": str(source_path),
                "type": item["type"]
            })
            
            operation_log.append({
                "type": "move",
                "source": str(source_path),
                "target": str(target_path),
                "status": "success"
            })
            
            print(f"✓ 移动: {item['source']} -> {item['target']}")
            
        except Exception as e:
            operation_log.append({
                "type": "error",
                "source": str(source_path),
                "target": str(target_path),
                "error": str(e)
            })
            print(f"✗ 错误: {item['source']} -> {item['target']}")
            print(f"  原因: {e}")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": duration,
        "operations": operation_log
    }
    
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    with open(UNDO_FILE, "w", encoding="utf-8") as f:
        json.dump(undo_log, f, ensure_ascii=False, indent=2)
    
    print(f"\n整理完成！耗时: {duration:.2f} 秒")
    print(f"操作日志已保存到: {LOG_FILE}")
    print(f"撤销日志已保存到: {UNDO_FILE}")
    
    return operation_log


def undo():
    print("=" * 60)
    print("整理脚本 - 撤销模式")
    print("=" * 60)
    
    if not UNDO_FILE.exists():
        print("错误: 撤销日志不存在")
        return
    
    with open(UNDO_FILE, "r", encoding="utf-8") as f:
        undo_log = json.load(f)
    
    print(f"共有 {len(undo_log)} 项操作需要撤销")
    
    for item in reversed(undo_log):
        source_path = Path(item["source"])
        target_path = Path(item["target"])
        
        if not source_path.exists():
            print(f"✗ 跳过: {item['source']} 不存在")
            continue
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(target_path))
            print(f"✓ 撤销: {item['source']} -> {item['target']}")
        except Exception as e:
            print(f"✗ 错误: {item['source']} -> {item['target']}")
            print(f"  原因: {e}")
    
    print("\n撤销完成！")


def verify():
    print("=" * 60)
    print("整理脚本 - 验证模式")
    print("=" * 60)
    
    files_after = scan_directory(BASE_DIR)
    print(f"\n整理后文件总数: {len(files_after)}")
    
    print("\n顶层目录结构:")
    for name in sorted(os.listdir(BASE_DIR)):
        path = BASE_DIR / name
        if path.is_dir():
            item_count = sum(1 for _ in path.rglob("*"))
            print(f"  {name}/ ({item_count} 个项目)")
    
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            log = json.load(f)
        
        successful = sum(1 for op in log["operations"] if op["type"] == "move" and op["status"] == "success")
        skipped = sum(1 for op in log["operations"] if op["type"] == "skip")
        errors = sum(1 for op in log["operations"] if op["type"] == "error")
        
        print(f"\n操作统计:")
        print(f"  成功移动: {successful}")
        print(f"  跳过: {skipped}")
        print(f"  错误: {errors}")


def generate_report():
    print("=" * 60)
    print("整理脚本 - 生成报告")
    print("=" * 60)
    
    if not LOG_FILE.exists():
        print("错误: 操作日志不存在")
        return
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        log = json.load(f)
    
    report_lines = []
    report_lines.append("# 文档目录结构调整说明")
    report_lines.append("")
    report_lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**整理耗时**: {log['duration_seconds']:.2f} 秒")
    report_lines.append("")
    report_lines.append("## 一、调整背景")
    report_lines.append("")
    report_lines.append("当前文档目录存在以下问题:")
    report_lines.append("1. **导师内容分散**: 同一导师的课程分散在多个顶层目录")
    report_lines.append("2. **命名不统一**: 部分使用编号前缀，部分直接使用导师名")
    report_lines.append("3. **等级不明确**: 导师级内容与普通课程混在一起")
    report_lines.append("")
    report_lines.append("## 二、新层级体系")
    report_lines.append("")
    report_lines.append("### 一级目录")
    report_lines.append("")
    report_lines.append("| 目录名 | 说明 |")
    report_lines.append("|--------|------|")
    report_lines.append("| 导师专区 | 按导师/机构分类，核心层级 |")
    report_lines.append("| 主题专区 | 按主题分类，跨导师内容 |")
    report_lines.append("| 案例合集 | 实战案例集合 |")
    report_lines.append("| 书籍资料 | 书籍类文档 |")
    report_lines.append("| 其他资料 | 零散未分类内容 |")
    report_lines.append("")
    report_lines.append("### 二级目录（导师专区）")
    report_lines.append("")
    report_lines.append("| 导师 | 整合来源 |")
    report_lines.append("|------|----------|")
    report_lines.append("| 林老头 | 【A01】各大情感导师/A04、林老头 + 1、林老头《lin系统认知方法论》 + 13、林老头《精华直播案例内部完整版》2023 |")
    report_lines.append("| 浪迹 | 浪迹情感 + 浪迹汇总 + 浪迹（5月1日蓉城计划） |")
    report_lines.append("| 老佟 | 乐福佬佟《新私教》 + 乐福老佟《私密空间》 + 老佟419《一ye.情缘》 + 老佟《短期关系》 + 荔枝新老佟私教 + 老佟《一次约会追到女神》 + 老佟《低成本速推》 |")
    report_lines.append("| RSD | 【A02】RSD国外顶尖合集 + RSD德里克-游戏十诫 + RSD朱利安《高共振沟通》 + RSD瓦伦蒂诺《隐型游戏》 + 前RSD导师托德（言语游戏） + 泰勒基础与高级游戏RSD |")
    report_lines.append("| 柯李思 | 【A01】各大情感导师/A15、柯李思团队全套课程 + 柯李思Chris、良叔专区 |")
    report_lines.append("| 瑞恩 | 瑞恩RYAN专区 |")
    report_lines.append("| 加藤非 | 【A01】各大情感导师/A09、加藤非 + 加藤非《肉体TD》 + 加藤飞大尧《心肾全能速成课》 |")
    report_lines.append("| 乌鸦 | 【A01】各大情感导师/A08、乌鸦课程 |")
    report_lines.append("| 梵公子 | 【A01】各大情感导师/A01、梵公子 |")
    report_lines.append("| 朱利安 | 朱利安《高频沟通》 + 朱利安ten game + 朱利安《满分游戏》 |")
    report_lines.append("| 泰勒 | 【社交光谱】泰勒系列 + 泰勒 高状态沟通 |")
    report_lines.append("")
    report_lines.append("## 三、调整前后对比")
    report_lines.append("")
    report_lines.append("### 调整前")
    report_lines.append("")
    report_lines.append("```")
    report_lines.append("文档/")
    report_lines.append("├── 1、林老头《lin系统认知方法论》")
    report_lines.append("├── 13、林老头《精华直播案例内部完整版》2023")
    report_lines.append("├── 【A01】各大情感导师/")
    report_lines.append("│   ├── A04、林老头/")
    report_lines.append("│   └── ...")
    report_lines.append("├── 浪迹情感/")
    report_lines.append("├── 浪迹汇总/")
    report_lines.append("├── 浪迹（5月1日蓉城计划）/")
    report_lines.append("├── 乐福佬佟《新私教》/")
    report_lines.append("├── ...")
    report_lines.append("```")
    report_lines.append("")
    report_lines.append("### 调整后")
    report_lines.append("")
    report_lines.append("```")
    report_lines.append("文档/")
    report_lines.append("├── 导师专区/")
    report_lines.append("│   ├── 林老头/")
    report_lines.append("│   │   ├── 《lin系统认知方法论》")
    report_lines.append("│   │   ├── 《精华直播案例内部完整版》2023")
    report_lines.append("│   │   └── 心态课/")
    report_lines.append("│   ├── 浪迹/")
    report_lines.append("│   │   ├── 《恋爱攻略》/")
    report_lines.append("│   │   ├── 《社交攻略》/")
    report_lines.append("│   │   ├── 蓉城计划/")
    report_lines.append("│   │   └── ...")
    report_lines.append("│   ├── 老佟/")
    report_lines.append("│   │   ├── 《新私教》/")
    report_lines.append("│   │   ├── 《私密空间》/")
    report_lines.append("│   │   └── ...")
    report_lines.append("│   └── ...")
    report_lines.append("├── 主题专区/")
    report_lines.append("│   ├── 私密空间操作/")
    report_lines.append("│   ├── 形象建设/")
    report_lines.append("│   ├── 约会实战/")
    report_lines.append("│   └── ...")
    report_lines.append("├── 案例合集/")
    report_lines.append("├── 书籍资料/")
    report_lines.append("└── 其他资料/")
    report_lines.append("```")
    report_lines.append("")
    report_lines.append("## 四、操作统计")
    report_lines.append("")
    successful = sum(1 for op in log["operations"] if op["type"] == "move" and op["status"] == "success")
    skipped = sum(1 for op in log["operations"] if op["type"] == "skip")
    errors = sum(1 for op in log["operations"] if op["type"] == "error")
    report_lines.append(f"- 成功移动: {successful} 项")
    report_lines.append(f"- 跳过: {skipped} 项")
    report_lines.append(f"- 错误: {errors} 项")
    report_lines.append("")
    report_lines.append("## 五、调整依据")
    report_lines.append("")
    report_lines.append("1. **导师优先原则**: 将同一导师的所有课程整合到同一目录下，便于查找和管理")
    report_lines.append("2. **主题归类原则**: 跨导师的同类内容按主题分类（如私密空间操作、形象建设）")
    report_lines.append("3. **命名统一原则**: 移除编号前缀，使用清晰的课程名称")
    report_lines.append("4. **等级分明原则**: 导师专区为核心层级，主题专区为辅助层级")
    report_lines.append("")
    report_lines.append("## 六、撤销方式")
    report_lines.append("")
    report_lines.append("如需撤销本次整理，请运行:")
    report_lines.append("```bash")
    report_lines.append("python organize_docs.py --undo")
    report_lines.append("```")
    
    report_path = BASE_DIR.parent / "结构调整说明.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    
    print(f"\n报告已保存到: {report_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="文档目录整理脚本")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不执行实际操作")
    parser.add_argument("--execute", action="store_true", help="执行整理操作")
    parser.add_argument("--undo", action="store_true", help="撤销整理操作")
    parser.add_argument("--verify", action="store_true", help="验证整理结果")
    parser.add_argument("--report", action="store_true", help="生成调整说明文档")
    
    args = parser.parse_args()
    
    if args.dry_run:
        dry_run()
    elif args.execute:
        execute()
    elif args.undo:
        undo()
    elif args.verify:
        verify()
    elif args.report:
        generate_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()