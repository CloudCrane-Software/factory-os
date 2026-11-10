# 测试读数（A3 / test-report）· bench多角色-20261108 · astropy__astropy-8872

> 角色：测试员（SPEC v1.0 §4.3＋判分链操作权 §4.4）｜ 日期：2026-11-08
> 输入：card-tester（任务材料）＋ fix.patch（sha256[:12]=`cad7015c642c`，1,023B）＋判分链既有 harness。
> 本件每条读数均为本会话实跑（命令＋输出随条留痕）；逐字测试 ID 只入 `judge/` 内档，本正文零逐字 ID
> （结构级计数＋形态归因，D-117 §七/§八口径）。判官件 `tools/swev-judge-v2.py` 零改动零触碰（判分前后
> 指纹各核一次，均 `4a7156dd5e45…`）；凭据零打印；anolis 侧只读＋仅写
> `/data/bench/bench多角色-8872/**` 与 warm-relay step4 的 `/data/bench/swev-judge-cache/tasks/astropy__astropy-8872.json`。
> 机读面＝`A3-test-readings.json`（同卷）；本件与 `test-report.md` 同物（编排面落位名）。

## 结论速览

| 面 | 读数 |
|---|---|
| **patch 应用** | 官方首档 `git apply` 干净施加（本侧 pristine 树 rc=0；镜像 /testbed rc=0，`Applied patch astropy/units/quantity.py cleanly.`）；GNU patch 兜底**未启用** |
| **F2P（1 项）** | 基线红（dtype 断言差）→ 判分容器 **PASSED**（红→绿）｜ judge 对账 **1/1** |
| **P2P（80 项）** | 判分容器 **80/80 全 PASSED**（p2p_unmatched_gold=0，零渲染形态差） |
| **既有面回归** | `astropy/units/` 全包：前 3 failed/1879 passed/3 skipped/6 xfailed ↔ 后完全同值，**新红=0** |
| **官方 verdict** | **`resolved=true`**（diff_valid=true ∧ F2P 1/1 ∧ P2P 80/80；judge_rc=0、judge.stderr 0 字节、hermetic=true、live_http/blocked_urls/socket_connects 全空） |

## §一 收件核（T5，≤10min 锚内）

1. 本侧 codeload pristine 树（`/tmp/bench8872-inv/astropy-base.tar.gz` 新解压，tarball sha256
   `c88679148be7…`＝SPEC §〇 期望值；`quantity.py` sha256[:16]=`569de7c23d180c29`）：
   - `git apply --check --verbose fix.patch` → `正在检查补丁 astropy/units/quantity.py...`，**rc=0**；
   - `patch -p1 --dry-run -i fix.patch` → `checking file astropy/units/quantity.py`，rc=0（兜底路亦通，未启用）。
2. 镜像 `/testbed`（合成 SWE-bench 提交 `dc4f4acd1`，工作树净）：`quantity.py` sha256 与 codeload 树
   **同值**（`569de7c23d180c29…`）——合成提交面与上游 tarball 在触面文件上逐字节同源；容器内
   `git apply --check --verbose /tmp/model_patch.diff` → **rc=0**。
3. 判定：**收件核过，官方 GIT_APPLY_CMDS 首档接受，无兜底必要**（SPEC §4.3-1 的「首档拒收原因」栏不适用）。

## §二 eval.sh 出土（对账）

- `judge/task.json` ← anolis `/data/bench/swev-s1-r0/astropy__astropy-8872.json`（10,795B，
  sha256[:12]=`0039f695aa1a`，两端同值）。
- `python3 -I` 提取 eval_script → `judge/eval.sh`（1,659B），sha256 =
  `53d61fbde8b8…e94e5e`，[:12] **= `53d61fbde8b8` 期望值**（不符即停条款未触发）。
- 题面量纲复核：problem_statement 887B / hints 425B / test_patch 963B / F2P=1 / P2P=80 /
  base_commit `b750a0e6…`——与 SPEC §〇 逐项一致。

## §三 基线容器（无补丁，T6–T7，11s 量级同 D-117）

```
docker run -d --name bench8872-baseline swebench/sweb.eval.x86_64.astropy_1776_astropy-8872:latest sleep infinity
docker cp eval.sh → docker exec bench8872-baseline bash /tmp/eval.sh > baseline_log.txt   # rc=0
```

- **汇总行：`4 failed, 84 passed, 1 xfailed in 2.34s`**（eval.sh 跑法 `pytest -rA astropy/units/tests/test_quantity.py`，施加判分测试补丁后 89 项）。
- **F2P 基线红 = 1 项**（题目本体，形态＝诊断预测）：测试补丁新增的 float16 dtype 保真断言，
  红形态 `AssertionError: assert dtype('float64') == dtype('float16')`——构造路径升档实锤
  （逐字 ID 与全文留 `judge/baseline_log.txt` 内档）。
- 另有 **3 项 era 环境既红**（非 F2P/P2P 对账面，明细见 §七）。

## §四 判分容器（施加 fix.patch，T8 前半）

```
docker run -d --name bench8872-judged <同镜像> sleep infinity
docker exec bench8872-judged bash -c "cd /testbed && git apply --verbose /tmp/model_patch.diff"  # rc=0
docker exec bench8872-judged bash /tmp/eval.sh > judged_log.txt                                  # rc=0
```

- git apply 输出：`Checking patch astropy/units/quantity.py... / Applied patch astropy/units/quantity.py cleanly.`（官方首档；施后 `quantity.py` sha256 `f69dd85cad4e…`）。
- **汇总行：`3 failed, 85 passed, 1 xfailed in 2.05s`**。
- **F2P 项 PASSED（红→绿）**；FAILED 行集合 diff 前后仅剩 F2P 一项翻转，其余 3 行逐字同单。
- 判分输入溯源：`judged_log.txt` sha256[:12]=`678f39becb66` ＝ judge.json `eval_sha256` 同值。

## §五 既有面回归（T8 后半；前=基线容器，后=判分容器）

测试面＝**pristine**（eval.sh 收尾自带 checkout 复原，实测两容器 `test_quantity.py` sha256[:16] 同值
`1e6aa17460f74d2c`；无 test_patch）。面域＝`astropy/units/` 全包（A1 涉及文件邻域）：

```
两侧同命令：python -m pytest astropy/units/ -q --tb=no -p no:cacheprovider   # 各 rc=0
基线容器： 3 failed, 1879 passed, 3 skipped, 6 xfailed in 7.67s
判分容器： 3 failed, 1879 passed, 3 skipped, 6 xfailed in 7.92s
```

- **新红 = 0**；失败集合两侧逐字同单（即 §七 3 项环境既红，与 patch 无关）。诊断预测（谓词收紧只
  改 float16 行为、新红应为零）获证。
- 应用级 dtype 探针（era 栈实测，numpy 1.25.2 / astropy 4.0.dev24917，两侧 `probe_dtype.py`/`probe2.py`）：

| 输入 | 基线容器 | 判分容器 |
|---|---|---|
| float16 标量 × u.km | float64 | **float16** |
| float16 数组 Quantity | float64 | **float16** |
| Quantity(float16 q) 重建 | float64 | **float16** |
| float32 / float64 / float128 | 保真 | 保真（不变） |
| int64 / bool | float64 | float64（R2 防溢出保持） |
| structured `[('a','<f8>')]` | 原样 | 原样（R1 fields 守卫保持） |
| object 数组 | float64 | float64（R3 守卫保持） |

（探针注记：probe2 的 int64 大值**精确等值**断言两侧同为 False——系探针断言自身写错：
float64 尾数精度本不可能精确表示 2⁶²×10⁹；两侧同值恰证行为无漂移。R2 主张以 dtype 升档两侧同
float64 为准，如实记录。）

## §六 判分腿（T9–T11，warm-relay→门→官方判分，零改动）

1. **warm-relay 五步**（D-106 形制；缓存 `tasks/` 原无 8872 条目 ⇒ 必行，未预热禁裸判）：
   `bash repos/factory-os/tools/swev-warm-relay.sh --task judge/task.json --out judge/warm-relay-r1.json
   --remote anolis --remote-dir /data/bench/swev-judge-cache`
   → 五步全绿（1-warm-local 1871ms ｜ 2-judge-attest 3579ms sha 一致 `4a7156dd5e45…`
   ｜ 3-cache-relay 3224ms 条目 12→12 ｜ 4-task-push 1724ms ｜ 5-remote-verify 3418ms
   spec_ok=true source=cache live_http=[]）；**all_ok=true, fail_step=null**，relay_rc=0。
2. **pre-judge 对账门**：`python3 -I tools/judge-deploy-recon-gate.py --pre-judge --fos-root
   repos/factory-os --cache-dir ~/.cache/swev-judge-v2` → **rc=0，结论「绿（pre-judge 放行：
   部署面＋记录面全绿）」**（J1/J5/H4 对账 PASS；输出留 `judge/prejudge-gate-r1.log`）。
3. **官方判分**（anolis 侧，attested 判官件，进程环境无代理/凭据类变量——ssh login env 掩码扫描
   0 命中；docker exec 仅继承镜像环境，测试进程环境剥离纪律成立）：
   ```
   cd /data/bench/bench多角色-8872 && SWEV_JUDGE_V2_CACHE=/data/bench/swev-judge-cache \
     <venv-python3.14> /data/bench/swev-judge-cache/swev-judge-v2.py \
     task.json judged_log.txt model_patch.diff > judge.json 2> judge.stderr   # judge_rc=0
   ```
   - **judge.stderr = 0 字节**（链健康态，D-117 §六口径）；
   - **verdict**：`diff_valid=true` ｜ `log_state=parsed`（markers start/end true）｜
     **f2p_success=1 / f2p_failure=0** ｜ **p2p_success=80 / p2p_failure=0** ｜
     **resolved=true（verdict=resolved）** ｜ hermetic=true ｜ live_http=[] ｜ blocked_urls=[] ｜
     socket_connects=[] ｜ swebench_version=4.1.0 ｜ p2p_id_normalized=[]、p2p_unmatched_gold=0
     （本轮无 D-117 型 ID 渲染差，归一化零触发）。
4. **判官件指纹**：判分前后本侧两活跃面（`tools/`、`repos/factory-os/tools/`）＋远端缓存面
   （`/data/bench/swev-judge-cache/swev-judge-v2.py`）三处 sha256 均 = `4a7156dd5e45…`，零改动零触碰成立。

## §七 失败明细（结构级；逐字 ID 留 judge/ 内档）

| # | 归属 | 形态 | 前/后 | 归因 |
|---|---|---|---|---|
| 1 | **F2P（题目本体）** | 构造路径 dtype 断言差：`assert dtype('float64') == dtype('float16')`（测试补丁新增的 float16 保真断言） | 红→**绿** | 根因谓词 `np.can_cast(np.float32, …)` 对 float16 误判；patch 两处同构替换后修复 |
| 2 | era 环境既红 | `AttributeError: module 'numpy' has no attribute 'int'`——经 `astropy.table` 导入链触发（`_np_utils.pyx` 用已移除别名） | 前×1 后×1（同单） | era numpy 1.25.2 移除 `np.int`；基线固有问题，与 patch 无关，不在 F2P/P2P 对账面 |
| 3 | era 环境既红 | 同 #2 形态（另一用例同走 astropy.table 导入） | 前×1 后×1（同单） | 同 #2 |
| 4 | era 环境既红 | `NotImplementedError: cannot evaluate truth value of quantities…`（quantity.py:1540 既有守卫，经 matplotlib masked_where 路径触发） | 前×1 后×1（同单） | era 环境交互既红，与 patch 无关，不在 F2P/P2P 对账面 |

## §八 诚实注记

1. **全部验收命令本会话实跑绿**：§4.3-1 四产物在盘 rc=0；§4.3-2 eval.sh 指纹 rc=0；
   §4.3-3 `verdict-shape-ok`；§4.3-4 本正文（及 json）零逐字 ID 形态；§4.4-1 `warm-ok`；
   §4.4-2 结论行 rc=0；§4.4-3 stderr 空 rc=0；§4.4-4 判官件前后指纹同值。
2. **资源纪律**：活跃容器 2（baseline/judged，空闲态 sleep infinity 留机可复查，同 D-117 先例）≤3；
   角色并发 1；anolis 主机 125G/16 核，本腿用量远低于测试腿 8G 预算与 Σmem≤45G 顶。
3. **回归面口径**：`pytest astropy/units/` 全包（1,891 项）两侧同命令，未加 `-x`（取完整前后
   计数，优于首败即停）；非全仓回归（按 §4.3-5「A1 涉及文件邻域」口径＝astropy/units/）。
4. **judge.json `tests_collected=81`**＝F2P+P2P 金标清单量纲（1+80），非日志收集量（89）——
   两量纲并存属判官件正常读数，非异常。
5. **not_run：无**——SPEC §4.3/§4.4 六步全部实跑（施工员侧 not_run 的「应用级前红后绿」本腿
   以 era 容器探针补证为实跑）。
6. **回环件 Fb-r{n}：不产出**——verdict=resolved=true，§4.6 回环唯一权威触发不成立。

（落定：2026-11-08 · 测试员 · bench多角色-20261108 ｜ judge/ 留档：task.json、eval.sh、
baseline_log.txt、judged_log.txt、judge.json、judge.stderr(0B)、warm-relay-r1.json、
prejudge-gate-r1.log、regression_baseline.txt、regression_judged.txt、probe_dtype.py）
