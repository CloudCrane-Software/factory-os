# swev 项目制规格书 · astropy/astropy 六实例族（v1.0 · 2026-11-08）

> **冻结声明**：本件 = astropy/astropy 六实例族（14365/14539/14508/14598/14369/14309）四波次
> 项目（P→A→B→C）的唯一行为契约，随本目录落成冻结（v1.0 · 2026-11-08）。冻结后禁改：任何
> 条款修改须经运营者裁决并升版号（v1.1），旧版留档不改写；角色派发件与本规格冲突时，以本
> 规格为准并停手报告，禁自行改规格迁卡面。
> **判官件纪律**：`tools/swev-judge-v2.py` 零改动零触碰（只读消费）；判据面只许变严（加门
> 可以，放宽官方谓词不可以）。对齐范式：D-117 bench 卡判分形制（`30-工件/夜轨A2-20261107/
> 判分读数.md` §一–§十）、D-106 warm-relay 五步形制、bench 多角色单体卡形制
> （`30-工件/bench多角色-20261108/SPEC.md`）。
> **实例族口径**：卡 = 实例；施工波按扇出产卷（≥2 卡 fanout=3），测试判分波逐卡官方判分并
> 在扇出多卷间择优；不过卡进打回重生成 ≤2 轮；终局如实的 not_resolved 也是合法闭环。

## 〇、任务与已核事实（本节每条 2026-11-08 设计会话实跑核得，核法随条注）

- **任务**：SWE-bench 实例族，repo=`astropy/astropy`，六实例 =
  `astropy__astropy-{14365,14539,14508,14598,14369,14309}`。题面 =
  `anolis:/data/bench/swev-s1-r0/astropy__astropy-{n}.json`（六件 ls 实测在盘：
  14365=7,169B ｜ 14539=14,617B ｜ 14508=23,196B ｜ 14598=23,314B ｜ 14369=68,396B ｜
  14309=20,651B）。六件 11 键同构实测一致：`base_commit / eval_script / fail_to_pass /
  hints_text / image / instance_id / pass_to_pass / problem_statement / repo / test_patch /
  version`；repo 字段逐字 = `astropy/astropy`，instance_id 逐字与文件名一致（python3 -I 实读）。
  注记：六件 `fail_to_pass/pass_to_pass` 为 **list 形态**（str 形态读取 TypeError 实证）；
  判分链读入兼容性由 B1 首判实证，若既有判分管线拒收 ⇒ 判分链红 = 环接不住，如实停判报告，
  禁改判官件。
- **六实例计数面**（题面逐字核得，公开面只给计数——D-117 §八口径；逐字 ID 清单 harness 侧
  持有，不入本规格）：

  | 实例 | version | base_commit | F2P | P2P | ps/hints/tp/eval(B) | eval sha256[:12] |
  |---|---|---|---|---|---|---|
  | astropy-14365 | 5.1 | `7269fa3e33e8…` | **1** | **8** | 1339/1550/1194/1884 | `bd7699563c7f` |
  | astropy-14539 | 5.1 | `c0a24c1dc957…` | **2** | **46** | 1463/676/3599/4289 | `87ce8af2c955` |
  | astropy-14508 | 5.1 | `a3f4ae6cd24d…` | **1** | **174** | 2629/675/1236/1932 | `08fbf0eba6c0` |
  | astropy-14598 | 5.2 | `80c3854a5f4f…` | **1** | **175** | 2651/925/1044/1740 | `caabde10cc32` |
  | astropy-14369 | 5.1 | `fa4e8d1cd279…` | **3** | **732** | 2597/2160/1102/1792 | `6c430653fb83` |
  | astropy-14309 | 5.1 | `cdb66059a2fe…` | **1** | **141** | 4910/24/895/1594 | `77ab0977f649` |

  （base_commit 全串与全串 sha 由 B 卡执行腿收件时逐字对账；本表给前 12 位锚。ps=problem_statement
  字节数、hints=hints_text、tp=test_patch、eval=eval_script。）
- **难度序（易→难，DAG 依据，按上表实测计数）**：14365（F2P1/P2P8，回归面最小，题面最短）→
  14539（F2P2/P2P46）→ 14508（1/174）≈ 14598（1/175，族内唯一 v5.2 基线）→ 14309（ps 4910B
  全族最大 + hints 24B 全族最薄，推理线索最少）→ 14369（F2P3 全族唯一多修复面 + P2P732 =
  次名 4.2 倍回归面，最难）。
- **判分镜像**：题面 image 字段六件逐字 =
  `swebench/sweb.eval.x86_64.astropy_1776_astropy-{14365,14539,14508,14598,14369,14309}:latest`
  （python3 -I 实读）。**六镜像 anolis 均不在盘**（`docker images | grep astropy` 实测仅
  7166/7606/7671/8872 四件，无一本题实例）⇒ **B 波镜像预热腿（B0）必行**，拉取路 =
  anolis `/etc/docker/daemon.json` `registry-mirrors`（实测在档：`docker.m.daocloud.io`、
  `docker.1ms.run`；data-root=/data/docker/docker）。拉取动作属写面，由 B0 执行腿做；设计
  会话不拉（not_run，见 §八 T6 预算注）。
- **判分缓存面**：`anolis:/data/bench/swev-judge-cache/tasks/` 既有条目实测 =
  7606/7671/8872/django-11133/11141/11149 六件（含各自 .verify.json），**与本题六实例零
  重叠 ⇒ 每实例判分前 warm-relay 预热必行**（未命中 fail-closed，禁裸判）。
- **判官件活跃面**：本侧两部署路径 sha256 均 =
  `4a7156dd5e45197f7d8ab39be236eb9bb7a0ce7af220bca2395f863d71133389`
  （`repos/factory-os/tools/swev-judge-v2.py` 与 `tools/swev-judge-v2.py`，sha256sum 实测
  同值；即任务给定活跃面 `4a7156dd5e45197f…[:16]`）。判分谓词 = swebench
  `get_resolution_status(...) == ResolvedStatus.FULL.value`
  （`tools/swev-judge-v2.py:486-489`，含 P2P 归一化重算路径 §459-490；判据零改动）。
- **pre-judge 对账门**：本设计会话实跑**绿（rc=0）**：`python3 -I
  tools/judge-deploy-recon-gate.py --pre-judge --fos-root repos/factory-os` → J1/J5 活跃面
  对账 PASS、H4 历史冻结对账 PASS、结论「绿（pre-judge 放行）」。拒判语义 =
  `tools/cb-run.py:85-96`（门红/不可证/缺席一律 fail-closed 拒判，翻 judge_blocked，不落
  结果行不计判，禁假阴污染成绩单）。
- **取码路（施工腿）**：codeload 白名单路已证（bench多角色 SPEC §〇 实测 HTTP 200、
  ~100KB/s 慢管道、≤6min 预算）：`https://codeload.github.com/astropy/astropy/tar.gz/<base_commit>`。
  各卡施工员自取自核 tarball sha256 并留痕；镜像内 `/testbed` 位于合成提交（与上游 blob
  不同），patch 施加以官方 `git apply` 首档、GNU `patch -p1 --fuzz=3` 兜底（cb-judge.sh
  头注两次实证），兜底启用须在 A3 记「首档拒收原因」。
- **参照读数（预算锚出处）**：D-117 全环 43m25s、施工 10m11s、收件核后判分腿 2m33s、
  warm-relay 五步 9.5s、基线容器 11s、判分容器 13s、judge.stderr 0B 健康态
  （`30-工件/夜轨A2-20261107/判分读数.md` §四–§九）；D-106 五步全绿 9.5s 量级
  （`30-工件/D-106-判分自足-20261106/warm-relay-readings.json`）；单卡损耗对拍 schema 与
  门槛先例（`30-工件/bench多角色-20261108/SPEC.md` §六）。
- **预算先例**：判分腿 mem 8G/实例（D-117 卡面）、活跃容器 ≤3 / 活跃角色会话 ≤4
  （bench多角色 SPEC §一.5）；Σmem≤45G、并发≤4 硬顶（anolis 纪律）。
- **未跑/未验证（如实登记，禁引本规格读数代替执行腿实跑）**：① 六镜像拉取未跑（写面，
  B0 事）；② 六实例 warm-relay/判分链未跑（B 卡事）；③ codeload 六 base_commit tarball
  未取（施工腿事，路已证）；④ B1 首判对 list 形态 F2P/P2P 的判分链兼容性未证（〇·注记）。

## 一、总则与纪律（全角色全卡约束，违一条即该工件不收卷）

1. **冷交接原则（本规格第一原则）**：角色间互不见会话历史；**交接工件（§四布局所列）是
   唯一信息通道**。每卡每角色只收：本规格对应节 + 卡面 + 该卡输入工件。不得反问上游、
   不得读上游工作目录；输入缺失/矛盾 ⇒ 停手报告（诚实纪律），禁猜补。
2. **两级信息面（泄题防线）**：**内档面**（test_patch 内容、F2P/P2P 逐字清单、判分日志
   全文）仅测试判分员在履职中可触；逐字 ID 禁出内档（公开面只给计数 + 结构级归因——D-117
   §七口径）。**交接面**（题面卡面、patch+报告、结构级读数、择优记录、裁决）跨角色流动。
   施工员与评审员永不在内档面：禁查上游 astropy 官方修复提交/PR；禁搜 `astropy-<n> patch`
   类关键词；禁翻 SWE-bench 数据集/答案件；禁访问除题面给定下载域（codeload.github.com、
   pypi）外的外部网络。
3. **禁改测试件**：任何交付物不得触碰 `*/tests/**`、`test_*.py`、`tests.py`（判分测试由
   判分链统一施加；改测试件 = 作弊形态）。
4. **禁改判分链**：`tools/swev-judge-v2.py`（活跃面 `4a7156dd5e45…`）、判分镜像、判据面、
   pre-judge 门、warm-relay 链零改动零触碰（只读消费）；判据只许变严；判分链自身红 =
   环接不住，如实判不通，禁人工抢救。
5. **anolis 纪律**：Σmem≤45G、并发≤4（硬顶）；判分腿 mem 8G/实例容器；**任一时刻活跃
   anolis 容器 ≤3、活跃角色会话 ≤4**（A 波扇出卷各占一个会话名额；B 波容器对 ≤3）；
   测试类进程环境**剥离代理/凭据类 env**（HTTP(S)_PROXY、*_TOKEN、*_KEY 等）。
6. **ssh 只读 + 工作目录内写**：对 anolis 的 ssh/docker 默认只读；写只许落
   `/data/bench/swev项目制-20261108/**`（本卡施工判分目录）与 warm-relay 的
   `/data/bench/swev-judge-cache/**`（既有判分缓存面形制内）与 B0 镜像拉取（daemon 正常
   写 data-root）；系统面、他卡条目、他债号目录零触碰。
7. **凭据零打印**：token/密钥经 openBao 程序化现取（0600、不打印、不落日志、不进 argv
   ——D-117 §九既证纪律）；一切工件/评论/日志正文零凭据形态（只允许 sha256[:12] 指纹与
   掩码）。
8. **预热 fail-closed（双面）**：缓存面未命中 ⇒ warm-relay 五步先预热再判；镜像面不在盘
   ⇒ B0 先拉，拉不到 ⇒ 该实例拒判翻 judge_blocked 如实登记（禁裸判）。
9. **诚实纪律高于完成度**：没跑的写成没跑（not_run + 理由），红的写红的；自报读数只作
   参考，判分以 anolis 判分腿重跑为准；交部分结果 + 写明缺口 > 假完整交卷。resolved=false
   也闭环（跑得通 ≠ 做对题，D-86/D-107/D-117 同口径）。
10. **git 不可逆动作全禁**：禁 `--force`、禁 `reset --hard`、禁改写已推历史；各角色只写
    §四布局内自己的落档位。
11. **多卷交卷纪律**：以静默窗（≥5 分钟无新卷）后末卷为该卷位正本，交卷后禁追加第二卷
    （D-117 晚到卷教训，cnb真沙箱读数 §一.4）。

## 二、波次定义（冻结）

```
P 核面波（已毕）→ A 施工波 → B 测试判分波 → C 集成评审波
                    ↑←── 回环 ≤2 轮（resolved=false 触发，A 卡重生成，B 卡重判）──←↓
```

- **P 核面波（已毕，1 卡）**：规格冻结 + 全族核面（题面/镜像/缓存/判官件/门五面），
  本设计会话完成，产出 = 本 SPEC §〇。P 不再发车；执行腿发现的核面漂移（如判官件指纹
  不符）⇒ 停手报告，禁在执行腿内改规格。
- **A 施工波（6 卡，卡 = 实例，易卡先行 DAG）**：每卡按 fanout 产 patch 卷；fanout=3 的
  卡产三卷（三个互不见会话的施工员独立施工同题），fanout=1 产一卷。产出 A2-patch.diff +
  A2-report.md（每卷）。**A 波零 anolis 容器**（施工在本地 codeload 基线树），只占会话
  名额。
- **B 测试判分波（7 卡 = B0 预热 + B1–B6 判分，卡 = 实例或全族）**：B0 = 判分镜像预热腿
  （六镜像拉取 + 在盘核，全族一张卡）；B1–B6 逐卡 = 收件核（apply-check）→ warm-relay
  五步 → pre-judge 门 → 基线容器（无补丁，验基线红）→ 判分容器（施 patch）→
  swev-judge-v2 官方判分 → judge.json；fanout 卡先按 §六择优规则判卷定正本。resolved=false
  ⇒ 触发回环（§七）。
- **C 集成评审波（2 卡，项目级）**：C1 = 跨卡一致性冷评审（六卡全工件冷读对拍）；C2 =
  项目总评 + 损耗账归并（loss-metrics-project.json + timing-ledger 收口）。
- **回环**：不独立成波，附属于 A/B（§七）；两轮后仍 resolved=false ⇒ 终局 not_resolved
  如实闭环。

## 三、卡表（冻结；id / instance / fanout / depends）

| id | instance | fanout | depends | 卡义 |
|---|---|---|---|---|
| P1 | 全族（规格+核面） | 1 | [] | 已毕：SPEC v1.0 冻结 + §〇 五面核得 |
| A1 | astropy__astropy-14365 | 1 | [] | 最易卡兼**全链先导卡**（首个走完施工→收件核，为后卡验形制） |
| A2 | astropy__astropy-14539 | 1 | [A1] | 次易 |
| A3 | astropy__astropy-14508 | 1 | [A1] | 中档 |
| A4 | astropy__astropy-14598 | 1 | [A2] | 中档（v5.2 基线） |
| A5 | astropy__astropy-14309 | **3** | [A3] | 难卡（hints 最薄 + ps 最大）→ 三卷择优 |
| A6 | astropy__astropy-14369 | **3** | [A4, A5] | 最难卡（F2P3 + P2P732）→ 三卷择优，A 波收官 |
| B0 | 全族（六判分镜像） | 1 | [] | 镜像预热腿：六镜像拉取 + 在盘核 + 读数落档 |
| B1 | astropy__astropy-14365 | 1 | [B0, A1] | 逐卡应用+跑测+官方判分（首判卡，兼证 list 形态兼容性） |
| B2 | astropy__astropy-14539 | 1 | [B0, A2] | 同上 |
| B3 | astropy__astropy-14508 | 1 | [B0, A3] | 同上 |
| B4 | astropy__astropy-14598 | 1 | [B0, A4] | 同上 |
| B5 | astropy__astropy-14309 | 1 | [B0, A5] | 判三卷 → §六择优定正本 |
| B6 | astropy__astropy-14369 | 1 | [B0, A6] | 判三卷 → §六择优定正本 |
| C1 | 项目级（跨卡冷评审） | 1 | [B1,B2,B3,B4,B5,B6] | 六卡全工件一致性冷评审 + 逐 junction 对拍 |
| C2 | 项目级（总评+损耗账） | 1 | [C1] | loss-metrics-project.json 归并 + 项目总评 + 计时收口 |

- **DAG 易卡先行依据** = §〇 难度序（实测计数），非主观分档。
- **并发核算（≤4 会话顶）**：A 波层 L1=A1（1 会话）→ L2=A2+A3（2）→ L3=A4+A5×3（**4，
  顶格**）→ L4=A6×3（3）；B 波判分腿受容器 ≤3 限制（8G×3=24G ≤45G ✓）；全周期任一时刻
  活跃会话 ≤4、活跃容器 ≤3。
- **卷数核算**：A 波 1+1+1+1+3+3 = **10 卷**；回环每轮按原 fanout 数重生成（+≤20 卷/全项目
  两轮满额，预算 §八按轮给顶）。B 波判分跑次 ≤10/轮（fanout 卡按 §六预排序逐卷判，首个
  resolved=true 即停）。

## 四、目录布局与角色交接工件（冻结）

```
30-工件/swev项目制-20261108/
├── SPEC.md                          # 本规格（冻结件）
├── timing-ledger.md                 # 全项目计时表（§八事件逐行 + 证据坐标）
├── loss-metrics-project.json        # 项目损耗账（C2 归并，§九 schema）
├── project-review.md                # C2 项目总评
├── cross-card-review.md             # C1 跨卡一致性冷评审（findings + 对拍）
├── mirrors-pull-readings.json       # B0 读数（六镜像：拉取态/ID/尺寸/失败如实）
└── cards/<实例简称>/                 # 实例简称 = astropy-14365 等，六目录同构
    ├── card-builder.md              # 施工员派发件（§五.1 形制；扇出卷卡面同文，卷号唯一）
    ├── card-tester.md               # 测试判分员派发件（§五.2 + §五.3 判分链操作权）
    ├── A2-patch.v{1,2,3}.diff       # 施工卷（fanout=1 卡只落 v1）
    ├── A2-report.v{1,2,3}.md        # 修复说明五节（与对应卷同交）
    ├── A2-selection.json            # 择优记录（仅 fanout=3 卡；§六 schema）
    ├── Fb-r{n}.json                 # 回环反馈件（n=1,2；测试判分员 → 施工员，结构级）
    ├── A2-patch.final.diff          # 正本卷（择优胜者或回环后末轮正本；fanout=1 卡即 v1）
    ├── A3-test-readings.md/.json    # 测试读数（正本卷判分跑次的结构级读数）
    └── judge/                       # 判分腿留档（harness 侧；anolis 侧镜像落
        │                            #   /data/bench/swev项目制-20261108/<卡>/）
        ├── warm-relay-r{n}.json     # D-106 五步读数（all_ok 必须 true）
        ├── prejudge-gate-r{n}.log   # pre-judge 门输出（结论绿）
        ├── eval.sh                  # 官方 eval_script 出土件（sha256[:12] 对账 §〇 表）
        ├── baseline_log.txt         # 基线容器日志（无补丁；每轮复跑防镜像漂移假阴）
        ├── judged_log.txt           # 判分容器日志（施加正本 patch）
        └── judge.json / judge.stderr # 官方判分 verdict（swev-judge-v2.py 产出；按轮留档）
```

- 角色集（四类）：**编排面**（派发/收卷/计时账/预算闸/回环裁量）、**施工员**（A 波，每卷
  一会话，互不见）、**测试判分员**（B 波，唯一内档面履职角色）、**评审员**（C 波，跨卡冷）。
- 每个施工员输入 = card-builder.md（题面逐字 + §〇 该卡已核前提）+ 本规格 §一/§五.1；仅
  回环轮追加 Fb-r{n}.json + 自己上一轮卷。测试判分员输入 = card-tester.md + 该卡全部卷
  （A2-patch.v*.diff + A2-report.v*.md）+ 判分链操作权。评审员输入 = 六卡全部交接面工件
  （禁 judge.json 逐字日志全文，结构级 verdict 读数可读；禁内档面）。
- 题面入卡面前人工复核一次（字节数对上才发车——禁夹带 test_patch/清单字段；发车前机检：
  卡面 grep `test_patch\|FAIL_TO_PASS\|PASS_TO_PASS` 仅允许出现在「计数声明」行）。

## 五、逐角色规格（输入 / 输出 / 验收命令）

### 5.1 施工员（A 波，每卷一会话，只拿题面卡面 + 本规格对应节 [+ 回环 Fb]）

- **任务**：按题面卡面施工，产出 A2-patch.v{n}.diff + A2-report.v{n}.md（同卷交付）：
  patch = SWE-bench 格式 unified diff（`git apply` 可干净施加到 pristine 基线 =
  codeload tarball at base_commit，自取自核 sha 留痕）；A2-report 五节 = ① 复现步骤与
  读数（前红后绿或 not_run + 理由）② 根因分析 ③ 修复说明（逐文件一行，与 patch 触面
  集合一致）④ 自验命令 + 退出码 + 输出头部 ⑤ 诚实注记。
- **允许**：改基线树非测试文件；基线树内最小复现自验（前红后绿）；跑基线树既有测试面查
  回归（基线树内既有面、非判分件）。
- **禁止**：碰任何测试文件；为跑通放宽断言/改测试；顺手修别的；接触判分链与内档面；查
  上游官方修复（§一.2）。
- **验收命令**（编排面收卷时跑，逐卷）：
  1. `git -C <基线树> apply --check cards/<卡>/A2-patch.v{n}.diff` → rc=0
  2. `grep '^diff --git' cards/<卡>/A2-patch.v{n}.diff | grep -E 'tests?/|test_'` → 空、rc=1
  3. `test -s A2-patch.v{n}.diff && grep -q '^## 修复说明' A2-report.v{n}.md` → rc=0
  4. `grep '^diff --git' A2-patch.v{n}.diff` 文件集合 = A2-report ③ 节文件集合（编排面
     diff 判等，不等 ⇒ 不收卷）
  5. `sha256sum A2-patch.v{n}.diff` [:12] 留痕入计时表（卷指纹）

### 5.2 测试判分员（B 波，唯一内档面角色；命令书 = 判分读数.md §一–§六形制）

- **收件核**：正本（或按 §六预排序的各卷）对 pristine 基线 `git apply --check` rc=0 才
  判；首档拒收时 GNU `patch -p1 --fuzz=3` 兜底并记「拒收原因」。
- **eval.sh 出土**：从 anolis 题面 JSON 提取 eval_script 落 judge/eval.sh，sha256[:12]
  必须 = §〇 表该实例值（不符 = 题面被动过，停手报告）。禁读/留存 test_patch 与清单
  内容（eval.sh 内含施加动作，允许；hunks 不摘抄）。
- **基线容器**（无补丁，每轮复跑）：起镜像容器 → bash eval.sh → baseline_log.txt；读数 =
  既有面汇总行 + F2P 基线红计数（基线红 = 题目本体）；逐字失败 ID 只入 judge/。
- **判分容器**（施 patch）：起同镜像新容器 → 官方首档 git apply → bash eval.sh →
  judged_log.txt；读数 = 汇总行计数。
- **判分腿**（测完即判）：warm-relay 五步（`bash repos/factory-os/tools/swev-warm-relay.sh
  --task <题面 JSON 本侧副本> --out judge/warm-relay-r{n}.json --remote anolis
  --remote-dir /data/bench/swev-judge-cache`，任一步败 fail-closed 停判）→ pre-judge 门
  （`python3 -I tools/judge-deploy-recon-gate.py --pre-judge --fos-root repos/factory-os
  --cache-dir <本侧缓存视图>`，结论绿才判；红/不可证 ⇒ 拒判翻 judge_blocked，cb-run.py:85-96
  语义）→ 官方判分（`SWEV_JUDGE_V2_CACHE=/data/bench/swev-judge-cache <venv-python>
  swev-judge-v2.py <题面 JSON> judge/judged_log.txt <正本 patch> > judge/judge.json
  2> judge/judge.stderr`；judge_rc=0 且 stderr 0 字节为链健康态）。
- **verdict 口径（冻结）**：`resolved=true ⇔ diff_valid=true ∧ F2P 全中 ∧ P2P 全中`
  （get_resolution_status FULL，tools/swev-judge-v2.py:486-489）；任一不满足 ⇒
  resolved=false 如实判，禁人工抢救、禁为过判改判据/判官件。
- **输出**：A3-test-readings.md/.json（每步命令、退出码、计数、产物 sha256[:12]；逐字
  测试 ID 不入交接面）+ judge/ 按轮留档 + 回环时 Fb-r{n}.json。
- **验收命令**（编排面收卷时跑，逐卡逐轮）：
  1. `test -s judge/{eval.sh,baseline_log.txt,judged_log.txt,judge.json}` → rc=0（四产物在盘）
  2. `test "$(sha256sum judge/eval.sh | cut -c1-12)" = "<§〇表该卡 eval[:12]>"` → rc=0
  3. `python3 -I -c` 校 judge.json：`diff_valid is True and log_state=='parsed' and hermetic
     is True and live_http==[] and blocked_urls==[] and f2p_success+f2p_failure==<§〇表 F2P>
     and p2p_success+p2p_failure==<§〇表 P2P>` → verdict-shape-ok
  4. `python3 -I -c` 校 warm-relay：`all_ok is True and fail_step is None` → warm-ok
  5. `grep -q '结论：绿' judge/prejudge-gate-r{n}.log` → rc=0
  6. `test ! -s judge/judge.stderr` → rc=0
  7. 判官件前后 `sha256sum` 活跃部署面均 = `4a7156dd5e45197f7d8a…`（计时表留痕）
  8. A3 正文 `grep -cE '<测试文件路径>::test_[^ ]+ (FAIL|PASS)ED'` → 0（逐字 ID 不出内档）

### 5.3 B0 镜像预热腿（全族一张卡，编排面或测试判分员执行）

- **任务**：对六实例逐一 `docker pull swebench/sweb.eval.x86_64.astropy_1776_astropy-{n}:latest`
  （并发 ≤3 路拉取；走 daemon.json registry-mirrors 两路，不另配源）；逐镜像落
  `docker images` ID + 尺寸读数；任一镜像拉取失败 ⇒ 重试一次（换镜像顺序），仍败 ⇒ 该
  实例如实登记 pull_failed + 对应 B 卡拒判 judge_blocked（fail-closed，不落判分结果行）。
- **输出**：mirrors-pull-readings.json（六条目：instance/image/pulled/image_id/size_bytes/
  error）。
- **验收命令**：`python3 -I -c` 读 mirrors-pull-readings.json：六条目齐、每条 pulled 布尔
  如实（true 则 image_id 非空）；编排面对「pulled=false 的实例，其 B 卡不得发判」做闸。

### 5.4 评审员（C 波，跨卡冷；C1+C2 两卡）

- **输入（仅交接面）**：六卡 A2-patch.final.diff + A2-report + A3-test-readings.md/.json +
  A2-selection.json（fanout 卡）+ 结构级 verdict 读数 + 本规格。禁判分日志全文、禁内档面、
  禁会话历史。
- **C1 任务（cross-card-review.md）**：① 六卡工件指纹行（key_for，sha256[:12]）② 跨卡
  一致性 findings（逐条 F#、严重度、证据坐标）：纪律面一致性（零测试触面/零判分链触碰/
  零凭据形态/命名与留痕形制）、同族修复互不矛盾（不同实例同模块修复是否冲突或重复）、
  择优链执行正确性（A2-selection.json vs 判分面事实）③ 逐 junction 对拍（§九）④ 裁决
  （逐卡 采纳|打回 + 项目级结论）⑤ 诚实注记。引文必须真实存在（抽查 grep 可复算）。
- **C2 任务（project-review.md + loss-metrics-project.json）**：归并六卡损耗账 → 项目级
  gate 判定；项目总评（resolved 计数、回环轮次实耗、预算实耗 vs §八、缺口清单如实）；
  timing-ledger 收口。
- **验收命令**：
  1. `grep -c '^key_for:' cross-card-review.md` → ≥6（六卡指纹齐）
  2. key_for 值逐一 = 对应 A2-patch.final.diff sha256[:12]（编排面 diff 判等）
  3. `python3 -I -c` 校 loss-metrics-project.json：`gate.pass` 布尔如实 + 六卡 junctions
     齐 + 每个 junction 有 loss_rate → loss-schema-ok
  4. 引文真实性抽核（编排面抽 2 条 grep 复算）

## 六、扇出择优规则（冻结；B5/B6 两卡适用；A2-selection.json 留链）

- **判分顺序（预算优化，不许跳判）**：三卷先按卷面质量预排序（apply-check 首档过 > 触面
  hunk 数少 > report 五节完备 > 诚实注记质量），**逐卷官方判分，首个 resolved=true 即停**，
  该卷定为正本；后续卷留档不销、不判（判分面省跑次）。
- **择优序（冻结；全卷判毕时用）**：
  1. **判官 resolved 优先**：resolved=true 卷 > false 卷（判分面为最高判据，质量面不得
     代判分面）；
  2. resolved 并列 ⇒ **f2p/p2p 计数**：f2p_success/f2p_total 高者优 → p2p_success/p2p_total
     高者优；
  3. 仍并列 ⇒ **卷面质量**：触面 hunk 数少者优（最小修复原则）→ 静默窗末卷优先（D-117
     晚到卷教训：晚到更完整卷取末）。
- **全 false**：同序取最优卷为正本 + 三卷失配归因（结构级）并入 Fb-r1.json 触发回环
  （§七）。
- **A2-selection.json schema（冻结）**：`{instance, volumes:[{id, patch_sha12, apply_ok,
  hunks, judged, resolved, f2p_s, f2p_f, p2p_s, p2p_f}], order_rule:"§六", winner,
  winner_reason, honest_notes}`。每轮回环后追加 `round` 行。

## 七、回环（打回重生成 ≤2 轮，冻结）

- **唯一权威触发 = 判分 resolved=false**；评审打回（矛盾项）为辅信号并入同一轮预算，编排面
  裁量当轮是否触发。轮次 r = 1,2；**两轮后仍 false ⇒ 终局 not_resolved 如实闭环**（环走完
  + 归因清晰 = 项目合法终点，禁人工抢救判分）。
- **Fb-r{n}.json（结构级，测试判分员产出）**：`{round, resolved, diff_valid, f2p:{s,f},
  p2p:{s,f}, failed_leg("F2P"|"P2P"|"diff"|null), 失配归因(结构级), 诚实注记}`——禁逐字
  测试 ID、禁 test_patch 内容、禁判分日志原文。
- **施工员重生成**：输入 = 原卡面 + Fb-r{n}.json + 自己上一轮卷（可自读复盘）；fanout=3
  卡重生成仍产三卷（同扇出）；产出 v(n+1) 卷，重跑 §5.1 验收。
- **判分腿每轮全量重跑**：warm-relay（幂等）→ 门 → 基线容器（复跑防镜像漂移假阴）→ 判分
  容器 → judge.json r{n}（judge/ 按轮留档）。fanout 卡每轮重新 §六择优。
- **回环不跨卡**：每卡独立回环预算（各 ≤2 轮）；回环中该卡会话名额计入 ≤4 顶。

## 八、计时点（冻结表；证据坐标 = mtime / JSON 字段，落 timing-ledger.md）

| # | 计时点 | 证据坐标 | 预算锚（在案实测/给顶） |
|---|---|---|---|
| T0 | SPEC 冻结（v1.0 落档） | SPEC.md mtime | — |
| T1 | A1 发车（先导卡） | card-builder mtime | 施工腿 ≤60min/卷（D-117 实测 10m11s 量级 + 本地取码 ≤6min） |
| T2 | A1 正本收卷（先导核过） | A2-patch.v1 mtime + 验收读数 | — |
| T3 | L2 收卷（A2+A3） | 对应 mtime | — |
| T4 | L3 收卷（A4+A5×3，顶格 4 会话） | 对应 mtime | — |
| T5 | L4 收卷（A6×3）＝A 波闭 | 对应 mtime | A 波全段 ≤8h |
| T6 | B0 六镜像预热读数落档 | mirrors-pull-readings.json mtime | **未实测给顶 ≤40min/镜像**（约 4.1–4.4GB/个，registry-mirrors 两路；超时/失败如实登记 fail-closed，禁假在盘） |
| T7 | B1 首判卡 verdict 落盘 | cards/astropy-14365/judge/judge.json mtime | 判分腿全段 ≤3min（D-117 实测 2m33s；warm-relay ~10s + 门 <5s + 基线 ≤2min + 判分容器 ≤5min 内含） |
| T8 | B2–B4 verdict 逐卡落盘 | 对应 judge.json mtime | 每卡 ≤3min + 排队 |
| T9 | B5/B6 三卷判分+择优落档 | A2-selection.json mtime | 每卡 ≤6 卷判次顶（§六首绿即停可省） |
| T10 | 回环轮 r{n}（触发→重生成→重判） | Fb-r{n}.json mtime | 每轮 ≤4h/卡；全项目回环合计 ≤12h |
| T11 | C1 跨卡冷评审落档 | cross-card-review.md mtime | 评审腿 ≤2h |
| T12 | C2 总评+损耗账+计时收口 | project-review.md / loss-metrics-project.json mtime | ≤1h |
| T13 | 全项目收口 | timing-ledger.md mtime | **项目总顶 ≤24h**（不含 B0 拉取失败重试的如实超顶） |

（计时刻度只对本链事件；角色内部自由用时不设限，只卡各段预算锚与总顶。人工现身目标 0 次。
B0 拉取预算为设计给顶非实测——执行腿以实读为准，超顶如实登记，禁填数。）

## 九、损耗度量（交接处信息丢失 = 评审员事后对拍；落 loss-metrics-project.json）

**定义**：损耗 = 上游工件携带的信息在交接后未在下游落地的部分。度量法 = 评审员事后对拍
（范式 = bench多角色 SPEC §六 + D-118 信息损耗审计：冷读对拍、逐项判级）。**主度量 =
H1（题面 → patch）**。

- **对拍项集（每卡各 junction，C1 逐卡执行、C2 归并）**：
  - **H1 题面 → patch（主度量）**：题面明示事实（报错形态/期望行为/涉及文件定位/复现
    步骤）逐条 vs A2-patch 实际触面 + A2-report ②③。
  - **H2 patch → 测试读数**：A2-report ④自验主张 vs A3 读数能否证实（自验 not_run 时 A3
    是否如实记录而非脑补绿）。
  - **H3 测试读数 → verdict**：A3 结构级读数 vs judge.json 字段两面合流不自相矛盾。
  - **H4 verdict → 择优链（仅 A5/B5、A6/B6）**：A2-selection.json 择优序执行 vs 判分面
    事实（§六序是否如实执行，winner_reason 可复算）。
  - **H5 跨卡一致性（项目级，仅一次）**：六卡间纪律面一致 + 同族修复互不矛盾（C1 ③）。
- **判级**：**一致**（落地且同向）/ **偏移**（落地但偏离，未违排除项）/ **丢失**（上游
  提出、下游未落地且无理由）/ **矛盾**（下游做了上游明确排除的，或另起炉灶）。
- **公式**：`保真率 = (一致 + 0.5×偏移) / 对拍项总数`；`loss_rate = 1 − 保真率`。
- **门槛（放行判据，冻结）**：`H1.loss_rate ≤ 0.20`（保真率 ≥80%，bench多角色/D-118 实测
  口径）**且全表矛盾项 = 0**，否则该卡 C1 裁决 = 打回（矛盾项必打回，偏移项评审裁量）；
  打回信号按 §七预算池由编排面裁量。
- **loss-metrics-project.json schema（冻结）**：

```json
{
  "spec": "30-工件/swev项目制-20261108/SPEC.md",
  "spec_sha256_12": "<SPEC.md sha256[:12]>",
  "project": "astropy/astropy 六实例族",
  "cards": {
    "<卡id>": {
      "junctions": {
        "H1": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0,
               "items": [{"claim": "<上游断言>", "downstream": "<下游坐标>", "grade": "consistent|offset|lost|contradiction", "note": "<一行为什么>"}]},
        "H2": {"…同构…": null},
        "H3": {"…同构…": null},
        "H4": {"…同构…或 absent(非fanout卡)": null}
      },
      "gate": {"h1_max_loss_rate": 0.20, "contradiction_required": 0, "pass": true}
    }
  },
  "cross_card": {"H5": {"checked": 0, "consistent": 0, "offset": 0, "lost": 0, "contradiction": 0, "loss_rate": 0.0, "items": []}},
  "gate": {"h1_max_loss_rate": 0.20, "contradiction_required": 0, "pass": true}
}
```

（落档时必须合法 JSON：H2/H3 与 H1 同构；非 fanout 卡 H4 置 null。验收只查六卡 junctions
集合与 loss_rate 在场、gate.pass 如实。）
- **回环减损证据**：每轮回环后按卡追加 review_round 行；第 r 轮丢失项在 r+1 轮转一致 =
  损耗可测可修可复验的实证。

## 十、集成验收（全项目收口，编排面跑）

1. §5.1–§5.4 各验收命令全过（逐条 rc 读数入 timing-ledger.md）。
2. 六卡 judge.json 在盘（resolved true/false 如实）+ B 卡判分腿健康三件（warm-relay
   all_ok=true、pre-judge 门绿、judge.stderr 0 字节）逐卡核。
3. `python3 -I -c` 校 loss-metrics-project.json：项目 gate.pass 如实（true 时六卡 H1 均
   ≤0.20 且矛盾=0）→ loss-gate-pass。
4. 纪律终检：全部交接面工件 `grep -rE '(BEGIN (RSA|OPENSSH) PRIVATE KEY|ghp_[A-Za-z0-9]|
   sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})'` → 全 0 命中；六卡正本 patch 零测试触面（§5.1-2
   重跑）；判官件前后指纹一致（§5.2-7）。
5. 计时表齐：T0–T13 每行有证据坐标；人工现身计数 = 0。
6. 台账/回卡：每卡 verdict（resolved + F2P/P2P **计数** + 正本 patch sha256[:12] + 失配
   归因结构级 + C1 裁决摘要）回填；测试清单只给计数、零凭据形态（D-117 §八口径）。
7. **终局口径**：6/6 resolved=true = 全绿；部分 resolved = 如实计数（x/6）+ 未过卡回环
   轮次与归因；not_resolved 卡也闭环（跑得通 ≠ 做对题，三卡同口径）。项目成功判据 =
   **链路完整性 + 如实性**，非 resolved 计数本身。

## 十一、冻结纪律与诚实性条款

- 本规格冻结于落档时刻（v1.0 · 2026-11-08）；改 = 运营者裁决 + 升版 + 旧版留档。
- 各角色派发件逐字嵌本规格对应节；冲突 ⇒ 停手报告，禁自行改规格。
- 诚实性高于完成度：任一腿做不完交部分结果并写明缺什么；verdict 如实判；B0 拉取失败、
  判分链拒收 list 形态、镜像漂移等一切意外 = 如实登记 + fail-closed，禁抢救禁填数。
- 本规格为设计件：§〇 所列事实为设计会话实跑核得；执行腿各命令须全量重跑留读数，禁引用
  本规格读数代替执行腿实跑（自报读数不作证据）。

（落定：2026-11-08 · 架构组·规格师 · swev项目制-20261108）
