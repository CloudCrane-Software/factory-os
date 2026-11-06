#!/bin/bash
# cb-judge.sh <task.json> <model.patch> <outdir> — codebuddy 补丁本地判分（eval 镜像 + swev-judge）
# 口径：profile=deepseek-cb（codebuddy NPC harness + deepseek-v4.1-flash），与 af-harness 不混算。
# 坑（两次实证）：eval 镜像 /testbed 是合成 SWE-bench 提交，与上游 blob 不同，
# git apply（含 --3way）报 "does not match index" 拒收——必须 GNU patch -p1 --fuzz=3。
# 出参：$OUT/{apply.log,eval.log,judge.json}；judge.json 为 swev-judge.py 官方判定。
# 2026-10-21 修理组：加 pipefail——原先 swev-judge 崩掉时 `| tee` 吞 rc 返 0、judge.json
# 落 0 字节，上层 json.load 必炸且无法区分"应用失败(exit 2)"与"判分链错误(rc 1)"。
set -e
set -o pipefail
TASK_JSON="$1"; PATCH="$2"; OUT="$3"
IID=$(python3 -c "import json;print(json.load(open('$TASK_JSON'))['instance_id'])")
IMG=$(python3 -c "import json;print(json.load(open('$TASK_JSON'))['image'])")
CT=cbj-$(echo "$IID" | tr '__' '-')
mkdir -p "$OUT"
docker rm -f "$CT" >/dev/null 2>&1 || true
docker run -d --name "$CT" "$IMG" sleep infinity >/dev/null
trap 'docker rm -f "$CT" >/dev/null 2>&1' EXIT
# 1) 应用 model patch（GNU patch 模糊应用；合成提交 blob 对不上，git apply 拒收）
docker exec -i "$CT" bash -c 'cd /testbed && patch -p1 --fuzz=3 --no-backup-if-mismatch' < "$PATCH" > "$OUT/apply.log" 2>&1 || {
  echo APPLY_FAILED; tail -5 "$OUT/apply.log"; exit 2; }
# 2) 跑官方 eval_script（内含 test_patch 应用与 pytest）
python3 -c "import json,sys;sys.stdout.write(json.load(open('$TASK_JSON'))['eval_script'])" \
  | timeout 1250 docker exec -i "$CT" bash -s > "$OUT/eval.log" 2>&1 || true
# 3) 官方判分
/home/pan-ding/swev-venv/bin/python /home/pan-ding/workspace/agent黑灯工厂/tools/swev-judge.py "$TASK_JSON" "$OUT/eval.log" "$PATCH" | tee "$OUT/judge.json"
