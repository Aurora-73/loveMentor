# Identity 身份目录

## 概述

`engine/identity/` 负责**联系人身份的映射和管理**，实现 Person → Account → Alias 三层映射架构，支持同一人有多个微信号、多个别名的场景。身份目录是整个系统的基础，确保所有数据操作都能正确关联到对应的人。

## 架构定位

```
用户输入: "小溪"
    │
    └── engine/tools.py: _resolve("小溪")
            │
            └── engine/identity/directory.py
                    │
                    ├── 模糊搜索（名字/别名/wxid）
                    ├── 身份解析（Person → Account → Alias）
                    └── 返回 IdentityPerson 对象
```

## 模块清单

| 文件 | 职责 | 核心功能 |
|------|------|---------|
| `directory.py` | 身份目录核心 | Person→Account→Alias 映射、模糊搜索、别名管理、账号绑定、合并、审计 |

## 三层身份模型

```
Person（人）
    ├── Account（账号）
    │   ├── wxid_1
    │   └── wxid_2
    └── Alias（别名）
        ├── fake_name: "小溪"
        ├── pinyin: "xiaoxi"
        ├── real_name: "xxx"
        └── manual: "女神"
```

### Person（人）

代表一个真实的人，可以绑定多个微信账号。

### Account（账号）

微信账号，一个 Person 可以有多个 Account（同一个人多个微信号）。

### Alias（别名）

别名类型：

| 类型 | 含义 | 示例 |
|------|------|------|
| `fake_name` | 假名（用于显示和搜索） | "小溪" |
| `pinyin` | 拼音 | "xiaoxi" |
| `real_name` | 真实姓名（隐私级别高） | "XXX" |
| `manual` | 手动别名 | "女神" |

## 核心功能

### 自动初始化

从现有联系人/会话自动创建 Person 记录。

### 模糊搜索

支持按名字、别名、wxid、person_id 搜索，返回最匹配的 Person。

### 别名管理

- 添加别名：`contact_alias(name, alias_type, value)`
- 删除别名：`contact_alias_remove(name, alias_type, value)`
- 支持标记隐私级别

### 账号绑定

一个 Person 可绑定多个 wxid，查询时自动聚合所有账号的消息和指标。

### 合并

两个 Person 合并为一个（不可逆操作，需确认）。

### 审计

- 检测多账号（同一人多个微信号）
- 检测疑似重复联系人
- 检测未归属联系人

### 排名聚合

排名按 person_id 聚合多账号的指标，避免重复排名。

## 数据库表

身份目录使用以下数据库表：

| 表名 | 用途 |
|------|------|
| `people` | Person 主表（person_id, display_name, created_at） |
| `contact_accounts` | Account 表（account_id, person_id, wxid） |
| `contact_aliases` | Alias 表（alias_id, person_id, alias_type, value, privacy_level） |
| `contact_identity_log` | 身份操作日志（记录合并、别名变更等操作） |

## 关键设计原则

1. **唯一性保证**：一个微信账号只能属于一个 Person
2. **隐私保护**：real_name 类型别名标记为高隐私级别，不对外暴露
3. **不可逆操作**：合并操作不可逆，必须向用户确认
4. **自动聚合**：查询消息和指标时，自动聚合同一 Person 的所有 Account
5. **向后兼容**：支持从旧格式（display_name 匹配）自动迁移到新格式（person_id 匹配）

## 调用关系

```
engine/tools.py: _resolve(name)
    └── directory.py: find_person(query)
            ├── find_by_name(query)
            ├── find_by_alias(query)
            ├── find_by_wxid(query)
            └── find_by_person_id(query)
```

## 参考文档

- 身份目录详细文档：`readme/identity.md`
