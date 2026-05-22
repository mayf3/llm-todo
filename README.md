# LLM Todo

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A local-first task management and life planning workspace powered by LLM.

一个本地优先的 LLM 任务与人生规划工作台。

## Features

- 📋 **Task Management** — CRUD tasks with priorities, tags, horizons, and areas
- 🤖 **Multi-Agent Support** — Each agent gets JWT auth, task views, and assignment tracking
- 🧠 **LLM Provider Integration** — Plug in OpenAI / DeepSeek / GLM for AI-assisted planning
- 📅 **Time Horizons** — Week / Month / Quarter / Year / Lifetime task scoping
- 🔗 **Task Relations** — Auto-compile related tasks with blocked-by / conflicts-with links
- 📊 **Web Dashboard** — Built-in HTML dashboard with Gantt chart, task board, and chat
- 💬 **Chat Interface** — Natural language task creation and management
- 🔄 **Remote Sync** — Sync tasks between instances

## Quick Start

```bash
# Clone
git clone https://github.com/mayf3/llm-todo.git
cd llm-todo

# Run
python3 scripts/llm_todo_server.py
```

Open `http://127.0.0.1:8720/`.

### Environment Variables

```bash
export OPENAI_API_KEY=...          # OpenAI provider
export OPENAI_COMPAT_API_KEY=...   # DeepSeek or other OpenAI-compatible API
export GLM_API_KEY=...             # Zhipu GLM provider
export LLM_TODO_MODEL=gpt-5.4-mini
export AGENT_CHAT_BASE_URL=http://127.0.0.1:8710
```

Default: when no model key is set, the system uses a local rule-based planner that supports task creation, listing next steps, and planning summaries via chat.

## Project Structure

```
llm-todo/
├── scripts/           # Python server
│   └── llm_todo_server.py
├── web/               # HTML dashboard
│   ├── index.html
│   ├── app.js
│   └── shared.js
├── data/              # Runtime data (gitignored)
├── todo/              # Planning docs
│   ├── horizons/      # Week/Month/Quarter/Year/Lifetime
│   └── areas/         # System/Life/Dev/Work
├── schema/            # JSON schemas
└── docs/              # Documentation
```

## Architecture

- `llm_todo` — Tasks, planning, personal long-term context, write strategies
- `llm_agent_chat` — Chat UI, provider adapter, tool manifest protocol (sibling project)

## License

[MIT](LICENSE)
