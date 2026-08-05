#!/usr/bin/env python3
"""
转录文稿口语化 → 书面化转换工具（改进版）
将 out/ 下所有目录中的 转录文稿.txt 转换为书面化文稿，保存为 书面文稿.txt
"""

import os
import re
import glob

# ========== 转换规则 ==========

# 1. 需要去除的口语填充词（独立词语，不影响正文）
FILLER_PATTERNS = [
    (r"对吧", ""),
    (r"对不对", ""),
    (r"是不是", ""),
    (r"是吧", ""),
    (r"好不好", ""),
    (r"懂吧", ""),
    (r"你懂吧", ""),
    (r"你懂了吗", ""),
    (r"听清楚了吗", ""),
    (r"听懂了没有", ""),
    (r"听懂了吗", ""),
    (r"知道了没有", ""),
    (r"明白了吗", ""),
    (r"知道了吧", ""),
    (r"懂不懂", ""),
    (r"你知不知道", ""),
    (r"晓得不", ""),
    (r"晓得了不", ""),
    (r"我跟你说", ""),
    (r"我告诉你", ""),
    (r"我跟你们说", ""),
    (r"我跟大家说", ""),
    # 语气词（独立出现时）
    (r"\b嗯\s+", ""),
    (r"嗯，", ""),
    (r"嗯。", "。"),
    (r"\b啊\s+", ""),
    (r"啊，", ""),
    (r"\b诶\s+", ""),
    (r"诶，", ""),
    (r"\b哎\s+", ""),
    (r"哎，", ""),
    (r"\b哦\s+", ""),
    (r"哦，", ""),
    (r"\b噢\s+", ""),
    (r"噢，", ""),
    (r"嘛，", ""),
    (r"嘛 ", ""),
    (r"好吧", ""),
    (r"好了", ""),
    (r"行吧", ""),
    (r"那行", ""),
    (r"那好吧", ""),
    (r"那这样", "那么"),
    (r"那这样吧", "那么"),
    (r"那咱们", "我们"),
    (r"咱们", "我们"),
    # 句末的语气词
    (r"啦", "了"),
    (r"喽", "了"),
    (r"哟", ""),
    (r"喔", ""),
    (r"咩", ""),
    (r"欸", ""),
]

# 2. 口语化表达 → 书面化表达（谨慎替换，不改变原意）
SPOKEN_TO_WRITTEN = [
    # 注意：不要替换"然后" → "此外"，因为"然后"在中文中也是合理的连接词
    # 只替换没有实际意义的"然后就是"、"然后呢"
    (r"然后就是", ""),
    (r"然后呢", ""),
    (r"就是说", "即"),
    (r"也就是说", "换言之"),
    (r"所以说", "因此"),
    (r"所以说呢", "因此"),
    (r"比如说", "例如"),
    (r"打个比方", "举例而言"),
    (r"举例子", "举例"),
    (r"举个例子", "举例而言"),
    (r"这样子", "如此"),
    (r"那样子", "那般"),
    (r"这么说吧", "换言之"),
    (r"这么来看", "由此观之"),
    (r"这么一说", "如此看来"),
    (r"说白了", "简而言之"),
    (r"简单来说", "简言之"),
    (r"简单点说", "简言之"),
    (r"总的来说", "总体而言"),
    (r"总的来看", "总体而言"),
    (r"整体来说", "整体而言"),
    (r"整体来看", "整体而言"),
    (r"基本上", "大体上"),
    (r"说实话", "坦诚而言"),
    (r"老实说", "平心而论"),
    (r"讲真的", "诚然"),
    (r"非常非常非常", "极其"),
    (r"非常非常", "非常"),
    (r"特别特别特别", "极为"),
    (r"特别特别", "特别"),
    (r"很很很很", "极其"),
    (r"很很很", "非常"),
    (r"有很多很多", "有诸多"),
    (r"很多很多", "诸多"),
    (r"太多太多", "过多"),
    (r"一大堆", "大量"),
    # "你"不替换，保留原样
]

# 3. 标点符号规范化
PUNCTUATION_FIXES = [
    (r"\.\.\.\.\.\.", "……"),
    (r"\.\.\.\.\.", "……"),
    (r"\.\.\.\.", "……"),
    (r"\.\.\.", "……"),
    (r"！{2,}", "！"),
    (r"？{2,}", "？"),
    (r"，{2,}", "，"),
    (r" {2,}", " "),
]


def clean_fillers(text):
    """去除口语填充词"""
    for pattern, replacement in FILLER_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def convert_spoken_to_written(text):
    """口语表达转书面语"""
    for pattern, replacement in SPOKEN_TO_WRITTEN:
        text = re.sub(pattern, replacement, text)
    return text


def fix_punctuation(text):
    """规范化标点符号"""
    for pattern, replacement in PUNCTUATION_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def clean_whitespace(text):
    """清理多余空白"""
    # 合并多个空行为一个
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines)


def fix_whisper_errors(text):
    """修正常见的 Whisper 转录错误"""
    corrections = [
        # 网文相关术语（高频错误）
        (r"欲如过万", "月入过万"),
        (r"欲如过半", "月入过万"),
        (r"运入郭万", "月入过万"),
        (r"西小说", "写小说"),
        (r"起小说", "写小说"),
        (r"写写小说", "写小说"),
        (r"写写", "写"),
        (r"王小说", "写小说"),
        (r"王小小说", "写小说"),
        (r"戴如感", "代入感"),
        (r"人色", "人设"),
        (r"人设", "人设"),  # 确保正确
        (r"湖光", "弧光"),
        (r"人物湖光", "人物弧光"),
        (r"人物浮光", "人物弧光"),
        (r"惠丽一", "绘梨衣"),
        (r"萧雄", "枭雄"),
        (r"三观演义", "三国演义"),
        (r"杜佛", "杜甫"),
        (r"自治通鉴", "资治通鉴"),
        (r"郭万", "过万"),
        (r"职务上", "创作"),
        (r"职务上当中", "创作过程中"),
        (r"职务", "创作"),
        (r"选手", "作者"),
        (r"空空付费", "慷慨付费"),
        (r"酷酷付费", "慷慨付费"),
        (r"国草", "感觉"),
        (r"感到感觉", "感觉"),
        (r"修教", "休教"),
        (r"找班", "照搬"),
        (r"我考", ""),
        (r"我草", ""),
        (r"我靠", ""),
        (r"牛逼", "出色"),
        (r"啥", "什么"),
        (r"干嘛", "做什么"),
        (r"咋", "怎么"),
        (r"咋样", "怎么样"),
        (r"甭", "不用"),
        # 重复字符（超过3个重复缩为2个）
        (r"(.)\1{4,}", r"\1\1"),
    ]
    for pattern, replacement in corrections:
        text = re.sub(pattern, replacement, text)
    return text


def post_process(text):
    """后处理：修复转换导致的额外问题"""
    # 修复"此外"滥用（如果有）
    # 修复"读者"滥用（如果前面的转换引入了"读者"）
    # 修复重复的空格和标点
    text = re.sub(r"，+", "，", text)
    text = re.sub(r"。+", "。", text)
    # 去除多余空格
    text = re.sub(r" +", " ", text)
    # 修复"此外"在句首不当使用
    # 如果"此外"出现过于频繁（每段多次），改为"同时"
    # 但这个靠统计很难，先不做

    # 修复"大家"被错误替换为"读者"的情况
    # 检查上下文：如果"读者"出现在"教"、"帮"、"希望"等词后面，
    # 且指向的是听众而非书中的读者，改为"大家"
    text = re.sub(r"教读者", "教大家", text)
    text = re.sub(r"帮读者", "帮大家", text)
    text = re.sub(r"希望读者", "希望大家", text)
    text = re.sub(r"给读者", "给大家", text)
    text = re.sub(r"让读者们", "让大家", text)
    text = re.sub(r"读者们", "大家", text)
    text = re.sub(r"读者可以", "大家可以", text)
    text = re.sub(r"读者们可以", "大家可以", text)
    text = re.sub(r"读者能够", "大家能够", text)
    text = re.sub(r"读者也", "大家也", text)
    text = re.sub(r"读者去", "大家去", text)
    text = re.sub(r"读者在", "大家在", text)
    text = re.sub(r"读者的书", "你们的书", text)
    text = re.sub(r"读者的小说", "你们的小说", text)
    text = re.sub(r"读者自己的", "你们自己的", text)
    text = re.sub(r"读者是不是", "是不是", text)
    text = re.sub(r"读者在写", "大家在写", text)
    text = re.sub(r"读者在创作", "大家在创作", text)
    # 修复"读者"前面没有空格的
    text = re.sub(r"那么读者", "那么", text)
    # 修复元数据行中的多余替换
    return text


def convert_file(input_path, output_path):
    """转换单个文件"""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, IOError) as e:
        print(f"  ❌ 读取失败: {e}")
        return

    # 检查是否只有 10 行左右（转录不完整）
    lines = content.strip().split("\n")
    if len(lines) <= 15:
        # 转录不完整，保持原样
        if os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    existing = f.read()
                if len(existing.strip().split("\n")) > 15:
                    return
            except (FileNotFoundError, IOError):
                pass
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
        except IOError as e:
            print(f"  ❌ 写入失败: {e}")
            return
        print(f"  ⚠️  转录不完整（{len(lines)}行），保持原样")
        return

    # 应用转换
    body = content
    body = fix_whisper_errors(body)
    body = clean_fillers(body)
    body = convert_spoken_to_written(body)
    body = fix_punctuation(body)
    body = clean_whitespace(body)
    body = post_process(body)

    # 写入输出
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(body)
    except IOError as e:
        print(f"  ❌ 写入失败: {e}")
        return

    print(f"  ✅ 转换完成: {len(lines)}行 → {len(body.split(chr(10)))}行")


def main():
    # 支持新结构 library/ 和旧结构 out/，优先扫描新结构
    pattern_lib = os.path.join("library", "作者", "*", "*", "转录文稿.txt")
    pattern_out = os.path.join("out", "*", "转录文稿.txt")
    files = sorted(glob.glob(pattern_lib) + glob.glob(pattern_out))

    print(f"找到 {len(files)} 个转录文稿\n")

    for i, input_path in enumerate(files, 1):
        dir_path = os.path.dirname(input_path)
        output_path = os.path.join(dir_path, "书面文稿.txt")
        dir_name = os.path.basename(dir_path)

        print(f"[{i}/{len(files)}] {dir_name[:40]}...")
        convert_file(input_path, output_path)

    print("\n所有文件处理完成！")


if __name__ == "__main__":
    main()
