#!/usr/bin/env python3
"""factory-scheduler — 黑灯工厂调度中枢/管理 agent 的机械层（本机常驻，60s 周期）

定位（运营者指令，2026-10-28）：调度中枢=管理 agent；本脚本只做机械层，不等主会话，
      与 burn-runner（补货器，anolis）/event-router（事件路由器，本机）同构：无 LLM、确定性 if-then。
职责（按指令序）：
  ① 队列守恒：ssh anolis 统计 /data/bench/queue/pending 条数与"已提交未跑量"
     （=anolis 在途 af-order 进程数，pgrep -c，burn-runner.py:44 同口径；条目被弹出即移
     done/，故"在途"即"已提交未跑完"）。pending<20 时依次会商供给层：
     a) ssh anolis 'python3 /data/bench/swev-pool-gen.py --limit 40'（脚本在位才触发）；
     b) 本机 python3 tools/report-feeder.py --limit 4（在位且距上次触发>2h 才触发）。
     触发与跳过都写日志（摘要日志落盘；实际触发才写变更日志）。
  ② 健康面：三守护探活（pgrep -f，模式加 [ ] bracket 防 pgrep 自匹配/防 wrapper 误判）——
     burn-runner / stream-tailer 在 anolis，event-router 在本机；
     任一缺位→变更日志告警行 + 尝试拉起一次；连续 3 轮失败后只在每小时整点再告警（防刷屏）；
     拉起有 300s 冷却（防刷屏）。探针自身失败（ssh 不通）不算缺位，只记日志不告警不拉起。
  ③ minimax 双道接线准备：读 状态观测/quota.json 的 minimax 段（quota-governor.py 60s 刷新，
     超 600s 视为过期，fail-closed）；go=true 且（step 道不可用（quota step.go=false：套餐到期/
     额度耗尽/读取失败）**或** step 道 8 槽满（pgrep -fc 'af-orde[r].*step-5'>=8)）
     时，向 pending 写 swev 条目（unit/data_root 同 swev 池：/data/bench/swev-s1-r0）。
     2026-11-03 RT：闸判据原为「step 8 槽满」——那是 step 套餐到期**前**的负载卸载语义；
     step 2026-10-30 20:40 到期 + 运营者令 step 不再使用（计划/方法论-持续改进-20261031.md:245）
     后 step 在途恒 0 → 闸结构永闭 → 自 2026-10-28 13:58 起零派发。现判据扩为「step 不可用
     或 step 满」：step 在役时原溢出语义一字不变（step 优先、未满不派），step 停用时
     minimax 升为主通道承活（既有保护 mm_go 闸/源过期闸/mm 封顶/候选池全保留）。
     profile 名考据（任务书写的 mini-m3 并非 af 真实档案名，2026-10-28 ssh anolis 实证）：
     anolis /data/af-factory/af-p3 无独立 profile 配置文件；档案表定义在
     anolis:/data/af-factory/af-p3/crates/af-execline/src/profile.rs:29/44
     （af-order 二进制 strings 亦内嵌同表；本机 af 仓镜像 af/crates/af-bench/src/main.rs:165/180）：
       profile.rs:29 "mavis-m31f" → MiniMax-M3.1-Flash-Preview（m3.1f 档）
       profile.rs:44 "mavis-m3"    → MiniMax-M3（m3 档）
       均走 mcode OAuth + mavis 网关（状态/优惠通道.md：m3.1flash 实测免费，M3 尊重 5h 窗）。
     缺省取 mavis-m3（对应任务书 m3 档；姊妹档 mavis-m31f 用 FS_MINIMAX_PROFILE 切换）。
     条目任务=当前 pending 的 swev 池任务（跨模型交叉验证用途，计划§1 运营者令：
     "跨模型交叉验证（step×minimax×glm 三色）"），按池序补 FS_MINIMAX_LIMIT 条；
     pending 中 mm 条目封顶 FS_MINIMAX_CAP 条（防无界增长）。
     消费序提示：mm 条目文件名 90-mm- 段（与 rr55 同段，排在编号池之后）——step-first
     燃尽纪律（10-30 step 到期前知识生产优先上 step）下不会被优先弹出；要立即起用双道，
     把 MM_PREFIX 改 "00-"（rr80 同段，排序最前）即可，条目 schema 不变。
  ④ STOP 熔断 + 状态文件 + 每轮一行摘要日志（队列/在途/三守护/配额四元组）。

守护启动命令（写死；② 探活缺位时按此尝试拉起）：
  burn-runner（anolis）: ssh anolis 'cd /data/bench && nohup python3 burn-runner.py >> /data/bench/queue/burn-runner.log 2>&1 &'
  stream-tailer（anolis）: ssh anolis 'cd /data/bench/af-board && nohup python3 stream-tailer.py --daemon --interval 10 --orders-dir /data/bench/af-p3-state/orders --out-root /data/bench/af-board/stream >> tailer.log 2>&1 &'
  event-router（本机）: cd <WS> && nohup python3 tools/event-router.py >> <WS>/状态观测/event-router.log 2>&1 &

STOP 文件: tools/.factory-scheduler.STOP（在位即全局熔断，与 burn-runner/event-router 同构）
状态文件: 状态观测/factory-scheduler-state.json（熔断/冷却/供给时间戳等跨轮记忆）
摘要日志: 状态观测/factory-scheduler.log（每轮一行四元组 + 动作行）
变更日志: 计划/变更日志.md（只记真实触发/告警，与 event-router 同格式）
用法: factory-scheduler.py [--once] [--dry-run] [--force-supply] [--status]
      --once 单轮即退（自测用）；--dry-run 只探不写（不落盘/不 scp/不拉起/不改变更日志，
      与 event-router 的 ROUTER_DRY 同语义）；--force-supply 越过 pending<20 闸强制会商
      供给层（自测跳过分支用）；--status 打印状态文件即退。
环境变量（缺省=生产值）: FS_INTERVAL=60 FS_PENDING_FLOOR=20 FS_SWEV_POOL_LIMIT=40
      FS_REPORT_FEEDER_LIMIT=4 FS_REPORT_FEEDER_MIN_GAP_S=7200 FS_MINIMAX=1
      FS_FEEDER_EMERGENCY_GAP_S=1800（旁路下限）FS_FEEDER_ZERO_STOP=6（连续零产出→STOP 熔断）
      FS_FEEDER_STOP_FILE=（report-feeder 熔断文件路径，默认与 report-feeder.py 同径）
      FS_MINIMAX_PROFILE=mavis-m3 FS_MINIMAX_LIMIT=4 FS_MINIMAX_CAP=8
      FS_MINIMAX_MAX_TURNS=55 FS_MINIMAX_SPEND_CAP=300 FS_RESTART_COOLDOWN=300
      FS_QUOTA_STALE_S=600 FS_STATE= FS_LOG= FS_CHANGELOG= FS_STOP= FS_REPORT_FEEDER=
      FS_PORTAL_SEEDER= FS_SEEDER_LOCK= FS_DRY=1
      FS_PORTAL_SEEDER_MIN_OPEN=15 FS_PORTAL_SEEDER_MIN_GAP_S=300（防抖）FS_PORTAL_SEEDER_LIMIT=24
      FS_QUALITY_CARDS= FS_QUALITY_CARDS_TOP=200 FS_QUALITY_CARDS_MIN_GAP_S=7200（2h 一轮）
      FS_QUALITY_CARDS_LOCK= FS_QUALITY_CARDS_TIMEOUT_S=3600
      FS_SUPPLY_ACTIVITY=（供给活性观测面，缺省 dirname(STATE)/supply-activity.json）
      FS_SA_GATE_N=3（连续 N 轮双零→活性红）FS_SA_KINDS=arbitrate,distill FS_SA_WINDOW_CAP=12
门户水位制（2026-10-29 工单①，原"地板触发 open<10 且距上次≥30min"）：每周期（60s）检查门户
      tasks.json（DEB-4 2026-10-30：探针改走瘦查询 /tasks.json?status=open&limit=200，
      口径不变仍取 open 真实总数，实测 <0.5s；全量板默认行为不变），
      open<15 且无播种在飞（锁文件 tools/.seeder-in-flight 的 PID 活，或 pgrep
      命中 portal-seeder.py）即补种 portal-seeder --limit 24 --source all；5min 最小防抖
      （非硬间隔：76 卡/h 实测消耗下 30min≈38 卡>单次补 24，必断供）；锁文件异常残留
      （进程不在）自动清理。触发/残留清理写变更日志；水位/防抖/在飞态只进每轮摘要行。
质量卡轮换（2026-10-30 工单①，供给常态化）：KB 存量 → 质量工序卡（quality-cards.py
      --kind all --top 200；2026-11-02 RT-E32 由 --kind verify 改 all——verify 单腿使
      分歧仲裁卡/蒸馏复核卡两腿生产侧零调用，E32 对账红根因之一），2h 一轮，
      **门户水位路与 burn 队列守恒路各接一路调用**
      （调用点 1/2 = _portal_supply；调用点 2/2 = supply_round）。两路共用同一节流键
      supply.last_quality_cards_ts + 同一在飞锁 tools/.quality-cards-in-flight → 同轮
      不双跑（先到者执行，后到者见节流跳过）。卡只上门户板（gov tasks）；"合格者可作
      report 素材登记"本批保守起见不做（report-feeder 的 known 集不因质量卡变动）。
      供给活性对账门（RT-E161 shadow .rt161wip，2026-11-06）：--kind all 轮触发并解析出
      分腿计数后，对 arbitrate/distill 两腿判『轮预算在跑 ∧ 连续 N 轮产出跳过双零』⇒
      活性红（疑似 pipeline 死）——台账拦截机制②「供给活性监测（存量在板不得替代），
      红队终局轮-20261101/逃逸问题台账.md:1321」的调度器内建腿。口径（区分「真无料」与
      「腿死」）：生成>0=绿·健康产出；生成==0∧跳过>0=绿·在干活（幂等跳过=逐例核对过
      既有卡，跳过计数增长即在推进）；生成==0∧跳过==0（双零）连续 SA_GATE_N 轮=红；
      本轮无读数（触发失败/超时/JSON 不可判/ok=false）不计入窗口且连击清零——触发层
      死亡由腿成败判据（_qc_leg_out，fail-loud）与 all-gates 门族覆盖，本门不越权判红。
      腿缺席（summary 无该 kind 键=kind 收缩嫌疑，RT-E161 复发形态）按双零证据计入。
      观测面：状态观测/supply-activity.json（真跑每轮双写；缺省落 dirname(STATE)——
      夹具改道 FS_STATE 即连带改道，零写生产；DRY 不落盘，只探不写契约不破）。
      回归门：tools/test-e161-supply-liveness.py（四态负正控）。
纪律: 密钥零明文（本脚本不接触任何 key，只写队列条目/发 ssh 探针）；anolis 承担重活
      （本机只 ssh 探活/触发/落条目）；不改 af 仓；所有自动动作一行变更日志。
      外部调用纪律（DEB-1 根治 2026-10-29：两次楔死根因=子调用无超时）：全部
      ssh/scp/curl/子进程双超时（连接层 ConnectTimeout=10 + subprocess timeout +
      curl --max-time），异常路径逐个 fail-loud 记日志后按分项契约降级，不吞不楔死。
回滚: 停进程 + 删 tools/.factory-scheduler.STOP（状态/日志文件可留作审计）。
"""
import argparse
import json
import os
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
# OTel MVP 埋点（2026-10-28）：工厂链路订单面关键事件 → OTLP（tools/otel/factory_otel）。
# 端点缺省（2026-11-02 起 AF_OTEL_ENDPOINT 未设落缺省 collector，此前=静默丢弃）；
# fail-open 绝不抛回主循环；
# 熔断文件 状态观测/OTEL-STOP 在位即静默（与 FS_STOP/tailer TAILER-STOP 同模式）。
sys.path.insert(0, os.path.join(WS, "tools", "otel"))
try:
    import factory_otel as _otel
except Exception:  # noqa: BLE001 —— 埋点缺失不影响调度主职
    _otel = None
ANOLIS = "anolis"
# 外部调用唯一连接超时口径（DEB-1 2026-10-29）：BatchMode 禁交互 + ConnectTimeout=10
# 连接层上限；subprocess timeout 参数兜底总时长。ssh/scp 两族同此口径（不搞双标）。
SSH = "ssh -o BatchMode=yes -o ConnectTimeout=10"

# ---------- 可调参数（环境变量覆盖，缺省=生产值） ----------
def _env_int(k, d):
    try:
        return int((os.environ.get(k) or "").strip() or d)
    except ValueError:
        return d

INTERVAL = _env_int("FS_INTERVAL", 60)
PENDING_FLOOR = _env_int("FS_PENDING_FLOOR", 20)          # ① 队列守恒闸
SWEV_POOL_LIMIT = _env_int("FS_SWEV_POOL_LIMIT", 40)      # ①a swev-pool-gen --limit
FEEDER_LIMIT = _env_int("FS_REPORT_FEEDER_LIMIT", 4)      # ①b report-feeder --limit
FEEDER_MIN_GAP = _env_int("FS_REPORT_FEEDER_MIN_GAP_S", 7200)  # ①b 距上次>2h
# 紧急补货旁路护栏（2026-11-01 RT 修复）：旁路原为无下限豁免——pending=0 时每调度轮
# (~4min) 重触 feeder，arXiv 限流期轮轮落 0 → pending 恒 0 → 下轮再触的永动环
# （10-28→11-01 实测 1299 次重触、999 轮落 0、report 道 >35h 零补货，且对限流源
# 自我放大打点）。护栏三件：①旁路下限（豁免≠零间隔）；②连续零产出退避（×2/轮，
# 封顶 FEEDER_MIN_GAP=常规节流）；③零产出升级（连续 FEEDER_ZERO_STOP 轮落 0 → 设
# report-feeder 内置 STOP 熔断，对限流源停手；人工删文件=恢复信号，计数清零）。
FEEDER_EMERGENCY_GAP = _env_int("FS_FEEDER_EMERGENCY_GAP_S", 1800)  # ①b 旁路下限 30min
FEEDER_ZERO_STOP = _env_int("FS_FEEDER_ZERO_STOP", 6)         # ①b 连续 6 轮零产出 → STOP
FEEDER_STOP_FILE = (os.environ.get("FS_FEEDER_STOP_FILE")
                    or WS + "/tools/.report-feeder-STOP")     # 与 report-feeder.py STOP 同径
SEEDER = os.environ.get("FS_PORTAL_SEEDER") or WS + "/tools/portal-seeder.py"
# 门户水位制（2026-10-29 工单①，替代旧"地板触发+30min 硬间隔"）：
#   每周期（60s）检查，open<SEEDER_MIN_OPEN 且无播种在飞（锁文件 PID / pgrep 双判）
#   即补种 --limit SEEDER_LIMIT --source all；SEEDER_MIN_GAP 降级为最小防抖（非硬间隔）：
#   旧 30min 硬间隔下实测 76 卡/h ≈ 38 卡/30min > 单次补 24，必断供 → 10→15 且 1800s→300s。
SEEDER_MIN_OPEN = _env_int("FS_PORTAL_SEEDER_MIN_OPEN", 15)
SEEDER_MIN_GAP = _env_int("FS_PORTAL_SEEDER_MIN_GAP_S", 300)   # 最小防抖 5min（旧硬间隔 1800s 已移除）
SEEDER_LIMIT = _env_int("FS_PORTAL_SEEDER_LIMIT", 24)          # 2026-10-29 战役档 8→24：按实测消耗速率配速
# 播种在飞锁：触发前落调度进程 PID，种完即删；异常残留（PID 进程不在）下一轮自动清理。
# 语义：锁内 PID=持锁调度进程（seeder 由其同步拉起）；seeder 被孤儿化时 pgrep 兜底判在飞。
SEEDER_LOCK = os.environ.get("FS_SEEDER_LOCK") or WS + "/tools/.seeder-in-flight"
# 质量工序卡轮换（2026-10-30 工单①）：门户水位与 burn 队列守恒两路各接一路周期性调用
#   quality-cards.py --top 200（KB 存量 → 质量工序卡，卡上门户板）。2h 一轮节流。
#   两路共用同一节流键 supply.last_quality_cards_ts 与同一在飞锁 → 同轮不会双跑。
#   卡只上门户板；「合格者可作 report 素材登记」本批保守起见**不做**（report-feeder 的
#   known 集不因质量卡变动，两条供给链互不污染）。
QC_CARDS = os.environ.get("FS_QUALITY_CARDS") or WS + "/tools/quality-cards.py"
QC_TOP = _env_int("FS_QUALITY_CARDS_TOP", 200)               # --top 选源窗口深度
QC_MIN_GAP = _env_int("FS_QUALITY_CARDS_MIN_GAP_S", 7200)    # 2h 一轮
QC_TIMEOUT = _env_int("FS_QUALITY_CARDS_TIMEOUT_S", 3600)    # 单轮子进程超时（136+ 张卡要 scp）
QC_LOCK = os.environ.get("FS_QUALITY_CARDS_LOCK") or WS + "/tools/.quality-cards-in-flight"
MM_ON = os.environ.get("FS_MINIMAX", "1") == "1"          # ③ 双道接线开关
MM_PROFILE = (os.environ.get("FS_MINIMAX_PROFILE") or "mavis-m3").strip() or "mavis-m3"
MM_LIMIT = _env_int("FS_MINIMAX_LIMIT", 4)                # ③ 每轮最多补几条
MM_CAP = _env_int("FS_MINIMAX_CAP", 8)                    # ③ pending 中 mm 条目封顶
MM_MAX_TURNS = _env_int("FS_MINIMAX_MAX_TURNS", 55)       # ③ 与在役 rr55 档同轮次
MM_SPEND = _env_int("FS_MINIMAX_SPEND_CAP", 300)          # ③ 同 swev 池预算
RESTART_CD = _env_int("FS_RESTART_COOLDOWN", 300)         # ② 拉起冷却（防刷屏）
QUOTA_STALE = _env_int("FS_QUOTA_STALE_S", 600)           # ③ 配额读数过期阈值（burn-runner 同值）

STATE = os.environ.get("FS_STATE") or WS + "/状态观测/factory-scheduler-state.json"
LOG = os.environ.get("FS_LOG") or WS + "/状态观测/factory-scheduler.log"
CHANGELOG = os.environ.get("FS_CHANGELOG") or WS + "/计划/变更日志.md"
STOP = os.environ.get("FS_STOP") or WS + "/tools/.factory-scheduler.STOP"
FEEDER = os.environ.get("FS_REPORT_FEEDER") or WS + "/tools/report-feeder.py"
QUOTA = WS + "/状态观测/quota.json"

# RT-E161（2026-11-06，shadow .rt161wip）供给活性对账门常量：判据口径见文件头
# 「供给活性对账门」段与 _supply_activity_gate docstring（两处同文，改判据须同改）。
# 观测面缺省**派生自 dirname(STATE)** 而非写死生产路径：夹具/回归只改 FS_STATE 一处，
# 观测面即连带改道（test-qc-leg-truth-gate.probe_fs 只重定向 FS_STATE/FS_LOG/
# FS_CHANGELOG——若本面写死生产路径，回归探针会零声写生产观测面；派生后零写生产）。
SA_STATE = (os.environ.get("FS_SUPPLY_ACTIVITY")
            or os.path.join(os.path.dirname(STATE), "supply-activity.json"))
SA_GATE_N = _env_int("FS_SA_GATE_N", 3)      # 连续 N 轮双零→红（提案 L3 N=3，2h 节拍≈6h 无消化）
SA_KINDS = tuple(k.strip() for k in
                 (os.environ.get("FS_SA_KINDS") or "arbitrate,distill").split(",") if k.strip())
SA_WINDOW_CAP = _env_int("FS_SA_WINDOW_CAP", 12)   # 观测面每腿保留最近轮数（观测用，不参与判定）

SWEV_POOL_GEN = "/data/bench/swev-pool-gen.py"   # anolis 在位才触发（2026-10-28 实测不在位）
PENDING = "/data/bench/queue/pending"            # anolis 队列目录
SWEV_ROOT = "/data/bench/swev-s1-r0"             # swev 池 data_root（mm 条目同根）
MM_PREFIX = "90-mm-"                             # mm 条目文件名前缀（与 rr55 同 90 段）

# ② 三守护：探活模式 + 拉起命令（启动命令与头部注释逐字一致）
DAEMONS = {
    "burn-runner": {
        "host": "anolis", "short": "burn",
        "pgrep": 'pgrep -f "burn-runne[r]"',
        "start": "cd /data/bench && nohup python3 burn-runner.py >> /data/bench/queue/burn-runner.log 2>&1 &",
    },
    "stream-tailer": {
        "host": "anolis", "short": "tailer",
        "pgrep": 'pgrep -f "stream-taile[r]"',
        "start": ("cd /data/bench/af-board && nohup python3 stream-tailer.py --daemon --interval 10 "
                  "--orders-dir /data/bench/af-p3-state/orders --out-root /data/bench/af-board/stream "
                  ">> tailer.log 2>&1 &"),
    },
    "event-router": {
        "host": "local", "short": "router",
        "pgrep": 'pgrep -f "event-route[r]"',
        "start": "nohup python3 tools/event-router.py >> 状态观测/event-router.log 2>&1 &",
    },
    # 2026-10-28 巡检修复：推送器静默死亡 18h 致 gate.json 过期、burner 拒补货——
    # 探活名单补第四员（与 burn/tailer/router 同构自愈）。
    "factory-status-push": {
        "host": "local", "short": "push",
        "pgrep": 'pgrep -f "factory-status-pus[h]"',
        "start": "nohup python3 tools/factory-status-push.py >> 状态观测/status-push.log 2>&1 &",
    },
}

_DRY = [False]   # 干跑标志（log/changelog/save_state 据此静默落盘）


_PORTAL = {"open": None, "act": ""}   # 门户水位观测（喂每轮摘要行；_portal_supply 更新）

# 投放闸读数（PoC-B 2026-11-03：anolis release-gate 的 CONWIP 水位；_gate_read 更新）。
# 开关：FS_GATE_READ=1（缺省，只读进摘要行，fail-open 不改任何判定）；
#       FS_GATE_REFILL_ACT=1（缺省 0，灰度：NeedRefill 时与 pending<20 供给动作**并联**）。
_GATE = {"wip": None, "upper": None, "refill": None, "act": ""}
GATE_READ = _env_int("FS_GATE_READ", 1)
GATE_REFILL_ACT = _env_int("FS_GATE_REFILL_ACT", 0)
GATE_BIN = "/data/bench/release-gate/release-gate"
GATE_DB = "/data/bench/release-gate/gate.db"


def _pid_alive(pid):
    """pid 存活判定（os.kill 0 探针）。ESRCH=不在；EPERM/其余=保守视为在（不误清锁）。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _seeder_in_flight():
    """播种在飞判定（工单①）：锁文件 tools/.seeder-in-flight（PID 活）优先，
    pgrep 兜底（防 seeder 被孤儿化）。锁文件进程不在=异常残留→自动清理并记日志。
    返回 (in_flight, note)。"""
    if os.path.exists(SEEDER_LOCK):
        pid = None
        try:
            pid = int((open(SEEDER_LOCK, encoding="utf-8").read() or "").strip())
        except (OSError, ValueError):
            pid = None
        if _pid_alive(pid):
            return True, f"锁文件在飞 pid={pid}"
        try:
            os.remove(SEEDER_LOCK)
            log(f"门户水位制：锁文件异常残留已自动清理（{os.path.basename(SEEDER_LOCK)}，"
                f"pid={pid} 进程不在）")
        except OSError as e:
            log(f"门户水位制：锁文件残留清理失败（{e}）")
    # DEB-1：pgrep 探针自身超时/失败 ≠ 无播种在飞——保守判在飞不触发（防双启），记日志
    try:
        r = sh('pgrep -fc "portal-seede[r].py"', timeout=20)
    except subprocess.TimeoutExpired:
        log("门户水位制：pgrep 在飞探针超时（>20s），保守视为在飞，本轮不补种（防双启）")
        return True, "pgrep 探针超时（保守判在飞）"
    except OSError as e:
        log(f"门户水位制：pgrep 在飞探针失败（{type(e).__name__}: {str(e)[:60]}），"
            "保守视为在飞，本轮不补种（防双启）")
        return True, "pgrep 探针失败（保守判在飞）"
    if r.returncode in (0, 1):
        try:
            n = int((r.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            n = 0
        if n >= 1:
            return True, f"pgrep 命中 {n} 个 portal-seeder 进程"
    return False, ""


def _quality_cards_in_flight():
    """质量卡在飞判定（工单①）：锁文件 tools/.quality-cards-in-flight（PID 活）优先，
    pgrep 兜底（防 quality-cards 被孤儿化）。锁文件进程不在=异常残留→自动清理并记日志。
    返回 (in_flight, note)。"""
    if os.path.exists(QC_LOCK):
        pid = None
        try:
            pid = int((open(QC_LOCK, encoding="utf-8").read() or "").strip())
        except (OSError, ValueError):
            pid = None
        if _pid_alive(pid):
            return True, f"锁文件在飞 pid={pid}"
        try:
            os.remove(QC_LOCK)
            log(f"质量卡轮换：锁文件异常残留已自动清理（{os.path.basename(QC_LOCK)}，"
                f"pid={pid} 进程不在）")
        except OSError as e:
            log(f"质量卡轮换：锁文件残留清理失败（{e}）")
    try:
        r = sh('pgrep -fc "quality-cards.p[y]"', timeout=20)
    except subprocess.TimeoutExpired:
        log("质量卡轮换：pgrep 在飞探针超时（>20s），保守视为在飞，本轮不触发（防双启）")
        return True, "pgrep 探针超时（保守判在飞）"
    except OSError as e:
        log(f"质量卡轮换：pgrep 在飞探针失败（{type(e).__name__}: {str(e)[:60]}），"
            "保守视为在飞，本轮不触发（防双启）")
        return True, "pgrep 探针失败（保守判在飞）"
    if r.returncode in (0, 1):
        try:
            n = int((r.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            n = 0
        if n >= 1:
            return True, f"pgrep 命中 {n} 个 quality-cards 进程"
    return False, ""


def _qc_summary_doc(stdout):
    """解析质量卡 stdout 里的 indent=1 JSON 摘要（顶层 ok + summary 分腿计数）。

    （RT-E161 shadow，2026-11-06：从 _qc_leg_out 原样提出的公共解析面——腿成败判据
    与供给活性门共用**同一次解析逻辑**，两判据永不漂移；本函数只读不写。）
    返回 dict（含 "ok" 键）或 None（无可解析的预期形状摘要——调用方 fail-loud/不判）。"""
    txt = stdout or ""
    lines = txt.split("\n")
    dec = json.JSONDecoder()
    starts, off = [], 0
    for ln in lines:
        if ln.strip() == "{":          # indent=1 打印的顶层 JSON 起始行（独占一行）
            starts.append(off)
        off += len(ln) + 1
    for s in reversed(starts):
        try:
            d, _ = dec.raw_decode(txt[s:])
        except ValueError:
            continue
        if isinstance(d, dict) and "ok" in d:
            return d
    return None


def _qc_leg_out(stdout, rc):
    """质量卡腿输出解析（2026-11-03 RT 修复：轮换腿的成败判据）。

    旧码取 stdout 末行当摘要：quality-cards.py 打印的是 indent=1 的多行 JSON，
    末行恒为「}」→ 状态面（supply.last_quality_cards_out）与变更日志恒记
    「已触发：}」，「成功」与「全批失败」完全不可区分（RT「质量卡轮换腿成败判据
    结构性不可判」）。且 ok 只看 returncode，而 quality-cards 此前逐项失败也恒
    exit 0（同一批修）→ 腿全败也记 qc:+、变更日志恒记「已触发」。

    现口径（口径同 report-feeder 腿的 returncode 判据，口径来源见 :847-852 注）：
      · 解析 stdout 里的 JSON 摘要（顶层 ok + summary 各腿 生成/跳过/失败 计数），
        拼成一行可读摘要写状态面与变更日志；
      · ok = (退出码 == 0) 且 (JSON 顶层 ok 为 true)——两个判据同时成立才算成功；
      · JSON 不可解析 → fail-loud 判失败（绝不把「读不出」当成功；旧码在此读到的
        是恒真的「}」）。
    解析面在 _qc_summary_doc（RT-E161 提出，与供给活性门同源）。
    返回 (out, ok)：out 恒为一行可读文本。"""
    txt = stdout or ""
    doc = _qc_summary_doc(txt)
    if doc is None:
        tail = (txt.strip().splitlines() or ["<空>"])[-1][:80]
        return (f"不可判：stdout 无预期 JSON 摘要（exit={rc}，末行 {tail}）", False)
    summ = doc.get("summary") or {}
    parts = []
    for k in sorted(summ):
        s = summ[k] or {}
        parts.append("%s 生成%s/跳过%s/失败%s" % (k, s.get("generated", 0),
                                                 s.get("skipped_existing", 0),
                                                 s.get("failed", 0)))
    out = "ok=%s %s exit=%s" % (str(doc.get("ok")).lower(),
                                " ".join(parts) if parts else "无分腿摘要", rc)
    return (out, rc == 0 and doc.get("ok") is True)


def _save_supply_activity(st):
    """供给活性观测面双写腿（RT-E161，2026-11-06）。

    工厂状态文件（factory-scheduler-state.json 的 supply_activity 段，经 save_state）
    是事实源；本函数把同一段**双写**到独立观测面 SA_STATE（状态观测/supply-activity.json，
    缺省 dirname(STATE) 派生）——给门族/人读的机器可读单件，与状态文件逐轮一致。
    原子写（tmp+os.replace，save_state 同款）；DRY 模式不落盘（「只探不写」契约，
    与 save_state/changelog 同门）。"""
    if _DRY[0]:
        return
    try:
        os.makedirs(os.path.dirname(SA_STATE), exist_ok=True)
        tmp = SA_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "gate_n": SA_GATE_N, "kinds": list(SA_KINDS),
                       "legs": st.get("supply_activity") or {}},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, SA_STATE)
    except OSError as e:
        log(f"供给活性观测面写入失败: {e}")


def _supply_activity_gate(st, qc_stdout, ok=True, why=""):
    """供给活性对账门（RT-E161 shadow，2026-11-06）：对 --kind all 轮的
    arbitrate/distill 两腿判『轮预算在跑 ∧ 连续 N 轮产出跳过双零』⇒ 活性红。

    判据口径（ask 判据原文的操作定义；「真无料」与「pipeline 死」之分）：
      · 生成>0                 → 绿·健康产出（连击清零）；
      · 生成==0 ∧ 跳过>0      → 绿·在干活（幂等跳过=逐例核对过既有卡——跳过计数
                                 增长即腿在推进输入面；RT-E161 现势「arb 生成0/跳过175」
                                 即此合法形态，不红）；
      · 生成==0 ∧ 跳过==0     → 双零：腿被触发、预算在花，却既无新卡也无一次幂等
                                 跳过=疑似腿死/输入面断裂。连续 SA_GATE_N 轮（缺省 3）
                                 即红；红只在该轮首次达成时写一条变更日志（一次性，
                                 后续红轮只记观测面不刷屏），转绿后重新武装；
      · 腿缺席（summary 无该 kind 键）：按双零证据计入（kind 收缩回 verify 单腿=
                                 RT-E161 根因复发形态），note 点名「缺席」；
      · 本轮无读数（qc_stdout 为 None / JSON 不可判 / 顶层 ok 非 true）：不计入
                                 窗口且连击清零——触发层死亡由 _qc_leg_out 成败判据
                                 （fail-loud 记「触发失败」）与 all-gates 门族覆盖，
                                 本门不越权判红、也不拿坏读数假绿。
    状态面双写：st["supply_activity"]（随 save_state 进工厂状态文件）+
    SA_STATE 观测面独立落盘（_save_supply_activity；DRY 不落盘）。
    返回 {kind: 该腿最新判定 dict}（供调用点与回归门断言）。"""
    st.setdefault("supply_activity", {})
    doc = _qc_summary_doc(qc_stdout) if qc_stdout is not None else None
    readable = doc is not None and doc.get("ok") is True   # 轮预算在跑=轮真触发且读数可判
    summ = (doc or {}).get("summary") or {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    verdicts = {}
    for kind in SA_KINDS:
        g = st["supply_activity"].setdefault(
            kind, {"streak": 0, "verdict": "green", "note": "尚无读数", "window": []})
        if not readable:
            g["streak"], g["verdict"] = 0, "green"
            g["note"] = "本轮无读数（触发失败/超时/JSON 不可判/ok=false），窗口不计入"
            verdicts[kind] = dict(g)
            continue
        s = summ.get(kind)
        if isinstance(s, dict):
            gen = int(s.get("generated") or 0)
            skip = int(s.get("skipped_existing") or 0)
            fail = int(s.get("failed") or 0)
            present = True
        else:
            gen = skip = fail = 0          # 腿缺席：无双零之外的任何活动证据
            present = False
        g["window"] = (g.get("window") or []) + [
            {"ts": now, "gen": gen, "skip": skip, "fail": fail, "present": present}]
        g["window"] = g["window"][-SA_WINDOW_CAP:]
        if gen > 0:
            g["streak"], g["verdict"] = 0, "green"
            g["note"] = "健康产出（生成%d/跳过%d/失败%d）" % (gen, skip, fail)
        elif skip > 0:
            g["streak"], g["verdict"] = 0, "green"
            g["note"] = "幂等跳过在干活（生成0/跳过%d/失败%d）" % (skip, fail)
        else:
            g["streak"] = int(g.get("streak") or 0) + 1
            miss = "" if present else "（腿缺席=kind收缩嫌疑）"
            if g["streak"] >= SA_GATE_N:
                g["verdict"] = "red"
                g["note"] = ("连续%d轮产出跳过双零%s→疑似pipeline死"
                             % (g["streak"], miss))
                if g["streak"] == SA_GATE_N:   # 达红首轮才告警（一次性，防 2h 一刷）
                    log(f"供给活性门：{kind} {g['note']}（{why}）")
                    changelog(f"供给活性告警（RT-E161）：{kind} {g['note']}"
                              f"（判据：轮预算在跑∧连续{SA_GATE_N}轮生成跳过双零；"
                              f"观测面 {os.path.basename(SA_STATE)}；{why}）")
            else:
                g["verdict"] = "green"
                g["note"] = "双零观察中（连击%d/%d）%s" % (g["streak"], SA_GATE_N, miss)
        verdicts[kind] = dict(g)
    _save_supply_activity(st)
    return verdicts


def _quality_cards_supply(st, why):
    """质量工序卡轮换供给（2026-10-30 工单①）：2h 一轮调用 quality-cards --top 200。

    门户水位路与 burn 队列守恒路各接一路调用；两路共用同一节流键
    （supply.last_quality_cards_ts）与同一在飞锁 → 同轮不会双跑（先到者执行，
    后到者见节流跳过）。卡只上门户板（gov tasks）：合格者可作 report 素材登记，
    本批保守起见**不做**登记（report-feeder 的 known 集不因质量卡变动）。
    返回 acts 列表（触发=["qc:+"]，DRY=["qc:would"]，失败=["qc:fail"]，否则空）。"""
    try:
        if not os.path.exists(QC_CARDS):
            log(f"质量卡轮换：quality-cards 不在位（{QC_CARDS}），跳过")
            return []
        st.setdefault("supply", {}).setdefault("last_quality_cards_ts", 0)
        gap = time.time() - st["supply"]["last_quality_cards_ts"]
        if gap < QC_MIN_GAP:
            log(f"质量卡轮换：{why} → 距上次 {int(gap)}s<{QC_MIN_GAP}s，跳过（2h 一轮）")
            return []
        inflight, note = _quality_cards_in_flight()
        if inflight:
            log(f"质量卡轮换：{why} → 在飞（{note}），跳过")
            return []
        # RT-E32（2026-11-02）：原 --kind verify 只跑 gen_verify_r3（quality-cards.py main
        # 按 kind 分派，gen_arbitrate 仅 kind∈{all,arbitrate} 执行且全仓无其他生产调用者）
        # → 分歧登记后仲裁卡自 2026-10-29 17:04 零产出、百例分歧无卡可裁（E32-RECON
        # 现势红的回路根因）。改 --kind all：同一轮恢复 ②分歧仲裁卡 + ③蒸馏复核卡两腿；
        # 幂等不靠 kind（divergence_key/卡目录精确名/gov 去重腿），重跑只跳已存在卡不双发。
        cmd = f"python3 {QC_CARDS} --kind all --top {QC_TOP} --advance-window"
        if _DRY[0]:
            # DRY 同样更新内存节流键（与真跑同语义）：本轮内第二个调用点会看到
            # 「距上次 <2h 跳过」→ 两路不双跑在 DRY 里也可见（状态文件不落盘）。
            st["supply"]["last_quality_cards_ts"] = time.time()
            log(f"质量卡轮换：{why} → [DRY] 将触发 {cmd}")
            return ["qc:would"]
        try:
            with open(QC_LOCK, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            log(f"质量卡轮换：锁文件写入失败（{e}），仍触发（pgrep 兜底判在飞）")
        qc_out = None   # RT-E161：质量卡 stdout 原文（供给活性门同源读数；异常路=None=无读数）
        try:
            r2 = sh(cmd, timeout=QC_TIMEOUT)
            qc_out = r2.stdout
            # 2026-11-03 RT 修复（轮换腿成败判据）：旧码取 stdout 末行当摘要——本腿
            # 打印的是 indent=1 的多行 JSON，末行恒为「}」→ 状态面与变更日志恒记
            # 「已触发：}」；且 ok 只看 returncode（quality-cards 此前逐项失败也恒
            # exit 0，同批修）→ 腿全败也记 qc:+。现口径：解析 JSON 摘要，ok 须
            # 「退出码 0 且 JSON 顶层 ok 为 true」同时成立；不可解析即判失败（fail-loud）。
            out, ok = _qc_leg_out(r2.stdout, r2.returncode)
            if not ok:
                log(f"质量卡轮换：quality-cards 本轮记失败（exit={r2.returncode}）："
                    f"{out[:120]}")
        except subprocess.TimeoutExpired:
            log(f"质量卡轮换：触发超时（>{QC_TIMEOUT}s，子进程已终止）——本轮记失败")
            out, ok = f"触发超时（>{QC_TIMEOUT}s）", False
        except OSError as e:
            log(f"质量卡轮换：触发失败 {type(e).__name__}: {str(e)[:80]}")
            out, ok = f"触发失败 {type(e).__name__}", False
        finally:
            try:
                os.remove(QC_LOCK)
            except OSError:
                pass
        # RT-E161 集成点（2026-11-06 shadow，--kind all 腿产出计数面）：腿成败判据
        # （_qc_leg_out）落账后，同一读数喂供给活性对账门——arbitrate/distill 两腿
        # 『轮预算在跑 ∧ 连续 SA_GATE_N 轮生成跳过双零』⇒ 红（疑似 pipeline 死；
        # 跳过>0=幂等在干活=绿）。状态面双写 st["supply_activity"] +
        # 状态观测/supply-activity.json（_save_supply_activity）。本行只在此真跑路
        # 可达：DRY 轮在上方 qc:would 分支提前返回（不跑子进程、无读数、不落盘），
        # 「只探不写」契约不破。锚点纪律：下方取样行文本是 test-qc-leg-truth-gate
        # tamper_fs 的源码锚（:237），不得改写/改缩进。
        _supply_activity_gate(st, qc_out, ok=ok, why=why)
        st["supply"]["last_quality_cards_ts"] = time.time()
        st["supply"]["last_quality_cards_out"] = out
        changelog(f"质量卡轮换：{why} → quality-cards --top {QC_TOP}（2h 一轮）"
                  f"{'已触发' if ok else '触发失败'}：{out[:100]}")
        acts = ["qc:+" if ok else "qc:fail"]
        return acts
    except Exception as e:
        log(f"质量卡轮换异常: {e}")
        return []


def _portal_open_count():
    """门户 tasks.json 的 open 条数（curl/解析失败返回 None，调用方按探针失败处理）。

    DEB-4（2026-10-30 产线续能批）：改走瘦查询路径 /tasks.json?status=open&limit=200
    ——全量板实测 6000+ 条 1.9MB、单次拉取 0.8–3.3s，而本探针只要 open 数；瘦路径
    只回 200 条、实测 <0.5s。响应形状两吃：新版门户的瘦路径信封
    {"tasks":[…],"total":N,…}（total＝open 真实总数，不受 limit 截断）与旧版门户的
    裸数组（门户未重启/回滚时仍可读）——按形状分派，不靠门户版本号猜。
    形状不可识别（如门户未重启、路径带参被 404）时返回 None（fail-loud，绝不把
    读不到当 open=0 去误触发播种）。

    DEB-1（2026-10-29）：curl --max-time 20 + subprocess timeout=30 双超时；异常路径
    fail-loud——超时/OS/解析失败各记一行日志后返回 None（与契约一致，不靠调用方泛捕获
    兜底，也不把半截输出当数据用）。"""
    import json as _json
    import subprocess as _sp
    try:
        raw = _sp.run(["curl", "-s", "--max-time", "20",
                       "https://jobs.hkmingdajiaoyu.com/tasks.json?status=open&limit=200"],
                      capture_output=True, text=True, timeout=30).stdout
        doc = _json.loads(raw)
        if isinstance(doc, dict):
            total = doc.get("total")
            if isinstance(total, int):
                return total
            tasks = doc.get("tasks")
            if isinstance(tasks, list):
                return sum(1 for t in tasks if t.get("status") == "open")
            log("门户水位制：瘦路径响应形状不可识别（无 total 也无 tasks），本轮不判定")
            return None
        return sum(1 for t in doc if t.get("status") == "open")
    except subprocess.TimeoutExpired:
        log("门户水位制：tasks.json 读取超时（curl --max-time 20 / subprocess 30s），本轮不判定")
        return None
    except Exception as e:  # noqa: BLE001 —— 探针失败按降级处理，记日志不吞
        log(f"门户水位制：tasks.json 读取/解析失败: {type(e).__name__}: {str(e)[:80]}")
        return None


def _portal_supply(st):
    """门户水位制（2026-10-29 工单①）：每周期（60s）检查，open<15 且无播种在飞
    （锁文件/pgrep 双判）即补种 --limit 24 --source all；5min 最小防抖替代旧 30min
    硬间隔（76 卡/h 实测消耗下 30min≈38 卡>补 24，必断供）；锁文件残留自动清理。
    返回 acts 列表（触发=["seeder:+"]，DRY=["seeder:would"]，否则空）。"""
    try:
        nopen = _portal_open_count()
        if nopen is None:
            _PORTAL["act"] = "探针失败"
            log("门户水位制：tasks.json 读取/解析失败，本轮不判定（不误触发）")
            return []
        _PORTAL["open"] = nopen
        st.setdefault("supply", {}).setdefault("last_seeder_ts", 0)
        gap = time.time() - st["supply"]["last_seeder_ts"]
        if nopen >= SEEDER_MIN_OPEN:
            _PORTAL["act"] = f"充足(≥{SEEDER_MIN_OPEN})"
            return []
        # 质量工序卡轮换（2026-10-30 工单①·调用点 1/2）：门户板缺卡时同路接一路
        # quality-cards --top 200（2h 一轮节流，与队列守恒路共用节流键→不双跑）。
        qc_acts = _quality_cards_supply(st, f"门户水位 open={nopen}<{SEEDER_MIN_OPEN}")
        if not os.path.exists(SEEDER):
            _PORTAL["act"] = "seeder 不在位"
            log(f"门户水位制：open={nopen}<{SEEDER_MIN_OPEN} 但 portal-seeder 不在位（{SEEDER}），跳过")
            return qc_acts
        inflight, note = _seeder_in_flight()
        if inflight:
            _PORTAL["act"] = f"播种在飞({note})"
            return qc_acts
        if gap < SEEDER_MIN_GAP:
            _PORTAL["act"] = f"防抖 {int(gap)}s/{SEEDER_MIN_GAP}s"
            return qc_acts
        _PORTAL["act"] = f"触发 --limit {SEEDER_LIMIT} --source all"
        log(f"门户水位制：open={nopen}<{SEEDER_MIN_OPEN} 且无播种在飞、防抖已过"
            f"（{int(gap)}s）→ 补种 --limit {SEEDER_LIMIT} --source all")
        if _DRY[0]:
            return qc_acts + ["seeder:would"]
        try:
            with open(SEEDER_LOCK, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            log(f"门户水位制：锁文件写入失败（{e}），仍触发（pgrep 兜底判在飞）")
        try:
            sh(f"python3 {SEEDER} --limit {SEEDER_LIMIT} --source all", timeout=600)
        except subprocess.TimeoutExpired:
            # DEB-1：触发超时→子进程已被 run() 终止；记失败并释放锁（防抖窗顺延覆盖重试间隔）
            log(f"门户水位制：portal-seeder 触发超时（>600s，子进程已终止）——本轮记失败")
            return qc_acts + ["seeder:fail"]
        except OSError as e:
            log(f"门户水位制：portal-seeder 触发失败 {type(e).__name__}: {str(e)[:80]}")
            return qc_acts + ["seeder:fail"]
        finally:
            try:
                os.remove(SEEDER_LOCK)
            except OSError:
                pass
        st["supply"]["last_seeder_ts"] = time.time()
        changelog(f"门户任务自动补种触发（水位制 open={nopen}<{SEEDER_MIN_OPEN}，"
                  f"--limit {SEEDER_LIMIT} --source all）")
        return qc_acts + ["seeder:+"]
    except Exception as e:
        _PORTAL["act"] = f"异常 {str(e)[:60]}"
        log(f"门户守恒异常: {e}")
        return []


def log(msg):
    """日志单通道：live 只直接 append LOG，不 print（W2-C19 同类收口，与
    factory-keepalive.py:357 klog 同款）。

    旧实现 print(stdout)+append LOG 双通道，而在役启动行
    `nohup python3 tools/factory-scheduler.py >> 状态观测/factory-scheduler.log 2>&1 &`
    （factory-keepalive.py:1288）与 keepalive spawn（stdout=lf、stderr=STDOUT，
    factory-keepalive.py:507-510）都把 stdout 重定向进同一文件——每行日志必写两次
    （2026-11-01 实测 factory-scheduler.log 相邻重复 8,511/17,522 行=48.6%，
    轮次/动作/告警读数翻倍）。现 live 只保留直接 append 单通道；stdout 不再承载
    日志，既有上岗命令的重定向退化为仅接崩溃 traceback（照旧落同一文件、恰好一次）。
    DRY 模式（不落盘）仍走 stdout——文件通道未启用，无双写可言，且 --dry-run
    需可见输出。单通道性由 log_single_channel_selfcheck() 启动断言兜底（live 上岗前跑）。"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    if _DRY[0]:
        print(line, flush=True)
        return
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"日志落盘失败: {e}", file=sys.stderr)


def _fail_selfcheck(reason):
    print(f"factory-scheduler 拒绝带病上岗：{reason}", file=sys.stderr)
    sys.exit(3)


def log_single_channel_selfcheck():
    """日志单通道启动断言（W2-C19 同类收口，factory-keepalive.py:375 同款）：
    live 上岗前一条探针后 LOG 必须恰 +1 行。

    若 stdout 又被重定向到 LOG 且 log() 双通道回归，探针会使行数 +2——即刻带原因
    退出拒跑（exit 3），防日志体积/轮次计数再度翻倍。行数按字节 '\\n' 计、不解码
    正文（DEB-3 教训：并发写撕裂的坏字节会让文本读在解码处掀翻常驻进程）。
    只在 live 模式跑：DRY 模式 log() 不落盘（走 stdout），探针判据不适用。"""
    try:
        with open(LOG, "rb") as f:
            before = f.read().count(b"\n")
    except OSError:
        before = 0
    log("日志单通道自检探针行（应恰出现一次）")
    try:
        with open(LOG, "rb") as f:
            after = f.read().count(b"\n")
    except OSError as e:
        _fail_selfcheck(f"LOG {LOG} 不可读（{e}）")
        return
    if after - before != 1:
        _fail_selfcheck(
            f"日志双写回归：一条探针 log 后 LOG 行数 {before}→{after}"
            f"（增量 {after - before}≠1）。log 只走直接 append 单通道，"
            f"stdout 不得再重定向到 {LOG}"
        )


def changelog(text):
    """真实触发/告警才写变更日志（与 event-router.py:49 同格式同门）。"""
    if _DRY[0]:
        log("变更日志(DRY 跳过落盘): " + text)
        return
    line = f"| {time.strftime('%Y-%m-%d %H:%M')} | 调度中枢(自动) | {text} |\n"
    try:
        os.makedirs(os.path.dirname(CHANGELOG), exist_ok=True)
        with open(CHANGELOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        log(f"变更日志写入失败: {e}")
    log("变更日志: " + text)


# ---------- 子进程原语（密钥零明文：只跑探针/触发/落条目，不碰任何 key） ----------
# DEB-1（2026-10-29 义务收口批）：三次楔死根因=子调用无超时。纪律：
#   · 每个原语都带 subprocess timeout（总时长上限）；ssh/scp 族另带 ConnectTimeout
#     （连接层上限，与 SSH 常量同口径 10s；scp 不经 SSH 常量，选项就地显式写）；
#   · curl 走 --max-time（连接+传输总上限）+ subprocess timeout 双保险；
#   · 异常路径 fail-loud：调用方逐个 try/except（TimeoutExpired/OSError），记日志后
#     按各分项契约降级（探针→None/fail-closed、触发→记失败继续、拉起→记失败），
#     不吞异常、不让单点超时拖死整轮（主循环兜底捕获仍在，属最后防线）。

def sh(cmd, timeout=90):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def ash(cmd, timeout=60):
    """anolis shell 片段（调用方传入的 cmd 不得含单引号；内部用双引号防 glob）。"""
    return subprocess.run(f"{SSH} anolis '{cmd}'", shell=True, capture_output=True, text=True, timeout=timeout)


def apy(script, timeout=90):
    """anolis python 片段经 stdin 送入（免远程引号地狱）。"""
    return subprocess.run(f"{SSH} anolis python3 -", shell=True, capture_output=True, text=True,
                          timeout=timeout, input=script)


# 远程快照：pending 条数 / mm 条目覆盖 / 在役任务集 / swev 池清单（一次 ssh 拿全）
SNAP = r'''
import json, glob, os
out = {"pending_count": 0, "mm_count": 0, "pending_tasks": [], "mm_tasks": [], "pool": []}
out["pending_count"] = len(glob.glob("/data/bench/queue/pending/*.json"))
mmg = glob.glob("/data/bench/queue/pending/__MM_PREFIX__*.json")
out["mm_count"] = len(mmg)
mmt = set()
for f in mmg:
    try:
        t = json.load(open(f)).get("task")
        if t:
            mmt.add(t)
    except Exception:
        pass
out["mm_tasks"] = sorted(mmt)
ts = set()
for f in glob.glob("/data/bench/queue/pending/*.json"):
    try:
        t = json.load(open(f)).get("task")
    except Exception:
        continue
    if t:
        ts.add(t)
out["pending_tasks"] = sorted(ts)
out["pool"] = sorted(os.path.basename(p)[:-5] for p in glob.glob("/data/bench/swev-s1-r0/*.json"))
print(json.dumps(out, ensure_ascii=False))
'''.replace("__MM_PREFIX__", MM_PREFIX)


def _pgrep_count(res):
    """pgrep -c/-fc：无匹配时打印 0 且 exit=1；ssh 失败 exit=255。返回 int 或 None。"""
    if res.returncode == 255:
        return None
    try:
        return int((res.stdout or "").strip().splitlines()[-1])
    except Exception:
        return None


def collect():
    """一轮只读探针：anolis 快照 + 在途 + 三守护 + 配额。任一失败只降级该分项（fail-closed）。

    DEB-1（2026-10-29）：每个探针调用逐个 try/except（TimeoutExpired/OSError）——单点
    超时只记日志并把该分项降级为 None（fail-closed），不再让一个探针的 TimeoutExpired
    冒泡到主循环把整轮探针全部带崩（与 docstring 的"任一失败只降级该分项"契约对齐）。"""
    d = {"error": "", "pending_count": -1, "mm_count": 0, "pending_tasks": [], "mm_tasks": [],
         "pool": [], "inflight": -1, "step_inflight": -1, "daemons": {}, "quota": read_quota()}
    try:
        r = apy(SNAP, timeout=90)
    except subprocess.TimeoutExpired:
        log(f"collect：anolis 快照探针超时（>90s），按不可达降级（其余 anolis 分项同跳过）")
        r = None
    except OSError as e:
        log(f"collect：anolis 快照探针失败: {type(e).__name__}: {str(e)[:80]}")
        r = None
    if r is None:
        d["error"] = "anolis 不可达（快照探针超时/失败）"
    elif r.returncode == 255:
        d["error"] = "anolis 不可达（快照失败）"
    elif r.returncode != 0:
        d["error"] = f"anolis 快照异常: {(r.stderr or r.stdout or '').strip()[:100]}"
    else:
        try:
            d.update(json.loads((r.stdout or "").strip().splitlines()[-1]))
        except Exception as e:
            d["error"] = f"anolis 快照解析失败: {e}"
    if d["error"].startswith("anolis 不可达"):
        # 连接类失败：其余 anolis 探针必然同样失败，跳过省时；本机分项照常
        d["inflight"] = None
        d["step_inflight"] = None
    else:
        for _key, _cmd in (("inflight", "pgrep -c af-order"),
                           ("step_inflight", 'pgrep -fc "af-orde[r].*step-5"')):
            try:
                d[_key] = _pgrep_count(ash(_cmd, timeout=30))
            except subprocess.TimeoutExpired:
                log(f"collect：anolis 在途探针超时（{_cmd} >30s），该分项降级为 None（fail-closed）")
                d[_key] = None
            except OSError as e:
                log(f"collect：anolis 在途探针失败（{_cmd}）: {type(e).__name__}: {str(e)[:60]}")
                d[_key] = None
    for name, spec in DAEMONS.items():
        try:
            if spec["host"] == "local":
                res = sh(spec["pgrep"], timeout=20)
            else:
                res = ash(spec["pgrep"], timeout=30)
        except subprocess.TimeoutExpired:
            _to = 20 if spec["host"] == "local" else 30
            log(f"collect：{name} 探针超时（>{_to}s），该分项降级为 None（fail-closed，不判缺位）")
            d["daemons"][name] = {"up": None, "err": f"探针超时（>{_to}s）"}
            continue
        except OSError as e:
            log(f"collect：{name} 探针失败: {type(e).__name__}: {str(e)[:60]}，"
                "该分项降级为 None（fail-closed，不判缺位）")
            d["daemons"][name] = {"up": None, "err": f"探针失败 {type(e).__name__}"}
            continue
        if res.returncode == 255 or (spec["host"] == "local" and res.returncode not in (0, 1)):
            d["daemons"][name] = {"up": None, "err": (res.stderr or "").strip()[:80]}
        else:
            d["daemons"][name] = {"up": res.returncode == 0, "err": ""}
    return d


def read_quota():
    """读 状态观测/quota.json（quota-governor.py 60s 刷新）。过期/缺失 → mm 不放行（fail-closed）。

    DEB-7：quota-governor 的 step/minimax 段错误形态已统一为 {"go": false, "error": "<一句>"}
    （旧形态 {"error": ...} 无 go 键 → go 为 None、形态两义）。故此处 go 恒为布尔：
    False=明确不放行（并带 error 真因），None 只可能来自「quota.json 无该段」。
    """
    q = {"stale": True, "step_go": None, "step_used": None, "mm_go": None,
         "mm_5h": None, "mm_wk": None, "age_s": None, "note": "",
         "step_err": None, "mm_err": None}
    try:
        st = json.load(open(QUOTA, encoding="utf-8"))
    except Exception as e:
        q["note"] = f"quota.json 不可读: {str(e)[:80]}"
        return q
    ts = st.get("ts") or 0
    age_ms = time.time() * 1000 - ts
    q["age_s"] = int(age_ms / 1000)
    q["stale"] = age_ms > QUOTA_STALE * 1000
    step, mm = st.get("step") or {}, st.get("minimax") or {}
    q["step_go"], q["step_used"] = step.get("go"), step.get("used_percent")
    q["mm_go"], q["mm_5h"], q["mm_wk"] = mm.get("go"), mm.get("five_hour_remaining_pct"), mm.get("weekly_remaining_pct")
    q["step_err"], q["mm_err"] = step.get("error"), mm.get("error")
    notes = []
    if step.get("error"):
        notes.append("step:" + str(step["error"])[:40])
    if mm.get("error"):
        notes.append("mm:" + str(mm["error"])[:40])
    if q["stale"]:
        notes.append(f"读数过期 {q['age_s']}s>{QUOTA_STALE}s")
    q["note"] = "; ".join(notes)
    return q


# ---------- ① 队列守恒 ----------

def _feeder_landed(out):
    """从 feeder 末行 stdout 抽「落 N 篇」的 N；无匹配返回 None（触发失败/超时）。"""
    i = out.find("落 ")
    if i == -1:
        return None
    j = out.find(" 篇", i + 2)
    if j == -1:
        return None
    n = out[i + 2:j]
    return int(n) if n.isdigit() else None

def _gate_read():
    """每轮读 anolis release-gate status（refill_needed/wip_minutes）。fail-open：
    ssh/闸不可达只记 ERR，不影响任何既有判定。"""
    if not GATE_READ:
        return
    _GATE.update({"wip": None, "upper": None, "refill": None, "act": ""})
    try:
        r = ash(f"{GATE_BIN} --db {GATE_DB} status", timeout=20)
        st = json.loads((r.stdout or "").strip().splitlines()[-1])
        _GATE.update({"wip": st.get("wip_minutes"), "upper": st.get("wip_upper_minutes"),
                      "refill": bool(st.get("refill_needed"))})
    except Exception as e:
        _GATE["act"] = f"ERR({type(e).__name__})"


def supply_round(st, d, force):
    acts = []
    pc = d["pending_count"]
    if pc is None or pc < 0:
        log(f"队列守恒：anolis 快照失败（{d['error']}），供给层本轮不会商")
        return acts
    # PoC-B（灰度）：闸 NeedRefill（在制断粮预警）与 pending<20 **并联**触发供给；
    # FS_GATE_REFILL_ACT=0（缺省）时本腿零作用，判定与旧码逐字节一致。
    gate_refill = GATE_READ and GATE_REFILL_ACT and _GATE["refill"] is True
    if pc >= PENDING_FLOOR and not force and not gate_refill:
        log(f"队列守恒：pending={pc}≥{PENDING_FLOOR}，供给层待命（不触发）")
        return acts
    why = (f"pending={pc}<{PENDING_FLOOR}" if pc < PENDING_FLOOR
           else f"gate NeedRefill 并联（pending={pc}，wip={_GATE['wip']}/{_GATE['upper']}）"
           if gate_refill else f"--force-supply（pending={pc}）")
    # 质量工序卡轮换（2026-10-30 工单①·调用点 2/2）：burn 队列守恒这一路接一路
    # quality-cards --top 200（2h 一轮节流，与门户水位路共用节流键→不双跑）。
    acts += _quality_cards_supply(st, f"队列守恒 {why}")
    # a) swev-pool-gen（anolis 在位才触发）
    # DEB-1：在位性探针超时/失败≠不在位——按"跳过并记日志"处理（与 255 不可达同语义），
    # 绝不把探针故障当成脚本缺席（那会永久性错跳供给层）。
    try:
        r = ash(f"test -f {SWEV_POOL_GEN} && echo PRESENT", timeout=30)
    except subprocess.TimeoutExpired:
        log(f"队列守恒：{why} → swev-pool-gen 在位性探针超时（>30s），跳过（非缺席）")
        r = None
    except OSError as e:
        log(f"队列守恒：{why} → swev-pool-gen 在位性探针失败（{type(e).__name__}: "
            f"{str(e)[:60]}），跳过（非缺席）")
        r = None
    if r is None:
        pass  # 探针故障：本轮跳过该通道（上面已记日志），继续会商 b) report-feeder
    elif r.returncode == 255:
        log(f"队列守恒：{why} → swev-pool-gen 在位性探针失败（anolis 不可达），跳过")
    elif r.stdout.strip().endswith("PRESENT"):
        if _DRY[0]:
            log(f"队列守恒：{why} → [DRY] 将触发 ssh anolis 'python3 {SWEV_POOL_GEN} --limit {SWEV_POOL_LIMIT}'")
            acts.append("pool:would")
        else:
            # DEB-1：触发调用逐个兜异常——超时/失败记一行日志与变更日志、out 记失败标记，
            # 继续走后面的 report-feeder 会商（两个供给通道互不连带）。
            try:
                r2 = ash(f"python3 {SWEV_POOL_GEN} --limit {SWEV_POOL_LIMIT}", timeout=600)
                out = ((r2.stdout or "").strip().splitlines() or [f"exit={r2.returncode}"])[-1][:200]
                ok = True
            except subprocess.TimeoutExpired:
                log(f"队列守恒：swev-pool-gen 触发超时（>600s）——记失败，继续会商 report-feeder")
                out, ok = "触发超时（>600s）", False
            except OSError as e:
                log(f"队列守恒：swev-pool-gen 触发失败: {type(e).__name__}: {str(e)[:80]}")
                out, ok = f"触发失败 {type(e).__name__}", False
            st["supply"]["last_swev_pool_gen_ts"] = time.time()
            st["supply"]["last_swev_pool_gen_out"] = out
            changelog(f"队列守恒：{why} → 供给层 swev-pool-gen --limit {SWEV_POOL_LIMIT}（anolis）"
                      f"{'已触发' if ok else '触发失败'}：{out[:100]}")
            acts.append("pool:+" if ok else "pool:fail")
            # 死角修补：严格模式产出 0（池内题全在册）→ 自动升级拉镜像扩池（冷却 2h；护栏 80G 在脚本内 fail-closed）
            if "候选" in out and "0 个" in out:
                pg = st["supply"].get("last_pool_pull_ts", 0)
                if time.time() - pg > 7200:
                    try:
                        r3 = ash(f"python3 {SWEV_POOL_GEN} --pull --max-pull 8 --limit 16", timeout=3600)
                        out3 = ((r3.stdout or "").strip().splitlines() or [f"exit={r3.returncode}"])[-1][:200]
                    except subprocess.TimeoutExpired:
                        log("扩池自动升级：swev-pool-gen --pull 触发超时（>3600s），记失败")
                        out3 = "触发超时（>3600s）"
                    except OSError as e:
                        log(f"扩池自动升级：swev-pool-gen --pull 触发失败: "
                            f"{type(e).__name__}: {str(e)[:80]}")
                        out3 = f"触发失败 {type(e).__name__}"
                    st["supply"]["last_pool_pull_ts"] = time.time()
                    changelog(f"扩池自动升级：严格模式 0 产出 → swev-pool-gen --pull --max-pull 8"
                              f"（护栏内）：{out3[:120]}")
    else:
        log(f"队列守恒：{why} → swev-pool-gen 不在位（anolis:{SWEV_POOL_GEN}），跳过")
    # b) report-feeder（本机在位且距上次>2h）
    if not os.path.exists(FEEDER):
        log(f"队列守恒：{why} → report-feeder 不在位（{FEEDER}），跳过")
        return acts
    gap = time.time() - st["supply"].get("last_report_feeder_ts", 0)
    if gap < FEEDER_MIN_GAP and pc > 0:
        log(f"队列守恒：{why} → report-feeder 距上次 {gap/60:.0f}min<{FEEDER_MIN_GAP//60}min，跳过")
        return acts
    if pc == 0:
        # 紧急补货旁路护栏（2026-11-01 RT 修复）：豁免≠零间隔。连续零产出（落 0 篇）
        # 逐轮×2 退避（下限起，封顶 FEEDER_MIN_GAP=常规节流）；连续 FEEDER_ZERO_STOP
        # 轮落 0 升级设 STOP 熔断——对限流中的 export.arxiv.org 停手（原永动环：每
        # ~4min 重触、轮轮落 0、自我加剧限流）。
        zrun = int(st["supply"].get("feeder_zero_run", 0))
        if st["supply"].get("feeder_stop_set") and not os.path.exists(FEEDER_STOP_FILE):
            # 人工删 STOP=恢复信号：计数清零，护栏重新起跑（再连败才会重设熔断）
            st["supply"]["feeder_stop_set"] = False
            st["supply"]["feeder_zero_run"] = zrun = 0
            log("紧急补货升级解除：report-feeder STOP 熔断已被删除——零产出计数清零，"
                "旁路护栏（下限/退避）重新起跑")
        if zrun >= FEEDER_ZERO_STOP:
            if not st["supply"].get("feeder_stop_set"):
                # 首次升级：设 STOP + 大声记账一次（熔断在位后整点复告防刷屏，
                # 同守护缺位告警口径；swev-pool 通道不受影响）
                if _DRY[0]:
                    log(f"队列守恒：{why} → [DRY] 连续 {zrun} 轮零产出，将设 STOP 熔断 "
                        f"{FEEDER_STOP_FILE}（不落盘）")
                    acts.append("feeder:stall-stop:would")
                    return acts
                try:
                    with open(FEEDER_STOP_FILE, "w") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 紧急补货升级："
                                f"report-feeder 连续 {zrun} 轮落 0 篇（pending=0 旁路永动环"
                                f"护栏）——排查 export.arxiv.org 限流/窗口耗尽后删除本文件恢复\n")
                except OSError as e:
                    log(f"紧急补货升级：STOP 熔断写入失败（{type(e).__name__}: "
                        f"{str(e)[:80]}）——本轮不触发，下轮再试")
                    return acts
                st["supply"]["feeder_stop_set"] = True
                changelog(f"供给停摆升级：report-feeder 连续 {zrun} 轮落 0 篇（末次："
                          f"{str(st['supply'].get('last_report_feeder_out') or '')[:60]}）"
                          f"→ 已设 STOP 熔断（{os.path.basename(FEEDER_STOP_FILE)}），"
                          f"恢复=人工删该文件（swev-pool 通道不受影响）")
                acts.append("feeder:stall-stop")
                log(f"队列守恒：{why} → 紧急补货升级：连续 {zrun} 轮零产出 → STOP 熔断已设，"
                    "本轮不触发")
                return acts
            if time.localtime().tm_min == 0:
                changelog(f"供给停摆复告：report-feeder STOP 熔断在位（连续 {zrun} 轮落 0 篇）"
                          f"——删 {os.path.basename(FEEDER_STOP_FILE)} 恢复")
            else:
                log(f"队列守恒：{why} → report-feeder STOP 熔断在位（连续 {zrun} 轮落 0 篇），"
                    "本轮不触发")
            acts.append("feeder:stall-stop")
            return acts
        eff_gap = min(FEEDER_EMERGENCY_GAP * (2 ** min(zrun, 16)), FEEDER_MIN_GAP)
        if gap < eff_gap:
            log(f"紧急补货旁路退避：pending=0 但距上次 feeder {gap/60:.0f}min<旁路下限 "
                f"{eff_gap/60:.0f}min（连续零产出 {zrun} 轮），跳过")
            return acts
        changelog(f"紧急补货旁路：pending=0 距上次 feeder {gap/60:.0f}min≥旁路下限 "
                  f"{eff_gap/60:.0f}min（连续零产出 {zrun} 轮）——节流豁免（护栏内）")
    if _DRY[0]:
        log(f"队列守恒：{why} → [DRY] 将触发 python3 {FEEDER} --limit {FEEDER_LIMIT}")
        acts.append("feeder:would")
        return acts
    # DEB-1：feeder 触发超时/失败记一行日志与变更日志，out 记失败标记（acts 不谎报成功）
    try:
        r2 = sh(f"python3 {FEEDER} --limit {FEEDER_LIMIT}", timeout=600)
        out = ((r2.stdout or "").strip().splitlines() or [f"exit={r2.returncode}"])[-1][:200]
        # E36 同族收口（2026-11-02）：以退出码为准。report-feeder 顶层失败 exit=3
        # （report-feeder.py:679）、STOP 熔断 exit=2（:502）、md5 锚拒跑 exit=4（:526），
        # 且 stdout 恒有 log 行（:73 双通道）——旧码 ok=True 无条件置位、returncode
        # 可判而不判，feeder 顶层失败也记「已触发」。口径同 quality-cards.py:172 /
        # cross-verify.py:164 / event-router.py:189 sh_rc。
        ok = r2.returncode == 0
        if not ok:
            log(f"队列守恒：report-feeder 退出码 {r2.returncode}≠0，记失败（{FEEDER}）")
    except subprocess.TimeoutExpired:
        log(f"队列守恒：report-feeder 触发超时（>600s），记失败（{FEEDER}）")
        out, ok = "触发超时（>600s）", False
    except OSError as e:
        log(f"队列守恒：report-feeder 触发失败: {type(e).__name__}: {str(e)[:80]}")
        out, ok = f"触发失败 {type(e).__name__}", False
    st["supply"]["last_report_feeder_ts"] = time.time()
    st["supply"]["last_report_feeder_out"] = out
    # 零产出计数（旁路退避/升级输入，2026-11-01）：末行抽「落 N 篇」，N>0 清零；
    # =0 或触发失败/超时（无匹配）累加——供给同样没恢复，不该重置退避。
    st["supply"]["feeder_zero_run"] = (0 if _feeder_landed(out)
                                       else int(st["supply"].get("feeder_zero_run", 0)) + 1)
    changelog(f"队列守恒：{why} → 供给层 report-feeder --limit {FEEDER_LIMIT}（本机）"
              f"{'已触发' if ok else '触发失败'}：{out[:100]}")
    acts.append("feeder:+" if ok else "feeder:fail")
    return acts


# ---------- ② 健康面 ----------

def restart(spec):
    if spec["host"] == "local":
        return sh(f"cd {WS} && {spec['start']}", timeout=60)
    return ash(spec["start"], timeout=60)


def health_round(st, d):
    acts = []
    now = time.time()
    minute = time.localtime().tm_min
    for name, spec in DAEMONS.items():
        h = st["health"].setdefault(name, {"fail": 0, "last_alarm_ts": 0, "last_restart_ts": 0})
        info = d["daemons"].get(name) or {}
        up = info.get("up")
        if up is None:
            log(f"健康面：{name} 探针失败（{info.get('err', '')}），本轮不判定/不告警/不拉起")
            continue
        if up:
            if h["fail"] > 0:
                changelog(f"守护恢复：{name}（{spec['host']}）连续 {h['fail']} 轮缺失后重新在线")
                acts.append(f"{spec['short']}=recovered({h['fail']})")
            h["fail"] = 0
            continue
        h["fail"] += 1
        # 告警：连续 1-3 轮每轮告警；第 4 轮起只在每小时整点告警（防刷屏）
        if h["fail"] <= 3 or minute == 0:
            h["last_alarm_ts"] = now
            if not _DRY[0]:
                changelog(f"守护缺位告警：{name}（{spec['host']}）连续 {h['fail']} 轮缺失"
                          + ("（整点复告）" if h["fail"] > 3 else ""))
            log(f"健康面：{name} 缺位（连续 {h['fail']} 轮）")
            acts.append(f"{spec['short']}=down({h['fail']})")
        # 拉起：冷却内不重复尝试（一次拉起/300s）
        if now - h["last_restart_ts"] < RESTART_CD:
            log(f"健康面：{name} 拉起冷却中（已 {int(now - h['last_restart_ts'])}s/{RESTART_CD}s），本轮不重复拉起")
            continue
        h["last_restart_ts"] = now
        if _DRY[0]:
            log(f"健康面：[DRY] 将拉起 {name}：{spec['start'][:90]}")
            acts.append(f"{spec['short']}=would-restart")
            continue
        # DEB-1：拉起命令超时/失败记一行日志，acts 记 restart:fail（不谎报"已发起"）
        try:
            r = restart(spec)
        except subprocess.TimeoutExpired:
            log(f"健康面：尝试拉起 {name} → 失败（拉起命令超时 >60s）")
            acts.append(f"{spec['short']}=restart:fail")
            continue
        except OSError as e:
            log(f"健康面：尝试拉起 {name} → 失败 {type(e).__name__}: {str(e)[:60]}")
            acts.append(f"{spec['short']}=restart:fail")
            continue
        ok = r.returncode == 0
        log(f"健康面：尝试拉起 {name} → {'已发起' if ok else '失败 exit=%d %s' % (r.returncode, (r.stderr or '').strip()[:80])}")
        acts.append(f"{spec['short']}=restart:{'ok' if ok else 'fail'}")
    return acts


# ---------- ③ minimax 双道接线 ----------

def enqueue_mm(task, why):
    """写一条 mm 条目到 anolis pending（schema 对齐 burn-runner.py:8 队列条目）。

    why=本条**派发判据真因**（step 在途 8/8 满 / step 道不可用→minimax 承活）。
    2026-11-03 RT：note 原写死「step 8 槽满」——闸判据放宽后该文案会与真因不符
    （step 停用时写的条目仍标「8 槽满」），故按实况写入，供读队列者判读。"""
    e = {"unit": "swev", "task": task, "data_root": SWEV_ROOT, "profile": MM_PROFILE,
         "max_turns": MM_MAX_TURNS, "spend_cap": MM_SPEND,
         "note": f"scheduler: minimax 双道（{why} + minimax go）profile={MM_PROFILE}",
         "dedupe_key": f"mm-{MM_PROFILE}-{task}"}
    safe = task.replace("/", "_")
    fn = f"/tmp/fs-mm-{MM_PROFILE}-{safe}.json"
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False)
    # DEB-1：scp 带 ConnectTimeout=10（与 SSH 常量同口径；scp 不经 SSH 常量故就地显式写）
    # + subprocess timeout=60 双超时；异常路径 fail-loud 记日志返回 False（调用方按未入队处理）
    try:
        r = sh(f"scp -q -o BatchMode=yes -o ConnectTimeout=10 {fn} "
               f"anolis:{PENDING}/{MM_PREFIX}{MM_PROFILE}-{safe}.json", timeout=60)
    except subprocess.TimeoutExpired:
        log(f"minimax 条目落盘失败 {task}: scp 超时（>60s）")
        return False
    except OSError as e:
        log(f"minimax 条目落盘失败 {task}: scp 失败 {type(e).__name__}: {str(e)[:60]}")
        return False
    if r.returncode != 0:
        log(f"minimax 条目落盘失败 {task}: {(r.stderr or '').strip()[:100]}")
        return False
    return True


def minimax_round(st, d):
    acts = []
    if not MM_ON:
        log("minimax 双道：FS_MINIMAX=0 关闭，跳过")
        return acts
    if d["error"]:
        log(f"minimax 双道：anolis 快照失败（{d['error']}），跳过（fail-closed）")
        return acts
    q = d["quota"]
    # DEB-7：mm_go 恒为布尔（读失败时 go=false 带 error 真因）；旧形态的 None
    # 只剩「quota.json 无 minimax 段」一种来源——单独成支，不再与 stale 混为一谈
    if q["stale"]:
        log(f"minimax 双道：配额读数过期（{q['note'] or 'stale'}），跳过")
        return acts
    if not q["mm_go"]:
        if q.get("mm_err"):
            log(f"minimax 双道：配额读数失败（{str(q['mm_err'])[:60]}），跳过")
        elif q["mm_go"] is None:
            log("minimax 双道：配额读数缺失（quota.json 无 minimax 段），跳过")
        else:
            log(f"minimax 双道：minimax 不放行（5h 剩 {q['mm_5h']}%/周池剩 {q['mm_wk']}%），跳过")
        return acts
    si = d["step_inflight"]
    # 2026-11-03 RT（minimax 双道闸结构永闭）：闸原判据「step 8 槽满 → 溢出到
    # minimax」是 step 套餐到期**前**的负载卸载语义。step 套餐 2026-10-30 20:40
    # 到期、运营者令 step 不再使用（计划/方法论-持续改进-20261031.md:245），
    # step 在途恒 0 → 8/8 闸结构永闭 → 自 2026-10-28 13:58 起零派发
    # （状态观测/factory-scheduler.log 实测 2634 轮「step 在途 0/8 未满，跳过」）。
    # 修法（最小）：闸判据扩为「step 不可用 **或** step 8 槽满」——
    #   step_go=False（治理器判 step 不可用：无活跃订阅/额度耗尽/读取失败）
    #     → step 道承不了活，minimax 升为主通道，不再等 8/8；
    #   step_go=True（step 仍在役）→ 原溢出语义一字不改（未满不派，step 优先）；
    #   step_go=None（quota.json 无 step 段，判据不可得）→ 按 step 在役处理，
    #     仍须 8/8 满（fail-closed，不猜）。
    # 不弱化任何既有保护：mm_go 闸、源过期闸、mm 条目封顶、候选池/去重全部保留。
    step_dead = q.get("step_go") is False
    if step_dead:
        gate_why = (f"step 道不可用（{str(q.get('step_err') or 'quota step.go=false')[:60]}）"
                    f"→ minimax 承活")
    else:
        if si is None:
            log("minimax 双道：step 在途探针失败，跳过（fail-closed）")
            return acts
        if si < 8:
            log(f"minimax 双道：step 在途 {si}/8 未满，跳过")
            return acts
        gate_why = f"step 在途 {si}/8 满"
    if d["mm_count"] >= MM_CAP:
        log(f"minimax 双道：pending 中 mm 条目 {d['mm_count']}≥上限 {MM_CAP}，跳过")
        return acts
    pend, have = set(d["pending_tasks"]), set(d["mm_tasks"])
    cand = [t for t in d["pool"] if t in pend and t not in have][:MM_LIMIT]
    if not cand:
        # 2026-11-03 RT：原文案恒称「在役池任务均已有 mm 条目」，但 pending 为空时
        # 真因是「pending∩在役池=0 条」——两者给读者的处置方向不同（前者=已派过，
        # 后者=供给侧无活）。此处按实况报数，不改判据。
        inter = len(pend & set(d["pool"]))
        log(f"minimax 双道：无候选任务（pending∩在役池={inter} 条；pending 共 {len(pend)} 条、"
            f"其中已有 mm 条目 {len(have)} 条），跳过")
        return acts
    if step_dead:
        log(f"minimax 双道：{gate_why}（step 8/8 闸不适用，minimax 承活）")
    if _DRY[0]:
        log(f"minimax 双道：[DRY] {gate_why} + minimax go（5h 剩 {q['mm_5h']}%）→ "
            f"将入队 {len(cand)} 条 profile={MM_PROFILE}：{', '.join(cand)}")
        return [f"mm:would+{len(cand)}"]
    ok = [t for t in cand if enqueue_mm(t, gate_why)]
    if ok:
        st["minimax"]["written_total"] += len(ok)
        st["minimax"]["last_write_ts"] = time.time()
        st["minimax"]["last_tasks"] = ok
        changelog(f"minimax 双道接线：{gate_why} + minimax go（5h 剩 {q['mm_5h']}%）→ "
                  f"入队 {len(ok)} 条 {MM_PROFILE}（data_root={SWEV_ROOT}）：{', '.join(ok)}")
        acts.append(f"mm:+{len(ok)}")
    return acts


# ---------- ④ 状态与摘要 ----------

def load_state():
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("started_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    st.setdefault("rounds", 0)
    st.setdefault("supply", {"last_swev_pool_gen_ts": 0, "last_swev_pool_gen_out": "",
                             "last_report_feeder_ts": 0, "last_report_feeder_out": "",
                             "feeder_zero_run": 0, "feeder_stop_set": False,
                             "last_quality_cards_ts": 0, "last_quality_cards_out": ""})
    st.setdefault("health", {n: {"fail": 0, "last_alarm_ts": 0, "last_restart_ts": 0} for n in DAEMONS})
    st.setdefault("minimax", {"profile": MM_PROFILE, "written_total": 0, "last_write_ts": 0, "last_tasks": []})
    st.setdefault("last_round", {})
    # RT-E161（2026-11-06 shadow）：供给活性窗口回灌——工厂状态文件缺段（首部署/
    # 状态重置）时从独立观测面 supply-activity.json 取回连击窗口，避免部署即丢史。
    # 观测面坏/缺按空处理（best-effort：状态文件仍是事实源，读不回只损失观测连续性）。
    st.setdefault("supply_activity", {})
    if not st["supply_activity"]:
        try:
            doc = json.load(open(SA_STATE, encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("legs"), dict):
                st["supply_activity"] = doc["legs"]
        except Exception:   # noqa: BLE001 —— 缺面/坏面不拖主职，按空窗口起算
            pass
    return st


def save_state(st):
    if _DRY[0]:
        return
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
    except OSError as e:
        log(f"状态文件写入失败: {e}")


def _fmt_go(v):
    return {True: "go", False: "hold", None: "?"}.get(v, "?")


def _mm_posture(d, acts):
    """mm 道姿态读数（2026-11-03 RT 新增）：闸姿态 + 本轮是否真派发。

    `mm=go` 只是**配额裁决**（minimax 窗位够），不等于**在派发**：闸闭时（step
    到期停用后 8/8 闸永闭）配额裁决恒为 go 而实际零派发——读者据摘要会得出
    「minimax 道已放行」的相反结论。故把闸姿态（主通道/溢出待 step）与本轮
    是否真产出 mm 动作显式写进摘要，与状态文件 last_round.mm_dispatch 段同源。"""
    q = d.get("quota") or {}
    if q.get("step_go") is False:
        gate = "主通道(step停用)"
    else:
        si = d.get("step_inflight")
        gate = "溢出待step(探针失效)" if si is None else f"溢出待step({si}/8)"
    fired = any(str(a).startswith("mm:") for a in (acts or []))
    return f"{gate}+{'已派发' if fired else '未派发'}"


def summary(d, acts):
    """每轮一行摘要：队列/在途/三守护/配额四元组 + 本轮动作。"""
    q = d["quota"]
    dm = " ".join(
        f"{spec['short']}={'up' if (d['daemons'].get(n) or {}).get('up') else ('ERR' if (d['daemons'].get(n) or {}).get('up') is None else 'DOWN')}"
        for n, spec in DAEMONS.items())
    if q.get("stale"):
        stale = f"(stale {q['age_s']}s)" if q.get("age_s") is not None else "(unreadable)"
    else:
        stale = ""
    line = (f"queue pending={d['pending_count']} unrun={d['inflight']} step={d['step_inflight']}/8 | "
            f"daemons {dm} | "
            f"quota step={_fmt_go(q['step_go'])}({q['step_used']}%) "
            f"mm={_fmt_go(q['mm_go'])}(5h:{q['mm_5h']}% wk:{q['mm_wk']}%){stale} | "
            f"mm道={_mm_posture(d, acts)} | "
            f"actions={','.join(acts) if acts else 'noop'}")
    if _PORTAL["open"] is not None:
        line += f" | portal open={_PORTAL['open']} {_PORTAL['act']}"
    if GATE_READ:
        # PoC-B：投放闸 CONWIP 读数（refill=need 即断粮预警；ERR=闸读失败 fail-open）
        if _GATE["wip"] is None:
            line += f" | gate ERR {_GATE['act']}"
        else:
            line += (f" | gate wip={_GATE['wip']}/{_GATE['upper']}"
                     f" refill={'need' if _GATE['refill'] else 'ok'}{_GATE['act']}")
    return line


def otel_order_round(pending, in_flight, triggered, mode):
    """订单面埋点发射（fail-open + 失败可见）：返回记账 dict（factory_otel.guard 口径）。

    2026-11-02 RT 修复（OTel 链·守护/收割发射面可见性）：此前调用点
    `except Exception: pass` 且**丢弃 order_round 的 ok 返回值**——发射面坏了
    （collector 不可达）进程内 errors 计数在涨，无人读、无人比对、无人告警。
    现失败落两处：① 轮次日志（状态观测/factory-scheduler.log）；② 状态文件 otel 段
    （状态观测/factory-scheduler-state.json，--status 可读）——即 stats 上报面。
    熔断（OTEL-STOP 在场）/禁用（AF_OTEL_DISABLE=1）是有意静默，不算失败、不刷屏。
    """
    if _otel is None:
        return {"ok": False, "errors": 0, "skipped": 0, "exc": None, "disabled": True}
    rep = _otel.guard(_otel.order_round, pending=pending, in_flight=in_flight,
                      triggered=triggered, mode=mode, service="factory-scheduler")
    vis = _otel.visible_failure(rep, "订单面")
    if vis:
        log("[otel] " + vis)
    return rep


def otel_state_section(rep):
    """状态文件里的 otel 段（stats 上报面）：本轮记账 + 进程内累计 stats。"""
    try:
        stats = _otel.emit_stats() if _otel is not None else {}
    except Exception:  # noqa: BLE001 —— 记账读不出来也不拖主职
        stats = {}
    rep = rep or {}
    return {"ok": bool(rep.get("ok")),
            "errors": int(rep.get("errors") or 0),
            "skipped": int(rep.get("skipped") or 0),
            "exc": rep.get("exc"),
            "stats": stats,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


def round_once(st, force):
    acts = []
    d = collect()
    _gate_read()   # PoC-B：先读闸（fail-open），供给并联判定与摘要行共用
    acts += supply_round(st, d, force)
    # 门户水位制（2026-10-29 工单①）：独立于 anolis 队列底闸、每周期（60s）都查——
    # anolis pending≥20 时供给层待命，但门户是另一条供给通道（沙箱领取），不可连带跳过。
    acts += _portal_supply(st)
    acts += health_round(st, d)
    mm_acts = minimax_round(st, d)
    acts += mm_acts
    st["rounds"] += 1
    line = summary(d, acts)
    log(line)
    st["last_round"] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pending": d["pending_count"],
                        "unrun": d["inflight"], "step_inflight": d["step_inflight"],
                        "daemons": {n: (d["daemons"].get(n) or {}).get("up") for n in DAEMONS},
                        "quota": {"step_go": d["quota"]["step_go"], "mm_go": d["quota"]["mm_go"],
                                  "mm_5h": d["quota"]["mm_5h"]},
                        # mm 道姿态（2026-11-03 RT 新增）：此前 last_round.quota 只给
                        # 「step_go=false, mm_go=true」——读者据此会得出「minimax 道已
                        # 放行」的结论，而闸闭时（8/8 闸永闭）实际零派发。补本段让
                        # 派发姿态机器可读：闸判据(step_go/step_inflight) + 本轮 mm 动作。
                        "mm_dispatch": {"step_go": d["quota"].get("step_go"),
                                        "step_dead": d["quota"].get("step_go") is False,
                                        "step_inflight": d["step_inflight"],
                                        "acts": list(mm_acts)},
                        "error": d["error"]}
    if d["error"]:
        log(f"本轮探针降级：{d['error']}（相关分项 fail-closed 跳过）")
    # OTel MVP 埋点：订单面队列守恒轮次（STOP 熔断轮次不进本函数，与既有语义零交集）
    # 2026-11-02 RT：ok 不再被丢弃——失败记账落日志 + 状态文件 otel 段（见 otel_order_round）
    _orep = otel_order_round(d["pending_count"], d["inflight"], acts,
                             "dry-run" if _DRY[0] else "live")
    st["otel"] = otel_state_section(_orep)
    save_state(st)
    return acts


def main():
    ap = argparse.ArgumentParser(description="黑灯工厂调度中枢机械层（60s 周期常驻）")
    ap.add_argument("--once", action="store_true", help="单轮即退（自测用）")
    ap.add_argument("--dry-run", action="store_true", help="只探不写（不落盘/不 scp/不拉起/不改变更日志）")
    ap.add_argument("--force-supply", action="store_true", help="越过 pending<20 闸强制会商供给层（自测用）")
    ap.add_argument("--status", action="store_true", help="打印状态文件即退")
    a = ap.parse_args()
    _DRY[0] = a.dry_run or os.environ.get("FS_DRY", "") == "1"
    if a.status:
        print(json.dumps(load_state(), ensure_ascii=False, indent=1))
        return
    if not _DRY[0]:
        log_single_channel_selfcheck()
    st = load_state()
    log(f"factory-scheduler 起：周期={INTERVAL}s pending 闸={PENDING_FLOOR} "
        f"供给=swev-pool-gen(anolis,在位才触发)/report-feeder(本机,>{FEEDER_MIN_GAP//3600}h,"
        f"旁路下限{FEEDER_EMERGENCY_GAP//60}min+零产出退避,零产出{FEEDER_ZERO_STOP}轮→STOP) "
        f"三守护探活+拉起(冷却{RESTART_CD}s) minimax={'profile=' + MM_PROFILE if MM_ON else 'off'} "
        f"STOP={STOP} DRY={_DRY[0]}")
    while True:
        if os.path.exists(STOP):
            lr = st.get("last_round") or {}
            log(f"STOP 熔断在位（{os.path.basename(STOP)}），本轮无探活无动作（删之恢复）；"
                f"上轮 pending={lr.get('pending')} unrun={lr.get('unrun')} "
                f"daemons={lr.get('daemons')} quota={lr.get('quota')}")
            if a.once:
                break
            time.sleep(INTERVAL)
            continue
        try:
            round_once(st, a.force_supply)
        except Exception as e:
            log(f"循环异常（不退出）: {e}")
        if a.once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
