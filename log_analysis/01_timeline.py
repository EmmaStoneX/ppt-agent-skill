#!/usr/bin/env python3
"""
脚本 1: 会话时间线
输出每条消息的时间戳、角色、摘要（工具名/内容前50字）

兼容两种 JSONL 格式:
  - 新格式 (OpenClaw): type=session/message/compaction, message.role=user/assistant/toolResult
  - 旧格式 (Claude CLI): type=user/assistant/system/progress, message.role=user/assistant

用法: python3 01_timeline.py <logfile.jsonl>
"""
import json
import sys
from datetime import datetime, timezone


def detect_format(first_line):
    """根据第一行判断日志格式: 'new' or 'old'"""
    obj = json.loads(first_line)
    if obj.get("type") == "session" and "version" in obj:
        return "new"
    return "old"


def parse_iso_ts(ts_str):
    """解析 ISO 格式时间戳字符串"""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def parse_epoch_ms(ts_val):
    """解析毫秒级 epoch 时间戳"""
    if not ts_val:
        return None
    try:
        return datetime.fromtimestamp(int(ts_val) / 1000, tz=timezone.utc)
    except Exception:
        return None


def get_timestamp(obj, fmt):
    """从一行数据中提取时间戳"""
    if fmt == "new":
        ts = obj.get("timestamp", "")
        if isinstance(ts, str):
            return parse_iso_ts(ts)
        return parse_epoch_ms(ts)
    else:
        ts = obj.get("timestamp", "")
        if isinstance(ts, str):
            return parse_iso_ts(ts)
        return parse_epoch_ms(ts)


def summarize_content_blocks(blocks, max_len=50):
    """从 content blocks 中提取摘要"""
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            text = block.get("text", "")
            if text:
                parts.append(text[:max_len].replace("\n", " "))
        elif btype in ("tool_use", "toolCall"):
            name = block.get("name", "?")
            parts.append(f"[tool:{name}]")
        elif btype == "tool_result":
            parts.append("[tool_result]")
        elif btype == "thinking":
            parts.append("[thinking]")
    return " | ".join(parts) if parts else "-"


def process_new_format(lines):
    """处理新格式 (OpenClaw)"""
    results = []
    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        otype = obj.get("type", "")
        ts = get_timestamp(obj, "new")
        ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"

        if otype == "session":
            results.append((i, ts_str, "SESSION", f"id={obj.get('id','')[:12]} cwd={obj.get('cwd','')}"))
        elif otype == "model_change":
            results.append((i, ts_str, "MODEL", f"{obj.get('provider','')} / {obj.get('modelId','')}"))
        elif otype == "compaction":
            results.append((i, ts_str, "COMPACT", f"tokensBefore={obj.get('tokensBefore','')}"))
        elif otype == "message":
            msg = obj.get("message", {})
            role = msg.get("role", "?")
            content = msg.get("content", [])
            usage = msg.get("usage", {})
            stop = msg.get("stopReason", "")

            if isinstance(content, list):
                summary = summarize_content_blocks(content)
            elif isinstance(content, str):
                summary = content[:50].replace("\n", " ")
            else:
                summary = "-"

            # 附加 usage 信息
            extra = ""
            if usage:
                inp = usage.get("input", 0)
                out = usage.get("output", 0)
                extra = f" (in={inp} out={out})"
            if stop and stop not in ("toolUse", "tool_use"):
                extra += f" [stop={stop}]"

            results.append((i, ts_str, role.upper(), summary[:80] + extra))
    return results


def process_old_format(lines):
    """处理旧格式 (Claude CLI)"""
    results = []
    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        otype = obj.get("type", "")
        ts = get_timestamp(obj, "old")
        ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"

        if otype == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            usage = msg.get("usage", {})
            stop = msg.get("stop_reason", "")

            if isinstance(content, list):
                summary = summarize_content_blocks(content)
            elif isinstance(content, str):
                summary = content[:50].replace("\n", " ")
            else:
                summary = "-"

            extra = ""
            if usage:
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                extra = f" (in={inp} out={out})"
            if stop and stop not in ("tool_use",):
                extra += f" [stop={stop}]"

            results.append((i, ts_str, "ASSISTANT", summary[:80] + extra))

        elif otype == "user":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                summary = summarize_content_blocks(content)
            elif isinstance(content, str):
                summary = content[:50].replace("\n", " ")
            else:
                summary = str(obj.get("toolUseResult", ""))[:50] or "-"
            results.append((i, ts_str, "USER", summary[:80]))

        elif otype == "system":
            sub = obj.get("subtype", "")
            if sub == "api_error":
                err = obj.get("error", {})
                results.append((i, ts_str, "SYS:ERROR", f"status={err.get('status','')} retry={obj.get('retryAttempt','')}"))
            elif sub == "compact_boundary":
                meta = obj.get("compactMetadata", {})
                results.append((i, ts_str, "SYS:COMPACT", f"trigger={meta.get('trigger','')} preTokens={meta.get('preTokens','')}"))
            elif sub == "turn_duration":
                results.append((i, ts_str, "SYS:TURN", f"duration={obj.get('durationMs','')}ms"))

        elif otype == "progress":
            data = obj.get("data", {})
            if isinstance(data, dict):
                results.append((i, ts_str, "PROGRESS", f"{data.get('type','')} {data.get('hookName','')}"))
    return results


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <logfile.jsonl>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, encoding="utf-8") as f:
        raw_lines = f.readlines()

    if not raw_lines:
        print("空文件")
        sys.exit(0)

    fmt = detect_format(raw_lines[0])
    print(f"检测到格式: {'新格式(OpenClaw)' if fmt == 'new' else '旧格式(Claude CLI)'}")
    print(f"总行数: {len(raw_lines)}")
    print()

    if fmt == "new":
        results = process_new_format(raw_lines)
    else:
        results = process_old_format(raw_lines)

    # 输出表格
    print(f"{'行号':>5}  {'时间':>8}  {'角色':<14}  {'摘要'}")
    print("-" * 120)
    for line_no, ts, role, summary in results:
        print(f"{line_no:>5}  {ts:>8}  {role:<14}  {summary}")

    print(f"\n共 {len(results)} 条记录")


if __name__ == "__main__":
    main()
