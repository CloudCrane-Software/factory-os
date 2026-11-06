#!/usr/bin/env python3
"""bearer-proxy.py — MiniMax mavis 的 Bearer 适配边车。

任何 anthropic-SDK 客户端（x-api-key 形态）→ 本边车 → mavis（Bearer OAuth）。
边车顺带承担 token 续期（每请求经 mcode-token.py get，剩 <10 分钟自动刷新）。

用法:
  ssh -L 8377:127.0.0.1:8377 anolis -N   # 或直接在 anolis 本机跑
  python3 bearer-proxy.py [--port 8377]
  客户端: ANTHROPIC_BASE_URL=http://127.0.0.1:8377 ANTHROPIC_API_KEY=任意非空
"""
import argparse
import http.server
import json
import subprocess
import time
import urllib.request

UPSTREAM = "https://agent.minimaxi.com/mavis/api/v1/llm"
TOKEN_CMD = ["python3", "/home/pan-ding/.local/bin/mcode-token.py", "get"]
USAGE_LOG = "/data/bench/sidecar-usage.jsonl"


def log_usage(path: str, payload: bytes):
    try:
        row = json.loads(payload)
    except Exception:
        return
    usage = row.get("usage")
    if not usage:
        return
    record = {
        "ts": int(time.time()),
        "path": path,
        "model": row.get("model"),
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
    }
    try:
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def current_token() -> str:
    return subprocess.run(TOKEN_CMD, capture_output=True, check=True, text=True).stdout.strip()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self, method: str):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=body,
            method=method,
            headers={
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Accept": self.headers.get("Accept", "application/json"),
                "User-Agent": "MiniMaxCode",
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                "Authorization": "Bearer " + current_token(),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = resp.read()
                status = resp.status
                ctype = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            payload = e.read()
            status = e.code
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        if status < 300 and self.path.endswith("/messages"):
            log_usage(self.path, payload)

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8377)
    args = parser.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"bearer-proxy on 127.0.0.1:{args.port} → {UPSTREAM}")
    server.serve_forever()


if __name__ == "__main__":
    main()
