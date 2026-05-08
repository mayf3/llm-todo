const statusLabels = { active: "进行中", waiting: "等待中", done: "已完成", dropped: "已放弃" };
const horizonLabels = { today: "今天", week: "本周", month: "本月", quarter: "季度", year: "年度", decade: "十年", lifetime: "人生" };
const areaLabels = { system: "系统", life: "生活", learning: "学习", work: "工作" };
const priorityLabels = { high: "高", medium: "中", low: "低" };
let characterState = { character: null, state: null, history: { tasks: [] } };
let selectedAbilityId = "";

const achievementIcons = {
  first_done: "✓",
  streak_7: "7",
  single_day_5: "5",
  high_priority_punctual: "时",
  system_builder: "建",
};

const abilityTierLabels = {
  foundation: "基础能力",
  execution: "执行能力",
  output: "输出能力",
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

function starRating(level, maxLevel = 5) {
  const max = Math.max(1, Number(maxLevel) || 5);
  const count = Math.max(0, Math.min(max, Number(level) || 0));
  return `${"★".repeat(count)}${"☆".repeat(max - count)}`;
}

function safeTasks(value) {
  return Array.isArray(value) ? value : [];
}

function abilityList(character) {
  return safeTasks(character.abilities);
}

function allKnownTasks(state, history) {
  return safeTasks(state.tasks).concat(safeTasks(history.tasks));
}

function taskMap(state, history) {
  const map = new Map();
  allKnownTasks(state, history).forEach((task) => {
    if (task.id) map.set(task.id, task);
  });
  return map;
}

function sortAbilities(abilities) {
  return [...abilities].sort((a, b) => {
    const tierOrder = { foundation: 0, execution: 1, output: 2 };
    return (tierOrder[a.tier] ?? 9) - (tierOrder[b.tier] ?? 9) || (b.level || 0) - (a.level || 0) || (b.xp || 0) - (a.xp || 0);
  });
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
  const tags = safeTasks(task.tags).slice(0, 4);
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

function countArea(tasks, area) {
  return tasks.filter((task) => task.area === area).length;
}

function countResearchTasks(tasks) {
  return tasks.filter((task) => {
    const title = `${task.title || ""} ${task.notes || ""} ${safeTasks(task.tags).join(" ")}`;
    return task.area === "learning" || /研究|调研|学习|阅读|知识|wiki/i.test(title);
  }).length;
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
  const activeTasks = safeTasks(state.tasks).filter((task) => task.status === "active");

  setText("character-name", character.name || "效率管家");
  setText("character-level", `Lv. ${formatCount(level, "1")}`);
  setText("active-count", activeTasks.length);
  setText("week-done", Number(week.done) || 0);
  setText("week-total", Number(week.total) || 0);
  setText("week-range", week.start && week.end ? `${week.start} 至 ${week.end}` : "本周暂无周期数据");
  renderExperience(experience);
}

function renderAbilityTags(character) {
  const tags = safeTasks(character.coreCapabilities).length
    ? safeTasks(character.coreCapabilities)
    : sortAbilities(abilityList(character)).slice(0, 5);

  document.getElementById("ability-tags").innerHTML = tags.length === 0
    ? '<p class="empty">暂无能力数据。</p>'
    : tags
    .map(
      (ability) => `
        <article class="ability-tag">
          <span>${escapeHtml(ability.icon || "✓")}</span>
          <div>
            <strong>${escapeHtml(ability.title || ability.name || "未命名能力")}</strong>
            <small>${escapeHtml(starRating(ability.level, ability.maxLevel))} · ${Number(ability.relatedCount) || 0} 个关联任务</small>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderSkillTree(character) {
  const abilities = sortAbilities(abilityList(character));
  if (abilities.length === 0) {
    document.getElementById("skill-tree").innerHTML = '<p class="empty">暂无能力树数据。</p>';
    document.getElementById("ability-detail").innerHTML = "";
    return;
  }
  if (!selectedAbilityId || !abilities.some((ability) => ability.id === selectedAbilityId)) {
    selectedAbilityId = safeTasks(character.coreCapabilities)[0]?.id || abilities[0].id;
  }
  const grouped = abilities.reduce((acc, ability) => {
    const tier = ability.tier || "execution";
    if (!acc[tier]) acc[tier] = [];
    acc[tier].push(ability);
    return acc;
  }, {});
  const tiers = ["foundation", "execution", "output"].filter((tier) => grouped[tier]?.length);

  document.getElementById("skill-tree").innerHTML = `
    <svg id="skill-tree-links" class="skill-tree-links" aria-hidden="true"></svg>
    <div class="skill-tree-columns">
      ${tiers
        .map(
          (tier) => `
            <section class="skill-tier">
              <h3>${escapeHtml(abilityTierLabels[tier] || tier)}</h3>
              <div>
                ${grouped[tier]
                  .map((ability) => {
                    const active = ability.id === selectedAbilityId;
                    return `
                      <button type="button" class="ability-node ${active ? "active" : ""}" data-ability="${escapeHtml(ability.id)}" data-ability-node="${escapeHtml(ability.id)}" aria-expanded="${active ? "true" : "false"}">
                        <span class="ability-node-icon">${escapeHtml(ability.icon || "✓")}</span>
                        <span>
                          <strong>${escapeHtml(ability.title || ability.name || ability.id)}</strong>
                          <small>${escapeHtml(starRating(ability.level, ability.maxLevel))} · ${Number(ability.xp) || 0} XP</small>
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
  `;
  renderAbilityDetail();
  requestAnimationFrame(drawSkillLinks);
}

function renderAbilityDetail() {
  const { character, state, history } = characterState;
  if (!character || !state) return;
  const ability = abilityList(character).find((item) => item.id === selectedAbilityId) || abilityList(character)[0];
  const tasksById = taskMap(state, history);
  if (!ability) {
    document.getElementById("ability-detail").innerHTML = "";
    return;
  }
  const relatedTasks = safeTasks(ability.relatedTasks)
    .map((id) => tasksById.get(id))
    .filter(Boolean)
    .sort((a, b) => taskDate(b).localeCompare(taskDate(a)))
    .slice(0, 6);
  document.getElementById("ability-detail").innerHTML = `
    <div class="ability-detail-head">
      <div>
        <h3>${escapeHtml(ability.name || ability.title || ability.id)}</h3>
        <p>${escapeHtml(ability.description || "")}</p>
      </div>
      <span>${escapeHtml(starRating(ability.level, ability.maxLevel))}</span>
    </div>
    <div class="ability-metrics">
      <span><strong>${Number(ability.xp) || 0}</strong> XP</span>
      <span><strong>${Number(ability.xpToNext) || 0}</strong> 距下一级</span>
      <span><strong>${Number(ability.relatedCount) || 0}</strong> 关联任务</span>
      <span><strong>${escapeHtml(ability.unlockedAt || "--")}</strong> 首次记录</span>
    </div>
    <div class="ability-skill-list">
      ${safeTasks(ability.skills).map((skill) => `<span>${escapeHtml(skill)}</span>`).join("")}
    </div>
    <div class="character-task-list compact-related-tasks">
      ${relatedTasks.length === 0 ? '<p class="empty">这个能力暂时没有关联任务。</p>' : relatedTasks.map((task) => renderTaskCard(task, true)).join("")}
    </div>
  `;
}

function drawSkillLinks() {
  const { character } = characterState;
  const root = document.getElementById("skill-tree");
  const svg = document.getElementById("skill-tree-links");
  if (!character || !root || !svg) return;
  const abilities = abilityList(character);
  const rootBox = root.getBoundingClientRect();
  if (!rootBox.width || !rootBox.height) return;
  const paths = [];
  abilities.forEach((ability) => {
    const from = root.querySelector(`[data-ability-node="${ability.id}"]`);
    if (!from) return;
    const fromBox = from.getBoundingClientRect();
    safeTasks(ability.linksTo).forEach((targetId) => {
      const to = root.querySelector(`[data-ability-node="${targetId}"]`);
      if (!to) return;
      const toBox = to.getBoundingClientRect();
      const x1 = fromBox.right - rootBox.left;
      const y1 = fromBox.top + fromBox.height / 2 - rootBox.top;
      const x2 = toBox.left - rootBox.left;
      const y2 = toBox.top + toBox.height / 2 - rootBox.top;
      const mid = x1 + Math.max(24, (x2 - x1) / 2);
      paths.push(`<path d="M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}" />`);
    });
  });
  svg.setAttribute("viewBox", `0 0 ${rootBox.width} ${rootBox.height}`);
  svg.innerHTML = paths.join("");
}

function renderTaskLists(state, history) {
  const activeTasks = sortCurrentTasks(safeTasks(state.tasks).filter((task) => task.status === "active"));
  const recentDone = safeTasks(history.tasks)
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

function renderCharacter(character, state, history) {
  characterState = { character, state, history };
  renderProfile(character, state);
  renderAbilityTags(character);
  renderSkillTree(character);
  renderTaskLists(state, history);
  renderAchievements(character.achievements || []);
}

async function initCharacter() {
  setText("character-url", window.location.origin + "/character");
  const [character, state, historyResult] = await Promise.all([
    api("/api/character"),
    api("/api/state"),
    api("/api/history").catch(() => ({ tasks: [] })),
  ]);
  const history = safeTasks(historyResult.tasks).length ? historyResult : { tasks: safeTasks(state.history) };
  renderCharacter(character, state, history);

  document.getElementById("skill-tree").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-ability]");
    if (!button) return;
    selectedAbilityId = button.dataset.ability;
    renderSkillTree(characterState.character);
  });
  window.addEventListener("resize", drawSkillLinks);
}

initCharacter().catch((error) => {
  document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
});
