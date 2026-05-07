---
title: LLM Todo 系统设计
kind: design
updated: 2026-05-05
sources: README.md; schema/AGENTS.md; data/tasks.json; data/history.json; Karpathy LLM Wiki pattern
confidence: high
---

# LLM Todo 系统设计

## 目标

做一个 LLM-first 的任务和人生规划系统。用户主要通过聊天窗口表达“我要做什么、我很乱、帮我整理、下一步是什么、长期方向是否还对”。系统把这些输入整理成结构化任务、时间尺度规划页和可复盘日志。

## 与 LLM Wiki 的关系

Karpathy 的 LLM Wiki 模式强调：不要只做一次性检索，而要让 LLM 维护一个长期存在的中间层。LLM Todo 采用同一思想：

- `raw/` 保存原始输入。
- `todo/` 保存 LLM 维护后的长期规划、领域页和日志。
- `data/tasks.json` 保存当前任务事实，`data/history.json` 保存已完成和已放弃归档。
- Web 是阅读、纠错和聊天入口，不是唯一 source of truth。

## 与 Agent Chat 的关系

`llm_todo` 不应该把模型提供方适配器写死在业务里。聊天模块应由同层 `../llm_agent_chat` 提供：

- `llm_todo` 负责上下文：任务、规划、写入权限、工具。
- `llm_agent_chat` 负责嵌入组件、模型提供方、会话和通用聊天协议。
- 首版 `llm_todo` 内置一个本地聊天端点，后续可以把请求转发给 `AGENT_CHAT_BASE_URL`。

## 数据流

```text
用户聊天或快速编辑
  ↓
scripts/llm_todo_server.py
  ↓ reads
data/tasks.json + data/history.json + todo/*.md + raw/inbox
  ↓
local planner or external provider
  ↓
task operations + planning notes
  ↓ writes
data/tasks.json + data/history.json + todo/log.md + 可选 raw 捕获
  ↓
Web dashboard rerenders
```

## 请求响应

```text
Browser GET /
  ↓
web/app.js requests /api/state
  ↓
服务端扫描任务和规划文档
  ↓
User sends chat message
  ↓
POST /api/chat
  ↓
Server assembles todo context
  ↓
模型提供方或本地规划器返回答复和可选操作
  ↓
Server applies safe operations
  ↓
Browser refreshes dashboard and chat transcript
```

## 状态流

```text
inbox
  ↓ clarify
候选任务
  ↓ accept
active
  ↓ finish / defer / drop
done | waiting | dropped

horizon_note
  ↓ review
principle / goal / constraint
  ↓ quarterly planning
project
  ↓ weekly planning
next_action
```

## 目录结构

```text
llm_todo/
  raw/
    inbox/
  data/
    tasks.json
    history.json
  todo/
    index.md
    log.md
    horizons/
    areas/
    review/
  schema/
    AGENTS.md
    task.schema.json
  docs/
    design.md
    review.md
  scripts/
    llm_todo_server.py
  web/
    index.html
    design.html
    styles.css
    shared.js
    app.js
    design.js
```

## 风险图

| 级别 | 风险 | 缓解措施 |
| --- | --- | --- |
| 高 | LLM 把人生规划过度任务化，制造伪精确感。 | 明确规划尺度和任务的分层，长期页只保存判断和约束。 |
| 高 | 聊天写入误改长期规划。 | 所有写入先限制在任务 JSON 和日志；长期页写入需要专门操作。 |
| 中 | 模型提供方适配散落在业务里。 | 把通用聊天模块放到同层 `llm_agent_chat`，todo 只暴露上下文和工具。 |
| 中 | 本地规则助手让用户误以为真实 LLM 已工作。 | UI 显示模型提供方状态，并返回明确的本地规则文案。 |
| 低 | JSON 和 Markdown 双写不一致。 | `data/tasks.json` 和 `data/history.json` 是任务事实源，Markdown 是解释和复盘层。 |

## 设计评审要求

`/design/` 必须展示数据流、代码依赖、状态流、request-response、风险图、目录结构、文件职责和评审历史。
