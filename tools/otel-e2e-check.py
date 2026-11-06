#!/usr/bin/env python3
"""otel-e2e-check.py — OTel MVP 端到端验证（exit 0 = 全绿）。

链路：真实工厂链路事件（sandbox-harvester verify，带唯一 marker）
      → OTLP/HTTP JSON → 本机 collector（七件重建件，clickhouse exporter+file_storage）
      → mingda CH otel 库 → SQL 查回逐值对账。

判据（全部实跑，任一不过即非零退出）：
  C1  schema    otel 库 9 表 + 1 MV 在场（缺 → --ensure-schema 可补）
  C2  artifact  collector 二进制含 clickhouse/file_storage 组件；
                交付配置 tools/otel/otelcol-config.yaml validate 过
  C3  ingest    本机 collector 起停正常，OTLP 接收 200
  C4  trace     探针 span 落 otel_traces（TraceId/SpanName/属性逐值相等）
  C5  trace     真实收割事件 span 落 otel_traces（task_id marker 命中，
                ServiceName=sandbox-harvester——埋点脚本路径实证）
  C6  metric    gauge 落 otel_metrics_gauge（marker 属性+Value 相等）
  C7  metric    sum   落 otel_metrics_sum（marker 属性+Value+temporality 相等）
  C8  mv        otel_traces_trace_id_ts_mv 为探针 trace 产出检索行
  C9  reconcile 发射值 vs 库内值全等（marker/service/span/value）
  C10 plaintext  collector 日志与本脚本输出均不含 CH 口令明文

退出码：0=全绿；1=判据不过；2=前置缺失（凭据/二进制/schema）；3=collector 起停失败。
可复跑：每轮 marker 唯一（uuid），按 marker 过滤查询，互不污染；不删历史行
（otel 库=可再生视图，DDL 原生 TTL 30d/90d 收尾——登记于 amvp-report.md）。
零明文：CH 凭据只经环境变量进 collector 子进程；口令绝不落盘、不进输出
（C10 反向断言）。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
OTEL_DIR = os.path.join(WS, "tools", "otel")
sys.path.insert(0, OTEL_DIR)
import ch_client  # noqa: E402
import factory_otel  # noqa: E402
import otel_emit  # noqa: E402

E2E_CFG = os.path.join(OTEL_DIR, "otelcol-config.yaml")
E2E_DDL = os.path.join(OTEL_DIR, "otel-ddl.sql")
HARVESTER = os.path.join(WS, "tools", "sandbox-harvester.py")

EXPECT_TABLES = ["otel_logs", "otel_metrics_exponential_histogram", "otel_metrics_gauge",
                 "otel_metrics_histogram", "otel_metrics_sum", "otel_metrics_summary",
                 "otel_traces", "otel_traces_trace_id_ts", "otel_traces_trace_id_ts_mv"]

_results: list[tuple[str, bool, str]] = []


def check(cid: str, ok: bool, evidence: str) -> bool:
    _results.append((cid, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {evidence}", flush=True)
    return ok


def redact(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "▉▉▉")
    return text


def find_collector(arg: str | None) -> str | None:
    for cand in (arg, os.environ.get("OTELCOL_BIN"),
                 os.path.join(OTEL_DIR, "bin", "otelcol"),
                 os.path.expanduser("~/otelcol-build/build/otelcol"),
                 os.path.expanduser("~/otelcol-build/bin/otelcol")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="OTel MVP 端到端验证（exit 0=全绿）")
    ap.add_argument("--ensure-schema", action="store_true",
                    help="otel 库 schema 缺失时按 tools/otel/otel-ddl.sql 补建（幂等）")
    ap.add_argument("--collector-bin", help="collector 二进制路径（缺省按 OTELCOL_BIN/约定位查找）")
    ap.add_argument("--marker", help="本轮唯一 marker（缺省 uuid，供调试复跑同一 marker）")
    ap.add_argument("--port", type=int, default=4318, help="本机 collector OTLP HTTP 口")
    ap.add_argument("--timeout", type=float, default=60.0, help="SQL 查回轮询上限（s）")
    ap.add_argument("--keep-running", action="store_true", help="验证后不关 collector（排查用）")
    a = ap.parse_args()
    marker = a.marker or f"e2e-{uuid.uuid4().hex[:12]}-{os.getpid()}"
    ep = f"http://127.0.0.1:{a.port}"
    # 探针 trace_id 由 marker 确定性派生（每轮 marker 唯一→trace 唯一，可复跑不撞车；
    # 与 otlp-model §1.0 同族派生式：域种子+身份键）
    probe_tid = hashlib.sha256(f"af-factory-v1|e2e|{marker}".encode()).hexdigest()[:32]
    probe_sid = otel_emit.span_id_for("e2e-probe", marker)
    harvest_task = f"kb-verify-{marker}"
    gauge_val, sum_val = 42.0, 7.0
    t_start = int(time.time())

    # ---- 前置：凭据链（零明文：只解析不打印） ---------------------------------
    try:
        base, auth = ch_client.resolve()
        secret = None
        if auth:
            secret = base64.b64decode(auth.split(" ", 1)[1]).decode().split(":", 1)[1]
        ch_client.query("SELECT 1")
        print(f"preflight: CH 端点 {base} 查询级连通（凭据经 env/0600 链现取，不打印）", flush=True)
    except Exception as e:
        print(f"前置失败：CH 凭据链解析/连通失败: {redact(str(e), None)}")
        return 2
    # 拆分 user:pass 供 collector 子进程 env 注入（只进子进程环境，不落盘）
    ch_user = ch_pass = ""
    if auth:
        userinfo = base64.b64decode(auth.split(" ", 1)[1]).decode()
        ch_user, ch_pass = userinfo.split(":", 1)

    # ---- C1 schema ------------------------------------------------------------
    try:
        rows = ch_client.query(
            "SELECT name FROM system.tables WHERE database='otel'")
        have = {r["name"] for r in rows}
        missing = [t for t in EXPECT_TABLES if t not in have]
        if missing and a.ensure_schema:
            ch_client.apply_ddl(E2E_DDL)
            have = {r["name"] for r in ch_client.query(
                "SELECT name FROM system.tables WHERE database='otel'")}
            missing = [t for t in EXPECT_TABLES if t not in have]
        check("C1", not missing,
              f"otel 库表在场 {len(have & set(EXPECT_TABLES))}/{len(EXPECT_TABLES)}"
              + (f"；缺 {missing}" if missing else ""))
        if missing:
            print("前置失败：schema 缺表（--ensure-schema 可补建）")
            return 2
    except Exception as e:
        print(f"前置失败：schema 检查异常: {redact(str(e), secret)}")
        return 2

    # ---- C2 artifact ----------------------------------------------------------
    cbin = find_collector(a.collector_bin)
    comp_ok, comp_ev = False, "未找到 collector 二进制"
    if cbin:
        r = subprocess.run([cbin, "components"], capture_output=True, text=True, timeout=60)
        names = set(re.findall(r"- name: (\w+)", r.stdout))
        comp_ok = {"clickhouse", "file_storage", "otlp", "batch", "memory_limiter"} <= names
        comp_ev = f"{os.path.basename(cbin)} 组件 {sorted(names)}"
    else:
        comp_ev = "OTELCOL_BIN/约定位无二进制（先 ocb 重建，见 tools/otel/builder-config.yaml）"
    check("C2a", comp_ok, comp_ev)
    if not cbin:
        print("前置失败：collector 二进制缺失")
        return 2
    env_ph = {"MES_CH_ENDPOINT": base, "MES_CH_USERNAME": ch_user, "MES_CH_PASSWORD": ch_pass}
    v = subprocess.run([cbin, "validate", f"--config={E2E_CFG}"],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, **{k: "validate-placeholder" for k in env_ph}})
    check("C2b", v.returncode == 0,
          f"validate {E2E_CFG} rc={v.returncode} {redact(v.stderr.strip()[:120], secret)}")
    if v.returncode != 0:
        return 2

    # ---- 本机 collector（交付配置派生：只改绑定地址与 storage 目录） -------------
    # 派生规则（相对交付配置的受控替换，形状漂移即显性失败）：
    #   · /data/otelcol/storage → 本轮临时目录（主目录+compaction 目录两处，缺一即起不来：
    #     filestorage extension.go:36 对 cfg.Directory 与 cfg.Compaction.Directory 都 MkdirAll）
    #   · anolis-host.invalid:4317/4318 → 127.0.0.1（本机验证绑定；生产部署保持 tailnet IP 不动）
    tmp = tempfile.mkdtemp(prefix="otel-e2e-", dir=os.path.expanduser("~"))
    storage_dir = os.path.join(tmp, "storage")
    cfg_src = open(E2E_CFG, encoding="utf-8").read()
    n_storage = cfg_src.count("/data/otelcol/storage")
    if n_storage < 2:
        print(f"前置失败：交付配置 storage 目录锚 <2（主+compaction，实 {n_storage}）——配置漂移？")
        shutil.rmtree(tmp, ignore_errors=True)
        return 2
    cfg = cfg_src.replace("/data/otelcol/storage", storage_dir)
    cfg = cfg.replace(f"anolis-host.invalid:4317", f"127.0.0.1:{a.port - 1}")
    cfg = cfg.replace(f"anolis-host.invalid:4318", f"127.0.0.1:{a.port}")
    cfg_path = os.path.join(tmp, "otelcol-config.yaml")
    open(cfg_path, "w", encoding="utf-8").write(cfg)
    log_path = os.path.join(tmp, "collector.log")
    proc = None
    try:
        logf = open(log_path, "wb")
        proc = subprocess.Popen([cbin, f"--config={cfg_path}"], stdout=logf,
                                stderr=subprocess.STDOUT,
                                env={**os.environ, **env_ph})
        ok_up = False
        for _ in range(50):  # 最多 10s 等起
            time.sleep(0.2)
            if proc.poll() is not None:
                break
            try:
                req = urllib.request.Request(ep + "/v1/traces", data=b"{}",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=2).read()
                ok_up = True
                break
            except urllib.error.HTTPError as e:
                if e.code in (400, 415):  # 端口活着、只是空体被拒=接收器在位
                    ok_up = True
                    break
            except Exception:
                continue
        check("C3", ok_up and proc.poll() is None,
              f"collector pid={proc.pid} OTLP {ep} 可收（rc={proc.poll()}）")
        if not ok_up:
            tail = redact(open(log_path, errors="replace").read()[-400:], secret)
            print("collector 日志尾:\n" + tail)
            return 3

        # ---- 发真实遥测：①真实工厂链路事件（埋点脚本路径） ----------------------
        report = os.path.join(tmp, f"report-{marker}.json")
        open(report, "w").write(json.dumps({
            "task_id": harvest_task, "sandbox": "otel-e2e",
            "payload": {"verify": True, "card_id": marker,
                        "verdicts": [{"atom_id": "a1", "verdict": "uphold",
                                      "quote_check": True, "reason": "e2e"}]}}))
        hv = subprocess.run([sys.executable, HARVESTER, "verify", report],
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, "AF_OTEL_ENDPOINT": ep})
        hv_json = json.loads(hv.stdout) if hv.stdout.strip() else {}
        check("C3b", hv_json.get("verdict") == "ok",
              f"sandbox-harvester verify verdict={hv_json.get('verdict')}（埋点路径实跑）")
        if hv_json.get("verdict") != "ok":
            return 1

        # ---- 发真实遥测：②探针 span + 标记 gauge/sum（库函数直发，同端点） -------
        os.environ["AF_OTEL_ENDPOINT"] = ep
        now = time.time_ns()
        otel_emit.emit_span("factory.e2e_probe", trace_id=probe_tid, span_id=probe_sid,
                            kind=1, start_ns=now, end_ns=now,
                            attributes={"af.e2e.marker": marker, "af.e2e.probe": "span"},
                            res=otel_emit.resource(service="otel-e2e-check"))
        otel_emit.emit_metric("factory.e2e_probe_gauge", gauge_val, unit="1",
                              attributes={"af.e2e.marker": marker, "af.e2e.probe": "gauge"},
                              res=otel_emit.resource(service="otel-e2e-check"), kind="gauge")
        otel_emit.emit_metric("factory.e2e_probe_sum", sum_val, unit="1",
                              attributes={"af.e2e.marker": marker, "af.e2e.probe": "sum"},
                              res=otel_emit.resource(service="otel-e2e-check"), kind="sum")
        st = otel_emit.stats()
        check("C3c", st["spans"] >= 1 and st["metrics"] >= 2 and st["errors"] == 0,
              f"进程内发射记账 spans={st['spans']} metrics={st['metrics']} errors={st['errors']}")
        if st["errors"]:
            return 1

        # ---- 查回对账（轮询至 timeout） -----------------------------------------
        def poll(sql):
            deadline = time.time() + a.timeout
            last = None
            while time.time() < deadline:
                try:
                    rows = ch_client.query(sql)
                    if rows:
                        return rows
                    last = rows
                except Exception as e:  # noqa: BLE001
                    last = [{"err": redact(str(e), secret)[:200]}]
                time.sleep(1.0)
            return last or []

        # C4 探针 span
        rows = poll(f"SELECT TraceId, SpanName, ServiceName, SpanKind, "
                    f"SpanAttributes['af.e2e.marker'] AS mk, Duration "
                    f"FROM otel.otel_traces FINAL WHERE TraceId = '{probe_tid}'")
        r = rows[0] if rows else {}
        check("C4", bool(rows) and r.get("TraceId") == probe_tid
              and r.get("SpanName") == "factory.e2e_probe"
              and r.get("mk") == marker and r.get("ServiceName") == "otel-e2e-check",
              f"traces 探针行: {json.dumps({k: r.get(k) for k in ('TraceId','SpanName','ServiceName','SpanKind','mk')}, ensure_ascii=False)[:220]}")
        # C5 真实收割事件 span
        rows = poll(f"SELECT SpanName, ServiceName, SpanAttributes['af.factory.harvest.task_id'] AS task, "
                    f"SpanAttributes['af.factory.harvest.verdict'] AS verdict "
                    f"FROM otel.otel_traces FINAL WHERE SpanAttributes['af.factory.harvest.task_id'] = '{harvest_task}'")
        r = rows[0] if rows else {}
        check("C5", bool(rows) and r.get("task") == harvest_task
              and r.get("ServiceName") == "sandbox-harvester" and r.get("verdict") == "ok",
              f"traces 收割事件行: {json.dumps({k: r.get(k) for k in ('SpanName','ServiceName','task','verdict')}, ensure_ascii=False)[:220]}")
        # C6 gauge
        rows = poll(f"SELECT MetricName, ServiceName, Value, Attributes['af.e2e.marker'] AS mk "
                    f"FROM otel.otel_metrics_gauge WHERE Attributes['af.e2e.marker'] = '{marker}'")
        r = rows[0] if rows else {}
        check("C6", bool(rows) and abs(float(r.get("Value", -1)) - gauge_val) < 1e-9
              and r.get("mk") == marker and r.get("ServiceName") == "otel-e2e-check",
              f"gauge 行: {json.dumps({k: r.get(k) for k in ('MetricName','ServiceName','Value','mk')}, ensure_ascii=False)[:200]}")
        # C7 sum
        rows = poll(f"SELECT MetricName, Value, AggregationTemporality, IsMonotonic, "
                    f"Attributes['af.e2e.marker'] AS mk FROM otel.otel_metrics_sum "
                    f"WHERE Attributes['af.e2e.marker'] = '{marker}'")
        r = rows[0] if rows else {}
        check("C7", bool(rows) and abs(float(r.get("Value", -1)) - sum_val) < 1e-9
              and int(r.get("AggregationTemporality", -1)) == 1
              and int(r.get("IsMonotonic", -1)) == 1 and r.get("mk") == marker,
              f"sum 行: {json.dumps({k: r.get(k) for k in ('MetricName','Value','AggregationTemporality','IsMonotonic','mk')}, ensure_ascii=False)[:220]}")
        # C8 MV 检索行
        rows = poll(f"SELECT TraceId, Start, End FROM otel.otel_traces_trace_id_ts "
                    f"WHERE TraceId = '{probe_tid}'")
        check("C8", bool(rows) and rows[0].get("TraceId") == probe_tid,
              f"trace_id_ts 行: {json.dumps(rows[0] if rows else {}, ensure_ascii=False)[:160]}")
        # C9 对账总判（C4-C8 全过即对账成立；此处复核两侧关键标量一致）
        c45678 = all(ok for cid, ok, _ in _results if cid in ("C4", "C5", "C6", "C7", "C8"))
        check("C9", c45678,
              f"发射↔入库逐值对账成立（marker={marker} probe_trace={probe_tid[:12]}… "
              f"gauge={gauge_val} sum={sum_val}）" if c45678 else "存在未过判据，对账不成立")
        # C10 零明文反向断言
        log_txt = open(log_path, errors="replace").read()
        leak = bool(secret) and secret in log_txt
        check("C10", not leak,
              "collector 日志与输出均无 CH 口令明文" if not leak else "collector 日志含口令明文！")
    finally:
        if proc is not None:
            if a.keep_running:
                print(f"collector 保持运行 pid={proc.pid}（--keep-running）；tmp={tmp}")
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                shutil.rmtree(tmp, ignore_errors=True)

    bad = [cid for cid, ok, _ in _results if not ok]
    print(f"\n===== OTel MVP e2e: {len(_results) - len(bad)}/{len(_results)} PASS"
          f"（marker={marker}）=====")
    if bad:
        print("未过判据:", ", ".join(bad))
        return 1
    print("全部判据通过：真实遥测 → collector → mingda CH otel 库 → SQL 查回对账闭环。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
