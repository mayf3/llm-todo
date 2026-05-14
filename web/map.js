let mapState = {
  domains: [],
  agents: [],
  roadmap: { milestones: [], openQuestions: [], updated: "" },
  activeDomainId: "",
};

const capabilityStatusLabels = {
  available: "可用",
  building: "进行中",
  planned: "计划中",
  gap: "缺口",
};

const capabilityStatusMarks = {
  available: "✅",
  building: "🔄",
  planned: "🗓️",
  gap: "⚠️",
};

const agentStatusLabels = {
  active: "活跃",
  idle: "空闲",
  disabled: "停用",
};

const priorityMarks = {
  high: "🔴",
  medium: "🟡",
  low: "🟢",
};

function clampMapPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  const percent = number <= 1 ? number * 100 : number;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function starRating(value) {
  const count = Math.max(0, Math.min(5, Number(value) || 0));
  return `${"★".repeat(count)}${"☆".repeat(5 - count)}`;
}

function domainById(id) {
  return mapState.domains.find((domain) => domain.id === id) || null;
}

function agentsForDomain(domain) {
  const ids = new Set(Array.isArray(domain.agents) ? domain.agents : []);
  return mapState.agents.filter((agent) => ids.has(agent.id) || agent.relatedDomain === domain.id);
}

function statusClass(value) {
  return String(value || "unknown").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
}

function renderMapStats() {
  const activeAgents = mapState.agents.filter((agent) => agent.status === "active").length;
  const plannedItems = mapState.roadmap.milestones.reduce((total, milestone) => total + (Array.isArray(milestone.items) ? milestone.items.length : 0), 0);
  document.getElementById("map-stats").innerHTML = `
    <span><strong>${mapState.domains.length}</strong> 能力域</span>
    <span><strong>${mapState.agents.length}</strong> Agents</span>
    <span><strong>${activeAgents}</strong> 活跃</span>
    <span><strong>${plannedItems}</strong> 规划项</span>
  `;
}

function renderCapabilityGrid() {
  document.getElementById("capability-grid").innerHTML =
    mapState.domains.length === 0
      ? '<p class="empty">暂无能力域数据。</p>'
      : mapState.domains
          .map((domain) => {
            const agents = Array.isArray(domain.agents) ? domain.agents : [];
            return `
              <button type="button" class="capability-card ${domain.id === mapState.activeDomainId ? "active" : ""}" data-domain="${escapeHtml(domain.id)}">
                <strong>${escapeHtml(domain.name || domain.id)}</strong>
                <span class="stars" aria-label="${Number(domain.maturity) || 0} 星">${escapeHtml(starRating(domain.maturity))}</span>
                <span>${agents.length} 个 Agent</span>
                <small>${escapeHtml(domain.description || "")}</small>
              </button>
            `;
          })
          .join("");
}

function renderTagList(items, emptyText) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) return `<p class="empty">${escapeHtml(emptyText)}</p>`;
  return `<div class="tag-list">${values.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
}

function renderCapabilityDetail() {
  const domain = domainById(mapState.activeDomainId) || mapState.domains[0];
  const container = document.getElementById("capability-detail");
  if (!domain) {
    container.innerHTML = '<p class="empty">请选择一个能力域。</p>';
    return;
  }
  mapState.activeDomainId = domain.id;
  const subCapabilities = Array.isArray(domain.subCapabilities) ? domain.subCapabilities : [];
  const relatedAgents = agentsForDomain(domain);
  container.innerHTML = `
    <div class="map-section-head">
      <div>
        <h2>${escapeHtml(domain.name || domain.id)}能力</h2>
        <span>${escapeHtml(domain.updated ? `更新 ${domain.updated}` : "未记录更新时间")}</span>
      </div>
      <strong class="maturity-pill">${escapeHtml(starRating(domain.maturity))}</strong>
    </div>
    <p class="map-description">${escapeHtml(domain.description || "")}</p>
    <div class="detail-grid">
      <div>
        <h3>子能力</h3>
        <div class="subcap-list">
          ${
            subCapabilities.length === 0
              ? '<p class="empty">暂无子能力。</p>'
              : subCapabilities
                  .map((item) => {
                    const label = capabilityStatusLabels[item.status] || item.status || "未标记";
                    const mark = capabilityStatusMarks[item.status] || "•";
                    return `
                      <article class="subcap-row status-${escapeHtml(statusClass(item.status))}">
                        <strong>${escapeHtml(mark)} ${escapeHtml(item.name || item.id || "未命名子能力")}</strong>
                        <span>${escapeHtml(label)}</span>
                        <p>${escapeHtml(item.notes || "")}</p>
                      </article>
                    `;
                  })
                  .join("")
          }
        </div>
      </div>
      <div>
        <h3>Gap</h3>
        ${
          Array.isArray(domain.gaps) && domain.gaps.length
            ? `<ul class="gap-list">${domain.gaps.map((gap) => `<li>${escapeHtml(gap)}</li>`).join("")}</ul>`
            : '<p class="empty">暂无 Gap。</p>'
        }
        <h3>关联 Agent</h3>
        ${renderTagList(relatedAgents.map((agent) => `${agent.id} · ${agentStatusLabels[agent.status] || agent.status || "未知"}`), "暂无关联 Agent。")}
        <h3>Skills</h3>
        ${renderTagList(domain.skills, "暂无关联 Skill。")}
      </div>
    </div>
  `;
}

function renderRoadmap() {
  setText("roadmap-updated", mapState.roadmap.updated ? `更新 ${mapState.roadmap.updated}` : "未记录更新时间");
  const milestones = Array.isArray(mapState.roadmap.milestones) ? mapState.roadmap.milestones : [];
  document.getElementById("roadmap-grid").innerHTML =
    milestones.length === 0
      ? '<p class="empty">暂无路线图数据。</p>'
      : milestones
          .map((milestone) => {
            const items = Array.isArray(milestone.items) ? milestone.items : [];
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
                            const percent = clampMapPercent(item.progress);
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

function renderOpenQuestions() {
  const questions = Array.isArray(mapState.roadmap.openQuestions) ? mapState.roadmap.openQuestions : [];
  document.getElementById("open-questions").innerHTML =
    questions.length === 0
      ? '<p class="empty">暂无待讨论问题。</p>'
      : questions.map((question) => `<div class="question-row">${escapeHtml(question)}</div>`).join("");
}

function renderAgents() {
  setText("agent-count", `${mapState.agents.length} 个 Agent`);
  document.getElementById("agent-status-list").innerHTML =
    mapState.agents.length === 0
      ? '<p class="empty">暂无 Agent 状态。</p>'
      : `
        <table class="agent-table">
          <thead>
            <tr><th>Agent</th><th>状态</th><th>能力域</th><th>定时</th><th>最近活跃</th></tr>
          </thead>
          <tbody>
            ${mapState.agents
              .map((agent) => {
                const domain = domainById(agent.relatedDomain);
                const status = agent.status || "unknown";
                return `
                  <tr>
                    <td><strong>${escapeHtml(agent.name || agent.id)}</strong><span>${escapeHtml(agent.id || "")} · ${escapeHtml(agent.category || "")}</span></td>
                    <td><span class="status-badge agent-${escapeHtml(statusClass(status))}">${escapeHtml(agentStatusLabels[status] || status)}</span></td>
                    <td>${escapeHtml(domain ? domain.name : agent.relatedDomain || "--")}</td>
                    <td>${agent.cronActive ? "开启" : "关闭"}</td>
                    <td>${escapeHtml(agent.lastActive || "--")}</td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      `;
}

function renderMap() {
  renderMapStats();
  renderCapabilityGrid();
  renderCapabilityDetail();
  renderRoadmap();
  renderOpenQuestions();
  renderAgents();
}

async function initMapSkillTree() {
  const skillTreeContainer = document.getElementById("skill-tree");
  if (!skillTreeContainer) return; // skill tree section not present

  const [character, skillTree, state, historyResult] = await Promise.all([
    api("/api/character").catch(() => ({})),
    api("/api/skill-tree").catch(() => ({ lines: [], skills: [], kpis: [], levelLegend: {} })),
    api("/api/state").catch(() => ({ tasks: [] })),
    api("/api/history").catch(() => ({ tasks: [] })),
  ]);

  characterState.character = character;
  characterState.state = state;
  characterState.history = historyResult;
  characterState.skillTree = skillTree || { lines: [], skills: [], kpis: [], levelLegend: {} };
  characterState.activeLineId = skillLines()[0]?.id || "";

  renderSkillKpis();
  renderSkillTabs();
  renderSkillTree();

  document.getElementById("skill-tree-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-line]");
    if (!button) return;
    characterState.activeLineId = button.dataset.line;
    characterState.selectedSkillId = "";
    renderSkillTabs();
    renderSkillTree();
  });

  document.getElementById("skill-tree").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-skill]");
    if (!button) return;
    characterState.selectedSkillId = button.dataset.skill;
    renderSkillTree();
  });

  window.addEventListener("resize", drawSkillLinks);
}

async function initMap() {
  setText("map-url", window.location.origin + "/map");
  const [capabilities, agents, roadmap] = await Promise.all([api("/api/capabilities"), api("/api/agents-status"), api("/api/roadmap")]);
  mapState.domains = Array.isArray(capabilities.domains) ? capabilities.domains : [];
  mapState.agents = Array.isArray(agents.agents) ? agents.agents : [];
  mapState.roadmap = roadmap || { milestones: [], openQuestions: [], updated: "" };
  mapState.activeDomainId = mapState.domains[0]?.id || "";
  renderMap();

  document.getElementById("capability-grid").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-domain]");
    if (!button) return;
    mapState.activeDomainId = button.dataset.domain;
    renderCapabilityGrid();
    renderCapabilityDetail();
  });

  // Initialize skill tree (from character.js)
  await initMapSkillTree();
}

initMap().catch((error) => {
  document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
});
