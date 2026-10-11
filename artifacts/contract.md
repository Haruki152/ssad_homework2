# 需求管理系统 —— 接口契约 v1（冻结）

> 本文件是本作业的基准契约，最初由同一会话按架构师角色整理，后续随修复更新。真实编排会在各自 runs 目录生成并冻结该次契约。
> 冻结后所有下游 agent（Data / Backend / Frontend / QA）必须严格遵守，
> 不得自行修改数据结构或接口签名。如需变更，须回到 Architect 重新走一遍流程。

## 一、技术栈（已定，不可更改）

| 项 | 选择 |
|---|---|
| 语言 | Python 3.12 |
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.x |
| 数据库 | SQLite |
| 校验 | Pydantic v2 |

## 二、数据模型

### 2.1 表结构

**project 项目**

| 字段 | 类型 | 约束 |
|---|---|---|
| project_id | INTEGER | PK, 自增 |
| name | TEXT | NOT NULL |
| created_at | DATETIME | 默认当前时间（现有模型允许空） |

**item_type 条目类型**

| 字段 | 类型 | 约束 |
|---|---|---|
| item_type_id | INTEGER | PK, 自增 |
| project_id | INTEGER | FK → project, NOT NULL |
| name | TEXT | NOT NULL |

**attribute_definition 属性定义**

| 字段 | 类型 | 约束 |
|---|---|---|
| attr_id | INTEGER | PK, 自增 |
| item_type_id | INTEGER | FK → item_type, NOT NULL |
| name | TEXT | NOT NULL |
| data_type | TEXT | NOT NULL，取值 text / int / enum |
| value_domain | TEXT | 可空，枚举取值域，逗号分隔 |
| required | BOOLEAN | NOT NULL, 默认 false |

**item 条目**

| 字段 | 类型 | 约束 |
|---|---|---|
| item_id | INTEGER | PK, 自增 |
| project_id | INTEGER | FK → project, NOT NULL |
| item_type_id | INTEGER | FK → item_type, NOT NULL |
| title | TEXT | NOT NULL |
| status | TEXT | NOT NULL, 默认 draft |
| owner | TEXT | 可空 |
| custom_attrs | JSON | 可空，存放自定义属性取值 |

**relationship 关系**

| 字段 | 类型 | 约束 |
|---|---|---|
| rel_id | INTEGER | PK, 自增 |
| from_item_id | INTEGER | FK → item, NOT NULL |
| to_item_id | INTEGER | FK → item, NOT NULL |
| link_type | TEXT | NOT NULL |
| suspect | BOOLEAN | NOT NULL, 默认 false |

### 2.2 设计约束（硬性）

> 以下三条是本系统的核心设计决定，**下游 agent 不得绕过**。

- **D1 元模型不可写死**：`item` 表**只允许**出现 `item_id / project_id / item_type_id / title / status / owner / custom_attrs` 七个字段。一切业务属性（优先级、来源、理由、验收度量、稳定性等）**必须**经 `attribute_definition` 定义、存入 `custom_attrs`。**不得**在 `item` 表上直接开业务列。
- **D2 状态机受控**：`item.status` 的合法流转为
  `draft → reviewing → approved → implemented → verified`，另有任意状态 → `deprecated`。
  非法流转必须拒绝。
- **D3 关系带可疑标记**：`relationship.suspect` 用于标记"上游条目已变更、下游待复核"。上游条目内容被修改时，以它为起点（from_item_id）的下游关系必须置 `suspect = true`。

## 三、接口签名

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/projects` | 创建项目 |
| POST | `/item-types` | 创建条目类型 |
| POST | `/item-types/{id}/attributes` | 为类型添加属性定义 |
| POST | `/items` | 创建条目 |
| GET | `/items/{id}` | 查询条目（含属性值） |
| PUT | `/items/{id}` | 修改条目（触发 D2、D3） |
| POST | `/relationships` | 建立关系 |
| GET | `/items/{id}/trace` | 查询某条目的上下游追溯 |

## 四、边界

- 不含前端，只做 API
- 不含权限、评审、报表
- 基线不在本契约范围内


## 五、修复补充约定（2026-10-10）

- 条目请求及响应字段统一为 `custom_attrs`，请求允许 `attrs` 作为兼容别名，但两者不可同时提交。
- 属性值严格校验 `text / int / enum`；整数不接受 bool 或数字字符串；必填值不可为 null 或空白文本。
- 项目、类型和关系端点必须存在，类型必须属于指定项目，关系暂不支持跨项目或自关联。
- 同一状态的重复更新按幂等操作接受。沿用本契约的简化生命周期；2.1 中的评审驳回暂未实现。
- 新建条目初始状态为 draft；未知对象返回 404；业务规则失败返回 400；重复定义或关系返回 409；请求格式错误返回 422。
- 原契约仅列出八个核心接口。修复版另提供列表、搜索、删除及清除可疑标记，作为演示辅助接口。
- 条目属性采取整对象替换；PUT 中省略的字段保持不变，显式 owner=null 用于清空负责人。
- API 包公开 engine；database 模块提供 make_engine(url)。启动时建表，SQLite 外键默认开启。
- 结构重设计需保留全部核心接口和请求字段兼容性，并通过同一组行为回归测试。

## 六、统一模型说明

七个基本字段固定保存，描述、优先级、来源、理由和验收度量等经属性定义保存于JSON。无独立AttributeValue表。可疑标记只作用于上游发出的直接关系，不递归。reviewing/approved是简化状态，不表示完成了真实审批。
