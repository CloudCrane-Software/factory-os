#!/usr/bin/env python3
"""test-sil-verdict-probe-outleg.py — SIL 裁决产出腿常驻门「⑥ 产出腿前进断言」回归

背景（红队确证发现，2026-11-02，修复员-14）：《目的-监测项映射.md》G-SIL 行以
sil-verdict-probe 当作「产出腿门」的达成证据，而该门 v1.1 前的绿判据只落在**输入
信任面**（≥1 镜像源可信），**不证明产出腿在产出**——源可信但守护签名不前进（无新
终态单可裁/聚合失败/判定门失败/策略册不可用）时，产出腿零产出而门照绿；逃逸台账
RT-E88 拦截机制②「产出腿 dead-man 断言」自认「机制②③④未见」。
修法（探针 v1.2）：在信任面对账①②③④⑤之后**追加**⑥产出腿前进断言——
  A 积压（有活未产出）：守护本轮算出的逐源镜像签名 ≠ 已签收签名 ⇒ 红；
  B 死手（空转环）：轮在前进 ∧ 末次裁决/回写长期零(>3h) ∧ 拒用持续 ⇒ 红；
既有判据①②③④⑤一字未删（见 S1/S2/S3 源码自证）。
本文件只测⑥与其退出码语义（信任面判据由 test-sil-verdict-probe.py 覆盖，两门互补）。

检查项（函数级＝⑥ 判据纯函数 output_leg_check；CLI 级＝探针整体退出码语义）：
  F1 健康基线：全源可信 + 签名一致 + 近期有裁决 → 绿（note 含「无积压」）
  F2 积压·源被拒用（拒用致签名不前进）→ 红（A，点名源）
  F3 死手·双源拒用 + 末次裁决 5h 前 → 红（B，含「长期零产出」）
  F4 状态面无 last_round.experiments.mirror 段（STOP/老版本）→ ⑥ 跳过（不猜绿不
     猜红；note 含「读数不可得」）
  F5 积压·源可用但有活未产出（聚合失败/判定门失败/策略册不可用）→ 红（A）← 本
     发现点名的洞（源可信却零产出）
  F6 死手·部分源拒用持续 + 末次裁决 5h 前 → 红（B）
  F7 源全可信 + 无新终态单可裁 + 末次裁决 5h 前 → 绿（口径收窄：绿=产出腿「未停
     摆」，不=「此刻正在产出」——镜像终态单最近到货 2026-10-30，其后产出为零属
     该系统常态，不是故障形态）
  F8 同 F7 但存在拒用源（拒用持续）→ 红（B 接管，绿不再掩盖拒用态零产出）
  C1 状态面缺件 → rc=2（缺件红，不静默放行）
  C2 状态面坏 JSON → rc=2（不可解析红）
  C3 状态面读数过期（mtime/heartbeat 老）→ rc=1（过期不背书绿）
  C4 状态面无 mirror_ro_gate 读数 → rc=2（产出腿状态不可证）
  C5 状态面源集与守护在册源集不一致 → rc=2（读数不可证，不猜绿）
  C6 状态面无源码版本钉（在役码早于版本钉机制）→ rc=2（在役判据版本不可证）
  C7 状态面版本钉 ≠ 盘上判据源版本（两套真相并行）→ rc=2（不可对账，不猜绿）
  S1 探针源码含 ⑥ 产出腿前进断言（判据在位）
  S2 探针源码既有判据①②③④⑤ 未被删改（不弱化断言）
  S3 PASS 行带产出腿断言注记 + 口径不越权背书（绿≠「此刻正在产出」）

用法：python3 -I tools/test-sil-verdict-probe-outleg.py
退出码：0 全过；1 断言失败。
零写生产面：夹具落 $HOME 自建 scratch 目录，完工即删；探针自身只读。
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(WS, "tools", "sil-verdict-probe.py")
DAEMON = os.path.join(WS, "tools", "self-improve-loop.py")
HB_FMT = "%Y-%m-%d %H:%M:%S"
SCRATCH = os.path.join(os.path.expanduser("~"), ".tmp_test_sil_probe_outleg")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# 盘上判据源此刻的 sha256＝「盘上判据版本」权威读数（动态取，随守护源码演进）。
DISK_GATE_SHA = _sha256_file(DAEMON)


def load_daemon():
    """导入守护判据源模块（判据单一源）——夹具封条用守护在册的 seal_state 签发，
    与在役状态面同口径（探针⑧ 判据验签用的也是守护在册 verify_state_seal）。"""
    spec = importlib.util.spec_from_file_location("sil_outleg_daemon_under_test", DAEMON)
    if spec is None or spec.loader is None:
        print("  [FAIL] 守护装载：spec 构建失败 %s" % DAEMON)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DAEMON_MOD = load_daemon()

FAILS = []
NCASE = 0


def check(name, cond, detail=""):
    global NCASE
    NCASE += 1
    if cond:
        print("  [PASS] %s %s" % (name, detail), flush=True)
    else:
        print("  [FAIL] %s %s" % (name, detail), flush=True)
        FAILS.append(name)


def load_probe():
    spec = importlib.util.spec_from_file_location("sil_probe_outleg_under_test", PROBE)
    if spec is None or spec.loader is None:
        print("  [FAIL] 探针装载：spec 构建失败 %s" % PROBE)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mk_state(trusted=True, refused=None, sig_mismatch=False, out_age_s=600,
             rounds=100, with_mirror=True, started_age_s=3600, verdict=True,
             src_sha=None, with_src=True):
    """夹具状态面。trusted=两源可信；refused=被拒用源名列表；sig_mismatch=守护已
    见新终态单却签名不前进（有活未产出）；out_age_s=末次裁决距今秒数。

    src_sha/with_src＝源码版本钉读数（探针⑦ 判据的前置条件，2026-11-03）：默认带上
    「与盘上判据源一致」的版本钉（在对齐态，既有 C1–C5 断言与期望退出码一字未改）；
    with_src=False 造版本钉缺席，src_sha 传异值造两套真相并行。

    封条（探针⑧ 判据的前置条件，2026-11-03 状态面面收口批）：默认带上**守护格式的
    有效封条**（判据单一源＝守护在册 seal_state 签发）＋state_seal_ok=True——即「封条
    过、权限面闭」的对齐态；既有 C1–C7/F1–F8 断言与期望退出码**一字未改**，仅夹具
    补齐新判据的前置读数（补前置≠弱化断言：新判据本身的负例在
    tools/test-sil-verdict-probe.py 的 A12–A17）。"""
    now = time.time()
    sigs = {"exp1": "sig-exp1-1", "exp2": "sig-exp2-1"}
    computed = dict(sigs)
    if sig_mismatch:
        computed["exp1"] = "sig-exp1-2"          # 守护本轮算出的新签名（未签收）
    ro = {"exp1": True, "exp2": True}
    for k in (refused or []):
        ro[k] = False
    st = {
        "rounds": rounds,
        "heartbeat_ts": time.strftime(HB_FMT, time.localtime(now)),
        "commits": ["aaaaaaa"],
        "started_at": time.strftime(HB_FMT, time.localtime(now - started_age_s)),
        "mirror_ro_gate": ro,
        "exp_mirror_sigs": dict(sigs),
        "verdict_log": ([{"exp_id": "EXP-1", "verdict": "inconclusive",
                          "ts": time.strftime(HB_FMT, time.localtime(now - out_age_s))}]
                         if verdict else []),
    }
    if with_src:
        st["daemon_src"] = {"ver": "夹具", "sha256": src_sha or DISK_GATE_SHA,
                            "pid": 0,
                            "loaded_at": time.strftime(HB_FMT, time.localtime(now))}
    if with_mirror:
        st["last_round"] = {
            "ts": time.strftime(HB_FMT, time.localtime(now)),
            "outcome": "noop",
            "experiments": {"mirror": {
                "sigs": computed,
                "n_terminal": {"exp1": 143, "exp2": 28},
                "changed_sources": ["exp1"] if sig_mismatch else [],
                "ro_gate": {k: {"trusted": v, "reason": "夹具"} for k, v in ro.items()},
                "changed": bool(sig_mismatch),
            }},
        }
    DAEMON_MOD.seal_state(st)                 # 探针⑧ 前置：守护格式的有效封条
    st["state_seal_ok"] = True
    return st


def run_cli(state_path):
    p = subprocess.run([sys.executable, "-I", PROBE, "--state", state_path],
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def write_state(path, st):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.chmod(path, 0o600)                # 探针⑧ 前置：落盘件 0600（同组/他人不可写）
    return path


def main():
    if not os.path.isfile(PROBE):
        print("  [FAIL] 探针件缺失：%s" % PROBE)
        return 1
    probe = load_probe()
    os.makedirs(SCRATCH, exist_ok=True)
    try:
        # ---------------- F1 健康基线 → 绿 ----------------
        rc, msg = probe.output_leg_check(mk_state())
        check("F1 健康基线（全源可信+签名一致+近期裁决）→绿", rc == 0 and "无积压" in msg,
              "rc=%s msg=%s" % (rc, msg[:90]))

        # ---------------- F2 积压·源被拒用 → 红(A) ----------------
        rc, msg = probe.output_leg_check(mk_state(refused=["exp1"], sig_mismatch=True))
        check("F2 积压·源被拒用（签名不前进）→红(A)", rc == 1 and "有活未产出" in msg
              and "exp1" in msg, "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- F3 死手·双源拒用+长期零裁决 → 红(B) ----------------
        rc, msg = probe.output_leg_check(mk_state(refused=["exp1", "exp2"],
                                                  out_age_s=5 * 3600))
        check("F3 死手·双源拒用+末次裁决5h前→红(B)", rc == 1 and "长期零产出" in msg,
              "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- F4 无 mirror 读数段 → ⑥ 跳过（不猜绿不猜红） ----------------
        rc, msg = probe.output_leg_check(mk_state(with_mirror=False))
        check("F4 状态面无mirror读数段→⑥跳过(不猜绿红)", rc == 0 and "读数不可得" in msg,
              "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- F5 积压·源可用但有活未产出 → 红(A)（本发现点名的洞） ----------------
        rc, msg = probe.output_leg_check(mk_state(sig_mismatch=True))
        check("F5 积压·源可信却有活未产出→红(A)", rc == 1 and "有活未产出" in msg
              and "exp1" in msg, "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- F6 死手·部分源拒用持续 → 红(B) ----------------
        rc, msg = probe.output_leg_check(mk_state(refused=["exp2"], out_age_s=5 * 3600))
        check("F6 死手·部分源拒用持续+长期零裁决→红(B)", rc == 1 and "长期零产出" in msg
              and "exp2" in msg, "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- F7 源全可信+无新终态单+长期零裁决 → 绿（口径收窄） ----------------
        rc, msg = probe.output_leg_check(mk_state(out_age_s=5 * 3600))
        check("F7 源全可信+无新终态单可裁+长期零裁决→绿", rc == 0 and "无积压" in msg,
              "rc=%s msg=%s" % (rc, msg[:130]))

        # ---------------- F8 同 F7 但有拒用源 → 红(B 接管) ----------------
        rc, msg = probe.output_leg_check(mk_state(refused=["exp2"], out_age_s=5 * 3600))
        check("F8 同F7但存在拒用源→红(B接管，绿不掩盖拒用态零产出)",
              rc == 1 and "长期零产出" in msg, "rc=%s msg=%s" % (rc, msg[:110]))

        # ---------------- CLI 级：退出码语义 ----------------
        missing = os.path.join(SCRATCH, "no-such-state.json")
        rc, out = run_cli(missing)
        check("C1 状态面缺件→rc=2", rc == 2 and "缺件" in out, "rc=%s out=%s" % (rc, out[:90]))

        bad = os.path.join(SCRATCH, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        rc, out = run_cli(bad)
        check("C2 状态面坏JSON→rc=2", rc == 2 and "不可解析" in out,
              "rc=%s out=%s" % (rc, out[:90]))

        stale = write_state(os.path.join(SCRATCH, "stale.json"),
                            mk_state(out_age_s=5 * 3600))
        st = json.load(open(stale, encoding="utf-8"))
        st["heartbeat_ts"] = time.strftime(HB_FMT, time.localtime(time.time() - 7200))
        write_state(stale, st)
        old = time.time() - 7200
        os.utime(stale, (old, old))
        rc, out = run_cli(stale)
        check("C3 读数过期(mtime/heartbeat老)→rc=1", rc == 1 and "过期" in out,
              "rc=%s out=%s" % (rc, out[:90]))

        nogate = write_state(os.path.join(SCRATCH, "no-gate.json"), mk_state())
        st = json.load(open(nogate, encoding="utf-8"))
        st.pop("mirror_ro_gate")
        write_state(nogate, st)
        rc, out = run_cli(nogate)
        check("C4 无mirror_ro_gate读数→rc=2", rc == 2 and "mirror_ro_gate" in out,
              "rc=%s out=%s" % (rc, out[:90]))

        badset = write_state(os.path.join(SCRATCH, "bad-set.json"), mk_state())
        st = json.load(open(badset, encoding="utf-8"))
        st["mirror_ro_gate"]["expX"] = True
        write_state(badset, st)
        rc, out = run_cli(badset)
        check("C5 源集与守护在册源集不一致→rc=2", rc == 2 and "源集" in out,
              "rc=%s out=%s" % (rc, out[:110]))

        # C6/C7（2026-11-03 SIL 环修复批）：源码版本钉对账——状态面读数来自在役守护
        # 载入时的判据，探针实测用盘上现码；不一致＝两套真相并行、不可对账 ⇒ rc=2。
        nosrc = write_state(os.path.join(SCRATCH, "no-src.json"), mk_state(with_src=False))
        rc, out = run_cli(nosrc)
        check("C6 版本钉缺席（在役码早于版本钉机制）→rc=2", rc == 2
              and "未登记载入源码版本" in out, "rc=%s out=%s" % (rc, out[:110]))

        oldsrc = write_state(os.path.join(SCRATCH, "old-src.json"),
                             mk_state(src_sha="0" * 64))
        rc, out = run_cli(oldsrc)
        check("C7 版本钉不等（在役旧码≠盘上判据＝两套真相并行）→rc=2", rc == 2
              and "两套判据并行" in out, "rc=%s out=%s" % (rc, out[:110]))

        # ---------------- 源码自证：不弱化既有断言 ----------------
        src = open(PROBE, encoding="utf-8").read()
        check("S1 源码含⑥产出腿前进断言", "output_leg_check" in src
              and "产出腿前进断言" in src and "DEADMAN_S" in src)
        kept = ["① 状态面在位且可解析", "② 读数新鲜", "③ mirror_ro_gate 逐源读数在位",
                "④【v1.1 新增】机械实测交叉核验", "⑤ 机械实测拒用"]
        missing_k = [k for k in kept if k not in src]
        check("S2 既有判据①②③④⑤未被删改（不弱化断言）", not missing_k,
              "缺=%s" % (missing_k or "无"))
        check("S3 PASS行带产出腿断言注记（口径不越权背书）",
              "PASS SIL 裁决产出腿（未停摆）" in src and "绿≠「此刻正在产出」" in src)
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("小计：PASS=%d FAIL=%d" % (NCASE - len(FAILS), len(FAILS)), flush=True)
    if FAILS:
        print("FAIL %s" % ",".join(FAILS), flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
