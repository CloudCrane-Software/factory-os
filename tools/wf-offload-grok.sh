#!/usr/bin/env bash
# 外派执行器（grok 通道）：把一批活送到 anolis 上用 grok build CLI 跑。
#
# 背景（2026-11-05）：GLM 停用期内 anolis 的 zcode 无头 CLI 只有 glm 一条可用通道，
# 而 ~/.local/bin/grok 经本机 mihomo 代理（pandev-host.invalid:7890）可正常调 xAI
#（直连被断 ⇒ 必须带 HTTPS_PROXY/HTTP_PROXY，实测 2026-11-05 01:5x）。
# grok 不在模型配额停用清单内 ⇒ 它是停用期内 anolis 侧唯一可用的代理通道（第三档）。
#
# 用法
# ----
#   bash tools/wf-offload-grok.sh <brief.md> <remote-workdir> <label> <base-ref>
#
#   <brief.md>        任务书（自足；会被 --prompt-file 喂给 grok）
#   <remote-workdir>  anolis 上的工作目录（须已存在，通常是 ~/af-dev/af）
#   <label>           本批标签（工作树 wt/<label>、构建盘 /data/bench/targets/<label>）
#   <base-ref>        工作树基线（分支名/commit；复核批用待复核分支，施工批用 salvage/* 或 origin/product/main）
#
# 行为
# ----
#   · 在 anolis 的 <remote-workdir> 下建独立工作树 wt/<label>（基线 <base-ref>，flock 串行 fetch/建树）
#   · 任务书 scp 到 wt/<label>/.offload/<brief>
#   · 用 grok 跑：HTTPS_PROXY/HTTP_PROXY=http://pandev-host.invalid:7890，pty 形态，输出落 .offload/<label>.log
#   · 日志 rsync 回本机 30-工件/外派/<label>/
#   · 退出码：0 = grok 正常退出；非 0 = 失败或被中止
#
# 硬约束
# --------
#   · 禁 sudo；不碰本机工作流槽位计数（那是 wf-gate.py 的事，外派不占本机槽）
#   · 不删远端任何目录；只写 wt/<label>/.offload/ 与任务书指定的面
set -uo pipefail

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WF_OFFLOAD_WS="$WS"

REMOTE="${OFFLOAD_REMOTE:-anolis}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)

[ $# -ge 4 ] || { echo "用法: bash tools/wf-offload-grok.sh <brief.md> <remote-workdir> <label> <base-ref>"; exit 2; }
BRIEF="$1"; REMOTE_DIR="$2"; LABEL="$3"; BASE="$4"
[ -f "$BRIEF" ] || { echo "FAIL 任务书不存在：$BRIEF"; exit 2; }
case "$BRIEF" in /*) BRIEF_ABS="$BRIEF";; *) BRIEF_ABS="$WS/$BRIEF";; esac

OFFDIR_REL=".offload"
LOG_REL="$OFFDIR_REL/$LABEL.log"
WT_REL="wt/$LABEL"
WT_ABS="$REMOTE_DIR/$WT_REL"

echo "== 外派（grok 通道）：$LABEL =="
echo "   任务书：$BRIEF_ABS"
echo "   目标机：$REMOTE   基准工作目录：$REMOTE_DIR   基线：$BASE"

ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR/$OFFDIR_REL'" || { echo "FAIL 连不上 $REMOTE"; exit 3; }

# 建树（flock 串行化，与 wf-offload.sh 同款，避免并发 fetch 抢 ref 锁）
ssh "${SSH_OPTS[@]}" "$REMOTE" "cd '$REMOTE_DIR' && \
  flock '.git/wf-offload-fetch.lock' -c \"
    git fetch -q origin && \
    ([ -e '$WT_REL/.git' ] || git worktree add --detach '$WT_REL' '$BASE') && \
    mkdir -p '$WT_ABS/$OFFDIR_REL'\"" || { echo "FAIL 建独立工作树失败"; exit 3; }
echo "   独立工作树：$WT_ABS（基线：$BASE）"

# 构建盘
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '/data/bench/targets/$LABEL'" || echo "WARN 建独占构建盘失败（批次须自行用独占 CARGO_TARGET_DIR）"

# 任务书送过去
scp -q "${SSH_OPTS[@]}" "$BRIEF_ABS" "$REMOTE:$WT_ABS/$OFFDIR_REL/$(basename "$BRIEF_ABS")" || { echo "FAIL 任务书投递失败"; exit 3; }

# 出口口径（2026-11-05 13:0x 修正）：**不再写死本机 mihomo**。
#   事故：本脚本原写死 HTTPS_PROXY=http://pandev-host.invalid:7890（本机 mihomo）。2026-11-05
#   12:0x~13:0x 实测该出口对 xAI 全断（12 个节点对 cli-chat-proxy.grok.com 的 delay
#   探测全红，仅 1 个存活节点 curl 仍 000/502）⇒ 波次A 五批全部 486B reqwest 报错、
#   零产出、工作树零提交（此前误判为"在跑"，实为已死）。
#   现口径：优先用**远端自带的** /data/af-factory/env.sh（= 状态/网络与出口.md §6 登记的
#   anolis grok 官方出口：gov 网关 gov-host.invalid:7890，口令认证；凭据只留在远端该文件，
#   **不进本仓、不进任务书、不进台账**）；该文件不存在时才回落本机 mihomo。
#   断网预检：grok 端点不可达 ⇒ 立刻 exit 4，不许空跑 3 小时。
PROXY_ENV='if [ -f /data/af-factory/env.sh ]; then set -a; . /data/af-factory/env.sh; set +a; fi; export HTTPS_PROXY="${HTTPS_PROXY:-http://pandev-host.invalid:7890}" HTTP_PROXY="${HTTP_PROXY:-http://pandev-host.invalid:7890}";'

echo "-- 出口预检（grok 端点可达性；不通即停，不空跑）--"
ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "$PROXY_ENV code=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 https://cli-chat-proxy.grok.com/v1/models); echo \"   端点 http_code=\$code\"; [ \"\$code\" = \"401\" ] || [ \"\$code\" = \"200\" ]" || {
  echo "FAIL 出口不通（grok 端点不可达）——本批不启动（防再空跑）"; exit 4; }

# 跑 grok（pty 形态 + 代理；输出全量落远端日志）
echo "-- 执行段 grok --"
ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "cd '$WT_ABS' && export PATH=\$HOME/.local/bin:\$PATH && \
   $PROXY_ENV \
   script -qfc \"grok --prompt-file '$WT_ABS/$OFFDIR_REL/$(basename "$BRIEF_ABS")' -m grok-4.6 --always-approve --output-format plain --leader-socket \\\$HOME/.grok/leader-$LABEL.sock\" /dev/null \
     >> '$WT_ABS/$LOG_REL' 2>&1"
RC=$?
echo "   grok 退出码：$RC"

# 日志拉回本机
mkdir -p "$WS/30-工件/外派/$LABEL"
scp -q "${SSH_OPTS[@]}" "$REMOTE:$WT_ABS/$LOG_REL" "$WS/30-工件/外派/$LABEL/$LABEL.log" 2>/dev/null || true
echo "   日志：30-工件/外派/$LABEL/$LABEL.log"

# 构建盘 GC（2026-11-05 14:1x 补面：/data 第三次 ENOSPC 教训）：
#   成功批 ⇒ 立即回收独占 target（增量缓存使命已尽）；失败批 ⇒ 保留供续跑续用（除非 WF_OFFLOAD_GC=1 强制回收）。
if [ "$RC" -eq 0 ] && [ "${WF_OFFLOAD_GC:-1}" != "0" ]; then
  ssh "${SSH_OPTS[@]}" "$REMOTE" "rm -rf '/data/bench/targets/$LABEL'" \
    && echo "   构建盘已回收：/data/bench/targets/$LABEL"
elif [ "$RC" -ne 0 ]; then
  echo "   构建盘保留（失败批续跑用）：/data/bench/targets/$LABEL —— 磁盘紧张时手动回收：ssh $REMOTE rm -rf /data/bench/targets/$LABEL"
fi

if [ "$RC" -eq 0 ]; then echo "OK 外派完成：$LABEL"; else echo "WARN 外派失败（rc=$RC）：$LABEL —— 见日志"; fi
exit "$RC"
