#!/usr/bin/env python3
"""
Gemini 原生生图脚本 — 零额外依赖（仅 urllib + json + base64 + time）

用法：
    # 单张生成
    python generate_image.py --prompt "..." --output path/to/image.png

    # 批量生成（自动串行 + 速率控制 + 失败重试）
    python generate_image.py --batch batch.json --output-dir path/to/images/

    batch.json 格式：
    [
      {"name": "slide_01", "prompt": "..."},
      {"name": "slide_02", "prompt": "..."}
    ]

可选参数：
    --model         模型名（默认从 .env 读取）
    --retry N       失败重试次数（默认 2）
    --interval S    请求间隔秒数（默认 8）

环境变量（从 .env 读取）：
    IMAGE_API_KEY   — API Key（必须）
    IMAGE_API_BASE  — 中转站地址，默认 https://api.zxvmax.com
    IMAGE_MODEL     — 模型名，默认 gemini-3.1-flash-image-preview
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error


def load_dotenv(path=None):
    """从 .env 文件加载环境变量（不覆盖已有值）"""
    if path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, ".env"),
            os.path.join(os.path.dirname(script_dir), ".env"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                path = c
                break
    if path is None or not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def _call_api(url: str, api_key: str, prompt: str, timeout: int = 150) -> bytes:
    """发送 API 请求，返回图片 bytes。失败抛异常。"""
    payload = {
        "contents": [
            {"parts": [{"text": f"Generate an image: {prompt}"}]}
        ],
        "generationConfig": {
            "responseModalities": ["image", "text"],
            "imageSize": "1K",
            "aspectRatio": "16:9",
        },
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])

    raise ValueError(f"No image in response: {json.dumps(data, ensure_ascii=False)[:300]}")


def generate_image(
    prompt: str,
    output_path: str,
    model: str | None = None,
    max_retries: int = 2,
    retry_base_delay: float = 15.0,
) -> bool:
    """生成单张图片，带重试。返回 True 成功 / False 失败。"""
    api_key = os.environ.get("IMAGE_API_KEY", "")
    api_base = os.environ.get("IMAGE_API_BASE", "https://api.zxvmax.com").rstrip("/")
    model = model or os.environ.get("IMAGE_MODEL", "gemini-3.1-flash-image-preview")

    if not api_key:
        print("ERROR: IMAGE_API_KEY not set.", file=sys.stderr)
        return False

    url = f"{api_base}/v1beta/models/{model}:generateContent"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    for attempt in range(1 + max_retries):
        try:
            image_bytes = _call_api(url, api_key, prompt)
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            print(f"OK: {output_path}")
            return True

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            is_quota = e.code == 429 or "exhausted" in error_body.lower() or "quota" in error_body.lower()
            if attempt < max_retries and (is_quota or e.code >= 500):
                delay = retry_base_delay * (2 ** attempt)
                print(f"RETRY {attempt + 1}/{max_retries}: HTTP {e.code}, wait {delay:.0f}s...", file=sys.stderr)
                time.sleep(delay)
            else:
                print(f"ERROR: HTTP {e.code}\n{error_body[:200]}", file=sys.stderr)
                return False

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries:
                delay = retry_base_delay * (2 ** attempt)
                print(f"RETRY {attempt + 1}/{max_retries}: {e}, wait {delay:.0f}s...", file=sys.stderr)
                time.sleep(delay)
            else:
                print(f"ERROR: {e}", file=sys.stderr)
                return False

        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return False

    return False


def batch_generate(
    batch_file: str,
    output_dir: str,
    model: str | None = None,
    max_retries: int = 2,
    interval: float = 8.0,
) -> dict:
    """批量串行生成，返回 {"ok": [...], "failed": [...]}。"""
    with open(batch_file, encoding="utf-8") as f:
        items = json.load(f)

    os.makedirs(output_dir, exist_ok=True)
    results = {"ok": [], "failed": []}

    for i, item in enumerate(items):
        name = item["name"]
        prompt = item["prompt"]
        output_path = os.path.join(output_dir, f"{name}.png")

        if i > 0:
            print(f"  (wait {interval:.0f}s for rate limit)", file=sys.stderr)
            time.sleep(interval)

        print(f"[{i + 1}/{len(items)}] {name}...", file=sys.stderr)
        ok = generate_image(prompt, output_path, model=model, max_retries=max_retries)
        if ok:
            results["ok"].append(name)
        else:
            results["failed"].append(name)

    print(f"\nDone: {len(results['ok'])} ok, {len(results['failed'])} failed", file=sys.stderr)
    if results["failed"]:
        print(f"Failed: {', '.join(results['failed'])}", file=sys.stderr)
    # 输出 JSON 到 stdout 供调用方解析
    print(json.dumps(results, ensure_ascii=False))
    return results


def main():
    parser = argparse.ArgumentParser(description="Gemini 原生图片生成")
    # 单张模式
    parser.add_argument("--prompt", help="图片生成提示词（单张模式）")
    parser.add_argument("--output", help="输出 PNG 路径（单张模式）")
    # 批量模式
    parser.add_argument("--batch", help="批量任务 JSON 文件路径")
    parser.add_argument("--output-dir", help="批量输出目录")
    # 通用
    parser.add_argument("--model", default=None, help="模型名（默认从 .env 读取）")
    parser.add_argument("--retry", type=int, default=2, help="失败重试次数（默认 2）")
    parser.add_argument("--interval", type=float, default=8, help="批量模式请求间隔秒数（默认 8）")
    args = parser.parse_args()

    load_dotenv()

    if args.batch:
        if not args.output_dir:
            parser.error("--batch requires --output-dir")
        result = batch_generate(
            args.batch, args.output_dir,
            model=args.model, max_retries=args.retry, interval=args.interval,
        )
        sys.exit(0 if not result["failed"] else 1)
    elif args.prompt and args.output:
        ok = generate_image(args.prompt, args.output, model=args.model, max_retries=args.retry)
        sys.exit(0 if ok else 1)
    else:
        parser.error("需要 --prompt + --output（单张）或 --batch + --output-dir（批量）")


if __name__ == "__main__":
    main()
