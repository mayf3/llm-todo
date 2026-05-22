# DEV_SELF_CHECK — 三层线路图视图 (d4ff6df5) + nginx 修复

**需求 ID**: d4ff6df5
**开发者**: 前端工程师-React ⚛️
**日期**: 2026-05-14
**状态**: ✅ 完成

---

## 1. 需求验收检查

### ✅ 三层线路图视图

| 检查项 | 结果 |
|--------|------|
| 新增「🗺️ 线路图」Tab | ✅ 4个Tab：列表/看板/线路图/甘特图 |
| 主线展示进度条 | ✅ 进度条 + done/total + 百分比 |
| 主线展示 deadline | ✅ 显示最近截止日期 |
| 主线展示成功标准 | ✅ 关键里程碑列表（Top 5 高优先级） |
| 三条线路（主线/探索线/生活线） | ✅ 按 category 自动归类 |
| 逾期提醒 | ✅ 逾期数量红色标记 |
| 主线=核心业务，探索线=新方向，生活线=日常 | ✅ |

### ✅ nginx 修复

| 检查项 | 结果 |
|--------|------|
| `/todo/map` 正确返回 map.html | ✅ 包含「能力地图」4处 |
| `/todo/character` 正确返回 character.html | ✅ 包含「角色」5处 |
| API 代理到 Python 服务器 | ✅ l端口 8721 |
| `/todo/` 主应用不受影响 | ✅ |

---

## 2. 变更文件清单

| 文件 | 说明 |
|------|------|
| `public/app.js` | 新增 `renderRoadmap()` + view Tab 集成 |
| `public/index.html` | 新增「🗺️ 线路图」Tab + roadmap-panel |
| `public/style.css` | 新增 roadmap-layer/progress/criterion 样式 |
| `nginx sites-enabled` | 新增 map/character 静态路由 + API 代理到 Python 8721 |

---

## 3. 当前线上状态

| 功能 | 状态 | 说明 |
|------|------|------|
| 📋 列表 | ✅ | 任务列表+筛选+搜索 |
| 📋 看板 | ✅ | 三列看板+拖拽 |
| 🗺️ 线路图 | ✅ | 三层线路图+进度条+deadline |
| 📊 甘特图 | ✅ | 周视角+拖拽改日期 |
| 🧭 能力地图 | ✅ | `/todo/map` nginx 修复 |
| 👤 角色页 | ✅ | `/todo/character` nginx 修复 |
| 📄 周报 | ✅ | 日报/周报自动生成 |
| 🔐 SSO | ✅ | JWT + sso_token |
