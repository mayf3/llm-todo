let state = null;
let historyState = { tasks: [] };
let activeDoc = "todo/index.md";
let chatMessages = [];
let activeView = "tasks";
let ganttWeekOffset = 0;
let activeIndexTab = "tasks";
let taskGroupCollapsed = { now: false, week: false, future: false };
let draftState = { tasks: [], stats: null };
let draftSelectedIds = new Set();

const statusLabels = { active: "进行中", waiting: "等待中", done: "已完成", dropped: "已放弃", draft: "需求池", archived: "已归档" };
const horizonLabels = { today: "今天", week: "本周", month: "本月", quarter: "季度", year: "年度", decade: "十年", lifetime: "人生" };
const areaLabels = { system: "系统", life: "生活", learning: "学习", work: "工作" };
const priorityLabels = { high: "高", medium: "中", low: "低" };
const kindLabels = { index: "索引", horizon: "时间尺度", area: "领域", log: "日志", review: "评审", page: "页面" };
const priorityMarks = { high: "🔴", medium: "🟡", low: "⚪" };
const typeLabels = { personal: "个人", agent: "Agent", review: "评审", discuss: "讨论" };
const typeColors = { personal: "#1677ff", agent: "#52c41a", review: "#fa8c16", discuss: "#722ed1" };
const horizonRanks = { today: 0, week: 1, month: 2, quarter: 3, year: 4, decade: 5, lifetime: 6 };
const horizonDocLabels = [
  ["lifetime", "人生尺度"],
  ["decade", "十年尺度"],
  ["year", "年度尺度"],
  ["quarter", "季度尺度"],
  ["month", "月度尺度"],
  ["week", "本周尺度"],
  ["today", "今天尺度"],
];
const taskGroupConfig = [
  { id: "now", title: "🔴 现在就做", note: "今日到期、已过期，或高优先级且近期" },
  { id: "week", title: "🟡 本周待办", note: "本周内到期，或已有明确下一步" },
  { id: "future", title: "⚪ 未来 / 待定", note: "长期事项、低优先级或待明确下一步" },
];

function tabFromHash() {
  const tab = window.location.hash.replace(/^#/, "");
  return ["tasks", "planning", "chat"].includes(tab) ? tab : "tasks";
}

function renderIndexTab() {
  activeIndexTab = tabFromHash();
  document.querySelectorAll("[data-index-tab-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.indexTabPanel !== activeIndexTab;
  });
  if (typeof updateMainNavigation === "function") updateMainNavigation(activeIndexTab);
}

function providerValue() {
  return document.getElementById("provider-select").value || "local-planner";
}

function parseDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function todayStart() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function weekEnd() {
  const today = todayStart();
  const day = today.getDay() || 7;
  const end = new Date(today);
  end.setDate(today.getDate() + (7 - day));
  return end;
}

function hasNextAction(task) {
  return Boolean(String(task.nextAction || "").trim());
}

function horizonRank(value) {
  return horizonRanks[value] ?? 99;
}

function isDueNow(task) {
  const due = parseDate(task.due);
  return Boolean(due && due <= todayStart());
}

function isDueThisWeek(task) {
  const due = parseDate(task.due);
  const today = todayStart();
  return Boolean(due && due > today && due <= weekEnd());
}

function taskGroupId(task) {
  if (isDueNow(task) || (task.priority === "high" && horizonRank(task.horizon) <= horizonRanks.week)) return "now";
  if (isDueThisWeek(task) || (task.priority === "medium" && hasNextAction(task)) || (task.priority === "high" && horizonRank(task.horizon) > horizonRanks.week)) return "week";
  if (horizonRank(task.horizon) >= horizonRanks.month || task.priority === "low" || !hasNextAction(task)) return "future";
  return "future";
}

function taskDateSortValue(task) {
  return task.due || "9999-99-99";
}

function priorityRank(task) {
  return { high: 0, medium: 1, low: 2 }[task.priority] ?? 3;
}

function sortTasks(tasks) {
  return [...tasks].sort((a, b) => {
    return priorityRank(a) - priorityRank(b) || taskDateSortValue(a).localeCompare(taskDateSortValue(b)) || String(b.updated || b.created || "").localeCompare(String(a.updated || a.created || ""));
  });
}

function renderStats() {
  const total = state.stats.total ?? state.stats.tasks;
  document.getElementById("task-count").textContent = `${state.stats.active} 个进行中 / 共 ${total} 个`;
  const strip = document.getElementById("stat-strip");
  if (strip) {
    strip.innerHTML = `
      <span><strong>${state.stats.active}</strong> 进行中</span>
      <span><strong>${state.stats.done}</strong> 已完成</span>
      <span><strong>${state.stats.dropped || 0}</strong> 已放弃</span>
      <span><strong>${state.stats.planningDocs}</strong> 规划页</span>
      <span><strong>${Object.keys(state.stats.byArea).length}</strong> 领域</span>
    `;
  }
  document.getElementById("provider-select").innerHTML = state.stats.providers
    .map((provider) => `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.name)}${provider.configured ? "" : " (未配置)"}</option>`)
    .join("");
}

function optionHtml(value, label, selectedValue) {
  return `<option value="${escapeHtml(value)}" ${value === selectedValue ? "selected" : ""}>${escapeHtml(label)}</option>`;
}

function uniqueValues(tasks, key) {
  return [...new Set(tasks.map((task) => task[key]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
}

function renderTaskFilterOptions() {
  const tasks = Array.isArray(state.tasks) ? state.tasks : [];
  const horizonFilter = document.getElementById("horizon-filter");
  const areaFilter = document.getElementById("area-filter");
  const priorityFilter = document.getElementById("priority-filter");
  const tagFilter = document.getElementById("tag-filter");
  const typeFilter = document.getElementById("type-filter");
  const previous = {
    horizon: horizonFilter.value,
    area: areaFilter.value,
    priority: priorityFilter.value,
    tag: tagFilter.value,
    type: typeFilter ? typeFilter.value : "",
  };

  horizonFilter.innerHTML = optionHtml("", "全部时间尺度", previous.horizon) + uniqueValues(tasks, "horizon").map((value) => optionHtml(value, horizonLabels[value] || value, previous.horizon)).join("");
  areaFilter.innerHTML = optionHtml("", "全部领域", previous.area) + uniqueValues(tasks, "area").map((value) => optionHtml(value, areaLabels[value] || value, previous.area)).join("");
  priorityFilter.innerHTML = optionHtml("", "全部优先级", previous.priority) + ["high", "medium", "low"].map((value) => optionHtml(value, `${priorityMarks[value] || ""} ${priorityLabels[value] || value}`, previous.priority)).join("");
  const tags = [...new Set(tasks.flatMap((task) => (Array.isArray(task.tags) ? task.tags : [])))].sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
  tagFilter.innerHTML = optionHtml("", "全部标签", previous.tag) + tags.map((value) => optionHtml(value, `#${value}`, previous.tag)).join("");

  if (typeFilter) {
    typeFilter.innerHTML = optionHtml("", "全部类型", previous.type) + Object.entries(typeLabels).map(([value, label]) => optionHtml(value, label, previous.type)).join("");
  }
}

function renderTags(task) {
  const tags = Array.isArray(task.tags) ? task.tags : [];
  if (tags.length === 0) return "";
  return `<div class="tag-list">${tags.map((tag) => `<span>#${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function taskMeta(task, includeStatus = false) {
  const parts = [
    horizonLabels[task.horizon] || task.horizon,
    areaLabels[task.area] || task.area,
    task.priority ? `${priorityMarks[task.priority] || "⚪"} ${priorityLabels[task.priority] || task.priority}优先级` : "",
  ];
  if (includeStatus) parts.unshift(statusLabels[task.status] || task.status);
  if (task.due) parts.push(`截止 ${task.due}`);
  if (task.updated) parts.push(`更新 ${task.updated}`);
  return parts.filter(Boolean).map(escapeHtml).join(" · ");
}

function renderViewTabs() {
  document.querySelectorAll("[data-task-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.taskView === activeView);
  });
  document.getElementById("task-panel").hidden = activeView !== "tasks";
  document.getElementById("history-panel").hidden = activeView !== "history";
  document.getElementById("week-panel").hidden = activeView !== "week";
  document.getElementById("gantt-panel").hidden = activeView !== "gantt";
  document.getElementById("draft-panel").hidden = activeView !== "draft";
  document.getElementById("status-filter").hidden = activeView !== "tasks";
  if (activeView === "week") renderWeekPlan();
  if (activeView === "gantt") renderGantt();
  if (activeView === "draft") loadAndRenderDraft();
}

// ===== Week Plan =====
function getWeekDateRange() {
  const now = new Date();
  const dayOfWeek = now.getDay(); // 0=Sun, 1=Mon...
  const diff = dayOfWeek === 0 ? 6 : dayOfWeek - 1; // Mon=0 offset
  const monday = new Date(now);
  monday.setDate(now.getDate() - diff);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);

  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    days.push(d);
  }
  return { monday, sunday, days, today: now };
}

function formatDateShort(d) {
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
}

function renderWeekPlan() {
  const { monday, sunday, days, today } = getWeekDateRange();
  const dayNames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const todayStr = today.toISOString().slice(0, 10);

  // Update header
  const weekStart = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
  const weekEnd = `${sunday.getFullYear()}-${String(sunday.getMonth() + 1).padStart(2, "0")}-${String(sunday.getDate()).padStart(2, "0")}`;
  document.getElementById("week-range").textContent = `${weekStart} ~ ${weekEnd}`;

  // Group tasks by day
  const tasks = state?.tasks || [];
  const dayTasks = {};
  const unscheduled = [];
  const allDueThisWeek = [];

  days.forEach((d) => {
    const key = d.toISOString().slice(0, 10);
    dayTasks[key] = [];
  });

  tasks.forEach((task) => {
    if (task.status === "done" || task.status === "dropped") return; // skip completed
    const due = task.due;
    if (due) {
      // Check if due date falls within this week
      const dueDate = new Date(due);
      if (dueDate >= new Date(weekStart) && dueDate <= new Date(weekEnd + "T23:59:59")) {
        const dueKey = due;
        if (dayTasks[dueKey]) {
          dayTasks[dueKey].push(task);
        } else {
          unscheduled.push(task);
        }
        allDueThisWeek.push(task);
      } else if (due < weekStart && task.status === "active") {
        // Overdue: show on Monday
        dayTasks[weekStart].push(task);
      } else if (task.horizon === "week" || task.horizon === "today") {
        unscheduled.push(task);
      }
    } else if (task.horizon === "week" || task.horizon === "today") {
      unscheduled.push(task);
    }
  });

  // Count total and done
  const totalWeek = allDueThisWeek.length;
  const doneCount = allDueThisWeek.filter((t) => t.status === "done").length;
  const pct = totalWeek > 0 ? Math.round((doneCount / totalWeek) * 100) : 0;

  document.getElementById("week-progress").innerHTML = `
    <div class="week-progress-fill" style="width:${pct}%"></div>
  `;

  // Render grid
  const grid = document.getElementById("week-grid");
  grid.innerHTML = days
    .map((d, i) => {
      const key = d.toISOString().slice(0, 10);
      const items = dayTasks[key] || [];
      const isToday = isSameDay(d, today);
      const dayLabel = `${dayNames[i]} ${formatDateShort(d)}`;

      const taskHtml = items
        .sort((a, b) => (a.priority === "high" ? -1 : 1))
        .map((task) => {
          const priorityIcon = task.priority === "high" ? "🔴" : task.priority === "medium" ? "🟡" : "⚪";
          const taskType = task.type || "personal";
          const typeColor = typeColors[taskType] || "#1677ff";
          const typeLabel = typeLabels[taskType] || taskType;
          const statusIcon = task.status === "active" ? "" : `[${escapeHtml(statusLabels[task.status] || task.status)}]`;
          return `<div class="week-task-item ${escapeHtml(task.status)}" data-task-id="${escapeAttr(task.id)}" title="${escapeAttr(task.title)}">
            <span class="week-task-title">${priorityIcon} ${escapeHtml(task.title)}</span>
            <span class="week-task-meta">${statusIcon} ${escapeHtml(task.area ? areaLabels[task.area] || task.area : "")}</span>
            <span style="display:inline-block;padding:0 6px;border-radius:3px;background:${typeColor}20;color:${typeColor};font-size:10px;margin-top:2px;">${escapeHtml(typeLabel)}</span>
            <span class="week-task-actions" style="display:flex;gap:4px;margin-top:4px;">
              ${task.status === "active" ? `<button type="button" data-action="done" data-id="${escapeAttr(task.id)}" style="font-size:0.65rem;padding:1px 6px;">✅</button><button type="button" data-action="waiting" data-id="${escapeAttr(task.id)}" style="font-size:0.65rem;padding:1px 6px;">⏳</button>` : ""}
              ${task.status === "waiting" ? `<button type="button" data-action="active" data-id="${escapeAttr(task.id)}" style="font-size:0.65rem;padding:1px 6px;">▶️</button><button type="button" data-action="done" data-id="${escapeAttr(task.id)}" style="font-size:0.65rem;padding:1px 6px;">✅</button>` : ""}
              <button type="button" data-action="dropped" data-id="${escapeAttr(task.id)}" style="font-size:0.65rem;padding:1px 6px;">❌</button>
            </span>
          </div>`;
        })
        .join("");

      return `<div class="week-day-card">
        <div class="week-day-header${isToday ? " today" : ""}">
          <span>${dayLabel}</span>
          <span class="week-day-count">${items.length}</span>
        </div>
        <div class="week-day-body">
          ${items.length > 0 ? taskHtml : '<div class="week-empty" style="padding:12px;font-size:0.8rem">—</div>'}
        </div>
      </div>`;
    })
    .join("");

  // Unscheduled section
  if (unscheduled.length > 0) {
    const unsatHtml = unscheduled
      .map((task) => {
        const priorityIcon = task.priority === "high" ? "🔴" : task.priority === "medium" ? "🟡" : "⚪";
        const taskType = task.type || "personal";
        const typeColor = typeColors[taskType] || "#1677ff";
        const typeLabel = typeLabels[taskType] || taskType;
        return `<div class="week-task-item ${escapeHtml(task.status)}" data-task-id="${escapeAttr(task.id)}" title="${escapeAttr(task.title)}">
          <span class="week-task-title">${priorityIcon} ${escapeHtml(task.title)}</span>
          <span class="week-task-meta">${escapeHtml(task.area ? areaLabels[task.area] || task.area : "")} · 未安排日期</span>
          <span style="display:inline-block;padding:0 6px;border-radius:3px;background:${typeColor}20;color:${typeColor};font-size:10px;">${escapeHtml(typeLabel)}</span>
        </div>`;
      })
      .join("");

    grid.insertAdjacentHTML("afterend", `<div class="week-unscheduled">
      <h3>📌 待安排 (${unscheduled.length})</h3>
      <div class="week-unscheduled-list">${unsatHtml}</div>
    </div>`);
  }
}

function escapeAttr(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function taskMatchesFilters(task) {
  const status = document.getElementById("status-filter").value;
  const keyword = document.getElementById("task-search").value.trim().toLowerCase();
  const horizon = document.getElementById("horizon-filter").value;
  const area = document.getElementById("area-filter").value;
  const priority = document.getElementById("priority-filter").value;
  const tag = document.getElementById("tag-filter").value;
  const typeEl = document.getElementById("type-filter");
  const type = typeEl ? typeEl.value : "";
  const tags = Array.isArray(task.tags) ? task.tags : [];
  const haystack = `${task.title || ""} ${task.nextAction || ""} ${task.notes || ""} ${tags.join(" ")}`.toLowerCase();
  return (
    (status === "all" || task.status === status) &&
    (!keyword || haystack.includes(keyword)) &&
    (!horizon || task.horizon === horizon) &&
    (!area || task.area === area) &&
    (!priority || task.priority === priority) &&
    (!tag || tags.includes(tag)) &&
    (!type || (task.type || "personal") === type)
  );
}

function renderTaskCard(task, includeStatus = false) {
  const taskType = task.type || "personal";
  const typeColor = typeColors[taskType] || "#1677ff";
  const typeLabel = typeLabels[taskType] || taskType;
  return `
    <article class="task-item ${escapeHtml(task.status)} urgency-${escapeHtml(taskGroupId(task))}">
      <div>
        <strong>${escapeHtml(task.title)}</strong>
        <span style="display:inline-block;padding:1px 8px;border-radius:4px;background:${typeColor}20;color:${typeColor};font-size:11px;margin-left:6px;vertical-align:middle;">${escapeHtml(typeLabel)}</span>
        <span>${taskMeta(task, includeStatus)}</span>
        ${renderTags(task)}
        <p>${escapeHtml(task.nextAction || task.notes || "未记录下一步")}</p>
      </div>
      <div class="task-actions">
        ${task.status === "active" ? `<button type="button" data-action="done" data-id="${escapeHtml(task.id)}">完成</button><button type="button" data-action="waiting" data-id="${escapeHtml(task.id)}">等待</button>` : ""}
        ${task.status === "waiting" ? `<button type="button" data-action="active" data-id="${escapeHtml(task.id)}">恢复</button><button type="button" data-action="done" data-id="${escapeHtml(task.id)}">完成</button>` : ""}
        <button type="button" data-action="dropped" data-id="${escapeHtml(task.id)}">放弃</button>
      </div>
    </article>
  `;
}

function renderHorizons() {
  const docPaths = new Set((state.docs || []).map((doc) => doc.path));
  document.getElementById("horizon-band").innerHTML = horizonDocLabels
    .map(([key, label]) => {
      const path = `todo/horizons/${key}.md`;
      const hasDoc = docPaths.has(path);
      return `<button type="button" ${hasDoc ? `data-doc="${escapeHtml(path)}"` : "disabled"}><strong>${label}</strong><span>${escapeHtml(state.plans[key] || (hasDoc ? "暂无摘要" : "暂未建档"))}</span></button>`;
    })
    .join("");
}

function renderPlanningDashboard() {
  // Planning dashboard moved to /map page
  // Quick link cards shown in index.html for navigation
}

function renderTasks() {
  const tasks = sortTasks(state.tasks.filter(taskMatchesFilters));
  const grouped = { now: [], week: [], future: [] };
  tasks.forEach((task) => grouped[taskGroupId(task)].push(task));
  const total = tasks.length;
  document.getElementById("task-list").innerHTML =
    total === 0
      ? '<p class="empty">没有匹配任务。</p>'
      : taskGroupConfig
          .map((group) => {
            const items = grouped[group.id] || [];
            const collapsed = taskGroupCollapsed[group.id];
            return `
              <section class="task-group task-group-${escapeHtml(group.id)}">
                <button type="button" class="task-group-head" data-task-group="${escapeHtml(group.id)}" aria-expanded="${collapsed ? "false" : "true"}">
                  <span>
                    <strong>${escapeHtml(group.title)} (${items.length})</strong>
                    <small>${escapeHtml(group.note)}</small>
                  </span>
                  <span class="collapse-mark">${collapsed ? "展开" : "收起"}</span>
                </button>
                <div class="task-group-body" ${collapsed ? "hidden" : ""}>
                  ${items.length === 0 ? '<p class="empty">这一组暂时没有任务。</p>' : items.map((task) => renderTaskCard(task)).join("")}
                </div>
              </section>
            `;
          })
          .join("");
}

function renderHistory() {
  const tasks = historyState.tasks || [];
  document.getElementById("history-list").innerHTML =
    tasks.length === 0
      ? '<p class="empty">暂无已完成或已放弃任务。</p>'
      : tasks
          .map(
            (task) => {
              const taskType = task.type || "personal";
              const typeColor = typeColors[taskType] || "#1677ff";
              const typeLabel = typeLabels[taskType] || taskType;
              return `
              <article class="task-item ${escapeHtml(task.status)} archived">
                <div>
                  <strong>${escapeHtml(task.title)} <span style="display:inline-block;padding:1px 8px;border-radius:4px;background:${typeColor}20;color:${typeColor};font-size:11px;margin-left:6px;vertical-align:middle;">${escapeHtml(typeLabel)}</span></strong>
                  <span>${taskMeta(task, true)}</span>
                  ${renderTags(task)}
                  <p>${escapeHtml(task.nextAction || task.notes || "未记录下一步")}</p>
                </div>
                <div class="task-actions">
                  <button type="button" data-action="active" data-id="${escapeHtml(task.id)}">恢复</button>
                </div>
              </article>
            `;
            })
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
  const [nextState] = await Promise.all([
    api("/api/state"),
  ]);
  let nextHistory = { tasks: nextState.history || [] };
  try {
    nextHistory = await api("/api/history");
  } catch (error) {
    console.warn("历史任务接口暂不可用，使用 /api/state 中的历史数据。", error);
  }
  state = nextState;
  historyState = nextHistory;
  const currentProvider = providerValue();
  renderStats();
  if ([...document.getElementById("provider-select").options].some((option) => option.value === currentProvider)) {
    document.getElementById("provider-select").value = currentProvider;
  }
  renderTaskFilterOptions();
  renderHorizons();
  renderPlanningDashboard();
  renderViewTabs();
  renderTasks();
  renderHistory();
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

  const provider = providerValue();
  // 判断是否支持流式输出
  const streamingProviders = ["openai-compat", "glm"];
  const useStream = streamingProviders.includes(provider);

  if (useStream) {
    await sendChatStream(content, provider);
  } else {
    await sendChatSync(content, provider);
  }
}

async function sendChatSync(content, provider) {
  const response = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({ provider, messages: chatMessages.filter((item) => item.content !== "处理中...") }),
  });
  chatMessages = chatMessages.filter((item) => item.content !== "处理中...");
  chatMessages.push({ role: "assistant", content: response.text });
  state = response.state;
  historyState = { tasks: response.state.history || historyState.tasks };
  renderStats();
  renderTaskFilterOptions();
  renderHorizons();
  renderViewTabs();
  renderTasks();
  renderHistory();
  renderDocs();
  renderChat();
}

async function sendChatStream(content, provider) {
  // 移除 "处理中..." 占位
  chatMessages = chatMessages.filter((item) => item.content !== "处理中...");
  chatMessages.push({ role: "assistant", content: "" });
  const assistantIndex = chatMessages.length - 1;

  const token = tokenValue();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers,
      body: JSON.stringify({ provider, messages: chatMessages.filter((item) => item.role !== "assistant" || item.content !== "") }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: response.statusText }));
      chatMessages[assistantIndex] = { role: "assistant", content: `错误: ${errorData.error || response.statusText}` };
      renderChat();
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        const payload = trimmed.slice(6);
        if (payload === "[DONE]") continue;

        try {
          const data = JSON.parse(payload);
          if (data.error) {
            chatMessages[assistantIndex] = { role: "assistant", content: `错误: ${data.error}` };
            renderChat();
            return;
          }
          if (data.content) {
            fullText += data.content;
            chatMessages[assistantIndex] = { role: "assistant", content: fullText };
            renderChat();
          }
          if (data.done) {
            fullText = data.text || fullText;
            chatMessages[assistantIndex] = { role: "assistant", content: fullText };
            if (data.state) {
              state = data.state;
              historyState = { tasks: data.state.history || historyState.tasks };
              renderStats();
              renderTaskFilterOptions();
              renderHorizons();
              renderViewTabs();
              renderTasks();
              renderHistory();
              renderDocs();
            }
            renderChat();
          }
        } catch { /* ignore parse errors */ }
      }
    }
  } catch (error) {
    chatMessages[assistantIndex] = { role: "assistant", content: `网络错误: ${error.message}` };
    renderChat();
  }
}

async function updateTaskStatus(id, status) {
  const response = await api("/api/tasks/update", { method: "POST", body: JSON.stringify({ id, status }) });
  state = response.state;
  historyState = { tasks: response.state.history || historyState.tasks };
  renderStats();
  renderTaskFilterOptions();
  renderViewTabs();
  renderTasks();
  renderHistory();
  renderDocs();
}

// ===== Gantt Chart =====
function getMonday(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function shortWeekDay(d) {
  const days = ["一", "二", "三", "四", "五", "六", "日"];
  return days[d.getDay() === 0 ? 6 : d.getDay() - 1];
}

// ===== Draft Pool (需求池) =====

async function loadDraftTasks() {
  const params = new URLSearchParams({ status: "draft" });
  const searchVal = document.getElementById("draft-search").value.trim();
  if (searchVal) params.set("search", searchVal);
  const sourceVal = document.getElementById("draft-source-filter").value;
  if (sourceVal) params.set("source", sourceVal);
  const areaVal = document.getElementById("draft-area-filter").value;
  if (areaVal) params.set("area", areaVal);
  const [tasksRes, statsRes] = await Promise.all([
    api("/api/tasks?" + params.toString()),
    api("/api/tasks/draft-stats"),
  ]);
  draftState.tasks = tasksRes.tasks || [];
  draftState.stats = statsRes;
  return draftState;
}

async function loadAndRenderDraft() {
  try {
    await loadDraftTasks();
  } catch (e) { console.warn("draft load error", e); }
  renderDraftStats();
  renderDraftFilters();
  renderDraftList();
  renderDraftBatchBar();
}

function renderDraftStats() {
  const el = document.getElementById("draft-stats");
  const total = draftState.stats?.total || 0;
  el.textContent = total > 0 ? `${total} 待审批` : "无待审批";
  el.style.background = total > 0 ? "#1677ff" : "#d9d9d9";
  el.style.color = total > 0 ? "#fff" : "#999";
}

function renderDraftFilters() {
  const stats = draftState.stats;
  if (!stats) return;
  const sourceSelect = document.getElementById("draft-source-filter");
  const currentSource = sourceSelect.value;
  const sources = Object.keys(stats.bySource || {});
  sourceSelect.innerHTML = '<option value="">全部来源</option>' +
    sources.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)} (${stats.bySource[s]})</option>`).join("");
  if (sources.includes(currentSource)) sourceSelect.value = currentSource;

  const areaSelect = document.getElementById("draft-area-filter");
  const currentArea = areaSelect.value;
  const areas = Object.keys(stats.byArea || {});
  areaSelect.innerHTML = '<option value="">全部领域</option>' +
    areas.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(areaLabels[a] || a)} (${stats.byArea[a]})</option>`).join("");
  if (areas.includes(currentArea)) areaSelect.value = currentArea;
}

function renderDraftList() {
  const container = document.getElementById("draft-list");
  const tasks = draftState.tasks;
  if (!tasks.length) {
    container.innerHTML = '<p class="empty" style="text-align:center;color:var(--ink-light);padding:24px;">✨ 需求池为空</p>';
    return;
  }
  container.innerHTML = tasks.map(task => {
    const sel = draftSelectedIds.has(task.id);
    const pri = priorityMarks[task.priority] || "⚪";
    const area = task.area ? (areaLabels[task.area] || task.area) : "";
    const source = task.source || "";
    const tags = (task.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");
    const created = task.created || "";
    return `<div class="draft-card ${sel ? "selected" : ""}" data-draft-id="${escapeAttr(task.id)}">
      <input type="checkbox" class="draft-checkbox" data-draft-check="${escapeAttr(task.id)}" ${sel ? "checked" : ""} />
      <div class="draft-card-title">${pri} ${escapeHtml(task.title)}</div>
      <div class="draft-card-meta">
        ${area ? `<span class="tag">${escapeHtml(area)}</span>` : ""}
        ${source ? `<span class="tag">来源: ${escapeHtml(source)}</span>` : ""}
        ${tags}
        ${created ? `<span>${escapeHtml(created)}</span>` : ""}
      </div>
      ${task.description ? `<div style="font-size:0.82rem;color:var(--ink-light);margin-bottom:6px;">${escapeHtml(task.description).slice(0, 120)}</div>` : ""}
      <div class="draft-card-actions">
        <button type="button" class="btn-approve" data-action="draft-approve" data-id="${escapeAttr(task.id)}">✅ 批准</button>
        <button type="button" class="btn-reject" data-action="draft-reject" data-id="${escapeAttr(task.id)}">❌ 拒绝</button>
      </div>
    </div>`;
  }).join("");
}

function renderDraftBatchBar() {
  const bar = document.getElementById("draft-batch-bar");
  const countEl = document.getElementById("draft-batch-count");
  const n = draftSelectedIds.size;
  bar.hidden = n === 0;
  countEl.textContent = `已选择 ${n} 个`;
}

function escapeAttr(v) { return String(v ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }

function showProposeModal() { document.getElementById("propose-modal").hidden = false; }
function hideProposeModal() { document.getElementById("propose-modal").hidden = true; document.getElementById("propose-form").reset(); }
function showApproveModal(taskId) { document.getElementById("approve-task-id").value = taskId; document.getElementById("approve-modal").hidden = false; }
function hideApproveModal() { document.getElementById("approve-modal").hidden = false; document.getElementById("approve-form").reset(); document.getElementById("approve-modal").hidden = true; }
function showRejectModal(taskId) { document.getElementById("reject-task-id").value = taskId; document.getElementById("reject-modal").hidden = false; }
function hideRejectModal() { document.getElementById("reject-modal").hidden = true; document.getElementById("reject-form").reset(); }

async function submitPropose(e) {
  e.preventDefault();
  const title = document.getElementById("propose-title").value.trim();
  if (!title) return;
  const body = { title };
  const desc = document.getElementById("propose-desc").value.trim();
  if (desc) body.description = desc;
  const pri = document.getElementById("propose-priority").value;
  if (pri) body.priority = pri;
  const area = document.getElementById("propose-area").value;
  if (area) body.area = area;
  const source = document.getElementById("propose-source").value.trim();
  if (source) body.source = source;
  const tags = document.getElementById("propose-tags").value.trim();
  if (tags) body.tags = tags.split(",").map(t => t.trim()).filter(Boolean);
  try {
    await api("/api/tasks/propose", { method: "POST", body: JSON.stringify(body) });
    hideProposeModal();
    await loadAndRenderDraft();
  } catch (err) { alert("提交失败: " + err.message); }
}

async function submitApprove(e) {
  e.preventDefault();
  const taskId = document.getElementById("approve-task-id").value;
  const overrides = {};
  const pri = document.getElementById("approve-priority").value;
  if (pri) overrides.priority = pri;
  const area = document.getElementById("approve-area").value;
  if (area) overrides.area = area;
  const assignee = document.getElementById("approve-assignee").value.trim();
  if (assignee) overrides.assignee = assignee;
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/approve`, { method: "PATCH", body: JSON.stringify(overrides) });
    hideApproveModal();
    await loadAndRenderDraft();
    await refresh();
  } catch (err) { alert("批准失败: " + err.message); }
}

async function submitReject(e) {
  e.preventDefault();
  const taskId = document.getElementById("reject-task-id").value;
  const reason = document.getElementById("reject-reason").value.trim();
  try {
    await api(`/api/tasks/${encodeURIComponent(taskId)}/reject`, { method: "PATCH", body: JSON.stringify({ reason }) });
    hideRejectModal();
    await loadAndRenderDraft();
  } catch (err) { alert("拒绝失败: " + err.message); }
}

async function batchApproveDrafts() {
  if (draftSelectedIds.size === 0) return;
  if (!confirm(`确认批量批准 ${draftSelectedIds.size} 个需求？`)) return;
  try {
    await api("/api/tasks/batch-approve", { method: "POST", body: JSON.stringify({ taskIds: [...draftSelectedIds], action: "approve" }) });
    draftSelectedIds.clear();
    await loadAndRenderDraft();
    await refresh();
  } catch (err) { alert("批量批准失败: " + err.message); }
}

async function batchRejectDrafts() {
  if (draftSelectedIds.size === 0) return;
  const reason = prompt(`批量拒绝 ${draftSelectedIds.size} 个需求，可选填原因：`) || "";
  try {
    await api("/api/tasks/batch-approve", { method: "POST", body: JSON.stringify({ taskIds: [...draftSelectedIds], action: "reject", reason }) });
    draftSelectedIds.clear();
    await loadAndRenderDraft();
  } catch (err) { alert("批量拒绝失败: " + err.message); }
}

function renderGantt() {
  const monday = getMonday(new Date());
  monday.setDate(monday.getDate() + ganttWeekOffset * 7);
  const sunday = new Date(monday);
  sunday.setDate(sunday.getDate() + 6);

  document.getElementById("gantt-week-label").textContent =
    `${formatDate(monday)} ~ ${formatDate(sunday)}`;

  // Build 7-day columns
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(d.getDate() + i);
    days.push({
      date: formatDate(d),
      dayLabel: `周${shortWeekDay(d)}`,
      isToday: formatDate(d) === formatDate(new Date()),
      dayOfWeek: d.getDay(),
    });
  }

  // Render header row
  document.getElementById("gantt-head-row").innerHTML = days
    .map((d) => `<div class="gantt-head-cell ${d.isToday ? "today" : ""}">${d.date}<br><span>${d.dayLabel}</span></div>`)
    .join("");

  // Collect tasks with due dates in range
  const allTasks = (state?.tasks || []).filter((t) => t.status === "active" && t.due);
  const inRange = allTasks.filter((t) => {
    const due = t.due;
    return due >= formatDate(monday) && due <= formatDate(sunday);
  });

  // Sort by priority (high first), then by due
  inRange.sort((a, b) => {
    const pOrder = { high: 0, medium: 1, low: 2 };
    const pa = pOrder[a.priority] ?? 1;
    const pb = pOrder[b.priority] ?? 1;
    if (pa !== pb) return pa - pb;
    return (a.due || "").localeCompare(b.due || "");
  });

  // Empty state
  if (inRange.length === 0) {
    document.getElementById("gantt-body").innerHTML = "";
    document.getElementById("gantt-empty").hidden = false;
    return;
  }
  document.getElementById("gantt-empty").hidden = true;

  // Render task rows as bars
  const priorityColors = { high: "#ff4d4f", medium: "#faad14", low: "#d9d9d9" };
  const typeColors = window.typeColors || { personal: "#1677ff", agent: "#52c41a", review: "#fa8c16", discuss: "#722ed1" };
  const typeLabels = window.typeLabels || { personal: "个人", agent: "Agent", review: "审阅", discuss: "讨论" };
  const statusLabels = window.statusLabels || {};

  const bodyHtml = inRange
    .map((task) => {
      const due = task.due || "";
      const dayIndex = days.findIndex((d) => d.date === due);
      const offset = dayIndex >= 0 ? dayIndex : 6; // clamp to saturday
      const width = 1; // single day width
      const barColor = priorityColors[task.priority] || "#1677ff";
      const taskType = task.type || "personal";
      const tColor = typeColors[taskType] || "#1677ff";
      const tLabel = typeLabels[taskType] || taskType;
      const pLabel = { high: "高", medium: "中", low: "低" }[task.priority] || "";

      return `<div class="gantt-row" draggable="true" data-task-id="${escapeAttr(task.id)}" data-due="${escapeAttr(task.due)}">
        <div class="gantt-row-label" title="${escapeHtml(task.title)}">
          <span class="gantt-priority-badge" style="background:${barColor}20;color:${barColor};">${pLabel}</span>
          <span class="gantt-type-badge" style="background:${tColor}15;color:${tColor};">${escapeHtml(tLabel)}</span>
          <span class="gantt-title">${escapeHtml(task.title)}</span>
        </div>
        <div class="gantt-track" data-task-id="${escapeAttr(task.id)}">
          <div class="gantt-bar" style="
            left: ${offset * (100 / 7)}%;
            width: ${width * (100 / 7)}%;
            background: ${barColor};
            opacity: 0.85;
          " title="${escapeHtml(task.title)} · ${formatDate(monday)} ~ ${task.due}">
            <span class="gantt-bar-label">${escapeHtml(task.title)}</span>
          </div>
          ${days
            .map(
              (d, di) =>
                `<div class="gantt-day-slot" data-date="${d.date}" data-task-id="${escapeAttr(task.id)}" style="left:${di * (100 / 7)}%;width:${100 / 7}%"></div>`
            )
            .join("")}
        </div>
      </div>`;
    })
    .join("");

  document.getElementById("gantt-body").innerHTML = bodyHtml;
}

// ===== Task Detail Modal =====
let editTaskId = null;

function openTaskDetail(taskId) {
  const allTasks = (state?.tasks || []).concat(historyState?.tasks || []);
  const task = allTasks.find((t) => t.id === taskId);
  if (!task) return;

  editTaskId = taskId;
  document.getElementById("edit-title").value = task.title || "";
  document.getElementById("edit-due").value = task.due || "";
  document.getElementById("edit-priority").value = task.priority || "medium";
  document.getElementById("edit-horizon").value = task.horizon || "week";
  document.getElementById("edit-repeat").value = task.repeat || "";
  document.getElementById("edit-area").value = task.area || "";
  document.getElementById("edit-type").value = task.type || "personal";
  document.getElementById("edit-tags").value = Array.isArray(task.tags) ? task.tags.join(", ") : "";
  document.getElementById("edit-next-action").value = task.nextAction || "";
  document.getElementById("edit-notes").value = task.notes || "";
  document.getElementById("task-edit-title").textContent = "编辑任务";
  document.getElementById("task-edit-meta").textContent = `#${task.id} · ${statusLabels[task.status] || task.status}`;
  document.getElementById("task-modal").hidden = false;
}

function closeTaskModal() {
  document.getElementById("task-modal").hidden = true;
  editTaskId = null;
}

async function saveTaskModal(event) {
  event.preventDefault();
  if (!editTaskId) return;

  // Parse tags from comma/space separated string
  const rawTags = document.getElementById("edit-tags").value.trim();
  const tags = rawTags
    ? rawTags.split(/[,\s]+/).filter(Boolean)
    : [];

  const payload = {
    id: editTaskId,
    title: document.getElementById("edit-title").value.trim(),
    due: document.getElementById("edit-due").value,
    priority: document.getElementById("edit-priority").value,
    horizon: document.getElementById("edit-horizon").value,
    repeat: document.getElementById("edit-repeat").value,
    area: document.getElementById("edit-area").value.trim(),
    type: document.getElementById("edit-type").value,
    tags,
    nextAction: document.getElementById("edit-next-action").value.trim(),
    notes: document.getElementById("edit-notes").value.trim(),
  };

  try {
    const response = await api("/api/tasks/update", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state = response.state;
    historyState = { tasks: response.state.history || historyState.tasks };
    closeTaskModal();
    renderStats();
    renderTaskFilterOptions();
    renderViewTabs();
    renderTasks();
    renderHistory();
    renderDocs();
  } catch (error) {
    alert("保存失败: " + error.message);
  }
}

// ===== Remote Sync =====
async function triggerRemoteSync() {
  const btn = document.getElementById("sync-remote-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "🔄 同步中...";
  }

  try {
    const result = await api("/api/sync", {
      method: "POST",
      body: JSON.stringify({}),
    });

    let message = "";
    if (result.ok) {
      message = `同步完成！\nWeb 文件: ${result.web_files} 个\n数据: ${Math.round(result.data_size / 1024)} KB`;
      if (result.remote) {
        message += `\n远程推送: ${result.remote.ok ? "成功" : "失败"}`;
      }
      if (result.remote_error) {
        message += `\n远程连接异常: ${result.remote_error}`;
      }
      message += `\n\n导出的文件:\n${result.export.web.join("\n")}`;
    } else {
      message = `同步失败: ${result.error}`;
    }
    alert(message);
  } catch (error) {
    alert("同步请求失败: " + error.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🔄 同步";
    }
  }
}

async function init() {
  setText("server-url", window.location.origin + "/");
  await refresh();
  await loadDoc(activeDoc);
  renderChat();
  renderIndexTab();

  window.addEventListener("hashchange", renderIndexTab);

  document.getElementById("status-filter").addEventListener("change", renderTasks);
  ["task-search", "horizon-filter", "area-filter", "priority-filter", "tag-filter", "type-filter"].forEach((id) => {
    const node = document.getElementById(id);
    node.addEventListener(node.tagName === "INPUT" ? "input" : "change", renderTasks);
  });

  document.getElementById("view-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-task-view]");
    if (!button) return;
    activeView = button.dataset.taskView;
    renderViewTabs();
  });

  document.getElementById("quick-task-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = document.getElementById("quick-task-title").value.trim();
    if (!title) return;
    const response = await api("/api/tasks/create", { method: "POST", body: JSON.stringify({ title, horizon: "week", priority: "medium" }) });
    document.getElementById("quick-task-title").value = "";
    state = response.state;
    historyState = { tasks: response.state.history || historyState.tasks };
    renderStats();
    renderTaskFilterOptions();
    renderTasks();
    renderHistory();
  });

  document.querySelector(".task-column").addEventListener("click", async (event) => {
    const groupButton = event.target.closest("button[data-task-group]");
    if (groupButton) {
      const groupId = groupButton.dataset.taskGroup;
      taskGroupCollapsed[groupId] = !taskGroupCollapsed[groupId];
      renderTasks();
      return;
    }
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    await updateTaskStatus(button.dataset.id, button.dataset.action);
  });

  // ===== Draft Pool (需求池) Event Handlers =====
  document.getElementById("draft-refresh")?.addEventListener("click", () => loadAndRenderDraft());
  document.getElementById("draft-propose-btn")?.addEventListener("click", showProposeModal);
  document.getElementById("propose-cancel")?.addEventListener("click", hideProposeModal);
  document.getElementById("propose-form")?.addEventListener("submit", submitPropose);
  document.getElementById("approve-cancel")?.addEventListener("click", hideApproveModal);
  document.getElementById("approve-form")?.addEventListener("submit", submitApprove);
  document.getElementById("reject-cancel")?.addEventListener("click", hideRejectModal);
  document.getElementById("reject-form")?.addEventListener("submit", submitReject);
  document.getElementById("draft-batch-approve")?.addEventListener("click", batchApproveDrafts);
  document.getElementById("draft-batch-reject")?.addEventListener("click", batchRejectDrafts);
  ["draft-search"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.addEventListener("input", () => { clearTimeout(node._debounce); node._debounce = setTimeout(loadAndRenderDraft, 300); });
  });
  ["draft-source-filter", "draft-area-filter"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.addEventListener("change", loadAndRenderDraft);
  });
  document.getElementById("draft-panel")?.addEventListener("click", (event) => {
    const checkbox = event.target.closest("input[data-draft-check]");
    if (checkbox) {
      const id = checkbox.dataset.draftCheck;
      if (checkbox.checked) draftSelectedIds.add(id); else draftSelectedIds.delete(id);
      renderDraftList();
      renderDraftBatchBar();
      return;
    }
    const approveBtn = event.target.closest("button[data-action='draft-approve']");
    if (approveBtn) { showApproveModal(approveBtn.dataset.id); return; }
    const rejectBtn = event.target.closest("button[data-action='draft-reject']");
    if (rejectBtn) { showRejectModal(rejectBtn.dataset.id); return; }
  });
  ["propose-modal", "approve-modal", "reject-modal"].forEach((id) => {
    document.getElementById(id)?.addEventListener("click", (e) => {
      if (e.target.id === id) e.target.hidden = true;
    });
  });

  // Week panel action buttons
  document.getElementById("week-grid")?.addEventListener("click", async (event) => {
    // Open task detail on card click (if not a button action)
    const item = event.target.closest(".week-task-item[data-task-id]");
    const button = event.target.closest("button[data-action]");
    if (button) {
      await updateTaskStatus(button.dataset.id, button.dataset.action);
      renderWeekPlan();
    } else if (item && item.dataset.taskId) {
      openTaskDetail(item.dataset.taskId);
    }
  });

  // Gantt navigation
  document.getElementById("gantt-prev")?.addEventListener("click", () => {
    ganttWeekOffset--;
    renderGantt();
  });
  document.getElementById("gantt-next")?.addEventListener("click", () => {
    ganttWeekOffset++;
    renderGantt();
  });
  document.getElementById("gantt-today")?.addEventListener("click", () => {
    ganttWeekOffset = 0;
    renderGantt();
  });

  // Gantt drag-drop to change due date
  document.getElementById("gantt-body")?.addEventListener("dragstart", (event) => {
    const row = event.target.closest(".gantt-row");
    if (row) event.dataTransfer.setData("text/plain", row.dataset.taskId);
  });
  document.getElementById("gantt-body")?.addEventListener("dragover", (event) => {
    event.preventDefault();
  });
  document.getElementById("gantt-body")?.addEventListener("drop", async (event) => {
    event.preventDefault();
    const taskId = event.dataTransfer.getData("text/plain");
    const slot = event.target.closest(".gantt-day-slot");
    if (!taskId || !slot) return;
    const newDue = slot.dataset.date;
    try {
      await api("/api/tasks/update", { method: "POST", body: JSON.stringify({ id: taskId, due: newDue }) });
      ganttWeekOffset = 0;
      const response = await api("/api/state");
      state = response;
      historyState = { tasks: response.history || [] };
      renderGantt();
    } catch (error) {
      alert("更新日期失败: " + error.message);
    }
  });

  // Task modal controls
  document.getElementById("task-edit-close")?.addEventListener("click", closeTaskModal);
  document.getElementById("task-edit-cancel")?.addEventListener("click", closeTaskModal);
  document.getElementById("task-edit-form")?.addEventListener("submit", saveTaskModal);
  document.getElementById("task-modal")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeTaskModal();
  });

  // Remote sync button
  document.getElementById("sync-remote-btn")?.addEventListener("click", triggerRemoteSync);

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
