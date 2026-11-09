#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner-bootstrap-watchdog.py — 引导看门狗可审计 CLI（SR-025 · factory-os #274）

把「worker 引导挂死检测」做成可审计命令：diag 目录里最新 Worker 件的
文件名时间戳年龄 > 12min，且内容扫描不到作业步骤标记 ⇒ 挂死。
判定核与 anolis 在役裸脚本同源（裁决 #46/#48 语义镜像；宿主路径不入仓）。

模式：
  --check <diag目录>     0=健康 / 1=挂死 / 2=不可证
                         证据：最新 Worker 文件名年龄 + 内容标记扫描结果
  --recover-cmd TEXT     恢复命令（exec 形，shlex 拆分；缺省不跑）
  --exec                 挂死时真跑恢复命令；缺省只打印 dry-run
  --selftest             夹具逐个真跑（健康 / 挂死 / 边界 12min± / dry-run / exec）
  --now-epoch SEC        审计钉（夹具用）；缺省墙钟

挂死判据（合取，缺一不判挂）：
  ① 最新 Worker 文件名时间戳年龄 > 720s（12min，严格大于）
  ② 该件内容扫描不到任一条作业步骤标记

健康 = 非挂死：窗内（≤720s）无论有无标记；窗外但已有标记（作业在跑）。
无 Worker 件 / 空目录 = 健康（没有在引导的 worker 可挂）。
缺目录 / 非目录 / --exec 无恢复命令 = rc=2 不猜绿。

Worker 件名（只认这两种诊断形，其它 Worker* 忽略）：
  Worker_YYYYMMDD-HHMMSS[-utc].log     runner _diag 形
  Worker-YYYY-MM-DDTHH-MM-SS[-mmm].log Chromium 形
时间戳按 UTC 解析。只扫 --check 给定目录一层，不递归。

作业步骤标记（子串命中即「已进入作业」，引导已过）：
  作业步骤 / ##[section] / Job message received / Running job / STEP_OK / STEP_FAIL

恢复：只在 VERDICT=hung 时动作。无 --exec = 打印 would-run 不落子进程。
--exec 须同时给 --recover-cmd，否则 rc=2。健康面 --exec 不跑恢复。

出口：
  --check     0 健康 / 1 挂死 / 2 不可证
  --selftest  0 夹具全过 / 1 有断言败
  用法错      2

纪律：零网络；selftest 只写临时目录用后即清；夹具 SENTINEL-XXX 形；
判据/判官/门禁件零触碰。
"""
import argparse
import datetime
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

SCHEMA = "af.runner-bootstrap-watchdog.v1"
HANG_MIN = 12
THRESHOLD_S = HANG_MIN * 60  # 720；严格大于才挂死

RC_OK, RC_HUNG, RC_UNPROVABLE = 0, 1, 2
RC_FAIL = 1  # selftest 断言败

UTC = datetime.timezone.utc

# 作业步骤标记：子串扫描，顺序稳定，输出点名用此表。
STEP_MARKERS = (
    "作业步骤",
    "##[section]",
    "Job message received",
    "Running job",
    "STEP_OK",
    "STEP_FAIL",
)

# runner _diag：Worker_YYYYMMDD-HHMMSS-utc.log
_RE_GHA = re.compile(
    r"^Worker_(\d{8})-(\d{6})(?:-utc)?(?:\.[A-Za-z0-9]+)?$",
    re.IGNORECASE,
)
# Chromium：Worker-YYYY-MM-DDTHH-MM-SS[-mmm].log
_RE_CHROME = re.compile(
    r"^Worker-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})"
    r"(?:[-.]\d+)?(?:\.[A-Za-z0-9]+)?$",
)

READ_CAP = 16 * 1024 * 1024
RECOVER_TIMEOUT_S = 30


def err(msg):
    sys.stderr.write("[runner-bootstrap-watchdog] %s\n" % msg)


def now_epoch(pin=None):
    if isinstance(pin, (int, float)) and not isinstance(pin, bool):
        return float(pin)
    return time.time()


def parse_worker_filename_ts(name):
    """从 Worker 件名解析 UTC epoch。对不上诊断形 → None。"""
    base = os.path.basename(name)
    m = _RE_GHA.match(base)
    if m:
        day, hms = m.group(1), m.group(2)
        try:
            dt = datetime.datetime.strptime(day + hms, "%Y%m%d%H%M%S")
        except ValueError:
            return None
        return dt.replace(tzinfo=UTC).timestamp()
    m = _RE_CHROME.match(base)
    if m:
        day, hh, mm, ss = m.group(1), m.group(2), m.group(3), m.group(4)
        try:
            dt = datetime.datetime.strptime(
                "%sT%s:%s:%s" % (day, hh, mm, ss), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
        return dt.replace(tzinfo=UTC).timestamp()
    return None


def is_worker_name(name):
    base = os.path.basename(name)
    return base.startswith("Worker_") or base.startswith("Worker-")


def list_workers(diag_dir):
    """→ ([(ts, basename, path), ... 升序], err|None)。listdir 失败 err 非空。"""
    try:
        entries = os.listdir(diag_dir)
    except OSError as exc:
        return None, "listdir 失败：%s" % exc
    rows = []
    for name in entries:
        if not is_worker_name(name):
            continue
        path = os.path.join(diag_dir, name)
        if not os.path.isfile(path):
            continue
        ts = parse_worker_filename_ts(name)
        if ts is None:
            continue
        rows.append((ts, name, path))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows, None


def scan_markers(path):
    """→ (hits:list, err|None)。读不出 → hits=[] 且 err 非空。"""
    try:
        with open(path, "rb") as fh:
            blob = fh.read(READ_CAP)
    except OSError as exc:
        return [], "read 失败：%s" % exc
    text = blob.decode("utf-8", errors="replace")
    hits = [m for m in STEP_MARKERS if m in text]
    return hits, None


def format_ts(epoch):
    dt = datetime.datetime.fromtimestamp(float(epoch), tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def gha_name(epoch):
    dt = datetime.datetime.fromtimestamp(float(epoch), tz=UTC)
    return "Worker_%s-utc.log" % dt.strftime("%Y%m%d-%H%M%S")


def chrome_name(epoch):
    dt = datetime.datetime.fromtimestamp(float(epoch), tz=UTC)
    return "Worker-%s.log" % dt.strftime("%Y-%m-%dT%H-%M-%S-000")


def decide(age_s, hits, readable):
    """纯判定。返回 (verdict, rc)。

    verdict: healthy / hung / unprovable
    窗外且内容不可读 → 不可证（不能证明「无标记」）。
    """
    over = age_s > THRESHOLD_S
    if not readable and over:
        return "unprovable", RC_UNPROVABLE
    if over and not hits:
        return "hung", RC_HUNG
    return "healthy", RC_OK


def emit_check(diag_dir, now, recover_cmd=None, do_exec=False):
    """跑 --check。返回 rc。证据打 stdout；用法/缺件打 stderr。"""
    lines = []

    def out(s):
        lines.append(s)
        print(s, flush=True)

    out("SCHEMA=%s" % SCHEMA)
    out("MODE=check")
    out("THRESHOLD_S=%d" % THRESHOLD_S)
    out("NOW_EPOCH=%.0f" % now)
    out("NOW_TS=%s" % format_ts(now))
    out("DIAG_DIR=%s" % diag_dir)

    if not os.path.exists(diag_dir):
        err("FAIL 缺件：diag 目录不在位")
        out("VERDICT=unprovable")
        out("RC=%d" % RC_UNPROVABLE)
        return RC_UNPROVABLE
    if not os.path.isdir(diag_dir):
        err("FAIL 非目录：--check 要的是 diag 目录")
        out("VERDICT=unprovable")
        out("RC=%d" % RC_UNPROVABLE)
        return RC_UNPROVABLE

    rows, lerr = list_workers(diag_dir)
    if lerr:
        err("FAIL %s" % lerr)
        out("VERDICT=unprovable")
        out("RC=%d" % RC_UNPROVABLE)
        return RC_UNPROVABLE

    out("WORKER_COUNT=%d" % len(rows))
    if not rows:
        out("WORKER_BASENAME=")
        out("FILENAME_TS=")
        out("AGE_S=")
        out("AGE_MIN=")
        out("OVER_THRESHOLD=no")
        out("MARKER_SCAN=none")
        out("MARKER_HITS=0")
        out("MARKER_NAMES=")
        out("VERDICT=healthy")
        out("NOTE=no Worker diagnostic file in dir")
        rec_lines, rec_rc = recover_action(
            "healthy", recover_cmd, do_exec)
        for ln in rec_lines:
            out(ln)
        out("RC=%d" % RC_OK)
        return RC_OK

    ts, basename, path = rows[-1]
    age_s = now - ts
    hits, rerr = scan_markers(path)
    readable = rerr is None
    verdict, rc = decide(age_s, hits, readable)
    over = age_s > THRESHOLD_S

    out("WORKER_BASENAME=%s" % basename)
    out("WORKER_PATH=%s" % path)
    out("FILENAME_TS=%s" % format_ts(ts))
    out("FILENAME_EPOCH=%.0f" % ts)
    out("AGE_S=%.0f" % age_s)
    out("AGE_MIN=%.2f" % (age_s / 60.0))
    out("OVER_THRESHOLD=%s" % ("yes" if over else "no"))
    if not readable:
        out("MARKER_SCAN=unreadable")
        out("MARKER_ERR=%s" % rerr)
        out("MARKER_HITS=0")
        out("MARKER_NAMES=")
    elif hits:
        out("MARKER_SCAN=hit")
        out("MARKER_HITS=%d" % len(hits))
        out("MARKER_NAMES=%s" % ",".join(hits))
    else:
        out("MARKER_SCAN=none")
        out("MARKER_HITS=0")
        out("MARKER_NAMES=")
    out("VERDICT=%s" % verdict)

    rec_lines, rec_rc = recover_action(verdict, recover_cmd, do_exec)
    for ln in rec_lines:
        out(ln)
    if rec_rc is not None and verdict != "hung":
        # recover_action 只在 hung 时可能把 rc 改成 2（--exec 无命令）
        pass
    if rec_rc == RC_UNPROVABLE:
        out("RC=%d" % RC_UNPROVABLE)
        return RC_UNPROVABLE
    out("RC=%d" % rc)
    return rc


def recover_action(verdict, recover_cmd, do_exec):
    """恢复腿。返回 (lines, override_rc|None)。override_rc=2 表示 --exec 无法兑现。"""
    lines = []
    if verdict != "hung":
        lines.append("RECOVER=skip")
        lines.append("RECOVER_NOTE=verdict-not-hung")
        return lines, None
    if not recover_cmd:
        if do_exec:
            err("FAIL 用法：--exec 须同时给 --recover-cmd")
            lines.append("RECOVER=error")
            lines.append("RECOVER_NOTE=exec-without-cmd")
            return lines, RC_UNPROVABLE
        lines.append("RECOVER=skip")
        lines.append("RECOVER_NOTE=no-recover-cmd")
        return lines, None
    lines.append("RECOVER_CMD=%s" % recover_cmd)
    if not do_exec:
        lines.append("RECOVER=dry-run")
        lines.append("would-run: %s" % recover_cmd)
        return lines, None
    try:
        argv = shlex.split(recover_cmd, posix=True)
    except ValueError as exc:
        err("FAIL 恢复命令拆分失败：%s" % exc)
        lines.append("RECOVER=error")
        lines.append("RECOVER_NOTE=shlex-split-fail")
        return lines, RC_UNPROVABLE
    if not argv:
        err("FAIL 恢复命令拆完为空")
        lines.append("RECOVER=error")
        lines.append("RECOVER_NOTE=empty-cmd")
        return lines, RC_UNPROVABLE
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=RECOVER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        lines.append("RECOVER=exec")
        lines.append("RECOVER_RC=timeout")
        lines.append("RECOVER_NOTE=timeout-%ds" % RECOVER_TIMEOUT_S)
        return lines, None
    except OSError as exc:
        lines.append("RECOVER=exec")
        lines.append("RECOVER_RC=oserr")
        lines.append("RECOVER_NOTE=%s" % exc)
        return lines, None
    lines.append("RECOVER=exec")
    lines.append("RECOVER_RC=%d" % p.returncode)
    tail = (p.stdout or "").strip().splitlines()[-1:] + (
        p.stderr or "").strip().splitlines()[-1:]
    if tail:
        lines.append("RECOVER_TAIL=%s" % " | ".join(tail)[:200])
    return lines, None


# ---- selftest：夹具逐个真跑（子进程 python3 -I 本件）------------------------

def _cli(args, timeout=30):
    cmd = [sys.executable, "-I", os.path.abspath(__file__)] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout or "", p.stderr or ""


def _write(path, body):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


BOOT_BODY = (
    "Worker process start\n"
    "Initializing host context\n"
    "Waiting for assignment\n"
    "SENTINEL-XXX-BOOT-0001\n"
)
STEP_BODY = (
    "Worker process start\n"
    "作业步骤 1 checkout\n"
    "SENTINEL-XXX-STEP-0001\n"
)
GHA_STEP_BODY = (
    "Worker process start\n"
    "##[section]Starting: Set up job\n"
    "SENTINEL-XXX-GHA-0001\n"
)


def run_selftest():
    cases = []

    def chk(name, ok, detail=""):
        cases.append((name, bool(ok), detail))
        flag = "PASS" if ok else "FAIL"
        extra = "" if ok else (" ｜ " + detail)
        print("  %s %s%s" % (flag, name, extra), flush=True)

    now = float(int(time.time()))
    now_s = "%.0f" % now

    with tempfile.TemporaryDirectory(prefix="rbw-selftest-") as td:
        def put(diag, age_s, body, namer=gha_name):
            os.makedirs(diag, exist_ok=True)
            ts = now - float(age_s)
            path = os.path.join(diag, namer(ts))
            _write(path, body)
            return path

        def check_args(diag, extra=None):
            args = ["--check", diag, "--now-epoch", now_s]
            if extra:
                args.extend(extra)
            return _cli(args)

        # F1 窗内无标记 → 健康（引导中）
        d1 = os.path.join(td, "f1")
        put(d1, 60, BOOT_BODY)
        rc, out, err_s = check_args(d1)
        chk("F1 窗内无标记 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "OVER_THRESHOLD=no" in out and "MARKER_SCAN=none" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:220]))

        # F2 窗内有标记 → 健康
        d2 = os.path.join(td, "f2")
        put(d2, 60, STEP_BODY)
        rc, out, err_s = check_args(d2)
        chk("F2 窗内有标记 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "MARKER_SCAN=hit" in out and "作业步骤" in out,
            "rc=%s" % rc)

        # F3 窗外有标记 → 健康（作业在跑）
        d3 = os.path.join(td, "f3")
        put(d3, 780, STEP_BODY)
        rc, out, err_s = check_args(d3)
        chk("F3 窗外有标记 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "OVER_THRESHOLD=yes" in out and "MARKER_SCAN=hit" in out,
            "rc=%s" % rc)

        # F4 窗外无标记 → 挂死
        d4 = os.path.join(td, "f4")
        put(d4, 780, BOOT_BODY)
        rc, out, err_s = check_args(d4)
        chk("F4 窗外无标记 → 挂死",
            rc == RC_HUNG and "VERDICT=hung" in out
            and "OVER_THRESHOLD=yes" in out and "MARKER_SCAN=none" in out
            and "AGE_S=780" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:220]))

        # F5 边界 12min-（719s 无标记）→ 健康
        d5 = os.path.join(td, "f5")
        put(d5, 719, BOOT_BODY)
        rc, out, err_s = check_args(d5)
        chk("F5 边界 719s 无标记 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "OVER_THRESHOLD=no" in out and "AGE_S=719" in out,
            "rc=%s" % rc)

        # F6 边界恰 720s 无标记 → 健康（严格大于才挂）
        d6 = os.path.join(td, "f6")
        put(d6, 720, BOOT_BODY)
        rc, out, err_s = check_args(d6)
        chk("F6 边界 720s 无标记 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "OVER_THRESHOLD=no" in out and "AGE_S=720" in out,
            "rc=%s" % rc)

        # F7 边界 12min+（721s 无标记）→ 挂死
        d7 = os.path.join(td, "f7")
        put(d7, 721, BOOT_BODY)
        rc, out, err_s = check_args(d7)
        chk("F7 边界 721s 无标记 → 挂死",
            rc == RC_HUNG and "VERDICT=hung" in out
            and "OVER_THRESHOLD=yes" in out and "AGE_S=721" in out,
            "rc=%s" % rc)

        # F8 最新窗内件压过旧挂死件 → 健康
        d8 = os.path.join(td, "f8")
        put(d8, 900, BOOT_BODY)
        put(d8, 60, BOOT_BODY)
        rc, out, err_s = check_args(d8)
        chk("F8 最新窗内压过旧挂死 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "AGE_S=60" in out and "WORKER_COUNT=2" in out,
            "rc=%s age_line" % rc)

        # F9 最新窗外无标记压过旧有标记 → 挂死
        d9 = os.path.join(td, "f9")
        put(d9, 900, STEP_BODY)
        put(d9, 800, BOOT_BODY)
        rc, out, err_s = check_args(d9)
        chk("F9 最新窗外无标记 → 挂死",
            rc == RC_HUNG and "VERDICT=hung" in out and "AGE_S=800" in out,
            "rc=%s" % rc)

        # F10 空目录 → 健康
        d10 = os.path.join(td, "f10")
        os.makedirs(d10)
        rc, out, err_s = check_args(d10)
        chk("F10 空目录 → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "WORKER_COUNT=0" in out,
            "rc=%s" % rc)

        # F11 缺目录 → rc=2
        missing = os.path.join(td, "no-such-diag")
        rc, out, err_s = check_args(missing)
        chk("F11 缺目录 → rc=2",
            rc == RC_UNPROVABLE and "VERDICT=unprovable" in out
            and "FAIL" in err_s,
            "rc=%s err=%s" % (rc, err_s.replace("\n", " | ")[:160]))

        # F12 dry-run：挂死打印 would-run，不落旗
        d12 = os.path.join(td, "f12")
        put(d12, 780, BOOT_BODY)
        flag12 = os.path.join(td, "flag12")
        cmd12 = "touch %s" % shlex.quote(flag12)
        rc, out, err_s = check_args(d12, ["--recover-cmd", cmd12])
        chk("F12 dry-run 挂死不落旗",
            rc == RC_HUNG and "RECOVER=dry-run" in out
            and "would-run:" in out and (not os.path.exists(flag12)),
            "rc=%s exists=%s" % (rc, os.path.exists(flag12)))

        # F13 --exec 挂死真跑恢复
        d13 = os.path.join(td, "f13")
        put(d13, 780, BOOT_BODY)
        flag13 = os.path.join(td, "flag13")
        cmd13 = "touch %s" % shlex.quote(flag13)
        rc, out, err_s = check_args(
            d13, ["--exec", "--recover-cmd", cmd13])
        chk("F13 --exec 挂死真跑恢复",
            rc == RC_HUNG and "RECOVER=exec" in out
            and "RECOVER_RC=0" in out and os.path.isfile(flag13),
            "rc=%s exists=%s out=%s" % (
                rc, os.path.isfile(flag13), out.replace("\n", " | ")[:200]))

        # F14 --exec 健康面不跑恢复
        d14 = os.path.join(td, "f14")
        put(d14, 60, STEP_BODY)
        flag14 = os.path.join(td, "flag14")
        cmd14 = "touch %s" % shlex.quote(flag14)
        rc, out, err_s = check_args(
            d14, ["--exec", "--recover-cmd", cmd14])
        chk("F14 --exec 健康不跑恢复",
            rc == RC_OK and "RECOVER=skip" in out
            and (not os.path.exists(flag14)),
            "rc=%s exists=%s" % (rc, os.path.exists(flag14)))

        # F15 --exec 无恢复命令 → rc=2
        rc, out, err_s = _cli(["--check", d4, "--now-epoch", now_s, "--exec"])
        chk("F15 --exec 无命令 → rc=2",
            rc == RC_UNPROVABLE and "FAIL" in err_s,
            "rc=%s err=%s" % (rc, err_s.replace("\n", " | ")[:160]))

        # F16 Chromium 件名窗外无标记 → 挂死
        d16 = os.path.join(td, "f16")
        put(d16, 800, BOOT_BODY, namer=chrome_name)
        rc, out, err_s = check_args(d16)
        chk("F16 Chromium 件名挂死",
            rc == RC_HUNG and "VERDICT=hung" in out
            and "Worker-" in out and "AGE_S=800" in out,
            "rc=%s" % rc)

        # F17 --check 指向普通文件 → rc=2
        f17 = os.path.join(td, "not-a-dir")
        _write(f17, "SENTINEL-XXX-NOTDIR-0001\n")
        rc, out, err_s = check_args(f17)
        chk("F17 非目录 → rc=2",
            rc == RC_UNPROVABLE and "VERDICT=unprovable" in out,
            "rc=%s" % rc)

        # F18 只有 Runner_ 件（非 Worker）→ 健康
        d18 = os.path.join(td, "f18")
        os.makedirs(d18)
        _write(os.path.join(d18, "Runner_%s-utc.log" %
                            datetime.datetime.fromtimestamp(now - 900, tz=UTC)
                            .strftime("%Y%m%d-%H%M%S")),
               BOOT_BODY)
        rc, out, err_s = check_args(d18)
        chk("F18 仅 Runner_ 件 → 健康",
            rc == RC_OK and "WORKER_COUNT=0" in out
            and "VERDICT=healthy" in out,
            "rc=%s" % rc)

        # F19 GHA ##[section] 标记窗外 → 健康
        d19 = os.path.join(td, "f19")
        put(d19, 800, GHA_STEP_BODY)
        rc, out, err_s = check_args(d19)
        chk("F19 窗外 ##[section] → 健康",
            rc == RC_OK and "VERDICT=healthy" in out
            and "MARKER_SCAN=hit" in out and "##[section]" in out,
            "rc=%s" % rc)

        # F20 --selftest 不得搭 --check
        rc, out, err_s = _cli(["--selftest", "--check", d1])
        chk("F20 --selftest 独用",
            rc == RC_UNPROVABLE and "FAIL" in err_s,
            "rc=%s" % rc)

    n = len(cases)
    n_ok = sum(1 for c in cases if c[1])
    fails = [c[0] for c in cases if not c[1]]
    if fails:
        print("自证 %d/%d 例不符：%s" % (n_ok, n, fails), flush=True)
        print("SELFTEST_VERDICT=FAIL", flush=True)
        print("ALL FAIL", flush=True)
        return RC_FAIL
    print("自证 %d/%d 例全过（夹具逐个真跑；零网络）" % (n_ok, n), flush=True)
    print("SELFTEST_VERDICT=PASS", flush=True)
    print("ALL PASS", flush=True)
    return RC_OK


def build_parser():
    ap = argparse.ArgumentParser(
        description="runner-bootstrap-watchdog — 引导看门狗可审计 CLI（SR-025）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "挂死 = 最新 Worker 文件名时间戳年龄 > 12min 且无作业步骤标记。\n"
            "  --check DIR            扫描 diag 目录（0 健康 / 1 挂死 / 2 不可证）\n"
            "  --recover-cmd TEXT     恢复命令（exec 形）\n"
            "  --exec                 挂死时真跑恢复；缺省 dry-run 只打印\n"
            "  --selftest             夹具逐个真跑\n"
        ),
    )
    ap.add_argument("--selftest", action="store_true",
                    help="夹具逐个真跑（子进程跑本件）")
    ap.add_argument("--check", metavar="DIAG_DIR", default=None,
                    help="diag 目录（只扫一层 Worker 件）")
    ap.add_argument("--exec", dest="do_exec", action="store_true",
                    help="挂死时真跑 --recover-cmd（缺省 dry-run）")
    ap.add_argument("--recover-cmd", dest="recover_cmd", default=None,
                    help="恢复命令（shlex 拆分后 exec）")
    ap.add_argument("--now-epoch", dest="now_epoch", type=float, default=None,
                    help="审计钉：冻结墙钟（夹具用）")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.selftest:
        if args.check or args.do_exec or args.recover_cmd:
            err("FAIL 用法：--selftest 独用，不搭 --check/--exec/--recover-cmd")
            return RC_UNPROVABLE
        return run_selftest()
    if not args.check:
        ap.print_usage()
        err("FAIL 用法：须 --check DIR 或 --selftest")
        return RC_UNPROVABLE
    if args.do_exec and not args.recover_cmd:
        err("FAIL 用法：--exec 须同时给 --recover-cmd")
        return RC_UNPROVABLE
    now = now_epoch(args.now_epoch)
    return emit_check(args.check, now, args.recover_cmd, args.do_exec)


if __name__ == "__main__":
    raise SystemExit(main())
