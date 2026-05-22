#!/bin/bash
# Agent 任务检查调度器
# 查询 LLM Todo，有任务的 Agent 才通过 sessions_send 唤醒
# 用法: bash agent-task-checker.sh [--dry-run]

set -euo pipefail

API_BASE="http://localhost:8720"
AGENTS_FILE="/home/user/projects/llm_todo/data/agents.json"
DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

echo "=== Agent Task Checker $(date '+%Y-%m-%d %H:%M') ==="

# 读取所有有 token 的 agent
AGENTS=$(jq -r '.accounts[] | "\(.id)|\(.name)|\(.token)"' "$AGENTS_FILE")

while IFS='|' read -r agent_id agent_name agent_token; do
  # 跳过效率管家自己（他自己就是调度器）
  [ "$agent_id" = "efficiency-agent" ] && continue
  
  # 查询该 agent 的 active 任务数
  result=$(curl -s -X POST "$API_BASE/api/tasks/search" \
    -H "Content-Type: application/json" \
    -d "{\"assignee\":\"$agent_id\",\"status\":\"active\"}" 2>/dev/null || echo '{"tasks":[]}')
  
  count=$(echo "$result" | jq '.tasks | length' 2>/dev/null || echo "0")
  
  if [ "$count" -gt 0 ]; then
    echo "✅ $agent_name ($agent_id): $count 个待办任务"
    
    if [ "$DRY_RUN" = true ]; then
      echo "   [dry-run] 会唤醒 $agent_name"
    else
      # 提取任务摘要
      summary=$(echo "$result" | jq -r '.tasks[:3] | .[] | "  - \(.title) (\(.priority)) \(.nextAction[:40] // "无")"' 2>/dev/null)
      
      # 这里需要配合 OpenClaw 的机制来唤醒
      # 方案：写入一个标记文件，让 cron job 的 payload 读取
      echo "$agent_id" >> /tmp/agent_task_pending.txt
      echo "$summary" >> /tmp/agent_task_pending.txt
      echo "---" >> /tmp/agent_task_pending.txt
    fi
  else
    echo "⏭️ $agent_name ($agent_id): 无待办"
  fi
done <<< "$AGENTS"

echo "=== Done ==="
