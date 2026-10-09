#!/usr/bin/env bash
# 给缺 kind/* 或 priority/* 的开启 issue 补上 needs-kind / needs-priority，
# 已经有对应维度的就把标志标签摘掉。打了 frozen 的条目不处理。
#
# 用法：
#   GH_REPO=owner/repo bash script/sync-missing-labels.sh --dry-run
#   GH_REPO=owner/repo bash script/sync-missing-labels.sh
# 在 workflow 里由 GITHUB_TOKEN 提供权限。
# 本地运行需要 bash 能直接调用 gh（Windows 下用 WSL，或把 gh 所在目录加进 PATH）。
set -euo pipefail

dry_run=false
if [ "${1:-}" = "--dry-run" ]; then
  dry_run=true
fi

# 标志标签必须先存在，缺了就停下，不要静默跳过
existing_labels="$(gh label list --limit 100 --json name --jq '.[].name')"
for label in needs-kind needs-priority; do
  if ! grep -qx "$label" <<<"$existing_labels"; then
    echo "缺少标签 $label，先跑 gh label clone 或 gh label create" >&2
    exit 1
  fi
done

edit() {
  local number="$1"
  shift
  if [ "$dry_run" = "true" ]; then
    echo "gh issue edit $number $*"
  else
    gh issue edit "$number" "$@"
  fi
}

# --limit 500：开启 issue 超过 500 条的仓库会被截断，届时调大这个数
# 过滤表达式交给 gh 自带的 --jq 执行，不额外依赖 jq
gh issue list --state open --limit 500 --json number,labels \
  --jq '.[] | [.number, ([.labels[].name] | any(startswith("kind/"))), ([.labels[].name] | any(startswith("priority/"))), ([.labels[].name] | any(. == "frozen"))] | @tsv' \
  | while IFS=$'\t' read -r number has_kind has_priority is_frozen; do
      if [ "$is_frozen" = "true" ]; then
        continue
      fi

      if [ "$has_kind" = "true" ]; then
        edit "$number" --remove-label needs-kind
      else
        edit "$number" --add-label needs-kind
      fi

      if [ "$has_priority" = "true" ]; then
        edit "$number" --remove-label needs-priority
      else
        edit "$number" --add-label needs-priority
      fi
    done
