#!/usr/bin/env python3
"""
脚本 8: 框架行为分析
分析 error 前后的消息模式和时间间隔
检测: 错误前是否有大量重复操作、超长等待、重试循环等

用法: python3 08_error_pattern.py <logfile.jsonl>
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


def build_event_stream(lines, fmt):
    """构建统一的事件流"""
    events = []

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))

        if fmt == "new":
            if obj.get("type") == "message":
                msg = obj.get("message", {})
                role = msg.get("role", "")
                usage = msg.get("usage", {})
                stop = msg.get("stopReason", "")
                is_error = msg.get("isError", False) or stop == "error"
                # 提取工具名
                tools = []
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "toolCall":
                            tools.append(block.get("name", "?"))
                events.append({
                    "line": i, "time": ts, "type": "msg",
                    "role": role, "stop": stop, "is_error": is_error,
                    "input_tokens": usage.get("input", 0),
                    "output_tokens": usage.get("output", 0),
                    "tools": tools
                })
            elif obj.get("type") == "compaction":
                events.append({
                    "line": i, "time": ts, "type": "compaction",
                    "role": "system", "stop": "", "is_error": False,
                    "input_tokens": obj.get("tokensBefore", 0),
                    "output_tokens": 0, "tools": []
                })

        else:  # 旧格式
            otype = obj.get("type", "")
            if otype == "assistant":
                msg = obj.get("message", {})
                usage = msg.get("usage", {})
                stop = msg.get("stop_reason", "")
                is_api_err = obj.get("isApiErrorMessage", False)
                tools = []
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tools.append(block.get("name", "?"))
                inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                events.append({
                    "line": i, "time": ts, "type": "msg",
                    "role": "assistant", "stop": stop, "is_error": is_api_err,
                    "input_tokens": inp,
                    "output_tokens": usage.get("output_tokens", 0),
                    "tools": tools
                })
            elif otype == "user":
                msg = obj.get("message", {})
                content = msg.get("content", [])
                has_error = False
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("is_error"):
                            has_error = True
                events.append({
                    "line": i, "time": ts, "type": "msg",
                    "role": "user", "stop": "", "is_error": has_error,
                    "input_tokens": 0, "output_tokens": 0, "tools": []
                })
            elif otype == "system":
                sub = obj.get("subtype", "")
                is_err = sub == "api_error"
                events.append({
                    "line": i, "time": ts, "type": f"system:{sub}",
                    "role": "system", "stop": sub, "is_error": is_err,
                    "input_tokens": 0, "output_tokens": 0, "tools": [],
                    "retry": obj.get("retryAttempt"),
                    "duration": obj.get("durationMs")
                })

    return events


def analyze_error_patterns(events):
    """分析错误前后的模式"""
    # 找出所有错误事件的索引
    error_indices = [i for i, e in enumerate(events) if e["is_error"]]

    if not error_indices:
        print("未发现错误事件!")
        return

    print(f"发现 {len(error_indices)} 个错误事件")
    print()

    for err_idx in error_indices:
        err = events[err_idx]
        print(f"{'='*80}")
        ts = err["time"].strftime("%H:%M:%S") if err["time"] else "?"
        print(f"错误事件 @ 行 {err['line']} ({ts}): role={err['role']} stop={err['stop']} type={err['type']}")

        # 分析错误前 5 条消息
        print(f"\n  --- 错误前 5 条 ---")
        start = max(0, err_idx - 5)
        for j in range(start, err_idx):
            e = events[j]
            e_ts = e["time"].strftime("%H:%M:%S") if e["time"] else "?"
            # 计算与错误事件的时间差
            if e["time"] and err["time"]:
                delta_s = (err["time"] - e["time"]).total_seconds()
                delta_str = f"(-{delta_s:.0f}s)"
            else:
                delta_str = ""
            tools_str = ",".join(e["tools"]) if e["tools"] else ""
            print(f"  [{j}] 行{e['line']:>5}  {e_ts}  {delta_str:>8}  {e['role']:<10}  {e['type']:<15}  {e['stop']:<12}  in={e['input_tokens']:>7}  tools={tools_str}")

        # 分析错误后 5 条消息
        print(f"\n  --- 错误后 5 条 ---")
        end_range = min(len(events), err_idx + 6)
        for j in range(err_idx, end_range):
            e = events[j]
            e_ts = e["time"].strftime("%H:%M:%S") if e["time"] else "?"
            if e["time"] and err["time"]:
                delta_s = (e["time"] - err["time"]).total_seconds()
                delta_str = f"(+{delta_s:.0f}s)"
            else:
                delta_str = ""
            marker = " <<<" if j == err_idx else ""
            tools_str = ",".join(e["tools"]) if e["tools"] else ""
            print(f"  [{j}] 行{e['line']:>5}  {e_ts}  {delta_str:>8}  {e['role']:<10}  {e['type']:<15}  {e['stop']:<12}  in={e['input_tokens']:>7}  tools={tools_str}{marker}")

        print()

    # 汇总模式分析
    print(f"\n{'='*80}")
    print("模式分析汇总:")

    # 检查是否有连续错误 (重试循环)
    consecutive = 0
    max_consecutive = 0
    for i, e in enumerate(events):
        if e["is_error"]:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
    print(f"  最大连续错误数: {max_consecutive}")

    # 检查错误前的时间间隔模式
    for err_idx in error_indices:
        if err_idx > 0:
            prev = events[err_idx - 1]
            curr = events[err_idx]
            if prev["time"] and curr["time"]:
                gap = (curr["time"] - prev["time"]).total_seconds()
                if gap > 60:
                    print(f"  行 {curr['line']}: 错误前有 {gap:.0f}s 的长间隔 (可能是超时)")

    # 检查错误时的 token 使用
    error_tokens = [events[i]["input_tokens"] for i in error_indices if events[i]["input_tokens"] > 0]
    if error_tokens:
        print(f"  错误时的 input tokens: {error_tokens}")
        print(f"  平均: {sum(error_tokens)//len(error_tokens):,}")

    # 检查错误前的工具模式
    pre_error_tools = Counter()
    for err_idx in error_indices:
        for j in range(max(0, err_idx - 3), err_idx):
            for t in events[j]["tools"]:
                pre_error_tools[t] += 1
    if pre_error_tools:
        print(f"  错误前常见工具: {dict(pre_error_tools.most_common(5))}")


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

    events = build_event_stream(raw_lines, fmt)
    print(f"事件流: {len(events)} 条")

    # 时间间隔分析
    print(f"\n--- 时间间隔分布 ---")
    gaps = []
    for i in range(1, len(events)):
        if events[i]["time"] and events[i-1]["time"]:
            gap = (events[i]["time"] - events[i-1]["time"]).total_seconds()
            gaps.append(gap)
    if gaps:
        print(f"  最大间隔: {max(gaps):.1f}s")
        print(f"  平均间隔: {sum(gaps)/len(gaps):.1f}s")
        print(f"  >30s 的间隔: {sum(1 for g in gaps if g > 30)}")
        print(f"  >60s 的间隔: {sum(1 for g in gaps if g > 60)}")

    print()
    analyze_error_patterns(events)


if __name__ == "__main__":
    main()
