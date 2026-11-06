#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""numbers-sota-check.py — G10 机算正本「值级对账」常驻门（all-gates L3 挂载 + 负向自测）。

背景（2026-11-02 红队终局轮确证发现）：G10 的监测手段只数 numbers json 的 `value` 键
个数（恒 73）——键数与「键值是否失真」无因果关系；而 `grep -rn "numbers-sota" tools/`
= 0 命中（无任何门/工具解析该机算正本）。实证：正本多条键值已与现势不符
（strategies_entries_on_disk 60→61、needs_syntax 11→12、experiment inconclusive 2→3、
KB 卡库 17986/9652/113/27751→25125/18179/1270/44574、HEAD a0418ef→b3d5330、
task-seeds 1265→7089、kb-atoms 0→458），漂移自报只覆盖 3 个 SIL 计数键 → 该门在原理
上永远测不出值失真。

修法（最小、只读、不弱化任何既有断言；判据不复制——正本自报命令为准据）：
  ① 键数不变量保留但**降级为口径自洽项**：严格递归「含 value 键的 dict」计数须 ==
     meta.verification.value_key_count_declared（原 73），键增删即红；
  ② **值级复算（新增能力，本门核心）**：正本每个 value 键在 meta.verification.legs
     里登记为 live（本地可机算）或 snapshot（点时快照、本地不可复算）。live 腿逐条跑
     登记的可执行命令复算并与登记值比对——exact / gte / exact-json / exact-list 四种
     口径，**漂移即红**（先例：af 仓 ci/step12_check.py「限定名键逐键跑来源命令复算、
     漂移即红」，本门把该纪律搬到 SOTA 正本上——先前本正本的 source 只是散文描述，
     无法机跑，故无人能对账）；
  ③ **盲区显式化**：全部 value 键必须被 legs 分类（未分类即红）；live 腿数有下限
     （live_leg_min——堵「把腿降级成 snapshot 来消音」）；snapshot 腿必须带 as_of 与
     「为何不可复算」理由，且逐条打印（明示盲区，不静默当成绿）；
  ④ **删键消音堵死**：legs 登记的键必须在本正本存在（删键即红）；
  ⑤ **时效失真即红**：live 腿/组带 as_of，超过 max_age_hours 未复核即红——本次发现的
     形态正是「活账长期不刷新、无人订阅」，故本门把「该刷新了」做成红而不是提醒；
  ⑥ **分区账自洽（KB 卡库三态+总数分组腿）**：登记侧三态和 == 登记总数（改任一数字
     即红）、活侧三态和 == 活总数、活总数 >= 登记总数（卡库被重建/清空即红）、登记
     分项 <= 活总数（过报即红）、活分项 < 登记分项（= SIL 重分类：candidate→
     verified/rejected 是常态且总量不变，**只提示不判红**——登记侧分区自洽已挡住
     「改任一分项」，「卡库被重建/清空」由「活总数 < 登记总数」判红）。

判定口径：
  live 腿 kind=exact      —— 复算值须与登记值**相等**（结构量：条目数/三态/状态分布/
                             比率/清单/布尔/提交在位）；不等即红。
  live 腿 kind=gte        —— 复算值须 **>=** 登记值（单调活账：卡库总量、轮次、文件
                             数、ISO 时间戳）；复算 < 登记 = 过报即红。
  live 腿 kind=exact-json —— 复算输出按 JSON 解析后须与登记对象相等（tier 分布）。
  live 腿 kind=exact-list —— 复算输出按逗号切分后须与登记清单逐项相等（needs_syntax
                             A/B 档 10 条清单）。
  snapshot 腿             —— 本地不可复算（远程扫描/公网榜单/文档抄录/点时读数），
                             不参与值级比对，但必须带 as_of + 理由，且逐条打印。

退出码：0=全过；1=红（值漂移/口径违规/盲区违规/时效失真）；2=基础设施缺件或坏件
        （缺件红、不静默放行——与 all-gates「摘门必须显式红」同口径）。
用法：
  python3 -I tools/numbers-sota-check.py              # 值级对账（只读，rc 0/1/2）
  python3 -I tools/numbers-sota-check.py --selftest    # 判别力负向自测（rc 0/2）
  python3 -I tools/numbers-sota-check.py --refresh      # 复核并回写 live 腿登记值（留 .bak）
  python3 -I tools/numbers-sota-check.py --make-pin     # 打印配套钉桩 JSON（stdout，不写文件）

【2026-11-03 RT 修复批：独立钉桩——命令集不得与登记值同处一文件】
确证洞（本次实测）：复算命令从**被验正本自身**的 meta.verification.legs 读出
（:299/:321/:426），故「把某条 live 腿的 recheck 改成 `echo 1`、把该腿的 value
改成 1」即可让该门自证为绿（亲跑 rc=0 / RED=0）；再跑 --refresh 更把篡改值写回
正本并重打 as_of（龄 0.0h），自证闭环完成。正本与门本体两个件在全仓 0 处摘要锚
（对照：L5 部署一致性门用 known-good md5 钉在役件）。
修法（最小、不弱化任何既有断言）：
  ⓪ **独立钉桩**：命令集/结构清单（腿路径/类别/口径/工作目录/复算命令 + 分组定义
     + 键数声明/live 腿下限/时效上限）的 sha256 锚在**另一个文件**
     tools/numbers-sota-check.pin.json（正本之外）——复算命令与登记值不再同处一
     文件，改一行即自证的形态被钉死。钉桩含门本体摘要（改门亦须同步改钉桩）。
     · 钉桩失配 → 硬红，且**不执行**任何登记复算命令（fail-closed：被篡改的
       命令集不得被执行，更不得被写回）；
     · 钉桩缺件/坏件 → rc=2（缺件红、不静默放行）；
     · --refresh 钉桩失配 → **拒绝回写**（回写=把篡改值写回正本并重打 as_of）；
     · 钉桩清单**不含** value 与 as_of——合法刷新会改这两者，纳入即误判。
  维护契约（三处，缺一即红）：改正本命令集 → ① 重新生成钉桩（--make-pin）
    ② 同步 tools/all-gates.sh 里的摘要常量 ③ 在 计划/变更日志.md 登记钉桩 sha256。
    （all-gates.sh 的摘要常量是**门本体之外**的第三锚：改门本体并删掉自检时，
     仍由 all-gates 摘要对账抓住——对照 L5 D1b 的 known-good md5 钉桩先例。）

【2026-11-03 RT 修复批（分数带值级复算）：锚1 段（分数带所在段）不再是 snapshot 岛】
确证洞（本次实测）：锚1 段（anchor1_benchmark_score_band）28 个 value 键**全为
snapshot**——含 5 个 public_band_* 带值键、2 个 gap_vs_* 差距键、anchor1_verdict；
门对它们只打印「不作值级机检腿，只作点时快照」。实测：把带值
public_band_2025_same_harness_pct 由 64.93 改成 20.00、成员集键改成 [9.9]*4、
差距键 47.9 改成 0.1 后，门仍 rc=0（PASS=26/RED=0）——**分数带这半边零值级机检**，
而 20.00 < 实测 28.90 恰可把锚1 判定从「未达标」翻成「达标」。唯一做带定义/
成员集对账的探针（计划/研究组/对标批-20261031/swev-banddef-check.py）无任何机器
消费者（all-gates/test-manifest/cron 0 命中）＝孤儿脚本。
修法（最小、不弱化任何既有断言）：
  ⓪ **带值改登记为 live 机检腿**：5 个带值键 + 2 个差距键在正本
     meta.verification.legs 里由 snapshot 改为 live（kind=exact / exact-json），
     复算命令＝本地证据件的复算源
     `python3 -I 计划/研究组/对标批-20261031/swev-banddef-check.py --emit <键>
      --numbers {SELF} --expect-sha <探针 sha256>`
     （该探针按 §D 的**定义规则**从 §A/§B/§C 行表 + 论文表复算出带值：全表最高 /
     同 harness 最高 / 2025 同 harness 带下沿 / 论文 test 集 / 2024 SWE-agent 成员集；
     差距键＝带上沿−被验正本里的实测值）。故带值不再是「无人可验的点时快照」。
  ⓪b **复算源本体摘要锚**：live 腿可登记 tool（复算脚本路径）+ tool_sha256；
     门在复算**前**先对摘要——不符即红且**不执行**被改的脚本（改脚本让它吐假值
     ＝自证）。tool/tool_sha256 纳入独立钉桩清单（改声明即钉桩失配）。
  ⓪c **{SELF} 占位**：复算命令里 {SELF} 由门替换成**被验正本**的绝对路径——
     差距键复算读的是被验的那一份（否则门检查副本时算的是别的文件的值）。
  维护契约（改复算源/正本腿声明必改四处）：①重算复算源 sha256 → ②更新正本
     legs 的 recheck（--expect-sha）→ ③--make-pin 重生成钉桩 → ④同步
     tools/all-gates.sh 的 G10_TOOL_SHA256/G10_PIN_SHA256 并在 计划/变更日志.md
     登记钉桩 sha256。

【2026-11-03 RT-SOTABODY 批：报告正文 ↔ 机算正本 值级对账 + 结论回指键一致性】
确证洞（红队终局轮复现，非推演）：①**报告正文与机算正本现势漂移**——报告正文
（计划/研究组/对标批-20261031/SOTA对标报告-20261031.md）写「全库 60 条 /
needs_syntax 11 / inconclusive 2 / tier C 1 / 可编译率 53.33%」，而同一正本的
同名 live 腿实测为 61 / 12 / 3 / C2 / 52.46%；②**正本自身的结论回指键与同一
文件的 live 腿直接矛盾**——`anchor2_verdict`（59/60 簇、11 簇 needs_syntax）、
`anchor3_verdict`（共识 59/60 簇、inconclusive×2）与 live 腿（61 条 / 12 簇 /
3 条）冲突，且这两个键是 snapshot 腿（门只点名不判红）；③**无任何机器对账面**
——修前 `grep -n "SOTA对标报告\\|公开分数带\\|对标批" tools/numbers-sota-check.py`
= 0 命中（门从不打开报告/证据件），映射 G10 行对条款②「差距报告」的核验只有
存在性（报告头 + §1.4 闭合表 + §4.3 未做清单在案），不比对任何数字。
修法（最小、不弱化任何既有断言、判定不复制——正本登记值为准据）：
  ⓪ **报告路径钉死在门本体内**（不在正本里、不由命令行覆盖：命令行覆盖只在
     `--file` 也被覆盖的沙箱件上生效；在役正本强制用钉死路径）——换件/换路径
     即失守；
  ① **正文↔正本值级对账**：门打开报告正文，按规则表逐条抽正文里的数字，与正本
     对应 value 键的登记值逐个比对——**任一不等即红**；**规则未命中（该句被删/
     被改写）同样判红**（「删掉断言」不得成为消音手段）；
  ② **结论回指键 ↔ live 腿一致性**：两个 verdict 键内嵌的条目数/缺口簇数/终裁
     计数**必须**与同文件 live 腿登记值一致——不一致即红（矛盾即红）。
  维护契约：改规则表或报告路径 → ①--make-pin 重生成钉桩 ②同步 tools/all-gates.sh
  的 G10_TOOL_SHA256/G10_PIN_SHA256 ③在 计划/变更日志.md 登记钉桩 sha256
  （三处缺一即红）。

【2026-11-03 RT-锚1钉值批：锚1 判定链快照值钉桩——同文件一致篡改实测/判定/回指键的翻转形态被钉死】
确证洞（本轮亲跑复现）：把正本 6 个 value 键**一致篡改**——实测
swev_order_solve_rate_pct 28.9→70.0、参照实测 swev_decided_subset_solve_rate_pct
53.37→70.11、两个差距键 47.9→6.8 / 23.43→6.69（差距键是 live 腿，但其复算源
banddef 的实测操作数读自被验正本自身 {SELF}——实测改了「复算」跟着继承）、判定串
anchor1_verdict 翻成『达标（不可直接比；实测 70.00% 为下界）』、
cross_anchor/anchors_passing 1→3、cross_anchor/g11_terminal_judgement_input
改写——两台常驻门零新红：本门 SUMMARY 与基线逐字全同（篡改件自相矛盾
anchor1_verdict=达标 ∧ g11=『锚1 判未达』∧ anchors_passing=3，且与未改报告 §〇
锚1 行 28.90%/未达标 冲突），banddef 门 PASS=57 FAIL=0。根因（file:line）：
  · manifest_of_doc 明注钉桩「不收 value 与 as_of」（只锚命令集/结构）；
  · REPORT_BODY_RULES 全表对锚1 只有 3 条带值规则——锚1 实测行/判定行/
    anchors_passing/g11 键零规则；VERDICT_RULES 仅 anchor2/anchor3 8 条；
  · 锚1 段 21 条腿 class=snapshot 只打印（SNAP 行）不判红——「比较式另一操作数
    （工厂实测）与三个结论回指键」在全部机检面之外。
修法（最小、不弱化任何既有断言；只收**锚1 判定链**的快照键，不动 live 腿）：
  ⓪ **快照值钉桩**：锚1 判定链 5 键（实测 swev_order_solve_rate_pct、参照实测
     swev_decided_subset_solve_rate_pct、判定串 anchor1_verdict、
     cross_anchor/anchors_passing、cross_anchor/g11_terminal_judgement_input）
     的**值**随 --make-pin 写进独立钉桩文件的 snapshot_value_pins 段；验钉桩时
     逐键比对正本现值——任一不等即红，且**不执行**任何登记复算命令（fail-closed
     同命令集失配口径）。快照腿不经 --refresh 回写，值钉桩不影响合法刷新；快照值
     只能被手改——手改=锚1 判定链变化=必须走重钉桩三步留痕（与改命令集同款）：
     ①--make-pin 重生成 ②同步 tools/all-gates.sh 两常量 ③变更日志登记 sha256。
  ① **报告正文锚1 行规则 +3**：§〇 总览锚1 行（实测%+同 harness 上沿%，判定列
     『**未达标**』以字面量进规则——改写即规则未命中=红）、§4.1 三锚总表锚1 行
     （订单级实测%）、§4.3 现势判定表锚1 行（『判未达』字面量在场断言）——
     正文↔正本↔钉桩三方可比。
  ② **判别力自测 +4 条红路**：R18 篡改实测值必红 / R19 翻转判定串必红 /
     R20 篡改 anchors_passing 必红 / R21 报告锚1 行漂移+翻判定必红
     （红路 17→21 条，只加不减；原 R1~R17 与绿路 G1/G2 判定逐条不变）。

【2026-11-06 g10 值钉补登批：snapshot_value_pins 7→26 键——已登记缺口 32→13】
背景（RT-E117/g10-window-verify 外派交卷回溢）：39 条 snapshot 腿中 32 条在独立钉桩
无值钉（gate-registry.json g10_hardaccept.registered_gaps.unpinned_snapshot_legs=32
「已登记缺口、只增不减」；g10-live-snapshot-hardaccept.py leg-4 逐轮点名）。外派
bot 因材料错配（切片只有 af 仓 Cargo/ci 件，无 tools/正本/状态观测）proposal_pins
为空，厂内按运营者令自行补登。口径（本批唯一定义，写死）：**逐腿补登，值须可由
状态面复算——复算不过即跳过留证不猜**；只扩 SNAPSHOT_VALUE_PIN_KEYS 与钉桩，不动
正本任何 value/as_of（正本是本门被验对象，其 refresh 走 --refresh 批，不属本批）。
亲跑复算（本机 + ssh anolis 只读扫描，env-check 前置）：
  · 补登 19 键（7→26）：anchor1 段 14 键（swev 扫描 11-06 亲跑与 10-31 归档件
    逐值一致：terminal=301/solved=87/failed=76/reward_null=138/28.90%、
    instances 108/38/58/50/34、histogram、12 仓、roots、exp1_root=0）；
    anchor3 段 4 键（card_production_today_orders=227 日别扫描 KEY 行 11-06 复跑
    仍 227；portal_seeds_derived_today=209=变更日志 10-31 门户种子行计数；
    sil_rounds_today=115=SIL 日志 10-31 行≤14:35:00 计数；
    sil_today_writeback_events=SIL 日志 10-31 三行回滚/commit）；
    cross_anchor 段 1 键（anchors_defined_in 指针可解：全局纲领 §一=三锚正本）。
  · 跳过 13 键（复算不过，全部留证于 30-工件/g10-pin-backfill-20261106.md）：
    orders_scanned_total/swev_nonterminal_orders/swev_orders_total（11-06 亲跑
    1176→1184/27→28/328→329 实时漂移，登记值系 10-31 点时读数）；
    swev_instance_source_pool（口径文本标签，无状态面源）；
    anchor2_verdict/anchor3_verdict（裁定产物，非机算量）；
    strategies_ci_gate_exit_code（af 仓 CI 全量复跑重负载，本机永禁 cargo）；
    strategies_ci_gate_rules/step_slot（上游文档抄录；唯一可用 af 工作树
    af-wt-d55 在 feature/s17 分支，ci/run.sh 行号 536-537→598+ 已漂移）；
    strategies_worktree（指名工作树 af-wt-sil-writeback 已被 bot 车道回收）；
    loop_ring1_cards_ingested_today（开区间读数，腿自述已增至 16823）；
    loop_ring4_gsil_writeback_commit_evidence（commit 自述+当日实跑的点时文本）；
    sil_counters（部分可复现：triggered=34/candidates_queued=0 精确命中，但
    noop 201≠203、verdicts_queued 3≠7——计数器口径不可精确复现，不猜）。
维护契约履行（三处缺一即红）：①--make-pin 重生成钉桩 ②同步 tools/all-gates.sh
G10_TOOL_SHA256/G10_PIN_SHA256（门本体改了）③计划/变更日志.md 登记钉桩 sha256；
另因 all-gates.sh 改动跑 tools/gate-pins-refresh.sh 重锚（gate-pins.list 行+
外置锚+复验）。判别力自测红路计数不变（21 条只加不减；R18~R20 的断言串随红消息
文案「锚1 判定链快照值被改」→「快照值钉桩值被改」同步——语义不变，仍要求
pin-tamper 红）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(TOOLS_DIR)
TOOL_PATH = os.path.abspath(__file__)
DEFAULT_FILE = os.path.join(WS, "工具状态备份", "numbers-sota-20261031.json")
DEFAULT_AF_REPO = "/home/pan-ding/workspace/af-wt-sil-writeback"
AS_OF_FMT = "%Y-%m-%d %H:%M:%S"
# 独立钉桩（命令集的外部锚）：**在正本之外**的另一个文件——命令与登记值同处
# 一文件=改一行即自证（本次确证洞），钉桩把它钉死。
PIN_FILE = os.path.join(TOOLS_DIR, "numbers-sota-check.pin.json")

# 快照值钉桩键总表。前 7 键为锚1 判定链+exp1/exp2 终裁（2026-11-03 RT-锚1钉值批/
# J5 批）：这 5 个链键决定「锚1 判定是否翻转」——工厂实测（比较式的另一操作数）+
# 参照实测 + 判定串 + 通过数 + G11 输入。它们全是 snapshot 腿（远程 anolis 扫描
# 点时读数/裁定产物，本地无源不可复算），门此前只打印不判红——同文件一致篡改即可
# 无声翻转锚1 结论（本批确证洞）。修法：值随 --make-pin 钉进独立钉桩文件
# snapshot_value_pins 段，验钉桩逐键比对现值。后 19 键为 2026-11-06 g10 值钉补登批
# 按「状态面可复算」逐腿亲跑补登（口径见下方注释与 30-工件/
# g10-pin-backfill-20261106.md）。快照腿不经 --refresh 回写 → 值钉桩不影响合法
# 刷新；快照值只能手改 → 手改必须走重钉桩三步留痕（同改命令集契约）。
SNAPSHOT_VALUE_PIN_KEYS = (
    "anchor1_benchmark_score_band/swev_order_solve_rate_pct",
    "anchor1_benchmark_score_band/swev_decided_subset_solve_rate_pct",
    "anchor1_benchmark_score_band/anchor1_verdict",
    "cross_anchor/anchors_passing",
    "cross_anchor/g11_terminal_judgement_input",
    # 2026-11-03 J5：exp1/exp2 终裁腿转 snapshot（loop-state verdict_log 清零不可复算）
    # ——快照值唯一机检锚在钉桩（同款防值面篡改；SIL 裁决链重通回 live 后随批出钉）
    "anchor3_improvement_loop/loop_ring3_exp1_verdict",
    "anchor3_improvement_loop/loop_ring3_exp2_verdict",
    # 【2026-11-06 g10 值钉补登批】39 条 snapshot 腿中 32 条无值钉（gate-registry
    # registered_gaps.unpinned_snapshot_legs=32 已登记缺口）。本批按「值须可由状态面
    # 复算——复算不过即跳过留证不猜」逐腿亲跑复算后补登 19 键（7+19=26）：
    #   · anchor1 段 14 键：复算源=远程 anolis 只读扫描（swev-solve-scan.py，
    #     env-check 前置后 ssh 亲跑）与 2026-10-31 归档扫描件逐值一致（腿键→扫描件
    #     行号见 30-工件/g10-pin-backfill-20261106.md）；未补登的 4 键
    #     （orders_scanned_total/swev_instance_source_pool/swev_nonterminal_orders/
    #     swev_orders_total）复算不过——前三者为实时漂移（11-06 亲跑 1176→1184、
    #     27→28、328→329，登记值是 10-31 点时读数），其一为口径文本标签无状态面源；
    #   · anchor3 段 4 键：card_production_today_orders=227（日别扫描件 KEY 行，
    #     11-06  ssh 复跑仍 227）、portal_seeds_derived_today=209（变更日志 10-31
    #     门户种子行计数=209）、sil_rounds_today=115（SIL 日志 10-31 行≤14:35:00
    #     =115）、sil_today_writeback_events（SIL 日志 10-31 回滚/commit 三行）；
    #   · cross_anchor 段 1 键：anchors_defined_in 指针可解（全局纲领 §一=三锚正本）。
    # 未补登的 13 键全部留证于同报告（复算不过：实时漂移/裁定产物/af 工作树被回收/
    #     SIL 计数器口径不可精确复现/开区间读数等）。
    "anchor1_benchmark_score_band/swev_attempts_histogram",
    "anchor1_benchmark_score_band/swev_instances_any_pass_rate_pct",
    "anchor1_benchmark_score_band/swev_instances_decided_any_pass_rate_pct",
    "anchor1_benchmark_score_band/swev_instances_distinct",
    "anchor1_benchmark_score_band/swev_instances_first_attempt_rate_pct",
    "anchor1_benchmark_score_band/swev_instances_fully_unjudged",
    "anchor1_benchmark_score_band/swev_order_solve_rate_by_profile",
    "anchor1_benchmark_score_band/swev_orders_failed_reward_false",
    "anchor1_benchmark_score_band/swev_orders_in_exp1_root",
    "anchor1_benchmark_score_band/swev_orders_reward_null",
    "anchor1_benchmark_score_band/swev_orders_solved_reward_true",
    "anchor1_benchmark_score_band/swev_repos_covered",
    "anchor1_benchmark_score_band/swev_scan_roots",
    "anchor1_benchmark_score_band/swev_terminal_orders",
    "anchor3_improvement_loop/loop_ring1_card_production_today_orders",
    "anchor3_improvement_loop/loop_ring1_portal_seeds_derived_today",
    "anchor3_improvement_loop/sil_rounds_today",
    "anchor3_improvement_loop/sil_today_writeback_events",
    "cross_anchor/anchors_defined_in",
)

# ----------------------------------------------------------------- 报告正文对账
# 【2026-11-03 RT-SOTABODY 批】报告正文的**路径钉死在门本体内**——不在正本里
# （正本可被改）、也不由命令行覆盖（在役正本强制用本路径；命令行覆盖只在
# --file 也被覆盖的沙箱件上生效）。换件/换路径即失守。
REPORT_REL = "计划/研究组/对标批-20261031/SOTA对标报告-20261031.md"
REPORT_FILE = os.path.join(WS, "计划", "研究组", "对标批-20261031",
                           "SOTA对标报告-20261031.md")

# 正文 ↔ 正本 值级对账规则表。
# 每条规则 = (规则名, 正则（对报告正文全文 finditer）, [(捕获组序号, 正本 value 键路径), ...])
# 判定：①**所有**匹配都必须与正本登记值相等（任一不等即红）；②**规则未命中**
# （该断言被删/被改写）**同样判红**——「删掉断言」不得成为消音手段。
REPORT_BODY_RULES = [
    ("§〇 总览·锚2 行（条目数+三态）",
     r"现势复算（\d{4}-\d{2}-\d{2}）全库 \*\*(\d+) 条\*\*（compilable (\d+) / "
     r"needs_syntax (\d+) / not_applicable (\d+)）",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (2, "anchor2_pattern_coverage/strategies_compilable"),
      (3, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (4, "anchor2_pattern_coverage/strategies_not_applicable")]),
    ("§2.1 逐条 YAML 复算·条目数",
     r"^entries_on_disk=(\d+)$",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk")]),
    ("§2.1 逐条 YAML 复算·experiment.status 四态",
     r"experiment\.status counts: \{'none': (\d+), 'inconclusive': (\d+), "
     r"'confirmed': (\d+), 'refuted': (\d+)\}",
     [(1, "anchor2_pattern_coverage/strategies_experiment_status_none"),
      (2, "anchor2_pattern_coverage/strategies_experiment_status_inconclusive"),
      (3, "anchor2_pattern_coverage/strategies_experiment_status_confirmed"),
      (4, "anchor2_pattern_coverage/strategies_experiment_status_refuted")]),
    ("附表#5 experiment.status 两态",
     r"experiment\.status counts: \{'none': (\d+), 'inconclusive': (\d+)\}",
     [(1, "anchor2_pattern_coverage/strategies_experiment_status_none"),
      (2, "anchor2_pattern_coverage/strategies_experiment_status_inconclusive")]),
    ("§2.1 逐条 YAML 复算·tier 分布",
     r"tier counts:\s*\{'A': (\d+), 'C': (\d+), 'B': (\d+)\}",
     [(1, "anchor2_pattern_coverage/strategies_tier_counts/value/A"),
      (2, "anchor2_pattern_coverage/strategies_tier_counts/value/C"),
      (3, "anchor2_pattern_coverage/strategies_tier_counts/value/B")]),
    ("§2.1 逐条 YAML 复算·dsl_state 三态",
     r"dsl_state counts:\s*\{'compilable': (\d+), 'needs_syntax': (\d+), "
     r"'not_applicable': (\d+)\}",
     [(1, "anchor2_pattern_coverage/strategies_compilable"),
      (2, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (3, "anchor2_pattern_coverage/strategies_not_applicable")]),
    ("§2.1 对照表·条目总数",
     r"\| 条目总数 \| [^|]*\| \*\*(\d+)\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk")]),
    ("§2.1 对照表·compilable",
     r"\| compilable \| \d+ \| \*\*(\d+)\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_compilable")]),
    ("§2.1 对照表·needs_syntax",
     r"\| needs_syntax \| \d+ \| \*\*(\d+)\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_needs_syntax")]),
    ("§2.1 对照表·not_applicable",
     r"\| not_applicable \| \d+ \| \*\*(\d+)\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_not_applicable")]),
    ("§2.1 对照表·tier C 档",
     r"\| tier \| A11\+B48 \| \*\*A11\+B48\+C(\d+)\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_tier_counts/value/C")]),
    ("§2.1 可编译率表·全库",
     r"\| 全库 (\d+)/(\d+) \| \*\*([\d.]+)%\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_compilable"),
      (2, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (3, "anchor2_pattern_coverage/strategies_compilable_rate_pct_all60")]),
    ("§2.1 可编译率表·G4 A+B 档",
     r"\| G4 A\+B 档 (\d+) 簇内 (\d+)/(\d+) \| \*\*([\d.]+)%\*\* \|",
     [(1, "anchor2_pattern_coverage/strategies_g4_baseline_entries"),
      (2, "anchor2_pattern_coverage/strategies_compilable"),
      (3, "anchor2_pattern_coverage/strategies_g4_baseline_entries"),
      (4, "anchor2_pattern_coverage/strategies_compilable_rate_pct_g4_scope59")]),
    ("§2.3 Phase 4 输入条数",
     r"吃这 (\d+) 条作为「语法边界图」输入",
     [(1, "anchor2_pattern_coverage/strategies_needs_syntax")]),
    ("§2.4 G2.1 缺口簇数",
     r"\| G2\.1 (\d+) 簇不可编译表达 \| needs_syntax=(\d+) \|",
     [(1, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (2, "anchor2_pattern_coverage/strategies_needs_syntax")]),
    ("§3.1 ② 共识筛选·A/B 簇数与 C 档",
     r"\*\*(\d+) 簇\*\*（A11\+B48）；现全库 (\d+) 条（\+C(\d+)）",
     [(1, "anchor2_pattern_coverage/strategies_g4_baseline_entries"),
      (2, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (3, "anchor2_pattern_coverage/strategies_tier_counts/value/C")]),
    ("§3.1 ④ 策略库条目数",
     r"`strategies/` (\d+) 条",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk")]),
    ("§3.2 确证策略数·条目数与状态分布",
     r"全库 (\d+) 条策略条目里，.*?分布是 .?none=(\d+) / inconclusive=(\d+) / "
     r"confirmed=(\d+) / refuted=(\d+)",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (2, "anchor2_pattern_coverage/strategies_experiment_status_none"),
      (3, "anchor2_pattern_coverage/strategies_experiment_status_inconclusive"),
      (4, "anchor2_pattern_coverage/strategies_experiment_status_confirmed"),
      (5, "anchor2_pattern_coverage/strategies_experiment_status_refuted")]),
    ("§4.1 三锚总表·锚2 行",
     r"全库 (\d+) 条：三态 (\d+)/(\d+)/(\d+)；可编译率 ([\d.]+)%（全库）",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (2, "anchor2_pattern_coverage/strategies_compilable"),
      (3, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (4, "anchor2_pattern_coverage/strategies_not_applicable"),
      (5, "anchor2_pattern_coverage/strategies_compilable_rate_pct_all60")]),
    ("§4.2 锚2 建议·三态与缺口簇数",
     r"现全库已是 (\d+) 条（新增 C 档 (\d+) 条），三态为 (\d+)/(\d+)/(\d+)；"
     r"(\d+) 条 needs_syntax",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (2, "anchor2_pattern_coverage/strategies_tier_counts/value/C"),
      (3, "anchor2_pattern_coverage/strategies_compilable"),
      (4, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (5, "anchor2_pattern_coverage/strategies_not_applicable"),
      (6, "anchor2_pattern_coverage/strategies_needs_syntax")]),
    ("§4.2 三句话输入·限定词",
     r"限定：(\d+) 条中 (\d+) 条 needs_syntax / (\d+) 条 not_applicable",
     [(1, "anchor2_pattern_coverage/strategies_entries_on_disk"),
      (2, "anchor2_pattern_coverage/strategies_needs_syntax"),
      (3, "anchor2_pattern_coverage/strategies_not_applicable")]),
    ("§1.2 分数带表·当期任意 agent 上沿",
     r"当期 SOTA 上沿（任意 agent） \| ([\d.]+)%",
     [(1, "anchor1_benchmark_score_band/public_band_top_any_agent_pct")]),
    ("§1.2 分数带表·当期同 harness 上沿",
     r"当期 SOTA 上沿（\*\*同 harness 可比\*\*：bash-only / mini-SWE-agent） \| "
     r"([\d.]+)%",
     [(1, "anchor1_benchmark_score_band/public_band_top_same_harness_pct")]),
    ("§1.2 分数带表·2025 同 harness 带下沿",
     r"\| 2025 同 harness 带 \| ([\d.]+)%",
     [(1, "anchor1_benchmark_score_band/public_band_2025_same_harness_pct")]),
    # 【2026-11-03 RT-锚1钉值批 +3】锚1 判定链的正文行此前零规则——正文独自翻判定
    # 或与正本合谋翻判定都无人能红。判定列以**字面量**进规则（『未达标』『判未达』）：
    # 改写成『达标』即规则未命中=红（删/改断言不得消音，同 ⓪ 口径）。
    ("§〇 总览·锚1 行（实测+同 harness 上沿+判定方向）",
     r"\| 锚1 基准分数带 \| 同一任务集上工厂编译配置 ≥ 公发表同类系统分数带下沿 \| "
     r"工厂 swev \*\*([\d.]+)%\*\*（订单级，87/301，终态单中 [\d.]+% 未判分）；"
     r"公榜当期同 harness 上沿 \*\*([\d.]+)%\*\* \| \*\*未达标\*\*（且口径不可直接比） \|",
     [(1, "anchor1_benchmark_score_band/swev_order_solve_rate_pct"),
      (2, "anchor1_benchmark_score_band/public_band_top_same_harness_pct")]),
    ("§4.1 三锚总表·锚1 行（订单级实测）",
     r"\| \*\*锚1\*\* 基准分数带 \| 订单级 ([\d.]+)%（87/301）；",
     [(1, "anchor1_benchmark_score_band/swev_order_solve_rate_pct")]),
    ("§4.3 现势判定·锚1 行（判未达在场断言）",
     r"\| 锚1 基准分数带 \| \*\*判未达\*\* \| 硬条件「同一任务集上工厂编译配置 "
     r"≥ 公发表同类系统分数带下沿」",
     []),
]

# 结论回指键 ↔ live 腿 一致性规则表。
# 每条 = (规则名, 结论回指键路径, 正则（对该键的 value 串）, 捕获组序号, 对照的 live 腿键路径)
# 两个 verdict 键是 snapshot 腿（本地不可复算），但它们**内嵌的数字**（条目数/
# 缺口簇数/终裁计数）必须与同文件 live 腿一致——否则正本自相矛盾（本次确证洞）。
VERDICT_RULES = [
    ("anchor2_verdict·G4 基线簇数", "anchor2_pattern_coverage/anchor2_verdict",
     r"G4 基线 (\d+) 簇", 1,
     "anchor2_pattern_coverage/strategies_g4_baseline_entries"),
    ("anchor2_verdict·全库条目数", "anchor2_pattern_coverage/anchor2_verdict",
     r"现全库 (\d+) 条", 1,
     "anchor2_pattern_coverage/strategies_entries_on_disk"),
    ("anchor2_verdict·needs_syntax 缺口", "anchor2_pattern_coverage/anchor2_verdict",
     r"(\d+) 簇 needs_syntax", 1,
     "anchor2_pattern_coverage/strategies_needs_syntax"),
    ("anchor2_verdict·not_applicable 缺口", "anchor2_pattern_coverage/anchor2_verdict",
     r"(\d+) 簇 not_applicable", 1,
     "anchor2_pattern_coverage/strategies_not_applicable"),
    ("anchor3_verdict·共识簇数", "anchor3_improvement_loop/anchor3_verdict",
     r"共识 G4 基线 (\d+) 簇", 1,
     "anchor3_improvement_loop/loop_ring2_consensus_clusters"),
    ("anchor3_verdict·全库条目数", "anchor3_improvement_loop/anchor3_verdict",
     r"现全库 (\d+) 条", 1,
     "anchor2_pattern_coverage/strategies_entries_on_disk"),
    ("anchor3_verdict·确证策略数", "anchor3_improvement_loop/anchor3_verdict",
     r"确证策略数 = (\d+)", 1,
     "anchor3_improvement_loop/loop_ring3_confirmed_strategy_count"),
    ("anchor3_verdict·第三环终裁计数", "anchor3_improvement_loop/anchor3_verdict",
     r"inconclusive×(\d+)", 1,
     "anchor2_pattern_coverage/strategies_experiment_status_inconclusive"),
]


# ----------------------------------------------------------------- 工具函数
def strict_value_paths(doc):
    """严格递归枚举「含 value 键的 dict」→ 键路径列表（与 G10 监测口径同源）。"""
    out = []

    def walk(node, prefix):
        if isinstance(node, dict):
            if "value" in node:
                out.append(prefix)
            for k, v in node.items():
                if k == "value":
                    continue
                walk(v, prefix + "/" + k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, prefix + "/" + str(i))

    walk(doc, "")
    return out


def get_by_path(doc, path):
    node = doc
    for seg in path.strip("/").split("/"):
        if isinstance(node, list):
            node = node[int(seg)]
        else:
            node = node[seg]
    return node


def set_by_path(doc, path, value):
    """回写**某个 value 键的值**（不动同层的 unit/note/source 等证据字段）。"""
    segs = path.strip("/").split("/")
    node = doc
    for seg in segs[:-1]:
        node = node[int(seg)] if isinstance(node, list) else node[seg]
    last = segs[-1]
    if isinstance(node, list):
        node = node[int(last)]
    else:
        node = node[last]
    if isinstance(node, dict) and "value" in node:
        node["value"] = value          # value 键：只改值，证据字段原样保留
    else:
        raise TypeError(f"路径 {path} 不是 value 键条目，拒绝回写")


def subst(text, ws, af_repo, self_path=None):
    """占位替换：{WS} / {AF_REPO} / {SELF}。

    {SELF} = 被验正本的绝对路径——让 live 腿的复算命令读**被验的那一份**
    （如差距键＝带上沿−被验正本里的实测值），而不是恒定读默认正本：否则门
    检查副本时算的是别的文件的值。{SELF} 由门在运行时替换，命令串本身仍被
    独立钉桩钉死（改命令串即钉桩失配）。
    """
    s = text.replace("{WS}", ws).replace("{AF_REPO}", af_repo)
    if self_path:
        s = s.replace("{SELF}", self_path)
    return s


def run_recheck(cmd, cwd, ws, af_repo, self_path=None, timeout=120):
    """跑登记的复算命令 → (rc, stdout, stderr)。cwd 支持 {WS}/{AF_REPO}/{SELF} 占位。"""
    real_cmd = subst(cmd, ws, af_repo, self_path)
    real_cwd = subst(cwd, ws, af_repo, self_path) if cwd else ws
    if not os.path.isdir(real_cwd):
        return 127, "", f"复算工作目录不在位：{real_cwd}"
    try:
        p = subprocess.run(real_cmd, shell=True, cwd=real_cwd,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"复算命令超时（{timeout}s）：{real_cmd}"
    return p.returncode, p.stdout, p.stderr


def last_line(out):
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""


def as_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def as_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def cmp_exact(recorded, live_text):
    """exact：登记值 vs 复算输出（末行）。返回 (ok, 说明)。"""
    if isinstance(recorded, bool):
        got = live_text.strip().lower()
        want = "true" if recorded else "false"
        return got == want, f"登记={recorded} 复算={live_text!r}"
    if isinstance(recorded, int):
        got = as_int(live_text)
        if got is None:
            return False, f"登记={recorded} 复算不可机数({live_text!r})"
        return got == recorded, f"登记={recorded} 复算={got}"
    if isinstance(recorded, float):
        got = as_float(live_text)
        if got is None:
            return False, f"登记={recorded} 复算不可机数({live_text!r})"
        return abs(got - recorded) <= 1e-9, f"登记={recorded} 复算={got}"
    # str：逐字符比对（大小写不敏感——十六进制/大小写等价口径），复算取末行
    return live_text == recorded, f"登记={recorded!r} 复算={live_text!r}"


def cmp_gte(recorded, live_text):
    """gte：单调活账——复算值须 >= 登记值（过报=失真即红；欠报=陈旧，时效由 as_of 判）。"""
    if isinstance(recorded, str):          # ISO 时间戳：字典序可比
        return live_text >= recorded, f"登记={recorded} 复算={live_text}"
    got = as_int(live_text)
    if got is None:
        got = as_float(live_text)
    if got is None:
        return False, f"登记={recorded} 复算不可机数({live_text!r})"
    if isinstance(recorded, int) and got != int(got):
        return False, f"登记={recorded} 复算非整数({live_text!r})"
    return got >= recorded, f"登记={recorded} 复算={got}"


def cmp_exact_json(recorded, live_text):
    try:
        got = json.loads(live_text)
    except (TypeError, ValueError) as e:
        return False, f"登记={recorded} 复算非 JSON({live_text!r}, {e})"
    return got == recorded, f"登记={recorded} 复算={got}"


def cmp_exact_list(recorded, live_text):
    got = [x.strip() for x in live_text.split(",") if x.strip() != ""]
    return got == list(recorded), f"登记={list(recorded)} 复算={got}"


CMP = {"exact": cmp_exact, "gte": cmp_gte,
       "exact-json": cmp_exact_json, "exact-list": cmp_exact_list}


# ----------------------------------------------------------------- 报告正文对账
def cmp_registered(expected, got_text):
    """正本登记值（int/float/str）vs 正文/结论串里捕获到的数字串。

    返回 (ok, 说明)。正文里的数字一律按**十进制字面量**比对（不做百分号/单位
    换算——规则表里的键值口径即正本登记值的口径）。
    """
    if isinstance(expected, bool):
        got = got_text.strip().lower()
        return got == ("true" if expected else "false"), \
            f"登记={expected} 捕获={got_text!r}"
    if isinstance(expected, int):
        got = as_int(got_text)
        if got is None:
            return False, f"登记={expected} 捕获不可机数({got_text!r})"
        return got == expected, f"登记={expected} 捕获={got}"
    if isinstance(expected, float):
        got = as_float(got_text)
        if got is None:
            return False, f"登记={expected} 捕获不可机数({got_text!r})"
        return abs(got - expected) <= 1e-9, f"登记={expected} 捕获={got}"
    return str(expected) == got_text, f"登记={expected!r} 捕获={got_text!r}"


def registered_value(doc, path):
    """取正本某个 value 键的登记值；路径也可直指某个 value 键内部的子项
    （如 strategies_tier_counts/value/A）。"""
    node = get_by_path(doc, path)
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def snapshot_value_pins_of(doc):
    """取锚1 判定链快照键的现值（--make-pin / 自测钉桩生成用）。

    任一链键缺失或缺 value → 抛 KeyError——钉桩拒绝在判定链不全的正本上生成
    （缺件不静默）。
    """
    out = {}
    for k in SNAPSHOT_VALUE_PIN_KEYS:
        node = get_by_path(doc, k)
        if not (isinstance(node, dict) and "value" in node):
            raise KeyError(f"锚1 判定链钉值键不在正本内或缺 value：{k}")
        out[k] = node["value"]
    return out


def check_report_body(doc, report_path, rep):
    """报告正文 ↔ 机算正本 值级对账（本次 RT-SOTABODY 批新增能力）。

    判据（不复刻判定、不弱化任何既有断言）：
      · 规则表里的每条规则，正文里**所有**匹配处的数字都必须等于正本对应 value
        键的登记值——任一不等即红（正文漂移）；
      · 规则**未命中**（该断言被删/被改写）同样即红（「删掉断言」不得消音）；
      · 正本 meta.report 指向的报告必须就是本门认领的那一份（换件即失守）。
    返回 (命中规则数, 红数)。
    """
    if not os.path.isfile(report_path):
        rep.red(f"infra：报告正文缺件：{report_path}——正文对账无从做起"
                "（缺件红，不静默放行）")
        return 0, 1
    try:
        with open(report_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        rep.red(f"infra：报告正文不可读：{report_path}（{e}）")
        return 0, 1

    declared = ((doc.get("meta") or {}).get("report") or "").strip()
    rel = os.path.relpath(report_path, WS)
    if declared and os.path.normpath(declared) != os.path.normpath(rel):
        rep.red(f"报告换件：正本 meta.report={declared!r} ≠ 本门认领的报告 "
                f"{rel!r}——正文对账口径被换即失守")

    hit_rules = 0
    reds = 0
    for name, pat, groups in REPORT_BODY_RULES:
        ms = list(re.finditer(pat, text, re.M))
        if not ms:
            rep.red(f"正文↔正本对账：规则未命中（{name}）——该断言被删/被改写，"
                    "正文与正本不再可比（删断言不得消音）")
            reds += 1
            continue
        bad = []
        for m in ms:
            for gi, key in groups:
                try:
                    expected = registered_value(doc, key)
                except (KeyError, IndexError, TypeError):
                    bad.append(f"正本键 {key} 不存在")
                    continue
                ok, detail = cmp_registered(expected, m.group(gi))
                if not ok:
                    bad.append(f"{key}: {detail}")
        if bad:
            for b in bad:
                rep.red(f"正文↔正本漂移（{name}，命中 {len(ms)} 处）：{b}")
                reds += 1
        else:
            hit_rules += 1
            rep.ok(f"正文↔正本  {name}  {len(ms)} 处命中·逐值一致")
    return hit_rules, reds


def check_verdict_backrefs(doc, rep):
    """结论回指键 ↔ 同文件 live 腿 一致性（本次 RT-SOTABODY 批新增能力）。

    `anchor2_verdict`/`anchor3_verdict` 是裁定产物（snapshot 腿、本地不可机算），
    但它们**内嵌的数字**（条目数/缺口簇数/终裁计数）必须与同文件 live 腿登记值
    一致——正本不得自相矛盾（本次确证洞：verdict 自称 59/60 簇、11 簇
    needs_syntax、inconclusive×2，而 live 腿实测 61 条、12 簇、3 条）。
    返回 (命中规则数, 红数)。
    """
    hit_rules = 0
    reds = 0
    for name, key, pat, gi, live_key in VERDICT_RULES:
        try:
            val = get_by_path(doc, key).get("value")
        except (KeyError, IndexError, TypeError):
            rep.red(f"结论回指键↔live 腿：键不存在 {key}")
            reds += 1
            continue
        if not isinstance(val, str):
            rep.red(f"结论回指键↔live 腿：{key} 的 value 不是文本（{val!r}）")
            reds += 1
            continue
        ms = list(re.finditer(pat, val))
        if not ms:
            rep.red(f"结论回指键↔live 腿：规则未命中（{name}，键 {key}）——该键"
                    "被改写/删词，回指与 live 腿不再可比")
            reds += 1
            continue
        try:
            expected = registered_value(doc, live_key)
        except (KeyError, IndexError, TypeError):
            rep.red(f"结论回指键↔live 腿：对照腿 {live_key} 不存在")
            reds += 1
            continue
        bad = []
        for m in ms:
            ok, detail = cmp_registered(expected, m.group(gi))
            if not ok:
                bad.append(f"{key} 内嵌 {m.group(gi)} vs live 腿 {live_key}: {detail}")
        if bad:
            for b in bad:
                rep.red(f"结论回指键↔live 腿矛盾（{name}）：{b}")
                reds += 1
        else:
            hit_rules += 1
            rep.ok(f"结论回指键↔live 腿  {name}  一致（{live_key}={expected!r}）")
    return hit_rules, reds


# ----------------------------------------------------------------- 独立钉桩
# 复算命令与登记值**不得同处一文件**——否则「把 recheck 改成 echo 1、把 value
# 改成 1」即可自证为绿，且 --refresh 会把篡改值写回并重打 as_of（自证闭环）。
# 钉桩是**另一个文件**里的外部锚：命令集/结构的 sha256 与门本体摘要锚在那里。
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    try:
        with open(path, "rb") as fh:
            return sha256_bytes(fh.read())
    except OSError:
        return None


def manifest_of_doc(doc):
    """正本 meta.verification 的「命令集+结构」规范化清单（dict）。

    只收**判定语义**字段：腿路径/类别/口径(case kind)/工作目录/复算命令、分组
    定义（类别/工作目录/复算命令/成员/总数键/活侧键映射）、键数声明、live 腿
    下限、时效上限。
    **不收** value 与 as_of——合法刷新会改这两者（--refresh 回写值 + 重打时点），
    纳入清单会把合法刷新误判成篡改。
    """
    ver = (doc.get("meta") or {}).get("verification") or {}
    legs = ver.get("legs") or {}
    groups = ver.get("groups") or {}
    man = {
        "value_key_count_declared": ver.get("value_key_count_declared"),
        "live_leg_min": ver.get("live_leg_min"),
        "max_age_hours": ver.get("max_age_hours"),
        "legs": {},
        "groups": {},
    }
    for p, lg in legs.items():
        man["legs"][p] = {"class": lg.get("class"), "kind": lg.get("kind"),
                          "cwd": lg.get("cwd"), "recheck": lg.get("recheck"),
                          "tool": lg.get("tool"), "tool_sha256": lg.get("tool_sha256")}
    for g, gd in groups.items():
        man["groups"][g] = {"class": gd.get("class"), "cwd": gd.get("cwd"),
                            "recheck": gd.get("recheck"),
                            "members": sorted(gd.get("members") or []),
                            "total": gd.get("total"),
                            "live_keys": gd.get("live_keys") or {}}
    return man


def manifest_canonical(man):
    """规范化序列化（键序固定、紧凑分隔符）——同一清单必得同一摘要。"""
    return json.dumps(man, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def manifest_digest(man):
    return sha256_bytes(manifest_canonical(man).encode("utf-8"))


def diff_manifest(pinned, cur):
    """逐项对比钉桩清单与现况清单 → 人类可读差异串（点名改了哪条腿的什么）。"""
    out = []
    for k in ("value_key_count_declared", "live_leg_min", "max_age_hours"):
        if pinned.get(k) != cur.get(k):
            out.append(f"{k}: 钉桩={pinned.get(k)!r} 现况={cur.get(k)!r}")
    pl = pinned.get("legs") or {}
    cl = cur.get("legs") or {}
    for p in sorted(set(pl) | set(cl)):
        if p not in cl:
            out.append(f"腿被删：{p}")
        elif p not in pl:
            out.append(f"腿被加：{p}")
        else:
            for f in ("class", "kind", "cwd", "recheck", "tool", "tool_sha256"):
                if pl[p].get(f) != cl[p].get(f):
                    out.append(f"腿 {p} 的 {f}：钉桩={pl[p].get(f)!r} 现况={cl[p].get(f)!r}")
    pg = pinned.get("groups") or {}
    cg = cur.get("groups") or {}
    for g in sorted(set(pg) | set(cg)):
        if g not in cg:
            out.append(f"分组被删：{g}")
        elif g not in pg:
            out.append(f"分组被加：{g}")
        elif pg[g] != cg[g]:
            out.append(f"分组 {g} 定义变更：钉桩={pg[g]!r} 现况={cg[g]!r}")
    return out


def verify_pin(doc, pin_path, tool_path):
    """独立钉桩对账。返回 (status, reds, snapshot_value_pins)。

    status：OK=在位；缺件/坏件=基础设施问题（调用方判 rc=2）；失配=被篡改（rc=1）。
    snapshot_value_pins：钉桩里的锚1 判定链快照值段（dict 或 None）——失配时
    调用方 fail-closed 不执行任何登记命令，故只在 OK 时被消费。
    """
    reds = []
    if not os.path.isfile(pin_path):
        return "缺件", [f"钉桩缺件：{pin_path}——复算命令与登记值同处一文件=改一行即自证；"
                        f"钉桩缺件无外部锚，按红处理（不静默放行）"], None
    try:
        with open(pin_path, encoding="utf-8") as fh:
            pin = json.load(fh)
    except (OSError, ValueError) as e:
        return "坏件", [f"钉桩坏件：{pin_path} 解析失败（{e}）——命令集无外部锚，按红处理"], None
    if not isinstance(pin, dict):
        return "坏件", [f"钉桩坏件：{pin_path} 不是对象——命令集无外部锚，按红处理"], None

    # ① 门本体摘要（改门本体须同步改钉桩；改门且删自检时由 all-gates 摘要常量抓）
    tsha = sha256_file(tool_path)
    pin_sha = (pin.get("tool") or {}).get("sha256")
    if not tsha:
        reds.append(f"钉桩红：门本体不可读（{tool_path}）——无法对账")
    elif pin_sha != tsha:
        reds.append(f"钉桩红：门本体摘要不符（钉桩={str(pin_sha)[:12]}… 实算={tsha[:12]}…）"
                    f"——门本体被改未同步钉桩（判定逻辑被改过）")

    # ② 正本命令集/结构摘要
    pm = pin.get("manifest")
    if not isinstance(pm, dict):
        reds.append("钉桩红：钉桩文件缺 manifest（命令集无外部锚）")
    else:
        pin_d = manifest_digest(pm)
        sub_d = ((pin.get("subject") or {}).get("manifest_sha256"))
        if sub_d and sub_d != pin_d:
            reds.append("钉桩红：钉桩自身不自洽（subject.manifest_sha256 与 manifest 不符）"
                        "——钉桩文件被改过")
        cur = manifest_of_doc(doc)
        if manifest_digest(cur) != pin_d:
            diffs = diff_manifest(pm, cur)
            reds.append("钉桩红：正本命令集/结构与独立钉桩不一致——「复算命令与登记值同处"
                        "一文件、改一行即自证」的形态被钉桩挡住；差异："
                        + ("；".join(diffs[:6]) + ("…" if len(diffs) > 6 else ""))
                        + "｜合法改动命令集后的重钉桩流程（**三处缺一即红**）："
                          "①python3 -I tools/numbers-sota-check.py --make-pin > "
                          "tools/numbers-sota-check.pin.json "
                          "②同步 tools/all-gates.sh 的 G10_TOOL_SHA256/G10_PIN_SHA256 "
                          "③在 计划/变更日志.md 登记 tools/numbers-sota-check.pin.json "
                          "sha256=<64位hex>")
    if reds:
        return "失配", reds, None

    # ③ 锚1 判定链快照值钉桩（2026-11-03 RT-锚1钉值批）：这 5 键是 snapshot 腿
    #    （本地无源不可复算，门只打印不判红），却是「锚1 判定是否翻转」的判据链
    #    ——同文件一致篡改实测/判定串/回指键即可无声翻转（本批确证洞）。修法：
    #    值随 --make-pin 钉进本钉桩文件，逐键比对正本现值，任一不等即红（fail-
    #    closed，不执行任何登记复算命令）。快照腿不经 --refresh 回写 → 不影响
    #    合法刷新；快照值只能手改 → 手改须走重钉桩三步（同改命令集契约）。
    svp = pin.get("snapshot_value_pins")
    if not isinstance(svp, dict) or not svp:
        return "失配", reds + [
            "钉桩红：钉桩缺 snapshot_value_pins 段（锚1 判定链快照值无外部锚——"
            "同文件一致篡改实测/判定/回指键的翻转形态无人能红）。重钉桩流程"
            "（**三处缺一即红**）：①python3 -I tools/numbers-sota-check.py "
            "--make-pin > tools/numbers-sota-check.pin.json ②同步 "
            "tools/all-gates.sh 的 G10_TOOL_SHA256/G10_PIN_SHA256 ③在 "
            "计划/变更日志.md 登记 tools/numbers-sota-check.pin.json sha256"], None
    missing = [k for k in SNAPSHOT_VALUE_PIN_KEYS if k not in svp]
    extra = [k for k in svp if k not in SNAPSHOT_VALUE_PIN_KEYS]
    if missing:
        reds.append(f"钉桩红：snapshot_value_pins 缺链键 {missing}——判定链钉不全")
    if extra:
        reds.append(f"钉桩红：snapshot_value_pins 含非链键 {extra}——钉桩面被扩改")
    for k in SNAPSHOT_VALUE_PIN_KEYS:
        if k not in svp:
            continue
        try:
            cur = get_by_path(doc, k).get("value")
        except (KeyError, IndexError, TypeError):
            cur = "<键不存在>"
        if cur != svp[k]:
            reds.append(f"钉桩红：快照值钉桩值被改：{k}  钉={svp[k]!r} "
                        f"正本现值={cur!r}——快照腿本地不可复算，唯一值锚在钉桩"
                        "（合法重测后的重钉桩流程同上三步）")
    if reds:
        return "失配", reds, None
    return "OK", [], svp


# ----------------------------------------------------------------- 主流程
class Report:
    def __init__(self):
        self.reds = []          # 红项清单（方法名 red 不可与属性同名）
        self.pass_n = 0
        self.snap_n = 0
        self.notes = []

    def red(self, msg):
        self.reds.append(msg)
        print(f"RED  {msg}")

    def ok(self, msg):
        self.pass_n += 1
        print(f"OK   {msg}")

    def note(self, msg):
        self.notes.append(msg)
        print(f"NOTE {msg}")


def check_file(path, ws, af_repo, max_age_hours, quiet=False, pin_path=None,
               report_path=None):
    """值级对账。返回 (rc, report)。rc: 0=过 1=红 2=infra。"""
    rep = Report()
    if not os.path.isfile(path):
        print(f"RED  infra：正本缺件：{path}")
        return 2, rep
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"RED  infra：正本解析失败：{path}（{e}）")
        return 2, rep

    ver = (doc.get("meta") or {}).get("verification")
    if not isinstance(ver, dict) or not isinstance(ver.get("legs"), dict):
        print("RED  infra：正本缺 meta.verification.legs（该正本未被本门认领——"
              "缺件红，不静默放行）")
        return 2, rep

    # ⓪ 独立钉桩对账（2026-11-03 RT 批）：复算命令与登记值**不得同处一文件**。
    # 钉桩是另一个文件里的外部锚；失配 → 硬红且**不执行**任何登记复算命令
    # （fail-closed：被篡改的命令集不得被执行，更不得被 --refresh 写回）。
    pin_path = pin_path or PIN_FILE
    pin_status, pin_reds, pin_svp = verify_pin(doc, pin_path, TOOL_PATH)
    if pin_status != "OK":
        for m in pin_reds:
            rep.red(m)
        print(f"SUMMARY 钉桩={pin_status} RED={len(rep.reds)}"
              f"（钉桩失配：未执行任何登记复算命令，未做任何写入）")
        return (2 if pin_status in ("缺件", "坏件") else 1), rep
    tsha = sha256_file(TOOL_PATH) or "?"
    print(f"PIN   命令集钉桩在位：正本 manifest_sha256="
          f"{manifest_digest(manifest_of_doc(doc))[:12]}… 门本体 sha256={tsha[:12]}… "
          f"快照值钉桩={len(SNAPSHOT_VALUE_PIN_KEYS)} 键在位")
    for k in SNAPSHOT_VALUE_PIN_KEYS:
        rep.ok(f"快照钉值  {k}  钉={pin_svp[k]!r} ≡ 正本现值"
               "（快照值钉桩：同文件一致篡改即红）")

    legs = ver["legs"]
    groups = ver.get("groups") or {}
    declared = ver.get("value_key_count_declared")
    live_min = ver.get("live_leg_min", 0)

    # ① 键数不变量（口径自洽项）
    paths = [p.lstrip("/") for p in strict_value_paths(doc)]
    if declared is None:
        rep.red("meta.verification.value_key_count_declared 缺失（键数不变量无锚点）")
    elif len(paths) != declared:
        rep.red(f"value 键数漂移：登记={declared} 实算={len(paths)}"
                f"（严格递归「含 value 键的 dict」计数）")

    # ② 全部 value 键必须被 legs 分类（未分类=盲区）
    classified = set(legs.keys())
    for g in groups.values():
        classified.update(g.get("members") or [])
        if g.get("total"):
            classified.add(g["total"])
    unclassified = [p for p in paths if p not in classified]
    if unclassified:
        rep.red(f"未分类 value 键 {len(unclassified)} 条（盲区，明示即红）："
                + ", ".join(unclassified[:8]) + (" …" if len(unclassified) > 8 else ""))
    for p in sorted(classified):
        if p not in paths:
            rep.red(f"legs 登记的键不在正本内（删键消音）：{p}")

    # ③ live 腿数下限（堵「降级成 snapshot 消音」）
    live_legs = [p for p, lg in legs.items() if lg.get("class") == "live"]
    live_groups = [g for g, gd in groups.items() if gd.get("class") == "live"]
    live_leg_n = len(live_legs) + len(live_groups)
    if live_leg_n < live_min:
        rep.red(f"live 腿数 {live_leg_n} < 下限 {live_min}"
                f"（把腿降级成 snapshot 会消音——下限是护栏）")

    # ④ snapshot 腿必须带 as_of + 理由
    for p, lg in legs.items():
        if lg.get("class") == "snapshot":
            if not lg.get("as_of") or not (lg.get("reason") or "").strip():
                rep.red(f"snapshot 腿缺 as_of/不可复算理由：{p}")
            else:
                rep.snap_n += 1
                if not quiet:
                    v = get_by_path(doc, p).get("value")
                    hint = f"  复算路径={lg['recheck_hint']}" if lg.get("recheck_hint") else ""
                    print(f"SNAP {p}  登记={v!r}  as_of={lg['as_of']}"
                          f"  不可复算理由={lg['reason']}{hint}")

    # ⑤ live 腿值级复算
    now = datetime.datetime.now()
    for p in sorted(live_legs):
        lg = legs[p]
        kind = lg.get("kind")
        cmd = lg.get("recheck")
        if kind not in CMP:
            rep.red(f"live 腿 {p} 的 kind 非法：{kind!r}")
            continue
        if not cmd:
            rep.red(f"live 腿 {p} 缺可执行复算命令（recheck）")
            continue
        # ⑤0 复算源本体摘要对账（2026-11-03 RT 批新增）：live 腿登记的复算
        #     脚本（tool）必须与登记的 tool_sha256 逐字相符——否则「把复算
        #     脚本改成吐一个假值」即可让该腿自证为绿（脚本被改 → 摘要不符
        #     → 红，且**不执行**被改的脚本）。tool_sha256 登记在正本里，正本
        #     的清单被独立钉桩钉死 → 「改脚本 + 改摘要」需同时动钉桩。
        tool_rel = lg.get("tool")
        if tool_rel:
            want_sha = lg.get("tool_sha256")
            tpath = (tool_rel if os.path.isabs(tool_rel)
                     else os.path.join(ws, tool_rel))
            actual_sha = sha256_file(tpath)
            if not want_sha:
                rep.red(f"live 腿 {p} 登记了复算源 {tool_rel} 但缺 tool_sha256"
                        "（复算源无摘要锚＝改脚本即自证）")
                continue
            if not actual_sha:
                rep.red(f"live 腿 {p} 的复算源不可读：{tpath}")
                continue
            if actual_sha != want_sha:
                rep.red(f"复算源摘要不符：live 腿 {p} 的 {tool_rel}"
                        f"（登记={want_sha[:12]}… 实算={actual_sha[:12]}…）"
                        "——复算源被改（改脚本让它吐假值＝自证），拒绝复算")
                continue
        # ⑤a 时效失真：as_of 过期未复核即红
        as_of = lg.get("as_of")
        if not as_of:
            rep.red(f"live 腿 {p} 缺 as_of（活账无时点=时效失真不可判）")
            continue
        try:
            ts = datetime.datetime.strptime(as_of, AS_OF_FMT)
        except ValueError:
            rep.red(f"live 腿 {p} 的 as_of 不可解析：{as_of!r}")
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        if age_h > max_age_hours:
            rep.red(f"时效失真：live 腿 {p} 的登记值 as_of={as_of}"
                    f"（龄 {age_h:.1f}h > 上限 {max_age_hours}h，活账未复核）")
            continue
        rc, out, err = run_recheck(cmd, lg.get("cwd"), ws, af_repo, self_path=path)
        if rc != 0:
            rep.red(f"复算失败：{p}（rc={rc} cmd={cmd} err={err.strip()[:200]}）")
            continue
        ok, detail = CMP[kind](get_by_path(doc, p).get("value"), last_line(out))
        if ok:
            rep.ok(f"live  {p}  {detail}  [{kind}]  as_of={as_of} 龄 {age_h:.1f}h")
        else:
            rep.red(f"值漂移：{p}  {detail}  [{kind}]  复算命令={cmd}")

    # ⑥ 分组腿（分区账自洽）
    for gname, g in sorted(groups.items()):
        if g.get("class") != "live":
            continue
        members = g.get("members") or []
        total_path = g.get("total")
        cmd = g.get("recheck")
        as_of = g.get("as_of")
        if not members or not total_path or not cmd:
            rep.red(f"分组腿 {gname} 定义不全（members/total/recheck）")
            continue
        try:
            ts = datetime.datetime.strptime(as_of, AS_OF_FMT)
        except (TypeError, ValueError):
            rep.red(f"分组腿 {gname} 的 as_of 缺失或不可解析：{as_of!r}")
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        if age_h > max_age_hours:
            rep.red(f"时效失真：分组腿 {gname} as_of={as_of}（龄 {age_h:.1f}h > {max_age_hours}h）")
            continue
        rc, out, err = run_recheck(cmd, g.get("cwd"), ws, af_repo, self_path=path)
        if rc != 0:
            rep.red(f"分组腿 {gname} 复算失败（rc={rc} cmd={cmd} err={err.strip()[:200]}）")
            continue
        try:
            live = json.loads(last_line(out))
        except (TypeError, ValueError) as e:
            rep.red(f"分组腿 {gname} 复算输出非 JSON：{last_line(out)!r}（{e}）")
            continue
        live_keys = g.get("live_keys") or {}
        rec = {m: get_by_path(doc, m).get("value") for m in members}
        rec_total = get_by_path(doc, total_path).get("value")
        live_total = live.get("total")
        bad = []
        # 登记侧分区自洽
        if sum(rec.values()) != rec_total:
            bad.append(f"登记侧分区不自洽：三态和={sum(rec.values())} "
                       f"登记总数({total_path})={rec_total}")
        # 活侧分区自洽
        if sum(live.get(live_keys.get(m, m.rsplit("/", 1)[-1]), 0)
               for m in members) != live_total:
            bad.append(f"活侧分区不自洽：三态和="
                       f"{sum(live.get(m, 0) for m in members)} 活总数={live_total}")
        # 总量单调（卡库被重建/清空 → 红）
        if live_total < rec_total:
            bad.append(f"总量倒退：登记({total_path})={rec_total} 活={live_total}"
                       f"（卡库被重建/清空）")
        # 过报（登记分项 > 活总数）
        for m in members:
            if rec[m] > live_total:
                bad.append(f"过报：登记 {m}={rec[m]} > 活总数={live_total}")
        # 活分项相对登记分项
        reclass = []
        for m in members:
            lv = live.get(live_keys.get(m, m.rsplit("/", 1)[-1]))  # 活侧键名映射
            if lv is None:
                bad.append(f"活侧缺分项 {m}")
                continue
            if lv < rec[m]:
                # 分项下降 = SIL 重分类（candidate→verified/rejected 是常态，总量不变）——
                # 不是失真：登记侧分区自洽（登记三态和 == 登记总数）已挡住「改任一分项」，
                # 「卡库被重建/清空」由「活总数 < 登记总数」判红。故此处只提示不判红。
                reclass.append(f"{m}: 登记={rec[m]} 活={lv}（分项下降=SIL 重分类，"
                               f"登记值按点时口径保留，不判红）")
        if bad:
            for b in bad:
                rep.red(f"分组腿 {gname}：{b}")
        else:
            rep.ok(f"group {gname}  分区自洽 登记总={rec_total} 活总={live_total} "
                   f"as_of={as_of} 龄 {age_h:.1f}h")
            for r in reclass:
                rep.note(f"分组腿 {gname} RECLASSIFIED {r}")

    # ⑦ 报告正文 ↔ 机算正本 值级对账（2026-11-03 RT-SOTABODY 批新增）
    #    报告路径钉死在门本体内（沙箱件才可覆盖）——正文数字与正本登记值不一致
    #    即红；规则未命中（断言被删改）同样即红。
    report_path = report_path or REPORT_FILE
    if not os.path.isfile(report_path):
        # 报告缺件＝基础设施问题（与正本缺件同口径）：rc=2，缺件红、不静默放行。
        print(f"RED  infra：报告正文缺件：{report_path}——正文对账无从做起"
              "（缺件红，不静默放行）")
        return 2, rep
    body_rules, body_reds = check_report_body(doc, report_path, rep)

    # ⑧ 结论回指键 ↔ 同文件 live 腿 一致性（2026-11-03 RT-SOTABODY 批新增）
    #    anchor2_verdict/anchor3_verdict 是裁定产物（snapshot 腿），但其内嵌的
    #    条目数/缺口簇数/终裁计数必须与 live 腿一致——正本不得自相矛盾。
    verdict_rules, verdict_reds = check_verdict_backrefs(doc, rep)

    print(f"SUMMARY live腿={len(live_legs)} 分组腿={len(live_groups)} "
          f"snapshot腿={rep.snap_n} 键数={len(paths)}/{declared} "
          f"正文对账规则={body_rules} 结论回指规则={verdict_rules} "
          f"时效上限={max_age_hours}h 钉桩={pin_status} PASS={rep.pass_n} RED={len(rep.reds)}")
    return (1 if rep.reds else 0), rep


def do_refresh(path, ws, af_repo, max_age_hours, pin_path=None):
    """复核 live 腿并回写登记值 + as_of（留改前 .bak；只写 live 腿，不动 snapshot 腿）。

    钉桩失配 → **拒绝回写**（rc=1/2，零写入）：回写=把（可能被篡改的）复算结果
    写回正本并重打 as_of，令「刚复核过」的表象与篡改值自洽——自证闭环的最后一步。
    """
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    pin_path = pin_path or PIN_FILE
    pin_status, pin_reds, _pin_svp = verify_pin(doc, pin_path, TOOL_PATH)
    if pin_status != "OK":
        for m in pin_reds:
            print(f"RED  {m}")
        print("RED  钉桩失配，拒绝回写（回写会把篡改值写回正本并重打 as_of=自证闭环）")
        return 2 if pin_status in ("缺件", "坏件") else 1
    ver = (doc.get("meta") or {}).get("verification")
    if not isinstance(ver, dict) or not isinstance(ver.get("legs"), dict):
        print("RED  infra：正本缺 meta.verification.legs，拒绝回写")
        return 2
    legs = ver["legs"]
    groups = ver.get("groups") or {}
    now = datetime.datetime.now().strftime(AS_OF_FMT)
    changed = []

    for p in sorted(p for p, lg in legs.items() if lg.get("class") == "live"):
        lg = legs[p]
        kind = lg.get("kind")
        cmd = lg.get("recheck")
        if kind not in CMP or not cmd:
            print(f"RED  live 腿 {p} 定义不全，跳过")
            return 2
        rc, out, err = run_recheck(cmd, lg.get("cwd"), ws, af_repo, self_path=path)
        if rc != 0:
            print(f"RED  复算失败 {p}（rc={rc} {err.strip()[:200]}），拒绝回写")
            return 2
        old = get_by_path(doc, p).get("value")
        if kind == "exact":
            _, detail = cmp_exact(old, last_line(out))
            new = old
            if isinstance(old, bool):        # bool 须先于 int 判（Python bool is int）
                new = last_line(out).strip().lower() == "true"
            elif isinstance(old, int):
                new = as_int(last_line(out))
            elif isinstance(old, float):
                new = as_float(last_line(out))
            else:
                new = last_line(out)
        elif kind == "exact-json":
            new = json.loads(last_line(out))
        elif kind == "exact-list":
            new = [x.strip() for x in last_line(out).split(",") if x.strip()]
        else:  # gte：回写当前活读数（登记值只会向前，不回退）
            if isinstance(old, str):
                new = last_line(out)
            else:
                new = as_int(last_line(out))
                if new is None:
                    new = as_float(last_line(out))
        if new is None:
            print(f"RED  复算结果不可用 {p}：{last_line(out)!r}，拒绝回写")
            return 2
        if new != old:
            set_by_path(doc, p, new)
            changed.append(f"{p}: {old!r} → {new!r}")
        lg["as_of"] = now

    for gname, g in sorted(groups.items()):
        if g.get("class") != "live":
            continue
        rc, out, err = run_recheck(g.get("recheck"), g.get("cwd"), ws, af_repo,
                                   self_path=path)
        if rc != 0:
            print(f"RED  分组腿 {gname} 复算失败（rc={rc}），拒绝回写")
            return 2
        live = json.loads(last_line(out))
        for m in (g.get("members") or []):
            old = get_by_path(doc, m).get("value")
            new = live.get((g.get("live_keys") or {}).get(m, m.rsplit("/", 1)[-1]))
            if new is None:
                print(f"RED  分组腿 {gname} 活侧缺分项 {m}，拒绝回写")
                return 2
            if new != old:
                set_by_path(doc, m, new)
                changed.append(f"{m}: {old!r} → {new!r}")
        tpath = g.get("total")
        old_t = get_by_path(doc, tpath).get("value")
        if live.get("total") != old_t:
            set_by_path(doc, tpath, live.get("total"))
            changed.append(f"{tpath}: {old_t!r} → {live.get('total')!r}")
        g["as_of"] = now

    ver["last_refresh"] = now
    bak = f"{path}.{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-pre-refresh.bak"
    shutil.copy2(path, bak)
    tmp = path + ".tmp-refresh"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(f"REFRESH as_of={now} 改前存照={bak}")
    print(f"REFRESH 变更 {len(changed)} 处：")
    for c in changed:
        print(f"  - {c}")
    if not changed:
        print("  （登记值与现势一致，无值变更）")
    return 0


# ----------------------------------------------------------------- 判别力自测
def selftest(path, ws, af_repo, max_age_hours, pin_path=None):
    """负向自测：证明本门**能**测出值失真（红路必须红）+ 绿路必须绿。

    红路用例（任一未红即自测失败——即门失去判别力）：
      R1 结构腿改值（strategies_entries_on_disk 61→60）必须红；
      R2 分区腿改值（KB 三态之一 +1）必须红（登记侧分区不自洽）；
      R3 单调腿过报（kb_registry_total 抬到 9e9）必须红；
      R4 删键（抽掉一个 live 腿的 value 键）必须红（删键消音 + 键数漂移）；
      R5 全量降级（把所有 live 腿改成 snapshot）必须红（live 腿数下限）；
      R6 未分类（抽掉一个 snapshot 腿的登记）必须红（盲区）；
      R7 **改复算命令自证**（把一条 live 腿的 recheck 改成 `echo 1` 且改其 value，
         用**在役真钉桩**跑）必须红——本次确证的核心洞：复算命令与登记值同处一
         文件=改一行即自证（先前 6 条红路用例只改 value/删键/改 class，**从不改
         legs.recheck**，即「判别力自证」恰好绕开该洞）；
      R8 **坏钉桩**（钉桩文件自身的 manifest 被改）必须红；
      R9 **钉桩缺件**必须红（rc=2，缺件红、不静默放行）；
      R10 **改门本体**（判定逻辑被改的门本体副本 → 门本体摘要失配）必须红。
      R11 **篡改带值**（anchor1 段 public_band_* 腿改值）必须红——分数带这半边
          原先是 snapshot（本地不可复算，篡改后门仍绿＝零值级机检）；本批把
          5 个带值 + 2 个差距键登记为 live 腿（复算源＝本地证据件行表），故
          改值必红（用**在役真钉桩**跑：manifest 未变 → 钉桩仍匹配 → 走到带腿
          复算 → 值漂移即红）。
      R12 **篡改差距键**（gap_vs_top_same_harness_pp 47.9→0.1）必须红。
      R13 **篡改复算源摘要**（live 腿登记的 tool_sha256 被改）必须红（钉桩失配）。
      R14 **报告正文数字漂移必红**（2026-11-03 RT-SOTABODY 批：正文写 60 条而
          正本 live 腿登记 61 条 → 正文↔正本对账必须红——修前无此能力）。
      R15 **删掉正文里的断言必红**（规则未命中＝「删断言」不得成为消音手段）。
      R16 **结论回指键与 live 腿矛盾必红**（anchor2_verdict 写 11 簇而 live 腿
          登记 12 → 矛盾即红）。
      R17 **报告缺件必红**（rc=2，缺件红、不静默放行）。
      R18 **篡改锚1 实测值必红**（swev_order_solve_rate_pct 28.9→70.0——快照腿
          本地无源不可复算，唯一值锚=钉桩 snapshot_value_pins，2026-11-03
          RT-锚1钉值批新增）。
      R19 **翻转锚1 判定串必红**（anchor1_verdict 未达标→达标——同上）。
      R20 **篡改 anchors_passing 必红**（1→3——同上）。
      R21 **报告锚1 行漂移+翻判定必红**（§〇 行 28.90%→70.00% 且 未达标→达标：
          前者正文↔正本漂移红、后者规则未命中红——正文独自翻判定不再是哑弹）。
    绿路对照：
      G1 原件必须绿（本正本现况下）；
      G2 改一个 snapshot 腿的值必须**仍绿但被点名**（snapshot 无本地复算源，
          不可判红——此为明示盲区，不得当成绿了事：输出必须逐条列出 snapshot 腿；
          注意 G2 改的 orders_scanned_total **不在**快照值钉桩键集内（2026-11-06
          值钉补登批因其实时漂移复算不过而未补登；链键已被 R18~R20 证明改值即红）。

    钉桩口径：R1~R6/G2 用**沙箱内为该副本重生成的配套钉桩**（保持原用例的
    值级语义不变——它们测的是值级判别力）；钉桩维度由 R7/R8/R9/R10/R13 独测；
    R11/R12（带值/差距键篡改）用**在役真钉桩**跑（manifest 未变 → 钉桩仍匹配
    → 走到带腿复算 → 值漂移即红）；R14~R17（正文漂移/删断言/回指矛盾/报告缺件）
    同样用**在役真钉桩** + **沙箱报告副本**（--file 已覆盖 → --report 可覆盖；
    在役正本的报告路径钉死不可覆盖）；R18~R21（锚1 判定链快照值/正文锚1 行）
    用**在役真钉桩**——快照值不在 manifest 内（钉桩 manifest 仍匹配），红来自
    snapshot_value_pins 逐键比对/正文规则，正是本批新增判别力。
    在役真钉桩（--pin 默认值）在沙箱内**只读**，永不被改写。
    """
    tmpdir = tempfile.mkdtemp(prefix="numbers-sota-selftest-")
    cases = []
    tool_sha = sha256_file(os.path.abspath(__file__))
    pin_path = pin_path or PIN_FILE

    def make_pin(pname, doc):
        """为某份正本生成配套钉桩（**仅沙箱自测用**）。在役钉桩的更新须同时改
        tools/all-gates.sh 的摘要常量 + 计划/变更日志.md 的登记串（三处缺一即红）。"""
        man = manifest_of_doc(doc)
        pin = {
            "pin_format": 1,
            "pinned_at": datetime.datetime.now().strftime(AS_OF_FMT),
            "tool": {"path": os.path.relpath(os.path.abspath(__file__), WS),
                     "sha256": tool_sha},
            "subject": {"path": os.path.relpath(os.path.abspath(path), WS),
                        "manifest_sha256": manifest_digest(man)},
            "manifest": man,
            "snapshot_value_pins": snapshot_value_pins_of(doc),
        }
        p = os.path.join(tmpdir, f"{pname}.pin.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(pin, fh, ensure_ascii=False, indent=1)
        return p

    def write_case(name, mutate, pin_mode="auto"):
        """写一份沙箱正本副本 + 其钉桩。

        pin_mode：auto=按副本重生成配套钉桩（值级用例保持原语义）；
                  real=用**在役真钉桩**（钉桩维度用例：改命令集必须红）；
                  bad=钉桩自身被改；missing=钉桩缺件。
        """
        p = os.path.join(tmpdir, f"{name}.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if mutate:
            mutate(doc)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        if pin_mode == "real":
            case_pin = pin_path
        elif pin_mode == "missing":
            case_pin = os.path.join(tmpdir, "no-such-pin.json")
        elif pin_mode == "bad":
            case_pin = make_pin(name, doc)
            with open(case_pin, encoding="utf-8") as fh:
                bad = json.load(fh)
            for _p, _lg in sorted((bad.get("manifest") or {}).get("legs", {}).items()):
                if _lg.get("class") == "live":      # 钉桩自身被改成恒真命令
                    _lg["recheck"] = "echo 1"
                    break
            with open(case_pin, "w", encoding="utf-8") as fh:
                json.dump(bad, fh, ensure_ascii=False, indent=1)
        else:
            case_pin = make_pin(name, doc)
        cases.append((name, p))
        return p, case_pin

    def run(p, case_pin, report=None):
        cmd = [sys.executable, "-I", os.path.abspath(__file__), "--file", p,
               "--pin", case_pin, "--af-repo", af_repo,
               "--max-age-hours", str(max_age_hours)]
        if report:
            cmd += ["--report", report]
        pr = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=600)
        return pr.returncode, pr.stdout + pr.stderr

    failures = []

    def expect(name, p, want_rc, must_mention=None, case_pin=None, report=None):
        rc, out = run(p, case_pin, report=report)
        ok = (rc == want_rc)
        if ok and must_mention:
            ok = must_mention in out
        print(f"{'PASS' if ok else 'FAIL'}  {name}: rc={rc} (期望 {want_rc})"
              f"{'' if not must_mention else ' 提及=' + must_mention}")
        if not ok:
            failures.append(f"{name}: rc={rc} 期望 {want_rc} "
                            f"提及={must_mention}\n--- 输出尾部 ---\n"
                            + "\n".join(out.splitlines()[-25:]))
        return out

    # 绿路对照
    expect("G1 原件绿路", path, 0, None, pin_path)

    # R1 结构腿改值
    p, cp = write_case("R1", lambda d: set_by_path(
        d, "anchor2_pattern_coverage/strategies_entries_on_disk", 60))
    expect("R1 结构腿改值必红", p, 1, "strategies_entries_on_disk", cp)

    # R2 分区腿改值（登记侧分区不自洽）
    def bump_kb(d):
        v = get_by_path(d, "anchor3_improvement_loop/kb_registry_verified")["value"]
        set_by_path(d, "anchor3_improvement_loop/kb_registry_verified", v + 1)
    p, cp = write_case("R2", bump_kb)
    expect("R2 分区腿改值必红", p, 1, "kb_registry", cp)

    # R3 单调腿过报
    p, cp = write_case("R3", lambda d: set_by_path(
        d, "anchor3_improvement_loop/kb_registry_total", 9000000000))
    expect("R3 单调腿过报必红", p, 1, "kb_registry_total", cp)

    # R4 删键
    def drop_key(d):
        node = d["anchor2_pattern_coverage"]
        node.pop("strategies_compilable")
    p, cp = write_case("R4", drop_key)
    expect("R4 删键必红", p, 1, None, cp)

    # R5 全量降级成 snapshot
    def downgrade_all(d):
        for lg in d["meta"]["verification"]["legs"].values():
            lg["class"] = "snapshot"
    p, cp = write_case("R5", downgrade_all)
    expect("R5 全量降级必红", p, 1, None, cp)

    # R6 未分类
    def unclassify(d):
        legs = d["meta"]["verification"]["legs"]
        legs.pop("cross_anchor/anchors_passing")
    p, cp = write_case("R6", unclassify)
    expect("R6 未分类必红", p, 1, None, cp)

    # R7 改复算命令自证必红（**在役真钉桩**）——本次确证的核心洞：
    # 把一条 live 腿的 recheck 改成 `echo 1`、把它的 value 改成 1：
    # 修前该门自证为绿（rc=0），修后必被钉桩抓住（命令集摘要不符）。
    def tamper_cmd(d):
        lg = d["meta"]["verification"]["legs"][
            "anchor3_improvement_loop/loop_ring3_confirmed_strategy_count"]
        lg["recheck"] = "echo 1"
        set_by_path(d, "anchor3_improvement_loop/loop_ring3_confirmed_strategy_count", 1)
    p, cp = write_case("R7", tamper_cmd, pin_mode="real")
    expect("R7 改复算命令自证必红（钉桩对账）", p, 1, "钉桩", cp)

    # R8 坏钉桩必红（钉桩文件自身被改）
    p, cp = write_case("R8", None, pin_mode="bad")
    expect("R8 坏钉桩必红", p, 1, "钉桩", cp)

    # R9 钉桩缺件必红（缺件红、不静默放行）
    p, cp = write_case("R9", None, pin_mode="missing")
    expect("R9 钉桩缺件必红（缺件不静默放行）", p, 2, "钉桩", cp)

    # R10 改门本体必红：把门本体副本的判定逻辑改成恒真（削弱判别力）→
    #     门本体摘要与钉桩不符 → 红。（改门且删掉本自检时，由 tools/all-gates.sh
    #     的摘要常量对账抓住——那是门本体之外的第三锚。）
    tampered = os.path.join(tmpdir, "numbers-sota-check-tampered.py")
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        src = fh.read()
    # 注入点用「拆开写的字面量」——否则本行自身的字面量也会被 replace 命中，
    # 把源码改成坏语法（实测过：replace 全文命中 → SyntaxError → 假红）。
    marker = "def cmp_exact(recorded, live_text)" + ":"
    tampered_src = src.replace(marker,
                               marker + "\n    return True, 'TAMPERED-恒真'", 1)
    if tampered_src == src:
        print("FAIL  R10 改门本体必红（门本体摘要失配）：篡改注入失败（源码形态已变）")
        failures.append("R10：门本体篡改注入失败（源码形态已变）")
    else:
        with open(tampered, "w", encoding="utf-8") as fh:
            fh.write(tampered_src)
        pr = subprocess.run(
            [sys.executable, "-I", tampered, "--file", path, "--pin", pin_path,
             "--af-repo", af_repo, "--max-age-hours", str(max_age_hours)],
            capture_output=True, text=True, timeout=600)
        out = pr.stdout + pr.stderr
        ok = (pr.returncode == 1) and ("门本体" in out)
        print(f"{'PASS' if ok else 'FAIL'}  R10 改门本体必红（门本体摘要失配）: "
              f"rc={pr.returncode} (期望 1) 提及=门本体")
        if not ok:
            failures.append(f"R10 改门本体必红: rc={pr.returncode} 期望 1 提及=门本体\n"
                            "--- 输出尾部 ---\n" + "\n".join(out.splitlines()[-25:]))

    # G2 改 snapshot 腿的值 → 仍绿但必须点名（明示盲区）
    def bump_snapshot(d):
        v = get_by_path(d, "anchor1_benchmark_score_band/orders_scanned_total")["value"]
        set_by_path(d, "anchor1_benchmark_score_band/orders_scanned_total", v + 1)
    p, cp = write_case("G2", bump_snapshot)
    out = expect("G2 snapshot 腿改值仍绿但点名", p, 0, "orders_scanned_total", cp)

    # R11 篡改带值必红（分数带这半边不再是无机检的 snapshot）
    def tamper_band(d):
        set_by_path(d, "anchor1_benchmark_score_band/public_band_2025_same_harness_pct",
                   20.00)
    p, cp = write_case("R11", tamper_band, pin_mode="real")
    expect("R11 篡改带值必红（带腿已是 live 机检腿）", p, 1,
           "public_band_2025_same_harness_pct", cp)

    # R12 篡改差距键必红
    def tamper_gap(d):
        set_by_path(d, "anchor1_benchmark_score_band/gap_vs_top_same_harness_pp", 0.1)
    p, cp = write_case("R12", tamper_gap, pin_mode="real")
    expect("R12 篡改差距键必红", p, 1, "gap_vs_top_same_harness_pp", cp)

    # R13 篡改 live 腿登记的复算源摘要必红（钉桩失配）
    def tamper_tool_sha(d):
        legs = d["meta"]["verification"]["legs"]
        for _p, lg in sorted(legs.items()):
            if lg.get("class") == "live" and lg.get("tool_sha256"):
                lg["tool_sha256"] = "0" * 64
                break
    p, cp = write_case("R13", tamper_tool_sha, pin_mode="real")
    expect("R13 篡改复算源摘要必红（钉桩失配）", p, 1, "钉桩", cp)

    # ---- 2026-11-03 RT-SOTABODY 批：报告正文对账 + 结论回指键一致性的判别力
    # R14 **报告正文数字漂移必红**（本次确证洞的正面复现：正文写 60 条而正本
    #     live 腿登记 61 条 → 正文↔正本对账必须红）。
    #     做法：把**沙箱报告副本**里的「全库 **61 条**」改回「全库 **60 条**」
    #     （= 修前正文的样子），配沙箱正本（manifest 未变 → 在役钉桩仍匹配）跑。
    stale_report = os.path.join(tmpdir, "R14-report.md")
    with open(REPORT_FILE, encoding="utf-8") as fh:
        rtext = fh.read()
    stale_text = rtext.replace("全库 **61 条**（compilable 32 / needs_syntax 12 "
                                "/ not_applicable 17）",
                                "全库 **60 条**（compilable 32 / needs_syntax 11 "
                                "/ not_applicable 17）")
    stale_text = stale_text.replace("| 全库 32/61 | **52.46%** |",
                                    "| 全库 32/60 | **53.33%** |")
    with open(stale_report, "w", encoding="utf-8") as fh:
        fh.write(stale_text)
    p, cp = write_case("R14", None, pin_mode="real")
    expect("R14 报告正文数字漂移必红（正文↔正本对账）", p, 1, "正文↔正本", cp,
           report=stale_report)

    # R15 **删掉正文里的断言**必须红（规则未命中＝删断言不得消音）
    gutted_report = os.path.join(tmpdir, "R15-report.md")
    gutted_text = rtext.replace("| G2.1 12 簇不可编译表达 | needs_syntax=12 |",
                                "| G2.1 缺口簇数见附录 |  —  |")
    with open(gutted_report, "w", encoding="utf-8") as fh:
        fh.write(gutted_text)
    p, cp = write_case("R15", None, pin_mode="real")
    expect("R15 报告正文断言被删必红（规则未命中）", p, 1, "规则未命中", cp,
           report=gutted_report)

    # R16 **结论回指键与 live 腿矛盾必红**（把 anchor2_verdict 改回修前那句
    #     「11 簇 needs_syntax」，而 live 腿登记 12 → 矛盾即红）
    def stale_verdict(d):
        set_by_path(d, "anchor2_pattern_coverage/anchor2_verdict",
                    "形式达标（59/60 簇逐条三态 + CI 门在位今日复跑全绿），"
                    "但表达能力有缺口：11 簇 needs_syntax、17 簇 not_applicable")
    p, cp = write_case("R16", stale_verdict, pin_mode="real")
    expect("R16 结论回指键与 live 腿矛盾必红", p, 1, "结论回指键", cp)

    # R17 **报告缺件必红**（rc=2，缺件红、不静默放行）
    p, cp = write_case("R17", None, pin_mode="real")
    expect("R17 报告缺件必红（缺件不静默放行）", p, 2, "报告正文缺件", cp,
           report=os.path.join(tmpdir, "no-such-report.md"))

    # ---- 2026-11-03 RT-锚1钉值批：锚1 判定链快照值钉桩 + 正文锚1 行的判别力 ----
    # R18 **篡改锚1 实测值必红**（本批确证洞的正面复现第一步：28.9→70.0——
    #     snapshot 腿本地无源不可复算，唯一值锚=在役真钉桩 snapshot_value_pins）。
    def tamper_anchor1_measured(d):
        set_by_path(d, "anchor1_benchmark_score_band/swev_order_solve_rate_pct",
                    70.0)
    p, cp = write_case("R18", tamper_anchor1_measured, pin_mode="real")
    expect("R18 篡改锚1 实测值必红（快照值钉桩）", p, 1, "快照值钉桩值被改", cp)

    # R19 **翻转锚1 判定串必红**（未达标→达标——同文件一致篡改的结论翻转键）。
    def tamper_anchor1_verdict(d):
        set_by_path(d, "anchor1_benchmark_score_band/anchor1_verdict",
                    "达标（不可直接比；实测 70.00% 为下界）")
    p, cp = write_case("R19", tamper_anchor1_verdict, pin_mode="real")
    expect("R19 翻转锚1 判定串必红（快照值钉桩）", p, 1, "快照值钉桩值被改", cp)

    # R20 **篡改 anchors_passing 必红**（1→3——回指汇总键）。
    def tamper_anchors_passing(d):
        set_by_path(d, "cross_anchor/anchors_passing", 3)
    p, cp = write_case("R20", tamper_anchors_passing, pin_mode="real")
    expect("R20 篡改 anchors_passing 必红（快照值钉桩）", p, 1,
           "快照值钉桩值被改", cp)

    # R21 **报告锚1 行漂移+翻判定必红**（§〇 行 28.90%→70.00% → 正文↔正本漂移红；
    #     未达标→达标 → 判定列字面量规则未命中红——正文独自翻判定不再是哑弹）。
    flipped_report = os.path.join(tmpdir, "R21-report.md")
    flipped_text = rtext.replace(
        "工厂 swev **28.90%**（订单级，87/301，终态单中 45.85% 未判分）",
        "工厂 swev **70.00%**（订单级，87/301，终态单中 45.85% 未判分）", 1)
    flipped_text = flipped_text.replace(
        "| **未达标**（且口径不可直接比） |",
        "| **达标**（且口径不可直接比） |", 1)
    with open(flipped_report, "w", encoding="utf-8") as fh:
        fh.write(flipped_text)
    p, cp = write_case("R21", None, pin_mode="real")
    expect("R21 报告锚1 行漂移+翻判定必红（正文↔正本）", p, 1, "正文↔正本", cp,
           report=flipped_report)

    shutil.rmtree(tmpdir, ignore_errors=True)
    if failures:
        print(f"SELFTEST FAIL：{len(failures)} 条用例未达预期")
        for f in failures:
            print("----")
            print(f)
        return 1
    print(f"SELFTEST PASS：{len(cases) + 2} 例（红路 21 条必红 + 绿路 2 条对照）——"
          f"本门**能**测出值失真（非真空门）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="G10 机算正本值级对账门")
    ap.add_argument("--file", default=DEFAULT_FILE, help="正本路径")
    ap.add_argument("--af-repo", default=DEFAULT_AF_REPO, help="af 仓工作树根")
    ap.add_argument("--max-age-hours", type=float, default=168.0,
                    help="live 腿登记值时效上限（小时），默认 168（7 天）")
    ap.add_argument("--pin", default=PIN_FILE,
                    help="独立钉桩文件路径（命令集的外部锚；缺件/失配即红）")
    ap.add_argument("--refresh", action="store_true",
                    help="复核 live 腿并回写登记值 + as_of（留改前 .bak）")
    ap.add_argument("--selftest", action="store_true", help="判别力负向自测")
    ap.add_argument("--make-pin", action="store_true",
                    help="打印当前正本的配套钉桩 JSON（stdout，不写任何文件）；"
                         "更新在役钉桩须同时改 tools/all-gates.sh 摘要常量与"
                         "计划/变更日志.md 登记串（三处缺一即红）")
    ap.add_argument("--report", default=None,
                    help="报告正文路径（**仅沙箱自测可用**：只有在役正本被 --file "
                         "一并覆盖时才生效；在役正本强制用钉死路径 "
                         + REPORT_REL + "）")
    args = ap.parse_args()

    # 报告路径的钉死规则（2026-11-03 RT-SOTABODY 批）：
    #   · 在役正本（--file 为默认件）→ 报告路径**不可覆盖**（钉死在门本体内），
    #     覆盖即红——否则「换一份报告」就能让正文对账面变成真空门；
    #   · 沙箱正本（--file 已被覆盖）→ 允许 --report 覆盖（判别力自测用）。
    report_path = REPORT_FILE
    if args.report:
        want = os.path.abspath(args.report)
        if os.path.abspath(args.file) == os.path.abspath(DEFAULT_FILE):
            print(f"RED  在役正本的报告路径不可覆盖（钉死路径={REPORT_REL}）——"
                  f"换件即失守（--report 仅在 --file 一并覆盖的沙箱件上可用）")
            return 1
        report_path = want

    if args.make_pin:
        with open(args.file, encoding="utf-8") as fh:
            doc = json.load(fh)
        man = manifest_of_doc(doc)
        pin = {
            "pin_format": 1,
            "pinned_at": datetime.datetime.now().strftime(AS_OF_FMT),
            "note": ("G10 值级对账门独立钉桩：正本 meta.verification 的命令集/结构锚"
                     "+快照值钉桩（snapshot_value_pins：锚1 判定链 7 键〔2026-11-03〕"
                     "+2026-11-06 值钉补登批按状态面可复算补登 19 键，共 26 键——快照"
                     "腿本地无源不可复算，其值唯一机检锚在此）。复算命令与登记值不得"
                     "同处一文件——改一行即自证的形态由此钉死；同文件一致篡改锚1 实测/"
                     "判定串/回指键或任何已钉快照值的翻转形态亦由此钉死。维护契约"
                     "（三处缺一即红）：改命令集或任何快照值钉桩键的值 → ①重新生成"
                     "本钉桩 ②同步 tools/all-gates.sh 的摘要常量 ③在 计划/变更日志.md "
                     "登记本文件 sha256。"),
            "tool": {"path": os.path.relpath(TOOL_PATH, WS),
                     "sha256": sha256_file(TOOL_PATH)},
            "subject": {"path": os.path.relpath(os.path.abspath(args.file), WS),
                        "manifest_sha256": manifest_digest(man)},
            "manifest": man,
            "snapshot_value_pins": snapshot_value_pins_of(doc),
        }
        print(json.dumps(pin, ensure_ascii=False, indent=1))
        return 0
    if args.selftest:
        return selftest(args.file, WS, args.af_repo, args.max_age_hours,
                        pin_path=args.pin)
    if args.refresh:
        return do_refresh(args.file, WS, args.af_repo, args.max_age_hours,
                          pin_path=args.pin)
    rc, _rep = check_file(args.file, WS, args.af_repo, args.max_age_hours,
                          pin_path=args.pin, report_path=report_path)
    return rc


if __name__ == "__main__":
    sys.exit(main())
