#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/telemetry-fresh-recon-gate.py — telemetry push 新鲜度门（D-146 · ESC-04 · 卡 #242）。

【锚号】D-146（账本/阶段欠账台账.md:177）　【卡号】factory-os issue #242
  （wave-15 · w15-d146-telemetry-fresh-gate · 允许路径=本件单件；本件=阶段一·门本体，
   哨兵与 /factory 的 telemetry 段接线随下一批跟进卡，不在本卡）。

【为什么建本门（D-146 债本体）】
  telemetry cron PAT 链断后 /factory planner_blind 看板陈旧 7.4h 无升级判据——
  degraded 标注是终点不是判据，「陈旧多久必须升级/谁被通知」无门规定（ESC-04
  新门设计栏；裁14 只补过 cron PATH，新鲜度无门）。本门把「上次成功 push
  时间戳」的年龄做成机器断言：age>2h ⇒ AMBER 点名、age>6h ⇒ RED+升级行
  （点名推送源与小时龄，升级通知运营者）；缺读数件/坏形/未来戳一律
  fail-closed 不猜绿。附带 crontab 一次性机检腿：含 askpass 调用者的
  crontab 行必须带显式 PATH 前缀（裁14 事故面：cron 环境无 PATH 时
  askpass/git 解析断供；缺 PATH ⇒ 红）。

【阈值与校准来源】
  AMBER_AGE_S=7200（2h）/ RED_AGE_S=21600（6h）＝ESC-04 面设计值（遥测 push
  慢档：D-146 债实例 7.4h 陈旧仍未升级）；amber/red 双档档制成例沿用
  40min/2h 档先例（D-142/ESC-09 sync 新鲜度腿同款双档结构），本门按 ESC-04
  面取 2h/6h 数值并在此注明。时钟宽限 CLOCK_SKEW_GRACE_S=300：
  last_success_utc 落于未来且超宽限 ⇒ 红（时钟后跳/时间戳不可证）；
  宽限内未来戳按 age=0 判新鲜。

【判定语义（leg-F 新鲜度，对读数件 JSON 的 pushes 逐条判）】
  · name 缺席/非非空串 ⇒ 红 rc=1（推送源点名与「谁被通知」无从指起）；
  · last_success_utc 缺席/非串/非 ISO 8601 带时区 ⇒ 红 rc=1（新鲜度无从对账，
    fail-closed 不猜绿）；
  · age = now(UTC) − last_success_utc：
      age > 6h ⇒ RED+升级行（点名推送源+小时龄+升级通知运营者）；
      age > 2h ⇒ AMBER 点名（rc=1；升级行只挂 RED 档）；
      其余（含宽限内未来戳）⇒ 新鲜过（INFO）。
  · 文件级：非 JSON/顶层非对象/schema 不符/pushes 缺席或空壳 ⇒ 红 rc=1
    （不猜绿）；--check 缺件/不可读 ⇒ 红 rc=1（缺读数件 fail-closed）。

【crontab 机检腿（leg-C，一次性部署断言）】
  非注释行含 askpass（GIT_ASKPASS=…af-github-askpass 等调用形态）⇒ 该行须带
  显式 PATH（本行 PATH= 前缀，或卷面存在 PATH= 环境行——vixie cron 环境行全局
  生效，与行序无关）；缺 ⇒ 红点名该行。卷面无 askpass 调用行 ⇒ INFO 域外
  不判（PAT 链接线归哨兵段跟进卡）。真查用法：
  crontab -l | python3 -I tools/telemetry-fresh-recon-gate.py --check-crontab -

【读数件契约（schema af.telemetry-push-reading/v1）】
  {"schema": "af.telemetry-push-reading/v1",
   "pushes": [{"name": "factory-status-push",
               "last_success_utc": "2026-11-09T08:31:02Z"}, …]}

【退出码】0=绿（全部推送源新鲜且 crontab 腿域内全过）；1=红（AMBER/RED/
  坏形/缺件，逐条点名——本门按卡面验收口径二值出红：amber 与 red 负例均
  rc=1，升级行只挂 RED 档）；2=CLI 用法错（未选模式/夹具名不识——非数据
  裁决面）。

【用法】
  python3 -I tools/telemetry-fresh-recon-gate.py --selftest        # 内嵌夹具全跑（rc=0）
  python3 -I tools/telemetry-fresh-recon-gate.py --fixture <名>    # 单夹具（rc=该夹具裁决）
  python3 -I tools/telemetry-fresh-recon-gate.py --check <读数件路径>       # 真查新鲜度
  python3 -I tools/telemetry-fresh-recon-gate.py --check-crontab <路径|->   # 真查 crontab
  夹具名：fresh-ok / fresh-near-amber-line / amber-just-over / amber-stale-3h /
          red-escalate / red-mixed-entry / missing-timestamp / garbage-timestamp /
          naive-timestamp / future-timestamp / missing-name / empty-pushes /
          bad-json / wrong-schema / cron-askpass-with-path / cron-askpass-inline-path /
          cron-askpass-missing-path / cron-no-askpass / cron-comment-ignored
  （三态验收语义夹具：fresh=fresh-ok（rc=0）；amber=amber-stale-3h（rc=1 AMBER
   点名）；red=red-escalate（rc=1 含升级行）；crontab 腿=cron-askpass-with-path
   （rc=0）/ cron-askpass-missing-path（rc=1 缺 PATH）。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面）；零网络、零凭据、零写入（--check/--check-crontab
  只读）；红不猜绿（缺读数件/坏形/未来戳即红）；selftest 全部真跑不编造。
"""

import argparse
import datetime
import json
import re
import sys

SCHEMA = "af.telemetry-push-reading/v1"
AMBER_AGE_S = 2 * 3600        # >2h ⇒ AMBER（ESC-04 设计值；双档档制成例沿 D-142/ESC-09 40min/2h 先例）
RED_AGE_S = 6 * 3600          # >6h ⇒ RED+升级行（ESC-04；D-146 债实例 7.4h 陈旧）
CLOCK_SKEW_GRACE_S = 300      # 未来戳宽限：超 5min ⇒ 时钟不可证红

GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "AMBER": 1, "INFO": 2}
RED_FAMILY = ("RED", "AMBER")  # 二值收敛族：AMBER 同出 rc=1（卡面验收口径二值出红）


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def amber(tag, msg):
    return {"sev": "AMBER", "tag": tag, "msg": "[AMBER] %s %s" % (tag, msg)}


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


# ---------------------------------------------------------------- leg-F 新鲜度 --
def judge_push(entry, idx, now):
    """单条推送源新鲜度判定。返回 findings（sev ∈ RED/AMBER/INFO）。"""
    if not isinstance(entry, dict):
        return [red("#%d" % idx, "读数条目非对象（%r）——读数件结构损坏，不猜绿"
                    % (entry,))]
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return [red("#%d" % idx, "name 缺席/非非空串（实得 %r）——推送源点名与"
                    "「谁被通知」无从指起，fail-closed 红" % (name,))]
    tag = name.strip()
    raw = entry.get("last_success_utc")
    ts = parse_ts(raw)
    if ts is None:
        return [red(tag, "last_success_utc 缺席/非 ISO 8601 带时区时间戳（实得 %r）"
                    "——上次成功 push 时间无从对账，fail-closed 不猜绿" % (raw,))]
    age_s = (now - ts).total_seconds()
    if age_s < -CLOCK_SKEW_GRACE_S:
        return [red(tag, "last_success_utc 落于未来（距今 -%.0fs，超 %ds 宽限）——"
                    "时钟后跳/时间戳不可证，不猜绿"
                    % (-age_s, CLOCK_SKEW_GRACE_S))]
    if age_s < 0:
        age_s = 0.0
    if age_s > RED_AGE_S:
        return [red(tag, "遥测推送陈旧 RED：上次成功 push 距今 %.1fh（>%.0fh 档）——"
                    "升级行：升级通知运营者处置（PAT 链/cron 断供排查；degraded "
                    "标注不是终点——ESC-04，D-146 债实例 7.4h 陈旧）"
                    % (age_s / 3600.0, RED_AGE_S / 3600))]
    if age_s > AMBER_AGE_S:
        return [amber(tag, "遥测推送陈旧 AMBER：上次成功 push 距今 %.1fh（>%.0fh 档、"
                      "≤%.0fh）——点名关注；越 %.0fh 档挂升级行"
                      % (age_s / 3600.0, AMBER_AGE_S / 3600, RED_AGE_S / 3600,
                         RED_AGE_S / 3600))]
    return [info(tag, "新鲜：上次成功 push 距今 %.0fmin（≤%.0fh amber 档）"
                 % (age_s / 60.0, AMBER_AGE_S / 3600))]


def judge_payload(text, origin, now=None):
    """读数件全文判定（文件级 fail-closed + 逐条新鲜度断言）。返回 findings。"""
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
    pushes = data.get("pushes")
    if not isinstance(pushes, list) or not pushes:
        return [red("<file>", "读数件 %s pushes 缺席/空（空壳读数件）——无任何推送"
                    "源时间戳即无新鲜度证明，不猜绿" % (origin,))]
    findings = []
    for idx, entry in enumerate(pushes):
        findings.extend(judge_push(entry, idx, now))
    return findings


# ------------------------------------------------------------- leg-C crontab --
PATH_ASSIGN_RE = re.compile(r"(?:^|[\s;])PATH=")   # 行内显式 PATH 前缀（词边界：GOPATH= 不算）
CRON_ENV_PATH_RE = re.compile(r"^\s*PATH\s*=")     # crontab 全局 PATH 环境行


def _strip_inline_comment(line):
    cut = re.search(r"\s#", line)
    return line[:cut.start()] if cut else line


def judge_crontab(text, origin):
    """leg-C：askpass 调用行显式 PATH 断言（一次性机检；只读卷面）。返回 findings。"""
    if not isinstance(text, str):
        return [red("<crontab>", "crontab 卷面 %s 非文本——fail-closed 不猜绿"
                    % (origin,))]
    has_global_path = False
    askpass_lines = []
    for lineno, rawline in enumerate(text.splitlines(), 1):
        if CRON_ENV_PATH_RE.match(rawline):
            has_global_path = True
        line = _strip_inline_comment(rawline).strip()
        if not line or line.startswith("#"):
            continue
        if "askpass" in line.lower():
            askpass_lines.append((lineno, line))
    if not askpass_lines:
        return [info("<crontab>", "卷面 %s 无 askpass 调用行——leg-C 域外不判"
                     "（telemetry PAT 链接线归哨兵段跟进卡）" % (origin,))]
    findings = []
    for lineno, line in askpass_lines:
        if PATH_ASSIGN_RE.search(line) or has_global_path:
            findings.append(info("crontab:%d" % lineno,
                                 "askpass 调用行带显式 PATH（%s…）——过"
                                 % (line[:60],)))
        else:
            findings.append(red("crontab:%d" % lineno,
                                "askpass 调用行缺显式 PATH 前缀（%s…）——裁14 "
                                "事故面：cron 环境无 PATH 则 askpass/git 解析断供，"
                                "缺 PATH ⇒ 红（ESC-04 一次性机检）" % (line[:60],)))
    return findings


def verdict_of(findings):
    """二值收敛：任一 RED/AMBER ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] in RED_FAMILY for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _ts(delta_s):
    """相对当前钟的 ISO Z 时间戳（夹具动态生成：真跑时龄随真钟走）。"""
    return (utcnow() + datetime.timedelta(seconds=delta_s)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _push(**kw):
    base = {"name": "factory-status-push", "last_success_utc": _ts(-1800)}
    base.update(kw)
    return base


def _doc(pushes):
    return json.dumps({"schema": SCHEMA, "pushes": pushes}, ensure_ascii=False)


# （名，描述，腿别，卷面文本，期望 rc，红行须含串）
FIXTURES = [
    ("fresh-ok", "新鲜通过（30min 与 90s 两推送源）",
     "fresh", _doc([_push(),
                    _push(name="planner-blind-push",
                          last_success_utc=_ts(-90))]),
     GREEN, None),
    ("fresh-near-amber-line", "2h 档内 60s 边界（age=2h−60s）⇒ 仍新鲜",
     "fresh", _doc([_push(last_success_utc=_ts(-(AMBER_AGE_S - 60)))]),
     GREEN, None),
    ("amber-just-over", "2h 档外 60s 边界（age=2h+60s）⇒ AMBER",
     "fresh", _doc([_push(last_success_utc=_ts(-(AMBER_AGE_S + 60)))]),
     RED, "AMBER"),
    ("amber-stale-3h", "陈旧 3h（>2h ≤6h 档）⇒ AMBER 点名——三态之 amber 态",
     "fresh", _doc([_push(last_success_utc=_ts(-3 * 3600))]),
     RED, "AMBER"),
    ("red-escalate", "陈旧 7.4h（>6h 档，D-146 债实例形态）⇒ RED+升级行——三态之 red 态",
     "fresh", _doc([_push(last_success_utc=_ts(-7.4 * 3600))]),
     RED, "升级行"),
    ("red-mixed-entry", "混卷（一新鲜一陈旧 8h）⇒ 只红陈旧条、新鲜条 INFO——逐条点名",
     "fresh", _doc([_push(),
                    _push(name="planner-blind-push",
                          last_success_utc=_ts(-8 * 3600))]),
     RED, "升级行"),
    ("missing-timestamp", "缺 last_success_utc ⇒ fail-closed 红",
     "fresh", _doc([{"name": "factory-status-push"}]),
     RED, "last_success_utc"),
    ("garbage-timestamp", "时间戳非 ISO（yesterday-ish）⇒ fail-closed 红",
     "fresh", _doc([_push(last_success_utc="yesterday-ish")]),
     RED, "last_success_utc"),
    ("naive-timestamp", "无时区基准时间戳（缺 Z/偏移）⇒ 不能对 UTC 钟算龄，红",
     "fresh", _doc([_push(last_success_utc="2026-11-09T08:31:02")]),
     RED, "带时区"),
    ("future-timestamp", "未来戳（距今 +1h，超 300s 宽限）⇒ 时钟不可证红",
     "fresh", _doc([_push(last_success_utc=_ts(3600))]),
     RED, "未来"),
    ("missing-name", "缺 name ⇒ 点名与「谁被通知」无从指起，红",
     "fresh", _doc([{"last_success_utc": _ts(-60)}]),
     RED, "name"),
    ("empty-pushes", "空壳读数件（pushes 空）⇒ 不猜绿",
     "fresh", json.dumps({"schema": SCHEMA, "pushes": []}),
     RED, "空壳"),
    ("bad-json", "坏形（非 JSON）⇒ fail-closed 红",
     "fresh", "{not json",
     RED, "非 JSON"),
    ("wrong-schema", "schema 不符 ⇒ 读数契约不可证红",
     "fresh", json.dumps({"schema": "other/v9", "pushes": [_push()]}),
     RED, "schema"),
    ("cron-askpass-with-path", "crontab 腿正例：PATH 环境行 + askpass 调用行 ⇒ 过",
     "crontab",
     "PATH=/usr/local/bin:/usr/bin:/bin\n"
     "*/5 * * * * GIT_ASKPASS=/home/op/.local/bin/af-github-askpass "
     "/home/op/ws/tools/telemetry-push.sh >> /var/log/telemetry.log 2>&1\n",
     GREEN, None),
    ("cron-askpass-inline-path", "crontab 腿正例：PATH 前缀写在调用行本行 ⇒ 过",
     "crontab",
     "*/10 * * * * PATH=/usr/local/bin:/usr/bin:/bin "
     "GIT_ASKPASS=/home/op/.local/bin/af-github-askpass "
     "/home/op/ws/tools/telemetry-push.sh\n",
     GREEN, None),
    ("cron-askpass-missing-path", "crontab 腿负例：askpass 调用行缺显式 PATH ⇒ 红",
     "crontab",
     "*/5 * * * * GIT_ASKPASS=/home/op/.local/bin/af-github-askpass "
     "/home/op/ws/tools/telemetry-push.sh\n",
     RED, "PATH"),
    ("cron-no-askpass", "卷面无 askpass 调用行 ⇒ 域外 INFO 不判",
     "crontab",
     "17 * * * * /home/op/ws/tools/ledger-sync.sh\n",
     GREEN, None),
    ("cron-comment-ignored", "注释里的 askpass 提及不算调用行（去注释后无调用）⇒ 过",
     "crontab",
     "# */5 * * * * GIT_ASKPASS=/home/op/.local/bin/af-github-askpass "
     "telemetry.sh（停用）\n"
     "30 3 * * * /usr/bin/backup.sh\n",
     GREEN, None),
]


def run_selftest():
    """内嵌夹具自测：三态验收语义各至少一夹具真跑 + 边界/形制单元断言，
    零网络零盘读（夹具全内联，时间戳相对真钟动态生成）。"""
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    for name, desc, kind, text, expect_rc, contains in FIXTURES:
        if kind == "crontab":
            findings = judge_crontab(text, "fixture:" + name)
        else:
            findings = judge_payload(text, "fixture:" + name)
        verdict, rc = verdict_of(findings)
        check("fixture.%s" % name, rc == expect_rc,
              "desc=%s verdict=%s（期望 %d）findings=%s"
              % (desc, verdict, expect_rc, [f["msg"][:80] for f in findings]))
        if contains is not None:
            check("fixture.%s.msg" % name,
                  any(f["sev"] in RED_FAMILY and contains in f["msg"]
                      for f in findings),
                  "红行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（judge_push/judge_payload/parse_ts/judge_crontab 纯函数面，钉钟）——
    pinned = datetime.datetime(2026, 11, 9, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)

    def _pinned_ts(delta_s):
        return (pinned - datetime.timedelta(seconds=delta_s)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")

    def _pf(delta_s):
        return judge_push({"name": "factory-status-push",
                           "last_success_utc": _pinned_ts(delta_s)}, 0, pinned)

    # 档位边界：2h 恰点=新鲜、2h+1s=AMBER、6h 恰点=AMBER（>6h 才红）、6h+1s=RED
    check("unit.amber-line-exact-2h-clean",
          verdict_of(_pf(AMBER_AGE_S)) == ("clean", GREEN))
    check("unit.amber-line-2h1s-amber",
          verdict_of(_pf(AMBER_AGE_S + 1)) == ("red", RED)
          and _pf(AMBER_AGE_S + 1)[0]["sev"] == "AMBER")
    f6h = _pf(RED_AGE_S)
    check("unit.red-line-exact-6h-still-amber",
          verdict_of(f6h) == ("red", RED)
          and f6h[0]["sev"] == "AMBER"
          and not any(x["sev"] == "RED" for x in f6h))
    f6h1s = _pf(RED_AGE_S + 1)
    check("unit.red-line-6h1s-red",
          verdict_of(f6h1s) == ("red", RED)
          and f6h1s[0]["sev"] == "RED"
          and "升级行" in f6h1s[0]["msg"])
    # 升级行点名推送源与小时龄（「谁被通知」语义：msg 含源名与 h 数）
    check("unit.escalation-names-source-and-age",
          "factory-status-push" in f6h1s[0]["msg"] and "h（>6h 档）" in f6h1s[0]["msg"],
          f6h1s[0]["msg"])
    # 混卷：红只落陈旧条，新鲜条保持 INFO（逐条点名不连坐）
    fmix = judge_payload(_doc([_push(last_success_utc=_pinned_ts(-120)),
                               _push(name="planner-blind-push",
                                     last_success_utc=_pinned_ts(-7 * 3600))]),
                         "<t>", now=pinned)
    check("unit.mixed-precise-naming",
          verdict_of(fmix) == ("red", RED)
          and len([x for x in fmix if x["sev"] == "INFO"]) == 1
          and len([x for x in fmix if x["sev"] == "RED"]) == 1
          and fmix[1]["tag"] == "planner-blind-push", str(fmix))
    # 时钟宽限：未来 60s（<300s 宽限）按 age=0 新鲜；未来 3600s ⇒ 红
    check("unit.skew-within-grace-clean",
          verdict_of(_pf(-60)) == ("clean", GREEN))
    ffut = _pf(-3600)
    check("unit.skew-beyond-grace-red",
          verdict_of(ffut) == ("red", RED) and "未来" in ffut[0]["msg"])
    # parse_ts 形制：Z/偏移两种合法形态等价；无时区/非法/非串 ⇒ None
    check("unit.parse-z-and-offset-equivalent",
          parse_ts("2026-11-09T12:00:00Z")
          == parse_ts("2026-11-09T20:00:00+08:00") == pinned)
    for bad in ("2026-11-09T08:31:02", "", "  ", "2026-13-99T99:99:99Z",
                None, 123, "next-push"):
        check("unit.parse-bad-%r" % (bad,), parse_ts(bad) is None)
    # name 形制：非串/空串/纯空白 ⇒ 红（点名无从指起）
    for badname in (None, 7, "", "   "):
        entry = {"last_success_utc": _pinned_ts(-60)}
        if badname is not None:
            entry["name"] = badname
        check("unit.bad-name-%r" % (badname,),
              verdict_of(judge_push(entry, 0, pinned)) == ("red", RED))
    # 文件级：顶层非对象 ⇒ 红（bad-json/空壳/schema 不符已在夹具面）
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_push()]), "<t>"))
          == ("red", RED))
    # verdict 二值收敛：AMBER 与 RED 同族 rc=1
    check("unit.verdict-amber-red-family",
          verdict_of([amber("a", "x"), red("b", "y")]) == ("red", RED)
          and verdict_of([info("c", "z")]) == ("clean", GREEN))
    # crontab 腿：PATH 环境行在调用行之后也过（vixie 环境行全局生效，与行序无关）
    check("unit.cron-global-path-after-caller",
          verdict_of(judge_crontab(
              "*/5 * * * * GIT_ASKPASS=/home/op/.local/bin/af-github-askpass "
              "telemetry.sh\nPATH=/usr/bin:/bin\n", "<t>")) == ("clean", GREEN))
    # 行尾注释提及 askpass 不算调用行
    check("unit.cron-trailing-comment-mention",
          verdict_of(judge_crontab(
              "*/5 * * * * telemetry.sh # fixed askpass link\n", "<t>"))
          == ("clean", GREEN))
    # 词边界：GOPATH= 不当显式 PATH
    fgop = judge_crontab(
        "17 * * * * GOPATH=/opt/go askpass-runner\n", "<t>")
    check("unit.cron-gopath-not-path",
          verdict_of(fgop) == ("red", RED)
          and "缺显式 PATH" in fgop[0]["msg"], str(fgop))
    # 空卷面 ⇒ 域外 INFO
    check("unit.cron-empty-out-of-scope",
          verdict_of(judge_crontab("", "<t>")) == ("clean", GREEN))

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
    n_amb = sum(1 for x in findings if x["sev"] == "AMBER")
    n_info = sum(1 for x in findings if x["sev"] == "INFO")
    print("verdict=%s rc=%d（%d 条：%d RED / %d AMBER / %d INFO）"
          % (verdict, rc, len(findings), n_red, n_amb, n_info))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="telemetry push 新鲜度门：上次成功 push 时间戳 age>2h⇒AMBER、"
                    ">6h⇒RED+升级行（D-146 · ESC-04 · 卡 #242）；含 crontab "
                    "askpass 调用行显式 PATH 一次性机检腿；缺件/坏形/未来戳 "
                    "fail-closed。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三态验收语义真跑；零网络零盘读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：fresh-ok→0，"
                         "amber-stale-3h/red-escalate/cron-askpass-missing-path→1）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.telemetry-push-reading/v1；"
                         "缺件 ⇒ fail-closed 红）")
    ap.add_argument("--check-crontab", metavar="路径或-",
                    help="真查 crontab 卷面（askpass 行显式 PATH 断言；"
                         "- = stdin，配合 crontab -l 管道一次性机检）")
    args = ap.parse_args(argv)

    modes = [bool(args.selftest), bool(args.fixture), bool(args.check),
             bool(args.check_crontab)]
    if sum(modes) != 1:
        ap.print_usage()
        print("须且仅须选一模式：--selftest / --fixture 名 / --check 路径 / "
              "--check-crontab 路径|-", file=sys.stderr)
        return 2
    if args.selftest:
        return run_selftest()
    if args.fixture:
        for name, desc, kind, text, _rc, _c in FIXTURES:
            if name == args.fixture:
                print("夹具 %s：%s" % (name, desc))
                findings = judge_crontab(text, "fixture:" + name) \
                    if kind == "crontab" else judge_payload(text,
                                                            "fixture:" + name)
                return print_findings("—— 裁决 ——", findings)
        print("不识夹具名 %r（可用：%s）"
              % (args.fixture, " / ".join(f[0] for f in FIXTURES)),
              file=sys.stderr)
        return 2
    if args.check:
        try:
            with open(args.check, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            return print_findings(
                "telemetry push 新鲜度门（D-146/#242）：读数件=%s" % args.check,
                [red("<file>", "读数件不可读：%s（%s）——缺读数件 fail-closed "
                     "不猜绿" % (args.check, exc))])
        return print_findings(
            "telemetry push 新鲜度门（D-146/#242）：读数件=%s" % args.check,
            judge_payload(text, args.check))
    # --check-crontab（路径或 - 读 stdin；只读）
    if args.check_crontab == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.check_crontab, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            return print_findings(
                "telemetry push 新鲜度门（D-146/#242）crontab 机检腿：卷面=%s"
                % args.check_crontab,
                [red("<crontab>", "crontab 卷面不可读：%s（%s）——fail-closed "
                     "不猜绿" % (args.check_crontab, exc))])
    return print_findings(
        "telemetry push 新鲜度门（D-146/#242）crontab 机检腿：卷面=%s"
        % args.check_crontab, judge_crontab(text, args.check_crontab))


if __name__ == "__main__":
    sys.exit(main())
