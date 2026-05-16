# LLM Todo 任务编译引擎 — API 设计

> 需求 ID: 5989c232-f371-4c29-98fc-ab222cf2b858
> 作者: agent-dev-engineer
> 日期: 2026-05-16

---

## 1. 现状

- 61 个任务，纯 CRUD，相互无关联
- skill tree 存在但静态
- 规划层只有手动维护

## 2. 新增功能

### 2.1 任务关系分析

新增 `relations` 字段在 task 对象中：

```json
{
  "id": "task-xxx",
  "relations": [
    {"id": "task-yyy", "type": "blocks", "direction": "out"},
    {"id": "task-zzz", "type": "related", "direction": "in"}
  ]
}
```

关系类型：`blocks`, `blocked-by`, `related`, `duplicates`, `conflicts-with`

**API**：
- `PUT /api/tasks/:id/relations` — 手动设置关系
- `GET /api/tasks/:id/relations` — 获取关系链（含反向关联）

**自动分析**：任务创建/更新时增量触发：
- 标题关键词匹配（如"依赖"、"基于"、"阻塞"）
- area 相同且标题相似的高亮为 `related`
- 相同 area 且优先级冲突的高亮为 `conflicts-with`

### 2.2 技能树联动

**新增函数**：`analyze_task_skills(task) → list[skill_updates]`
- 任务 title/area/tags 匹配技能树节点
- 新方向自动建议 `suggest_new_skill(task)`
- 技能成熟度评估：`evaluate_skill_maturity(skill_id)`

**存储**：技能节点新增 `taskRefs: list[str]` 字段

**API**：
- `GET /api/skill-tree/node-impact?taskId=xxx` — 预测任务对技能树的影响

### 2.3 规划层更新

**新增函数**：`analyze_planning(tasks) → dict`
- 按 area 聚合 in-progress + draft 任务
- 检测 Q 方向集中度（> 50% 提升建议）
- 偏差检测：week horizon 但有 year-level 任务

**API**：
- `GET /api/roadmap/analysis` — 规划分析报告

### 2.4 编译引擎

**增量编译**：任务创建/更新/关系变更时触发
- 重新计算该任务的关系
- 重新评估相关技能节点
- 推送编译结果

**全量编译**：`POST /api/compile/full`
- 遍历所有任务重建关系图
- 重新评估所有技能节点
- 生成编译报告

**编译报告**：新增 `data/compile-artifacts.json`
```json
{
  "lastFullCompile": "2026-05-16T10:00:00",
  "taskCount": 61,
  "relationCount": 15,
  "skillUpdates": [{"skill": "量化交易", "maturityDelta": 0.1}],
  "planningAlerts": [{"type": "deviation", "area": "ops", "message": "..."}]
}
```

## 3. API 总览

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `PUT` | `/api/tasks/:id/relations` | Admin/Agent | 设置任务关系 |
| `GET` | `/api/tasks/:id/relations` | Any | 获取关系链 |
| `GET` | `/api/skill-tree/node-impact?taskId=xxx` | Any | 预测技能影响 |
| `GET` | `/api/roadmap/analysis` | Any | 规划分析 |
| `POST` | `/api/compile/full` | Admin | 全量编译 |
| `POST` | `/api/compile/auto` | 内部 | 增量编译（内部调用） |

## 4. 实现策略

直接在 `llm_todo_server.py` 中新增：
- `analyze_task_relationships(task)` — 任务关系分析
- `analyze_task_skills(task)` — 技能树联动
- `analyze_planning()` — 规划层分析
- `incremental_compile(task_id)` — 增量编译
- `full_compile()` — 全量编译
- 路由注册 + 处理函数

所有新增逻辑放在同一文件中（Python 服务器模式），新增约 300-400 行。
