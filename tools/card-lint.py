#!/usr/bin/env python3
"""card-lint — 任务卡质量闸（P3-11，自动派发的防退化闸门）

机器可判的硬指标：任何自动生成的门户任务（沙箱派发卡）发布前必须全绿，
否则不许发布（fail-closed）。目的是回答「派发委派后质量会不会掉」——
把质量从人的品味变成可执行的门。

检查项（每条 give 出可核证据）：
  L1 三件套齐备：problem.md / AGENTS.md / meta.json 均存在且非平凡（>200B / >20B）
  L2 任务书含完整 payload schema（atom_id + kind 词表 + source 四字段 + relations 词表）
  L3 证据源可解析：任务书引用的 arXiv id 唯一且格式正确（NNNN.NNNNN）
  L4 证据缓存可用：本地 evidence-cache/<id>/abs.md 存在且 >5KB；
     full.md 存在时须 >2KB，否则该文被标为「仅摘要页」，任务书须已声明降级
  L5 引用纪律在册：任务书须含「连续子串」字样（AGENTS.md 契约同款）
  L6 禁项在册：AGENTS.md 须含禁项与自验清单段
  L7 meta 合法：JSON 可解析，title/type/est_load 三字段在位
  L8 无密钥/内网串：任务书与 AGENTS.md 不得出现 sk-/token=/密码/内网 IP 段

2026-10-29 供给扩容批 S2 新增 kind 维度（tools/quality-cards.py 三类质量工序卡）：
  · L2 词表按 kind 分表（KIND_L2）：既有 kind（kb-verify / kb-atom-extraction）逐字节
    沿用原 REQUIRED_SCHEMA/REQUIRED_KINDS；新 kind 显式登记自己的 payload schema 与
    合法值词表。未登记的 kind 回落既有词表（fail-closed 默认，不因漏登记而放松）。
  · L3/L4 证据源规则按 kind 分流：ARXIV_EVIDENCE_KINDS 白名单内的 kind 走原「单一
    arXiv id + evidence-cache 快照」强规则（**代码路径与判据一字未改**）；
    KB_EVIDENCE_KINDS 白名单内的 kind（kb-distill-review）走等强度「KB 内部证据」门
    L3′/L4′——卡必须内嵌赢家/输家原子全文与 merge provenance，lint 直接对 kb/kb.db
    交叉验证（atom_id 存在、内嵌正文与库内逐字节一致、provenance 确有该 merge 对）。
    证据源=库本身、本地可机检，比抓外部快照更强；未登记 kind 一律默认 arXiv 强规则。
用法：
  python3 tools/card-lint.py <任务目录> [...]        # 指定目录
  python3 tools/card-lint.py --all                  # 扫本地 task-seeds/ 全部
  python3 tools/card-lint.py --gov                  # 扫 gov 门户全部任务（ssh 拉回来校）
退出码：0 全绿；1 有硬伤（须修）；2 用法错误。
"""
import json
import os
import re
import subprocess
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = os.path.join(WS, "kb-seed/sandbox/task-seeds")
CACHE = os.path.join(WS, "kb-seed/sandbox/evidence-cache")
GOV = "root@gov-host.invalid"
ARX_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]\s*\S{12,}|password\s*[:=]|token\s*[:=]\s*[A-Za-z0-9_\-]{16,})", re.I)
INNER_RE = re.compile(r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b")

REQUIRED_SCHEMA = ["atom_id", "kind", "source", "quote", "relations"]
REQUIRED_KINDS = ["claim", "concept", "procedure", "evidence_record", "failure_pattern", "evaluator"]

# ---- kind 维度（2026-10-29 供给扩容批 S2）----------------------------------
# L2 词表分表：既有 kind 与原常量同值（行为逐字节不变）；新 kind 显式登记。
ARBITRATE_SCHEMA = ["atom_id", "verdict", "quote_check", "reason", "final", "rationale"]
ARBITRATE_KINDS = ["uphold", "refute", "unverifiable"]
DISTILL_SCHEMA = ["atom_id", "text", "score", "reason", "provenance"]
DISTILL_KINDS = ["winner", "loser", "no_loss", "info_loss", "wrong_winner", "unverifiable"]

KIND_L2 = {
    "kb-verify": (REQUIRED_SCHEMA, REQUIRED_KINDS),
    "kb-atom-extraction": (REQUIRED_SCHEMA, REQUIRED_KINDS),
    "kb-arbitrate": (ARBITRATE_SCHEMA, ARBITRATE_KINDS),
    "kb-distill-review": (DISTILL_SCHEMA, DISTILL_KINDS),
}
# L3/L4 证据源白名单（显式登记；未登记 kind 默认 arXiv 强规则 = fail-closed）
ARXIV_EVIDENCE_KINDS = {"kb-verify", "kb-atom-extraction", "kb-arbitrate"}
KB_EVIDENCE_KINDS = {"kb-distill-review"}

# KB 内部证据（L3′/L4′）的内嵌结构：卡里必须出现且可机检的定界块
KB_META_RE = re.compile(r"<!--KB-DISTILL-META-->(?P<body>.*?)<!--KB-DISTILL-META-END-->", re.S)
KB_RECORD_RE = re.compile(
    r"<!--KB-DISTILL:(?P<role>winner|loser):(?P<atom_id>[^>]+?)-->\n"
    r"(?P<content>.*?)"
    r"\n<!--KB-DISTILL-END:(?P=role):(?P=atom_id)-->", re.S)
KB_META_KEYS = ("atom_id", "winner", "loser", "score", "reason", "provenance")


def card_kind(meta_path):
    """meta.json 的 type（kind）；缺失/不可解析 → ""（回落既有默认词表，fail-closed）。"""
    try:
        return str(json.load(open(meta_path, encoding="utf-8")).get("type") or "").strip()
    except Exception:
        return ""


def lint_arxiv_evidence(prob, errs, notes, cache=CACHE):
    """L3/L4 原判据（arXiv 证据源 + evidence-cache 快照）——从 lint_card 原样搬出，
    代码路径与判据一字未改；仅改由 kind 白名单决定是否调用。"""
    ids = set(ARX_RE.findall(prob))
    if not ids:
        errs.append("L3 任务书未解析到 arXiv id（证据源缺失或格式异常）")
        return
    if len(ids) > 1:
        errs.append(f"L3 证据源不唯一: {sorted(ids)}（应为单篇）")
        return
    arx = ids.pop()
    notes.append(f"证据源 arXiv:{arx}")
    # L4 证据缓存
    cd = os.path.join(cache, arx)
    abs_f = os.path.join(cd, "abs.md")
    full_f = os.path.join(cd, "full.md")
    if not os.path.isfile(abs_f) or os.path.getsize(abs_f) < 5000:
        errs.append(f"L4 证据缓存缺摘要: {arx}/abs.md")
    else:
        notes.append(f"abs.md {os.path.getsize(abs_f)//1024}KB")
    if os.path.isfile(full_f):
        if os.path.getsize(full_f) < 2000:
            errs.append(f"L4 全文为空壳: {arx}/full.md <2KB（须改标「仅摘要页」并移除该文件）")
        else:
            notes.append(f"full.md {os.path.getsize(full_f)//1024}KB")
    else:
        if "未提供 HTML 全文" not in prob and "仅摘要页" not in prob:
            errs.append(f"L4 全文不可用但任务书未声明降级: {arx}")
        else:
            notes.append("全文不可用→任务书已声明仅摘要页")


def lint_kb_evidence(prob, errs, notes, kb_db=None):
    """L3′/L4′：KB 内部证据门（kind=kb-distill-review，运营者 2026-10-29 裁决方案 B）。

    L3′（结构完整可机检）：卡必须内嵌 merge META 块（atom_id/winner/loser/score/
      reason/provenance 六键齐全）且恰有 winner/loser 两条全文记录块、正文非空。
    L4′（等强度替代 arXiv 快照）：直接对 kb/kb.db 交叉验证——两个 atom_id 存在、
      内嵌正文与库内 content 逐字节一致、provenance 里确有这对 merge 事件。
      kb.db 在本地，机检比抓外部快照更强（伪造内嵌正文=对不上库）。
    """
    db = kb_db or os.path.join(WS, "kb", "kb.db")
    mm = KB_META_RE.search(prob)
    if not mm:
        errs.append("L3′ 缺 KB-DISTILL-META 块（未内嵌合并元数据）")
        return
    meta = {}
    for ln in mm.group("body").splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    miss = [k for k in KB_META_KEYS if not meta.get(k)]
    if miss:
        errs.append(f"L3′ META 块缺字段: {','.join(miss)}")
        return
    recs = KB_RECORD_RE.findall(prob)
    roles = sorted(r[0] for r in recs)
    if roles != ["loser", "winner"]:
        errs.append(f"L3′ 记录块须恰有 winner/loser 各一条，实得 {roles or '无'}")
        return
    if meta.get("winner") not in [r[1] for r in recs if r[0] == "winner"]:
        errs.append(f"L3′ META.winner={meta.get('winner')} 与 winner 记录块 atom_id 不一致")
        return
    if meta.get("loser") not in [r[1] for r in recs if r[0] == "loser"]:
        errs.append(f"L3′ META.loser={meta.get('loser')} 与 loser 记录块 atom_id 不一致")
        return
    notes.append(f"L3′ 内嵌合并对 {meta['winner']} ← {meta['loser']}（score {meta['score']}）")

    # L4′：对 kb.db 交叉验证（只读）
    if not os.path.isfile(db):
        errs.append(f"L4′ kb 库不可用（fail-closed）: {db}")
        return
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception as e:
        errs.append(f"L4′ kb 库连接失败（fail-closed）: {e}")
        return
    try:
        contents = {}
        for role, aid, body in recs:
            row = con.execute("SELECT content FROM atoms WHERE id=?", (aid,)).fetchone()
            if row is None:
                errs.append(f"L4′ 库内无此 atom: {aid}（{role}）")
                continue
            contents[aid] = row[0] or ""
            if body != (row[0] or ""):
                errs.append(f"L4′ 内嵌正文与库内不一致: {aid}（{role}，"
                            f"卡内 {len(body)}B / 库内 {len(row[0] or '')}B）")
        w, l = meta["winner"], meta["loser"]
        if w in contents and l in contents:
            ev = con.execute(
                "SELECT atom_id, event_type, detail FROM provenance "
                "WHERE event_type='merge' AND atom_id IN (?,?)", (w, l)).fetchall()
            ok = False
            for aid, et, det in ev:
                try:
                    d = json.loads(det)
                except Exception:
                    continue
                if aid == l and d.get("counterpart") == w:
                    ok = True
                if aid == w and d.get("counterpart") == l:
                    ok = True
            if not ok:
                errs.append(f"L4′ provenance 无该 merge 对: {w} / {l}")
            else:
                notes.append(f"L4′ kb 交叉验证通过（2 原子存在+正文逐字节一致+merge 事件在册）")
    finally:
        con.close()


def lint_card(d, cache=CACHE, kb_db=None):
    """返回 (errors, notes)：errors 为硬伤列表，notes 为可读证据。"""
    errs = []
    notes = []
    name = os.path.basename(d.rstrip("/"))
    pm = os.path.join(d, "problem.md")
    am = os.path.join(d, "AGENTS.md")
    mm = os.path.join(d, "meta.json")

    # L1 三件套
    for f, lim, tag in ((pm, 200, "problem.md"), (am, 200, "AGENTS.md"), (mm, 20, "meta.json")):
        if not os.path.isfile(f):
            errs.append(f"L1 缺件: {tag}")
        elif os.path.getsize(f) < lim:
            errs.append(f"L1 过小: {tag}={os.path.getsize(f)}B < {lim}B")
    if errs:
        return errs, notes
    prob = open(pm, encoding="utf-8").read()
    agr = open(am, encoding="utf-8").read()
    kind = card_kind(mm)

    # L2 schema 完整（按 kind 取词表；未登记 kind 回落既有词表，不放松）
    schema_keys, kind_vocab = KIND_L2.get(kind, (REQUIRED_SCHEMA, REQUIRED_KINDS))
    missing = [k for k in schema_keys if k not in prob]
    if missing:
        errs.append(f"L2 任务书缺 schema 字段: {','.join(missing)}")
    kinds_missing = [k for k in kind_vocab if k not in prob]
    if kinds_missing:
        errs.append(f"L2 缺 kind 词表项: {','.join(kinds_missing)}")

    # L3/L4 证据源（按 kind 分流；未登记 kind 默认 arXiv 强规则）
    if kind in KB_EVIDENCE_KINDS:
        lint_kb_evidence(prob, errs, notes, kb_db=kb_db or os.path.join(WS, "kb", "kb.db"))
    else:
        lint_arxiv_evidence(prob, errs, notes, cache=cache)

    # L5 引用纪律
    if "连续子串" not in prob and "连续子串" not in agr:
        errs.append("L5 引用逐字纪律不在册（缺「连续子串」字样）")
    # L6 禁项与自验清单
    if "禁项" not in agr:
        errs.append("L6 AGENTS.md 缺禁项段")
    if "自验" not in agr:
        errs.append("L6 AGENTS.md 缺自验清单段")
    # L7 meta
    try:
        meta = json.load(open(mm, encoding="utf-8"))
        for k in ("title", "type", "est_load"):
            if not meta.get(k):
                errs.append(f"L7 meta 缺字段: {k}")
    except Exception as e:
        errs.append(f"L7 meta.json 解析失败: {e}")
    # L8 密钥/内网
    for txt, tag in ((prob, "problem.md"), (agr, "AGENTS.md")):
        m = SECRET_RE.search(txt)
        if m:
            errs.append(f"L8 {tag} 疑似密钥: {m.group(0)[:12]}…")
        m = INNER_RE.search(txt)
        if m:
            errs.append(f"L8 {tag} 含内网地址: {m.group(0)}")
    return errs, notes


def lint_all(dirs, label):
    bad = 0
    for d in dirs:
        errs, notes = lint_card(d)
        if errs:
            bad += 1
            print(f"✗ {os.path.basename(d.rstrip('/'))}")
            for e in errs:
                print(f"    {e}")
        else:
            print(f"✓ {os.path.basename(d.rstrip('/'))}  {' / '.join(notes)}")
    print(f"\n{label}: 共 {len(dirs)} 卡，硬伤 {bad}")
    return bad


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args == ["--all"]:
        dirs = [os.path.join(SEEDS, d) for d in sorted(os.listdir(SEEDS))
                if os.path.isdir(os.path.join(SEEDS, d))]
        return 1 if lint_all(dirs, "本地任务卡") else 0
    if args == ["--gov"]:
        raw = subprocess.run(f"ssh {GOV} 'ls -d /opt/company/af-jobs/data/tasks/*/'",
                             shell=True, capture_output=True, text=True, timeout=120).stdout.split()
        tmp = "/tmp/gov-cards"
        subprocess.run(f"rm -rf {tmp} && mkdir -p {tmp} && rsync -a --timeout=60 "
                       f"root@gov-host.invalid:/opt/company/af-jobs/data/tasks/ {tmp}/",
                       shell=True, capture_output=True, timeout=180)
        dirs = [os.path.join(tmp, d) for d in sorted(os.listdir(tmp))
                if os.path.isdir(os.path.join(tmp, d))]
        return 1 if lint_all(dirs, "gov 门户任务卡") else 0
    dirs = [a.rstrip("/") for a in args]
    return 1 if lint_all(dirs, "指定任务卡") else 0


if __name__ == "__main__":
    sys.exit(main())
