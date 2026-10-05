import re
import sys

# 允许的提交类型
ALLOWED_TYPES = ("feat", "fix", "refactor", "test", "docs", "chore", "perf")

# merge / revert / autosquash 提交不做格式校验
SKIP_PREFIXES = ("Merge ", "Revert ", "fixup! ", "squash! ", "amend! ")

# 标题格式：type(scope): 描述，scope 可省略，允许 Conventional Commits 的破坏性变更标记 !
TITLE_PATTERN = re.compile(r"^(feat|fix|refactor|test|docs|chore|perf)(\([^()]+\))?!?: \S.*$")


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
    if title.startswith(SKIP_PREFIXES) or TITLE_PATTERN.match(title):
        return 0

    print(f"提交信息不合规：{title}", file=sys.stderr)
    print(f"要求格式：type(scope): 描述，type 取 {'/'.join(ALLOWED_TYPES)}", file=sys.stderr)
    print("示例：fix(queue): 修复任务重复入队", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
