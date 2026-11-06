#!/bin/bash
# zc-judge-collect.sh — zcode 官方 harness 对照线（step-5）：收集 patch → 容器判分 → 落账
#
# 口径：profile=zcode-step5 / scaffold=zcode-workflow（zcode 官方 agent 脚手架子代理产 patch，
#       本脚本吃 patch 走 cb-judge.sh 同一条已验证容器判分链），与 deepseek-cb / af-harness 不混算。
# 判分链（tools/cb-judge.sh，deepseek-cb 120/120 验证过）：sweb.eval 镜像容器 + GNU patch -p1
#       --fuzz=3 应用 + 官方 eval_script + swev-judge.py（swebench 4.1，含 xarray env-yml 合成兜底）。
# 约定路径：patch 在 /tmp/zc-ws/<instance_id>/model.patch（zc-prep-ws.py 预置，/tmp/zc-ws 是指向
#       /home/pan-ding/zc-ws 的符号链接）；题目 /tmp/swev-s1/<instance_id>.json。
# 落账：$OUTROOT/results.jsonl，字段仿 deepseek-cb 行（suite/task_id/profile/trial/reward/status/
#       scaffold/gate/attempts/turns/model_calls/tokens/agent_wall_ms/verifier_note）。
# 幂等断点续跑：某题已有 status=completed 的结果行即跳过；status=pending（image_missing/
#       judge_error）的题重跑本脚本自动重判。flock 防并发追加互踩。
# 用法：
#   zc-judge-collect.sh --one <instance_id> [solve_summary]   # 单题（工作流 world.run 调；
#                                                             # stdout 只打一行 RESULT <json>）
#   zc-judge-collect.sh --batch [D1|D2|D3|all]                # 批量串行补判（安静串行防 OOM 假失败）
#   zc-judge-collect.sh --status                              # 账目汇总
# 环境变量：ZC_OUTROOT（默认 /tmp/bench-official-zcode-step5）、ZC_WORK_ROOT（默认 /tmp/zc-ws）——
#       仅测试时覆写，勿在生产设置。
set -u
set -o pipefail

WS="/home/pan-ding/workspace/agent黑灯工厂"
NAMELIST="$WS/计划/s1-swev-120.json"
TASKS_DIR="/tmp/swev-s1"
JUDGE_SH="$WS/tools/cb-judge.sh"
OUTROOT="${ZC_OUTROOT:-/tmp/bench-official-zcode-step5}"
WORK_ROOT="${ZC_WORK_ROOT:-/tmp/zc-ws}"
RESULTS="$OUTROOT/results.jsonl"
PROFILE="zcode-step5"
SCAFFOLD="zcode-workflow"

mkdir -p "$OUTROOT"
touch "$RESULTS"

emit() {  # RESULT <json> 一行上 stdout，其余诊断全走 stderr
  echo "RESULT $1"
  echo "$2" >&2
}

# 结果行落账：$1=task_id $2=tier $3=reward(true/false) $4=gate $5=status $6=note $7=solve自报
record() {
  local tid="$1" tier="$2" reward="$3" gate="$4" status="$5" note="$6" solve="$7"
  python3 - "$RESULTS" "$tid" "$tier" "$reward" "$gate" "$status" "$note" "$solve" \
    "$PROFILE" "$SCAFFOLD" <<'PYEOF'
import json, sys, os, fcntl
path, tid, tier, reward, gate, status, note, solve, profile, scaffold = sys.argv[1:11]
line = {"suite": "swe-v", "task_id": tid, "profile": profile, "trial": False,
        "reward": reward == "true", "status": status, "scaffold": scaffold,
        "gate": gate, "attempts": 1, "turns": None, "model_calls": None,
        "tokens": None, "agent_wall_ms": None,
        "verifier_note": (note + ("; solve自报=" + solve if solve else "")).strip("; ")}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode())
finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
print(json.dumps({"task_id": tid, "tier": tier, "reward": reward == "true",
                  "gate": gate, "status": status}, ensure_ascii=False))
PYEOF
}

# 查某题是否已有终态（completed）行：有则跳过。stdout: existing|absent
already_done() {
  python3 - "$RESULTS" "$1" <<'PYEOF'
import json, sys
path, tid = sys.argv[1], sys.argv[2]
try:
    for ln in open(path, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if r.get("task_id") == tid and r.get("status") == "completed":
            print("existing")
            raise SystemExit
except FileNotFoundError:
    pass
print("absent")
PYEOF
}

tier_of() {
  python3 -c "import json,sys;tids={t['instance_id']:t['tier'] for t in json.load(open('$NAMELIST'))};print(tids.get('$1','?'))"
}

judge_one() {
  local iid="$1" solve="${2:-}"
  local tj="$TASKS_DIR/$iid.json"
  local work="$WORK_ROOT/$iid"
  local patch="$work/model.patch"
  local out="$OUTROOT/$iid"
  local tier; tier=$(tier_of "$iid")

  if [ "$(already_done "$iid")" = "existing" ]; then
    emit "{\"task_id\": \"$iid\", \"skipped\": true}" "SKIP $iid（已有 completed 结果行）"
    return 0
  fi
  if [ ! -f "$tj" ]; then
    record "$iid" "$tier" false "no_task_json" "pending" "题目 JSON 缺失（$tj），待补数据源" "$solve"
    emit "$(last_line)" "题目 JSON 缺失：$tj"; return 3
  fi
  # patch 缺失/空 → 模型没交卷，是真实结果（终态）
  if [ ! -s "$patch" ]; then
    record "$iid" "$tier" false "no_patch" "completed" \
      "模型未产出补丁（$patch 缺失或为空）；patch 路径约定 /tmp/zc-ws/<iid>/model.patch" "$solve"
    emit "$(last_line)" "no_patch：$iid"; return 0
  fi
  # 镜像在场检查（缺镜像不算模型失败，可重判）
  local img; img=$(python3 -c "import json;print(json.load(open('$tj'))['image'])")
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    record "$iid" "$tier" false "image_missing" "pending" \
      "eval 镜像不在本机（$img），镜像到位后重跑本脚本自动补判" "$solve"
    emit "$(last_line)" "image_missing：$iid"; return 3
  fi
  mkdir -p "$out"
  local rc=0
  # cb-judge 的 docker/eval 输出全落 collect.log，stdout 只留 RESULT 行给工作流解析
  bash "$JUDGE_SH" "$tj" "$patch" "$out" > "$out/collect.log" 2>&1 || rc=$?
  local jp="$out/judge.json"
  local judge=""
  if [ -s "$jp" ]; then
    judge=$(python3 -c "
import json,sys
try:
    j=json.load(open('$jp'))
    sys.stdout.write(json.dumps(j,ensure_ascii=False))
except Exception as e:
    sys.stdout.write('')
" 2>/dev/null)
  fi
  if [ "$rc" = "2" ]; then
    local tail; tail=$(tail -c 300 "$out/apply.log" 2>/dev/null | tr '\n' ' ')
    record "$iid" "$tier" false "apply_failed" "completed" \
      "cb-judge rc=2（补丁应用失败，GNU patch -p1 --fuzz=3 拒收）apply.log 尾部: $tail" "$solve"
    emit "$(last_line)" "apply_failed：$iid"; return 0
  fi
  if [ "$rc" = "0" ] && [ -n "$judge" ]; then
    # 判分字段一律从 judge.json 文件直读，JSON 不经 shell 二次插值（防引号/反斜杠炸参）
    local resolved synth
    resolved=$(python3 -c "import json,sys;print(str(bool(json.load(open(sys.argv[1]))['resolved'])).lower())" "$jp")
    synth=$(python3 -c "import json,sys;print('yes' if json.load(open(sys.argv[1])).get('env_yml_synthesized') else 'no')" "$jp")
    local snote=""
    [ "$synth" = "yes" ] && snote="; env_yml_synthesized（swev-judge 对老实例合成 environment.yml，判分语义零变化）"
    record "$iid" "$tier" "$resolved" "ok" "completed" \
      "judge: $judge; model=step-5-preview scaffold=zcode(官方工作流), patch=$patch(浅克隆@base_commit), 本地 sweb.eval+GNU patch fuzz 应用+官方 eval_script+swebench4.1 判分$snote; zcode线无token落账(tokens/turns恒null)" \
      "$solve"
    emit "$(last_line)" "ok：$iid resolved=$resolved"
    return 0
  fi
  record "$iid" "$tier" false "judge_error" "pending" \
    "cb-judge rc=$rc judge.json 缺失或空（判分链基础设施错误，非补丁问题），重跑自动重试" "$solve"
  emit "$(last_line)" "judge_error：$iid rc=$rc"; return 3
}

last_line() { tail -n 1 "$RESULTS" 2>/dev/null; }

cmd_status() {
  python3 - "$RESULTS" "$NAMELIST" <<'PYEOF'
import json, sys, collections
res, name = sys.argv[1], sys.argv[2]
tiers = {t["instance_id"]: t["tier"] for t in json.load(open(name, encoding="utf-8"))}
seen = {}
for ln in open(res, encoding="utf-8"):
    try:
        r = json.loads(ln)
    except json.JSONDecodeError:
        continue
    seen[r["task_id"]] = r  # 后行覆盖前行（重判以最新为准）
by = collections.defaultdict(lambda: [0, 0, 0])  # tier -> [completed, reward, pending]
for tid, r in seen.items():
    t = tiers.get(tid, "?")
    if r.get("status") == "completed":
        by[t][0] += 1
        by[t][1] += 1 if r.get("reward") else 0
    else:
        by[t][2] += 1
tc = collections.Counter(tiers.values())
for tier in ("D1", "D2", "D3"):
    c, w, p = by[tier]
    print(f"{tier}: 终态 {c}/{tc[tier]}，resolved {w}，待重判 {p}")
c = sum(v[0] for v in by.values()); w = sum(v[1] for v in by.values())
print(f"合计: 终态 {c}/120，resolved {w}（{w/c*100:.1f}% of 终态）" if c else "合计: 0/120")
PYEOF
}

case "${1:-}" in
  --one)
    [ -n "${2:-}" ] || { echo "用法: $0 --one <instance_id> [solve_summary]" >&2; exit 4; }
    judge_one "$2" "${3:-}"
    ;;
  --batch)
    filter="${2:-all}"
    python3 - "$NAMELIST" "$filter" <<'PYEOF' | while read -r iid; do
import json, sys
name, flt = sys.argv[1], sys.argv[2]
for t in json.load(open(name, encoding="utf-8")):
    if flt in ("all", t["tier"]):
        print(t["instance_id"])
PYEOF
      echo "== batch $iid $(date +%H:%M:%S)" >&2
      judge_one "$iid" || true
    done
    cmd_status
    ;;
  --status)
    cmd_status
    ;;
  *)
    sed -n '2,20p' "$0" >&2
    exit 4
    ;;
esac
