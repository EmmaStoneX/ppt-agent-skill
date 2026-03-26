#!/usr/bin/env python3
"""
脚本 2: 异常终止事件
找出所有 error/terminated/length 类型的终止，输出行号、时间、usage

兼容两种 JSONL 格式:
  - 新格式: stopReason = error/stop/toolUse
  - 旧格式: stop_reason = end_turn/tool_use/stop_sequence, subtype=api_error

用法: python3 02_errors.py <logfile.jsonl>
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


def analyze_new_format(lines):
    """新格式: 检查 stopReason=error 和 compaction"""
    events = []
    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "?"

        if obj.get("type") == "message":
            msg = obj.get("message", {})
            stop = msg.get("stopReason", "")
            usage = msg.get("usage", {})
            role = msg.get("role", "")

            # 异常终止: error, length, 或者非正常 stop
            if stop in ("error", "length"):
                err_msg = msg.get("errorMessage", "")
                events.append({
                    "line": i, "time": ts_str, "type": f"STOP:{stop}",
                    "role": role,
                    "input_tokens": usage.get("input", 0),
                    "output_tokens": usage.get("output", 0),
                    "total_tokens": usage.get("totalTokens", 0),
                    "detail": str(err_msg)[:100] if err_msg else ""
                })

            # isError 在 toolResult 中
            if role == "toolResult":
                is_err = msg.get("isError", False)
                if is_err:
                    tool_name = msg.get("toolName", "?")
                    events.append({
                        "line": i, "time": ts_str, "type": "TOOL_ERROR",
                        "role": role,
                        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                        "detail": f"tool={tool_name}"
                    })

        elif obj.get("type") == "compaction":
            events.append({
                "line": i, "time": ts_str, "type": "COMPACTION",
                "role": "-",
                "input_tokens": obj.get("tokensBefore", 0),
                "output_tokens": 0, "total_tokens": 0,
                "detail": f"tokensBefore={obj.get('tokensBefore', 0)}"
            })

    return events


def analyze_old_format(lines):
    """旧格式: 检查 api_error, stop_sequence, isApiErrorMessage"""
    events = []
    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "?"

        if obj.get("type") == "assistant":
            msg = obj.get("message", {})
            stop = msg.get("stop_reason", "")
            usage = msg.get("usage", {})
            is_api_err = obj.get("isApiErrorMessage", False)

            input_t = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            output_t = usage.get("output_tokens", 0)

            if is_api_err or obj.get("error"):
                events.append({
                    "line": i, "time": ts_str, "type": "API_ERROR",
                    "role": "assistant",
                    "input_tokens": input_t, "output_tokens": output_t,
                    "total_tokens": input_t + output_t,
                    "detail": f"error={obj.get('error', '')}"[:100]
                })
            elif stop == "stop_sequence":
                events.append({
                    "line": i, "time": ts_str, "type": f"STOP:{stop}",
                    "role": "assistant",
                    "input_tokens": input_t, "output_tokens": output_t,
                    "total_tokens": input_t + output_t,
                    "detail": ""
                })

        elif obj.get("type") == "system":
            sub = obj.get("subtype", "")
            if sub == "api_error":
                err = obj.get("error", {})
                status = err.get("status", "?") if isinstance(err, dict) else str(err)[:50]
                events.append({
                    "line": i, "time": ts_str, "type": "SYS:API_ERROR",
                    "role": "system",
                    "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                    "detail": f"status={status} retry={obj.get('retryAttempt','')}/{obj.get('maxRetries','')} wait={obj.get('retryInMs',0):.0f}ms"
                })
            elif sub == "compact_boundary":
                meta = obj.get("compactMetadata", {})
                events.append({
                    "line": i, "time": ts_str, "type": "COMPACT",
                    "role": "system",
                    "input_tokens": meta.get("preTokens", 0),
                    "output_tokens": 0, "total_tokens": 0,
                    "detail": f"trigger={meta.get('trigger', '')}"
                })

        elif obj.get("type") == "user":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("is_error"):
                        events.append({
                            "line": i, "time": ts_str, "type": "TOOL_RESULT_ERROR",
                            "role": "user",
                            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                            "detail": str(block.get("content", ""))[:80]
                        })

    return events


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

    if fmt == "new":
        events = analyze_new_format(raw_lines)
    else:
        events = analyze_old_format(raw_lines)

    print(f"\n共发现 {len(events)} 个异常事件:")
    print()
    print(f"{'行号':>5}  {'时间':>19}  {'类型':<18}  {'输入tok':>8}  {'输出tok':>8}  {'详情'}")
    print("-" * 110)
    for e in events:
        print(f"{e['line']:>5}  {e['time']:>19}  {e['type']:<18}  {e['input_tokens']:>8}  {e['output_tokens']:>8}  {e['detail']}")

    # 汇总
    from collections import Counter
    type_counts = Counter(e["type"] for e in events)
    print(f"\n--- 异常类型汇总 ---")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
