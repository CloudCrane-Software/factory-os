#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cb-five-segment-timing.py — 试跑全环五段计时自动采集器（D-121 · factory-os#128）。

定位（卡面 [试跑复盘][D-121] factory-os#128 · task_id=shipan-fupan-d121）
----
三跑计时口径不一（D-86 判分腿内 / D-107 沙箱环内 / D-117 五 milestone），复盘缺统一
口径。试跑全环计时规范 v1（工作区 30-工件/试跑全环计时规范-v1-20261107.md，§一）
已把五段定义落死：T0 建卡→T1 派发→T2 回收→T3 判分→T4 回卡。此前五段表全靠人工补
（规范 §四三跑表即人工补齐产物）。本件把它固化为一个采集 CLI——每跑自动出五段表
入 readings（卡面待办 2「零人工补表」），台账回填行直接引用机器五段表（待办 3）。

五段权威数据源（卡面待办 1 逐段，与规范 §一 一致）
----
  T0 建卡  issue created_at          ← GitHub API GET /issues/{n}（--fetch 实读或
                                        --issue-cache 留痕件；先落盘再解析·规范 §三.2）
  T1 派发  派发评论 id+created_at    ← 派发留痕（--t1-id/--t1-at 直给，source 记
                                        「cli:dispatch-trace」）＞ bench-watch 读数
                                        --dispatched-at 口（dispatched_at_utc）＞
                                        n/a（--t1-na 原因必填，等价点 --t1-equiv 参考列）
  T2 回收  交卷→收件核落定           ← bench-watch 读数（schema
                                        af.cb-dispatch.bench-watch.v1：末卷
                                        chosen.created → collected_at_utc）；
                                        早于 bench-watch 落地的跑可用
                                        --t2-start-at/--t2-end-at 留痕转引，或
                                        --t2-na 原因必填
  T3 判分  判分腿起→verdict 落盘     ← judge.json mtime 实读（终点；os.stat 机读，
                                        禁从 trace 转抄·规范 §三.1）；判分腿起点
                                        --judge-start-at 可选留痕转引，缺席自动
                                        n/a+原因；跑未判分用 --t3-na
  T4 回卡  回执评论 id+created_at    ← GitHub API comments 实读（规范 §三.3：以
                                        201 评论 created_at 为准，不以自述为准；
                                        marker「判分回卡」取末条或 --t4-id 显式）；
                                        未回卡用 --t4-na

跑型映射（规范 §二）：--run-type A（harness 自工自判）/ B（模拟沙箱+径B代交）/
C（cnb 真沙箱+径B）。A/B 的 T1（A 并 T2）按规范应记 n/a+原因、等价点入参考列——
给时刻属口径漂移，读数 warnings[] 点名（不拒卷：规范 §二总规则是 n/a 段必须写
原因，n/a+原因对任何段合法）。

输出
----
  --out  读数 JSON（schema=af.five-segment-timing.reading.v1）：segments T0-T4
         （全段有时点或 n/a+原因·卡面验收）、intervals 五段段间指标、bench_watch
         对接块（schema 校验+末卷指纹+baseline apply-check rc 参考列）、judge 块
         （verdict+sha256[:12]，全值禁入公开面）、ledger_row_draft（引用机器表，
         **零账本写入路径**——登记走 PR 流+owner 批，D-123 双正本/D-133 P3 同纪律）
  --md   五段表 markdown（规范 §四表格形制 + 数据源列 + +0800 展示列·规范 §三.1）

模式（三态互斥；缺省 --collect）
----
  --collect   采集出表（读本地件/夹具缓存；零网络零板写）
  --fetch     --collect 之上对 GitHub API 匿名实读 T0/T4（公开仓匿名可读；环境量
              GH_TOKEN/GITHUB_TOKEN 在场才带授权头，禁 argv 直传/禁回显/禁落盘）；
              原始响应先落盘（<out 目录>/issue-raw.json、comments-raw.json）再解析
              （规范 §三.2）；只读 GET，零板写
  --selftest  夹具自测（零网络零板写零凭据）

凭据与公开面纪律
----
  零凭据形态（卡面验收）：产出（readings/md/台账草案）写盘前过 scrub 预检
  （凭据形态子集，同 tools/cnb-verdict-reply.py:94-108 形制；全量树扫归 gates
  bot-scrub 剖面），命中即拒写 fail-closed、匹配原文永不进输出。
  判官件/判据件零改动（卡面「本卡不做什么」）：本件只读 judge.json 的 mtime 与
  公开安全字段（verdict/sha 前 12 位/计数），不写不判不碰 swev-judge*。

同族参考件（只读，禁改）：tools/cb-dispatch.py bench-watch 读数 schema
af.cb-dispatch.bench-watch.v1（本件消费端，schema 不符即拒收 rc=2）；
tools/cnb-verdict-reply.py:309-310（「五段计时采集归 D-121」交接口，其 --timeline
可承接本件 ledger_row_draft）；tools/cb-bench-dispatch.py:337-340（静默窗同源口径注）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
GH_API = "https://api.github.com"
DEFAULT_REPO = "CloudCrane-Software/factory-os"
READING_SCHEMA = "af.five-segment-timing.reading.v1"
BENCH_WATCH_SCHEMA = "af.cb-dispatch.bench-watch.v1"   # 消费端对接口（禁改生产端）
DEFAULT_MARKER = "判分回卡"
SPEC_REF = "30-工件/试跑全环计时规范-v1-20261107.md §一/§二/§三"

# 五段定义（规范 §一）：key → (名称, 形态 point-start/point-end/span)
SEGMENT_DEFS = [
    ("T0", "建卡", "start"),   # 起点=issue created_at；终点=—
    ("T1", "派发", "start"),   # 起点=派发评论/指令发出；终点=—
    ("T2", "回收", "span"),    # 起点=交卷评论 created_at；终点=收件核落定
    ("T3", "判分", "span"),    # 起点=判分腿起；终点=verdict 落盘（judge.json mtime）
    ("T4", "回卡", "end"),     # 起点=—；终点=回执评论 created_at
]

# ─────────────────────────────────────────────────────────────────────────── #
# scrub 预检（凭据形态子集）——逐字同 tools/cnb-verdict-reply.py:94-108 形制。      #
#   全量 18 模式树扫归 gates 剖面② bot-scrub；本件只守产出面（卡面验收「零凭据    #
#   形态」）。fail-closed：命中即拒写，匹配原文永不进输出。                        #
# ─────────────────────────────────────────────────────────────────────────── #
SCRUB_PATTERNS = [
    ("SCRUB-JWT", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}")),
    ("SCRUB-SK", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")),
    ("SCRUB-GHPAT", re.compile(r"\b(?:ghp|gho|ghu|github_pat_)[A-Za-z0-9_]{20,}")),
    ("SCRUB-AWS", re.compile(r"\bAKIA[0-9A-Z]{14,22}\b")),
    ("SCRUB-PEM", re.compile(
        r"-----BEGIN [A-Za-z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Za-z ]*PRIVATE KEY-----"
        r"|-----BEGIN [A-Za-z ]*PRIVATE KEY-----")),
    ("SCRUB-BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}")),
    ("SCRUB-URLUSERINFO", re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://[^\s/:@]+:[^\s/@]{4,}@")),
    ("SCRUB-ASSIGN", re.compile(
        r"(?i)['\"]?[A-Za-z0-9_-]{0,64}?(?:password|passwd|pwd|secret|token|api_key|apikey"
        r"|access_key|auth_key|auth_token|credential|cred)s?['\"]?\s{0,16}[:=]\s{0,16}['\"]?"
        r"(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,4096}")),
]

# 零板写计数器：--fetch 每次真网络 GET 登记；--collect/--selftest 断言为空
# （结构上证明采集干跑零网络——不靠"我以为没调"）。
_NET_CALLS = []


def scrub_precheck(text):
    """产出面 scrub 预检。返回 [(形态名, 行号)]；空表=clean。fail-closed。"""
    hits = []
    nl = [m.start() for m in re.finditer("\n", text)]

    def ln_of(pos):
        lo, hi = 0, len(nl)
        while lo < hi:
            mid = (lo + hi) // 2
            if nl[mid] < pos:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    for pid, rx in SCRUB_PATTERNS:
        for m in rx.finditer(text):
            hits.append((pid, ln_of(m.start())))
    return hits


# ─────────────────────────────────────────────────────────────────────────── #
# 时间工具（规范 §三.1：一律 UTC ISO8601；+0800 只作展示列）                      #
# ─────────────────────────────────────────────────────────────────────────── #
def parse_utc(ts):
    """ISO8601（Z 或 ±hh:mm）→ aware datetime(UTC)。解析失败返回 None。"""
    if not ts:
        return None
    s = str(ts).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_utc(path):
    """文件 mtime → UTC ISO8601（os.stat 机读——T3 判分终点权威源）。"""
    return iso_utc(datetime.fromtimestamp(os.stat(path).st_mtime, tz=timezone.utc))


def iso8(dt):
    return iso_utc(dt) if dt else None


def to8(dt):
    return dt.astimezone(TZ8).strftime("%Y-%m-%d %H:%M:%S +0800") if dt else "n/a"


def fmt_delta(sec):
    """秒 → 人读时长（spec §四形制：2h19m21s / 43m25s / 37s）。"""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh%dm%ds" % (h, m, s)
    if m:
        return "%dm%ds" % (m, s)
    return "%ds" % s


# ─────────────────────────────────────────────────────────────────────────── #
# GitHub API（仅 --fetch 走；GET 只读；先落盘再解析·规范 §三.2）                   #
# ─────────────────────────────────────────────────────────────────────────── #
def gh_get(path, out_path):
    """GET api.github.com<path> → 原始响应**先落盘**（out_path）再解析返回。
    授权头只在环境量现取到令牌时携带（禁 argv/禁回显/禁落盘）。"""
    import urllib.request
    import urllib.error
    _NET_CALLS.append({"path": path, "method": "GET"})
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    bearer = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    authed = False
    if bearer:
        headers["Authorization"] = "Bearer %s" % bearer
        authed = True
    req = urllib.request.Request(GH_API + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        raise RuntimeError("gh_get http=%d body=%s" % (e.code, raw[:200].decode("utf-8", "replace")))
    with open(out_path, "wb") as f:   # 先落盘……
        f.write(raw)
    with open(out_path, encoding="utf-8") as f:   # ……再解析
        return json.load(f), authed


# ─────────────────────────────────────────────────────────────────────────── #
# 五段段位装载（每段：时点+数据源 或 n/a+原因——禁留空、禁编估·规范 §二规则）        #
# ─────────────────────────────────────────────────────────────────────────── #
def seg_point(at, source, note=None):
    return {"at_utc": iso_utc(at), "source": source, "note": note or ""}


def seg_na(reason, equiv=None, note=None):
    d = {"na": True, "reason": reason, "note": note or ""}
    if equiv:
        d["equiv_utc"] = iso_utc(equiv)   # 等价点入参考列（规范 §二）
        d["note"] = (d["note"] + "；" if d["note"] else "") + "等价点入参考列"
    return d


def load_issue_t0(args, warnings):
    """T0：--issue-cache 留痕件 或 --fetch 实读（cache 优先，fetch 补缺）。"""
    src = None
    if args.issue_cache:
        with open(args.issue_cache, encoding="utf-8") as f:
            obj = json.load(f)
        src = "issue-cache:%s" % args.issue_cache
    elif args.fetch:
        out_dir = os.path.dirname(os.path.abspath(args.out)) if args.out else "."
        raw_path = os.path.join(out_dir, "issue-raw.json")
        obj, authed = gh_get("/repos/%s/issues/%d" % (args.repo, args.issue), raw_path)
        src = "github-api:created_at（%s）" % ("授权读" if authed else "匿名读")
    else:
        raise SystemExit2("T0 无数据源：需 --issue-cache 留痕件或 --fetch（禁编估）")
    created = obj.get("created_at")
    dt = parse_utc(created)
    if not dt:
        raise SystemExit2("T0 数据源无 created_at 或不可解析：%r" % (created,))
    if args.issue and obj.get("number") not in (None, args.issue):
        warnings.append("issue-cache number=%s 与 --issue %d 不一致（以 cache 实读为准）"
                        % (obj.get("number"), args.issue))
    return seg_point(dt, src, note="规范 §一：GitHub API GET /issues/{n} created_at 实读")


def load_t1(args, bw, warnings):
    """T1：显式留痕直给 ＞ bench-watch --dispatched-at 口 ＞ n/a（原因必填）。"""
    if args.t1_at:
        dt = parse_utc(args.t1_at)
        if not dt:
            raise SystemExit2("--t1-at 不可解析：%r" % args.t1_at)
        if args.run_type in ("A", "B"):
            warnings.append("跑型 %s 按规范 §二 T1 应记 n/a+原因（等价点入参考列）；"
                            "给了时刻属口径漂移，已照录并点名" % args.run_type)
        note = None
        if args.t1_id:
            note = "派发评论 id=%s（cnb-dispatch 留痕）" % args.t1_id
        return seg_point(dt, args.t1_source or "cli:dispatch-trace", note=note)
    if bw:
        at = parse_utc(bw.get("dispatched_at_utc") or "")
        if at:
            return seg_point(at, "bench-watch-readings:dispatched_at_utc（--dispatched-at 口）",
                             note="派发评论 id 未入该读数件（id 见派发留痕 state 件）")
    if args.t1_na:
        return seg_na(args.t1_na, equiv=parse_utc(args.t1_equiv) if args.t1_equiv else None,
                      note="等价点/原因口径见规范 §二跑型映射")
    raise SystemExit2("T1 无数据源且无 --t1-na 原因——n/a 禁留空（规范 §二）")


def load_bench_watch(path):
    """读 bench-watch 读数件并校验 schema（消费端对接·不符即拒收）。"""
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("schema") != BENCH_WATCH_SCHEMA:
        raise SystemExit2("bench-watch 读数 schema 不符：got %r want %r（拒收 fail-closed）"
                          % (obj.get("schema"), BENCH_WATCH_SCHEMA))
    return obj


def load_t2(args, bw, warnings):
    """T2：bench-watch 末卷 chosen.created → collected_at_utc ＞ 留痕转引 ＞ n/a。"""
    if bw:
        chosen = bw.get("chosen") or {}
        created = parse_utc(chosen.get("created") or "")
        collected = parse_utc(bw.get("collected_at_utc") or "")
        if not created:
            # deadline 到零候选卷 = 未交卷（bench-watch 退出码 2 形制）
            reason = "未交卷（bench-watch 零候选卷%s）" % (
                "，deadline_hit=true" if bw.get("deadline_hit") else "")
            return seg_na(reason, note="volume_chain=%d 卷" % len(bw.get("volume_chain") or []))
        end = collected or None
        note = "末卷规则（规范 §三.4）：chosen sha256[:12]=%s（%d 卷指纹链随读数落盘）" % (
            str(chosen.get("sha256") or "")[:12] or "n/a", len(bw.get("volume_chain") or []))
        d = {"start": seg_point(created, "bench-watch-readings:chosen.created（交卷评论 created_at）", note=note)}
        if end:
            d["end"] = seg_point(end, "bench-watch-readings:collected_at_utc（收卷关窗落盘）",
                                 note="收件核 apply-check rc=%s 入参考列"
                                      % (json.dumps((bw.get("baseline_apply_check") or {}).get("rc"))
                                         if bw.get("baseline_apply_check") else "未跑（无 --baseline）"))
        else:
            d["end"] = seg_na("bench-watch 读数无 collected_at_utc")
        return d
    start = parse_utc(args.t2_start_at) if args.t2_start_at else None
    end = parse_utc(args.t2_end_at) if args.t2_end_at else None
    if start or end:
        if args.run_type == "A":
            warnings.append("跑型 A 按规范 §二 T2 应记 n/a+原因；给了时刻属口径漂移，已照录并点名")
        d = {"start": seg_point(start, "cli:留痕转引", note="早于 bench-watch 落地的跑，时刻自留痕件转引") if start
             else seg_na("无交卷时刻留痕"),
             "end": seg_point(end, "cli:留痕转引", note="收件核落定时刻自留痕件转引") if end
             else seg_na("无收件核落定时刻留痕")}
        return d
    if args.t2_na:
        return seg_na(args.t2_na, equiv=parse_utc(args.t2_equiv) if args.t2_equiv else None)
    raise SystemExit2("T2 无数据源且无 --t2-na 原因——n/a 禁留空（规范 §二）")


def load_t3(args, warnings):
    """T3：终点=judge.json mtime（os.stat 机读）；起点=留痕转引或缺席自动 n/a+原因。"""
    if args.t3_na:
        return {"start": seg_na("跑未判分（--t3-na）"),
                "end": seg_na(args.t3_na)}
    if not args.judge:
        raise SystemExit2("T3 无数据源：需 --judge <judge.json>（mtime 机读）或 --t3-na 原因")
    if not os.path.exists(args.judge):
        raise SystemExit2("--judge 文件不存在：%s（mtime 无从机读，禁编估）" % args.judge)
    start = parse_utc(args.judge_start_at) if args.judge_start_at else None
    seg = {"end": seg_point(datetime_from_mtime(args.judge), "judge.json mtime（os.stat 机读）",
                            note="规范 §一：verdict 落盘时点·禁从 trace 转抄"),
           "start": seg_point(start, "cli:留痕转引", note="判分腿起（输入部署+warm-relay 起）")
           if start else
           seg_na("判分腿起步时刻无机器留痕源（warm-relay 起步在判分读数面）；本件以 "
                  "judge.json mtime 为 T3 终点机读，起点缺席如实记 n/a")}
    return seg


def datetime_from_mtime(path):
    return datetime.fromtimestamp(os.stat(path).st_mtime, tz=timezone.utc)


def load_t4(args, comments, warnings):
    """T4：回执评论 id+created_at（API 实读·规范 §三.3 以 201 评论 created_at 为准）。

    定位规则：marker（缺省「判分回卡」·cnb-verdict-reply 渲染头）取末条；或 --t4-id
    显式（须在实读列表内恰一命中）。都缺席且无 --t4-na ⇒ rc=2。"""
    if comments is None:
        if args.t4_na:
            return seg_na(args.t4_na)
        raise SystemExit2("T4 无数据源：需 --comments-cache/--fetch 或 --t4-id/--t4-na 原因")
    hits = []
    if args.t4_id:
        hits = [c for c in comments if str(c.get("id")) == str(args.t4_id)]
        if not hits:
            raise SystemExit2("--t4-id %s 在实读评论列表 %d 条中零命中（禁编估）"
                              % (args.t4_id, len(comments)))
    else:
        hits = [c for c in comments if args.marker in (c.get("body") or "")]
        if not hits:
            if args.t4_na:
                return seg_na(args.t4_na, note="实读 %d 条评论无 marker %r"
                              % (len(comments), args.marker))
            raise SystemExit2("实读 %d 条评论无 marker %r 命中，且无 --t4-id/--t4-na——"
                              "回执评论无从定位（禁猜）" % (len(comments), args.marker))
        if len(hits) > 1:
            hits.sort(key=lambda c: (c.get("created_at") or "", str(c.get("id"))))
            warnings.append("marker 命中 %d 条，取末条 id=%s（多卷回卡以末回执为准）"
                            % (len(hits), hits[-1].get("id")))
    c = hits[-1]
    dt = parse_utc(c.get("created_at") or "")
    if not dt:
        raise SystemExit2("回执评论 created_at 缺席/不可解析：%r" % (c.get("created_at"),))
    author = (c.get("user") or {}).get("login")
    return seg_point(dt, "github-api:comments created_at（201 评论）",
                     note="回执评论 id=%s author=%s" % (c.get("id"), author or "n/a"))


def load_comments(args):
    """T4 数据源：cache 优先，--fetch 实读（先落盘再解析）。"""
    if args.comments_cache:
        with open(args.comments_cache, encoding="utf-8") as f:
            return json.load(f), "comments-cache:%s" % args.comments_cache
    if args.fetch:
        out_dir = os.path.dirname(os.path.abspath(args.out)) if args.out else "."
        raw_path = os.path.join(out_dir, "comments-raw.json")
        obj, authed = gh_get("/repos/%s/issues/%d/comments?per_page=100"
                             % (args.repo, args.issue), raw_path)
        return obj, "github-api:comments（%s）" % ("授权读" if authed else "匿名读")
    return None, None


# ─────────────────────────────────────────────────────────────────────────── #
# 段间指标（规范 §一：T0→T1 排队等窗｜T1→T2 施工+交卷｜T2→T3 收件核+判分准备｜     #
# T3→T4 回卡腿｜T0→T4 全环）                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
INTERVAL_DEFS = [
    ("T0→T1", "排队等窗", "T0", "at", "T1", "at"),
    ("T1→T2", "沙箱施工+交卷", "T1", "at", "T2", "start"),
    ("T2→T3", "收件核+判分准备", "T2", "end", "T3", "end"),
    ("T3→T4", "回卡腿", "T3", "end", "T4", "at"),
    ("T0→T4", "全环", "T0", "at", "T4", "at"),
]


def seg_endpoint(segments, seg_key, which):
    """取段端点 datetime；n/a 或缺席返回 None（诚实 n/a，不编 0）。"""
    seg = segments.get(seg_key) or {}
    if seg.get("na"):
        return None
    if which == "at":
        node = seg if "at_utc" in seg else (seg.get("end") or {})
    else:
        node = seg.get(which) or {}
    if node.get("na"):
        return None
    return parse_utc(node.get("at_utc") or "")


def compute_intervals(segments):
    out = {}
    for key, label, s_seg, s_end, e_seg, e_end in INTERVAL_DEFS:
        a = seg_endpoint(segments, s_seg, s_end if s_end != "at" else "at")
        b = seg_endpoint(segments, e_seg, e_end)
        if a and b:
            sec = (b - a).total_seconds()
            out[key] = {"label": label, "seconds": round(sec, 1), "human": fmt_delta(sec)}
        else:
            missing = "+".join(x for x in ((s_seg if not a else ""),
                                           (e_seg if not b else "")) if x)
            out[key] = {"label": label, "na": True,
                        "reason": "端点缺席（%s）——n/a 如实，不编估" % missing}
    return out


# ─────────────────────────────────────────────────────────────────────────── #
# 渲染：五段表 markdown（规范 §四形制 + 数据源列 + +0800 展示列）＋台账行草案       #
# ─────────────────────────────────────────────────────────────────────────── #
def _cell_point(node, dt):
    if node.get("na"):
        s = "n/a（%s）" % node.get("reason", "")
        if node.get("equiv_utc"):
            s += "｜等价点 %s" % to8(parse_utc(node["equiv_utc"]))
        return s
    return iso_utc(dt) if dt else "n/a（端点缺席）"


def render_md(debt, issue, run_type, segments, intervals, out_path, bw_path, judge_path):
    lines = []
    lines.append("## 五段计时表（机器采集 · %s · factory-os#%s · 跑型 %s）" % (debt, issue, run_type))
    lines.append("")
    lines.append("> 数据源与规范 §一 一致；采集件 tools/cb-five-segment-timing.py"
                 "（schema=%s）；零人工补表、零凭据形态。" % READING_SCHEMA)
    lines.append("")
    lines.append("| 段 | 时刻(UTC) | 时刻(+0800 展示列) | 数据源 | 备注 |")
    lines.append("|---|---|---|---|---|")
    for key, name, form in SEGMENT_DEFS:
        seg = segments.get(key) or {}
        if form == "span":
            st, en = seg.get("start") or {}, seg.get("end") or {}
            dts = seg_endpoint(segments, key, "start")
            dte = seg_endpoint(segments, key, "end")
            lines.append("| %s %s（起） | %s | %s | %s | %s |" % (
                key, name, _cell_point(st, dts), to8(dts),
                st.get("source") or "n/a", st.get("note") or ""))
            lines.append("| %s %s（讫） | %s | %s | %s | %s |" % (
                key, name, _cell_point(en, dte), to8(dte),
                en.get("source") or "n/a", en.get("note") or ""))
        else:
            node = seg if (seg.get("na") or "at_utc" in seg) \
                else (seg.get("end") or seg.get("start") or {})
            dt = seg_endpoint(segments, key, "at")
            lines.append("| %s %s | %s | %s | %s | %s |" % (
                key, name, _cell_point(node, dt), to8(dt),
                node.get("source") or "n/a", node.get("note") or ""))
    lines.append("| **全环 T0→T4** | — | — | intervals 机算 | %s |" % (
        intervals["T0→T4"].get("human") if not intervals["T0→T4"].get("na") else "n/a（%s）" % intervals["T0→T4"]["reason"]))
    lines.append("")
    lines.append("### 段间指标（规范 §一）")
    lines.append("")
    lines.append("| 段间 | 含义 | 间隔 |")
    lines.append("|---|---|---|")
    for key, label, *_ in INTERVAL_DEFS:
        iv = intervals[key]
        lines.append("| %s | %s | %s |" % (key, label,
                    iv.get("human") if not iv.get("na") else "n/a（%s）" % iv["reason"]))
    lines.append("")
    lines.append("### 溯源")
    lines.append("")
    lines.append("- bench-watch 读数件：%s（schema %s）" % (bw_path or "未接（n/a 见段行）", BENCH_WATCH_SCHEMA))
    lines.append("- judge.json：%s（T3 终点=mtime 机读）" % (judge_path or "未接（n/a 见段行）"))
    lines.append("- 读数 JSON：%s（规范依据：%s）" % (out_path or "n/a", SPEC_REF))
    if intervals.get("T0→T4", {}).get("human"):
        lines.append("- 台账回填行（草案·零账本写入，登记走 PR 流+owner 批）引用本机器表："
                     "时间轴=机器五段表 %s 全环 T0→T4=%s" % (out_path or "n/a", intervals["T0→T4"]["human"]))
    return "\n".join(lines) + "\n"


def ledger_draft(debt, issue, segments, intervals, out_path):
    """台账行回填草案（待办 3：直接引用机器五段表）。零账本写入路径。"""
    t1 = segments.get("T1") or {}
    full = intervals.get("T0→T4") or {}
    timeline = ("机器五段表 %s（schema=%s）" % (out_path or "n/a", READING_SCHEMA))
    if not full.get("na"):
        timeline += " 全环 T0→T4=%s" % full["human"]
    t1_txt = ("T1 派发 %s" % t1["at_utc"][11:]) if not t1.get("na") else "T1 n/a（%s）" % t1.get("reason", "")
    return "时间轴=%s；%s（本行由 tools/cb-five-segment-timing.py 生成，禁人工补表）" % (timeline, t1_txt)


# ─────────────────────────────────────────────────────────────────────────── #
# 采集主流程                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
class SystemExit2(Exception):
    """fail-closed 采集失败（rc=2）。"""


def collect(args):
    warnings = []
    bw = load_bench_watch(args.bench_watch) if args.bench_watch else None
    t0 = load_issue_t0(args, warnings)
    t1 = load_t1(args, bw, warnings)
    t2 = load_t2(args, bw, warnings)
    t3 = load_t3(args, warnings)
    comments, comments_src = load_comments(args)
    t4 = load_t4(args, comments, warnings)

    segments = {"T0": t0, "T1": t1, "T2": t2, "T3": t3, "T4": t4}
    intervals = compute_intervals(segments)

    judge_block = None
    if args.judge and os.path.exists(args.judge):
        try:
            with open(args.judge, encoding="utf-8") as f:
                j = json.load(f)
            judge_block = {
                "verdict": j.get("verdict"),
                "diff_sha256_12": str(j.get("diff_sha256") or "")[:12] or None,
                "f2p_success": j.get("f2p_success"), "f2p_failure": j.get("f2p_failure"),
                "p2p_success": j.get("p2p_success"), "p2p_failure": j.get("p2p_failure"),
                "note": "只读公开安全字段（sha 前 12 位+计数）；判官件零改动",
            }
        except Exception as exc:  # noqa: BLE001
            judge_block = {"verdict": None, "note": "judge.json 解析失败（%s）；"
                           "mtime 仍为 T3 终点机器时点" % type(exc).__name__}
    bw_block = None
    if bw:
        chosen = bw.get("chosen") or {}
        bw_block = {"file": args.bench_watch, "schema": bw.get("schema"),
                    "volumes": len(bw.get("volume_chain") or []),
                    "chosen_sha256_12": str(chosen.get("sha256") or "")[:12] or None,
                    "deadline_hit": bw.get("deadline_hit"),
                    "baseline_apply_check_rc": (bw.get("baseline_apply_check") or {}).get("rc"),
                    "note": "卡面待办 2：与 tools/cb-dispatch.py bench-watch 读数 schema 对接"}

    reading = {
        "schema": READING_SCHEMA,
        "debt": args.debt, "issue": args.issue, "repo": args.repo,
        "run_type": args.run_type,
        "generated_at_utc": iso_utc(datetime.now(timezone.utc)),
        "spec": SPEC_REF,
        "segments": segments,
        "intervals": intervals,
        "bench_watch": bw_block,
        "judge": judge_block,
        "comments_source": comments_src,
        "ledger_row_draft": ledger_draft(args.debt, args.issue, segments, intervals, args.out),
        "warnings": warnings,
        "net_writes": 0,
        "note": "零凭据形态：产出经 scrub 预检 clean 方落盘；零账本写入；判官件/判据件零改动",
    }

    md = render_md(args.debt, args.issue, args.run_type, segments, intervals,
                   args.out, args.bench_watch, args.judge)
    body = json.dumps(reading, ensure_ascii=False, indent=1) + "\n"
    for label, text in (("readings", body), ("五段表", md)):
        hits = scrub_precheck(text)
        if hits:
            for pid, ln in hits:
                print("SCRUB-HIT %s at %s line %d（匹配原文不进输出）" % (pid, label, ln),
                      file=sys.stderr)
            raise SystemExit2("拒写：%s scrub 预检命中 %d 处——零凭据形态 fail-closed"
                              % (label, len(hits)))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("readings -> %s" % args.out)
    else:
        sys.stdout.write(body)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
        print("五段表 -> %s" % args.md)
    else:
        sys.stdout.write(md)
    full = intervals["T0→T4"]
    print("全环 T0→T4 = %s" % (full.get("human") if not full.get("na")
                               else "n/a（%s）" % full["reason"]))
    for w in warnings:
        print("WARNING %s" % w, file=sys.stderr)
    return 0


# ─────────────────────────────────────────────────────────────────────────── #
# selftest（夹具驱动，零网络零板写零凭据）                                         #
# ─────────────────────────────────────────────────────────────────────────── #
def selftest():
    """夹具断言：跑型 C 全链 + 跑型 A n/a 形制 + bench-watch schema 对接 + T3 mtime
    机读 + T4 marker 定位 + scrub 正反例 + 零网络零板写。"""
    import contextlib
    import io
    import shutil
    import tempfile

    n = 0
    base = os.path.dirname(os.path.abspath(__file__))
    fx = os.path.join(base, "fixtures", "cb-five-segment-timing")

    def fxpath(name):
        return os.path.join(fx, name)

    tmp = tempfile.mkdtemp(prefix="d121-selftest-")

    def argv_run(extra, ut3=None):
        """跑 --collect 于临时目录；返回 (rc, stdout)。ut3=judge.json 目标 mtime epoch。"""
        d = tempfile.mkdtemp(prefix="d121-run-", dir=tmp)
        out = os.path.join(d, "readings.json")
        md = os.path.join(d, "五段表.md")
        argv = ["--collect", "--out", out, "--md", md] + list(extra)
        buf = io.StringIO()
        ebuf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            rc = main_argv(argv)
        return rc, buf.getvalue(), ebuf.getvalue(), out, md

    # ── 1. 跑型 C 全链：T0-T4 全段有时点 ──
    judge_c = os.path.join(tmp, "judge-c.json")
    shutil.copy(fxpath("judge-c.json"), judge_c)
    os.utime(judge_c, (1794000630, 1794000630))  # 2026-11-06T21:30:30Z（固定 mtime 机读）
    n += 1
    rc, out, err, outp, mdp = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-c.json"),
        "--bench-watch", fxpath("bench-watch-c.json"),
        "--judge", judge_c,
        "--t1-id", "2118812026456629248", "--t1-at", "2026-11-06T21:05:26Z",
    ])
    assert rc == 0, "跑型 C 全链 rc=%d err=%s" % (rc, err)
    with open(outp, encoding="utf-8") as f:
        r = json.load(f)
    n += 1
    assert r["schema"] == READING_SCHEMA, r["schema"]
    # 全段有时点（卡面验收：T0-T4 全段有时点）
    n += 1
    assert r["segments"]["T0"]["at_utc"] == "2026-11-06T20:51:19Z", r["segments"]["T0"]
    assert r["segments"]["T1"]["at_utc"] == "2026-11-06T21:05:26Z", r["segments"]["T1"]
    assert r["segments"]["T2"]["start"]["at_utc"] == "2026-11-06T21:18:09Z", r["segments"]["T2"]
    assert r["segments"]["T2"]["end"]["at_utc"] == "2026-11-06T21:25:39Z", r["segments"]["T2"]
    assert r["segments"]["T3"]["end"]["at_utc"] == "2026-11-06T21:30:30Z", r["segments"]["T3"]
    assert r["segments"]["T4"]["at_utc"] == "2026-11-06T21:34:44Z", r["segments"]["T4"]
    # T1 全要素 id+created_at（卡面待办 1）；T4 同
    n += 1
    assert "2118812026456629248" in (r["segments"]["T1"]["note"] or ""), r["segments"]["T1"]["note"]
    assert "6696243328" in (r["segments"]["T4"]["note"] or ""), r["segments"]["T4"]["note"]
    # 段间指标对拍（规范 §四 D-117 行同口径）
    n += 1
    iv = r["intervals"]
    assert iv["T0→T1"]["human"] == "14m7s", iv["T0→T1"]
    assert iv["T1→T2"]["human"] == "12m43s", iv["T1→T2"]
    assert iv["T2→T3"]["human"] == "4m51s", iv["T2→T3"]
    assert iv["T3→T4"]["human"] == "4m14s", iv["T3→T4"]
    assert iv["T0→T4"]["human"] == "43m25s", iv["T0→T4"]   # 与规范 §四 D-117 全环一致
    # bench-watch 对接块 + T3 mtime 机读源名
    n += 1
    assert r["bench_watch"]["schema"] == BENCH_WATCH_SCHEMA, r["bench_watch"]
    assert r["bench_watch"]["volumes"] == 2 and r["bench_watch"]["chosen_sha256_12"] == "e0c58d54645f", r["bench_watch"]
    assert "mtime" in r["segments"]["T3"]["end"]["source"], r["segments"]["T3"]["end"]
    # T4 marker 定位自 cache；md 五段表在盘且行齐
    n += 1
    with open(mdp, encoding="utf-8") as f:
        md_txt = f.read()
    for must in ("T0 建卡", "T1 派发", "T2 回收", "T3 判分", "T4 回卡", "全环 T0→T4",
                 "43m25s", "judge.json mtime"):
        assert must in md_txt, "五段表缺要素：%s" % must
    # 台账行草案引用机器五段表（卡面待办 3）
    n += 1
    assert "机器五段表" in r["ledger_row_draft"] and READING_SCHEMA in r["ledger_row_draft"], r["ledger_row_draft"]

    # ── 2. 跑型 A：T1/T2 n/a+原因+等价点参考列（规范 §二映射）──
    judge_a = os.path.join(tmp, "judge-a.json")
    shutil.copy(fxpath("judge-a.json"), judge_a)
    os.utime(judge_a, (1793974267, 1793974267))  # 2026-11-06T14:11:07Z
    n += 1
    rc, out, err, outp, mdp = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "21", "--debt", "D-86", "--run-type", "A",
        "--issue-cache", fxpath("issue-a.json"),
        "--comments-cache", fxpath("comments-a.json"),
        "--judge", judge_a,
        "--t1-na", "harness 侧自工（规范 §二跑型 A）", "--t1-equiv", "2026-11-06T14:03:17Z",
        "--t2-na", "自产 patch 直入判分（规范 §二跑型 A）", "--t2-equiv", "2026-11-06T14:10:53Z",
    ])
    assert rc == 0, "跑型 A rc=%d err=%s" % (rc, err)
    with open(outp, encoding="utf-8") as f:
        r = json.load(f)
    n += 1
    for k in ("T1", "T2"):
        assert r["segments"][k].get("na") and r["segments"][k].get("reason"), r["segments"][k]
    assert r["segments"]["T1"]["equiv_utc"] == "2026-11-06T14:03:17Z", r["segments"]["T1"]
    assert r["segments"]["T2"]["equiv_utc"] == "2026-11-06T14:10:53Z", r["segments"]["T2"]
    assert r["segments"]["T0"]["at_utc"] == "2026-11-06T11:55:06Z"
    assert r["segments"]["T4"]["at_utc"] == "2026-11-06T14:14:27Z"
    n += 1
    assert r["intervals"]["T0→T4"]["human"] == "2h19m21s", r["intervals"]["T0→T4"]  # 规范 §四 D-86 全环
    assert r["intervals"]["T1→T2"]["na"], r["intervals"]["T1→T2"]
    # 全环口径含等窗（规范 §二：与跑型 C 同口径可比）
    n += 1
    with open(mdp, encoding="utf-8") as f:
        md_a = f.read()
    assert "n/a（harness 侧自工" in md_a and "等价点" in md_a, md_a

    # ── 3. bench-watch schema 对接负例：schema 不符拒收 rc=2 ──
    n += 1
    rc, out, err, *_ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-c.json"),
        "--bench-watch", fxpath("bench-watch-badschema.json"),
        "--judge", judge_c,
    ])
    assert rc == 2 and "schema 不符" in err, (rc, err)

    # ── 4. n/a 禁留空：跑型 C 缺 T1 数据源且无 --t1-na ⇒ rc=2 ──
    n += 1
    rc, out, err, *_ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-c.json"),
        "--judge", judge_c,
    ])
    assert rc == 2 and "T1" in err, (rc, err)

    # ── 5. bench-watch --dispatched-at 口作 T1 源（卡面待办 1）──
    n += 1
    bw2 = os.path.join(tmp, "bw2.json")
    with open(fxpath("bench-watch-c.json"), encoding="utf-8") as f:
        bwo = json.load(f)
    bwo["dispatched_at_utc"] = "2026-11-06T21:05:26Z"
    with open(bw2, "w", encoding="utf-8") as f:
        json.dump(bwo, f, ensure_ascii=False, indent=1)
    rc, out, err, outp, _ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-c.json"),
        "--bench-watch", bw2,
        "--judge", judge_c,
    ])
    assert rc == 0, err
    with open(outp, encoding="utf-8") as f:
        r = json.load(f)
    assert r["segments"]["T1"]["at_utc"] == "2026-11-06T21:05:26Z", r["segments"]["T1"]
    assert "dispatched_at_utc" in r["segments"]["T1"]["source"], r["segments"]["T1"]

    # ── 6. T4：marker 零命中且无 --t4-na ⇒ rc=2；给 --t4-na ⇒ n/a+原因 ──
    n += 1
    rc, out, err, *_ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-no-reply.json"),
        "--judge", judge_c,
        "--bench-watch", fxpath("bench-watch-c.json"),
        "--t1-at", "2026-11-06T21:05:26Z",
    ])
    assert rc == 2 and "marker" in err, (rc, err)
    n += 1
    rc, out, err, outp, _ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "90", "--debt", "D-117", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-no-reply.json"),
        "--judge", judge_c,
        "--bench-watch", fxpath("bench-watch-c.json"),
        "--t1-at", "2026-11-06T21:05:26Z",
        "--t4-na", "压测在飞未回卡（规范 §五待续形制）",
    ])
    assert rc == 0, err
    with open(outp, encoding="utf-8") as f:
        r = json.load(f)
    assert r["segments"]["T4"]["na"] and r["segments"]["T4"]["reason"], r["segments"]["T4"]
    assert r["intervals"]["T0→T4"]["na"], "T4 n/a 时全环必须 n/a（禁编估）"

    # ── 7. T3：--judge 文件缺席且无 --t3-na ⇒ rc=2；--t3-na ⇒ n/a+原因 ──
    n += 1
    rc, out, err, *_ = argv_run([
        "--repo", DEFAULT_REPO, "--issue", "117", "--debt", "D-118", "--run-type", "C",
        "--issue-cache", fxpath("issue-c.json"),
        "--comments-cache", fxpath("comments-no-reply.json"),
        "--bench-watch", fxpath("bench-watch-c.json"),
        "--t1-at", "2026-11-07T07:07:16Z",
        "--t4-na", "未回卡",
    ])
    assert rc == 2 and "T3" in err, (rc, err)

    # ── 8. scrub 预检正反例（零凭据形态·卡面验收）──
    n += 1
    probes = {
        "SCRUB-JWT": "eyJ" + "A" * 24 + "." + "B" * 12 + "." + "C" * 24,
        "SCRUB-SK": "sk-" + "A" * 30,
        "SCRUB-GHPAT": "gh" + "p_" + "A" * 30,
        "SCRUB-AWS": "AKIA" + "A" * 16,
        "SCRUB-PEM": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "SCRUB-BEARER": "Bearer " + "A" * 30,
        "SCRUB-URLUSERINFO": "http://" + "u" * 4 + ":" + "p" * 8 + "@h.example",
        "SCRUB-ASSIGN": "access_" + "token" + ": " + "A" * 30,
    }
    for pid, probe in probes.items():
        n += 1
        got = scrub_precheck("前缀行\n" + probe + "\n尾行")
        assert any(p == pid for p, _ in got), "scrub 探针 %s 未被检出：%s" % (pid, got)
    # 产出面 clean：全链 readings + md 过 scrub
    n += 1
    assert scrub_precheck(out) == [] and scrub_precheck(md_txt) == [], "产出面凭据形态命中"

    # ── 9. 零板写断言：--collect 路径零网络调用（_NET_CALLS 只登记 --fetch GET）──
    n += 1
    assert len(_NET_CALLS) == 0, "--collect 发起了网络调用：%s" % _NET_CALLS

    # ── 10. 工具函数小对拍：fmt_delta/parse_utc 形制 ──
    n += 1
    assert fmt_delta(2 * 3600 + 19 * 60 + 21) == "2h19m21s"
    assert fmt_delta(43 * 60 + 25) == "43m25s"
    assert fmt_delta(37) == "37s"
    assert parse_utc("2026-11-06T21:05:26Z") is not None
    assert parse_utc("垃圾") is None

    shutil.rmtree(tmp, ignore_errors=True)
    print("selftest: %d/%d 断言全过（跑型C全链 T0-T4 时点+段间指标对拍规范§四 D-117/"
          "跑型A n/a+原因+等价点/bench-watch schema 对接正反例/--dispatched-at 口/"
          "T4 marker 定位正反例/T3 mtime 机读+缺席 fail-closed/scrub 正反例/"
          "零板写零网络）" % (n, n))
    return 0


def main_argv(argv):
    old = sys.argv[:]
    try:
        sys.argv = ["cb-five-segment-timing.py"] + list(argv)
        return main()
    except SystemExit2 as e:
        print("拒收：%s" % e, file=sys.stderr)
        return 2
    finally:
        sys.argv = old


def main():
    ap = argparse.ArgumentParser(
        description="试跑全环五段计时自动采集器（D-121）：T0 建卡→T1 派发→T2 回收→T3 判分→T4 回卡")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="目标板 owner/name")
    ap.add_argument("--issue", type=int, default=None, help="卡号（GitHub issue 号）")
    ap.add_argument("--debt", default=None, help="债号（如 D-117）")
    ap.add_argument("--run-type", dest="run_type", choices=["A", "B", "C"], default="C",
                    help="跑型映射（规范 §二：A harness 自工/B 模拟沙箱/C cnb 真沙箱）")
    ap.add_argument("--issue-cache", default=None, help="GET /issues/{n} 留痕件（T0 源，先落盘再解析）")
    ap.add_argument("--comments-cache", default=None, help="GET /issues/{n}/comments 留痕件（T4 源）")
    ap.add_argument("--bench-watch", default=None,
                    help="bench-watch 读数件（schema %s；T1 --dispatched-at 口+T2 末卷/收卷）"
                         % BENCH_WATCH_SCHEMA)
    ap.add_argument("--judge", default=None, help="judge.json（T3 终点=mtime 机读）")
    ap.add_argument("--judge-start-at", default=None, help="T3 起点留痕转引（判分腿起，可选）")
    ap.add_argument("--t1-id", default=None, help="派发评论 id（cnb-dispatch 留痕）")
    ap.add_argument("--t1-at", default=None, help="T1 派发时刻（ISO8601，留痕转引）")
    ap.add_argument("--t1-source", default=None, help="T1 数据源注记（缺省 cli:dispatch-trace）")
    ap.add_argument("--t1-na", default=None, help="T1 n/a 原因（必填当无时刻源——禁留空）")
    ap.add_argument("--t1-equiv", default=None, help="T1 等价点参考列（规范 §二）")
    ap.add_argument("--t2-start-at", default=None, help="T2 交卷时刻留痕转引（无 bench-watch 读数时）")
    ap.add_argument("--t2-end-at", default=None, help="T2 收件核落定时刻留痕转引")
    ap.add_argument("--t2-na", default=None, help="T2 n/a 原因（禁留空）")
    ap.add_argument("--t2-equiv", default=None, help="T2 等价点参考列")
    ap.add_argument("--t3-na", default=None, help="T3 n/a 原因（跑未判分时）")
    ap.add_argument("--t4-id", default=None, help="回执评论 id（显式；须在实读列表恰一命中）")
    ap.add_argument("--t4-na", default=None, help="T4 n/a 原因（未回卡时）")
    ap.add_argument("--marker", default=DEFAULT_MARKER, help="回执评论定位 marker（缺省 %s）" % DEFAULT_MARKER)
    ap.add_argument("--out", default=None, help="读数 JSON 落盘路径（缺省 stdout）")
    ap.add_argument("--md", default=None, help="五段表 markdown 落盘路径（缺省 stdout）")
    sub = ap.add_mutually_exclusive_group()
    sub.add_argument("--collect", action="store_true",
                     help="采集出表（缺省；零网络零板写）")
    sub.add_argument("--selftest", action="store_true",
                     help="夹具自测（零网络零板写零凭据）")
    ap.add_argument("--fetch", action="store_true",
                    help="随 --collect：对 GitHub API 匿名/环境量令牌只读实读 T0/T4"
                         "（GET；原始响应先落盘再解析；与 --issue-cache/--comments-cache 互斥于各源）")
    args = ap.parse_args()
    if args.selftest:
        if args.fetch:
            print("拒收：--selftest 零网络，不与 --fetch 同用（fail-closed）", file=sys.stderr)
            return 2
        return selftest()
    if not args.issue or args.issue <= 0:
        print("拒收：--issue 需正整数卡号（T0 无从建段，禁编估）", file=sys.stderr)
        return 2
    try:
        return collect(args)
    except SystemExit2 as e:
        print("拒收：%s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
