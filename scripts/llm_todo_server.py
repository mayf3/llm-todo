#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RAW = ROOT / "raw"
TODO = ROOT / "todo"
DATA = ROOT / "data"
DOCS = ROOT / "docs"
REVIEW_DIR = TODO / "review"
TASKS_PATH = DATA / "tasks.json"
HISTORY_PATH = DATA / "history.json"

DEFAULT_MODEL = os.environ.get("LLM_TODO_MODEL", "gpt-5.4-mini")
AGENT_CHAT_BASE_URL = os.environ.get("AGENT_CHAT_BASE_URL", "").rstrip("/")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
}

HORIZON_ORDER = ["today", "week", "month", "quarter", "year", "decade", "lifetime"]
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
CURRENT_STATUSES = {"active", "waiting"}
ARCHIVE_STATUSES = {"done", "dropped"}
TASK_STATUSES = CURRENT_STATUSES | ARCHIVE_STATUSES


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + 4 :].lstrip("\n")
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"')
    return data, body


def write_markdown(path: Path, frontmatter: dict[str, str], body: str) -> None:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.extend(["---", "", body.rstrip(), ""])
    write_text(path, "\n".join(lines))


def title_for(path: Path, body: str, frontmatter: dict[str, str]) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ")


def first_summary(body: str) -> str:
    for line in body.splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#") and not clean.startswith("---"):
            return clean[:180]
    return ""


def clean_text(value: object, limit: int, fallback: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return (text[:limit] if text else fallback)


def normalize_area(value: object, fallback: str = "life") -> str:
    area = re.sub(r"\s+", " ", str(value if value is not None else "").strip())
    area = area.strip("#/，,。；;")
    return area[:40] or fallback


def normalize_tags(value: object) -> list[str]:
    if value is None:
        return []
    raw_items: list[str] = []
    if isinstance(value, list):
        for item in value:
            raw_items.extend(re.split(r"[,，、\s]+", str(item)))
    else:
        raw_items.extend(re.split(r"[,，、\s]+", str(value)))

    tags: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        tag = item.strip().strip("#/，,。；;")
        if not tag:
            continue
        tag = tag[:32]
        marker = tag.lower()
        if marker not in seen:
            tags.append(tag)
            seen.add(marker)
        if len(tags) >= 12:
            break
    return tags


def normalize_task(task: dict, default_status: str = "active") -> dict:
    today = str(datetime.now().date())
    status = task.get("status") if task.get("status") in TASK_STATUSES else default_status
    horizon = task.get("horizon") if task.get("horizon") in HORIZON_ORDER else "week"
    priority = task.get("priority") if task.get("priority") in PRIORITY_ORDER else "medium"
    return {
        "id": clean_text(task.get("id"), 80, new_task_id()),
        "title": clean_text(task.get("title"), 160, "未命名任务"),
        "status": status,
        "horizon": horizon,
        "area": normalize_area(task.get("area"), "life"),
        "priority": priority,
        "tags": normalize_tags(task.get("tags")),
        "due": clean_text(task.get("due"), 20),
        "nextAction": clean_text(task.get("nextAction"), 220),
        "notes": clean_text(task.get("notes"), 500),
        "created": clean_text(task.get("created"), 20, today),
        "updated": clean_text(task.get("updated"), 20, today),
    }


def read_task_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(read_text(path))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    items = payload.get("tasks", payload.get("history", [])) if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def load_tasks() -> list[dict]:
    current: list[dict] = []
    archived: list[dict] = []
    for raw_task in read_task_file(TASKS_PATH):
        task = normalize_task(raw_task)
        if task["status"] in ARCHIVE_STATUSES:
            archived.append(task)
        else:
            current.append(task)
    if archived:
        write_tasks_file(TASKS_PATH, current)
        append_history(archived)
    return current


def save_tasks(tasks: list[dict]) -> None:
    current: list[dict] = []
    archived: list[dict] = []
    for raw_task in tasks:
        task = normalize_task(raw_task)
        if task["status"] in ARCHIVE_STATUSES:
            archived.append(task)
        else:
            current.append(task)
    write_tasks_file(TASKS_PATH, current)
    if archived:
        append_history(archived)


def write_tasks_file(path: Path, tasks: list[dict]) -> None:
    write_text(path, json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2) + "\n")


def load_history() -> list[dict]:
    load_tasks()
    return [normalize_task(task, "done") for task in read_task_file(HISTORY_PATH)]


def save_history(tasks: list[dict]) -> None:
    unique: dict[str, dict] = {}
    for raw_task in tasks:
        task = normalize_task(raw_task, "done")
        if task["status"] not in ARCHIVE_STATUSES:
            task["status"] = "done"
        unique[task["id"]] = task
    write_tasks_file(HISTORY_PATH, list(unique.values()))


def append_history(tasks: list[dict]) -> None:
    history = {task["id"]: task for task in load_history_raw()}
    for raw_task in tasks:
        task = normalize_task(raw_task, "done")
        if task["status"] not in ARCHIVE_STATUSES:
            task["status"] = "done"
        history[task["id"]] = task
    write_tasks_file(HISTORY_PATH, list(history.values()))


def load_history_raw() -> list[dict]:
    return [normalize_task(task, "done") for task in read_task_file(HISTORY_PATH)]


def list_markdown(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def doc_records() -> list[dict]:
    records = []
    for path in list_markdown(TODO):
        text = read_text(path)
        frontmatter, body = split_frontmatter(text)
        records.append(
            {
                "path": rel(path),
                "title": title_for(path, body, frontmatter),
                "kind": frontmatter.get("kind", "page"),
                "updated": frontmatter.get("updated", ""),
                "summary": first_summary(body),
                "lines": len(text.splitlines()),
            }
        )
    return records


def safe_project_path(raw_path: str) -> Path:
    path = (ROOT / raw_path).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise ValueError("path escapes project root")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(raw_path)
    return path


def providers() -> list[dict]:
    return [
        {
            "id": "local-planner",
            "name": "本地规划器",
            "configured": True,
            "model": "本地规则",
            "notes": "本地规则助手，可创建任务、完成任务和列出下一步。",
        },
        {
            "id": "openai-responses",
            "name": "OpenAI Responses",
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": DEFAULT_MODEL,
            "notes": "使用 OPENAI_API_KEY 和 LLM_TODO_MODEL。",
        },
        {
            "id": "agent-chat",
            "name": "同层 Agent Chat",
            "configured": bool(AGENT_CHAT_BASE_URL),
            "model": AGENT_CHAT_BASE_URL or "未配置",
            "notes": "转发到 ../llm_agent_chat，后续适合用 git/submodule 引入。",
        },
    ]


def stats() -> dict:
    tasks = load_tasks()
    history = load_history()
    all_tasks = tasks + history
    active = [task for task in tasks if task.get("status") == "active"]
    by_horizon: dict[str, int] = {}
    by_area: dict[str, int] = {}
    for task in all_tasks:
        by_horizon[task.get("horizon", "week")] = by_horizon.get(task.get("horizon", "week"), 0) + 1
        by_area[task.get("area", "life")] = by_area.get(task.get("area", "life"), 0) + 1
    return {
        "total": len(all_tasks),
        "tasks": len(all_tasks),
        "current": len(tasks),
        "history": len(history),
        "active": len(active),
        "done": len([task for task in history if task.get("status") == "done"]),
        "dropped": len([task for task in history if task.get("status") == "dropped"]),
        "planningDocs": len(doc_records()),
        "byHorizon": by_horizon,
        "byArea": by_area,
        "providers": providers(),
    }


def sorted_tasks(tasks: list[dict]) -> list[dict]:
    return sorted(
        tasks,
        key=lambda task: (
            task.get("status") != "active",
            HORIZON_ORDER.index(task.get("horizon", "week")) if task.get("horizon", "week") in HORIZON_ORDER else 99,
            PRIORITY_ORDER.get(task.get("priority", "medium"), 1),
            task.get("due") or "9999-99-99",
            task.get("created", ""),
        ),
    )


def sorted_history(tasks: list[dict]) -> list[dict]:
    return sorted(tasks, key=lambda task: (task.get("updated", ""), task.get("created", ""), task.get("title", "")), reverse=True)


def state_payload() -> dict:
    tasks = sorted_tasks(load_tasks())
    history = sorted_history(load_history())
    docs = doc_records()
    plans = {}
    for key, path in {
        "lifetime": TODO / "horizons" / "lifetime.md",
        "year": TODO / "horizons" / "year.md",
        "quarter": TODO / "horizons" / "quarter.md",
    }.items():
        if path.exists():
            _, body = split_frontmatter(read_text(path))
            plans[key] = first_summary(body)
    return {"stats": stats(), "tasks": tasks, "history": history, "docs": docs, "plans": plans}


def append_log(line: str) -> None:
    path = TODO / "log.md"
    today = str(datetime.now().date())
    if not path.exists():
        write_markdown(path, {"title": "LLM Todo Log", "kind": "log", "updated": today, "sources": "local", "confidence": "medium"}, "# LLM Todo Log\n")
    text = read_text(path).rstrip()
    text += f"\n- {today}：{line}\n"
    frontmatter, body = split_frontmatter(text)
    frontmatter["updated"] = today
    write_markdown(path, frontmatter, body)


def new_task_id() -> str:
    return "task-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def infer_horizon(text: str) -> str:
    lowered = text.lower()
    if any(key in text for key in ["今天", "今日", "马上"]) or "today" in lowered:
        return "today"
    if any(key in text for key in ["这周", "本周", "周内"]) or "week" in lowered:
        return "week"
    if any(key in text for key in ["这个月", "本月"]) or "month" in lowered:
        return "month"
    if any(key in text for key in ["季度", "本季"]) or "quarter" in lowered:
        return "quarter"
    if any(key in text for key in ["今年", "年度"]) or "year" in lowered:
        return "year"
    if any(key in text for key in ["十年", "长期"]) or "decade" in lowered:
        return "decade"
    if any(key in text for key in ["人生", "一生"]) or "lifetime" in lowered:
        return "lifetime"
    return "week"


def extract_area(text: str) -> str:
    match = re.search(r"(?:领域|area)\s*[:：]\s*([^\s,，。；;#]{1,40})", text, re.I)
    if match:
        return normalize_area(match.group(1))
    match = re.search(r"#area/([\w\-\u4e00-\u9fff]{1,40})", text, re.I)
    if match:
        return normalize_area(match.group(1))
    return ""


def infer_area(text: str) -> str:
    explicit = extract_area(text)
    if explicit:
        return explicit
    lowered = text.lower()
    if any(key in text for key in ["系统", "项目", "代码", "agent", "聊天", "工具"]) or any(key in lowered for key in ["code", "system", "agent"]):
        return "system"
    if any(key in text for key in ["健康", "睡眠", "运动", "关系", "家庭", "生活"]):
        return "life"
    if any(key in text for key in ["学习", "读书", "课程"]):
        return "learning"
    if any(key in text for key in ["工作", "客户", "会议"]):
        return "work"
    return "life"


def extract_tags(text: str) -> list[str]:
    tag_text = re.sub(r"#area/[\w\-\u4e00-\u9fff]{1,40}", "", text, flags=re.I)
    tags = re.findall(r"(?<![\w/])#([\w\-\u4e00-\u9fff]{1,32})", tag_text)
    match = re.search(r"(?:标签|tags?)\s*[:：]\s*([^。；;\n]+)", tag_text, re.I)
    if match:
        tags.extend(re.split(r"[,，、\s]+", match.group(1)))
    return normalize_tags(tags)


def infer_priority(text: str) -> str:
    lowered = text.lower()
    if any(key in text for key in ["紧急", "重要", "高优先级"]) or "urgent" in lowered or "high" in lowered:
        return "high"
    if any(key in text for key in ["不急", "低优先级"]) or "low" in lowered:
        return "low"
    return "medium"


def extract_title(message: str) -> str:
    quoted = re.search(r"[「『“\"]([^」』”\"]{2,120})[」』”\"]", message)
    if quoted:
        return quoted.group(1).strip()
    title = re.sub(r"^(帮我|请|麻烦)?(新增|添加|记录|记一下|安排|创建)(一个)?(todo|待办|任务)?[:：,\s]*", "", message.strip(), flags=re.I)
    title = strip_task_metadata(title)
    title = re.sub(r"(今天|这周|本周|这个月|今年|长期|高优先级|紧急|重要)", "", title).strip(" ，,。.")
    return title[:120] or message.strip()[:120] or "未命名任务"


def strip_task_metadata(text: str) -> str:
    title = str(text).strip()
    title = re.sub(r"(?:领域|area)\s*[:：]\s*[^\s,，。；;#]{1,40}", "", title, flags=re.I)
    title = re.sub(r"#area/[\w\-\u4e00-\u9fff]{1,40}", "", title, flags=re.I)
    title = re.sub(r"(?:标签|tags?)\s*[:：]\s*[^。；;\n]+", "", title, flags=re.I)
    title = re.sub(r"(?<![\w/])#[\w\-\u4e00-\u9fff]{1,32}", "", title)
    return title.strip(" ，,。.")


def create_task_from_message(message: str) -> dict:
    today = str(datetime.now().date())
    title = extract_title(message)
    horizon = infer_horizon(message)
    return {
        "id": new_task_id(),
        "title": title,
        "status": "active",
        "horizon": horizon,
        "area": infer_area(message),
        "priority": infer_priority(message),
        "tags": extract_tags(message),
        "due": today if horizon == "today" else "",
        "nextAction": "明确下一步动作" if len(title) < 12 else title,
        "notes": "由聊天创建。",
        "created": today,
        "updated": today,
    }


def complete_matching_task(message: str) -> dict | None:
    tasks = load_tasks()
    active = [task for task in tasks if task.get("status") == "active"]
    needle = re.sub(r"(完成|做完|done|finish|了|这个|任务|把)", "", message, flags=re.I).strip()
    target = None
    if needle:
        for task in active:
            if needle in task.get("title", ""):
                target = task
                break
    if target is None and len(active) == 1:
        target = active[0]
    if target is None:
        return None
    today = str(datetime.now().date())
    for task in tasks:
        if task["id"] == target["id"]:
            task["status"] = "done"
            task["updated"] = today
            target = task
            break
    save_tasks(tasks)
    append_log(f"完成任务：{target['title']}")
    return target


def next_actions(limit: int = 5) -> list[dict]:
    active = [task for task in sorted_tasks(load_tasks()) if task.get("status") == "active"]
    return active[:limit]


def local_chat(payload: dict) -> dict:
    messages = payload.get("messages") or []
    last = str(messages[-1].get("content", "") if messages else "").strip()
    operations = []
    lowered = last.lower()
    create_keywords = ["新增", "添加", "记一下", "记录", "安排", "创建", "todo", "待办"]
    done_keywords = ["完成", "做完", "done", "finish"]

    if any(key in last for key in create_keywords):
        tasks = load_tasks()
        task = create_task_from_message(last)
        tasks.append(task)
        save_tasks(tasks)
        append_log(f"新增任务：{task['title']}（{task['horizon']} / {task['area']}）")
        operations.append({"type": "create_task", "task": task})
        text = f"已新增任务：{task['title']}\n时间尺度：{task['horizon']}；领域：{task['area']}；优先级：{task['priority']}。\n下一步：{task['nextAction']}"
    elif any(key in last for key in done_keywords):
        task = complete_matching_task(last)
        if task:
            operations.append({"type": "update_task", "id": task["id"], "status": "done"})
            text = f"已标记完成：{task['title']}。"
        else:
            text = "我没有找到明确匹配的活跃任务。可以说“完成 任务标题的一部分”。"
    elif any(key in last for key in ["下一步", "今天", "现在", "next", "优先"]):
        actions = next_actions()
        if actions:
            lines = [f"{idx + 1}. {task['title']}（{task['horizon']} / {task['priority']}）- {task.get('nextAction') or '补充下一步'}" for idx, task in enumerate(actions)]
            text = "建议先看这些下一步：\n" + "\n".join(lines)
        else:
            text = "当前没有进行中的任务。可以先把收集箱里的承诺变成一个具体下一步。"
    elif any(key in last for key in ["长期", "人生", "规划", "年度", "十年", "方向"]):
        text = (
            "我会把这个当作 horizon 讨论，而不是直接塞进待办。\n"
            "建议先回答三件事：1. 哪个时间尺度变化了；2. 新约束是什么；3. 本周是否需要一个真实 next action。"
        )
    else:
        current = next_actions(3)
        text = (
            "我已读取当前任务和规划上下文。你可以让我新增任务、完成任务、列下一步，或讨论长期规划。\n"
            f"当前进行中的任务 {len([t for t in load_tasks() if t.get('status') == 'active'])} 个。"
        )
        if current:
            text += "\n当前最靠前的任务：" + "；".join(task["title"] for task in current)
    return {"text": text, "provider": "local-planner", "model": "deterministic-rules", "operations": operations}


def context_package(messages: list[dict]) -> dict:
    docs = {}
    for key, path in {
        "index": TODO / "index.md",
        "lifetime": TODO / "horizons" / "lifetime.md",
        "year": TODO / "horizons" / "year.md",
        "quarter": TODO / "horizons" / "quarter.md",
    }.items():
        if path.exists():
            _, body = split_frontmatter(read_text(path))
            docs[key] = body[:4000]
    for path in sorted((TODO / "areas").glob("*.md")):
        _, body = split_frontmatter(read_text(path))
        docs[f"area:{path.stem}"] = body[:4000]
    return {
        "system": (
            "你是 LLM Todo 规划助手。必须区分人生规划尺度和具体任务。"
            "需要变更时返回包含 reply 和安全 operations 的 JSON。"
        ),
        "tasks": load_tasks(),
        "history": sorted_history(load_history())[:30],
        "planningDocs": docs,
        "messages": messages[-16:],
        "operationSchema": {
            "reply": "string",
            "operations": [
                {"type": "create_task", "title": "string", "horizon": "week", "area": "custom area", "priority": "medium", "tags": ["string"], "nextAction": "string", "notes": "string"},
                {"type": "update_task", "id": "task id", "status": "active|waiting|done|dropped", "tags": ["string"], "nextAction": "string"},
                {"type": "append_log", "content": "string"},
            ],
        },
    }


def openai_chat(payload: dict) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置")
    package = context_package(payload.get("messages") or [])
    prompt = json.dumps(package, ensure_ascii=False, indent=2)
    data = json.dumps({"model": DEFAULT_MODEL, "input": prompt}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = json.loads(response.read().decode("utf-8"))
    text = raw.get("output_text", "")
    if not text:
        chunks = []
        for item in raw.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    chunks.append(content.get("text", ""))
        text = "\n".join(chunks).strip()
    result = apply_model_json(text)
    result["provider"] = "openai-responses"
    result["model"] = DEFAULT_MODEL
    result["rawText"] = text
    return result


def agent_chat_forward(payload: dict) -> dict:
    if not AGENT_CHAT_BASE_URL:
        raise RuntimeError("AGENT_CHAT_BASE_URL 未配置")
    messages = payload.get("messages") or []
    package_note = "LLM Todo 上下文包：\n" + json.dumps(context_package(messages), ensure_ascii=False)[:12000]
    forwarded = {
        "provider": payload.get("agentProvider") or "local-echo",
        "contextId": "llm-todo",
        "messages": [{"role": "user", "content": package_note}, *messages[-8:]],
    }
    data = json.dumps(forwarded, ensure_ascii=False).encode("utf-8")
    raw = agent_chat_stream_request(data)
    return {
        "text": raw.get("text", ""),
        "provider": "agent-chat",
        "model": raw.get("model", ""),
        "operations": [],
        "toolRequests": raw.get("toolRequests", []),
    }


def agent_chat_stream_request(data: bytes) -> dict:
    request = urllib.request.Request(
        f"{AGENT_CHAT_BASE_URL}/api/chat/stream",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8")
        done = {}
        for block in text.split("\n\n"):
            lines = block.splitlines()
            event = ""
            payload = ""
            for line in lines:
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload += line[5:].strip()
            if event == "done" and payload:
                done = json.loads(payload)
            elif event == "error" and payload:
                raise RuntimeError(json.loads(payload).get("error", "Agent Chat stream error"))
        if done:
            return done
    except Exception:
        fallback = urllib.request.Request(
            f"{AGENT_CHAT_BASE_URL}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(fallback, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    return {"text": "", "model": "", "toolRequests": []}


def apply_model_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"text": text, "operations": []}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"text": text, "operations": []}
    operations = apply_operations(payload.get("operations", []))
    return {"text": payload.get("reply", text), "operations": operations}


def apply_operations(operations: list[dict]) -> list[dict]:
    applied = []
    tasks = load_tasks()
    today = str(datetime.now().date())
    changed = False
    for op in operations:
        kind = op.get("type")
        if kind == "create_task":
            task = {
                "id": new_task_id(),
                "title": str(op.get("title", "未命名任务"))[:160],
                "status": "active",
                "horizon": op.get("horizon") if op.get("horizon") in HORIZON_ORDER else "week",
                "area": normalize_area(op.get("area"), "life"),
                "priority": op.get("priority") if op.get("priority") in {"high", "medium", "low"} else "medium",
                "tags": normalize_tags(op.get("tags")),
                "due": str(op.get("due", ""))[:20],
                "nextAction": str(op.get("nextAction", ""))[:220],
                "notes": str(op.get("notes", ""))[:500],
                "created": today,
                "updated": today,
            }
            tasks.append(task)
            applied.append({"type": "create_task", "task": task})
            changed = True
        elif kind == "update_task":
            for task in tasks:
                if task.get("id") == op.get("id"):
                    if op.get("status") in {"active", "waiting", "done", "dropped"}:
                        task["status"] = op["status"]
                    if "nextAction" in op:
                        task["nextAction"] = str(op.get("nextAction", ""))[:220]
                    if "tags" in op:
                        task["tags"] = normalize_tags(op.get("tags"))
                    if "area" in op:
                        task["area"] = normalize_area(op.get("area"), task.get("area", "life"))
                    task["updated"] = today
                    applied.append({"type": "update_task", "id": task["id"], "status": task["status"]})
                    changed = True
                    break
        elif kind == "append_log":
            content = str(op.get("content", "")).strip()
            if content:
                append_log(content[:500])
                applied.append({"type": "append_log"})
    if changed:
        save_tasks(tasks)
    return applied


def dispatch_chat(payload: dict) -> dict:
    provider = str(payload.get("provider") or "local-planner")
    start = time.time()
    if provider == "openai-responses":
        result = openai_chat(payload)
    elif provider == "agent-chat":
        result = agent_chat_forward(payload)
    else:
        result = local_chat(payload)
    result["latencyMs"] = round((time.time() - start) * 1000)
    result["state"] = state_payload()
    return result


def create_task(payload: dict) -> dict:
    today = str(datetime.now().date())
    raw_title = str(payload.get("title", "未命名任务")).strip()
    title = strip_task_metadata(raw_title)[:160] or raw_title[:160] or "未命名任务"
    task = {
        "id": new_task_id(),
        "title": title,
        "status": str(payload.get("status", "active")) if payload.get("status") in {"active", "waiting", "done", "dropped"} else "active",
        "horizon": payload.get("horizon") if payload.get("horizon") in HORIZON_ORDER else infer_horizon(raw_title),
        "area": normalize_area(payload.get("area"), infer_area(raw_title)),
        "priority": payload.get("priority") if payload.get("priority") in {"high", "medium", "low"} else infer_priority(title),
        "tags": normalize_tags(payload.get("tags")) or extract_tags(raw_title),
        "due": str(payload.get("due", "")).strip()[:20],
        "nextAction": str(payload.get("nextAction", "")).strip()[:220],
        "notes": str(payload.get("notes", "")).strip()[:500],
        "created": today,
        "updated": today,
    }
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    append_log(f"新增任务：{task['title']}（手动）")
    return {"task": task, "state": state_payload()}


def update_task(payload: dict) -> dict:
    task_id = str(payload.get("id", ""))
    tasks = load_tasks()
    history = load_history()
    today = str(datetime.now().date())
    updated = None
    source = "tasks"
    for task in tasks:
        if task.get("id") != task_id:
            continue
        updated = task
        break
    if updated is None:
        source = "history"
        for task in history:
            if task.get("id") == task_id:
                updated = task
                break
    if not updated:
        raise ValueError("task not found")

    for key in ("title", "nextAction", "notes", "due"):
        if key in payload:
            updated[key] = str(payload.get(key, "")).strip()
    if "area" in payload:
        updated["area"] = normalize_area(payload.get("area"), updated.get("area", "life"))
    if "tags" in payload:
        updated["tags"] = normalize_tags(payload.get("tags"))
    if payload.get("status") in TASK_STATUSES:
        updated["status"] = payload["status"]
    if payload.get("horizon") in HORIZON_ORDER:
        updated["horizon"] = payload["horizon"]
    if payload.get("priority") in {"high", "medium", "low"}:
        updated["priority"] = payload["priority"]
    updated["updated"] = today

    if source == "history":
        history = [task for task in history if task.get("id") != task_id]
        if updated["status"] in CURRENT_STATUSES:
            tasks.append(updated)
        else:
            history.append(updated)
        save_history(history)
        save_tasks(tasks)
    else:
        save_tasks(tasks)
    append_log(f"更新任务：{updated['title']} → {updated['status']}")
    return {"task": updated, "state": state_payload()}


def file_lines(path: Path) -> int:
    return len(read_text(path).splitlines()) if path.exists() else 0


def directory_tree() -> str:
    return """llm_todo/
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
    design.js"""


def design_payload() -> dict:
    files = [
        ("scripts/llm_todo_server.py", "本地 HTTP API、任务读写、聊天分发、OpenAI/Agent Chat 边界、设计数据"),
        ("web/index.html", "任务规划工作台结构，首屏含任务、规划尺度和聊天窗口"),
        ("web/design.html", "设计文档网站结构"),
        ("web/styles.css", "中文任务工作台视觉系统和响应式布局"),
        ("web/shared.js", "API 客户端和 Markdown 渲染器"),
        ("web/app.js", "任务列表、文档阅读、聊天、模型提供方选择和快速创建交互"),
        ("web/design.js", "设计图、风险图、职责表和评审历史"),
        ("data/tasks.json", "当前任务事实源，只保存 active/waiting"),
        ("data/history.json", "已完成和已放弃任务归档"),
        ("schema/AGENTS.md", "LLM 维护规则"),
        ("schema/task.schema.json", "任务字段约束"),
        ("docs/design.md", "系统设计文档"),
        ("docs/review.md", "严格设计评审"),
        ("todo/index.md", "规划入口"),
        ("todo/log.md", "规划与任务变更日志"),
    ]
    return {
        "stats": stats(),
        "architecture": [
            "raw/ 保存未整理输入，避免聊天材料丢失。",
            "data/tasks.json 是当前任务事实源，data/history.json 保存已完成和已放弃任务。",
            "todo/ 保存时间尺度、领域、日志和评审，是 LLM 维护的解释层。",
            "scripts/llm_todo_server.py 暴露本地 API，并把聊天消息转成安全变更操作。",
            "web/ 提供任务工作台和设计文档网站；聊天窗口是主入口。",
            "../llm_agent_chat 是通用聊天和模型提供方模块，后续可以作为 git 依赖引入。",
        ],
        "diagrams": {
            "dataFlow": ["聊天或快速编辑", "服务端组装上下文", "任务和规划文档", "本地或外部模型提供方", "安全变更操作", "写入 JSON 和 Markdown", "工作台重新渲染"],
            "stateFlow": ["收集箱", "候选任务", "进行中", "等待中", "已完成或已放弃", "记录日志"],
            "horizonFlow": ["人生价值", "十年方向", "年度主题", "季度成果", "本周下一步", "今天执行"],
            "requestResponse": ["浏览器打开首页", "请求 /api/state", "渲染工作台", "提交 /api/chat", "组装任务上下文", "应用安全操作", "返回最新状态"],
            "codeDeps": [
                {"from": "web/app.js", "to": "scripts/llm_todo_server.py", "label": "/api/state /api/chat /api/tasks/update"},
                {"from": "scripts/llm_todo_server.py", "to": "data/tasks.json", "label": "读写当前任务事实源"},
                {"from": "scripts/llm_todo_server.py", "to": "data/history.json", "label": "归档 done/dropped 任务"},
                {"from": "scripts/llm_todo_server.py", "to": "todo/", "label": "读取规划文档并追加日志或评审"},
                {"from": "scripts/llm_todo_server.py", "to": "../llm_agent_chat", "label": "可选转发 AGENT_CHAT_BASE_URL"},
                {"from": "scripts/llm_todo_server.py", "to": "OpenAI Responses API", "label": "可选模型提供方"},
            ],
            "riskMap": [
                {"level": "严重", "risk": "长期规划被误拆成大量短期任务", "mitigation": "保持规划尺度与任务分层，普通聊天不自动重写人生尺度页面"},
                {"level": "高", "risk": "聊天写入误改任务事实源", "mitigation": "只支持白名单变更操作，并保留日志"},
                {"level": "高", "risk": "模型提供方适配污染 todo 业务", "mitigation": "通用适配器放到同层 llm_agent_chat"},
                {"level": "中", "risk": "本地规则助手能力有限", "mitigation": "UI 明确提供方状态，可接 OpenAI 或 Agent Chat"},
            ],
        },
        "directoryTree": directory_tree(),
        "files": [{"path": path, "lines": file_lines(ROOT / path), "responsibility": responsibility} for path, responsibility in files],
        "designMarkdown": split_frontmatter(read_text(DOCS / "design.md"))[1],
    }


def review_payload() -> dict:
    path = DOCS / "review.md"
    return {"review": split_frontmatter(read_text(path))[1] if path.exists() else ""}


def review_history() -> dict:
    items = []
    for path in sorted(REVIEW_DIR.glob("*.md"), reverse=True):
        text = read_text(path)
        frontmatter, body = split_frontmatter(text)
        items.append({"path": rel(path), "title": title_for(path, body, frontmatter), "updated": frontmatter.get("updated", ""), "summary": first_summary(body), "lines": file_lines(path)})
    return {"reviews": items[:40]}


def save_review(payload: dict) -> dict:
    content = str(payload.get("content", "")).strip() or "# 设计评审\n\n未填写。"
    title = str(payload.get("title", "")).strip() or "LLM Todo 设计评审"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
    target = REVIEW_DIR / f"{stamp}-{digest}.md"
    write_markdown(
        target,
        {"title": title, "kind": "review", "updated": str(datetime.now().date()), "sources": "/design/", "confidence": "medium"},
        content,
    )
    return {"saved": rel(target)}


def safe_web_path(path: str) -> Path:
    if path == "/":
        return WEB / "index.html"
    if path == "/design/":
        return WEB / "design.html"
    target = (WEB / path.lstrip("/")).resolve()
    if WEB not in target.parents and target != WEB:
        raise ValueError("path escapes web root")
    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "LLMTodo/0.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.send_json({"ok": True, "root": str(ROOT), "stats": stats()})
            elif parsed.path == "/api/state":
                self.send_json(state_payload())
            elif parsed.path == "/api/stats":
                self.send_json(stats())
            elif parsed.path == "/api/tasks":
                self.send_json({"tasks": sorted_tasks(load_tasks())})
            elif parsed.path == "/api/history":
                self.send_json({"tasks": sorted_history(load_history())})
            elif parsed.path == "/api/docs":
                self.send_json({"docs": doc_records()})
            elif parsed.path == "/api/doc":
                target = safe_project_path(query.get("path", [""])[0])
                frontmatter, body = split_frontmatter(read_text(target))
                self.send_json({"path": rel(target), "frontmatter": frontmatter, "markdown": body})
            elif parsed.path == "/api/design":
                self.send_json(design_payload())
            elif parsed.path == "/api/review":
                self.send_json(review_payload())
            elif parsed.path == "/api/reviews":
                self.send_json(review_history())
            else:
                self.send_file(safe_web_path(parsed.path))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        size = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
            if parsed.path == "/api/chat":
                self.send_json(dispatch_chat(payload))
            elif parsed.path == "/api/tasks/create":
                self.send_json(create_task(payload))
            elif parsed.path == "/api/tasks/update":
                self.send_json(update_task(payload))
            elif parsed.path == "/api/review/save":
                self.send_json(save_review(payload))
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    port = int(os.environ.get("LLM_TODO_PORT", "8720"))
    host = os.environ.get("LLM_TODO_HOST", "127.0.0.1")
    DATA.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
