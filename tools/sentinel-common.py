#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sentinel-common.py — 夜轨B 哨兵公共件（单源；D-128 阶段一·单源件落盘，卡面 factory-os#245）

【为什么建本模块】
  夜轨B 双哨兵（在役部署副本 30-工件/夜轨B-20261106/sentinel-anolis.py 376 行与
  sentinel-local.py 687 行）同形骨架逐字近重复：log / log_heal / load_state /
  save_state / http / anomaly / push_heartbeat 同形函数两份各自维护，
  HEARTBEAT_URL 两处硬编码——修一处另一处静默漂移，两哨兵对同一世界给出相反
  结论（债证 30-工件/技术债清册-20261107.md D-128 行；台账锚行 2026-11-08
  锚补全·裁决 #31）。本模块把该公共骨架收为仓内单源件：两哨兵此后只留差异化
  探针与部署坐标（ESC-30 新门设计 / SR-07）。

【阶段纪律（本卡=阶段一·单源件落盘）】
  · 本卡只落 tools/sentinel-common.py ＋ selftest，零消费面改动：两哨兵是在役
    部署副本（哨兵 crontab */5 在役），改 import 须先公共件双读验证 ≥24h 读数
    一致再切、忌在飞直改——切换属阶段二另卡（卡面 #245 合线策略明示 depends_on
    跟进卡；台账锚行同款口径）。
  · 阶段一语义=台账锚行记载的同形骨架最小公共语义。锚行只记函数名族与
    HEARTBEAT_URL 硬编码债、未附在役副本函数体（副本不入库），故本件语义为
    锚行记载的公共骨架承载；时间戳格式/超时/去抖窗等具体口径以阶段二双读
    （在役副本实读）对齐为准——届时如需改，只改本件单处（这正是单源化的目的；
    P1 同款「禁借收编之机调值」纪律在阶段二对齐时承接）。
  · 【六函数/七名目 勘误（如实记录，2026-11-09 读卡）】卡面标题与台账锚行均记
    「六函数」，锚行同段列名却为七个（log/log_heal/load_state/save_state/http/
    anomaly/push_heartbeat）——按 log/log_heal 同属 log 族计六。本件七名全落
    （超集，不裁谁出局），selftest 逐函数覆盖；FAMILY_OF 为该勘误的机读面。

【函数族（锚行七名；卡面/台账「六函数」＝log/log_heal 同族并计（FAMILY_OF
  机读勘误面）；依赖注入式签名——路径/URL/时钟由调用哨兵传入，两哨兵差异化
  探针与部署坐标留在哨兵件内，阶段二以薄包装接线）】
  log / log_heal     追加式时间戳日志；log_heal 带 HEAL 标记（自愈事件可辨）；
                     失败返回 False 不抛（在役哨兵禁因日志坏而崩）
  load_state         JSON 状态读；缺席/坏 JSON/非 dict → default，永不抛
  save_state         JSON 状态原子写（同目录 tmp＋os.replace；sort_keys 定序——
                     双读逐字节可比）；失败返回 False 不抛且旧状态完好
  http               极简 HTTP 助手（data=None → GET，否则 POST-JSON）；响应
                     JSON 可析则返回解析值、否则原文；任何失败 → None 不抛
  anomaly            异常判定＋去抖记账：同类异常在 dedupe_s 窗口内 → 抑制，
                     窗口外/新类 → 产出事件并记账（历史有界防状态无界膨胀）；
                     纯函数返回 (event|None, new_state)，是否落盘/上报由调用面定
  push_heartbeat     心跳载荷构造＋推送；HEARTBEAT_URL 模块单源（原两哨兵各自
    （含 heartbeat_   硬编码收编一处）；载荷核心四键（ts/iso/sentinel/status）
     payload）        不可被 extra 覆写——身份字段防伪造；单轮失败不重试，节奏
                     由哨兵 crontab */5 承载，下轮自然补
  dupscan（附）      跨件同名函数体归一化逐字相同扫描——阶段二验收工装随单源件
                     先行落盘（锚行验收口径：抽取后 0 命中 → rc=0；修前快照/
                     死码复生 → rc=1 点名）；归一化=剥 docstring 后 ast.dump
                     （排版/注释/行号不敏感，代码结构与常量逐字相同才命中）

【rc 口径（与仓内对账门同款，三态 fail-loud）】
  --selftest   0 = 全部断言过；1 = 有断言败
  --dupscan    0 = 跨件零命中（抽取后形态）；1 = 有命中（同名同体，点名
                file:line 对）；2 = 不可证（读不出/语法坏——读不出就没有比对
                可言，rc=2 优先于 rc=1，不猜绿）

【纪律】selftest 零网络（http 面用 file:// 夹具与进程内 stub，不打真端口）、
  零仓内写入（临时目录用后即清，且自证 tools/ 目录快照前后不变）；判官/门禁/
  判据件零改动；HEARTBEAT_URL 缺省为本地回环无凭据形态（禁 secret 入件——
  生产 URL 由部署环境 SENTINEL_HEARTBEAT_URL 注入或阶段二双读时钉值，只改
  本件单处）。

用法：
  python3 -I tools/sentinel-common.py --selftest
  python3 -I tools/sentinel-common.py --dupscan FILE [FILE ...]
  python3 -I tools/sentinel-common.py            （无参：单源面函数清单＋心跳单源）
"""
import argparse
import ast
import copy
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.request

SCHEMA = "af.sentinel-common.v1"
DUPSCAN_SCHEMA = "af.sentinel-common.dupscan.v1"

RC_OK = 0
RC_DRIFT = 1          # dupscan：同名同体命中；selftest：断言败
RC_UNPROVABLE = 2     # dupscan：读不出/语法坏（fail-loud）

MODULE_BASENAME = "sentinel-common.py"

# ---- 单源面（六族七名；FAMILY_OF=「六函数」计数的机读勘误面）------------------
FUNCTION_INVENTORY = ("log", "log_heal", "load_state", "save_state", "http",
                      "anomaly", "push_heartbeat")
FAMILY_OF = {
    "log": "log", "log_heal": "log",
    "load_state": "load_state",
    "save_state": "save_state",
    "http": "http",
    "anomaly": "anomaly",
    "push_heartbeat": "push_heartbeat",
}
SIX_FAMILY_COUNT = 6   # 「六函数」口径＝log/log_heal 同族并计一、余五各计一 ⇒ 六族

# ---- 口径注（阶段二双读对齐点；均为可参数化缺省，双读后只改本件单处）----------
#   时间戳＝UTC tz-aware isoformat(seconds)；HTTP_TIMEOUT_S=10；
#   ANOMALY_DEDUPE_S=300；ANOMALY_HISTORY_MAX=200；
#   心跳 ok 判据＝http() 往返非 None（4xx/5xx/超时/断连皆败）。
DEFAULT_HEARTBEAT_URL = "http://127.0.0.1:8787/heartbeat"
HEARTBEAT_URL_ENV = "SENTINEL_HEARTBEAT_URL"
HTTP_TIMEOUT_S = 10.0
ANOMALY_DEDUPE_S = 300.0
ANOMALY_HISTORY_MAX = 200


def resolve_heartbeat_url(env=None):
    """心跳 URL 单源解析：环境 SENTINEL_HEARTBEAT_URL 优先，缺省本地回环。
    零凭据形态由 selftest 断言（scheme=http 且无 userinfo）。"""
    env = os.environ if env is None else env
    return env.get(HEARTBEAT_URL_ENV) or DEFAULT_HEARTBEAT_URL


HEARTBEAT_URL = resolve_heartbeat_url()


# ---------------------------------------------------------------------------
# 时间助手（双读确定性：全部公共函数接受 now 注入，缺省墙钟）
# ---------------------------------------------------------------------------
def now_ts(now=None):
    """epoch 秒；now 为数值则原样采纳（bool 不算数值——防 True 混入）。"""
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        return float(now)
    return time.time()


def now_iso(now=None):
    """UTC tz-aware ISO 时间戳（timespec=seconds；阶段二双读对齐点）。"""
    return datetime.datetime.fromtimestamp(
        now_ts(now), tz=datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# log 族（log / log_heal）
# ---------------------------------------------------------------------------
def log(log_path, msg, now=None):
    """追加一行「ISO 时间戳 消息」日志；失败返回 False 不抛（哨兵禁崩）。"""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (now_iso(now), msg))
        return True
    except OSError:
        return False


def log_heal(log_path, msg, now=None):
    """追加一行自愈日志（HEAL 标记，与普通日志同文件可辨）；失败 False 不抛。
    复用 log() 单一落盘路径——同形重复在本件内即已消解。"""
    return log(log_path, "HEAL " + msg, now=now)


# ---------------------------------------------------------------------------
# 状态读写（load_state / save_state）
# ---------------------------------------------------------------------------
def load_state(state_path, default=None):
    """读 JSON 状态；缺席/坏 JSON/非 dict → default（缺省 {}），永不抛。"""
    if default is None:
        default = {}
    try:
        with open(state_path, encoding="utf-8") as f:
            val = json.load(f)
    except (OSError, ValueError):
        return default
    return val if isinstance(val, dict) else default


def save_state(state_path, state):
    """原子写 JSON 状态（同目录 .tmp＋os.replace；sort_keys＋ensure_ascii=False
    定序——同状态逐字节稳定，双读可比）；失败返回 False 不抛、旧状态完好、
    .tmp 即清。"""
    tmp_path = state_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, state_path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# 传输助手（http）
# ---------------------------------------------------------------------------
def http(url, data=None, timeout=HTTP_TIMEOUT_S):
    """极简 HTTP 助手：data=None → GET，否则 POST（JSON 体）。响应 JSON 可析
    则返回解析值、否则原文；任何失败（含超时/4xx/5xx/断连/坏 URL）→ None，
    永不抛——在役哨兵禁因上报通道坏而崩，调用面以 None 判失败。"""
    try:
        if data is None:
            req = urllib.request.Request(url, method="GET")
        else:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    except Exception:
        return None


# ---------------------------------------------------------------------------
# anomaly 族（去抖判定＋有界记账；纯函数）
# ---------------------------------------------------------------------------
def anomaly(state, kind, detail="", now=None, dedupe_s=ANOMALY_DEDUPE_S):
    """异常判定＋去抖：state 内同类异常最近一条距今不足 dedupe_s → 抑制（返回
    (None, state 拷贝)）；窗口外或新类 → 产出事件并记账（历史封顶
    ANOMALY_HISTORY_MAX）。返回 (event|None, new_state)——纯函数不落盘，
    调用面决定 save_state/上报（阶段二哨兵薄包装接线点）。"""
    ts = now_ts(now)
    st = dict(state) if isinstance(state, dict) else {}
    hist = st.get("anomalies")
    hist = list(hist) if isinstance(hist, list) else []
    for rec in reversed(hist):                      # 最近一条同类在表尾
        if isinstance(rec, dict) and rec.get("kind") == kind:
            try:
                if ts - float(rec.get("ts")) < dedupe_s:
                    return None, st
            except (TypeError, ValueError):
                pass                                # 记账坏值不当抑制依据
            break
    event = {"ts": ts, "iso": now_iso(now), "kind": kind, "detail": detail}
    hist.append(event)
    if ANOMALY_HISTORY_MAX > 0:
        del hist[:-ANOMALY_HISTORY_MAX]           # 有界：只留最近 N 条
    st["anomalies"] = hist
    return event, st


# ---------------------------------------------------------------------------
# 心跳（heartbeat_payload / push_heartbeat）
# ---------------------------------------------------------------------------
def heartbeat_payload(sentinel, status="ok", extra=None, now=None):
    """构造心跳载荷（纯函数零网络——双读/自测可独立验证）。核心四键
    ts/iso/sentinel/status 后写，extra 同名键不得覆写（身份字段防伪造）。"""
    payload = dict(extra) if extra else {}
    payload["ts"] = now_ts(now)
    payload["iso"] = now_iso(now)
    payload["sentinel"] = sentinel
    payload["status"] = status
    return payload


def push_heartbeat(sentinel, status="ok", extra=None, now=None,
                   url=None, timeout=HTTP_TIMEOUT_S):
    """推送心跳到 HEARTBEAT_URL（模块单源；原两哨兵各自硬编码收编一处）。
    返回 (ok, payload)：ok=http() 往返非 None。单轮失败不重试——节奏由哨兵
    crontab */5 承载，下轮自然补。url=None → 模块 HEARTBEAT_URL 单源缺省；
    url 显式空串 → 禁用心跳（(False, payload) 零打点，部署面显式关闸形态）。"""
    target = HEARTBEAT_URL if url is None else url
    payload = heartbeat_payload(sentinel, status=status, extra=extra, now=now)
    if not target:
        return False, payload
    resp = http(target, data=payload, timeout=timeout)
    return resp is not None, payload


# ---------------------------------------------------------------------------
# dupscan：跨件同名函数体归一化逐字相同扫描（阶段二验收工装，阶段一先行落盘）
# ---------------------------------------------------------------------------
def _normalized_dump(fn_node):
    """归一化函数体：deepcopy 后剥首条字符串 docstring（空体补 Pass），
    ast.dump（默认不含行号/字段属性——排版与注释天然不敏感）。"""
    node = copy.deepcopy(fn_node)
    if node.body and isinstance(node.body[0], ast.Expr) \
            and isinstance(node.body[0].value, ast.Constant) \
            and isinstance(node.body[0].value.value, str):
        node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(node)


def dupscan(paths):
    """跨件同名函数体归一化逐字相同扫描。同名且归一体相同 ⇒ 命中（死码复生/
    未抽取形态）；同名不同体不命中（近重复属人审，扫描只防逐字复生）。
    返回 (rc, reading)：rc=0 零命中；rc=1 有命中（点名 file:line 对）；
    rc=2 不可证（任一件读不出/语法坏——fail-loud，优先于命中判定）。"""
    reading = {"schema": DUPSCAN_SCHEMA, "paths": list(paths),
               "hits": [], "unprovable": []}
    seen = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            tree = ast.parse(text, filename=path)
        except (OSError, SyntaxError, ValueError) as exc:
            reading["unprovable"].append(
                {"path": path, "error": "%s: %s" % (type(exc).__name__, exc)})
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                norm = _normalized_dump(node)
                prev = seen.get(node.name)
                if prev is None:
                    seen[node.name] = (norm, path, node.lineno)
                elif prev[0] == norm:
                    reading["hits"].append({
                        "name": node.name,
                        "first": "%s:%d" % (prev[1], prev[2]),
                        "second": "%s:%d" % (path, node.lineno)})
    if reading["unprovable"]:
        rc = RC_UNPROVABLE
    elif reading["hits"]:
        rc = RC_DRIFT
    else:
        rc = RC_OK
    reading["rc"] = rc
    return rc, reading


def dupscan_report(rc, reading):
    lines = ["[dupscan] 跨件同名函数体归一化逐字相同扫描（D-128 阶段二验收工装；"
             "抽取后应 0 命中）"]
    for h in reading["hits"]:
        lines.append("  [RED] 同名同体 %s：%s ↔ %s" % (h["name"], h["first"], h["second"]))
    for u in reading["unprovable"]:
        lines.append("  [RED·不可证] %s：%s" % (u["path"], u["error"]))
    verdict = {RC_OK: "跨件零命中（抽取后形态）", RC_DRIFT: "同名同体命中",
               RC_UNPROVABLE: "不可证"}[rc]
    lines.append("verdict: rc=%d %s（扫描 %d 件；命中 %d 对；不可证 %d 件）"
                 % (rc, verdict, len(reading["paths"]), len(reading["hits"]),
                    len(reading["unprovable"])))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# selftest：内嵌夹具（六族七名 好/坏 双语义＋dupscan 判别力＋零仓内写自证），
#   零网络（file:// 夹具与进程内 stub）、零仓内写入（临时目录用后即清）。
# ---------------------------------------------------------------------------
ST_FAILS = []
ST_TOTAL = [0]


def expect(name, cond, detail=""):
    ST_TOTAL[0] += 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           ("  " + detail) if detail else ""), flush=True)
    if not cond:
        ST_FAILS.append(name)


# 夹具：dupscan 判别力（A 件 / B 件同体 / B 件不同体 / 语法坏）
FIX_DUP_A = (
    "def probe(path):\n"
    "    \"\"\"A 件探针（docstring 将被归一化剥除）。\"\"\"\n"
    "    data = open(path).read()\n"
    "    return data\n"
)
FIX_DUP_B_SAME = (
    "def probe(path):\n"
    "    # B 件：仅 docstring/注释/排版不同，函数体归一化后与 A 逐字相同\n"
    "    data = open( path ) .read( )\n"
    "    return    data\n"
)
FIX_DUP_B_DIFF = (
    "def probe(path):\n"
    "    data = open(path).read()\n"
    "    return len(data)\n"
)
FIX_DUP_BROKEN = "def probe(:\n    pass\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def selftest():
    print("sentinel-common.py --selftest（D-128 阶段一·单源件落盘；零网络、零仓内写入）",
          flush=True)
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    tools_before = set(os.listdir(tools_dir))       # 零仓内写自证基线

    # ---- F1 结构自含（单源面＋心跳单源形态）------------------------------------
    expect("F1a FUNCTION_INVENTORY 七名齐备且皆为模块可调用",
           len(FUNCTION_INVENTORY) == 7
           and all(callable(globals().get(n, None)) for n in FUNCTION_INVENTORY),
           "/".join(FUNCTION_INVENTORY))
    expect("F1b 六函数口径=六族（log/log_heal 同族；勘误机读面）",
           len(FAMILY_OF) == 7 and len(set(FAMILY_OF.values())) == SIX_FAMILY_COUNT
           and FAMILY_OF["log"] == FAMILY_OF["log_heal"])
    expect("F1c HEARTBEAT_URL 单源零凭据形态（http 且无 userinfo）",
           HEARTBEAT_URL.startswith("http://") and "@" not in HEARTBEAT_URL
           and len(HEARTBEAT_URL) > len("http://"),
           HEARTBEAT_URL)
    expect("F1d resolve_heartbeat_url 环境覆写语义（注入优先/空串回退/缺省回环）",
           resolve_heartbeat_url({}) == DEFAULT_HEARTBEAT_URL
           and resolve_heartbeat_url(
               {HEARTBEAT_URL_ENV: "http://10.0.0.1:9000/hb"}) == "http://10.0.0.1:9000/hb"
           and resolve_heartbeat_url({HEARTBEAT_URL_ENV: ""}) == DEFAULT_HEARTBEAT_URL)

    tmp = tempfile.mkdtemp(prefix="sentinel-common-selftest-")
    try:
        # ---- F2 log 族（好：追加/格式/HEAL 标记/时间注入；坏：目录缺席）----------
        bad_log = os.path.join(tmp, "no-such-dir", "sentinel.log")
        expect("F2a 坏·目录缺席 log → False 不抛", log(bad_log, "x") is False
               and log_heal(bad_log, "x") is False)
        lp = os.path.join(tmp, "sentinel.log")
        t0 = 1780000000.0
        r1 = log(lp, "第一读", now=t0)
        r2 = log(lp, "第二读", now=t0 + 60)
        r3 = log_heal(lp, "探针自愈", now=t0 + 120)
        with open(lp, encoding="utf-8") as f:
            lines = f.read().splitlines()
        expect("F2b 好·追加语义三行全 True", (r1, r2, r3) == (True, True, True)
               and len(lines) == 3)
        expect("F2c 好·行格式=ISO 前缀＋消息尾；HEAL 行带标记",
               lines[0] == "%s 第一读" % now_iso(t0)
               and lines[1].endswith("第二读") and lines[1].startswith("2")
               and lines[2] == "%s HEAL 探针自愈" % now_iso(t0 + 120),
               lines[2])

        # ---- F3 state 族（好：roundtrip/定序/原子；坏：缺席/坏 JSON/不可序列化）--
        sp = os.path.join(tmp, "state.json")
        state = {"round": 3, "note": "夜轨B·哨兵", "guards":
                 [{"name": "scheduler", "stale_s": 2400}]}
        ok1 = save_state(sp, state)
        ok2 = save_state(sp, state)
        with open(sp, "rb") as f:
            raw1 = f.read()
        save_state(sp, state)
        with open(sp, "rb") as f:
            raw2 = f.read()
        expect("F3a 好·roundtrip（含非 ASCII/嵌套）", ok1 and ok2
               and load_state(sp) == state)
        expect("F3b 好·sort_keys 定序（同状态两写字节相同）且无 .tmp 残留",
               raw1 == raw2 and not os.path.exists(sp + ".tmp"))
        expect("F3c 坏·状态缺席 → default（缺省 {} 与自定义均验）",
               load_state(os.path.join(tmp, "absent.json")) == {}
               and load_state(os.path.join(tmp, "absent.json"), {"x": 1}) == {"x": 1})
        corrupt = os.path.join(tmp, "corrupt.json")
        _write(corrupt, "not-json{")
        nondict = os.path.join(tmp, "nondict.json")
        _write(nondict, "[1, 2]")
        expect("F3d 坏·坏 JSON/非 dict JSON → default 不抛",
               load_state(corrupt) == {} and load_state(corrupt, {"d": 1}) == {"d": 1}
               and load_state(nondict) == {})
        expect("F3e 坏·save 不可序列化 → False 且旧状态完好（原子性）",
               save_state(sp, {"f": object()}) is False
               and load_state(sp) == state and not os.path.exists(sp + ".tmp"))
        expect("F3f 坏·save 目录缺席 → False 不抛",
               save_state(bad_log + ".json", {}) is False)

        # ---- F4 http（好：file:// GET 两形态；坏：缺席/POST 通道败/坏 URL）-------
        jf = os.path.join(tmp, "reading.json")
        _write(jf, '{"ok": 1, "msg": "哨兵读数"}')
        tf = os.path.join(tmp, "plain.txt")
        _write(tf, "plain-ok")
        juri, turi = pathlib.Path(jf).as_uri(), pathlib.Path(tf).as_uri()
        expect("F4a 好·GET JSON → 解析 dict（file:// 夹具零网络）",
               http(juri) == {"ok": 1, "msg": "哨兵读数"})
        expect("F4b 好·GET 非 JSON → 原文", http(turi) == "plain-ok")
        expect("F4c 坏·GET 缺席 → None",
               http(pathlib.Path(os.path.join(tmp, "absent.json")).as_uri()) is None)
        dir_uri = pathlib.Path(tmp).as_uri()          # 目录 URL：通道必败形态
        expect("F4d 坏·POST 到目录 file:// → None（通道失败形态，不抛）",
               http(dir_uri, data={"heartbeat": 1}) is None)
        expect("F4e 坏·畸形 URL → None 不抛", http("not a url") is None)

        # ---- F5 anomaly（好：首报/抑制/异类/复报/有界；坏：state 非法）------------
        ev1, st1 = anomaly({}, "probe-stale", "mtime 超 2400s", now=t0)
        ev2, st2 = anomaly(st1, "probe-stale", "窗口内再报", now=t0 + 60)
        ev3, st3 = anomaly(st2, "probe-down", "异类首报", now=t0 + 60)
        ev4, st4 = anomaly(st3, "probe-stale", "窗口外复报", now=t0 + 301)
        expect("F5a 好·首报产出事件并记账",
               ev1 is not None and ev1["kind"] == "probe-stale"
               and ev1["detail"] == "mtime 超 2400s" and ev1["ts"] == t0
               and len(st1["anomalies"]) == 1)
        expect("F5b 好·窗口内同类 → 抑制且不重复记账",
               ev2 is None and st2["anomalies"] == st1["anomalies"])
        expect("F5c 好·异类不抑制；窗口外同类复报",
               ev3 is not None and ev4 is not None
               and len(st4["anomalies"]) == 3)
        st_big = {}
        for i in range(ANOMALY_HISTORY_MAX + 50):
            _, st_big = anomaly(st_big, "k%d" % i, now=t0 + i)
        expect("F5d 好·历史有界（封顶 ANOMALY_HISTORY_MAX）",
               len(st_big["anomalies"]) == ANOMALY_HISTORY_MAX
               and st_big["anomalies"][-1]["kind"] == "k%d" % (ANOMALY_HISTORY_MAX + 49))
        ev_bad, st_bad = anomaly(None, "k", now=t0)
        ev_bad2, _ = anomaly("junk-state", "k", now=t0)
        expect("F5e 坏·state 非法（None/str）→ 按新账处理不抛",
               ev_bad is not None and ev_bad2 is not None
               and st_bad["anomalies"][0]["kind"] == "k")

        # ---- F6 push_heartbeat（好：载荷/防覆写/单源打点；坏：通道败/空 URL）------
        payload = heartbeat_payload("sentinel-anolis", status="degraded",
                                    extra={"round": 7, "sentinel": "fake"},
                                    now=t0)
        expect("F6a 好·载荷核心四键＋extra 合入、ts/iso 形态",
               payload["ts"] == t0 and payload["iso"] == now_iso(t0)
               and payload["status"] == "degraded" and payload["round"] == 7
               and set(payload) == {"ts", "iso", "sentinel", "status", "round"})
        expect("F6b 好·extra 不得覆写核心键（sentinel 防伪）",
               payload["sentinel"] == "sentinel-anolis")
        saved_http = globals()["http"]
        try:
            calls = []

            def stub_http(url, data=None, timeout=None):
                calls.append((url, data, timeout))
                return {"ret": 0}

            globals()["http"] = stub_http
            ok, pl = push_heartbeat("sentinel-local", extra={"round": 1}, now=t0)
            ok2, pl2 = push_heartbeat("sentinel-local", url="http://127.0.0.1:1/hb",
                                      now=t0)
            expect("F6c 好·成功往返 (True, payload) 且缺省打点 URL=HEARTBEAT_URL 单源"
                   "（显式 url 覆写透传）",
                   ok is True and pl["sentinel"] == "sentinel-local"
                   and calls[0][0] == HEARTBEAT_URL and calls[0][1] == pl
                   and ok2 is True and calls[1][0] == "http://127.0.0.1:1/hb")

            def stub_http_dead(url, data=None, timeout=None):
                calls.append((url, data, timeout))
                return None

            globals()["http"] = stub_http_dead
            okd, _ = push_heartbeat("sentinel-local", now=t0)
            n_before = len(calls)
            oke, ple = push_heartbeat("sentinel-local", url="", now=t0)
            expect("F6d/e 坏·通道败 → False；url 显式空 → False 且零打点",
                   okd is False and oke is False and len(calls) == n_before
                   and ple["sentinel"] == "sentinel-local")
        finally:
            globals()["http"] = saved_http

        # ---- F7 dupscan 判别力（好：异体零命中/单件；坏：同体命中/语法坏）--------
        da = os.path.join(tmp, "sentinel-a.py")
        db_same = os.path.join(tmp, "sentinel-b-same.py")
        db_diff = os.path.join(tmp, "sentinel-b-diff.py")
        dbroken = os.path.join(tmp, "sentinel-broken.py")
        _write(da, FIX_DUP_A)
        _write(db_same, FIX_DUP_B_SAME)
        _write(db_diff, FIX_DUP_B_DIFF)
        _write(dbroken, FIX_DUP_BROKEN)
        rc, rd = dupscan([da, db_diff])
        expect("F7a 好·两件同名不同体 → rc=0 零命中", rc == RC_OK
               and rd["hits"] == [], dupscan_report(rc, rd).splitlines()[-1])
        rc, rd = dupscan([da, db_same])
        expect("F7b 坏·同名同体（仅 docstring/注释/排版异）→ rc=1 点名两坐标",
               rc == RC_DRIFT and len(rd["hits"]) == 1
               and rd["hits"][0]["name"] == "probe"
               and rd["hits"][0]["first"].endswith(".py:1")
               and rd["hits"][0]["second"].endswith(".py:1"),
               "%s ↔ %s" % (rd["hits"][0]["first"], rd["hits"][0]["second"]))
        rc, rd = dupscan([da, dbroken])
        expect("F7c 坏·语法坏件 → rc=2 不可证（优先于命中）",
               rc == RC_UNPROVABLE and len(rd["unprovable"]) == 1)
        rc, rd = dupscan([da])
        expect("F7d 好·单件入参 → rc=0（无跨件对）", rc == RC_OK)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- F8 阶段一纪律面（零仓内写自证）----------------------------------------
    expect("F8a 零仓内写自证：tools/ 目录快照前后不变",
           set(os.listdir(tools_dir)) == tools_before,
           "%d 件" % len(tools_before))

    if ST_FAILS:
        print("SELFTEST FAIL：%d/%d 条断言未过：%s"
              % (len(ST_FAILS), ST_TOTAL[0], "; ".join(ST_FAILS)))
        return 1
    print("断言 %d/%d 过（六族七名 好/坏 双语义＋dupscan 判别力＋零仓内写自证）"
          % (ST_TOTAL[0] - len(ST_FAILS), ST_TOTAL[0]))
    print("SELFTEST OK：D-128 阶段一·单源件落盘（两哨兵改 import 属阶段二另卡，"
          "本卡零消费面改动）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sentinel-common.py",
        description="夜轨B 哨兵公共件单源（log/state/http/anomaly/heartbeat；"
                    "D-128 阶段一·卡面 factory-os#245）")
    ap.add_argument("--selftest", action="store_true",
                    help="内嵌夹具自测（零网络、零仓内写入）")
    ap.add_argument("--dupscan", nargs="+", metavar="FILE", default=None,
                    help="跨件同名函数体归一化逐字相同扫描（阶段二验收工装："
                         "抽取后 0 命中 rc=0；命中 rc=1 点名；不可证 rc=2）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.dupscan:
        rc, reading = dupscan(args.dupscan)
        print(dupscan_report(rc, reading))
        return rc
    # 无参：单源面清单（机读面）
    print("单源面（六族七名；D-128 阶段一·tools/sentinel-common.py）：")
    for n in FUNCTION_INVENTORY:
        print("  %-14s %s 族" % (n, FAMILY_OF[n]))
    print("HEARTBEAT_URL = %s（单源；原两哨兵硬编码收编；env=%s 可覆写）"
          % (HEARTBEAT_URL, HEARTBEAT_URL_ENV))
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
