# LLM Todo Maintainer Rules

## Invariants

- `raw/` 保存原始输入、语音转写、聊天摘录和外部材料。默认只追加，不重写。
- `todo/` 是 LLM 维护的规划与任务解释层，适合 Obsidian 和 Web 阅读。
- `data/tasks.json` 是当前任务列表的结构化事实源。
- 任务变更必须记录 `status`、`horizon`、`area`、`priority`、`created`、`updated`，并尽量有 `nextAction`。
- 长期规划页只保存方向、约束、判断和复盘节奏；不要把十年目标硬拆成伪精确任务。
- 聊天窗口是主交互入口。按钮和表单只是可视化、纠错和快速编辑。

## Planning Horizons

- `lifetime`：价值观、长期身份、不可逆承诺、放弃清单。
- `decade`：10 年方向和能力资本。
- `year`：年度主题、项目组合、资源约束。
- `quarter`：季度成果和阶段性指标。
- `month`：项目节奏和外部承诺。
- `week`：当前 next actions。
- `today`：今天可完成的动作。

## Chat Workflow

1. 读取 `data/tasks.json`、`todo/index.md` 和相关 horizon/area 页面。
2. 根据用户消息判断是新增任务、调整计划、复盘、查询还是整理 inbox。
3. 需要结构化变更时输出可应用 operation。
4. 更新 `data/tasks.json` 和相关 `todo/` 页面。
5. 在 `todo/log.md` 记录重要规划变更。

## Review Workflow

浏览器 UI 变更前后检查：

- 首页是否直接进入任务与聊天，不做营销页。
- 长期规划、当前任务、聊天上下文是否同屏可理解。
- 数据流、状态流、request-response、代码依赖、风险图是否出现在 `/design/`。
- 空任务、长标题、移动端、provider 未配置、写入失败是否有明确状态。
