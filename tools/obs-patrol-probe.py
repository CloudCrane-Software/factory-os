#!/usr/bin/env python3
"""obs-patrol-probe.py — G7 巡检 obs-patrol 自身健康/事件馈活性的机器消费者（门消费面）。

背景（2026-11-03 确证发现修复批）：tools/obs-patrol.sh（cron 每小时 :17 一轮）修复前
  ①退出语义三态不可区分：事件馈死亡/空馈/runs 根被删在退出码上全部=0（绿）——扫描根
    （工具状态备份/observability/runs）2026-10-24 08:17 起事件馈死亡，patrol.log 连报
    236+ 轮「候选=0 退出码=0」恒绿 10 天（2026-11-03 09:17/10:17/11:17 轮同）；
  ②巡检自身健康零监测项：cron 行 >/dev/null 2>&1、退出码无消费者、patrol.log 无人机读、
    目的-监测项映射全文无一行覆盖 obs-patrol——巡检停摆/馈死均「静默无人见」。

obs-patrol.sh 2026-11-03 修复后每轮终态原子写状态面 状态观测/obs-patrol.json
（status=ok/red/error + 计数 + 馈龄），status=red 时追加 状态观测/alarms.log
（code=obs-feed-silent / obs-patrol-fail，同 red 事件去重）。本件=该状态面的门消费面，
与 tools/otel/otel-reconcile-probe.py --check 同构（RT-E116「静默无人见」同族堵法）：

  check 模式（门姿势，零网络）——只读状态面，判三件事：
    ①在位可解析（缺件/坏 JSON/结构不可识别 → rc=2，不静默放行）；
    ②读数新鲜（mtime ≤ MAX_AGE_S=7200s=2 倍 cron 周期）——**巡检本身停摆即红**
      （死手断言：cron 死/脚本死/机器挂都将走到这，馈静默将再次无人见）；
    ③末次判定：status=red → rc=1（馈静默/checker FAIL 候选）；status=error → rc=2
      （执行错不可证）；status=ok → rc=0；status=retired → rc=4（2026-11-05 波次
      A5/C4 新增：馈线如实下线的显式消费态——授权标注在位时 obs-patrol 退出码 4
      落此态；rc=4 非绿非红：馈线不在巡（不许读成绿），红态已由授权标注显式处置
      （不再刷安灯）。retired 判据不挂起新鲜度死手：读数过期照旧 rc=1）。

  退役语义（C4，obs-patrol.sh 侧）：扫描根 runs/FEED-RETIRED.json 标注有效
  （可解析 ∧ status=retired ∧ 关键字段齐）时，空馈/死馈两分支的红挂起为
  retired（exit 4）；标注缺失/坏/非法 → fail-closed 回原红（判据未删未弱化）。
  重接线＝删标注件即自动复巡。

  selftest 模式：夹具自证（零网络零真树污染，临时目录），钉住消费语义映射
    （ok/红两码/执行错/过期死手/年龄不可得/不可识别状态 + 文件级缺件/坏 JSON/红态/
    过期/绿路对照）——防「门被改成恒红也能过」与「恒绿也能过」两向退化。

  gate 模式（2026-11-05 夜·obs-gate 退役态消费批）：all-gates L3 常驻项的入口。
    --check 的 rc=4（status=retired）在 all-gates 记账面只有「非零即红」一档
    （run_item 的 case 分支），而 rc=4 的设计语义是「非绿非红」——馈线按 A5/C4
    授权标注如实下线。门把该态记成一条无信息量的红（note 只有「rc=4：」），既掩了
    真红也训练人忽略门。--gate = --check 语义**加上** rc=4 的显式消费，且只认
    **独立复核过**的授权（fail-closed，四环全过才判 0）：
      ① 授权标注有效——合同与 tools/obs-patrol.sh 退役校验逐字同构（可解析 ∧
         status=retired ∧ feed∈{None,"runs"} ∧ since ∧ reason ∧
         semantics.reactivation）；
      ② 授权指得出来、读得到——标注 retired_by 点名的 .md 授权件在册且件内载明
         「退役/下线」（堵「自己写个标注就把安灯熄了」的自授权洞）；
      ③ 同根——状态面 root 与授权标注所在 observability 根一致；
      ④ 新鲜度死手未触发（judge_state 已判：retired 读数过期照旧 rc=1）。
    任一环不成立 ⇒ 1 红。判据一字未删未弱化：空馈/死馈红（obs-feed-silent）、
    巡检执行错、巡检停摆死手原样在；删标注件即自动复巡、照旧红。

退出码：0=绿 / 1=红（末次判定红 或 读数过期=巡检停摆死手）/ 2=不可证（缺件/坏 JSON/
执行错/判定不可识别）/ 4=馈线退役（status=retired：授权标注挂起空馈/死馈红的显式
消费态——非绿非红，读数过期仍 rc=1）。

gate 模式退出码：0=绿（含「授权退役态·非在巡」这一条显式绿路，四环独立复核全过）/
1=红（末次判定红、读数过期、或退役态授权四环任一环不过——fail-closed）/ 2=不可证。

纪律：本件只读状态面，**不复制 obs-patrol.sh 的巡检判据**（候选发现/分桶/checker 绑定
仍在脚本一处）；脚本侧判据变更只需自改并保持状态面字段契约（selftest 钉住）即不漂移。
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)                              # tools → 仓根
STATE_FILE = os.path.join(WS, "状态观测", "obs-patrol.json")
MARKER_FILE = os.path.join(WS, "工具状态备份", "observability", "runs",
                           "FEED-RETIRED.json")         # 同 obs-patrol.sh:64 缺省
MAX_AGE_S = 7200                                        # cron 每小时 :17 一轮 → 2 倍容差


def read_state(path=None):
    """→ (state|None, age_s|None, err|None)。缺件/坏 JSON/非对象 → (None, None, 原因)。"""
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


def judge_state(state, age_s, max_age_s=MAX_AGE_S):
    """状态面 → (rc, 文案)。纯函数（selftest 钉语义映射）。

    rc：0=绿 / 1=红（末次判定红 或 读数过期=巡检停摆死手）/ 2=不可证。
    口径：不可证不猜绿；读数过期判红（巡检本身停摆 = 本次事故形态「静默无人见」）。"""
    if age_s is None:
        return 2, "FAIL obs-patrol 状态面读数无年龄（stat 失败）——不可证，不猜绿"
    if age_s > max_age_s:
        return 1, ("FAIL obs-patrol 巡检读数过期：state_age=%.0fs > 阈 %ds——"
                   "巡检本身停摆（死手：cron 死/脚本死/机器挂都将走到这），"
                   "事件馈静默将再次无人见；末次 ts=%s 判定=%s"
                   % (age_s, max_age_s, state.get("ts"), state.get("status")))
    status = state.get("status")
    if status == "retired":
        # 2026-11-05 波次A5/C4：馈线「如实下线」的显式消费态——判定面标注已退役
        # （扫描根 FEED-RETIRED.json 授权在位，obs-patrol 退出码 4 落此态）。
        # 纪律：rc=4 既非绿（巡检未在巡该馈线）也非红（红态已由授权标注显式处置）；
        # 新鲜度死手在上（retired 读数过期＝巡检自身停摆，照旧 rc=1——退役挂起的
        # 只是空馈/死馈两分支，巡检自身健康判据不挂起）。
        return 4, ("RETIRED obs-patrol 馈线退役：末次判定=retired（code=%s）——"
                   "空馈/死馈红判据按授权标注挂起（非绿、非在巡）；末次 ts=%s，%s"
                   % (state.get("alarm_code") or "?",
                      state.get("ts"), state.get("message") or "原因未记"))
    if status == "error":
        return 2, ("FAIL obs-patrol 巡检执行错：末次判定不可证（%s）——不猜绿；"
                   "处置=看 patrol.log 本轮段与扫描根/checker 在位性"
                   % (state.get("message") or "原因未记"))
    if status == "red":
        return 1, ("FAIL obs-patrol 巡检红：末次判定=red（code=%s）：%s；末次 ts=%s，"
                   "root=%s 候选=%s"
                   % (state.get("alarm_code") or "?", state.get("message") or "",
                      state.get("ts"), state.get("root"),
                      (state.get("counts") or {}).get("candidates")))
    if status != "ok":
        return 2, ("FAIL obs-patrol 状态面判定不可识别：status=%r——不可证，不猜绿"
                   % (status,))
    c = state.get("counts") or {}
    return 0, ("PASS obs-patrol 巡检绿：末次判定=ok；state_age=%.0fs ≤ 阈 %ds；末次 ts=%s，"
               "候选=%s PASS=%s FAIL=%s（root=%s）"
               % (age_s, max_age_s, state.get("ts"), c.get("candidates"),
                  c.get("pass"), c.get("fail"), state.get("root")))


def check_state_file(path=None, max_age_s=MAX_AGE_S):
    """状态面文件 → (rc, 文案)（门消费面核心；只读文件、零网络）。

    rc：0=绿 / 1=红（末次判定红 或 读数过期=巡检停摆死手）/ 2=不可证（缺件/坏 JSON/
    执行错）。"""
    st, age, err = read_state(path)
    if st is None:
        return 2, ("FAIL obs-patrol 状态面缺件/不可用：%s——巡检从未跑过或状态面被删，"
                   "摘门必须显式红，不静默放行" % (err or "未知原因"))
    if err and age is None:
        return 2, "FAIL obs-patrol 状态面不可证：%s" % err
    return judge_state(st, age, max_age_s)


def read_json_file(path):
    """→ (obj|None, err|None)（只读文件、零网络）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read().decode("utf-8", "replace")
    except OSError as e:
        return None, "不可读：%s（%s）" % (path, e)
    try:
        return json.loads(raw), None
    except ValueError as e:
        return None, "坏 JSON：%s（%s）" % (path, e)


def marker_status(path):
    """馈线退役授权标注 → (有效?, 原因)。合同与 tools/obs-patrol.sh:230-238 逐字同构
    （fail-closed：缺件/坏 JSON/status!=retired/feed 不符/关键字段缺 ⇒ 无效——按无退役
    处理，空馈/死馈照旧红；不猜退役更不猜绿）。"""
    m, err = read_json_file(path)
    if m is None:
        return False, "授权标注不可证：%s" % err
    if not isinstance(m, dict):
        return False, "授权标注结构不可识别（非对象）：%s" % path
    if m.get("status") != "retired":
        return False, ("授权标注 status=%r != retired——按无退役处理（fail-closed）"
                       % (m.get("status"),))
    if m.get("feed") not in (None, "runs"):
        return False, ("授权标注 feed=%r 不属 runs 馈线（fail-closed）"
                       % (m.get("feed"),))
    missing = [k for k in ("since", "reason") if not m.get(k)]
    if not (m.get("semantics") or {}).get("reactivation"):
        missing.append("semantics.reactivation")
    if missing:
        return False, ("授权标注缺关键字段：%s——授权不可证（fail-closed）"
                       % "、".join(missing))
    return True, "授权标注有效（status=retired 且关键字段齐）"


def authorization_on_file(marker, path):
    """标注自带的 retired_by 授权出处 → (在册且载明退役?, 原因)。

    纪律：rc=4 的口径是「红态已由授权标注显式处置」——授权必须指得出来、读得到。
    只认 retired_by 里点名的 .md 件（工作区内相对路径或绝对路径）：件不在册、或件内
    不载「退役/下线」字样 ⇒ 不可证 ⇒ 红（堵「自己写个标注就把安灯熄了」的自授权洞）。
    """
    by = marker.get("retired_by") or ""
    cited = re.findall(r"[0-9A-Za-z一-龥_\-/\.]+\.md", by)
    if not cited:
        return False, ("retired_by 未指名任何 .md 授权件（%r）——授权不可证"
                       "（fail-closed：自授权洞）" % by)
    for c in cited:
        p = c if os.path.isabs(c) else os.path.join(WS, c)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                txt = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        if ("退役" in txt) or ("下线" in txt):
            return True, "授权件在册且载明退役/下线：%s" % c
        return False, ("授权件 %s 在册但不载「退役/下线」字样——授权不可证"
                       "（fail-closed）" % c)
    return False, ("retired_by 点名的授权件不在册：%s——授权不可证（fail-closed）"
                   % "、".join(cited))


def gate_check(state_path=None, marker_path=None, max_age_s=MAX_AGE_S):
    """all-gates L3 常驻项入口：--check 语义 + rc=4（授权退役态）的显式消费。

    rc：0=绿（含「授权退役态·非在巡」这一条显式绿路）/ 1=红（末次判定红、读数过期，
    或退役态授权四环任一环不过——fail-closed）/ 2=不可证。
    为什么需要本函数：--check 的 rc=4 设计语义是「非绿非红」，而 all-gates 记账面
    （run_item）只有「非零即红」一档 ⇒ 授权退役被记成无信息量的红（note 仅「rc=4：」），
    既掩真红也训练人忽略门。修法=把 rc=4 显式消费掉，且只认独立复核过的授权：
    标注有效（合同同 obs-patrol.sh:230-238）+ 授权件在册载明退役/下线 + 同根 +
    新鲜度死手未触发；任一环不过 ⇒ 1。判据一字未删未弱化（空馈/死馈红、执行错、
    停摆死手原样在；删标注件即自动复巡、照旧红）。
    """
    rc, msg = check_state_file(state_path, max_age_s)
    if rc != 4:
        return rc, msg                      # 0=绿 / 1=红 / 2=不可证：原样透传
    # rc=4 ⇒ judge_state 已判 retired 且读数新鲜（死手在上：过期照旧 rc=1，不挂起）
    st, age, _err = read_state(state_path)
    marker_path = marker_path or MARKER_FILE
    ok, why = marker_status(marker_path)
    if not ok:
        return 1, ("FAIL obs-patrol 退役态无有效授权标注：%s——rc=4 不可证，按红点名"
                   "（fail-closed，与 tools/obs-patrol.sh 退役校验同口径：标注缺/坏/"
                   "非法即回原红）" % why)
    marker, _e = read_json_file(marker_path)
    ok, why = authorization_on_file(marker, marker_path)
    if not ok:
        return 1, ("FAIL obs-patrol 退役态授权不可证：%s——按红点名（fail-closed："
                   "自授权洞不放开）" % why)
    root = (st or {}).get("root") or ""
    want_root = os.path.dirname(os.path.dirname(marker_path))   # .../observability
    if os.path.normpath(root) != os.path.normpath(want_root):
        return 1, ("FAIL obs-patrol 退役态不同根：状态面 root=%s 与授权标注所在根 %s "
                   "不一致——不可证，按红点名（fail-closed）" % (root, want_root))
    return 0, ("PASS obs-patrol 巡检绿（授权退役态·非在巡）：末次判定=retired"
               "（code=%s）；授权标注 %s 有效且授权件在册（%s）；state_age=%.0fs ≤ 阈 "
               "%ds（巡检自身健康死手未触发）；空馈/死馈红判据按授权标注挂起、未删未"
               "弱化（删标注件即自动复巡）——非活馈，勿读作馈线已修复"
               % ((st or {}).get("alarm_code") or "?", marker_path, why, age or -1,
                  max_age_s))


def selftest():
    """夹具自证：消费语义映射 + 文件级路径。零网络零真树污染（临时目录）。"""
    cases = [
        # (state, age_s, expect_rc, 场景)
        ({"ts": "2026-11-03 12:00:00", "status": "ok",
          "counts": {"candidates": 3, "pass": 3, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "巡检绿"}, 60, 0, "绿路（ok·有候选全过）"),
        ({"ts": "2026-11-03 12:00:00", "status": "ok",
          "counts": {"candidates": 0, "pass": 0, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "候选=0 但馈活"}, 60, 0,
         "绿路（ok·静默但馈活——候选=0 不再恒绿的对照面）"),
        ({"ts": "2026-11-03 12:00:00", "status": "red", "alarm_code": "obs-feed-silent",
          "counts": {"candidates": 0, "pass": 0, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "死馈：最新事件流 247.1h 无新增"}, 60, 1,
         "红=馈静默（死馈/空馈，obs-feed-silent）"),
        ({"ts": "2026-11-03 12:00:00", "status": "red", "alarm_code": "obs-patrol-fail",
          "counts": {"candidates": 2, "pass": 0, "fail": 2, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "巡检红：FAIL=2"}, 60, 1,
         "红=checker FAIL 候选（obs-patrol-fail）"),
        ({"ts": "2026-11-03 12:00:00", "status": "error",
          "counts": {"candidates": 0, "pass": 0, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "事件流根目录不存在"}, 60, 2,
         "执行错=不可证（不猜绿）"),
        ({"ts": "2026-11-03 09:00:00", "status": "ok",
          "counts": {"candidates": 1, "pass": 1, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs", "message": "巡检绿"}, 8000, 1,
         "读数过期=巡检停摆（死手红，>7200s=2 倍 cron 周期）"),
        ({"ts": "2026-11-03 09:00:00", "status": "ok", "counts": {}}, None, 2,
         "年龄不可得=不可证"),
        ({"ts": "2026-11-03 12:00:00", "status": "???", "counts": {}}, 60, 2,
         "判定不可识别=不可证"),
        ({"ts": "2026-11-05 14:00:00", "status": "retired",
          "alarm_code": "obs-feed-retired",
          "counts": {"candidates": 0, "pass": 0, "fail": 0, "ambiguous": 0,
                     "inflight": 0, "error": 0},
          "root": "/x/runs",
          "message": "馈线退役：FEED-RETIRED.json 标注有效（非绿、非在巡）"}, 60, 4,
         "退役态=rc=4（A5/C4 显式消费态：非绿非红，不留假绿）"),
        ({"ts": "2026-11-05 09:00:00", "status": "retired",
          "alarm_code": "obs-feed-retired", "counts": {}}, 8000, 1,
         "退役态读数过期=照旧 rc=1（新鲜度死手不挂起：退役≠巡检停摆的许可证）"),
    ]
    fails = []
    for i, (st, age, exp, why) in enumerate(cases):
        rc, _msg = judge_state(st, age)
        ok = rc == exp
        print("  case%d: %s → rc=%d（期望 %d）%s" % (i, why, rc, exp,
                                                    "PASS" if ok else "FAIL"))
        if not ok:
            fails.append((i, rc, exp))
    # 绿路对照：消费面在「绿态」不得红（防门被改成恒红也能过）
    rc, _ = judge_state({"status": "ok", "counts": {}}, 5)
    print("  control: 绿态消费 rc=%d（期望 0）%s" % (rc, "PASS" if rc == 0 else "FAIL"))
    if rc != 0:
        fails.append(("control", rc, 0))
    # 判别力对照：消费面在「红态」不得绿（防门被改成恒绿也能过——本次事故的镜像）
    rc, _ = judge_state({"status": "red", "alarm_code": "obs-feed-silent",
                         "counts": {}, "ts": "x"}, 5)
    print("  control: 红态消费 rc=%d（期望 1）%s" % (rc, "PASS" if rc == 1 else "FAIL"))
    if rc != 1:
        fails.append(("control-red", rc, 1))
    # 文件级路径（临时目录，零污染真树）：缺件 / 坏 JSON / 红态文件 / 过期文件 / 绿态文件
    import tempfile
    with tempfile.TemporaryDirectory(prefix="obs-patrol-probe-selftest-") as td:
        badp = os.path.join(td, "bad.json")
        redp = os.path.join(td, "red.json")
        greenp = os.path.join(td, "green.json")
        oldp = os.path.join(td, "old.json")
        missp = os.path.join(td, "missing.json")
        with open(badp, "w", encoding="utf-8") as f:
            f.write("{not json")
        with open(redp, "w", encoding="utf-8") as f:
            json.dump({"status": "red", "ts": "2026-11-03 12:00:00",
                       "alarm_code": "obs-feed-silent",
                       "counts": {"candidates": 0, "pass": 0, "fail": 0,
                                  "ambiguous": 0, "inflight": 0, "error": 0}}, f)
        with open(greenp, "w", encoding="utf-8") as f:
            json.dump({"status": "ok", "ts": "2026-11-03 12:00:00",
                       "counts": {"candidates": 1, "pass": 1, "fail": 0,
                                  "ambiguous": 0, "inflight": 0, "error": 0}}, f)
        with open(oldp, "w", encoding="utf-8") as f:
            json.dump({"status": "ok", "ts": "2026-11-03 09:00:00",
                       "counts": {"candidates": 1, "pass": 1, "fail": 0,
                                  "ambiguous": 0, "inflight": 0, "error": 0}}, f)
        old_ts = time.time() - 8000
        os.utime(oldp, (old_ts, old_ts))
        file_cases = [
            (missp, 2, "状态面缺件=不可证红（不静默放行）"),
            (badp, 2, "坏 JSON=不可证红"),
            (redp, 1, "红态文件=红"),
            (greenp, 0, "绿态文件=绿"),
            (oldp, 1, "过期文件=巡检停摆死手红"),
        ]
        for path, exp, why in file_cases:
            rc, _ = check_state_file(path)
            ok = rc == exp
            print("  file: %s → rc=%d（期望 %d）%s" % (why, rc, exp,
                                                      "PASS" if ok else "FAIL"))
            if not ok:
                fails.append(("file:" + why, rc, exp))
    gate_fails, n_gate = gate_selftest()
    fails.extend(gate_fails)
    if fails:
        print("SELFTEST FAIL: %d 项" % len(fails))
        return 1
    print("SELFTEST PASS: %d 语义用例 + 5 文件级用例 + %d gate 用例 + 绿/红两向对照"
          % (len(cases), n_gate))
    return 0


def gate_selftest():
    """gate 模式夹具自证（零网络零真树污染，临时目录）→ (fails, 用例数)。

    钉住两件事：① 退役态授权四环全过才绿（堵「自己写个标注就把安灯熄了」的自授权洞）；
    ② 非退役态原样透传——绿的就是绿的、红的就是红的、不可证的就是不可证的
    （退役消费不得顺手放宽别的判据）。"""
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory(prefix="obs-patrol-probe-gate-") as td:
        obs = os.path.join(td, "observability")
        runs = os.path.join(obs, "runs")
        os.makedirs(runs)
        statep = os.path.join(obs, "obs-patrol.json")
        markerp = os.path.join(runs, "FEED-RETIRED.json")
        docp = os.path.join(td, "A5-fixture.md")
        with open(docp, "w", encoding="utf-8") as f:
            f.write("# 夹具任务书\nC4 · 死馈重接线或如实下线（下线=改判定面标注「已退役」）\n")

        def write_state(status="retired", root=obs, stale=False):
            st = {"ts": "2026-11-05 20:17:02", "ts_epoch": 1793881022,
                  "tool": "obs-patrol", "status": status,
                  "exit_code": 4 if status == "retired" else 0,
                  "message": "夹具状态面",
                  "counts": {"candidates": 0, "pass": 0, "fail": 0,
                             "ambiguous": 0, "inflight": 0, "error": 0},
                  "root": root,
                  "alarm_code": "obs-feed-retired" if status == "retired" else "-"}
            with open(statep, "w", encoding="utf-8") as f:
                json.dump(st, f)
            if stale:
                old = time.time() - 8000
                os.utime(statep, (old, old))

        def write_marker(mut=None, raw=None):
            m = {"feed": "runs", "status": "retired", "marker_version": 1,
                 "since": "2026-11-05",
                 "retired_by": "波次 A5 施工员（外派任务书 %s 之 C4）" % docp,
                 "decision": "如实下线",
                 "reason": "夹具：扫描根 events.jsonl 上游无在役生产者",
                 "semantics": {"while_marker_valid": "挂起空馈/死馈红",
                               "reactivation": "删本件即自动复巡",
                               "fail_closed": "缺/坏/非法 ⇒ 回原红"}}
            if mut:
                mut(m)
            with open(markerp, "w", encoding="utf-8") as f:
                f.write(raw if raw is not None else json.dumps(m))

        def drop(m, k):
            m.pop(k, None)

        rows = []          # (场景, 期望 rc, 实测 rc)——即时取材即时判，见 report()

        def report(why, exp, rc):
            rows.append((why, exp, rc))
            ok = rc == exp
            print("  gate: %s → rc=%d（期望 %d）%s"
                  % (why, rc, exp, "PASS" if ok else "FAIL"))
            if not ok:
                fails.append(("gate:" + why, rc, exp))

        # ① 授权四环全过 ⇒ 绿（retired 显式消费态）
        write_state()
        write_marker()
        report("授权四环全过=绿（retired 显式消费态）", 0,
               gate_check(statep, markerp)[0])
        # ② 标注缺件 ⇒ 红（fail-closed 回原红）
        os.remove(markerp)
        report("授权标注缺件=红（fail-closed 回原红）", 1,
               gate_check(statep, markerp)[0])
        # ③ 标注坏 JSON ⇒ 红
        write_marker(raw="{not json")
        report("授权标注坏 JSON=红", 1, gate_check(statep, markerp)[0])
        # ④ status!=retired ⇒ 红（按无退役处理）
        write_marker(lambda m: m.update({"status": "active"}))
        report("标注 status!=retired=红（按无退役处理）", 1,
               gate_check(statep, markerp)[0])
        # ⑤ 缺 reason ⇒ 红
        write_marker(lambda m: drop(m, "reason"))
        report("标注缺 reason=红（关键字段不齐）", 1,
               gate_check(statep, markerp)[0])
        # ⑥ 缺 semantics.reactivation ⇒ 红
        write_marker(lambda m: m["semantics"].pop("reactivation"))
        report("标注缺 semantics.reactivation=红", 1,
               gate_check(statep, markerp)[0])
        # ⑦ feed 不属 runs ⇒ 红
        write_marker(lambda m: m.update({"feed": "other"}))
        report("标注 feed 不属 runs=红", 1, gate_check(statep, markerp)[0])
        # ⑧ 点名授权件不在册 ⇒ 红（自授权洞）
        write_marker(lambda m: m.update({"retired_by": "波次 A5（外派任务书 %s 之 C4）"
                                        % os.path.join(td, "no-such.md")}))
        report("retired_by 点名授权件不在册=红（自授权洞）", 1,
               gate_check(statep, markerp)[0])
        # ⑨ 授权件在册但不载退役/下线 ⇒ 红
        blandp = os.path.join(td, "bland.md")
        with open(blandp, "w", encoding="utf-8") as f:
            f.write("# 无关件\nnothing here\n")
        write_marker(lambda m: m.update({"retired_by": "施工员（%s）" % blandp}))
        report("授权件在册但不载退役/下线=红", 1, gate_check(statep, markerp)[0])
        # ⑩ retired_by 未指名 .md ⇒ 红
        write_marker(lambda m: m.update({"retired_by": "波次 A5 施工员"}))
        report("retired_by 未指名 .md 授权件=红", 1, gate_check(statep, markerp)[0])
        # ⑪ 状态面 root 与标注不同根 ⇒ 红
        write_marker()
        write_state(root=os.path.join(td, "other-root"))
        report("状态面 root 与标注不同根=红", 1, gate_check(statep, markerp)[0])
        # ⑫ retired 读数过期 ⇒ 红（停摆死手不挂起）
        write_state(stale=True)
        report("退役态读数过期=红（停摆死手不挂起）", 1,
               gate_check(statep, markerp)[0])
        # ⑬ 非退役态透传：ok=绿
        write_state(status="ok")
        report("非退役态透传：ok=绿", 0, gate_check(statep, markerp)[0])
        # ⑭ 非退役态透传：red=红
        write_state(status="red")
        report("非退役态透传：red=红", 1, gate_check(statep, markerp)[0])
        # ⑮ 状态面缺件 ⇒ 不可证红
        os.remove(statep)
        report("状态面缺件=不可证红", 2, gate_check(statep, markerp)[0])
    return fails, len(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description="obs-patrol 巡检健康/馈活性 门消费面")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="消费状态面（门姿势，零网络）")
    g.add_argument("--gate", action="store_true",
                   help="all-gates L3 常驻项入口：--check 语义 + rc=4 授权退役态"
                        "的显式消费（fail-closed 四环复核）")
    g.add_argument("--selftest", action="store_true", help="夹具自证（进 all-gates L3）")
    p.add_argument("--state", default=STATE_FILE, help="状态面路径（默认 %s）" % STATE_FILE)
    p.add_argument("--marker", default=MARKER_FILE,
                   help="馈线退役授权标注路径（默认 %s）" % MARKER_FILE)
    p.add_argument("--max-age", type=float, default=MAX_AGE_S,
                   help="读数新鲜阈秒（默认 %d=2 倍 cron 周期）" % MAX_AGE_S)
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.gate:
        rc, msg = gate_check(args.state, args.marker, args.max_age)
        print(msg)
        return rc
    rc, msg = check_state_file(args.state, args.max_age)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
