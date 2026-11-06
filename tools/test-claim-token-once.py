#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-claim-token-once.py — RT-E44 ③ L2 回归：同 token 二连 report 第二次必须非 200
                              （2026-11-02 施工，逃逸问题台账 RT-E44 拦截机制③原文）

台账原文（计划/研究组/红队终局轮-20261101/逃逸问题台账.md §十二 RT-E44 拦截机制③）：
    「L2 回归：同 token 二连 report 第二次必须非 200」
红队确证发现（RT-E44 证据）：修复前 af-jobs-portal.py /report 只查 revoked+expires，
成功后不吊销/轮换——同 token 连续 POST /report 三次全 200，reports/ 落 3 份、
mes_event 记 3 笔（MES 产能记账重复计数）。修复后语义（af-jobs-portal.py /report
分支「claim_token 一次性」）：成功回报后同一 token 再报一律 409（'claim_token
already used'），判定先于任何落盘。

被测件：tools/af-jobs-portal.py（本地副本=L5 部署一致性门的钉桩已修版，同一正本）。
跑法：临时 AF_JOBS_DATA 起隔离本地实例（AF_JOBS_PORT 随机空闲端口，零公网零生产扰动；
MES 无 MES_CH_URL 时降级写本地可重放队列 <DATA>/mes-events.jsonl，正好用作记账断言面）。

断言（全过才 exit 0；任一非零退出=红，不静默 SKIP）：
  ① 钉桩对账：本地副本 md5 ≡ deploy-consistency-probe.sh D1b 的 PIN_MD5
    （两处同源，改正本必须同步两处——防本测试被换成旧版被测件后照跑）
  ② 内容标记：'claim_token already used' 在被测件中在位（同 D1c 口径）
  ③ claim → 200 且发 token；report #1 → 200
  ④ report #2（同 token）→ 409「claim_token already used」（非 200 即台账红线，
     钉死 409=修复实现契约；被测件若为 pre-RT 带洞版此处得 200 → ④红=判别力）
  ⑤ reports/ 恰 1 份（重复回报不重复落盘）；mes 队列 sandbox_report 恰 1 笔
    （MES 记账不重复——RT-E44 发现的核心危害面）

退出码：0=语义在位；1=回归红（④⑤ 或 ③ 行为异常）；2=前置失败（被测件缺件/
      起不来/端口异常——按 all-gates「非零即红」口径照样红点名，不静默 SKIP）。
判别力实证（2026-11-02 亲跑）：同套夹具对 pre-RT 带洞副本
  tools/af-jobs-portal.py.20261031-pre-RT.bak → report #2 = 200（无一次性语义）→
  本测试④必红；钉桩已修版 → 409 → 绿。见 RT-E46 收口批回归记录。
"""

import json
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

TOOLS = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.join(TOOLS, "af-jobs-portal.py")
DEPLOY_PROBE = os.path.join(TOOLS, "deploy-consistency-probe.sh")

MARK = "claim_token already used"


def _pinned_md5():
    """从 tools/deploy-consistency-probe.sh D1b 派生钉桩（单一真源，消除双钉桩漂移：
    2026-11-02 实证——并行批改正本而钉桩未同步时，硬编码双副本会各自为政；本测试
    钉桩值改为随部署一致性门联动，正本换版=拥有方更新 D1b=本测试自动跟随）。
    解析不到按前置红（rc=2），不猜绿。"""
    import re
    try:
        src = open(DEPLOY_PROBE, encoding="utf-8").read()
        m = re.search(r'PIN_MD5="([0-9a-f]{32})"', src)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None
TASK_ID = "t-gate-once-001"  # 须匹配 portal _STATIC_NAME_RE = [A-Za-z0-9._-]+
# 夹具 payload（2026-11-03 修）：第八批 RT-E169 服务端回报门
# （portal _report_admission_error）要求 payload 至少含一个已知回报 schema 键
# （atoms/verdicts/verifications/rulings/findings 之一且为非空数组），且树内
# quote 串 ≤120 字。夹具原用 {"ok": True}，在第八批正本下 report #1 会被 400
# 拒收（③红）——该断言此前被 rc=2 前置红（钉桩未同步）遮住，从未走到。
# 改为合形 payload 后 report #1 才可能 200，④ 的 409 一次性断言才真正被执行。
# 断言本身一字未动（只换夹具载荷形状）。
PAYLOAD = {"atoms": [{"id": "atom-1", "quote": "gate fixture atom"}]}


def die(code, msg):
    print(f"[RED rc={code}] {msg}", file=sys.stderr)
    sys.exit(code)


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def http(port, method, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    # ①② 钉桩与内容标记
    if not os.path.isfile(PORTAL):
        die(2, f"前置失败：被测件缺件 {PORTAL}")
    pin = _pinned_md5()
    if not pin:
        die(2, f"前置失败：无法从 {DEPLOY_PROBE} 解析 PIN_MD5（部署一致性门不在位/被改形）")
    got = md5_of(PORTAL)
    if got != pin:
        die(2, f"前置失败：被测件 md5={got} ≠ 钉桩 {pin}（=deploy-consistency-probe.sh D1b；"
               f"被测件被替换/回滚/改正本未部署未同步钉桩——拥有方更新 D1b 后本测试自动跟随）")
    if MARK not in open(PORTAL, encoding="utf-8").read():
        die(2, f"前置失败：被测件缺一次性语义标记「{MARK}」（md5 钉桩锚失效/内容被换）")

    # 隔离实例
    data = tempfile.mkdtemp(prefix="afjobs-gate-once-")
    port = free_port()
    tdir = os.path.join(data, "tasks", TASK_ID)
    os.makedirs(tdir)
    open(os.path.join(tdir, "meta.json"), "w").write(json.dumps({"id": TASK_ID, "title": "gate fixture"}))
    open(os.path.join(tdir, "problem.md"), "w").write("# gate fixture\n")
    open(os.path.join(tdir, "AGENTS.md"), "w").write("# fixture contract\n")
    env = dict(os.environ)
    env["AF_JOBS_DATA"] = data
    env["AF_JOBS_PORT"] = str(port)
    env.pop("MES_CH_URL", None)  # 显式走本地可重放队列（记账断言面）
    proc = subprocess.Popen([sys.executable, "-I", PORTAL],
                            env=env, cwd=data,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if proc.poll() is not None:
                die(2, f"前置失败：本地实例启动即退（rc={proc.returncode}）")
            try:
                st, _ = http(port, "GET", "/healthz")
                if st == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            die(2, f"前置失败：healthz 2s 内未就绪（port={port}）")

        # ③ claim → report #1
        st, body = http(port, "POST", "/claim", {"task_id": TASK_ID, "sandbox": "gate-once"})
        if st != 200:
            die(1, f"③红：claim 期望 200 得 {st}：{body[:120]}")
        tok = (json.loads(body).get("claim_token") or "")
        if not tok:
            die(1, "③红：claim 200 但未发放 claim_token")
        st1, body1 = http(port, "POST", "/report", {"claim_token": tok, "payload": PAYLOAD})
        if st1 != 200:
            die(1, f"③红：report #1 期望 200 得 {st1}：{body1[:120]}")

        # ④ 同 token 二连 report → 必须 409
        st2, body2 = http(port, "POST", "/report", {"claim_token": tok, "payload": PAYLOAD})
        if st2 == 200:
            die(1, f"④红：同 token 二连 report 得 200（claim_token 一次性语义缺失——RT-E44 漏洞态复现）")
        if st2 != 409:
            die(1, f"④红：同 token 二连 report 得 {st2}（非 200 但也非契约 409）：{body2[:120]}")
        if "already used" not in body2:
            die(1, f"④红：409 体缺「already used」标记：{body2[:160]}")

        # ⑤ 落盘与记账恰一次
        reps = [f for f in os.listdir(os.path.join(data, "reports")) if f.endswith(".json")]
        if len(reps) != 1:
            die(1, f"⑤红：reports/ 期望恰 1 份，得 {len(reps)}：{reps}（重复回报重复落盘）")
        q = os.path.join(data, "mes-events.jsonl")
        n_report = 0
        if os.path.isfile(q):
            n_report = sum(1 for ln in open(q, encoding="utf-8") if '"sandbox_report"' in ln)
        if n_report != 1:
            die(1, f"⑤红：mes 队列 sandbox_report 期望恰 1 笔，得 {n_report}（MES 记账重复——RT-E44 核心危害面）")

        print(f"OK：claim→report 200 → 同 token 再报 409（{MARK}）；reports/=1、mes sandbox_report=1"
              f"——RT-E44 一次性语义在位（被测件 md5 {got[:8]}… ≡ 钉桩）")
        sys.exit(0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
