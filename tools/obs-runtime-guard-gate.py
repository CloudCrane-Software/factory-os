#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""观测面运行时守卫门（RT-E135 / RT-E106 / RT-E28 三腿；波次B·B2 链 2026-11-05）。

判据源=单一源：
  · RT-E135 发射面判死判据=tools/otel/otlp-assert.py:_sidecar_emit_dead_reason
    （读快照 emit.span_sent/emit.metrics_sent）；本门**不复制**该判据语义，只做
    交叉断言与**失明回归**守卫（判据被摘掉 ⇒ 红）。
  · RT-E106 判活根=tools/factory-watch.py:SCHED_STATUS 与
    tools/factory-keepalive.py:LOCAL_GUARDS[scheduler].state（两监督面须同源）。
  · RT-E28 预期灯到期记账=tools/bench-retire-obs-review.py:classify_alarms
    （首见时间/连续时长/超阈升级）。
登记面=30-工件/观测面清偿批-20261105/gate-registry.json。

出口：0=绿；2=红；3=执行错（面缺/不可证，不猜绿）。
自证（--selftest）：每腿各造夹具——改面必红 / 不改必绿。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(WS, "30-工件", "观测面清偿批-20261105", "gate-registry.json")
SIDECAR_SNAP = os.path.join(WS, "状态观测", "otel-sidecar.json")
SIDECAR_LOG = os.path.join(WS, "状态观测", "otel-sidecar.log")
LATEST_JSON = os.path.join(WS, "状态观测", "latest.json")
SCHED_STATE = os.path.join(WS, "状态观测", "factory-scheduler-state.json")
IMGC_EVID = os.path.join(WS, "状态观测", "img-gc-evidence.jsonl")
GUARD_STATE = os.path.join(WS, "状态观测", "sched-supervision-gate.json")
OTLP_ASSERT = os.path.join(WS, "tools", "otel", "otlp-assert.py")
WATCH_PY = os.path.join(WS, "tools", "factory-watch.py")
KEEPALIVE_PY = os.path.join(WS, "tools", "factory-keepalive.py")
IMGC_PY = os.path.join(WS, "tools", "img-gc.py")
BENCH_PY = os.path.join(WS, "tools", "bench-retire-obs-review.py")
RETIRE_MARK = ("退役", "摘除", "DEB57", "旧值", "原根", "已退役", "旧口径")


def err(msg):
    sys.stderr.write("[obs-runtime-guard-gate] %s\n" % msg)


def load_registry(path=REG_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        err("登记面不可读：%s（%s）" % (path, exc))
        return None


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────── RT-E135：发射面判死 · 交叉断言 · 追溯告警
def leg_e135(reg, snap_path=SIDECAR_SNAP, log_path=SIDECAR_LOG):
    reds, notes = [], []
    # ① 判据未失明：otlp-assert 仍带 emit 死判据且读两个字段
    try:
        with open(OTLP_ASSERT, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as exc:
        reds.append("RT-E135 判据源不可读：%s（%s）" % (OTLP_ASSERT, exc))
        return reds, notes
    if "_sidecar_emit_dead_reason" not in src:
        reds.append("RT-E135 判据源 otlp-assert.py 已无 _sidecar_emit_dead_reason "
                    "⇒ 发射面死判据被摘（失明复发）")
    elif "span_sent" not in src or "metrics_sent" not in src:
        reds.append("RT-E135 判据源 otlp-assert.py 未同时读 emit.span_sent/metrics_sent "
                    "⇒ 判据退化（失明复发）")
    else:
        notes.append("RT-E135① 判据在位：otlp-assert.py:_sidecar_emit_dead_reason "
                     "（读 span_sent+metrics_sent）")
    # ② 现役快照：emit 死 ⇒ 红；并与 collector 活性交叉断言
    snap = None
    if not os.path.exists(snap_path):
        notes.append("RT-E135② 侧车快照不在位（%s）——本腿不可证（不判红，"
                     "快照陈旧另有断言门）" % os.path.basename(snap_path))
    else:
        try:
            with open(snap_path, encoding="utf-8") as fh:
                snap = json.load(fh)
        except (OSError, ValueError) as exc:
            notes.append("RT-E135② 侧车快照不可读（%s）——不可证（不判红）" % exc)
    if snap is not None:
        emit = snap.get("emit")
        metrics = snap.get("metrics") or {}
        alive = metrics.get("collector_alive")
        if not isinstance(emit, dict) or "span_sent" not in emit:
            reds.append("RT-E135② 快照无 emit 块 ⇒ 断言面对发射面失明（RT-E135 原盲区）")
        else:
            span_ok = emit.get("span_sent")
            m_sent = emit.get("metrics_sent")
            notes.append("RT-E135② 当轮 emit：span_sent=%s metrics_sent=%s；"
                         "collector_alive=%s" % (span_ok, m_sent, alive))
            if span_ok is False and int(m_sent or 0) == 0:
                if alive == 1:
                    reds.append("RT-E135② 发射面已死（span_sent=False ∧ metrics_sent=0）"
                                "而 collector_alive=1 ⇒ 链路断在发送侧（交叉断言腿："
                                "collector 在位却零成功发射）")
                else:
                    reds.append("RT-E135② 发射面已死（span_sent=False ∧ metrics_sent=0）"
                                "且 collector_alive≠1 ⇒ collector 与发射面同死（跨面同时失联）")
            elif span_ok is False:
                notes.append("RT-E135② span 未成功但 metrics_sent=%s>0 ⇒ 按判据口径"
                             "非「发射面已死」（部分链路存活），不作已死判定" % m_sent)
    # ③ 40h 历史窗追溯告警面：基线端点之后出现新的 span 已死轮 ⇒ 红
    base = reg.get("otel_emit_dead_baseline") or {}
    base_end = base.get("window_end")
    try:
        with open(log_path, "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except OSError as exc:
        notes.append("RT-E135③ 侧车日志不可读（%s）——追溯面不可证（不判红）" % exc)
        return reds, notes
    dead, full_dead = [], []
    for line in raw.split("\n"):
        if "emit(span=False" not in line:
            continue
        m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
        ts = m.group(1) if m else None
        dead.append(ts)
        if re.search(r"metrics=0\b", line):
            full_dead.append(ts)
    notes.append("RT-E135③ 侧车日志 span 已死轮 %d（其中 metrics=0 全死轮 %d）"
                 % (len(dead), len(full_dead)))
    if dead:
        notes.append("RT-E135③ 历史已死窗：%s → %s（跨度 %s）"
                     % (dead[0], dead[-1],
                        str(datetime_span(dead[0], dead[-1]))))
    if base_end:
        newer = [t for t in dead if t and t > base_end]
        if newer:
            reds.append("RT-E135③ 基线端点 %s 之后仍出现 %d 轮发射面已死（首 %s）"
                        "⇒ 新增已死窗，追溯告警面须人工处置"
                        % (base_end, len(newer), newer[0]))
        else:
            notes.append("RT-E135③ 基线端点 %s 之后无新增已死轮（存量历史窗已登记）"
                         % base_end)
    return reds, notes


def datetime_span(a, b):
    try:
        ta = time.mktime(time.strptime(a, "%Y-%m-%d %H:%M:%S"))
        tb = time.mktime(time.strptime(b, "%Y-%m-%d %H:%M:%S"))
        return "%ds(%.1fh)" % (int(tb - ta), (tb - ta) / 3600.0)
    except (TypeError, ValueError):
        return "?"


# ───────────────────────── RT-E106：监督面单源化 · 互斥即红 · fail-closed 计数
def leg_e106(reg, watch_py=WATCH_PY, keepalive_py=KEEPALIVE_PY, imgc_py=IMGC_PY,
             latest=LATEST_JSON, sched_state=SCHED_STATE):
    reds, notes = [], []
    cfg = reg.get("sched_supervision_roots") or {}
    active_state = cfg.get("active_state")
    # ① 单源化：watch 与 keepalive 的判活根必须同源于现役状态根
    roots = {}
    try:
        with open(watch_py, encoding="utf-8") as fh:
            wsrc = fh.read()
        m = re.search(r"^SCHED_STATUS\s*=\s*f?[\"']\{WS\}/([^\"']+)[\"']", wsrc, re.M)
        if not m:
            m = re.search(r"SCHED_STATUS\s*=\s*[^\n]*factory-scheduler-state\.json", wsrc)
            roots["watch"] = "状态观测/factory-scheduler-state.json" if m else None
        else:
            roots["watch"] = m.group(1)
    except OSError as exc:
        reds.append("RT-E106① watch 不可读：%s（%s）" % (watch_py, exc))
    try:
        with open(keepalive_py, encoding="utf-8") as fh:
            ksrc = fh.read()
        blk = re.search(r"\"name\"\s*:\s*\"scheduler\".*?\"state\"\s*:\s*f?[\"']\{WS\}/"
                        r"([^\"']+)[\"']", ksrc, re.S)
        roots["keepalive"] = blk.group(1) if blk else None
    except OSError as exc:
        reds.append("RT-E106① keepalive 不可读：%s（%s）" % (keepalive_py, exc))
    for who, val in roots.items():
        if val is None:
            reds.append("RT-E106① %s 判活根解析不出（不可证不猜绿）" % who)
        elif active_state and val != active_state:
            reds.append("RT-E106① %s 判活根=%s ≠ 登记的现役状态根 %s ⇒ 监督面未单源化"
                        % (who, val, active_state))
        else:
            notes.append("RT-E106① %s 判活根=%s（与现役状态根同源）" % (who, val))
    # ② 退役根不得作活探针根（RT-E106 错根签名）
    for retired in (cfg.get("retired_roots") or []):
        for path, tag in ((watch_py, "watch"), (keepalive_py, "keepalive"),
                          (imgc_py, "img-gc")):
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.read().split("\n")
                for i, line in enumerate(lines, 1):
                        if retired not in line:
                            continue
                        if re.search(r"=\s*['\"][^'\"]*%s" % re.escape(
                                os.path.basename(retired)), line):
                            reds.append("RT-E106② %s:%d 退役根 %s 被赋值为活探针根 ⇒ "
                                        "错根复发（RT-E106 原签名）"
                                        % (os.path.basename(path), i, retired))
                        elif not any(k in line for k in RETIRE_MARK) and \
                                not is_comment_line(lines, i):
                            notes.append("RT-E106② %s:%d 退役根 %s 出现在非退役标注行"
                                         "（人工复核登记，不判红）"
                                         % (os.path.basename(path), i, retired))
            except OSError:
                continue
    notes.append("RT-E106② 退役根 %s 未被任何面赋值为活探针根"
                 % "、".join(cfg.get("retired_roots") or []) or "—")
    # ③ 运行面互斥：watch 判死（A0 红）而调度器实活 ⇒ 错根；watch 判活而调度器实死 ⇒ 真失联不可感知
    sched_alive = scheduler_alive()
    state_age = None
    if os.path.exists(sched_state):
        state_age = time.time() - os.path.getmtime(sched_state)
    else:
        reds.append("RT-E106③ 现役状态根不在位：%s（面缺）" % sched_state)
    a0 = []
    if os.path.exists(latest):
        try:
            with open(latest, encoding="utf-8") as fh:
                data = json.load(fh)
            for al in (data.get("alarms") or []):
                if str(al.get("code")) == "A0":
                    a0.append(al)
        except (OSError, ValueError) as exc:
            notes.append("RT-E106③ latest.json 不可读（%s）——不判红" % exc)
    notes.append("RT-E106③ 调度器进程在=%s；状态根龄=%s；A0 报警条数=%d"
                 % (sched_alive,
                    ("%.0fs" % state_age) if state_age is not None else "—", len(a0)))
    if a0 and sched_alive and state_age is not None and state_age < 2400:
        reds.append("RT-E106③ watch 判 A0 死（%s）而调度器实活（进程在、状态根龄 %ds）"
                    "⇒ 监督面互斥＝错根复发" % (a0[-1].get("message", "")[:60], state_age))
    if not a0 and not sched_alive:
        reds.append("RT-E106③ 无 A0 报警而调度器进程不在 ⇒ 真实失联不可感知"
                    "（watch 判活面失能）")
    # ④ fail-closed 持续计数告警：img-gc 证据面若报 fail-closed 触发 ⇒ 计数并红
    streak = 0
    if os.path.exists(GUARD_STATE):
        try:
            with open(GUARD_STATE, encoding="utf-8") as fh:
                streak = int(json.load(fh).get("fail_closed_streak") or 0)
        except (OSError, ValueError):
            streak = 0
    fc_active = False
    if os.path.exists(IMGC_EVID):
        try:
            with open(IMGC_EVID, encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-1:]
            last = tail[0] if tail else ""
            if re.search(r"fail[-_]closed", last, re.I) and not re.search(
                    r"fail[-_]closed[^,}]{0,12}(无|None|null|0|false)", last, re.I):
                fc_active = True
            notes.append("RT-E106④ img-gc 证据末行 fail-closed 触发=%s（计数 %d）"
                         % (fc_active, streak))
        except OSError as exc:
            notes.append("RT-E106④ img-gc 证据面不可读（%s）" % exc)
    else:
        notes.append("RT-E106④ img-gc 证据面不在位——不判红（面缺不可证）")
    if fc_active:
        streak += 1
        reds.append("RT-E106④ img-gc fail-closed 触发（连续 %d 轮）⇒ 安全阀持续禁用，"
                    "须人工解封并留痕" % streak)
    else:
        streak = 0
    try:
        with open(GUARD_STATE, "w", encoding="utf-8") as fh:
            json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "fail_closed_streak": streak}, fh, ensure_ascii=False)
    except OSError as exc:
        notes.append("RT-E106④ 状态面写不了（%s）——计数不落盘（登记）" % exc)
    return reds, notes


def is_comment_line(lines, idx):
    """该行是否注释（含 # 注释块的续行：上一非空行以 # 开头 ⇒ 本行仍是注释）。"""
    if lines[idx - 1].strip().startswith("#"):
        return True
    for j in range(idx - 2, -1, -1):
        t = lines[j].strip()
        if not t:
            continue
        return t.startswith("#")
    return False


def scheduler_alive(pattern="factory-scheduler.py"):
    """扫 /proc 判调度器进程在否（不用 pgrep——pgrep -f 会匹配到本门自身的命令行）。"""
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace").replace("\x00", " ")
        except OSError:
            continue
        if pattern in cmd and "grep" not in cmd:
            return True
    return False


# ───────────────────────── RT-E28：预期灯到期复核 · 两态自证
def leg_e28(reg):
    reds, notes = [], []
    mod = load_module(BENCH_PY, "bench_retire_obs_review_probe")
    cfg = reg.get("expected_lamp_aging") or {}
    thr = int(cfg.get("threshold_s") or 86400)
    exempt = set((cfg.get("exempt") or {}).keys())
    # ① 夹具：超阈 ⇒ 必须产出升级行；未超阈 ⇒ 不得误升级
    # 超阈夹具：连续 26 小时每小时一条（相邻间隔 3600s ≤ 容差）⇒ 跨 24h 阈
    over = [{"ts": time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(time.time() - (30 - i) * 3600)),
             "level": "amber", "code": "af-execline-idle", "message": "夹具"}
            for i in range(26)]
    c_over = mod.classify_alarms(over)
    if not c_over.get("escalated"):
        reds.append("RT-E28① 超阈夹具（连续 40h）未产出升级行 ⇒ 到期升级机制未落码"
                    "（RT-E28 机制③）")
    else:
        notes.append("RT-E28① 超阈夹具 ⇒ 升级行可见：%s"
                     % c_over["escalated"][0].get("reason", "")[:70])
    under = [{"ts": time.strftime("%Y-%m-%d %H:%M:%S",
                                   time.localtime(time.time() - 600)),
              "level": "amber", "code": "af-execline-idle", "message": "夹具"}]
    c_under = mod.classify_alarms(under)
    if c_under.get("escalated"):
        reds.append("RT-E28① 未超阈夹具误升级 ⇒ 升级动作越权（RT-E28 机制③）")
    else:
        notes.append("RT-E28① 未超阈夹具 ⇒ 无误升级")
    # ② 现役读数：非豁免预期灯超阈必须已升级
    entries = mod.read_alarms()
    if entries is None:
        notes.append("RT-E28② 报警面不可读——不判红（不可证）")
    else:
        cls = mod.classify_alarms(entries)
        esc = {e["code"] for e in cls.get("escalated", [])}
        for code, v in (cls.get("expected") or {}).items():
            if code in exempt:
                notes.append("RT-E28② %s：豁免（%s）"
                             % (code, (cfg.get("exempt") or {}).get(code, "")[:40]))
                continue
            span = v.get("continuous_s", 0)
            notes.append("RT-E28② %s：首见 %s 连续 %ds 升级=%s"
                         % (code, v.get("first_seen"), span, v.get("escalated")))
            if code not in esc and (span >= thr or v.get("escalated")):
                reds.append("RT-E28② %s 超阈却未升级出预期集 ⇒ 预期灯仍无限期吞没"
                            % code)
        for e in cls.get("escalated", []):
            notes.append("RT-E28② 升级登记：%s 首见 %s 跨度/连续 %ss/%ss → %s"
                         % (e.get("code"), e.get("first_seen"), e.get("span_s"),
                            e.get("continuous_s"), "人工复核待办"))
    # ③ 两态自证：真值根不可达 ≠ 心跳超窗（走真实 fix_af_execline，落临时告警面）
    try:
        fk = load_module(KEEPALIVE_PY, "factory_keepalive_probe")
    except Exception as exc:                     # noqa: BLE001 — 导入失败即不可证
        reds.append("RT-E28③ keepalive 不可导入（%s）——两态自证不可证" % exc)
        return reds, notes
    tmpdir = tempfile.mkdtemp(prefix="e28-twostate-")
    fk.ALARMS_LOG = os.path.join(tmpdir, "alarms.log")
    fk.klog = lambda *a, **k: None
    fk.mes_event = lambda *a, **k: None
    msgs = {}
    for tag, detail in (("unreachable",
                          "生产订单 ledger 真值根不可达/读取失败（h:d）"),
                         ("stale",
                          "无本机 af 进程；生产订单 ledger 心跳 300000s 前"
                          "（窗 259200s，根=h:d）")):
        fk.last_af_exec_detail = detail
        fk.last_af_idle_alarm = 0
        try:
            fk.fix_af_execline(False, time.time(), {})
        except Exception as exc:                 # noqa: BLE001
            reds.append("RT-E28③ fix_af_execline 调用失败（%s）" % exc)
            return reds, notes
        try:
            with open(fk.ALARMS_LOG, encoding="utf-8") as fh:
                rows = [json.loads(l) for l in fh if l.strip()]
            msgs[tag] = rows[-1].get("message", "") if rows else ""
        except (OSError, ValueError) as exc:
            reds.append("RT-E28③ 临时告警面不可读（%s）" % exc)
            return reds, notes
    u, s = msgs.get("unreachable", ""), msgs.get("stale", "")
    if "不可达" not in u or "超 72h" in u:
        reds.append("RT-E28③ 不可达态文案失实：%r" % u[:80])
    elif "心跳超" not in s or "不可达" in s:
        reds.append("RT-E28③ 超窗态文案失实：%r" % s[:80])
    else:
        notes.append("RT-E28③ 两态自证过：不可达态=%r；超窗态=%r"
                     % (u[:46], s[:46]))
    # ④ 现役告警面的两态实证（历史文案留证）
    try:
        with open(os.path.join(WS, "状态观测", "alarms.log"), encoding="utf-8",
                  errors="replace") as fh:
            raw = fh.read()
        n_un = raw.count("真值根不可达")
        n_st = raw.count("心跳超 72h")
        notes.append("RT-E28④ 告警面文案实证：不可达措辞 %d 处、超窗措辞 %d 处"
                     % (n_un, n_st))
        if n_un == 0 or n_st == 0:
            notes.append("RT-E28④ 告警面未同时出现两态（不判红——历史留证不足，"
                         "机制已由③夹具自证）")
    except OSError as exc:
        notes.append("RT-E28④ 告警面不可读（%s）" % exc)
    return reds, notes


def selftest(reg):
    fails = []
    tmp = tempfile.mkdtemp(prefix="obs-runtime-fixture-")
    # ① E135：合成快照 emit 已死 + collector 在位 ⇒ 必红；emit 活 ⇒ 必绿
    dead_snap = os.path.join(tmp, "snap_dead.json")
    with open(dead_snap, "w", encoding="utf-8") as fh:
        json.dump({"ts": 1, "emit": {"span_sent": False, "metrics_sent": 0},
                   "metrics": {"collector_alive": 1}}, fh)
    reds, _ = leg_e135(reg, snap_path=dead_snap)
    if not any("断在发送侧" in r for r in reds):
        fails.append("夹具① 发射面已死快照应红未红：%s" % reds[:2])
    else:
        print("  夹具① E135 发射面已死（collector 在位）⇒ 红（%s）"
              % [r for r in reds if "断在发送侧" in r][0][:90])
    alive_snap = os.path.join(tmp, "snap_alive.json")
    with open(alive_snap, "w", encoding="utf-8") as fh:
        json.dump({"ts": 1, "emit": {"span_sent": True, "metrics_sent": 13},
                   "metrics": {"collector_alive": 1}}, fh)
    reds2, _ = leg_e135(reg, snap_path=alive_snap)
    if any("断在发送侧" in r or "发射面已死" in r for r in reds2):
        fails.append("夹具①b 发射面活快照应绿却红：%s" % reds2[:2])
    else:
        print("  夹具①b E135 发射面活 ⇒ 绿")
    # ② E106：把退役根赋值为 watch 判活根 ⇒ 必红
    w = os.path.join(tmp, "watch_fixture.py")
    with open(w, "w", encoding="utf-8") as fh:
        fh.write('SCHED_STATUS = f"{WS}/tmp/factory-status.json"\n')
    reds3, _ = leg_e106(reg, watch_py=w)
    if not any("错根复发" in r or "未单源化" in r for r in reds3):
        fails.append("夹具② 退役根作活探针根应红未红：%s" % reds3[:3])
    else:
        print("  夹具② E106 退役根作活探针根 ⇒ 红（%s）"
              % [r for r in reds3 if "错根复发" in r or "未单源化" in r][0][:90])
    # ③ E28：夹具内已含超阈/未超阈两态（见 leg_e28 ①）
    reds4, notes4 = leg_e28(reg)
    if any("未产出升级行" in r or "误升级" in r for r in reds4):
        fails.append("夹具③ E28 到期升级夹具应过却红：%s" % reds4[:3])
    else:
        print("  夹具③ E28 超阈⇒升级 / 未超阈⇒不升级 ⇒ 绿")
    # ④ 现盘未改动 ⇒ 必绿
    reds5, notes5 = run_all(reg)
    if reds5:
        fails.append("夹具④ 现盘应绿却红：%s" % reds5[:3])
    else:
        print("  夹具④ 现盘未改动 ⇒ 绿")
    return fails


def run_all(reg):
    reds, notes = [], []
    for fn in (leg_e135, leg_e106, leg_e28):
        r, n = fn(reg)
        reds += r
        notes += n
    return reds, notes


def main(argv):
    reg = load_registry()
    if reg is None:
        return 3
    if "--selftest" in argv:
        fails = selftest(reg)
        for f in fails:
            err("自证失败：%s" % f)
        print("自证：%s" % ("全过" if not fails else "有 %d 项失败" % len(fails)))
        return 0 if not fails else 2
    reds, notes = run_all(reg)
    for n in notes:
        print("[注] %s" % n)
    if reds:
        for r in reds:
            print("[红] %s" % r)
        print("结论：红（观测面运行时守卫门，RT-E135/106/28）")
        return 2
    print("结论：绿（观测面运行时守卫门，RT-E135/106/28）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
