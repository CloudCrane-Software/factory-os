#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""第三腿 netmap 断言门（「改盘未重启」型同源分叉盲区）——D-149/ESC-11。

【锚号】D-149（账本/阶段欠账台账.md D-149 行 · 2026-11-08 锚补全三要件）
【卡号】factory-os issue #243（wave-15 · w15-d149-netmap-assert-gate ·
  允许路径=本件单件 · pinned base bbb5f6e）
【新门设计源】30-工件/逃逸问题台账-20261108.md ESC-11 新门设计栏。

【为什么建本门（D-149 债本体）】
  policy-dual-hash 检测件的 disk 侧与 runtime 侧两腿可同源取值：「双态一致」
  恒真而真实生效策略（客户端 netmap）可仍旧态——检测件在役反成假绿背书
  （裁18 已把它入 gov cron */10，同源盲区本体未动）。本门补第三腿：抽 ≥1
  在役客户端 `tailscale debug netmap` 实读（`tailscale status --json` 作
  在役性辅证），由本件自行从原始 payload 推导「生效 ACL 摘要」（FilterRules
  规范化摘要——客户端实际执行的包过滤即生效 ACL），与盘面策略文件（acls）
  推导摘要比对：不一致 ⇒ 红「runtime 陈旧」（盘已改、控制面未下发/未重启）。
  摘要推导只在本件内做——不收外部预算好的摘要值（那会重造同源盲区）。

【与并联检测件的关系（锚行注记如实转登）】
  本门与 policy-dual-hash 检测件并联（gov cron 消费）；该检测件盘面正本在
  宿主/gov 侧，仓内镜像缺位（本仓 tools/ grep 零命中，2026-11-09 复核）——
  如实注记不猜其形制。gov cron 消费接线属宿主面留运营者窗（卡面明文），
  本件零网络：客户端实读（tailscale CLI）由宿主面采集成读数件，本件消费
  读数件做裁决；锚行「真跑 ≥1 客户端实读 → rc=0」即宿主面真跑口径。

【判据（卡面+锚行钉死，只增拦截禁放宽）】
  · 一致：盘面 acls 推导摘要 == ≥1 可证读数的 FilterRules 推导摘要 ⇒ rc=0
    （全部分叉为零且至少一腿在证——「抽 ≥1」即覆盖口径，废读数点名注记）。
  · 分叉：任一可证读数摘要 ≠ 盘面推导 ⇒ rc=1 红逐客户端点名「runtime 陈旧」
    （红优先：与废读数并存时红先出）。
  · 第三腿缺席/不可证：零读数（--reading-file 未给）／读数全废（schema 坏、
    netmap 缺席、FilterRules 缺席、时效不可证）／盘腿不可读（文件在而坏形，
    含 grants-only 面未覆盖跨腿编译——如实不可证不猜绿）⇒ rc=2，输出必带
    「未证真运行态」注记——禁裸绿（本件结构上不可能在零可证读数时出绿）。
  · 注记不判红：captured_at 距今 ≥24h ⇒ 「读数偏旧」注记（分叉红只来自
    摘要比对，判据单一源自含）；同客户端重复读数 ⇒ 注记。

【出口】0=一致；1=分叉（runtime 陈旧）；2=第三腿缺席/不可证（未证真运行
  态）；3=CLI 用法错（未选模式/参数缺/夹具名不识——非数据裁决面）。
  注：仓内 recon-gate 族多用 0/2/3，本卡卡面标题与锚行验收口径明文钉
  0/1/2（一致/分叉/缺席），判据单一源=卡面 ⇒ 从卡；用法错另设 3 不占 2。

【读数件契约（schema af.netmap-assert.reading/v1）】
  {"schema": "af.netmap-assert.reading/v1",
   "client": "worker-a",                       # 在役客户端标识（非空）
   "source": "tailscale debug netmap",         # 采集面来源（非空）
   "captured_at": "2026-11-09T08:00:00Z",      # 采集时刻（ISO8601，可解析）
   "netmap": {"FilterRules": [                 # 必给：规则面证据（原始 payload，
       {"src": ["tag:worker"],                 #   本件自行推导摘要，不收预摘要）
        "dst": [{"ip": "10.0.0.5", "bits": 32, "ports": ["22"]}]}]},
   "status": {"Self": {"HostName": "worker-a", "Online": true}}}  # 可选辅证
  盘面策略件：JSON/hujson（容错剥注释与尾逗号），取 "acls" 数组
  （{"action","src","dst":["host:ports",…]}）；grants-only 面跨腿编译未覆盖
  ⇒ 不可证不猜绿。规范化：src 条目小写去重排序；dst 统一 "addr|ports" 形
  （acl "10.0.0.5:22,443" 与 filter {"ip":"10.0.0.5","bits":32,
  "ports":["443","22"]} 同归一 "10.0.0.5|22,443"；bits=32 折叠、端口排序、
  int 端口转串），两侧同一规范化器 ⇒ 摘要可比。

【纪律】零网络、零凭据、零写入（--selftest/--fixture 只用 tempfile 临时件；
  --check/裁决面只读给定路径）；判官/门禁/判据件零改动（本件为 tools/ 新增
  单件，不碰 all-gates.sh/gate-pins.list/点选面）。

用法：
  python3 -I tools/netmap-assert-recon-gate.py --selftest          # 夹具全跑 rc=0
  python3 -I tools/netmap-assert-recon-gate.py --fixture <名>      # 单夹具（rc=裁决）
  python3 -I tools/netmap-assert-recon-gate.py --check --policy-file P \
      --reading-file R1 [--reading-file R2 …]                      # 形制面 rc=0/1
  python3 -I tools/netmap-assert-recon-gate.py --policy-file P \
      --reading-file R1 [--reading-file R2 …]                      # 裁决面 rc=0/1/2
  夹具名：consistent / divergent / absent / one-of-two-divergent /
          status-only / netmap-no-filterrules / bad-reading-schema /
          disk-bad-json / hujson-tolerant / multi-consistent
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile

READING_SCHEMA = "af.netmap-assert.reading/v1"
REPORT_SCHEMA = "af.netmap-assert.verdict/v1"
CAPTURE_FRESH_WARN_H = 24   # captured_at 偏旧注记线（小时；注记不判红）

GREEN, STALE, UNPROVEN, USAGE = 0, 1, 2, 3
VERDICT_WORD = {GREEN: "GREEN", STALE: "RED", UNPROVEN: "UNPROVEN"}
UNPROVEN_NOTE = "未证真运行态（禁裸绿）"


def err(msg):
    sys.stderr.write("[netmap-assert-recon-gate] %s\n" % msg)


class LegError(Exception):
    """腿证据不可用（盘面/读数坏形或证据不足）——不可证面，不猜绿。"""


class UsageError(Exception):
    """CLI 用法错——非数据裁决面（rc=3）。"""


# ---- hujson 容错（剥注释/尾逗号；串内内容不剥） --------------------------------

def _strip_comments(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1          # 尾逗号丢弃
                continue
        out.append(c)
        i += 1
    return "".join(out)


def load_json_tolerant(text):
    """JSON/hujson → 对象；坏形 ⇒ LegError（fail-closed）。"""
    try:
        return json.loads(_strip_trailing_commas(_strip_comments(text)))
    except ValueError as exc:
        raise LegError("非 JSON/hujson：%s" % exc)


# ---- 规范化与摘要（盘腿/读数腿同一套 ⇒ 摘要可比） ------------------------------

def _norm_ports(ports, origin):
    if ports is None:
        raise LegError("%s：端口段缺席（acl/filter 规则端口不可缺）" % origin)
    parts = ports.split(",") if isinstance(ports, str) else ports
    if not isinstance(parts, list):
        raise LegError("%s：端口段非法（%r）" % (origin, ports))
    norm = set()
    for p in parts:
        if isinstance(p, bool):
            raise LegError("%s：端口项非法（布尔 %r）" % (origin, p))
        if isinstance(p, int):
            p = str(p)
        if not isinstance(p, str) or not p.strip():
            raise LegError("%s：端口项非法（%r）" % (origin, p))
        norm.add(p.strip())
    return sorted(norm)


def _norm_src(items, origin):
    if not isinstance(items, list) or not items:
        raise LegError("%s：src 缺席/非列表/空" % origin)
    out = []
    for s in items:
        if not isinstance(s, str) or not s.strip():
            raise LegError("%s：src 条目非法（%r）" % (origin, s))
        out.append(s.strip().lower())
    return sorted(set(out))


def _norm_dst_str(s, origin):
    """acl dst 条目 "host:ports" → "host|p1,p2"。"""
    if not isinstance(s, str) or ":" not in s:
        raise LegError("%s：dst 条目非法（%r，须 host:ports）" % (origin, s))
    host, _, ports = s.rpartition(":")
    return "%s|%s" % (host.strip().lower(), ",".join(_norm_ports(ports, origin)))


def _norm_dst_obj(o, origin):
    """filter dst 条目 {"ip","bits","ports"} → "addr|p1,p2"（bits=32 折叠）。"""
    if not isinstance(o, dict):
        raise LegError("%s：dst 条目非对象（%r）" % (origin, o))
    ip = o.get("ip")
    if not isinstance(ip, str) or not ip.strip():
        raise LegError("%s：dst.ip 缺席/非法" % origin)
    addr = ip.strip().lower()
    if o.get("bits") not in (None, 32, "32"):
        addr = "%s/%s" % (addr, o.get("bits"))
    return "%s|%s" % (addr, ",".join(_norm_ports(o.get("ports"), origin)))


def rule_digest(rules):
    """规则集规范化摘要：条目 canonical JSON 排序后拼接 sha256（全 hex）。"""
    canon = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")) for r in rules)
    return hashlib.sha256("\n".join(canon).encode("utf-8")).hexdigest()


def policy_rules(data, origin):
    """盘面策略 → 规范化规则集（acls 面；grants-only 未覆盖跨腿编译 ⇒ 不可证）。"""
    if not isinstance(data, dict):
        raise LegError("%s：盘面顶层非对象（%s）" % (origin, type(data).__name__))
    acls = data.get("acls")
    if acls is None:
        raise LegError("%s：acls 缺席%s——跨腿编译未覆盖 ⇒ 不可证不猜绿"
                       % (origin, "（有 grants 无 acls）" if data.get("grants") is not None else ""))
    if not isinstance(acls, list) or not acls:
        raise LegError("%s：acls 非列表/空" % origin)
    rules = []
    for ent in acls:
        if not isinstance(ent, dict):
            raise LegError("%s：acl 条目非对象（%r）" % (origin, ent))
        action = ent.get("action") or "accept"
        if not isinstance(action, str) or not action.strip():
            raise LegError("%s：action 非法（%r）" % (origin, ent.get("action")))
        dst = ent.get("dst")
        if not isinstance(dst, list) or not dst:
            raise LegError("%s：dst 缺席/空（%r）" % (origin, ent))
        rules.append({"action": action.strip().lower(),
                      "src": _norm_src(ent.get("src"), origin),
                      "dst": sorted(_norm_dst_str(d, origin) for d in dst)})
    return rules


def netmap_rules(payload, origin):
    """客户端 netmap → 规范化规则集（FilterRules=实际执行的包过滤=生效 ACL）。"""
    if not isinstance(payload, dict):
        raise LegError("%s：netmap 缺席/非对象——status --json 辅证不能替代"
                       "规则面证据（须 tailscale debug netmap 实读）" % origin)
    fr = payload.get("FilterRules")
    if fr is None:
        fr = payload.get("filterRules")
    if not isinstance(fr, list) or not fr:
        raise LegError("%s：FilterRules 缺席/空——客户端规则面证据不足" % origin)
    rules = []
    for ent in fr:
        if not isinstance(ent, dict):
            raise LegError("%s：filter 条目非对象（%r）" % (origin, ent))
        dst = ent.get("dst")
        if not isinstance(dst, list) or not dst:
            raise LegError("%s：filter dst 缺席/空（%r）" % (origin, ent))
        rules.append({"action": "accept",   # 包过滤编译产物全 accept 语义
                      "src": _norm_src(ent.get("src"), origin),
                      "dst": sorted(_norm_dst_obj(d, origin) for d in dst)})
    return rules


def parse_ts(s):
    try:
        ts = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:       # 裸时刻按 UTC 归一（可比性）
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts


def load_reading_doc(doc, origin):
    """读数件裁决装载：坏形/证据不足 ⇒ LegError（第三腿不可证面）。"""
    if not isinstance(doc, dict):
        raise LegError("%s：读数顶层非对象（%s）" % (origin, type(doc).__name__))
    if doc.get("schema") != READING_SCHEMA:
        raise LegError("%s：schema 缺席/不符（期望 %s，实得 %r）"
                       % (origin, READING_SCHEMA, doc.get("schema")))
    client = doc.get("client")
    if not isinstance(client, str) or not client.strip():
        raise LegError("%s：client 缺席/非串——在役客户端标识不可证" % origin)
    source = doc.get("source")
    if not isinstance(source, str) or not source.strip():
        raise LegError("%s：source 缺席/非串——采集面不可证" % origin)
    captured_at = doc.get("captured_at")
    ts = parse_ts(captured_at) if isinstance(captured_at, str) else None
    if ts is None:
        raise LegError("%s：captured_at 缺席/不可解析（%r）——读数时效不可证"
                       % (origin, captured_at))
    rules = netmap_rules(doc.get("netmap"), origin)
    return {"ok": True, "origin": origin, "client": client.strip(),
            "source": source.strip(),
            "captured_at": captured_at, "captured_ts": ts,
            "digest": rule_digest(rules), "rule_n": len(rules),
            "has_status": isinstance(doc.get("status"), dict)}


# ---- 腿装载（文件面；只读） -----------------------------------------------------

def load_policy_file(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return {"ok": False, "origin": path, "err": "不可读（%s）" % exc}
    try:
        rules = policy_rules(load_json_tolerant(raw.decode("utf-8")), path)
    except (LegError, UnicodeDecodeError) as exc:
        return {"ok": False, "origin": path, "err": str(exc)}
    return {"ok": True, "origin": path, "digest": rule_digest(rules),
            "rule_n": len(rules)}


def load_reading_file(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return {"ok": False, "origin": path, "client": None,
                "err": "不可读（%s）" % exc}
    try:
        r = load_reading_doc(json.loads(raw.decode("utf-8")), path)
    except (LegError, ValueError, UnicodeDecodeError) as exc:
        return {"ok": False, "origin": path, "client": None, "err": str(exc)}
    return dict(r, ok=True, origin=path)


# ---- 裁决核（纯函数；--selftest/--fixture/真跑共用） ----------------------------

def _freshness(r, now):
    age = (now - r["captured_ts"]).total_seconds()
    if age < 0:
        return "client=%s captured_at 在未来（时钟面注记）" % r["client"]
    if age >= CAPTURE_FRESH_WARN_H * 3600:
        return "读数偏旧（client=%s captured_at=%s 距今 %.1fh ≥ %dh）" % (
            r["client"], r["captured_at"], age / 3600.0, CAPTURE_FRESH_WARN_H)
    return None


def judge(policy, readings, now=None):
    """policy=load_policy_file 形；readings=load_reading_file 形列表。
    返回 (rc, report)。结构保证：零可证读数或盘腿废 ⇒ 永不 GREEN（禁裸绿）。"""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    provable = [r for r in readings if r.get("ok")]
    broken = [r for r in readings if not r.get("ok")]
    diverged = [r for r in provable
                if policy.get("ok") and r["digest"] != policy["digest"]]

    notes = []
    if not policy.get("ok"):
        notes.append("盘腿不可读（%s）——%s" % (policy.get("origin"), policy.get("err")))
    if not readings:
        notes.append("第三腿缺席——未提供任何在役客户端读数（--reading-file）")
    elif not provable:
        notes.append("读数全废（%d 件不可用，逐件点名）——第三腿证据不足"
                     % len(broken))
    for b in broken:
        notes.append("废读数 %s——%s" % (b["origin"], b["err"]))
    for r in provable:
        note = _freshness(r, now)
        if note:
            notes.append(note)
    clients = [r["client"] for r in provable]
    dup = sorted({c for c in clients if clients.count(c) > 1})
    if dup:
        notes.append("同客户端重复读数（%s）——逐件独立裁决" % "、".join(dup))

    if not policy.get("ok"):
        rc = UNPROVEN          # 盘面推导集不可得 ⇒ 比对不可能 ⇒ 未证真运行态
    elif diverged:
        rc = STALE             # 红优先：实证分叉先出（废读数只注记）
    elif provable:
        rc = GREEN             # ≥1 可证读数且零分叉（抽 ≥1 覆盖口径）
    else:
        rc = UNPROVEN
    if rc == UNPROVEN:
        notes.append(UNPROVEN_NOTE)

    report = {
        "schema": REPORT_SCHEMA,
        "verdict": VERDICT_WORD[rc],
        "policy": {"ok": policy.get("ok", False), "origin": policy.get("origin"),
                   "digest": policy.get("digest"), "rule_n": policy.get("rule_n"),
                   "err": policy.get("err")},
        "readings": [{"client": r.get("client"), "origin": r["origin"],
                      "ok": r.get("ok", False), "digest": r.get("digest"),
                      "rule_n": r.get("rule_n"), "source": r.get("source"),
                      "captured_at": r.get("captured_at"),
                      "match": (r.get("digest") == policy.get("digest")
                                if (r.get("ok") and policy.get("ok"))
                                else None),   # 任一腿废 ⇒ 不可比（非分叉）
                      "err": r.get("err")} for r in readings],
        "counts": {"readings": len(readings), "provable": len(provable),
                   "broken": len(broken), "diverged": len(diverged)},
        "annotations": notes,
    }
    return rc, report


def render(report):
    word = {GREEN: "GREEN（已证真运行态）", STALE: "RED（runtime 陈旧）",
            UNPROVEN: "UNPROVEN（未证真运行态——禁裸绿）"}[{"GREEN": GREEN,
                                                        "RED": STALE,
                                                        "UNPROVEN": UNPROVEN}[report["verdict"]]]
    out = ["== netmap-assert-recon-gate · %s ==" % word]
    pol = report["policy"]
    if pol["ok"]:
        out.append("盘腿：%s 规则 n=%d 摘要=%s" % (pol["origin"], pol["rule_n"],
                                                  pol["digest"][:16]))
    else:
        out.append("盘腿：%s 不可读——%s" % (pol["origin"], pol["err"]))
    c = report["counts"]
    out.append("读数腿：%d 件（可证 %d｜废 %d｜分叉 %d）"
               % (c["readings"], c["provable"], c["broken"], c["diverged"]))
    for r in report["readings"]:
        if r["ok"] and r["match"] is True:
            out.append("  一致 client=%s 摘要=%s（source=%s，captured_at=%s）"
                       % (r["client"], r["digest"][:16], r["source"],
                          r["captured_at"]))
    for r in report["readings"]:
        if r["ok"] and r["match"] is False:
            out.append("  红 client=%s runtime 陈旧：实读摘要=%s ≠ 盘面推导=%s"
                       "（source=%s）" % (r["client"], r["digest"][:16],
                                          report["policy"]["digest"][:16],
                                          r["source"]))
    for r in report["readings"]:
        if not r["ok"]:
            out.append("  废 %s——%s" % (r["origin"], r["err"]))
    for note in report["annotations"]:
        out.append("  注记：%s" % note)
    return "\n".join(out)


# ---- 面：裁决 / 形制校验 --------------------------------------------------------

def run_adjudication(policy_path, reading_paths):
    rc, report = judge(load_policy_file(policy_path),
                       [load_reading_file(p) for p in reading_paths])
    print(render(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return rc


def run_check(policy_path, reading_paths):
    """形制面（--check）：存在性/形制校验，不做裁决——rc=0 全过 / rc=1 有缺陷
    （形制面出口，非裁决面 0/1/2；锚行实读采集属宿主面，本面只验已交材料）。"""
    rows = []
    pol = load_policy_file(policy_path)
    rows.append((pol["ok"], "policy %s：可解析且 acls 规则 n=%d、摘要=%s…"
                 % (policy_path, pol.get("rule_n", 0), (pol.get("digest") or "")[:16])
                 if pol["ok"] else "policy %s：缺陷——%s" % (policy_path, pol["err"])))
    for p in reading_paths:
        r = load_reading_file(p)
        if r["ok"]:
            rows.append((True, "reading %s：schema/client/netmap 形制过（client=%s，"
                         "FilterRules n=%d）" % (p, r["client"], r["rule_n"])))
        else:
            rows.append((False, "reading %s：缺陷——%s" % (p, r["err"])))
    print("== netmap-assert-recon-gate · --check 形制面 ==")
    for ok, msg in rows:
        print("  %s %s" % ("[OK]" if ok else "[缺陷]", msg))
    bad = sum(1 for ok, _ in rows if not ok)
    print("形制校验 %d/%d 过（rc=%d）" % (len(rows) - bad, len(rows), 1 if bad else 0))
    return 1 if bad else 0


# ---- 夹具（全内联；--fixture 经真文件装载路径裁决） ------------------------------

def _acl(action, src, dst):
    return {"action": action, "src": src, "dst": dst}


def _fr(src, dst):
    return {"src": src, "dst": dst}


ACL_A = _acl("accept", ["tag:worker"], ["10.0.0.5:22"])
ACL_B = _acl("accept", ["group:ops"], ["10.0.0.6:22,443"])
ACL_C = _acl("accept", ["tag:ci"], ["10.0.0.9:8443"])
FR_A = _fr(["tag:worker"], [{"ip": "10.0.0.5", "bits": 32, "ports": ["22"]}])
FR_B = _fr(["group:ops"], [{"ip": "10.0.0.6", "bits": 32, "ports": ["443", "22"]}])
FR_C = _fr(["tag:ci"], [{"ip": "10.0.0.9", "bits": 32, "ports": [8443]}])


def _policy_doc(acls):
    return json.dumps({"acls": acls}, ensure_ascii=False, indent=1)


HUJSON_POLICY = """// 夹具：hujson 注释与尾逗号容错
{
  "acls": [
    {"action": "accept", "src": ["tag:worker"], "dst": ["10.0.0.5:22",], // 尾逗号
    }, // 条目尾逗号
    # 行注释
  ], /* 块注释 */
}
"""


def _reading_doc(client, frs, captured_at="2026-11-09T08:00:00Z", **kw):
    doc = {"schema": READING_SCHEMA, "client": client,
           "source": "tailscale debug netmap", "captured_at": captured_at,
           "netmap": {"FilterRules": frs, "Node": {" StableID": "夹具"}},
           "status": {"Self": {"HostName": client, "Online": True}}}
    doc.update(kw)
    return doc


def _reading_text(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1)


# （名，描述，盘面文本，读数件文本列表，期望 rc，输出须含串列表）
FIXTURES = [
    ("consistent", "一致负例反例：盘=acls A+B，客户端实读 FilterRules 同归一 ⇒ rc=0",
     _policy_doc([ACL_A, ACL_B]),
     [_reading_text(_reading_doc("worker-a", [FR_A, FR_B]))],
     GREEN, ["已证真运行态"]),
    ("divergent", "分叉（D-149 本债形态）：盘已加 ci 规则（C），客户端实读仍旧态 ⇒ rc=1",
     _policy_doc([ACL_A, ACL_B, ACL_C]),
     [_reading_text(_reading_doc("worker-a", [FR_A, FR_B]))],
     STALE, ["runtime 陈旧", "worker-a"]),
    ("absent", "第三腿缺席：零读数 ⇒ rc=2 带注记禁裸绿",
     _policy_doc([ACL_A, ACL_B]), [],
     UNPROVEN, [UNPROVEN_NOTE, "第三腿缺席"]),
    ("one-of-two-divergent", "多客户端一腿分叉：红优先点名 worker-b，worker-a 一致注记",
     _policy_doc([ACL_A, ACL_B, ACL_C]),
     [_reading_text(_reading_doc("worker-a", [FR_A, FR_B, FR_C])),
      _reading_text(_reading_doc("worker-b", [FR_A, FR_B]))],
     STALE, ["runtime 陈旧", "worker-b"]),
    ("status-only", "读数只有 status 辅证无 netmap 规则面 ⇒ 证据不足 rc=2",
     _policy_doc([ACL_A, ACL_B]),
     [_reading_text({k: v for k, v in _reading_doc("worker-a", [FR_A]).items()
                     if k != "netmap"})],
     UNPROVEN, [UNPROVEN_NOTE, "辅证不能替代"]),
    ("netmap-no-filterrules", "netmap 在而 FilterRules 缺席 ⇒ 规则面证据不足 rc=2",
     _policy_doc([ACL_A, ACL_B]),
     [_reading_text(_reading_doc("worker-a", [FR_A], netmap={"Node": {}}))],
     UNPROVEN, [UNPROVEN_NOTE, "FilterRules 缺席"]),
    ("bad-reading-schema", "读数 schema 不符 ⇒ 全废不可证 rc=2",
     _policy_doc([ACL_A, ACL_B]),
     [_reading_text(dict(_reading_doc("worker-a", [FR_A]), schema="other/v9"))],
     UNPROVEN, [UNPROVEN_NOTE, "schema"]),
    ("disk-bad-json", "盘腿坏形（非 JSON）⇒ 盘面推导集不可得 rc=2",
     "{ not json",
     [_reading_text(_reading_doc("worker-a", [FR_A]))],
     UNPROVEN, [UNPROVEN_NOTE, "盘腿"]),
    ("hujson-tolerant", "盘面 hujson（注释+尾逗号）容错解析 ⇒ 与实读一致 rc=0",
     HUJSON_POLICY,
     [_reading_text(_reading_doc("worker-a", [FR_A]))],
     GREEN, ["已证真运行态"]),
    ("multi-consistent", "多客户端全一致（含 int 端口/端口乱序归一）⇒ rc=0",
     _policy_doc([ACL_A, ACL_B, ACL_C]),
     [_reading_text(_reading_doc("worker-a", [FR_A, FR_B, FR_C])),
      _reading_text(_reading_doc("worker-b", [FR_C, FR_B, FR_A]))],
     GREEN, ["已证真运行态"]),
]

FIXTURE_NAMES = [f[0] for f in FIXTURES]


def _adjudicate_texts(policy_text, reading_texts):
    """夹具走真路径：落临时件 → 文件装载 → judge（裁决核与真跑同一入口）。"""
    with tempfile.TemporaryDirectory() as td:
        pp = os.path.join(td, "policy.json")
        with open(pp, "w", encoding="utf-8") as fh:
            fh.write(policy_text)
        rps = []
        for i, text in enumerate(reading_texts):
            rp = os.path.join(td, "reading-%d.json" % i)
            with open(rp, "w", encoding="utf-8") as fh:
                fh.write(text)
            rps.append(rp)
        rc, report = judge(load_policy_file(pp), [load_reading_file(p) for p in rps])
        return rc, render(report), report


def run_fixture(name):
    for fname, desc, ptext, rtexts, _rc, _c in FIXTURES:
        if fname == name:
            print("夹具 %s：%s" % (name, desc))
            rc, text, _report = _adjudicate_texts(ptext, rtexts)
            print(text)
            print("verdict=%s rc=%d" % (VERDICT_WORD[rc], rc))
            return rc
    raise UsageError("不识夹具名 %r（可用：%s）" % (name, " / ".join(FIXTURE_NAMES)))


# ---- 自证面（零网络零凭据；夹具真跑 + 判定核单元 + 形制面） ----------------------

def run_selftest():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # ① 夹具全跑（三验收语义各至少一例；经真文件装载路径）
    for fname, desc, ptext, rtexts, expect_rc, contains in FIXTURES:
        rc, text, report = _adjudicate_texts(ptext, rtexts)
        check("fixture.%s" % fname, rc == expect_rc,
              "desc=%s rc=%d（期望 %d）\n%s" % (desc, rc, expect_rc, text))
        for s in contains:
            check("fixture.%s.contains[%s]" % (fname, s), s in text,
                  "输出未含 %r" % s)

    # ② 禁裸绿结构断言：零读数/读数全废/盘腿废 ⇒ 永不 GREEN
    pol_ok = load_policy_file(_write_tmp(_policy_doc([ACL_A])))
    rd_ok = load_reading_file(_write_tmp(_reading_text(_reading_doc("w", [FR_A]))))
    for label, pol, rds in (
            ("零读数", pol_ok, []),
            ("读数全废", pol_ok, [dict(rd_ok, ok=False, err="夹具废")]),
            ("盘腿废", dict(pol_ok, ok=False, err="夹具废"), [rd_ok])):
        rc, report = judge(pol, rds, now=datetime.datetime(2026, 11, 9, 9, 0,
                                                           tzinfo=datetime.timezone.utc))
        text = render(report)
        check("nogreen.%s" % label, rc == UNPROVEN and UNPROVEN_NOTE in text,
              "rc=%s text=%s" % (rc, text))

    # ③ 规范化器单元（摘要可比性的根）
    d_ab1 = rule_digest(policy_rules(json.loads(_policy_doc([ACL_A, ACL_B])), "t"))
    d_ab2 = rule_digest(policy_rules(json.loads(_policy_doc([ACL_B, ACL_A])), "t"))
    check("unit.rule-order-invariant", d_ab1 == d_ab2,
          "规则乱序摘要应同：%s vs %s" % (d_ab1[:16], d_ab2[:16]))
    d_c = rule_digest(policy_rules(json.loads(_policy_doc([ACL_C])), "t"))
    check("unit.rule-diff-bites", d_ab1 != d_c, "不同规则集摘要须不同")
    # acl "10.0.0.9:8443" 与 filter {ip,bits:32,ports:[8443 int]} 同归一
    pol_c = policy_rules(json.loads(_policy_doc([ACL_C])), "t")
    net_c = netmap_rules({"FilterRules": [FR_C]}, "t")
    check("unit.acl-filter-normalize-equal",
          rule_digest(pol_c) == rule_digest(net_c),
          "acl 与 filter 规范化后须同摘要：%r vs %r" % (pol_c, net_c))
    # bits=24 保留为 cidr；端口串/列表/去重
    check("unit.bits24-kept",
          _norm_dst_obj({"ip": "10.6.0.0", "bits": 24, "ports": ["443"]}, "t")
          == "10.6.0.0/24|443", "")
    check("unit.ports-dedup-sort",
          _norm_dst_str("10.0.0.6:443,22,443", "t") == "10.0.0.6|22,443", "")
    for bad in (None, 22, [""], [True]):   # 顶层面非列表/空项/布尔项须咬
                                                      #（串 "22" 为合法单端口形）
        try:
            _norm_ports(bad, "t")
            check("unit.bad-ports-%r" % (bad,), False, "未咬")
        except LegError:
            check("unit.bad-ports-%r" % (bad,), True)
    try:
        policy_rules({"grants": [{"src": ["g:x"], "dst": []}]}, "t")
        check("unit.grants-only-unprovable", False, "未咬")
    except LegError as exc:
        check("unit.grants-only-unprovable", "grants" in str(exc), str(exc))

    # ④ hujson 剥离单元（串内 // 不剥；尾逗号在对象/数组两形）
    j = load_json_tolerant('{ "a": "http://x#y", "b": [1,2,], // c\n "d": 1, }')
    check("unit.hujson", j == {"a": "http://x#y", "b": [1, 2], "d": 1}, repr(j))
    try:
        load_json_tolerant("{ not json")
        check("unit.hujson-bad-bites", False, "未咬")
    except LegError:
        check("unit.hujson-bad-bites", True)

    # ⑤ 时效注记单元（注记不判红）
    now = datetime.datetime(2026, 11, 9, 9, 0, tzinfo=datetime.timezone.utc)
    fresh = _reading_doc("w", [FR_A], captured_at="2026-11-09T07:30:00Z")
    stale = _reading_doc("w", [FR_A], captured_at="2026-11-07T07:30:00Z")
    rcf, repf = judge(pol_ok, [load_reading_doc(fresh, "t")], now=now)
    rcs, reps = judge(pol_ok, [load_reading_doc(stale, "t")], now=now)
    check("unit.fresh-green", rcf == GREEN and not any("偏旧" in n for n in repf["annotations"]),
          str(repf["annotations"]))
    check("unit.stale-note-not-red", rcs == GREEN and any("读数偏旧" in n for n in reps["annotations"]),
          str(reps["annotations"]))
    check("unit.naive-ts-utc", parse_ts("2026-11-09 07:30:00") is not None
          and parse_ts("2026-11-09 07:30:00").tzinfo is not None, "")

    # ⑥ 形制面（--check）：好材料 rc=0；坏材料（缺文件+坏 schema）rc=1
    with tempfile.TemporaryDirectory() as td:
        good_pol = os.path.join(td, "p.json")
        with open(good_pol, "w", encoding="utf-8") as fh:
            fh.write(_policy_doc([ACL_A]))
        good_rd = os.path.join(td, "r.json")
        with open(good_rd, "w", encoding="utf-8") as fh:
            fh.write(_reading_text(_reading_doc("worker-a", [FR_A])))
        bad_rd = os.path.join(td, "bad.json")
        with open(bad_rd, "w", encoding="utf-8") as fh:
            fh.write('{"schema": "other/v1"}')
        check("check.good", run_check(good_pol, [good_rd]) == 0, "")
        check("check.bad", run_check(good_pol, [bad_rd, os.path.join(td, "missing.json")]) == 1, "")

    failed = [(n, d) for (n, ok, d) in checks if not ok]
    for (n, ok, d) in checks:
        print("  %s %s%s" % ("PASS" if ok else "FAIL", n,
                             (" — " + d[:160]) if (d and not ok) else ""))
    print("selftest %d/%d 过（三态夹具真跑＋禁裸绿结构断言＋规范化器/hujson/时效"
          "单元＋--check 形制面）" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


def _write_tmp(text):
    fd, path = tempfile.mkstemp(prefix="netmap-assert-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ---- main ----------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError("参数错：%s（-h 看用法）" % message)


def parse_args(argv):
    ap = _Parser(add_help=True,
                 description="第三腿 netmap 断言门（D-149 · ESC-11 · 卡 #243）："
                             "在役客户端 netmap 实读的生效 ACL 摘要与盘面 acls 推导"
                             "集比对——一致 rc=0／分叉 rc=1（runtime 陈旧）／第三腿"
                             "缺席不可证 rc=2 带「未证真运行态」注记禁裸绿。")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具全跑（三态夹具＋单元断言；零网络零凭据）")
    ap.add_argument("--fixture", metavar="名",
                    help="单跑一个内嵌夹具（rc=该夹具裁决：%s）"
                         % " / ".join("%s→%d" % (f[0], f[4]) for f in FIXTURES))
    ap.add_argument("--check", action="store_true",
                    help="形制面：只做存在性/形制校验（rc=0/1），不裁决")
    ap.add_argument("--policy-file", metavar="路径",
                    help="盘面策略件（JSON/hujson，取 acls）")
    ap.add_argument("--reading-file", metavar="路径", action="append",
                    help="客户端读数件（af.netmap-assert.reading/v1；可多次）")
    args = ap.parse_args(argv)
    modes = [bool(args.selftest), args.fixture is not None, bool(args.check)]
    if sum(modes) > 1:
        raise UsageError("--selftest/--fixture/--check 须且仅须选一模式")
    if not any(modes) and not (args.policy_file and args.reading_file):
        raise UsageError("裁决面须 --policy-file 与 ≥1 个 --reading-file"
                         "（或选 --selftest / --fixture 名 / --check）")
    if args.check and not (args.policy_file and args.reading_file):
        raise UsageError("--check 形制面同须 --policy-file 与 ≥1 个 --reading-file")
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv)
        if args.selftest:
            return run_selftest()
        if args.fixture is not None:
            return run_fixture(args.fixture)
        if args.check:
            return run_check(args.policy_file, args.reading_file)
        return run_adjudication(args.policy_file, args.reading_file)
    except UsageError as exc:
        err(str(exc))
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
