# D-102-A 施工读数（TAC `sde-fix-factual-mistake`）

- 子卡: factory-os#92 ｜ 父卡: #34 ｜ 债号: D-102-A ｜ task_id: `w07-tac-cotrial-A`
- 施工身份: App `repo-writer4agent`（installation 166164132，contents/pull_requests/issues: write）
- TAC 任务书: `workspaces/tasks/sde-fix-factual-mistake/task.md`（raw.githubusercontent.com HTTP 200，逐字抄录于卡面 #92）

## 一、替身登记（C4 平台耦合，如实登记）

| 项 | 登记 |
|---|---|
| 任务书点名仓 | `http://the-agent-company.com:8929/root/openhands`（TAC 公司 GitLab） |
| 可达性 | **不可达**（本环境无该域名路由；TAC 四服务栈全量上 anolis 属二期，D-15 裁决联动，不在本卡） |
| 替身 | 公开上游 `All-Hands-AI/OpenHands` pinned commit `af5bdf67aa92` |
| pinned 依据 | 该文件最后一次被改动的提交（其子提交 `e6847e9e61bf` = "Move agenthub within openhands (#4130)"，即 agenthub 迁移点） |
| 替身保真 | 实 clone（`git clone --filter=blob:none --no-checkout --shallow-since=2024-05-01`，pinned commit 在历史内）+ blob sha 与 GitHub contents API 逐件对账 |
| 交付物形态 | 文件级 fix（任务书点名文件/行号/目标值）——替身不改变交付物形态 |

## 二、clone 与正本对账

```
$ git clone --filter=blob:none --no-checkout --shallow-since=2024-05-01 \
    https://github.com/All-Hands-AI/OpenHands.git openhands-trial
$ git sparse-checkout set agenthub/micro/math_agent README.md
$ git checkout af5bdf67aa92        # detached HEAD @ pinned commit
$ git log --oneline -1
af5bdf67a Add AgentRejectAction across multiple modules (#1615)
```

| 文件 | 本地 `git hash-object` | GitHub contents API `?ref=af5bdf67aa92` | 对账 |
|---|---|---|---|
| `agenthub/micro/math_agent/agent.yaml` | `9f7dd20c6cfe4d2671298cf6f1e7018d2580ad78` | `9f7dd20c6cfe…`（size 601） | 一致 |
| `README.md`（供子卡 B 接力） | `5c9acd4de3e8a0dc9a1ec9d81313191e94d05ca6` | `5c9acd4de3e8…`（size 6508） | 一致 |

## 三、两处订正（任务书点名行号，1-based）

```
-      answer: "Saturday"      →  +      answer: "Thursday"      # L20
-      answer: "0.603848"      →  +      answer: "0.620537"      # L24
```

diff 全文见 `agent.yaml.patch`（单 hunk、单文件、删 2 增 2）。

## 四、事实独立复核（不采信任务书给的订正值，自行算）

| 断言 | 复核方法 | 结果 |
|---|---|---|
| 2099-01-01 的星期 | `datetime.date(2099,1,1).strftime('%A')` | **Thursday**（任务书订正值正确） |
| ∫₋₁¹ sin(x²)dx | Simpson（n=10⁶ 区间）与 Taylor 级数（k=0..11）两法 | 两法均 **0.620536603**（一致到 1e-9）；任务书"close to 0.620537"= 6 位有效数字表述，差 4e-7 |

## 五、机验读数（`python3 -I verify_A.py`，exit=0）

```
V1 ok  L20 = answer: "Thursday"
V2 ok  L24 = 0.620537000（与 0.620537 差 0.00e+00）
V3a ok  datetime.date(2099,1,1).strftime('%A') = Thursday
V3b ok  Simpson=0.620536603  series=0.620536603（一致；0.620537 为 6 位有效数字表述）
V4 ok  diff 仅触 agenthub/micro/math_agent/agent.yaml，删 2 行/增 2 行（=任务书点名两处）
V5 ok  diff index 原 sha 9f7dd20c6… = pinned 9f7dd20c6cfe 前缀（commit af5bdf67aa92）；新 sha 9630e48f5… = 交付正本 blob sha
V6 ok  交付正本→反撤两处订正→blob sha == pinned API 对账值（9f7dd20c6cfe4d2671298cf6f1e7018d2580ad78），链自洽
VERDICT: A 交付物机验全过（V1-V6）
```

## 六、交接信息（供子卡 B / af-relay 消费）

- 上游树 pinned commit：`af5bdf67aa92`（A、B 同树）
- A 的施工 commit（本地 trial 仓，App bot 归因）：`c531af4d764a79c85afd1695e3047a549f13a701`
- 本卡产物在 factory-os 的落点：`状态观测/D-102-TAC协同试跑-20261107/A-sde-fix-factual-mistake/`
- 未决事项：见 af-relay 交接块 `open_items` 字段（板面机读，不在此正文自报）

## 七、口径声明

- 「跑得通≠做对题」同 #8 口径：本卡只证明 TAC 任务本体被正确执行到文件级、且事实复核独立成立；不声称 benchmark 计分。
- 本 `verify_A.py` 是本卡试跑产物（非在役工具件），按 factory-os README §一 收录口径**不进 `tools/`**。
