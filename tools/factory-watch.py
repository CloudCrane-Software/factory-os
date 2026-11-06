#!/usr/bin/env python3
"""factory-watch.py — 黑灯工厂可观测中心（本机半边）：watchdog 守护 + 安灯分级 + 看板数据源。

定位：只读观测，不启动/不重启任何执行面组件。调度器（factory-scheduler.py）与 anolis 侧
      由别的角色负责；本脚本负责"看得见"：聚合 bench 结果、探活调度器、巡检 anolis、
      解析中继失败，并按安灯规则产出分级报警。

两种模式:
  factory-watch.py --once   # 单轮扫描，stdout 打印人类可读巡检报告（另刷新 latest.json/data.json）
  factory-watch.py          # 常驻：每 60s 一轮；写 状态观测/latest.json（机器可读全量快照）、
                            #   追加 状态观测/alarms.log（报警流水，同种报警 30 分钟内不重复记）、
                            #   每轮刷新 状态/看板/data.json（看板静态页的数据源）
环境变量:
  AF_WATCH_EXTRA_DIRS       # 逗号分隔的第二产线观测清单（目录 glob=额外面臂 tier=F2；
                            #   .json=额外调度器状态，配对同名 -graph.json 解析臂 out 映射），
                            #   如 "/tmp/bench-fix2-rerun-*,/tmp/factory2-status.json"

安灯规则（level / code / 触发条件，实现见 build_alarms()）:
  red   A0  调度器死/状态停更（状态文件缺失、mtime>2400s，或进程连续 2 轮不在；
            DEB57-A0 2026-11-02 判活面改读现役状态根 状态观测/factory-scheduler-state.json）
  red   A1  任一臂末态 run_failed 占比>10%（≥5 题；任务级口径：按 task_id 取
            results.jsonl 末行，重试救回的 attempt 不计——2026-10-22 修，修前
            行级口径把"曾经失败过的尝试"计成"现在仍失败"（实证 D1/D2-step-5
            行级 13/17 → 末态 0，四臂全误报）；与②组 mcode 官方线"78 任务有
            重复行、71 是 None+judged 混合、必须 last-row 口径"同源同坑）
            （归档豁免：results.jsonl mtime>6h 且无关联在跑进程的终态臂跳过不报，
            安灯节汇总一行 [已归档臂]——慢性信号不再每轮复报，归档依据见巡检日志）
  red   A2  任一臂末态零补丁（reward 为 None 且非 run_failed）占比>30%（≥10 题；
            同 A1 任务级口径。不用 gate 判零补丁：实证 gate=no_patch 行里有
            reward=true（启发式误判），reward/status 才是判分事实）
            （同 A1 归档豁免；行级零补丁/gate 拦截降为诊断信息行，不再触发红灯）
  amber A3  某档案 ≥10 题已判分且通过数为 0
  amber A4  anolis 任一巡检分区（/data、/）使用率>85%
  amber A4L 本机 /tmp 可用 <2662MiB（usrquota 校准线 2.6GiB，D-24；statvfs 盘点失败
            同码报「/tmp 盘点失败（fail-closed）」与写满文案强制区分；2252MiB 闸线
            之下 factory-sched/mcode-dispatch 已自动拦新臂/新判分，安灯提前叫人）
  red   A4W  本机 /tmp 写即失败（2026-11-02 RT 收尾 DEB57 增：真写 1MiB 探针）。
            A4L 量的是 statvfs f_bavail＝全机剩余空间那一本账，量不到 tmpfs 每用户
            配额（usrquota）那一本账——2026-11-02 10:37 实测 f_bavail 报 1012MiB
            「可用」，同刻 1MiB 写即 OSError 122 Disk quota exceeded（/home 同刻
            可写）。A4L 文案只承诺「拦新臂/新判分」，本灯覆盖「写即失败」：落 /tmp
            的门件（kb/verify.py 快照 sqlite backup）当场 disk I/O error 硬红。
            与 A4L 并存不互斥（低水=提前叫人；写不进=当场坏）。
  amber A5  factory.log 尾部中继（relay）连续失败 ≥3（中间无一次 ok）
  amber A6  调度器认为 running 的 bench 臂 30 分钟无新 results 行
            （豁免：该臂 out 目录 runs/ 最新子目录 10 分钟内有写入——慢任务
            GLM/kimi 单题 30-60 分钟属正常，results 行只在整题收尾时落盘）
  amber A7  本机 sweb.eval 镜像唯一任务数<120 且连续 2 小时无新增
            （口径与 tools/local-image-feed.py 盘点一致：docker images 里
            swebench/sweb.eval.x86_64.<task> 去重仓库数；anolis 上的 relay
            镜像池另巡检上报，但不参与 A7——2026-10-22 前数的是 anolis 池，
            与 feed 进度无关，实证为误报来源）
  red   A8  gov 公网门户（jobs.hkmingdajiaoyu.com 宿主 gov-host.invalid:8090，在役
            裸进程）三签名任一失败：①/healthz 非 200 或响应体非 {"ok":true}；
            ②/tasks.json?status=open&limit=1 信封不可解析（进程在但数据面死）；
            ③在役进程 environ 缺 AF_JOBS_DATA（2026-11-02 09:00 板面全零事故
            根因签名——该形态下 ①② 照样全绿，alarms.log 全窗零门户条目，
            详见 计划/变更日志.md:40794）。发布链（L5 deploy 门）与 keepalive
            自愈（portal 看护对象）之外，本灯=门户可用性的常驻告警面。
  red   A9  活性安灯腿失活（风险#7 收口批 2026-11-04 新增臂；**只增，既有臂判定
            一律不动**）：安灯判据文件 状态观测/trigger-inbox-liveness.json 由
            tools/event-router.py::_trigger_liveness_andon 每轮重写＝报活心跳；
            判据文件超 3600s 未重写 ⇒ 安灯腿本身没在跑（比 amber 更严重的一档：
            amber=安灯在跑但收件箱静默；stale=安灯腿死了）；判据文件不在位同理。
            **读到旧判据不得报 green**——「把陈旧判据当成活」正是 268h 静默前科的
            失败形态。与 event-router 自写的 trigger-inbox-silent 摘要行**不同码
            不同义**（那行=安灯在跑但收件箱静默；本行=安灯腿本身失活），不重复记。
  一次性 amber bench-arm-vanished  某臂目录消失（exists=false）：臂态显式化为
            三态之一（在跑/退役/缺失，见 classify_arm_states），**禁以 0 冒充
            在案**——n_total=0 对缺失臂是"无数据"不是"零失败"。每个消失
            episode 只报一次（首见即报、记入 watch-state 不再复报；臂复活后
            再次消失算新 episode 重报）；持续缺失 ≥ARM_RETIRE_AFTER_S 天转
            retired 态（panel 标记），不再复报。
            （D-112/factory-os#80，夜轨C2 红队分诊 H4：18 臂 exists=false
            全零 + scheduler alive=true、alarms 仅 A4/A7 amber——人无法分辨
            退役 vs 死了；本灯+三态字段即收口该盲区）
  red   A10  /data 停手线触顶后恢复动作腿（D-113，夜轨C2 红队分诊 H3；**只增，
            既有臂判定一律不动**）：img-gc 停手线（≥88%）触顶后，tools/img-gc.py
            产「可 GC 候选清单+预估回收量」**只读报告件**（img-gc-evidence.jsonl
            kind=recovery 行，code=gc-recovery）；本灯把该读数抬进安灯+latest.json。
            判据：末条 recovery 证据 tier∈{L1,L2,L3}，或末次 apply 为停手线回报
            却无 recovery 证据（D-113 之前的旧形态＝触顶后零自动恢复动作）。
            H3 实录：354 行证据里 197 条 apply 仅 2 条 ok=true、峰值 use_pct=100
            （2026-11-04 13:30:57，HALT 拒绝），11-06 gc-watch 红 ×17。
  amber A11  /data 回落无留痕（D-113）：现值低于「末次成功 apply 之后的未解释
            峰值」≥5pp，且该落差不能由成功 apply 的事后水位解释 ⇒ 回落来源既非
            img-gc 路径亦无 recovery 证据行，须人工核定并登记。一次性/episode：
            每个未解释峰值只报一次（闩锁落 watch-state），chronic 真相由快照
            gc_recovery 段每轮承载。H3 实录：93%→70% 回落零留痕。

容错：bench-fix1-* 目录尚未生成/工厂重启后空目录/结果行有空行或坏 JSON（逐行
      try/except 跳过并计数 n_bad_lines，不整文件失败、不漏坏行之后的所有行——
      2026-10-22 修，实测 D1-mavis-m31f 有 1 行写截断）/anolis ssh 不通/
      调度器从未运行——全部不崩，按 0 或 ok:false 呈现。密钥零明文（本脚本不碰密钥）。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SAMPLE = f"{WS}/计划/s1-swev-120.json"          # D1/D2/D3 分母来源（读取用绝对路径）
SAMPLE_REL = "计划/s1-swev-120.json"            # P0-2 根治（2026-10-28）：发布面 plan.file 只写相对
                                                # 路径——原绝对路径双命中 O-03（/home/ 路径+用户名），
                                                # 经无闸推送链每分钟带上公网（publish-gate.md §1.7 两轨
                                                # 处置之根治轨；页面/工具无消费方解析该字段，实查零引用）
# DEB57-A0（2026-11-02）：判活面改读现役调度器状态根。旧值 /tmp/factory-status.json 是
# 已退役链（tools/factory-sched.py）的根，文件早已不在盘——watch 据此把在役
# factory-scheduler.py 判成「状态文件缺失」打 A0 假红（alarms.log 累计 267 条）且
# alive=false 上公网看板；真死/真停更时该灯已红且归「已退役预期灯」，测不出其目的。
# 现役状态文件=tools/factory-scheduler.py:154 STATE（每轮 60s 落盘，round_once 末尾写）。
SCHED_STATUS = f"{WS}/状态观测/factory-scheduler-state.json"
SCHED_LOG = "/tmp/factory.log"                  # 调度器日志（中继失败解析）
GRAPH = "/tmp/factory-graph.json"               # 调度图（读 bench 臂 out 目录映射）

OBS_DIR = f"{WS}/状态观测"
LATEST = f"{OBS_DIR}/latest.json"
ALARMS_LOG = f"{OBS_DIR}/alarms.log"
STATE_FILE = f"{OBS_DIR}/watch-state.json"
DASH_DIR = f"{WS}/状态/看板"
DASH_DATA = f"{DASH_DIR}/data.json"

INTERVAL = 60                # 常驻轮询周期（s）
DEDUP_WINDOW = 1800          # 同种报警 30 分钟内不重复记（s）
SCHED_STALE_S = 2400         # 状态文件 mtime 超此值 → A0（DEB57-A0 2026-11-02 由 300 改
                             # 2400：现役 factory-scheduler 单轮含 anolis/gov 多路 ssh，
                             # 实测 round 间隔 p99=784s/max=1258s、7.4% 轮次>300s（近 3 天
                             # 119 轮）——300 阈必假红抖动；2400 与 keepalive scheduler
                             # 判活线同值（factory-keepalive.py LOCAL_GUARDS stale_s=2400），
                             # 两个监督面共用一套世界模型）
RUNNING_STALL_S = 1800       # running 臂无新结果行 → A6
RUNS_FRESH_S = 600           # runs/ 最新子目录 10 分钟内有写入 → A6 豁免（慢任务在跑）
IMG_STALL_S = 7200           # 镜像数停滞判定窗 → A7
IMAGE_TARGET = 120
ARCHIVE_MATURITY_S = 6 * 3600  # results.jsonl mtime 超此龄且无关联在跑进程 → 臂归档（A1/A2 免报）
RELAY_FAIL_MIN = 3           # 连败阈值 → A5
# ---- D-112（factory-os#80，夜轨C2 红队分诊 H4）：bench 臂退役态显式化 ----
# 缺口实录（2026-11-07 分诊复核留证）：anolis /tmp/bench-fix1-* 0 目录（ssh
# 实测）；公网 /static/data.json 与本地 状态/看板/data.json 均照常呈现 18 臂
# exists=false 全零 + scheduler alive=true，alarms 仅 A4/A7 amber——**人无法
# 分辨退役 vs 死了**（目录消失被渲染成与"在案但零产出"完全同形的全零行），
# 且消失时长无独立记录（逐臂时刻不可证：memory-readings 无 bench-fix1 行；
# 旁证=bench-infra-retired-20261029 清单+旧链 /tmp 日志末次 mtime 10-21~10-24，
# 量级 14.7-17 天，但不可独立复算）。
# 收口三件（只增不改，全部落在 data.json 生成侧=本文件；判据/判官件零改动）：
#   ① 臂态三态字段 arm_state（running/retired/missing，见 classify_arm_states）
#      ——独立字段进 data.json arms[]（发布面顶层键集冻结不受影响：DATA_TOP
#      只钉顶层，臂级新键不入冻结集）；
#   ② 一次性告警码 bench-arm-vanished（每个消失 episode 只报一次）；
#   ③ scheduler alive 摘要与臂态解耦呈现（render_report 显式声明 alive≠臂在案）。
ARM_VANISH_CODE = "bench-arm-vanished"   # 一次性告警码（卡面正本命名；任务转述
                                         # "arm_missing" 即此码——臂缺失显式态）
ARM_RETIRE_AFTER_S = 14 * 86400          # exists=false 持续 ≥14 天 → retired 态
# N=14 天取值依据：红队分诊实测消失量级 14.7-17 天（旁证）；与厂内 14 天归档
# 惯例同值（D-116 sunset-audit --days 14 缺省）。<14 天保持 missing（新近消失，
# 告警/epilogue 仍认）；≥14 天转 retired（慢性，panel 标记）。时钟起点=watch
# **首次显式观测到缺失**的时刻（记入 watch-state.json arm_missing_seen）——
# 历史消失时刻不可证（分诊留证），不拿 last_new_row_age 之类间接信号倒推伪造
# 消失时刻；末次新结果行年龄仍以既有 last_new_row_age_s 字段原样呈现（下界
# 参照，非消失时刻）。
# A4L 本机 /tmp 安灯线（D-24，patch-tmpfs-alarm-watch-A4L-R2 / 方案 P1-1）：/tmp=
# 7.5G tmpfs+usrquota，与判分结果/任务 json/调度器三件套共居；EDQUOT 实测于仅余
# ~1.7G（mes500-根因报告.md:42）。校准线 2662MiB≈2.6GiB=factory-sched tmpfs 闸 WARN；
# 闸线 2252MiB≈2.2GiB=factory-sched tmpfs_gate / mcode-dispatch probe_tmpfs 的
# CLOSE——低于它自动拦新，安灯负责在闸线之前叫人。
A4L_TMP_WARN_MB = 2662
A4L_TMP_GATE_MB = 2252
# ---- D-113（factory-os#81，夜轨C2 红队分诊 H3）：/data 水位恢复腿 + 回落留痕 ----
# 缺口实录（卡面复核留证，2026-11-07 分诊，全部命令重跑留证）：
#   img-gc-evidence.jsonl 354 行、峰值 use_pct=100（2026-11-04 13:30:57，reason=HALT
#   哨兵在场拒绝执行）；11-06 gc-alarm-sent 红 ×17，末条 message「删 0 张/rmi-fail 0，
#   /data 93%→None%，reason=use_pct 93% ≥ 停手线 88%，只 plan 停手回报」——
#   **停手线触顶后零自动恢复动作**（197 条 apply 仅 2 条 ok=true，全在 10-22）；
#   现值 /data 69-70%（anolis `df -P /data` 实测）而 93%→70% 回落无任何 img-gc/
#   安灯留痕。/data=订单生产真值根（/data/bench/af-p3-state/orders 末条
#   A0897-report-glm-cp mtime 2026-11-05 23:17:03 实测）。
# 收口（只增不改，全部落在本文件安灯/快照侧；判据/判官件零改动）：
#   ① A10：停手线触顶后 img-gc.py 产「可 GC 候选清单+预估回收量」只读报告件
#      （kind=recovery 证据行，code=gc-recovery）——本件把它抬进安灯+latest.json；
#   ② A11：/data 回落（非 img-gc 路径）留痕灯——回落不能由成功 apply 解释即报。
GC_EVIDENCE = f"{WS}/状态观测/img-gc-evidence.jsonl"   # img-gc 双写耐久件（与 keepalive 同源）
GC_RECOVERY_CODE = "gc-recovery"                       # 停手线恢复腿专码（A10）
GC_FALLBACK_CODE = "gc-recovery-fallback-untraced"     # 回落无留痕专码（A11）
GC_PEAK_WINDOW_S = 7 * 86400        # 峰值回看窗（与 img-gc warm-cache TTL 同源 7 天）
GC_FALLBACK_MIN_DROP_PP = 5         # 回落幅度阈（百分点；<此值视为正常抖动）
GC_FALLBACK_LATCH_KEY = "gc_fallback_reported_peak"    # watch-state 闩锁键（一次性/episode）
# img-gc 停手线（apply 现场复核 use_pct≥此值即只 plan 停手回报；第二道闸）——
# 与 tools/img-gc.py STOP_PCT 同值。本件只读消费该口径，不另设闸。
STOP_LINE_PCT = 88
# A4W 本机 /tmp 实际写入门径（2026-11-02 RT 收尾 DEB57）：A4L 量的是 statvfs
# f_bavail——「全机剩余空间」那一本账；实际拒绝写入的是 tmpfs 每用户配额
# （usrquota）那一本账，两本账不是一本。2026-11-02 10:37 实测：f_bavail 报
# 1012MiB「可用」，同刻 1MiB 写即 OSError 122 Disk quota exceeded（/home 同刻
# WRITE OK）——statvfs 报的数字好看，写真实文件时已被拒。
# 本机不推算配额余量（quotactl 对 tmpfs 返回 EINVAL，7.0.0-38 内核实测），直接
# 真写 1MiB 试门径：写不进＝写即失败，这是唯一权威判据（statvfs 永远给不出）。
A4W_PROBE_BYTES = 1 << 20      # 1MiB 写探针（<50MB 短命件，D-24 /tmp 白名单内）
A4W_PROBE_DIR = "/tmp"         # 被探目录（可被单测/沙箱改指）

# ---------- ⑦ 活性安灯聚合段（风险#7 收口批 2026-11-04；只增新段，既有臂不动） ----------
# 安灯本体（**写入方**）= tools/event-router.py::_trigger_liveness_andon()：
# 每轮重写判据文件 状态观测/trigger-inbox-liveness.json（重写＝报活心跳）
# + 告警面 状态观测/alarms.log 摘要行（跃迁必写 + 6h 刷新）。
# 本段**只读**判据文件（绝不写它——写入方是 event-router 消费腿），
# 把安灯读数抬进机器可读全量快照 状态观测/latest.json：
# 此前快照里没有安灯读数（本文件 grep "trigger|liveness" 命中 0），
# 安灯响了没有任何机器可读面把它抬起来——这正是 268h 静默前科的结构性成因。
# ★ 陈旧即失活：安灯腿没在跑 ⇒ 判据文件不再被重写 ⇒ mtime 陈旧。
#   这**比 amber 更严重**一档（amber＝安灯在跑但收件箱静默；stale＝安灯腿本身死了）。
#   **读到旧文件不得报 green**——「把陈旧判据当成活」正是 268h 那次的失败形态。
TRIGGER_LIVENESS_FILE = f"{OBS_DIR}/trigger-inbox-liveness.json"
# ★ 形态A/形态B 判据文件（写入方=tools/factory-keepalive.py 判据行④，**不是**本件）：
#   状态观测/trigger-inbox-source-silent.json —— 收件箱**进程态 + 源头断供**的机器可读读数。
#   与上面那份 trigger-inbox-liveness.json（写入方=event-router 安灯本体）**同机制、
#   不同文件、不互相覆盖**：前者答「收件箱进程在不在 + 源头断没断供」（形态A/B 分码），
#   后者答「安灯腿在不在跑 + 投递活性」。
# 本批（2026-11-05 发布面接线批 ①P4）把**形态B 读数**接进机器可读聚合面
# （此前 latest.json 的 trigger_liveness 段只含路由侧那一份 ⇒ 新码抬不起来）。
TRIGGER_SOURCE_SILENT_FILE = f"{OBS_DIR}/trigger-inbox-source-silent.json"
# 陈旧阈 3600s（1h）：与 tools/live-daemon-version-probe.py 的 router stale_s=3600
# 同一世界模型（router 判活线同值）；实测依据——router 主循环 INTERVAL=60s
# （tools/event-router.py:74），但一轮会逐个 ssh 拉 gov 回报（poll_verify_reports），
# 2026-11-04 实测在役轮长 >12min（17:21:38 那轮至 17:34 仍未收尾）⇒ 1h ≈ 实测
# 最坏轮长的 5 倍余量（不误红），且 1h ≪ 268h 前科尺度（静默类失活在 1h 内被抬起）。
TRIGGER_LIVENESS_STALE_S = 3600
ROUTER_STOP_FILE = f"{WS}/kb-seed/sandbox/.router-STOP"   # router 主循环熔断（STOP 在位时安灯按设计停报）

PROFILES = ["glm-cp", "glm-cp-max", "kimi-k3", "step-5", "qwen30b-local", "mavis-m31f"]
TIERS = ["D1", "D2", "D3"]
# 与 tools/factory-sched.py EXISTING_DIRS 保持一致（fix1 代目录；bench-s1-* 已作废不扫）
ARMS = {}
for _t in TIERS:
    _lo = _t.lower()
    ARMS[(_t, "glm-cp")] = f"/tmp/bench-fix1-{_lo}-glm-cp"
    ARMS[(_t, "glm-cp-max")] = f"/tmp/bench-fix1-{_lo}-glm-max"
    ARMS[(_t, "kimi-k3")] = f"/tmp/bench-fix1-{_lo}-kimi"
    ARMS[(_t, "step-5")] = f"/tmp/bench-fix1-{_lo}-step5"
    ARMS[(_t, "qwen30b-local")] = f"/tmp/bench-fix1-{_lo}-30b"
    ARMS[(_t, "mavis-m31f")] = f"/tmp/bench-fix1-{_lo}-m31f"

# status 字段里可判定为"零补丁"的取值（判不准的不计入，只按 status/reward 如实统计）
ZERO_PATCH_STATUSES = {"no_patch", "empty_patch", "zero_patch", "no_diff", "patch_empty"}

# ---------- 第二产线（实验线）观测 ----------
# AF_WATCH_EXTRA_DIRS：逗号分隔。含通配符的条目按目录 glob 展开为额外面臂（tier=F2，
# profile=目录名去掉 bench-fix2-rerun- 前缀）；.json 条目视为额外调度器状态文件
# （自动配对同名 -graph.json 以解析运行臂 → out 目录映射与 F2 目标题数）。
# 缺省空 = 只观测主产线（行为与引入前完全一致）。
EXTRA_DIRS_SPEC = os.environ.get("AF_WATCH_EXTRA_DIRS", "")


def parse_extra(spec):
    arm_dirs, statuses = [], []
    for ent in [x.strip() for x in spec.split(",") if x.strip()]:
        if any(c in ent for c in "*?["):
            arm_dirs.extend(sorted(p for p in glob.glob(ent) if os.path.isdir(p)))
        elif ent.endswith(".json"):
            statuses.append(ent)
    return arm_dirs, statuses


EXTRA_ARM_DIRS, EXTRA_STATUS_FILES = parse_extra(EXTRA_DIRS_SPEC)
EXTRA_GRAPHS = {s: s.replace("-status.json", "-graph.json") for s in EXTRA_STATUS_FILES}


def extra_profile(path):
    name = os.path.basename(path)
    return name[len("bench-fix2-rerun-"):] if name.startswith("bench-fix2-rerun-") else name


def now_s():
    return time.strftime("%F %T")


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---- P0-2 发布面脱敏（2026-10-28）：data.json 是公网发布物（factory-status-push
# 每分钟推 gov static/data.json），自由文本值须过 K/O 正则族再落盘。真源单一：
# tools/stream-tailer.py SCRUB_RULES（importlib 按路径加载，不复制正则——P1-4 方向）。
# 本地运维面（latest.json / alarms.log）保留原文，不脱敏。
_scrub_fn = None
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "af_stream_tailer_scrub", os.path.join(WS, "tools", "stream-tailer.py"))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _scrub_fn = _mod.scrub
except Exception:  # noqa: BLE001 —— 真源加载失败=显式降级：发布面拒绝写自由文本（见下）
    _scrub_fn = None


def scrub_public(o):
    """递归重写字符串值（键不动——键集冻结由 gate 校验）。真源缺失时抛异常，
    由调用方降级为保留上一版 data.json（宁可停更不可泄密）。"""
    if _scrub_fn is None:
        raise RuntimeError("scrub 真源（stream-tailer.py SCRUB_RULES）加载失败")
    if isinstance(o, str):
        return _scrub_fn(o)[0]
    if isinstance(o, list):
        return [scrub_public(x) for x in o]
    if isinstance(o, dict):
        return {k: scrub_public(v) for k, v in o.items()}
    return o


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------- 内部状态（吞吐/停滞判定用，仅常驻模式推进） ----------

def load_state():
    st = load_json(STATE_FILE, {})
    st.setdefault("line_hist", [])       # [[epoch, {dir: 行数}], ...] 保留 40min
    st.setdefault("last_increase", {})   # {dir: epoch} 该目录最近一次行数增长时刻
    st.setdefault("first_running", {})   # {node_id: epoch} 首次见到该节点 running
    st.setdefault("sweb_img_hist", [])   # [[epoch, 本机 sweb.eval 唯一任务数], ...] 保留 ~3h（A7 口径）
    st.pop("img_hist", None)             # 2026-10-22：A7 口径由 anolis SSH 计数改本机 feed 盘点，旧历史作废
    st.setdefault("alarm_open", {})      # {key: epoch} 报警条件首次持续出现时刻
    st.setdefault("alarm_logged", {})    # {key: epoch} 上次写入 alarms.log 时刻
    # D-112：{dir: epoch} watch 首次显式观测到该臂目录缺失的时刻（三态时钟+
    # 一次性 bench-arm-vanished 的 episode 判据；臂复活即除，再消失算新 episode）
    st.setdefault("arm_missing_seen", {})
    st.setdefault("proc_miss_streak", 0)
    # D-113：{peak_epoch} 已报过「/data 回落无留痕」的未解释峰值（一次性/episode
    # 闩锁；新峰值出现即重报）。0=从未报过。
    st.setdefault(GC_FALLBACK_LATCH_KEY, 0)
    return st


def save_state(st):
    try:
        write_atomic(STATE_FILE, json.dumps(st, ensure_ascii=False))
    except Exception:
        pass  # 状态写失败不影响观测主流程


def rows_10m(line_hist, path, cur_count, t):
    """最近 ~10 分钟新增行数：取 9-11 分钟前最近的采样做基线；无基线则取最老采样。"""
    base = None
    window = [s for s in line_hist if t - 660 <= s[0] <= t - 480]
    if window:
        base = window[-1]
    elif line_hist:
        base = line_hist[0]
    if base is None:
        return 0
    return max(0, cur_count - base[1].get(path, 0))


def runs_recent_mtime(arm_dir):
    """该臂 out/runs/ 最新子目录的最后活动时刻（epoch）；无 runs/ 或异常返回 None。

    取"最新子目录自身 mtime"与"其内直接文件最大 mtime"的较大者：长生成期
    只追加写单个文件（如 effects.db-wal）时目录 mtime 不动，须看文件级才能
    真实反映"任务还在跑"。
    """
    runs = os.path.join(arm_dir, "runs")
    try:
        subs = [e for e in os.scandir(runs) if e.is_dir()]
        if not subs:
            return None
        newest = max(subs, key=lambda e: e.stat().st_mtime)
        mt = newest.stat().st_mtime
        for f in os.scandir(newest.path):
            try:
                mt = max(mt, f.stat().st_mtime)
            except OSError:
                continue
        return mt
    except OSError:
        return None


# ---------- ① bench 结果聚合 ----------

def scan_arm(path):
    st = {
        "dir": path, "exists": os.path.isdir(path),
        "n_total": 0, "n_reward_true": 0, "n_completed_not_reward": 0,
        "n_run_failed": 0, "n_blocked": 0,
        # 任务级（末行口径，A1/A2 判定用，2026-10-22 修）：按 task_id 取末行
        "n_tasks": 0, "task_run_failed": 0, "task_zero_patch": 0,
        "n_bad_lines": 0,          # 坏行计数（JSON 解析/解码失败，逐行跳过）
        "sum_turns": 0, "n_turns": 0,
        "sum_tin": 0, "sum_tout": 0, "sum_tcache": 0, "n_tokens": 0,
        "sum_wall_ms": 0, "n_wall": 0,
        "judged_tasks": 0, "resolved_tasks": 0,
        "res_mtime": None,          # results.jsonl mtime（epoch）；终态臂归档判定用
    }
    if not st["exists"]:
        return st
    res = os.path.join(path, "results.jsonl")
    try:
        st["res_mtime"] = os.stat(res).st_mtime
    except OSError:
        st["res_mtime"] = None
    last_by_task = {}
    any_reward = set()
    try:
        # 二进制逐行读 + 逐行 try/except：坏行（写截断/编码坏字节）跳过并计数，
        # 不整文件失败、不漏掉坏行之后的所有行（2026-10-22 修；D1-m31f 实测 1 行）
        with open(res, "rb") as f:
            for raw in f:
                try:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    r = json.loads(line)
                except Exception:
                    st["n_bad_lines"] += 1
                    continue
                if not isinstance(r, dict):
                    continue
                st["n_total"] += 1
                if r.get("reward") is True:
                    st["n_reward_true"] += 1
                status = r.get("status")
                if status == "completed" and r.get("reward") is not True:
                    st["n_completed_not_reward"] += 1
                if status == "run_failed":
                    st["n_run_failed"] += 1
                gate = r.get("gate")
                if (gate is not None and gate != "ok") or \
                   (gate is None and status in ZERO_PATCH_STATUSES):
                    st["n_blocked"] += 1
                turns = r.get("turns")
                if isinstance(turns, (int, float)):
                    st["sum_turns"] += turns
                    st["n_turns"] += 1
                tok = r.get("tokens") if isinstance(r.get("tokens"), dict) else {}
                if tok:
                    st["sum_tin"] += tok.get("input") or 0
                    st["sum_tout"] += tok.get("output") or 0
                    st["sum_tcache"] += tok.get("cache_read") or 0
                    st["n_tokens"] += 1
                wall = r.get("agent_wall_ms")
                if isinstance(wall, (int, float)):
                    st["sum_wall_ms"] += wall
                    st["n_wall"] += 1
                task = r.get("task_id") or r.get("case_id")
                if task:
                    last_by_task[task] = r  # append 语义：后行覆盖前行
                    if r.get("reward") is True:
                        any_reward.add(task)
    except FileNotFoundError:
        st["exists"] = False
        return st
    # 任务级末行口径（A1/A2 判定，2026-10-22 修）：last_by_task 即 append 序末行
    st["n_tasks"] = len(last_by_task)
    st["task_run_failed"] = sum(
        1 for r in last_by_task.values() if r.get("status") == "run_failed")
    # 末态零补丁：判分事实 reward=None（未解决/未判到）且末行非 run_failed。
    # 不用 gate 判零补丁——实证 gate=no_patch 行里有 reward=true（启发式误判）。
    st["task_zero_patch"] = sum(
        1 for r in last_by_task.values()
        if r.get("reward") is None and r.get("status") != "run_failed")
    st["judged_tasks"] = sum(
        1 for r in last_by_task.values()
        if r.get("reward") is not None or r.get("status") not in (None, "run_failed"))
    st["resolved_tasks"] = len(any_reward)
    return st


def scan_all_arms(state, t):
    hist = state["line_hist"]
    spec = [(tier, prof, ARMS[(tier, prof)]) for tier in TIERS for prof in PROFILES]
    spec += [("F2", extra_profile(d), d) for d in EXTRA_ARM_DIRS]
    arms = []
    for tier, prof, path in spec:
        a = scan_arm(path)
        cnt = a["n_total"]
        if a["exists"]:
            prev = hist[-1][1].get(path, 0) if hist else 0
            if cnt > prev:
                state["last_increase"][path] = t
            elif path not in state["last_increase"]:
                state["last_increase"][path] = t
        a["tier"] = tier
        a["profile"] = prof
        a["rows_10m"] = rows_10m(hist, path, cnt, t) if hist else 0
        li = state["last_increase"].get(path)
        a["last_new_row_age_s"] = int(t - li) if li else None
        arms.append(a)
    return arms


def scan_plan_tiers():
    """各难度档题数（分母）。计划文件缺失/坏 → 全 0，不崩。"""
    tiers = {}
    sample = load_json(SAMPLE, None)
    if isinstance(sample, list):
        for it in sample:
            if isinstance(it, dict) and it.get("tier") in TIERS:
                tiers[it["tier"]] = tiers.get(it["tier"], 0) + 1
    for t in TIERS:
        tiers.setdefault(t, 0)
    return tiers


# ---------- ② 调度器活性 ----------

def node_arm_dir(nid):
    base = nid[:-3] if nid.endswith("-w1") else nid
    m = re.match(r"arm-d([123])-(.+)$", base)
    if not m:
        return None
    return ARMS.get(("D" + m.group(1), m.group(2)))


def scan_scheduler(state, t):
    out = {"status_file_exists": os.path.exists(SCHED_STATUS),
           "mtime_age_s": None, "pids": [], "alive": False,
           "summary": None, "running_arms": [], "error": None}
    try:
        out["mtime_age_s"] = int(t - os.stat(SCHED_STATUS).st_mtime)
    except FileNotFoundError:
        pass
    except Exception as e:
        out["error"] = str(e)
    try:
        # DEB57-A0（2026-11-02）：进程名改现役 factory-scheduler.py——旧 pattern
        # "factory-sched.py" 是退役进程名，正则不命中 factory-scheduler.py（"factory-sched"
        # 后随 "uler.py"），pgrep 永远扑空 → alive 恒 false。
        r = subprocess.run(["pgrep", "-f", "factory-scheduler.py"],
                           capture_output=True, text=True, timeout=15)
        pids = []
        for x in r.stdout.split():
            try:
                with open(f"/proc/{x}/cmdline", "rb") as f:
                    argv0 = f.read().split(b"\0")[0].decode("utf-8", "replace")
                # 只认 python3 进程本体，排除启动它的 bash 包装命令行
                if os.path.basename(argv0).startswith("python"):
                    pids.append(int(x))
            except Exception:
                continue
        out["pids"] = pids
    except Exception as e:
        out["error"] = out["error"] or str(e)
    proc_up = bool(out["pids"])
    state["proc_miss_streak"] = 0 if proc_up else state.get("proc_miss_streak", 0) + 1
    proc_confirmed_down = state["proc_miss_streak"] >= 2  # 2 轮确认，避免重启窗口误报
    mtime_stale = out["mtime_age_s"] is None or out["mtime_age_s"] > SCHED_STALE_S
    out["alive"] = proc_up and not mtime_stale
    out["proc_confirmed_down"] = proc_confirmed_down
    out["mtime_stale"] = mtime_stale

    stt = load_json(SCHED_STATUS, None)
    if isinstance(stt, dict):
        out["summary"] = stt.get("_summary")
        for nid, n in stt.items():
            if nid == "_summary" or not isinstance(n, dict):
                continue
            if n.get("kind") == "bench-arm" and n.get("state") == "running":
                out["running_arms"].append({"node": nid, "dir": node_arm_dir(nid)})
    return out


def scan_extra_schedulers(t):
    """第二产线调度器（EXTRA_STATUS_FILES）：只读观测——活性看状态文件 mtime，
    运行臂 out 目录从配对 -graph.json 的 params 解析。"""
    out = []
    for sp in EXTRA_STATUS_FILES:
        e = {"status": sp, "exists": os.path.exists(sp), "mtime_age_s": None,
             "summary": None, "running_arms": []}
        try:
            e["mtime_age_s"] = int(t - os.stat(sp).st_mtime)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        gparams = {}
        gp = EXTRA_GRAPHS.get(sp)
        if gp:
            g = load_json(gp, None)
            if isinstance(g, dict):
                gparams = {n.get("id"): n.get("params", {})
                           for n in g.get("nodes", []) if isinstance(n, dict)}
        stt = load_json(sp, None)
        if isinstance(stt, dict):
            e["summary"] = stt.get("_summary")
            for nid, n in stt.items():
                if nid == "_summary" or not isinstance(n, dict):
                    continue
                if n.get("kind") == "bench-arm" and n.get("state") == "running":
                    d = (gparams.get(nid) or {}).get("out") or node_arm_dir(nid)
                    e["running_arms"].append({"node": nid, "dir": d})
        out.append(e)
    return out


def extra_f2_target():
    """F2 实验线目标题数（配对 graph 里 bench-arm tasks 数之和；图缺则按已见目录数×1）。"""
    total = 0
    for sp in EXTRA_STATUS_FILES:
        gp = EXTRA_GRAPHS.get(sp)
        g = load_json(gp, None) if gp else None
        if isinstance(g, dict):
            total += sum(len((n.get("params") or {}).get("tasks", []))
                         for n in g.get("nodes", [])
                         if isinstance(n, dict) and n.get("kind") == "bench-arm")
    return total


# ---------- ③ anolis 巡检 ----------

ANOLIS_CMD = (
    "df -P /data / 2>/dev/null; "
    "echo ---; docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -c 'sweb.eval'; "
    "echo ---; curl -s -m 5 http://127.0.0.1:11434/api/tags 2>/dev/null | head -c 2000; "
    "echo; echo ---; cat /proc/loadavg 2>/dev/null"
)


def scan_anolis(state, t):
    out = {"ok": False, "disk": {}, "sweb_images": None, "image_target": IMAGE_TARGET,
           "ollama": "unknown", "load": None, "error": None}
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            "anolis", ANOLIS_CMD],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            out["error"] = (r.stderr or "").strip().splitlines()[-1:] or f"rc={r.returncode}"
            out["error"] = out["error"][0] if out["error"] else f"rc={r.returncode}"
            return out
        parts = [p.strip("\n") for p in r.stdout.split("\n---\n")]
        if len(parts) >= 4:
            for line in parts[0].splitlines():
                f_ = line.split()
                if len(f_) >= 5 and f_[0].startswith("/dev/"):
                    out["disk"][f_[5]] = {"use_pct": int(f_[4].rstrip("%")),
                                          "size": f_[1], "used": f_[2], "avail": f_[3]}
            cnt_s = parts[1].strip().splitlines()[-1].strip() if parts[1].strip() else ""
            out["sweb_images"] = int(cnt_s) if cnt_s.isdigit() else None
            tags = parts[2].strip()
            out["ollama"] = "ok" if '"models"' in tags else "down"
            la = parts[3].strip().split()
            if len(la) >= 3:
                out["load"] = {"m1": float(la[0]), "m5": float(la[1]), "m15": float(la[2])}
            out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
    return out


def scan_local_images(state, t):
    """本机 sweb.eval 镜像唯一任务数（A7 口径，与 tools/local-image-feed.py 盘点一致）。

    数法：docker images 的 Repository 列取 swebench/sweb.eval.x86_64.<task> 前缀的
    去重集合大小——同任务多 tag/重复 tag 不重复计，与 feed"已就位 120/120"同源同口径。
    2026-10-22 前 A7 数的是 anolis SSH 口径（anolis 的 relay 镜像池，67/120 与本机
    feed 进度无关），已实证为误报来源；anolis 池仍巡检上报，但不再参与 A7 停滞判定。
    docker 不可用/超时/非零退出 → None（本轮不判定、不写历史）。
    """
    try:
        r = subprocess.run(["docker", "images", "--format", "{{.Repository}}"],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    prefix = "swebench/sweb.eval.x86_64."
    n = len({ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith(prefix)})
    hist = state["sweb_img_hist"]
    hist.append([t, n])
    state["sweb_img_hist"] = [s for s in hist if t - s[0] <= IMG_STALL_S + 600]
    return n


# ---------- ③-b D-113 /data 恢复腿与回落留痕判据（只读 img-gc 耐久证据） ----------

def read_gc_recovery_state(now):
    """读 img-gc 耐久证据，产出 /data 水位恢复腿与回落留痕判据（**只读**）。

    返回 dict（缺文件/坏行 ⇒ 各字段 None，fail-closed：不明不报绿也不假红）：
      last_apply     末条 apply 记录（epoch/ok/use_pct/use_pct_after/reason）
      last_recovery  末条 kind=recovery 记录（D-113 恢复腿读数）
      baseline_pct   末次**成功** apply 的 use_pct_after（成功 GC 的事后水位）
      peak_pct/peak_epoch  窗内 use_pct 峰值（**仅统计末次成功 apply 之后**的记录——
                     成功 GC 已把该次水位解释掉，不能再算进「未解释的峰值」）
      （回落判据不在此函数内裁决——由 gc_recovery_alarm_inputs 纯函数判，
        避免「 reader 里算一半、arm 里算一半」两处口径漂移）

    峰值窗 GC_PEAK_WINDOW_S 之外的记录不参与（远古峰值不驱动当期告警）。
    """
    out = {"last_apply": None, "last_recovery": None, "baseline_pct": None,
           "peak_pct": None, "peak_epoch": None,
           "n_records": 0, "read_err": None, "stop_line_hits": 0}
    try:
        with open(GC_EVIDENCE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return out                      # 无 GC 历史：不报绿也不假红
    except Exception as e:
        out["read_err"] = f"{type(e).__name__}: {e}"
        return out

    recs = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if isinstance(r, dict):
            recs.append(r)
    out["n_records"] = len(recs)

    # 第一遍：末条 apply / 末次成功 apply（baseline）/ 停手线命中计数
    last_success_epoch = 0.0
    for r in recs:
        ep = r.get("epoch") or 0
        if r.get("kind") == "apply":
            prev = out["last_apply"] or {}
            if ep >= (prev.get("epoch") or 0):
                out["last_apply"] = {
                    "epoch": ep, "ts": r.get("ts"), "ok": bool(r.get("ok")),
                    "use_pct": r.get("use_pct"), "use_pct_after": r.get("use_pct_after"),
                    "reason": r.get("reason"), "deleted": r.get("deleted")}
            if r.get("ok") and ep >= last_success_epoch:
                last_success_epoch = ep
                out["baseline_pct"] = r.get("use_pct_after")
            if "停手线" in str(r.get("reason") or ""):
                out["stop_line_hits"] += 1
        elif r.get("kind") == "recovery":
            prev = out["last_recovery"] or {}
            if ep >= (prev.get("epoch") or 0):
                out["last_recovery"] = {
                    "epoch": ep, "ts": r.get("ts"), "tier": r.get("tier"),
                    "use_pct": r.get("use_pct"), "L1_n": r.get("L1_n"),
                    "L1_est_reclaim_bytes": r.get("L1_est_reclaim_bytes"),
                    "L2_n": r.get("L2_n"), "report_path": r.get("report_path"),
                    "auto_delete": r.get("auto_delete")}

    # 第二遍：未解释峰值 = 末次成功 apply 之后的记录里的 use_pct 最大值
    for r in recs:
        if r.get("kind") not in ("apply", "plan"):
            continue
        ep = r.get("epoch") or 0
        if ep <= last_success_epoch or now - ep > GC_PEAK_WINDOW_S:
            continue
        p = r.get("use_pct")
        if isinstance(p, int) and (out["peak_pct"] is None or p > out["peak_pct"]):
            out["peak_pct"], out["peak_epoch"] = p, ep
    return out


def gc_recovery_alarm_inputs(gc, cur_pct, t):
    """D-113 两腿判据（纯函数，便于夹具自检）。返回 dict：

      a10 / a10_why   停手线触顶后恢复动作腿（red）
      a11 / a11_why   /data 回落无留痕（amber）
      stop_active     停手线**当前**是否算触顶（现值≥停手线，或窗内刚被停手线拒过）

    A10 是**活条件**而非永久红：停手线触顶（现值≥88 或窗内刚被拒）时，若恢复腿
    未对该次触顶产出分级档位（L1/L2/L3）即报红；触顶过去且恢复腿确有档位读数则不报
    （避免「水已退、红灯常亮」的告警疲劳——chronic 真相由快照 gc_recovery 段承载）。
    """
    out = {"a10": False, "a10_why": "", "a11": False, "a11_why": "",
           "stop_active": False}
    if not gc:
        out["a10_why"] = out["a11_why"] = "gc 判据缺席（fail-closed：不报绿也不假红）"
        return out
    la = gc.get("last_apply") or {}
    lr = gc.get("last_recovery") or {}
    stop_hit = bool(la.get("reason") and "停手线" in str(la.get("reason"))
                    and not la.get("ok"))
    fresh_hit = stop_hit and (t - (la.get("epoch") or 0)) <= GC_PEAK_WINDOW_S
    live_hit = isinstance(cur_pct, int) and cur_pct >= STOP_LINE_PCT
    out["stop_active"] = bool(fresh_hit or live_hit)
    leg_responded = bool(lr.get("tier") in ("L1", "L2", "L3")
                         and (lr.get("epoch") or 0) >= (la.get("epoch") or 0))
    if out["stop_active"] and not leg_responded:
        out["a10"] = True
        if lr.get("tier") is None and lr.get("epoch"):
            out["a10_why"] = (f"恢复腿已跑但档位=None（use_pct={lr.get('use_pct')}"
                              f"<停手线 {STOP_LINE_PCT}%，常水位不启动）——对本次触顶"
                              f"未产出 L1/L2/L3 分级档位")
        elif not lr.get("epoch"):
            out["a10_why"] = ("**无 kind=recovery 证据行**——恢复腿未启动或未落码"
                              "（D-113 之前的旧形态：触顶后零自动恢复动作）")
        else:
            out["a10_why"] = f"恢复腿档位不可识别：{lr.get('tier')!r}"
    elif leg_responded:
        out["a10"] = True
        out["a10_why"] = (f"恢复腿档位 {lr.get('tier')}（use_pct={lr.get('use_pct')}，"
                          f"L1 候选 {lr.get('L1_n')} 项/预估回收 "
                          f"{lr.get('L1_est_reclaim_bytes')}B）")
    else:
        out["a10_why"] = "停手线未触顶（现值<停手线且窗内无停手线回报）——A10 不判"
    peak = gc.get("peak_pct")
    if peak is not None and isinstance(cur_pct, int) \
            and peak - cur_pct >= GC_FALLBACK_MIN_DROP_PP:
        out["a11"] = True
        out["a11_why"] = (
            f"未解释峰值 {peak}%"
            f"（{time.strftime('%F %T', time.localtime(gc.get('peak_epoch') or 0))}）"
            f"→ 现值 {cur_pct}%，落差 {peak - cur_pct}pp ≥{GC_FALLBACK_MIN_DROP_PP}pp，"
            f"且末次成功 apply 事后水位 {gc.get('baseline_pct')}% 不解释该落差")
    else:
        out["a11"] = False
        out["a11_why"] = (f"回落可由成功 apply 解释（baseline={gc.get('baseline_pct')}%）"
                          f"或落差 <{GC_FALLBACK_MIN_DROP_PP}pp")
    return out


# ---------- ④ 中继连败解析 ----------
RELAY_END_RE = re.compile(r"\] 结束 (relay-\S+): (ok|FAILED\S*)")


def scan_relay():
    out = {"consecutive_failures": 0, "last_event": None}
    try:
        with open(SCHED_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200000))
            tail = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        out["last_event"] = "factory.log 不存在"
        return out
    except Exception as e:
        out["last_event"] = f"读取失败: {e}"
        return out
    events = [(m.group(1), m.group(2), line.strip())
              for line in tail.splitlines()
              if (m := RELAY_END_RE.search(line))]
    if not events:
        out["last_event"] = "日志尾部暂无 relay 结束事件"
        return out
    cutoff = time.time() - 1800  # 30min 窗：更旧的结局不计入连败（2026-10-21 教训：
    # 图内 relay 清零后不会再有新事件，历史连败尾巴会让 A5 永久常亮 = 告警疲劳）
    for name, verdict, line in reversed(events):  # 从最新往回数连败（尾部连败才触发 A5）
        out["last_event"] = line
        m_ts = re.match(r"\[([\d\-]+ [\d:]+)\]", line)
        if m_ts:
            try:
                if time.mktime(time.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")) < cutoff:
                    break
            except ValueError:
                pass
        if verdict == "ok":
            break
        out["consecutive_failures"] += 1
    return out


# ---------- ⑤ gov 公网门户巡检（A8 数据源，2026-11-02 RT 收口） ----------
# 背景：门户在 gov 宿主是裸进程（PPID=1，无 systemd/supervisor），watch 原无门户
# 探针——2026-11-02 09:00 板面全零事故（门户重启未带 AF_JOBS_DATA，板面空转
# 20+min）在 alarms.log 全窗零门户条目，是纯告警盲区。本巡检只读（处置=keepalive
# 同批新增的 portal 看护对象，factory-keepalive.py PORTAL_* 段），三签名任一败
# → A8 红：①healthz 非 {"ok":true}；②/tasks.json 瘦信封不可解析（进程在但数据
# 面死）；③在役进程 environ 缺 AF_JOBS_DATA——③是 11-02 事故根因签名，该形态
# 下 ①② 照样全绿（wrong-data-dir 只让板面变空，进程照常应答）。探针走 origin
# 直连（factory-kb-worker.py PORTAL 同址），公网链路（反代/CDN）不在本灯量纲；
# ssh 不可达时 ③=unknown：HTTP 面照常裁决，不把「验证手段断」当「被测面死」。
PORTAL_HEALTH_URL = "http://gov-host.invalid:8090/healthz"
PORTAL_TASKS_URL = "http://gov-host.invalid:8090/tasks.json?status=open&limit=1"
PORTAL_SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "root@gov-host.invalid"]
PORTAL_HTTP_TIMEOUT = 8    # curl --max-time（DEB-1 双超时纪律的外层帽见 _portal_http）
PORTAL_SSH_TIMEOUT = 15
# 在役进程 env 读数（与 factory-keepalive.py portal_env_state 同口径双写，
# 两文件互不 import——keepalive 顶层带 otel 装载副作用，watch 不引入；
# 同 smith 先例：factory-scheduler/factory-status-push 各自持有同口径 _mes_event）。
# pid 遴选必须过 argv0==python3 过滤：pgrep -f 的 [p] 括号法只防 pgrep 自匹配，
# 防不了「重启命令的残留 bash 包装壳」（2026-11-02 18:30 实证：gov 上
# `-bash -c '…nohup python3 af-jobs-portal.py…'` 包装壳 cmdline 含同款子串、
# 无 AF_JOBS_* env，head -1 会选中它 → env 误读 MISSING → 对健康门户误判红）。
PORTAL_ENV_SH = r'''
pid=""
for p in $(pgrep -f '[p]ython3 af-jobs-portal.py' 2>/dev/null); do
  a0="$(tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | head -1)"
  if [ "$a0" = "python3" ]; then pid="$p"; break; fi
done
if [ -z "$pid" ]; then
  echo "NOPROC"
elif tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -q '^AF_JOBS_DATA='; then
  echo "OK pid=$pid"
else
  echo "MISSING pid=$pid"
fi
'''


def _portal_http(url):
    """门户 GET 探针（curl --max-time + subprocess 双超时，DEB-1 纪律同
    factory-scheduler _portal_open_count）。返回 (rc, body)；异常路径 rc=124
    （curl 超时码同款语义），不抛出。"""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(PORTAL_HTTP_TIMEOUT), url],
                           capture_output=True, text=True,
                           timeout=PORTAL_HTTP_TIMEOUT + 7)
        return r.returncode, (r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""


def _portal_env_state():
    """③ 进程 env 签名：gov 在役 af-jobs-portal 进程 environ 是否含 AF_JOBS_DATA=。
    返回 (st, why)：st ∈ {"ok","missing","unknown"}——ssh 不可达/读数不可识别
    =unknown（判不准不假报）；NOPROC=missing（进程不在时 ①② 亦必败，方向一致）。"""
    try:
        r = subprocess.run(PORTAL_SSH + [PORTAL_ENV_SH], capture_output=True,
                           text=True, timeout=PORTAL_SSH_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "unknown", f"ssh 读 env 失败（{type(e).__name__}）"
    if r.returncode != 0:
        return "unknown", f"ssh rc={r.returncode}"
    lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
    line = lines[-1] if lines else ""
    if line.startswith("OK"):
        return "ok", line
    if line.startswith("MISSING"):
        return "missing", f"{line}（environ 无 AF_JOBS_DATA）"
    if line == "NOPROC":
        return "missing", "gov 在役进程不在（pgrep 'python3 af-jobs-portal.py' 空）"
    return "unknown", f"读数不可识别（{line[:60]!r}）"


def scan_portal():
    """gov 公网门户三签名巡检（只读；A8 判定在 build_alarms，处置在 keepalive）。
    ok=三签名全过；env=unknown 且 ①② 过时不判死，仅如实上报 env 未验证。"""
    out = {"ok": False, "healthz": False, "open_total": None, "env": None, "error": None}
    reasons = []
    rc, body = _portal_http(PORTAL_HEALTH_URL)
    if rc == 0:
        try:
            doc = json.loads(body.strip())
            out["healthz"] = isinstance(doc, dict) and doc.get("ok") is True
        except ValueError:
            out["healthz"] = False
    if not out["healthz"]:
        reasons.append(f"healthz 探针失败（curl rc={rc}，body={body[:60]!r}）")
    rc2, body2 = _portal_http(PORTAL_TASKS_URL)
    if rc2 == 0:
        try:
            doc = json.loads(body2)
            if isinstance(doc, dict) and isinstance(doc.get("total"), int):
                out["open_total"] = doc["total"]
            elif isinstance(doc, list):
                out["open_total"] = len(doc)   # 旧版门户裸数组（回滚形态）也算数据面在
        except ValueError:
            pass
    if out["open_total"] is None:
        reasons.append(f"tasks.json 信封不可解析/非数据面形状（curl rc={rc2}）")
    st, why = _portal_env_state()
    out["env"] = st
    if st == "missing":
        reasons.append(f"在役进程 env 缺 AF_JOBS_DATA（{why}）——11-02 板面全零事故同款根因")
    if reasons:
        if st == "unknown" and out["healthz"] and out["open_total"] is not None:
            reasons.append(f"env 未验证（{why}）——HTTP 面已过，仅注记不判死")
        out["error"] = "；".join(reasons)
        return out
    out["ok"] = True
    if st == "unknown":
        # 健康但 env 签名不可验证：不判死（HTTP 面已裁决），error 作注记随快照上报
        # （A8 只吃 ok，注记不触发红灯；巡检报告/最新快照能看到为何 env 列为 unknown）
        out["error"] = f"env 未验证（{why}）——HTTP 面已过，仅注记不判死"
    return out


# ---------- ⑦ 活性安灯聚合段（风险#7 收口批 2026-11-04；只读判据面） ----------

def scan_trigger_source_silent(t):
    """形态A/形态B 读数聚合（**只读**；写入方=tools/factory-keepalive.py 判据行④）。

    读 状态观测/trigger-inbox-source-silent.json（keepalive 每轮重写＝报活心跳），
    把**两种失联形态**的机器可读读数抬进聚合面（此前聚合面只有路由侧那一份）：
      · 形态A 收件箱进程不在          → status=down  / alarm_code=trigger-inbox-down
      · 形态B 收件箱进程在但源头断供  → status=amber / alarm_code=trigger-inbox-source-silent
      · 形态B 的健康侧                → status=green（alarm_code=None）
      · 第三形态（进程在但不健康）    → status=degraded（不判源断供）
      · 不可证                       → unknown（在位但读不出/坏 JSON/自述状态不可识别）
      · 判据文件不在位                → missing
      · stale                        → 判据文件 mtime 超 TRIGGER_LIVENESS_STALE_S（陈旧即失活）
    ★ **只增不减**：本读数落在**新子键** source_silent 下，与路由侧那份
      （status/alarm_code/… 既有键）**平级并存、互不覆盖**；两形态的码各归各位
      （形态A=既有码 trigger-inbox-down，形态B=新码 trigger-inbox-source-silent）。
    只读纪律：本函数**不写**判据文件、不写任何在役状态面。
    """
    out = {
        "status": "unknown",
        "alarm_code": None,        # 判据文件自述 alarm_code（down / source-silent / None）
        "form": None,              # "A"=进程不在 / "B"=进程在但断供 / None=非形态告警
        "process_alive": None,     # 判据文件自述进程态（True/False；读不出=None）
        "healthy": None,
        "silent_s": None,          # 收件箱静默秒数（判据文件自述）
        "threshold_min": None,
        "message": "",
        "criterion_file": TRIGGER_SOURCE_SILENT_FILE,
        "criterion_ts": None,
        "criterion_age_s": None,   # 判据文件 mtime 距今（读到多旧——陈旧即失活）
        "stale_after_s": TRIGGER_LIVENESS_STALE_S,
        "stale": False,
        "missing": False,
        "tool": "factory-watch/trigger-inbox-source-silent-aggregator",
    }
    try:
        stt = os.stat(TRIGGER_SOURCE_SILENT_FILE)
    except FileNotFoundError:
        out["status"] = "missing"
        out["missing"] = True
        out["message"] = ("形态判据文件不在位——keepalive 判据行④没在产出"
                          "（形态A/B 读数不可证，不得当成活）")
        return out
    except OSError as e:
        out["message"] = (f"形态判据文件 stat 失败（{type(e).__name__}）"
                          "——不可证，不猜绿")
        return out
    out["criterion_age_s"] = max(0, int(t - stt.st_mtime))
    doc = load_json(TRIGGER_SOURCE_SILENT_FILE, None)
    if not isinstance(doc, dict):
        out["status"] = "unknown"
        out["message"] = "形态判据文件不可解析/坏 JSON——不可证，不猜绿"
        return out

    def _s(k):
        v = doc.get(k)
        return v if isinstance(v, str) else None

    def _n(k):
        v = doc.get(k)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _b(k):
        v = doc.get(k)
        return v if isinstance(v, bool) else None

    out["alarm_code"] = _s("alarm_code")
    out["process_alive"] = _b("process_alive")
    out["healthy"] = _b("healthy")
    out["silent_s"] = _n("silent_s")
    out["threshold_min"] = _n("threshold_min")
    out["criterion_ts"] = _s("ts")
    # 陈旧判定**先于**状态解读：判据行④没在跑 ⇒ 文件不再被重写 ⇒ 自述一律作废
    if out["criterion_age_s"] > TRIGGER_LIVENESS_STALE_S:
        out["status"] = "stale"
        out["stale"] = True
        out["message"] = (f"形态判据文件已 {out['criterion_age_s']}s 未重写"
                          f"（>{TRIGGER_LIVENESS_STALE_S}s）——keepalive 判据行④没在跑"
                          "（文件自述作废，不当成活）")
        return out
    st = _s("status")
    if st == "down":
        out["status"] = "down"
        out["form"] = "A"
    elif st == "amber":
        out["status"] = "amber"
        out["form"] = "B"
    elif st in ("green", "degraded"):
        out["status"] = st
    else:
        out["status"] = "unknown"
    msg = doc.get("message")
    out["message"] = msg if isinstance(msg, str) else ""
    if out["status"] == "unknown" and not out["message"]:
        out["message"] = "形态判据文件自述状态不可识别——不可证，不猜绿"
    return out


def scan_trigger_liveness(t):
    """活性安灯聚合段（只读；fail-closed：判不准一律不报 green）。

    读安灯判据文件 状态观测/trigger-inbox-liveness.json（event-router 每轮重写
    ＝报活心跳），产出机器可读读数，供快照段与安灯臂共用：
      · status ∈ {green, amber, stale, missing, unknown}
        green/amber = 判据文件自述状态（安灯腿在跑；amber＝收件箱静默超阈）
        stale       = 判据文件 mtime 超 TRIGGER_LIVENESS_STALE_S ⇒ 安灯腿没在跑
                      （**比 amber 更严重**；无论文件自述什么，**绝不报 green**——
                      「读到旧文件＝活」正是 268h 静默前科的失败形态）
        missing     = 判据文件不在位（安灯面缺席；同样不得报 green）
        unknown     = 在位但读不出/坏 JSON/自述状态不可识别（不可证，不猜绿）
    只读纪律：本函数**不写**判据文件、不写任何在役状态面（写入方是 event-router）。
    """
    out = {
        "status": "unknown",
        "criterion_status": None,      # 判据文件自述 status（green/amber）
        "alarm_code": None,            # 判据文件自述 alarm_code（trigger-inbox-silent/live）
        "message": "",
        "silent_s": None,              # 收件箱静默秒数（判据文件 newest_delivery_age_s）
        "threshold_min": None,         # 静默阈（分钟；判据文件 threshold_min）
        "criterion_file": TRIGGER_LIVENESS_FILE,
        "criterion_ts": None,          # 判据文件自述 ts（写入方落笔时刻）
        "criterion_age_s": None,       # 判据文件 mtime 距今（读到多旧——陈旧即失活）
        "criterion_ts_age_s": None,    # 判据文件自述 ts 距今（内容龄）
        "stale_after_s": TRIGGER_LIVENESS_STALE_S,
        "stale": False,
        "missing": False,
        "stop_breaker_in_place": os.path.exists(ROUTER_STOP_FILE),
        "since_epoch": None,
        # ★ 2026-11-05 发布面接线批 ①P4 新增（**只增**）：路由侧那盏灯**进程态**读数
        #   （写入方=event-router 安灯本体读 keepalive 判据文件后落的三字段；
        #     既有键 status/alarm_code 的语义与取值域**一律不动**）。
        "process_alive": None,      # 路由侧灯自读的收件箱进程态（True/False/None=不可证）
        "lamp_state": None,         # 路由侧灯的进程感知裁决（green/amber/down/unknown）
        "lamp_alarm_code": None,    # 进程感知裁决的形态码（down/source-silent/None）
        # ★ 同批新增（**只增**）：形态A/形态B 读数（子键，与路由侧那份平级不覆盖）
        "source_silent": None,
        "tool": "factory-watch/trigger-liveness-aggregator",
    }
    # 形态读数先算（各 return 分支都要带上它）
    _ss = scan_trigger_source_silent(t)
    out["source_silent"] = _ss
    try:
        stt = os.stat(TRIGGER_LIVENESS_FILE)
    except FileNotFoundError:
        out["status"] = "missing"
        out["missing"] = True
        out["message"] = ("安灯判据文件不在位——安灯腿未产出判据"
                          "（安灯面缺席；不得当成活）")
        return out
    except OSError as e:
        out["message"] = (f"安灯判据文件 stat 失败（{type(e).__name__}）"
                          "——不可证，不猜绿")
        return out
    out["criterion_age_s"] = max(0, int(t - stt.st_mtime))
    doc = load_json(TRIGGER_LIVENESS_FILE, None)
    if isinstance(doc, dict):
        def _s(k):
            v = doc.get(k)
            return v if isinstance(v, str) else None

        def _n(k):
            v = doc.get(k)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        def _b(k):
            v = doc.get(k)
            return v if isinstance(v, bool) else None

        out["criterion_status"] = _s("status")
        out["alarm_code"] = _s("alarm_code")
        # ★ 2026-11-05 ①P4：路由侧灯的**进程态**三字段（既有键语义不动，只是多读出来）
        out["process_alive"] = _b("process_alive")
        out["lamp_state"] = _s("lamp_state")
        out["lamp_alarm_code"] = _s("lamp_alarm_code")
        out["criterion_ts"] = _s("ts")
        out["silent_s"] = _n("newest_delivery_age_s")
        out["threshold_min"] = _n("threshold_min")
        out["since_epoch"] = _n("since_epoch")
        ts_epoch = _n("ts_epoch")
        if ts_epoch is not None:
            out["criterion_ts_age_s"] = max(0, int(t - ts_epoch))
    # 陈旧判定**先于**任何状态解读：安灯腿没在跑 ⇒ 判据文件不再被重写
    # ⇒ 文件里写的 green/amber 一律作废（读到旧文件≠活）。
    if out["criterion_age_s"] > TRIGGER_LIVENESS_STALE_S:
        out["status"] = "stale"
        out["stale"] = True
        out["message"] = (f"安灯判据文件已 {out['criterion_age_s']}s 未重写"
                          f"（>{TRIGGER_LIVENESS_STALE_S}s）——安灯腿本身没在跑"
                          "（比 amber 更严重的一档；文件自述 "
                          f"{out['criterion_status']!r} 作废，不当成活）")
        return out
    if not isinstance(doc, dict):
        out["status"] = "unknown"
        out["message"] = ("安灯判据文件不可解析/坏 JSON——不可证，不猜绿")
        return out
    if out["criterion_status"] in ("green", "amber"):
        out["status"] = out["criterion_status"]
        out["message"] = doc.get("message") if isinstance(doc.get("message"), str) else ""
    else:
        out["status"] = "unknown"
        out["message"] = ("安灯判据文件自述状态不可识别"
                          f"（status={out['criterion_status']!r}）——不可证，不猜绿")
    return out


# ---------- 安灯 ----------

def bench_proc_dirs():
    """正在运行的 bench 进程涉及的臂 out 目录集合（读 /proc 命令行，零子进程）。

    判据=argv0 basename 含 "bench" 的进程（af-bench/af-bench-fix2）的 --out 实参，
    兼收命令行里任何 /tmp/bench-* 实参。调度器 running_arms 之外的第二判据：
    臂被调度器之外的方式拉起（手工重跑等）也认其在跑，避免误归档灭掉在跑臂的报警。
    """
    dirs = set()
    me = os.getpid()
    try:
        pids = os.listdir("/proc")
    except OSError:
        return dirs
    for pid in pids:
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                toks = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not toks or "bench" not in os.path.basename(toks[0]):
            continue
        for i, a in enumerate(toks):
            if a == "--out" and i + 1 < len(toks):
                dirs.add(toks[i + 1])
            elif a.startswith("/tmp/bench-"):
                dirs.add(a)
    return dirs


def classify_archived(arms, sched, extras, t):
    """终态臂归档：results.jsonl mtime > ARCHIVE_MATURITY_S 且无关联在跑进程的臂，
    A1/A2 慢性灯免报（安灯节汇总一行 [已归档臂]）；有新活动的臂照常报警。

    "关联在跑进程" = 调度器（主产线/实验线）running_arms 指向的 out 目录，或 /proc
    里 bench 进程命令行出现的臂目录，二者取并。无 results.jsonl 的臂不判归档
    （无行即无 A1/A2 可报，且无法主张 6h 停滞）。返回 (archived, active_dirs)。
    """
    active = set()
    for ra in sched.get("running_arms") or []:
        if ra.get("dir"):
            active.add(ra["dir"])
    for e in extras or []:
        for ra in e.get("running_arms") or []:
            if ra.get("dir"):
                active.add(ra["dir"])
    active |= bench_proc_dirs()
    archived = [a for a in arms
                if a.get("res_mtime") is not None
                and t - a["res_mtime"] > ARCHIVE_MATURITY_S
                and a["dir"] not in active]
    return archived, active


# ---------- D-112 臂态三态分类（在跑/退役/缺失；与 classify_archived 边界对齐） ----------

def classify_arm_states(arms, archived, state, t):
    """臂态显式化（D-112/factory-os#80，红队分诊 H4）：每个臂标注三态之一。

      running  目录在案且未达自然退役边界（=不在 classify_archived 归档集）
      retired  两种慢性终态之一：
               (a) 自然退役：目录在案但 results.jsonl mtime>ARCHIVE_MATURITY_S
                   且无关联在跑进程（=classify_archived 归档集成员——**边界
                   完全对齐，不另立口径**）；
               (b) 消失退役：目录缺失且自 watch 首见缺失起持续
                   ≥ARM_RETIRE_AFTER_S 天。
      missing  目录缺失（exists=false）且持续 <ARM_RETIRE_AFTER_S 天——
               **禁以 0 冒充在案**：此态臂的 n_total=0 是"无数据"不是"零失败"。

    一次性告警 episode 判据：目录缺失首见（arm_missing_seen 无记录）时在臂上
    打 vanished_new=True（build_alarms 据此报一次 bench-arm-vanished 并记录）；
    目录复活（exists 回真）即除记录——再次消失算新 episode 重报。

    返回 annotate 后的 arms（原地补 arm_state / arm_missing_since_s /
    arm_missing_age_s / vanished_new 四键；既有键一律不动——只增不改）。
    """
    seen = state.setdefault("arm_missing_seen", {})
    archived_dirs = {a["dir"] for a in (archived or [])}
    for a in arms:
        a["vanished_new"] = False
        a["arm_missing_since_s"] = None
        a["arm_missing_age_s"] = None
        if not a.get("exists"):
            first = seen.get(a["dir"])
            if first is None:
                # 首见缺失：记时并标记新 episode（本轮由 build_alarms 报一次性码）
                first = int(t)
                seen[a["dir"]] = first
                a["vanished_new"] = True
            age = int(t - first)
            a["arm_missing_since_s"] = int(first)
            a["arm_missing_age_s"] = age
            a["arm_state"] = "retired" if age >= ARM_RETIRE_AFTER_S else "missing"
        elif a["dir"] in seen:
            # 目录复活：清 episode 记录（再消失算新 episode）；在案性仍按
            # classify_archived 边界判（复活即带着旧结果的臂照样可归档）
            seen.pop(a["dir"], None)
            a["arm_state"] = "retired" if a["dir"] in archived_dirs else "running"
        else:
            a["arm_state"] = "retired" if a["dir"] in archived_dirs else "running"
    return arms


def probe_local_tmp_mb():
    """本机 /tmp 可用（MiB）。statvfs 本地读 f_bavail（tmpfs 无 root 保留，与 df 同值）。
    异常 → (-1, True)=盘点失败（fail-closed 口径；与真写满同码 A4L:tmp 但文案强制区分）。
    **量纲边界（2026-11-02 RT 收尾 DEB57）**：f_bavail 是全机剩余空间，量不到本
    用户的每用户配额（usrquota）——它不是「写得进去」的判据；写入门径见
    probe_tmp_write_admission()。"""
    try:
        st = os.statvfs("/tmp")
        return st.f_bavail * st.f_frsize // 1048576, False
    except Exception:
        return -1, True


def probe_tmp_write_admission(path=None):
    """本机 /tmp 实际写入门径探针：真写 A4W_PROBE_BYTES 字节再立刻删（零留存）。

    为什么必须真写（2026-11-02 RT 收尾 DEB57）：statvfs f_bavail 量的是「全机
    剩余空间」，实际拒绝写入的是 tmpfs 每用户配额（usrquota）「本用户还能写多少」
    那一本账。2026-11-02 10:37 实测 f_bavail=1012MiB 时 1MiB 写即
    OSError 122 Disk quota exceeded（同刻 /home 可写）——数字好看 ≠ 写得进去，
    落 /tmp 的门件与运行件（kb/verify.py 快照 sqlite backup）当场 disk I/O error。

    返回 (ok: bool, err: str)：ok=True＝写得进去；ok=False 时 err 记失败原因
    （形如 "OSError 122 Disk quota exceeded"）。探针自身异常一律 fail-closed
    （当作写不进报出），绝不因探针故障静默放行。
    """
    d = path or A4W_PROBE_DIR
    p = os.path.join(d, ".factory-watch-write-probe-%d.tmp" % os.getpid())
    try:
        with open(p, "wb") as f:
            f.write(b"\0" * A4W_PROBE_BYTES)
        return True, ""
    except OSError as e:
        return False, "OSError %s %s" % (e.errno, e.strerror)
    except Exception as e:  # noqa: BLE001 - 探针故障按写不进处理（fail-closed）
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            os.unlink(p)
        except OSError:
            pass


def build_alarms(arms, sched, anolis, relay, plan, state, t, extras=None, archived=None,
                 portal=None, trigger_liveness=None, gc=None):
    alarms = []

    def add(level, code, key, message, first_seen):
        alarms.append({"level": level, "code": code, "key": key,
                       "message": message,
                       "since": time.strftime("%F %T", time.localtime(first_seen))})

    # A0 调度器死/状态停更
    if not sched["status_file_exists"]:
        add("red", "A0", "A0", "调度器状态文件缺失（从未运行或已被清理）", t)
    elif sched["mtime_stale"]:
        age = sched["mtime_age_s"]
        add("red", "A0", "A0",
            f"调度器状态停更：{os.path.basename(SCHED_STATUS)} 已 {age}s 未刷新"
            f"（阈值 {SCHED_STALE_S}s）", t)
    elif sched["proc_confirmed_down"]:
        add("red", "A0", "A0", "调度器进程不存在（连续 2 轮 pgrep 无果）", t)

    # A1/A2 按臂（归档的终态臂跳过：results.jsonl mtime>6h 且无关联在跑进程，
    # 慢性红灯不再每轮复报——汇总见安灯节 [已归档臂] 行，归档依据见巡检日志）
    archived_dirs = {a["dir"] for a in (archived or [])}
    for a in arms:
        if a["dir"] in archived_dirs:
            continue
        name = f"{a['tier']}-{a['profile']}"
        # A1/A2 = 任务级末行口径（2026-10-22 修）：按 task_id 取 results.jsonl 末行，
        # 重试救回的 attempt 不计入；行级值降为诊断信息行（render_report [口径明细]），
        # 不再触发红灯。修前误报实证：D1/D2-step-5 行级 run_failed 13/17 → 末态 0，
        # D1/D2-mavis-m31f 行级拦截 27/21 → 末态零补丁 5/1，10%/30% 阈值全不触。
        if a["n_tasks"] >= 5 and a["task_run_failed"] / a["n_tasks"] > 0.10:
            add("red", "A1", f"A1:{name}",
                f"臂 {name}: 末态 run_failed {a['task_run_failed']}/{a['n_tasks']} "
                f"({a['task_run_failed'] * 100 / a['n_tasks']:.0f}%) > 10%"
                f"（任务级末行口径；行级 run_failed={a['n_run_failed']}/{a['n_total']} 为历史尝试）", t)
        if a["n_tasks"] >= 10 and a["task_zero_patch"] / a["n_tasks"] > 0.30:
            add("red", "A2", f"A2:{name}",
                f"臂 {name}: 末态零补丁 {a['task_zero_patch']}/{a['n_tasks']} "
                f"({a['task_zero_patch'] * 100 / a['n_tasks']:.0f}%) > 30%"
                f"（任务级末行口径；行级零补丁/gate拦截={a['n_blocked']}/{a['n_total']} 为历史尝试）", t)

    # A3 按档案聚合：≥10 题已判分且通过 0
    by_prof = {}
    for a in arms:
        p = by_prof.setdefault(a["profile"], {"judged": 0, "resolved": 0})
        p["judged"] += a["judged_tasks"]
        p["resolved"] += a["resolved_tasks"]
    for prof, p in sorted(by_prof.items()):
        if p["judged"] >= 10 and p["resolved"] == 0:
            add("amber", "A3", f"A3:{prof}",
                f"档案 {prof}: 已判分 {p['judged']} 题通过 0", t)

    # A4 anolis 分区
    for mnt, d in sorted((anolis.get("disk") or {}).items()):
        if d["use_pct"] > 85:
            add("amber", "A4", f"A4:{mnt}",
                f"anolis 分区 {mnt} 使用率 {d['use_pct']}%（{d['used']}/{d['size']}）> 85%", t)

    # A4L 本机 /tmp（D-24，patch-tmpfs-alarm-watch-A4L-R2 / 方案 P1-1）：判分 results、
    # swev 任务 json、调度器三件套全落本机 /tmp（tmpfs+usrquota）。<校准线报 amber；
    # 盘点失败同码另文案。30min 去重由 log_alarms 的 alarm_logged 同款承担。
    tmp_mb, tmp_fail = probe_local_tmp_mb()
    if tmp_fail:
        add("amber", "A4L:tmp", "A4L:tmp", "/tmp 盘点失败（fail-closed）", t)
    elif tmp_mb < A4L_TMP_WARN_MB:
        add("amber", "A4L:tmp", "A4L:tmp",
            f"本机 /tmp 可用 {tmp_mb} MiB<{A4L_TMP_WARN_MB}MiB"
            f"（usrquota 校准线，闸线 {A4L_TMP_GATE_MB}MiB，低于则 sched/mcode 拦新臂/新判分）", t)

    # A4W 本机 /tmp 写即失败（2026-11-02 RT 收尾 DEB57）：真写探针判门径。
    # 与 A4L 并存不互斥——两本账：A4L 量「全机剩余空间」（低水＝提前叫人，量纲
    # 见 probe_local_tmp_mb docstring），A4W 量「本用户现在还能不能写」（写不进
    # ＝当场坏）。2026-11-02 10:37 实测两本账打架：f_bavail 报 1012MiB 可用，
    # 同刻 1MiB 写即 EDQUOT → 门件 kb/verify.py 的 sqlite backup 当场
    # disk I/O error，L4 集成门硬红。A4L 文案只承诺「拦新臂/新判分」，写即失败
    # 由本灯承诺覆盖（红级：不是提前叫人，是现在就坏）。
    tmp_w_ok, tmp_w_err = probe_tmp_write_admission()
    if not tmp_w_ok:
        add("red", "A4W:tmp", "A4W:tmp",
            f"本机 /tmp 写即失败（{tmp_w_err}）——usrquota 每用户配额耗尽，"
            f"statvfs 可用量口径（A4L）量不到此状态；落 /tmp 的门件与运行件"
            f"（如 kb/verify.py 快照 sqlite backup）当场失败", t)

    # A5 中继连败
    if relay["consecutive_failures"] >= RELAY_FAIL_MIN:
        add("amber", "A5", "A5",
            f"中继连续失败 {relay['consecutive_failures']} 次（≥{RELAY_FAIL_MIN}）无一次 ok；"
            f"最近: {relay['last_event']}", t)

    # A6 running 臂 30 分钟无新结果行（主产线 + 第二产线实验调度器）
    if sched.get("alive"):
        for ra in sched["running_arms"]:
            nid, d = ra["node"], ra["dir"]
            if not d:
                continue
            first = state["first_running"].setdefault(nid, t)
            if t - first < RUNNING_STALL_S:
                continue
            li = state["last_increase"].get(d)
            age = t - li if li else None
            if age is None or age > RUNNING_STALL_S:
                # 慢任务豁免：runs/ 最新子目录 10 分钟内有写入（含其内文件）即视为
                # 活跃——GLM/kimi 单题 30-60 分钟正常，results 行整题收尾才落盘。
                rmt = runs_recent_mtime(d)
                if rmt is not None and t - rmt <= RUNS_FRESH_S:
                    continue
                add("amber", "A6", f"A6:{nid}",
                    f"运行中臂 {nid} 已 {int(age)}s 无新结果行"
                    f"（{d}）" if age is not None else
                    f"运行中臂 {nid} 无新结果行记录（{d}）", t)
    for e in (extras or []):
        for ra in e.get("running_arms", []):
            nid, d = ra["node"], ra["dir"]
            if not d:
                continue
            first = state["first_running"].setdefault(nid, t)
            if t - first < RUNNING_STALL_S:
                continue
            li = state["last_increase"].get(d)
            age = t - li if li else None
            if age is None or age > RUNNING_STALL_S:
                rmt = runs_recent_mtime(d)
                if rmt is not None and t - rmt <= RUNS_FRESH_S:
                    continue
                add("amber", "A6", f"A6:{nid}",
                    f"运行中臂 {nid} 已 {int(age)}s 无新结果行"
                    f"（{d}）" if age is not None else
                    f"运行中臂 {nid} 无新结果行记录（{d}）", t)

    # A7 镜像停滞：2 小时无新增且 <120（本机 feed 盘点口径，见 scan_local_images）
    ih = state["sweb_img_hist"]
    if len(ih) >= 2 and ih[-1][0] - ih[0][0] >= IMG_STALL_S:
        recent = [c for ts, c in ih if t - ts <= IMG_STALL_S]
        if recent and ih[-1][1] < IMAGE_TARGET and max(recent) == min(recent) == ih[-1][1]:
            add("amber", "A7", "A7",
                f"本机 sweb.eval 镜像停滞在 {ih[-1][1]}/{IMAGE_TARGET} 已 2 小时无新增"
                f"（feed 盘点口径：唯一任务数）", t)

    # A8 gov 公网门户（2026-11-02 RT 收口批）：scan_portal 三签名任一败即红。
    # 11-02 09:00 板面全零事故（重启未带 AF_JOBS_DATA，板面空转 20+min）在
    # alarms.log 全窗零门户条目——watch 无门户探针是告警盲区，本灯收口；
    # 自愈处置在 keepalive（portal 看护对象），本灯只管叫人。
    # portal=None（单测桩输入）时跳过：探针扫描面缺位不虚构红灯。
    if portal is not None and not portal.get("ok"):
        add("red", "A8", "A8",
            f"gov 公网门户不可用（{portal.get('error') or '未知原因'}）"
            f"——公网领任务/看板/回报全断；keepalive portal 对象负责自动拉起"
            f"（ssh gov 经 start-portal.sh），拉不回或 ssh 亦断需人工介入", t)

    # A9 活性安灯腿失活（风险#7 收口批 2026-11-04 新增臂；**只增，既有臂不动**）
    # 判据：安灯判据文件（event-router 每轮重写＝报活心跳）超陈旧阈未重写，
    # 或根本不在位 ⇒ 安灯腿本身没在跑。**stale/missing 一律不报 green**
    # （268h 静默前科的失败形态正是「读到旧判据当成活」）。
    # 与 event-router 自写的 trigger-inbox-silent 摘要行**不同码不同义**：那行=
    # 安灯在跑但收件箱静默；本行=安灯腿本身失活 ⇒ 不重复记（同码不同义不同档）。
    # 冷却：走既有 log_alarms 的 30min 同码去重（不新造冷却口径）。
    if trigger_liveness is not None:
        tl_status = trigger_liveness.get("status")
        if tl_status in ("stale", "missing"):
            stop_note = ("（router STOP 熔断在位：安灯腿按设计停报，非失活）"
                          if trigger_liveness.get("stop_breaker_in_place") else "")
            add("amber" if trigger_liveness.get("stop_breaker_in_place") else "red",
                "A9:trigger-andon", "A9:trigger-andon",
                f"活性安灯腿失活：{trigger_liveness.get('message')}{stop_note}"
                "——安灯腿没在跑（比收件箱静默更严重）；读数取自判据文件"
                "（event-router 每轮重写＝报活心跳）", t)

    # D-112 一次性 bench-arm-vanished（红队分诊 H4：目录消失禁以 0 冒充在案）。
    # 每个消失 episode 只报一次：vanished_new 由 classify_arm_states 在**首见**
    # 缺失时置位（记录落 watch-state.json arm_missing_seen，重启不重报；臂复活
    # 清记录，再消失算新 episode 重报）。持续缺失的慢性真相由臂态字段
    # arm_state（missing/retired）每轮承载，不靠本灯复报——故本灯是一次性
    # 事件通知，不是持续性条件灯（A 族编号灯的复报语义不适用于此）。
    # 档位=amber：bench 基础设施退役是已登记事项（bench-infra-retired-20261029），
    # 本灯要的是"可分辨"（人看得见消失发生了），不是"当急事叫人"；真急事
    # （调度器死/失败率/写即失败）由 A0/A1/A2/A4W 红级承担。
    for a in arms:
        if not a.get("vanished_new"):
            continue
        name = f"{a['tier']}-{a['profile']}"
        add("amber", ARM_VANISH_CODE, f"{ARM_VANISH_CODE}:{name}",
            f"臂 {name} 目录消失（{a['dir']}，exists=false）——臂态显式化为 "
            f"{a['arm_state']}；该臂 n_total=0 是「无数据」不是「零失败」，"
            f"禁以 0 冒充在案。持续缺失 ≥{ARM_RETIRE_AFTER_S // 86400} 天转 "
            f"retired 态；本码每个消失 episode 只报一次（chronic 真相以臂态"
            f"字段承载）。scheduler alive 与臂在案性无关，勿据 alive 推断臂在跑", t)

    # ---- D-113 /data 水位恢复腿 + 回落留痕（红队分诊 H3；**只增，既有臂不动**）----
    # 判据面 = img-gc 耐久证据（状态观测/img-gc-evidence.jsonl），本件只读消费。
    # gc=None（旧调用路径/单测桩未传）⇒ 两腿全不判——不猜绿也不假红。
    if gc is not None:
        cur_pct = ((anolis.get("disk") or {}).get("/data") or {}).get("use_pct")
        gi = gc_recovery_alarm_inputs(gc, cur_pct, t)
        if gi["a10"]:
            lr = gc.get("last_recovery") or {}
            la = gc.get("last_apply") or {}
            if lr.get("tier") in ("L1", "L2", "L3"):
                detail = (f"恢复腿档位 {lr.get('tier')}；L1 白名单候选 "
                          f"{lr.get('L1_n')} 项、预估回收 "
                          f"{lr.get('L1_est_reclaim_bytes')} B；L2 腾挪建议 "
                          f"{lr.get('L2_n')} 项（不自动执行）；报告件 "
                          f"{lr.get('report_path')}")
            else:
                detail = (f"末次 apply：/data {la.get('use_pct')}%（{la.get('ts')}），"
                          f"reason={la.get('reason')}；{gi['a10_why']}")
            add("red", GC_RECOVERY_CODE, GC_RECOVERY_CODE,
                f"/data 停手线触顶后恢复动作腿：{detail}。"
                f"——停手线触顶后零自动恢复动作即本次收口的病灶（197 条 apply 仅 "
                f"2 条 ok=true，峰值 use_pct=100）；报告件只读、不自动删，"
                f"删除仍走既有 apply 通道（HALT 解除且 <停手线）", t)
        if gi["a11"] and state.get(GC_FALLBACK_LATCH_KEY) != gc.get("peak_epoch"):
            # 一次性/episode：每个「未解释峰值」只报一次（闩锁记 watch-state），
            # chronic 真相由快照 gc_recovery 段每轮承载，不靠本灯复报刷屏。
            state[GC_FALLBACK_LATCH_KEY] = gc.get("peak_epoch")
            add("amber", GC_FALLBACK_CODE, GC_FALLBACK_CODE,
                f"/data 回落无留痕：{gi['a11_why']}。回落来源既非 img-gc 成功 apply "
                f"亦无 kind=recovery 分级证据行——/data=订单生产真值根，须人工核定"
                f"回落来源并在变更日志/安灯登记；读数为 img-gc 耐久证据（只读）", t)

    # since 持续性：条件消失即清；持续则沿用首次时刻
    open_keys = {}
    for al in alarms:
        first = state["alarm_open"].get(al["key"], t)
        state["alarm_open"][al["key"]] = first
        al["since"] = time.strftime("%F %T", time.localtime(first))
        open_keys[al["key"]] = True
    for k in list(state["alarm_open"]):
        if k not in open_keys:
            del state["alarm_open"][k]
    order = {"red": 0, "amber": 1}
    alarms.sort(key=lambda x: (order[x["level"]], x["code"], x["key"]))
    return alarms


def log_alarms(alarms, state, t):
    try:
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            for al in alarms:
                last = state["alarm_logged"].get(al["key"])
                if last is None or t - last >= DEDUP_WINDOW:
                    f.write(json.dumps({
                        "ts": now_s(), "level": al["level"], "code": al["code"],
                        "message": al["message"], "since": al["since"],
                    }, ensure_ascii=False) + "\n")
                    state["alarm_logged"][al["key"]] = t
    except Exception:
        pass


# ---------- 汇总快照 ----------

def build_snapshot(arms, plan, sched, anolis, relay, alarms, mode, extras=None, archived=None,
                   portal=None, trigger_liveness=None, gc=None):
    totals = {
        "n_total": sum(a["n_total"] for a in arms),
        "n_reward_true": sum(a["n_reward_true"] for a in arms),
        "n_run_failed": sum(a["n_run_failed"] for a in arms),
        "rows_10m": sum(a["rows_10m"] for a in arms),
        "n_tasks": sum(a["n_tasks"] for a in arms),
        "task_run_failed": sum(a["task_run_failed"] for a in arms),
        "task_zero_patch": sum(a["task_zero_patch"] for a in arms),
        "n_bad_lines": sum(a["n_bad_lines"] for a in arms),
    }
    cost = []
    for prof in PROFILES:
        rows = [a for a in arms if a["profile"] == prof]
        cost.append({
            "profile": prof,
            "runs": sum(a["n_total"] for a in rows),
            "tokens_in": sum(a["sum_tin"] for a in rows),
            "tokens_out": sum(a["sum_tout"] for a in rows),
            "tokens_cache": sum(a["sum_tcache"] for a in rows),
        })
    plan_tiers = dict(plan)
    if EXTRA_ARM_DIRS:
        plan_tiers.setdefault("F2", extra_f2_target())
    return {
        "ts": now_s(),
        "epoch": int(time.time()),
        "generated_by": "tools/factory-watch.py",
        "mode": mode,
        "interval_s": INTERVAL,
        "plan": {"file": SAMPLE_REL, "tiers": plan_tiers},
        "scheduler": {k: v for k, v in sched.items() if k != "summary"} | {"summary": sched.get("summary")},
        "extra_schedulers": extras or [],
        "arms": [{k: a[k] for k in (
            "tier", "profile", "dir", "exists", "n_total", "n_reward_true",
            "n_completed_not_reward", "n_run_failed", "n_blocked",
            "n_tasks", "task_run_failed", "task_zero_patch", "n_bad_lines",
            "judged_tasks", "resolved_tasks", "rows_10m", "last_new_row_age_s",
        )} | {
            # D-112 臂态三态显式化（H4 收口）：arm_state=running/retired/missing；
            # arm_missing_since_s/arm_missing_age_s=缺失时钟（首见缺失 epoch/
            # 持续秒数，非缺失臂为 null）。臂级新键——data.json 顶层键集冻结
            # （publish-scrub-gate DATA_TOP）不受影响（只钉顶层）。
            # 容错：未经 classify_arm_states 注解的臂（旧调用路径/单测桩）按
            # exists 回落推导，不 KeyError（只增不改——旧形状调用方不崩）。
            "arm_state": a.get("arm_state") or (
                "missing" if not a.get("exists") else "running"),
            "arm_missing_since_s": a.get("arm_missing_since_s"),
            "arm_missing_age_s": a.get("arm_missing_age_s"),
        } | {
            "avg_turns": round(a["sum_turns"] / a["n_turns"], 1) if a["n_turns"] else None,
            "avg_tokens_in": int(a["sum_tin"] / a["n_tokens"]) if a["n_tokens"] else None,
            "avg_tokens_out": int(a["sum_tout"] / a["n_tokens"]) if a["n_tokens"] else None,
            "avg_tokens_cache": int(a["sum_tcache"] / a["n_tokens"]) if a["n_tokens"] else None,
            "avg_wall_ms": int(a["sum_wall_ms"] / a["n_wall"]) if a["n_wall"] else None,
        } for a in arms],
        "anolis": anolis,
        "relay": relay,
        # RT 收口批（2026-11-02）：gov 公网门户巡检面（scan_portal 三签名）。
        # data.json 冻结键集（publish-scrub-gate.py DATA_TOP）同批已同步加 "portal"。
        "portal": portal,
        # ⑦ 活性安灯聚合段（风险#7 收口批 2026-11-04）：安灯读数进机器可读全量快照
        # （此前 latest.json 无安灯读数＝安灯响了没人抬得起来）。**只读**判据文件，
        # 不写它；陈旧判据一律报 stale/missing，**绝不报 green**。
        "trigger_liveness": trigger_liveness,
        # D-113 /data 恢复腿读数（红队分诊 H3 收口）：**只读** img-gc 耐久证据的
        # 机器可读投影——停手线触顶后的恢复腿档位/L1 候选/预估回收量、未解释峰值
        # 与回落判据。安灯响了要有机器可读面把它抬起来（268h 静默前科的结构性成因）。
        "gc_recovery": (dict(gc) | {"alarm_codes": [GC_RECOVERY_CODE, GC_FALLBACK_CODE],
                                    "current_use_pct":
                                        ((anolis.get("disk") or {}).get("/data")
                                         or {}).get("use_pct"),
                                    "fallback_min_drop_pp": GC_FALLBACK_MIN_DROP_PP,
                                    "peak_window_s": GC_PEAK_WINDOW_S}
                        if gc is not None else None),
        "totals": totals,
        "cost": cost,
        "archived_arms": {
            "n": len(archived or []),
            "arms": [f"{a['tier']}-{a['profile']}" for a in (archived or [])],
            "rule": f"results.jsonl mtime>{ARCHIVE_MATURITY_S}s 且无关联在跑进程 → A1/A2 免报",
        },
        "alarms": alarms,
    }


# ---------- 人类可读报告（--once） ----------

def fmt_avg(x, unit=""):
    return "-" if x is None else f"{x}{unit}"


def render_report(s):
    L = []
    L.append("=" * 72)
    L.append(f"黑灯工厂巡检报告  {s['ts']}  （模式 {s['mode']}）")
    L.append("=" * 72)

    sc = s["scheduler"]
    if sc["alive"]:
        sm = sc.get("summary") or {}
        L.append(f"[调度器] 存活 pid={' '.join(map(str, sc['pids'])) or '?'}  "
                 f"状态龄 {sc['mtime_age_s']}s  "
                 f"running={sm.get('running')} done={sm.get('done')} "
                 f"failed={sm.get('failed')} partial={sm.get('partial')} "
                 f"pending={sm.get('pending')}（摘要 ts {sm.get('ts')}）")
    else:
        why = []
        if not sc["status_file_exists"]:
            why.append("状态文件缺失")
        if sc.get("mtime_stale"):
            why.append(f"状态停更 {sc['mtime_age_s']}s")
        if sc.get("proc_confirmed_down"):
            why.append("进程不在")
        L.append(f"[调度器] 失联（{'；'.join(why) or '未知'}）——若修理组正在重启属预期，A0 会持续挂红直至恢复")

    L.append(f"[产线矩阵] 目标分母 D1={s['plan']['tiers']['D1']} "
             f"D2={s['plan']['tiers']['D2']} D3={s['plan']['tiers']['D3']}"
             f"（{os.path.basename(SAMPLE)}）"
             + (f"  F2={s['plan']['tiers'].get('F2', 0)}（实验线 fix2 重跑）"
                if "F2" in s["plan"]["tiers"] else ""))
    L.append(f"  {'档/档案':<18}{'臂态':<4}{'总行':>5}{'通过':>5}{'完成未过':>7}"
             f"{'run_fail':>9}{'拦截':>5}{'判分题':>6}{'10min':>6}"
             f"{'avg turns':>10}{'avg wall':>10}")
    # D-112 三态灯位（在跑/退役/缺失）——目录缺失不再渲染成与"在案零产出"
    # 同形的全零行（H4：人无法分辨退役 vs 死了）
    arm_state_label = {"running": "在跑", "retired": "退役", "missing": "缺失"}
    for a in s["arms"]:
        st = a.get("arm_state") or ("missing" if not a["exists"] else "running")
        L.append(f"  {a['tier']}-{a['profile']:<13}"
                 f"{arm_state_label.get(st, st):>4}"
                 f"{a['n_total']:>6}{a['n_reward_true']:>6}"
                 f"{a['n_completed_not_reward']:>8}{a['n_run_failed']:>9}"
                 f"{a['n_blocked']:>6}{a['judged_tasks']:>7}{a['rows_10m']:>7}"
                 f"{fmt_avg(a['avg_turns']):>11}{fmt_avg(a['avg_wall_ms'], 'ms'):>12}")
    t = s["totals"]
    L.append(f"  合计: 行 {t['n_total']}，reward=true {t['n_reward_true']}，"
             f"run_failed {t['n_run_failed']}，最近10分钟新增 {t['rows_10m']} 行")
    # 臂态普查 + 解耦声明（D-112）：缺失臂的 0 是"无数据"不是"零失败"；
    # scheduler alive 只说明调度进程/状态在，不构成臂在案证据。
    n_run = sum(1 for a in s["arms"] if (a.get("arm_state") or "running") == "running")
    n_ret = sum(1 for a in s["arms"] if a.get("arm_state") == "retired")
    n_mis = sum(1 for a in s["arms"] if a.get("arm_state") == "missing")
    L.append(f"[臂态普查] 在跑 {n_run} · 自然/消失退役 {n_ret} · 目录缺失 {n_mis}"
             f"（共 {len(s['arms'])} 臂；缺失臂禁以 0 冒充在案——其 0=无数据非零失败；"
             f"缺失持续 ≥{ARM_RETIRE_AFTER_S // 86400} 天转 retired，"
             f"时钟=watch 首见缺失时刻，末次新结果行年龄见各行 last_new_row_age_s 为下界参照）")
    if n_mis or n_ret:
        L.append("[臂态解耦] scheduler alive 摘要与臂态解耦：alive 只说明调度进程在、"
                 "状态文件在刷新，不构成臂在案证据——臂在案性以臂态列（在跑/退役/缺失）"
                 "与一次性 bench-arm-vanished 码为准")

    # 口径明细（2026-10-22 修）：A1/A2 按任务级末行判定；行级=历史 attempt 仅诊断
    data_arms = [a for a in s["arms"]
                 if a["exists"] and (a["n_total"] > 0 or a["n_bad_lines"] > 0)]
    if data_arms:
        L.append("[口径明细] A1/A2=任务级末行（每 task 取 results.jsonl 末行，重试救回不计）；"
                 "行级=历史 attempt，仅诊断不触发安灯")
        for a in data_arms:
            nm = f"{a['tier']}-{a['profile']}"
            bad = f"  坏行 {a['n_bad_lines']}" if a["n_bad_lines"] else ""
            L.append(f"  {nm:<18}唯一题 {a['n_tasks']:>3}  末态 run_failed {a['task_run_failed']:>2}  "
                     f"末态零补丁 {a['task_zero_patch']:>2}  ｜行级 run_failed "
                     f"{a['n_run_failed']}/{a['n_total']}  零补丁/gate "
                     f"{a['n_blocked']}/{a['n_total']}{bad}")

    for e in s.get("extra_schedulers", []):
        if not e["exists"]:
            L.append(f"[实验线调度器] 状态文件缺失（{e['status']}）")
            continue
        sm = e.get("summary") or {}
        fresh = e["mtime_age_s"] is not None and e["mtime_age_s"] <= SCHED_STALE_S
        arms_s = " ".join(f"{ra['node']}→{ra['dir']}" for ra in e["running_arms"]) or "无"
        L.append(f"[实验线调度器] {'存活' if fresh else '停更'} "
                 f"状态龄 {e['mtime_age_s']}s  running={sm.get('running')} "
                 f"done={sm.get('done')} partial={sm.get('partial')} "
                 f"failed={sm.get('failed')} pending={sm.get('pending')}  运行臂: {arms_s}")

    an = s["anolis"]
    if an["ok"]:
        disks = "  ".join(f"{m} {d['use_pct']}%({d['avail']}可用)"
                          for m, d in sorted(an["disk"].items()))
        loc = an.get("local_sweb_images")
        loc_s = (f"本机 {loc}/{an['image_target']}（A7 口径）"
                 if loc is not None else "本机 未知")
        img_s = (f"镜像 anolis {an['sweb_images']}/{an['image_target']}｜{loc_s}")
        ld = an["load"]
        L.append(f"[anolis] {disks}  {img_s}  ollama {an['ollama']}  "
                 f"load {ld['m1']}/{ld['m5']}/{ld['m15']}" if ld else
                 f"[anolis] {disks}  {img_s}  ollama {an['ollama']}  load 未知")
    else:
        L.append(f"[anolis] 巡检失败：{an.get('error') or '未知原因'}"
                 f"（A4 暂不判定；A7 口径=本机 docker feed 盘点，不受 ssh 影响）")

    rl = s["relay"]
    L.append(f"[中继] 连续失败 {rl['consecutive_failures']}（≥{RELAY_FAIL_MIN} 触发 A5）  "
             f"最近事件: {rl['last_event']}")

    po = s.get("portal")
    if isinstance(po, dict):
        if po.get("ok"):
            env_s = {"ok": "env AF_JOBS_DATA 在位",
                     "missing": "env 缺 AF_JOBS_DATA（A8）",
                     "unknown": "env 未验证（ssh 不可达，仅注记不判死）"}.get(po.get("env"),
                                                                         "env 未知")
            L.append(f"[门户] gov 公网门户 ok  healthz ok  open_total {po.get('open_total')}  "
                     f"{env_s}")
        else:
            L.append(f"[门户] gov 公网门户探针失败：{po.get('error') or '未知原因'}（A8 红）")

    tl = s.get("trigger_liveness")
    if isinstance(tl, dict):
        L.append(f"[安灯] 收件箱活性安灯 {tl.get('status')}（自述 {tl.get('criterion_status') or '-'}，"
                 f"判据龄 {tl.get('criterion_age_s')}s/陈旧阈 {tl.get('stale_after_s')}s，"
                 f"静默 {tl.get('silent_s')}s/阈 {tl.get('threshold_min')}min，"
                 f"码 {tl.get('alarm_code') or '-'}）"
                 + ("　★安灯腿失活：判据陈旧，读数不得当成活"
                    if tl.get("stale") else ""))

    # D-113 /data 恢复腿 + 回落留痕（红队分诊 H3；只读 img-gc 耐久证据投影）
    gr = s.get("gc_recovery")
    if isinstance(gr, dict):
        lr = gr.get("last_recovery") or {}
        la = gr.get("last_apply") or {}
        peak = gr.get("peak_pct")
        peak_s = (time.strftime("%F %T", time.localtime(gr.get("peak_epoch")))
                  if gr.get("peak_epoch") else "-")
        L.append(f"[gc-recovery] /data 现值 {gr.get('current_use_pct')}%｜"
                 f"未解释峰值 {peak}%（{peak_s}，窗 {gr.get('peak_window_s') // 86400} 天）｜"
                 f"末次成功 apply 事后水位 {gr.get('baseline_pct')}%｜"
                 f"停手线命中 {gr.get('stop_line_hits')} 次｜证据 {gr.get('n_records')} 行")
        if lr.get("tier"):
            L.append(f"  恢复腿档位 {lr.get('tier')}（use_pct={lr.get('use_pct')}）："
                     f"L1 白名单候选 {lr.get('L1_n')} 项、预估回收 "
                     f"{lr.get('L1_est_reclaim_bytes')} B；L2 {lr.get('L2_n')} 项"
                     f"（不自动执行）｜报告件 {lr.get('report_path')}")
        else:
            L.append(f"  恢复腿未启动｜末次 apply：/data {la.get('use_pct')}% "
                     f"ok={la.get('ok')} reason={la.get('reason') or '-'}")
        if gr.get("read_err"):
            L.append(f"  ★证据读取失败（fail-closed）：{gr.get('read_err')}")

    al = s["alarms"]
    n_red = sum(1 for x in al if x["level"] == "red")
    n_amb = sum(1 for x in al if x["level"] == "amber")
    L.append(f"[安灯] 红 {n_red} / 黄 {n_amb}")
    if not al:
        L.append("  （无报警）")
    for x in al:
        mark = "红灯" if x["level"] == "red" else "黄灯"
        L.append(f"  [{mark}] {x['code']} since {x['since']}  {x['message']}")

    arc = s.get("archived_arms") or {}
    if arc.get("n"):
        L.append(f"  [已归档臂] {arc['n']} 臂（fix1 终态矩阵，慢性信号已归档见巡检日志）")

    L.append("[成本] 各档案累计（跨三档聚合）")
    L.append(f"  {'档案':<16}{'runs':>6}{'tokens_in':>14}{'tokens_out':>13}{'cache_read':>14}")
    for c in s["cost"]:
        L.append(f"  {c['profile']:<16}{c['runs']:>7}"
                 f"{c['tokens_in']:>15}{c['tokens_out']:>14}{c['tokens_cache']:>15}")
    L.append("=" * 72)
    return "\n".join(L)


# ---------- 主流程 ----------

def public_snapshot(snap):
    """公网发布面投影：剥**只进本地 latest.json** 的键（trigger_liveness / gc_recovery）。

    发布面顶层键集 = publish-scrub-gate.py DATA_TOP **人工审定冻结集**；未审新键会被
    --freeze-keys 拦＝整轮拒发＝公网看板停更。故活性安灯读数段（2026-11-04 批）与
    D-113 /data 恢复腿读数段（gc_recovery）一律只进本地全量快照，不进公网 data.json。
    """
    return {k: v for k, v in snap.items()
            if k not in ("trigger_liveness", "gc_recovery")}


def one_round(state, mode):
    t = time.time()
    arms = scan_all_arms(state, t)
    plan = scan_plan_tiers()
    sched = scan_scheduler(state, t)
    extras = scan_extra_schedulers(t)
    anolis = scan_anolis(state, t)
    anolis["local_sweb_images"] = scan_local_images(state, t)
    relay = scan_relay()
    portal = scan_portal()   # RT 收口批（2026-11-02）：gov 公网门户三签名巡检
    # ⑦ 活性安灯聚合段（风险#7 收口批 2026-11-04）：**只读**安灯判据文件
    # （写入方=event-router），把安灯读数抬进机器可读全量快照。
    trigger_liveness = scan_trigger_liveness(t)
    # D-113：/data 恢复腿与回落留痕判据（**只读** img-gc 耐久证据；写入方=img-gc.py，
    # 本件只消费）——停手线触顶后的恢复腿档位/L1 候选/预估回收量、未解释峰值与
    # 回落判据，抬进安灯（A10/A11）与本地全量快照。
    gc = read_gc_recovery_state(t)
    archived, _active = classify_archived(arms, sched, extras, t)
    # D-112：臂态三态标注（与 classify_archived 边界对齐）+ 缺失 episode 计时
    # （arm_missing_seen 落 watch-state，重启不重报一次性码）
    classify_arm_states(arms, archived, state, t)
    alarms = build_alarms(arms, sched, anolis, relay, plan, state, t, extras, archived,
                          portal=portal, trigger_liveness=trigger_liveness, gc=gc)
    snap = build_snapshot(arms, plan, sched, anolis, relay, alarms, mode, extras, archived,
                          portal=portal, trigger_liveness=trigger_liveness, gc=gc)

    write_atomic(LATEST, json.dumps(snap, ensure_ascii=False, indent=1))
    # P0-2（2026-10-28）：data.json=公网发布物 → K/O scrub 后落盘；
    # scrub 真源缺失/异常 → 保留上一版（不写坏数据上网，宁可停更不可泄密），
    # 本地 latest.json 与 alarms.log 不受影响（运维面保留原文）。
    # 键集冻结（publish-scrub-gate.py DATA_TOP）：公网发布面顶层键集是**人工审定
    # 冻结项**，未审新键会被 --freeze-keys 拦＝整轮拒发＝公网看板停更；本批禁改
    # 该闸（新键入冻结集须人工审定 + 重锚钉桩 + 变更日志登记），故安灯段与 D-113
    # 恢复腿读数段**只进本地全量快照 latest.json**，不进发布面 data.json（与
    # trigger_liveness 同纪律；发布面键集与既有键内容零变化）。
    try:
        pub = public_snapshot(snap)
        write_atomic(DASH_DATA, json.dumps(scrub_public(pub), ensure_ascii=False))
    except Exception as e:
        print(f"[{now_s()}] data.json 脱敏失败，保留上一版: {e}", flush=True)
    if mode == "daemon":
        log_alarms(alarms, state, t)
        # 采样历史推进（保留窗）
        state["line_hist"].append([int(t), {a["dir"]: a["n_total"] for a in arms}])
        state["line_hist"] = [s for s in state["line_hist"] if t - s[0] <= 2400]
    save_state(state)
    return snap


# ---------- D-112 三态夹具自检（--selftest：零生产副作用） ----------

def _selftest_d113(PASS, FAIL, check, sandbox, T):
    """D-113（factory-os#81）/data 恢复腿+回落留痕夹具自检。

    夹具面（形态照抄 img-gc-evidence.jsonl 实录 2026-11-07 复核）：
      · 10-22 两条成功 apply（77→71 / 85→43，deleted 8/82）= baseline 来源
      · 11-04~11-06 停手线/HALT 拒绝 apply（use_pct 91~100）= 未解释峰值来源
      · 11-07 两条 kind=recovery（L1 / L3）= 恢复腿读数来源
    零生产副作用：GC_EVIDENCE 重定向沙箱；不跑真实 watch 轮。
    """
    global GC_EVIDENCE
    import importlib.util
    saved_gc_ev = GC_EVIDENCE
    ev = os.path.join(sandbox, "img-gc-evidence.jsonl")
    rows = [
        # 10-22 两次成功 GC（baseline=43）
        {"kind": "apply", "ts": "2026-10-22 04:16:59", "epoch": T - 16 * 86400,
         "host": "anolis", "use_pct": 77, "use_pct_after": 71, "ok": True, "deleted": 8},
        {"kind": "apply", "ts": "2026-10-22 21:48:38", "epoch": T - 15 * 86400 - 3600,
         "host": "anolis", "use_pct": 85, "use_pct_after": 43, "ok": True, "deleted": 82},
        # 11-04 HALT 拒绝（峰值 100）
        {"kind": "apply", "ts": "2026-11-04 13:30:57", "epoch": T - 3 * 86400,
         "host": "anolis", "use_pct": 100, "ok": False,
         "reason": "HALT 哨兵在场，拒绝执行（人工停手）"},
        # 11-06 停手线回报 ×2（93 / 100）
        {"kind": "apply", "ts": "2026-11-06 06:20:09", "epoch": T - 86400,
         "host": "anolis", "use_pct": 100, "ok": False,
         "reason": "use_pct 100% ≥ 停手线 88%，只 plan 停手回报"},
        {"kind": "apply", "ts": "2026-11-06 10:42:35", "epoch": T - 3600,
         "host": "anolis", "use_pct": 93, "ok": False,
         "reason": "use_pct 93% ≥ 停手线 88%，只 plan 停手回报"},
        # D-113 恢复腿证据（L1 档：8 候选/33.48GB）
        {"kind": "recovery", "card": "D-113", "ts": "2026-11-07 06:09:35",
         "epoch": T - 600, "host": "anolis", "use_pct": 93, "tier": "L1",
         "tier_reason": "L1 白名单候选 8 项", "L1_n": 8,
         "L1_est_reclaim_bytes": 33480000000, "L2_n": 20,
         "report_path": "/sandbox/recovery-x.json", "auto_delete": False, "ok": True},
    ]
    with open(ev, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    GC_EVIDENCE = ev
    try:
        # ---- 读数 ----
        gc = read_gc_recovery_state(T)
        check("D-113 读数：证据 6 行全解析", gc["n_records"] == 6, f"got {gc['n_records']}")
        check("D-113 读数：baseline=末次成功 apply 事后水位 43",
              gc["baseline_pct"] == 43, f"got {gc['baseline_pct']}")
        check("D-113 读数：未解释峰值=100（11-04 HALT 拒绝那次）",
              gc["peak_pct"] == 100 and gc["peak_epoch"] == T - 3 * 86400,
              f"got {gc['peak_pct']}@{gc['peak_epoch']}")
        check("D-113 读数：停手线命中 2 次（不含 HALT 拒绝）",
              gc["stop_line_hits"] == 2, f"got {gc['stop_line_hits']}")
        check("D-113 读数：末条 recovery 档位 L1/候选 8/预估 33.48GB",
              gc["last_recovery"]["tier"] == "L1"
              and gc["last_recovery"]["L1_n"] == 8
              and gc["last_recovery"]["L1_est_reclaim_bytes"] == 33480000000,
              f"got {gc['last_recovery']}")

        # ---- A10/A11 判据（纯函数夹具）----
        gi = gc_recovery_alarm_inputs(gc, 70, T)
        check("D-113 A10：停手线触顶（窗内刚被拒）+ 恢复腿档位 L1 ⇒ 触发",
              gi["a10"] and gi["stop_active"], gi["a10_why"])
        check("D-113 A11：未解释峰值 100→现值 70（落差 30pp≥5pp）⇒ 触发",
              gi["a11"], gi["a11_why"])
        gi_b = gc_recovery_alarm_inputs(gc, 100, T)
        check("D-113 A11 负例：现值=峰值 100（零回落）⇒ 不触发",
              not gi_b["a11"], gi_b["a11_why"])
        # A10 活条件：停手线触顶已久（超出回看窗）+ 现值低于停手线 + 恢复腿无档位
        # ⇒ 不报红（避免「水已退、红灯常亮」的告警疲劳；chronic 真相由快照段承载）
        _stale_apply = dict(gc["last_apply"], epoch=T - GC_PEAK_WINDOW_S - 7200)
        gi_stale = gc_recovery_alarm_inputs(
            dict(gc, last_recovery=None, last_apply=_stale_apply), 70, T)
        check("D-113 A10 负例：停手线触顶超窗+现值<停手线 ⇒ 不报红（活条件非永久红）",
              not gi_stale["a10"] and not gi_stale["stop_active"], gi_stale["a10_why"])
        # A10 活条件：现值≥停手线（现场正触顶）即便上次 apply 已旧 ⇒ 报红
        gi_live = gc_recovery_alarm_inputs(
            dict(gc, last_recovery=None, last_apply=_stale_apply), 93, T)
        check("D-113 A10 活条件：现值 93≥停手线 88 ⇒ 报红（现场正触顶）",
              gi_live["a10"] and gi_live["stop_active"], gi_live["a10_why"])
        # A10 活条件：恢复腿**确有档位**且触顶仍新鲜 ⇒ 报红并带候选清单
        gi_tier = gc_recovery_alarm_inputs(gc, 93, T)
        check("D-113 A10：恢复腿档位 L1 + 现场触顶 ⇒ 报红且带候选清单",
              gi_tier["a10"] and "L1 候选 8 项" in gi_tier["a10_why"], gi_tier["a10_why"])
        # 回落被**峰值之后**的成功 apply 解释 ⇒ 未解释峰值清空 ⇒ 不触发
        with open(ev, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "apply", "ts": "2026-11-07 06:00:00",
                                "epoch": T - 300, "host": "anolis", "use_pct": 93,
                                "use_pct_after": 70, "ok": True, "deleted": 8},
                               ensure_ascii=False) + "\n")
        gc_explained = read_gc_recovery_state(T)
        check("D-113 A11 负例：峰值后成功 apply ⇒ 未解释峰值清空、不触发",
              gc_explained["peak_pct"] is None
              and not gc_recovery_alarm_inputs(gc_explained, 70, T)["a11"],
              f"peak={gc_explained['peak_pct']}")
        # 峰值超出回看窗（远古）⇒ 不驱动当期告警
        with open(ev, "w", encoding="utf-8") as f:
            for r in rows[:2] + [dict(rows[2], epoch=T - (GC_PEAK_WINDOW_S + 86400))]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        gc_stale = read_gc_recovery_state(T)
        check("D-113 A11 负例：峰值超出 7 天回看窗 ⇒ 不触发",
              gc_stale["peak_pct"] is None
              and not gc_recovery_alarm_inputs(gc_stale, 70, T)["a11"],
              f"peak={gc_stale['peak_pct']}")
        # 复原夹具件（后续断言用）
        with open(ev, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        gc = read_gc_recovery_state(T)
        gi_c = gc_recovery_alarm_inputs(gc, 97, T)
        check("D-113 A11 负例：落差 3pp<5pp ⇒ 不触发（正常抖动）",
              not gi_c["a11"], gi_c["a11_why"])
        check("D-113 A10 负例：gc=None ⇒ 两腿全不判（fail-closed 不猜绿）",
              gc_recovery_alarm_inputs(None, 70, T)["a10"] is False
              and gc_recovery_alarm_inputs(None, 70, T)["a11"] is False)

        # ---- 旧形态（无 recovery 证据）⇒ A10 仍须报（回归探测器）----
        gc_old = dict(gc, last_recovery=None)
        gi_d = gc_recovery_alarm_inputs(gc_old, 70, T)
        check("D-113 A10 旧形态：停手线回报且零 recovery 证据 ⇒ 仍触发",
              gi_d["a10"] and "无 kind=recovery 证据行" in gi_d["a10_why"], gi_d["a10_why"])
        gc_none = dict(gc, last_recovery=None,
                       last_apply={"epoch": T - 10, "ok": True, "use_pct": 40,
                                   "use_pct_after": 39, "reason": None})
        check("D-113 A10 负例：末次 apply 成功且无停手线 ⇒ 不触发",
              not gc_recovery_alarm_inputs(gc_none, 39, T)["a10"])
        # 恢复腿跑了但档位=None（常水位）+ 触顶已久 + 现值<停手线 ⇒ 不报红
        gc_tier_none = dict(gc,
                            last_apply=dict(gc["last_apply"],
                                            epoch=T - GC_PEAK_WINDOW_S - 7200),
                            last_recovery=dict(gc["last_recovery"], tier=None,
                                               use_pct=69))
        gi_e = gc_recovery_alarm_inputs(gc_tier_none, 70, T)
        check("D-113 A10 负例：恢复腿已跑但档位=None 且触顶已久 ⇒ 不报红",
              not gi_e["a10"] and "停手线未触顶" in gi_e["a10_why"], gi_e["a10_why"])
        # 同形状但**现场正触顶**（现值 93）⇒ 仍须报红（腿没对这次触顶产出档位）
        gi_f = gc_recovery_alarm_inputs(gc_tier_none, 93, T)
        check("D-113 A10 活条件：档位=None 但现场正触顶 ⇒ 仍报红",
              gi_f["a10"] and "档位=None" in gi_f["a10_why"], gi_f["a10_why"])

        # ---- build_alarms 接线（含一次性闩锁）----
        st = {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": [],
              GC_FALLBACK_LATCH_KEY: 0}
        anolis = {"ok": True, "disk": {"/data": {"use_pct": 70, "size": "308G",
                                                "used": "215G", "avail": "92G"}},
                  "sweb_images": 118, "image_target": 120, "ollama": "ok",
                  "load": {"m1": 13.57, "m5": 8.02, "m15": 7.06}}
        al = build_alarms(
            [], {"status_file_exists": True, "mtime_stale": False,
                 "proc_confirmed_down": False, "alive": False, "running_arms": []},
            anolis, {"consecutive_failures": 0, "last_event": "-"}, [], st, T,
            extras=None, archived=None, portal=None, trigger_liveness=None, gc=gc)
        a10_al = [x for x in al if x["code"] == GC_RECOVERY_CODE]
        a11_al = [x for x in al if x["code"] == GC_FALLBACK_CODE]
        check("D-113 build_alarms：A10 专码 gc-recovery 落 alarms 面（red）",
              len(a10_al) == 1 and a10_al[0]["level"] == "red", f"got {a10_al}")
        check("D-113 build_alarms：A11 回落无留痕落 alarms 面（amber）",
              len(a11_al) == 1 and a11_al[0]["level"] == "amber", f"got {a11_al}")
        check("D-113 A11 一次性：同峰值第二轮不重报（闩锁落 watch-state）",
              st[GC_FALLBACK_LATCH_KEY] == gc["peak_epoch"]
              and not [x for x in build_alarms(
                  [], {"status_file_exists": True, "mtime_stale": False,
                       "proc_confirmed_down": False, "alive": False,
                       "running_arms": []},
                  anolis, {"consecutive_failures": 0, "last_event": "-"}, [], st, T,
                  extras=None, archived=None, portal=None, trigger_liveness=None,
                  gc=gc) if x["code"] == GC_FALLBACK_CODE])
        check("D-113 负例：gc=None 时 build_alarms 零 D-113 码（旧调用路径不崩）",
              not [x for x in build_alarms(
                  [], {"status_file_exists": True, "mtime_stale": False,
                       "proc_confirmed_down": False, "alive": False,
                       "running_arms": []},
                  anolis, {"consecutive_failures": 0, "last_event": "-"}, [],
                  {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []}, T,
                  extras=None, archived=None, portal=None, trigger_liveness=None)
                  if x["code"] in (GC_RECOVERY_CODE, GC_FALLBACK_CODE)])

        # ---- 快照接线 + render_report 呈现 ----
        snap = build_snapshot(
            [], {"D1": 40, "D2": 40, "D3": 40},
            {"status_file_exists": True, "alive": False, "pids": [],
             "mtime_age_s": None, "summary": None},
            anolis, {"consecutive_failures": 0, "last_event": "-"}, al, "once",
            extras=None, archived=None, portal=None, trigger_liveness=None, gc=gc)
        gr = snap.get("gc_recovery")
        check("D-113 快照：gc_recovery 段进本地 latest.json（机器可读投影）",
              isinstance(gr, dict) and gr["peak_pct"] == 100
              and gr["current_use_pct"] == 70
              and GC_RECOVERY_CODE in gr["alarm_codes"], f"got {gr}")
        # 发布面冻结集对账（真源=publish-scrub-gate.py DATA_TOP；真源缺席则 SKIP 不猜）
        _gate_top = None
        try:
            _gs = importlib.util.spec_from_file_location(
                "af_publish_gate_d113_top",
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "publish-scrub-gate.py"))
            _gm = importlib.util.module_from_spec(_gs)
            _gs.loader.exec_module(_gm)
            _gate_top = set(_gm.DATA_TOP)
        except Exception:  # noqa: BLE001
            _gate_top = None
        if _gate_top is None:
            print("SKIP D-113 发布面冻结对账（publish-scrub-gate.py 真源缺席）")
        else:
            check("D-113 快照：gc_recovery 不在 DATA_TOP 冻结集且被 pub 投影剥除",
                  "gc_recovery" not in _gate_top
                  and set(public_snapshot(snap)) == _gate_top,
                  f"in_top={'gc_recovery' in _gate_top}")
        rep = render_report(snap)
        check("D-113 报告：[gc-recovery] 行含现值/未解释峰值/恢复腿档位",
              "[gc-recovery]" in rep and "恢复腿档位 L1" in rep
              and "预估回收 33480000000 B" in rep, rep[-600:])

        # ---- 证据文件缺席 ⇒ fail-closed（不报绿也不假红）----
        GC_EVIDENCE = os.path.join(sandbox, "no-such-evidence.jsonl")
        gc_missing = read_gc_recovery_state(T)
        check("D-113 负例：证据件缺席 ⇒ 全字段 None 且零报警判据",
              gc_missing["last_apply"] is None and gc_missing["peak_pct"] is None
              and not gc_recovery_alarm_inputs(gc_missing, 70, T)["a10"]
              and not gc_recovery_alarm_inputs(gc_missing, 70, T)["a11"])
    finally:
        GC_EVIDENCE = saved_gc_ev


def _selftest():
    """D-112（factory-os#80）臂态三态显式化自检：在跑/自然退役/目录消失三态
    夹具各一 + 负例（禁 0 冒充在案/一次性/复活重报/≥N 天转 retired/legacy
    兼容）。纪律照 test-tmp-write-admission.py：零生产副作用——不跑真实 watch
    轮（不写生产 latest.json/data.json/watch-state.json/alarms.log，全部路径
    重定向沙箱）；bench_proc_dirs 打桩（不依赖 /proc 实况）。

    跑法：python3 -I tools/factory-watch.py --selftest   （期望末行 ALL PASS，rc=0）
    """
    global bench_proc_dirs, LATEST, DASH_DATA, ALARMS_LOG, STATE_FILE
    import importlib.util
    import shutil
    import tempfile

    sandbox = tempfile.mkdtemp(prefix="factory-watch-d112-selftest-")
    LATEST, DASH_DATA = f"{sandbox}/latest.json", f"{sandbox}/data.json"
    ALARMS_LOG, STATE_FILE = f"{sandbox}/alarms.log", f"{sandbox}/watch-state.json"
    bench_proc_dirs = lambda: set()   # 打桩：episode 判据不依赖 /proc 实况
    PASS, FAIL = [], []

    def check(name, cond, detail=""):
        (PASS if cond else FAIL).append(name)
        print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))

    T = 1792610000.0
    RETIRE_S = ARM_RETIRE_AFTER_S
    d_run = os.path.join(sandbox, "bench-fix1-d1-glm-cp")      # 夹具①在跑
    d_ret = os.path.join(sandbox, "bench-fix1-d1-step5")       # 夹具②自然退役
    d_mis = os.path.join(sandbox, "bench-fix1-d2-m31f")        # 夹具③目录消失（不建）
    RES_ROWS = (
        '{"task_id": "t1", "status": "completed", "reward": true}\n'
        '{"task_id": "t2", "status": "completed", "reward": false}\n')

    def write_res(d, age_s):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "results.jsonl"), "w", encoding="utf-8") as f:
            f.write(RES_ROWS)
        os.utime(os.path.join(d, "results.jsonl"), (T - age_s, T - age_s))

    def one_round(state, t):
        """一轮（夹具面）：scan_arm→classify_archived→classify_arm_states→build_alarms。"""
        arms = []
        for tier, prof, path in (("D1", "glm-cp", d_run), ("D1", "step-5", d_ret),
                                 ("D2", "mavis-m31f", d_mis)):
            a = scan_arm(path)
            a["tier"], a["profile"] = tier, prof
            # scan_all_arms 常补的两个键（快照 totals/键集要用）；夹具面无历史线
            a["rows_10m"] = 0
            a["last_new_row_age_s"] = None
            arms.append(a)
        archived, _ = classify_archived(arms, {"running_arms": []}, [], t)
        classify_arm_states(arms, archived, state, t)
        alarms = build_alarms(
            arms, {"status_file_exists": True, "mtime_stale": False,
                   "proc_confirmed_down": False, "alive": False, "running_arms": []},
            {}, {"consecutive_failures": 0, "last_event": "-"}, [], state, t,
            extras=None, archived=archived, portal=None, trigger_liveness=None)
        return arms, archived, alarms

    try:
        write_res(d_run, 60)                                   # 在跑：60s 前有结果
        write_res(d_ret, ARCHIVE_MATURITY_S + 120)             # 自然退役：>6h 无关联进程
        st = {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []}

        # ---- 夹具①在跑 ----
        arms, archived, alarms = one_round(st, T)
        a_run = arms[0]
        check("夹具①在跑：目录在案+结果新鲜", a_run["exists"] and a_run["n_tasks"] == 2)
        check("夹具①在跑：arm_state=running", a_run["arm_state"] == "running",
              f"got {a_run.get('arm_state')}")
        check("夹具①在跑：不入 classify_archived 归档集",
              d_run not in {x["dir"] for x in archived})
        check("夹具①在跑：无 bench-arm-vanished（本臂键）",
              not [x for x in alarms if x["key"] == f"{ARM_VANISH_CODE}:D1-glm-cp"])

        # ---- 夹具②自然退役（与 classify_archived 边界对齐）----
        a_ret = arms[1]
        check("夹具②自然退役：入归档集（mtime>6h 无关联进程）",
              d_ret in {x["dir"] for x in archived})
        check("夹具②自然退役：arm_state=retired", a_ret["arm_state"] == "retired",
              f"got {a_ret.get('arm_state')}")
        check("夹具②自然退役：无 bench-arm-vanished（目录在案≠消失，本臂键）",
              not [x for x in alarms if x["key"] == f"{ARM_VANISH_CODE}:D1-step-5"])

        # ---- 夹具③目录消失 ----
        a_mis = arms[2]
        check("夹具③目录消失：exists=false 且全零", (not a_mis["exists"])
              and a_mis["n_total"] == 0 and a_mis["n_tasks"] == 0)
        check("夹具③目录消失：arm_state=missing", a_mis["arm_state"] == "missing",
              f"got {a_mis.get('arm_state')}")
        check("夹具③目录消失：vanished_new=True（首见即报）", a_mis["vanished_new"] is True)
        van = [x for x in alarms if x["code"] == ARM_VANISH_CODE]
        check("夹具③目录消失：一次性 bench-arm-vanished 报警在列", len(van) == 1,
              f"got {len(van)}")
        check("夹具③目录消失：amber 级+键含臂名",
              van and van[0]["level"] == "amber"
              and van[0]["key"] == f"{ARM_VANISH_CODE}:D2-mavis-m31f")
        # 负例：禁以 0 冒充在案——缺失臂不在归档集、A1/A2 边界不受影响、
        # 且告警存在（不静默）
        check("负例-禁0冒充在案：缺失臂不入归档集（A1/A2 边界不动）",
              d_mis not in {x["dir"] for x in archived})
        check("负例-禁0冒充在案：缺失臂有显式告警（不静默全零）", len(van) == 1)
        check("负例-禁0冒充在案：since=首见缺失时刻",
              van and van[0]["since"] == time.strftime("%F %T", time.localtime(T)))

        # ---- 一次性语义：持续缺失不复报 ----
        _, _, alarms2 = one_round(st, T + 60)
        van2 = [x for x in alarms2 if x["code"] == ARM_VANISH_CODE]
        check("一次性：第二轮持续缺失零复报", len(van2) == 0, f"got {len(van2)}")
        check("一次性：arm_state 仍为 missing（慢性真相由字段承载）",
              one_round(st, T + 60)[0][2]["arm_state"] == "missing")

        # ---- 复活重报：目录回来清 episode，再消失算新 episode ----
        write_res(d_mis, 30)
        arms3, _, alarms3 = one_round(st, T + 120)
        check("复活：arm_state 回归 running", arms3[2]["arm_state"] == "running",
              f"got {arms3[2].get('arm_state')}")
        check("复活：无 bench-arm-vanished", not [x for x in alarms3 if x["code"] == ARM_VANISH_CODE])
        shutil.rmtree(d_mis)
        _, _, alarms4 = one_round(st, T + 180)
        van4 = [x for x in alarms4 if x["code"] == ARM_VANISH_CODE]
        check("复活后再消失：新 episode 重报一次", len(van4) == 1, f"got {len(van4)}")

        # ---- ≥N 天转 retired（消失退役）----
        st2 = {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": [],
               "arm_missing_seen": {d_mis: int(T - RETIRE_S - 60)}}
        arms5, _, alarms5 = one_round(st2, T)
        check("≥N天：arm_state=retired（消失退役）", arms5[2]["arm_state"] == "retired",
              f"got {arms5[2].get('arm_state')}")
        check("≥N天：age_s≥阈值且不再复报",
              arms5[2]["arm_missing_age_s"] >= RETIRE_S
              and not [x for x in alarms5 if x["code"] == ARM_VANISH_CODE])

        # ---- data.json 接线（build_snapshot 键集 + render_report 呈现）----
        arms6, archived6, alarms6 = one_round(st2, T)
        snap = build_snapshot(
            arms6, {"D1": 40, "D2": 40, "D3": 40},
            {"status_file_exists": True, "mtime_age_s": 5, "pids": [1], "alive": True,
             "summary": {"running": 0, "done": 0, "failed": 0, "partial": 0,
                         "pending": 0, "ts": "-"}},
            {"ok": False, "error": "selftest-stub"},
            {"consecutive_failures": 0, "last_event": "-"}, alarms6, "once",
            extras=None, archived=archived6, portal=None, trigger_liveness=None)
        keys = {"arm_state", "arm_missing_since_s", "arm_missing_age_s"}
        check("data.json：arms[] 带三态键（独立字段）",
              all(keys <= set(a) for a in snap["arms"]))
        # 顶层键集冻结对账：真源=tools/publish-scrub-gate.py DATA_TOP（按路径加载，
        # 与 scrub 真源同款加载方式）；真源缺席则该检查显式 SKIP（不假装验过）
        _gate_top = None
        try:
            _gs = importlib.util.spec_from_file_location(
                "af_publish_gate_data_top",
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "publish-scrub-gate.py"))
            _gm = importlib.util.module_from_spec(_gs)
            _gs.loader.exec_module(_gm)
            _gate_top = _gm.DATA_TOP
        except Exception:  # noqa: BLE001 —— 真源缺席=不可证，SKIP 不猜
            _gate_top = None
        if _gate_top is None:
            print("SKIP data.json 顶层键集冻结对账（publish-scrub-gate.py 真源缺席）")
        else:
            # 对账面=发布面 pub（one_round 同款剥离 trigger_liveness/gc_recovery
            # ——这两键只进本地 latest.json，不进公网 data.json：前者 2026-11-04
            # 活性安灯批既定，后者 D-113 恢复腿读数同纪律）
            pub_top = set(public_snapshot(snap))
            check("data.json：顶层键集≡DATA_TOP 冻结集（零新顶层键）",
                  pub_top == set(_gate_top),
                  f"extra={sorted(pub_top - set(_gate_top))}")
        rep = render_report(snap)
        check("报告：三态灯位+普查+解耦三行在列",
              all(k in rep for k in ("在跑", "退役", "缺失", "[臂态普查]", "[臂态解耦]")))

        # ---- 负例：legacy 臂（无三态注解，如旧单测桩）不产幽灵报警 ----
        legacy = [dict(scan_arm(d_run), tier="D1", profile="glm-cp",
                       rows_10m=0, last_new_row_age_s=None)]
        la = build_alarms(
            legacy, {"status_file_exists": True, "mtime_stale": False,
                     "proc_confirmed_down": False, "alive": False, "running_arms": []},
            {}, {"consecutive_failures": 0, "last_event": "-"}, [],
            {"alarm_open": {}, "alarm_logged": {}, "sweb_img_hist": []}, T,
            extras=None, archived=None, portal=None, trigger_liveness=None)
        check("负例-legacy：无三态注解的臂零幽灵 bench-arm-vanished",
              not [x for x in la if x["code"] == ARM_VANISH_CODE])
        check("负例-legacy：render_report 对缺 arm_state 快照不崩（回落 exists 判）",
              "在跑" in render_report(build_snapshot(
                  legacy, {"D1": 40, "D2": 40, "D3": 40},
                  {"status_file_exists": True, "alive": False,
                                       "pids": [], "mtime_age_s": None, "summary": None},
                  {"ok": False, "error": "stub"},
                  {"consecutive_failures": 0, "last_event": "-"}, [], "once")))

        # ---- D-113 /data 恢复腿 + 回落留痕夹具（同沙箱，GC_EVIDENCE 重定向）----
        _selftest_d113(PASS, FAIL, check, sandbox, T)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    print(f"\n{'ALL PASS' if not FAIL else 'HAS FAIL'} ({len(PASS)}/{len(PASS) + len(FAIL)})")
    return 0 if not FAIL else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="单轮扫描并打印巡检报告")
    ap.add_argument("--selftest", action="store_true",
                    help="D-112 臂态三态夹具自检（零生产副作用，沙箱内跑）")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    args = ap.parse_args()
    os.makedirs(OBS_DIR, exist_ok=True)
    os.makedirs(DASH_DIR, exist_ok=True)
    state = load_state()
    if args.once:
        snap = one_round(state, "once")
        print(render_report(snap))
        return
    write_atomic(f"{OBS_DIR}/watchdog.pid", f"{os.getpid()}\n")
    print(f"[{now_s()}] factory-watch 常驻启动 pid={os.getpid()} 周期 {INTERVAL}s", flush=True)
    while True:
        try:
            snap = one_round(state, "daemon")
            n_red = sum(1 for x in snap["alarms"] if x["level"] == "red")
            n_amb = sum(1 for x in snap["alarms"] if x["level"] == "amber")
            print(f"[{now_s()}] 轮完成: 行 {snap['totals']['n_total']} "
                  f"(+{snap['totals']['rows_10m']}/10min) 安灯 红{n_red} 黄{n_amb}",
                  flush=True)
        except Exception as e:
            print(f"[{now_s()}] 轮异常（不退出）: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
