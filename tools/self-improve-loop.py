#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self-improve-loop.py — 自改进循环产线守护（本机常驻，默认 600s 周期；无 LLM、确定性编排）

定位（工单：循环产线批-20261029）
    把一次性批处理改造成周期性增量守护。守护只做编排，不做新逻辑：每个环节复用
    已验证的确定性工具，本文件不复制、不改写任何判定/聚类/裁决逻辑。

四段增量流水（每轮）：
  ① 感知：只读 kb-seed/registry.db（SQLite mode=ro）取 verified 计数与水位线
     （max(created_at)）。与 loop-state.json 的上次基线比：增量 ≥ 阈值（默认 50）
     → 触发②；否则本轮结束（仍做⑤记账）。首轮无基线=只建基线不触发（防一上线
     就触发全量差）。基线仅在②成功后前进（增量可跨轮累积；②失败不前进，
     下轮重试同一增量——状态文件防重放）。
  ② 共识增量：跑 B线核心批已验证的 b-canon.py（--out-md/--out-jsonl 指临时出目录，
     确定性管道，正本策略册只读不碰）→ 与上一版策略册 diff（新增/变更/消失簇，
     逐行 sha256 比对）→ 落 loop-state；新/变簇含 tier A/B 且 strategies/ 无对应
     条目 → 生成投影待办（格式规范=af 仓 strategies/README.md 的 G4 契约，只登记
     不臆造：claimed_value/dsl_state 判定需语义级判断，v1 守护不硬凑）。
  ③ 实验排队：对 tier A/B 且 experiment.status=none 的新簇，按 task-planner 的
     优先级规则（策略语料优先→共识强度优先→策略册全局 rank 升序）产出实验候选
     清单，只登记排队（实验设计需材料钉死纪律；执行走工厂订单 af-order EXP-1
     命令模式，绝不 inline 跑模型——登记为待主代理/后续自动化裁决项，v1 边界）。
     另：检查 anolis exp 只读镜像终态单签名（completed 订单集 sha256，逐源：
     默认 ~/exp1-raw/mirror/orders 的 E1-* + ~/exp2-raw/mirror/orders 的
     E2-*——EXP-2 聚合器 G7 件口径：exp2-state orders 镜像、glob E2-*，repeat
     形 E2-<arm>-r<N>-<paper> 同被覆盖）。有新终态单 → 跑对应源聚合器
     （exp1→b-exp1-aggregate.py；exp2→b-exp2-aggregate.py，均临时出目录）
     + b-verdict-unique.py（判定程序唯一性门）→ 终裁按 主断言卡→簇→条目
    确定性映射写 loop-state 裁决队列。**v1.3.5（RT-E12 真实性锚，红队
    SIL 环）**：镜像源须过只读门——机制性只读才算可信输入，非只读即拒用该源
    （不跑聚合器/签名不前进/裁决不产生，fail-closed；台账拦截①）；签名=HMAC-SHA256（密钥
     ~/.config/sil-rt/mirror-signing.key 0600 独立持有，无密钥不可离线
     逐字重算；旧无密钥 sha256 基线一次性迁移——仅镜像与旧签名零漂移才
     采纳，漂移维持 changed 走聚合路径并告警；台账拦截②）。裁决证据新增
     聚合器脚本/输出件 sha256 绑定（拦截③ daemon 侧）。**v1.3.7（RT-E12③
     checker 侧落地）**：④回写面对队列终裁 confirmed/refuted 项前置证据门——
     evidence 三锚在位+aggregator_sha 对账在位聚合器脚本才入回写计划，缺锚/
     异版拒落盘留队（v1.3.5 自注「checker 侧校验另行」的另侧；修复 2026-11-02
    沙盒实证「零证据伪 confirmed 条目 checker 全绿直通 commit de65bcf」旁路面）。
    **v1.3.8（RT-E85④ 只读门收紧，红队 SIL 环）**：只读门判据收紧为「**findmnt
    OPTIONS 必须含 ro 才 trusted**」——rw+收权分支（目录/文件对 uid 全不可写）
    **降级为不可信**：权限位是同 uid 可逆面，伪造镜像可「先改后收权」（写入伪造
    内容后再 chmod 收权），门把**已被伪造**的镜像重新判可信并放行进聚合（2026-11-02
    沙盒实证：findmnt=rw + 树内全不可写 → trusted=True，被信任的是伪造内容；
    chmod 644 后原地改写成功＝uid 可写是所有者随时可逆的面）。findmnt 无读数
    （不可用/超时）亦 fail-closed：不可证即不可信。恢复路径唯一＝把镜像目录以 ro
    方式挂载（chmod 收权**不得**替代挂载 ro）。
    **v1.3.9（RT-E12③ 终裁证据门加固 / 台账 RT-E86 拦截②③）**：v1.3.7 的证据门
    只查三锚**格式**+aggregator_sha 对账**公开可读**的在位聚合器脚本——三锚攻击者
    全部可自算（捏造 64 位 hex + 公开聚合器 sha 即过门；2026-11-02 沙盒实证伪三锚
    confirmed 经真 checker 全绿入库 sandbox commit e21f115，条目 st-C996）。故
    ④回写面加三道**攻击者不可自算**的锚：①**守护封条** evidence.verdict_seal=
    HMAC-SHA256(密钥, 条目关键字段规范化串)，③段签发/④段验签（注入或篡改条目
    ——哪怕三锚逐字全对——一律验签失败拒落盘）；②**状态面封条** state_seal=
    HMAC-SHA256(密钥, 回写面三段 verdict_queue/auto_create_retry/projection_todos
    规范化串)，save_state 签发/load_state 验签，验签失败或缺席 → 三段隔离
    （fail-closed，不入④回写面；计数+摘要+留样入 quarantine_log，台账拦截②
    「verdict_queue 段 HMAC 钉」）；③**来源镜像只读门复判**（④消费点，来源源当前
    须可信；不依赖密钥——产腿停摆期任何 confirmed/refuted 都不得落库）。另：投影
    待办草稿携终裁态（confirmed/refuted）一律拒写（终裁只能经③段证据门落库）。
    残余边界（如实）：同 uid 进程仍可读密钥（台账 RT-E85 拦截②「密钥出域」未施工
    ——需 root/独立 uid/非对称改造）——封条消的是「无密钥人人可算」，不宣称对抗
    持密钥同 uid；但④门第三道腿（镜像只读门）不依赖密钥，产腿停摆期伪终裁仍无
    路可入。回归见 selftest T18g/T19a-f。
    **v1.3.10（逃逸符号链接面，镜像真实性门）**：只读门加**结构性腿**——镜像树内
    存在**逃逸符号链接**（链接目标解析后落在镜像树外）即 fail-closed 拒用，**即便
    findmnt=ro**：ro 挂载只保护本挂载点内的 inode，链接目标在树外完全不受保护（可被
    随时原地改写、或把整个目标目录整体换掉），而守护的订单枚举（_completed_orders_in）
    与两个聚合器（b-exp1/b-exp2-aggregate.py）都**穿过该链接**读它——旧门对符号链接
    目录零设防：E1-* 订单目录整体换成符号链接即判可信，同时守护自己穿链读到攻击者
    的伪造终态单（直通聚合器→终裁→回写）。三处同时收口：①门（_mirror_ro_verdict
    →_mirror_escape_links）拒用；②守护枚举（_completed_orders_in）不读符号链接订单
    目录；③两个聚合器对符号链接订单目录 fail-loud（进 problems 通道→整批拒绝聚
    合）。树内链接（目标仍在树内、内容仍受 ro 保护）不构成逃逸，不误拒。回归见
    selftest T18d3。
    **v1.3.11（2026-11-03 SIL 环修复批·在役源码版本钉）**：守护把**载入时**自身
    源码的 sha256 指纹登记进状态面 st["daemon_src"]（起跑即落盘，每次写盘随封条
    同行）。修的是「盘上修复不在役」这一类缺陷的**根**：此前守护无版本钉，监督面
    （keepalive）判活只看「进程在+state 新鲜」，盘上源码改了不重启＝修复不生效
    （2026-11-03 实证：在役 06:53 起跑、盘上 17:53 已改、17h 未重载＝轮4 SIL 修整体
    未在役；在役旧判据更宽松＝同一镜像面两套结论、两套真相并行且无人对账）。本版
    只**登记事实**（不新增判定、不改既有判据），由监督面（tools/factory-keepalive.py
    源码版本钉判活：版本不对齐⇒判死⇒自动拉起新码）与巡检面（tools/sil-verdict-probe.py
    版本钉对账：在役版本≠盘上判据版本⇒rc=2 不可证即红）消费。
    **v1.3.12（2026-11-03 SIL 环修复批·verdict_log 段未封条＝状态面封条被绕过）**：
    封条覆盖面补第四段 **verdict_log**（此前只钉 verdict_queue/auto_create_retry/
    projection_todos 三段）。修的是确证发现「轮4 注入拦截被 verdict_log 段绕过」：
    verdict_log 是**通往回写面的第四条来源**（_reenqueue_parked_auto_creates 路径(b)
    「历史丢弃裁决恢复重入队」从日志复制条目进 verdict_queue），而它不在封条覆盖内
    ⇒ 攻击者注入日志条目不破坏封条：load_state 验签通过 → 重入队扫描（**验签之后**
    执行）把伪造条目搬进 verdict_queue → 非终裁态零证据要求（verdict_evidence_gate
    对 inconclusive/pending 直接 return None）→ 伪条目经真 checker（含 R4 编译断言）
    全绿写进 strategies/ 正本并 commit。收口两层：①**状态面封条覆盖 verdict_log**
    （日志被改即验签失败 → 四段隔离 fail-closed，日志不得作重入队来源）；②**重入队
    路径(b) 只复活带守护封条（③段签发、攻击者不可自算）的日志条目**（源不可信即拒，
    留痕不静默丢弃）——纵深防御：即便将来封条覆盖面被放宽，复制点自身仍只信守护自产件。
    残余边界（如实）：同 uid 可读密钥（台账 RT-E85 拦截②「密钥出域」未施工）；封条验
    签只在守护起跑时做一次（起跑后状态面在内存中演进，60s 心跳以内存态覆盖文件——故
    注入须落盘且在守护重启前生效，见台账「在役源码版本钉」批的换码收口）。
    **v1.3.14（2026-11-03 红队 SIL 环·判据读出通道换件面收口）**：RT-E85④ 把信任锚
    迁到 kernel 挂载态（findmnt OPTIONS 含 ro），但**测量工具本身**此前按裸名走本进程
    PATH 解析（subprocess.run(["findmnt",…])）——在役守护 PATH 前置 ~/bin、~/.local/bin、
    ~/.cargo/bin 三个**同 uid 可写**目录（2026-11-03 亲读 /proc/<pid>/environ + 目录
    权限位佐证），任何同 uid 进程在其中落一个恒打印「ro,relatime」的假 findmnt 即按
    POSIX 解析序胜出＝kernel 挂载态读数被整体伪造（沙盒复现：rw 挂载镜像 + PATH 前置
    假件 → trusted=True「挂载 ro」＝与「先改后收权」同构的「先放假件后放伪造镜像」）。
    收口：findmnt 一律经 _system_tool 按 **confstr _CS_PATH**（libc 编译期系统默认
    工具目录 /bin:/usr/bin，不含任何用户 PATH 目录）解析为**绝对路径**再调；子进程
    env 只给 {PATH, LC_ALL}（不继承父进程全环境，堵 LD_PRELOAD/LD_LIBRARY_PATH 注入）；
    解析不到系统 findmnt → 无读数 → 维持 RT-E85④ fail-closed。巡检腿（sil-verdict-probe
    ④机械实测）同批加**独立复算对账**（探针进程自行按 _CS_PATH 解析，与判据模块实际
    解析对账，不一致即红）——防「两腿共用同一被换件读出」的同源失明。残余边界（如实）：
    _CS_PATH 目录本身（/bin、/usr/bin）被写则面仍在，但那已需 root，超出「同 uid 换件」
    威胁模型；keepalive 拉起不洗 PATH 环境一事经此修不再构成该面（判据不再消费 PATH）。
    **v1.1：裁决目标簇无库条目时不再
     跳过**——自动建条目（tier 照实标、experiment 填终裁、claim 取册内断言、
     dsl_state=needs_syntax+note '待投影'）进④同机制，checker 全绿才 commit；
     红/失败 → 回滚+登记（v1.3.3：失败项寄存 auto_create_retry，回写面环境键
     变化后自动重入队——原 attempt-once「同输入重试必得同结果」前提被
     2026-10-31 同窗事实推翻：st-C103 同输入 09:15/09:25 两红（旧 checker/
     守护 index 计数缺陷），09:30 修复后同输入绿 commit a0418ef，红绿由
     回写面环境版本决定、不由条目输入决定；st-C122/EXP-1 真实终裁曾被旧
     语义永久丢弃，B5 修复+一次性恢复）。
  ④ 回写：裁决队列非空 → 在 af 仓 git 分支 sil-writeback（工作树
     ~/workspace/af-wt-sil-writeback，base=phase2 tip=strategies/ 正本所在）
    改 strategies/ 对应条目 experiment 字段（幂等：目标值已在场即跳过）；
     **v1.1：条目文件缺席（含 tier C/D 档簇）时自动建条目**（九钉死字段按
     G4 契约渲染：tier 照实、claim 取册内断言、experiment 填终裁、
     claimed_value 三维标'待投影'占位、dsl_state=needs_syntax+note '待投影'，
     index 并集登记一条；投影补齐另行排队待办）→ 跑
     ci/strategies_check.py 全量校验门（R1 schema/R2 index/R3 计数/R4 编译断言）
     → 全绿才 git add+commit（不 push）；红/失败 → 回滚（tracked 文件 git
     checkout、新建件显式 unlink）+ 登记失败。既有 experiment 字段更新与
     ②投影待办（带齐 entry_draft）路径机制不变（v1.3.4：失败项与自动初建
     同语义寄存 auto_create_retry，回写面环境键变化后按原队列重入队——
     曾留队下轮无条件重试，持续红环境每 600s 一次编辑→checker→回滚抖环，
     2026-11-01 st-C103/EXP-2 rollbacks 25→42 实证）。
  ⑤ 每轮：loop-state.json 原子写（tmp+os.replace：轮次/各段动作/增量数字/
     commit 列表/裁决与待办队列）+ 变更日志一行（只记真实动作/告警，与
     factory-scheduler/event-router 同格式同门）；指标面动作计数原子写
     状态观测/self-improve.json（pusher 已带状态观测件则自动上板——现役
     factory-status-push.py 只暂存 quota/stages/otel-sidecar 三件，本件未挂，
     上板需 pusher+脱敏闸各加一行，超出本工单指定文件面，v1 边界）。

守护纪律（仿 event-router/factory-scheduler，同构）：
  · STOP 熔断文件 tools/.self-improve-STOP（在位即全局熔断，轮内/轮间同判；
    熔断轮仍写 loop-state（keepalive 判据要新鲜度）但不做任何动作）；
  · 状态文件防重放：基线/镜像签名/幂等回写三重去重，崩在半轮可重入；
  · 全寿命心跳线程每 60s 原子重写 loop-state（轮周期 600s > keepalive 300s
    新鲜度判据，无心跳则轮间隔内必被误判失联反复拉起——2026-10-29 实测教训，
    心跳只带时间戳、不前进任何基线/签名）；
  · 每步失败只记日志不崩主循环（逐个 try/except，DEB-1 口径：所有子进程带
    timeout，无超时=可楔死）；
  · 全动作 changelog 留痕；DRY 模式（SELF_IMPROVE_DRY=1 或 --dry-run）只记
    不写：不写 git/不变更日志/不落 loop-state/不建工作树，本地纯读工具照跑
    （b-canon 只读输入、临时出目录落 $HOME）；④回写面在 DRY 下只报回写计划
    不执行（writeback_round 入口守卫+ensure_writeback_tree 熔断，双保险——
    复核判据5 修复）；
  · 单实例守卫（tools/.self-improve-loop.pid，活进程即拒双开；陈旧 pidfile
    自动接管）；keepalive 判据=进程在+loop-state.json<300s（与 watch 同构）。
  密钥零明文：本脚本不读不写任何令牌。kb/ 与策略册正本、af 仓非授权文件只读；
  临时件一律 $HOME（~/sil-tmp；构建 target 复用 ~/afbuild-stratlib，缺则
  ~/afbuild-sil）。实验执行绝不 inline——只排队/只聚合既有终态单。

用法：
  python3 tools/self-improve-loop.py                # 常驻（默认 600s 一轮）
  python3 tools/self-improve-loop.py --once         # 单轮即退（自测）
  python3 tools/self-improve-loop.py --dry-run      # 只记不写（同 SELF_IMPROVE_DRY=1）
  python3 tools/self-improve-loop.py --force-trigger # 越过增量闸强制跑②（自测②③④）
  python3 tools/self-improve-loop.py --status       # 打印 loop-state.json 即退
  python3 tools/self-improve-loop.py --selftest     # 不变量自检（合成夹具+真实只读对账）

环境变量（缺省=生产值）：
  SIL_INTERVAL=600            轮询周期（s）
  SIL_THRESHOLD=50            ① verified 增量触发阈值
  SIL_STATE / SIL_METRICS / SIL_LOG / SIL_CHANGELOG / SIL_STOP / SIL_PIDFILE / SIL_TMP
                             （SIL_PIDFILE=单实例锁路径，沙箱复跑时改指即可与在役实例隔离）
  SIL_REGISTRY_DB              kb-seed/registry.db（mode=ro）
  SIL_B_CANON / SIL_CARDS / SIL_CANON_BOOK        b-canon.py / cards-v1.jsonl / 策略册正本
  SIL_B_EXP1 / SIL_B_VERDICT / SIL_EXP1_DIR       聚合器 / 判定门 / EXP 规格目录
  SIL_B_EXP2 / SIL_EXP2_DIR                       EXP-2 聚合器 / exp2 规格目录（实验批）
  SIL_EXP_MIRROR / SIL_EXP_MIRROR2                anolis exp 只读镜像（exp1: ~/exp1-raw/mirror/orders，
                                                   glob E1-*；exp2: ~/exp2-raw/mirror/orders，glob E2-*）
  SIL_AF / SIL_WB_BRANCH / SIL_WB_BASE / SIL_WB_WT   af 仓 / 回写分支 / 基线 / 工作树
  SIL_WB_CARGO_TARGET          checker R4 的 CARGO_TARGET_DIR（复用热缓存）
  SIL_STRATEGIES_DIR           strategies/ 读数覆盖（缺省按工作树链解析）
  SIL_DRY=1                    DRY（同 --dry-run）
回滚：停进程 + 删 tools/.self-improve-STOP + 删 tools/.self-improve-loop.pid；
      git 侧无远程推送（只本地分支 sil-writeback），`git -C af branch -D
      sil-writeback` + `git -C af worktree remove ~/workspace/af-wt-sil-writeback`
      只回退④回写面（strategies/ 裁决回写线）；loop-state/日志可留作审计。
      **2026-11-02 RT-E49/E97 语义修正（原「即彻底回退」是假的且危险）**：本指令
      早已不回退 CI 门族——门族修复（摘门保牌/整槽连摘/判据钉/名册绑定各批）已
      落主干基线 phase2（c483dd2 起，与 sil-writeback 门族逐文件同值；af 仓门族
      耐久性由 ci/fix_verify.py 收口门机守：跨树篡改回放+基线在场+门码单源，
      `python3 -I ci/fix_verify.py` 在 af 仓任一在役树可跑）；删分支后守护按
      wb_base=phase2 重建工作树必带门族（修复不随回退灭失）。若真要连同门族一起
      回退，须显式对 phase2 分支操作并在 ci/fix_verify.py 跑红确认后再动手——
      不得借「回退 SIL」之名静默摘门（RT-E48/E49「修复未落库=未落地」教训）。

v1.1 边界（相对 v1 的变更，详见报告 v1.1-报告.md）：
  B1 投影待办不自动成条：G4 条目九字段中 claimed_value{metric,direction,context}
     策略册无对应字段、dsl_state 三态判定需 AFB 语义级撰写——守护不臆造，待办
     带全部册内材料排队，待主代理/后续自动化补 entry_draft 后由④同机制落条。
     **v1.1 起：终裁目标簇无库条目时守护自动建"初建条目"**（claimed_value 三维
     显式标'待投影'占位、dsl_state=needs_syntax），checker 全绿才 commit；commit
     后另行排队投影待办补齐 claimed_value/dsl_snippet（仍走既有待办路径）。
  B2 终裁→条目映射规则=主断言卡→簇→条目（experiments-v1.json primary_claim
     .card_id 确定性推导）。st-C007 的「EXP-1 实例化」是 libA 人工判读先例，
     守护不复制该判读（不臆造实例化关系）。**v1.1 起：目标簇无库条目（含
     tier C/D）不再跳过不回写，而是自动建条目进④**——tier C/D 初建条目必被
     R1 闭集（tier∈{A,B}，G4 工单钉死）红斩并回滚，如实登记为卡点（自动建条
     目只尝试一次）；tier A/B 且册内无对应条目的新簇则可全绿 commit。
  B3 指标面文件已写（状态观测/self-improve.json），pusher 自动上板未挂（需改
     factory-status-push.py + publish-scrub-gate.py，超出工单指定文件面）。
  B4 聚合触发逐源看「新终态单」（镜像 completed 集合签名变化，exp1/exp2 分源
     记账）；已跑过的实验不重跑（签名不变即跳过）。终裁词 pending（数据未到齐）
     亦排队回写：G4 experiment.status 闭集含 pending，按实情填；main_diff 等
     判读键缺失时 note 只记实际产出的键（不臆造数值）。
  B5(v1.3.3) 自动初建失败不再永久丢弃（G-SIL「裁决无论何种均如实回写」缺口
     修复）：原 attempt-once 出队后再无再入队路径——EXP-1/st-C122 真实终裁
     （2026-10-31 09:14:59）被永久丢弃实证。现失败项寄存 auto_create_retry，
     回写面环境键（worktree 内 ci/strategies_check.py 内容 sha + 本守护源码
     sha + worktree HEAD）变化后自动重入队（环境不变则保持寄存，防确定性
     违约抖环）；
     verdict_log 里旧语义丢弃（outcome 以「自动建条目尝试 1 次即止」开头）
     且条目文件仍缺席的裁决一次性恢复重入队（st-C122 实证回收）。
  B6(v1.3.4) 更新/投影路径失败项同寄存语义（attempt-once 语义洞修复）：
     v1.3.3 只把自动初建失败项挂环境键门控，更新/投影失败项仍留队每轮
     无条件重试——「键不变不重试」（_wb_env_key 原则）被更新路径违反。
     2026-11-01 实证：持续红环境（共享 target 溯源脏，与条目输入无关）
     下 st-C103/EXP-2 每 600s 一次编辑→checker→回滚，rollbacks 25→42
     无界增长、共享 cargo target 每轮被 provenance ensure 判脏即清。现
     checker 红/git 失败时全部失败项出队寄存（kind 记原属队列），键变化
     后按原队列重入队；键不变保持寄存（防抖环，不永久丢弃）。
"""

import argparse
import ast
import copy
import glob
import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import threading
import time

try:
    import yaml  # type: ignore
except ImportError:  # 与 ci/strategies_check.py 同口径：缺 PyYAML 即 FATAL
    print("self-improve-loop: FATAL 需要 PyYAML（python3 -c 'import yaml'）", file=sys.stderr)
    sys.exit(2)

WS = "/home/pan-ding/workspace/agent黑灯工厂"
HOME = os.path.expanduser("~")


def _env(k, d):
    v = os.environ.get(k)
    return v.strip() if v and v.strip() else d


def _env_int(k, d):
    try:
        return int((os.environ.get(k) or "").strip() or d)
    except ValueError:
        return d


# ---------- 可调参数（环境变量覆盖，缺省=生产值；dict 形态供 selftest 改写） ----------
CFG = {
    "interval": _env_int("SIL_INTERVAL", 600),
    "threshold": _env_int("SIL_THRESHOLD", 50),
    "state": _env("SIL_STATE", WS + "/状态观测/loop-state.json"),
    "metrics": _env("SIL_METRICS", WS + "/状态观测/self-improve.json"),
    "log": _env("SIL_LOG", WS + "/状态观测/self-improve-loop.log"),
    "changelog": _env("SIL_CHANGELOG", WS + "/计划/变更日志.md"),
    "stop": _env("SIL_STOP", WS + "/tools/.self-improve-STOP"),
    "pidfile": _env("SIL_PIDFILE", WS + "/tools/.self-improve-loop.pid"),
    "tmp": _env("SIL_TMP", HOME + "/sil-tmp"),
    "registry_db": _env("SIL_REGISTRY_DB", WS + "/kb-seed/registry.db"),
    "b_canon": _env("SIL_B_CANON", WS + "/计划/研究组/B线核心批-20261029/tools/b-canon.py"),
    "cards": _env("SIL_CARDS", WS + "/kb-seed/candidates-batch1/b线-20261028/cards-v1.jsonl"),
    "canon_book": _env("SIL_CANON_BOOK", WS + "/计划/研究组/B线核心批-20261029/策略册-v0.1.jsonl"),
    "b_exp1": _env("SIL_B_EXP1", WS + "/tools/b-exp1-aggregate.py"),
    "b_verdict": _env("SIL_B_VERDICT", WS + "/tools/b-verdict-unique.py"),
    "exp1_dir": _env("SIL_EXP1_DIR", WS + "/计划/研究组/B线核心批-20261029"),
    "exp_mirror": _env("SIL_EXP_MIRROR", HOME + "/exp1-raw/mirror/orders"),
    "b_exp2": _env("SIL_B_EXP2", WS + "/tools/b-exp2-aggregate.py"),
    "exp2_dir": _env("SIL_EXP2_DIR", WS + "/计划/研究组/实验批-20261029"),
    "exp_mirror2": _env("SIL_EXP_MIRROR2", HOME + "/exp2-raw/mirror/orders"),
    "af": _env("SIL_AF", WS + "/af"),
    "wb_branch": _env("SIL_WB_BRANCH", "sil-writeback"),
    "wb_base": _env("SIL_WB_BASE", "phase2"),
    "wb_wt": _env("SIL_WB_WT", HOME + "/workspace/af-wt-sil-writeback"),
    "wb_cargo_target": _env("SIL_WB_CARGO_TARGET",
                            HOME + "/afbuild-stratlib" if os.path.isdir(HOME + "/afbuild-stratlib")
                            else HOME + "/afbuild-sil"),
    "strategies_dir": _env("SIL_STRATEGIES_DIR", ""),
    "dry": _env("SIL_DRY", "") == "1" or "--dry-run" in sys.argv,
}
# 子进程超时（DEB-1 口径：无超时=可楔死；checker 略大于其内部 cargo 900s 预算，
# 让门自行产出红判决而非被外层 timeout 抢先）
TMO = {"b_canon": 300, "exp1": 900, "exp2": 900, "verdict": 300, "git": 120, "checker": 960}

# 终裁词表 → strategies_check R1 五态映射（保守：非 confirmed/refuted 一律
# inconclusive，精确判词原样进 note——不把 equivalent/dose_unstable 等
# 混同为库语义闭集里的值）。例外：pending 是 G4 闭集原生的"数据未到齐、
# 不出终裁"态（b-exp2-aggregate 纪律），与 inconclusive（已终裁无清晰效应）
# 语义互斥，不得混同——v1.1 起显式映射）。
VERDICT_STATUS_MAP = {"confirmed": "confirmed", "refuted": "refuted",
                      "pending": "pending"}
VERDICT_FALLBACK = "inconclusive"
TERMINAL_ORDER_STATUS = "completed"   # 实测词表（records.jsonl 末行 status）

# 实验只读镜像源（v1.1 补丁①：watch 面扩容——exp1 E1-* + exp2 E2-* 逐源签名；
# exp2 口径对齐 EXP-2 聚合器 G7 件：exp2-state orders 镜像、glob E2-*，repeat
# 形 E2-<arm>-r<N>-<paper> 同被 glob 覆盖）。每源带自己的聚合器/规格目录/
# 汇总件名——守护只编排，判定逻辑仍在各聚合器内。函数形态（非模块级快照）：
# CFG 可在 selftest/探针中改写，源清单随之重建。
def exp_sources():
    return [
        {"name": "exp1", "dir": CFG["exp_mirror"], "glob": "E1-*",
         "aggregator": CFG["b_exp1"], "dir_flag": "--exp1-dir", "spec_dir": CFG["exp1_dir"],
         "summary": "exp1-aggregate-summary.json"},
        {"name": "exp2", "dir": CFG["exp_mirror2"], "glob": "E2-*",
         "aggregator": CFG["b_exp2"], "dir_flag": "--exp2-dir", "spec_dir": CFG["exp2_dir"],
         "summary": "exp2-aggregate-summary.json"},
    ]

DRY = CFG["dry"]

# 镜像真实性门「持续拒用」再告警节奏（s，本批 2026-11-02）：门位翻转只在翻转瞬间
# 写一行变更日志，双源持续拒用（裁决产出停摆）期间审计面静默——2026-11-02 实证
# 00:13 翻转一行后 3.5h+ 零告警。拒用未解时每 2h 重报一行（审计面持续红，不 600s 刷屏）。
MIRROR_GATE_REALARM_S = 7200


# ---------------------------------------------------------------- 基础件
def _stdout_is_logfile():
    """stdout 是否已重定向进本日志文件（nohup … >> LOG 姿势）——红队 W2-C19：
    print+append 双通道会让同一行写两次，故同文件时只走 stdout 单通道。"""
    try:
        return os.path.realpath("/proc/self/fd/1") == os.path.realpath(CFG["log"])
    except OSError:
        return False


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if not DRY and not _stdout_is_logfile():
        try:
            os.makedirs(os.path.dirname(CFG["log"]), exist_ok=True)
            with open(CFG["log"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print("日志落盘失败: %s" % e, file=sys.stderr)


def changelog(text):
    """真实动作/告警才写变更日志（与 factory-scheduler.py:314/event-router.py:133 同门）。"""
    line = "| %s | 循环产线(自动) | %s |\n" % (time.strftime("%Y-%m-%d %H:%M"), text)
    if DRY:
        log("变更日志(DRY 跳过落盘): " + text)
        return
    try:
        os.makedirs(os.path.dirname(CFG["changelog"]), exist_ok=True)
        with open(CFG["changelog"], "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        log("变更日志写入失败: %s" % e)
    log("变更日志: " + text)


def sh(cmd, timeout, cwd=None, env_extra=None):
    """子进程原语：一律带 timeout（DEB-1）；返回 CompletedProcess 或 None（异常只由调用方降级）。"""
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)


def atomic_write_json(path, obj, mode=None):
    """原子写：tmp + os.replace（同 factory-scheduler.py:738 save_state 口径）。

    v1.3.13（2026-11-03 状态面面收口批）：mode=落盘件的**目标权限位**。给定则 tmp
    **创建即用该权限**（os.open 的 mode 只减不增——umask 只会把 0600 减成更严，
    不会放宽，故再 os.fchmod 兜底防「tmp 残留既有宽权限」），落盘件 os.replace 后
    即为该权限。

    修的是什么（2026-11-03 确证发现）：状态面落盘件此前**继承 umask 默认位**
    （本机 umask 0002 ⇒ **664：同组可写**）——即「谁都能改写状态面」的面一直开着：
    封条（v1.3.9）只保证**内容**不被注入（验签失败即 fail-closed 隔离），**不保证
    「没人能写」**；664 面下同组进程改写状态面后，守护下一轮会把篡改后的内容重新
    签发封条（洗白）。权限面与内容面是两件事，两面都要闭。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 mode if mode is not None else 0o666)
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 在役源码版本钉
# **v1.3.11（2026-11-03 SIL 环修复批）**：守护把**自己载入时**的源码指纹登记进状态面
# （st["daemon_src"]），使「在役进程跑的是哪一份判据」从推断变为**可核验事实**。
# 修的是什么（2026-11-03 确证发现）：此前**无任何版本钉**——盘上源码改了不重启＝
# 修复不生效（实证：在役守护 06:53:37 起跑、盘上源码 17:53:28 已改，17h 未重载＝
# 轮4 SIL 修整体未在役）；且在役判据**更宽松**（旧码 rw+收权⇒可信，RT-E85④ 已收紧
# 仍只在盘上）⇒ 同一镜像面两套结论、两套真相并行，无人对账。
# 语义：sha256 = **载入时**盘上源码的内容指纹（不是「此刻盘上」的——盘上改了而在役
# 进程仍跑旧码，进程内指纹不变；这正是版本钉要暴露的事实）。监督面（keepalive 源码
# 版本钉判活）与巡检面（sil-verdict-probe 版本钉对账）据此判「在役判据＝盘上判据」。
# ver 字段=本文件当前版本号（版本钉机制本身落在 v1.3.11；本文件另有并发批次的
# v1.3.12 同批在役——**版本号只是注记，sha256 才是版本钉的权威身份**：同一份源码
# 改一行即换指纹，版本号不随之变，故对账一律以 sha256 为准）。
#
# **v1.3.13（2026-11-03 状态面面收口批）**：状态面**权限面**收口——落盘件 0600
# （此前继承 umask ⇒ 664 同组可写：封条只管内容不管「谁能写」）+ 读盘时权限自愈
# （被改宽即收回并留痕）。内容面（封条验签 fail-closed 隔离）机制不动。
# **v1.3.14（2026-11-03 红队 SIL 环·判据读出通道换件面收口）**：只读门 findmnt 读出
# 从裸名/进程 PATH 解析收紧为 confstr _CS_PATH 绝对路径解析（_system_tool）+ 子进程
# env 清洗——RT-E85④ 的 kernel 挂载态信任锚此前可被同 uid 在 PATH 前置可写目录
# 落假 findmnt 整体伪造（见模块头 v1.3.14 段）。巡检腿独立复算对账在
# sil-verdict-probe.py v1.5 同批施工。
DAEMON_VER = "v1.3.15"           # RT-E85② 密钥出域（H8.4：shadow 身份由文件名 .rt85wip 承载，部署换正本后版本即正式）
try:
    DAEMON_SRC_SHA256 = sha256_text(
        open(os.path.abspath(__file__), encoding="utf-8").read())
except OSError:
    DAEMON_SRC_SHA256 = "unreadable"


def daemon_src_stamp():
    """在役源码版本钉：守护载入时自身源码的指纹（版本号+sha256+pid+载入时刻）。"""
    return {"ver": DAEMON_VER, "sha256": DAEMON_SRC_SHA256, "pid": os.getpid(),
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


# ---------------------------------------------------------------- 单实例守卫
def acquire_pidfile():
    """活进程即拒双开（argv 含本脚本）；陈旧 pidfile 自动接管。"""
    pf = CFG["pidfile"]
    try:
        old = open(pf, encoding="utf-8").read().strip()
    except OSError:
        old = ""
    if old and old.isdigit() and os.path.exists("/proc/%s" % old):
        try:
            argv = open("/proc/%s/cmdline" % old, "rb").read().decode().split("\0")
            if any("self-improve-loop.py" in a for a in argv):
                print("self-improve-loop 已在跑 pid=%s，拒绝双实例" % old, file=sys.stderr)
                sys.exit(3)
        except OSError:
            pass
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    with open(pf, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release_pidfile():
    try:
        if open(CFG["pidfile"], encoding="utf-8").read().strip() == str(os.getpid()):
            os.unlink(CFG["pidfile"])
    except OSError:
        pass


# ---------------------------------------------------------------- 心跳（保 keepalive 新鲜度）
# keepalive 判据=进程在+loop-state.json<300s，而轮周期默认 600s——轮间隔内 state 必然
# 过期 → 会被误判失联反复拉起。故心跳为**全寿命周期**（不止长轮次）：每 60s 原子重写
# 同一份 state（只带 heartbeat_ts，不前进任何基线/签名——防重放语义不变）。
_HB = {"lock": threading.Lock(), "stop": False, "state": None}


def _heartbeat_loop():
    while not _HB["stop"]:
        time.sleep(60)
        with _HB["lock"]:
            st = _HB["state"]
        if st is None or DRY:
            continue
        try:
            st = copy.deepcopy(st)
            st["heartbeat_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
            seal_state(st)                              # v1.3.9：心跳写盘同样签发封条
            atomic_write_json(CFG["state"], st, mode=0o600)   # v1.3.13：状态面 0600
        except Exception:
            pass


def heartbeat_start(st):
    _HB["state"] = st
    _HB["stop"] = False
    threading.Thread(target=_heartbeat_loop, daemon=True).start()


def heartbeat_stop():
    _HB["stop"] = True


# ---------------------------------------------------------------- ① 感知
def perceive():
    """只读 registry.db：verified 计数 + 水位线 + 分状态计数。"""
    db = CFG["registry_db"]
    if not os.path.isfile(db):
        raise FileNotFoundError("registry.db 不在位: %s" % db)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
    try:
        by_status = dict(con.execute(
            "SELECT status, COUNT(*) FROM candidates GROUP BY status").fetchall())
        total = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        watermark = con.execute("SELECT MAX(created_at) FROM candidates").fetchone()[0]
    finally:
        con.close()
    return {"verified": int(by_status.get("verified", 0)),
            "candidate": int(by_status.get("candidate", 0)),
            "rejected": int(by_status.get("rejected", 0)),
            "total": int(total), "watermark": watermark or ""}


# ---------------------------------------------------------------- ② 共识增量
def load_book(path):
    """读策略册 jsonl → {cluster_id: {row, fp}}；fp=该行规范序列化 sha256。"""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out[row["cluster_id"]] = {"row": row, "fp": sha256_text(line)}
    return out


def diff_books(prev, cur):
    new, changed, removed = [], [], []
    for cid, v in cur.items():
        if cid not in prev:
            new.append(cid)
        elif v["fp"] != prev[cid]["fp"]:
            changed.append(cid)
    for cid in prev:
        if cid not in cur:
            removed.append(cid)

    def key(cid):
        r = cur.get(cid) or prev[cid]["row"]
        try:
            rank = int(r.get("rank"))
        except (TypeError, ValueError):
            rank = 10 ** 9
        return (rank, cid)

    return sorted(new, key=key), sorted(changed, key=key), sorted(removed)


def entry_id_for(cluster_id, tier):
    """簇→库条目 id 命名空间（libA=st-C0XX，libB=st-b-C0XX，与文件名 stem 同构）。

    v1.1：tier 非 A/B（C/D 档）时不再落 B 线命名空间——那些簇从无库条目，
    自动建条目用簇自身 id 的平铺命名空间 st-C0XX（符合 checker ID_RE
    ^st-(b-)?C[0-9]+$；st-b- 前缀是 B 线命名空间，会给 C/D 档簇错贴 B 线身份）。
    """
    num = re.sub(r"\D", "", cluster_id)
    return ("st-C%s" % num) if tier in ("A", "C", "D") else ("st-b-C%s" % num)


# entry_id 命名空间门（与 ci/strategies_check.py ID_RE ^st-(b-)?C[0-9]+$ 同构；
# entry_id_for 是唯一合法生产者，见上）。回写面在拼路径/落盘**之前**校验：
# loop-state.json 与实验镜像同信任域（同用户可写，664），伪造 target_entry_id
# 携带 / 或 .. 时 os.path.join 会逃逸回写工作树写任意路径——checker 兜底在
# 写盘之后来不及，故写盘面前置此门（红队 SIL 环修复）。
ENTRY_ID_RE = re.compile(r"^st-(b-)?C[0-9]+$")

# v1.3.7（RT-E12③ checker 侧落地）：终裁证据门。v1.3.5 只施工了 daemon 侧绑定
# （③聚合时把聚合器脚本/输出件 sha256 绑进条目 evidence，自注「checker 侧校验
# 另行」，另侧从未施工）——回写面对 verdict_queue 条目长期只校验 ENTRY_ID_RE
# 命名空间：同 uid 进程向 664 的 loop-state.json 注入零证据伪 confirmed 条目，
# 即可自动建条目、checker 全绿直通 git commit（2026-11-02 沙盒实证
# commit de65bcf，镜像门/HMAC/证据绑定三锚全被旁路）。本门与 ENTRY_ID_RE 同位
# （回写面 plan 拼装处、写盘/checker 之前——checker 兜不了）：终裁
# confirmed/refuted（改变库语义的两态）必须带 v1.3.5 证据三锚且 aggregator_sha
# 对账在位聚合器脚本，缺锚/异版拒入回写计划（项留队带 writeback_error，与
# 命名空间门同拒法：如实留痕、不静默丢弃）。
EVIDENCE_SHA_RE = re.compile(r"[0-9a-f]{64}")

# v1.3.9（RT-E12③ 加固 / 台账 RT-E86 拦截②③）：v1.3.7 的终裁证据门只做两件事——
# 三锚**格式**校验 + aggregator_sha 对账**公开可读**的在位聚合器脚本：三锚攻击者
# 全部可自算（捏造 64 位 hex + 公开聚合器 sha 即过门）。2026-11-02 沙盒实证：伪
# 三锚 confirmed 终裁经真 checker 全绿入库（sandbox commit e21f115，条目 st-C996，
# experiment.status=confirmed）——「证据门可被伪造」面仍开。故在证据门之上补
# **攻击者不可自算**的锚（台账 RT-E86 拦截②「verdict_queue 段 HMAC 钉」）：
#   ① 守护封条 evidence.verdict_seal = HMAC-SHA256(密钥, 条目关键字段规范化串)：
#      ③段签发 / ④段验签——注入或篡改条目（哪怕三锚逐字全对）一律验签失败拒落盘；
#   ② 状态面封条 state_seal = HMAC-SHA256(密钥, 回写面四段规范化串）：save_state
#      签发 / load_state 验签；验签失败 → 回写面四段隔离（fail-closed；不静默丢弃：
#      计数+摘要+留样入 quarantine_log）；**v1.3.12 覆盖面补第四段 verdict_log**
#      （2026-11-03 红队确证：verdict_log 未在封条覆盖内 → 攻击者注入日志条目 →
#      _reenqueue_parked_auto_creates 验签后搬进 verdict_queue → 非终裁态零证据
#      要求 → 伪条目经真 checker 全绿入库 commit）；
#   ③ 镜像只读门复判（④消费点）：终裁来源源的镜像只读门当前须可信（RT-E12①）——
#      该腿不依赖密钥（攻击者自算不了）：产腿停摆期（双源拒用）任何 confirmed/
#      refuted 都不得落库。
# 残余边界（如实）：同 uid 进程仍可读密钥（台账 RT-E85 拦截②「密钥出域」未施工——
# 需 root/独立 uid/非对称改造）——封条消的是「无密钥人人可算」，不宣称对抗持
# 密钥同 uid；镜像腿的残余是「先改后收权」（权限位同 uid 可逆；v1.3.8 已把
# rw+收权降级为不可信），物理防线是挂 ro。
VERDICT_SEAL_FIELDS = ("exp_id", "verdict", "status", "target_entry_id",
                        "target_cluster", "target_tier", "note")
VERDICT_SEAL_EV_FIELDS = ("summary", "mirror_sig", "aggregator_sha", "summary_sha",
                          "n_terminal")
# v1.3.12（2026-11-03 红队 SIL 环·轮4 确证发现修复）：状态面封条覆盖面补第四段
# **verdict_log**。此前封条只钉 verdict_queue/auto_create_retry/projection_todos 三段，
# 而 verdict_log 是**第四条通往回写面的来源**（_reenqueue_parked_auto_creates 路径(b)
# 「历史丢弃裁决恢复重入队」从 verdict_log 复制条目进 verdict_queue）——它不在封条
# 覆盖内 ⇒ 攻击者（同 uid 可写 loop-state.json）注入日志条目**不破坏封条**：
#   load_state 验签通过（state_seal_ok=True）→ 重入队扫描（验签**之后**执行）把伪造
#   条目搬进 verdict_queue → verdict_evidence_gate 对非终裁态零证据要求（inconclusive/
#   pending 直接 return None）→ 伪条目经真 checker 全绿写进 strategies/ 正本并 commit。
# 覆盖面与「凡通往回写面的段皆在封条内」同口径（v1.3.9 已由一段扩到三段，此次补第四段）。
STATE_SEAL_SECTIONS = ("verdict_queue", "auto_create_retry", "projection_todos",
                       "verdict_log")

# 封条覆盖段的有界上限（**写盘前**与读盘后同口径裁剪）。v1.3.12 起 verdict_log 亦在
# 封条覆盖内 ⇒ 段长必须在签发前定界：否则守护轮内追加使段超限 → 落盘件超限 → 下轮
# load_state 读盘裁剪 → 裁剪后内容 ≠ 签发时内容 → 封条验签失败 → 守护把**自己的
# 合法写盘**误判成篡改并隔离回写面（自伤）。故签发前先按同一上限裁剪（load_state
# 的读盘裁剪口径与此一致）。
STATE_SECTION_BOUNDS = {"verdict_queue": 200, "auto_create_retry": 50,
                        "projection_todos": 200, "verdict_log": 200}

# 状态面封条告警去重（同一原因只报一次，防每轮刷屏）
_SEAL_WARN = {}


def _canonical_json(obj):
    """规范化 JSON 串（键排序、无空格）——封条载荷口径唯一。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verdict_seal_payload(item):
    """封条载荷 = 条目关键字段 + 证据锚（规范化串）。只取签发后不变的字段——
    writeback_error/requeued_ts/requeue_of 等运行期字段不入载荷（它们在封条
    签发后仍会被守护改写，入载荷会把合法项误判为篡改）。"""
    ev = item.get("evidence") or {}
    return _canonical_json({"item": {k: item.get(k) for k in VERDICT_SEAL_FIELDS},
                            "evidence": {k: ev.get(k) for k in VERDICT_SEAL_EV_FIELDS}})


def verdict_seal(item):
    """守护封条 = HMAC-SHA256(密钥, 条目关键字段规范化串)——无密钥不可自算。"""
    return _mirror_hmac(verdict_seal_payload(item))


def seal_verdict_item(item):
    """③段签发：给条目证据打上守护封条（幂等：同载荷同值）。"""
    ev = item.setdefault("evidence", {})
    ev["verdict_seal"] = verdict_seal(item)
    return item


def _seal_eq(a, b):
    """定长安全比较（攻击者可塞非 ASCII → compare_digest 抛错，视为不等）。"""
    try:
        return hmac.compare_digest(str(a), str(b))
    except (TypeError, ValueError):
        return False


def verdict_seal_check(item):
    """验守护封条。返回 (ok, reason)。"""
    ev = item.get("evidence") or {}
    got = str(ev.get("verdict_seal") or "")
    if not got:
        return False, ("无守护封条 evidence.verdict_seal——非守护③段签发（疑 loop-state "
                       "被注入/篡改），拒落盘")
    if not _seal_eq(got, verdict_seal(item)):
        return False, ("守护封条验签失败（条目关键字段与守护签发时不一致——疑 loop-state "
                       "被篡改），拒落盘")
    return True, "守护封条验签通过"


def verdict_evidence_gate(item):
    """终裁条目证据校验（RT-E12③ checker 侧）。返回 None=过；非 None=拒落盘原因。

    只查终裁 confirmed/refuted：这两态把「策略成立/被驳」写进 strategies/ 正本，
    是本发现的伪造目标面；inconclusive/pending（无清晰效应/数据未到齐）不改变
    库语义，且 v1.3.5 前旧件 evidence 无 sha 锚（恢复重入队路径在飞）——不适用。
    aggregator_sha 强对账（在位聚合器脚本逐字重算，evidence.summary 件名识别
    来源）：异版=「同路径异产物」漂移，正是 v1.3.5 绑定要拦的漂移面，fail-closed。
    mirror_sig/summary_sha 只查在位+格式：镜像签名随终态单前进、summary 临时件
    被下轮聚合覆写，跨轮逐字重算会误杀合法寄存重入队项——两锚的强对账在 ③
    消费点（聚合器读镜像/HMAC 密钥）已完成，此处不重复也不放宽。

    v1.3.9（RT-E12③ 加固）：三锚**攻击者全部可自算**（公开聚合器 sha + 捏造 hex
    即过门，2026-11-02 沙盒实证伪三锚 confirmed 经真 checker 全绿入库 e21f115），
    故门在格式与聚合器对账之上加两道**攻击者不可自算**的锚：
      ① 守护封条验签（③段签发/④段验签，无密钥不可自算）——注入或篡改条目
         （哪怕三锚逐字全对）一律拒落盘；
      ② 镜像只读门复判（来源源当前须可信，RT-E12①；不依赖密钥）——产腿停摆期
         （双源拒用）任何 confirmed/refuted 都不得落库。"""
    if item.get("status") not in ("confirmed", "refuted"):
        return None
    ev = item.get("evidence")
    if not isinstance(ev, dict):
        return ("终裁 %s 无 evidence 证据绑定（v1.3.5 三锚 mirror_sig/aggregator_sha/"
                "summary_sha）——零证据伪终裁不得落库" % (item.get("status"),))
    bad = [k for k in ("mirror_sig", "aggregator_sha", "summary_sha")
           if not EVIDENCE_SHA_RE.fullmatch(str(ev.get(k) or ""))]
    if bad:
        return ("evidence 缺合法锚 %s（须 64 位小写 hex sha256/HMAC）——零证据/残锚伪终裁不得落库"
                % bad)
    ok, why = verdict_seal_check(item)
    if not ok:
        return why
    summary_name = os.path.basename(str(ev.get("summary") or ""))
    src = next((s for s in exp_sources() if s["summary"] == summary_name), None)
    if src is None:
        return ("evidence.summary 件名 %r 非任何已知实验源汇总件（exp1/exp2）——"
                "聚合器锚无从对账，拒落盘" % summary_name)
    try:
        cur_agg = sha256_bytes(open(src["aggregator"], "rb").read())
    except OSError as e:
        return ("聚合器锚对账失败（读 %s: %s）——无法证同版，fail-closed 拒落盘"
                % (src["aggregator"], e))
    if cur_agg != ev["aggregator_sha"]:
        return ("aggregator_sha ≠ 在位聚合器脚本 %s（裁决产自异版聚合器=同路径异产物"
                "漂移，须重跑聚合重产裁决）——拒落盘" % src["aggregator"])
    trusted, reason = mirror_source_ro_gate(src)
    if not trusted:
        return ("终裁来源源 %s 镜像只读门当前拒用（%s）——无可信终态单即不得落库"
                "（产腿停摆期的伪终裁无路可入，RT-E12①）" % (src["name"], reason))
    return None


def resolve_strategies_dir():
    """strategies/ 读数链：显式覆盖 > 回写工作树 > phase2 工作树 > af 主检出。"""
    if CFG["strategies_dir"]:
        return CFG["strategies_dir"]
    for cand in (os.path.join(CFG["wb_wt"], "strategies"),
                 HOME + "/workspace/af-wt-phase2-execline/strategies",
                 os.path.join(CFG["af"], "strategies")):
        if os.path.isdir(cand):
            return cand
    return ""


def read_entry_experiment(strategies_dir, entry_id):
    """读条目 experiment 字段；条目/目录缺席返回 None（视同 status=none）。"""
    if not strategies_dir:
        return None
    p = os.path.join(strategies_dir, entry_id + ".yaml")
    if not os.path.isfile(p):
        return None
    try:
        doc = yaml.safe_load(open(p, encoding="utf-8").read())
        return (doc or {}).get("experiment")
    except Exception as e:
        log("条目读取失败 %s: %s" % (p, e))
        return None


def consensus_round(st, tmpdir):
    """跑 b-canon 到临时出目录 → diff 上一版 → 投影待办/条目漂移登记。成功才推进 prev-book。"""
    if not os.path.isfile(CFG["b_canon"]):
        raise FileNotFoundError("b-canon.py 不在位: %s" % CFG["b_canon"])
    out_md = os.path.join(tmpdir, "策略册.md")
    out_js = os.path.join(tmpdir, "策略册.jsonl")
    t0 = time.time()
    proc = sh([sys.executable, CFG["b_canon"], "--cards", CFG["cards"],
               "--out-md", out_md, "--out-jsonl", out_js], timeout=TMO["b_canon"])
    if proc.returncode != 0:
        raise RuntimeError("b-canon exit=%s: %s" % (proc.returncode, (proc.stderr or "")[-300:]))
    cur = load_book(out_js)
    prev_path = os.path.join(CFG["tmp"], "prev-book.jsonl")
    if os.path.isfile(prev_path):
        prev = load_book(prev_path)
        prev_src = "上一轮快照 %s" % prev_path
    elif os.path.isfile(CFG["canon_book"]):
        prev = load_book(CFG["canon_book"])
        prev_src = "正本 %s（首轮基线）" % CFG["canon_book"]
    else:
        prev = {}
        prev_src = "无（空基线，全量计新增）"
    new, changed, removed = diff_books(prev, cur)

    tiers = {}
    for v in cur.values():
        tiers[v["row"]["tier"]] = tiers.get(v["row"]["tier"], 0) + 1

    # 投影待办：新/变簇含 tier A/B 且 strategies/ 无对应条目
    sdir = resolve_strategies_dir()
    todos, drift = [], []
    for cid in new + changed:
        row = cur[cid]["row"]
        tier = row.get("tier")
        if tier not in ("A", "B"):
            continue
        eid = entry_id_for(cid, tier)
        epath = os.path.join(sdir, eid + ".yaml") if sdir else ""
        if epath and os.path.isfile(epath):
            if cid in changed:
                drift.append({"cluster_id": cid, "entry_id": eid,
                              "note": "簇内容变更但库条目已存在——claim/sources 漂移待人工复核"
                                      "（守护不改册值语义）"})
            continue
        todos.append({
            "cluster_id": cid, "entry_id": eid, "tier": tier,
            "rank": row.get("rank"), "topic": row.get("topic_label"),
            "name": row.get("strategy_name"), "claim": row.get("assertion"),
            "sources": _lit(row.get("card_ids")),
            "consensus": {"corpora": row.get("n_corpora"), "cards": row.get("n_cards")},
            "change_kind": "new" if cid in new else "changed",
            "status": "pending_projection",
            "blocked_reason": ("claimed_value{metric,direction,context} 策略册无对应字段、"
                               "dsl_state 三态需 AFB 语义级判定——v1 守护不臆造；待主代理/"
                               "后续自动化补 entry_draft 后由④同机制落条"),
            "material": {
                "representative_id": row.get("representative_id"),
                "citation_density": row.get("citation_density"),
                "empirical_question": row.get("empirical_question"),
                "confirm_line": row.get("confirm_line"),
                "refute_line": row.get("refute_line"),
            },
            "entry_draft": None,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 1),
        "book": {"path": out_js, "sha256": sha256_text(open(out_js, encoding="utf-8").read()),
                 "n_clusters": len(cur), "tiers": tiers},
        "baseline_book": prev_src,
        "diff": {"new": new, "changed": changed, "removed": removed},
        "strategies_dir": sdir or "(不可读)",
        "projection_todos_new": todos,
        "entry_drift": drift,
    }
    # 成功才推进 prev-book（防重放：失败则下轮对同一基线重试）
    if not DRY:
        os.makedirs(CFG["tmp"], exist_ok=True)
        with open(prev_path, "w", encoding="utf-8") as f:
            f.write(open(out_js, encoding="utf-8").read())
    return rec


def _lit(v):
    """策略册里 list 字段是 repr 字符串（实测），安全还原；失败原样返回。"""
    if isinstance(v, list):
        return v
    try:
        x = ast.literal_eval(v)
        return x if isinstance(x, list) else [v]
    except Exception:
        return [v] if v else []


# ---------------------------------------------------------------- ③ 实验排队
def experiment_candidates(st, cons):
    """task-planner 优先级规则：策略语料优先→共识强度优先（tier A>B）→册 rank 升序。"""
    if not cons or cons.get("error"):
        return []
    # 读本轮新出册（DRY/实跑都可用；prev-book 仅在缺出册路径时兜底）
    book_path = (cons.get("book") or {}).get("path") \
        or os.path.join(CFG["tmp"], "prev-book.jsonl")
    cur = load_book(book_path) if os.path.isfile(book_path) else {}
    sdir = cons.get("strategies_dir")
    if sdir == "(不可读)":
        sdir = ""
    seen = {c.get("cluster_id") for c in st.get("experiment_candidates", [])}
    seen |= set(st.get("candidates_dispatched", []))
    out = []
    for cid in cons["diff"]["new"] + cons["diff"]["changed"]:
        row = cur.get(cid, {}).get("row")
        if not row or row.get("tier") not in ("A", "B") or cid in seen:
            continue
        eid = entry_id_for(cid, row["tier"])
        exp = read_entry_experiment(sdir, eid) or {}
        status = (exp or {}).get("status", "none")
        if status != "none":
            continue
        try:
            rank = int(row.get("rank"))
        except (TypeError, ValueError):
            rank = 10 ** 9
        out.append({
            "cluster_id": cid, "entry_id": eid, "tier": row["tier"], "rank": rank,
            "topic": row.get("topic_label"), "claim": row.get("assertion"),
            "empirical_question": row.get("empirical_question"),
            "confirm_line": row.get("confirm_line"), "refute_line": row.get("refute_line"),
            "n_corpora": row.get("n_corpora"), "n_cards": row.get("n_cards"),
            "citation_density": row.get("citation_density"),
            "priority": "P0" if row["tier"] == "A" else "P1",
            "status": "queued",
            "action": ("排队待裁：实验设计需材料钉死纪律（确证/反证线+预注册判据），"
                       "执行走工厂订单 af-order（EXP-1 实证命令模式），绝不 inline 跑模型；"
                       "待主代理/后续自动化裁决（v1 边界）"),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    out.sort(key=lambda c: (0 if c["priority"] == "P0" else 1, c["rank"], c["cluster_id"]))
    return out


def _completed_orders_in(mirror_dir, pattern):
    """单源 completed 订单 id 列表（records.jsonl 末行 status=completed；空文件/坏行跳过）。

    v1.3.10（逃逸符号链接面）：**逃逸符号链接的订单目录/记录文件都不读**——glob/
    isdir/isfile/open 都追随符号链接，攻击者把 E1-* 订单目录整体换成指向树外的符号
    链接（或把订单目录内的 records.jsonl 换成符号链接）后，本函数会穿过链接读到
    攻击者可随时改写的 records.jsonl（伪造终态单即进签名面→直通聚合器）。现对
    **逃逸**链接（目标在镜像树外，判据与门同口径 _mirror_link_escapes）直接跳过
    （不读、不计入订单集）；树内链接（目标仍在树内、内容仍受镜像只读保护）照常读，
    不漏读不误拒。真实性门（_mirror_ro_verdict → _mirror_escape_links）另对该树
    fail-closed 拒用，两道独立。"""
    orders = []
    for d in sorted(glob.glob(os.path.join(mirror_dir, pattern))):
        if os.path.islink(d) and _mirror_link_escapes(mirror_dir, d):
            continue                       # 逃逸符号链接订单目录：不穿链读取
        rec = os.path.join(d, "records.jsonl")
        if os.path.islink(rec) and _mirror_link_escapes(mirror_dir, rec):
            continue                       # 逃逸符号链接记录文件：不穿链读取
        if not os.path.isfile(rec):
            continue
        last = None
        try:
            with open(rec, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        last = line
        except OSError:
            continue
        if not last:
            continue
        try:
            st = json.loads(last).get("status")
        except ValueError:
            continue
        if st == TERMINAL_ORDER_STATUS:
            orders.append(os.path.basename(d))
    return orders


# ---------------------------------------------------------------- RT-E12 真实性锚
# 红队 RT-E12（high）：镜像/签名全在「同用户可写」盘面，旧签名为无密钥内容 sha256
# （可离线逐字重算），伪造终态单被真函数接受为「新终态单」→ 直通聚合器→自动回写。
# 对应台账拦截①②落机制（此处）+拦截③ daemon 侧证据绑定（experiment_round）。
# 残余边界（如实）：同 uid 进程仍可读密钥——同信任域伪造的物理防线是①的机制性
# 只读（挂 ro/收权后不可写）；②消的是「无密钥人人可算」与 loop-state 签名面伪写。
MIRROR_KEY_PATH = _env("SIL_MIRROR_KEY", HOME + "/.config/sil-rt/mirror-signing.key")

# ---------------------------------------------------------------- RT-E85② 密钥出域（P1-设计 §2.2 K1/K4）
# 生产钥源模式开关（台账 RT-E85 拦截②施工）：
#   openbao（生产缺省）：签名钥从 gov OpenBao 取入**进程内存**——本机零钥文件；
#     取钥失败＝签名功能**停摆**（四段冻结语义，见 save_state/round_once），绝不
#     回退自生成、绝不降级为无签名照跑（逃逸问题台账:747 RT-E88 口径：停摆必须
#     显式在册且可判定红——真相在册且有人订阅：key_status 段+probe ⑩）。
#   test：仅 selftest/沙盒演练——保留旧自生成语义（0600 文件），SIL_KEY_SRC=test
#     显式声明；生产守护在 openbao 模式下永不走到旧自生成分支。
SIL_KEY_SRC = _env("SIL_KEY_SRC", "openbao")
# 预期指纹钉死（K4）：取得钥文本的 sha256 必须等于该值——迁移连续性锚。gov 侧值
# 被改/误上载 ⇒ fingerprint-mismatch 停摆红，**即便 HMAC 可算也拒用**（存量 keyed
# 签名信任连续性 fail-closed）。缺省值=迁移时点本机旧钥文件的 sha256（P0-盘点 §2.1
# 亲测：sha256sum ~/.config/sil-rt/mirror-signing.key → 8342632c…；钥值不变=存量
# exp_mirror_sigs/verdict_seal/state_seal 全部继续验签通过——覆盖面不变）。
SIL_KEY_EXPECTED_SHA256 = _env(
    "SIL_KEY_EXPECTED_SHA256",
    "8342632c2d5852d71e51f77093fa536b44567e22936d1dff054b8b6dfc8be33c")


# ---------------------------------------------------------------- RT-E85② 密钥出域（P1-设计 §2.2 K2/K3/K6/K7）
# 内存钥缓存与停摆态（openbao 模式：钥只存在于本进程内存，本机零钥文件）。
_KEY_CACHE = None          # bytearray | None（未取/已清）
_KEY_STATE = "unfetched"   # ok | failed:<分类> | unfetched（test 模式恒 "test"）
_KEY_ERR = ""              # 人读原因（key_status.err，写盘留痕）
_KEY_FP = ""               # 取得钥的 sha256 前 16（key_status.fp16）


class SigningUnavailable(RuntimeError):
    """RT-E85②（K7）：签名功能停摆异常——openbao 钥源取钥失败/指纹失配时抛出。

    三消费面（verdict_seal / 镜像签名 / state_seal）统一走停摆语义（四段冻结），
    绝不降级为「无签名继续跑」，也绝不自生成换钥（旧 :990-1006 的「钥文件缺席→
    自生成新钥继续跑」静默降级语义废除——台账:747 RT-E88 口径）。验签侧
    verify_state_seal 有专用 `except SigningUnavailable` 前置分支（:2593，H2 修法(1)）：
    停摆世复算不可得 → 专用 reason「签名停摆（复算不可得）」，load_state 据此**四段
    保留不隔离**（不消费不销毁；probe ⑧a fail(2) 不诬篡改、⑩ 精确红）；篡改/其余
    异常仍走 except Exception 兜底 → 四段隔离 fail-closed（口径不放宽）。"""


def _key_fp_ok(val_bytes):
    """RT-E85②（K4）：指纹对账纯函数——生产 fetch/T18e/演练同一口径。"""
    return hashlib.sha256(val_bytes).hexdigest() == SIL_KEY_EXPECTED_SHA256


def _parse_kv_key(data):
    """RT-E85②（T18f 态2 夹具点）：kv v2 读响应解析——缺 data 层/缺 key 字段/
    空白值一律返回空串（上游判定 not-found 分类）。纯函数：独立可负控。"""
    return str(((data.get("data") or {}).get("data") or {}).get("key") or "").strip()


def _keychain_token(cache):
    """RT-E85②（T18f 态3 夹具点）：bao-token 短时 token 签发原语——
    返回 (tok|None, err)；网络/凭据副作用全部收敛于此缝（编排/分类/对账在 fetch 真码）。
    H8.2（P4-联评）：绝对路径优先（与 v1.5 读出通道 _CS_PATH 收口同精神——不消费
    进程 PATH，防 PATH 前置可写目录换件）；在位性缺失回退裸名（留 log）。"""
    import subprocess
    bao_token_bin = os.path.expanduser("~/.local/bin/bao-token")
    if not os.path.isfile(bao_token_bin):
        bao_token_bin = "bao-token"
    env = dict(os.environ)
    env["BAO_TOKEN_CACHE_DIR"] = cache
    out = subprocess.run([bao_token_bin, "get", "sil-mirror-key-read", "--ttl", "300"],
                         env=env, capture_output=True, timeout=60)
    tok = out.stdout.decode("utf-8", "replace").strip()
    if out.returncode != 0 or not tok:
        return None, ("bao-token 签发失败 rc=%s %s"
                      % (out.returncode,
                         out.stderr.decode("utf-8", "replace").strip()[:160]))
    return tok, ""


def _kv_http_get(req, timeout=30):
    """RT-E85②（T18f 态3 夹具点）：kv HTTP 读原语——返回解析后 dict 或抛
    urllib.error.HTTPError/URLError（分类映射在 fetch 真码）。
    H8.3（P4-联评）：ProxyHandler({}) 禁代理链——未来环境加 http_proxy 不得把
    gov kv 读引去代理（引去即停摆，此处直接收口）。"""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _harden_key_memory():
    """RT-E85②（K6）：core 禁（双保险，实测宿主 ulimit -c 已 0）+ mlock 钥页。
    失败仅告警不阻断——残余如实登记（P1-设计 §2.4）：CPython 释放不清零、swap
    未加密时 mlock 失败可换出（root 域风险，同 uid 不可读进程内存：yama=1）。"""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception as e:
        log("RT-E85②: RLIMIT_CORE 收紧失败（不阻断）：%s" % e)
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        view = ctypes.c_char.from_buffer(_KEY_CACHE)
        if libc.mlock(ctypes.c_void_p(ctypes.addressof(view)),
                      ctypes.c_size_t(len(_KEY_CACHE))) != 0:
            log("RT-E85②: mlock 失败 errno=%s（不阻断；swap 残余已登记）"
                % ctypes.get_errno())
    except Exception as e:
        log("RT-E85②: mlock 不可用（不阻断）：%s" % e)


def _openbao_fetch_key():
    """RT-E85②（K3，P1-设计 §2.1）：从 gov OpenBao 取生产签名钥入内存。

    链路：本机 bao-token（短时 token，经 SSH 引导 gov 签发，TTL 300s；token 不
    落盘——私有缓存目录+取后 clear）→ HTTP GET kv/data/company/SIL-signing/
    mirror-signing（传输=100.64 tailscale overlay 内 HTTP，机密性依赖 overlay，
    P1-设计 §2.1 如实登记）。任何一步失败 → 返回 (None, 分类, 人读原因)：
    unreachable / sealed / auth-denied / timeout / not-found / fingerprint-mismatch。
    """
    import subprocess
    import urllib.request
    import urllib.error
    addr = _env("BAO_ADDR", "http://gov-host.invalid:8200")
    path = "kv/data/company/SIL-signing/mirror-signing"
    cache = os.path.join(CFG["tmp"], "rt85-token-cache")   # 守护私有 token 缓存（0700）
    tok = None
    try:
        os.makedirs(cache, exist_ok=True)
        os.chmod(cache, 0o700)
        tok, terr = _keychain_token(cache)
        if tok is None:
            return None, "auth-denied", terr
        req = urllib.request.Request(addr + "/v1/" + path,
                                     headers={"X-Vault-Token": tok})
        data = _kv_http_get(req)
        val = _parse_kv_key(data)
        if not val:
            return None, "not-found", "kv 路径无 key 字段（%s）" % path
        if not _key_fp_ok(val.encode("ascii")):
            fp = hashlib.sha256(val.encode("ascii")).hexdigest()
            return None, "fingerprint-mismatch", (
                "kv 值指纹 %s… ≠ 预期 %s…（迁移连续性锚失配——停摆，不可静默换钥）"
                % (fp[:16], SIL_KEY_EXPECTED_SHA256[:16]))
        return val.encode("ascii"), "ok", ""
    except subprocess.TimeoutExpired:
        return None, "timeout", "bao-token 签发超时（60s）"
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return None, "auth-denied", "kv 读被拒（403）——token 权限/策略面"
        if e.code == 503:
            return None, "sealed", "OpenBao 已封（503）——需运维解封"
        return None, "unreachable", "kv 读 HTTP %s" % e.code
    except urllib.error.URLError as e:
        return None, "unreachable", "gov 不可达：%s" % (getattr(e, "reason", e))
    except (OSError, ValueError) as e:
        return None, "unreachable", "IO/解析：%s" % e
    finally:
        if tok:
            try:
                subprocess.run(["bao-token", "clear", "sil-mirror-key-read"],
                               env=dict(os.environ, BAO_TOKEN_CACHE_DIR=cache),
                               capture_output=True, timeout=30)
            except Exception:
                pass                    # clear 失败不阻断（token 300s 自过期）


def _mirror_signing_key_legacy():
    """（test 模式专用，原 _mirror_signing_key 原样保留）拦截②：签名密钥首次自生成
    os.urandom(32) hex；0600 独立目录独立持有；已在位则校验并收紧过宽权限。
    生产 openbao 模式**永不调用**本函数（停摆语义取代自生成）。"""
    d = os.path.dirname(MIRROR_KEY_PATH)
    os.makedirs(d, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    try:
        key = open(MIRROR_KEY_PATH, "rb").read().strip()
    except OSError:
        key = b""
    if key:
        mode = stat.S_IMODE(os.stat(MIRROR_KEY_PATH).st_mode)
        if mode != 0o600:
            os.chmod(MIRROR_KEY_PATH, 0o600)
            log("RT-E12②: 签名密钥权限 %o→0600 收紧（%s）" % (mode, MIRROR_KEY_PATH))
        return key
    key = os.urandom(32).hex().encode("ascii")
    fd = os.open(MIRROR_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    log("RT-E12②: 生成镜像签名密钥 %s（0600）——旧无密钥 sha256 签名口径随即作废（状态面一次性迁移见 _migrate_mirror_sig_scheme）"
        % MIRROR_KEY_PATH)
    return key


def _mirror_signing_key():
    """RT-E85②（K2/K5）：返回当前签名钥（bytes）。

    openbao 模式（生产缺省）：进程生命周期取钥一次入内存缓存（_KEY_CACHE）；
    取钥失败/指纹失配 → 置停摆态（_KEY_STATE=failed:<分类>）并 raise
    SigningUnavailable——**绝不自生成、绝不落盘、绝不静默换钥**。
    SIL_MIRROR_KEY 环境变量在 openbao 模式下禁用（K5，运行时判——P0-盘点 R2：
    同 uid 经 env 注入换钥的面收口；出现非空值即拒启动）。
    test 模式：旧自生成语义原样（0600 文件），仅供 selftest/沙盒。"""
    global _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP
    if SIL_KEY_SRC == "test":
        _KEY_STATE = "test"
        return _mirror_signing_key_legacy()
    if os.environ.get("SIL_MIRROR_KEY", "").strip():
        raise SystemExit("RT-E85②: SIL_MIRROR_KEY 在 openbao 钥源模式下禁用"
                         "（env 注入换钥面已收口，P0-盘点 R2）——去掉该环境变量后重试")
    if _KEY_CACHE is not None:
        return bytes(_KEY_CACHE)
    if _KEY_STATE.startswith("failed"):
        raise SigningUnavailable("签名钥停摆（%s）：%s" % (_KEY_STATE, _KEY_ERR))
    key, state, err = _openbao_fetch_key()
    _KEY_STATE = state if state == "ok" else "failed:" + state
    _KEY_ERR = err
    if key is None:
        log("RT-E85②: 取钥失败（%s）→ 签名功能停摆（不降级、不自生成）：%s" % (state, err))
        raise SigningUnavailable("取钥失败（%s）：%s" % (state, err))
    # 入口指纹锚（K4 防御纵深第二道）：fetch 内部已对账一次，此处对「进入缓存的
    # 钥」再对账一次——任何取钥路（真 fetch/未来替代路/被换件的 fetch）返回的钥
    # 都强制过锚，指纹失配即停摆，不可静默换钥。
    if not _key_fp_ok(key):
        _KEY_STATE = "failed:fingerprint-mismatch"
        _KEY_ERR = ("kv 值指纹 %s… ≠ 预期 %s…（迁移连续性锚失配——停摆，不可静默换钥）"
                    % (hashlib.sha256(key).hexdigest()[:16], SIL_KEY_EXPECTED_SHA256[:16]))
        log("RT-E85②: %s" % _KEY_ERR)
        raise SigningUnavailable(_KEY_ERR)
    _KEY_CACHE = bytearray(key)
    _KEY_FP = hashlib.sha256(key).hexdigest()[:16]
    _harden_key_memory()
    log("RT-E85②: 生产签名钥已入内存（openbao；fp16=%s；本机零钥文件）" % _KEY_FP)
    return bytes(_KEY_CACHE)


def _key_signing_halted():
    """RT-E85②：签名功能是否停摆（openbao 模式且取钥未成功）——冻结轮判据。"""
    return SIL_KEY_SRC == "openbao" and _KEY_STATE.startswith("failed")


def _mirror_hmac(text):
    """拦截②：镜像签名 = HMAC-SHA256(密钥, 内容串联)——无密钥不可离线逐字重算。
    RT-E85②（K7）：openbao 模式无钥 → raise SigningUnavailable（签名停摆；
    消费面统一走四段冻结，见 save_state/round_once）。"""
    return hmac.new(_mirror_signing_key(), text.encode("utf-8"), hashlib.sha256).hexdigest()


def _mirror_uid_writable_path(d, _seen=None):
    """镜像树内首个对当前 uid 可写的路径（顶层/子目录/订单文件/**符号链接目标内部**）。

    v1.3.6（RT-E12①回归修复）：镜像树内首个对当前 uid 可写的路径（顶层/子目录/
    订单文件），全不可写返回 None。旧门只查顶层目录——同 uid 一次 chmod 555 顶层
    即骗过（订单文件保持 644 可原地逐字改写、子目录保持 755 可换件，2026-11-02
    沙盒实证），目录不可写只挡增删/换名。
    v1.3.10（逃逸符号链接面回归修复）：旧实现用 os.walk（followlinks=False → **不
    下降**符号链接目录）+ os.access（只判链接**目标本身**的权限位）——链接目标目录
    **内部**的文件从不被检查（docstring 自称「符号链接由 os.access 追随判定」与实现
    不符：只追到目标目录的权限，目标内部的文件一律漏检；E1-* 订单目录整体换成符
    号链接即骗过门，2026-11-02 沙盒实证）。现改为：符号链接按**目标递归扫描**
    （visited 集合环保护），链接目标内部的文件/目录一并计入可写面。"""
    if _seen is None:
        _seen = set()
    try:
        key = os.path.realpath(d)
    except OSError:
        key = d
    if key in _seen:
        return None
    _seen.add(key)
    if os.access(d, os.W_OK):
        return d
    try:
        entries = list(os.scandir(d))
    except OSError:
        return None
    for e in entries:
        p = e.path
        try:
            if e.is_symlink():
                # 链接：os.access 追随到目标（目标目录本身可写 → 命中），并递归
                # 扫目标内部（目标内部可写 → 也命中）
                w = _mirror_uid_writable_path(p, _seen)
            elif e.is_dir(follow_symlinks=False):
                w = _mirror_uid_writable_path(p, _seen)
            else:
                w = p if os.access(p, os.W_OK) else None
        except OSError:
            continue
        if w:
            return w
    return None


def _mirror_link_escapes(root, p):
    """链接 p 的目标是否**逃出**镜像根 root（realpath 口径；不可解析＝按逃逸处理）。

    与 _mirror_escape_links 同口径（门拒逃逸、消费侧不读逃逸，两处一致）：树内
    链接（目标仍在镜像树内，内容仍受镜像只读保护）不算逃逸——不误拒、不漏读。"""
    try:
        r = os.path.realpath(root)
        tgt = os.path.realpath(p)
    except OSError:
        return True
    return not (tgt == r or tgt.startswith(r + os.sep))


def _mirror_escape_links(d, _seen=None):
    """镜像树内的「逃逸符号链接」清单：符号链接解析后的目标落在镜像树**外**者。
    返回 [(链接路径, 目标 realpath), ...]（发现顺序）；无则 []。

    v1.3.10（逃逸符号链接面，2026-11-02）：ro 挂载只保护**本挂载点内的 inode**——
    树内符号链接指向树外（另一挂载点/普通目录）时，守护的订单枚举
    （_completed_orders_in）与聚合器（b-exp1/b-exp2-aggregate.py）都**穿过该链接**
    读**树外**内容，而那部分内容完全不受 ro 保护（uid 可随时原地改写、或把整个
    目标目录整体换掉）——「镜像只读」的可信结论不覆盖链接目标 ⇒ 该树不可信
    （fail-closed）。树内链接（目标仍在同一棵树内）**不**构成逃逸（内容仍在
    ro 保护范围内），但链接目标内部仍要继续扫（堵「树内链接→树内目录→树外链接」）。
    判据＝realpath 后是否仍落在镜像树根 realpath 之下（visited 集合环保护）。"""
    if _seen is None:
        _seen = set()
    try:
        root = os.path.realpath(d)
    except OSError:
        return []
    out = []
    stack = [d]
    while stack:
        cur = stack.pop()
        try:
            key = os.path.realpath(cur)
        except OSError:
            continue
        if key in _seen:
            continue
        _seen.add(key)
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for e in entries:
            p = e.path
            try:
                if e.is_symlink():
                    tgt = os.path.realpath(p)
                    if tgt == root or tgt.startswith(root + os.sep):
                        stack.append(tgt)        # 树内链接：继续扫其内部
                    else:
                        out.append((p, tgt))      # 逃逸链接（目标在树外）
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(p)
            except OSError:
                continue
    return out


def _mirror_perm_diag(d):
    """权限位诊断（**不作可信依据**，RT-E85④）：树内首个对当前 uid 可写的路径，
    全不可写返回 None。权限位是同 uid 可逆面——「先改后收权」不可察（写入伪造
    内容后再 chmod 收权，门看到的仍是一棵「全不可写」的树），故只作文案诊断，
    不构成「镜像可信」的依据。"""
    w = _mirror_uid_writable_path(d)
    if w:
        return "树内 %s 对 uid 可写（原地改写面）" % w
    return "树内对 uid 全不可写（权限收权不构成机制性只读：同 uid 可逆）"


def _cs_path():
    """confstr _CS_PATH（libc 系统默认工具目录，如 /bin:/usr/bin）。confstr 读的是
    libc 常量，**不经本进程 PATH 环境变量**；取不到时退回 POSIX 默认 "/bin:/usr/bin"。"""
    try:
        return os.confstr("CS_PATH") or "/bin:/usr/bin"
    except (ValueError, OSError):
        return "/bin:/usr/bin"


def _system_tool(name):
    """系统工具解析：按 confstr _CS_PATH 逐目录找首个可执行 name，返回**绝对路径**；
    解析不到返回 None。

    **为什么绝不裸名/进程 PATH 解析（v1.3.14 同 uid 换件面，2026-11-03）**：裸名由
    execvp 按本进程 PATH 逐目录解析，而在役守护 PATH 前置 ~/bin、~/.local/bin、
    ~/.cargo/bin 三个**同 uid 可写**目录——任何同 uid 进程在其中落假件即按 POSIX
    解析序胜出，把判据的 kernel 挂载态读数（RT-E85④ 信任锚）整体换掉。_CS_PATH 只含
    系统工具目录（root 所有），同 uid 换件面被移出解析域。"""
    cs = _cs_path()
    for d in cs.split(":"):
        if not d:
            continue
        p = os.path.join(d, name)
        try:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        except OSError:
            continue
    return None


def _mirror_mount_options(d):
    """真机制只读判定面（只读）：findmnt OPTIONS。返回 (opts|None, how)。

    opts=None＝findmnt 不可用/超时/非零返回——**无法证实**机制性只读 →
    fail-closed（不可证即不可信，RT-E85④）。

    v1.3.14（判据读出通道换件面收口，2026-11-03）：findmnt 一律经 _system_tool 按
    confstr _CS_PATH 解析为**绝对路径**再调，绝不裸名走进程 PATH（在役守护 PATH 前置
    三个同 uid 可写目录——裸名解析下假 findmnt 恒打印 ro 即伪造 kernel 挂载态读数，
    RT-E85④ 信任锚失效；沙盒复现在案）。子进程 env 只给 {PATH=_CS_PATH, LC_ALL=C}
    （不继承父进程全环境，堵 LD_PRELOAD/LD_LIBRARY_PATH 对绝对路径二进制的注入面；
    LC_ALL=C 保 OPTIONS 输出不受 locale 影响）。`how` 附解析出的绝对路径＝审计可查
    「这次读数是哪个二进制读的」。解析不到系统 findmnt → opts=None → fail-closed。"""
    fp = _system_tool("findmnt")
    if not fp:
        return None, "findmnt 不可用（_CS_PATH=%s 解析不到系统 findmnt）" % _cs_path()
    try:
        r = subprocess.run([fp, "-no", "OPTIONS", "-T", d],
                           capture_output=True, text=True, timeout=10,
                           env={"PATH": _cs_path(), "LC_ALL": "C"})
        if r.returncode == 0:
            opts = [o.strip() for o in (r.stdout or "").strip().split(",") if o.strip()]
            return opts, "findmnt(%s) OPTIONS=%s" % (fp, ",".join(opts) or "?")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None, "findmnt(%s) 不可用" % fp


def _mirror_ro_verdict(opts, how, d):
    """真机制只读裁决（RT-E85④ + 逃逸符号链接面）：opts＝findmnt OPTIONS 列表
    （None＝无读数）。返回 (trusted, reason)。

    **唯一可信路径：镜像树内无逃逸符号链接 且 OPTIONS 含 ro 且不含 rw**。其余
    （rw 挂载 / 无读数 / 树内存在逃逸符号链接）一律不可信——权限位收权腿（树内对
    uid 全不可写）已降级为诊断，不是可信依据。

    v1.3.10（逃逸符号链接面，2026-11-02）：ro 挂载只保护本挂载点内的 inode；树内
    符号链接指向树外时，守护枚举与聚合器都穿过该链接读**树外**内容（不受 ro 保
    护、可随时改写）——「镜像只读」结论不覆盖链接目标 ⇒ 逃逸链接一律 fail-closed
    （即便 findmnt=ro）。"""
    esc = _mirror_escape_links(d)
    if esc:
        p, tgt = esc[0]
        return False, ("%s——镜像树内存在逃逸符号链接 %s → %s（链接目标在镜像树外，"
                       "不受本挂载 ro 保护，可被随时整体换掉/原地改写；守护订单枚举"
                       "与聚合器都穿过该链接读它）——镜像非机制性只读，终态单不可信"
                       "（逃逸符号链接面，fail-closed）" % (how, p, tgt))
    if opts is None:
        return False, ("%s——无法证实机制性只读（无 findmnt 读数），终态单不可信"
                       "（RT-E85④，fail-closed）" % how)
    if "ro" in opts and "rw" not in opts:
        return True, "%s（挂载 ro，机制性只读）" % how
    return False, ("%s——非 ro 挂载，镜像非机制性只读（%s），终态单不可信（RT-E85④）；"
                   "恢复=把镜像目录以 ro 方式挂载（findmnt OPTIONS 含 ro）后守护下轮"
                   "自动解拒——**不得用 chmod 收权替代**（权限位同 uid 可逆，不构成"
                   "机制性只读）" % (how, _mirror_perm_diag(d)))


def mirror_source_ro_gate(src, mount_opts=None):
    """拦截①：镜像源是否被**机制性**只读。返回 (trusted, reason)。非机制性只读 =
    不可信输入：调用方 fail-closed（不跑聚合器/签名不前进/裁决不产生）。台账拦截①
    「非 ro 即拒启」在此落为「非 ro 即拒用」：拒启会把①感知/②共识/⑤记账（含本
    告警的留痕通道）一并停摆，拒用把不信任精确落在消费点。

    v1.3.8（RT-E85④，2026-11-02）：**判据唯一＝findmnt OPTIONS 含 ro**。旧门把
    「目录与镜像树对 uid 全不可写」（权限强制只读腿）当可信分支，而权限位是同
    uid 可逆面：同 uid 进程可「先改后收权」——写入伪造内容后 chmod 收权，门把
    **已被伪造**的镜像重新判 trusted=True 并放行进聚合（2026-11-02 沙盒实证：
    findmnt=rw + 树内全不可写 → trusted=True，被信任的是伪造内容；chmod 644 后
    原地改写成功＝uid 可写是所有者随时可逆的面）。故 rw+收权分支降级为不可信；
    findmnt 无读数（不可用/超时）亦 fail-closed（不可证即不可信）。
    v1.3.10（逃逸符号链接面）：另加一道**结构性**腿——镜像树内存在**逃逸符号
    链接**（目标落在镜像树外）即 fail-closed 拒用，即便 findmnt=ro：ro 挂载只保护
    本挂载点内的 inode，链接目标在树外完全不受保护（可被随时整体换掉/原地改写），
    而守护的订单枚举与两个聚合器都穿过该链接读它——「镜像只读」的可信结论不覆盖
    链接目标。树内链接（目标仍在树内）不构成逃逸（内容仍受 ro 保护），不误拒。
    mount_opts 仅供 selftest 夹具注入（生产调用点一律不传 → 走真实 findmnt）。"""
    d = src["dir"]
    if not os.path.isdir(d):
        return False, "镜像目录缺席: %s" % d
    if mount_opts is None:
        opts, how = _mirror_mount_options(d)
    else:
        opts = list(mount_opts)
        how = "findmnt OPTIONS=%s（selftest 夹具注入）" % ",".join(opts)
    return _mirror_ro_verdict(opts, how, d)


def exp_mirror_signatures(keyed=True):
    """v1.1：逐源终态单签名 {source_name: (sig, orders)}（completed 订单 id 集合哈希）。

    exp1 源（E1-*）与 exp2 源（E2-*）分源记账：任一侧有新终态单 → 该侧签名变 →
    只跑该侧聚合器（不重复跑未变侧）。
    v1.3.1：签名扩容 = 订单集合 sha + 该源聚合器汇总件内容 sha——聚合器修复/
    人工重跑等「同订单、新产出」情形（2026-10-31 EXP-2 实证：收割路径 bug 修复
    使 verdict pending→inconclusive 而订单镜像零变化）也能触发重读与回写。
    v1.3.5（RT-E12②）：签名=HMAC-SHA256(密钥 0600)（内容串联口径不变）——无密钥
    不可离线逐字重算。keyed=False 仅复算旧无密钥 sha256 口径，供状态面一次性迁移
    对账（_migrate_mirror_sig_scheme），业务判据一律 keyed。"""
    out = {}
    for src in exp_sources():
        orders = _completed_orders_in(src["dir"], src["glob"])
        parts = ["\n".join(orders)]
        sp = os.path.join(src["spec_dir"], src["summary"])
        if os.path.isfile(sp):
            try:
                parts.append("summary:" + sha256_text(open(sp, encoding="utf-8").read()))
            except OSError:
                pass
        text = "|".join(parts)
        out[src["name"]] = (_mirror_hmac(text) if keyed else sha256_text(text), orders)
    return out


def _migrate_mirror_sig_scheme(st, sigs):
    """v1.3.5（RT-E12②）一次性迁移：loop-state 里旧无密钥 sha256 签名 → keyed HMAC。

    仅当旧口径对当前镜像复算==存值（镜像自旧签名后零漂移）才把 keyed 签名采纳为
    基线——采纳不引入未审计增量（镜像内容与旧签名所签内容逐字一致）；不匹配
    （切换窗内镜像有漂移）则不动 stored：维持 changed 走聚合路径，并告警「无真实
    性锚窗口内漂移」。返回迁移后的 stored 视图。"""
    stored = dict(st.get("exp_mirror_sigs") or {})
    legacy = exp_mirror_signatures(keyed=False)
    migrated, drifted = [], []
    for src in exp_sources():
        name = src["name"]
        cur = stored.get(name)
        if cur is None or cur == sigs[name][0]:
            continue                                   # 新口径已对齐/无基线（首轮建基线）
        if cur == legacy[name][0]:
            stored[name] = sigs[name][0]
            st.setdefault("exp_mirror_sigs", {})[name] = sigs[name][0]
            migrated.append(name)
        else:
            drifted.append(name)
            log("RT-E12② 迁移告警：%s 源存值与旧口径复算不符（无真实性锚窗口内镜像漂移）→ 维持 changed 走聚合路径" % name)
    if migrated:
        st["exp_mirror_sig"] = exp_mirror_signature()[0]   # 兼容字段同步（不单独作判据）
        log("RT-E12② 签名 keyed 化迁移：%s（旧 sha256 基线经零漂移核验后采纳为 HMAC 基线）"
            % ",".join(migrated))
    return stored


def exp_mirror_signature():
    """兼容 v1 的单选口径：合并签名 + 逐源订单表（旧状态 exp_mirror_sig 即 exp1 口径）。"""
    sigs = exp_mirror_signatures()
    combined = sha256_text("|".join("%s:%s" % (k, v[0]) for k, v in sorted(sigs.items())))
    return combined, {k: v[1] for k, v in sigs.items()}


def map_verdict_to_entry(exp_id, book):
    """终裁→条目确定性映射：experiments-v1.json primary_claim.card_id → 簇 → 条目。

    v1.1：目标簇无论档位都返回 target_entry_id（自动建条目用的命名空间 id，
    tier C/D 用平铺 st-C0XX）；tier A/B 时 target_entry 同值（既有条目更新路径）。
    册内材料（name/claim/sources/consensus）一并带回，④自动建条目自取不再重读。
    """
    spec_path = os.path.join(CFG["exp1_dir"], "experiments-v1.json")
    if not os.path.isfile(spec_path):
        return {"error": "spec 不在位: %s" % spec_path}
    spec = json.load(open(spec_path, encoding="utf-8"))
    exp = next((e for e in spec.get("experiments", []) if e.get("exp_id") == exp_id), None)
    if not exp:
        return {"error": "spec 无 %s" % exp_id}
    card = (exp.get("primary_claim") or {}).get("card_id")
    if not card:
        return {"error": "%s 无 primary_claim.card_id" % exp_id}
    hit = [cid for cid, v in book.items() if card in _lit(v["row"].get("card_ids"))]
    sup = []
    for s in exp.get("supporting_cards") or []:
        sc = s.get("card_id") if isinstance(s, dict) else s
        for cid, v in book.items():
            if sc in _lit(v["row"].get("card_ids")) and cid not in sup:
                sup.append(cid)
    if not hit:
        return {"primary_claim_card": card, "target_cluster": None,
                "note": "主断言卡 %s 不在策略册任何簇内" % card}
    cid = hit[0]
    row = book[cid]["row"]
    tier = row.get("tier")
    eid = entry_id_for(cid, tier)
    return {"primary_claim_card": card, "target_cluster": cid, "target_tier": tier,
            "target_entry": eid if tier in ("A", "B") else None,
            "target_entry_id": eid,
            "target_rank": row.get("rank"),
            "supporting_clusters": sup,
            "entry_material": {
                "name": row.get("strategy_name"), "claim": row.get("assertion"),
                "sources": _lit(row.get("card_ids")), "topic": row.get("topic_label"),
                "corpora": row.get("n_corpora"), "cards": row.get("n_cards"),
                "representative_id": row.get("representative_id"),
                "citation_density": row.get("citation_density"),
                "empirical_question": row.get("empirical_question"),
                "confirm_line": row.get("confirm_line"),
                "refute_line": row.get("refute_line"),
            },
            "note": "主断言卡 %s → 簇 %s（tier %s）" % (card, cid, tier)}


def _verdict_note(verdict, v, summary_path, sig, n_terminal, extra=""):
    """终裁 note：只记聚合器实际产出的键（pending 无 n_p/main_diff 等判读键——
    不臆造数值）；精确判词与 pending_reason 原样进 note。"""
    parts = ["终裁 %s" % verdict]
    if v.get("pending_reason"):
        parts.append("pending_reason=%s" % v["pending_reason"])
    for k, unit in (("n_p", ""), ("main_diff_pp", "pp"), ("mcnemar_p_one_sided", ""),
                    ("main_tost_cp90_pp", "pp"), ("gate_fires", "")):
        if v.get(k) is not None:
            parts.append("%s=%s%s" % (k, v[k], unit))
    parts.append("来源 %s（镜像 sig=%s，completed=%d）" % (os.path.basename(summary_path), sig[:12], n_terminal))
    if extra:
        parts.append(extra)
    return "；".join(parts) + "。"


def _resolve_book_for_verdict(cons):
    """②出册路径优先，缺则上一轮快照；都无 → {}（调用方按"映射延期"处理）。
    v1.3：cons 可为 None（noop 轮 ③照跑——②未跑/失败时终裁映射走快照兜底）。"""
    p = ((cons or {}).get("book") or {}).get("path") or os.path.join(CFG["tmp"], "prev-book.jsonl")
    return load_book(p) if os.path.isfile(p) else {}


def experiment_round(st, cons):
    """(a) 候选排队；(b) 逐源新终态单 → 对应聚合器+判定门 → 裁决队列/裁决日志。

    v1.1 补丁①：镜像源扩容为 exp1(E1-*)+exp2(E2-*) 逐源签名；仅签名变化的源
    跑自己的聚合器（未变源不重复跑）。v1.1 补丁②：目标簇无库条目（含 tier
    C/D）的终裁同样进裁决队列（自动建条目），不再 target_entry=None 跳过。
    """
    rec = {"candidates": [], "verdicts": [], "mirror": {}, "errors": []}
    # (a) 候选
    try:
        cands = experiment_candidates(st, cons)
        rec["candidates"] = cands
    except Exception as e:
        rec["errors"].append("候选排队异常: %s" % e)
        log("③候选排队异常（不崩）: %s" % e)
    # (b) 逐源终态单签名
    try:
        sigs = exp_mirror_signatures()
    except Exception as e:
        rec["errors"].append("镜像签名异常: %s" % e)
        log("③镜像签名异常（不崩）: %s" % e)
        return rec
    stored = dict(st.get("exp_mirror_sigs") or {})
    if not stored and st.get("exp_mirror_sig") and sigs.get("exp1") \
            and sigs["exp1"][0] == st["exp_mirror_sig"]:
        # v1→v1.1 状态迁移：旧 combined 签名即 exp1 单选口径（glob E1-*）——逐源
        # 对齐避免扩容首轮把 143 个既有 E1 单误判成"新终态单"重复聚合。立即落盘
        # （exp1 源确实已在旧口径下聚合成功过，不是跳过未跑源）。
        stored["exp1"] = sigs["exp1"][0]
        st.setdefault("exp_mirror_sigs", {})["exp1"] = sigs["exp1"][0]
        log("③状态迁移：旧 exp_mirror_sig 对齐 exp1 源（避免重复聚合 143 既有单）")
    # v1.3.5（RT-E12②）签名口径迁移：旧无密钥 sha256 存值零漂移核验后采纳为
    # keyed HMAC 基线（防 143+28 既有单被误判新终态单重复聚合）；漂移源维持
    # changed 走聚合路径并告警（无真实性锚窗口内变化不静默采纳）。
    if any(stored.get(s["name"]) not in (None, sigs[s["name"]][0]) for s in exp_sources()):
        stored = _migrate_mirror_sig_scheme(st, sigs)
    changed = [s for s in exp_sources() if stored.get(s["name"]) != sigs[s["name"]][0]]
    # v1.3.5（RT-E12①）只读真实性门：非机制性只读的镜像源=不可信输入——拒用
    # （不跑聚合器/签名不前进/裁决不产生）；门位翻转才写变更日志（防 600s 刷屏）。
    # v1.3.8（RT-E85④）：判据唯一＝findmnt OPTIONS 含 ro（rw+收权=不可信）。
    gate = {s["name"]: mirror_source_ro_gate(s) for s in exp_sources()}
    gprev = st.setdefault("mirror_ro_gate", {})
    for s in exp_sources():
        t = gate[s["name"]][0]
        if gprev.get(s["name"]) is not t:
            changelog("SIL 镜像真实性门（RT-E12①/RT-E85④）：%s 源%s（%s）" % (
                s["name"], "可信：机制性只读（挂载 ro）" if t else "不可信：非机制性只读，终态单拒用",
                gate[s["name"]][1][:160]))
            gprev[s["name"]] = t
    # 持续拒用再告警（本批 2026-11-02）：上面翻转告警只在门位变化瞬间写一行，双源
    # 持续拒用（裁决产出停摆）期间变更日志静默——巡检间隔内审计面零告警（2026-11-02
    # 实证：00:13 翻转一行后 3.5h+ 零告警，同期 keepalive/轮次/队列全绿）。拒用未解时
    # 每 MIRROR_GATE_REALARM_S 重报一行；st 内记上次告警 epoch（随 state/心跳持久化）。
    _untrusted = sorted(n for n in gate if not gate[n][0])
    if _untrusted:
        _now_ep = time.time()
        if _now_ep - (st.get("mirror_ro_gate_alarm_ts") or 0) >= MIRROR_GATE_REALARM_S:
            st["mirror_ro_gate_alarm_ts"] = _now_ep
            changelog("SIL 镜像真实性门持续拒用再告警（RT-E12①/RT-E85④，%ds 节奏防静默）：%s "
                      "源终态单仍拒用——裁决产出停摆中（签名不前进、无新裁决/回写）；"
                      "恢复=把镜像目录以 ro 方式挂载（findmnt OPTIONS 含 ro）后下轮自动"
                      "解拒——不得用 chmod 收权替代（权限位同 uid 可逆）"
                      % (MIRROR_GATE_REALARM_S, "+".join(_untrusted)))
    rec["mirror"] = {"sigs": {k: v[0] for k, v in sigs.items()},
                     "n_terminal": {k: len(v[1]) for k, v in sigs.items()},
                     "dirs": {s["name"]: s["dir"] for s in exp_sources()},
                     "changed_sources": [s["name"] for s in changed],
                     "ro_gate": {k: {"trusted": v[0], "reason": v[1]} for k, v in gate.items()}}
    if not changed:
        rec["mirror"]["changed"] = False
        return rec
    rec["mirror"]["changed"] = True
    log("③检测到新终态单（%s；completed=%s）→ 跑对应源聚合器" % (
        ",".join("%s sig %s→%s" % (s["name"], (stored.get(s["name"]) or "-")[:12],
                                    sigs[s["name"]][0][:12]) for s in changed),
        {k: len(v[1]) for k, v in sigs.items()}))
    if DRY:
        rec["mirror"]["dry"] = "DRY：不跑聚合器/不更新签名"
        return rec
    tmpdir = os.path.join(CFG["tmp"], "exp-out")
    os.makedirs(tmpdir, exist_ok=True)
    book = _resolve_book_for_verdict(cons)
    verdict_gate_ran = False
    for src in changed:
        if not gate[src["name"]][0]:
            rec["errors"].append("镜像真实性门未过(%s): %s——拒用该源终态单，不跑聚合器/签名不前进（RT-E12① fail-closed）"
                                 % (src["name"], gate[src["name"]][1]))
            log("③镜像真实性门未过（%s：%s）→ 拒用该源终态单，签名不前进（RT-E12①）"
                % (src["name"], gate[src["name"]][1]))
            continue
        try:
            p1 = sh([sys.executable, src["aggregator"], "--mirror", src["dir"],
                     src["dir_flag"], src["spec_dir"], "--out-dir", tmpdir],
                    timeout=TMO["exp2"] if src["name"] == "exp2" else TMO["exp1"])
            if p1.returncode != 0:
                raise RuntimeError("%s exit=%s: %s" % (
                    os.path.basename(src["aggregator"]), p1.returncode,
                    (p1.stderr or "")[-300:]))
            summary = json.load(open(os.path.join(tmpdir, src["summary"]), encoding="utf-8"))
        except Exception as e:
            rec["errors"].append("聚合失败(%s): %s" % (src["name"], e))
            log("③聚合失败（不崩，%s 源签名不前进下轮重试）: %s" % (src["name"], e))
            continue
        # 判定程序唯一性门（独立跑一遍；exp2 聚合器内部亦经 importlib 加载同件）
        try:
            p2 = sh([sys.executable, CFG["b_verdict"], "--spec",
                     os.path.join(CFG["exp1_dir"], "experiments-v1.json")], timeout=TMO["verdict"])
            if p2.returncode != 0:
                raise RuntimeError("b-verdict-unique exit=%s: %s" % (p2.returncode, (p2.stderr or "")[-300:]))
            verdict_gate_ran = True
        except Exception as e:
            rec["errors"].append("判定门失败(%s): %s" % (src["name"], e))
            log("③判定门失败（不崩，%s 源签名不前进下轮重试）: %s" % (src["name"], e))
            continue
        v = summary.get("verdict") or {}
        verdict = v.get("verdict")
        if not verdict:
            rec["errors"].append("聚合产物无 verdict（%s）" % src["name"])
            continue
        # v1.3.5（RT-E12③ daemon 侧）：裁决证据绑定聚合器脚本与输出件 sha256
        # （checker 侧校验另行；本绑定使 verdict_log/queue 条目可对账溯源到
        # 恰好那次聚合的代码与产物，防「同路径异产物」漂移不可见）。
        try:
            prov = {"aggregator_sha": sha256_bytes(open(src["aggregator"], "rb").read()),
                    "summary_sha": sha256_bytes(open(os.path.join(tmpdir, src["summary"]), "rb").read())}
        except OSError as e:
            prov = {"aggregator_sha": None, "summary_sha": None, "prov_error": str(e)[:120]}
            log("③证据绑定失败（不崩，%s）: %s" % (src["name"], e))
        n_terminal = len(sigs[src["name"]][1])
        if not book:
            # 复核 F3 修复：策略册不可用（②失败/无快照）——映射无从求值。终裁照记、
            # 明确写"延期"，**签名不前进**（下轮对同一批终态单重映射）；不谎称"卡不在簇内"。
            rec["errors"].append("策略册不可用（②失败或无快照）→ 终裁映射延期，签名不前进")
            log("③终裁 %s 已取得，但策略册不可用（②失败/无快照）→ 映射延期、签名不前进（下轮重映射）"
                % verdict)
            st.setdefault("verdict_log", []).append(seal_verdict_item({
                "exp_id": summary.get("exp_id"), "verdict": verdict,
                "status": VERDICT_STATUS_MAP.get(verdict, VERDICT_FALLBACK),
                "note": _verdict_note(verdict, v, os.path.join(tmpdir, src["summary"]),
                                      sigs[src["name"]][0], n_terminal,
                                      "映射延期：策略册不可用（②失败或无快照），签名不前进，下轮重映射"),
                "evidence": dict({"summary": os.path.join(tmpdir, src["summary"]),
                                  "mirror_sig": sigs[src["name"]][0], "n_terminal": n_terminal}, **prov),
                "outcome": "延期：策略册不可用，签名不前进，下轮重映射",
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }))
            continue
        m = map_verdict_to_entry(summary.get("exp_id", "EXP-1"), book)
        note = _verdict_note(verdict, v, os.path.join(tmpdir, src["summary"]),
                             sigs[src["name"]][0], n_terminal,
                             "判定程序唯一性门 b-verdict-unique exit=0。%s" % m.get("note", ""))
        rec_verdict = {
            "exp_id": summary.get("exp_id"), "verdict": verdict,
            "status": VERDICT_STATUS_MAP.get(verdict, VERDICT_FALLBACK),
            "note": note, "primary_claim_card": m.get("primary_claim_card"),
            "target_cluster": m.get("target_cluster"), "target_tier": m.get("target_tier"),
            "target_entry": m.get("target_entry"),
            "target_entry_id": m.get("target_entry_id"),
            "target_rank": m.get("target_rank"),
            "supporting_clusters": m.get("supporting_clusters"),
            "entry_material": m.get("entry_material"),
            "evidence": dict({"summary": os.path.join(tmpdir, src["summary"]),
                              "spec": os.path.join(CFG["exp1_dir"], "experiments-v1.json"),
                              "mirror_sig": sigs[src["name"]][0], "n_terminal": n_terminal}, **prov),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        # v1.3.9（RT-E12③ 加固）：③段签发守护封条——只有守护自己签发过的终裁
        # 才带得上封条；注入/篡改的条目（哪怕三锚逐字全对）④段验签必失败。
        seal_verdict_item(rec_verdict)
        rec["verdicts"].append(rec_verdict)
        st.setdefault("exp_mirror_sigs", {})[src["name"]] = sigs[src["name"]][0]  # 签名前进
        if rec_verdict["target_cluster"]:
            # v1.1：目标簇在册即排队（tier A/B→既有条目更新；tier C/D→自动建条目）
            st.setdefault("verdict_queue", []).append(rec_verdict)
        else:
            st.setdefault("verdict_log", []).append(dict(
                rec_verdict, outcome="不回写：主断言卡不在策略册任何簇内"))
            log("③终裁 %s 按映射规则不回写（%s）——登记裁决日志" % (verdict, m.get("note")))
    if verdict_gate_ran:
        st["exp_mirror_sig"] = exp_mirror_signature()[0]   # 兼容字段同步（不单独作判据）
    return rec


# ---------------------------------------------------------------- ④ 回写
def find_experiment_block(lines):
    """定位顶层 experiment 键。返回 (start, end_exclusive, flow_rest)；flow_rest 非空=flow 单行。"""
    for i, ln in enumerate(lines):
        m = re.match(r"^experiment:[ \t]*(.*)$", ln)
        if not m:
            continue
        rest = m.group(1).strip()
        if rest:
            return i, i + 1, rest
        j, last_content = i + 1, i + 1
        while j < len(lines):
            s = lines[j]
            if s.strip() == "":
                j += 1
                continue
            if (len(s) - len(s.lstrip())) == 0:
                break
            last_content = j + 1
            j += 1
        return i, last_content, ""
    return None


def render_experiment_block(exp):
    return ["experiment:",
            "  status: %s" % exp["status"],
            "  exp_id: %s" % json.dumps(exp["exp_id"], ensure_ascii=False),
            "  note: %s" % json.dumps(exp["note"], ensure_ascii=False)]


def apply_experiment_edit(path, target):
    """幂等改写条目 experiment 块（flow/块两种形态都认）；写后自校验，异样即还原。"""
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    found = find_experiment_block(lines)
    if not found:
        raise RuntimeError("未找到顶层 experiment 键: %s" % path)
    i, j, rest = found
    if rest:
        cur = yaml.safe_load("experiment: " + rest)["experiment"]
    else:
        cur = yaml.safe_load("\n".join(lines[i:j]))["experiment"]
    if cur == target:
        return {"changed": False, "current": cur}
    before = yaml.safe_load(text)
    new_lines = lines[:i] + render_experiment_block(target) + lines[j:]
    new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    after = yaml.safe_load(new_text)
    if after.get("experiment") != target or {k: v for k, v in after.items() if k != "experiment"} \
            != {k: v for k, v in before.items() if k != "experiment"}:
        with open(path, "w", encoding="utf-8") as f:      # 自校验失败 → 还原
            f.write(text)
        raise RuntimeError("experiment 改写自校验失败（已还原）: %s" % path)
    return {"changed": True, "previous": cur}


def render_entry_yaml(d):
    """按 strategies/README.md G4 契约渲染条目（九钉死字段+三态条件字段）。

    未知/缺失的三态组合不在此预判——照实渲染（dsl_state 行+存在的条件字段），
    由 ci/strategies_check.py R1 裁决红绿（守护只编排不预判；绝不 KeyError）。
    """
    state = d.get("dsl_state")
    L = ["id: %s" % d["id"],
         "name: %s" % json.dumps(d["name"], ensure_ascii=False),
         "tier: %s" % d["tier"],
         "claim: %s" % json.dumps(d["claim"], ensure_ascii=False),
         "claimed_value:",
         "  metric: %s" % json.dumps(d["claimed_value"]["metric"], ensure_ascii=False),
         "  direction: %s" % d["claimed_value"]["direction"],
         "  context: %s" % json.dumps(d["claimed_value"]["context"], ensure_ascii=False),
         "sources: [%s]" % ", ".join(json.dumps(s, ensure_ascii=False) for s in d["sources"]),
         "consensus: {corpora: %s, cards: %s}" % (d["consensus"]["corpora"], d["consensus"]["cards"]),
         "experiment: {status: %s, exp_id: %s, note: %s}" % (
             d["experiment"]["status"],
             json.dumps(d["experiment"]["exp_id"], ensure_ascii=False),
             json.dumps(d["experiment"]["note"], ensure_ascii=False)),
         "dsl_state: %s" % state]
    if state == "compilable" and d.get("dsl_snippet"):
        L.append("dsl_snippet: |")
        L += ["  " + s for s in d["dsl_snippet"].splitlines()]
    elif state == "needs_syntax" and d.get("needs_syntax_note"):
        L.append("needs_syntax_note: %s" % json.dumps(d["needs_syntax_note"], ensure_ascii=False))
    elif state == "not_applicable" and d.get("na_reason"):
        L.append("na_reason: %s" % json.dumps(d["na_reason"], ensure_ascii=False))
    return "\n".join(L) + "\n"


def update_index_file(index_path, new_entry):
    """并集登记簿：entries 按 rank 有序插一条 + 重算 counts 块（最小 diff，不动既有行）。

    幂等：new_entry.id 已登记则只重算 counts（dsl_state 翻转场景）、不重复插行。
    """
    text = open(index_path, encoding="utf-8").read()
    lines = text.splitlines()
    idx = yaml.safe_load(text)
    entries = list(idx.get("entries") or [])
    already = any(e.get("id") == new_entry["id"] for e in entries)
    if not already:
        entries.append(new_entry)
    tiers, states = {}, {}
    for e in entries:
        tiers[e.get("tier")] = tiers.get(e.get("tier"), 0) + 1
        states[e.get("dsl_state")] = states.get(e.get("dsl_state"), 0) + 1
    line = "  - { id: %s, file: %s, tier: %s, topic: %s, dsl_state: %s, rank: %s }" % (
        new_entry["id"], new_entry["file"], new_entry["tier"],
        json.dumps(new_entry.get("topic") or "", ensure_ascii=False),
        new_entry["dsl_state"], new_entry.get("rank"))
    # v1.3.2：tiers/dsl_states 按出现键输出（闭集序 A,B,C,D / 三态序）——原实现
    # 硬编码 {A,B}，v1.2 契约扩 C/D 后自动建条目导致 counts 缺非零键 'C'（R3 红，
    # 2026-10-31 09:25 轮实证）。无 C/D 条目时输出与旧格式逐字兼容（A/B 基线不变）。
    def _fmt_counts(d, order):
        keys = [k for k in order if d.get(k)] + \
            sorted(k for k in d if d.get(k) and k not in order)
        return "{ " + ", ".join("%s: %d" % (k, d[k]) for k in keys) + " }"
    counts = ["counts:", "  total: %d" % len(entries),
              "  tiers: " + _fmt_counts(tiers, ["A", "B", "C", "D"]),
              "  dsl_states: " + _fmt_counts(
                  states, ["compilable", "needs_syntax", "not_applicable"])]

    def _rank(ln):
        m = re.search(r"rank:\s*(\d+)", ln)
        return int(m.group(1)) if m else 10 ** 9

    new_lines = list(lines)
    if not already:
        # entries 块边界
        ent_start = ent_end = None
        for i, ln in enumerate(lines):
            if re.match(r"^entries:\s*$", ln):
                ent_start = i
                continue
            if ent_start is not None and ent_end is None and ln.strip() \
                    and not ln.startswith("  - {"):
                ent_end = i
        if ent_start is None:
            raise RuntimeError("index.yaml 无 entries: 键: %s" % index_path)
        if ent_end is None:
            ent_end = len(lines)
        try:
            new_rank = int(new_entry.get("rank"))
        except (TypeError, ValueError):
            new_rank = 10 ** 9
        pos = ent_end
        for i in range(ent_start + 1, ent_end):
            if _rank(lines[i]) > new_rank:
                pos = i
                break
        new_lines = lines[:pos] + [line] + lines[pos:]
    # 重算 counts 块（吞旧块其余行；非 entries 行不受影响）
    out, replaced = [], False
    for ln in new_lines:
        if not replaced and ln.startswith("counts:"):
            out.extend(counts)
            replaced = True
            continue
        if replaced and re.match(r"^\s{2,}\S", ln) and not ln.startswith("  - {"):
            continue
        out.append(ln)
    if not replaced:
        out.append("")
        out.extend(counts)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + ("\n" if text.endswith("\n") else ""))


def ensure_writeback_tree():
    """确保 af 仓 sil-writeback 工作树在场（base=phase2 tip=strategies/ 正本所在）。

    DRY 守卫（复核判据5 修复）：DRY 绝不创建 worktree/分支（git 突变面）。"""
    if DRY:
        raise RuntimeError("DRY 模式不创建回写工作树（writeback_round 应在 DRY 下提前返回）")
    wt = CFG["wb_wt"]
    if os.path.isfile(os.path.join(wt, ".git")) and os.path.isdir(os.path.join(wt, "strategies")):
        return wt
    r = sh(["git", "-C", CFG["af"], "rev-parse", "--verify", "--quiet", CFG["wb_branch"]],
           timeout=TMO["git"])
    if r.returncode == 0:
        cmd = ["git", "-C", CFG["af"], "worktree", "add", wt, CFG["wb_branch"]]
    else:
        cmd = ["git", "-C", CFG["af"], "worktree", "add", "-b", CFG["wb_branch"], wt, CFG["wb_base"]]
    r = sh(cmd, timeout=TMO["git"])
    if r.returncode != 0:
        raise RuntimeError("worktree add 失败: %s" % (r.stderr or r.stdout)[-300:])
    if not os.path.isdir(os.path.join(wt, "strategies")):
        raise RuntimeError("工作树内 strategies/ 缺席: %s" % wt)
    return wt


def run_checker(wt):
    """ci/strategies_check.py 全量门（R1/R2/R3/R4；R4=cargo 装载测试，热缓存秒级）。"""
    env = {"CARGO_TARGET_DIR": CFG["wb_cargo_target"]}
    r = sh([sys.executable, "-B", "ci/strategies_check.py"], timeout=TMO["checker"],
           cwd=wt, env_extra=env)
    tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:])
    return r.returncode, tail


def git_commit(wt, paths, msg):
    """提交**本轮回写面**（只提交本轮 paths；绝不夹带 index 里他者已 staged 的改动）。

    20261103 红队 SIL 环修复（账实不符面）：原实现 `git add -- <paths>` 只加本轮
    路径，但 `git commit -m msg` **不带 paths** —— git 语义是提交**整个 index**，
    于是工作树内他人（并发 agent）已 staged 的改动被一并夹带进这个「回写 commit」：
    commit message（「回写 N 项（checker 全绿 exit 0）」）与 verdict_log 的
    「已回写 commit=<hash>」均宣称与实际内容不符，且夹带件从未过 checker
    （checker 只校验 strategies/）。失败路径反而是克制的（scoped reset 只动本轮
    paths，不碰他者 staged 面）——成功/失败两路的提交范围不对称。

    修法（最小面三处）：
    ① 无差异判据只看本轮 paths：整树 status 会因他者的脏面误判「有差异」，
       本轮无差异时本应幂等跳过（否则把别人的改动提交出去）。
    ② 提交只带本轮变更文件（git 部分提交语义）：本轮 paths 的已暂存差异清单
       = 提交面，用它作 pathspec → 他者已 staged 的改动留在 index、不入本次
       提交；成功/失败两路的提交范围对称。
    ③ 落库后核对提交面（账实相符）：commit 内文件集必须恰为提交面清单，不符
       则如实报失败（不得让 verdict_log 的「已回写 commit=<hash>」指向范围
       不符的提交）。"""
    paths = list(dict.fromkeys([p for p in (paths or []) if p]))
    if not paths:
        return None
    add = sh(["git", "-C", wt, "add", "--"] + paths, timeout=TMO["git"])
    if add.returncode != 0:
        raise RuntimeError("git add 失败: %s" % (add.stderr or "")[-200:])
    st = sh(["git", "-C", wt, "status", "--porcelain", "--"] + paths, timeout=TMO["git"])
    if st.returncode != 0:
        raise RuntimeError("git status 失败: %s" % (st.stderr or "")[-200:])
    if not (st.stdout or "").strip():
        return None                                    # 本轮回写面无差异（全幂等跳过）
    # 提交面清单＝本轮 paths 的已暂存差异（相对 HEAD）：只用它作 pathspec，
    # 他者（并发 agent）已 staged 的改动不在其中 → 不会被本次 commit 带走。
    df = sh(["git", "-C", wt, "-c", "core.quotepath=false", "diff", "--cached",
             "--name-only", "-M", "--"] + paths, timeout=TMO["git"])
    if df.returncode != 0:
        raise RuntimeError("git diff --cached 失败: %s" % (df.stderr or "")[-200:])
    want = sorted({ln.strip() for ln in (df.stdout or "").splitlines() if ln.strip()})
    if not want:
        return None                                    # 本轮无实质差异（全幂等跳过）
    pre = sh(["git", "-C", wt, "rev-parse", "HEAD"], timeout=TMO["git"])
    c = sh(["git", "-C", wt, "commit", "-m", msg, "--"] + want, timeout=TMO["git"])
    if c.returncode != 0:
        post = sh(["git", "-C", wt, "rev-parse", "HEAD"], timeout=TMO["git"])
        _pre, _post = (pre.stdout or "").strip(), (post.stdout or "").strip()
        if _post and _post != _pre:
            h = _post                     # post-commit 钩子失败但 commit 已落 → 如实按已落库
        else:
            # commit 未落：add 已写入的 index 登记必须撤销。否则 rollback_edits 对 staged
            # 新件 ls-files --error-unmatch 误判 tracked → checkout 只还原到 index 态 →
            # 残留件+登记行留场，随下一轮 add/commit 静默入库（verdict_log 记「未落条已
            # 寄存」而账实分离；20261102 红队 SIL 环）。scoped reset 只动本轮 paths，
            # 不碰他者（并发 agent）staged 面；reset 只还原 index 不触工作树。
            rs = sh(["git", "-C", wt, "reset", "-q", "--"] + paths, timeout=TMO["git"])
            if rs.returncode != 0:
                raise RuntimeError("git commit 失败且 staging 撤销失败（index 残留，回滚将不净）"
                                   ": commit: %s | reset: %s"
                                   % ((c.stderr or "")[-150:], (rs.stderr or "")[-150:]))
            raise RuntimeError("git commit 失败: %s" % (c.stderr or "")[-300:])
    else:
        _h = sh(["git", "-C", wt, "rev-parse", "--short", "HEAD"], timeout=TMO["git"])
        h = (_h.stdout or "").strip()
    # 落库后核对提交面（账实相符）：相对 commit 前的 HEAD，新提交只应改动本轮
    # 回写面——用两棵树对比（不依赖 commit 的父：钩子 amend 落库时父会变，
    # 按父对比会把被 amend 掉的上一提交也算进来 → 误判范围不符）
    _pre_sha = (pre.stdout or "").strip()
    got = sh(["git", "-C", wt, "-c", "core.quotepath=false", "diff", "--name-only",
              "-M", _pre_sha, "HEAD"], timeout=TMO["git"])
    got_set = sorted({ln.strip() for ln in (got.stdout or "").splitlines() if ln.strip()})
    if got_set != want:
        raise RuntimeError("回写 commit 范围与本轮回写面不符（账实不符，不得落 verdict_log）："
                           "commit=%s 期望=%s 实际=%s" % (h, want, got_set))
    return h


def rollback_edits(wt, touched_tracked, created):
    """回滚：未跟踪新件显式 unlink；tracked 文件（改动的+误跟踪的新件）走 git checkout。
    路径均相对工作树根（join wt）；返回**本轮回写面**是否已还原干净。
    越出工作树的路径（git checkout 管不到、status --porcelain 也看不见 → 静默
    失配）与 checkout 失败 → 如实返回 False，不谎报 clean=True（写盘面已由
    ENTRY_ID_RE 拦逃逸路径，此为纵深防御；红队 SIL 环修复）。
    净判据只看本轮回写面，不看整树 status：工作树常驻脏（轮1 ci/* 直改未提交、
    *.bak 未跟踪）与本环回写无关，整树判净使 clean 位与还原成败永久脱钩——
    恒 clean=False 底噪，真还原失败反而无从浮现（红队 E15②，20261101 修复）。
    restore 走 scoped status（staged 残差=checkout 只还原到 index 态，与
    unstaged 残差同为还原失败）；removed 新件直接查存在性（gitignored 也逃不掉，
    OSError 被吞的 unlink 失败同此暴露）；status 本身失败按无法证净如实 False。"""
    wt_real = os.path.realpath(wt)

    def _in_wt(p):
        rp = os.path.realpath(os.path.join(wt, p))
        return rp == wt_real or rp.startswith(wt_real + os.sep)

    restore, outside, removed = [], [], []
    for p in touched_tracked:
        (restore if _in_wt(p) else outside).append(p)
    for p in created:
        if not _in_wt(p):
            outside.append(p)                          # 仓库外新件不越权 unlink，如实报不净
            continue
        tracked = sh(["git", "-C", wt, "ls-files", "--error-unmatch", p], timeout=TMO["git"])
        if tracked.returncode == 0:
            restore.append(p)                          # 已跟踪（极少见：件在登记时已入库）
        else:
            removed.append(p)
            try:
                os.unlink(os.path.join(wt, p))
            except OSError:
                pass
    if restore:
        co = sh(["git", "-C", wt, "checkout", "--"] + sorted(set(restore)), timeout=TMO["git"])
        if co.returncode != 0:
            return False                               # 还原失败 → 如实报不干净
    if outside:
        return False                                   # 仓库外改动 git/status 双盲，无法证净
    for p in set(removed):
        if os.path.lexists(os.path.join(wt, p)):
            return False                               # unlink 失败残留 → 如实报不干净
    if restore:
        dirty = sh(["git", "-C", wt, "status", "--porcelain", "--"] + sorted(set(restore)),
                   timeout=TMO["git"])
        if dirty is None or (dirty.stdout or "").strip():
            return False                               # status 失败=无法证净；残差=还原失败
        return True
    return True                                        # 本轮无可证不净的写面 → 已净


def _dequeue(st, plan, outcome, force=False):
    """出队helper：仅无 writeback_error 的项出队（失败项留队下轮重试）。

    force=True（自动初建失败出队）：同轮出队防抖环（确定性违约不得每轮重复
    建条目→红→回滚），但**不再永久丢弃**——调用方随即 _park_writeback_failed 寄存
    auto_create_retry，回写面环境键变化后 _reenqueue_parked_auto_creates 自动
    重入队（v1.3.3）。原 attempt-once「同输入重试必得同结果」前提被
    2026-10-31 同窗事实推翻：st-C103 同输入 09:15 旧 checker 红/09:25 守护
    index 计数缺陷红/09:30 修复后绿 commit a0418ef——红绿由回写面环境版本
    决定，不由条目输入决定；st-C122/EXP-1 曾因旧语义被永久丢弃。
    v1.3.4：更新/投影失败项同样 force 出队寄存（不再留队每轮无条件重试——
    键不变不重试对全回写面成立，抖环实证见 _park_writeback_failed docstring）。
    v1.3.4 不变量：writeback_error 只标「当轮失败」——编辑成功的项由
    writeback_round 即时剥离旧错，红轮残留错不得钉死后续绿轮的出队
    （2026-11-01 实证：残留错使绿轮 commit 落库而项永驻队列、verdict_log
    永缺「已回写」outcome，队列永不排干）。"""
    for kind, item, _ in plan:
        if item.get("writeback_error") and not force:
            continue
        if kind == "verdict":
            st["verdict_queue"] = [v for v in st["verdict_queue"] if v is not item]
            st.setdefault("verdict_log", []).append(dict(item, outcome=outcome))
        else:
            st["projection_todos"] = [t for t in st["projection_todos"] if t is not item]
            st.setdefault("projection_log", []).append(dict(item, outcome=outcome))


def build_auto_entry(item):
    """v1.1 补丁②：裁决目标簇无库条目 → 按 G4 契约渲染初建条目 dict。

    照实字段：id（簇命名空间）、tier（簇档位照实标）、claim（册内断言原文）、
    name/sources/consensus（册内材料）。显式占位：claimed_value 三维策略册无
    对应字段（B1），metric/context 标'待投影'，direction 取 R1 闭集 up|down
    的占位值（**非判读结论**，note 明示）；dsl_state=needs_syntax + note
    '待投影'（dsl_snippet 需 AFB 语义级撰写，守护不臆造）；experiment 填终裁。
    红绿由 ci/strategies_check.py 裁决（守护不预判）。
    """
    mat = item.get("entry_material") or {}
    tier = item.get("target_tier")
    return {
        "id": item["target_entry_id"],
        "name": mat.get("name") or item.get("target_cluster"),
        "tier": tier,
        "claim": mat.get("claim") or "-",
        "claimed_value": {
            "metric": "（待投影：策略册无 metric 字段）",
            "direction": "down",     # R1 闭集占位（up|down 二选一不可避免）；非判读
            "context": ("（待投影：claimed_value 三维待投影补齐；direction 为 R1 闭集"
                        "占位、非判读结论——见 needs_syntax_note）"),
        },
        "sources": mat.get("sources") or ["-"],
        "consensus": {"corpora": mat.get("corpora") or 1, "cards": mat.get("cards") or 1},
        "experiment": {"status": item["status"], "exp_id": item.get("exp_id") or "-",
                       "note": item.get("note") or "-"},
        "dsl_state": "needs_syntax",
        "needs_syntax_note": (
            "待投影：本条目由循环产线守护按 G4 契约自动初建（tier 照实=%s、claim 取"
            "册内断言、experiment 填终裁 %s/%s）。claimed_value{metric,direction,"
            "context} 策略册无对应字段（direction 为 R1 闭集占位、非判读结论）；"
            "dsl_snippet 需 AFB 语义级撰写——投影补齐走既有待办路径"
            "（loop-state projection_todos），补前本条目不参与任何判读引用。" % (
                tier, item.get("exp_id"), item.get("verdict"))),
    }


def _queue_projection_todo(st, item):
    """自动建条目 commit 成功后，排队投影待办（补齐 claimed_value/dsl_snippet）。"""
    mat = item.get("entry_material") or {}
    st.setdefault("projection_todos", []).append({
        "cluster_id": item.get("target_cluster"), "entry_id": item["target_entry_id"],
        "tier": item.get("target_tier"), "rank": item.get("target_rank"),
        "topic": mat.get("topic"), "name": mat.get("name"), "claim": mat.get("claim"),
        "sources": mat.get("sources") or [],
        "consensus": {"corpora": mat.get("corpora"), "cards": mat.get("cards")},
        "change_kind": "auto-created",
        "status": "pending_projection",
        "blocked_reason": ("守护自动初建条目已 commit（needs_syntax+待投影）；claimed_value"
                           "{metric,direction,context} 与 dsl_snippet 需语义级投影——待主代理/"
                           "后续自动化补 entry_draft 后由④同机制补齐"),
        "material": {
            "representative_id": mat.get("representative_id"),
            "citation_density": mat.get("citation_density"),
            "empirical_question": mat.get("empirical_question"),
            "confirm_line": mat.get("confirm_line"),
            "refute_line": mat.get("refute_line"),
        },
        "entry_draft": None,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    st["projection_todos"] = st["projection_todos"][-200:]


def _wb_env_key(wt=None):
    """v1.3.3 回写面环境版本键：worktree 内 checker 脚本内容 sha + 本守护源码 sha
    + worktree HEAD。

    自动初建条目的红绿由此三者代表的环境决定（2026-10-31 实证：st-C103 同一条目
    输入 09:15 旧 checker 红/09:25 守护 index 计数缺陷红/09:30 两者修复后绿；
    2026-11-01 17:03 再证：checker 红由共享 target 溯源脏+他代理在修 ci/ 所致，
    与条目输入无关）——故重试资格挂在环境版本上：键不变不重试（防确定性违约
    抖环；v1.3.4 起对全回写面成立——更新/投影失败项同寄存，此前仅自动初建
    挂键、更新路径留队每轮重试成抖环），键变化（门修/守护修/分支有新
    commit——环境已被证明可绿可写）后失败裁决必得重试。"""
    parts = []
    cp = os.path.join(wt or "", "ci", "strategies_check.py")
    if wt and os.path.isfile(cp):
        try:
            parts.append(sha256_text(open(cp, encoding="utf-8").read()))
        except OSError:
            pass
    try:
        parts.append(sha256_text(open(os.path.abspath(__file__), encoding="utf-8").read()))
    except OSError:
        pass
    if wt:
        r = sh(["git", "-C", wt, "rev-parse", "--short", "HEAD"], timeout=TMO["git"])
        if r is not None and r.returncode == 0:
            parts.append((r.stdout or "").strip())
    return sha256_text("|".join(parts))


def _park_writeback_failed(st, items, why, kind="verdict"):
    """v1.3.4：回写失败项寄存（attempt-once 的替代语义：每回写面环境版本一次）。

    v1.3.3 只寄存自动初建失败项；v1.3.4 起覆盖全部回写失败项（自动初建+更新/
    投影——「键不变不重试」防抖原则对全回写面成立。2026-11-01 实证更新路径曾
    留队每轮无条件重试：持续红环境 st-C103/EXP-2 每 600s 一次编辑→checker→
    回滚抖环，rollbacks 25→42 无界增长）。条目内容原样寄存（裁决/材料+终裁，
    落条时确定性重现）；writeback_error 只留 verdict_log（寄存件不带失败残留）。
    kind 记录原属队列（verdict/projection），键变化后由 _reenqueue_parked_auto_creates
    按原队列重入队；环境不变保持寄存（防抖环）。"""
    key = _wb_env_key(CFG["wb_wt"])
    park = st.setdefault("auto_create_retry", [])
    for it in items:
        park.append({"item": {k: v for k, v in it.items() if k != "writeback_error"},
                     "kind": kind, "env_key": key, "why": why,
                     "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    st["auto_create_retry"] = park[-50:]
    log("④回写失败项寄存 %d 项（kind=%s；回写面环境键 %s…；键变化后自动重入队，不永久丢弃；原因：%s）"
        % (len(items), kind, key[:12], why))


def _reenqueue_parked_auto_creates(st):
    """v1.3.3/v1.3.4：回写失败寄存件的**再入队路径**（每轮跑，DRY 跳过）。

    两条来源，均幂等：
    (a) 寄存区 auto_create_retry：env_key ≠ 当前回写面环境键（checker/守护升级）
        → 按寄存时 kind 重入队（v1.3.4：verdict→裁决队列、projection→投影队列；
        旧寄存件无 kind 一律按裁决队列，兼容 v1.3.3 存量）并移出寄存区
        （④若再红按新键重寄存）；
    (b) 一次性恢复：verdict_log 里 outcome 以「自动建条目尝试 1 次即止」开头
        （v1.3.3 前旧语义永久丢弃的裁决，如 2026-10-31 st-C122/EXP-1）且条目
        文件仍缺席 → 重建队列项重入队；verdict_log 原条目只加 requeued_ts 标记
        （失败史不抹改）防重；条目已在场的历史失败只标记 requeue_note（裁决
        已如实在库，不重排队）。**v1.3.12：只复活带守护封条（③段签发）的日志条目**
        ——日志条目须自证为守护自产件，否则拒（留痕不静默丢弃）；注入/篡改的日志
        条目不得借本路径进入裁决队列（2026-11-03 红队确证：注入 verdict_log →
        本路径搬进 verdict_queue → 非终裁态零证据要求 → 伪条目经真 checker 全绿
        写进 strategies/ 正本并 commit）。
    返回重入队项数。"""
    if DRY:
        return 0
    q = st.setdefault("verdict_queue", [])
    n = 0
    cur = _wb_env_key(CFG["wb_wt"])
    keep = []
    for rec in (st.get("auto_create_retry") or []):
        if (rec.get("env_key") or "") != cur:
            it = dict(rec.get("item") or {})
            it.pop("outcome", None)
            it["requeue_of"] = rec.get("ts")
            if rec.get("kind") == "projection":        # v1.3.4：投影失败项回投影队列
                st.setdefault("projection_todos", []).append(it)
            else:                                      # 无 kind=v1.3.3 旧寄存件→裁决队列
                q.append(it)
            n += 1
            log("③④寄存重入队：%s（%s/%s；寄存时 %s，回写面环境键 %s…→%s…）" % (
                it.get("target_entry_id") or it.get("target_entry"), it.get("exp_id"),
                it.get("verdict"), rec.get("ts"), (rec.get("env_key") or "")[:12], cur[:12]))
        else:
            keep.append(rec)
    st["auto_create_retry"] = keep
    sdir = resolve_strategies_dir()
    for v in (st.get("verdict_log") or []):
        if v.get("requeued_ts") or v.get("requeue_rejected"):
            continue
        if not (v.get("outcome") or "").startswith("自动建条目尝试 1 次即止"):
            continue
        eid = v.get("target_entry_id") or v.get("target_entry")
        if not eid:
            continue
        # v1.3.12（纵深防御·复制点自证来源）：只复活**守护自己签发过**的日志条目——
        # ③段签发的守护封条 evidence.verdict_seal（HMAC，攻击者不可自算）验签不过
        # 者即拒（留痕留条目，不静默丢弃、不改失败史）。为什么复制点还要自证：路径(b)
        # 在 load_state 验签**之后**运行，且日志条目会被守护在轮内再标记（requeued_ts
        # 等不进封条载荷）——复制点不能只靠「上游验过签」这一句。v1.3.12 已把
        # verdict_log 纳入状态面封条（面级），此腿是点级（纵深）：即便将来覆盖面
        # 被放宽，复制点自身仍只信守护自产件。
        # 影响面（如实）：v1.3.9 之前签发的旧件无封条 → 旧语义一次性恢复路径对
        # **无封条旧件**不再复活（生产现状：旧件已全部带 requeued_ts 标记，无存量
        # 待恢复项；v1.3.4 起的失败项走 auto_create_retry 寄存路径，不经本腿）。
        ok_seal, why_seal = verdict_seal_check(v)
        if not ok_seal:
            v["requeue_rejected"] = why_seal
            log("③④[拒] 历史丢弃裁决恢复重入队：%s（%s）——%s（疑 loop-state 被注入/"
                "篡改，不入裁决队列、不落盘）" % (eid, v.get("exp_id"), why_seal))
            continue
        v["requeued_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if sdir and os.path.isfile(os.path.join(sdir, eid + ".yaml")):
            v["requeue_note"] = "条目已在场（裁决已如实在库），不重排队"
            continue
        it = {k: v[k] for k in v if k not in ("outcome", "writeback_error",
                                              "requeued_ts", "requeue_note")}
        it["requeue_of"] = v.get("ts")
        q.append(it)
        n += 1
        log("③④历史丢弃裁决恢复重入队：%s（%s/%s，原尝试 %s；条目仍缺席→重试落条）" % (
            eid, it.get("exp_id"), it.get("verdict"), v.get("ts")))
    return n


def writeback_round(st, cons):
    """裁决队列 → experiment 字段回写（条目在场）或**自动建条目**（v1.1：条目缺席，
    含 tier C/D）；投影待办（带齐 entry_draft）→ 新条目。checker 全绿才 commit。

    DRY 守卫（复核判据5 修复）：DRY 只登记将回写什么，绝不建工作树/不编辑/不跑
    checker/不 commit——writeback_round 是全件唯一 git 突变面，守卫放函数入口
    （不依赖调用方），返回 dry-run 计划供审阅。"""
    sdir_wt = os.path.join(CFG["wb_wt"], "strategies")
    plan = []                                          # (kind, item, entry_path)
    for v in st.get("verdict_queue", []):
        eid = v.get("target_entry_id") or v.get("target_entry")
        if not eid:
            continue
        if not ENTRY_ID_RE.match(eid):
            # 命名空间门：id 带 / 或 .. 时 join 会逃逸工作树写任意路径（写盘在
            # checker 之前，checker 兜不了）——落盘前拦截，项留队带 writeback_error
            v["writeback_error"] = ("target_entry_id 非法（须匹配 ^st-(b-)?C[0-9]+$，"
                                    "疑 loop-state 被篡改/损坏，已拒落盘）：%r" % (eid,))
            log("④[拒] 非法 entry_id %r：不入回写计划，项留队带 writeback_error" % (eid,))
            continue
        bad_ev = verdict_evidence_gate(v)
        if bad_ev:
            # v1.3.7（RT-E12③ checker 侧）：终裁证据门（见 verdict_evidence_gate）——
            # 零证据伪 confirmed 不得经 checker 全绿直通 commit（2026-11-02 沙盒
            # 实证 de65bcf 的修复面）；拒法与命名空间门同构：不入计划、留队留痕
            v["writeback_error"] = ("终裁证据校验未过（RT-E12③ checker 侧，疑 loop-state "
                                    "被篡改/损坏，已拒落盘）：" + bad_ev)
            log("④[拒] %s 终裁证据校验未过：不入回写计划，项留队带 writeback_error"
                % (eid,))
            continue
        plan.append(("verdict", v, os.path.join(sdir_wt, eid + ".yaml")))
    for t in st.get("projection_todos", []):
        if t.get("entry_draft"):
            if not ENTRY_ID_RE.match(t.get("entry_id") or ""):
                t["writeback_error"] = ("entry_id 非法（须匹配 ^st-(b-)?C[0-9]+$，"
                                        "疑 loop-state 被篡改/损坏，已拒落盘）：%r"
                                        % (t.get("entry_id"),))
                log("④[拒] 非法 entry_id %r：不入回写计划，项留队带 writeback_error"
                    % (t.get("entry_id"),))
                continue
            # v1.3.9（RT-E12③ 加固）：投影面不得写终裁态——confirmed/refuted 只能
            # 经③段终裁（证据三锚+守护封条）落库；投影待办是「补 claimed_value/
            # dsl_snippet」通道，携终裁态的草稿=绕过证据门的伪终裁注入面（loop-state
            # 被篡改即得，与裁决队列注入同族）。拒法与命名空间门同构：不入回写计划、
            # 留队带 writeback_error（不静默丢弃）。
            _pd = t.get("entry_draft") if isinstance(t.get("entry_draft"), dict) else {}
            _pex = _pd.get("experiment") if isinstance(_pd.get("experiment"), dict) else {}
            if str(_pex.get("status") or "") in ("confirmed", "refuted"):
                t["writeback_error"] = ("投影草稿携终裁态 experiment.status=%r——终裁只能"
                                        "经③段终裁证据门（三锚+守护封条）落库，投影面拒写"
                                        "（疑 loop-state 被篡改/注入）"
                                        % (_pex.get("status"),))
                log("④[拒] 投影草稿携终裁态 %s：不入回写计划，项留队带 writeback_error"
                    % (_pex.get("status"),))
                continue
            plan.append(("projection", t, os.path.join(sdir_wt, t["entry_id"] + ".yaml")))
    if not plan:
        return {"status": "empty", "commits": []}
    if DRY:
        # 队列非空但 DRY：只报计划（不碰 git/不建工作树/不跑 checker）
        log("④[DRY] 回写计划 %d 项（不执行）：%s" % (
            len(plan), "；".join("%s %s" % (k, (it.get("target_entry_id") or it.get("target_entry")
                                                or it.get("entry_id"))) for k, it, _ in plan)))
        return {"status": "dry-run", "commits": [],
                "plan": [{"kind": k, "entry": it.get("target_entry_id") or it.get("target_entry")
                          or it.get("entry_id")} for k, it, _ in plan]}
    wt = ensure_writeback_tree()
    log("④回写工作树就绪: %s（分支 %s）" % (wt, CFG["wb_branch"]))

    edits, touched, created = [], [], []
    auto_created = []                                   # v1.1：本论自动初建的条目 item
    # v1.3.4：编辑成功（含幂等改写/幂等跳过/初建落盘）即剥离历史 writeback_error
    # 残留——否则 _dequeue 的「带错留队」守卫会把红轮残留错带进绿轮：commit 落库
    # 而项永不出队、verdict_log 永缺「已回写」outcome，队列永不排干（2026-11-01
    # 实证：st-C103 红转绿后永驻队列）。本轮编辑异常仍由 except 置新错留队，重试
    # 语义不变；checker 红/git 失败路径无条件全量置错，也不受剥离影响。
    for kind, item, epath in plan:
        try:
            if kind == "verdict":
                if not os.path.isfile(epath):
                    # v1.1 补丁②：条目缺席 → 自动建条目（tier 照实、claim 册内断言、
                    # experiment 填终裁、needs_syntax+待投影），红绿交 checker 裁决
                    d = build_auto_entry(item)
                    rel = os.path.relpath(epath, wt)
                    new_text = render_entry_yaml(d)
                    created.append(rel)                 # 先登记再落盘：异常时回滚也知有此件
                    with open(epath, "w", encoding="utf-8") as f:
                        f.write(new_text)
                    update_index_file(os.path.join(wt, "strategies", "index.yaml"),
                                      {"id": d["id"], "file": d["id"] + ".yaml", "tier": d["tier"],
                                       "topic": (item.get("entry_material") or {}).get("topic") or "",
                                       "dsl_state": d["dsl_state"], "rank": item.get("target_rank")})
                    touched.append("strategies/index.yaml")
                    auto_created.append(item)
                    edits.append({"kind": "verdict", "entry": d["id"], "exp_id": item.get("exp_id"),
                                  "changed": True, "action": "auto-create"})
                    log("④目标簇 %s（tier %s）无库条目 → 自动初建 %s（needs_syntax/待投影），"
                        "交 checker 裁决" % (item.get("target_cluster"), item.get("target_tier"), d["id"]))
                    item.pop("writeback_error", None)   # v1.3.4 剥离残留错（见上）
                    continue
                target = {"status": item["status"], "exp_id": item.get("exp_id") or "-",
                          "note": item.get("note") or "-"}
                res = apply_experiment_edit(epath, target)
                if res["changed"]:
                    touched.append(os.path.relpath(epath, wt))
                item.pop("writeback_error", None)       # v1.3.4 剥离残留错（见上）
                edits.append({"kind": "verdict", "entry": item.get("target_entry"),
                              "exp_id": item.get("exp_id"), "changed": res["changed"]})
            else:
                d = dict(item["entry_draft"])
                d.setdefault("id", item["entry_id"])
                d.setdefault("experiment", {"status": "none", "exp_id": "-", "note": "-"})
                rel = os.path.relpath(epath, wt)
                new_text = render_entry_yaml(d)
                old_text = open(epath, encoding="utf-8").read() if os.path.isfile(epath) else None
                if old_text == new_text:
                    edits.append({"kind": "projection", "entry": d["id"], "changed": False})
                    item.pop("writeback_error", None)  # v1.3.4 剥离残留错（见上）
                    continue                          # 已在场且字节一致 → 幂等跳过
                if old_text is None:
                    created.append(rel)                 # 先登记再落盘：异常时回滚也知有此件
                else:
                    touched.append(rel)
                with open(epath, "w", encoding="utf-8") as f:
                    f.write(new_text)
                update_index_file(os.path.join(wt, "strategies", "index.yaml"),
                                  {"id": d["id"], "file": d["id"] + ".yaml", "tier": d["tier"],
                                   "topic": item.get("topic") or "", "dsl_state": d["dsl_state"],
                                   "rank": item.get("rank")})
                touched.append("strategies/index.yaml")
                edits.append({"kind": "projection", "entry": d["id"], "changed": True})
                item.pop("writeback_error", None)       # v1.3.4 剥离残留错（见上）
        except Exception as e:
            item["writeback_error"] = str(e)[:300]
            log("④编辑失败（记下继续）: %s %s" % (item.get("entry_id") or item.get("target_entry_id")
                                                 or item.get("target_entry"), e))

    changed_paths = sorted(set(touched + created))
    if not changed_paths:
        _dequeue(st, plan, "已回写（幂等跳过，无新 commit）")
        return {"status": "idempotent-noop", "commits": [], "edits": edits}

    rc, tail = run_checker(wt)
    if rc != 0:
        ok = rollback_edits(wt, touched, created)
        for kind, item, _ in plan:
            item["writeback_error"] = "checker 红（exit=%s，已回滚 clean=%s）：%s" % (rc, ok, tail[-200:])
        # v1.3.3：自动初建失败不再永久丢弃——同轮出队防抖环，寄存 auto_create_retry
        # 待回写面环境键变化重入队（attempt-once 前提被 2026-10-31 同窗事实推翻：
        # st-C103 同输入两红一绿，红绿由 checker/守护版本决定）。
        # v1.3.4：更新/投影失败项同语义寄存（不再留队下轮无条件重试——「键不变
        # 不重试」原则对全回写面成立；2026-11-01 实证留队重试在持续红环境每 600s
        # 一次编辑→checker→回滚抖环，st-C103/EXP-2 rollbacks 25→42 无界增长）。
        failed = [p for p in plan if p[1].get("writeback_error")]
        if auto_created:
            _dequeue(st, [p for p in failed if p[1] in auto_created],
                     "自动建条目本轮未落条已寄存：checker 红 exit=%s 已回滚 clean=%s"
                     "（回写面环境键变化后自动重入队，不永久丢弃；缺口见 writeback_error 尾）"
                     % (rc, ok), force=True)
            _park_writeback_failed(st, auto_created, "checker 红 exit=%s" % rc, kind="verdict")
        others = [p for p in failed if p[1] not in auto_created]
        if others:
            _dequeue(st, others,
                     "回写失败本轮已寄存：checker 红 exit=%s 已回滚 clean=%s"
                     "（回写面环境键变化后自动重入队，不永久丢弃；详情见 writeback_error）"
                     % (rc, ok), force=True)
            for k in ("verdict", "projection"):
                grp = [it for kk, it, _ in others if kk == k]
                if grp:
                    _park_writeback_failed(st, grp, "checker 红 exit=%s" % rc, kind=k)
        changelog("SIL 回写失败回滚：checker 红 exit=%s（%d 处编辑已还原 clean=%s；失败项 %d 项寄存待回写面环境键变化重入队，防抖环不永久丢弃）" %
                  (rc, len(edits), ok, len(failed)))
        return {"status": "checker-red", "rc": rc, "rollback_clean": ok,
                "commits": [], "edits": edits, "tail": tail}
    msg = ("strategies(%s): 循环产线守护回写 %d 项（checker 全绿 exit 0）\n\n"
           "%s\n\n证据：ci/strategies_check.py exit 0（R1 schema/R2 index/R3 计数/R4 编译断言）；"
           "loop-state.json 轮次记录；不 push（本地分支 %s）。" % (
               CFG["wb_branch"],
               len(edits), "\n".join("  - %s %s %s" % (e["kind"], e.get("entry"), e.get("exp_id") or "")
                                     for e in edits), CFG["wb_branch"]))
    try:
        h = git_commit(wt, changed_paths, msg)
    except Exception as e:
        ok = rollback_edits(wt, touched, created)
        for kind, item, _ in plan:
            item["writeback_error"] = "git 失败（已回滚 clean=%s）：%s" % (ok, e)
        # v1.3.4：全失败项（自动初建+更新/投影）同轮出队寄存，键变化重入队（防抖环）
        failed = [p for p in plan if p[1].get("writeback_error")]
        if auto_created:
            _dequeue(st, [p for p in failed if p[1] in auto_created],
                     "自动建条目本轮未落条已寄存：git 失败已回滚 clean=%s"
                     "（回写面环境键变化后自动重入队，不永久丢弃）" % ok, force=True)
            _park_writeback_failed(st, auto_created, "git 失败已回滚 clean=%s" % ok, kind="verdict")
        others = [p for p in failed if p[1] not in auto_created]
        if others:
            _dequeue(st, others,
                     "回写失败本轮已寄存：git 失败已回滚 clean=%s"
                     "（回写面环境键变化后自动重入队，不永久丢弃；详情见 writeback_error）" % ok,
                     force=True)
            for k in ("verdict", "projection"):
                grp = [it for kk, it, _ in others if kk == k]
                if grp:
                    _park_writeback_failed(st, grp, "git 失败已回滚 clean=%s" % ok, kind=k)
        changelog("SIL 回写失败回滚：git 失败已还原 clean=%s（失败项 %d 项寄存待回写面环境键变化重入队，防抖环不永久丢弃）"
                  % (ok, len(failed)))
        return {"status": "git-failed", "rollback_clean": ok, "commits": [], "edits": edits}
    _dequeue(st, plan, "已回写 commit=%s" % (h or "无差异"))
    for item in auto_created:
        # v1.1：自动初建条目落条后，投影补齐走既有待办路径（B1 缺口照实排队）
        _queue_projection_todo(st, item)
    if h is None:
        return {"status": "nothing-to-commit", "commits": [], "edits": edits}
    changelog("SIL 回写 commit=%s（分支 %s）：%d 项——%s" % (
        h, CFG["wb_branch"], len(edits),
        "；".join("%s%s%s" % (e.get("entry"), ("=" + e["exp_id"]) if e.get("exp_id") else "",
                              "(自动初建)" if e.get("action") == "auto-create" else "")
                  for e in edits)))
    return {"status": "committed", "commit": h, "commits": [h], "edits": edits}


# ---------------------------------------------------------------- 状态/指标
def state_seal_payload(st):
    """状态面封条载荷 = 回写面四段（裁决队列/失败寄存/投影待办/**裁决日志**）规范化串。

    v1.3.12：补第四段 verdict_log——它是通往回写面的第四条来源（重入队路径(b)
    从日志复制条目进裁决队列），未封条即等于封条被绕过（2026-11-03 红队确证）。"""
    return _canonical_json({k: st.get(k) for k in STATE_SEAL_SECTIONS})


def state_seal(st):
    """状态面封条 = HMAC-SHA256(密钥, 回写面四段规范化串)（台账 RT-E86 拦截②
    「verdict_queue 段 HMAC 钉」——覆盖面扩到另两段：失败寄存是裁决重入队来源、
    投影待办是另一条回写面，三段同封一钉；v1.3.12 再扩第四段：裁决日志亦为重入队
    来源（路径(b)），四段同封一钉）。"""
    return _mirror_hmac(state_seal_payload(st))


def _bound_state_sections(st):
    """封条覆盖段的有界裁剪（**签发前**执行；口径与 load_state 读盘裁剪一致）。

    v1.3.12 起 verdict_log 在封条覆盖内：若段长在签发后才被裁掉（读盘裁剪），
    落盘件与验签时的内容就不一致 → 封条自伤（守护把自己的合法写盘判成篡改）。
    故签发前先定界：写盘件恒为「已定界」内容，读盘裁剪对其为幂等。"""
    for k, n in STATE_SECTION_BOUNDS.items():
        v = st.get(k)
        if isinstance(v, list) and len(v) > n:
            st[k] = v[-n:]
    return st


def seal_state(st):
    """签发状态面封条（save_state/心跳写盘前调用；幂等）。"""
    _bound_state_sections(st)                 # v1.3.12：签发前定界（封条覆盖段有界）
    st["state_seal"] = {"alg": "hmac-sha256", "sections": list(STATE_SEAL_SECTIONS),
                        "hmac": state_seal(st), "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    return st


def verify_state_seal(st):
    """状态面封条验签。返回 (trusted, reason)。"""
    seal = st.get("state_seal")
    if not isinstance(seal, dict) or not seal.get("hmac"):
        return False, "状态面无封条（state_seal 缺席——非守护签发/被抹/升级前旧件）"
    if list(seal.get("sections") or []) != list(STATE_SEAL_SECTIONS):
        return False, ("状态面封条覆盖面不匹配（%r ≠ %r）"
                       % (seal.get("sections"), list(STATE_SEAL_SECTIONS)))
    try:
        cur = state_seal(st)
    except SigningUnavailable:
        # RT-E85②（H2 修法(1)，P4-联评）：签名停摆世复算不可得——**与篡改分离**：
        # 专用 reason（load_state 据此「保留四段不清空」，probe ⑧a 据此 fail(2)
        # 不诬篡改，⑩ key_status 提供精确红）。原 except Exception 兜底会把停摆
        # 误报成「复算失败」并诱发四段隔离清空+⑧c sticky 自伤链（P4-H2）。
        return False, "签名停摆（复算不可得）——RT-E85② 钥源不可用，四段保留不消费"
    except Exception as e:
        return False, "状态面封条复算失败: %s" % e
    if not _seal_eq(seal.get("hmac"), cur):
        return False, ("状态面封条验签失败（%s 段内容与守护签发时不一致——疑 loop-state "
                       "被篡改/注入）" % "/".join(STATE_SEAL_SECTIONS))
    return True, "状态面封条验签通过"


def _quarantine_unverified_sections(st, reason):
    """封条验签失败 → 回写面四段隔离（fail-closed）：内容移出回写面（绝不进④），
    留痕 quarantine_log（计数+摘要 sha+留样至多 20 项/段）——不静默丢弃。

    v1.3.12：四段含 verdict_log——日志被注入/篡改即整段移出（否则守护下次写盘会
    给篡改后的日志**重新签发封条**，篡改件即被「洗白」成守护自产件；故日志与队列
    同口径：不可验即移出，留样+摘要入 quarantine_log 供取证）。"""
    ql = st.setdefault("quarantine_log", [])
    moved = 0
    for name in STATE_SEAL_SECTIONS:
        items = st.get(name) or []
        if not items:
            continue
        moved += len(items)
        try:
            dig = sha256_text(_canonical_json(items))[:32]
        except Exception:
            dig = "?"
        ql.append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "section": name,
                   "n": len(items), "digest": dig, "reason": reason,
                   "sample": items[:20]})                # 留样（至多 20 项/段）
        st[name] = []
    st["quarantine_log"] = ql[-20:]
    st["state_seal_ok"] = False
    log("RT-E12③ 状态面封条未过 → 回写面四段隔离 %d 项（fail-closed，不入④回写面）：%s"
        % (moved, reason))
    return moved


def _tighten_state_mode(path):
    """状态面落盘件权限收紧（v1.3.13）：**同组/他人可写的状态面＝改写面开着**。

    口径同 _mirror_signing_key（签名密钥 0600 收紧：已在位则校验并收紧过宽权限）：
    守护对自己写的状态面负责——落盘即 0600（atomic_write_json(mode=0o600)），
    读盘时若发现被改宽（他人 chmod 放宽）即收回并留痕（log）。收紧只动权限位，
    不动内容（内容面由封条验签 fail-closed 管，两面分工不重叠）。"""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return
    if mode & 0o022:                                     # 同组或他人可写
        try:
            os.chmod(path, 0o600)
            log("状态面权限 %o→0600 收紧（%s）——同组/他人可写面已闭" % (mode, path))
        except OSError as e:
            log("状态面权限收紧失败（%s：%s）" % (path, e))


def load_state():
    try:
        st = json.load(open(CFG["state"], encoding="utf-8"))
    except Exception:
        st = {}
    _tighten_state_mode(CFG["state"])                   # v1.3.13：权限面自愈
    st.setdefault("started_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    st.setdefault("rounds", 0)
    st.setdefault("baseline", None)                    # {verified,total,watermark,ts}
    st.setdefault("exp_mirror_sig", None)              # 兼容 v1：合并签名（exp1 口径遗留）
    st.setdefault("exp_mirror_sigs", {})               # v1.1：逐源签名 {exp1:…, exp2:…}
    st.setdefault("verdict_queue", [])
    st.setdefault("verdict_log", [])
    st.setdefault("auto_create_retry", [])             # v1.3.3：自动初建失败寄存（环境键变化重入队）
    st.setdefault("projection_todos", [])
    st.setdefault("projection_log", [])
    st.setdefault("experiment_candidates", [])
    st.setdefault("candidates_dispatched", [])
    st.setdefault("commits", [])
    st.setdefault("rollbacks", [])
    st.setdefault("counters", {"triggered": 0, "noop": 0, "candidates_queued": 0,
                               "verdicts_queued": 0, "commits": 0, "rollbacks": 0, "errors": 0})
    st.setdefault("last_round", {})
    for k in ("verdict_queue", "verdict_log", "projection_todos", "projection_log",
              "experiment_candidates", "commits", "rollbacks"):
        if len(st[k]) > 200:                           # 状态文件有界（防无界增长）
            st[k] = st[k][-200:]
    if len(st["auto_create_retry"]) > 50:              # v1.3.3：寄存区有界
        st["auto_create_retry"] = st["auto_create_retry"][-50:]
    # v1.3.12：封条覆盖段按**签发时同一上限**裁剪（签发前已定界，故此处对守护自产
    # 件为幂等；对外来超限件则使其与封条载荷口径一致——否则读盘裁剪会改内容、令
    # 封条自伤）。
    _bound_state_sections(st)
    # v1.3.9（台账 RT-E86 拦截②）：状态面封条验签——失败/缺席 → 回写面四段隔离
    # （fail-closed：注入/篡改的裁决队列项、失败寄存件、投影待办、**裁决日志**一律
    # 不进④；v1.3.12 补第四段 verdict_log——日志是重入队路径(b)的来源面，不封即
    # 等于封条可被绕过）。
    # 「拒用不拒启」：守护照跑①②⑤记账（不信任精确落在消费点，与镜像只读门同口径）。
    ok, why = verify_state_seal(st)
    st["state_seal_ok"] = ok
    if not ok:
        if "签名停摆" in why:
            # RT-E85②（H2 修法(2)，P4-联评）：停摆世读盘**不清四段**——内容原样
            # 保留（不消费也不销毁；隔离=销毁语义，恢复后旧数据已灭=自伤链）。
            # 红=state_seal_ok=False + key_status（probe ⑩ 精确红）；恢复=钥源可用
            # 后重启守护，fetch 成功复算旧封条+原四段通过 ⇒ 无缝解冻（消 ⑧c
            # sticky 诱发源）。「不消费」由冻结轮/③④消费点自然保证（无钥不可签
            # 不可验）。T18e6 负控钉住本语义。
            if why not in _SEAL_WARN:
                _SEAL_WARN[why] = True
                log("RT-E85② 停摆世读盘：%s——四段保留不消费不销毁（恢复后重启守护自动解冻）" % why)
        else:
            moved = _quarantine_unverified_sections(st, why)
            if moved:
                changelog("SIL 状态面封条未过 → 回写面四段隔离（RT-E12③ / 台账 RT-E86 "
                          "拦截②，fail-closed 不入回写面）：%s（隔离 %d 项）" % (why, moved))
            elif why not in _SEAL_WARN:
                _SEAL_WARN[why] = True
                log("RT-E12③ 状态面封条未过（%s）——回写面四段当前无可验内容（无隔离）" % why)
    return st


def save_state(st):
    if DRY:
        return
    try:
        st["daemon_src"] = daemon_src_stamp()     # v1.3.11：每次写盘登记在役源码版本钉
        try:
            seal_state(st)                             # v1.3.9：写盘即签发状态面封条
        except SigningUnavailable:
            # RT-E85②（K7 四段冻结，P1-设计 §2.3）：签名停摆轮**不重签封条**——
            # 四段由冻结轮（round_once）保证与上轮逐字一致 ⇒ 旧封条（st["state_seal"]
            # 原值）继续验签通过；冷启动无旧封条 → 置显式 unavailable 值（下轮
            # load_state 验签失败隔离=fail-closed，probe ⑧a/⑩ 红）。若四段仍被意外
            # 改动（编程错），旧封条失配 → 下轮验签隔离自证，不静默。
            # 绝不降级为「无封条写盘」，也绝不为写盘而自生成钥。
            st.setdefault("state_seal", {"alg": "hmac-sha256",
                                         "sections": list(STATE_SEAL_SECTIONS),
                                         "hmac": "signing-halted",
                                         "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        # RT-E85②（K8）：key_status **唯一写盘点**。probe ⑩ 同步点：sil-verdict-probe
        # 消费 st["key_status"]（source/state/fp16/err）——state 非 ok ⇒ rc=1 红
        # （停摆显式在册且有人订阅，台账:747 口径）。本段不进 STATE_SEAL_SECTIONS
        # 覆盖（覆盖面不变、只更严，P1-设计 §6）。
        st["key_status"] = {"source": SIL_KEY_SRC, "state": _KEY_STATE,
                            "fp16": _KEY_FP, "err": _KEY_ERR[:200],
                            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        atomic_write_json(CFG["state"], st, mode=0o600)   # v1.3.13：状态面 0600（关同组可写面）
    except OSError as e:
        log("状态文件写入失败: %s" % e)


def write_metrics(st):
    if DRY:
        return
    c = st.get("counters", {})
    lr = st.get("last_round") or {}
    m = {
        "ts": int(time.time() * 1000),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "service": "self-improve-loop",
        "interval_s": CFG["interval"], "threshold": CFG["threshold"],
        "rounds": st.get("rounds", 0),
        "dry": DRY,
        "stopped": os.path.exists(CFG["stop"]),
        "actions_total": {
            "rounds": st.get("rounds", 0),
            "triggered_rounds": c.get("triggered", 0),
            "noop_rounds": c.get("noop", 0),
            "candidates_queued": c.get("candidates_queued", 0),
            "verdicts_queued": c.get("verdicts_queued", 0),
            "commits": c.get("commits", 0),
            "rollbacks": c.get("rollbacks", 0),
            "errors": c.get("errors", 0),
        },
        "queues": {"verdict": len(st.get("verdict_queue", [])),
                   "projection": len(st.get("projection_todos", [])),
                   "candidates": len(st.get("experiment_candidates", []))},
        # 镜像真实性门位上板（本批 2026-11-02）：metrics 面此前无 gate 状态——双源
        # 拒用（裁决产出停摆）时本文件照常全绿刷新（2026-11-02 实证 3.5h+）。键值=
        # loop-state 同名键逐源 trusted 布尔；false=该源终态单拒用（产出腿收窄/停摆）。
        "mirror_ro_gate": dict(st.get("mirror_ro_gate") or {}),
        # RT-E85② 密钥出域停摆位上板（P1-设计 K8；probe ⑩ 同步点）：metrics 面此前
        # 无「签名钥可用性」读数——取钥失败（gov 不可达/解封/403/指纹失配）时其余
        # 面照常刷新（RT-E88 同型失真）。state 非 ok ⇒ 停摆在册。
        "key_status": dict(st.get("key_status") or {}),
        # 在役源码版本钉上板（v1.3.11）：metrics 面此前无「在役跑哪份码」读数——
        # 盘上源码改了不重启时，面面照常刷新（读数全绿失真）。此处=守护载入时的
        # 源码指纹，与盘上 tools/self-improve-loop.py 逐字比对即可判「在役=盘上」。
        "daemon_src": dict(st.get("daemon_src") or {}),
        "last_round": {
            "ts": lr.get("ts"), "outcome": lr.get("outcome"),
            "verified": (lr.get("perceive") or {}).get("verified"),
            "delta": lr.get("delta"),
            "new_clusters": len((lr.get("consensus") or {}).get("diff", {}).get("new", [])),
            "changed_clusters": len((lr.get("consensus") or {}).get("diff", {}).get("changed", [])),
            "commits": lr.get("commits", []),
        },
        "baseline": st.get("baseline"),
    }
    try:
        atomic_write_json(CFG["metrics"], m)
    except OSError as e:
        log("指标文件写入失败: %s" % e)


# ---------------------------------------------------------------- 一轮
def exp_and_writeback_round(st, cons):
    """③实验排队+终裁聚合 与 ④回写（v1.3 抽出为独立函数）。

    v1.3 修订依据（2026-10-31 实证）：原实现把 ③④ 放在 ①KB 增量触发之后，
    verified 停滞 15h（沙箱抽取线静默）期间 EXP-2 五臂终裁落定却无人感知——
    实验链（exp 镜像签名→源聚合器→判定门→回写）与 KB 增长是两条独立触发源，
    回写不应被 ①阈值饿死。现 noop 轮也执行本函数（cons=None：候选返空、
    策略册走 prev-book 兜底、映射不可求值时按既有「映射延期」路径处理）。
    """
    acts = []
    # ③ 实验排队 + 终裁聚合
    exp = None
    try:
        exp = experiment_round(st, cons)
    except Exception as e:
        st["counters"]["errors"] += 1
        exp = {"error": str(e)[:300]}
        log("③实验排队异常（不崩）: %s" % e)
    for c in (exp or {}).get("candidates", []):
        st["experiment_candidates"].append(c)
        st["counters"]["candidates_queued"] += 1
        acts.append("candidate:%s" % c["cluster_id"])
    st["experiment_candidates"] = st["experiment_candidates"][-200:]
    for v in (exp or {}).get("verdicts", []):
        st["counters"]["verdicts_queued"] += 1
        acts.append("verdict:%s=%s" % (v.get("exp_id"), v.get("verdict")))
    # v1.3.3：寄存/历史丢弃的自动初建裁决再入队（回写面环境键变化触发+一次性
    # 恢复旧语义丢弃项——st-C122/EXP-1 实证回收；DRY 内部跳过）。必须在④队列
    # 判空之前，恢复项当轮即可进回写。
    try:
        _reenqueue_parked_auto_creates(st)
    except Exception as e:
        st["counters"]["errors"] += 1
        log("③④寄存重入队扫描异常（不崩，下轮重试）: %s" % e)
    # ④ 回写（轮内熔断：STOP 中途落下则本轮不回写，留队下轮）
    wb = None
    if st.get("verdict_queue") or any(t.get("entry_draft") for t in st.get("projection_todos", [])):
        if os.path.exists(CFG["stop"]):
            log("STOP 熔断中途落下——跳过④回写（队列留队，删 STOP 后下轮执行）")
            wb = {"status": "stopped-midround"}
        else:
            try:
                wb = writeback_round(st, cons)
            except Exception as e:
                st["counters"]["errors"] += 1
                wb = {"error": str(e)[:300]}
                log("④回写异常（不崩，失败项留队）: %s" % e)
    if wb and wb.get("commits"):
        st["commits"].extend(wb["commits"])
        st["counters"]["commits"] += len(wb["commits"])
        acts.append("commit:%s" % ",".join(wb["commits"]))
    if wb and wb.get("status") in ("checker-red", "git-failed"):
        st["rollbacks"].append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "status": wb["status"], "detail": (wb.get("tail") or "")[-200:]})
        st["counters"]["rollbacks"] += 1
    return acts, exp, wb


def round_once(st, force=False):
    acts = []
    # STOP 熔断（轮间+轮内同判）
    if os.path.exists(CFG["stop"]):
        log("STOP 熔断在位（%s），本轮无动作（删之恢复）" % os.path.basename(CFG["stop"]))
        st["rounds"] += 1
        st["last_round"] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "outcome": "stopped"}
        save_state(st)
        write_metrics(st)
        return acts
    # ① 感知
    try:
        perc = perceive()
    except Exception as e:
        st["counters"]["errors"] += 1
        log("①感知失败（不崩，下轮重试）: %s" % e)
        st["last_round"] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "outcome": "perceive-error", "error": str(e)[:200]}
        save_state(st)
        write_metrics(st)
        return acts
    base = st.get("baseline")
    delta = None if base is None else perc["verified"] - base["verified"]
    r = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "perceive": perc,
         "baseline": base, "delta": delta, "threshold": CFG["threshold"]}
    # RT-E85② 签名停摆冻结轮（P1-设计 §2.3；probe ⑩ 同步点=save_state 的 key_status，
    # sil-verdict-probe 消费 st["key_status"]——state 非 ok ⇒ rc=1 红）：
    # openbao 钥源停摆 ⇒ ②③④ 全部跳过（凡写封条覆盖四段 verdict_queue/
    # auto_create_retry/projection_todos/verdict_log 的段皆冻结）——不降级为
    # 「无签名继续裁/写」，也不自生成换钥；只保 ①感知+⑤记账+心跳（活性保持真实，
    # 台账:747 RT-E88 口径：停摆显式在册、可判定红，与「环在跑」的绿可区分）。
    if _key_signing_halted():
        st["rounds"] += 1
        st["counters"]["signing_halted_rounds"] = \
            st["counters"].get("signing_halted_rounds", 0) + 1
        r["outcome"] = "signing-halted"
        r["note"] = ("RT-E85② 签名钥停摆（%s：%s）——②③④冻结，仅感知+记账"
                     % (_KEY_STATE, _KEY_ERR[:80]))
        st["last_round"] = r
        save_state(st)
        write_metrics(st)
        log("⑤签名停摆轮（%s）：②③④冻结——恢复=钥源可用后**重启守护进程**自动续跑"
            "（停摆态粘滞不重取，T18f1 钉住；不自生成、不降级）"
            % _KEY_STATE)
        return acts
    if base is None and not force:
        st["baseline"] = {"verified": perc["verified"], "total": perc["total"],
                          "watermark": perc["watermark"],
                          "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        st["rounds"] += 1
        st["counters"]["noop"] += 1
        r["outcome"] = "baseline-established"
        st["last_round"] = r
        save_state(st)
        write_metrics(st)
        log("①首轮建基线：verified=%d watermark=%s（未触发，阈值 %d）" %
            (perc["verified"], perc["watermark"], CFG["threshold"]))
        changelog("SIL 首轮建基线 verified=%d（阈值 %d，增量累积到阈值才触发）" %
                  (perc["verified"], CFG["threshold"]))
        return acts
    triggered = bool(force) or (delta is not None and delta >= CFG["threshold"])
    r["triggered"] = triggered
    if not triggered:
        # v1.3：①未触发（KB 增量不足）不再整轮返回——③实验终态感知与④回写照跑
        # （修订依据见 exp_and_writeback_round docstring：2026-10-31 回写饿死实证）
        wb_acts, exp, wb = exp_and_writeback_round(st, None)
        st["rounds"] += 1
        st["counters"]["noop"] += 1
        r["outcome"] = "noop"
        r["note"] = "增量 %s < 阈值 %d" % (delta, CFG["threshold"])
        r["experiments"] = exp
        if wb is not None:
            r["writeback"] = wb
        st["last_round"] = r
        save_state(st)
        write_metrics(st)
        log("①感知：verified=%d（基线 %s，增量 %s < 阈值 %d）→ ②跳过；③实验感知照跑%s" %
            (perc["verified"], base["verified"] if base else "-", delta, CFG["threshold"],
             ("（终裁 +%d；回写 %s）" % (len((exp or {}).get("verdicts", [])),
                                       (wb or {}).get("status", "无待写"))) if wb_acts else "（无实验事件）"))
        # 空转轮仅在有实验事件时才写变更日志（防 10min 周期刷屏）
        if (exp or {}).get("verdicts") or (wb or {}).get("commits") or \
                (wb or {}).get("status") in ("checker-red", "git-failed"):
            wb_txt = ("commit " + ",".join(wb["commits"])) if (wb or {}).get("commits") \
                else ((wb or {}).get("status") or "无待写")
            changelog("SIL 空转轮（增量 %s < 阈值 %d；②跳过）③实验链照跑：终裁 +%d；回写 %s" %
                      (delta, CFG["threshold"], len((exp or {}).get("verdicts", [])), wb_txt))
        return acts + wb_acts
    # ② 共识增量
    if delta is not None:
        log("①触发：verified 增量 %+d ≥ 阈值 %d → ②共识出册" % (delta, CFG["threshold"]))
    else:
        log("①强制触发（--force-trigger，基线 %s）→ ②共识出册" % ((base or {}).get("verified", "-")))
    st["counters"]["triggered"] += 1
    acts.append("trigger")
    cons = None
    try:
        os.makedirs(CFG["tmp"], exist_ok=True)
        cons = consensus_round(st, os.path.join(CFG["tmp"], "bcanon-out"))
    except Exception as e:
        st["counters"]["errors"] += 1
        cons = {"error": str(e)[:300]}
        log("②共识增量失败（不崩；基线不前进，下轮重试同一增量）: %s" % e)
    r["consensus"] = cons
    if cons and not cons.get("error"):
        # 基线前进（防重放）；投影待办/漂移登记
        st["baseline"] = {"verified": perc["verified"], "total": perc["total"],
                          "watermark": perc["watermark"],
                          "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        have = {t["cluster_id"] for t in st["projection_todos"]}
        have |= {t["cluster_id"] for t in st["projection_log"]}
        for t in cons["projection_todos_new"]:
            if t["cluster_id"] not in have:
                st["projection_todos"].append(t)
        st["projection_todos"] = st["projection_todos"][-200:]
        acts.append("consensus")
    # ③ 实验排队 + 终裁聚合 + ④ 回写（v1.3：抽为 exp_and_writeback_round）
    wb_acts, exp, wb = exp_and_writeback_round(st, cons)
    acts.extend(wb_acts)
    r["experiments"] = exp
    if wb is not None:
        r["writeback"] = wb
    # ⑤ 记账
    r["outcome"] = "triggered"
    r["commits"] = (wb or {}).get("commits", [])
    st["rounds"] += 1
    st["last_round"] = r
    save_state(st)
    write_metrics(st)
    d = (cons or {}).get("diff", {})
    cons_failed = bool((cons or {}).get("error"))
    # 回写状态唯一真源=r["writeback"]（④各分支都写它；局部 wb 在 stopped-midround
    # 分支不赋值——第 2 轮复核残漏：曾因此把轮内 STOP 轮写成「回写 无」）
    wbr = r.get("writeback") or {}
    wb_status = wbr.get("status", "无待写")
    if cons_failed:
        log("⑤本轮收官：②共识出册失败（diff 未产出，基线不前进下轮重试）；候选 +%d；终裁 +%d；回写 %s" %
            (len((exp or {}).get("candidates", [])), len((exp or {}).get("verdicts", [])),
             wb_status))
    else:
        log("⑤本轮收官：新簇 %d/变簇 %d/消失 %d；候选 +%d；终裁 +%d；回写 %s" %
            (len(d.get("new", [])), len(d.get("changed", [])), len(d.get("removed", [])),
             len((exp or {}).get("candidates", [])), len((exp or {}).get("verdicts", [])),
             wb_status))
    # 回写状态如实入行（复核 F2/F3 + 第 2 轮残漏：②失败不得冒领 diff；回写失败/
    # DRY/轮内 STOP 都不得写"无"——统一读 r["writeback"]）
    if wbr.get("commits"):
        wb_txt = "commit " + ",".join(wbr["commits"])
    elif wbr.get("status") in ("checker-red", "git-failed"):
        # v1.1：含自动初建条目的轮次，该项 attempt-once 已出队（不谎称"留队重试"）
        if any(e.get("action") == "auto-create" for e in (wbr.get("edits") or [])):
            wb_txt = "失败已回滚（自动初建寄存待回写面环境变化重入队，详见回滚行）"
        else:
            wb_txt = "失败已回滚（详见回滚行，留队重试）"
    elif wbr.get("status") == "dry-run":
        wb_txt = "DRY 未执行（计划 %d 项）" % len(wbr.get("plan") or [])
    elif wbr.get("status") == "stopped-midround":
        wb_txt = "STOP 中途熔断跳过（留队）"
    else:
        wb_txt = "无"
    if cons_failed:
        head = ("SIL 触发轮：verified 增量 %s（%s→%d，阈值 %d）→ ②共识出册失败"
                "（diff 未产出、基线不前进，下轮对同一增量重试）：%s" % (
                    ("%+d" % delta) if delta is not None else "全量(force)",
                    (base or {}).get("verified", "-"), perc["verified"], CFG["threshold"],
                    (cons.get("error") or "")[:120]))
    else:
        head = ("SIL 触发轮：verified 增量 %s（%s→%d，阈值 %d）→ 出册 diff 新%d/变%d/没%d；"
                "投影待办 %d（v1.1：终裁目标缺条自动初建条目、checker 过才 commit）；实验候选 %d；终裁 %d" % (
                    ("%+d" % delta) if delta is not None else "全量(force)",
                    (base or {}).get("verified", "-"), perc["verified"], CFG["threshold"],
                    len(d.get("new", [])), len(d.get("changed", [])), len(d.get("removed", [])),
                    len(cons["projection_todos_new"]) if cons and not cons.get("error") else 0,
                    len((exp or {}).get("candidates", [])),
                    len((exp or {}).get("verdicts", []))))
    changelog(head + "；回写 " + wb_txt)
    return acts


# ---------------------------------------------------------------- selftest
def _selftest():
    """不变量自检：合成夹具 + 真实只读对账。全部临时件落 $HOME。"""
    import tempfile
    import shutil
    fails = []

    def check(name, cond, detail=""):
        print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name, (" — " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="sil-selftest-", dir=HOME)
    old = dict(CFG)
    try:
        CFG.update({"state": tmp + "/loop-state.json", "metrics": tmp + "/self-improve.json",
                    "log": tmp + "/loop.log", "changelog": tmp + "/变更日志.md",
                    "stop": tmp + "/.STOP", "pidfile": tmp + "/.pid", "tmp": tmp + "/sil-tmp",
                    "wb_wt": tmp + "/af-wt-none", "wb_branch": "sil-selftest-wb"})
        # RT-E85②（K9 前置/T18a 适配）：selftest 强制 test 钥源+独立夹具钥路径——
        # 生产 openbao 模式守护不落钥文件，selftest 不读生产钥、不触 ~/.config/sil-rt。
        # T18a「签名密钥在位且 0600」断言对象随之=selftest 夹具钥（语义保持）；
        # 生产钥可用性断言由 key_status（守护侧）+probe ⑩（消费侧）接管（更严）。
        global SIL_KEY_SRC, MIRROR_KEY_PATH
        global SIL_KEY_EXPECTED_SHA256
        global _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP
        SIL_KEY_SRC = "test"
        MIRROR_KEY_PATH = tmp + "/test-signing.key"
        _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
        print("== selftest（tmp=%s）==" % tmp)

        # T1 diff 逻辑（合成两版策略册）
        def row(cid, tier, rank, extra=""):
            return json.dumps({"cluster_id": cid, "tier": tier, "rank": rank,
                               "strategy_name": "n" + cid, "assertion": "a" + cid + extra,
                               "topic_label": "t", "card_ids": "['S1','S2']",
                               "n_cards": 2, "n_corpora": 1 if tier == "B" else 2,
                               "representative_id": "S1", "citation_density": 9,
                               "empirical_question": "q", "confirm_line": "c",
                               "refute_line": "r"}, ensure_ascii=False)
        prev = {r["cluster_id"]: {"row": r, "fp": sha256_text(json.dumps(r, ensure_ascii=False))}
                for r in (json.loads(row("C001", "A", 1)), json.loads(row("C002", "B", 2)),
                          json.loads(row("C003", "C", 3)))}
        cur = {r["cluster_id"]: {"row": r, "fp": sha256_text(json.dumps(r, ensure_ascii=False))}
               for r in (json.loads(row("C001", "A", 1)), json.loads(row("C002", "B", 2, "!")),
                         json.loads(row("C004", "A", 4)))}
        n, c, rm = diff_books(prev, cur)
        check("T1 diff 新/变/消失", n == ["C004"] and c == ["C002"] and rm == ["C003"],
              "new=%s changed=%s removed=%s" % (n, c, rm))

        # T2 条目 id 命名空间
        check("T2 tier→entry id", entry_id_for("C130", "A") == "st-C130"
              and entry_id_for("C130", "B") == "st-b-C130")

        # T3 experiment 块幂等改写（flow 与块两种形态 + 自校验还原）
        base_entry = ("id: st-C007\nname: x\ntier: A\nclaim: c\nexperiment: {status: none,"
                      " exp_id: \"-\", note: \"-\"}\ndsl_state: not_applicable\nna_reason: r\n")
        p1 = tmp + "/st-C007.yaml"
        open(p1, "w", encoding="utf-8").write(base_entry)
        tgt = {"status": "inconclusive", "exp_id": "EXP-1", "note": "终裁：p=0.75；\"引号\" 换行\n"}
        r1 = apply_experiment_edit(p1, tgt)
        after = yaml.safe_load(open(p1, encoding="utf-8").read())
        check("T3a flow 形态改写", r1["changed"] and after["experiment"] == tgt
              and after["na_reason"] == "r")
        r2 = apply_experiment_edit(p1, tgt)
        check("T3b 幂等（二次不改）", not r2["changed"])
        block_entry = base_entry.replace(
            'experiment: {status: none, exp_id: "-", note: "-"}',
            'experiment:\n  status: none\n  exp_id: "-"\n  note: "-"')
        p2 = tmp + "/st-b-C001.yaml"
        open(p2, "w", encoding="utf-8").write(block_entry)
        r3 = apply_experiment_edit(p2, tgt)
        after2 = yaml.safe_load(open(p2, encoding="utf-8").read())
        check("T3c 块形态改写", r3["changed"] and after2["experiment"] == tgt
              and after2["dsl_state"] == "not_applicable")

        # T4 阈值/触发语义（含首轮建基线）
        stt = load_state()
        check("T4a 首轮无基线", stt["baseline"] is None)
        stt["baseline"] = {"verified": 100, "total": 200, "watermark": "x"}
        d = 49 - 100
        check("T4b 增量<阈值不触发", not (d >= CFG["threshold"]))
        d = 150 - 100
        check("T4c 增量≥阈值触发", d >= CFG["threshold"])

        # T5 真实只读对账：逐源镜像终态单签名（v1.1 补丁①：exp1 E1-* + exp2 E2-*）
        sigs1, sigs2 = exp_mirror_signatures(), exp_mirror_signatures()
        check("T5a 逐源签名稳定且双源非空",
              sigs1 == sigs2 and len(sigs1["exp1"][1]) > 0 and len(sigs1["exp2"][1]) > 0,
              "exp1 completed=%d；exp2 completed=%d" % (len(sigs1["exp1"][1]), len(sigs1["exp2"][1])))
        comb1, orders1 = exp_mirror_signature()
        check("T5b 合并签名≠exp1 单选签名（watch 面确已扩容）",
              comb1 != sigs1["exp1"][0] and set(orders1) == {"exp1", "exp2"},
              "combined=%s… exp1=%s…" % (comb1[:12], sigs1["exp1"][0][:12]))
        # T5c v1→v1.1 状态迁移：旧 combined（exp1 口径）== exp1 源签名 → exp1 不重复聚合
        legacy = {"exp_mirror_sig": sigs1["exp1"][0]}
        migrated = dict(legacy.get("exp_mirror_sigs") or {})
        if not migrated and legacy.get("exp_mirror_sig") and sigs1.get("exp1") \
                and sigs1["exp1"][0] == legacy["exp_mirror_sig"]:
            migrated["exp1"] = sigs1["exp1"][0]
        changed_after_migrate = [s["name"] for s in exp_sources()
                                 if migrated.get(s["name"]) != sigs1[s["name"]][0]]
        check("T5c 旧状态迁移后仅 exp2 源算新终态单",
              changed_after_migrate == ["exp2"], str(changed_after_migrate))

        # T6 终裁→条目映射（v1.1：EXP-1 主断言卡 S161 → C122 tier C——不再跳过，
        # 带 target_entry_id（自动建条目命名空间）与册内材料；EXP-2 同构查 S115→C103）
        book = load_book(CFG["canon_book"])
        m = map_verdict_to_entry("EXP-1", book)
        mat = m.get("entry_material") or {}
        check("T6a EXP-1 映射 C122/tier C/自动建条目 id st-C122",
              m.get("target_cluster") == "C122" and m.get("target_tier") == "C"
              and m.get("target_entry") is None
              and m.get("target_entry_id") == "st-C122"
              and mat.get("claim") and mat.get("name") and mat.get("sources")
              and mat.get("corpora") and mat.get("cards"),
              json.dumps({k: m.get(k) for k in ("target_cluster", "target_tier",
                                                "target_entry_id")}, ensure_ascii=False))
        m2 = map_verdict_to_entry("EXP-2", book)
        check("T6b EXP-2 映射 C103/tier C/自动建条目 id st-C103",
              m2.get("target_cluster") == "C103" and m2.get("target_tier") == "C"
              and m2.get("target_entry_id") == "st-C103",
              json.dumps({k: m2.get(k) for k in ("target_cluster", "target_tier",
                                                 "target_entry_id")}, ensure_ascii=False))

        # T7 终裁词→库五态映射（pending 为 G4 闭集原生"数据未到齐"态，不与
        # inconclusive 混同；其余非 confirmed/refuted 保守落 inconclusive）
        check("T7 verdict→status 映射保守",
              VERDICT_STATUS_MAP.get("confirmed") == "confirmed"
              and VERDICT_STATUS_MAP.get("refuted") == "refuted"
              and VERDICT_STATUS_MAP.get("pending") == "pending"
              and VERDICT_STATUS_MAP.get("equivalent", VERDICT_FALLBACK) == "inconclusive"
              and VERDICT_STATUS_MAP.get("dose_unstable", VERDICT_FALLBACK) == "inconclusive")

        # T7b v1.1：pending 终裁的 note 只记实际产出的键（不臆造 n_p/main_diff 等）
        n_pending = _verdict_note("pending", {"pending_reason": "臂未到齐"},
                                  "/x/exp2-aggregate-summary.json", "ab" * 6, 23,
                                  "映射：主断言卡 S115 → 簇 C103（tier C）")
        check("T7b pending note 不带臆造判读键",
              "n_p=" not in n_pending and "pending_reason=臂未到齐" in n_pending
              and "completed=23" in n_pending and "tier C" in n_pending, n_pending[:120])

        # T7c v1.1：条目 id 命名空间（tier C/D 用平铺 st-C0XX，不落 B 线 st-b- 前缀）
        check("T7c tier→entry id 命名空间",
              entry_id_for("C130", "A") == "st-C130"
              and entry_id_for("C130", "B") == "st-b-C130"
              and entry_id_for("C130", "C") == "st-C130"
              and entry_id_for("C130", "D") == "st-C130")

        # T7d v1.1：自动初建条目 dict（tier 照实/claim 册内断言/experiment 终裁/
        # needs_syntax+待投影；claimed_value 三维显式占位、direction 在 R1 闭集）
        auto_item = {"target_entry_id": "st-C103", "target_cluster": "C103",
                     "target_tier": "C", "status": "pending", "exp_id": "EXP-2",
                     "verdict": "pending", "note": "终裁 pending（臂未到齐）。",
                     "entry_material": {"name": "夹具策略名", "claim": "夹具断言",
                                        "sources": ["S115"], "corpora": 1, "cards": 1,
                                        "topic": "多agent协同"}}
        d_auto = build_auto_entry(auto_item)
        check("T7d 自动初建条目字段照实+占位显式",
              d_auto["id"] == "st-C103" and d_auto["tier"] == "C"
              and d_auto["claim"] == "夹具断言" and d_auto["sources"] == ["S115"]
              and d_auto["experiment"]["status"] == "pending"
              and d_auto["experiment"]["exp_id"] == "EXP-2"
              and d_auto["dsl_state"] == "needs_syntax"
              and "待投影" in d_auto["needs_syntax_note"]
              and d_auto["claimed_value"]["direction"] in ("up", "down")
              and "待投影" in d_auto["claimed_value"]["metric"]
              and "待投影" in d_auto["claimed_value"]["context"],
              json.dumps({k: d_auto[k] for k in ("id", "tier", "dsl_state")}, ensure_ascii=False))

        # T8 条目 YAML 生成（G4 九字段+三态互斥，过 R1 形状检查）
        draft = {"id": "st-C999", "name": "SELFTEST-FIXTURE 自检夹具条目",
                 "tier": "A", "claim": "夹具声称", "sources": ["S1", "S2"],
                 "claimed_value": {"metric": "m", "direction": "up", "context": "c"},
                 "consensus": {"corpora": 2, "cards": 2},
                 "experiment": {"status": "none", "exp_id": "-", "note": "-"},
                 "dsl_state": "needs_syntax",
                 "needs_syntax_note": "缺一等构造 X（示例：loop.exit_when 跨轮计数器）"}
        y = render_entry_yaml(draft)
        p3 = tmp + "/st-C999.yaml"
        open(p3, "w", encoding="utf-8").write(y)
        doc = yaml.safe_load(y)
        check("T8a 条目 R1 形状", all(k in doc for k in ("id", "name", "tier", "claim",
              "claimed_value", "sources", "consensus", "experiment", "dsl_state"))
              and doc["id"] == "st-C999" and doc["tier"] in ("A", "B")
              and doc["experiment"]["status"] in
              ("none", "inconclusive", "confirmed", "refuted", "pending")
              and doc["claimed_value"]["direction"] in ("up", "down")
              and "dsl_snippet" not in doc and "na_reason" not in doc
              and isinstance(doc["needs_syntax_note"], str) and doc["needs_syntax_note"])
        # T8b index 计数块更新（最小 diff：插一行+重算 counts）
        idx = tmp + "/index.yaml"
        open(idx, "w", encoding="utf-8").write(
            "version: 1\nentries:\n  - { id: st-C007, file: st-C007.yaml, tier: A,"
            " topic: t, dsl_state: not_applicable, rank: 2 }\ncounts:\n  total: 1\n"
            "  tiers: { A: 1, B: 0 }\n  dsl_states: { compilable: 0, needs_syntax: 0,"
            " not_applicable: 1 }\n")
        update_index_file(idx, {"id": "st-C999", "file": "st-C999.yaml", "tier": "A",
                                "topic": "夹具", "dsl_state": "needs_syntax", "rank": 130})
        idx2 = yaml.safe_load(open(idx, encoding="utf-8").read())
        check("T8b index 计数对账", len(idx2["entries"]) == 2
              and idx2["counts"]["total"] == 2 and idx2["counts"]["tiers"]["A"] == 2
              and idx2["counts"]["dsl_states"]["needs_syntax"] == 1)

        # T9 DRY 语义：一轮 DRY 不写任何 workspace 件
        CFG["dry"] = True
        globals()["DRY"] = True
        stt2 = load_state()
        round_once(stt2)
        check("T9a DRY 不落 state/metrics/changelog",
              not os.path.exists(CFG["state"]) and not os.path.exists(CFG["metrics"])
              and not os.path.exists(CFG["changelog"]))
        CFG["dry"] = False
        globals()["DRY"] = False

        # T10 STOP 熔断：在位即无动作但仍记账（keepalive 新鲜度）
        open(CFG["stop"], "w").write("x")
        stt3 = load_state()
        before = stt3["rounds"]
        round_once(stt3)
        check("T10 STOP 轮无动作但记账", stt3["last_round"].get("outcome") == "stopped"
              and stt3["rounds"] == before + 1 and os.path.exists(CFG["state"]))
        os.unlink(CFG["stop"])

        # T13 DRY 回写守卫（复核判据5 回归）：队列非空+DRY → 只报计划；
        # 绝不建工作树/不编辑/不跑 checker/不 commit，队列原样保留
        CFG["dry"] = True
        globals()["DRY"] = True
        stt4 = load_state()
        stt4["verdict_queue"] = [{
            "exp_id": "EXP-1", "verdict": "inconclusive", "status": "inconclusive",
            "note": "T13 守卫回归（不得落任何 git 动作）", "target_entry": "st-C007",
        }]
        r13 = writeback_round(stt4, None)
        check("T13a DRY 回写只报计划", r13.get("status") == "dry-run"
              and len(r13.get("plan") or []) == 1
              and not os.path.exists(CFG["wb_wt"]),
              json.dumps(r13, ensure_ascii=False)[:140])
        check("T13b DRY 不动队列/无 commit", len(stt4["verdict_queue"]) == 1
              and not r13.get("commits"))
        CFG["dry"] = False
        globals()["DRY"] = False

        # T14 触发轮无终裁回归（复核修复实证）：verdicts 空+队列空 → ⑤正常收官、
        # writeback=None、基线前进（曾因④块误缩进进 for 循环而 UnboundLocalError）
        real_cons, real_exp = globals()["consensus_round"], globals()["experiment_round"]

        def _fake_cons(_st, _tmpdir):
            return {"ts": "x", "book": {"path": CFG["canon_book"], "sha256": "x",
                                        "n_clusters": 129, "tiers": {}},
                    "baseline_book": "fake", "diff": {"new": [], "changed": [], "removed": []},
                    "strategies_dir": "", "projection_todos_new": [], "entry_drift": []}

        def _fake_exp(_st, _cons):
            return {"candidates": [], "verdicts": [], "mirror": {"changed": False}}

        globals()["consensus_round"], globals()["experiment_round"] = _fake_cons, _fake_exp
        thr = CFG["threshold"]
        CFG["threshold"] = 0
        try:
            stt5 = load_state()
            stt5["baseline"] = {"verified": 1, "total": 1, "watermark": "w"}
            round_once(stt5)
        finally:
            globals()["consensus_round"], globals()["experiment_round"] = real_cons, real_exp
            CFG["threshold"] = thr
        check("T14 触发轮无终裁正常收官（④缩进回归）",
              stt5["last_round"].get("outcome") == "triggered"
              and stt5["last_round"].get("writeback") is None
              and stt5["baseline"]["verified"] > 1,
              json.dumps({"outcome": stt5["last_round"].get("outcome"),
                          "wb": stt5["last_round"].get("writeback")}, ensure_ascii=False))

        # T15 v1.3.3：自动初建失败寄存+回写面环境键变化重入队+历史丢弃裁决一次性
        # 恢复（回归：st-C122/EXP-1 真实终裁 2026-10-31 09:14:59 曾被 attempt-once
        # 永久丢弃且再无再入队路径——G-SIL「裁决无论何种均如实回写」缺 1/2）
        real_checker15 = globals()["run_checker"]
        old_af, old_base, old_sdir = CFG["af"], CFG["wb_base"], CFG["strategies_dir"]
        CFG["af"] = tmp + "/af-syn"
        os.makedirs(CFG["af"] + "/strategies", exist_ok=True)
        os.makedirs(CFG["af"] + "/ci", exist_ok=True)
        open(CFG["af"] + "/strategies/index.yaml", "w", encoding="utf-8").write(
            "version: 1\nentries:\ncounts:\n  total: 0\n  tiers: {}\n  dsl_states: {}\n")
        open(CFG["af"] + "/strategies/README.md", "w", encoding="utf-8").write("syn\n")
        open(CFG["af"] + "/ci/strategies_check.py", "w", encoding="utf-8").write(
            "raise SystemExit(0)\n")
        sh(["git", "-C", CFG["af"], "init", "-q"], timeout=30)
        sh(["git", "-C", CFG["af"], "add", "-A"], timeout=30)
        sh(["git", "-C", CFG["af"], "-c", "user.email=sil-selftest@local",
            "-c", "user.name=sil-selftest", "commit", "-q", "-m", "syn"], timeout=30)
        _br = sh(["git", "-C", CFG["af"], "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
        CFG["wb_base"] = (_br.stdout or "").strip() or "master"
        CFG["strategies_dir"] = tmp + "/strategies-probe"
        os.makedirs(CFG["strategies_dir"], exist_ok=True)

        def _t15_item(eid, clu, mat_name):
            return {"exp_id": "EXP-9", "verdict": "inconclusive", "status": "inconclusive",
                    "note": "T15 夹具终裁", "target_cluster": clu, "target_tier": "C",
                    "target_entry_id": eid, "target_rank": 998,
                    "entry_material": {"name": mat_name, "claim": "夹具断言",
                                       "sources": ["S1"], "topic": "夹具",
                                       "corpora": 1, "cards": 1}}

        # T15a checker 红 → 回滚+出队但**寄存**（不再永久丢弃）
        globals()["run_checker"] = lambda wt: (1, "[FAIL] R1 T15 模拟红")
        stt6 = load_state()
        stt6["verdict_queue"] = [_t15_item("st-C998", "C998", "T15a")]
        r15 = writeback_round(stt6, None)
        globals()["run_checker"] = real_checker15
        check("T15a 初建红→回滚+寄存（不永久丢弃）",
              r15.get("status") == "checker-red"
              and len(stt6["verdict_queue"]) == 0
              and len(stt6.get("auto_create_retry") or []) == 1
              and stt6["verdict_log"][-1]["outcome"].startswith("自动建条目本轮未落条已寄存")
              and "writeback_error" not in stt6["auto_create_retry"][0]["item"],
              json.dumps({"status": r15.get("status"), "q": len(stt6["verdict_queue"]),
                          "park": len(stt6.get("auto_create_retry") or [])},
                         ensure_ascii=False))
        # T15b 回写面环境键变化（worktree 内 checker 内容变）→ 寄存项自动重入队
        with open(os.path.join(CFG["wb_wt"], "ci", "strategies_check.py"), "a",
                  encoding="utf-8") as f:
            f.write("\n# T15 env bump（模拟门修）\n")
        n15 = _reenqueue_parked_auto_creates(stt6)
        check("T15b 环境键变化→寄存项重入队",
              n15 == 1 and len(stt6["verdict_queue"]) == 1
              and stt6["verdict_queue"][0]["target_entry_id"] == "st-C998"
              and len(stt6.get("auto_create_retry") or []) == 0,
              "n=%d q=%d park=%d" % (n15, len(stt6["verdict_queue"]),
                                     len(stt6.get("auto_create_retry") or [])))
        # 同键不重试（防抖环）
        stt6["verdict_queue"] = []
        stt6["auto_create_retry"] = [{"item": _t15_item("st-C998", "C998", "T15a"),
                                      "env_key": _wb_env_key(CFG["wb_wt"]),
                                      "ts": "x"}]
        n15_same = _reenqueue_parked_auto_creates(stt6)
        check("T15c 同环境键不重试（防抖环）",
              n15_same == 0 and len(stt6["verdict_queue"]) == 0
              and len(stt6["auto_create_retry"]) == 1)
        # T15d verdict_log 旧语义丢弃裁决一次性恢复（st-C122 同构）+幂等
        # v1.3.12：日志条目须带守护封条（③段签发）方可被复活（复制点自证来源）——
        # 夹具按守护自产件同款签发（seal_verdict_item）。
        stt7 = load_state()
        dropped = _t15_item("st-C997", "C997", "T15d")
        dropped.update({"exp_id": "EXP-8", "ts": "2026-10-31 09:14:59",
                        "writeback_error": "checker 红（exit=1…旧语义）",
                        "outcome": "自动建条目尝试 1 次即止：checker 红 exit=1 已回滚 "
                                   "clean=True（旧语义永久丢弃）"})
        seal_verdict_item(dropped)          # v1.3.12：守护自产件同款签发
        stt7["verdict_log"] = [dropped]
        n15d1 = _reenqueue_parked_auto_creates(stt7)
        n15d2 = _reenqueue_parked_auto_creates(stt7)     # 幂等：已标记不重排
        check("T15d 历史丢弃裁决一次性恢复+幂等",
              n15d1 == 1 and n15d2 == 0 and len(stt7["verdict_queue"]) == 1
              and stt7["verdict_queue"][0]["entry_material"]["name"] == "T15d"
              and "writeback_error" not in stt7["verdict_queue"][0]
              and stt7["verdict_log"][0].get("requeued_ts")
              and stt7["verdict_log"][0].get("writeback_error"),
              "n1=%d n2=%d q=%d" % (n15d1, n15d2, len(stt7["verdict_queue"])))
        # T15d2 v1.3.12：日志条目**无守护封条**（注入/篡改件）→ 复制点拒（不复活、
        # 不入裁决队列、不入回写计划）——纵深腿：面级封条之外，复制点自证来源。
        stt7b = load_state()
        injected = _t15_item("st-C994", "C994", "T15d2-注入")
        injected.update({"exp_id": "EXP-EVIL", "ts": "2026-11-03 00:00:00",
                         "outcome": "自动建条目尝试 1 次即止：checker 红 exit=1 已回滚 "
                                    "clean=False（注入伪造）"})
        stt7b["verdict_log"] = [injected]        # 无 seal_verdict_item = 非守护签发
        n15d2b = _reenqueue_parked_auto_creates(stt7b)
        CFG["dry"] = True
        globals()["DRY"] = True
        r15d2b = writeback_round(stt7b, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        check("T15d2 无守护封条的日志条目（注入件）→ 不得复活、不得入回写计划"
              "（v1.3.12 复制点自证来源）",
              n15d2b == 0 and len(stt7b["verdict_queue"]) == 0
              and not (r15d2b.get("plan") or [])
              and stt7b["verdict_log"][0].get("requeue_rejected"),
              json.dumps({"n": n15d2b, "q": len(stt7b["verdict_queue"]),
                          "plan": r15d2b.get("plan"),
                          "why": (stt7b["verdict_log"][0].get("requeue_rejected") or "")[:60]},
                         ensure_ascii=False))
        # T15e 条目已在场的历史失败只标记不重排队（裁决已如实在库）
        open(os.path.join(CFG["strategies_dir"], "st-C996.yaml"), "w",
             encoding="utf-8").write("id: st-C996\n")
        stt8 = load_state()
        present = _t15_item("st-C996", "C996", "T15e")
        present.update({"ts": "2026-10-30 00:22:26",
                        "outcome": "自动建条目尝试 1 次即止：checker 红 exit=1 已回滚 "
                                   "clean=True（旧语义永久丢弃）"})
        seal_verdict_item(present)          # v1.3.12：守护自产件同款签发
        stt8["verdict_log"] = [present]
        n15e = _reenqueue_parked_auto_creates(stt8)
        check("T15e 条目已在场→只标记不重排队",
              n15e == 0 and len(stt8["verdict_queue"]) == 0
              and "不重排队" in (stt8["verdict_log"][0].get("requeue_note") or "")
              and stt8["verdict_log"][0].get("requeued_ts"))

        # T15f v1.3.4：更新/投影路径失败项同寄存语义（attempt-once 语义洞回归：
        # 2026-11-01 st-C103/EXP-2 持续红环境每 600s 一次编辑→checker→回滚抖环
        # rollbacks 25→42 实证——更新路径留队每轮无条件重试违反「键不变不重试」
        # 原则；v1.3.3 门控只盖自动初建）。条目在场（更新路径）+投影待办在场。
        open(os.path.join(CFG["wb_wt"], "strategies", "st-C995.yaml"), "w",
             encoding="utf-8").write(
                'id: st-C995\nname: "T15f 夹具"\ntier: A\nclaim: "夹具断言"\n'
                'claimed_value: {metric: m, direction: up, context: c}\n'
                'sources: ["S1"]\nconsensus: {corpora: 1, cards: 1}\n'
                'experiment: {status: none, exp_id: "-", note: "-"}\n'
                'dsl_state: needs_syntax\nneeds_syntax_note: "x"\n')
        sh(["git", "-C", CFG["wb_wt"], "add", "-A"], timeout=TMO["git"])
        sh(["git", "-C", CFG["wb_wt"], "-c", "user.email=sil-selftest@local",
            "-c", "user.name=sil-selftest", "commit", "-q", "-m", "t15f fixture"],
           timeout=TMO["git"])
        globals()["run_checker"] = lambda wt: (1, "[FAIL] R1 T15f 模拟红")
        stt10 = load_state()
        upd10 = {"exp_id": "EXP-9", "verdict": "inconclusive", "status": "inconclusive",
                 "note": "T15f 夹具终裁", "target_entry": "st-C995",
                 "target_entry_id": "st-C995"}
        proj10 = {"entry_id": "st-C994", "tier": "A", "rank": 997,
                  "entry_draft": {"id": "st-C994", "name": "T15f 投影夹具", "tier": "A",
                                  "claim": "夹具断言",
                                  "claimed_value": {"metric": "m", "direction": "up",
                                                    "context": "c"},
                                  "sources": ["S1"], "consensus": {"corpora": 1, "cards": 1},
                                  "experiment": {"status": "none", "exp_id": "-", "note": "-"},
                                  "dsl_state": "needs_syntax",
                                  "needs_syntax_note": "x"}}
        stt10["verdict_queue"] = [upd10]
        stt10["projection_todos"] = [proj10]
        r15f = writeback_round(stt10, None)
        globals()["run_checker"] = real_checker15
        check("T15f 更新/投影失败项出队寄存（不留队下轮重试）",
              r15f.get("status") == "checker-red"
              and len(stt10["verdict_queue"]) == 0
              and len(stt10["projection_todos"]) == 0
              and len(stt10.get("auto_create_retry") or []) == 2
              and stt10["auto_create_retry"][-2].get("kind") == "verdict"
              and stt10["auto_create_retry"][-1].get("kind") == "projection"
              and "writeback_error" not in stt10["auto_create_retry"][-2]["item"]
              and "writeback_error" not in stt10["auto_create_retry"][-1]["item"]
              and stt10["verdict_log"][-1]["outcome"].startswith("回写失败本轮已寄存"),
              json.dumps({"status": r15f.get("status"), "q": len(stt10["verdict_queue"]),
                          "p": len(stt10["projection_todos"]),
                          "park": len(stt10.get("auto_create_retry") or [])},
                         ensure_ascii=False))
        # T15f 同键不重入队（防抖环核心：零环境变化 → 队列保持空 → ④不再跑 checker）
        n15f_same = _reenqueue_parked_auto_creates(stt10)
        check("T15f 同环境键不重入队（防抖环；修前此处置读队重试成 600s 抖环）",
              n15f_same == 0 and len(stt10["verdict_queue"]) == 0
              and len(stt10["projection_todos"]) == 0
              and len(stt10.get("auto_create_retry") or []) == 2,
              "n=%d q=%d p=%d park=%d" % (n15f_same, len(stt10["verdict_queue"]),
                                          len(stt10["projection_todos"]),
                                          len(stt10.get("auto_create_retry") or [])))
        # T15f 键变化（模拟门修）→ 寄存件按原属队列各自重入队（不永久丢弃）
        with open(os.path.join(CFG["wb_wt"], "ci", "strategies_check.py"), "a",
                  encoding="utf-8") as f:
            f.write("\n# T15f env bump（模拟门修）\n")
        n15f = _reenqueue_parked_auto_creates(stt10)
        check("T15f 键变化→按原属队列重入队（更新→裁决队列，投影→投影队列）",
              n15f == 2 and len(stt10["verdict_queue"]) == 1
              and stt10["verdict_queue"][0]["target_entry_id"] == "st-C995"
              and len(stt10["projection_todos"]) == 1
              and stt10["projection_todos"][0]["entry_id"] == "st-C994"
              and len(stt10.get("auto_create_retry") or []) == 0,
              "n=%d q=%d p=%d park=%d" % (n15f, len(stt10["verdict_queue"]),
                                          len(stt10["projection_todos"]),
                                          len(stt10.get("auto_create_retry") or [])))
        CFG["af"], CFG["wb_base"], CFG["strategies_dir"] = old_af, old_base, old_sdir

        # T16 回写面 entry_id 命名空间门 + rollback_edits 如实报净（红队 SIL 环修复回归）
        # T16a 在 DRY 下跑：即便门被回归移除，plan 非空也只走 dry-run 分支，不落任何
        # git/磁盘动作——回归时本判据以 status=dry-run≠empty 的形式红
        CFG["dry"] = True
        globals()["DRY"] = True
        stt9 = {"verdict_queue": [
            {"exp_id": "EXP-X", "target_entry_id": tmp + "/evil-abs"},   # 绝对路径逃逸
            {"exp_id": "EXP-Y", "target_entry_id": "../../evil-rel"},    # 相对路径逃逸
        ], "projection_todos": [
            {"entry_id": "../evil-proj", "entry_draft": {"id": "x"}},    # 投影面逃逸
        ]}
        r16 = writeback_round(stt9, None)
        check("T16a 非法 entry_id 拒入回写计划（不落盘，项留队带 writeback_error）",
              r16.get("status") == "empty"
              and all(v.get("writeback_error") for v in stt9["verdict_queue"])
              and stt9["projection_todos"][0].get("writeback_error")
              and not os.path.exists(tmp + "/evil-abs.yaml")
              and not os.path.exists(tmp + "/evil-rel.yaml"),
              json.dumps({"status": r16.get("status"),
                          "q_err": [bool(v.get("writeback_error"))
                                    for v in stt9["verdict_queue"]]}, ensure_ascii=False))
        CFG["dry"] = False
        globals()["DRY"] = False
        # T16b rollback_edits：仓库外路径如实 False（不谎报 clean=True）；树内照常 True 且还原
        repo16 = tmp + "/rb-repo"
        os.makedirs(repo16 + "/strategies", exist_ok=True)
        open(repo16 + "/strategies/st-C007.yaml", "w", encoding="utf-8").write(base_entry)
        _ok16 = True
        for _args in (["init", "-q"], ["add", "-A"],
                      ["-c", "user.email=sil-selftest@local",
                       "-c", "user.name=sil-selftest", "commit", "-q", "-m", "t16"]):
            _r16g = sh(["git", "-C", repo16] + _args, timeout=TMO["git"])
            if _r16g.returncode != 0:
                check("T16b rollback_edits 如实报净", False,
                      "git %s 失败: %s" % (_args[0], (_r16g.stderr or "")[-120:]))
                _ok16 = False
                break
        if _ok16:
            out16 = tmp + "/rb-outside.yaml"
            open(out16, "w", encoding="utf-8").write("id: out\nexp_id: injected\n")
            ok_out16 = rollback_edits(repo16, ["../rb-outside.yaml"], [])
            still16 = "exp_id: injected" in open(out16, encoding="utf-8").read()
            check("T16b rollback_edits 仓库外路径如实 False（不谎报 clean，注入不被谎称已还原）",
                  ok_out16 is False and still16,
                  "clean=%s 注入行仍在=%s" % (ok_out16, still16))
            p16 = repo16 + "/strategies/st-C007.yaml"
            open(p16, "a", encoding="utf-8").write("exp_id: injected\n")
            ok_in16 = rollback_edits(repo16, ["strategies/st-C007.yaml"], [])
            check("T16c rollback_edits 树内路径照常 True 且还原",
                  ok_in16 is True and "injected" not in open(p16, encoding="utf-8").read(),
                  "clean=%s 还原后含注入行=%s" %
                  (ok_in16, "injected" in open(p16, encoding="utf-8").read()))
            # T16d 净判据只看本轮回写面（红队 E15② 回归：整树 status 判净使 clean 位
            # 与还原成败脱钩——工作树常驻脏（未跟踪+已改未提交）不得把空回滚/成功
            # 回滚压成 False；真残差（staged，checkout 只还原到 index 态）仍须 False）
            open(repo16 + "/dirt-untracked.txt", "w", encoding="utf-8").write("dirt\n")
            open(p16, "a", encoding="utf-8").write("exp_id: dirt\n")   #  M 常驻脏（未提交）
            ok_e16 = rollback_edits(repo16, [], [])                    # 空回滚集
            open(repo16 + "/strategies/st-C009.yaml", "w", encoding="utf-8").write(base_entry)
            ok_n16 = rollback_edits(repo16, [], ["strategies/st-C009.yaml"])
            gone16 = not os.path.exists(repo16 + "/strategies/st-C009.yaml")
            sh(["git", "-C", repo16, "add", "--", "strategies/st-C007.yaml"], timeout=TMO["git"])
            ok_res16 = rollback_edits(repo16, ["strategies/st-C007.yaml"], [])
            res_dirty16 = "dirt" in open(p16, encoding="utf-8").read()
            check("T16d rollback_edits 常驻脏不压 clean（空集/成功回滚 True）且 staged 残差如实 False",
                  ok_e16 is True and ok_n16 is True and gone16
                  and ok_res16 is False and res_dirty16,
                  "空集clean=%s 新件回滚clean=%s 已删=%s staged残差clean=%s 残差内容仍脏=%s" % (
                      ok_e16, ok_n16, gone16, ok_res16, res_dirty16))
            # T16e git_commit 失败轮回滚语义（20261102 红队 SIL 环）：commit 失败后
            # add 已写 index——若不撤销，rollback_edits 对 staged 新件误判 tracked、
            # checkout 只还原到 index 态 → 残留件+登记行随下一轮 commit 静默入库。
            # 判据：失败轮 rollback_edits=True、scoped porcelain 净、round2 commit
            # 不含 round1 残留件；HEAD 移动后调用报失败 → 如实返回新头。
            _r16cfg = sh(["git", "-C", repo16, "config", "user.email", "sil-selftest@local"],
                         timeout=TMO["git"])
            _r16cfg2 = sh(["git", "-C", repo16, "config", "user.name", "sil-selftest"],
                          timeout=TMO["git"])
            _hk16 = repo16 + "/.git/hooks/pre-commit"
            open(_hk16, "w", encoding="utf-8").write("#!/bin/sh\nexit 1\n")
            os.chmod(_hk16, 0o755)
            _p998 = repo16 + "/strategies/st-C998.yaml"
            open(_p998, "w", encoding="utf-8").write(base_entry + "exp_id: injected-t16e\n")
            _p007 = repo16 + "/strategies/st-C007.yaml"
            _head007 = sh(["git", "-C", repo16, "show", "HEAD:strategies/st-C007.yaml"],
                          timeout=TMO["git"]).stdout or ""
            open(_p007, "a", encoding="utf-8").write("exp_id: touched-t16e\n")
            _raised16e = None
            try:
                git_commit(repo16, ["strategies/st-C007.yaml", "strategies/st-C998.yaml"],
                           "t16e 应被 pre-commit 钩子拒绝")
            except RuntimeError as _e16e:
                _raised16e = str(_e16e)
            ok16e = rollback_edits(repo16, ["strategies/st-C007.yaml"], ["strategies/st-C998.yaml"])
            _porc16e = sh(["git", "-C", repo16, "status", "--porcelain", "--",
                           "strategies/st-C007.yaml", "strategies/st-C998.yaml"],
                          timeout=TMO["git"])
            _gone16e = not os.path.lexists(_p998)
            _restored16e = open(_p007, encoding="utf-8").read() == _head007
            check("T16e commit 失败轮：rollback_edits True+无 staged 残留（件删净/tracked 还原到 HEAD）",
                  _raised16e is not None and "git commit 失败" in _raised16e
                  and ok16e is True and _gone16e and _restored16e
                  and not (_porc16e.stdout or "").strip(),
                  "raised=%s clean=%s 新件已删=%s tracked还原=%s scoped_porcelain=%r" % (
                      bool(_raised16e), ok16e, _gone16e, _restored16e,
                      (_porc16e.stdout or "").strip()[:80]))
            # round2 模拟：合规新件 commit，不得带入 round1 残留（st-C998 不得出现在
            # 新 commit；scoped porcelain 保持净——发现②的放大通道必须关死）
            os.remove(_hk16)
            _p997 = repo16 + "/strategies/st-C997.yaml"
            open(_p997, "w", encoding="utf-8").write(base_entry)
            _h2_16e = git_commit(repo16, ["strategies/st-C997.yaml"], "t16e round2 合规项")
            _tree16e = sh(["git", "-C", repo16, "ls-tree", "-r", "--name-only", "HEAD",
                           "--", "strategies/"], timeout=TMO["git"]).stdout or ""
            check("T16e round2 commit 只含合规项（round1 残留不静默入库）",
                  bool(_h2_16e) and "st-C997.yaml" in _tree16e and "st-C998.yaml" not in _tree16e
                  and "st-C996.yaml" not in _tree16e,
                  "commit=%s tree_has_C997=%s tree_has_C998=%s" % (
                      _h2_16e, "st-C997.yaml" in _tree16e, "st-C998.yaml" in _tree16e))
            # HEAD 移动后 commit 调用仍报失败 → git_commit 如实返回新头（不报失败、
            # 不 scoped reset——若误 reset，index=新头内容，回滚 checkout 后 scoped
            # porcelain 净 → 谎报 clean=True 而内容已落库，正是本修复要关死的谎报面）。
            # 沙盒实证本 git 版 post-commit 钩子失败不影响 commit exit code，故以
            # pre-commit 钩子内 amend 移动 HEAD 再 exit 1 模拟同一分支。
            _hk16b = repo16 + "/.git/hooks/pre-commit"
            open(_hk16b, "w", encoding="utf-8").write(
                "#!/bin/sh\ngit -C '%s' commit --amend --no-verify -m t16e-hook-landed "
                ">/dev/null 2>&1\nexit 1\n" % repo16)
            os.chmod(_hk16b, 0o755)
            _p996 = repo16 + "/strategies/st-C996.yaml"
            open(_p996, "w", encoding="utf-8").write(base_entry)
            _pre16h = (sh(["git", "-C", repo16, "rev-parse", "HEAD"],
                          timeout=TMO["git"]).stdout or "").strip()
            _h3_16e = git_commit(repo16, ["strategies/st-C996.yaml"], "t16e 钩子移 HEAD 后拒外层")
            _moved16h = (sh(["git", "-C", repo16, "rev-parse", "HEAD"],
                            timeout=TMO["git"]).stdout or "").strip()
            _in16e = sh(["git", "-C", repo16, "cat-file", "-e",
                         "HEAD:strategies/st-C996.yaml"], timeout=TMO["git"]).returncode == 0
            check("T16e HEAD 已移但 commit 调用报失败 → 返回新头（不误报失败误回滚已落库）",
                  bool(_h3_16e) and _moved16h != _pre16h and _h3_16e == _moved16h and _in16e,
                  "head=%s moved=%s 落库=%s" % (bool(_h3_16e), _moved16h != _pre16h, _in16e))
            os.remove(_hk16b)

            # T16f 回写 commit 的提交范围（20261103 红队 SIL 环修复·账实不符面）：
            # git add 只加本轮 paths 而 git commit 不带 paths → 提交**整个 index**，
            # 工作树内他人（并发 agent）已 staged 的改动被夹带进本「回写 commit」：
            # commit message（「回写 N 项（checker 全绿 exit 0）」）与 verdict_log 的
            # 「已回写 commit=<hash>」均宣称与实际内容不符，夹带件从未过 checker
            # （checker 只校验 strategies/）。失败路径反而是克制的（scoped reset
            # 只动本轮 paths）——成功/失败两路范围不对称。
            # 判据：①他人已 staged 的件不得出现在本轮 commit 内；②他人 staged 态
            # 保留（不被本轮 commit 吞掉）；③本轮无差异时幂等跳过、HEAD 不动
            # （整树 status 会因他者脏面误判「有差异」）；④提交面恰为本轮回写面。
            _of16 = repo16 + "/他人文件.txt"
            open(_of16, "w", encoding="utf-8").write("origin\n他人改动-未过checker\n")
            sh(["git", "-C", repo16, "add", "--", "他人文件.txt"], timeout=TMO["git"])
            _p996f = repo16 + "/strategies/st-C996f.yaml"
            open(_p996f, "w", encoding="utf-8").write(base_entry)
            _h4_16f = git_commit(repo16, ["strategies/st-C996f.yaml"], "t16f 回写 commit 范围")
            _show16f = (sh(["git", "-C", repo16, "-c", "core.quotepath=false", "show",
                            "--name-only", "--format=%H %s", _h4_16f or "HEAD"],
                           timeout=TMO["git"]).stdout or "")
            _files16f = [l.strip() for l in _show16f.splitlines()[1:] if l.strip()]
            _stg16f = [l.strip() for l in (sh(["git", "-C", repo16, "-c", "core.quotepath=false",
                                              "diff", "--cached", "--name-only"],
                                             timeout=TMO["git"]).stdout or "").splitlines()
                       if l.strip()]
            check("T16f 回写 commit 只含本轮回写面（他人已 staged 的改动不被夹带，且其 staged 态保留）",
                  bool(_h4_16f) and _files16f == ["strategies/st-C996f.yaml"]
                  and _stg16f == ["他人文件.txt"],
                  "commit=%s commit内文件=%s 余留staged=%s" % (_h4_16f, _files16f, _stg16f))
            _head16f = (sh(["git", "-C", repo16, "rev-parse", "HEAD"],
                           timeout=TMO["git"]).stdout or "").strip()
            _h5_16f = git_commit(repo16, ["strategies/st-C996f.yaml"], "t16f 本轮无差异")
            _head16f2 = (sh(["git", "-C", repo16, "rev-parse", "HEAD"],
                            timeout=TMO["git"]).stdout or "").strip()
            check("T16f 本轮无差异（仅他者脏面）→ 幂等跳过、HEAD 不动、他人 staged 态不动",
                  _h5_16f is None and _head16f == _head16f2 and _stg16f == ["他人文件.txt"],
                  "返回=%s HEAD动=%s 余留staged=%s" % (_h5_16f, _head16f != _head16f2, _stg16f))

        # T17 v1.3.4：红转绿后队列必须排干（writeback_error 残留钉死出队回归）。
        # 2026-11-01 实证（活体 st-C103 同构）：带错项在编辑成功的绿轮仍被
        # _dequeue 的带错守卫跳过 → commit 落库而项永驻队列、verdict_log 永缺
        # 「已回写」outcome，次轮起恒 idempotent-noop。修复=编辑成功即剥离残留错。
        # 前置态播种：a=活体旧残留错（checker-red 寄存重入队路径 v1.3.4 已剥离
        # 无残留，故按活体存量直接播种）；d=编辑异常留队项次轮修复后的红转绿。
        # 夹具：合成 af 仓（条目在场=编辑路径；仓级 git 身份供 git_commit）+
        # 新 wb_wt；真实 run_checker（合成 checker 绿 exit 0）。
        old_af17, old_base17, old_wt17 = CFG["af"], CFG["wb_base"], CFG["wb_wt"]
        CFG["af"] = tmp + "/af-syn17"
        os.makedirs(CFG["af"] + "/strategies", exist_ok=True)
        os.makedirs(CFG["af"] + "/ci", exist_ok=True)
        _e17 = ("id: st-C901\nname: t17夹具\ntier: C\nclaim: 夹具断言\nclaimed_value:\n"
                "  metric: \"（待投影）\"\n  direction: down\n  context: \"（待投影）\"\n"
                "sources: [S1]\nconsensus: {corpora: 1, cards: 1}\n"
                "experiment: {status: none, exp_id: \"-\", note: \"-\"}\n"
                "dsl_state: needs_syntax\nneeds_syntax_note: \"夹具待投影\"\n")
        open(CFG["af"] + "/strategies/st-C901.yaml", "w", encoding="utf-8").write(_e17)
        open(CFG["af"] + "/strategies/index.yaml", "w", encoding="utf-8").write(
            "version: 1\nentries:\n"
            "  - { id: st-C901, file: st-C901.yaml, tier: C, topic: t17, dsl_state: needs_syntax, rank: 997 }\n"
            "counts:\n  total: 1\n  tiers: {C: 1}\n  dsl_states: {needs_syntax: 1}\n")
        open(CFG["af"] + "/strategies/README.md", "w", encoding="utf-8").write("t17\n")
        open(CFG["af"] + "/ci/strategies_check.py", "w", encoding="utf-8").write(
            "raise SystemExit(0)\n")
        sh(["git", "-C", CFG["af"], "init", "-q"], timeout=30)
        sh(["git", "-C", CFG["af"], "config", "user.email", "sil-selftest@local"], timeout=30)
        sh(["git", "-C", CFG["af"], "config", "user.name", "sil-selftest"], timeout=30)
        sh(["git", "-C", CFG["af"], "add", "-A"], timeout=30)
        sh(["git", "-C", CFG["af"], "commit", "-q", "-m", "t17"], timeout=30)
        _br17 = sh(["git", "-C", CFG["af"], "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
        CFG["wb_base"] = (_br17.stdout or "").strip() or "master"
        CFG["wb_wt"] = tmp + "/af-wt-t17"

        def _t17_item():
            return {"exp_id": "EXP-17", "verdict": "inconclusive", "status": "inconclusive",
                    "note": "T17 夹具终裁", "target_cluster": "C901", "target_tier": "C",
                    "target_entry_id": "st-C901", "target_entry": "st-C901", "target_rank": 997}

        # T17a 残留错项绿轮排干（bug 主判据）：旧红轮残留错+条目在场+目标异于在库值
        # → 真实 checker 绿 → commit 落库且项出队、verdict_log 记「已回写 commit=…」
        stt17 = load_state()
        _it17 = _t17_item()
        _it17["writeback_error"] = "checker 红（exit=1，已回滚 clean=True）：旧轮残留"
        stt17["verdict_queue"] = [_it17]
        _log17 = len(stt17["verdict_log"])
        r17a = writeback_round(stt17, None)
        _wb_e17 = open(os.path.join(CFG["wb_wt"], "strategies", "st-C901.yaml"),
                       encoding="utf-8").read()
        check("T17a 残留错项绿轮：commit 落库+出队+verdict_log 记已回写",
              r17a.get("status") == "committed" and (r17a.get("commit") or "")
              and len(stt17["verdict_queue"]) == 0
              and len(stt17["verdict_log"]) == _log17 + 1
              and stt17["verdict_log"][-1]["outcome"].startswith("已回写 commit=")
              and "writeback_error" not in stt17["verdict_log"][-1]
              and 'status: inconclusive' in _wb_e17,
              json.dumps({"status": r17a.get("status"), "commit": r17a.get("commit"),
                          "q": len(stt17["verdict_queue"]),
                          "outcome": stt17["verdict_log"][-1]["outcome"][:40]},
                         ensure_ascii=False))
        # T17b 幂等轮排干（活体轮4同构）：残留错+目标已在库（上轮已 commit 落库）
        # → idempotent-noop 轮也必须出队记「已回写（幂等跳过）」（修复前永驻队列）
        stt17b = load_state()
        _it17b = _t17_item()
        _it17b["writeback_error"] = "checker 红（exit=1，已回滚 clean=True）：残留"
        stt17b["verdict_queue"] = [_it17b]
        _log17b = len(stt17b["verdict_log"])
        r17b = writeback_round(stt17b, None)
        check("T17b 幂等轮排干残留错项（verdict_log 补记已回写）",
              r17b.get("status") == "idempotent-noop"
              and len(stt17b["verdict_queue"]) == 0
              and len(stt17b["verdict_log"]) == _log17b + 1
              and stt17b["verdict_log"][-1]["outcome"] == "已回写（幂等跳过，无新 commit）"
              and "writeback_error" not in stt17b["verdict_log"][-1],
              json.dumps({"status": r17b.get("status"), "q": len(stt17b["verdict_queue"]),
                          "outcome": stt17b["verdict_log"][-1]["outcome"]},
                         ensure_ascii=False))
        # T17c 本轮编辑异常：新错留队重试语义不变（防修复扩得过宽误排干真失败项）
        open(os.path.join(CFG["wb_wt"], "strategies", "st-C902.yaml"), "w",
             encoding="utf-8").write("id: st-C902\nname: 无experiment键\n")  # 无 experiment 块
        stt17c = load_state()
        _it17c = _t17_item()
        _it17c.update({"target_entry_id": "st-C902", "target_entry": "st-C902"})
        stt17c["verdict_queue"] = [_it17c]
        _log17c = len(stt17c["verdict_log"])
        r17c = writeback_round(stt17c, None)
        check("T17c 本轮编辑异常留队重试（新错不被误剥离）",
              len(stt17c["verdict_queue"]) == 1
              and "未找到顶层 experiment" in (stt17c["verdict_queue"][0].get("writeback_error") or "")
              and len(stt17c["verdict_log"]) == _log17c,
              json.dumps({"q": len(stt17c["verdict_queue"]),
                          "err": (stt17c["verdict_queue"][0].get("writeback_error") or "")[:60]},
                         ensure_ascii=False))
        # T17d 异常轮→修复→绿轮排干：上轮异常残留错不得钉死本轮成功出队
        # （编辑异常留队路径的红转绿——残留错的第二条真实产生路径）
        with open(os.path.join(CFG["wb_wt"], "strategies", "st-C902.yaml"), "a",
                  encoding="utf-8") as f:
            f.write('experiment: {status: none, exp_id: "-", note: "-"}\n')
        r17d = writeback_round(stt17c, None)      # 同项同态：上轮带异常错留队
        check("T17d 异常轮后修复→绿轮 commit 排干+verdict_log 记已回写",
              r17d.get("status") == "committed" and (r17d.get("commit") or "")
              and len(stt17c["verdict_queue"]) == 0
              and len(stt17c["verdict_log"]) == _log17c + 1
              and stt17c["verdict_log"][-1]["outcome"].startswith("已回写 commit=")
              and "writeback_error" not in stt17c["verdict_log"][-1],
              json.dumps({"status": r17d.get("status"), "commit": r17d.get("commit"),
                          "q": len(stt17c["verdict_queue"]),
                          "outcome": stt17c["verdict_log"][-1]["outcome"][:40]},
                         ensure_ascii=False))
        CFG["af"], CFG["wb_base"], CFG["wb_wt"] = old_af17, old_base17, old_wt17

        # T18 RT-E12 真实性锚回归（红队 SIL 环修复：①只读门 ②keyed HMAC ③证据绑定）
        _k18 = _mirror_signing_key()
        check("T18a 签名密钥在位且 0600", os.path.isfile(MIRROR_KEY_PATH)
              and stat.S_IMODE(os.stat(MIRROR_KEY_PATH).st_mode) == 0o600,
              "%s mode=%o" % (MIRROR_KEY_PATH, stat.S_IMODE(os.stat(MIRROR_KEY_PATH).st_mode)))
        # T18b 合成镜像夹具：keyed 签名确定、≠旧无密钥口径（旧口径可被独立实现离线复算
        # =RT-E12 原始发现复现面；新口径无密钥复算必失配）。夹具密封：exp1_dir 同指
        # tmp（无 summary 件）→ 内容串联=订单集，独立复算与守护实现逐字对账。
        fm18 = tmp + "/mirror-e18"
        fo18 = fm18 + "/E1-T18-x"
        os.makedirs(fo18, exist_ok=True)
        open(fo18 + "/records.jsonl", "w", encoding="utf-8").write('{"status": "completed"}\n')
        om18, od18 = CFG["exp_mirror"], CFG["exp1_dir"]
        CFG["exp_mirror"] = fm18                      # exp_sources() 逐调用读 CFG（探针同构）
        CFG["exp1_dir"] = tmp
        s18a, s18b = exp_mirror_signatures(), exp_mirror_signatures()
        leg18 = exp_mirror_signatures(keyed=False)
        leg_re18 = sha256_text("\n".join(leg18["exp1"][1]))   # 独立 hashlib 复算（不复用守护代码）
        keyed_re18 = hmac.new(_k18, ("\n".join(leg18["exp1"][1])).encode("utf-8"),
                              hashlib.sha256).hexdigest()
        check("T18b keyed 签名确定且≠旧无密钥口径；旧口径=无密钥 sha（原发现复现）",
              s18a["exp1"][0] == s18b["exp1"][0] and s18a["exp1"][0] != leg18["exp1"][0]
              and leg18["exp1"][0] == leg_re18,
              "keyed=%s… legacy=%s… 独立复算=%s…" % (s18a["exp1"][0][:8], leg18["exp1"][0][:8],
                                                     leg_re18[:8]))
        check("T18c keyed 签名持密钥可独立复算（HMAC-SHA256 口径稳定，非混淆）",
              s18a["exp1"][0] == keyed_re18, "keyed=%s… 独立HMAC=%s…" % (s18a["exp1"][0][:8], keyed_re18[:8]))
        # T18d 只读门（v1.3.8 / RT-E85④ 构造性四态）：判据唯一＝findmnt OPTIONS 含 ro。
        # ①uid 可写夹具 → 拒用；②「顶层555+订单目录/文件仍可写」→ 拒用（RT-E12①回归：
        # 旧门只查顶层目录，同 uid 一次 chmod 555 即被判可信，644 订单文件可原地注入
        # 伪造行后门仍放行——2026-11-02 沙盒实证）；③**「先改后收权」（写入伪造内容后
        # 再把树内全收权：目录555+订单目录555+文件444）→ 仍须拒用**——旧门在此判
        # trusted=True＝旁路（权限位同 uid 可逆，门把已被伪造的镜像重新判可信并放进
        # 聚合，2026-11-02 沙盒实证）；④真机制只读（OPTIONS 含 ro）→ 可信。
        src18 = {"name": "exp1", "dir": fm18, "glob": "E1-*"}
        rec18 = fo18 + "/records.jsonl"
        g18w = mirror_source_ro_gate(src18)
        os.chmod(fm18, 0o555)                      # 一次 chmod 555：仅顶层收权，树内仍可写
        g18atk = mirror_source_ro_gate(src18)
        forged18 = False                           # 攻击面实证：目录555下订单文件可原地注入
        try:
            with open(rec18, "a", encoding="utf-8") as f:
                f.write('{"gate":"ok","forged_by":"selftest-t18d"}\n')
            forged18 = True
        except OSError:
            pass
        g18atk2 = mirror_source_ro_gate(src18)     # 注入后门判定须仍拒用
        os.chmod(fo18, 0o555)                      # 「先改后收权」：伪造写入后再收权
        os.chmod(rec18, 0o444)
        g18r = mirror_source_ro_gate(src18)        # 树内全收权（findmnt=rw）→ 仍须拒用（RT-E85④）
        g18ro = mirror_source_ro_gate(src18, mount_opts=["ro", "relatime"])   # 真机制只读 → 可信
        g18rw = mirror_source_ro_gate(src18, mount_opts=["rw", "relatime"])   # rw 挂载 → 拒用
        g18no = _mirror_ro_verdict(None, "findmnt 不可用", fm18)              # 无读数 → fail-closed
        os.chmod(rec18, 0o644)                     # 还原夹具权限（内容还原需写权限）
        with open(rec18, encoding="utf-8") as f:   # 还原夹具内容（剥掉伪造行）
            body18 = f.read()
        with open(rec18, "w", encoding="utf-8") as f:
            f.write(body18.split('{"gate":"ok"')[0])
        os.chmod(fo18, 0o755)
        os.chmod(fm18, 0o755)
        check("T18d 只读门（RT-E85④）：可写→拒用；顶层555+文件644（含原地注入后）→拒用；"
              "「先改后收权」（伪造写入+树内全收权）→仍拒用（chmod 收权不构成机制性只读）",
              g18w[0] is False and g18atk[0] is False and forged18
              and g18atk2[0] is False and g18r[0] is False,
              "writable:%s | dir555+file644:%s | 注入成功:%s 注入后:%s | 收权后:%s"
              % (g18w[1][:30], g18atk[1][:38], forged18, g18atk2[1][:38], g18r[1][:56]))
        check("T18d2 只读门：findmnt OPTIONS 含 ro → 可信；rw → 拒用；无 findmnt 读数 → 拒用"
              "（fail-closed，不可证即不可信）",
              g18ro[0] is True and g18rw[0] is False and g18no[0] is False,
              "ro:%s | rw:%s | 无读数:%s" % (g18ro[1][:34], g18rw[1][:40], g18no[1][:44]))
        # T18d3 逃逸符号链接面（2026-11-02 沙盒实证复现）：ro 挂载只保护本挂载点内的
        # inode——树内符号链接指向树外时，守护订单枚举与聚合器都穿过该链接读**树外**
        # 内容（不受 ro 保护、可随时原地改写/整体换掉）。旧门对符号链接目录零设防：
        # E1-* 订单目录整体换成符号链接 → 门绿 + 守护自己穿链读到攻击者记录（伪造
        # 终态单直通聚合器）。判据：①findmnt=ro 且树内有逃逸链接 → 仍须拒用；
        # ②守护枚举不得穿链（订单集为空）；③树内链接（目标仍在树内）→ 可信（不误拒）。
        fml18 = tmp + "/mirror-e18-link"
        os.makedirs(fml18, exist_ok=True)
        out18 = tmp + "/outside-e18"
        os.makedirs(out18 + "/fake", exist_ok=True)
        with open(out18 + "/fake/records.jsonl", "w", encoding="utf-8") as f:
            f.write('{"status": "completed", "order": "E1-LINK"}\n')
        os.chmod(out18 + "/fake/records.jsonl", 0o644)   # 树外内容 uid 可原地改写
        os.symlink(out18 + "/fake", fml18 + "/E1-LINK")   # 订单目录整体换成树外符号链接
        g18esc = mirror_source_ro_gate({"name": "exp1", "dir": fml18, "glob": "E1-*"},
                                       mount_opts=["ro", "relatime"])   # ro 也须拒用
        ord18 = _completed_orders_in(fml18, "E1-*")       # 枚举不得穿链读到攻击者记录
        # 变体：订单目录本身是真实目录，但订单目录内的 records.jsonl 是树外符号链接
        fmr18 = tmp + "/mirror-e18-link2"
        os.makedirs(fmr18 + "/E1-LINK2", exist_ok=True)   # 订单目录是真实目录（记录文件才是链接）
        with open(out18 + "/fake2.jsonl", "w", encoding="utf-8") as f:
            f.write('{"status": "completed", "order": "E1-LINK2"}\n')
        os.chmod(out18 + "/fake2.jsonl", 0o644)
        os.symlink(out18 + "/fake2.jsonl", fmr18 + "/E1-LINK2/records.jsonl")
        g18esc2 = mirror_source_ro_gate({"name": "exp1", "dir": fmr18, "glob": "E1-*"},
                                        mount_opts=["ro", "relatime"])   # ro 也须拒用
        ord18b = _completed_orders_in(fmr18, "E1-*")      # 记录文件是链接 → 不读
        fmi18 = tmp + "/mirror-e18-intra"
        os.makedirs(fmi18 + "/E1-INTRA", exist_ok=True)
        os.makedirs(fmi18 + "/_real", exist_ok=True)
        with open(fmi18 + "/_real/records.jsonl", "w", encoding="utf-8") as f:
            f.write('{"status": "completed", "order": "E1-INTRA"}\n')
        os.symlink(fmi18 + "/_real/records.jsonl",
                   fmi18 + "/E1-INTRA/records.jsonl")     # 树内链接（目标仍在树内）
        g18intra = mirror_source_ro_gate({"name": "exp1", "dir": fmi18, "glob": "E1-*"},
                                         mount_opts=["ro", "relatime"])
        check("T18d3 逃逸符号链接：ro 挂载 + 树外链接（订单目录/记录文件两种形态）→ 拒用"
              "（fail-closed）；守护枚举不穿链；树内链接 → 可信（不误拒）",
              g18esc[0] is False and g18esc2[0] is False and ord18 == []
              and ord18b == [] and g18intra[0] is True,
              "逃逸(目录):%s | 逃逸(记录文件):%s | 枚举读到:%s/%s | 树内链接:%s"
              % (g18esc[1][:44], g18esc2[1][:44], ord18, ord18b, g18intra[1][:36]))
        # T18d4 判据读出通道换件面（v1.3.14，2026-11-03 确证发现修复回归）：RT-E85④
        # 的信任锚是 kernel 挂载态读数，而测量工具 findmnt 此前按**裸名走进程 PATH**
        # 解析——在役守护 PATH 前置 ~/bin、~/.local/bin、~/.cargo/bin 三个同 uid 可写
        # 目录，同 uid 落一个恒打印 ro 的假件即伪造读数（「先放假件后放伪造镜像」与
        # 「先改后收权」同构）。判据：①_system_tool 按 _CS_PATH 解析出**绝对路径**且
        # 落在系统工具目录内；②PATH 前置假件后解析结果不变（与 PATH 无关）；③
        # PATH 前置恒打印 ro 的假 findmnt 后，判据读数不含假件标记、门仍拒用
        # （假件若被采纳必 trusted=True 且 how 含标记——回归即红）；④解析不到的
        # 件 → None（无读数 → fail-closed 腿在位，真 findmnt 读数仍在位）。
        fakebin18 = tmp + "/fakebin-e18"
        os.makedirs(fakebin18, exist_ok=True)
        _fake_marker18 = "forged-by-selftest-t18d4"
        with open(fakebin18 + "/findmnt", "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "ro,relatime,%s"\n' % _fake_marker18)
        os.chmod(fakebin18 + "/findmnt", 0o755)
        _p18 = os.environ.get("PATH", "")
        sys_path18 = _system_tool("findmnt")
        try:
            os.environ["PATH"] = fakebin18 + ":" + _p18    # 假件按 POSIX 解析序胜出的姿势
            hij_path18 = _system_tool("findmnt")
            g18hij = mirror_source_ro_gate(src18)          # src18=fm18（真 rw 挂载树）
        finally:
            os.environ["PATH"] = _p18                      # 还原，不得污染后续用例
        _csdirs18 = set(_cs_path().split(":"))
        check("T18d4 读出通道换件面（v1.3.14）：findmnt 按 _CS_PATH 解析绝对路径、"
              "不消费进程 PATH——PATH 前置恒打印 ro 的假 findmnt：解析结果不变、判据"
              "读数不含假件标记、门仍拒用（假件被采纳=trusted=True=回归即红）",
              os.path.isabs(sys_path18 or "") and os.path.dirname(sys_path18) in _csdirs18
              and hij_path18 == sys_path18 and g18hij[0] is False
              and _fake_marker18 not in g18hij[1],
              "sys=%s | PATH前置假件后=%s | 判据=%s"
              % (sys_path18, hij_path18, g18hij[1][:60]))
        check("T18d4b 解析不到的系统工具 → None（fail-closed 腿在位）；真 findmnt 读数仍在位",
              _system_tool("findmnt-自检不存在件-xyz") is None
              and _mirror_mount_options(fm18)[0] is not None,
              "缺席件解析=%s | 真 findmnt=%s"
              % (_system_tool("findmnt-自检不存在件-xyz"),
                 (_mirror_mount_options(fm18)[1] or "")[:46]))
        # ---- RT-E85② T18e：密钥出域停摆语义负控（P1-设计 K9；只增不改既有判据）----
        # e1 取钥失败 → SigningUnavailable（绝不自生成/不降级）；e2 失败后零钥文件
        # 新增写（本机零钥文件面）；e3 指纹对账纯函数（真值 True/篡改 False）；
        # e4 openbao 模式+SIL_MIRROR_KEY 注入 → 拒启动（K5，P0-盘点 R2 收口）；
        # e5 停摆轮 save_state 四段冻结（四段与旧封条原样保留、key_status 停摆态在册
        # ——probe ⑩ 消费点）。判据=台账:747 RT-E88 口径：停摆必须可判定红、不静默。
        _sv18e = (SIL_KEY_SRC, SIL_KEY_EXPECTED_SHA256, MIRROR_KEY_PATH,
                  _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP)
        _key18e = os.path.join(tmp, "rt85-e-signing.key")
        _e5key = os.urandom(32).hex().encode("ascii")
        _e5_halted = False
        try:
            # e1/e2：openbao + fetch 失败（monkeypatch 模拟 unreachable）→ 抛停摆、
            # 且全程不写任何钥文件（夹具路径保持不存在）
            SIL_KEY_SRC = "openbao"
            MIRROR_KEY_PATH = _key18e
            _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
            os.environ.pop("SIL_MIRROR_KEY", None)
            _fetch18 = _openbao_fetch_key
            globals()["_openbao_fetch_key"] = \
                lambda: (None, "unreachable", "rt85-selftest-drill")
            _e1ok = _e2ok = False
            try:
                _mirror_hmac("t18e-probe")
            except SigningUnavailable:
                _e1ok = (_KEY_STATE == "failed:unreachable")
            _e2ok = not os.path.exists(_key18e)      # 绝不自生成落盘
            globals()["_openbao_fetch_key"] = _fetch18
            # e3：指纹对账纯函数——夹具钥值（非预期指纹）必须 False；把预期指纹
            # 重设为该值后必须 True（对账口径=钥文本 sha256，同生产 fetch 判）
            _e3a = not _key_fp_ok(_e5key)
            globals()["SIL_KEY_EXPECTED_SHA256"] = hashlib.sha256(_e5key).hexdigest()
            _e3b = _key_fp_ok(_e5key)
            # e4：openbao 模式 + SIL_MIRROR_KEY env 注入 → 拒启动（SystemExit）
            os.environ["SIL_MIRROR_KEY"] = "rt85-drill-override"
            _e4ok = False
            try:
                _mirror_signing_key()
            except SystemExit:
                _e4ok = True
            except Exception:
                _e4ok = False
            os.environ.pop("SIL_MIRROR_KEY", None)
            globals()["SIL_KEY_EXPECTED_SHA256"] = _sv18e[1]
            # e5：停摆轮 save_state 四段冻结——test 模式先签旧封条，切 openbao 停摆
            # 态后再 save_state：四段与封条原样保留、key_status 记停摆（probe ⑩ 消费）
            MIRROR_KEY_PATH = os.path.join(tmp, "rt85-e5-signing.key")
            SIL_KEY_SRC = "test"
            _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
            CFG["state"] = tmp + "/rt85-e5-loop-state.json"
            CFG["metrics"] = tmp + "/rt85-e5-metrics.json"
            st_e5 = {"verdict_queue": [{"q": 1}], "auto_create_retry": [],
                     "projection_todos": [], "verdict_log": [], "rounds": 1,
                     "counters": {"triggered": 0, "noop": 0, "candidates_queued": 0,
                                  "verdicts_queued": 0, "commits": 0, "rollbacks": 0,
                                  "errors": 0}}
            save_state(st_e5)                        # test 钥签发旧封条
            _se5 = json.load(open(CFG["state"], encoding="utf-8"))
            _secs5_before = {k: _se5.get(k) for k in STATE_SEAL_SECTIONS}
            _seal5_before = dict(_se5.get("state_seal") or {})
            SIL_KEY_SRC = "openbao"                  # 切停摆（fetch 保持 monkeypatch）
            globals()["_openbao_fetch_key"] = \
                lambda: (None, "unreachable", "rt85-selftest-drill")
            _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
            st_e5["rounds"] = 2                      # 非四段变更照写
            save_state(st_e5)
            _se5b = json.load(open(CFG["state"], encoding="utf-8"))
            _secs5_after = {k: _se5b.get(k) for k in STATE_SEAL_SECTIONS}
            _e5_halted = (_secs5_after == _secs5_before
                          and _se5b.get("state_seal") == _seal5_before
                          and (_se5b.get("key_status") or {}).get("state") == "failed:unreachable"
                          and _se5b["state_seal"]["hmac"] == _seal5_before.get("hmac"))
        finally:
            globals()["_openbao_fetch_key"] = _fetch18
            os.environ.pop("SIL_MIRROR_KEY", None)
            (SIL_KEY_SRC, SIL_KEY_EXPECTED_SHA256, MIRROR_KEY_PATH,
             _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP) = _sv18e
            CFG["state"] = tmp + "/loop-state.json"      # e5 沙盒面还原（防污染后续 T18g/T19）
            CFG["metrics"] = tmp + "/self-improve.json"
        check("T18e1 密钥出域（RT-E85②）：取钥失败 → SigningUnavailable 停摆"
              "（_KEY_STATE=failed:<分类>），绝不自生成换钥",
              _e1ok and _e2ok,
              "e1=%s e2(零钥文件新增写)=%s state=%s" % (_e1ok, _e2ok, _KEY_STATE))
        check("T18e3 密钥出域：指纹对账纯函数——非预期值拒用（False）/预期值通过（True）",
              _e3a and _e3b, "篡改值拒=%s 预期值过=%s" % (_e3a, _e3b))
        check("T18e4 密钥出域：openbao 模式 + SIL_MIRROR_KEY env 注入 → 拒启动"
              "（K5：同 uid env 换钥面收口，P0-盘点 R2）",
              _e4ok, "SystemExit=%s" % _e4ok)
        check("T18e5 密钥出域：停摆轮 save_state 四段冻结——四段与旧封条逐字保留、"
              "key_status 记停摆（probe ⑩ 同步点，不重签不降级）",
              _e5_halted,
              "四段冻结+旧封条保留+key_status=failed:unreachable → %s" % _e5_halted)
        # T18e6（H2 修法(2)(4)，P4-联评）：停摆世 load_state **不清四段**——e5 落盘
        # 件（四段有内容+旧封条在）上切停摆态读盘：封条复算不可得 ⇒ 四段必须原样
        # 保留（隔离=销毁语义，停摆触发即自伤链）；红=state_seal_ok=False 在册。
        # 对照腿：非停摆的验签失败仍走隔离（用被篡改内容验证原语义未放宽）。
        _sv6 = dict(CFG)
        try:
            CFG["state"] = tmp + "/rt85-e5-loop-state.json"   # e5 落盘件复用
            _pre6 = json.load(open(CFG["state"], encoding="utf-8"))
            SIL_KEY_SRC = "openbao"
            os.environ.pop("SIL_MIRROR_KEY", None)
            _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
            st6 = load_state()
            _e6_keep = all(st6.get(kk) == _pre6.get(kk) for kk in STATE_SEAL_SECTIONS)
            _e6_red = (st6.get("state_seal_ok") is False)
            # 对照腿：真篡改内容（非停摆）仍须隔离——原 v1.3.9 语义未放宽
            SIL_KEY_SRC = "test"
            MIRROR_KEY_PATH = tmp + "/rt85-e6-signing.key"
            _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP = None, "unfetched", "", ""
            st6b = json.load(open(CFG["state"], encoding="utf-8"))
            st6b["verdict_queue"] = [{"forged": "t18e6"}]
            json.dump(st6b, open(CFG["state"], "w", encoding="utf-8"))
            st6c = load_state()
            _e6_ctrl = (st6c.get("verdict_queue") == []
                        and len(st6c.get("quarantine_log") or []) >= 1)
        finally:
            CFG.update(_sv6)
            (SIL_KEY_SRC, SIL_KEY_EXPECTED_SHA256, MIRROR_KEY_PATH,
             _KEY_CACHE, _KEY_STATE, _KEY_ERR, _KEY_FP) = _sv18e
        check("T18e6 密钥出域：停摆世 load_state 四段保留不隔离（不消费也不销毁，"
              "state_seal_ok=False 在册）；对照腿：真篡改仍隔离（原语义不放宽）",
              _e6_keep and _e6_red and _e6_ctrl,
              "停摆保留=%s 红=%s 篡改仍隔离=%s" % (_e6_keep, _e6_red, _e6_ctrl))
        # T18e 迁移（零漂移）：存值=旧口径复算 → 采纳 keyed 基线且不算新终态单
        # （changed 只看夹具源 exp1；真实 exp2 无存值属首轮建基线语义，不入判据）
        st18 = {"exp_mirror_sigs": {"exp1": leg18["exp1"][0]}}
        stored18 = _migrate_mirror_sig_scheme(st18, s18a)
        changed18 = stored18.get("exp1") != s18a["exp1"][0]
        check("T18e 迁移零漂移：旧基线采纳为 keyed，夹具源不算新终态单",
              stored18["exp1"] == s18a["exp1"][0] and not changed18,
              "adopted=%s changed=%s" % (stored18["exp1"][:8], changed18))
        # T18f 迁移（漂移）：存值≠旧口径复算 → 不静默采纳，维持 changed（告警路径）
        st18b = {"exp_mirror_sigs": {"exp1": "0" * 64}}
        stored18b = _migrate_mirror_sig_scheme(st18b, s18a)
        changed18b = stored18b.get("exp1") != s18a["exp1"][0]
        check("T18f 迁移漂移：不采纳、夹具源维持 changed",
              stored18b["exp1"] == "0" * 64 and changed18b,
              "kept=%s… changed=%s" % (stored18b["exp1"][:8], changed18b))
        CFG["exp_mirror"], CFG["exp1_dir"] = om18, od18

        # T18g v1.3.7/v1.3.9 终裁证据门（RT-E12③ checker 侧回归）：零证据伪 confirmed
        # （2026-11-02 沙盒实证 de65bcf 的注入形状）不得入回写计划——缺锚/异版
        # 聚合器/未知源同拒；全锚+对账+守护封条放行；非终裁态（inconclusive/pending）
        # 与 v1.3.5 前旧件语义不受门影响。DRY 下跑：plan 只含放行项，绝不碰 git。
        # v1.3.9：门加「守护封条验签」+「来源镜像只读门复判」两道**不可自算**的锚
        # ——夹具件由守护自己签发封条走正例（seal_verdict_item）；来源只读门注入
        # 「ro 挂载读数」（生产调用点一律不传 mount_opts → 走真实 findmnt）。
        _agg18 = tmp + "/agg-exp1-t18g.py"
        open(_agg18, "w", encoding="utf-8").write("# t18g aggregator fixture\n")
        _oe1 = CFG["b_exp1"]
        CFG["b_exp1"] = _agg18                     # 夹具聚合器（对账正例锚定其 sha）
        _sha18 = sha256_bytes(open(_agg18, "rb").read())
        _ro_gate18 = globals()["mirror_source_ro_gate"]

        def _ro_stub18(src, mount_opts=None):
            """selftest 夹具：来源源只读门注入「ro 挂载读数」（生产不传该参）。"""
            try:
                return _ro_gate18(src, mount_opts=["ro"])
            except TypeError:
                return (True, "selftest 夹具：ro 挂载读数注入")

        def _t18g(status, ev, seal=False):
            it = {"exp_id": "EXP-T18G", "verdict": status, "status": status,
                  "note": "T18g 夹具终裁", "target_entry_id": "st-C989",
                  "target_cluster": "C989", "target_tier": "A"}
            if ev is not None:
                it["evidence"] = ev
            if seal:
                seal_verdict_item(it)              # 守护自己签发封条（③段同款）
            return it

        _ev18 = {"summary": tmp + "/exp-out/exp1-aggregate-summary.json",
                 "mirror_sig": "ab" * 32, "aggregator_sha": _sha18,
                 "summary_sha": "cd" * 32, "n_terminal": 3}
        q18 = [_t18g("confirmed", None),                                  # 零证据（原发现复现面）
               _t18g("confirmed", {"mirror_sig": "ab" * 32}),             # 残锚（缺两 sha）
               _t18g("confirmed", dict(_ev18, aggregator_sha="0" * 64), seal=True),  # 异版聚合器
               _t18g("refuted", dict(_ev18, summary=tmp + "/exp9.json"), seal=True),  # 未知源无从对账
               _t18g("confirmed", dict(_ev18), seal=True),                # 全锚+对账+封条 → 放行
               _t18g("inconclusive", None)]                               # 非终裁 → 门不适用
        globals()["mirror_source_ro_gate"] = _ro_stub18
        CFG["dry"] = True
        globals()["DRY"] = True
        r18g = writeback_round({"verdict_queue": q18, "projection_todos": []}, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        CFG["b_exp1"] = _oe1
        globals()["mirror_source_ro_gate"] = _ro_gate18
        _p18 = r18g.get("plan") or []
        check("T18g 终裁证据门：零证据/残锚/异版聚合器/未知源 confirmed·refuted 拒入计划，"
              "全锚+对账+守护封条放行，inconclusive 不适用",
              r18g.get("status") == "dry-run" and len(_p18) == 2
              and all(q18[i].get("writeback_error") for i in range(4))
              and "无 evidence" in (q18[0].get("writeback_error") or "")
              and "缺合法锚" in (q18[1].get("writeback_error") or "")
              and "异版聚合器" in (q18[2].get("writeback_error") or "")
              and "非任何已知实验源" in (q18[3].get("writeback_error") or "")
              and not q18[4].get("writeback_error") and not q18[5].get("writeback_error")
              and {p["entry"] for p in _p18} == {"st-C989"},
              json.dumps({"status": r18g.get("status"), "plan": len(_p18),
                          "errs": [bool(q18[i].get("writeback_error")) for i in range(6)]},
                         ensure_ascii=False))

        # T19 RT-E12③ 终裁证据门加固回归（红队 SIL 环修复批 2026-11-02：伪三锚
        # confirmed 经真 checker 全绿入库 e21f115 —— 台账 RT-E86 拦截②③）：
        #   T19a 伪三锚（捏造 mirror_sig/summary_sha + 真实 aggregator_sha）→ 门拒
        #        （无守护封条；攻击者无密钥不可自算）——本发现的直接复现面；
        #   T19b 守护签发的合法终裁（封条在）→ 放行（正例对照，防门变「全拒」）；
        #   T19c 封条与条目内容不一致（改 status/note 沿用旧封条）→ 验签失败拒；
        #   T19d 来源镜像只读门拒用时（真实门 + 可写夹具目录）→ 合法封条终裁
        #        仍拒（产腿停摆期伪终裁无路可入；该腿不依赖密钥）；
        #   T19e 状态面封条钉（台账拦截②）：签发件验签通过；注入伪终裁项（不重签）
        #        → 验签失败 → 该项隔离、不入回写面 + quarantine_log 留痕；
        #   T19f 投影草稿携终裁态 → 拒写（留队带 writeback_error）。
        # v1.3.12（2026-11-03 轮4 红队确证发现：verdict_log 段未封条⇒封条被绕过）：
        #   T19g 注入 verdict_log（其余三段未动）→ 面级封条验签失败 → 四段隔离 →
        #        日志不得作重入队来源 → 伪条目不入裁决队列/不入回写计划；
        #   T19g2 正例对照：面级封条在 → 验签通过、日志段不隔离、旧语义恢复路径
        #        仍可用（合法件不误伤）。
        #   T15d2 复制点自证来源：无守护封条的日志条目（注入件）→ 不得复活。
        def _t19_forged():
            """攻击者伪造的终裁项：三锚逐字全对（真实聚合器 sha + 捏造 hex）。"""
            return {"exp_id": "EXP-RT", "verdict": "confirmed", "status": "confirmed",
                    "note": "伪确证（捏造 mirror_sig/summary_sha + 真实 aggregator_sha）",
                    "target_entry_id": "st-C997", "target_cluster": "C997",
                    "target_tier": "A",
                    "evidence": {"summary": tmp + "/exp-out/exp1-aggregate-summary.json",
                                 "mirror_sig": "a3" * 32, "aggregator_sha": _sha18,
                                 "summary_sha": "b7" * 32, "n_terminal": 3}}

        CFG["b_exp1"] = _agg18                     # 夹具聚合器（_ev18 的 aggregator_sha 锚定它）
        globals()["mirror_source_ro_gate"] = _ro_stub18
        CFG["dry"] = True
        globals()["DRY"] = True
        _f19 = _t19_forged()
        _leg19 = _t18g("confirmed", dict(_ev18), seal=True)
        _leg19["target_entry_id"] = _leg19["target_entry"] = "st-C988"
        _leg19["target_cluster"] = "C988"
        seal_verdict_item(_leg19)                    # 改字段后重签（守护自产件语义）
        _tam19 = _t18g("confirmed", dict(_ev18), seal=True)
        _tam19["note"] = "签发后被改写的 note"          # 封条与内容不一致
        _tam19["target_entry_id"] = _tam19["target_entry"] = "st-C986"
        r19 = writeback_round({"verdict_queue": [_f19, _leg19, _tam19],
                                "projection_todos": []}, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        _p19 = r19.get("plan") or []
        check("T19a 伪三锚终裁（真实 aggregator_sha + 捏造 hex）不得入回写计划——"
              "无守护封条，攻击者不可自算",
              "无守护封条" in (_f19.get("writeback_error") or "")
              and not [p for p in _p19 if p.get("entry") == "st-C997"],
              json.dumps({"err": (_f19.get("writeback_error") or "")[:70],
                          "plan": _p19}, ensure_ascii=False))
        check("T19b 守护签发的合法终裁（封条在）仍放行（正例对照，防门变全拒）",
              not _leg19.get("writeback_error")
              and [p.get("entry") for p in _p19 if p.get("entry") == "st-C988"],
              json.dumps({"err": (_leg19.get("writeback_error") or "")[:70],
                          "plan": _p19}, ensure_ascii=False))
        check("T19c 封条与条目内容不一致（改 note）→ 验签失败拒入计划",
              "验签失败" in (_tam19.get("writeback_error") or "")
              and not [p for p in _p19 if p.get("entry") == "st-C986"],
              json.dumps({"err": (_tam19.get("writeback_error") or "")[:70]},
                         ensure_ascii=False))
        # T19d 来源镜像只读门拒用（真实门 + 可写夹具目录）→ 合法封条终裁仍拒
        _mir19 = tmp + "/mirror-t19d"
        os.makedirs(_mir19, exist_ok=True)
        _om19, _om219 = CFG["exp_mirror"], CFG["exp_mirror2"]
        CFG["exp_mirror"], CFG["exp_mirror2"] = _mir19, _mir19
        globals()["mirror_source_ro_gate"] = _ro_gate18      # 恢复真实门（不注入 ro）
        _leg19b = _t18g("confirmed", dict(_ev18), seal=True)
        CFG["dry"] = True
        globals()["DRY"] = True
        r19d = writeback_round({"verdict_queue": [_leg19b], "projection_todos": []}, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        CFG["exp_mirror"], CFG["exp_mirror2"] = _om19, _om219
        globals()["mirror_source_ro_gate"] = _ro_gate18
        check("T19d 来源镜像只读门拒用时（产腿停摆期）合法封条终裁亦拒——"
              "无可信终态单即不得落库（该腿不依赖密钥）",
              "镜像只读门当前拒用" in (_leg19b.get("writeback_error") or "")
              and not (r19d.get("plan") or []),
              json.dumps({"err": (_leg19b.get("writeback_error") or "")[:90]},
                         ensure_ascii=False))
        # T19e 状态面封条钉（台账拦截②）：签发件验签通过；注入伪终裁项 → 隔离
        # v1.3.12：封条覆盖四段（含 verdict_log），夹具须把四段都置齐——否则
        # 签发时的载荷与 load_state 读盘后的载荷不同（缺段补默认）→ 封条自伤。
        _st19 = {"verdict_queue": [], "auto_create_retry": [], "projection_todos": [],
                 "verdict_log": []}
        seal_state(_st19)
        _sp19 = tmp + "/state-t19e.json"
        with open(_sp19, "w", encoding="utf-8") as f:
            json.dump(_st19, f, ensure_ascii=False)
        _os19 = CFG["state"]
        CFG["state"] = _sp19
        _ld19 = load_state()
        _atk19 = json.load(open(_sp19, encoding="utf-8"))
        _atk19["verdict_queue"] = [_t19_forged()]      # 攻击者改状态面（无密钥不能重签）
        with open(_sp19, "w", encoding="utf-8") as f:
            json.dump(_atk19, f, ensure_ascii=False)
        _ld19b = load_state()
        CFG["state"] = _os19
        check("T19e 状态面封条钉：签发件验签通过；注入伪终裁项 → 验签失败 → 隔离"
              "（不入回写面）+ quarantine_log 留痕",
              _ld19.get("state_seal_ok") is True
              and _ld19b.get("state_seal_ok") is False
              and len(_ld19b.get("verdict_queue") or []) == 0
              and len(_ld19b.get("quarantine_log") or []) == 1
              and (_ld19b.get("quarantine_log") or [{}])[0].get("n") == 1,
              json.dumps({"ok": _ld19.get("state_seal_ok"),
                          "tampered_ok": _ld19b.get("state_seal_ok"),
                          "q": len(_ld19b.get("verdict_queue") or []),
                          "quarantine_n": len(_ld19b.get("quarantine_log") or [])},
                         ensure_ascii=False))
        # T19f 投影草稿携终裁态 → 拒写（旁路终裁证据面的等价通道）
        _proj19 = {"entry_id": "st-C995", "entry_draft": {
            "id": "st-C995", "name": "投影夹具", "tier": "A", "claim": "夹具",
            "sources": ["S1"], "consensus": {"corpora": 1, "cards": 1},
            "experiment": {"status": "confirmed", "exp_id": "EXP-RT", "note": "伪确证"},
            "dsl_state": "not_applicable"}, "cluster_id": "C995"}
        CFG["dry"] = True
        globals()["DRY"] = True
        r19f = writeback_round({"verdict_queue": [], "projection_todos": [_proj19]}, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        check("T19f 投影草稿携终裁态（confirmed）→ 拒写、不入回写面、留队带错",
              "投影草稿携终裁态" in (_proj19.get("writeback_error") or "")
              and not (r19f.get("plan") or []),
              json.dumps({"err": (_proj19.get("writeback_error") or "")[:80],
                          "plan": r19f.get("plan")}, ensure_ascii=False))
        # T19g v1.3.12（2026-11-03 轮4 红队确证发现修复回归）：**verdict_log 段
        # 未在封条覆盖内 ⇒ 状态面封条被绕过**：攻击者只注入 verdict_log（其余三段
        # 一字未动）→ 面级封条验签通过 → 重入队扫描（验签**之后**）把伪造条目搬进
        # verdict_queue → 非终裁态零证据要求 → 伪条目经真 checker 全绿入库 commit。
        # 修复回归：注入 → 面级封条验签失败 → 四段隔离（fail-closed）→ 日志不得
        # 作重入队来源 → 伪条目不入裁决队列、不入回写计划。
        _st19g = {"verdict_queue": [], "auto_create_retry": [], "projection_todos": [],
                  "verdict_log": []}
        seal_state(_st19g)
        _sp19g = tmp + "/state-t19g.json"
        with open(_sp19g, "w", encoding="utf-8") as f:
            json.dump(_st19g, f, ensure_ascii=False)
        _os19g = CFG["state"]
        CFG["state"] = _sp19g
        _atk19g = json.load(open(_sp19g, encoding="utf-8"))
        _atk19g["verdict_log"] = [{
            "ts": "2026-11-03 00:00:00", "exp_id": "EXP-EVIL", "verdict": "inconclusive",
            "status": "inconclusive", "note": "【注入】零证据伪裁决",
            "target_cluster": "C999", "target_tier": "C", "target_entry_id": "st-C998",
            "target_rank": 998,
            "entry_material": {"name": "注入条目", "claim": "【注入】伪断言",
                               "sources": ["-"], "consensus": {"corpora": 1, "cards": 1}},
            "evidence": {},
            "outcome": "自动建条目尝试 1 次即止：checker 红 exit=1 已回滚 clean=False（注入伪造）"}]
        with open(_sp19g, "w", encoding="utf-8") as f:
            json.dump(_atk19g, f, ensure_ascii=False)
        _ld19g = load_state()
        globals()["DRY"] = False
        _n19g = _reenqueue_parked_auto_creates(_ld19g)
        CFG["dry"] = True
        globals()["DRY"] = True
        _r19g = writeback_round(_ld19g, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        CFG["state"] = _os19g
        check("T19g verdict_log 注入（其余三段未动）→ 面级封条验签失败 → 四段隔离 → "
              "日志不得作重入队来源 → 伪条目不入裁决队列/不入回写计划（v1.3.12）",
              _ld19g.get("state_seal_ok") is False
              and len(_ld19g.get("verdict_log") or []) == 0
              and _n19g == 0
              and len(_ld19g.get("verdict_queue") or []) == 0
              and not (_r19g.get("plan") or []),
              json.dumps({"seal_ok": _ld19g.get("state_seal_ok"),
                          "log_n": len(_ld19g.get("verdict_log") or []),
                          "reenq": _n19g, "q": len(_ld19g.get("verdict_queue") or []),
                          "plan": _r19g.get("plan"),
                          "quarantine": len(_ld19g.get("quarantine_log") or [])},
                         ensure_ascii=False))
        # T19g2 正例对照（防门变「全拒」）：守护自签发的状态面（面级封条在）→ 验签
        # 通过、verdict_log 段**不被隔离**（合法日志件不误伤）、旧语义一次性恢复
        # 路径仍可用（带封条的日志条目仍能复活进裁决队列）。
        _st19g2 = {"verdict_queue": [], "auto_create_retry": [], "projection_todos": [],
                   "verdict_log": []}
        _leg19g2 = _t15_item("st-C993", "C993", "T19g2")
        _leg19g2.update({"exp_id": "EXP-8", "ts": "2026-11-03 00:00:00",
                         "outcome": "自动建条目尝试 1 次即止：checker 红 exit=1 已回滚 "
                                    "clean=True（旧语义永久丢弃）"})
        seal_verdict_item(_leg19g2)            # 守护自产件同款签发
        _st19g2["verdict_log"] = [_leg19g2]
        seal_state(_st19g2)
        _sp19g2 = tmp + "/state-t19g2.json"
        with open(_sp19g2, "w", encoding="utf-8") as f:
            json.dump(_st19g2, f, ensure_ascii=False)
        _os19g2 = CFG["state"]
        CFG["state"] = _sp19g2
        _ld19g2 = load_state()
        globals()["DRY"] = False
        _n19g2 = _reenqueue_parked_auto_creates(_ld19g2)
        CFG["dry"] = True
        globals()["DRY"] = True
        _r19g2 = writeback_round(_ld19g2, None)
        CFG["dry"] = False
        globals()["DRY"] = False
        CFG["state"] = _os19g2
        check("T19g2 正例对照：面级封条在 → 验签通过、日志段不被隔离、旧语义恢复"
              "路径仍可用（合法件不误伤）",
              _ld19g2.get("state_seal_ok") is True
              and len(_ld19g2.get("verdict_log") or []) == 1
              and _n19g2 == 1
              and len(_ld19g2.get("verdict_queue") or []) == 1
              and [x.get("entry") for x in (_r19g2.get("plan") or [])] == ["st-C993"],
              json.dumps({"seal_ok": _ld19g2.get("state_seal_ok"),
                          "log_n": len(_ld19g2.get("verdict_log") or []),
                          "reenq": _n19g2, "q": len(_ld19g2.get("verdict_queue") or []),
                          "plan": _r19g2.get("plan")}, ensure_ascii=False))
        CFG["b_exp1"] = _oe1                        # 还原在位聚合器

        # T11 真实对账：b-canon 确定性（临时出目录两跑字节一致 + 与正本一致）
        o1d, o2d = tmp + "/bc1", tmp + "/bc2"
        os.makedirs(o1d, exist_ok=True)
        os.makedirs(o2d, exist_ok=True)
        for d in (o1d, o2d):
            p = sh([sys.executable, CFG["b_canon"], "--cards", CFG["cards"],
                    "--out-md", d + "/m.md", "--out-jsonl", d + "/j.jsonl"], timeout=TMO["b_canon"])
            if p.returncode != 0:
                check("T11 b-canon 两跑", False, (p.stderr or "")[-200:])
        same = open(o1d + "/j.jsonl", "rb").read() == open(o2d + "/j.jsonl", "rb").read()
        canon = open(CFG["canon_book"], "rb").read()
        check("T11 b-canon 确定性+与正本字节一致", same and open(o1d + "/j.jsonl", "rb").read() == canon)

        # T12 真实对账：registry 只读感知
        perc = perceive()
        check("T12 registry 感知", perc["verified"] > 0 and perc["total"] >= perc["verified"]
              and perc["watermark"], json.dumps({k: perc[k] for k in
                                                 ("verified", "total", "watermark")}, ensure_ascii=False))
    finally:
        CFG.clear()
        CFG.update(old)
        globals()["DRY"] = CFG["dry"]
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print("SELFTEST FAIL (%d): %s" % (len(fails), ", ".join(fails)))
        return 1
    print("SELFTEST PASS")
    return 0


# ---------------------------------------------------------------- main
def _production_launch_guard():
    """RT-E85②（H5 修法，P4-联评）：生产启动路径 env 注入守卫（K5 收口的另一半）。

    生产启动（非 --selftest/--status）下：
      · SIL_KEY_SRC=test 显式 env ⇒ 整个出域机制被旁路（legacy 自生成/钥文件语义
        回归）→ 拒启动（selftest 内部强制 test 不经此路；演练/夹具直调函数不经
        main，均不受影响）；
      · SIL_KEY_EXPECTED_SHA256 显式 env ⇒ 迁移连续性锚可被 env 换值（K4 声称
        「进码钉死」）→ 拒启动（换钥属代码变更走 gate-pins 重锚，不走 env）。
    可被 keepalive 拉起的崩溃循环由 keepalive Debounce 兜底（超限只报警，
    factory-keepalive.py:663+，P4-H8.8 对账）。"""
    if os.environ.get("SIL_KEY_SRC", "").strip() == "test":
        raise SystemExit("RT-E85②: SIL_KEY_SRC=test 生产启动被拒（出域旁路面收口，"
                         "P4-H5/K5 同款）——selftest 用 --selftest（内部强制 test），"
                         "影子演练请用影子件直调")
    if os.environ.get("SIL_KEY_EXPECTED_SHA256", "").strip():
        raise SystemExit("RT-E85②: SIL_KEY_EXPECTED_SHA256 env 注入被拒（迁移连续性"
                         "锚进码钉死，P4-H5/K4）——换钥须改码并跑 gate-pins-refresh.sh 重锚")


def main():
    ap = argparse.ArgumentParser(description="自改进循环产线守护（四段增量流水，600s 周期）")
    ap.add_argument("--once", action="store_true", help="单轮即退（自测用）")
    ap.add_argument("--dry-run", action="store_true", help="只记不写（同 SELF_IMPROVE_DRY=1）")
    ap.add_argument("--force-trigger", action="store_true", help="越过增量闸强制跑②③④（自测用）")
    ap.add_argument("--status", action="store_true", help="打印 loop-state.json 即退")
    ap.add_argument("--selftest", action="store_true", help="不变量自检后退出")
    a = ap.parse_args()
    globals()["DRY"] = a.dry_run or CFG["dry"]
    CFG["dry"] = DRY
    if a.selftest:
        sys.exit(_selftest())
    _production_launch_guard()                       # RT-E85②（H5）：selftest 豁免路径之后
    if a.status:
        try:
            print(json.dumps(json.load(open(CFG["state"], encoding="utf-8")),
                             ensure_ascii=False, indent=1))
        except Exception as e:
            print("loop-state 不可读: %s" % e)
        return
    acquire_pidfile()
    try:
        st = load_state()
        st["daemon_src"] = daemon_src_stamp()     # v1.3.11：起跑即登记在役源码版本钉
        save_state(st)                            # v1.3.11：起跑即落盘（版本钉对监督面
                                                  #   秒级可见——监督面据此判「在役
                                                  #   判据≠盘上判据」并自动换码）
        log("self-improve-loop 起：周期=%ds 阈值=%d STOP=%s DRY=%s state=%s" %
            (CFG["interval"], CFG["threshold"], CFG["stop"], DRY, CFG["state"]))
        log("在役源码版本钉：ver=%s sha256=%s（载入时盘上源码指纹——盘上源码改动后"
            "本进程仍跑旧码，须重启方生效）" % (DAEMON_VER, DAEMON_SRC_SHA256[:12]))
        # 全寿命心跳（60s 原子重写 state）：轮周期 600s > keepalive 300s 新鲜度判据，
        # 无心跳则轮间隔内必被误判失联反复拉起；心跳只带时间戳，不前进基线/签名。
        if not DRY:
            heartbeat_start(st)
        while True:
            if os.path.exists(CFG["stop"]):
                try:
                    round_once(st)          # STOP 轮：记账不动作（保 keepalive 新鲜度）
                except Exception as e:
                    log("STOP 轮异常（不退出）: %s" % e)
                if a.once:
                    break
                time.sleep(CFG["interval"])
                continue
            try:
                round_once(st, force=a.force_trigger)
            except Exception as e:
                st["counters"]["errors"] = st.get("counters", {}).get("errors", 0) + 1
                log("循环异常（不退出）: %s" % e)
            if a.once:
                break
            time.sleep(CFG["interval"])
    finally:
        heartbeat_stop()
        release_pidfile()


if __name__ == "__main__":
    main()
