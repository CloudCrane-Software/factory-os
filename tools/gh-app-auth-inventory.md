# tools/gh-app-auth-inventory.md — App 凭据样板存量副本盘点（D-139；债本体 D-126）

> **头注纪律（卡面 P2，置顶）**：本件**只盘点不删**——存量副本禁删，收敛**择窗**
> （先盘点后删，保留一份正本；在役件禁动）。卡面原文：「本卡只盘点不收敛（存量
> 收敛择窗，先盘点后删，保留一份正本；在役件禁动）」。
>
> **定位**：D-139 交付单源件 `tools/gh-app-auth.sh`（mint + askpass + api + merge
> 四能力一个 CLI 入口）。本件登记该样板在单源件落盘前的全部已知存量副本坐标，
> 供后续「新面立即改用共享件」与「存量择窗收敛」两件事对账。
>
> **盘点口径**：
> · 坐标 root = 厂内工作区（`/home/pan-ding/workspace/agent黑灯工厂/`），除注明
>   相对 factory-os 仓根的路径（`tools/ledger-sync.sh`）。
> · 「在役」= 当前流程/任务仍在调用或作为只读参照件的副本；「历史」= 已收卷任务
>   目录残留副本（无活跃调用）。
> · 行号为 2026-11-08 实读坐标（债证出处：30-工件/技术债清册-20261107.md D-126
>   行；卡面 factory-os#154 背景段）。
>
> **单源件（本卡新增，正本）**：`tools/gh-app-auth.sh`——四子命令 mint / askpass /
> api / merge；0600 临时件 + 用后 shred + 禁 argv/URL/日志/stdout；`--selftest`
> 五族断言全桩（JWT 形制 / 0600 权限 / askpass 两形态 / curl -K 头注入 / 405
> 自愈轮次）。新施工面**立即改用**本件，不重写样板。

## 存量副本盘点表（11 处）

| 件（坐标） | 行号 | 能力 | 在役性 | 收敛建议 |
|---|---|---|---|---|
| tools/ledger-sync.sh | 743 | 铸 token（openBao 取钥 → RS256 JWT → POST /app/installations/166164132/access_tokens） | 在役（夜轨C3 断点4 闭合件，规划环可见性靠它；卡面禁改） | 择窗：先立替代通道（登记直写仓本 PR 流端到端跑通 + 规划环复读验证）再退役腿，防规划环失明窗（清册 D-126 清偿窗口建议原文） |
| tools/ledger-sync.sh | 836-838 | PAT askpass 现取 → 0600 件 → curl -K 注入 | 在役（同上，三处样板只读作参照） | 同上（同文件同窗退役） |
| tools/ledger-sync.sh | 891-938 | 405 竞速自愈（update-branch 拉平 → 等 gates → 重试）+ 判官复审 | 在役（同上） | 同上（同文件同窗退役） |
| 30-工件/A批执行-20261107/脚本/a1-app-api.sh | 16-37 | mint（openBao 取钥 → JWT → access token；0600 件） | 在役样板（本审计 PR 流即复用后者） | 新面立即改用 gh-app-auth.sh；存量择窗删 |
| 30-工件/A批执行-20261107/脚本/a1-pr-flow.sh | 15-46 | PR 全流程（推分支 → 开 PR → PAT 判官批 → 等 required check → squash → 删支；0600 临时件 + curl -K + shred + 405 自愈） | 在役样板（D-126 债证原文点名「本审计的 PR 流即复用后者」） | 新面立即改用 gh-app-auth.sh；存量择窗删 |
| .w05-d81/app-run.sh | 30-85 | mint + askpass 两形态 + git 包装器（mktemp 0600/700 + trap 清理 + 代理回落） | 历史（D-81 任务目录，已收卷） | 择窗删（保留正本 gh-app-auth.sh 后） |
| .w06-d87/app-api.sh | 25-53 | mint（baoq 取钥 → JWT → access_tokens；直连/代理回落） | 历史（D-87 任务目录） | 择窗删 |
| .w06-d88/gh.sh | 31-89 | mint + askpass 两形态 + 代理回落 + git 包装（D-139 卡面点名可复用参照件，只读） | 历史任务件 / 在飞流程参照（卡面禁改） | 择窗删任务目录副本；参照价值由 gh-app-auth.sh 头注承继 |
| .w07-d102/apptoken.py | 13-18 | mint（python 版：内存签 RS256 JWT → POST access_tokens → 令牌落 0600 件） | 历史（D-102 任务目录） | 择窗删 |
| .w06-d105/appcred/mint.sh | 10-29 | mint（baoq + jq 取钥 → JWT → access_tokens） | 历史（D-105 任务目录） | 择窗删 |
| .w07-d103/appcred/mint.sh | 7-24 | mint（baoq + jq 取钥 → JWT → access_tokens） | 历史（D-103 任务目录） | 择窗删 |

## 收敛总则（择窗执行，不在本卡）

1. **新面立即改用**：本卡之后新写的凭据相关脚本一律调 `tools/gh-app-auth.sh`
   （清册 D-126「清偿窗口建议」原文：新脚本立即改用共享件）。
2. **存量择窗收敛**：与规划环二期变更同窗评估；`tools/ledger-sync.sh` 退役前
   必须先立替代通道并复读验证（防规划环失明窗）；`30-工件/A批执行-20261107/脚本/`
   两件与 `.w0*` 任务目录副本在保留正本后逐步删。
3. **禁删红线**：本卡自身不删任何上表条目（P2）；在役件（ledger-sync.sh 三处、
   A 批两脚本）禁动，只作只读参照。
4. **漂移风险注记**（承债册）：凭据相关逻辑多副本 = 安全姿态漂移面（一处忘
   shred / 忘 mask / 忘 600 即泄漏形态，单点修正不到全体）——收敛到单源件后
   单点修正到全体。
