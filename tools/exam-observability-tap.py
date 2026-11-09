#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exam-observability-tap.py — 考试观测事件采集器（af.exam-obs.v1 · factory-os #272）

读 stdin 或文件流的 JSONL 事件行，schema af.exam-obs.v1，字段 ts / actor /
event / detail。三类事件：

  GOLDEN_ACCESS_ATTEMPT
  IDLE_TIMEOUT
  TEST_REQUESTED

模式：
  --summary   聚合计数 + 时间线
  --anomaly   同 actor 在 300s 窗内 GOLDEN_ACCESS_ATTEMPT > 3 ⇒ 点名
  --selftest  夹具逐个真跑（子进程 python3 -I 本件；零网络；临时目录用后即清）

无 --summary/--anomaly/--selftest 时，默认同时出 summary 与 anomaly。
夹具用 SENTINEL-XXX 形。本件零网络、零仓内写入（selftest 只写临时目录）。

出口：
  0  采集完成 / 自证全过
  1  自证有断言败
  2  缺件 / 不可读 / 用法错（tty 无参）

用法：
  python3 -I tools/exam-observability-tap.py --selftest
  python3 -I tools/exam-observability-tap.py --summary FILE.jsonl
  python3 -I tools/exam-observability-tap.py --anomaly FILE.jsonl
  python3 -I tools/exam-observability-tap.py --summary --anomaly < stream.jsonl
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

SCHEMA = "af.exam-obs.v1"
EVT_GOLDEN = "GOLDEN_ACCESS_ATTEMPT"
EVT_IDLE = "IDLE_TIMEOUT"
EVT_TEST = "TEST_REQUESTED"
KNOWN_EVENTS = (EVT_GOLDEN, EVT_IDLE, EVT_TEST)

ANOMALY_WINDOW_S = 300
ANOMALY_OVER = 3

RC_OK, RC_FAIL, RC_UNPROVABLE = 0, 1, 2

UTC = datetime.timezone.utc


def parse_ts(raw):
    """把 ts 收成 UTC epoch 秒。unix 数字 / ISO 8601 / 空格分隔 均可。失败 → None。"""
    if raw is None or raw is False or raw is True:
        return None
    if isinstance(raw, int):
        val = float(raw)
        if val > 1e12:
            val = val / 1000.0
        return val
    if isinstance(raw, float):
        if raw != raw:  # NaN
            return None
        val = float(raw)
        if val > 1e12:
            val = val / 1000.0
        return val
    s = str(raw).strip()
    if not s:
        return None
    try:
        val = float(s)
    except ValueError:
        val = None
    if val is not None:
        if val > 1e12:
            val = val / 1000.0
        return val
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def format_ts(epoch):
    dt = datetime.datetime.fromtimestamp(float(epoch), tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_line(line):
    """解析一行。返回 (event_dict|None, kind)。

    kind: ok / blank / skip
      blank = 空行或 # 注释（不计入 SKIPPED）
      skip  = 坏 JSON / 缺字段 / 未知事件 / 错 schema
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None, "blank"
    try:
        obj = json.loads(s)
    except ValueError:
        return None, "skip"
    if not isinstance(obj, dict):
        return None, "skip"
    sch = obj.get("schema")
    if sch is not None and sch != SCHEMA:
        return None, "skip"
    actor = obj.get("actor")
    event = obj.get("event")
    ts = parse_ts(obj.get("ts"))
    if not isinstance(actor, str) or not actor.strip():
        return None, "skip"
    if event not in KNOWN_EVENTS:
        return None, "skip"
    if ts is None:
        return None, "skip"
    detail = obj.get("detail", {})
    return {
        "ts": ts,
        "actor": actor.strip(),
        "event": event,
        "detail": detail,
        "schema": SCHEMA,
    }, "ok"


def load_text(text):
    events = []
    skipped = 0
    for line in text.splitlines():
        rec, kind = parse_line(line)
        if kind == "blank":
            continue
        if kind != "ok":
            skipped += 1
            continue
        events.append(rec)
    return events, skipped


def load_paths(paths, stdin_stream):
    """读路径列表；空列表读 stdin。缺件/不可读 → (None, None, err)。"""
    chunks = []
    if not paths:
        chunks.append(stdin_stream.read())
    else:
        for p in paths:
            if p == "-":
                chunks.append(stdin_stream.read())
                continue
            if not os.path.isfile(p):
                return None, None, "缺件：%s" % p
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    chunks.append(fh.read())
            except OSError as exc:
                return None, None, "不可读：%s（%s）" % (p, exc)
    events = []
    skipped = 0
    for text in chunks:
        ev, sk = load_text(text)
        events.extend(ev)
        skipped += sk
    return events, skipped, None


def summarize(events):
    counts = {evt: 0 for evt in KNOWN_EVENTS}
    for rec in events:
        counts[rec["event"]] += 1
    decorated = []
    for i, rec in enumerate(events):
        decorated.append((rec["ts"], rec["actor"], rec["event"], i, rec))
    decorated.sort()
    timeline = [row[4] for row in decorated]
    return counts, timeline


def detect_anomalies(events, window_s=ANOMALY_WINDOW_S, over=ANOMALY_OVER):
    """同 actor 滑窗：GOLDEN_ACCESS_ATTEMPT 条数 > over 且跨度 ≤ window_s ⇒ 点名。"""
    by_actor = {}
    for rec in events:
        if rec["event"] != EVT_GOLDEN:
            continue
        by_actor.setdefault(rec["actor"], []).append(rec["ts"])
    named = []
    for actor in sorted(by_actor):
        stamps = sorted(by_actor[actor])
        left = 0
        best_n = 0
        best_lo = 0
        best_hi = 0
        for right, t in enumerate(stamps):
            while t - stamps[left] > window_s:
                left += 1
            n = right - left + 1
            if n > best_n:
                best_n = n
                best_lo = left
                best_hi = right
        if best_n > over:
            named.append({
                "actor": actor,
                "n": best_n,
                "span_s": stamps[best_hi] - stamps[best_lo],
                "first_ts": stamps[best_lo],
                "last_ts": stamps[best_hi],
            })
    return named


def render_summary(events, skipped):
    counts, timeline = summarize(events)
    lines = [
        "SCHEMA=%s" % SCHEMA,
        "EVENTS=%d" % len(events),
        "%s=%d" % (EVT_GOLDEN, counts[EVT_GOLDEN]),
        "%s=%d" % (EVT_IDLE, counts[EVT_IDLE]),
        "%s=%d" % (EVT_TEST, counts[EVT_TEST]),
        "SKIPPED=%d" % skipped,
        "TIMELINE",
    ]
    for rec in timeline:
        lines.append("%s %s %s" % (format_ts(rec["ts"]), rec["actor"], rec["event"]))
    return lines


def render_anomaly(named, window_s=ANOMALY_WINDOW_S, over=ANOMALY_OVER):
    lines = [
        "ANOMALY_WINDOW_S=%d" % window_s,
        "ANOMALY_OVER=%d" % over,
        "ANOMALY_COUNT=%d" % len(named),
    ]
    for row in named:
        lines.append(
            "NAMED %s n=%d span_s=%.0f first=%s last=%s"
            % (row["actor"], row["n"], row["span_s"],
               format_ts(row["first_ts"]), format_ts(row["last_ts"]))
        )
    return lines


def run_collect(paths, do_summary, do_anomaly, stdin_stream):
    events, skipped, err = load_paths(paths, stdin_stream)
    if err is not None:
        sys.stderr.write("FAIL %s\n" % err)
        return RC_UNPROVABLE
    out_lines = []
    if do_summary:
        out_lines.extend(render_summary(events, skipped))
    if do_anomaly:
        named = detect_anomalies(events)
        out_lines.extend(render_anomaly(named))
    sys.stdout.write("\n".join(out_lines) + "\n")
    return RC_OK


def _cli(argv, stdin_text=""):
    cmd = [sys.executable, "-I", os.path.abspath(__file__)] + list(argv)
    proc = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _row(ts, actor, event, detail=None):
    rec = {
        "schema": SCHEMA,
        "ts": int(ts) if float(ts) == int(float(ts)) else ts,
        "actor": actor,
        "event": event,
        "detail": {} if detail is None else detail,
    }
    return json.dumps(rec, ensure_ascii=False)


def run_selftest():
    """夹具逐个真跑：每例 subprocess -I 本件，实取 returncode 与输出。"""
    cases = []

    def chk(name, ok, detail=""):
        cases.append((name, bool(ok), detail))
        mark = "PASS" if ok else "FAIL"
        extra = ""
        if not ok and detail:
            extra = " | " + detail.replace("\n", " / ")[:240]
        print("[%s] %s%s" % (mark, name, extra), flush=True)

    t0 = datetime.datetime(2026, 11, 9, 6, 0, 0, tzinfo=UTC).timestamp()
    iso0 = "2026-11-09T06:00:00Z"

    with tempfile.TemporaryDirectory(prefix="exam-obs-tap-") as td:
        def dump(name, rows):
            path = os.path.join(td, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
            return path

        # F1 summary：三类各 1，时间线按 ts 序
        p1 = dump("f1.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 1, "actor-alpha", EVT_IDLE),
            _row(t0 + 2, "actor-beta", EVT_TEST),
        ])
        rc, out, err = _cli(["--summary", p1])
        want_tl = (
            "%s actor-alpha %s" % (iso0, EVT_GOLDEN),
            "%s actor-alpha %s" % ("2026-11-09T06:00:01Z", EVT_IDLE),
            "%s actor-beta %s" % ("2026-11-09T06:00:02Z", EVT_TEST),
        )
        chk("F1 summary 三类各 1 + 时间线序",
            rc == 0
            and "SCHEMA=%s" % SCHEMA in out
            and "EVENTS=3" in out
            and "%s=1" % EVT_GOLDEN in out
            and "%s=1" % EVT_IDLE in out
            and "%s=1" % EVT_TEST in out
            and "SKIPPED=0" in out
            and all(line in out for line in want_tl)
            and "ANOMALY_COUNT" not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F2 anomaly 点名：同 actor 4 次落在 90s 内
        p2 = dump("f2.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 30, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 60, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 90, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p2])
        chk("F2 同 actor 4 次 90s 内 ⇒ 点名",
            rc == 0
            and "ANOMALY_COUNT=1" in out
            and "NAMED actor-alpha n=4" in out
            and "ANOMALY_WINDOW_S=300" in out
            and "ANOMALY_OVER=3" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F3 恰 3 次：>3 才点名，3 次安静
        p3 = dump("f3.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 10, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 20, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p3])
        chk("F3 同 actor 恰 3 次 ⇒ 安静",
            rc == 0 and "ANOMALY_COUNT=0" in out and "NAMED " not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F4 4 次但两两间隔 200s，5min 窗内最多 2 次
        p4 = dump("f4.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 200, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 400, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 600, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p4])
        chk("F4 4 次跨窗（间隔 200s）⇒ 安静",
            rc == 0 and "ANOMALY_COUNT=0" in out and "NAMED " not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F5 两 actor：alpha 4 次点名，beta 2 次安静
        p5 = dump("f5.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 5, "actor-beta", EVT_GOLDEN),
            _row(t0 + 10, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 15, "actor-beta", EVT_GOLDEN),
            _row(t0 + 20, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 25, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p5])
        chk("F5 两 actor 只点名超阈者",
            rc == 0
            and "ANOMALY_COUNT=1" in out
            and "NAMED actor-alpha n=4" in out
            and "NAMED actor-beta" not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F6 IDLE / TEST 不计入 GOLDEN 滑窗
        p6 = dump("f6.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 1, "actor-alpha", EVT_IDLE),
            _row(t0 + 2, "actor-alpha", EVT_TEST),
            _row(t0 + 3, "actor-alpha", EVT_IDLE),
            _row(t0 + 4, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 5, "actor-alpha", EVT_TEST),
        ])
        rc, out, err = _cli(["--anomaly", p6])
        chk("F6 IDLE/TEST 不计入点名",
            rc == 0 and "ANOMALY_COUNT=0" in out and "NAMED " not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F7 坏行 / 错 schema / 缺字段计入 SKIPPED；空行与 # 注释不计
        p7 = dump("f7.jsonl", [
            "{not-json",
            _row(t0, "actor-alpha", EVT_IDLE),
            json.dumps({"schema": "nope.v0", "ts": int(t0),
                        "actor": "actor-alpha", "event": EVT_IDLE}),
            json.dumps({"schema": SCHEMA, "ts": int(t0), "actor": "actor-alpha"}),
            "",
            "# comment-line",
            _row(t0 + 1, "actor-alpha", EVT_TEST),
        ])
        rc, out, err = _cli(["--summary", p7])
        chk("F7 坏行 SKIPPED=3 且有效 2 条入账",
            rc == 0 and "EVENTS=2" in out and "SKIPPED=3" in out
            and "%s=1" % EVT_IDLE in out and "%s=1" % EVT_TEST in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F8 stdin 路径（无文件参）
        body8 = "\n".join([
            _row(t0, "actor-stdin", EVT_TEST),
            _row(t0 + 7, "actor-stdin", EVT_IDLE),
        ]) + "\n"
        rc, out, err = _cli(["--summary"], stdin_text=body8)
        chk("F8 stdin 无文件参",
            rc == 0 and "EVENTS=2" in out
            and "actor-stdin %s" % EVT_TEST in out
            and "actor-stdin %s" % EVT_IDLE in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F9 缺件 ⇒ rc=2
        missing = os.path.join(td, "no-such.jsonl")
        rc, out, err = _cli(["--summary", missing])
        chk("F9 缺件 rc=2",
            rc == RC_UNPROVABLE and "FAIL" in err and "缺件" in err,
            "rc=%s err=%s" % (rc, err.replace("\n", " | ")[:200]))

        # F10 窗右沿含等号 300s：4 次跨度恰 300s ⇒ 点名
        p10 = dump("f10.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 100, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 200, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 300, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p10])
        chk("F10 跨度恰 300s ⇒ 点名",
            rc == 0 and "ANOMALY_COUNT=1" in out
            and "NAMED actor-alpha n=4" in out
            and "span_s=300" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F11 跨度 301s：窗内最多 3 次 ⇒ 安静
        p11 = dump("f11.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 100, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 200, "actor-alpha", EVT_GOLDEN),
            _row(t0 + 301, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p11])
        chk("F11 跨度 301s ⇒ 安静",
            rc == 0 and "ANOMALY_COUNT=0" in out and "NAMED " not in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F12 默认同出 summary+anomaly；ISO 字面 ts
        iso_row = json.dumps({
            "schema": SCHEMA,
            "ts": iso0,
            "actor": "actor-iso",
            "event": EVT_IDLE,
            "detail": {"note": "SENTINEL-ISO-0001"},
        }, ensure_ascii=False)
        body12 = iso_row + "\n" + _row(t0 + 9, "actor-iso", EVT_TEST) + "\n"
        rc, out, err = _cli([], stdin_text=body12)
        chk("F12 默认双面 + ISO ts",
            rc == 0
            and "SCHEMA=%s" % SCHEMA in out
            and "EVENTS=2" in out
            and "%s actor-iso %s" % (iso0, EVT_IDLE) in out
            and "ANOMALY_COUNT=0" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F13 空文件
        p13 = dump("f13.jsonl", [])
        # dump 仍写了单个换行；再写真正空件
        p13 = os.path.join(td, "f13-empty.jsonl")
        open(p13, "w", encoding="utf-8").close()
        rc, out, err = _cli(["--summary", "--anomaly", p13])
        chk("F13 空文件 EVENTS=0 安静",
            rc == 0 and "EVENTS=0" in out and "SKIPPED=0" in out
            and "ANOMALY_COUNT=0" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F14 同时刻 4 条 ⇒ 点名 span_s=0
        p14 = dump("f14.jsonl", [
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0, "actor-alpha", EVT_GOLDEN),
            _row(t0, "actor-alpha", EVT_GOLDEN),
        ])
        rc, out, err = _cli(["--anomaly", p14])
        chk("F14 同时刻 4 条 ⇒ 点名",
            rc == 0 and "ANOMALY_COUNT=1" in out
            and "NAMED actor-alpha n=4" in out
            and "span_s=0" in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

        # F15 两文件拼接
        pa = dump("f15a.jsonl", [_row(t0, "actor-a", EVT_TEST)])
        pb = dump("f15b.jsonl", [_row(t0 + 3, "actor-b", EVT_IDLE)])
        rc, out, err = _cli(["--summary", pa, pb])
        chk("F15 两文件拼接计数",
            rc == 0 and "EVENTS=2" in out
            and "actor-a %s" % EVT_TEST in out
            and "actor-b %s" % EVT_IDLE in out,
            "rc=%s out=%s" % (rc, out.replace("\n", " | ")[:200]))

    n = len(cases)
    n_ok = sum(1 for c in cases if c[1])
    fails = [c[0] for c in cases if not c[1]]
    if fails:
        print("自证 %d/%d 例不符：%s" % (n_ok, n, fails), flush=True)
        print("SELFTEST_VERDICT=FAIL", flush=True)
        print("ALL FAIL", flush=True)
        return RC_FAIL
    print("自证 %d/%d 例全过（夹具逐个真跑；零网络）" % (n_ok, n), flush=True)
    print("SELFTEST_VERDICT=PASS", flush=True)
    print("ALL PASS", flush=True)
    return RC_OK


def build_parser():
    ap = argparse.ArgumentParser(
        description="exam-observability-tap — 考试观测事件采集器（af.exam-obs.v1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "读 stdin 或文件的 JSONL 事件行。三类事件：\n"
            "  GOLDEN_ACCESS_ATTEMPT / IDLE_TIMEOUT / TEST_REQUESTED\n"
            "字段：ts / actor / event / detail；schema=af.exam-obs.v1\n"
            "\n"
            "  --summary   聚合计数 + 时间线\n"
            "  --anomaly   同 actor 在 300s 内 GOLDEN_ACCESS_ATTEMPT>3 则点名\n"
            "  --selftest  夹具逐个真跑（零网络，临时目录用后即清）\n"
        ),
    )
    ap.add_argument("--selftest", action="store_true",
                    help="夹具逐个真跑（子进程跑本件）")
    ap.add_argument("--summary", action="store_true",
                    help="聚合计数 + 时间线")
    ap.add_argument("--anomaly", action="store_true",
                    help="同 actor 5min 内 GOLDEN_ACCESS_ATTEMPT>3 点名")
    ap.add_argument("paths", nargs="*",
                    help="JSONL 路径；缺省读 stdin；- 亦为 stdin")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.selftest:
        if args.paths or args.summary or args.anomaly:
            sys.stderr.write("FAIL 用法：--selftest 独用，不搭路径或其它开关\n")
            return RC_UNPROVABLE
        return run_selftest()
    do_summary = args.summary
    do_anomaly = args.anomaly
    if not do_summary and not do_anomaly:
        do_summary = True
        do_anomaly = True
    if not args.paths and sys.stdin.isatty():
        ap.print_usage()
        sys.stderr.write("FAIL 用法：tty 下须给文件路径，或显式 --selftest\n")
        return RC_UNPROVABLE
    return run_collect(args.paths, do_summary, do_anomaly, sys.stdin)


if __name__ == "__main__":
    raise SystemExit(main())
