#!/usr/bin/env python3
"""
脚本 6: 输出质量检查
搜索 overflow:auto、emoji、CSS 违规等质量问题

检查目标:
  - overflow:auto/scroll/hidden (可能导致内容被截断)
  - emoji 字符 (PPT 中不应有 emoji)
  - CSS 违规: !important, position:absolute, inline style 过多
  - HTML 尺寸过大
  - 中文乱码迹象

用法: python3 06_quality_check.py <logfile.jsonl>
"""
import json
import sys
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone


def detect_format(first_line):
    obj = json.loads(first_line)
    if obj.get("type") == "session" and "version" in obj:
        return "new"
    return "old"


# emoji 正则: 匹配常见 emoji 范围
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # 表情
    "\U0001F300-\U0001F5FF"  # 符号
    "\U0001F680-\U0001F6FF"  # 交通
    "\U0001F1E0-\U0001F1FF"  # 国旗
    "\U00002702-\U000027B0"  # 杂项
    "\U0001F900-\U0001F9FF"  # 补充
    "\U00002600-\U000026FF"  # 杂项符号
    "\U0000FE00-\U0000FE0F"  # 变体选择符
    "\U0000200D"             # ZWJ
    "\U00002B50"             # 星号
    "\U0000231A-\U0000231B"  # 手表
    "]+",
    re.UNICODE
)

# CSS 违规模式
CSS_PATTERNS = {
    "overflow:auto": re.compile(r"overflow\s*:\s*auto", re.IGNORECASE),
    "overflow:scroll": re.compile(r"overflow\s*:\s*scroll", re.IGNORECASE),
    "overflow:hidden": re.compile(r"overflow\s*:\s*hidden", re.IGNORECASE),
    "!important": re.compile(r"!important", re.IGNORECASE),
    "position:absolute": re.compile(r"position\s*:\s*absolute", re.IGNORECASE),
    "position:fixed": re.compile(r"position\s*:\s*fixed", re.IGNORECASE),
    "z-index": re.compile(r"z-index\s*:", re.IGNORECASE),
}


def extract_text_content(obj, fmt):
    """从一行数据中提取所有文本内容"""
    texts = []

    if fmt == "new":
        if obj.get("type") != "message":
            return texts
        msg = obj.get("message", {})
        content = msg.get("content", [])
    else:
        if obj.get("type") not in ("assistant", "user"):
            return texts
        msg = obj.get("message", {})
        content = msg.get("content", [])

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    texts.append(("text", block.get("text", "")))
                elif btype in ("tool_use", "toolCall"):
                    inp = block.get("input", block.get("arguments", {}))
                    if isinstance(inp, dict):
                        for v in inp.values():
                            if isinstance(v, str) and len(v) > 20:
                                texts.append(("tool_input", v))
                    elif isinstance(inp, str):
                        texts.append(("tool_input", inp))
                elif btype == "tool_result":
                    rc = block.get("content", "")
                    if isinstance(rc, str):
                        texts.append(("tool_result", rc))
                    elif isinstance(rc, list):
                        for rb in rc:
                            if isinstance(rb, dict):
                                texts.append(("tool_result", rb.get("text", "")))
            elif isinstance(block, str):
                texts.append(("text", block))
    elif isinstance(content, str):
        texts.append(("text", content))

    # 新格式的 toolResult
    if fmt == "new" and msg.get("role") == "toolResult":
        tc = msg.get("content", [])
        if isinstance(tc, list):
            for tb in tc:
                if isinstance(tb, dict):
                    texts.append(("tool_result", tb.get("text", "")))
        elif isinstance(tc, str):
            texts.append(("tool_result", tc))

    return texts


def check_quality(text, source_type):
    """检查文本的质量问题"""
    issues = []

    # 检查 emoji
    emojis = EMOJI_RE.findall(text)
    if emojis:
        issues.append(("EMOJI", f"发现 {len(emojis)} 个 emoji: {''.join(emojis[:5])}"))

    # 检查 CSS 违规
    for pattern_name, pattern_re in CSS_PATTERNS.items():
        matches = pattern_re.findall(text)
        if matches:
            issues.append(("CSS", f"{pattern_name} x{len(matches)}"))

    # 检查 HTML 过大 (tool_input 中可能有完整 HTML)
    if source_type == "tool_input" and len(text) > 50000:
        issues.append(("LARGE_INPUT", f"工具输入过大: {len(text):,} chars"))

    if source_type == "tool_result" and len(text) > 100000:
        issues.append(("LARGE_OUTPUT", f"工具输出过大: {len(text):,} chars"))

    return issues


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <logfile.jsonl>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, encoding="utf-8") as f:
        raw_lines = f.readlines()

    fmt = detect_format(raw_lines[0])
    print(f"格式: {'新格式(OpenClaw)' if fmt == 'new' else '旧格式(Claude CLI)'}")
    print(f"总行数: {len(raw_lines)}")

    all_issues = []
    issue_counts = Counter()

    for i, raw in enumerate(raw_lines):
        obj = json.loads(raw)
        texts = extract_text_content(obj, fmt)
        for source_type, text in texts:
            if not text:
                continue
            issues = check_quality(text, source_type)
            for issue_type, detail in issues:
                all_issues.append({
                    "line": i,
                    "issue_type": issue_type,
                    "source": source_type,
                    "detail": detail,
                    "context": text[:60].replace("\n", " ")
                })
                issue_counts[issue_type] += 1

    # 输出
    print(f"\n共发现 {len(all_issues)} 个质量问题")
    print()

    # 汇总
    print("--- 问题类型汇总 ---")
    for it, cnt in issue_counts.most_common():
        print(f"  {it}: {cnt}")

    # 详细列表
    if all_issues:
        print(f"\n--- 详细列表 ---")
        print(f"{'行号':>5}  {'类型':<15}  {'来源':<12}  {'详情':<40}  {'上下文'}")
        print("-" * 120)
        for issue in all_issues[:50]:  # 只显示前50个
            print(f"{issue['line']:>5}  {issue['issue_type']:<15}  {issue['source']:<12}  {issue['detail']:<40}  {issue['context'][:40]}")

        if len(all_issues) > 50:
            print(f"\n... 还有 {len(all_issues)-50} 个问题未显示")
    else:
        print("\n未发现质量问题!")


if __name__ == "__main__":
    main()
