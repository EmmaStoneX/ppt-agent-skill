#!/usr/bin/env python3
"""
脚本 4: 修复效果验证
对比两份日志的关键指标: token 消耗、错误率、工具调用、时长等

用法: python3 04_compare.py <logfile1.jsonl> <logfile2.jsonl>
  第一个参数为基线(旧), 第二个为修复后(新)
"""
import json
import sys
from datetime import datetime, timezone
from collections import Counter


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


def extract_metrics(filepath):
    """提取日志的关键指标"""
    with open(filepath, encoding="utf-8") as f:
        raw_lines = f.readlines()

    fmt = detect_format(raw_lines[0])
    metrics = {
        "file": filepath,
        "format": fmt,
        "total_lines": len(raw_lines),
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "max_input_tokens": 0,
        "api_calls": 0,
        "tool_calls": Counter(),
        "errors": 0,
        "api_errors": 0,
        "compactions": 0,
        "stop_reasons": Counter(),
        "timestamps": [],
        "turn_durations": [],
    }

    for raw in raw_lines:
        obj = json.loads(raw)

        if fmt == "new":
            # 新格式
            if obj.get("type") == "message":
                msg = obj.get("message", {})
                ts = parse_ts(obj.get("timestamp"))
                if ts:
                    metrics["timestamps"].append(ts)

                if msg.get("role") == "assistant":
                    usage = msg.get("usage", {})
                    inp = usage.get("input", 0)
                    out = usage.get("output", 0)
                    metrics["total_input_tokens"] += inp
                    metrics["total_output_tokens"] += out
                    metrics["max_input_tokens"] = max(metrics["max_input_tokens"], inp)
                    metrics["api_calls"] += 1
                    stop = msg.get("stopReason", "")
                    if stop:
                        metrics["stop_reasons"][stop] += 1
                    if stop == "error":
                        metrics["errors"] += 1

                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "toolCall":
                                metrics["tool_calls"][block.get("name", "?")] += 1

                elif msg.get("role") == "toolResult" and msg.get("isError"):
                    metrics["errors"] += 1

            elif obj.get("type") == "compaction":
                metrics["compactions"] += 1

        else:
            # 旧格式
            ts = parse_ts(obj.get("timestamp"))
            if ts:
                metrics["timestamps"].append(ts)

            if obj.get("type") == "assistant":
                msg = obj.get("message", {})
                usage = msg.get("usage", {})
                inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                out = usage.get("output_tokens", 0)
                metrics["total_input_tokens"] += inp
                metrics["total_output_tokens"] += out
                metrics["max_input_tokens"] = max(metrics["max_input_tokens"], inp)
                metrics["api_calls"] += 1
                stop = msg.get("stop_reason", "")
                if stop:
                    metrics["stop_reasons"][stop] += 1
                if obj.get("isApiErrorMessage") or obj.get("error"):
                    metrics["errors"] += 1

                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            metrics["tool_calls"][block.get("name", "?")] += 1

            elif obj.get("type") == "system":
                sub = obj.get("subtype", "")
                if sub == "api_error":
                    metrics["api_errors"] += 1
                elif sub == "compact_boundary":
                    metrics["compactions"] += 1
                elif sub == "turn_duration":
                    dur = obj.get("durationMs", 0)
                    if dur:
                        metrics["turn_durations"].append(dur)

            elif obj.get("type") == "user":
                msg = obj.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("is_error"):
                            metrics["errors"] += 1

    # 计算时间跨度
    if metrics["timestamps"]:
        metrics["start_time"] = min(metrics["timestamps"])
        metrics["end_time"] = max(metrics["timestamps"])
        metrics["duration_min"] = (metrics["end_time"] - metrics["start_time"]).total_seconds() / 60
    else:
        metrics["start_time"] = None
        metrics["end_time"] = None
        metrics["duration_min"] = 0

    return metrics


def print_comparison(m1, m2):
    """对比输出"""
    def delta_str(v1, v2, lower_better=True):
        if v1 == 0:
            return "N/A"
        pct = (v2 - v1) / v1 * 100
        arrow = "v" if (pct < 0 and lower_better) or (pct > 0 and not lower_better) else "^"
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}% {arrow}"

    print("=" * 80)
    print("修复效果对比报告")
    print("=" * 80)

    rows = [
        ("指标", "基线(文件1)", "修复后(文件2)", "变化"),
        ("-" * 20, "-" * 20, "-" * 20, "-" * 15),
        ("日志格式", m1["format"], m2["format"], ""),
        ("总行数", str(m1["total_lines"]), str(m2["total_lines"]), delta_str(m1["total_lines"], m2["total_lines"])),
        ("API 调用次数", str(m1["api_calls"]), str(m2["api_calls"]), delta_str(m1["api_calls"], m2["api_calls"])),
        ("总输入 tokens", f"{m1['total_input_tokens']:,}", f"{m2['total_input_tokens']:,}", delta_str(m1["total_input_tokens"], m2["total_input_tokens"])),
        ("总输出 tokens", f"{m1['total_output_tokens']:,}", f"{m2['total_output_tokens']:,}", delta_str(m1["total_output_tokens"], m2["total_output_tokens"])),
        ("最大输入 tokens", f"{m1['max_input_tokens']:,}", f"{m2['max_input_tokens']:,}", delta_str(m1["max_input_tokens"], m2["max_input_tokens"])),
        ("错误数", str(m1["errors"]), str(m2["errors"]), delta_str(m1["errors"], m2["errors"])),
        ("API 错误", str(m1["api_errors"]), str(m2["api_errors"]), delta_str(m1["api_errors"], m2["api_errors"])),
        ("Compaction 次数", str(m1["compactions"]), str(m2["compactions"]), delta_str(m1["compactions"], m2["compactions"])),
        ("会话时长(分)", f"{m1['duration_min']:.1f}", f"{m2['duration_min']:.1f}", delta_str(m1["duration_min"], m2["duration_min"])),
        ("工具调用总数", str(sum(m1["tool_calls"].values())), str(sum(m2["tool_calls"].values())), delta_str(sum(m1["tool_calls"].values()), sum(m2["tool_calls"].values()))),
    ]

    for row in rows:
        print(f"  {row[0]:<22}  {row[1]:<22}  {row[2]:<22}  {row[3]}")

    # stop_reason 分布
    print(f"\n--- Stop Reason 分布 ---")
    all_stops = set(m1["stop_reasons"].keys()) | set(m2["stop_reasons"].keys())
    print(f"  {'Stop Reason':<20}  {'基线':>8}  {'修复后':>8}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*8}")
    for s in sorted(all_stops):
        print(f"  {s:<20}  {m1['stop_reasons'].get(s,0):>8}  {m2['stop_reasons'].get(s,0):>8}")

    # 工具使用分布
    print(f"\n--- 工具调用分布 ---")
    all_tools = set(m1["tool_calls"].keys()) | set(m2["tool_calls"].keys())
    print(f"  {'工具名':<25}  {'基线':>8}  {'修复后':>8}")
    print(f"  {'-'*25}  {'-'*8}  {'-'*8}")
    for t in sorted(all_tools):
        print(f"  {t:<25}  {m1['tool_calls'].get(t,0):>8}  {m2['tool_calls'].get(t,0):>8}")


def main():
    if len(sys.argv) < 3:
        print(f"用法: python3 {sys.argv[0]} <baseline.jsonl> <fixed.jsonl>")
        print(f"  也可以只提供一个文件查看单个指标: python3 {sys.argv[0]} <logfile.jsonl>")
        if len(sys.argv) == 2:
            m = extract_metrics(sys.argv[1])
            print(f"\n单文件指标:")
            print(f"  格式: {m['format']}")
            print(f"  总行数: {m['total_lines']}")
            print(f"  API 调用: {m['api_calls']}")
            print(f"  总输入 tokens: {m['total_input_tokens']:,}")
            print(f"  总输出 tokens: {m['total_output_tokens']:,}")
            print(f"  最大输入 tokens: {m['max_input_tokens']:,}")
            print(f"  错误数: {m['errors']}")
            print(f"  Compactions: {m['compactions']}")
            print(f"  时长: {m['duration_min']:.1f} 分钟")
            print(f"  工具调用: {dict(m['tool_calls'])}")
            print(f"  Stop reasons: {dict(m['stop_reasons'])}")
        sys.exit(0)

    m1 = extract_metrics(sys.argv[1])
    m2 = extract_metrics(sys.argv[2])
    print_comparison(m1, m2)


if __name__ == "__main__":
    main()
