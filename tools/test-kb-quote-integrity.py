#!/usr/bin/env python3
"""test-kb-quote-integrity.py — KB 引文对账门（quote_check 机械真值的存量常驻化）。

背景（红队确证发现，RT-kbquote 批 2026-11-02）：增量侧 admit 已按「uphold∧quote_check」
过滤（tools/event-router.py:1137-1150），但存量 verified∧sandbox 原子中曾确证 1,330 条
引文逐字不在论文证据缓存（空白归一化后仍 miss 1,137 条，103 条带 refute/unverifiable
裁决），且此前无任何门可测（grep quote_check tools/all-gates.sh=0）——代码修了，
数据没清、门也没有。本门 = 该缺口的常驻对账：
  对 kb/kb.db 全量 verified∧sandbox 原子，逐条把 attrs.source.quote 回查
  kb-seed/sandbox/evidence-cache/<paper>/{abs.md,full.md}（逐字 → 空白归一化宽容）：
    A1 缺 attrs.source.quote 的 verified 原子数必须为 0（无引文=无 provenance，红）；
    A2 证据缓存全缺的原子数必须为 0（「缓存不全」不是托辞，红）；
    A3 空白归一化后仍 miss 的原子数必须为 0（确证污染：编造/改写引文，红）。
  逐字 miss 但归一化命中 = 排版差异，保留并只计数（tolerance_kept，不红）。
  红时点名论文与原子 id，并交叉点名 registry.db 侧状态（双库同污一屏看全）。

扫描逻辑单一真源：复用 tools/kb-quote-purge.py 的 scan_quote_integrity（importlib
装载，同 tools/test-kb-content-parity.py 装载 kb-ingest 的先例）——清洗件与对账门
永不各持一套口径。

用法：
  python3 tools/test-kb-quote-integrity.py
退出码：0 全过；1 断言失败（A1/A2/A3 任一非零）；2 前置/环境不满足（缺库/缺件）。
all-gates L2 注册（register_L2 显式超时），tools/test-manifest.list 在列（防单件摘除）。
零密钥、零网络、零写入：两库只读（mode=ro），证据缓存只读。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PURGE_TOOL = os.path.join(WS, "tools", "kb-quote-purge.py")
DEFAULT_DB = os.path.join(WS, "kb", "kb.db")
DEFAULT_REGISTRY = os.path.join(WS, "kb-seed", "registry.db")
DEFAULT_SEED_ROOT = os.path.join(WS, "kb-seed")

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2


def _load_scan():
    if not os.path.isfile(PURGE_TOOL):
        print("ERROR: 清洗件不在位：%s（对账门与清洗件必须同在——摘件须显式对账，"
              "不得静默放行）" % PURGE_TOOL, file=sys.stderr)
        return None
    spec = importlib.util.spec_from_file_location("kb_quote_purge_under_audit",
                                                  PURGE_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "scan_quote_integrity"):
        print("ERROR: %s 无 scan_quote_integrity——口径单一真源被破坏" % PURGE_TOOL,
              file=sys.stderr)
        return None
    return mod


def _registry_status_of(ids):
    """红时交叉点名 registry 侧状态（只读；读不到返回空表，不构成额外红）。"""
    out = {}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DEFAULT_REGISTRY, uri=True)
        try:
            for aid in ids:
                row = con.execute("SELECT status FROM candidates WHERE id=?",
                                  (aid,)).fetchone()
                out[aid] = row[0] if row else "(registry 无此 id)"
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return out


def main() -> int:
    mod = _load_scan()
    if mod is None:
        return EXIT_ENV
    if not os.path.isfile(DEFAULT_DB):
        print("ERROR: KB 库不存在：%s" % DEFAULT_DB, file=sys.stderr)
        return EXIT_ENV

    scan = mod.scan_quote_integrity(DEFAULT_DB, DEFAULT_SEED_ROOT)
    counts = {"scanned": scan["scanned"], "checked": scan["checked"]}
    counts.update({k: len(scan[k]) for k in
                   ("verbatim_miss", "normalized_miss", "tolerance_kept",
                    "no_quote", "no_cache")})
    print("KB 引文对账（verified∧sandbox %s 条，完成比对 %s 条）"
          % (counts["scanned"], counts["checked"]), flush=True)
    print("  逐字 miss=%s（其中空白归一化命中=排版差异保留 %s 条）"
          % (counts["verbatim_miss"], counts["tolerance_kept"]), flush=True)

    failures = []
    if counts["no_quote"]:
        failures.append("A1 缺引文 attrs.source.quote=%s 条（例 %s）"
                        % (counts["no_quote"], scan["no_quote"][:5]))
    if counts["no_cache"]:
        failures.append("A2 证据缓存全缺=%s 条（例 %s；「缓存不全」不是托辞）"
                        % (counts["no_cache"], scan["no_cache"][:5]))
    if counts["normalized_miss"]:
        bad = scan["normalized_miss"]
        reg = _registry_status_of(bad[:5])
        examples = ["%s（paper %s, registry=%s）"
                    % (aid, scan["detail"].get(aid, {}).get("paper", "?"),
                       reg.get(aid, "?")) for aid in bad[:5]]
        failures.append("A3 引文空白归一化后仍不在证据缓存=%s 条（确证污染；例 %s%s）"
                        % (counts["normalized_miss"], "; ".join(examples),
                           " …" if counts["normalized_miss"] > 5 else ""))
    for line in failures:
        print("  [FAIL] %s" % line, flush=True)

    print(json.dumps({"gate": "test-kb-quote-integrity", **counts,
                      "pass": not failures}, ensure_ascii=False), flush=True)
    if failures:
        print("QUOTE-INTEGRITY FAILED: %d 项断言红（清洗入口："
              "python3 tools/kb-quote-purge.py，先干跑后 --apply）" % len(failures),
              flush=True)
        return EXIT_FAIL
    print("QUOTE-INTEGRITY PASSED: A1/A2/A3 全零（verified∧sandbox 引文逐字"
          "可回查证据缓存，宽容空白排版差异）", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
