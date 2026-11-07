# 期望评论要素断言件 · not_resolved 态（D-133 夹具）

定位：`tools/cnb-verdict-reply.py --selftest` 的**期望评论断言件**（卡面 [真锚][D-133]
factory-os#148 交付物②「夹具：judge.json 两态 + 期望评论要素断言件」）。

驱动方式：本件 `## 期望要素断言清单` 小节下每条 `- ` 行，都是一条**必须逐字出现在**
渲染评论里的子串；selftest 逐条断言（缺场即红）。改本件 = 改夹具判据，随主件同批评审。

输入夹具：`judge-not-resolved.json`（D-117 留档 judge.json 逐字复本——
30-工件/夜轨A2-20261107/judge.json；判分读数.md:111-120 回卡实证同源）。
渲染命令：`python3 -I tools/cnb-verdict-reply.py --render --judge
tools/fixtures/cnb-verdict-reply/judge-not-resolved.json --issue 0 --debt D-133`。

公开面纪律（卡面 P2）**对本件自身同样生效**：本件零逐字用例 ID、零测试清单形态、
零凭据形态——卡面验收命令 3 的负例 grep（靶形态：pytest 空串参数化自动索引名、参数化
用例 ID 方括号、F2P·P2P 两键名的字面量、以及 F2P·P2P 键名后接「清单」二字的表述）即以
本件为靶文件；本件因此**刻意不落任何靶串字面量**（形态只作文字描述，见下文「期望缺席
断言」节）。selftest 亦对本件跑同族负例断言（判据表见主件 `FORBIDDEN_IN_COMMENT`）。

---

## 期望评论（canonical · not_resolved）

```markdown
## 判分回卡 · D-133（cnb-verdict-reply ｜ tools/cnb-verdict-reply.py 渲染）

- **verdict**：`not_resolved`（judge.json `verdict` 字段原值。跑得通≠做对题——D-107/D-117 同口径： verdict=not_resolved 也如实回卡，禁把失败卷渲染成成功）
- **judge.json 关键字段**：`diff_valid=true` ｜ `log_state=parsed` ｜ `tests_collected=242`
- **patch 指纹**：`sha256[:12]=5c040ce9bffd`（全值不入公开面，只给前 12 位）
- **F2P 计数**：**1/1**（只给计数）
- **P2P 计数**：**240/241**（只给计数）
- **失配归因（结构级）**：P2P 失配 1 项（结构级：判分对账基准与镜像内 pytest 日志的 ID 形态差，或真实回归——二属一须人工判读 judge.json 与 judged_log；本件只给结构级分类，不指定根因）
- **测试清单**：只给计数（F2P 1/1、P2P 240/241）——零逐字用例 ID、零清单形态
- **凭据形态**：零（本评论经 scrub 预检 clean 后方可贴板；匹配原文永不进输出）

**板面翻格**：`state:rejected`（卡面 P4：只翻 state:* 族；wave 等既有 label 原样保留，quality:* 归回评器 tools/planner-quality-score.py，本件不碰）
```

对应 D-117 回卡实证六要素表（30-工件/夜轨A2-20261107/判分读数.md:120）逐项对齐：

| 六要素 | 本夹具期望形态 | D-117 实证读数 |
|---|---|---|
| ① verdict | `verdict=not_resolved`（原值，禁美化） | verdict=NOT_RESOLVED ✓ |
| ② patch 指纹 | `sha256[:12]=5c040ce9bffd`（全值不入面） | patch sha256[:12]=`5c040ce9bffd` ✓ |
| ③ F2P/P2P 计数 | F2P **1/1**、P2P **240/241**（只给计数） | F2P 1/1＋P2P 240/241 读数 ✓ |
| ④ 失配归因 | 结构级分类（不指定根因、零逐字 ID） | 失配归因（结构级，ID 不入公开面）✓ |
| ⑤ 零凭据形态 | scrub 预检 clean 后才准贴板 | 零凭据形态 ✓ |
| ⑥ 测试清单只给计数 | 只给 F2P/P2P 计数，零清单展开 | 测试清单只给计数 ✓ |

## 期望要素断言清单

- ## 判分回卡 · D-133（cnb-verdict-reply ｜ tools/cnb-verdict-reply.py 渲染）
- - **verdict**：`not_resolved`
- - **judge.json 关键字段**：`diff_valid=true` ｜ `log_state=parsed` ｜ `tests_collected=242`
- - **patch 指纹**：`sha256[:12]=5c040ce9bffd`
- - **F2P 计数**：**1/1**（只给计数）
- - **P2P 计数**：**240/241**（只给计数）
- - **失配归因（结构级）**：P2P 失配 1 项
- - **测试清单**：只给计数（F2P 1/1、P2P 240/241）
- - **凭据形态**：零（本评论经 scrub 预检 clean 后方可贴板
- **板面翻格**：`state:rejected`（卡面 P4：只翻 state:* 族
- quality:* 归回评器 tools/planner-quality-score.py，本件不碰

## 期望缺席断言（禁入公开面形态 · 反例靶）

以下形态**任何一处都不得**出现在渲染评论与本夹具件自身（selftest 对两态评论 +
四个夹具件跑同一负例断言；判据形态表见主件 `FORBIDDEN_IN_COMMENT`）：

- 逐字参数化用例 ID 方括号形态（pytest 空串参数化自动索引名 / 参数化方括号）
- F2P·P2P 清单的字面展开形态（键名后跟方括号列表）
- 带「清单」二字的 F2P·P2P 表述
- 逐字测试节点 ID（模块路径双冒号分隔形态）
- 镜像内自动索引名（unit 后跟数字）
- 凭据形态族（JWT 三段式 / sk- 前缀 / GitHub PAT 前缀 / AWS AK / PEM 私钥块 /
  Bearer 头 / URL 直嵌凭据 / 通用凭据赋值对）——由主件 `SCRUB_PATTERNS` 机检

> 注：上表刻意只作**形态描述**，不落字面靶串——本件自身必须过验收命令 3 的同一条
> 负例 grep，落字面靶串即自击穿。字面靶串只存在于主件源码的判据表内（该表本身
> 不含上述凭据字面量，探测串一律运行时拼装）。
