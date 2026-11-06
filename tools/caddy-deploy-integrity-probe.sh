#!/usr/bin/env bash
# =============================================================================
# caddy-deploy-integrity-probe.sh — caddy 限速部署面完整性巡检门本体
#                                （all-gates.sh L6 门的本体，2026-11-02 施工）
#
# 施工缘起（确证发现 RT-E46 收口批，实测非推演）：
#   · RT-E46 修复（ai./af-jobs/* 的 rate_limit zone afjobs_ai_pub + 4MB 体帽）只存在
#     于 gov:/opt/company/platform 未提交工作树——git log -- ops/caddy/Caddyfile 末条
#     7aa5356（2026-10-01 baseline），git status = M（diff 107+ 行，含 jobs./otlp./
#     factory./zhihui. 五轮限速配置的版本化欠账）→ 一次 git checkout / reset --hard
#     即静默回退到零限速脆弱态（.20261031-pre-RT.bak 里的 ai. 块正是零限速原件）。
#   · 零门护栏：all-gates.sh grep 'Caddyfile|rate_limit|429' = 0 命中，
#     deploy-consistency-probe.sh 只对账 af-jobs-portal.py——回退后全门照绿。
#
# 分工（与并行批 rate-limit-symmetry-probe.py（all-gates L3，2026-11-02 修复员-54）
# 不重复：那边管「行为面」（公网并发 429 断言=RT-E46②原文口径 + 12 穿越变体无泄露
# + 入口登记册），本探针管「部署面完整性」——行为面测不出以下三类静默漂移）：
#   A 腿 版本面（RT-E48 模式⑧「版本面外修复」的 caddy 侧机检；2026-11-02 提交前
#      实测红：status=" M ops/caddy/Caddyfile" → 提交 c53f857 后绿——判别力实盘留证）：
#      gov:/opt/company/platform ops/caddy/Caddyfile 工作树 ≡ HEAD
#      （status --porcelain 空 且 diff --quiet HEAD）。非空=配置未落库=红——
#      「修复只在工作树、git 操作即静默回退」通道的常驻红线。
#   B 腿 配置钉桩（版本面正本 + 在役挂载源 双面）：
#      ① git show HEAD:ops/caddy/Caddyfile 与在役 ops/caddy/Caddyfile 两份文本各自
#        断言五 zone 在位：afjobs_ai_pub×1 / jobs_pub×2（jobs.+factory.）/ otlp_pub×1 /
#        zhihui_pub×1、events 120×5、request_body×4（4MB×3 + 8MB×1）
#        —— 防「HEAD 本身被改成零限速版再提交」（对账相等也会一起带洞）；
#      ② ops/compose/docker-compose.yml 含定制二进制挂载行
#        caddy-ratelimit/caddy:/usr/local/bin/caddy
#        —— 防「compose 丢挂载 → 重建即 stock caddy 不识别 rate_limit 指令」。
#      ③ 公网暴露口「完备性」对账（2026-11-03 施工，补「只验在场不验完备」的洞）：
#        枚举 Caddyfile 全部公网 host 块（顶层块且标签含 {$DOMAIN}），逐块判其
#        是否带 rate_limit zone——任一公网块无 zone 且未在「限速豁免台账」显式
#        登记 ⇒ 红（fail-closed）；台账反向自检：条目对应块已不存在 ⇒ 红（陈旧）；
#        条目对应块已带 zone ⇒ 红（豁免不得沉淀——限速补齐即须注销该条目）。
#        HEAD 正本与在役挂载源双面各跑一遍。① 防「HEAD 被改成零限速版再提交」，
#        ③ 防「新增一个公网块不带限速」（此情形 ①② 全绿也照红——旧门对此零红）。
#      范围口径（2026-11-03 勘误，如实）：旧注记称「langfuse./net./board. 与
#      tailnet-only 绑定（:8200/:3000）系无 zone 设计现状，不在本门护栏对象内」
#      ——该前提被本门自己读的同一份 Caddyfile 推翻：langfuse.(Caddyfile 第 47 行)/
#      net.(60)/board.(78) 各自另有独立的公网 {$DOMAIN} HTTPS 块，与 :63-76 的
#      tailnet-only 明文监听（http://:8200 / http://:3000）是两块不同配置；第四个
#      无 zone 的公网口 zot.(52) 连旧注记都未提及。实测（gov HEAD c53f857）公网
#      host 块 9 个：带 rate_limit zone 的 5 个（ai./otlp./jobs./factory./zhihui.）、
#      无 zone 的 4 个（langfuse./zot./net./board.）。故按实情改写：四者登入显式
#      豁免台账（=显式债务，不是「不在护栏对象内」），缺口本身另案处置——限速补齐
#      属公网流量策略裁决，且 gov 生产面是硬纪律 2 的保留资产，本门只如实钉住。
#   D 腿 加载态钉桩（2026-11-02 当日实盘新发现，本腿为其唯一机检；当日实跑红→修复
#      后绿——判别力实盘留证）：
#      caddy 单文件 bind mount 钉「容器启动时 inode」——rename/scp 型写入（scp/vim/
#      git checkout 均换 inode）后宿主路径文件已变而容器 reload 读的仍是旧 inode 内容
#      （18:44 实证：scp 剃除版后 reload，容器加载态仍=旧全文）。后果：宿主文件
#      「已写未加载」静默漂移——当日实盘抓到现行：挂载 inode 里 request_body=0，
#      10-03 起的全部体帽（4MB×4+8MB×1）自「部署」以来从未在运行态生效过
#      （18:49:52 修复激活）。本腿=caddy admin API（127.0.0.1:2019/config/，容器内
#      只读）取**运行加载态**，断言五 zone 在位 + request_body ≥4——宿主文件写没
#      写对（B 腿）之外，钉「加载了没有」。部署纪律：改该文件必须原 inode 截断写
#      （cat > file / editor no-rename；容器重建/重启前宿主路径必须已是目标内容），
#      改完必 reload（docker exec company-caddy-1 caddy reload …）。
#      ④ 完备性对账（2026-11-03 施工）：加载态的公网 host 匹配器集合 ≡ 在役文件
#      的公网块集合（新增公网块未 reload / 旧块未退役 ⇒ 红），且加载态
#      rate_limit handler 数 ≥ 在役文件 rate_limit 指令数（限速写进文件未加载 ⇒ 红）
#
# 行为面（429 在役证明）由 L3 rate-limit-symmetry-probe.py 常驻（B 腿 131×8 并发
# 断言 429；2026-11-02 本批负向判别力留证：真实剃零限速态（docker restart 载入
# 剃除版）下三公网入口 140 并发全 200 零 429——同型断言必红，L3 判据成立）。
#
# 退出码：0=本腿全绿；1=断言红；2=前置失败（gov 不可达/仓库缺件/域解析失败）
#         ——all-gates 口径「非零即红」，2 也按红点名对账，不静默 SKIP。
# =============================================================================
set -u
GOV_SSH="root@gov-host.invalid"
REPO="/opt/company/platform"
CF_REL="ops/caddy/Caddyfile"
COMPOSE_REL="ops/compose/docker-compose.yml"
CADDY_CONTAINER="company-caddy-1"

LEG="${2:-all}"
[ "${1:-}" = "--leg" ] && LEG="$LEG"

rc_global=0
worst() { [ "$1" -gt "$rc_global" ] && rc_global="$1"; return 0; }

ssh_gov() { ssh -o ConnectTimeout=10 -o BatchMode=yes "$GOV_SSH" "$@"; }

# ============================================================ 公网暴露口完备性对账
# （2026-11-03 施工；补「五 zone 在场 ≠ 公网 host 块完备」的洞。旧门只钉住
#  五个限速 zone 的「在场」，Caddyfile 里任何一个公网 {$DOMAIN} 块不带限速都
#  零红——新增公网暴露口（zot. 那样）绕过全部门。判定口径：Caddyfile 顶层块、
#  标签含 {$DOMAIN} 者 = 公网暴露口，逐块判其是否带 rate_limit zone。）
#
# Caddyfile 顶层块解析 → "<块标签>\t<rate_limit 指令数>\t<zone 声明数>"。
# 语法前提：顶层块头顶格（无缩进）、以 "{" 结尾；顶层块以顶格 "}" 收尾；嵌套块
# 一律缩进——故按「顶格 { 起 / 顶格 } 止」切块稳定（顶格 "#" 注释行不成块）。
caddy_blocks() {
  awk '
    BEGIN { inblk = 0 }
    {
      line = $0
      if (!inblk) {
        if (line ~ /^[^\t ]/ && line !~ /^#/ && line ~ /\{[ \t]*$/) {
          label = line
          sub(/[ \t]*\{[ \t]*$/, "", label)
          inblk = 1; rl = 0; zn = 0
        }
        next
      }
      if (line ~ /^[ \t]*rate_limit[ \t]*\{/) rl++
      if (line ~ /^[ \t]*zone[ \t]+[A-Za-z0-9_]+[ \t]*\{/) zn++
      if (line ~ /^\}/) { printf "%s\t%d\t%d\n", label, rl, zn; inblk = 0 }
    }
  '
}

# 公网 host 块枚举：$1=Caddyfile 文本 → "<归一标签>\t<rl>\t<zn>"（仅标签含 {$DOMAIN}）
# 归一标签：ai.{$DOMAIN} → ai（去 "{$DOMAIN}" 9 字符后缀 + 去尾点）；*.{$DOMAIN} → *。
caddy_public_hosts() {
  printf '%s\n' "$1" | caddy_blocks | while IFS=$'\t' read -r lab rl zn; do
    [ -n "$lab" ] || continue
    for tok in $lab; do
      case "$tok" in
        *'{$DOMAIN}'*) : ;;
        *) continue ;;
      esac
      sub="${tok:0:$(( ${#tok} - 9 ))}"
      sub="${sub%.}"
      [ -n "$sub" ] || sub="@apex"
      printf '%s\t%s\t%s\n' "$sub" "$rl" "$zn"
    done
  done
}

# 「限速豁免台账」（显式登记；未登记者一律红——fail-closed）。
# 格式：<公网 host 标签>|<台账号>|<理由>
# 注销条件：该公网块补上 rate_limit zone 后条目即失效（反向自检会红），须同时
#           删掉本行——豁免不沉淀、不转世。
L6_EXC_LEDGER='langfuse|L6-EXC-001|Langfuse UI 公网 HTTPS 块（Caddyfile langfuse.{$DOMAIN}）2026-09-26 建块即无 zone；限速缺口的显式登记（非 tailnet-only——该 host 另有公网块）
zot|L6-EXC-002|Zot 容器仓库公网块（Caddyfile zot.{$DOMAIN}）basic_auth 到位、限速缺（容器推送大层不限速的取舍待运营者裁决）
net|L6-EXC-003|Headscale 公网块（Caddyfile net.{$DOMAIN}）2026-09-26 建块即无 zone
board|L6-EXC-004|看板公网块（Caddyfile board.{$DOMAIN}）2026-09-26 建块即无 zone'

ledger_has() {                 # $1=host 标签 → 0=在台账
  local h="$1" lh _rest
  while IFS='|' read -r lh _rest; do
    [ "$lh" = "$h" ] && return 0
  done <<< "$L6_EXC_LEDGER"
  return 1
}
ledger_note() {                # $1=host 标签 → 打印 "台账号｜理由"
  local h="$1" lh id rs
  while IFS='|' read -r lh id rs; do
    [ "$lh" = "$h" ] && { printf '%s｜%s' "$id" "$rs"; return 0; }
  done <<< "$L6_EXC_LEDGER"
  return 1
}

# 公网暴露口完备性对账：$1=来源名（HEAD正本/在役挂载源） $2=Caddyfile 文本
# 返回 0=绿 / 1=红
completeness() {
  local src="$1" txt="$2"
  local FAIL=0 lab rl zn h lh id rs x
  local -a pub=() lim=() unl=()
  while IFS=$'\t' read -r lab rl zn; do
    [ -n "$lab" ] || continue
    pub+=("$lab")
    if [ "${rl:-0}" -ge 1 ] && [ "${zn:-0}" -ge 1 ]; then lim+=("$lab"); else unl+=("$lab"); fi
  done < <(caddy_public_hosts "$txt")
  echo "  · 公网暴露口枚举（$src）：公网 host 块 ${#pub[@]} 个 —— 限速到位 ${#lim[@]} 个 / 无 rate_limit zone ${#unl[@]} 个"
  # ⓪ 反空转：枚举口径（顶层块标签含 {$DOMAIN}）若失效导致枚举为 0，完备性对账
  #    不得静默放行——否则「改名/整段丢失」即等于零红（RT-E84 类空转形态）。
  if [ "${#pub[@]}" -lt 1 ]; then
    echo "B红：公网 host 块枚举结果为 0——枚举口径失效（顶层块标签含 {\$DOMAIN} 的约定被改名或整段丢失？）——完备性对账不得空转放行"; FAIL=1
  fi
  # ① 任一无 zone 的公网块必须在台账显式登记（未登记 ⇒ 红：新增公网口未配限速）
  for h in "${unl[@]}"; do
    if ledger_has "$h"; then
      echo "  [台账] 公网块 ${h}. 无 rate_limit zone —— 已登记豁免（$(ledger_note "$h")）"
    else
      echo "B红：公网 host 块 ${h}. 带公网暴露（标签含 {\$DOMAIN}）却无 rate_limit zone，且未在「限速豁免台账」登记——新增公网暴露口未配限速（fail-closed）"; FAIL=1
    fi
  done
  # ② 台账条目须仍对应存在的公网块（陈旧条目 ⇒ 红）
  # ③ 台账条目对应块若已带 zone ⇒ 红（豁免不得沉淀：限速补齐即须注销条目）
  while IFS='|' read -r lh id rs; do
    [ -n "$lh" ] || continue
    local found=0 limfound=0
    for x in "${pub[@]}"; do [ "$x" = "$lh" ] && found=1; done
    for x in "${lim[@]}"; do [ "$x" = "$lh" ] && limfound=1; done
    if [ "$found" = "0" ]; then
      echo "B红：限速豁免台账条目 ${lh}（${id}）已无对应公网 host 块——陈旧条目，请注销"; FAIL=1
      continue
    fi
    if [ "$limfound" = "1" ]; then
      echo "B红：限速豁免台账条目 ${lh}（${id}）对应的公网块已带 rate_limit zone——豁免已失效，请注销台账条目（豁免不得沉淀）"; FAIL=1
    fi
  done <<< "$L6_EXC_LEDGER"
  return $FAIL
}

# --------------------------------------------------------------- A 腿 版本面
leg_A() {
  local out
  out="$(ssh_gov "cd '$REPO' 2>/dev/null || { echo 'A红：仓库 $REPO 不在位'; exit 2; }
    git rev-parse --verify -q HEAD >/dev/null || { echo 'A红：git HEAD 不存在（空仓/损坏）'; exit 2; }
    [ -f '$CF_REL' ] || { echo \"A红：$REPO/$CF_REL 在役文件缺件\"; exit 2; }
    st=\$(git status --porcelain -- '$CF_REL')
    if [ -n \"\$st\" ]; then echo \"A红：$CF_REL 工作树 ≠ HEAD（git status：\${st}）——限速修复未落库，一次 git checkout/reset 即静默回退零限速态（RT-E46/模式⑧版本面外修复）\"; exit 1; fi
    if ! git diff --quiet HEAD -- '$CF_REL'; then echo \"A红：$CF_REL 与 HEAD diff 非空（未提交改动）\"; exit 1; fi
    echo \"A绿：$CF_REL 工作树 ≡ HEAD（已提交 \$(git log -1 --format='%h %s' -- '$CF_REL' | cut -c1-60)）——git checkout/reset 不再回退限速修复\"" )"; local rc=$?
  echo "$out"
  worst "$rc"
  [ "$rc" = "0" ]
}

# --------------------------------------------------------------- B 腿 配置钉桩
leg_B() {
  local headblob livefile mountline
  headblob="$(ssh_gov "cd '$REPO' && git show HEAD:$CF_REL" 2>/dev/null)" || {
    echo "B红：git show HEAD:$CF_REL 失败（版本面无正本可钉，gov 不可达也走此路）"; return 2; }
  livefile="$(ssh_gov "cat '$REPO/$CF_REL'" 2>/dev/null)" || {
    echo "B红：在役 $CF_REL 读取失败（gov 不可达/缺件）"; return 2; }
  mountline="$(ssh_gov "grep -cF 'caddy-ratelimit/caddy:/usr/local/bin/caddy' '$REPO/$COMPOSE_REL'" 2>/dev/null)" || {
    echo "B红：compose 定制二进制挂载行检查失败（$COMPOSE_REL 不可读）"; return 2; }

  local FAIL=0
  chk() { # <文本名> <文本> <pattern(-F)> <下限>
    local n; n="$(printf '%s\n' "$2" | grep -cF -- "$3" || true)"
    if [ "$n" -ge "$4" ]; then
      echo "  [ok] $1：$3 命中 $n ≥ $4"
    else
      echo "B红：$1 钉桩失守：「$3」命中 $n < $4（限速配置不在位）"; FAIL=1
    fi
  }
  for src in "HEAD正本" "在役挂载源"; do
    local txt; [ "$src" = "HEAD正本" ] && txt="$headblob" || txt="$livefile"
    chk "$src" "$txt" "zone afjobs_ai_pub" 1
    chk "$src" "$txt" "zone jobs_pub" 2
    chk "$src" "$txt" "zone otlp_pub" 1
    chk "$src" "$txt" "zone zhihui_pub" 1
    chk "$src" "$txt" "events 120" 5
    chk "$src" "$txt" "request_body" 4
    chk "$src" "$txt" "max_size 4MB" 3
    chk "$src" "$txt" "max_size 8MB" 1
    completeness "$src" "$txt" || FAIL=1
  done
  if [ "${mountline:-0}" -ge 1 ]; then
    echo "  [ok] compose 定制二进制挂载在位（caddy-ratelimit/caddy → /usr/local/bin/caddy，重建不失 rate_limit 指令）"
  else
    echo "B红：compose 缺定制二进制挂载行（caddy-ratelimit/caddy:/usr/local/bin/caddy）——重建容器即 stock caddy，rate_limit 指令不被识别"; FAIL=1
  fi
  if [ "$FAIL" = "0" ]; then
    local n_pub n_unl n_lim
    n_pub="$(caddy_public_hosts "$livefile" | wc -l | tr -d ' ')"
    n_unl="$(caddy_public_hosts "$livefile" | awk -F'\t' '($2+0)<1 || ($3+0)<1' | wc -l | tr -d ' ')"
    n_lim=$(( n_pub - n_unl ))
    echo "B绿：版本面正本与在役挂载源五 zone/events 120/体帽钉桩全过 + 公网暴露口完备性对账全过（公网块 ${n_pub} 个：限速到位 ${n_lim} / 无 zone ${n_unl}（均台账登记豁免））+ 定制二进制挂载在位"
    return 0
  fi
  return 1
}

# --------------------------------------------------------------- D 腿 加载态钉桩
leg_D() {
  local cfg n name want fail=0
  cfg="$(ssh_gov "docker exec $CADDY_CONTAINER wget -qO- http://127.0.0.1:2019/config/ 2>/dev/null")" || {
    echo "D红：caddy admin API 读取失败（容器不在/接口不可达）——加载态无法对账"; return 2; }
  if [ -z "$cfg" ]; then
    echo "D红：admin API 返回空（admin 端点未开/容器异常）——加载态无法对账"; return 2
  fi
  # 五 zone 在位（jobs_pub 在运行态出现 2 次=jobs.+factory. 两 handler 实例）
  for pair in "afjobs_ai_pub:1" "jobs_pub:2" "otlp_pub:1" "zhihui_pub:1"; do
    name="${pair%%:*}"; want="${pair##*:}"
    n="$(printf '%s' "$cfg" | grep -o "$name" | wc -l)"
    if [ "$n" -ge "$want" ]; then
      echo "  [ok] 加载态：zone $name ×$n ≥ $want"
    else
      echo "D红：运行加载态缺 zone $name（命中 $n < $want）——配置写了但没加载/被回退（bind-mount 旧 inode 漂移或 reload 缺席）"; fail=1
    fi
  done
  n="$(printf '%s' "$cfg" | grep -o "request_body" | wc -l)"
  if [ "$n" -ge 4 ]; then
    echo "  [ok] 加载态：request_body ×$n ≥ 4（体帽已在运行态生效）"
  else
    echo "D红：运行加载态 request_body 命中 $n < 4——体帽已写未加载（bind-mount 旧 inode 漂移：scp/rename 型写入换 inode 后 reload 读旧内容）——须原 inode 截断写 + reload"; fail=1
  fi
  # ④ 完备性对账（2026-11-03 施工）：加载态公网 host 集合 ≡ 在役文件公网块集合；
  #    加载态 rate_limit handler 数 ≥ 在役文件 rate_limit 指令数。
  local livefile fpub lpub f_rl l_rl
  livefile="$(ssh_gov "cat '$REPO/$CF_REL'" 2>/dev/null)" || {
    echo "D红：在役 $CF_REL 读取失败（gov 不可达/缺件）——加载态与文件面无法对账"; return 2; }
  fpub="$(caddy_public_hosts "$livefile" | cut -f1 | sort -u | tr '\n' ' ' | sed 's/ *$//')"
  lpub="$(printf '%s' "$cfg" | grep -o '"host":[[:space:]]*\[[^]]*\]' | sed 's/^"host":[[:space:]]*\[//; s/\]$//' | tr ',' '\n' | tr -d '" ' | grep -v '^$' | sed 's/\..*//' | sort -u | tr '\n' ' ' | sed 's/ *$//')"
  if [ -n "$fpub" ] && [ "$fpub" = "$lpub" ]; then
    echo "  [ok] 加载态公网 host 集合 ≡ 在役文件公网块集合（$(printf '%s' "$lpub" | wc -w | tr -d ' ') 个：$lpub）"
  else
    echo "D红：加载态公网 host 集合与在役文件不一致（文件：[$fpub]｜加载态：[$lpub]）——新公网块未 reload 或旧块未退役"; fail=1
  fi
  f_rl="$(printf '%s\n' "$livefile" | grep -cE '^[[:space:]]*rate_limit[[:space:]]*\{' || true)"
  l_rl="$(printf '%s' "$cfg" | grep -o '"handler":[[:space:]]*"rate_limit"' | wc -l | tr -d ' ')"
  if [ "$f_rl" -ge 1 ] && [ "$l_rl" -ge "$f_rl" ]; then
    echo "  [ok] 加载态 rate_limit handler ×$l_rl ≥ 在役文件 rate_limit 指令数 ×$f_rl"
  else
    echo "D红：加载态 rate_limit handler ×$l_rl < 在役文件 rate_limit 指令数 ×$f_rl——限速写进文件未加载（bind-mount 旧 inode 漂移）——须原 inode 截断写 + reload"; fail=1
  fi
  [ "$fail" = "0" ] && { echo "D绿：运行加载态五 zone + 体帽全部在役 + 完备性对账通过（公网 host 集合 ≡ 在役文件；rate_limit handler 数 ≥ 文件指令数）（admin API 实证，非宿主文件推定）"; return 0; }
  return 1
}

case "$LEG" in
  A) leg_A ;;
  B) leg_B ;;
  D) leg_D ;;
  all)
    leg_A; leg_B; leg_D
    echo "巡检总退出码：$rc_global（0=三腿全绿 1=断言红 2=前置失败）"
    exit "$rc_global"
    ;;
  *) echo "用法：$0 [--leg A|B|D]（缺省三腿全跑；行为面 429/穿越见 L3 rate-limit-symmetry-probe.py）" >&2; exit 2 ;;
esac
exit $?
