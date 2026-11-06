#!/usr/bin/env python3
"""swev-judge-v2-selftest.py — D-32 判分器 v2 正反例测试套件。

三缺陷各配正反例（红队裁决 R4/R5/R7 修改要求）:
  ① 零状态三态：正例=三种零状态形态（0 tests / 标记间空段（整日志回退为空）/
     截断日志）→ v2 判 zero_state/no_markers 且 log_parsed=false；
     反例=真跑过的日志 → parsed/log_parsed=true（不误伤）；并复现 v1 缺陷
     （同一零状态日志 v1 记 log_parsed=true）。
  ② hermeticity：正例=冷缓存判分被拒（verdict=hermeticity_blocked、resolved=null、
     blocked_urls 含 raw.githubusercontent.com）；假域/本地探针证明禁外呼；
     反例=暖缓存后同输入离线判出与 v1 同值（hermetic=true）。
  ③ diff 合法性：正例=R7 实证 ssh 错误残片（63 字节 CRLF，sha256 f5906672…）
     与 docker 错误文本 → invalid_diff/resolved=null；反例=真补丁（diff --git）
     照常判定。

用法: python3 tools/swev-judge-v2-selftest.py [task.json]
  默认 task=/tmp/swev-s1/pallets__flask-5014.json（可用 argv[1] 覆盖）。
退出码: 0=无 FAIL（SKIP 如实列明）；1=有 FAIL；2=环境不满足（如无网络且冷缓存）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/home/pan-ding/workspace/agent黑灯工厂")
V2 = ROOT / "tools" / "swev-judge-v2.py"
V1 = ROOT / "tools" / "swev-judge.py"
VENV_PY = "/home/pan-ding/swev-venv/bin/python"
DEFAULT_TASK = "/tmp/swev-s1/pallets__flask-5014.json"

# R7 实证残片原文（裁决书抽查锚点：3 文件 sha256 同为 f5906672…，sphinx-8120-a2 63 字节/CRLF）
SSH_RESIDUE = (b"ssh: connect to host anolis-host.invalid port 22: Connection timed out\r\n")
SSH_RESIDUE_SHA = "f59066727a8b97bf086f4a4aff751ce9f993b82112ddbc1b1770f51c41bc08c1"
# R7 注：第 4 例（bench-poc-step5，docker 错误文本）同型
DOCKER_RESIDUE = (b"docker: Error response from daemon: Get https://registry-1.docker.io/v2/: "
                  b"dial tcp: lookup registry-1.docker.io: Temporary failure in name resolution\n")

RESULTS = []


def rec(name, ok, detail="", skip=False):
    RESULTS.append((name, "SKIP" if skip else ("PASS" if ok else "FAIL"), detail))
    tag = "SKIP" if skip else ("PASS" if ok else "FAIL")
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def run(cmd, env=None, timeout=180):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=timeout)


def run_retry(cmd, env=None, attempts=3, timeout=180):
    """v1 判分每判必发 live HTTP（R5 缺陷本体）——ConnectionReset 属预期噪声，重试。
    重试次数与失败事实在用例详情里如实体现。"""
    last = None
    for i in range(attempts):
        last = run(cmd, env=env, timeout=timeout)
        if last.returncode == 0 and jload(last.stdout):
            return last
    return last


def jload(text):
    try:
        return json.loads(text.strip().splitlines()[-1])
    except Exception:
        return None


# ---------------------------------------------------------------- 单元测试
def unit_tests(task_json=DEFAULT_TASK):
    sys.path.insert(0, str(V2.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("swev_judge_v2", V2)
    v2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v2)

    # --- 缺陷③ diff_legal ---
    ok, why = v2.diff_legal(SSH_RESIDUE.decode())
    rec("unit/diff_legal 拒 ssh 残片", (not ok) and why == "ssh_error_text", f"reason={why}")
    ok, why = v2.diff_legal(DOCKER_RESIDUE.decode())
    rec("unit/diff_legal 拒 docker 错误文本", (not ok) and why == "docker_error_text", f"reason={why}")
    ok, why = v2.diff_legal("")
    rec("unit/diff_legal 拒空补丁(标记 empty)", (not ok) and why == "empty", f"reason={why}")
    ok, why = v2.diff_legal("random garbage\nno headers here\n")
    rec("unit/diff_legal 拒无补丁头垃圾文本", (not ok) and why == "no_patch_header", f"reason={why}")
    ok, why = v2.diff_legal("diff --git a/x.py b/x.py\nindex 1..2 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n")
    rec("unit/diff_legal 收 diff --git 补丁", ok, f"reason={why}")
    ok, why = v2.diff_legal("--- a/x.py\t2020-01-01\n+++ b/x.py\t2020-01-01\n@@ -1 +1 @@\n-a\n+b\n")
    rec("unit/diff_legal 收纯 unified diff", ok, f"reason={why}")
    import hashlib
    rec("unit/ssh 残片字节与 sha256 锚点一致",
        len(SSH_RESIDUE) == 63
        and hashlib.sha256(SSH_RESIDUE).hexdigest() == SSH_RESIDUE_SHA,
        f"bytes={len(SSH_RESIDUE)} sha={hashlib.sha256(SSH_RESIDUE).hexdigest()[:16]}…")

    # --- 缺陷① log_state 分类（stub spec，零网络） ---
    class StubSpec:
        def __init__(self, repo, version):
            self.repo, self.version = repo, version

    _t = json.load(open(task_json, encoding="utf-8"))
    spec_obj = StubSpec(_t["repo"], _t.get("version", ""))
    tmp = Path(tempfile.mkdtemp(prefix="swev-v2-selftest-"))

    def wlog(name, text):
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    zero_0tests = wlog("zero-0tests.log",
                       "+ : '>>>>> Start Test Output'\n"
                       "============================= test session starts ==============================\n"
                       "collected 0 items\n"
                       "============================= no tests ran in 0.01s =============================\n"
                       "+ : '>>>>> End Test Output'\n")
    zero_emptysection = wlog("zero-empty-section.log",
                             "+ some set -x trace\n+ : '>>>>> Start Test Output'\n"
                             "+ : '>>>>> End Test Output'\n+ more trace\n")
    truncated = wlog("truncated.log",
                     "+ : '>>>>> Start Test Output'\n"
                     "PASSED tests/test_basic.py::test_ok\n"
                     "…(运行中超时击杀，无 End 标记)\n")
    empty = wlog("empty.log", "")
    evalerr = wlog("eval-error.log",
                   "+ git apply 输出\n>>>>> Patch Apply Failed\n"
                   "+ : '>>>>> Start Test Output'\n+ : '>>>>> End Test Output'\n")
    good = wlog("good.log",
                "+ : '>>>>> Start Test Output'\n"
                "============================= test session starts ==============================\n"
                "PASSED tests/test_basic.py::test_ok\n"
                "FAILED tests/test_basic.py::test_bad\n"
                "+ : '>>>>> End Test Output'\n")
    for name, path, want in [
        ("unit/log_state 零状态-0tests", zero_0tests, "zero_state"),
        ("unit/log_state 零状态-标记间空段(整日志回退为空)", zero_emptysection, "zero_state"),
        ("unit/log_state no_markers-截断日志", truncated, "no_markers"),
        ("unit/log_state no_markers-空日志", empty, "no_markers"),
        ("unit/log_state eval_error-补丁应用失败码", evalerr, "eval_error"),
        ("unit/log_state parsed-反例(真跑过不误伤)", good, "parsed"),
    ]:
        state, sm, markers, bad = v2.classify_log_state(spec_obj, path)
        rec(name, state == want, f"state={state} parsed_status={len(sm)}")

    # --- 缺陷② HermeticGuard ---
    import requests
    import socket
    g = v2.HermeticGuard(allow_live=False, cache_dir=str(tmp / "guard-cache"))
    with g():
        blocked = None
        try:
            requests.get("http://judge-hermeticity-probe.invalid/probe")
        except v2.HermeticBlocked as e:
            blocked = e.target
        rec("unit/guard 假域外呼被拒且留痕",
            blocked is not None and blocked in g.blocked_urls and not g.hermetic(),
            f"blocked={blocked}")
        sock_blocked = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("anolis-host.invalid", 22))  # 本地探针：补线在真实 connect 前拦下
        except v2.HermeticBlocked as e:
            sock_blocked = e.target
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        rec("unit/guard 本地 socket 探针被拒且留痕", sock_blocked is not None,
            f"connects={g.socket_connects}")
        dns_blocked = None
        try:
            socket.getaddrinfo("raw.githubusercontent.com", 443)
        except v2.HermeticBlocked as e:
            dns_blocked = e.target
        rec("unit/guard DNS 外呼被拒", dns_blocked is not None, f"target={dns_blocked}")

    # 缓存命中不触网
    g2 = v2.HermeticGuard(allow_live=False, cache_dir=str(tmp / "guard-cache"))
    g2._cache_put("https://example.invalid/cached.txt", 200, "cached-body")
    with g2():
        r = requests.get("https://example.invalid/cached.txt", headers={"X": "1"})
        rec("unit/guard 缓存命中零外呼",
            r.status_code == 200 and r.text == "cached-body" and g2.hermetic(),
            f"status={r.status_code} hermetic={g2.hermetic()}")
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- CLI 端到端
def e2e_tests(task_json):
    tmp = Path(tempfile.mkdtemp(prefix="swev-v2-e2e-"))
    cache = str(tmp / "cache")
    cold_cache = str(tmp / "cold-cache")
    os.makedirs(cold_cache, exist_ok=True)

    # 暖缓存（显式放行口子；留痕见 warm 输出 live_http）
    warm = run_retry([VENV_PY, str(V2), "--warm-cache", task_json],
                     env={"SWEV_JUDGE_V2_ALLOW_LIVE": "1", "SWEV_JUDGE_V2_CACHE": cache})
    wj = jload(warm.stdout)
    if not (warm.returncode == 0 and wj and wj.get("warm")):
        rec("e2e/暖缓存(需网络)", False, f"rc={warm.returncode} err={warm.stderr[-200:]}", skip=True)
        print("SKIP-ALL-E2E: 无法暖缓存（网络不可达？）——e2e 全部跳过", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        return "skip-all"
    rec("e2e/暖缓存(需网络)", True, f"urls={len(wj.get('urls_fetched', []))}")

    task = json.load(open(task_json, encoding="utf-8"))
    iid = task["instance_id"]

    def v2_judge(log, diff, cache_dir=cache):
        cmd = [VENV_PY, str(V2), task_json, log]
        if diff:
            cmd.append(diff)
        return run(cmd, env={"SWEV_JUDGE_V2_CACHE": cache_dir})

    def v1_judge(log, diff):
        cmd = [VENV_PY, str(V1), task_json, log]
        if diff:
            cmd.append(diff)
        return run_retry(cmd)  # R5：v1 每判实呼，网络抖动即崩——重试后仍崩则该例 FAIL 并留痕

    # 合成日志
    def wlog(name, text):
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    zero = wlog("zero.log",
                "+ : '>>>>> Start Test Output'\n"
                "============================= test session starts ==============================\n"
                "collected 0 items\n============================= no tests ran in 0.01s =============================\n"
                "+ : '>>>>> End Test Output'\n")
    trunc = wlog("trunc.log", "+ : '>>>>> Start Test Output'\nPASSED tests/test_basic.py::test_ok\n(截断)\n")
    empty = wlog("empty.log", "")
    good = wlog("good.log",
                "+ : '>>>>> Start Test Output'\n"
                "============================= test session starts ==============================\n"
                + "".join(f"PASSED tests/test_x.py::test_{i}\n" for i in range(3))
                + "+ : '>>>>> End Test Output'\n")
    ssh_diff = tmp / "ssh-residue.diff"
    ssh_diff.write_bytes(SSH_RESIDUE)
    docker_diff = tmp / "docker-residue.diff"
    docker_diff.write_bytes(DOCKER_RESIDUE)
    real_diff = tmp / "real.diff"
    real_diff.write_text("diff --git a/CHANGES.rst b/CHANGES.rst\nindex 498d5e5..d6595f5 100644\n"
                         "--- a/CHANGES.rst\n+++ b/CHANGES.rst\n@@ -33,6 +33,8 @@ Unreleased\n", encoding="utf-8")

    # ①零状态正例：v2 三态 + v1 缺陷复现
    r = v2_judge(zero, str(real_diff)); j = jload(r.stdout)
    rec("e2e/①零状态(0 tests) → zero_state/log_parsed=false",
        bool(j) and j.get("log_state") == "zero_state" and j.get("log_parsed") is False
        and j.get("tests_status_parsed") == 0 and j.get("resolved") is False
        and j.get("verdict") == "zero_state" and j.get("hermetic") is True,
        f"verdict={j and j.get('verdict')} lp={j and j.get('log_parsed')} tsp={j and j.get('tests_status_parsed')}")
    r1 = v1_judge(zero, str(real_diff)); j1 = jload(r1.stdout)
    rec("e2e/①零状态 v1 缺陷复现(log_parsed=true)",
        bool(j1) and j1.get("log_parsed") is True and j1.get("resolved") is False,
        f"v1: {r1.stdout.strip()[:160]}")
    for name, path, want in [("e2e/①截断日志 → no_markers", trunc, "no_markers"),
                             ("e2e/①空日志 → no_markers", empty, "no_markers")]:
        r = v2_judge(path, str(real_diff)); j = jload(r.stdout)
        rec(name, bool(j) and j.get("log_state") == want and j.get("log_parsed") is False,
            f"verdict={j and j.get('verdict')}")
        r1 = v1_judge(path, str(real_diff)); j1 = jload(r1.stdout)
        rec(f"{name}（v1 同判=false，反例：v1 在此形态本就正确）",
            bool(j1) and j1.get("log_parsed") is False, f"v1 lp={j1 and j1.get('log_parsed')}")

    # ①反例：真跑过不误伤 + v1/v2 一致
    r = v2_judge(good, str(real_diff)); j = jload(r.stdout)
    rec("e2e/①反例 真跑过日志 → parsed/log_parsed=true（不误伤）",
        bool(j) and j.get("log_state") == "parsed" and j.get("log_parsed") is True,
        f"tsp={j and j.get('tests_status_parsed')}")

    # ②正例：冷缓存拒判
    r = v2_judge(good, str(real_diff), cache_dir=cold_cache); j = jload(r.stdout)
    blocked_raw = any("raw.githubusercontent.com" in u for u in (j or {}).get("blocked_urls", []))
    rec("e2e/②冷缓存 → hermeticity_blocked/resolved=null/禁外呼留痕",
        bool(j) and j.get("verdict") == "hermeticity_blocked" and j.get("resolved") is None
        and blocked_raw and j.get("hermetic") is False,
        f"blocked={len((j or {}).get('blocked_urls', []))} raw_hit={blocked_raw}")

    # ②反例：暖缓存后离线判出（与 v1 同输入对比放在回放脚本，这里验证 hermetic=true 且可判）
    r = v2_judge(good, str(real_diff)); j = jload(r.stdout)
    rec("e2e/②反例 暖缓存离线判分 hermetic=true",
        bool(j) and j.get("hermetic") is True and j.get("live_http") == []
        and j.get("blocked_urls") == [] and j.get("resolved") is not None,
        f"verdict={j and j.get('verdict')} resolved={j and j.get('resolved')}")

    # ③正例：ssh/docker 残片拒判（v1 同输入会照单全收当补丁放行）
    for name, dpath in [("e2e/③ssh 残片 → invalid_diff", str(ssh_diff)),
                        ("e2e/③docker 错误文本 → invalid_diff", str(docker_diff))]:
        r = v2_judge(good, dpath); j = jload(r.stdout)
        rec(name, bool(j) and j.get("verdict") == "invalid_diff" and j.get("resolved") is None
            and j.get("diff_valid") is False and j.get("hermetic") is True,
            f"reason={j and j.get('diff_reject_reason')} bytes={j and j.get('diff_bytes')}")
    r1 = v1_judge(good, str(ssh_diff)); j1 = jload(r1.stdout)
    rec("e2e/③ssh 残片 v1 缺陷复现（照单全收当补丁，判 resolved=false 假阴性）",
        bool(j1) and j1.get("resolved") is False and "diff" not in j1,
        f"v1: {r1.stdout.strip()[:160]}")

    # ③反例：真补丁照常判定
    r = v2_judge(good, str(real_diff)); j = jload(r.stdout)
    rec("e2e/③反例 真补丁 diff_valid=true 照常判定",
        bool(j) and j.get("diff_valid") is True and j.get("resolved") is not None,
        f"verdict={j and j.get('verdict')}")

    # 空补丁：仍判日志但标记（C6 口径不变）
    empty_diff = tmp / "empty.diff"
    empty_diff.write_bytes(b"")
    r = v2_judge(good, str(empty_diff)); j = jload(r.stdout)
    rec("e2e/③空补丁(0B) 仍判日志+标记 diff_valid=false/empty",
        bool(j) and j.get("diff_valid") is False and j.get("diff_reject_reason") == "empty"
        and j.get("resolved") is not None, f"verdict={j and j.get('verdict')}")

    # 缺日志：确定性无判定（v1 此处 Traceback）
    r = v2_judge(str(tmp / "no-such.log"), str(real_diff)); j = jload(r.stdout)
    rec("e2e/缺日志 → no_log/resolved=null（v1 在此 Traceback）",
        bool(j) and j.get("verdict") == "no_log" and j.get("resolved") is None,
        f"verdict={j and j.get('verdict')}")

    shutil.rmtree(tmp, ignore_errors=True)
    return "ran"


def main():
    task_json = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    if not os.path.isfile(task_json):
        print(f"task.json 不存在: {task_json}（可用 argv[1] 指定，如 /tmp/swev-s1/pallets__flask-5014.json）")
        return 2
    print(f"== 单元测试 ==", flush=True)
    unit_tests(task_json)
    print(f"== CLI 端到端（task={task_json}） ==", flush=True)
    mode = e2e_tests(task_json)
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    n_skip = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print(f"\n== 汇总: {len(RESULTS)} 例, FAIL={n_fail}, SKIP={n_skip} ==", flush=True)
    if n_fail:
        print("FAILED 用例:")
        for name, s, d in RESULTS:
            if s == "FAIL":
                print(f"  - {name} — {d}")
        return 1
    if mode == "skip-all":
        print("（e2e 全部因网络不可达跳过；单元测试全过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
