#!/usr/bin/env bash
# swev-warm-relay.sh — bench 判分缓存预热→跨机中继自动链（D-106 摩擦点①收编）。
#
# 为什么建（依据 30-工件/D-86-bench试跑-20261106/判分读数.md 六环表·摩擦点 1）：
#   · anolis 对 raw.githubusercontent.com 零直连（curl rc=000），判官件 v2 的
#     离线缓存在无网侧无从自建——每实例首次判分都依赖一次「有网侧预热」人工步，
#     判分腿不是零依赖自足。
#   · 与 D-67 扩池/镜像 relay 同址：本链产物统一落 anolis /data/bench/ 面
#     （默认 /data/bench/swev-judge-cache，与 swev-pool-cache 同址邻位），
#     判分腿经 SWEV_JUDGE_V2_CACHE 指向即用，避免每实例人工跨机步。
#
# 链路（每 task.json 五步，任一步败即 fail-closed：该实例后续步跳过、退出非零）：
#   ① 有网侧预热  swev-judge-v2.py --warm-cache（判官件自身预热口，判官件零改动）
#   ② 判官件对账  本侧与远端 swev-judge-v2.py sha256 逐字节对账（零改动判据面）；
#                 远端缺失则推本侧件；不一致 fail-closed 不覆盖
#   ③ 缓存中继    tar -C <cache> raw | ssh <remote> 'tar -C <remote-dir> -xf -'
#                 （条目=URL sha256 内容寻址、不可变；合并式，幂等可重跑）
#   ④ task 推送   task.json → <remote-dir>/tasks/<iid>.json
#   ⑤ 远端复用验证  远端离线跑 swev-spec-fetch.py（默认离线模式，禁外呼）：
#                 spec_ok=true 且 source=cache 且 live_http=[] ⇒ 判分腿可复用
#
# 用法:
#   swev-warm-relay.sh --task <task.json> [--task ...] [--out <readings.json>]
#                     [--remote anolis] [--remote-dir /data/bench/swev-judge-cache]
#                     [--cache-dir ~/.cache/swev-judge-v2] [--remote-py <py>]
#                     [--no-relay]
# 退出码: 0=全链绿；1=某步败（读数文件 step_fail 归因到步）。
# 读数: --out 落盘 JSON（先落盘再解析——判分读数.md 摩擦点 4 教训），
#       每实例每步 ok/detail/elapsed，detail 经 python json 构造（无手拼转义）。
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JUDGE="$SELF_DIR/swev-judge-v2.py"
FETCHER="$SELF_DIR/swev-spec-fetch.py"

TASKS=()
OUT=""
REMOTE="anolis"
REMOTE_DIR="/data/bench/swev-judge-cache"
CACHE_DIR="${SWEV_JUDGE_V2_CACHE:-$HOME/.cache/swev-judge-v2}"
NO_RELAY=0
LOCAL_PY="/home/pan-ding/swev-venv/bin/python3.14"
[ -x "$LOCAL_PY" ] || LOCAL_PY="python3"
REMOTE_PY="/home/pan-ding/swev-venv/bin/python3.14"

while [ $# -gt 0 ]; do
  case "$1" in
    --task) TASKS+=("$2"); shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
    --cache-dir) CACHE_DIR="$2"; shift 2 ;;
    --remote-py) REMOTE_PY="$2"; shift 2 ;;
    --no-relay) NO_RELAY=1; shift ;;
    *) echo "FAIL 未知参数 $1（用法见件头注释）" >&2; exit 1 ;;
  esac
done
[ ${#TASKS[@]} -gt 0 ] || { echo "FAIL 缺 --task <task.json>（至少一件）" >&2; exit 1; }

TMP="$(mktemp -d /tmp/swev-warm-relay.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
ANY_FAIL=0
LOG_NDJSON="$TMP/steps.ndjson"
: > "$LOG_NDJSON"

# 读数行追加：detail 经 python json.dumps 构造（杜绝手拼转义）
emit() {  # emit <instance> <step> <ok0/1> <elapsed_ms> <detail-file-or-"-">
  DET_FILE="$5"
  python3 - "$1" "$2" "$3" "$4" "$DET_FILE" "$LOG_NDJSON" <<'PY'
import json, sys, os
inst, step, ok, ms, df, nd = sys.argv[1:7]
detail = {}
if df != "-" and os.path.isfile(df):
    txt = open(df, encoding="utf-8", errors="replace").read()
    try:
        detail = json.loads(txt)
    except Exception:
        detail = {"raw": txt[:400]}
line = json.dumps({"instance": inst, "step": step, "ok": bool(int(ok)),
                   "elapsed_ms": int(ms), "detail": detail}, ensure_ascii=False)
with open(nd, "a", encoding="utf-8") as f:
    f.write(line + "\n")
print("    step[%s] ok=%s %sms" % (step, ok, ms))
PY
}

sha256_file() { sha256sum "$1" | cut -d' ' -f1; }

# ---- 链前自检：三件套在位 + 远端可达 ------------------------------------------
[ -f "$JUDGE" ]    || { echo "FAIL 判官件不在位 $JUDGE" >&2; exit 1; }
[ -f "$FETCHER" ]  || { echo "FAIL 取数件不在位 $FETCHER" >&2; exit 1; }
LOCAL_JUDGE_SHA="$(sha256_file "$JUDGE")"

RELAY=1
if [ "$NO_RELAY" -eq 1 ]; then
  RELAY=0
elif ssh -o ConnectTimeout=10 "$REMOTE" true 2>/dev/null; then
  RELAY=1
else
  echo "FAIL 远端 $REMOTE 不可达（预热仍可 --no-relay 只做本侧预热）" >&2
  exit 1
fi

for TASK in "${TASKS[@]}"; do
  IID="$("$LOCAL_PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["instance_id"])' "$TASK")"
  echo "=== [$IID] 预热→中继链 起（task=$TASK cache=$CACHE_DIR remote=$REMOTE:$REMOTE_DIR）"
  FAIL_STEP="none"

  # ① 有网侧预热（判官件自身 --warm-cache；产物=离线缓存含 404）
  WARM_T0=$(date +%s%3N)
  if SWEV_JUDGE_V2_CACHE="$CACHE_DIR" "$LOCAL_PY" "$JUDGE" --warm-cache "$TASK" \
      > "$TMP/warm.json" 2> "$TMP/warm.stderr"; then
    cp "$TMP/warm.json" "$TMP/warm.detail"
    WARM_OK=1
  else
    WARM_OK=0
    printf '{"warm":false}' > "$TMP/warm.detail"
    tail -c 400 "$TMP/warm.stderr" > "$TMP/warm.tailerr"
  fi
  WARM_MS=$(( $(date +%s%3N) - WARM_T0 ))
  if [ "$WARM_OK" -eq 1 ]; then
    emit "$IID" "1-warm-local" 1 "$WARM_MS" "$TMP/warm.detail"
  else
    cat "$TMP/warm.detail" "$TMP/warm.tailerr" > "$TMP/warm.detail2" 2>/dev/null || true
    python3 - "$TMP/warm.detail2" "$TMP/warm.stderr" <<'PY' || true
import json, sys
p, sp = sys.argv[1], sys.argv[2]
d = {}
try:
    d = json.loads(open(p, encoding="utf-8").read() or "{}")
except Exception:
    pass
d.setdefault("warm", False)
try:
    d["stderr_tail"] = open(sp, encoding="utf-8", errors="replace").read()[-300:]
except Exception:
    pass
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
PY
    emit "$IID" "1-warm-local" 0 "$WARM_MS" "$TMP/warm.detail2"
    FAIL_STEP="1-warm-local"
  fi
  echo "  ① 有网侧预热: warm=$WARM_OK ($WARM_MS ms)"

  # ② 判官件对账（远端已有则逐字节对账；缺失推本侧件；不一致 fail-closed 不覆盖）
  if [ "$RELAY" -eq 1 ] && [ "$WARM_OK" -eq 1 ] && [ "$FAIL_STEP" = "none" ]; then
    T2_0=$(date +%s%3N)
    R_SHA="$(ssh "$REMOTE" "sha256sum $REMOTE_DIR/swev-judge-v2.py 2>/dev/null | cut -d' ' -f1" || true)"
    if [ -z "$R_SHA" ]; then
      ssh "$REMOTE" "mkdir -p $REMOTE_DIR/raw $REMOTE_DIR/tasks"
      scp -q "$JUDGE" "$REMOTE:$REMOTE_DIR/swev-judge-v2.py"
      printf '{"action":"deployed","sha":"%s","reason":"remote缺失，已推本侧件"}' "$LOCAL_JUDGE_SHA" \
        > "$TMP/attest.detail"
      echo "  ② 判官件对账: 远端缺失→已部署本侧件（sha ${LOCAL_JUDGE_SHA:0:12}…）"
    elif [ "$R_SHA" = "$LOCAL_JUDGE_SHA" ]; then
      ssh "$REMOTE" "mkdir -p $REMOTE_DIR/raw $REMOTE_DIR/tasks"
      printf '{"action":"attested","sha":"%s"}' "$R_SHA" > "$TMP/attest.detail"
      echo "  ② 判官件对账: sha 一致（${LOCAL_JUDGE_SHA:0:12}…零改动判据面成立）"
    else
      printf '{"action":"mismatch","local":"%s","remote":"%s","reason":"sha不一致，fail-closed不覆盖"}' \
        "$LOCAL_JUDGE_SHA" "$R_SHA" > "$TMP/attest.detail"
      echo "  ② 判官件对账: FAIL sha 不一致（本 ${LOCAL_JUDGE_SHA:0:12}… 远 ${R_SHA:0:12}…）"
      FAIL_STEP="2-judge-attest"
    fi
    scp -q "$FETCHER" "$REMOTE:$REMOTE_DIR/swev-spec-fetch.py"
    emit "$IID" "2-judge-attest" "$([ "$FAIL_STEP" = "none" ] && echo 1 || echo 0)" \
      "$(( $(date +%s%3N) - T2_0 ))" "$TMP/attest.detail"
  fi

  # ③ 缓存中继（合并式 tar 管道；条目内容寻址不可变，幂等）
  if [ "$RELAY" -eq 1 ] && [ "$WARM_OK" -eq 1 ] && [ "$FAIL_STEP" = "none" ]; then
    T3_0=$(date +%s%3N)
    BEFORE="$(ssh "$REMOTE" "ls $REMOTE_DIR/raw 2>/dev/null | wc -l" | tr -d '[:space:]')"
    if tar -C "$CACHE_DIR" -cf - raw | ssh "$REMOTE" "tar -C $REMOTE_DIR -xf -"; then
      AFTER="$(ssh "$REMOTE" "ls $REMOTE_DIR/raw 2>/dev/null | wc -l" | tr -d '[:space:]')"
      printf '{"entries_before":%s,"entries_after":%s}' "$BEFORE" "$AFTER" > "$TMP/relay.detail"
      echo "  ③ 缓存中继: 远端条目 $BEFORE→$AFTER"
    else
      printf '{"reason":"tar/ssh 管道失败"}' > "$TMP/relay.detail"
      echo "  ③ 缓存中继: FAIL"
      FAIL_STEP="3-cache-relay"
    fi
    emit "$IID" "3-cache-relay" "$([ "$FAIL_STEP" = "none" ] && echo 1 || echo 0)" \
      "$(( $(date +%s%3N) - T3_0 ))" "$TMP/relay.detail"
  fi

  # ④ task 推送
  if [ "$RELAY" -eq 1 ] && [ "$WARM_OK" -eq 1 ] && [ "$FAIL_STEP" = "none" ]; then
    T4_0=$(date +%s%3N)
    if scp -q "$TASK" "$REMOTE:$REMOTE_DIR/tasks/$IID.json"; then
      printf '{"path":"%s"}' "$REMOTE_DIR/tasks/$IID.json" > "$TMP/push.detail"
      echo "  ④ task 推送: $REMOTE_DIR/tasks/$IID.json"
    else
      printf '{"reason":"scp 失败"}' > "$TMP/push.detail"
      echo "  ④ task 推送: FAIL"
      FAIL_STEP="4-task-push"
    fi
    emit "$IID" "4-task-push" "$([ "$FAIL_STEP" = "none" ] && echo 1 || echo 0)" \
      "$(( $(date +%s%3N) - T4_0 ))" "$TMP/push.detail"
  fi

  # ⑤ 远端复用验证（离线模式禁外呼：spec_ok ∧ source=cache ∧ live_http 空 ⇒ 可复用）
  if [ "$RELAY" -eq 1 ] && [ "$WARM_OK" -eq 1 ] && [ "$FAIL_STEP" = "none" ]; then
    T5_0=$(date +%s%3N)
    ssh "$REMOTE" \
      "SWEV_JUDGE_V2_CACHE=$REMOTE_DIR $REMOTE_PY $REMOTE_DIR/swev-spec-fetch.py \
       --quiet --out $REMOTE_DIR/tasks/$IID.verify.json $REMOTE_DIR/tasks/$IID.json" \
      > /dev/null 2> "$TMP/verify.stderr" || true
    scp -q "$REMOTE:$REMOTE_DIR/tasks/$IID.verify.json" "$TMP/verify.json" 2>/dev/null || true
    VERIFY_MS=$(( $(date +%s%3N) - T5_0 ))
    V5="$TMP/verify.json"
    if [ -s "$V5" ]; then
      V5_OK="$("$LOCAL_PY" -c 'import json,sys;d=json.load(open(sys.argv[1]));print(1 if d.get("spec_ok") else 0)' "$V5")"
      V5_SRC="$("$LOCAL_PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("source"))' "$V5")"
      V5_LIVE="$("$LOCAL_PY" -c 'import json,sys;print(len(json.load(open(sys.argv[1])).get("live_http") or []))' "$V5")"
      V5_ERR="$("$LOCAL_PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("error"))' "$V5")"
      V5_ERR="${V5_ERR:-none}"
    else
      V5_OK=0; V5_SRC="none"; V5_LIVE=-1; V5_ERR="verify.json 缺失（远端跑取数件失败）"
      cp "$TMP/verify.stderr" "$V5" 2>/dev/null || true
    fi
    if [ "$V5_OK" -eq 1 ] && [ "$V5_SRC" = "cache" ] && [ "$V5_LIVE" -eq 0 ]; then
      emit "$IID" "5-remote-verify" 1 "$VERIFY_MS" "$V5"
      echo "  ⑤ 远端复用验证: PASS（离线 source=cache 零外呼，$VERIFY_MS ms）"
    else
      printf '{"spec_ok":%s,"source":"%s","live_http":%s,"error":"%s"}' \
        "$V5_OK" "$V5_SRC" "$V5_LIVE" "$(printf %s "$V5_ERR" | tr -d '"')" > "$TMP/verify-fail.detail"
      emit "$IID" "5-remote-verify" 0 "$VERIFY_MS" "$TMP/verify-fail.detail"
      echo "  ⑤ 远端复用验证: FAIL（spec_ok=$V5_OK source=$V5_SRC live_http=$V5_LIVE）"
      FAIL_STEP="5-remote-verify"
    fi
  fi

  if [ "$FAIL_STEP" != "none" ]; then
    ANY_FAIL=1
    echo "=== [$IID] 链毕：FAIL（首败步=$FAIL_STEP）"
  else
    echo "=== [$IID] 链毕：全绿"
  fi
done

# ---- 读数落盘（先落盘再解析；判官件 sha 对账随 ② 步 detail 留痕） ----------------
RC=0
[ "$ANY_FAIL" -eq 0 ] || RC=1
if [ -n "$OUT" ]; then
  python3 - "$LOG_NDJSON" "$OUT" "${TASKS[0]}" "$ANY_FAIL" "$REMOTE" "$REMOTE_DIR" <<'PY'
import json, sys
nd, outp, first_task, any_fail, remote, rdir = sys.argv[1:7]
steps = [json.loads(l) for l in open(nd, encoding="utf-8") if l.strip()]
by = {}
for s in steps:
    by.setdefault(s["instance"], []).append(s)
report = {"tool": "tools/swev-warm-relay.sh",
          "task_file": first_task, "remote": remote, "remote_dir": rdir,
          "fail_step": next((s["step"] for s in steps if not s["ok"]), None),
          "all_ok": all(s["ok"] for s in steps),
          "instances": by}
with open(outp, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
    f.write("\n")
print("读数已落盘", outp, "all_ok=%s" % report["all_ok"])
PY
fi
if [ "$RC" -ne 0 ]; then
  echo "FAIL 链未全绿（读数见 ${OUT:-<未指定 --out>}）" >&2
fi
exit "$RC"
