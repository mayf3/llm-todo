# LLM Todo 交接文档

## 项目概述

LLM Todo 是一个本地优先的任务与人生规划工作台。核心设计理念：

- **双轨结构**：结构化任务（JSON）+ 规划文档（Markdown），AGENTS 维护规则，LLM 维护规划
- **多时间尺度**：从人生尺度到今天执行的清晰分层
- **可本地化**：纯 Python 标准库 HTTP 服务，无需外部依赖
- **可上云**：支持 Token 认证，便于部署后多端访问

## 角色分工

### 效率管家（Agent A）
- **职责**：日常任务管理、执行跟进、任务状态更新
- **关注点**：今天做什么、本周做什么、任务有没有过期、优先级对不对
- **工具**：直接调用 API（`/api/tasks/create`、`/api/tasks/update`、`/api/tasks/search`）
- **不负责**：人生方向选择、价值观讨论、长期目标设定

### 宏观规划 Agent（Agent B）
- **职责**：人生方向、长期目标、年度主题、季度节奏
- **关注点**：我的人生想往哪走、今年最重要的是什么、哪些事情值得长期投入
- **工具**：阅读和编辑 `todo/horizons/` 下的规划文档，通过聊天窗口给建议
- **不负责**：具体任务的执行状态、每天的任务清单更新

## 项目架构

### 数据层

```
data/
├── tasks.json        # 当前任务（active + waiting）
├── history.json      # 已完成/已放弃任务归档
└── backups/          # 自动备份（保留最近 10 份）
```

**重要**：`tasks.json` 和 `history.json` 是"事实源"，所有 UI 和 LLM 都从这里读取数据。任何修改都必须通过 API，不能直接手改。

### 规划层

```
todo/
├── index.md          # 规划入口，指向各个尺度
├── horizons/
│   ├── lifetime.md   # 人生价值观、不可逆承诺、放弃清单
│   ├── decade.md     # 十年方向和能力资本
│   ├── year.md       # 年度主题、项目组合、资源约束
│   ├── quarter.md    # 季度成果和阶段性指标
│   ├── month.md      # 项目节奏和外部承诺
│   ├── week.md       # 当前 next actions
│   └── today.md      # 今天可完成的动作
├── areas/            # 按领域组织的规划（system / life / learning / work / 自定义）
└── log.md            # 重要规划变更日志
```

**规则**：规划文档是 LLM 维护的"解释层"，用来回答"为什么做这些任务"和"如何选择优先级"。任务事实源记录"做什么"，规划文档记录"为什么"。

### API 接口

#### 核心查询

```bash
# 获取完整状态（任务 + 文档 + 统计）
GET /api/state

# 响应示例
{
  "tasks": [...],
  "history": [...],
  "stats": {...},
  "plans": {
    "lifetime": "人生价值摘要",
    "year": "2026 年度主题...",
    ...
  },
  "docs": [...]
}
```

#### 任务操作

```bash
# 创建任务
POST /api/tasks/create
Body: {"title": "任务标题", "horizon": "week", "area": "system", "priority": "high", "due": "2026-05-10"}

# 更新任务（支持所有字段）
POST /api/tasks/update
Body: {"id": "task-xxx", "status": "done", "priority": "medium"}

# 批量操作（适合 Agent A 批量同步任务清单）
POST /api/tasks/batch
Body: {"create": [{...}, {...}], "ids": ["task-1", "task-2"], "status": "done"}

# 搜索筛选
POST /api/tasks/search
Body: {"query": "关键词", "horizon": ["week", "month"], "area": "system", "priority": "high"}

# 撤销最近一次变更
POST /api/undo
```

#### 角色系统

```bash
# 获取角色数据（等级、能力值、成就）
GET /api/character

# 响应示例
{
  "name": "冒险者",
  "level": 5,
  "experience": {"current": 3, "next": 10, "totalCompleted": 43, "percent": 30},
  "abilities": [
    {"id": "engineering", "name": "🏗️ 工程力", "value": 75, "raw": 15, "unit": "项"},
    {"id": "learning", "name": "📚 学习力", "value": 40, "raw": 8, "unit": "项"},
    ...
  ],
  "achievements": [
    {"id": "first_done", "title": "首次完成任务", "unlocked": true},
    {"id": "streak_7", "title": "连续 7 天完成任务", "unlocked": false},
    ...
  ]
}
```

#### 提醒系统

```bash
# 获取到期和过期的高优先级任务
GET /api/reminders

# 响应示例
{
  "today": [{...}],   # 今天到期的高优先级任务
  "overdue": [{...}], # 已过期的高优先级任务
  "count": 3
}
```

## 任务 JSON Schema

```json
{
  "id": "task-YYYYMMDD-随机ID",
  "title": "任务标题（160 字符）",
  "status": "active | waiting | done | dropped",
  "horizon": "today | week | month | quarter | year | decade | lifetime",
  "area": "system | life | learning | work | 自定义字符串",
  "priority": "high | medium | low",
  "tags": ["标签1", "标签2"],
  "due": "YYYY-MM-DD",
  "nextAction": "下一步动作描述（220 字符）",
  "notes": "详细说明（500 字符）",
  "repeat": "daily | weekly | monthly | quarterly | yearly | 空",
  "created": "YYYY-MM-DD",
  "updated": "YYYY-MM-DD"
}
```

## 前端页面

```
http://localhost:8720/
├── /                    # 主工作台（任务列 + 规划文档 + 聊天）
├── /character/          # 角色页面（等级、能力雷达图、成就墙）
└── /design/             # 设计文档（架构、API、风险图）
```

## Agent 协作模式

### 场景 1：用户问"今天该做什么"
- **效率管家**：调用 `/api/state`，筛选 `horizon=today` 且 `status=active` 的任务，按优先级排序输出
- **宏观规划 Agent**：不需要参与，这是执行层的事情

### 场景 2：用户问"我今年的重点应该是什么"
- **宏观规划 Agent**：阅读 `todo/horizons/year.md` 和 `todo/horizons/lifetime.md`，结合当前任务分布，给出建议
- **效率管家**：可以提供数据支持（比如"今年已完成 15 个 system 任务，3 个 life 任务"），但不主导方向

### 场景 3：用户说"把整理年度规划加到任务里"
- **效率管家**：调用 `/api/tasks/create`，创建 `title="整理年度规划", horizon="week", area="system"`
- **宏观规划 Agent**：如果被邀请，可以补充"建议重点回顾哪些维度"（但不直接创建任务）

### 场景 4：用户说"我觉得今年应该更专注学习"
- **宏观规划 Agent**：讨论"为什么想专注学习"、"想学什么"、"愿意投入多少时间"，可能更新 `year.md`
- **效率管家**：如果讨论结果明确（比如"决定每周投入 10 小时学 Python"），则创建具体任务跟踪进度

## 部署配置

### 本地开发（无需认证）
```bash
cd <workspace>/llm_todo
python3 scripts/llm_todo_server.py
# 访问 http://localhost:8720/
```

### 上云部署（启用认证）
```bash
# 设置环境变量
export LLM_TODO_TOKEN="your-secret-token-here"
export LLM_TODO_HOST="0.0.0.0"
export LLM_TODO_PORT="8720"

# 启动服务
python3 scripts/llm_todo_server.py
```

**重要**：
- Token 通过环境变量 `LLM_TODO_TOKEN` 设置，不要写死在代码里
- 设置 Token 后，所有 `/api/*` 请求必须带 `Authorization: Bearer <token>` 头
- 静态文件（HTML/CSS/JS）无需认证，可以直接访问
- 前端首次访问会弹出 Token 输入框，自动存入 localStorage

### 反向代理（Nginx 示例）
```nginx
location / {
    proxy_pass http://127.0.0.1:8720;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## 数据安全

### 自动备份
- 每次写入 `tasks.json` 或 `history.json` 前，自动创建快照到 `data/backups/`
- 保留最近 10 份备份，自动清理旧备份
- 备份目录格式：`data/backups/YYYYMMDD-HHMMSS-操作标签/`

### 撤销操作
```bash
# 撤销最近一次变更
POST /api/undo

# 手动恢复
cp -r data/backups/20260508-123456-save-tasks/* data/
```

### Git 版本控制
```bash
# 建议忽略
gitignore: data/tasks.json data/history.json data/backups/

# 建议纳入
git add: todo/ schema/ scripts/ web/
```

## 效率管家的日常工作

### 每日检查（通过心跳触发）
```bash
# 1. 获取到期任务
GET /api/reminders

# 2. 输出提醒
if reminders.count > 0:
  print(f"有 {len(reminders.today)} 个任务今天到期")
  print(f"有 {len(reminders.overdue)} 个任务已过期")
```

### 同步外部任务清单
```bash
# 场景：从 AGENTS.md 读取任务清单，批量创建
POST /api/tasks/batch
Body: {
  "create": [
    {"title": "完善 LLM Todo", "horizon": "week", "priority": "high"},
    {"title": "研究 QuantDing 仓库", "horizon": "month", "priority": "high"}
  ]
}
```

### 任务状态流转
```bash
# 完成任务
POST /api/tasks/update
Body: {"id": "task-xxx", "status": "done"}

# 注意：如果任务设置了 repeat，会自动创建下一个周期的任务
```

## 宏观规划 Agent 的工作流

### 阅读规划文档
```python
# 伪代码示例
state = api("/api/state")
lifetime_plan = api(f"/api/doc?path=todo/horizons/lifetime.md")
year_plan = api(f"/api/doc?path=todo/horizons/year.md")

# 分析现状
system_tasks = [t for t in state["tasks"] if t["area"] == "system"]
print(f"当前有 {len(system_tasks)} 个系统任务在进行中")
```

### 更新规划文档
```bash
# Agent 不直接写文件，通过聊天接口让服务器写
POST /api/chat
Body: {
  "provider": "local-planner",
  "messages": [
    {"role": "user", "content": "更新年度规划，聚焦在学习和健康"}
  ]
}
```

**注意**：`/api/chat` 会调用本地规则引擎（`local-planner`），它可以安全地更新 `todo/` 下的 Markdown 文件。

## 重要约束

### 效率管家
- ✅ 可以：创建/编辑/删除任务、批量操作、搜索筛选、提醒到期
- ❌ 不可以：修改人生价值观、决定年度主题、改变规划方向
- ⚠️ 边界：可以建议"是否需要调整规划"，但由宏观规划 Agent 决定

### 宏观规划 Agent
- ✅ 可以：阅读和编辑规划文档、讨论人生方向、设定年度目标
- ❌ 不可以：直接修改任务状态、批量创建任务、撤销操作
- ⚠️ 边界：可以建议"需要添加哪些任务"，但由效率管家执行

## 代码结构

```
llm_todo/
├── scripts/
│   └── llm_todo_server.py    # 单文件 HTTP 服务（1482 行）
├── web/
│   ├── index.html            # 主工作台
│   ├── character.html        # 角色页面
│   ├── design.html           # 设计文档
│   ├── styles.css            # 全局样式（响应式）
│   ├── shared.js             # API 客户端 + Markdown 渲染
│   ├── app.js                # 主工作台逻辑
│   ├── character.js          # 角色页面逻辑
│   └── design.js             # 设计页面逻辑
├── schema/
│   ├── task.schema.json      # 任务 JSON Schema
│   └── AGENTS.md             # AGENTS 维护规则
├── data/
│   ├── tasks.json            # 当前任务（事实源）
│   ├── history.json          # 历史归档
│   └── backups/              # 自动备份
└── todo/
    ├── index.md              # 规划入口
    ├── horizons/             # 时间尺度规划
    ├── areas/                # 领域规划
    └── log.md                # 变更日志
```

## 下一步优化方向（非阻塞）

1. **移动端适配**：当前响应式布局已支持手机，但可能需要针对小屏优化
2. **Webhook 推送**：任务到期时主动推送通知（目前只在页面显示横幅）
3. **子任务/依赖关系**：支持任务间的 parent/children 结构
4. **PWA 支持**：离线使用和桌面快捷方式
5. **数据导入导出**：支持从 Todoist/Things 导入数据

## 联系方式

- 项目路径：`<workspace>/llm_todo/`
- 本地端口：`8720`
- Agent 负责人：效率管家（Agent A）+ 宏观规划 Agent（Agent B）
- 密钥管理：效率管家 Token 存储在环境变量或密钥管理工具中，不写入代码库
