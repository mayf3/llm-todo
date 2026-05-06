---
title: LLM Todo 索引
kind: index
updated: 2026-05-05
sources: README.md; schema/AGENTS.md
confidence: high
---

# LLM Todo 索引

## 用途

LLM Todo 是任务列表、长期规划和聊天式复盘的持久层。它不把人生规划简化成待办清单，而是把不同时间尺度分开维护：长期方向保存判断和约束，短期任务保存下一步动作。

## 入口

- [人生尺度](horizons/lifetime.md)：长期身份、价值、边界和放弃清单。
- [十年尺度](horizons/decade.md)：十年能力资本和方向。
- [年度尺度](horizons/year.md)：年度主题、项目组合和复盘节奏。
- [季度尺度](horizons/quarter.md)：季度成果与当前阶段。
- [系统领域](areas/system.md)：这个工具自身的建设任务。
- [生活领域](areas/life.md)：生活、健康、关系、长期稳定性。
- [日志](log.md)：重要规划变更记录。

## 运行规则

每次聊天都应先判断用户处于哪个时间尺度：如果是“今天做什么”，进入下一步动作；如果是“未来要成为什么”，进入规划尺度页面；如果是“我最近很乱”，先做收集箱清理和承诺盘点。
