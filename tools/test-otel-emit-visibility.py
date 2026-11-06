#!/usr/bin/env python3
"""test-otel-emit-visibility.py — OTel 链「发射失败可见性」常驻回归门

背景（红队确证发现，2026-11-02，修复员-18-OTel链）：守护/收割两发射面此前无
「发射失败可见性」——
  ① 双守护调用点丢弃返回值：tools/factory-scheduler.py 的 _otel.order_round(...)、
     tools/factory-keepalive.py 的 _otel.guardian_round(...) 外层 `except Exception:
     pass` 且 ok 不取；tools/otel/factory_otel.py 内 `ok &= otel_emit.emit_metric(...)`
     的失败布尔一路无人消费；守护面 grep stats/describe/errors 零命中＝无 stats 上报面。
  ② 收割面记账被管道吃掉：tools/sandbox-harvester.py 的 [otel] 逐条记账走 stderr，
     唯一调用者 tools/event-router.py 用 `harvest 2>&1 | tail -1`——合流后再截末行，
     记账行整段被吃；且全仓无任何消费者解析 'otel spans='（即便末行 errors=14 也无人读）。

判据（全部实跑，任一不过即非零退出）：
  A  factory_otel.guard/visible_failure：端点不可达→errors 增量>0 且出可见文本；
     真发成功（本地假 collector 200）→ok=True、errors=0、无可见文本（不误报）；
     禁用（AF_OTEL_DISABLE=1）→errors=0 且无可见文本（有意静默不算失败、不刷屏）
  B  守护面：调度器/守护的发射失败落各自日志；调度器另有状态文件 otel 段（stats 上报面）
  C  收割面：harvester _otel_safe 消费 ok → stderr 逐条记账 + 计数（emit_failures）
  D  管道不再吃账：旧形态 `2>&1 | tail -1` 吃掉 [otel] 行（复现），新形态分流保留；
     汇总行的 otel 记账可被解析（有人读了）
  E  源码自证：调用点不再 `except Exception: pass` 丢 ok；harvester 调用不再合流截断；
     factory_otel 三函数仍返回 ok（不弱化既有断言）

用法：python3 -I tools/test-otel-emit-visibility.py
退出码：0 全过；1 断言失败。
零写生产面：夹具落 $HOME 自建 scratch 目录，完工即删；探针自身只读生产面。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WS, "tools")
OTEL_DIR = os.path.join(TOOLS, "otel")
SCRATCH = os.path.join(os.path.expanduser("~"), ".tmp_test_otel_emit_vis")

UNREACHABLE = "http://127.0.0.1:1"      # 连接即拒（ECONNREFUSED，瞬时失败）

FAILS = []
NCASE = 0


def check(name, cond, detail=""):
    global NCASE
    NCASE += 1
    if cond:
        print("  [PASS] %s %s" % (name, detail), flush=True)
    else:
        print("  [FAIL] %s %s" % (name, detail), flush=True)
        FAILS.append(name)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("spec 构建失败 %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# 本地假 collector（真 HTTP 收发）：证明「真发成功」时 ok=True 且不误报失败
# --------------------------------------------------------------------------- #
class _Collector(BaseHTTPRequestHandler):
    hits = []

    def do_POST(self):  # noqa: N802 —— BaseHTTPRequestHandler 约定名
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_a):
        pass


def start_fake_collector():
    srv = HTTPServer(("127.0.0.1", 0), _Collector)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def main():
    os.makedirs(SCRATCH, exist_ok=True)
    # 熔断文件指向 scratch 下不存在的路径：让本门在生产 OTEL-STOP 在/不在场时口径一致
    # （stop_active 只看文件在位；本门不测熔断分支，只测「真失败可见」）。
    os.environ["AF_OTEL_STOP"] = os.path.join(SCRATCH, "no-such-stop")
    os.environ["AF_OTEL_DISABLE"] = ""
    os.environ["AF_OTEL_ENDPOINT"] = UNREACHABLE
    # 调度器日志重定向到 scratch（FS_LOG 在 import 时读）
    sched_log = os.path.join(SCRATCH, "scheduler.log")
    os.environ["FS_LOG"] = sched_log
    os.environ["FS_STATE"] = os.path.join(SCRATCH, "scheduler-state.json")
    try:
        fo = load("otel_fo_under_test", os.path.join(OTEL_DIR, "factory_otel.py"))
        fs = load("otel_fs_under_test", os.path.join(TOOLS, "factory-scheduler.py"))
        fk = load("otel_fk_under_test", os.path.join(TOOLS, "factory-keepalive.py"))
        sh = load("otel_sh_under_test", os.path.join(TOOLS, "sandbox-harvester.py"))
        er = load("otel_er_under_test", os.path.join(TOOLS, "event-router.py"))

        # ---------------- A1 端点不可达 → guard 记账 errors 增量>0 ----------------
        rep = fo.guard(fo.order_round, pending=3, in_flight=1, triggered=[],
                       mode="live", service="factory-scheduler")
        check("A1 端点不可达→guard 记 errors 增量>0（失败不再被丢弃）",
              rep["errors"] >= 1 and rep["ok"] is False and rep["exc"] is None,
              "rep=%s" % json.dumps(rep, ensure_ascii=False))

        # ---------------- A2 visible_failure 出可见文本 ----------------
        vis = fo.visible_failure(rep, "订单面")
        check("A2 visible_failure 出可见文本（含 订单面埋点 与 发射失败）",
              bool(vis) and "订单面埋点" in vis and "发射失败" in vis, "vis=%r" % vis)

        # ---------------- A3 真发成功（本地假 collector）→ ok=True、无误报 ----------------
        srv, ep = start_fake_collector()
        try:
            os.environ["AF_OTEL_ENDPOINT"] = ep
            before_hits = len(_Collector.hits)
            rep_ok = fo.guard(fo.order_round, pending=1, in_flight=0, triggered=["pool:+"],
                              mode="live", service="factory-scheduler")
            hits = _Collector.hits[before_hits:]
        finally:
            srv.shutdown()
            os.environ["AF_OTEL_ENDPOINT"] = UNREACHABLE
        check("A3 真发成功→ok=True 且 errors=0（不误报失败）",
              rep_ok["ok"] is True and rep_ok["errors"] == 0 and rep_ok["exc"] is None,
              "rep=%s" % json.dumps(rep_ok, ensure_ascii=False))
        check("A3b 真发成功→collector 实收 trace/metric 两路（ok 反映真值）",
              any(h.endswith("/v1/traces") for h in hits)
              and any(h.endswith("/v1/metrics") for h in hits),
              "hits=%s" % (hits or "无"))
        check("A3c 真发成功→visible_failure 不出声（无失败不刷屏）",
              fo.visible_failure(rep_ok, "订单面") is None,
              "vis=%r" % fo.visible_failure(rep_ok, "订单面"))

        # ---------------- A4 禁用（有意静默）→ 不算失败、不出声 ----------------
        os.environ["AF_OTEL_DISABLE"] = "1"
        try:
            rep_dis = fo.guard(fo.order_round, pending=0, in_flight=0, triggered=[],
                               mode="live", service="factory-scheduler")
        finally:
            os.environ["AF_OTEL_DISABLE"] = ""
        check("A4 禁用(AF_OTEL_DISABLE=1)→errors=0 且不出文本（有意静默≠失败）",
              rep_dis["errors"] == 0 and fo.visible_failure(rep_dis, "订单面") is None,
              "rep=%s" % json.dumps(rep_dis, ensure_ascii=False))

        # ---------------- B1 调度器：发射失败落调度器日志 ----------------
        if os.path.exists(sched_log):
            os.remove(sched_log)
        rep_s = fs.otel_order_round(2, 1, ["pool:+"], "live")
        log_txt = open(sched_log, encoding="utf-8").read() if os.path.exists(sched_log) else ""
        check("B1 调度器：发射失败落日志（含 [otel]/发射失败）",
              rep_s["errors"] >= 1 and "[otel]" in log_txt and "发射失败" in log_txt,
              "rep=%s log=%r" % (json.dumps(rep_s, ensure_ascii=False), log_txt[-120:]))

        # ---------------- B2 调度器：状态文件 otel 段（stats 上报面） ----------------
        sec = fs.otel_state_section(rep_s)
        check("B2 调度器：状态 otel 段带 errors + stats（stats 上报面在位）",
              sec.get("errors", 0) >= 1 and isinstance(sec.get("stats"), dict)
              and "errors" in sec["stats"],
              "sec=%s" % json.dumps(sec, ensure_ascii=False)[:200])

        # ---------------- B3 守护：发射失败落守护日志 ----------------
        keep_log = os.path.join(SCRATCH, "keepalive.log")
        fk.KLOG = keep_log
        rep_k = fk.otel_guardian_round({"a": (True, "x"), "b": (False, "y")}, dry=False)
        klog_txt = open(keep_log, encoding="utf-8").read() if os.path.exists(keep_log) else ""
        check("B3 守护：发射失败落 klog（含 [otel]/发射失败）",
              rep_k["errors"] >= 1 and "[otel]" in klog_txt and "发射失败" in klog_txt,
              "rep=%s log=%r" % (json.dumps(rep_k, ensure_ascii=False), klog_txt[-120:]))

        # ---------------- B4 调度器 round_once 集成：状态文件真落 otel 段 ----------------
        # （轮次各面全部打桩：不接网络、不碰生产面；FS_LOG/FS_STATE 已在 import 前指到 scratch）
        fs.collect = lambda: {"pending_count": 2, "inflight": 1, "step_inflight": 0,
                              "daemons": {}, "error": None,
                              "quota": {"step_go": "go", "step_used": 0, "mm_go": "go",
                                        "mm_5h": 0, "mm_wk": 0, "stale": False,
                                        "age_s": None}}
        fs.supply_round = lambda st, d, force: []
        fs._portal_supply = lambda st: []
        fs.health_round = lambda st, d: []
        fs.minimax_round = lambda st, d: []
        st_in = {"rounds": 0}
        fs.round_once(st_in, False)
        state_json = json.load(open(os.environ["FS_STATE"], encoding="utf-8"))
        otel_sec = state_json.get("otel") or {}
        check("B4 调度器 round_once 集成：状态文件落 otel 段（errors>0 + stats）",
              otel_sec.get("errors", 0) >= 1 and isinstance(otel_sec.get("stats"), dict)
              and "errors" in otel_sec["stats"],
              "state.otel=%s" % json.dumps(otel_sec, ensure_ascii=False)[:200])

        # ---------------- C1 收割面：_otel_safe 消费 ok → stderr 逐条 + 计数 ----------------
        before_fail = getattr(sh, "_otel_emit_failures", 0)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            sh._otel_safe(task_id="otelvis-t1", verdict="ok", atoms=1, mode="harvest")
        err_txt = buf.getvalue()
        after_fail = getattr(sh, "_otel_emit_failures", 0)
        check("C1 收割面：发射失败逐条落 stderr（含 [otel]/发射失败）",
              "[otel]" in err_txt and "发射失败" in err_txt, "stderr=%r" % err_txt[-160:])
        check("C1b 收割面：发射失败计数递增（emit_failures）",
              after_fail >= before_fail + 1,
              "before=%s after=%s" % (before_fail, after_fail))

        # ---------------- D1 管道不再吃账（旧形态复现 vs 新形态保留） ----------------
        fake = ("echo '[otel] harvest 埋点发射失败 1 次（已记账，不影响主职）' >&2; "
                "echo 'harvest done; log: /x/HARVEST-LOG.md; otel spans=0 metrics=0 "
                "errors=14 stop_skipped=0'")
        old = subprocess.run("sh -c \"%s 2>&1 | tail -1\"" % fake, shell=True,
                             capture_output=True, text=True, timeout=60).stdout
        new_out, new_err = er.run_harvester(cmd=fake, timeout=60)
        check("D1 旧形态 `2>&1 | tail -1` 复现：[otel] 记账行被整段吃掉",
              "[otel]" not in old and "otel spans=0" in old, "old=%r" % old[:120])
        check("D1b 新形态（stdout/stderr 分流）：[otel] 记账行保留",
              "[otel]" in new_err and "harvest done" in new_out,
              "out=%r err=%r" % (new_out[:100], new_err[:120]))

        # ---------------- D2 汇总行的 otel 记账可被解析（有人读了） ----------------
        s = er.harvest_summary_otel(new_out)
        check("D2 汇总行 otel 记账可解析（errors=14 不再无人读）",
              bool(s) and s["errors"] == 14 and s["spans"] == 0 and s["stop_skipped"] == 0,
              "parsed=%s" % json.dumps(s, ensure_ascii=False))
        check("D2b 汇总行无 otel 段→返回 None（不猜数）",
              er.harvest_summary_otel("harvest done; log: /x") is None)

        # ---------------- D3 stderr 逐条透传（不被合流截断） ----------------
        lines = er.harvest_stderr_lines(new_err)
        check("D3 harvest_stderr_lines 逐条保留记账行",
              len(lines) == 1 and lines[0].startswith("[otel]"), "lines=%s" % lines)

        # ---------------- E 源码自证：不弱化断言、洞已堵 ----------------
        src_fs = open(os.path.join(TOOLS, "factory-scheduler.py"), encoding="utf-8").read()
        src_fk = open(os.path.join(TOOLS, "factory-keepalive.py"), encoding="utf-8").read()
        src_er = open(os.path.join(TOOLS, "event-router.py"), encoding="utf-8").read()
        src_fo = open(os.path.join(OTEL_DIR, "factory_otel.py"), encoding="utf-8").read()
        src_sh = open(os.path.join(TOOLS, "sandbox-harvester.py"), encoding="utf-8").read()
        check("E1 调度器调用点不再 `except Exception: pass` 丢 ok（改走 guard）",
              "_otel.guard(" in src_fs and "_otel.order_round(pending=" not in src_fs
              and 'st["otel"]' in src_fs,
              "guard=%s order_round(pending=%s otel段=%s"
              % ("_otel.guard(" in src_fs, "_otel.order_round(pending=" in src_fs,
                 'st["otel"]' in src_fs))
        check("E2 守护调用点不再 `except Exception: pass` 丢 ok（改走 guard）",
              "_otel.guard(" in src_fk and "_otel.guardian_round(up=_up," not in src_fk,
              "guard=%s old=%s" % ("_otel.guard(" in src_fk,
                                   "_otel.guardian_round(up=_up," in src_fk))
        check("E3 harvester 调用不再 `2>&1 | tail -1` 合流截断（改分流捕获）",
              "run_harvester(" in src_er
              and "python3 tools/sandbox-harvester.py harvest 2>&1 | tail -1" not in src_er
              and "harvest_stderr_lines(" in src_er and "harvest_summary_otel(" in src_er,
              "run_harvester=%s 合流截断残留=%s"
              % ("run_harvester(" in src_er,
                 "python3 tools/sandbox-harvester.py harvest 2>&1 | tail -1" in src_er))
        check("E4 factory_otel 三发射函数仍返回 ok（既有断言未弱化）",
              all(x in src_fo for x in ("def order_round", "def guardian_round",
                                        "def harvest_report"))
              and src_fo.count("return ok") >= 3
              and "def guard(" in src_fo and "def visible_failure(" in src_fo,
              "return ok×%d guard=%s visible_failure=%s"
              % (src_fo.count("return ok"), "def guard(" in src_fo,
                 "def visible_failure(" in src_fo))
        check("E5 收割面逐条记账与计数在位（stderr + emit_failures + 汇总行）",
              "_otel_emit_failures" in src_sh and "emit_failures" in src_sh
              and "otel 发射失败" in src_sh,
              "计数=%s JSON=%s 汇总行=%s" % ("_otel_emit_failures" in src_sh,
                                            "emit_failures" in src_sh,
                                            "otel 发射失败" in src_sh))
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("小计：PASS=%d FAIL=%d" % (NCASE - len(FAILS), len(FAILS)), flush=True)
    if FAILS:
        print("FAIL %s" % ",".join(FAILS), flush=True)
        return 1
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
