#!/usr/bin/env python3
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import calendar
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
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
CAPABILITIES_PATH = DATA / "capabilities.json"
AGENTS_PATH = DATA / "agents.json"
ROADMAP_PATH = DATA / "roadmap.json"
SKILL_TREE_PATH = DATA / "skill_tree.json"
BACKUP_DIR = DATA / "backups"

BASE_PATH = os.environ.get("LLM_TODO_BASE_PATH", "").rstrip("/")
DEFAULT_MODEL = os.environ.get("LLM_TODO_MODEL", "gpt-5.4-mini")
AGENT_CHAT_BASE_URL = os.environ.get("AGENT_CHAT_BASE_URL", "").rstrip("/")
AUTH_TOKEN = os.environ.get("LLM_TODO_TOKEN", "").strip()

# LLM Provider 配置
OPENAI_COMPAT_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
OPENAI_COMPAT_BASE_URL = os.environ.get("OPENAI_COMPAT_BASE_URL", "https://api.deepseek.com/v1")
OPENAI_COMPAT_MODEL = os.environ.get("OPENAI_COMPAT_MODEL", "deepseek-chat")

GLM_API_KEY = os.environ.get("GLM_API_KEY", "73a397915e3646f9ab9d9ed7cfd04611.CXQiVkPOEqkuTe1G")
GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4-flash")

REMOTE_SYNC_URL = os.environ.get("LLM_TODO_REMOTE_SYNC_URL", "").rstrip("/")
REMOTE_SYNC_TOKEN = os.environ.get("LLM_TODO_REMOTE_SYNC_TOKEN", "").strip()

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
REPEAT_OPTIONS = {"daily", "weekly", "monthly", "quarterly", "yearly"}
CURRENT_STATUSES = {"active", "waiting"}
ARCHIVE_STATUSES = {"done", "dropped"}
TASK_STATUSES = CURRENT_STATUSES | ARCHIVE_STATUSES
TASK_TYPES = {"personal", "agent", "review", "discuss"}
TASK_SUB_STATUSES = {"pending", "in_progress", "submitted"}
DATA_FILES = {TASKS_PATH, HISTORY_PATH, CAPABILITIES_PATH, AGENTS_PATH, ROADMAP_PATH, SKILL_TREE_PATH}
DATA_WRITE_CONTEXT = threading.local()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def read_json_object(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return dict(fallback)
    payload = json.loads(read_text(path))
    return payload if isinstance(payload, dict) else dict(fallback)


def write_json_object(path: Path, payload: dict, label: str) -> None:
    with data_change(label):
        ensure_data_backup(path)
        write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def clean_label(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")[:40] or "change"


def backup_paths() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(path for path in BACKUP_DIR.iterdir() if path.is_dir())


def prune_backups() -> None:
    for path in backup_paths()[:-10]:
        shutil.rmtree(path, ignore_errors=True)


def create_backup_snapshot(label: str = "change") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = BACKUP_DIR / f"{stamp}-{clean_label(label)}"
    target.mkdir(parents=True, exist_ok=False)
    for source in sorted(DATA_FILES, key=lambda item: item.name):
        if source.exists():
            shutil.copy2(source, target / source.name)
        else:
            (target / f"{source.name}.missing").write_text("", encoding="utf-8")
    metadata = {"created": datetime.now().isoformat(timespec="seconds"), "label": label}
    (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prune_backups()
    return target


@contextmanager
def data_change(label: str = "change"):
    depth = getattr(DATA_WRITE_CONTEXT, "depth", 0)
    if depth == 0:
        DATA_WRITE_CONTEXT.label = label
        DATA_WRITE_CONTEXT.snapshot = None
    DATA_WRITE_CONTEXT.depth = depth + 1
    try:
        yield
    finally:
        DATA_WRITE_CONTEXT.depth -= 1
        if DATA_WRITE_CONTEXT.depth == 0:
            DATA_WRITE_CONTEXT.label = ""
            DATA_WRITE_CONTEXT.snapshot = None


def ensure_data_backup(path: Path) -> None:
    if path not in DATA_FILES:
        return
    depth = getattr(DATA_WRITE_CONTEXT, "depth", 0)
    if depth > 0:
        if getattr(DATA_WRITE_CONTEXT, "snapshot", None) is None:
            DATA_WRITE_CONTEXT.snapshot = create_backup_snapshot(getattr(DATA_WRITE_CONTEXT, "label", "change"))
        return
    create_backup_snapshot(f"write-{path.stem}")


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


def normalize_repeat(value: object) -> str:
    repeat = str(value if value is not None else "").strip().lower()
    return repeat if repeat in REPEAT_OPTIONS else ""


def normalize_task_type(value: object) -> str:
    task_type = str(value if value is not None else "").strip().lower()
    return task_type if task_type in TASK_TYPES else "personal"


def normalize_sub_status(value: object) -> str:
    sub_status = str(value if value is not None else "").strip().lower()
    return sub_status if sub_status in TASK_SUB_STATUSES else "pending"


def parse_iso_date(value: object) -> date | None:
    text = str(value if value is not None else "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def advance_repeat_once(day: date, repeat: str) -> date:
    if repeat == "daily":
        return day + timedelta(days=1)
    if repeat == "weekly":
        return day + timedelta(days=7)
    if repeat == "monthly":
        return add_months(day, 1)
    if repeat == "quarterly":
        return add_months(day, 3)
    if repeat == "yearly":
        return add_months(day, 12)
    return day


def next_repeat_due(current_due: object, repeat: str) -> str:
    today = datetime.now().date()
    base = parse_iso_date(current_due) or today
    next_due = advance_repeat_once(base, repeat)
    while next_due <= today:
        next_due = advance_repeat_once(next_due, repeat)
    return next_due.isoformat()


def next_repeating_task(task: dict) -> dict | None:
    repeat = normalize_repeat(task.get("repeat"))
    if not repeat or task.get("status") != "done":
        return None
    today = str(datetime.now().date())
    next_task = dict(task)
    next_task.update(
        {
            "id": new_task_id(),
            "status": "active",
            "due": next_repeat_due(task.get("due"), repeat),
            "created": today,
            "updated": today,
        }
    )
    return normalize_task(next_task)


def normalize_task(task: dict, default_status: str = "active") -> dict:
    today = str(datetime.now().date())
    status = task.get("status") if task.get("status") in TASK_STATUSES else default_status
    horizon = task.get("horizon") if task.get("horizon") in HORIZON_ORDER else "week"
    priority = task.get("priority") if task.get("priority") in PRIORITY_ORDER else "medium"
    return {
        "id": clean_text(task.get("id"), 80, new_task_id()),
        "title": clean_text(task.get("title"), 160, "未命名任务"),
        "status": status,
        "type": normalize_task_type(task.get("type")),
        "assignee": clean_text(task.get("assignee"), 80),
        "subStatus": normalize_sub_status(task.get("subStatus")),
        "horizon": horizon,
        "area": normalize_area(task.get("area"), "life"),
        "priority": priority,
        "tags": normalize_tags(task.get("tags")),
        "due": clean_text(task.get("due"), 20),
        "nextAction": clean_text(task.get("nextAction"), 220),
        "notes": clean_text(task.get("notes"), 500),
        "repeat": normalize_repeat(task.get("repeat")),
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
        with data_change("migrate-archived-tasks"):
            write_tasks_file(TASKS_PATH, current)
            append_history(archived)
    return current


def save_tasks(tasks: list[dict]) -> None:
    current: list[dict] = []
    archived: list[dict] = []
    repeated: list[dict] = []
    for raw_task in tasks:
        task = normalize_task(raw_task)
        if task["status"] in ARCHIVE_STATUSES:
            archived.append(task)
            next_task = next_repeating_task(task)
            if next_task:
                repeated.append(next_task)
        else:
            current.append(task)
    current.extend(repeated)
    with data_change("save-tasks"):
        write_tasks_file(TASKS_PATH, current)
        if archived:
            append_history(archived)


def write_tasks_file(path: Path, tasks: list[dict]) -> None:
    ensure_data_backup(path)
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
    with data_change("save-history"):
        write_tasks_file(HISTORY_PATH, list(unique.values()))


def append_history(tasks: list[dict]) -> None:
    history = {task["id"]: task for task in load_history_raw()}
    for raw_task in tasks:
        task = normalize_task(raw_task, "done")
        if task["status"] not in ARCHIVE_STATUSES:
            task["status"] = "done"
        history[task["id"]] = task
    with data_change("append-history"):
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
            "id": "openai-compat",
            "name": "OpenAI 兼容 (DeepSeek)",
            "configured": bool(OPENAI_COMPAT_API_KEY),
            "model": OPENAI_COMPAT_MODEL,
            "notes": f"使用 OPENAI_COMPAT_BASE_URL，默认 {OPENAI_COMPAT_MODEL}。",
            "streaming": True,
        },
        {
            "id": "glm",
            "name": "GLM (智谱清言)",
            "configured": bool(GLM_API_KEY),
            "model": GLM_MODEL,
            "notes": f"使用智谱 API，模型 {GLM_MODEL}。",
            "streaming": True,
        },
        {
            "id": "agent-chat",
            "name": "同层 Agent Chat",
            "configured": bool(AGENT_CHAT_BASE_URL),
            "model": AGENT_CHAT_BASE_URL or "未配置",
            "notes": "转发到 ../llm_agent_chat，后续适合用 git/submodule 引入。",
        },
    ]


def capabilities_payload() -> dict:
    payload = read_json_object(CAPABILITIES_PATH, {"domains": []})
    payload["domains"] = [domain for domain in payload.get("domains", []) if isinstance(domain, dict)]
    return payload


def agents_payload() -> dict:
    payload = read_json_object(AGENTS_PATH, {"agents": []})
    agents = [agent for agent in payload.get("agents", []) if isinstance(agent, dict) and "token" not in agent]
    return {"agents": agents}


def load_agents() -> dict:
    payload = read_json_object(AGENTS_PATH, {"agents": [], "sessions": {}})
    raw_accounts = payload.get("accounts")
    if not isinstance(raw_accounts, list):
        candidate_agents = payload.get("agents", [])
        raw_accounts = candidate_agents if isinstance(candidate_agents, list) and any(isinstance(agent, dict) and "token" in agent for agent in candidate_agents) else []

    accounts: list[dict] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for raw_agent in raw_accounts:
        if not isinstance(raw_agent, dict):
            continue
        name = clean_text(raw_agent.get("name"), 80)
        token = clean_text(raw_agent.get("token"), 512)
        if not name or not token:
            continue
        agent_id = clean_text(raw_agent.get("id"), 80) or f"agent-{uuid.uuid4().hex[:10]}"
        marker = name.lower()
        if marker in seen_names or agent_id in seen_ids:
            continue
        accounts.append(
            {
                "id": agent_id,
                "name": name,
                "token": token,
                "created": clean_text(raw_agent.get("created"), 30, str(datetime.now().date())),
            }
        )
        seen_names.add(marker)
        seen_ids.add(agent_id)

    raw_sessions = payload.get("sessions", {})
    sessions = raw_sessions if isinstance(raw_sessions, dict) else {}
    sessions = {str(jwt): session for jwt, session in sessions.items() if isinstance(session, dict)}
    return {"agents": accounts, "sessions": sessions}


def save_agents(data: dict) -> None:
    payload = read_json_object(AGENTS_PATH, {"agents": []})
    accounts = [agent for agent in data.get("agents", []) if isinstance(agent, dict)]
    sessions = data.get("sessions", {})
    payload["accounts"] = accounts
    payload["sessions"] = sessions if isinstance(sessions, dict) else {}
    write_json_object(AGENTS_PATH, payload, "save-agent-accounts")


def unique_agent_id(name: str, existing: list[dict], preferred: object = "") -> str:
    used = {str(agent.get("id", "")) for agent in existing}
    preferred_id = clean_text(preferred, 80)
    if preferred_id and preferred_id not in used:
        return preferred_id
    base = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "agent"
    candidate = base[:48]
    while candidate in used:
        candidate = f"{base[:40]}-{uuid.uuid4().hex[:6]}"
    return candidate


def create_agent_account(payload: dict) -> dict:
    data = load_agents()
    name = clean_text(payload.get("name"), 80)
    if not name:
        raise ValueError("agent name is required")
    if any(agent.get("name", "").lower() == name.lower() for agent in data["agents"]):
        raise ValueError("agent already exists")
    token = clean_text(payload.get("token"), 512) or uuid.uuid4().hex
    agent = {
        "id": unique_agent_id(name, data["agents"], payload.get("id")),
        "name": name,
        "token": token,
        "created": str(datetime.now().date()),
    }
    data["agents"].append(agent)
    save_agents(data)
    return agent


def verify_agent(name: object, token: object) -> dict | None:
    clean_name = clean_text(name, 80)
    clean_token = clean_text(token, 512)
    if not clean_name or not clean_token:
        return None
    for agent in load_agents()["agents"]:
        if agent.get("name") == clean_name and hmac.compare_digest(str(agent.get("token", "")), clean_token):
            return {"id": agent["id"], "name": agent["name"]}
    return None


def jwt_secret() -> bytes:
    secret = os.environ.get("LLM_TODO_JWT_SECRET", "").strip() or AUTH_TOKEN or "llm-todo-local-secret"
    return secret.encode("utf-8")


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_agent_jwt(message: str) -> str:
    return b64url_encode(hmac.new(jwt_secret(), message.encode("utf-8"), hashlib.sha256).digest())


def create_agent_session(agent: dict) -> str:
    header = b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = b64url_encode(
        json.dumps(
            {"sub": agent["id"], "name": agent["name"], "iat": int(time.time()), "jti": uuid.uuid4().hex},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    message = f"{header}.{payload}"
    jwt = f"{message}.{sign_agent_jwt(message)}"
    data = load_agents()
    data["sessions"][jwt] = {"agentId": agent["id"], "created": datetime.now().isoformat(timespec="seconds")}
    save_agents(data)
    return jwt


def verify_agent_jwt(jwt: str) -> dict | None:
    parts = jwt.split(".")
    if len(parts) != 3:
        return None
    message = ".".join(parts[:2])
    if not hmac.compare_digest(sign_agent_jwt(message), parts[2]):
        return None
    data = load_agents()
    session = data["sessions"].get(jwt)
    if not isinstance(session, dict):
        return None
    try:
        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    agent_id = str(payload.get("sub", ""))
    if session.get("agentId") != agent_id:
        return None
    for agent in data["agents"]:
        if agent.get("id") == agent_id:
            return {"id": agent["id"], "name": agent["name"]}
    return None


def delete_agent_account(name: str) -> dict | None:
    data = load_agents()
    removed = None
    remaining = []
    for agent in data["agents"]:
        if agent.get("name") == name:
            removed = agent
        else:
            remaining.append(agent)
    if not removed:
        return None
    data["agents"] = remaining
    data["sessions"] = {jwt: session for jwt, session in data["sessions"].items() if session.get("agentId") != removed["id"]}
    save_agents(data)
    return removed


def roadmap_payload() -> dict:
    payload = read_json_object(ROADMAP_PATH, {"milestones": [], "openQuestions": [], "updated": ""})
    payload["milestones"] = [milestone for milestone in payload.get("milestones", []) if isinstance(milestone, dict)]
    open_questions = payload.get("openQuestions", [])
    payload["openQuestions"] = open_questions if isinstance(open_questions, list) else []
    payload["updated"] = str(payload.get("updated", ""))
    return payload


def find_by_id(items: list[dict], item_id: str) -> dict | None:
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def update_capability(domain_id: str, payload: dict) -> dict | None:
    data = capabilities_payload()
    incoming = payload.get("domain") if isinstance(payload.get("domain"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    for index, domain in enumerate(data["domains"]):
        if domain.get("id") != domain_id:
            continue
        updated = _deep_merge(domain, incoming)
        updated["id"] = domain_id
        updated["updated"] = str(datetime.now().date())
        data["domains"][index] = updated
        write_json_object(CAPABILITIES_PATH, data, "update-capability")
        return updated
    return None


def update_agent_status(agent_id: str, payload: dict) -> dict | None:
    data = read_json_object(AGENTS_PATH, {"agents": []})
    data["agents"] = [agent for agent in data.get("agents", []) if isinstance(agent, dict) and "token" not in agent]
    incoming = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    for index, agent in enumerate(data["agents"]):
        if agent.get("id") != agent_id:
            continue
        updated = _deep_merge(agent, incoming)
        updated["id"] = agent_id
        data["agents"][index] = updated
        write_json_object(AGENTS_PATH, data, "update-agent-status")
        return updated
    return None


def _merge_by_id(current_list: list, incoming_list: list, id_key: str = "id") -> list:
    """Merge incoming list items into current by id_key. Items present in current
    but absent from incoming are preserved (never deleted)."""
    lookup = {item[id_key]: item for item in incoming_list if isinstance(item, dict) and id_key in item}
    result = []
    for existing in current_list:
        if not isinstance(existing, dict) or id_key not in existing:
            result.append(existing)
            continue
        eid = existing[id_key]
        if eid in lookup:
            merged = _deep_merge(existing, lookup.pop(eid))
            merged[id_key] = eid
            result.append(merged)
        else:
            result.append(existing)
    # append genuinely new items
    for item in lookup.values():
        result.append(item)
    return result


def _deep_merge(current: dict, incoming: dict) -> dict:
    """Recursively merge incoming into current. Lists with id-bearing dicts use
    _merge_by_id; plain scalars/other lists are overwritten."""
    result = dict(current)
    for key, value in incoming.items():
        if key == "updated":
            continue
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        elif (
            isinstance(existing, list)
            and isinstance(value, list)
            and existing
            and isinstance(existing[0], dict)
            and "id" in existing[0]
        ):
            result[key] = _merge_by_id(existing, value)
        else:
            result[key] = value
    return result


def update_roadmap(payload: dict) -> dict:
    incoming = payload.get("roadmap") if isinstance(payload.get("roadmap"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    current = roadmap_payload()
    updated = _deep_merge(current, incoming)
    updated["updated"] = str(datetime.now().date())
    write_json_object(ROADMAP_PATH, updated, "update-roadmap")
    return updated


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


def sync_to_remote(remote_url: str = "", token: str = "") -> dict:
    """Export data and web files to remote server."""
    url = remote_url or REMOTE_SYNC_URL
    tok = token or REMOTE_SYNC_TOKEN
    if not url:
        return {"ok": False, "error": "未配置远程同步地址（LLM_TODO_REMOTE_SYNC_URL）"}

    web_files = []
    for item in WEB.rglob("*"):
        if item.is_file() and item.suffix in {".html", ".js", ".css", ".json", ".png", ".svg", ".ico"}:
            web_files.append({"path": str(item.relative_to(WEB)), "size": item.stat().st_size})

    data_snapshot = {
        "tasks": load_tasks(),
        "history": load_history(),
        "capabilities": capabilities_payload(),
        "agents": agents_payload(),
        "roadmap": roadmap_payload(),
        "skill_tree": skill_tree_payload(),
        "character": character_payload(),
    }

    result = {"ok": True, "web_files": len(web_files), "data_size": len(json.dumps(data_snapshot, ensure_ascii=False))}

    if tok:
        # Push data snapshot to remote server
        try:
            req = urllib.request.Request(
                f"{url}/api/sync/import",
                data=json.dumps({"data": data_snapshot, "web_files": web_files}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {tok}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                remote_result = json.loads(resp.read().decode("utf-8"))
                result["remote"] = remote_result
        except Exception as exc:
            result["remote_error"] = str(exc)

    result["export"] = {
        "web": [f["path"] for f in web_files],
        "data": list(data_snapshot.keys()),
    }
    return result


def state_payload() -> dict:
    tasks = sorted_tasks(load_tasks())
    history = sorted_history(load_history())
    docs = doc_records()
    plans = {}
    for key in HORIZON_ORDER:
        path = TODO / "horizons" / f"{key}.md"
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
        "subStatus": "pending",
        "tags": extract_tags(message),
        "due": today if horizon == "today" else "",
        "nextAction": "明确下一步动作" if len(title) < 12 else title,
        "notes": "由聊天创建。",
        "repeat": "",
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
                {"type": "create_task", "title": "string", "horizon": "week", "area": "custom area", "priority": "medium", "tags": ["string"], "nextAction": "string", "notes": "string", "repeat": ""},
                {"type": "update_task", "id": "task id", "status": "active|waiting|done|dropped", "tags": ["string"], "nextAction": "string", "repeat": ""},
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


def openai_compat_chat(payload: dict) -> dict:
    """OpenAI 兼容接口（支持 DeepSeek 等第三方 Provider）"""
    if not OPENAI_COMPAT_API_KEY:
        raise RuntimeError("OPENAI_COMPAT_API_KEY 未配置")

    messages = payload.get("messages") or []
    package = context_package(messages)
    system_msg = package["system"]
    user_msgs = messages[-16:]

    api_messages = [{"role": "system", "content": system_msg}]
    for msg in user_msgs:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            api_messages.append({"role": role, "content": str(msg.get("content", ""))})

    data = json.dumps({
        "model": OPENAI_COMPAT_MODEL,
        "messages": api_messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{OPENAI_COMPAT_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {OPENAI_COMPAT_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = json.loads(response.read().decode("utf-8"))

    text = ""
    choices = raw.get("choices", [])
    if choices:
        text = choices[0].get("message", {}).get("content", "").strip()

    result = apply_model_json(text)
    result["provider"] = "openai-compat"
    result["model"] = OPENAI_COMPAT_MODEL
    result["rawText"] = text
    return result


def glm_chat(payload: dict) -> dict:
    """GLM (智谱清言) 聊天接口"""
    if not GLM_API_KEY:
        raise RuntimeError("GLM_API_KEY 未配置")

    messages = payload.get("messages") or []
    package = context_package(messages)
    system_msg = package["system"]
    user_msgs = messages[-16:]

    api_messages = [{"role": "system", "content": system_msg}]
    for msg in user_msgs:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            api_messages.append({"role": role, "content": str(msg.get("content", ""))})

    data = json.dumps({
        "model": GLM_MODEL,
        "messages": api_messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{GLM_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {GLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = json.loads(response.read().decode("utf-8"))

    text = ""
    choices = raw.get("choices", [])
    if choices:
        text = choices[0].get("message", {}).get("content", "").strip()

    result = apply_model_json(text)
    result["provider"] = "glm"
    result["model"] = GLM_MODEL
    result["rawText"] = text
    return result


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
                "subStatus": normalize_sub_status(op.get("subStatus")),
                "tags": normalize_tags(op.get("tags")),
                "due": str(op.get("due", ""))[:20],
                "nextAction": str(op.get("nextAction", ""))[:220],
                "notes": str(op.get("notes", ""))[:500],
                "repeat": normalize_repeat(op.get("repeat")),
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
                    if "repeat" in op:
                        task["repeat"] = normalize_repeat(op.get("repeat"))
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
    elif provider == "openai-compat":
        result = openai_compat_chat(payload)
    elif provider == "glm":
        result = glm_chat(payload)
    elif provider == "agent-chat":
        result = agent_chat_forward(payload)
    else:
        result = local_chat(payload)
    result["latencyMs"] = round((time.time() - start) * 1000)
    result["state"] = state_payload()
    return result


def build_api_messages(payload: dict) -> list[dict]:
    """构建发送给 LLM 的 messages 数组"""
    messages = payload.get("messages") or []
    package = context_package(messages)
    system_msg = package["system"]
    user_msgs = messages[-16:]
    api_messages = [{"role": "system", "content": system_msg}]
    for msg in user_msgs:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            api_messages.append({"role": role, "content": str(msg.get("content", ""))})
    return api_messages


def stream_openai_compat(payload: dict):
    """流式调用 OpenAI 兼容接口，yield SSE 格式的 chunk"""
    if not OPENAI_COMPAT_API_KEY:
        yield f"data: {json.dumps({'error': 'OPENAI_COMPAT_API_KEY 未配置'}, ensure_ascii=False)}\n\n"
        return

    api_messages = build_api_messages(payload)
    data = json.dumps({
        "model": OPENAI_COMPAT_MODEL,
        "messages": api_messages,
        "temperature": 0.7,
        "max_tokens": 2048,
        "stream": True,
    }, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{OPENAI_COMPAT_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {OPENAI_COMPAT_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    full_text = ""
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            buffer = ""
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload_str = line[6:]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(payload_str)
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_text += content
                            yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        return

    # 流结束，发送最终状态
    result = apply_model_json(full_text)
    operations = result.get("operations", [])
    result_state = state_payload()
    yield f"data: {json.dumps({'done': True, 'text': full_text, 'operations': operations, 'provider': 'openai-compat', 'model': OPENAI_COMPAT_MODEL, 'state': result_state}, ensure_ascii=False)}\n\n"


def stream_glm(payload: dict):
    """流式调用 GLM 接口，yield SSE 格式的 chunk"""
    if not GLM_API_KEY:
        yield f"data: {json.dumps({'error': 'GLM_API_KEY 未配置'}, ensure_ascii=False)}\n\n"
        return

    api_messages = build_api_messages(payload)
    data = json.dumps({
        "model": GLM_MODEL,
        "messages": api_messages,
        "temperature": 0.7,
        "max_tokens": 2048,
        "stream": True,
    }, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{GLM_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {GLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    full_text = ""
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            buffer = ""
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload_str = line[6:]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk_data = json.loads(payload_str)
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_text += content
                            yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        return

    result = apply_model_json(full_text)
    operations = result.get("operations", [])
    result_state = state_payload()
    yield f"data: {json.dumps({'done': True, 'text': full_text, 'operations': operations, 'provider': 'glm', 'model': GLM_MODEL, 'state': result_state}, ensure_ascii=False)}\n\n"


def dispatch_stream_chat(payload: dict):
    """根据 provider 选择流式生成器"""
    provider = str(payload.get("provider") or "local-planner")
    if provider == "openai-compat":
        return stream_openai_compat(payload)
    elif provider == "glm":
        return stream_glm(payload)
    else:
        # 非 streaming provider 回退到同步方式
        return stream_fallback(payload)


def stream_fallback(payload: dict):
    """同步 provider 的模拟流式输出（一次性发送全部内容）"""
    start = time.time()
    result = dispatch_chat(payload)
    latency = round((time.time() - start) * 1000)
    text = result.get("text", "")

    # 模拟按字符流式输出
    chunk_size = max(1, len(text) // 20)
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'done': True, 'text': text, 'operations': result.get('operations', []), 'provider': result.get('provider', 'local-planner'), 'model': result.get('model', ''), 'latencyMs': latency, 'state': result.get('state', state_payload())}, ensure_ascii=False)}\n\n"


def task_from_payload(payload: dict) -> dict:
    today = str(datetime.now().date())
    raw_title = str(payload.get("title", "未命名任务")).strip()
    title = strip_task_metadata(raw_title)[:160] or raw_title[:160] or "未命名任务"
    return {
        "id": new_task_id(),
        "title": title,
        "status": str(payload.get("status", "active")) if payload.get("status") in {"active", "waiting", "done", "dropped"} else "active",
        "type": normalize_task_type(payload.get("type")),
        "assignee": clean_text(payload.get("assignee"), 80),
        "subStatus": normalize_sub_status(payload.get("subStatus")),
        "horizon": payload.get("horizon") if payload.get("horizon") in HORIZON_ORDER else infer_horizon(raw_title),
        "area": normalize_area(payload.get("area"), infer_area(raw_title)),
        "priority": payload.get("priority") if payload.get("priority") in {"high", "medium", "low"} else infer_priority(title),
        "tags": normalize_tags(payload.get("tags")) or extract_tags(raw_title),
        "due": str(payload.get("due", "")).strip()[:20],
        "nextAction": str(payload.get("nextAction", "")).strip()[:220],
        "notes": str(payload.get("notes", "")).strip()[:500],
        "repeat": normalize_repeat(payload.get("repeat")),
        "created": today,
        "updated": today,
    }


def create_task(payload: dict) -> dict:
    task = task_from_payload(payload)
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
    if payload.get("type") in TASK_TYPES:
        updated["type"] = payload["type"]
    if "assignee" in payload:
        updated["assignee"] = "" if payload.get("assignee") is None else str(payload.get("assignee"))
    if payload.get("subStatus") in TASK_SUB_STATUSES:
        updated["subStatus"] = payload["subStatus"]
    if payload.get("horizon") in HORIZON_ORDER:
        updated["horizon"] = payload["horizon"]
    if payload.get("priority") in {"high", "medium", "low"}:
        updated["priority"] = payload["priority"]
    if "repeat" in payload:
        updated["repeat"] = normalize_repeat(payload.get("repeat"))
    updated["updated"] = today

    with data_change("update-task"):
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


def tasks_for_agent(agent_info: dict) -> list[dict]:
    name = str(agent_info.get("name", ""))
    return sorted_tasks([task for task in load_tasks() if task.get("assignee") == name])


def update_agent_task_sub_status(task_id: str, agent_info: dict, payload: dict) -> tuple[dict, int]:
    sub_status = normalize_sub_status(payload.get("subStatus"))
    if payload.get("subStatus") not in TASK_SUB_STATUSES:
        return {"error": "invalid subStatus"}, 400
    tasks = load_tasks()
    today = str(datetime.now().date())
    found = None
    for task in tasks:
        if task.get("id") == task_id:
            found = task
            break
    if not found:
        return {"error": "task not found"}, 404
    if found.get("assignee") != agent_info.get("name"):
        return {"error": "forbidden"}, 403
    found["subStatus"] = sub_status
    found["updated"] = today
    save_tasks(tasks)
    append_log(f"Agent 更新任务子状态：{found['title']} → {sub_status}")
    return {"task": found, "tasks": tasks_for_agent(agent_info)}, 200


def filter_values(payload: dict, key: str) -> set[str]:
    value = payload.get(key)
    if value in (None, "", "all"):
        return set()
    raw_values = value if isinstance(value, list) else [value]
    return {str(item).strip().lower() for item in raw_values if str(item).strip() and str(item).strip().lower() != "all"}


def search_tasks(payload: dict) -> dict:
    query = str(payload.get("query", "")).strip().lower()
    status_filter = filter_values(payload, "status")
    type_filter = filter_values(payload, "type")
    assignee_filter = filter_values(payload, "assignee")
    horizon_filter = filter_values(payload, "horizon")
    area_filter = filter_values(payload, "area")
    priority_filter = filter_values(payload, "priority")
    tag_filter = filter_values(payload, "tag")

    matches = []
    for task in load_tasks():
        tags = {str(tag).lower() for tag in task.get("tags", [])}
        if query and query not in task.get("title", "").lower():
            continue
        if status_filter and task.get("status", "").lower() not in status_filter:
            continue
        if type_filter and task.get("type", "personal").lower() not in type_filter:
            continue
        if assignee_filter and task.get("assignee", "").lower() not in assignee_filter:
            continue
        if horizon_filter and task.get("horizon", "").lower() not in horizon_filter:
            continue
        if area_filter and task.get("area", "").lower() not in area_filter:
            continue
        if priority_filter and task.get("priority", "").lower() not in priority_filter:
            continue
        if tag_filter and not tags.intersection(tag_filter):
            continue
        matches.append(task)
    return {"tasks": sorted_tasks(matches), "count": len(matches)}


def batch_tasks(payload: dict) -> dict:
    tasks = load_tasks()
    history = load_history()
    created: list[dict] = []
    updated: list[dict] = []
    changed_tasks = False
    changed_history = False
    today = str(datetime.now().date())

    creates = payload.get("create", payload.get("creates", []))
    if isinstance(creates, dict):
        creates = [creates]
    if not isinstance(creates, list):
        creates = []
    for item in creates:
        if isinstance(item, dict):
            task = task_from_payload(item)
            tasks.append(task)
            created.append(task)
            changed_tasks = True

    updates: list[dict] = []
    status_payload = payload.get("updateStatus") if isinstance(payload.get("updateStatus"), dict) else {}
    ids = payload.get("ids", status_payload.get("ids", []))
    status = payload.get("status", status_payload.get("status", ""))
    if isinstance(ids, str):
        ids = [ids]
    if isinstance(ids, list) and status in TASK_STATUSES:
        updates.extend({"id": str(task_id), "status": status} for task_id in ids)
    if isinstance(payload.get("updates"), list):
        updates.extend(item for item in payload["updates"] if isinstance(item, dict))

    for item in updates:
        task_id = str(item.get("id", ""))
        status = item.get("status")
        if status not in TASK_STATUSES:
            continue
        target = None
        source = "tasks"
        for task in tasks:
            if task.get("id") == task_id:
                target = task
                break
        if target is None:
            source = "history"
            for task in history:
                if task.get("id") == task_id:
                    target = task
                    break
        if target is None:
            continue
        target["status"] = status
        target["updated"] = today
        updated.append({"id": target["id"], "status": target["status"], "title": target["title"]})
        if source == "history":
            history = [task for task in history if task.get("id") != task_id]
            if target["status"] in CURRENT_STATUSES:
                tasks.append(target)
                changed_tasks = True
            else:
                history.append(target)
            changed_history = True
        else:
            changed_tasks = True

    with data_change("batch-tasks"):
        if changed_history:
            save_history(history)
        if changed_tasks:
            save_tasks(tasks)

    if created:
        append_log(f"批量新增 {len(created)} 个任务")
    if updated:
        append_log(f"批量更新 {len(updated)} 个任务状态")
    return {"created": created, "updated": updated, "state": state_payload()}


def reminder_task(task: dict) -> dict:
    return {
        "id": task.get("id", ""),
        "title": task.get("title", ""),
        "due": task.get("due", ""),
        "priority": task.get("priority", ""),
        "horizon": task.get("horizon", ""),
        "area": task.get("area", ""),
    }


def reminders_payload() -> dict:
    today = datetime.now().date()
    due_today = []
    overdue = []
    for task in sorted_tasks(load_tasks()):
        if task.get("priority") != "high" or task.get("status") not in CURRENT_STATUSES:
            continue
        due = parse_iso_date(task.get("due"))
        if not due:
            continue
        if due < today:
            overdue.append(reminder_task(task))
        elif due == today:
            due_today.append(reminder_task(task))
    return {"today": due_today, "overdue": overdue, "count": len(due_today) + len(overdue)}


def task_completion_date(task: dict) -> date | None:
    return parse_iso_date(task.get("updated")) or parse_iso_date(task.get("created"))


def max_completion_streak(done_tasks: list[dict]) -> int:
    days = sorted({day for task in done_tasks if (day := task_completion_date(task))})
    best = 0
    current = 0
    previous = None
    for day in days:
        if previous is None or day == previous + timedelta(days=1):
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = day
    return best


SKILL_TREE_ORDER = ["content", "invest", "system", "life", "growth"]
SKILL_TREE_LAST_VERIFIED = "2026-05-08"
SKILL_LEVELS = {
    0: {"label": "未解锁", "marker": "🔒", "color": "gray", "className": "locked", "status": "locked"},
    1: {"label": "入门", "marker": "🌱", "color": "lightblue", "className": "beginner", "status": "beginner"},
    2: {"label": "可用", "marker": "🔄", "color": "blue", "className": "usable", "status": "usable"},
    3: {"label": "熟练", "marker": "✅", "color": "green", "className": "proficient", "status": "proficient"},
    4: {"label": "精通", "marker": "⭐", "color": "gold", "className": "expert", "status": "expert"},
    5: {"label": "大师", "marker": "🏆", "color": "purple", "className": "master", "status": "master"},
}


def upgrade_conditions(level: int, name: str) -> list[str]:
    if level <= 0:
        return [f"完成{name}的首个可复现流程", "记录输入、输出、检查点和异常处理方式"]
    if level == 1:
        return [f"累计稳定使用{name} >= 5 次", "形成固定模板或检查清单"]
    if level == 2:
        return [f"{name}连续稳定产出 >= 4 周", "主要异常有明确处理路径"]
    if level == 3:
        return [f"{name}形成自动化闭环，人工只做抽查", "关键数据可追踪并能复盘"]
    if level == 4:
        return [f"{name}获得外部用户、收入或团队复用验证", "沉淀为可公开复用的标准流程"]
    return ["保持外部验证数据持续增长", "定期复盘并更新标准流程"]


def skill_node(
    skill_id: str,
    name: str,
    icon: str,
    level: int,
    tree_id: str,
    parent_id: str | None = None,
    dependencies: list[str] | None = None,
    notes: str = "",
    keywords: list[str] | None = None,
    areas: list[str] | None = None,
    conditions: list[str] | None = None,
) -> dict:
    deps = list(dependencies or [])
    if parent_id and parent_id not in deps:
        deps.insert(0, parent_id)
    level = max(0, min(5, int(level)))
    meta = SKILL_LEVELS[level]
    title = name.strip()
    display_name = f"{icon} {title}".strip() if icon and not title.startswith(icon) else title
    return {
        "id": skill_id,
        "name": display_name,
        "title": title,
        "icon": icon,
        "level": level,
        "maxLevel": 5,
        "parentId": parent_id,
        "treeId": tree_id,
        "dependencies": deps,
        "upgradeConditions": list(conditions or upgrade_conditions(level, name)),
        "status": meta["status"],
        "lastVerified": SKILL_TREE_LAST_VERIFIED,
        "notes": notes,
        "description": notes or f"{name}能力节点。",
        "line": tree_id,
        "keywords": list(keywords or [name]),
        "areas": list(areas or []),
    }


SKILL_TREES = {
    "content": {
        "id": "content",
        "name": "内容创作线",
        "icon": "📝",
        "skills": [
            skill_node("writing", "文本写作", "📝", 2, "content", notes="文本写作主能力，承载技术博客、文风学习和随想记录。", keywords=["写作", "文本", "文章", "博客", "创作", "文案", "随想", "文风", "内容"]),
            skill_node("tech-blog", "技术博客", "📝", 3, "content", "writing", notes="有持续产出，但频率不稳定", keywords=["技术博客", "博客", "技术文章", "文章", "blog"]),
            skill_node("literary-writing", "文学创作", "✍️", 0, "content", "writing", notes="待建立稳定文学创作流程", keywords=["文学", "小说", "散文", "诗歌", "文学创作"]),
            skill_node("style-learning", "文风学习", "🖋️", 1, "content", "writing", notes="有 agent，产出不持续", keywords=["文风", "风格", "文风学习", "仿写"]),
            skill_node("random-notes", "随想记录", "📓", 1, "content", "writing", notes="有流程，但不稳定", keywords=["随想", "记录", "灵感", "笔记", "想法"]),
            skill_node("multi-platform-publishing", "多平台发布", "📤", 1, "content", "writing", dependencies=["writing"], notes="发布链路已起步，稳定性仍需提升", keywords=["多平台", "发布", "分发", "上线", "内容发布"]),
            skill_node("blog-publishing", "博客发布", "🌐", 2, "content", "multi-platform-publishing", notes="基本能用，偶尔出问题", keywords=["博客发布", "博客", "发布"]),
            skill_node("wechat-official-account", "微信公众号", "💬", 1, "content", "multi-platform-publishing", notes="有工具，不稳定", keywords=["微信公众号", "公众号", "微信发布"]),
            skill_node("zhihu-juejin-csdn", "知乎/掘金/CSDN", "🧩", 1, "content", "multi-platform-publishing", notes="有工具，不稳定", keywords=["知乎", "掘金", "CSDN", "csdn"]),
            skill_node("xiaohongshu", "小红书", "📕", 0, "content", "multi-platform-publishing", notes="未解锁小红书稳定发布流程", keywords=["小红书", "rednote"]),
            skill_node("overseas-platforms", "海外平台", "🌍", 0, "content", "multi-platform-publishing", notes="未解锁海外平台发布流程", keywords=["海外平台", "medium", "substack", "海外发布"]),
            skill_node("voice", "语音能力", "🔊", 1, "content", "writing", dependencies=["writing"], notes="语音能力已起步，播客链路未闭环", keywords=["语音", "tts", "播客", "音频", "配音", "声音"]),
            skill_node("tts-single-voice", "TTS 单音色", "🔉", 2, "content", "voice", notes="能用，偶尔有问题", keywords=["TTS 单音色", "tts", "语音合成", "单音色"]),
            skill_node("tts-multi-voice", "TTS 多音色", "🎙️", 0, "content", "voice", notes="未解锁多音色稳定流程", keywords=["TTS 多音色", "多音色", "配音"]),
            skill_node("podcast-topic-script", "播客选题脚本", "🎧", 1, "content", "voice", notes="有 agent，产出不持续", keywords=["播客选题", "播客脚本", "播客", "选题脚本"]),
            skill_node("audio-post-production", "音频后期剪辑", "🎚️", 0, "content", "voice", notes="未解锁音频后期剪辑流程", keywords=["音频后期", "剪辑", "降噪", "混音"]),
            skill_node("podcast-platform-publishing", "播客平台发布", "📡", 0, "content", "voice", dependencies=["audio-post-production", "podcast-topic-script"], notes="未解锁播客平台发布流程", keywords=["播客发布", "播客平台", "小宇宙", "podcast"]),
            skill_node("image", "图像能力", "🎨", 1, "content", "writing", dependencies=["writing"], notes="图像生成和配图能力已起步", keywords=["图像", "图片", "配图", "封面", "AI 生成图"]),
            skill_node("ai-image-generation", "AI 生成图", "🖼️", 2, "content", "image", notes="能产出，不稳定", keywords=["AI 生成图", "生成图", "图片生成", "imagegen"]),
            skill_node("cover-image", "封面图/配图", "🌄", 1, "content", "image", notes="有工具", keywords=["封面图", "配图", "封面", "头图"]),
            skill_node("brand-visual-guidelines", "品牌视觉规范", "🎯", 0, "content", "image", notes="未沉淀品牌视觉规范", keywords=["品牌视觉", "视觉规范", "品牌规范"]),
            skill_node("graphic-layout", "图文排版", "🧾", 0, "content", "image", notes="未解锁稳定图文排版流程", keywords=["图文排版", "排版", "长图"]),
            skill_node("video", "视频能力", "🎬", 0, "content", "writing", dependencies=["writing", "image"], notes="视频产线尚未解锁", keywords=["视频", "短视频", "视频制作"]),
            skill_node("video-script", "视频脚本", "📜", 0, "content", "video", notes="未解锁视频脚本流程", keywords=["视频脚本", "分镜", "脚本"]),
            skill_node("ai-text-to-video", "AI 文生视频", "🎞️", 0, "content", "video", notes="有工具但没用过", keywords=["文生视频", "AI 视频", "视频生成"]),
            skill_node("subtitles-titles", "字幕/标题", "🔤", 0, "content", "video", notes="未解锁字幕和标题流程", keywords=["字幕", "标题", "视频标题"]),
            skill_node("editing-workflow", "剪辑流程", "✂️", 0, "content", "video", notes="未解锁剪辑流程", keywords=["剪辑", "视频剪辑", "剪映"]),
            skill_node("video-platform-publishing", "视频平台发布", "📺", 0, "content", "video", dependencies=["editing-workflow"], notes="未解锁视频平台发布流程", keywords=["视频发布", "B站", "抖音", "YouTube"]),
        ],
    },
    "invest": {
        "id": "invest",
        "name": "投资理财线",
        "icon": "📈",
        "skills": [
            skill_node("investment-research", "投资研究", "📈", 1, "invest", notes="投资研究主能力，覆盖价值分析和跟踪提醒。", keywords=["投资", "理财", "股票", "研究", "财务", "portfolio"]),
            skill_node("value-investing-analysis", "价值投资分析", "💎", 3, "invest", "investment-research", notes="100只A股四维度分析已完成，但推送停了", keywords=["价值投资", "四维度", "A股", "股票分析", "基本面"]),
            skill_node("financial-data-api", "金融数据接口", "🔌", 1, "invest", "investment-research", notes="有接口，未稳定使用", keywords=["金融数据", "数据接口", "行情", "财务数据", "API"]),
            skill_node("daily-tracking-push", "每日跟踪推送", "📬", 0, "invest", "investment-research", dependencies=["value-investing-analysis", "financial-data-api"], notes="之前有现在停了", keywords=["每日跟踪", "推送", "股票推送", "跟踪提醒"]),
            skill_node("anomaly-alerts", "异常驱动提醒", "🚨", 0, "invest", "investment-research", dependencies=["financial-data-api"], notes="未解锁异常驱动提醒", keywords=["异常", "提醒", "预警", "异动", "告警"]),
            skill_node("quant-trading", "量化交易", "📊", 0, "invest", "investment-research", dependencies=["financial-data-api"], notes="量化交易主流程未解锁", keywords=["量化", "交易", "策略", "回测", "quant"]),
            skill_node("data-pipeline", "数据管道", "🧱", 1, "invest", "quant-trading", notes="Phase 1 跑过，不稳定", keywords=["数据管道", "pipeline", "数据清洗", "行情数据"]),
            skill_node("strategy-backtest", "策略回测", "🧪", 0, "invest", "quant-trading", dependencies=["data-pipeline"], notes="未解锁策略回测流程", keywords=["策略回测", "回测", "backtest"]),
            skill_node("paper-trading", "仿真交易", "🕹️", 0, "invest", "quant-trading", dependencies=["strategy-backtest"], notes="未解锁仿真交易流程", keywords=["仿真交易", "模拟交易", "paper trading"]),
            skill_node("live-trading", "实盘对接", "🏦", 0, "invest", "quant-trading", dependencies=["paper-trading"], notes="未解锁实盘对接", keywords=["实盘", "券商", "交易接口", "下单"]),
        ],
    },
    "system": {
        "id": "system",
        "name": "系统工具线",
        "icon": "🔧",
        "skills": [
            skill_node("personal-os", "个人操作系统", "🔧", 1, "system", notes="个人操作系统主线，覆盖任务、知识库、工作台和调度。", keywords=["个人操作系统", "系统", "工作台", "自动化", "工具"]),
            skill_node("task-management", "任务管理", "✅", 2, "system", "personal-os", notes="LLM Todo 本地能用", keywords=["任务", "todo", "LLM Todo", "规划", "优先级", "提醒", "复盘", "迁移"], areas=["system"]),
            skill_node("local-run", "本地运行", "💻", 3, "system", "task-management", notes="稳定", keywords=["本地运行", "本地服务", "localhost", "8720"]),
            skill_node("cloud-deploy", "上云部署", "☁️", 0, "system", "task-management", notes="未解锁上云部署", keywords=["上云", "部署", "云服务器", "公网"]),
            skill_node("multi-device-access", "多端访问", "📱", 0, "system", "task-management", notes="未解锁多端访问", keywords=["多端", "手机", "平板", "同步", "访问"]),
            skill_node("knowledge-base", "知识库", "📚", 0, "system", "personal-os", notes="未解锁稳定知识库", keywords=["知识库", "wiki", "知识", "归档", "知识图谱"], areas=["learning"]),
            skill_node("agent-workbench-platform", "Agent 工作台平台化", "🧰", 1, "system", "personal-os", notes="Agent 工作台平台化已起步", keywords=["Agent 工作台", "平台化", "agent", "工作台"]),
            skill_node("llm-todo-workbench", "LLM Todo 工作台", "🧭", 3, "system", "agent-workbench-platform", notes="稳定可用", keywords=["LLM Todo", "任务工作台", "todo 工作台"]),
            skill_node("stock-analysis-site", "股票分析网站", "📈", 2, "system", "agent-workbench-platform", notes="能用", keywords=["股票分析网站", "股票网站", "投资网站"]),
            skill_node("writing-review-site", "写稿审稿网站", "📝", 2, "system", "agent-workbench-platform", notes="能用", keywords=["写稿", "审稿", "文章网站", "写作网站"]),
            skill_node("podcast-workbench", "播客制作工作台", "🎧", 0, "system", "agent-workbench-platform", notes="未解锁播客制作工作台", keywords=["播客工作台", "播客制作"]),
            skill_node("video-workbench", "视频制作工作台", "🎬", 0, "system", "agent-workbench-platform", notes="未解锁视频制作工作台", keywords=["视频工作台", "视频制作"]),
            skill_node("content-publishing-backend", "内容发布后台", "📤", 0, "system", "agent-workbench-platform", notes="未解锁内容发布后台", keywords=["内容发布后台", "发布后台", "CMS"]),
            skill_node("agent-scheduling", "Agent 调度", "⏱️", 1, "system", "personal-os", notes="Agent 调度已起步", keywords=["Agent 调度", "调度", "定时任务", "cron", "自动化"]),
            skill_node("cron-jobs", "Cron 定时任务", "🕒", 2, "system", "agent-scheduling", notes="能用，部分任务不稳定", keywords=["Cron", "定时", "定时任务", "计划任务"]),
            skill_node("anomaly-notification", "异常通知", "📣", 0, "system", "agent-scheduling", notes="未解锁异常通知", keywords=["异常通知", "通知", "告警", "失败提醒"]),
            skill_node("closed-loop-automation", "闭环自动化", "🔁", 0, "system", "agent-scheduling", dependencies=["cron-jobs", "anomaly-notification"], notes="未解锁闭环自动化", keywords=["闭环", "自动化", "自动执行", "自动修复"]),
        ],
    },
    "life": {
        "id": "life",
        "name": "生活服务线",
        "icon": "🏠",
        "skills": [
            skill_node("life", "生活", "🏠", 1, "life", notes="生活服务主线，覆盖健康、购物、旅游、育儿和报销。", keywords=["生活", "家庭", "家务", "服务"], areas=["life"]),
            skill_node("home-health-record", "家庭健康档案", "🏥", 1, "life", "life", notes="有结构，不持续", keywords=["健康档案", "健康", "体检", "病历", "家庭健康"], areas=["life"]),
            skill_node("shopping-list", "购物清单", "🛒", 1, "life", "life", notes="偶尔用", keywords=["购物清单", "购物", "淘宝", "京东", "清单"], areas=["life"]),
            skill_node("travel-planning", "旅游规划", "🧳", 1, "life", "life", notes="偶尔用", keywords=["旅游", "旅行", "行程", "攻略", "酒店"], areas=["life"]),
            skill_node("parenting-education", "育儿教育", "🧒", 1, "life", "life", notes="偶尔用", keywords=["育儿", "教育", "孩子", "亲子"], areas=["life"]),
            skill_node("printing-3d", "3D打印", "🧊", 0, "life", "life", notes="未解锁 3D 打印流程", keywords=["3D打印", "打印", "建模"], areas=["life"]),
            skill_node("reimbursement", "报销", "🧾", 0, "life", "life", notes="未解锁报销流程", keywords=["报销", "发票", "票据", "费用"], areas=["life"]),
        ],
    },
    "growth": {
        "id": "growth",
        "name": "运营/增长线",
        "icon": "🚀",
        "skills": [
            skill_node("growth", "运营与增长", "🚀", 0, "growth", notes="运营与增长主线尚未解锁", keywords=["运营", "增长", "流量", "变现", "KPI"]),
            skill_node("data-collection-kpi", "数据采集（KPI 面板）", "📊", 0, "growth", "growth", notes="KPI 面板未解锁", keywords=["KPI", "数据采集", "指标", "面板"]),
            skill_node("fan-tracking", "粉丝量追踪", "👥", 0, "growth", "data-collection-kpi", notes="微信公众号、知乎、CSDN、掘金、B站、小红书、GitHub 等粉丝数据待采集", keywords=["粉丝", "followers", "关注者", "B站", "GitHub"]),
            skill_node("content-output-stats", "内容产出统计", "📈", 0, "growth", "data-collection-kpi", notes="文章数/月、播客数/月、视频数/月待统计", keywords=["内容产出", "文章数", "播客数", "视频数", "统计"]),
            skill_node("revenue-tracking", "收入追踪", "💰", 0, "growth", "data-collection-kpi", notes="广告/流量收入、付费内容收入、投资收益待追踪", keywords=["收入", "广告", "付费内容", "投资收益", "变现"]),
            skill_node("growth-skills", "增长技能", "📣", 0, "growth", "growth", notes="增长技能未解锁", keywords=["增长技能", "流量获取", "社群", "分发"]),
            skill_node("seo-traffic", "SEO / 流量获取", "🔎", 0, "growth", "growth-skills", notes="未解锁 SEO / 流量获取", keywords=["SEO", "流量", "搜索", "获客"]),
            skill_node("content-distribution-strategy", "内容分发策略", "🧭", 0, "growth", "growth-skills", notes="未解锁内容分发策略", keywords=["内容分发", "分发策略", "渠道"]),
            skill_node("community-operations", "社群运营", "💬", 0, "growth", "growth-skills", notes="未解锁社群运营", keywords=["社群", "社群运营", "微信群", "社区"]),
            skill_node("monetization-design", "变现模式设计", "💼", 0, "growth", "growth-skills", notes="未解锁变现模式设计", keywords=["变现", "商业模式", "付费", "收入"]),
            skill_node("analysis-skills", "分析技能", "🧠", 0, "growth", "growth", notes="分析技能未解锁", keywords=["分析", "复盘", "竞品", "ROI"]),
            skill_node("viral-analysis", "爆款分析", "🔥", 0, "growth", "analysis-skills", notes="哪篇火了、为什么", keywords=["爆款", "爆文", "热门", "火了"]),
            skill_node("competitor-monitoring", "竞品/同行监控", "👀", 0, "growth", "analysis-skills", notes="未解锁竞品/同行监控", keywords=["竞品", "同行", "监控", "对标"]),
            skill_node("time-roi", "时间投资回报率", "⏳", 0, "growth", "analysis-skills", notes="各领域时间 vs 产出", keywords=["时间投资回报率", "ROI", "时间投入", "产出"]),
        ],
    },
}

PRACTICAL_ABILITIES = [SKILL_TREES[line_id] for line_id in SKILL_TREE_ORDER if line_id in SKILL_TREES]

ABILITY_LEVEL_THRESHOLDS = [0, 10, 30, 60, 100]


def ability_level(xp: int) -> tuple[int, int]:
    level = 1
    for threshold in ABILITY_LEVEL_THRESHOLDS[1:]:
        if xp >= threshold:
            level += 1
    level = min(level, 5)
    if level >= 5:
        return level, 0
    return level, max(0, ABILITY_LEVEL_THRESHOLDS[level] - xp)


def task_search_text(task: dict) -> str:
    return " ".join(
        [
            str(task.get("title", "")),
            str(task.get("nextAction", "")),
            str(task.get("notes", "")),
            " ".join(str(tag) for tag in task.get("tags", []) if tag),
        ]
    ).lower()


def task_matches_ability(task: dict, ability: dict) -> bool:
    text = task_search_text(task)
    keywords = [str(keyword).lower() for keyword in ability.get("keywords", [])]
    if any(keyword and keyword in text for keyword in keywords):
        return True
    areas = set(ability.get("areas", []))
    return bool(areas and task.get("area") in areas)


def earliest_task_date(tasks: list[dict]) -> str:
    dates = [value for task in tasks for value in (task.get("created"), task.get("updated"), task.get("due")) if value]
    return min(dates) if dates else ""


def skill_line_list(skill_trees: dict) -> list[dict]:
    return [skill_trees[line_id] for line_id in SKILL_TREE_ORDER if line_id in skill_trees]


def flatten_skill_lines(lines: list[dict]) -> list[dict]:
    return [skill for line in lines for skill in line.get("skills", []) if isinstance(skill, dict)]


def flatten_skill_trees(skill_trees: dict) -> list[dict]:
    return flatten_skill_lines(skill_line_list(skill_trees))


def skill_level_meta(level: object) -> dict:
    try:
        value = int(level)
    except (TypeError, ValueError):
        value = 0
    return SKILL_LEVELS.get(max(0, min(5, value)), SKILL_LEVELS[0])


def skill_dependency_edges(skills: list[dict]) -> list[dict]:
    valid_ids = {skill.get("id") for skill in skills if skill.get("id")}
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for skill in skills:
        target = str(skill.get("id") or "")
        if not target:
            continue
        parent_id = str(skill.get("parentId") or "")
        raw_dependencies = skill.get("dependencies", [])
        dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
        for dependency in dependencies:
            source = str(dependency or "")
            if not source or source not in valid_ids or source == target:
                continue
            edge_type = "parent" if source == parent_id else "dependency"
            marker = (source, target, edge_type)
            if marker not in seen:
                edges.append({"from": source, "to": target, "type": edge_type})
                seen.add(marker)
    return edges


def annotate_skill_line(line: dict) -> None:
    skills = [skill for skill in line.get("skills", []) if isinstance(skill, dict)]
    skill_by_id = {skill.get("id"): skill for skill in skills if skill.get("id")}
    children: dict[str, list[str]] = {str(skill.get("id")): [] for skill in skills if skill.get("id")}
    for skill in skills:
        parent_id = skill.get("parentId")
        if parent_id in children:
            children[str(parent_id)].append(str(skill.get("id")))

    depth_cache: dict[str, int] = {}

    def depth_for(skill: dict) -> int:
        skill_id = str(skill.get("id") or "")
        if skill_id in depth_cache:
            return depth_cache[skill_id]
        parent_id = skill.get("parentId")
        parent = skill_by_id.get(parent_id)
        depth_cache[skill_id] = depth_for(parent) + 1 if parent else 0
        return depth_cache[skill_id]

    for skill in skills:
        level = max(0, min(5, int(skill.get("level") or 0)))
        meta = skill_level_meta(level)
        skill["level"] = level
        skill["levelLabel"] = meta["label"]
        skill["levelMarker"] = meta["marker"]
        skill["levelClass"] = meta["className"]
        skill["childrenIds"] = children.get(str(skill.get("id")), [])
        skill["depth"] = depth_for(skill)
        skill["tier"] = skill.get("tier") or ("foundation" if skill["depth"] == 0 else "execution" if skill["depth"] == 1 else "output")
        skill["skills"] = skill.get("skills") or [skill_by_id[child_id].get("name", child_id) for child_id in skill["childrenIds"] if child_id in skill_by_id]

    edges = skill_dependency_edges(skills)
    links: dict[str, list[str]] = {str(skill.get("id")): [] for skill in skills if skill.get("id")}
    for edge in edges:
        links.setdefault(edge["from"], []).append(edge["to"])
    for skill in skills:
        skill["linksTo"] = links.get(str(skill.get("id")), [])

    node_copies = {str(skill.get("id")): {**skill, "children": []} for skill in skills if skill.get("id")}
    roots: list[dict] = []
    for skill in skills:
        skill_id = str(skill.get("id") or "")
        node = node_copies.get(skill_id)
        if not node:
            continue
        parent_id = str(skill.get("parentId") or "")
        parent = node_copies.get(parent_id)
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)

    line["tree"] = roots
    line["edges"] = edges
    line["summary"] = skill_tree_summary(skills)


def finalize_skill_trees(skill_trees: dict) -> None:
    for line in skill_line_list(skill_trees):
        annotate_skill_line(line)


def skill_tree_summary(skills: list[dict]) -> dict:
    levels = [max(0, min(5, int(skill.get("level") or 0))) for skill in skills]
    total = len(levels)
    return {
        "total": total,
        "locked": len([level for level in levels if level == 0]),
        "inProgress": len([level for level in levels if 1 <= level <= 3]),
        "mastered": len([level for level in levels if level >= 4]),
        "averageLevel": round(sum(levels) / total, 1) if total else 0,
    }


def skill_tree_kpis(skills: list[dict], history: list[dict]) -> list[dict]:
    today = datetime.now().date()
    recent_content_ids = {
        task.get("id")
        for skill in skills
        if skill.get("line") == "content"
        for task_id in skill.get("relatedTasks", [])
        for task in history
        if task.get("id") == task_id and task_completion_date(task) and (today - task_completion_date(task)).days <= 30
    }
    return [
        {"id": "followers", "label": "粉丝量", "value": "待采集", "note": "KPI 数据源将在 Phase 2 接入"},
        {"id": "content-output-30d", "label": "近30天内容产出", "value": str(len(recent_content_ids)), "note": "由完成任务粗略估算"},
        {"id": "revenue", "label": "收入", "value": "待采集", "note": "按投资 / 内容 / 工具拆分"},
        {"id": "time-roi", "label": "时间投资回报率", "value": "待采集", "note": "等待时间投入数据结构"},
    ]


def skill_tree_store() -> dict:
    payload = read_json_object(SKILL_TREE_PATH, {"overrides": {}, "updated": ""})
    overrides = payload.get("overrides", {})
    payload["overrides"] = overrides if isinstance(overrides, dict) else {}
    payload["updated"] = str(payload.get("updated", "") or SKILL_TREE_LAST_VERIFIED)
    return payload


def find_skill_node(skill_trees: dict, skill_id: str) -> dict | None:
    for skill in flatten_skill_trees(skill_trees):
        if skill.get("id") == skill_id:
            return skill
    return None


def apply_skill_tree_overrides(skill_trees: dict, overrides: dict) -> None:
    for skill in flatten_skill_trees(skill_trees):
        override = overrides.get(skill.get("id"))
        if not isinstance(override, dict):
            continue
        if "level" in override:
            skill["level"] = max(0, min(5, int(override.get("level") or 0)))
        if "notes" in override:
            skill["notes"] = str(override.get("notes", ""))
            skill["description"] = skill["notes"] or skill.get("description", "")
        if isinstance(override.get("upgradeConditions"), list):
            skill["upgradeConditions"] = [str(item) for item in override["upgradeConditions"] if str(item).strip()]
        if override.get("lastVerified"):
            skill["lastVerified"] = str(override["lastVerified"])


def enrich_skill_tree(skill_trees: dict, tasks: list[dict], history: list[dict]) -> None:
    all_tasks = tasks + history
    done_ids = {task.get("id") for task in history if task.get("status") == "done"}
    current_ids = {task.get("id") for task in tasks}
    for skill in flatten_skill_trees(skill_trees):
        related = [task for task in all_tasks if task_matches_ability(task, skill)]
        related_ids = [str(task.get("id")) for task in related if task.get("id")]
        done_count = len([task for task in related if task.get("id") in done_ids])
        current_count = len([task for task in related if task.get("id") in current_ids])
        xp = done_count * 10 + current_count * 4
        _activity_level, xp_to_next = ability_level(xp)
        skill.update(
            {
                "xp": xp,
                "xpToNext": xp_to_next,
                "relatedTasks": related_ids,
                "relatedCount": len(related_ids),
                "doneCount": done_count,
                "activeCount": current_count,
                "unlockedAt": earliest_task_date(related),
            }
        )


def build_skill_trees(tasks: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    skill_trees = copy.deepcopy(SKILL_TREES)
    apply_skill_tree_overrides(skill_trees, skill_tree_store()["overrides"])
    if tasks is not None and history is not None:
        enrich_skill_tree(skill_trees, tasks, history)
    finalize_skill_trees(skill_trees)
    return skill_trees


def skill_tree_payload(tasks: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    if tasks is None:
        tasks = load_tasks()
    if history is None:
        history = load_history()
    store = skill_tree_store()
    skill_trees = build_skill_trees(tasks, history)
    lines = skill_line_list(skill_trees)
    skills = flatten_skill_lines(lines)
    dependencies = [{**edge, "line": line.get("id")} for line in lines for edge in line.get("edges", [])]
    return {
        "skillTrees": skill_trees,
        "lines": lines,
        "skills": skills,
        "dependencies": dependencies,
        "summary": skill_tree_summary(skills),
        "kpis": skill_tree_kpis(skills, history),
        "levelLegend": SKILL_LEVELS,
        "updated": store.get("updated") or SKILL_TREE_LAST_VERIFIED,
    }


def practical_abilities(tasks: list[dict], history: list[dict]) -> list[dict]:
    return skill_tree_payload(tasks, history)["skills"]


def update_skill_node(skill_id: str, payload: dict) -> dict | None:
    if not find_skill_node(SKILL_TREES, skill_id):
        return None
    incoming = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    store = skill_tree_store()
    overrides = dict(store["overrides"])
    current = dict(overrides.get(skill_id, {}))
    changed = False

    if "level" in incoming:
        try:
            level = int(incoming["level"])
        except (TypeError, ValueError) as exc:
            raise ValueError("技能等级必须是 0 到 5 的整数") from exc
        if level < 0 or level > 5:
            raise ValueError("技能等级必须是 0 到 5 的整数")
        current["level"] = level
        changed = True
    if "notes" in incoming:
        current["notes"] = str(incoming.get("notes") or "").strip()
        changed = True
    if changed:
        current["lastVerified"] = str(datetime.now().date())
        overrides[skill_id] = current
        write_json_object(SKILL_TREE_PATH, {"updated": current["lastVerified"], "overrides": overrides}, "update-skill-tree")
        append_log(f"更新技能节点：{skill_id} → Lv.{current.get('level', '未变更')}")

    payload = skill_tree_payload()
    return {"skill": find_skill_node(payload["skillTrees"], skill_id), **payload}


def character_payload() -> dict:
    tasks = load_tasks()
    history = load_history()
    done = [task for task in history if task.get("status") == "done"]
    done_count = len(done)
    skill_tree_data = skill_tree_payload(tasks, history)
    abilities = skill_tree_data["skills"]
    ability_lines = skill_tree_data["lines"]
    flat_abilities = abilities
    total_ability_xp = sum(ability["xp"] for ability in flat_abilities)
    level = total_ability_xp // 50 + 1
    xp = total_ability_xp % 50

    area_counts = {
        "system": len([task for task in done if task.get("area") == "system"]),
        "learning": len([task for task in done if task.get("area") == "learning"]),
        "work": len([task for task in done if task.get("area") == "work"]),
        "life": len([task for task in done if task.get("area") == "life"]),
    }

    high_done_with_due = [task for task in done if task.get("priority") == "high" and parse_iso_date(task.get("due"))]
    high_done_on_time = [
        task
        for task in high_done_with_due
        if task_completion_date(task) and task_completion_date(task) <= parse_iso_date(task.get("due"))
    ]
    efficiency = round(len(high_done_on_time) / len(high_done_with_due) * 100) if high_done_with_due else 0

    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    def in_this_week(day: date | None) -> bool:
        return bool(day and week_start <= day <= week_end)

    week_done = [task for task in done if in_this_week(task_completion_date(task))]
    week_total_ids = set()
    for task in tasks + history:
        if in_this_week(parse_iso_date(task.get("due"))) or in_this_week(parse_iso_date(task.get("created"))) or in_this_week(parse_iso_date(task.get("updated"))):
            week_total_ids.add(task.get("id"))
    focus = round(len(week_done) / len(week_total_ids) * 100) if week_total_ids else 0

    completion_days: dict[str, int] = {}
    for task in done:
        day = task_completion_date(task)
        if day:
            key = day.isoformat()
            completion_days[key] = completion_days.get(key, 0) + 1
    streak = max_completion_streak(done)

    achievements = [
        {
            "id": "first_done",
            "title": "首次完成任务",
            "description": "完成任意一个任务。",
            "unlocked": done_count >= 1,
        },
        {
            "id": "streak_7",
            "title": "连续 7 天完成任务",
            "description": f"当前历史最长连续 {streak} 天。",
            "unlocked": streak >= 7,
        },
        {
            "id": "single_day_5",
            "title": "单日完成 5 个任务",
            "description": f"当前单日最高 {max(completion_days.values(), default=0)} 个。",
            "unlocked": max(completion_days.values(), default=0) >= 5,
        },
        {
            "id": "high_priority_punctual",
            "title": "高优先级准时者",
            "description": "至少 5 个高优先级任务按时完成率达到 80%。",
            "unlocked": len(high_done_with_due) >= 5 and efficiency >= 80,
        },
        {
            "id": "system_builder",
            "title": "系统建造者",
            "description": "完成 10 个 system 领域任务。",
            "unlocked": area_counts["system"] >= 10,
        },
    ]

    core_capabilities = sorted(flat_abilities, key=lambda item: (item["level"], item["xp"], item["relatedCount"]), reverse=True)[:5]

    return {
        "name": "效率管家",
        "level": level,
        "experience": {"current": xp, "next": 50, "totalCompleted": done_count, "percent": xp * 2, "totalAbilityXp": total_ability_xp},
        "abilities": abilities,
        "abilityList": flat_abilities,
        "abilityLines": ability_lines,
        "skillTrees": skill_tree_data["skillTrees"],
        "skillTreeSummary": skill_tree_data["summary"],
        "skillTreeKpis": skill_tree_data["kpis"],
        "levelLegend": skill_tree_data["levelLegend"],
        "coreCapabilities": core_capabilities,
        "achievements": achievements,
        "week": {"start": week_start.isoformat(), "end": week_end.isoformat(), "done": len(week_done), "total": len(week_total_ids)},
    }


def undo_last_change() -> dict:
    backups = backup_paths()
    if not backups:
        raise ValueError("no backups available")
    target = backups[-1]
    create_backup_snapshot("pre-undo")
    for destination in (TASKS_PATH, HISTORY_PATH):
        source = target / destination.name
        if source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            write_text(destination, json.dumps({"tasks": []}, ensure_ascii=False, indent=2) + "\n")
    append_log(f"撤销任务数据变更：恢复 {target.name}")
    return {"restored": target.name, "state": state_payload()}


def file_lines(path: Path) -> int:
    return len(read_text(path).splitlines()) if path.exists() else 0


def directory_tree() -> str:
    return """llm_todo/
  raw/
    inbox/
  data/
    tasks.json
    history.json
    capabilities.json
    agents.json
    roadmap.json
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
    character.html
    design.html
    map.html
    styles.css
    shared.js
    app.js
    character.js
    design.js
    map.js"""


def design_payload() -> dict:
    files = [
        ("scripts/llm_todo_server.py", "本地 HTTP API、任务读写、聊天分发、OpenAI/Agent Chat 边界、设计数据"),
        ("web/index.html", "任务规划工作台结构，首屏含任务、规划尺度和聊天窗口"),
        ("web/character.html", "角色概览页面结构，展示等级、能力值和成就墙"),
        ("web/design.html", "设计文档网站结构"),
        ("web/map.html", "能力地图页面结构，展示能力域、路线图和 Agent 状态"),
        ("web/styles.css", "中文任务工作台视觉系统和响应式布局"),
        ("web/shared.js", "API 客户端和 Markdown 渲染器"),
        ("web/app.js", "任务列表、文档阅读、聊天、模型提供方选择和快速创建交互"),
        ("web/character.js", "角色页面数据加载、能力雷达图和成就渲染"),
        ("web/design.js", "设计图、风险图、职责表和评审历史"),
        ("web/map.js", "能力地图数据加载、卡片展开、路线图进度和 Agent 状态渲染"),
        ("data/tasks.json", "当前任务事实源，只保存 active/waiting"),
        ("data/history.json", "已完成和已放弃任务归档"),
        ("data/capabilities.json", "能力域事实源，记录成熟度、子能力、Gap 和关联 Agent"),
        ("data/agents.json", "Agent 状态事实源，记录活跃状态、定时状态和关联能力域"),
        ("data/roadmap.json", "结构化路线图事实源，记录多时间尺度目标和开放问题"),
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
                {"from": "web/app.js", "to": "scripts/llm_todo_server.py", "label": "/api/state /api/chat /api/tasks/search /api/tasks/batch /api/tasks/update"},
                {"from": "web/character.js", "to": "scripts/llm_todo_server.py", "label": "/api/character /api/state /api/history"},
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
    if path in {"/character", "/character/"}:
        return WEB / "character.html"
    if path == "/design/":
        return WEB / "design.html"
    if path in {"/map", "/map/"}:
        return WEB / "map.html"
    if path in {"/skill-tree", "/skill-tree/"}:
        return WEB / "skill-tree.html"
    target = (WEB / path.lstrip("/")).resolve()
    if WEB not in target.parents and target != WEB:
        raise ValueError("path escapes web root")
    return target


def strip_base_path(path: str) -> str:
    """Remove BASE_PATH prefix from request path."""
    if BASE_PATH and path.startswith(BASE_PATH):
        return path[len(BASE_PATH):] or "/"
    return path


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

    def send_sse_stream(self, generator):
        """发送 SSE 流式响应"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for chunk in generator:
                if isinstance(chunk, str):
                    self.wfile.write(chunk.encode("utf-8"))
                else:
                    self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        # SSE 结束标记
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        # Inject <base> tag into HTML files when BASE_PATH is set
        if BASE_PATH and path.suffix == ".html":
            html = data.decode("utf-8", errors="replace")
            base_tag = f'<base href="{BASE_PATH}/">'
            if "<head>" in html:
                html = html.replace("<head>", f"<head>{base_tag}", 1)
            else:
                html = base_tag + html
            data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, path: str) -> bool:
        self.agent_info = None
        self.is_admin = False
        if not path.startswith("/api/"):
            return True
        if path == "/api/auth/login":
            return True
        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {AUTH_TOKEN}" if AUTH_TOKEN else ""
        if expected and auth_header == expected:
            self.is_admin = True
            return True
        if auth_header.startswith("Bearer "):
            agent = verify_agent_jwt(auth_header[7:].strip())
            if agent:
                self.agent_info = agent
                return True
        if not AUTH_TOKEN:
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", 'Bearer realm="LLM Todo"')
        data = json.dumps({"error": "unauthorized"}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return False

    def require_admin(self) -> bool:
        if self.is_admin:
            return True
        self.send_json({"error": "admin authorization required"}, 403)
        return False

    def require_agent(self) -> bool:
        if self.agent_info:
            return True
        self.send_json({"error": "agent authorization required"}, 403)
        return False

    def read_json_body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0") or "0")
        payload = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = strip_base_path(parsed.path)
        if not self.authorized(path):
            return
        query = urllib.parse.parse_qs(parsed.query)
        capability_match = re.fullmatch(r"/api/capabilities/([^/]+)", path)
        try:
            if path == "/api/health":
                self.send_json({"ok": True, "root": str(ROOT), "stats": stats()})
            elif path == "/api/state":
                self.send_json(state_payload())
            elif path == "/api/stats":
                self.send_json(stats())
            elif path == "/api/tasks":
                self.send_json({"tasks": sorted_tasks(load_tasks())})
            elif path == "/api/tasks/mine":
                if not self.require_agent():
                    return
                self.send_json({"agent": self.agent_info, "tasks": tasks_for_agent(self.agent_info)})
            elif path == "/api/history":
                self.send_json({"tasks": sorted_history(load_history())})
            elif path == "/api/reminders":
                self.send_json(reminders_payload())
            elif path == "/api/character":
                self.send_json(character_payload())
            elif path == "/api/skill-tree":
                self.send_json(skill_tree_payload())
            elif path == "/api/docs":
                self.send_json({"docs": doc_records()})
            elif path == "/api/doc":
                target = safe_project_path(query.get("path", [""])[0])
                frontmatter, body = split_frontmatter(read_text(target))
                self.send_json({"path": rel(target), "frontmatter": frontmatter, "markdown": body})
            elif path == "/api/design":
                self.send_json(design_payload())
            elif path == "/api/review":
                self.send_json(review_payload())
            elif path == "/api/reviews":
                self.send_json(review_history())
            elif path == "/api/capabilities":
                self.send_json(capabilities_payload())
            elif capability_match:
                domain_id = urllib.parse.unquote(capability_match.group(1))
                domain = find_by_id(capabilities_payload()["domains"], domain_id)
                self.send_json({"domain": domain} if domain else {"error": "capability not found"}, 200 if domain else 404)
            elif path == "/api/agents-status":
                self.send_json(agents_payload())
            elif path == "/api/agents":
                if not self.require_admin():
                    return
                self.send_json({"agents": load_agents()["agents"]})
            elif path == "/api/roadmap":
                self.send_json(roadmap_payload())
            else:
                self.send_file(safe_web_path(path))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = strip_base_path(parsed.path)
        if not self.authorized(path):
            return
        size = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
            if path == "/api/auth/login":
                agent = verify_agent(payload.get("name"), payload.get("token"))
                if not agent:
                    self.send_json({"error": "invalid agent credentials"}, 401)
                    return
                self.send_json({"jwt": create_agent_session(agent), "agent": agent})
            elif path == "/api/chat":
                self.send_json(dispatch_chat(payload))
            elif path == "/api/chat/stream":
                self.send_sse_stream(dispatch_stream_chat(payload))
            elif path == "/api/tasks/create":
                self.send_json(create_task(payload))
            elif path == "/api/tasks/update":
                self.send_json(update_task(payload))
            elif path == "/api/tasks/search":
                self.send_json(search_tasks(payload))
            elif path == "/api/tasks/batch":
                self.send_json(batch_tasks(payload))
            elif path == "/api/agents":
                if not self.require_admin():
                    return
                try:
                    agent = create_agent_account(payload)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, 400)
                    return
                self.send_json({"agent": agent, "agents": load_agents()["agents"]}, 201)
            elif path == "/api/sync":
                self.send_json(sync_to_remote(payload.get("url", ""), payload.get("token", "")))
            elif path == "/api/undo":
                self.send_json(undo_last_change())
            elif path == "/api/review/save":
                self.send_json(save_review(payload))
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_PUT(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = strip_base_path(parsed.path)
        if not self.authorized(path):
            return
        capability_match = re.fullmatch(r"/api/capabilities/([^/]+)", path)
        agent_match = re.fullmatch(r"/api/agents-status/([^/]+)", path)
        skill_match = re.fullmatch(r"/api/skill-tree/([^/]+)", path)
        try:
            payload = self.read_json_body()
            if capability_match:
                domain_id = urllib.parse.unquote(capability_match.group(1))
                domain = update_capability(domain_id, payload)
                self.send_json({"domain": domain, "domains": capabilities_payload()["domains"]} if domain else {"error": "capability not found"}, 200 if domain else 404)
            elif agent_match:
                agent_id = urllib.parse.unquote(agent_match.group(1))
                agent = update_agent_status(agent_id, payload)
                self.send_json({"agent": agent, "agents": agents_payload()["agents"]} if agent else {"error": "agent not found"}, 200 if agent else 404)
            elif skill_match:
                skill_id = urllib.parse.unquote(skill_match.group(1))
                result = update_skill_node(skill_id, payload)
                self.send_json(result if result else {"error": "skill not found"}, 200 if result else 404)
            elif path == "/api/roadmap":
                self.send_json(update_roadmap(payload))
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = strip_base_path(parsed.path)
        if not self.authorized(path):
            return
        try:
            payload = self.read_json_body()
            task_match = re.fullmatch(r"/api/tasks/([^/]+)", path)
            if task_match:
                if not self.require_agent():
                    return
                task_id = urllib.parse.unquote(task_match.group(1))
                result, status = update_agent_task_sub_status(task_id, self.agent_info, payload)
                self.send_json(result, status)
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = strip_base_path(parsed.path)
        if not self.authorized(path):
            return
        try:
            agent_match = re.fullmatch(r"/api/agents/([^/]+)", path)
            if agent_match:
                if not self.require_admin():
                    return
                agent_name = urllib.parse.unquote(agent_match.group(1))
                data = load_agents()
                before = len(data["agents"])
                data["agents"] = [a for a in data["agents"] if a.get("name") != agent_name]
                if len(data["agents"]) == before:
                    self.send_json({"error": "agent not found"}, 404)
                    return
                save_agents(data)
                self.send_json({"deleted": agent_name, "agents": load_agents()["agents"]})
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    port = int(os.environ.get("LLM_TODO_PORT", "8720"))
    host = os.environ.get("LLM_TODO_HOST", "127.0.0.1")
    DATA.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
