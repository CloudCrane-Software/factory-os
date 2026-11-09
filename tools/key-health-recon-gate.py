#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/key-health-recon-gate.py — 轮换断供→恢复 SLA 哨兵腿（D-158 · ESC-21 · 卡 #276）。

【锚号】D-158（账本/阶段欠账台账.md）　【卡号】factory-os issue #276
  （wave-14 迟建 · w14-d158-key-health-gate · 允许路径=本件单件）。

【为什么建本门（D-158 债本体）】
  kimi-for-coding 401 自 11-05 20:2x 断供约 2 天无升级行——无「断供→恢复」SLA
  判据与 key-health 监测腿（ESC-21 新门设计栏；判据=宪章资源域 v1 R-14 :198）。
  meters 单腿已实弹立证 R-14 三件读数（裁24），「任一轮换必须产出三件读数」的
  常驻机检判据与 D-147（ESC-07 验收门）同族合流——本锚增量=SLA 哨兵腿。本门把
  SLA 做成机器断言：对 key 健康读数件逐面断言「401 首报→恢复」时长，
  未恢复且超 SLA ⇒ 红点名「须升级行」（哨兵腿本体）；已恢复 ⇒ 绿并 INFO 留
  断供时长读数（供 R-14 三件读数族/D-147 合流消费）。

【判定语义（对读数件 JSON 的 keys[] 逐条判；as_of=读数采集时刻）】
  在域条目=keys[] 全体（每条即一个模型访问面的健康读数）。逐条断言：
  · key_id 缺席/非串/空 ⇒ 红（点名无从谈起，fail-closed）；
  · status 越词表 {healthy, outage, recovered} ⇒ 红（fail-closed）；
  · status=healthy：健康在役面 ⇒ 绿；带 first_401_at/recovered_at ⇒ 红
    （口径矛盾：401 域字段只在 outage/recovered 语义下有意义）；
  · status=outage：first_401_at 缺席/坏形/naive（无时区）/未来戳（>as_of）
    ⇒ 红（fail-closed：SLA 分母无从计算或时序坏形，不猜绿）；
    as_of - first_401_at > SLA_HOURS(=24) ⇒ 红点名「断供 X.Xh 超 SLA 24h
    未恢复——须升级行」（D-158 判据明文：模型 401 首报后 >24h 未恢复 ⇒
    升级行）；恰 24h 或以内 ⇒ 绿（SLA 窗口内，无升级行义务）；
  · status=recovered：first_401_at 与 recovered_at 双必带（缺/坏 ⇒ 红）；
    recovered_at < first_401_at ⇒ 红（负时长坏形）；recovered_at > as_of
    ⇒ 红（未来戳）——以上全过 ⇒ 绿（锚行验收口径：已恢复 → rc=0）并 INFO
    点名断供时长（超 24h 的恢复留痕仍出 INFO，事后面不吞读数）。
  文件级：非 JSON/顶层非对象/schema 不符/as_of 缺席坏形 naive/keys 空壳 ⇒
  红 rc=1（缺读数/坏形 fail-closed，不猜绿）。

【读数件契约（schema af.key-health-reading/v1）】
  {"schema": "af.key-health-reading/v1",
   "as_of": "2026-11-09T10:00:00+08:00",
   "keys": [{"key_id": "…", "status": "healthy|outage|recovered",
             "first_401_at": "2026-11-05T20:25:00+08:00",   # outage/recovered 必带
             "recovered_at": "2026-11-06T09:00:00+08:00"}]}  # recovered 必带
  时刻全 ISO 8601 且必须带时区（naive ⇒ 不可比 ⇒ 红）。key 健康读数件由
  哨兵腿产出后经 --check 入检；缺件即缺读数（红）。

【退出码】0=绿（全部在役面 SLA 内或已恢复）；1=红（超 SLA 未恢复须升级行/
  缺读数/坏形，逐条点名——本门按卡面验收口径二值出红：25h 未恢复与坏形均
  rc=1）；2=CLI 用法错（未选模式/夹具名不识——非数据裁决面）。

【用法】
  python3 -I tools/key-health-recon-gate.py --selftest        # 内嵌夹具全跑（rc=0）
  python3 -I tools/key-health-recon-gate.py --fixture <名>    # 单夹具（rc=该夹具裁决）
  python3 -I tools/key-health-recon-gate.py --check <读数件路径>   # 真查现势读数件
  夹具名：healthy-ok / outage-within-sla / outage-exact-24h / outage-25h-red /
          outage-24h06m-red / recovered-ok / recovered-31h-info /
          missing-first-401 / bad-ts / naive-ts / future-ts /
          recovered-missing-at / negative-span / bad-status /
          healthy-with-401-fields / missing-key-id / empty-keys /
          bad-json / bad-schema / as-of-absent / multi-face-mixed
  （三验收语义夹具：首报 25h 未恢复负例=outage-25h-red（rc=1 升级行点名）；
   已恢复=recovered-ok（rc=0）；SLA 边界=outage-exact-24h（恰 24h rc=0，
   判 >24h 非 ≥24h）＋outage-24h06m-red（24h+6min rc=1）。）

纪律：判官/门禁/判据件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面）；零网络、零凭据、零写入（--check 只读）；
  红不猜绿（缺读数/坏形即红）；selftest 全部真跑不编造。轮换三件读数常驻
  机检与 D-147 同族合流属后续经批动作，本件只落 SLA 哨兵腿本体。
"""

import argparse
import datetime
import json
import sys

SCHEMA = "af.key-health-reading/v1"
SLA_HOURS = 24            # D-158 判据：模型 401 首报后 >24h 未恢复 ⇒ 升级行
KNOWN_STATUS = {"healthy", "outage", "recovered"}
GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "INFO": 1}
HOUR_S = 3600.0


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def parse_ts(text):
    """ISO 8601 时刻解析（须带时区）。

    返回 tz-aware datetime；naive（无时区）/非串/非 ISO ⇒ None（调用方按
    fail-closed 处理：绝对时刻不可比即 SLA 分母不可证）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        ts = datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if ts.tzinfo is None or ts.utcoffset() is None:
        return None
    return ts


def fmt_hours(delta):
    """timedelta → 「X.Xh」一位小数读数（红/INFO 行内时长口径统一）。"""
    return "%.1fh" % (delta.total_seconds() / HOUR_S)


def judge_entry(entry, idx, as_of):
    """单面读数判定（断供→恢复 SLA 断言）。返回 findings（sev ∈ RED/INFO）。

    as_of=tz-aware 读数采集时刻（文件级已验，非 None）。"""
    if not isinstance(entry, dict):
        return [red("#%d" % idx, "读数条目非对象（%r）——读数件结构损坏，不猜绿"
                    % (entry,))]
    face = entry.get("key_id")
    tag = face.strip() if isinstance(face, str) and face.strip() else "#%d" % idx
    if not isinstance(face, str) or not face.strip():
        return [red(tag, "key_id 缺席/非串/空（实得 %r）——点名无从谈起，"
                    "fail-closed 红" % (face,))]
    status = entry.get("status")
    if not (isinstance(status, str) and status.strip() in KNOWN_STATUS):
        return [red(tag, "status 越词表（实得 %r，合法 %s）——健康口径不可证，"
                    "fail-closed 红"
                    % (status, sorted(KNOWN_STATUS)))]
    status = status.strip()

    if status == "healthy":
        stray = [f for f in ("first_401_at", "recovered_at") if f in entry]
        if stray:
            return [red(tag, "healthy 面带 401 域字段（%s）——口径矛盾：健康在役"
                        "与断供史字段同现，读数坏形" % ("/".join(stray),))]
        return [info(tag, "healthy 在役——SLA 腿无义务，过")]

    first = parse_ts(entry.get("first_401_at"))
    if status == "outage":
        if "first_401_at" not in entry or first is None:
            return [red(tag, "outage 面缺/坏 first_401_at（实得 %r）——401 首报"
                        "时刻即 SLA 分母，缺席或 naive/非 ISO 即不可证，fail-closed"
                        % (entry.get("first_401_at"),))]
        if first > as_of:
            return [red(tag, "first_401_at=%s 晚于 as_of=%s（未来戳）——时序坏形，"
                        "不猜绿" % (entry.get("first_401_at"), as_of.isoformat()))]
        elapsed = as_of - first
        hours = elapsed.total_seconds() / HOUR_S
        if hours > SLA_HOURS:
            return [red(tag, "断供 %s 超 SLA %dh 未恢复（首报 %s，读数时刻 %s）——"
                        "须升级行（D-158：模型 401 首报后 >%dh 未恢复 ⇒ 升级行，"
                        "哨兵腿点名）"
                        % (fmt_hours(elapsed), SLA_HOURS,
                           entry.get("first_401_at"), as_of.isoformat(),
                           SLA_HOURS))]
        return [info(tag, "断供 %s 在 SLA %dh 窗口内（首报 %s）——无升级行义务，"
                     "续监" % (fmt_hours(elapsed), SLA_HOURS,
                               entry.get("first_401_at")))]

    # status == "recovered"
    problems = []
    if "first_401_at" not in entry or first is None:
        problems.append(red(tag, "recovered 面缺/坏 first_401_at（实得 %r）——"
                            "断供起点不可证，fail-closed"
                            % (entry.get("first_401_at"),)))
    rec = parse_ts(entry.get("recovered_at"))
    if "recovered_at" not in entry or rec is None:
        problems.append(red(tag, "recovered 面缺/坏 recovered_at（实得 %r）——"
                            "恢复时刻缺席即「断供→恢复」时长不可证，fail-closed"
                            % (entry.get("recovered_at"),)))
    if problems:
        return problems
    if rec < first:
        problems.append(red(tag, "recovered_at=%s 早于 first_401_at=%s（负时长）——"
                            "时序坏形，不猜绿"
                            % (entry.get("recovered_at"),
                               entry.get("first_401_at"))))
        return problems
    if rec > as_of:
        problems.append(red(tag, "recovered_at=%s 晚于 as_of=%s（未来戳）——时序"
                            "坏形，不猜绿"
                            % (entry.get("recovered_at"), as_of.isoformat())))
        return problems
    span = rec - first
    note = ("断供 %s 后已恢复（%s → %s）——锚行口径已恢复即绿；断供时长留痕供 "
            "R-14 三件读数族/D-147 合流" % (fmt_hours(span),
                                            entry.get("first_401_at"),
                                            entry.get("recovered_at")))
    if span.total_seconds() / HOUR_S > SLA_HOURS:
        note += "（事后面曾超 SLA %dh，升级行留痕义务在流程面追认）" % SLA_HOURS
    return [info(tag, note)]


def judge_payload(text, origin):
    """读数件全文判定（文件级 fail-closed + 逐面 SLA 断言）。返回 findings。"""
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
                    "口径契约不可证，不猜绿" % (origin, SCHEMA, data.get("schema")))]
    as_of = parse_ts(data.get("as_of"))
    if as_of is None:
        return [red("<file>", "读数件 %s as_of 缺席/坏形/naive（实得 %r）——读数"
                    "采集时刻即 SLA 判定基准，不可证即全体不可判，fail-closed"
                    % (origin, data.get("as_of")))]
    faces = data.get("keys")
    if not isinstance(faces, list) or not faces:
        return [red("<file>", "读数件 %s keys 缺席/空（空壳读数件）——无任何面"
                    "的读数即无 SLA 证明，不猜绿" % (origin,))]
    findings = []
    for idx, entry in enumerate(faces):
        findings.extend(judge_entry(entry, idx, as_of))
    return findings


def verdict_of(findings):
    """二值收敛：任一 RED ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] == "RED" for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _face(**kw):
    base = {"key_id": "model-face-a", "status": "healthy"}
    base.update(kw)
    return base


def _doc(faces, as_of="2026-11-09T10:00:00+08:00"):
    return json.dumps({"schema": SCHEMA, "as_of": as_of, "keys": faces},
                      ensure_ascii=False)


# （名，描述，读数件文本，期望 rc，红行须含串）
FIXTURES = [
    ("healthy-ok", "健康在役面（无 401 域字段）⇒ 绿",
     _doc([_face()]),
     GREEN, None),
    ("outage-within-sla", "断供 5h 在 SLA 24h 窗口内 ⇒ 绿（无升级行义务）",
     _doc([_face(key_id="model-face-b", status="outage",
                 first_401_at="2026-11-09T05:00:00+08:00")]),
     GREEN, None),
    ("outage-exact-24h", "断供恰 24h ⇒ 绿（判 >24h 非 ≥24h，边界钉住）",
     _doc([_face(key_id="model-face-c", status="outage",
                 first_401_at="2026-11-08T10:00:00+08:00")]),
     GREEN, None),
    ("outage-25h-red", "首报 25h 未恢复 ⇒ rc=1 升级行点名（D-158 本债实例形态）",
     _doc([_face(key_id="kimi-for-coding", status="outage",
                 first_401_at="2026-11-08T09:00:00+08:00")]),
     RED, "升级行"),
    ("outage-24h06m-red", "断供 24h+6min ⇒ rc=1（边界反向：越线即红）",
     _doc([_face(key_id="model-face-d", status="outage",
                 first_401_at="2026-11-08T09:54:00+08:00")]),
     RED, "升级行"),
    ("recovered-ok", "已恢复（12.6h 断供时长）⇒ rc=0（锚行验收：已恢复→rc=0）",
     _doc([_face(key_id="model-face-e", status="recovered",
                 first_401_at="2026-11-07T20:25:00+08:00",
                 recovered_at="2026-11-08T09:00:00+08:00")]),
     GREEN, None),
    ("recovered-31h-info", "超 SLA 后恢复 ⇒ rc=0＋INFO 留痕（事后面不吞读数）",
     _doc([_face(key_id="model-face-f", status="recovered",
                 first_401_at="2026-11-05T20:25:00+08:00",
                 recovered_at="2026-11-07T03:40:00+08:00")]),
     GREEN, None),
    ("missing-first-401", "outage 缺 first_401_at ⇒ fail-closed 红",
     _doc([{"key_id": "model-face-g", "status": "outage"}]),
     RED, "first_401_at"),
    ("bad-ts", "first_401_at 非 ISO 时刻 ⇒ fail-closed 红",
     _doc([_face(key_id="model-face-h", status="outage",
                 first_401_at="since-tuesday-evening")]),
     RED, "first_401_at"),
    ("naive-ts", "first_401_at 无时区（naive）⇒ 不可比即红",
     _doc([_face(key_id="model-face-i", status="outage",
                 first_401_at="2026-11-08T09:00:00")]),
     RED, "first_401_at"),
    ("future-ts", "first_401_at 晚于 as_of（未来戳）⇒ 红",
     _doc([_face(key_id="model-face-j", status="outage",
                 first_401_at="2026-11-12T00:00:00+08:00")]),
     RED, "未来戳"),
    ("recovered-missing-at", "recovered 缺 recovered_at ⇒ fail-closed 红",
     _doc([_face(key_id="model-face-k", status="recovered",
                 first_401_at="2026-11-07T20:25:00+08:00")]),
     RED, "recovered_at"),
    ("negative-span", "recovered_at 早于 first_401_at（负时长）⇒ 红",
     _doc([_face(key_id="model-face-l", status="recovered",
                 first_401_at="2026-11-07T20:25:00+08:00",
                 recovered_at="2026-11-06T09:00:00+08:00")]),
     RED, "负时长"),
    ("bad-status", "status 越词表 ⇒ fail-closed 红",
     _doc([_face(key_id="model-face-m", status="degraded-sorta")]),
     RED, "越词表"),
    ("healthy-with-401-fields", "healthy 面带 401 域字段（口径矛盾）⇒ 红",
     _doc([_face(first_401_at="2026-11-07T20:25:00+08:00")]),
     RED, "口径矛盾"),
    ("missing-key-id", "key_id 缺席 ⇒ fail-closed 红",
     _doc([{"status": "healthy"}]),
     RED, "key_id"),
    ("empty-keys", "空壳读数件（keys 空）⇒ 不猜绿",
     json.dumps({"schema": SCHEMA, "as_of": "2026-11-09T10:00:00+08:00",
                 "keys": []}),
     RED, "空壳"),
    ("bad-json", "坏形（非 JSON）⇒ fail-closed 红",
     "{not json",
     RED, "非 JSON"),
    ("bad-schema", "schema 不符 ⇒ fail-closed 红",
     json.dumps({"schema": "other/v9", "as_of": "2026-11-09T10:00:00+08:00",
                 "keys": [_face()]}),
     RED, "schema"),
    ("as-of-absent", "as_of 缺席 ⇒ SLA 基准不可证即红",
     json.dumps({"schema": SCHEMA,
                 "keys": [_face(key_id="model-face-n", status="outage",
                                first_401_at="2026-11-08T09:00:00+08:00")]}),
     RED, "as_of"),
    ("multi-face-mixed", "多面混判：healthy 绿＋超时面逐条点名红（只红超时面）",
     _doc([_face(),
           _face(key_id="kimi-for-coding", status="outage",
                 first_401_at="2026-11-08T09:00:00+08:00"),
           _face(key_id="model-face-o", status="outage",
                 first_401_at="2026-11-09T08:00:00+08:00")]),
     RED, "kimi-for-coding"),
]


def run_selftest():
    """内嵌夹具自测：三验收语义各至少一夹具真跑 + 边界/形制单元断言，
    零网络零盘读（夹具全内联）。"""
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
                  any(contains in f["msg"] for f in findings
                      if f["sev"] == ("RED" if expect_rc == RED else "INFO")),
                  "行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（parse_ts/judge_entry/judge_payload 纯函数面）——
    AS_OF = parse_ts("2026-11-09T10:00:00+08:00")
    # parse_ts：ISO 带区收、naive 拒、垃圾拒
    check("parse.iso-ok", parse_ts("2026-11-05T20:25:00+08:00") is not None
          and parse_ts("2026-11-05T20:25:00Z") is not None)
    check("parse.naive-rej", parse_ts("2026-11-05T20:25:00") is None)
    check("parse.garbage-rej", parse_ts("11/05 evening") is None
          and parse_ts("") is None and parse_ts(None) is None
          and parse_ts(20261105) is None)
    # SLA 秒级边界：恰 24h 绿、24h+1s 红（判 >24h 非 ≥24h）
    f24 = judge_entry(_face(key_id="t-a", status="outage",
                            first_401_at="2026-11-08T10:00:00+08:00"), 0, AS_OF)
    check("unit.sla-exact-24h-green", verdict_of(f24) == ("clean", GREEN),
          str(f24))
    f24s = judge_entry(_face(key_id="t-b", status="outage",
                             first_401_at="2026-11-08T09:59:59+08:00"), 0, AS_OF)
    check("unit.sla-24h-plus-1s-red", verdict_of(f24s) == ("red", RED)
          and any("升级行" in x["msg"] for x in f24s), str(f24s))
    # 25h 实例语义串在位（卡面验收：首报 25h 未恢复→rc=1 升级）
    f25 = judge_entry(_face(key_id="t-c", status="outage",
                            first_401_at="2026-11-08T09:00:00+08:00"), 0, AS_OF)
    check("unit.25h-msg", any("25.0h" in x["msg"] and "升级行" in x["msg"]
                              for x in f25), str(f25))
    # 首报=读数时刻（0h）⇒ 绿（刚首报在窗口内）
    f0 = judge_entry(_face(key_id="t-d", status="outage",
                           first_401_at="2026-11-09T10:00:00+08:00"), 0, AS_OF)
    check("unit.zero-span-green", verdict_of(f0) == ("clean", GREEN), str(f0))
    # 已恢复超 SLA：绿 + INFO 含超 SLA 留痕串（不吞读数不冒红）
    fr = judge_entry(_face(key_id="t-e", status="recovered",
                           first_401_at="2026-11-05T20:25:00+08:00",
                           recovered_at="2026-11-07T03:40:00+08:00"), 0, AS_OF)
    check("unit.recovered-over-sla-info",
          verdict_of(fr) == ("clean", GREEN)
          and any("超 SLA" in x["msg"] and "留痕" in x["msg"] for x in fr),
          str(fr))
    # recovered 双缺 ⇒ 两条红各自点名（独立断言语义）
    fboth = judge_entry({"key_id": "t-f", "status": "recovered"}, 0, AS_OF)
    check("unit.recovered-both-missing-two-reds",
          len([x for x in fboth if x["sev"] == "RED"]) == 2, str(fboth))
    # healthy 带 recovered_at 单字段 ⇒ 红（口径矛盾面）
    fh = judge_entry(_face(recovered_at="2026-11-08T09:00:00+08:00"), 0, AS_OF)
    check("unit.healthy-stray-field",
          verdict_of(fh) == ("red", RED)
          and any("recovered_at" in x["msg"] and "口径矛盾" in x["msg"]
                  for x in fh), str(fh))
    # 非对象条目 ⇒ 红
    check("unit.non-dict-entry-red",
          verdict_of(judge_entry("nope", 0, AS_OF)) == ("red", RED))
    # 时区混算：as_of 带区 +08、first 带区 +00，跨区差正确折算（25h 不因区标漂移）
    ftz = judge_entry(_face(key_id="t-g", status="outage",
                            first_401_at="2026-11-08T01:00:00+00:00"), 0, AS_OF)
    check("unit.tz-mixed-25h-red",
          verdict_of(ftz) == ("red", RED)
          and any("25.0h" in x["msg"] for x in ftz), str(ftz))
    # 文件级：as_of naive ⇒ 红（基准不可证）；schema/顶层夹具已在 FIXTURES 面
    check("unit.asof-naive-red",
          verdict_of(judge_payload(json.dumps(
              {"schema": SCHEMA, "as_of": "2026-11-09T10:00:00",
               "keys": [_face()]}), "<t>")) == ("red", RED))
    # 点名可读面：红行必须带 tag（逐面点名语义）
    check("unit.naming-tag",
          all(x["tag"] == "kimi-for-coding" for x in
              judge_payload(FIXTURES[3][2], "fixture:t")
              if x["sev"] == "RED"))
    # 三态收敛面（本门二值：RED 优先；纯 INFO ⇒ 绿）
    check("unit.verdict-bistate",
          verdict_of([]) == ("clean", GREEN)
          and verdict_of([{"sev": "INFO", "tag": "t", "msg": ""}])
          == ("clean", GREEN)
          and verdict_of([{"sev": "INFO", "tag": "t", "msg": ""},
                          {"sev": "RED", "tag": "t", "msg": ""}])
          == ("red", RED))
    # status 词面收边（小写表；越表一律红）
    check("unit.status-vocab", "outage" in KNOWN_STATUS
          and "recovered" in KNOWN_STATUS and "healthy" in KNOWN_STATUS
          and "degraded" not in KNOWN_STATUS)

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
    print("verdict=%s rc=%d（%d 条：%d RED / %d INFO）"
          % (verdict, rc, len(findings),
             sum(1 for x in findings if x["sev"] == "RED"),
             sum(1 for x in findings if x["sev"] == "INFO")))
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="key 健康断供→恢复 SLA 哨兵腿：对读数件逐面断言 401 首报后"
                    " >24h 未恢复 ⇒ 升级行红点名（D-158 · ESC-21 · 卡 #276）；"
                    "缺读数/坏形 ⇒ fail-closed 红。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三验收语义真跑；零网络零盘读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：healthy-ok→0，"
                         "outage-25h-red/missing-first-401/bad-json→1）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.key-health-reading/v1；"
                         "缺件/不可读 ⇒ fail-closed 红）")
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
    # --check（只读真查；缺件/不可读 ⇒ fail-closed 红=缺读数）
    try:
        with open(args.check, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return print_findings(
            "key 健康断供→恢复 SLA 哨兵腿（D-158/#276）：读数件=%s" % args.check,
            [red("<file>", "读数件不可读：%s（%s）——缺读数 fail-closed 不猜绿"
                 % (args.check, exc))])
    return print_findings(
        "key 健康断供→恢复 SLA 哨兵腿（D-158/#276）：读数件=%s" % args.check,
        judge_payload(text, args.check))


if __name__ == "__main__":
    sys.exit(main())
