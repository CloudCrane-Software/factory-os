#!/usr/bin/env python3
"""kb-ingest.py — registry verified 原子 → kb/ 知识库原子导入器（轨道 K，冲刺批 1 第 4 线）

背景：沙箱抽取线（seeder→claim→harvest→quote 回查→交叉验证→registry admit）生产出的
      verified 原子散在 kb-seed/registry.db（只有 id/corpus/status/note）与收割件
      kb-seed/**/*.jsonl（原子原文）两处。本工具把两者按 id 内连接，原子级写入 kb/ 新库
      （kb.store.KBStore，十 API 契约见《第三阶段总体作战计划-v2》§三.2）。

连接口径（registry 无原文，必须回收割件取）：
  registry.candidates(id, source_corpus, status, created_at, note)  —— 状态与依据
    ⋈ candidate_id / atom_id
  kb-seed/sandbox/*.jsonl、kb-seed/paper-batch1/atoms/*.jsonl、
  kb-seed/candidates-batch1/*.jsonl、计划/研究组/三阶段POC-知识资产-20261027/*.jsonl
                                                                —— 原子原文（kind/body/source/relations）

字段映射（KBStore.put_atom 契约，字段名固定不得增删）：
  id           ← candidate_id | atom_id
  content      ← kb/import_registry.py:94 `_build_content(rec)` 的复用句柄：text（或 content）
                 为主，body/preconditions/influence_hints/notes/summary 里的字符串值收平去重后
                 追加（冲刺批2 第一步：与 kb/import_registry.py 同口径，同 id 两入口混跑不再让
                 库内 content 形态来回翻；实测真语料 478/718 条 verified 两口径不同）
  source_corpus← registry.source_corpus（sandbox / atoms / candidates-batch1 / 三阶段POC…）
  paper        ← 从 source.task / candidate_id 解析出的 arXiv id（NNNN.NNNNN），解析不出为 ""
  status       ← verified（registry verified 才有资格；candidate 见 --status）
  created_at   ← registry.created_at（admit 时刻，KB 侧不改写）
  attrs        ← {kind, body, source(file/locator/quote/evidence_sha256/task/sandbox),
                  relations, extractor, harvested_at, registry_note, registry_admitted_at}

用法：
  python3 tools/kb-ingest.py --dry-run          # 不碰 kb/：只读 registry+收割件，出清单与统计
  python3 tools/kb-ingest.py                    # 真导入 kb/kb.db（默认只导 verified）
  python3 tools/kb-ingest.py --status candidate # 连候选层一起导（KB status=candidate）
  python3 tools/kb-ingest.py --status all       # verified + candidate 两层全导
  python3 tools/kb-ingest.py --sources DIR ...  # 自定义收割件目录（可多个）
  python3 tools/kb-ingest.py --db PATH --out PATH
  python3 tools/kb-ingest.py --quiet            # 不打逐条清单（仍打统计与末行 JSON）
  python3 tools/kb-ingest.py --allow-unresolved # 收割件缺原文只警告不失败

幂等：put_atom 按 id upsert；本工具再按内容指纹跳过"完全没变"的原子（不计 new/updated，
      也不重复写 provenance 事件），故重复跑输出稳定（new=0 updated=0 unchanged=N）。
      content 口径与 kb/import_registry.py 逐字节一致（复用其 _build_content），故同 id 两入口
      交替混跑不会让库内 content 形态来回翻（冲刺批2 第一步；回归见
      tools/test-kb-content-parity.py）。注意 attrs 形状仍是本工具自有（两入口不同，未统一）。
零密钥：不读任何凭据文件、不出网、不 scp/ssh（import 清单仅 argparse/glob/hashlib/json/
        os/sqlite3/sys/time）；registry 以只读方式打开（mode=ro，跑前跑后 sha256 不变）。
--dry-run 独立可用：kb/store.py 尚未就位时也必须能跑（store 只在实际导入时惰性 import，
       统一口径的 content 构造句柄取不到时 dry-run 退化为 text-only 预览，不落库）。
日志风格仿 tools/event-router.py：时间戳行 + 末行 JSON 摘要（摘要不含耗时等漂移字段，
      同输入下两次运行末行逐字节相同——机器门判据之一）。
回滚：删 kb/kb.db（-wal/-shm）；registry 与收割件本工具从不写。
退出码：0 成功（含 unresolved=0）；1 kb/store 缺失或 kb.import_registry 不可用
        （提示改用 --dry-run；实跑取不到统一口径的 content 句柄即 fail-closed）；
        2 参数/IO 错；4 有 verified 原子在收割件里找不到原文（--allow-unresolved 降为警告）；
        5 导入过程中有 put_atom/record_provenance 报错（摘要 JSON 的 errors 数组列明细）。"""
import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
REGISTRY_DB = os.path.join(WS, "kb-seed/registry.db")
KB_DB = os.path.join(WS, "kb/kb.db")
DEFAULT_SOURCES = [
    os.path.join(WS, "kb-seed/sandbox"),
    os.path.join(WS, "kb-seed/paper-batch1/atoms"),
    os.path.join(WS, "kb-seed/candidates-batch1"),
    os.path.join(WS, "计划/研究组/三阶段POC-知识资产-20261027"),
]
ARX_RE = r"(\d{4}\.\d{4,5})"
STATUS_MAP = {"verified": "verified", "candidate": "candidate"}  # registry → KB（rejected 无对应态）


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- 输入侧：registry（只读） ----------

def registry_rows(db, statuses):
    """只读打开 registry.db，取 (id, source_corpus, status, created_at, note)。"""
    if not os.path.isfile(db):
        raise FileNotFoundError(f"registry 不存在: {db}")
    uri = f"file:{db}?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    try:
        rows = c.execute("SELECT id, source_corpus, status, created_at, note "
                         "FROM candidates WHERE status IN (%s)" % ",".join("?" * len(statuses)),
                         tuple(statuses)).fetchall()
    finally:
        c.close()
    return rows


def registry_all_status_counts(db):
    """全量状态分布（dry-run 统计用，便于运营者对账）。"""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(c.execute("SELECT status, COUNT(*) FROM candidates GROUP BY 1").fetchall())
    finally:
        c.close()


# ---------- 输入侧：收割件（原子原文） ----------

def source_files(dirs):
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            log(f"收割件目录不存在，跳过: {d}")
            continue
        out.extend(sorted(glob.glob(os.path.join(d, "*.jsonl"))))
    return out


def build_index(files):
    """candidate_id/atom_id → 原子原文 dict。同 id 多处出现：后读不覆盖先读（首次即收割件原样）。"""
    idx, dup, bad_lines = {}, 0, 0
    for f in files:
        try:
            fh = open(f, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    bad_lines += 1
                    continue
                if not isinstance(j, dict):
                    bad_lines += 1
                    continue
                cid = j.get("candidate_id") or j.get("atom_id")
                if not cid:
                    bad_lines += 1
                    continue
                if cid in idx:
                    dup += 1
                    continue
                idx[cid] = j
    return idx, dup, bad_lines


def parse_paper(*texts):
    import re
    for t in texts:
        if not isinstance(t, str):
            continue
        m = re.search(ARX_RE, t)
        if m:
            return m.group(1)
    return ""


# ---------- content 口径统一（冲刺批2 第一步） ----------

_SHARED_BUILD_CONTENT = None   # 惰性解析结果缓存：kb.import_registry._build_content 或 None
_SHARED_TRIED = False


def resolve_build_content():
    """取 kb/import_registry.py 的 content 构造句柄（唯一实现源，本工具不复制算法）。

    返回 callable 或 None（None = kb 包未就位，只有 __init__.py 无 store.py 等）。
    惰性 + 模块级缓存：--dry-run 不能因 kb 包缺失而失败（既有口径：dry-run 不依赖 kb/），
    故这里不抛异常，由调用方按模式处置——实跑 fail-closed（exit 1），dry-run 退化为
    text-only 清单预览（不落库，不影响任何幂等口径）。
    用 append 而非 insert(0)：测试桩可经 PYTHONPATH 前置注入假 kb 包。"""
    global _SHARED_BUILD_CONTENT, _SHARED_TRIED
    if not _SHARED_TRIED:
        _SHARED_TRIED = True
        ws = WS if WS not in sys.path else None
        if ws:
            sys.path.append(ws)
        try:
            from kb.import_registry import _build_content as fn  # noqa: E402
        except Exception:
            fn = None
        _SHARED_BUILD_CONTENT = fn
    return _SHARED_BUILD_CONTENT


def build_content(raw):
    """原子原文 → KB content（与 kb/import_registry.py:94 `_build_content` 逐字节同口径）。

    口径：text（缺 content）为主；body/preconditions/influence_hints/notes/summary 的
    字符串值收平去重后按序追加，空行 join。kb 包未就位返回 None（调用方按模式处置）。"""
    fn = resolve_build_content()
    return None if fn is None else fn(raw)


# ---------- 装配：registry 行 ⋈ 收割件 → KBStore.put_atom 入参 ----------

def assemble(reg_row, raw, content):
    """→ (atom_dict, fingerprint)。fingerprint 用于幂等跳过（不含 created_at/note）。
    状态按 STATUS_MAP 从 registry 状态映射：verified→verified、candidate→candidate。
    registry 的 rejected 无 KB 对应态，调用方已先行跳过，这里不允许把候选层标成 verified。
    content 为必传入参（由 build_content()/resolve_build_content() 统一构造）：历史上这里
    直接写 text-only，与 kb/import_registry.py 的拼平口径不一致，同 id 两入口混跑会让库内
    content 来回翻（冲刺批2 第一步修掉）；禁止在本函数内再实现一份 content 算法。"""
    cid, corpus, status, created_at, note = reg_row
    src = raw.get("source") or {}
    task = src.get("task") or ""
    sandbox = src.get("sandbox") or (raw.get("extractor") or {}).get("sandbox") or ""
    attrs = {
        "kind": raw.get("kind") or "",
        "body": raw.get("body") if isinstance(raw.get("body"), dict) else {},
        "source": {
            "file": src.get("file") or "",
            "locator": src.get("locator") or "",
            "quote": src.get("quote") or "",
            "evidence_sha256": src.get("evidence_sha256") or "",
            "task": task,
            "sandbox": sandbox,
        },
        "relations": raw.get("relations") if isinstance(raw.get("relations"), list) else [],
        "extractor": raw.get("extractor") if isinstance(raw.get("extractor"), dict) else {},
        "harvested_at": raw.get("harvested_at") or "",
        "registry_note": note or "",
        "registry_admitted_at": created_at or "",
    }
    atom = {
        "id": cid,
        "content": content,
        "source_corpus": corpus or "",
        "paper": parse_paper(task, cid, raw.get("paper") or ""),
        "status": STATUS_MAP.get(status, "candidate"),
        "created_at": created_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "attrs": attrs,
    }
    fp = hashlib.sha256(json.dumps(
        {k: atom[k] for k in ("id", "content", "source_corpus", "paper", "status", "attrs")},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return atom, fp


def preview(text, n=48):
    t = (text or "").replace("\n", " ")
    return t if len(t) <= n else t[:n] + "…"


# ---------- 输出侧：kb/ 知识库 ----------

def load_store(db_path):
    """惰性 import kb.store：--dry-run 不走到这里，故 kb 包未就位也能跑。
    用 append 而非 insert(0)：真实 kb/ 包在工作树根，同时允许测试桩经 PYTHONPATH 前置注入。"""
    ws = WS if WS not in sys.path else None
    if ws:
        sys.path.append(ws)
    try:
        from kb.store import KBStore  # noqa: E402
    except Exception as e:
        log(f"kb.store 不可用（{e}）——kb 包尚未就位；"
            f"若只想看清单与统计，请用 --dry-run（不依赖 kb/）")
        sys.exit(1)
    return KBStore(db_path)


def existing_fp(store, atom_id):
    """库里已有原子 → 内容指纹（与 assemble 同口径），没有则 None。"""
    cur = store.get_atom(atom_id)
    if not cur:
        return None
    same = {k: cur.get(k) for k in ("id", "content", "source_corpus", "paper", "status")}
    same["attrs"] = cur.get("attrs") if isinstance(cur.get("attrs"), dict) else {}
    return hashlib.sha256(json.dumps(same, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description="registry verified 原子 → kb/ 知识库（幂等，--dry-run 独立可用）")
    ap.add_argument("--registry", default=REGISTRY_DB, help="registry.db 路径（默认 kb-seed/registry.db）")
    ap.add_argument("--db", default=KB_DB, help="KB sqlite 路径（默认 kb/kb.db，由 kb.store 建库）")
    ap.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES,
                    help="收割件目录（含 *.jsonl）；默认 sandbox + paper-batch1/atoms + candidates-batch1 + POC")
    ap.add_argument("--status", default="verified", choices=["verified", "candidate", "all"],
                    help="导哪一层（默认 verified；candidate=候选层；all=两者，registry 的 rejected 无 KB 对应态故跳过）")
    ap.add_argument("--dry-run", action="store_true", help="只读 registry+收割件，不建/不写 kb/")
    ap.add_argument("--allow-unresolved", action="store_true",
                    help="收割件里找不到原文的 id 只警告不失败（默认失败，退出码 4）")
    ap.add_argument("--out", default="", help="把摘要 JSON 另写一份到该路径（给机器门/复核用）")
    ap.add_argument("--quiet", action="store_true", help="不打逐条清单（仍打统计与末行 JSON）")
    a = ap.parse_args()

    statuses = ["verified"] if a.status == "verified" else \
               (["candidate"] if a.status == "candidate" else ["verified", "candidate"])
    # content 口径统一（冲刺批2 第一步）：唯一实现源是 kb/import_registry.py 的
    # _build_content。实跑模式取不到该句柄一律 fail-closed（宁可不导，也不许写回
    # text-only 的旧口径）；--dry-run 不依赖 kb/（既有口径），退化为 text-only 清单预览。
    shared = resolve_build_content()
    if shared is None:
        if a.dry_run:
            log("kb.import_registry 不可用：dry-run 清单按 text-only 预览（不落库）")
        else:
            log("kb.import_registry 不可用——kb 包尚未就位，无法按统一口径构造 content；"
                "若只想看清单与统计，请用 --dry-run（不依赖 kb/）")
            return 1
    try:
        rows = registry_rows(a.registry, statuses)
    except Exception as e:
        log(f"registry 读取失败: {e}")
        return 2
    counts = registry_all_status_counts(a.registry)
    log(f"registry {a.registry}：全量 {counts}，本次取 status in {statuses} → {len(rows)} 行")

    files = source_files(a.sources)
    log(f"收割件 {len(files)} 个 JSONL：{[os.path.basename(os.path.dirname(f)) + '/' + os.path.basename(f) for f in files[:3]]}…")
    idx, dup, bad_lines = build_index(files)
    log(f"收割件索引 {len(idx)} 个原子 id（重复 id 跳过 {dup}，坏行 {bad_lines}）")

    plan, unresolved, skipped_rejected = [], [], 0
    for r in rows:
        cid, corpus, status, _created, _note = r
        raw = idx.get(cid)
        if raw is None:
            unresolved.append({"id": cid, "source_corpus": corpus, "registry_status": status})
            continue
        if status == "rejected":
            skipped_rejected += 1  # KB 无 rejected 对应态，如实跳过
            continue
        content = shared(raw) if shared else (raw.get("text") or "").strip()
        atom, fp = assemble(r, raw, content)
        plan.append({"atom": atom, "fp": fp})

    # 统计
    by_corpus, by_paper = {}, {}
    for p in plan:
        by_corpus[p["atom"]["source_corpus"]] = by_corpus.get(p["atom"]["source_corpus"], 0) + 1
        if p["atom"]["paper"]:
            by_paper[p["atom"]["paper"]] = by_paper.get(p["atom"]["paper"], 0) + 1
    no_quote = sum(1 for p in plan if not p["atom"]["attrs"]["source"]["quote"])
    no_paper = sum(1 for p in plan if not p["atom"]["paper"])

    summary = {
        "mode": "dry-run" if a.dry_run else "import",
        "registry": a.registry, "kb_db": None if a.dry_run else a.db,
        "registry_status_counts": counts, "selected_status": statuses,
        "registry_selected": len(rows),
        "harvest_files": len(files), "harvest_atom_ids": len(idx),
        "to_import": len(plan), "unresolved": len(unresolved),
        "skipped_rejected_no_kb_status": skipped_rejected,
        "duplicate_ids_in_harvest": dup, "bad_lines": bad_lines,
        "atoms_without_quote": no_quote, "atoms_without_paper": no_paper,
        "by_source_corpus": by_corpus, "distinct_papers": len(by_paper),
        "new": 0, "updated": 0, "unchanged": 0, "provenance_events": 0,
        # 注意：摘要 JSON 不含耗时等漂移字段——判据要求「两次运行输出一致（幂等）」，
        # 耗时只进人类可读日志行（log()），不进 JSON，保证同输入下末行逐字节相同。
    }

    if not a.quiet:
        log(f"将导入 {len(plan)} 条（按语料 {by_corpus}；覆盖论文 {len(by_paper)} 篇）")
        for p in plan:
            at = p["atom"]
            print(f"  {at['id']} | {at['source_corpus']} | {at['paper'] or '-'} | "
                  f"{at['attrs']['kind'] or '-'} | {preview(at['content'])}", flush=True)

    if unresolved:
        for u in unresolved[:20]:
            log(f"未解析原文（registry 有、收割件无）: {u['id']} [{u['source_corpus']}/{u['registry_status']}]")
        if len(unresolved) > 20:
            log(f"…另有 {len(unresolved) - 20} 条未解析")
        if not a.allow_unresolved:
            log(f"unresolved={len(unresolved)} > 0：按 fail-closed 记失败（--allow-unresolved 可降级为警告）")
            print(json.dumps(summary, ensure_ascii=False))
            return 4

    if a.dry_run:
        log(f"dry-run 完成：未建/未写 {a.db}（kb 包是否就位不影响本模式）")
        print(json.dumps(summary, ensure_ascii=False))
        if a.out:
            json.dump(summary, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return 0

    store = load_store(a.db)
    for p in plan:
        at, fp = p["atom"], p["fp"]
        cur = existing_fp(store, at["id"])
        if cur == fp:
            summary["unchanged"] += 1
            continue
        try:
            got = store.put_atom(at)
        except Exception as e:
            log(f"put_atom 失败 {at['id']}: {e}")
            summary.setdefault("errors", []).append({"id": at["id"], "error": str(e)[:120]})
            continue
        if got not in (None, at["id"]):
            log(f"put_atom 返回异常 {at['id']} -> {got!r}（契约：按 id upsert 返回该 id）")
            summary.setdefault("errors", []).append({"id": at["id"], "error": f"put_atom 返回 {got!r}"})
            continue
        if cur is None:
            summary["new"] += 1
        else:
            summary["updated"] += 1
        try:
            if store.record_provenance(at["id"], "kb_ingest", {
                "source_corpus": at["source_corpus"], "paper": at["paper"],
                "registry": os.path.abspath(a.registry),
                "registry_admitted_at": at["created_at"],
                "registry_note": at["attrs"]["registry_note"],
                "quote_sha256": at["attrs"]["source"]["evidence_sha256"],
                "content_sha256": fp[:16], "tool": "tools/kb-ingest.py"}):
                summary["provenance_events"] += 1
        except Exception as e:
            log(f"record_provenance 失败 {at['id']}: {e}")
    try:
        summary["kb_stats"] = store.stats()
    except Exception as e:
        summary["kb_stats"] = {"error": str(e)[:120]}
    log(f"导入完成：new={summary['new']} updated={summary['updated']} "
        f"unchanged={summary['unchanged']} unresolved={summary['unresolved']} → {a.db}")
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        json.dump(summary, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if not summary.get("errors") else 5


if __name__ == "__main__":
    sys.exit(main())
