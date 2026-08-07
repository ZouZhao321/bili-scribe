#!/bin/bash
# 通过远程服务器中转操作 GitHub
# 用法:
#   ./scripts/push.sh push <branch>           # 推送分支到 GitHub
#   ./scripts/push.sh pr-update <pr> <file>   # 从文件读取内容更新 PR 描述

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env not found"
    exit 1
fi
source "$ENV_FILE"

REMOTE="ssh://${SSH_USER}@${SSH_HOST}/home/ubuntu/bili-scribe.git"
API="https://api.github.com/repos/ZouZhao321/bili-scribe"

case "${1:-help}" in
    push)
        BRANCH="${2:-$(git rev-parse --abbrev-ref HEAD)}"
        echo "=== Pushing branch '$BRANCH' via $SSH_USER@$SSH_HOST ==="
        GIT_SSH_COMMAND="sshpass -p '$SSH_PASSWORD' ssh -o StrictHostKeyChecking=no" \
          git push "$REMOTE" "$BRANCH"
        echo "=== Done ==="
        ;;

    pr-update)
        PR_NUM="${2:?Usage: push.sh pr-update <pr-number> <body-file>}"
        BODY_FILE="${3:?Usage: push.sh pr-update <pr-number> <body-file>}"
        if [ ! -f "$BODY_FILE" ]; then
            echo "Error: body file not found: $BODY_FILE"
            exit 1
        fi
        echo "=== Updating PR #$PR_NUM ==="
        # 读取文件内容，转义为 JSON 字符串，通过 SSH 发送
        PR_BODY=$(python3 -c "import json,sys; print(json.dumps(open('$BODY_FILE').read()))")
        sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" \
          "curl -s -X PATCH -H 'Authorization: Bearer $GITHUB_TOKEN' \
            -H 'Content-Type: application/json' \
            -d '{\"body\": $PR_BODY}' \
            '$API/pulls/$PR_NUM'" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'PR #{d[\"number\"]}: {d[\"html_url\"]}')"
        ;;

    help|*)
        echo "用法:"
        echo "  ./scripts/push.sh push <branch>          推送分支到 GitHub"
        echo "  ./scripts/push.sh pr-update <n> <file>   从文件读取内容更新 PR 描述"
        exit 1
        ;;
esac