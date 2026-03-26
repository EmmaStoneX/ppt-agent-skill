#!/usr/bin/env python3
"""
脚本 9: Pipeline 进度追踪
检测 PPT 生成 Pipeline 每个 Step 的产物文件和执行状态

PPT-Agent Pipeline Steps:
  Step 1: 研究/搜索 (web_search.py)
  Step 2: 大纲生成
  Step 3: 风格选择 (extract_style.py)
  Step 4: HTML 幻灯片生成
  Step 5: SVG/图片转换 (html2svg.py, generate_image.py)
  Step 6: PPTX 打包 (svg2pptx.py)

检测逻辑:
  - 搜索工具调用和文件写入操作
  - 匹配已知的 pipeline 产物文件名模式
  - 追踪 exec/Bash 调用中的脚本执行

用法: python3 09_pipeline.py <logfile.jsonl>
"""
import json
import sys
import re
from datetime import datetime, timezone
from collections import defaultdict


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


# Pipeline 阶段和对应的文件/工具模式
PIPELINE_PATTERNS = {
    "Step1:研究搜索": {
        "tool_patterns": [r"web_search", r"WebSearch", r"search"],
        "file_patterns": [r"research", r"search_result"],
        "script_patterns": [r"web_search\.py"],
    },
    "Step2:大纲生成": {
        "tool_patterns": [],
        "file_patterns": [r"outline", r"大纲", r"structure"],
        "text_patterns": [r"(?:step\s*2|第[二2]步|大纲|outline)", r"slide.*structure"],
    },
    "Step3:风格选择": {
        "tool_patterns": [],
        "file_patterns": [r"style", r"theme", r"风格"],
        "script_patterns": [r"extract_style\.py"],
    },
    "Step4:HTML生成": {
        "tool_patterns": [r"write", r"Write"],
        "file_patterns": [r"slide.*\.html", r"\.html$"],
        "text_patterns": [r"(?:step\s*4|第[四4]步|HTML|幻灯片)"],
    },
    "Step5:SVG转换": {
        "tool_patterns": [],
        "file_patterns": [r"\.svg$", r"\.png$"],
        "script_patterns": [r"html2svg\.py", r"generate_image\.py", r"html_packager\.py"],
    },
    "Step6:PPTX打包": {
        "tool_patterns": [],
        "file_patterns": [r"\.pptx$"],
        "script_patterns": [r"svg2pptx\.py"],
    },
}


def extract_events(lines, fmt):
    """从日志中提取 pipeline 相关事件"""
    events = []

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))
        ts_str = ts.strftime("%H:%M:%S") if ts else "??:??:??"

        if fmt == "new":
            if obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", [])

            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")

                    if btype == "toolCall":
                        name = block.get("name", "")
                        args = block.get("arguments", {})
                        if isinstance(args, dict):
                            # 检查文件路径
                            for k, v in args.items():
                                if isinstance(v, str):
                                    events.append({
                                        "line": i, "time": ts_str,
                                        "action": f"tool:{name}",
                                        "detail": f"{k}={v[:80]}",
                                        "full_text": v
                                    })
                            # 检查命令内容
                            cmd = args.get("command", "") or args.get("content", "")
                            if isinstance(cmd, str) and len(cmd) > 5:
                                events.append({
                                    "line": i, "time": ts_str,
                                    "action": f"cmd:{name}",
                                    "detail": cmd[:100],
                                    "full_text": cmd
                                })

                    elif btype == "text":
                        text = block.get("text", "")
                        if text and role == "assistant":
                            events.append({
                                "line": i, "time": ts_str,
                                "action": "assistant_text",
                                "detail": text[:100].replace("\n", " "),
                                "full_text": text
                            })

        else:  # 旧格式
            otype = obj.get("type", "")
            if otype == "assistant":
                msg = obj.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            if isinstance(inp, dict):
                                for k, v in inp.items():
                                    if isinstance(v, str):
                                        events.append({
                                            "line": i, "time": ts_str,
                                            "action": f"tool:{name}",
                                            "detail": f"{k}={v[:80]}",
                                            "full_text": v
                                        })
                                cmd = inp.get("command", "") or inp.get("content", "")
                                if isinstance(cmd, str) and len(cmd) > 5:
                                    events.append({
                                        "line": i, "time": ts_str,
                                        "action": f"cmd:{name}",
                                        "detail": cmd[:100],
                                        "full_text": cmd
                                    })
                        elif btype == "text":
                            text = block.get("text", "")
                            if text:
                                events.append({
                                    "line": i, "time": ts_str,
                                    "action": "assistant_text",
                                    "detail": text[:100].replace("\n", " "),
                                    "full_text": text
                                })

    return events


def classify_events(events):
    """将事件分类到 pipeline 阶段"""
    stage_events = defaultdict(list)

    for ev in events:
        text = ev["full_text"]
        detail = ev["detail"]

        for stage_name, patterns in PIPELINE_PATTERNS.items():
            matched = False

            # 检查工具模式
            for pat in patterns.get("tool_patterns", []):
                if re.search(pat, ev["action"], re.IGNORECASE):
                    matched = True
                    break

            # 检查文件名模式
            if not matched:
                for pat in patterns.get("file_patterns", []):
                    if re.search(pat, detail, re.IGNORECASE):
                        matched = True
                        break

            # 检查脚本名模式
            if not matched:
                for pat in patterns.get("script_patterns", []):
                    if re.search(pat, text, re.IGNORECASE):
                        matched = True
                        break

            # 检查文本模式
            if not matched:
                for pat in patterns.get("text_patterns", []):
                    if re.search(pat, text[:200], re.IGNORECASE):
                        matched = True
                        break

            if matched:
                stage_events[stage_name].append(ev)

    return stage_events


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

    events = extract_events(raw_lines, fmt)
    print(f"提取事件: {len(events)} 条")

    stage_events = classify_events(events)

    # 输出每个阶段的状态
    print(f"\n{'='*80}")
    print("Pipeline 阶段追踪")
    print(f"{'='*80}")

    for stage_name in PIPELINE_PATTERNS:
        sevents = stage_events.get(stage_name, [])
        status = "DETECTED" if sevents else "NOT FOUND"
        print(f"\n--- {stage_name} [{status}] ({len(sevents)} events) ---")
        if sevents:
            # 时间范围
            times = [e["time"] for e in sevents]
            print(f"  时间范围: {times[0]} - {times[-1]}")
            # 显示关键事件 (前5个)
            for j, ev in enumerate(sevents[:5]):
                print(f"  [{j}] 行{ev['line']:>5}  {ev['time']}  {ev['action']:<20}  {ev['detail'][:60]}")
            if len(sevents) > 5:
                print(f"  ... 还有 {len(sevents)-5} 条")

    # 输出时间线概要
    print(f"\n{'='*80}")
    print("阶段时间线概要")
    print(f"{'='*80}")
    print(f"{'阶段':<20}  {'开始时间':>10}  {'事件数':>6}  {'状态'}")
    print("-" * 60)
    for stage_name in PIPELINE_PATTERNS:
        sevents = stage_events.get(stage_name, [])
        if sevents:
            print(f"{stage_name:<20}  {sevents[0]['time']:>10}  {len(sevents):>6}  OK")
        else:
            print(f"{stage_name:<20}  {'---':>10}  {0:>6}  MISSING")


if __name__ == "__main__":
    main()
