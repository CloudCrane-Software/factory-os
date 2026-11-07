#!/usr/bin/env bash
# cb-judge-leg.sh — bench 判分腿一键链：收卷落定→warm-relay 自动预热中继→eval 出土→
#                    双容器判分（基线+判分）→判官件 verdict→判官件三方 sha 对账→回卡草案
#                    （D-120 · factory-os#127；D-86 摩擦①残余收编）。
#
# 为什么建（卡面现状段，实测读数）：
#   D-106 tools/swev-warm-relay.sh 五步链已在役（预热→判官件 sha 对账→缓存 tar 中继→
#   task 推送→远端离线复用验证），但它是判分前**人工触发的一步脚本**——D-86/107/117
#   三次判分腿各步（eval 出土用 dump_eval_sh 手工拷贝、docker 双容器、判官件调用、
#   回卡）都是子代理会话逐条手搓命令；判分腿本体不是零依赖自足，漏跑 relay 即起手
#   失败。本件把 D-117 实证链（30-工件/夜轨A2-20261107/判分读数.md §一–§八）固化为
#   一个 CLI：一条命令从收卷落定走到 verdict+回卡草案，零人工跨机步。
#
# 链路（八步，任一步败即 fail-closed：后续步跳过、退出非零、读数归因到步）：
#   0 leg-intake        收卷核：task/patch 在场+sha 记录；判官件仓内权威件 sha 记录
#                       （链前基线）；远端可达性；远端腿工作目录建立；task/patch
#                       部署（scp）。**判官件不落地腿目录**——判分腿消费注册表内
#                       缓存面对账件（judge-paths J2），本链零新增判官件部署拷贝
#                       （登记表只增不减纪律不被本链稀释；L2 扫描根不添未登记面）
#   1 warm-relay        自动触发 D-106 五步链（tools/swev-warm-relay.sh --task …）。
#                       **必经步，无跳过开关**——卡面待办③：漏跑 relay 的实例判分腿
#                       起手即 fail-closed 并给「先跑 warm-relay」归因（本链结构上
#                       不存在漏跑形态；relay 自身败也给同款归因+其读数文件坐标）。
#                       relay 第②步负责缓存面判官件对账/部署（缺失推本侧件）
#   2 eval-dump         远端出土官方 eval_script（tools/swev-eval-dump.py，guard 离线
#                       零外呼；live_http≠[] 即红；--judge=缓存面对账件）——
#                       D-86/107/117 三份 dump_eval_sh 手工拷贝收编为参数化单源件
#   3 baseline-ct       基线容器（无补丁）：docker run→cp eval.sh→timeout exec→日志留证
#                       （stdout+stderr 合流取回——判官件 markers 经 set -x xtrace
#                       走 stderr，D-117 实证形态；基线 F2P 红=题目本体，D-86 §二
#                       口径；判定语义归判官件）
#   4 judged-ct         判分容器（施补丁）：docker run→cp patch→git apply --verbose
#                       （官方 GIT_APPLY_CMDS 首档；apply 败=收卷面问题如实短路）→
#                       timeout exec→judged_log 取回（stdout+stderr 合流，同上）
#   5 verdict           判官件判分（缓存面对账件；SWEV_JUDGE_V2_CACHE=中继缓存面）：
#                       judge.json 落盘取回；hermetic/live_http 零外呼硬闸——
#                       hermetic≠true 或 live_http≠[] 即红（anolis 侧零外呼，卡面验收）
#   6 sha-tri-attest    判官件三方 sha256 对账：仓内链前实测＝仓内链后实测＝缓存面
#                       消费点实测（零改动判据面；任一不等即红）。本链对判官件只读
#                       +对账，结构上无写入路径、无新增部署拷贝；注册表期望值对账
#                       彰 judge-deploy-recon-gate.py（门本体，链外验收证据）
#   7 reply-draft       回卡草案（tools/cnb-verdict-reply.py --render，零板写零网络；
#                       --card 缺席则记 skipped 不计败）。--post-reply 才真贴板
#                       （cnb-verdict-reply.py --post；硬闸=调用环境已持回卡写板
#                       令牌环境量——本链零凭据读取路径，不代取不落盘不回显）
#
# 用法:
#   cb-judge-leg.sh --task <task.json> --patch <model.patch>
#                   [--card <issue 号>] [--debt <D-xxx>]
#                   [--remote anolis] [--remote-root /data/bench/D-120]
#                   [--cache /data/bench/swev-judge-cache]
#                   [--remote-py /home/pan-ding/swev-venv/bin/python3.14]
#                   [--eval-timeout 1500] [--out <readings.json>]
#                   [--post-reply]
# 退出码: 0=全链绿（skipped 步不计败）；1=某步败（读数 fail_step 归因到步）。
# 读数: --out 落盘 JSON（先落盘再解析——判分读数.md 摩擦点④教训）；逐步 NDJSON
#       经 python json 构造（无手拼转义）；judge 判定字段/sha 三方值随报告内嵌；
#       judge.json/warm-relay.json/reply-draft.md 落 --out 同目录。
# 纪律: 判官件/判据面零改动（只读+复制+对账）；判分判定语义归判官件本体，本链
#       不解读 F2P/P2P 明细（回卡只给计数——cnb-verdict-reply 渲染路径内置）；
#       凭据零 argv 零落盘（--post-reply 的 token 只经环境量现取）。
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
JUDGE_LOCAL="$REPO_ROOT/tools/swev-judge-v2.py"
RELAY="$SELF_DIR/swev-warm-relay.sh"
DUMPER="$SELF_DIR/swev-eval-dump.py"
REPLYER="$SELF_DIR/cnb-verdict-reply.py"

TASK="" PATCH="" CARD="" DEBT="" OUT=""
REMOTE="anolis"
REMOTE_ROOT="/data/bench/D-120"
CACHE="/data/bench/swev-judge-cache"
REMOTE_PY="/home/pan-ding/swev-venv/bin/python3.14"
EVAL_TIMEOUT=1500
POST_REPLY=0
LOCAL_PY="/home/pan-ding/swev-venv/bin/python3.14"
[ -x "$LOCAL_PY" ] || LOCAL_PY="python3"

while [ $# -gt 0 ]; do
  case "$1" in
    --task) TASK="$2"; shift 2 ;;
    --patch) PATCH="$2"; shift 2 ;;
    --card) CARD="$2"; shift 2 ;;
    --debt) DEBT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --remote-root) REMOTE_ROOT="$2"; shift 2 ;;
    --cache) CACHE="$2"; shift 2 ;;
    --remote-py) REMOTE_PY="$2"; shift 2 ;;
    --eval-timeout) EVAL_TIMEOUT="$2"; shift 2 ;;
    --post-reply) POST_REPLY=1; shift ;;
    *) echo "FAIL 未知参数 $1（用法见件头注释）" >&2; exit 1 ;;
  esac
done
[ -n "$TASK" ]  || { echo "FAIL 缺 --task <task.json>" >&2; exit 1; }
[ -n "$PATCH" ] || { echo "FAIL 缺 --patch <model.patch>（收卷落定的交卷物）" >&2; exit 1; }
[ -f "$TASK" ]  || { echo "FAIL task 不在位: $TASK" >&2; exit 1; }
[ -f "$PATCH" ] || { echo "FAIL patch 不在位: $PATCH" >&2; exit 1; }
for f in "$JUDGE_LOCAL" "$RELAY" "$DUMPER" "$REPLYER"; do
  [ -f "$f" ] || { echo "FAIL 链上件不在位: $f" >&2; exit 1; }
done
# task 必须是含 instance_id 的 JSON（预检快败；坏输入不进链、不留半程读数）
"$LOCAL_PY" -I -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert isinstance(d, dict) and d.get("instance_id"), "task.json 缺 instance_id"' \
  "$TASK" 2>/dev/null \
  || { echo "FAIL task 非 JSON 或缺 instance_id: $TASK" >&2; exit 1; }

TMP="$(mktemp -d /tmp/cb-judge-leg.XXXXXX)"
OUTDIR="$(mktemp -d /tmp/cb-judge-leg-out.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
ANY_FAIL=0
FAIL_STEP="none"
VERDICT="na"
LOG_NDJSON="$TMP/steps.ndjson"
: > "$LOG_NDJSON"

# 读数行追加：detail 经 python json 构造（杜绝手拼转义；swev-warm-relay 同款）
emit() {  # emit <step> <ok0/1> <elapsed_ms> <detail-file-or-"-">
  python3 -I - "$1" "$2" "$3" "$4" "$LOG_NDJSON" <<'PY'
import json, sys, os
step, ok, ms, df, nd = sys.argv[1:6]
detail = {}
if df != "-" and os.path.isfile(df):
    txt = open(df, encoding="utf-8", errors="replace").read()
    try:
        detail = json.loads(txt)
    except Exception:
        detail = {"raw": txt[:400]}
line = json.dumps({"step": step, "ok": bool(int(ok)),
                   "elapsed_ms": int(ms), "detail": detail}, ensure_ascii=False)
with open(nd, "a", encoding="utf-8") as f:
    f.write(line + "\n")
print("    step[%s] ok=%s %sms" % (step, ok, ms))
PY
}

record_fail() {  # record_fail <step> <detail-file> <归因句>
  emit "$1" 0 0 "$2" >/dev/null 2>&1 || true
  echo "FAIL [$1] $3" >&2
}
sha256_file() { sha256sum "$1" | cut -d' ' -f1; }

IID="$("$LOCAL_PY" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["instance_id"])' "$TASK")"
IID_TAG="$(printf '%s' "$IID" | tr '__' '-' | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9.-' '-')"
LEGDIR="$REMOTE_ROOT/$IID"
CT_BASE="d120-$IID_TAG-baseline"
CT_JUD="d120-$IID_TAG-judged"

echo "=== [$IID] bench 判分腿一键链 起（task=$TASK patch=$PATCH remote=$REMOTE legdir=$LEGDIR）"

# ---- 0 leg-intake：收卷核 + task/patch 腿目录部署（判官件不落地——只记链前 sha）---
T0=$(date +%s%3N)
INTAKE_OK=0
if ssh -o ConnectTimeout=10 "$REMOTE" true 2>/dev/null; then
  if ssh "$REMOTE" "mkdir -p $LEGDIR" \
      && scp -q "$TASK" "$REMOTE:$LEGDIR/task.json" \
      && scp -q "$PATCH" "$REMOTE:$LEGDIR/model_patch.diff"; then
    INTAKE_OK=1
  fi
fi
if [ "$INTAKE_OK" -eq 1 ]; then
  LOCAL_JUDGE_SHA="$(sha256_file "$JUDGE_LOCAL")"
  TASK_SHA="$(sha256_file "$TASK")"
  PATCH_SHA="$(sha256_file "$PATCH")"
  printf '{"instance_id":"%s","task_sha256":"%s","patch_sha256":"%s","judge_repo_sha_pre":"%s","leg_dir":"%s","judge_deploy":"cache-face-only（注册表 J2；本链零新增判官件拷贝）"}' \
    "$IID" "$TASK_SHA" "$PATCH_SHA" "$LOCAL_JUDGE_SHA" "$LEGDIR" > "$TMP/intake.detail"
  emit "0-leg-intake" 1 "$(( $(date +%s%3N) - T0 ))" "$TMP/intake.detail"
  echo "  ⓪ 收卷核: task=${TASK_SHA:0:12}… patch=${PATCH_SHA:0:12}… judge=${LOCAL_JUDGE_SHA:0:12}…（链前基线；判官件消费缓存面 J2，零新增部署拷贝）"
else
  printf '{"reason":"远端不可达或部署失败"}' > "$TMP/intake.detail"
  record_fail "0-leg-intake" "$TMP/intake.detail" "收卷核失败（远端 $REMOTE 可达性/腿目录部署/task+patch scp）"
  ANY_FAIL=1; FAIL_STEP="0-leg-intake"
fi

# ---- 1 warm-relay：自动触发 D-106 五步链（必经步，无跳过开关）----------------
if [ "$FAIL_STEP" = "none" ]; then
  T1=$(date +%s%3N)
  if bash "$RELAY" --task "$TASK" --out "$OUTDIR/warm-relay.json" \
      --remote "$REMOTE" --remote-dir "$CACHE" \
      > "$TMP/relay.stdout" 2> "$TMP/relay.stderr"; then
    RELAY_OK="$("$LOCAL_PY" -I -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("all_ok") else 0)' "$OUTDIR/warm-relay.json")"
    if [ "$RELAY_OK" = "1" ]; then
      cp "$OUTDIR/warm-relay.json" "$TMP/relay.detail"
      emit "1-warm-relay" 1 "$(( $(date +%s%3N) - T1 ))" "$TMP/relay.detail"
      echo "  ① warm-relay: 五步链全绿（内建自动触发，无人工步）"
    else
      printf '{"reason":"relay rc=0 但读数 all_ok≠true","relay_readings":"%s"}' "$OUTDIR/warm-relay.json" > "$TMP/relay.detail"
      record_fail "1-warm-relay" "$TMP/relay.detail" "relay 读数未全绿——先跑 warm-relay 查读数（tools/swev-warm-relay.sh；读数 $OUTDIR/warm-relay.json）"
      ANY_FAIL=1; FAIL_STEP="1-warm-relay"
    fi
  else
    printf '{"reason":"relay 非零退出","relay_readings":"%s"}' "$OUTDIR/warm-relay.json" > "$TMP/relay.detail"
    tail -c 300 "$TMP/relay.stderr" >> "$TMP/relay.detail" 2>/dev/null || true
    record_fail "1-warm-relay" "$TMP/relay.detail" "warm-relay 预热中继失败——先跑 warm-relay 查读数（tools/swev-warm-relay.sh；读数 $OUTDIR/warm-relay.json；判分腿无 relay 不起判）"
    ANY_FAIL=1; FAIL_STEP="1-warm-relay"
  fi
fi

# ---- 2 eval-dump：远端出土官方 eval_script（guard 离线零外呼）----------------
if [ "$FAIL_STEP" = "none" ]; then
  T2=$(date +%s%3N)
  DUMP_OK=0
  if scp -q "$DUMPER" "$REMOTE:$LEGDIR/swev-eval-dump.py" \
      && ssh "$REMOTE" "$REMOTE_PY -I $LEGDIR/swev-eval-dump.py \
          --task $LEGDIR/task.json --judge $CACHE/swev-judge-v2.py \
          --cache $CACHE --out $LEGDIR/eval.sh > $LEGDIR/eval-dump.json 2> $LEGDIR/eval-dump.stderr" \
      && scp -q "$REMOTE:$LEGDIR/eval-dump.json" "$TMP/eval-dump.detail"; then
    DUMP_OK=1
  fi
  if [ "$DUMP_OK" -eq 1 ]; then
    DUMP_LIVE="$("$LOCAL_PY" -I -c 'import json,sys;print(len(json.load(open(sys.argv[1])).get("live_http") or []))' "$TMP/eval-dump.detail")"
    if [ "$DUMP_LIVE" = "0" ]; then
      emit "2-eval-dump" 1 "$(( $(date +%s%3N) - T2 ))" "$TMP/eval-dump.detail"
      echo "  ② eval 出土: 零外呼（live_http=[]，远端 guard 离线）"
    else
      record_fail "2-eval-dump" "$TMP/eval-dump.detail" "出土 live_http=$DUMP_LIVE 非空——无网侧出土必须零外呼（先跑 warm-relay 灌中继缓存）"
      ANY_FAIL=1; FAIL_STEP="2-eval-dump"
    fi
  else
    scp -q "$REMOTE:$LEGDIR/eval-dump.stderr" "$TMP/eval-dump.detail" 2>/dev/null \
      || printf '{"reason":"远端出土失败且 stderr 取回失败"}' > "$TMP/eval-dump.detail"
    record_fail "2-eval-dump" "$TMP/eval-dump.detail" "eval 出土失败（缓存未命中/判官件载入失败）——先跑 warm-relay（tools/swev-warm-relay.sh）"
    ANY_FAIL=1; FAIL_STEP="2-eval-dump"
  fi
fi

# ---- 3 baseline-ct：基线容器（无补丁；基线红=题目本体，日志留证）--------------
IMG=""
if [ "$FAIL_STEP" = "none" ]; then
  T3=$(date +%s%3N)
  IMG="$("$LOCAL_PY" -I -c 'import json,sys;print(json.load(open(sys.argv[1])).get("image",""))' "$TASK")"
  BASE_OK=0
  if [ -n "$IMG" ] \
      && ssh "$REMOTE" "docker rm -f $CT_BASE >/dev/null 2>&1; docker run -d --name $CT_BASE $IMG sleep infinity >/dev/null" \
      && ssh "$REMOTE" "docker cp $LEGDIR/eval.sh $CT_BASE:/tmp/eval.sh" \
      && ssh "$REMOTE" "timeout $EVAL_TIMEOUT docker exec $CT_BASE bash /tmp/eval.sh > $LEGDIR/baseline_log.txt 2>&1; echo \$? > $LEGDIR/baseline.rc"; then
    BASE_OK=1
  fi
  if [ "$BASE_OK" -eq 1 ]; then
    BASE_RC="$(ssh "$REMOTE" "cat $LEGDIR/baseline.rc" | tr -d '[:space:]')"
    printf '{"container":"%s","image":"%s","eval_rc":"%s","log":"%s/baseline_log.txt"}' \
      "$CT_BASE" "$IMG" "$BASE_RC" "$LEGDIR" > "$TMP/baseline.detail"
    emit "3-baseline-ct" 1 "$(( $(date +%s%3N) - T3 ))" "$TMP/baseline.detail"
    echo "  ③ 基线容器: eval_rc=$BASE_RC（无补丁基线；F2P 基线红=题目本体，判定归判官件）"
  else
    printf '{"container":"%s","image":"%s","reason":"image 缺席或容器起/cp/exec 失败"}' \
      "$CT_BASE" "${IMG:-none}" > "$TMP/baseline.detail"
    record_fail "3-baseline-ct" "$TMP/baseline.detail" "基线容器腿失败（镜像在盘性/远端 docker 面）"
    ANY_FAIL=1; FAIL_STEP="3-baseline-ct"
  fi
fi

# ---- 4 judged-ct：判分容器（施补丁；git apply 官方首档）-----------------------
if [ "$FAIL_STEP" = "none" ]; then
  T4=$(date +%s%3N)
  RUN_OK=0
  if ssh "$REMOTE" "docker rm -f $CT_JUD >/dev/null 2>&1; docker run -d --name $CT_JUD $IMG sleep infinity >/dev/null" \
      && ssh "$REMOTE" "docker cp $LEGDIR/model_patch.diff $CT_JUD:/tmp/patch.diff" \
      && ssh "$REMOTE" "docker exec $CT_JUD bash -c 'cd /testbed && git apply --verbose /tmp/patch.diff' > $LEGDIR/apply.log 2>&1; echo \$? > $LEGDIR/apply.rc"; then
    RUN_OK=1
  fi
  if [ "$RUN_OK" -eq 1 ]; then
    APPLY_RC="$(ssh "$REMOTE" "cat $LEGDIR/apply.rc" | tr -d '[:space:]')"
    if [ "$APPLY_RC" = "0" ]; then
      EVAL_OK=0
      if ssh "$REMOTE" "docker cp $LEGDIR/eval.sh $CT_JUD:/tmp/eval.sh" \
          && ssh "$REMOTE" "timeout $EVAL_TIMEOUT docker exec $CT_JUD bash /tmp/eval.sh > $LEGDIR/judged_log.txt 2>&1; echo \$? > $LEGDIR/judged.rc"; then
        EVAL_OK=1
      fi
      if [ "$EVAL_OK" -eq 1 ]; then
        JUD_RC="$(ssh "$REMOTE" "cat $LEGDIR/judged.rc" | tr -d '[:space:]')"
        printf '{"container":"%s","apply_rc":0,"eval_rc":"%s","log":"%s/judged_log.txt"}' \
          "$CT_JUD" "$JUD_RC" "$LEGDIR" > "$TMP/judged.detail"
        emit "4-judged-ct" 1 "$(( $(date +%s%3N) - T4 ))" "$TMP/judged.detail"
        echo "  ④ 判分容器: apply_rc=0 eval_rc=$JUD_RC（官方 GIT_APPLY_CMDS 首档）"
      else
        printf '{"container":"%s","apply_rc":0,"reason":"eval exec 传输失败"}' "$CT_JUD" > "$TMP/judged.detail"
        record_fail "4-judged-ct" "$TMP/judged.detail" "判分容器 eval 执行失败（远端 docker/ssh 面）"
        ANY_FAIL=1; FAIL_STEP="4-judged-ct"
      fi
    else
      scp -q "$REMOTE:$LEGDIR/apply.log" "$TMP/apply.detail" 2>/dev/null \
        || printf '{"apply_rc":"%s"}' "$APPLY_RC" > "$TMP/apply.detail"
      record_fail "4-judged-ct" "$TMP/apply.detail" "补丁应用失败 rc=$APPLY_RC（收卷面问题如实短路；判分腿不抢救）"
      ANY_FAIL=1; FAIL_STEP="4-judged-ct"
    fi
  else
    printf '{"container":"%s","reason":"容器起/cp/git-apply 任一步失败"}' "$CT_JUD" > "$TMP/judged.detail"
    record_fail "4-judged-ct" "$TMP/judged.detail" "判分容器腿失败（镜像 $IMG 在盘性/远端 docker 面）"
    ANY_FAIL=1; FAIL_STEP="4-judged-ct"
  fi
fi

# ---- 5 verdict：判官件判分（腿目录部署件；hermetic/live_http 零外呼硬闸）------
if [ "$FAIL_STEP" = "none" ]; then
  T5=$(date +%s%3N)
  VERDICT_OK=0
  if ssh "$REMOTE" "cd $LEGDIR && SWEV_JUDGE_V2_CACHE=$CACHE $REMOTE_PY $CACHE/swev-judge-v2.py \
        task.json judged_log.txt model_patch.diff > judge.json 2> judge.stderr; echo \$? > judge.rc" \
      && scp -q "$REMOTE:$LEGDIR/judge.json" "$OUTDIR/judge.json"; then
    VERDICT_OK=1
  fi
  scp -q "$REMOTE:$LEGDIR/judge.stderr" "$OUTDIR/judge.stderr" 2>/dev/null || true
  if [ "$VERDICT_OK" -eq 1 ]; then
    JUDGE_RC="$(ssh "$REMOTE" "cat $LEGDIR/judge.rc" 2>/dev/null | tr -d '[:space:]' || true)"
    JUDGE_RC="${JUDGE_RC:-na}"
    if "$LOCAL_PY" -I - "$OUTDIR/judge.json" > "$TMP/verdict.detail" 2>/dev/null <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
keep = ("judge", "verdict", "resolved", "diff_valid", "log_state", "log_parsed",
        "f2p_success", "f2p_failure", "p2p_success", "p2p_failure",
        "hermetic", "live_http", "blocked_urls", "socket_connects",
        "swebench_version", "diff_sha256")
out = {k: d.get(k) for k in keep if k in d}
print(json.dumps(out, ensure_ascii=False))
PY
    then
      VERDICT="$("$LOCAL_PY" -I -c 'import json,sys;print(json.load(open(sys.argv[1])).get("verdict"))' "$TMP/verdict.detail")"
      emit "5-verdict" 1 "$(( $(date +%s%3N) - T5 ))" "$TMP/verdict.detail"
      echo "  ⑤ verdict: judge_rc=$JUDGE_RC verdict=$VERDICT（judge.json 已取回 $OUTDIR/judge.json）"
      V_HERM="$("$LOCAL_PY" -I -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("hermetic") else 0)' "$TMP/verdict.detail")"
      V_LIVE="$("$LOCAL_PY" -I -c 'import json,sys;print(len(json.load(open(sys.argv[1])).get("live_http") or []))' "$TMP/verdict.detail")"
      if [ "$V_HERM" != "1" ] || [ "$V_LIVE" != "0" ]; then
        printf '{"hermetic":"%s","live_http_n":"%s","reason":"anolis 侧零外呼硬闸红"}' \
          "$V_HERM" "$V_LIVE" > "$TMP/hermetic-gate.detail"
        record_fail "5-verdict-hermetic-gate" "$TMP/hermetic-gate.detail" "判分期外呼痕迹在场——先跑 warm-relay 灌缓存（tools/swev-warm-relay.sh）"
        ANY_FAIL=1; FAIL_STEP="5-verdict-hermetic-gate"
      fi
    else
      printf '{"reason":"judge.json 解析失败（判官件输出非 JSON）","judge_rc":"%s"}' "$JUDGE_RC" > "$TMP/verdict.detail"
      record_fail "5-verdict" "$TMP/verdict.detail" "judge.json 无法解析——判分输出面问题如实短路（stderr 见 $OUTDIR/judge.stderr）"
      ANY_FAIL=1; FAIL_STEP="5-verdict"
    fi
  else
    printf '{"reason":"判官件远端跑败或 judge.json 取回失败","stderr":"%s/judge.stderr"}' "$OUTDIR" > "$TMP/verdict.detail"
    record_fail "5-verdict" "$TMP/verdict.detail" "判官件判分失败——先跑 warm-relay 查缓存面对账（tools/swev-warm-relay.sh）"
    ANY_FAIL=1; FAIL_STEP="5-verdict"
  fi
fi

# ---- 6 sha-tri-attest：判官件三方 sha256 对账（仓内链前＝仓内链后＝缓存面消费点）--
if [ "$FAIL_STEP" = "none" ]; then
  T6=$(date +%s%3N)
  REPO_POST_SHA="$(sha256_file "$JUDGE_LOCAL")"
  CACHE_SHA="$(ssh "$REMOTE" "sha256sum $CACHE/swev-judge-v2.py 2>/dev/null | cut -d' ' -f1" || true)"
  TRI_OK=0
  [ -n "$REPO_POST_SHA" ] && [ "$REPO_POST_SHA" = "$LOCAL_JUDGE_SHA" ] \
    && [ -n "$CACHE_SHA" ] && [ "$CACHE_SHA" = "$LOCAL_JUDGE_SHA" ] && TRI_OK=1 || true
  printf '{"repo_pre":"%s","repo_post":"%s","cache_face":"%s","three_way_equal":%s,"registry_conformance":"judge-deploy-recon-gate.py（门本体，链外验收）"}' \
    "$LOCAL_JUDGE_SHA" "$REPO_POST_SHA" "${CACHE_SHA:-none}" \
    "$([ "$TRI_OK" = "1" ] && echo true || echo false)" > "$TMP/sha-tri.detail"
  if [ "$TRI_OK" -eq 1 ]; then
    emit "6-sha-tri-attest" 1 "$(( $(date +%s%3N) - T6 ))" "$TMP/sha-tri.detail"
    echo "  ⑥ 三方 sha 对账: 一致（${LOCAL_JUDGE_SHA:0:12}… 零改动判据面成立；缓存面=消费点）"
  else
    record_fail "6-sha-tri-attest" "$TMP/sha-tri.detail" \
      "判官件三方 sha 不一致（链前 ${LOCAL_JUDGE_SHA:0:12}… 链后 ${REPO_POST_SHA:-none} 缓存面 ${CACHE_SHA:-none}）——fail-closed 禁判"
    ANY_FAIL=1; FAIL_STEP="6-sha-tri-attest"
  fi
fi

# ---- 7 reply-draft：回卡草案（cnb-verdict-reply.py --render，零板写零网络）----
REPLY_SKIPPED=0
if [ "$FAIL_STEP" = "none" ]; then
  T7=$(date +%s%3N)
  if [ -z "$CARD" ]; then
    printf '{"skipped":"缺 --card（回卡需要卡号）；verdict 已落盘，本步不计败"}' > "$TMP/reply.detail"
    emit "7-reply-draft" 1 "$(( $(date +%s%3N) - T7 ))" "$TMP/reply.detail"
    REPLY_SKIPPED=1
    echo "  ⑦ 回卡草案: skipped（缺 --card；verdict 已落盘）"
  else
    REPLY_OK=0
    RENDER_ARGS=(--render --judge "$OUTDIR/judge.json" --issue "$CARD" --out "$OUTDIR/reply-draft.md")
    [ -n "$DEBT" ] && RENDER_ARGS+=(--debt "$DEBT")
    if python3 -I "$REPLYER" "${RENDER_ARGS[@]}" > "$TMP/reply.stdout" 2> "$TMP/reply.stderr"; then
      REPLY_OK=1
    fi
    if [ "$REPLY_OK" -eq 1 ]; then
      printf '{"issue":"%s","debt":"%s","draft":"%s","posted":%s}' \
        "$CARD" "${DEBT:-none}" "$OUTDIR/reply-draft.md" \
        "$([ "$POST_REPLY" = "1" ] && echo true || echo false)" > "$TMP/reply.detail"
      emit "7-reply-draft" 1 "$(( $(date +%s%3N) - T7 ))" "$TMP/reply.detail"
      echo "  ⑦ 回卡草案: $OUTDIR/reply-draft.md（render 零板写零网络）"
      if [ "$POST_REPLY" = "1" ]; then
        # 真贴板硬闸（凭据面与 cnb-verdict-reply --post 同一）：--post-reply 要求
        # **调用环境**已持回卡写板令牌环境量（运营侧先经 af-github-askpass 现取
        # 该环境量、再发车 cb-judge-leg.sh … --post-reply）。本链零凭据读取路径：
        # 不代取、不落盘、不回显、不经 argv——缺令牌环境量即拒写板（fail-closed），
        # 渲染草案已落盘可人工补贴。
        POST_OK=0
        if [ -n "${GH_TOKEN:-}" ] || [ -n "${GITHUB_TOKEN:-}" ]; then
          if python3 -I "$REPLYER" --post --judge "$OUTDIR/judge.json" --issue "$CARD" \
              ${DEBT:+"--debt"} ${DEBT:+"$DEBT"} \
              --out "$OUTDIR/reply-posted.md" >> "$TMP/reply.stdout" 2>> "$TMP/reply.stderr"; then
            POST_OK=1
          fi
        else
          printf '{"reason":"--post-reply 需调用环境已持回卡写板令牌环境量（本链零凭据读取路径，不代取）"}' \
            > "$TMP/reply-post.detail"
          record_fail "7-reply-post" "$TMP/reply-post.detail" \
            "回卡真写被拒：调用环境未持回卡令牌环境量（fail-closed；渲染草案已落盘，可现取后人工补贴）"
          ANY_FAIL=1; FAIL_STEP="7-reply-post"
        fi
        if [ "$POST_OK" -eq 1 ]; then
          echo "     回卡真写: 完成（POST 评论 + PUT state:*；渲染 $OUTDIR/reply-posted.md）"
        elif [ "$FAIL_STEP" != "7-reply-post" ]; then
          printf '{"reason":"--post 真写板失败（评论渲染已落盘，贴板面人工处置）"}' > "$TMP/reply-post.detail"
          record_fail "7-reply-post" "$TMP/reply-post.detail" "回卡真写板失败"
          ANY_FAIL=1; FAIL_STEP="7-reply-post"
        fi
      fi
    else
      printf '{"reason":"cnb-verdict-reply --render 失败"}' > "$TMP/reply.detail"
      record_fail "7-reply-draft" "$TMP/reply.detail" "回卡草案渲染失败（verdict 已落盘，回卡面可人工补）"
      ANY_FAIL=1; FAIL_STEP="7-reply-draft"
    fi
  fi
fi

# ---- 远端容器清理（任何退出路径都尽力收；禁占名僵尸容器）----------------------
ssh -o ConnectTimeout=10 "$REMOTE" \
  "docker rm -f $CT_BASE $CT_JUD >/dev/null 2>&1" >/dev/null 2>&1 || true

# ---- 读数落盘（先落盘再解析；判分读数.md 摩擦点④教训）------------------------
RC=0
[ "$ANY_FAIL" -eq 0 ] || RC=1
if [ -z "$OUT" ]; then OUT="$OUTDIR/leg-readings.json"; fi
python3 -I - "$LOG_NDJSON" "$OUT" "$TMP" "$IID" "$TASK" "$PATCH" \
  "$REMOTE" "$LEGDIR" "$CACHE" "$VERDICT" "$REPLY_SKIPPED" "${CARD:-none}" "${DEBT:-none}" <<'PY'
import json, os, sys
nd, outp, tmp, iid, task, patch, remote, legdir, cache, verdict, reply_skipped, card, debt = sys.argv[1:14]

def load(name):
    p = os.path.join(tmp, name)
    if os.path.isfile(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return None
    return None

steps = [json.loads(l) for l in open(nd, encoding="utf-8") if l.strip()]
fail_step = next((s["step"] for s in steps if not s["ok"]), None)
report = {
    "tool": "tools/cb-judge-leg.sh",
    "instance_id": iid,
    "task": task,
    "patch": patch,
    "remote": remote,
    "leg_dir": legdir,
    "cache": cache,
    "card": None if card == "none" else card,
    "debt": None if debt == "none" else debt,
    "fail_step": fail_step,
    "all_ok": all(s["ok"] for s in steps),
    "steps": steps,
    "intake": load("intake.detail"),
    "verdict_summary": load("verdict.detail"),
    "sha_tri": load("sha-tri.detail"),
    "reply": load("reply.detail"),
    "reply_skipped": bool(int(reply_skipped)),
    "verdict": verdict,
}
with open(outp, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
    f.write("\n")
print("读数已落盘 %s all_ok=%s fail_step=%s" % (outp, report["all_ok"], fail_step))
PY
if [ "$RC" -ne 0 ]; then
  echo "FAIL 判分腿未全绿（首败步=$FAIL_STEP；读数见 $OUT）" >&2
  exit "$RC"
fi
echo "=== [$IID] 判分腿链毕：全绿（verdict=$VERDICT 读数=$OUT judge=$OUTDIR/judge.json）"
exit 0
