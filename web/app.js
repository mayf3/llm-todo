let state = null;
let historyState = { tasks: [] };
let planningState = { domains: [], agents: [], roadmap: { milestones: [], openQuestions: [], updated: "" } };
let activeDoc = "todo/index.md";
let chatMessages = [];
let activeView = "tasks";
let activeIndexTab = "tasks";
let taskGroupCollapsed = { now: false, week: false, future: false };

const statusLabels = { active: "进行中", waiting: "等待中", done: "已完成", dropped: "已放弃" };
const horizonLabels = { today: "今天", week: "本周", month: "本月", quarter: "季度", year: "年度", decade: "十年", lifetime: "人生" };
const areaLabels = { system: "系统", life: "生活", learning: "学习", work: "工作" };
const priorityLabels = { high: "高", medium: "中", low: "低" };
const kindLabels = { index: "索引", horizon: "时间尺度", area: "领域", log: "日志", review: "评审", page: "页面" };
const priorityMarks = { high: "🔴", medium: "🟡", low: "⚪" };
const typeLabels = { personal: "个人", agent: "Agent", review: "评审", discuss: "讨论" };
const typeColors = { personal: "#1677ff", agent: "#722ed1", review: "#fa8c16", discuss: "#52c41a" };
const agentStatusLabels = { active: "活跃", idle: "空闲", disabled: "停用" };
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

function clampPlanningPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  const percent = number <= 1 ? number * 100 : number;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function starRating(value) {
  const count = Math.max(0, Math.min(5, Number(value) || 0));
  return `${"★".repeat(count)}${"☆".repeat(5 - count)}`;
}

function statusClass(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
}

function domainById(id) {
  return planningState.domains.find((domain) => domain.id === id) || null;
}

function renderStats() {
  const total = state.stats.total ?? state.stats.tasks;
  document.getElementById("task-count").textContent = `${state.stats.active} 个进行中 / 共 ${total} 个`;
  document.getElementById("stat-strip").innerHTML = `
    <span><strong>${state.stats.active}</strong> 进行中</span>
    <span><strong>${state.stats.done}</strong> 已完成</span>
    <span><strong>${state.stats.dropped || 0}</strong> 已放弃</span>
    <span><strong>${state.stats.planningDocs}</strong> 规划页</span>
    <span><strong>${Object.keys(state.stats.byArea).length}</strong> 领域</span>
  `;
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
  document.getElementById("status-filter").hidden = activeView !== "tasks";
  if (activeView === "week") renderWeekPlan();
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
          const statusIcon = task.status === "active" ? "" : `[${escapeHtml(statusLabels[task.status] || task.status)}]`;
          return `<div class="week-task-item ${escapeHtml(task.status)}" title="${escapeAttr(task.title)}">
            <span class="week-task-title">${priorityIcon} ${escapeHtml(task.title)}</span>
            <span class="week-task-meta">${statusIcon} ${escapeHtml(task.area ? areaLabels[task.area] || task.area : "")}</span>
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
        return `<div class="week-task-item ${escapeHtml(task.status)}" onclick="openTaskDetail('${escapeAttr(task.id)}')" title="${escapeAttr(task.title)}">
          <span class="week-task-title">${priorityIcon} ${escapeHtml(task.title)}</span>
          <span class="week-task-meta">${escapeHtml(task.area ? areaLabels[task.area] || task.area : "")} · 未安排日期</span>
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

function renderPlanningStats() {
  const activeAgents = planningState.agents.filter((agent) => agent.status === "active").length;
  const plannedItems = (planningState.roadmap.milestones || []).reduce((total, milestone) => total + (Array.isArray(milestone.items) ? milestone.items.length : 0), 0);
  document.getElementById("planning-map-stats").innerHTML = `
    <span><strong>${planningState.domains.length}</strong> 能力域</span>
    <span><strong>${planningState.agents.length}</strong> Agents</span>
    <span><strong>${activeAgents}</strong> 活跃</span>
    <span><strong>${plannedItems}</strong> 规划项</span>
  `;
}

function renderPlanningRoadmap() {
  setText("planning-roadmap-updated", planningState.roadmap.updated ? `更新 ${planningState.roadmap.updated}` : "未记录更新时间");
  const milestones = Array.isArray(planningState.roadmap.milestones) ? planningState.roadmap.milestones : [];
  document.getElementById("planning-roadmap-grid").innerHTML =
    milestones.length === 0
      ? '<p class="empty">暂无路线图数据。</p>'
      : milestones
          .map((milestone) => {
            const items = Array.isArray(milestone.items) ? milestone.items.slice(0, 3) : [];
            return `
              <article class="roadmap-card">
                <div class="roadmap-card-head">
                  <strong>${escapeHtml(milestone.period || milestone.id || "未命名周期")}</strong>
                  <span>→ ${escapeHtml(milestone.deadline || "--")}</span>
                </div>
                <div class="roadmap-items">
                  ${
                    items.length === 0
                      ? '<p class="empty">暂无目标项。</p>'
                      : items
                          .map((item) => {
                            const percent = clampPlanningPercent(item.progress);
                            const domain = domainById(item.relatedDomain);
                            return `
                              <div class="roadmap-item">
                                <div class="progress-meta">
                                  <strong>${escapeHtml(priorityMarks[item.priority] || "⚪")} ${escapeHtml(item.title || item.id || "未命名目标")}</strong>
                                  <span>${percent}%</span>
                                </div>
                                <div class="meter" aria-label="${escapeHtml(item.title || "目标")}进度">
                                  <span style="width: ${percent}%"></span>
                                </div>
                                <p>${escapeHtml(item.currentStatus || "")}${item.gap ? ` · Gap: ${escapeHtml(item.gap)}` : ""}</p>
                                <small>${escapeHtml(domain ? domain.name : item.relatedDomain || "")}</small>
                              </div>
                            `;
                          })
                          .join("")
                  }
                </div>
              </article>
            `;
          })
          .join("");
}

function renderPlanningCapabilities() {
  document.getElementById("planning-capability-grid").innerHTML =
    planningState.domains.length === 0
      ? '<p class="empty">暂无能力域数据。</p>'
      : planningState.domains
          .map((domain) => {
            const level = domain.level ?? domain.maturity ?? 0;
            const agents = Array.isArray(domain.agents) ? domain.agents : [];
            return `
              <a class="capability-card" href="/map">
                <strong>${escapeHtml(domain.name || domain.id)}</strong>
                <span class="stars" aria-label="${Number(level) || 0} 星">${escapeHtml(starRating(level))}</span>
                <span>${agents.length} 个 Agent</span>
                <small>${escapeHtml(domain.description || "")}</small>
              </a>
            `;
          })
          .join("");
}

function renderPlanningAgents() {
  setText("planning-agent-count", `${planningState.agents.length} 个 Agent`);
  const agents = planningState.agents.slice(0, 10);
  document.getElementById("planning-agent-list").innerHTML =
    agents.length === 0
      ? '<p class="empty">暂无 Agent 状态。</p>'
      : agents
          .map((agent) => {
            const domain = domainById(agent.relatedDomain);
            const status = agent.status || "unknown";
            return `
              <article class="planning-agent-row">
                <div>
                  <strong>${escapeHtml(agent.name || agent.id)}</strong>
                  <span>${escapeHtml(agent.id || "")} · ${escapeHtml(domain ? domain.name : agent.relatedDomain || "--")}</span>
                </div>
                <span class="status-badge agent-${escapeHtml(statusClass(status))}">${escapeHtml(agentStatusLabels[status] || status)}</span>
              </article>
            `;
          })
          .join("");
}

function renderPlanningDashboard() {
  renderPlanningStats();
  renderPlanningRoadmap();
  renderPlanningCapabilities();
  renderPlanningAgents();
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
            (task) => `
              <article class="task-item ${escapeHtml(task.status)} archived">
                <div>
                  <strong>${escapeHtml(task.title)}</strong>
                  <span>${taskMeta(task, true)}</span>
                  ${renderTags(task)}
                  <p>${escapeHtml(task.nextAction || task.notes || "未记录下一步")}</p>
                </div>
                <div class="task-actions">
                  <button type="button" data-action="active" data-id="${escapeHtml(task.id)}">恢复</button>
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
  const [nextState, capabilities, agents, roadmap] = await Promise.all([
    api("/api/state"),
    api("/api/capabilities").catch(() => ({ domains: [] })),
    api("/api/agents-status").catch(() => ({ agents: [] })),
    api("/api/roadmap").catch(() => ({ milestones: [], openQuestions: [], updated: "" })),
  ]);
  let nextHistory = { tasks: nextState.history || [] };
  try {
    nextHistory = await api("/api/history");
  } catch (error) {
    console.warn("历史任务接口暂不可用，使用 /api/state 中的历史数据。", error);
  }
  state = nextState;
  historyState = nextHistory;
  planningState = {
    domains: Array.isArray(capabilities.domains) ? capabilities.domains : [],
    agents: Array.isArray(agents.agents) ? agents.agents : [],
    roadmap: roadmap || { milestones: [], openQuestions: [], updated: "" },
  };
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

  // Week panel action buttons
  document.getElementById("week-grid")?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    await updateTaskStatus(button.dataset.id, button.dataset.action);
    renderWeekPlan(); // Re-render after status change
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
