#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账本面对账门（账本面九腿：RT-E76 / RT-E101 / RT-E92 / RT-E29 / RT-E27〔首批五腿〕
＋ RT-E109 / RT-E110 / RT-E111〔2026-11-05 波次B·B1 批新增三腿〕
＋ D-148〔2026-11-09 wave-17 批新增一腿：三本账三向逐行 diff 常驻腿〕）。

【D-148 批（2026-11-09 wave-17）新增一腿摘要——为什么加】
  台账 D-148（factory-os#257 · 逃逸台账-20261108 ESC-08①）：Q20 三本账（正本/仓本/
  规划环）非严格逐行一致——实例差虽经裁15/裁21 手术＋重考一次性三向机核闭合，但常驻
  机制腿未落：八腿判据均不含「三副本严格逐行一致」，三本间内容漂移在门绿下不可见。
  leg-D148 ＝ 三本实读 sha256＋两两逐行 diff＋逐 hunk 机器归因（设计内投影入白名单；
  滞后形态归因 D-123 不并吞；其余一切 hunk ⇒ 红）。

【B1 批（2026-11-05）新增三腿摘要——为什么加】
  RT-E109（台账:14 ← 逃逸台账:883）：台账行态与实盘**零对账**——「未开始」无验证命令
      绑定、行态编辑无实盘核对义务、下游判定引用失实行态无断言。leg-E109 ＝ 行态验证
      命令绑定（逐条实跑登记面在册的绑定命令并与行内登记读数对账）＋下游引用对账。
  RT-E110（台账:71 ← 逃逸台账:898）：G5 勘正未横扫同族行；E76 腿只断「台账 ✅ 行 ↔
      映射判定」一个方向。leg-E110 ＝ 横扫对账的**最后一段**：反向对齐 + 同格矛盾
      （✅ 行状态列内不得含自认未达措辞）＋下游汇总引用（G11「G1-G10 全绿」须带否定标记）。
  RT-E111/119（台账:72,75 ← 逃逸台账:905/970）：G5「清零」判定域只读一本账 ⇒ 实债在
      别本账里隐身（台账可博弈处）。leg-E111 ＝ G5 清零断言**多源化**（台账＋逃逸台账
      未竟行＋技术债登记＋剩余欠账总表；逃逸源口径同源复用迁移对账门）。

为什么建本门（账本面八笔债的共同根因；原文见 30-工件/剩余欠账总表-20261104/
剩余欠账总表.md §3-1/§3-2/§3-4，台账行号见 计划/阶段欠账台账.md）：账本面自己的
「声称」长期**无机器复算面**——

  RT-E76（台账:42 ← 逃逸台账:619）
      系统目标台账的 ✅ 行与 目的-监测项映射 的判定列**两面无同步义务**：台账标 ✅
      而映射判「未达」的假绿面可长期存活（逃逸台账 E43 拦截机制②＝「台账 ✅ 行与
      映射判定列自动对账」；红队亲跑 grep -rln 系统目标台账 tools/*.py tools/*.sh = 0
      ⇒ 对账门无处可对）。本门 leg-E76 = 台账 ✅ 行 ↔ 映射 §二 判定列逐行对账。

  RT-E101（台账:68 ← 逃逸台账:834）
      销项行内的**耐久断言**（「alarms.log 零新增」）在事件发生后无人有义务回查；同格
      回填编辑不核对全行既有断言（逃逸台账：模式⑮+⑤；机制①②③＝断言机器化 / 事件
      驱动勘正 / 回填编辑纪律）。本门 leg-E101 = alarms.log 事件 ↔ 台账 OBS-D4 销项行
      断言的逐事件复算对账。

  RT-E92（台账:88 ← 逃逸台账:770）
      方法论 §8 M-2 锚可指向**非空但内容错**的行而机检全绿放行（RT-E93 坐标 bug +
      「未核(无声称)」按存在性计入 PASS ⇒ 零内容核验 ⇒ 该锚永不可能转红）。本门
      leg-E92 = 期望串核验面在册生效 + M-2 锚坐标/核验状态对账 + 未核锚计数零增长。

  RT-E29（逃逸台账:253）
      关键定性证据建立在 `stat %w`（birth）这类**易失属性**上，编辑器 temp+rename 一次
      就重置 ⇒ 证据链单点、不可复验；无快照固化机制核。本门 leg-E29 = birth 快照
      append-only 链固化 + 文书登记面在册 + 「登记值与现值矛盾时强制勘误登记」。

  RT-E27（逃逸台账:239）
      判据文件自称「判据先行」而 birth 晚于全部施工，且全工作区**无任何文书登记**；
      对照名单完整性无检查（选择性列举不可见）。本门 leg-E27 = 判据时序登记在册 +
      判据全集 vs 登记覆盖（缺一即红）。

【本门的两种判据口径（严格腿 vs 登记腿）——口径本身不得被误读】
  · **严格腿**：判据为「该面此刻即须自洽」。任何不自洽 ⇒ 红（rt=1），不接受登记豁免。
    腿：RT-E76 / RT-E101 / RT-E27。理由：这三笔的债是「新不一致无人拦」，一旦允许
    登记豁免，登记面本身就成了新的免检通道。
  · **登记腿**：判据为「**未登记**的缺口即红；已登记的缺口可见且被点名」。腿：RT-E92 /
    RT-E29。理由：这两笔的**缺口本体就是该笔债**（RT-E92＝M-2 锚漂移且零内容核验；
    RT-E29＝birth 证据锚灭失），且该缺口已在上游台账/逃逸台账**逐条登记**；本门不可能
    靠改判据件清偿（判据件的静态分母只增不减，见 leg-E92 注），故本门改为：把已知缺口
    固化成**机读登记面**（gate-registry.json），并对「未登记的新缺口」与「已登记缺口
    的形状变化」开红。登记缺口在每次运行中逐条打印（附上游登记出处），**不得读作已消**。

判据（单一源，本文档化）：
  leg-E76【严格】系统目标台账 ✅ 行 ↔ 映射 §二 判定列
    · 台账状态列首个符号 ∈ {✅,❌,🔄}（❌/🔄 不判）。
    · ✅ 行必须在 映射 §二（章节标题含「系统目标台账」且含「G-SIL」）有同 目的ID 行
      （缺 ⇒ 红：台账 ✅ 无判定可对）。
    · 该行判定列（末列）归一化后必须以「达标」开头（否则 ⇒ 红：✅ 与映射判定不一致
      ＝假绿面）。
    · 台账 ✅ 行数必须 ≡ 映射 §二 判定「达标」行数（台账漏标 ✅ ⇒ 红）。
  leg-E101【严格】台账 OBS-D4 销项行耐久断言复算对账
    · (a) 耐久断言（行内含「零新增」等）必须同行带时点限定标记（时点断言 / 不构成
      耐久承诺）⇒ 否则红（RT-E101 原始形态复发）。
    · (b) 行内登记的「alarms.log N 条、末条 <ts>」必须可复算：alarms.log 中
      code=af-execline-idle 且 ts ≤ 末条 的条数必须 == N ⇒ 否则红（登记值与现值矛盾）。
    · (c) 逐事件覆盖：af-execline-idle 事件按行文口径分两类——
        ① 分支覆盖类：报文含行内「起转入「X」」声明的签名 X；
        ② 须逐条登记类：其余报文（例：生产真值根不可达＝判不准即报警）。
      ②类事件必须被行内「第 N 条」逐条登记（N ∈ 行内登记序号集）⇒ 否则红（点名
      ordinal+ts+报文）；①类事件须 ordinal ≤ 行内快照覆盖数（登记的 N）或 ≥ 分支声明
      起点 ordinal，否则红。
  leg-E92【登记】方法论 §8 M-2 锚内容级核验
    · (a)【严格】§7 人工抽查清单须有该映射文件的期望串条目，且 anchor-check --table
      对该条目判 OK（期望串核验面真在生效）⇒ 否则红。
    · (b)【登记】M-2 行所引坐标须 == 登记面的 m2_expected_coord；不等 ⇒ 缺口
      「E92-G1:M2锚坐标=<coord>」⇒ 该缺口未登记 ⇒ 红。
    · (c)【登记】anchor-check 全量跑中该锚判「未核」⇒ 缺口「E92-G2:M2锚零内容核验」
      ⇒ 未登记 ⇒ 红。
    · (d)【严格】未核锚计数（未核(无声称)+未核(散文元语言)）必须 ≤ 登记基线 ⇒ 新增
      未核锚即红（「未核=0」门缺席下的零增长补偿；只增不减）。
    · 注：判据件（criteria.yaml G9-3）的静态分母 123 = 85 全路径 + 38 短式，且
      「本值只增不减、删锚→下调」——把 §8 M-2 的坐标回填到现位会使锚总数 123→122
      （全路径 85→84）⇒ 直接触发 g93-denom-recon.py 的②总数对账/拆解① 红。**故本
      门不改判据件、不改方法论文档**：坐标纠偏面落在本门登记面（机读），缺口按登记腿
      处置（见证据文 §二 RT-E92 落点与 §四 沙箱读数）。
  leg-E29【登记】birth 快照固化
    · 快照面 = 30-工件/账本面对账门批-20261105/birth-snapshot.jsonl（append-only，
      每行带 prev_sha256 链）。
    · (a)【严格】链完整：逐行重算 prev 哈希链，任一行被改/删/重排 ⇒ 红。
    · (b)【严格】覆盖：登记清单（gate-registry.json 的 birth_files）每件至少一行快照；
      路径须实存 ⇒ 否则红。
    · (c)【严格】快照记录 birth ≠ 盘面现 birth 时，必须有**更晚**的同路径快照行带
      birth_reset=true + 非空理由 ⇒ 否则红（禁静默）。
    · (d)【登记】文书登记面在册：每件判据件必须在「判据件全文 + 逃逸台账 + 阶段欠账
      台账」语料中存在一行，同行含该件名标识与一个 birth 值 ⇒ 否则红（登记面缺失）。
    · (e)【登记】语料引用的 birth 值 ≠ 快照记录值 ⇒ 缺口「E29-G1:birth登记矛盾:<路径>」
      ⇒ 该缺口未登记 ⇒ 红。
  leg-E27【严格】判据时序登记完整性
    · 判据全集 = 计划/研究组/OBS回头批-20261031/*判据*.md（排除 .bak）。
    · (a) 时序登记在册：每件判据件必须在「判据件全文 + 阶段欠账台账」语料中存在一行，
      该行同时含该件名标识、一个 birth 值与一个时序判定词（早于/晚于/事后补写/事后
      追认/重置/不成立/判据先行）⇒ 否则红（判据时序无文书登记＝RT-E27 原始形态）。
    · (b) 全集覆盖：有效时序登记的判据件数必须 == 判据全集件数 ⇒ 否则红
      （ls *判据*.md 全集 vs 登记覆盖 diff，缺一即红）。
    · (c)【B1 加严】自称「判据先行」的件必须有时序自洽证据：自带时序更正/预注册状态
      声明，或语料有一行把它判为「早于」⇒ 否则红（自称与盘面脱节＝RT-E27 原始形态）。
  leg-E109【严格】台账行态验证命令绑定 ＋ 下游引用对账
    · 绑定面（登记面 row_state_bindings）逐条：①行内状态列必须带该机读校验命令；
      ②实跑命令得实跑读数；③行内登记读数 ⟷ 实跑读数对账——**假绿方向判红**
      （行内称绿而实跑为红）；台账**保守方向**（行内称红而实跑为绿）只报勘正建议。
      ④机制②：下游引用面声明的被引行态必须 == 台账当前状态词（删除线段内历史状态
      不算当前声明）⇒ 否则红（下游判定建立在失实行态上）。
  leg-E110【严格】系统目标台账横扫对账的最后一段
    · ①反向对齐：台账 ❌/🔄 行在映射 §二 不得判「达标」（两面打架且无人拦）。
    · ②同格矛盾：台账 ✅ 行的状态列内不得含自认未达措辞（矛盾证据同格在场而门不红）。
    · ③下游汇总引用：汇总行（G11）「G1-G10 全绿」类引用必须带否定/勘误标记，否则红
      （汇总面冻结于成文时点、被引行变化不传播）。
  leg-E111【严格】G5「清零留证」验收断言的多源化
    · ①各源在位且可解析（缺件 ⇒ 不可证 fail-closed）；②逐源枚举未清零项并打印；
      ③G5 状态列声称已清零（✅）而任一源仍有未清零项 ⇒ 红（假绿面）；
      ④逃逸源口径同源复用 tools/test-ledger-migration-recon.py；
      ⑤G5 验收门格若声明多源而与源清单不一致 ⇒ 红（半声明＝假多源化）；若完全未
      声明多源 ⇒ 记为已登记缺口 E111-G1（登记腿：绿但逐次打印并给出清偿路径）。
  leg-D148【严格·白名单投影】三本账三向逐行 diff 常驻腿（ESC-08① / 台账 D-148）
    · 三本 ＝ 正本 A=计划/阶段欠账台账.md；仓本 B=repos/factory-os/账本/阶段欠账台账.md；
      规划环实读 C=ledger-sync 克隆 账本/阶段欠账台账.md（路径解析序：AF_LEDGER_SYNC_CLONE
      env 覆盖 → 工作区内 ledger-sync-clone/（沙箱位）→ 生产位 ~/ledger-sync/factory-os-clone；
      缺任一本 ⇒ 不可证 fail-closed 不猜绿）。三本实读 sha256/行数入读数面。
    · 两两（A↔C / A↔B / B↔C）逐行 diff，逐 hunk 机器归因；**非白名单且非滞后形态的
      hunk>0 ⇒ 红**（逐 hunk 点名：书对/行号/首格 id/首异摘录/归因失败原因）。
    · W1 白名单＝设计内投影（当前一员：D-114 P-04 脱敏——`[内网地址P-04已脱敏]` 标记
      与对侧同序内网地址字面（CGNAT 100.64.0.0/10＋10.0.0.0/8）**一一可逆替换后相等**；
      标记数≠地址数、或替换后不等〔地址↔异地址〕⇒ 非白名单 ⇒ 红）。白名单扩张须
      判官批 PR（先例 PR #121/#156 形制），施工不得自扩。
    · W2 滞后形态 ⇒ **不判红**、响亮归因 D-123（卡 factory-os#135 承载仓本滞后腿，本腿
      不并吞；逐 hunk 点名＋滞后锚数读数，**不得读作已消**）：
      (a) 尾行滞后——领先本文件末尾的连续锚行（| 起头）在滞后本整行缺失（A 参与的书对
          只认 B/C 作滞后侧；B↔C 双向皆可＝本地检出 currency）；
      (b) 行尾 append 滞后——同首格 id 行，滞后本整行（去尾 `|`/空白）为领先本行的
          前缀（append-only 合法演化「翻状态格＋行尾 append」的在途形态；可与 W1 投影
          复合同行）。
    · 其余一切 hunk（中段行内联改写／中段整锚行增删／行序漂移／非尾插入／状态格分叉／
      领先方向违例〔B、C 多出 A 无的内容〕）⇒ 红。
    · 边界（如实登记）：滞后形态判据是 D-123 域的**窄门**（只放行「尾行缺失」与「行尾
      前缀 append」两形）；状态格分叉（同 id 行中段内容不同）不在窄门内 ⇒ 红——同步
      在途窗（*/20 cadence）造成的瞬时红属如实红；断腿型持续红归 ESC-09/D-142 域。

模式：
  （无参）      对真盘面判账。exit 0=绿；1=红（逐腿逐条点名）；2=不可证（缺件/坏件/
                环境错，fail-closed 不猜绿）。
  --selftest   内嵌夹具自测（零网络、零真盘面写入；只在临时目录造副本）：九腿各造
                「改动该面 ⇒ 判据红」负例（现 24 例，含 D-148 批 6 例＝4 负例＋白名单
                投影/滞后形态正控 2 例）＋「未改动 ⇒ 绿」对照，全过 exit 0。
                ★ 沙箱基线归一（B1 批）：alarms.log 的「台账尚未补登」ordinal 在沙箱台账行
                  上补登（模拟「台账已补登」）⇒ 对照组不被事件驱动的台账补登义务污染
                  （真盘面 leg-E101 的红见证据文 §五；该腿负例仍由夹具自造）。
                ★ 三本账沙箱合成（D-148 批）：仓本 B/规划环 C **不复制真件**（真 C 每
                  20 分钟随 ledger-sync 漂移，对照须确定性），由沙箱正本 A 派生——C＝P-04
                  全量投影（白名单夹具实装于对照），B＝C 再退两步（撤尾两锚行＋撤一行
                  行尾 append；滞后形态夹具实装于对照）；两形态对照绿、负例各自咬人。
  --ws <root>  指定工作区根（沙箱负控用；缺省=本脚本上级目录）。
  --leg <名>   只跑指定腿（可重复；名＝腿名如 RT-E76 / D-148——三向 diff 注入差异负例
                的独立 rc 读数用；缺省＝全腿，全腿行为与既有版一致只增一腿）。
  --snapshot   把登记清单内各件的 birth/mtime/ino/sha256 追加进快照面（append-only，
                只追加，不改历史行）。
  --write-registry  写 gate-registry.json（登记清单 + 未核基线 + 已登记缺口）。

本门只读：真盘面上除 --snapshot/--write-registry 指定的两个新增件外零写入；不改任何
台账/日志/方法论文档/判据件/既有门件。

边界（如实登记，见证据文 §五）：
  · leg-E101 的「同格编辑时刻」用**文件 mtime**代理（行级编辑时刻不可得）：台账在
    某事件之后被无关编辑 ⇒ 该事件视为已覆盖（已知盲区）。
  · leg-E101(c) 的分支覆盖签名 X 从行文「起转入「X」」抽取；X 变更即判据变更。
  · leg-E92(d) 的未核基线随 anchor-check 口径漂移，基线写死在登记清单里、只增不减
    （升基线须人工改登记清单并留痕）。
  · 登记腿的「已登记缺口」只覆盖**已登记形状**；缺口形状一变（坐标漂到别处、未核
    计数上涨、新件未登记）即红。登记 ≠ 已消。
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEF_WS = Path(__file__).resolve().parents[1]

P_TARGET = "计划/系统目标台账.md"
P_MAPPING = "计划/研究组/红队终局轮-20261101/目的-监测项映射.md"
P_LEDGER = "计划/阶段欠账台账.md"
P_ESCAPE = "计划/研究组/红队终局轮-20261101/逃逸问题台账.md"
P_DOC = "计划/方法论-持续改进-20261031.md"
P_ANCHOR_DIR = "计划/研究组/方法论批-20261031"
P_ANCHOR = P_ANCHOR_DIR + "/anchor-check.py"
P_ALARMS = "状态观测/alarms.log"
P_OBSDIR = "计划/研究组/OBS回头批-20261031"
P_EVID = "30-工件/账本面对账门批-20261105"
P_SNAPSHOT = P_EVID + "/birth-snapshot.jsonl"
P_REGISTRY = P_EVID + "/gate-registry.json"
# --- B1 批（2026-11-05 账本面清偿批）新增面 ---
P_TECH_DEBT = "计划/技术债登记.md"            # RT-E111 三源之一：技术债登记
P_TOTAL_TABLE = "30-工件/剩余欠账总表-20261104/剩余欠账总表.md"  # RT-E111 三源之一：总表
P_MIGRECON = "tools/test-ledger-migration-recon.py"  # RT-E111 逃逸源口径（同源复用）
P_WRITEBACK = "tools/writeback-check.py"       # RT-E109 行态验证命令（writeback 门）
# --- D-148 批（2026-11-09 wave-17）新增面：三本账三向逐行 diff ---
P_REPO_LEDGER = "repos/factory-os/账本/阶段欠账台账.md"        # 仓本 B（gov 检出树）
P_PLANC_SB_LEDGER = "ledger-sync-clone/账本/阶段欠账台账.md"   # 规划环 C：ws 内沙箱位
DEF_PLANC_CLONE = Path("/home/pan-ding/ledger-sync/factory-os-clone")  # C：生产位克隆
P04_MARK = "[内网地址P-04已脱敏]"   # D-114 P-04 机械脱敏标记（ledger-sync.sh SCRUB 同源）
MARK_RE = re.compile(re.escape(P04_MARK))
INTADDR_RE = re.compile(r"(?<![0-9.])(?:100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])"
                        r"\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![0-9.])")
# ↑ CGNAT 100.64.0.0/10（100.64–100.127）＋10.0.0.0/8——四段完整 IPv4 字面

GENESIS = "0" * 64
GID_RE = re.compile(r"^G(?:\d{1,2}|-SIL)$")
SEQ_WORDS = ("早于", "晚于", "事后补写", "事后追认", "重置", "不成立", "判据先行")
BIRTHVAL_RE = re.compile(r"(?:\d{4}-\d{2}-\d{2}[ T])?(\d{2}:\d{2}:\d{2})(?:\.\d+)?")
BIRTH_WINDOW = 160          # 件名之后多少字符内算「该件的 birth 登记」


# ---------------------------------------------------------------- 小工具

def norm(s):
    return re.sub(r"[\s*`]+", "", s or "")


def read_text(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


def read_lines(p):
    return read_text(p).splitlines()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def birth_of(p):
    out = subprocess.run(["stat", "-c", "%w", str(p)], capture_output=True, text=True)
    if out.returncode == 0:
        v = out.stdout.strip()
        if v and v != "-":
            return v
    return None


def mtime_of(p):
    return os.stat(p).st_mtime


def table_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def last_col(line):
    s = line.strip()
    if s.endswith("|"):
        s = s[:-1]
    return s.rsplit("|", 1)[1].strip() if "|" in s else ""


def status_symbol(cells):
    for c in cells:
        n = norm(c)
        if n[:1] in ("✅", "❌", "🔄"):
            return n[0]
    return None


def hhmmss(v):
    """把各种 birth 写法归一到 HH:MM:SS（时刻口径：本工作区数据不跨年，日期另行保留）。"""
    if not v:
        return None
    m = re.search(r"(\d{2}):(\d{2}):(\d{2})", v)
    if m:
        return "%s:%s:%s" % (m.group(1), m.group(2), m.group(3))
    return None


def norm_birth(v):
    """归一 birth 值 → HH:MM:SS（无日期者只取时刻；日期在本工作区不跨年）。"""
    return hhmmss(v)


# ---------------------------------------------------------------- 登记面

def load_registry(ws):
    p = ws / P_REGISTRY
    if not p.is_file():
        return None, "登记清单缺件：%s" % p
    try:
        return json.loads(read_text(p)), None
    except Exception as e:
        return None, "登记清单坏 JSON：%s" % e


def registered_keys(reg):
    out = set()
    for g in (reg.get("registered_gaps") or []):
        k = g.get("key")
        if k:
            out.add(k)
    return out


# ---------------------------------------------------------------- leg-E76

def check_e76(ws):
    """【严格】系统目标台账 ✅ 行 ↔ 映射 §二 判定列 自动对账。"""
    red, note, gaps = [], [], []
    tgt, mp = ws / P_TARGET, ws / P_MAPPING
    for p in (tgt, mp):
        if not p.is_file():
            return None, [], [], ["缺件：%s" % p]
    green = []
    for i, l in enumerate(read_lines(tgt), 1):
        if not l.startswith("|"):
            continue
        cells = table_cells(l)
        if not cells or not GID_RE.match(cells[0]):
            continue
        if status_symbol(cells) == "✅":
            green.append((i, cells[0]))
    verdicts = {}
    in_sec = False
    for i, l in enumerate(read_lines(mp), 1):
        if l.startswith("## "):
            in_sec = ("系统目标台账" in l and "G-SIL" in l)
            continue
        if not in_sec or not l.startswith("|"):
            continue
        cells = table_cells(l)
        if not cells or not GID_RE.match(cells[0]):
            continue
        verdicts[cells[0]] = (i, norm(last_col(l)))
    for ln, gid in green:
        if gid not in verdicts:
            red.append("台账✅行 %s(:%d) 在映射§二无对应判定行 → 无判定可对（假绿面）" % (gid, ln))
            continue
        vln, v = verdicts[gid]
        if not v.startswith("达标"):
            red.append("台账✅行 %s(:%d) 与映射§二判定(映射:%d「%s…」)不一致 → 假绿面"
                       % (gid, ln, vln, v[:24]))
    n_ok = sum(1 for _g, (_i, v) in verdicts.items() if v.startswith("达标"))
    if n_ok != len(green):
        red.append("台账✅行数(%d) ≠ 映射§二判定「达标」行数(%d) → 台账漏标✅或映射多判"
                   % (len(green), n_ok))
    note.append("台账✅行=%s；映射§二达标行=%d"
                % (",".join(g for _l, g in green) or "-", n_ok))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E101

def load_alarms(ws):
    p = ws / P_ALARMS
    if not p.is_file():
        return None
    evs = []
    for i, l in enumerate(read_lines(p), 1):
        s = l.strip()
        if not s.startswith("{"):
            continue
        try:
            o = json.loads(s)
        except Exception:
            continue
        evs.append({"line": i, "ts": o.get("ts", ""), "code": o.get("code", ""),
                    "msg": o.get("message", "")})
    return evs


def md_key(ts):
    """MM-DD HH:MM:SS 归一键（年无关；本工作区数据不跨年）。两种写法都吃：
    YYYY-MM-DD HH:MM:SS 与 MM-DD HH:MM:SS。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})", ts)
    if m:
        return "%s-%s %s" % (m.group(2), m.group(3), m.group(4))
    m = re.match(r"(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})", ts)
    if m:
        return "%s-%s %s" % (m.group(1), m.group(2), m.group(3))
    return None


def check_e101(ws):
    """【严格】台账 OBS-D4 销项行耐久断言复算对账。"""
    red, note, gaps = [], [], []
    led, al = ws / P_LEDGER, ws / P_ALARMS
    if not led.is_file() or not al.is_file():
        return None, [], [], ["缺件：%s" % (led if not led.is_file() else al)]
    row, rowln = None, 0
    for i, l in enumerate(read_lines(led), 1):
        if l.startswith("| OBS-D4 |"):
            row, rowln = l, i
            break
    if row is None:
        return None, [], [], ["缺件：阶段欠账台账.md 无 OBS-D4 行"]
    if not ("时点断言" in row or "不构成耐久承诺" in row):
        red.append("OBS-D4 销项行(:%d) 含耐久断言「零新增」但无时点限定标记（时点断言/不构成耐久承诺）"
                   "→ 断言可被无声作废" % rowln)
    evs = load_alarms(ws)
    exe = [e for e in evs if e["code"] == "af-execline-idle"]
    for k, e in enumerate(exe, 1):
        e["ord"] = k
    m = re.search(r"alarms\.log\s*(\d+)\s*条、末条\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|"
                  r"\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", row)
    snap_n = None
    if not m:
        red.append("OBS-D4 行(:%d) 未登记可复算口径「alarms.log N 条、末条 <ts>」" % rowln)
    else:
        snap_n = int(m.group(1))
        cut = m.group(2)
        cut_key = md_key(cut)
        calc = sum(1 for e in exe
                   if md_key(e["ts"]) is not None and cut_key is not None
                   and md_key(e["ts"]) <= cut_key)
        if calc != snap_n:
            red.append("OBS-D4 行(:%d) 登记的「alarms.log %d 条」与现值复算 %d 条矛盾（末条 %s）"
                       % (rowln, snap_n, calc, cut))
        note.append("登记 %d 条/末条 %s → 复算 %d 条" % (snap_n, cut, calc))
    registered = set(int(x) for x in re.findall(r"第\s*(\d+)\s*条", row))
    branch_m = re.search(r"起转入「(.+?)」", row)
    sig = branch_m.group(1) if branch_m else None
    br_ord = None
    nums = [int(a) for a, b in re.findall(r"第\s*(\d+)(?:/(\d+))?\s*条起", row)]
    flats = []
    for a, b in re.findall(r"第\s*(\d+)(?:/(\d+))?\s*条起", row):
        flats.append(int(a))
        if b:
            flats.append(int(b))
    if flats:
        br_ord = min(flats)
    if sig is None:
        red.append("OBS-D4 行(:%d) 无「起转入「X」」持续分支声明 → 第 110 条之后的真实持续类事件"
                   "无覆盖口径（对照名单缺失）" % rowln)
    uncovered = []
    for e in exe:
        o = e["ord"]
        if o in registered:
            continue
        if snap_n is not None and o <= snap_n:
            continue
        if sig is not None and sig in e["msg"] and br_ord is not None and o >= br_ord:
            continue
        uncovered.append(e)
    if uncovered:
        red.append("OBS-D4 行(:%d) 未覆盖的 af-execline-idle 事件 %d 条（点名前 3：%s）→ 同格编辑未同步"
                   % (rowln, len(uncovered),
                      "; ".join("#%d %s %s" % (e["ord"], e["ts"], e["msg"][:34]) for e in uncovered[:3])))
    note.append("af-execline-idle 事件 %d 条；行内登记序号 %d 个；分支签名=%s 起点=%s；未覆盖 %d"
                % (len(exe), len(registered), sig, br_ord, len(uncovered)))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E92

def check_e92(ws, reg):
    """【登记】方法论 §8 M-2 锚内容级核验。"""
    red, note, gaps = [], [], []
    doc, mp = ws / P_DOC, ws / P_MAPPING
    if not doc.is_file() or not mp.is_file():
        return None, [], [], [], ["缺件：%s" % (doc if not doc.is_file() else mp)]
    m2, m2ln = None, 0
    for i, l in enumerate(read_lines(doc), 1):
        if l.startswith("| M-2 |"):
            m2, m2ln = l, i
            break
    if m2 is None:
        return None, [], [], [], ["缺件：方法论文档无 `| M-2 |` 行"]
    cm = re.search(r"目的-监测项映射\.md:(\d+)", m2)
    if not cm:
        red.append("方法论 §8 M-2 行(:%d) 无「目的-监测项映射.md:NN」坐标 → 锚不可判" % m2ln)
        return True, red, gaps, note
    coord = int(cm.group(1))

    # (a)【严格】§7 期望串核验面在册且生效
    exp, exp_ln, exp_coord_row = None, 0, None
    m7 = re.compile(r"\|\s*`([^`]*目的-监测项映射\.md:(\d+))`\s*\|\s*`([^`]*)`")
    for i, l in enumerate(read_lines(doc), 1):
        mm = m7.search(l)
        if mm:
            exp = mm.group(3).replace("\\|", "|")
            exp_ln = i
            exp_coord_row = int(mm.group(2))
            break
    if exp is None:
        for i, l in enumerate(read_lines(doc), 1):
            if not l.startswith("|") or "目的-监测项映射.md" not in l:
                continue
            cells = table_cells(l)
            if len(cells) < 3:
                continue
            if "目的-监测项映射.md" in cells[1] and cells[2].strip("`"):
                exp = cells[2].strip("`").replace("\\|", "|")
                exp_ln = i
                break
    if exp is None:
        red.append("方法论 §7 人工抽查清单无「目的-监测项映射.md」期望串条目 → 该锚退回存在性放行"
                   "（RT-E92 原始形态）")
    exp_coord = reg.get("m2_expected_coord")
    tbl_ok = None
    anch_dir = ws / P_ANCHOR_DIR
    if not anch_dir.is_dir():
        return None, [], [], [], ["缺件：%s" % anch_dir]
    try:
        pr = subprocess.run([sys.executable, "-I", str(ws / P_ANCHOR), "--table"],
                            capture_output=True, text=True, timeout=300, cwd=str(ws))
    except Exception as e:
        return None, [], [], [], ["anchor-check --table 执行错：%s" % e]
    tbl_out = pr.stdout or ""
    # §7 期望串条目（其登记坐标 = exp_coord）必须被 anchor-check --table 判 [OK]
    # ——只断该条目，不连带判其他锚（其他锚的断链是 C5 债，另有其门）
    tbl_line = None
    for l in tbl_out.splitlines():
        if l.startswith("[") and "目的-监测项映射.md:%d" % (exp_coord or -1) in l:
            tbl_line = l
            break
    if tbl_line is None:
        red.append("anchor-check --table 输出中无「目的-监测项映射.md:%s」条目 → §7 期望串核验面未生效"
                   % exp_coord)
    elif not tbl_line.startswith("[OK"):
        red.append("anchor-check --table 对「目的-监测项映射.md:%s」判 %s → §7 期望串核验面未生效"
                   % (exp_coord, tbl_line.split("|")[0].strip()))
    else:
        tbl_ok = True
    note.append("M-2 锚坐标=映射.md:%d；§7 期望串行=%s（登记坐标=%s）；--table 该条目=%s"
                % (coord, exp_ln or "-", exp_coord, "OK" if tbl_ok else "红"))

    # (b)【登记】坐标对账
    if exp_coord is None:
        red.append("登记面缺 m2_expected_coord → M-2 锚坐标无判据（不可证）")
    elif coord != exp_coord:
        gaps.append({"leg": "RT-E92", "key": "E92-G1:M2锚坐标=%d≠登记坐标%d" % (coord, exp_coord),
                      "desc": "方法论 §8 M-2 行引用的 目的-监测项映射.md 坐标=%d，"
                              "而 §7 期望串核验面登记的现位坐标=%d（映射件 2026-11-03 12:05 再重写致漂）；"
                              "该锚指向非空但内容错的行（G-SIL 行），anchor-check 因零内容核验按存在性放行"
                              % (coord, exp_coord),
                      "upstream": "逃逸台账:770 RT-E92 / 阶段欠账台账:88"})

    # (c)(d) anchor-check 全量口径
    try:
        pr2 = subprocess.run([sys.executable, "-I", str(ws / P_ANCHOR), "--sample", "0"],
                             capture_output=True, text=True, timeout=300, cwd=str(ws))
    except Exception as e:
        return None, [], [], [], ["anchor-check 执行错：%s" % e]
    out = pr2.stdout or ""
    anchor_line = None
    for l in out.splitlines():
        if l.startswith("[") and "目的-监测项映射.md:%d" % coord in l:
            anchor_line = l
            break
    # (a2)【严格·B1 加严】期望串核验面在**全量口径**（=all-gates L3 常驻门口径）
    # 真实生效——原腿只断 --table（部分口径 exit 3），常驻门跑的是全量口径；
    # 两口径的期望串面必须都活着，否则「期望串面在册」是假面。
    if exp and exp_coord_row:
        exp_probe = exp[:24]
        full_line = None
        for l in out.splitlines():
            if l.startswith("[") and "目的-监测项映射.md:%d" % exp_coord_row in l:
                full_line = l
                break
        if full_line is None:
            red.append("anchor-check 全量跑输出中无「目的-监测项映射.md:%d」锚行 → §7 期望串面"
                       "在常驻门（全量）口径下未被机检面收集" % exp_coord_row)
        elif not full_line.startswith("[OK"):
            red.append("anchor-check 全量跑对「目的-监测项映射.md:%d」判 %s → §7 期望串面"
                       "在常驻门（全量）口径下未生效" % (exp_coord_row, full_line.split("|")[0].strip()))
        elif exp_probe not in full_line:
            red.append("anchor-check 全量跑对「目的-监测项映射.md:%d」判 OK 但输出行不含期望串"
                       "前缀「%s」→ 期望串面在常驻门口径下未生效" % (exp_coord_row, exp_probe))
        else:
            note.append("全量口径期望串面生效：映射.md:%d 含期望串前缀「%s…」"
                        % (exp_coord_row, exp_probe))
    # (b2)【B1 加严】坐标失配必须**机器可证**：登记坐标那一行确实载着被声称内容，
    # 而文档所引坐标那一行确实不载 ⇒ 「内容错」是事实而非登记面的自述。
    if exp and exp_coord_row and coord != exp_coord_row:
        ml = read_lines(mp)
        ok_row = ml[exp_coord_row - 1] if 0 < exp_coord_row <= len(ml) else ""
        bad_row = ml[coord - 1] if 0 < coord <= len(ml) else ""
        if exp[:24] not in ok_row:
            red.append("登记坐标 映射.md:%d 行不含 §7 期望串前缀「%s…」→ 登记坐标本身"
                       "已失准（登记面的 m2_expected_coord 须人工重锚）" % (exp_coord_row, exp[:24]))
        if exp[:24] in bad_row:
            red.append("文档所引 映射.md:%d 行**含**期望串前缀「%s…」→ 登记缺口描述"
                       "「该锚指向非空但内容错的行」与实况不符" % (coord, exp[:24]))
    if anchor_line is None:
        red.append("anchor-check 全量跑输出中无「目的-监测项映射.md:%d」锚行 → 该锚未被机检面收集"
                   % coord)
    elif "未核" in anchor_line and exp_coord_row is not None and exp_coord_row != coord:
        gaps.append({"leg": "RT-E92", "key": "E92-G2:M2锚零内容核验",
                     "desc": "anchor-check 全量跑判「目的-监测项映射.md:%d」为 未核(无声称) ⇒ "
                             "该锚**无 §7 期望串条目**（期望串登记在 %d）⇒ 零内容核验、按存在性"
                             "计入 PASS ⇒ 该锚永不可能转红（RT-E92 原始形态）"
                             % (coord, exp_coord_row),
                     "upstream": "逃逸台账:770 RT-E92 修复对账②③ / 阶段欠账台账:88"})
    elif "未核" in anchor_line:
        note.append("M-2 锚(映射.md:%d) 标签为未核，但该锚**有 §7 期望串条目**（期望串面已内容级"
                    "核验，标签只反映「散文/声称」面）⇒ 不计入零内容核验缺口" % coord)
    mv = re.search(r"未核\(无声称\)=(\d+)\s+未核\(散文元语言\)=(\d+)", out)
    if mv:
        unv = int(mv.group(1)) + int(mv.group(2))
        base = reg.get("anchor_unverified_baseline")
        if base is None:
            red.append("登记面缺 anchor_unverified_baseline → 未核计数无判据（不可证）")
        elif unv > base:
            red.append("anchor-check 未核锚计数 %d > 登记基线 %d → 新增未核锚（零内容核验面扩张）"
                       % (unv, base))
        note.append("未核计数=%d（基线 %s）；anchor-check rc=%d" % (unv, base, pr2.returncode))
    else:
        red.append("anchor-check 输出无「未核(无声称)/未核(散文元语言)」计数行 → 口径漂移不可判")
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E29

def snapshot_rows(ws):
    p = ws / P_SNAPSHOT
    if not p.is_file():
        return None
    rows = []
    for i, l in enumerate(read_lines(p), 1):
        s = l.strip()
        if not s:
            continue
        try:
            rows.append((i, json.loads(s)))
        except Exception:
            return None
    return rows


def row_hash(row):
    d = {k: v for k, v in row.items() if k != "prev_sha256"}
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def crit_key(p):
    """判据件的行文标识（行内出现的形态）：OBS-Dx-判据 / OBS-Dx 判据 / OBS-Dx-判据.md"""
    stem = p.stem                      # OBS-D1-判据 / OBS-D6-整改判据-20261101
    base = stem.split("-判据")[0]       # OBS-D1 / OBS-D6
    return base, stem


def check_e29(ws, reg):
    """【登记】birth 快照固化 + 文书登记面。"""
    red, note, gaps = [], [], []
    snap = ws / P_SNAPSHOT
    for p in (snap,):
        if not p.is_file():
            return None, [], [], [], ["缺件：%s" % p]
    files = reg.get("birth_files") or []
    if not files:
        return None, [], [], [], ["登记面 birth_files 为空"]
    rows = snapshot_rows(ws)
    if rows is None:
        return None, [], [], [], ["快照面坏 JSONL"]
    if not rows:
        red.append("快照面无任何行 → birth 快照未固化（RT-E29 原始形态）")
        return True, red, gaps, note
    prev = GENESIS
    for ln, r in rows:
        need, got = prev, r.get("prev_sha256")
        if got != need:
            red.append("快照链断裂：第 %d 行 prev_sha256=%s… ≠ 应为 %s… → 快照行被改/删/重排"
                       "（append-only 破）" % (ln, str(got)[:12], need[:12]))
            break
        prev = row_hash(r)
    else:
        note.append("快照链 %d 行完整" % len(rows))
    seen = {}
    for _ln, r in rows:
        seen.setdefault(r.get("path"), []).append(r)
    for rel in files:
        p = ws / rel
        if rel not in seen:
            red.append("登记件 %s 无 birth 快照行 → birth 证据锚未固化（RT-E29 原始形态）" % rel)
            continue
        if not p.is_file():
            red.append("登记件 %s 不在位（快照行在、件被删）→ 证据链断" % rel)
    # (c) 快照值 vs 盘面现值（严格）
    for rel in files:
        p = ws / rel
        if not p.is_file():
            continue
        rs = seen.get(rel) or []
        cur = birth_of(p)
        if cur is None:
            continue
        for idx, r in enumerate(rs):
            if r.get("birth") == cur:
                continue
            if not any(x.get("birth_reset") is True and (x.get("note") or "").strip()
                       for x in rs[idx + 1:]):
                red.append("登记件 %s 的快照 birth(%s) 与现值(%s) 矛盾且无更晚的勘误登记行"
                           "（birth_reset=true+理由）→ 禁静默（RT-E29 机制③）"
                           % (rel, str(r.get("birth"))[:19], cur[:19]))
                break
    # (d)(e) 文书登记面 + 登记值矛盾（登记腿）
    corpus = []
    for rel in [P_LEDGER, P_ESCAPE]:
        p = ws / rel
        if p.is_file():
            corpus.extend(read_lines(p))
    obsdir = ws / P_OBSDIR
    if obsdir.is_dir():
        for p in sorted(obsdir.glob("*.md")):
            corpus.extend(read_lines(p))
    for rel in files:
        p = ws / rel
        if not p.is_file():
            continue
        base, stem = crit_key(p)
        pat = re.compile(re.escape(base) + r"(?![0-9])")
        cited = set()
        nhits = 0
        for l in corpus:
            for m in pat.finditer(l):
                win = l[m.end(): m.end() + BIRTH_WINDOW]
                vals = [v for v in BIRTHVAL_RE.findall(win) if v]
                if vals:
                    nhits += 1
                    cited.update(vals)
        if nhits == 0:
            red.append("判据件 %s 的 birth 值在文书面（台账/逃逸台账/判据件）零登记 → 证据锚无登记面"
                       % rel)
            continue
        rs = seen.get(rel) or []
        snap_birth = rs[-1].get("birth") if rs else None
        snap_mtime = rs[-1].get("mtime") if rs else None
        sb = norm_birth(snap_birth)
        sm = norm_birth(snap_mtime)
        if sb and cited and sb not in cited and sm not in cited:
            gaps.append({"leg": "RT-E29", "key": "E29-G1:birth登记矛盾:%s" % rel,
                         "desc": "文书面登记的 birth 时刻 %s 与快照固化时刻 %s 矛盾（birth 易失："
                                 "编辑器 temp+rename 即重置）"
                                 % (",".join(sorted(cited)), sb),
                         "upstream": "逃逸台账:253 RT-E29 / 阶段欠账台账:54"})
    # (f)【严格·B1 加严】快照面与盘面**内容**同步：内容漂移必须有更晚的快照行。
    # （原腿只管 birth（易失属性）与文书登记值，管不到「内容改了而快照面没跟上」
    #   ⇒ 快照固化件只能证明「快照当时的内容」，快照面本身可被静默过期。）
    nsync = 0
    for rel in files:
        p = ws / rel
        if not p.is_file():
            continue
        rs = seen.get(rel) or []
        if not rs:
            continue
        cur_sha = sha256_file(p)
        last = rs[-1]
        if (last.get("sha256") or "") == cur_sha:
            nsync += 1
            continue
        red.append("登记件 %s 的盘面 sha256=%s… 与最新快照行(seq=%s)登记值 %s… 不符 ⇒ "
                   "内容已漂移而快照面未更新（快照固化件只能证明快照当时的内容）"
                   % (rel, cur_sha[:12], last.get("seq"), str(last.get("sha256"))[:12]))
    note.append("快照面内容同步 %d/%d 件（sha256 与最新快照行逐件相等）" % (nsync, len(files)))
    note.append("登记件 %d 件；快照行 %d 行" % (len(files), len(rows)))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E27

def check_e27(ws, reg):
    """【严格】判据时序登记完整性。"""
    red, note, gaps = [], [], []
    obs = ws / P_OBSDIR
    led = ws / P_LEDGER
    if not obs.is_dir() or not led.is_file():
        return None, [], [], [], ["缺件：%s" % (obs if not obs.is_dir() else led)]
    crit = sorted(p for p in obs.glob("*判据*.md") if not p.name.endswith(".bak"))
    if not crit:
        return None, [], [], [], ["判据全集为空（%s 无 *判据*.md）" % obs]
    corpus = []
    for p in crit:
        corpus.extend(read_lines(p))
    corpus.extend(read_lines(led))
    covered = set()
    for l in corpus:
        if not any(w in l for w in SEQ_WORDS) or not BIRTHVAL_RE.search(l):
            continue
        for p in crit:
            base, _stem = crit_key(p)
            if re.search(re.escape(base) + r"(?![0-9])", l):
                covered.add(p.name)
    for p in crit:
        if p.name not in covered:
            red.append("判据件 %s 无「判据时序登记」（语料中无同行含件名+birth 值+时序判定词的行）"
                       "→ 判据时序无文书登记（RT-E27 原始形态）" % p.name)
    if len(covered) != len(crit):
        red.append("判据时序登记覆盖 %d/%d 件（全集 ls *判据*.md vs 登记覆盖 diff，缺 %d 件）"
                   % (len(covered), len(crit), len(crit) - len(covered)))
    note.append("判据全集 %d 件：%s；登记覆盖 %d 件"
                % (len(crit), ",".join(p.name for p in crit), len(covered)))
    # (c)【严格·B1 加严】自称「判据先行」的件必须有时序自洽证据：
    #   要么该件自带时序更正/预注册状态声明（声明≠盘面已分账），要么语料里有
    #   一行把它**判为早于**施工（真预注册）。两者皆无 ⇒ 自称与盘面脱节＝
    #   RT-E27 原始形态（「判据先行」标题 + 事后补写事实，无任何文书登记）。
    cfg = (reg or {}).get("e27") or {}
    claim_marks = cfg.get("title_claim_markers") or ["判据先行"]
    corr_marks = cfg.get("correction_markers") or [
        "预注册状态声明", "时序更正声明", "事后补写", "事后追认", "不是预注册判据面", "时序声明"]
    for p in crit:
        txt = read_text(p)
        head = txt.splitlines()[0] if txt.splitlines() else ""
        if not any(m in head for m in claim_marks):
            continue
        if any(m in txt for m in corr_marks):
            continue
        base, _stem = crit_key(p)
        pat = re.compile(re.escape(base) + r"(?![0-9])")
        early = False
        for l in corpus:
            m = pat.search(l)
            if not m:
                continue
            win = l[m.end(): m.end() + 60]
            if "早于" in win and not any(w in win for w in ("晚于", "事后", "重置", "不成立")):
                early = True
                break
        if not early:
            red.append("判据件 %s 标题自称「%s」但既无自带时序更正声明、语料也未把它判为"
                       "「早于」⇒ 自称与盘面脱节（判据时序无文书登记，RT-E27 原始形态）"
                       % (p.name, "/".join(claim_marks)))
        else:
            note.append("判据件 %s 自称判据先行但语料判其「早于」⇒ 时序自洽（预注册成立）"
                        % p.name)
    return True, red, gaps, note


# ---------------------------------------------------------------- 状态词工具（B1 批新增）

STATE_WORDS = ("未开始", "已销", "部分", "未达", "在飞", "已消", "未核", "在途", "已核销")


def strip_strike(s):
    """去掉 markdown 删除线段（~~…~~）——被划掉的历史状态不得当作当前状态声明。"""
    return re.sub(r"~~[^~]*~~", "", s or "")


def state_word(s):
    """台账状态列 → 当前状态词（首符号原样 + 首词截取）。"""
    s = (s or "").strip()
    for sym in ("✅", "❌", "🔄"):
        if s.startswith(sym):
            return sym
    m = re.match(r"^(部分|未开始|未核|在飞|已消|已销|未达|已核销)", s)
    return m.group(1) if m else (s[:4] if s else "")


def first_state_token(text):
    """文本中最先出现的状态词（按出现位置取最早的；None=无）。"""
    best = None
    for w in STATE_WORDS:
        i = text.find(w)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, w)
    return best[1] if best else None


def status_cell_of(cells, idx=None):
    """取状态列（两本台账的列序不同：阶段欠账台账=末列；系统目标台账=第 4 列）。"""
    if idx is None:
        return cells[-1]
    try:
        i = int(idx)
    except (TypeError, ValueError):
        return cells[-1]
    if i < 0:
        i = len(cells) + i
    return cells[i] if 0 <= i < len(cells) else cells[-1]


# ---------------------------------------------------------------- leg-E109

def check_e109(ws, reg):
    """【严格】台账行态验证命令绑定 + 下游引用对账（RT-E109 拦截机制①②）。

    机制①（逃逸台账:883 RT-E109）：「行态验证命令绑定：状态列非空行同格带机读校验
      命令，巡检复跑」——本腿对**登记面在册**的每一行逐条执行：
      ① 行内状态列必须带该机读命令（绑定在位）；
      ② 实跑该命令 → 得实跑读数；
      ③ 行内**登记的读数** ⟷ 实跑读数 对账。★ 判红方向是**单向**的：
         「行内称绿（红 0 条 / exit=0）而实跑为红」⇒ **假绿面 ⇒ 判红**；
         「行内称红而实跑为绿」⇒ 台账**方向保守**（不是假绿）⇒ 只报**勘正建议**
         （打印在 note，不判红）；两侧读数均绿但计数漂移 ⇒ 同样只报勘正建议。
         （口径理由：判据面只许变严且不得制造假红；假绿是必须拦的方向。）
    机制②（同条）：下游判定引用台账行态时，断言被引行态与台账当前状态词一致
      （被引面的状态声明取「首个 anchor 出现之后、删除线段已剔除」的最先状态词；
       删除线段内是被划掉的历史状态，不得当作当前声明）。
    """
    red, note, gaps = [], [], []
    binds = (reg or {}).get("row_state_bindings") or []
    if not binds:
        red.append("登记面缺 row_state_bindings → 「行态验证命令绑定」未在册（RT-E109 拦截机制①未落）")
        return True, red, gaps, note
    for b in binds:
        bid = b.get("id") or "?"
        led_rel = b.get("ledger")
        row_id = b.get("row_id")
        cmd = b.get("verify_cmd") or []
        claim_re = b.get("claim_re")
        live_re = b.get("live_re")
        if not (led_rel and row_id and cmd and claim_re and live_re):
            red.append("绑定 %s 登记不全（ledger/row_id/verify_cmd/claim_re/live_re 必填）" % bid)
            continue
        led_p = ws / led_rel
        if not led_p.is_file():
            red.append("绑定 %s 的台账缺件：%s" % (bid, led_rel))
            continue
        row = None
        for i, l in enumerate(read_lines(led_p), 1):
            if not l.startswith("|"):
                continue
            cells = table_cells(l)
            if cells and cells[0].strip() == row_id:
                row = (i, cells)
                break
        if row is None:
            red.append("绑定 %s：台账 %s 无 %s 行（行已下线或改名）" % (bid, led_rel, row_id))
            continue
        rln, rcells = row
        status_cell = status_cell_of(rcells, b.get("status_col_idx"))
        # ① 机制①：同格必须带机读校验命令
        cmd_key = b.get("cmd_key") or (
            " ".join(str(c) for c in cmd[1:]) if (cmd and str(cmd[0]).endswith("python3"))
            else " ".join(str(c) for c in cmd))
        if cmd_key and cmd_key not in status_cell:
            red.append("台账 %s(:%d) 状态列未带机读校验命令「%s」→ 行态验证命令绑定未落"
                       % (row_id, rln, cmd_key))
            continue
        # ② 实跑校验命令
        try:
            pr = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                                timeout=300, cwd=str(ws))
        except Exception as e:  # noqa: BLE001
            red.append("绑定 %s 的校验命令执行错：%s" % (bid, e))
            continue
        out = (pr.stdout or "") + (pr.stderr or "")
        live = re.search(live_re, out)
        if not live:
            red.append("绑定 %s 的校验命令输出不匹配 live_re → 实跑读数不可解析（判据不可证）" % bid)
            continue
        claim = re.search(claim_re, status_cell)
        if not claim:
            red.append("台账 %s(:%d) 状态列内无可解析的登记读数（claim_re 不命中）→ "
                       "行态无机器可对账的证据（RT-E109 原始形态）" % (row_id, rln))
            continue
        crows, creg = int(claim.group("rows")), int(claim.group("reg"))
        cunreg, cred = int(claim.group("unreg")), int(claim.group("red"))
        cexit = claim.groupdict().get("exit")
        lrows, lreg = int(live.group("rows")), int(live.group("reg"))
        lunreg, lred = int(live.group("unreg")), int(live.group("red"))
        # ③ 读数对账（单向判红：只拦假绿方向）
        if cred == 0 and lred > 0:
            red.append("台账 %s(:%d) 登记读数称绿（红 0 条）而实跑为红（红 %d 条）→ 假绿面"
                       % (row_id, rln, lred))
        elif (crows, creg, cunreg, cred) != (lrows, lreg, lunreg, lred):
            note.append("台账 %s(:%d) 登记读数已过期（登记 裁决行%d/登记回写%d/未登记%d/红%d ｜ "
                        "实跑 裁决行%d/登记回写%d/未登记%d/红%d）→ **台账行态勘正建议**"
                        "（方向保守、非假绿，本腿不判红；判红口径见门件 docstring leg-E109）"
                        % (row_id, rln, crows, creg, cunreg, cred, lrows, lreg, lunreg, lred))
        if cexit is not None and str(cexit) == "0" and pr.returncode != 0:
            red.append("台账 %s(:%d) 登记 exit=0 而实跑 exit=%d → 假绿面"
                       % (row_id, rln, pr.returncode))
        note.append("绑定 %s：台账 %s(:%d)｜命令 %s｜登记读数 红%d ｜ 实跑 红%d（exit=%d）"
                    % (bid, row_id, rln, cmd_key, cred, lred, pr.returncode))
        # ④ 机制②：下游引用对账
        cur = state_word(status_cell)
        for ref in (b.get("downstream_refs") or []):
            rp = ws / (ref.get("path") or "")
            rid = ref.get("row_id")
            anchor = ref.get("anchor") or row_id
            if not rp.is_file():
                red.append("下游引用 %s：%s 缺件" % (bid, ref.get("path")))
                continue
            cell = None
            for l in read_lines(rp):
                if not l.startswith("|"):
                    continue
                cs = table_cells(l)
                if cs and cs[0].strip() == rid:
                    cell = status_cell_of(cs, ref.get("status_col_idx"))
                    break
            if cell is None:
                red.append("下游引用 %s：%s 无 %s 行" % (bid, ref.get("path"), rid))
                continue
            s = strip_strike(cell)
            k = s.find(anchor)
            if k < 0:
                red.append("下游引用 %s：%s 的 %s 行内无「%s」引用 → 引用面消失（不得默认可对）"
                           % (bid, ref.get("path"), rid, anchor))
                continue
            seg = s[k + len(anchor):]
            # 2026-11-06：符号态（✅/❌/🔄）优先识别——原 first_state_token 词表无符号，
            # 被引行态翻 ✅ 后本腿结构性永红（RT-PP3 核销回写实证）。词表路径不变、只增可比面。
            _msym = re.match(r"^[\s=\→·:*\-~]*([✅❌🔄])", seg)
            tok = _msym.group(1) if _msym else first_state_token(seg)
            if tok is None:
                red.append("下游引用 %s：%s 的 %s 行引用「%s」后无可解析的状态声明 → "
                           "下游引用对账不可判（RT-E109 拦截机制②未落）"
                           % (bid, ref.get("path"), rid, anchor))
                continue
            if tok != cur:
                red.append("下游引用 %s：%s 的 %s 行声明被引行态=「%s」，台账 %s(:%d) 实际=「%s」"
                           " → 下游判定建立在失实行态上（RT-E109 拦截机制②）"
                           % (bid, ref.get("path"), rid, tok, row_id, rln, cur))
            else:
                note.append("下游引用 %s：%s 的 %s 行声明被引行态=「%s」≡ 台账 %s(:%d) 实际=「%s」"
                            % (bid, ref.get("path"), rid, tok, row_id, rln, cur))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E110

def check_e110(ws, reg):
    """【严格】系统目标台账横扫对账的「最后一段」（RT-E110 残项）。

    E76 腿只断「台账 ✅ 行 ↔ 映射§二 判定列」**一个方向**；RT-E110 判定的残余是
    ①**反向**也必须对齐（台账 ❌/🔄 行在映射 §二 不得判「达标」——反向失配＝
      台账在表内自认未达、映射却在另一面判达标 ⇒ 两面打架且无人拦）；
    ②**同格矛盾**：台账 ✅ 行的状态列内不得含自认未达措辞（矛盾证据同格在场
      而门不红＝RT-E110「为什么既有门没拦」直指）；
    ③**下游汇总引用**：G11 行的「G1-G10 全绿」类汇总引用必须带否定/勘误标记，
      否则汇总面冻结于成文时点、被引行变化不传播（RT-E110 原始形态）。
    """
    red, note, gaps = [], [], []
    cfg = (reg or {}).get("e110") or {}
    cwords = cfg.get("contradiction_words") or []
    sum_row = cfg.get("summary_row") or "G11"
    sum_phrases = cfg.get("summary_ref_phrases") or []
    neg_markers = cfg.get("negation_markers") or []
    tgt, mp = ws / P_TARGET, ws / P_MAPPING
    for p in (tgt, mp):
        if not p.is_file():
            return None, [], [], ["缺件：%s" % p]
    rows = {}
    for i, l in enumerate(read_lines(tgt), 1):
        if not l.startswith("|"):
            continue
        cells = table_cells(l)
        if not cells or not GID_RE.match(cells[0]):
            continue
        rows[cells[0]] = (i, cells, status_symbol(cells))
    verdicts = {}
    in_sec = False
    for i, l in enumerate(read_lines(mp), 1):
        if l.startswith("## "):
            in_sec = ("系统目标台账" in l and "G-SIL" in l)
            continue
        if not in_sec or not l.startswith("|"):
            continue
        cells = table_cells(l)
        if not cells or not GID_RE.match(cells[0]):
            continue
        verdicts[cells[0]] = (i, norm(last_col(l)))
    # ① 反向对齐
    for gid, (i, cells, sym) in rows.items():
        if sym not in ("❌", "🔄"):
            continue
        if gid not in verdicts:
            red.append("台账 %s(:%d) 状态=%s 但映射§二无对应判定行 → 两面不对齐（不可对）"
                       % (gid, i, sym))
            continue
        vln, v = verdicts[gid]
        if v.startswith("达标"):
            red.append("台账 %s(:%d) 状态=❌/🔄 而映射§二判定为「%s…」（映射:%d）→ 两面打架"
                       "（RT-E110 横扫对账反向缺口）" % (gid, i, v[:16], vln))
    # ② 同格矛盾
    n_ok = 0
    for gid, (i, cells, sym) in rows.items():
        if sym != "✅":
            continue
        n_ok += 1
        cell = status_cell_of(cells, 3)   # 系统目标台账列序：| G | 目标 | 验收门 | 状态 | 批次 |
        hit = [w for w in cwords if w in cell]
        if hit:
            red.append("台账 %s(:%d) 状态列=✅ 但同格含自认未达措辞 %s → 同格矛盾（假绿面）"
                       % (gid, i, "、".join(hit)))
    # ③ 下游汇总引用
    if sum_row in rows:
        i, cells, sym = rows[sum_row]
        cell = status_cell_of(cells, 3)   # 系统目标台账列序：| G | 目标 | 验收门 | 状态 | 批次 |
        hitp = [p for p in sum_phrases if p in cell]
        if hitp:
            nbad = [g for g, (_i, _c, s) in rows.items()
                    if s == "❌" and g != sum_row and GID_RE.match(g)]
            if nbad and not [m for m in neg_markers if m in cell]:
                red.append("台账 %s(:%d) 含汇总引用 %s，而同表存在未达行 %s，但该行无任何"
                           "否定/勘误标记 → 汇总面冻结于成文时点（RT-E110 原始形态）"
                           % (sum_row, i, "、".join(hitp), "、".join(sorted(nbad))))
            else:
                note.append("汇总行 %s(:%d) 引用 %s；同表未达行 %s；否定/勘误标记在位=%s"
                            % (sum_row, i, "、".join(hitp), "、".join(sorted(nbad)) or "无",
                               bool([m for m in neg_markers if m in cell])))
    note.append("台账行 %d（✅%d）；映射§二判定行 %d" % (len(rows), n_ok, len(verdicts)))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-E111

def check_e111(ws, reg):
    """【严格】G5「清零留证」验收断言的**多源化**对账（RT-E111 拦截机制① / RT-E119）。

    RT-E111 根因：「清零」的判定域（欠账台账）与实债的存放域（逃逸台账未竟行、
    技术债登记、剩余欠账总表）不重合 ⇒ 欠账台账按字面清零即可达标而实债在
    另一本账里隐身（台账可博弈处）。本腿把 G5 的验收断言钉成多源：
      ① 各源必须**在位且可解析**（缺件 ⇒ 不可证 fail-closed，不猜绿）；
      ② 逐源枚举未清零项（打印，可审）；
      ③ **假绿面**：G5 行状态列声称已清零（✅）而任一源仍有未清零项 ⇒ 红；
      ④ 逃逸源口径**同源复用** tools/test-ledger-migration-recon.py（不另立一套
        判定词表——防「对账面自身失明」同源病）；
      ⑤ G5 行的验收门格若未声明多源枚举域 ⇒ 记为**已登记缺口**（登记腿：绿但
        逐次打印，并给出清偿路径）；若声明了多源而与本腿源清单不一致 ⇒ 红
        （半声明＝假三源化）。
    """
    red, note, gaps = [], [], []
    cfg = (reg or {}).get("g5_clear_assertion") or {}
    srcs = cfg.get("sources") or []
    if not srcs:
        red.append("登记面缺 g5_clear_assertion.sources → G5 清零断言未多源化（RT-E111 机制①未落）")
        return True, red, gaps, note
    tgt = ws / P_TARGET
    if not tgt.is_file():
        return None, [], [], ["缺件：%s" % tgt]
    # G5 行
    g5 = None
    for i, l in enumerate(read_lines(tgt), 1):
        if not l.startswith("|"):
            continue
        cells = table_cells(l)
        if cells and cells[0].strip() == (cfg.get("ledger_row_id") or "G5"):
            g5 = (i, cells)
            break
    if g5 is None:
        return None, [], [], ["缺件：系统目标台账无 %s 行" % (cfg.get("ledger_row_id") or "G5")]
    g5ln, g5cells = g5
    # 系统目标台账列序：| G | 目标 | 验收门（机检） | 状态 | 批次 |
    g5_gate = g5cells[2] if len(g5cells) > 2 else ""
    g5_status = g5cells[3] if len(g5cells) > 3 else ""
    counts = {}
    for s in srcs:
        sid = s.get("id")
        path = s.get("path")
        p = ws / path
        if not p.is_file():
            return None, [], [], ["缺件（源 %s）：%s" % (sid, path)]
        if s.get("kind") == "escape":
            # 同源复用迁移对账门（口径唯一）
            mp = ws / P_MIGRECON
            if not mp.is_file():
                return None, [], [], ["缺件（逃逸源口径门）：%s" % P_MIGRECON]
            try:
                pr = subprocess.run([sys.executable, "-I", str(mp)], capture_output=True,
                                    text=True, timeout=300, cwd=str(ws))
            except Exception as e:  # noqa: BLE001
                return None, [], [], ["逃逸源口径门执行错：%s" % e]
            mo = (pr.stdout or "") + (pr.stderr or "")
            mm = re.search(r"修复对账自认未完结\s*(\d+)", mo)
            if not mm:
                return None, [], [], ["逃逸源口径门输出不可解析（未完结计数缺失）"]
            counts[sid] = int(mm.group(1))
            note.append("源 %s（%s）：未完结 %d 条（口径同源 %s）"
                        % (sid, path, counts[sid], P_MIGRECON))
            continue
        n = 0
        total = 0
        for l in read_lines(p):
            if not l.startswith("|"):
                continue
            cells = table_cells(l)
            if not cells or len(cells) < 2:
                continue
            rid = cells[0].strip()
            if s.get("id_prefixes"):
                if not any(rid.startswith(x) for x in s["id_prefixes"]):
                    continue
            total += 1
            st = cells[-1] if s.get("status_col") == "last" else (
                cells[s.get("status_idx", 3)] if len(cells) > s.get("status_idx", 3) else "")
            st = st.strip()
            cleared = False
            for m in (s.get("cleared_markers") or []):
                if m in st:
                    cleared = True
                    break
            if not cleared:
                n += 1
        counts[sid] = n
        note.append("源 %s（%s）：在册 %d 行，未清零 %d 行" % (sid, path, total, n))
    uncleared = {k: v for k, v in counts.items() if v > 0}
    # ③ 假绿面：G5 声称已清零而任一源仍有未清零项
    if g5_status.strip().startswith("✅") and uncleared:
        red.append("系统目标台账 G5(:%d) 状态列=✅（声称清零留证）而多源实况仍有未清零项 %s"
                   " → G5 验收断言只读一本账＝可博弈面（RT-E111 拦截机制①）"
                   % (g5ln, "、".join("%s:%d" % (k, v) for k, v in sorted(uncleared.items()))))
    # ⑤ G5 验收门格的多源声明
    declared = [t for t in (cfg.get("source_declaring_markers") or []) if t in g5_gate]
    need = [t for t in (cfg.get("source_declaring_markers") or [])]
    if declared and len(declared) < len(need):
        red.append("系统目标台账 G5(:%d) 验收门格声明了部分源 %s 而未声明全部 %s → 半声明＝假多源化"
                   % (g5ln, "、".join(declared), "、".join(need)))
    elif not declared:
        gaps.append({"leg": "RT-E111", "key": "E111-G1:G5验收门只读一本账",
                     "desc": "系统目标台账 G5(:%d) 验收门格现文「%s」只声明单一源（欠账台账），"
                             "未声明逃逸台账/技术债登记/总表枚举域 ⇒ G5「清零」判定域与实债存放域"
                             "不重合（台账可博弈处，RT-E111 根因）；清偿路径＝改该格为多源枚举声明"
                             % (g5ln, g5_gate[:60]),
                     "upstream": "逃逸台账:905 RT-E111 / 逃逸台账:970 RT-E119 / 阶段欠账台账:72,75"})
    else:
        note.append("G5(:%d) 验收门格已声明多源枚举域 %s" % (g5ln, "、".join(declared)))
    note.append("多源未清零计数：%s" % ("、".join("%s=%d" % (k, v) for k, v in sorted(counts.items()))))
    return True, red, gaps, note


# ---------------------------------------------------------------- leg-D148（三本账三向逐行 diff · ESC-08①/台账 D-148）

def scrub_p04(text):
    """P-04 机械脱敏（整段替换；与 ledger-sync.sh SCRUB 的 span 投影同形——沙箱合成用）。"""
    return INTADDR_RE.sub(P04_MARK, text)


def cell_id(line):
    """锚行首格 id（未转义竖线界；无第二枚竖线取行首格尾；非 | 起头 ⇒ None）。"""
    if not line.startswith("|"):
        return None
    idx, esc = [], False
    for i, ch in enumerate(line):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == "|":
            idx.append(i)
            if len(idx) == 2:
                return line[idx[0] + 1:idx[1]].strip() or None
    return line[1:].strip() or None


def resolve_planc_ledger(ws):
    """规划环实读 C 的台账路径（AF_LEDGER_SYNC_CLONE env → ws 内沙箱位 → 生产位克隆）。"""
    env = os.environ.get("AF_LEDGER_SYNC_CLONE")
    if env:
        return Path(env) / "账本" / "阶段欠账台账.md"
    sb = ws / P_PLANC_SB_LEDGER
    if sb.is_file():
        return sb
    return DEF_PLANC_CLONE / "账本" / "阶段欠账台账.md"


def _tail_core(line):
    s = line.rstrip()
    if s.endswith("|"):
        s = s[:-1].rstrip()
    return s


def _p04_unmark(x, y):
    """x 内脱敏标记以 y 内同序内网地址一一回代 ⇒ 回代后文本；不可逆（计数不匹配）⇒ None。"""
    marks = list(MARK_RE.finditer(x))
    if not marks:
        return None
    addrs = INTADDR_RE.findall(y)
    if len(marks) != len(addrs):
        return None
    out, last = [], 0
    for m, a in zip(marks, addrs):
        out.append(x[last:m.start()])
        out.append(a)
        last = m.end()
    out.append(x[last:])
    return "".join(out)


def _canon_pair(x, y):
    """两侧各归到「地址形」（各自标记以对侧同序地址回代；数不匹配 ⇒ None＝不可归一）。"""
    def one(a, b):
        if MARK_RE.search(a):
            return _p04_unmark(a, b)
        return a
    cx = one(x, y)
    if cx is None:
        return None
    cy = one(y, x)
    if cy is None:
        return None
    return cx, cy


def _first_diff(x, y):
    n = min(len(x), len(y))
    i = 0
    while i < n and x[i] == y[i]:
        i += 1
    return i


def _classify_line_pair(xl, yl, lag_side):
    """单行对判定 ⇒ (cls, desc)。cls ∈ {"equal","p04","lag","red"}。
    lag_side：允许作滞后侧的方向（"x"/"y"/"both"——A 参与的书对只认 B/C 滞后）。
    滞后两径：①投影可逆归一后的前缀（标记↔地址值对得上）；②字节级前缀（公共区逐字节
    同 ⇒ 分歧必然全在领先侧 append 尾内——投影×滞后复合：滞后本未收含地址的 append
    时无地址可回代，①不可用而②成立）。公共区内值变（地址↔异地址）两径皆败 ⇒ 红。"""
    cp = _canon_pair(xl, yl)
    had_mark = bool(MARK_RE.search(xl) or MARK_RE.search(yl))
    if cp is not None and cp[0] == cp[1]:
        return ("p04" if had_mark else "equal"), ""
    if cp is not None:
        tcx, tcy = _tail_core(cp[0]), _tail_core(cp[1])
        if lag_side in ("y", "both") and tcy and tcx.startswith(tcy):
            return "lag", "行尾 append 滞后（复合投影）"
        if lag_side in ("x", "both") and tcx and tcy.startswith(tcx):
            return "lag", "行尾 append 滞后（复合投影）"
    rx, ry = _tail_core(xl), _tail_core(yl)
    if lag_side in ("y", "both") and ry and rx.startswith(ry):
        return "lag", "行尾 append 滞后"
    if lag_side in ("x", "both") and rx and ry.startswith(rx):
        return "lag", "行尾 append 滞后"
    bx, by = cp if cp is not None else (xl, yl)
    i = _first_diff(bx, by)
    if cp is None:
        return "red", "投影不可逆（P-04 标记/内网地址计数不匹配）⇒ 非白名单"
    return "red", "行内分叉（%s）首异@%d「%s」→「%s」" % (
        "投影不可逆·非白名单" if had_mark else "非投影·非滞后形态",
        i, bx[max(0, i - 18):i + 22], by[max(0, i - 18):i + 22])


def _tail_anchor_block(all_lines, left):
    """残行组是否为「文件末尾连续锚行块」（滞后尾行形态的形状门）。"""
    if not left:
        return False
    nums = [n for n, _l in left]
    if nums != list(range(nums[0], nums[-1] + 1)):
        return False
    if nums[-1] != len(all_lines):
        return False
    return all(l.startswith("|") for _n, l in left)


def check_e148(ws):
    """【严格·白名单投影】三本账三向逐行 diff 常驻腿（ESC-08① / 台账 D-148）。"""
    red, note = [], []
    books = [("A", ws / P_LEDGER), ("B", ws / P_REPO_LEDGER),
             ("C", resolve_planc_ledger(ws))]
    texts, lines = {}, {}
    for tag, p in books:
        if not p.is_file():
            return None, [], [], ["缺件：三本账之%s（%s）不可读——fail-closed 不猜绿" % (tag, p)]
        try:
            texts[tag] = read_text(p)
        except Exception as e:  # noqa: BLE001
            return None, [], [], ["坏件：三本账之%s 读失败：%s" % (tag, e)]
    for tag, txt in texts.items():
        ls = txt.split("\n")
        while ls and not ls[-1].strip():
            ls.pop()
        lines[tag] = ls
    for tag, p in books:
        note.append("三本实读 %s=%s 行=%d sha256=%s" % (tag, p, len(lines[tag]), sha256_file(p)[:12]))
    idsets = {t: set(i for i in (cell_id(l) for l in ls) if i)
              for t, ls in lines.items()}
    stat = {}
    for xt, yt in (("A", "C"), ("A", "B"), ("B", "C")):
        pair = "%s↔%s" % (xt, yt)
        xa, ya = lines[xt], lines[yt]
        lag_side = "both" if {xt, yt} == {"B", "C"} else ("y" if yt in ("B", "C") else "x")
        p04r, lagtail, lagapp = [], [], []
        sm = difflib.SequenceMatcher(None, xa, ya, autojunk=False)
        for _tag, i1, i2, j1, j2 in sm.get_opcodes():
            if _tag == "equal":
                continue
            xr, yr = xa[i1:i2], ya[j1:j2]
            if len(xr) == len(yr):
                for k in range(len(xr)):
                    cls, desc = _classify_line_pair(xr[k], yr[k], lag_side)
                    ln, cid = i1 + k + 1, cell_id(xr[k]) or "?"
                    if cls == "p04":
                        p04r.append((ln, cid))
                    elif cls == "lag":
                        lagapp.append((ln, cid))
                    elif cls == "red":
                        red.append("%s L%d「%s」%s" % (pair, ln, cid, desc))
                continue
            # 行数不等：同首格 id 配对；残行按「尾行滞后 / 红」分派
            ymap = {}
            for k, l in enumerate(yr):
                cid = cell_id(l)
                if cid and cid not in ymap:
                    ymap[cid] = k
            taken, xleft = set(), []
            for k, l in enumerate(xr):
                cid = cell_id(l)
                if cid and cid in ymap and ymap[cid] not in taken:
                    taken.add(ymap[cid])
                    cls, desc = _classify_line_pair(l, yr[ymap[cid]], lag_side)
                    ln, rid = i1 + k + 1, cid
                    if cls == "p04":
                        p04r.append((ln, rid))
                    elif cls == "lag":
                        lagapp.append((ln, rid))
                    elif cls == "red":
                        red.append("%s L%d「%s」%s" % (pair, ln, rid, desc))
                else:
                    xleft.append((i1 + k + 1, l))
            yleft = [(j1 + k + 1, l) for k, l in enumerate(yr) if k not in taken]
            for left, lls, side_ok, other_ids, lead_tag, lag_tag in (
                    (xleft, xa, lag_side in ("y", "both"), idsets[yt], xt, yt),
                    (yleft, ya, lag_side in ("x", "both"), idsets[xt], yt, xt)):
                if not left:
                    continue
                ok_tail = _tail_anchor_block(lls, left)
                no_reorder = all((cell_id(l) or "?") not in other_ids for _n, l in left)
                if ok_tail and no_reorder and side_ok:
                    ids_ = [cell_id(l) or "?" for _n, l in left]
                    lagtail.extend((n, i) for (n, _l), i in zip(left, ids_))
                elif ok_tail and no_reorder:
                    red.append("%s 尾行 %d 行为%s 侧独有而领先方向不获准（%s 多出 %s 无的内容，"
                               "方向违例）⇒ 非白名单 hunk" % (pair, len(left), lead_tag, lead_tag, lag_tag))
                else:
                    for n, l in left:
                        cid = cell_id(l) or "?"
                        why = ("行序漂移（id 在对侧他处出现）" if cid in other_ids
                               else ("非锚行残差" if not l.startswith("|") else "中段行增删（非尾行滞后形态）"))
                        red.append("%s L%d「%s」%s ⇒ 非白名单 hunk" % (pair, n, cid, why))
        stat[pair] = (p04r, lagtail, lagapp)
    nlag = 0
    for pair, (p04r, lagtail, lagapp) in stat.items():
        if p04r:
            note.append("%s 设计内投影（P-04 脱敏，D-114）%d 行（%s）→ 白名单；白名单扩张须判官批 PR"
                        % (pair, len(p04r), "、".join("L%d「%s」" % (n, c) for n, c in p04r[:5])))
        if lagtail or lagapp:
            nlag += len(lagtail) + len(lagapp)
            note.append("%s 滞后 hunk＝尾行 %d 行（%s）＋行尾 append %d 行（%s）→ 归因 D-123 滞后腿"
                        "（factory-os#135 承载·本腿不并吞不判红；不得读作已消）"
                        % (pair, len(lagtail), "、".join(c for _n, c in lagtail[:6]) or "-",
                           len(lagapp), "、".join(c for _n, c in lagapp[:6]) or "-"))
    a, b, c = idsets["A"], idsets["B"], idsets["C"]
    note.append("滞后锚数（D-123 读数面）：A−B=%d A−C=%d C−B=%d" % (len(a - b), len(a - c), len(c - b)))
    note.append("hunk 归因计数：非白名单=%d（⇒红）；P-04 投影=%d 行；滞后（归因 D-123）=%d 行"
                % (len(red), sum(len(s[0]) for s in stat.values()), nlag))
    return True, red, [], note


# ---------------------------------------------------------------- 编排

def run_all(ws, reg, only=None):
    results = []
    for name, fn in (("RT-E76", check_e76), ("RT-E101", check_e101),
                     ("RT-E92", check_e92), ("RT-E29", check_e29), ("RT-E27", check_e27),
                     ("RT-E109", check_e109), ("RT-E110", check_e110), ("RT-E111", check_e111),
                     ("D-148", check_e148)):
        if only and name not in only:
            continue
        try:
            if name in ("RT-E92", "RT-E29", "RT-E109", "RT-E110", "RT-E111", "RT-E27"):
                ok, red, gaps, note = fn(ws, reg)
            else:
                ok, red, gaps, note = fn(ws)
        except Exception as e:  # noqa: BLE001 —— 任何异常＝不可证，不猜绿
            results.append((name, None, [], [], ["执行错：%s: %s" % (type(e).__name__, e)]))
            continue
        results.append((name, ok, red, gaps, note))
    return results


def report(results, reg, out=sys.stdout):
    keys = registered_keys(reg or {})
    nred = ninf = 0
    for name, ok, red, gaps, note in results:
        if ok is None:
            ninf += 1
            out.write("[不可证] %-8s %s\n" % (name, "；".join(note)))
            continue
        for g in gaps:
            if g["key"] not in keys:
                red = red + ["未登记缺口 %s｜%s" % (g["key"], g["desc"])]
        if red:
            nred += 1
            out.write("[红]     %-8s %d 项\n" % (name, len(red)))
            for r in red:
                out.write("           - %s\n" % r)
        else:
            out.write("[绿]     %-8s\n" % name)
        if gaps:
            out.write("           · 已登记缺口 %d 项（**账实未清，勿读作已消**）：\n" % len(gaps))
            for g in gaps:
                out.write("             · %s ｜ %s ｜ 上游登记：%s\n"
                          % (g["key"], g["desc"][:90], g.get("upstream", "-")))
        for nn in note:
            out.write("           · %s\n" % nn)
    return nred, ninf


# ---------------------------------------------------------------- 写入面

DEFAULT_BIRTH_FILES = [
    P_OBSDIR + "/OBS-D1-判据.md",
    P_OBSDIR + "/OBS-D2-判据.md",
    P_OBSDIR + "/OBS-D3-判据.md",
    P_OBSDIR + "/OBS-D4-判据.md",
    P_OBSDIR + "/OBS-D4-判据.md.20261031-pre-RT.bak",
    P_OBSDIR + "/OBS-D6-判据.md",
    P_OBSDIR + "/OBS-D6-整改判据-20261101.md",
]

DEFAULT_GAPS = [
    {"leg": "RT-E92", "key": "E92-G1:M2锚坐标=29≠登记坐标28",
     "desc": "方法论 §8 M-2 行引用的 目的-监测项映射.md 坐标=29，"
             "而 §7 期望串核验面登记的现位坐标=28（映射件 2026-11-03 12:05 再重写致漂）；"
             "该锚指向非空但内容错的行（G-SIL 行），anchor-check 因零内容核验按存在性放行",
     "upstream": "逃逸台账:770 RT-E92 / 阶段欠账台账:88"},
    {"leg": "RT-E92", "key": "E92-G2:M2锚零内容核验",
     "desc": "anchor-check 全量跑判「目的-监测项映射.md:29」为 未核(无声称) ⇒ 零内容核验、"
             "按存在性计入 PASS ⇒ 该锚永不可能转红（RT-E92 原始形态）",
     "upstream": "逃逸台账:770 RT-E92 修复对账②③ / 阶段欠账台账:88"},
    {"leg": "RT-E29", "key": "E29-G1:birth登记矛盾:%s" % (P_OBSDIR + "/OBS-D4-判据.md"),
     "desc": "文书面登记的 birth 值 19:56:18（重置前历史值）与快照固化值 2026-11-02 17:59:42 "
             "矛盾（birth 易失：编辑器 temp+rename 即重置；台账:26 已注明以改前留档 .bak mtime 为准）",
     "upstream": "逃逸台账:253 RT-E29 / 阶段欠账台账:54 / 阶段欠账台账:26 勘误登记"},
    {"leg": "RT-E29", "key": "E29-G1:birth登记矛盾:%s" % (P_OBSDIR + "/OBS-D6-判据.md"),
     "desc": "文书面登记的 birth 值 19:46:13 / 00:54:45（重置前）与快照固化值 2026-11-01 17:36:53 "
             "矛盾（该件 §0 勘误登记已注明 birth 证据锚被 R1 写法重置、自此不作证据锚）",
     "upstream": "逃逸台账:253 RT-E29 / 阶段欠账台账:54"},
    {"leg": "RT-E29", "key": "E29-G1:birth登记矛盾:%s" % (P_OBSDIR + "/OBS-D6-整改判据-20261101.md"),
     "desc": "文书面登记的 birth 值 2026-11-01 01:57:41.730（改前实测）与快照固化值 "
             "2026-11-01 17:38:25 矛盾（改前留档 .bak 在盘）",
     "upstream": "阶段欠账台账:88 行⑥ / 阶段欠账台账:54"},
]


def write_snapshot(ws, out=sys.stdout):
    reg, err = load_registry(ws)
    if reg is None:
        out.write("FATAL: %s\n" % err)
        return 2
    snap_p = ws / P_SNAPSHOT
    rows = snapshot_rows(ws) or []
    prev = row_hash(rows[-1][1]) if rows else GENESIS
    seq = len(rows)
    snap_p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(snap_p, "a", encoding="utf-8") as f:
        for rel in reg.get("birth_files") or []:
            p = ws / rel
            if not p.is_file():
                out.write("  跳过（不在位）：%s\n" % rel)
                continue
            seq += 1
            st = os.stat(p)
            row = {
                "seq": seq,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "path": rel,
                "birth": birth_of(p),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                "ino": st.st_ino,
                "size": st.st_size,
                "sha256": sha256_file(p),
                "note": reg.get("birth_note", ""),
                "birth_reset": False,
            }
            row["prev_sha256"] = prev
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            prev = row_hash(row)
            n += 1
            out.write("  快照：seq=%d %s birth=%s\n" % (seq, rel, row["birth"]))
    out.write("SNAPSHOT_APPENDED: %d 行（append-only，历史行未改）\n" % n)
    return 0


def write_registry(ws, baseline, out=sys.stdout):
    reg_p = ws / P_REGISTRY
    reg = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "batch": "账本面对账门批-20261105",
        "note": "账本面对账门登记面（birth 快照件 + 未核基线 + M-2 坐标正本 + 已登记缺口）。"
                "改此件须留痕；registered_gaps 只增不减（删一条＝放行一个未登记缺口）。",
        "birth_files": DEFAULT_BIRTH_FILES,
        "birth_note": "RT-E29 birth 快照固化（2026-11-05 首锚）",
        "anchor_unverified_baseline": baseline,
        "m2_expected_coord": 28,
        "registered_gaps": DEFAULT_GAPS,
    }
    # ★ 合并保留：本登记面已被 B1 批（2026-11-05）扩展出四节（row_state_bindings /
    #   g5_clear_assertion / e110 / e27），--write-registry **不得**把它们抹掉
    #   （抹掉＝把三源化/行态绑定/横扫对账的登记面删了 ⇒ 门会当场判「未在册」红）。
    if reg_p.is_file():
        try:
            old = json.loads(read_text(reg_p))
        except Exception:
            old = {}
        for k in ("row_state_bindings", "g5_clear_assertion", "e110", "e27", "b1_batch"):
            if old.get(k) is not None and k not in reg:
                reg[k] = old[k]
        og = {g.get("key"): g for g in (old.get("registered_gaps") or []) if g.get("key")}
        ng = {g.get("key"): g for g in (reg.get("registered_gaps") or []) if g.get("key")}
        merged = list(ng.values())
        for k, g in og.items():
            if k not in ng:
                merged.append(g)
        reg["registered_gaps"] = merged
    reg_p.parent.mkdir(parents=True, exist_ok=True)
    reg_p.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.write("REGISTRY_WRITTEN: %s（未核基线=%s）\n" % (reg_p, baseline))
    return 0


# ---------------------------------------------------------------- 自测（自证会咬人）

SANDBOX_FILES = [
    P_TARGET, P_MAPPING, P_LEDGER, P_ESCAPE, P_DOC, P_ALARMS,
    P_OBSDIR + "/OBS-D1-判据.md",
    P_OBSDIR + "/OBS-D2-判据.md",
    P_OBSDIR + "/OBS-D3-判据.md",
    P_OBSDIR + "/OBS-D4-判据.md",
    P_OBSDIR + "/OBS-D4-判据.md.20261031-pre-RT.bak",
    P_OBSDIR + "/OBS-D6-判据.md",
    P_OBSDIR + "/OBS-D6-整改判据-20261101.md",
    P_SNAPSHOT, P_REGISTRY,
    # --- B1 批新增面（leg-E109 的校验命令件、leg-E111 的三源件）---
    P_WRITEBACK, P_MIGRECON, P_TECH_DEBT, P_TOTAL_TABLE,
]


def build_sandbox(ws, tmp):
    """造一份可判的沙箱盘面。

    · 核心件 copy2（保 mtime：leg-E101 依赖台账文件 mtime）；
    · 方法论文档的**锚目标件**一并复制（否则 anchor-check 在沙箱内把全部锚判缺件
      → --table 口径失真、leg-E92 的严格腿在沙箱里假红）；
    · 快照面**不复制、就地按沙箱实际 birth 重建**（copy 不保留 birth ⇒ 复制件 birth
      必然变 ⇒ 沿用真快照会让 leg-E29(c) 在对照组里假红；重建后对照绿、改写即红）。
    """
    sb = Path(tmp) / "ws"
    for rel in SANDBOX_FILES:
        src, dst = ws / rel, sb / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel == P_SNAPSHOT:
            dst.write_text("", encoding="utf-8")     # 快照面就地重建（见上）
        elif src.is_file():
            shutil.copy2(src, dst)
        else:
            dst.write_text("", encoding="utf-8")
    src_dir = ws / P_ANCHOR_DIR
    if src_dir.is_dir():
        shutil.copytree(src_dir, sb / P_ANCHOR_DIR, dirs_exist_ok=True)
    # 锚目标件：解析方法论文档全文的「路径:行」锚，把落在工作区内的目标复制进沙箱
    doc = ws / P_DOC
    if doc.is_file():
        text = read_text(doc)
        pat = (r"([A-Za-z0-9_一-鿿][\w./一-鿿-]*\.(?:md|py|sh|json|yaml|yml|jsonl|ts|txt|dwf))"
               r":(\d+)")
        for m in re.finditer(pat, text):
            rel = m.group(1)
            if rel.startswith("~") or rel.startswith("/"):
                continue
            src = ws / rel
            if not src.is_file() or rel in SANDBOX_FILES:
                continue
            dst = sb / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass
    # 快照面重建（按沙箱实际 birth 追加）
    reg, err = load_registry(sb)
    if reg is not None:
        with open(os.devnull, "w") as _dn:
            write_snapshot(sb, out=_dn)
    # ★ 沙箱基线归一（B1 批新增）：把真盘面「台账尚未补登」的 af-execline-idle
    #   ordinal 在**沙箱台账行**上补登（模拟「台账已补登」基线）⇒ 对照组不被
    #   事件驱动的台账补登义务污染（真盘面 leg-E101 会红，见证据文 §五；属非本批
    #   的实盘漂移：alarms.log 新增事件而台账未补登）。该腿的负例由夹具自造。
    led_p = sb / P_LEDGER
    if led_p.is_file() and (sb / P_ALARMS).is_file():
        lines = read_lines(led_p)
        for idx, l in enumerate(lines):
            if not l.startswith("| OBS-D4 |"):
                continue
            m = re.search(r"alarms\.log\s*(\d+)\s*条、末条\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|"
                          r"\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", l)
            if not m:
                break
            snap_n = int(m.group(1))
            exe = [e for e in (load_alarms(sb) or []) if e["code"] == "af-execline-idle"]
            registered = set(int(x) for x in re.findall(r"第\s*(\d+)\s*条", l))
            bm = re.search(r"起转入「(.+?)」", l)
            sig = bm.group(1) if bm else None
            flats = [int(a) for a, _b in re.findall(r"第\s*(\d+)(?:/(\d+))?\s*条起", l)]
            br_ord = min(flats) if flats else None
            unc = []
            for k, e in enumerate(exe, 1):
                if k in registered:
                    continue
                if k <= snap_n:
                    continue
                if sig and sig in e["msg"] and br_ord is not None and k >= br_ord:
                    continue
                unc.append(k)
            if unc:
                add = "；【沙箱基线补登】第 %s 条" % "、".join(str(x) for x in unc)
                if l.rstrip().endswith("|"):
                    lines[idx] = l.rstrip()[:-1].rstrip() + add + " |"
                else:
                    lines[idx] = l + add
            break
        led_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # ★ 三本账沙箱合成（D-148 批）：B/C 不复制真件（真 C 每 20 分钟随 ledger-sync 漂移，
    #   对照须确定性），由沙箱正本 A（含上方基线归一补登）派生——
    #   C＝A 的 P-04 全量投影（白名单投影夹具实装于对照）；
    #   B＝C 再退两步：撤尾两锚行（尾行滞后形态）＋撤一行行尾 append（前缀滞后形态）。
    a_p = sb / P_LEDGER
    if a_p.is_file():
        a_txt = read_text(a_p)
        c_p = sb / P_PLANC_SB_LEDGER
        c_p.parent.mkdir(parents=True, exist_ok=True)
        c_p.write_text(scrub_p04(a_txt), encoding="utf-8")
        blines = scrub_p04(a_txt).split("\n")
        aidx = [i for i, l in enumerate(blines) if l.startswith("|")]
        drop = set(aidx[-2:]) if len(aidx) >= 2 else set()
        blines = [l for i, l in enumerate(blines) if i not in drop]
        for i in reversed([i for i, l in enumerate(blines) if l.startswith("|")]):
            k = blines[i].rfind("〔")
            if k > 0:
                body = _tail_core(blines[i])
                blines[i] = body[:k].rstrip() + " |"
                break
        b_p = sb / P_REPO_LEDGER
        b_p.parent.mkdir(parents=True, exist_ok=True)
        b_p.write_text("\n".join(blines), encoding="utf-8")
    return sb


def selftest(ws, out=sys.stdout):
    cases = []
    tmp = tempfile.mkdtemp(prefix="ledger-face-recon-selftest.")
    try:
        sb = build_sandbox(ws, tmp)
        reg, err = load_registry(sb)
        if reg is None:
            out.write("SELFTEST_RESULT: FAIL（%s）\n" % err)
            return 1
        base = run_all(sb, reg)
        nb = report(base, reg, out)
        out.write("\n=== 对照组（未改动 ⇒ 应全绿）===\n")
        if nb[0] != 0 or nb[1] != 0:
            out.write("SELFTEST_RESULT: FAIL（对照组非全绿：红=%d 不可证=%d）\n" % nb)
            return 1
        out.write("对照组：%d 腿全绿 ✔\n" % len(base))

        def mutate(fn):
            t2 = tempfile.mkdtemp(prefix="ledger-face-recon-case.")
            sb2 = build_sandbox(ws, t2)
            fn(sb2)
            return sb2

        def leg_red(sb2, leg):
            r2, e2 = load_registry(sb2)
            if e2:
                return False
            for name, ok, red, gaps, _n in run_all(sb2, r2):
                if name != leg:
                    continue
                if ok is not True:
                    return False
                keys = registered_keys(r2)
                if any(g["key"] not in keys for g in gaps):
                    return True
                return bool(red)
            return False

        def leg_green(sb2, leg):
            """正控（D-148 批）：该腿须保持绿（白名单投影/滞后形态不得误红）。"""
            r2, e2 = load_registry(sb2)
            if e2:
                return False
            for name, ok, red, gaps, _n in run_all(sb2, r2):
                if name != leg:
                    continue
                if ok is not True:
                    return False
                keys = registered_keys(r2)
                return (not red) and all(g["key"] in keys for g in gaps)
            return False

        # ---- E76 负例：台账行标 ✅ 而映射判「未达」
        def m76(sb2):
            p = sb2 / P_TARGET
            lines = p.read_text(encoding="utf-8").splitlines()
            for i, l in enumerate(lines):
                if l.startswith("| G3 |"):
                    cells = table_cells(l)
                    cells[3] = "✅ 2026-11-05（夹具伪造）"
                    lines[i] = "| " + " | ".join(cells) + " |"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m76)
        cases.append(("E76 台账✅行↔映射判定不一致⇒红", lambda sb=sb2: leg_red(sb, "RT-E76")))

        # ---- E101 负例①：新增一条未登记的「判不准类」事件
        # 2026-11-09 夹具修复（D-148 批顺手修复·判据零改动）：OBS-D4 行的持续分支签名
        # 已扩长为「af 执行面空闲：无 af-order/af-execline 进程且…」，旧报文含签名前缀
        # ⇒ 被分支覆盖类吸收永不红；改为不含签名的判不准类报文，恢复负例咬合力。
        def m101a(sb2):
            p = sb2 / P_ALARMS
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": "2026-11-05 00:00:00", "level": "amber",
                                    "code": "af-execline-idle",
                                    "message": "夹具：判不准即报警类未登记事件（ledger 真值根"
                                               "读取失败复现形态·不含持续分支签名）"},
                                   ensure_ascii=False) + "\n")
        sb2 = mutate(m101a)
        cases.append(("E101 新增未登记事件⇒红", lambda sb=sb2: leg_red(sb, "RT-E101")))

        # ---- E101 负例②：登记值与现值矛盾
        def m101b(sb2):
            p = sb2 / P_LEDGER
            p.write_text(p.read_text(encoding="utf-8").replace(
                "alarms.log 107 条、末条 10-31 18:53:37",
                "alarms.log 106 条、末条 10-31 18:53:37"), encoding="utf-8")
        sb2 = mutate(m101b)
        cases.append(("E101 登记值与现值矛盾⇒红", lambda sb=sb2: leg_red(sb, "RT-E101")))

        # ---- E92 负例：M-2 锚坐标漂到第三处（未登记缺口形状变化）
        def m92(sb2):
            p = sb2 / P_DOC
            lines = p.read_text(encoding="utf-8").splitlines()
            for i, l in enumerate(lines):
                if l.startswith("| M-2 |"):
                    lines[i] = l.replace("目的-监测项映射.md:29", "目的-监测项映射.md:30")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m92)
        cases.append(("E92 M-2 锚坐标漂移⇒红（未登记缺口）", lambda sb=sb2: leg_red(sb, "RT-E92")))

        # ---- E92 负例②：§7 期望串条目被摘除（内容核验面失效）
        def m92b(sb2):
            p = sb2 / P_DOC
            lines = p.read_text(encoding="utf-8").splitlines()
            for i, l in enumerate(lines):
                if l.startswith("| 11 |") and "目的-监测项映射.md" in l:
                    lines[i] = "| 11 | （夹具：期望串条目被摘除） | — | — |"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m92b)
        cases.append(("E92 §7 期望串面被摘⇒红", lambda sb=sb2: leg_red(sb, "RT-E92")))

        # ---- E29 负例①：快照行被改（链断）
        def m29(sb2):
            p = sb2 / P_SNAPSHOT
            lines = p.read_text(encoding="utf-8").splitlines()
            if lines:
                lines[0] = lines[0].replace('"birth":', '"birth": "2000-01-01 00:00:00.000000000 +0800", "x":')
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m29)
        cases.append(("E29 快照行被改⇒红（链断）", lambda sb=sb2: leg_red(sb, "RT-E29")))

        # ---- E29 负例②：判据件 birth 被重置且无勘误登记
        # 重置机制＝编辑器整文件替换写法（临时文件 + rename）——这正是逃逸台账 RT-E29
        # 记载的真实成因（"整文件替换写法（临时文件+rename）"）；原地 write_text 不改
        # birth，必须用 rename 形态才复现真实漂移。
        def m29b(sb2):
            p = sb2 / (P_OBSDIR + "/OBS-D1-判据.md")
            tmp = p.with_name(p.name + ".tmpfix")
            tmp.write_text(p.read_text(encoding="utf-8") + "\n<!-- 夹具改写：重置 birth -->\n",
                           encoding="utf-8")
            os.replace(str(tmp), str(p))
        sb2 = mutate(m29b)
        cases.append(("E29 birth 重置未勘误⇒红", lambda sb=sb2: leg_red(sb, "RT-E29")))

        # ---- E27 负例①：新增判据件未登记（对照名单不全）
        def m27(sb2):
            shutil.copy2(sb2 / (P_OBSDIR + "/OBS-D1-判据.md"),
                         sb2 / (P_OBSDIR + "/OBS-D7-判据.md"))
        sb2 = mutate(m27)
        cases.append(("E27 判据全集多出未登记件⇒红", lambda sb=sb2: leg_red(sb, "RT-E27")))

        # ---- E27 负例②：某件判据件的时序登记被全部摘除（对照名单被摘）
        # 该件的登记散落在多处载体（D6 §0 的对照名单、D4 §0 的同批对照、D6整改 §0、
        # 台账行）⇒ 只删一处仍被别处覆盖，必须把所有载体上的登记行一并抹掉才复现
        # 「时序无文书登记」的原始形态。
        def m27b(sb2):
            targets = sorted((sb2 / P_OBSDIR).glob("*.md")) + [sb2 / P_LEDGER]
            for p in targets:
                lines = p.read_text(encoding="utf-8").splitlines()
                out = []
                for l in lines:
                    if (re.search(r"OBS-D4(?![0-9])", l) and any(w in l for w in SEQ_WORDS)
                            and BIRTHVAL_RE.search(l)):
                        out.append("> （夹具：本行时序登记被删）")
                    else:
                        out.append(l)
                p.write_text("\n".join(out) + "\n", encoding="utf-8")
        sb2 = mutate(m27b)
        cases.append(("E27 时序登记被摘除⇒红", lambda sb=sb2: leg_red(sb, "RT-E27")))

        # ================= B1 批（2026-11-05）新增负例 =================
        # ---- E109 负例①：台账登记读数称绿而实跑为红（假绿面）
        def m109a(sb2):
            p = sb2 / P_LEDGER
            txt = p.read_text(encoding="utf-8")
            old = "exit=1「writeback-check: 裁决行 12 条（登记回写 3，未登记 9），红 9 条」"
            new = "exit=0「writeback-check: 裁决行 13 条（登记回写 13，未登记 0），红 0 条」"
            if old not in txt:
                raise AssertionError("夹具前提失效：台账 RT-PP3 行未找到登记读数串")
            p.write_text(txt.replace(old, new), encoding="utf-8")
            stub = sb2 / P_WRITEBACK
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "# 夹具替身：模拟 writeback 门报红（判据面受控模拟）\n"
                "import sys\n"
                "print('writeback-check: 裁决行 14 条（登记回写 14，未登记 0），红 4 条')\n"
                "sys.exit(1)\n", encoding="utf-8")
        sb2 = mutate(m109a)
        cases.append(("E109 台账登记读数称绿而实跑为红⇒红（假绿面）",
                      lambda sb=sb2: leg_red(sb, "RT-E109")))

        # ---- E109 负例②：行态验证命令绑定缺失（状态列无机读命令与登记读数）
        def m109b(sb2):
            p = sb2 / P_LEDGER
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, l in enumerate(lines):
                if l.startswith("| RT-PP3 |"):
                    cells = table_cells(l)
                    cells[-1] = "✅ 2026-11-05（夹具：删除机读校验命令与登记读数）"
                    lines[i] = "| " + " | ".join(cells) + " |"
                    hit = True
            if not hit:
                raise AssertionError("夹具前提失效：台账无 RT-PP3 行")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m109b)
        cases.append(("E109 行态验证命令绑定缺失⇒红", lambda sb=sb2: leg_red(sb, "RT-E109")))

        # ---- E109 负例③：下游引用对账（台账行态与被引面声明不一致）
        # 2026-11-09 夹具修复（D-148 批顺手修复·判据零改动）：RT-PP3 末格已翻 ✅（2026-11-06
        # 核销回写），旧夹具替换「部分（」成空操作永不红；改为末格首状态符号外科翻转
        # （仅动 1 字符，行字节布局不变），制造「台账行态 ≠ 被引面声明」的真实分叉。
        def m109c(sb2):
            p = sb2 / P_LEDGER
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, l in enumerate(lines):
                if not l.startswith("| RT-PP3 |"):
                    continue
                idx, esc = [], False
                for ci, ch in enumerate(l):
                    if esc:
                        esc = False
                        continue
                    if ch == "\\":
                        esc = True
                        continue
                    if ch == "|":
                        idx.append(ci)
                if not idx:
                    raise AssertionError("夹具前提失效：RT-PP3 行无竖线")
                j = idx[-1]
                cell = l[j + 1:]          # 末格（状态列）＝最后未转义竖线后至行尾（行可无收尾 |）
                ms = re.match(r"\s*([✅❌🔄])", cell)
                if not ms:
                    raise AssertionError("夹具前提失效：RT-PP3 末格首部无状态符号")
                flipped = "❌" if ms.group(1) == "✅" else "✅"
                lines[i] = l[:j + 1] + cell[:ms.start(1)] + flipped + cell[ms.end(1):]
                hit = True
            if not hit:
                raise AssertionError("夹具前提失效：台账无 RT-PP3 行")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m109c)
        cases.append(("E109 下游引用行态不一致⇒红", lambda sb=sb2: leg_red(sb, "RT-E109")))

        # ---- E110 负例①：✅ 行同格含自认未达措辞（同格矛盾）
        def m110a(sb2):
            p = sb2 / P_TARGET
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, l in enumerate(lines):
                if l.startswith("| G7 |"):
                    cells = table_cells(l)
                    cells[3] = cells[3] + "（夹具：巡检接线腿未施工）"
                    lines[i] = "| " + " | ".join(cells) + " |"
                    hit = True
            if not hit:
                raise AssertionError("夹具前提失效：系统目标台账无 G7 行")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m110a)
        cases.append(("E110 ✅行同格矛盾⇒红", lambda sb=sb2: leg_red(sb, "RT-E110")))

        # ---- E110 负例②：汇总行「G1-G10 全绿」失去否定/勘误标记
        def m110b(sb2):
            p = sb2 / P_TARGET
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, l in enumerate(lines):
                if l.startswith("| G11 |"):
                    for w in ("勘误", "勘正", "否定", "已被", "不成立"):
                        l = l.replace(w, "曾")
                    lines[i] = l
                    hit = True
            if not hit:
                raise AssertionError("夹具前提失效：系统目标台账无 G11 行")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m110b)
        cases.append(("E110 汇总引用失去否定标记⇒红", lambda sb=sb2: leg_red(sb, "RT-E110")))

        # ---- E111 负例①：G5 行状态列改 ✅ 而多源仍有未清零项（假绿面）
        def m111a(sb2):
            p = sb2 / P_TARGET
            lines = p.read_text(encoding="utf-8").splitlines()
            hit = False
            for i, l in enumerate(lines):
                if l.startswith("| G5 |"):
                    cells = table_cells(l)
                    cells[3] = "✅ 2026-11-05（夹具伪造：G5 声称清零留证）"
                    lines[i] = "| " + " | ".join(cells) + " |"
                    hit = True
            if not hit:
                raise AssertionError("夹具前提失效：系统目标台账无 G5 行")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sb2 = mutate(m111a)
        cases.append(("E111 G5 声称清零而多源未清零⇒红（假绿面）",
                      lambda sb=sb2: leg_red(sb, "RT-E111")))

        # ---- E92 加严负例：全量口径（常驻门口径）下 §7 期望串面失效
        def m92c(sb2):
            p = sb2 / P_MAPPING
            txt = p.read_text(encoding="utf-8")
            old = "| G9 | 台账:15 | 方法论文档锚点全可解析"
            new = "| G9 | 台账:15 | 夹具改写：期望串已不命中"
            if old not in txt:
                raise AssertionError("夹具前提失效：映射件无 G9 期望串行")
            p.write_text(txt.replace(old, new), encoding="utf-8")
        sb2 = mutate(m92c)
        cases.append(("E92 全量口径期望串面失效⇒红", lambda sb=sb2: leg_red(sb, "RT-E92")))

        # ---- E29 加严负例：判据件内容漂移而快照面未更新（sha256 对账）
        def m29c(sb2):
            p = sb2 / (P_OBSDIR + "/OBS-D1-判据.md")
            p.write_text(p.read_text(encoding="utf-8")
                         + "\n<!-- 夹具：内容漂移（快照面未更新） -->\n", encoding="utf-8")
        sb2 = mutate(m29c)
        cases.append(("E29 内容漂移而快照面未更新⇒红", lambda sb=sb2: leg_red(sb, "RT-E29")))

        # ---- E27 加严负例：自称「判据先行」的件其时序更正声明被摘
        def m27c(sb2):
            p = sb2 / (P_OBSDIR + "/OBS-D4-判据.md")
            txt = p.read_text(encoding="utf-8")
            for w in ("预注册状态声明", "时序更正声明", "事后补写", "事后追认",
                      "不是预注册判据面", "时序声明"):
                txt = txt.replace(w, "〔夹具：自述被摘〕")   # 替换串本身不得含任何声明词
            p.write_text(txt, encoding="utf-8")
        sb2 = mutate(m27c)
        cases.append(("E27 自称判据先行但时序声明被摘⇒红", lambda sb=sb2: leg_red(sb, "RT-E27")))

        # ================= D-148 批（2026-11-09 wave-17）三向逐行 diff 夹具 =================
        # ---- D-148 负例①：仓本 B 中段行内联改写（非投影·非前缀滞后）⇒ 必红
        def m148a(sb2):
            p = sb2 / P_REPO_LEDGER
            lines = p.read_text(encoding="utf-8").split("\n")
            hit = False
            for i, l in enumerate(lines):
                if l.startswith("|") and len(l) > 120:
                    lines[i] = l[:80] + "（夹具：中段行内联改写）" + l[80:]
                    hit = True
                    break
            if not hit:
                raise AssertionError("夹具前提失效：沙箱仓本无长锚行")
            p.write_text("\n".join(lines), encoding="utf-8")
        sb2 = mutate(m148a)
        cases.append(("D-148 仓本中段行内联改写⇒红（归因点名 A↔B）",
                      lambda sb=sb2: leg_red(sb, "D-148")))

        # ---- D-148 负例②：规划环 C 投影不可逆（标记↔异地址）⇒ 必红（白名单窄门证明）
        def m148b(sb2):
            p = sb2 / P_PLANC_SB_LEDGER
            txt = p.read_text(encoding="utf-8")
            if P04_MARK not in txt:
                raise AssertionError("夹具前提失效：沙箱规划环无 P-04 投影（正本无内网地址字面）")
            p.write_text(txt.replace(P04_MARK, "10.99.99.99", 1), encoding="utf-8")
        sb2 = mutate(m148b)
        cases.append(("D-148 投影不可逆（脱敏标记↔异内网地址）⇒红（非白名单）",
                      lambda sb=sb2: leg_red(sb, "D-148")))

        # ---- D-148 负例③：仓本 B 中段整锚行蒸发（非尾行滞后形态）⇒ 必红
        def m148c(sb2):
            p = sb2 / P_REPO_LEDGER
            lines = p.read_text(encoding="utf-8").split("\n")
            aidx = [i for i, l in enumerate(lines) if l.startswith("|")]
            if len(aidx) < 8:
                raise AssertionError("夹具前提失效：沙箱仓本锚行不足")
            k = aidx[4]                      # 第 5 条锚行＝中段（远离文件尾）
            del lines[k]
            p.write_text("\n".join(lines), encoding="utf-8")
        sb2 = mutate(m148c)
        cases.append(("D-148 仓本中段整锚行蒸发⇒红（append-only 破坏形态）",
                      lambda sb=sb2: leg_red(sb, "D-148")))

        # ---- D-148 负例④：仓本 B 状态格首符号翻转（中段分叉·非前缀滞后）⇒ 必红
        def m148d(sb2):
            p = sb2 / P_REPO_LEDGER
            lines = p.read_text(encoding="utf-8").split("\n")
            hit = False
            for i, l in enumerate(lines):
                if not l.startswith("|") or ("✅" not in l and "❌" not in l):
                    continue
                lines[i] = l.replace("✅", "❌", 1) if "✅" in l else l.replace("❌", "✅", 1)
                hit = True
                break
            if not hit:
                raise AssertionError("夹具前提失效：沙箱仓本无状态符号行")
            p.write_text("\n".join(lines), encoding="utf-8")
        sb2 = mutate(m148d)
        cases.append(("D-148 仓本状态格首符号翻转⇒红（同步在途窗外分叉）",
                      lambda sb=sb2: leg_red(sb, "D-148")))

        # ---- D-148 正控①：新增一处合法 P-04 投影（A 加地址·C 同位加标记）⇒ 必不红
        def m148p(sb2):
            pa = sb2 / P_LEDGER
            pc = sb2 / P_PLANC_SB_LEDGER
            la = pa.read_text(encoding="utf-8").split("\n")
            lc = pc.read_text(encoding="utf-8").split("\n")
            hit = False
            for i in range(min(len(la), len(lc))):
                if (la[i] == lc[i] and la[i].startswith("|") and len(la[i]) > 100
                        and not la[i].startswith("| OBS-D4 |")
                        and not la[i].startswith("| RT-PP3 |")):
                    la[i] = _tail_core(la[i]) + "（探针坐标 10.20.30.40 夹具） |"
                    lc[i] = _tail_core(lc[i]) + "（探针坐标 %s 夹具） |" % P04_MARK
                    hit = True
                    break
            if not hit:
                raise AssertionError("夹具前提失效：沙箱无 A/C 同文长锚行")
            pa.write_text("\n".join(la), encoding="utf-8")
            pc.write_text("\n".join(lc), encoding="utf-8")
        sb2 = mutate(m148p)
        cases.append(("D-148 合法 P-04 投影同位增量⇒不红（白名单归因正控）",
                      lambda sb=sb2: leg_green(sb, "D-148")))

        # ---- D-148 正控②：滞后形态加深（再撤 B 三尾行＋再撤一行行尾 append）⇒ 必不红
        def m148q(sb2):
            p = sb2 / P_REPO_LEDGER
            lines = p.read_text(encoding="utf-8").split("\n")
            aidx = [i for i, l in enumerate(lines) if l.startswith("|")]
            if len(aidx) < 6:
                raise AssertionError("夹具前提失效：沙箱仓本锚行不足")
            drop = set(aidx[-3:])
            lines = [l for i, l in enumerate(lines) if i not in drop]
            for i in reversed([i for i, l in enumerate(lines) if l.startswith("|")]):
                k = lines[i].rfind("〔")
                if k > 0:
                    body = _tail_core(lines[i])
                    lines[i] = body[:k].rstrip() + " |"
                    break
            p.write_text("\n".join(lines), encoding="utf-8")
        sb2 = mutate(m148q)
        cases.append(("D-148 滞后形态加深（尾行/行尾 append）⇒不红（归因 D-123 不并吞正控）",
                      lambda sb=sb2: leg_green(sb, "D-148")))

        out.write("\n=== 逐笔「自证会咬人」夹具（负例 ⇒ 必红；正控 ⇒ 必不红）===\n")
        nfail = 0
        for name, fn in cases:
            try:
                ok = fn()
            except Exception as e:  # noqa: BLE001
                ok = False
                out.write("  [FAIL] %s（自测执行错：%s）\n" % (name, e))
            if ok:
                out.write("  [OK  ] %s ✔\n" % name)
            else:
                nfail += 1
                out.write("  [FAIL] %s ✘（未如判）\n" % name)
        if nfail:
            out.write("SELFTEST_RESULT: FAIL（%d 例未如判）\n" % nfail)
            return 1
        out.write("SELFTEST_RESULT: PASS（对照组全绿 ＋ %d 例负例/正控全如判）\n" % len(cases))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ws", default=None)
    ap.add_argument("--leg", action="append", default=None,
                    help="只跑指定腿（可重复；腿名如 RT-E76 / D-148；缺省=全腿）")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--write-registry", action="store_true")
    ap.add_argument("--baseline", type=int, default=None)
    a = ap.parse_args(argv)
    ws = Path(a.ws).resolve() if a.ws else DEF_WS
    if a.selftest:
        return selftest(ws)
    if a.write_registry:
        return write_registry(ws, a.baseline if a.baseline is not None else 0)
    if a.snapshot:
        return write_snapshot(ws)
    all_legs = ("RT-E76", "RT-E101", "RT-E92", "RT-E29", "RT-E27",
                "RT-E109", "RT-E110", "RT-E111", "D-148")
    want = list(dict.fromkeys(a.leg)) if a.leg else list(all_legs)
    bad = [w for w in want if w not in all_legs]
    if bad:
        print("结论：参数错 —— 未知腿名 %s（在役腿：%s）" % ("、".join(bad), "、".join(all_legs)))
        return 2
    print("=== 账本面对账门（九腿：%s）===" % "、".join(all_legs))
    print("工作区：%s｜本次跑腿：%s" % (ws, "、".join(want)))
    reg = None
    reg_legs = {"RT-E92", "RT-E29", "RT-E109", "RT-E110", "RT-E111", "RT-E27"}
    if any(w in reg_legs for w in want):
        reg, err = load_registry(ws)
        if reg is None:
            print("结论：不可证 —— %s（fail-closed，不猜绿）" % err)
            return 2
    res = run_all(ws, reg, only=want)
    nred, ninf = report(res, reg)
    if ninf:
        print("结论：不可证（%d 腿）——缺件/坏件 fail-closed，不猜绿" % ninf)
        return 2
    if nred:
        print("结论：红（%d 腿有红项，见上）" % nred)
        return 1
    print("结论：绿（%d 腿全绿；已登记缺口见各腿「已登记缺口」行——账实未清，勿读作已消）" % len(res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
