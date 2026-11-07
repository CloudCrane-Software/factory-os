#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planner-call-recon.py — 失败调用记账对账器（[真锚][D-136] · factory-os#151）

读什么（只读 artifact，零网络、零工作流改动）：
  artifact 目录内的成对件——
    `*-planner-raw.json`（planner 单跑原始读数：model/attempts/calls[]；
      calls[] 含**全部尝试**——成功与失败都在内）；
    `*-planner-call-log.json`（调用账本：**只记成功调用**——HTTP 200 之后
      才写入）。
  按文件名主干（run）配对；配对不齐 ⇒ 点名不可证（不计入分母）。
  （另兼容无前缀的裸名 planner-raw.json / planner-call-log.json——单跑 artifact
    目录直接落地即可读；配对语义不变。）

算什么（判据 CST-6 / J-39，阈值=0）：
  per-run 缺失 = max(0, raw.attempts − log 条目数)
  窗汇总 = Σ per-run：expected_calls / recorded_calls / missing_calls /
          missing_wall_ms / missing_prompt_tk / missing_completion_tk
  语义坐标（只读作证据，本器不改记账逻辑）：
    .github/workflows/planner-core.yml:1317-1322（meta.attempts=已尝试次数，
      每轮循环开始置位；max_attempts=2 硬顶）
    .github/workflows/planner-core.yml:1339-1341（HTTP 错误路径 exit 4：
      只写 planner-raw.json 即退出——不写账本）
    .github/workflows/planner-core.yml:1350-1352（传输失败路径 exit 5：同）
    .github/workflows/planner-core.yml:1372-1377（成功写入位：HTTP 200 之后
      才 append 进 planner-call-log.json）
  ⇒ 504 风暴里烧掉的真调用（每次至多 300s 超时+20s 睡）既不在次数帽里也不在
    token 账本里；本器把这个缺口量化成读数面（椅子错位 CST-2 的量化面）。

模式：
  --dir DIR [--out PATH]   读数（exit 0=计算成功——读数本身可示 missing>0）
  --gate --dir DIR         判闸（阈值=0：missing>0 ⇒ exit 1；存在不可证 run
                            ⇒ exit 1 fail-closed——未知≠0，禁假绿）
  --selftest               夹具自证（零网络）：失败窗/干净窗/坏行三夹具
                           ＋三个临时目录边例（配对不齐/attempts 缺席/
                           成功调用入账丢失）

退出码：0=绿或计算成功；1=判闸红（missing>0 或不可证 run 在场）；2=fail-loud
  （目录缺席、非 JSON 坏行、结构非法——禁吞禁猜，禁 SKIP 冒充）。

纪律（卡面禁项照抄进代码）：
  P2 禁把漏记当全量：账本仅记成功调用——读数件必带 caliber 标注；
  P3 artifact 缺席 ⇒ 未知≠0：不可证 run 逐条点名、不计入分母；
  P4 禁假绿：阈值恒 0（THRESHOLD 常量，不开放 CLI 配置）；坏行 fail-loud
     exit 2，禁为刷绿放宽口径。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 常量

RAW_SUFFIX = "-planner-raw.json"
LOG_SUFFIX = "-planner-call-log.json"
RAW_BARE = "planner-raw.json"
LOG_BARE = "planner-call-log.json"

THRESHOLD = 0  # 判据 J-39：缺失调用数阈值=0（现非 0 ⇒ 判红）。禁配置化。

SCHEMA = "planner-call-recon/1"
CARD = "[真锚][D-136] factory-os#151（宪章域1 CST-6 / 判据 J-39）"

# P2 口径标注（CST-1 同款）：账本仅记成功调用——禁把漏记当全量。
CALIBER = (
    "调用账本 planner-call-log.json 仅记成功调用（HTTP 200 之后才写入；失败路径"
    "只写 planner-raw.json 即退出——.github/workflows/planner-core.yml:1339-1352"
    " 与 :1372-1377）。缺失调用数=应入账而未入账的失败/未入账调用，是对账差值、"
    "不是全部调用的全量普查；禁把漏记当全量，禁读作调用失败率。"
)
# 墙钟/token 归因口径：失败调用在 API 错误路径不回报 usage。
ATTRIBUTION_NOTE = (
    "missing_wall_ms=未入账调用的 raw.calls[].ms 之和（不含 20s 睡隔）；"
    "missing_prompt_tk/missing_completion_tk 只累计 raw 中带 usage 的未入账"
    "调用——API 错误路径的失败调用不回报 usage，计 missing_calls_without_usage，"
    "禁把 token 读数 0 读作无成本。"
)
# P3 口径：不可证 run 不计入分母、逐条点名。
UNVERIFIABLE_NOTE = (
    "unverifiable_runs（配对不齐/attempts 缺席）不计入分母、逐条点名——"
    "未知≠0；判闸模式下不可证 run 在场即 fail-closed 判红。"
)

FIXTURE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "planner-call-recon")


class ReconError(Exception):
    """fail-loud（exit 2）：输入不可证——坏行/结构非法/目录缺席。禁吞禁猜。"""


# ---------------------------------------------------------------- 读数内核

def load_json_file(path):
    """读 JSON 件；非 JSON/非 UTF-8/读不动 ⇒ ReconError（坏行 fail-loud exit 2）。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise ReconError("读不动 %s：%s" % (path, e))
    except UnicodeDecodeError as e:
        raise ReconError("非 UTF-8（坏行）%s：%s" % (path, e))
    try:
        return json.loads(raw)
    except ValueError as e:
        raise ReconError("非 JSON（坏行）%s：%s" % (path, e))


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def reconcile_pair(stem, raw_path, log_path):
    """对账一对 raw/log；返回 per-run 读数 dict。坏行 ⇒ ReconError。"""
    raw = load_json_file(raw_path)
    if not isinstance(raw, dict):
        raise ReconError("raw 顶层非对象 %s" % raw_path)
    log = load_json_file(log_path)
    if not isinstance(log, list):
        raise ReconError("log 顶层非数组 %s" % log_path)
    for e in log:
        if not isinstance(e, dict):
            raise ReconError("log 条目非对象（坏行）%s：%r" % (log_path, e))

    calls = raw.get("calls")
    if calls is None:
        calls = []
    if not isinstance(calls, list):
        raise ReconError("raw.calls 非数组 %s" % raw_path)
    for c in calls:
        if not isinstance(c, dict):
            raise ReconError("raw.calls 条目非对象（坏行）%s：%r" % (raw_path, c))

    attempts = _int_or_none(raw.get("attempts"))
    run = {
        "run": stem if stem else "(bare)",
        "raw_file": os.path.basename(raw_path),
        "log_file": os.path.basename(log_path),
        "run_ids": sorted({str(e.get("run_id")) for e in log
                           if e.get("run_id") is not None}),
        "attempts": attempts,
        "recorded": len(log),
        "notes": [],
    }
    if attempts is None or attempts < 0:
        # P3：attempts 缺席 ⇒ 不可证（不计入分母，点名）。
        run["verifiable"] = False
        run["reason"] = "raw.attempts 缺席或非非负整数——不可证（不计入分母）"
        return run

    # 判据公式（权威）：缺失 = max(0, attempts − log 条目数)
    missing = max(0, attempts - len(log))

    # log 条目 ↔ raw calls 按 attempt 号一对一匹配（余下的 raw 调用即未入账）
    used = set()
    unmatched = []
    for c in calls:
        a = c.get("attempt")
        idx = None
        for i, e in enumerate(log):
            if i not in used and e.get("attempt") == a:
                idx = i
                break
        if idx is None:
            unmatched.append(c)
        else:
            used.add(idx)

    # attempt 重复/不对齐的边例如实点名（不吞）
    entry_attempts = [e.get("attempt") for e in log]
    if len(set(entry_attempts)) != len(entry_attempts):
        run["notes"].append("log 条目 attempt 号重复——计数公式仍按条目数走，点名备查")
    if len(log) != len(used):
        run["notes"].append(
            "log 有条目与 raw.calls 的 attempt 不对齐（%d 条目中 %d 条目匹配不上）"
            "——点名备查，计数公式不变" % (len(log), len(log) - len(used)))

    # ms/token 归因：只归到能与「缺失计数」对上的未入账调用（按 attempt 序），
    # 对不上的残余点名 unattributed_missing（禁猜绿）
    attributed = unmatched[:missing]
    unattributed = missing - len(attributed)
    wall = 0
    ptk = 0
    ctk = 0
    no_usage = 0
    for c in attributed:
        ms = _int_or_none(c.get("ms"))
        if ms is not None:
            wall += ms
        p = _int_or_none(c.get("prompt_tk"))
        k = _int_or_none(c.get("completion_tk"))
        if p is None:
            no_usage += 1
        else:
            ptk += p
        if k is not None:
            ctk += k
    breakdown = {}
    for c in calls:
        key = str(c.get("http"))
        breakdown[key] = breakdown.get(key, 0) + 1

    run.update({
        "verifiable": True,
        "missing": missing,
        "missing_wall_ms": wall,
        "missing_prompt_tk": ptk,
        "missing_completion_tk": ctk,
        "missing_calls_without_usage": no_usage,
        "unattributed_missing": unattributed,
        "unmatched_calls": len(unmatched),
        "http_breakdown": breakdown,
    })
    if unattributed:
        run["notes"].append(
            "计数公式判缺 %d 个调用但 raw.calls 中只有 %d 个可归因——"
            "unattributed_missing=%d 如实点名" % (missing, len(attributed), unattributed))
    if len({str(e.get("run_id")) for e in log}) > 1:
        run["notes"].append(
            "log 含多个 run_id（跨跑累积账本形态）——条目数含他跑条目，"
            "计数按卡面公式走，跨跑污染风险点名备查")
    return run


def reconcile_dir(directory):
    """扫目录 ⇒ 窗汇总 + per-run 读数 dict。坏行 ⇒ ReconError（exit 2）。"""
    if not os.path.isdir(directory):
        raise ReconError("目录缺席或非目录：%s" % directory)
    raws, logs, ignored = {}, {}, []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(RAW_SUFFIX):
            raws[name[:-len(RAW_SUFFIX)]] = path
        elif name == RAW_BARE:
            raws[""] = path
        elif name.endswith(LOG_SUFFIX):
            logs[name[:-len(LOG_SUFFIX)]] = path
        elif name == LOG_BARE:
            logs[""] = path
        else:
            ignored.append(name)

    per_run, unverifiable = [], []
    for stem in sorted(set(raws) | set(logs)):
        rp, lp = raws.get(stem), logs.get(stem)
        label = stem if stem else "(bare)"
        if rp is None:
            unverifiable.append({"run": label,
                                 "reason": "配对不齐：%s 缺席（log 在场）" % RAW_BARE})
            continue
        if lp is None:
            unverifiable.append({"run": label,
                                 "reason": "配对不齐：%s 缺席（raw 在场）" % LOG_BARE})
            continue
        row = reconcile_pair(stem, rp, lp)
        if row.get("verifiable"):
            per_run.append(row)
        else:
            unverifiable.append({"run": row["run"], "reason": row["reason"],
                                 "raw_file": row["raw_file"],
                                 "log_file": row["log_file"]})

    def s(field):
        return sum(r[field] for r in per_run)

    window = {
        "runs": len(per_run),
        "expected_calls": s("attempts"),
        "recorded_calls": s("recorded"),
        "missing_calls": s("missing"),
        "missing_wall_ms": s("missing_wall_ms"),
        "missing_prompt_tk": s("missing_prompt_tk"),
        "missing_completion_tk": s("missing_completion_tk"),
        "missing_calls_without_usage": s("missing_calls_without_usage"),
        "unattributed_missing": s("unattributed_missing"),
        "unverifiable_runs": unverifiable,
        "threshold": THRESHOLD,
    }
    window["verdict"] = ("red" if (window["missing_calls"] > THRESHOLD
                                   or unverifiable) else "green")
    return {
        "schema": SCHEMA,
        "card": CARD,
        "dir": directory,
        "caliber": CALIBER,
        "attribution_note": ATTRIBUTION_NOTE,
        "unverifiable_note": UNVERIFIABLE_NOTE,
        "window": window,
        "per_run": per_run,
        "ignored_files": ignored,
    }


def gate(reading):
    """判闸（阈值=0）。返回 (rc, 人行可读判定串)。0=绿；1=红；坏行在外层已 exit 2。"""
    w = reading["window"]
    lines = [
        "planner-call-recon 判闸：runs=%d expected=%d recorded=%d missing=%d "
        "（missing_wall_ms=%d missing_prompt_tk=%d missing_completion_tk=%d "
        "without_usage=%d unattributed=%d）" % (
            w["runs"], w["expected_calls"], w["recorded_calls"], w["missing_calls"],
            w["missing_wall_ms"], w["missing_prompt_tk"], w["missing_completion_tk"],
            w["missing_calls_without_usage"], w["unattributed_missing"]),
        "阈值=%d（判据 J-39，禁配置化放宽）" % THRESHOLD,
    ]
    if w["missing_calls"] > THRESHOLD:
        for r in reading["per_run"]:
            if r["missing"] > 0:
                lines.append(
                    "  判红 run=%s：attempts=%s recorded=%s missing=%s "
                    "http=%s run_ids=%s" % (
                        r["run"], r["attempts"], r["recorded"], r["missing"],
                        json.dumps(r["http_breakdown"], ensure_ascii=False),
                        r["run_ids"]))
        lines.append("判定：红（missing>0——应入账而未入账的调用被点名；fail-closed 不放宽）")
        return 1, "\n".join(lines)
    if w["unverifiable_runs"]:
        for u in w["unverifiable_runs"]:
            lines.append("  不可证 run=%s：%s" % (u["run"], u["reason"]))
        lines.append("判定：红（不可证 run 在场——未知≠0，禁假绿）")
        return 1, "\n".join(lines)
    lines.append("判定：绿（missing=0 且零不可证 run）")
    return 0, "\n".join(lines)


def render(reading):
    """人行可读读数摘要（--dir 模式 stdout）。"""
    w = reading["window"]
    lines = [
        "planner-call-recon 读数：dir=%s" % reading["dir"],
        "runs=%d expected_calls=%d recorded_calls=%d missing_calls=%d "
        "missing_wall_ms=%d missing_prompt_tk=%d missing_completion_tk=%d "
        "missing_calls_without_usage=%d unattributed_missing=%d" % (
            w["runs"], w["expected_calls"], w["recorded_calls"], w["missing_calls"],
            w["missing_wall_ms"], w["missing_prompt_tk"], w["missing_completion_tk"],
            w["missing_calls_without_usage"], w["unattributed_missing"]),
        "caliber：%s" % CALIBER,
    ]
    for r in reading["per_run"]:
        lines.append(
            "  run=%s attempts=%s recorded=%s missing=%s http=%s run_ids=%s%s" % (
                r["run"], r["attempts"], r["recorded"], r["missing"],
                json.dumps(r["http_breakdown"], ensure_ascii=False), r["run_ids"],
                (" notes=" + ";".join(r["notes"])) if r["notes"] else ""))
    for u in w["unverifiable_runs"]:
        lines.append("  不可证 run=%s：%s" % (u["run"], u["reason"]))
    if reading["ignored_files"]:
        lines.append("  忽略件（非本器输入形态）：%s" % ", ".join(reading["ignored_files"]))
    lines.append("attribution：%s" % ATTRIBUTION_NOTE)
    lines.append("unverifiable：%s" % UNVERIFIABLE_NOTE)
    return "\n".join(lines)


def write_reading(reading, out_path):
    d = os.path.dirname(os.path.abspath(out_path))
    if d and not os.path.isdir(d):
        raise ReconError("--out 目录缺席：%s" % d)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reading, f, ensure_ascii=False, indent=1)
        f.write("\n")


# ---------------------------------------------------------------- 自证

def _mk_pair(d, stem, attempts, calls, entries, raw_name=None, log_name=None):
    rp = os.path.join(d, raw_name or (stem + RAW_SUFFIX))
    lp = os.path.join(d, log_name or (stem + LOG_SUFFIX))
    with open(rp, "w", encoding="utf-8") as f:
        json.dump({"model": "fixture-model", "attempts": attempts, "calls": calls},
                  f, ensure_ascii=False)
    with open(lp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    return rp, lp


def _entry(run_id, attempt, http=200, ptk=100, ctk=50):
    return {"hour": "2026110713", "run_id": run_id, "attempt": attempt,
            "http": http, "prompt_tk": ptk, "completion_tk": ctk}


def selftest():
    """三夹具（失败窗/干净窗/坏行）＋三个临时目录边例。返回 (fails, total)。"""
    fails = []

    def check(name, cond, detail=""):
        if not cond:
            fails.append("%s %s" % (name, detail))

    # 夹具一：失败窗（raw attempts=2、log 零条目 ⇒ missing=2）
    fw = os.path.join(FIXTURE_ROOT, "failed-window")
    r = reconcile_dir(fw)
    w = r["window"]
    check("失败窗.missing=2", w["missing_calls"] == 2, "得 %r" % w["missing_calls"])
    check("失败窗.expected=2", w["expected_calls"] == 2, "得 %r" % w["expected_calls"])
    check("失败窗.recorded=0", w["recorded_calls"] == 0, "得 %r" % w["recorded_calls"])
    check("失败窗.wall=600000", w["missing_wall_ms"] == 600000,
          "得 %r" % w["missing_wall_ms"])
    check("失败窗.verdict=red", w["verdict"] == "red", "得 %r" % w["verdict"])
    rc, _ = gate(r)
    check("失败窗.gate=rc1", rc == 1, "得 %r" % rc)

    # 夹具二：干净窗（全 200 全入账 ⇒ missing=0）
    cw = os.path.join(FIXTURE_ROOT, "clean-window")
    r = reconcile_dir(cw)
    w = r["window"]
    check("干净窗.missing=0", w["missing_calls"] == 0, "得 %r" % w["missing_calls"])
    check("干净窗.verdict=green", w["verdict"] == "green", "得 %r" % w["verdict"])
    rc, _ = gate(r)
    check("干净窗.gate=rc0", rc == 0, "得 %r" % rc)

    # 夹具三：坏行（非 JSON ⇒ fail-loud exit 2）——库内抛 + 子进程实测
    bl = os.path.join(FIXTURE_ROOT, "bad-line")
    try:
        reconcile_dir(bl)
        check("坏行.库内抛", False, "未抛 ReconError")
    except ReconError:
        pass
    for extra in ([], ["--gate"]):
        p = subprocess.run(
            [sys.executable, "-I", os.path.abspath(__file__), "--dir", bl] + extra,
            capture_output=True, text=True)
        check("坏行.子进程%s=rc2" % ("+gate" if extra else ""),
              p.returncode == 2, "得 rc=%r stderr=%s" % (p.returncode, p.stderr[-200:]))

    # 边例一（临时目录）：配对不齐 ⇒ 点名不可证、不计入分母、判闸 fail-closed
    d = tempfile.mkdtemp(prefix="d136-selftest-")
    try:
        _mk_pair(d, "run-a", 2,
                 [{"attempt": 1, "http": 200, "ms": 10, "prompt_tk": 5,
                   "completion_tk": 5},
                  {"attempt": 2, "http": 200, "ms": 10, "prompt_tk": 5,
                   "completion_tk": 5}],
                 [_entry("1", 1), _entry("1", 2)])
        with open(os.path.join(d, "run-b" + RAW_SUFFIX), "w", encoding="utf-8") as f:
            json.dump({"attempts": 2, "calls": []}, f)
        r = reconcile_dir(d)
        w = r["window"]
        check("配对不齐.点名", len(w["unverifiable_runs"]) == 1
              and w["unverifiable_runs"][0]["run"] == "run-b",
              "得 %r" % w["unverifiable_runs"])
        check("配对不齐.不计分母", w["expected_calls"] == 2,
              "得 %r" % w["expected_calls"])
        check("配对不齐.verdict=red", w["verdict"] == "red")
        rc, _ = gate(r)
        check("配对不齐.gate=rc1", rc == 1, "得 %r" % rc)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 边例二（临时目录）：成功调用入账丢失（cache evict 形）⇒ missing=1 且 token 入读数
    d = tempfile.mkdtemp(prefix="d136-selftest-")
    try:
        _mk_pair(d, "run-c", 1,
                 [{"attempt": 1, "http": 200, "ms": 44417, "prompt_tk": 15621,
                   "completion_tk": 6906, "finish_reason": "stop"}],
                 [])
        r = reconcile_dir(d)
        w = r["window"]
        check("入账丢失.missing=1", w["missing_calls"] == 1, "得 %r" % w["missing_calls"])
        check("入账丢失.ptk", w["missing_prompt_tk"] == 15621,
              "得 %r" % w["missing_prompt_tk"])
        check("入账丢失.ctk", w["missing_completion_tk"] == 6906,
              "得 %r" % w["missing_completion_tk"])
        check("入账丢失.wall", w["missing_wall_ms"] == 44417,
              "得 %r" % w["missing_wall_ms"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 边例三（临时目录）：attempts 缺席 ⇒ 不可证点名（不进 per_run）
    d = tempfile.mkdtemp(prefix="d136-selftest-")
    try:
        _mk_pair(d, "run-d", None,
                 [{"attempt": 1, "http": 200, "ms": 10}], [_entry("4", 1)])
        # _mk_pair 写 attempts=None ⇒ 手工改写为缺键形态
        rp = os.path.join(d, "run-d" + RAW_SUFFIX)
        with open(rp, "w", encoding="utf-8") as f:
            json.dump({"model": "fixture-model", "calls": [
                {"attempt": 1, "http": 200, "ms": 10}]}, f)
        r = reconcile_dir(d)
        w = r["window"]
        check("attempts缺席.不可证", len(w["unverifiable_runs"]) == 1
              and "attempts" in w["unverifiable_runs"][0]["reason"],
              "得 %r" % w["unverifiable_runs"])
        check("attempts缺席.runs=0", w["runs"] == 0, "得 %r" % w["runs"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    return fails, 6 + 3 + 3 + 3 + 2 + 2  # 夹具 6+3+3、边例 3+2+2 项断言


# ---------------------------------------------------------------- CLI

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        fails, total = selftest()
        if fails:
            print("FAIL selftest %d/%d 过：" % (total - len(fails), total))
            for f in fails:
                print("  " + f)
            return 1
        print("selftest %d/%d 过（失败窗 missing=2 判红/干净窗 missing=0 放行/"
              "坏行 fail-loud exit 2（库内+子进程双测）/配对不齐点名不可证且不计分母/"
              "成功调用入账丢失 missing=1 且 token 入读数/attempts 缺席不可证）" % (total, total))
        return 0

    p = argparse.ArgumentParser(
        prog="planner-call-recon.py",
        description="失败调用记账对账器（D-136）：planner-raw.json attempts × "
                    "planner-call-log.json 缺失调用数，阈值=0（判据 J-39）")
    p.add_argument("--dir", required=True,
                   help="artifact 目录（*-planner-raw.json 与 *-planner-call-log.json 按 run 配对）")
    p.add_argument("--out", help="读数 JSON 落盘路径（--dir 模式）")
    p.add_argument("--gate", action="store_true",
                   help="判闸：阈值=0，missing>0 或不可证 run 在场 ⇒ exit 1")
    args = p.parse_args(argv)

    try:
        reading = reconcile_dir(args.dir)
    except ReconError as e:
        print("FAIL-LOUD（exit 2）：%s" % e, file=sys.stderr)
        return 2

    if args.gate:
        rc, msg = gate(reading)
        print(msg)
        if args.out:
            try:
                write_reading(reading, args.out)
                print("读数落盘：%s" % args.out)
            except ReconError as e:
                print("FAIL-LOUD（exit 2）：%s" % e, file=sys.stderr)
                return 2
        return rc

    print(render(reading))
    if args.out:
        try:
            write_reading(reading, args.out)
        except ReconError as e:
            print("FAIL-LOUD（exit 2）：%s" % e, file=sys.stderr)
            return 2
        print("读数落盘：%s" % args.out)
    else:
        print(json.dumps(reading, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
