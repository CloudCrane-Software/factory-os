#!/usr/bin/env python3
"""test-sil-version-pin.py — 「在役源码版本钉」三件套回归门（2026-11-03 SIL 环修复批）

修的缺陷（2026-11-03 确证发现，severity=high）：轮4 的 SIL 修复整体未在役——
在役守护跑的是 06:53 启动时载入的旧码，盘上现码（17:53）已含 RT-E85④ 只读门收紧、
v1.3.9 三锚封条、v1.3.10 逃逸符号链接门，但**在役进程一个都没跑**（守护只在启动
时载入源码，无版本钉、无源变更即重启）；且在役旧判据**更宽松**（rw 挂载 + chmod
收权 ⇒ trusted=True＝RT-E85④ 旁路仍开，沙盒 A/B 实证），而巡检探针量的是**盘上
现码**⇒ 同一镜像面两套结论（探针报「双源拒用/停摆」、守护写盘旧口径「RT-E12①」），
两套真相并行且无人对账。

修法（三件套，判据单一源、只读面不弱化）：
  ① 守护 tools/self-improve-loop.py v1.3.11：起跑即把**载入时**自身源码 sha256
     登记进状态面 st["daemon_src"]（每次写盘随封条同行）——「在役跑哪份码」成为
     可核验事实；
  ② 监督面 tools/factory-keepalive.py：判活追加「源码版本钉」**必要条件**——在役
     登记版本 ≠ 盘上源码 sha256 ⇒ 判死 ⇒ 走既有 fix_guard 拉起新码（=「修复落盘
     自动生效」的耐久性门）；keepalive 自身源码变更 ⇒ os.execv 自我重载；
  ③ 巡检面 tools/sil-verdict-probe.py：追加 ⑦ 版本钉对账——在役版本 ≠ 盘上判据
     版本 ⇒ rc=2（两套真相并行、不可对账，不猜绿）。

本门覆盖（全部零写生产面：夹具落 $HOME 自建 scratch，完工即删）：
  V1 守护侧·登记正确：daemon_src_stamp() 的 sha256 == 盘上 tools/self-improve-loop.py
     的 sha256（钉的就是它载入的那一份）
  V2 守护侧·写盘即带钉：save_state() 落盘件含 daemon_src（调用方不预置也带）
  V3 守护侧·钉是「载入时」语义：同一进程内两次取戳 sha256 恒等（不随盘上改动漂移）
  V4 监督面·版本钉判据三态：对齐 ⇒ 通过；不等 ⇒ 判死（文案含「两套真相并行」）；
     缺席 ⇒ 判死（文案含「未登记载入版本」＝在役码早于版本钉机制）
  V5 监督面·判活集成：真起一个哑进程冒充在役守护（argv basename 命中），
     状态面登记旧版本 ⇒ check_guard 判死且 detail 点名「版本钉未对齐」（会走
     fix_guard 拉起新码）；登记对齐版本 ⇒ 不误杀在役守护（detail 含「源码版本钉：对齐」）
  V6 巡检面·版本对账口径：probe.gate_src_sha256() == 盘上守护源码 sha256
     （探针实测所用判据版本 == 盘上判据源版本）
  V7 监督面·自我重载判据：源码未变 ⇒ 不重载；源码变更 ⇒ 需重载并给出新指纹；
     新码语法坏 ⇒ 不重载（护栏②：不能把监督面换死）
  V8 在役面·版本钉落地实况：在役 状态观测/loop-state.json 的 daemon_src.sha256
     == 盘上守护源码 sha256（在役守护已载入盘上判据；不等＝修复未在役，本门红）

用法：python3 -I tools/test-sil-version-pin.py
退出码：0=全过；任一断言红即非零退出并点名断言。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WS, "tools")
DAEMON = os.path.join(TOOLS, "self-improve-loop.py")
KEEPALIVE = os.path.join(TOOLS, "factory-keepalive.py")
PROBE = os.path.join(TOOLS, "sil-verdict-probe.py")
SIL_STATE = os.path.join(WS, "状态观测", "loop-state.json")
SCRATCH = os.path.join(os.path.expanduser("~"), ".tmp_test_sil_version_pin")

FAILS = []
NCASE = 0


def check(name, cond, detail=""):
    global NCASE
    NCASE += 1
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)
    if not cond:
        FAILS.append(name)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def write_state(path, stamp=None, extra=None):
    st = {"rounds": 3, "heartbeat_ts": time.strftime("%Y-%m-%d %H:%M:%S"),
          "mirror_ro_gate": {"exp1": False, "exp2": False}}
    if stamp is not None:
        st["daemon_src"] = {"ver": "夹具", "sha256": stamp, "pid": 0,
                            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if extra:
        st.update(extra)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    return path


def main():
    if not (os.path.isfile(DAEMON) and os.path.isfile(KEEPALIVE)
            and os.path.isfile(PROBE)):
        print("  [FAIL] 门件缺失：守护/keepalive/探针任一不在位")
        return 1
    disk_sha = sha256_file(DAEMON)
    daemon = load("sil_daemon_pin_under_test", DAEMON)
    keep = load("sil_keepalive_pin_under_test", KEEPALIVE)
    probe = load("sil_probe_pin_under_test", PROBE)
    os.makedirs(SCRATCH, exist_ok=True)
    dummy = None
    try:
        # ---------------- V1 守护侧：登记的指纹 == 盘上判据源指纹 ----------------
        stamp = daemon.daemon_src_stamp()
        check("V1 守护登记的载入版本 sha256 == 盘上守护源码 sha256",
              stamp.get("sha256") == disk_sha,
              "登记=%s 盘上=%s" % (str(stamp.get("sha256"))[:12], disk_sha[:12]))
        check("V1b 登记内容含版本号/进程号/载入时刻",
              bool(stamp.get("ver")) and stamp.get("pid") == os.getpid()
              and bool(stamp.get("loaded_at")), json.dumps(stamp, ensure_ascii=False))

        # ---------------- V2 守护侧：写盘即带钉（调用方不预置也带） ----------------
        st_tmp = os.path.join(SCRATCH, "loop-state.json")
        old_cfg = dict(daemon.CFG)
        try:
            daemon.CFG["state"] = st_tmp
            daemon.save_state({"rounds": 1, "verdict_queue": [],
                               "auto_create_retry": [], "projection_todos": []})
        finally:
            daemon.CFG.update(old_cfg)
        on_disk = {}
        if os.path.isfile(st_tmp):
            with open(st_tmp, encoding="utf-8") as fh:
                on_disk = json.load(fh)
        check("V2 save_state 落盘件含 daemon_src 版本钉（写盘即带钉）",
              isinstance(on_disk.get("daemon_src"), dict)
              and on_disk["daemon_src"].get("sha256") == disk_sha,
              "落盘=%s" % json.dumps(on_disk.get("daemon_src"), ensure_ascii=False))

        # ---------------- V3 守护侧：钉是「载入时」语义（进程内恒定） ----------------
        s1 = daemon.daemon_src_stamp()["sha256"]
        s2 = daemon.daemon_src_stamp()["sha256"]
        check("V3 同一进程内两次取戳 sha256 恒等（钉=载入时指纹，非盘上实时指纹）",
              s1 == s2 == disk_sha, "%s/%s" % (s1[:12], s2[:12]))

        # ---------------- V4 监督面：版本钉判据三态 ----------------
        spec = {"name": "sil-pin-fixture", "script": "self-improve-loop.py",
                "state": os.path.join(SCRATCH, "pin-state.json"),
                "log": os.path.join(SCRATCH, "pin.log"),
                "stale_s": 300, "grace_s": 0,
                "cmd": ["python3", "tools/self-improve-loop.py"],
                "src_pin": "tools/self-improve-loop.py",
                "src_pin_state_key": "daemon_src"}
        write_state(spec["state"], stamp=disk_sha)
        ok, why = keep.src_pin_verdict(spec, "tools/self-improve-loop.py")
        check("V4a 版本钉对齐（在役登记 == 盘上源码）⇒ 通过", ok is True, why[:120])

        write_state(spec["state"], stamp="0" * 64)
        ok, why = keep.src_pin_verdict(spec, "tools/self-improve-loop.py")
        check("V4b 版本钉不等（在役旧码 ≠ 盘上判据）⇒ 判死", ok is False, why[:120])
        check("V4c 版本钉不等须点名「两套真相并行」", "两套真相并行" in why, why[:140])

        write_state(spec["state"], stamp=None)
        ok, why = keep.src_pin_verdict(spec, "tools/self-improve-loop.py")
        check("V4d 版本钉缺席（在役码早于版本钉机制）⇒ 判死", ok is False, why[:120])
        check("V4e 版本钉缺席须点名「未登记载入版本」", "未登记载入版本" in why, why[:140])

        unreadable = dict(spec)
        unreadable["src_pin"] = "tools/不存在的件.py"
        ok, why = keep.src_pin_verdict(unreadable, "tools/不存在的件.py")
        check("V4f 盘上源码不可读 ⇒ 判不准不处置（保持原判，不制造杀拉循环）",
              ok is True and "不可读" in why, why[:120])

        # ---------------- V5 监督面：判活集成（真哑进程冒充在役守护） ----------------
        fake_script = os.path.join(SCRATCH, "fake-pin-guard.py")
        with open(fake_script, "w", encoding="utf-8") as fh:
            fh.write("import time\ntime.sleep(600)\n")
        dummy = subprocess.Popen([sys.executable, fake_script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        live_spec = {"name": "fake-pin-guard", "script": "fake-pin-guard.py",
                     "state": spec["state"], "log": spec["log"],
                     "stale_s": 300, "grace_s": 0,
                     "cmd": [sys.executable, fake_script],
                     "src_pin": "tools/self-improve-loop.py",
                     "src_pin_state_key": "daemon_src"}
        # 落一份新鲜日志，使活性判据本身成立（否则「进程不在/读数不新鲜」会先判死，
        # 掩盖版本钉这一条腿的判定）
        with open(live_spec["log"], "w", encoding="utf-8") as fh:
            fh.write("alive\n")
        write_state(live_spec["state"], stamp="0" * 64)
        alive, detail = keep.check_guard(time.time(), live_spec)
        check("V5a 在役登记旧版本 ⇒ 判死（会走 fix_guard 拉起新码）", alive is False,
              detail[:160])
        check("V5b 判死理由须点名「版本钉未对齐」", "版本钉未对齐" in detail, detail[:160])

        write_state(live_spec["state"], stamp=disk_sha)
        alive, detail = keep.check_guard(time.time(), live_spec)
        check("V5c 在役登记 == 盘上源码 ⇒ 不误杀在役守护", alive is True, detail[:160])
        check("V5d 活判理由须含「源码版本钉：对齐」", "源码版本钉：对齐" in detail,
              detail[:160])

        # ---------------- V6 巡检面：版本对账口径 ----------------
        check("V6 探针实测所用判据版本 == 盘上守护源码 sha256",
              probe.gate_src_sha256() == disk_sha,
              "探针=%s 盘上=%s" % (probe.gate_src_sha256()[:12], disk_sha[:12]))

        # ---------------- V7 监督面：自我重载判据（三道护栏） ----------------
        keep_src = os.path.join(SCRATCH, "keepalive-copy.py")
        shutil.copyfile(KEEPALIVE, keep_src)
        old_src, old_sha = keep.KEEPALIVE_SRC, keep.KEEPALIVE_SRC_SHA
        try:
            keep.KEEPALIVE_SRC = keep_src
            keep.KEEPALIVE_SRC_SHA = sha256_file(keep_src)
            need, why = keep._self_refresh_verdict()
            check("V7a 源码未变 ⇒ 不需自我重载", need is False, why[:120])

            with open(keep_src, "a", encoding="utf-8") as fh:
                fh.write("\n# 夹具追加一行（模拟盘上源码变更）\n")
            need, why = keep._self_refresh_verdict()
            check("V7b 源码变更 ⇒ 需自我重载且给出新指纹", need is True and why,
                  "need=%s why=%s" % (need, str(why)[:12]))

            with open(keep_src, "a", encoding="utf-8") as fh:
                fh.write("\ndef broken(:\n")     # 语法坏件
            need, why = keep._self_refresh_verdict()
            check("V7c 新码语法坏 ⇒ 不重载（护栏②：不得把监督面换死）",
                  need is False and "不可编译" in why, why[:120])
        finally:
            keep.KEEPALIVE_SRC, keep.KEEPALIVE_SRC_SHA = old_src, old_sha

        # ---------------- V8 在役面：版本钉落地实况 ----------------
        if os.path.isfile(SIL_STATE):
            with open(SIL_STATE, encoding="utf-8") as fh:
                live_st = json.load(fh)
            live_sha = ((live_st.get("daemon_src") or {}) or {}).get("sha256")
            check("V8 在役守护已登记版本钉且 == 盘上守护源码 sha256（在役=盘上）",
                  live_sha == disk_sha,
                  "在役=%s 盘上=%s（在役无钉=在役码早于版本钉机制，修复未在役）"
                  % (str(live_sha)[:12], disk_sha[:12]))
        else:
            print("  [说明] 在役 状态观测/loop-state.json 不在位 → V8 未跑（缺件由"
                  "其它门覆盖）", flush=True)
    finally:
        if dummy is not None:
            try:
                dummy.terminate()
                dummy.wait(timeout=10)
            except Exception:
                pass
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("小计：PASS=%d FAIL=%d" % (NCASE - len(FAILS), len(FAILS)), flush=True)
    if FAILS:
        print("FAIL %s" % ",".join(FAILS), flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
