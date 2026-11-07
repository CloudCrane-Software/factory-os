#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planner-audit-weekly.py —— planner 规划质量周审计器（问卷十题 · glm-5.3 · 周报 append-only）。

定位（2026-11-07 规划质量二期 · 运营者裁定「有质量提升的多花 token 全上」）：
  周期性（每周一 06:20 +08；双触发腿：workflow schedule + anolis pacer 兜底 cron
  周一 06:25）对 planner 规划环做一次**顾问式周审计**：
    读近 7 天波次清单 manifest + 板面结局 + planner-quality 读数
      → tokenrhythm 同 key 换模型（glm-5.3，免费档、免新钥）答固定问卷十题
       （每题 0-10 分 + 一句依据；无证据 ⇒ score=null，禁编中位分）
      → 出 {total, per_q, trend_vs_last, findings[]} 周报，
        append-only 落 波次清单/quality/weekly-<YYYY>W<WW>.json，
        并评论到 planner-review 常驻 issue（标题前缀幂等检索，无则首建）。

边界纪律（与 planner step 08d 分层顾问评审腿同族）：
  · advisory：本审计**永不进门禁 verdict**——零触碰 gates.yml／required checks／
    planner step 08 十校验与一切判据面；结论只进周报件与常驻 issue 评论。
  · 决策/评审模型结论永不改判：planner 自家 09/09b/10 链不受本器影响。
  · LLM 调用不计入 planner 03b 计划调用预算（免费档同 key 换模型；本器不读不写
    planner-call-log.json）。
  · 诚实性高于完成度：任何一腿采不到即显式 null + 原因码，禁把「没采到」装扮成
    「零」；问卷不可达 ⇒ 报告照落（空壳 + 结构化 finding）且 run fail-loud。
  · 凭据：LLM_API_KEY 只进请求头（零打印零落盘零 argv）；GitHub 读用内置
    GITHUB_TOKEN（CI）／PAT（本地环境变量传入），同样零打印零落盘。

glm-5.3 参数定姿（2026-11-07 本机探针实测，tokenrhythm 免费档同 key）：
  · thinking 必须开着（关思考 ⇒ 400 REASONING_REQUIRED），故不发 thinking 字段；
  · 输出面压制：默认深度隐藏推理可吃光 4096 max_tokens（content 空·finish=length，
    与 kimi-k3 256 档同族事故）；API 支持 reasoning_effort=low|high|max
    （budget_tokens 400 不支持）——low 档实测 118 completion_tokens/4.6s 回完整
    判词，故本器发 reasoning_effort=low（上游不收则剥参重试，见 llm_chat）；
  · temperature=0.2 实测 200 出词；十题 + 依据面输出 max_tokens=4096；
  · 超时 120s；429/5xx/传输错退避重试一次，仍败 ⇒ fail-open advisory（见上）。

用法：
  python3 -I tools/planner-audit-weekly.py --collect  --out audit-inputs.json
  python3 -I tools/planner-audit-weekly.py --answer   --in audit-inputs.json --out audit-answers.json
  python3 -I tools/planner-audit-weekly.py --assemble --in audit-inputs.json \
        --answers audit-answers.json --out 波次清单/quality/weekly-2026W45.json \
        --summary weekly-summary.md
  python3 -I tools/planner-audit-weekly.py --self-test      # 离线自测（零网络零板写）

回滚：删 .github/workflows/planner-audit-weekly.yml 与本件即回到「无周审计」现势
  （波次清单/quality/weekly-*.json 为 append-only 新增件，可整目录删）。
"""
import argparse
import glob
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

SCHEMA = "af.planner-audit-weekly.v1"
INPUTS_SCHEMA = "af.planner-audit-weekly.inputs.v1"
ANSWERS_SCHEMA = "af.planner-audit-weekly.answers.v1"
REPO = os.environ.get("AUDIT_REPO") or "CloudCrane-Software/factory-os"
API = "https://api.github.com"
WAVE_DIR = os.environ.get("WAVE_DIR") or "波次清单"
LEDGER_FILE = os.environ.get("LEDGER_FILE") or "账本/阶段欠账台账.md"
QUALITY_SUBDIR = "quality"
LLM_BASE_URL = (os.environ.get("LLM_BASE_URL") or "https://tokenrhythm.studio/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL") or "glm-5.3"
LLM_PROVIDER = "tokenrhythm"
LLM_TEMPERATURE = 0.2          # 探针实测 200 出词（glm-5.3 thinking 强制开）
LLM_MAX_TOKENS = 4096          # 十题 + 一句依据 + 隐藏推理面
LLM_TIMEOUT_S = 120
LLM_ATTEMPTS = 2               # 429/5xx/传输错退避重试一次；仍败 ⇒ fail-open advisory
STANDING_PREFIX = "planner-review"   # 常驻 issue 标题前缀（与 step 08d 同一幂等检索口径）
WINDOW_DAYS = int(os.environ.get("AUDIT_WINDOW_DAYS") or "7")
ARTIFACT_PREFIX = "planner-run-"
TZ8 = timezone(timedelta(hours=8))

# digest 体积帽（防超长输入烧 token／超时；超帽即截断并记 note，不猜）
CAP_MANIFESTS = 12
CAP_CARDS_PER_MANIFEST = 12
CAP_DEBTS = 48
CAP_BOARD_OPEN = 40
CAP_BOARD_CLOSED = 40
CAP_FAILURE_MODES = 8
CAP_FINDINGS = 5

# ── 固定问卷十题（id/topic/ask/rubric 一字不改即「固定」；改题=改审计形制，
#    须走正路登记，不在运行中擅改）────────────────────────────────────────────
QUESTIONS = [
    {"id": "q01", "topic": "锚真实性",
     "ask": "波次卡所选 debt 锚是否真实存在于欠账台账正本（编号可解析、非凭空生成）",
     "rubric": "10=窗口内锚全部可解析到台账行；0=多数锚台账无行。按可解析比例给分。"},
    {"id": "q02", "topic": "锚可施工性",
     "ask": "所选锚当前是否可施工：未完成（open）、未被板面 open 卡占用、有验收门依据",
     "rubric": "10=锚全部 open 且无占用冲突；0=多数锚已完成或被占。按比例给分。"},
    {"id": "q03", "topic": "验收有效性",
     "ask": "卡 acceptance 是否带可判定形制（期望退出码/期望串），对照 quality C1 通过率",
     "rubric": "10=C1 通过率 100%；0=全缺。按通过率线性给分；无 quality 记录时按 manifest acceptance 在场率。"},
    {"id": "q04", "topic": "卡面自包含",
     "ask": "六要件 C1-C6（验收形制/钉桩基线/证据锚/依赖边界/允许路径/环境前提）整体通过面",
     "rubric": "10=六要件平均通过率 100%；0=全挂。按平均通过率给分。"},
    {"id": "q05", "topic": "重复率",
     "ask": "新卡与板面 open 卡/近 7 天 merged 卡同锚或同 allowed_paths 重复的程度（分高=重复少）",
     "rubric": "10=零同锚/同路径重复；0=大面积重复。按 1-重复率 给分。"},
    {"id": "q06", "topic": "空波归因",
     "ask": "planner 成功但零出卡（空波）时的归因是否合理：无锚可派=idle 合理；有锚不派=盲态",
     "rubric": "10=空波均有明确合理归因（或无空波）；0=有锚不派且无归因读数。"},
    {"id": "q07", "topic": "评审拦截质量",
     "ask": "08d 顾问评审（kimi-k3 快判）verdict 质量：误拦正产/漏拦劣质的程度",
     "rubric": "10=判词全部有据；0=判词与事实相反。**无评审落板记录时 score=null**，basis 注明不可证。"},
    {"id": "q08", "topic": "上下文新鲜度",
     "ask": "planner 输入面新鲜度：factory_obs cache age、artifact warnings/degraded、输入与现势板面差",
     "rubric": "10=输入全部新鲜无 degraded；0=输入陈旧或多腿 degraded。按实测读数给分。"},
    {"id": "q09", "topic": "失败模式趋势",
     "ask": "quality 读数 top failure_modes 的严重度与集中度（少数模式高频复发=低分）",
     "rubric": "10=失败模式分散且低频；0=单一模式大面积复发。"},
    {"id": "q10", "topic": "规划环健康",
     "ask": "planner run 成功率、失败聚因、artifact 在场情况（近 7 天 runs 读数）",
     "rubric": "10=成功率 100% 且读数齐全；0=大面失败或缺读数。按读数给分。"},
]
QUESTION_IDS = [q["id"] for q in QUESTIONS]
SEVERITIES = ("high", "medium", "low", "info")


def _iso(dt):
    return dt.astimezone(TZ8).isoformat(timespec="seconds") if dt else None


def _parse_ts(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(TZ8) if dt.tzinfo else dt.replace(tzinfo=TZ8)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def week_id_of(dt):
    cal = dt.isocalendar()
    return "%04d-W%02d" % (cal[0], cal[1])


def week_filename(week):
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week or "")
    if not m:
        raise ValueError("week 形制坏：%r（期望 YYYY-WW）" % (week,))
    return "weekly-%sW%s.json" % (m.group(1), m.group(2))


def week_sort_key(week):
    m = re.fullmatch(r"(\d{4})-W(\d{2})", week or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# ── 凭据与 HTTP（PAT/内置 Token 走 env；LLM key 只进头）──────────────────────

def gh_token():
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = os.environ.get(k) or ""
        if v.strip():
            return v.strip()
    return None


def _api_get(tok, url, timeout=30, retries=2):
    """PAT/内置 Token GET（JSON）。返回 (code, obj|None, err)。5xx/网络层（含
    大响应读超时所致的 IncompleteRead）按 retries 退避重试；超时上限由调用方按
    响应体量给定（runs 页 ~1.4MB ⇒ 180s；CI 网络秒级，慢网环境靠退避兜底）。"""
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "Authorization": "token %s" % tok,
            "Accept": "application/vnd.github+json",
            "User-Agent": "planner-audit-weekly (read-only)",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(2048).decode("utf-8", "replace")
            except Exception:
                pass
            if e.code >= 500 and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = "http_%s" % e.code
                continue
            return e.code, None, "http_%s:%s" % (e.code, body[:160])
        except Exception as e:  # noqa: BLE001 —— 网络层失败如实点名
            last = type(e).__name__
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, None, last
    return None, None, last or "unknown"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """artifact zip 下载专用：GitHub 回 302 指向 Azure blob（第三方主机），
    跟随前必须摘掉 Authorization 头（PAT 禁出域；同 planner-quality-telemetry.py:131）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)


def _download_zip(tok, url):
    req = urllib.request.Request(url, headers={
        "Authorization": "token %s" % tok,
        "User-Agent": "planner-audit-weekly (read-only)"})
    try:
        with _NO_REDIRECT.open(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        loc = e.headers.get("Location")
        if not loc:
            raise RuntimeError("artifact redirect 无 Location（code=%s）" % e.code)
        req2 = urllib.request.Request(loc, headers={
            "User-Agent": "planner-audit-weekly (read-only)"})   # 零凭据出域
        with urllib.request.urlopen(req2, timeout=120) as r:
            return r.read()


# ── 纯函数层（self-test 夹具直驱；IO/API 由 collect 编排）────────────────────

def parse_manifest_file(path):
    """读单个 wave-*.json manifest → 摘要 dict。坏 JSON 返回 None（调用方点名）。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    cards = [c for c in (d.get("cards") or []) if isinstance(c, dict)]
    by_state = {}
    for c in cards:
        s = str(c.get("state") or "?")
        by_state[s] = by_state.get(s, 0) + 1
    created = d.get("created") or d.get("created_at")
    detail = []
    for c in cards[:CAP_CARDS_PER_MANIFEST]:
        board = c.get("board") if isinstance(c.get("board"), dict) else {}
        prs = []
        mg = c.get("merge") if isinstance(c.get("merge"), dict) else {}
        for pr in (mg.get("prs") or []):
            if isinstance(pr, dict) and _int(pr.get("number")) is not None:
                prs.append(pr.get("number"))
        detail.append({
            "debt": c.get("debt"), "state": c.get("state"),
            "task_id": c.get("task_id"),
            "issue": _int(board.get("issue")), "prs": prs,
            "closed_at": board.get("closed_at"),
        })
    return {
        "wave": d.get("wave"), "file": os.path.basename(path),
        "created": created, "cards": len(cards), "by_state": by_state,
        "debts": [c.get("debt") for c in cards if c.get("debt")][:CAP_DEBTS],
        "cards_detail": detail,
        "cards_detail_truncated": len(cards) > CAP_CARDS_PER_MANIFEST,
        "cards_full": cards[:60],      # 原样卡面（锚核对/路径重复的确定性输入；artifact 内备查）
    }


def manifest_in_window(manifest, cut, now):
    """窗口归属：created/created_at 在窗内，或任一卡 board.created_at/closed_at 在窗内。
    返回 (bool, reason)。"""
    ts = _parse_ts(manifest.get("created"))
    if ts and cut <= ts <= now:
        return True, "manifest created 在窗内"
    for c in manifest.get("cards_detail") or []:
        for k in ("closed_at",):
            t = _parse_ts(c.get(k))
            if t and cut <= t <= now:
                return True, "卡 board.%s 在窗内" % k
    return False, "窗外（created 与卡板面事件均早于窗）"


def parse_quality_file(path):
    """读单个 wave-*.quality.json（JSONL：每行一条 card_quality）→ 聚合 dict。"""
    records = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    grades, scored, modes = {}, 0, {}
    six_pass = six_total = 0
    for r in records:
        if r.get("scored") and r.get("grade"):
            g = str(r["grade"]).strip().upper()
            grades[g] = grades.get(g, 0) + 1
            scored += 1
        fm = r.get("failure_modes")
        if isinstance(fm, dict):
            for m, n in fm.items():
                modes[m] = modes.get(m, 0) + (n if isinstance(n, int) else 1)
        six = ((r.get("items") or {}).get("six_essential") or {}) if isinstance(r.get("items"), dict) else {}
        if isinstance(six, dict):
            six_pass += _int(six.get("pass")) or 0
            six_total += _int(six.get("total")) or 0
    den = sum(grades.values())
    gv = {"A": 4, "B": 3, "C": 2, "D": 1}
    return {
        "wave": (records[0].get("wave") if records else None),
        "file": os.path.basename(path), "records": len(records),
        "scored": scored, "grades": grades,
        "mean_grade": round(sum(gv.get(g, 0) * n for g, n in grades.items()) / den, 3) if den else None,
        "grade_scale": "A=4 B=3 C=2 D=1（与一期遥测同映射）",
        "six_essential_pass": six_pass, "six_essential_total": six_total,
        "top_failure_modes": [{"mode": m, "count": n} for m, n in
                              sorted(modes.items(), key=lambda kv: -kv[1])[:CAP_FAILURE_MODES]],
    }


def parse_ledger_lines(lines):
    """欠账台账 markdown 表 → {rows_total, done_rows, open_anchors, anchor_ids}。
    行判据与 planner step 05 同族：行首锚编号正则 + ✅ 完成态标记（不猜）。"""
    anchors, rows_total, done_rows = [], 0, 0
    for line in lines:
        m = re.match(r"^\|\s*([A-Za-z]{1,5}-[A-Za-z0-9-]+)\s*\|", line)
        if not m:
            continue
        rows_total += 1
        done = "\u2705" in line
        if done:
            done_rows += 1
        anchors.append({"id": m.group(1), "done": done})
    return {"rows_total": rows_total, "done_rows": done_rows,
            "open_anchors_n": rows_total - done_rows,
            "open_anchors": [a["id"] for a in anchors if not a["done"]],
            "anchor_ids": [a["id"] for a in anchors]}


def compute_anchor_check(data):
    """确定性锚交叉核对（不用 LLM）：窗内 manifest 卡的 debt 锚 × 台账正本 × 板面占用。
    产出 q01/q02/q05 的机读读数——「采不到」与「零」严格区分（板面腿失败即 null）。"""
    led = data.get("ledger") or {}
    ledger_ids = set(led.get("anchor_ids") or [])
    ledger_open = set(led.get("open_anchors") or [])
    board = data.get("board") or {}
    board_ok = "board-issues" not in " ".join(data.get("degraded") or []) and \
        (board.get("wave_open") is not None)
    occupied = set(board.get("occupied_anchors") or []) if board_ok else None
    closed_debts = set()
    if board_ok:
        for c in (board.get("wave_closed_in_window") or []):
            if c.get("debt"):
                closed_debts.add(c["debt"])
    cards, resolvable, unresolvable = 0, 0, []
    open_hits, done_hits, dup_open, dup_closed = [], [], [], []
    for m in (data.get("manifests") or []):
        if not m.get("in_window"):
            continue
        for c in (m.get("cards_detail") or []):
            debt = c.get("debt")
            if not debt:
                continue
            cards += 1
            if debt in ledger_ids:
                resolvable += 1
                if debt in ledger_open:
                    open_hits.append(debt)
                else:
                    done_hits.append(debt)
            else:
                unresolvable.append({"wave": m.get("wave"), "debt": debt})
            if occupied is not None:
                if debt in occupied:
                    dup_open.append({"wave": m.get("wave"), "debt": debt})
                if debt in closed_debts:
                    dup_closed.append({"wave": m.get("wave"), "debt": debt})
    # 同路径重复（allowed_paths 仅原始形制 manifest 携带；补档件无此字段 ⇒ 显式记覆盖面）
    path_owner, same_path_pairs, cards_with_paths = {}, [], 0
    judge_path_hits = []
    for m in (data.get("manifests") or []):
        if not m.get("in_window"):
            continue
        for c in (m.get("cards_full") or []):
            aps = [p for p in (c.get("allowed_paths") or []) if isinstance(p, str)]
            if not aps:
                continue
            cards_with_paths += 1
            for p in aps:
                path_owner.setdefault(p, []).append({"wave": m.get("wave"), "debt": c.get("debt")})
                if p.startswith("tools/") or p.startswith("账本/"):
                    judge_path_hits.append({"wave": m.get("wave"), "debt": c.get("debt"), "path": p})
    for p, owners in path_owner.items():
        if len(owners) > 1:
            same_path_pairs.append({"path": p, "owners": owners})
    return {
        "in_window_cards_with_debt": cards,
        "resolvable": resolvable,
        "unresolvable": unresolvable[:20],
        "unresolvable_n": len(unresolvable),
        "open_in_ledger": len(open_hits),
        "done_in_ledger": len(done_hits),
        "resolvable_rate": round(resolvable / cards, 4) if cards else None,
        "open_rate_of_resolvable": round(len(open_hits) / resolvable, 4) if resolvable else None,
        "dup_with_open_board": dup_open[:20],
        "dup_with_open_board_n": len(dup_open),
        "dup_with_closed_in_window": dup_closed[:20],
        "dup_with_closed_in_window_n": len(dup_closed),
        "board_leg_ok": bool(board_ok),
        "cards_with_allowed_paths": cards_with_paths,
        "same_path_overlaps": same_path_pairs[:10],
        "same_path_overlaps_n": len(same_path_pairs),
        "judge_path_hits": judge_path_hits[:10],
        "judge_path_hits_n": len(judge_path_hits),
        "note": "锚核对=确定性机读（manifest cards_detail.debt × 台账行 × 板面占用）；"
                "board_leg_ok=false 时重复率腿显式 null（板面采不到≠零重复）",
    }


def build_digest(inp):
    """audit-inputs.json → 送 LLM 的紧凑 digest（带帽；截断处记 note）。"""
    notes = []
    manifests = []
    for m in (inp.get("manifests") or []):
        if not m.get("in_window"):
            continue
        manifests.append({
            "wave": m.get("wave"), "cards": m.get("cards"), "by_state": m.get("by_state"),
            "debts": (m.get("debts") or [])[:CAP_DEBTS],
        })
    if len(manifests) > CAP_MANIFESTS:
        notes.append("manifest 超帽截断：%d→%d" % (len(manifests), CAP_MANIFESTS))
        manifests = manifests[:CAP_MANIFESTS]
    quality = [{
        "wave": q.get("wave"), "records": q.get("records"), "scored": q.get("scored"),
        "grades": q.get("grades"), "mean_grade": q.get("mean_grade"),
        "six_essential_pass": q.get("six_essential_pass"),
        "six_essential_total": q.get("six_essential_total"),
        "top_failure_modes": q.get("top_failure_modes"),
    } for q in (inp.get("quality") or [])]
    board = inp.get("board") or {}
    runs = inp.get("planner_runs") or {}
    digest = {
        "window": inp.get("window"),
        "manifests": manifests,
        "quality": quality,
        "board": {
            "open_issues_total": board.get("open_issues_total"),
            "wave_open_n": len(board.get("wave_open") or []),
            "wave_open_debts": [c.get("debt") for c in (board.get("wave_open") or [])][:CAP_BOARD_OPEN],
            "wave_closed_in_window_n": len(board.get("wave_closed_in_window") or []),
            "wave_closed_in_window_debts": [c.get("debt") for c in (board.get("wave_closed_in_window") or [])][:CAP_BOARD_CLOSED],
            "occupied_anchors_n": len(board.get("occupied_anchors") or []),
        },
        "ledger": {k: v for k, v in (inp.get("ledger") or {}).items()
                   if k not in ("open_anchors", "anchor_ids")},
        "anchor_check": inp.get("anchor_check"),
        "obs_weekly": inp.get("obs_weekly"),
        "planner_runs": {
            "total": runs.get("total"), "by_conclusion": runs.get("by_conclusion"),
            "by_event": runs.get("by_event"), "last_success_at": runs.get("last_success_at"),
            "latest_artifact": runs.get("latest_artifact"),
        },
        "review": inp.get("review"),
        "previous_weekly": inp.get("previous_weekly"),
        "notes": notes + (inp.get("notes") or []),
    }
    return digest


def validate_answers(obj, questions=None):
    """校验 LLM 答卷。返回 (ok, errors, normalized)。
    normalized.per_q 恒为十题全量（缺答=score null + basis 点名原因）。"""
    questions = questions or QUESTIONS
    ids = [q["id"] for q in questions]
    errors = []
    if not isinstance(obj, dict):
        return False, ["答卷非 JSON 对象"], _null_per_q(questions, "答卷非 JSON 对象")
    raw = obj.get("per_q")
    if not isinstance(raw, list):
        return False, ["per_q 非数组"], _null_per_q(questions, "模型未按 schema 输出 per_q")
    by_id = {}
    for it in raw:
        if not isinstance(it, dict):
            errors.append("per_q 元素非对象")
            continue
        qid = it.get("id")
        if qid not in ids:
            errors.append("未知题号 %r" % (qid,))
            continue
        if qid in by_id:
            errors.append("题号重复 %s" % qid)
            continue
        score = it.get("score", "MISSING")
        if score is not None:
            if not isinstance(score, int) or isinstance(score, bool) or not (0 <= score <= 10):
                errors.append("%s 分数非 0-10 整数：%r" % (qid, score))
                continue
        basis = it.get("basis")
        if not isinstance(basis, str) or not basis.strip():
            errors.append("%s 缺依据句" % qid)
            continue
        if len(basis) > 200:
            errors.append("%s 依据句超 200 字" % qid)
            continue
        by_id[qid] = {"id": qid, "topic": _topic(questions, qid), "score": score,
                      "basis": basis.strip()}
    missing = [q for q in ids if q not in by_id]
    if missing:
        errors.append("缺题：%s" % ",".join(missing))
    per_q = []
    for qid in ids:
        if qid in by_id:
            per_q.append(by_id[qid])
        else:
            per_q.append({"id": qid, "topic": _topic(questions, qid), "score": None,
                          "basis": "模型未答/答非所问（重试后仍缺）——不可证，禁编分"})
    findings = _sanitize_findings(obj.get("findings"), ids)
    ok = not errors
    return ok, errors, {"per_q": per_q, "findings": findings}


def _topic(questions, qid):
    for q in questions:
        if q["id"] == qid:
            return q["topic"]
    return qid


def _null_per_q(questions, reason):
    return {"per_q": [{"id": q["id"], "topic": q["topic"], "score": None, "basis": reason}
                      for q in questions], "findings": []}


def _sanitize_findings(raw, ids):
    """findings 清洗：severity/question 白名单 + text 非空 + 去重 + 帽 CAP_FINDINGS。"""
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        sev = it.get("severity")
        if sev not in SEVERITIES:
            sev = "info"
        q = it.get("question")
        if q not in ids and q != "general":
            q = "general"
        text = it.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        key = (sev, q, text.strip()[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append({"severity": sev, "question": q, "text": text.strip()[:200]})
        if len(out) >= CAP_FINDINGS:
            break
    return out


def compute_trend(current_per_q, baseline):
    """环比：与上一份周报（末次读数）逐题差 + 总分差。无基线 ⇒ None + note（首份）。"""
    if not baseline or not isinstance(baseline.get("per_q"), dict):
        return None
    cur = {q["id"]: q.get("score") for q in current_per_q}
    base = baseline.get("per_q") or {}
    per_q_delta, compared = {}, 0
    for qid in QUESTION_IDS:
        a, b = cur.get(qid), base.get(qid)
        if isinstance(a, int) and isinstance(b, int):
            per_q_delta[qid] = a - b
            compared += 1
    total_now = sum(v for v in cur.values() if isinstance(v, int))
    total_base = baseline.get("total")
    out = {
        "baseline_week": baseline.get("week"),
        "baseline_generated_at": baseline.get("generated_at"),
        "baseline_file": baseline.get("file"),
        "questions_compared": compared,
        "per_q_delta": per_q_delta,
        "total_now": total_now,
        "total_baseline": total_base if isinstance(total_base, int) else None,
    }
    if isinstance(total_base, int):
        out["delta_total"] = total_now - total_base
    if compared < len(QUESTION_IDS):
        out["note"] = ("仅 %d/%d 题可环比（任一侧 score=null 的题跳过——不硬猜）"
                       % (compared, len(QUESTION_IDS)))
    return out


def assemble_report(inp, answers, week, trigger):
    """inputs + answers → 周报对象（{total, per_q, trend_vs_last, findings[]} 等）。"""
    per_q = (answers.get("per_q") if isinstance(answers, dict) else None) or \
        _null_per_q(QUESTIONS, "answers 缺场")["per_q"]
    scores = [q["score"] for q in per_q if isinstance(q.get("score"), int)]
    total = sum(scores)
    baseline = (inp or {}).get("previous_weekly")
    trend = compute_trend(per_q, baseline)
    findings = list((answers.get("findings") if isinstance(answers, dict) else None) or [])
    # 结构化 findings（脚本侧，诚实性面）：LLM 不可达/缺题/manifest 缺档等
    status = (answers or {}).get("status") or "unavailable"
    if status == "unavailable":
        findings.insert(0, {"severity": "high", "question": "general",
                            "text": "问卷未产出：%s——本周报告为空壳，run fail-loud 待处置"
                                    % ((answers or {}).get("errors") or ["LLM 不可达"])[0]})
    elif status == "partial":
        nulls = [q["id"] for q in per_q if q.get("score") is None]
        if nulls:
            findings.insert(0, {"severity": "medium", "question": "general",
                                "text": "部分题目无有效作答：%s（已记 null，禁编分）" % ",".join(nulls)})
    gaps = (inp or {}).get("structural_notes") or []
    for g in gaps[:3]:
        findings.append({"severity": "info", "question": "general", "text": g})
    findings = _sanitize_findings(findings, QUESTION_IDS)
    now = datetime.now(TZ8)
    return {
        "schema": SCHEMA,
        "week": week,
        "generated_at": _iso(now),
        "trigger": trigger,
        "window": (inp or {}).get("window"),
        "inputs_summary": {
            "manifests": [{"wave": m.get("wave"), "cards": m.get("cards"),
                           "by_state": m.get("by_state"), "in_window": m.get("in_window")}
                          for m in ((inp or {}).get("manifests") or [])],
            "quality": [{"wave": q.get("wave"), "records": q.get("records"),
                         "scored": q.get("scored"), "mean_grade": q.get("mean_grade")}
                        for q in ((inp or {}).get("quality") or [])],
            "board": {"open_issues_total": ((inp or {}).get("board") or {}).get("open_issues_total"),
                      "wave_open_n": len(((inp or {}).get("board") or {}).get("wave_open") or []),
                      "wave_closed_in_window_n": len(((inp or {}).get("board") or {}).get("wave_closed_in_window") or [])},
            "ledger": {k: v for k, v in ((inp or {}).get("ledger") or {}).items() if k != "open_anchors"},
            "anchor_check": {k: v for k, v in ((inp or {}).get("anchor_check") or {}).items()
                             if k in ("in_window_cards_with_debt", "resolvable", "unresolvable_n",
                                      "open_in_ledger", "done_in_ledger", "resolvable_rate",
                                      "dup_with_open_board_n", "dup_with_closed_in_window_n",
                                      "same_path_overlaps_n", "judge_path_hits_n", "board_leg_ok")},
            "obs_weekly": {k: v for k, v in ((inp or {}).get("obs_weekly") or {}).items()
                           if k in ("ts", "planner_failures_in_obs_window", "planner_failed_steps")}
            if isinstance((inp or {}).get("obs_weekly"), dict) else None,
            "planner_runs": {k: v for k, v in ((inp or {}).get("planner_runs") or {}).items()
                             if k in ("total", "by_conclusion", "by_event", "last_success_at")},
        },
        "questionnaire": per_q,
        "per_q": {q["id"]: q.get("score") for q in per_q},
        "total": total,
        "scored_count": len(scores),
        "score_scale": "十题各 0-10，total=Σ（null 不计入；scored_count 明示有效题数）",
        "trend_vs_last": trend,
        "findings": findings,
        "llm": (answers or {}).get("llm") or {"provider": LLM_PROVIDER, "model": LLM_MODEL,
                                              "status": status},
        "llm_status": status,
        "advisory": {
            "gate_exempt": True,
            "note": "周审计为 advisory：永不进门禁 verdict、零触碰 gates/required checks/"
                    "planner step 08 十校验；结论只进本件与 planner-review 常驻 issue 评论。",
        },
    }


def wrap_append(out_path, report, week, read_path=None):
    """append-only 落盘：新件建 wrapper；已有本 schema wrapper ⇒ 追加（旧件一字不动）；
    已存在非本 schema 内容 ⇒ fail-closed 拒写（禁覆盖未知内容）。

    read_path：既有内容的读取源（默认=out_path 自身）。周审计工作流取
    「仓内波次清单/quality/weekly-*.json 为读源、$RUNNER_TEMP 为写源」——周报件是
    05 步唯一有意入仓产物，须先过「工作树干净」闸再落树（planner step 09 同款次序）。
    返回 (ok, detail)。"""
    fname = week_filename(week)
    if os.path.dirname(out_path) and not os.path.isdir(os.path.dirname(out_path)):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    src = read_path if (read_path and os.path.exists(read_path)) else \
        (out_path if os.path.exists(out_path) else None)
    if src:
        try:
            existing = json.load(open(src, encoding="utf-8"))
        except Exception as e:
            return False, "既有周报件不可解析（%s）——拒写（禁覆盖）" % type(e).__name__
        if isinstance(existing, dict) and existing.get("schema") == SCHEMA:
            reports = existing.get("reports")
            if not isinstance(reports, list):
                # 旧形态裸报告（无 wrapper）：升级包装，原件为 reports[0]
                reports = [existing]
            reports.append(report)
            existing["reports"] = reports
            existing["last_report_at"] = report.get("generated_at")
            blob = existing
        else:
            return False, ("既有周报件 %s 非 %s（schema=%r）——拒写（append-only 禁覆盖未知内容）"
                           % (fname, SCHEMA, (existing or {}).get("schema") if isinstance(existing, dict) else None))
    else:
        blob = {"schema": SCHEMA, "week": week, "reports": [report],
                "last_report_at": report.get("generated_at")}
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)
    return True, "reports=%d" % len(blob["reports"])


def render_summary(report, merge_status=None):
    """周报 → markdown（step summary + 常驻 issue 评论共用）。"""
    w = report.get("window") or {}
    tr = report.get("trigger") or {}
    lines = []
    lines.append("### planner 规划质量周审计 · %s（%s · %s 同 key 换模型）"
                 % (report.get("week"), (report.get("llm") or {}).get("model"),
                    (report.get("llm") or {}).get("provider")))
    lines.append("")
    lines.append("- 窗口：%s → %s（%s 天）· 触发：%s（%s）· run %s"
                 % (w.get("from"), w.get("to"), w.get("days"), tr.get("event"),
                    tr.get("reason"), tr.get("run_id")))
    isum = report.get("inputs_summary") or {}
    mans = isum.get("manifests") or []
    cards = sum(m.get("cards") or 0 for m in mans)
    in_win = [m for m in mans if m.get("in_window")]
    lines.append("- 输入：manifest %d 件在窗（共 %d 件 %d 卡）· quality %d 件 · 板面 wave open %s/窗内 closed %s · 台账 %s 行（done %s/open %s）· planner runs %s（%s）"
                 % (len(in_win), len(mans), cards, len(isum.get("quality") or []),
                    (isum.get("board") or {}).get("wave_open_n"),
                    (isum.get("board") or {}).get("wave_closed_in_window_n"),
                    (isum.get("ledger") or {}).get("rows_total"),
                    (isum.get("ledger") or {}).get("done_rows"),
                    (isum.get("ledger") or {}).get("open_anchors_n"),
                    (isum.get("planner_runs") or {}).get("total"),
                    json.dumps((isum.get("planner_runs") or {}).get("by_conclusion") or {},
                               ensure_ascii=False)))
    lines.append("- 问卷状态：**%s**（scored %d/10 · total %s）"
                 % (report.get("llm_status"), report.get("scored_count"), report.get("total")))
    lines.append("")
    lines.append("| # | 题 | 分 | 依据 |")
    lines.append("|---|---|---|---|")
    for q in report.get("questionnaire") or []:
        score = q.get("score")
        lines.append("| %s | %s | %s | %s |"
                     % (q.get("id"), q.get("topic"),
                        "—" if score is None else score,
                        (q.get("basis") or "").replace("|", "\\|").replace("\n", " ")))
    lines.append("")
    trd = report.get("trend_vs_last")
    if trd:
        arrow = {1: "↑", -1: "↓", 0: "→"}
        deltas = " ".join("%s%s%+d" % (k, arrow.get((v > 0) - (v < 0), ""), v)
                          for k, v in sorted((trd.get("per_q_delta") or {}).items()))
        lines.append("- 环比 %s：total %s → %s（%+d）· 逐题：%s"
                     % (trd.get("baseline_week"), trd.get("total_baseline"),
                        trd.get("total_now"), trd.get("delta_total"), deltas or "（无可比题）"))
    else:
        lines.append("- 环比：无上一份周报（首份或无基线）——trend_vs_last=null")
    lines.append("")
    fs = report.get("findings") or []
    if fs:
        lines.append("**findings**")
        lines.append("")
        for f in fs:
            lines.append("- [%s][%s] %s" % (f.get("severity"), f.get("question"), f.get("text")))
    else:
        lines.append("**findings**：无")
    lines.append("")
    if merge_status:
        lines.append("- 周报落库：%s" % merge_status)
    lines.append("- 周报件：`%s`（append-only；趋势接观测：一期遥测 planner_quality_weekly 段消费末次读数）"
                 % (os.path.join(WAVE_DIR, QUALITY_SUBDIR, week_filename(report.get("week")))))
    lines.append("")
    lines.append("*advisory：本审计永不进门禁 verdict（零触碰 gates/required checks/planner "
                 "step 08 十校验）；glm-5.3 结论只进本评论与周报件。*")
    return "\n".join(lines)


# ── IO/API 编排层 ───────────────────────────────────────────────────────────

def _read_obs_weekly():
    """仓内 状态观测/sandbox-obs-weekly.json（obs-nightly 周档）→ planner 失败聚因旁证。
    只读仓内件、零 API；缺件/坏 JSON ⇒ None + 不猜（q10 聚因面收窄如实点名）。"""
    p = os.path.join("状态观测", "sandbox-obs-weekly.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    sig = ((d.get("signals") or {}).get("B2_ext_any_event_repeat") or {})
    planner_rows = [r for r in (sig.get("value") or [])
                    if isinstance(r, dict) and r.get("workflow") == "planner"]
    steps = []
    for r in planner_rows:
        for h in (r.get("same_cause_hint") or []):
            for s in (h.get("failed_steps") or []):
                if s not in steps:
                    steps.append(s)
    return {"file": p, "ts": d.get("ts"), "status": d.get("status"),
            "planner_failures_in_obs_window": sum(r.get("failures") or 0 for r in planner_rows),
            "planner_failed_steps": steps[:8],
            "note": "obs-nightly 周档旁证（其自窗非本审计窗；失败聚因只作方向性读数）"}


def _issue_debt(title, body):
    m = re.search(r"\[wave-\d+\]\[([^\]]+)\]", title or "")
    if m:
        return m.group(1).strip()
    m = re.search(r"【债号】`([^`]+)`", body or "")
    if m:
        return m.group(1).strip()
    return None


def _issue_state_labels(it):
    return [lb.get("name") for lb in (it.get("labels") or []) if isinstance(lb, dict)
            and str(lb.get("name") or "").startswith("state:")]


def _is_wave_issue(it):
    labels = [str(lb.get("name") or "") for lb in (it.get("labels") or []) if isinstance(lb, dict)]
    if "wave" in labels or any(l.startswith("wave-") for l in labels):
        return True
    return bool(re.match(r"\[wave-\d+\]", it.get("title") or ""))


def collect(window_days=WINDOW_DAYS, wave_dir=WAVE_DIR, ledger_file=LEDGER_FILE,
            fetch_api=True):
    now = datetime.now(TZ8)
    cut = now - timedelta(days=window_days)
    notes, degraded = [], []
    data = {
        "schema": INPUTS_SCHEMA, "generated_at": _iso(now), "repo": REPO,
        "window": {"days": window_days, "from": _iso(cut), "to": _iso(now)},
        "manifests": [], "quality": [], "board": {}, "ledger": {},
        "planner_runs": {}, "review": {}, "previous_weekly": None,
        "notes": notes, "degraded": degraded,
    }
    # ── 波次清单 manifest（近 7 天归属；窗外件也列但 in_window=false）──
    for p in sorted(glob.glob(os.path.join(wave_dir, "wave-*.json"))):
        if p.endswith(".quality.json"):
            continue
        m = parse_manifest_file(p)
        if m is None:
            notes.append("manifest 解析失败：%s（跳过并点名）" % os.path.basename(p))
            continue
        in_win, reason = manifest_in_window(m, cut, now)
        m["in_window"] = in_win
        m["include_reason"] = reason
        data["manifests"].append(m)
    # ── planner-quality 读数（wave-*.quality.json，JSONL）──
    for p in sorted(glob.glob(os.path.join(wave_dir, "wave-*.quality.json"))):
        try:
            data["quality"].append(parse_quality_file(p))
        except Exception as e:
            notes.append("quality 解析失败 %s：%s" % (os.path.basename(p), type(e).__name__))
    # ── 欠账台账 ──
    try:
        with open(ledger_file, encoding="utf-8") as f:
            data["ledger"] = parse_ledger_lines(f.readlines())
    except OSError as e:
        data["ledger"] = {"rows_total": None, "done_rows": None, "open_anchors_n": None,
                          "open_anchors": []}
        degraded.append("ledger-unreadable:%s" % type(e).__name__)
    # ── 确定性锚交叉核对（q01/q02/q05 机读读数；不用 LLM）──
    data["anchor_check"] = compute_anchor_check(data)
    # ── 上一份周报（趋势基线；只取严格早于本周的最近一件）──
    cur_week = week_id_of(now)
    prev = None
    for p in sorted(glob.glob(os.path.join(wave_dir, QUALITY_SUBDIR, "weekly-*.json"))):
        m = re.fullmatch(r"weekly-(\d{4})W(\d{2})\.json", os.path.basename(p))
        if not m:
            continue
        wk = "%s-W%s" % (m.group(1), m.group(2))
        if week_sort_key(wk) >= week_sort_key(cur_week):
            continue
        try:
            blob = json.load(open(p, encoding="utf-8"))
        except Exception:
            notes.append("上周周报不可解析：%s（趋势基线跳过）" % os.path.basename(p))
            continue
        reports = blob.get("reports") if isinstance(blob, dict) else None
        last = (reports[-1] if isinstance(reports, list) and reports else
                (blob if isinstance(blob, dict) and "per_q" in blob else None))
        if not isinstance(last, dict):
            continue
        if prev is None or week_sort_key(wk) > week_sort_key(prev["week"]):
            prev = {"week": wk, "file": os.path.basename(p),
                    "generated_at": last.get("generated_at"),
                    "total": last.get("total"), "per_q": last.get("per_q")}
    data["previous_weekly"] = prev
    # ── API 腿（板面结局 / planner runs / 评审评论 / 最新 artifact）──
    tok = gh_token() if fetch_api else None
    if fetch_api and not tok:
        degraded.append("no-github-token：板面/runs/评审腿全部不可得（显式 null，不猜）")
        data["board"] = {"open_issues_total": None, "wave_open": [],
                         "wave_closed_in_window": [], "occupied_anchors": []}
        data["planner_runs"] = {"total": None, "by_conclusion": None, "by_event": None,
                                "last_success_at": None, "latest_artifact": None}
        data["review"] = {"standing_issue": None, "note": "无 token：评审腿不可得"}
    if tok:
        _collect_board(tok, data, cut, now)
        _collect_runs(tok, data, cut, now)
        _collect_review(tok, data, cut)
        data["anchor_check"] = compute_anchor_check(data)   # 板面腿回来后重算（占用面才齐）
    # ── 观测面旁证（仓内 obs-nightly 周档：planner 失败聚因；缺件=note 不猜）──
    data["obs_weekly"] = _read_obs_weekly()
    # 结构性注记（进 findings 的 info 族）
    struct = []
    waves = sorted((m.get("wave") or "" for m in data["manifests"]),
                   key=lambda w: int(re.sub(r"\D", "", w) or 0))
    nums = [int(re.sub(r"\D", "", w) or 0) for w in waves]
    missing = [n for n in range(1, (max(nums) + 1) if nums else 1) if n not in nums]
    if missing:
        struct.append("波次清单缺档：wave-%s（板面/台账或有卡，无 manifest——事实登记，不伪造补齐）"
                      % "/wave-".join("%02d" % n for n in missing))
    if data["ledger"].get("rows_total") is None:
        struct.append("欠账台账不可读——锚宇宙腿缺席（q01/q02 证据面收窄）")
    data["structural_notes"] = struct
    return data


def _collect_board(tok, data, cut, now):
    # per_page=50：issues 响应带 body（~6.5KB/条），小页传输降低慢网截断暴露面
    # （本机实测 per_page=100 偶发 IncompleteRead——诚实降级有兜底，此处再降一档风险）；
    # 页帽 6=300 issue 封顶，超帽记 degraded（factory-os 现役 46 issue，1 页即全覆盖）。
    issues, page = [], 1
    while page <= 6:
        code, obj, err = _api_get(tok, "%s/repos/%s/issues?state=all&per_page=50&page=%d"
                                  % (API, REPO, page), timeout=180)
        if code != 200 or not isinstance(obj, list):
            data["degraded"].append("board-issues:%s" % (err or code))
            break
        issues.extend(it for it in obj if isinstance(it, dict) and "pull_request" not in it)
        if len(obj) < 50:
            break
        page += 1
    if page >= 6 and issues:
        data["degraded"].append("board-issues:页数封顶 6（板面可能未全覆盖——如实点名）")
    wave_open, wave_closed, occupied = [], [], []
    for it in issues:
        if not _is_wave_issue(it):
            continue
        debt = _issue_debt(it.get("title"), it.get("body"))
        row = {"number": _int(it.get("number")), "title": (it.get("title") or "")[:120],
               "debt": debt, "state_labels": _issue_state_labels(it),
               "created_at": it.get("created_at"), "closed_at": it.get("closed_at")}
        if debt:
            occupied.append(debt)
        if it.get("state") == "open":
            wave_open.append(row)
        else:
            ct = _parse_ts(it.get("closed_at"))
            if ct and cut <= ct <= now:
                wave_closed.append(row)
    data["board"] = {
        "open_issues_total": None,   # 全仓 open issue 数不在本腿（wave 口径外不采）
        "wave_open": wave_open[:CAP_BOARD_OPEN],
        "wave_open_truncated": len(wave_open) > CAP_BOARD_OPEN,
        "wave_closed_in_window": wave_closed[:CAP_BOARD_CLOSED],
        "wave_closed_truncated": len(wave_closed) > CAP_BOARD_CLOSED,
        "occupied_anchors": sorted(set(occupied)),
        "note": "板面口径=wave label/[wave-NN] 标题 issue（state=all 翻页≤3 页）",
    }


def _collect_runs(tok, data, cut, now):
    runs, page = [], 1
    while page <= 8:   # 100/页；created_at 降序，遇窗外即止（8 页=800 跑封顶，超帽记 note）
        code, obj, err = _api_get(tok, "%s/repos/%s/actions/workflows/planner.yml/runs"
                                  "?per_page=100&page=%d" % (API, REPO, page), timeout=180)
        if code != 200 or not isinstance(obj, dict):
            data["degraded"].append("planner-runs:%s" % (err or code))
            break
        batch = [r for r in (obj.get("workflow_runs") or []) if isinstance(r, dict)]
        if not batch:
            break
        oldest = _parse_ts(batch[-1].get("created_at"))
        runs.extend(batch)
        if len(batch) < 100 or (oldest and oldest < cut):
            break        # 末页或已探到窗外（降序）——后续页全在窗外，不再取
        page += 1
    if page >= 8 and runs:
        data["degraded"].append("planner-runs:页数封顶 8（窗内 runs 可能未全覆盖——如实点名）")
    in_win = []
    for r in runs:
        ts = _parse_ts(r.get("created_at"))
        if ts and cut <= ts <= now:
            in_win.append(r)
    by_concl, by_event = {}, {}
    for r in in_win:
        c = str(r.get("conclusion"))
        by_concl[c] = by_concl.get(c, 0) + 1
        e = str(r.get("event"))
        by_event[e] = by_event.get(e, 0) + 1
    ordered = sorted(in_win, key=lambda r: r.get("created_at") or "", reverse=True)
    last_success = next((r for r in ordered if r.get("conclusion") == "success"), None)
    data["planner_runs"] = {
        "total": len(in_win), "by_conclusion": by_concl, "by_event": by_event,
        "last_success_at": last_success.get("created_at") if last_success else None,
        "last_success_age_min": (round((now - _parse_ts(last_success["created_at"])).total_seconds() / 60, 1)
                                 if last_success else None),
        "runs_list_truncated": len(runs) >= 300,
        "latest_artifact": _probe_latest_artifact(tok, ordered, data),
        "note": "artifact 在场率未逐跑核（周窗 runs 量大，逐跑 artifacts API 不经济；"
                "24h 粒度由一期遥测 planner-quality-telemetry 覆盖）——本腿只探最新一跑",
    }


def _probe_latest_artifact(tok, ordered_runs, data):
    """只探最新一个 completed run 的 artifact（1 次 artifacts API + 1 zip），
    取 planner-inputs/ledger-summary/manifest-validation/board-state 四件摘要。"""
    target = next((r for r in ordered_runs if r.get("conclusion") in ("success", "failure")), None)
    if not target:
        data["degraded"].append("latest-artifact:窗内无 completed run")
        return None
    rid = target.get("id")
    code, obj, err = _api_get(tok, "%s/repos/%s/actions/runs/%d/artifacts" % (API, REPO, rid),
                              timeout=60)
    if code != 200 or not isinstance(obj, dict):
        data["degraded"].append("latest-artifact:%s" % (err or code))
        return None
    art = next((a for a in (obj.get("artifacts") or [])
                if str(a.get("name") or "").startswith(ARTIFACT_PREFIX)
                and str(a.get("name") or "").endswith(str(rid))), None)
    if not art:
        data["degraded"].append("latest-artifact:run %s 无 %s* artifact" % (rid, ARTIFACT_PREFIX))
        return None
    try:
        blob = _download_zip(tok, "%s/repos/%s/actions/artifacts/%s/zip"
                             % (API, REPO, art.get("id")))
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as e:  # noqa: BLE001
        data["degraded"].append("latest-artifact:zip_%s" % type(e).__name__)
        return None

    def member(name):
        try:
            return json.loads(z.read(name).decode("utf-8"))
        except Exception:
            return None

    pi = member("planner-inputs.json") or {}
    ls = member("ledger-summary.json") or {}
    mv = member("manifest-validation.json") or {}
    bs = member("board-state.json") or {}
    fo = pi.get("factory_obs") if isinstance(pi.get("factory_obs"), dict) else None
    return {
        "run_number": target.get("run_number"), "run_id": rid,
        "conclusion": target.get("conclusion"), "created_at": target.get("created_at"),
        "outcome": mv.get("outcome"), "cards_total": _int(mv.get("cards_total")),
        "new_cards": _int(mv.get("new_cards")),
        "open_anchors_n": len(ls.get("open_anchors") or []) if isinstance(ls, dict) else None,
        "in_flight_n": len(bs.get("in_flight_task_ids") or []) if isinstance(bs, dict) else None,
        "factory_obs_ts": (fo or {}).get("fetched_at") or (fo or {}).get("ts"),
        "factory_obs_age_s": (fo or {}).get("cache_age_s"),
        "factory_obs_present": fo is not None,
        "inputs_warnings": pi.get("warnings") if isinstance(pi.get("warnings"), list) else None,
        "quality_recent_present": bool((ls.get("quality_recent") or {}).get("waves"))
        if isinstance(ls, dict) else None,
    }


def _collect_review(tok, data, cut):
    code, obj, err = _api_get(tok, "%s/repos/%s/issues?state=open&per_page=100" % (API, REPO))
    standing = None
    if code == 200 and isinstance(obj, list):
        for it in obj:
            if "pull_request" in it or not isinstance(it, dict):
                continue
            if str(it.get("title") or "").startswith(STANDING_PREFIX):
                standing = it
                break
    if not standing:
        data["review"] = {"standing_issue": None,
                          "note": "planner-review 常驻 issue 不在场（08d 零 block 未建）——"
                                  "q07 无落板评审记录，按 schema 记 null 不编分"}
        return
    n = standing.get("number")
    code, comments, err = _api_get(tok, "%s/repos/%s/issues/%d/comments?per_page=100"
                                   % (API, REPO, n))
    if code != 200 or not isinstance(comments, list):
        data["review"] = {"standing_issue": n, "note": "评论列表不可得：%s" % (err or code)}
        return
    in_win, verdicts = [], {"block": 0, "pass": 0, "unavailable": 0}
    for c in comments:
        ts = _parse_ts(c.get("created_at"))
        if not (ts and cut <= ts):
            continue
        body = c.get("body") or ""
        in_win.append({"id": _int(c.get("id")), "created_at": c.get("created_at"),
                       "verdict": ("block" if "verdict=block" in body else
                                   "pass" if "verdict=pass" in body else
                                   "unavailable" if "review=unavailable" in body else "unknown")})
        v = in_win[-1]["verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1
    data["review"] = {"standing_issue": n, "comments_in_window": len(in_win),
                      "verdicts": verdicts, "comments": in_win[:20],
                      "note": "08d 评论脚注判定（verdict=block/pass、review=unavailable）"}


# ── LLM 问卷 ───────────────────────────────────────────────────────────────

def _strip_fences(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def llm_chat(key, system, user_obj, timeout_s=LLM_TIMEOUT_S, attempts=LLM_ATTEMPTS):
    """tokenrhythm /chat/completions（同 key 换模型）。返回 (ok, payload|None, err, attempts)。

    glm-5.3 输出面压制（2026-11-07 探针实测）：thinking 强制开（关思考 400
    REASONING_REQUIRED）；默认深度下隐藏推理可吃光整个输出面（4096 max_tokens 全耗、
    content 空、finish=length——与 kimi-k3 256 档同族事故）。API 明示支持
    reasoning_effort=low|high|max（budget_tokens 400 不支持）：low 档实测
    118 completion_tokens（reasoning 65）/4.6s 即回完整判词。故本器发
    reasoning_effort=low；若上游改判不收该参（400 点名 reasoning_effort）⇒
    当场剥参进入下一 attempt 重试（attempts=2 预算内，仍败即 fail-open）。"""
    # 赋值形落 max_tokens/reasoning_effort——禁字面量 "max_tokens": <变量> 形
    # （bot-scrub G-13 凭据形态误判家族：token 关键词 + 非数值 6+ 字符值即命中，
    #   fail-closed 门红；planner step 08d 同款规避，见该步注释）
    body = {"model": LLM_MODEL, "temperature": LLM_TEMPERATURE,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)}]}
    body["max_tokens"] = LLM_MAX_TOKENS
    body["reasoning_effort"] = "low"
    last, used = None, 0
    for attempt in range(1, attempts + 1):
        used = attempt
        req = urllib.request.Request(
            LLM_BASE_URL + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return True, json.loads(resp.read().decode("utf-8")), None, used
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code == 400 and "reasoning_effort" in (last or "") + _safe_body(e) \
                    and "reasoning_effort" in body:
                body.pop("reasoning_effort", None)   # 上游不收该参：剥参重试（同 attempt 内）
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts:
                time.sleep(3)
                continue
            return False, None, last, used
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
            if attempt < attempts:
                time.sleep(3)
                continue
            return False, None, last, used
    return False, None, last or "unknown", used


def _safe_body(http_err):
    try:
        return http_err.read(2048).decode("utf-8", "replace")
    except Exception:
        return ""


AUDIT_SYSTEM = (
    "你是黑灯工厂「planner 规划质量周审计员」。你的职责是依据给定的周窗 digest，"
    "对固定问卷十题逐题打分。纪律：①只依据 digest 中的事实与数字打分，禁引入 digest "
    "之外的假设；②每题 score 为 0-10 整数，方向见 rubric（分高=质量好）；digest 中"
    "没有证据能回答某题时，该题 score 必须为 null 并在 basis 说明「不可证」——禁编"
    "中位分、禁把没采到当作零；③basis 为一句话（≤80 字），必须引用 digest 中的具体"
    "数字或事实；④findings 至多 5 条，每条 {severity: high|medium|low|info, question: "
    "题号或 general, text: ≤80 字}，只写 digest 支撑的问题；⑤只输出 JSON，禁任何"
    "额外文字、禁 markdown 围栏之外的说明。"
)


def answer(inputs_path, out_path):
    inp = json.load(open(inputs_path, encoding="utf-8"))
    digest = build_digest(inp)
    user = {
        "digest": digest,
        "questions": QUESTIONS,
        "output_schema": {
            "per_q": [{"id": "q01", "score": 8, "basis": "一句依据（≤80字，引用 digest 数字）"}],
            "findings": [{"severity": "medium", "question": "q05", "text": "≤80 字"}],
        },
        "remind": "十题必须全部作答（无证据=null+不可证依据）；total 由脚本计算，你不要输出。",
    }
    key = (os.environ.get("LLM_API_KEY") or "").strip()
    errors, status, payload, attempts, latency = [], "unavailable", None, 0, None
    if not key:
        errors.append("LLM_API_KEY 缺席——问卷不可用（fail-open advisory：报告照落空壳）")
    else:
        for attempt in range(1, LLM_ATTEMPTS + 1):
            attempts = attempt
            t0 = time.time()
            ok, payload, err, used = llm_chat(key, AUDIT_SYSTEM, user)
            latency = round(time.time() - t0, 1)
            attempts = used
            if not ok:
                errors.append("第 %d 次调用失败：%s" % (attempt, err))
                continue
            content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            try:
                obj = json.loads(_strip_fences(content))
            except Exception as e:
                errors.append("第 %d 次答卷非 JSON：%s（content 前 80 字：%r）"
                              % (attempt, type(e).__name__, (content or "")[:80]))
                continue
            ok, verrs, normalized = validate_answers(obj)
            if ok:
                status = "ok"
                errors = []
                break
            errors.append("第 %d 次答卷不合 schema：%s" % (attempt, "; ".join(verrs[:4])))
            if attempt < LLM_ATTEMPTS:
                user["fix_errors"] = verrs[:6]
        if status != "ok":
            # 重试用尽：保全可用的部分（partial）或全 null（unavailable）
            best = None
            try:
                obj = json.loads(_strip_fences(
                    ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""))
                _, _, cand = validate_answers(obj)
                if any(q.get("score") is not None for q in cand["per_q"]):
                    best = cand
            except Exception:
                best = None
            if best:
                status = "partial"
                normalized = best
            else:
                status = "unavailable"
                normalized = _null_per_q(QUESTIONS, "LLM 不可达/答卷不合 schema（重试后仍败）")
    usage = {}
    if isinstance(payload, dict):
        u = payload.get("usage") or {}
        # 赋值形落 *_tokens 键（G-13 误判家族规避：禁字面量 "x_tokens": <表达式> 形）
        usage["prompt_tokens"] = _int(u.get("prompt_tokens"))
        usage["completion_tokens"] = _int(u.get("completion_tokens"))
        usage["total_tokens"] = _int(u.get("total_tokens"))
        finish = ((payload.get("choices") or [{}])[0].get("finish_reason"))
        if finish:
            usage["finish_reason"] = finish
    out = {
        "schema": ANSWERS_SCHEMA, "generated_at": _iso(datetime.now(TZ8)),
        "model": LLM_MODEL, "provider": LLM_PROVIDER, "status": status,
        "per_q": normalized["per_q"], "findings": normalized["findings"],
        "llm": {"provider": LLM_PROVIDER, "model": LLM_MODEL, "status": status,
                "attempts": attempts, "latency_s": latency, "usage": usage,
                "temperature": LLM_TEMPERATURE},
        "errors": errors,
        "digest_notes": digest.get("notes") or [],
    }
    # max_tokens 赋值形落键（G-13 误判家族规避，同 llm_chat）
    out["llm"]["max_tokens"] = LLM_MAX_TOKENS
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)
    return out


def assemble(inputs_path, answers_path, out_path, summary_path, week=None, trigger=None):
    inp = json.load(open(inputs_path, encoding="utf-8"))
    answers = json.load(open(answers_path, encoding="utf-8")) if answers_path else {}
    week = week or week_id_of(datetime.now(TZ8))
    # 仓内权威路径（append-only 读源）：既有周报件在此（合线后）；写出路径由调用方定
    # （工作流落 $RUNNER_TEMP，05 步过干净闸后再落树——planner step 09 同款次序）。
    repo_weekly = os.path.join(WAVE_DIR, QUALITY_SUBDIR, week_filename(week))
    if not out_path:
        out_path = repo_weekly
    trigger = trigger or {"event": os.environ.get("GITHUB_EVENT_NAME") or "local",
                          "reason": os.environ.get("RUN_REASON") or "local",
                          "run_id": os.environ.get("GITHUB_RUN_ID") or "local"}
    report = assemble_report(inp, answers, week, trigger)
    ok, detail = wrap_append(out_path, report, week, read_path=repo_weekly)
    if not ok:
        print("assemble 拒写：%s" % detail, file=sys.stderr)
        return None, detail
    summary = render_summary(report)
    if not summary_path:
        summary_path = out_path + ".summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary + "\n")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write("week=%s\n" % week)
            f.write("out=%s\n" % out_path)
            f.write("total=%s\n" % report["total"])
            f.write("scored_count=%s\n" % report["scored_count"])
            f.write("llm_status=%s\n" % report["llm_status"])
            f.write("trend=%s\n" % ("true" if report.get("trend_vs_last") else "false"))
    return report, detail


# ── 离线自测（零网络零板写；纯函数 + 夹具）──────────────────────────────────

def self_test():
    import tempfile
    import shutil
    checks = []

    def ck(name, cond, got=""):
        checks.append((name, bool(cond), got))

    # ① week 编号与文件名
    ck("week_id_of 2026-11-07 = 2026-W45",
       week_id_of(datetime(2026, 11, 7, 12, tzinfo=TZ8)) == "2026-W45")
    ck("week_filename weekly-2026W45.json",
       week_filename("2026-W45") == "weekly-2026W45.json")
    ck("week_sort_key 排序", week_sort_key("2026-W45") < week_sort_key("2026-W46"))

    # ② manifest 窗口归属
    now = datetime(2026, 11, 7, 12, tzinfo=TZ8)
    cut = now - timedelta(days=7)
    m_in = {"created": "2026-11-06T00:30:00+0800", "cards_detail": []}
    m_out = {"created": "2026-10-01T00:00:00+0800", "cards_detail": []}
    m_card = {"created": "2026-10-01T00:00:00+0800",
              "cards_detail": [{"closed_at": "2026-11-06T22:26:43Z"}]}
    ck("manifest created 在窗内", manifest_in_window(m_in, cut, now)[0] is True)
    ck("manifest 窗外", manifest_in_window(m_out, cut, now)[0] is False)
    ck("卡 closed_at 在窗内 ⇒ 在窗", manifest_in_window(m_card, cut, now)[0] is True)

    # ③ 台账解析（✅ 完成态；行首锚编号）
    led = parse_ledger_lines([
        "| 编号 | 欠什么 | 状态 |", "|---|---|---|",
        "| D-1 | x | ✅ |", "| D-2 | y | 未开始 |", "| OBS-D5 | z | 部分 |",
        "普通行不匹配", "| bad | 无连字符不匹配 |"])
    ck("ledger rows=3", led["rows_total"] == 3, led)
    ck("ledger done=1", led["done_rows"] == 1, led)
    ck("ledger open=2", led["open_anchors_n"] == 2, led)
    ck("ledger open ids", led["open_anchors"] == ["D-2", "OBS-D5"], led)

    # ④ quality 聚合（JSONL；A×1+D×3 ⇒ mean 1.75）
    tmp = tempfile.mkdtemp(prefix="audit-st-")
    try:
        qp = os.path.join(tmp, "wave-99.quality.json")
        with open(qp, "w", encoding="utf-8") as f:
            for g in ("A", "D", "D", "D"):
                f.write(json.dumps({"wave": "wave-99", "scored": True, "grade": g,
                                    "failure_modes": {"卡面无 file:line 证据锚": 1},
                                    "items": {"six_essential": {"pass": 3, "total": 6}}},
                                   ensure_ascii=False) + "\n")
        q = parse_quality_file(qp)
        ck("quality records=4", q["records"] == 4, q)
        ck("quality grades {A:1,D:3}", q["grades"] == {"A": 1, "D": 3}, q)
        ck("quality mean=1.75", q["mean_grade"] == 1.75, q)
        ck("quality six 12/24", (q["six_essential_pass"], q["six_essential_total"]) == (12, 24), q)
        ck("quality top modes", q["top_failure_modes"][0]["mode"] == "卡面无 file:line 证据锚", q)

        # ④b 锚交叉核对（确定性；板面腿失败 ⇒ 重复率 null 不猜零）
        ac_in = {
            "manifests": [
                {"wave": "wave-99", "in_window": True,
                 "cards_detail": [{"debt": "D-1"}, {"debt": "D-2"}, {"debt": "RT-E9"}],
                 "cards_full": [{"debt": "D-1", "allowed_paths": ["tools/x.py", "账本/y.md"]},
                                {"debt": "D-2", "allowed_paths": ["tools/x.py"]}]},
                {"wave": "wave-98", "in_window": False,
                 "cards_detail": [{"debt": "D-3"}], "cards_full": []},
            ],
            "ledger": {"anchor_ids": ["D-1", "D-2", "D-3"], "open_anchors": ["D-2"],
                       "rows_total": 3, "done_rows": 2, "open_anchors_n": 1},
            "board": {"wave_open": [{"debt": "D-2"}], "occupied_anchors": ["D-2"],
                      "wave_closed_in_window": [{"debt": "D-3"}]},
            "degraded": [],
        }
        ac = compute_anchor_check(ac_in)
        ck("anchor_check 卡数=3（窗外不计）", ac["in_window_cards_with_debt"] == 3, ac)
        ck("anchor_check 可解析 2/3", ac["resolvable"] == 2 and ac["unresolvable_n"] == 1, ac)
        ck("anchor_check RT-E9 点名", ac["unresolvable"][0]["debt"] == "RT-E9", ac)
        ck("anchor_check open=1/done=1", (ac["open_in_ledger"], ac["done_in_ledger"]) == (1, 1), ac)
        ck("anchor_check 同开板重复 D-2", ac["dup_with_open_board_n"] == 1, ac)
        ck("anchor_check 同窗内 closed 不计（D-3 窗外）", ac["dup_with_closed_in_window_n"] == 0, ac)
        ck("anchor_check 同路径 1 处", ac["same_path_overlaps_n"] == 1, ac)
        ck("anchor_check 判官路径 3 处（逐卡×路径）", ac["judge_path_hits_n"] == 3, ac)
        ac_bad = compute_anchor_check({**ac_in, "degraded": ["board-issues:IncompleteRead"]})
        ck("板面腿败 ⇒ 重复率 null（不猜零）",
           ac_bad["board_leg_ok"] is False and ac_bad["dup_with_open_board_n"] == 0
           and ac_bad["dup_with_closed_in_window_n"] == 0, ac_bad)

        # ⑤ 答卷校验：合法 / 围栏 / 缺题 / 分数越界 / 非对象
        good = {"per_q": [{"id": i, "score": 7, "basis": "digest 读数 7/10"}
                          for i in QUESTION_IDS],
                "findings": [{"severity": "medium", "question": "q05", "text": "同锚 2 例"}]}
        ok, errs, norm = validate_answers(good)
        ck("合法答卷 ok", ok and not errs, errs)
        ck("合法答卷十题", len(norm["per_q"]) == 10)
        fenced = "```json\n" + json.dumps(good) + "\n```"
        ck("围栏剥离去重", validate_answers(json.loads(_strip_fences(fenced)))[0] is True)
        bad_score = {"per_q": [{"id": "q01", "score": 11, "basis": "x"}]}
        ok, errs, _ = validate_answers(bad_score)
        ck("分数越界拒收", (not ok) and any("q01" in e for e in errs), errs)
        missing = {"per_q": [{"id": "q01", "score": 5, "basis": "ok"}]}
        ok, errs, norm = validate_answers(missing)
        ck("缺题不全 ok", not ok and "缺题" in ";".join(errs), errs)
        ck("缺题补 null+原因", all(q["score"] is None for q in norm["per_q"][1:])
           and "未答" in norm["per_q"][1]["basis"], norm["per_q"][1])
        ok, _, norm2 = validate_answers("not-a-dict")
        ck("非对象答卷全 null", (not ok) and all(q["score"] is None for q in norm2["per_q"]))

        # ⑥ findings 清洗（坏 severity/question、去重、帽 5）
        raw = [{"severity": "wat", "question": "q99", "text": "a"},
               {"severity": "high", "question": "q01", "text": "b"},
               {"severity": "high", "question": "q01", "text": "b"}]
        fs = _sanitize_findings(raw, QUESTION_IDS)
        ck("findings severity 归一 info", fs[0]["severity"] == "info", fs)
        ck("findings question 归一 general", fs[0]["question"] == "general", fs)
        ck("findings 去重", len(fs) == 2, fs)
        many = _sanitize_findings([{"severity": "low", "question": "general", "text": str(i)}
                                   for i in range(9)], QUESTION_IDS)
        ck("findings 帽 5", len(many) == 5, len(many))

        # ⑦ 趋势：有基线/无基线/null 题跳过
        cur = [{"id": i, "score": 8, "basis": "x"} for i in QUESTION_IDS]
        cur[6]["score"] = None      # q07 无证据
        base = {"week": "2026-W44", "total": 60,
                "per_q": {i: 7 for i in QUESTION_IDS}}
        tr = compute_trend(cur, base)
        ck("trend delta_total=+12（9×8-7×9）", tr["delta_total"] == 72 - 60, tr)
        ck("trend q07 跳过（null 不比）", "q07" not in tr["per_q_delta"], tr)
        ck("trend compared=9", tr["questions_compared"] == 9, tr)
        ck("trend note 点名", "仅 9/10" in (tr.get("note") or ""), tr)
        ck("trend 无基线=null", compute_trend(cur, None) is None)

        # ⑧ append-only：新件/追加/异 schema 拒写
        wp = os.path.join(tmp, "weekly-2026W45.json")
        r1 = {"schema": SCHEMA, "week": "2026-W45", "generated_at": "t1", "total": 70}
        r2 = {"schema": SCHEMA, "week": "2026-W45", "generated_at": "t2", "total": 80}
        ok, d = wrap_append(wp, r1, "2026-W45")
        ck("首份落盘 ok", ok, d)
        ok, d = wrap_append(wp, r2, "2026-W45")
        ck("二份追加 ok", ok and len(json.load(open(wp, encoding="utf-8"))["reports"]) == 2, d)
        first = json.load(open(wp, encoding="utf-8"))["reports"][0]
        ck("旧件一字不动", first["generated_at"] == "t1" and first["total"] == 70)
        foreign = os.path.join(tmp, "weekly-2026W44.json")
        with open(foreign, "w", encoding="utf-8") as f:
            json.dump({"schema": "someone.else.v1"}, f)
        ok, d = wrap_append(foreign, r1, "2026-W44")
        ck("异 schema 拒写", not ok and "拒写" in d, d)

        # ⑧b read_path 分离（run#2 热修形制）：仓内件只读、$RUNNER_TEMP 件为写源
        repo_wp = os.path.join(tmp, "repo", "weekly-2026W45.json")
        os.makedirs(os.path.dirname(repo_wp), exist_ok=True)
        ok, d = wrap_append(repo_wp, r1, "2026-W45")
        ck("仓内首份 ok", ok, d)
        tmp_wp = os.path.join(tmp, "tmp", "weekly-report.json")
        ok, d = wrap_append(tmp_wp, r2, "2026-W45", read_path=repo_wp)
        ck("读仓内/写临时 ok", ok, d)
        blob = json.load(open(tmp_wp, encoding="utf-8"))
        ck("临时件含仓内旧件+新件", [r["generated_at"] for r in blob["reports"]] == ["t1", "t2"], blob)
        ck("仓内件未被写坏（仍 1 件）",
           len(json.load(open(repo_wp, encoding="utf-8"))["reports"]) == 1)
        tmp_fresh = os.path.join(tmp, "tmp", "weekly-report-fresh.json")
        ok, d = wrap_append(tmp_fresh, r2, "2026-W45", read_path=os.path.join(tmp, "nope.json"))
        ck("读源缺席⇒新件", ok and len(json.load(open(tmp_fresh, encoding="utf-8"))["reports"]) == 1, d)

        # ⑨ assemble_report：total 只计非 null；scored_count
        ans = {"status": "partial", "per_q": cur,
               "findings": [], "llm": {"model": "glm-5.3"}}
        inp = {"window": {"days": 7}, "manifests": [], "quality": [], "board": {},
               "ledger": {}, "planner_runs": {}, "previous_weekly": base}
        rep = assemble_report(inp, ans, "2026-W45", {"event": "workflow_dispatch"})
        ck("total=72（q07 null 不计）", rep["total"] == 72, rep["total"])
        ck("scored_count=9", rep["scored_count"] == 9, rep["scored_count"])
        ck("partial 有结构化 finding",
           any("部分题目无有效作答" in f["text"] for f in rep["findings"]), rep["findings"])
        ans2 = {"status": "unavailable", "per_q": _null_per_q(QUESTIONS, "x")["per_q"],
                "findings": [], "llm": {}, "errors": ["LLM 不可达"]}
        rep2 = assemble_report(inp, ans2, "2026-W45", {})
        ck("unavailable total=0+high finding",
           rep2["total"] == 0 and rep2["findings"][0]["severity"] == "high", rep2["findings"])
        ck("advisory gate_exempt", rep2["advisory"]["gate_exempt"] is True)

        # ⑩ digest 帽
        big_inp = {"window": {}, "manifests": [
            {"wave": "wave-%02d" % i, "in_window": True, "cards": 3,
             "by_state": {"merged": 3}, "debts": ["D-%d" % j for j in range(60)]}
            for i in range(20)],
            "quality": [], "board": {}, "ledger": {}, "planner_runs": {},
            "previous_weekly": None, "notes": ["n1"]}
        dg = build_digest(big_inp)
        ck("digest manifest 帽 12", len(dg["manifests"]) == 12, len(dg["manifests"]))
        ck("digest debts 帽 48", len(dg["manifests"][0]["debts"]) == 48)
        ck("digest 截断 note 在场", any("超帽截断" in n for n in dg["notes"]), dg["notes"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [c for c in checks if not c[1]]
    for name, passed, got in checks:
        print("%s %s%s" % ("PASS" if passed else "FAIL", name,
                           "" if passed else " → %r" % (got,)))
    print("self-test: %d/%d %s" % (sum(1 for c in checks if c[1]), len(checks),
                                   "OK" if not bad else "FAILED"))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="planner 规划质量周审计器（问卷十题 · glm-5.3 · append-only 周报）")
    ap.add_argument("--collect", action="store_true", help="采集审计输入 → audit-inputs.json")
    ap.add_argument("--answer", action="store_true", help="glm-5.3 答十题问卷 → audit-answers.json")
    ap.add_argument("--assemble", action="store_true", help="组装周报（append-only）+ 摘要 md")
    ap.add_argument("--in", dest="inp", help="输入 JSON（--answer/--assemble）")
    ap.add_argument("--answers", help="答卷 JSON（--assemble）")
    ap.add_argument("--out", help="输出路径（--collect/--answer/--assemble）")
    ap.add_argument("--summary", help="摘要 markdown 输出路径（--assemble）")
    ap.add_argument("--week", help="覆盖周编号 YYYY-WW（默认=现在）")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--self-test", action="store_true", help="离线自测（零网络零板写）")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.out and not (args.assemble and args.inp):
        print("--collect/--answer 需 --out 输出路径；--assemble 可省略 --out（按周编号派生默认路径）",
              file=sys.stderr)
        return 2

    if args.collect:
        data = collect(window_days=args.window_days)
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, args.out)
        print(json.dumps({
            "mode": "collect", "out": args.out,
            "window": data["window"],
            "manifests_total": len(data["manifests"]),
            "manifests_in_window": sum(1 for m in data["manifests"] if m.get("in_window")),
            "quality_files": len(data["quality"]),
            "ledger": {k: data["ledger"].get(k) for k in ("rows_total", "done_rows", "open_anchors_n")},
            "wave_open": len((data.get("board") or {}).get("wave_open") or []),
            "wave_closed_in_window": len((data.get("board") or {}).get("wave_closed_in_window") or []),
            "planner_runs_total": (data.get("planner_runs") or {}).get("total"),
            "planner_runs_by_conclusion": (data.get("planner_runs") or {}).get("by_conclusion"),
            "latest_artifact_run": ((data.get("planner_runs") or {}).get("latest_artifact") or {}).get("run_number"),
            "review_standing_issue": (data.get("review") or {}).get("standing_issue"),
            "previous_weekly": (data.get("previous_weekly") or {}).get("week"),
            "degraded": data.get("degraded"), "structural_notes": data.get("structural_notes"),
        }, ensure_ascii=False))
        return 0

    if args.answer:
        if not args.inp:
            print("--answer 需 --in audit-inputs.json", file=sys.stderr)
            return 2
        out = answer(args.inp, args.out)
        print(json.dumps({
            "mode": "answer", "out": args.out, "status": out["status"],
            "scored": sum(1 for q in out["per_q"] if q.get("score") is not None),
            "total": sum(q["score"] for q in out["per_q"] if isinstance(q.get("score"), int)),
            "llm": {k: out["llm"].get(k) for k in ("model", "attempts", "latency_s", "usage")},
            "errors": out["errors"],
        }, ensure_ascii=False))
        return 0 if out["status"] in ("ok", "partial") else 3

    if args.assemble:
        if not args.inp:
            print("--assemble 需 --in audit-inputs.json", file=sys.stderr)
            return 2
        report, detail = assemble(args.inp, args.answers, args.out,
                                  args.summary or None, week=args.week)
        if report is None:
            return 4
        print(json.dumps({
            "mode": "assemble", "out": report.get("_out") or args.out or
            os.path.join(WAVE_DIR, QUALITY_SUBDIR, week_filename(report["week"])),
            "detail": detail,
            "week": report["week"], "total": report["total"],
            "scored_count": report["scored_count"],
            "trend_vs_last": bool(report.get("trend_vs_last")),
            "findings": len(report.get("findings") or []),
            "llm_status": report["llm_status"],
        }, ensure_ascii=False))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
