# LLM Todo

本地 LLM 任务与人生规划工作台。

这个项目沿用 LLM Wiki 的模式：原始输入保存在 `raw/`，长期规划和任务解释保存在 `todo/`，结构化任务保存在 `data/tasks.json`，浏览器工作台提供任务视图、规划文档和聊天窗口。

## Quick Start

```bash
python3 scripts/llm_todo_server.py
```

打开 `http://127.0.0.1:8720/`。

可选环境：

```bash
export OPENAI_API_KEY=...
export LLM_TODO_MODEL=gpt-5.4-mini
export AGENT_CHAT_BASE_URL=http://127.0.0.1:8710
```

默认没有模型 key 时，系统使用本地规则助手：可以通过聊天新增任务、列出下一步、生成规划摘要。接入真实 provider 后，同一上下文包会交给模型处理。

## Project Boundary

- `llm_todo`：任务、规划、个人长期上下文、写入策略。
- sibling `../llm_agent_chat`：可嵌入聊天 UI、provider adapter、工具 manifest 协议。
- 后续可以把 `llm_agent_chat` 作为 git submodule 或 package 引入。
