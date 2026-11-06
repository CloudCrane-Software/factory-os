#!/usr/bin/env python3
"""sandbox-harvester.py — af-jobs 沙箱回报收割校验器（轨道 K / V2 收口件，P3 补丁台账 P3-5）

流程：ssh gov 只读拉取 /opt/company/af-jobs/data/reports/*.json
  → 三级校验（结构 / quote 逐字回查（缺证据则抓 arXiv 缓存）/ 去重）
  → 合格转候选层 kb-seed/sandbox/<task_id>-<ts>.jsonl（schema 对齐 K2 k2-atoms.jsonl）
  → 流水 kb-seed/sandbox/HARVEST-LOG.md；已收割去重 .harvested
CLI：harvest [--dry-run] | verify <report.json>
纪律：gov 严格只读；arXiv 每任务至多抓 2 次（abs+html）。回滚：删 kb-seed/sandbox/。
"""
import json, os, subprocess, sys, time, hashlib, re, urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
# OTel MVP 埋点（2026-10-28）：工厂链路收割面关键事件 → OTLP（tools/otel/factory_otel）。
# 端点缺省（2026-11-02 起 AF_OTEL_ENDPOINT 未设落缺省 collector，此前=静默丢弃）；
# fail-open 绝不抛回主职；
# 熔断文件 状态观测/OTEL-STOP 在场即静默；.harvested 去重幂等语义不变。
sys.path.insert(0, os.path.join(WS, "tools", "otel"))
try:
    import factory_otel as _otel
except Exception as _e:  # noqa: BLE001 —— 埋点缺失不影响收割主职，但不再无声降级
    _otel = None
    print(f"[otel] factory_otel 加载失败，埋点整线停用（不影响收割主职）: "
          f"{type(_e).__name__}: {_e}", file=sys.stderr)
# 2026-11-02 RT 批修（OTel 链第三发射面项）：此前两处埋点调用 `except Exception: pass`
# 静默吞掉调用面异常（otel_emit 内部失败自记 stats，这里兜的是签名漂移/属性错型等），
# 发射面坏了无人知晓。fail-open 语义不变——绝不抛回收割主职；但不再无声：
# 进程内计数 _otel_emit_errors + stderr 逐条，harvest 汇总行/verify JSON 带记账。
_otel_emit_errors = 0
# 2026-11-02 RT 修复（收割面·发射失败可见性）：此前 _otel_safe 兜住了**调用面异常**，
# 但 harvest_report 的 ok 返回值被丢弃——发射**真失败**（collector 不可达 → otel_emit
# errors 计数涨）既不计数也不出声，调用方更看不到（stderr 逐条记账还被 event-router 的
# `2>&1 | tail -1` 整段吃掉）。现两条失败路径都记账+逐条 stderr：
#   · 调用异常 → _otel_emit_errors（既有计数，语义不变）
#   · 发射失败 → _otel_emit_failures（新增；真失败，errors 计数增量口径）
# 熔断（OTEL-STOP）/禁用（AF_OTEL_DISABLE=1）是有意静默，不计失败、不出声。
_otel_emit_failures = 0


def _otel_safe(**kw):
    """factory_otel.harvest_report 的 fail-open 包装：失败记账+stderr，绝不抛回。"""
    global _otel_emit_errors, _otel_emit_failures
    if _otel is None:
        return
    before = _otel_stats() or {}
    ok = False
    try:
        ok = bool(_otel.harvest_report(**kw))
    except Exception as e:  # noqa: BLE001 —— 埋点异常不影响收割主职，但记账可见
        _otel_emit_errors += 1
        print(f"[otel] harvest 埋点发射异常（已记账，不影响主职）: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return
    after = _otel_stats() or {}
    derr = int(after.get("errors", 0)) - int(before.get("errors", 0))
    if derr:
        # 真失败（collector 不可达等）：ok=False 且 errors 计数涨——逐条记账+stderr。
        _otel_emit_failures += derr
        print(f"[otel] harvest 埋点发射失败 {derr} 次（ok={ok}，已记账，不影响主职）: "
              f"task_id={kw.get('task_id')} verdict={kw.get('verdict')}", file=sys.stderr)


def _otel_stats():
    """进程内发射记账（None-safe）：spans/metrics/errors/skipped_stop。
    harvest 汇总与 verify JSON 带出——collector 不可达这类发射失败至少在输出可见。"""
    try:
        return _otel.otel_emit.stats() if _otel is not None else None
    except Exception:  # noqa: BLE001
        return None
OUT = os.path.join(WS, "kb-seed/sandbox")
CACHE = os.path.join(OUT, "evidence-cache")
DONE = os.path.join(OUT, ".harvested")
LOG = os.path.join(OUT, "HARVEST-LOG.md")
GOV = "root@gov-host.invalid"
REMOTE_DIR = "/opt/company/af-jobs/data/reports"
KINDS = {"claim", "concept", "procedure", "evidence_record", "failure_pattern", "evaluator"}
# AGENTS 契约硬条款：source.quote ≤120 字（2026-11-02 RT 起在收割面强制；门户服务端门
# af-jobs-portal.QUOTE_MAX_CHARS 同源同值，两处单一语义不得漂移）。
QUOTE_MAX_CHARS = 120
# 卡号尾允许 -r<数字> 重派后缀链（event-router 拒收/交叉验证未过自动重派生成
# `kb-atoms-<tag>-<arx>-r2/-r3`，再重派即深链 `-r2-r3/-r2-r3-r3`，HARVEST-LOG 实存
# 41 行；口径同 test-kvfix-verdicts-contract.py 的 KA_ID_RE `(?:-r\d+)*`）。
# 2026-10-31 RT 批修：此前正则锚定行尾，重派卡号匹配失败 → fetch_arxiv 空 →
# 主循环传 None → quote 逐字回查整份跳过（编造引文放行）。
# 2026-11-01 RT-E31 二次收口：即便仍传 None（证据全空），validate 也 fail-closed
# 拒收——回查未执行的报告不再有 ok 出口（主循环 `ev if any(ev.values()) else None`
# 形态保留，只影响拒收文案区分「未执行」与「miss」）。
ARXIV_RE = re.compile(r"kb-atoms-.+?-(\d{4}\.\d{4,5})(?:-r\d+)*$")
# kb-verify 回报的两个同义键名：卡模板（cross-verify.py）与路由器（event-router.py）历史上
# 用过 verifications，harvester 早先用 verdicts。执行方两种都可能写，故两个都认（向后兼容）。
VERIFY_LIST_KEYS = ("verdicts", "verifications")
# 拒收文案附的一行合法 schema 示例——HARVEST-LOG.md 会原样留存，重派卡若引回这段，
# 执行方下轮天然看到正确格式。刻意压成一行且不带 evidence 块（那是抽取线字段）：
# 全形契约（含 evidence/sections_missing）在卡 problem.md 的「完整合法回报 JSON 示例」里。
KBVERIFY_SCHEMA_LINE = ('合法格式：{"verify":true,"card_id":"<卡id>","verdicts":'
                        '[{"atom_id":"<atom_id>","verdict":"uphold|refute|unverifiable",'
                        '"quote_check":true,"reason":"≤80字：证据位置与依据"}]}'
                        '（verdicts 亦可写 verifications，二选一）')
# kb-arbitrate 仲裁卡回报的一行合法 schema 示例（2026-11-02 kb-arbitrate 回报链断裂修复：
# 此前仲裁/蒸馏两类回报落进 atoms 分支整类拒收「payload.atoms 缺失或为空」——HARVEST-LOG
# 实存 55 行全 rejected、终裁无人读，被判 refute 的原子 registry/kb 双库仍 verified）。
# 五字段口径=quality-cards.py build_arbitrate_md 的字段表（atom_id/final/quote_check/
# rationale/agree_with），卡 problem.md 自检清单同源。
ARBITRATE_SCHEMA_LINE = ('合法格式：{"arbitrate":true,"card_id":"<卡id>","rulings":'
                         '[{"atom_id":"<上表atom_id>","final":"uphold|refute|unverifiable",'
                         '"quote_check":true,"rationale":"≤120字：证据位置与依据",'
                         '"agree_with":"b1|b2|neither"}]}')
# kb-distill 蒸馏复核卡的一行合法 schema 示例（口径=build_distill_md 字段表；winner/loser
# 各一条是卡自检清单的硬条款，收割方照它收）。
DISTILL_SCHEMA_LINE = ('合法格式：{"distill_review":true,"card_id":"<卡id>","findings":'
                       '[{"atom_id":"<META块winner或loser>","role":"winner|loser",'
                       '"final":"no_loss|info_loss|wrong_winner|unverifiable",'
                       '"rationale":"≤200字","lost_items":[]}]}'
                       '（winner 与 loser 各一条，共 2 条）')


def verify_list(pay):
    """kb-verify 回报的裁决清单：verdicts 优先，缺失时退回同义键 verifications。"""
    for k in VERIFY_LIST_KEYS:
        v = pay.get(k)
        if isinstance(v, list) and v:
            return v
    return None


def gov_reports():
    r = subprocess.run(["ssh", GOV, f"ls {REMOTE_DIR}/*.json 2>/dev/null"],
                       capture_output=True, text=True, timeout=30)
    return [l.strip() for l in r.stdout.splitlines() if l.strip().endswith(".json")]


def gov_cat(path):
    r = subprocess.run(["ssh", GOV, f"cat {path}"], capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


def fetch_arxiv(task_id):
    m = ARXIV_RE.search(task_id)
    if not m:
        return {}
    aid = m.group(1)
    d = os.path.join(CACHE, aid)
    os.makedirs(d, exist_ok=True)
    out = {}
    for name, url in [("abs.md", f"https://arxiv.org/abs/{aid}"),
                      ("full.md", f"https://arxiv.org/html/{aid}")]:
        p = os.path.join(d, name)
        if os.path.exists(p):
            out[name] = open(p, encoding="utf-8", errors="replace").read()
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "af-jobs-harvester/0.1"})
            txt = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            open(p, "w").write(txt)
            out[name] = txt
        except Exception:
            out[name] = ""
    return out


def validate(rep, ev_texts=None):
    """返回 (verdict, reason, stats)。verdict: ok | rejected"""
    tid = rep.get("task_id", "?")
    pay = rep.get("payload") or {}
    # kb-verify 验证卡回报：结构是裁决清单而非原子集，不走 quote 回查（路由器聚合线消费）。
    # 卡 id 口径 kb-verify-<base>-<attempt>[r<replica>]（2026-10-29 验证放大：同 atom 集
    # k 张独立复核副本）；前缀判定不变，stats/文案里带回完整卡号（含副本号）便于对账。
    if tid.startswith("kb-verify"):
        vs = verify_list(pay)
        if vs is None:
            return ("rejected", "kb-verify payload.verdicts 缺失或为空；" + KBVERIFY_SCHEMA_LINE,
                    {"verdicts": 0, "card": tid})
        okc = 0
        for v in vs:
            # 2026-10-29 崩溃修复：沙箱偶发把 verdicts 元素写成数组/标量——按结构缺件拒收，
            # 不得让单条坏回报崩掉整条收割线（收割循环对全部新回报生效）。
            if not isinstance(v, dict):
                return ("rejected",
                        f"verdicts 含非对象项（{type(v).__name__}）；" + KBVERIFY_SCHEMA_LINE,
                        {"verdicts": len(vs), "card": tid})
            if v.get("atom_id") and v.get("verdict") in ("uphold", "refute", "unverifiable") \
               and isinstance(v.get("quote_check"), bool):
                okc += 1
        if okc != len(vs):
            return ("rejected",
                    f"verdicts 结构缺件 {len(vs)-okc}/{len(vs)}；" + KBVERIFY_SCHEMA_LINE,
                    {"verdicts": len(vs), "card": tid})
        up = sum(1 for v in vs if v["verdict"] == "uphold")
        return ("ok", f"验证回报结构合格（卡 {tid}；uphold {up}/{len(vs)}；聚合裁决由路由器做）",
                {"verdicts": len(vs), "uphold": up, "card": tid})
    # kb-arbitrate 仲裁卡回报（2026-11-02 kb-arbitrate 回报链断裂修复）：结构是终裁清单
    # payload.rulings 而非原子集，不走 quote 回查（消费面=事件路由器仲裁消费线，
    # refute 判死原子由路由器落 registry/kb 双库）。字段口径=quality-cards.py
    # build_arbitrate_md 的字段表与自检清单（五字段缺一即拒）。
    if tid.startswith("kb-arbitrate"):
        rs = pay.get("rulings")
        if not isinstance(rs, list) or not rs:
            return ("rejected", "kb-arbitrate payload.rulings 缺失或为空；" + ARBITRATE_SCHEMA_LINE,
                    {"rulings": 0, "card": tid})
        okc = 0
        for r in rs:
            # 同 kb-verify 分支：单条坏项按结构缺件整份拒收，不让坏回报崩掉收割线
            if not isinstance(r, dict):
                return ("rejected",
                        f"rulings 含非对象项（{type(r).__name__}）；" + ARBITRATE_SCHEMA_LINE,
                        {"rulings": len(rs), "card": tid})
            if (isinstance(r.get("atom_id"), str) and r["atom_id"].strip()
                    and r.get("final") in ("uphold", "refute", "unverifiable")
                    and isinstance(r.get("quote_check"), bool)
                    and isinstance(r.get("rationale"), str) and r["rationale"].strip()
                    and r.get("agree_with") in ("b1", "b2", "neither")):
                okc += 1
        if okc != len(rs):
            return ("rejected",
                    f"rulings 结构缺件 {len(rs)-okc}/{len(rs)}；" + ARBITRATE_SCHEMA_LINE,
                    {"rulings": len(rs), "card": tid})
        fin = {"final_" + k: sum(1 for r in rs if r["final"] == k)
               for k in ("uphold", "refute", "unverifiable")}
        return ("ok", f"仲裁终裁结构合格（卡 {tid}；rulings {len(rs)}；终裁由路由器落双库）",
                {"rulings": len(rs), **fin, "card": tid})
    # kb-distill 蒸馏复核卡回报（同批修复）：结构是复核结论 payload.findings（winner/loser
    # 各一条=卡自检清单硬条款），聚合比例由路由器登记为合并蒸馏规则回归信号，不改原子状态。
    if tid.startswith("kb-distill"):
        fs = pay.get("findings")
        if not isinstance(fs, list) or not fs:
            return ("rejected", "kb-distill payload.findings 缺失或为空；" + DISTILL_SCHEMA_LINE,
                    {"findings": 0, "card": tid})
        okc = 0
        roles = set()
        for f in fs:
            if not isinstance(f, dict):
                return ("rejected",
                        f"findings 含非对象项（{type(f).__name__}）；" + DISTILL_SCHEMA_LINE,
                        {"findings": len(fs), "card": tid})
            if (isinstance(f.get("atom_id"), str) and f["atom_id"].strip()
                    and f.get("role") in ("winner", "loser")
                    and f.get("final") in ("no_loss", "info_loss", "wrong_winner", "unverifiable")
                    and isinstance(f.get("rationale"), str) and f["rationale"].strip()
                    and isinstance(f.get("lost_items"), list)
                    and all(isinstance(x, str) for x in f["lost_items"])):
                okc += 1
                roles.add(f["role"])
        if okc != len(fs):
            return ("rejected",
                    f"findings 结构缺件 {len(fs)-okc}/{len(fs)}；" + DISTILL_SCHEMA_LINE,
                    {"findings": len(fs), "card": tid})
        if roles != {"winner", "loser"}:
            return ("rejected",
                    f"findings 缺 {'loser' if 'winner' in roles else 'winner'} 角色（winner/loser 各一条）；"
                    + DISTILL_SCHEMA_LINE,
                    {"findings": len(fs), "card": tid})
        fin = {"final_" + k: sum(1 for f in fs if f["final"] == k)
               for k in ("no_loss", "info_loss", "wrong_winner", "unverifiable")}
        return ("ok", f"蒸馏复核结构合格（卡 {tid}；findings {len(fs)}；聚合回归信号由路由器登记）",
                {"findings": len(fs), **fin, "card": tid})
    atoms = pay.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        return "rejected", "payload.atoms 缺失或为空", {"atoms": 0}
    bad = []
    seen_quote = {}
    for a in atoms:
        aid = a.get("atom_id"); q = ((a.get("source") or {}).get("quote") or "").strip()
        if not aid or a.get("kind") not in KINDS or not (a.get("text") or "").strip():
            bad.append(f"{aid}:结构缺件"); continue
        if not q:
            bad.append(f"{aid}:quote 空"); continue
        # ≤120 字上限（2026-11-02 红队 RT：AGENTS 契约硬条款「每条产出原子带
        # source.quote（≤120 字）」此前 portal/收割方全链无一处执行——实测 5000 字
        # 逐字 quote 判 ok 入库。门户已加同款服务端门（af-jobs-portal
        # _report_admission_error，QUOTE_MAX_CHARS 同源 120）；此处是收割面同口径
        # 收口，超限按结构缺件整份拒收（fail-closed，与 quote 空/miss 同待遇）。
        if len(q) > QUOTE_MAX_CHARS:
            bad.append(f"{aid}:quote {len(q)}字>{QUOTE_MAX_CHARS}上限（AGENTS 契约硬纪律）"); continue
        h = hashlib.sha256(q.encode()).hexdigest()[:12]
        seen_quote[h] = seen_quote.get(h, 0) + 1
    if ev_texts is None:
        # 2026-11-01 RT-E31 fail-closed 收口：无证据文本=quote 逐字回查未执行，绝不放行。
        # 旧码此处仅置标记便落到函数尾 return "ok"（fail-open：编造引文随 ok 入库，
        # HARVEST-LOG 实存 819 份 ok+hit=None；逃逸台账 E31）。标记键原样保留，
        # 供对账门 grep（该标记只许与 rejected 并存，见 test-kvfix-verdicts-contract T12）。
        return ("rejected",
                "quote 回查未执行（无证据文本）——无证据不裁决，整份作废",
                {"atoms": len(atoms), "bad": len(bad), "回查": "未执行（无证据文本）"})
    ok = miss = 0
    for a in atoms:
        q = ((a.get("source") or {}).get("quote") or "").strip()
        if not q:
            continue
        if any(q in t for t in ev_texts.values() if t):
            ok += 1
        else:
            miss += 1
    hits = {"quote_hit": ok, "quote_miss": miss}
    if bad:
        return "rejected", ";".join(bad[:5]), {"atoms": len(atoms), "bad": len(bad), **hits}
    if isinstance(hits.get("quote_miss"), int) and hits["quote_miss"] > 0:
        return "rejected", f"quote 回查 miss={hits['quote_miss']}/{hits.get('quote_hit',0)+hits['quote_miss']}（AGENTS.md 契约：任何一条 miss 整份作废）", {"atoms": len(atoms), **hits}
    return "ok", "", {"atoms": len(atoms), **hits}


def to_candidates(rep):
    tid = rep.get("task_id", "unknown")
    sbx = rep.get("sandbox") or "unknown"
    now = time.strftime("%Y%m%d-%H%M%S")
    rows = []
    for n, a in enumerate((rep.get("payload") or {}).get("atoms", []), 1):
        rows.append({
            "candidate_id": f"sbx-{tid}-{n}",
            "kind": a.get("kind"), "text": a.get("text"), "body": a.get("body") or {},
            "source": dict(a.get("source") or {}, task=tid, sandbox=sbx),
            "relations": a.get("relations") or [],
            "extractor": {"sandbox": sbx, "channel": "af-jobs", "schema_ver": "kb-poc-v0"},
            "status": "candidate", "harvested_at": now,
        })
    fp = os.path.join(OUT, f"{tid}-{now}.jsonl")
    with open(fp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return fp, len(rows)


def log_line(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def harvested():
    try:
        return set(open(DONE).read().split())
    except Exception:
        return set()


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "harvest"
    dry = "--dry-run" in sys.argv
    done = harvested()
    if cmd == "verify":
        rep = json.load(open(sys.argv[2]))
        ev = fetch_arxiv(rep.get("task_id", ""))
        v, why, st = validate(rep, ev)
        # OTel MVP 埋点：收割面单报告校验（verify 手动单件路径，与 harvest 循环同口径）
        _otel_safe(task_id=rep.get("task_id", "unknown"), verdict=v,
                   atoms=st.get("atoms", st.get("verdicts", 0)),
                   quote_hit=st.get("quote_hit"), quote_miss=st.get("quote_miss"),
                   mode="verify", service="sandbox-harvester")
        print(json.dumps({"file": sys.argv[2], "verdict": v, "reason": why, "stats": st,
                          "otel": {"stats": _otel_stats(),
                                   "call_errors": _otel_emit_errors,
                                   "emit_failures": _otel_emit_failures}},
                         ensure_ascii=False, indent=1))
        return
    seen = harvested()
    # 2026-11-02 RT 修复（token 一次性·收割面放大链收口）：同一任务的重复回报
    # （同一 claim_token 被门户反复受理落盘，af_mes.sandbox_report 实录 32 任务/
    # 34 对复用记账、最小间隔 109ms）此前按文件名逐份各自收割校验，直接放大进
    # 验证裁决流。门户已强制 claim_token 一次性（/report 二报 409，2026-11-02
    # 部署生效），这里按契约补上收割面的任务级去重：/claim 对已报告任务恒 409、
    # 停滞收回需 ≥15min 且已回报 claim 不参与收回（portal _reclaim_stalled 跳过
    # reported）——同任务相邻回报 <15min 者必为同一 token 复用，只认最早一笔，
    # 其余按重复拒收（仍记入 .harvested，不重扫）。≥15min 的笔序不在此裁决
    # （避免误伤任何人工重开流），跨 run 判定以 .harvested 已收名为准。
    DUP_WINDOW_MS = 900 * 1000  # 与门户 STALL_S（15min 停滞收回窗）同源

    def _ts_of(n):
        m = re.match(r"^(.*)-(\d{13})\.json$", n)
        return (m.group(1), int(m.group(2))) if m else (None, 0)

    last_rep = {}
    for n in seen:
        t, ts = _ts_of(n)
        if t and ts > last_rep.get(t, 0):
            last_rep[t] = ts
    for rp in sorted(gov_reports(), key=lambda p: _ts_of(os.path.basename(p))[1]):
        name = os.path.basename(rp)
        if name in seen:
            continue
        _t, _ts = _ts_of(name)
        if _t and abs(_ts - last_rep.get(_t, 0)) < DUP_WINDOW_MS and last_rep.get(_t, 0) > 0:
            gap_s = abs(_ts - last_rep[_t]) / 1000.0
            log_line(f"| {name} | rejected | 同任务重复回报（距上一笔 {gap_s:.0f}s <15min："
                     f"同一 claim_token 复用，门户 409 语义的对偶，只认最早一笔）| - |")
            if not dry:
                open(DONE, "a").write(name + "\n")
            continue
        try:
            rep = gov_cat(rp)
        except Exception as e:
            log_line(f"| {name} | rejected | 拉取失败:{str(e)[:60]} | - |")
            continue
        ev = fetch_arxiv(rep.get("task_id", ""))
        try:
            v, why, st = validate(rep, ev if any(ev.values()) else None)
        except Exception as e:
            v, why, st = "rejected", f"校验异常（按拒收处理）: {type(e).__name__}: {str(e)[:80]}", {}
        # OTel MVP 埋点：收割面单报告校验（harvest 循环路径；去重/落盘语义不变）
        _otel_safe(task_id=rep.get("task_id", "unknown"), verdict=v,
                   atoms=st.get("atoms", st.get("verdicts", 0)),
                   quote_hit=st.get("quote_hit"), quote_miss=st.get("quote_miss"),
                   mode="dry-run" if dry else "harvest",
                   service="sandbox-harvester")
        if v == "ok" and not dry:
            # 2026-11-02 kb-arbitrate 修复：裁决型回报（kb-verify/kb-arbitrate/kb-distill，
            # stats 带 card 键）结构是裁决清单而非原子集，不产候选层 JSONL（旧法对它们跑
            # to_candidates 会写 0 行空文件且日志谎称走候选线）；消费面在事件路由器。
            if st.get("card"):
                log_line(f"| {name} | ok | {why}；stats={json.dumps(st, ensure_ascii=False)} | - |")
            else:
                fp, n = to_candidates(rep)
                log_line(f"| {name} | ok | 原子 {n}；回查 hit={st.get('quote_hit')} miss={st.get('quote_miss')} | {fp} |")
        else:
            log_line(f"| {name} | {v} | {why or '(dry-run)'}；stats={json.dumps(st, ensure_ascii=False)} | - |")
        if not dry:
            open(DONE, "a").write(name + "\n")
            if _t and _ts > last_rep.get(_t, 0):
                last_rep[_t] = _ts
    tail = f"harvest done; log: {LOG}"
    st = _otel_stats()
    if st:
        tail += (f"; otel spans={st['spans']} metrics={st['metrics']} "
                 f"errors={st['errors']} stop_skipped={st['skipped_stop']}")
    if _otel_emit_errors:
        tail += f"; otel 埋点调用异常 {_otel_emit_errors} 次（stderr 已逐条记账）"
    if _otel_emit_failures:
        # 发射真失败（collector 不可达等）计数入汇总行——此前只有 stderr 逐条，
        # 而 stderr 会被调用方的 `2>&1 | tail -1` 吃掉（现由 event-router 分流捕获）。
        tail += f"; otel 发射失败 {_otel_emit_failures} 次（stderr 已逐条记账）"
    print(tail)


if __name__ == "__main__":
    main()
