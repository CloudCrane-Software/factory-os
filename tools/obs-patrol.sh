#!/usr/bin/env bash
# obs-patrol.sh — G7 接线：巡检观测脚本。
#
# 职责（只读，不碰任何测量语义）：对 $AF_OBS_ROOT/runs 下「最近 $PATROL_HOURS 小时
# 新增/变动」的 events.jsonl 逐个跑 obs-checker.py，按流分桶并汇总 PASS/FAIL 行，
# 全部输出追加到 $PATROL_LOG（默认 工具状态备份/observability/patrol.log），
# 同时打到 stdout（tee），cron 里把 stdout 另引一份即可。
#
# 分桶口径（2026-10-22 对齐 obs-checker.py 撞名修复后的绑定语义：索引=(run_id,path)
# 联合键精确绑定、manifest=归属 scope (line,arm)、聚合只数本 scope 索引行；
# 本脚本直接复用 checker 的绑定函数，判据同源不漂移）：
#   PASS      = 已按 (run_id,path) 联合键唯一入索引、manifest 归属本 scope 唯一且
#               checker rc=0
#   FAIL      = 同上但 checker rc≠0（真异常 → 安灯候选，FAIL 原因原样抄进日志；
#               联合键拒绑跨线同名陈旧行等归属明确的失败也走这里，FAIL 行自带归属信息）
#   AMBIGUOUS = 绑定本身不可判定的残余兜底：联合键多行命中 / 多份 manifest 同时归属本
#               scope 且均复算自洽 / 同 scope 内 run_id 重名致聚合仍被污染
#               → 照跑 checker 取诊断输出，但不计 PASS/FAIL，单列并标"归属存疑"
#   INFLIGHT  = 本流 path 未入索引且末行非 run_finished/correction（在飞/未收尾）
#               → 按 obs-checker 入参形态 (c) 的既有口径（setup_failed/无观测流按跳过不判
#                 fail），本脚本同样不判 fail，只记账
#
# 退出语义（2026-11-03 修复：候选=0/根缺失此前一律退出 0=绿——死馈/空馈/根被删三态
# 与巡检正常不可区分，2026-10-24 08:17 起事件馈死亡后 patrol.log 连报 236+ 轮
# 「候选=0 退出码=0」恒绿 10 天无人见）：
#   0 = 绿（有候选全过 / 候选=0 但馈活：根下最新事件流在 stale 阈内=正常静默）
#   1 = 红（FAIL/ERROR 候选——安灯候选，原因原样进日志）
#   2 = 执行错（checker 缺失 / runs 根缺失 / 候选发现失败 / 馈活性探查失败 / 分桶失败
#       ——不可证，不猜绿）
#   3 = 红（馈静默——安灯候选：空馈=根下零 events.jsonl；死馈=最新事件流已
#       > PATROL_STALE_HOURS 无新增且本窗候选=0）
#   4 = 馈线退役（2026-11-05 波次A5/C4 新增，仅空馈/死馈两分支可达）：扫描根挂
#       $PATROL_RETIRE_FILE（默认 $AF_OBS_ROOT/runs/FEED-RETIRED.json）且标注有效
#       （可解析 JSON ∧ status=retired）⇒ 空馈/死馈的红判据**挂起为显式 retired 态**
#       ——非绿（巡检未在巡该馈线）、非红（红态已由授权标注显式处置，安灯不再刷），
#       状态面记 status=retired 供消费面区分。标注缺失/坏/非法 ⇒ fail-closed 回
#       原空馈/死馈红（判据一字未删未弱化）。「静默但活」分支不受标注影响（馈活着
#       就照绿）。退役≠假绿：重接线＝删标注件即自动复巡。
# 状态面/报警面（2026-11-03 新增，巡检自身健康的机器消费通道——此前 cron >/dev/null、
# 退出码无消费者、全文无任何监测项覆盖本巡检自身）：
#   每轮终态原子写 状态观测/obs-patrol.json（status=ok/red/error + 计数 + 馈龄）；
#   status=red 时追加 状态观测/alarms.log（code=obs-feed-silent / obs-patrol-fail，
#   同一 red 事件不重复刷屏）。消费面=tools/obs-patrol-probe.py --check（all-gates L3
#   常驻门：末次判定红即红、读数过期即红=巡检停摆死手、缺件/坏 JSON/执行错 → rc=2
#   不可证不猜绿；与 otel-reconcile-probe --check 同构）。
#
# 环境变量（均有缺省）：AF_OBS_ROOT / OBS_CHECKER / PATROL_HOURS / PATROL_LOG /
#                     PATROL_LOCK / CHECK_TIMEOUT / PATROL_STALE_HOURS /
#                     PATROL_STATE / PATROL_ALARM_LOG
# 回滚 = 删本脚本 + 删 crontab 行（脚本不写任何 runs 观测数据、不改 tools/ 现役件；
#       状态面/报警面为本巡检自身健康的新增件，可删）。
set -uo pipefail

WS="/home/pan-ding/workspace/agent黑灯工厂"
AF_OBS_ROOT="${AF_OBS_ROOT:-$WS/工具状态备份/observability}"
OBS_CHECKER="${OBS_CHECKER:-$AF_OBS_ROOT/obs-checker.py}"
PATROL_HOURS="${PATROL_HOURS:-24}"
PATROL_LOG="${PATROL_LOG:-$AF_OBS_ROOT/patrol.log}"
PATROL_LOCK="${PATROL_LOCK:-$WS/tools/.obs-patrol.lock}"
CHECK_TIMEOUT="${CHECK_TIMEOUT:-180}"
PATROL_STALE_HOURS="${PATROL_STALE_HOURS:-48}"   # 馈活性阈：最新事件流超此小时数无新增且本窗候选=0 → 死馈（红）
PATROL_STATE="${PATROL_STATE:-$WS/状态观测/obs-patrol.json}"       # 状态面（门消费面读这里）
PATROL_ALARM_LOG="${PATROL_ALARM_LOG:-$WS/状态观测/alarms.log}"    # 报警面（red/retired 时追加，去重）
PATROL_RETIRE_FILE="${PATROL_RETIRE_FILE:-$AF_OBS_ROOT/runs/FEED-RETIRED.json}"  # 馈线退役标注（A5/C4）

NEWEST_AGE_H=""   # 馈龄（小时）；仅在候选=0 分支填
STATUS="ok"; ALARM_CODE="-"; STATE_MSG=""

# ---- 状态面（原子写）+ 报警面（red 去重追加）：巡检自身健康的机器消费通道 ----
emit_state() { # emit_state <status> <exit_code> <alarm_code> <message>
  python3 - "$PATROL_STATE" "$PATROL_ALARM_LOG" "$1" "$2" "$3" "$4" \
    "${NCAND:-0}" "${n_pass:-0}" "${n_fail:-0}" "${n_amb:-0}" "${n_inflight:-0}" "${n_err:-0}" \
    "$AF_OBS_ROOT" "$PATROL_HOURS" "$PATROL_STALE_HOURS" "$NEWEST_AGE_H" <<'PY' \
    || echo "obs-patrol: 状态面写入失败（见上）——退出码语义不受影响，但消费面将读到旧读数"
import json, os, sys, time

(state_file, alarm_log, status, exit_code, alarm_code, message,
 ncand, npass, nfail, namb, ninfl, nerr,
 root, window_h, stale_after_h, newest_age_h) = sys.argv[1:]


def atomic_write_json(path, obj):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


now = time.strftime("%Y-%m-%d %H:%M:%S")
st = {
    "ts": now,
    "ts_epoch": int(time.time()),
    "tool": "obs-patrol",
    "status": status,
    "exit_code": int(exit_code),
    "message": message,
    "counts": {"candidates": int(ncand), "pass": int(npass), "fail": int(nfail),
               "ambiguous": int(namb), "inflight": int(ninfl), "error": int(nerr)},
    "root": root,
    "window_h": float(window_h),
    "stale_after_h": float(stale_after_h),
    "newest_event_age_h": (float(newest_age_h) if newest_age_h != "" else None),
    "alarm_code": None if alarm_code == "-" else alarm_code,
}

prev = None
if os.path.exists(state_file):
    try:
        with open(state_file, "rb") as f:
            prev = json.load(f)
    except Exception:
        prev = None  # 旧读数坏掉不掩盖本轮判定
atomic_write_json(state_file, st)

if status in ("red", "retired") and alarm_code != "-":
    if prev and prev.get("status") == status and prev.get("alarm_code") == alarm_code:
        sys.exit(0)  # 已在报：同一 red/retired 事件不重复写（红牌去重，同 otel-reconcile 口径）
    rec = {"ts": now,
           "level": "red" if status == "red" else "notice",
           "code": alarm_code, "message": message, "since": now}
    d = os.path.dirname(alarm_log)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(alarm_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PY
}

mkdir -p "$(dirname "$PATROL_LOG")"
exec > >(tee -a "$PATROL_LOG") 2>&1

# ---- 单实例锁（cron 每小时一轮，人工可随时手跑；重叠则跳过，不排队）----
exec 9>"$PATROL_LOCK" || { echo "obs-patrol: 无法开锁文件 $PATROL_LOCK，退出"; exit 2; }
if ! flock -n 9; then
  echo "obs-patrol $(date -Is) | 已有实例在跑（lock=$PATROL_LOCK），本轮跳过"
  exit 0
fi

echo "=================================================================="
echo "=== obs-patrol 起 $(date '+%F %T') | as-of $(date -Is) | host=$(hostname) | window=${PATROL_HOURS}h"
echo "=== root=$AF_OBS_ROOT"
if [ ! -f "$OBS_CHECKER" ]; then
  echo "obs-patrol: checker 不存在：$OBS_CHECKER —— 本轮未跑（不是 PASS）"
  echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 | 退出码=2（checker 缺失）"
  emit_state error 2 - "checker 不存在：$OBS_CHECKER —— 执行错，不猜绿"
  exit 2
fi
echo "=== checker=$OBS_CHECKER sha256=$(sha256sum "$OBS_CHECKER" | cut -c1-16)"
if [ ! -d "$AF_OBS_ROOT/runs" ]; then
  echo "obs-patrol: 事件流根目录不存在：$AF_OBS_ROOT/runs —— 本轮未跑（不是 PASS；根被删/改名=执行错，2026-11-03 前此处恒绿）"
  echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 退出码=2（事件流根缺失）"
  emit_state error 2 - "事件流根目录不存在：$AF_OBS_ROOT/runs（根被删/改名）——执行错，不猜绿"
  exit 2
fi

# ---- 候选：最近 $PATROL_HOURS 小时内 mtime 变动过的 events.jsonl（按 mtime 升序）----
# 用临时文件而非进程替换：find 的退出码必须拿到——候选发现失败会伪装成"候选=0 全绿"。
CAND_RAW="$(mktemp "${PATROL_LOG}.raw.XXXXXX")"
CAND_LIST="$(mktemp "${PATROL_LOG}.list.XXXXXX")"
trap 'rm -f "$CAND_RAW" "$CAND_LIST" "${BUCKETS:-}"' EXIT
if ! find "$AF_OBS_ROOT/runs" -type f -name events.jsonl -mmin -"$((PATROL_HOURS * 60))" \
        -printf '%T@ %p\0' > "$CAND_RAW" 2>>"$PATROL_LOG"; then
  echo "obs-patrol: find 候选发现失败（见本节上方 stderr）——本轮未跑，不是 PASS"
  echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 退出码=2（候选发现失败）"
  emit_state error 2 - "候选发现失败：find 扫根失败（$AF_OBS_ROOT/runs）"
  exit 2
fi
sort -z -n "$CAND_RAW" | tr '\0' '\n' | sed 's/^[0-9.]* //' > "$CAND_LIST"
CANDS=()
while IFS= read -r line; do
  [ -n "$line" ] && CANDS+=("$line")
done < "$CAND_LIST"

NCAND=${#CANDS[@]}
echo "=== 候选事件流（${PATROL_HOURS}h 内新增/变动）=$NCAND"

if [ "$NCAND" -eq 0 ]; then
  # ---- 馈活性三态判别（2026-11-03 修复核心：候选=0 ≠ 恒绿）----
  # 用根下全部 events.jsonl 的最新 mtime 判馈面（无状态、重启安全、幂等）：
  #   空馈 empty = 根下一件 events.jsonl 都没有（馈未接线/扫描根指错）      → 退出 3
  #   死馈 dead  = 最新事件流 > PATROL_STALE_HOURS 无新增（2026-10-24 起本根
  #              即此态，此前恒绿 10 天）                                  → 退出 3
  #   静默 quiet = 最新事件流在阈内（工厂合理停工期，不警）                → 退出 0
  NEWEST_T=""
  # %T@ 必须带 \n 分隔：无分隔符会把多件 mtime 拼成一串不可解析长数字（2026-11-03
  # 本修复首版实跑即中招——python float 抛错 → FEED 空 → 静默落「静默但活」恒绿，
  # 与本修复要堵的事故同型；现 find 失败与判别失败一律 exit 2 不可证，fail-closed）
  if ! NEWEST_T="$(find "$AF_OBS_ROOT/runs" -type f -name events.jsonl -printf '%T@\n' \
                      2>>"$PATROL_LOG" | sort -n | tail -1)"; then
    echo "obs-patrol: 馈活性探查失败（find 失败，见本节上方 stderr）——本轮未跑，不是 PASS"
    echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 退出码=2（馈活性探查失败）"
    emit_state error 2 - "馈活性探查失败：find 扫根失败（$AF_OBS_ROOT/runs）"
    exit 2
  fi
  FEED="$(NEWEST_T="$NEWEST_T" PATROL_STALE_HOURS="$PATROL_STALE_HOURS" python3 - <<'PY'
import os, sys, time

newest = os.environ.get("NEWEST_T", "").strip()
stale_h = float(os.environ.get("PATROL_STALE_HOURS", "48"))
if not newest:
    print("empty\t0.00")
    raise SystemExit
age_h = (time.time() - float(newest)) / 3600.0
print(("dead\t%.2f" if age_h > stale_h else "quiet\t%.2f") % age_h)
PY
)"
  FEED_STATE="${FEED%%$'\t'*}"
  NEWEST_AGE_H="${FEED#*$'\t'}"
  case "$FEED_STATE" in
    empty|dead|quiet) ;;                       # 三态合法
    *)
      echo "obs-patrol: 馈活性判别失败（FEED=$FEED）——本轮未跑，不是 PASS（不猜绿）"
      echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 退出码=2（馈活性判别失败）"
      emit_state error 2 - "馈活性判别失败：判别器输出不可识别（FEED=$FEED）"
      exit 2
      ;;
  esac
  # ---- 馈线退役标注（A5/C4，仅空馈/死馈两态可达；「静默但活」不受标注影响）----
  # fail-closed：标注缺件/坏 JSON/status!=retired/缺关键字段 ⇒ RETIRE=INVALID ⇒
  # 落原空馈/死馈红（判据一字未删未弱化，不猜绿不猜退役）。
  RETIRE="INVALID"
  if [ "$FEED_STATE" = "empty" ] || [ "$FEED_STATE" = "dead" ]; then
    RETIRE="$(RETIRE_FILE="$PATROL_RETIRE_FILE" python3 - <<'PY'
import json, os, sys
p = os.environ.get("RETIRE_FILE", "")
try:
    with open(p, "rb") as f:
        m = json.loads(f.read().decode("utf-8", "replace"))
    ok = (isinstance(m, dict) and m.get("status") == "retired"
          and m.get("feed") in (None, "runs") and m.get("since")
          and m.get("reason") and m.get("semantics", {}).get("reactivation"))
except Exception:
    ok = False
print("VALID" if ok else "INVALID")
PY
)"
  fi
  if { [ "$FEED_STATE" = "empty" ] || [ "$FEED_STATE" = "dead" ]; } \
     && [ "$RETIRE" = "VALID" ]; then
    STATE_MSG="馈线退役：$AF_OBS_ROOT/runs 馈线按 $PATROL_RETIRE_FILE 标注显式退役（非绿、非在巡；空馈/死馈红判据挂起，判据本身未删——删标注件即自动复巡）；本窗馈面=${FEED_STATE}（最新事件流 ${NEWEST_AGE_H}h 前）"
    echo "obs-patrol: $STATE_MSG"
    echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 馈面=退役(${FEED_STATE}) | 退出码=4（馈线退役——判定面已标注）"
    emit_state retired 4 obs-feed-retired "$STATE_MSG"
    exit 4
  fi
  if [ "$FEED_STATE" = "empty" ]; then
    STATE_MSG="空馈：扫描根 $AF_OBS_ROOT/runs 下零 events.jsonl——事件馈未接线或扫描根指错（生产事件流实际落点需人工核对）——安灯候选"
    echo "obs-patrol: $STATE_MSG"
    echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 馈面=空馈 | 退出码=3（馈静默——安灯候选）"
    emit_state red 3 obs-feed-silent "$STATE_MSG"
    exit 3
  fi
  if [ "$FEED_STATE" = "dead" ]; then
    STATE_MSG="死馈：扫描根 $AF_OBS_ROOT/runs 下最新事件流已 ${NEWEST_AGE_H}h 无新增（>阈 ${PATROL_STALE_HOURS}h）且本 ${PATROL_HOURS}h 窗候选=0——事件馈死亡或扫描根与生产事件流实际落点失配——安灯候选"
    echo "obs-patrol: $STATE_MSG"
    echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 馈面=死馈（最新事件流 ${NEWEST_AGE_H}h 前） | 退出码=3（馈静默——安灯候选）"
    emit_state red 3 obs-feed-silent "$STATE_MSG"
    exit 3
  fi
  STATE_MSG="候选=0 但馈活：根下最新事件流 ${NEWEST_AGE_H}h 前有新增（≤阈 ${PATROL_STALE_HOURS}h）——正常静默，不警"
  echo "=== 汇总: 候选=0 PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 馈面=静默但活（最新事件流 ${NEWEST_AGE_H}h 前 ≤阈 ${PATROL_STALE_HOURS}h） | 退出码=0"
  emit_state ok 0 - "$STATE_MSG"
  exit 0
fi

# ---- 分桶（python3 只做 JSON 归类，不改任何数据）----
# 判据与 obs-checker.py 同源：直接 import checker 模块，复用其 load_index_rows /
# find_manifests / line_arm_of / manifest_home_scopes / manifest_self_consistent
# 与主流程逐行同款的绑定逻辑，避免"巡检一套判据、checker 一套判据"漂移
# （旧判据按 run_id 首匹配/重名即 AMBIGUOUS，撞名修复后已过期）。
BUCKETS="$(mktemp "${PATROL_LOG}.cands.XXXXXX")"
python3 - "$AF_OBS_ROOT" "$OBS_CHECKER" "${CANDS[@]}" <<'PY' > "$BUCKETS"
import importlib.util
import json
import os
import sys

root, checker_path, cands = sys.argv[1], sys.argv[2], sys.argv[3:]

try:
    _spec = importlib.util.spec_from_file_location("obs_checker_mod", checker_path)
    oc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(oc)
except Exception as err:  # noqa: BLE001
    print("ERROR\t<classifier>\t无法载入 checker 模块 %s: %s" % (checker_path, err))
    sys.exit(3)

index_rows = oc.load_index_rows(root)
mans = oc.find_manifests(root)
mans_by_name = dict(mans)


def scoped_rows_of(scope):
    """归属 scope 的索引行（聚合范围，与 checker 主流程同口径）。"""
    if scope is None:
        return list(index_rows)
    return [(_n, r) for _n, r in index_rows if oc.line_arm_of(r.get("path") or "") == scope]


def first_event(path):
    """首个可解析事件（checker 同口径：run_id 取 run_started payload）。"""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        return ev if isinstance(ev, dict) else None
    return None


def last_kind(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as err:
        return None, str(err)
    for raw in reversed([x for x in data.split(b"\n") if x.strip()]):
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        if isinstance(ev, dict):
            return ev.get("kind", ""), None
    return "", None


def pick_manifest(rid, scope):
    """复刻 checker 的 manifest 绑定选择：归属 scope (line,arm) + 自洽挑选 + 回退路径。
    返回 (清单名 or None, 状态, 说明)。状态：
      ok         唯一归属本 scope 且复算自洽
      tie        多份清单同归属本 scope 且均自洽 → 归属不可判定
      incons     归属本 scope 但无一自洽（checker 绑首份，FAIL 行如实暴露）
      fallback   兄弟索引行缺失致无完整归属 scope 的回退绑定（missing_runs fail-closed）
      stale      含本 run 的清单均归属其他 scope（跨线陈旧清单，不误绑）
      none       无批次清单覆盖（checker 记 WARN）
      undecidable 事件流布局不可判定 scope（维持旧行为首匹配，不猜）"""
    cand = [(n, m) for n, m in mans if rid in (m.get("run_ids") or [])]
    if not cand:
        return None, "none", "无批次清单覆盖（checker 记 WARN）"
    if scope is None:
        return cand[0][0], "undecidable", "事件流布局不可判定 scope，维持旧行为取首个含本 run 的清单"
    homed = [
        (n, m)
        for n, m in cand
        if scope in oc.manifest_home_scopes(m.get("run_ids") or [], index_rows)
    ]
    if homed:
        good = [
            n for n, m in homed if oc.manifest_self_consistent(m, scoped_rows_of(scope))
        ]
        if len(good) > 1:
            return (
                good[0],
                "tie",
                "多份清单（%s）均归属本 scope 且复算自洽，归属不可判定"
                % " ; ".join(good[:4]),
            )
        if not good:
            return (
                homed[0][0],
                "incons",
                "清单 %s 归属本 scope 但 merkle/计数/status 复算不自洽"
                "（checker 绑定首份，FAIL 行如实暴露）" % homed[0][0],
            )
        return good[0], "ok", "清单 %s 归属本 scope 且复算自洽" % good[0]
    for n, m in cand:
        if oc.manifest_home_scopes(m.get("run_ids") or [], index_rows):
            continue
        if any(
            r.get("run_id") == rid and oc.line_arm_of(r.get("path") or "") == scope
            for _n, r in index_rows
        ):
            return (
                n,
                "fallback",
                "清单 %s 兄弟索引行缺失致无完整归属 scope，按回退路径绑定"
                "（missing_runs 照常 fail-closed）" % n,
            )
    return None, "stale", "含本 run 的清单均归属其他 scope（跨线陈旧清单，不误绑）"


for p in cands:
    ap = os.path.abspath(p)
    ev = first_event(ap)
    rid = None
    if isinstance(ev, dict) and ev.get("kind") == "harness.run_started":
        payload = ev.get("payload")
        if isinstance(payload, dict):
            rid = payload.get("run_id")

    # 索引绑定：(run_id, path) 联合键——path 是写侧钉在本索引行里的本流绝对路径。
    exact = [r for _n, r in index_rows if r.get("run_id") == rid and r.get("path") == ap]
    by_path = [r for _n, r in index_rows if r.get("path") == ap]

    if len(exact) > 1:
        print("AMBIGUOUS\t%s\t(run_id,path) 联合键命中 %d 行（%s）：索引侧归属不可判定"
              % (p, len(exact), " ; ".join(sorted({r.get("path", "") for r in exact})[:4])))
        continue
    if not exact:
        if by_path:
            print("CHECK\t%s\t索引行 run_id=%s 与本流 run_id=%r 不符（联合键未命中，"
                  "checker 将 FAIL 暴露）" % (p, by_path[0].get("run_id"), rid))
            continue
        kind, err = last_kind(ap)
        if err is not None:
            print("ERROR\t%s\t读取失败: %s" % (p, err))
            continue
        if kind in ("harness.run_finished", "harness.correction"):
            print("CHECK\t%s\t已收尾但索引无对应行（漏登记/索引被删）" % p)
        else:
            print("INFLIGHT\t%s\t未入索引且末行 kind=%s（在飞/未收尾，不判 fail）"
                  % (p, kind or "不可解析"))
        continue

    scope = oc.line_arm_of(ap)
    if scope is None:
        scope = oc.line_arm_of(exact[0].get("path") or "")
    mname, mstate, mnote = pick_manifest(rid, scope)

    # 同 scope 聚合污染：被绑清单的任一 run_id 在本 scope 有多行索引
    # → merkle/Σevent_count/status_counts 仍会双重计数（撞名修复的已知残余，见交付 §6.5）。
    polluted = []
    if mname is not None:
        body = mans_by_name.get(mname) or {}
        for r in (body.get("run_ids") or []):
            if len([1 for _n, row in scoped_rows_of(scope) if row.get("run_id") == r]) > 1:
                polluted.append(r)
    if polluted:
        print("AMBIGUOUS\t%s\t同 scope 内 run_id 重名（%s）：merkle/计数聚合仍会被双重计数"
              % (p, " ; ".join(sorted(set(polluted))[:4])))
        continue
    if mstate == "tie":
        print("AMBIGUOUS\t%s\t%s" % (p, mnote))
        continue
    print("CHECK\t%s\t已按 (run_id,path) 联合键入索引；%s" % (p, mnote))
PY
cls_rc=$?
# 分类器自身失败（bug/权限/JSON 解析炸）必须显式暴露：静默 0/0 会被误读成"全绿"。
if [ "$cls_rc" -ne 0 ] || [ ! -s "$BUCKETS" ]; then
  echo "obs-patrol: 分桶失败（classifier rc=$cls_rc，桶文件行数=$(wc -l < "$BUCKETS")）——本轮未跑，不是 PASS"
  echo "=== 汇总: 候选=$NCAND PASS=0 FAIL=0 AMBIGUOUS=0 INFLIGHT=0 ERROR=0 | 退出码=2（分桶失败）"
  emit_state error 2 - "分桶失败：classifier rc=$cls_rc（桶文件行数=$(wc -l < "$BUCKETS")）"
  exit 2
fi

# ---- 逐流跑 checker ----
n_pass=0; n_fail=0; n_amb=0; n_inflight=0; n_err=0; rc_all=0
while IFS=$'\t' read -r bucket path reason; do
  [ -z "${bucket:-}" ] && continue
  short="${path#$AF_OBS_ROOT/}"
  case "$bucket" in
    INFLIGHT)
      n_inflight=$((n_inflight + 1))
      echo "--- [INFLIGHT] $short"
      echo "    理由: $reason"
      ;;
    ERROR)
      n_err=$((n_err + 1)); rc_all=1
      echo "--- [ERROR] $short"
      echo "    理由: $reason"
      ;;
    CHECK|AMBIGUOUS)
      out="$(timeout "$CHECK_TIMEOUT" python3 "$OBS_CHECKER" "$path" 2>&1)"
      rc=$?
      if [ "$bucket" = CHECK ]; then
        if [ "$rc" -eq 0 ]; then
          n_pass=$((n_pass + 1))
          echo "--- [PASS] $short"
        else
          n_fail=$((n_fail + 1)); rc_all=1
          echo "--- [FAIL] $short"
          echo "    理由: $reason；checker rc=$rc → 安灯候选"
        fi
      else
        n_amb=$((n_amb + 1))
        [ "$rc" -ne 0 ] && rc_all=1
        echo "--- [AMBIGUOUS] $short"
        echo "    理由: $reason；checker rc=$rc（诊断输出，绑定归属未定，不计 FAIL）"
      fi
      printf '%s\n' "$out" | grep -E '^\[obs-checker\] (汇总|/)|^  result:|^FAIL:|^WARN:|^  events=|^  sha256=' \
        | sed 's/^/    | /'
      ;;
    *)
      echo "--- [SKIP] $short （未知桶=$bucket）"
      ;;
  esac
done < "$BUCKETS"

[ "$n_fail" -gt 0 ] && echo "=== 提示: $n_fail 条流 checker 判 FAIL —— 安灯候选（原因见上方 FAIL 行）"
[ "$n_amb" -gt 0 ] && echo "=== 提示: $n_amb 条流绑定不可判定（联合键多行命中/多份清单同归属本 scope 且均自洽/同 scope 内 run_id 重名污染聚合）——安灯候选：先修索引/manifest 归属，再信 checker rc 判定"
echo "=== 汇总: 候选=$NCAND PASS=$n_pass FAIL=$n_fail AMBIGUOUS=$n_amb INFLIGHT=$n_inflight ERROR=$n_err | 退出码=$rc_all"
if [ "$rc_all" -ne 0 ]; then
  STATUS="red"; ALARM_CODE="obs-patrol-fail"
  STATE_MSG="巡检红：候选=$NCAND PASS=$n_pass FAIL=$n_fail AMBIGUOUS=$n_amb INFLIGHT=$n_inflight ERROR=$n_err——安灯候选（原因见 patrol.log 本轮 FAIL/ERROR 行）"
else
  STATUS="ok"; ALARM_CODE="-"
  STATE_MSG="巡检绿：候选=$NCAND PASS=$n_pass FAIL=$n_fail AMBIGUOUS=$n_amb INFLIGHT=$n_inflight ERROR=$n_err"
fi
emit_state "$STATUS" "$rc_all" "$ALARM_CODE" "$STATE_MSG"
echo "=== obs-patrol 止 $(date '+%F %T')"
exit "$rc_all"