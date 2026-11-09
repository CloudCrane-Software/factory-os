# bench 多角色冷交接协同规格书 · astropy__astropy-8872（v1.1 · 2026-11-09）

> **冻结声明（v1.1 升版）**：本件 = astropy__astropy-8872 多角色冷交接协同的行为契约。v1.0
> （2026-11-08）随目录落成冻结；本版 v1.1（2026-11-09）依运营者裁决载体——板面 issue #264
> （wave-19 · w19-d169-bench-layout-recon，债号 D-169，锚补全段=裁决 #31 planner preflight
> 产物）——升版，旧版留档不改写：`SPEC.md.v1.0.bak`（sha256 =
> `c76726d9d08802780c36360383b2ec1d80d3c7d965ec13f1b399ffc1253ce5a1`）。
> 冻结后禁改：任何条款修改须经运营者裁决并升版号（v1.2），旧版留档不改写；角色派发件与本
> 规格冲突时，以本规格为准并停手报告，禁自行改规格迁卡面。
> **判官件纪律**：`tools/swev-judge-v2.py` 零改动零触碰（只读消费）；判据面只许变严（加门可以，
> 放宽官方谓词不可以）。对齐范式：D-117 bench 卡范式（`30-工件/夜轨A2-20261107/d117-dispatch-prompt.md`
> §转发段 + `d117-card-body.md`）、D-106 warm-relay 五步形制、D-118 协同压测 SPEC/信息损耗审计形制
> （`30-工件/协同压测-20261107/SPEC.md`、`集成腿-D118-信息损耗审计-20261107.md`）。
>
> **v1.1 改动清单（D-169 · 复盘 F1/F3 收敛；逐项对应 retrospective.md §三.1/§三.2）**：
> 1. **判分相二选一收敛（F1，留一删一）**：判分归属 = **测试员腿全链**（§4.3-6 调用 §4.4 判分腿，
>    唯一产生点）；编排器原独立「判分执行员」复判相**删除**（v1.0 实跑两轮 judge.json cmp 逐字节
>    同、冗余墙钟 ~5m——复盘 §一/§三.1 实证）。§4.4 落 `judge-producer-site` 唯一产生点标记；
>    §4.7 编排模板条款明文禁独立判分/复判相。复判留痕件（judge-rejudge.* / warm-relay-r1-rejudge.json /
>    prejudge-gate-r1-rejudge.log）= 已删相历史 attestation，留档不再产生。
> 2. **§二布局表对账清零（F3）**：布局表改用编排器/实盘**实名**（v1.0 表 20 位中 6 缺＋5 同物异名
>    清零——2026-11-09 施工前机械复现读数：缺名 6 = card×4＋A5＋timing-ledger；同物异名 5 =
>    diagnosis/fix.patch/impl-notes/test-report/review）；旧 A-名以映射表留档；机器可读布局清单
>    供 `layout-recon.py` 对账（施工须知①固化件）。
> 3. **验收命令书按实盘名参数化（F3）**：§4.1/4.2/4.3/4.5 验收命令全部改指实盘名；§4.2-3 节名
>    二选一统一为实盘形制 `^## 一、改动点`（原 `^## 修复说明` 对 impl-notes.md 实测 rc=1——
>    复盘 §三.2 字面验收红，本条即其修复）。
> 4. **编排模板入目录（F1/F3 挂载面）**：编排器模板坐标 = 本目录 `bench多角色复杂协同真跑.dwf.ts`
>    （原 `.zcode/workflow-drafts/` 草稿位已不在盘——两份契约零对账的根源；v1.1 起模板随目录落档，
>    与本规格同面收对账门约束，见 §4.7）。
> 5. A5 机读损耗账义务入编排面 ask（复盘 F2 的 SPEC 侧条款化；本跑未落盘如实注记，见 §4.5）。

## 〇、任务与已核事实（本节每条 2026-11-08 设计会话实跑核得，核法随条注；v1.1 未改本节）

- **任务**：SWE-bench 单体 `astropy__astropy-8872`（repo=astropy/astropy ｜ version=3.1）。
  题面 = `anolis:/data/bench/swev-s1-r0/astropy__astropy-8872.json`（10,795B，ls 实测），
  内嵌键 `base_commit / eval_script / fail_to_pass / hints_text / image / instance_id /
  pass_to_pass / problem_statement / repo / test_patch / version`（键名清单实测）。
- **题面规模**：problem_statement 887B ｜ hints_text 425B ｜ base_commit =
  `b750a0e6ee76fb6b8a099a4d16ec51977be46bf6` ｜ eval_script 1,659B（sha256[:12]=`53d61fbde8b8`）
  ｜ test_patch 963B（sha256[:12]=`975b09236ecb`，与任务给定指纹一致；施加面仅
  `astropy/units/tests/test_quantity.py`——指纹级/路径级实测，内容零外流）。
- **判分规模**：FAIL_TO_PASS **1** 项 / PASS_TO_PASS **80** 项（清单与内容 harness 侧持有，
  公开面只给计数——D-117 §八口径）。判分谓词：`diff_valid=true ∧ F2P 1/1 ∧ P2P 80/80 →
  resolved=true`（swebench `get_resolution_status`，`tools/swev-judge-v2.py:463-490`）。
- **判分镜像**：anolis 在盘 `swebench/sweb.eval.x86_64.astropy_1776_astropy-8872:latest`，
  Image ID `468c8d10c1fc`（docker images 实测；任务给定 4,354,980,026B 同物）。`/testbed`
  位于 base_commit（合成 SWE-bench 提交，与上游 blob 不同——cb-judge.sh 头注两次实证，patch
  施加以官方 `git apply` 首档、GNU `patch -p1 --fuzz=3` 兜底，见 §4.3）。
- **取码路（施工/调查腿）**：codeload 白名单路已证——本设计会话实测
  `curl -sSL https://codeload.github.com/astropy/astropy/tar.gz/b750a0e6ee76fb6b…` HTTP 200，
  tarball **7,175,498 字节**，sha256 =
  `c88679148be78ac37d392374b38cabdf1012bc05566297ebd93c5795924e0134`，解压顶层目录
  `astropy-b750a0e6ee76fb6b8a099a4d16ec51977be46bf6/`（astropy/units/ 下 64 文件在树）。
  管道慢（约 100KB/s，60s 超时不够、300s 内完成）——与 D-107「codeload 通但慢」读数同源，
  预算按 ≤6 分钟给。
- **判分缓存**：`anolis:/data/bench/swev-judge-cache/tasks/` 现有条目 = 7606/11133/11141/11149
  四实例（ls 实测），**8872 无条目 ⇒ 判分前 warm-relay 预热必行**（未命中 fail-closed，禁裸判）。
- **判官件活跃面**：本侧两部署路径 sha256 均 =
  `4a7156dd5e45197f7d8ab39be236eb9bb7a0ce7af220bca2395f863d71133389`（`repos/factory-os/tools/swev-judge-v2.py` 与 `tools/swev-judge-v2.py`，
  sha256sum 实测同值；即任务给定活跃面 `4a7156dd5e45…`）。pre-judge 对账门本设计会话实跑
  **绿（rc=0）**：`python3 -I tools/judge-deploy-recon-gate.py --pre-judge --fos-root
  repos/factory-os` → J1/J5 活跃面对账 PASS、H4 历史冻结对账 PASS、结论「绿（pre-judge 放行）」。
- **备选同池材料（top3②③，本卡黄段才启用，见 §4.6 回环终局）**：
  `anolis:/data/bench/swev-s1-r0/astropy__astropy-7671.json`（4,955B）与
  `astropy__astropy-7166.json`（4,455B）在盘；镜像 `sweb.eval.x86_64.astropy_1776_astropy-7671`
  （`ea67d17c5e18`）与 `…_astropy-7166`（`4b46c9269732`）在盘（docker images 实测）。
- **参照读数**：D-117 全环 43m25s 时间轴 + S1–S9 自动拉起清单
  （`30-工件/夜轨A2-20261107/cnb真沙箱bench环-读数-20261107.md`）；D-106 warm-relay 五步读数
  （`30-工件/D-106-判分自足-20261106/warm-relay-readings.json`：五步全绿 9.5s 量级）。

## 一、总则与纪律（全角色约束，违一条即该工件不收卷；v1.1 未改本节）

1. **冷交接原则（本规格第一原则）**：多角色互相不见会话历史；**交接工件（§二布局所列）是唯一
   信息通道**。每角色只收：本规格 §四 给它的「输入工件 + 任务材料 + 本节纪律」。角色不得反问
   上游、不得自行去读上游工作目录；发现输入缺失/矛盾 ⇒ 停手报告（诚实纪律），禁猜补。
2. **两级信息面（泄题防线）**：
   - **内档面**（harness 侧持有：test_patch 内容、F2P/P2P 清单、逐字测试 ID、判分日志全文）
     ——仅测试员与判分腿在履职中可触；**逐字 ID 禁出内档**（D-117 §七口径：失配项逐字 ID 留
     内档坐标、公开面只给计数 + 结构级归因）。
   - **交接面**（题面卡面、诊断报告、patch、结构级读数、裁决）——跨角色流动的唯一面。
   - 施工员与评审员**永不在内档面**：禁查上游 astropy 官方修复提交/PR；禁搜 `astropy-8872
     patch` 类关键词；禁翻 SWE-bench 数据集/答案件；禁访问除题面给定下载域（codeload.github.com、
     pypi）外的外部网络。
3. **禁改测试件**：任何角色的交付物不得触碰 `*/tests/**`、`test_*.py`、`tests.py`（判分测试由
   判分链统一施加；改测试件 = 作弊形态）。
4. **禁改判分链**：`tools/swev-judge-v2.py`、判分镜像、判据面、pre-judge 门、warm-relay 链
   一概零改动零触碰（只读消费）；判分链自身红 = 环接不住，如实判不通，禁人工抢救。
5. **anolis 纪律**：Σmem≤45G、并发≤4（硬顶）；判分腿 mem 预算 8G（D-117 卡面先例）、测试腿
   8G（单镜像单容器）；任一时刻活跃容器 ≤3、活跃角色会话 ≤4，不并线超顶。测试类进程环境
   **剥离代理/凭据类 env**（HTTP(S)_PROXY、*_TOKEN、*_KEY 等；cargo 纪律通则对 Python 腿同款
   适用），与判分腿 hermetic 口径（live_http=[] / blocked_urls=[]）同源。
6. **ssh 只读 + 工作目录内写**：对 anolis 的 ssh/docker 会话默认只读；写只许落
   `/data/bench/bench多角色-8872/**`（本卡施工判分目录）与 warm-relay 的
   `/data/bench/swev-judge-cache/**`（既有判分缓存面，D-106 形制内）；系统面、他卡条目、
   他债号目录零触碰。
7. **凭据零打印**：token/密钥经 openBao 程序化现取（0600、不打印、不落日志、不进 argv——
   D-117 §九既证纪律）；一切工件/评论/日志正文零凭据形态（只允许 sha256[:12] 指纹与掩码）。
8. **warm-cache fail-closed**：判分缓存未命中 ⇒ 先预热（§4.4）再判；禁在未预热实例上裸跑判分。
9. **诚实纪律高于完成度**：没跑的写成没跑（not_run + 理由），红的写红的；自报读数只作参考，
   判分以 anolis 判分腿重跑为准；交部分结果 + 写明缺口 > 假完整交卷。
10. **git 不可逆动作全禁**：禁 `--force`、禁 `reset --hard`、禁改写已推历史；路径外零改动
    （各角色只写本规格 §二布局内自己的落档位）。

## 二、目录布局（冻结 v1.1 · 实盘名对账版；全部落 `30-工件/bench多角色-20261108/`）

> v1.0 布局为树形图＋A-名（见 `SPEC.md.v1.0.bak` §二），与编排器实盘投递名漂移（复盘 §三.2：
> 20 位中 6 缺＋5 同物异名，§4.2-3 字面验收实测不过）。v1.1 改为**机器可读布局清单**（行式 =
> 相对路径；`#` 行 = 面标记），由 `layout-recon.py`（本目录收敛施工件）做双向对账：清单内每名
> 须在盘命中、盘上每件（除声明忽略的施工暂存树）须入清单——缺名/异名/孤儿件任一 >0 即 rc=1
> 点名（D-169 施工须知①固化）。

### 布局清单（冻结 v1.1 · 机器可读面）

```text
# face:run 运行工件（编排器/角色实盘名 · 2026-11-08 跑落档）
SPEC.md
diagnosis.md
fix.patch
impl-notes.md
test-report.md
A3-test-readings.md
A3-test-readings.json
review.md
retrospective.md
judge/task.json
judge/eval.sh
judge/baseline_log.txt
judge/judged_log.txt
judge/probe_dtype.py
judge/regression_baseline.txt
judge/regression_judged.txt
judge/warm-relay-r1.json
judge/warm-relay-r1-rejudge.json
judge/prejudge-gate-r1.log
judge/prejudge-gate-r1-rejudge.log
judge/judge.json
judge/judge.stderr
judge/judge-rejudge.json
judge/judge-rejudge.stderr
# face:meta 收敛施工件（D-169 · 2026-11-09 落档）
SPEC.md.v1.0.bak
bench多角色复杂协同真跑.dwf.ts
layout-recon.py
d169-recon-readings.md
dryrun-report.json
```

**v1.0 → v1.1 名位映射与缺件处置（对账依据，逐项）**：

| v1.0 表名 | v1.1 处置 | 实盘名/说明 |
|---|---|---|
| A1-diagnosis.md | 同物异名收敛 | `diagnosis.md`（调查员实盘投递名） |
| A2-patch.diff | 同物异名收敛 | `fix.patch`（施工员实盘投递名） |
| A2-report.md | 同物异名收敛 | `impl-notes.md`（施工员实盘投递名；报告骨架节 =「一、改动点」） |
| A3-test-readings.md | 保留表名（正本位） | 在盘；`test-report.md` = 同容别名留档（cmp 逐字节同，review.md §〇 注）——双档并列入清单 |
| A4-review-verdict.md | 同物异名收敛 | `review.md`（评审员实盘投递名） |
| timing-ledger.md | 替位注记 | 本跑由 `retrospective.md` §一替位（复盘 F7 落位差如实记）；后续跑由编排模板复盘相落档（§4.7 相义务） |
| A5-loss-metrics.json | 未落盘如实注记 | 本跑未落（复盘 §二缺口/F2 债）；§4.5 义务保留＋编排面 ask 已加落盘义务；落盘后入 face:run 清单 |
| card-investigator/builder/tester/reviewer.md ×4 | 出布局（派发载荷） | 实跑为编排器 ask 直发（载荷段内嵌模板），未落独立卡面档——v1.1 起归 §4.7 模板 ask 载荷面；泄题机检留痕另卡收口（D-170） |
| Fb-r{n}.json | 条件件 | 回环触发才落（本跑 r1 resolved=true 不触发）；落盘后入清单 |
| judge/judge-rejudge.json（及 warm-relay-r1-rejudge/prejudge-gate-r1-rejudge/judge-rejudge.stderr） | 已删相留痕 | v1.0 编排器独立复判相产物（两轮 judge.json cmp 逐字节同 = attestation 价值留档）；§4.7 删相后不再产生 |

（判分腿的 anolis 侧落 `/data/bench/bench多角色-8872/`，与本目录 judge/ 镜像同拍留档。施工暂存树
`.build/`、`.tester-scratch/` 为施工期工作面，不属冻结布局，对账扫描声明忽略。）

## 三、角色链与依赖图（v1.1 未改结构，仅注名位）

```
                    H0 派发载荷（编排模板 ask 段内嵌各卡面 + 本规格对应节；不落独立卡面档）
H0① ──> 调查员 ──diagnosis.md──┐
                              ├──> 施工员 ──fix.patch + impl-notes.md──┐
        （施工员输入 = H0②+诊断+基线码）  ↑回环Fb-r{n}                ├──> 测试员 ──A3 读数──┐
        （测试员输入 = H0③+fix.patch+判分链操作权）                    │      │               ├──> 评审员 ──review.md 裁决 + A5 损耗账
                                                              │      └─判分腿（§4.4 warm-relay→门→swev-judge，零改动，唯一产生点）
                                                              │              └─judge.json verdict──> 回卡/台账
                                                              └────── resolved=false ⇒ 回环（≤2 轮，§4.6）
```

- **串行主干**：调查员 → 施工员 → 测试员（+判分腿）→ 评审员 → 复盘员；每段交接只过 §二所列工件。
- **判分腿独立于评审员**：评审员冷看三工件（诊断/patch/读数），不看 judge.json——评审裁决是
  质量面（一致性），官方 verdict 是判分面（resolved），两面在台账合流，互不代替（跑得通 ≠ 做
  对题，D-117 §六口径）。
- **判分产生点唯一（v1.1 · D-169）**：判分腿（§4.4）是 judge.json 的唯一产生点，由测试员腿
  §4.3-6 调用；编排层**禁**另设独立判分/复判相（§4.7）。
- **回环唯一权威触发 = 判分 resolved=false**；评审打回（矛盾项）作为质量信号并入同一轮预算，
  由编排面裁量是否当轮触发（两源合计 ≤2 轮，见 §4.6）。

## 四、逐角色规格（输入 / 输出 / 验收命令 · v1.1 实盘名参数化）

### 4.0 H0 派发载荷公共形制（四卡同款；范式 = d117-dispatch-prompt.md §转发段）

- 每派发载荷自包含：①禁项置顶（§一.2–§一.7 逐条落卡面）②卡面即任务（problem_statement 887B +
  hints_text 425B **逐字**嵌入；hints_text 允许给到调查员与施工员——属题面，非内档）③已核
  前提（§〇 相应行：base_commit、镜像名、codeload tarball 期望 sha256/字节数、判分规模**只给
  计数** F2P=1/P2P=80）④不许假设的前提 ⑤施工步与完成定义 ⑥验收命令 ⑦诚实纪律与停手条款。
- 派发载荷内嵌的题面从 anolis 题面 JSON 摘出后**落卡面前人工复核一次**（887B/425B 字节数对上才
  发车——禁夹带 test_patch/清单字段；发车前机检：卡面 grep `test_patch\|FAIL_TO_PASS\|PASS_TO_PASS`
  仅允许出现在「计数声明」行）。载荷以编排模板 ask 段投递（§4.7），不落独立 card-*.md 档；
  机检留痕件（dispatch-trace）由编排面落 judge/（D-170 收口项，v1.1 注记义务）。
- 一次卡一个会话；多卷交卷纪律照 D-117 教训：**以静默窗（≥5 分钟无新卷）后末卷为正本**，
  交卷后禁追加第二卷。

### 4.1 调查员（只出诊断报告，零代码）

- **输入工件**：H0① 载荷（含题面逐字 + §〇已核前提）+ 基线源码树
  （codeload tarball，§〇指纹核过后解压；只读参照）。
- **任务**：产出 `diagnosis.md`（v1.0 名 A1-diagnosis.md，同物异名收敛），必含六节：**① 问题复述**
  （题面事实清单，逐条标注来自题面哪一行）② **根因**（机制级：代码路径、触发条件、为何抛错/
  错行为；给出涉及的既有函数与行段定位方式）③ **修复方案**（逐文件一段：改什么、为什么这样改、
  预期行为变化 前红→后绿）④ **涉及文件清单**（逐个：路径 + 预期改动性质；**只许非测试文件**）
  ⑤ **风险**（回归风险点、边界情形、与既有行为的兼容性；每条给「施工员该如何自证未踩」的
  建议核法）⑥ **诚实注记**（复现了什么/没复现什么/不确定什么）。
- **允许**：只读跑最小复现（`python3 -c` 探针级命令；装不了依赖如实记 not_run + 理由）；读
  基线源码树。
- **禁止**：产出任何代码工件（diff/补丁/新文件内容）；改基线树；接触测试信息面（§一.2）。
- **验收命令**（编排面收卷时跑）：
  1. `grep -q '^## 根因' diagnosis.md && grep -q '^## 修复方案' diagnosis.md && grep -q '^## 涉及文件清单' diagnosis.md && grep -q '^## 风险' diagnosis.md` → rc=0（六节骨架在）
  2. `grep -cE '(^|/)(tests?/|test_[^/]*\.py)' diagnosis.md` → 输出 0（涉及面零测试文件）
  3. `grep -cE '^(diff --git|--- a/|\+\+\+ b/|@@ )' diagnosis.md` → 输出 0（零代码形态）
  4. `test -s diagnosis.md` → rc=0（非空）

### 4.2 施工员（只拿诊断报告 + 题面，出 patch）

- **输入工件**：H0② 载荷（题面逐字 + §〇已核前提）+ diagnosis.md + 基线源码树
  （codeload 同路取码，pristine，建 git 工作区供 diff 出土——d117-dispatch-prompt.md §三形制）。
  回环轮追加 Fb-r{n}.json（§4.6）。**禁收**：测试读数全文、judge.json、内档面一切。
- **任务**：按诊断报告施工，产出 **fix.patch + impl-notes.md**（v1.0 名 A2-patch.diff /
  A2-report.md，同物异名收敛；同末卷交付）：
  - patch = SWE-bench 格式 unified diff（`git apply` 可干净施加到 pristine 基线）；
  - impl-notes.md 五节（实盘形制，节名以「一、改动点」起头编号节）：① 改动点（**逐文件一行**，
    与 patch 触面集合一致）② 施工过程与取码链 ③ 自证记录（命令＋读数）④ 与诊断的偏差
    ⑤ not_run（诚实面）。v1.0 的「修复说明」节名形制废止（二选一统一——复盘 §三.2 字面验收
    红的修复项）。
- **允许**：改基线树非测试文件；基线树内跑最小复现自验（前红后绿）；跑基线树既有测试面查
  回归（既有面在基线树内、非判分件，可跑）。
- **禁止**：碰任何测试文件；为跑通放宽断言/改测试；顺手「修别的」（涉及文件 ⊆ 诊断清单，
  超出 = 矛盾项，见 §六对拍）；接触判分链与内档面。
- **验收命令**（编排面收卷时跑；基线树 = 按 §〇指纹重建的 pristine 副本）：
  1. `git -C <基线树> apply --check fix.patch` → rc=0（干净施加核）
  2. `grep '^diff --git' fix.patch | grep -E 'tests?/|test_' ` → 输出空、rc=1（零测试触面）
  3. `test -s fix.patch && grep -q '^## 一、改动点' impl-notes.md` → rc=0（实盘节名形制，v1.1 统一）
  4. 逐文件一致性（机检）：`grep '^diff --git' fix.patch` 的文件集合 = impl-notes.md 「一、改动点」
     节列出的文件集合（编排面 diff 两清单，不等 ⇒ 不收卷）
  5. patch 自身 sha256 留痕（`sha256sum fix.patch`，指纹入计时表与回卡评论）

### 4.3 测试员（anolis bench 环应用 + 任务测试 + 回归，出读数；**判分腿唯一调用方**）

- **输入工件**：H0③ 载荷 + fix.patch + 判分链操作权（task.json 在 anolis 的坐标、§4.4 链路
  命令书）。测试员是**唯一**在内档面履职的角色，但产出只落交接面结构级读数。
- **任务**（命令书 = D-117 判分读数.md §一–§六形制，逐条留读数入 A3）：
  1. **收件核**：pristine 基线（anis 镜像 `/testbed` checkout base_commit 或 codeload 树）
     `git apply --check fix.patch` rc=0 才收卷（官方 GIT_APPLY_CMDS 首档；若镜像内合成提交
     blob 拒收，GNU `patch -p1 --fuzz=3` 兜底——cb-judge.sh 头注既证坑，兜底使用须在读数记
     「首档拒收原因」）。
  2. **eval.sh 出土**：从 anolis 题面 JSON 直接提取 eval_script 落 judge/eval.sh
     （`python3 -I -c "import json;sys.stdout.write(json.load(open(T))['eval_script'])" > eval.sh`），
     sha256[:12] 必须 = `53d61fbde8b8`（不符 = 题面被动过，停手报告）。禁读/留存 test_patch
     与 F2P/P2P 清单内容（eval.sh 内含施加动作，允许；hunks 不摘抄）。
  3. **基线容器**（无补丁）：起镜像容器 → bash eval.sh → baseline_log.txt；读数 = 既有面汇总
     行 + F2P 基线红（1 failed 形态）——基线红 = 题目本体（D-117 §四口径）；**逐字失败 ID 只入
     judge/（内档），不进读数正文**。
  4. **判分容器**（施加 fix.patch）：起同镜像新容器 → 官方首档 git apply → bash eval.sh →
     judged_log.txt；读数 = 汇总行（passed/failed 计数）。
  5. **既有面回归**：判分容器上对**未施加 test_patch** 的基线测试面跑受影响区回归
     （`pytest astropy/units/ -x -q` 级别；确切面按诊断涉及文件邻域定），前（基线容器复用读数）
     后（判分容器）对账，任何 新红 记入读数并结构级归因。
  6. **判分腿**（§4.4，测完后立即接；**唯一产生点调用口**）：warm-relay 五步 → pre-judge 门 →
     swev-judge-v2.py → judge.json。A3 收录 verdict 的**结构级读数**：diff_valid、log_state、
     f2p_success/f2p_failure、p2p_success/p2p_failure、resolved、hermetic、live_http 是否空——
     逐字测试 ID 不入 A3。
- **输出**：`A3-test-readings.md`（人读，六步各节 + 诚实注记；本跑同容别名 `test-report.md`
  双档留档——v1.1 起正本位 = A3-test-readings.md）+ `A3-test-readings.json`（机读：每步命令、
  退出码、计数、产物 sha256[:12] 指纹）。
- **验收命令**（编排面收卷时跑）：
  1. `test -s judge/eval.sh && test -s judge/baseline_log.txt && test -s judge/judged_log.txt
     && test -s judge/judge.json` → rc=0（四产物在盘）
  2. `test "$(sha256sum judge/eval.sh | cut -c1-12)" = "53d61fbde8b8"` → rc=0（题面出土件对账）
  3. `python3 -I -c "import json;j=json.load(open('judge/judge.json'));assert j['diff_valid'] is
     True and j['log_state']=='parsed' and j['hermetic'] is True and j['live_http']==[] and
     j['blocked_urls']==[] and j['f2p_success']+j['f2p_failure']==1 and
     j['p2p_success']+j['p2p_failure']==80;print('verdict-shape-ok')"` → 输出 verdict-shape-ok
  4. `grep -cE 'astropy/units/tests/test_quantity\.py::test_[^ ]+ (FAIL|PASS)ED' A3-test-readings.md`
     → 输出 0（逐字测试 ID 不入交接面；汇总行计数形态除外）
  5. `test -s A3-test-readings.json` → rc=0

### 4.4 判分腿（官方 swev-judge，零接触；测完即判；**judge.json 唯一产生点**）

> judge-producer-site: spec-4.4-judge-leg（唯一判分产生点 · D-169 v1.1 收敛：判分归测试员腿
> 全链，§4.3-6 为调用口；编排层禁另设判分/复判相——§4.7。产生点计数由 layout-recon.py 断言
> ==1。）

- **判官件**：`tools/swev-judge-v2.py`（活跃面 sha `4a7156dd5e45…`，零改动零触碰；判据只许
  变严）。链 = **warm-relay 五步（D-106 形制）→ pre-judge 对账门 → 官方判分**：
  1. **warm-relay**（8872 无缓存条目，必行）：`bash repos/factory-os/tools/swev-warm-relay.sh
     --task <题面 JSON 本侧副本> --out judge/warm-relay-r{n}.json --remote anolis
     --remote-dir /data/bench/swev-judge-cache`——五步（1-warm-local / 2-judge-attest /
     3-cache-relay / 4-task-push / 5-remote-verify）任一步败即 fail-closed 停判（D-106 读数
     量级 ~10s；step2 即远端判官件 sha 对账：远端缺失推本侧件、不一致不覆盖）。
  2. **pre-judge 门**：`python3 -I tools/judge-deploy-recon-gate.py --pre-judge --fos-root
     repos/factory-os --cache-dir <本侧缓存视图>` → 结论绿才判（L1 部署面对账 + L3 记录面双
     sha；本设计会话已实跑绿 rc=0，判分机侧带 --cache-dir 验 L3；红/不可证 ⇒ 拒判翻
     judge_blocked，不落结果行——cb-run.py:85-96 语义）。
  3. **官方判分**：`SWEV_JUDGE_V2_CACHE=/data/bench/swev-judge-cache <venv-python>
     swev-judge-v2.py task.json judge/judged_log.txt fix.patch > judge/judge.json
     2> judge/judge.stderr`（D-117 §六同构；judge_rc=0 且 stderr 0 字节为链健康态）。
  4. **verdict 口径（冻结）**：`resolved=true ⇔ diff_valid=true ∧ f2p 1/1 ∧ p2p 80/80`；
     任一不满足 ⇒ resolved=false 如实判，禁人工抢救、禁为过判改判据/判官件。
- **验收命令**：
  1. `python3 -I -c "import json;j=json.load(open('judge/warm-relay-r{n}.json'));assert
     j['all_ok'] is True and j['fail_step'] is None;print('warm-ok')"` → warm-ok
  2. `grep -q '结论：绿' judge/prejudge-gate-r{n}.log` → rc=0
  3. `test ! -s judge/judge.stderr` → rc=0（判分腿无 stderr——D-117 §六健康态）
  4. 判官件前后指纹一致：判分前后 `sha256sum` 活跃部署面均 = `4a7156dd5e45…`（计时表留痕）。

### 4.5 评审员（冷看三工件，出裁决意见 + 损耗账）

- **输入工件（仅此三件 + 本卡面）**：diagnosis.md、fix.patch（+impl-notes.md）、
  A3-test-readings.md/.json。**禁收**：judge.json、任何会话历史、上游任何档案；不接触基线树
  亦可完成（对拍是文本面工作；如需代码事实核引文，可自取 codeload 基线只读比对）。
- **任务**：产出 `review.md`（v1.0 名 A4-review-verdict.md，同物异名收敛）+
  `A5-loss-metrics.json`：
  - review.md 裁决意见：① 工件指纹行（`key_for:` 三行，sha256[:12]——ANC-5 换键口径：裁决键
    钉被测件版本指纹，工件换版 ⇒ 显式换键重审）② 逐工件审查意见（诊断四节齐备性/自洽性；
    patch 与诊断同向性；测试读数对 patch 行为主张的证实度）③ **findings**（逐条：F#、严重度、
    证据坐标 = 工件内行级引用）④ **裁决 = 采纳 | 打回**（打回必附矛盾项 F# 与回环建议段）⑤
    诚实注记。引文纪律：每条 finding 的引文必须真实存在于所引工件（抽查 grep 可复算）。
  - A5 损耗账：按 §六 schema 逐 junction 落数。**编排面 ask 义务（v1.1 · 复盘 F2 条款化）**：
    评审员 ask 必含「另落 A5-loss-metrics.json（§六 schema，§4.5-4 验收）」一句——本跑（v1.0）
    未落盘，复盘 §二已如实记 not-run-able，属欠账不属合规。
- **裁决语义**：采纳 = 质量面放行（工件链自洽）；打回 = 存在矛盾项（§六定义）或关键缺失。
  评审裁决不改变官方 verdict（判分面独立）；打回信号交编排面按 §4.6 裁量。
- **验收命令**（编排面收卷时跑）：
  1. `grep -c '^key_for:' review.md` → 输出 ≥3（三工件指纹齐）
  2. 三指纹实测：review.md 三个 key_for 值逐一 = `sha256sum` diagnosis.md / fix.patch /
     A3-test-readings.md 取 [:12]（编排面 diff 判等）
  3. `grep -q '^## findings' review.md && grep -qE '^## 裁决' review.md` → rc=0
  4. `python3 -I -c "import json;m=json.load(open('A5-loss-metrics.json'));assert
     set(m['junctions'])=={'H1','H2','H3','H4'} and all('loss_rate' in v for v in
     m['junctions'].values());print('loss-schema-ok')"` → loss-schema-ok
  5. 引文真实性抽核（编排面抽 2 条）：review.md 引文在所引工件内 grep 得中 ≥1 次

### 4.6 修复回环（判分不过 → 测试员反馈 → 施工员修；≤2 轮）

- **触发**：judge.json `resolved=false`（唯一权威触发）；评审打回为辅信号，同一预算池，编排面
  裁量。回环轮次 r = 1,2；**两轮后仍 resolved=false ⇒ 终局 not_resolved 如实闭环**（D-117 口径：
  全链走完 + 归因清晰 = 环成功；禁人工抢救判分）。
- **Fb-r{n}.json 反馈件（结构级，测试员产出；条件件——回环触发才落盘）**：
  `{round, verdict(resolved), diff_valid, f2p:{success,failure}, p2p:{success,failure},
  failed_leg("F2P"|"P2P"|"diff"|null), 失配归因(结构级: 形态描述——断言差/异常类型差/ID渲染
  形态差/超时/环境缺依赖…), 既有面回归读数(测试员自己的非内档读数，可给全文), 诚实注记}`
  ——**禁逐字测试 ID、禁 test_patch 内容、禁判分日志原文**（内档面不外流，§一.2）。
- **施工员回环输入** = 原输入（H0② + 诊断 + 基线树）+ Fb-r{n}.json + 自己上一轮 fix.patch
  （可自读复盘）；产出 fix.patch v(n+1) + impl-notes.md v(n+1)（同 §4.2 验收重跑）。
- **判分腿每轮全量重跑**（仍在测试员腿内、§4.4 唯一产生点）：warm-relay（幂等，可重跑）→ 门
  → 基线容器（每轮复跑基线红核对，防镜像漂移假阴）→ 判分容器 → judge.json r{n}（judge/ 下
  按轮留档）。**编排层不得另设复判相重复此链**（v1.0 实跑曾双跑：两轮 judge.json cmp 逐字节
  同、冗余墙钟 ~5m——D-169 已删，见 §4.7）。
- **终局**：任一轮 `resolved=true` ⇒ 环成功收卷，回卡；r=2 仍 false ⇒ 终局 not_resolved，
  如实回卡 + 台账（黄段：若运营者裁决转备选题 7671/7166，须**新开卡**走本规格全链，
  禁在本卡会话内续跑——冷交接纪律不破）。

### 4.7 编排层（编排器模板 · v1.1 新增条款；D-169 F1/F3 挂载面）

- **模板坐标（冻结）**：`30-工件/bench多角色-20261108/bench多角色复杂协同真跑.dwf.ts`
  （随目录落档；v1.0 实跑模板在 `.zcode/workflow-drafts/` 草稿位、跑后不在盘——两份契约零
  对账的根源，v1.1 收编入目录受对账门约束。该件为**重建件**：结构依据 retrospective.md §一/§三
  与 actor 留痕复原，非原脚本字节拷贝——头部注记声明）。
- **相序（冻结）**：选题员 → 设计员（写 SPEC）→ 调查员（diagnosis.md）→ 施工员（fix.patch +
  impl-notes.md）→ 测试员（读数 + 判分腿全链，**唯一判分产生点引用：judge-ref: spec-4.4-judge-leg**）
  → 评审员（review.md + A5-loss-metrics.json）→ 复盘员（retrospective.md + timing-ledger.md）。
- **判分相归属（冻结 · 留一删一裁决）**：判分 = **测试员腿全链**（§4.3-6 → §4.4）。编排层
  **禁**另设独立「判分执行员」/复判相（v1.0 曾设：两轮 judge.json cmp 逐字节同、冗余墙钟
  ~5m，复盘 §三.1——D-169 删）。模板相清单零判分相；`judge-producer-site` 标记全契约面计数
  必须为 1（layout-recon.py 断言，施工须知②固化）。
- **BASE 路径（冻结）**：模板内一切工件坐标 = 本规格 §二布局清单实盘名（v1.0 漂移源
  「.dwf.ts:8 BASE 路径硬编码在先」收编：模板与 SPEC 同源对账，layout-recon.py 双向扫描）。
- **派发载荷**：H0①–④ 载荷段内嵌模板 ask（不落独立 card-*.md 档）；§4.0 发车前机检由编排面
  执行并落留痕件 judge/dispatch-trace.json（D-170 收口项；v1.1 注记义务，未实现前如实记缺）。
- **对账门（冻结）**：每跑收口与每次模板/SPEC 改动后，跑 `python3 -I layout-recon.py`
  （本目录）：①布局对账（§二清单 ↔ 盘面双向，缺名/异名/孤儿点名，rc=0 才绿）②判分产生点
  唯一性（judge-producer-site 计数==1 ∧ 模板零判分相签名，rc=0 才绿）③SPEC/模板改前 .bak +
  改前后 sha256 对账留痕（施工须知③）。

## 五、计时点（冻结表；每点证据坐标 = mtime / JSON 字段 / 评论 id，落 timing-ledger.md）

| # | 计时点 | 证据坐标 | 预算锚（在案实测） |
|---|---|---|---|
| T0 | SPEC 冻结（v1.0 落档；v1.1 升版同位留档） | SPEC.md mtime | — |
| T1 | 调查员派发（H0① 载荷发车） | 派发留痕 | — |
| T2 | diagnosis.md 落档（六节验收过） | diagnosis.md mtime + 验收命令读数 | 调查腿 ≤40min（含取码 ≤6min） |
| T3 | 施工员派发（含诊断投递） | 派发留痕 | — |
| T4 | fix.patch 末卷收卷（静默窗后取末卷） | fix.patch mtime + sha256[:12] 留痕 | 施工腿 ≤60min（D-117 实测 10m11s 量级） |
| T5 | 收件核过（apply-check rc=0） | A3.json 第 1 步字段 | ≤10min（D-117 实测回收后 10m02s 量级） |
| T6 | 测试腿起（基线容器起跑） | baseline_log.txt mtime | — |
| T7 | 基线容器读数落档 | baseline_log.txt mtime | ≤2min（D-117 实测 11s） |
| T8 | 判分容器读数 + 既有面回归落档（A3 成卷） | judged_log.txt / A3 mtime | ≤5min（D-117 实测 13s + 回归余量） |
| T9 | warm-relay 五步全绿 | warm-relay-r{n}.json `all_ok=true` | ~10s（D-106/D-117 实测 9.5s） |
| T10 | pre-judge 门绿 | prejudge-gate-r{n}.log 结论行 | ≤1min（本会话实跑 <5s） |
| T11 | judge.json 落盘（verdict；唯一产生点） | judge.json mtime + judge_rc=0 | 判分腿全段 ≤3min（D-117 实测 2m33s） |
| T12 | verdict 回卡/台账翻格 | 评论 id / 台账行 | ≤10min |
| T13 | 回环触发→Fb-r{n} 落档→施工员再派发 | Fb-r{n}.json mtime | 每轮 ≤90min（T4–T11 重走） |
| T14 | 评审员派发（三工件投递） | 派发留痕 | — |
| T15 | review.md + A5 落档 | review.md / A5 mtime | 评审腿 ≤30min（D-118 实测 ~8m 量级） |
| T16 | 全环收口（timing-ledger 落档） | timing-ledger.md mtime | 全环目标 ≤3h（单轮 D-117 实测 43m25s） |

（计时刻度只对本链事件；角色内部自由用时不设限，只卡各段预算锚与总顶。人工现身目标 0 次。
v1.0 跑 T16 落位差：timing-ledger.md 未落，由 retrospective.md §一替位——复盘 F7 如实记；
后续跑由编排模板复盘相负责落档，禁再替位。）

## 六、损耗度量（交接处信息丢失 = 评审员事后对拍；落 A5-loss-metrics.json）

**定义**：损耗 = 上游工件携带的信息在交接后未在下游工件落地的部分。度量法 = 评审员事后对拍
（范式 = D-118 信息损耗审计：冷读导出 vs 成品对拍、逐项判 一致/偏移/丢失/矛盾、答对率即保真度）。
**主度量 = H2（诊断报告 → patch）**——任务指定：评审员将 diagnosis.md 的可核查断言集逐条对拍
fix.patch 落地。

- **对拍项集（各 junction）**：
  - **H1 题面 → 诊断**：题面事实清单（复现 traceback 指明的文件与行段定位、期望行为、报错
    形态）逐条 vs diagnosis.md ①/② 节。丢项 = 题面明示事实诊断未覆盖。
  - **H2 诊断 → patch（主度量）**：诊断 ③修复方案逐文件要点、④涉及文件清单、⑤风险处置建议
    vs fix.patch 实际触面与改动 + impl-notes.md 偏差节。判级：**一致**（落地且同向）/
    **偏移**（落地但方式或范围偏离诊断，未违排除项）/ **丢失**（诊断提出、patch 未落地且
    未给理由）/ **矛盾**（patch 做了诊断明确排除的，或根因另起炉灶）。
  - **H3 patch → 测试读数**：impl-notes 自证主张 vs A3 既有面前后读数能否证实（自证 not_run
    时 A3 是否如实记录而非脑补绿）。
  - **H4 三工件 → 裁决**：review.md 每条 finding 的引文坐标真实性（抽查 grep）+ key_for 指纹
    正确性——裁决链自身不引入新信息噪声。
- **公式（每 junction）**：`保真率 = (一致 + 0.5×偏移) / 对拍项总数`；
  **损耗率 `loss_rate = 1 − 保真率`**。
- **门槛（放行判据，冻结）**：`H2.loss_rate ≤ 0.20`（保真率 ≥80%，D-118 实测口径 4/5=80%）
  **且全表矛盾项 = 0**，否则裁决必须 = 打回（矛盾项必打回，偏移项评审裁量）。
- **A5-loss-metrics.json schema（冻结）**：

```json
{
  "spec": "30-工件/bench多角色-20261108/SPEC.md",
  "spec_sha256_12": "<SPEC.md sha256[:12]>",
  "task": "astropy__astropy-8872",
  "review_round": 1,
  "key_for": {"diagnosis": "<sha256[:12]>", "fix_patch": "<sha256[:12]>", "a3": "<sha256[:12]>"},
  "junctions": {
    "H1": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0,
           "items": [{"claim": "<上游断言>", "downstream": "<下游坐标>", "grade": "consistent|offset|lost|contradiction", "note": "<一行为什么>"}]},
    "H2": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0, "items": []},
    "H3": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0, "items": []},
    "H4": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0, "items": []}
  },
  "gate": {"h2_max_loss_rate": 0.20, "contradiction_required": 0, "pass": true}
}
```

（schema 内 key_for 键名 v1.1 改实盘名；验收命令 §4.5-4 只查 junctions 集合与 loss_rate 在场。）
- **回环减损证据**：每轮回环后，评审员对拍账按轮追加 `review_round` 行；若第 r 轮某丢失项在
  r+1 轮转一致，即「损耗可测、可修、可复验」的实证（D-118 反事实注记同款）。

## 七、集成验收（全链收口，编排面跑）

1. §4.1–§4.5 各验收命令全过（逐条留 rc 读数入 timing-ledger.md）。
2. `python3 -I -c "import json;j=json.load(open('A5-loss-metrics.json'));assert
   j['gate']['pass'] is True;print('loss-gate-pass')"` → loss-gate-pass（本跑 v1.0 未落 A5，
   如实 not-run-able——复盘 §二；后续跑起为硬验收）。
3. judge 链健康三件：warm-relay all_ok=true、pre-judge 门绿、judge.stderr 0 字节。
4. 纪律终检：diagnosis.md / impl-notes.md / test-report.md / review.md 正文
   `grep -rE '(BEGIN (RSA|OPENSSH) PRIVATE KEY|ghp_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})'`
   → 全 0 命中（零凭据形态）；fix.patch 触面零测试文件（§4.2-2 重跑）。
5. 计时表齐：T0–T16 每行有证据坐标；人工现身计数 = 0（回卡评论/台账行佐证）。
6. 台账与回卡：verdict（resolved + F2P/P2P **计数** + patch sha256[:12] + 失配归因结构级 +
   裁决摘要）回卡/台账；测试清单只给计数、零凭据形态（D-117 §八口径）。
7. **对账门（v1.1 新增）**：`python3 -I layout-recon.py --root .` 全绿——①布局对账 rc=0
   （§二清单 ↔ 盘面双向零差）②判分产生点唯一性 rc=0（producer 计数==1 ∧ 模板零判分相签名）；
   读数留档 d169-recon-readings.md（首跑读数即该件，后续跑追加）。

## 八、冻结纪律与诚实性条款

- 本规格 v1.0 冻结于 2026-11-08 落档时刻；v1.1 升版于 2026-11-09（issue #264 · D-169）；
  再改 = 运营者裁决 + 升版 + 旧版留档（现行旧版档 = SPEC.md.v1.0.bak）。
- 各角色派发载荷逐字嵌本规格对应节；冲突 ⇒ 停手报告，禁自行改规格。
- 诚实性高于完成度：任一腿做不完交部分结果并写明缺什么；verdict 如实判（resolved=false 也
  闭环——跑得通 ≠ 做对题，D-86/D-107/D-117 三卡同口径）。
- 本规格为设计件：§〇 所列事实为设计会话实跑核得；判分腿各命令在执行会话须全量重跑留读数，
  禁引用本规格读数代替执行腿实跑（自报读数不作证据）。

（v1.0 落定：2026-11-08 · 分解设计员 ｜ v1.1 落定：2026-11-09 · D-169 施工员（板面 issue #264，
wave-19）· 改前档 SPEC.md.v1.0.bak sha256 `c76726d9d088…`）
