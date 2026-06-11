#!/usr/bin/env zsh
input=$(cat)

MODEL=$(echo "$input" | jq -r '.model.display_name // "unknown"')
CTX=$(echo "$input" | jq -r '.context_window.used_percentage // 0 | floor')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0 | . * 100 | round / 100')
DIR=$(echo "$input" | jq -r '.workspace.current_dir // ""')
DIR="${DIR##*/}"

BRANCH=""
if git -C "$(echo "$input" | jq -r '.workspace.current_dir // "."')" rev-parse --git-dir &>/dev/null 2>&1; then
    BRANCH=$(git -C "$(echo "$input" | jq -r '.workspace.current_dir // "."')" branch --show-current 2>/dev/null)
    [ -n "$BRANCH" ] && BRANCH=" | $BRANCH"
fi

echo "[$MODEL] $DIR$BRANCH | ctx:${CTX}% | \$${COST}"