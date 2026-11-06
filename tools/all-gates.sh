#!/usr/bin/env bash
# =============================================================================
# all-gates.sh — tools/ 层统一门禁（一条命令的全量质量门）
#
# 收编原先散跑的各套测试/自检件，按层组织、红绿分明、失败清单可读：
#   L1 语法门  全部 tools/*.py py_compile + 全部 tools/*.sh bash -n
#              + 环境自适应清单（anolis-only 件识别为 SKIP，不标绿）
#              + py_compile 件数下限对账（清单声明 #L1_PY_COUNT_MIN，2026-11-02 RT-E84③：
#                删门脚本即红——此前件数随 glob 缩小、照绿）
#   L2 单测门  tools/test-*.py 逐个跑（非零即红并点名）
#              + test-manifest.list 在列件对账（缺一件即红点名，2026-11-02 RT-E5b：
#                堵「删单个 test-*.py 静默绿」——glob 只能堵全删）
#              + 在列门件内容钉对账（2026-11-03 RT-L2身钉：在盘 test-*.py 身钉入
#                tools/gate-pins.list，在列件缺钉行/实时摘要≠钉值即红——堵「同名
#                替换成恒绿桩照常在列照常绿」，此前名册/自声明/件数三面对账只钉
#                名与数、不钉身，L3 gate-pins-check.sh 对钉面全行双消费面同款对账）
#              + 清单在列数自声明对账 + 摘要 PASS 数下限（2026-11-02 RT-E84②：
#                堵「删件并同时删清单行」两侧同缩——此前只钉单边）
#              + 清单 sha256 变更留痕对账（2026-11-02 RT-E84④：tools/ 不在任何 git
#                仓内，清单改动须登记在 计划/变更日志.md，未登记即红）
#   L3 selftest 门  b-canon / b-pick-claims / b-verdict-unique / task-planner
#              的 --selftest，card-lint --all，publish-scrub-gate --selftest，
#              ch-mes-reconcile --selftest（CH 写入对账门，红队 C5 次项；
#              实查模式由 otel-reconcile-probe 定时跑+落状态面，门消费状态面）
#              + 门本体钉桩完整性对账（2026-11-03 RT-CI门本体批：tools/ 与工作区
#                根都不在任何 git 仓内 →「门面 diff 即见」不成立；门件件数下限钉值
#                外置到钉桩面 tools/gate-pins.list，其摘要登记在 计划/变更日志.md，
#                钉桩面内每个 sha256 行与子探针/门本体实时摘要绑定——改钉值/改门/
#                改探针未重锚即红。改后唯一合规动作：bash tools/gate-pins-refresh.sh）
#   L4 集成门  python3 kb/verify.py --quick；task-planner 裸跑（须 exit 0）
#   L5 部署一致性门  gov 在役 af-jobs-portal（jobs.hkmingdajiaoyu.com 宿主裸进程）
#              ≡ 本地已修副本（md5 对账）且在役进程启动晚于部署时刻（已加载
#              生效）——2026-11-02 RT 收口：三轮红队修复只落本地副本、在役公网
#              门户仍跑 10-30 pre-RT 带洞版而全门全绿的盲区（此前 grep
#              af-jobs 本脚本=0 命中）。本体 tools/deploy-consistency-probe.sh
#   L6 caddy 部署面完整性门（RT-E46 收口批，2026-11-02）：RT-E46 修复（ai./af-jobs
#              rate_limit + 五轮限速/体帽配置）曾只存在于 gov:/opt/company/platform
#              未提交工作树（HEAD 停在 7aa5356=2026-10-01 baseline，107+ 行 diff）——
#              一次 git checkout/reset 即静默回退零限速态而全门照绿。三腿（秒级、
#              零公网流量，内联同 L5 先例）：A 版本面（gov 工作树≡HEAD——模式⑧
#              「版本面外修复」caddy 侧机检，提交 c53f857 前实跑红留证）；B 配置
#              钉桩（HEAD 正本+在役挂载源双面五 zone/events 120/体帽 + compose 定制
#              二进制挂载行）；D 加载态（caddy admin API 运行配置断言五 zone+体帽
#              ——bind mount 钉「容器启动时 inode」，rename/scp 型写入=已写未加载，
#              2026-11-02 实盘抓到现行：体帽自 10-03 起从未在运行态生效，18:49
#              修复激活，本腿为其唯一机检）。行为面（429/穿越）=L3
#              rate-limit-symmetry-probe.py（并行批同日施工，分工不重复）。本体
#              tools/caddy-deploy-integrity-probe.sh
#
# 用法：
#   bash tools/all-gates.sh              # 全量（L1→L4）
#   bash tools/all-gates.sh --fast       # 跳过 L4（集成门）
#   bash tools/all-gates.sh L2           # 单门点名（可多次：L1 L3 L5 L6）
#   bash tools/all-gates.sh --par 8      # 并行度（默认 8）
#   bash tools/all-gates.sh --selftest-perrun
#       # RT-E73：双实例并发自检 + 旧形态破坏夹具（秒级；HOME 隔离，不抢生产锁）
#
# 退出码：0=无红（PASS 与 SKIP 都算非红）；1=有红（FAIL）；2=用法/环境错误（含单例锁拒绝——已有并发实例在跑时立即 exit 2 拒跑，见主流程单例锁段）。
# 状态语义：PASS=实跑通过；FAIL=实跑失败/超时/断言红/被测件自退非零（含 rc=2——
#          「非零即红」，与 af/ci/run.sh step() 同口径）/门本体缺失（L2 无
#          test-*.py、L3/L4 目标件不在位——摘门必须显式红出来对账，不得静默放行，
#          2026-10-31 RT 批收口：缺件/自退 2 不再进 SKIP）；
#          SKIP=本门不执行该项（--fast / 全局时限 / anolis-only 不可跑），
#          原因逐条写明——SKIP 绝不当成绿，被测件缺件/非零退出更不进 SKIP。
#
# 执行模型：L1 内联跑（秒级）；L2/L3/L4 全部项进同一并行池（--par，默认 8），
#           池壁钟=最长项（parity 回归为长杆），全量墙钟 = parity 实测上界 + 汇总开销
#           （2026-10-31 DEB-5 重标后 ≈ 17~40 分钟起步，视在役负载；2026-11-01 DEB-5a
#           起长杆预算随 registry verified 规模自适应上调、墙钟同向上涨——见主流程
#           DEB-5a 段；旧注释「~3.5 分钟」是 registry 15339 verified 时代的规模，按实测改写）；
#           各门仍独立段输出+汇总表。结果经文件台账回收（$RUNDIR/item-<n>.result），
#           不靠后台子 shell 改父 shell 数组。日志落
#           $HOME/all-gates-logs/<时间戳>-<pid>/（RT-E73：per-run 隔离，同秒两实例
#           零共写；父目录 / 锁文件 / gate-pins.anchor 位置不变。AGENT.md 硬纪律 7：
#           /tmp 只放白名单件）。
#
# 纪律：不修改任何被测件；每项独立跑、独立记 rc/耗时/日志。
# =============================================================================
set -u

WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$WS/tools"
START_MS=$(date +%s%3N)
GLOBAL_BUDGET_MS=3000000         # 全局时限：项超时帽=剩余预算-10s。
                                # 预算必须 ≥ 最长杆基础超时（parity 2400s）+ 10s 安全边
                                # + 启动耗时，否则自适应帽会低于项自报基础超时、把长杆
                                # 误杀成假红。2026-10-29 实证：285000 预算把 parity 裁到
                                # 274s，而该项空载直跑已需 242s（registry 15339 atoms，
                                # 25 分钟内 11440→15440），在役 8 路并发下连续两次 274s
                                # 超时 FAIL，直跑却 exit 0、4 项断言全绿。预算只约束上限、
                                # 不改任何断言。
                                # 2026-10-31（DEB-5）按实测重标：registry 17986 verified
                                # （较 10-29 的 15339 涨 17%），三长杆并行池实测
                                # parity 573.5/574.7/661.3s、router-kb-ingest
                                # 358.2/359.8/444.8s、task-planner 209.3/209.9/210.9s
                                # （3 轮干净实测，均 exit 0）。最长杆基础超时 parity=1440s
                                # → 全局预算须 ≥1460s，取 1560s（余量 120s）。
                                # 同日再校准：晚间在役重载（外来 12 进程 sweep 并发，
                                # load 10~20）把三长杆整体拉长——池内 parity > 1440s（被帽
                                # 掐）、router 787s、planner 484s；parity 单跑 1015s（rc=0）。
                                # 根因是工作量 ∝ registry 原子数（29434→33601 原子，+14%/5h），
                                # 不是门逻辑退化。故 parity 帽 1440→2400s、router 960→1500s、
                                # planner 540→900s，全局预算 1560→3000s（= 2400+600 余量）。
                                # 池壁钟随之由 ~3.5 分钟变为 17~40 分钟（视在役负载）——
                                # 墙钟不再声称 ≤5 分钟（见文件头注释）；2026-11-01 DEB-5a 再适配：预算随 registry 规模自适应，见主流程 DEB-5a 段。
PAR=8
RUN_L1=0; RUN_L2=0; RUN_L3=0; RUN_L4=0; RUN_L5=0; RUN_L6=0; ANY_NAMED=0; FAST=0
SELFTEST_PERRUN=0
SELFTEST_PERRUN_CHILD=""

usage() { sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }

prev=""
for arg in "$@"; do
  if [ "$prev" = "--par" ]; then PAR="$arg"; prev=""; continue; fi
  if [ "$prev" = "--selftest-perrun-child" ]; then SELFTEST_PERRUN_CHILD="$arg"; prev=""; continue; fi
  case "$arg" in
    --fast) FAST=1 ;;
    --par) prev="--par" ;;
    --selftest-perrun) SELFTEST_PERRUN=1 ;;
    --selftest-perrun-child) prev="--selftest-perrun-child" ;;
    L1) RUN_L1=1; ANY_NAMED=1 ;;
    L2) RUN_L2=1; ANY_NAMED=1 ;;
    L3) RUN_L3=1; ANY_NAMED=1 ;;
    L4) RUN_L4=1; ANY_NAMED=1 ;;
    L5) RUN_L5=1; ANY_NAMED=1 ;;
    L6) RUN_L6=1; ANY_NAMED=1 ;;
    all|--all) ;;
    -h|--help) usage ;;
    *) echo "未知参数：$arg（可用：--fast / L1 / L2 / L3 / L4 / L5 / --par N / --selftest-perrun）" >&2; usage ;;
  esac
done
if [ "$prev" = "--par" ] || [ "$prev" = "--selftest-perrun-child" ]; then
  echo "FATAL: $prev 需要参数" >&2; exit 2
fi
# L5（部署一致性门）默认随任意形态常开（含 --fast）：它只测在役面与本地副本的
# 一致性，秒级、无重负载，而「本地绿、在役带洞」正是它要堵的盲区——跳过它=白修。
if [ "$ANY_NAMED" = "0" ]; then RUN_L1=1; RUN_L2=1; RUN_L3=1; [ "$FAST" = "0" ] && RUN_L4=1; RUN_L5=1; RUN_L6=1; fi
[ "$FAST" = "1" ] && RUN_L4=0
case "$PAR" in ''|*[!0-9]*) echo "FATAL: --par 需正整数（当前 $PAR）" >&2; exit 2 ;; esac
[ "$PAR" -ge 1 ] || { echo "FATAL: --par 需 ≥1" >&2; exit 2; }

# --- RT-E84②③（2026-11-02）+ RT-CI门本体（2026-11-03）：门件件数下限锚（钉桩面） ---
# 背景：清单声明（tools/test-manifest.list 的 #L2_ITEMS_COUNT / #L1_PY_COUNT_MIN）
# 与清单正文是同一份可改文件——「删件 + 删清单行 + 同步下调声明 + 登记留痕」可把
# 两侧一起缩到小，门仍绿。故另设**钉值**（与清单非同文件）：有效下限 = max(钉值,
# 清单声明)。
# RT-CI门本体批（红队已确证发现，非推演）：原钉值写在本脚本的硬编码常量里，而
# tools/ 与工作区根都不在任何 git 仓内（git -C tools rev-parse → fatal: 不是 Git
# 仓库）——「改门=纪律红线，门面 diff 即见，红队审门面必见」在本仓**不成立**：
# 改钉值零版本面、零完整性绑定，且无任何机检消费其摘要 ⇒「改钉值 + 删件 + 删清单
# 行 + 下调声明 + 追加一行登记」可让 RT-E84②③ 两侧对账同时通过、exit=0。
# 修法（最小改动、下限语义不变）：钉值搬出本脚本 → 钉桩面 tools/gate-pins.list，
#   本脚本只读取值；该文件摘要须登记在 计划/变更日志.md（登记面＝tools/ 唯一版本
#   面，RT-E84④ 同款口径），并由 tools/gate-pins-check.sh（L3 常驻项）机检消费
#   ⇒ 改钉值 / 改门本体 / 改子探针，三者任一未重锚即红。钉桩面不可读 ⇒ 判红
#   （fail-closed：不回退到本脚本内的兜底值——留兜底值即等于钉值仍在门本体内）。
# 维护纪律：新增/下线门件 → 同步更新清单行、清单声明行、钉桩面 L2_MIN_ITEMS 三处
#   （缺一即红或提示盲区，见 register_L2「自声明对账」项的提示行）；改后跑
#   bash tools/gate-pins-refresh.sh 重锚摘要与登记。
# L2_MIN_ITEMS 历史亲数（钉值已搬至钉桩面 tools/gate-pins.list；下列记录备查）：
#   2026-11-02 16:0x 亲数：清单在列 16 件；
                     # 2026-11-02 16:3x 增 RT-E32 跨卡分歧消费腿机制自证 1 件 → 17 件；
                     # 2026-11-02 16:5x 增 /tmp 写入门径量纲门自证 1 件 → 18 件；
                     # 2026-11-02 18:1x 增 RT-E80④ 卡型三侧接线清单门自证 1 件 → 19 件；
                     # 2026-11-02 18:1x 增 RT-E67 机制② qc 存量对账门自证 1 件 → 20 件；
                     # 2026-11-02 18:5x 增 RT-E44③/E45/E47② 门户安全三面回归门 1 件
                     # （test-portal-attack-surface.py；并行 ledger 批在列 21 件后随本批
                     # 同步）→ 22 件；
                     # 2026-11-02 18:5x 增 RT-E44③ 在役公网腿 + RT-E47② 在役公网腿
                     # （test-claim-token-once.py + test-path-traversal-404.py，
                     # RT-E46 收口批；本地隔离面由 portal-attack-surface 覆盖，
                     # 此两件=公网在役部署侧腿）→ 24 件；
                     # 2026-11-03 05:2x 增配额闸派发侧↔执行侧判据对账门 1 件
                     # （test-quota-gate-criteria-parity.py；同一份 quota.json 两侧
                     # 裁决恒等门——修前 8/8 vs 15/20 各判各的，无对账项可红）→ 27 件；
                     # 同窗并行批另增 test-qc-leg-truth-gate.py 等 2 件（其中 1 件=
                     # 派生闸源读数新鲜度门 test-gate-source-freshness.py：派生闸携带
                     # 源 ts + 执行/消费两侧独立判源年龄——修前派生闸只带自身写入时刻、
                     # 执行闸对源停写完全失明）→ 29 件；
                     # 2026-11-03 05:4x 增 minimax 双道派发闸判据门 1 件
                     # （test-minimax-dispatch-gate.py；step 套餐到期+运营者令停用后
                     # 「step 8/8 槽满才溢出」的闸结构永闭 → 自 2026-10-28 13:58 起
                     # 零派发，而配额/摘要面仍写 mm=go——本门钉住新判据：step 不可用
                     # → 闸放行；step 在役且未满 → 仍不派（原溢出语义保留））→ 30 件；
                     # 2026-11-03 05:5x 增 event-router 在役源码版本钉对账门 1 件
                     # （test-router-version-pin.py；router 的版本钉此前每次写盘现读
                     # 盘面重算 ⇒ 盘面一改钉即自愈成新盘面指纹，钉≡盘面恒等 ⇒ 对账
                     # 面永远看不到漂移＝假绿，版本钉机制自我失效——本门钉住「钉=
                     # 载入时指纹」且修前件必须自愈（判别力负控））→ 31 件）
#
# L1_MIN_PY 历史亲数（钉值已搬至钉桩面 tools/gate-pins.list；下列记录备查）：
#   2026-11-02 16:2x 亲数：81 件；2026-11-02 16:5x 亲数：83 件；
#   2026-11-02 18:1x 亲数：86 件（+test-cardtype-three-side-wiring.py
#   + 并行批新增件，随在册件数同步）；
#   2026-11-02 18:1x 增 RT-E67 批 2 件（test-e67-qc-stock-recon.py +
#   kb-e67-qc-stock-clean.py）→ 88 件（随在册件数同步）；
#   2026-11-02 18:5x 亲数 91 件（tools/*.py 84 + tools/otel/*.py 7；
#   并行批 3 件在册漂移随本批归零 + 本批新增
#   test-portal-attack-surface.py / rate-limit-symmetry-probe.py）
#
# --- RT-CI门本体（2026-11-03）：钉值改由钉桩面供给（fail-closed，语义不变）---
GATE_PINS_FILE="$TOOLS/gate-pins.list"
gate_pin() {  # $1=键 → 打印钉桩面取值（读不到则返回非零、输出为空）
  [ -f "$GATE_PINS_FILE" ] || return 1
  sed -n "s/^$1=//p" "$GATE_PINS_FILE" 2>/dev/null | head -1
}
L2_MIN_ITEMS="$(gate_pin L2_MIN_ITEMS)"
L1_MIN_PY="$(gate_pin L1_MIN_PY)"
# 钉桩面不可读/取值非法 ⇒ PINS_OK=0：件数下限无从对账 → 下限对账项判红（fail-closed，
# 不得回退到门本体内的兜底值——留兜底值＝钉值仍在门本体内，可被同文件编辑绕过）。
PINS_OK=1
case "$L2_MIN_ITEMS" in ''|*[!0-9]*) PINS_OK=0 ;; esac
case "$L1_MIN_PY"     in ''|*[!0-9]*) PINS_OK=0 ;; esac
[ "$L2_MIN_ITEMS" = "0" ] && PINS_OK=0
[ "$L1_MIN_PY" = "0" ] && PINS_OK=0

# --- RT-G10pin（2026-11-03）：G10 值级对账门独立钉桩摘要锚（门内钉值） ---
# 背景（红队确证发现，非推演）：G10 值级对账门的复算命令与登记值**同处一个被验
# 文件**——tools/numbers-sota-check.py 从被验正本自身的 meta.verification.legs
# 读出复算命令（改一行即改判据），故「把某条 live 腿的 recheck 改成 `echo 1`、
# 把该腿 value 改成 1」即可让本门自证为绿（实测 rc=0 / PASS=26 / RED=0）；再跑
# --refresh 更把篡改值写回正本并重打 as_of（龄 0.0h）——自证闭环完成。
# 修法：命令集/结构的 sha256 锚在**另一个文件** tools/numbers-sota-check.pin.json
# （门本体自校：正本命令集摘要 + 门本体摘要；失配即红且**不执行**任何登记命令，
# --refresh 亦拒绝回写）。
# 本段是**门本体之外的第三锚**：改门本体（哪怕把它的自校删掉）时本段仍会红——
# 先例：L5 部署一致性门 D1b 的 known-good md5 钉桩（改门=纪律红线，门面 diff
# 即见）。
# 维护契约（三处，缺一即红）：改 tools/numbers-sota-check.py 或
# tools/numbers-sota-check.pin.json → ①本段两个常量 ②计划/变更日志.md 登记串
# （tools/numbers-sota-check.pin.json sha256=<64位hex>）③钉桩自身的 manifest。
# 2026-11-03 RT-SOTABODY 批（报告正文↔正本值级对账 + 结论回指键一致性）：
#   门本体新增两节能力（正文对账规则表 + 两个 verdict 键与 live 腿的一致性），
#   规则表与报告路径**钉在门本体内**——改正本命令集或门本体均须重钉桩；
#   本段两个常量随本批重算（tool=d9b212eb… pin=1c25b273…）。
# 2026-11-03 RT-带结构批（分数带机器可读口径 + 漏记带值补全）：正本
#   meta.verification 变了（value_key_count_declared 73→75；新增 2 条带值 live
#   腿；9 条带/差距腿的 recheck --expect-sha 随探针本体 sha 同步）→ 钉桩清单
#   必须重生成。**门本体未改**（tool sha 仍 d9b212eb…，本批只改正本与探针），
#   故只有 pin 一处常量随本批重算（pin=50f1ba63…）。
# 2026-11-03 RT-当期带下沿批（当期(2026)同 harness 带下沿补入机检键集）：正本
#   meta.verification 变了（value_key_count_declared 75→76；新增 1 条
#   public_band_2026_same_harness_pct live 腿；9 条带/差距腿的 recheck
#   --expect-sha 随探针本体 sha 同步 98dc3b33…→96427c26…）→ 钉桩清单必须重生成。
#   **门本体未改**（tool sha 仍 d9b212eb…，本批只改正本与探针），故只有 pin
#   一处常量随本批重算（pin=50f1ba63…→c8f6132b…）。
# 2026-11-03 RT-锚1钉值批（锚1 判定链快照值钉桩——同文件一致篡改实测/判定/回指
#   键无声翻转锚1 结论的形态被钉死）：门本体新增 snapshot_value_pins（锚1 判定链
#   5 键——实测/参照实测/anchor1_verdict/anchors_passing/g11 输入——的值随
#   --make-pin 钉进独立钉桩文件；snapshot 腿本地无源不可复算，唯一值锚在钉桩，
#   逐键比对失配即红且 fail-closed）+ 正文锚1 行规则 +3（§〇/§4.1/§4.3，判定列
#   『未达标』『判未达』以字面量进规则）+ 判别力自测红路 +4（R18 篡改实测 /
#   R19 翻判定串 / R20 改 anchors_passing / R21 正文锚1 行漂移+翻判定，17→21 条）。
#   快照腿不经 --refresh 回写，值钉桩不影响合法刷新；合法重测锚1 判定链值须走
#   重钉桩三步（①--make-pin ②本段两常量 ③变更日志登记串）。本段两常量随本批
#   重算（tool=d9b212eb…→72ba0fbd… pin=c8f6132b…→7bb45ff3…）。
#   【2026-11-06 g10 值钉补登批】SNAPSHOT_VALUE_PIN_KEYS 7→26 键（32 条未钉缺口
#   补登 19 条、留证跳过 13 条），门本体与钉桩同步重算：
#   tool=72ba0fbd…→5ac23f03… pin=7bb45ff3…→c853aeb3…（登记串见变更日志
#   2026-11-06 g10 值钉补登批行；复算证据见 30-工件/g10-pin-backfill-20261106.md）。
G10_TOOL_SHA256=5ac23f0339b22ba437193e37735e22503b6af9f93b19a08e8fd3410e6e7c60b4
G10_PIN_SHA256=c853aeb3f6e40196b727f5c49cfa9b2f90728a346436f4f9e041cbf1780f888d

# ---------------------------------------------------------------- 运行环境
command -v python3 >/dev/null 2>&1 || { echo "FATAL: 缺 python3，全门不可执行" >&2; exit 2; }
PYV="$(python3 -V 2>&1)"
export PAR   # xargs/bash -c 子进程要用（L1 并行编译/语法检查）

# RT-E73（2026-11-05）：门日志 per-run 隔离。
# 旧形态 `$HOME/all-gates-logs/<YYYYMMDD-HHMMSS>` 同秒启动两实例会 mkdir -p
# 同一目录，run_item 的 `> "$logf"` / item-N.result 互相截断覆盖（逃逸台账
# RT-E73 实证：两跑同秒启动共写同一日志目录）。
# 新形态：<时间戳>-<pid>，mkdir 排他创建（已存在则加 nsec 消歧）。
# 只收紧不放宽：
#   · 父目录 $HOME/all-gates-logs/ 不变（锁文件 .all-gates.lock 与
#     gate-pins.anchor 仍落父目录，L5/L6 自测 HOME 隔离语义不变）；
#   · 汇总行仍打印「日志目录：$RUNDIR」，L5 自测 grep '日志目录：' 仍成立；
#   · 历史时间戳目录原样保留；新目录名是旧形态的真后缀，`ls -t` /
#     `~/all-gates-logs/*/item-*.result` glob 仍吃得下；
#   · DEB-10 flock 单例锁不放宽（生产同 HOME 仍拒第二实例）；本隔离堵住
#     「锁被绕过 / HOME 隔离的双实例 / 锁前已 mkdir」三条仍会共写的缝。
# 分配点：锁拿到之后（拒跑实例不再留下空时间戳目录）。
alloc_rundir() {
  local root="$HOME/all-gates-logs" ts pid dir nsec
  mkdir -p "$root" || return 1
  ts="$(date +%Y%m%d-%H%M%S)"
  pid="$$"
  dir="$root/${ts}-${pid}"
  if mkdir "$dir" 2>/dev/null; then
    RUNDIR="$dir"
    export RUNDIR
    return 0
  fi
  nsec="$(date +%N)"
  dir="$root/${ts}-${pid}-${nsec}"
  mkdir "$dir" || return 1
  RUNDIR="$dir"
  export RUNDIR
  return 0
}

# RT-E73 拦截②③ 机检消费面。--selftest-perrun-child TOKEN 是叶子：走与生产
# 同一条 alloc_rundir，写 marker + item-0.result 后退出，不抢锁、不跑门。
selftest_perrun_child() {
  local token="$1"
  [ -n "$token" ] || { echo "FATAL: --selftest-perrun-child 需要 token" >&2; exit 2; }
  alloc_rundir || { echo "FATAL: alloc_rundir 失败" >&2; exit 1; }
  printf '%s\n' "$token" >"$RUNDIR/marker" || exit 1
  printf 'PASS|0|%s\n' "$token" >"$RUNDIR/item-0.result" || exit 1
  printf 'SELFTEST_PERRUN_CHILD token=%s RUNDIR=%s pid=%s\n' "$token" "$RUNDIR" "$$"
  exit 0
}

# RT-E73 拦截②③：旧形态破坏夹具必须咬人 + 新形态双实例零交叉。
# 子实例 HOME 隔离，不抢生产 flock（DEB-10 单例锁不放宽）。
selftest_perrun() {
  local work nfail=0 oldroot share ts go h1 h2 cA cB rcA rcB dirA dirB baseA baseB tsA tsB got
  work="$HOME/all-gates-logs/.perrun-selftest-$$"
  mkdir -p "$work" || { echo "FATAL: 无法创建自检工作根 $work" >&2; exit 2; }
  echo "=== RT-E73 门日志 per-run 隔离双实例自检 ==="
  echo "工作根：$work"

  # ---- A. 旧形态破坏夹具：同秒时间戳共写同一目录（run_item 的 `>` 截断语义）----
  oldroot="$work/oldform"
  ts="20261105-000000"
  share="$oldroot/$ts"
  mkdir -p "$share"
  (
    printf 'A-UNIQUE-PAYLOAD\n' >"$share/item-0.log"
    printf 'PASS|1|A-UNIQUE-PAYLOAD\n' >"$share/item-0.result"
  ) &
  (
    printf 'B-UNIQUE-PAYLOAD\n' >"$share/item-0.log"
    printf 'PASS|1|B-UNIQUE-PAYLOAD\n' >"$share/item-0.result"
  ) &
  wait
  got="$(cat "$share/item-0.result" 2>/dev/null || true)"
  if printf '%s' "$got" | grep -q 'A-UNIQUE-PAYLOAD' && printf '%s' "$got" | grep -q 'B-UNIQUE-PAYLOAD'; then
    echo "  [FAIL] 旧形态夹具未咬人：共享 item-0.result 同时保全了双方 payload（读到：$got）"
    nfail=$(( nfail + 1 ))
  elif printf '%s' "$got" | grep -qE 'A-UNIQUE-PAYLOAD|B-UNIQUE-PAYLOAD'; then
    echo "  [OK]   旧形态咬人：共享 item-0.result 只留下一方（读到：$(printf '%s' "$got" | tr '\n' ' ')）——另一方被截断覆盖"
  else
    echo "  [FAIL] 旧形态夹具未按预期写出（读到：${got:-<空>}）"
    nfail=$(( nfail + 1 ))
  fi
  if [ "$(find "$share" -name 'item-0.result' | wc -l)" -eq 1 ]; then
    echo "  [OK]   旧形态结构咬人：同秒时间戳目录里只有 1 份 item-0.result（无法按实例分账）"
  else
    echo "  [FAIL] 旧形态结构未咬人：item-0.result 份数=$(find "$share" -name 'item-0.result' | wc -l)"
    nfail=$(( nfail + 1 ))
  fi

  # ---- B. 新形态公式：同秒时间戳 + 不同 pid → 两目录 ----
  # `( )` 子 shell 的 $$ 仍是父 pid，必须起真 bash 进程才与生产 alloc_rundir 同形。
  ts="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$work/newform"
  bash -c '
    dir="$1/${2}-$$"
    mkdir "$dir" || exit 1
    printf "A-UNIQUE-PAYLOAD\n" >"$dir/item-0.log"
    printf "PASS|1|A-UNIQUE-PAYLOAD\n" >"$dir/item-0.result"
    printf "%s\n" "$dir" >"$3"
  ' _ "$work/newform" "$ts" "$work/dir-formula-A" &
  bash -c '
    dir="$1/${2}-$$"
    mkdir "$dir" || exit 1
    printf "B-UNIQUE-PAYLOAD\n" >"$dir/item-0.log"
    printf "PASS|1|B-UNIQUE-PAYLOAD\n" >"$dir/item-0.result"
    printf "%s\n" "$dir" >"$3"
  ' _ "$work/newform" "$ts" "$work/dir-formula-B" &
  wait
  dirA="$(cat "$work/dir-formula-A" 2>/dev/null || true)"
  dirB="$(cat "$work/dir-formula-B" 2>/dev/null || true)"
  if [ -n "$dirA" ] && [ -n "$dirB" ] && [ "$dirA" != "$dirB" ] \
     && grep -qx 'A-UNIQUE-PAYLOAD' "$dirA/item-0.log" \
     && grep -qx 'B-UNIQUE-PAYLOAD' "$dirB/item-0.log" \
     && ! grep -q 'B-UNIQUE-PAYLOAD' "$dirA/item-0.log" \
     && ! grep -q 'A-UNIQUE-PAYLOAD' "$dirB/item-0.log"; then
    echo "  [OK]   新形态公式隔离：同秒 ts=$ts 两目录独立（A=$(basename "$dirA") B=$(basename "$dirB")），零交叉"
  else
    echo "  [FAIL] 新形态公式隔离失败：dirA=${dirA:-<空>} dirB=${dirB:-<空>}"
    nfail=$(( nfail + 1 ))
  fi

  # ---- C. 真 all-gates 双实例（HOME 隔离，生产 alloc_rundir）----
  h1="$work/home1"; h2="$work/home2"; go="$work/go"
  mkdir -p "$h1" "$h2"
  (
    export HOME="$h1"
    while [ ! -f "$go" ]; do sleep 0.05; done
    bash "$TOOLS/all-gates.sh" --selftest-perrun-child A
  ) >"$work/outA" 2>"$work/errA" &
  cA=$!
  (
    export HOME="$h2"
    while [ ! -f "$go" ]; do sleep 0.05; done
    bash "$TOOLS/all-gates.sh" --selftest-perrun-child B
  ) >"$work/outB" 2>"$work/errB" &
  cB=$!
  sleep 0.15
  : >"$go"
  wait "$cA"; rcA=$?
  wait "$cB"; rcB=$?
  dirA="$(sed -n 's/^SELFTEST_PERRUN_CHILD token=A RUNDIR=//p' "$work/outA" | awk '{print $1}')"
  dirB="$(sed -n 's/^SELFTEST_PERRUN_CHILD token=B RUNDIR=//p' "$work/outB" | awk '{print $1}')"
  if [ "$rcA" != "0" ] || [ "$rcB" != "0" ]; then
    echo "  [FAIL] 双实例子进程非零：rcA=$rcA rcB=$rcB"
    echo "         outA=$(tr '\n' ' ' <"$work/outA" 2>/dev/null)"
    echo "         errA=$(tr '\n' ' ' <"$work/errA" 2>/dev/null)"
    echo "         outB=$(tr '\n' ' ' <"$work/outB" 2>/dev/null)"
    echo "         errB=$(tr '\n' ' ' <"$work/errB" 2>/dev/null)"
    nfail=$(( nfail + 1 ))
  elif [ -z "$dirA" ] || [ -z "$dirB" ] || [ "$dirA" = "$dirB" ]; then
    echo "  [FAIL] 双实例 RUNDIR 未独立：dirA=${dirA:-<空>} dirB=${dirB:-<空>}"
    nfail=$(( nfail + 1 ))
  else
    baseA="$(basename "$dirA")"
    baseB="$(basename "$dirB")"
    tsA=""; tsB=""
    if [[ "$baseA" =~ ^([0-9]{8}-[0-9]{6})-([0-9]+) ]]; then tsA="${BASH_REMATCH[1]}"; fi
    if [[ "$baseB" =~ ^([0-9]{8}-[0-9]{6})-([0-9]+) ]]; then tsB="${BASH_REMATCH[1]}"; fi
    if [ -z "$tsA" ] || [ -z "$tsB" ]; then
      echo "  [FAIL] RUNDIR 名不是 <时间戳>-<pid>：A=$baseA B=$baseB"
      nfail=$(( nfail + 1 ))
    elif [ "$(cat "$dirA/marker" 2>/dev/null)" != "A" ] \
      || [ "$(cat "$dirB/marker" 2>/dev/null)" != "B" ] \
      || grep -q B "$dirA/marker" \
      || grep -q A "$dirB/marker" \
      || ! grep -q '|A$' "$dirA/item-0.result" \
      || ! grep -q '|B$' "$dirB/item-0.result"; then
      echo "  [FAIL] 双实例交叉污染：A.marker=$(cat "$dirA/marker" 2>/dev/null) B.marker=$(cat "$dirB/marker" 2>/dev/null)"
      nfail=$(( nfail + 1 ))
    else
      if [ "$tsA" = "$tsB" ]; then
        echo "  [OK]   双实例真路径隔离：同秒 ts=$tsA 两 RUNDIR 独立（A=$baseA B=$baseB），marker/result 零交叉"
      else
        echo "  [OK]   双实例真路径隔离：两 RUNDIR 独立（A=$baseA B=$baseB，跨秒 tsA=$tsA tsB=$tsB），marker/result 零交叉"
      fi
    fi
  fi

  if [ "$nfail" -eq 0 ]; then
    echo "SELFTEST_PERRUN: PASS（旧形态咬人 + 新形态零交叉 + 双实例 RUNDIR 独立）"
    rm -rf "$work"
    return 0
  fi
  echo "SELFTEST_PERRUN: FAIL（$nfail 项，现场留 $work）"
  return 1
}

# 门路径的环境隔离（2026-11-02 RT 修复，OTel 链·新鲜度帽旁路）：
# 门项跑法是 `timeout "$eff_tmo" bash -c "$cmd"`，子进程**继承调用者环境**，
# 且本脚本此前无任何 unset/清环境（grep 'unset|env -i' 零命中）→ 外部注入一个
# 环境变量即可从门路径旁路整条门语义。已实证旁路样本：OTEL_SIDECAR_STALE_CAP_S
# （边车新鲜度帽）=999999 时，陈旧快照从 rc=2（红）变 rc=0（绿）。
# 处置：断言器侧已把该变量改为「只认 CLI 显式旗标 --stale-cap-s，环境变量一律
# 不看」（tools/otel/otlp-assert.py:_sidecar_stale_cap）；此处再从门面清一道，
# 防旧件/旧路径复活旁路。unset 只影响本 shell 及其子进程，不改调用者环境。
unset OTEL_SIDECAR_STALE_CAP_S

now_ms() { date +%s%3N; }
elapsed_s() { local d=$(( $(now_ms) - START_MS )); echo "$(( d / 1000 )).$(( d % 1000 / 100 ))s"; }

# 项账本：ITEMS[i]="idx|gate|name|timeout|cmd"；结果落 $RUNDIR/item-<idx>.result
ITEMS=()
# RT-E84②：L2 清单在列门件名（清单 roster）——摘要表的 PASS 数下限按「清单在列」
# 口径计（未列名新增件是额外覆盖，不计入下限，补录清单后即在册受保护）。
L2_ROSTER_NAMES=()
add_item() { ITEMS+=("$(( ${#ITEMS[@]} ))|$1|$2|$3|$4"); }

item_result_file() { echo "$RUNDIR/item-$1.result"; }

# ---------------------------------------------------------------- 反馈梯度批（2026-11-04）件②：结构化产物出口接线
# v0.3 T5 终裁⑤现症：台账行 item-N.result 是管道行（PASS|耗时ms|说明），汇总层无法
# 区分「真绿」与「没跑成」——退出码不可单独判绿。本批接线：每件门的台账行落盘后
# **即时**结构化为 item-N.json（与本台账同 RUNDIR 留证，不写 /tmp）。解析口径在
# tools/gate-item-legacy-bridge.py（件①，af 仓同名桥同款：PASS/FAIL/SKIP 三态 +
# 未知 SKIP 词拒判不落产物 + 异内容拒覆盖）。
# 纪律红线：本段只加「落产物 + 三态汇总（见 summary 尾 structured_rollup）」，零门判
# 改动——阈值/判据/SKIP 条件/门件清单一律未动；产物缺失/损坏/拒判**不进门级 FAIL
# 计数、不改退出码**，只在三态汇总里按「未跑成」显名（防假绿，也不添假红）。
EMIT_PY="$TOOLS/gate-item-legacy-bridge.py"
SUMMARY_PY="$TOOLS/gate-item-three-state-summary.py"
item_json_file() { echo "$RUNDIR/item-$1.json"; }
emit_item_json() { # $1=idx $2=gate $3=name —— 台账落盘后即时结构化（run_item 后台并发安全：一件一文件互不重叠）
  [ -f "$(item_result_file "$1")" ] || return 0
  [ -f "$(item_json_file "$1")" ] && return 0   # 产物不可改写（拒覆盖语义，同桥内 persist_json）
  if [ ! -f "$EMIT_PY" ]; then
    printf 'FATAL: %s 不在位——item-%s 结构化产物未产出（三态汇总将按「未跑成」显名）\n' "$EMIT_PY" "$1" >>"$RUNDIR/structured-emit.err"
    return 0
  fi
  python3 "$EMIT_PY" --result "$(item_result_file "$1")" --json-out "$(item_json_file "$1")" \
    --check-id "all-gates:$2:$3" --gate "$2" --name "$3" \
    --source "$(basename "$(item_result_file "$1")")" \
    >>"$RUNDIR/structured-emit.out" 2>>"$RUNDIR/structured-emit.err" \
    || printf 'item-%s 结构化失败（桥拒判/落盘失败，见 structured-emit.err）——三态汇总按「未跑成」显名\n' "$1" >>"$RUNDIR/structured-emit.err"
  return 0
}

# ---------------------------------------------------------------- RT-E84②③④ 清单读取
# tools/test-manifest.list 两段语义：
#   · '#' 开头声明行：'#KEY=VALUE'（L2_ITEMS_COUNT / L1_PY_COUNT_MIN）
#   · 其余非空行：L2 在列门件 roster（tools/ 下 basename）
manifest_decl() { # <KEY> → 声明值原样（无声明则空串）
  local mf="$TOOLS/test-manifest.list" k="$1" line v=""
  [ -f "$mf" ] || { printf '%s' ""; return 0; }
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '#'*) ;; *) continue ;; esac
    line="${line#\#}"
    case "$line" in "$k"=*) v="${line#*=}"; break ;; esac
  done <"$mf"
  printf '%s' "$v"
}
manifest_rows() { # 清单在列行数（空行与 '#' 行忽略）
  local mf="$TOOLS/test-manifest.list" n=0 line
  [ -f "$mf" ] || { echo 0; return 0; }
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    n=$((n + 1))
  done <"$mf"
  echo "$n"
}
manifest_sha() { # 清单内容 sha256（变更留痕对账用）
  local mf="$TOOLS/test-manifest.list"
  [ -f "$mf" ] || { printf '%s' ""; return 0; }
  sha256sum "$mf" 2>/dev/null | cut -d' ' -f1
}

# 直接记账（不执行：L1 内联项、各类 SKIP 预检）
record_item() { # <gate> <name> <status> <ms> <note>
  local idx=${#ITEMS[@]}
  ITEMS+=("$idx|$1|$2|0|")
  printf '%s|%s|%s\n' "$3" "$4" "$5" > "$(item_result_file "$idx")"
  emit_item_json "$idx" "$1" "$2"   # 反馈梯度批件②：即时落结构化产物（记账语义零改动）
}

# 单项执行器：在并行池的后台子 shell 里跑，结果写文件台账（父 shell 回收）
# 超时帽自适应：min(项基础超时, 全局剩余预算-10s)——在役工厂重载下长杆项
# （parity 实测 574~661s / router-kb-ingest 360~445s）不被误杀；全局剩余不足
# 45s 的项不再启动（run_pool 记 SKIP），避免超发。
run_item() { # $1=ITEMS 下标
  local spec="${ITEMS[$1]}"
  local idx gate name tmo cmd
  IFS='|' read -r idx gate name tmo cmd <<<"$spec"
  local logf="$RUNDIR/item-$idx.log"
  local remain_ms=$(( GLOBAL_BUDGET_MS - ($(now_ms) - START_MS) - 10000 ))
  local eff_tmo=$tmo
  [ "$remain_ms" -lt $(( tmo * 1000 )) ] && eff_tmo=$(( remain_ms / 1000 ))
  [ "$eff_tmo" -lt 30 ] && eff_tmo=30
  local t0 t1 rc ms status note
  t0=$(now_ms)
  timeout "$eff_tmo" bash -c "$cmd" >"$logf" 2>&1
  rc=$?
  t1=$(now_ms); ms=$(( t1 - t0 ))
  case "$rc" in
    0)  status=PASS; note="$(tail -1 "$logf" 2>/dev/null | tr -d '\r' | cut -c1-160)" ;;
    2)  status=FAIL; note="rc=2 非零即红（缺件/前置不满足也按红点名对账，不静默 SKIP）：$(tail -1 "$logf" 2>/dev/null | tr -d '\r' | cut -c1-100)" ;;
    124) status=FAIL; note="超时 ${eff_tmo}s（item-$idx.log；在役重载可复跑对账）" ;;
    *)  status=FAIL; note="rc=$rc：$(grep -m1 -E 'FAIL|Error|error|Traceback|assert' "$logf" 2>/dev/null | tr -d '\r' | cut -c1-140)" ;;
  esac
  printf '%s|%s|%s\n' "$status" "$ms" "$note" > "$(item_result_file "$idx")"
  emit_item_json "$idx" "$gate" "$name"   # 反馈梯度批件②：即时落结构化产物
}

# 并行池：把所有尚无结果账本的项跑掉（受 --par 限流；剩余预算 <45s 的项不启动，
# 记 SKIP(全局时限)——不牺牲已启动项的超时帽）
run_pool() {
  local par="$1" spec idx g name remain_ms
  for spec in "${ITEMS[@]}"; do
    IFS='|' read -r idx g name _ _ <<<"$spec"
    [ -f "$(item_result_file "$idx")" ] && continue
    remain_ms=$(( GLOBAL_BUDGET_MS - ($(now_ms) - START_MS) ))
    if [ "$remain_ms" -lt 45000 ]; then
      printf 'SKIP|0|全局时限剩余 %d.%ds，不再启动（复跑该门即可）\n' \
        $(( remain_ms / 1000 )) $(( remain_ms % 1000 / 100 )) > "$(item_result_file "$idx")"
      emit_item_json "$idx" "$g" "$name"   # 反馈梯度批件②：预算型 SKIP 同样落结构化产物（skip_reason=environment_unavailable）
      continue
    fi
    run_item "$idx" &
    while [ "$(jobs -rp | wc -l)" -ge "$par" ]; do sleep 0.2; done
  done
  wait
}

print_gate_head() { echo ""; echo "================ $1 $2 ================"; }

print_gate() { # <gate>
  local gate="$1" spec idx g name tmo cmd rf status ms note
  for spec in "${ITEMS[@]}"; do
    IFS='|' read -r idx g name tmo cmd <<<"$spec"
    [ "$g" = "$gate" ] || continue
    rf="$(item_result_file "$idx")"
    if [ ! -f "$rf" ]; then
      status=SKIP; ms=0; note="未执行（异常：无结果台账，见 item-$idx.log）"
    else
      IFS='|' read -r status ms note <<<"$(cat "$rf")"
    fi
    case "$status" in
      PASS) echo "  [PASS] $name（$(( ms / 1000 ))s） $note" ;;
      SKIP) echo "  [SKIP] $name —— $note" ;;
      *)    echo "  [FAIL] $name（$(( ms / 1000 ))s） $note" ;;
    esac
  done
}

# ---------------------------------------------------------------- L1 语法门
gate_L1() {
  print_gate_head "L1" "语法门（py_compile + bash -n + 环境自适应清单）"
  local pyfiles=() shfiles=() f
  shopt -s nullglob
  for f in "$TOOLS"/*.py; do pyfiles+=("$f"); done
  for f in "$TOOLS"/*.sh; do shfiles+=("$f"); done
  # 子目录件也纳入语法门：tools/otel/（OTel 工具面）此前不被顶层 glob 覆盖，
  # 其语法错只在运行期才暴露。纳入后 py_compile 件数 61→67（+6，2026-10-31 G8 批）。
  for f in "$TOOLS"/otel/*.py; do pyfiles+=("$f"); done
  shopt -u nullglob

  local t0 ms npy nsh nfail nshf pyfail shfail
  # --- L1a py_compile（逐文件、并行；失败件点名） ---
  t0=$(now_ms)
  pyfail="$RUNDIR/l1a-pycompile-fail.txt"; : >"$pyfail"
  if [ "${#pyfiles[@]}" -gt 0 ]; then
    printf '%s\n' "${pyfiles[@]}" | xargs -P "$PAR" -I{} bash -c '
      python3 -m py_compile "$1" 2>>"$RUNDIR/l1a-pycompile.err" || echo "$1"' _ {} >"$pyfail"
  fi
  ms=$(( $(now_ms) - t0 )); npy=${#pyfiles[@]}
  nfail=$(grep -c . "$pyfail" 2>/dev/null || true); nfail=${nfail:-0}
  if [ "$nfail" = "0" ]; then
    record_item L1 "py_compile ${npy} 件" PASS "$ms" "全部通过（$PYV）"
  else
    record_item L1 "py_compile ${npy} 件" FAIL "$ms" \
      "${nfail}/${npy} 件编译失败：$(tr '\n' ' ' <"$pyfail" | sed "s|$WS/||g" | cut -c1-200)（详见 l1a-pycompile.err）"
  fi

  # --- RT-E84③：L1 py_compile 件数下限对账（件数入同一清单 tools/test-manifest.list） ---
  # 发现（红队 RT-E84 确证）：此前 L1 件数用 glob 实算（register_L1/${#pyfiles[@]}），
  # 删任一门脚本后件数随 glob 缩小、照绿（清单只含 12 个 test-*.py，tools/ 下 py 件
  # 共 79 件，56 件门脚本不在任何清单内——删一件即静默）。修法：件数下限写进同一份
  # 清单（声明行 #L1_PY_COUNT_MIN），实测少于下限即红；删门脚本并同步改本声明也红
  # （改声明本身要过「变更留痕对账」：清单 sha256 须登记在 计划/变更日志.md）。
  local l1decl l1floor
  l1decl="$(manifest_decl L1_PY_COUNT_MIN)"
  case "$l1decl" in
    ''|*[!0-9]*)
      record_item L1 "L1 件数下限对账" FAIL 0 \
        "清单缺可用的 #L1_PY_COUNT_MIN 声明（读到 '${l1decl}'）——L1 py_compile 件数下限无从对账（RT-E84③）" ;;
    *)
      # 有效下限 = max(钉桩面钉值 L1_MIN_PY, 清单声明)：清单声明可被同步下调配合删件，
      # 钉桩面钉值不可（改它须改钉桩面 + 登记留痕 + 重锚，三处缺一即红）；新增 .py
      # 件不误红（下限语义，只增不减）。钉桩面不可读 ⇒ 判红（fail-closed）。
      if [ "$PINS_OK" != "1" ]; then
        record_item L1 "L1 件数下限对账" FAIL 0 \
          "钉桩面不可读或取值非法（tools/gate-pins.list：L1_MIN_PY='${L1_MIN_PY}'）——件数下限无从对账（fail-closed，不得回退门本体兜底值；RT-CI门本体）"
      else
        l1floor="$l1decl"
        [ "$L1_MIN_PY" -gt "$l1floor" ] && l1floor="$L1_MIN_PY"
        if [ "$npy" -lt "$l1floor" ]; then
          record_item L1 "L1 件数下限对账" FAIL 0 \
            "在册 py_compile 件数 $npy < 下限 $l1floor（钉桩面钉值 L1_MIN_PY=$L1_MIN_PY / 清单声明 L1_PY_COUNT_MIN=$l1decl）——有门脚本被摘除：删件并同步改清单声明也红（RT-E84③）"
        else
          record_item L1 "L1 件数下限对账" PASS 0 \
            "在册 py_compile 件数 $npy ≥ 下限 $l1floor（钉桩面钉值 L1_MIN_PY=$L1_MIN_PY / 清单声明 L1_PY_COUNT_MIN=$l1decl）"
        fi
      fi ;;
  esac

  # --- L1b bash -n（逐文件、并行；失败件点名） ---
  t0=$(now_ms)
  shfail="$RUNDIR/l1b-bashn-fail.txt"; : >"$shfail"
  if [ "${#shfiles[@]}" -gt 0 ]; then
    printf '%s\n' "${shfiles[@]}" | xargs -P "$PAR" -I{} bash -c '
      bash -n "$1" 2>>"$RUNDIR/l1b-bashn.err" || echo "$1"' _ {} >"$shfail"
  fi
  ms=$(( $(now_ms) - t0 )); nsh=${#shfiles[@]}
  nshf=$(grep -c . "$shfail" 2>/dev/null || true); nshf=${nshf:-0}
  if [ "$nshf" = "0" ]; then
    record_item L1 "bash -n ${nsh} 件" PASS "$ms" "全部通过"
  else
    record_item L1 "bash -n ${nsh} 件" FAIL "$ms" \
      "${nshf}/${nsh} 件语法失败：$(tr '\n' ' ' <"$shfail" | sed "s|$WS/||g" | cut -c1-200)（详见 l1b-bashn.err）"
  fi

  # --- L1c 环境自适应：anolis-only / 本机不可跑件（SKIP，不标绿） ---
  # 已核判据（件内硬依赖 anolis 路径/二进制，本机不存在或设计为远端执行）：
  # SKIP≠无对账（2026-11-03 RT 批）：这四件在 anolis 侧的「在役 ≡ 本地正本 + 常驻
  # 守护已加载生效」部署对账由 L5 anolis 腿（tools/anolis-deploy-consistency-probe.sh）
  # 常驻执行——本节 SKIP 只说明「本机不跑它们」，不说明「没人对账它们」。
  local -a ANOLIS_ONLY=(
    "tools/burn-runner.py|硬依赖 /data/bench/queue 与 /data/af-factory/target-p3/debug/af-order（本机无；anolis 常驻补货器）"
    "tools/image-pool-retire.py|PENDING=/data/bench/queue/pending（anolis 队列件，本机无该目录）"
    "tools/swev-pool-gen.py|设计为 ssh anolis 远端执行（usage 头：ssh anolis .../swev-pool-gen.py）"
    "tools/setup-8b-anolis.sh|anolis 装机脚本（目标机非本机）"
  )
  local e path reason
  for e in "${ANOLIS_ONLY[@]}"; do
    path="${e%%|*}"; reason="${e#*|}"
    [ -e "$WS/$path" ] || reason="$reason；且当前不在位"
    record_item L1 "$(basename "$path")" SKIP 0 "anolis-only：$reason"
  done
  # 动态兜底提示：新件若硬写 anolis 路径而尚未人工核类——只提示不判色
  # （启发式扫全文本含注释；本脚本自身与在役远端依赖件的注释也会命中，故仅提示）
  local cand known f unclassified=""
  cand=$(grep -l "/data/bench\|/data/af-factory" "$TOOLS"/*.py "$TOOLS"/*.sh 2>/dev/null \
         | sed "s|$WS/||" | grep -v "^tools/all-gates.sh$" || true)
  for f in $cand; do
    known=0
    for e in "${ANOLIS_ONLY[@]}"; do [ "${e%%|*}" = "$f" ] && known=1; done
    [ "$known" = "0" ] && unclassified="$unclassified $f"
  done
  print_gate L1
  if [ -n "$unclassified" ]; then
    echo "  [提示] 以下件文本中含 anolis 路径、未人工核类（在役远端依赖件的注释多在此列，"
    echo "         不是门红也不是门绿；新增件需人工判是否本机可跑）：$unclassified"
  fi
  echo "  [说明] 远端依赖件（event-router/factory-scheduler/report-feeder/mcode-dispatch/"
  echo "         cnb-relay/egress-gw-check/escrow-*/cb-* 等）本机在役可跑，门不执行它们，"
  echo "         其行为由 L2/L3 的对口回归件覆盖；上表 SKIP 行的才是本机不可跑件。"
  echo "  [说明] order-stages.py 活采模式数据源在 anolis，但有 --replay <orders-dir> 本机"
  echo "         回放模式（只读本机目录），故不列 anolis-only；bearer-proxy 运行面待核。"
}

# ---------------------------------------------------------------- L2 单测门（注册）
register_L2() {
  local f base tmo found=0
  shopt -s nullglob
  for f in "$TOOLS"/test-*.py; do
    found=1
    base="$(basename "$f")"
    tmo=180
    # 长杆两项（2026-10-31 DEB-5 按实测重标；口径：预算 > 实测 p95×2）：
    #   test-kb-content-parity.py   真 registry 全量对账（工作量 ∝ registry 原子数，
    #       registry 在涨：29434 原子（19:40）→ 33601 原子（00:55），门耗同步上涨）
    #       空载单跑 p50/p95 = 558.0/560.3s（3 轮直跑，rc 全 0）
    #       8 路并行池 p50/p95 = 574.7/661.3s（3 轮同跑，rc 全 0）
    #       在役重载（外来 12 进程 sweep 并发，load 10~20）单跑 = 1015s（rc=0，4/4 绿）
    #       池内最坏观测 > 1440s（2026-10-31 20:13 那次跑，1440s 帽被掐）
    #       预算须 > 池内最坏观测并留余量 → 取 2400s（=池内最坏 ×1.67 / 单跑 ×2.36）
    #   test-router-kb-ingest.py    端到端接线
    #       空载 p50/p95 = 286.8/288.4s → 并行池 p50/p95 = 359.8/444.8s
    #       在役重载池内观测 = 565s / 787s（两次跑）→ 预算取 1500s（≥最坏 ×1.9）
    # 注意：自适应帽 = 剩余预算-10s，故 GLOBAL_BUDGET_MS 必须 > 最长杆+10s，否则这里的
    # 基础超时拿不到（2026-10-29 收口批校准预算，2026-10-31 两度再校准，见文件头注释）。
    # registry 从 15339 涨到 17986 verified（+17%）是重标根因：旧 300s/240s 预算在并行池
    # 下必然掐死长杆（历史红：parity 274s / router 240s 超时 FAIL）。2026-11-01 DEB-5a：
    # 静态帽落地当天即再被击穿（verified 17986→23498、+30%/40h、parity 2400s 帽被掐假红）。
    [ "$base" = "test-kb-content-parity.py" ] && tmo="${PARITY_TMO:-2400}"   # DEB-5a：主流程按 registry 实测外推；缺省回落本校准基线 2400s
    [ "$base" = "test-router-kb-ingest.py" ] && tmo="${ROUTER_TMO:-1500}"   # DEB-5a：同上（R4 全量导 verified 层，工作量∝registry）；缺省回落 1500s
    # RT-kbquote（2026-11-02）：KB 引文对账门（quote_check 机械真值的存量常驻化）。
    # 红队确证：存量 1,330 条 verified∧sandbox 引文逐字不在证据缓存（空白归一化后仍
    # miss 1,137），此前无门可测（grep quote_check 本文件=0）——存量已由清洗件
    # tools/kb-quote-purge.py 净化（registry rejected + kb retired，provenance 留痕），
    # 本门常驻防复污：新 admit 的坏引文（quote_check 搭车）即红。空载实测 4.7~14.6s，
    # 工作量∝verified∧sandbox 原子数与证据缓存规模，重载按 40× 余量取 600s。
    [ "$base" = "test-kb-quote-integrity.py" ] && tmo="${QUOTE_TMO:-600}"
    add_item L2 "$base" "$tmo" "python3 '$f'"
  done
  shopt -u nullglob
  # RT-E5b（2026-11-02）：单件摘除清单对账门（tools/test-manifest.list）。
  # 发现（红队 RT-E5 复核实证）：上面「found=0 才红」只堵全删——删单个 test-*.py
  # 仍是静默绿：glob「存在即注册」没有期望清单对账，删一件=汇总表少一行、
  # nfail 不变、exit=0（2026-11-02 04:14 真仓全绿基线 PASS=19 实证，rm 单件后同跑
  # 照绿）。修法（最小，不动任何既有断言）：以 tools/test-manifest.list 在列件逐一
  # 对账，缺一件即 FAIL 并点名文件名——摘门必须显式改清单并留说明，不得静默放行；
  # 清单件自身缺失同样红（防「先删清单再删件」绕过）。
  local mf="$TOOLS/test-manifest.list" mbase listed missing=""
  L2_UNLISTED=""
  if [ ! -f "$mf" ]; then
    record_item L2 "test-manifest.list" FAIL 0 \
      "门件清单缺失：$mf 不在位，无法对账单件摘除（清单与被测件须同在——摘门须显式对账，不得静默放行）"
  else
    while IFS= read -r mbase; do
      case "$mbase" in ''|'#'*) continue ;; esac
      L2_ROSTER_NAMES+=("$mbase")
      listed=0
      for f in "$TOOLS"/test-*.py; do
        [ "$(basename "$f")" = "$mbase" ] && { listed=1; break; }
      done
      [ "$listed" = "0" ] && missing="$missing $mbase"
    done <"$mf"
    if [ -n "$missing" ]; then
      record_item L2 "test-manifest.list 对账" FAIL 0 \
        "清单在列门件缺件：$missing（tools/test-manifest.list 对账红——删单件不再静默绿，摘门须显式改清单并留说明）"
    fi
    # 新增件未列入清单 → 照常注册实跑（新增只会加覆盖，不判红），但提示补录：
    # 未列名件被删不触发对账红，清单须保持与在役件同步。
    for f in "$TOOLS"/test-*.py; do
      [ -e "$f" ] || continue   # 全删时 nullglob 已关，glob 保持字面量——不把它当新增件
      base="$(basename "$f")"; listed=0
      while IFS= read -r mbase; do
        case "$mbase" in ''|'#'*) continue ;; esac
        [ "$mbase" = "$base" ] && listed=1
      done <"$mf"
      [ "$listed" = "0" ] && L2_UNLISTED="$L2_UNLISTED $base"
    done
    # --- RT-E84②：清单在列数自声明对账（清单改动须显式同步声明行） ---
    # 发现（红队 RT-E84 确证）：上面那段只钉单边——「清单在列件缺件」红，但
    # 「删件 + 同时删清单行」两侧同步缩小：汇总表少一行、nfail 不变、exit=0
    # （2026-11-02 沙箱实证：删 test-kb-content-parity.py 且删其清单行 → PASS 12→11、
    # 零红、exit=0）。补两道对账把「两侧同缩」钉死：
    #   ①自声明对账：在列行数 ≡ 声明行 #L2_ITEMS_COUNT（清单改行数不改声明 → 红）
    #   ②变更留痕对账：清单 sha256 须已登记在 计划/变更日志.md（RT-E84④）
    local mf_rows decl_rows msha clog
    mf_rows="$(manifest_rows)"
    decl_rows="$(manifest_decl L2_ITEMS_COUNT)"
    case "$decl_rows" in
      ''|*[!0-9]*)
        record_item L2 "test-manifest.list 自声明对账" FAIL 0 \
          "清单缺可用的 #L2_ITEMS_COUNT 自声明（读到 '${decl_rows}'）——清单须显式声明在列件数（RT-E84②）" ;;
      *)
        if [ "$PINS_OK" != "1" ]; then
          record_item L2 "test-manifest.list 自声明对账" FAIL 0 \
            "钉桩面不可读或取值非法（tools/gate-pins.list：L2_MIN_ITEMS='${L2_MIN_ITEMS}'）——件数下限无从对账（fail-closed，不得回退门本体兜底值；RT-CI门本体）"
        elif [ "$decl_rows" -ne "$mf_rows" ]; then
          record_item L2 "test-manifest.list 自声明对账" FAIL 0 \
            "在列 $mf_rows 件 ≠ 自声明 L2_ITEMS_COUNT=$decl_rows——清单增删行须同步改声明行（删件并删清单行两侧同缩即红，RT-E84②）"
        elif [ "$decl_rows" -lt "$L2_MIN_ITEMS" ]; then
          # 在列数被下调到钉桩面钉值之下 = 摘门未同步钉值（改钉值须改钉桩面 + 登记
          # 留痕 + 重锚，三处缺一即红——不再是「改门=纪律红线」的无版本面自证）
          record_item L2 "test-manifest.list 自声明对账" FAIL 0 \
            "在列 $mf_rows 件 < 钉桩面钉值 L2_MIN_ITEMS=$L2_MIN_ITEMS 件——摘门须同步更新钉桩面（tools/gate-pins.list 的 L2_MIN_ITEMS）并重锚登记，不得只改清单（RT-E84②）"
        elif [ "$decl_rows" -gt "$L2_MIN_ITEMS" ]; then
          # 钉桩面钉值落后于在列数 = 新增门件未同步钉值：单件删除存在 1 件盲区
          # （有效下限取 max(钉值, 声明)=声明，故新件仍受保护；但若有人再删一件
          #   并同步下调声明到钉值，钉值即兜不住 → 提示补钉值，不判红避免误红）。
          record_item L2 "test-manifest.list 自声明对账" PASS 0 \
            "在列 $mf_rows 件 ≡ 自声明 L2_ITEMS_COUNT=$decl_rows（提示：钉桩面钉值 L2_MIN_ITEMS=$L2_MIN_ITEMS 落后 $((decl_rows - L2_MIN_ITEMS)) 件——新增门件须同步更新 tools/gate-pins.list 的 L2_MIN_ITEMS，否则单件删除有该件数盲区）"
        else
          record_item L2 "test-manifest.list 自声明对账" PASS 0 \
            "在列 $mf_rows 件 ≡ 自声明 L2_ITEMS_COUNT=$decl_rows ≡ 钉桩面钉值 L2_MIN_ITEMS"
        fi ;;
    esac
    # ②变更留痕对账（RT-E84④）：tools/ 与工作区根都不在任何 git 仓内
    # （git -C tools rev-parse → fatal: 不是 Git 仓库），清单改动零版本面可审计；
    # 唯一留痕面 = 变更日志。故要求：清单当前 sha256 须已登记在 计划/变更日志.md
    # （登记串：test-manifest.list sha256=<64位hex>）——未登记即红（清单被改过）。
    msha="$(manifest_sha)"
    clog="$WS/计划/变更日志.md"
    if [ -z "$msha" ]; then
      record_item L2 "test-manifest.list 变更留痕对账" FAIL 0 \
        "无法计算清单 sha256（sha256sum 不可用或清单不在位）——清单变更留痕无从对账（RT-E84④）"
    elif [ ! -f "$clog" ]; then
      record_item L2 "test-manifest.list 变更留痕对账" FAIL 0 \
        "变更日志不在位（$clog）——清单变更留痕无从对账（RT-E84④：清单改动须登记留痕）"
    elif grep -qF "test-manifest.list sha256=$msha" "$clog" 2>/dev/null; then
      record_item L2 "test-manifest.list 变更留痕对账" PASS 0 \
        "清单 sha256=${msha:0:12}… 已登记在变更日志（留痕在位）"
    else
      record_item L2 "test-manifest.list 变更留痕对账" FAIL 0 \
        "清单 sha256=$msha 未登记在变更日志——清单被改动但未留痕（登记串：test-manifest.list sha256=$msha；RT-E84④：本目录无 git，清单改动零版本面可审计）"
    fi
    # --- RT-L2身钉（2026-11-03）：在列门件内容钉对账（同名恒绿桩替换即红）---
    # 发现（红队已确证发现）：在册 L2 门件零内容钉——钉桩面钉值全为 L3/L5/L6 探针
    # 与门本体，无一为 tools/test-*.py；名册/自声明/件数三面对账只钉名与数、不钉身，
    # 把任一件换成同名恒绿桩（import sys; sys.exit(0)）照常注册、照常在列、桩 PASS、
    # 全门 exit=0（沙箱端到端实证）。修法（最小：复用既有钉桩面 + refresh 重锚机制，
    # 同 af 仓 ci 门族「名册+sha 钉」先例）：在盘 test-*.py 全部入钉桩面
    # （tools/gate-pins.list 的 sha256 行），本项对在列件逐件对账——
    #   · 在列件缺钉行/钉值非法 → 红（fail-closed：无钉=无法证身，不猜绿）；
    #   · 实时摘要 ≠ 钉值 → 红（同名恒绿桩/改身未重锚即红；重锚=bash
    #     tools/gate-pins-refresh.sh：变更日志登记 + 工作区外外置锚，工作区内
    #     「换桩+自签」链到此为止）。L3 常驻项 gate-pins-check.sh 对钉面全行同款
    #     对账（双消费面）。维护契约：新增在册门件 → 清单行 + #L2_ITEMS_COUNT +
    #     L2_MIN_ITEMS + 钉桩面钉行 四处同步，改后跑 tools/gate-pins-refresh.sh。
    local pins="$GATE_PINS_FILE" prow pfound plive pname nmiss="" npinned=0
    if [ ! -f "$pins" ]; then
      record_item L2 "在列门件内容钉对账" FAIL 0 \
        "钉桩面不在位（$pins）——在列门件内容钉无从对账（fail-closed：同名恒绿桩无从抓；RT-L2身钉）"
    else
      while IFS= read -r pname; do
        case "$pname" in ''|'#'*) continue ;; esac
        pfound=""
        while IFS= read -r prow; do
          case "$prow" in
            "sha256 tools/$pname "*) pfound="${prow#"sha256 tools/$pname "}"; break ;;
          esac
        done <"$pins"
        case "$pfound" in
          ''|*[!0-9a-f]*)
            nmiss="$nmiss $pname(缺钉行或钉值非法)" ;;
          *)
            if [ "${#pfound}" -ne 64 ]; then
              nmiss="$nmiss $pname(钉值长度异常)"
            else
              plive="$(sha256sum "$TOOLS/$pname" 2>/dev/null | cut -d' ' -f1)"
              if [ -z "$plive" ]; then
                nmiss="$nmiss $pname(被验件不可读)"
              elif [ "$plive" != "$pfound" ]; then
                nmiss="$nmiss $pname(摘要漂移：实时${plive:0:8}…≠钉${pfound:0:8}…)"
              else
                npinned=$((npinned + 1))
              fi
            fi ;;
        esac
      done <"$mf"
      if [ -n "$nmiss" ]; then
        record_item L2 "在列门件内容钉对账" FAIL 0 \
          "在列门件内容钉缺失/漂移：$nmiss——同名恒绿桩替换或改身未重锚即红；重锚唯一合规动作 bash tools/gate-pins-refresh.sh（钉桩面 tools/gate-pins.list；RT-L2身钉）"
      else
        record_item L2 "在列门件内容钉对账" PASS 0 \
          "在列 $npinned 件全部有钉桩面钉行且实时摘要一致（tools/gate-pins.list 身钉；同名替换/改身未重锚即红；L3 gate-pins-check.sh 双消费面；RT-L2身钉）"
      fi
    fi
  fi
  [ "$found" = "0" ] && record_item L2 "tools/test-*.py" FAIL 0 \
    "L2 门本体缺失：无 test-*.py 件（被测件全被删/目录不对——摘门须显式对账，不得静默放行）"
}

# ---------------------------------------------------------------- L3 selftest 门（注册）
register_L3() {
  local before=${#ITEMS[@]} target
  add_item L3 "b-canon.py --selftest" 180 \
    "python3 '$WS/计划/研究组/B线核心批-20261029/tools/b-canon.py' --selftest"
  add_item L3 "b-pick-claims.py --selftest" 120 "python3 '$TOOLS/b-pick-claims.py' --selftest"
  add_item L3 "b-verdict-unique.py --selftest" 120 "python3 '$TOOLS/b-verdict-unique.py' --selftest"
  add_item L3 "card-lint.py --all" 180 "python3 '$TOOLS/card-lint.py' --all"
  add_item L3 "publish-scrub-gate.py --selftest" 120 "python3 '$TOOLS/publish-scrub-gate.py' --selftest"
  add_item L3 "ch-mes-reconcile.py --selftest" 120 "python3 '$TOOLS/otel/ch-mes-reconcile.py' --selftest"
  add_item L3 "otlp-assert.py --selftest" 120 "python3 '$TOOLS/otel/otlp-assert.py' --selftest"
  # --sidecar 项语义变更（2026-11-02 RT 修复批）：断言器新增「判定记录数」记账，
  # 0 条记录求值的断言记 VACUOUS 且不计 PASS；覆盖不全（语义层总体为空）→ rc=2
  # （非零即红，不标绿）。此前该载荷只含 1 个 factory span，R4/A5/N2/S1~S7 等 10 条
  # 断言在空集上求值却计入 PASS=26——真空绿。此项在语义层投影器落地前将持续红，
  # 这是真实缺口（无语义层 span 生产者）的机器化暴露，不是回归。
  add_item L3 "otlp-assert.py --sidecar" 120 "python3 '$TOOLS/otel/otlp-assert.py' --sidecar"
  # OTel 全订单名册覆盖门（2026-11-02 RT 修复批接入）：「名册有项」≠「生产有 span」——
  # 名册 9 项（语义层 4 + 工厂族 5）此前无任何一层逐项回查生产面（断言层三模式碰不到
  # 语义层四个名字；--sidecar 只复原 1 个名册项；ch-mes-reconcile 只按 ServiceName 计数）。
  # 本门=真库逐名册项近窗入库计数下界 + 订单级键在位（判据源=span-conventions.md §6
  # production 块，唯一源；断言层实现，见 tools/otel/otlp-assert.py --production）。
  # 门内跑零网络消费面 --production-check（只读状态面 状态观测/otel-production.json，
  # 由 tools/otel/otlp-assert.py --production 定时跑落盘，cron 每 15min 一轮）——
  # 末次判定红即红、**读数过期即红**（死手断言：巡检停摆=静默无人见）、状态面缺件/
  # 坏 JSON → rc=2 不可证不猜绿。与 otel-reconcile-probe --check 同构。
  add_item L3 "otlp-assert.py --production-check（全订单名册覆盖·真库消费面）" 60 \
    "python3 '$TOOLS/otel/otlp-assert.py' --production-check"
  # G9 方法论锚点常驻门（2026-11-01 接入）：方法论文档全部 文件:行/commit 锚点机检，
  # 锚点漂移（后续改文件移行）即时红——防「文档锚点烂掉没人知道」。
  add_item L3 "方法论 anchor-check（锚点全解析）" 120 "python3 '$WS/计划/研究组/方法论批-20261031/anchor-check.py'"
  # 裁决回写核对门接线（2026-11-03 J5·RT-E164②，先清登记后接线——①补登记 10 条裁决行
  # 回写清单已于本批落地并 standalone exit=0；此前本门零消费面：all-gates/obs-patrol/
  # crontab grep=0，RT-PP3 教训〔裁决只落裁决书、正本与执行记录相反仍可并存〕复发面）。
  # 实扫腿：两条台账全部裁决行——未登记回写清单=红、登记项缺件/锚未命中/mtime 倒挂=红；
  # selftest 腿：夹具自证判别力（红路/绿路/$HOME 临时件，不碰真台账）。
  add_item L3 "writeback-check.py --selftest（裁决回写核对判别力自证）" 60 "python3 '$TOOLS/writeback-check.py' --selftest"
  add_item L3 "writeback-check.py（裁决回写核对·两条台账实扫）" 60 "python3 '$TOOLS/writeback-check.py'"
  # 账本纪律接线（2026-11-04 止增门接入allgates批）：账本机制批交付的两件门件进常驻判定面。
  # 分层理由：它们是「账本纪律」（台账↔台账/基线的对账与草案生成），不是 L1 语法、
  # L2 单测、L5/L6 部署面——与 writeback-check.py（裁决回写核对·台账实扫）同族，
  # 故接 L3、沿用其「常驻实扫 + --selftest 判别力自证」接线形态（不自创一套）。
  #   · 止增门（tools/ledger-growth-gate.py）：增量口封堵——只判**基线之后新增**的
  #     逃逸台账条目有无欠账行/豁免（基线=30-工件/账本机制批-20261104/
  #     ledger-growth-baseline.json，235 条快照 @2026-11-04T01:13:54）；存量 235 条
  #     不判（存量清偿=迁移门 tools/test-ledger-migration-recon.py 的事，两门互不
  #     点名是设计意图）。缺件/坏基线/台账缺件/id 重复 ⇒ rc=2 非零即红（run_item
  #     口径，fail-closed 语义不放宽）；新增未迁未豁免 ⇒ rc=1 红。命名纪律：不带
  #     test- 前缀（件 docstring 自记），不进 L2 glob，L2 件数钉值不受影响。
  #   · 收卷草案生成器（tools/ledger-close-draft.py）：只接 --selftest 判别力自证，
  #     **不接无参草案实跑**——本件 docstring 自记「收卷时人工调用的生成器，不进
  #     常驻判定面」，且其无参 exit 1=有草案行（收卷时正常态，待人工审定入账），
  #     非门违规；把「有草案行」接成红=与迁移门（存量）/止增门（增量）对同一 id
  #     重复点名，正是两件设计里要避免的打架形态。生成器自身的判别力（出草案/
  #     覆盖豁免判定/fail-closed rc=2 零草案/零完成态措辞/幂等）由 selftest 常驻钉住。
  #   · 接线核对（2026-11-04 实测）：两件无参真台账跑止增门 rc=0（新增 0 条、存量
  #     235 不判）、草案 rc=0（草案行 0 条）；两件 --selftest rc=0（20/20、14/14）。
  add_item L3 "ledger-growth-gate（止增门·基线后新增逃逸台账条目实扫）" 60 "python3 '$TOOLS/ledger-growth-gate.py'"
  add_item L3 "ledger-growth-gate --selftest（止增门判别力负向自测）" 60 "python3 '$TOOLS/ledger-growth-gate.py' --selftest"
  add_item L3 "ledger-close-draft --selftest（收卷草案生成器判别力自证）" 60 "python3 '$TOOLS/ledger-close-draft.py' --selftest"
  # G9-3 分母②③腿对账门（2026-11-03 接入，RT-E189 同类逃逸修复批，常驻非 selftest）：
  # 判据 G9-3 的②「总数对账」③「零漏覆盖」两腿此前全仓零机器调用点（tools/ 状态观测/
  # af/ kb/ grep、crontab、本文件均零命中，映射 G9 行只跑①+schema）——判据落定 4h 内
  # 同仓批增锚未同步登记值（静态登记 121 vs 实况 122→123/独立面 84→85），②腿现值红而
  # 无人跑：防自指闸当日被同类逃逸穿透。本门＝②③腿的机检 runner：静态登记分母
  # （criteria.yaml G9-3 denominator.value，权威）≡ 机检「正文锚点总数」≡ 独立面
  # 全路径锚+短式拆解逐项对账，且 anchor-coverage-check.py 零漏覆盖须过；漂移即红
  # （增删锚须同步上抬/下调登记值并重跑覆盖检查），登记件缺席/不可解析 rc=2 不猜绿。
  # 判别力负控（--selftest）：登记值陈旧副本/正本倒退存照两条逃逸路径必须红。
  add_item L3 "g93-denom-recon（G9-3 分母②③腿对账门）" 120 \
    "python3 '$WS/计划/研究组/方法论批-20261031/g93-denom-recon.py'"
  # SIL 裁决产出腿常驻门（2026-11-02 接入）：只读 状态观测/loop-state.json 镜像真实性
  # 门读数，「全部镜像源被拒用=裁决产出停摆」显式红——此前本脚本无任何 sil 门位
  # （grep 'sil|self-improve'=0），产出腿停摆期环活性读数（keepalive 新鲜度+60s 心跳、
  # 轮次、队列）全绿失真（2026-11-02 实证：00:13 双源拒用后 3.5h+ 巡检面零红）。
  # 非 selftest，同 anchor-check 常驻门先例；源恢复机制性只读后自动翻绿。
  add_item L3 "sil-verdict-probe（SIL 裁决产出腿门）" 60 "python3 '$TOOLS/sil-verdict-probe.py'"
  # 在役进程版本对账门（2026-11-03 接入，红队终局轮确证发现「在役 event-router 守护
  # 载旧码」修复批，常驻非 selftest）：此前全仓**零**机检把「在役进程跑的是哪一版」
  # 与「盘上是哪一版」对账——RT-E157/RT-E160/RT-E169 三批修复整批只落本地、在役守护
  # 仍跑 17:58 旧码 30h+ 无人发现，88 条冻结账被旧码防重放永久冻结、63 条原子永远停
  # 在非 verified，而变更日志按「已生效」记账（虚记生产生效）。逃逸台账 RT-E103:848
  # 自记该机制①②③「均未见施工」、目的-监测项映射零行、all-gates 零门项。
  # 本门＝那道缝的机检（只读、不换码）：受管在册守护（router/self-improve-loop，两者
  # 均有版本钉机制）的「在役载入指纹 ≡ 盘面 sha256」+「进程启动时刻 ≥ 盘面源码 mtime」
  # 双证对账；漂移即红、不可证 rc=2 不猜绿、不静默 SKIP。另带判别力负向自测
  # （--selftest，纯夹具零改动真树）——钉住「本门能测出版本漂移」，防退化成真空门。
  add_item L3 "live-daemon-version-probe（在役进程版本对账门）" 60 \
    "python3 '$TOOLS/live-daemon-version-probe.py'"
  add_item L3 "live-daemon-version-probe --selftest（在役版本对账门判别力负向自测）" 60 \
    "python3 '$TOOLS/live-daemon-version-probe.py' --selftest"
  # anolis 部署一致性探针判别力负向自测（2026-11-03 RT 批接入，常驻非 live）：
  # 红队确证：anolis 部署面（四件在役 + 两常驻守护）此前零常态机检——L1 四件
  # anolis-only 恒 SKIP、live-daemon-version-probe 名册 6 件全本机守护、L5 原两腿只
  # 对账 gov，「修复落盘≠anolis 在役」复发无门能红（现势 sha256 对齐系修复批一次性
  # 手工换码重启，非机检所系）。本体 tools/anolis-deploy-consistency-probe.sh
  # （L5 anolis 腿），本自测在沙箱 PATH 注入桩 ssh 按夹具回放：红路（sha 漂移／换码
  # 未重启／在役缺件／守护失联／ssh 不可达／读数坏）必红、绿路对照必绿——钉住
  # 「探针能测出 anolis 部署面漂移」，零触达真 anolis。
  add_item L3 "anolis-deploy-consistency-probe --selftest（anolis 部署对账判别力负向自测）" 60 \
    "bash '$TOOLS/anolis-deploy-consistency-probe.sh' --selftest"
  # 公网入口安全巡检门（2026-11-02 接入，红队终局轮确证发现修复批，常驻非 selftest）：
  # 逃逸台账 RT-E46②「对每个公网入口并发探针断言 429 出现（限速在役证明）」此前零
  # 施工——grep '429|rate_limit|path-as-is' 本文件全 0。RT-E46 病根=限速按「入口块」
  # 配置：jobs. 块 120/min 在役，ai./af-jobs 经 Higress 的镜像入口（Caddyfile 无此块，
  # 反代拓扑不可从本机静态审计）一度零限速，使 jobs. 侧限速形同虚设；行为面巡检
  # （并发打 /healthz 断言 429）是唯一与「对称性」本体对齐的机检面，不依赖反代拓扑。
  # 探针（tools/rate-limit-symmetry-probe.py）两腿/入口：A 穿越无泄露（--path-as-is
  # 等价原样路径 12 变体；契约口径按登记册 contract_mode 分档：门户/演示站=200 体
  # 必须逐字节=公开契约参照件，otlp.=未认证面必须 401 且变体不得 200——RT-E47 部署侧腿）
  # + B 限速对称（131×并发 {probe_path}，恰超 120/min 帽，≥1×429）。打生产面 self-limit：
  # 只 GET、零写端点、每入口每轮 ≤145 请求、总数 ≤725（五入口×144；同量级为 RT-E46
  # 红队确证时已用过的 140×3 打压）；入口登记册=正本 tools/public_entry_registry.py
  # （五入口：新公网反代入口必登记，RT-E46③ 机检替身；「配置面新增限速口未登记」
  # 由 L6 E 腿 public-entry-registry-check.py 对账判红——缺登记=巡检盲区）。

  # 门户本体三面（穿越/token 一次性/竞态）回归在 L2 test-portal-attack-surface.py
  # （本地隔离实例）；在役=本地版本一致性由 L5 部署一致性门兜底。
  add_item L3 "rate-limit-symmetry-probe（公网入口限速对称+穿越巡检门）" 240 \
    "python3 '$TOOLS/rate-limit-symmetry-probe.py'"
  # G10 机算正本值级对账门（2026-11-02 接入，红队终局轮确证发现修复批）：
  # 原 G10 监测手段只数 numbers json 的 `value` 键个数（恒 73）——键数与「键值是否失真」
  # 无因果关系；且本脚本此前 grep 'numbers-sota' = 0 命中（无任何门解析该机算正本）→
  # 正本多条键值已与现势不符（策略库 60→61、needs_syntax 11→12、KB 卡库 17986/9652/
  # 113/27751→25125/18179/1270/44574、task-seeds 1265→7177…）而无人订阅。
  # 本门=值级复算（判据源=正本自报的 meta.verification 名册，不复制判据）：
  #   ① 值级对账门（非 selftest，常驻门先例同 sil-verdict-probe）：逐条 live 腿跑登记
  #      命令复算并与登记值比对（exact/gte/exact-json/exact-list），漂移即红；全部 73 键
  #      必须被分类（未分类=盲区即红）；live 腿数有下限（堵「降级成 snapshot 消音」）；
  #      snapshot 腿（点时快照，本地不可复算）必须带 as_of+理由且逐条打印明示；
  #      live 腿登记值超时效（默认 168h）即红（活账不刷新=时效失真）。
  #   ①b **报告正文 ↔ 机算正本 值级对账**（2026-11-03 RT-SOTABODY 批新增）：门
  #      **打开差距报告正文**，把正文里的条目数/三态/tier/状态分布/可编译率/分数带
  #      等 **24 条规则**逐条与正本 live 腿登记值比对——漂移即红；**规则未命中
  #      （断言被删改）同样即红**（删断言不得消音）；另加**结论回指键 ↔ live 腿
  #      一致性** 8 条规则（anchor2_verdict/anchor3_verdict 内嵌的条目数/缺口簇数/
  #      终裁计数必须与 live 腿一致）。报告路径钉死在门本体内，在役正本不可覆盖。
  #   ② 判别力负向自测（--selftest，零改动真树：沙箱内跑篡改副本）：红路 21 条必红
  #      （结构腿改值/分区腿改值/单调腿过报/删键/全量降级/未分类 + **改复算命令自证**
  #      /坏钉桩/钉桩缺件/改门本体 + 篡改带值/篡改差距键/篡改复算源摘要
  #      + **报告正文数字漂移/删断言/结论回指键矛盾/报告缺件**，后四条为
  #      2026-11-03 RT-SOTABODY 批新增——正文↔正本对账与结论回指一致性必须**能红**
  #      + **篡改锚1 实测值/翻转锚1 判定串/篡改 anchors_passing/报告锚1 行漂移+翻判定**，
  #      后四条为 2026-11-03 RT-锚1钉值批新增——锚1 判定链快照值钉桩与正文锚1 行
  #      必须**能红**）
  #      + 绿路 2 条对照——钉住「本门**能**测出值失真」，
  #      防它退化成只数键个数的真空门。
  #   ③ 独立钉桩对账（2026-11-03 RT-G10pin 批新增项）：门本体摘要 + 钉桩文件摘要
  #      ≡ 门内钉值（G10_TOOL_SHA256 / G10_PIN_SHA256，见上方常量块）——改门本体
  #      或改钉桩文件未同步留痕即红；这是**门本体之外**的第三锚（门本体自校被删
  #      时仍由本项抓住；先例同 L5 D1b 的 known-good md5 钉桩）。
  add_item L3 "numbers-sota-check.py（G10 机算正本值级对账门）" 120 \
    "python3 '$TOOLS/numbers-sota-check.py'"
  add_item L3 "numbers-sota-check.py --selftest（G10 值级对账门判别力负向自测）" 600 \
    "python3 '$TOOLS/numbers-sota-check.py' --selftest"
  add_item L3 "G10 钉桩对账（门本体+钉桩文件摘要锚）" 60 \
    "t=\$(sha256sum '$TOOLS/numbers-sota-check.py'); t=\${t%% *}; p=\$(sha256sum '$TOOLS/numbers-sota-check.pin.json'); p=\${p%% *}; if [ \"\$t\" = '$G10_TOOL_SHA256' ] && [ \"\$p\" = '$G10_PIN_SHA256' ]; then echo 'OK：门本体摘要与钉桩文件摘要均 ≡ 门内钉值（改门/改钉桩须同步留痕）'; else echo \"RED：门本体或钉桩文件摘要与门内钉值不符（tool=\$t pin=\$p）——改门本体/改钉桩未留痕即红\"; exit 1; fi"
  # 公开分数带「定义列 ↔ 成员集 ↔ 带值」对账门（2026-11-03 RT 批接入，常驻非 selftest）：
  # 本探针此前是**孤儿脚本**——`grep -rn "swev-banddef" tools/ 计划/ 状态观测/` 只命中
  # 探针自身，all-gates/test-manifest.list/crontab 全 0 命中 → 唯一做带定义/成员集
  # 对账的探针无任何机器消费者（事实孤儿）→ 本项给它机器消费面（每轮实跑）。
  # 判据（27 项断言 + 本批新增 13 项值级复算，合计 40 项）：
  #   ① §A/§B 抽行数（8/11）② §D.1 成员表覆盖每行且不多不少 ③ 带值==成员集 min–max
  #   ④ 定义列含成员数与口径关键词 ⑤ 不入带行均有理由 ⑥ 报告/证据件/正本三处一致
  #   ⑦ 回归护栏（键数 73 + 三个差距计算键 79.20/76.80/64.93 未动）
  #   ⑧ **值级复算**（本批新增）：5 个带值按 §D 定义规则从 §A/§B/§C 行表 + §A 论文表
  #      复算、2 个差距键按「带上沿−实测」复算、锚1 判定方向按「实测 vs 2025 同
  #      harness 带下沿」复算且须引用实测值——**分数带这半边从此有值级机检**
  #      （此前锚1 段 28 键全为 snapshot＝零值级机检，篡改带值后 G10 门仍 rc=0）。
  # 本探针同时是 G10 值级门 7 条带/差距 live 腿的**复算命令源**（--emit 模式，
  # 复算源本体 sha256 锚在正本腿登记 tool_sha256 里）。
  add_item L3 "swev-banddef-check.py（公开分数带定义↔成员集↔带值 对账门）" 120 \
    "python3 '$WS/计划/研究组/对标批-20261031/swev-banddef-check.py'"
  add_item L3 "swev-banddef-check.py --selftest（带值判别力负向自测）" 300 \
    "python3 '$WS/计划/研究组/对标批-20261031/swev-banddef-check.py' --selftest"
  # OTel lane 对账实查消费面（2026-11-02 RT 批接入）：ch-mes-reconcile.py 的 R1/R2/R3/R6
  # 是本仓唯一能抓「OTel lane 静默」的规则集，但修复前实查模式零机器消费者——门内只有
  # --selftest 夹具、实查不在任何门、也无调度器（crontab 仅 obs-patrol 一行、
  # systemd --user 无 reconcile 单元）→ 2026-11-01 同窗 MES 侧活着而 OTel 侧零入库
  # （正是 R1 触发条件）却 40h+ 静默无人见。本门=消费面（判据不复制）：
  #   ① 夹具门（零网络）：otel-reconcile-probe.py --selftest —— 消费语义映射自证
  #      （绿/warn/红/执行错/过期死手 + 文件级缺件/坏 JSON/红态/过期 + 绿路对照）；
  #   ② 常驻门（同 sil-verdict-probe 先例，非 selftest）：--check 只读状态面
  #      状态观测/otel-reconcile.json（由 tools/otel/otel-reconcile-probe.py --run
  #      定时跑落盘，cron 每 15min 一轮）——末次判定红即红、**读数过期即红**
  #      （死手断言：巡检本身停摆=静默无人见的正面堵法）、状态面缺件/坏 JSON/执行错
  #      → rc=2 不可证不猜绿。门跑时零网络（CH 可达性由 run 模式承担）。
  add_item L3 "otel-reconcile-probe.py --selftest" 60 \
    "python3 '$TOOLS/otel/otel-reconcile-probe.py' --selftest"
  add_item L3 "otel-reconcile-probe.py --check（OTel lane 对账实查消费面）" 60 \
    "python3 '$TOOLS/otel/otel-reconcile-probe.py' --check"
  # G7 巡检自身健康/事件馈活性门（2026-11-03 确证发现修复批接入，常驻非 selftest +
  # 判别力自测）：obs-patrol（cron 每小时 :17）修复前 ①扫描根事件馈 2026-10-24 起死亡，
  # 「候选=0 退出码=0」恒绿 10 天（死馈/空馈/根被删三态在退出码上与正常不可区分），
  # ②巡检自身零监测项（cron >/dev/null、退出码无消费者、映射全文无一行覆盖）。
  # 修复：obs-patrol.sh 三态判别（根缺=2 执行错 / 空馈·死馈=3 红牌 / 静默但活=0）+
  # 每轮原子写状态面 状态观测/obs-patrol.json、red 追加 alarms.log（obs-feed-silent /
  # obs-patrol-fail，去重）。本门=消费面（与 otel-reconcile-probe --check 同构）：
  #   ① 夹具门（零网络零真树污染）：obs-patrol-probe.py --selftest —— 消费语义映射自证
  #     （ok 两绿路/红两码/执行错/过期死手/缺件/坏 JSON/绿红两向对照）；
  #   ② 常驻门：--gate（= --check 语义 + rc=4 授权退役态的显式消费）——末次判定红即红、读数
  #     过期即红（死手断言）、缺件/坏 JSON/执行错 → rc=2 不可证不猜绿。2026-11-05 夜 obs-gate
  #     批：A5/C4 授权标注已把死馈如实下线为 retired（--check rc=4，非绿非红）——② 改挂
  #     --gate，rc=4 仅授权四环独立复核全过才判绿（fail-closed；判据未删未弱化，详见探针件）。
  add_item L3 "obs-patrol-probe.py --selftest（巡检健康消费面判别力自证）" 60 \
    "python3 '$TOOLS/obs-patrol-probe.py' --selftest"
  add_item L3 "obs-patrol-probe.py --gate（G7 巡检自身健康/事件馈活性消费面）" 60 \
    "python3 '$TOOLS/obs-patrol-probe.py' --gate"
  # af 仓修复耐久性跨树收口门（2026-11-02 RT-E49/E97 批接入，常驻非 selftest）：
  # E49/E6 门族修复曾只存 g0merge/sil-writeback 两条树线，SIL 守护文档自带回滚指令
  # （branch -D sil-writeback + worktree remove）一度会把活跃树修复一并抹掉、按
  # wb_base=phase2 重建出无 fix 树（RT-E97 修复对账栏自记「跨树回放收口门未见」）。
  # 本门=该收口义务机器化（正本=af 仓 phase2 基线，ci/fix_verify.py + 名册
  # ci/fix-verify.duty 随 c483dd2 落库）：
  #   ① 跨树回放：名册在列每棵在役树跑整槽连摘篡改回放（step10/11/12 整槽摘除的
  #      /tmp 副本），xcheck 必须 exit=1 且 [FAIL] gates-g0-erratum——全红才判该树
  #      带修复；对照臂未篡改 run.sh 必须不红。篡改件只落临时目录、仓内零改动。
  #   ② 基线在场（内容级）：修复锚点+收口门本体+numbers.json ci.steps_total 登记
  #      值锚必须在 phase2 基线在场——缺席=重建/回滚即回到无 fix 态，红。
  #   ③ 门族全集单源（2026-11-03 RT-E83 扩面）：对账面派生自 phase2 基线 ref 本身＝ci/ 门码面全集（排除 ci/out/ 运行证据面与 *.bak 历史快照面）+ 判据/证据自指正本（numbers.json/deliverables.yaml/doc-claims.txt）+ 策略正本数据面（strategies/ 全库 + af-dsl 编译断言测试件），各在役树逐件双核对账（提交面 git blob oid + 工作树面 sha256），分叉/缺件/多余件即红；存档/并行树旧门码 fork 须名册显式钉住；仓内工作树漏登记名册即红。〔原实现只对账 ci/xcheck.py 一个门码文件——门族另外 3 个本体与 strategies/ 正本双向分叉时门照绿（假绿：「绿 19 / 红 0」exit=0），2026-11-02 耐久性断口修复只在 g0merge 一棵树（基线与活跃树皆无）〕
  #      口径与门本体 ci/fix_verify.py + 名册 ci/fix-verify.duty 一致（基线 ref 派生对账面，不手填清单——手填清单随门族增删陈年化＝RT-E6/E51「只钉 6 件」同型漏钉）。
  # 正本树缺失时走下方缺件预检记红（不静默放行）。
  add_item L3 "fix-verify（af 仓修复耐久性跨树收口门）" 120 \
    "python3 '$WS/af/ci/fix_verify.py' --repo '$WS/af'"
  # L5 部署一致性门「判别力」负向自测（2026-11-02 RT 收口接入，常驻）：
  # L5 门曾用 note="$(probe 2>&1 | tail -1)" + rc=${PIPESTATUS[0]} 捕获探针退出码——
  # bash 的「命令替换赋值重置 PIPESTATUS」+「命令替换含管道取末段退出码」两处失效
  # 叠加，rc 恒 0：探针任何红（D2 漂移 rc=1 / gov 不可达 rc=2 / 探针缺件 rc=127）
  # 都被门记 PASS、exit=0——真空门，结构上不可能红，而映射 G3 行拿它当机器证据。
  # 本自测在 mktemp 沙箱里跑「真门副本 + 桩探针」，钉住「探针必红 → 门必记 FAIL」，
  # 并带一条绿路对照（防把门改成「恒红」也能骗过红路）。零改动真树；HOME 隔离
  # （沙箱内 all-gates 的单例锁 flock 落在 $HOME/all-gates-logs/，不隔离会与在跑实例
  # 抢锁 → exit 2 假红）。
  if [ -f "$TOOLS/l5-deploy-gate-selftest.sh" ]; then
    add_item L3 "L5 部署门判别力负向自测（探针必红→门必记 FAIL）" 120 \
      "bash '$TOOLS/l5-deploy-gate-selftest.sh'"
  else
    record_item L3 "L5 部署门判别力负向自测（探针必红→门必记 FAIL）" FAIL 0 \
      "缺件：tools/l5-deploy-gate-selftest.sh 不在位（判别力自测本体缺失，记红对账，不静默放行）"
  fi
  # --- RT-CI门本体（2026-11-03）：门本体钉桩完整性对账（常驻消费面）---
  # 本项是「改门 / 改子探针 / 改钉值 ⇒ 红」的机检消费面：钉桩面 tools/gate-pins.list
  # 的摘要须登记在 计划/变更日志.md（登记面＝tools/ 唯一版本面，RT-E84④ 同款口径），
  # 且其中每个 sha256 行须与被验件**实时**摘要一致（子探针被改成恒 exit 0 即红）、
  # 门本体摘要须与钉桩面一致（改门未重锚即红）。fail-closed：钉桩面缺失/不可读即红。
  # 改门/改探针/改钉值后的唯一合规动作：bash tools/gate-pins-refresh.sh。
  if [ -f "$TOOLS/gate-pins-check.sh" ]; then
    add_item L3 "门本体钉桩完整性对账（钉桩摘要登记 + 子探针摘要绑定 + 门本体版本面）" 60 \
      "bash '$TOOLS/gate-pins-check.sh'"
  else
    record_item L3 "门本体钉桩完整性对账（钉桩摘要登记 + 子探针摘要绑定 + 门本体版本面）" FAIL 0 \
      "缺件：tools/gate-pins-check.sh 不在位（钉桩对账本体缺失，记红对账，不静默放行）"
  fi
  # --- RT-E73（2026-11-05）：门日志 per-run 隔离 + 双实例并发自检（常驻）---
  # 逃逸台账 RT-E73 拦截②③：①夹具 per-pid 已落（test-kvfix-verdicts-contract.py:83
  # SCRATCH=kvfix-contract-scratch.<pid>；publish-scrub-gate.py:343-344
  # base=vgate-work/selftest-<pid>）；②双实例同跑互不干扰；③同秒启动不共写日志目录。
  # 本项是②③的机检消费面。DEB-10 flock 单例锁不放宽：--selftest-perrun 在锁前
  # 早退，子实例 HOME 隔离，不抢生产锁。
  add_item L3 "门日志 per-run 隔离双实例自检（同秒零共写 + 旧形态破坏夹具）" 60 \
    "bash '$TOOLS/all-gates.sh' --selftest-perrun"
  # --- RT-CI门本体（2026-11-03）：L6 门判别力负向自测（补 L6 无自测的空洞）---
  # 缺口（红队已确证发现）：L5 有判别力负向自测（tools/l5-deploy-gate-selftest.sh，
  # 桩探针 → 门必记 FAIL），而 L6（caddy 部署面完整性门）全门无任何判别力自测——
  # 「把 caddy-deploy-integrity-probe.sh 改成恒 exit 0」在 L6 侧无人能红。
  # 本自测在 mktemp 沙箱里跑「真门副本 + 桩探针 + 桩登记对账件」，钉住
  # 「探针必红 → L6 必记 FAIL」，并带一条绿路对照（防把门改成恒红也能骗过红路）。
  if [ -f "$TOOLS/l6-deploy-gate-selftest.sh" ]; then
    add_item L3 "L6 部署门判别力负向自测（探针必红→门必记 FAIL）" 120 \
      "bash '$TOOLS/l6-deploy-gate-selftest.sh'"
  else
    record_item L3 "L6 部署门判别力负向自测（探针必红→门必记 FAIL）" FAIL 0 \
      "缺件：tools/l6-deploy-gate-selftest.sh 不在位（判别力自测本体缺失，记红对账，不静默放行）"
  fi
  # --- RT-E58（2026-11-05）：mes-ttl 审计 rc/红牌的机器消费腿 ---
  # 债：逃逸台账 RT-E58 / 阶段欠账台账:39。拦截①②③已落 tools/mes-ttl-sweep.py
  # （①钉死清单数量下界红牌 ②审计失败/缩水 rc 上抛 ③水位行恒带审计表数/承诺表数），
  # 但审计结论此前零机器消费者（本批前 grep -c ttl 本文件=0）。观测面无人消费=没有观测。
  # 本项把只读机读核挂进 L3 族（一次性进程、零新增守护，同 otel-reconcile-probe --check）：
  #   探针 = tools/mes-ttl-audit-consumer.py
  #   --selftest：夹具（往决策点注一条红牌必红、干净必绿；子进程跑本体）
  #   --check：近 N 行决策点 + 近 N 条 otel-readonly-audit 证据；红牌/审计 rc 非零 ⇒ 门红
  # 退出码对齐 run_item :360-365（0=PASS / 2=FAIL / 其余非零=FAIL）；红文案含 FAIL。
  # 判据只增不减：不改 mes-ttl-sweep.py、不改 otlp-assert.py、不改 PIN_MD5。
  add_item L3 "mes-ttl-audit-consumer --selftest（mes-ttl 审计消费腿判别力自证）" 60 \
    "python3 '$TOOLS/mes-ttl-audit-consumer.py' --selftest"
  add_item L3 "mes-ttl-audit-consumer --check（mes-ttl 审计 rc/红牌消费面）" 60 \
    "python3 '$TOOLS/mes-ttl-audit-consumer.py' --check"
  # --- 2026-11-05 发布面接线批 ②P2：两处 tools/trigger-inbox.py 同源纪律的机检 ---
  # 债表 v0.3-T5②/T6③ 行遗留 P2：契约（poc/poc-super-agent/contracts/af.trigger.v1.md
  # + ADR-015 决策 1）要求两处 tools/trigger-inbox.py **逐字同源**（af 仓 tools/ ＝
  # 版本受控正本；工作区级 tools/ ＝ 在役运行位），但此前**零机械保障**：没有 installer、
  # 没有探针（且工作区根不是 git 仓 ⇒ 那份的改动连 diff 都没有）⇒ 改一处忘另一处
  # **静默漂移**、在役跑的不是受控正本那版。
  # 本项把**前批已落盘的只读探针本体**挂进在役门族：
  #   探针本体 = af 仓版本受控正本 tools/trigger-inbox-src-parity-probe.py
  #     （sha256 ec43302ab4ed…；随 origin/product/main 合线；**本批未改其一个字节**）
  #   A 侧＝af 仓正本 tools/trigger-inbox.py；B 侧＝工作区在役运行位同文件名。
  # ★ **零新增守护进程、零新增监听**：一次性只读进程，被既有门轮次调用
  #   （只 sha256 两个文件；不写、不删、不换码）。
  # ★ 探针本体**自身也在钉面**（tools/gate-pins.list 有其摘要行）⇒ 本体有完整性绑定；
  #   改本体未重锚 ⇒ 门本体钉桩对账门（上面的 L3 常驻项）必红。
  # ★ 不改 tools/deploy-consistency-probe.sh 的 PIN_MD5（那是 af-jobs-portal 的锚，
  #   改它＝触发钉桩重锚＝发布面变更）；本批只改门本体一处 ⇒ 已按维护契约重锚。
  add_item L3 "trigger-inbox-src-parity-probe（两处 trigger-inbox.py 同源对账）" 60 \
    "python3 '$WS/af/tools/trigger-inbox-src-parity-probe.py' --a '$WS/af/tools/trigger-inbox.py' --b '$TOOLS/trigger-inbox.py'"
  # task-planner --selftest 2026-10-31 DEB-5 按实测重标：
  #   空载 p50/p95 = 202.1/206.5s（3 轮，rc 全 0）→ 并行池 p50/p95 = 209.9/210.9s
  #   旧预算 240s 对 210.9s 只有 14% 余量 → 并行池下随时可能假红；预算须 > p95×2 = 421.8s
  #   在役重载池内观测 = 233s / 484s（两次跑）→ 预算取 900s（≥最坏 ×1.86）
  #   （该项历史是 rc=1 ACCEPTANCE FAIL[A5]，属真缺陷，已修被测件
  #   tools/task-planner.py，验收断言 A5/A8 未动——见 tools/task-planner.py 的 DEB-5 注释。）
  add_item L3 "task-planner.py --selftest" 900 "cd '$WS' && python3 tools/task-planner.py --selftest"
  # 波次B判据面清偿批新门接线（2026-11-05 门位接线批，九件全绿读数后接入；逐件
  # 自证夹具与施工读数见 30-工件/波次B-*/ 与各自 --selftest；接线条目只增不减）：
  add_item L3 "obs-deadcode-scan-gate（观测面死码扫描门·B2）" 120 "python3 '$TOOLS/obs-deadcode-scan-gate.py'"
  add_item L3 "obs-runtime-guard-gate（观测运行时守护门·B2）" 120 "python3 '$TOOLS/obs-runtime-guard-gate.py'"
  add_item L3 "ci-crosstree-subgate-set-check（跨树集合比较门·B4/RT-E82）" 120 "python3 '$TOOLS/ci-crosstree-subgate-set-check.py'"
  add_item L3 "ci-gatecode-trace-check（门码入库可追溯门·B4/RT-E83）" 120 "python3 '$TOOLS/ci-gatecode-trace-check.py'"
  add_item L3 "g10-live-snapshot-hardaccept（G10 live↔snapshot 硬验收门·B5/C11）" 240 "python3 '$TOOLS/g10-live-snapshot-hardaccept.py'"
  add_item L3 "anchor-inbatch-gate（锚批内同批回填纪律门·B5/C5+E92族）" 120 "python3 '$TOOLS/anchor-inbatch-gate.py'"
  add_item L3 "ledger-greenclaim-recon-gate（账本绿声称对账门·B1）" 120 "python3 '$TOOLS/ledger-greenclaim-recon-gate.py'"
  add_item L3 "test-board-public-surface-recon（公网面×在役面对账门·B3/RT-E112）" 240 "python3 '$TOOLS/test-board-public-surface-recon.py'"
  add_item L3 "bench-retire-obs-review（观测退役评审门·B2/RT-E108）" 240 "python3 '$TOOLS/bench-retire-obs-review.py'"
  # E92 门本体批·处置正本口径「未核=0」门（2026-11-05 施工·E92门本体批新增）：
  #   跑 anchor-check 全量口径取未核两类计数，对账处置正本
  #   30-工件/门红面批-20261105/e92-disposition.json（每条未核锚须在册：kind 合法、
  #   证据非空、豁免件 expiry 未过）；未处置未核锚数 > 0 ⇒ 红。
  #   【2026-11-05 收卷批退役注记】同批既有门（tools/e92-unverified-zero-gate.py，白名单口径）已于收卷批拆接线+撤钉+归档（30-工件/门红面批-20261105/retired-e92-whitelist-gate/），本门（anchor-uncheck-zero-gate 处置正本口径）独存；原「共存，互不覆盖」句失效留痕。
  add_item L3 "anchor-uncheck-zero-gate" 120 "python3 -I '$TOOLS/anchor-uncheck-zero-gate.py'"
  # 缺件预检：目标文件不在位 → SKIP 并说明（不进执行、不猜绿）
  local i spec idx name cmd
  for i in $(seq "$before" $(( ${#ITEMS[@]} - 1 ))); do
    spec="${ITEMS[$i]}"
    IFS='|' read -r idx _ name _ cmd <<<"$spec"
    target=$(printf '%s' "$cmd" | sed -n "s|.*python3 '\([^']*\)'.*|\1|p")
    if [ -n "$target" ] && [ ! -f "$target" ]; then
      record_item L3 "$name" FAIL 0 "缺件：$target 不在位（门本体缺失，记红对账，不静默放行）"
    fi
  done
}

# ---------------------------------------------------------------- L4 集成门（注册）
register_L4() {
  if [ "$RUN_L4" = "0" ]; then
    record_item L4 "kb/verify.py --quick" SKIP 0 "--fast 跳过 L4"
    record_item L4 "task-planner 裸跑" SKIP 0 "--fast 跳过 L4"
    return
  fi
  # L4 超时帽 2026-11-02 DEB-5b 重标+自适应（DEB-57 收尾批；零断言改动、不删任何测试）：
  # 原 240s 是 2026-10-29 校准值且恒定——DEB-5a 只外推 parity/router 两帽，L4 的
  # kb/verify.py --quick 是被漏掉的第四根 registry 成比例长杆（真 registry 全量导入
  # 临时库，工作量 ∝ 台账原子数）。实测链：10-29 35.0s（imported_new=10187，
  # ~/all-gates-logs/20261029-131519/item-19.result「PASS|35021|QUICK PASSED」）→
  # 2026-11-02 本批亲跑独跑 296.21s（imported_new=43304 / verified=25125，QUICK
  # PASSED）——原子 ×4.25、耗时 ×8.5，240s 帽余量 8.9×→0.8×；timeout 240 wrapper
  # 复现 rc=124 必假红（同 DEB-5/DEB-5a 型：长杆按实测重标，不改断言）。修法：
  # 帽 = max(1600, 1600×verified/25125)——锚=本批两实测：独跑 296.21s（16:2x 空载）、
  # 在役重载 796.80s（19:1x load 5~7、在役 kb-ingest 并发，QUICK PASSED）×2=1600
  # （同 router 口径：在役观测 787s→帽 1500=×1.9；600s 帽在 18:59 门内真跑即被掐
  # ——余量按在役负载口径取，不按空载口径取）。随 REG_VERIFIED 线性外推、分钟粒度
  # 向上取整，下限=校准基线 1600s 不松帽。残余边界如实登记：registry 仍日涨，帽再被
  # 击穿时按「在役重载可复跑对账」处置（同 run_item 超时注记口径）。
  if [ -f "$WS/kb/verify.py" ]; then
    add_item L4 "kb/verify.py --quick" "${KBVERIFY_TMO:-1600}" "python3 '$WS/kb/verify.py' --quick"
  else
    record_item L4 "kb/verify.py --quick" FAIL 0 "缺件：kb/verify.py 不在位（门本体缺失，记红对账）"
  fi
  if [ -f "$TOOLS/task-planner.py" ]; then
    # 裸跑（无参数）：验收判据 A1-A8 全过才 exit 0；按设计重写
    # 计划/研究组/沙箱战役备战-20261028/规划-v1.{json,md}（该项固有副作用）
    # 超时帽 240→900s：裸跑做的是与 L3 task-planner.py --selftest 同一套
    # build_plan×2 + acceptance_checks（A1-A8），只多一步落盘；同款负载实测
    # 20261102-102308/item-29.result「PASS|358809|selftest OK」（358.8s）⇒ 240s 帽必假红
    add_item L4 "task-planner 裸跑" 900 "cd '$WS' && python3 tools/task-planner.py"
  else
    record_item L4 "task-planner 裸跑" FAIL 0 "缺件：tools/task-planner.py 不在位（门本体缺失，记红对账）"
  fi
}

# ---------------------------------------------------------------- L3 追加门件：E92「未核=0」门（2026-11-05 施工·E92门本体批）
# **本段刻意置于 L4 段头（:1242）之后**：方法论文档以 `tools/all-gates.sh:604/:720/
# :906/:1242` 锚死各层段头、`:936` 锚死 anchor-check 的 add_item 行、`:6/:10/:21/:30/
# :58/:84` 锚死文件头与退出码口径行——门本体是热改写件，**行号位移即锚点断链**
# （anchor-check 即时红，改锚即改正本）。改门＝改锚点，而方法论正本禁改 ⇒ 本次接线
# 一律追加在既有锚点之后（零位移＝零断链）；后续批若要往本段**前面**插内容，必须
# 同批回填方法论坐标（anchor-inbatch-gate 会按 mtime 归因点名）。
#

# ---------------------------------------------------------------- L5 部署一致性门（2026-11-02 RT 收口）
# 发现：三轮红队修复只落在本地副本 tools/af-jobs-portal.py，gov 在役公网门户
# （jobs.hkmingdajiaoyu.com，gov-host.invalid:/opt/company/af-jobs/af-jobs-portal.py，
# 宿主裸进程 `python3 af-jobs-portal.py`，Oct30 起未重启）仍跑 10-30 pre-RT 版：
# /claim、/report task_id 段校验、claim_token 一次性、revoked 原子写全部缺席；
# 而本脚本只测本地副本（grep af-jobs=0 命中），本地全绿与在役带洞并存——
# 「修了」与「在役修了」之间无任何门。本门把部署面变成常驻红线：本地已修副本
# 与在役副本 md5 漂移即红、在役进程早于部署时刻（换文件未重启=仍跑旧码）即红、
# gov 不可达/缺件也红（与全脚本「缺件/前置不满足也按红点名对账，不静默放行」
# 同口径）。本体 tools/deploy-consistency-probe.sh（绿/红双路 2026-11-02 实测，
# 红路以 pre-RT .bak 冒充本地副本触发 D2红 rc=1 验证判别力）。
# 内联跑（同 L1 秒级先例），不进并行池——不占全局预算、不受预算耗尽 SKIP 影响：
# 部署面一致性没有「今天预算紧就明天再对账」的正当性。
gate_L5() {
  print_gate_head "L5" "部署一致性门（gov 在役 af-jobs-portal ≡ 本地已修副本且已加载生效）"
  local t0 ms rc note out
  t0=$(now_ms)
  # rc 捕获与输出分离（2026-11-02 RT 收口）：原写法
  #   note="$(bash probe 2>&1 | tail -1)"; rc=${PIPESTATUS[0]}
  # 在 bash 里有两处独立失效——① 命令替换赋值本身会重置 PIPESTATUS，
  #   故第 2 行读到的是「赋值语句」自身的退出码（恒 0），不是探针的；
  # ② 即使赋值不重置，命令替换里含管道时其退出码取管道**末段**（tail，恒 0）
  #   的退出码。两者叠加 → 探针 rc 被整个吞掉：探针无论红（D2 md5 漂移 rc=1 /
  #   gov 不可达 rc=2 / 探针本体缺件 rc=127）门都记 PASS、all-gates exit=0
  #   —— 本门在任何失败场景都不可能红（真空门），而映射 G3 行拿它当部署稳定性的
  #   机器证据。修法：先单命令替换取全量输出（无管道 → $? 即探针退出码），
  #   再从输出截最后一行做 note；红绿只看 rc。
  out="$(bash "$TOOLS/deploy-consistency-probe.sh" 2>&1)"; rc=$?
  note="$(printf '%s\n' "$out" | tail -1)"
  ms=$(( $(now_ms) - t0 ))
  if [ "$rc" = "0" ]; then
    record_item L5 "deploy-consistency（gov 在役=本地已修版）" PASS "$ms" "$note"
  else
    record_item L5 "deploy-consistency（gov 在役=本地已修版）" FAIL "$ms" "$note"
  fi
  # 公网静态面实况腿（2026-11-03 RT-45 修复批）：脱敏闸的读数此前只覆盖**本地待
  # 发布暂存树**（scanned=1807），公网在役 static/ 树（实测 1814 件）另有 6 件从未
  # 过闸——服务端静态路由此前只有字符集正则、零发布形状白名单（tools/af-jobs-portal.py
  # _static_path），任何 ASCII 名文件落在 static/ 下即公网直出且不经脱敏。
  # 本腿把「闸的读数」与「公网面实况」绑在一起：在役 static/ 树只读拉回，用**同一份
  # 闸规则**扫一遍（形状白名单 + K/O/X 族内容模式 + 同一份 allowlist），并对账
  # 发布端 PATH_OK ≡ 本地门户 ≡ 在役门户三面一致 + 在役进程已加载（未加载即红）。
  # 探针缺件/不可达/不合形一律红（fail-closed），不静默放行。
  t0=$(now_ms)
  out="$(python3 "$TOOLS/publish-live-surface-probe.py" 2>&1)"; rc=$?
  note="$(printf '%s\n' "$out" | tail -1)"
  ms=$(( $(now_ms) - t0 ))
  if [ "$rc" = "0" ]; then
    record_item L5 "公网静态面实况（gate 读数覆盖在役树+三面白名单一致+在役已加载）" PASS "$ms" "$note"
  else
    record_item L5 "公网静态面实况（gate 读数覆盖在役树+三面白名单一致+在役已加载）" FAIL "$ms" "$note"
  fi
  # anolis 部署面一致性腿（2026-11-03 RT 批接入）：红队确证 anolis 侧部署面零常态
  # 版本对账——L1 四件 anolis-only 恒 SKIP「本机无」、live-daemon-version-probe 名册
  # 6 件全本机守护、本门原两腿只对账 gov；「修复落盘≠anolis 在役」复发无门能红
  # （现势三件 sha256 对齐系修复批一次性手工换码重启所致，非机检所系；调度器自愈
  # 拉起只执行远端件不先 scp——tools/factory-scheduler.py DAEMONS.start——本地改未
  # 同步／远端换件未重启两形态皆无人见）。本体 tools/anolis-deploy-consistency-probe.sh
  # （只读 ssh 对账四件在役 ≡ 本地正本 + burn-runner/stream-tailer 两守护启动≥在役件
  # mtime；ssh 不可达/在役缺件/读数坏按红 rc=2 不静默放行；判别力负向自测 --selftest
  # 在 L3 常驻，零触达真 anolis）。
  t0=$(now_ms)
  out="$(bash "$TOOLS/anolis-deploy-consistency-probe.sh" 2>&1)"; rc=$?
  note="$(printf '%s\n' "$out" | tail -1)"
  ms=$(( $(now_ms) - t0 ))
  if [ "$rc" = "0" ]; then
    record_item L5 "anolis-deploy-consistency（anolis 在役≡本地正本 且 两守护已加载生效）" PASS "$ms" "$note"
  else
    record_item L5 "anolis-deploy-consistency（anolis 在役≡本地正本 且 两守护已加载生效）" FAIL "$ms" "$note"
  fi
  print_gate L5
}

# ---------------------------------------------------------------- L6 caddy 部署面完整性门（2026-11-02 RT-E46 收口批）
# 发现：RT-E46 修复（ai./af-jobs rate_limit + 五轮限速/体帽）只存在于 gov
# /opt/company/platform 未提交工作树（HEAD=7aa5356 2026-10-01，diff 107+ 行），
# 且 all-gates 零护栏（grep 'Caddyfile|rate_limit|429'=0）——一次 git
# checkout/reset --hard 即静默回退零限速态而全门照绿；当日更实盘抓到第二类漂移：
# caddy 单文件 bind mount 钉「容器启动时 inode」，rename/scp 型写入后 reload 读旧
# inode——10-03 起的全部体帽「已写未加载」从未在运行态生效（18:49:52 修复激活）。
# 本门三腿（本体 tools/caddy-deploy-integrity-probe.sh，秒级、零公网流量，内联同
# L5 先例——部署面完整性没有「今天预算紧就明天再对账」的正当性）：
#   A 版本面：gov 工作树 ≡ HEAD（提交前实跑红：status=" M ops/caddy/Caddyfile"；
#     提交 c53f857 后绿——判别力实盘留证，模式⑧「版本面外修复」caddy 侧机检）
#   B 配置钉桩：HEAD 正本+在役挂载源双面五 zone/events 120/体帽 + compose 定制
#     二进制挂载行（防 HEAD 带洞提交 / 重建失 rate_limit 指令）
#   D 加载态：caddy admin API 运行配置断言五 zone+体帽（实跑红→18:49 修复后绿，
#     判别力实盘留证）——行为面（429/穿越）由 L3 rate-limit-symmetry-probe.py
#     （并行批同日施工）常驻，分工不重复。
#   E 登记对账（本批新增，2026-11-03）：配置面五限速 zone ↔ 登记册正本 ↔ 运行时
#     探针入口册三方对账（本体 tools/public-entry-registry-check.py，秒级、只读
#     gov）。修前「配置面知道五口、运行时面只登记三口、otlp./zhihui. 行为零覆盖」
#     且纪律零机检——新增公网口漏登记则三门全绿（巡检盲区）；本腿把
#     「缺登记=巡检盲区」钉成红线（缺登记/登记漂移/探针未消费登记册/配置面自漂
#     四类红），并要求运行时探针不得内嵌第二份手抄入口清单。
gate_L6() {
  print_gate_head "L6" "caddy 部署面完整性门（版本面≡HEAD + 配置钉桩 + admin API 加载态 + 登记对账）"
  local leg t0 ms rc note out
  for leg in A B D; do
    t0=$(now_ms)
    out="$(bash "$TOOLS/caddy-deploy-integrity-probe.sh" --leg "$leg" 2>&1)"; rc=$?
    note="$(printf '%s\n' "$out" | tail -1)"
    ms=$(( $(now_ms) - t0 ))
    if [ "$rc" = "0" ]; then
      record_item L6 "$leg（caddy-deploy-integrity）" PASS "$ms" "$note"
    else
      record_item L6 "$leg（caddy-deploy-integrity）" FAIL "$ms" "$note"
    fi
  done
  # E 腿：公网入口登记对账（配置面 Caddyfile 限速口 ↔ 登记册正本 ↔ 运行时探针入口册）
  t0=$(now_ms)
  out="$(python3 "$TOOLS/public-entry-registry-check.py" 2>&1)"; rc=$?
  note="$(printf '%s\n' "$out" | tail -1)"
  ms=$(( $(now_ms) - t0 ))
  if [ "$rc" = "0" ]; then
    record_item L6 "E（公网入口登记对账）" PASS "$ms" "$note"
  else
    record_item L6 "E（公网入口登记对账）" FAIL "$ms" "$note"
  fi
  print_gate L6
}

# ---------------------------------------------------------------- 反馈梯度批（2026-11-04）件②：三态汇总
# 读本 RUNDIR 的 item-N.json（件①产物）+ 回读 item-N.result 台账行**交叉对账**，产出
# 三态结论：真绿 / 真红 / SKIP（带在案原因）/ 未跑成（无产物、产物损坏或产物≠台账）。
# SKIP 与「没跑成」从此可区分——「退出码不可单独判绿」（v0.3 T5 终裁⑤）有了正面判据：
# 消费方看 summary.json 的三态与台账一致性，不再单看退出码。
# 本段是只读报告面：不进门级 FAIL 计数、不改退出码（退出码语义见文件头，门怎么判未动）；
# 汇总层自身故障时显名警告（无结构化证据 ≠ 绿）。结构化留证落 RUNDIR/summary.json。
structured_rollup() {
  local spec idx g name roster=""
  for spec in "${ITEMS[@]}"; do
    IFS='|' read -r idx g name _ _ <<<"$spec"
    roster+="$idx|$g|$name"$'\n'
  done
  if ! printf '%s' "$roster" | python3 "$SUMMARY_PY" --rundir "$RUNDIR" \
      >"$RUNDIR/structured-rollup.out" 2>"$RUNDIR/structured-rollup.err"; then
    echo ""
    echo "---------------- 三态汇总（结构化产物口径） ----------------"
    echo "  [警告] 三态汇总未产出（汇总层 rc 非零，见 $RUNDIR/structured-rollup.err）——本轮无结构化三态证据，退出码不可单独判绿（v0.3 T5⑤）"
    return 0
  fi
  echo ""
  echo "---------------- 三态汇总（结构化产物口径；SKIP≠没跑成，退出码不可单独判绿——v0.3 T5⑤） ----------------"
  cat "$RUNDIR/structured-rollup.out"
  return 0
}

# ---------------------------------------------------------------- 汇总表
summary() {
  local npass=0 nfail=0 nskip=0 spec idx gate name tmo cmd rf status ms note ms_s
  local rpass=0 rverdict=0 rbudget=0
  for spec in "${ITEMS[@]}"; do
    IFS='|' read -r idx gate name tmo cmd <<<"$spec"
    rf="$(item_result_file "$idx")"
    if [ ! -f "$rf" ]; then status=SKIP; ms=0; note="未执行"
    else IFS='|' read -r status ms note <<<"$(cat "$rf")"; fi
    case "$status" in
      PASS) npass=$((npass + 1)) ;;
      FAIL) nfail=$((nfail + 1)) ;;
      *)    nskip=$((nskip + 1)) ;;
    esac
    # RT-E84②：L2「清单在列」门件的判据计数（未列名新增件不计入下限——它是额外
    # 覆盖，清单补录后即在册受保护）。
    if [ "$gate" = "L2" ] && [ "${#L2_ROSTER_NAMES[@]}" -gt 0 ]; then
      case " ${L2_ROSTER_NAMES[*]} " in
        *" $name "*)
          case "$status" in
            PASS) rpass=$((rpass + 1)); rverdict=$((rverdict + 1)) ;;
            FAIL) rverdict=$((rverdict + 1)) ;;
            SKIP) case "$note" in *全局时限*) rbudget=$((rbudget + 1)) ;; esac ;;
          esac ;;
      esac
    fi
  done
  echo ""
  echo "================ 汇总表（PASS/FAIL/SKIP 及原因） ================"
  printf "%-4s %-44s %-6s %-7s %s\n" "门" "项" "状态" "耗时" "说明"
  printf '%.0s-' {1..104}; echo ""
  for spec in "${ITEMS[@]}"; do
    IFS='|' read -r idx gate name tmo cmd <<<"$spec"
    rf="$(item_result_file "$idx")"
    if [ ! -f "$rf" ]; then status=SKIP; ms=0; note="未执行"
    else IFS='|' read -r status ms note <<<"$(cat "$rf")"; fi
    ms_s="-"; [ "$status" != "SKIP" ] && ms_s="$(( ms / 1000 ))s"
    printf "%-4s %-44s %-6s %-7s %s\n" "$gate" "$name" "$status" "$ms_s" "$(echo "$note" | cut -c1-70)"
  done
  printf '%.0s-' {1..104}; echo ""
  # --- RT-E84②：summary PASS 数下限（清单在列件口径，下限从清单自声明数出） ---
  # 发现（红队 RT-E84 确证）：summary 此前只累加 npass/nfail/nskip 并判 nfail>0，
  # **无任何下限比较**——门项被摘除时 PASS 数下降、nfail 不变、exit=0（静默绿）。
  # 本段补下限：清单在列件逐件计「已产出判据」（PASS/FAIL）数，少于清单自声明
  # 在列数即红。口径说明：
  #   · 只计「清单在列」的件（未列名新增件是额外覆盖，不计入下限，补录清单后即计入）
  #   · 判据口径 = PASS+FAIL（FAIL 本就红，不重复计红）；全 PASS 时即 PASS 数下限
  #   · 全局时限耗尽未启动的项记 SKIP（门没跑完 ≠ 门件被摘）→ 本轮豁免下限并在
  #     结论行显式说明（SKIP 语义见文件头：SKIP 绝不当成绿，故仍列明未判原因）
  local l2floor floor_msg="" budget_note=""
  l2floor="$(manifest_decl L2_ITEMS_COUNT)"
  case "$l2floor" in ''|*[!0-9]*) l2floor=0 ;; esac
  # 有效下限 = max(门内钉值 L2_MIN_ITEMS, 清单声明)：清单声明可被同步下调配合删件，
  # 门内钉值不可（改它=改门=纪律红线）。
  [ "$L2_MIN_ITEMS" -gt "$l2floor" ] && l2floor="$L2_MIN_ITEMS"
  if [ "${#L2_ROSTER_NAMES[@]}" -gt 0 ] && [ "$l2floor" -gt 0 ]; then
    if [ "$rbudget" -gt 0 ]; then
      budget_note="  [说明] 本轮全局时限耗尽，清单在列件有 $rbudget 件未启动（SKIP，原因已注明）——本轮不判 PASS 数下限（复跑该门即判）"
    elif [ "$rverdict" -lt "$l2floor" ]; then
      nfail=$((nfail + 1))
      floor_msg="  - L2 PASS 数下限：清单在列 $l2floor 件中已产出判据 $rverdict 件（PASS=$rpass FAIL=$((rverdict - rpass))）——有在列门件缺件或未跑出判据（删件并删清单行两侧同缩也红，RT-E84②）"
    fi
  fi
  echo "总计：PASS=$npass FAIL=$nfail SKIP=$nskip  总耗时 $(elapsed_s)  日志目录：$RUNDIR"
  [ -n "$budget_note" ] && echo "$budget_note"
  structured_rollup   # 反馈梯度批件②（2026-11-04）：三态汇总（真绿/真红/SKIP/未跑成）——只读产物对账，零门判改动
  if [ "$nfail" -gt 0 ]; then
    echo "结论：有红（FAIL=$nfail）；exit=1。红名单："
    for spec in "${ITEMS[@]}"; do
      IFS='|' read -r idx gate name tmo cmd <<<"$spec"
      rf="$(item_result_file "$idx")"
      [ -f "$rf" ] || continue
      IFS='|' read -r status ms note <<<"$(cat "$rf")"
      [ "$status" = "FAIL" ] && echo "  - $gate $name：$note"
    done
    [ -n "$floor_msg" ] && echo "$floor_msg"
    return 1
  fi
  echo "结论：无红（PASS=$npass；SKIP=$nskip 均已注明原因）；exit=0"
  # 口径标注（2026-11-02 DEB-57 批）：--fast 运行**不执行 L4 集成门**（RUN_L4=0，
  # register_L4 记两条 SKIP「--fast 跳过 L4」）⇒ 本结论只覆盖 L1-L3+L5，**不是全量门
  # （L1-L5）结论**。此前汇总行与全量门的「结论：无红」逐字同形，--fast 结果可冒充
  # 全量门绿（判据 G9-4 的 count_rule 就栽在这：原口径 `all-gates.sh --fast` 结构上
  # 跳过 L4，而判据声称的是「全量门全绿」）。此处显式标注，避免快跑结论被当全量结论用。
  if [ "$FAST" = "1" ]; then
    echo "  [口径] 本次为 --fast 运行：L4 集成门未执行（汇总表 L4 段＝SKIP「--fast 跳过 L4」）——本结论只覆盖 L1-L3+L5，不作全量门（L1-L5）结论；全量口径请亲跑 \`bash tools/all-gates.sh\`（判据 G9-4 口径）"
  fi
  return 0
}

# ---------------------------------------------------------------- 主流程
# RT-E73：自检早退（不抢生产锁、不建生产 RUNDIR）。叶子 --selftest-perrun-child
# 与父 --selftest-perrun 都必须在 flock 之前退出，否则 L3 常驻项在父实例持锁下
# 再起本脚本会被单例锁 exit 2 假红。
if [ -n "$SELFTEST_PERRUN_CHILD" ]; then
  selftest_perrun_child "$SELFTEST_PERRUN_CHILD"
  exit $?
fi
if [ "$SELFTEST_PERRUN" = "1" ]; then
  selftest_perrun
  exit $?
fi

echo "统一门禁 all-gates.sh | WS=$WS | $PYV | 并行=$PAR | 模式=$([ "$ANY_NAMED" = "1" ] && echo 点名 || echo 全量)$([ "$FAST" = "1" ] && echo '(--fast)')"
echo "开始：$(date '+%F %T')"

# ---- 单例锁（2026-11-01 RT-G9-4/DEB-10）：同一台机只允许一个 all-gates 实例在跑 ----
# 发现（假红实测，非推演）：2026-11-01 20:35:38~20:42:16 本机 7 个 all-gates 实例并发
# （~/all-gates-logs/20261101-2035{38,55,58}/20261101-2036{16,19}/20261101-203821/
# 20261101-204216），7×--par8 顶满 16 核——parity 被拉到 2394~2603s（独跑 872~1122s，
# 约×3），router-kb-ingest 内部 kb-ingest 帽被击穿 → item-11 七连红（全部
# 「成功路径返回非 dict：None」）；同一份代码独跑三次全绿（19:14/20:19/21:27）。
# 根因是盒载（并发实例把负载推到 DEB-5 校准包络 load 10~20 之外），不是代码——
# 任何静态或自适应预算都只按包络标定、被包络外负载击穿只是时间问题，G9-4
# 「亲跑 all-gates --fast 须全绿 exit 0」因此随跑时负载翻转、不可复现。
# 修法：flock 非阻塞单例锁——已有实例在跑则立即 exit 2（环境错误，非门红，
# 见文件头退出码口径；宁拒绝误跑、不发假红假绿），等在跑实例结束再跑。
# 预算只约束上限、不改任何断言的纪律不变：本锁消掉「门自身并发」这一负载维，
# 外来（非 all-gates）重载仍按 run_item 注记「在役重载可复跑对账」处置。
# 锁文件放 $HOME/all-gates-logs/（AGENTS.md 纪律 7：/tmp 只放白名单件）。
LOCK_F="$HOME/all-gates-logs/.all-gates.lock"
mkdir -p "$HOME/all-gates-logs"
exec 9>"$LOCK_F"
if ! flock -n 9; then
  echo "FATAL: 已有 all-gates 实例在跑（锁 $LOCK_F 被占），本实例拒绝启动——并发实例会把盒载推到校准包络外，长杆假红（2026-11-01 20:35~20:46 七实例并发 item-11 七连红实证）。等在跑实例结束（ls -t ~/all-gates-logs）再跑。" >&2
  exit 2
fi
# RT-E73：锁拿到之后再分配 RUNDIR——拒跑实例不再留下空时间戳目录；
# 同秒第二实例（若锁被绕过）因 pid 后缀也不会共写。
alloc_rundir || { echo "FATAL: 无法创建 RUNDIR（$HOME/all-gates-logs/<时间戳>-<pid>）" >&2; exit 2; }

# ---- DEB-5a（2026-11-01）：长杆预算按 registry 实测规模自适应 ----
# 发现（假红实测，非推演）：DEB-5 重标（静态 2400s @ verified=17986）落地当天即被击穿——
# 2026-11-01 14:56 亲跑 all-gates --fast，parity 在 2400s 帽处被掐
# （~/all-gates-logs/20261101-145606/item-8.result =「FAIL|2400074|超时 2400s」，
# item-8.log 终态停在 A1/A2/A3 PASS，B 用例未跑出——假红）；而 DEB-5 验收当日两次全量
# exit=0（1090s/990s）。工作量根因（只读直查 kb-seed/registry.db）：verified
# 17986（10-31 00:55，all-gates.sh:60 校准注释自记）→ 23296（11-01 15:2x）→
# 23498（11-01 17:1x）≈ +30%/40h。按此增速，DEB-5 遗留的「按季重标」节奏在数字上
# 不成立。修法（只改预算推导，零断言改动、被测件零改动）：以 DEB-5 校准点
# verified=17986 为基线，把两根 registry 成比例的长杆（parity 2400s——B1/B2 全量扫
# verified 层；router-kb-ingest 1500s——R4 全量导 verified 层）线性外推；全局预算随之
# = 最长杆 +600s（DEB-5 同款余量政策），且不低于 3000000ms 下限。读不到 registry
# （缺件/库锁死）时回落校准基线 2400s/1500s/3000000ms——与 DEB-5 收口态逐字一致。
# task-planner --selftest（L3,900s）是纯夹具自测、与 registry 规模无关，不参与缩放。
# 残余边界（如实登记）：外来负载超过 DEB-5 校准包络（load 10~20，如 11-01 实测
# load 38）仍可能吃掉余量——那时按 run_item 注记「在役重载可复跑对账」处置；本自适应
# 只消掉「registry 规模增长」这一维的假红，不承诺吸收任意负载。
reg_verified() {
  python3 -I - "$WS/kb-seed/registry.db" <<'PY' 2>/dev/null
import sqlite3, sys
try:
    con = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
    print(con.execute("select count(*) from candidates where status='verified'").fetchone()[0])
except Exception:
    print(0)
PY
}
REG_VERIFIED=$(reg_verified)
case "$REG_VERIFIED" in ''|*[!0-9]*) REG_VERIFIED=0 ;; esac
PARITY_TMO=$(( 2400 * REG_VERIFIED / 17986 ))   # 基线：DEB-5 校准点 17986 verified → 2400s
ROUTER_TMO=$(( 1500 * REG_VERIFIED / 17986 ))   # 基线：同上 → 1500s
[ "$PARITY_TMO" -lt 2400 ] && PARITY_TMO=2400   # 下限=校准基线：registry 缩小时不松帽
[ "$ROUTER_TMO" -lt 1500 ] && ROUTER_TMO=1500
# DEB-5b（2026-11-02，DEB-57 收尾批）：第四根 registry 成比例长杆——L4 kb/verify.py
# --quick（真 registry 全量导入临时库，工作量 ∝ 台账原子数）此前恒 240s 不缩放，
# 实测独跑 296.21s / 在役重载 796.80s（load 5~7）均已超旧帽，L4 一执行即超时假红。
# 校准基线：25125 verified → 1600s（=在役重载实测 796.80s ×2，同 router「在役观测
# 787s→帽 1500」口径；600s 帽在 18:59 门内真跑被掐后按在役口径重锚）；同 DEB-5a
# 口径线性外推+下限不松帽。
KBVERIFY_TMO=$(( 1600 * REG_VERIFIED / 25125 ))   # 基线：DEB-5b 校准点 25125 verified → 1600s
[ "$KBVERIFY_TMO" -lt 1600 ] && KBVERIFY_TMO=1600
KBVERIFY_TMO=$(( (KBVERIFY_TMO + 59) / 60 * 60 ))   # 向上取整到 1 分钟粒度
GLOBAL_BUDGET_MS=$(( PARITY_TMO * 1000 + 600000 ))   # = 最长杆 +600s（DEB-5 同款余量）
[ "$GLOBAL_BUDGET_MS" -lt 3000000 ] && GLOBAL_BUDGET_MS=3000000
echo "registry 自适应（DEB-5a/5b）：verified=$REG_VERIFIED（校准基线 17986/25125）→ parity 帽 ${PARITY_TMO}s / router 帽 ${ROUTER_TMO}s / kb-verify 帽 ${KBVERIFY_TMO:-1600}s（DEB-5b）/ 全局预算 ${GLOBAL_BUDGET_MS}ms"

if [ "$RUN_L1" = "1" ]; then gate_L1; fi
if [ "$RUN_L5" = "1" ]; then gate_L5; fi
if [ "$RUN_L6" = "1" ]; then gate_L6; fi

# L2/L3/L4：先注册（含缺件 SKIP 预检），再进同一并行池，最后按门分段输出
NEED_POOL=0
if [ "$RUN_L2" = "1" ] || [ "$RUN_L3" = "1" ] || [ "$RUN_L4" = "1" ]; then
  if [ $(( $(now_ms) - START_MS )) -ge "$GLOBAL_BUDGET_MS" ]; then
    [ "$RUN_L2" = "1" ] && { record_item L2 "tools/test-*.py" SKIP 0 "全局时限已到（$(elapsed_s)），未执行"; }
    [ "$RUN_L3" = "1" ] && { record_item L3 "selftest 组" SKIP 0 "全局时限已到（$(elapsed_s)），未执行"; }
    [ "$RUN_L4" = "1" ] && { record_item L4 "集成组" SKIP 0 "全局时限已到（$(elapsed_s)），未执行"; }
  else
    [ "$RUN_L2" = "1" ] && register_L2
    [ "$RUN_L3" = "1" ] && register_L3
    # 【2026-11-05 收卷批退役】register_L3_e92 调用随白名单门一并摘除（函数本体已删，见上行留痕）。
    [ "$RUN_L4" = "1" ] && register_L4
    NEED_POOL=1
  fi
fi
[ "$NEED_POOL" = "1" ] && run_pool "$PAR"

if [ "$RUN_L2" = "1" ]; then
  print_gate_head "L2" "单测门（tools/test-*.py 逐个，非零即红并点名 + test-manifest.list 清单对账 + 在列数自声明/留痕对账 + 在列门件内容钉对账 + PASS 数下限）"
  [ -n "${L2_UNLISTED:-}" ] && echo "  [提示] 新增门件未列入 tools/test-manifest.list（本轮照常实跑；未列名件被删不触发对账红，也不计入 PASS 数下限，请补录清单并在变更日志留痕）：$L2_UNLISTED"
  print_gate L2
fi
if [ "$RUN_L3" = "1" ]; then print_gate_head "L3" "selftest 门（b-canon / b-pick-claims / b-verdict-unique / task-planner / card-lint --all / publish-scrub-gate / anchor-check / sil-verdict-probe）"; print_gate L3; fi
if [ "$RUN_L4" = "1" ]; then
  print_gate_head "L4" "集成门（kb/verify.py --quick + task-planner 裸跑 exit 0）"
  print_gate L4
  [ "$FAST" = "1" ] && echo "  [说明] --fast 只到 L3；改 tools 后请跑全量（L4 才是集成面）。"
elif [ "$FAST" = "1" ]; then
  print_gate_head "L4" "集成门（--fast 跳过）"
  record_item L4 "kb/verify.py --quick" SKIP 0 "--fast 跳过 L4"
  record_item L4 "task-planner 裸跑" SKIP 0 "--fast 跳过 L4"
  print_gate L4
  echo "  [说明] --fast 只到 L3；改 tools 后请跑全量（L4 才是集成面）。"
fi

summary
exit $?
