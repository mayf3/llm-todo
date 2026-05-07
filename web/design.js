function renderPipeline(id, steps) {
  document.getElementById(id).innerHTML = steps
    .map(
      (step, index) => `
        <div class="pipeline-node">
          <span>${index + 1}</span>
          <strong>${escapeHtml(step)}</strong>
        </div>
        ${index < steps.length - 1 ? '<div class="connector" aria-hidden="true"></div>' : ""}
      `,
    )
    .join("");
}

function renderSequence(id, steps) {
  document.getElementById(id).innerHTML = steps
    .map(
      (step, index) => `
        <div class="sequence-row">
          <span>${String(index + 1).padStart(2, "0")}</span>
          <strong>${escapeHtml(step)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderState(id, steps) {
  document.getElementById(id).innerHTML = steps
    .map(
      (step, index) => `
        <div class="state-node">
          <span>${escapeHtml(step)}</span>
          ${index < steps.length - 1 ? '<i aria-hidden="true"></i>' : ""}
        </div>
      `,
    )
    .join("");
}

function renderDeps(edges) {
  document.getElementById("code-deps-list").innerHTML = edges
    .map(
      (edge) => `
        <div class="dep-row">
          <code>${escapeHtml(edge.from)}</code>
          <span>→</span>
          <code>${escapeHtml(edge.to)}</code>
          <small>${escapeHtml(edge.label)}</small>
        </div>
      `,
    )
    .join("");
}

function renderRisk(items) {
  document.getElementById("risk-map").innerHTML = items
    .map(
      (item) => `
        <div class="risk-row">
          <strong>${escapeHtml(item.level)}</strong>
          <span>${escapeHtml(item.risk)}</span>
          <small>${escapeHtml(item.mitigation)}</small>
        </div>
      `,
    )
    .join("");
}

function renderResponsibilities(files) {
  document.getElementById("responsibility-table").innerHTML = `
    <table>
      <thead><tr><th>文件</th><th>行数</th><th>职责</th></tr></thead>
      <tbody>
        ${files
          .map((file) => `<tr><td><code>${escapeHtml(file.path)}</code></td><td>${file.lines}</td><td>${escapeHtml(file.responsibility)}</td></tr>`)
          .join("")}
      </tbody>
    </table>
  `;
}

function renderHistory(items) {
  document.getElementById("review-history").innerHTML =
    items.length === 0
      ? '<p class="empty">暂无评审历史。</p>'
      : items
          .map((item) => `<div class="history-row"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.path)} · ${escapeHtml(item.updated)} · ${item.lines} 行</span><p>${escapeHtml(item.summary)}</p></div>`)
          .join("");
}

async function initDesign() {
  setText("design-url", window.location.origin + "/design/");
  const [design, review, history] = await Promise.all([api("/api/design"), api("/api/review"), api("/api/reviews")]);
  document.getElementById("design-stats").innerHTML = `
    <span><strong>${design.stats.active}</strong> 进行中</span>
    <span><strong>${design.stats.tasks}</strong> 任务</span>
    <span><strong>${design.stats.planningDocs}</strong> 规划页</span>
    <span><strong>${design.stats.providers.length}</strong> 提供方</span>
  `;
  document.getElementById("architecture").innerHTML = design.architecture.map((item) => `<p>${escapeHtml(item)}</p>`).join("");
  renderPipeline("data-flow-diagram", design.diagrams.dataFlow);
  renderSequence("request-flow", design.diagrams.requestResponse);
  renderState("state-flow-diagram", design.diagrams.stateFlow);
  renderState("horizon-flow-diagram", design.diagrams.horizonFlow);
  renderDeps(design.diagrams.codeDeps);
  document.getElementById("directory-tree").textContent = design.directoryTree;
  renderResponsibilities(design.files);
  renderRisk(design.diagrams.riskMap);
  document.getElementById("review-doc").innerHTML = renderMarkdown(review.review);
  renderHistory(history.reviews);
}

initDesign().catch((error) => {
  document.body.innerHTML = `<main class="fatal">启动失败：${escapeHtml(error.message)}</main>`;
});
