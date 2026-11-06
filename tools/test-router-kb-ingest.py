#!/usr/bin/env python3
"""test-router-kb-ingest.py — 冲刺批2 第二步的接线回归：event-router → kb 入库。

工单判据：tools/event-router.py 在 registry admit/verify 聚合成功处（verified 状态落定后）
追加一次 kb 入库调用；幂等；subprocess 超时基线 600s（2026-10-31 实测重标，原 ≤120s；
2026-11-01 起按 registry verified 规模自适应=DEB-5a 内层帽，下限仍 600s）；
失败只记日志不阻塞主循环；
沿用 .router-STOP 熔断；ROUTER_DRY 干跑模式下只记日志不落库；入库成功记一行 changelog。

检查项：
  R1 常量口径：KB_INGEST_TIMEOUT_BASELINE == 600（2026-10-31 实测重标，原 ≤120s）且
     KB_INGEST_TIMEOUT 恰等于按当前 registry verified 相对校准点 17986 线性外推的
     自适应值（2026-11-01 DEB-5a 内层帽：600 静态帽被 verified 17986→23510 增长击穿，
     并发门跑重载下 R4/R8 假红——与 all-gates.sh 外层帽同病同修）。断言不比原「==600」
     松：钉死基线常量精确等值 + 本测试用同一公式独立重算外推值等值（防静默调参）；
     调的是 tools/kb-ingest.py --status verified；目标 kb/kb.db
  R2 DRY 干跑：只记日志，不跑子进程、不建库、不写 changelog
  R3 STOP 熔断：STOP 在位 → 跳过，不跑子进程、不写 changelog
  R4 成功路径：真跑 kb-ingest（临时库）→ 返回摘要；changelog 恰好多一行；库里确有原子，
     且 content 与 kb/import_registry.py 的 _build_content 逐字节一致（口径统一接线生效）
  R5 幂等：同一临时库再调一次 → new=0 updated=0 unchanged=N，content 不变
  R6 失败路径（exit≠0 / 输出不可解析）：只记日志，不写 changelog，不抛异常
  R7 超时路径（KB_INGEST_TIMEOUT 临时压到 1s + 睡眠桩）：TimeoutExpired 被吞掉，不抛异常
  R8 端到端接线：构造一份 uphold 达标的验证回报走 handle_verify_report → registry admit
     （打桩）+ kb 入库（真跑）+ 两行 changelog + 卡状态 passed
  R9 既有行为不回退：主循环 STOP 检查、DRY 门（save_state/poll_harvest/registry_admit/
     make_portal_seed）、状态文件防重放键都还在（源码级结构断言）
  R10 混合裁决 admit 口径（2026-10-31 RT 审计修复）：卡通过率达标时只 admit uphold
     原子，refute/unverifiable 不随卡搭车入库；changelog 如实记录排除条数（admit/kb
     入库双打桩，零写生产库）
  R11 quote_check 机械真值对账（2026-11-01 RT 修复）：verdict=uphold 而 quote_check
     =false 的原子不得入库（机器回查引文未证实；历史 578 条坏引文经此通道放行），
     保留 candidate、卡级通过率口径不变、changelog 如实记录排除条数；uphold∧qc=true
     原子照常 admit（admit/kb 入库双打桩，零写生产库）

用法：python3 tools/test-router-kb-ingest.py [--keep]
退出码：0 全过；1 断言失败；2 前置不满足。
临时库/临时目录建在 $HOME 下自建目录（/tmp 配额有限），默认完工即删。零网络、零密钥。
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
HOME = os.path.expanduser("~")
ROUTER = os.path.join(WS, "tools", "event-router.py")
ROUTER_INGEST = os.path.join(WS, "tools", "kb-ingest.py")  # 生产调用目标（用例里改完要还原）
# 2026-10-31 DEB-5：临时目录按 PID 隔离（原为固定路径 ~/kbrouter-ingest-scratch）。
# 实测：两次 all-gates --fast 并发跑同一台机（19:21:15 与 19:30:42 两次）共享同一个临时
# 目录，互相 rmtree 对方的 case 目录 → 双方用例同时红（一方「原子集合变了（+0 / -12281)」
# "、另一方「OperationalError: unable to open database file」）。本门同源同病：
# case-N/changelog.md 与临时库都在同一个固定目录下。断言一字未动，只改临时目录命名。
_SCRATCH_BASE = "kbrouter-ingest-scratch"
SCRATCH = os.path.join(HOME, "%s-%d" % (_SCRATCH_BASE, os.getpid()))
REGISTRY = os.path.join(WS, "kb-seed", "registry.db")


def purge_stale_scratch(base):
    """清掉本机已退出进程遗留的同前缀临时目录（PID 不在了才删，不碰在跑的那份）。"""
    for d in glob.glob(os.path.join(HOME, "%s-*" % base)):
        try:
            pid = int(os.path.basename(d).rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass  # 权限/其它异常一律不删，留给人工

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def load_router(name, dry):
    """按 ROUTER_DRY 取/清环境变量后再加载模块（DRY 在 import 时求值）。"""
    os.environ["ROUTER_DRY"] = "1" if dry else ""
    spec = importlib.util.spec_from_file_location(name, ROUTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_ir():
    if WS not in sys.path:
        sys.path.insert(0, WS)
    import kb.import_registry as ir  # noqa: E402
    return ir


def snapshot(db_path):
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        return dict(con.execute("SELECT id, content FROM atoms").fetchall())
    finally:
        con.close()


def verified_ids(n, db=None):
    # 2026-11-01 DEB-57：db 缺省仍打活 registry（R8/R10 既有探针不动）；R4/R5 幂等对
    # 改传快照（同一冻结视图，杜绝两次读活库被在役 admit 错位）。
    con = sqlite3.connect("file:%s?mode=ro" % (db or REGISTRY), uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT id FROM candidates WHERE status='verified' LIMIT ?", (n,))]
    finally:
        con.close()


def write_stub(path, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


# ---------- 各检查项 ----------

def case_constants(mod):
    # 2026-10-31 DEB-5：kb-ingest 自身预算按实测重标（原 ≤120s）。
    # 实测：真 registry 全量 verified（17986 条）冷启动导入 3 次 = 143.4/142.9/140.5s
    # （p95≈143.4s），120s 恒超时 → R4「成功路径返回非 dict」假红（生产侧同因）。
    # 基线 600s：> 空载 p95×2=286.8s，且 > 并行重载 p95×2=487.8s。
    # 2026-11-01 DEB-5a 内层帽（RT 实证）：verified 17986→23510（+30%/40h）后并发门跑
    # 重载下 600s 静态帽被恰点掐破（R4「成功路径返回 None」/R8「changelog 少一行」假红；
    # solo 同代码同数据 9/9 全绿）→ 与 all-gates.sh 外层帽同款线性外推。
    # 断言不放松：①基线常量精确等值 600（DEB-5 重标不被静默调参）；②当前值恰等于本测试
    # 用同一公式独立重算的外推值（规模输入取被测件取帽时的实测快照
    # KB_INGEST_TIMEOUT_SRC_VERIFIED——不用本测试现查的条数，避免与在产 admit 线竞态错位）
    # ——钉死机制本身，比原「==600」更强。
    check(mod.KB_INGEST_TIMEOUT_BASELINE == 600,
          "KB_INGEST_TIMEOUT_BASELINE=%r != 600（DEB-5 校准基线，2026-10-31 实测重标："
          "须 > p95×2=287s）" % mod.KB_INGEST_TIMEOUT_BASELINE)
    src_n = getattr(mod, "KB_INGEST_TIMEOUT_SRC_VERIFIED", None)
    check(isinstance(src_n, int) and not isinstance(src_n, bool) and src_n >= 0,
          "KB_INGEST_TIMEOUT_SRC_VERIFIED=%r（应为 ≥0 整数的实测 verified 规模）" % (src_n,))
    want = -(-600 * src_n // 17986)          # 与 event-router._kb_ingest_timeout 同式：ceil
    if want < 600:
        want = 600                            # 下限=校准基线：registry 缩小时不松帽
    want = (want + 59) // 60 * 60             # 向上取整到 1 分钟粒度
    check(mod.KB_INGEST_TIMEOUT == want,
          "KB_INGEST_TIMEOUT=%r != 按实测规模 %d 线性外推的 %r（DEB-5a 内层帽公式："
          "ceil(600×verified/17986)，下限 600、分钟粒度）"
          % (mod.KB_INGEST_TIMEOUT, src_n, want))
    check(mod.KB_INGEST_TIMEOUT >= 600, "KB_INGEST_TIMEOUT 低于基线 600")
    check(mod.KB_INGEST_TIMEOUT > 0, "KB_INGEST_TIMEOUT 非正")
    check(mod.KB_INGEST.endswith("tools/kb-ingest.py"), "KB_INGEST=%r" % mod.KB_INGEST)
    check(mod.KB_DB.endswith("kb/kb.db"), "KB_DB=%r" % mod.KB_DB)
    src = open(ROUTER, encoding="utf-8").read()
    check("--status verified" in src, "调用里没有 --status verified")
    return {"timeout": mod.KB_INGEST_TIMEOUT, "src_verified": src_n,
            "ingest": mod.KB_INGEST, "db": mod.KB_DB}


def case_dry(mod, d):
    """DRY：只记日志，不跑子进程、不建库、不写 changelog。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP")  # 确保不在位
    exploded = []

    def boom(*a, **kw):
        exploded.append(1)
        raise AssertionError("DRY 模式不应起子进程")
    real_run, mod.subprocess.run = mod.subprocess.run, boom
    try:
        r = mod.kb_ingest_verified("DRY 探针")
    finally:
        mod.subprocess.run = real_run
    check(r is None, "DRY 模式返回了 %r（应为 None）" % (r,))
    check(not exploded, "DRY 模式起了子进程")
    check(not os.path.exists(mod.KB_DB), "DRY 模式建了库：%s" % mod.KB_DB)
    check(not os.path.exists(mod.CHANGELOG), "DRY 模式写了 changelog")
    return {"subprocess_runs": 0, "db_created": False, "changelog_lines": 0}


def case_stop(mod, d):
    """STOP 熔断在位 → 跳过（循环中途落下熔断同样生效）。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    stop = os.path.join(d, ".router-STOP")
    open(stop, "w").write("")
    mod.STOP = stop
    exploded = []

    def boom(*a, **kw):
        exploded.append(1)
        raise AssertionError("STOP 在位不应起子进程")
    real_run, mod.subprocess.run = mod.subprocess.run, boom
    try:
        r = mod.kb_ingest_verified("STOP 探针")
    finally:
        mod.subprocess.run = real_run
    check(r is None, "STOP 在位返回了 %r（应为 None）" % (r,))
    check(not exploded, "STOP 在位起了子进程")
    check(not os.path.exists(mod.KB_DB), "STOP 在位建了库")
    check(not os.path.exists(mod.CHANGELOG), "STOP 在位写了 changelog")
    return {"subprocess_runs": 0, "db_created": False, "changelog_lines": 0}


def case_success_and_idempotent(mod, d, ir):
    """真跑 kb-ingest（临时库）：成功 + changelog 一行 + 口径统一；再跑一次幂等。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    # 2026-11-01 DEB-57（收尾）：本幂等对两次 kb_ingest_verified 全量导入直读活 registry
    # （event-router 的子进程命令不带 --registry → kb-ingest 默认打 kb-seed/registry.db），
    # 两跑之间无任何输入冻结——在役 admit 批量落进窗口即二跑 new>0「幂等破」假红，红的是
    # 门不是被测件（~/all-gates-logs/20261101-120003|133520|140117 三轮 item-11 实证：
    # 二跑 new=49/178/192 updated=0，窗口仅 11~19s；R10 修复注释自证单卡 admit 可含数十原子）。
    # 与同批已修款 tools/test-kb-content-parity.py real_case（DEB-5 主控终验根治）同款处理：
    # sqlite backup API 取一致快照，两次导入都打快照——KB_INGEST 重定向包装器只补
    # --registry（沿用 R6/R7 既有打桩位，production 命令串一字未动，finally 还原），
    # 探针 id 同样读快照（verified_ids(·, snap)）。断言一字不动，只封输入。
    snap = os.path.join(d, "registry-snapshot.db")
    _src = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
    _dst = sqlite3.connect(snap)
    with _dst:
        _src.backup(_dst)
    _dst.close()
    _src.close()
    check(os.path.isfile(snap), "registry 快照未生成：%s" % snap)
    mod.KB_INGEST = write_stub(
        os.path.join(d, "snapshot-redirect.py"),
        "import os, sys\n"
        "os.execv(sys.executable, [sys.executable, %r, '--registry', %r] + sys.argv[1:])\n"
        % (ROUTER_INGEST, snap))
    try:
        ids = verified_ids(12, snap)
        check(len(ids) == 12, "registry verified 不足 12 条")
        ctx = "探针卡 `kb-verify-probe` uphold 12/12 → registry admit 12 条"

        r1 = mod.kb_ingest_verified(ctx)
        check(isinstance(r1, dict), "成功路径返回非 dict：%r" % (r1,))
        # kb-ingest 导的是整个 verified 层（工单语义：verified 落定后入库），故 new=台账 verified 数
        want_new = r1.get("registry_status_counts", {}).get("verified")
        check(r1.get("new") == want_new,
              "首跑 new=%r（应等于台账 verified 数 %r）" % (r1.get("new"), want_new))
        check(r1.get("errors") in (None, []), "首跑有 errors：%r" % r1.get("errors"))
        lines = open(mod.CHANGELOG, encoding="utf-8").read().splitlines()
        check(len(lines) == 1, "changelog 行数=%d（应恰 1 行）" % len(lines))
        check("verified 原子自动入库 kb" in lines[0] and ("new=%d" % want_new) in lines[0],
              "changelog 内容不符：%r" % lines[0])
        check(os.path.isfile(mod.KB_DB), "临时库未建：%s" % mod.KB_DB)

        snap1 = snapshot(mod.KB_DB)
        check(set(snap1) >= set(ids), "库里缺探针原子：%s" % (set(ids) - set(snap1)))
        # 口径统一：content 与 kb/import_registry._build_content 逐字节一致
        originals = ir.load_originals(os.path.join(WS, "kb-seed"),
                                      os.path.join(WS, "计划", "研究组",
                                                   "三阶段POC-知识资产-20261027"))
        bad = [aid for aid in ids if snap1.get(aid) != originals[aid][1]]
        check(not bad, "%d 条 content 与 import_registry 口径不一致：%s" % (len(bad), bad[:3]))

        r2 = mod.kb_ingest_verified(ctx)
        check(isinstance(r2, dict), "二跑返回非 dict")
        check(r2.get("new") == 0 and r2.get("updated") == 0,
              "二跑 new=%r updated=%r（幂等破）" % (r2.get("new"), r2.get("updated")))
        check(r2.get("unchanged") == want_new,
              "二跑 unchanged=%r（应 %r）" % (r2.get("unchanged"), want_new))
        snap2 = snapshot(mod.KB_DB)
        check(snap1 == snap2, "二跑后 content 变了（%d 条）"
              % len([k for k in snap1 if snap1.get(k) != snap2.get(k)]))
        lines = open(mod.CHANGELOG, encoding="utf-8").read().splitlines()
        check(len(lines) == 2, "二跑后 changelog 行数=%d（应 2）" % len(lines))
    finally:
        mod.KB_INGEST = ROUTER_INGEST
    return {"first": {"new": r1.get("new"), "updated": r1.get("updated"),
                      "unchanged": r1.get("unchanged")},
            "second": {"new": r2.get("new"), "updated": r2.get("updated"),
                       "unchanged": r2.get("unchanged")},
            "content_matches_import_registry": True, "changelog_lines": len(lines)}


def case_failure(mod, d):
    """子进程非零退出且输出不可解析 → 只记日志，不写 changelog，不抛异常。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    stub = write_stub(os.path.join(d, "bad-ingest.py"),
                      "import sys\nprint('不是 JSON 的鬼话')\nsys.exit(4)\n")
    mod.KB_INGEST = stub
    try:
        r = mod.kb_ingest_verified("失败探针")
    except Exception as e:  # noqa: BLE001 - 本项就是断言"不抛"
        raise Fail("失败路径抛了异常：%s: %s" % (type(e).__name__, e))
    finally:
        mod.KB_INGEST = ROUTER_INGEST
    check(r is None, "失败路径返回了 %r（应为 None）" % (r,))
    check(not os.path.exists(mod.KB_DB), "失败路径建了库")
    check(not os.path.exists(mod.CHANGELOG), "失败路径写了 changelog")
    return {"raised": False, "changelog_lines": 0}


def case_timeout(mod, d):
    """超时分支：把 KB_INGEST_TIMEOUT 临时压到 1s，配睡眠桩（生产值=自适应帽，不改）。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    stub = write_stub(os.path.join(d, "slow-ingest.py"),
                      "import time\ntime.sleep(30)\n")
    mod.KB_INGEST = stub
    prod_timeout = mod.KB_INGEST_TIMEOUT
    real_timeout, mod.KB_INGEST_TIMEOUT = prod_timeout, 1
    t0 = time.time()
    try:
        r = mod.kb_ingest_verified("超时探针")
    except Exception as e:  # noqa: BLE001 - 本项就是断言"不抛"
        raise Fail("超时路径抛了异常：%s: %s" % (type(e).__name__, e))
    finally:
        mod.KB_INGEST_TIMEOUT = real_timeout
        mod.KB_INGEST = ROUTER_INGEST
    check(r is None, "超时路径返回了 %r（应为 None）" % (r,))
    check(time.time() - t0 < 10, "超时分支耗时 %rs（应很快返回）" % (time.time() - t0))
    check(not os.path.exists(mod.CHANGELOG), "超时路径写了 changelog")
    check(mod.KB_INGEST_TIMEOUT == prod_timeout,
          "生产超时值被改成 %r（应还原为取帽时的自适应值 %r）"
          % (mod.KB_INGEST_TIMEOUT, prod_timeout))
    return {"raised": False, "production_timeout": mod.KB_INGEST_TIMEOUT,
            "changelog_lines": 0}


def case_end_to_end(mod, d, ir):
    """端到端：一份 uphold 达标的验证回报走 handle_verify_report → admit + kb 入库。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    mod.VERIFY_DIR = os.path.join(d, "verify")
    os.makedirs(mod.VERIFY_DIR, exist_ok=True)
    ids = verified_ids(12)
    st = mod.load_state()
    st["verify_cards"]["kb-verify-probe-1"] = {
        "card_id": "kb-verify-probe-1", "task_id": "kb-atoms-acr-2404.05427-r2",
        "arxiv": "2404.05427", "candidates": "", "atom_ids": ids,
        "sampled": len(ids), "status": "open"}
    rep = {"task_id": "kb-verify-probe-1",
           "payload": {"card_id": "kb-verify-probe-1",
                       "verifications": [{"atom_id": aid, "verdict": "uphold",
                                          "quote_check": True, "reason": "探针"}
                                         for aid in ids]}}
    admitted = []
    real_admit, mod.registry_admit = mod.registry_admit, \
        lambda i, ev, cand: (admitted.extend(i) or len(i), 0)
    try:
        mod.handle_verify_report(st, "kb-verify-probe-1.json",
                                 os.path.join(mod.VERIFY_DIR, "kb-verify-probe-1.json"),
                                 rep)
    finally:
        mod.registry_admit = real_admit
    check(admitted == ids, "admit 的 id 与回报不符：%d 条" % len(admitted))
    check(st["verify_cards"]["kb-verify-probe-1"]["status"] == "passed", "卡状态未 passed")
    lines = open(mod.CHANGELOG, encoding="utf-8").read().splitlines()
    check(len(lines) == 2, "changelog 行数=%d（应 2：admit + kb 入库）" % len(lines))
    check("registry admit 12 条" in lines[0], "第一行不是 admit：%r" % lines[0])
    check("verified 原子自动入库 kb" in lines[1], "第二行不是 kb 入库：%r" % lines[1])
    snap = snapshot(mod.KB_DB)
    check(set(snap) >= set(ids), "库里缺端到端原子")
    originals = ir.load_originals(os.path.join(WS, "kb-seed"),
                                  os.path.join(WS, "计划", "研究组",
                                               "三阶段POC-知识资产-20261027"))
    bad = [aid for aid in ids if snap.get(aid) != originals[aid][1]]
    check(not bad, "%d 条 content 口径不一致" % len(bad))
    return {"admitted": len(admitted), "changelog_lines": len(lines),
            "kb_atoms": len(snap), "content_parity": True}


def case_admit_scope(mod, d):
    """R10 混合裁决 admit 口径（2026-10-31 RT 审计修复）：卡通过率达标时只 admit
    裁决 uphold 的原子。refute/unverifiable 是验证者明确判非，不得随整卡通过率搭车
    入库——修复前把全量 judged 整包送 registry_admit，实测 694 张 rate≥0.8 的混合
    裁决卡中被拒原子全部错误转 verified（铁证案例 sbx-kb-atoms-cls-2303.17760-r2-19：
    裁决原文明写「数字 25000 在证据文本中不存在」仍入库）。admit/kb 入库双打桩，零写库。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    mod.VERIFY_DIR = os.path.join(d, "verify")
    os.makedirs(mod.VERIFY_DIR, exist_ok=True)
    ids = verified_ids(12)
    check(len(ids) == 12, "registry verified 不足 12 条")
    st = mod.load_state()
    st["verify_cards"]["kb-verify-probe-mix"] = {
        "card_id": "kb-verify-probe-mix", "task_id": "kb-atoms-acr-2404.05427-r2",
        "arxiv": "2404.05427", "candidates": "", "atom_ids": ids,
        "sampled": len(ids), "status": "open"}
    # 10 uphold + 1 refute + 1 unverifiable：rate=10/12≈0.83≥0.8 卡过，
    # 但两个被拒原子不得入库（后者正是被修复的搭车路径）
    bad_refute, bad_unver = ids[10], ids[11]
    rep = {"task_id": "kb-verify-probe-mix",
           "payload": {"card_id": "kb-verify-probe-mix",
                       "verdicts": [{"atom_id": aid, "verdict": "uphold",
                                     "quote_check": True, "reason": "探针"}
                                    for aid in ids[:10]]
                                  + [{"atom_id": bad_refute, "verdict": "refute",
                                      "quote_check": True,
                                      "reason": "数字不在证据文本中（探针）"},
                                     {"atom_id": bad_unver, "verdict": "unverifiable",
                                      "quote_check": True,
                                      "reason": "证据不可得（探针）"}]}}
    admitted = []
    real_admit, mod.registry_admit = mod.registry_admit, \
        lambda i, ev, cand: (admitted.extend(i) or len(i), 0)
    real_ing, mod.kb_ingest_verified = mod.kb_ingest_verified, \
        lambda ctx: {"new": 0}
    try:
        mod.handle_verify_report(st, "kb-verify-probe-mix.json",
                                 os.path.join(mod.VERIFY_DIR,
                                              "kb-verify-probe-mix.json"),
                                 rep)
    finally:
        mod.registry_admit = real_admit
        mod.kb_ingest_verified = real_ing
    check(admitted == ids[:10],
          "admit 应恰为 10 条 uphold 原子（实测 %d 条，混入被拒原子 %r）"
          % (len(admitted), [a for a in admitted
                             if a in (bad_refute, bad_unver)]))
    check(st["verify_cards"]["kb-verify-probe-mix"]["status"] == "passed",
          "卡状态未 passed")
    lines = open(mod.CHANGELOG, encoding="utf-8").read().splitlines()
    check(len(lines) == 1, "changelog 行数=%d（应 1：仅 admit 行，kb 入库已打桩）"
          % len(lines))
    check("registry admit 10 条" in lines[0] and "refute/unverifiable 2 条不入库" in lines[0],
          "changelog 未如实记录 admit 口径：%r" % lines[0])
    return {"admitted_uphold_only": len(admitted),
            "excluded_refute_unverifiable": 2,
            "card_status": st["verify_cards"]["kb-verify-probe-mix"]["status"]}


def case_admit_quote_check(mod, d):
    """R11 quote_check 机械真值对账（2026-11-01 RT 修复）：verdict=uphold 而
    quote_check=false 的原子不得入库。quote_check 是卡内逐原子机器回查（引文是否在
    证据文本中逐字出现）的真值——修复前聚合只信验证者 verdict 字段，该组合全扫
    sandbox/verify 8,414+ 份回报 1,784 处、其中 578 条独立回查确证坏引文已入库；
    E32（refute 不搭车）落地后通道仍开（10-31/11-01 两日又 admit 305 条）。此类原子
    保留 candidate（他卡可 uphold∧quote_check=true 独立复核翻案），卡级通过率仍按
    验证者裁决口径计；changelog 如实记录排除条数。admit/kb 入库双打桩，零写库。"""
    mod.CHANGELOG = os.path.join(d, "changelog.md")
    mod.KB_DB = os.path.join(d, "kb.db")
    mod.STOP = os.path.join(d, ".router-STOP-not-there")
    mod.VERIFY_DIR = os.path.join(d, "verify")
    os.makedirs(mod.VERIFY_DIR, exist_ok=True)
    ids = verified_ids(12)
    check(len(ids) == 12, "registry verified 不足 12 条")
    st = mod.load_state()
    st["verify_cards"]["kb-verify-probe-qc"] = {
        "card_id": "kb-verify-probe-qc", "task_id": "kb-atoms-acr-2404.05427-r2",
        "arxiv": "2404.05427", "candidates": "", "atom_ids": ids,
        "sampled": len(ids), "status": "open"}
    # 12/12 全 uphold：rate=1.00≥0.8 卡过；但 4 条 quote_check=false 的机器真值未证实
    # 引文，不得入库（正是被修复的「聚合对 qc 机械真值失明」通道）
    qc_false = ids[8:]
    rep = {"task_id": "kb-verify-probe-qc",
           "payload": {"card_id": "kb-verify-probe-qc",
                       "verdicts": [{"atom_id": aid, "verdict": "uphold",
                                     "quote_check": (aid not in qc_false),
                                     "reason": "探针"}
                                    for aid in ids]}}
    admitted = []
    real_admit, mod.registry_admit = mod.registry_admit, \
        lambda i, ev, cand: (admitted.extend(i) or len(i), 0)
    real_ing, mod.kb_ingest_verified = mod.kb_ingest_verified, \
        lambda ctx: {"new": 0}
    try:
        mod.handle_verify_report(st, "kb-verify-probe-qc.json",
                                 os.path.join(mod.VERIFY_DIR,
                                              "kb-verify-probe-qc.json"),
                                 rep)
    finally:
        mod.registry_admit = real_admit
        mod.kb_ingest_verified = real_ing
    check(admitted == ids[:8],
          "admit 应恰为 8 条 uphold∧qc=true 原子（实测 %d 条；混入 qc=false 原子 %r）"
          % (len(admitted), [a for a in admitted if a in qc_false]))
    check(st["verify_cards"]["kb-verify-probe-qc"]["status"] == "passed",
          "卡状态未 passed（qc=false 只影响逐原子 admit，不改卡级通过率口径）")
    lines = open(mod.CHANGELOG, encoding="utf-8").read().splitlines()
    check(len(lines) == 1, "changelog 行数=%d（应 1：仅 admit 行，kb 入库已打桩）"
          % len(lines))
    check("registry admit 8 条" in lines[0]
          and "uphold∧quote_check 非真 4 条不入库" in lines[0],
          "changelog 未如实记录 qc 机械真值排除口径：%r" % lines[0])
    return {"admitted_uphold_qc_true": len(admitted),
            "excluded_uphold_qc_false": len(qc_false),
            "card_status": st["verify_cards"]["kb-verify-probe-qc"]["status"]}


def case_no_regression(mod, d):
    """既有行为不回退：主循环 STOP 熔断、DRY 门、状态文件防重放键仍在。"""
    src = open(ROUTER, encoding="utf-8").read()
    check("if os.path.exists(STOP):" in src and "STOP 熔断在位" in src,
          "主循环 STOP 熔断检查不见了")
    check(src.count("if DRY:") >= 4, "DRY 门数量=%d（应 ≥4：save_state/changelog/"
          "poll_harvest/make_portal_seed/registry_admit/registry_reject/kb_ingest）"
          % src.count("if DRY:"))
    for fn in ("save_state", "poll_harvest", "make_portal_seed", "registry_admit",
               "registry_reject", "handle_verify_report", "poll_verify_reports",
               "make_rework_card", "enqueue_rr55", "make_verify_card", "poll_orders"):
        check(("def %s(" % fn) in src, "既有函数 %s 不见了" % fn)
    check('"verify_reports"' in src and '"verify_scanned"' in src,
          "状态文件防重放键不见了")
    check('"r3"' in src and '"rr55"' in src, "r3/rr55 键不见了")
    return {"stop_gate": True, "dry_gates": src.count("if DRY:"),
            "functions_intact": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="event-router → kb 入库接线回归（冲刺批2 第二步）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录（排查用）")
    a = ap.parse_args(argv)

    check(os.path.isfile(ROUTER), "event-router.py 不存在：%s" % ROUTER)
    check(os.path.isfile(REGISTRY), "registry 不存在：%s" % REGISTRY)
    ir = load_ir()
    dry_mod = load_router("router_dry_under_test", dry=True)
    live_mod = load_router("router_live_under_test", dry=False)
    check(dry_mod.DRY is True, "DRY 模块 DRY=False")
    check(live_mod.DRY is False, "非 DRY 模块 DRY=True")

    purge_stale_scratch(_SCRATCH_BASE)
    os.makedirs(SCRATCH, exist_ok=True)
    results, failures = {}, []
    try:
        cases = [
            ("R1 常量口径（超时基线==600s+DEB-5a 规模自适应 / kb-ingest --status verified / kb.db）",
             lambda d: case_constants(live_mod)),
            ("R2 ROUTER_DRY 干跑只记日志不落库", lambda d: case_dry(dry_mod, d)),
            ("R3 .router-STOP 熔断在位即跳过", lambda d: case_stop(live_mod, d)),
            ("R4/R5 成功 + 幂等 + content 口径统一 + changelog 一行",
             lambda d: case_success_and_idempotent(live_mod, d, ir)),
            ("R6 失败路径只记日志不阻塞", lambda d: case_failure(live_mod, d)),
            ("R7 超时路径被吞掉不阻塞", lambda d: case_timeout(live_mod, d)),
            ("R8 端到端接线（验证回报 → admit → kb 入库）",
             lambda d: case_end_to_end(live_mod, d, ir)),
            ("R10 混合裁决 admit 口径（refute/unverifiable 不随卡搭车入库）",
             lambda d: case_admit_scope(live_mod, d)),
            ("R11 quote_check 机械真值对账（uphold∧qc=false 不入库，保留 candidate）",
             lambda d: case_admit_quote_check(live_mod, d)),
            ("R9 既有路由行为不回退（STOP/DRY/防重放/函数集）",
             lambda d: case_no_regression(live_mod, d)),
        ]
        for i, (name, fn) in enumerate(cases):
            d = os.path.join(SCRATCH, "case-%d" % i)
            # 先清后建：上次被硬杀（超时/Ctrl-C）时 finally 的 rmtree 没跑到，残留
            # case 目录里已带 kb.db/changelog——首跑 new=0 unchanged=5708、changelog
            # 行数虚增，全是残留态不是被测件缺陷（2026-10-29 统一门禁取证：探针跑
            # 179s 超时被杀即复现下一跑 R4/R5+R8 假红；断言一字未动）。
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
            try:
                results[name] = fn(d)
                print("  [PASS] %s -> %s" % (name, json.dumps(results[name],
                                                              ensure_ascii=False)))
            except Fail as e:
                failures.append(name)
                print("  [FAIL] %s -> %s" % (name, e))
            except Exception as e:  # noqa: BLE001
                failures.append(name)
                print("  [FAIL] %s -> %s: %s" % (name, type(e).__name__, e))
    finally:
        if not a.keep:
            shutil.rmtree(SCRATCH, ignore_errors=True)

    if failures:
        print("ROUTER-KB FAILED: %d 项未过 -> %s" % (len(failures), failures))
        return EXIT_FAIL
    print("ROUTER-KB PASSED: %d 项" % len(results))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
