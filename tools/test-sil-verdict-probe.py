#!/usr/bin/env python3
"""test-sil-verdict-probe.py — SIL 裁决产出腿常驻门（sil-verdict-probe.py）回归门

背景（2026-11-02 确证发现，本门为其常驻防复发）：RT-E88 修复合规产线监控门位
（all-gates L3 sil-verdict-probe）后复核实证该门**失效型**——判据只读 664 同 uid 可写的
状态观测/loop-state.json 里的 mirror_ro_gate 布尔、无任何完整性校验：同 uid 进程改写
该文件即可把「产出腿停摆」读成绿（亲测：真文件 FAIL exit=1 → 注入副本
mirror_ro_gate={"exp1":true,"exp2":true} → PASS exit=0），即 RT-E88「真相在册无人
订阅」可被订阅者喂假值，常驻红被静音。修复=绿不再由可改写的文件背书：状态面布尔降为
辅证、物理镜像面机械实测升为准据，逐源取交集（绿 ⟺ 每一源「状态面记可信」∧「机械
实测=机制性只读」，机械实测直接调用守护在册判据 self-improve-loop.mirror_source_ro_gate）。

本门覆盖（逻辑层用替身实测口径，端到端层用真 CLI + 环境变量换源，两层互补）：
  逻辑层（monkeypatch 机械实测，判据语义全覆盖）
    A1 绿路对照：状态面全可信 ∧ 机械实测全可信 → rc=0（防「恒红门」自欺：门必须能绿）
    A2 注入翻绿：状态面记可信 ∧ 机械实测拒用 → rc≠0（v1.0 失效点，核心负例）
    A3 未恢复：状态面记拒用 ∧ 机械实测可信 → rc=1（守护未翻转，不早绿）
    A4 真停摆：状态面全拒用 ∧ 机械实测全拒用 → rc=1（停摆语义保留）
    A5 源集不一致（状态面源集 ≠ 在册源集）→ rc=2（不可证即红）
    A6 状态面自相矛盾（扁平读数 vs last_round 逐源读数）→ rc=2（被改写嫌疑）
    A7 缺件/坏 JSON/无 mirror_ro_gate 读数 → rc=2（缺件红，不静默放行）
    A8 读数过期（heartbeat 陈旧）→ rc=1（过期不背书绿）
    A9 机械实测不可得（判据源不可用）→ rc=2（不猜绿）
    A10 源码版本钉缺席（状态面无 daemon_src.sha256＝在役码早于版本钉机制）→ rc=2
    A11 源码版本钉不等（在役载入版本≠盘上判据源＝两套真相并行）→ rc=2
    A12 状态面封条验签失败（内容与守护签发时不一致＝被改写/注入）→ rc=1
    A13 状态面无封条（在役码早于封条机制/封条被抹）→ rc=2（不可证即红）
    A14 守护上轮不信任状态面（state_seal_ok=False）且无隔离条目 → rc=2
    A15 封条未过且守护已隔离条目（state_seal_ok=False＋quarantine_log）→ rc=1
    A16 篡改/注入事件在册（quarantine_log「验签失败」类，sticky）→ rc=1
    A17 状态面落盘件同组可写（mode=664＝改写面开着）→ rc=1
  端到端层（真 CLI + SIL_EXP_MIRROR/SIL_EXP_MIRROR2 换源，零生产写入）
    B1 绿路：源指向真 ro 挂载 + 状态面全可信 → rc=0（真 findmnt 路径，门能翻绿）
    B2 注入翻绿（真 CLI）：状态面全可信 + 源指向可写目录 → rc≠0 且点名「背离」
    B3 真停摆：状态面全拒用 + 源指向可写目录 → rc=1
    B4 生产不变量：对在役 状态观测/loop-state.json 实跑，若 rc=0 则机械实测必须全可信
       （绿 ⟹ 物理面可信——生产面永不出现「假绿」；真停摆期 rc=1/2 均可接受）
退出码：0=全过；任一断言红即非零退出并点名断言。"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_PROBE = os.path.join(_TOOLS, "sil-verdict-probe.py")
_DAEMON = os.path.join(_TOOLS, "self-improve-loop.py")
_STATE = os.path.join(os.path.dirname(_TOOLS), "状态观测", "loop-state.json")

# 被测探针按路径导入（模块名可点、可 monkeypatch 机械实测口径）
_loader = SourceFileLoader("sil_verdict_probe_under_test", _PROBE)
_spec = importlib.util.spec_from_file_location("sil_verdict_probe_under_test", _PROBE,
                                               loader=_loader)
probe = importlib.util.module_from_spec(_spec)
_loader.exec_module(probe)

# 守护在册源集（源名/目录取自在册判据源，源集变化时本门自动跟随，不写死）
_dl = SourceFileLoader("sil_daemon_under_test", _DAEMON)
_ds = importlib.util.spec_from_file_location("sil_daemon_under_test", _DAEMON, loader=_dl)
daemon = importlib.util.module_from_spec(_ds)
_dl.exec_module(daemon)
SOURCES = [s["name"] for s in daemon.exp_sources()]

FAILS = []
PASSES = []


def check(name, cond, detail=""):
    if cond:
        PASSES.append(name)
        print("  [PASS] %s" % name, flush=True)
    else:
        FAILS.append(name)
        print("  [FAIL] %s %s" % (name, detail), flush=True)


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# 盘上判据源（守护源码）此刻的 sha256——「盘上判据版本」的权威读数（动态取，守护
# 源码一改即自动跟随，不写死）。
DISK_GATE_SHA = _sha256_file(_DAEMON)


def mk_state(path, gate, hb=None, detailed=None, rounds=7, src_sha=None,
             with_src=True, with_seal=True, seal_ok=True, quarantine=None,
             tamper=False, mode=0o600):
    """夹具状态面。

    src_sha/with_src：源码版本钉读数（2026-11-03 SIL 环修复批新增的探针⑦ 判据
    前置条件）。默认**带上与盘上判据源一致的版本钉**——即「在役判据＝盘上判据」的
    对齐态；with_src=False 造「版本钉缺席」（在役码早于版本钉机制），src_sha 传
    其它值造「两套真相并行」。

    with_seal/seal_ok/quarantine/tamper/mode：**探针⑧ 判据（2026-11-03 状态面面
    收口批）的前置读数与负例开关**——默认带上**守护格式的有效封条**（判据单一源
    ＝守护在册 seal_state 签发）＋state_seal_ok=True＋落盘件 0600，即「封条过、
    权限面闭」的对齐态；with_seal=False 造「封条缺席」、tamper=True 造「封条验签
    失败（签发后内容被改写）」、seal_ok=False 造「守护上轮不信任这份状态面」、
    quarantine=[...] 造「已隔离条目」、mode=0o664 造「同组可写面开着」。
    既有 A1–A11/B1–B4 断言与期望退出码**一字未改**，仅夹具补齐新判据的前置读数
    （补前置≠弱化断言：新增 A12–A17 六条负例覆盖新判据本身）。"""
    st = {"started_at": now_str(), "rounds": rounds, "commits": ["deadbeef"],
          "heartbeat_ts": hb or now_str(), "mirror_ro_gate": gate}
    if with_src:
        st["daemon_src"] = {"ver": "夹具", "sha256": src_sha or DISK_GATE_SHA,
                            "pid": 0, "loaded_at": now_str()}
    if detailed is not None:
        st["last_round"] = {"ts": now_str(), "outcome": "noop",
                            "experiments": {"mirror": {"ro_gate": detailed}}}
    if with_seal:
        daemon.seal_state(st)                  # 判据单一源＝守护在册 seal_state
        st["state_seal_ok"] = seal_ok
    if quarantine is not None:
        st["quarantine_log"] = quarantine
    if tamper:                                 # 封条签发**之后**改写覆盖段 → 验签失败
        st["verdict_log"] = [{"ts": now_str(), "verdict": "injected",
                              "note": "注入条目（非守护签发）"}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    if mode is not None:
        os.chmod(path, mode)
    return path


def run_probe(state_path, live=None, live_exc=None):
    """跑被测探针 main()（monkeypatch 机械实测口径）→ (rc, stdout)"""
    old_live = probe.live_ro_gate
    if live_exc is not None:
        def boom():
            raise live_exc
        probe.live_ro_gate = boom
    else:
        probe.live_ro_gate = lambda: live
    old_argv = sys.argv
    sys.argv = ["sil-verdict-probe.py", "--state", state_path]
    buf = io.StringIO()
    rc = 0
    try:
        with contextlib.redirect_stdout(buf):
            probe.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = old_argv
        probe.live_ro_gate = old_live
    return rc, buf.getvalue()


def live_all(trusted):
    return {s: (trusted, "夹具机械实测：%s" % ("机制性只读" if trusted else "非机制性只读"))
            for s in SOURCES}


def find_trusted_ro_source():
    """找一个**守护在册判据认可**的可信 ro 源目录（绿路端到端对照用）。

    候选=本机 ro 挂载的可读目录；取舍=用守护自己的 mirror_source_ro_gate 判（判据
    单一源，随守护判据演进自动跟随——不写死某个 snap 路径）。无候选被认可 → 返回
    None（该对照明确标注未跑，不静默当绿）。"""
    try:
        r = subprocess.run(["findmnt", "-rno", "TARGET,OPTIONS"], capture_output=True,
                           text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    cands = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        tgt = parts[0]
        if "/" in tgt:                       # 树形输出前缀（├─/…）剥掉
            tgt = tgt[tgt.index("/"):]
        opts = parts[1].split(",")
        if "ro" in opts and "rw" not in opts and os.path.isdir(tgt) \
                and os.access(tgt, os.R_OK | os.X_OK):
            cands.append(tgt)
    for tgt in cands:
        try:
            trusted, _reason = daemon.mirror_source_ro_gate({"name": "exp1", "dir": tgt})
        except Exception:
            continue
        if trusted:
            return tgt
    return None


def main():
    tmp = tempfile.mkdtemp(prefix="sil-verdict-probe-test-")
    try:
        # ---------------- 逻辑层（monkeypatch 机械实测）----------------
        print("逻辑层（monkeypatch 机械实测口径）:", flush=True)
        p = os.path.join(tmp, "s.json")
        det_true = {s: {"trusted": True, "reason": "夹具"} for s in SOURCES}
        det_false = {s: {"trusted": False, "reason": "夹具"} for s in SOURCES}

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true),
                            live=live_all(True))
        check("A1 绿路对照：状态面全可信 ∧ 机械实测全可信 → rc=0", rc == 0,
              "rc=%s out=%s" % (rc, out[:160]))

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true),
                            live=live_all(False))
        check("A2 注入翻绿被堵：状态面记可信 ∧ 机械实测拒用 → rc≠0", rc != 0,
              "rc=%s" % rc)
        check("A2b 注入翻绿须点名「状态面与机械实测背离」", "背离" in out, out[:160])

        rc, out = run_probe(mk_state(p, {s: False for s in SOURCES}, detailed=det_false),
                            live=live_all(True))
        check("A3 未恢复：状态面记拒用 ∧ 机械实测可信 → rc=1", rc == 1, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {s: False for s in SOURCES}, detailed=det_false),
                            live=live_all(False))
        check("A4 真停摆：状态面全拒用 ∧ 机械实测全拒用 → rc=1", rc == 1, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {SOURCES[0]: True}, detailed=det_true),
                            live=live_all(True))
        check("A5 源集不一致 → rc=2（不可证即红）", rc == 2, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_false),
                            live=live_all(True))
        check("A6 状态面自相矛盾 → rc=2（被改写嫌疑）", rc == 2, "rc=%s" % rc)

        rc, out = run_probe(os.path.join(tmp, "不存在.json"), live=live_all(True))
        check("A7a 状态面缺件 → rc=2", rc == 2, "rc=%s" % rc)
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        rc, out = run_probe(bad, live=live_all(True))
        check("A7b 状态面坏 JSON → rc=2", rc == 2, "rc=%s" % rc)
        rc, out = run_probe(mk_state(p, {}), live=live_all(True))
        check("A7c 无 mirror_ro_gate 读数 → rc=2", rc == 2, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {s: False for s in SOURCES}, detailed=det_false,
                                    hb="2020-01-01 00:00:00"), live=live_all(False))
        check("A8 读数过期 → rc=1（过期不背书绿）", rc == 1, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true),
                            live_exc=RuntimeError("判据源不可用"))
        check("A9 机械实测不可得 → rc=2（不猜绿）", rc == 2, "rc=%s" % rc)

        # A10/A11（2026-11-03 SIL 环修复批）：探针⑦ 源码版本钉对账——状态面读数来自
        # 在役守护载入时的判据，探针实测用的是盘上现码；两者不一致＝两套真相并行，
        # 不可对账 ⇒ rc=2（不可证即红，不猜绿）。
        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    with_src=False), live=live_all(True))
        check("A10 版本钉缺席（在役码早于版本钉机制）→ rc=2", rc == 2, "rc=%s" % rc)
        check("A10b 版本钉缺席须点名「未登记载入源码版本」", "未登记载入源码版本" in out,
              out[:160])

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    src_sha="0" * 64), live=live_all(True))
        check("A11 版本钉不等（在役旧码≠盘上判据＝两套真相并行）→ rc=2", rc == 2,
              "rc=%s" % rc)
        check("A11b 版本钉不等须点名「两套判据并行」", "两套判据并行" in out, out[:160])

        # A12–A17（2026-11-03 状态面面收口批）：探针⑧ 状态面封条+权限面对账——
        # 本门读的状态面是同 uid/同组可写的文件，此前对封条**完全失明**（内容面
        # 机制在、监测面不在）：注入者改写状态面后由守护下一轮重新签发封条即被洗白。
        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    tamper=True), live=live_all(True))
        check("A12 封条验签失败（状态面被改写/注入）→ rc=1", rc == 1, "rc=%s" % rc)
        check("A12b 封条验签失败须点名「封条验签失败」", "封条验签失败" in out, out[:200])

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    with_seal=False), live=live_all(True))
        check("A13 封条缺席（在役码早于封条机制/封条被抹）→ rc=2（不可证即红）",
              rc == 2, "rc=%s" % rc)
        check("A13b 封条缺席须点名「无封条」", "无封条" in out, out[:200])

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    seal_ok=False), live=live_all(True))
        check("A14 守护上轮不信任状态面（state_seal_ok=False，无隔离条目）→ rc=2",
              rc == 2, "rc=%s" % rc)

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    seal_ok=False,
                                    quarantine=[{"ts": now_str(),
                                                 "section": "verdict_log", "n": 3,
                                                 "digest": "x", "sample": [],
                                                 "reason": "状态面封条验签失败（疑 loop-state "
                                                           "被篡改/注入）"}]),
                            live=live_all(True))
        check("A15 封条未过且守护已隔离条目 → rc=1（注入发生过，红）", rc == 1, "rc=%s" % rc)
        check("A15b 已隔离条目须点名「隔离条目」", "隔离条目" in out, out[:200])

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    quarantine=[{"ts": now_str(),
                                                 "section": "verdict_queue", "n": 1,
                                                 "digest": "y", "sample": [],
                                                 "reason": "状态面封条验签失败（疑 loop-state "
                                                           "被篡改/注入）"}]),
                            live=live_all(True))
        check("A16 篡改/注入事件在册（sticky，不许被重新签发洗白）→ rc=1", rc == 1,
              "rc=%s" % rc)
        check("A16b 篡改事件在册须点名「篡改/注入事件在册」", "篡改/注入事件在册" in out,
              out[:200])

        rc, out = run_probe(mk_state(p, {s: True for s in SOURCES}, detailed=det_true,
                                    mode=0o664), live=live_all(True))
        check("A17 落盘件同组可写（mode=664＝改写面开着）→ rc=1", rc == 1, "rc=%s" % rc)
        check("A17b 权限过宽须点名「权限过宽」", "权限过宽" in out, out[:200])

        # A18（v1.5，2026-11-03 判据读出通道换件面）：⑨ 独立复算对账——④机械实测与
        # 守护判据共用同一 findmnt 读出，若判据按裸名走进程 PATH 解析（守护 v1.3.13
        # 及以前的形态），同 uid 在 PATH 前置可写目录落恒打印 ro 的假件即**同时换掉
        # 两腿读出**（④交叉核验结构性失明；守护 v1.3.14 沙盒复现在案）。判据：判据
        # 模块解析 ≠ 本进程独立按 _CS_PATH 复算 → live_ro_gate 抛 RuntimeError（调用
        # 方 fail-closed rc=2 不猜绿）；判据无解析口 → 同红；逐字一致 → 实测继续
        # （不误红）。
        _real_loader18 = probe.load_gate_module
        _real_resolve18 = probe._resolve_system_tool

        class _FakeMod18:
            """判据模块替身：_system_tool 可编程（模拟被换件/在册 v1.3.14 口径）。"""
            def __init__(self, tool):
                self._tool = tool
            def _system_tool(self, name):
                return self._tool(name)
            def exp_sources(self):
                return [{"name": "exp1", "dir": tmp, "glob": "E1-*"}]
            def mirror_source_ro_gate(self, src, mount_opts=None):
                return False, "夹具机械实测"

        def _hijacked18(name):                    # 模拟被换件判据：解析到 PATH 前置假件
            return os.path.join(tmp, "fakebin-e18", name)

        class _OldMod18:                          # 模拟在役码早于 v1.3.14（无解析口）
            pass

        try:
            probe.load_gate_module = lambda *a, **k: _FakeMod18(_hijacked18)
            try:
                probe.live_ro_gate()
                a18 = "未抛（红未触发＝回归）"
            except RuntimeError as e:
                a18 = str(e)
            check("A18 判据读出被换件（判据解析=PATH 假件 ≠ 独立复算）→ live_ro_gate "
                  "抛 RuntimeError（调用方 fail-closed rc=2 不猜绿）",
                  "独立复算不一致" in a18 and "不猜绿" in a18 and "PATH 换件" in a18,
                  str(a18)[:140])

            probe.load_gate_module = lambda *a, **k: _FakeMod18(_real_resolve18)
            ok18 = probe.live_ro_gate()
            check("A18b 判据解析=独立复算逐字一致（v1.3.14 在册口径）→ 实测继续不误红",
                  isinstance(ok18, dict) and "exp1" in ok18
                  and ok18["exp1"] == (False, "夹具机械实测"), str(ok18)[:90])

            probe.load_gate_module = lambda *a, **k: _OldMod18()
            try:
                probe.live_ro_gate()
                a18c = "未抛（红未触发＝回归）"
            except RuntimeError as e:
                a18c = str(e)
            check("A18c 判据无 _system_tool 读出解析口（版本过旧/判据源被改）→ 抛 "
                  "RuntimeError", "_system_tool 读出解析口" in a18c, str(a18c)[:110])
        finally:
            probe.load_gate_module = _real_loader18

        # ---------------- 端到端层（真 CLI + 换源，零生产写入）----------------
        print("端到端层（真 CLI + SIL_EXP_MIRROR/SIL_EXP_MIRROR2 换源）:", flush=True)
        w1 = os.path.join(tmp, "m1")
        w2 = os.path.join(tmp, "m2")
        os.makedirs(w1, exist_ok=True)
        os.makedirs(w2, exist_ok=True)
        green = mk_state(os.path.join(tmp, "green.json"),
                         {s: True for s in SOURCES}, detailed=det_true)
        red = mk_state(os.path.join(tmp, "red.json"),
                       {s: False for s in SOURCES}, detailed=det_false)

        def cli(state_path, d1, d2):
            env = dict(os.environ)
            env["SIL_EXP_MIRROR"] = d1
            env["SIL_EXP_MIRROR2"] = d2
            r = subprocess.run([sys.executable, "-I", _PROBE, "--state", state_path],
                               capture_output=True, text=True, env=env, timeout=120)
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        rc, out = cli(green, w1, w2)
        check("B2 注入翻绿（真 CLI）：状态面全可信 + 源可写 → rc≠0 且点名背离",
              rc != 0 and "背离" in out, "rc=%s out=%s" % (rc, out[:160]))

        rc, out = cli(red, w1, w2)
        check("B3 真停摆（真 CLI）：状态面全拒用 + 源可写 → rc=1", rc == 1,
              "rc=%s out=%s" % (rc, out[:160]))

        ro = find_trusted_ro_source()
        if ro:
            rc, out = cli(green, ro, ro)
            check("B1 绿路（真 CLI）：源指向守护判据认可的真 ro 挂载 + 状态面全可信 → rc=0",
                  rc == 0, "rc=%s out=%s" % (rc, out[:200]))
        else:
            print("  [说明] 本机未找到被守护判据认可的 ro 挂载 → B1 绿路端到端对照未跑"
                  "（绿路由 A1 逻辑层对照覆盖；不静默当绿）", flush=True)

        # B4 生产不变量：绿 ⟹ 物理面可信（在役状态面实跑）
        if os.path.isfile(_STATE):
            rc, out = cli(_STATE, os.environ.get("SIL_EXP_MIRROR",
                                                  daemon.CFG["exp_mirror"]),
                          os.environ.get("SIL_EXP_MIRROR2", daemon.CFG["exp_mirror2"]))
            if rc == 0:
                live = probe.live_ro_gate()
                all_trusted = bool(live) and all(v[0] for v in live.values())
                check("B4 生产不变量：rc=0 ⟹ 机械实测全可信（生产面无假绿）", all_trusted,
                      "live=%s" % live)
            else:
                check("B4 生产不变量：在役状态面非绿（rc=%s，真停摆/缺件皆可接受，红）"
                      % rc, rc != 0, "rc=%s" % rc)
        else:
            print("  [说明] 在役 状态观测/loop-state.json 不在位 → B4 未跑（缺件红由 A7 覆盖）",
                  flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("小计：PASS=%d FAIL=%d" % (len(PASSES), len(FAILS)), flush=True)
    if FAILS:
        print("FAIL %s" % ",".join(FAILS), flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
