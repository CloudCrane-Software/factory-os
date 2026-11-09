# 诊断报告（A1）· astropy__astropy-8872

> 角色：调查员（bench多角色-20261108 · SPEC v1.0 §4.1）｜ 日期：2026-11-08
> 本件即 SPEC §二布局的 A1 诊断报告；编排面落位名 `diagnosis.md`（与 `A1-diagnosis.md` 同物）。
> 输入面：题面（anolis:/data/bench/swev-s1-r0/astropy__astropy-8872.json 的允许字段，本侧摘录
> /tmp/bench8872-inv/task-face.json；test patch 内容 / FAIL_TO_PASS / PASS_TO_PASS 清单 / eval_script
> **零接触**，内档纪律 §一.2）＋ 基线源码树（codeload tarball `astropy-base.tar.gz`，
> sha256 = `c88679148be78ac37d392374b38cabdf1012bc05566297ebd93c5795924e0134`、7,175,498 字节，
> 与 SPEC §〇 期望指纹逐字节一致〔本会话 sha256sum 实测〕；解压顶层
> `astropy-b750a0e6ee76fb6b8a099a4d16ec51977be46bf6/`，只读参照）。
> 以下行号一律指该 pristine 基线树（施工员取码同路，行号可复算）。

## 问题复述（题面事实清单，逐条标注来源）

- **F1（复现子·标题行）**：`float16 quantities get upgraded to float64 automatically`
  ——题面 problem_statement 标题（task JSON 内嵌键，本侧摘录 task-face.json）。
- **F2（float16 被升档）**：`np.float16(1) * u.km` → `<Quantity 1. km>`，其 `.dtype` =
  `dtype('float64')`——problem_statement 会话记录 In[74]/Out[75]。
- **F3（其他浮点宽度保真）**：`np.float32(1) * u.km` → float32；float64 → float64；
  float128 → float128；Python float（`np.float(1)`）→ float64、`np.float_(1)` → float64
  ——problem_statement Out[76]–Out[80]。即：只有 float16 违背"浮点宽度保真"直觉。
- **F4（期望行为）**：float16 应与其他 inexact 类型一样保真——problem_statement 标题反推
  ＋ hints_text 明示「It does seem reasonable to allow every inexact type」。
- **F5（hints 指认引入点）**：该行为由 gh-1776 引入（题面 hints_text；判分镜像名
  `astropy_1776` 同源）；时点代码在 quantity.py L299 与 L379 两处，判据是
  `np.can_cast(np.float32, value.dtype)`；「half floats were never considered」。
  另注：problem_statement 尾部标「Somewhat related: #6389」（本题非 #6389 本体）。
- **F6（已核前提）**：base_commit = `b750a0e6ee76fb6b8a099a4d16ec51977be46bf6`、
  repo = astropy/astropy、version = 3.1、镜像 = `swebench/sweb.eval.x86.64.astropy_1776_astropy-8872:latest`
  （Image ID `468c8d10c1fc`，anolis `docker images` 本会话实测在盘）；判分规模只给计数
  F2P=1 / P2P=80（D-117 §八口径）。

## 根因

**触发链（复现子 `np.float16(1) * u.km` 的完整代码路径）**：

1. numpy 标量 `np.float16(1)` 与 `u.km` 相乘，因 `UnitBase.__array_priority__ = 1000`
   （`astropy/units/core.py:499`），反射运算使 `UnitBase.__rmul__` 胜出——`core.py:703`；
   `m`（np.float16 标量）无 `.unit` 属性 ⇒ 走 `core.py:717` `return Quantity(m, self)`。
2. `Quantity.__new__`（`astropy/units/quantity.py:272-392`）：输入非 Quantity、非 str、
   非可迭代（np.float16 标量），落非 Quantity 主路：`quantity.py:368`
   `value = np.array(value, dtype=None, …)` → 0-d 数组，dtype=**float16**；
   `quantity.py:371-377` 的 OSU 类型检查通过（kind='f'）。
3. **命中点**：`quantity.py:379-383`：
   升档条件 = `dtype is None` 且（非（`np.can_cast(np.float32, value.dtype)` 或
   `value.dtype.fields`）或 `value.dtype.kind == 'O'`）⇒ `value = value.astype(float)`。
   对 float16：`np.can_cast(np.float32, np.float16)` = **False**（安全降档拒收）、
   fields = None ⇒ 判定"需要升到 float64" ⇒ `astype(float)` ⇒ float64；
   随后 `quantity.py:385` `value.view(cls)` 得 `<Quantity 1. km>`，dtype=float64。
   —— 与 F2 逐项吻合。
4. **为何错（机制级）**：该谓词目的按 `quantity.py:379` 行注释是「by default, cast any
   integer, boolean, etc., to float」——即 gh-1776 防整数溢出的**意图域是"非浮点数"**；
   但实现用 `can_cast(np.float32, dt)` 判"dt 是否装得下 float32"，float16 虽是 inexact
   浮点却装不下 float32，被误并入"整数/布尔"一档（注释里的 "etc." 恰是漏考虑的裂缝）。
   hints_text 自证：gh-1776 只考虑了 ≥float32 的浮点，半精度从未入考虑（F5）。

**第二触面（同谓词的另一分支）**：`quantity.py:295-301`（`__new__` 的 Quantity→Quantity
拷贝分支，`value.dtype.fields` 守卫相同、落点为 `dtype = float` 后经 `quantity.py:303`
`np.array(value, dtype=dtype, …)` 重建）。float16 Quantity 一旦经 dtype=None、copy=True
重建（如 `Quantity(q16)`），同样被升为 float64。hints 指认的两行（L299/L379）与基线树
299/380 两处谓词一一对应——**修复必须两处同改**，只改一处会留下"构造保真、重建升档"
的半修状态。

**排除面（逐一读过、确认非触面）**：
- `Quantity.__array_ufunc__`（`quantity.py:423-476`）：只做单位换算（converters）与
  view 包装，无 dtype 升档逻辑；
- `astropy/units/quantity_helper/converters.py:343` 的 `can_cast(…, casting='same_kind')`：
  是 `out` 输出缓冲的安全校验，失败路径是 raise TypeError，不改 dtype；
- `quantity.py:1370` 的 `can_cast`：`insert` 的精度损失检查，与构造/运算升档无关。

**机制级复现读数（本会话实跑）**：本侧无 era 运行栈（见诚实注记），用 numpy 2.3.5 /
python 3.14.4 探针**逐字复刻 `quantity.py:380-383` 谓词逻辑**（仅 numpy，不导入 astropy），
对六种输入实测输出 dtype：

```
in dtype=float16    -> out dtype=float64    （bug：与题面 Out[75] 吻合）
in dtype=float32    -> out dtype=float32    （与 Out[76] 吻合）
in dtype=float64    -> out dtype=float64    （与 Out[77] 吻合）
in dtype=float128   -> out dtype=float128   （与 Out[78] 吻合）
in dtype=int64      -> out dtype=float64    （gh-1776 本意，保溢出防护）
in dtype=bool       -> out dtype=float64    （同上）
```

六行与题面 Out[74]–Out[80] 逐行吻合 ⇒ 根因机制成立（应用级 not_run 见诚实注记）。

## 修复方案

**唯一触面文件 `astropy/units/quantity.py`，两处同构替换，无结构改动、零新文件。**

1. **`Quantity.__new__` 非 Quantity 分支（`quantity.py:379-383`）**：把谓词里的
   `np.can_cast(np.float32, value.dtype)` 换成 `np.issubdtype(value.dtype, np.inexact)`；
   `value.dtype.fields` 守卫与 `or value.dtype.kind == 'O'` 两个析散项**原样保留**，
   `value.astype(float)` 落点不动。
2. **`Quantity.__new__` Quantity 拷贝分支（`quantity.py:299-301`）**：同款替换
   （此处无 `kind == 'O'` 项，只换 can_cast 为 issubdtype），`dtype = float` 落点不动。

**为什么这样改**：语义对齐意图域——"只有非浮点（整数/布尔/对象）才默认升 float64"，
一切 inexact（float16/32/64/128、complex 族）保真；gh-1776 的整数防溢出初衷不变。
`np.issubdtype` 在 era numpy（1.x）与现役 numpy 语义一致（本侧 2.3.5 探针验证，
1.x 起即有此 API）。等价替代写法：`value.dtype.kind not in 'fc'`（kind 判定）；
推荐 issubdtype——与 hints_text「allow every inexact type」措辞直接对应，可读性更好。
两处择一即可，但**必须同一写法两处同用**，避免分支间语义漂移。

**预期行为变化（前红→后绿，修复后谓词探针实测读数，本会话实跑）**：

```
in dtype=float16    -> out dtype=float16    （前 float64，红→绿）
in dtype=float32    -> out dtype=float32    （不变）
in dtype=float64    -> out dtype=float64    （不变）
in dtype=float128   -> out dtype=float128   （不变）
in dtype=int64      -> out dtype=float64    （不变，防溢出保持）
in dtype=bool       -> out dtype=float64    （不变）
structured [('a','<f8>')] -> 原样不升、不抛错 （不变，fields 守卫保持）
object 数组               -> float64          （不变，kind=='O' 项保持）
```

**施工员自验命令建议（基线树内，前红后绿）**：
装好本仓 astropy（era 栈；装不了按 D-117 先例垫 astropy-helpers + 现装
build-essential 编 C 扩展，或如实 not_run）后：
`python3 -c "import numpy as np; from astropy import units as u; print((np.float16(1)*u.km).dtype)"`
——基线（前）期望输出 float64（红），修复后期望 float16（绿）。

## 涉及文件清单（只非测试文件）

| 路径 | 预期改动性质 |
|---|---|
| `astropy/units/quantity.py` | 两处谓词表达式替换（`Quantity.__new__` 内 295-301 与 379-383 两个分支，各 1–2 行），零结构改动、零新文件、不触任何其他模块 |

（全树其余文件零改动；`quantity_helper/`、`core.py` 均只读排除面，不进 patch。）

## 风险

**回归风险点与施工员自证核法**（每条给"如何自证未踩"）：

- **R1 结构化 dtype 守卫被误删**：若施工员顺手删掉 `value.dtype.fields` 析散项，结构化
  数组将走 `astype(float)`（旧码不升，且可能抛错）。自证：对含 fields 的 dtype 数组跑
  构造探针，修复前后 dtype 均应原样（上面探针已含 structured 行，可复算）。
- **R2 整数防溢出初衷被误伤**：gh-1776 的本意是 int/bool 升 float64（大 scale 单位如
  u.Gm 下 int 会溢出）。自证：`np.int64` 输入的谓词行保持 float64（探针行已列）；施工后
  跑大数构造对照（int64 大值 × 大 scale 单位不溢出）。
- **R3 object 数组路径被误伤**：`kind == 'O'` 项保持（object 数字数组仍升 float64）。
  自证：探针 object 行保持 float64。
- **R4 float16 溢出语义（非回归，但评审可能问）**：修复后 float16 参与原生 numpy 溢出
  语义——float16 Quantity 换算到大 scale 单位（如 u.Em）会得 inf，这与普通 float16 数组
  算术一致，属预期；若判分用例涉及，归因按"原生 float16 语义"写结构级说明。自证：
  float16 裸数组乘同系数对照，行为应与 Quantity 一致。
- **R5 单位换算链中间精度**：`.to()` 换算经 float64 换算系数，numpy 数值提升规则决定
  中间 dtype，可能非 float16——这不属本谓词触面（排除面已核），禁在 patch 里顺手"修
  换算链"（涉及文件 ⊆ 本清单，超界 = 矛盾项 §六）。自证：修复后最小复现只看构造路径
  dtype；换算链读数如与构造不同，在 A2-report 如实记录即可，不扩触面。
- **R6 era numpy 与探针 numpy 的语义漂移**：本侧探针用 numpy 2.3.5（py3.14 无 era
  1.x 轮子可装），判分镜像内为 era numpy。`can_cast`（安全降档拒收）与 `issubdtype`
  对本案六 dtype 的真值在 1.x/2.x 稳定，但**施工员本地自报不作证据**（SPEC §一.9），
  以判分容器（era 栈）读数为准。
- **R7 判分腿环境链（测试员交接）**：anolis:/data/bench/swev-judge-cache/tasks/ 本会话
  ls 实测仅 7606/11133/11141/11149（+.verify 同伴件），**8872 无条目 ⇒ 判分前
  warm-relay 五步必行**（未命中 fail-closed，禁裸判，SPEC §4.4）。三方判官件指纹本会话
  实测一致 = `4a7156dd5e45…`（tools/swev-judge-v2.py、repos/factory-os/tools/
  swev-judge-v2.py、anolis:/data/bench/swev-judge-cache/swev-judge-v2.py 三处
  sha256sum 同值）；anolis <venv-python3.14> 在位。warm-relay
  step2 对账语义（`swev-warm-relay.sh` 件头+②段）：远端缺失→推本侧件；不一致→fail-closed
  不覆盖——三方已一致，step2 应走 attested 快路。

**测试建议（测试员腿，命令书按 SPEC §4.3/§4.4，此处只给结构级要点）**：

1. **基线红核对**（§4.3 第 3 步）：无补丁容器跑 eval 后，F2P 基线红应呈"构造路径
   float16 升 float64"形态（1 failed 量级）；失败形态若不是 dtype 断言差，
   按回环件口径结构级归因。
2. **判分容器 verdict 结构读数**（§4.3 第 6 步）：diff_valid / log_state / f2p / p2p /
   resolved / hermetic / live_http 六项结构级入 A3；逐字 ID 留判分腿内档。
3. **既有面回归**（§4.3 第 5 步）：判分容器对未施加判分测试补丁的基线面做
   astropy/units/ 包级前后对账（-x -q 量级）；本诊断预测：新红应为零（谓词收紧只改变
   float16 行为），如出现新红优先核 R1/R2/R3 三类守卫误删。
4. **patch 形态核**：patch 触面应仅 `astropy/units/quantity.py` 一个文件、两处谓词 hunks；
   超出该文件集合 = 与本诊断矛盾（§六 H2 对拍面）。

## 诚实注记

**实跑清单（本会话命令级留痕）**：
1. 题面抽取：`ssh anolis 'python3 -I -' < extract.py`，只取 instance_id/repo/version/
   base_commit/image/problem_statement/hints_text 七个允许字段（1,646B 落本侧）；
   anolis 侧题面 JSON ls 实测 10,795B（与 SPEC §〇 一致）；test patch / F2P / P2P /
   eval_script 字段零读取零落盘。
2. 取码：codeload tarball sha256 = `c88679148be7…`、7,175,498B，与 SPEC §〇 期望值一致
   （下载约 70s，慢管道形态与 SPEC 所记同源）；解压顶层目录在盘。
3. 判分链对账（只读）：三方判官件 sha256 同值（4a7156dd5e45…）；warm-cache tasks/
   无 8872 条目；镜像 `astropy-8872`（468c8d10c1fc）/7671（ea67d17c5e18）/7166
   （4b46c9269732）三件在盘（`docker images` 实测）；anolis venv python3.14 在位；
   判分链文件只读消费（cb-judge.sh 全文、cb-run.py 判分门段 70-140、swev-warm-relay.sh
   全文、swev-judge-v2.py 455-500），判官件零改动零触碰。
4. 谓词定位：`grep -rn "can_cast" astropy/units/` 全树共 4 处，2 处即本案触面
   （quantity.py:299/380），另 2 处逐一读过排除（converters.py:343、quantity.py:1370）。
5. 机制级复现：numpy 谓词复刻探针两个（旧谓词表 + 修复谓词表），读数见根因/修复方案节；
   探针后对基线树 quantity.py 与 tarball 新解压件 `diff -q` 确认零污染（导入尝试曾触发
   astropy 源码树自建机制，未改动 quantity.py）。

**not_run 清单（诚实面）**：
1. **应用级最小复现**（装好 astropy 后 `(np.float16(1)*u.km).dtype`）：本侧
   python 3.14.4 + numpy 2.3.5 无法承载——基线树导入尝试实录：`astropy/__init__`
   自动触发扩展重建并失败（`IMPORT FAILED: ImportError astropy`；codeload tarball 不含
   astropy_helpers 子模块，era numpy 亦无 py3.14 轮子），完整施工垫片属施工员/测试员腿
   （判分容器 era 栈天然满足，D-117 晚到卷已证垫片可行）。机制级探针已覆盖题面全表，
   但"应用级前红后绿"实证留给施工员自验（命令建议见修复方案节）。
2. **F2P/P2P 清单内容**：未读（内档纪律 §一.2）；本诊断只依赖计数 F2P=1/P2P=80。
3. **hints_text 引用的 gh-1776 本体 / #6389 / 上游任何修复提交**：未访问（泄题防线
   §一.2；只消费题面转述文本）。
4. **era numpy（1.x）谓词直测**：未做（py3.14 无法安装 era 轮子）；以 2.3.5 实测 +
   API 语义稳定性说明代替，风险 R6 已注明判分以 era 容器为准。

**不确定面**：修复后 float16 在 `.to()` 换算链、复合运算链的中间 dtype 未逐路径静态
推演完（R5 已划界：不属本谓词触面，禁扩触面）；判分用例具体断言形态未知（内档），
若 F2P 含换算链断言，回环件会暴露，届时按结构级归因走 §4.6。

（落定：2026-11-08 · 调查员 · bench多角色-20261108）
