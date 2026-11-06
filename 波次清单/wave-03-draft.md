# wave-03 草案（全卡表·26 候选）——af 波次自转规划件

- 工件身份：wave-03 预制冷规划（主代理派工 `计划/变更日志.md:48611`「④wave-03 预制冷已派（dwfrun-e39c5b0c·step：五路候选≥20 卡+首发 8 精选——模板缺口 76/78 为主卡候选/旧 otel 表 DROP/镜像扩池三案/部署窗两卡/runner 改进三件套/KB 口径批[math 归一预裁输入]/harness 收编）」）。本件=**只读扫描+产卡草案**，零施工、零账本写入；每卡验收命令确定性；引用坐标 `file:line`。
- 制度基准：`30-工件/波次自转器-20261106/制度-v1.md`（§二 四通道；§四 主代理只现身于异常裁决/部署窗/清单签发；§五 OOM 准入；§六.3 台账无行的债号占用闸 fail-closed）。
- 前波状态（本件亲读）：`30-工件/波次自转器-20261106/wave-02.json` 六卡全 `gates-local`（runner 状态机不含该态= runner 不碰，由主代理本地监督轨推进）；单树 `/data/bench/wt-mc-s17-all` 六支 `--no-ff` 合并在位（anolis 亲读：`5ee16ec`/`ad75223`/`fcea6d5`…）；`计划/变更日志.md:48605`（11:10）「加速五条①②落地：单树六支合线+环境基准卡；③④⑤下一步：补板/wave-03 预制冷/监督轨统一入 runner 改进清单」。
- base_sha 建议：以部署窗前 `git fetch origin` 后 `origin/product/main` 实测为准（本件不预设；本地 product/main ref=2de44533 已 stale，af 仓 HEAD=286c65e4 on `feature/s17-training-artifact-registry`，`git log --oneline -3` 实测）。

## §0 本件实测读数（全部本会话亲跑；命令+输出）

| # | 命令（cwd） | 输出 | 用途 |
|---|---|---|---|
| 1 | `grep -ho "template_ref: [^ ]*" strategies/st-\*.yaml \| sed 's/template_ref: //' \| sort -u \| wc -l`（af 仓） | **78** | 模板缺口分子（复验设计稿 §三.2） |
| 2 | `find af/packages -path "\*/prompts/\*" -type f \| sort`（af 仓） | 10 文件=8 模板（sweng 6+reportkit 2）+2 `MANIFEST.sha256` | 缺口分母：**78−8=76 引用无盘文件**（复验成立） |
| 3 | 76 缺件家族分布（python 枚举，本件跑） | sweng 4（`pkg.sweng.coder_system` 被 6 条策略引）、ttc 4（`pkg.ttc.coder_system` 被 5 条引）、长尾 68 件各 1 条 | 供给批分批依据（T1/T2/T3） |
| 4 | `ssh anolis 'cat /data/bench/swev-pool-gen-state.json'` | `stop_why="no_candidates"`；detail：`dataset=500, have_img=2, pool=108, subm=804, cands=0, expandable=392, disk_free_gib=104.8`（ts 2026-11-06 10:58:46） | 镜像扩池三案地面事实 |
| 5 | `ssh anolis 'df -h /data; cat /etc/docker/daemon.json'` | 105G 可用（63%）；mirrors=`docker.m.daocloud.io`+`docker.1ms.run`，`max-concurrent-downloads=16` | 扩源案磁盘/加速器前置 |
| 6 | `ssh anolis 'ls /data/bench/fast-pull.py'` | **No such file**（工作区 `tools/fast-pull.py:1-13` 在位未部署） | 加速器恢复案靶点 |
| 7 | `ssh anolis 'ls /data/bench/queue/pending \| wc -l; wc -l /data/bench/queue/submitted.jsonl'` | pending=11（<20 闸在位）；submitted=906 行 | 队列守恒活口 |
| 8 | `ssh anolis 'ls -d /data/bench/wt-mc-\*; cd /data/bench/wt-mc-s17-all && git log --oneline -3'` | `5ee16ec merge(s17): s17-judge-reliability-protocol（wave-02 六卡批量合线）` 等六支在位 | wave-02 收卷段坐标 |
| 9 | otel 审计末条（`工具状态备份/mes-ttl-sweep-evidence.jsonl`，kind=`otel-readonly-audit`，ts 2026-11-06 04:30:48） | `otel_red_reasons=["ttl-drift"]`；`otel_traces` ttl_exp=30/ttl_act=**None**；`otel_traces_bak_20261105` ttl_unpinned、rows=32373/bytes=1386168；promised=8/audited=**9** | DROP 卡复验前置（现势红，须如实） |
| 10 | `af-state/dispatch/exceptions.jsonl` 末段 | `s17-registry-batch-a`/`s17-judge-reliability-protocol` 10:39/10:40 parked@merge-check（缺 FMT_OK）；4 笔 bot（af-dsl-needs-syntax-12cl/p3a1-clippy-gateshape/rt-e82/rt-e83）每 20min 复现 STALE_RED/RED | 复跑卡+bot 裁断卡依据 |
| 11 | KB residue（`30-工件/KB清偿轨-20261105/out/absorb-mechanical-20261106-residue.jsonl`，40 行=1 meta+38 明细+1 回场） | skip 分类：不在库 34（其中 11 条证据注记含「标记伪象」）/rejected 史 2/修文项 1/重立引文 1；另 99 条已 admit 原子 registry=verified∧kb=retired 回场欠账 | KB 口径批分组依据 |
| 12 | KB math/归一池（本件 python 扫 batch-01..09） | 非 admit 且 evidence 含 math/归一/空白 的行 **62**（quote_check=false 53 条）；`rejudged-2610.34962.jsonl` 7 条「空白归一翻案」样板 | math 宽容批池（主代理预裁 ~40 条的可复核上界） |
| 13 | D-54 分支（af 仓 `git show --stat 6a4783b3`/`20b13f69`） | 新门 `ci/harness_regression_gate.py`+`ci/baselines/harness-regression-set.json`，挂 `ci/run.sh` step14(14e)；门面 rc=0+selftest 19/19+注入劣化/空回归集负例实测 | harness 收编卡靶点 |

## §1 全卡表（26 候选；序=组内价值）

> 通道释义：`local-api`=step 子代理 ssh-anolis 施工（本机永禁 cargo，mem=0）；`anolis-build`=runner 生成 run 脚本 nohup（mem 计入 45G 准入）；`deploy-window`=**主代理专属**（制度 §四②），runner 状态机不含该态（`tools/wave-runner.py:305` 不推进）。`merge_policy`：af 仓卡=merge-check 范式（显式 refspec+单树）；tools/ 单件=改前 `.bak`+钉桩重锚；库操作卡=n/a。

### 组 A·模板供给面（主卡+配对，4 卡）

#### A0 `w03-debt-registration`（前置卡·无债号）
- debt：—（动作卡：在 `计划/阶段欠账台账.md` 登记 D-61…D-78 行；现正本最大 D-59，`grep -o "D-[0-9]\+" 计划/阶段欠账台账.md \| sort -t- -k2 -n \| tail -3` 实测）
- channel：local-api；mem_budget_g：0
- title：wave-03 新卡债号登记前置（D-61…D-78 行+占用闸放行之本）
- rationale：制度 §六.3「台账无行的债号占用闸 fail-closed BLOCK → 派卡前置=登记债行或换锚」（`30-工件/波次自转器-20261106/制度-v1.md:47`）；设计稿 §七 同款前置（`30-工件/strategies17-供给面设计-20261106.md:175`）。wave-02 的 D-54…D-59 即先登记后派卡（`计划/阶段欠账台账.md:117-122`）。
- acceptance：`grep -c "^| D-6[1-9] \|^| D-7[0-8] " 计划/阶段欠账台账.md` = 18；`python3 -I tools/dispatch-occupancy-check.py D-61 --json` 输出 `verdict=ALLOW`（或按卡换锚）；`wc -l` 登记前后差=18（append-only，禁改行）。
- merge_policy：n/a（台账登记，整文件先备+行尾 append）；ledger：本卡即登记动作；depends_on：无（首发第一刀）。

#### A1 `w03-template-supply-batch`（最大单卡）
- debt：D-61（建议；父债 P3-B1）
- channel：local-api；mem_budget_g：0（ssh-anolis 施工；合线长杆本监）
- title：模板供给批：76 个无盘 template_ref 补齐（T1 sweng 4→T2 ttc 4→T3 长尾 68；MANIFEST.sha256 同步）
- rationale：设计稿 §三.2（`30-工件/strategies17-供给面设计-20261106.md:50`）「78 个 distinct template_ref，盘上仅 8 个模板文件，**76 个引用无盘文件**；模板装载在执行面启动期逐件 sha256 核对（`af/packages/README.md:77-82`，EX4001-4003）——编译门绿 ≠ 跑得起，模板供给缺口对 44 条 compilable 全体仍开放」；§八.4「建议单列供给批（E9001 同型），不与 17 条判定混批」（`:182`）；断点延续 `af/poc/poc-p3-a1-strategy-dsl/README.md:109`「(a) 全部 44 条引用注册表缺失的 prompt 模板」、`:122`「再补缺失供给（prompt 模板+…）」。本件 §0 #1-#3 复验 78/8/76 与家族分布（coder_system 高杠杆：sweng 6 条/ttc 5 条策略引用）。
- acceptance：① `find af/packages -path "*/prompts/*" -name "*.md" \| wc -l` = 8+76=84 ② 逐包 `cd af/packages/<包> && sha256sum -c prompts/MANIFEST.sha256` 全 OK（含新增行）③ 新门 A2 `python3 -B tools/template-supply-gate.py` rc=0 ④ `python3 -B ci/strategies_check.py` 全绿（44/0/17 不劣化）⑤ 判据件（ci/strategies_check.py、criteria.yaml、gate_inputs 钉）零改 ⑥ 装载面既有测试 `cargo test -p af-execline --test pkg_sweng --test pkg_reportkit` 零失败（sweng/reportkit 包扩件后）。
- allowed_paths：`af/packages/`（prompts/ 与 MANIFEST.sha256；禁碰 components.json 与计数钉——纯资产批）
- merge_policy：merge-check 范式（显式 refspec；可搭单树批量组）；ledger：台账 D-61 行+变更日志行；depends_on：A0（债号在位）。

#### A2 `w03-template-loader-gate`（配对门）
- debt：D-62（建议）
- channel：local-api；mem_budget_g：0
- title：模板供给对账门（78 template_ref ↔ 盘文件 ↔ MANIFEST sha256；存量 roster 登记不判红、新缺件红）
- rationale：缺口当前**零机器消费面**（compile 门不读模板；EX4001-4003 只在执行面启动期，`af/packages/README.md:77-82`）→ 复发不可见。门型先例=观测面死码门「存量登记不判红、新增同名仍红」（`30-工件/观测面清偿批-20261105/gate-registry.json` deadcode_baseline/deadcode_roster 段）+ all-gates 提示行为（`tools/all-gates.sh:782` 新增件未列入照常注册实跑只提示）。
- acceptance：① 现盘（补料前）rc=0 且红单=0（76 件全在 roster 基线）② 负例：临时藏一个已登记模板文件→rc=1 点名缺件 ③ 负例：MANIFEST 行与文件 sha 不符→rc=1 ④ 正例：A1 补料后 roster 清空→rc=0 ⑤ 门件入 `tools/` 且 `python3 -m py_compile` OK；若入 all-gates L3 须同批 `bash tools/gate-pins-refresh.sh` 重锚+变更日志登记（禁越权直改）。
- merge_policy：merge-check 范式或 tools/ 单件直推（按落点裁）；ledger：台账 D-62 行；depends_on：A0。

#### A3 `w03-template-t1t2-leverage`（高杠杆先行批，可并 A1）
- debt：D-63（建议）
- channel：local-api；mem_budget_g：0
- title：模板先行批 T1+T2：sweng 4 件（coder_system 覆盖 6 策略）+ttc 4 件（coder_system 覆盖 5 策略）新包 prompts/+MANIFEST
- rationale：本件 §0 #3 实测杠杆集中度：`pkg.sweng.coder_system` 6 条策略引用、`pkg.ttc.coder_system` 5 条；ttc 为 prompts 新包（`af/packages/ttc/prompts/` 首建，装载按包名解析无需 components.json 声明——`af/packages/README.md:77-82` 机制）。先落地可让 11+ 条策略的模板面先行闭合，长尾 68 件随后。
- acceptance：① `ls af/packages/sweng/prompts/ af/packages/ttc/prompts/` 含 8 个新 `.md`+各包 `MANIFEST.sha256` ② 两包 `sha256sum -c prompts/MANIFEST.sha256` OK ③ `python3 -B ci/strategies_check.py` 全绿 ④ `cargo test -p af-execline --test pkg_sweng` 零失败（sweng 包扩件回归）。
- merge_policy：merge-check 范式；ledger：台账 D-63 行；depends_on：A0（与 A1 同树不冲突：文件集按包分区，可并行施工、单树合流）。

### 组 B·gov/部署窗（3 卡；主代理专属，runner 不派）

#### B1 `otel-bak-drop-20261105`
- debt：D-64（建议；锚 `计划/变更日志.md:47907`「旧表 otel_traces_bak_20261105 保留待下批 DROP」+wave-01 seed「旧 otel 表 DROP」`30-工件/波次自转器-20261106/wave-01.json:221`）
- channel：deploy-window；mem_budget_g：2（gov 小件后端手术上限，制度 §五）
- title：旧 otel 表 DROP：otel_traces_bak_20261105（复验稳定后手术；CH otel 库）
- rationale：11-05 手术收卷（`计划/变更日志.md:47907`）明确「保留待下批 DROP」；DDL 侧注记 `tools/otel/otel-ddl.sql:77`「otel_traces_bak_<ts> 保留，本批不 DROP」；现势审计（§0 #9）：bak rows=32373/bytes=1386168、ttl_unpinned、audited=9≠promised=8，且 **otel_red_reasons=["ttl-drift"] 当刻为红**（otel_traces ttl_act=None）——复验必须如实含此红，不许带红强签。
- acceptance（按序，任一不过=中止不 DROP）：① 零丢失复验：`SELECT count() FROM otel_traces_bak_20261105 WHERE SpanId NOT IN (SELECT SpanId FROM otel_traces)` = 0（手术批同款判据，`计划/变更日志.md:47907`「bak 有而 new 无=0」）② `count()=countDistinct(SpanId)` 去重复验 ③ MV 重绑后自然写入仍在（近窗新 span 计数>0）④ 三查询点 FINAL 在位（`tools/otel/otlp-assert.py:925/951/1009` 口径，手术批注记）⑤ `DROP TABLE otel_traces_bak_20261105` 后重跑 otel 只读审计：audited_table_count=8=promised、ttl_unpinned_tables=[]；⑥ 变更日志登记（DROP 前后 count/bytes 快照+零丢失读数）；⑦ **ttl-drift 红单独登记**（不因 DROP 消失，转异常队列或欠账行，禁并入本卡销项）。
- merge_policy：n/a（gov CH 手术）；ledger：变更日志行+台账 D-64 行；depends_on：主代理终审（G0 同款放行）。

#### B2 `rt-e85-deploy-window`
- debt：RT-E85（`计划/阶段欠账台账.md:84` 未开始）
- channel：deploy-window；mem_budget_g：2
- title：RT-E85 部署窗：gov T1（root@gov-host.invalid 三动作）+T2 对账+正本换码（守护→探针同窗）+G0-G8 验收门
- rationale：移交简报就绪（`30-工件/RT-E85轨-20261105/P5-移交.md`：wip 4,478 行 py_compile OK、selftest 72 PASS、演练 PASS(0)、夹具 T18f+T18g 全 PASS、正本零触碰 md5 留证）；前置硬条件 (0a) T1 gov 侧三动作+ (0b) T2 sha256==`8342632c2d5852d7…be33c`（`:31-32`）；换码顺序锁死=守护 mv→探针 mv→重锚→重启→验证→复 keepalive（`:63`）；验收门 G0-G8（`:87-99`）。
- acceptance：① G1：`printf '%s' "$(bao kv get -field=key kv/company/SIL-signing/mirror-signing)" \| sha256sum` == `8342632c…` ② G2/G3：`daemon_src.ver=="v1.3.15"` ∧ loop-state `key_status.state=="ok"` ∧ `fp16=="8342632c2d5852d7"` ③ G4 `bash tools/gate-pins-check.sh` exit=0 ④ G5 `python3 -I tools/sil-verdict-probe.py` PASS（绿行含「⑩ 签名钥在役」）+`bash tools/all-gates.sh` exit=0 ⑤ G6（建议）停摆两态实测 ⑥ G7 四留证链（迁移前快照/T2 对账/部署后 fp16/销毁留证）⑦ G8 `ls ~/.config/sil-rt/` 空；变更日志登记。
- merge_policy：n/a（正本换码=部署窗）；ledger：台账 RT-E85 行翻✅+变更日志行；depends_on：主代理终审放行（G0）。

#### B3 `rt-e161-deploy-window`
- debt：RT-E161（`计划/阶段欠账台账.md:103` 未开始）
- channel：deploy-window；mem_budget_g：2
- title：RT-E161 部署窗：factory-scheduler 换正本（.rt161wip）+test-manifest.list 登记行+#L2_ITEMS_COUNT 31→32+钉桩重锚+首读核对
- rationale：落码轨就绪（`30-工件/RT-E161轨-20261106/rt-e161-supply-liveness-设计与自证.md`：供给活性门五态夹具 PASSED 5 项、QCLEG_FS 回归 24 组全绿、正本/manifest 前后 sha 逐字相等）；部署清单 6 步（`rt-e161-test-manifest-登记行提案.md:7-24`：换正本→追加 `test-e161-supply-liveness.py` 行→计数 31→32→变更日志登记新 sha→`gate-pins-refresh.sh`→双验证）。
- acceptance：① 换后 `sha256sum tools/factory-scheduler.py` == wip sha（`2651e3a1e82d…`，轨文件 §三）② `python3 tools/test-e161-supply-liveness.py` 输出「被测=正本」且 PASSED ③ `python3 -I tools/test-qc-leg-truth-gate.py`（QCLEG_FS 缺省）PASS ④ manifest 声明 `#L2_ITEMS_COUNT=32` 且末行在列 ⑤ 变更日志登记 `test-manifest.list sha256=<改后 64hex>` ⑥ 首个真跑轮（2h 节拍到点）`状态观测/supply-activity.json` 出现且双腿 verdict=green（arb「生成0/跳过175」/dst 跳过21 合法态，不得误红——轨文件 §二判定矩阵）。
- merge_policy：n/a（tools/ 正本换码）；ledger：台账 RT-E161 行+变更日志行；depends_on：主代理终审；随行提案（test-arb-reissue-unblock.py 同批补录否）由部署窗裁——裁「同批补录」则并卡 G3 执行。

### 组 C·runner 改进三件套（3 卡；`计划/变更日志.md:48605` ③④⑤下一步）

#### C1 `wave-runner-batch-merge-policy`（运营者①）
- debt：D-65（建议）
- channel：local-api；mem_budget_g：0
- title：wave-runner 批量合线 merge-policy 步：branch 就绪自动组单树（oper者①；根治多树并行门自造 ENOSPC）
- rationale：运营者建议已落地验证（`计划/变更日志.md:48605`「①批量合线范式切换：六分支回收分散 mc 树/targets（含 wave-02 施工期 104G）→ 单树 wt-mc-s17-all --no-ff 六支全 M_OK 零冲突 → 一轮 -j8 全量门本监；六卡 mc_wt/mc_ref 归并单树」）；runner 现码每卡独立建树（`tools/wave-runner.py:141-146` `wt=/data/bench/wt-mc-<task_id>`、`:150-151` 逐支 fetch+merge）——wave-02 靠人工在 JSON 里把六卡 mc_wt/mc_ref 手改同值实现，未入 runner。
- acceptance：① runner 新增分组步：同波次 merge 就绪卡（state∈{verifying} 且 merge.branches 非空）按 `merge.group`（缺省=波次名）自动归并单 mc_wt/mc_ref，组内 `--no-ff` 顺序合② 单测/干跑：构造 3 卡 JSON→分组输出单树+三支 M_OK（沙箱 wt，`--dry` 不触生产）③ 既有单卡路径不回归（无 group 时按旧行为）④ ENOSPC 防护：targets 目录按组共享（`CARGO_TARGET_DIR=/data/bench/targets/mc-<group>`，现码 `:152` 按 task_id 分）⑤ `python3 -m py_compile tools/wave-runner.py` OK；改前 `.bak` 留证。
- merge_policy：tools/ 单件直推（改前 .bak+如入钉桩则重锚）；ledger：台账 D-65 行+变更日志行；depends_on：A0。

#### C2 `wave-runner-supervision-unify`（监督轨统一）
- debt：D-66（建议）
- channel：local-api；mem_budget_g：0
- title：监督轨统一：全量门本地后台监督范式收编为确定性脚本（nohup-over-ssh 弃用后的单一监督面）
- rationale：双实证弃用（`计划/变更日志.md:48417`「EXP1 后台门 07:06 静默死于 anolis（nohup-over-ssh 连续两程不保活）→ 处置=nohup 思路弃用，转『本地后台终端任务监督』」；`:48422`「本地监督轨范式确认……入 wave-02 runner 改进项」）；现码以注释约定（`tools/wave-runner.py:162-167`「全量门不走 anolis 后台，统一『主代理本地后台终端任务监督』范式（完成通知驱动）；本态只记树/分支，主代理验门后置卡 mc_done=true」）——mc_done 目前靠人工置位，无工具面。
- acceptance：① 新脚本（如 `tools/wave-gates-supervise.py`）对指定 mc_wt/mc_ref 跑四门（fmt+strategies_check+全量 test+clippy）并原子写结果文件（含 rc 与期望串）② 结果绿→自动置卡 `mc_done=true`（幂等，同态不重跑）③ 红→append 异常队列（`af-state/dispatch/exceptions.jsonl`，格式同现码 `:58-63`）④ 干跑：对既有沙箱树实跑一轮 rc=0 ⑤ `python3 -m py_compile` OK+改前 `.bak`。
- merge_policy：tools/ 单件直推；ledger：台账 D-66 行；depends_on：A0；与 C1 同树不冲突（可并行）。

#### C3 `wave-runner-env-check-adopt`（env-check 收编）
- debt：D-67（建议）
- channel：local-api；mem_budget_g：0
- title：anolis-env-check.sh 收编：runner 准入步+生成 run 脚本前置（fail-closed 结构化 JSON）
- rationale：环境基准卡已落码并部署（`计划/变更日志.md:48605`「②环境基准卡 tools/anolis-env-check.sh 落码（cargo PATH 面+df /data≥10G 预检+fail-closed 结构化 JSON——复发 ≥4 次坑类一次收编；已部署 anolis 并实证 OK/127G）」；卡件 `tools/anolis-env-check.sh:1-16`；本件亲读 anolis `/data/bench/anolis-env-check.sh` 在位）——但 runner 尚未调用它（现码 `tools/wave-runner.py:97` 只 `export PATH=$HOME/.cargo/bin:$PATH`）。
- acceptance：① `dispatch_anolis` 生成的脚本首行=env-check 前置（`bash /data/bench/anolis-env-check.sh || exit 2` 语义）② 准入步新增 anolis 侧 env-check 探测（失败→parked+异常队列，不派）③ 负例：沙箱 PATH 破坏/df 桩 <10G → 结构化 JSON `env_check:FAIL` 且 rc=2 不续跑 ④ 现码单测/干跑一轮 rc=0 ⑤ py_compile OK+`.bak` 留证。
- merge_policy：tools/ 单件直推；ledger：台账 D-67 行；depends_on：A0。

### 组 D·KB 口径批执行卡（6 卡；主代理预裁口径输入，材料 `30-工件/KB清偿轨-20261105/out/absorb-mechanical-20261106-residue.jsonl`）

> 共同纪律：库操作走 `kb-seed/registry.py admit <atom_id> <basis.json>`（CLI fail-closed 依据路径校验在位，`kb-seed/registry.py:33-43`）；禁 demote/reject、禁改 schema（主文件 meta 纪律）；每卡前后 registry 三态计数对账（前态 candidate=19480/verified=26729/rejected=1263，主文件 meta「registry对账」段）；收尾 `python3 -I tools/test-e32-verified-uphold-recon.py` exit=0。

#### D1 `kb-math-lenient-batch`（math 形态归一宽容批）
- debt：D-68（建议；关联 RT-E32 口径面）
- channel：local-api；mem_budget_g：0
- title：math 形态归一宽容批：~40 条可翻案原子按预裁口径再 admit（空白/连字符/math 标记伪象归一）
- rationale：主代理预裁输入（派工 `计划/变更日志.md:48611`「KB 口径批[math 归一预裁输入]」）；样板 7 条已翻（`rejudged-2610.34962.jsonl`：「quote『ntify interaction magnitude rather than』空白归一后连续命中 evidence-cache/2610.34962/full.md(sha256 8ab164d8…)」式）；池实测（§0 #12）：非 admit 且含 math/归一/空白 证据的行 62 条（quote_check=false 53）——~40 为预裁子集，逐条须过四问同款判定（引用命中+sha 实证+无阻断注记）；单字符/连字符差样板（`batch-03.jsonl:12` man-hour/man-hours、`batch-01.jsonl:34` 连字符差）与标记伪象注记（residue 11 条「数字 xx% 不存在系标记伪象」）。
- acceptance：① 翻案清单 JSONL（每条带 atom_id+归一口径+命中坐标 file:line+sha）② 逐条 `python3 kb-seed/registry.py admit <atom_id> /tmp/…/basis/<atom_id>.json` 成功（CLI fail-closed 通过）③ registry 前后三态计数净变=applied 数（candidate−N/verified+N/rejected 不动）④ `python3 -I tools/test-e32-verified-uphold-recon.py` exit=0（违规=0）⑤ 未翻案条目清单留档（不壮胆入库）。
- merge_policy：n/a（库操作）；ledger：台账 D-68 行+依据 JSONL 归档 `30-工件/KB清偿轨-20261105/out/`；depends_on：主代理口径预裁确认（~40 名单）。

#### D2 `kb-recite-reestablish-batch`（重立引文批）
- debt：D-69（建议）
- channel：local-api；mem_budget_g：0
- title：重立引文批：locator/引文修正后重 admit（w4-2610.35757-r2-2 样板：引文实为 Abstract 段，locator 改摘要）
- rationale：residue 明细「重立引文」1 条（`sbx-kb-atoms-w4-2610.35757-r2-2`，依据卡 `batch-07.jsonl:19`：「evidence 明言『locator 需修正』（引文实为 Abstract 段内容，locator 元数据需在再 admit 时改为摘要）——重立引文在先，宁可不 absorbed」）；修文项同族（`sbx-kb-atoms-rpt-2610.35188-r2-22`，「即使」疑为「即足以」，`batch-03.jsonl:28`）可并批裁。
- acceptance：① 修正后 basis JSON（新 locator+原文逐字命中坐标+sha）② `registry.py admit` 成功 ③ 计数对账同 D1③ ④ recon 门 exit=0 ⑤ 未修正条目留残档。
- merge_policy：n/a；ledger：台账 D-69 行；depends_on：A0。

#### D3 `kb-version-drift-maintain`（版本漂移维持）
- debt：D-70（建议）
- channel：local-api；mem_budget_g：0
- title：版本漂移维持批：3 条 verSame=False 注记口径维持登记（101/101 现势 sha 实证一致）
- rationale：主文件统计段「版本漂移：0 条 skip——3 条 evidence 含 verSame=False 均系被翻案旧卡注记；101/101 现势 sha 实证一致」（`absorb-mechanical-20261106.jsonl` 统计行「分类零项说明」）；翻案卡登记 sha 与现势 evidence-cache 的对应关系需留机器可读面，防后续复核再误判为漂移。
- acceptance：① 漂移注记册 JSONL（3 条：登记 sha/现势 sha/对应翻案卡/结论=旧卡注记非漂移）② 复核命令 `python3 -B tools/<sha 对账脚本或等效>` 现跑 rc=0（无真漂移）③ 计数对账 ④ recon 门 exit=0。
- merge_policy：n/a（登记+只读对账）；ledger：台账 D-70 行；depends_on：A0。

#### D4 `kb-not-in-library-import`（24 不在库入库面）
- debt：D-71（建议）
- channel：local-api；mem_budget_g：0
- title：不在库入库面：预裁 24 条 import 决策执行（residue 34 条不在库：11 条标记伪象注记+23 其他；admit 无行可翻→先 import）
- rationale：residue 明细（34 条「四问①②双败：原子不在 kb.db 快照亦不在 registry.db（仅 JSONL 候选层）——admit 无行可翻，先需主代理裁 import 事项」）；派工预裁「24 不在库入库面」（`计划/变更日志.md:48611`）；11 条证据自带「数字 xx% 不存在系 math/表格标记伪象」注记（import 时按 D1 归一口径同裁）。
- acceptance：① import 清单（24 条 atom_id+来源 JSONL 行坐标+四问读数）② import 后双库在场对账（kb.db/registry.db 各 24 行或留未入库原因册）③ 计数对账（import 属新增行，须前后快照留证）④ recon 门 exit=0 ⑤ 未裁 10 条留残档（不壮胆）。
- merge_policy：n/a（库操作）；ledger：台账 D-71 行；depends_on：主代理 import 口径预裁（24 名单+来源行许可）。

#### D5 `kb-return-99-adjudication`（99 回场欠账）
- debt：D-72（建议）
- channel：local-api；mem_budget_g：0
- title：99 条已 admit 原子 KB 侧回场欠账裁办（registry=verified∧kb=retired；kb/import_registry.py:220 纪律=本地裁决优先）
- rationale：residue 回场行（「99 条原子 registry.db=verified（本轮 admit）∧ kb.db=retired（RT-E32 跨卡分歧降级）……retired→verified 的 KB 侧翻面不在本轮权限内，需主代理裁（或确认由 kb 重建/他卡流程回场）」；判据 `kb/import_registry.py:220`「绝不触碰 merged/retired——KB 侧合并退役是本地裁决，优先级高于台账」）。
- acceptance：① 主代理裁令放行后，回场路径二选一留证（kb-ingest 幂等 upsert 回场 或 重建流程）② 回场后双库 verified 对账（99 条逐条或抽样+汇总计数）③ `python3 -I tools/test-e32-verified-uphold-recon.py` exit=0 ④ 计数对账 ⑤ 不回场条目册（原因+裁令号）。
- merge_policy：n/a；ledger：台账 D-72 行；depends_on：**主代理裁**（权限外，先裁后动）；A0。

#### D6 `kb-e32-return-path-verify`（RT-E32-CLEAN 边界活链）
- debt：RT-E32-CLEAN（`计划/阶段欠账台账.md:35` ✅ 行边界注）
- channel：local-api；mem_budget_g：0
- title：RT-E32 翻案回场活链复验（边界：「库存降级后未复验『他卡翻案后回场 verified』活链」——D1 翻案批的首个活链实证）
- rationale：台账 :35 边界如实（「库存降级后未复验『他卡翻案后回场 verified』活链——回场通路由既有 kb-ingest 幂等 upsert 承担，本轮只验机制腿与豁免不误红」）；D1 的 ~40 翻案恰提供活链实测面（uphold 卡翻案→candidate→verified→kb 回场 verified）。
- acceptance：① 活链样例 ≥3 条（翻案原子：registry candidate→verified ∧ kb 回场 verified，逐条双库 SELECT 留证）② `python3 -I tools/test-e32-verified-uphold-recon.py` exit=0 ③ `python3 -I tools/test-e32-crosscard-divergence-consume.py` exit=0 ④ 无活链=红并登记（不假绿）。
- merge_policy：n/a；ledger：台账 RT-E32-CLEAN 行附注（同格编辑，行数不变）；depends_on：D1（有翻案实物才可验）。

### 组 E·镜像题扩池行动卡（3 案；stop_why=no_candidates 已可读）

#### E1 `swev-pool-expand-pull`（扩源案）
- debt：D-73（建议；锚 wave-01 seed「镜像题供给扩池（stop_why=no_candidates 已可读后的下一步）」`30-工件/波次自转器-20261106/wave-01.json:223`）
- channel：anolis-build；mem_budget_g：2
- title：扩源案：swev-pool-gen --pull --max-pull 8（严格候选 0 而可扩题 392；磁盘 105G 过 80G 护栏；mirrors 在位）
- rationale：§0 #4/#5/#7 实测：strict cands=0、expandable=392、disk_free=104.8GiB≥80、registry-mirrors 双在位、pending=11<20；生成器扩池路径（`tools/swev-pool-gen.py:407-413` pull 触发+`:248-294` 磁盘护栏/帽 40/加速器回退）；队列守恒触发链（`tools/factory-scheduler.py:810-866`：pending<20→swev-pool-gen 在位才触发→0 产出自动升级 --pull --max-pull 8，`:863-865`）。
- acceptance：① `ssh anolis 'cat /data/bench/swev-pool-gen-state.json'` stop_why ∈ {"", "target_met"} 或 pulled>0 ② detail.pulled=预期数 ∧ have_img 增长 ③ 新增题库 JSON≤limit ∧ pending 新增 `0300-gen1-*` 条目 ④ 磁盘护栏全程 ≥80GiB（detail.disk_free_gib）⑤ `df /data` 复核 ⑥ 零 STOP 熔断件（`/data/bench/queue/STOP`、`/data/bench/swev-pool-gen.STOP` 缺席，实测当刻缺席）。
- merge_policy：n/a（anolis 一次性工具实跑）；ledger：变更日志行+台账 D-73 行；depends_on：A0；E2 先行更佳（加速器在位再扩源）——可并行。

#### E2 `swev-accelerator-restore`（加速器恢复案）
- debt：D-74（建议）
- channel：anolis-build；mem_budget_g：1
- title：加速器恢复案：fast-pull.py 部署 anolis（工作区在位/在役缺失）+registry 对齐+实拉探针
- rationale：§0 #6 实测 `/data/bench/fast-pull.py` **不在役**（workspace `tools/fast-pull.py:1-13` 297 行在位：OCI 多连接速拉+range 分片，2026-10-20 复活记录 docker.1panel.live 对 swebench 镜像每连接 ~400-800KB/s）；生成器回退路径依赖它（`tools/swev-pool-gen.py:221-240` docker pull 失败→fast-pull→docker load→tag；缺失时两次连续失败即 `accelerator_unavailable` 停因，`:283-287`）；现 mirrors 含 `docker.1ms.run` 而 fast-pull 用法注记 `docker.1panel.live`——须对齐现役 mirror 集。
- acceptance：① `ssh anolis 'ls -la /data/bench/fast-pull.py'` 在位且 sha256==workspace 件 ② `ssh anolis 'python3 -m py_compile /data/bench/fast-pull.py'` OK ③ 探针实拉 1 个未缓存层（或 dry 参数）rc=0 且 `--registry` 值与 daemon.json mirror 对齐 ④ 回退链探针：docker pull 失败路径可触发 fast-pull（注入不可达 registry 名实测一次）⑤ 变更日志登记（部署前后 sha+探针读数）。
- merge_policy：tools/ 单件直推（anolis 部署件）；ledger：变更日志行+台账 D-74 行；depends_on：A0。

#### E3 `swev-pool-abandon-backoff`（放弃补池案）
- debt：D-75（建议）
- channel：local-api；mem_budget_g：0
- title：放弃补池案：no_candidates 稳态认定+调度热触发退避（每分钟触发实录→节流/降频）+替代供给登记
- rationale：热循环实录（`计划/变更日志.md:48586-48608`：10:30-10:52 调度中枢**每分钟**触发 swev-pool-gen 且每次「0 个新任务生成」）；队列守恒路触发条件（`tools/factory-scheduler.py:802-809` pending<20 即会商）+ state 机读面已能判停因（`tools/swev-pool-gen.py:26-34, 438-458` stop_why 码化双写）；放弃案=运营者裁「接受 strict 池枯竭稳态」后：调度侧对 `no_candidates` 停因退避（如连续 N 轮 no_candidates→拉长会商间隔/暂停 --pull 升级），补货面转向已 pending 的 report 卡等既有供给（11 条 `50-report-*` 在位，§0 #7）。
- acceptance：① 退避逻辑在位（读 state stop_why→连续 N 轮 no_candidates 触发退避窗，参数 env 化）② 干跑：桩 state `no_candidates`×N→退避生效日志+不触发 ③ 現码行为不回归（pending≥20 仍会商）④ `python3 -m py_compile tools/factory-scheduler.py` OK+改前 `.bak`+钉桩重锚（若在钉面）⑤ 变更日志登记+**运营者裁令留证**（放弃补池是口径决策，禁技术面私定）。
- merge_policy：tools/ 单件直推；ledger：变更日志行+台账 D-75 行；depends_on：**主代理/运营者裁**（放弃案的口径属性）；A0。

### 组 F·harness/telemetry 收编（2 卡）

#### F1 `s17-harness-gate-adoption`（harness 回归门收编）
- debt：D-54（wave-02 卡；`计划/阶段欠账台账.md:117`）
- channel：local-api；mem_budget_g：0
- title：harness 回归门收编：D-54 门合线后挂 all-gates L3+gate-pins 身钉+readings 管线（harness-readings.jsonl 追加者）接线
- rationale：门已建成未合线（§0 #13：`ci/harness_regression_gate.py`+`ci/baselines/harness-regression-set.json`，挂 `ci/run.sh` step14(14e)，门面 rc=0+selftest 19/19+负例实测；分支 `feature/s17-harness-regression-gate` 在位 6a4783b3/20b13f69）；读数面依赖发布管线追加 `harness-readings.jsonl`（commit 6a4783b3 信息：「读数面（有数才判）：发布管线追加 harness-readings.jsonl 后逐条核对口径（模型/seed/双跑/任务集全覆盖——子集跑分不得过门）」）——追加者面未见落码，收编卡补齐。
- acceptance：① 门入 `tools/all-gates.sh` L3（或既有 CI 面等价位）且 `bash tools/all-gates.sh L3` 该门 rc=0 ② `tools/gate-pins.list` 新钉行+`bash tools/gate-pins-check.sh` exit=0 ③ readings 追加者在位（发布管线写 `harness-readings.jsonl`，空=门按定义面判、有=逐条核对）④ 负例：注入降级 reading（resolve −6pp）→门红 ⑤ 门件/基线判据零弱化（diff 对 6a4783b3 仅接线面）。
- merge_policy：merge-check 范式；ledger：台账 D-54 行（收编附注）+变更日志行；depends_on：D-54 本体合线（G1 单树推送后）。

#### F2 `telemetry-gate-template-adoption`（telemetry 模板面）
- debt：D-76（建议）
- channel：local-api；mem_budget_g：0
- title：telemetry 模板面：观测三门进 all-gates L3 收编（obs-deadcode-scan/ledger-greenclaim-recon/obs-runtime-guard）+otlp-assert --sidecar 在役红登记+otel-ddl TTL 面核对
- rationale：派工点名「telemetry 模板面」（`计划/变更日志.md:48611` 上下文）；仓内可坐标的遥测/观测面遗留=①三门未接线（`30-工件/观测面清偿批-20261105/changelog-draft.md` §五.1「all-gates 未接线：三门未进 tools/all-gates.sh L3（钉桩纪律与『变更日志.md 主代理才追加』冲突）——遗留待主代理并入」+`gate-registry.json` note 同述）②`--sidecar` 覆盖红在役（同件 §四表：「tools/otel/otlp-assert.py --sidecar rc=2 红在『覆盖不全』腿（载荷记录数=1）……在役既有红，如实登记」+§五.3「不属五条债射程」）③otel-ddl TTL 与 bak 面（§0 #9：ttl-drift 红+unpinned，与 B1 联动但**不互相销项**）。**解释注记**：ask 命名「telemetry 模板面」，本卡按上述可坐标面映射；若主代理所指为 strategies 提示词模板的 telemetry 子集，则应并入 A1 处理（78 缺件家族枚举中无 telemetry 专属模板，见 §0 #3）。
- acceptance：① 三门入 all-gates L3（含 cron 巡检位迁移说明）且各门 rc=0 ② `gate-pins-refresh.sh` 重锚+变更日志登记 ③ `--sidecar` 红单独立行（红因+责任债号或豁免登记，禁混绿）④ otel-ddl §1b TTL 声明与现役表 TTL 对账读数留档（ttl-drift 归 B1 ⑦或单立行）⑤ 三门 selftest 复跑全过（`--selftest` 4/4 同款）。
- merge_policy：tools/ 单件直推+all-gates 接线（重锚纪律）；ledger：变更日志行+台账 D-76 行；depends_on：A0；与 B1 同窗不互锁（读数共享）。

### 组 G·wave-02 收尾（3 卡）

#### G1 `wave-02-final-push-ledger`（六卡终态收卷）
- debt：D-54…D-59（六卡；`计划/阶段欠账台账.md:117-122`）
- channel：local-api；mem_budget_g：0
- title：wave-02 收卷跟单：单树全量门绿后验标推送（FF product/main）+六卡 ledger 落账（D-54…D-59 行）
- rationale：六卡 gates-local+单树六支合并在位（§0 #8）；runner v3 路径（`tools/wave-runner.py:265-280`：mc_done=true→验标 push→merged→ledger_write 翻 ✅+append 依据句+wc -l 不变）；全量门本监 exec_a8fba407（`计划/变更日志.md:48605`）。
- acceptance：① `ssh anolis 'cd /data/bench/wt-mc-s17-all && git log --oneline origin/product/main..merge-check/s17-all \| wc -l'` = 6 支差 ② push 后 `git ls-remote origin product/main` 含 mc_ref ③ 台账 D-54…D-59 六行状态翻 ✅（`wc -l` 前后不变+append-only）④ `python3 -B ci/strategies_check.py` 全绿（44/0/17 或按 D-58 翻态实测登记，不预设）⑤ 合线树/targets 回收（ENOSPC 纪律，`:48422`「合线树+target 即收」）。
- merge_policy：merge-check 范式（FF push）；ledger：台账六行+变更日志行；depends_on：全量门绿（本监结果件）。

#### G2 `wave-02-fmt-red-recheck`（两卡 FMT 例外复跑）
- debt：D-58/D-57（两卡；同上台账行）
- channel：local-api；mem_budget_g：0
- title：FMT 红例外复跑判定：s17-registry-batch-a/s17-judge-reliability-protocol 换码修复（e73c4089/cbc5a1e）后 merge-check 快门复跑
- rationale：异常队列 10:39/10:40 两卡 parked@merge-check 缺 FMT_OK（§0 #10）；修复两轮已在 anolis wt 上 `cargo fmt`+commit+push（`计划/变更日志.md:48594`「同型 fmt 修两轮（anolis wt 上 cargo fmt+commit+push+e73c4089/cbc5a1e），六卡全入 merge-testing」）——parked 态需复跑确认转绿，防陈旧例外滞留队列。
- acceptance：① 复跑两卡 merge-check 快门（M_OK+FMT_OK+STRAT_OK 齐）② 若仍红→异常队列附新证据+人工裁 ③ 转绿则并回 G1 单树推送流 ④ `git log --oneline -3` 含两修复 commit。
- merge_policy：merge-check 范式；ledger：随 G1 同行落账；depends_on：G1（或并行复跑）。

#### G3 `test-manifest-unregistered-triage`（未列名夹具补录）
- debt：D-77（建议）
- channel：local-api；mem_budget_g：0
- title：test-manifest 未列名夹具补录裁办：test-e161-supply-liveness.py（B3 已定 31→32）+test-arb-reissue-unblock.py（RT-E161 轨随行提案，部署窗裁）
- rationale：名册纪律（`30-工件/RT-E161轨-20261106/rt-e161-supply-liveness-设计与自证.md` 读准记录：「tools/test-arb-reissue-unblock.py……未在 tools/test-manifest.list 在列（31 行清单 :28-58 无此件，亲读）」；格式=行=basename 一行一件+`#L2_ITEMS_COUNT` 自声明+新 sha 登记变更日志）；all-gates 行为（`tools/all-gates.sh:782` 新增件未列入清单照常注册实跑只提示不判红、`:849` 起在列件才有身钉）。
- acceptance：① 补录行落 `test-manifest.list` 末区（test-router-version-pin.py 之后）② 声明行计数同步（33 或按裁令）③ 变更日志登记 `test-manifest.list sha256=<改后 64hex>`（`sha256sum` 实测）④ `bash tools/gate-pins-refresh.sh` 重锚+`gate-pins-check.sh` exit=0 ⑤ 两夹具实跑 rc=0（`python3 tools/test-e161-supply-liveness.py` 被测=正本；`python3 -I tools/test-arb-reissue-unblock.py`）。
- merge_policy：tools/ 单件直推；ledger：变更日志行+台账 D-77 行；depends_on：B3（换正本后被测切正本）+部署窗对 arb 件的裁令。

### 组 H·运行面杂项（2 卡）

#### H1 `stream-tailer-guard-review`（守护缺失复盘）
- debt：D-78（建议）
- channel：local-api；mem_budget_g：0
- title：stream-tailer（anolis）连续 6 轮缺失复盘：看护阈值/自愈路径/告警文案三面对账+欠账行
- rationale：实录（`计划/变更日志.md` 10:46/10:47/10:48「守护缺位告警：stream-tailer（anolis）连续 1/2/3 轮缺失」→10:54「守护恢复：stream-tailer（anolis）连续 6 轮缺失后重新在线」）；看护清单与告警面在 `tools/factory-keepalive.py`/`factory-scheduler.py`（守护缺位告警产出链），RT-E162 已将 portal 纳看护（`计划/阶段欠账台账.md` RT-E162 行）——同类缺口复盘入档。
- acceptance：① 缺失根因读数（进程为何 6 轮不在：崩溃/宿主/探针误判三态对账，留日志坐标）② 阈值/自愈缺口清单（连续几轮才告警、有无自愈）③ 欠账行或修复卡提案（不假绿）④ 变更日志登记。
- merge_policy：n/a（复盘+登记；若出修复卡另立）；ledger：变更日志行+台账 D-78 行；depends_on：A0。

#### H2 `bot-stale-red-triage`（bot 常驻例外裁断）
- debt：RT-E82/RT-E83（`计划/阶段欠账台账.md` 既有行；rt-e83 已 G-JUDGE RED+registry rejected，`计划/变更日志.md:47898`）
- channel：local-api；mem_budget_g：0
- title：4 笔 bot STALE_RED/RED 常驻例外裁断：SLA 取消重派 or 归档终态（禁 20min 无限复现刷队列）
- rationale：exceptions.jsonl 每 20min 复现 4 笔（af-dsl-needs-syntax-12cl/p3a1-clippy-gateshape/rt-e82-strategies-crosstree STALE_RED；rt-e83-fixverify-dutymain RED——§0 #10）；SLA 常备件在位（`tools/bot-lane-sla-enforce.py`，「1h 无回报/30min 无心跳即取消重派」，`计划/变更日志.md:47898`②）；dev 型 bot 卡禁项（判官/门/判据件一改即拒收，同行「教训登记」+制度 §六.4）。
- acceptance：① 4 笔逐笔裁断记录（取消重派/归档 rejected/重发三选一+依据）② 注册表状态与裁断一致（`af-state/dispatch/registry.json`）③ 异常队列不再 20min 复现同 4 笔（复跑一轮收割验证）④ 变更日志登记。
- merge_policy：n/a（裁断+注册表动作）；ledger：变更日志行+相关台账行；depends_on：A0。

## §2 first_eight（精选首发 8 卡；序=价值/依赖）

1. **`w03-debt-registration`**——依赖根：D-61…D-78 登记前，一切新卡占用闸 fail-closed（制度 §六.3）。零风险、一刀开路。
2. **`rt-e85-deploy-window`**——部署窗·安全轨最高紧迫：P5 移交已终审就绪（自证全 PASS+正本零触碰），gov T1 需 root 侧排期；主代理在场即开窗。
3. **`rt-e161-deploy-window`**——同窗第二刀：scheduler 换正本+manifest 转正（六步清单就绪），与 RT-E85 共用部署窗注意力。
4. **`w03-template-supply-batch`**——最大单卡：76/78 模板供给缺口=44 条 compilable 全体的可跑面（编译门绿≠跑得起）；T1→T3 分批可并行。
5. **`wave-runner-batch-merge-policy`**——runner 三件套之首（运营者①）：wave-02 已人工证单树六支零冲突，固化后每波省 N 棵树/targets（根治自造 ENOSPC）。
6. **`kb-math-lenient-batch`**——KB 口径批主卡：~40 条翻案预裁输入+62 条实测池+7 条翻案样板在场，机械可判。
7. **`otel-bak-drop-20261105`**——gov 小手术：复验清单七条就绪（含 ttl-drift 红如实单列），DROP 后审计面回 8 表承诺。
8. **`swev-pool-expand-pull`**——队列供给活口：pending=11<20 闸常红、no_candidates 已机读；扩源 392 可扩题+磁盘过护栏，先于放弃案试一刀。

（未入首发但有依赖的强候选：`kb-return-99-adjudication`/`swev-pool-abandon-backoff` 待主代理/运营者裁令；`s17-harness-gate-adoption`/`telemetry-gate-template-adoption` 待对应本体合线；`wave-02-final-push-ledger` 已在本监推进中，跟单不占首发名额。）

## §3 边界与未决（如实）

1. **anolis 在役全量门结果未亲验**：exec_a8fba407（11:10 起本监）的完成态本件未读（只读到单树六支合并 log）；G1 的 push/ledger 前置以其结果件为准。
2. **base_sha 未钉**：本地 product/main ref stale（2de44533）；wave-03 派卡前须 `git fetch origin` 实读（本件不预设）。
3. **「telemetry 模板面」为解释性映射**：仓内无同名债务；本卡按观测三门未接线+sidecar 在役红+otel-ddl TTL 面映射（F2 卡内已注记替代解释=并入 A1）。若主代理本意非此，F2 应重立范围。
4. **KB ~40/24 为预裁输入**：本件实测上界=62 条 math/归一相关非 admit 行、34 条不在库；预裁子集名单须主代理确认后逐条过四问，不壮胆凑数。
5. **部署窗两卡不可被 runner 派发**：channel=deploy-window 态不在 runner 状态机（`tools/wave-runner.py:305`），主代理按制度 §四②亲自执行；草案只给验收门。
6. **swev-pool-gen state 工作区双写件缺席**：`状态观测/swev-pool-gen-state.json` 在本机未见（anolis 在役件 10:58 亲读有值）——双写第二址失效或路径差异，已计入 E1/E3 验收以 anolis 侧为准；建议 E3 或杂项卡顺带核对双写链（未单独立卡）。
7. **债号 D-61…D-78 为建议顺延号**（现正本最大 D-59 实测），A0 登记时以正本实测最大号顺延，防撞号。
8. 本件**零施工、零账本写**：只读 af 仓/工作区/anolis（ssh 均为只读命令：cat/ls/df/git log）；未跑任何门套件全量、未触任何库/正本。

## §四 指纹

- 实测命令清单见 §0 表（13 项，全部本会话亲跑）。
- 关键坐标：`30-工件/strategies17-供给面设计-20261106.md:50/182`（模板缺口+单列建议）；`af/packages/README.md:77-82`（装载核对 EX4001-4003）；`af/poc/poc-p3-a1-strategy-dsl/README.md:109/122`（断点 (a)）；`tools/wave-runner.py:135-167/265-280`（合线+落账+监督轨注释）；`tools/anolis-env-check.sh:1-16`；`tools/swev-pool-gen.py:26-34/214-294/407-413/438-458`；`30-工件/RT-E85轨-20261105/P5-移交.md:28-42/87-99`；`30-工件/RT-E161轨-20261106/rt-e161-test-manifest-登记行提案.md:7-24`；`30-工件/KB清偿轨-20261105/out/absorb-mechanical-20261106-residue.jsonl`（38+99）；`计划/变更日志.md:47907/48417/48422/48586-48608/48605/48611`；`工具状态备份/mes-ttl-sweep-evidence.jsonl`（末条 otel 审计）；`af-state/dispatch/exceptions.jsonl`（末段）。
- 本件路径：`30-工件/波次自转器-20261106/wave-03-draft.md`（工作区，非 af 仓）。
