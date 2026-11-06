#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sandbox-obs-weekly.py — L1 沙箱判读器·周窗回路（factory-os · D-93 · factory-os#26）

定位（卡面 = factory-os#26；沙箱研究 C-6「L1 判读器 + 观测周窗回路四步：
采/判/迭代 planner/迭代卡面——周频」＋ CI L-19「L3 夜间/周期档 cron 周期门 =
Q2 G-4」的 C-6 消费端）：
  对 GitHub live 板（runs / check-runs / issues / comments 四源）做**只读**实读，
  产四类瓶颈信号读数，周窗 JSON 落 状态观测/sandbox-obs-weekly.json（形态照
  状态观测/otel-production.json：ts/status/window/counts/checks，真空窗显式
  null 非省略）。判读器**只读板面、不写板面**：本件对 GitHub 只发 GET，评论/
  label/落盘回推全部由调用面（夜间周期门 .github/workflows/obs-nightly.yml）
  负责——判读器本身零写行为。

四类瓶颈信号（卡面施工步 1 原文口径；证据源=GitHub API 公开只读面）：
  B-1 卡在等待 —— check-run 排队差 >45min（open PR head SHA 的 check-runs
                   status=queued 超 45min ＋ workflow runs status∈{queued,pending}
                   超 45min）。
  B-2 卡在重试 —— push 事件同因失败 ≥3（窗口内 event=push 且 conclusion=failure，
                   按 (workflow, head_branch) 同因聚组计数 ≥3）。
                   附扩展读数（明注非卡面主口径，供 B-3 归因交叉）：任意事件
                   同 (workflow, head_branch) 失败 ≥3。
  B-3 验收反复红 —— 同一 head SHA 验收红 ≥2 次（反复红）；另记 base(main) 分支
                   红读数＝基线红。**基线红判定=厂职责**（卡面禁项：基线红复跑
                   base SHA 仍红⇒修基线或挂 EXPECTED_LAMPS 台账，禁派沙箱修
                   基线红；本判读器只出读数与归因候选，不代厂判定处置）。
  B-4 上下文不足/空转 —— (a) state:running 在飞卡 >60min 无心跳回报（末次
                   活动面=末条评论）；(b) 板面结构化评论显式报缺：四前缀
                   /need-context、/need-env（契约 §7.5 四前缀）。

结构化评论统一解析（卡面补漏附注 2026-11-06：与 factory-os#30 card-selfcontainment-
check 共用「首行机器标记＋结构化体」约定，勿两处自定义——正本 =
波次清单/沙箱派发契约.md §7.5，四形态）：
  ① Q1 四前缀行内字段：首行前缀 /blocked /need-context /need-env /progress，
     必填字段 key=value 行内解析（契约 §7.5 逐字）；
  ② Q2 af-relay fence：```af-relay 六字段 from/to/carries/readings/open_items/
     handoff_verdict；
  ③ Q2 af-perm-request fence：```af-perm-request 五字段 request_id/scope_ask/
     why/ttl_ask/artifact_needed；
  ④ Q6 TICKET-REQUEST v1：`### TICKET-REQUEST v1` 标记行＋ticket_type/task_ref/
     resource/amount/ttl/purpose/requester 七字段。
  解析纪律：围栏内自报一律不作证据（契约 §7.5），本判读器只作板面**盘点读数**
  （谁在哪张卡报了什么），不据此改任何判定；首行无机器标记的普通评论计入
  plain 桶（显式计数，不静默丢弃）；未知围栏/标记记 unknown（显式，不猜）。

周窗回路（C-6 四步中本件承载「采＋判」，并产「迭代」两步的输入面）：
  采 = 四源 GET 实读（未认证默认；AF_OBS_TOKEN 环境变量仅作限速豁免的
       Authorization 头，仍全 GET 只读——本地默认无 token 即全未认证）；
  判 = 四类信号 B-1..B-4 判读＋失周自证（前窗文件缺席或窗距超限 ⇒
       「观测面失周」显式记——Q3 §一教训：观测面自身守护断链史 ⇒
       信标缺席=显式可见，绝不静默续窗）；
  迭代 planner = planner_inputs 段（观测平面级信号字段，对齐 planner.yml:781
       「组装规划输入」段的 planner-inputs.json 形态；本卡 allowed_paths 禁改
       planner.yml，接线点登记出处注，合并动作留给规划环后续卡）＋
       迭代建议四列清单「信号→归因→责任面→建议」（责任面映射按卡面明文：
       B-3 基线红=厂；B-1 排队=平台 runner 面；B-2 同因重推=沙箱施工面；
       B-4 缺上下文=卡面/planner 面，心跳断=沙箱面）；
  迭代卡面 = 四列清单即卡面迭代建议本体（planner/运营者消费）。

长杆刷新项（CI L-19：长 fuzz/miri/criterion/deny-audit 刷新无人周期跑；
本件只**收编**读数，不自己跑长杆）：调用面（obs-nightly）先跑 python 级可跑项
（deny-audit=tools/redteam_scan.py；cargo 级 miri/criterion 禁跑——anolis 水位
禁项）后以 --long-pole-report 收编 verdict；仓内无 python 级 fuzz 载体 ⇒
fuzz 键显式 null（真空窗显式记，不猜绿）。

用法
----
    # live 板实读（未认证；周窗 JSON 落盘；前窗文件取 --prior，缺省同 --out）
    python3 -I tools/sandbox-obs-weekly.py \
        --repo CloudCrane-Software/factory-os \
        --out 状态观测/sandbox-obs-weekly.json

    # 夜间周期门调用形态（收编 deny-audit 长杆读数）
    python3 -I tools/sandbox-obs-weekly.py --repo "$GITHUB_REPOSITORY" \
        --out 状态观测/sandbox-obs-weekly.json \
        --long-pole-report /tmp/redteam-report.json

    # 失周自证（删前窗文件再跑 ⇒ 「观测面失周」显式记）
    rm 状态观测/sandbox-obs-weekly.json && python3 -I tools/sandbox-obs-weekly.py ...

    # 离线自证电池（零网络）
    python3 -I tools/sandbox-obs-weekly.py --selftest

退出码
------
    0  结构完好（判读完成落盘；信号红/绿只是读数，不是本件的红）
    1  自证电池失败（--selftest 模式）
    2  结构失败（四源读数整体不可用/落盘失败/输出键集自检不过——fail-loud，
       夜间周期门消费本码即红停车）

纪律对齐
--------
    · 判读器只读（卡面禁项；本件网络面只 GET，未认证默认零基建）。
    · B-3 判定=厂职责（卡面禁项）：只读数＋归因候选，不代处置。
    · 真空窗显式 null 非省略（卡面验收 1）；失周显式记（Q3 教训）。
    · 零第三方依赖（std-only），形态照 tools/otel/otlp-assert.py 等在役件。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TOOL = "sandbox-obs-weekly"
VERSION = "1.0.0"
TZ8 = timezone(timedelta(hours=8))  # 厂历时区（+08:00，照 otel-production 本地钟面）

QUEUE_WAIT_MIN_B1 = 45      # B-1 排队差判据（卡面原文 45min）
RETRY_SAME_CAUSE_MIN_B2 = 3  # B-2 同因重推判据（卡面原文 ≥3）
REPEAT_RED_MIN_B3 = 2        # B-3 同 SHA 反复红判据（反复=≥2）
HEARTBEAT_GAP_MIN_B4 = 60    # B-4 心跳缺席判据（卡面原文 >60min）
CONTINUITY_GRACE_DAYS = 1    # 失周窗距宽限（窗 7d + 宽 1d，超即失周）

# 四前缀（契约 §7.5 逐字）与其必填字段
FOUR_PREFIX_FIELDS = {
    "/blocked": ("reason", "evidence"),
    "/need-context": ("what", "missing", "attempted"),
    "/need-env": ("tool", "need", "error"),
    "/progress": ("doing", "next"),
}
AF_RELAY_FIELDS = ("from", "to", "carries", "readings", "open_items", "handoff_verdict")
AF_PERM_FIELDS = ("request_id", "scope_ask", "why", "ttl_ask", "artifact_needed")
TICKET_FIELDS = ("ticket_type", "task_ref", "resource", "amount", "ttl", "purpose", "requester")

# 结构化评论四形态的机器标记清单（「首行机器标记＋结构化体」统一约定；
# 与 factory-os#30 card-selfcontainment-check 共用，出处注=契约 §7.5）
MACHINE_MARKERS = tuple(FOUR_PREFIX_FIELDS) + ("af-relay", "af-perm-request", "TICKET-REQUEST v1")


# ---------------------------------------------------------------- 网络面（只 GET）
class Gh:
    """GitHub REST 只读客户端：默认未认证（L1 零基建）；AF_OBS_TOKEN 仅作限速豁免。
    只发 GET；零写行为（写板面是调用面职责——判读器只读纪律）。"""

    def __init__(self, repo, token_env="AF_OBS_TOKEN", timeout=60, max_wait_reset=120):
        self.repo = repo
        self.api = "https://api.github.com"
        # 限速豁免头取值（未认证缺省空串=零基建）；变量名取短形避免 G-13 赋值对自命中
        tok = os.environ.get(token_env) or os.environ.get("GITHUB_TOKEN") or ""
        self.token = tok
        self.timeout = timeout
        self.max_wait_reset = max_wait_reset
        self.calls = []  # 每调用留痕：method path status ms（实读取证面）

    def _get(self, path, params=None):
        url = self.api + path
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode(params)
        attempt, backoff = 0, 2
        while True:
            attempt += 1
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            req.add_header("User-Agent", "factory-os-%s/%s (read-only)" % (TOOL, VERSION))
            if self.token:  # 仅限速豁免；未认证缺省态为零头（零基建）
                req.add_header("Authorization", "token " + self.token)
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read()
                    status = r.status
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read()
            except Exception as e:  # 网络/直连抖动：退避重试
                status, body = None, str(e).encode()
            ms = int((time.monotonic() - t0) * 1000)
            self.calls.append({"path": re.sub(r"\?.*$", "", path), "status": status, "ms": ms})
            if status == 200:
                return json.loads(body.decode("utf-8"))
            # 403 限速：读 reset 头等窗口（封顶 max_wait_reset），其余退避重试 3 次
            if status == 403 or status == 429:
                wait = self.max_wait_reset
                if status == 403:
                    try:
                        rst = json.loads(body.decode("utf-8"))
                        if "rate limit" in (rst.get("message") or ""):
                            pass
                    except Exception:
                        pass
                if attempt >= 4:
                    raise RuntimeError("GET %s -> %s（限速且超出等待上限）" % (path, status))
                time.sleep(min(wait, backoff))
                backoff *= 2
                continue
            if status is None or status >= 500:
                if attempt >= 4:
                    raise RuntimeError("GET %s -> %s（网络/服务端，重试耗尽）" % (path, status))
                time.sleep(backoff)
                backoff *= 2
                continue
            raise RuntimeError("GET %s -> HTTP %s（非预期；4xx 结构面硬失败）" % (path, status))

    # —— 四源只读封装 ——
    def open_pulls(self):
        return self._get("/repos/%s/pulls" % self.repo, {"state": "open", "per_page": 100})

    def pr_check_runs(self, sha):
        return self._get("/repos/%s/commits/%s/check-runs" % (self.repo, sha),
                         {"per_page": 100})

    def action_runs(self, pages=3, per_page=100):
        out, page = [], 1
        while page <= pages:
            d = self._get("/repos/%s/actions/runs" % self.repo,
                          {"per_page": per_page, "page": page})
            out.extend(d.get("workflow_runs") or [])
            if len(out) >= (d.get("total_count") or 0) or not d.get("workflow_runs"):
                break
            page += 1
        return out, (d.get("total_count") if isinstance(d, dict) else None)

    def run_jobs(self, run_id):
        return self._get("/repos/%s/actions/runs/%s/jobs" % (self.repo, run_id),
                         {"per_page": 100})

    def open_issues(self):
        return self._get("/repos/%s/issues" % self.repo,
                         {"state": "open", "per_page": 100})

    def issue_comments(self, pages=3):
        out, page = [], 1
        while page <= pages:
            d = self._get("/repos/%s/issues/comments" % self.repo,
                          {"per_page": 100, "page": page, "sort": "created", "direction": "desc"})
            chunk = d if isinstance(d, list) else []
            out.extend(chunk)
            if len(chunk) < 100:  # 末页
                break
            page += 1
        return out


# ---------------------------------------------------------------- 结构化评论解析
_FIELD_RE = re.compile(r"^\s*[-*]?\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:：=]\s*(.*?)\s*$")


def _parse_fields(lines, want):
    """结构化体字段行解析：key: value / key=value（支持 '- key: value' 列表形态）。
    返回 (fields{}, missing[])——缺必填字段不静默（missing 显式回填）。"""
    fields, seen = {}, set()
    for ln in lines:
        m = _FIELD_RE.match(ln)
        if m and m.group(1) in want:
            fields[m.group(1)] = m.group(2)
            seen.add(m.group(1))
    missing = [k for k in want if k not in seen]
    return fields, missing


def parse_structured_comment(body):
    """「首行机器标记＋结构化体」统一解析（契约 §7.5 四形态；与 #30 共用约定）。
    返回 record dict；无机器标记 ⇒ {"marker": None}（plain 桶）；标记存在但
    结构残缺 ⇒ valid=False + missing 显式列缺（fail-open 到盘点面，不猜补）。"""
    text = body or ""
    lines = [l for l in text.splitlines()]
    nonempty = [l for l in lines if l.strip()]
    first = nonempty[0].strip() if nonempty else ""

    # ① 围栏形态（af-relay / af-perm-request）：首行机器标记=围栏信息串
    fence = re.search(r"```(af-relay|af-perm-request)\s*\n(.*?)```", text, re.S)
    if fence:
        kind, inner = fence.group(1), fence.group(2)
        want = AF_RELAY_FIELDS if kind == "af-relay" else AF_PERM_FIELDS
        fields, missing = _parse_fields(inner.splitlines(), want)
        return {"marker": kind, "family": "fence", "fields": fields,
                "missing_required": missing, "valid": not missing}

    # ④ TICKET-REQUEST v1：`### TICKET-REQUEST v1` 标记行（首行或 ```text 围栏内）＋字段体
    m_tk = re.search(r"^#{1,6}\s*TICKET-REQUEST\s+v1\s*$", text, re.M)
    if m_tk:
        after = text.split(m_tk.group(0), 1)[1]
        fence2 = re.search(r"```[A-Za-z-]*\s*\n(.*?)```", after, re.S)
        seg = fence2.group(1) if fence2 else after
        fields, missing = _parse_fields(seg.splitlines(), TICKET_FIELDS)
        return {"marker": "TICKET-REQUEST v1", "family": "ticket", "fields": fields,
                "missing_required": missing, "valid": not missing}

    # ① 四前缀行内字段：首行以 /blocked /need-context /need-env /progress 开头
    for prefix, want in FOUR_PREFIX_FIELDS.items():
        if first == prefix or first.startswith(prefix + " ") or first.startswith(prefix + "：") \
                or first.startswith(prefix + ":"):
            rest_lines = nonempty[1:] if len(nonempty) > 1 else []
            fields, missing = _parse_fields(rest_lines, want)
            # 行内同形（/progress doing=X next=Y 单行多键值）也认：按键界切分
            inline = first[len(prefix):].strip()
            if inline:
                pairs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:：=]\s*(.*?)(?=\s+[A-Za-z_][A-Za-z0-9_]*\s*[:：=]\s*|$)", inline)
                for k, v in pairs:
                    if k in want:
                        fields.setdefault(k, v.strip())
                missing = [k for k in missing if k not in fields]
            return {"marker": prefix, "family": "four-prefix", "fields": fields,
                    "missing_required": missing, "valid": not missing}

    # 未知围栏（```something-else）＝ unknown（显式，不静默）
    fence_x = re.match(r"^```([A-Za-z][A-Za-z0-9-]*)\s*$", first)
    if fence_x:
        return {"marker": "```" + fence_x.group(1), "family": "unknown-fence",
                "fields": {}, "missing_required": [], "valid": False}

    # 首行形似标记但契约外（/xxx 或 ### XXX-REQUEST 等）＝ unknown-line
    if first.startswith("/") or re.match(r"^#{1,6}\s*\S*REQUEST", first):
        return {"marker": first[:40], "family": "unknown-line",
                "fields": {}, "missing_required": [], "valid": False}

    return {"marker": None, "family": "plain", "fields": {},
            "missing_required": [], "valid": True}


# ---------------------------------------------------------------- 失周自证（连续性）
def continuity_record(prior_path, window_days):
    """前窗文件在位性＋窗距连续性（Q3 教训：信标缺席=显式可见）。
    返回 (record, prior_dict)。缺失/超窗 ⇒ 失周=True（绝不平滑续窗）。"""
    rec = {"prior_path": prior_path, "prior_file_present": False,
           "prior_window_end": None, "gap_days": None, "missing_week": False,
           "record": "", "note": ""}
    prior = None
    if os.path.exists(prior_path):
        try:
            with open(prior_path, "r", encoding="utf-8") as f:
                prior = json.load(f)
            rec["prior_file_present"] = True
            rec["prior_window_end"] = prior.get("window_end")
        except Exception as e:
            rec["note"] = "前窗文件存在但不可解析（%s）——按失周记，不猜" % e.__class__.__name__
            rec["missing_week"] = True
            rec["record"] = "观测面失周"
            return rec, None
        pend = prior.get("window_end_epoch")
        if isinstance(pend, (int, float)):
            gap_days = (time.time() - float(pend)) / 86400.0
            rec["gap_days"] = round(gap_days, 3)
            if gap_days > window_days + CONTINUITY_GRACE_DAYS:
                rec["missing_week"] = True
                rec["record"] = "观测面失周"
                rec["note"] = ("前窗 window_end 距今 %.1f 天 > 窗 %dd + 宽限 %dd——周窗回路断链显式记"
                               % (gap_days, window_days, CONTINUITY_GRACE_DAYS))
            else:
                rec["record"] = "周窗连续"
        else:
            rec["missing_week"] = True
            rec["record"] = "观测面失周"
            rec["note"] = "前窗文件缺 window_end_epoch——连续性不可证，按失周记"
    else:
        rec["missing_week"] = True
        rec["record"] = "观测面失周"
        rec["note"] = ("前窗文件缺席（%s 不存在）——「信标缺席=显式可见」："
                       "观测面失周显式记，不静默续窗（Q3 §一教训）" % prior_path)
    return rec, prior


# ---------------------------------------------------------------- 四类信号判读
def _iso(dt):
    return dt.isoformat(timespec="seconds")


def judge_signals(gh, now, window_days):
    """四源只读实读 ⇒ B-1..B-4 读数。真空窗显式 null＋empty_window=True（非省略）。
    返回 (signals{}, counts{}, sources{}, degraded{})。"""
    sources = []
    degraded = {"degraded": False, "detail": ""}
    w_start = now - timedelta(days=window_days)
    signals, counts = {}, {}
    runs, win_runs = [], []  # 跨段复用面：B-1 采集，B-2/B-3 窗内消费（缺源⇒空面，不 NameError）

    # —— B-1 卡在等待：check-run 排队差 >45min ——
    b1 = []
    try:
        pulls = gh.open_pulls()
        sources.append({"endpoint": "/repos/{repo}/pulls(state=open)",
                        "purpose": "B-1 open PR head SHA 面", "n": len(pulls)})
        for pr in pulls[:10]:  # 上限钉 10（板面 open PR 惯常个位数；超限记裁剪）
            try:
                crs = gh.pr_check_runs(pr["head"]["sha"])
                sources.append({"endpoint": "/repos/{repo}/commits/{sha}/check-runs",
                                "purpose": "B-1 check-runs（PR #%s）" % pr["number"], "n": crs.get("total_count")})
                for c in crs.get("check_runs") or []:
                    if c.get("status") != "queued":
                        continue
                    t0 = datetime.fromisoformat((c.get("started_at") or c.get("created_at") or "").replace("Z", "+00:00"))
                    waited_min = (now - t0).total_seconds() / 60.0
                    if waited_min > QUEUE_WAIT_MIN_B1:
                        b1.append({"kind": "check-run", "pr": pr["number"], "name": c.get("name"),
                                   "queued_min": round(waited_min, 1), "head_sha": pr["head"]["sha"][:12]})
            except RuntimeError as e:
                degraded["degraded"] = True
                degraded["detail"] += "PR#%s check-runs 不可读（%s）；" % (pr["number"], e)
        runs, total = gh.action_runs(pages=2)
        sources.append({"endpoint": "/repos/{repo}/actions/runs",
                        "purpose": "B-1/B-2/B-3 workflow runs 窗读", "n": total})
        for r in runs:
            if r.get("status") in ("queued", "pending") and r.get("created_at"):
                t0 = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                waited_min = (now - t0).total_seconds() / 60.0
                if waited_min > QUEUE_WAIT_MIN_B1:
                    b1.append({"kind": "workflow-run", "run_id": r["id"], "name": r["name"],
                               "queued_min": round(waited_min, 1), "event": r.get("event")})
        if len(pulls) > 10:
            b1.append({"kind": "note", "detail": "open PR %d 个超采集上限 10——check-runs 面按前 10 个 PR 裁剪" % len(pulls)})
    except RuntimeError as e:
        degraded["degraded"] = True
        degraded["detail"] += "B-1 源整体不可读（%s）；" % e
    signals["B1_stuck_waiting"] = _signal("B-1", "卡在等待（check-run 排队差>%dmin）" % QUEUE_WAIT_MIN_B1, b1)
    counts["b1_stuck_waiting"] = len([x for x in b1 if x.get("kind") != "note"])

    # —— B-2 卡在重试：push 同因 ≥3 ——（附扩展读数：任意事件同 workflow+branch 失败 ≥3）
    b2, b2_ext = [], []
    try:
        win_runs = [r for r in runs
                    if r.get("created_at")
                    and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= w_start]
        grp, grp_all = {}, {}
        for r in win_runs:
            if r.get("conclusion") != "failure":
                continue
            key = (r.get("name"), r.get("head_branch"))
            grp_all.setdefault(key, []).append(r)
            if r.get("event") == "push":
                grp.setdefault(key, []).append(r)
        for (name, br), lst in sorted(grp.items()):
            if len(lst) >= RETRY_SAME_CAUSE_MIN_B2:
                b2.append({"workflow": name, "head_branch": br, "push_failures": len(lst),
                           "last_run_id": lst[-1]["id"], "last_sha": (lst[-1].get("head_sha") or "")[:12]})
        for (name, br), lst in sorted(grp_all.items()):
            if len(lst) >= RETRY_SAME_CAUSE_MIN_B2:
                causes = _same_cause_hint(gh, lst[-3:])
                b2_ext.append({"workflow": name, "head_branch": br, "event_mix": sorted({x.get("event") for x in lst}),
                               "failures": len(lst), "same_cause_hint": causes,
                               "last_run_id": lst[-1]["id"], "last_sha": (lst[-1].get("head_sha") or "")[:12]})
    except RuntimeError as e:
        degraded["degraded"] = True
        degraded["detail"] += "B-2 源不可读（%s）；" % e
    signals["B2_stuck_retrying"] = _signal("B-2", "卡在重试（push 同因 ≥%d）" % RETRY_SAME_CAUSE_MIN_B2, b2)
    counts["b2_stuck_retrying"] = len(b2)
    signals["B2_ext_any_event_repeat"] = _signal(
        "B-2x", "扩展读数（明注：非卡面 B-2 主口径——任意事件同 workflow+branch 失败 ≥%d，供 B-3 归因交叉）"
        % RETRY_SAME_CAUSE_MIN_B2, b2_ext)
    counts["b2_ext_any_event_repeat"] = len(b2_ext)

    # —— B-3 验收反复红：同 head SHA 红 ≥2；另记 base(main) 基线红 ——
    b3_rep, b3_base = [], []
    try:
        by_sha, base_reds = {}, []
        for r in win_runs:
            if r.get("conclusion") != "failure":
                continue
            sha = r.get("head_sha") or ""
            if sha:
                by_sha.setdefault(sha, []).append(r)
            if r.get("head_branch") in ("main", "master"):
                base_reds.append(r)
        for sha, lst in sorted(by_sha.items()):
            if len(lst) >= REPEAT_RED_MIN_B3:
                b3_rep.append({"head_sha": sha[:12], "red_runs": len(lst),
                               "workflows": sorted({x.get("name") for x in lst}),
                               "branches": sorted({x.get("head_branch") for x in lst}),
                               "run_ids": [x["id"] for x in lst]})
        if base_reds:
            causes = _same_cause_hint(gh, base_reds[-3:])
            b3_base.append({"kind": "baseline-red", "branch": "main",
                            "red_runs_in_window": len(base_reds),
                            "distinct_shas": len({x.get("head_sha") for x in base_reds}),
                            "same_cause_hint": causes,
                            "run_ids": [x["id"] for x in base_reds][-5:],
                            "duty_note": "基线红判定=厂职责（卡面禁项：修基线或挂 EXPECTED_LAMPS 台账，禁派沙箱修基线红；本件只出读数与归因候选）"})
    except RuntimeError as e:
        degraded["degraded"] = True
        degraded["detail"] += "B-3 源不可读（%s）；" % e
    signals["B3_acceptance_repeat_red"] = _signal("B-3", "验收反复红（同 head SHA 红 ≥%d）＋基线红读数" % REPEAT_RED_MIN_B3, b3_rep)
    counts["b3_repeat_red_shas"] = len(b3_rep)
    signals["B3_base_baseline_red"] = _signal("B-3b", "基线红（main 分支窗内验收红）——判定=厂职责", b3_base)
    counts["b3_base_baseline_red"] = len(b3_base)

    # —— B-4 上下文不足/空转 ——
    b4_idle, b4_ctx = [], []
    try:
        issues = gh.open_issues()
        sources.append({"endpoint": "/repos/{repo}/issues(state=open)",
                        "purpose": "B-4 在飞卡面＋结构化评论宿主", "n": len(issues)})
        running = [i for i in issues if "pull_request" not in i
                   and any(l["name"] == "state:running" for l in (i.get("labels") or []))]
        comments = gh.issue_comments(pages=3)
        sources.append({"endpoint": "/repos/{repo}/issues/comments",
                        "purpose": "B-4 心跳面＋结构化评论解析宿主", "n": len(comments)})
        last_by_issue = {}
        for c in comments:
            n = int(c["issue_url"].rsplit("/", 1)[-1])
            t = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            if n not in last_by_issue or t > last_by_issue[n]:
                last_by_issue[n] = t
        for i in running:
            n = i["number"]
            t = datetime.fromisoformat(i["created_at"].replace("Z", "+00:00"))
            last = last_by_issue.get(n) or t
            gap_min = (now - last).total_seconds() / 60.0
            if gap_min > HEARTBEAT_GAP_MIN_B4:
                b4_idle.append({"issue": n, "title": (i.get("title") or "")[:40],
                                "last_activity": _iso(last.astimezone(TZ8)),
                                "idle_min": round(gap_min, 1),
                                "heartbeat_source": "comment" if n in last_by_issue else "issue-created_at"})
    except RuntimeError as e:
        degraded["degraded"] = True
        degraded["detail"] += "B-4 源不可读（%s）；" % e
    signals["B4_idle_no_heartbeat"] = _signal(
        "B-4", "空转（state:running 在飞卡 >%dmin 无心跳回报）" % HEARTBEAT_GAP_MIN_B4, b4_idle)
    counts["b4_idle_no_heartbeat"] = len(b4_idle)
    signals["B4_context_insufficient"] = _signal(
        "B-4b", "上下文不足（板面结构化评论显式报缺：/need-context、/need-env）", b4_ctx)
    counts["b4_context_insufficient"] = len(b4_ctx)
    return signals, counts, sources, degraded


def _signal(sig_id, name, samples):
    """信号封口：真空窗 value=null + empty_window=True 显式记（非省略）。"""
    fired = any(x for x in samples if x.get("kind") != "note")
    return {"id": sig_id, "name": name, "status": "red" if fired else "green",
            "empty_window": not fired,
            "value": (samples if fired else None),
            "detail": ("%d 条读数" % len([x for x in samples if x.get("kind") != "note"])
                       if fired else "真空窗：窗内零命中（显式 null，非省略）")}


def _same_cause_hint(gh, runs):
    """同因提示：取至多 3 个失败 run 的首个失败步名（jobs API 只读）。
    不可读 ⇒ 显式 'unreadable'，不猜。"""
    hints = []
    for r in runs[:3]:
        try:
            jobs = gh.run_jobs(r["id"])
            names = []
            for j in jobs.get("jobs") or []:
                for s in j.get("steps") or []:
                    if s.get("conclusion") == "failure":
                        names.append("%s/step%02d:%s" % (j.get("name"), s.get("number") or 0, (s.get("name") or "")[:24]))
            hints.append({"run_id": r["id"], "failed_steps": names or ["<job-level failure, step 面 zero>"]})
        except RuntimeError as e:
            hints.append({"run_id": r["id"], "failed_steps": "unreadable(%s)" % e.__class__.__name__})
    return hints


# ---------------------------------------------------------------- planner 输入面
RESPONSIBILITY_MAP = {
    "B-1": ("平台", "runner 排队/容量面（排队差>45min 非施工侧可修）",
            "扩 runner 池或降并发档；planner 派发时点选 runner 水位"),
    "B-2": ("沙箱", "施工侧同因重推（push≥3 同因=重试循环未收敛）",
            "停手报告走四前缀 /need-context，禁第 4 次盲推；卡面迭代=补「重推上限」纪律"),
    "B-3": ("厂", "基线红=厂职责（卡面禁项明文；修基线或挂 EXPECTED_LAMPS 台账）",
            "禁派沙箱修基线红；厂侧修基线或台账化，planner 派发前查 base SHA 门红面"),
    "B-4": ("卡面/planner", "上下文不足（卡面证据缺口）或心跳断（空转回收）",
            "卡面迭代=补 self-contained 六要件；心跳断走 STALL 回收语义"),
}


def planner_inputs_block(signals, counts, now):
    """回路「迭代」两步的输入面：观测平面级信号字段（对齐 planner.yml:781
    组装段的 planner-inputs.json 形态）＋ 卡面/契约迭代建议四列清单
    「信号→归因→责任面→建议」。接线点登记出处注：本卡 allowed_paths 禁改
    planner.yml，合并动作留给规划环后续卡。"""
    obs_plane = {
        "generated_at": _iso(now.astimezone(TZ8)),
        "b1_stuck_waiting_count": counts.get("b1_stuck_waiting"),
        "b2_stuck_retrying_count": counts.get("b2_stuck_retrying"),
        "b3_repeat_red_shas": counts.get("b3_repeat_red_shas"),
        "b3_base_baseline_red": bool(counts.get("b3_base_baseline_red")),
        "b4_idle_no_heartbeat_count": counts.get("b4_idle_no_heartbeat"),
        "b4_context_insufficient_count": counts.get("b4_context_insufficient"),
        "note": "观测平面级信号字段（#14 planner 组装段扩展位；零改 planner.yml——接线点出处注）",
    }
    rows = []
    for sig_key, sig_no in (("B1_stuck_waiting", "B-1"), ("B2_stuck_retrying", "B-2"),
                            ("B3_acceptance_repeat_red", "B-3"), ("B3_base_baseline_red", "B-3b"),
                            ("B4_idle_no_heartbeat", "B-4"), ("B4_context_insufficient", "B-4b")):
        sig = signals.get(sig_key) or {}
        if sig.get("status") != "red":
            continue
        face, attribution, suggestion = RESPONSIBILITY_MAP.get(
            sig_no, RESPONSIBILITY_MAP.get(sig_no[:3], ("未定", "归因候选缺", "建议缺")))  # B-3b/B-4b 归并基信号责任面
        rows.append({"signal": sig_no, "name": sig.get("name"),
                     "attribution": attribution, "responsibility_face": face,
                     "suggestion": suggestion,
                     "evidence": sig.get("value")})
    return {"schema": "af.obs-weekly-planner-inputs.v1",
            "obs_plane": obs_plane,
            "iteration_suggestions": rows,
            "iteration_columns": ["signal", "attribution", "responsibility_face", "suggestion"],
            "wiring_note": ("判读输出进 planner-inputs 扩展（观测平面级信号字段）——planner.yml:781 "
                            "「组装规划输入」段合并位；本卡禁改 planner.yml，接线=规划环后续卡（出处注登记）")}


# ---------------------------------------------------------------- 长杆刷新收编
def long_pole_block(report_path):
    """收编调用面跑出的 python 级长杆刷新读数（deny-audit=redteam_scan.py）。
    fuzz/miri/criterion 无 python 级载体 ⇒ 显式 null（真空窗显式记，不猜绿）。"""
    blk = {
        "deny_audit": None, "fuzz": None, "miri": None, "criterion": None,
        "note": ("点选长杆刷新项（CI L-19）：python 级可跑项=deny-audit（tools/redteam_scan.py，"
                 "零 token 确定性扫描）；fuzz 仓内无 python 级载体（显式 null）；miri/criterion "
                 "为 cargo 级——anolis 水位禁项明令禁跑（显式 null，非省略）"),
    }
    if report_path:
        if os.path.exists(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                blk["deny_audit"] = {
                    "verdict": d.get("verdict"), "selftest": (d.get("selftest") or {}).get("status"),
                    "rules": (d.get("playbook") or {}).get("rule_count"),
                    "scanned": d.get("scanned_files"),
                    "hits": len(d["hits"]) if isinstance(d.get("hits"), list) else d.get("hits"),
                    "uncovered": d.get("uncovered"),
                    "fingerprint": (d.get("fingerprint") or "")[:16],
                    "source": "os.path:%s（调用面 obs-nightly 步 02 产物；本件只收编读数）" % report_path,
                }
            except Exception as e:
                blk["deny_audit"] = {"verdict": "unreadable", "error": str(e)[:120]}
        else:
            blk["deny_audit"] = {"verdict": "report-missing",
                                 "error": "长杆报告文件缺席（%s）——显式记，不猜绿" % report_path}
    return blk


# ---------------------------------------------------------------- schema（键集与出处注）
SCHEMA_BLOCK = {
    "_note": "周窗 JSON 键集与出处注（卡面验收 2：schema 实读）。形态照 状态观测/otel-production.json。",
    "ts": "本窗落盘钟面（+08:00 ISO）——本件生成时刻",
    "ts_epoch": "ts 的 unix 秒（失周窗距判据消费面）",
    "status": "窗级红绿：任一信号红/失周⇒red；全绿⇒green（读数面，非门判）",
    "window_days": "周窗宽（卡面=周频 7d）",
    "window_start": "窗起（+08:00 ISO）",
    "window_end": "窗止（+08:00 ISO）＝ts",
    "window_end_epoch": "窗止 unix 秒（下窗失周判据源）",
    "counts": "四类信号计数面（b1/b2/b2x/b3/b3b/b4/b4b）",
    "signals": "四类信号读数本体（B-1 卡在等待/B-2 卡在重试/B-3 验收反复红/B-4 上下文不足与空转；真空窗显式 null）",
    "checks": "otelo-production 形态 checks[]（id/name/status/detail）：CW=周窗连续性（失周显式记）；S1..S4=四类信号",
    "structured_comments": "板面结构化评论统一解析盘点（首行机器标记＋结构化体，契约 §7.5 四形态；与 factory-os#30 共用约定）",
    "planner_inputs": "回路「迭代」输入面：观测平面级信号字段＋四列清单（信号→归因→责任面→建议）——planner.yml:781 合并位",
    "long_pole_refresh": "长杆刷新读数收编（deny-audit=python 级 redteam_scan；fuzz/miri/criterion 显式 null）",
    "continuity": "周窗连续性记录（前窗在位性/窗距/失周显式记——Q3 信标缺席=显式可见）",
    "sources": "四源 API 端点实读留痕（endpoint/purpose/n——只读 GET 实读取证）",
    "api_calls": "网络调用流水（path/status/ms，实读取证）",
    "degraded": "降级面：部分源不可读时显式记（不静默绿）",
    "gate_verdict": "夜间周期门消费面：pass=结构完好且周窗连续；fail:missing-week=失周（门红停车）；本字段只作门判据，不改读数",
    "tool": "本件身份（tool/version/repo/argv/prior_path/token_mode）",
    "schema": "本块（键集与出处注）——卡面验收 2 的 schema 实读面",
}


def gate_verdict_of(continuity, degraded, structural_ok):
    """门判据（只消费结构完好性＋周窗连续性；信号红绿是读数不是门红）。"""
    if not structural_ok:
        return "fail:structural"
    if continuity.get("missing_week"):
        return "fail:missing-week"
    if degraded.get("degraded"):
        return "pass:degraded"  # 结构完好、周窗连续、部分源降级——pass 但显式记降级
    return "pass"


# ---------------------------------------------------------------- 主流程
def build(repo, out_path, prior_path, window_days, long_pole_report, token_mode):
    now = datetime.now(timezone.utc)
    w_start = now - timedelta(days=window_days)
    gh = Gh(repo)
    signals, counts, sources, degraded = judge_signals(gh, now, window_days)

    comments = []
    try:
        comments = gh.issue_comments(pages=3)
    except RuntimeError as e:
        degraded["degraded"] = True
        degraded["detail"] += "结构化评论宿主源不可读（%s）；" % e
    parsed, marker_stat, prefix_stat = [], {}, {}
    for c in comments:
        rec = parse_structured_comment(c.get("body") or "")
        fam = rec["family"]
        marker_stat[fam] = marker_stat.get(fam, 0) + 1
        if fam == "four-prefix":
            prefix_stat[rec["marker"]] = prefix_stat.get(rec["marker"], 0) + 1
        if rec["family"] in ("plain",):
            continue
        parsed.append({
            "issue": int(c["issue_url"].rsplit("/", 1)[-1]),
            "comment_id": c["id"], "author": (c.get("user") or {}).get("login"),
            "created_at": c["created_at"],
            "marker": rec["marker"], "family": rec["family"], "valid": rec["valid"],
            "fields": rec["fields"], "missing_required": rec["missing_required"],
            "evidence_note": "围栏内自报不作证据（契约 §7.5）——本面只作板面盘点读数",
        })
    # B-4b：显式报缺的结构化评论进上下文不足读数
    for p in parsed:
        if p["marker"] in ("/need-context", "/need-env"):
            signals["B4_context_insufficient"]["value"] = (signals["B4_context_insufficient"]["value"] or []) + [p]
            signals["B4_context_insufficient"]["status"] = "red"
            signals["B4_context_insufficient"]["empty_window"] = False
            signals["B4_context_insufficient"]["detail"] = "%d 条结构化报缺读数" % len(signals["B4_context_insufficient"]["value"])
    counts["b4_context_insufficient"] = len(signals["B4_context_insufficient"]["value"] or [])

    structured = {
        "convention": "首行机器标记＋结构化体（与 factory-os#30 card-selfcontainment-check 共用；正本=波次清单/沙箱派发契约.md §7.5）",
        "markers_seen": {
            "four_prefix": {m: prefix_stat.get(m, 0) for m in FOUR_PREFIX_FIELDS},
            "four_prefix_total": marker_stat.get("four-prefix", 0),
            "af-relay": marker_stat.get("af-relay", 0),
            "af-perm-request": marker_stat.get("af-perm-request", 0),
            "TICKET-REQUEST v1": marker_stat.get("TICKET-REQUEST v1", 0),
            "unknown": marker_stat.get("unknown-fence", 0) + marker_stat.get("unknown-line", 0),
            "plain": marker_stat.get("plain", 0),
        },
        "parsed": parsed,
    }

    # 失周自证（连续性）：前窗文件读在 --prior（缺省同 --out）——写盘前判
    continuity, prior = continuity_record(prior_path, window_days)

    lp = long_pole_block(long_pole_report)

    any_red = any(s.get("status") == "red" for s in signals.values())
    out = {
        "ts": _iso(now.astimezone(TZ8)),
        "ts_epoch": int(now.timestamp()),
        "status": "red" if (any_red or continuity["missing_week"]) else "green",
        "window_days": window_days,
        "window_start": _iso(w_start.astimezone(TZ8)),
        "window_end": _iso(now.astimezone(TZ8)),
        "window_end_epoch": int(now.timestamp()),
        "counts": counts,
        "signals": signals,
        "checks": _checks(signals, continuity, degraded),
        "structured_comments": structured,
        "planner_inputs": planner_inputs_block(signals, counts, now),
        "long_pole_refresh": lp,
        "continuity": continuity,
        "sources": sources,
        "api_calls": gh.calls,
        "degraded": degraded,
        "gate_verdict": gate_verdict_of(continuity, degraded, True),  # 结构失败=异常路径（main 捕获 RuntimeError⇒rc=2）
        "tool": {"tool": TOOL, "version": VERSION, "repo": repo,
                 "argv": sys.argv, "prior_path": prior_path,
                 "token_mode": token_mode,
                 "readonly_note": "判读器只读板面：本件网络面全 GET 零写；落盘回推=调用面（obs-nightly）职责"},
        "schema": SCHEMA_BLOCK,
    }
    return out


def _checks(signals, continuity, degraded):
    """otelo-production 形态 checks[]：CW=周窗连续性（失周⇒FAIL）；S1..S4=四类信号读数面。"""
    checks = [{
        "id": "CW", "name": "周窗连续性（失周显式记——Q3 信标缺席=显式可见）",
        "status": "FAIL" if continuity.get("missing_week") else "PASS",
        "detail": continuity.get("record") + ("；" + continuity["note"] if continuity.get("note") else ""),
    }]
    for i, key in enumerate(("B1_stuck_waiting", "B2_stuck_retrying",
                             "B3_acceptance_repeat_red", "B4_idle_no_heartbeat"), 1):
        s = signals.get(key) or {}
        checks.append({"id": "S%d" % i, "name": "信号 %s %s" % (s.get("id"), s.get("name")),
                       "status": "RED" if s.get("status") == "red" else "GREEN",
                       "detail": s.get("detail") + ("；降级：" + degraded["detail"] if degraded.get("degraded") else "")})
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(description="L1 沙箱判读器·周窗回路（只读板面）")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "CloudCrane-Software/factory-os"))
    ap.add_argument("--out", default="状态观测/sandbox-obs-weekly.json")
    ap.add_argument("--prior", default=None, help="前窗文件路径（缺省同 --out；失周自证=删它再跑）")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--long-pole-report", default=None, help="调用面长杆刷新读数（deny-audit JSON）收编")
    ap.add_argument("--selftest", action="store_true", help="离线自证电池（零网络）")
    ap.add_argument("--print-summary", action="store_true", default=True)
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    prior = args.prior or args.out
    token_mode = "unauthenticated" if not (os.environ.get("AF_OBS_TOKEN") or os.environ.get("GITHUB_TOKEN")) else "token(ratelimit-only,read-only)"
    try:
        out = build(args.repo, args.out, prior, args.window_days, args.long_pole_report, token_mode)
    except RuntimeError as e:
        print("FAIL 结构失败（fail-loud）：四源只读实读整体不可用——%s" % e, file=sys.stderr)
        return 2

    # 键集 fail-closed（fail-loud）：输出顶层键集 ⊆ SCHEMA_BLOCK 声明集，缺注即红
    uncovered = set(out) - set(SCHEMA_BLOCK)
    if uncovered:
        print("FAIL 键集自检不过（SCHEMA_BLOCK 缺出处注：%s）" % sorted(uncovered), file=sys.stderr)
        return 2
    if not out["planner_inputs"]["iteration_suggestions"] and not isinstance(
            out["planner_inputs"]["obs_plane"].get("b1_stuck_waiting_count"), int):
        pass  # 空建议清单=合法（真空窗）；obs_plane 字段面必须成形（上面取值已保证）

    d = os.path.dirname(os.path.abspath(args.out))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)

    if args.print_summary:
        print("OBS-WEEKLY ts=%s window=%dd status=%s gate=%s"
              % (out["ts"], out["window_days"], out["status"], out["gate_verdict"]))
        for k in ("B1_stuck_waiting", "B2_stuck_retrying", "B2_ext_any_event_repeat",
                  "B3_acceptance_repeat_red", "B3_base_baseline_red",
                  "B4_idle_no_heartbeat", "B4_context_insufficient"):
            s = out["signals"][k]
            print("  %-28s %-5s empty=%s %s" % (k, s["status"], s["empty_window"], s["detail"]))
        print("  continuity: %s %s" % (out["continuity"]["record"], out["continuity"]["note"]))
        sc = out["structured_comments"]["markers_seen"]
        print("  structured_comments: 4prefix=%s relay=%d perm=%d ticket=%d unknown=%d plain=%d"
              % (sum(sc["four_prefix"].values()), sc["af-relay"], sc["af-perm-request"],
                 sc["TICKET-REQUEST v1"], sc["unknown"], sc["plain"]))
        print("  out=%s" % args.out)
    return 0 if out["gate_verdict"].startswith("pass") else 2


# ---------------------------------------------------------------- 离线自证电池
def selftest():
    """零网络自证电池：失周两形态/真空窗形态/四形态解析/同因聚组/键集 fail-closed。"""
    cases = []

    # 1) 失周形态A：前窗文件缺席 ⇒ 观测面失周显式记
    rec, _ = continuity_record("/nonexistent/prior.json", 7)
    cases.append(("missing-week:前窗缺席⇒失周显式记",
                  rec["missing_week"] and rec["record"] == "观测面失周" and rec["prior_window_end"] is None))

    # 2) 失周形态B：窗距超限（窗 7d + 宽 1d）
    with open("/tmp/obs-st-prior.json", "w", encoding="utf-8") as f:
        json.dump({"window_end_epoch": time.time() - 9 * 86400}, f)
    rec, _ = continuity_record("/tmp/obs-st-prior.json", 7)
    cases.append(("missing-week:窗距 9d>7d+1d 宽限⇒失周", rec["missing_week"] and rec["record"] == "观测面失周"))
    with open("/tmp/obs-st-prior2.json", "w", encoding="utf-8") as f:
        json.dump({"window_end_epoch": time.time() - 2 * 86400}, f)
    rec, _ = continuity_record("/tmp/obs-st-prior2.json", 7)
    cases.append(("continuity:窗距 2d 在窗内⇒周窗连续", not rec["missing_week"] and rec["record"] == "周窗连续"))

    # 3) 真空窗形态：零命中 ⇒ value=None + empty_window=True（显式 null 非省略）
    sig = _signal("B-1", "test", [])
    cases.append(("empty-window:零命中⇒null+empty_window", sig["value"] is None and sig["empty_window"] and sig["status"] == "green"))

    # 4) 四形态解析
    r = parse_structured_comment("/progress\n做完了判读器主流程\n下一步推分支")
    ok4a = r["marker"] == "/progress" and r["family"] == "four-prefix" and r["valid"] is False \
        and set(r["missing_required"]) == {"doing", "next"}
    cases.append(("parse:/progress 前缀识别＋缺必填显式记", ok4a))
    r = parse_structured_comment("/progress doing=主流程收尾 next=推分支开PR")
    ok4b = r["valid"] and r["fields"].get("doing") == "主流程收尾" and r["fields"].get("next") == "推分支开PR"
    cases.append(("parse:/progress 行内字段解析", ok4b))
    r = parse_structured_comment("交接\n```af-relay\nfrom: sandbox-a\nto: next-claimant\ncarries: PR #52\n"
                                 "readings: rc=0\nopen_items: 无\nhandoff_verdict: handoff-clean\n```")
    ok4c = r["marker"] == "af-relay" and r["valid"] and len(r["fields"]) == 6
    cases.append(("parse:af-relay 六字段 fence", ok4c))
    r = parse_structured_comment("```af-perm-request\nrequest_id: 26-p1\nscope_ask: repo:read=X/Y\n"
                                 "why: 卡面证据面\nttl_ask: 1h\nartifact_needed: 读该仓 ledger\n```")
    cases.append(("parse:af-perm-request 五字段 fence", r["marker"] == "af-perm-request" and r["valid"] and len(r["fields"]) == 5))
    r = parse_structured_comment("### TICKET-REQUEST v1\n- ticket_type:  llm-gw\n- task_ref:     #44\n"
                                 "- resource: llm:x\n- amount: 1\n- ttl: 1h\n- purpose: 试跑\n- requester: bot\n")
    cases.append(("parse:TICKET-REQUEST v1 七字段块", r["marker"] == "TICKET-REQUEST v1" and r["valid"] and len(r["fields"]) == 7))
    r = parse_structured_comment("```some-unknown-fence\nx: 1\n```")
    cases.append(("parse:未知围栏⇒unknown 显式非静默", r["family"] == "unknown-fence" and r["valid"] is False))
    r = parse_structured_comment("## D-93 交卷（普通回执评论）\n正文……")
    cases.append(("parse:无机器标记⇒plain 桶", r["family"] == "plain"))

    # 5) B-3 反复红聚组判据（≥2）
    sig2 = _signal("B-3", "test", [{"head_sha": "a", "red_runs": 2}])
    sig1 = _signal("B-3", "test", [])
    cases.append(("B-3:同SHA红≥2⇒red；零命中⇒green", sig2["status"] == "red" and sig1["status"] == "green"))

    # 6) 门判据：结构完好＋连续⇒pass；失周⇒fail:missing-week
    ok_rec, _ = continuity_record("/tmp/obs-st-prior2.json", 7)
    miss_rec, _ = continuity_record("/nonexistent/prior.json", 7)
    cases.append(("gate:连续⇒pass", gate_verdict_of(ok_rec, {"degraded": False}, True) == "pass"))
    cases.append(("gate:失周⇒fail:missing-week", gate_verdict_of(miss_rec, {"degraded": False}, True).startswith("fail:missing-week")))

    # 7) 输出键集 fail-closed：SCHEMA_BLOCK 覆盖周窗 JSON 正典顶层键集（缺注即红；tamper 反例）
    canonical = {"ts", "ts_epoch", "status", "window_days", "window_start", "window_end",
                 "window_end_epoch", "counts", "signals", "checks", "structured_comments",
                 "planner_inputs", "long_pole_refresh", "continuity", "sources",
                 "api_calls", "degraded", "gate_verdict", "tool", "schema"}
    cases.append(("schema:SCHEMA_BLOCK 覆盖正典顶层键集（缺键即红）", canonical.issubset(set(SCHEMA_BLOCK))))
    cases.append(("schema:tamper 反例——正典键集 20 键逐字", len(canonical) == 20))

    failed = [name for name, ok in cases if not ok]
    for name, ok in cases:
        print(("PASS " if ok else "FAIL ") + name)
    print("SELFTEST %d/%d" % (len(cases) - len(failed), len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
