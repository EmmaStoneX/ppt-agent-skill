#!/usr/bin/env python3
"""
脚本 7: 降级决策追踪
搜索"跳过"/"降级"/"skip"/"fallback"/"简化"等关键词
追踪降级决策的上下文和原因

用法: python3 07_degradation.py <logfile.jsonl>
"""
import json
import sys
import re
from collections import Counter
from datetime import datetime, timezone


def detect_format(first_line):
    obj = json.loads(first_line)
    if obj.get("type") == "session" and "version" in obj:
        return "new"
    return "old"


def parse_ts(ts_val):
    if not ts_val:
        return None
    if isinstance(ts_val, str):
        try:
            return datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
        except Exception:
            return None
    try:
        return datetime.fromtimestamp(int(ts_val) / 1000, tz=timezone.utc)
    except Exception:
        return None


# 降级相关关键词 (中文 + 英文)
DEGRADATION_PATTERNS = [
    (re.compile(r"跳过", re.IGNORECASE), "跳过"),
    (re.compile(r"降级", re.IGNORECASE), "降级"),
    (re.compile(r"简化", re.IGNORECASE), "简化"),
    (re.compile(r"省略", re.IGNORECASE), "省略"),
    (re.compile(r"fallback", re.IGNORECASE), "fallback"),
    (re.compile(r"skip(?:ping|ped)?", re.IGNORECASE), "skip"),
    (re.compile(r"degrad", re.IGNORECASE), "degrade"),
    (re.compile(r"simplif", re.IGNORECASE), "simplify"),
    (re.compile(r"减少", re.IGNORECASE), "减少"),
    (re.compile(r"精简", re.IGNORECASE), "精简"),
    (re.compile(r"截断", re.IGNORECASE), "截断"),
    (re.compile(r"truncat", re.IGNORECASE), "truncate"),
    (re.compile(r"too\s+(?:large|long|big|many)", re.IGNORECASE), "too_large"),
    (re.compile(r"context.*(?:limit|overflow|exceed)", re.IGNORECASE), "context_limit"),
    (re.compile(r"token.*(?:limit|budget|exceed)", re.IGNORECASE), "token_limit"),
    (re.compile(r"超[出过]", re.IGNORECASE), "超出"),
    (re.compile(r"无法|失败", re.IGNORECASE), "失败"),
    (re.compile(r"retry|重试", re.IGNORECASE), "重试"),
]


def extract_all_text(obj, fmt):
    """从一行数据中提取所有文本"""
    texts = []

    if fmt == "new":
        if obj.get("type") == "message":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            role = msg.get("role", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        t = block.get("text", "") or block.get("thinking", "")
                        if t:
                            texts.append((role, t))
            elif isinstance(content, str):
                texts.append((role, content))
        elif obj.get("type") == "compaction":
            s = obj.get("summary", "")
            if s:
                texts.append(("compaction", s))

    else:
        otype = obj.get("type", "")
        if otype in ("assistant", "user"):
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        t = block.get("text", "") or block.get("thinking", "")
                        if t:
                            texts.append((otype, t))
                        # tool_use/tool_result content
                        inp = block.get("input", {})
                        if isinstance(inp, dict):
                            for v in inp.values():
                                if isinstance(v, str) and len(v) > 10:
                                    texts.append((otype, v))
                        rc = block.get("content", "")
                        if isinstance(rc, str) and len(rc) > 10:
                            texts.append((otype, rc))
            elif isinstance(content, str):
                texts.append((otype, content))
            # toolUseResult 字段 (旧格式 user)
            tur = obj.get("toolUseResult", "")
            if isinstance(tur, str) and len(tur) > 10:
                texts.append((otype, tur))

    return texts


def search_degradation(text, line_no, role, ts):
    """在文本中搜索降级关键词"""
    findings = []
    for pattern, label in DEGRADATION_PATTERNS:
        matches = list(pattern.finditer(text))
        for m in matches:
            # 提取匹配位置前后的上下文
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            context = text[start:end].replace("\n", " ")
            findings.append({
                "line": line_no,
                "role": role,
                "keyword": label,
                "match": m.group(),
                "context": context,
                "time": ts
            })
    return findings


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

    all_findings = []
    keyword_counts = Counter()

    for i, raw in enumerate(raw_lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))
        ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"

        texts = extract_all_text(obj, fmt)
        for role, text in texts:
            findings = search_degradation(text, i, role, ts_str)
            for f_item in findings:
                all_findings.append(f_item)
                keyword_counts[f_item["keyword"]] += 1

    # 去重 (同一行 + 同一关键词只保留一次)
    seen = set()
    unique_findings = []
    for f_item in all_findings:
        key = (f_item["line"], f_item["keyword"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(f_item)

    print(f"\n共发现 {len(unique_findings)} 条降级相关记录 (去重后)")
    print()

    # 关键词汇总
    print("--- 关键词频率 ---")
    for kw, cnt in keyword_counts.most_common():
        print(f"  {kw}: {cnt}")

    # 详细列表 (按行号排序, 只看 assistant 的)
    print(f"\n--- 助手消息中的降级决策 (按时间序) ---")
    assistant_findings = [f for f in unique_findings if f["role"] in ("assistant",)]
    print(f"{'行号':>5}  {'时间':>8}  {'关键词':<12}  {'上下文'}")
    print("-" * 100)
    for f_item in sorted(assistant_findings, key=lambda x: x["line"])[:50]:
        print(f"{f_item['line']:>5}  {f_item['time']:>8}  {f_item['keyword']:<12}  {f_item['context'][:70]}")

    if len(assistant_findings) > 50:
        print(f"\n... 还有 {len(assistant_findings)-50} 条未显示")


if __name__ == "__main__":
    main()
