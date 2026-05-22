# LLM Todo 需求池 + Agent 提需求 — 后端 API 设计

> 需求 ID: 0b0b5608-0b9a-47bd-858c-f878dfea4f53
> 作者: agent-dev-engineer
> 日期: 2026-05-15

---

## 1. 现状

- 任务存储: `data/tasks.json`（JSON 文件）
- 现有 status 值: `active`, `waiting`, `done`, `dropped`
- 任务类型: `personal`, `agent`, `review`, `discuss`
- 任务字段: id, title, status, type, assignee, subStatus, horizon, area, priority, tags, due, nextAction, notes, repeat, created, updated
- API: `/api/tasks/create`, `/api/tasks/update`, `/api/tasks/search`, `/api/tasks/batch`
- 认证: Bearer token (admin) 或 Agent JWT
- 服务器: Python `scripts/llm_todo_server.py`

## 2. 变更设计

### 2.1 新增 `draft` 状态

```python
DRAFT_STATUSES = {"draft"}
CURRENT_STATUSES = {"active", "waiting"} | DRAFT_STATUSES
ARCHIVE_STATUSES = {"done", "dropped", "archived"}
TASK_STATUSES = CURRENT_STATUSES | ARCHIVE_STATUSES
```

**行为**:
- `draft` 任务**不出现在**默认 `GET /api/tasks` 返回中
- `draft` 任务**不出现在** `GET /api/state` 的工作台视图中
- 需要 `?status=draft` 参数才能查询

### 2.2 新增 `source` 字段

```python
{
    "source": "agent:cto-agent",     # 任务来源
    "sourceType": "agent",           # 来源类型: agent | user | system | import
}
```

在 `task_from_payload` 和 `normalize_task` 中加入：
```python
"source": str(payload.get("source", "")).strip()[:120],
"sourceType": str(payload.get("sourceType", "agent")).strip() if payload.get("sourceType") in {"agent", "user", "system", "import"} else "agent",
```

## 3. 新增 API

### 3.1 Agent 提需求

```
POST /api/tasks/propose
```

**认证**: Agent JWT 或 admin token

**请求体**:
```json
{
  "title": "优化搜索算法性能",
  "notes": "当前搜索在 10k+ 任务时延迟明显",
  "area": "dev",
  "priority": "high",
  "tags": ["性能", "搜索"],
  "source": "agent:dev-engineer",
  "sourceType": "agent"
}
```

**行为**:
1. 创建任务，`status = "draft"`
2. 自动设置 `source` 和 `sourceType`
3. 不出现在正式列表
4. 返回完整任务数据

**响应**:
```json
{
  "task": {
    "id": "task-20260515-dev-01",
    "title": "优化搜索算法性能",
    "status": "draft",
    "source": "agent:dev-engineer",
    "sourceType": "agent",
    "area": "dev",
    ...
  },
  "message": "需求已提交到需求池，等待审批"
}
```

### 3.2 查询需求池

```
GET /api/tasks?status=draft
GET /api/tasks?status=draft&source=agent:cto-agent
GET /api/tasks?status=draft&area=dev
GET /api/tasks?status=draft&priority=high
```

**修改 `GET /api/tasks` 路由**:
- 无 status 参数 → 返回非 draft 任务（向后兼容）
- `status=draft` → 返回 draft 任务
- `status=all` → 返回全部任务（admin only）

### 3.3 审批 API

```
POST /api/tasks/:id/approve
POST /api/tasks/:id/reject
```

**认证**: admin token only（只有管理员能审批）

**approve 请求体**（可选）:
```json
{
  "priority": "high",
  "horizon": "week",
  "assignee": "dev-engineer"
}
```

**行为**:
- `approve`: `draft → active`，可覆盖字段
- `reject`: `draft → archived`，可加原因

**approve 响应**:
```json
{
  "task": { "id": "xxx", "status": "active", ... },
  "message": "需求已批准并激活"
}
```

**reject 响应**:
```json
{
  "task": { "id": "xxx", "status": "archived", ... },
  "message": "需求已拒绝"
}
```

### 3.4 批量审批

```
POST /api/tasks/batch-approve
```

**请求体**:
```json
{
  "taskIds": ["task-xxx-01", "task-xxx-02"],
  "action": "approve",
  "overrides": {
    "priority": "medium"
  }
}
```

### 3.5 需求池统计

```
GET /api/tasks/draft-stats
```

**响应**:
```json
{
  "total": 15,
  "bySource": {
    "agent:cto-agent": 5,
    "agent:dev-engineer": 8,
    "user:admin": 2
  },
  "byArea": {
    "dev": 6,
    "content": 4,
    "life": 3,
    "ops": 2
  },
  "byPriority": {
    "high": 5,
    "medium": 7,
    "low": 3
  },
  "oldest": "2026-05-13"
}
```

## 4. 修改点汇总

| 文件 | 修改 |
|------|------|
| `scripts/llm_todo_server.py` | 修改 `TASK_STATUSES`、`task_from_payload`、`GET /api/tasks`、新增路由 |

### 具体代码修改

#### 4.1 状态常量

```python
DRAFT_STATUSES = {"draft"}
CURRENT_STATUSES = {"active", "waiting"} | DRAFT_STATUSES
ARCHIVE_STATUSES = {"done", "dropped", "archived"}
TASK_STATUSES = CURRENT_STATUSES | ARCHIVE_STATUSES
```

#### 4.2 task_from_payload 增加 source 字段

```python
def task_from_payload(payload: dict) -> dict:
    # ... 现有字段 ...
    return {
        # ... 现有 ...
        "source": str(payload.get("source", "")).strip()[:120],
        "sourceType": str(payload.get("sourceType", "agent")).strip() if payload.get("sourceType") in {"agent", "user", "system", "import"} else "agent",
    }
```

#### 4.3 normalize_task 兼容旧数据

```python
def normalize_task(task: dict, default_status: str = "active") -> dict:
    # ... 现有 ...
    task.setdefault("source", "")
    task.setdefault("sourceType", "agent")
    return task
```

#### 4.4 propose_task 函数

```python
def propose_task(payload: dict) -> dict:
    """Agent 提需求，创建 draft 任务"""
    payload["status"] = "draft"
    payload.setdefault("sourceType", "agent")
    task = task_from_payload(payload)
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    append_log(f"新需求提交：{task['title']}（来源：{task.get('source', 'unknown')}）")
    return {"task": task, "message": "需求已提交到需求池，等待审批"}
```

#### 4.5 approve/reject_task 函数

```python
def approve_task(task_id: str, overrides: dict | None = None) -> dict:
    tasks = load_tasks()
    for task in tasks:
        if task.get("id") != task_id:
            continue
        if task.get("status") != "draft":
            raise ValueError(f"任务状态不是 draft（当前: {task['status']}）")
        task["status"] = "active"
        task["updated"] = str(datetime.now().date())
        if overrides:
            for key in ("priority", "horizon", "assignee", "area", "tags"):
                if key in overrides:
                    task[key] = overrides[key]
        save_tasks(tasks)
        append_log(f"需求批准：{task['title']}")
        return {"task": task, "message": "需求已批准并激活"}
    raise ValueError("task not found")


def reject_task(task_id: str, reason: str = "") -> dict:
    tasks = load_tasks()
    for task in tasks:
        if task.get("id") != task_id:
            continue
        if task.get("status") != "draft":
            raise ValueError(f"任务状态不是 draft（当前: {task['status']}）")
        task["status"] = "archived"
        task["updated"] = str(datetime.now().date())
        if reason:
            task["notes"] = f"{task.get('notes', '')}\n[拒绝原因]: {reason}".strip()
        save_tasks(tasks)
        append_log(f"需求拒绝：{task['title']}")
        return {"task": task, "message": "需求已拒绝"}
    raise ValueError("task not found")
```

#### 4.6 GET /api/tasks 修改

```python
# 在 do_GET 中
elif path == "/api/tasks":
    status_filter = query.get("status", [None])[0]
    all_tasks = sorted_tasks(load_tasks())
    if status_filter == "all":
        if not self.require_admin():
            return
        filtered = all_tasks
    elif status_filter == "draft":
        filtered = [t for t in all_tasks if t.get("status") == "draft"]
    elif status_filter:
        filtered = [t for t in all_tasks if t.get("status") == status_filter]
    else:
        # 默认：不返回 draft（向后兼容）
        filtered = [t for t in all_tasks if t.get("status") != "draft"]
    # 支持 source/area 筛选
    source_filter = query.get("source", [None])[0]
    if source_filter:
        filtered = [t for t in filtered if t.get("source") == source_filter]
    area_filter = query.get("area", [None])[0]
    if area_filter:
        filtered = [t for t in filtered if t.get("area") == area_filter]
    self.send_json({"tasks": filtered})
```

#### 4.7 路由注册

```python
# do_POST
elif path == "/api/tasks/propose":
    if not self.require_agent() and not self.is_admin:
        return
    self.send_json(propose_task(payload))
elif path == "/api/tasks/batch-approve":
    if not self.require_admin():
        return
    self.send_json(batch_approve(payload))

# 新增 do_PATCH 路由
task_approve_match = re.fullmatch(r"/api/tasks/([^/]+)/(approve|reject)", path)
if task_approve_match:
    if not self.require_admin():
        return
    task_id = task_approve_match.group(1)
    action = task_approve_match.group(2)
    if action == "approve":
        self.send_json(approve_task(task_id, payload))
    else:
        self.send_json(reject_task(task_id, payload.get("reason", "")))
```

## 5. API 总览

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `POST` | `/api/tasks/propose` | Agent/Admin | Agent 提需求（创建 draft） |
| `PATCH` | `/api/tasks/:id/approve` | Admin | 审批通过（draft → active） |
| `PATCH` | `/api/tasks/:id/reject` | Admin | 拒绝需求（draft → archived） |
| `POST` | `/api/tasks/batch-approve` | Admin | 批量审批 |
| `GET` | `/api/tasks?status=draft` | Any | 查询需求池 |
| `GET` | `/api/tasks/draft-stats` | Any | 需求池统计 |

## 6. 向后兼容

- `GET /api/tasks` 不传 status → 返回非 draft 任务（与现有行为一致）
- 现有任务无 `source`/`sourceType` 字段 → `normalize_task` 自动补默认值
- 现有 `POST /api/tasks/create` → 不受影响，默认 status=active
- 新状态 `archived` 仅为 draft 拒绝后使用，不影响现有 `dropped`

## 7. 实现排期

**预计 1 天完成全部后端 API**（纯 Python 修改，无数据库）
前端需求池标签页由 devtools-agent 负责。
