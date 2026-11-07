# 期望评论要素断言件 · resolved 态（D-133 夹具）

定位：`tools/cnb-verdict-reply.py --selftest` 的**期望评论断言件（resolved 态）**——
与 `expected-comment.md`（not_resolved 态）成对，共覆卡面「judge.json 两态」要求。

驱动方式：本件 `## 期望要素断言清单` 小节下每条 `- ` 行，都是一条**必须逐字出现在**
渲染评论里的子串；selftest 逐条断言（缺场即红）。改本件 = 改夹具判据，随主件同批评审。

输入夹具：`judge-resolved.json`（A6 翻正态 judge.json 的**脱敏复本**——源 =
30-工件/A批执行-20261107/A6-P2P归一化-20261107/夹具/A-d117-realcase/judge.json）。
脱敏点（卡面 P2）：源件的 `p2p_id_normalized` 是 ID 对**数组**（含逐字用例 ID），
按公开面纪律不得入公开面，本复本改为**计数形态**（`"p2p_id_normalized": 1`）；
主件 `read_judge` 两态都归一（数组取长度、整数取本值），只读计数、不读 ID 列。
其余字段（verdict/diff_valid/log_state/F2P·P2P 计数/diff_sha256）与源件逐字一致。

渲染命令：`python3 -I tools/cnb-verdict-reply.py --render --judge
tools/fixtures/cnb-verdict-reply/judge-resolved.json --issue 90 --debt D-117`。

历史对齐（卡面背景段）：A6 翻正先例 = 判官件 P2P 归一化修误判后 verdict=resolved，
卡 fos#90 翻 `state:merged`（计划/阶段欠账台账.md:144 D-117 行）——本夹具即该态的
回卡渲染期望，翻格两形态（merged/rejected）因此均有夹具实证。

公开面纪律（卡面 P2）**对本件自身同样生效**：本件零逐字用例 ID、零测试清单形态、
零凭据形态——selftest 对本件跑与验收命令 3 同族的负例断言。

---

## 期望评论（canonical · resolved）

```markdown
## 判分回卡 · D-117（cnb-verdict-reply ｜ tools/cnb-verdict-reply.py 渲染）

- **verdict**：`resolved`（judge.json `verdict` 字段原值。跑得通≠做对题——D-107/D-117 同口径： verdict=not_resolved 也如实回卡，禁把失败卷渲染成成功）
- **judge.json 关键字段**：`diff_valid=true` ｜ `log_state=parsed` ｜ `tests_collected=242`
- **patch 指纹**：`sha256[:12]=5c040ce9bffd`（全值不入公开面，只给前 12 位）
- **F2P 计数**：**1/1**（只给计数）
- **P2P 计数**：**241/241**（只给计数）
- **失配归因（结构级）**：零失配项（F2P/P2P 全过）
- **测试清单**：只给计数（F2P 1/1、P2P 241/241）——零逐字用例 ID、零清单形态
- **凭据形态**：零（本评论经 scrub 预检 clean 后方可贴板；匹配原文永不进输出）

**板面翻格**：`state:merged`（卡面 P4：只翻 state:* 族；wave 等既有 label 原样保留，quality:* 归回评器 tools/planner-quality-score.py，本件不碰）
```

## 期望要素断言清单

- ## 判分回卡 · D-117（cnb-verdict-reply ｜ tools/cnb-verdict-reply.py 渲染）
- - **verdict**：`resolved`
- - **judge.json 关键字段**：`diff_valid=true` ｜ `log_state=parsed` ｜ `tests_collected=242`
- - **patch 指纹**：`sha256[:12]=5c040ce9bffd`
- - **F2P 计数**：**1/1**（只给计数）
- - **P2P 计数**：**241/241**（只给计数）
- - **失配归因（结构级）**：零失配项（F2P/P2P 全过）
- - **测试清单**：只给计数（F2P 1/1、P2P 241/241）
- - **凭据形态**：零（本评论经 scrub 预检 clean 后方可贴板
- **板面翻格**：`state:merged`（卡面 P4：只翻 state:* 族

## 期望缺席断言（禁入公开面形态 · 反例靶）

与 `expected-comment.md` 同族同口径：渲染评论与本夹具件自身，任何一处都不得出现
逐字参数化用例 ID、F2P·P2P 清单字面展开、带「清单」二字的 F2P·P2P 表述、逐字测试
节点 ID（双冒号分隔）、镜像内自动索引名、凭据形态族。形态描述不落字面靶串（防本件
自击穿验收命令 3 的负例 grep）；字面靶串只存在于主件源码判据表内。
