# DEV_SELF_CHECK — LLM Todo 周视角甘特图

**需求 ID**: 5ad5de94-fdae-424b-a234-717a4345fdfa
**开发者**: 前端工程师-React ⚛️
**日期**: 2026-05-14
**状态**: ✅ 完成

---

## 1. 需求验收检查

### ✅ 新增「周视角甘特图」视图

| 检查项 | 结果 |
|--------|------|
| 以周为单位（周一到周日） | ✅ |
| 每天列显示到期任务 | ✅ |
| 任务按甘特条位置对应日期 | ✅ |

### ✅ 任务按优先级用不同颜色区分

| 优先级 | 颜色 | 色值 |
|--------|------|------|
| 高 (high) | 🔴 红 | `#ff4d4f` |
| 中 (medium) | 🟡 黄 | `#faad14` |
| 低 (low) | 🟢 绿 | `#52c41a` |

### ✅ 支持周视图和列表视图切换

| 检查项 | 结果 |
|--------|------|
| 视图切换 Tab 栏 | ✅ 列表 ⇆ 甘特图 |
| 切换后保持数据状态 | ✅ |

### ✅ 可选：拖拽调整任务日期

| 检查项 | 结果 |
|--------|------|
| 拖拽甘特条到新日期列 | ✅ |
| 通过 PUT `/api/todos/:id` 更新 `due_date` | ✅ |
| 释放后即时重新渲染 | ✅ |

### ✅ 部署

| 检查项 | 结果 |
|--------|------|
| `rsync` to `/opt/llm-todo/web/` | ✅ |
| `docker cp` into running container | ✅ |
| 线上可访问 | ✅ `http://<SERVER_IP>/todo/` |
| 甘特图 Tab 可点击切换 | ✅ |

---

## 2. 变更文件清单

| 文件 | 说明 |
|------|------|
| `/opt/services/llm-todo/public/index.html` | 新增甘特图面板 HTML + 视图 Tab |
| `/opt/services/llm-todo/public/app.js` | 新增 `renderGantt()` + `ganttWeekOffset` 状态 + 导航/拖拽事件 |
| `/opt/services/llm-todo/public/style.css` | 新增甘特图 CSS（布局/条/列/交互状态） |
| `/opt/llm-todo/web/` (same 3 files) | 同步副本 |

---

## 3. 技术自检

| 检查项 | 结果 |
|--------|------|
| JS 语法 (`node -c`) | ✅ |
| API 无破坏性变更 | ✅ 只读取 `todos[].due_date`，写入 `PUT /api/todos/:id` |
| 与新后端兼容 | ✅ 适配 Node.js Express + SQLite 后端 |

---

## 4. 用户操作路径

1. 打开 `http://<SERVER_IP>/todo/`
2. 点击「📊 甘特图」Tab 切换到甘特图视图
3. 使用 ◀/▶ 按钮切换周
4. 点击「📅 今天」快速回本周
5. 拖拽甘特条到任意日期列 → 自动保存新的截止日期
6. 切回「📋 列表」查看更新后的任务
