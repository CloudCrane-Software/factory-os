#!/usr/bin/env python3
r"""kb-quote-purge.py — KB 存量引文污染清洗（RT-kbquote 批，2026-11-02）

背景（红队确证发现，只读复扫亲证）：kb/kb.db status='verified'∧source_corpus='sandbox'
的原子中，其 attrs.source.quote 在论文证据缓存 kb-seed/sandbox/evidence-cache/<paper>/
{abs.md,full.md} 中逐字不存在的有 1,330 条；空白归一化后仍 miss 1,137 条（连字都不在
缓存里，属编造/改写引文，非格式差异）；其中 103 条历史上有过 refute/unverifiable
裁决（latest 口径 refute 30 / unverifiable 30）——代码侧 admit 过滤
（tools/event-router.py:1137-1150，2026-10-31/11-01 两轮 RT 修复）只管住了增量，
存量数据零清洗、无对账门（grep quote_check tools/all-gates.sh=0）。

清洗标准（与 2026-11-01 起增量 admit 的机械真值同源）：
  引文在证据缓存中逐字（verbatim）不在 → 宽容空白差异（\s 归一化）后再查；
  归一化后仍不在 = 污染（引文文本在论文证据里不存在，含每篇缓存全量拼接 haystack）。
  归一化后命中 = 保留（格式/换行差异，非编造），单列 tolerance_kept 类如实计数。

清洗动作（幂等、可追溯、可人工回滚，不删任何行）：
  registry.db：verified → rejected（附 note 前缀 quote-purge@<日期>）。
    ——不走 kb-seed/registry.py reject（其只对 candidate 生效，registry.py:54），
      也不留 candidate（kb-ingest 按 registry status∈{verified,candidate} 选拉，
      put_atom 直写 status 会把 kb 侧 retired 翻回 verified——kb-ingest.py:234/271；
      只有 rejected 两边永不重选，清洗才耐久）。registry.py:5「verified/rejected 终态
      不改回」的立法本意是防验证口径翻饼，本清洗是机械真值裁决（引文不在证据里），
      非口径翻饼；偏离已在本头注 + 计划/变更日志.md 显式登记，人工可逆（改回即回滚）。
  kb/kb.db：verified → retired（走 kb.store.KBStore.update_status，状态机合法迁移
    verified→retired，自动追加 provenance status_change 事件；import_registry 对
    retired「绝不触碰」——kb/import_registry.py:220，KB 侧本地裁决永不被台账覆盖）。
  顺序：先 registry 后 kb（registry rejected 落定后，即使 kb 半途失败也不存在
    「kb 翻回 verified」的通路；kb 失败会留 verified 且被对账门点名）。

对账门：tools/test-kb-quote-integrity.py（复用本件 scan_quote_integrity，单一真源），
  已注册 all-gates L2 + tools/test-manifest.list——此后任何新 admit 的坏引文即红。

用法：
  python3 tools/kb-quote-purge.py             # 干跑：只算账出计划，不写库
  python3 tools/kb-quote-purge.py --apply     # 实清洗（写 registry + kb，出回执）
  python3 tools/kb-quote-purge.py --apply --receipt-dir DIR
退出码：0 = 干跑出账 或 实清洗后复扫归零；1 = 存在清洗拒判类（缺 quote/缺缓存）
        或实清洗后复扫仍非零；2 = 前置/环境不满足。
回执：$HOME/kb-quote-purge-logs/<UTC时间戳>/receipt.json（硬纪律 7：不落 /tmp）。
零密钥、零网络：只读本仓两库与证据缓存；写仅限两库的状态/备注字段与回执目录。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "kb", "kb.db")
DEFAULT_REGISTRY = os.path.join(REPO_ROOT, "kb-seed", "registry.db")
DEFAULT_SEED_ROOT = os.path.join(REPO_ROOT, "kb-seed")
DEFAULT_RECEIPT_DIR = os.path.join(
    os.path.expanduser("~"), "kb-quote-purge-logs")
PURGE_TAG = time.strftime("quote-purge@%Y-%m-%d", time.gmtime())
EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


def norm_ws(s: str) -> str:
    """空白归一化：删尽全部空白字符后再比对（宽容 md 排版/换行差异）。"""
    return re.sub(r"\s+", "", s or "")


class EvidenceCache:
    """按论文缓存 abs.md/full.md 文本（进程内 dict 缓存；扫描期内只读）。"""

    def __init__(self, seed_root: str):
        self.root = os.path.join(seed_root, "sandbox", "evidence-cache")
        self._texts = {}

    def haystack(self, paper: str) -> str | None:
        """该论文全部缓存文本拼接；无任何缓存文件返回 None。"""
        if paper in self._texts:
            return self._texts[paper]
        parts = []
        for name in ("abs.md", "full.md"):
            p = os.path.join(self.root, paper, name)
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        parts.append(fh.read())
                except OSError:
                    pass  # 读不开按缺该文件处置；全缺由 no_cache 类点名
        text = "\n".join(parts) if parts else None
        self._texts[paper] = text
        return text


def scan_quote_integrity(db_path: str, seed_root: str,
                         progress=None) -> dict:
    """只读扫描 verified∧sandbox 原子的引文完整性，返回分类账（id 列表排序稳定）。

    分类：
      checked            有 quote 且有缓存、完成比对的原子数
      verbatim_miss      逐字不在缓存的 id（含下类；发现口径=红队发现标题）
      normalized_miss    空白归一化后仍不在缓存的 id（清洗目标=确证污染）
      tolerance_kept     逐字 miss 但归一化命中（格式差异，保留并计数）
      no_quote / no_cache  缺 attrs.source.quote / 证据缓存全缺（拒判类：不清洗、
                         不放行，由调用方显式红出来——「缓存不全不是托辞」）
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError("KB 库不存在：%s" % db_path)
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        rows = con.execute(
            "SELECT id, paper, created_at, attrs FROM atoms "
            "WHERE status='verified' AND source_corpus='sandbox'").fetchall()
    finally:
        con.close()
    cache = EvidenceCache(seed_root)
    out = {"scanned": len(rows), "checked": 0, "verbatim_miss": [],
           "normalized_miss": [], "tolerance_kept": [], "no_quote": [],
           "no_cache": [], "detail": {}}
    for i, (aid, paper, created_at, attrs_raw) in enumerate(rows):
        if progress and i % 4000 == 0:
            progress(i, len(rows))
        try:
            attrs = json.loads(attrs_raw) if attrs_raw else {}
        except ValueError:
            attrs = {}
        quote = ((attrs.get("source") or {}).get("quote") or "").strip()
        if not quote:
            out["no_quote"].append(aid)
            continue
        hay = cache.haystack(paper or "")
        if hay is None:
            out["no_cache"].append(aid)
            continue
        out["checked"] += 1
        if quote in hay:
            continue
        nq = norm_ws(quote)
        if nq and nq in norm_ws(hay):
            out["verbatim_miss"].append(aid)
            out["tolerance_kept"].append(aid)
            continue
        out["verbatim_miss"].append(aid)
        out["normalized_miss"].append(aid)
        out["detail"][aid] = {"paper": paper or "", "created_at": created_at or "",
                              "quote_sha256": hashlib.sha256(
                                  quote.encode("utf-8")).hexdigest(),
                              "quote_head": quote[:80]}
    for k in ("verbatim_miss", "normalized_miss", "tolerance_kept",
              "no_quote", "no_cache"):
        out[k].sort()
    return out


def _registry_reject_all(registry_path: str, targets: list, detail: dict,
                         batch_commit: int = 200) -> dict:
    """registry.db：verified→rejected（守卫 status='verified'，分批提交让位在役写者）。"""
    con = sqlite3.connect(registry_path, timeout=30.0)
    con.execute("PRAGMA busy_timeout=30000")
    ok, not_verified, errs = [], [], []
    try:
        pending = 0
        for aid in targets:
            paper = (detail.get(aid) or {}).get("paper", "")
            note = ("%s：引文空白归一化后不在证据缓存"
                    "(kb-seed/sandbox/evidence-cache/%s/)" % (PURGE_TAG, paper))
            try:
                cur = con.execute(
                    "UPDATE candidates SET status='rejected', note=note||? "
                    "WHERE id=? AND status='verified'", ("；" + note, aid))
                if cur.rowcount:
                    ok.append(aid)
                    pending += 1
                else:
                    not_verified.append(aid)
            except sqlite3.Error as e:
                errs.append({"id": aid, "error": str(e)[:120]})
            if pending >= batch_commit:
                con.commit()
                pending = 0
        con.commit()
    finally:
        con.close()
    return {"rejected": ok, "registry_not_verified": not_verified,
            "registry_errors": errs}


def _kb_retire_all(db_path: str, targets: list) -> dict:
    """kb.db：verified→retired（KBStore 状态机合法迁移 + provenance 事件）。"""
    sys.path.insert(0, REPO_ROOT)
    from kb.store import KBStore  # noqa: E402
    store = KBStore(db_path)
    ok, skipped, errs = [], [], []
    try:
        for aid in targets:
            try:
                if store.update_status(
                        aid, "retired",
                        reason="%s：引文空白归一化后不在证据缓存（存量污染清洗；"
                               "registry 已同步 rejected；对账门 tools/test-kb-"
                               "quote-integrity.py 常驻）" % PURGE_TAG):
                    ok.append(aid)
                else:
                    skipped.append(aid)  # 不存在/状态已变/迁移不合法
            except (ValueError, sqlite3.Error) as e:
                errs.append({"id": aid, "error": str(e)[:120]})
    finally:
        store.close()
    return {"retired": ok, "kb_skipped": skipped, "kb_errors": errs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="KB 存量引文污染清洗（verified∧sandbox 引文逐字回查证据缓存）")
    ap.add_argument("--db", default=DEFAULT_DB, help="KB 库（默认 kb/kb.db）")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
                    help="registry 台账（默认 kb-seed/registry.db）")
    ap.add_argument("--seed-root", default=DEFAULT_SEED_ROOT,
                    help="kb-seed 根（默认 ./kb-seed）")
    ap.add_argument("--apply", action="store_true",
                    help="实清洗（缺省=干跑只出账）")
    ap.add_argument("--receipt-dir", default=DEFAULT_RECEIPT_DIR,
                    help="回执目录（默认 ~/kb-quote-purge-logs）")
    a = ap.parse_args(argv)

    t0 = time.time()
    try:
        scan = scan_quote_integrity(a.db, a.seed_root,
                                    progress=lambda i, n: print(
                                        "  scan %d/%d" % (i, n), flush=True))
    except (FileNotFoundError, sqlite3.Error) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return EXIT_ENV
    summary = {"scanned": scan["scanned"], "checked": scan["checked"]}
    summary.update({k: len(scan[k]) for k in
                    ("verbatim_miss", "normalized_miss",
                     "tolerance_kept", "no_quote", "no_cache")})
    print("引文完整性扫描：scanned=%(scanned)s checked=%(checked)s "
          "verbatim_miss=%(verbatim_miss)s normalized_miss=%(normalized_miss)s "
          "tolerance_kept=%(tolerance_kept)s no_quote=%(no_quote)s "
          "no_cache=%(no_cache)s" % summary, flush=True)

    # 拒判类：缺 quote / 缺缓存 → 不清洗不放行（防「缓存不全」托辞）
    if summary["no_quote"] or summary["no_cache"]:
        print("FAIL: 拒判类非零 no_quote=%s no_cache=%s（例 %s / %s）——人工核判，"
              "本工具不处置不放行" % (summary["no_quote"], summary["no_cache"],
                                    scan["no_quote"][:3], scan["no_cache"][:3]),
              flush=True)
        return EXIT_FAIL

    targets = scan["normalized_miss"]
    if not a.apply:
        print("DRY-RUN：清洗目标 %d 条（registry verified→rejected + kb "
              "verified→retired）；--apply 实清洗" % len(targets), flush=True)
        for aid in targets[:5]:
            print("  例 %s（paper %s，quote %s…）"
                  % (aid, scan["detail"][aid]["paper"],
                     scan["detail"][aid]["quote_head"][:48]), flush=True)
        return EXIT_OK

    if not targets:
        print("无清洗目标（normalized_miss=0）——幂等空跑", flush=True)
        return EXIT_OK

    reg = _registry_reject_all(a.registry, targets, scan["detail"])
    print("registry rejected=%d / 目标%d（not_verified=%d errors=%d）"
          % (len(reg["rejected"]), len(targets),
             len(reg["registry_not_verified"]), len(reg["registry_errors"])),
          flush=True)
    kb = _kb_retire_all(a.db, targets)
    print("kb retired=%d / 目标%d（skipped=%d errors=%d）"
          % (len(kb["retired"]), len(targets),
             len(kb["kb_skipped"]), len(kb["kb_errors"])), flush=True)

    # 实清洗后复扫：必须归零（同一进程内证据缓存可复用）
    scan2 = scan_quote_integrity(a.db, a.seed_root)
    remain = len(scan2["normalized_miss"]) + len(scan2["no_quote"]) \
        + len(scan2["no_cache"])
    receipt = {
        "tool": "tools/kb-quote-purge.py", "applied": True,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - t0, 1),
        "db": a.db, "registry": a.registry, "seed_root": a.seed_root,
        "before": summary, "targets": len(targets),
        "registry_rejected": len(reg["rejected"]),
        "registry_not_verified": reg["registry_not_verified"],
        "registry_errors": reg["registry_errors"],
        "kb_retired": len(kb["retired"]),
        "kb_skipped": kb["kb_skipped"], "kb_errors": kb["kb_errors"],
        "after": {"scanned": scan2["scanned"], "checked": scan2["checked"],
                  **{k: len(scan2[k]) for k in
                     ("verbatim_miss", "normalized_miss", "tolerance_kept",
                      "no_quote", "no_cache")}},
        "target_detail": {aid: scan["detail"][aid] for aid in targets},
    }
    rdir = os.path.join(a.receipt_dir,
                        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    os.makedirs(rdir, exist_ok=True)
    rpath = os.path.join(rdir, "receipt.json")
    with open(rpath, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, ensure_ascii=False, indent=1)
    print("回执：%s" % rpath, flush=True)
    if remain:
        print("FAIL: 实清洗后复扫仍有未净项（normalized_miss=%d no_quote=%d "
              "no_cache=%d）" % (len(scan2["normalized_miss"]),
                                 len(scan2["no_quote"]),
                                 len(scan2["no_cache"])), flush=True)
        return EXIT_FAIL
    print("PURGED：清洗后复扫归零（verified∧sandbox 引文对账 0 miss）", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
