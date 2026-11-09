# 终考题面：台账分析器三件套（EXAM-E1/E2/E3）

> 本题面为公开面。判官黄金件与参考数据外置封存（不出仓）。验收=调度侧判官四门（G1 参考全过／G2 空实现必红／G3 变异判别 ≥90%／G4 确定性逐字节）。

## Feature A：`tools/exam-parse-manifest.py`（EXAM-E1）

- 输入：一个 wave manifest JSON 文件路径（argv[1]；字段同 `波次清单/wave-NN.json` 的 `cards[]`：task_id/debt/state/channel/mem_budget/allowed_paths）
- 输出（stdout）：每卡一行 JSONL，键序固定 `task_id,debt,state,channel,mem_budget,n_paths`，分隔符 `,`/`:`（compact），`n_paths=len(allowed_paths)`；**卡序=manifest 卡序**
- 非法输入（文件缺/坏 JSON/缺卡字段）：stderr 一行 `E: <原因>`，exit 2

## Feature B：`tools/exam-aggregate.py`（EXAM-E2）

- 输入：Feature A 的 JSONL 文件路径（argv[1]）
- 输出（stdout）：单行 JSON（compact，`sort_keys=True`），键：
  `waves`（task_id 首段 `-` 前缀去重升序列表）、`cards_per_wave`、`state_distribution`、`channel_distribution`（三者为计数 dict，键升序）、`total_cards`、`total_mem_budget`
- 非法输入：同 A 语义 exit 2

## Feature C：`tools/exam-render-report.py`（EXAM-E3）

- 输入：Feature B 的 stats JSON 文件路径（argv[1]）
- 输出（stdout）：markdown 报告，模板逐行固定：
  `# 考试聚合报告` / 空 / `- 总卡数: N` / `- 总内存预算: NG` / `- 每波卡数:` / 每波 `  - <wave>: <n>` / `- 状态分布:` / 每态 `  - <state>: <n>` / `- 通道分布:` / 每通道 `  - <channel>: <n>`
  （三组内键均升序）
- 非法输入：同 A 语义 exit 2

## 通用纪律

- 三件互相独立可执行；B 只吃 A 的输出形，C 只吃 B 的输出形（管道组合可跑）
- 确定性：同输入两次运行 stdout 逐字节同（禁时间戳/随机/字典序漂移）
- 禁硬编码任何期望输出值（判官含变异判别门）
- 台账锚：EXAM-E1/E2/E3（三锚各一卡；三卡有依赖 E1→E2→E3，同波时 depends_on 声明链）
