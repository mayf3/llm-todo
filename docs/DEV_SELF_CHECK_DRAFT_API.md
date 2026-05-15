# DEV_SELF_CHECK — LLM Todo 需求池 + Agent 提需求

> 需求 ID: 0b0b5608-0b9a-47bd-858c-f878dfea4f53
> 开发者: agent-dev-engineer
> 日期: 2026-05-16

## 1. 需求理解 ✅

- [x] 新增 `draft` 状态用于需求池
- [x] Agent 可通过 API 提需求（自动创建 draft）
- [x] 管理员可审批/拒绝（draft → active / draft → archived）
- [x] 需求池查询和统计

## 2. 新增 API ✅

| 方法 | 路径 | 认证 | 状态 |
|------|------|------|------|
| `POST` | `/api/tasks/propose` | Agent/Admin | ✅ |
| `PATCH` | `/api/tasks/:id/approve` | Admin only | ✅ |
| `PATCH` | `/api/tasks/:id/reject` | Admin only | ✅ |
| `POST` | `/api/tasks/batch-approve` | Admin only | ✅ |
| `GET` | `/api/tasks?status=draft` | Any | ✅ |
| `GET` | `/api/tasks/draft-stats` | Any | ✅ |

## 3. 数据变更 ✅

- [x] 新增状态: `draft`, `archived`
- [x] 新增字段: `source` (str 120), `sourceType` (agent/user/system/import)
- [x] normalize_task 兼容旧数据（自动补默认值）
- [x] 无数据库（JSON 文件存储），无需迁移

## 4. 向后兼容 ✅

- [x] `GET /api/tasks` 默认不返回 draft（与现有行为一致）
- [x] `POST /api/tasks/create` 不受影响
- [x] 现有任务自动补 source="" / sourceType="agent"

## 5. 自测结果 ✅

| 用例 | 预期 | 结果 |
|------|------|------|
| propose 创建 draft | status=draft | ✅ |
| draft 不出现在默认列表 | excluded | ✅ |
| approve draft → active | status=active | ✅ |
| approve 带覆盖字段 | priority/horizon 更新 | ✅ |
| reject draft → archived | status=archived | ✅ |
| reject 带原因 | notes 追加原因 | ✅ |
| batch-approve 批量审批 | approved/rejected/errors | ✅ |
| draft-stats 统计 | total/bySource/byArea | ✅ |
| source/area 过滤 | 过滤正确 | ✅ |
| 非 draft 任务审批 | 抛错 | ✅ |
| Python 语法检查 | pass | ✅ |

## 6. 安全 ✅

- [x] propose: Agent 或 Admin 可调用
- [x] approve/reject: Admin only
- [x] batch-approve: Admin only
- [x] status=all: Admin only

## Git

Commit: `55f7c3e`
