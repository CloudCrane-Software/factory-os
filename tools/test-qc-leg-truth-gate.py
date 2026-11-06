#!/usr/bin/env python3
"""test-qc-leg-truth-gate.py — 质量卡轮换腿的成败判据门（2026-11-03 RT 修复批）

被钉住的结构性缺陷（RT「OBS回头」确证发现，本门为常驻机检面）：
  ① tools/quality-cards.py 逐项失败（过闸挂/推送挂）时**退出码恒 0**——失败只进
     stdout JSON 的 ok/summary.failed；进程却「成功」返回。
  ② 唯一在役调用者 tools/factory-scheduler.py:_quality_cards_supply 取 stdout **末行**
     当摘要——本腿打印的是 indent=1 的多行 JSON，末行恒为「}」；且 ok 只看
     returncode（恒 0）→ 腿全败也记 acts=qc:+、变更日志恒记「已触发：}」。
  两者相乘 = 轮换腿的成败结构性不可判（本批成功与「全批失败」在调度中枢读数上
  完全同形）。

本门三组断言（全 hermetic：零网络、零 ssh、零门户、零生产写入）：
  A 组 产侧退出码：成功→0；有失败项→非 0（3）且 JSON ok=false、failed 计数如实；
                dry-run 计划态→0（不是失败）；失败时 stderr 有提示、stdout 仍可解析。
  B 组 消费侧判读：rc=0∧JSON ok=true→qc:+ 且 out 含逐腿计数（非「}」）；
                全败（任一口径：修前 rc=0+ok=false / 修后 rc=3+ok=false）→qc:fail
                且变更日志写「触发失败」而非「已触发」；stdout 非预期 JSON → fail-loud
                判失败；rc≠0 即便 JSON ok=true 也判失败。
  C 组 判别力（负向自检）：把缺陷注回副本（产侧 return 3→0；消费侧解析→取末行），
                本门同一套探针**必须**判它红——否则本门自己已失明（防「门恒绿」）。

用法：python3 tools/test-qc-leg-truth-gate.py [--keep]
退出码：0 全过；1 断言失败；2 前置不满足（被测件不在位）。
临时目录建在 $HOME 下自建目录（/tmp 配额有限，硬纪律），pid 后缀互不踩踏，完工即删。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from importlib.machinery import SourceFileLoader

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
TOOLS = os.path.join(WS, "tools")
QC = os.environ.get("QCLEG_QC") or os.path.join(TOOLS, "quality-cards.py")
FS = os.environ.get("QCLEG_FS") or os.path.join(TOOLS, "factory-scheduler.py")
SCRATCH = os.path.expanduser("~/qc-leg-truth-scratch.%d" % os.getpid())

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

RESULTS = []

# quality-cards.py 的 kind → 生成函数名映射（main() 的分派口径，见 quality-cards.py:1277-1284）
GEN_NAME = {"verify": "gen_verify_r3", "arbitrate": "gen_arbitrate", "distill": "gen_distill"}


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)
    RESULTS.append(("PASS", msg))


def note(msg):
    RESULTS.append(("NOTE", msg))


def load(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


# --------------------------------------------------------------- 探针 A：产侧退出码
def probe_qc(qc_path, items, kind="verify", extra_args=()):
    """跑一次 quality-cards.py（生成器全打桩），返回 (rc, stdout, stderr, json_doc)。

    生成器打桩：dedup_legs / ro_connect / _load 全部替身 → 零网络零 ssh 零写生产面；
    gen_<kind> 替身返回给定 items → 只验 main() 的「汇总→退出码」这一段真逻辑。
    """
    qc = load("qc_leg_probe_%d" % os.getpid(), qc_path)
    qc.dedup_legs = lambda: {"legs": {k: set() for k in ("evidence-cache", "task-seeds",
                                                         "gov", "submitted")},
                             "used": set(), "names_local": set(), "names_gov": set(),
                             "gov_reachable": False}
    qc.ro_connect = lambda p: None
    qc._load = lambda n, p: types.SimpleNamespace()
    setattr(qc, GEN_NAME[kind], lambda *a, **k: list(items))
    argv = ["quality-cards.py", "--kind", kind, "--dry-run", "--quiet"] + list(extra_args)
    old_argv, old_out, old_err = sys.argv, sys.stdout, sys.stderr
    out_buf, err_buf = [], []
    sys.argv = argv
    sys.stdout = types.SimpleNamespace(write=lambda s: out_buf.append(s), flush=lambda: None)
    sys.stderr = types.SimpleNamespace(write=lambda s: err_buf.append(s), flush=lambda: None)
    try:
        rc = qc.main()
    finally:
        sys.argv, sys.stdout, sys.stderr = old_argv, old_out, old_err
    so, se = "".join(out_buf), "".join(err_buf)
    doc = None
    try:
        doc = json.loads(so[so.index("{"):])
    except Exception:
        pass
    return rc, so, se, doc


# --------------------------------------------------------------- 探针 B：消费侧判读
def probe_fs(fs_path, rc, stdout_text, scratch):
    """跑一次调度中枢的质量卡腿（子进程打桩），返回 (acts, out, changelog_text)。"""
    env = dict(os.environ)
    env["FS_STATE"] = os.path.join(scratch, "state.json")
    env["FS_LOG"] = os.path.join(scratch, "fs.log")
    env["FS_CHANGELOG"] = os.path.join(scratch, "changelog.md")
    env["FS_QUALITY_CARDS_LOCK"] = os.path.join(scratch, "qc.lock")
    env["FS_QUALITY_CARDS"] = QC
    old = {k: os.environ.get(k) for k in env if k.startswith("FS_")}
    os.environ.update(env)
    try:
        fs = load("fs_leg_probe_%d" % os.getpid(), fs_path)
        fs._quality_cards_in_flight = lambda: (False, "")
        fs.sh = lambda cmd, timeout=90: subprocess.CompletedProcess(
            cmd, rc, stdout=stdout_text, stderr="")
        st = {"supply": {"last_quality_cards_ts": 0}}
        acts = fs._quality_cards_supply(st, "门探针")
        out = (st.get("supply") or {}).get("last_quality_cards_out")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    clog = ""
    p = os.path.join(scratch, "changelog.md")
    if os.path.exists(p):
        rows = [ln for ln in open(p, encoding="utf-8").read().splitlines() if ln.strip()]
        clog = rows[-1] if rows else ""      # 只看本探针刚写的那一行（前面探针的行不算）
    return acts, out, clog


def qc_stdout(items_by_leg):
    """造一份与 quality-cards.py 打印形状同构的 stdout（indent=1 多行 JSON）。"""
    summary = {}
    ok_all = True
    for leg, items in items_by_leg.items():
        made = [x for x in items if x.get("ok") and not x.get("skipped")]
        failed = [x for x in items if not x.get("ok")]
        ok_all = ok_all and not failed
        summary[leg] = {"generated": len(made), "skipped_existing": 0,
                        "dry_run_planned": 0, "failed": len(failed), "cards": []}
    return json.dumps({"ok": ok_all, "dry_run": False, "summary": summary},
                      ensure_ascii=False, indent=1), ok_all


# --------------------------------------------------------------- A 组
def group_a():
    ok_items = [{"ok": True, "card_id": "kb-verify-probe-r3", "arxiv": "2610.11111"}]
    bad_items = [{"ok": False, "card_id": "kb-verify-probe-r3",
                  "gate": ["L4 证据缓存缺摘要"], "arxiv": "2610.11111"}]

    rc, so, se, doc = probe_qc(QC, ok_items)
    check(rc == 0, "A1 全成功 → 退出码 0（实测 rc=%s）" % rc)
    check(doc is not None and doc.get("ok") is True,
          "A1 全成功 → stdout JSON ok=true（实测 %r）" % (doc or {}).get("ok"))
    check(doc is not None and set(["ok", "dry_run", "summary"]) <= set(doc.keys()),
          "A1 stdout JSON 形状不变（ok/dry_run/summary 三键在位）")

    rc, so, se, doc = probe_qc(QC, bad_items)
    check(rc != 0, "A2 有失败项 → 退出码非 0（实测 rc=%s）" % rc)
    check(doc is not None and doc.get("ok") is False,
          "A2 有失败项 → stdout JSON ok=false（实测 %r）" % (doc or {}).get("ok"))
    failed_n = ((doc or {}).get("summary", {}).get("verify", {}) or {}).get("failed")
    check(failed_n == 1, "A2 summary.failed 如实计数（实测 %r，期望 1）" % failed_n)
    check("失败" in se, "A2 失败时 stderr 有提示（不静默）：%r" % se.strip()[:80])

    # dry-run 计划态：项带 dry_run=True 但 ok=True → 不是失败，退出码须为 0
    rc, so, se, doc = probe_qc(QC, [{"ok": True, "card_id": "kb-verify-probe-r3",
                                      "dry_run": True}])
    check(rc == 0, "A3 dry-run 计划态 → 退出码 0（实测 rc=%s）" % rc)


# --------------------------------------------------------------- B 组
def group_b():
    scratch = os.path.join(SCRATCH, "b")
    os.makedirs(scratch, exist_ok=True)

    good, _ = qc_stdout({"verify": [{"ok": True}]})
    acts, out, clog = probe_fs(FS, 0, good, scratch)
    check(acts == ["qc:+"], "B1 成功腿 → acts=['qc:+']（实测 %r）" % (acts,))
    check(out != "}" and "ok=true" in str(out),
          "B1 成功腿 → 摘要非「}」且含 ok=true（实测 %r）" % (out,))
    check("生成" in str(out), "B1 成功腿 → 摘要含逐腿计数（实测 %r）" % (out,))
    check("已触发" in clog, "B1 成功腿 → 变更日志记「已触发」")

    # 全败：两种口径都要判失败（修前 rc=0+ok=false / 修后 rc=3+ok=false）
    bad, _ = qc_stdout({"verify": [{"ok": False}] * 7})
    for rc_in in (0, 3):
        acts, out, clog = probe_fs(FS, rc_in, bad, scratch)
        check(acts == ["qc:fail"],
              "B2 全败(rc=%s) → acts=['qc:fail']（实测 %r）" % (rc_in, acts))
        check("ok=false" in str(out) and "失败7" in str(out),
              "B2 全败(rc=%s) → 摘要含 ok=false 与失败计数（实测 %r）" % (rc_in, out))
        check("触发失败" in clog and "已触发" not in clog,
              "B2 全败(rc=%s) → 变更日志记「触发失败」而非「已触发」（实测 %r）"
              % (rc_in, clog.strip()[-120:]))

    # stdout 非预期 JSON → fail-loud（绝不把「读不出」当成功）
    acts, out, clog = probe_fs(FS, 0, "boom\nnot json at all\n", scratch)
    check(acts == ["qc:fail"], "B3 stdout 非预期 JSON → 判失败（实测 %r）" % (acts,))
    check("不可判" in str(out), "B3 stdout 非预期 JSON → 摘要点明不可判（实测 %r）" % (out,))

    # rc≠0 即便 JSON 说 ok=true 也判失败
    acts, out, clog = probe_fs(FS, 3, good, scratch)
    check(acts == ["qc:fail"], "B4 rc≠0 → 判失败（实测 %r）" % (acts,))

    # 空 stdout（子进程什么都没打）→ 判失败，不得当成功
    acts, out, clog = probe_fs(FS, 0, "", scratch)
    check(acts == ["qc:fail"], "B5 空 stdout → 判失败（实测 %r）" % (acts,))


# --------------------------------------------------------------- C 组：判别力（负向自检）
def tamper_qc(src, dst):
    """把「有失败项 → return 3」注回「return 0」（=修前恒 0 退出码）。"""
    s = open(src, encoding="utf-8").read()
    old = "        print(f\"质量卡工序失败 {n_failed} 项（逐项见上 JSON summary.failed）\", file=sys.stderr)\n        return 3"
    new = "        print(f\"质量卡工序失败 {n_failed} 项（逐项见上 JSON summary.failed）\", file=sys.stderr)\n        return 0"
    if old not in s:
        raise Fail("无法定位 quality-cards.py 的失败退出码片段（源码形态已变？）")
    open(dst, "w", encoding="utf-8").write(s.replace(old, new))
    return dst


def tamper_fs(src, dst):
    """把「解析 JSON 摘要」注回「取 stdout 末行 + 只看 returncode」（=修前口径）。"""
    s = open(src, encoding="utf-8").read()
    old = "            out, ok = _qc_leg_out(r2.stdout, r2.returncode)"
    new = ("            out = ((r2.stdout or \"\").strip().splitlines() "
           "or [f\"exit={r2.returncode}\"])[-1][:200]\n"
           "            ok = r2.returncode == 0")
    if old not in s:
        raise Fail("无法定位 factory-scheduler.py 的质量卡腿取样行（源码形态已变？）")
    open(dst, "w", encoding="utf-8").write(s.replace(old, new))
    return dst


def group_c():
    scratch = os.path.join(SCRATCH, "c")
    os.makedirs(scratch, exist_ok=True)
    bad_items = [{"ok": False, "card_id": "kb-verify-probe-r3",
                  "gate": ["L4 证据缓存缺摘要"]}]

    tqc = tamper_qc(QC, os.path.join(scratch, "tampered-quality-cards.py"))
    rc, so, se, doc = probe_qc(tqc, bad_items)
    check(rc == 0 and doc is not None and doc.get("ok") is False,
          "C1 判别力：把退出码注回 0 后本门探针判红（实测 rc=%s，ok=%r）"
          % (rc, (doc or {}).get("ok")))

    tfs = tamper_fs(FS, os.path.join(scratch, "tampered-factory-scheduler.py"))
    bad, _ = qc_stdout({"verify": [{"ok": False}] * 7})
    acts, out, clog = probe_fs(tfs, 0, bad, scratch)
    check(acts == ["qc:+"] and out == "}",
          "C2 判别力：把取样注回末行后本门探针判红（实测 acts=%r out=%r）" % (acts, out))


def main():
    ap = argparse.ArgumentParser(description="质量卡轮换腿成败判据门")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    a = ap.parse_args()

    for p in (QC, FS):
        if not os.path.exists(p):
            print("前置不满足：被测件不在位 %s" % p, file=sys.stderr)
            return EXIT_ENV

    os.makedirs(SCRATCH, exist_ok=True)
    try:
        for g in (group_a, group_b, group_c):
            try:
                g()
            except Fail as e:
                print("FAIL %s：%s" % (g.__name__, e), file=sys.stderr)
                for st, m in RESULTS:
                    print("  %-4s %s" % (st, m))
                return EXIT_FAIL
        for st, m in RESULTS:
            print("  %-4s %s" % (st, m))
        print("PASS %d 组断言（全绿）" % len(RESULTS))
        return EXIT_OK
    finally:
        if not a.keep:
            shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
