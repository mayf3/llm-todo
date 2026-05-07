const abilityLabels = {
  engineering: "工程力",
  learning: "学习力",
  execution: "执行力",
  life: "生活力",
  efficiency: "效率值",
  focus: "专注度",
};

const abilityDescriptions = {
  engineering: "系统建设和工程任务推进能力",
  learning: "学习、阅读和知识沉淀能力",
  execution: "工作任务完成和落地能力",
  life: "生活领域维护和习惯执行能力",
  efficiency: "高优先级任务按时完成表现",
  focus: "本周任务投入与完成集中度",
};

const abilityOrder = Object.keys(abilityLabels);

function clampPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function formatCount(value, fallback = "--") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function abilityName(ability) {
  return abilityLabels[ability.id] || String(ability.name || "能力值").replace(/^[^\u4e00-\u9fa5A-Za-z0-9]+/u, "").trim();
}

function sortAbilities(abilities) {
  return [...abilities].sort((a, b) => {
    const left = abilityOrder.indexOf(a.id);
    const right = abilityOrder.indexOf(b.id);
    return (left === -1 ? abilityOrder.length : left) - (right === -1 ? abilityOrder.length : right);
  });
}

function meterStyle(percent) {
  return `width: ${clampPercent(percent)}%`;
}

function renderExperience(experience) {
  const current = Number(experience.current) || 0;
  const next = Number(experience.next) || 0;
  const percent = clampPercent(experience.percent ?? (next ? (current / next) * 100 : 0));

  setText("xp-label", `${current} / ${next || "--"} XP`);
  setText("xp-note", `升级进度 ${percent}% · 累计完成 ${formatCount(experience.totalCompleted, "0")} 个任务`);
  document.getElementById("xp-bar").style.cssText = meterStyle(percent);
}

function renderAbilities(abilities) {
  const items = sortAbilities(Array.isArray(abilities) ? abilities : []);
  document.getElementById("abilities-grid").innerHTML =
    items.length === 0
      ? '<p class="empty">暂无能力数据。</p>'
      : items
          .map((ability) => {
            const percent = clampPercent(ability.value);
            const raw = ability.raw === null || ability.raw === undefined ? "" : `${formatCount(ability.raw)}${formatCount(ability.unit, "")}`;
            const description = ability.description || abilityDescriptions[ability.id] || "根据任务完成记录计算";
            const detail = raw && raw !== `${percent}%` ? `${raw} · ${description}` : description;
            return `
              <article class="ability-card">
                <div class="ability-card-head">
                  <strong>${escapeHtml(abilityName(ability))}</strong>
                  <span>${percent}%</span>
                </div>
                <div class="meter" aria-label="${escapeHtml(abilityName(ability))}进度">
                  <span style="${meterStyle(percent)}"></span>
                </div>
                <p>${escapeHtml(detail)}</p>
              </article>
            `;
          })
          .join("");
}

function renderAchievements(achievements) {
  const items = Array.isArray(achievements) ? achievements : [];
  const unlockedCount = items.filter((item) => item.unlocked).length;
  setText("achievement-count", `${unlockedCount} / ${items.length} 已解锁`);
  document.getElementById("achievements-grid").innerHTML =
    items.length === 0
      ? '<p class="empty">暂无成就数据。</p>'
      : items
          .map((achievement) => {
            const unlocked = Boolean(achievement.unlocked);
            return `
              <article class="achievement-card ${unlocked ? "unlocked" : "locked"}">
                <div>
                  <strong>${escapeHtml(achievement.title || "未命名成就")}</strong>
                  <span>${unlocked ? "已解锁" : "锁定"}</span>
                </div>
                <p>${escapeHtml(achievement.description || (unlocked ? "成就已达成。" : "继续完成任务解锁。"))}</p>
              </article>
            `;
          })
          .join("");
}

function renderWeek(week) {
  const done = Number(week.done) || 0;
  const total = Number(week.total) || 0;
  const percent = total ? clampPercent((done / total) * 100) : 0;

  setText("week-done", done);
  setText("week-total", total);
  setText("week-range", week.start && week.end ? `${week.start} 至 ${week.end}` : "--");
  setText("week-note", `本周完成 ${done} / ${total}，完成率 ${percent}%`);
  document.getElementById("week-bar").style.cssText = meterStyle(percent);
}

function renderCharacter(character) {
  setText("character-name", character.name || "冒险者");
  setText("character-level", `等级 ${formatCount(character.level, "1")}`);
  renderExperience(character.experience || {});
  renderAbilities(character.abilities || []);
  renderAchievements(character.achievements || []);
  renderWeek(character.week || {});
}

async function initCharacter() {
  setText("character-url", window.location.origin + "/character.html");
  const character = await api("/api/character");
  renderCharacter(character);
}

initCharacter().catch((error) => {
  document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
});
