#!/usr/bin/env python3
"""test-vamp-verify-replicas.py — 战役优化批①验证放大回归（k 张独立复核卡 + 分歧检测）

工单判据（2026-10-29，运营者令「一张抽取的产出应被多个沙箱独立复核」）：
  ① cross-verify.py 增 --replicas（默认 2）：同一 atom 集生成 k 张卡，各用不同抽样
     种子与不同复核员视角提示语（r1 逐字核验 / r2 语义核对）；id 方案
     kb-verify-<base>-<attempt>r<j>，不与回流 attempt 计数冲突；同步更新所有消费方
     正则（event-router VERIFY_REJECT_RE / 回流重发键 / harvester 展示）；回流语义
     不变（attempt+1，k 张各自独立计重发上限）。
  ② event-router 聚合处记录同一 atom 集的跨卡一致率（同 uphold/refute 原子比例），
     一致率 <1 时 changelog 登记一行「分歧检测」列双方卡号与分歧原子；日志持续输出一致率
     指标。2026-11-02 RT-E32 修复后：跨卡分歧不再纯观测——消费腿接管裁决时序（更晚的
     非 uphold 裁决 → 该原子不 admit／已 verified 者双库降级），分歧行声明接管。
  ③ 回归：既有单卡路径、回流路径、kb-ingest 入库、r2 回流行为不变（对照验证）；
     新卡全过 card-lint。

检查项：
  V1 单卡路径对照：--replicas 1 与改动前（.20261029-pre-vamp.bak）逐字节一致
     （problem.md / AGENTS.md / meta.json / stdout 末行 JSON），且种子口径同旧公式
  V2 默认 k=2：两张卡 id 带 r1/r2，种子不同、抽样不同、视角提示语差异化，meta 记
     replica 元数据；两卡全过 card-lint（L1-L8）
  V3 回流单副本（--replica J）：同 seed → 同一批原子，attempt+1，视角保留，
     另一副本血线不被挤占；跑 hermetic fixture registry（真 registry 已全部
     verified，守卫会整集跳过），并显式断言守卫 skip 分支输出形
     （ok+skipped_verify，不落卡、无 cards 键）
  V4 id 方案与消费方正则：parse_verify_card_id 老/新格式；VERIFY_REJECT_RE 命中
     真实 HARVEST-LOG 老格式拒收行（≥60 行，实测 79）+ 合成新格式行（attempt/replica
     拆对）；抽取线 r2 正则仍不误命中验证卡行
  V5 派单面：router make_verify_card 一次派 k 张卡入状态与 changelog（stub 掉
     scp/registry，零写生产、零推 gov）
  V6 聚合与分歧：两卡回报有 1 条共有原子裁决相反 → 一致率<1 打日志 + 「分歧检测」
     changelog 行（列双方卡号与分歧原子）；admit 不被阻塞；全同判时不出分歧行
  V7 回流面：poll_verify_rejects → 同副本 attempt+1 重发（同批原子）；k 张各自独立
     计重发上限（r2 满后 r1 仍可重发；满后再拒不生成）；守卫 skip 分支在 router
     侧记账 status=skipped（不 KeyError 'card_ids'）
  V8 老格式回流对照：legacy 卡 -1 → -2（id 无 r 后缀、meta 无 replica 字段），
     在飞跳过逻辑按血线生效
  V9 不回退：router STOP 熔断 / DRY 门 / 既有函数与状态键；cross-verify STOP 熔断；
     harvester 展示带回完整卡号（含副本号）

用法：python3 tools/test-vamp-verify-replicas.py [--keep]
退出码：0 全过；1 断言失败；2 前置不满足。
临时目录建在 $HOME 下自建目录（/tmp 配额有限），默认完工即删。零网络、零密钥、
零写生产（registry/kb/gov 全部打桩或指到 scratch；cross-verify 一律 --no-scp）。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
HOME = os.path.expanduser("~")
TOOLS = os.path.join(WS, "tools")
CROSS = os.path.join(TOOLS, "cross-verify.py")
CROSS_BAK = os.path.join(TOOLS, "cross-verify.py.20261029-pre-vamp.bak")
ROUTER = os.path.join(TOOLS, "event-router.py")
HARVESTER = os.path.join(TOOLS, "sandbox-harvester.py")
CARDLINT = os.path.join(TOOLS, "card-lint.py")
CAND = os.path.join(WS, "kb-seed/sandbox/kb-atoms-w4-2610.36623-20261028-142910.jsonl")
ARX = "2610.36623"
# 非密闭修复（2026-11-01 RT）：原为固定共享路径，并行跑本件的一方 rmtree 会拆掉
# 另一方在测的夹具（假红实证：2026-10-31 RT 轮 V1「单卡路径对照」红，姊妹跑同位全绿）。
# 加 pid 后缀：每次运行独占夹具根；仍落 $HOME（/tmp 配额有限，硬纪律 5），跑完即清。
SCRATCH = os.path.join(HOME, "vamp-replicas-scratch.%d" % os.getpid())
HARVEST_LOG = os.path.join(WS, "kb-seed/sandbox/HARVEST-LOG.md")

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_cross(args, seeds, quiet=False, cand=CAND):
    """跑 cross-verify（一律 --dry-run --no-fetch，零网络零推送）。

    不用 --quiet：stdout 末行必须是结构化 JSON（日志行在前），与 router 的
    `... 2>&1 | tail -1` 消费口径一致。
    """
    cmd = [sys.executable, CROSS, cand, ARX, "--seeds-dir", seeds,
           "--dry-run", "--no-fetch"] + (["--quiet"] if quiet else []) + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r


def last_json(r):
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def hermetic_fixture(d, status="candidate", keep_candidate=None):
    """隔离夹具：CAND 的字节副本 + 一张全 candidate 的 scratch registry。

    cross-verify 2026-10-29 生成前守卫按 `<jsonl 所在目录>/../registry.db` 过滤
    已 admit 原子（防空转）；真 registry 里这 40 条已 36 verified，池子被收窄到 4
    条，单卡字节对照/两副本抽样差异化/每卡 12 条等断言全部失真（V1/V2/V5/V6 假红）。
    本件 docstring 承诺「registry/kb/gov 全部打桩或指到 scratch」——守卫按路径
    推断读的是真库，这里把 Hermetic 补上：副本同 basename（task_id 口径不变），
    registry 落在 `<d>/registry.db`（即副本的 ../registry.db，守卫推断路径）。

    2026-10-29 收口批：真 registry 里这 40 条现已全部 verified（实测见报告），守卫
    会整集跳过、返回 `{"ok":true,"skipped_verify":true}`（无 cards 键）——V3/V7 直跑
    退化成 KeyError 'cards'/'card_ids'。故本函数补两样：
      · 幂等：DROP+CREATE，同一 d 可重复调用（V3 主路径与 skip 探针共用一份夹具）；
      · status / keep_candidate：可造「全 verified」或「仅留前 N 条 candidate」的
        夹具，让守卫 skip 分支（判据 len(rows) < max(2, n//3)，cross-verify.py:436）
        被显式断言，而不是让下游抛 KeyError。
    """
    import sqlite3
    iso = os.path.join(d, "iso")
    os.makedirs(iso, exist_ok=True)
    cand = os.path.join(iso, os.path.basename(CAND))
    shutil.copyfile(CAND, cand)
    reg = os.path.join(d, "registry.db")
    con = sqlite3.connect(reg)
    con.execute("DROP TABLE IF EXISTS candidates")
    con.execute("CREATE TABLE candidates (id TEXT PRIMARY KEY, source_corpus TEXT, "
                "status TEXT CHECK (status IN ('candidate','verified','rejected')), "
                "created_at TEXT, note TEXT)")
    ids = []
    with open(CAND, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln:
                ids.append(json.loads(ln)["candidate_id"])
    con.executemany("INSERT INTO candidates VALUES (?,?,?,?,?)",
                    [(cid, "sandbox",
                      "candidate" if (keep_candidate is not None and i < keep_candidate) else status,
                      "2026-10-29 00:00:00", "hermetic-fixture")
                     for i, cid in enumerate(ids)])
    con.commit()
    con.close()
    return cand


# ---------- V1 单卡路径对照（改动前 .bak 逐字节） ----------

def case_single_card_control(d):
    if not os.path.isfile(CROSS_BAK):
        return {"control_bak": "absent（跳过字节对照，仅做口径断言）"}
    old_dir, new_dir = os.path.join(d, "old"), os.path.join(d, "new")
    for sub in (old_dir, new_dir):
        os.makedirs(sub, exist_ok=True)
    # 不带 --seed：让旧派生公式 sha256(arx|task_id|attempt)[:12] 也被字节对照覆盖
    args = ["--n", "3"]
    # 隔离夹具（全 candidate scratch registry）：.bak 无守卫、两边池子同为 40 条，
    # 字节对照才测得「改动本身」而不是真 registry 的 admit 进度
    cand = hermetic_fixture(d)
    # 两边都不带 --quiet：stdout 末行才是结构化 JSON（--quiet 会连 JSON 一起吞掉）
    r_old = subprocess.run([sys.executable, CROSS_BAK, cand, ARX, "--seeds-dir", old_dir,
                            "--dry-run", "--no-fetch"] + args,
                           capture_output=True, text=True, timeout=300)
    r_new = run_cross(args + ["--replicas", "1"], new_dir, cand=cand)
    check(r_old.returncode == 0 and r_new.returncode == 0,
          "生成失败 old=%d new=%d" % (r_old.returncode, r_new.returncode))
    # stdout 末行 JSON 也逐字节同形（card_dir 同路径才可比，故两边用各自目录后替换路径）
    j_old = json.loads([l for l in r_old.stdout.splitlines() if l.strip()][-1])
    j_new = last_json(r_new)
    check(set(j_old) == set(j_new), "stdout 键集不同：%r vs %r" % (sorted(j_old), sorted(j_new)))
    for k in ("ok", "card_id", "task_id", "arxiv", "atoms_total", "sampled", "seed",
              "atom_ids", "gate", "scp", "note"):
        check(j_old.get(k) == j_new.get(k), "stdout 字段 %s 不同：%r vs %r" % (k, j_old.get(k), j_new.get(k)))
    card = j_new["card_id"]
    check(not re.search(r"r\d+$", card), "单卡路径 id 不应带 r 后缀：%r" % card)
    for f in ("problem.md", "AGENTS.md", "meta.json"):
        a = open(os.path.join(old_dir, card, f), "rb").read()
        b = open(os.path.join(new_dir, card, f), "rb").read()
        check(a == b, "单卡路径 %s 与改动前不一致（%d vs %d 字节）" % (f, len(a), len(b)))
    # 口径断言：种子 = sha256(arx|task_id|attempt)[:12]（旧公式，未显式传 --seed 时）
    import hashlib
    want = hashlib.sha256(f"{ARX}|kb-atoms-w4-{ARX}|1".encode()).hexdigest()[:12]
    check(j_new["seed"] == want, "单卡种子口径变了：%r（应 %r）" % (j_new["seed"], want))
    check("本卡视角" not in open(os.path.join(new_dir, card, "problem.md"), encoding="utf-8").read(),
          "单卡路径不应注入视角段")
    meta = json.load(open(os.path.join(new_dir, card, "meta.json"), encoding="utf-8"))["verify"]
    check("replica" not in meta, "单卡路径 meta 不应带 replica 元数据")
    return {"byte_identical": ["problem.md", "AGENTS.md", "meta.json", "stdout-json"],
            "card": card, "seed": j_new["seed"]}


# ---------- V2 默认 k=2 ----------

def case_default_two_replicas(d):
    seeds = os.path.join(d, "k2")
    os.makedirs(seeds, exist_ok=True)
    cand = hermetic_fixture(d)  # 40 条全 candidate：两副本各抽 6 条才抽得出差异
    r = run_cross(["--n", "6"], seeds, cand=cand)
    check(r.returncode == 0, "默认 k=2 生成失败 exit=%d：%s%s"
          % (r.returncode, r.stdout[-200:], r.stderr[-200:]))
    j = last_json(r)
    check(j.get("replicas") == 2 and len(j.get("cards") or []) == 2,
          "默认应为 2 张副本卡：%r" % {k: j.get(k) for k in ("ok", "replicas")})
    c1, c2 = j["cards"]
    base = f"kb-verify-kb-atoms-w4-{ARX}-1"
    check(c1["card_id"] == base + "r1" and c2["card_id"] == base + "r2",
          "id 方案应为 <base>-<attempt>r<j>：%r %r" % (c1["card_id"], c2["card_id"]))
    check(c1["seed"] != c2["seed"], "两副本种子应不同（独立性）")
    check(c1["perspective"] != c2["perspective"], "两副本视角应差异化")
    check(set(c1["atom_ids"]) != set(c2["atom_ids"]), "两副本抽样应不同")
    lint = subprocess.run([sys.executable, CARDLINT,
                           os.path.join(seeds, c1["card_id"]), os.path.join(seeds, c2["card_id"])],
                          capture_output=True, text=True, timeout=120)
    check(lint.returncode == 0 and "硬伤 0" in lint.stdout,
          "新卡未过 card-lint（exit=%d）：%s" % (lint.returncode, lint.stdout + lint.stderr))
    p1 = open(os.path.join(seeds, c1["card_id"], "problem.md"), encoding="utf-8").read()
    p2 = open(os.path.join(seeds, c2["card_id"], "problem.md"), encoding="utf-8").read()
    check("逐字核验" in p1 and "语义核对" in p2, "视角段未按副本分化")
    ids = set(re.findall(r"\b(\d{4}\.\d{4,5})\b", p1 + p2))
    check(ids == {ARX}, "card-lint L3 口径：证据源 arXiv id 应唯一：%r" % ids)
    return {"cards": [c1["card_id"], c2["card_id"]], "seeds": [c1["seed"], c2["seed"]],
            "perspectives": [c1["perspective"], c2["perspective"]], "lint": "硬伤 0"}


# ---------- V3 回流单副本 ----------

def case_guard_skip_shape(d, n=6, keep_candidate=0):
    """守卫 skip 分支的显式断言（V3/V7 夹具化的另一半，2026-10-29 收口批）。

    夹具 registry 全 verified（keep_candidate=0）时 cross-verify 必须返回
    `{"ok": true, "skipped_verify": true, "note": "守卫跳过：…"}`：exit 0、不落任何卡
    目录、不带 cards 键。旧口径直接 `j["cards"]`，守卫一跳过就 KeyError 'cards' 崩掉
    回流面（V3 直跑红的形态）。本条把形状钉死：skip 时断言 skipped_verify=true，
    而不是 KeyError。keep_candidate=1 时仍应 skip（1 < max(2, n//3)）——反例探针
    用它证明阈值边界内该分支照样绿。
    """
    seeds = os.path.join(d, "skip-seeds")
    os.makedirs(seeds, exist_ok=True)
    cand = hermetic_fixture(d, status="verified", keep_candidate=keep_candidate)
    r = run_cross(["--n", str(n)], seeds, cand=cand)
    check(r.returncode == 0, "守卫 skip 应 exit 0，实得 %d：%s%s"
          % (r.returncode, r.stdout[-200:], r.stderr[-200:]))
    j = last_json(r)
    check(j is not None and j.get("ok") is True and j.get("skipped_verify") is True,
          "守卫 skip 形状异常（应 ok=true 且 skipped_verify=true）：%r" % j)
    check("守卫跳过" in (j.get("note") or ""),
          "skip note 未说明守卫原因：%r" % (j or {}).get("note"))
    check(not j.get("cards") and not j.get("card_id"),
          "skip 形状不得带 cards/card_id（否则下游误当已派单）：%r" % j)
    check(not os.listdir(seeds), "skip 分支不得落任何卡目录：%r" % os.listdir(seeds))
    return {"skipped_verify": True, "note": j["note"], "seeds_dir_empty": True,
            "keep_candidate": keep_candidate}


def case_dispatch_guard_skip(d):
    """守卫 skip 分支在 router 派单面的显式断言（V7 夹具化的另一半）。

    夹具 registry 全 verified → cross-verify 返回 `{"ok":true,"skipped_verify":true}`
    （既无 cards 也无 card_id）。router 必须按 skipped 记账放行
    （event-router.py:732-735），`verify_by_file[cand]` 只留 `{"status":"skipped"}`。
    旧口径是 `st["verify_by_file"][cand]["card_ids"]`，守卫一跳过就 KeyError
    'card_ids' 崩掉回流面（V7 直跑红的形态）。本条把形状钉死：skip 时断言
    status=skipped + 变更日志记因，而不是 KeyError。
    """
    er, rec = make_router(d)
    st = er.load_state()
    cand = hermetic_fixture(d, status="verified")
    er.CAND_DIR = os.path.dirname(cand)  # 回流按 candidates_file basename 在本目录解析
    er.make_verify_card(st, cand)        # 不得抛（一张无卡可派的候选不许带崩回流线）
    entry = st["verify_by_file"].get(cand) or {}
    check(entry.get("status") == "skipped",
          "守卫 skip 应按 skipped 记账：%r" % entry)
    check("card_ids" not in entry and "card_id" not in entry,
          "skip 记账不得带 card_ids/card_id（否则下游误当已派单）：%r" % entry)
    log = open(er.CHANGELOG, encoding="utf-8").read()
    check("交叉验证跳过（无卡可派" in log and "守卫跳过" in log,
          "skip 未记变更日志：%r" % log[-200:])
    check(not rec["scped"], "skip 分支不得推送：%r" % rec["scped"])
    return {"router_status": "skipped", "no_keyerror": True}


def case_replica_resend(d):
    seeds = os.path.join(d, "k2b")
    os.makedirs(seeds, exist_ok=True)
    # 夹具化（2026-10-29 收口）：真 registry 里这 40 条已全部 verified，生成前守卫会
    # 整集跳过、stdout 末行 JSON 无 cards 键 → 旧断言 j["cards"] 直接 KeyError。
    # 主路径跑全 candidate 夹具；skip 分支由 case_guard_skip_shape 显式断言。
    cand = hermetic_fixture(d)
    r = run_cross(["--n", "6"], seeds, cand=cand)
    j = last_json(r)
    check(r.returncode == 0 and j is not None and j.get("ok") is True
          and j.get("skipped_verify") is not True,
          "夹具 registry 全 candidate 时不应走守卫跳过：rc=%d %r" % (r.returncode, j))
    check(isinstance(j.get("cards"), list) and len(j["cards"]) == 2,
          "默认 k=2 应出 2 张副本卡：%r" % {k: j.get(k) for k in ("ok", "replicas")})
    c1, c2 = j["cards"]
    r2 = run_cross(["--n", "6", "--seed", c1["seed"], "--replica", "1"], seeds, cand=cand)
    check(r2.returncode == 0, "--replica 1 重发失败：%s%s" % (r2.stdout[-200:], r2.stderr[-200:]))
    j2 = last_json(r2)
    check(j2 is not None and j2.get("ok") is True and j2.get("skipped_verify") is not True,
          "--replica 1 重发不应走守卫跳过：%r" % j2)
    check(isinstance(j2.get("cards"), list) and len(j2["cards"]) == 1,
          "--replica 1 应只发 1 张同副本卡：%r" % {k: j2.get(k) for k in ("ok", "replicas")})
    c = j2["cards"][0]
    check(c["card_id"] == f"kb-verify-kb-atoms-w4-{ARX}-2r1",
          "回流 id 应为 attempt+1 同副本：%r" % c["card_id"])
    check(c["seed"] == c1["seed"], "回流未沿用原副本种子")
    check(c["atom_ids"] == c1["atom_ids"], "回流未保持同一批原子（atom 集应不变）")
    check(c["perspective"] == c1["perspective"], "回流未保留原副本视角")
    m = json.load(open(os.path.join(seeds, c["card_id"], "meta.json"), encoding="utf-8"))["verify"]
    check(m.get("replica") == 1 and m.get("attempt") == 2, "回流 meta 轮次/副本不对：%r" % m)
    dirs = sorted(os.listdir(seeds))
    check(dirs == [f"kb-verify-kb-atoms-w4-{ARX}-1r1", f"kb-verify-kb-atoms-w4-{ARX}-1r2",
                   f"kb-verify-kb-atoms-w4-{ARX}-2r1"],
          "r1 回流不得挤占 r2 血线序号：%r" % dirs)
    # 守卫 skip 分支显式断言（同一用例内，故 V3 的 PASS 覆盖该分支）
    skip = case_guard_skip_shape(d, n=6)
    return {"resend_card": c["card_id"], "same_atoms": True, "attempt": m.get("attempt"),
            "guard_skip": skip}


# ---------- V4 id 方案与消费方正则 ----------

def case_id_scheme():
    er = load_mod("router_v4", ROUTER)
    expect = {
        "kb-verify-kb-atoms-acr-2404.05427-r2-1r1": ("kb-atoms-acr-2404.05427-r2", 1, 1),
        "kb-verify-kb-atoms-acr-2404.05427-r2-1": ("kb-atoms-acr-2404.05427-r2", 1, None),
        "kb-verify-kb-atoms-w4-2610.37631-1r2": ("kb-atoms-w4-2610.37631", 1, 2),
        "kb-verify-x-12r3": ("x", 12, 3),
        "kb-verify-x-2": ("x", 2, None),
    }
    for cid, want in expect.items():
        got = er.parse_verify_card_id(cid)
        check(got == want, "parse_verify_card_id(%r)=%r（应 %r）" % (cid, got, want))
    check(er.parse_verify_card_id("garbage") is None, "非法 id 应返回 None")
    # 真实 HARVEST-LOG 的拒收行分两种形态各查各的：
    #   老格式（id 无 r 后缀）：attempt/replica 必须拆成 (attempt, None)；
    #   新格式（-<attempt>r<replica>，2026-10-29 验证放大上线后活日志已混入）：
    #   replica 必须拆得出。混在一循环里要求「全部 replica=None」会把上线后的
    #   新格式行判成假红（统一门禁取证：真日志 79 老格式 + 129 新格式）。
    NEW_FMT_CARD_RE = re.compile(r"kb-verify-[a-z0-9.\-]+-\d+r\d+(?:-\d{6,})?\.json")
    if os.path.isfile(HARVEST_LOG):
        allrej = [l for l in open(HARVEST_LOG, encoding="utf-8").read().splitlines()
                  if "kb-verify" in l and "| rejected |" in l]
        lines = [l for l in allrej if not NEW_FMT_CARD_RE.search(l)]
        check(len(lines) >= 60, "HARVEST-LOG 老格式 kb-verify 拒收行应 ≥60 行（实测 %d）" % len(lines))
        for l in lines:
            m = er.VERIFY_REJECT_RE.search(l)
            check(m is not None, "老格式拒收行未命中 VERIFY_REJECT_RE：%r" % l[:100])
            p = er.parse_verify_card_id(m.group("card"))
            check(p is not None and p[2] is None and p[1] >= 1,
                  "老格式行 attempt/replica 拆解异常：%r" % m.group("card"))
        n_real = len(lines)
        n_new = 0
        for l in allrej:
            if not NEW_FMT_CARD_RE.search(l):
                continue
            n_new += 1
            m = er.VERIFY_REJECT_RE.search(l)
            check(m is not None, "新格式拒收行未命中 VERIFY_REJECT_RE：%r" % l[:100])
            p = er.parse_verify_card_id(m.group("card"))
            check(p is not None and p[2] is not None and p[1] >= 1,
                  "新格式行 attempt/replica 拆解异常：%r" % m.group("card"))
    else:
        n_real = n_new = 0
    # 合成新格式行（含/不含时间戳）：attempt 与 replica 都要拆对
    synth = [
        ("| kb-verify-kb-atoms-acr-2404.05427-r2-1r1-1793164999542.json | rejected | why | - |",
         ("kb-verify-kb-atoms-acr-2404.05427-r2-1r1", "kb-atoms-acr-2404.05427-r2", "1", "1")),
        ("| kb-verify-kb-atoms-w4-2610.37631-2r2.json | rejected | why | - |",
         ("kb-verify-kb-atoms-w4-2610.37631-2r2", "kb-atoms-w4-2610.37631", "2", "2")),
        ("| kb-verify-x-1r1.json | rejected | why | - |",
         ("kb-verify-x-1r1", "x", "1", "1")),
    ]
    for line, want in synth:
        m = er.VERIFY_REJECT_RE.search(line)
        check(m is not None, "新格式拒收行未命中：%r" % line)
        got = (m.group("card"), m.group("base"), m.group("attempt"), m.group("replica"))
        check(got == want, "新格式行拆解 %r（应 %r）" % (got, want))
    # 抽取线 r2 正则互斥不变（验证卡行不得被当成 kb-atoms 拒收）
    r2_re = re.compile(r"\|\s*(kb-atoms-[a-z0-9]+-(\d{4}\.\d{4,5}))(?:-r2)?-\d+\.json"
                       r"\s*\|\s*rejected\s*\|([^|]*)\|")
    check(not any(r2_re.search(l) for l, _ in synth), "新格式验证卡行误命中了抽取线 r2 正则")
    return {"real_reject_lines": n_real, "real_new_format_lines": n_new,
            "synthetic_new_format": len(synth)}


# ---------- V5 派单面（router make_verify_card，stub 掉 scp/registry） ----------

def make_router(d, dry=False):
    er = load_mod("router_under_test", ROUTER)
    er.CHANGELOG = os.path.join(d, "changelog.md")
    er.STATE_F = os.path.join(d, ".router-state.json")
    er.STOP = os.path.join(d, ".router-STOP-not-there")
    er.VERIFY_SEEDS = os.path.join(d, "task-seeds")
    er.VERIFY_DIR = os.path.join(d, "verify")
    er.CAND_DIR = os.path.join(WS, "kb-seed/sandbox")
    os.makedirs(er.VERIFY_SEEDS, exist_ok=True)
    os.makedirs(er.VERIFY_DIR, exist_ok=True)
    os.environ["ROUTER_DRY"] = "1" if dry else ""
    er.DRY = dry
    admitted, rejected, ingested, scped = [], [], [], []
    er.registry_admit = lambda i, ev, c: (admitted.extend(i) or len(i), 0)
    er.registry_reject = lambda i, why: (rejected.extend(i) or len(i))
    er.kb_ingest_verified = lambda ctx: (ingested.append(ctx) or {"new": 0})
    er.make_rework_card = lambda *a, **kw: None
    real_sh = er.sh

    def sh(cmd, timeout=60):
        if "tools/cross-verify.py" in cmd and "2>&1 | tail -1" in cmd:
            # --no-scp 必须插在管道之前（绝不推 gov；回流路径本就自带 --no-scp，重复无害）
            out = real_sh(cmd.replace(" 2>&1 | tail -1", " --no-scp 2>&1 | tail -1"),
                          timeout=timeout)
            # 2026-11-01 RT 修复配套：--no-scp 产出的结果 JSON 带 scp=false，而
            # scp=false 的新语义是「未送达」（event-router 据此不注册 open，见
            # make_verify_card 的 DEB-1 同款分支）。本夹具模拟的是「生成后推送成功」
            # 的派单面（scp 桩零推 gov）——把被桩掉的推送步骤补记为已送达，
            # V5/V6/V7 的派单断言口径不变（不是放水：未送达路径由 make_verify_card
            # 的 push_failed 分支与本次修复的探针另行覆盖）。
            try:
                j = json.loads(out)
                if isinstance(j, dict):
                    j["scp"] = True
                    for c in j.get("cards") or []:
                        if isinstance(c, dict):
                            c["scp"] = True
                out = json.dumps(j, ensure_ascii=False)
            except Exception:
                pass
            return out
        if cmd.startswith("scp "):
            scped.append(cmd)
            return ""
        return real_sh(cmd, timeout=timeout)
    er.sh = sh
    return er, {"admitted": admitted, "rejected": rejected, "ingested": ingested,
                "scped": scped}


def mkrep(cid, verdicts):
    return {"task_id": cid, "payload": {"verify": True, "card_id": cid,
            "verdicts": [{"atom_id": a, "verdict": v, "quote_check": True, "reason": "探针"}
                         for a, v in verdicts]}}


def case_dispatch(d):
    er, rec = make_router(d)
    st = er.load_state()
    cand = hermetic_fixture(d)  # 守卫见全 candidate：每卡实抽 12 条（真库已 admit 36/40）
    er.make_verify_card(st, cand)
    entry = st["verify_by_file"][cand]
    check(len(entry.get("card_ids") or []) == 2, "一次派发应注册 2 张卡：%r" % entry)
    cids = entry["card_ids"]
    check(entry["card_id"] == cids[0], "card_id 兼容键应为首张")
    for cid in cids:
        info = st["verify_cards"][cid]
        check(info["status"] == "open" and len(info["atom_ids"]) == 12,
              "卡状态/原子数异常：%r" % {k: info.get(k) for k in ("status", "sampled")})
    log = open(er.CHANGELOG, encoding="utf-8").read()
    check("2 张独立复核" in log and all(c in log for c in cids),
          "派单 changelog 未列全 k 张卡：%r" % log[-200:])
    check(not rec["scped"], "stub 后不应有 scp 记录：%r" % rec["scped"])
    # DRY 面：干跑不推送不落 changelog
    er2, rec2 = make_router(os.path.join(d, "dry"), dry=True)
    st2 = er2.load_state()
    er2.make_verify_card(st2, hermetic_fixture(os.path.join(d, "dry")))
    check(not rec2["scped"] and not os.path.exists(er2.CHANGELOG),
          "DRY 模式派单不得推送/写 changelog")
    return {"cards": cids, "changelog_lists_all": True, "dry_no_push": True}


def case_agreement_and_divergence(d):
    er, rec = make_router(d)
    st = er.load_state()
    cand = hermetic_fixture(d)  # 40 条全 candidate：两卡各 12 条、共有原子 ≥2 可算一致率
    er.make_verify_card(st, cand)
    c1, c2 = st["verify_by_file"][cand]["card_ids"]
    a1 = st["verify_cards"][c1]["atom_ids"]
    a2 = st["verify_cards"][c2]["atom_ids"]
    common = sorted(set(a1) & set(a2))
    check(len(common) >= 2, "两副本应有 ≥2 条共有原子才能算一致率（实测 %d）" % len(common))
    open(er.CHANGELOG, "w").close()
    # r1 先回报：全 uphold；r2 后回报：对 1 条共有原子 refute
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        er.handle_verify_report(st, c1 + ".json", os.path.join(er.VERIFY_DIR, "r1.json"),
                                mkrep(c1, [(a, "uphold") for a in a1]))
        adm_after_c1 = len(rec["admitted"])
        er.handle_verify_report(st, c2 + ".json", os.path.join(er.VERIFY_DIR, "r2.json"),
                                mkrep(c2, [(a, "refute" if a == common[0] else "uphold")
                                           for a in a2]))
    out = buf.getvalue()
    check("交叉验证一致率" in out, "一致率指标未进日志：%r" % out[-200:])
    m = re.search(r"同判 (\d+)/(\d+)=([\d.]+)", out)
    check(m is not None, "一致率指标格式异常：%r" % out[-200:])
    agree, compared = int(m.group(1)), int(m.group(2))
    check(compared == len(common) and agree == len(common) - 1,
          "一致率口径应只数双方都明裁决的共有原子：%d/%d（共有 %d）"
          % (agree, compared, len(common)))
    log = open(er.CHANGELOG, encoding="utf-8").read()
    check("分歧检测" in log, "一致率<1 未登记分歧检测行")
    check(c1 in log and c2 in log, "分歧检测行未列双方卡号：%r" % log[-300:])
    check(common[0] in log, "分歧检测行未列分歧原子：%r" % log[-300:])
    # 2026-11-02 RT-E32 修复后契约改钉：分歧行须声明「跨卡裁决时序消费腿已接管」
    # （旧钉「不阻塞 admit」是对旧纯观测机制的自述——该机制已被判缺陷，被更晚独立验证卡
    #  判 refute 的原子仍双库 verified；新契约=分歧行声明消费腿接管，admit 按裁决时序闸）。
    check("跨卡裁决时序消费腿已接管" in log,
          "分歧检测行应声明跨卡裁决时序消费腿已接管（RT-E32 新契约）：%r" % log[-300:])
    # admit 不被阻塞：两卡各自走完 admit；且各卡只 admit 自己裁 uphold 的原子
    # （2026-10-31 RT 审计修复：c2 对 common[0] refute 但 11/12=0.92≥0.8 卡仍过——
    #  旧口径 refute 原子随整卡搭车入库（合计 24），修复后 c2 只入其余 11 条，合计 23）
    check(len(rec["admitted"]) == len(a1) + len(a2) - 1 and len(rec["ingested"]) == 2,
          "分歧检测不应阻塞 admit，且被 refute 的原子不得随 c2 入库：admitted=%d ingested=%d"
          % (len(rec["admitted"]), len(rec["ingested"])))
    c2_added = rec["admitted"][adm_after_c1:]
    check(sorted(c2_added) == sorted(set(a2) - {common[0]}),
          "c2 只应 admit 其 uphold 原子（排除被 refute 的 %s）：%r"
          % (common[0], sorted(c2_added)))
    # 全同判 → 不出分歧行（一致率=1 只打日志）
    er3, rec3 = make_router(os.path.join(d, "agree1"))
    st3 = er3.load_state()
    cand3 = hermetic_fixture(os.path.join(d, "agree1"))
    er3.make_verify_card(st3, cand3)
    d1, d2 = st3["verify_by_file"][cand3]["card_ids"]
    b1 = st3["verify_cards"][d1]["atom_ids"]
    b2 = st3["verify_cards"][d2]["atom_ids"]
    com = sorted(set(b1) & set(b2))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        er3.handle_verify_report(st3, d1 + ".json", os.path.join(er3.VERIFY_DIR, "a.json"),
                                 mkrep(d1, [(a, "uphold") for a in b1]))
        er3.handle_verify_report(st3, d2 + ".json", os.path.join(er3.VERIFY_DIR, "b.json"),
                                 mkrep(d2, [(a, "uphold") for a in b2]))
    log3 = open(er3.CHANGELOG, encoding="utf-8").read()
    check("分歧检测" not in log3, "全同判不应登记分歧检测")
    check(f"同判 {len(com)}/{len(com)}=1.00" in buf.getvalue(),
          "一致率=1 时应持续打日志：%r" % buf.getvalue()[-200:])
    # unverifiable 不进一致率分子分母（口径钉死）
    er4, _ = make_router(os.path.join(d, "unver"))
    st4 = er4.load_state()
    cand4 = hermetic_fixture(os.path.join(d, "unver"))
    er4.make_verify_card(st4, cand4)
    e1, e2 = st4["verify_by_file"][cand4]["card_ids"]
    f1 = st4["verify_cards"][e1]["atom_ids"]
    f2 = st4["verify_cards"][e2]["atom_ids"]
    comf = sorted(set(f1) & set(f2))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        er4.handle_verify_report(st4, e1 + ".json", os.path.join(er4.VERIFY_DIR, "u1.json"),
                                 mkrep(e1, [(a, "uphold") for a in f1]))
        er4.handle_verify_report(st4, e2 + ".json", os.path.join(er4.VERIFY_DIR, "u2.json"),
                                 mkrep(e2, [(a, "unverifiable" if a == comf[0] else "uphold")
                                            for a in f2]))
    out4 = buf.getvalue()
    m4 = re.search(r"同判 (\d+)/(\d+)=([\d.]+)", out4)
    check(m4 is not None and int(m4.group(2)) == len(comf) - 1,
          "unverifiable 应排除出可比原子：%r（共有 %d）" % (out4[-160:], len(comf)))
    return {"agreement": "%d/%d" % (agree, compared), "divergence_logged": True,
            "admit_not_blocked": True, "refute_not_carried_into_admit": True,
            "agree1_no_log": True, "unverifiable_excluded": True}


def case_reflow(d):
    er, rec = make_router(d)
    st = er.load_state()
    # 夹具化（2026-10-29 收口）：真 registry 里这 40 条已全部 verified，生成前守卫会
    # 整集跳过、router 的 verify_by_file 只留 {"status":"skipped"}（无 card_ids 键）
    # → 旧断言 st["verify_by_file"][CAND]["card_ids"] 直接 KeyError。
    # 主路径跑全 candidate 夹具；skip 分支由 case_dispatch_guard_skip 显式断言。
    cand = hermetic_fixture(d)
    # resend_verify_card 按 candidates_file 的 basename 在 CAND_DIR 下解析候选清单
    # （event-router.py:557）——指到夹具目录，回流才同样读到全 candidate registry。
    er.CAND_DIR = os.path.dirname(cand)
    er.make_verify_card(st, cand)
    entry = st["verify_by_file"][cand]
    check(entry.get("status") == "open" and len(entry.get("card_ids") or []) == 2,
          "夹具 registry 全 candidate 时应派 2 张卡：%r" % entry)
    c1, c2 = entry["card_ids"]
    a2 = st["verify_cards"][c2]["atom_ids"]
    seeds = er.VERIFY_SEEDS
    line2 = f"| {c2}-1793200000000.json | rejected | kb-verify payload.verdicts 缺失或为空；合法格式：{{...}} | - |"
    er.poll_verify_rejects(st, [line2])
    new2 = f"kb-verify-kb-atoms-w4-{ARX}-2r2"
    check(os.path.isdir(os.path.join(seeds, new2)), "r2 被拒未重发：%r" % sorted(os.listdir(seeds)))
    m2 = json.load(open(os.path.join(seeds, new2, "meta.json"), encoding="utf-8"))["verify"]
    check(m2["atom_ids"] == a2 and m2.get("attempt") == 2 and m2.get("replica") == 2,
          "r2 回流未保持 atom 集/轮次/副本：%r" % {k: m2.get(k) for k in ("attempt", "replica")})
    check(st["verify_resends"].get(f"kb-atoms-w4-{ARX}-20261028-142910.jsonl#r2") == 1,
          "重发键应按 atom 集+副本记：%r" % st["verify_resends"])
    # 同一张再拒 → 第 2 次重发；第 3 次拒 → capped 不再生成
    er.poll_verify_rejects(st, [f"| {new2}-1793200000001.json | rejected | x | - |"])
    check(os.path.isdir(os.path.join(seeds, f"kb-verify-kb-atoms-w4-{ARX}-3r2")), "第 2 次重发未生成")
    before = sorted(os.listdir(seeds))
    er.poll_verify_rejects(st, [f"| kb-verify-kb-atoms-w4-{ARX}-3r2-1793200000002.json | rejected | y | - |"])
    check(sorted(os.listdir(seeds)) == before, "超上限后不得再生成新卡")
    check(st["verify_resends"][f"kb-atoms-w4-{ARX}-20261028-142910.jsonl#r2"] == 2,
          "r2 副本应独立计满 2 次上限：%r" % st["verify_resends"])
    # r1 独立：此时仍可重发（k 张各自独立计上限）
    er.poll_verify_rejects(st, [f"| {c1}-1793200000003.json | rejected | z | - |"])
    check(os.path.isdir(os.path.join(seeds, f"kb-verify-kb-atoms-w4-{ARX}-2r1")),
          "r1 应能独立重发：%r" % sorted(os.listdir(seeds)))
    check(st["verify_resends"].get(f"kb-atoms-w4-{ARX}-20261028-142910.jsonl#r1") == 1,
          "r1 独立计数异常：%r" % st["verify_resends"])
    # 在飞跳过：原卡再被拒而同一副本血线已有更新轮次在飞 → 不重复派单
    r = er.resend_verify_card(st, c1, "again")
    check(r == "skipped_newer", "同副本更新轮次在飞时应跳过，实得 %r" % r)
    log = open(er.CHANGELOG, encoding="utf-8").read()
    check("第 2/2 次重发" in log and "副本 r2" in log, "回流 changelog 口径异常：%r" % log[-200:])
    # 守卫 skip 分支在 router 侧的显式断言（同一用例内，故 V7 的 PASS 覆盖该分支）
    skip = case_dispatch_guard_skip(os.path.join(d, "skip"))
    return {"r2_resend": new2, "cap_per_replica": True, "r1_independent": True,
            "in_flight_skip": True, "guard_skip": skip}


def case_legacy_reflow(d):
    """老格式单卡回流对照：id 无 r 后缀、meta 无 replica 字段、attempt+1。"""
    er, rec = make_router(d)
    st = er.load_state()
    seeds = er.VERIFY_SEEDS
    # 候选清单落在 scratch（不写生产 kb-seed/sandbox）
    er.CAND_DIR = d
    legacy_id = "kb-verify-kb-atoms-legacy-2404.05427-1"
    os.makedirs(os.path.join(seeds, legacy_id), exist_ok=True)
    cand_name = "kb-atoms-legacy-2404.05427-20261028-000000.jsonl"
    cand_path = os.path.join(er.CAND_DIR, cand_name)
    with open(cand_path, "w", encoding="utf-8") as fh:
        for i in range(20):
            fh.write(json.dumps({"candidate_id": f"sbx-legacy-{i}", "kind": "claim",
                                 "text": f"t{i}", "source": {"locator": "L", "quote": "q"}},
                                ensure_ascii=False) + "\n")
    json.dump({"title": "t", "type": "kb-verify", "est_load": "x",
               "verify": {"card_id": legacy_id, "task_id": "kb-atoms-legacy-2404.05427",
                          "arxiv": "2404.05427", "candidates_file": cand_name,
                          "atoms_total": 20, "sampled": 5, "seed": "legacyseed",
                          "atom_ids": []}},
              open(os.path.join(seeds, legacy_id, "meta.json"), "w"), ensure_ascii=False)
    # 证据缓存：card-lint L4 要 abs.md>5KB（用现有 2404.05427 缓存，零网络）
    r = er.resend_verify_card(st, legacy_id, "verdicts 结构缺件 1/2；合法格式：{...}")
    check(r == "resent", "老格式回流应成功，实得 %r" % r)
    new_id = "kb-verify-kb-atoms-legacy-2404.05427-2"
    check(os.path.isdir(os.path.join(seeds, new_id)),
          "老格式回流 id 应无 r 后缀且 attempt+1：%r" % sorted(os.listdir(seeds)))
    m = json.load(open(os.path.join(seeds, new_id, "meta.json"), encoding="utf-8"))["verify"]
    check("replica" not in m, "老格式回流 meta 不应带 replica 字段：%r" % sorted(m))
    check(m.get("seed") == "legacyseed", "老格式回流应沿用原 seed：%r" % m.get("seed"))
    log = open(er.CHANGELOG, encoding="utf-8").read()
    check(f"`{legacy_id}` → 新版验证卡 `{new_id}`" in log, "老格式回流 changelog 异常：%r" % log[-200:])
    return {"legacy_resend": new_id, "no_r_suffix": True}


def case_no_regression(d):
    rsrc = open(ROUTER, encoding="utf-8").read()
    hsrc = open(HARVESTER, encoding="utf-8").read()
    csrc = open(CROSS, encoding="utf-8").read()
    check("if os.path.exists(STOP):" in rsrc and "STOP 熔断在位" in rsrc,
          "router 主循环 STOP 熔断检查不见了")
    check(rsrc.count("if DRY:") >= 6, "router DRY 门数量=%d（应 ≥6）" % rsrc.count("if DRY:"))
    for fn in ("save_state", "poll_harvest", "make_portal_seed", "registry_admit",
               "registry_reject", "handle_verify_report", "poll_verify_reports",
               "make_rework_card", "enqueue_rr55", "make_verify_card", "poll_orders",
               "resend_verify_card", "poll_verify_rejects", "kb_ingest_verified",
               "record_verify_agreement"):
        check(("def %s(" % fn) in rsrc, "router 函数 %s 不见了" % fn)
    for k in ('"verify_reports"', '"verify_scanned"', '"verify_reflows"',
              '"verify_resends"', '"verify_groups"', '"verify_cards"', '"verify_by_file"'):
        check(k in rsrc, "router 状态键 %s 不见了" % k)
    check("VERIFY_RESEND_CAP = 2" in rsrc, "回流重发上限常量被改")
    check('if os.path.exists(STOP) and not a.force:' in csrc, "cross-verify STOP 熔断不见了")
    check('DEFAULT_REPLICAS = 2' in csrc, "cross-verify 默认副本数应为 2")
    # harvester 展示：kb-verify 分支带回完整卡号（含副本号）
    check('"card": tid' in hsrc and "验证回报结构合格（卡 {tid}" in hsrc,
          "harvester kb-verify 展示未带回完整卡号")
    check(hsrc.count('tid.startswith("kb-verify")') == 1, "harvester kb-verify 判定分支异常")
    check('KINDS = {"claim"' in hsrc, "harvester KINDS 词表不见了")
    return {"stop_gate": True, "dry_gates": rsrc.count("if DRY:"), "functions_intact": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="验证放大 k 副本回归（战役优化批①）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录（排查用）")
    a = ap.parse_args(argv)

    for p, tag in ((CROSS, "cross-verify.py"), (ROUTER, "event-router.py"),
                   (HARVESTER, "sandbox-harvester.py"), (CARDLINT, "card-lint.py")):
        check(os.path.isfile(p), "缺文件：%s" % p)
    check(os.path.isfile(CAND), "缺候选文件：%s" % CAND)
    check(os.path.isfile(os.path.join(WS, "kb-seed/sandbox/evidence-cache", ARX, "abs.md")),
          "缺证据缓存（card-lint L4 需要）：%s" % ARX)

    os.makedirs(SCRATCH, exist_ok=True)
    results, failures = {}, []
    try:
        cases = [
            ("V1 单卡路径对照：--replicas 1 与改动前逐字节一致",
             lambda d: case_single_card_control(d)),
            ("V2 默认 k=2：id r1/r2 + 种子/抽样/视角差异化 + 全过 card-lint",
             lambda d: case_default_two_replicas(d)),
            ("V3 回流单副本：同 seed 同批原子，attempt+1，视角保留，不挤占他副本"
             "（夹具 registry + 守卫 skip 分支断言）",
             lambda d: case_replica_resend(d)),
            ("V4 id 方案与消费方正则（真实老/新格式行 + 合成新格式行）",
             lambda d: case_id_scheme()),
            ("V5 派单面：一次派 k 张入状态与 changelog；DRY 不推送",
             lambda d: case_dispatch(d)),
            ("V6 聚合与分歧：一致率口径 + 分歧检测行 + 消费腿接管声明（RT-E32 新契约）",
             lambda d: case_agreement_and_divergence(d)),
            ("V7 回流面：同副本 attempt+1；k 张各自独立计上限；在飞跳过"
             "（夹具 registry + 守卫 skip 分支断言）",
             lambda d: case_reflow(d)),
            ("V8 老格式回流对照：id 无 r 后缀、meta 无 replica 字段",
             lambda d: case_legacy_reflow(d)),
            ("V9 不回退：STOP/DRY/函数集/状态键/harvester 展示",
             lambda d: case_no_regression(d)),
        ]
        for i, (name, fn) in enumerate(cases):
            d = os.path.join(SCRATCH, "case-%d" % i)
            # 先清后建：上次被硬杀（超时/Ctrl-C）时 finally 的 rmtree 没跑到，残留
            # case 目录会让 next_attempt/卡目录对照读到上一轮的卡（假红）。
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
                print("  [FAIL] %s: %s: %s" % (name, type(e).__name__, e))
    finally:
        if not a.keep:
            shutil.rmtree(SCRATCH, ignore_errors=True)

    if failures:
        print("VAMP-REPLICAS FAILED: %d 项未过 -> %s" % (len(failures), failures))
        return EXIT_FAIL
    print("VAMP-REPLICAS PASSED: %d 项" % len(results))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
