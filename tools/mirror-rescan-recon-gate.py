#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/mirror-rescan-recon-gate.py — 公开面全量复扫新鲜度门（D-153 · ESC-15 · 卡 #249）。

【锚号】D-153（账本/阶段欠账台账.md D-153 行）　【卡号】factory-os issue #249
  （wave-16 · w16-d153-mirror-rescan-gate · 允许路径=本件单件；本件=阶段一·门本体，
   阶段二＝tools/mirror-disclose.sh 增 --full 模式与读数件落地，另卡不碰本卡；
   豁免首硬期限 2026-12-05 关联 issue #2）。

【为什么建本门（D-153 债本体）】
  镜像披露扫描器+豁免清单+到期即红机制齐备（mirror-disclose.sh 18 模式）但
  「全量复扫的排程腿」缺位——到期判定只在脚本被跑时发生，无门保证全量面按期
  被跑（ESC-15 新门设计栏）。台账 D-153 行载现势：存量 8 VERIFIED+63 PENDING
  （G-13 已禁整批落地），mirror-scan-allowlist.json 现势 84 条全部
  expires=2026-12-05（2026-11-09 本机实测计数）。本门把「上次全量复扫」的
  读数件做成机器断言：时间戳新鲜（age>7d⇒红）、覆盖面完整（scope/patterns/
  hits/reds 逐项 fail-closed）、豁免到期前 7d 复核清单行在场（挂裁或续期，
  禁静默过期）——三腿合出「全量面按期被跑且跑全了」的门级证明，缺读数件/
  坏形一律红不猜绿。

【阈值与校准来源】
  STALE_AGE_S=604800（7d）＝D-153 修复方向「读数件新鲜度断言（上次全量扫
  时间戳 age>7d⇒红）」原值；周期对齐豁免 expiry 最小粒度周级（复扫 cron 建议
  周级，阶段二接线，本门只消费读数件）。EXPIRY_REVIEW_WINDOW_D=7＝D-153
  前置检查「expires=2026-12-05 项到期前 7d 生成复核清单行」原值。单档红无
  amber 档：锚行只规定 7d 一档（周级预算整档耗尽即红，不设预警中间档——
  与 telemetry 门（D-146/ESC-04 面双档）不同源，此差异在此注明）。
  时钟宽限 CLOCK_SKEW_GRACE_S=300：finished_utc 落于未来且超宽限 ⇒ 红
  （时钟后跳/时间戳不可证）；宽限内未来戳按 age=0 判新鲜（沿 D-146 门同款）。
  MIN_PATTERNS=18＝mirror-disclose.sh 模式表现势（13 通用 G-01..G-13＋
  5 项目自有 P-01..P-05）；模式数低于现势 ⇒ 覆盖面不完整红（扫描器降级跑
  旧模式表不得静默过门）。

【判定语义（三腿，对读数件 af.mirror-rescan-reading/v1）】
  · leg-F 新鲜度：age = now(UTC) − scan.finished_utc：
      age > 7d ⇒ RED（点名上次全量扫距今天数与「复扫 cron 排程腿」处置方向）；
      其余（含宽限内未来戳）⇒ 新鲜过（INFO）。
  · leg-C 覆盖面（全量完整性，逐项 fail-closed）：
      scan.scope=="full"（增量/局部扫描读数不得冒充全量）；patterns≥18；
      commits≥1 且 blobs≥1（历史面为空不可证全量）；unexempt_hits==0 且
      guardrail_reds==0（复扫自身裁决面绿——命中/护栏红项见 mirror-disclose
      扫描件处置，本门只认零）；source_head 为 40/64 位 hex（钉住被扫树）；
      binary_compressed 为 ≥0 整数（压缩容器＝如实登记的不覆盖面，>0 时 INFO
      点名「披露前人工复核」，非静默跳过故不连坐红）。任一缺席/坏形 ⇒ 红。
  · leg-E 到期复核（禁静默过期，按日粒度 days_left=expires−today）：
      days_left<0（已过期）：复核清单行必须在场且处置有效，缺 ⇒ RED 静默过期；
      0≤days_left≤7（临期窗）：复核清单行必须在场，缺 ⇒ RED 复核清单行缺位；
      days_left>7：无义务（行提前在场 ⇒ INFO 提前复核）。
      行形制：disposition∈{renew=续期, revoke=挂裁}；renew 须带 new_expires
      且严格后移（>原 expires）并 ≥今日；reviewed_utc 须 ISO 8601 带时区；
      reviewer 非空。指向不在场到期日的行/同行重复 ⇒ 红（日期错写会使真到期
      日的行缺位，fail-closed）。
  · 文件级：非 JSON/顶层非对象/schema 不符/scan·expiring·expiry_review 段
    缺席 ⇒ 红 rc=1（不猜绿）；expiring=[]（豁免面已清零）为合法绿态；
    --check 缺件/不可读 ⇒ 红 rc=1（缺读数件 fail-closed）。

【读数件契约（schema af.mirror-rescan-reading/v1；阶段二 --full 产件目标形】
  {"schema": "af.mirror-rescan-reading/v1",
   "scan": {"scope": "full", "finished_utc": "2026-11-09T02:58:00Z",
            "source_head": "<40 位 hex>", "patterns": 18, "commits": 311,
            "blobs": 1204, "unexempt_hits": 0, "guardrail_reds": 0,
            "binary_compressed": 0},
   "expiring": [{"expires": "2026-12-05", "entries": 84}, …],
   "expiry_review": [{"expires": "2026-12-05", "disposition": "renew",
                      "new_expires": "2027-06-05",
                      "reviewed_utc": "2026-11-28T09:00:00Z",
                      "reviewer": "清障员·xxx"}, …]}}

【退出码】0=绿（三腿全过）；1=红（陈旧/覆盖不完整/到期复核缺位/坏形/缺件，
  逐条点名）；2=CLI 用法错（未选模式/夹具名不识——非数据裁决面）。

【用法】
  python3 -I tools/mirror-rescan-recon-gate.py --selftest       # 内嵌夹具全跑（rc=0）
  python3 -I tools/mirror-rescan-recon-gate.py --fixture <名>   # 单夹具（rc=该夹具裁决）
  python3 -I tools/mirror-rescan-recon-gate.py --check <读数件路径>  # 真查读数件
  夹具名：fresh-ok / fresh-near-7d-line / stale-over-7d / stale-far-30d /
          due-review-row-present / due-review-row-missing / due-row-bad-disposition /
          due-renew-not-later / expired-silent / expired-renewed-valid /
          expired-renewed-into-past / orphan-review-row / duplicate-review-row /
          coverage-patterns-short / coverage-hits-nonzero / coverage-reds-nonzero /
          coverage-scope-partial / coverage-empty-history / bad-source-head /
          compressed-registered / missing-finished-ts / naive-ts / future-ts /
          bad-expires-date / empty-reading / bad-json / wrong-schema / scan-missing
  （三态验收语义夹具：fresh=fresh-ok（rc=0）；age>7d=stale-over-7d（rc=1）；
   临期=due-review-row-present（rc=0）/ due-review-row-missing（rc=1 复核清单
   行在场断言之负例）；2026-12-05 真场景由 selftest 钉钟单元断言覆盖。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 mirror-disclose.sh/
  all-gates.sh/gate-pins.list——mirror-disclose.sh 判据面禁改禁抄其豁免，本门
  只消费读数件契约）；零网络、零凭据、零写入（--check 只读）；本门不扫凭据
  形态（凭据面扫描归 mirror-disclose.sh 模式表），夹具零凭据串；红不猜绿
  （缺读数件/坏形/未来戳/覆盖缺项即红）；selftest 全部真跑不编造。
"""

import argparse
import datetime
import json
import re
import sys

SCHEMA = "af.mirror-rescan-reading/v1"
STALE_AGE_S = 7 * 86400          # >7d ⇒ RED（D-153 修复方向原值；周级对齐）
EXPIRY_REVIEW_WINDOW_D = 7       # 到期前 7d ⇒ 复核清单行在场义务（D-153 前置检查）
CLOCK_SKEW_GRACE_S = 300         # 未来戳宽限：超 5min ⇒ 时钟不可证红（沿 D-146 门同款）
MIN_PATTERNS = 18                # mirror-disclose.sh 模式表现势（13 通用+5 项目自有）

GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "INFO": 1}
DISPOSITIONS = {"renew": "续期", "revoke": "挂裁"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_ts(value):
    """ISO 8601 带时区解析（Z 或 ±hh:mm 偏移）；缺席/无时区/非法 ⇒ None（调用方
    按 fail-closed 红：无时区基准的时间戳不能对 UTC 钟算龄，不猜）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        ts = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None or ts.utcoffset() is None:
        return None
    return ts.astimezone(datetime.timezone.utc)


def parse_date(value):
    """严格 YYYY-MM-DD（日历合法）；其余 ⇒ None（到期日坏形 fail-closed 红）。"""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _is_count(value):
    """非负整数形（排除 bool——True 是 int 子类，计数面不得混入布尔）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# ---------------------------------------------------------------- leg-F 新鲜度 --
def judge_freshness(finished_raw, now):
    """leg-F：上次全量复扫时间戳新鲜度。返回 (findings, finished_ts or None)。"""
    ts = parse_ts(finished_raw)
    if ts is None:
        return [red("scan.finished_utc",
                    "finished_utc 缺席/非 ISO 8601 带时区时间戳（实得 %r）——"
                    "上次全量复扫时间无从对账，fail-closed 不猜绿"
                    % (finished_raw,))], None
    age_s = (now - ts).total_seconds()
    if age_s < -CLOCK_SKEW_GRACE_S:
        return [red("scan.finished_utc",
                    "finished_utc 落于未来（距今 -%.0fs，超 %ds 宽限）——时钟后跳/"
                    "时间戳不可证，不猜绿" % (-age_s, CLOCK_SKEW_GRACE_S))], None
    if age_s < 0:
        age_s = 0.0
    if age_s > STALE_AGE_S:
        return [red("scan.finished_utc",
                    "全量复扫陈旧 RED：上次全量扫距今 %.1fd（>%.0fd 档，周级预算"
                    "整档耗尽）——处置：复核复扫 cron 排程腿是否断供（D-153 排程"
                    "腿缺位债本体：到期判定只在扫描器被跑时发生，无门保证按期被跑"
                    "即本门所守）；豁免临期叠加陈旧 ⇒ 先复扫后裁到期"
                    % (age_s / 86400.0, STALE_AGE_S / 86400))], ts
    return [info("scan.finished_utc",
                 "新鲜：上次全量扫距今 %.1fh（≤%.0fd 档）"
                 % (age_s / 3600.0, STALE_AGE_S / 86400))], ts


# ---------------------------------------------------------------- leg-C 覆盖面 --
def judge_coverage(scan, origin):
    """leg-C：全量覆盖面完整性（逐项 fail-closed）。返回 findings。"""
    if not isinstance(scan, dict):
        return [red("scan", "scan 段缺席/非对象（实得 %s）——读数件结构损坏，"
                    "不猜绿" % (type(scan).__name__,))]
    findings = []
    if scan.get("scope") != "full":
        findings.append(red("scan.scope",
                            "scope 缺席/非 full（实得 %r）——增量/局部扫描读数不得"
                            "冒充全量复扫（D-153 债本体是「全量面按期被跑」）"
                            % (scan.get("scope"),)))
    n_pat = scan.get("patterns")
    if not _is_count(n_pat) or n_pat < MIN_PATTERNS:
        findings.append(red("scan.patterns",
                            "patterns 缺席/非 ≥%d 整数（实得 %r）——模式数低于"
                            "扫描器模式表现势 ⇒ 覆盖面不完整（降级跑旧模式表"
                            "不得静默过门）" % (MIN_PATTERNS, n_pat)))
    for key, why in (("commits", "历史面提交数为空不可证全量"),
                     ("blobs", "历史面对象数为空不可证全量")):
        n = scan.get(key)
        if not _is_count(n) or n < 1:
            findings.append(red("scan.%s" % key,
                                "%s 缺席/非 ≥1 整数（实得 %r）——%s"
                                % (key, n, why)))
    for key, label in (("unexempt_hits", "未豁免命中"),
                       ("guardrail_reds", "护栏红")):
        n = scan.get(key)
        if not _is_count(n):
            findings.append(red("scan.%s" % key,
                                "%s 缺席/非 ≥0 整数（实得 %r）——复扫裁决面计数"
                                "不可证，fail-closed" % (key, n)))
        elif n != 0:
            findings.append(red("scan.%s" % key,
                                "%s=%d 非零——上次全量复扫自身裁决不绿（%s项须先"
                                "在 mirror-disclose 扫描件面处置：真凭据 denylist "
                                "移除、误报才进豁免），处置完成前读数件不得过门"
                                % (key, n, label)))
    head = scan.get("source_head")
    if not isinstance(head, str) or not SHA_RE.match(head.strip()):
        findings.append(red("scan.source_head",
                            "source_head 非 40/64 位 hex 对象号（实得 %r）——被扫"
                            "树钉不住，覆盖面无从对账" % (head,)))
    n_bc = scan.get("binary_compressed")
    if not _is_count(n_bc):
        findings.append(red("scan.binary_compressed",
                            "binary_compressed 缺席/非 ≥0 整数（实得 %r）——压缩"
                            "容器面计数不可证（非静默跳过台账语义要求登记在场）"
                            % (n_bc,)))
    elif n_bc > 0:
        findings.append(info("scan.binary_compressed",
                             "压缩容器 %d 件＝如实登记的不覆盖面（明文探针与模式"
                             "扫描均不适用）——披露前人工复核，非静默跳过故不"
                             "连坐红" % (n_bc,)))
    if not findings:
        findings.append(info("scan",
                             "覆盖面完整：scope=full · patterns=%d（≥%d）· "
                             "commits=%d · blobs=%d · 未豁免命中=0 · 护栏红=0"
                             % (n_pat, MIN_PATTERNS, scan.get("commits"),
                                scan.get("blobs"))))
    return findings


# ------------------------------------------------------------- leg-E 到期复核 --
def _row_form_findings(row, idx, expiring_dates):
    """单条复核清单行形制判定。返回 findings（空=形制过）；附 (expires_str, ok)。"""
    tag = "expiry_review#%d" % idx
    if not isinstance(row, dict):
        return [red(tag, "复核清单行非对象（%r）——清单结构损坏，不猜绿"
                    % (row,))]
    exp_raw = row.get("expires")
    exp = parse_date(exp_raw)
    if exp is None:
        return [red(tag, "expires 缺席/非 YYYY-MM-DD 日历合法日期（实得 %r）——"
                    "行指向不可证" % (exp_raw,))]
    disp = row.get("disposition")
    if disp not in DISPOSITIONS:
        return [red(tag, "disposition 缺席/非 renew|revoke（实得 %r）——挂裁或"
                    "续期二择未记，复核语义不可证" % (disp,))]
    reviewer = row.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return [red(tag, "reviewer 缺席/非非空串（实得 %r）——谁复核无从点名"
                    % (reviewer,))]
    if parse_ts(row.get("reviewed_utc")) is None:
        return [red(tag, "reviewed_utc 缺席/非 ISO 8601 带时区时间戳（实得 %r）"
                    % (row.get("reviewed_utc"),))]
    if disp == "renew":
        new_exp = parse_date(row.get("new_expires"))
        if new_exp is None:
            return [red(tag, "renew 缺 new_expires/非合法日期（实得 %r）——续期"
                        "目标日不可证" % (row.get("new_expires"),))]
        if new_exp <= exp:
            return [red(tag, "renew 的 new_expires=%s 未严格后移（≤原 %s）——"
                        "无意义续期不得过门"
                        % (row.get("new_expires"), exp_raw))]
    if exp_raw not in expiring_dates:
        return [red(tag, "指向不在场到期日 %r（读数件 expiring 面无此日）——日期"
                    "错写会使真到期日的行缺位，fail-closed" % (exp_raw,))]
    return []


def judge_expiry(expiring, review_rows, now):
    """leg-E：豁免到期前 7d 复核清单行在场断言＋禁静默过期。返回 findings。"""
    findings = []
    if not isinstance(expiring, list):
        return [red("expiring", "expiring 段缺席/非数组（实得 %s）——豁免到期面"
                    "不可证，不猜绿" % (type(expiring).__name__,))]
    today = now.date()
    faces = {}
    for idx, item in enumerate(expiring):
        if not isinstance(item, dict):
            findings.append(red("expiring#%d" % idx,
                                "条目非对象（%r）——豁免面结构损坏" % (item,)))
            continue
        exp = parse_date(item.get("expires"))
        n = item.get("entries")
        if exp is None or not _is_count(n) or n < 1:
            findings.append(red("expiring#%d" % idx,
                                "expires 缺席/坏形或 entries 非 ≥1 整数（实得 "
                                "expires=%r entries=%r）" % (item.get("expires"), n)))
            continue
        key = item["expires"].strip()
        if key in faces:
            findings.append(red("expiring#%d" % idx,
                                "到期日 %s 重复登记——豁免面计数不可证（产件侧"
                                "应按日聚合去重）" % (key,)))
            continue
        faces[key] = (exp, n)
    if not isinstance(review_rows, list):
        findings.append(red("expiry_review",
                            "expiry_review 段缺席/非数组（实得 %s）——复核清单"
                            "不可证，不猜绿" % (type(review_rows).__name__,)))
        return findings

    seen_rows = {}
    for idx, row in enumerate(review_rows):
        form = _row_form_findings(row, idx, set(faces))
        findings.extend(form)
        if form or not isinstance(row, dict):
            continue
        key = row["expires"].strip()
        if key in seen_rows:
            findings.append(red("expiry_review#%d" % idx,
                                "到期日 %s 复核清单行重复——处置计数不可证" % (key,)))
            continue
        seen_rows[key] = row

    for key, (exp, n) in sorted(faces.items()):
        tag = "expires:%s" % key
        days_left = (exp - today).days
        row = seen_rows.get(key)
        if days_left < 0:
            if row is None:
                findings.append(red(tag,
                                    "豁免已过期 %dd 仍无复核清单行——静默过期"
                                    "（过期自动失效后原豁免命中即转红，禁静默"
                                    "过期＝D-153 前置检查）" % (-days_left,)))
                continue
            disp = row["disposition"]
            if disp == "renew":
                new_exp = parse_date(row.get("new_expires"))
                if new_exp < today:
                    findings.append(red(tag,
                                        "renew 目标日 %s 已落于今日之前——续期即"
                                        "刻失效，视同静默过期" % (row.get("new_expires"),)))
                    continue
            findings.append(info(tag,
                                 "已过期 %dd（%d 条）· 复核行在场 · %s——%s"
                                 % (-days_left, n, DISPOSITIONS[disp],
                                    "下轮全量复扫须见证豁免面清零（挂裁）"
                                    if disp == "revoke"
                                    else "按新到期日 %s 重进临期窗"
                                         % row.get("new_expires"))))
        elif days_left <= EXPIRY_REVIEW_WINDOW_D:
            if row is None:
                findings.append(red(tag,
                                    "临期 %dd ≤ %dd（%d 条）而复核清单行缺位——"
                                    "到期前 %dd 须生成复核清单行（挂裁或续期），"
                                    "禁静默过期（D-153 前置检查；首个硬期限 "
                                    "2026-12-05 关联 issue #2）"
                                    % (days_left, EXPIRY_REVIEW_WINDOW_D, n,
                                       EXPIRY_REVIEW_WINDOW_D)))
                continue
            disp = row["disposition"]
            findings.append(info(tag,
                                 "临期 %dd ≤ %dd（%d 条）· 复核行在场 · %s%s——"
                                 "复核清单行在场断言过"
                                 % (days_left, EXPIRY_REVIEW_WINDOW_D, n,
                                    DISPOSITIONS[disp],
                                    ("→ 新到期日 %s" % row.get("new_expires"))
                                    if disp == "renew" else "（下轮复扫见证清零）")))
        else:
            if row is None:
                findings.append(info(tag,
                                     "距到期 %dd（%d 条）＞ %dd 窗——复核行义务"
                                     "未启" % (days_left, n, EXPIRY_REVIEW_WINDOW_D)))
            else:
                findings.append(info(tag,
                                     "距到期 %dd（%d 条）· 复核行提前在场（%s）——"
                                     "义务未启不判"
                                     % (days_left, n, DISPOSITIONS[row["disposition"]])))
    if not faces and not findings:
        findings.append(info("expiring",
                             "豁免面为空（expiring=[]）——无到期复核义务，豁免"
                             "清零态即 D-153 债清方向"))
    return findings


# -------------------------------------------------------------------- 文件级 --
def judge_payload(text, origin, now=None):
    """读数件全文判定（文件级 fail-closed＋三腿）。返回 findings。"""
    if now is None:
        now = utcnow()
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [red("<file>", "读数件 %s 非 JSON：%s——fail-closed 不猜绿"
                    % (origin, exc))]
    if not isinstance(data, dict):
        return [red("<file>", "读数件 %s 顶层非对象（实得 %s）——结构损坏"
                    % (origin, type(data).__name__))]
    if data.get("schema") != SCHEMA:
        return [red("<file>", "读数件 %s schema 缺席/不符（期望 %s，实得 %r）——"
                    "读数契约不可证，不猜绿" % (origin, SCHEMA, data.get("schema")))]
    if "scan" not in data:
        return [red("<file>", "读数件 %s scan 段缺席——新鲜度与覆盖面均无从对账，"
                    "不猜绿" % (origin,))]
    findings = []
    scan = data.get("scan")
    fresh, _ts = judge_freshness(
        scan.get("finished_utc") if isinstance(scan, dict) else scan, now)
    findings.extend(fresh)
    findings.extend(judge_coverage(scan, origin))
    findings.extend(judge_expiry(data.get("expiring"),
                                 data.get("expiry_review"), now))
    return findings


def verdict_of(findings):
    """二值收敛：任一 RED ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] == "RED" for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _ts(delta_s):
    """相对当前钟的 ISO Z 时间戳（夹具动态生成：真跑时龄随真钟走）。"""
    return (utcnow() + datetime.timedelta(seconds=delta_s)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(delta_d):
    """相对今日的 YYYY-MM-DD 到期日（夹具动态生成：临期/过期态任意日真跑稳定）。"""
    return (utcnow().date() + datetime.timedelta(days=delta_d)).isoformat()


_FAKE_HEAD = "327ed120e870119b5ccc893a3d267c1975f7e45c"   # 钉桩基线对象号（本仓公开 sha）


def _scan(**kw):
    base = {"scope": "full", "finished_utc": _ts(-3600),
            "source_head": _FAKE_HEAD, "patterns": MIN_PATTERNS,
            "commits": 311, "blobs": 1204, "unexempt_hits": 0,
            "guardrail_reds": 0, "binary_compressed": 0}
    base.update(kw)
    return base


def _row(expires, disposition="renew", **kw):
    base = {"expires": expires, "disposition": disposition,
            "reviewed_utc": _ts(-7200), "reviewer": "清障员·fixture"}
    if disposition == "renew":
        base["new_expires"] = _day(180)
    base.update(kw)
    return base


def _doc(scan=None, expiring=None, review=None, schema=SCHEMA):
    body = {"schema": schema,
            "scan": _scan() if scan is None else scan,
            "expiring": [{"expires": _day(60), "entries": 84}] if expiring is None
            else expiring,
            "expiry_review": [] if review is None else review}
    return json.dumps(body, ensure_ascii=False)


# （名，描述，卷面文本，期望 rc，红行须含串）
FIXTURES = [
    ("fresh-ok", "新鲜通过（1h 前全量扫，覆盖全零裁决，到期 60d 外）——三态之 fresh 态",
     _doc(), GREEN, None),
    ("fresh-near-7d-line", "7d 档内 60s 边界（age=7d−60s）⇒ 仍新鲜",
     _doc(scan=_scan(finished_utc=_ts(-(STALE_AGE_S - 60)))), GREEN, None),
    ("stale-over-7d", "陈旧 8d（>7d 档）⇒ RED 点名复扫排程腿——三态之 age>7d 态",
     _doc(scan=_scan(finished_utc=_ts(-8 * 86400))), RED, "排程"),
    ("stale-far-30d", "陈旧 30d（豁免 12-05 面整个暴露窗量级）⇒ RED",
     _doc(scan=_scan(finished_utc=_ts(-30 * 86400))), RED, "RED"),
    ("due-review-row-present",
     "临期 3d ≤7d 窗且复核行在场（renew 后移）⇒ 过——三态之临期·行在场断言",
     _doc(expiring=[{"expires": _day(3), "entries": 84}],
          review=[_row(_day(3))]), GREEN, None),
    ("due-review-row-missing",
     "临期 3d ≤7d 窗而复核清单行缺位 ⇒ RED——三态之临期·负例（在场断言）",
     _doc(expiring=[{"expires": _day(3), "entries": 84}], review=[]),
     RED, "复核清单行缺位"),
    ("due-row-bad-disposition",
     "临期行 disposition 非 renew|revoke ⇒ 复核语义不可证红",
     _doc(expiring=[{"expires": _day(3), "entries": 84}],
          review=[_row(_day(3), disposition="maybe")]), RED, "disposition"),
    ("due-renew-not-later",
     "临期行 renew 的 new_expires 未严格后移 ⇒ 无意义续期红",
     _doc(expiring=[{"expires": _day(3), "entries": 84}],
          review=[_row(_day(3), new_expires=_day(2))]), RED, "严格后移"),
    ("expired-silent",
     "已过期 2d 仍无复核行 ⇒ 静默过期红（D-153 前置检查禁项本体）",
     _doc(expiring=[{"expires": _day(-2), "entries": 84}], review=[]),
     RED, "静默过期"),
    ("expired-renewed-valid",
     "已过期 2d 但复核行在场（renew 至 180d 后且 ≥今日）⇒ 过",
     _doc(expiring=[{"expires": _day(-2), "entries": 84}],
          review=[_row(_day(-2))]), GREEN, None),
    ("expired-renewed-into-past",
     "已过期 2d 且 renew 目标日已落今日前 ⇒ 视同静默过期红",
     _doc(expiring=[{"expires": _day(-2), "entries": 84}],
          review=[_row(_day(-2), new_expires=_day(-1))]), RED, "静默过期"),
    ("orphan-review-row",
     "复核行指向不在场到期日（真到期日行因此缺位）⇒ 红",
     _doc(expiring=[{"expires": _day(3), "entries": 84}],
          review=[_row(_day(4))]), RED, "不在场到期日"),
    ("duplicate-review-row",
     "同行到期日复核清单行重复 ⇒ 处置计数不可证红",
     _doc(expiring=[{"expires": _day(3), "entries": 84}],
          review=[_row(_day(3)), _row(_day(3), disposition="revoke")]),
     RED, "重复"),
    ("coverage-patterns-short",
     "patterns=17＜现势 18 ⇒ 覆盖面不完整红（降级旧模式表不得静默过门）",
     _doc(scan=_scan(patterns=17)), RED, "patterns"),
    ("coverage-hits-nonzero",
     "unexempt_hits=2 ⇒ 复扫自身裁决不绿红（先处置后过门）",
     _doc(scan=_scan(unexempt_hits=2)), RED, "非零"),
    ("coverage-reds-nonzero",
     "guardrail_reds=1 ⇒ 复扫自身裁决不绿红",
     _doc(scan=_scan(guardrail_reds=1)), RED, "非零"),
    ("coverage-scope-partial",
     "scope=incremental ⇒ 增量读数冒充全量红",
     _doc(scan=_scan(scope="incremental")), RED, "scope"),
    ("coverage-empty-history",
     "commits=0/blobs=0 ⇒ 历史面为空不可证全量红",
     _doc(scan=_scan(commits=0, blobs=0)), RED, "不可证全量"),
    ("bad-source-head", "source_head 非 hex 对象号 ⇒ 被扫树钉不住红",
     _doc(scan=_scan(source_head="not-an-object-name")), RED, "source_head"),
    ("compressed-registered",
     "binary_compressed=2（如实登记的不覆盖面）⇒ INFO 不连坐红",
     _doc(scan=_scan(binary_compressed=2)), GREEN, None),
    ("missing-finished-ts", "缺 finished_utc ⇒ fail-closed 红",
     _doc(scan={k: v for k, v in _scan().items()
                if k != "finished_utc"}), RED, "finished_utc"),
    ("naive-ts", "无时区基准时间戳（缺 Z/偏移）⇒ 不能对 UTC 钟算龄，红",
     _doc(scan=_scan(finished_utc="2026-11-09T02:58:00")), RED, "带时区"),
    ("future-ts", "未来戳（距今 +1h，超 300s 宽限）⇒ 时钟不可证红",
     _doc(scan=_scan(finished_utc=_ts(3600))), RED, "未来"),
    ("bad-expires-date", "到期日坏形（2026-13-01 非日历合法）⇒ 行指向不可证红",
     _doc(expiring=[{"expires": "2026-13-01", "entries": 3}],
          review=[_row("2026-13-01")]), RED, "日历合法"),
    ("empty-reading", "豁免面空（expiring=[]）⇒ 无到期义务绿（债清方向态）",
     _doc(expiring=[], review=[]), GREEN, None),
    ("bad-json", "坏形（非 JSON）⇒ fail-closed 红",
     "{not json", RED, "非 JSON"),
    ("wrong-schema", "schema 不符 ⇒ 读数契约不可证红",
     _doc(schema="other/v9"), RED, "schema"),
    ("scan-missing", "scan 段缺席 ⇒ 新鲜度与覆盖面均无从对账红",
     json.dumps({"schema": SCHEMA, "expiring": [], "expiry_review": []},
                ensure_ascii=False), RED, "scan 段缺席"),
]


def run_selftest():
    """内嵌夹具自测：三态验收语义各至少一夹具真跑 + 钉钟单元断言（含
    2026-12-05 真硬期限场景），零网络零盘读（夹具全内联动态生成）。"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    for name, desc, text, expect_rc, contains in FIXTURES:
        findings = judge_payload(text, "fixture:" + name)
        verdict, rc = verdict_of(findings)
        check("fixture.%s" % name, rc == expect_rc,
              "desc=%s verdict=%s（期望 %d）findings=%s"
              % (desc, verdict, expect_rc, [f["msg"][:80] for f in findings]))
        if contains is not None:
            check("fixture.%s.msg" % name,
                  any(f["sev"] == "RED" and contains in f["msg"]
                      for f in findings),
                  "红行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（纯函数面，钉钟）——
    pinned = datetime.datetime(2026, 11, 9, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)

    def _pf(delta_s):
        return judge_freshness(
            (pinned - datetime.timedelta(seconds=delta_s))
            .strftime("%Y-%m-%dT%H:%M:%SZ"), pinned)

    # 7d 档位边界：恰点=新鲜、+1s=RED、−60s=新鲜（>7d 才红）
    check("unit.stale-line-exact-7d-clean",
          verdict_of(_pf(STALE_AGE_S)[0]) == ("clean", GREEN))
    f1s = _pf(STALE_AGE_S + 1)
    check("unit.stale-line-7d1s-red",
          verdict_of(f1s[0]) == ("red", RED)
          and f1s[0][0]["sev"] == "RED" and "排程" in f1s[0][0]["msg"])
    # 陈旧红点名天数（「距上次全量扫 N d」语义：8d 龄 msg 含 "8.0d"）
    check("unit.stale-msg-names-days",
          "8.0d" in _pf(8 * 86400)[0][0]["msg"])
    # 时钟宽限：未来 60s（<300s）按 age=0 新鲜；未来 3600s ⇒ 红
    check("unit.skew-within-grace-clean",
          verdict_of(_pf(-60)[0]) == ("clean", GREEN))
    ffut = _pf(-3600)
    check("unit.skew-beyond-grace-red",
          verdict_of(ffut[0]) == ("red", RED) and "未来" in ffut[0][0]["msg"])
    # parse_ts 形制：Z/偏移等价；无时区/非法/非串 ⇒ None
    check("unit.parse-z-and-offset-equivalent",
          parse_ts("2026-11-09T12:00:00Z")
          == parse_ts("2026-11-09T20:00:00+08:00") == pinned)
    for bad in ("2026-11-09T08:31:02", "", "  ", "2026-13-99T99:99:99Z",
                None, 123, "next-scan"):
        check("unit.parse-ts-bad-%r" % (bad,), parse_ts(bad) is None)
    # parse_date 形制：严格 YYYY-MM-DD 且日历合法；单 digit 月日/斜杠/非串 ⇒ None
    for good in ("2026-12-05", "2027-02-28"):
        check("unit.parse-date-good-%s" % good, parse_date(good) is not None)
    for bad in ("2026-12-5", "2026/12/05", "2026-13-01", "2026-02-30",
                "", None, 42, "20261205"):
        check("unit.parse-date-bad-%r" % (bad,), parse_date(bad) is None)
    # source_head：40/64 hex 过；39 hex/大写/非串不过（git 对象号小写 hex 形）
    for good in ("327ed120e870119b5ccc893a3d267c1975f7e45c",
                 "a" * 64):
        check("unit.head-good-%d" % len(good),
              SHA_RE.match(good) is not None)
    for bad in ("327ed120e870119b5ccc893a3d267c1975f7e45", "A" * 40,
                "head", ""):
        check("unit.head-bad-%r" % (bad[:12],), SHA_RE.match(bad) is None)

    # —— 2026-12-05 真硬期限钉钟场景（D-153 前置检查真值面）——
    def _pin_read(now_str, expiring, review):
        now = parse_ts(now_str)
        return judge_expiry(expiring, review, now)

    hard = [{"expires": "2026-12-05", "entries": 84}]   # mirror-scan-allowlist 现势形
    # 11-20（距 12-05 还有 15d＞7d 窗）：无行 ⇒ 义务未启绿
    check("unit.hard-12205-15d-out-no-row-clean",
          verdict_of(_pin_read("2026-11-20T00:00:00Z", hard, []))
          == ("clean", GREEN))
    # 11-28（窗口开启日：恰 7d）：无行 ⇒ 红
    f28 = _pin_read("2026-11-28T00:00:00Z", hard, [])
    check("unit.hard-12205-window-open-day-red",
          verdict_of(f28) == ("red", RED)
          and "复核清单行缺位" in f28[0]["msg"], str(f28))
    # 11-30（临期 5d）：行在场 renew 至 2027-06-05 ⇒ 绿且行点名
    f30 = _pin_read("2026-11-30T00:00:00Z", hard,
                    [{"expires": "2026-12-05", "disposition": "renew",
                      "new_expires": "2027-06-05",
                      "reviewed_utc": "2026-11-28T09:00:00Z",
                      "reviewer": "清障员·钉钟"}])
    check("unit.hard-12205-5d-row-present-clean",
          verdict_of(f30) == ("clean", GREEN)
          and any("复核清单行在场断言过" in x["msg"] for x in f30), str(f30))
    # 12-06（过期 1d）：无行 ⇒ 静默过期红；revoke 行在场 ⇒ 绿（下轮复扫见证清零）
    f06 = _pin_read("2026-12-06T00:00:00Z", hard, [])
    check("unit.hard-12205-expired-silent-red",
          verdict_of(f06) == ("red", RED)
          and "静默过期" in f06[0]["msg"], str(f06))
    f06r = _pin_read("2026-12-06T00:00:00Z", hard,
                     [{"expires": "2026-12-05", "disposition": "revoke",
                       "reviewed_utc": "2026-12-01T09:00:00Z",
                       "reviewer": "清障员·钉钟"}])
    check("unit.hard-12205-expired-revoked-clean",
          verdict_of(f06r) == ("clean", GREEN)
          and any("见证豁免面清零" in x["msg"] for x in f06r), str(f06r))

    # 行形制负例：缺 reviewer / reviewed_utc 无时区 / 行非对象
    for label, row in (
            ("no-reviewer", {"expires": _day(3), "disposition": "renew",
                             "new_expires": _day(180),
                             "reviewed_utc": _ts(-7200)}),
            ("naive-reviewed-utc", {"expires": _day(3), "disposition": "revoke",
                                    "reviewed_utc": "2026-11-09T09:00:00",
                                    "reviewer": "清障员·x"}),
            ("row-not-dict", "not-a-row")):
        fr = judge_expiry([{"expires": _day(3), "entries": 5}], [row],
                          utcnow())
        check("unit.row-form-%s-red" % label,
              verdict_of(fr) == ("red", RED), str(fr))
    # _is_count：True/False 是 bool 不是计数（防布尔混入计数面）
    check("unit.count-excludes-bool",
          all(not _is_count(v) for v in (True, False))
          and _is_count(0) and _is_count(18) and not _is_count(-1)
          and not _is_count("18"))
    # verdict 二值收敛
    check("unit.verdict-binary",
          verdict_of([red("a", "x")]) == ("red", RED)
          and verdict_of([info("c", "z")]) == ("clean", GREEN))
    # 文件级：顶层非对象 ⇒ 红
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_doc()]), "<t>"))
          == ("red", RED))

    failed = [(n, d) for (n, ok, d) in checks if not ok]
    for (n, ok, d) in checks:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", n,
                             (" — " + d[:120]) if (d and not ok) else ""))
    print("selftest %d/%d 过" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# -------------------------------------------------------------------- main --
def print_findings(header, findings):
    print(header)
    for f in sorted(findings, key=lambda x: (SEV_ORDER.get(x["sev"], 9),
                                             x.get("tag", ""))):
        print("  " + f["msg"])
    verdict, rc = verdict_of(findings)
    n_red = sum(1 for x in findings if x["sev"] == "RED")
    n_info = sum(1 for x in findings if x["sev"] == "INFO")
    print("verdict=%s rc=%d（%d 条：%d RED / %d INFO）"
          % (verdict, rc, len(findings), n_red, n_info))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公开面全量复扫新鲜度门：上次全量复扫时间戳 age>7d⇒红＋"
                    "覆盖面完整性（scope=full/patterns≥18/裁决零）＋豁免到期前 "
                    "7d 复核清单行在场断言（挂裁或续期，禁静默过期；D-153 · "
                    "ESC-15 · 卡 #249）；缺件/坏形 fail-closed。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三态验收语义真跑；零网络零盘读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：fresh-ok→0，"
                         "stale-over-7d/due-review-row-missing→1）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.mirror-rescan-reading/v1；"
                         "缺件 ⇒ fail-closed 红）")
    args = ap.parse_args(argv)

    modes = [bool(args.selftest), bool(args.fixture), bool(args.check)]
    if sum(modes) != 1:
        ap.print_usage()
        print("须且仅须选一模式：--selftest / --fixture 名 / --check 路径",
              file=sys.stderr)
        return 2
    if args.selftest:
        return run_selftest()
    if args.fixture:
        for name, desc, text, _rc, _c in FIXTURES:
            if name == args.fixture:
                print("夹具 %s：%s" % (name, desc))
                return print_findings("—— 裁决 ——",
                                      judge_payload(text,
                                                    "fixture:" + name))
        print("不识夹具名 %r（可用：%s）"
              % (args.fixture, " / ".join(f[0] for f in FIXTURES)),
              file=sys.stderr)
        return 2
    try:
        with open(args.check, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return print_findings(
            "公开面全量复扫新鲜度门（D-153/#249）：读数件=%s" % args.check,
            [red("<file>", "读数件不可读：%s（%s）——缺读数件 fail-closed 不猜绿"
                 % (args.check, exc))])
    return print_findings(
        "公开面全量复扫新鲜度门（D-153/#249）：读数件=%s" % args.check,
        judge_payload(text, args.check))


if __name__ == "__main__":
    sys.exit(main())
