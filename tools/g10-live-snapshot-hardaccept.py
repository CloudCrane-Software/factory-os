#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G10 两腿 live→snapshot 硬验收门（波次B · B5 链 · 债号 C11）。

判据来源（单一源，逐条可追）：
  · 30-工件/janitor-20261103/j5-redlist-baseline.md:57（J5 复核整改批 2026-11-03 设）
    「**硬验收（G10 两腿 live→snapshot 收缩项）**：镜像目录 ro 重挂、裁决链重通
    （mirror_ro_gate=双真）后的**首个 `--refresh` 周期**必须满足其一——(a) exp1/exp2
    两腿自动回切 live 且复算通过（SUMMARY live腿≥35）；(b) 该两腿 snapshot 登记失效
    → G10 判红。**终裁不得永久挂 snapshot**。」
  · 30-工件/janitor-20261103/j5-redlist-baseline.md:33（M1 处置记录）：exp1/exp2 终裁腿
    live→snapshot 是「弱化方向的既成事实」，live_leg_min=32 未下调、值钉 5→7 为加固
    ⇒ 硬验收＝重通后回 live 或 snapshot 登记失效。
  · 任务书 波次B-判据面批量清偿.md:39「C11：G10 两腿 live→snapshot 硬验收——G10 门的
    live 腿与 snapshot 腿对同一对象硬对账。」

本门只读，不改任何判据件（不改 tools/numbers-sota-check.py、不改 tools/all-gates.sh、
不改 tools/gate-pins.list、不写 计划/变更日志.md）——改门必跑 gate-pins-refresh.sh，而
该脚本无条件写 计划/变更日志.md＝本批禁改（同批 B1 账本面对账门批的同款处置）。

四条腿：
  leg-1 触发源可信：裁决链是否已重通——**委派 tools/sil-verdict-probe.py**（机械实测
        findmnt OPTIONS 含 ro + 状态面逐源交叉核验 + 产出腿前进断言；该门 PASS 语义
        ＝「源可信且产出腿在产出」＝裁决链重通）。rc=0⇒重通；rc=1⇒未重通；
        rc=2⇒不可证⇒本门 rc=2（不可证即红，不猜绿）。
  leg-2 未到期（链未重通）：两腿挂 snapshot 合法（J5 明写：SIL 停摆期防「复算失败恒红」
        掩盖值的点时真源）⇒ 绿，并打印未到期读数与债务归属（C3/PoC D 裁决链收口批）。
  leg-3 到期兑付（链已重通）：
        (a) 两腿 class=live ⇒ 复核 live腿≥35 且 G10 本体 exit 0 ⇒ 绿（(a) 兑现）；
        (b) 两腿仍 class=snapshot ⇒ 兑付条件＝「snapshot 登记失效 → G10 判红」：
            G10 本体红 ⇒ 绿（以红兑付）；G10 本体绿且首个 `--refresh` 周期已过/宽限期已过
            ⇒ **红**（终裁永久挂 snapshot＝(a)(b) 双双未兑现）。
  leg-4 同对象硬对账（任务书措辞「live 腿与 snapshot 腿对同一对象硬对账」）：同一对象
        （anchor 组）上并存 live 腿与 snapshot 腿时，其 snapshot 腿的值必须在独立钉桩
        （tools/numbers-sota-check.pin.json 的 snapshot_value_pins 段）有值钉——否则该对
        象上 snapshot 值无外部锚（live 腿侧有 live_leg_min 下限护栏）。未钉桩集合登记为
        「已登记缺口」，基线冻结、**只增不减**：增长即红（绿但缺口可见，不得读作已消）。

退出码：0=绿 / 1=红 / 2=不可证（缺件或读数不可信）。
用法：
  python3 -I tools/g10-live-snapshot-hardaccept.py [--registry PATH] [--subject PATH]
        [--pin PATH] [--probe PATH] [--state PATH] [--g10-cmd "..."] [--selftest]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = "30-工件/门红面批-20261105/gate-registry.json"
DEFAULT_SUBJECT = "工具状态备份/numbers-sota-20261031.json"
DEFAULT_PIN = "tools/numbers-sota-check.pin.json"
DEFAULT_PROBE = "tools/sil-verdict-probe.py"
DEFAULT_STATE = "状态观测/g10-hardaccept-state.json"
DEFAULT_G10_CMD = "python3 -I tools/numbers-sota-check.py"

EXP_KEYS = ("anchor3_improvement_loop/loop_ring3_exp1_verdict",
            "anchor3_improvement_loop/loop_ring3_exp2_verdict")


def now_iso(ts=None):
    ts = time.time() if ts is None else ts
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


def load_json(path: Path, what: str):
    if not path.is_file():
        return None, "[缺件] %s 不存在：%s" % (what, path)
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:                                   # noqa: BLE001
        return None, "[坏件] %s 不可解析：%s（%s）" % (what, path, e)


def run_probe(probe_path: Path, timeout=300):
    """跑 SIL 裁决产出腿探针：rc=0 重通 / rc=1 未重通 / rc=2 不可证。"""
    if not probe_path.is_file():
        return None, "[缺件] 探针不存在：%s" % probe_path
    cmd = [sys.executable, "-I", str(probe_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WS), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "[不可证] 探针超时（>%ss）：%s" % (timeout, probe_path)
    out = (r.stdout or "") + (r.stderr or "")
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    return r.returncode, tail


def run_g10(g10_cmd: str, timeout=900):
    """跑 G10 本体（numbers-sota-check.py）：rc=0 绿 / 非 0 红。返回 (rc, summary)。"""
    cmd = g10_cmd.split() if isinstance(g10_cmd, str) else list(g10_cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WS), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "[不可证] G10 超时（>%ss）：%s" % (timeout, g10_cmd)
    out = (r.stdout or "") + (r.stderr or "")
    summary = ""
    for line in out.splitlines():
        if line.startswith("SUMMARY"):
            summary = line.strip()
    return r.returncode, (summary or out.strip().splitlines()[-1] if out.strip() else "")


def subject_legs(subject):
    return (subject.get("meta", {}).get("verification", {}) or {}).get("legs", {}) or {}


def classify(legs):
    live = [k for k, v in legs.items() if v.get("class") == "live"]
    snap = [k for k, v in legs.items() if v.get("class") == "snapshot"]
    return live, snap


def same_object_report(legs, pin_value_keys):
    """同对象硬对账：按 anchor 组（对象）统计 live/snapshot 并列与未钉桩的 snapshot 腿。"""
    objs = {}
    for k, v in legs.items():
        obj = k.split("/")[0]
        c = objs.setdefault(obj, {"live": [], "snapshot": []})
        c[v.get("class", "?")].append(k)
    rows = []
    unpinned = []
    for obj in sorted(objs):
        c = objs[obj]
        both = bool(c["live"]) and bool(c["snapshot"])
        un = [k for k in c["snapshot"] if k not in pin_value_keys]
        unpinned.extend(un)
        rows.append({"object": obj, "live": len(c["live"]), "snapshot": len(c["snapshot"]),
                     "both": both, "unpinned": len(un), "unpinned_keys": un})
    return rows, unpinned


def decide(cfg, subject, pin, probe_rc, probe_tail, g10_rc, g10_summary,
           state, now_ts, state_path=None):
    """纯判定（可被 --selftest 直接喂构造输入）。返回 (rc, lines[])。"""
    L = []
    legs = subject_legs(subject)
    live_keys, snap_keys = classify(legs)
    live_n, snap_n = len(live_keys), len(snap_keys)
    exp_keys = list(cfg.get("exp_leg_keys") or EXP_KEYS)
    min_after = int(cfg.get("live_leg_min_after_reconnect", 35))
    grace_h = float(cfg.get("grace_hours", 48))
    baseline_unpinned = int(cfg.get("registered_gaps", {}).get("unpinned_snapshot_legs", 0))

    L.append("== G10 两腿 live→snapshot 硬验收门（债号 C11 · 波次B·B5）")
    L.append("工作区：%s" % WS)
    L.append("  触发源：%s" % cfg.get("probe", DEFAULT_PROBE))
    L.append("  读数：live腿=%d snapshot腿=%d（钉桩 live_leg_min=%s）" %
             (live_n, snap_n, subject.get("meta", {}).get("verification", {}).get("live_leg_min")))
    L.append("  两腿 class：%s" % "；".join(
        "%s=%s" % (k.split("/")[-1], legs.get(k, {}).get("class", "缺席")) for k in exp_keys))

    # ---- leg-1 触发源 ----
    if probe_rc is None:
        L.append("[红] leg-1 触发源不可证：%s" % probe_tail)
        return 2, L
    if probe_rc == 2:
        L.append("[红] leg-1 触发源不可证（探针 rc=2）：%s" % probe_tail[:300])
        return 2, L
    chain_reconnected = (probe_rc == 0)
    L.append("[%s] leg-1 触发源：裁决链%s（探针 rc=%d）%s" % (
        "绿" if chain_reconnected else "绿（未到期）",
        "已重通（ro 挂载+产出腿在产出）" if chain_reconnected else "未重通（镜像源非机制性只读）",
        probe_rc, "" if chain_reconnected else " —— " + probe_tail[:160]))

    # ---- leg-4 同对象硬对账（与到期无关，先算）----
    svp = (pin or {}).get("snapshot_value_pins") or {}
    rows, unpinned = same_object_report(legs, set(svp))
    grew = len(unpinned) > baseline_unpinned
    L.append("[%s] leg-4 同对象硬对账（live 腿 vs snapshot 腿对同一对象）：未钉桩 snapshot 腿 %d 条"
             "（登记基线 %d，只增不减）%s" % (
                 "红" if grew else "绿", len(unpinned), baseline_unpinned,
                 " —— 已登记缺口：同对象上 snapshot 值无外部锚（live 腿侧有 live_leg_min 下限护栏）；"
                 "勿读作已消" if unpinned else ""))
    for r in rows:
        L.append("           · 对象 %s：live %d / snapshot %d（并列=%s）· 未钉桩 snapshot 腿 %d 条%s" % (
            r["object"], r["live"], r["snapshot"], "是" if r["both"] else "否",
            r["unpinned"], ("：" + "、".join(r["unpinned_keys"][:3])) if r["unpinned_keys"] else ""))

    rc_final = 0
    reds = []

    if not chain_reconnected:
        # ---- leg-2 未到期 ----
        L.append("[绿] leg-2 未到期：两腿挂 snapshot 合法（J5：SIL 停摆期防「复算失败恒红」"
                 "掩盖值的点时真源）；债务归属＝C3 / PoC D 裁决链收口批（镜像目录 ro 重挂）")
        L.append("结论：绿（硬验收未到期；触发条件＝裁决链重通后的首个 --refresh 周期）")
        return (1 if grew else 0), L

    # ---- leg-3 到期兑付 ----
    rc_first_seen = state.get("rc_first_seen_ts")
    if rc_first_seen is None:
        rc_first_seen = now_ts
        state["rc_first_seen_ts"] = rc_first_seen
        state["rc_first_seen_iso"] = now_iso(rc_first_seen)
        state["note"] = "首次观察到裁决链重通的时点（硬验收窗口起算）"
    subject_mtime = float(cfg.get("_subject_mtime") or 0)
    last_refresh = parse_ts((subject.get("meta", {}).get("verification", {}) or {}).get("last_refresh"))
    refresh_after = (subject_mtime > rc_first_seen) or (
        last_refresh is not None and last_refresh > rc_first_seen)
    elapsed_h = (now_ts - float(rc_first_seen)) / 3600.0

    classes = [legs.get(k, {}).get("class") for k in exp_keys]
    all_live = all(c == "live" for c in classes)
    if all_live:
        ok = (live_n >= min_after) and (g10_rc == 0)
        L.append("[%s] leg-3 到期兑付 (a)：两腿已回 live（live腿=%d，下限 %d）＋ G10 本体 rc=%s%s" % (
            "绿" if ok else "红", live_n, min_after, g10_rc,
            " ⇒ (a) 兑现：回切 live 且复算通过" if ok else
            " ⇒ 未达成 (a)：live腿数未达 %d 或 G10 本体非绿" % min_after))
        if not ok:
            reds.append("两腿已回 live 但 live腿=%d（应 ≥%d）或 G10 本体 rc=%s" % (live_n, min_after, g10_rc))
    else:
        if g10_rc != 0:
            L.append("[绿] leg-3 到期兑付 (b)：两腿仍挂 snapshot，但 G10 本体已判红（rc=%s，%s）"
                     " ⇒ (b) 兑现：snapshot 登记失效，G10 判红" % (g10_rc, g10_summary[:120]))
        elif refresh_after:
            L.append("[红] leg-3 到期兑付：裁决链已重通且首个 --refresh 周期已过"
                     "（刷新于 %s），但两腿仍挂 snapshot（class=%s）且 G10 本体仍绿"
                     " ⇒ (a) 未兑现（未回 live）＋(b) 未兑现（snapshot 登记未失效）"
                     " ⇒ 终裁永久挂 snapshot" % (now_iso(max(subject_mtime, last_refresh or 0)), classes))
            reds.append("首个 --refresh 周期已过但两腿仍挂 snapshot 且 G10 未判红")
        elif elapsed_h >= grace_h:
            L.append("[红] leg-3 到期兑付：裁决链已重通 %.1fh（起算 %s，宽限 %sh），既未回切 live"
                     " 也未发生任何 --refresh 周期 ⇒ 终裁永久挂 snapshot" % (
                         elapsed_h, state.get("rc_first_seen_iso"), grace_h))
            reds.append("重通后超过宽限期仍无回切/无刷新周期")
        else:
            L.append("[绿] leg-3 未到期：裁决链已重通 %.1fh（起算 %s），尚未发生首个 --refresh 周期"
                     " ⇒ 硬验收窗口未开；到期线 %s" % (
                         elapsed_h, state.get("rc_first_seen_iso"),
                         now_iso(float(rc_first_seen) + grace_h * 3600)))
    if reds:
        L.append("结论：红（%s）" % "；".join(reds))
        rc_final = 1
    else:
        L.append("结论：绿（硬验收未到期或已按 J5 兑现；已登记缺口见 leg-4 行——勿读作已消）")
        rc_final = 0
    if grew:
        rc_final = 1
        L.append("结论：红（leg-4 已登记缺口增长）")
    return rc_final, L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--subject", default=DEFAULT_SUBJECT)
    ap.add_argument("--pin", default=DEFAULT_PIN)
    ap.add_argument("--probe", default=DEFAULT_PROBE)
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--g10-cmd", default=DEFAULT_G10_CMD)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    reg, err = load_json(WS / args.registry, "登记面")
    if err:
        print(err)
        return 2
    cfg = dict(reg.get("g10_hardaccept") or {})
    cfg.setdefault("exp_leg_keys", list(EXP_KEYS))
    cfg.setdefault("live_leg_min_after_reconnect", 35)
    cfg.setdefault("grace_hours", 48)
    cfg.setdefault("registered_gaps", {}).setdefault("unpinned_snapshot_legs", 0)
    cfg["probe"] = args.probe

    subject_path = Path(args.subject)
    if not subject_path.is_absolute():
        subject_path = WS / subject_path
    pin_path = Path(args.pin)
    if not pin_path.is_absolute():
        pin_path = WS / pin_path
    probe_path = Path(args.probe)
    if not probe_path.is_absolute():
        probe_path = WS / probe_path
    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = WS / state_path

    subject, err = load_json(subject_path, "G10 正本（subject）")
    if err:
        print(err)
        return 2
    pin, err = load_json(pin_path, "G10 独立钉桩（pin）")
    if err:
        print(err)
        return 2

    if args.selftest:
        return selftest(cfg, subject, pin, args)

    state, err = load_json(state_path, "硬验收窗口状态面")
    if err and state_path.exists():
        print(err)
        return 2
    if state is None:
        state = {}

    probe_rc, probe_tail = run_probe(probe_path)
    g10_rc, g10_summary = run_g10(args.g10_cmd)
    cfg["_subject_mtime"] = subject_path.stat().st_mtime
    now_ts = time.time()
    rc, lines = decide(cfg, subject, pin, probe_rc, probe_tail, g10_rc, g10_summary,
                        state, now_ts, state_path)
    if state != (load_json(state_path, "s")[0] or {}):
        # 只在观测到新事实时落状态（窗口起算点），避免噪声刷盘
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_suffix(state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, state_path)
            lines.append("  状态面已更新：%s（窗口起算=%s）" % (state_path, state.get("rc_first_seen_iso")))
        except OSError as e:
            lines.append("  [提示] 状态面写入失败（不影响判定）：%s" % e)
    for l in lines:
        print(l)
    return rc


def selftest(cfg, subject, pin, args):
    """五例构造夹具（全部在内存/临时目录，不碰生产件）。"""
    import copy
    import tempfile
    cases = []

    def mk_subject(live_exp=False, bump_live=0, drop_live=0):
        s = copy.deepcopy(subject)
        legs = subject_legs(s)
        for k in EXP_KEYS:
            if live_exp:
                legs[k] = dict(legs.get(k, {}), **{"class": "live", "as_of": "2026-11-05 12:00:00"})
            else:
                legs[k] = dict(legs.get(k, {}), **{"class": "snapshot"})
        if bump_live:
            legs["_fixture_extra_live"] = {"class": "live"}
        if drop_live:
            for k in [k for k, v in legs.items() if v.get("class") == "live"][:drop_live]:
                legs[k] = dict(legs[k], **{"class": "snapshot"})
        return s

    def mk_state(first_seen):
        return ({"rc_first_seen_ts": first_seen, "rc_first_seen_iso": now_iso(first_seen)}
                if first_seen else {})

    base = copy.deepcopy(cfg)
    # 夹具内把 leg-4 基线对齐现值（否则基线=0 会把每例都判成「缺口增长」）
    _rows, _unpinned = same_object_report(subject_legs(subject),
                                          set((pin or {}).get("snapshot_value_pins") or {}))
    base["registered_gaps"] = {"unpinned_snapshot_legs": len(_unpinned)}
    now = time.time()
    # 1) 链未重通 + 两腿 snapshot ⇒ 绿（未到期）
    rc, _ = decide(base, mk_subject(), pin, 1, "停摆", 0, "SUMMARY", mk_state(None), now)
    cases.append(("链未重通+两腿snapshot⇒绿（未到期）", rc == 0, rc))
    # 2) 链已重通 + 两腿已回 live + live腿≥35 + G10 绿 ⇒ 绿（(a) 兑现）
    rc, _ = decide(base, mk_subject(live_exp=True, bump_live=2), pin, 0, "PASS", 0, "SUMMARY",
                   mk_state(now - 3600), now)
    cases.append(("链已重通+两腿回live+live腿≥35+G10绿⇒绿（(a)兑现）", rc == 0, rc))
    # 3) 链已重通 + 两腿仍 snapshot + G10 绿 + 刷新已过 ⇒ 红（永久挂 snapshot）
    cfg3 = dict(base)
    cfg3["_subject_mtime"] = now          # 刷新周期已过（subject mtime > 起算点）
    rc, _ = decide(cfg3, mk_subject(), pin, 0, "PASS", 0, "SUMMARY", mk_state(now - 3600), now)
    cases.append(("链已重通+两腿仍snapshot+G10绿+刷新已过⇒红（永久挂snapshot）", rc == 1, rc))
    # 4) 链已重通 + 两腿仍 snapshot + G10 红 ⇒ 绿（以红兑付 (b)）
    rc, _ = decide(base, mk_subject(), pin, 0, "PASS", 1, "SUMMARY RED=1", mk_state(now - 3600), now)
    cases.append(("链已重通+两腿仍snapshot+G10红⇒绿（(b)以红兑付）", rc == 0, rc))
    # 5) 链已重通 + 两腿已回 live 但 live腿数不足 35（另两条 live 腿被降级）⇒ 红
    rc, _ = decide(base, mk_subject(live_exp=True, drop_live=2), pin, 0, "PASS", 0, "SUMMARY",
                   mk_state(now - 3600), now)
    cases.append(("链已重通+两腿回live但live腿<35⇒红", rc == 1, rc))
    # 6) 链已重通 + 两腿仍 snapshot + 尚未刷新 + 未过宽限 ⇒ 绿（窗口未开）
    rc, _ = decide(base, mk_subject(), pin, 0, "PASS", 0, "SUMMARY", mk_state(now - 600), now)
    cases.append(("链已重通+两腿仍snapshot+未刷新+未过宽限⇒绿（窗口未开）", rc == 0, rc))
    # 7) leg-4 已登记缺口增长（未钉桩 snapshot 腿数 > 基线）⇒ 红
    cfg7 = dict(base)
    cfg7["registered_gaps"] = {"unpinned_snapshot_legs": len(_unpinned) - 1}
    rc, _ = decide(cfg7, mk_subject(), pin, 1, "停摆", 0, "SUMMARY", mk_state(None), now)
    cases.append(("leg-4 已登记缺口增长⇒红", rc == 1, rc))

    ok = all(c[1] for c in cases)
    for name, good, rc in cases:
        print("  %s %s（rc=%d）" % ("[PASS]" if good else "[FAIL]", name, rc))
    print("SELFTEST_%s（%d/%d 例过）" % ("OK" if ok else "FAIL", sum(1 for c in cases if c[1]), len(cases)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
