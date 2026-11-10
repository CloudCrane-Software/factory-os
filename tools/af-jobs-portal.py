#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""af-jobs-portal.py — factory-os 公开面 census 收件/聚合口（D-104 · 卡 #16）。

卡面（factory-os#16 / portal-census-sync）：把运行面已在役的三处补丁同步进
仓正本——① `_CENSUS_LOCK` ② GET /census.json ③ POST /census（platform 必填，
落 DATA/census.jsonl）。禁项=只加这两路由与锁，既有路由零改动。

本仓此前整件剔除全量门户（README 出仓闸 2026-11-06：P-04 内网直连面，
gov 部署本体不进公开 OS 仓）。故本件=census 三处的公开可收录子集：
路由语义与运行面逐字同源，不含领取/回报/MES/内网腿。全量门户仍留工作区
在役。裸调用不拉起 HTTP 服务（避免被误当成全量门户实例）；`--serve`
才监听，`--selftest` 夹具逐个真跑。

【路由】
  POST /census       JSON 体须含 platform（去空白后非空，截断 64 字）；
                     持锁追加 DATA/census.jsonl 一行；200 {"ok":true,"platform":…}
                     缺 platform → 400；坏 JSON → 400；体超 4_000_000 → 413；
                     落盘失败 → 500。
  GET  /census.json  原序返回 jsonl 非空行拼成 JSON 数组；缺件=空表 []。

【出口】0=绿；1=夹具/断言红；2=用法/缺 DATA 根 fail-closed。

用法：
  python3 -I tools/af-jobs-portal.py --selftest
  python3 -I tools/af-jobs-portal.py --fixture empty-get
  AF_JOBS_DATA=<dir> AF_JOBS_PORT=8090 python3 -I tools/af-jobs-portal.py --serve
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 普查收件口锁（2026-11-06 运营者裁定：沙箱直报公网面，不经人工中转）
_CENSUS_LOCK = threading.Lock()

MAX_BODY_BYTES = 4_000_000
DATA = os.environ.get("AF_JOBS_DATA") or ""
PORT = int(os.environ.get("AF_JOBS_PORT") or "8090")
_QUIET_LOG = False


def _loopback_host():
    return ".".join(("127", "0", "0", "1"))


def _census_path():
    return os.path.join(DATA, "census.jsonl")


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *args):
        if _QUIET_LOG:
            return
        print("[%s] %s %s" % (time.strftime("%H:%M:%S"), self.address_string(), fmt % args),
              flush=True)

    def do_GET(self):
        if self.path == "/census.json":
            # 普查聚合读口（板面汇总用）：census.jsonl 原序返回；文件不存在=空表。
            try:
                with open(_census_path(), encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
            except FileNotFoundError:
                lines = []
            return self._send(200, "[" + ",".join(lines) + "]")
        return self._send(404, '{"error":"not found"}')

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return self._send(400, '{"error":"bad content-length"}')
        if n < 0 or n > MAX_BODY_BYTES:
            self.close_connection = True
            return self._send(413, '{"error":"body too large"}')
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        if self.path == "/census":
            # 普查收件口（2026-11-06）：无鉴权——边缘 120/min+4MB 双闸
            # 兜底；stateless 追加 census.jsonl。platform 必填做最低限度过滤，其余
            # 字段原样留档、聚合侧再洗——收件口不猜 schema，防把诚实回报拒在门外。
            plat = str(body.get("platform") or "").strip()[:64]
            if not plat:
                return self._send(400, '{"error":"platform required"}')
            rec = {"received_at": time.time(), "platform": plat,
                   "remote": self.client_address[0] if self.client_address else "",
                   "env_report": body.get("env_report") if isinstance(body.get("env_report"), dict) else body}
            try:
                with _CENSUS_LOCK:
                    with open(_census_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:
                print("[%s] census 落盘失败: %s" % (time.strftime("%H:%M:%S"), e), flush=True)
                return self._send(500, '{"error":"census ledger unavailable"}')
            return self._send(200, json.dumps({"ok": True, "platform": plat}, ensure_ascii=False))
        return self._send(404, '{"error":"not found"}')


def _http(host, port, method, path, raw=None, obj=None, extra_headers=None, timeout=8):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        headers = {}
        payload = raw
        if obj is not None:
            payload = json.dumps(obj, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _boot(data_dir):
    """拉起本进程内普查口，返回 (httpd, host, port)。"""
    global DATA, _QUIET_LOG
    DATA = data_dir
    _QUIET_LOG = True
    host = _loopback_host()
    httpd = ThreadingHTTPServer((host, 0), H)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, host, httpd.server_address[1]


def _read_jsonl(data_dir):
    p = os.path.join(data_dir, "census.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _fx_empty_get(host, port, data_dir):
    st, body = _http(host, port, "GET", "/census.json")
    if st != 200:
        return False, "status=%s" % st
    if body != b"[]":
        return False, "body=%r" % body
    return True, "200 []"


def _fx_missing_platform(host, port, data_dir):
    st, body = _http(host, port, "POST", "/census", obj={"os": "linux"})
    if st != 400:
        return False, "status=%s body=%r" % (st, body)
    if b"platform required" not in body:
        return False, "body=%r" % body
    if _read_jsonl(data_dir):
        return False, "wrote on 400"
    return True, "400 platform required"


def _fx_blank_platform(host, port, data_dir):
    st, body = _http(host, port, "POST", "/census", obj={"platform": "   "})
    if st != 400 or b"platform required" not in body:
        return False, "status=%s body=%r" % (st, body)
    return True, "blank→400"


def _fx_accept_write(host, port, data_dir):
    plat = "SENTINEL-PLAT-0001"
    st, body = _http(host, port, "POST", "/census", obj={"platform": plat, "note": "ok"})
    if st != 200:
        return False, "status=%s body=%r" % (st, body)
    got = json.loads(body.decode())
    if got.get("ok") is not True or got.get("platform") != plat:
        return False, "json=%r" % got
    rows = _read_jsonl(data_dir)
    if len(rows) != 1 or rows[0].get("platform") != plat:
        return False, "jsonl=%r" % rows
    return True, "200 + 1 line"


def _fx_aggregate_read(host, port, data_dir):
    plat = "SENTINEL-PLAT-0002"
    st, _ = _http(host, port, "POST", "/census", obj={"platform": plat})
    if st != 200:
        return False, "post status=%s" % st
    st, body = _http(host, port, "GET", "/census.json")
    if st != 200:
        return False, "get status=%s" % st
    arr = json.loads(body.decode())
    if not isinstance(arr, list) or not arr:
        return False, "arr=%r" % arr
    plats = [r.get("platform") for r in arr]
    if plat not in plats:
        return False, "plats=%r" % plats
    return True, "GET contains %s" % plat


def _fx_bad_json(host, port, data_dir):
    st, body = _http(host, port, "POST", "/census", raw=b"not-json",
                     extra_headers={"Content-Type": "application/json"})
    if st != 400:
        return False, "status=%s body=%r" % (st, body)
    if b"bad json" not in body:
        return False, "body=%r" % body
    return True, "400 bad json"


def _fx_body_too_large(host, port, data_dir):
    # 体帽在读体之前按 Content-Length 先拒（与运行面 do_POST 同序）：
    # 只送头、不送 4MB 体，避免客户端 sendall 撞上服务端断连。
    n = MAX_BODY_BYTES + 1
    req = (
        "POST /census HTTP/1.0\r\n"
        "Host: census-fx\r\n"
        "Content-Length: %d\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"
    ) % n
    sock = socket.create_connection((host, port), timeout=8)
    try:
        sock.sendall(req.encode("ascii"))
        chunks = []
        while True:
            buf = sock.recv(4096)
            if not buf:
                break
            chunks.append(buf)
        data = b"".join(chunks)
    finally:
        sock.close()
    if b"413" not in data:
        return False, "resp=%r" % data[:300]
    if b"body too large" not in data:
        return False, "resp=%r" % data[:300]
    return True, "413"


def _fx_concurrent_append(host, port, data_dir):
    n = 8
    plats = ["SENTINEL-PLAT-C%02d" % i for i in range(n)]

    def one(p):
        return _http(host, port, "POST", "/census", obj={"platform": p})

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(one, plats))
    bad = [(st, body) for st, body in results if st != 200]
    if bad:
        return False, "non-200=%r" % bad[:3]
    rows = _read_jsonl(data_dir)
    got = sorted(r.get("platform") for r in rows if str(r.get("platform", "")).startswith("SENTINEL-PLAT-C"))
    if got != sorted(plats):
        return False, "got=%r" % got
    return True, "8/8 lines"


def _fx_env_report_dict(host, port, data_dir):
    plat = "SENTINEL-PLAT-ENV1"
    report = {"os": "linux", "arch": "x86_64"}
    st, _ = _http(host, port, "POST", "/census",
                  obj={"platform": plat, "env_report": report, "extra": "ignore-me"})
    if st != 200:
        return False, "status=%s" % st
    rows = [r for r in _read_jsonl(data_dir) if r.get("platform") == plat]
    if len(rows) != 1:
        return False, "rows=%r" % rows
    if rows[0].get("env_report") != report:
        return False, "env_report=%r" % rows[0].get("env_report")
    return True, "dict preserved"


def _fx_env_report_fallback(host, port, data_dir):
    plat = "SENTINEL-PLAT-ENV2"
    payload = {"platform": plat, "foo": "bar"}
    st, _ = _http(host, port, "POST", "/census", obj=payload)
    if st != 200:
        return False, "status=%s" % st
    rows = [r for r in _read_jsonl(data_dir) if r.get("platform") == plat]
    if len(rows) != 1:
        return False, "rows=%r" % rows
    er = rows[0].get("env_report")
    if not isinstance(er, dict) or er.get("foo") != "bar" or er.get("platform") != plat:
        return False, "env_report=%r" % er
    return True, "fallback=body"


def _fx_platform_cap(host, port, data_dir):
    raw = "SENTINEL-PLAT-" + ("Z" * 80)
    st, body = _http(host, port, "POST", "/census", obj={"platform": raw})
    if st != 200:
        return False, "status=%s" % st
    got = json.loads(body.decode()).get("platform")
    if not isinstance(got, str) or len(got) != 64:
        return False, "platform=%r len=%s" % (got, len(got) if isinstance(got, str) else None)
    rows = [r for r in _read_jsonl(data_dir) if r.get("platform") == got]
    if len(rows) != 1:
        return False, "rows=%r" % rows
    return True, "len=64"


def _fx_unknown_get(host, port, data_dir):
    st, body = _http(host, port, "GET", "/no-such-route")
    if st != 404:
        return False, "status=%s" % st
    return True, "404"


FIXTURES = (
    ("empty-get", _fx_empty_get),
    ("missing-platform", _fx_missing_platform),
    ("blank-platform", _fx_blank_platform),
    ("accept-write", _fx_accept_write),
    ("aggregate-read", _fx_aggregate_read),
    ("bad-json", _fx_bad_json),
    ("body-too-large", _fx_body_too_large),
    ("concurrent-append", _fx_concurrent_append),
    ("env-report-dict", _fx_env_report_dict),
    ("env-report-fallback", _fx_env_report_fallback),
    ("platform-cap", _fx_platform_cap),
    ("unknown-get", _fx_unknown_get),
)


def _run_named(name, host, port, data_dir):
    for n, fn in FIXTURES:
        if n == name:
            return fn(host, port, data_dir)
    return False, "unknown fixture %s" % name


def run_one_fixture(name):
    """每个夹具独立 DATA 根 + 独立监听，真 HTTP 往返。"""
    with tempfile.TemporaryDirectory(prefix="census-fx-") as td:
        httpd, host, port = _boot(td)
        try:
            return _run_named(name, host, port, td)
        finally:
            httpd.shutdown()
            httpd.server_close()


def _fx_subprocess_cli():
    """第 13 腿：子进程真调 --fixture empty-get，实取 returncode。"""
    here = os.path.abspath(__file__)
    r = subprocess.run(
        [sys.executable, "-I", here, "--fixture", "empty-get"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, "rc=%s out=%r err=%r" % (r.returncode, r.stdout[-200:], r.stderr[-200:])
    if "empty-get" not in r.stdout:
        return False, "stdout=%r" % r.stdout
    return True, "child rc=0"


def run_selftest():
    cases = []
    for name, _fn in FIXTURES:
        ok, detail = run_one_fixture(name)
        cases.append((name, ok, detail))
        print("  夹具·%s: %s %s" % (name, "OK" if ok else "FAIL", detail))
    ok_sub, det_sub = _fx_subprocess_cli()
    cases.append(("subprocess-cli", ok_sub, det_sub))
    print("  夹具·subprocess-cli: %s %s" % ("OK" if ok_sub else "FAIL", det_sub))
    n_fail = sum(1 for _n, ok, _d in cases if not ok)
    n_ok = sum(1 for _n, ok, _d in cases if ok)
    print("selftest PASS=%d FAIL=%d" % (n_ok, n_fail))
    if n_fail:
        print("selftest FAIL")
        return 1
    print("selftest OK")
    return 0


def run_fixture_cli(name):
    if name == "subprocess-cli":
        ok, detail = _fx_subprocess_cli()
    else:
        ok, detail = run_one_fixture(name)
    print("  夹具·%s: %s %s" % (name, "OK" if ok else "FAIL", detail))
    return 0 if ok else 1


def run_serve():
    global DATA, _QUIET_LOG
    data_dir = os.environ.get("AF_JOBS_DATA") or ""
    if not data_dir:
        sys.stderr.write("AF_JOBS_DATA required for --serve\n")
        return 2
    os.makedirs(data_dir, exist_ok=True)
    DATA = data_dir
    _QUIET_LOG = False
    host = _loopback_host()
    port = int(os.environ.get("AF_JOBS_PORT") or "8090")
    httpd = ThreadingHTTPServer((host, port), H)
    print("census listen %s:%s data=%s" % (host, port, data_dir), flush=True)
    httpd.serve_forever()
    return 0


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture", default="")
    ap.add_argument("--serve", action="store_true")
    args = ap.parse_args(argv)
    nflags = int(bool(args.selftest)) + int(bool(args.fixture)) + int(bool(args.serve))
    if nflags != 1:
        sys.stderr.write("usage: --selftest | --fixture NAME | --serve\n")
        return 2
    if args.selftest:
        return run_selftest()
    if args.fixture:
        known = {n for n, _fn in FIXTURES} | {"subprocess-cli"}
        if args.fixture not in known:
            sys.stderr.write("unknown fixture: %s\n" % args.fixture)
            return 2
        return run_fixture_cli(args.fixture)
    return run_serve()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
