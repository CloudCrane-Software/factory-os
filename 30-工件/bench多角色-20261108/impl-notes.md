# 施工说明 · astropy__astropy-8872 fix.patch

> 角色：施工员（bench多角色-20261108）｜ 日期：2026-11-08
> 输入：diagnosis.md（A1）＋题面（problem_statement 887B + hints_text 425B，摘录件 task-face.json 本会话复读核对）
> 产出：`fix.patch`（unified diff / git apply 兼容，sha256 = `cad7015c642ce27b…`，1,023B）
> 判官件 `tools/swev-judge-v2.py` 零改动零触碰（本会话未写 tools/ 任何文件）；凭据零涉及零打印；
> ssh 本会话零调用（取码走 D-117 已证白名单路 codeload@base_commit，tarball 与 SPEC §〇 指纹比对通过后直接消费调查员在盘件）。

## 一、改动点

唯一触面文件 `astropy/units/quantity.py`，两处同构谓词替换，零结构改动、零新文件：

| # | 位置（pristine 基线树行号） | 分支 | 替换 |
|---|---|---|---|
| 1 | `astropy/units/quantity.py:299` | `Quantity.__new__` 的 Quantity→Quantity 拷贝分支 | `np.can_cast(np.float32, value.dtype)` → `np.issubdtype(value.dtype, np.inexact)` |
| 2 | `astropy/units/quantity.py:380` | `Quantity.__new__` 非 Quantity 主路 | 同款替换（同写法两处同用，无分支间语义漂移） |

保持不动项（诊断 R1/R2/R3 守卫）：
- 两处 `value.dtype.fields` 析散项原样保留；
- 第二处 `or value.dtype.kind == 'O'` 原样保留；
- 两处落点（`dtype = float` / `value.astype(float)`）原样保留；
- 行 379 注释原样保留（"cast any integer, boolean, etc., to float" 意图域不变，只修"etc."裂缝）。

patch 逐字内容（22 行，1 file changed, 2 insertions(+), 2 deletions(-)）：

```diff
diff --git a/astropy/units/quantity.py b/astropy/units/quantity.py
index ded609c..677f855 100644
--- a/astropy/units/quantity.py
+++ b/astropy/units/quantity.py
@@ -296,7 +296,7 @@ class Quantity(np.ndarray, metaclass=InheritDocstrings):
                 if not copy:
                     return value

-                if not (np.can_cast(np.float32, value.dtype) or
+                if not (np.issubdtype(value.dtype, np.inexact) or
                         value.dtype.fields):
                     dtype = float

@@ -377,7 +377,7 @@ class Quantity(np.ndarray, metaclass=InheritDocstrings):
                             "Numpy numeric type.")

         # by default, cast any integer, boolean, etc., to float
-        if dtype is None and (not (np.can_cast(np.float32, value.dtype)
+        if dtype is None and (not (np.issubdtype(value.dtype, np.inexact)
                                    or value.dtype.fields)
                               or value.dtype.kind == 'O'):
             value = value.astype(float)
```

## 二、施工过程与取码链

1. 取码：消费调查员在盘 `/tmp/bench8872-inv/astropy-base.tar.gz`，本会话 `sha256sum` 实测
   `c88679148be78ac37d392374b38cabdf1012bc05566297ebd93c5795924e0134`、7,175,498B——
   与 SPEC §〇 期望指纹一致（同 D-117 白名单 codeload 形制产物）。
2. 施工区：`30-工件/bench多角色-20261108/.build/`（工作目录内写，符合纪律）。
   `base/`＝pristine 参照，`work/`＝施工副本（两树 `quantity.py` 起始 sha256 同值
   `569de7c2…` 确认同源后下刀）。
3. 触面定位：`grep -rn "can_cast" astropy/units/` 复测 4 处——299/380 即触面；
   `converters.py:343`（out 缓冲校验）与 `quantity.py:1370`（insert 精度检查）按诊断排除面原样不碰。
4. 生成：`.build/patchgen` 内 git init＋提交 pristine 后 `git diff`，产出标准
   `a/ b/` 形态 unified diff（`git apply` 与 `patch -p1` 双兼容；blob index `ded609c`
   即基线文件内容哈希，与真实仓 /testbed @ b750a0e6 内容同源）。

## 三、自证记录（本会话实跑，命令＋读数）

1. **可应用性（对全新 pristine 解压树，双重验）**：
   - `git apply --check --verbose fix.patch` → `正在检查补丁 astropy/units/quantity.py...`（exit 0）；
   - `patch -p1 --dry-run -i fix.patch` → `checking file astropy/units/quantity.py`。
2. **实落落点核**：fresh 树 `git apply fix.patch` → applied；结果文件与施工副本
   `cmp` → `byte-identical to work tree`；`git apply --check -R` → reverse-check ok
   （patch 恰为完整增量、无多余 hunk）。
3. **形态核**（诊断测试建议 4）：触面仅 `astropy/units/quantity.py` 一文件两 hunk
   （`git diff --stat`：1 file changed, 2 insertions, 2 deletions），无超界文件。
4. **语法核**：`python3 -I -m py_compile` 施工后 quantity.py → OK。
5. **机制级谓词探针**（python3.14.4 + numpy 2.3.5，逐字复刻 L295-303 与 L368-383 两分支，
   旧/新谓词全表对照，`python3 -I` 实跑）：

   ```
   float16        L380: float64    -> float16  | L299: float64    -> float16   <- FIXED（前红→后绿）
   float32        L380: float32    -> float32  | L299: float32    -> float32
   float64        L380: float64    -> float64  | L299: float64    -> float64
   float128       L380: float128   -> float128 | L299: float128   -> float128
   python float   L380: float64    -> float64  | L299: float64    -> float64
   int64          L380: float64    -> float64  | L299: float64    -> float64   （R2 防溢出保持）
   bool           L380: float64    -> float64  | L299: float64    -> float64   （R2 保持）
   structured     L380/L299 均原样 [('a','<f8')] 不升不抛                    （R1 fields 守卫保持）
   object arr     L380: float64    -> float64                              （R3 kind=='O' 保持）
   ```

   与诊断"预期行为变化"表逐行吻合（差异行见下节偏差①）。

## 四、与诊断的偏差

1. **探针偏差（非修复语义偏差，如实记录）**：L299 拷贝分支对**裸 object 数组**输入，
   旧谓词探针输出为保留 object dtype（`np.can_cast(np.float32, object)=True` 所致），
   新谓词为升 float64。该输入在 astropy 真实路径**不可达**：L295 分支仅对
   `isinstance(value, Quantity)` 执行，而经 `__new__` 产生的 Quantity 不可能携带
   object dtype（L372-377 数字检查 + L383 `kind=='O'` 升档双闸保证），故无回归面；
   且新行为与 L380 主路（object→float64）方向一致，属分支间语义归一。诊断预测表
   只列 L380 object 行（保持 float64），本探针确认其保持；诊断未对 L299 object
   行作预测，此处补记。
2. **无其他偏差**：修复语义、守卫保留、同写法两处同用、零扩触面——全部按诊断方案执行。

## 五、not_run（诚实面）

1. **应用级前红后绿**（装好 astropy 后 `(np.float16(1)*u.km).dtype`）：本侧
   python 3.14.4 + numpy 2.3.5 无 era 栈可承载；`astropy_helpers/` 目录本会话 ls 实测
   为空目录（印证诊断"tarball 不含子模块内容"），era 构建垫片属判分容器 era 栈
   （D-117 晚到卷已证可行），施工员腿未跑成——判读以判分容器为准（诊断 R6 口径）。
2. **era numpy（1.x）谓词直测**：未做（同诊断 R6）；以 2.3.5 探针 + API 语义稳定性说明代替。
3. **anolis 远端核验**（判分链/warm-cache/镜像在位性）：本会话零 ssh 调用——
   本施工件产出不依赖远端状态；R7 交接要点（判分前 warm-relay 五步必行，8872
   无条目 fail-closed）按诊断原文移交测试员腿，施工员未复核远端现状。
4. **F2P/P2P 清单内容 / test patch 内容 / eval_script**：零读取（内档纪律 §一.2），
   仅消费计数 F2P=1 / P2P=80。

## 六、测试员腿交接要点（结构级，承诊断）

- patch 应用方式：/testbed 根目录 `git apply fix.patch`（或 `patch -p1`），触面单文件两 hunk；
- 判分前：`swev-warm-relay.sh` 五步预热必行（cache 无 8872 条目即 fail-closed，禁裸判）；
- 判官件与既有 harness 语义零改动（本件未触 tools/）；
- 基线红预期形态：构造路径 float16 升 float64 的 dtype 断言差（1 failed 量级）；
  修复后若现新红，优先核 R1（fields 守卫）/R2（int 防溢出）/R3（object 行）三类误删——
  本探针已证三者保持，残余风险集中在判分容器 era numpy 真值（R6）。

（落定：2026-11-08 · 施工员 · bench多角色-20261108）
