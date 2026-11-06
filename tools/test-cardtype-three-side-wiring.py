#!/usr/bin/env python3
"""test-cardtype-three-side-wiring.py — 卡型三侧（收割分支/消费面/拒收回流正则）同批接线清单门
（RT-E80 拦截机制④施工件，2026-11-02）

背景（RT-E80 + 确证发现「收割侧整类拒收面未修复」）：kb-arbitrate/kb-distill 两类回报
2026-11-02 07:26 前整类落收割方 atoms 分支被拒（HARVEST-LOG 实存 55 行全 rejected
「payload.atoms 缺失或为空」、新格式文案 0 行）；修复批（pre-KBARB）补了收割分支与
路由器消费线，但①收割分支在生产零真实命中（55 行全是旧码拒收，分域校验落下后无任一
真实 arb/distill 回报再过收割方）；②拒收回流正则只认 kb-atoms/kb-verify 前缀，两类卡的
拒收行零处置（蒸发面）；③55 行旧式拒收与路由器消费线（.router-state arb_reports=54）
并存却无任何「已由消费线接手」的对账桥（读日志者只见 55 条死拒收）。本门把 RT-E80
拦截机制④自承待施工的「卡型三侧同批接线清单」落成常驻确定性检查——产侧新增卡型时，
收/用/回流三侧缺一即红，不再靠事后红队。

检查项：
  W1 卡型域登记完备：HARVEST-LOG 全量报表行的卡名前缀 ⊆ 本门接线清单——
     新卡型出现而三侧未接线时，本项先红点名（产侧新增卡型、收/用两侧无人接的 tripwire）。
  W2 收割分支（每域行为探针 + 生产真回报全量回放）：
     · 空 payload → 本域专属拒收文案（各 schema 一行），绝不落「payload.atoms 缺失或为空」
       整类拒收（kb-atoms 域除外——抽取线 fallback 按设计保留）；
     · 合法最小 payload → ok 且 stats 带本域统计键（verdicts/rulings/findings/atoms）；
     · kb-seed/sandbox/arbitrate/ 的真实仲裁/蒸馏回报（54 件生产原件）全量回放
       validate()：0 件命中 atoms 整类拒收、stats 全带本域键——收割分支对真实形态
       真的执行（RT-E80 对账「分支在生产零命中」的常驻反证）。
  W3 消费面：消费线在册且接线——poll_verify_reports / poll_arbitrate_reports 定义、
     主循环调用、分域前缀判据在码；生产 state arb_reports 非空（消费线真跑过）。
  W4 回流面：三域回流正则/处理器在册且接线——kb-atoms（poll_harvest r2 正则）、
     kb-verify（VERIFY_REJECT_RE+poll_verify_rejects）、kb-arbitrate/kb-distill
     （ARB_REJECT_RE+poll_arb_rejects，2026-11-02 新增回流腿）；行为探针：未消费拒收行
     →registered+变更日志点名、已消费/已留档 →resolved-by-router（状态内回填标记，
     对账桥）、防重放、kb-verify 行不得误认领；三条域回流正则对同一行恰一条命中（互斥）。
  W5 对账腿（回填标记 + 零终裁可测）：HARVEST-LOG 的 kb-arbitrate/kb-distill 拒收行
     逐一解析 → 每行必须有主，且分得清「已解决」与「零终裁」：
       · resolved_by_router = 终裁**确已落库**（arbitrate/ 顶层留档=落库依据，且载荷
         过收割方 validate 校验）；
       · no_verdict_registered = 终裁未落库但已显式登记（零终裁台账 / 回流腿
         no-verdict-registered）——有主但不是已解决；
       · registered/pending = 未被消费、登记待运营者。
     未决行 >0 即红——「拒收=终裁蒸发」从此有门可测。
     2026-11-03 RT 修复（零终裁蒸发面）：旧口径把「已消费」（state arb_reports）
     直接当已解决 ⇒ 终裁无从落库的零终裁回报（收割方整份拒收「payload.rulings 缺失
     或为空」）也被记 resolved-by-router，门 108/108 全绿而门自称的目的测不出。
     现「已解决」须有终裁落库凭据；零终裁必须显式登记（台账 + 点名受影响原子 +
     证据副本），未登记即红；另设两条反假绿断言（登记须有台账凭据／零终裁行不得被
     计入 resolved_by_router）。
  W6 重派账腿（零终裁登记必须有消费面；2026-11-03 RT·「只登记不重派」滞留面）：
     W5 判「有主（待重派）」的零终裁登记若**永不重派**则结构性恒绿（实测 55 登记/
     64 原子滞留：重发被发卡幂等腿 divergence_key「已承载」遮蔽、无台账/无告警，唯一
     消费面恰是把「有主」记绿的 W5）。本腿对零终裁台账逐条对账「重派动作在发生」：
       · entry.reissue 字段 ∈ {reissued:<卡>, exhausted, pending}——路由器消费腿
         （event-router arb_reissue_accounting）在跑的凭据，缺字段=消费腿未接线 → 红；
       · exhausted（同分歧零终裁卡 ≥ 重发帽）必须在 状态观测/alarms.log 有
         ARB-REISSUE-STUCK 行且文案点到该分歧 → 红（耗尽必告警=运营者可见）；
       · pending 超 REISSUE_DEADLINE_S（与路由器 24h 同值）仍无重派动作且无
         ARB-REISSUE-STUCK 点名 → 红（「登记后石沉大海」从此有门）。

用法：python3 tools/test-cardtype-three-side-wiring.py
退出码：0 全过；1 断言失败；2 前置不满足。
只读生产面（HARVEST-LOG / .router-state.json / arbitrate/ 留档 / 源码），写面仅 $HOME
下自建 scratch（完工即删）。零网络、零密钥、不重启在役进程。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
TOOLS = os.path.join(WS, "tools")
HARVESTER = os.path.join(TOOLS, "sandbox-harvester.py")
ROUTER = os.path.join(TOOLS, "event-router.py")
CARDS = os.path.join(TOOLS, "quality-cards.py")
LOG = os.path.join(WS, "kb-seed/sandbox/HARVEST-LOG.md")
STATE = os.path.join(WS, "kb-seed/sandbox/.router-state.json")
ARB_ARCHIVE = os.path.join(WS, "kb-seed/sandbox/arbitrate")
ARB_SEEDS = os.path.join(WS, "kb-seed/sandbox/task-seeds")   # 发卡名册（名册原子清单核对）
ALARMS_LOG = os.path.join(WS, "状态观测", "alarms.log")       # W6：重派滞留告警流水（JSONL）
REISSUE_DEADLINE_S = 24 * 3600   # W6：pending 超时线（与 event-router ARB_REISSUE_DEADLINE_S 同值）

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


# ---- 接线清单（单一真源）：每卡型域一行，三侧判据显式在列 ----
# 新增卡型 = 在此加一行 + 三侧判据随之补齐；HARVEST-LOG 出现清单外前缀即 W1 红。
WIRING = (
    {"domain": "extract", "prefix": "kb-atoms", "stats_key": "atoms",
     "label": "抽取线（atoms fallback 分支按设计保留）"},
    {"domain": "verify", "prefix": "kb-verify", "stats_key": "verdicts",
     "label": "kb-verify 验证卡"},
    {"domain": "arbitrate", "prefix": "kb-arbitrate", "stats_key": "rulings",
     "label": "kb-arbitrate 仲裁终裁卡"},
    {"domain": "distill", "prefix": "kb-distill", "stats_key": "findings",
     "label": "kb-distill 蒸馏复核卡"},
)
PREFIXES = tuple(w["prefix"] for w in WIRING)

LOG_ROW_RE = re.compile(r"^\|\s*(?P<card>[A-Za-z0-9._\-]+?\.json)\s*\|"
                        r"\s*(?P<verdict>ok|rejected)\s*\|")


def log_rows():
    """HARVEST-LOG 的报表行 → [(card, verdict, line)]；解析不出报表名的行忽略（表头等）。"""
    out = []
    for line in open(LOG, encoding="utf-8").read().splitlines():
        m = LOG_ROW_RE.match(line)
        if m:
            out.append((m.group("card"), m.group("verdict"), line))
    return out


# ---- W1 卡型域登记完备 ----

def w1_domain_roster(rows):
    pref_re = re.compile(r"^(kb-[a-z]+)")
    unknown = {}
    for card, _, _ in rows:
        m = pref_re.match(card)
        p = m.group(1) if m else card.split("-")[0]
        if p not in PREFIXES:
            unknown.setdefault(p, []).append(card)
    check(not unknown,
          "HARVEST-LOG 出现接线清单外的卡型前缀（产侧新增卡型、三侧接线清单未登记——"
          "请补 tools/test-cardtype-three-side-wiring.py 的 WIRING 与三侧判据）：%r"
          % {k: v[:3] for k, v in unknown.items()})
    per = {w["prefix"]: sum(1 for c, _, _ in rows if c.startswith(w["prefix"]))
           for w in WIRING}
    for pfx, n in per.items():
        check(n > 0, "接线清单域 %s 在活日志 0 行（域可能已消亡，请复核清单）" % pfx)
    return {"domains": per, "unregistered": 0}


# ---- W2 收割分支 ----

def w2_harvest_branch(hv):
    res = {}
    # 每域空 payload 探针：拒收文案必须本域专属
    probes = {
        "kb-atoms": ("payload.atoms 缺失或为空", None),
        "kb-verify": (hv.KBVERIFY_SCHEMA_LINE, None),
        "kb-arbitrate": (hv.ARBITRATE_SCHEMA_LINE, None),
        "kb-distill": (hv.DISTILL_SCHEMA_LINE, None),
    }
    for pfx, (want, _) in probes.items():
        v, why, st = hv.validate({"task_id": pfx + "-probe-1", "payload": {}}, None)
        check(v == "rejected", "%s 空 payload 应拒收，实得 %r" % (pfx, v))
        check(want in why, "%s 空 payload 拒收文案不是本域专属：%r" % (pfx, why))
        if pfx != "kb-atoms":
            check("payload.atoms 缺失或为空" not in why,
                  "%s 回落 atoms 整类拒收（断链复发）：%r" % (pfx, why))
    # 合法最小 payload 探针：ok + 本域统计键
    good = {
        "kb-atoms": ({"atoms": [{"atom_id": "a1", "kind": "claim", "text": "t",
                                 "source": {"quote": "q"}}]}, {"abs.md": "q"}),
        "kb-verify": ({"verdicts": [{"atom_id": "a1", "verdict": "uphold",
                                     "quote_check": True, "reason": "探针"}]}, None),
        "kb-arbitrate": ({"rulings": [{"atom_id": "a1", "final": "uphold",
                                       "quote_check": True, "rationale": "探针",
                                       "agree_with": "b1"}]}, None),
        "kb-distill": ({"findings": [
            {"atom_id": "W", "role": "winner", "final": "no_loss",
             "rationale": "探针", "lost_items": []},
            {"atom_id": "L", "role": "loser", "final": "info_loss",
             "rationale": "探针", "lost_items": []}]}, None),
    }
    for pfx, (pay, ev) in good.items():
        v, why, st = hv.validate({"task_id": pfx + "-probe-1", "payload": pay}, ev)
        check(v == "ok", "%s 合法最小 payload 应 ok，实得 %r/%r" % (pfx, v, why))
        key = {w["prefix"]: w["stats_key"] for w in WIRING}[pfx]
        check(st.get(key, 0) >= 1, "%s ok stats 缺本域统计键 %s：%r" % (pfx, key, st))
    res["empty_payload_probes"] = "domain-specific"
    res["valid_payload_probes"] = "ok+domain-stats"

    # 生产真回报全量回放（RT-E80「分支在生产零命中」的常驻反证）
    if not os.path.isdir(ARB_ARCHIVE):
        raise Fail("前置不满足：真实回报留档目录缺失 %s" % ARB_ARCHIVE)
    files = sorted(f for f in os.listdir(ARB_ARCHIVE) if f.endswith(".json"))
    if not files:
        raise Fail("前置不满足：真实回报留档为空 %s" % ARB_ARCHIVE)
    replay = {"total": len(files), "ok": 0, "rejected": 0, "atoms_branch": []}
    for n in files:
        rep = json.load(open(os.path.join(ARB_ARCHIVE, n), encoding="utf-8"))
        v, why, st = hv.validate(rep, None)
        if "payload.atoms 缺失或为空" in why:
            replay["atoms_branch"].append(n)
        if v == "ok":
            replay["ok"] += 1
        else:
            replay["rejected"] += 1
    check(not replay["atoms_branch"],
          "真实仲裁/蒸馏回报 %d 件落 atoms 整类拒收（收割分支断链复发）：%r"
          % (len(replay["atoms_branch"]), replay["atoms_branch"][:5]))
    res["real_report_replay"] = replay
    return res


# ---- W3 消费面 ----

def w3_consumer_side(rsrc, st):
    for fn in ("poll_verify_reports", "poll_arbitrate_reports", "poll_harvest"):
        check(("def %s(" % fn) in rsrc, "router 消费线 %s 不见了" % fn)
        check(re.search(r"^\s+%s\(st\)" % fn, rsrc, re.M) is not None,
              "router 主循环未调用消费线 %s" % fn)
    check('tid.startswith("kb-arbitrate")' in rsrc and 'tid.startswith("kb-distill")' in rsrc,
          "poll_arbitrate_reports 分域前缀判据缺失（kb-arbitrate/kb-distill）")
    check('startswith("kb-verify-")' in rsrc,
          "poll_verify_reports 分域前缀判据缺失（kb-verify）")
    n = len(st.get("arb_reports") or [])
    check(n > 0, "生产 state arb_reports 为空——消费线从未真跑（前置/在役面异常）")
    return {"consumers_wired": ["poll_harvest", "poll_verify_reports",
                                "poll_arbitrate_reports"],
            "arb_reports_consumed": n}


# ---- W4 回流面 ----

def w4_reflux_side(rsrc, rt):
    # 结构锚：三域回流正则/处理器在册且被 poll_harvest 接线
    check("VERIFY_REJECT_RE = re.compile" in rsrc, "kb-verify 回流正则不见了")
    check("def poll_verify_rejects(" in rsrc, "poll_verify_rejects 不见了")
    check("poll_verify_rejects(st, lines)" in rsrc, "poll_verify_rejects 未被 poll_harvest 接线")
    check("ARB_REJECT_RE = re.compile" in rsrc, "kb-arbitrate/kb-distill 回流正则不见了")
    check("def poll_arb_rejects(" in rsrc, "poll_arb_rejects 不见了")
    check("poll_arb_rejects(st, lines)" in rsrc, "poll_arb_rejects 未被 poll_harvest 接线")
    pats = re.findall(r're\.search\(r"([^"]*kb-atoms-\[a-z0-9\]\+[^"]*)"', rsrc)
    check(len(pats) == 1, "poll_harvest 的 kb-atoms r2 回流正则应恰一处，实得 %d" % len(pats))
    r2_re = re.compile(pats[0])

    # 行为探针（scratch，零生产写）：认领语义 + 防重放 + 跨域不误认领
    d = tempfile.mkdtemp(prefix="cardtype-wiring-scratch.", dir=os.path.expanduser("~"))
    try:
        rt.CHANGELOG = os.path.join(d, "ch.md")
        rt.STOP = os.path.join(d, "no-stop")
        rt.ARB_DIR = os.path.join(d, "arb")
        rt.DRY = False  # 只对 scratch CHANGELOG 落笔（探针要断言变更日志点名语义）
        os.makedirs(rt.ARB_DIR)
        # 留档在册的那份必须是**含真终裁**的载荷（留档=落库依据；写 "{}" 的空壳不
        # 构成终裁凭据——「已解决」的判据是终裁确已落库，不是文件在不在）
        json.dump({"task_id": "kb-arbitrate-archived-1-1793270000000",
                   "payload": {"rulings": [{"atom_id": "sbx-probe-1", "final": "uphold",
                                            "quote_check": True, "rationale": "探针",
                                            "agree_with": "b1"}]}},
                  open(os.path.join(rt.ARB_DIR, "kb-arbitrate-archived-1-1793270000000.json"),
                       "w"), ensure_ascii=False)
        open(rt.CHANGELOG, "w").close()
        # 零终裁取证走 gov（网络）——本门零网络：取证腿打桩（分类/登记语义不受取证影响）
        real_fetch = rt.arb_zero_verdict_evidence
        rt.arb_zero_verdict_evidence = lambda st, names, batch=60: {}
        lines = [
            # 未消费：终裁未入账 → 登记待运营者
            ("| kb-arbitrate-fresh-1-1793270000001.json | rejected | "
             "kb-arbitrate payload.rulings 缺失或为空；合法格式 | - |", "registered"),
            ("| kb-distill-fresh-2-1793270000002.json | rejected | "
             "kb-distill payload.findings 缺失或为空；合法格式 | - |", "registered"),
            # 已消费但**无终裁留档凭据**（零终裁）：改判 no-verdict-registered（有主但
            # 不是已解决）——旧口径一律记 resolved-by-router，零终裁整批蒸发而门全绿
            ("| kb-arbitrate-consumed-3-1793270000003.json | rejected | "
             "payload.atoms 缺失或为空 | - |", "no-verdict-registered"),
            # 留档在册且含真终裁：resolved-by-router，且不刷变更日志
            ("| kb-arbitrate-archived-1-1793270000000.json | rejected | "
             "payload.atoms 缺失或为空 | - |", "resolved-by-router"),
        ]
        st = {"arb_reports": ["kb-arbitrate-consumed-3-1793270000003.json"]}
        rt.poll_arb_rejects(st, [l for l, _ in lines])
        rj = st["arb_rejects"]
        check(rj["kb-arbitrate-fresh-1-1793270000001"]["status"] == "registered"
              and rj["kb-distill-fresh-2-1793270000002"]["status"] == "registered",
              "未消费的 arb/distill 拒收行未被登记（蒸发面复发）：%r" % rj)
        check(rj["kb-arbitrate-archived-1-1793270000000"]["status"] == "resolved-by-router",
              "已留档（含真终裁）拒收行未记 resolved-by-router（对账桥缺失）：%r" % rj)
        check(rj["kb-arbitrate-consumed-3-1793270000003"]["status"] == "no-verdict-registered",
              "已消费但无终裁留档凭据的拒收行未改判 no-verdict-registered"
              "（零终裁被误判成已解决——终裁蒸发面复发）：%r" % rj)
        nov = st.get("arb_zero_verdict") or {}
        check("kb-arbitrate-consumed-3-1793270000003.json" in nov
              and nov["kb-arbitrate-consumed-3-1793270000003.json"]["status"]
              == "no-verdict-registered",
              "零终裁未落台账（无凭据的「已解决」判据复发）：%r" % nov)
        ch = open(rt.CHANGELOG, encoding="utf-8").read()
        check(ch.count("拒收登记") == 2 and "archived-1" not in ch,
              "已解决拒收行误刷变更日志（历史积压上线即刷屏的形态）：%r" % ch)
        check("consumed-3" in ch and "零终裁登记" in ch,
              "零终裁行未点名登记（终裁蒸发面复发——终裁没落库却无痕）：%r" % ch)
        n0, c0 = len(rj), ch.count("拒收登记")
        rt.poll_arb_rejects(st, [l for l, _ in lines])
        check(len(rj) == n0 and ch.count("拒收登记") == c0, "防重放失效（重复登记）")
        # kb-verify 行不得被 arb 回流误认领（域互斥的处理器侧）
        st2 = {"arb_reports": []}
        rt.poll_arb_rejects(st2, ["| kb-verify-x-1r1-1793213510031.json | rejected | x | - |"])
        check(not st2["arb_rejects"], "kb-verify 拒收行被 arb 回流误认领：%r" % st2["arb_rejects"])
        # 零终裁取证（本地 raw/ 路径，零网络）：证据副本落 no-verdict/ 且台账回填 evidence
        rt.arb_zero_verdict_evidence = real_fetch
        rawd = os.path.join(d, "raw")
        os.makedirs(rawd)
        zv = "kb-arbitrate-zv-1-1793270000000.json"
        json.dump({"task_id": zv[:-5], "payload": {"atoms": []}},
                  open(os.path.join(rawd, zv), "w"), ensure_ascii=False)
        rt.RAW_DIR = rawd
        st3 = {"arb_reports": [zv]}
        rt.register_arb_zero_verdict(st3, zv, "探针：零终裁（无 rulings）")
        rt.arb_zero_verdict_evidence(st3, [zv])
        check(os.path.isfile(os.path.join(rt.ARB_DIR, "no-verdict", zv)),
              "零终裁取证副本未落 arbitrate/no-verdict/（终裁未落库却无证）：%r" % os.listdir(
                  os.path.join(rt.ARB_DIR, "no-verdict"))
              if os.path.isdir(os.path.join(rt.ARB_DIR, "no-verdict")) else "no-verdict 目录缺失")
        check((st3.get("arb_zero_verdict") or {}).get(zv, {}).get("evidence", "").endswith(zv),
              "零终裁台账未回填证据路径：%r" % st3.get("arb_zero_verdict"))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # 三条域回流正则互斥：合成行（四域 × 老/新格式）逐行恰一条命中且落在本域
    synth = [
        ("| kb-atoms-cls-2303.11366-1793259867351.json | rejected | quote 回查 miss=1/1 | - |",
         "extract"),  # r2 域
        ("| kb-verify-kb-atoms-cls-2303.11366-r2-1r1-1793213510031.json | rejected | "
         "kb-verify payload.verdicts 缺失或为空 | - |", "verify"),
        ("| kb-arbitrate-kb-atoms-acr-2404.05427-1-1793269062184.json | rejected | "
         "payload.atoms 缺失或为空 | - |", "arbitrate"),
        ("| kb-arbitrate-kb-atoms-acr-2404.05427-1-1793269062184.json | rejected | "
         "kb-arbitrate payload.rulings 缺失或为空；合法格式 | - |", "arbitrate"),
        ("| kb-distill-S001-k1-S001-1793248176918.json | rejected | "
         "payload.atoms 缺失或为空 | - |", "distill"),
    ]
    domain_of = {"extract": r2_re, "verify": rt.VERIFY_REJECT_RE,
                 "arbitrate": rt.ARB_REJECT_RE, "distill": rt.ARB_REJECT_RE}
    for line, dom in synth:
        hits = [name for name, rx in (("extract", r2_re), ("verify", rt.VERIFY_REJECT_RE),
                                      ("arb/distill", rt.ARB_REJECT_RE))
                if rx.search(line)]
        check(len(hits) == 1, "拒收行回流正则命中数≠1（应恰落一域）：%r → %r" % (line[:80], hits))
        check(hits[0] == ("arb/distill" if dom in ("arbitrate", "distill") else dom),
              "拒收行落错回流域（应 %s 实得 %r）：%r" % (dom, hits, line[:80]))
        check(domain_of[dom].search(line) is not None, "本域正则未命中本域合成行：%r" % line[:80])
    return {"reflux_wired": ["kb-atoms:r2", "kb-verify:VERIFY_REJECT_RE",
                             "kb-arbitrate/kb-distill:ARB_REJECT_RE"],
            "arb_claim_semantics": "registered|resolved-by-router",
            "regex_exclusivity": "1-hit-per-row"}


# ---- W5 对账腿（回填标记 + 零终裁可测）----

def _arb_card_id_of(name):
    """回报文件名 → 卡 id（去 .json 后缀与 13 位时间尾戳；=发卡名册目录名）。"""
    base = name[:-5] if name.endswith(".json") else name
    return re.sub(r"-\d{13}$", "", base)


def w5_reconciliation(rows, st, hv):
    """W5 对账腿：仲裁/蒸馏拒收行逐行判「有主」，且分得清「已解决」与「零终裁」。

    2026-11-03 RT 修复（零终裁蒸发面）：旧口径把「文件名 ∈ arb_reports（已消费）」
    直接当已解决——于是**终裁无从落库**的零终裁回报（收割方整份拒收「payload.rulings
    缺失或为空」）也被记 resolved-by-router，门 108/108 全绿，而门自称的目的
    「拒收=终裁蒸发 从此有门可测」测不出（实测 55 份零终裁回报 / 64 个原子受影响，
    零留档零登记）。现判据分三层：
      · resolved_by_router = 终裁**确已落库**（ARB_DIR 顶层留档=落库依据，且载荷过
        收割方 validate 校验）——真正的已解决；
      · no_verdict_registered = 终裁未落库但已显式登记（零终裁台账 / 回流腿
        no-verdict-registered）——有主（待运营者重派）但**不是**已解决；
      · registered/pending/dedup-skipped = 未被消费/重复回报，登记待运营者；
      · 无主 → 红（终裁蒸发面复发）。
    另加两条反假绿断言：①零终裁登记必须有台账凭据（status 与原子清单）；②零终裁
    行不得被计入 resolved_by_router。"""
    consumed = set(st.get("arb_reports") or [])
    try:
        consumed |= {f for f in os.listdir(ARB_ARCHIVE) if f.endswith(".json")}
    except OSError:
        pass
    nov = st.get("arb_zero_verdict") or {}
    dedup = set(st.get("arb_dedup_skipped") or [])
    rejects = st.get("arb_rejects") or {}
    registered = {c for c, v in rejects.items()
                  if isinstance(v, dict) and v.get("status") in
                  ("registered", "pending", "no-verdict-registered", "dedup-skipped")}

    def verdict_archived(name):
        """ARB_DIR 顶层留档存在且载荷过收割方 validate（=终裁确已落库的凭据）。"""
        p = os.path.join(ARB_ARCHIVE, name)
        if not os.path.isfile(p):
            return False
        try:
            rep = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 读不到=无凭据
            return False
        v, _, _ = hv.validate(rep, None)
        return v == "ok"

    def stem(n):
        return n[:-5] if n.endswith(".json") else n

    unresolved, by_router, zero_verdict, reg_pending = [], 0, 0, 0
    for card, verdict, _ in rows:
        if verdict != "rejected":
            continue
        if not (card.startswith("kb-arbitrate") or card.startswith("kb-distill")):
            continue
        nm = card + ".json"
        if nm in nov or card in nov:
            zero_verdict += 1
            continue
        if nm in dedup or card in dedup:
            reg_pending += 1
            continue
        if verdict_archived(nm) or verdict_archived(card):
            by_router += 1
            continue
        if card in consumed or stem(card) in {stem(c) for c in consumed}:
            # 消费过但**无终裁留档凭据**、也未零终裁登记 → 终裁蒸发面（红）
            unresolved.append(card + "（已消费但无终裁留档凭据、未零终裁登记）")
            continue
        if card in registered or stem(card) in {stem(c) for c in registered}:
            reg_pending += 1
            continue
        unresolved.append(card)
    check(not unresolved,
          "仲裁/蒸馏拒收行 %d 行无主（既无终裁落库凭据、也未被回流腿登记）——"
          "终裁蒸发面复发：%r" % (len(unresolved), unresolved[:5]))

    # 反假绿①：零终裁登记必须有台账凭据（status + 受影响原子清单）
    bad_nov = []
    for c, v in rejects.items():
        if isinstance(v, dict) and v.get("status") == "no-verdict-registered" \
                and (c + ".json") not in nov:
            bad_nov.append(c + "（回流腿记了零终裁但零终裁台账无凭据）")
    for name, e in nov.items():
        if not isinstance(e, dict):
            bad_nov.append(name)
            continue
        if e.get("status") != "no-verdict-registered":
            bad_nov.append(name + "（status=%r）" % e.get("status"))
            continue
        cid = e.get("card") or _arb_card_id_of(name)
        meta_p = os.path.join(ARB_SEEDS, cid, "meta.json")
        if os.path.isfile(meta_p):
            # 卡在发卡名册 → 登记必须点名受影响原子（名册唯一来源=meta.arbitrate.atom_ids）
            ids = ((json.load(open(meta_p, encoding="utf-8")).get("arbitrate") or {})
                   .get("atom_ids") or [])
            if ids and not (set(e.get("atoms") or []) & set(ids)):
                bad_nov.append(name + "（登记未点名名册原子 %d 个）" % len(ids))
    check(not bad_nov,
          "零终裁台账 %d 条缺凭据（status 非 no-verdict-registered / 未点名受影响原子）"
          "——「零终裁有主」不可核：%r" % (len(bad_nov), bad_nov[:5]))

    # 反假绿②：零终裁行不得被回流腿记成 resolved-by-router（终裁没落库≠已解决）
    misjudged = [c for c, v in rejects.items()
                 if isinstance(v, dict) and v.get("status") == "resolved-by-router"
                 and (c + ".json") in nov]
    check(not misjudged,
          "零终裁回报被回流腿记成 resolved-by-router（终裁没落库却判已解决——"
          "旧口径误判复发）：%r" % misjudged[:5])

    total = sum(1 for c, v, _ in rows if v == "rejected" and
                (c.startswith("kb-arbitrate") or c.startswith("kb-distill")))
    return {"arb_reject_rows_total": total,
            "resolved_by_router": by_router,
            "no_verdict_registered": zero_verdict,
            "registered_pending": reg_pending,
            "unresolved": 0}


# ---- W6 重派账腿（零终裁登记必须有消费面：重派/耗尽/告警，不许只登记）----

def _zv_div_key_of(card):
    """零终裁卡 → 分歧记账键（与 event-router._zv_div_key_of 同算法同回退：
    「d:<divergence_key>」/种子已撤回退「f:<卡号族前缀>」）。"""
    try:
        arb = (json.load(open(os.path.join(ARB_SEEDS, card, "meta.json"),
                             encoding="utf-8")).get("arbitrate") or {})
        if arb.get("divergence_key"):
            return "d:" + arb["divergence_key"]
    except Exception:  # noqa: BLE001 - 种子不在册照回退
        pass
    m = re.match(r"^(kb-arbitrate-.+)-\d+$", card or "")
    return "f:" + (m.group(1) if m else (card or "?"))


def w6_reissue_ledger(st):
    """W6 重派账腿：零终裁台账逐条对账「重派动作在发生」，登记不许是终点。

    旧形态（确证发现亲证）：55 份零终裁登记后无任何消费面——重发被发卡幂等腿遮蔽、
    唯一消费面恰是把「有主」记绿的 W5 对账门、无门红/无台账/无告警 → 64 原子仲裁链
    永久滞留。本腿判据（对账对象=路由器消费腿 arb_reissue_accounting 的产出）：
      · entry.reissue 字段必须在（缺=消费腿未接线/未跑 → 红）；
      · exhausted（同分歧零终裁卡 ≥ 重发帽）/超时 pending 必须在 alarms.log 有
        ARB-REISSUE-STUCK 行且文案点到该分歧（dk 前 60 字或卡号）→ 红；
      · reissued:<卡> / 有告警点名的 exhausted / 24h 内 pending = 有主且在推进，绿。"""
    nov = st.get("arb_zero_verdict") or {}
    try:
        alarms = [json.loads(l) for l in open(ALARMS_LOG, encoding="utf-8") if l.strip()]
    except Exception:  # noqa: BLE001 - 告警流水读不到=按零告警对账
        alarms = []
    stuck = [a for a in alarms if isinstance(a, dict) and a.get("code") == "ARB-REISSUE-STUCK"]

    def alarm_hit(card, dk):
        return any(card in (a.get("message") or "") or dk[:60] in (a.get("message") or "")
                   for a in stuck)

    no_ledger, no_alarm, stale = [], [], []
    now = time.time()
    for name, e in nov.items():
        if not isinstance(e, dict):
            continue
        re = e.get("reissue")
        card = e.get("card") or ""
        dk = _zv_div_key_of(card)
        if not re:
            no_ledger.append(f"{name}（无 reissue 重派账字段=消费腿未接线）")
            continue
        if re == "pending":
            try:
                age = now - time.mktime(time.strptime(e.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
            except Exception:  # noqa: BLE001 - ts 坏按 0（不误报超时）
                age = 0
            if age > REISSUE_DEADLINE_S and not alarm_hit(card, dk):
                stale.append(f"{name}（登记超 {REISSUE_DEADLINE_S // 3600}h 仍 pending，"
                             f"无重派动作且 alarms.log 无点名）")
            continue
        if re == "exhausted" and not alarm_hit(card, dk):
            no_alarm.append(f"{name}（重发预算耗尽但 alarms.log 无 ARB-REISSUE-STUCK 点名）")
    check(not no_ledger,
          "零终裁登记 %d 条无重派账字段（event-router arb_reissue_accounting 消费腿"
          "未接线/未跑——「只登记不重派」滞留面复发）：%r"
          % (len(no_ledger), no_ledger[:5]))
    check(not stale,
          "零终裁登记 %d 条 pending 超时且无告警点名（登记后石沉大海——重发预算未耗尽"
          "但重发线未动）：%r" % (len(stale), stale[:5]))
    check(not no_alarm,
          "零终裁重发预算耗尽 %d 条无 ARB-REISSUE-STUCK 告警点名（转运营者面失明）：%r"
          % (len(no_alarm), no_alarm[:5]))
    def _cnt(pred):
        return sum(1 for e in nov.values() if isinstance(e, dict) and pred(e.get("reissue")))
    return {"zero_verdict_total": len(nov),
            "reissued": _cnt(lambda r: isinstance(r, str) and r.startswith("reissued")),
            "exhausted": _cnt(lambda r: r == "exhausted"),
            "pending": _cnt(lambda r: r == "pending"),
            "reissue_alarms": len(stuck)}


def main(argv=None):
    for p in (HARVESTER, ROUTER, CARDS, LOG, STATE):
        if not os.path.isfile(p):
            print("前置不满足：缺 %s" % p)
            return EXIT_ENV
    os.environ.pop("ROUTER_DRY", None)  # W4 探针要断言变更日志点名语义（CHANGELOG 已指 scratch）
    hv = load_mod("wiring_harvester", HARVESTER)
    rt = load_mod("wiring_router", ROUTER)
    rsrc = open(ROUTER, encoding="utf-8").read()
    st = json.load(open(STATE, encoding="utf-8"))
    rows = log_rows()
    check(len(rows) > 100, "HARVEST-LOG 报表行 %d 行异常地少（日志面大变？）" % len(rows))

    results, failures = {}, []
    cases = (
        ("W1 卡型域登记完备（清单外前缀=红）", lambda: w1_domain_roster(rows)),
        ("W2 收割分支：分域行为探针 + 生产真回报全量回放（0 件落 atoms 整类拒收）",
         lambda: w2_harvest_branch(hv)),
        ("W3 消费面：消费线在册接线 + 生产 state 非空", lambda: w3_consumer_side(rsrc, st)),
        ("W4 回流面：三域正则/处理器接线 + arb/distill 认领行为 + 三正则互斥",
         lambda: w4_reflux_side(rsrc, rt)),
        ("W5 对账腿：仲裁/蒸馏拒收行 100% 有主（终裁落库凭据/零终裁登记/未消费登记）",
         lambda: w5_reconciliation(rows, st, hv)),
        ("W6 重派账腿：零终裁登记 100% 有重派动作（reissued/exhausted+告警/24h 内 pending）",
         lambda: w6_reissue_ledger(st)),
    )
    for name, fn in cases:
        try:
            results[name] = fn()
            print("  [PASS] %s -> %s" % (name, json.dumps(results[name], ensure_ascii=False)))
        except Fail as e:
            failures.append(name)
            print("  [FAIL] %s -> %s" % (name, e))
        except Exception as e:  # noqa: BLE001
            failures.append(name)
            print("  [FAIL] %s: %s: %s" % (name, type(e).__name__, e))

    if failures:
        print("CARDTYPE-THREE-SIDE-WIRING FAILED: %d 项未过 -> %s" % (len(failures), failures))
        return EXIT_FAIL
    print("CARDTYPE-THREE-SIDE-WIRING PASSED: %d 项" % len(results))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
