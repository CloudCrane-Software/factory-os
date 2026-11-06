#!/usr/bin/env python3
"""test-router-version-pin.py — event-router「在役源码版本钉」回归门（2026-11-03 RT 修复批）

被测缺陷（2026-11-03 确证发现，severity=high）：**版本钉自愈**——版本钉在每次写盘时
**现读盘面文件重算** sha256，而不是冻结「本进程载入时」的指纹。后果：盘面源码一改，
在役进程（仍跑旧码）的下一次 save_state() 就把**新盘面指纹**登记成「在役载入版本」，
于是钉 ≡ 盘面恒等 ⇒ 对账面永远看不到漂移 ⇒ 版本钉机制自我失效、假绿。这正是该机制
要治的病（「修复落盘≠在役生效」无人对账）：RT-E157/RT-E160/RT-E169 三批修复整批只落
本地、在役守护仍跑旧码 30h+ 无人发现，同款缺陷第二次复发（第一次＝无钉；第二次＝有钉
但钉自愈）。

对账两端（与 tools/live-daemon-version-probe.py 同一判据）：
  ①在役守护**载入时**的判据源指纹（状态面 st["daemon_src"].sha256，守护每次写盘随封条
    登记）；②盘上判据源此刻的 sha256。

本门覆盖（全部零写生产面：夹具落 $HOME 自建 scratch，完工即删；真树只读）：
  R1 钉的**载入时**语义：同一进程内两次取戳 sha256 恒等（不随盘面改动漂移）——
     钉钉的是「载入的那一份」，不是「此刻盘上的那一份」。
  R2 钉 ≠ 盘面时，钉不得被盘面改动**自愈**成盘面指纹（真树副本改盘面后取戳，
     钉必须仍是旧码指纹 ⇒ 漂移可测；这是本批的核心断言）。
  R3 save_state() 落盘件必含 daemon_src 版本钉（写盘即带钉，调用方不预置也带）。
  R4 监督面（tools/factory-keepalive.py）版本钉判据三态：对齐⇒通过；不等⇒判死
     （文案含「两套真相并行」）；缺席⇒判死（文案含「未登记载入版本」＝在役码早于
     版本钉机制）。
  R5 巡检面（tools/live-daemon-version-probe.py）版本对账口径：探针判 DRIFT 的那条
     夹具路径在本守护的钉语义下**确实判红**（不静默 SKIP、不猜绿）。
  R6 **判别力负向对照（红队必备）**：修前件（tools/event-router.py.20261031-pre-RT-
     versionpin.bak）的钉**必须自愈**（改盘面后取戳随盘面变）——若修前件也不自愈，
     说明本门测不出本批要治的病 ⇒ 本门无判别力 ⇒ 红。
  R7 在役面·版本钉落地实况：在役 状态面 kb-seed/sandbox/.router-state.json 的
     daemon_src.sha256 ≡ 盘上 tools/event-router.py 的 sha256（在役守护已载入盘上
     判据；不等＝修复未在役，本门红）。

用法：python3 -I tools/test-router-version-pin.py
退出码：0=全过；任一断言红即非零退出并点名断言。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader

WS = "/home/pan-ding/workspace/agent黑灯工厂"
TOOLS = f"{WS}/tools"
ROUTER = f"{TOOLS}/event-router.py"
ROUTER_BAK = f"{TOOLS}/event-router.py.20261031-pre-RT-versionpin.bak"
KEEPALIVE = f"{TOOLS}/factory-keepalive.py"
PROBE = f"{TOOLS}/live-daemon-version-probe.py"
LIVE_STATE = f"{WS}/kb-seed/sandbox/.router-state.json"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(name, path):
    """装载守护/监督面/探针模块（.bak 后缀件 loader 需显式指定）。"""
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def copy_tree(src, dst):
    """拷贝真件到 scratch（供「改盘面后取戳」夹具用，零改动真树）。"""
    os.makedirs(dst, exist_ok=True)
    shutil.copyfile(src, os.path.join(dst, os.path.basename(src)))
    return os.path.join(dst, os.path.basename(src))


def main():
    for p in (ROUTER, ROUTER_BAK, KEEPALIVE, PROBE):
        if not os.path.isfile(p):
            print(f"  [FAIL] 门件缺失：{p}")
            return 1
    scratch = tempfile.mkdtemp(prefix="router-version-pin-")
    try:
        disk_sha = sha256_file(ROUTER)
        router = load("router_version_pin_under_test", ROUTER)

        # ---------------- R1 钉的「载入时」语义：两次取戳恒等 ----------------
        s1 = router.daemon_src_stamp()
        s2 = router.daemon_src_stamp()
        check("R1 同一进程内两次取戳 sha256 恒等（钉=载入时指纹，非盘上实时指纹）",
              s1.get("sha256") == s2.get("sha256"),
              f"{str(s1.get('sha256'))[:12]} vs {str(s2.get('sha256'))[:12]}")

        # ---------------- R2 钉不得被盘面改动自愈（核心断言） ----------------
        # 用 scratch 副本模拟「在役进程起跑后，盘面源码被并行批改掉」：
        # 副本装载（=载入时刻）→ 改副本盘面 → 再取戳，钉必须仍是载入时的旧码指纹。
        copy_path = copy_tree(ROUTER, os.path.join(scratch, "frozen"))
        frozen_mod = load("router_version_pin_frozen", copy_path)
        pin_before = frozen_mod.daemon_src_stamp().get("sha256")
        with open(copy_path, "a", encoding="utf-8") as fh:
            fh.write("\n# 夹具：模拟并行批在守护起跑后改动盘面源码\n")
        disk_after = sha256_file(copy_path)
        pin_after = frozen_mod.daemon_src_stamp().get("sha256")
        check("R2a 盘面改动后钉仍=载入时指纹（钉不自愈）",
              pin_after == pin_before,
              f"改前={str(pin_before)[:12]} 改后={str(pin_after)[:12]}")
        check("R2b 盘面确实变了且钉≠新盘面指纹（漂移可测）",
              disk_after != pin_after,
              f"盘面={disk_after[:12]} 钉={str(pin_after)[:12]}")

        # ---------------- R3 写盘即带钉 ----------------
        # save_state() 写生产状态面——不真写：把 STATE_F 重定向到 scratch 后再调。
        st_path = os.path.join(scratch, "state.json")
        old_state_f = router.STATE_F
        old_dry = router.DRY
        try:
            router.STATE_F = st_path
            router.DRY = False
            router.save_state({"results": {}})
        finally:
            router.STATE_F = old_state_f
            router.DRY = old_dry
        stamped = {}
        if os.path.isfile(st_path):
            with open(st_path, encoding="utf-8") as fh:
                stamped = json.load(fh)
        rec = stamped.get("daemon_src") or {}
        check("R3 save_state() 落盘件含 daemon_src 版本钉（写盘即带钉）",
              bool(rec.get("sha256")),
              f"落盘 daemon_src={json.dumps(rec, ensure_ascii=False)[:120]}")

        # ---------------- R4 监督面版本钉判据三态 ----------------
        keep = load("keepalive_router_version_pin_under_test", KEEPALIVE)
        spec = {"state": st_path, "src_pin_state_key": "daemon_src"}
        # R4a 钉缺席 ⇒ 判死（点名「未登记载入版本」）
        with open(st_path, "w", encoding="utf-8") as fh:
            json.dump({"results": {}}, fh)
        ok, why = keep.src_pin_verdict(spec, "tools/event-router.py")
        check("R4a 版本钉缺席 ⇒ 判死（文案含「未登记载入版本」）",
              (not ok) and "未登记载入版本" in why, why)
        # R4b 钉≠盘面 ⇒ 判死（点名「两套真相并行」）
        with open(st_path, "w", encoding="utf-8") as fh:
            json.dump({"daemon_src": {"sha256": "0" * 64}}, fh)
        ok, why = keep.src_pin_verdict(spec, "tools/event-router.py")
        check("R4b 版本钉≠盘上源码 ⇒ 判死（文案含「两套真相并行」）",
              (not ok) and "两套真相并行" in why, why)
        # R4c 钉≡盘面 ⇒ 通过（不误杀在役守护）
        with open(st_path, "w", encoding="utf-8") as fh:
            json.dump({"daemon_src": {"sha256": disk_sha}}, fh)
        ok, why = keep.src_pin_verdict(spec, "tools/event-router.py")
        check("R4c 版本钉≡盘上源码 ⇒ 通过（不误杀在役守护）",
              ok and "对齐" in why, why)

        # ---------------- R5 巡检面判红路径 ----------------
        probe = load("router_version_probe_under_test", PROBE)
        verdict, why = probe.judge(disk_sha, os.path.getmtime(ROUTER),
                                   time.time() - 10, "0" * 64, None)
        check("R5 探针判定核：钉≠盘面 ⇒ DRIFT（对账面判红，不猜绿）",
              verdict == "DRIFT", f"{verdict}: {why}")
        verdict_ok, why_ok = probe.judge(disk_sha, os.path.getmtime(ROUTER),
                                         time.time() - 10, disk_sha, None)
        check("R5b 探针判定核：钉≡盘面 ⇒ ALIGNED（对齐不误红）",
              verdict_ok == "ALIGNED", f"{verdict_ok}: {why_ok}")

        # ---------------- R6 判别力负向对照：修前件必须自愈 ----------------
        bak_path = copy_tree(ROUTER_BAK, os.path.join(scratch, "prefix"))
        bak_mod = load("router_version_pin_prefix", bak_path)
        bak_pin_before = bak_mod.daemon_src_stamp().get("sha256")
        with open(bak_path, "a", encoding="utf-8") as fh:
            fh.write("\n# 夹具：并行批改盘面（修前件）\n")
        bak_pin_after = bak_mod.daemon_src_stamp().get("sha256")
        self_heals = bak_pin_after != bak_pin_before
        check("R6 判别力负控：修前件（.bak）的钉会随盘面改动漂移＝本门测得出本批要治的病",
              self_heals,
              f"修前件改盘面前={str(bak_pin_before)[:12]} 改后={str(bak_pin_after)[:12]}"
              "（两者相同⇒修前件不自愈⇒本门无判别力）")

        # ---------------- R7 在役面：钉 ≡ 盘上源码 ----------------
        live_ok, live_detail = False, "在役状态面不可读"
        if os.path.isfile(LIVE_STATE):
            try:
                with open(LIVE_STATE, encoding="utf-8") as fh:
                    live = json.load(fh)
                live_sha = ((live.get("daemon_src") or {}).get("sha256"))
                live_ok = (live_sha == disk_sha)
                live_detail = (f"在役={str(live_sha)[:12]} 盘上={disk_sha[:12]}"
                               f"（不等＝修复未在役）")
            except (OSError, ValueError) as e:
                live_detail = f"在役状态面不可读：{type(e).__name__}: {e}"
        check("R7 在役守护已载入盘上判据（状态面钉 ≡ 盘上源码 sha256）",
              live_ok, live_detail)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(f"小计：PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  [FAIL] {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
