#!/usr/bin/env bash
# =============================================================================
# deploy-consistency-probe.sh — gov 在役 af-jobs-portal 部署一致性探针
#                                （all-gates.sh L5 部署一致性门的本体）
#
# 发现（2026-11-02 RT 收口，实测非推演）：三轮红队修复只落在本地副本
# tools/af-jobs-portal.py，而 gov 在役公网门户（jobs.hkmingdajiaoyu.com，
# 宿主 gov-host.invalid:/opt/company/af-jobs/af-jobs-portal.py，宿主裸进程
# `python3 af-jobs-portal.py`，无 systemd/docker）仍跑 2026-10-30 pre-RT 版——
# /claim、/report task_id 段校验、claim_token 一次性 409、revoked 原子写
# 全部缺席；all-gates 只测本地副本（grep af-jobs=0 命中），本地全绿与
# 在役带洞并存。本探针把部署面变成常驻对账红线：
#
# 判定（各腿全过才 exit 0；任一不过非零退出=红，不静默 SKIP）：
#   D1a 在位：tools/af-jobs-portal.py
#   D1c 内容断言：**先跑**（2026-11-03 勘正）——九批安全修复的功能标记逐一
#      grep 在位（缺一即红，并点名缺的是哪一项）。
#      本腿必须先于 D1b：修前 D1b 先 exit(1)，md5 失配时 D1c 根本不可达
#      ——内容断言对「md5 失配」这一最需要它的场景结构性失明。
#      标记清单含第八批 RT-E169 服务端 quote 契约门（REPORT_SHAPE_KEYS /
#      QUOTE_MAX_CHARS / _report_admission_error）——修前清单只有前七批六项，
#      「把本地副本回滚成第七批钉桩版＝删掉 RT-E169 quote 契约门」这一漂移
#      在 D1c 全程失明（两版都判绿：钉桩版六标记全在位、本地版六标记也全在位）。
#   D1b md5 钉桩：本地副本 md5 ≡ 钉桩 PIN_MD5。**钉的是「本地正本已修版」，
#      不是 gov 在役版**（修前把两件事混为一谈：在役面一致由 D2 对账，
#      钉桩只锚「本地基准是哪一版」）。
#      失配时**按证据判方向**（修前一律断言「本地基准被回滚/被替换」，
#      与实测方向相反——实测是本地比在役新、且本地多出的正是未部署的安全修复）：
#        · D1c 全过（内容标记齐备）+ 本地 mtime 晚于钉桩基线 mtime
#          → 漂移方向＝**本地比钉桩新**（钉桩锚滞后一批），**不是**本地被回滚；
#            处置＝按维护契约同步 PIN_MD5/PIN_MTIME+D1c 标记后部署本地件；
#            **切勿把本地副本回滚/替换成旧钉桩**（那会删掉本地新增的安全修复）。
#        · D1c 全过但本地 mtime 不晚于钉桩基线 mtime
#          → 本地副本被改写/换版（内容被换），须人工确认后重钉桩。
#        · D1c 有缺项 → 内容既非钉桩版、也不含完整安全修复（内容被换）。
#      两种方向都判红（断言不弱化），只是文案不再把方向指反。
#   D2 在役副本 md5 ≡ 本地副本 md5（root@gov-host.invalid:$REMOTE_F）
#      —— 漂移即红：本地改了没部署 / 在役被回退，都点名为「修复只落本地」复发；
#      红文案按在役实测缺哪些安全标记点名（本地有、在役无）＝漂移方向的
#      内容面证据：「在役跑的是更旧的带洞版本，本地比在役新」，而不是笼统
#      一句「在役不是本地已修版」。
#   D3 在役进程在位，且进程启动时刻 ≥ 在役文件 mtime
#      —— 文件换新而进程未重启 = 进程仍跑旧码（Python 启动时加载），
#         部署了≠生效，同红点名「须重启加载」
# gov 不可达也按红（与 all-gates「缺件/前置不满足也按红点名对账，不静默放行」
# 同口径）——在役面失去可对账性本身就是异常。
#
# 〔2026-11-03 D1 短路修（本批；前情＝修前 D1 任一腿红即 exit 1，且位置在取
# 在役读数的 ssh **之前**——故 D2（在役≠本地）与 D3（进程未重启加载）**永不
# 执行**，门在「本地与钉桩失配」这一最需要看清漂移方向的场景恰恰报不出漂移
# 方向；红文案还固定写「本地基准被回滚/被替换」，方向与实测相反：实测＝
# 本地比在役新、且本地多出的正是未部署的安全修复，照文案处置会删掉 RT-E169
# quote 契约门）〕本批改动三处，**断言一律未弱化**：
#   ① D1 改为**收集红因不短路**：D1c/D1b 红因先入 REDS，D2/D3/D4 一律照跑，
#      末了合并打印并 exit 1（任一红因 ⇒ 红，与修前同判）。门因此在任何场景
#      都能报出「在役 vs 本地」的真实漂移方向，不再只在 md5 失配时盲。
#   ② D2c 新增**在役带洞独立红**：md5 一致但**在役缺安全修复标记**（两侧同缺）
#      也判红——修前该形态只在 md5 失配分支被顺带提及，md5 相等时全程失明，
#      「在役无恙」由此得证（**md5 相等 ≠ 安全基线相等**）。
#   ③ D4 新增**在役 AGENTS quote 契约功能实测**：只 grep 标记＝只证「代码在」，
#      不证「契约被强制」——本腿取在役件全文，用 ast 抽出**在役自己的**
#      _report_admission_error/QUOTE_MAX_CHARS 实跑四组正负例（合规件放行／
#      quote>120 字拒／嵌套 quote>120 字拒／无 schema 键拒），全过＝在役
#      **真的强制**AGENTS quote 契约（RT-E169 服务端零强制的根因面）；任一不过
#      即红。本体：tools/portal-quote-contract-probe.py（同一判定逻辑，可单跑取证）。
#   all-gates L5 取探针输出**末行**作 note，故末行固定为**合并结论行**
#   （含漂移方向），不会被 D1/D3 的单条消息顶掉。
# =============================================================================
set -u
GOV_SSH="root@gov-host.invalid"
REMOTE_F="/opt/company/af-jobs/af-jobs-portal.py"
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_F="$_HERE/af-jobs-portal.py"
QUOTE_PROBE="$_HERE/portal-quote-contract-probe.py"

# D1c 断言面：十批安全修复的内容标记（逐代加入，防再滞后一批）
MARKS=(
  '_task_dir_path'                                   # 批次1-4：任务目录/文件路径锚点
  'claim_token already used'                         # 批次4：claim_token 一次性 409
  'os.replace(tmp, _revoked_path())'                 # 批次5：收回册原子写
  'os.path.realpath(os.path.join(root, tid, name))'  # 批次6：读路径锚点钉回 DATA/tasks
  'MAX_BODY_BYTES'                                   # 批次7：do_POST 体帽常量
  'body too large'                                   # 批次7：体帽超限文案
  'REPORT_SHAPE_KEYS'                                # 批次8：RT-E169 服务端 quote 契约门
  'QUOTE_MAX_CHARS'                                  # 批次8：quote ≤120 字上限
  '_report_admission_error'                          # 批次8：/report 落盘前准入门
  '_STATIC_PATH_OK'                                  # 批次9（2026-11-03 RT-45 批）：服务端公网静态面「发布形状白名单」（_static_path 强制发布端同一份 PATH_OK 形状）——此前服务端仅字符集正则，任何 ASCII 名文件落 static/ 即公网直出且不经脱敏
  'RATE_LIMIT_PER_MIN'                               # 批次10（2026-11-03 安全面批）：服务本体限速闸帽值——公网限速只挂门口时前门 120/min 可被 tailnet/docker 网段直连绕过（RT-E166「4MB 体帽 × 无速率」余留面）
  'AF_JOBS_TRUSTED_PROXY_IPS'                        # 批次10：可信反代名单 env（客户键口径：只有可信反代送来的 X-Forwarded-For 末跳被采信；其余对端按直连维限速，伪造头换桶无效）
  '/trigger/gitea-webhook'                           # 批次11（2026-11-03 生产接线批）：gitea→本机 trigger-inbox 触发转发腿端点（验段A HMAC→白名单/体帽→段B 重签转发；缺标记=转发腿被删/回滚）
  'X-Gitea-Signature'                                # 批次11：段A 验签头（常时比较，401 不转发）
  'AF_TRIGGER_INBOX_SECRET'                          # 批次11：段B secret env（X-AF-Signature 重签转发；与段A 相互独立）
  'TRIGGER_HOOK_MAX_BODY'                            # 批次11：转发腿独立 1MiB 体帽（与收件箱 MAX_BODY 同值）
  '_TRIGGER_OPENER'                                  # 批次11：转发腿无代理 opener——gov 宿主 http_proxy 会使 urllib 经出口代理访问 tailnet 收件箱（实测回 502 空体），且 no_proxy 的 CIDR urllib 不识别；删此=转发腿退化为经代理必坏
)

# 红因收集器（D1 不再短路；D2/D3/D4 的红因也入此列，末了合并打印）
REDS=()
drift_add() { # 拼漂移方向摘要（结论行用）
  if [ -z "${DRIFT:-}" ]; then DRIFT="$1"; else DRIFT="$DRIFT；$1"; fi
}

# D1 本地已修副本
if [ ! -f "$LOCAL_F" ]; then
  echo "D1红：本地已修副本缺件 $LOCAL_F（对账无基准）"; exit 2
fi
LMD5="$(md5sum "$LOCAL_F")"; LMD5="${LMD5%% *}"
LM="$(stat -c %Y "$LOCAL_F")"

# D1c 内容断言（**先于 D1b**：md5 失配时内容断言也必须可达，否则这一腿
# 在最需要它的场景结构性失明——修前即如此；且**不再就地 exit**，红因入列后
# 仍继续跑 D2/D3/D4，见文首「D1 短路修」①）
MISSING=""
for MARK in "${MARKS[@]}"; do
  if ! grep -qF -- "$MARK" "$LOCAL_F"; then
    MISSING="$MISSING「$MARK」"
  fi
done
if [ -n "$MISSING" ]; then
  REDS+=("D1红：本地副本缺安全修复标记${MISSING}——九批修复内容不在位（本地内容被换/本地基准被回滚或被替换；md5 失配只是表象，缺项才是判据）")
fi

# D1b known-good 摘要钉桩（2026-11-03 更新到第九批＝本地正本已修版；
# pre-RT 带洞版=0482fb7e3dbc28fbb789e9fdc794e2c4，必须钉死为红）
PIN_MD5="8a7ea5a2132ff1c02b6bccf6b0a059f5"  # 第十一批（2026-11-03 生产接线批：POST /trigger/gitea-webhook gitea→本机 trigger-inbox 触发转发腿——验段A HMAC/白名单 push+pull_request/1MiB 体帽→注入 af.trigger.v1 event+delivery_id→段B 重签 X-AF-Signature 转发 pandev-host.invalid:8765，_TRIGGER_OPENER 无代理直连，失败结构化 502）；上一基线 c372f371 = 第十批（服务本体限速闸+可信反代名单，2026-11-03 06:16 已部署生效）；再上 7ebd85ca = 第八批（RT-E169 服务端 quote 契约门）；再上 86eb3258 = 第七批（do_POST 体帽）；再上 40e99e22 = 第六批（读路径锚点）；再上 6e01c781 = 第五批收口版
PIN_MTIME="1793709315"  # 钉桩基线 mtime（epoch）＝第十一批本地正本写定时刻；判漂移方向用（本地比它新＝本地比钉桩新，非回滚）
if [ "$LMD5" != "$PIN_MD5" ]; then
  if [ -n "$MISSING" ]; then
    REDS+=("D1红：本地副本 md5=$LMD5 ≠ 钉桩已修版 ${PIN_MD5:0:8}…，且 D1c 九批安全标记缺${MISSING}——本地内容既非钉桩版、也不含完整安全修复（内容被换），须人工确认后重钉桩")
  elif [ "$LM" -gt "$PIN_MTIME" ]; then
    REDS+=("D1红：本地副本 md5=$LMD5 ≠ 钉桩已修版 ${PIN_MD5:0:8}…，但 D1c 九批安全标记全在位且本地 mtime($LM) 晚于钉桩基线 mtime($PIN_MTIME)——漂移方向＝本地比钉桩新（钉桩锚滞后一批），**不是**本地基准被回滚/被替换；处置＝按维护契约同步 PIN_MD5/PIN_MTIME+D1c 标记后部署本地件；**切勿把本地副本回滚/替换成旧钉桩**（那会删掉本地新增的安全修复，如第八批 RT-E169 quote 契约门）")
  else
    REDS+=("D1红：本地副本 md5=$LMD5 ≠ 钉桩已修版 ${PIN_MD5:0:8}…，D1c 九批安全标记全在位但本地 mtime($LM) 不晚于钉桩基线 mtime($PIN_MTIME)——本地副本被改写/换版（内容被换），须人工确认后重钉桩")
  fi
  drift_add "本地≠钉桩基线(钉桩外版本)"
fi

# D2/D3 一次 ssh 拉回在役读数：md5 / 文件 mtime / 进程启动时刻（epoch 秒）/
# 九批安全标记的在位表（内容面证据＝漂移方向的判据）
REM="$(printf '%s\n' "${MARKS[@]}" | ssh -o ConnectTimeout=10 -o BatchMode=yes "$GOV_SSH" '
  f="/opt/company/af-jobs/af-jobs-portal.py"
  if [ ! -f "$f" ]; then echo MISSING_FILE; exit 0; fi
  md5sum "$f" | cut -d" " -f1
  stat -c %Y "$f"
  pid="$(pgrep -f "[p]ython3 af-jobs-portal.py" | head -1)"
  if [ -n "$pid" ]; then stat -c %Y "/proc/$pid"; else echo NOPROC; fi
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    if grep -qF -- "$m" "$f"; then echo "HIT|$m"; else echo "MISS|$m"; fi
  done
')" || { echo "D2红：ssh $GOV_SSH 不可达——在役面无法对账（按红点名，不静默）"; exit 2; }

RMD5="$(printf '%s\n' "$REM" | sed -n 1p)"
RMT="$(printf '%s\n' "$REM" | sed -n 2p)"
PST="$(printf '%s\n' "$REM" | sed -n 3p)"
REM_MISSING=""
while IFS='|' read -r st mk; do
  if [ "$st" = "MISS" ]; then
    REM_MISSING="$REM_MISSING「$mk」"
  fi
done < <(printf '%s\n' "$REM" | tail -n +4)

if [ "$RMD5" = "MISSING_FILE" ]; then
  if [ "${#REDS[@]}" -gt 0 ]; then printf '%s\n' "${REDS[@]}"; fi
  echo "D2红：在役副本缺件 $REMOTE_F"; exit 2
fi
if [ "$RMD5" != "$LMD5" ]; then
  if [ -n "$REM_MISSING" ]; then
    REDS+=("D2红：md5 不一致 local=$LMD5 remote=${RMD5:-空}——在役不是本地已修版；漂移方向＝本地比在役新（在役缺安全修复标记$REM_MISSING——本地有、在役无，在役跑的是更旧的带洞版本）；「修复只落本地」复发形态，须部署本地已修版并重启加载")
  else
    REDS+=("D2红：md5 不一致 local=$LMD5 remote=${RMD5:-空}——在役不是本地已修版（「修复只落本地」复发形态），须部署本地已修版并重启加载")
  fi
  drift_add "在役≠本地(md5 失配；漂移方向见上方 D2 红因)"
elif [ -n "$REM_MISSING" ]; then
  # D2c 在役带洞独立红（md5 相等但两侧同缺）：修前该形态全程失明 →「在役无恙」
  REDS+=("D2红：在役副本缺安全修复标记$REM_MISSING——在役 md5 与本地一致但**两侧同缺**＝在役跑的是带洞版本（在役≠known-good 安全基线，「在役无恙」不成立），须补齐在役安全修复并重启加载")
  drift_add "在役≡本地(md5 一致)但**两侧同缺安全修复标记**(在役带洞)"
else
  drift_add "在役≡本地(md5 一致)"
fi

if [ -z "$PST" ] || [ "$PST" = "NOPROC" ]; then
  REDS+=("D3红：在役进程不在位（pgrep 'python3 af-jobs-portal.py' 空，公网门户宕机）")
else
  # 读数合法性：mtime 与进程时刻**各自**须为纯数字（修前只查拼接串，RMT 空而 PST
  # 有值时会漏过；且比较式出错会走「非错」分支＝失守）——任一不合法即对账失败按红
  READ_OK=1
  case "$RMT" in ''|*[!0-9]*) READ_OK=0 ;; esac
  case "$PST" in ''|*[!0-9]*) READ_OK=0 ;; esac
  if [ "$READ_OK" != "1" ]; then
    if [ "${#REDS[@]}" -gt 0 ]; then printf '%s\n' "${REDS[@]}"; fi
    echo "D3红：mtime/进程时刻读数异常（mtime=$RMT proc=$PST），对账失败按红"; exit 2
  fi
  if [ "$PST" -ge "$RMT" ]; then
    : # 进程启动晚于在役文件 mtime ＝ 已加载生效（无红因）
  else
    REDS+=("D3红：在役文件已更新(mtime=$RMT)但进程启动=$PST 早于部署——进程仍跑旧码，须重启加载")
  fi
fi

# D4 在役 AGENTS quote 契约功能实测（grep 标记只证「代码在」，本腿证「强制在生效」）
QLIVE="未测"; QLOCAL="未测"
if [ ! -f "$QUOTE_PROBE" ]; then
  REDS+=("D4红：quote 契约功能实测件缺件 $QUOTE_PROBE——在役 AGENTS quote 契约是否被强制**不可实测**，按红点名，不静默放行")
else
  TMPD="$(mktemp -d "${TMPDIR:-/tmp}/deploy-probe.XXXXXX")"
  trap 'rm -rf "$TMPD"' EXIT
  if ssh -o ConnectTimeout=10 -o BatchMode=yes "$GOV_SSH" "cat '$REMOTE_F'" > "$TMPD/live.py" 2>/dev/null && [ -s "$TMPD/live.py" ]; then
    CAT_MD5="$(md5sum "$TMPD/live.py")"; CAT_MD5="${CAT_MD5%% *}"
    if [ "$CAT_MD5" != "$RMD5" ]; then
      REDS+=("D4红：在役件取回内容 md5=$CAT_MD5 ≠ 在役盘面 md5=$RMD5——在役面读数不自洽（取回过程有竞态/换码），对账失败按红")
    fi
    if qout="$(python3 -I "$QUOTE_PROBE" "$TMPD/live.py" 2>&1)"; then
      QLIVE="强制"; drift_add "在役 AGENTS quote 契约功能实测＝强制"
    else
      QLIVE="未强制"
      REDS+=("D4红：在役门户**未强制** AGENTS quote 契约（功能实测不通过）：$(printf '%s' "$qout" | tail -3 | tr '\n' ' ')")
      drift_add "在役 AGENTS quote 契约功能实测＝未强制"
    fi
  else
    REDS+=("D4红：在役件全文取回失败（ssh cat $REMOTE_F 失败或空）——在役 AGENTS quote 契约无法功能实测，按红点名，不静默放行")
    drift_add "在役 AGENTS quote 契约功能实测＝未测(取回失败)"
  fi
  if qout="$(python3 -I "$QUOTE_PROBE" "$LOCAL_F" 2>&1)"; then
    QLOCAL="强制"
  else
    QLOCAL="未强制"
    REDS+=("D1d红：本地副本**未强制** AGENTS quote 契约（功能实测不通过）：$(printf '%s' "$qout" | tail -3 | tr '\n' ' ')")
  fi
fi

# 合并打印：逐条红因 + 末行结论行（all-gates L5 取末行作 note，故结论行须含漂移方向）
if [ "${#REDS[@]}" -gt 0 ]; then
  printf '%s\n' "${REDS[@]}"
  echo "结论：门红 ${#REDS[@]} 项——${DRIFT:-在对账中}；上列逐条为判据与实测"
  exit 1
fi
echo "OK：在役=本地已修版 md5=${LMD5:0:8}…（≡钉桩 ${PIN_MD5:0:8}…，D1c ${#MARKS[@]} 项安全标记在位；在役 AGENTS quote 契约功能实测＝${QLIVE}／本地＝${QLOCAL}），进程启动($PST)≥文件mtime($RMT)——部署一致且已加载生效"
exit 0
