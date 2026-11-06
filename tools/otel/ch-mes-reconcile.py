#!/usr/bin/env python3
"""ch-mes-reconcile.py — CH 写入对账门（红队 C5 次项，2026-10-29 义务收口批）

C5 教训：MES/CH 写入无闭环——每笔写入必须有对账断言。本门对两条 lane 在**同一时间窗**
内的新增行数做对账，任一 lane 静默/掉线即红（不靠 grep 函数名，真查库真比数）：

  OTel 侧（真值源 otel 库）  ：otel.otel_metrics_gauge + otel_metrics_sum 中
                               ServiceName IN OTEL_SERVICES 的指标行数；R6 另查三表
                               （traces/sum/gauge）各服务末笔写入做新鲜度对账
  MES/事件侧（真值源 af_mes）：af_mes.mes_event 本窗新增事件数（--mes-kind/--mes-station
                               可收窄到某一批，如门户 sandbox_claim/sandbox_report）

断言规则（阈值+时间窗，异常红）：
  R1  MES 有新增而 OTel 零行                      → 红（观测 lane 静默，写入只进了一半）
  R2  MES 有新增而 OTel 行数 < --min-otel         → 红（阈值不足，边车半活）
  R3  OTel 有行而 MES 零新增                      → 红（事件 lane 静默；--allow-mes-idle 豁免）
  R4  双零                                        → 区分「真空闲」与「整链静默」：MES 空闲是
      正常的（停工期），但 OTel 发射面有 30s 心跳（emit-sidecar OTEL_SIDECAR_INTERVAL
      默认 30），本窗内「无任何已知发射服务写入」= 链没在写 → 整链静默 → 红
      （2026-11-03 修：原「双零=空闲默认 PASS」使「MES 空闲 + OTel 整链死」整链静默
      无人见——R1/R2 以 mes_rows>0 为前提、R3 被 --allow-mes-idle 豁免、R6 默认 WARN
      不挡门，四洞叠加 → 门消费 rc=0 绿）；链本窗仍在写 → 真空闲 → PASS 带注；
      --idle red 仍可把双零无条件改红
  R5  occurred_at 超上界 + --skew 的未来戳行      → 默认红（挡门），--no-strict-future 降回 WARN
       （2026-11-03 修：确证发现——wo-live-smoke 7 行戳在 2027-01-15 且已聚合进
       mes_line_hour 未来桶，而 R5 默认 WARN 不挡门、cron 档未开 --strict-future、
       judge_state 对 warn 记 rc=0 绿，三层叠加=「无任何门/告警能发现」。该批残行当日
       ALTER DELETE 清账（mes_event 7 行 + mes_line_hour 2027 桶），写源头 mes_live.rs
       改戳随钟走；WARN 的「现网常态」前提不复存在——未来戳行=账目不符，默认记红）
  R6  OTel 某服务末笔写入 > --stale-hours（默认 24h）→ 严重度分档（2026-11-03 修）：
      持续发射面（近期一直在写）超阈未写 = 「从活变死」→ 红（挡门）；按需发射面
      （本就稀疏，如 otel-e2e-check 按需跑）→ 仍 WARN（不挡门），防常态误红恒红。
      2026-11-02 RT 批修新增：此前第三发射服务 sandbox-harvester
      漏在对账集外，末笔 2026-10-31 12:36:56 后静默 42h+ 无任何机制可见——R1-R5 全绿
      （sidecar 30s 心跳把 OTel 计数撑着）。R6 按「曾经发射过、现在超阈没写」判，
      从未发射的服务（如 factory-scheduler/keepalive，AF_OTEL_ENDPOINT 未挂）只注不判。
      「持续 vs 按需」由数据判定（近 7 天写入条数 ≥ 100），不手钉服务名单——手钉名单
      会随代码漂移（RT-E116 即因此漏过第三发射面）。

时间窗双侧界定（时区坑，现网实证）：af_mes.mes_event.occurred_at 是 DateTime64(3,'UTC')，
但 Python 侧写手（factory-keepalive/factory-sched）写的是**本地墙钟串**（pandev=CST，
落库即 +8h 即时），而 order-cli/af-mes RowBinary 写真 UTC 即时——混记。单侧窗口
`> now() - N` 会把未来戳行永久算进"本窗"，故本门一律双边界定 [now-N, now+skew]，
超上界的行单列 R5 处置，不静默混入。

零明文：凭据只走 tools/otel/ch_client 既有链（0600 文件/env），本件不接触口令；
输出只含端点与库名。--selftest 全夹具零网络（不进 all-gates 打真库）。

用法：
  tools/otel/ch-mes-reconcile.py                  # 实查对账（exit 0=绿 1=红 2=执行错）
  tools/otel/ch-mes-reconcile.py --window 30 --min-otel 50
  tools/otel/ch-mes-reconcile.py --mes-kind sandbox_claim --json
  tools/otel/ch-mes-reconcile.py --strict-stale   # R6 新鲜度超阈一律记红（默认仅持续发射面记红）
  tools/otel/ch-mes-reconcile.py --selftest       # 夹具矩阵自证（进 all-gates L3）
"""
import argparse
import inspect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ch_client  # noqa: E402  凭据解析单一真源（0600 文件/env；口令零明文）

# 2026-11-02 RT 批修：钉死集此前只有 ('otel-sidecar','otel-e2e-check') 两个字面，
# 第三发射服务 sandbox-harvester（factory_otel.harvest_report 默认 service，真库实存
# 12+12 行）漏在集外，静默 42h+ 无机制可见。现扩为**代码面全部已知发射者**：
# selftest 断言本集 == known_emitter_services()（发射面代码推导全集）——今后新发射者
# 接入而漏更本集，selftest 即红，「钉死集」不许再静默落后于发射面代码。
OTEL_SERVICES = ("otel-sidecar", "otel-e2e-check", "sandbox-harvester",
                 "factory-scheduler", "factory-keepalive")
DEFAULT_WINDOW_MIN = 15
DEFAULT_SKEW_MIN = 5
DEFAULT_MIN_OTEL = 10
DEFAULT_STALE_HOURS = 24.0
# 「持续发射面」判定的数据口径（2026-11-03 新增）：近 CONTINUOUS_LOOKBACK_DAYS 天写入
# 条数 ≥ CONTINUOUS_MIN_WRITES 者视为持续发射面（近期一直在写），其超阈未写即
# 「从活变死」→ R6 记红挡门；写入稀疏者（如 otel-e2e-check 按需跑）按需档 WARN 不挡门。
# 现网实测（2026-11-03 01:0x 亲跑 CH 三表并集计数）：otel-sidecar 108537 / factory-keepalive
# 6570 / factory-scheduler 4047 / sandbox-harvester 2772（持续）vs otel-e2e-check 39
# （按需）——阈 100 落在两侧的宽裕中位（39 与 2772 之间），不贴边。
CONTINUOUS_LOOKBACK_DAYS = 7
CONTINUOUS_MIN_WRITES = 100


def known_emitter_services() -> set:
    """代码面已声明的 OTel 发射者全集（零网络：只读本仓源码与函数签名，零库查询）。
    真源三处：①factory_otel 三 helper 的 service 默认值；②emit-sidecar.py SERVICE 常量
    （该件是常驻脚本，只正则读源不 import）；③otel-e2e-check.py resource(service=…) 字面。
    本函数与 OTEL_SERVICES 的等价性由 selftest 断言——发射面新增/改名而集未跟，即红。"""
    svcs = set()
    import factory_otel  # noqa: E401  import 无副作用（发射仅在 helper 调用且端点在时发生）
    for fn in (factory_otel.order_round, factory_otel.guardian_round,
               factory_otel.harvest_report):
        svcs.add(inspect.signature(fn).parameters["service"].default)
    here = os.path.dirname(os.path.abspath(__file__))
    m = re.search(r'^SERVICE\s*=\s*"([^"]+)"',
                  open(os.path.join(here, "emit-sidecar.py"), encoding="utf-8").read(), re.M)
    if m:
        svcs.add(m.group(1))
    e2e = open(os.path.join(here, "..", "otel-e2e-check.py"), encoding="utf-8").read()
    for m in re.finditer(r'resource\(service="([^"]+)"\)', e2e):
        svcs.add(m.group(1))
    return svcs


# ---------------------------------------------------------------- 查询（真值源）
def _in_list(values):
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def mes_count_sql(window_min, skew_min, kind=None, station=None, upper_only=False):
    """MES 侧计数 SQL。双侧窗口 [now-window, now+skew]；upper_only=仅未来戳桶。"""
    conds = []
    if upper_only:
        conds.append(f"occurred_at > now() + INTERVAL {skew_min} MINUTE")
    else:
        conds.append(f"occurred_at > now() - INTERVAL {window_min} MINUTE")
        conds.append(f"occurred_at <= now() + INTERVAL {skew_min} MINUTE")
    if kind:
        conds.append(f"kind = '{kind}'")
    if station:
        conds.append(f"station_id = '{station}'")
    return f"SELECT count() AS n FROM af_mes.mes_event WHERE {' AND '.join(conds)}"


def otel_count_sql(window_min, skew_min):
    """OTel 侧计数 SQL：gauge+sum 两表、OTEL_SERVICES 全集、同一双侧窗口。"""
    w = f"TimeUnix > now() - INTERVAL {window_min} MINUTE AND TimeUnix <= now() + INTERVAL {skew_min} MINUTE"
    svc = f"ServiceName IN ({_in_list(OTEL_SERVICES)})"
    return (f"SELECT (SELECT count() FROM otel.otel_metrics_gauge WHERE {w} AND {svc}) "
            f"+ (SELECT count() FROM otel.otel_metrics_sum WHERE {w} AND {svc}) AS n")


def _otel_from(tbl: str) -> str:
    """otel 库表 FROM 子句（U-6 去重腿：2026-11-05 otel_traces 换
    ReplacingMergeTree(Timestamp) ORDER BY (TraceId, SpanId)——合并前重复行仍可见，
    读必须带 FINAL 才是去重后口径；metrics 三表仍 MergeTree，无需 FINAL）。"""
    return f"otel.{tbl} FINAL" if tbl == "otel_traces" else f"otel.{tbl}"


def otel_last_write_sql():
    """R6 新鲜度 SQL：各服务在 traces/sum/gauge 三表的末笔写入距今秒数（dateDiff 对 now）。
    只报「有行」的服务；从未发射的服务不在结果里，由调用方按集差注记。"""
    uni = " UNION ALL ".join(
        f"SELECT ServiceName, max({col}) AS t FROM {_otel_from(tbl)} GROUP BY ServiceName"
        for tbl, col in (("otel_traces", "Timestamp"), ("otel_metrics_sum", "TimeUnix"),
                         ("otel_metrics_gauge", "TimeUnix")))
    return (f"SELECT ServiceName, dateDiff('second', max(t), now()) AS age_s "
            f"FROM ({uni}) GROUP BY ServiceName ORDER BY ServiceName")


def otel_write_count_sql(lookback_days=CONTINUOUS_LOOKBACK_DAYS):
    """近 N 天各服务写入条数（traces/sum/gauge 三表并集）→ 判「持续发射面」用。

    口径：只数写入量（不判成败、不按服务名过滤、不看 span 名）——用于区分「持续发射面」
    （近期一直在写，超阈未写=从活变死）与「按需发射面」（本就稀疏，超阈未写属常态）。
    不手钉服务名单：手钉名单会随代码漂移（RT-E116 即因此漏过第三发射面）。"""
    w = f"t > now() - INTERVAL {lookback_days} DAY"
    uni = " UNION ALL ".join(
        f"SELECT ServiceName, {col} AS t FROM {_otel_from(tbl)}"
        for tbl, col in (("otel_traces", "Timestamp"), ("otel_metrics_sum", "TimeUnix"),
                         ("otel_metrics_gauge", "TimeUnix")))
    return f"SELECT ServiceName, count() AS n FROM ({uni}) WHERE {w} GROUP BY ServiceName"


def fetch_counts(window_min, skew_min, kind=None, station=None):
    """实查两侧计数+各服务末笔 → dict。CH 不可达等异常直接抛（门不猜绿）。"""
    mes = ch_client.query(mes_count_sql(window_min, skew_min, kind, station))[0]["n"]
    otel = ch_client.query(otel_count_sql(window_min, skew_min))[0]["n"]
    future = ch_client.query(mes_count_sql(window_min, skew_min, kind, station, upper_only=True))[0]["n"]
    clock = ch_client.query("SELECT now() AS ch_now FROM system.one")[0]["ch_now"]
    last = ch_client.query(otel_last_write_sql())
    wcounts = ch_client.query(otel_write_count_sql())
    return {"mes_rows": int(mes), "otel_rows": int(otel),
            "future_rows": int(future), "ch_now": clock,
            "otel_last": {r["ServiceName"]: int(r["age_s"]) for r in last},
            "otel_write_counts": {r["ServiceName"]: int(r["n"]) for r in wcounts}}


# ---------------------------------------------------------------- 判据辅助（纯函数）
def chain_silence(stale_hours, window_min):
    """→ (注记, 是否整链静默)。判据源=末笔新鲜度（stale_hours，跨 traces/sum/gauge）。

    「整链静默」= 已知发射面（OTEL_SERVICES）本窗内无任何一个写过。OTel 侧有 30s 心跳
    （emit-sidecar OTEL_SIDECAR_INTERVAL 默认 30），本窗（默认 15min）零写入 = 链没在写。
    stale_hours=None（调用方未给新鲜度数据）→ 不可证 → 不判红也不判绿（只注记）。"""
    if stale_hours is None:
        return "（无末笔新鲜度数据——未判整链静默，不猜红不猜绿）", False
    win_h = window_min / 60.0
    pinned = {s: h for s, h in stale_hours.items() if s in set(OTEL_SERVICES)}
    alive = sorted(s for s, h in pinned.items() if h <= win_h)
    if alive:
        return "（已知发射面本窗仍在写：%s——是真空闲，非整链静默）" % ",".join(alive), False
    if not pinned:
        return "（已知发射面无任何写入记录——观测面不存在，非空闲）", True
    outside = sorted(s for s, h in stale_hours.items()
                     if s not in set(OTEL_SERVICES) and h <= win_h)
    tail = "；集外服务本窗在写：%s（钉死集待核）" % ",".join(outside) if outside else ""
    return ("（已知发射面本窗内无一写入，末笔最旧 %.1fh 前——整链静默%s）"
            % (max(pinned.values()), tail)), True


def is_continuous(service, write_counts, min_writes=CONTINUOUS_MIN_WRITES):
    """该服务是否为「持续发射面」（近期一直在写）→ 其超阈未写即「从活变死」记红。

    判据=数据（近 CONTINUOUS_LOOKBACK_DAYS 天写入条数 ≥ min_writes），不手钉服务名单。
    write_counts=None（调用方未给写入量）→ 不可证 → 按需档（WARN，不挡门），不猜红。"""
    if not write_counts:
        return False
    try:
        return int(write_counts.get(service, 0)) >= min_writes
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 断言（对账引擎）
def reconcile(mes_rows, otel_rows, future_rows=0, window_min=DEFAULT_WINDOW_MIN,
              min_otel=DEFAULT_MIN_OTEL, allow_mes_idle=False, strict_future=True,
              idle_red=False, stale_hours=None, stale_after_h=DEFAULT_STALE_HOURS,
              strict_stale=False, write_counts=None):
    """纯函数对账引擎：计数 → 裁决 dict（status=pass|warn|red + rules 明细带 severity）。
    stale_hours: {service: 距末笔写入小时数}（只含有行的服务）；None=无数据（R6 跳过）。
    write_counts: {service: 近 CONTINUOUS_LOOKBACK_DAYS 天写入条数}；None=无数据
      （R6 严重度分档不可证 → 按需档 WARN，不猜红）。
    strict_future: 未来戳行（occurred_at > now+skew）处置档——2026-11-03 起默认 True
      （记红挡门）；False 仅留给显式降档（--no-strict-future），不得作调度默认。"""
    rules = []

    def rule(rid, severity, ok, detail):
        rules.append({"rule": rid, "severity": severity, "ok": bool(ok), "detail": detail})
        return ok

    if mes_rows > 0 and otel_rows == 0:
        rule("R1", "red", False, f"MES 本窗新增 {mes_rows} 笔而 OTel 零行——观测 lane 静默（写入只进一半）")
    else:
        rule("R1", "red", True, f"MES {mes_rows} / OTel {otel_rows}（R1 不触发）")

    if mes_rows > 0 and 0 < otel_rows < min_otel:
        rule("R2", "red", False, f"OTel 本窗 {otel_rows} 行 < 阈值 {min_otel}——边车半活")
    else:
        rule("R2", "red", True, f"OTel {otel_rows} ≥ 阈值 {min_otel} 或 MES 无新增（R2 不触发）")

    if mes_rows == 0 and otel_rows > 0 and not allow_mes_idle:
        rule("R3", "red", False, f"OTel 本窗 {otel_rows} 行而 MES 零新增——事件 lane 静默（--allow-mes-idle 可豁免）")
    else:
        rule("R3", "red", True, f"MES {mes_rows} / OTel {otel_rows}（R3 不触发）")

    if mes_rows == 0 and otel_rows == 0:
        # 双零：区分「真空闲」与「整链静默（死）」。MES 侧空闲是正常的（停工期），
        # 但 OTel 发射面有 30s 心跳（emit-sidecar OTEL_SIDECAR_INTERVAL 默认 30），
        # 本窗内无任何已知发射服务写入 = 链没在写 → 这不是空闲，是整链死。
        # 2026-11-03 修：原「双零默认记 PASS」使「MES 空闲 + OTel 整链静默」这一
        # RT-E116「静默无人见」事故形态在停工期复现（R1/R2 要 mes_rows>0、R3 被
        # --allow-mes-idle 豁免、R6 默认 WARN 不挡门 → 门消费 rc=0 绿）。
        chain_note, chain_dead = chain_silence(stale_hours, window_min)
        if idle_red:
            rule("R4", "red", False,
                 "双 lane 本窗均无新增（空闲或双挂）；--idle red 已置红" + chain_note)
        elif chain_dead:
            rule("R4", "red", False,
                 "双 lane 本窗均无新增，且 OTel 整链静默——不是空闲，是整链死"
                 "（静默无人见）" + chain_note)
        else:
            rule("R4", "pass", True,
                 "双 lane 本窗均无新增（OTel 发射面本窗仍在写→真空闲）" + chain_note)
    else:
        rule("R4", "red", True, "至少一侧有新增（R4 不触发）")

    if future_rows > 0:
        rule("R5", "red" if strict_future else "warn", False,
             f"occurred_at 超上界 +skew 的未来戳行 {future_rows} 条（时区混记/冒烟残行；"
             + ("默认红挡门（账目不符：mes_event 记账面混入未来账，SummingMergeTree "
                "小时账聚合将永久携带该桶）" if strict_future
                else "--no-strict-future 显式降档 WARN 不挡门"))
    else:
        rule("R5", "red", True, "无未来戳行（R5 不触发）")

    # R6 发射面新鲜度（2026-11-02 RT 批修）：某服务「曾经发射过」而末笔超阈 → 可见。
    # 按 OTEL_SERVICES 全集比对，集差（从未发射/无行）只注不判——不把「未挂端点的
    # 发射面」误判成故障，只盯「从活变死」。
    if stale_hours is None:
        rule("R6", "red", True, "无末笔新鲜度数据（R6 跳过）")
    else:
        stale = sorted((s, h) for s, h in stale_hours.items() if h > stale_after_h)
        absent = sorted(s for s in OTEL_SERVICES if s not in stale_hours)
        note = (f"（从未发射/无行: {','.join(absent)}）" if absent else "")
        if stale:
            # 严重度分档（2026-11-03 修）：R6 是唯一能抓「从活变死」的规则，原默认 WARN
            # 不挡门 → 「某发射面静默 25h」这类事故形态门消费 rc=0 绿（RT-E91 台账
            # 自述的「超阈红」从未在调度面落地）。现按「该服务近 7 天是否一直在写」
            # 分档：持续发射面超阈未写 = 从活变死 → 红（挡门）；按需发射面（本就稀疏，
            # 如 otel-e2e-check 按需跑）→ 仍 WARN 不挡门（防常态误红恒红）。
            cont = [s for s, _ in stale if is_continuous(s, write_counts)]
            cont_set = set(cont)
            known = write_counts is not None

            def _tag(s):
                if s in cont_set:
                    return "（持续发射面）"
                if not known:
                    return "（写入量未知）"
                if s in write_counts:
                    return "（按需发射面）"
                return "（写入量无记录）"

            det = "；".join("%s 末笔 %.1fh 前%s" % (s, h, _tag(s))
                            for s, h in stale)
            reasons = []
            if strict_stale:
                reasons.append("--strict-stale 已置红")
            if cont:
                reasons.append("持续发射面超阈未写=从活变死，已置红")
            if not reasons:
                reasons.append("按需发射面（本就稀疏）→ 默认 WARN 不挡门")
            rule("R6", "red" if (strict_stale or cont) else "warn", False,
                 f"OTel 发射面新鲜度超阈（>{stale_after_h:.0f}h）：{det}"
                 + "；" + "；".join(reasons)
                 + ("；" + note if note else ""))
        else:
            top = max(stale_hours.values()) if stale_hours else 0.0
            rule("R6", "red", True,
                 f"发射面末笔均新鲜（最旧 {top:.2f}h ≤ {stale_after_h:.0f}h 阈）" + note)

    failed = [r for r in rules if not r["ok"]]
    if any(r["severity"] == "red" for r in failed):
        status = "red"
    elif failed:
        status = "warn"
    else:
        status = "pass"
    return {"status": status,
            "window_min": window_min,
            "counts": {"mes_rows": mes_rows, "otel_rows": otel_rows, "future_rows": future_rows},
            "min_otel": min_otel,
            "failed_rules": [r["rule"] for r in failed],
            "rules": rules}


# ---------------------------------------------------------------- selftest（夹具矩阵）
def selftest():
    """夹具矩阵自证：每条用例断言期望状态；零网络零库写入。"""
    cases = [
        # (mes, otel, future, kwargs, expect_status, expect_rule)
        (34, 0, 0, {}, "red", "R1"),                    # MES 在写、OTel 静默（现网即此状）
        (5, 3, 0, {}, "red", "R2"),                     # OTel 行数不足阈值
        (0, 312, 0, {}, "red", "R3"),                   # OTel 在写、MES 静默
        (0, 312, 0, {"allow_mes_idle": True}, "pass", None),
        (0, 0, 0, {}, "pass", None),                    # 双零=空闲（默认不挡门）
        (0, 0, 0, {"idle_red": True}, "red", "R4"),     # --idle red
        (5, 312, 0, {}, "pass", None),                  # 双 lane 健康
        (5, 312, 7, {}, "red", "R5"),                   # 未来戳行默认红（2026-11-03 修：原默认 WARN 不挡门→无人见）
        (5, 312, 7, {"strict_future": False}, "warn", "R5"),  # --no-strict-future 显式降档 WARN（降档路径钉防）
        (5, 312, 7, {"min_otel": 500}, "red", "R2"),    # 阈值可调
        # R6 新鲜度（2026-11-02 RT 批修）：harvester 静默 42h 即本轮事故形状——
        # R1-R5 全绿（sidecar 心跳撑计数）而 R6 WARN 可见；strict 记红；无行不判死。
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "otel-e2e-check": 42.0,
                                     "sandbox-harvester": 42.0}}, "warn", "R6"),
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "otel-e2e-check": 42.0,
                                     "sandbox-harvester": 42.0},
                     "strict_stale": True}, "red", "R6"),
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "otel-e2e-check": 3.0,
                                     "sandbox-harvester": 2.0}}, "pass", None),
        (0, 0, 0, {"stale_hours": {"otel-sidecar": 0.01}}, "pass", None),  # 其余服务无行=未发射，只注不判
        (34, 0, 0, {"stale_hours": {"otel-sidecar": 0.01, "sandbox-harvester": 42.0}},
         "red", "R1"),                                  # R1 优先于 R6（红压 warn）
        # ── 2026-11-03 补：R4 双零区分「真空闲 vs 整链静默」（停工期「静默无人见」堵法）
        (0, 0, 0, {"stale_hours": {"otel-sidecar": 25.0}}, "red", "R4"),
        #   MES 空闲 + OTel 整链静默（末笔 25h 前）→ 红（修前：R4 记 PASS → 门消费 rc=0 绿）
        (0, 0, 0, {"stale_hours": {"otel-sidecar": 0.5}}, "red", "R4"),
        #   末笔 30min 前 > 窗宽 15min → 整链静默 → 红（边车 30s 心跳，停 30min 即死）
        (0, 0, 0, {"stale_hours": {}}, "red", "R4"),
        #   观测面从未存在（无任何写入）→ 红（反真空绿：老「双零=空闲 PASS」即真空绿）
        (0, 0, 0, {"stale_hours": {"otel-sidecar": 25.0},
                    "write_counts": {"otel-sidecar": 108537}}, "red", "R4"),
        #   双零 + 整链静默 + 持续发射面 → 红
        (0, 494, 0, {"allow_mes_idle": True,
                     "stale_hours": {"otel-sidecar": 0.01, "factory-scheduler": 0.02}},
         "pass", None),
        #   MES 空闲但 OTel 在流（链活）→ 非双零 → R4 不触发，真空闲不误红
        # ── 2026-11-03 补：R6 严重度分档（持续发射面超阈未写 = 从活变死 → 红挡门）
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "sandbox-harvester": 42.0},
                     "write_counts": {"otel-sidecar": 39566,
                                      "sandbox-harvester": 2772}}, "red", "R6"),
        #   sandbox-harvester 近 7 天 2772 条（持续发射面）而末笔 42h 未写 → 红（挡门）
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "otel-e2e-check": 30.0},
                     "write_counts": {"otel-sidecar": 39566,
                                      "otel-e2e-check": 39}}, "warn", "R6"),
        #   otel-e2e-check 近 7 天仅 39 条（按需发射面）→ 仍 WARN 不挡门（防常态误红恒红）
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "sandbox-harvester": 42.0},
                     "write_counts": {"sandbox-harvester": 2772},
                     "strict_stale": True}, "red", "R6"),
        #   --strict-stale 对按需发射面亦记红（既有语义不弱化）
        (5, 312, 0, {"stale_hours": {"otel-sidecar": 0.01, "sandbox-harvester": 42.0},
                     "write_counts": {"otel-sidecar": 39566}}, "warn", "R6"),
        #   写入量里查无该服务（不可证其为持续发射面）→ 按需档 WARN，不猜红
    ]
    fails = []
    for i, (mes, otel, fut, kw, expect, erule) in enumerate(cases):
        v = reconcile(mes, otel, fut, **kw)
        ok = v["status"] == expect and (erule is None or erule in v["failed_rules"])
        print(f"  case{i}: mes={mes} otel={otel} future={fut} {kw} → {v['status']}"
              f"（期望 {expect}/{erule or '-'}）{'PASS' if ok else 'FAIL'}")
        if not ok:
            fails.append((i, v["status"], expect))
    # SQL 回归断言：窗口必须双侧界定（时区坑防回归）；服务集必须=发射面代码全集
    # （2026-11-02 RT 批修：旧断言只查「钉死字面仍在 SQL」，sandbox-harvester 漏集
    # 照样绿——改为与 known_emitter_services() 全等，发射面新增而集未跟即红）。
    msql = mes_count_sql(15, 5)
    osql = otel_count_sql(15, 5)
    lsql = otel_last_write_sql()
    wsql = otel_write_count_sql()
    derived = known_emitter_services()
    sql_checks = [
        ("MES 下界", "occurred_at > now() - INTERVAL 15 MINUTE" in msql),
        ("MES 上界", "occurred_at <= now() + INTERVAL 5 MINUTE" in msql),
        ("OTel 下界", "TimeUnix > now() - INTERVAL 15 MINUTE" in osql),
        ("OTel 上界", "TimeUnix <= now() + INTERVAL 5 MINUTE" in osql),
        ("服务集=现役发射面全集", derived == set(OTEL_SERVICES)),
        ("harvester 在对账集（RT 批修事故钉防）", "sandbox-harvester" in set(OTEL_SERVICES)
         and "'sandbox-harvester'" in osql),
        ("gauge+sum 双表", "otel_metrics_gauge" in osql and "otel_metrics_sum" in osql),
        ("kind 过滤可加", "kind = 'sandbox_claim'" in mes_count_sql(15, 5, kind="sandbox_claim")),
        ("R6 末笔 SQL 覆盖三表", all(t in lsql for t in
                                     ("otel.otel_traces", "otel.otel_metrics_sum",
                                      "otel.otel_metrics_gauge"))
         and "dateDiff('second'" in lsql),
        # 2026-11-03 补：「持续发射面」判据的数据源不许退化（回看窗 + 三表并集 + 阈）
        ("R6 写入量 SQL 回看 7 天", "now() - INTERVAL 7 DAY" in wsql),
        ("R6 写入量 SQL 覆盖三表", all(t in wsql for t in
                                       ("otel.otel_traces", "otel.otel_metrics_sum",
                                        "otel.otel_metrics_gauge"))
         and "count() AS n" in wsql),
        ("持续发射面阈=100 / 回看=7 天",
         CONTINUOUS_MIN_WRITES == 100 and CONTINUOUS_LOOKBACK_DAYS == 7),
    ]
    for name, ok in sql_checks:
        print(f"  sql: {name} {'PASS' if ok else 'FAIL'}")
        if not ok:
            fails.append(("sql:" + name,))
    if fails:
        print(f"SELFTEST FAIL: {len(fails)} 项")
        return 1
    print(f"SELFTEST PASS: {len(cases)} 用例 + {len(sql_checks)} 条 SQL 回归断言")
    return 0


# ---------------------------------------------------------------- 实查模式
def run_live(args):
    counts = fetch_counts(args.window, args.skew, args.mes_kind, args.mes_station)
    stale_hours = {s: age / 3600.0 for s, age in counts["otel_last"].items()}
    v = reconcile(counts["mes_rows"], counts["otel_rows"], counts["future_rows"],
                  window_min=args.window, min_otel=args.min_otel,
                  allow_mes_idle=args.allow_mes_idle, strict_future=args.strict_future,
                  idle_red=args.idle_red, stale_hours=stale_hours,
                  stale_after_h=args.stale_hours, strict_stale=args.strict_stale,
                  write_counts=counts.get("otel_write_counts"))
    v["ch_now"] = counts["ch_now"]
    v["endpoint"] = ch_client.resolve()[0]
    v["otel_last_write"] = counts["otel_last"]
    if args.mes_kind or args.mes_station:
        v["mes_filter"] = {"kind": args.mes_kind, "station": args.mes_station}
    if args.json:
        print(json.dumps(v, ensure_ascii=False, indent=1))
    else:
        print(f"[{v['ch_now']}] CH={v['endpoint']} 窗口={v['window_min']}min "
              f"MES={v['counts']['mes_rows']} OTel={v['counts']['otel_rows']} "
              f"未来戳={v['counts']['future_rows']} → {v['status'].upper()}")
        for r in v["rules"]:
            mark = "ok  " if r["ok"] else r["severity"].upper()
            print(f"  {r['rule']} {mark} {r['detail']}")
    return 1 if v["status"] == "red" else 0


def main(argv=None):
    p = argparse.ArgumentParser(description="CH 写入对账门（OTel 库 vs MES/事件侧，同窗比数，异常红）")
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW_MIN, help="对账时间窗（分钟，默认 15）")
    p.add_argument("--skew", type=int, default=DEFAULT_SKEW_MIN, help="未来戳容忍（分钟，默认 5）")
    p.add_argument("--min-otel", type=int, default=DEFAULT_MIN_OTEL, help="OTel 本窗最少行数阈值（默认 10）")
    p.add_argument("--mes-kind", help="MES 侧只看某 kind（如 sandbox_claim）")
    p.add_argument("--mes-station", help="MES 侧只看某 station_id")
    p.add_argument("--allow-mes-idle", action="store_true", help="豁免 R3（工厂停工时 MES 静默不算红）")
    p.add_argument("--strict-future", action=argparse.BooleanOptionalAction, default=True,
                   help="未来戳行记红挡门（2026-11-03 起默认 True；--no-strict-future 显式降回 WARN）")
    p.add_argument("--stale-hours", type=float, default=DEFAULT_STALE_HOURS,
                   help="R6 新鲜度阈值（小时，默认 24；只判「曾发射过而末笔超阈」的服务）")
    p.add_argument("--strict-stale", action="store_true",
                   help="R6 新鲜度超阈一律记红（默认按需发射面仍 WARN 不挡门；"
                        "持续发射面超阈未写默认已红）")
    p.add_argument("--idle", choices=("pass", "red"), default="pass",
                   help="双零处置（默认：OTel 整链静默→红，链仍在写→真空闲记 PASS 带注）")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--selftest", action="store_true", help="夹具矩阵自证（零网络，进 all-gates L3）")
    args = p.parse_args(argv)
    args.idle_red = args.idle == "red"
    if args.selftest:
        return selftest()
    try:
        return run_live(args)
    except ch_client.CHError as e:
        print(f"对账门执行错（CH 不可达/查询失败，不猜绿）: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"对账门执行错: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
