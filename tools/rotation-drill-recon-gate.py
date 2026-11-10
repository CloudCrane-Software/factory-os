#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/rotation-drill-recon-gate.py — 轮换演练三件读数验收门（D-147 · ESC-07 · 卡 #278）。

【锚号】D-147（账本/阶段欠账台账.md）　【卡号】factory-os issue #278
  （wave-14 迟建 · w14-d147-rotation-drill-gate · 允许路径=本件单件；
   判据=资源负载均衡与调度域-SOTA宪章-v1.md:198 R-14①②③——卡面引注，
   宪章件不在本卡触碰面）。

【为什么建本门（D-147 债本体）】
  68 项消费点清册在案但「会话日志泄露→全部消费点换新」实测演练无门强制——
  清册在案即可继续在役，演练证据腿从无判据（R-14 三件读数判据已立=纸面，
  机检门未建；ESC-07 新门设计栏）。本门把「一轮换演练是否真做过」做成机器
  断言：每个凭据面过门须同时存在三件读数——①并存窗读数（新旧两枚同时
  有效窗，带账本行/探针读数证据）②零业务中断探针（failed_requests=0
  实测）③旧钥停用负控实测（旧钥实测 401/403）；任一缺席 ⇒ 该凭据面证伪
  不了按不过（逐面逐件点名）。读数件带 expiry 登记：过期 ⇒ 该面读数作废、
  rc=1 待重演（演练读数有时效，不是一劳永逸的纸面证据）。

【判定语义（对读数件 JSON 的 drills[] 逐面判）】
  文件级：非 JSON/顶层非对象/schema 不符/drills 缺席或空壳 ⇒ 红 rc=1
    （缺读数/坏形 fail-closed，不猜绿）；--check 缺件/不可读 ⇒ 红 rc=1
    （缺读数件即缺演练证据，fail-closed）。
  逐面（drills[] 每条=一个凭据面的轮换演练读数）级联：
  · face（凭据面点名串）缺席/非非空串 ⇒ 红（面点名无从指起，fail-closed）；
  · expires 缺席/非 ISO 8601 带时区 ⇒ 红（读数时效不可证——「读数件带
    expiry 登记」是 D-147/R-14 明文契约面，缺登记即不可证新鲜度）；
    now > expires ⇒ 红「读数过期待重演」，该面读数作废不再深判三件
    （重演后自然重判）；
  · 未过期 ⇒ 三件逐件断言（缺一即红点名，全齐才绿）：
    ① coexist_window：both_valid_from/both_valid_until 双必带且 ISO 带时区；
      until ≤ from ⇒ 红（零长/负跨度窗证不了「同时有效」）；evidence 非空
      （R-14① 明文「有账本行/探针读数」——窗读数无出处不可证）；
    ② zero_interruption：failed_requests 必带且为整数（bool 不算——True
      会冒充 1）——非 0 ⇒ 红点名实测数（零中断=0 是实测读数不是声明）；
      0 ⇒ 过；probed_at 必带且带时区、不晚于 now（未来戳=探针读数不可证）；
    ③ old_key_negative_control：observed_status 必带且为整数 ∈ {401, 403}
      ——旧钥仍 200 ⇒ 红（未停用即演练未完成）；其他码 ⇒ 红（停用实证形
      只认 401/403——D-147 锚行明文；其他码可能是误配/断供，证不了「停用」）；
      probed_at 同②形制。
  · 三件全齐且过 ⇒ 逐件 INFO 留读数（窗长/0/实测码），另加面级 INFO 留
    有效期读数（剩 X.Xd）。

【读数件契约（schema af.rotation-drill-reading/v1）】
  {"schema": "af.rotation-drill-reading/v1",
   "drills": [
     {"face": "meters-api-key",
      "expires": "2026-12-09T00:00:00Z",
      "coexist_window": {"both_valid_from": "2026-11-08T20:00:00Z",
                         "both_valid_until": "2026-11-08T21:00:00Z",
                         "evidence": "轮换盘点总表-20261108 该面行＋探针 d147-1"},
      "zero_interruption": {"failed_requests": 0,
                            "probed_at": "2026-11-08T20:30:00Z"},
      "old_key_negative_control": {"observed_status": 401,
                                   "probed_at": "2026-11-08T22:00:00Z"}}]}
  时刻全 ISO 8601 且必须带时区（naive ⇒ 不可比 ⇒ 红）。读数件由演练腿产出
  后经 --check 入检；本门只读不产、零凭据（evidence 只是指针串，禁真钥）。

【退出码】0=绿（全部凭据面三件读数齐且未过期）；1=红（缺件/坏形/过期/
  负控不过，逐面逐件点名——卡面验收口径二值出红）；2=CLI 用法错（未选
  模式/夹具名不识——非数据裁决面）。

【用法】
  python3 -I tools/rotation-drill-recon-gate.py --selftest        # 内嵌夹具全跑（rc=0）
  python3 -I tools/rotation-drill-recon-gate.py --fixture <名>    # 单夹具（rc=该夹具裁决）
  python3 -I tools/rotation-drill-recon-gate.py --check <读数件路径>  # 真查演练读数
  夹具名：three-readings-ok / missing-coexist-window / missing-zero-interruption /
          missing-old-key-negative-control / all-pieces-null / piece-wrong-type /
          expired-reading / expiry-absent / old-key-still-valid / old-key-404 /
          interruption-counted / interruption-count-missing / window-negative-span /
          window-zero-span / window-evidence-missing / naive-ts / future-probe-ts /
          missing-face / multi-face-mixed / empty-drills / bad-json / wrong-schema
  （卡面三验收语义夹具：三件齐=three-readings-ok（rc=0）；缺任一=
   missing-coexist-window / missing-zero-interruption /
   missing-old-key-negative-control（rc=1 逐件点名）；过期=expired-reading
   （rc=1 待重演）。）

纪律：判据/判官/门禁件零改动（本件为 tools/ 新增件，不碰 all-gates.sh/
  gate-pins.list/点选面/宪章件）；零网络、零凭据、零写入（--check 只读）；
  红不猜绿（缺读数/坏形/过期即红）；selftest 全部真跑不编造。
"""

import argparse
import datetime
import json
import sys

SCHEMA = "af.rotation-drill-reading/v1"
OLD_KEY_DEAD_CODES = (401, 403)   # D-147 锚行明文：旧钥停用实证形（401/403）
GREEN, RED = 0, 1
SEV_ORDER = {"RED": 0, "INFO": 1}
RED_FAMILY = ("RED",)


def red(tag, msg):
    return {"sev": "RED", "tag": tag, "msg": "[RED] %s %s" % (tag, msg)}


def info(tag, msg):
    return {"sev": "INFO", "tag": tag, "msg": "[INFO] %s %s" % (tag, msg)}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_ts(value):
    """ISO 8601 带时区解析（Z 或 ±hh:mm 偏移）；缺席/无时区/非法 ⇒ None（调用方
    按 fail-closed 红：无时区基准的时间戳不能对 UTC 钟判序，不猜）。"""
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


def _fmt(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts is not None else "?"


# ---------------------------------------------------------------- 逐面判定 --
def rt(value):
    """repr 截断（防超长值刷屏；repr 自带引号）。"""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "…"


def judge_face(entry, idx, now):
    """单凭据面级联判定。返回 findings（sev ∈ RED/INFO）。"""
    if not isinstance(entry, dict):
        return [red("#%d" % idx, "读数条目非对象（%s）——读数件结构损坏，不猜绿"
                    % (rt(entry),))]
    face_id = entry.get("face")
    if not isinstance(face_id, str) or not face_id.strip():
        return [red("#%d" % idx, "face 缺席/非非空串（实得 %s）——凭据面点名"
                    "无从指起，fail-closed 红" % (rt(face_id),))]
    tag = face_id.strip()
    findings = []

    # —— expiry 登记（R-14/D-147：读数件带 expiry 登记，过期待重演）——
    exp_ts = parse_ts(entry.get("expires"))
    if exp_ts is None:
        findings.append(red(tag, "expires 缺席/非 ISO 8601 带时区（实得 %s）——读数"
                          "时效不可证（「读数件带 expiry 登记」是 D-147 明文契约"
                          "面），fail-closed 不猜绿" % (rt(entry.get("expires")),)))
    elif exp_ts < now:
        age_d = (now - exp_ts).total_seconds() / 86400.0
        findings.append(red(tag, "轮换演练读数过期待重演：expires=%s 已过 %.1fd——"
                          "过期读数作废，该面三件读数须重演后再过门"
                          "（R-14/D-147）" % (_fmt(exp_ts), age_d)))
        return findings           # 读数作废：不再深判三件（重演后自然重判）

    # —— ① 并存窗读数 ——
    piece = entry.get("coexist_window")
    if piece is None:
        findings.append(red(tag, "①并存窗读数缺席——该凭据面证伪不了按不过"
                          "（R-14①：新旧两枚同时有效窗须有账本行/探针读数；"
                          "D-147/ESC-07）"))
    elif not isinstance(piece, dict):
        findings.append(red(tag, "①并存窗读数坏形（非对象，实得 %s）——fail-closed "
                          "不猜绿" % (rt(piece),)))
    else:
        t_from = parse_ts(piece.get("both_valid_from"))
        t_until = parse_ts(piece.get("both_valid_until"))
        ev = piece.get("evidence")
        ok = True
        if t_from is None or t_until is None:
            findings.append(red(tag, "①并存窗读数坏形：both_valid_from/until 须 "
                              "ISO 8601 带时区（实得 %s / %s）——窗界不可证，"
                              "不猜绿" % (rt(piece.get("both_valid_from")),
                                        rt(piece.get("both_valid_until")))))
            ok = False
        elif t_until <= t_from:
            findings.append(red(tag, "①并存窗窗界坏形：until ≤ from（窗长 "
                              "%.0fs ≤ 0）——零长/负跨度窗证不了新旧两枚"
                              "「同时有效」（R-14①），不猜绿"
                              % ((t_until - t_from).total_seconds(),)))
            ok = False
        if not isinstance(ev, str) or not ev.strip():
            findings.append(red(tag, "①并存窗读数缺证据：evidence 缺席/空（实得 "
                              "%s）——R-14① 明文「有账本行/探针读数」，窗读数"
                              "无出处不可证" % (rt(ev),)))
            ok = False
        if ok:
            span = (t_until - t_from).total_seconds()
            findings.append(info(tag, "①并存窗读数在案：新旧两枚同时有效窗 %s→%s"
                                 "（窗长 %.0fmin；evidence=%s）"
                                 % (_fmt(t_from), _fmt(t_until), span / 60.0,
                                    ev.strip()[:40])))

    # —— ② 零业务中断探针 ——
    piece = entry.get("zero_interruption")
    if piece is None:
        findings.append(red(tag, "②零业务中断探针缺席——该凭据面证伪不了按不过"
                          "（R-14②；D-147/ESC-07）"))
    elif not isinstance(piece, dict):
        findings.append(red(tag, "②零业务中断探针坏形（非对象，实得 %s）——"
                          "fail-closed 不猜绿" % (rt(piece),)))
    else:
        failed = piece.get("failed_requests")
        ok = True
        if type(failed) is not int:      # bool 是 int 子类：True 会冒充 1，排除
            findings.append(red(tag, "②零业务中断探针读数坏形：failed_requests "
                              "缺席/非整数（实得 %s）——零中断须以实测 0 证明，"
                              "不可声明，不猜绿" % (rt(failed),)))
            ok = False
        elif failed != 0:
            findings.append(red(tag, "②零业务中断探针不过：failed_requests=%d ≠ "
                              "0——轮换窗内业务中断 %d 次（R-14②），该面须重演"
                              % (failed, failed)))
            ok = False
        pt = parse_ts(piece.get("probed_at"))
        if pt is None:
            findings.append(red(tag, "②零业务中断探针缺探针时刻：probed_at 缺席/"
                              "非 ISO 8601 带时区（实得 %s）——探针读数不可对钟，"
                              "不猜绿" % (rt(piece.get("probed_at")),)))
            ok = False
        elif pt > now:
            findings.append(red(tag, "②零业务中断探针时刻落于未来（%s > now）——"
                              "探针读数不可证，不猜绿" % (_fmt(pt),)))
            ok = False
        if ok:
            findings.append(info(tag, "②零业务中断探针过：failed_requests=0"
                                 "（probed_at=%s）" % (_fmt(pt),)))

    # —— ③ 旧钥停用负控实测 ——
    piece = entry.get("old_key_negative_control")
    if piece is None:
        findings.append(red(tag, "③旧钥停用负控缺席——该凭据面证伪不了按不过"
                          "（R-14③：旧钥实测 401/403；D-147/ESC-07）"))
    elif not isinstance(piece, dict):
        findings.append(red(tag, "③旧钥停用负控坏形（非对象，实得 %s）——"
                          "fail-closed 不猜绿" % (rt(piece),)))
    else:
        code = piece.get("observed_status")
        ok = True
        if type(code) is not int:
            findings.append(red(tag, "③旧钥停用负控读数坏形：observed_status 缺席/"
                              "非整数（实得 %s）——停用实证码无从读起，不猜绿"
                              % (rt(code),)))
            ok = False
        elif code == 200:
            findings.append(red(tag, "③旧钥停用负控不过：旧钥实测 200（仍有效）——"
                              "旧钥未停用即演练未完成（R-14③ 须 401/403），该面"
                              "须补停用腿"))
            ok = False
        elif code not in OLD_KEY_DEAD_CODES:
            findings.append(red(tag, "③旧钥停用负控不可证：旧钥实测 %d（停用实证形"
                              "只认 401/403——D-147 锚行明文）——其他码证不了"
                              "「停用」（可能是误配/断供），不猜绿" % (code,)))
            ok = False
        pt = parse_ts(piece.get("probed_at"))
        if pt is None:
            findings.append(red(tag, "③旧钥停用负控缺探针时刻：probed_at 缺席/"
                              "非 ISO 8601 带时区（实得 %s）——负控读数不可对钟，"
                              "不猜绿" % (rt(piece.get("probed_at")),)))
            ok = False
        elif pt > now:
            findings.append(red(tag, "③旧钥停用负控时刻落于未来（%s > now）——"
                              "负控读数不可证，不猜绿" % (_fmt(pt),)))
            ok = False
        if ok:
            findings.append(info(tag, "③旧钥停用负控实测过：旧钥实测 %d"
                                 "（probed_at=%s）" % (code, _fmt(pt))))

    # —— 面级有效期读数（expires 在场且未过期才走到这）——
    if exp_ts is not None:
        left_d = (exp_ts - now).total_seconds() / 86400.0
        findings.append(info(tag, "读数有效期至 %s（剩 %.1fd）——过期待重演"
                             % (_fmt(exp_ts), left_d)))
    return findings


def judge_payload(text, origin, now=None):
    """读数件全文判定（文件级 fail-closed + 逐面三件断言）。返回 findings。"""
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
        return [red("<file>", "读数件 %s schema 缺席/不符（期望 %s，实得 %s）——"
                    "读数契约不可证，不猜绿" % (origin, SCHEMA, rt(data.get("schema"))))]
    drills = data.get("drills")
    if not isinstance(drills, list) or not drills:
        return [red("<file>", "读数件 %s drills 缺席/空（空壳读数件）——无任何"
                    "凭据面读数即无演练证明，不猜绿" % (origin,))]
    findings = []
    for idx, entry in enumerate(drills):
        findings.extend(judge_face(entry, idx, now))
    return findings


def verdict_of(findings):
    """二值收敛：任一 RED ⇒ (red, 1)；否则绿 ⇒ (clean, 0)。"""
    if any(f["sev"] in RED_FAMILY for f in findings):
        return "red", RED
    return "clean", GREEN


# ---------------------------------------------------------------- 夹具与自测 --
def _ts(delta_s):
    """相对当前钟的 ISO Z 时间戳（夹具动态生成：真跑时读数随真钟走）。"""
    return (utcnow() + datetime.timedelta(seconds=delta_s)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def _win(**kw):
    base = {"both_valid_from": _ts(-7200), "both_valid_until": _ts(-3600),
            "evidence": "轮换盘点总表-20261108 该面行＋探针 d147-1"}
    base.update(kw)
    return base


def _probe(**kw):
    base = {"failed_requests": 0, "probed_at": _ts(-5400)}
    base.update(kw)
    return base


def _negctl(**kw):
    base = {"observed_status": 401, "probed_at": _ts(-1800)}
    base.update(kw)
    return base


def _drill(face="meters-api-key", **kw):
    base = {"face": face, "expires": _ts(30 * 86400),
            "coexist_window": _win(), "zero_interruption": _probe(),
            "old_key_negative_control": _negctl()}
    base.update(kw)
    for key in list(base):               # 值 None ⇒ 删键＝该件缺席（负例造形）
        if base[key] is None:
            del base[key]
    return base


def _doc(drills):
    return json.dumps({"schema": SCHEMA, "drills": drills}, ensure_ascii=False)


# （名，描述，卷面文本，期望 rc，红行须含串）
FIXTURES = [
    ("three-readings-ok",
     "三件读数齐且未过期（meters 面）⇒ rc=0——卡面三验收语义之「三件齐」",
     _doc([_drill()]), GREEN, None),
    ("missing-coexist-window",
     "①并存窗读数缺席 ⇒ rc=1 点名——「缺任一」负例一",
     _doc([_drill(coexist_window=None)]), RED, "并存窗"),
    ("missing-zero-interruption",
     "②零业务中断探针缺席 ⇒ rc=1 点名——「缺任一」负例二",
     _doc([_drill(zero_interruption=None)]), RED, "零业务中断"),
    ("missing-old-key-negative-control",
     "③旧钥停用负控缺席 ⇒ rc=1 点名——「缺任一」负例三",
     _doc([_drill(old_key_negative_control=None)]), RED, "旧钥停用负控"),
    ("all-pieces-null",
     "三件键全在场但值 null ⇒ 按缺席判（缺席另一形）⇒ rc=1 三件齐点名",
     _doc([_drill(coexist_window=None, zero_interruption=None,
                  old_key_negative_control=None)]), RED, "③旧钥停用负控"),
    ("piece-wrong-type",
     "①并存窗读数非对象（字符串）⇒ 坏形红",
     _doc([_drill(coexist_window="yes-it-rotated")]), RED, "坏形"),
    ("expired-reading",
     "读数过期（expires 距今 -1d）⇒ rc=1 待重演——卡面三验收语义之「过期」",
     _doc([_drill(expires=_ts(-86400))]), RED, "待重演"),
    ("expiry-absent",
     "expires 缺席 ⇒ 读数时效不可证红（「读数件带 expiry 登记」契约面）",
     _doc([_drill(expires=None)]), RED, "expires"),
    ("old-key-still-valid",
     "③旧钥实测 200（仍有效）⇒ 演练未完成红",
     _doc([_drill(old_key_negative_control=_negctl(observed_status=200))]),
     RED, "200"),
    ("old-key-404",
     "③旧钥实测 404（非停用实证形）⇒ 负控不可证红",
     _doc([_drill(old_key_negative_control=_negctl(observed_status=404))]),
     RED, "401/403"),
    ("interruption-counted",
     "②failed_requests=3 ⇒ 零中断证伪红（点名实测数）",
     _doc([_drill(zero_interruption=_probe(failed_requests=3))]),
     RED, "failed_requests=3"),
    ("interruption-count-missing",
     "②failed_requests 缺席 ⇒ 零中断无从以实测证明红",
     _doc([_drill(zero_interruption={"probed_at": _ts(-5400)})]),
     RED, "failed_requests"),
    ("window-negative-span",
     "①窗 until < from（负跨度）⇒ 窗界坏形红",
     _doc([_drill(coexist_window=_win(both_valid_from=_ts(-3600),
                                      both_valid_until=_ts(-7200)))]),
     RED, "窗界坏形"),
    ("window-zero-span",
     "①窗 until = from（零长窗）⇒ 证不了同时有效红",
     _doc([_drill(coexist_window=_win(both_valid_until=_ts(-7200)))]),
     RED, "零长"),
    ("window-evidence-missing",
     "①evidence 空白 ⇒ 窗读数无出处红（R-14①「有账本行/探针读数」）",
     _doc([_drill(coexist_window=_win(evidence="   "))]), RED, "evidence"),
    ("naive-ts",
     "probed_at 无时区基准 ⇒ 不可比对钟红",
     _doc([_drill(zero_interruption=_probe(probed_at="2026-11-08T20:30:00"))]),
     RED, "带时区"),
    ("future-probe-ts",
     "probed_at 落于未来（+1h）⇒ 探针读数不可证红",
     _doc([_drill(zero_interruption=_probe(probed_at=_ts(3600)))]),
     RED, "未来"),
    ("missing-face",
     "face 缺席 ⇒ 面点名无从指起红",
     _doc([_drill(face=None)]), RED, "face"),
    ("multi-face-mixed",
     "混卷（meters 面全齐、cnb-pat 面缺③）⇒ 只红缺席面、全齐面留 INFO——逐面点名不连坐",
     _doc([_drill(face="meters-api-key"),
           _drill(face="cnb-pat", old_key_negative_control=None)]),
     RED, "cnb-pat"),
    ("empty-drills",
     "空壳读数件（drills 空）⇒ 不猜绿",
     json.dumps({"schema": SCHEMA, "drills": []}), RED, "空壳"),
    ("bad-json",
     "坏形（非 JSON）⇒ fail-closed 红",
     "{not json", RED, "非 JSON"),
    ("wrong-schema",
     "schema 不符 ⇒ 读数契约不可证红",
     json.dumps({"schema": "other/v9", "drills": [_drill()]}), RED, "schema"),
]


def run_selftest():
    """内嵌夹具自测：卡面三验收语义各夹具真跑 + 边界/形制单元断言，
    零网络零盘读（夹具全内联，时间戳相对真钟动态生成）。"""
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
                  any(f["sev"] in RED_FAMILY and contains in f["msg"]
                      for f in findings),
                  "红行未含 %r：%s" % (contains, [f["msg"][:80] for f in findings]))

    # —— 单元断言（judge_face/judge_payload/parse_ts 纯函数面，钉钟）——
    pinned = datetime.datetime(2026, 11, 9, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)

    def _pts(delta_s):
        return (pinned + datetime.timedelta(seconds=delta_s)) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")

    def _face(expires_s=30 * 86400, **kw):
        d = {"face": "meters-api-key",
             "expires": None if expires_s is None else _pts(expires_s),
             "coexist_window": {"both_valid_from": _pts(-7200),
                                "both_valid_until": _pts(-3600),
                                "evidence": "ledger-row-7"},
             "zero_interruption": {"failed_requests": 0,
                                   "probed_at": _pts(-5400)},
             "old_key_negative_control": {"observed_status": 401,
                                          "probed_at": _pts(-1800)}}
        d.update(kw)
        for key in list(d):
            if d[key] is None:
                del d[key]
        return d

    # 全齐面：4 条 INFO（三件＋有效期），零红
    fall = judge_face(_face(), 0, pinned)
    check("unit.full-face-clean",
          verdict_of(fall) == ("clean", GREEN)
          and len([x for x in fall if x["sev"] == "INFO"]) == 4
          and not [x for x in fall if x["sev"] == "RED"], str(fall))
    # expiry 边界：恰 now 未过期（判 > 不判 ≥）；过 1s 即红待重演
    check("unit.expiry-exact-now-clean",
          verdict_of(judge_face(_face(expires_s=0), 0, pinned))
          == ("clean", GREEN))
    fexp = judge_face(_face(expires_s=-1), 0, pinned)
    check("unit.expiry-1s-over-red",
          verdict_of(fexp) == ("red", RED) and "待重演" in fexp[0]["msg"])
    # 过期即作废：只出 1 条红（不再深判三件），无 INFO
    check("unit.expired-void-no-deep-judge",
          len(fexp) == 1 and fexp[0]["sev"] == "RED", str(fexp))
    # ③停用实证码：401 与 403 双形皆过；200/404/500/非 int 皆红
    check("unit.negctl-403-also-passes",
          verdict_of(judge_face(_face(old_key_negative_control={
              "observed_status": 403, "probed_at": _pts(-1800)}), 0, pinned))
          == ("clean", GREEN))
    for code, label in ((200, "still-valid"), (404, "wrong-code"),
                        (500, "server-error"), ("401", "string-code"),
                        (None, "absent-code"), (True, "bool-code")):
        piece = {"probed_at": _pts(-1800)}
        if code is not None:
            piece["observed_status"] = code
        check("unit.negctl-%s-red" % label,
              verdict_of(judge_face(_face(old_key_negative_control=piece),
                                    0, pinned)) == ("red", RED))
    # ②零中断读数：0 过；1/True/0.0/缺场皆红（bool 冒充与浮点零不算实测 0）
    check("unit.interruption-zero-clean",
          verdict_of(judge_face(_face(zero_interruption={
              "failed_requests": 0, "probed_at": _pts(-5400)}), 0, pinned))
          == ("clean", GREEN))
    for failed, label in ((1, "one"), (True, "bool"), (0.0, "float-zero"),
                          (None, "absent"), ("0", "string-zero")):
        piece = {"probed_at": _pts(-5400)}
        if failed is not None:
            piece["failed_requests"] = failed
        check("unit.interruption-%s-red" % label,
              verdict_of(judge_face(_face(zero_interruption=piece),
                                    0, pinned)) == ("red", RED))
    # ①窗界：until=from+1s 过（正跨度）；until=from（零长）/from-1s（负）红
    check("unit.window-1s-span-clean",
          verdict_of(judge_face(_face(coexist_window={
              "both_valid_from": _pts(-7200), "both_valid_until": _pts(-7199),
              "evidence": "ledger-row-7"}), 0, pinned)) == ("clean", GREEN))
    for until_s, label in ((-7200, "zero-span"), (-7201, "negative-span")):
        fwin = judge_face(_face(coexist_window={
            "both_valid_from": _pts(-7200), "both_valid_until": _pts(until_s),
            "evidence": "ledger-row-7"}), 0, pinned)
        check("unit.window-%s-red" % label,
              verdict_of(fwin) == ("red", RED)
              and fwin[0]["sev"] == "RED", str(fwin))
    # ①evidence 非串（int）亦红；①窗界缺一侧红
    check("unit.window-evidence-int-red",
          verdict_of(judge_face(_face(coexist_window={
              "both_valid_from": _pts(-7200), "both_valid_until": _pts(-3600),
              "evidence": 7}), 0, pinned)) == ("red", RED))
    check("unit.window-missing-bound-red",
          verdict_of(judge_face(_face(coexist_window={
              "both_valid_until": _pts(-3600), "evidence": "ledger-row-7"}),
              0, pinned)) == ("red", RED))
    # 三件 null＝缺席：3 条红逐件点名（①②③ 各一）
    fnull = judge_face(_face(coexist_window=None, zero_interruption=None,
                             old_key_negative_control=None), 0, pinned)
    check("unit.all-pieces-null-3-reds",
          verdict_of(fnull) == ("red", RED)
          and len([x for x in fnull if x["sev"] == "RED"]) == 3
          and all(any(m in x["msg"] for m in ("并存窗", "零业务中断", "旧钥停用负控"))
                  for x in fnull if x["sev"] == "RED"), str(fnull))
    # 缺一红点名面名（tag 与 msg 都含凭据面名——点名可检索）
    fone = judge_face(_face(old_key_negative_control=None), 0, pinned)
    fone_red = [x for x in fone if x["sev"] == "RED"][0]
    check("unit.missing-piece-names-face",
          fone_red["tag"] == "meters-api-key"
          and "meters-api-key" in fone_red["msg"]
          and "①" not in fone_red["msg"] and "②" not in fone_red["msg"],
          str(fone))
    # 混卷：红只落缺席面（cnb-pat），全齐面（meters）保持 4 条 INFO——不连坐
    fmix = judge_payload(_doc([_face(),
                               _face(face="cnb-pat",
                                     old_key_negative_control=None)]),
                         "<t>", now=pinned)
    fmix_reds = [x for x in fmix if x["sev"] == "RED"]
    check("unit.mixed-precise-naming",
          verdict_of(fmix) == ("red", RED)
          and len(fmix_reds) == 1
          and fmix_reds[0]["tag"] == "cnb-pat"
          and len([x for x in fmix if x["sev"] == "INFO"
                   and x["tag"] == "meters-api-key"]) == 4, str(fmix))
    # expires 缺席（时效不可证红）时三件仍照判（时效与三件是两独立契约面）
    fexpabs = judge_face(_face(expires_s=None), 0, pinned)
    check("unit.expiry-absent-still-judges-pieces",
          verdict_of(fexpabs) == ("red", RED)
          and len([x for x in fexpabs if x["sev"] == "RED"]) == 1
          and len([x for x in fexpabs if x["sev"] == "INFO"]) == 3, str(fexpabs))
    # face 坏形：非串/空串/纯空白/条目非对象 ⇒ 红
    for bad, label in ((None, "absent"), (7, "int"), ("", "empty"),
                       ("   ", "blank")):
        entry = _face()
        if bad is not None:
            entry["face"] = bad
        else:
            del entry["face"]
        check("unit.bad-face-%s-red" % label,
              verdict_of(judge_face(entry, 0, pinned)) == ("red", RED))
    check("unit.entry-non-dict-red",
          verdict_of(judge_face(["not", "a", "dict"], 0, pinned))
          == ("red", RED))
    # parse_ts 形制：Z/偏移等价；无时区/非法/非串 ⇒ None
    check("unit.parse-z-and-offset-equivalent",
          parse_ts("2026-11-09T12:00:00Z")
          == parse_ts("2026-11-09T20:00:00+08:00") == pinned)
    for bad in ("2026-11-09T08:31:02", "", "  ", "2026-13-99T99:99:99Z",
                None, 123, "next-drill"):
        check("unit.parse-bad-%s-red" % (rt(bad),), parse_ts(bad) is None)
    # 文件级：顶层非对象 ⇒ 红（bad-json/空壳/schema 不符已在夹具面）
    check("unit.top-list-red",
          verdict_of(judge_payload(json.dumps([_face()]), "<t>"))
          == ("red", RED))
    # verdict 二值收敛
    check("unit.verdict-convergence",
          verdict_of([red("a", "x"), info("b", "y")]) == ("red", RED)
          and verdict_of([info("c", "z")]) == ("clean", GREEN))

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
        description="轮换演练三件读数验收门：并存窗/零业务中断探针/旧钥停用负控"
                    "（401/403）三件读数逐件断言，缺一即该凭据面不过（rc=1 点名）；"
                    "读数件带 expiry 登记，过期待重演（D-147 · ESC-07 · 卡 #278；"
                    "判据=宪章资源域 R-14①②③）；缺件/坏形 fail-closed。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（卡面三验收语义真跑；零网络零盘读）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：three-readings-ok→0，"
                         "missing-*/expired-reading→1）")
    ap.add_argument("--check", metavar="读数件路径",
                    help="真查读数件 JSON（af.rotation-drill-reading/v1；"
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
                                      judge_payload(text, "fixture:" + name))
        print("不识夹具名 %r（可用：%s）"
              % (args.fixture, " / ".join(f[0] for f in FIXTURES)),
              file=sys.stderr)
        return 2
    # --check（只读）
    try:
        with open(args.check, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return print_findings(
            "轮换演练三件读数验收门（D-147/#278）：读数件=%s" % args.check,
            [red("<file>", "读数件不可读：%s（%s）——缺读数件即缺演练证据，"
                 "fail-closed 不猜绿" % (args.check, exc))])
    return print_findings(
        "轮换演练三件读数验收门（D-147/#278）：读数件=%s" % args.check,
        judge_payload(text, args.check))


if __name__ == "__main__":
    sys.exit(main())
