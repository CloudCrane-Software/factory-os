# D-102-B 施工读数（TAC `sde-update-readme`）

- 子卡: factory-os#93 ｜ 父卡: #34 ｜ 债号: D-102-B ｜ task_id: `w07-tac-cotrial-B`
- 施工身份: App `repo-writer4agent`（installation 166164132）
- TAC 任务书: `workspaces/tasks/sde-update-readme/task.md`（raw.githubusercontent.com HTTP 200，逐字抄录于卡面 #93）

## 一、接力链（S4 第二棒，先读交接块再动笔）

sweep 提取 A 的 af-relay 交接块（`python3 -I sweep.py 92`，仓内正本解析器 `tools/sandbox-obs-weekly.py:parse_structured_comment`，判据件零改动）：

```
SWEEP issue #92 —— 评论 2 条
  [af-relay] cid=6695811533 author=repo-writer4agent[bot](Bot) trusted=YES valid=True missing=[] 2026-11-06T21:16:28Z
        from             = bot-lane · 子卡A（factory-os#92 · D-102-A）
        to               = next-claimant（子卡B factory-os#93 · D-102-B）
        carries          = PR #94（squash merge sha 5d105f8f9446871f0666a54af801a67f750d7253）＋上游 pinned commit af5bdf67aa92（A/B 同树）＋本卡合线后的 factory-os main
        handoff_verdict  = handoff-clean
```

B 消费到的物料：PR #94 merge sha `5d105f8f…`、上游 pinned commit `af5bdf67aa92`、A 合线后的 factory-os main。本地 `git pull origin main` → `origin/main = 5d105f8`，A 的四件产物在树，树内 `agent.yaml` blob sha `9630e48f52f35d2d655ad6fdc97c99011fc2f26e`（= A 的 diff 新 sha）。

## 二、waiting-supply 实演读数（Q1 §4.2 第一实例）

label 事件链（`GET /issues/93/events` 回读，禁手抄）：

| 时刻（UTC） | 事件 | 操作者 |
|---|---|---|
| 2026-11-06T21:06:12Z | labeled `wave` + `state:queued` | feasy898 |
| 2026-11-06T21:06:31Z | parent_issue_added（挂到父卡 #34） | — |
| 2026-11-06T21:06:40Z | blocked_by_added（依赖子卡 A #92） | — |
| 2026-11-06T21:17:56Z | `state:queued` → `state:running` | feasy898 |
| 2026-11-06T21:18:12Z | `/need-context` 结构化评论（cid=6695851879，App bot，valid=True） | repo-writer4agent[bot] |
| 2026-11-06T21:18:54Z | labeled **`blocked`**（叠加位；harness sweep 语义） | repo-writer4agent[bot] |
| 2026-11-06T21:19:59Z | `/progress` 心跳（cid=6695892977，App bot） | repo-writer4agent[bot] |
| 2026-11-06T21:20:16Z | planner 补料裁定（cid=6695899910，PAT） | feasy898 |
| 2026-11-06T21:20:35Z | unlabeled **`blocked`**（悬置回收衔接） | repo-writer4agent[bot] |

SLA 读数（`python3 -I sweep-consume.py 93` 回读）：

```
最新受信阻塞信号：cid=6695851879 marker=/need-context at=2026-11-06T21:18:12Z valid=True
  心跳 /progress cid=6695892977 at=2026-11-06T21:19:59Z doing=… next=…
补料到达：cid=6695899910 author=feasy898 at=2026-11-06T21:20:16Z
SLA 窗（阻塞→补料）= 124 s；等待窗内心跳 1 条 ⇒ 合法等待（非失联）
动作：摘 blocked 叠加位 → HTTP 200（悬置回收衔接）
VERDICT: 补料已到达，等待态关闭
```

**合法等待 vs 失联区分**：等待窗（124 s）内有受信 `/progress` 心跳 1 条 ⇒ 判合法等待；若心跳停且超过 30min（契约 §7.5 默认）则转 STALL 语义（回收交既有 STALL 面，本件只报读数不做回收动作）。本窗内两种形态都未触发失联分支。

**如实登记（不隐）**：
1. 本窗的触发原因是 B 的**真阻塞**——任务书点名的 "api-server repository" 在公司 wiki（不可达）里定位不了，B 在拿到 planner 裁定前不动笔（不猜仓库冒充）。它不是为演示而编造的等待。
2. 卡面步 3 写的时序是「B 等 A 合线期间挂 waiting-supply」；本试跑中 A 的合线先于 B 开窗完成（两棒在同一会话内背靠背施工），故 B 实际等的是 **planner 对替身目标的裁定**而非 A 的合线。机制四步（结构化异议 → sweep 打 blocked 叠加位 → planner 补料 → sweep 摘位回收）与 SLA 时点全部实走，时序偏差在此登记，不冒充成卡面写的时序。
3. 仓内**没有**已部署的 */20 cron 消费件会把 `blocked` 叠加位打上板面（grep tools/ 无此件；`planner-quality-score.py` 只有 `quality:*` 叠加位先例）。本试跑的 sweep 消费步由本卡 sweep 脚本代行（用 App installation token 写 label），登记为「机制试跑」而非「在役 cron」。

## 三、替身登记（C4 平台耦合）

- 公司 wiki / GitLab（`the-agent-company.com:8929`）不可达 ⇒ 不定位 "api-server repository"、不拿 org 内任何仓的 README 冒充（planner 裁定 2）。
- 替身正本（唯一，planner 裁定 1）：`All-Hands-AI/OpenHands` pinned commit `af5bdf67aa92` 根部 `README.md`，blob sha `5c9acd4de3e8a0dc9a1ec9d81313191e94d05ca6`，size 6508。**blob sha 对账通过后才动笔**（verify_B.py V5）。
- 执行的是任务书中与平台无关的文件级交付物部分；交付物形态（文件级 diff）不变。

## 四、交付物与机验（`python3 -I verify_B.py` → exit=0）

| 件 | 说明 |
|---|---|
| `README-contribute-section.md` | 新增章节正本（4 行） |
| `README-after.md` | 插入章节后的 README 全本（blob sha `0fc856d6bfaa…`） |
| `readme-contribute.patch` | 统一 diff（单文件、删 0 增 4） |
| `verify_B.py` | 机验件 V1–V7 |
| `readings.md` | 本件 |

```
V1 ok  标题 level-2 且逐字 = ## Contribute to this project
V2 ok  标题下文本逐字 = We welcome contributions to this project. Please follow the guidelines to contribute.
V3 ok  内容后恰一空行（章节件 = 标题+空行+文本+空行，共 4 行）
V4 ok  章节恰 1 次，插在 License 段内容行之后、链接引用定义之前（1-based 行 111）
V5 ok  交付正本撤下该 4 行 → blob sha == pinned API 对账值 5c9acd4de3e8a0dc9a1ec9d81313191e94d05ca6（commit af5bdf67aa92）
V6 ok  diff 单文件 README.md、删 0 行、增 4 行（=章节件四行逐字）
V7 ok  index 原 sha 5c9acd4de… = pinned 前缀；新 sha 0fc856d6b… = 交付正本 blob sha
VERDICT: B 交付物机验全过（V1-V7）
```

## 五、接力链可回放

trial 仓（等价公司仓替身）提交链：`af5bdf67a`（pinned 上游）→ `c531af4d7`（A：agent.yaml 两处订正）→ `d374d54d3`（B：README 新增章节）。B 的 commit 直接坐在 A 的 commit 之上——接力不是口头约定，是树上的先后。

## 六、口径声明

- 「跑得通≠做对题」同 #8 口径：本卡证明 TAC 任务本体被正确执行到文件级；不声称 benchmark 计分。
- `verify_B.py` 是本卡试跑产物（非在役工具件），按 factory-os README §一 收录口径**不进 `tools/`**。
