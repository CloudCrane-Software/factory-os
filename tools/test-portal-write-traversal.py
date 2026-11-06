#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-portal-write-traversal.py — af-jobs 门户**写分支**路径穿越回归门（RT-E79）

背景（逃逸台账 RT-E79「/claim 的 task_id 无段校验（仅 isdir）」，红队 2026-11-01
本地隔离实测；逃逸拦截-60.md:181「四攻击形态对在役件的受控重放零实现」；
欠账处置-20261103.md:67 RT-E79 行「沙盒隔离重放四攻击 POST 留证或常驻测试件」）：
  · 同一文件里读分支（/task/<id>/<file>.md）早已上双保险，**写分支漏网**（模式③
    同型漏洞同文件修一漏一）：/claim 原先只 `os.path.isdir(os.path.join(DATA,
    "tasks", tid))` 裸拼 ⇒ "../static" / "../reports" / "../../../tmp" / ".." 全是
    已存在目录，皆可领成「伪任务」；
  · 危害三面：①claims.json 落越权键；②/report 落盘文件名直接拼 tid ⇒ 逃出
    reports/ 写容器 FS 多层（../static → DATA 根；../../../tmp → 容器根）；
    ③MES 记幽灵账（work_order_id=af-jobs-..）。
  · 修复已落（登记员 2026-11-02 亲读）：af-jobs-portal.py:355-370 `_task_dir_path`
    （单段正则 + realpath 前缀双保险）；/claim 入口 af-jobs-portal.py:916-920
    （非法 tid → 404「unknown task」，不泄露存在性）；/report 落盘前
    af-jobs-portal.py:987-992（claims.json 残留越权键 → 401，零落盘）。
  · **残余**：台账修复对账栏自认「四条攻击 POST 未重放（生产零触碰纪律）」——
    修复正确性零证据；且既有常驻门 tools/test-portal-attack-surface.py 的穿越面
    只打**读分支**（/task/ 与 /static/ 共 12 变体，:146-177），**写分支零覆盖**
    → 写分支守卫被摘/被改写时全门照绿。

本件 = 写分支四攻击的沙盒重放常驻门：
  · 同一份判据代码跑**两个**门户实例——在役正本 tools/af-jobs-portal.py 与**修复前**
    带洞副本 tools/af-jobs-portal.py.20261031-pre-RT.bak（md5=0482fb7e3dbc28fbb789e9fdc794e2c4
    ≡ 逃逸台账 RT-E113 记的「10-30 pre-RT 带洞版」= 当时公网在役的那一份），
    断言集完全相同 ⇒ 判别力自证（红路/绿路双臂）内建，不必另开 selftest 件。
  · 判据**黑盒**：只看 HTTP 状态码 / 落盘位置 / 账本键集 / MES 行数，
    不 import 门户源码（门与被测件同源会恒绿）。
  · **零生产触碰**：门户实例起在临时沙箱里（AF_JOBS_DATA 指向沙箱 DATA），
    逃逸落点也刻意布置在沙箱内（S/tmp），零写生产面、零打公网入口。

判据（每一腿都是可观测后果；任一不过 = 红）：
  W1 四攻击 /claim 一律 404（非法 tid 按未知任务拒收）——A1 ../static /
     A2 ../reports / A3 ../../../tmp / A4 ..
  W2 账本零越权键：claims.json 的键集 ⊆ 合法任务集（无 ../static、../reports、
     ../../../tmp、.. 键）
  W3 MES 零幽灵账：mes-events.jsonl 中 task_id 无越权串（零行幽灵记账）
  W4 零落盘逃逸：沙箱内除 DATA/{tasks,reports}/ 与三个已知账本件外零新增文件
     （逃逸落点 DATA 根 static-<ts>.json、S/tmp-<ts>.json 皆为零）
  W5 /report 污染账本腿：claims.json 预置越权 tid 的 token → /report 必 401 且零落盘
  P  正例对照：合法任务 /claim → 200（防「全 404 = 服务死了」假绿）

用法：python3 -I tools/test-portal-write-traversal.py [--selftest]
  （无参 = 跑在役正本一件，须全绿 exit 0；--selftest = 只跑判别力双臂：
   修复前副本必判红、正本必判绿，任一不成立即红）
退出码：0 全过；1 断言失败（红）；2 环境错误（门户实例起不来/沙箱不可写/负控件缺件）。
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from http.client import HTTPConnection

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WS, "tools")
PORTAL = os.path.join(TOOLS, "af-jobs-portal.py")
# 负控件＝修复前带洞副本（md5=0482fb7e… ≡ 逃逸台账 RT-E113 记的「10-30 pre-RT
# 带洞版」＝当时公网在役的那一份；该副本无 _task_dir_path ⇒ 写分支无守卫）。
OLD_PORTAL = os.path.join(TOOLS, "af-jobs-portal.py.20261031-pre-RT.bak")
OLD_PORTAL_MD5 = "0482fb7e3dbc28fbb789e9fdc794e2c4"

CANARY = "CANARY-%s-绝密件-SECRET" % uuid.uuid4().hex[:12]

# 四攻击（逃逸台账 RT-E79 证据栏原文，2026-11-01 红队本地隔离实测）
ATTACKS = ["../static", "../reports", "../../../tmp", ".."]
LEGIT_TASK = "t-rt79-ok"

# 沙箱内允许存在的文件（相对沙箱根 S）：DATA 树的公开两棵 + 三个账本/预置件。
# 任何不在此集合内的文件 = 落盘逃逸（W4 红）。
ALLOWED_RELPATHS = {
    "inner/data/claims.json",
    "inner/data/mes-events.jsonl",
    "inner/data/secret-canary.md",
    "inner/data/static/index.html",
}
ALLOWED_PREFIXES = ("inner/data/tasks/", "inner/data/reports/")


class Client:
    """HTTP 客户端（写分支用 POST JSON；路径/体逐字上送）。"""

    def __init__(self, port, timeout=20):
        self.port = port
        self.timeout = timeout

    def post(self, path, obj):
        c = HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            c.request("POST", path, body=json.dumps(obj),
                      headers={"Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def get(self, path):
        c = HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            c.request("GET", path)
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def seed_sandbox(root):
    """铺沙箱 DATA 树：
      S/inner/data/tasks/<合法任务>/{AGENTS.md,problem.md,meta.json}
      S/inner/data/static/index.html          （A1 的逃逸目标必须「存在」）
      S/inner/data/reports/                   （A2 的逃逸目标必须「存在」）
      S/inner/data/secret-canary.md           （DATA 根机密件：越权读/写即红）
      S/tmp/                                  （A3 的逃逸落点：仍在沙箱内，零生产面）
    逃逸目标必须真实存在——修复前版本只做 isdir 检查，目标不存在时它也会 404，
    那样负控件就「因环境巧合」而不复现漏洞（判别力失真）。
    """
    data = os.path.join(root, "inner", "data")
    tdir = os.path.join(data, "tasks", LEGIT_TASK)
    os.makedirs(tdir, exist_ok=True)
    open(os.path.join(tdir, "AGENTS.md"), "w").write(f"# 任务 {LEGIT_TASK} 契约\n")
    open(os.path.join(tdir, "problem.md"), "w").write(f"# 任务 {LEGIT_TASK} 任务书\n")
    json.dump({"title": LEGIT_TASK, "type": "rt79-gate", "est_load": 1, "reward": 0},
              open(os.path.join(tdir, "meta.json"), "w"))
    os.makedirs(os.path.join(data, "static"), exist_ok=True)
    open(os.path.join(data, "static", "index.html"), "w").write("<html>static-ok</html>")
    os.makedirs(os.path.join(data, "reports"), exist_ok=True)
    open(os.path.join(data, "secret-canary.md"), "w").write(CANARY + "\n")
    os.makedirs(os.path.join(root, "tmp"), exist_ok=True)
    return data


def spawn_portal(script, data_dir, cwd):
    """起隔离实例（沙箱 DATA + 随机端口）。返回 (proc, port)。"""
    port = _free_port()
    env = os.environ.copy()
    env["AF_JOBS_DATA"] = data_dir
    env["AF_JOBS_PORT"] = str(port)
    env.pop("AF_JOBS_RATE_LIMIT_PER_MIN", None)
    env.pop("AF_JOBS_TRUSTED_PROXY_IPS", None)
    p = subprocess.Popen([sys.executable, script], cwd=cwd, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cl = Client(port, timeout=5)
    for _ in range(100):
        if p.poll() is not None:
            raise RuntimeError(f"门户实例退出 rc={p.returncode}（脚本 {script}）")
        try:
            st, _b = cl.get("/healthz")
            if st == 200:
                return p, port
        except OSError:
            pass
        time.sleep(0.1)
    p.kill()
    raise RuntimeError(f"门户实例 10s 内未就绪（脚本 {script}）")


def _scan_sandbox(root):
    """列出沙箱内全部文件（相对 S）。"""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def _claims(data_dir):
    p = os.path.join(data_dir, "claims.json")
    try:
        with open(p) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {"__unreadable__": True}


def _mes_rows(data_dir):
    p = os.path.join(data_dir, "mes-events.jsonl")
    rows = []
    if not os.path.isfile(p):
        return rows
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append({"task_id": "__unparsable__"})
    return rows


def run_replay(script, label):
    """在隔离实例上重放四攻击 + 污染账本回报腿。返回 (ok, detail, fails)。"""
    fails = []
    root = tempfile.mkdtemp(prefix="rt79-sandbox-")
    proc = None
    try:
        data = seed_sandbox(root)
        proc, port = spawn_portal(script, data, root)
        cl = Client(port)

        # --- W1 四攻击 /claim 必须 404 ---
        bad = []
        for tid in ATTACKS:
            st, body = cl.post("/claim", {"task_id": tid, "sandbox": "rt79-gate"})
            if st != 404:
                bad.append(f"{tid!r} → {st}（应 404）")
        if bad:
            fails.append("W1 写分支领取面红：" + "；".join(bad))

        # --- W2 账本零越权键 ---
        c = _claims(data)
        if isinstance(c, dict) and c.get("__unreadable__"):
            fails.append("W2 不可证：claims.json 不可解析")
        else:
            escaped = sorted(k for k in c if k in ATTACKS)
            if escaped:
                fails.append(f"W2 账本越权键红：claims.json 出现越权键 {escaped}")

        # --- W3 MES 零幽灵账 ---
        ghosts = [r.get("task_id") for r in _mes_rows(data)
                  if r.get("task_id") in ATTACKS]
        if ghosts:
            fails.append(f"W3 MES 幽灵记账红：{ghosts}")

        # --- W4 零落盘逃逸 ---
        stray = [rel for rel in _scan_sandbox(root)
                 if rel not in ALLOWED_RELPATHS and not rel.startswith(ALLOWED_PREFIXES)]
        if stray:
            fails.append(f"W4 落盘逃逸红：沙箱内越界文件 {stray}")

        # --- W5 /report 污染账本腿（越权 tid 的 token → 必 401 且零落盘） ---
        c = _claims(data)
        if isinstance(c, dict) and not c.get("__unreadable__"):
            c["../static"] = {"claim_token": "RT79-POISON-TOKEN", "claimed_at": time.time(),
                              "last_heartbeat": time.time(),
                              "expires_at": time.time() + 7200, "sandbox": "poison"}
            with open(os.path.join(data, "claims.json"), "w") as f:
                json.dump(c, f, indent=1)
            before = set(_scan_sandbox(root))
            st, body = cl.post("/report", {"claim_token": "RT79-POISON-TOKEN",
                                           "payload": {"atoms": [{"id": "a1", "text": "x",
                                                                 "source": {"quote": "q"}}]}})
            after = set(_scan_sandbox(root))
            newfiles = sorted(after - before)
            if st != 401:
                fails.append(f"W5 污染账本回报腿红：越权 token /report → {st}（应 401）")
            if newfiles:
                fails.append(f"W5 污染账本回报腿红：越权 token 落盘 {newfiles}")

        # --- P 正例对照：合法任务可领（防「全 404＝服务死了」假绿） ---
        st, body = cl.post("/claim", {"task_id": LEGIT_TASK, "sandbox": "rt79-gate"})
        if st != 200:
            fails.append(f"P 正例对照红：合法任务 /claim → {st}（应 200；门户未正常服务）")
        else:
            try:
                json.loads(body)["claim_token"]
            except Exception:
                fails.append("P 正例对照红：合法任务 /claim 响应无 claim_token")

        detail = ("四攻击全 404、账本零越权键、MES 零幽灵账、零落盘逃逸、"
                  "污染账本 /report 401 零落盘、合法任务 200" if not fails
                  else "；".join(fails))
        return (not fails), f"{label}：{detail}", fails
    finally:
        if proc is not None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)


def selftest():
    """判别力双臂：修复前带洞副本必判红（门有判别力）、在役正本必判绿。"""
    print("=== RT-E79 写分支门 · 判别力自证（双臂）===")
    fails = []
    if not os.path.isfile(OLD_PORTAL):
        print(f"[RED] 负控件缺件：{OLD_PORTAL} 不在位——修复前带洞副本缺失，"
              f"判别力不可证（fail-closed，不猜绿）")
        return 1
    ok_old, det_old, _ = run_replay(OLD_PORTAL, f"修复前副本（md5={OLD_PORTAL_MD5}）")
    if ok_old:
        fails.append(f"判别力失真：修复前副本对四攻击竟全绿（{det_old}）——"
                     f"本门对「写分支无守卫」零判别力（恒绿真空门）")
        print(f"  [FAIL] 红路（修复前副本应判红）：{det_old}")
    else:
        print(f"  [OK]   红路：修复前副本被判红 —— {det_old[:300]}")
    ok_new, det_new, _ = run_replay(PORTAL, "在役正本")
    if not ok_new:
        fails.append(f"绿路红：在役正本对四攻击判红（{det_new}）——门被改成「恒红」")
        print(f"  [FAIL] 绿路（在役正本应判绿）：{det_new[:300]}")
    else:
        print(f"  [OK]   绿路：在役正本判绿 —— {det_new[:300]}")
    if fails:
        for f in fails:
            print(f"[RED] {f}")
        return 1
    print("小计：PASS=2 FAIL=0（红路必红 + 绿路必绿）")
    return 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        rc = selftest()
        return rc
    ok, detail, fails = run_replay(PORTAL, "在役正本")
    if ok:
        print(f"[PASS] RT-E79 写分支穿越门绿：{detail}")
        print("小计：PASS=1 FAIL=0")
        return 0
    print(f"[FAIL] RT-E79 写分支穿越门红：{detail}")
    print("小计：PASS=0 FAIL=1")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 —— 环境异常一律红（不可证不猜绿）
        print(f"[RED rc=2] 门件执行异常：{e!r}", file=sys.stderr)
        sys.exit(2)
