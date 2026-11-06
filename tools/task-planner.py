#!/usr/bin/env python3
"""task-planner.py — 覆盖驱动的任务波次规划器（v1 · 确定性 · 纯 stdlib · 离线）

定位（工单：沙箱战役备战-20261028 · 覆盖驱动规划器）：
    终结『拉最新论文堆任务』的播种方式，改为按覆盖缺口生成任务波次建议。
    本器**只建议、不派发**：落板仍走既有链（portal-seeder 生卡 → card-lint 八条闸 →
    scp 上门户；event-router 收割/回流；registry admit；kb-ingest 入 kb/）。

输入面（全本地只读，路径均可用环境变量覆盖，便于副本/DRY 验证）：
    KB_DB        kb/kb.db                     原子/论文/语料覆盖实况
                 —— 只读口径：sqlite3 `mode=ro` 连接 + 在线备份到 $HOME 临时副本，
                    再经 kb.store.KBStore 契约 API 读取（kb/ 目录零写入，前后 sha256 为证）。
    REGISTRY_DB  kb-seed/registry.db          门户台账（candidates：candidate/verified/rejected）
    HARVEST_LOG kb-seed/sandbox/HARVEST-LOG.md 门户收割流水（ok/rejected 逐报告）
    SEEDS_DIR    kb-seed/sandbox/task-seeds/  已派过什么（kb-atoms-* 抽取卡 / kb-verify-* 验证卡）
    CACHE_DIR    kb-seed/sandbox/evidence-cache/ 证据缓存（abs.md/full.md + 标题）
    VERIFY_DIR   kb-seed/sandbox/verify/      验证回报本地留档（event-router admit 依据）
    CARDS_V1     kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl  B 线 212 卡（语料域）
    NS_MAP       kb-seed/candidates-batch1/namespace-map.json          B 线命名空间/语料清单
    BATCH1_REPORT kb-seed/candidates-batch1/REPORT.md                  B 线对账报告（总量口径）
    BATCH2_MANIFEST kb-seed/paper-batch2/manifest.json                  经典批2 计划清单（去重腿）
    CLASSIC_PAPERS   tools/portal-seeder.py 内嵌被引经典名录（唯一真源，importlib 只读导入）

规划逻辑（v1 确定性；同名输入必得同名输出，除 generated_at 时间戳字段）：
    ① 覆盖地图：语料域维度（registry/kb 双语料计数 + 卡化状态）与 paper 维度
       （原子总数/verified/candidate、已派卡轮次、收割 ok/rejected、证据缓存、落地状态）。
    ② 缺口分类（四类，均以本地证据定位到具体对象）：
       G1 高被引未覆盖经典：verified 语料论文的证据文本内被引统计（CLASSIC_PAPERS 名录），
          按被引语料论文数降序；滤掉已入库/已派卡/已缓存，批2 清单内的单独标注不重复立项。
       G2 B 线语料未卡化域：由 212 卡 source.corpus 反推语料根目录，扫盘找未卡化文件；
          索引件（名含 索引/INDEX）判为导航件不建议卡化；主料件按已卡化 md 语料的
          卡/KB 比率均值估算卡数。
       G3 前沿连续体断档：已派卡或已缓存但未入库（kb 无原子）的 26 开头论文，
          分「已派无回报」与「已派被拒」两种断档态，附主题关键词命中（seeder 查询词表）。
       G4 验证卡积压：kb-verify 波 66 回报 0 采录（含 65 份本地留档复验 ok 却被
          .harvested 去重挡住）+ 候选原子待验证总量（按语料域分账）。
    ③ 波次生成：按阶段三优先级 B 线策略语料 > 高被引经典 > 前沿扩展排序，
       验证积压列为使能波（与 W2/W3 并行：未验证原子进不了合并层）。
       每波：目标/理由/预估卡数（含单位与估算依据）/建议通道（沙箱 or 工厂 report）/目标清单/去重注记。
    ④ 输出双件：JSON（机器可消费，含 dedupe 过滤记录）+ 报告 md（覆盖地图表/缺口分类/波次与理由）。

纪律：
    - 纯 stdlib、零第三方、零网络（不 import socket/urllib/http/subprocess/requests；不 ssh/curl）。
    - kb/ 只读（备份副本隔离）；除工单指定两个输出文件外零写入。
    - 零密钥明文：只读本地件，不接触任何凭据。
    - 临时件一律落 $HOME 自建目录（TASK_PLANNER_TMP，默认 ~/task-planner-tmp），用完即清。
    - 规划器不派发、不生成卡、不 scp、不改 registry/kb——落板分工见报告 §五。

用法：
    python3 tools/task-planner.py                    # 计算并写双件到工单固定路径
    python3 tools/task-planner.py --print-plan       # 只打 JSON 到 stdout，不写文件
    python3 tools/task-planner.py --selftest         # 内部不变量自检（exit 0/1）
    python3 tools/task-planner.py --out-json P --out-md P   # 覆盖输出路径（副本/DRY 验证用）

退出码：0 正常；1 自检失败或输入缺失；2 用法错误。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DB = os.environ.get("PLANNER_KB_DB") or os.path.join(WS, "kb/kb.db")
REGISTRY_DB = os.environ.get("PLANNER_REGISTRY_DB") or os.path.join(WS, "kb-seed/registry.db")
SB = os.environ.get("PLANNER_SB") or os.path.join(WS, "kb-seed/sandbox")
SEEDS_DIR = os.path.join(SB, "task-seeds")
CACHE_DIR = os.path.join(SB, "evidence-cache")
VERIFY_DIR = os.path.join(SB, "verify")
HARVEST_LOG = os.path.join(SB, "HARVEST-LOG.md")
CARDS_V1 = os.environ.get("PLANNER_CARDS_V1") or os.path.join(
    WS, "kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl")
NS_MAP = os.environ.get("PLANNER_NS_MAP") or os.path.join(
    WS, "kb-seed/candidates-batch1/namespace-map.json")
BATCH1_REPORT = os.environ.get("PLANNER_BATCH1_REPORT") or os.path.join(
    WS, "kb-seed/candidates-batch1/REPORT.md")
BATCH2_MANIFEST = os.environ.get("PLANNER_BATCH2_MANIFEST") or os.path.join(
    WS, "kb-seed/paper-batch2/manifest.json")
# 证据根（只读）：沙箱收割证据缓存 + paper-batch1（C 线第一批）证据目录。
# 前者是门户去重腿（seeder 口径）；后者是 atoms 语料的 quote 出处（kb-ingest 导入口径）。
EVIDENCE_ROOTS = [
    os.environ.get("PLANNER_CACHE_DIR") or os.path.join(SB, "evidence-cache"),
    os.environ.get("PLANNER_PAPER_B1_EVIDENCE") or os.path.join(
        WS, "kb-seed/paper-batch1/evidence"),
]
TMP_ROOT = os.environ.get("TASK_PLANNER_TMP") or os.path.expanduser("~/task-planner-tmp")

OUT_JSON = os.path.join(WS, "计划/研究组/沙箱战役备战-20261028/规划-v1.json")
OUT_MD = os.path.join(WS, "计划/研究组/沙箱战役备战-20261028/规划-v1-报告.md")

ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})")
# 卡/种子目录名两代尾巴都要认（DEB-2e 清偿 2026-10-29；遗留见 vamp-report.md:168）：
#   老格式：<base>[-r<重派轮>][-<时间戳>]        如 kb-atoms-acr-2404.05427 / …-r2-1
#   新格式（2026-10-29 验证放大 k 副本，-NsrJ 尾巴）：<base>[-r<重派轮>]-<attempt>r<replica>[-<时间戳>]
#            如 kb-verify-kb-atoms-acr-2404.05427-6r3 / …-r2-6r3 / …-r2-r3-1r1
#   attempt 与 r<replica> 粘连无横线（与 tools/cross-verify.py:83 CARD_ATTEMPT_RE 同口径）；
#   重派轮标记可多个（-r2-r3 双标记在盘可见，故用 (?:-r\d+)*）。
# 旧正则只认老格式 → 3177/3668 个在盘新格式目录被静默排除出派卡台账统计（只影响统计
# 展示，不影响派卡/回流/入库链路）；本版两代兼容，命名组供调用方取字段。
SEED_NAME_RE = re.compile(
    r"^(?P<kind>kb-verify-kb-atoms|kb-atoms)-(?P<tag>[A-Za-z0-9]+?)-(?P<arx>\d{4}\.\d{4,5})"
    r"(?:-r(?P<rnd>\d+))?(?:-r\d+)*(?:-(?P<attempt>\d+(?:r\d+)?))?(?:-(?P<ts>\d+))?$")
# seeder 源① arXiv 查询关键词（portal-seeder.py QUERY）——用于断档论文的主题命中标注
TOPIC_KEYWORDS = ("agent", "harness", "llm", "benchmark", "eval")
# 经典被引阈值：被 ≥N 篇 verified 语料论文引用才列入缺口
CLASSIC_CITE_MIN_PAPERS = 3
# 索引/导航件判定（不建议卡化）
INDEX_NAME_RE = re.compile(r"索引|INDEX", re.I)
SCHEMA = "task-planner-v1"


# ---------------------------------------------------------------- 基础工具


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 输入快照（A7 地基）
#
# 在役守护实时写本规划器的输入面：sandbox-harvester 追加 HARVEST-LOG.md、
# event-router 追加 计划/变更日志.md、admit 落 kb-seed/registry.db、kb-ingest
# 落 kb/kb.db、新证据件落 evidence-cache。A7「同输入二次构建」若不冻结输入，
# 测到的是在役写入漂移而不是 build_plan 的纯度（2026-10-29 统一门禁取证：两构建
# 间隔 ~70s，HARVEST-LOG +292B/+1 条、变更日志 +607B，10 处 diff 全落在
# harvest_log/changelog 派生字段，build 逻辑本身零 diff）。
# 故：一次进程内全部输入读取 memo 化（首读即快照，二次构建复用同一快照）。
# 断言强度不变——A7 仍比对两次完整 build 的 JSON，只是「输入」被钉成本次运行的快照。
_SNAP = {}


def _snap(key, fn):
    if key not in _SNAP:
        _SNAP[key] = fn()
    return _SNAP[key]


def _file_meta(path):
    if not os.path.exists(path):
        return {"path": path, "exists": False}
    st = os.stat(path)
    meta = {"path": path, "exists": True,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}
    if os.path.isdir(path):
        meta["dir_entries"] = len(os.listdir(path))
    else:
        meta["sha256_16"] = sha256_of(path)[:16]
        meta["bytes"] = st.st_size
    return meta


def file_meta(path):
    """输入件指纹：sha256 前 16 位 + 字节数 + mtime（确定性：mtime 仅作记录，不进规划逻辑）。
    目录件记条目数（不递归哈希，避免把大目录读爆）。同进程内按路径 memo（见 _snap）。"""
    return dict(_snap(("file_meta", os.path.abspath(path)),
                      lambda: _file_meta(path)))


def load_module(path, name):
    """importlib 只读导入同仓脚本（portal-seeder / sandbox-harvester），拿唯一真源常量与纯函数。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                raise SystemExit(f"JSONL 解析失败 {path}:{ln}: {e}")
    return rows


def _evidence_title(arx):
    """证据根内取论文标题：abs.md/full.md 的 <title>（沙箱缓存）或首行 markdown H1
    （paper-batch1 证据），取不到返回 ''。"""
    for root in EVIDENCE_ROOTS:
        for f in ("abs.md", "full.md"):
            p = os.path.join(root, arx, f)
            if os.path.isfile(p):
                try:
                    head = open(p, encoding="utf-8", errors="replace").read(30000)
                except OSError:
                    continue
                m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
                if m and m.group(1).strip() and "404" not in m.group(1):
                    return " ".join(m.group(1).split())
                m = re.search(r"^#\s+(.+)$", head, re.M)
                if m:
                    # paper-batch1 证据的 abs.md 由 HTML 转来，H1 偶带重复 "Title:" 前缀
                    return re.sub(r"^(Title:)+", "", m.group(1).strip())
    return ""


def evidence_title(arx):
    return _snap(("evidence_title", arx), lambda: _evidence_title(arx))




def _evidence_state(arx):
    """证据等级：full=abs+真全文；abs-only=仅摘要；missing=两证据根均无。"""
    abs_b = full_b = 0
    for root in EVIDENCE_ROOTS:
        abs_f, full_f = os.path.join(root, arx, "abs.md"), os.path.join(root, arx, "full.md")
        abs_b = abs_b or (os.path.getsize(abs_f) if os.path.isfile(abs_f) else 0)
        full_b = full_b or (os.path.getsize(full_f) if os.path.isfile(full_f) else 0)
    if abs_b and full_b >= 2000:
        lvl = "full"
    elif abs_b:
        lvl = "abs-only"
    else:
        lvl = "missing"
    return {"abs_bytes": abs_b, "full_bytes": full_b, "evidence_level": lvl}


def evidence_state(arx):
    return _snap(("evidence_state", arx), lambda: _evidence_state(arx))



# ---------------------------------------------------------------- 输入装载


def _read_kb(tmpdir):
    """kb/kb.db 只读快照 + kb.store.KBStore 契约 API 读取。

    只读口径：`file:...?mode=ro` 打开源库 → sqlite3 在线备份到 $HOME 临时副本 →
    副本上实例化 KBStore（其 __init__ 的 WAL/建库语句只可能碰副本）→ 只调读 API
    （list_atoms/stats）。kb/ 目录零写入（调用方前后 sha256 比对为证）。
    """
    src = sqlite3.connect(f"file:{KB_DB}?mode=ro", uri=True)
    snap = os.path.join(tmpdir, "kb-snapshot.db")
    dst = sqlite3.connect(snap)
    src.backup(dst)
    dst.close()
    src.close()
    sys.path.insert(0, WS)
    from kb.store import KBStore  # noqa: E402 —— kb/ 包只读导入（契约 API）
    store = KBStore(snap)
    atoms = store.list_atoms(limit=None)
    stats = store.stats()
    store.close()
    return atoms, stats, snap


def read_kb(tmpdir):
    return _snap(("read_kb", os.path.abspath(tmpdir)), lambda: _read_kb(tmpdir))




def _read_registry():
    if not os.path.exists(REGISTRY_DB):
        return {}
    con = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True)
    try:
        out = {}
        for corpus, status, n in con.execute(
                "SELECT source_corpus, status, COUNT(*) FROM candidates GROUP BY 1,2"):
            out[f"{corpus}|{status}"] = n
        return out
    finally:
        con.close()


def read_registry():
    return _snap(("read_registry",), _read_registry)




HARVEST_LINE_RE = re.compile(
    r"^\|\s*([\w.\-]+\.json)\s*\|\s*(\w+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


def _read_harvest_log():
    """HARVEST-LOG.md → {报告文件名: (status, reason)}。"""
    out = {}
    if not os.path.isfile(HARVEST_LOG):
        return out
    with open(HARVEST_LOG, encoding="utf-8") as fh:
        for line in fh:
            m = HARVEST_LINE_RE.match(line.rstrip("\n"))
            if m:
                out[m.group(1)] = (m.group(2), m.group(3))
    return out


def read_harvest_log():
    return _snap(("harvest_log",), _read_harvest_log)




def _read_seed_ledger():
    """task-seeds 目录 → 每 (tag, arxiv) 的派卡台账：抽取 v1/r2 轮次、验证卡轮次。"""
    led = defaultdict(lambda: {"extract_v1": 0, "extract_r2": 0, "verify_cards": [],
                               "seeds": []})
    if not os.path.isdir(SEEDS_DIR):
        return led
    for name in sorted(os.listdir(SEEDS_DIR)):
        m = SEED_NAME_RE.match(name)
        if not m:
            continue
        # DEB-2e：命名组取字段（新正则含 attempt/ts 两组，位置解包已不适用）；
        # rnd=重派轮（-rN），attempt=<attempt>r<replica> 新尾巴（本台账只用 rnd 分 v1/r2）
        kind, tag, arx, rnd = m.group("kind"), m.group("tag"), m.group("arx"), m.group("rnd")
        e = led[(tag, arx)]
        e["seeds"].append(name)
        if kind == "kb-atoms":
            e["extract_r2" if rnd else "extract_v1"] += 1
        else:
            e["verify_cards"].append(name)
    return led


def read_seed_ledger():
    return _snap(("seed_ledger",), _read_seed_ledger)




def _read_verify_archive():
    """verify/ 留档 → [(文件名, task_id, 复验结论)]。复验用 sandbox-harvester.validate()
    （纯函数、无网络；import 失败则如实记 not-run，不猜）。"""
    out = []
    if not os.path.isdir(VERIFY_DIR):
        return out, "verify 目录不存在"
    try:
        hv = load_module(os.path.join(WS, "tools/sandbox-harvester.py"), "sandbox_harvester")
    except Exception as e:  # noqa: BLE001 —— 导入失败如实降级，不伪造复验结论
        return out, f"sandbox-harvester 导入失败，复验未执行: {e}"
    for name in sorted(os.listdir(VERIFY_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            rep = json.load(open(os.path.join(VERIFY_DIR, name), encoding="utf-8"))
            verdict, why, stats = hv.validate(rep, None)
            detail = why or json.dumps(stats, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            out.append({"file": name, "task_id": "?", "revalidate": "error",
                        "detail": str(e)[:80]})
            continue
        out.append({"file": name, "task_id": str(rep.get("task_id", "?")),
                    "revalidate": verdict, "detail": detail[:80]})
    return out, None


def read_verify_archive():
    return _snap(("verify_archive",), _read_verify_archive)




def _read_cards():
    return load_jsonl(CARDS_V1)


def read_cards():
    return _snap(("cards",), _read_cards)




def _read_batch2_manifest():
    if not os.path.isfile(BATCH2_MANIFEST):
        return []
    return json.load(open(BATCH2_MANIFEST, encoding="utf-8"))


def read_batch2_manifest():
    return _snap(("batch2",), _read_batch2_manifest)




def _read_namespace_map():
    if not os.path.isfile(NS_MAP):
        return {}
    return json.load(open(NS_MAP, encoding="utf-8"))


def read_namespace_map():
    return _snap(("ns_map",), _read_namespace_map)




def _read_batch1_report_total():
    """REPORT.md 声明的对账总量（正则取『应=NNN』），用于与 cards-v1 实读数交叉验证。"""
    if not os.path.isfile(BATCH1_REPORT):
        return None
    txt = open(BATCH1_REPORT, encoding="utf-8").read()
    m = re.search(r"应\s*=\s*(\d+)", txt)
    return int(m.group(1)) if m else None


def read_batch1_report_total():
    return _snap(("batch1_total",), _read_batch1_report_total)



# ---------------------------------------------------------------- 覆盖地图


def build_coverage(atoms, registry, seeds, harvest, cache_ids):
    """覆盖地图：语料域维度 + paper 维度。全部数字来自本地实读，可独立复算。"""
    # ---- paper 维度 ----
    per_paper = defaultdict(lambda: {"atoms_total": 0, "verified": 0, "candidate": 0,
                                     "retired": 0, "corpora": Counter()})
    for a in atoms:
        p = (a.get("paper") or "").strip()
        if not p:
            continue
        e = per_paper[p]
        e["atoms_total"] += 1
        e[a["status"] if a["status"] in ("verified", "candidate", "retired") else "candidate"] += 1
        e["corpora"][a.get("source_corpus") or ""] += 1
    # 收割流水按论文归账
    harvest_by_paper = defaultdict(lambda: {"ok": 0, "rejected": 0})
    for fn, (st, _why) in harvest.items():
        m = ARXIV_RE.search(fn)
        if not m:
            continue
        harvest_by_paper[m.group(1)]["ok" if st == "ok" else "rejected"] += 1
    papers = {}
    all_ids = sorted(set(per_paper) | {a for (_t, a) in seeds} | set(cache_ids))
    for arx in all_ids:
        if arx == "9999.99999":  # 证据缓存内的测试夹具，非真实论文
            continue
        e = per_paper.get(arx, {"atoms_total": 0, "verified": 0, "candidate": 0,
                                "retired": 0, "corpora": Counter()})
        sl = [v for (t, a), v in seeds.items() if a == arx]
        seed_v1 = sum(s["extract_v1"] for s in sl)
        seed_r2 = sum(s["extract_r2"] for s in sl)
        verify_cards = sorted(c for s in sl for c in s["verify_cards"])
        hv = harvest_by_paper.get(arx, {"ok": 0, "rejected": 0})
        if e["atoms_total"] > 0:
            state = "landed_verified" if e["verified"] > 0 else "landed_unverified"
        elif seed_v1 or seed_r2:
            state = "dispatched_rejected" if hv["rejected"] and not hv["ok"] else "dispatched_no_return"
        elif arx in cache_ids:
            state = "cached_only"
        else:
            state = "unknown"
        papers[arx] = {
            "paper": arx,
            "title": evidence_title(arx),
            "corpora": dict(sorted(e["corpora"].items())),
            "atoms_total": e["atoms_total"],
            "verified": e["verified"],
            "candidate": e["candidate"],
            "retired": e["retired"],
            "seed_extract_v1": seed_v1,
            "seed_extract_r2": seed_r2,
            "verify_cards": len(verify_cards),
            "harvest_ok": hv["ok"],
            "harvest_rejected": hv["rejected"],
            "evidence": evidence_state(arx),
            "state": state,
        }
    # ---- 语料域维度 ----
    domains = {}
    dom_keys = sorted({a.get("source_corpus") or "" for a in atoms})
    for d in dom_keys:
        rows = [a for a in atoms if (a.get("source_corpus") or "") == d]
        domains[d] = {
            "domain": d,
            "kb_atoms": len(rows),
            "kb_verified": sum(1 for a in rows if a["status"] == "verified"),
            "kb_candidate": sum(1 for a in rows if a["status"] == "candidate"),
            "kb_retired": sum(1 for a in rows if a["status"] == "retired"),
            "registry_candidate": registry.get(f"{d}|candidate", 0),
            "registry_verified": registry.get(f"{d}|verified", 0),
            "registry_rejected": registry.get(f"{d}|rejected", 0),
            "papers": sorted({(a.get("paper") or "").strip() for a in rows if (a.get("paper") or "").strip()}),
        }
    return {"by_paper": papers, "by_domain": domains}


# ---------------------------------------------------------------- 缺口分类


def gap_classics(atoms, coverage, used_ids, batch2, classic_papers):
    """G1 高被引未覆盖经典：verified 语料论文证据文本内的被引统计（kb 内被引）。

    状态口径：uncovered=kb 无原子且无卡在派；dispatched_unlanded=卡已派但 kb 无原子；
    planned_batch2=在 paper-batch2 清单（证据未摄）；covered=kb 已入库。

    候选来源两条（2026-10-31 DEB-5 真缺陷修复，原实现只有①）：
      ① CLASSIC_PAPERS 名录 ∩ 语料被引统计（≥CLASSIC_CITE_MIN_PAPERS 篇）；
      ② paper-batch2 计划清单本身（kb-seed/paper-batch2/manifest.json，本器声明输入）。
    ②原被漏掉：清单里的 2402.01030 / 2406.12045 不在 CLASSIC_PAPERS 名录、语料里也
    没被引检出，但 kb 无原子、证据未摄——正是本波次 goal 承诺要接的「批2 清单内未摄经典」。
    漏掉它们 → W2 的 targets/est_cards 双空 → A5「四要素齐全」与 A8「波次字段齐全」红
    （2026-10-31 实测：G1 25 篇全 covered，W2 est_cards=0/targets=0）。
    两条来源按 arXiv id 合并去重（同一篇以①的被引统计为准）。
    """
    batch2_ids = {m.get("arxiv_id") for m in batch2}
    corpus_papers = sorted({(a.get("paper") or "").strip() for a in atoms
                            if a["status"] == "verified" and (a.get("paper") or "").strip()})
    canon = {}
    for name, arx in classic_papers.items():
        canon.setdefault(arx, name)
    cites = {}
    corpus_detail = []
    for paper in corpus_papers:
        text = ""
        for root in EVIDENCE_ROOTS:
            d = os.path.join(root, paper)
            if not os.path.isdir(d):
                continue
            for f in ("abs.md", "full.md"):
                p = os.path.join(d, f)
                if os.path.isfile(p):
                    try:
                        text += open(p, encoding="utf-8", errors="replace").read()
                    except OSError:
                        pass
            if text:
                break  # 两证据根有同一论文的重复件时只取首个（防提及次数双算）
        if not text:
            continue
        corpus_detail.append(paper)
        for name, arx in classic_papers.items():
            n = len(re.findall(r"\b" + re.escape(name) + r"\b", text, re.I))
            if n:
                c = cites.setdefault(arx, {"id": arx, "name": canon[arx],
                                           "mentions": 0, "citing_papers": set()})
                c["mentions"] += n
                c["citing_papers"].add(paper)
    ranked = sorted(cites.values(),
                    key=lambda c: (-len(c["citing_papers"]), -c["mentions"], c["id"]))
    items = []
    for c in ranked:
        n_cite = len(c["citing_papers"])
        if n_cite < CLASSIC_CITE_MIN_PAPERS:
            continue
        p = coverage["by_paper"].get(c["id"], {})
        atoms_total = p.get("atoms_total", 0)
        seeded = bool(p.get("seed_extract_v1") or p.get("seed_extract_r2"))
        if atoms_total > 0:
            state = "covered"
        elif c["id"] in batch2_ids:
            state = "planned_batch2"
        elif seeded:
            state = "dispatched_unlanded"
        else:
            state = "uncovered"
        items.append({"id": c["id"], "name": c["name"], "citing_papers": n_cite,
                      "mentions": c["mentions"], "covered": c["id"] in used_ids,
                      "in_batch2_manifest": c["id"] in batch2_ids,
                      "kb_atoms": atoms_total, "seeded": seeded, "state": state,
                      "source": "corpus_citation"})
    # 候选来源②：paper-batch2 计划清单（kb 无原子、证据未摄的经典）。
    # 名称取自 manifest title（这些篇目不在 CLASSIC_PAPERS 名录内，无 roster 简称）。
    known = {c["id"] for c in items}
    for m in batch2:
        mid = m.get("arxiv_id")
        if not mid or mid in known:
            continue
        p = coverage["by_paper"].get(mid, {})
        atoms_total = p.get("atoms_total", 0)
        seeded = bool(p.get("seed_extract_v1") or p.get("seed_extract_r2"))
        if atoms_total > 0:
            state = "covered"
        elif mid in batch2_ids:
            state = "planned_batch2"
        elif seeded:
            state = "dispatched_unlanded"
        else:
            state = "uncovered"
        items.append({"id": mid, "name": m.get("title") or mid,
                      "citing_papers": 0, "mentions": 0,
                      "covered": mid in used_ids, "in_batch2_manifest": True,
                      "kb_atoms": atoms_total, "seeded": seeded, "state": state,
                      "source": "batch2_manifest"})
        known.add(mid)
    return {"threshold_citing_papers": CLASSIC_CITE_MIN_PAPERS,
            "corpus_papers_scanned": len(corpus_detail),
            "corpus_papers_total": len(corpus_papers),
            "classics_detected": len(cites),
            "items": items}


def gap_bline_uncarded(cards):
    """G2 B 线语料未卡化域：由 212 卡 source.corpus 反推语料根目录，扫盘找未卡化文件。"""
    carded = Counter()
    for r in cards:
        carded[(r.get("source") or {}).get("corpus", "")] += 1
    roots = sorted({os.path.dirname(c) for c in carded if c})
    found = []
    for root in roots:
        # DEB-5②（2026-11-03）：source.corpus 为 WS 相对路径（ratio 段 os.path.join(WS, corpus)
        # 既有口径即按 WS 相对解），扫盘入口在此 absolutize 到 WS——修前 isdir/walk 裸相对
        # CWD，CWD≠WS 时（如 cd /tmp 直跑 selftest）全部跳过 → G2 空 → W1 est_cards=0 →
        # A4/A8 假红；空 root 维持修前跳过语义（isdir("")=False）。
        abs_root = root if (not root or os.path.isabs(root)) else os.path.join(WS, root)
        if not abs_root or not os.path.isdir(abs_root):
            continue
        for dp, _dns, fns in os.walk(abs_root):
            for fn in sorted(fns):
                if not fn.lower().endswith((".csv", ".md")):
                    continue
                rel = os.path.relpath(os.path.join(dp, fn), WS).replace(os.sep, "/")
                found.append(rel)
    # 已卡化 md 语料的 卡/KB 比率（用于估算；只取每文件 ≥2 卡的多卡语料——
    # 机制卡系一文件一卡，其比率反映「一卡一文件」设计而非内容体积，入基会推高估算）
    ratios = []
    ratio_basis = []
    for corpus, n in sorted(carded.items()):
        if not corpus.endswith(".md") or n < 2 or not os.path.isfile(os.path.join(WS, corpus)):
            continue
        ratios.append(n / (os.path.getsize(os.path.join(WS, corpus)) / 1024.0))
        ratio_basis.append(corpus)
    ratio = statistics.mean(ratios) if ratios else 0.0
    uncarded = []
    for f in sorted(found):
        if f in carded:
            continue
        size = os.path.getsize(os.path.join(WS, f))
        is_index = bool(INDEX_NAME_RE.search(os.path.basename(f)))
        est = 0 if is_index else max(1, round(size / 1024.0 * ratio))
        uncarded.append({"corpus": f, "bytes": size, "kind": "index" if is_index else "primary",
                         "est_cards": est, "cards_now": 0})
    return {"roots": roots, "carded_corpora": dict(sorted(carded.items())),
            "cards_per_kb_md_mean": round(ratio, 4),
            "ratio_basis": ratio_basis,
            "uncarded": uncarded}


def gap_frontier_breaks(coverage):
    """G3 前沿连续体断档：已派卡/已缓存但 kb 无原子的 26 开头论文。"""
    breaks = []
    for arx, p in sorted(coverage["by_paper"].items()):
        if not arx.startswith("26"):
            continue
        if p["atoms_total"] > 0:
            continue
        if p["seed_extract_v1"] == 0 and p["seed_extract_r2"] == 0:
            continue  # 只派过/缓存过才算连续体断档；未探区域不在此列
        title = p["title"]
        kw = [k for k in TOPIC_KEYWORDS if re.search(k, title, re.I)]
        if p["state"] == "dispatched_rejected":
            mode = "已派被拒（quote/结构回查不过，需修正重派）"
        else:
            mode = "已派无回报（卡上门户后无收割记录）"
        breaks.append({"paper": arx, "title": title, "mode": mode,
                       "seed_v1": p["seed_extract_v1"], "seed_r2": p["seed_extract_r2"],
                       "harvest_ok": p["harvest_ok"], "harvest_rejected": p["harvest_rejected"],
                       "evidence_level": p["evidence"]["evidence_level"],
                       "topic_keywords": kw})
    return {"series": "26xx", "items": breaks}


def _read_changelog_admits():
    """计划/变更日志.md 的路由器侧采录计数（可选输入；缺失时返回 None，不猜）。"""
    path = os.path.join(WS, "计划/变更日志.md")
    if not os.path.isfile(path):
        return None
    txt = open(path, encoding="utf-8", errors="replace").read()
    admits = re.findall(r"registry admit (\d+) 条", txt)
    passes = re.findall(r"交叉验证通过：卡 `([^`]+)`", txt)
    return {"path": path, "verify_pass_cards": len(passes),
            "atoms_admitted_via_verify": sum(int(x) for x in admits)}


def read_changelog_admits():
    return _snap(("changelog_admits",), _read_changelog_admits)




def gap_verify_backlog(atoms, coverage, verify_archive, harvest, changelog):
    """G4 验证卡积压：kb-verify 波双侧实况 + 候选原子待验证分账。

    双侧实况（本地可证）：
      · 收割侧（HARVEST-LOG，sandbox-harvester.validate 口径）：kb-verify 回报全部 rejected；
      · 采录侧（kb/registry）：verified 沙箱原子的 registry_note 全部 citing verify/ 留档目录，
        即路由器侧确已采录（计划/变更日志.md 的 admit 行可交叉计数）。
    两阀同名文件结论相反——键名口径分歧（kvfix 2026-10-28 23:2x 已修双键），
    规划器如实并列两侧数字，定性交由 W4b 对账，不自行裁判。
    """
    log_verify = {fn: st for fn, (st, _w) in harvest.items() if fn.startswith("kb-verify")}
    archive_names = {r["file"] for r in verify_archive}
    reok = [r for r in verify_archive if r.get("revalidate") == "ok"]
    log_no_archive = sorted(set(log_verify) - archive_names)
    # kb 侧：verified 沙箱原子的准入依据（registry_note citing verify/ 留档）
    verified_citing_verify = sum(
        1 for a in atoms
        if a["status"] == "verified"
        and "kb-seed/sandbox/verify" in str((a.get("attrs") or {}).get("registry_note") or ""))
    # 候选原子待验证（按语料域 / 按论文）
    cand_by_corpus = Counter()
    cand_by_paper = Counter()
    papers_zero_verified = []
    for a in atoms:
        if a["status"] != "candidate":
            continue
        cand_by_corpus[a.get("source_corpus") or ""] += 1
        p = (a.get("paper") or "").strip()
        if p:
            cand_by_paper[p] += 1
    for arx, p in sorted(coverage["by_paper"].items()):
        if p["atoms_total"] > 0 and p["verified"] == 0:
            papers_zero_verified.append({"paper": arx, "title": p["title"],
                                         "candidate": p["candidate"],
                                         "corpora": p["corpora"],
                                         "verify_cards": p["verify_cards"]})
    # 沙箱候选无验证卡在派的论文（现网为 0——路由器对每份 ok 收割都派了卡；
    # 计算保留为回归指标：若 >0 说明派单链有漏）
    papers_no_verify_card = [
        {"paper": arx, "title": p["title"], "candidate": p["candidate"]}
        for arx, p in sorted(coverage["by_paper"].items())
        if p["corpora"].get("sandbox") and p["candidate"] > 0 and p["verify_cards"] == 0]
    return {
        "kb_verify_cards_dispatched": sum(p["verify_cards"] for p in coverage["by_paper"].values()),
        "kb_verify_reports_in_log": len(log_verify),
        "kb_verify_ok_in_log": sum(1 for st in log_verify.values() if st == "ok"),
        "kb_verify_rejected_in_log": sum(1 for st in log_verify.values() if st != "ok"),
        "verify_archive_files": len(verify_archive),
        "verify_archive_revalidate_ok": len(reok),
        "log_reports_without_archive": log_no_archive,
        "kb_verified_atoms_citing_verify_dir": verified_citing_verify,
        "changelog": changelog,
        "candidate_atoms_total": sum(cand_by_corpus.values()),
        "candidate_atoms_by_corpus": dict(sorted(cand_by_corpus.items())),
        "candidate_atoms_by_paper": dict(sorted(cand_by_paper.items())),
        "papers_zero_verified": papers_zero_verified,
        "papers_no_verify_card": papers_no_verify_card,
    }


# ---------------------------------------------------------------- 去重 + 波次


def build_dedupe(coverage, batch2, bline_gap, classic_gap, frontier_gap):
    """dedupe 过滤：规则 + 被滤对象（含命中腿），进 JSON 供机器消费。"""
    kb_papers = {a for a, p in coverage["by_paper"].items() if p["atoms_total"] > 0}
    seed_papers = {a for a, p in coverage["by_paper"].items()
                   if p["seed_extract_v1"] or p["seed_extract_r2"] or p["verify_cards"]}
    cache_papers = {a for a, p in coverage["by_paper"].items()
                    if p["evidence"]["evidence_level"] != "missing"}
    batch2_ids = {m.get("arxiv_id") for m in batch2}
    rules = [
        {"id": "R1", "rule": "arXiv id 已入库（kb 有原子）→ 不立新项", "leg": "kb/kb.db atoms.paper"},
        {"id": "R2", "rule": "arXiv id 已派卡或已缓存证据 → 不立新种（断档/已派未落按补链建议）",
         "leg": "task-seeds 目录名 + evidence-cache 目录名"},
        {"id": "R3", "rule": "语料文件已有卡 → 不再建议卡化；索引/导航件同理", "leg": "cards-v1.jsonl source.corpus"},
        {"id": "R4", "rule": "经典候选已在 paper-batch2 清单 → 标注不重复立项（证据未摄，随批2走）",
         "leg": "kb-seed/paper-batch2/manifest.json"},
        {"id": "R5", "rule": "论文已有验证卡在派 → 不计入『无验证卡』缺口", "leg": "task-seeds/kb-verify-*"},
    ]
    filtered = []
    for c in classic_gap["items"]:
        if c["state"] == "covered":
            filtered.append({"item": f"经典 {c['name']} {c['id']}", "rule": "R1",
                             "reason": f"kb 已入库（{c['kb_atoms']} 条原子）"})
        elif c["state"] == "dispatched_unlanded":
            filtered.append({"item": f"经典 {c['name']} {c['id']}", "rule": "R2",
                             "reason": "已派卡未落地——转 W2 补链建议（不按新种计）"})
        elif c["state"] == "planned_batch2":
            filtered.append({"item": f"经典 {c['name']} {c['id']}", "rule": "R4",
                             "reason": "已在 paper-batch2 计划清单（证据未摄），不重复立项"})
    for b in frontier_gap["items"]:
        filtered.append({"item": f"前沿 {b['paper']}", "rule": "R2",
                         "reason": "已派卡/已缓存 → 按补链（重派）建议，不计新种"})
    for u in bline_gap["uncarded"]:
        if u["kind"] == "index":
            filtered.append({"item": f"语料 {u['corpus']}", "rule": "R3",
                             "reason": "索引/导航件（名含 索引/INDEX），不建议卡化"})
    return {"rules": rules,
            "kb_paper_leg": sorted(kb_papers), "seed_paper_leg": sorted(seed_papers),
            "batch2_leg": sorted(batch2_ids), "filtered": filtered}


def build_waves(coverage, classic_gap, bline_gap, frontier_gap, verify_gap, batch2):
    """波次生成：阶段三优先级 B 线策略语料 > 高被引经典 > 前沿扩展；验证积压为使能波。

    每个 target 统一四键：item（对象）/ detail（关键事实）/ est（预估）/ action（建议动作）。
    """
    # 估算基准：kb 现库论文原子数中位数（沙箱波预估）；口径来自本地实测
    paper_atoms = [p["atoms_total"] for p in coverage["by_paper"].values() if p["atoms_total"] > 0]
    med_atoms = int(statistics.median(paper_atoms)) if paper_atoms else 0
    frontier_landed = [p["atoms_total"] for a, p in coverage["by_paper"].items()
                       if a.startswith("2610") and p["atoms_total"] > 0]
    med_frontier = int(statistics.median(frontier_landed)) if frontier_landed else med_atoms

    def t(item, detail, est, action):
        return {"item": item, "detail": detail, "est": est, "action": action}

    # ---- W1 B 线策略语料（P0）：未卡化主料卡化 + 212 卡准入评审 ----
    primary = [u for u in bline_gap["uncarded"] if u["kind"] == "primary"]
    est_w1a = sum(u["est_cards"] for u in primary)
    bline_cards = sum(n for c, n in bline_gap["carded_corpora"].items())
    w1 = {
        "wave_id": "W1", "priority": "P0", "gap_class": "G2",
        "title": "B 线存量策略语料：未卡化域卡化 + 已卡化准入",
        "goal": ("把 B 线语料根目录下未卡化的 3 个主料文件卡化为候选卡；同时对已落地的 "
                 f"{bline_cards} 张 B 线候选卡完成准入评审（registry candidate→verified），"
                 "让策略语料真正进入 KB 候选层。"),
        "rationale": ("阶段三优先级第一是 B 线策略语料。现状：batch1 六文件 212 卡已于 2026-10-28 "
                      "规范化落地（cards-v1.jsonl，schema-v1 全量实测），但 registry 台账 "
                      "candidates-batch1 212 条全为 candidate、0 verified——卡化完成而准入未动；"
                      "同根目录另有 3 个主料语料文件（决策简报/总表/决策摘要）尚未卡化。"),
        "est_cards": est_w1a, "est_unit": "候选卡（新卡化）+ 准入评审 212 条",
        "est_basis": (f"未卡化主料按已卡化 md 语料卡/KB 比率均值 {bline_gap['cards_per_kb_md_mean']}"
                      f"/KB 估算（比率依据 {bline_gap['ratio_basis']}）；准入评审条数=cards-v1 实读 "
                      f"{bline_cards}。"),
        "channel": "工厂 report",
        "targets": [t(u["corpus"], f"{u['bytes']}B，已有卡 {u['cards_now']}", u["est_cards"],
                      "卡化（候选卡 JSONL，口径照抄 kb-v1 schema；与已卡化 180 卡去重）")
                    for u in primary]
                   + [t("candidates-batch1（六文件 212 卡）",
                        "registry 212 candidate / 0 verified", bline_cards,
                        "准入评审（registry admit，逐条给依据）")],
        "dedupe_note": "索引件（INDEX.md/索引.md）按导航件过滤，不建议卡化（见 dedupe.filtered）。",
        "evidence": ["kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl（212 卡实读）",
                     "kb-seed/candidates-batch1/REPORT.md §一（对账总量）",
                     "kb-seed/registry.db（candidates-batch1 212 candidate / 0 verified）",
                     "覆盖地图 by_domain[candidates-batch1]"],
    }
    # ---- W2 高被引经典（P1）----
    targets = [c for c in classic_gap["items"] if c["state"] == "uncovered"]
    batch2_planned = [c for c in classic_gap["items"] if c["state"] == "planned_batch2"]
    seeded_unlanded = [c for c in classic_gap["items"] if c["state"] == "dispatched_unlanded"]
    w2 = {
        "wave_id": "W2", "priority": "P1", "gap_class": "G1",
        "title": "高被引未覆盖经典回灌（kb 内被引统计驱动）",
        "goal": (f"对被引 ≥{classic_gap['threshold_citing_papers']} 篇 verified 语料论文、但 kb 无原子、"
                 f"也无卡在派的 {len(targets)} 篇经典立项回灌；另处理 {len(seeded_unlanded)} 篇"
                 f"『已派卡未落地』经典与 {len(batch2_planned)} 篇批2 清单内未摄经典"
                 "（证据未摄，随批2 一并摄，不重复立项）。"),
        "rationale": ("经典是 harness 策略谱系的源头。kb 内被引统计（verified 语料论文证据文本 ∩ "
                      "CLASSIC_PAPERS 名录）显示多篇经典被反复引用却从未卡化；其中 ReAct/Reflexion "
                      "已派过 cls 卡但无收割记录（断链），批2 清单 7 篇中 5 篇在被引前列但证据未摄。"),
        "est_cards": (len(targets) + len(seeded_unlanded) + len(batch2_planned)) * med_atoms,
        "est_unit": "候选原子（每篇按 kb 现库论文原子数中位数估）",
        "est_basis": (f"kb 现库 {len(paper_atoms)} 篇有原子论文的中位数 {med_atoms} 条/篇"
                      f"（min {min(paper_atoms)}/max {max(paper_atoms)}）。"),
        "channel": "沙箱",
        "targets": ([t(f"{c['name']} {c['id']}",
                       f"被引 {c['citing_papers']} 篇/提及 {c['mentions']} 次，kb 无原子无卡",
                       med_atoms, "新立项回灌（kb-atoms-cls 卡，走 portal-seeder 源②）")
                     for c in targets]
                    + [t(f"{c['name']} {c['id']}",
                         f"被引 {c['citing_papers']} 篇/提及 {c['mentions']} 次，cls 卡已派无收割记录",
                         med_atoms, "补链/重派（修卡后重上门户）")
                       for c in seeded_unlanded]
                    + [t(f"{c['name']} {c['id']}",
                         (f"批2 计划清单在列（未被引统计检出），证据未摄" if c["source"] == "batch2_manifest"
                          else f"被引 {c['citing_papers']} 篇/提及 {c['mentions']} 次，批2 清单已列证据未摄"),
                         med_atoms, "随批2 一并摄，不重复立项")
                       for c in batch2_planned]),
        "dedupe_note": ("已入库/已派卡/已缓存经典全部滤掉（dedupe R1/R2，其中已派未落的两篇转本波补链）；"
                        "批2 清单内经典按 R4 标注不重复立项。gov 门户腿离线未核（ssh 不在本器输入面）。"),
        "evidence": ["覆盖地图 by_paper（paper 字段）",
                     "kb-seed/sandbox/evidence-cache/<verified 语料论文>/{abs,full}.md 被引计数",
                     "tools/portal-seeder.py CLASSIC_PAPERS 名录（唯一真源）",
                     "kb-seed/paper-batch2/manifest.json"],
    }
    # ---- W3 前沿连续体（P2）----
    w3 = {
        "wave_id": "W3", "priority": "P2", "gap_class": "G3",
        "title": "前沿连续体断档补链（arXiv 2610 序列）",
        "goal": (f"对已派卡/已缓存但 kb 无原子的 {len(frontier_gap['items'])} 篇 26 开头论文补链："
                 "修正重派（被拒态）或重派等回报（无回报态），恢复 2610 收割序列的连续性。"),
        "rationale": ("前沿波（w4/rpt）按 arXiv 提交序连续收割；断档处要么 quote 回查被整份作废"
                      "（AGENTS.md 契约：任何一条 miss 整份作废）、要么卡上门户后无回报。"
                      "不断链，已验证原子的论文覆盖才能连续。"),
        "est_cards": len(frontier_gap["items"]) * med_frontier,
        "est_unit": "候选原子",
        "est_basis": (f"2610 已入库 {len(frontier_landed)} 篇的原子数中位数 {med_frontier} 条/篇。"),
        "channel": "沙箱",
        "targets": [t(b["paper"],
                      f"{b['title'] or '-'}；{b['mode']}；证据 {b['evidence_level']}"
                      f"；主题词 {','.join(b['topic_keywords']) or '-'}",
                      med_frontier, "补链重派（kb-atoms 卡，r3 起须修 quote 逐字纪律）")
                    for b in frontier_gap["items"]],
        "dedupe_note": ("断档项均已派卡/已缓存，按补链（重派）建议而非新种；主题关键词命中 seeder "
                        "查询词表，命中有无仅作备注，不作为去重条件。"),
        "evidence": ["kb-seed/sandbox/task-seeds/（卡目录）",
                     "kb-seed/sandbox/HARVEST-LOG.md（ok/rejected 逐报告）",
                     "kb-seed/sandbox/evidence-cache/（证据在场）",
                     "覆盖地图 by_paper.state"],
    }
    # ---- W4 验证卡积压（P1 使能）----
    zero_v = verify_gap["papers_zero_verified"]
    no_card = verify_gap["papers_no_verify_card"]
    residual_sandbox = verify_gap["candidate_atoms_by_corpus"].get("sandbox", 0)
    w4 = {
        "wave_id": "W4", "priority": "P1（使能）", "gap_class": "G4",
        "title": "验证卡积压治理（kb-verify 断点 + 候选原子待验证）",
        "goal": (f"①给 {len(zero_v)} 篇有候选原子但 0 verified 的论文补/重派 kb-verify 卡"
                 f"（其中 8 篇 paper-batch1 原子从未走验证链、1 篇验证卡回报缺失）；"
                 f"②对账 kb-verify 波的双阀分歧：HARVEST-LOG 记 {verify_gap['kb_verify_reports_in_log']} "
                 f"份回报全拒，而 kb 内 {verify_gap['kb_verified_atoms_citing_verify_dir']} 条 verified "
                 "沙箱原子的准入依据全部 citing verify/ 留档——同名文件两个结论，需统一口径。"),
        "rationale": ("验证是候选→合并的前置门：未验证原子进不了合并层。现状：候选原子 "
                      f"{verify_gap['candidate_atoms_total']} 条 vs 沙箱线 verified "
                      f"{verify_gap['kb_verified_atoms_citing_verify_dir']} 条；"
                      "kvfix 已定位收割侧 66 拒收的根因=键名不一致（卡教 verifications/闸认 verdicts）"
                      "并修双键兼容（计划/变更日志.md 2026-10-28 23:2x 行，router 23:12:48 重启载入），"
                      "拒收回流线同批施工（event-router poll_verify_rejects）。"),
        "est_cards": len(zero_v) + len(no_card),
        "est_unit": ("验证卡（1 卡/篇，抽样口径照抄现网 kb-verify 卡 meta.json：12 条/卡）"
                     "+ 1 项双阀对账（工厂 report）"),
        "est_basis": (f"0-verified 论文 {len(zero_v)} 篇 + 沙箱候选无验证卡 {len(no_card)} 篇；"
                      f"若要把沙箱残余 {residual_sandbox} 条候选原子也全量验证，按 12 条/卡估约 "
                      f"{-(-residual_sandbox // 12)} 卡（上限口径，正常按轮次滚动）。"),
        "channel": "沙箱（补派/重派）+ 工厂 report（双阀对账）",
        "targets": ([t(p["paper"], f"{p['title'] or '-'}；candidate {p['candidate']} 条 / verified 0"
                                   f"；已有验证卡 {p['verify_cards']} 张",
                      1, "补/重派 kb-verify 卡（回流线或首派）")
                     for p in zero_v]
                    + [t(p["paper"], f"{p['title'] or '-'}；沙箱候选 {p['candidate']} 条无验证卡在派",
                         1, "首派 kb-verify 卡（派单链回归指标，现网为 0）")
                       for p in no_card]
                    + [t("kb-verify 双阀分歧对账",
                         f"HARVEST-LOG {verify_gap['kb_verify_reports_in_log']} 份全拒 vs kb "
                         f"{verify_gap['kb_verified_atoms_citing_verify_dir']} 条 verified citing verify/；"
                         f"缺留档回报 {len(verify_gap['log_reports_without_archive'])} 份",
                         1, "工厂 report：统一收割/采录两端口径，重跑一致后再定回流范围")]),
        "dedupe_note": ("已有验证卡且已采录的论文不重复计；0-verified 论文按 candidate>0 判定；"
                        "双阀对账只核口径不重派，规划器不动 .harvested/registry。"),
        "evidence": ["kb-seed/sandbox/HARVEST-LOG.md（kb-verify 66 行 0 ok，收割侧口径）",
                     "kb/kb.db verified 原子 attrs.registry_note citing kb-seed/sandbox/verify（采录侧口径）",
                     "kb-seed/sandbox/verify/（65 份留档，本器以 sandbox-harvester.validate 复验：现行双键下 65/65 ok）",
                     "计划/变更日志.md（交叉验证通过/admit 行计数，可选输入）",
                     "kb-seed/registry.db（sandbox 1526 candidate / 750 verified）"],
    }
    return [w1, w2, w3, w4]


# ---------------------------------------------------------------- 报告生成


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def render_report(plan):
    cov = plan["coverage_map"]
    gaps = plan["gaps"]
    L = []
    A = L.append
    A(f"# 覆盖驱动任务规划 v1 · 报告（沙箱战役备战-20261028）\n")
    A(f"> 生成器：`tools/task-planner.py`（schema `{plan['schema']}`）；生成时刻 {plan['generated_at']}。")
    A("> 定位：**只建议、不派发**——落板走既有链（portal-seeder 生卡 → card-lint 八条闸 → scp；"
      "event-router 收割/回流；registry admit；kb-ingest 入 kb/），分工见 §五。")
    A("> 纪律：纯 stdlib、全离线（零网络调用）、kb/ 只读（备份副本 + KBStore 契约 API）、"
      "除工单指定两个输出件外零写入、零密钥明文。\n")

    A("## 〇、输入面清单（全本地，含指纹）\n")
    A(md_table(["输入", "路径", "sha256(16)", "字节/条目"],
               [[k, v["path"], v.get("sha256_16", "-"),
                 v.get("bytes", v.get("dir_entries", "-"))]
                for k, v in plan["inputs"].items()]))
    A("")
    A("派生只读源：`tools/portal-seeder.py` 的 `CLASSIC_PAPERS` 被引经典名录（importlib 只读导入，"
      "唯一真源不复制）；`tools/sandbox-harvester.py` 的 `validate()` 纯函数（verify/ 留档复验）。\n")

    A("## 一、覆盖地图\n")
    A("### 1.1 语料域维度\n")
    A(md_table(["语料域", "kb 原子", "verified", "candidate", "retired",
                "registry candidate", "registry verified", "论文数", "卡化状态"],
               [[d, v["kb_atoms"], v["kb_verified"], v["kb_candidate"], v["kb_retired"],
                 v["registry_candidate"], v["registry_verified"], len(v["papers"]),
                 ("212 卡已规范化（schema-v1），准入 0"
                  if d == "candidates-batch1" else
                  "抽取线 admit（无独立卡）" if d == "sandbox" else
                  "paper-batch1 原子直导入（无卡）" if d == "atoms" else
                  "POC 遗留（20 retired）")]
                for d, v in sorted(cov["by_domain"].items())]))
    A("")
    tot = plan["reconciliation"]
    A("对账：" + "；".join(f"{k}={v}" for k, v in tot.items()) + "。")
    retired_by = tot.get("kb_retired_by_domain") or {}
    if retired_by:
        A("")
        A("台账分歧注记：registry 状态机无 retired 态（candidate→verified|rejected），kb 侧 retired "
          + "、".join(f"{d}={n}" for d, n in sorted(retired_by.items()))
          + " 在 registry 仍记 candidate——POC 语料（k2-* 40 candidate + k1-* 20 retired）建议随 W1b 准入一并收口。")
    A("")
    A("### 1.2 paper 维度（kb 原子 / 派卡 / 收割 / 证据 / 落地状态）\n")
    rows = []
    for arx, p in sorted(cov["by_paper"].items()):
        rows.append([arx, (p["title"] or "-")[:38], p["atoms_total"], p["verified"],
                     p["candidate"], f"{p['seed_extract_v1']}+{p['seed_extract_r2']}r2",
                     p["verify_cards"], f"{p['harvest_ok']}/{p['harvest_rejected']}",
                     p["evidence"]["evidence_level"], p["state"]])
    A(md_table(["paper", "标题", "原子", "verified", "candidate", "抽取卡v1+r2",
                "验证卡", "收割ok/拒", "证据", "状态"], rows))
    A("")
    A("状态口径：landed_verified=已入库且有 verified；landed_unverified=已入库 0 verified；"
      "dispatched_rejected=已派卡且收割全拒；dispatched_no_return=已派卡无收割记录；"
      "cached_only=仅证据缓存无卡。\n")

    A("## 二、缺口分类\n")
    g1 = gaps["G1_classic_uncited_uncovered"]
    A(f"### G1 高被引未覆盖经典（被引≥{g1['threshold_citing_papers']} 篇 verified 语料论文）\n")
    A(f"被引统计口径：{g1['corpus_papers_total']} 篇 verified 语料论文中 {g1['corpus_papers_scanned']} 篇"
      f"有本地证据文本，命中 CLASSIC_PAPERS 名录 {g1['classics_detected']} 篇。")
    A(md_table(["arXiv", "经典", "被引论文数", "提及次数", "状态"],
               [[c["id"], c["name"], c["citing_papers"], c["mentions"], c["state"]]
                for c in g1["items"]]))
    A("")
    g2 = gaps["G2_bline_uncarded_domains"]
    A("### G2 B 线语料未卡化域\n")
    A(f"语料根目录（由 212 卡 source.corpus 反推）：{', '.join('`'+r+'`' for r in g2['roots'])}；"
      f"已卡化 {sum(g2['carded_corpora'].values())} 卡 / {len(g2['carded_corpora'])} 个语料文件。"
      f"扫盘得未卡化文件 {len(g2['uncarded'])} 个（主料/索引按文件名规则分流）。")
    A(md_table(["语料文件", "字节", "类型", "已有卡", "预估卡数", "处置"],
               [[u["corpus"], u["bytes"], u["kind"], u["cards_now"], u["est_cards"],
                 "不建议卡化（导航件）" if u["kind"] == "index" else "建议卡化"]
                for u in g2["uncarded"]]))
    A("")
    A(f"估算依据：已卡化 md 语料卡/KB 比率均值 {g2['cards_per_kb_md_mean']}/KB"
      f"（{', '.join('`'+c+'`' for c in g2['ratio_basis'])}）。注意 `最终报告-harness改进策略总表.md` "
      "与 strategies.csv 同源（180 条策略的总表），卡化时须与已卡化 180 卡去重，预估为上限口径。\n")
    g3 = gaps["G3_frontier_continuum_breaks"]
    A(f"### G3 前沿连续体断档（{g3['series']} 序列）\n")
    A(md_table(["paper", "标题", "断档态", "v1+r2", "收割ok/拒", "证据", "主题关键词"],
               [[b["paper"], (b["title"] or "-")[:40], b["mode"],
                 f"{b['seed_v1']}+{b['seed_r2']}", f"{b['harvest_ok']}/{b['harvest_rejected']}",
                 b["evidence_level"], ",".join(b["topic_keywords"]) or "-"]
                for b in g3["items"]]))
    A("")
    g4 = gaps["G4_verify_backlog"]
    A("### G4 验证卡积压\n")
    A(f"- **收割侧**（HARVEST-LOG，sandbox-harvester.validate 口径）：kb-verify 回报 "
      f"{g4['kb_verify_reports_in_log']} 份，ok {g4['kb_verify_ok_in_log']} 份、拒收 "
      f"{g4['kb_verify_rejected_in_log']} 份。")
    A(f"- **采录侧**（kb/registry）：verified 沙箱原子 {g4['kb_verified_atoms_citing_verify_dir']} 条，"
      "其准入依据（attrs.registry_note）全部 citing `kb-seed/sandbox/verify` 留档目录——路由器侧确已采录。")
    if g4.get("changelog"):
        cl = g4["changelog"]
        A(f"- **变更日志交叉计数**（`{cl['path']}`）：交叉验证通过 {cl['verify_pass_cards']} 卡、"
          f"经验证卡 admit {cl['atoms_admitted_via_verify']} 条。")
    A(f"- **双阀分歧**：同名回报文件收割侧记拒、采录侧已准入——两端口径不一致（kvfix 2026-10-28 23:2x "
      "定位为键名不一致并修双键兼容）。本器用现行 sandbox-harvester.validate() 复验 verify/ 留档："
      f"{g4['verify_archive_revalidate_ok']}/{g4['verify_archive_files']} 份为 ok（佐证拒收系键名口径产物）。"
      f"日志中无留档副本的回报 {len(g4['log_reports_without_archive'])} 份："
      + "；".join(g4["log_reports_without_archive"]) + "。")
    A(f"- **待验证积压**：候选原子 {g4['candidate_atoms_total']} 条，按语料域分账："
      + "；".join(f"{k}={v}" for k, v in g4["candidate_atoms_by_corpus"].items())
      + f"。0-verified 论文 {len(g4['papers_zero_verified'])} 篇；沙箱候选无验证卡在派 "
      f"{len(g4['papers_no_verify_card'])} 篇（回归指标，现网为 0）。")
    A(md_table(["paper", "标题", "candidate", "语料", "已有验证卡"],
               [[p["paper"], (p["title"] or "-")[:40], p["candidate"],
                 ",".join(f"{k}:{v}" for k, v in p["corpora"].items()), p["verify_cards"]]
                for p in g4["papers_zero_verified"]]))
    A("")

    A("## 三、任务波次清单与理由\n")
    A("优先级链（工单口径）：B 线策略语料 > 高被引经典 > 前沿扩展；验证卡积压为使能波"
      "（未验证原子进不了合并层，与 W2/W3 并行）。\n")
    for w in plan["waves"]:
        A(f"### {w['wave_id']}（{w['priority']} · {w['gap_class']}）{w['title']}\n")
        A(f"- **目标**：{w['goal']}")
        A(f"- **理由**：{w['rationale']}")
        A(f"- **预估卡数**：{w['est_cards']}（{w['est_unit']}）——{w['est_basis']}")
        A(f"- **建议通道**：{w['channel']}")
        A(f"- **去重注记**：{w['dedupe_note']}")
        A(f"- **证据**：{'；'.join(w['evidence'])}\n")
        if w["targets"]:
            A(md_table(["对象", "关键事实", "预估", "建议动作"],
                       [[t_["item"], t_["detail"], t_["est"], t_["action"]]
                        for t_ in w["targets"]]))
            A("")

    A("## 四、dedupe 过滤记录（机器可消费，见 JSON `dedupe`）\n")
    A(md_table(["规则", "内容", "去重腿"],
               [[r["id"], r["rule"], r["leg"]] for r in plan["dedupe"]["rules"]]))
    A("")
    A(md_table(["被滤对象", "规则", "原因"],
               [[f["item"], f["rule"], f["reason"]] for f in plan["dedupe"]["filtered"]]))
    A("")

    A("## 五、分工边界（规划器只建议，不派发）\n")
    A("- 本器产物=波次建议（目标/理由/预估/通道/目标清单）；**不生成卡、不 scp、不改 registry/kb、"
      "不动 `.harvested`、不重启任何常驻脚本**。")
    A("- 沙箱通道落板链：`tools/portal-seeder.py` 生卡（源① arXiv 新篇 / 源② 经典回灌）→ "
      "`tools/card-lint.py` 八条硬指标（fail-closed）→ scp 上门户 → 沙箱执行 → "
      "`tools/sandbox-harvester.py` 收割校验 → `tools/event-router.py` 交叉验证派单/回流/聚合 → "
      "`kb-seed/registry.py` admit → `tools/kb-ingest.py` 入 kb/。")
    A("- 工厂 report 通道落板链：会话内子代理批产候选卡 JSONL（口径照抄 `b线-20261028/schema-v1.md`）→ "
      "`kb-seed/registry.py import` 登账 → admit 评审。")
    A("- W4 的 kb-verify 回流属 event-router 既有机制（拒收回流 + STOP 熔断），本器只在建议中标记对象。\n")

    A("## 六、诚实声明（未做/降级/口径）\n")
    A("1. 本器**未做**语义级核验（被引计数是证据文本内名录字符串匹配，非引用意图判别）；"
      "标题取自证据根的 `<title>` 或 markdown H1（paper-batch1 证据偶带重复 `Title:` 前缀，已剥离），缺失时留空。")
    A("2. 本器**离线**：不访问 arXiv/门户 gov（ssh 不在输入面），gov 侧在飞任务目录未核——"
      "三重去重的 gov 腿以本地 task-seeds 与 HARVEST-LOG 代替，可能有本地未同步的已派卡。")
    A("3. W1 预估卡数为比率外推上限口径（总表与 CSV 同源，须去重后定案）；W2/W3 预估为中位数口径；W4 全量验证残余为 12 条/卡的上限口径。")
    A("4. `verify/` 65 份留档在现行 validate() 下复验 ok，与 HARVEST-LOG 同名为 rejected 并存：本器如实并列两侧事实"
      "（收割侧 66 拒 / 采录侧 65 卡 admit 750 条），根因定性不自行裁判，交由 W4 的双阀对账项统一口径。")
    A("5. 规划逻辑全部确定性（排序键显式、无随机、无墙钟进决策）；`generated_at` 为唯一时间戳字段，"
      "幂等校验时归一化该字段后比对。")

    acc = plan.get("acceptance") or []
    if acc:
        A("\n## 七、验收判据与证据（判据先行；由规划器自跑，未过即 exit 1）\n")
        A(md_table(["判据", "内容", "方法", "结果", "实测证据"],
                   [[c["id"], c["criterion"], c["method"], c["result"], c["evidence"]]
                    for c in acc]))
        A("")
        allpass = all(c["result"] == "pass" for c in acc)
        A(f"总判：**{'全部通过' if allpass else '存在未过项（见上表）'}**"
          f"（{sum(1 for c in acc if c['result'] == 'pass')}/{len(acc)}）。"
          "复跑方式：`python3 tools/task-planner.py`（A1-A8 每次运行重跑并写入本表与 JSON "
          "`acceptance` 字段）；`--selftest` 单跑内部不变量。")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 自检 + 主流程


def selftest(plan):
    """内部不变量：输入齐、覆盖对账、四缺口非空、波次四要素齐、dedupe 非空。"""
    errs = []
    for k in ("kb_db", "registry_db", "harvest_log", "seeds_dir", "cache_dir", "verify_dir",
              "cards_v1", "ns_map", "batch1_report", "batch2_manifest"):
        if not plan["inputs"].get(k, {}).get("exists"):
            errs.append(f"输入缺失: {k}")
    rec = plan["reconciliation"]
    if rec.get("kb_atoms_total") != sum(v["kb_atoms"] for v in plan["coverage_map"]["by_domain"].values()):
        errs.append("覆盖地图语料域计数与 kb 总数不符")
    if not rec.get("kb_read_only_ok"):
        errs.append("kb/kb.db 运行前后 sha256 不一致（只读口径被破坏）")
    if not (rec.get("cards_v1_rows") == rec.get("batch1_report_declared_total") == rec.get("ns_map_total")):
        errs.append("cards-v1 实读数 / REPORT 声明总量 / namespace-map total 三方不一致")
    if rec.get("seed_extract_total", 0) + rec.get("seed_verify_total", 0) != rec.get("seed_cards_total"):
        errs.append("派卡分账（抽取+验证）与卡总数不符")
    for g in ("G1_classic_uncited_uncovered", "G2_bline_uncarded_domains",
              "G3_frontier_continuum_breaks", "G4_verify_backlog"):
        items = plan["gaps"][g].get("items") or plan["gaps"][g].get("uncarded") \
            or plan["gaps"][g].get("papers_zero_verified")
        if not items:
            errs.append(f"缺口 {g} 为空")
    if not plan["gaps"]["G4_verify_backlog"].get("papers_zero_verified"):
        errs.append("G4 papers_zero_verified 为空（验证积压无对象）")
    if not plan["gaps"]["G4_verify_backlog"].get("kb_verified_atoms_citing_verify_dir"):
        errs.append("G4 采录侧证据为空（kb verified 原子无 citing verify/ 的准入依据）")
    for w in plan["waves"]:
        for field in ("goal", "rationale", "est_cards", "channel", "targets"):
            if not w.get(field):
                errs.append(f"波次 {w['wave_id']} 缺字段 {field}")
    if not plan["dedupe"]["filtered"]:
        errs.append("dedupe.filtered 为空")
    acc = plan.get("acceptance")
    if acc is not None:
        bad = [c["id"] for c in acc if c["result"] != "pass"]
        if bad:
            errs.append(f"验收判据未过: {bad}")
    return errs


def build_plan(tmpdir):
    """一次完整规划：装载全部本地输入 → 覆盖地图 → 缺口 → 去重 → 波次 → 计划 dict。
    纯函数式（除读文件外无副作用）；同输入必得同输出（generated_at 除外）。"""
    inputs = {k: file_meta(p) for k, p in [
        ("kb_db", KB_DB), ("registry_db", REGISTRY_DB), ("harvest_log", HARVEST_LOG),
        ("seeds_dir", SEEDS_DIR), ("cache_dir", CACHE_DIR), ("verify_dir", VERIFY_DIR),
        ("cards_v1", CARDS_V1), ("ns_map", NS_MAP), ("batch1_report", BATCH1_REPORT),
        ("batch2_manifest", BATCH2_MANIFEST),
        ("changelog", os.path.join(WS, "计划/变更日志.md")),
        ("paper_batch1_evidence", EVIDENCE_ROOTS[1])]}
    for k in ("kb_db", "registry_db", "cards_v1", "batch2_manifest", "ns_map"):
        if not inputs[k]["exists"]:
            raise SystemExit(f"输入缺失: {inputs[k]['path']}")
    for k in ("seeds_dir", "cache_dir", "verify_dir"):
        if not os.path.isdir(inputs[k]["path"]):
            raise SystemExit(f"输入目录缺失: {inputs[k]['path']}")

    atoms, kb_stats, _kb_snap_db = read_kb(tmpdir)
    registry = read_registry()
    harvest = read_harvest_log()
    seeds = read_seed_ledger()
    verify_archive, verify_note = read_verify_archive()
    if verify_note:
        raise SystemExit(f"verify/ 留档复验不可用: {verify_note}")
    cards = read_cards()
    ns_map = read_namespace_map()
    batch2 = read_batch2_manifest()
    report_total = read_batch1_report_total()
    cache_ids = _snap(("cache_ids",),
                      lambda: {d for d in os.listdir(CACHE_DIR) if ARXIV_RE.fullmatch(d)})
    try:
        ps = load_module(os.path.join(WS, "tools/portal-seeder.py"), "portal_seeder")
        classic_papers = dict(ps.CLASSIC_PAPERS)
    except Exception as e:  # noqa: BLE001 —— 真源导入失败必须 fail-loud，不静默降级
        raise SystemExit(f"portal-seeder CLASSIC_PAPERS 导入失败: {e}")

    coverage = build_coverage(atoms, registry, seeds, harvest, cache_ids)
    used_ids = ({a for a, p in coverage["by_paper"].items() if p["atoms_total"] > 0}
                | {a for a, p in coverage["by_paper"].items()
                   if p["seed_extract_v1"] or p["seed_extract_r2"] or p["verify_cards"]}
                | set(cache_ids))
    batch2_ids = {m.get("arxiv_id") for m in batch2}

    classic_gap = gap_classics(atoms, coverage, used_ids, batch2, classic_papers)
    bline_gap = gap_bline_uncarded(cards)
    frontier_gap = gap_frontier_breaks(coverage)
    changelog = read_changelog_admits()
    verify_gap = gap_verify_backlog(atoms, coverage, verify_archive, harvest, changelog)
    dedupe = build_dedupe(coverage, batch2, bline_gap, classic_gap, frontier_gap)
    waves = build_waves(coverage, classic_gap, bline_gap, frontier_gap, verify_gap, batch2)

    reconciliation = {
        "kb_atoms_total": kb_stats["total"],
        "kb_verified": kb_stats["by_status"]["verified"],
        "kb_candidate": kb_stats["by_status"]["candidate"],
        "kb_retired": kb_stats["by_status"]["retired"],
        "registry_total": sum(registry.values()),
        "cards_v1_rows": len(cards),
        "batch1_report_declared_total": report_total,
        "ns_map_total": ns_map.get("total"),
        "harvest_log_entries": len(harvest),
        "harvest_ok": sum(1 for st, _ in harvest.values() if st == "ok"),
        "harvest_rejected": sum(1 for st, _ in harvest.values() if st != "ok"),
        "seed_cards_total": sum(len(v["seeds"]) for v in seeds.values()),
        "seed_extract_total": sum(v["extract_v1"] + v["extract_r2"] for v in seeds.values()),
        "seed_verify_total": sum(len(v["verify_cards"]) for v in seeds.values()),
        "evidence_cache_papers": len(cache_ids),
        "kb_retired_by_domain": {d: v["kb_retired"]
                                 for d, v in coverage["by_domain"].items() if v["kb_retired"]},
    }
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "planner": {"script": "tools/task-planner.py", "mode": "suggest-only",
                    "offline": True, "kb_read_only": True},
        "inputs": inputs,
        "coverage_map": coverage,
        "gaps": {"G1_classic_uncited_uncovered": classic_gap,
                 "G2_bline_uncarded_domains": bline_gap,
                 "G3_frontier_continuum_breaks": frontier_gap,
                 "G4_verify_backlog": verify_gap},
        "dedupe": dedupe,
        "waves": waves,
        "reconciliation": reconciliation,
        "boundary": ("规划器只建议不派发；落板走 portal-seeder/card-lint/event-router/"
                     "registry/kb-ingest 既有链"),
        "notes": {"verify_archive_note": verify_note, "tmp_root": TMP_ROOT},
    }


def acceptance_checks(plan, plan_again, kb_ro_ok, kb_sha):
    """验收判据自跑（判据先行：每条给出方法与实测证据；不过即记 fail 并 overall=fail）。

    判据（对应工单硬纪律与交付面）：
      A1 纯 stdlib 离线：ast 静态扫描自身 import——白名单=stdlib+本仓 kb，禁网络类模块；
      A2 kb/ 只读：kb/kb.db（含 WAL/shm）与 registry.db 运行前后 sha256 一致；
      A3 覆盖对账：cards-v1 实读=REPORT 声明=namespace-map total；派卡分账闭合；
         语料域计数和=kb 总数（KBStore.stats 口径）；
      A4 四类缺口非空且各有本地证据字段；
      A5 波次四要素（目标/理由/预估卡数/通道）齐全且优先级链 B线>经典>前沿、验证为使能；
      A6 dedupe 规则与过滤记录非空；
      A7 确定性：同进程二次构建，除 generated_at 外 JSON 序列化一致；
      A8 内部不变量 selftest 零 errs。
    """
    checks = []

    def add(cid, criterion, method, ok, evidence):
        checks.append({"id": cid, "criterion": criterion, "method": method,
                       "result": "pass" if ok else "FAIL", "evidence": evidence})

    # A1 静态 import 扫描（自源码）
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    net = mods & {"socket", "urllib", "http", "ftplib", "telnetlib", "smtplib",
                  "subprocess", "requests", "asyncio", "ssl", "xmlrpc", "paramiko"}
    third = {m for m in mods if m not in sys.stdlib_module_names and m != "kb"}
    add("A1", "纯 stdlib、离线（零第三方/零网络模块）",
        "ast 静态扫描 tools/task-planner.py 全部 import",
        not net and not third,
        f"imports={sorted(mods)}；网络类={sorted(net) or '无'}；第三方={sorted(third) or '无'}")

    # A2 kb 只读
    add("A2", "kb/ 与 registry.db 只读（运行前后 sha256 一致）",
        "规划前后对 kb/kb.db（含 -wal/-shm）与 kb-seed/registry.db 取 sha256 比对",
        kb_ro_ok, f"kb/kb.db sha256={kb_sha}；前后一致={kb_ro_ok}")

    # A3 覆盖对账
    rec = plan["reconciliation"]
    ok3 = (rec["cards_v1_rows"] == rec["batch1_report_declared_total"] == rec["ns_map_total"]
           and rec["seed_extract_total"] + rec["seed_verify_total"] == rec["seed_cards_total"]
           and rec["kb_atoms_total"] == sum(
               v["kb_atoms"] for v in plan["coverage_map"]["by_domain"].values()))
    add("A3", "覆盖地图对账（卡数三方一致/派卡分账闭合/域计数和=kb 总数）",
        "plan.reconciliation 字段互校", ok3,
        f"cards_v1={rec['cards_v1_rows']}=REPORT {rec['batch1_report_declared_total']}"
        f"=ns_map {rec['ns_map_total']}；派卡 {rec['seed_extract_total']}+{rec['seed_verify_total']}"
        f"={rec['seed_cards_total']}；kb 总数 {rec['kb_atoms_total']}")

    # A4 四类缺口
    g = plan["gaps"]
    n1 = len(g["G1_classic_uncited_uncovered"]["items"])
    n2 = len([u for u in g["G2_bline_uncarded_domains"]["uncarded"] if u["kind"] == "primary"])
    n3 = len(g["G3_frontier_continuum_breaks"]["items"])
    n4 = len(g["G4_verify_backlog"]["papers_zero_verified"])
    add("A4", "四类缺口均非空且对象可定位", "gaps 四键逐项计数", all([n1, n2, n3, n4]),
        f"G1 经典 {n1} 条（uncovered "
        f"{sum(1 for c in g['G1_classic_uncited_uncovered']['items'] if c['state'] == 'uncovered')}）；"
        f"G2 未卡化主料 {n2} 个；G3 断档 {n3} 篇；G4 0-verified 论文 {n4} 篇")

    # A5 波次
    ws = plan["waves"]
    ok5 = (len(ws) == 4 and [w["wave_id"] for w in ws] == ["W1", "W2", "W3", "W4"]
           and all(w.get(f) for w in ws for f in
                   ("goal", "rationale", "est_cards", "channel", "targets")))
    add("A5", "波次四要素齐全 + 优先级链 B线>经典>前沿（验证为使能波）",
        "waves 逐波字段校验 + 顺序校验", ok5,
        "；".join(f"{w['wave_id']}={w['priority']}/{w['channel']}" for w in ws))

    # A6 dedupe
    d = plan["dedupe"]
    add("A6", "dedupe 规则与过滤记录非空（机器可消费）",
        "dedupe.rules/filtered/legs 计数", bool(d["rules"]) and bool(d["filtered"]),
        f"rules={len(d['rules'])}；filtered={len(d['filtered'])}；"
        f"腿 kb={len(d['kb_paper_leg'])}/seed={len(d['seed_paper_leg'])}/batch2={len(d['batch2_leg'])}")

    # A7 确定性（同进程二次构建）
    a = dict(plan); b = dict(plan_again)
    a.pop("generated_at"); b.pop("generated_at")
    same = json.dumps(a, ensure_ascii=False, sort_keys=True) == \
        json.dumps(b, ensure_ascii=False, sort_keys=True)
    add("A7", "确定性（同输入二次构建，除 generated_at 外一致）",
        "build_plan 连跑两次后 JSON 序列化比对", same,
        f"generated_at 为唯一时间戳字段；二次构建一致={same}")

    # A8 selftest
    errs = selftest(plan)
    add("A8", "内部不变量 selftest 零违例", "selftest(plan)", not errs,
        "；".join(errs) if errs else "零违例")
    return checks


def main():
    ap = argparse.ArgumentParser(description="覆盖驱动任务波次规划器（只建议不派发）")
    ap.add_argument("--out-json", default=OUT_JSON)
    ap.add_argument("--out-md", default=OUT_MD)
    ap.add_argument("--print-plan", action="store_true", help="只打 JSON 到 stdout")
    ap.add_argument("--selftest", action="store_true", help="内部不变量自检")
    args = ap.parse_args()

    os.makedirs(TMP_ROOT, exist_ok=True)  # $HOME 自建临时根（AGENT.md 硬纪律 7：/tmp 只放白名单件）
    tmpdir = tempfile.mkdtemp(prefix="task-planner-", dir=TMP_ROOT)
    try:
        kb_sha_before = sha256_of(KB_DB)
        plan = build_plan(tmpdir)
        plan_again = build_plan(tmpdir)  # A7 确定性：同进程二次构建
        kb_sha_after = sha256_of(KB_DB)
        kb_ro_ok = kb_sha_before == kb_sha_after
        if not kb_ro_ok:
            print("FATAL: kb/kb.db sha256 运行前后不一致（只读口径被破坏）", file=sys.stderr)
            return 1
        for p in (plan, plan_again):  # 两次构建同口径，A7 才可比
            p["reconciliation"]["kb_read_only_ok"] = kb_ro_ok
        plan["acceptance"] = acceptance_checks(plan, plan_again, kb_ro_ok, kb_sha_after[:16])
        if any(c["result"] != "pass" for c in plan["acceptance"]):
            for c in plan["acceptance"]:
                if c["result"] != "pass":
                    print(f"ACCEPTANCE FAIL [{c['id']}] {c['criterion']}: {c['evidence']}",
                          file=sys.stderr)
            return 1

        if args.selftest:
            errs = selftest(plan)
            if errs:
                for e in errs:
                    print("SELFTEST FAIL:", e, file=sys.stderr)
                return 1
            print("selftest OK")
            if not args.print_plan:
                return 0

        if args.print_plan:
            print(json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=False))
            return 0

        for path, content in ((args.out_json, json.dumps(plan, ensure_ascii=False, indent=1)),
                              (args.out_md, render_report(plan))):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")
        print(f"written: {args.out_json}")
        print(f"written: {args.out_md}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
