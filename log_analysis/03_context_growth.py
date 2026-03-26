#!/usr/bin/env python3
"""
脚本 3: 上下文增长曲线
输出每次 API 调用的 input_tokens，标注增长量和可能的膨胀原因

逻辑:
  - 提取每次 assistant 回复的 input tokens
  - 计算与上一次的增量 (delta)
  - 标注增长异常原因: 大增量可能来自大工具输出、compaction 重置等

用法: python3 03_context_growth.py <logfile.jsonl>
"""
import json
import sys
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


def extract_new_format(lines):
    """新格式: 从 message(role=assistant) 提取 usage"""
    data_points = []
    compaction_lines = set()

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        if obj.get("type") == "compaction":
            compaction_lines.add(i)
            data_points.append({
                "line": i,
                "time": parse_ts(obj.get("timestamp")),
                "input_tokens": 0,
                "output_tokens": 0,
                "is_compaction": True,
                "tokens_before": obj.get("tokensBefore", 0),
                "tool_context": "COMPACTION"
            })
        elif obj.get("type") == "message":
            msg = obj.get("message", {})
            if msg.get("role") != "assistant":
                continue
            usage = msg.get("usage", {})
            if not usage:
                continue
            inp = usage.get("input", 0)
            out = usage.get("output", 0)
            stop = msg.get("stopReason", "")
            # 提取工具名称作为上下文
            tools = []
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("toolCall", "tool_use"):
                        tools.append(block.get("name", "?"))
            tool_ctx = ",".join(tools) if tools else stop
            data_points.append({
                "line": i,
                "time": parse_ts(obj.get("timestamp")),
                "input_tokens": inp,
                "output_tokens": out,
                "is_compaction": False,
                "tokens_before": 0,
                "tool_context": tool_ctx
            })
    return data_points


def extract_old_format(lines):
    """旧格式: 从 assistant type 提取 usage"""
    data_points = []

    for i, raw in enumerate(lines):
        obj = json.loads(raw)

        if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary":
            meta = obj.get("compactMetadata", {})
            data_points.append({
                "line": i,
                "time": parse_ts(obj.get("timestamp")),
                "input_tokens": 0,
                "output_tokens": 0,
                "is_compaction": True,
                "tokens_before": meta.get("preTokens", 0),
                "tool_context": f"COMPACTION({meta.get('trigger','')})"
            })
        elif obj.get("type") == "assistant":
            msg = obj.get("message", {})
            usage = msg.get("usage", {})
            if not usage:
                continue
            # 旧格式的 input 计算: input_tokens + cache_read_input_tokens
            inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            out = usage.get("output_tokens", 0)
            stop = msg.get("stop_reason", "")
            # 提取工具名
            tools = []
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tools.append(block.get("name", "?"))
            tool_ctx = ",".join(tools) if tools else (stop or "-")
            data_points.append({
                "line": i,
                "time": parse_ts(obj.get("timestamp")),
                "input_tokens": inp,
                "output_tokens": out,
                "is_compaction": False,
                "tokens_before": 0,
                "tool_context": tool_ctx
            })
    return data_points


def annotate_growth(data_points):
    """标注增长量和膨胀原因"""
    prev_input = 0
    for dp in data_points:
        if dp["is_compaction"]:
            dp["delta"] = -(dp["tokens_before"])  # compaction 减少
            dp["annotation"] = f"<-- 压缩前 {dp['tokens_before']} tokens"
            prev_input = 0  # 重置
        else:
            delta = dp["input_tokens"] - prev_input
            dp["delta"] = delta
            # 判断膨胀原因
            if delta > 20000:
                dp["annotation"] = "<-- 大幅增长! 可能是大文件读取/大工具输出"
            elif delta > 10000:
                dp["annotation"] = "<-- 显著增长"
            elif delta < -10000:
                dp["annotation"] = "<-- 大幅下降 (可能 compaction 后)"
            elif delta < 0:
                dp["annotation"] = "<-- 下降 (cache?)"
            else:
                dp["annotation"] = ""
            prev_input = dp["input_tokens"]
    return data_points


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <logfile.jsonl>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, encoding="utf-8") as f:
        raw_lines = f.readlines()

    fmt = detect_format(raw_lines[0])
    print(f"格式: {'新格式(OpenClaw)' if fmt == 'new' else '旧格式(Claude CLI)'}")

    if fmt == "new":
        data_points = extract_new_format(raw_lines)
    else:
        data_points = extract_old_format(raw_lines)

    data_points = annotate_growth(data_points)

    print(f"共 {len(data_points)} 次 API 调用")
    print()
    print(f"{'#':>3}  {'行号':>5}  {'时间':>8}  {'输入tok':>9}  {'输出tok':>8}  {'增量':>9}  {'工具/上下文':<25}  {'标注'}")
    print("-" * 130)

    max_input = 0
    total_output = 0
    for idx, dp in enumerate(data_points):
        ts = dp["time"].strftime("%H:%M:%S") if dp["time"] else "??:??:??"
        max_input = max(max_input, dp["input_tokens"])
        total_output += dp["output_tokens"]

        # 简单的 ASCII 柱状图
        bar_len = min(dp["input_tokens"] // 5000, 30) if dp["input_tokens"] > 0 else 0
        bar = "#" * bar_len

        print(f"{idx:>3}  {dp['line']:>5}  {ts:>8}  {dp['input_tokens']:>9,}  {dp['output_tokens']:>8,}  {dp['delta']:>+9,}  {dp['tool_context']:<25}  {dp['annotation']}")

    # 汇总统计
    inputs = [dp["input_tokens"] for dp in data_points if not dp["is_compaction"]]
    print(f"\n--- 统计 ---")
    print(f"  最大 input tokens: {max(inputs) if inputs else 0:,}")
    print(f"  最小 input tokens: {min(inputs) if inputs else 0:,}")
    print(f"  平均 input tokens: {sum(inputs)//len(inputs) if inputs else 0:,}")
    print(f"  总 output tokens:  {total_output:,}")
    print(f"  Compaction 次数:   {sum(1 for dp in data_points if dp['is_compaction'])}")


if __name__ == "__main__":
    main()
