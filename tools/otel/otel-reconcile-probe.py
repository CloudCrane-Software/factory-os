#!/usr/bin/env python3
"""otel-reconcile-probe.py — ch-mes-reconcile 实查模式的机器消费者（常驻面）。

背景（2026-11-02 RT 批·确证发现；台账：计划/研究组/红队终局轮-20261101/逃逸问题台账.md
RT-E116）：tools/otel/ch-mes-reconcile.py 的 R1/R2/R3/R6 是本仓**唯一**能抓「OTel lane
静默」的规则集（MES 有新增而 OTel 零行→红 / OTel 行数不足阈值→红 / 事件 lane 静默→红 /
发射面末笔写入超阈→可见），但修复前**实查模式零机器消费者**：
  ①门内只有 --selftest 夹具（tools/all-gates.sh L3「ch-mes-reconcile.py --selftest」行），
    实查不在任何门；
  ②无调度器（crontab 仅 obs-patrol 一行、systemd --user 无 reconcile 单元）——
    2026-11-01 同窗 MES 侧活着（状态观测/alarms.log 147 条 mes-queue-replay/A0/A4 记录）
    而 OTel 侧零入库，正是 R1 的触发条件，却因无人跑实查，40h+ 静默无人见。

本件=实查的消费者（**判据不复制**：reconcile/fetch_counts 直接从 ch-mes-reconcile.py
导入，唯一源；本件只补「谁来跑 / 跑了谁消费 / 停了谁报警」三层，ch-mes-reconcile 的
任一断言、阈值、语义一字未改——2026-11-03 起判据源自身有语义收紧，见下「2026-11-03」段，
本件仍只消费、不复制判据）：

  run 模式（调度器调用；cron 每 15min 一轮）：
    跑 ch-mes-reconcile 实查（真库真比数）→ 原子写状态面 状态观测/otel-reconcile.json
    → 判定 red 时追加 状态观测/alarms.log 报警（运维报警面；字段格式同 factory-keepalive
    的 mes-ch 报警 ts/level/code/message/since）→ 退出码 0=绿（含 warn）/1=红/2=执行错。
    CH 不可达等执行错同样落状态面（status=error）——不可证即不猜绿。

  check 模式（门消费面；all-gates L3 常驻门位，与 sil-verdict-probe 同先例）：
    只读状态面，判三件事——①状态面在位可解析（缺件/坏 JSON → rc=2，不静默放行）；
    ②读数新鲜（mtime ≤ MAX_AGE_S=1800s=2 倍调度周期）——**巡检本身停摆即红**（死手
    断言：本次事故形态「静默无人见」的正面堵法）；③末次判定非 red。
    零网络：门跑时不需要 CH 在线（CH 不可达在 run 模式判执行错 → 状态面 error → 红）。

  selftest 模式：夹具自证（零网络零库），覆盖 check 模式的消费语义映射
    （绿/warn/红/执行错/过期/不可识别）与 run→状态面的字段契约（含绿路对照，
    防「门被改成恒红也能过」）。

2026-11-03（判据源语义收紧，本件只跟随、不复制判据）：确证发现——「MES 空闲 + OTel 轨
整链静默」时门消费 rc=0 绿：判据源 R1/R2 以 mes_rows>0 为前提、R3 被调度档
--allow-mes-idle 豁免、R4 双零默认记 PASS、R6 默认 severity=warn 且调度档未开
--strict-stale —— 四洞叠加，恰是 RT-E116 修的「静默无人见」事故形态在工厂停工期复现。
修复落在判据源 tools/otel/ch-mes-reconcile.py：①R4 双零区分「真空闲」与「整链静默」
（已知发射面本窗内无一写入 → 记红，不再默认 PASS）；②R6 严重度分档（持续发射面超阈
未写=从活变死 → 记红挡门；按需发射面仍 WARN 不挡门）。本件相应只做两件事：透传
write_counts 判据参数、状态面增记 otel_write_counts（分档依据可复核）。门消费映射
（judge_state）一字未改——status=red 即 rc=1、红牌（code=otel-lane-silent）照旧写，
即本件的报警面与门位无需改判即得堵法。

用法：
  tools/otel/otel-reconcile-probe.py --run                 # 跑实查并落状态面（调度器姿势）
  tools/otel/otel-reconcile-probe.py --check                # 消费状态面（门姿势，零网络）
  tools/otel/otel-reconcile-probe.py --selftest             # 夹具自证（进 all-gates L3）

2026-11-03（R5 默认收紧，本件只改透传默认、判据仍在 ch-mes-reconcile.py）：确证发现——
wo-live-smoke 7 行戳 2027-01-15 已进 mes_event+mes_line_hour 未来桶，而 --strict-future
原默认 False、cron 行未传 → R5 恒 WARN → judge_state rc=0 绿 →「无任何门/告警能发现」。
本件 --strict-future 改默认 True（BooleanOptionalAction，--no-strict-future 可显式降档），
cron 现有行（--run --allow-mes-idle）零改动即走红档：未来戳行>0 → 判定 red → 本件照旧
写 alarms.log 红牌 + 门消费 rc=1。

纪律：只读真库；只写本仓状态观测面（状态 json + alarms.log）；凭据只走 ch_client 既有链
（0600 文件/env），本件不接触口令，输出只含端点与库名；判据只在 ch-mes-reconcile.py
一处（2026-11-03 前本件不改判据源本体；该批判据源自身被收紧，见上段）。
"""
import argparse
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(os.path.dirname(HERE))          # tools/otel → tools → 仓根
RECONCILE_SRC = os.path.join(HERE, "ch-mes-reconcile.py")
STATE_FILE = os.path.join(WS, "状态观测", "otel-reconcile.json")
ALARMS_LOG = os.path.join(WS, "状态观测", "alarms.log")
MAX_AGE_S = 1800          # 状态面读数可信上界（cron 15min 一轮 → 2 倍容差）
ALARM_CODE = "otel-lane-silent"


# ---------------------------------------------------------------- 判据源（唯一源，不复制）
def load_reconcile():
    """导入 ch-mes-reconcile.py 本体（判据单一源）。导入失败 → 抛（调用方 fail-closed）。"""
    spec = importlib.util.spec_from_file_location("ch_mes_reconcile", RECONCILE_SRC)
    if spec is None or spec.loader is None:
        raise RuntimeError("判据源 spec 构建失败：%s" % RECONCILE_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 状态面
def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write_state(state, path=None):
    """原子写状态面（tmp + os.replace）：门读到的一定是完整 JSON，不会半截。"""
    path = path or STATE_FILE
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def read_state(path=None):
    """→ (state|None, age_s|None, err|None)。读不到/坏 JSON → (None, None, 原因)。"""
    path = path or STATE_FILE
    try:
        with open(path, "rb") as f:
            raw = f.read().decode("utf-8", "replace")
    except OSError as e:
        return None, None, "状态面不可读：%s（%s）" % (path, e)
    try:
        st = json.loads(raw)
    except ValueError as e:
        return None, None, "状态面不可解析（坏 JSON）：%s（%s）" % (path, e)
    if not isinstance(st, dict):
        return None, None, "状态面结构不可识别（非对象）：%s" % path
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError as e:
        return st, None, "状态面 stat 失败：%s" % e
    return st, age, None


def build_state(verdict, counts, endpoint, allow_mes_idle, verdict_no_exempt=None):
    """run 模式 → 状态面 dict（纯函数；selftest 用它钉字段契约）。"""
    st = {
        "ts": now_str(),
        "ts_epoch": int(time.time()),
        "status": verdict["status"],
        "failed_rules": verdict["failed_rules"],
        "counts": verdict["counts"],
        "window_min": verdict["window_min"],
        "min_otel": verdict["min_otel"],
        "allow_mes_idle": bool(allow_mes_idle),
        "rules": verdict["rules"],
        "ch_now": counts.get("ch_now"),
        "endpoint": endpoint,
        "otel_last_write": counts.get("otel_last", {}),
        # 2026-11-03 新增：近 7 天各服务写入条数（R6「持续 vs 按需发射面」分档的数据源，
        # 落状态面供复核看「为何判红/判 warn」——不落则状态面看不出分档依据）
        "otel_write_counts": counts.get("otel_write_counts", {}),
    }
    # 豁免档透明度：调度档用了 --allow-mes-idle 时，另记「不豁免」的判定（R3 原判），
    # 使状态面仍能看出事件 lane 是否静默（MES 零新增而 OTel 在写）——不因豁免而丢信息。
    if verdict_no_exempt is not None:
        st["status_without_mes_idle_exempt"] = verdict_no_exempt["status"]
        st["failed_rules_without_mes_idle_exempt"] = verdict_no_exempt["failed_rules"]
    return st


def judge_state(state, age_s, max_age_s=MAX_AGE_S):
    """状态面 → (rc, 文案)。纯函数（selftest 钉语义映射）。

    rc：0=绿 / 1=红（对账红 或 读数过期=巡检停摆死手）/ 2=不可证（缺件/坏 JSON/执行错）。
    口径：不可证不猜绿；读数过期判红（巡检本身停摆 = 本次事故形态「静默无人见」）。"""
    if age_s is None:
        return 2, "FAIL OTel lane 对账状态面读数无年龄（stat 失败）——不可证，不猜绿"
    if age_s > max_age_s:
        return 1, ("FAIL OTel lane 对账实查读数过期：state_age=%.0fs > 阈 %ds——"
                   "巡检本身停摆（死手），OTel lane 静默将再次无人见；末次 ts=%s 判定=%s%s"
                   % (age_s, max_age_s, state.get("ts"), state.get("status"),
                      ("（失败规则 " + ",".join(state.get("failed_rules") or []) + "）")
                      if state.get("failed_rules") else ""))
    status = state.get("status")
    if status == "error":
        return 2, ("FAIL OTel lane 对账实查执行错：末次判定不可证（%s）——不猜绿；"
                   "处置=看 状态观测/otel-reconcile.log 与 CH 可达性"
                   % (state.get("error") or "原因未记"))
    if status == "red":
        return 1, ("FAIL OTel lane 对账实查红：末次判定=red（失败规则 %s）——MES 在写而 "
                   "OTel 零行(R1)/行数不足(R2)/事件 lane 静默(R3)/发射面末笔超阈(R6)或未来戳"
                   "(R5)；末次 ts=%s，MES=%s OTel=%s"
                   % (",".join(state.get("failed_rules") or []) or "?",
                      state.get("ts"),
                      (state.get("counts") or {}).get("mes_rows"),
                      (state.get("counts") or {}).get("otel_rows")))
    if status not in ("pass", "warn"):
        return 2, ("FAIL OTel lane 对账状态面判定不可识别：status=%r——不可证，不猜绿"
                   % (status,))
    note = ""
    if status == "warn":
        note = ("（WARN 不挡门：失败规则 " + ",".join(state.get("failed_rules") or []) + "）")
    return 0, ("PASS OTel lane 对账实查：末次判定=%s%s；state_age=%.0fs ≤ 阈 %ds；"
               "末次 ts=%s，MES=%s OTel=%s"
               % (status, note, age_s, max_age_s, state.get("ts"),
                  (state.get("counts") or {}).get("mes_rows"),
                  (state.get("counts") or {}).get("otel_rows")))


# ---------------------------------------------------------------- 报警面（运维可见）
def append_alarm(state, prev, path=None):
    """判定 red → 追加 状态观测/alarms.log（红牌）。同一 red 事件不重复刷屏。

    格式与 factory-keepalive 的 mes-ch 报警同构：ts/level/code/message/since。
    since=本次 red 事件的起点（承接上一轮 red 状态面的 ts），非每轮重置。"""
    path = path or ALARMS_LOG
    if state.get("status") != "red":
        return False
    rules = list(state.get("failed_rules") or [])
    if prev and prev.get("status") == "red" and \
            list(prev.get("failed_rules") or []) == rules:
        return False                       # 已在报：同一 red 事件不重复写
    since = state.get("ts")
    if prev and prev.get("status") == "red" and prev.get("ts"):
        since = prev.get("ts")
    counts = state.get("counts") or {}
    rec = {
        "ts": state.get("ts"),
        "level": "red",
        "code": ALARM_CODE,
        "message": ("OTel lane 对账实查红（失败规则 %s）：MES=%s OTel=%s —— "
                    "观测 lane 静默/半活/事件 lane 静默/发射面超阈；"
                    "处置=跑 tools/otel/ch-mes-reconcile.py --json 看逐条规则明细，"
                    "查 sidecar/collector 与 otel 库入库链"
                    % (",".join(rules) or "?", counts.get("mes_rows"),
                       counts.get("otel_rows"))),
        "since": since,
    }
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


# ---------------------------------------------------------------- 模式
def cmd_run(args):
    """跑实查 → 落状态面 → 红则报警。退出码 0=绿/1=红/2=执行错。"""
    prev, _, _ = read_state(args.state)
    try:
        mod = load_reconcile()
    except Exception as e:  # noqa: BLE001
        st = {"ts": now_str(), "ts_epoch": int(time.time()), "status": "error",
              "failed_rules": [], "counts": {}, "error": "判据源导入失败：%s: %s"
              % (type(e).__name__, e)}
        write_state(st, args.state)
        print("FAIL 判据源导入失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    try:
        counts = mod.fetch_counts(args.window, args.skew, args.mes_kind, args.mes_station)
    except Exception as e:  # noqa: BLE001  CH 不可达等：执行错，不猜绿
        st = {"ts": now_str(), "ts_epoch": int(time.time()), "status": "error",
              "failed_rules": [], "counts": {},
              "error": "实查执行错（CH 不可达/查询失败）：%s: %s" % (type(e).__name__, e)}
        write_state(st, args.state)
        print("FAIL 对账实查执行错（不猜绿）：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    stale = {s: age / 3600.0 for s, age in (counts.get("otel_last") or {}).items()}
    kw = dict(window_min=args.window, min_otel=args.min_otel,
              allow_mes_idle=args.allow_mes_idle, strict_future=args.strict_future,
              idle_red=args.idle_red, stale_hours=stale,
              stale_after_h=args.stale_hours, strict_stale=args.strict_stale,
              write_counts=counts.get("otel_write_counts"))
    v = mod.reconcile(counts["mes_rows"], counts["otel_rows"], counts["future_rows"], **kw)
    v_noex = None
    if args.allow_mes_idle:
        kw2 = dict(kw)
        kw2["allow_mes_idle"] = False
        v_noex = mod.reconcile(counts["mes_rows"], counts["otel_rows"],
                               counts["future_rows"], **kw2)
    try:
        endpoint = mod.ch_client.resolve()[0]
    except Exception:  # noqa: BLE001  端点解析失败不掩盖判定
        endpoint = "(端点解析失败)"
    state = build_state(v, counts, endpoint, args.allow_mes_idle, v_noex)
    write_state(state, args.state)
    alarmed = append_alarm(state, prev, args.alarms)
    c = state["counts"]
    print("[%s] OTel 对账实查 status=%s MES=%s OTel=%s 未来戳=%s 失败规则=%s%s"
          % (state["ts"], state["status"], c.get("mes_rows"), c.get("otel_rows"),
             c.get("future_rows"), ",".join(state["failed_rules"]) or "无",
             "｜已写 alarms.log 红牌" if alarmed else ""))
    for r in v["rules"]:
        if not r["ok"]:
            print("  %s %s %s" % (r["rule"], r["severity"].upper(), r["detail"]))
    return 1 if v["status"] == "red" else 0


def check_state_file(path=None, max_age_s=MAX_AGE_S):
    """状态面文件 → (rc, 文案)（门消费面核心；只读文件、零网络）。

    rc：0=绿 / 1=红（对账红 或 读数过期=巡检停摆死手）/ 2=不可证（缺件/坏 JSON/执行错）。"""
    st, age, err = read_state(path)
    if st is None:
        return 2, ("FAIL OTel lane 对账状态面缺件/不可用：%s——摘门必须显式红，不静默放行"
                   % (err or "未知原因"))
    if err and age is None:
        return 2, "FAIL OTel lane 对账状态面不可证：%s" % err
    return judge_state(st, age, max_age_s)


def cmd_check(args):
    """消费状态面（门姿势，零网络）。退出码 0=绿/1=红/2=不可证。"""
    rc, msg = check_state_file(args.state, args.max_age)
    print(msg)
    return rc


def selftest():
    """夹具自证：消费语义映射 + 状态面字段契约。零网络零库。"""
    cases = [
        # (state, age_s, expect_rc, 场景)
        ({"status": "pass", "ts": "2026-11-02 10:00:00", "counts": {"mes_rows": 30,
          "otel_rows": 500}, "failed_rules": []}, 10, 0, "绿路（对照）"),
        ({"status": "warn", "ts": "2026-11-02 10:00:00", "counts": {"mes_rows": 30,
          "otel_rows": 500}, "failed_rules": ["R5"]}, 10, 0, "WARN 不挡门"),
        ({"status": "red", "ts": "2026-11-02 10:00:00", "counts": {"mes_rows": 34,
          "otel_rows": 0}, "failed_rules": ["R1"]}, 10, 1, "R1 红（OTel lane 静默）"),
        ({"status": "red", "ts": "2026-11-02 10:00:00", "counts": {"mes_rows": 5,
          "otel_rows": 3}, "failed_rules": ["R2"]}, 10, 1, "R2 红（边车半活）"),
        ({"status": "red", "ts": "2026-11-03 10:00:00", "counts": {"mes_rows": 0,
          "otel_rows": 0}, "failed_rules": ["R4"]}, 10, 1,
         "R4 红（MES 空闲+OTel 整链静默；2026-11-03 堵「停工期静默无人见」形态）"),
        ({"status": "error", "ts": "2026-11-02 10:00:00", "counts": {},
          "error": "CH 不可达"}, 10, 2, "执行错=不可证（不猜绿）"),
        ({"status": "pass", "ts": "2026-11-02 09:00:00", "counts": {"mes_rows": 30,
          "otel_rows": 500}, "failed_rules": []}, 5000, 1, "读数过期=巡检停摆（死手红）"),
        ({"status": "pass", "ts": "2026-11-02 09:00:00", "counts": {"mes_rows": 30,
          "otel_rows": 500}, "failed_rules": []}, None, 2, "年龄不可得=不可证"),
        ({"status": "???", "ts": "2026-11-02 10:00:00", "counts": {}}, 10, 2,
         "判定不可识别=不可证"),
    ]
    fails = []
    for i, (st, age, exp, why) in enumerate(cases):
        rc, msg = judge_state(st, age)
        ok = rc == exp
        print("  case%d: %s → rc=%d（期望 %d）%s" % (i, why, rc, exp,
                                                    "PASS" if ok else "FAIL"))
        if not ok:
            fails.append((i, rc, exp))
    # 状态面字段契约（run 模式产出必须含消费面所需键）
    verdict = {"status": "pass", "failed_rules": [], "counts": {"mes_rows": 1,
               "otel_rows": 2, "future_rows": 0}, "window_min": 15, "min_otel": 10,
               "rules": [{"rule": "R1", "severity": "red", "ok": True, "detail": "x"}]}
    st = build_state(verdict, {"ch_now": "2026-11-02 10:00:00", "otel_last": {"s": 1}},
                     "http://example:1", True,
                     {"status": "red", "failed_rules": ["R3"]})
    need = ["ts", "status", "failed_rules", "counts", "rules", "endpoint",
            "otel_last_write", "otel_write_counts", "allow_mes_idle",
            "status_without_mes_idle_exempt"]
    miss = [k for k in need if k not in st]
    print("  state: 状态面字段契约（%d 键）%s" % (len(need), "PASS" if not miss else "FAIL"))
    if miss:
        fails.append(("state-contract", miss))
    # 绿路对照：消费面在「绿态」不得红（防门被改成恒红也能过）
    rc, _ = judge_state({"status": "pass", "counts": {}}, 5)
    print("  control: 绿态消费 rc=%d（期望 0）%s" % (rc, "PASS" if rc == 0 else "FAIL"))
    if rc != 0:
        fails.append(("control", rc, 0))
    # 文件级路径（临时目录，零污染真树）：缺件 / 坏 JSON / 红态文件 / 过期文件
    import tempfile
    with tempfile.TemporaryDirectory(prefix="otel-reconcile-selftest-") as td:
        badp = os.path.join(td, "bad.json")
        redp = os.path.join(td, "red.json")
        greenp = os.path.join(td, "green.json")
        oldp = os.path.join(td, "old.json")
        missp = os.path.join(td, "missing.json")
        with open(badp, "w", encoding="utf-8") as f:
            f.write("{not json")
        with open(redp, "w", encoding="utf-8") as f:
            json.dump({"status": "red", "ts": "2026-11-02 10:00:00",
                       "failed_rules": ["R1"],
                       "counts": {"mes_rows": 34, "otel_rows": 0}}, f)
        with open(greenp, "w", encoding="utf-8") as f:
            json.dump({"status": "pass", "ts": "2026-11-02 10:00:00",
                       "failed_rules": [],
                       "counts": {"mes_rows": 30, "otel_rows": 500}}, f)
        with open(oldp, "w", encoding="utf-8") as f:
            json.dump({"status": "pass", "ts": "2026-11-02 10:00:00",
                       "failed_rules": [],
                       "counts": {"mes_rows": 30, "otel_rows": 500}}, f)
        old_ts = time.time() - 5000
        os.utime(oldp, (old_ts, old_ts))
        file_cases = [
            (missp, 2, "状态面缺件=红（不静默放行）"),
            (badp, 2, "坏 JSON=不可证红"),
            (redp, 1, "红态文件=红"),
            (greenp, 0, "绿态文件=绿"),
            (oldp, 1, "过期文件=死手红"),
        ]
        for path, exp, why in file_cases:
            rc, _ = check_state_file(path)
            ok = rc == exp
            print("  file: %s → rc=%d（期望 %d）%s" % (why, rc, exp,
                                                       "PASS" if ok else "FAIL"))
            if not ok:
                fails.append(("file:" + why, rc, exp))
    if fails:
        print("SELFTEST FAIL: %d 项" % len(fails))
        return 1
    print("SELFTEST PASS: %d 语义用例 + 5 文件级用例 + 1 条状态面契约断言 + 1 条绿路对照"
          % len(cases))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="OTel lane 对账实查的机器消费者（跑/消费/夹具）")
    p.add_argument("--run", action="store_true", help="跑实查并落状态面（调度器姿势）")
    p.add_argument("--check", action="store_true", help="消费状态面（门姿势，零网络）")
    p.add_argument("--selftest", action="store_true", help="夹具自证（零网络，进 all-gates L3）")
    p.add_argument("--window", type=int, default=15, help="对账时间窗（分钟，默认 15）")
    p.add_argument("--skew", type=int, default=5, help="未来戳容忍（分钟，默认 5）")
    p.add_argument("--min-otel", type=int, default=10, help="OTel 本窗最少行数阈值（默认 10）")
    p.add_argument("--mes-kind", help="MES 侧只看某 kind")
    p.add_argument("--mes-station", help="MES 侧只看某 station_id")
    p.add_argument("--allow-mes-idle", action="store_true",
                   help="豁免 R3（工厂停工时 MES 静默不算红；调度档默认用此档，"
                        "R1/R2/R5/R6 不豁免）")
    p.add_argument("--strict-future", action=argparse.BooleanOptionalAction, default=True,
                   help="R5 未来戳行记红挡门（2026-11-03 起默认 True，透传判据源；"
                        "cron 档未传参即红档——wo-live-smoke 2027 未来账事故的堵法）")
    p.add_argument("--stale-hours", type=float, default=24.0, help="R6 新鲜度阈值（小时，默认 24）")
    p.add_argument("--strict-stale", action="store_true", help="R6 超阈记红")
    p.add_argument("--idle", choices=("pass", "red"), default="pass", help="双零空闲处置")
    p.add_argument("--max-age", type=int, default=MAX_AGE_S,
                   help="check 模式读数可信上界（秒，默认 1800=2 倍调度周期）")
    p.add_argument("--state", help="状态面路径（默认 状态观测/otel-reconcile.json；夹具回归用）")
    p.add_argument("--alarms", help="报警面路径（默认 状态观测/alarms.log；夹具回归用）")
    args = p.parse_args(argv)
    args.idle_red = args.idle == "red"
    modes = [bool(args.run), bool(args.check), bool(args.selftest)]
    if sum(modes) > 1:
        print("用法：--run / --check / --selftest 三选一", file=sys.stderr)
        return 2
    if args.selftest:
        return selftest()
    if args.check:
        return cmd_check(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
