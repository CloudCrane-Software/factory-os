#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timer-active-recon-gate.py — 机制激活态门（ESC-37 · 账本 D-165 · 卡 w11-d165-timer-active-gate #217）。

【为什么建本门（ESC-37 门盲区）】
  机制「在码」被当「在役」：jit-broker-renew.timer（broker 日自轮换 renew-broker.sh：
  签后继→原子写回→撤旧——重叠双钥窗口的生产先例件）在 gov 长期 disabled 而无任何门
  能红（重叠轮换演练-20261108.md §6.2d + T1 行「timer 已 disabled」）；轮换 SLA 判据
  （R-14）对该面输出证伪不了而无人察觉原因。本门把 systemd 单元激活态变成机器对账：
  关键自轮换/自愈 timer 清单（件名+期望 is-enabled/is-active 态）成册，systemctl 实读
  ≡ 册（不符⇒红点名）；disabled 登记必须带 reason+approved_by+expires（比照
  tools/publish-allowlist.json 形制，expires 过期⇒红=登记失效须运营者重登记）。

【登记册（单一源）】
  tools/timer-expected-state.json（schema timer-expected-state/v1）。只增不减：删行/
  缩窄对账面视同改判据（判据只许变严）。启用/停用/触发类活体动作属运营者窗口——
  本门只读对账，绝不执行 systemctl enable/disable/start/stop（代码内无写路径）。

【两腿判据】
  leg-R1 登记面形制：expected_enabled ∈ {disabled,masked,masked-runtime} 的行必须带
    非空 reason+approved_by+expires（缺/坏⇒红点名该行）；expires < 当日⇒红（登记
    过期自动失效）；expected_* 词不在 systemd 已知态词表⇒不可证（fail-closed）。
  leg-R2 激活态对账（--live）：hosts 未登记的行对每台跑门主机生效，登记了的行只对
    名单内主机判（其余⇒INFO 跳过）；is-enabled 读 not-found⇒红（册上有机上无）；
    实读词 ≡ 册词否则红（逐单元逐面点名 expected/actual）；实读不可得（systemctl
    缺席/超时/输出非已知态词）⇒不可证（不猜绿）。
  语义注：systemctl is-enabled/is-active 对 disabled/inactive 等态以非零 rc 退出——
    本门按 stdout 态词+rc 归一化判读，非零 rc 本身不构成不可证（如本机实测：
    is-enabled 缺件→「not-found」rc=4；is-active 缺件→「inactive」rc=4）。

【退出码（三态，与 judge-deploy-recon-gate/ledger-face-recon-gate 同语义）】
  0=绿 / 1=红（逐条点名）/ 2=不可证（缺件坏件 fail-closed，不猜绿）。
  门本体未挂 all-gates 点选面（gates-pr-selection.list 受 CODEOWNERS 判官路径锁，
  本卡允许路径仅本门+登记册两件）——巡检接线属后续经批动作；接线前由操作员/巡检
  在目标机手动跑 --live。

用法:
  timer-active-recon-gate.py --selftest            # 内嵌夹具自测（零网络/零 systemctl）
  timer-active-recon-gate.py --live [--register F] [--host NAME] [--systemctl-bin P]
                                    [--json]        # 激活态实读对账（目标机巡检腿）
  --register 缺省=与本件同目录的 timer-expected-state.json；
  --host 缺省=socket.gethostname()（登记册 hosts 与之精确对位，支持别名/IP 行）。
  --systemctl-bin 缺省 "systemctl"（自测/夹具机可指桩件）。

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面）；禁 secret 入 git（本件零凭据，bot-scrub 可扫）；不猜绿。
"""

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys

# systemd 已知态词表（is-enabled / is-active 两面；越表词=不可证，不猜绿）
KNOWN_ENABLED = {
    "enabled", "enabled-runtime", "disabled", "masked", "masked-runtime",
    "static", "generated", "transient", "indirect", "not-found", "bad",
}
KNOWN_ACTIVE = {
    "active", "reloading", "inactive", "failed", "activating", "deactivating",
    "unknown",
}
# 这些 enabled 态=机制停摆，登记必须带 reason+approved_by+expires（比照 allowlist 形制）
REQUIRES_REGISTRATION = {"disabled", "masked", "masked-runtime"}

SEV_ORDER = {"RED": 0, "UNPROVABLE": 1, "INFO": 2}


def default_register_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "timer-expected-state.json")


def parse_expires(text):
    """ISO 日期解析；非 ISO/越界 ⇒ None（调用方判红：登记形制违例）。"""
    try:
        return datetime.date.fromisoformat(str(text).strip())
    except (ValueError, TypeError):
        return None


def check_registration_row(entry):
    """leg-R1：disabled/masked 行必须带 reason+approved_by+expires（未过期）。

    返回 findings 列表（RED=形制违例点名该行）。文件级损坏不在本函数（由
    load_register 判不可证）。"""
    findings = []
    unit = entry.get("unit") if isinstance(entry, dict) else None
    tag = unit if unit else "<bad-row>"
    if str(entry.get("expected_enabled", "")).strip() not in REQUIRES_REGISTRATION:
        return findings
    for field in ("reason", "approved_by"):
        val = entry.get(field)
        if not isinstance(val, str) or not val.strip():
            findings.append({
                "sev": "RED", "unit": tag, "aspect": "register",
                "msg": "[RED] %s 登记形制违例：expected_enabled=%s 缺非空 %s"
                       "（disabled 须带 reason+approved_by+expires 登记，比照 allowlist 形制）"
                       % (tag, entry.get("expected_enabled"), field),
            })
    exp_raw = entry.get("expires")
    exp = parse_expires(exp_raw) if isinstance(exp_raw, str) else None
    if exp is None:
        findings.append({
            "sev": "RED", "unit": tag, "aspect": "register",
            "msg": "[RED] %s 登记形制违例：expires 缺席或非 ISO 日期（实得 %r）"
                   "——过期自动失效语义无从成立" % (tag, exp_raw),
        })
    return findings


def judge_entry(entry, host, today, readings=None):
    """对单行登记判读。readings=None ⇒ 只跑 leg-R1（登记面）；--live 传实读。

    返回 findings：sev ∈ RED / UNPROVABLE / INFO。"""
    findings = []
    if not isinstance(entry, dict):
        return [{"sev": "UNPROVABLE", "unit": "<bad-row>", "aspect": "register",
                 "msg": "[UNPROVABLE] 登记册存在非对象行（fail-closed，不猜绿）"}]
    unit = entry.get("unit")
    if not isinstance(unit, str) or not unit.strip() or not unit.endswith(".timer"):
        return [{"sev": "UNPROVABLE", "unit": repr(unit), "aspect": "register",
                 "msg": "[UNPROVABLE] unit 缺席/非 .timer 后缀（登记册结构损坏）"}]
    unit = unit.strip()
    exp_en = str(entry.get("expected_enabled", "")).strip()
    exp_ac = str(entry.get("expected_active", "")).strip()
    if exp_en not in KNOWN_ENABLED:
        return [{"sev": "UNPROVABLE", "unit": unit, "aspect": "enabled",
                 "msg": "[UNPROVABLE] %s expected_enabled=%r 越已知态词表" % (unit, exp_en)}]
    if exp_ac not in KNOWN_ACTIVE:
        return [{"sev": "UNPROVABLE", "unit": unit, "aspect": "active",
                 "msg": "[UNPROVABLE] %s expected_active=%r 越已知态词表" % (unit, exp_ac)}]
    findings.extend(check_registration_row(entry))

    # hosts 域：未登记 ⇒ 对每台跑门主机生效；登记了 ⇒ 名单外 INFO 跳过
    hosts = entry.get("hosts")
    if isinstance(hosts, list) and hosts:
        if host not in [str(h).strip() for h in hosts]:
            findings.append({
                "sev": "INFO", "unit": unit, "aspect": "scope",
                "msg": "[INFO] %s 本机 %s ∉ 登记 hosts %s——跨机域外跳过不判"
                       % (unit, host, hosts),
            })
            return findings

    exp = parse_expires(entry.get("expires")) \
        if isinstance(entry.get("expires"), str) else None
    if exp is not None and today > exp:
        findings.append({
            "sev": "RED", "unit": unit, "aspect": "register",
            "msg": "[RED] %s 登记已过期（expires=%s < today=%s）——登记失效，"
                   "须运营者窗口重登记（启用或续登 disabled）" % (unit, exp, today),
        })

    if readings is None:
        return findings

    # leg-R2 激活态对账（先在位，后逐面 ≡）
    en_word = readings.get(unit, {}).get("enabled")
    ac_word = readings.get(unit, {}).get("active")
    en_err = readings.get(unit, {}).get("enabled_err")
    ac_err = readings.get(unit, {}).get("active_err")
    if en_word == "not-found":
        findings.append({
            "sev": "RED", "unit": unit, "aspect": "presence",
            "msg": "[RED] %s 实读 is-enabled=not-found——册上有机上无（单元被删/"
                   "机不对位），激活态对账无从谈起" % unit,
        })
        return findings
    if en_word is None:
        findings.append({
            "sev": "UNPROVABLE", "unit": unit, "aspect": "enabled",
            "msg": "[UNPROVABLE] %s is-enabled 实读不可得（%s）——不猜绿"
                   % (unit, en_err or "空读数"),
        })
    elif en_word != exp_en:
        findings.append({
            "sev": "RED", "unit": unit, "aspect": "enabled",
            "msg": "[RED] %s is-enabled 实读≠册：期望 %s 实得 %s——激活态漂移"
                   "（启用/停用属运营者窗口动作，未登记先行动⇒红）"
                   % (unit, exp_en, en_word),
        })
    if ac_word is None:
        findings.append({
            "sev": "UNPROVABLE", "unit": unit, "aspect": "active",
            "msg": "[UNPROVABLE] %s is-active 实读不可得（%s）——不猜绿"
                   % (unit, ac_err or "空读数"),
        })
    elif ac_word != exp_ac:
        findings.append({
            "sev": "RED", "unit": unit, "aspect": "active",
            "msg": "[RED] %s is-active 实读≠册：期望 %s 实得 %s"
                   % (unit, exp_ac, ac_word),
        })
    return findings


def load_register(path):
    """读登记册。文件级损坏⇒ (None, unprovable_finding)；好⇒ (dict, None)。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, {"sev": "UNPROVABLE", "unit": "<register>", "aspect": "file",
                      "msg": "[UNPROVABLE] 登记册不可读/非 JSON：%s（%s）——不猜绿"
                             % (path, exc)}
    if not isinstance(reg, dict) or not isinstance(reg.get("timers"), list) \
            or not reg["timers"]:
        return None, {"sev": "UNPROVABLE", "unit": "<register>", "aspect": "file",
                      "msg": "[UNPROVABLE] 登记册结构损坏（缺非空 timers[]）——不猜绿"}
    return reg, None


def read_unit_state(unit, aspect, systemctl_bin):
    """systemctl 实读单面。返回 (word-or-None, err-or-None)。

    态词在表内即有效读数（rc 非零不构成不可证——见 docstring 语义注）。"""
    cmd = [systemctl_bin, "is-enabled" if aspect == "enabled" else "is-active", unit]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "systemctl 调用失败：%s" % (str(exc).strip()[:80])
    word = (proc.stdout or "").strip().splitlines()
    word = word[0].strip().lower() if word else ""
    table = KNOWN_ENABLED if aspect == "enabled" else KNOWN_ACTIVE
    if word in table:
        return word, None
    preview = (proc.stdout or proc.stderr or "").strip()[:40]
    return None, "输出越态词表（rc=%d，原文 %r）" % (proc.returncode, preview)


def live_readings(entries, systemctl_bin):
    """逐单元双面实读。返回 {unit: {enabled:…, enabled_err:…, active:…, active_err:…}}"""
    readings = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        unit = e.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            continue
        unit = unit.strip()
        en, en_err = read_unit_state(unit, "enabled", systemctl_bin)
        ac, ac_err = read_unit_state(unit, "active", systemctl_bin)
        readings[unit] = {"enabled": en, "enabled_err": en_err,
                          "active": ac, "active_err": ac_err}
    return readings


def verdict_of(findings):
    """三态收敛：任一 RED ⇒ (red,1)；否则任一 UNPROVABLE ⇒ (unprovable,2)；绿 ⇒ (clean,0)。"""
    sevs = {f["sev"] for f in findings}
    if "RED" in sevs:
        return "red", 1
    if "UNPROVABLE" in sevs:
        return "unprovable", 2
    return "clean", 0


# ---------------------------------------------------------------- selftest --
def selftest():
    """内嵌夹具自测：纯函数面（judge_entry/verdict_of/load_register 形制腿），
    零网络、零 systemctl、零真登记册读取——CI 夹具机上可复跑。"""
    today = datetime.date(2026, 11, 8)
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    FUT = {"expires": "2027-02-06"}

    def row(**kw):
        base = {"unit": "jit-broker-renew.timer", "expected_enabled": "disabled",
                "expected_active": "inactive", "reason": "在码 disabled 现势",
                "approved_by": "裁24", "hosts": ["company-bao-1", "gov"]}
        base.update(FUT)
        base.update(kw)
        return base

    GREEN_EN = {"jit-broker-renew.timer": {"enabled": "disabled", "active": "inactive",
                                           "enabled_err": None, "active_err": None}}
    # ① 绿：实读≡册（disabled+inactive，登记三件齐，未过期，在域）
    f = judge_entry(row(), "company-bao-1", today, GREEN_EN)
    check("green.congruent", verdict_of(f) == ("clean", 0), str(f))
    # ② 红：enabled 漂移（册 disabled 实得 enabled——活体动作未登记）
    f = judge_entry(row(), "gov", today,
                    {"jit-broker-renew.timer": {"enabled": "enabled", "active": "inactive",
                                                "enabled_err": None, "active_err": None}})
    v = verdict_of(f)
    check("red.enabled-drift", v == ("red", 1) and any(
        "is-enabled 实读≠册：期望 disabled 实得 enabled" in x["msg"] for x in f), str(f))
    # ③ 红：active 漂移（册 inactive 实得 active）
    f = judge_entry(row(), "gov", today,
                    {"jit-broker-renew.timer": {"enabled": "disabled", "active": "active",
                                                "enabled_err": None, "active_err": None}})
    check("red.active-drift", verdict_of(f) == ("red", 1) and any(
        "is-active 实读≠册：期望 inactive 实得 active" in x["msg"] for x in f), str(f))
    # ④ 红：缺 reason（disabled 行登记形制违例，点名该行）
    e = row(); e.pop("reason")
    f = judge_entry(e, "gov", today, GREEN_EN)
    check("red.missing-reason", verdict_of(f) == ("red", 1) and any(
        "缺非空 reason" in x["msg"] for x in f), str(f))
    # ⑤ 红：缺 expires
    e = row(); e.pop("expires")
    f = judge_entry(e, "gov", today, GREEN_EN)
    check("red.missing-expires", verdict_of(f) == ("red", 1) and any(
        "expires 缺席" in x["msg"] for x in f), str(f))
    # ⑥ 红：expires 已过期（登记失效）
    f = judge_entry(row(expires="2026-11-07"), "gov", today, GREEN_EN)
    check("red.expired", verdict_of(f) == ("red", 1) and any(
        "登记已过期" in x["msg"] and "2026-11-07" in x["msg"] for x in f), str(f))
    # ⑦ 红：册上有机上无（not-found）
    f = judge_entry(row(hosts=None), "anyhost", today,
                    {"jit-broker-renew.timer": {"enabled": "not-found", "active": "inactive",
                                                "enabled_err": None, "active_err": None}})
    check("red.not-found", verdict_of(f) == ("red", 1) and any(
        "册上有机上无" in x["msg"] for x in f), str(f))
    # ⑧ 不可证：实读不可得（systemctl 坏）——fail-closed 不猜绿
    f = judge_entry(row(hosts=None), "anyhost", today,
                    {"jit-broker-renew.timer": {"enabled": None, "active": None,
                                                "enabled_err": "systemctl 调用失败",
                                                "active_err": "systemctl 调用失败"}})
    check("unprovable.unreadable", verdict_of(f) == ("unprovable", 2) and
          sum(1 for x in f if x["sev"] == "UNPROVABLE") == 2, str(f))
    # ⑨ 跨机域外：INFO 跳过不判（hosts 名单外）
    f = judge_entry(row(), "anolis-runner", today, None)
    check("info.out-of-scope", verdict_of(f) == ("clean", 0) and
          any(x["sev"] == "INFO" and "域外跳过" in x["msg"] for x in f), str(f))
    # ⑩ 无 hosts 行：任一主机都在域（机上无 ⇒ not-found 红）
    f = judge_entry(row(hosts=None), "anyhost", today,
                    {"jit-broker-renew.timer": {"enabled": "not-found", "active": None,
                                                "enabled_err": None, "active_err": None}})
    check("red.no-hosts-row-in-scope", verdict_of(f) == ("red", 1), str(f))
    # ⑪ 绿方向补：enabled+active 登记行，实读≡册 ⇒ 绿（enabled 态词反向覆盖）
    e = row(unit="periodic-token-renew.timer", expected_enabled="enabled",
            expected_active="active")
    f = judge_entry(e, "gov", today,
                    {"periodic-token-renew.timer": {"enabled": "enabled", "active": "active",
                                                    "enabled_err": None, "active_err": None}})
    check("green.enabled-direction", verdict_of(f) == ("clean", 0), str(f))
    # ⑫ 非 disabled 行（enabled）不触发登记三件套
    f = judge_entry(e, "gov", today, None)
    check("green.no-registration-needed", verdict_of(f) == ("clean", 0), str(f))
    # ⑬ 不可证：expected_enabled 越词表
    f = judge_entry(row(expected_enabled="quasi-enabled"), "gov", today, None)
    check("unprovable.bad-word", verdict_of(f) == ("unprovable", 2), str(f))
    # ⑭ 不可证：unit 非 .timer 后缀
    f = judge_entry(row(unit="renew-broker.service"), "gov", today, None)
    check("unprovable.bad-unit", verdict_of(f) == ("unprovable", 2), str(f))
    # ⑮ 非 dict 行 ⇒ 不可证
    check("unprovable.bad-row", verdict_of(judge_entry("nope", "gov", today, None))
          == ("unprovable", 2))
    # ⑯ 归一化语义注实证：disabled 态词+非零 rc 是有效读数（模拟 is-enabled rc=1）
    #    （read_unit_state 以 subprocess 实跑，此处只钉 judge 面不因 rc 语义误判——
    #     词面已归一化后才进 judge_entry；词表见 KNOWN_ENABLED。）
    check("norm.disabled-word-valid", "disabled" in KNOWN_ENABLED
          and "masked" in KNOWN_ENABLED and "not-found" in KNOWN_ENABLED)
    check("norm.active-word-valid", {"inactive", "active", "failed"} <= KNOWN_ACTIVE)
    # ⑰ expires 解析面：ISO 收、垃圾拒
    check("parse.expires-iso", parse_expires("2027-02-06")
          == datetime.date(2027, 2, 6))
    check("parse.expires-garbage", parse_expires("next-quarter") is None
          and parse_expires(None) is None and parse_expires("") is None)
    # ⑱ 文件级损坏 ⇒ 不可证（load_register 形制腿，内存夹具不走真盘真册）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p_bad = os.path.join(td, "bad.json")
        with open(p_bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        reg, u = load_register(p_bad)
        check("load.bad-json", reg is None and u is not None
              and u["sev"] == "UNPROVABLE")
        p_empty = os.path.join(td, "empty-timers.json")
        with open(p_empty, "w", encoding="utf-8") as fh:
            json.dump({"schema": "timer-expected-state/v1", "timers": []}, fh)
        reg, u = load_register(p_empty)
        check("load.empty-timers", reg is None and u is not None)
        p_ok = os.path.join(td, "ok.json")
        with open(p_ok, "w", encoding="utf-8") as fh:
            json.dump({"schema": "timer-expected-state/v1",
                       "timers": [{"unit": "a.timer", "expected_enabled": "enabled",
                                   "expected_active": "active"}]}, fh)
        reg, u = load_register(p_ok)
        check("load.ok", reg is not None and u is None)
    # ⑲ 三态收敛面
    check("verdict.tri-state", verdict_of([]) == ("clean", 0)
          and verdict_of([{"sev": "INFO", "unit": "u", "aspect": "a", "msg": ""}])
          == ("clean", 0)
          and verdict_of([{"sev": "UNPROVABLE", "unit": "u", "aspect": "a", "msg": ""}])
          == ("unprovable", 2)
          and verdict_of([{"sev": "RED", "unit": "u", "aspect": "a", "msg": ""},
                          {"sev": "UNPROVABLE", "unit": "u", "aspect": "a", "msg": ""}])
          == ("red", 1))
    # ⑳ 点名可读面：红行必须带 unit+aspect（逐条点名语义）
    f = judge_entry(row(), "gov", today,
                    {"jit-broker-renew.timer": {"enabled": "enabled", "active": "active",
                                                "enabled_err": None, "active_err": None}})
    check("naming.red-carries-unit-aspect",
          all(x["unit"] == "jit-broker-renew.timer" and x["aspect"] in
              ("enabled", "active", "register", "presence") for x in f) and len(f) >= 2,
          str(f))

    failed = [(n, d) for (n, ok, d) in checks if not ok]
    for (n, ok, d) in checks:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", n,
                             (" — " + d[:120]) if (d and not ok) else ""))
    print("selftest %d/%d 过" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# -------------------------------------------------------------------- main --
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="机制激活态门：systemctl is-enabled/is-active 实读≡登记册"
                    "（ESC-37 · D-165）；--selftest=内嵌夹具自测。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具自测（零网络/零 systemctl/零真册读取）")
    ap.add_argument("--live", action="store_true",
                    help="激活态实读对账（目标机巡检腿；--selftest 互斥）")
    ap.add_argument("--register", default=None,
                    help="登记册路径（缺省=与本件同目录 timer-expected-state.json）")
    ap.add_argument("--host", default=None,
                    help="本机名（缺省 socket.gethostname()；与登记 hosts 对位）")
    ap.add_argument("--systemctl-bin", default="systemctl",
                    help="systemctl 可执行（夹具机可指桩件）")
    ap.add_argument("--json", action="store_true", help="机器可读裁决")
    args = ap.parse_args(argv)

    if args.selftest and args.live:
        print("--selftest 与 --live 互斥", file=sys.stderr)
        return 2
    if args.selftest:
        return selftest()
    if not args.live:
        ap.print_usage()
        print("未选腿：--selftest（自测）或 --live（实读对账）二者择一", file=sys.stderr)
        return 2

    reg_path = args.register or default_register_path()
    host = args.host or socket.gethostname()
    today = datetime.date.today()
    reg, u = load_register(reg_path)
    findings = []
    if u is not None:
        findings.append(u)
    else:
        if not isinstance(host, str) or not host.strip():
            findings.append({"sev": "UNPROVABLE", "unit": "<host>", "aspect": "scope",
                             "msg": "[UNPROVABLE] 本机名不可得——域判定无从做，不猜绿"})
        else:
            readings = live_readings(reg["timers"], args.systemctl_bin)
            for entry in reg["timers"]:
                findings.extend(judge_entry(entry, host, today, readings))

    findings.sort(key=lambda f: (SEV_ORDER.get(f["sev"], 9),
                                 f.get("unit", ""), f.get("aspect", "")))
    verdict, rc = verdict_of(findings)
    if args.json:
        print(json.dumps({
            "schema": "timer-active-recon-gate/v1",
            "verdict": verdict, "rc": rc,
            "register": reg_path, "host": host, "today": today.isoformat(),
            "findings": findings,
        }, ensure_ascii=False, indent=1))
    else:
        print("机制激活态门（ESC-37/D-165）：册=%s 本机=%s 当日=%s"
              % (reg_path, host, today.isoformat()))
        for f in findings:
            print("  " + f["msg"])
        print("verdict=%s（%d 条：%d RED / %d UNPROVABLE / %d INFO）"
              % (verdict, len(findings),
                 sum(1 for x in findings if x["sev"] == "RED"),
                 sum(1 for x in findings if x["sev"] == "UNPROVABLE"),
                 sum(1 for x in findings if x["sev"] == "INFO")))
    return rc


if __name__ == "__main__":
    sys.exit(main())
