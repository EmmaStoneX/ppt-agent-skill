#!/usr/bin/env python3
"""
脚本 5: 工具调用统计
统计工具类型、频率、每次调用的内容大小

逻辑:
  - 提取所有 tool_use/toolCall 块
  - 统计每种工具的调用次数
  - 估算每次调用的 input 大小 (参数 JSON 大小)
  - 匹配对应的 toolResult 估算输出大小

用法: python3 05_tool_stats.py <logfile.jsonl>
"""
import json
import sys
from collections import Counter, defaultdict
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


def analyze_new_format(lines):
    """新格式: toolCall 在 assistant message 中, toolResult 在 toolResult role 中"""
    tool_calls = []  # (line, name, input_size, call_id)
    tool_results = {}  # call_id -> (line, output_size, is_error)

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        if obj.get("type") != "message":
            continue
        msg = obj.get("message", {})
        role = msg.get("role", "")
        ts = parse_ts(obj.get("timestamp"))

        if role == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        name = block.get("name", "?")
                        args = block.get("arguments", {})
                        input_size = len(json.dumps(args, ensure_ascii=False)) if args else 0
                        call_id = block.get("id", "")
                        tool_calls.append({
                            "line": i, "name": name, "input_size": input_size,
                            "call_id": call_id, "time": ts,
                            "args_preview": json.dumps(args, ensure_ascii=False)[:80] if args else ""
                        })

        elif role == "toolResult":
            call_id = msg.get("toolCallId", "")
            content = msg.get("content", [])
            output_size = 0
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        output_size += len(json.dumps(block, ensure_ascii=False))
                    elif isinstance(block, str):
                        output_size += len(block)
            elif isinstance(content, str):
                output_size = len(content)
            tool_results[call_id] = {
                "line": i,
                "output_size": output_size,
                "is_error": msg.get("isError", False),
                "tool_name": msg.get("toolName", "?")
            }

    # 匹配
    for tc in tool_calls:
        result = tool_results.get(tc["call_id"], {})
        tc["output_size"] = result.get("output_size", 0)
        tc["is_error"] = result.get("is_error", False)

    return tool_calls


def analyze_old_format(lines):
    """旧格式: tool_use 在 assistant message 中, tool_result 在 user message 中"""
    tool_calls = []
    tool_results = {}

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))

        if obj.get("type") == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        inp = block.get("input", {})
                        input_size = len(json.dumps(inp, ensure_ascii=False)) if inp else 0
                        call_id = block.get("id", "")
                        tool_calls.append({
                            "line": i, "name": name, "input_size": input_size,
                            "call_id": call_id, "time": ts,
                            "args_preview": json.dumps(inp, ensure_ascii=False)[:80] if inp else ""
                        })

        elif obj.get("type") == "user":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        call_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            output_size = sum(len(json.dumps(b, ensure_ascii=False)) for b in result_content)
                        elif isinstance(result_content, str):
                            output_size = len(result_content)
                        else:
                            output_size = len(str(result_content))
                        tool_results[call_id] = {
                            "line": i,
                            "output_size": output_size,
                            "is_error": block.get("is_error", False)
                        }

    for tc in tool_calls:
        result = tool_results.get(tc["call_id"], {})
        tc["output_size"] = result.get("output_size", 0)
        tc["is_error"] = result.get("is_error", False)

    return tool_calls


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
        tool_calls = analyze_new_format(raw_lines)
    else:
        tool_calls = analyze_old_format(raw_lines)

    # 按工具汇总
    tool_stats = defaultdict(lambda: {"count": 0, "input_total": 0, "output_total": 0, "errors": 0, "max_output": 0})
    for tc in tool_calls:
        name = tc["name"]
        tool_stats[name]["count"] += 1
        tool_stats[name]["input_total"] += tc["input_size"]
        tool_stats[name]["output_total"] += tc["output_size"]
        tool_stats[name]["max_output"] = max(tool_stats[name]["max_output"], tc["output_size"])
        if tc["is_error"]:
            tool_stats[name]["errors"] += 1

    print(f"\n共 {len(tool_calls)} 次工具调用")
    print()

    # 汇总表
    print(f"{'工具名':<25}  {'调用次数':>8}  {'输入总量':>10}  {'输出总量':>10}  {'平均输出':>10}  {'最大输出':>10}  {'错误数':>6}")
    print("-" * 95)
    for name in sorted(tool_stats, key=lambda n: tool_stats[n]["count"], reverse=True):
        s = tool_stats[name]
        avg_out = s["output_total"] // s["count"] if s["count"] > 0 else 0
        print(f"{name:<25}  {s['count']:>8}  {s['input_total']:>10,}  {s['output_total']:>10,}  {avg_out:>10,}  {s['max_output']:>10,}  {s['errors']:>6}")

    # 详细列表 (最大的前20个输出)
    print(f"\n--- 最大输出 TOP 20 ---")
    sorted_calls = sorted(tool_calls, key=lambda tc: tc["output_size"], reverse=True)[:20]
    print(f"{'行号':>5}  {'工具名':<20}  {'输入大小':>8}  {'输出大小':>10}  {'错误?':>5}  {'参数预览'}")
    print("-" * 100)
    for tc in sorted_calls:
        err_mark = "ERR" if tc["is_error"] else ""
        print(f"{tc['line']:>5}  {tc['name']:<20}  {tc['input_size']:>8,}  {tc['output_size']:>10,}  {err_mark:>5}  {tc['args_preview'][:50]}")


if __name__ == "__main__":
    main()
