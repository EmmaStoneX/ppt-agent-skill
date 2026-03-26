#!/usr/bin/env python3
"""
脚本 10: 根因汇总
综合以上数据输出摘要报告

整合所有维度的分析结果:
  - 基本信息 (格式、行数、时长)
  - Token 消耗概况
  - 错误和异常
  - 工具使用模式
  - 质量问题
  - 降级决策
  - Pipeline 完成度
  - 根因推断

用法: python3 10_summary.py <logfile.jsonl>
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


EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF]+",
    re.UNICODE
)

CSS_VIOLATION_RE = re.compile(r"overflow\s*:\s*(auto|scroll|hidden)|!important|position\s*:\s*(absolute|fixed)", re.IGNORECASE)

DEGRADATION_RE = re.compile(r"跳过|降级|简化|省略|skip|fallback|degrad|simplif|truncat|截断", re.IGNORECASE)


def full_analysis(lines, fmt):
    """综合分析, 返回报告数据"""
    report = {
        "format": "新格式(OpenClaw)" if fmt == "new" else "旧格式(Claude CLI)",
        "total_lines": len(lines),
        "timestamps": [],
        "api_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "max_input_tokens": 0,
        "input_tokens_list": [],
        "stop_reasons": Counter(),
        "tool_calls": Counter(),
        "errors": [],
        "api_errors": 0,
        "compactions": 0,
        "compaction_details": [],
        "emoji_count": 0,
        "css_violations": 0,
        "degradation_hits": 0,
        "large_outputs": 0,
        "pipeline_stages": defaultdict(int),
        "model": "",
    }

    # Pipeline 脚本名
    pipeline_scripts = {
        "web_search": "Step1", "extract_style": "Step3",
        "html2svg": "Step5", "generate_image": "Step5",
        "svg2pptx": "Step6", "html_packager": "Step5"
    }

    for i, raw in enumerate(lines):
        obj = json.loads(raw)
        ts = parse_ts(obj.get("timestamp"))
        if ts:
            report["timestamps"].append(ts)

        if fmt == "new":
            if obj.get("type") == "model_change":
                report["model"] = obj.get("modelId", "")

            elif obj.get("type") == "message":
                msg = obj.get("message", {})
                role = msg.get("role", "")
                usage = msg.get("usage", {})
                stop = msg.get("stopReason", "")
                content = msg.get("content", [])

                if role == "assistant" and usage:
                    inp = usage.get("input", 0)
                    out = usage.get("output", 0)
                    report["api_calls"] += 1
                    report["total_input_tokens"] += inp
                    report["total_output_tokens"] += out
                    report["max_input_tokens"] = max(report["max_input_tokens"], inp)
                    report["input_tokens_list"].append(inp)
                    if stop:
                        report["stop_reasons"][stop] += 1
                    if stop == "error":
                        report["errors"].append({"line": i, "type": "stopReason=error"})
                    if not report["model"]:
                        report["model"] = msg.get("model", "")

                if role == "toolResult" and msg.get("isError"):
                    report["errors"].append({"line": i, "type": "toolResult_error"})

                # 扫描内容
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "toolCall":
                            name = block.get("name", "?")
                            report["tool_calls"][name] += 1
                            args = block.get("arguments", {})
                            if isinstance(args, dict):
                                for v in args.values():
                                    if isinstance(v, str):
                                        for script, stage in pipeline_scripts.items():
                                            if script in v:
                                                report["pipeline_stages"][stage] += 1
                                        if v.endswith(".html"):
                                            report["pipeline_stages"]["Step4"] += 1
                                        if v.endswith(".pptx"):
                                            report["pipeline_stages"]["Step6"] += 1

                        text = block.get("text", "")
                        if text:
                            report["emoji_count"] += len(EMOJI_RE.findall(text))
                            report["css_violations"] += len(CSS_VIOLATION_RE.findall(text))
                            report["degradation_hits"] += len(DEGRADATION_RE.findall(text))

            elif obj.get("type") == "compaction":
                report["compactions"] += 1
                report["compaction_details"].append({
                    "line": i, "tokensBefore": obj.get("tokensBefore", 0)
                })

        else:  # 旧格式
            otype = obj.get("type", "")

            if otype == "assistant":
                msg = obj.get("message", {})
                usage = msg.get("usage", {})
                stop = msg.get("stop_reason", "")
                content = msg.get("content", [])

                if usage:
                    inp = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    report["api_calls"] += 1
                    report["total_input_tokens"] += inp
                    report["total_output_tokens"] += out
                    report["max_input_tokens"] = max(report["max_input_tokens"], inp)
                    report["input_tokens_list"].append(inp)
                    if stop:
                        report["stop_reasons"][stop] += 1
                    if not report["model"]:
                        report["model"] = msg.get("model", "")

                if obj.get("isApiErrorMessage") or obj.get("error"):
                    report["errors"].append({"line": i, "type": "api_error"})

                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            name = block.get("name", "?")
                            report["tool_calls"][name] += 1
                            inp_data = block.get("input", {})
                            if isinstance(inp_data, dict):
                                for v in inp_data.values():
                                    if isinstance(v, str):
                                        for script, stage in pipeline_scripts.items():
                                            if script in v:
                                                report["pipeline_stages"][stage] += 1
                                        if v.endswith(".html"):
                                            report["pipeline_stages"]["Step4"] += 1
                                        if v.endswith(".pptx"):
                                            report["pipeline_stages"]["Step6"] += 1

                        text = block.get("text", "")
                        if text:
                            report["emoji_count"] += len(EMOJI_RE.findall(text))
                            report["css_violations"] += len(CSS_VIOLATION_RE.findall(text))
                            report["degradation_hits"] += len(DEGRADATION_RE.findall(text))

            elif otype == "system":
                sub = obj.get("subtype", "")
                if sub == "api_error":
                    report["api_errors"] += 1
                elif sub == "compact_boundary":
                    report["compactions"] += 1
                    meta = obj.get("compactMetadata", {})
                    report["compaction_details"].append({
                        "line": i, "tokensBefore": meta.get("preTokens", 0)
                    })

    return report


def print_report(r):
    """输出汇总报告"""
    print("=" * 80)
    print("              JSONL 日志根因分析汇总报告")
    print("=" * 80)

    # 1. 基本信息
    print("\n[1] 基本信息")
    print(f"  日志格式:     {r['format']}")
    print(f"  模型:         {r['model']}")
    print(f"  总行数:       {r['total_lines']}")
    if r["timestamps"]:
        start = min(r["timestamps"])
        end = max(r["timestamps"])
        duration = (end - start).total_seconds() / 60
        print(f"  开始时间:     {start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间:     {end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  总时长:       {duration:.1f} 分钟")

    # 2. Token 消耗
    print("\n[2] Token 消耗")
    print(f"  API 调用次数:     {r['api_calls']}")
    print(f"  总输入 tokens:    {r['total_input_tokens']:,}")
    print(f"  总输出 tokens:    {r['total_output_tokens']:,}")
    print(f"  最大输入 tokens:  {r['max_input_tokens']:,}")
    if r["input_tokens_list"]:
        avg = sum(r["input_tokens_list"]) // len(r["input_tokens_list"])
        print(f"  平均输入 tokens:  {avg:,}")
        # 增长趋势
        if len(r["input_tokens_list"]) > 1:
            first_half = r["input_tokens_list"][:len(r["input_tokens_list"])//2]
            second_half = r["input_tokens_list"][len(r["input_tokens_list"])//2:]
            avg1 = sum(first_half) // len(first_half) if first_half else 0
            avg2 = sum(second_half) // len(second_half) if second_half else 0
            trend = "上升" if avg2 > avg1 * 1.2 else "平稳" if avg2 > avg1 * 0.8 else "下降"
            print(f"  上下文趋势:      {trend} (前半均值={avg1:,} 后半均值={avg2:,})")

    # 3. 停止原因
    print("\n[3] 停止原因分布")
    for sr, cnt in r["stop_reasons"].most_common():
        print(f"  {sr}: {cnt}")

    # 4. 错误和异常
    print("\n[4] 错误和异常")
    print(f"  错误总数:     {len(r['errors'])}")
    print(f"  API 错误:     {r['api_errors']}")
    print(f"  Compaction:   {r['compactions']}")
    if r["compaction_details"]:
        for cd in r["compaction_details"]:
            print(f"    行 {cd['line']}: tokensBefore={cd['tokensBefore']:,}")
    if r["errors"]:
        for err in r["errors"][:10]:
            print(f"    行 {err['line']}: {err['type']}")

    # 5. 工具使用
    print("\n[5] 工具使用统计")
    total_tools = sum(r["tool_calls"].values())
    print(f"  总调用次数:   {total_tools}")
    for name, cnt in r["tool_calls"].most_common():
        pct = cnt / total_tools * 100 if total_tools > 0 else 0
        bar = "#" * int(pct / 3)
        print(f"  {name:<20}  {cnt:>4}  ({pct:5.1f}%)  {bar}")

    # 6. 质量问题
    print("\n[6] 质量问题")
    print(f"  Emoji 出现次数:    {r['emoji_count']}")
    print(f"  CSS 违规次数:      {r['css_violations']}")
    print(f"  降级关键词出现:    {r['degradation_hits']}")

    # 7. Pipeline 完成度
    print("\n[7] Pipeline 阶段检测")
    all_stages = ["Step1", "Step2", "Step3", "Step4", "Step5", "Step6"]
    stage_names = {
        "Step1": "研究搜索", "Step2": "大纲生成", "Step3": "风格选择",
        "Step4": "HTML生成", "Step5": "SVG转换", "Step6": "PPTX打包"
    }
    for stage in all_stages:
        cnt = r["pipeline_stages"].get(stage, 0)
        status = "OK" if cnt > 0 else "未检测到"
        print(f"  {stage}({stage_names[stage]}): {status} ({cnt} 次)")

    # 8. 根因推断
    print("\n" + "=" * 80)
    print("[8] 根因推断")
    print("=" * 80)

    issues = []

    # 上下文膨胀
    if r["max_input_tokens"] > 100000:
        issues.append(f"上下文膨胀: 最大 input tokens 达到 {r['max_input_tokens']:,}, 可能导致性能下降或上下文截断")

    # compaction 频繁
    if r["compactions"] > 2:
        issues.append(f"频繁 compaction ({r['compactions']} 次): 说明上下文反复膨胀, 需要优化工具输出大小")

    # 错误率
    if r["api_calls"] > 0:
        err_rate = len(r["errors"]) / r["api_calls"] * 100
        if err_rate > 10:
            issues.append(f"高错误率: {err_rate:.1f}% ({len(r['errors'])}/{r['api_calls']})")

    # API 错误 (重试)
    if r["api_errors"] > 5:
        issues.append(f"大量 API 错误 ({r['api_errors']}): 可能是服务端不稳定或请求过大")

    # CSS 违规
    if r["css_violations"] > 0:
        issues.append(f"CSS 违规 ({r['css_violations']} 次): overflow/position 问题需要在 prompt 中约束")

    # Emoji
    if r["emoji_count"] > 0:
        issues.append(f"Emoji 出现 ({r['emoji_count']} 次): PPT 中不应有 emoji, 需要在 prompt 中禁止")

    # 降级
    if r["degradation_hits"] > 5:
        issues.append(f"频繁降级决策 ({r['degradation_hits']} 次): 可能是任务过于复杂或 prompt 不够清晰")

    # Pipeline 缺失
    missing_stages = [s for s in all_stages if r["pipeline_stages"].get(s, 0) == 0]
    if missing_stages:
        issues.append(f"Pipeline 阶段缺失: {', '.join(missing_stages)} 未被检测到")

    # 工具使用不均衡
    if r["tool_calls"]:
        top_tool, top_count = r["tool_calls"].most_common(1)[0]
        if top_count > total_tools * 0.5:
            issues.append(f"工具使用不均衡: {top_tool} 占 {top_count}/{total_tools} ({top_count/total_tools*100:.0f}%)")

    if issues:
        for j, issue in enumerate(issues, 1):
            print(f"  {j}. {issue}")
    else:
        print("  未发现明显问题")


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <logfile.jsonl>")
        sys.exit(1)

    filepath = sys.argv[1]
    with open(filepath, encoding="utf-8") as f:
        raw_lines = f.readlines()

    fmt = detect_format(raw_lines[0])

    report = full_analysis(raw_lines, fmt)
    print_report(report)


if __name__ == "__main__":
    main()
