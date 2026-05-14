const statusLabels = { active: "进行中", waiting: "等待中", done: "已完成", dropped: "已放弃" };
const horizonLabels = { today: "今天", week: "本周", month: "本月", quarter: "季度", year: "年度", decade: "十年", lifetime: "人生" };
const areaLabels = { system: "系统", life: "生活", learning: "学习", work: "工作" };
const priorityLabels = { high: "高", medium: "中", low: "低" };
const skillLineOrder = ["content", "invest", "system", "life", "growth"];

let characterState = {
  character: null,
  state: null,
  history: { tasks: [] },
  skillTree: { lines: [], skills: [], kpis: [], levelLegend: {} },
  activeLineId: "",
  selectedSkillId: "",
};

const achievementIcons = {
  first_done: "✓",
  streak_7: "7",
  single_day_5: "5",
  high_priority_punctual: "时",
  system_builder: "建",
};

const fallbackLevelLegend = {
  0: { label: "未解锁", marker: "🔒", className: "locked" },
  1: { label: "入门", marker: "🌱", className: "beginner" },
  2: { label: "可用", marker: "🔄", className: "usable" },
  3: { label: "熟练", marker: "✅", className: "proficient" },
  4: { label: "精通", marker: "⭐", className: "master" },
  5: { label: "大师", marker: "🏆", className: "grandmaster" },
};

function clampPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function formatCount(value, fallback = "--") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function meterStyle(percent) {
  return `width: ${clampPercent(percent)}%`;
}

function safeItems(value) {
  return Array.isArray(value) ? value : [];
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
  return String(value).replace(/"/g, '\\"');
}

function levelMeta(skill) {
  const level = Math.max(0, Math.min(5, Number(skill?.level) || 0));
  const legend = characterState.skillTree.levelLegend || characterState.character?.levelLegend || fallbackLevelLegend;
  return legend[level] || legend[String(level)] || fallbackLevelLegend[level] || fallbackLevelLegend[0];
}

function levelText(skill) {
  const level = Math.max(0, Math.min(5, Number(skill?.level) || 0));
  const meta = levelMeta(skill);
  return `${meta.marker || ""} Lv.${level} ${meta.label || ""}`.trim();
}

function abilityList(character = characterState.character) {
  if (!character) return [];
  const explicit = safeItems(character.abilityList);
  if (explicit.length) return explicit;
  const abilities = safeItems(character.abilities);
  if (abilities.some((item) => Array.isArray(item.skills))) {
    return abilities.flatMap((line) => safeItems(line.skills));
  }
  return abilities;
}

function skillLines() {
  const fromTree = safeItems(characterState.skillTree.lines);
  if (fromTree.length) return fromTree;
  const fromCharacter = safeItems(characterState.character?.abilityLines);
  if (fromCharacter.length) return fromCharacter;
  const skillTrees = characterState.character?.skillTrees || {};
  return skillLineOrder.map((id) => skillTrees[id]).filter(Boolean);
}

function activeLine() {
  const lines = skillLines();
  return lines.find((line) => line.id === characterState.activeLineId) || lines[0] || null;
}

function skillsForLine(line) {
  const skills = safeItems(line?.skills).map((skill, index) => ({ ...skill, _order: index }));
  const byId = new Map(skills.map((skill) => [skill.id, skill]));
  const depthCache = new Map();

  function depthFor(skill, visiting = new Set()) {
    if (!skill?.id) return 0;
    if (depthCache.has(skill.id)) return depthCache.get(skill.id);
    if (Number.isFinite(Number(skill.depth))) {
      const depth = Number(skill.depth);
      depthCache.set(skill.id, depth);
      return depth;
    }
    if (visiting.has(skill.id)) return 0;
    visiting.add(skill.id);
    const parent = byId.get(skill.parentId);
    const depth = parent ? depthFor(parent, visiting) + 1 : 0;
    depthCache.set(skill.id, depth);
    return depth;
  }

  return skills.map((skill) => ({ ...skill, depth: depthFor(skill) }));
}

function edgesForLine(line, skills) {
  const explicit = safeItems(line?.edges);
  if (explicit.length) return explicit;
  const validIds = new Set(skills.map((skill) => skill.id).filter(Boolean));
  const edges = [];
  const seen = new Set();
  skills.forEach((skill) => {
    const dependencies = safeItems(skill.dependencies);
    if (skill.parentId && !dependencies.includes(skill.parentId)) dependencies.unshift(skill.parentId);
    dependencies.forEach((dependency) => {
      if (!validIds.has(dependency) || dependency === skill.id) return;
      const type = dependency === skill.parentId ? "parent" : "dependency";
      const key = `${dependency}::${skill.id}::${type}`;
      if (seen.has(key)) return;
      seen.add(key);
      edges.push({ from: dependency, to: skill.id, type });
    });
  });
  return edges;
}

function allKnownTasks(state, history) {
  return safeItems(state?.tasks).concat(safeItems(history?.tasks));
}

function taskMap(state, history) {
  const map = new Map();
  allKnownTasks(state, history).forEach((task) => {
    if (task.id) map.set(task.id, task);
  });
  return map;
}

function taskDate(task) {
  return task.updated || task.created || task.due || "";
}

function priorityRank(task) {
  return { high: 0, medium: 1, low: 2 }[task.priority] ?? 3;
}

function sortCurrentTasks(tasks) {
  return [...tasks].sort((a, b) => {
    const dueA = a.due || "9999-99-99";
    const dueB = b.due || "9999-99-99";
    return priorityRank(a) - priorityRank(b) || dueA.localeCompare(dueB) || taskDate(b).localeCompare(taskDate(a));
  });
}

function taskMeta(task, includeStatus = false) {
  const parts = [
    includeStatus ? statusLabels[task.status] || task.status : "",
    horizonLabels[task.horizon] || task.horizon,
    areaLabels[task.area] || task.area,
    task.priority ? `${priorityLabels[task.priority] || task.priority}优先级` : "",
    task.due ? `截止 ${task.due}` : "",
  ];
  return parts.filter(Boolean).map(escapeHtml).join(" · ");
}

function taskTags(task) {
  const tags = safeItems(task.tags).slice(0, 4);
  if (tags.length === 0) return "";
  return `<div class="character-task-tags">${tags.map((tag) => `<span>#${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function renderTaskCard(task, includeStatus = false) {
  const note = task.nextAction || task.notes || (task.status === "done" ? "已完成，等待复盘沉淀。" : "未记录下一步。");
  return `
    <article class="character-task ${escapeHtml(task.status || "active")}">
      <div>
        <strong>${escapeHtml(task.title || "未命名任务")}</strong>
        <span>${taskMeta(task, includeStatus)}</span>
        ${taskTags(task)}
        <p>${escapeHtml(note)}</p>
      </div>
    </article>
  `;
}

function renderExperience(experience) {
  const current = Number(experience.current) || 0;
  const next = Number(experience.next) || 0;
  const percent = clampPercent(experience.percent ?? (next ? (current / next) * 100 : 0));
  const totalCompleted = Number(experience.totalCompleted) || 0;

  setText("xp-label", `${current} / ${next || "--"} XP`);
  setText("xp-note", `实用能力 XP ${Number(experience.totalAbilityXp) || 0} · 累计完成 ${totalCompleted} 个任务`);
  setText("character-total", `累计完成 ${totalCompleted} 个任务`);
  document.getElementById("xp-bar").style.cssText = meterStyle(percent);
}

function renderProfile(character, state) {
  const experience = character.experience || {};
  const week = character.week || {};
  const level = Number(character.level) || 1;
  const activeTasks = safeItems(state.tasks).filter((task) => task.status === "active");

  setText("character-name", character.name || "效率管家");
  setText("character-level", `Lv. ${formatCount(level, "1")}`);
  setText("active-count", activeTasks.length);
  setText("week-done", Number(week.done) || 0);
  setText("week-total", Number(week.total) || 0);
  setText("week-range", week.start && week.end ? `${week.start} 至 ${week.end}` : "本周暂无周期数据");
  renderExperience(experience);
}

function renderAbilityTags(character) {
  const tags = safeItems(character.coreCapabilities).length
    ? safeItems(character.coreCapabilities)
    : [...abilityList(character)].sort((a, b) => (b.level || 0) - (a.level || 0) || (b.xp || 0) - (a.xp || 0)).slice(0, 5);

  document.getElementById("ability-tags").innerHTML =
    tags.length === 0
      ? '<p class="empty">暂无能力数据。</p>'
      : tags
          .map(
            (ability) => `
              <article class="ability-tag">
                <span>${escapeHtml(ability.icon || "✓")}</span>
                <div>
                  <strong>${escapeHtml(ability.title || ability.name || "未命名能力")}</strong>
                  <small>${escapeHtml(levelText(ability))} · ${Number(ability.relatedCount) || 0} 个关联任务</small>
                </div>
              </article>
            `,
          )
          .join("");
}

function renderSkillKpis() {
  const kpis = safeItems(characterState.skillTree.kpis).length ? safeItems(characterState.skillTree.kpis) : safeItems(characterState.character?.skillTreeKpis);
  const summary = characterState.skillTree.summary || characterState.character?.skillTreeSummary || {};
  const items = kpis.length
    ? kpis
    : [
        { id: "total", label: "技能节点", value: String(summary.total || abilityList().length || 0), note: "已纳入树结构" },
        { id: "locked", label: "未解锁", value: String(summary.locked || 0), note: "灰色节点" },
        { id: "active", label: "进行中", value: String(summary.inProgress || 0), note: "蓝色节点" },
        { id: "mastered", label: "精通", value: String(summary.mastered || 0), note: "金色节点" },
      ];

  document.getElementById("skill-kpis").innerHTML = items
    .map(
      (item) => `
        <article class="skill-kpi-card">
          <span>${escapeHtml(item.label || item.id)}</span>
          <strong>${escapeHtml(item.value ?? "--")}</strong>
          <small>${escapeHtml(item.note || "")}</small>
        </article>
      `,
    )
    .join("");
}

function renderSkillTabs() {
  const lines = skillLines();
  if (!characterState.activeLineId || !lines.some((line) => line.id === characterState.activeLineId)) {
    characterState.activeLineId = lines[0]?.id || "";
  }
  document.getElementById("skill-tree-tabs").innerHTML =
    lines.length === 0
      ? ""
      : lines
          .map((line) => {
            const active = line.id === characterState.activeLineId;
            const summary = line.summary || {};
            return `
              <button type="button" class="${active ? "active" : ""}" data-line="${escapeHtml(line.id)}" aria-pressed="${active ? "true" : "false"}">
                <span>${escapeHtml(line.icon || "")}</span>
                <strong>${escapeHtml(line.name || line.id)}</strong>
                <small>${Number(summary.total) || safeItems(line.skills).length} 节点</small>
              </button>
            `;
          })
          .join("");
}

function renderSkillTree() {
  const line = activeLine();
  const container = document.getElementById("skill-tree");
  if (!line) {
    container.innerHTML = '<p class="empty">暂无技能树数据。</p>';
    document.getElementById("ability-detail").innerHTML = "";
    return;
  }

  const skills = skillsForLine(line);
  if (!characterState.selectedSkillId || !skills.some((skill) => skill.id === characterState.selectedSkillId)) {
    characterState.selectedSkillId = skills.find((skill) => !skill.parentId)?.id || skills[0]?.id || "";
  }

  const depthValues = [...new Set(skills.map((skill) => skill.depth))].sort((a, b) => a - b);
  const columns = depthValues.map((depth) => skills.filter((skill) => skill.depth === depth).sort((a, b) => a._order - b._order));

  container.innerHTML = `
    <div class="skill-tree" data-active-line="${escapeHtml(line.id)}">
      <svg id="skill-tree-links" class="skill-tree-links" aria-hidden="true"></svg>
      <div class="skill-tree-columns" style="grid-template-columns: repeat(${Math.max(1, columns.length)}, minmax(150px, 1fr))">
        ${columns
          .map(
            (items, columnIndex) => `
              <section class="skill-tier">
                <h3>${columnIndex === 0 ? "主干" : columnIndex === 1 ? "分支" : `第 ${columnIndex + 1} 层`}</h3>
                <div>
                  ${items
                    .map((skill) => {
                      const active = skill.id === characterState.selectedSkillId;
                      const meta = levelMeta(skill);
                      return `
                        <button type="button" class="ability-node level-${escapeHtml(meta.className || "locked")} ${active ? "active" : ""}" data-skill="${escapeHtml(skill.id)}" data-skill-node="${escapeHtml(skill.id)}" aria-expanded="${active ? "true" : "false"}">
                          <span class="ability-node-icon">${escapeHtml(skill.icon || "✓")}</span>
                          <span>
                            <strong>${escapeHtml(skill.name || skill.title || skill.id)}</strong>
                            <small>${escapeHtml(levelText(skill))} · ${Number(skill.relatedCount) || 0} 任务</small>
                          </span>
                        </button>
                      `;
                    })
                    .join("")}
                </div>
              </section>
            `,
          )
          .join("")}
      </div>
    </div>
  `;

  renderSkillDetail(line, skills);
  requestAnimationFrame(drawSkillLinks);
}

function dependencyNames(skill, skills) {
  const byId = new Map(skills.map((item) => [item.id, item]));
  return safeItems(skill.dependencies)
    .map((id) => byId.get(id)?.name || id)
    .filter(Boolean);
}

function renderSkillDetail(line, skills) {
  const skill = skills.find((item) => item.id === characterState.selectedSkillId) || skills[0];
  const detail = document.getElementById("ability-detail");
  if (!skill) {
    detail.innerHTML = "";
    return;
  }

  const { state, history } = characterState;
  const tasksById = taskMap(state, history);
  const relatedTasks = safeItems(skill.relatedTasks)
    .map((id) => tasksById.get(id))
    .filter(Boolean)
    .sort((a, b) => taskDate(b).localeCompare(taskDate(a)))
    .slice(0, 6);
  const children = skills.filter((item) => item.parentId === skill.id);
  const dependents = skills.filter((item) => safeItems(item.dependencies).includes(skill.id) && item.parentId !== skill.id);
  const dependencies = dependencyNames(skill, skills);
  const conditions = safeItems(skill.upgradeConditions);

  detail.innerHTML = `
    <article class="ability-detail">
      <div class="ability-detail-head">
        <div>
          <h3>${escapeHtml(skill.icon || "")} ${escapeHtml(skill.name || skill.title || skill.id)}</h3>
          <p>${escapeHtml(skill.notes || skill.description || "")}</p>
        </div>
        <span>${escapeHtml(levelText(skill))}</span>
      </div>
      <div class="ability-metrics">
        <span><strong>${escapeHtml(line.name || line.id)}</strong> 主线</span>
        <span><strong>${Number(skill.xp) || 0}</strong> XP</span>
        <span><strong>${Number(skill.relatedCount) || 0}</strong> 关联任务</span>
        <span><strong>${escapeHtml(skill.lastVerified || "--")}</strong> 上次验证</span>
        <span><strong>${children.length}</strong> 子技能</span>
      </div>
      <div class="skill-detail-grid">
        <section>
          <h4>前置依赖</h4>
          ${dependencies.length ? `<div class="ability-skill-list">${dependencies.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : '<p class="empty">无前置依赖。</p>'}
        </section>
        <section>
          <h4>后续节点</h4>
          ${
            children.length || dependents.length
              ? `<div class="ability-skill-list">${children
                  .concat(dependents)
                  .map((item) => `<span>${escapeHtml(item.name || item.id)}</span>`)
                  .join("")}</div>`
              : '<p class="empty">暂无后续节点。</p>'
          }
        </section>
      </div>
      <section>
        <h4>升级条件</h4>
        ${
          conditions.length
            ? `<ul class="skill-condition-list">${conditions.map((condition) => `<li>${escapeHtml(condition)}</li>`).join("")}</ul>`
            : '<p class="empty">暂无升级条件。</p>'
        }
      </section>
      <div class="character-task-list compact-related-tasks">
        ${relatedTasks.length === 0 ? '<p class="empty">这个技能暂时没有关联任务。</p>' : relatedTasks.map((task) => renderTaskCard(task, true)).join("")}
      </div>
    </article>
  `;
}

function drawSkillLinks() {
  const line = activeLine();
  const root = document.querySelector("#skill-tree .skill-tree");
  const svg = document.getElementById("skill-tree-links");
  if (!line || !root || !svg) return;
  const skills = skillsForLine(line);
  const edges = edgesForLine(line, skills);
  const rootBox = root.getBoundingClientRect();
  if (!rootBox.width || !rootBox.height) return;
  const canvasWidth = Math.max(root.scrollWidth, Math.ceil(rootBox.width));
  const canvasHeight = Math.max(root.scrollHeight, Math.ceil(rootBox.height));

  const paths = [];
  edges.forEach((edge) => {
    const from = root.querySelector(`[data-skill-node="${cssEscape(edge.from)}"]`);
    const to = root.querySelector(`[data-skill-node="${cssEscape(edge.to)}"]`);
    if (!from || !to) return;
    const fromBox = from.getBoundingClientRect();
    const toBox = to.getBoundingClientRect();
    const forward = fromBox.left <= toBox.left;
    const x1 = (forward ? fromBox.right : fromBox.left) - rootBox.left + root.scrollLeft;
    const y1 = fromBox.top + fromBox.height / 2 - rootBox.top + root.scrollTop;
    const x2 = (forward ? toBox.left : toBox.right) - rootBox.left + root.scrollLeft;
    const y2 = toBox.top + toBox.height / 2 - rootBox.top + root.scrollTop;
    const distance = Math.max(28, Math.abs(x2 - x1) / 2);
    const c1 = forward ? x1 + distance : x1 - distance;
    const c2 = forward ? x2 - distance : x2 + distance;
    paths.push(`<path class="${edge.type === "dependency" ? "dependency" : "parent"}" d="M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}" />`);
  });
  svg.style.width = `${canvasWidth}px`;
  svg.style.height = `${canvasHeight}px`;
  svg.setAttribute("viewBox", `0 0 ${canvasWidth} ${canvasHeight}`);
  svg.innerHTML = paths.join("");
}

function renderTaskLists(state, history) {
  const activeTasks = sortCurrentTasks(safeItems(state.tasks).filter((task) => task.status === "active"));
  const recentDone = safeItems(history.tasks)
    .filter((task) => task.status === "done")
    .sort((a, b) => taskDate(b).localeCompare(taskDate(a)))
    .slice(0, 5);

  setText("active-task-count", `${activeTasks.length} 个任务`);
  setText("recent-task-count", `${recentDone.length} 个任务`);

  document.getElementById("active-task-list").innerHTML =
    activeTasks.length === 0 ? '<p class="empty">当前没有进行中任务。</p>' : activeTasks.slice(0, 5).map((task) => renderTaskCard(task)).join("");

  document.getElementById("recent-done-list").innerHTML =
    recentDone.length === 0 ? '<p class="empty">暂无近期完成任务。</p>' : recentDone.map((task) => renderTaskCard(task, true)).join("");
}

function renderAchievements(achievements) {
  const items = Array.isArray(achievements) ? achievements : [];
  const unlockedCount = items.filter((item) => item.unlocked).length;
  setText("achievement-count", `${unlockedCount} / ${items.length} 已解锁`);
  document.getElementById("achievement-badges").innerHTML =
    items.length === 0
      ? '<p class="empty">暂无成就数据。</p>'
      : items
          .map((achievement) => {
            const unlocked = Boolean(achievement.unlocked);
            const icon = achievementIcons[achievement.id] || "章";
            return `
              <article class="achievement-badge ${unlocked ? "unlocked" : "locked"}">
                <span>${escapeHtml(icon)}</span>
                <div>
                  <strong>${escapeHtml(achievement.title || "未命名成就")}</strong>
                  <small>${escapeHtml(unlocked ? "已解锁" : achievement.description || "继续完成任务解锁")}</small>
                </div>
              </article>
            `;
          })
          .join("");
}

function renderCharacter(character, state, history, skillTree) {
  characterState.character = character;
  characterState.state = state;
  characterState.history = history;
  characterState.skillTree = skillTree || { lines: safeItems(character.abilityLines), skills: abilityList(character), levelLegend: character.levelLegend || {} };
  characterState.activeLineId = characterState.activeLineId || skillLines()[0]?.id || "";

  renderProfile(character, state);
  renderAbilityTags(character);
  renderSkillKpis();
  renderSkillTabs();
  renderSkillTree();
  renderTaskLists(state, history);
  renderAchievements(character.achievements || []);
}

async function initCharacter() {
  setText("character-url", window.location.origin + "/character");
  const [character, state, historyResult, skillTree] = await Promise.all([
    api("/api/character"),
    api("/api/state"),
    api("/api/history").catch(() => ({ tasks: [] })),
    api("/api/skill-tree"),
  ]);
  const history = safeItems(historyResult.tasks).length ? historyResult : { tasks: safeItems(state.history) };
  renderCharacter(character, state, history, skillTree);

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

// Only auto-init on character page
if (document.getElementById("character-url")) {
  initCharacter().catch((error) => {
    document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
  });
}
