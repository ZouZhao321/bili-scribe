import re
import sys

# 允许的提交类型
ALLOWED_TYPES = ("feat", "fix", "refactor", "test", "docs", "chore", "perf")

# merge / revert / autosquash 提交不做格式校验
SKIP_PREFIXES = ("Merge ", "Revert ", "fixup! ", "squash! ", "amend! ")

# 标题格式：type(scope): 描述，scope 可省略，允许 Conventional Commits 的破坏性变更标记 !
TITLE_PATTERN = re.compile(r"^(feat|fix|refactor|test|docs|chore|perf)(\([^()]+\))?!?: \S.*$")

# Titles describe the change itself. Review rounds, reviewer references and batch item
# counts are process records: they mean nothing to later readers and they hide the fact
# that several unrelated changes were bundled into a single commit.
FORBIDDEN_PATTERNS = (
    (re.compile(r"第\s*[0-9一二三四五六七八九十百零]+\s*轮"), "引用审查轮次"),
    (re.compile(r"\b(ocr|ai|coderabbit|机器人)\b\s*(审核|评审|review)", re.IGNORECASE), "引用审查过程"),
    (re.compile(r"(修复|修正|处理|解决)\s*\d+\s*项"), "以条目数量描述批量改动"),
    (re.compile(r"\d+\s*项\s*(发现|修复|改动|问题|内容|意见)"), "以条目数量描述批量改动"),
)


def find_forbidden_phrase(title: str) -> str | None:
    """Return the reason of the first forbidden pattern the title matches, if any."""
    for pattern, reason in FORBIDDEN_PATTERNS:
        if pattern.search(title):
            return reason
    return None


def read_title(message_path):
    # 取第一条非空且非注释行作为标题
    with open(message_path, encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
    return ""


def main():
    if len(sys.argv) != 2:
        print("用法：python script/check_commit_msg.py <提交信息文件>", file=sys.stderr)
        return 2

    title = read_title(sys.argv[1])
    if title.startswith(SKIP_PREFIXES):
        return 0

    reason = find_forbidden_phrase(title)
    if reason is not None:
        print(f"提交信息不合规：{title}", file=sys.stderr)
        print(f"原因：{reason}。标题只描述变更本身，不写审查轮次、审查方与条目数量", file=sys.stderr)
        print("示例：fix(queue): 修复任务重复入队", file=sys.stderr)
        return 1

    if TITLE_PATTERN.match(title):
        return 0

    print(f"提交信息不合规：{title}", file=sys.stderr)
    print(f"要求格式：type(scope): 描述，type 取 {'/'.join(ALLOWED_TYPES)}", file=sys.stderr)
    print("示例：fix(queue): 修复任务重复入队", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
