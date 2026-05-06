let state = null;
let activeDoc = "todo/index.md";
let chatMessages = [];

const statusLabels = { active: "进行中", waiting: "等待中", done: "已完成", dropped: "已放弃" };
const horizonLabels = { today: "今天", week: "本周", month: "本月", quarter: "季度", year: "年度", decade: "十年", lifetime: "人生" };
const areaLabels = { system: "系统", life: "生活", learning: "学习", work: "工作" };
const priorityLabels = { high: "高", medium: "中", low: "低" };
const kindLabels = { index: "索引", horizon: "时间尺度", area: "领域", log: "日志", review: "评审", page: "页面" };

function providerValue() {
  return document.getElementById("provider-select").value || "local-planner";
}

function renderStats() {
  document.getElementById("task-count").textContent = `${state.stats.active} 个进行中 / 共 ${state.stats.tasks} 个`;
  document.getElementById("stat-strip").innerHTML = `
    <span><strong>${state.stats.active}</strong> 进行中</span>
    <span><strong>${state.stats.done}</strong> 已完成</span>
    <span><strong>${state.stats.planningDocs}</strong> 规划页</span>
    <span><strong>${Object.keys(state.stats.byArea).length}</strong> 领域</span>
  `;
  document.getElementById("provider-select").innerHTML = state.stats.providers
    .map((provider) => `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.name)}${provider.configured ? "" : " (未配置)"}</option>`)
    .join("");
}

function renderHorizons() {
  const labels = [
    ["lifetime", "人生尺度"],
    ["year", "年度尺度"],
    ["quarter", "季度尺度"],
  ];
  document.getElementById("horizon-band").innerHTML = labels
    .map(([key, label]) => `<button type="button" data-doc="todo/horizons/${key}.md"><strong>${label}</strong><span>${escapeHtml(state.plans[key] || "暂无摘要")}</span></button>`)
    .join("");
}

function renderTasks() {
  const filter = document.getElementById("status-filter").value;
  const tasks = state.tasks.filter((task) => filter === "all" || task.status === filter);
  document.getElementById("task-list").innerHTML =
    tasks.length === 0
      ? '<p class="empty">没有匹配任务。</p>'
      : tasks
          .map(
            (task) => `
              <article class="task-item ${escapeHtml(task.status)}">
                <div>
                  <strong>${escapeHtml(task.title)}</strong>
                  <span>${escapeHtml(horizonLabels[task.horizon] || task.horizon)} · ${escapeHtml(areaLabels[task.area] || task.area)} · ${escapeHtml(priorityLabels[task.priority] || task.priority)}优先级${task.due ? ` · 截止 ${escapeHtml(task.due)}` : ""}</span>
                  <p>${escapeHtml(task.nextAction || task.notes || "未记录下一步")}</p>
                </div>
                <div class="task-actions">
                  ${task.status === "active" ? `<button type="button" data-action="done" data-id="${escapeHtml(task.id)}">完成</button><button type="button" data-action="waiting" data-id="${escapeHtml(task.id)}">等待</button>` : ""}
                  ${task.status !== "active" ? `<button type="button" data-action="active" data-id="${escapeHtml(task.id)}">恢复</button>` : ""}
                </div>
              </article>
            `,
          )
          .join("");
}

function renderDocs() {
  const groups = ["index", "horizon", "area", "log", "review"];
  const docs = [...state.docs].sort((a, b) => groups.indexOf(a.kind) - groups.indexOf(b.kind) || a.path.localeCompare(b.path));
  document.getElementById("doc-list").innerHTML = docs
    .map(
      (doc) => `
        <button type="button" class="${doc.path === activeDoc ? "active" : ""}" data-doc="${escapeHtml(doc.path)}">
          <strong>${escapeHtml(doc.title)}</strong>
          <span>${escapeHtml(kindLabels[doc.kind] || doc.kind)} · ${doc.lines} 行</span>
        </button>
      `,
    )
    .join("");
}

async function loadDoc(path) {
  activeDoc = path;
  renderDocs();
  const data = await api(`/api/doc?path=${encodeURIComponent(path)}`);
  document.getElementById("doc-reader").innerHTML = renderMarkdown(data.markdown);
}

function resolveDocPath(link) {
  if (link.startsWith("todo/")) return link;
  const base = activeDoc.split("/").slice(0, -1);
  for (const part of link.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") base.pop();
    else base.push(part);
  }
  return base.join("/");
}

async function refresh() {
  state = await api("/api/state");
  const currentProvider = providerValue();
  renderStats();
  if ([...document.getElementById("provider-select").options].some((option) => option.value === currentProvider)) {
    document.getElementById("provider-select").value = currentProvider;
  }
  renderHorizons();
  renderTasks();
  renderDocs();
}

function renderChat() {
  document.getElementById("chat-messages").innerHTML =
    chatMessages.length === 0
      ? '<p class="empty">这是主入口。可以问“今天下一步是什么”，也可以说“新增任务 本周整理长期规划”。</p>'
      : chatMessages
          .map((message) => `<div class="chat-message ${escapeHtml(message.role)}">${escapeHtml(message.content)}</div>`)
          .join("");
  const box = document.getElementById("chat-messages");
  box.scrollTop = box.scrollHeight;
}

async function sendChat(content) {
  chatMessages.push({ role: "user", content });
  renderChat();
  chatMessages.push({ role: "assistant", content: "处理中..." });
  renderChat();
  const response = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({ provider: providerValue(), messages: chatMessages.filter((item) => item.content !== "处理中...") }),
  });
  chatMessages = chatMessages.filter((item) => item.content !== "处理中...");
  chatMessages.push({ role: "assistant", content: response.text });
  state = response.state;
  renderStats();
  renderHorizons();
  renderTasks();
  renderDocs();
  renderChat();
}

async function init() {
  setText("server-url", window.location.origin + "/");
  await refresh();
  await loadDoc(activeDoc);
  renderChat();

  document.getElementById("status-filter").addEventListener("change", renderTasks);

  document.getElementById("quick-task-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = document.getElementById("quick-task-title").value.trim();
    if (!title) return;
    const response = await api("/api/tasks/create", { method: "POST", body: JSON.stringify({ title, horizon: "week", area: "life", priority: "medium" }) });
    document.getElementById("quick-task-title").value = "";
    state = response.state;
    renderStats();
    renderTasks();
  });

  document.getElementById("task-list").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const response = await api("/api/tasks/update", { method: "POST", body: JSON.stringify({ id: button.dataset.id, status: button.dataset.action }) });
    state = response.state;
    renderStats();
    renderTasks();
    renderDocs();
  });

  document.getElementById("doc-list").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-doc]");
    if (button) await loadDoc(button.dataset.doc);
  });

  document.getElementById("horizon-band").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-doc]");
    if (button) await loadDoc(button.dataset.doc);
  });

  document.getElementById("doc-reader").addEventListener("click", async (event) => {
    const link = event.target.closest("a[data-doc-link]");
    if (!link) return;
    event.preventDefault();
    await loadDoc(resolveDocPath(link.dataset.docLink));
  });

  document.getElementById("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("chat-input");
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    await sendChat(content);
  });
}

init().catch((error) => {
  document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
});
