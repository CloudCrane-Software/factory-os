#!/usr/bin/env python3
"""event-router — 确定性事件路由器（P3-9，编排层阶段 2；本机常驻，无 LLM）

机械 if-then，四类信号 → 转移表：
  ① anolis 订单 results.jsonl 状态跃迁（ssh 轮询末行）：
     · report 单 reward=true → 该论文自动生成门户 kb-atoms 抽取种子（证据缓存+scp gov）
     · swev 单 status=max_turns 且该题尚未有 55 档复跑 → 队列追加 rr55 条目（ssh）
  ② 沙箱收割（调 tools/sandbox-harvester.py）：
     · 新 candidates JSONL 出现（验谎通过）→ registry 自动导入 + 日志
     · HARVEST-LOG 新拒收行（kb-atoms 任务）→ 自动生成 r2 任务（拒收原因写进 problem.md）
     · HARVEST-LOG 新拒收行（kb-verify 验证卡，结构性拒收）→ 自动重发新版验证卡
       （复用 tools/cross-verify.py 的卡生成，attempt+1；拒收原因 + 收割方合法 schema
       一行写进 problem.md 的「上轮为何被拒」段；同一 atom 集重发 ≤2 次，超限登记
       changelog 等运营者）。既有 kb-atoms r2 回流正则不动，两条路径互斥。
  ③ 交叉验证（运营者裁决：A 的工作交给 B 验证）：
     · 生成侧：新 candidates JSONL（A 报通过）→ 除 registry import 外，自动调
       tools/cross-verify.py 生成门户验证卡 kb-verify-<原taskid>-<attempt>[r<j>]
       （默认 --replicas 2：同一 atom 集 k 张卡，各用不同抽样种子与不同复核员视角
       提示语，状态文件按候选文件防重），验证者 B 独立抓 arXiv 证据逐条裁决 12 条原子；
     · 消费侧：portal 回报 payload 带 "verify" 的任务（ssh gov 读 reports/，兼看本地 raw/）
       → 聚合 verdict：uphold 率≥0.8 → registry admit（candidate→verified）+ 变更日志，
       并自动把 verified 原子导入 kb/ 知识库（tools/kb-ingest.py，幂等，冲刺批2 第二步）；
       裁决清单键名 verdicts 与 verifications 同义双认（与 sandbox-harvester.py 同口径），
       否则 registry reject 并自动生成 r3 重派卡（复用 r2 逻辑改后缀）。
       quote_check 全 false 的回报判为验证者摆烂，该卡作废不计（不 admit 不 reject）。
     · 分歧检测（2026-10-29 验证放大）：同一 atom 集（同候选文件）的跨卡一致率在聚合处
       记录并持续打日志（同 uphold/refute 原子比例，仅统计双方都给出明裁决的原子）；
       一致率 <1 时 changelog 登记一行「分歧检测」列双方卡号与分歧原子。
     · 跨卡裁决时序消费（2026-11-02 RT-E32 修复，本条取代旧「纯观测、不阻塞 admit」）：
       跨卡分歧不再只观测——裁决时序最新者为准，三条腿：①admit 闸（更晚的卡已判
       refute/unverifiable → 该原子不 admit，保留 candidate）；②消费腿（更晚的非 uphold
       裁决到达时，双库 verified 的原子降级：registry verified→candidate、kb
       verified→retired，欠账待独立复核翻案）；③存量回灌腿（启动时全扫留档卡对账，
       把修复前遗留的 verified 违规原子一并降级——净化批只清存量一轮，实测 2.5h 即复现
       本类，机制腿必须自愈）。豁免：依据卡 uphold∧quote_check=true 且晚于该原子全部
       非 uphold 裁决（他卡独立复核翻案，合法产物，不得误降级）。
  ⑤ 仲裁/蒸馏消费（2026-11-02 kb-arbitrate 回报链断裂修复）：
     · kb-arbitrate 仲裁回报 payload.rulings → 终裁入账：final=refute 的原子
       registry arbitrate-refute（verified→rejected 唯一例外路径）+ kb retire 双库翻案，
       依据=回报本地留档；uphold/unverifiable 只聚合登记。
     · kb-distill 蒸馏复核回报 payload.findings → 聚合 info_loss/wrong_winner 比例
       作合并蒸馏规则回归信号（纯观测，不改原子状态）。
     此前两类回报被收割方整类拒收且零消费者（HARVEST-LOG 55 行全 rejected，被判
     refute 的原子双库滞留 verified），收割方校验分支见 sandbox-harvester.py 同批修复。
  ④ MES 事件：暂不消费（①②③⑤已覆盖实用面），登记于台账备注。
护栏：kb-seed/sandbox/.router-STOP 熔断；状态文件防重放；所有自动动作一行变更日志；
      外部调用纪律（DEB-1 同款根治 2026-10-29）：全部 ssh/scp/curl/子进程双超时
      （连接层 ConnectTimeout=10 + subprocess timeout + curl --max-time），异常路径
      逐个 fail-loud 记日志后按各链路契约降级（拉取失败下轮重试/生成失败记 failed/
      推送失败不谎报已上门户），不吞不楔死；kb 入库子进程超时按 registry 规模自适应
      （基线 600s，DEB-5 重标 + DEB-5a 内层帽线性外推）、任何失败只记日志
      不阻塞主循环（ROUTER_DRY 干跑只记日志不落库）。
      kb-verify 拒收回流与既有 r2/r3/验证卡同一条熔断：STOP 在位不回流、DRY 只记日志不生成不推送。
回滚：停进程；无外部残留（r2/r3/验证卡子上 gov 前有 dry-run 布尔）。"""
import copy
import hashlib
import json
import os
import glob
import re
import shutil
import sqlite3
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
GOV = "root@gov-host.invalid"
SSH = "ssh -o BatchMode=yes -o ConnectTimeout=10"
GOV_TASKS = "/opt/company/af-jobs/data/tasks/"   # gov 门户任务目录（gov_has_tasks 在位核查用；2026-11-02 RT）
STATE_F = WS + "/kb-seed/sandbox/.router-state.json"
STOP = WS + "/kb-seed/sandbox/.router-STOP"
CHANGELOG = WS + "/计划/变更日志.md"
INTERVAL = 60
DRY = os.environ.get("ROUTER_DRY", "") == "1"  # 只打印不落盘/scp（测试用）
# ---- verified 原子自动入库 kb（冲刺批2 第二步） ----
KB_DB = WS + "/kb/kb.db"                 # kb/ 知识库（KBStore 的库）
KB_INGEST = WS + "/tools/kb-ingest.py"   # registry verified 原子 → kb/（幂等，零网络）
REGISTRY = WS + "/kb-seed/registry.db"   # 只读直查 verified 规模用（内层帽自适应的输入）
REGISTRY_CLI = WS + "/kb-seed/registry.py"  # registry 写面 CLI（admit/reject/arbitrate-refute/demote）
# 工单原口径「子进程超时 ≤120s」已于 2026-10-31 按实测重标（DEB-5）：
# kb-ingest 对真 registry 全量 verified（17986 条）冷启动导入实测 143.4/142.9/140.5s
# （p95≈143.4s），120s 预算下必然被 TimeoutExpired 掐死（实测 R4 失败：kb 入库超时（>120s）
# → 返回 None → 「成功路径返回非 dict」）。基线预算 600s = p95×2 以上余量，且仍远小于
# 事件路由器主循环 INTERVAL=60s 的容忍上限之外的单次阻塞上限（失败只记日志、不阻塞主循环）。
# 2026-11-01 DEB-5a 内层帽自适应（RT 实证假红根治）：600 静态帽与 all-gates.sh 外层帽同病
# ——工作量 ∝ registry verified（17986→23510，+30%/40h），并发门跑重载下 R4/R8 的全量导入
# 被恰 600s 掐点（item-11.log 两处「kb 入库超时（>600s，不阻塞主循环）」→ 返回 None →
# 「成功路径返回非 dict」假红；solo 同代码同数据 9/9 全绿）。修法与 tools/all-gates.sh
# DEB-5a 外层帽同款：相对校准点 17986→600s 线性外推、下限=基线 600s、向上取整到分钟粒度、
# 读不到 registry 回落校准基线（=DEB-5 收口态逐字一致）。断言侧（test-router-kb-ingest.py
# R1）同步钉死「基线常量==600 + 外推公式独立重算」，不比原「==600」松。
# 残余边界（如实登记，同 DEB-5a 政策）：帽在模块导入时取值，常驻守护不重启不随 registry
# 增长自愈；外来负载超过 DEB-5 校准包络（load 10~20）仍可能吃掉余量——按「在役重载可
# 复跑对账」处置。本自适应只消掉「registry 规模增长」这一维，不承诺吸收任意负载。
# 2026-11-02 生产生效批（E68 在役旧帽形态收口）：修复落盘（11-01 23:43）≠ 生产生效——
# 在役守护（11-01 17:54 起）未重启，带旧静态 600 帽跑了 9.5h 才被 ps lstart vs 盘面
# mtime 对账发现。两条落地：①启动行带取帽快照（见 main()），「在役进程跑的是哪个帽」
# 自此可直接从 状态观测/event-router.log 对账；②换帽=重启（keepalive 看护下 TERM 旧
# 进程即自动重拉新码），生产侧已于 2026-11-02 重启收口。残余边界本身不变：不重启不自愈。
KB_INGEST_TIMEOUT_BASELINE = 600       # DEB-5 校准基线（17986 verified → 600s，2026-10-31）
KB_TIMEOUT_CALIB_VERIFIED = 17986      # DEB-5 校准点（与 all-gates.sh DEB-5a 同源）


def _verified_count_ro():
    """只读直查 registry verified 条数（all-gates.sh reg_verified 同款）；读不到回落校准点。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
        try:
            return int(con.execute(
                "select count(*) from candidates where status='verified'"
            ).fetchone()[0])
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 缺件/库锁死一律回落校准基线，不许 import 失败
        return KB_TIMEOUT_CALIB_VERIFIED


def _kb_ingest_timeout(n):
    """DEB-5a 同款线性外推：工作量 ∝ registry verified；下限=基线；分钟粒度向上取整。"""
    t = -(-KB_INGEST_TIMEOUT_BASELINE * n // KB_TIMEOUT_CALIB_VERIFIED)  # ceil 整除
    if t < KB_INGEST_TIMEOUT_BASELINE:
        t = KB_INGEST_TIMEOUT_BASELINE
    return (t + 59) // 60 * 60


KB_INGEST_TIMEOUT_SRC_VERIFIED = _verified_count_ro()   # 取帽时的实测规模（测试对账用）
KB_INGEST_TIMEOUT = _kb_ingest_timeout(KB_INGEST_TIMEOUT_SRC_VERIFIED)
# ---- ③ 交叉验证（A 报 → B 验） ----
VERIFY_DIR = WS + "/kb-seed/sandbox/verify"      # 验证回报本地留档（registry admit 的依据文件）
RAW_DIR = WS + "/kb-seed/sandbox/raw"            # harvester 早期留存的原始回报
GOV_REPORTS = "/opt/company/af-jobs/data/reports"
VERDICTS = ("uphold", "refute", "unverifiable")
# 裁决清单的两个同义键名：verdicts（cross-verify.py 新卡模板主键）/ verifications
# （历史卡与已归档回报的老键）。与 tools/sandbox-harvester.py 的 VERIFY_LIST_KEYS 同口径。
VERIFY_LIST_KEYS = ("verdicts", "verifications")
UPHOLD_THRESHOLD = 0.8
# 收割方产出 <task_id>-<ts>.jsonl；ask 里记的 sbx-*.jsonl 命名一并认（候选 id 本就是 sbx- 前缀）
CAND_GLOBS = ("sbx-*.jsonl", "kb-atoms-*.jsonl")
CAND_DIR = WS + "/kb-seed/sandbox"
TS_SUFFIX_RE = re.compile(r"^(?P<tid>.+?)-\d{8}-\d{6}\.jsonl$")
ARX_RE = re.compile(r"(\d{4}\.\d{4,5})")
# ---- ② kb-verify 拒收回流（拒收的验证卡不得蒸发，白费上游抽取算力） ----
# 验证卡本地目录（与 tools/cross-verify.py 的 SEEDS 默认值一致；单点可改，测试可指到 scratch）
VERIFY_SEEDS = WS + "/kb-seed/sandbox/task-seeds"
# 同一 atom 集（同一份候选 JSONL）重发上限：防"坏卡死循环"（卡被拒→重发→再被拒→…）
# 2026-10-29 验证放大：k 张副本各自独立计重发上限（键含副本号，见 resend_verify_card）。
VERIFY_RESEND_CAP = 2
# 拒收文案里的合法 schema 一行示例：取收割方的 KBVERIFY_SCHEMA_LINE（单一真源，不在本文件复制）
HARVESTER = WS + "/tools/sandbox-harvester.py"
# HARVEST-LOG 拒收行：| kb-verify-<base>-<attempt>[r<replica>][-<ts>].json | rejected | <why> | - |
# <base> 可含 -r2/-r3（抽取线重派基名）；<attempt> 回流轮次；[r<replica>] 副本号
# （2026-10-29 验证放大新增；缺省为老格式单卡，两代格式都必须命中）。
# 与 r2 正则（poll_harvest 里那条）互斥：它要求文件名以 kb-atoms- 开头，验证卡回报名前缀是 kb-verify-。
# 非贪婪 base + 可选时间戳：-<ts> 要求 ≥6 位数字，故 attempt（个位数）不会被误当时间戳；
# r<replica> 段无横线，attempt 计数不会被副本号顶掉（id 方案与回流计数解耦）。
# why 必须吃到行尾再剥掉末列：收割方的合法 schema 一行里含"uphold|refute|unverifiable"
# 的竖线，按 [^|]* 切列会把 schema 行和 stats 一起截掉（实测踩中，故用 .* + 剥行尾）。
VERIFY_REJECT_RE = re.compile(
    r"\|\s*(?P<card>kb-verify-(?P<base>[a-z0-9.\-]+?)"
    r"-(?P<attempt>\d+)(?:r(?P<replica>\d+))?)(?:-\d{6,})?\.json\s*\|\s*rejected\s*\|\s*"
    r"(?P<why>.*)$")
# 本地卡目录名 → (base, attempt, replica|None)：老格式无 r 后缀（replica=None 视作单卡血线）
VERIFY_ID_RE = re.compile(r"^kb-verify-(?P<base>.+)-(?P<attempt>\d+)(?:r(?P<replica>\d+))?$")
# 拒收行末列（收割方对被拒行恒写 "-"）；剥掉它还拒收原因以本来面目
VERIFY_TAIL_RE = re.compile(r"\s*\|\s*-\s*\|\s*$")
# 拒收原因截断长度：收割方附 schema 行后整条约 240-300 字，300 保 schema 行与 stats 都完整
VERIFY_WHY_MAX = 300


def parse_verify_card_id(card_id):
    """kb-verify-<base>-<attempt>[r<replica>] → (base, attempt, replica|None)；不认返回 None。

    base 贪婪回溯，故 <base> 里的 -r2/-r3（抽取线重派基名）与 attempt 段不会混淆；
    副本号 r<replica> 无横线粘连在 attempt 后，回流 attempt 计数不受副本数影响。
    """
    m = VERIFY_ID_RE.match(card_id or "")
    if not m:
        return None
    return (m.group("base"), int(m.group("attempt")),
            int(m.group("replica")) if m.group("replica") else None)


def card_gate(d):
    """发布前任务卡质量闸（P3-11）：机器可判硬指标，不过闸不许发布。"""
    try:
        sys.path.insert(0, WS + "/tools")
        import importlib.util
        spec = importlib.util.spec_from_file_location("cardlint", WS + "/tools/card-lint.py")
        cl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cl)
        errs, _ = cl.lint_card(d)
        return "; ".join(errs) if errs else None
    except Exception as e:
        return f"质量闸自身异常（fail-closed）: {e}"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def changelog(text):
    line = f"| {time.strftime('%Y-%m-%d %H:%M')} | 事件路由器(自动) | {text} |\n"
    if not DRY:
        open(CHANGELOG, "a").write(line)
    log("变更日志: " + text)


def sh(cmd, timeout=60):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


def sh_rc(cmd, timeout=60):
    """sh 的带退出码版（DEB-1）：scp 等推送类调用要分辨"跑了"与"成了"——
    超时/OS 异常与 rc≠0 都记一行日志（fail-loud），由调用方决定降级语义。"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"外部调用超时（>{timeout}s）: {cmd[:120]}")
        return None
    except OSError as e:
        log(f"外部调用失败 {type(e).__name__}: {str(e)[:80]} —— {cmd[:120]}")
        return None
    return r


def gov_has_tasks(names, timeout=30):
    """核 gov 门户同名任务目录是否在位（真源=gov；只读 ls，零副作用）。

    2026-11-02 RT 修复（拒发残目录误判在飞）配套：「更新轮次在飞」此前只按本地
    task-seeds 目录名匹配，不核该卡是否真的上板——被质量闸拒发而残留本地的卡目录
    把真卡的重发永久误判成 skipped_newer（实测 175 条跳过，点名
    kb-verify-kb-atoms-rpt-2610.36499-1r1→2r1，而 2r1/2r2 在 gov 侧不存在）。
    返回在位名字集合；ssh 失败/超时（连接层 rc=255）返回 None=不可判定，由调用方
    按保守口径处理（维持跳过，不放大派单）。ls 对「一个都不在位」也 rc≠0（=2），
    故除 ssh 层失败外一律按 stdout 逐行解析（在位目录每行一个绝对路径，卡 id 含
    空格不存在——id 词表 [a-z0-9.\\-]，split 安全）。
    """
    if not names:
        return set()
    lst = " ".join(GOV_TASKS + n for n in names)
    r = sh_rc(f"{SSH} {GOV} 'ls -d {lst} 2>/dev/null'", timeout=timeout)
    if r is None or r.returncode == 255:
        return None
    return {os.path.basename(ln.rstrip("/")) for ln in (r.stdout or "").split()}


STATE_DEFAULTS = {"results": {}, "candidates": [], "rejects": [], "r2": [], "r3": [],
                  "rr55": [], "verify_cards": {}, "verify_by_file": {}, "verify_reports": [],
                  "verify_scanned": [],
                  # ② kb-verify 拒收回流：verify_reflows 按卡号防重放（含最终状态），
                  # verify_resends 按 atom 集+副本记重发次数（k 张副本各自独立计上限）
                  "verify_reflows": {}, "verify_resends": {},
                  # ③ 分歧检测：verify_groups 按 atom 集（候选文件）记各副本血线的最新裁决，
                  # 用于跨卡一致率与「分歧检测」登记（观测；原子状态由跨卡裁决时序消费腿承担）
                  "verify_groups": {},
                  # ⑤ 仲裁/蒸馏消费线：arb_reports 记已消费回报文件名（防重放），
                  # arb_attempts 记落库未全成的重试次数（≥ARBITRATE_RETRY_CAP 转人工登记）
                  "arb_reports": [], "arb_attempts": {},
                  # ⑤ 零终裁台账（2026-11-03 RT 修复·零终裁蒸发面）：终裁未落库的
                  # 仲裁/蒸馏回报（无有效 rulings / 结构缺件 / 无有效 findings）→
                  # 逐份登记 {card, why, atoms, n_atoms, evidence, status}——有主
                  # （点名受影响原子）+ 留证（arbitrate/no-verdict/ 副本）+ 可测。
                  # 旧口径把这类当「已消费」静默蒸发（对账门判 resolved-by-router 全绿）。
                  "arb_zero_verdict": {},
                  # ⑤ 同任务重复回报去重跳过的名（≠ 零终裁：本份本就无需再处理）
                  "arb_dedup_skipped": [],
                  # ⑤ RT-E80 机制④回流腿（2026-11-02）：arb_rejects 记收割方拒收的
                  # kb-arbitrate/kb-distill 回报文件名 → {why,status}（防重放）。
                  # 此前这两类拒收行不落 kb-verify 回流正则、也不落 r2 正则，整类蒸发
                  # （HARVEST-LOG 实存 55 行全 rejected 零处置）；现逐行认领：
                  # 已被本消费线消费的记 resolved-by-router（状态内回填标记，不再刷屏），
                  # 未消费的登记待运营者（changelog 点名）。
                  "arb_rejects": {},
                  # ② 收割面 OTel 发射记账（2026-11-02 RT 修复·收割面发射失败可见性）：
                  # 收割子进程的 [otel] 逐条记账原被 `2>&1 | tail -1` 整段吃掉、汇总行里的
                  # otel 记账无人解析——现记在本键（summary=解析出的 spans/metrics/errors/
                  # stop_skipped，stderr_lines=本轮透传落日志的记账行数）
                  "otel": {},
                  # ⑥ Trigger 收件箱消费腿（PoC-D）：trigger_consumed 按 delivery_id 记
                  # 消费结论（order_id/skip/dedup/rejected，加速缓存——真源=consumed.jsonl
                  # 游标）；trigger_dedup 按 dedup_key 防业务重放；trigger_leg 记腿起跑/
                  # 安灯态（活性安灯自建成起算的锚点）。
                  "trigger_consumed": {}, "trigger_dedup": {}, "trigger_leg": {}}


def load_state():
    # 深拷贝默认值：dict(STATE_DEFAULTS) 只是浅拷贝，st 与 STATE_DEFAULTS 会共享同一批
    # dict/list 对象；老状态文件缺新键时（本次新增的 verify_reflows/verify_resends 正是如此），
    # 往 st 里写就等于改模块级默认值，跨次 load_state 互相污染。深拷贝后各自独立。
    st = copy.deepcopy(STATE_DEFAULTS)
    try:
        st.update(json.load(open(STATE_F)))
    except FileNotFoundError:
        pass  # 首轮无状态文件属正常起步
    except Exception as e:
        # 损坏不许静默吞（2026-11-01 状态原子写批）：except-pass 会把全部防重放键
        # （candidates/r2/r3/rr55/verify_by_file/verify_reflows）无声清零 → 下轮全量
        # 重放灌重复卡。fail-loud 记一行日志，行为仍按空状态起步（与全场降级契约一致）。
        log(f"状态文件损坏/不可读，按空状态起步（{STATE_F}: {type(e).__name__}: {str(e)[:100]}）"
            f"——防重放键清零，若复发需人工核对防重放台账")
    # 老状态文件补新键（③ 交叉验证的键），避免 KeyError
    for k, v in STATE_DEFAULTS.items():
        st.setdefault(k, copy.deepcopy(v))
    return st


# 在役载入源码指纹（版本钉，2026-11-03 在役换码批）：**载入时**一次算定并冻结。
# 语义：sha256 = 本进程**载入时**判据源（tools/event-router.py 自身）的内容指纹，
# 不是「此刻盘上」的——盘上改了而在役进程仍跑旧码，进程内指纹必须不变；这正是
# 版本钉要暴露的事实（同 self-improve-loop.py v1.3.11 的 DAEMON_SRC_SHA256 同款）。
# 2026-11-03 RT 修复（本批确证缺陷面）：旧实现**每次写盘现读盘面文件重算** sha256，
# 于是「盘面改了」会被下一次 save_state() 的重算**自愈**成新盘面指纹——版本钉
# 变成「盘面此刻的指纹」而非「在役载入的指纹」，机制自我失效：钉与盘面恒等、
# 对账面永远看不到漂移（假绿），而这正是本机制要治的病。改为模块导入时一次
# 算定并冻结（与 self-improve-loop.py 同款已证先例）后，进程内恒定：盘面改了
# ⇒ 钉仍是旧码指纹 ⇒ 对账面红 ⇒ keepalive 判死换码（新码起跑即登记新指纹）。
try:
    DAEMON_SRC_SHA256 = hashlib.sha256(
        open(os.path.abspath(__file__), "rb").read()).hexdigest()
except OSError:
    DAEMON_SRC_SHA256 = None


def daemon_src_stamp():
    """在役载入源码指纹（版本钉，2026-11-03 在役换码批）：登记本进程**载入时**
    判据源（tools/event-router.py 自身）的 sha256。

    修的是「修复落盘≠在役生效」这一类缺陷的根：此前守护无版本钉，监督面判活只看
    「进程在 + state 新鲜」，盘上源码改了不重启＝修复不生效（2026-11-02 实证：在役
    守护 17:54:51 起跑、盘面 18:45 已改，RT-E157/RT-E160/RT-E169 三批修复整批未在役
    30h+；RT-E160 的 88 条 skipped_newer 存量重武装一次性腿从未执行）。本版只**登记
    事实**（不新增判定、不改既有判据），由监督面（tools/factory-keepalive.py 源码版本
    钉判活：版本不对齐⇒判死⇒自动拉起新码）与巡检面（tools/live-daemon-version-probe.py
    在役进程版本对账门：在役版本≠盘上版本⇒rc≠0 不可证即红）消费。
    读不到源文件时登记 sha256=None（不可证），不猜。

    钉值取自**模块导入时**算定并冻结的 DAEMON_SRC_SHA256（导入后盘面再改，本进程
    内的钉不变）——不得在每次写盘时现读盘面重算（那会让钉自愈成新盘面指纹，
    版本钉自我失效、对账面永远假绿，见上方常量旁注）。
    """
    path = os.path.abspath(__file__)
    return {"sha256": DAEMON_SRC_SHA256, "path": path, "ts": time.time(),
            "pid": os.getpid()}


def save_state(st):
    """状态文件原子写（tmp + os.replace，与 factory-scheduler/quality-cards 同款，2026-11-01）：
    旧法直写 open(STATE_F,"w")，5.97MB 逐段 dump 窗口内杀进程即截断文件，load_state
    静默清零全部防重放键 → 全量重放。tmp 与 STATE_F 同目录保证 os.replace 原子性。

    版本钉（2026-11-03）：每次写盘随封条登记在役载入源码指纹（st["daemon_src"]）——
    「在役进程跑的是哪一份判据」从推断（ps lstart vs 盘面 mtime）变为**可核验事实**。
    """
    if DRY:
        return
    try:
        st["daemon_src"] = daemon_src_stamp()   # 版本钉：每次写盘登记在役载入源码指纹
        tmp = STATE_F + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, STATE_F)
    except OSError as e:
        log(f"状态文件写入失败: {e}")


# ---------- ① anolis 订单跃迁 ----------

def poll_orders(st):
    # DEB-1：ssh 轮询超时/失败只记日志、本轮无跃迁（下轮再试），不冒泡到主循环
    # （冒泡会连带跳过本轮 harvest/verify 两个面）。
    try:
        raw = sh(f"{SSH} anolis 'for f in /data/bench/af-p3-state/orders/*/results.jsonl; do "
                 f"printf \"%s \" \"${{f##*/orders/}}\"; tail -1 \"$f\"; echo; done'", timeout=90)
    except subprocess.TimeoutExpired:
        log("订单轮询超时（>90s），本轮无跃迁（下轮再试）")
        return []
    except OSError as e:
        log(f"订单轮询失败 {type(e).__name__}: {str(e)[:80]}（本轮无跃迁，下轮再试）")
        return []
    fired = []
    for line in raw.splitlines():
        m = re.match(r"(\S+)-step5? \{(.*)", line)
        if not m:
            parts = line.split(" ", 1)
            if len(parts) != 2 or not parts[1].startswith("{"):
                continue
            order, body = parts[0].rstrip("/"), parts[1]
        else:
            order, body = m.group(1), "{" + m.group(2)
        try:
            j = json.loads(body)
        except Exception:
            continue
        status = j.get("status")
        reward = j.get("reward")
        oid = order.split("/")[0]
        key = f"{oid}:{status}:{reward}"
        if st["results"].get(oid) == key:
            continue
        st["results"][oid] = key
        suite = j.get("suite")
        task = j.get("task_id") or ""
        if suite == "report" and reward is True:
            fired.append(("report_ok", oid, task))
        elif suite in ("swe-v", "swev") and status == "max_turns":
            fired.append(("swev_max", oid, task))
    return fired


def make_portal_seed(task):
    """report 单 task 形如 <slug>-<2610-xxxxx> → 门户 kb-atoms 种子 + 证据缓存。"""
    m = re.search(r"(\d{4})-(\d{4,5})$", task)
    if not m:
        return None
    arx = f"{m.group(1)}.{m.group(2)}"
    ev = WS + f"/kb-seed/sandbox/evidence-cache/{arx}"
    os.makedirs(ev, exist_ok=True)
    # DEB-1：证据抓取超时/失败 fail-loud——无证据不产卡（宁可本轮不派生，也不发
    # 指向空证据的种子；curl --max-time + subprocess timeout 双超时在位）。
    try:
        if not os.path.exists(ev + "/abs.md"):
            sh(f"curl -sL --max-time 60 https://arxiv.org/abs/{arx} -o {ev}/abs.md", timeout=90)
        if not os.path.exists(ev + "/full.md"):
            sh(f"curl -sL --max-time 90 https://arxiv.org/html/{arx} -o {ev}/full.md", timeout=120)
    except subprocess.TimeoutExpired:
        log(f"证据抓取超时（{arx}），本轮不派生种子（下轮跃迁重试）")
        return None
    except OSError as e:
        log(f"证据抓取失败 {type(e).__name__}: {str(e)[:80]}（{arx}），本轮不派生种子")
        return None
    # 全文缺失/空壳（arXiv 未提供 HTML 全文）→ 任务书只承认摘要页，否则沙箱引文必被回查判 miss
    only_abs = False
    try:
        if not os.path.exists(ev + "/full.md") or os.path.getsize(ev + "/full.md") < 2000:
            only_abs = True
            if os.path.exists(ev + "/full.md"):
                os.rename(ev + "/full.md", ev + "/full.unavailable.html")
    except OSError:
        only_abs = True
    d = WS + f"/kb-seed/sandbox/task-seeds/kb-atoms-rpt-{arx}"
    os.makedirs(d, exist_ok=True)
    src_desc = (
        f"1. 摘要页：https://arxiv.org/abs/{arx} —— **该文 arXiv 未提供 HTML 全文**，全部 quote 只能取自摘要页原文\n"
        if only_abs else
        f"1. 摘要页：https://arxiv.org/abs/{arx}\n2. 全文 HTML（优先）：https://arxiv.org/html/{arx}\n")
    open(d + "/problem.md", "w").write(
        f"# {arx} 论文知识原子抽取\n\n## 证据源（唯一）\n" + src_desc +
        "把抓到的内容存为本地文件 wikiskill 同款证据：abs.md 与 full.md（若可得），并计算 sha256 备用。\n\n"
        "## 固定抽取问题（逐项作答，证据不可得则如实记 missing）\n"
        "论文解决什么问题；核心方法/架构；关键实验设置；关键结果（带数字）；失败模式/副作用；适用前提与局限；可作为验证器/评测用的事实。\n\n"
        "## 产出（POST /report 的 payload.schema）\n"
        '{"evidence": {"sources": [{"name": "abs.md|full.md", "sha256": "..."}], "sections_missing": []},\n'
        ' "atoms": [{"atom_id": "a1-<n>", "kind": "claim|concept|procedure|evidence_record|failure_pattern|evaluator",\n'
        '            "text": "一句话(≤60字)", "body": {}, "source": {"file": "...", "locator": "节名/段落", "quote": "≤120字逐字引", "evidence_sha256": "..."},\n'
        '            "relations": [{"type": "supportedBy|isA|partOf|requires|uses|validatedBy|observedIn", "to": "a1-<n>", "context": "一句话"}]}]}\n'
        "数量建议 15-40 条，宁缺毋滥。关系类型只用上列词表。\n")
    src = WS + "/kb-seed/sandbox/task-seeds/_AGENTS_template.md"
    if os.path.exists(src):
        open(d + "/AGENTS.md", "w").write(open(src).read())
    json.dump({"title": f"{arx} 论文知识原子抽取", "type": "kb-atom-extraction",
               "est_load": "~30-60min CPU+web", "reward": "工厂积分记账（sandbox_report 入 MES）"},
              open(d + "/meta.json", "w"), ensure_ascii=False)
    if not DRY:
        err = card_gate(d)
        if err:
            log(f"卡片未过质量闸，拒发: {d} -> {err}")
            return None
        # DEB-1：scp 带 ConnectTimeout=10 + subprocess timeout=60；失败/超时记日志并
        # 返回 None（调用方 changelog 记 None，不谎报"上门户"）。
        r = sh_rc(f"scp -q -o BatchMode=yes -o ConnectTimeout=10 -r {d} "
                  f"{GOV}:/opt/company/af-jobs/data/tasks/", timeout=60)
        if r is None or r.returncode != 0:
            log(f"门户种子推送失败（卡已在本地 {d}，未上门户）: "
                f"{'超时/异常' if r is None else (r.stderr or '').strip()[:100]}")
            return None
    return d


def make_rework_card(st, base, arx, why, tag, done_msg):
    """重派卡生成（r2=机械验谎拒收 / r3=交叉验证未过；同一套骨架，换后缀与反馈块）。"""
    d = WS + f"/kb-seed/sandbox/task-seeds/{base}-{tag}"
    rnd = {"r2": 2, "r3": 3}.get(tag, tag)
    if tag == "r3":
        head = "## 上一轮交叉验证未过（验证者 B 的裁决，逐字引回）"
        core = ("上一轮 A 的 quote 过了厂内机械回查，但 B 独立复核后认为条目本身不成立（见上）。"
                "本轮重抽时逐条自查：表述必须与证据逐字对应，不得把可能性写成结论、不得把单点实验"
                "写成普适规律、数字必须与原文一致；宁缺毋滥。")
    else:
        head = "## 上一轮拒收原因（逐字引回，吸取教训）"
        core = ("核心教训：quote 必须是你实际抓到的证据文本的**连续子串**（逐字符复制粘贴，不得改写、"
                "缩略、翻译或凭记忆补写）。上轮 miss 的条目就是栽在这一条。")
    os.makedirs(d, exist_ok=True)
    # 证据源降级声明（card-lint L4 门红根因修复）：r2/r3 任务书必须按 evidence-cache
    # 实况声明「全文不可用」——full.md 缺席或空壳（<2KB）时老模板无条件写"全文 HTML
    # （优先）"，card-lint.py:112 判「L4 全文不可用但任务书未声明降级」红（2026-10-29
    # all-gates 实证：2610.36870 / 2610.37211 两卡，门 item-16 FAIL）。口径与
    # make_portal_seed 的 only_abs 分支逐字一致；空壳 full.md 同步改名
    # full.unavailable.html（card-lint L4 第二臂"须移除该文件"）。
    ev_dir = WS + f"/kb-seed/sandbox/evidence-cache/{arx}"
    full_f = os.path.join(ev_dir, "full.md")
    only_abs = (not os.path.isfile(full_f)) or os.path.getsize(full_f) < 2000
    if only_abs and os.path.isfile(full_f):
        try:
            os.replace(full_f, os.path.join(ev_dir, "full.unavailable.html"))
        except OSError:
            pass   # 改名失败不阻塞出卡（card-lint 会按空壳文件报红，如实呈现）
    src_desc = (
        f"1. 摘要页：https://arxiv.org/abs/{arx} —— **该文 arXiv 未提供 HTML 全文**，"
        f"全部 quote 只能取自摘要页原文\n"
        if only_abs else
        f"1. 摘要页：https://arxiv.org/abs/{arx}\n2. 全文 HTML（优先）：https://arxiv.org/html/{arx}\n")
    open(d + "/problem.md", "w").write(
        f"# {arx} 论文知识原子抽取（第 {rnd} 轮）\n\n"
        f"{head}\n> {why}\n\n"
        f"{core}\n\n"
        f"## 证据源（唯一）\n{src_desc}"
        "把抓到的内容存为本地文件 wikiskill 同款证据：abs.md（摘要页）与 full.md（全文，若可得），"
        "并计算 sha256 备用。\n\n"
        "## 固定抽取问题（逐项作答，证据不可得则如实记 missing）\n"
        "论文解决什么问题；核心方法/架构；关键实验设置；关键结果（带数字）；失败模式/副作用；"
        "适用前提与局限；可作为验证器/评测用的事实。\n\n"
        "## 产出（POST /report 的 payload.schema）\n"
        '{"evidence": {"sources": [{"name": "abs.md|full.md", "sha256": "..."}], "sections_missing": []},\n'
        ' "atoms": [{"atom_id": "a1-<n>", "kind": "claim|concept|procedure|evidence_record|failure_pattern|evaluator",\n'
        '            "text": "一句话(≤60字)", "body": {}, "source": {"file": "...", "locator": "节名/段落", "quote": "≤120字逐字引", "evidence_sha256": "..."},\n'
        '            "relations": [{"type": "supportedBy|isA|partOf|requires|uses|validatedBy|observedIn", "to": "a1-<n>", "context": "一句话"}]}]}\n'
        "数量建议 15-40 条，宁缺毋滥。关系类型只用上列词表。\n")
    src = WS + "/kb-seed/sandbox/task-seeds/_AGENTS_template.md"
    if os.path.exists(src):
        open(d + "/AGENTS.md", "w").write(open(src).read())
    json.dump({"title": f"{arx} 原子抽取 r{rnd}（含上轮反馈）", "type": "kb-atom-extraction",
               "est_load": "~30-60min", "reward": "工厂积分记账",
               "rework": {"round": rnd, "trigger": tag, "base_task": base}},
              open(d + "/meta.json", "w"), ensure_ascii=False)
    if not DRY:
        err = card_gate(d)
        if err:
            log(f"{tag} 卡片未过质量闸，拒发: {d} -> {err}")
            return None
        # DEB-1：scp 双超时（ConnectTimeout=10 + timeout=60）；推送失败/超时记日志 +
        # 变更日志如实记"未上门户"，不沿用旧的静默失败（那会让变更日志谎报已推送）。
        r = sh_rc(f"scp -q -o BatchMode=yes -o ConnectTimeout=10 -r {d} "
                  f"{GOV}:/opt/company/af-jobs/data/tasks/", timeout=60)
        if r is None or r.returncode != 0:
            why = "超时/异常" if r is None else (r.stderr or "").strip()[:100]
            log(f"{tag} 卡推送失败（卡已在本地 {d}，未上门户）: {why}")
            changelog(done_msg + f"（卡已过质量闸但推送失败未上门户：{why}）")
            return None
    changelog(done_msg + "（卡已过质量闸）" if not DRY else done_msg + "（DRY：未过闸未推送）")
    return d


def enqueue_rr55(task):
    e = {"unit": "swev", "task": task, "data_root": "/data/bench/swev-s1-r0",
         "profile": "step-5", "max_turns": 55, "spend_cap": 300,
         "note": "router: max_turns → rr55", "dedupe_key": f"rr55-{task}"}
    fn = f"/tmp/rr55-{task.replace('/', '_')}.json"
    json.dump(e, open(fn, "w"), ensure_ascii=False)
    if not DRY:
        # DEB-1：scp 双超时（ConnectTimeout=10 + timeout=60）；失败/超时记日志（条目留在
        # 本机 /tmp，未入队=下轮 swev max_turns 状态键未变也不会重发，登记待运营者）。
        r = sh_rc(f"scp -q -o BatchMode=yes -o ConnectTimeout=10 {fn} "
                  f"anolis:/data/bench/queue/pending/90-rr55-{task.replace('/', '_')}.json",
                  timeout=60)
        if r is None or r.returncode != 0:
            why = "超时/异常" if r is None else (r.stderr or "").strip()[:100]
            log(f"rr55 条目入队失败 {task}（条目未入 anolis pending）: {why}")


# ---------- ② 沙箱收割面 ----------

def run_harvester(cmd=None, timeout=300):
    """收割子进程调用（stdout/stderr **分流**捕获）：返回 (stdout 末行, stderr 全文)。

    2026-11-02 RT 修复（OTel 链·收割面发射失败可见性）：原命令
    `harvest 2>&1 | tail -1` 把 harvester 的 stderr（[otel] 逐条发射记账）与 stdout
    **合流后再截末行** → 记账行整段被吃，发射失败无人可见（且全仓无任何消费者解析
    'otel spans='）。现分流捕获：stdout 仍取末行作既有判据（语义不变），stderr 交
    调用方逐条落日志。
    """
    c = cmd or f"cd {WS} && python3 tools/sandbox-harvester.py harvest"
    p = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=timeout)
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    return (lines[-1].strip() if lines else ""), (p.stderr or "")


def harvest_stderr_lines(err):
    """harvester stderr 的非空行（[otel] 逐条记账 + traceback）——原样透传给调用方落日志。"""
    return [ln.strip() for ln in (err or "").splitlines() if ln.strip()]


def harvest_summary_otel(out):
    """从 harvest 汇总行解析 otel 记账 → {"spans","metrics","errors","stop_skipped"}。

    此前全仓无任何消费者解析 'otel spans='（grep 零命中）——即便末行里 errors=14
    也无人读、无人比对、无人告警。现解析出来，errors>0 即点名（发射失败可见）。
    解析不出来返回 None（不猜数）。
    """
    m = re.search(r"otel\s+spans=(\d+)\s+metrics=(\d+)\s+errors=(\d+)\s+stop_skipped=(\d+)",
                  out or "")
    if not m:
        return None
    return {"spans": int(m.group(1)), "metrics": int(m.group(2)),
            "errors": int(m.group(3)), "stop_skipped": int(m.group(4))}


def poll_harvest(st):
    # DEB-1：harvester 子进程超时/失败只记日志（本轮不当新候选处理，下轮再跑），
    # 不冒泡到主循环（冒泡会连带跳过本轮 verify 消费面）。
    try:
        out, err = run_harvester(timeout=300)
    except subprocess.TimeoutExpired:
        log("harvest 子进程超时（>300s），本轮跳过（下轮再跑）")
        out, err = "", ""
    except OSError as e:
        log(f"harvest 子进程失败 {type(e).__name__}: {str(e)[:80]}（本轮跳过）")
        out, err = "", ""
    if "harvest" not in out:
        log("harvest 输出异常: " + out[:100])
    # 发射失败可见性（2026-11-02 RT 修复）：harvester 的 [otel] 逐条记账走 stderr，
    # 原 `2>&1 | tail -1` 把它整段吃掉——现原样落 router 日志（状态观测/event-router.log）。
    err_lines = harvest_stderr_lines(err)
    for line in err_lines:
        log("harvester stderr: " + line)
    # 汇总行里的 otel 记账：此前无人读——现解析并在 errors>0 时点名。
    otel_sum = harvest_summary_otel(out)
    if otel_sum and otel_sum.get("errors"):
        log(f"harvest 埋点发射失败可见（collector 不可达等）: {otel_sum}")
    st["otel"] = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": otel_sum,
                  "stderr_lines": len(err_lines)}
    # 验谎通过 → 新 candidates JSONL → 入库 + 生成交叉验证卡（A 的工作交给 B 验证）
    import glob
    for f in candidate_files():
        if f in st["candidates"]:
            continue
        st["candidates"].append(f)
        if DRY:
            log(f"[DRY] 跳过 registry import（避免干跑写库）：`{os.path.basename(f)}`")
        else:
            # DEB-1：registry import 超时/失败记日志，该候选仍走验证卡派发（卡生成侧
            # 有自己的闸与失败记账），不冒泡。
            try:
                r = sh(f"cd {WS} && python3 kb-seed/registry.py import {f} 2>&1 | tail -1", timeout=120)
            except subprocess.TimeoutExpired:
                r = "import 超时（>120s）"
                log(f"registry import 超时：`{os.path.basename(f)}`（>120s）")
            except OSError as e:
                r = f"import 失败 {type(e).__name__}"
                log(f"registry import 失败 {type(e).__name__}: {str(e)[:80]} —— `{os.path.basename(f)}`")
            changelog(f"沙箱回报验谎通过自动入库：`{os.path.basename(f)}` → registry import {r}")
        make_verify_card(st, f)
    # 拒收 → r2 种子（拒收原因入 problem.md）
    try:
        lines = open(WS + "/kb-seed/sandbox/HARVEST-LOG.md").read().splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        m = re.search(r"\|\s*(kb-atoms-[a-z0-9]+-(\d{4}\.\d{4,5}))(?:-r2)?-\d+\.json\s*\|\s*rejected\s*\|([^|]*)\|", line)
        if not m or (m.group(1) + "-r2") in st["r2"]:
            continue
        base, arx, why = m.group(1), m.group(2), m.group(3).strip()[:160]
        st["r2"].append(base + "-r2")
        make_rework_card(st, base, arx, why, "r2",
                         f"拒收自动重派：`{base}-r2` 上门户（拒收原因已写入任务书）")
    # kb-verify 拒收 → 重发新版验证卡（与上面 r2 同一份日志行集、两条正则互斥）
    poll_verify_rejects(st, lines)
    # RT-E80 机制④回流腿（2026-11-02）：kb-arbitrate/kb-distill 拒收 → 认领登记，
    # 不再整类蒸发（此前只认 kb-atoms/kb-verify 前缀，55 行旧式拒收零处置）
    poll_arb_rejects(st, lines)


def candidate_files():
    """候选 JSONL：ask 记的 sbx-*.jsonl + 收割方实际产出的 <task_id>-<ts>.jsonl。"""
    import glob
    out = []
    for g in CAND_GLOBS:
        out.extend(glob.glob(CAND_DIR + "/" + g))
    return sorted(set(out))


def parse_candidate_file(path):
    """候选文件名 → (原 task_id, arXiv id)；解析不出 arXiv id 返回 None。"""
    base = os.path.basename(path)
    m = TS_SUFFIX_RE.match(base)
    tid = m.group("tid") if m else (base[:-6] if base.endswith(".jsonl") else base)
    am = ARX_RE.search(tid)
    return (tid, am.group(1)) if am else None


# ---------- ② kb-verify 拒收回流（结构性拒收不得蒸发） ----------

_SCHEMA_LINE = None


def harvest_schema_line():
    """收割方拒收文案附的合法 schema 一行示例（tools/sandbox-harvester.py 的
    KBVERIFY_SCHEMA_LINE，单一真源；本文件不复制，避免两处口径漂移）。取不到只影响
    回流卡里那一行格式示例的有无，不阻塞回流本身。"""
    global _SCHEMA_LINE
    if _SCHEMA_LINE is None:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("sbxharvester", HARVESTER)
            hv = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hv)
            _SCHEMA_LINE = hv.KBVERIFY_SCHEMA_LINE
        except Exception as e:  # noqa: BLE001 - 守护动作不抛回主循环
            _SCHEMA_LINE = ""
            log(f"取收割方 schema 行失败（回流继续，仅少一行格式示例）: {type(e).__name__}: {e}")
    return _SCHEMA_LINE


def verify_card_meta(card_id):
    """验证卡 meta.json 的 verify 块（task_id/arxiv/candidates_file/seed/sampled）。"""
    try:
        return json.load(open(os.path.join(VERIFY_SEEDS, card_id, "meta.json"),
                              encoding="utf-8")).get("verify") or {}
    except Exception:
        return {}


def _mask_foreign_arx(text, arx):
    """注入文本里出现别的 arXiv id 会让 card-lint L3 判「证据源不唯一」而拒发——就地掩掉。"""
    return ARX_RE.sub(lambda m: m.group(1) if m.group(1) == arx else "<arXiv-id>", text or "")


def inject_reject_note(card_dir, old_card_id, attempt, why, atoms_total, cand_name, arx):
    """把「上轮为何被拒」段写进新版验证卡 problem.md（插在 H1 之后、首个二级标题之前）。

    内容：上轮卡号 + 逐字引回的拒收原因 + 收割方合法 schema 一行示例 + 本轮重发语义。
    返回是否写入了该段（已有则跳过，重复调用幂等）。"""
    pm = os.path.join(card_dir, "problem.md")
    if not os.path.isfile(pm):
        return False
    txt = open(pm, encoding="utf-8").read()
    if "## 上轮为何被拒" in txt:
        return False
    why = _mask_foreign_arx(why.strip()[:VERIFY_WHY_MAX], arx)
    schema = harvest_schema_line()
    schema_row = (f"厂内收割方对本卡的合法格式要求（一行示例，逐字照这个结构写）：\n"
                  f"`{_mask_foreign_arx(schema, arx)}`\n\n" if schema else "")
    block = (
        f"## 上轮为何被拒（第 {attempt} 轮重发；上一版卡 `{old_card_id}` 的回报"
        f"被厂内收割方结构性拒收，整份作废）\n\n"
        f"> {why}\n\n"
        f"上一轮因此白跑一轮算力。本轮是**同一批原子的重发**（atom 集不变：候选清单 "
        f"`{_mask_foreign_arx(cand_name, arx)}` 共 {atoms_total} 条，抽样口径同上轮），"
        f"请先把 problem.md 的「verdicts 逐字段说明」「完整合法回报 JSON 示例」"
        f"「回报前自检清单」三节读完，再逐条写满 `payload.verdicts`。\n\n"
        f"{schema_row}"
        f"**四个字段缺任何一个 = 整份再被结构性拒收**：`atom_id`（上表 atom_id 原文照抄，"
        f"含 `sbx-` 前缀）/ `verdict`（`uphold` / `refute` / `unverifiable` 小写原词）/ "
        f"`quote_check`（JSON 布尔 `true`/`false`，不是字符串 `\"true\"`、不是 1/0）/ "
        f"`reason`（≤80 字，指向你自己抓到的证据位置）。\n\n")
    i = txt.find("\n## ")
    if i > 0:
        open(pm, "w", encoding="utf-8").write(txt[:i + 1] + block + txt[i + 1:])
    else:  # 模板没有二级标题时的兜底：整段前置
        open(pm, "w", encoding="utf-8").write(block + txt)
    return True


def resend_verify_card(st, card_id, why):
    """为一张被结构性拒收的验证卡重发新版（同副本血线 attempt+1）。返回处置状态字符串。

    步骤：读被拒卡的 meta.json（task_id/arxiv/candidates_file/seed/sampled）→ 解析卡 id
    得 (base, attempt, replica) → 校验同一 atom 集可重抽 → 上限/在飞检查（均按副本血线）→
    调 tools/cross-verify.py 生成新卡（--no-scp，本函数自己走发布链）→ 注入「上轮为何被拒」段
    → card-lint 质量闸（fail-closed）→ scp。失败只记日志/变更日志，不抛回主循环。

    2026-10-29 验证放大：k 张副本各自独立计轮次与重发上限——重发只发同一副本号
    （--replica J，老格式单卡走 --replicas 1 保持旧路径），重发键含副本号；
    回流语义不变：同 seed 同条数 = 同一批原子，attempt+1。
    """
    meta = verify_card_meta(card_id)
    parsed = parse_verify_card_id(card_id)
    tid = meta.get("task_id") or (parsed[0] if parsed else card_id[len("kb-verify-"):].rsplit("-", 1)[0])
    arx = meta.get("arxiv") or ""
    m = ARX_RE.search(tid)
    if m and not arx:
        arx = m.group(1)
    cand_name = meta.get("candidates_file") or ""
    cand = os.path.join(CAND_DIR, cand_name) if cand_name else ""
    # atom 集键：同一份候选 JSONL = 同一批原子；副本各自独立计重发上限（键含副本号）
    replica = parsed[2] if parsed else None
    key = f"{cand_name or tid or card_id}#r{replica or 1}"
    attempt = parsed[1] if parsed else 0
    if not tid or not arx or not os.path.isfile(cand):
        changelog(f"kb-verify 回流跳过（缺候选清单/arXiv id，登记待运营者）：`{card_id}`"
                  f" task_id={tid or '?'} arxiv={arx or '?'} cand={cand_name or '?'}；"
                  f"拒收原因 {why[:80]}")
        return "no_candidates"
    # 同一 atom 集同一副本血线已有更新轮次的卡在飞 → 不重复派单（避免同一批原子同副本两张待验卡）；
    # 别的副本（r<j> 不同）互不挤占，各自独立回流。
    # 2026-11-02 RT 修复（拒发残目录误判在飞）：「在飞」必须核该卡真的上板——
    # ①状态注册表 status=open（推送成功且未被消费/作废/失败）；②gov 侧同名任务目录在位
    # （状态文件丢账时的兜底真源）。两者皆否的本地残目录（旧拒发残留/推送未遂老账）
    # 不算在飞，回流继续。gov 不可达时按旧口径保守跳过（fail-open，防派单风暴）。
    vc = st.setdefault("verify_cards", {})
    newer_unconfirmed = []
    for d in sorted(glob.glob(os.path.join(VERIFY_SEEDS, f"kb-verify-{tid}-*"))):
        p = parse_verify_card_id(os.path.basename(d))
        if not p:
            continue
        a, r = p[1], (p[2] or 1)
        if a <= attempt or r != (replica or 1):
            continue
        mv = verify_card_meta(os.path.basename(d))
        if (mv.get("candidates_file") or "") != cand_name:
            continue
        if (vc.get(os.path.basename(d)) or {}).get("status") == "open":
            log(f"kb-verify 回流跳过（已有更新轮次在飞）：`{card_id}` → {os.path.basename(d)}")
            return "skipped_newer"
        newer_unconfirmed.append(os.path.basename(d))
    if newer_unconfirmed:
        on_gov = gov_has_tasks(newer_unconfirmed)
        if on_gov is None:
            log(f"kb-verify 回流跳过（gov 不可达，保守按在飞）：`{card_id}` → {', '.join(newer_unconfirmed)}")
            return "skipped_newer"
        if on_gov:
            log(f"kb-verify 回流跳过（已有更新轮次在飞，gov 在位）：`{card_id}` → {', '.join(sorted(on_gov))}")
            return "skipped_newer"
        log(f"kb-verify 回流：本地残目录未上板，不算在飞，继续重发：`{card_id}`"
            f"（gov 侧无 {', '.join(newer_unconfirmed)}）")
    # 上限：同一 atom 集同一副本重发 ≤ VERIFY_RESEND_CAP 次，超限登记等运营者（防坏卡死循环）
    resends = st.setdefault("verify_resends", {})
    done = resends.get(key, 0)
    if done >= VERIFY_RESEND_CAP:
        changelog(f"kb-verify 重发上限已满（atom 集 `{cand_name}` 副本 r{replica or 1} 已重发 {done} 次，"
                  f"上限 {VERIFY_RESEND_CAP}），登记待运营者处理：`{card_id}`"
                  f" 拒收原因 {why[:80]}")
        return "capped"
    if DRY:
        log(f"[DRY] kb-verify 回流只记日志（不生成不推送）：`{card_id}` → 第 {attempt + 1} 轮，"
            f"候选 {cand_name}（arXiv:{arx}），拒收原因 {why[:60]}")
        return "dry"
    # 复用 cross-verify 的卡生成：同 seed 同条数 = 同一批原子；attempt+1 由卡序号自然给出
    flags = f"--seeds-dir {VERIFY_SEEDS} --no-scp"
    if replica:  # 新格式副本卡：只重发同一副本（id 带 r{J}，attempt+1，视角不变）
        flags += f" --replica {replica}"
    else:        # 老格式单卡：保持既有单卡路径（--replicas 1，id 无 r 后缀）
        flags += " --replicas 1"
    if meta.get("seed"):
        flags += f" --seed {meta['seed']}"
    if meta.get("sampled"):
        flags += f" --n {int(meta['sampled'])}"
    # 末行 stdout 是 cross-verify 的结构化结果 JSON（日志行在前，故取 tail -1；同 make_verify_card）
    # DEB-1：卡生成子进程超时/失败 → 记变更日志 gen_failed（不冒泡；一张坏卡不许带崩回流线）
    try:
        r = sh(f"cd {WS} && python3 tools/cross-verify.py {cand} {arx} {flags} 2>&1 | tail -1",
               timeout=300)
    except subprocess.TimeoutExpired:
        changelog(f"kb-verify 回流卡生成超时（>300s）：`{card_id}`")
        return "gen_failed"
    except OSError as e:
        changelog(f"kb-verify 回流卡生成失败（{type(e).__name__}: {str(e)[:80]}）：`{card_id}`")
        return "gen_failed"
    try:
        j = json.loads(r)
    except Exception:
        changelog(f"kb-verify 回流卡生成失败（输出不可解析）：`{card_id}` → {r[:120]}")
        return "gen_failed"
    if not j.get("ok"):
        changelog(f"kb-verify 回流卡未过质量闸/未生成：`{card_id}` → "
                  f"{str(j.get('note') or j.get('error') or '')[:160]}")
        return "gen_failed"
    # 无卡可派形状（与 make_verify_card 同款守卫）：守卫跳过 ok=true 但无 cards/card_id，
    # 旧码会令 c0={} → card_dir=None → os.path.join TypeError（虽被 poll_verify_rejects
    # 捕获记 error，但该卡永不再重试）。按 skipped 记账。
    if j.get("skipped_verify") or not (j.get("cards") or j.get("card_id")):
        changelog(f"kb-verify 回流跳过（无卡可派：{str(j.get('note') or '')[:160]}）：`{card_id}`")
        return "skipped"
    # 回流只生成一张卡：兼容两种 stdout 形态（单卡老形 / cards 数组新形）
    c0 = (j.get("cards") or [j])[0] if (j.get("cards") or j.get("card_id")) else {}
    new_card, card_dir = c0.get("card_id"), c0.get("card_dir")
    new_parsed = parse_verify_card_id(new_card or "")
    new_attempt = new_parsed[1] if new_parsed else attempt + 1
    # 拒收原因 + 合法 schema 一行写进新卡 problem.md 的「上轮为何被拒」段
    inject_reject_note(card_dir, card_id, new_attempt, why,
                       j.get("atoms_total") or meta.get("atoms_total") or 0, cand_name, arx)
    # 发布链与 make_rework_card 同款：card-lint fail-closed，过了才 scp
    err = card_gate(card_dir)
    if err:
        # 2026-11-02 RT 修复：拒发残目录就地清除（与 cross-verify 拒发分支同款纪律）——
        # 没过闸的卡永不上板，留在 task-seeds/ 会被 card-lint --all 扫成硬伤、并占住
        # 副本血线的 attempt 位误触发「已有更新轮次在飞」。
        shutil.rmtree(card_dir, ignore_errors=True)
        changelog(f"kb-verify 回流卡未过质量闸，拒发: {new_card} -> {err}")
        return "gate_failed"
    # DEB-1：scp 双超时；推送失败/超时 → 状态记 push_failed（不计重发次数——没上门户
    # 就不算发过；不谎报"已自动重派上门户"）。
    r = sh_rc(f"scp -q -o BatchMode=yes -o ConnectTimeout=10 -r {card_dir} "
              f"{GOV}:/opt/company/af-jobs/data/tasks/", timeout=60)
    if r is None or r.returncode != 0:
        why = "超时/异常" if r is None else (r.stderr or "").strip()[:100]
        log(f"kb-verify 回流卡推送失败（卡已在本地 {card_dir}，未上门户）: {why}")
        changelog(f"kb-verify 回流卡推送失败（未上门户，不计重发）：`{card_id}` → `{new_card}`：{why}")
        return "push_failed"
    resends[key] = done + 1
    st.setdefault("verify_cards", {})[new_card] = {
        "card_id": new_card, "task_id": tid, "arxiv": arx, "candidates": cand,
        "atom_ids": c0.get("atom_ids", []), "sampled": c0.get("sampled"), "status": "open",
        "resend_of": card_id}
    rlabel = f"副本 r{replica}，" if replica else ""
    changelog(f"kb-verify 拒收自动重派：`{card_id}` → 新版验证卡 `{new_card}` 上门户"
              f"（第 {new_attempt} 轮，{rlabel}拒收原因+schema 行已写入"
              f"「上轮为何被拒」段；atom 集 `{cand_name}` 第 {done + 1}/{VERIFY_RESEND_CAP} 次重发）")
    return "resent"


def poll_verify_rejects(st, lines):
    """扫 HARVEST-LOG 的 kb-verify 拒收行 → 逐张回流重发（st['verify_reflows'] 防重放）。"""
    seen = st.setdefault("verify_reflows", {})
    for line in lines:
        m = VERIFY_REJECT_RE.search(line)
        if not m:
            continue
        card_id = m.group("card")
        if card_id in seen:
            continue
        # 拒收原因可能含竖线（schema 一行的裁决词表），故吃到行尾再剥掉末列
        why = VERIFY_TAIL_RE.sub("", m.group("why")).strip()
        seen[card_id] = {"why": why[:VERIFY_WHY_MAX], "status": "pending"}
        try:
            seen[card_id]["status"] = resend_verify_card(st, card_id, why)
        except Exception as e:  # noqa: BLE001 - 一张坏卡不许带崩整条回流线（含后面的 r2 行）
            seen[card_id]["status"] = "error"
            log(f"kb-verify 回流异常（不阻塞后续卡）: `{card_id}` → {type(e).__name__}: {e}")


# ---------- ③ 交叉验证：生成侧（A 报通过 → 派验证卡给 B） ----------

def make_verify_card(st, cand_file):
    """A 报通过 → 每份候选 JSONL 至多派 1 次验证卡（st['verify_by_file'] 防重）。

    2026-10-29 验证放大：一次派发 = 同一 atom 集的 k 张独立复核卡（cross-verify 默认
    --replicas 2，各用不同抽样种子与不同复核员视角提示语）。stdout 末行 JSON 两种形态
    都认：老形（单卡，{card_id,...}）与新形（{replicas, cards:[...]}）。
    """
    per_file = st.setdefault("verify_by_file", {})
    if cand_file in per_file:
        return
    parsed = parse_candidate_file(cand_file)
    if not parsed:
        per_file[cand_file] = {"status": "skipped"}
        changelog(f"交叉验证跳过：`{os.path.basename(cand_file)}` 无法解析 arXiv id")
        return
    tid, arx = parsed
    dry = " --no-scp" if DRY else ""
    # 末行 stdout 是 cross-verify 的结构化结果 JSON（日志行在前，故取 tail -1）
    # --seeds-dir 显式给出（默认值与 cross-verify 内置 SEEDS 同路径，生产行为不变；
    # 显式传是为了让本文件的 VERIFY_SEEDS 单点改向时真的生效——回流路径同款）
    # DEB-1：卡生成子进程超时/失败 → per_file 记 failed + 变更日志（不冒泡到主循环）
    try:
        r = sh(f"cd {WS} && python3 tools/cross-verify.py {cand_file} {arx} "
               f"--seeds-dir {VERIFY_SEEDS}{dry} 2>&1 | tail -1",
               timeout=300)
    except subprocess.TimeoutExpired:
        per_file[cand_file] = {"status": "failed"}
        changelog(f"交叉验证卡生成超时（>300s）：`{os.path.basename(cand_file)}`")
        return
    except OSError as e:
        per_file[cand_file] = {"status": "failed"}
        changelog(f"交叉验证卡生成失败（{type(e).__name__}: {str(e)[:80]}）：`{os.path.basename(cand_file)}`")
        return
    try:
        j = json.loads(r)
    except Exception:
        per_file[cand_file] = {"status": "failed"}
        changelog(f"交叉验证卡生成失败（输出不可解析）：`{os.path.basename(cand_file)}` → {r[:120]}")
        return
    if not j.get("ok"):
        per_file[cand_file] = {"status": "failed", "card_id": j.get("card_id")}
        changelog(f"交叉验证卡未过闸/未生成：`{os.path.basename(cand_file)}` → {j.get('note', j.get('error', ''))[:160]}")
        return
    # 无卡可派形状（DEB-1 同批修复的轮次杀手）：cross-verify 守卫跳过返回
    # {"ok": true, "skipped_verify": true, "note": "…不再发验证卡"}——ok 为真但既无
    # cards 数组也无 card_id（cross-verify.py:48-49 已预告"缺键会 KeyError"）。旧码
    # 径直走 c["card_id"] → KeyError 冒泡到主循环 → 整轮 abort（poll_verify_reports
    # 被连带跳过，2026-10-29 实测 348 轮连续中招）。此处按 skipped 记账放行。
    if j.get("skipped_verify") or not (j.get("cards") or j.get("card_id")):
        per_file[cand_file] = {"status": "skipped"}
        changelog(f"交叉验证跳过（无卡可派：{str(j.get('note') or '')[:160]}）：`{os.path.basename(cand_file)}`")
        return
    cards = j.get("cards") or [j]  # 新形多副本 / 老形单卡
    card_ids, undelivered = [], []
    for c in cards:
        if not c.get("ok"):
            changelog(f"交叉验证副本卡未过闸：`{os.path.basename(cand_file)}` → "
                      f"{c.get('card_id')} {'; '.join(c.get('gate') or [])[:160]}")
            continue
        # 2026-11-01 RT 修复（DEB-1 同款纪律「没上门户就不算发过」）：cross-verify
        # 如实回报 scp=false（推送失败，卡只在本地）时不得注册 status=open——旧码
        # 不问 scp 字段，gov 不可达窗内照标 open，B 永无回报、A→B 交叉验证静默停摆。
        # 此处记 push_failed 留痕（per_file 防重照旧，不自动重放；DRY 的 --no-scp
        # 是「不推送」不是「推送失败」，维持旧口径）。
        if not DRY and not c.get("scp"):
            undelivered.append(c["card_id"])
            continue
        st.setdefault("verify_cards", {})[c["card_id"]] = {
            "card_id": c["card_id"], "task_id": tid, "arxiv": arx,
            "candidates": cand_file, "atom_ids": c.get("atom_ids", []),
            "sampled": c.get("sampled"), "status": "open"}
        card_ids.append(c["card_id"])
    if undelivered:
        changelog(f"交叉验证副本卡推送失败（未上门户，不注册 open）："
                  f"`{os.path.basename(cand_file)}` → 验证卡 "
                  f"{'+'.join('`' + c + '`' for c in undelivered)}（arXiv:{arx}；"
                  f"卡在本地 task-seeds，gov 恢复后可手工补推或清 verify_by_file 重派）")
    if card_ids:
        per_file[cand_file] = {"status": "open", "card_id": card_ids[0],
                               "card_ids": card_ids}
    elif undelivered:
        per_file[cand_file] = {"status": "push_failed", "card_id": undelivered[0],
                               "card_ids": undelivered}
    else:
        per_file[cand_file] = {"status": "open", "card_id": "",
                               "card_ids": []}
    if len(card_ids) > 1:
        changelog(f"交叉验证派单（A→B，{len(card_ids)} 张独立复核）：`{os.path.basename(cand_file)}` → "
                  f"验证卡 {'+'.join('`' + c + '`' for c in card_ids)}"
                  f"（各抽 {cards[0].get('sampled')}/{j.get('atoms_total')} 条，arXiv:{arx}，scp={cards[0].get('scp')}）")
    elif card_ids:
        changelog(f"交叉验证派单（A→B）：`{os.path.basename(cand_file)}` → 验证卡 `{card_ids[0]}`"
                  f"（抽 {cards[0].get('sampled')}/{j.get('atoms_total')} 条，arXiv:{arx}，scp={cards[0].get('scp')}）")
    elif not card_ids and not undelivered:
        # 全部未过闸（无可注册也无未送达）才走旧口径；推送失败已由上方专项行记账
        changelog(f"交叉验证派单无可注册卡：`{os.path.basename(cand_file)}` → {j.get('note', '')[:160]}")


# ---------- ③ 交叉验证：消费侧（B 的回报 → admit / reject+r3） ----------

def gov_report_paths():
    # DEB-1：ssh 列目录超时/失败 → 返回空列表（本轮只消费本地 raw/，下轮再试），
    # 不冒泡到主循环。
    try:
        raw = sh(f"{SSH} {GOV} 'ls {GOV_REPORTS}/*.json 2>/dev/null'", timeout=60)
    except subprocess.TimeoutExpired:
        log("gov reports 列举超时（>60s），本轮只扫本地 raw/")
        return []
    except OSError as e:
        log(f"gov reports 列举失败 {type(e).__name__}: {str(e)[:80]}（本轮只扫本地 raw/）")
        return []
    return [l.strip() for l in raw.splitlines() if l.strip().endswith(".json")]


def fetch_report(path):
    """本地 raw/ 留档优先，否则 ssh gov 只读拉取。拉取失败返回 None（不标记，下轮再试）。"""
    try:
        if os.path.isfile(path):
            return json.load(open(path, encoding="utf-8"))
    except Exception:
        pass
    # DEB-1：ssh cat 超时/失败 → None（与"拉取失败不标记，下轮再试"契约一致，不冒泡）
    try:
        r = subprocess.run(f"{SSH} {GOV} 'cat {path}'", shell=True, capture_output=True,
                           text=True, timeout=60)
    except subprocess.TimeoutExpired:
        log(f"回报拉取超时（>60s，下轮再试）: {os.path.basename(path)}")
        return None
    except OSError as e:
        log(f"回报拉取失败 {type(e).__name__}: {str(e)[:60]} —— {os.path.basename(path)}")
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def card_info(st, card_id):
    """卡 → 候选清单：先查状态文件，丢了则回读本地卡目录 meta.json（自愈）。"""
    info = (st.get("verify_cards") or {}).get(card_id)
    if info:
        return info
    mf = WS + f"/kb-seed/sandbox/task-seeds/{card_id}/meta.json"
    try:
        v = json.load(open(mf, encoding="utf-8")).get("verify") or {}
        cand = v.get("candidates_file") or ""
        cand = os.path.join(CAND_DIR, cand) if cand else ""
        return {"card_id": card_id, "task_id": v.get("task_id"), "arxiv": v.get("arxiv"),
                "candidates": cand, "atom_ids": v.get("atom_ids", []),
                "sampled": v.get("sampled"), "status": "open"}
    except Exception:
        return None


def save_verify_report(name, rep):
    """验证回报本地留档 → registry admit/reject 的依据文件路径。"""
    os.makedirs(VERIFY_DIR, exist_ok=True)
    p = os.path.join(VERIFY_DIR, name)
    if not DRY:
        json.dump(rep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def mark_harvested(name):
    """验证回报已由路由器消费，写进 .harvested 让 harvester 不再按抽取 schema 校验它。"""
    if DRY:
        return
    try:
        open(WS + "/kb-seed/sandbox/.harvested", "a").write(name + "\n")
    except OSError:
        pass


def registry_admit(ids, ev_path, cand_file):
    """逐条 candidate → verified；全数 no-such 说明没入库过，先补 import 再重试一次。"""
    import shlex
    if DRY:
        log(f"[DRY] 跳过 registry admit（避免干跑写库）：{len(ids)} 条，依据 {ev_path}")
        return 0, len(ids)
    ok = miss = 0
    for cid in ids:
        # DEB-1：admit 子进程超时/失败按 miss 记（不冒泡；全 miss 时的补 import 重试
        # 逻辑不变）
        try:
            r = sh(f"cd {WS} && python3 kb-seed/registry.py admit {shlex.quote(cid)} "
                   f"{shlex.quote(ev_path)} 2>&1 | tail -1", timeout=60)
        except subprocess.TimeoutExpired:
            log(f"registry admit 超时（>60s）: {cid}")
            r = ""
        except OSError as e:
            log(f"registry admit 失败 {type(e).__name__}: {str(e)[:60]} —— {cid}")
            r = ""
        if r == "admitted":
            ok += 1
        else:
            miss += 1
    if miss and ok == 0 and cand_file and os.path.isfile(cand_file):
        try:
            sh(f"cd {WS} && python3 kb-seed/registry.py import {cand_file} 2>&1 | tail -1", timeout=120)
        except subprocess.TimeoutExpired:
            log(f"registry import 超时（>120s）: {os.path.basename(cand_file)}")
        except OSError as e:
            log(f"registry import 失败 {type(e).__name__}: {str(e)[:60]}")
        ok = miss = 0
        for cid in ids:
            try:
                r = sh(f"cd {WS} && python3 kb-seed/registry.py admit {shlex.quote(cid)} "
                       f"{shlex.quote(ev_path)} 2>&1 | tail -1", timeout=60)
            except subprocess.TimeoutExpired:
                log(f"registry admit 超时（>60s，重试轮）: {cid}")
                r = ""
            except OSError as e:
                log(f"registry admit 失败 {type(e).__name__}: {str(e)[:60]} —— {cid}")
                r = ""
            if r == "admitted":
                ok += 1
            else:
                miss += 1
    return ok, miss


def registry_reject(ids, why):
    import shlex
    if DRY:
        log(f"[DRY] 跳过 registry reject（避免干跑写库）：{len(ids)} 条，原因 {why}")
        return 0
    ok = 0
    for cid in ids:
        # DEB-1：reject 子进程超时/失败只记日志（不冒泡；该条按未拒绝计）
        try:
            r = sh(f"cd {WS} && python3 kb-seed/registry.py reject {shlex.quote(cid)} "
                   f"{shlex.quote(why)} 2>&1 | tail -1", timeout=60)
        except subprocess.TimeoutExpired:
            log(f"registry reject 超时（>60s）: {cid}")
            continue
        except OSError as e:
            log(f"registry reject 失败 {type(e).__name__}: {str(e)[:60]} —— {cid}")
            continue
        if r == "rejected":
            ok += 1
    return ok


def kb_ingest_verified(context):
    """verified 状态落定 → kb 入库（冲刺批2 第二步：接进事件路由器）。

    只在 registry admit 聚合成功处调用（handle_verify_report 的 uphold 达标分支）。
    幂等：kb-ingest 按内容指纹跳过"完全没变"的原子（重复跑 new=0 updated=0 unchanged=N）；
    其 content 口径已与 kb/import_registry.py 统一（tools/kb-ingest.py 复用后者的
    _build_content），故同 id 两入口混跑不会让库内 content 形态来回翻。

    护栏（工单硬性）：
      · ROUTER_DRY=1 → 只记日志，不跑子进程、不落库；
      · .router-STOP 在位 → 跳过（与主循环同一条熔断；循环中途落下熔断同样生效）；
      · subprocess 超时 = KB_INGEST_TIMEOUT（基线 600s，2026-10-31 实测重标，原 120s；
        2026-11-01 起按 registry verified 规模自适应=DEB-5a 内层帽）；
      · 任何失败（超时 / 非零退出 / 输出不可解析）只记日志，绝不抛回主循环。
    --allow-unresolved：个别 verified 原子在收割件里找不到原文时，仍导入其余原子并如实
      报数（进变更日志），不让一条缺原文的 id 冻结整条 kb 入库链路；内容侧仍 fail-closed
      （缺原文的 id 不编造内容，只跳过）。
    入库成功记一行变更日志（每个自动动作一行）；返回摘要 dict，否则 None。"""
    if DRY:
        log(f"[DRY] 跳过 kb 入库（避免干跑写库）：{context}")
        return None
    if os.path.exists(STOP):
        log(f"STOP 熔断在位，跳过 kb 入库：{context}")
        return None
    try:
        r = subprocess.run(
            f"cd {WS} && python3 {KB_INGEST} --status verified --quiet "
            f"--allow-unresolved --db {KB_DB}",
            shell=True, capture_output=True, text=True, timeout=KB_INGEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"kb 入库超时（>{KB_INGEST_TIMEOUT}s，不阻塞主循环）：{context}")
        return None
    except Exception as e:  # noqa: BLE001 - 守护动作不许把异常抛回主循环
        log(f"kb 入库调用失败（不阻塞主循环）：{type(e).__name__}: {e} —— {context}")
        return None
    summ = None
    for line in reversed((r.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                summ = json.loads(line)
            except ValueError:
                summ = None
            break
    if r.returncode != 0 or not isinstance(summ, dict):
        log(f"kb 入库未成功（exit={r.returncode}，输出不可解析，不阻塞主循环）：{context}"
            f" → {(r.stdout or '')[-160:]!r}")
        return None
    if summ.get("unresolved"):
        log(f"kb 入库有 {summ['unresolved']} 条 verified 在收割件找不到原文（已跳过，未编造内容）")
    if summ.get("errors"):
        log(f"kb 入库有原子级错误（不阻塞主循环）：{summ['errors'][:3]}")
    changelog(f"verified 原子自动入库 kb：{context} → kb-ingest "
              f"new={summ.get('new')} updated={summ.get('updated')} "
              f"unchanged={summ.get('unchanged')} unresolved={summ.get('unresolved')}"
              f"（{KB_DB}）")
    return summ


def record_verify_agreement(st, card_id, info, judged):
    """同一 atom 集的跨卡一致率 + 分歧检测（观测登记；裁决时序由跨卡消费腿接管）。

    口径（2026-10-29 验证放大）：按候选 JSONL（= atom 集）分组，组内按副本血线
    （r<j>；老格式单卡算一条血线）各自保留**最新**一份回报的逐原子裁决；仅统计被
    ≥2 条血线都给出 uphold/refute 明裁决的共有原子，一致率 = 同判原子数 / 可比原子数
    （unverifiable 不进分子分母：证据不可得不是裁决分歧）。每次计算都打日志（持续
    输出一致率指标）；一致率 <1 时登记一行「分歧检测」列双方卡号与分歧原子（同一组
    同一分歧签名只登一次，避免刷屏）。本函数只观测一致率，不改判；跨卡分歧对原子状态的
    影响由「跨卡裁决时序消费腿」（admit 闸 + 消费腿 + 存量回灌腿）承担。
    """
    parsed = parse_verify_card_id(card_id)
    lineage = f"r{parsed[2]}" if parsed and parsed[2] else "single"
    cand = (info or {}).get("candidates") or ""
    gkey = os.path.basename(cand) if cand else f"card:{card_id}"
    groups = st.setdefault("verify_groups", {})
    g = groups.setdefault(gkey, {"candidates": cand, "lineages": {},
                                 "agreement": None, "divergence_sig": None})
    g["lineages"][lineage] = {"card_id": card_id,
                              "verdicts": {v["atom_id"]: v["verdict"] for v in judged}}
    if len(g["lineages"]) < 2:
        return
    tally = {}
    for lname, lrec in g["lineages"].items():
        for aid, verdict in lrec["verdicts"].items():
            if verdict in ("uphold", "refute"):
                tally.setdefault(aid, {})[lname] = verdict
    compared = {aid: m for aid, m in tally.items() if len(m) >= 2}
    if not compared:
        log(f"交叉验证一致率：atom 集 `{gkey}` 跨卡 {len(g['lineages'])} 张，暂无可比原子"
            f"（没有 ≥2 张卡都给出 uphold/refute 明裁决的共有原子）")
        return
    diverge = sorted(aid for aid, m in compared.items() if len(set(m.values())) > 1)
    agree_n = len(compared) - len(diverge)
    rate = agree_n / len(compared)
    card_ids = sorted(l["card_id"] for l in g["lineages"].values())
    g["agreement"] = {"rate": rate, "agree": agree_n, "compared": len(compared),
                      "cards": card_ids}
    log(f"交叉验证一致率：atom 集 `{gkey}` 跨卡 {len(g['lineages'])} 张 → "
        f"同判 {agree_n}/{len(compared)}={rate:.2f}（分歧 {len(diverge)} 条）")
    if rate >= 1:
        return
    detail = "；".join(
        f"{aid}(" + ",".join(f"{lname}={vd}" for lname, vd in sorted(compared[aid].items())) + ")"
        for aid in diverge[:8])
    sig = f"{card_ids}|{diverge}"
    if g.get("divergence_sig") == sig:
        return
    g["divergence_sig"] = sig
    changelog(f"分歧检测（跨卡裁决时序消费腿已接管）：同一 atom 集 `{gkey}` 跨卡一致率 "
              f"{agree_n}/{len(compared)}={rate:.2f}<1；卡 "
              f"{'、'.join('`' + c + '`' for c in card_ids)}；分歧原子：{detail}"
              f"（裁决时序最新者为准：更晚的非 uphold 裁决 → 该原子不 admit／已 verified "
              f"者双库降级待独立复核）")


# ---------- 跨卡裁决时序消费腿（RT-E32「跨卡分歧不阻塞 admit」修复，2026-11-02） ----------
# 缺陷根因（旧版本文件 26-29 行自述「分歧检测……纯观测，不阻塞 admit（各卡仍按 uphold 率
# 阈值与 registry 幂等规则独立裁决）」）：跨卡分歧只登记一行 changelog 就放过——更晚到的
# 独立验证卡把某原子判 refute/unverifiable，该原子仍以 verified 滞留 registry+kb 双库
# （RT-E32 对账门判据「verified ∧ 卡内 verdict≠uphold 计数必须=0」实测红；净化批清完存量
# 2.5h 即复现本类）。
# 判据（与 tools/test-e32-verified-uphold-recon.py 对账门同判据、同数据源=验证回报留档；
# 实现独立——对账门不借本路径，防「对账面自身失明」同源病）：
#   不变量：registry status=verified 的原子，其 note 依据卡（received_at）必须晚于该原子
#           在任何验证卡上的全部非 uphold（refute/unverifiable）裁决的 received_at
#           ——「入库所据卡是裁决史上最新权威仲裁」。
#   豁免（他卡可独立复核翻案，合法产物，不得误降级）：依据卡对本原子 verdict=uphold ∧
#         quote_check=true ∧ 依据卡 received_at 晚于该原子全部非 uphold 裁决。
# 三条腿：①admit 闸 ②消费腿 ③存量回灌腿（见下）。
CROSSCARD_NONUP = ("refute", "unverifiable")
_CROSSCARD_INDEX = {}   # atom_id -> (最新非 uphold 裁决 ts, 卡文件名, verdict)


def qc_true(v):
    """quote_check 机械真值：仅 JSON 布尔 true 算真（与 sandbox-harvester.validate 的
    isinstance(v.get("quote_check"), bool) 逐字同口径）。字符串 "true"/"false"、1/0、
    缺失一律非真。类型洞修复（2026-11-02）：本文件四处原用 bool() 直判该字段，
    Python 语义 bool("false")=True 使字符串 qc 在路由器侧被判「真值通过」而 admit、
    在收割方侧被整份拒收（同一 payload 双实现判定相反，实测 6 卡 51 原子受害）。
    改判 fail-closed：非布尔 qc 的原子不 admit、保留 candidate，与收割方拒收同向。"""
    qc = v.get("quote_check")
    return isinstance(qc, bool) and qc


def crosscard_index(verify_dir=None):
    """全扫验证回报留档 → {atom_id: (最新非 uphold 裁决 ts, 卡文件名, verdict)}。
    坏卡跳过不抛（对账门另有 fail-closed 的 unparseable 计数，本腿不重复计红）。"""
    vd = verify_dir or VERIFY_DIR
    idx, n_bad = {}, 0
    for p in sorted(glob.glob(os.path.join(vd, "*.json"))):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001 - 坏卡跳过（盲区由对账门 fail-closed 兜底）
            n_bad += 1
            continue
        pay = d.get("payload") or {}
        if not isinstance(pay, dict):
            n_bad += 1
            continue
        ts = float(d.get("received_at") or 0.0)
        for v in (pay.get("verdicts") or pay.get("verifications") or []):
            if isinstance(v, dict) and v.get("atom_id") and v.get("verdict") in CROSSCARD_NONUP:
                aid = v["atom_id"]
                cur = idx.get(aid)
                if cur is None or ts > cur[0]:
                    idx[aid] = (ts, os.path.basename(p), v["verdict"])
    return idx, n_bad


def crosscard_card_verdict(card_path, atom_id):
    """验证卡文件 → 该卡对本原子的裁决 (ts, verdict, quote_check)；查不到返回 None。"""
    try:
        with open(card_path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:  # noqa: BLE001 - 依据卡读不到=无豁免依据（fail-closed）
        return None
    pay = d.get("payload") or {}
    if not isinstance(pay, dict):
        return None
    ts = float(d.get("received_at") or 0.0)
    for v in (pay.get("verdicts") or pay.get("verifications") or []):
        if (isinstance(v, dict) and v.get("atom_id") == atom_id
                and v.get("verdict") in VERDICTS):
            return (ts, v["verdict"], qc_true(v))
    return None


def registry_row_ro(atom_id):
    """只读直查 registry 单原子 (status, note)；缺件返回 (None, None)。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
        try:
            row = con.execute("SELECT status, note FROM candidates WHERE id=?",
                              (atom_id,)).fetchone()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 判态失败按未决处理（不误降级）
        return (None, None)
    return (row[0], row[1]) if row else (None, None)


def crosscard_exempt(atom_id, note):
    """豁免判定（与对账门逐字同判据）：依据卡 uphold ∧ quote_check=true ∧ 依据卡
    received_at 晚于该原子全部非 uphold 裁决 → 他卡独立复核翻案，不降级。"""
    if not note or not note.startswith("依据:"):
        return False
    j = crosscard_card_verdict(note[3:], atom_id)
    if j is None:
        return False
    ts, verdict, qc = j
    if verdict != "uphold" or not qc:
        return False
    cur = _CROSSCARD_INDEX.get(atom_id)
    return cur is None or ts > cur[0]


def crosscard_admit_ok(atom_id, card_ts):
    """admit 闸：本卡裁决（received_at=card_ts）须晚于该原子全部非 uphold 裁决——否则
    更晚的卡已判 refute/unverifiable，该原子不得 admit（保留 candidate 待独立复核）。"""
    cur = _CROSSCARD_INDEX.get(atom_id)
    return cur is None or card_ts > cur[0]


def registry_demote(atom_id, ev_path):
    """registry verified→candidate 降级（跨卡分歧消费腿专用例外路径，registry.py demote）。
    返回 "demoted"/"no-such-atom-or-not-verified"/None（调用失败）。"""
    import shlex
    if DRY:
        log(f"[DRY] 跳过 registry demote（避免干跑写库）：{atom_id}，依据 {ev_path}")
        return None
    try:
        r = sh(f"cd {WS} && python3 {REGISTRY_CLI} demote {shlex.quote(atom_id)} "
               f"{shlex.quote(ev_path)} 2>&1 | tail -1", timeout=60)
    except subprocess.TimeoutExpired:
        log(f"registry demote 超时（>60s）: {atom_id}")
        return None
    except OSError as e:
        log(f"registry demote 失败 {type(e).__name__}: {str(e)[:60]} —— {atom_id}")
        return None
    return r or None


def consume_crosscard_divergence(atom_ids=None):
    """消费腿：双库里 verified ∧ 不豁免 的原子 → 降级待独立复核翻案。
    atom_ids=None → 存量回灌（只查有非 uphold 裁决史的原子，双库 verified 的才动）。
    返回明细 [(atom_id, 台账状态, 说明)]；台账状态 ∈ registry-demoted/kb-retired/
    registry-unresolved/kb-unresolved（未落成如实记账，下轮重试）。"""
    detail = []
    cands = sorted(set(_CROSSCARD_INDEX) if atom_ids is None else set(atom_ids))
    for aid in cands:
        rec = _CROSSCARD_INDEX.get(aid)
        if rec is None:
            continue                       # 无非 uphold 裁决史 → 无跨卡分歧可消费
        ts, card, verdict = rec
        st, note = registry_row_ro(aid)
        kb_st = _kb_atom_status(aid)
        reg_bad = (st == "verified") and not crosscard_exempt(aid, note)
        kb_bad = (kb_st == "verified") and not crosscard_exempt(aid, note)
        if not (reg_bad or kb_bad):
            continue
        ev_path = os.path.join(VERIFY_DIR, card)
        why = ("跨卡分歧消费：卡 %s（received_at=%.3f）判 %s，入库依据卡更早 → 降级待独立复核"
               % (card, ts, verdict))
        if reg_bad:
            r = registry_demote(aid, ev_path)
            if r == "demoted":
                detail.append((aid, "registry-demoted", why))
            else:
                detail.append((aid, "registry-unresolved", "%s（registry demote=%r）"
                               % (why, r)))
        if kb_bad:
            ok = kb_retire_refuted(aid, why)
            detail.append((aid, "kb-retired" if ok else "kb-unresolved", why))
    return detail


def crosscard_startup_reconcile():
    """存量回灌腿（启动时）：全扫留档卡重建跨卡裁决索引 → 双库 verified ∧ 不豁免 的原子
    一并降级。自愈腿——净化批只清存量一轮（实测净化批后 2.5h 即复现本类），机制腿必须
    自己收口。返回明细条数。"""
    idx, n_bad = crosscard_index()
    _CROSSCARD_INDEX.clear()
    _CROSSCARD_INDEX.update(idx)
    log(f"跨卡裁决索引：留档卡全扫完成，非 uphold 裁决涉及原子 {len(idx)} 个"
        f"（坏卡 {n_bad} 张跳过；对账门另有 fail-closed 的 unparseable 计数）")
    detail = consume_crosscard_divergence()
    if detail:
        changelog("跨卡分歧消费（存量回灌腿）：双库 verified ∧ 依据卡非裁决史最新的原子 "
                  "%d 条已降级（registry verified→candidate；kb verified→retired），"
                  "欠账待独立复核翻案：%s"
                  % (len(detail), "、".join(d[0] for d in detail[:8])))
    else:
        log("跨卡分歧消费（存量回灌腿）：双库无 verified 违规原子")
    return detail


def handle_verify_report(st, name, path, rep):
    """B 的验证回报 → 聚合裁决。quote_check 全 false = 摆烂，作废不计。"""
    pay = rep.get("payload") or {}
    card_id = str(pay.get("card_id") or rep.get("task_id") or "")
    # 裁决清单双键兼容：verdicts（新卡模板主键，tools/cross-verify.py）/ verifications
    # （历史卡与已归档回报的老键）。两个键都认，缺一即按无效回报忽略。
    vsrc = pay.get("verdicts") or pay.get("verifications") or []
    verifs = [v for v in vsrc
              if isinstance(v, dict) and v.get("atom_id") and v.get("verdict") in VERDICTS]
    if not card_id or not verifs:
        changelog(f"验证回报无效（无 card_id 或无有效裁决清单 verdicts/verifications），忽略：`{name}`")
        return
    info = card_info(st, card_id)
    ev_path = save_verify_report(name, rep)
    known = set((info or {}).get("atom_ids") or [])
    judged = [v for v in verifs if not known or v["atom_id"] in known]
    dropped = len(verifs) - len(judged)
    if not judged:
        changelog(f"验证回报的 atom_id 与卡 `{card_id}` 不对应（{len(verifs)} 条全不认识），忽略：`{name}`")
        return
    # 防摆烂：quote_check 全 false → 该验证卡作废，不计 admit/reject
    if not any(qc_true(v) for v in judged):
        if info:
            info["status"] = "void"
        changelog(f"交叉验证作废（防摆烂）：卡 `{card_id}` 回报 quote_check 全 false"
                  f"（{len(judged)} 条），不 admit 不 reject，回报留档 {os.path.basename(ev_path)}")
        return
    n = len(judged)
    up = sum(1 for v in judged if v["verdict"] == "uphold")
    rate = up / n
    bad = [v for v in judged if v["verdict"] != "uphold"]
    tail = f"（{dropped} 条 atom_id 不在卡内已忽略）" if dropped else ""
    # 跨卡裁决时序（RT-E32 跨卡分歧消费腿）：本卡的非 uphold 裁决入索引——admit 闸与消费腿
    # 共用同一份「裁决史上最新非 uphold 裁决」账（索引口径见本文件消费腿段注释）。
    # received_at 缺失/为 0 的回报（合成夹具、早期无戳老卡）不带时序信息，不入索引——
    # 「裁决史上最新」的比较只能发生在都带时间戳的真实裁决之间（消费腿同理不消费无戳裁决）。
    card_ts = float(rep.get("received_at") or 0.0)
    if card_ts > 0:
        for v in judged:
            if v["verdict"] in CROSSCARD_NONUP:
                aid = v["atom_id"]
                cur = _CROSSCARD_INDEX.get(aid)
                if cur is None or card_ts > cur[0]:
                    _CROSSCARD_INDEX[aid] = (card_ts, os.path.basename(ev_path), v["verdict"])
    if rate >= UPHOLD_THRESHOLD:
        # RT 审计修复（2026-10-31）：只 admit 裁决为 uphold 的原子。原实现把全量 judged
        # （含 refute/unverifiable）整包送 registry_admit——卡内他原子把 uphold 率抬过
        # 阈值后，验证者明确判非的原子也一并翻转 verified（实测 694 张 rate≥0.8 混合裁决
        # 卡的被拒原子全部入库；铁证案例 sbx-kb-atoms-cls-2303.17760-r2-19，裁决原文
        # 「数字 25000 在证据文本中不存在」仍为 verified）。坏原子保留 candidate：不随卡
        # 搭车入库，也不在本分支终判 reject（他卡可独立复核仲裁）。
        # RT 修复（2026-11-01）：uphold 逐条消费 quote_check 机械真值。verdict=uphold
        # 而 quote_check 非真（false/缺；2026-11-02 类型洞修复起含字符串 "true"/"false"、
        # 1/0 等一切非 JSON 布尔值，判定走 qc_true 与收割方同口径）= 验证者回报「引文未在
        # 证据文本中逐字出现」仍判成立——聚合与门族此前对该机械真值全维失明（全扫
        # sandbox/verify 8,414+ 份回报共 1,784 处此组合，其中 578 条经独立回查确证坏引文
        # 已入库）。此类原子不 admit、保留 candidate（他卡可以 uphold∧quote_check=true
        # 独立复核翻案），本分支不终判 reject；卡级通过率仍按验证者裁决口径计，防摆烂
        # 全 false 作废条款不变。
        qc_false_up = [v["atom_id"] for v in judged
                       if v["verdict"] == "uphold" and not qc_true(v)]
        good = [v["atom_id"] for v in judged
                if v["verdict"] == "uphold" and qc_true(v)]
        # admit 闸（跨卡裁决时序消费腿）：该原子在更晚的卡上已被判 refute/unverifiable →
        # 本卡裁决不是裁决史上最新 → 该原子不 admit（保留 candidate，待独立复核翻案）。
        # 修复前此处分歧只观测不阻塞（实测：后到的独立验证卡判 refute，原子仍双库 verified）。
        xcard_blocked = [aid for aid in good if not crosscard_admit_ok(aid, card_ts)]
        if xcard_blocked:
            blocked_set = set(xcard_blocked)
            good = [aid for aid in good if aid not in blocked_set]
        ok, miss = registry_admit(good, ev_path, (info or {}).get("candidates"))
        if info:
            info["status"] = "passed"
        skipnote = (f"；refute/unverifiable {len(bad)} 条不入库（保留 candidate）"
                    if bad else "")
        if qc_false_up:
            skipnote += (f"；uphold∧quote_check 非真 {len(qc_false_up)} 条不入库"
                         f"（机器回查引文未证实，保留 candidate）")
        if xcard_blocked:
            skipnote += (f"；跨卡裁决时序非最新 {len(xcard_blocked)} 条不入库"
                         f"（更晚的卡判 refute/unverifiable，保留 candidate待独立复核）")
        changelog(f"交叉验证通过：卡 `{card_id}` uphold {up}/{n}={rate:.2f}≥{UPHOLD_THRESHOLD} → "
                  f"registry admit {ok} 条（no-such/wrong-state {miss}）{skipnote}，"
                  f"依据 {os.path.basename(ev_path)}{tail}")
        # verified 状态落定 → kb 入库（幂等；STOP 熔断/DRY/失败都只记日志，不阻塞主循环）
        kb_ingest_verified(f"卡 `{card_id}` uphold {up}/{n} → registry admit {ok} 条")
    else:
        why = f"交叉验证未过：uphold {up}/{n}={rate:.2f}<{UPHOLD_THRESHOLD}（卡 {card_id}）"
        ok = registry_reject([v["atom_id"] for v in judged], why)
        if info:
            info["status"] = "failed"
        changelog(f"交叉验证未过：卡 `{card_id}` uphold {up}/{n}={rate:.2f}<{UPHOLD_THRESHOLD} → "
                  f"registry reject {ok} 条，转 r3 重派{tail}")
        if info and info.get("task_id"):
            base = info["task_id"]
            arx = info.get("arxiv") or (ARX_RE.search(base).group(1) if ARX_RE.search(base) else "")
            if arx and (base + "-r3") not in st["r3"]:
                st["r3"].append(base + "-r3")
                detail = "；".join(
                    f"{v['atom_id'].split('sbx-')[-1]}:{v['verdict']}:{str(v.get('reason') or '')[:60]}"
                    for v in bad[:8])
                make_rework_card(st, base, arx,
                                 f"第 2 轮交叉验证 uphold {up}/{n}={rate:.2f}（阈值 {UPHOLD_THRESHOLD}）。"
                                 f"被 refute/unverifiable 的条目（atom:裁决:理由）：{detail}",
                                 "r3",
                                 f"交叉验证未过自动重派：`{base}-r3` 上门户（B 的裁决理由已写入任务书）")
    # ② 消费腿（跨卡裁决时序）：本卡判非 uphold 的原子，若已 verified 且入库依据卡更早
    # → 双库降级（registry verified→candidate；kb verified→retired），欠账待独立复核翻案。
    # 修复前此处无消费者：更晚的独立验证卡判 refute，原子仍以 verified 滞留双库。
    xcard_nonup = [v["atom_id"] for v in judged if v["verdict"] in CROSSCARD_NONUP]
    if xcard_nonup:
        xdetail = consume_crosscard_divergence(xcard_nonup)
        for _aid, _what, _why in xdetail:
            log(f"跨卡分歧消费：{_aid} → {_what}（{_why}）")
        if xdetail:
            changelog("跨卡分歧消费（消费腿）：卡 `%s` 的非 uphold 裁决使 %d 条已 verified "
                      "原子降级（registry verified→candidate；kb verified→retired），"
                      "欠账待独立复核翻案：%s"
                      % (card_id, len(xdetail), "、".join(d[0] for d in xdetail[:8])))
    # 分歧检测（观测登记）：记录同一 atom 集的跨卡一致率，一致率 <1 登记一行
    record_verify_agreement(st, card_id, info, judged)


def poll_verify_reports(st):
    """扫 gov reports/（兼看本地 raw/），消费 payload 带 verify 的回报。"""
    consumed = st.setdefault("verify_reports", [])
    scanned = st.setdefault("verify_scanned", [])
    paths = gov_report_paths() + sorted(glob.glob(RAW_DIR + "/*.json"))
    seen = set()
    for p in paths:
        name = os.path.basename(p)
        if name in seen or name in consumed or name in scanned:
            continue
        seen.add(name)
        rep = fetch_report(p)
        if rep is None:
            continue  # 拉取失败不标记，下轮再试
        pay = rep.get("payload") or {}
        is_verify = bool(pay.get("verify")) or str(rep.get("task_id") or "").startswith("kb-verify-")
        if not is_verify:
            if len(scanned) > 500:  # 状态文件防膨胀
                del scanned[:len(scanned) - 500]
            scanned.append(name)
            continue
        handle_verify_report(st, name, p, rep)
        consumed.append(name)
        mark_harvested(name)


# ---------- ⑤ 仲裁/蒸馏回报消费（kb-arbitrate 终裁落双库 / kb-distill 聚合登记） ----------
# 2026-11-02 kb-arbitrate 回报链断裂修复：此前 kb-arbitrate-*/kb-distill-* 回报被收割方
# 按抽取 schema 整类拒收（「payload.atoms 缺失或为空」，HARVEST-LOG 实存 55 行全 rejected），
# payload.rulings 终裁与 payload.findings 复核结论全链零消费者——被判 refute 的原子
# registry/kb 双库滞留 verified（实证案例 sbx-kb-atoms-acr-2404.05427-22，仲裁 rationale
# 「§6.1 引文逐字命中但张冠李戴：17.96%/701 秒属 AutoCodeRover @3」而双库仍 verified）。
# 消费语义（与卡面「聚合规则（告知在先）」条款同源，quality-cards.py ②③）：
#   · kb-arbitrate：final=refute → registry arbitrate-refute（verified→rejected，唯一例外
#     路径，candidate 走普通 reject）+ kb retire（→retired，provenance 留痕）；依据=回报
#     本地留档。uphold/unverifiable 只聚合登记不改状态（原子已 verified；终裁不抬、也不
#     复活他卡已判死原子——翻案须新仲裁卡）。多卡对同一原子先后终裁时先到 refute 定死。
#   · kb-distill：findings 聚合 info_loss/wrong_winner 比例作合并蒸馏规则回归信号，
#     纯观测不改任何原子状态（卡面明示「本卡是一次性复核卡」）。
# 护栏同全线：STOP 熔断（主循环）/DRY 只记日志不落库不写留档；落库未全成不计消费、
# 下轮重试，≥ARBITRATE_RETRY_CAP 转人工登记（防瞬时故障吞判决，也防永久缺件刷屏）。
ARB_DIR = WS + "/kb-seed/sandbox/arbitrate"      # 仲裁/蒸馏回报本地留档（refute 落库依据）
# 零终裁回报留档（2026-11-03 RT 修复·零终裁蒸发面）：终裁**未落库**的回报副本放
# arbitrate/no-verdict/ 子目录——与 ARB_DIR 顶层「终裁已落库的落库依据」严格分目录，
# 免得对账把「终裁没落库」误当成「已解决」（旧口径正是这么误判的：零终裁回报进了
# arb_reports 即记 resolved-by-router，对账门 108/108 全绿而终裁整批蒸发）。
# 子目录随 ARB_DIR 动态派生（测试把 ARB_DIR 打桩到 scratch 时，零终裁留档一并落
# scratch，零写生产面）。
def arb_nov_dir():
    """零终裁回报留档目录（ARB_DIR/no-verdict/；随 ARB_DIR 派生）。"""
    return ARB_DIR.rstrip("/") + "/no-verdict"


ARBITRATE_RETRY_CAP = 3
# 零终裁重派账（2026-11-03 RT·「只登记不重派」滞留面）：零终裁登记后的消费腿口径——
# 同一分歧（divergence_key）零终裁卡 ≥ ARB_REISSUE_CAP（与 quality-cards
# _arbitrate_existing 同帽值）= 该分歧自动重发预算耗尽，转运营者并告警；
# ARB_REISSUE_DEADLINE_S = 登记 pending 超此时长仍无重派动作（reissued/exhausted）
# 也告警（防「重发预算没耗尽但重发线坏了」的静默滞留——旧形态正是无任何消费面：
# 重发被发卡幂等腿遮蔽、唯一消费面（W5 对账门）把「有主」记绿，55 卡/64 原子滞留）。
ARB_REISSUE_CAP = 2
ARB_REISSUE_DEADLINE_S = 24 * 3600
ALARMS_LOG = WS + "/状态观测/alarms.log"   # 报警流水（JSONL；写法对齐 factory-watch log_alarms）
ARBITRATE_FINALS = ("uphold", "refute", "unverifiable")
AGREE_WITHS = ("b1", "b2", "neither")
DISTILL_ROLES = ("winner", "loser")
DISTILL_FINALS = ("no_loss", "info_loss", "wrong_winner", "unverifiable")
# ---- refute 终裁厂内回查面（2026-11-02 红队 RT：AGENTS 契约 quote 条款零强制修复）----
# 此前 final=refute 的落双库只采信沙箱自述 quote_check 布尔（且旧 rs 过滤器连布尔都不
# 看——五字段契约仅收割方单侧执行），任何持有合法 claim_token 的外部沙箱可伪造终裁把
# verified 原子在 registry/kb 双库翻案（实测 PoC：never-issued 卡 + refute → 双库
# resolved）。契约「发布方逐条逐字回查」在消费线落地为三道机械门（见 _arb_refute_recheck）：
#   ①卡必须在册：quality-cards gen_arbitrate 发卡时写 task-seeds/<卡id>/meta.json
#     （arbitrate.atom_ids=厂内铸定的本卡原子名册）——never-issued 卡的「终裁」不可消费；
#   ②refute 原子须在本卡名册内（越册=越权终裁，不落库）；
#   ③终裁自述 quote_check 位须与厂内对原子存档 quote 的逐字回查一致（quote 在=qc 须
#     true、quote 不在=qc 须 false——伪造「quote 已烂」的翻案被机械事实否决）。
# 回查数据源全部厂内自持、零网络：kb.db atoms.attrs.source.quote（收割入库时经 E31
# fail-closed 回查存档）+ evidence-cache/<arx>/（收割方既有缓存）；arx 从 atom_id 铸定段
# 推导（candidate_id=sbx-<base>-<n>，正则与 sandbox-harvester ARXIV_RE 单一语义镜像）
# ——绝不取信回报 payload 自带的 arxiv/card_id 指针（那是攻击者可控字段）。
# 残余信任边界（如实登记）：对「quote 逐字在而命题层错」的 refute（qc=true 且 quote 回查
# hit），厂内机械面无法证伪其命题判断——该语义信任仍锚在外部仲裁员；缓解=①本卡名册
# 限定爆炸半径 ②claim 账本可归因 ③全程留档+台账 ④翻案须新仲裁卡（既有设计）。
ARB_SEEDS_DIR = WS + "/kb-seed/sandbox/task-seeds"   # 发卡名册（quality-cards gen_arbitrate 写面）
KB_EVIDENCE_CACHE = WS + "/kb-seed/sandbox/evidence-cache"  # 收割方既有证据缓存（只读）
_ATOM_ARX_RE = re.compile(r"kb-atoms-.+?-(\d{4}\.\d{4,5})(?:-r\d+)*$")  # 镜像 harvester ARXIV_RE

_KBSTORE = None


def _kb_store():
    """KBStore 单例（kb/kb.db；经 importlib 直载 kb/store.py，零网络零第三方）。"""
    global _KBSTORE
    if _KBSTORE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("kbstore", WS + "/kb/store.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _KBSTORE = mod.KBStore(KB_DB)
    return _KBSTORE


def save_arb_report(name, rep):
    """仲裁/蒸馏回报本地留档 → refute 落库的依据文件路径（DRY 只给路径不落盘）。"""
    os.makedirs(ARB_DIR, exist_ok=True)
    p = os.path.join(ARB_DIR, name)
    if not DRY:
        json.dump(rep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def save_arb_nov_report(name, rep):
    """零终裁回报留档（终裁未落库的证据副本）→ 落 arbitrate/no-verdict/。

    与 save_arb_report（顶层=终裁已落库的落库依据）严格分目录：顶层那份是「终裁
    已处理」的凭据，本目录那份是「终裁没落库」的凭据——两者混在一处，对账就会把
    零终裁误当成已解决（2026-11-03 确证缺陷面）。DRY 只给路径不落盘。"""
    d = arb_nov_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    if not DRY:
        json.dump(rep, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def registry_arbitrate_refute(atom_id, ev_path):
    """kb-arbitrate 终裁 refute → registry verified→rejected（唯一例外路径，附依据）。
    返回 "arbitration-refuted"（翻了）/"no-such-atom-or-not-verified"/None（调用失败）。"""
    import shlex
    if DRY:
        log(f"[DRY] 跳过 registry arbitrate-refute（避免干跑写库）：{atom_id}，依据 {ev_path}")
        return None
    try:
        r = sh(f"cd {WS} && python3 kb-seed/registry.py arbitrate-refute {shlex.quote(atom_id)} "
               f"{shlex.quote(ev_path)} 2>&1 | tail -1", timeout=60)
    except subprocess.TimeoutExpired:
        log(f"registry arbitrate-refute 超时（>60s）: {atom_id}")
        return None
    except OSError as e:
        log(f"registry arbitrate-refute 失败 {type(e).__name__}: {str(e)[:60]} —— {atom_id}")
        return None
    return r or None


def registry_status_ro(atom_id):
    """只读直查 registry 单原子状态（判「终态已决」用；读不到返回 None）。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % REGISTRY, uri=True)
        try:
            row = con.execute("SELECT status FROM candidates WHERE id=?",
                              (atom_id,)).fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 判态失败按未决处理（走重试/人工登记）
        return None


def kb_retire_refuted(atom_id, why):
    """kb-arbitrate 终裁 refute → kb 原子 retired（verified→retired 为既有合法迁移；
    candidate→retired 亦合法）。返回 True=翻案成功，False=未翻（终态/缺件/异常，判态
    由调用方读 _kb_atom_status 分辨）。"""
    if DRY:
        log(f"[DRY] 跳过 kb retire（避免干跑写库）：{atom_id}，{why}")
        return False
    try:
        return bool(_kb_store().update_status(atom_id, "retired", reason=why))
    except Exception as e:  # noqa: BLE001 - 单原子失败不许带崩消费线
        log(f"kb retire 失败（不阻塞消费线）: {atom_id} → {type(e).__name__}: {str(e)[:80]}")
        return False


def _kb_atom_status(atom_id):
    """只读直查 kb.db 单原子状态（update_status 返回 False 时分辨「终态已决/缺件」与
    「真失败」；读不到返回 None）。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
        try:
            row = con.execute("SELECT status FROM atoms WHERE id=?", (atom_id,)).fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None


def _kb_atom_quote(atom_id):
    """只读直查 kb.db 单原子存档 quote（attrs.source.quote，strip 后）；缺件/坏 JSON/
    读失败返回 None——调用方按「无法回查」fail-closed（与 _kb_atom_status 同款护栏）。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % KB_DB, uri=True)
        try:
            row = con.execute("SELECT attrs FROM atoms WHERE id=?", (atom_id,)).fetchone()
        finally:
            con.close()
        if not row:
            return None
        src = (json.loads(row[0]) or {}).get("source") or {}
        q = src.get("quote")
        return q.strip() if isinstance(q, str) and q.strip() else None
    except Exception:  # noqa: BLE001 - 回查读失败不许带崩消费线，按不可回查处理
        return None


def _arb_card_scope(card_id):
    """发卡名册：卡 id → 本卡 atom_ids（厂内铸定）；未发卡/缺 meta/缺名册返回 None。
    名册唯一来源=quality-cards gen_arbitrate 落的 task-seeds/<卡id>/meta.json
    （arbitrate.atom_ids），回报 payload 自带的 card_id/atom 指针一律不采信。"""
    if not isinstance(card_id, str) or not card_id.strip():
        return None
    try:
        with open(os.path.join(ARB_SEEDS_DIR, card_id.strip(), "meta.json"),
                  encoding="utf-8") as fh:
            arb = (json.load(fh) or {}).get("arbitrate") or {}
        ids = arb.get("atom_ids")
        return ids if isinstance(ids, list) and ids else None
    except Exception:  # noqa: BLE001 - 读不到=不在册（fail-closed）
        return None


def _arb_report_card_id(name):
    """回报文件名 → 卡 id（去 .json 后缀与 13 位时间尾戳；=发卡名册目录名）。

    回报文件名形如 kb-arbitrate-<卡id>-<13位ms>.json；卡 id 带 -r2/-6 之类副本轮次，
    与 task-seeds/<卡id>/ 一一对应（发卡名册唯一来源）。"""
    base = name[:-5] if name.endswith(".json") else name
    return re.sub(r"-\d{13}$", "", base)


def _arb_rulings_ok(raw_all):
    """仲裁 rulings 清单 → 合法条（五字段口径：atom_id/final/quote_check 布尔/
    rationale 非空/agree_with 词表；镜像收割方 validate，单一真源在此）。

    非法条整份不作数（收割方同口径 fail-closed：任一条缺件→整份拒收）。"""
    return [r for r in (raw_all or [])
            if isinstance(r, dict) and isinstance(r.get("atom_id"), str) and r["atom_id"].strip()
            and r.get("final") in ARBITRATE_FINALS
            and isinstance(r.get("quote_check"), bool)
            and isinstance(r.get("rationale"), str) and r["rationale"].strip()
            and r.get("agree_with") in AGREE_WITHS]


def _arb_rep_has_verdict(rep):
    """这份回报载荷里是否含真终裁/复核结论（合法 rulings / findings）。返回 bool。"""
    pay = (rep or {}).get("payload") or {}
    if _arb_rulings_ok(pay.get("rulings")):
        return True
    fs = pay.get("findings")
    return bool(isinstance(fs, list)
                and any(isinstance(f, dict) and f.get("final") in DISTILL_FINALS for f in fs))


def arb_verdict_evidence(name):
    """ARB_DIR 顶层这份留档是否含真终裁（=终裁确已处理过的凭据）。返回 bool。

    ARB_DIR 顶层只在终裁路径写入（save_arb_report），故其存在已是「终裁已处理」的
    凭据；本函数再核载荷里确有合法 rulings/findings（防目录里混进别的东西）。
    零终裁副本在 arbitrate/no-verdict/ 子目录，不在此列——终裁没落库就不算已解决。"""
    try:
        rep = json.load(open(os.path.join(ARB_DIR, name), encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 读不到=无凭据（按未落库处理）
        return False
    return _arb_rep_has_verdict(rep)


def arb_zero_verdict_evidence(st, names, batch=60):
    """零终裁回报取证留档（批量、fail-soft）：把「终裁未落库」的回报副本取回归档。

    来源：本地 raw/ 优先；否则 gov reports/ 一次 ssh cat 批量取回（按 cat 顺序与
    JSON 流 raw_decode 逐份对齐——每份回报恰一个 JSON 对象）。取不到就跳过：登记
    仍以收割方拒收行为据（不阻塞主线）。副本落 arbitrate/no-verdict/（语义=终裁没
    落库，与顶层「落库依据」分目录），并回填零终裁台账的 evidence 字段。
    返回 {回报文件名: 本地留档路径}。"""
    out = {}
    nov = st.setdefault("arb_zero_verdict", {})
    todo = [n for n in dict.fromkeys(names or []) if isinstance(n, str) and n.endswith(".json")]
    todo = todo[:batch]
    if not todo:
        return out
    last = st.get("arb_zero_verdict_fetch_ts") or 0
    if time.time() - last < 600:
        return out          # 退避：10min 内不重复取证（避免逐轮刷 ssh）
    st["arb_zero_verdict_fetch_ts"] = time.time()
    for n in list(todo):    # 本地 raw/ 优先（零网络）
        p = os.path.join(RAW_DIR, n)
        if os.path.isfile(p):
            try:
                rep = json.load(open(p, encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 坏文件跳过
                continue
            out[n] = save_arb_nov_report(n, rep)
    rest = [n for n in todo if n not in out]
    if rest:
        r = None
        try:
            cmd = "%s %s 'cat %s'" % (SSH, GOV,
                                     " ".join(os.path.join(GOV_REPORTS, n) for n in rest))
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as e:
            log(f"零终裁取证拉取失败 {type(e).__name__}: {str(e)[:60]}（登记继续，不阻塞主线）")
        if r is not None and r.returncode == 0:
            dec, s, i = json.JSONDecoder(), r.stdout, 0
            for n in rest:  # cat 顺序=入参顺序，逐份对齐
                while i < len(s) and s[i] in " \t\r\n":
                    i += 1
                if i >= len(s):
                    break
                try:
                    obj, i = dec.raw_decode(s, i)
                except ValueError:
                    log("零终裁取证流解析中断（已取到的照留，不阻塞主线）")
                    break
                if isinstance(obj, dict) and not _arb_rep_has_verdict(obj):
                    out[n] = save_arb_nov_report(n, obj)
        elif r is not None:
            log(f"零终裁取证拉取失败（rc={r.returncode}）：登记继续，不阻塞主线")
    for n, p in out.items():
        e = nov.get(n)
        if isinstance(e, dict) and not e.get("evidence"):
            e["evidence"] = p
    return out


def register_arb_zero_verdict(st, name, why, atoms=None, evidence=None, cid=None):
    """零终裁回报登记（终裁未落库 → 显式登记待运营者；绝不静默蒸发）。

    2026-11-03 RT 修复·零终裁蒸发面：旧口径把「无有效 rulings」的回报当「已消费」
    写进 arb_reports 且不留档 ⇒ 终裁零落库、对账门测不出（判 resolved-by-router
    全绿）。现落 st['arb_zero_verdict'][<回报文件名>] = {card, why, atoms, n_atoms,
    evidence, status}——有主（点名受影响原子）+ 留证（证据副本路径）+ 可测。
    防重放由调用方保证（消费线侧=arb_reports；回流腿侧=arb_rejects）。"""
    nov = st.setdefault("arb_zero_verdict", {})
    if name in nov:
        return nov[name]
    cid = cid or _arb_report_card_id(name)
    if atoms is None:
        atoms = _arb_card_scope(cid) or []
    e = nov[name] = {
        "card": cid,
        "why": (why or "")[:200],
        "atoms": list(atoms),
        "n_atoms": len(atoms),
        "evidence": evidence or "",
        "status": "no-verdict-registered",
        # 重派账（2026-11-03 RT·只登记不重派滞留面）：登记即开账（pending），由
        # arb_reissue_accounting 消费腿逐轮推进 reissued:<卡>/exhausted——登记不许
        # 是终点（旧形态登记后无任何消费面，分歧被幂等腿永久遮蔽）。
        "reissue": "pending",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    changelog(f"仲裁/蒸馏零终裁登记（终裁未落库，待人工重派/换卡）：`{name}`：{e['why']}；"
              f"受影响原子 {e['n_atoms']} 个（{'；'.join(e['atoms'][:6]) or '—'}）"
              + (f"，证据 {os.path.basename(e['evidence'])}" if e["evidence"] else ""))
    return e


def nov_names(st):
    """零终裁台账里的回报文件名集合（st['arb_zero_verdict'] 的键）。"""
    return set((st.get("arb_zero_verdict") or {}).keys())


def _zv_div_key_of(card):
    """零终裁卡 → 分歧记账键：「d:<divergence_key>」（发卡名册 meta 在册时，精确到分歧）；
    种子已撤=回退「f:<卡号族前缀>」（同 base 粗界账——仍可对账告警，绝不因种子撤除静默）。"""
    try:
        arb = (json.load(open(os.path.join(ARB_SEEDS_DIR, card, "meta.json"),
                             encoding="utf-8")).get("arbitrate") or {})
        if arb.get("divergence_key"):
            return "d:" + arb["divergence_key"]
    except Exception:  # noqa: BLE001 - 种子不在册照回退
        pass
    m = re.match(r"^(kb-arbitrate-.+)-\d+$", card or "")
    return "f:" + (m.group(1) if m else (card or "?"))


def arb_reissue_accounting(st):
    """零终裁台账消费腿（2026-11-03 RT·「只登记不重派」滞留面）：给每条零终裁登记记
    重派账（entry['reissue']），滞留/预算耗尽即告警+变更日志点名。

    旧形态（确证发现亲证）：登记后**无任何消费面**——重发被发卡幂等腿遮蔽
    （quality-cards._arbitrate_existing 按 divergence_key 判「已承载」→ 永不重发，
    种子不删=永不再发）、唯一消费面（W5 对账门）把「有主」记绿、无门红/无台账/无
    告警 → 55 卡/64 原子仲裁链永久滞留（其中 11 条带未决分歧的原子已双库 verified）。
    本腿让台账从「登记终点」变「重派账」：

      · 同分歧存在健康承载卡（发卡名册在册、不在零终裁台账——gen_arbitrate 重发落的
        新卡）→ reissue="reissued:<卡>"（重派在途；终裁落库后走既有 resolved 对账）；
      · 同分歧零终裁卡 ≥ ARB_REISSUE_CAP → reissue="exhausted"（自动重发预算耗尽，
        转运营者）+ alarms.log（code=ARB-REISSUE-STUCK，同分歧一次性）+ 变更日志点名；
      · 其余 → reissue="pending"；登记 ts 超 ARB_REISSUE_DEADLINE_S 仍 pending =
        重发线停滞（预算没耗尽但没人干活）→ 同款告警（文案区分）。

    判据全本地读（扫发卡名册 meta.json + 台账分组，零 ssh），每轮跑代价可忽略；
    告警防重旗标 st['arb_reissue_alarmed'][<分歧键>] 一次性；异常不阻塞主循环。"""
    nov = st.setdefault("arb_zero_verdict", {})
    if not nov:
        return nov
    # 台账按分歧键分组（组内卡数=该分歧已耗的零终裁预算，对齐 quality-cards 重发帽）
    zv_by_dk, zv_all = {}, set()
    for e in nov.values():
        if not isinstance(e, dict):
            continue
        c = e.get("card") or ""
        zv_by_dk.setdefault(_zv_div_key_of(c), []).append(c)
        zv_all.add(c)
    # 发卡名册 divergence_key → 卡清单（一次全量扫，含健康承载卡；零 ssh）
    carriers = {}
    try:
        for d in glob.glob(os.path.join(ARB_SEEDS_DIR, "kb-arbitrate-*")):
            try:
                dk = ((json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
                       .get("arbitrate") or {}).get("divergence_key"))
                if dk:
                    carriers.setdefault("d:" + dk, []).append(os.path.basename(d))
            except Exception:  # noqa: BLE001 - 单份坏 meta 不带崩名册扫描
                continue
    except Exception as e:  # noqa: BLE001 - 名册不可读=本轮只推进台账分组
        log(f"零终裁重派账名册扫描失败（不阻塞）: {type(e).__name__}: {str(e)[:80]}")
    alarmed = st.setdefault("arb_reissue_alarmed", {})
    now = time.time()
    for name, e in nov.items():
        if not isinstance(e, dict):
            continue
        card = e.get("card") or _arb_report_card_id(name)
        dk = _zv_div_key_of(card)
        zvc = zv_by_dk.get(dk) or ([card] if card not in zv_all else [])
        healthy = [c for c in carriers.get(dk) or [] if c not in zv_all]
        try:
            age = now - time.mktime(time.strptime(e.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
        except Exception:  # noqa: BLE001 - ts 坏按 0（不误报超时）
            age = 0
        if zvc and len(zvc) >= ARB_REISSUE_CAP:
            e["reissue"] = "exhausted"
            why = "重发预算耗尽（同分歧 %d 张零终裁卡）" % len(zvc)
        elif healthy:
            e["reissue"] = "reissued:" + sorted(healthy)[-1]
            continue
        else:
            e["reissue"] = "pending"
            if age < ARB_REISSUE_DEADLINE_S:
                continue
            why = ("登记超 %ds 仍 pending（重发预算 %d/%d 未耗尽但无重派动作）"
                   % (ARB_REISSUE_DEADLINE_S, len(zvc), ARB_REISSUE_CAP))
        if alarmed.get(dk):
            continue   # 同分歧一次性（台账 reissue 字段恒记现态，告警流水留一次性凭据）
        alarmed[dk] = time.strftime("%Y-%m-%d %H:%M:%S")
        atoms = e.get("atoms") or []
        msg = (f"{why}：分歧 {dk[:80]}；零终裁卡 {','.join(zvc) or card}；"
               f"受影响原子 {len(atoms)} 个（零终裁台账 st.arb_zero_verdict）")
        changelog(f"零终裁重派滞留告警（待运营者，{why}）：`{msg}`")
        if not DRY:
            try:
                with open(ALARMS_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "level": "amber",
                        "code": "ARB-REISSUE-STUCK", "message": msg,
                        "since": alarmed[dk],
                    }, ensure_ascii=False) + "\n")
            except Exception as ex:  # noqa: BLE001 - 告警写盘失败不阻塞主循环
                log(f"零终裁重派告警写盘失败（不阻塞）: {type(ex).__name__}: {str(ex)[:80]}")
    return nov


def _arb_quote_hit(atom_id):
    """厂内逐字回查：atom 存档 quote 是否为厂内证据缓存文本的连续子串（与收割方
    validate 的 `q in t` 逐字同口径）。返回 True/False；证据不可得（quote 缺档/
    arx 推导不出/缓存缺文本）返回 None=无法回查。"""
    q = _kb_atom_quote(atom_id)
    if not q:
        return None
    base = re.sub(r"-\d+$", "", atom_id)   # 剥 candidate_id 铸定尾序号 sbx-<base>-<n>
    m = _ATOM_ARX_RE.search(base)
    if not m:
        return None
    d = os.path.join(KB_EVIDENCE_CACHE, m.group(1))
    hit = False
    seen_text = False
    for name in ("abs.md", "full.md"):
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if t:
            seen_text = True
            if q in t:
                return True
    return False if seen_text else None


def _arb_refute_recheck(card_id, r):
    """refute 终裁的厂内回查门。返回 ("ok","") | ("contradict",<理由>) | ("unavailable",<理由>)。
    contradict=终裁与厂内机械事实矛盾/越册/卡未在册（确定性，不重试不落库）；
    unavailable=厂内数据暂缺（原子未入库/证据缓存缺/名册读不到→发卡面可补），走既有
    arb_attempts 重试帽轮再转人工。card_id 由调用方解析（payload.card_id 优先，回落
    rep.task_id——两者在真卡上同值；都缺=不在册）。"""
    aid = r.get("atom_id")
    sids = _arb_card_scope(card_id if isinstance(card_id, str) else None)
    if sids is None:
        return ("contradict", "卡不在发卡名册（task-seeds 无本卡 meta/atom_ids）——疑似伪造终裁，不落库")
    if aid not in sids:
        return ("contradict", "atom 不在本卡 atom_ids 名册（越册终裁），不落库")
    hit = _arb_quote_hit(aid)
    qc = r.get("quote_check")
    if hit is None:
        return ("unavailable", "厂内无法逐字回查（原子缺档/证据缓存缺/arXiv 段推导不出）")
    if hit != bool(qc):
        return ("contradict",
                f"终裁 quote_check={qc} 与厂内逐字回查矛盾（quote 回查 {'hit' if hit else 'miss'}）——伪造翻案，不落库")
    return ("ok", "")


def apply_arbitrate_refute(atom_id, ev_path):
    """一条 refute 终裁落双库。返回 (reg_state, kb_state)：两态 ∈ resolved/unresolved。
    registry：verified→arbitrate-refute；candidate→普通 reject；已 rejected=已决；
    缺件=resolved-absent（如实进日志，无从翻案也是终局事实）。
    kb：update_status→retired；已 retired/merged=已决；缺件=resolved-absent。"""
    reg = registry_arbitrate_refute(atom_id, ev_path)
    reg_state = "unresolved"
    if reg == "arbitration-refuted":
        reg_state = "resolved"
    else:
        st = registry_status_ro(atom_id)
        if reg == "no-such-atom-or-not-verified" and st == "candidate":
            ok = registry_reject([atom_id], f"kb-arbitrate 终裁 refute，依据 {ev_path}")
            reg_state = "resolved" if ok else "unresolved"
        elif st == "rejected":
            reg_state = "resolved"          # 已决（他卡先到 refute 或此前已否决）
        elif st is None:
            reg_state = "resolved-absent"   # registry 缺件：如实记，无需重试
    kb_ok = kb_retire_refuted(
        atom_id, f"kb-arbitrate 终裁 refute，依据 {os.path.basename(ev_path)}")
    if kb_ok:
        kb_state = "resolved"
    else:
        st = _kb_atom_status(atom_id)
        if st in ("retired", "merged"):
            kb_state = "resolved"           # 已决（终态）
        elif st is None:
            kb_state = "resolved-absent"    # kb 缺件：如实记，无需重试
        else:
            kb_state = "unresolved"
    return reg_state, kb_state


def handle_arb_report(st, name, rep, is_arb):
    """消费一份仲裁/蒸馏回报。返回 True=本份可计消费（终裁全落库或纯观测），False=待重试。
    2026-11-02 RT：五字段契约镜像收割方 validate（quote_check 须 JSON 布尔、rationale
    非空、agree_with∈词表——旧码只看 atom_id+final）；refute 落双库前另过厂内回查门
    _arb_refute_recheck（在册卡名册/逐字回查一致），contradict 不落库留台账、
    unavailable 走既有重试帽轮。
    2026-11-03 RT（零终裁蒸发面）：「无有效 rulings」/「结构缺件」= 终裁无从落库——
    旧码把它当「已消费」静默 return True（写进 arb_reports 防重放、不留档、不登记），
    终裁整批蒸发而对账门因「已消费」判绿（108/108 resolved_by-router）。现两类都走
    零终裁处置：留档（arbitrate/no-verdict/ 证据副本）+ 显式登记待运营者（点名受影响
    原子），再计消费（防重放；本份重试无意义——内容不会变）。"""
    pay = rep.get("payload") or {}
    if is_arb:
        raw_all = pay.get("rulings") or []
        rs = _arb_rulings_ok(raw_all)
        if not raw_all:
            # 零终裁：收割方同口径整份拒收（「payload.rulings 缺失或为空」）——终裁无从落库。
            changelog(f"仲裁回报无效（无有效 rulings，终裁无从落库），忽略终裁并零终裁登记"
                      f"（待人工重派/换卡）：`{name}`")
            ev = save_arb_nov_report(name, rep)
            register_arb_zero_verdict(st, name, "无有效 rulings（零终裁；收割方同口径整份拒收）",
                                      evidence=ev)
            return True
        if len(rs) != len(raw_all):
            # 单一语义两处镜像：收割方 validate 对任一条结构缺件整份拒收（fail-closed），
            # 消费线同口径整份不作数——坏条混在合法 refute 里搭车翻案不再可行。
            changelog(f"仲裁回报结构缺件 {len(raw_all) - len(rs)}/{len(raw_all)}（五字段口径："
                      f"quote_check 须 JSON 布尔、rationale 非空、agree_with∈b1|b2|neither，"
                      f"同收割方整份拒收待遇），忽略终裁并零终裁登记（待人工重派/换卡）：`{name}`")
            ev = save_arb_nov_report(name, rep)
            register_arb_zero_verdict(
                st, name,
                f"结构缺件 {len(raw_all) - len(rs)}/{len(raw_all)}（五字段口径；终裁未落库）",
                evidence=ev)
            return True
        ev_path = save_arb_report(name, rep)
        per, pending, blocked = [], [], []
        for r in rs:
            if r["final"] != "refute":
                continue
            aid = r["atom_id"]
            verdict, why = _arb_refute_recheck(
                pay.get("card_id") if isinstance(pay.get("card_id"), str) else rep.get("task_id"),
                r)
            if verdict == "contradict":
                # 确定性拦截（卡未在册/越册/qc 位与厂内回查矛盾）：重试无意义，
                # 不落库、计消费，逐条进台账（伪造/矛盾如实留痕）。
                blocked.append(f"{aid}:{why}")
                continue
            if verdict == "unavailable":
                # 厂内数据暂缺：按落库未全成处理（不翻转，走既有 arb_attempts 重试→
                # ≥ARBITRATE_RETRY_CAP 转人工），数据补齐后下轮自然落库。
                per.append(f"{aid}:registry=unresolved,kb=unresolved")
                pending.append(aid)
                continue
            reg_state, kb_state = apply_arbitrate_refute(aid, ev_path)
            per.append(f"{aid}:registry={reg_state},kb={kb_state}")
            if "unresolved" in (reg_state, kb_state):
                pending.append(aid)
        fin = {k: sum(1 for r in rs if r["final"] == k) for k in ARBITRATE_FINALS}
        agree = {k: sum(1 for r in rs if r.get("agree_with") == k) for k in AGREE_WITHS}
        if per:
            tail = f"；落双库明细 {'; '.join(per)}"
        elif blocked:
            tail = "；refute 终裁全被厂内回查拦截，无双库动作"
        else:
            tail = "；无 refute 终裁，无双库动作"
        if blocked:
            tail += f"；厂内回查拦截 {'; '.join(blocked)}"
        if pending:
            n = st.setdefault("arb_attempts", {}).get(name, 0) + 1
            st["arb_attempts"][name] = n
            if n >= ARBITRATE_RETRY_CAP:
                changelog(f"仲裁终裁落库 {ARBITRATE_RETRY_CAP} 轮未全成（登记待运营者，本份计消费"
                          f"不再重试）：`{name}` rulings {len(rs)}（refute {fin['refute']}）→ "
                          f"{'; '.join(per)}，依据 {os.path.basename(ev_path)}")
                return True
            log(f"仲裁终裁落库未全成（第 {n}/{ARBITRATE_RETRY_CAP} 轮，下轮重试）："
                f"`{name}` → {'; '.join(per)}")
            return False
        changelog(f"仲裁终裁入账：`{name}` rulings {len(rs)}（uphold {fin['uphold']}/refute "
                  f"{fin['refute']}/unverifiable {fin['unverifiable']}；agree_with b1={agree['b1']}"
                  f"/b2={agree['b2']}/neither={agree['neither']}）{tail}，"
                  f"依据 {os.path.basename(ev_path)}")
        return True
    fs = [f for f in (pay.get("findings") or [])
          if isinstance(f, dict) and f.get("final") in DISTILL_FINALS]
    if not fs:
        # 零复核（与仲裁零终裁同构）：收割方同口径整份拒收（「payload.findings 缺失或为空」）
        # ——复核结论无从落库，不得静默当「已消费」蒸发：留档 + 显式登记待运营者。
        changelog(f"蒸馏回报无效（无有效 findings），忽略复核并零终裁登记"
                  f"（待人工重派/换卡）：`{name}`")
        ev = save_arb_nov_report(name, rep)
        register_arb_zero_verdict(st, name, "无有效 findings（零复核；收割方同口径整份拒收）",
                                  evidence=ev)
        return True
    ev_path = save_arb_report(name, rep)
    fin = {k: sum(1 for f in fs if f["final"] == k) for k in DISTILL_FINALS}
    flag = "；info_loss/wrong_winner>0 = 合并蒸馏规则回归信号，登记待运营者复盘" \
        if (fin["info_loss"] or fin["wrong_winner"]) else ""
    changelog(f"蒸馏复核聚合（纯观测，不改原子状态）：`{name}` findings {len(fs)}"
              f"（no_loss {fin['no_loss']}/info_loss {fin['info_loss']}/wrong_winner "
              f"{fin['wrong_winner']}/unverifiable {fin['unverifiable']}）{flag}，"
              f"依据 {os.path.basename(ev_path)}")
    return True


def _task_ts_of(name):
    """回报文件名 → (task 基名, 13 位尾戳 ms)；解析不出返回 (None, 0)。
    口径与 sandbox-harvester.py 主循环的同任务去重 _ts_of 逐字同形（单一语义两处镜像，
    注释互指）。"""
    import re as _re
    m = _re.match(r"^(.*)-(\d{13})\.json$", name)
    return (m.group(1), int(m.group(2))) if m else (None, 0)


def poll_arbitrate_reports(st):
    """扫 gov reports/（兼看本地 raw/）消费 kb-arbitrate / kb-distill 回报。

    修复整类拒收+零消费者断链（历史 54 份积压回报仍在 gov reports/，本消费线上线首轮
    即回灌）。防重放 st['arb_reports']；拉取失败不标记下轮再试；单份坏回报不阻塞其余。
    任务级去重与收割方同款（2026-11-02 token 一次性批：同任务 <15min 相邻回报必为
    同一 claim_token 复用，只认最早一笔——消费面镜像该裁决，防同批双份都进终裁线）。
    """
    consumed = st.setdefault("arb_reports", [])
    # 已消费名的尾戳按任务种子化（与收割方从 .harvested 种子化同构）
    last_rep = {}
    for n in consumed:
        t, ts = _task_ts_of(n)
        if t and ts > last_rep.get(t, 0):
            last_rep[t] = ts
    paths = sorted(gov_report_paths() + sorted(glob.glob(RAW_DIR + "/*.json")),
                   key=lambda p: (_task_ts_of(os.path.basename(p))[1],
                                  os.path.basename(p)))
    seen = set()
    for p in paths:
        name = os.path.basename(p)
        if name in seen or name in consumed:
            continue
        seen.add(name)
        base, ts = _task_ts_of(name)
        if base and last_rep.get(base, 0) > 0 and abs(ts - last_rep[base]) < 900 * 1000:
            log(f"仲裁/蒸馏消费跳过（同任务重复回报，距已消费上一笔 "
                f"{abs(ts - last_rep[base]) / 1000.0:.0f}s <15min，只认最早一笔）: {name}")
            consumed.append(name)
            # 重复回报去重跳过 ≠ 零终裁：单独记一笔（回流腿据此不把本份误判成
            # 「终裁未落库」——它本就无需再处理，最早一笔已作数）
            st.setdefault("arb_dedup_skipped", []).append(name)
            continue
        tid = name[:-5] if name.endswith(".json") else name
        is_arb = tid.startswith("kb-arbitrate")
        if not (is_arb or tid.startswith("kb-distill")):
            continue
        rep = fetch_report(p)
        if rep is None:
            continue  # 拉取失败不标记，下轮再试
        try:
            done = handle_arb_report(st, name, rep, is_arb)
        except Exception as e:  # noqa: BLE001 - 一份坏回报不许带崩消费线（与其余域同款）
            log(f"仲裁/蒸馏消费异常（本份下轮重试）: `{name}` → {type(e).__name__}: {e}")
            continue
        if done:
            consumed.append(name)
            st.get("arb_attempts", {}).pop(name, None)
            if base and ts > last_rep.get(base, 0):
                last_rep[base] = ts


# ---- ⑤ RT-E80 机制④：kb-arbitrate/kb-distill 拒收回流（拒收的终裁/复核不得蒸发） ----
# HARVEST-LOG 拒收行：| kb-arbitrate-<...>[-<ts>].json | rejected | <why> | - |
#                     | kb-distill-<...>[-<ts>].json   | rejected | <why> | - |
# 前缀判定与 poll_arbitrate_reports 的 is_arb/蒸馏分域同口径（startswith kb-arbitrate /
# kb-distill）；卡名与 kb-verify（VERIFY_REJECT_RE）、kb-atoms（poll_harvest r2 正则）
# 前缀互斥——一行至多落一个域的回流正则（三侧接线清单门 test-cardtype-three-side-wiring
# 钉死互斥）。why 吃到行尾再剥末列：拒收文案附的合法 schema 一行含竖线（裁决词表），
# 同 VERIFY_REJECT_RE 的既有口径。
# （2026-11-02 前：这两类拒收行不落任何回流正则，HARVEST-LOG 实存 55 行全 rejected
# 零处置——「仲裁/蒸馏终裁被拒=终裁无人再读」的蒸发面。）
ARB_REJECT_RE = re.compile(
    r"\|\s*(?P<card>(?:kb-arbitrate|kb-distill)-[A-Za-z0-9._\-]+?)\.json"
    r"\s*\|\s*rejected\s*\|\s*(?P<why>.*)$")


def arb_consumed_names(st):
    """本消费线已见过的仲裁/蒸馏回报名（state 防重放键 ∪ 本地留档目录），用于把
    历史拒收行认领为 resolved-by-router（留档=落库依据在盘，可直接对账）。"""
    names = set(st.get("arb_reports") or [])
    try:
        names |= {n for n in os.listdir(ARB_DIR)
                  if n.endswith(".json")} if os.path.isdir(ARB_DIR) else set()
    except OSError:
        pass
    return names


def register_arb_reject(st, card, why):
    """被收割方结构性拒收的仲裁/蒸馏回报 → 处置动作。返回处置状态字符串。

    仲裁/蒸馏卡是一次性复核卡（产卡需分歧上下文/双分支报告，无法像 kb-verify 那样
    按 meta.json 机械重发新版），故回流语义=显式登记+变更日志点名（与 resend_verify_card
    的「缺候选清单登记待运营者」同款），等人工重派或新仲裁卡覆盖。终裁内容未经本消费线
    入账前，绝不静默。"""
    changelog(f"仲裁/蒸馏回报拒收登记（终裁/复核未入账，待人工重派）：`{card}`：{why}")
    return "registered"


def poll_arb_rejects(st, lines):
    """扫 HARVEST-LOG 的 kb-arbitrate/kb-distill 拒收行 → 逐行认领（st['arb_rejects'] 防重放）。

    认领语义（RT-E80 修复对账「55 行旧式拒收无回填标记」的对偶腿）：
      · 该回报已被本消费线消费**且终裁确已落库**（ARB_DIR 顶层留档在册=落库依据）→
        记 resolved-by-router（状态内回填标记）；不写变更日志（防历史积压上线首轮刷屏）。
      · 该回报已被消费但**终裁未落库**（无留档依据：零终裁/结构缺件/零复核）→ 不得记
        「已解决」（2026-11-03 RT 修复·零终裁蒸发面：旧口径一律记 resolved-by-router，
        零终裁整批蒸发而对账门 108/108 全绿）。改记 no-verdict-registered 并落零终裁
        台账（点名受影响原子 + 取证留档）——有主但**不是**已解决。
      · 未被消费 → 登记待运营者（changelog 点名），status=registered。
    一张坏回报不许带崩整条回流线（与其余域同款）。
    """
    seen = st.setdefault("arb_rejects", {})
    rows = []
    for line in lines:
        m = ARB_REJECT_RE.search(line)
        if not m:
            continue
        card = m.group("card")
        if card in seen:
            # 自愈腿（2026-11-03 RT 修复·零终裁蒸发面）：旧口径把「已消费」一律记
            # resolved-by-router ⇒ 零终裁回报被误判成「已解决」（终裁整批蒸发而对账门
            # 全绿）。已记 resolved-by-router 但**无终裁留档凭据**的，改判重估（落下面
            # 的零终裁分支）：判据升级为「终裁确已落库」才算已解决。
            v = seen[card]
            if not (isinstance(v, dict) and v.get("status") == "resolved-by-router"
                    and not (arb_verdict_evidence(card)
                             or arb_verdict_evidence(card + ".json"))):
                continue
        why = VERIFY_TAIL_RE.sub("", m.group("why")).strip()[:VERIFY_WHY_MAX]
        rows.append((card, why))
    if not rows:
        return
    consumed = arb_consumed_names(st)
    dedup = set(st.get("arb_dedup_skipped") or [])   # 同任务重复回报（只认最早一笔）
    # 零终裁候选：已被消费但**无终裁留档依据**（≠重复回报去重跳过）→ 取证留档（批量，
    # 一次 ssh；失败不阻塞登记）
    cand = []
    for card, _ in rows:
        if card in dedup or (card + ".json") in dedup:
            continue
        nm = card + ".json"
        if nm in nov_names(st):
            # 已登记但证据副本缺失 → 补取证（取证失败时的重试腿）
            if not ((st.get("arb_zero_verdict") or {}).get(nm) or {}).get("evidence"):
                cand.append(nm)
            continue
        if (card in consumed or nm in consumed) and \
                not (arb_verdict_evidence(card) or arb_verdict_evidence(nm)):
            cand.append(nm)
    ev_map = {}
    if cand:
        try:
            ev_map = arb_zero_verdict_evidence(st, cand)
        except Exception as e:  # noqa: BLE001 - 取证失败不阻塞登记
            log(f"零终裁取证异常（不阻塞登记）: {type(e).__name__}: {str(e)[:80]}")
    for card, why in rows:
        nov = nov_names(st)
        # 零终裁台账已有登记（消费线侧或上一轮回流腿登记）→ 有主，但不算「已解决」
        if card in nov or (card + ".json") in nov:
            seen[card] = {"why": why, "status": "no-verdict-registered"}
            continue
        if card in dedup or (card + ".json") in dedup:
            # 同任务重复回报（15min 内只认最早一笔）：本份本就无需再处理，非零终裁
            seen[card] = {"why": why, "status": "dedup-skipped"}
            continue
        if card in consumed or (card + ".json") in consumed:
            if arb_verdict_evidence(card) or arb_verdict_evidence(card + ".json"):
                seen[card] = {"why": why, "status": "resolved-by-router"}
                continue
            # 消费过但终裁未落库（零终裁）——显式登记待运营者（存量自愈腿：旧口径把这批
            # 记成 resolved-by-router 而终裁整批蒸发）。取证留档失败也不阻塞登记。
            try:
                register_arb_zero_verdict(
                    st, card + ".json", why or "收割方拒收（终裁未落库）",
                    evidence=ev_map.get(card + ".json", ""))
            except Exception as e:  # noqa: BLE001 - 一张坏卡不许带崩整条回流线
                log(f"零终裁登记异常（不阻塞后续卡）: `{card}` → {type(e).__name__}: {e}")
            seen[card] = {"why": why, "status": "no-verdict-registered"}
            continue
        seen[card] = {"why": why, "status": "pending"}
        try:
            seen[card]["status"] = register_arb_reject(st, card, why)
        except Exception as e:  # noqa: BLE001 - 一张坏卡不许带崩整条回流线
            seen[card]["status"] = "error"
            log(f"仲裁/蒸馏拒收登记异常（不阻塞后续卡）: `{card}` → {type(e).__name__}: {e}")


def rearm_skipped_newer(st):
    """一次性摘除 verify_reflows 里被旧口径误判冻结的 skipped_newer 条目（返回摘除数）。

    2026-11-02 RT 修复（拒发残目录误判在飞）存量腿：「在飞」判定此前只按本地目录名，
    被质量闸拒发而残留 task-seeds/ 的卡目录把真卡的重发判成 skipped_newer 终态，而
    poll_verify_rejects 的防重放（`if card_id in seen: continue`）会把该错判永久冻结
    （实测 88 条，点名 kb-verify-kb-atoms-rpt-2610.36499-1r1/1r2，其 2r1..4r2 残目录
    gov 侧不存在）。摘除后 HARVEST-LOG 拒收行仍在，下一轮 poll_verify_rejects 按
    「真上板才在飞」新口径重评估；重发上限 verify_resends 照旧累计（每血线 ≤
    VERIFY_RESEND_CAP），总量有界。旗标 verify_reflows_rearmed 落状态文件，防逐轮重武装。
    """
    stuck = [k for k, v in (st.get("verify_reflows") or {}).items()
             if isinstance(v, dict) and v.get("status") == "skipped_newer"]
    for k in stuck:
        del st["verify_reflows"][k]
    return len(stuck)


# ---------- ⑥ Trigger 收件箱消费腿（PoC-D，af.trigger.v1；MES complete 腿不在此批） ----------
# 契约/注册表正本：af 仓 poc/poc-super-agent/{contracts,registry}/；运行位读
# af-state/triggers/registry.json。本腿只做：读已验消息→按注册表映射套件→
# 确定性 order_id 派单记录（**不执行门套件**——webhook 只进收件箱，执行是 F 门单
# 职责）。派单记录落 af-state/triggers/dispatch/，与 anolis 订单面（af-state/orders/）
# 分居：本腿首版不直投 af-order CLI（那是 MES complete→裁决单腿/PoC-C 之后的合流面）。
TRIGGERS_HOME = os.environ.get("AF_TRIGGER_HOME", WS + "/af-state/triggers")
TRIGGER_REGISTRY_F = TRIGGERS_HOME + "/registry.json"
TRIGGER_INBOX_D = TRIGGERS_HOME + "/inbox"
TRIGGER_CONSUMED_F = TRIGGERS_HOME + "/consumed.jsonl"   # 读侧游标（T6.3 一行一事件）
TRIGGER_DISPATCH_D = TRIGGERS_HOME + "/dispatch"
TRIGGER_ANDON_DIR = os.environ.get("AF_TRIGGER_ANDON_DIR", WS + "/状态观测")
TRIGGER_ALARMS_F = os.environ.get("AF_TRIGGER_ALARMS_F", WS + "/状态观测/alarms.log")
TRIGGER_ANDON_F = TRIGGER_ANDON_DIR + "/trigger-inbox-liveness.json"
TRIGGER_ANDON_REFRESH_S = 6 * 3600     # 安灯摘要行刷新节奏（防刷屏；跃迁必写）
# ★ 2026-11-05 发布面接线批 ①P4：形态判据文件（**写入方=tools/factory-keepalive.py
#   判据行④**；本腿只读，不写、不重判）。它答的是「收件箱进程在不在 + 源头断没断供」
#   ——即形态A（进程不在，既有码 trigger-inbox-down）与形态B（进程在但断供，新码
#   trigger-inbox-source-silent）的分家判据。本腿此前只按「投递静默时长」判 ⇒
#   进程不在时照样自述 green（投递面新鲜＝看着像活）——这正是「路由侧那盏灯不知
#   进程态」的失败形态。**不新建探针进程、不新建监听**，只读既有判据文件。
TRIGGER_SOURCE_SILENT_F = os.environ.get(
    "AF_TRIGGER_SILENT_F", WS + "/状态观测/trigger-inbox-source-silent.json")
# 形态判据文件陈旧阈（3600s，与安灯判据文件同值）：keepalive 轮询周期 30s
# （tools/factory-keepalive.py:283）⇒ 1h 未重写＝判据行④没在跑 ⇒ 进程态不可证
# （读到旧文件≠活——268h 静默前科的失败形态）。
TRIGGER_SOURCE_SILENT_STALE_S = 3600
TRIGGER_CONTRACT = "af.trigger.v1"


def _trigger_registry():
    """只读触发层注册表（映射表/安灯阈值是数据不是代码）。读不到返回 None——
    消费腿整腿 no-op（首日志限频：注册表未装=腿未开通，不该每 60s 刷屏）。"""
    try:
        with open(TRIGGER_REGISTRY_F, encoding="utf-8") as f:
            reg = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log(f"触发层注册表损坏（{TRIGGER_REGISTRY_F}: {type(e).__name__}: {str(e)[:80]}），"
            f"本轮消费腿跳过（fail-loud 不猜）")
        return None
    if reg.get("schema") != "af.trigger.registry.v1":
        log(f"触发层注册表 schema 不识别: {str(reg.get('schema'))[:60]}，本轮消费腿跳过")
        return None
    return reg


def _trigger_recipe_digest(reg, raw_text):
    """order_id 确定性生成的配方指纹：优先注册表自带 recipe_digest（安装时算定），
    缺席时对注册表原文字节现算（同文件同值，仍确定）。"""
    rd = reg.get("recipe_digest")
    if isinstance(rd, str) and len(rd) == 64:
        return rd
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _suite_for_event(reg, repo, event_type, action):
    """按注册表 repo_suites 把事件映射到门套件（push→F1、pull_request
    opened/synchronize→F2 是注册表数据，不是代码）。多条命中取 glob 最窄者；
    pull_request 的 action 不在 actions 列表=收下不派单（返回 None，记 skip）。"""
    import fnmatch
    hits = []
    for row in reg.get("repo_suites", []):
        pat = row.get("repo_glob", "**")
        if fnmatch.fnmatch(repo, pat):
            hits.append((len(pat), row))
    if not hits:
        return None
    row = max(hits, key=lambda t: t[0])[1]          # 最窄 glob 优先
    m = (row.get("map") or {}).get(event_type)
    if not isinstance(m, dict):
        return None                                  # 该事件类型无映射
    if event_type == "pull_request":
        acts = m.get("actions") or []
        if action not in acts:
            return None                              # 白名单管进门，actions 管派单
    s = m.get("suite")
    return s if isinstance(s, str) and s else None


def _trigger_order_id(repo, suite, subject, recipe_digest):
    """order_id 确定性生成 = hash(repo+suite+subject+recipe_digest) 前 16 hex。
    同内容必然同单号——重放/重复投递在派单面天然幂等（状态文件之外的第三道对账锚）。"""
    h = hashlib.sha256("|".join([repo, suite, subject, recipe_digest]).encode("utf-8")).hexdigest()
    return f"{suite}-{repo.replace('/', '-')}-{h[:16]}"


def _trigger_verify_envelope(env, source, delivery_id, reg):
    """只读已验消息·信封核对（2026-11-03 修复批修死高危2：篡改派单）。
    唯一可信载荷=body_b64（payload_sha256 自证）；派单决策输入
    repo/event/delivery/subject/dedup_key **一律从重解析 body_b64 取**，
    不消费信封冗余 parsed body（env['body'] 可被篡改而 hash 不破——信封
    非自证）。信封冗余字段（event_type/delivery_id/dedup_key/thread_key/
    body）逐项与重解析核对，任一不符=拒读（返回原因，调用方记拒读痕迹）。
    推导公式=trigger-inbox envelope_for 的镜像（同仓两处，改公式须两处同步）。
    返回 (facts, []) 或 (None, reasons)。"""
    import base64
    reasons = []
    if env.get("contract") != TRIGGER_CONTRACT:
        reasons.append(f"contract 不符: {str(env.get('contract'))[:40]!r}")
    b64 = env.get("body_b64")
    raw = None
    if not isinstance(b64, str) or not b64:
        reasons.append("body_b64 缺失/非字符串")
    else:
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception as e:
            reasons.append(f"body_b64 非法 base64: {type(e).__name__}")
    parsed = None
    if raw is not None:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as e:
            reasons.append(f"body_b64 非 UTF-8 JSON: {type(e).__name__}")
        if parsed is not None and not isinstance(parsed, dict):
            reasons.append("body_b64 顶层非 JSON 对象")
            parsed = None
        if parsed is not None and env.get("payload_sha256") != hashlib.sha256(raw).hexdigest():
            reasons.append("payload_sha256 对 body_b64 复算不符（篡改痕迹）")
    if parsed is None or reasons:
        return None, reasons
    # ---- 从已验 body_b64 重解析推导（envelope_for 同公式） ----
    repo_obj = parsed.get("repository") or {}
    repo = str(repo_obj.get("full_name") or repo_obj.get("name") or "unknown-repo")
    etype = parsed.get("event")
    after = str(parsed.get("after") or parsed.get("sha") or "")
    pr = parsed.get("pull_request") or {}
    head = str((pr.get("head") or {}).get("sha") or parsed.get("head_sha") or "")
    if etype == "push":
        num = ""
        subject = after or delivery_id
        dedup_key = f"push:{repo}:{after}"
    elif etype == "pull_request":
        num = pr.get("number") or parsed.get("number") or "?"
        subject = head or delivery_id
        dedup_key = f"pull_request:{repo}:{num}:{head}"
    else:
        num = ""
        subject = head or delivery_id
        dedup_key = f"{etype}:{repo}"
    # ---- 信封冗余字段逐项核对（被篡=拒读，不猜不改） ----
    if not isinstance(etype, str) or not etype:
        reasons.append("重解析 event 缺失/非字符串")
    elif env.get("event_type") != etype:
        reasons.append(f"event_type 信封={env.get('event_type')!r} ≠ 重解析={etype!r}")
    if env.get("delivery_id") != delivery_id:
        reasons.append(f"delivery_id 信封={env.get('delivery_id')!r} ≠ 文件名={delivery_id!r}")
    v_del = parsed.get("delivery_id")
    if isinstance(v_del, str) and v_del and v_del != delivery_id:
        reasons.append(f"delivery_id body={v_del!r} ≠ 文件名={delivery_id!r}")
    if env.get("dedup_key") != dedup_key:
        reasons.append(f"dedup_key 信封={str(env.get('dedup_key'))[:60]!r} ≠ 重推导={dedup_key!r}")
    if "body" in env and env.get("body") != parsed:
        reasons.append("冗余 parsed body 与 body_b64 重解析不一致（篡改痕迹；"
                       "本腿不消费 parsed body，仅核对）")
    if etype in ("push", "pull_request"):
        domain = "unknown"
        for s in reg.get("sources", []):
            if s.get("name") == source:
                domain = s.get("domain") or "unknown"
                break
        tk = (f"{domain}:{repo}@{after[:12]}" if etype == "push"
              else f"{domain}:{repo}#{num}")
        if env.get("thread_key") != tk:
            reasons.append(f"thread_key 信封={str(env.get('thread_key'))[:60]!r} ≠ 重推导={tk!r}")
    if reasons:
        return None, reasons
    return {"repo": repo, "etype": etype, "action": str(parsed.get("action") or ""),
            "subject": subject, "dedup_key": dedup_key}, []


def _trigger_reject(st, dk, path, reason):
    """拒读登记（不消费不派单；原因进状态面 trigger_leg.rejected，一次一条）。"""
    leg = st.setdefault("trigger_leg", {})
    rejected = leg.setdefault("rejected", {})
    if dk not in rejected:
        rejected[dk] = {"ts": time.time(), "reason": str(reason)[:300]}
        log(f"拒读未验/不符消息（不消费不派单）: {path}: {str(reason)[:200]}")


def _trigger_consumed_ledger():
    """读侧游标真源（consumed.jsonl，一行一事件）。返回 (delivery_ids, dedup_keys,
    order_ids)。损坏行跳过并记日志（追加型日志，坏行不阻断整腿）。"""
    dids, dkeys, oids = set(), set(), set()
    try:
        with open(TRIGGER_CONSUMED_F, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    j = json.loads(ln)
                except Exception:
                    log(f"consumed.jsonl 坏行跳过: {ln[:80]}")
                    continue
                if j.get("delivery_id"):
                    dids.add(f"{j.get('source')}/{j['delivery_id']}")
                if j.get("dedup_key"):
                    dkeys.add(j["dedup_key"])
                if j.get("order_id"):
                    oids.add(j["order_id"])
    except FileNotFoundError:
        pass  # 首轮无游标属正常起步
    except OSError as e:
        log(f"consumed.jsonl 读失败 {type(e).__name__}: {str(e)[:80]}（按空游标起步）")
    return dids, dkeys, oids


def _trigger_append_consumed(rec):
    """游标追加（一行一事件）。"""
    with open(TRIGGER_CONSUMED_F, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _trigger_source_silent_state():
    """读 keepalive 判据行④的形态判据文件（**只读**），返回收件箱**进程态**视图。

    为什么路由侧要读它（本腿只读、不重判、不改判据）：
      · 本腿的安灯此前只按「投递静默时长」判 ⇒ 收件箱**进程不在**时它仍自述 green
        （投递面新鲜＝看着像活）——「路由侧那盏灯不知进程态」的失败形态；
      · 形态A/B 的分家判据（进程在不在 / 源头断没断供）本来就在 keepalive 侧，
        本腿**只读既有判据文件**即可知道，不新建探针进程、不新建监听。

    返回 dict：process_alive(True/False/None) / process_state(alive|down|unknown) /
    source_silent_status / source_silent_code / process_state_age_s /
    process_state_stale。
    ★ fail-closed：读不到 / 坏 JSON / 陈旧 ⇒ process_alive=None、process_state=unknown
      （**不把「读不到」当成「进程在」**）。
    """
    out = {"process_alive": None, "process_state": "unknown",
           "source_silent_status": None, "source_silent_code": None,
           "process_state_age_s": None, "process_state_stale": False}
    try:
        stt = os.stat(TRIGGER_SOURCE_SILENT_F)
    except OSError:
        return out
    out["process_state_age_s"] = max(0, int(time.time() - stt.st_mtime))
    try:
        with open(TRIGGER_SOURCE_SILENT_F, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return out
    if not isinstance(doc, dict):
        return out
    pa = doc.get("process_alive")
    if isinstance(pa, bool):
        out["process_alive"] = pa
        out["process_state"] = "alive" if pa else "down"
    ss = doc.get("status")
    if isinstance(ss, str):
        out["source_silent_status"] = ss
    sc = doc.get("alarm_code")
    if isinstance(sc, str):
        out["source_silent_code"] = sc
    # 陈旧即失活：判据行④没在跑 ⇒ 文件不再被重写 ⇒ 文件自述的进程态作废
    if out["process_state_age_s"] > TRIGGER_SOURCE_SILENT_STALE_S:
        out["process_state_stale"] = True
        out["process_state"] = "unknown"
        out["process_alive"] = None
    return out


def _trigger_liveness_andon(reg, st):
    """收件箱活性安灯（PoC-D 任务5；复用机制11 状态面）。
    治『建成没事件可路由』——事件流曾静默 267h/273.9h（obs-patrol obs-feed-silent 前科）。
    判据：收件箱最新一投递距今超过注册表 liveness.inbox_silent_after_min ⇒ amber。
    起算=本腿首跑时刻（收件箱自建成就没来过事件也算静默，从建成起算，不冤枉刚部署）。
    落面：①状态观测/trigger-inbox-liveness.json 判据文件（每轮重写=报活心跳，
    同 obs-patrol.json 形态）；②状态观测/alarms.log 摘要行（跃迁必写+每 6h 刷新，
    同 af-execline-idle 节奏）。安灯随主循环评估=STOP 熔断在位时同样停报（全腿一致）。
    ★ 2026-11-05 发布面接线批 ①P4：**进程态感知**（只改判定，**启动/调度逻辑未动**）——
      增读 keepalive 判据行④ 的形态判据文件（状态观测/trigger-inbox-source-silent.json，
      只读；不新建探针进程、不新建监听），新增字段 process_alive / process_state /
      lamp_state / lamp_alarm_code / process_note / source_silent_status /
      source_silent_code / process_state_age_s / process_state_stale；
      **既有键 status/alarm_code/message 的口径（投递活性）与取值域一律不动**
      （形态A/B 的分码落在新增键上：形态A=既有码 trigger-inbox-down、
      形态B=新码 trigger-inbox-source-silent）。"""
    import glob as _glob
    from datetime import datetime, timezone
    leg = st.setdefault("trigger_leg", {})
    if not leg.get("started_at"):
        leg["started_at"] = time.time()
    newest = 0.0
    for p in _glob.glob(os.path.join(TRIGGER_INBOX_D, "*", "*.json")):
        try:
            newest = max(newest, os.path.getmtime(p))
        except OSError:
            pass
    since = max(newest, leg["started_at"])
    silent_s = time.time() - since
    lv = reg.get("liveness") or {}
    thr_min = lv.get("inbox_silent_after_min")
    if thr_min is None:                    # 缺省回落 240（显式 None 判——0 是合法阈值）
        thr_min = 240
    thr_s = float(thr_min) * 60
    status = "amber" if silent_s > thr_s else "green"
    if status == "amber":
        code = "trigger-inbox-silent"
        msg = (f"Trigger 收件箱静默 {silent_s / 3600:.1f}h（>阈 {thr_min}min）——"
               f"Fast Path 断供：无事件可路由；恢复=事件源重投/检查 webhook 出口")
    else:
        code, msg = "trigger-inbox-live", (f"收件箱活性正常（最新投递 {silent_s / 60:.0f}min 前，"
                                           f"阈 {thr_min}min）")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # ★ 2026-11-05 ①P4：路由侧那盏灯**知道收件箱进程态**（读既有形态判据文件）。
    #   既有键 status/alarm_code 的口径（投递活性）**一律不动**；进程感知的裁决落在
    #   **新增键** lamp_state / lamp_alarm_code 上（形态A=既有码 trigger-inbox-down、
    #   形态B=新码 trigger-inbox-source-silent，两码分家、互不覆盖）。
    ps = _trigger_source_silent_state()
    lamp_state, lamp_code = status, code
    if ps["process_state"] == "down":
        lamp_state = "down"
        lamp_code = "trigger-inbox-down"          # 形态A（既有码；与形态B 新码分家）
    elif ps["process_state"] == "unknown":
        lamp_state = "unknown"                    # 进程态不可证 ⇒ 不当成活
        lamp_code = None
    elif ps["source_silent_code"] == "trigger-inbox-source-silent":
        lamp_state = "amber"
        lamp_code = "trigger-inbox-source-silent"  # 形态B（keepalive 侧的新码）
    if ps["process_state"] == "down":
        pnote = (f"收件箱进程不在（形态A；形态码 {lamp_code}；"
                 f"keepalive 判据行④ 自述 process_alive=false）")
    elif ps["process_state"] == "alive":
        pnote = (f"收件箱进程在（形态B 口径；源头断供判据由 keepalive 判据行④ 持有："
                 f"status={ps['source_silent_status']} code={ps['source_silent_code']}）")
    else:
        pnote = ("收件箱进程态不可证（形态判据文件读不到/陈旧）——不猜活")
    snap = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ts_epoch": int(time.time()),
            "tool": "event-router/trigger-leg", "status": status,
            "message": msg, "alarm_code": code,
            "newest_delivery_age_s": int(silent_s), "threshold_min": thr_min,
            "inbox_dir": TRIGGER_INBOX_D, "since_epoch": int(since),
            # ★ ①P4 新增字段（既有键语义/名字不动）：
            "process_alive": ps["process_alive"],
            "process_state": ps["process_state"],
            "lamp_state": lamp_state,
            "lamp_alarm_code": lamp_code,
            "process_note": pnote,
            "source_silent_status": ps["source_silent_status"],
            "source_silent_code": ps["source_silent_code"],
            "process_state_age_s": ps["process_state_age_s"],
            "process_state_stale": ps["process_state_stale"]}
    if not DRY:
        try:
            os.makedirs(TRIGGER_ANDON_DIR, exist_ok=True)
            tmp = TRIGGER_ANDON_F + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
            os.replace(tmp, TRIGGER_ANDON_F)
        except OSError as e:
            log(f"安灯判据文件写失败 {type(e).__name__}: {str(e)[:80]}（不阻塞主循环）")
    # 摘要行：跃迁必写；持续 amber 每 6h 刷新一次
    prev = leg.get("alarm_state")
    due_refresh = time.time() - (leg.get("last_alarm_ts") or 0) > TRIGGER_ANDON_REFRESH_S
    if not DRY and status == "amber" and (prev != "amber" or due_refresh):
        try:
            with open(TRIGGER_ALARMS_F, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "level": "amber", "code": code, "message": msg,
                                    "since": datetime.fromtimestamp(since).strftime(
                                        "%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
            leg["last_alarm_ts"] = time.time()
        except OSError as e:
            log(f"安灯摘要行写失败 {type(e).__name__}: {str(e)[:80]}（不阻塞主循环）")
    leg["alarm_state"] = status
    leg["last_liveness"] = now_iso
    return snap


def poll_triggers(st):
    """Trigger 收件箱消费腿（PoC-D）：只读**已验消息**（trigger-inbox 落盘时已
    HMAC 验签+白名单；本腿再核信封完整性=contract 对+payload_sha256 对 body_b64
    复算，且**派单决策输入一律从已验 body_b64 重解析取**、信封冗余字段逐项核对
    ——防收件箱文件被篡改；2026-11-03 修复批修死『篡改 parsed body 而保留合法
    body_b64+hash 可按篡改字段派单』高危2），按注册表映射套件，产派单记录。
    **不执行门套件**。
    防重放三道：consumed.jsonl 游标（真源）/dedup_key（业务内容）/order_id（确定性
    单号）。异常不带崩主循环（外层还有 try，这里内层再兜一层=与全线护栏一致）。"""
    from datetime import datetime, timezone
    try:
        raw_text = None
        with open(TRIGGER_REGISTRY_F, encoding="utf-8") as f:
            raw_text = f.read()
        reg = json.loads(raw_text)
        if reg.get("schema") != "af.trigger.registry.v1":
            raise ValueError(f"schema 不识别: {str(reg.get('schema'))[:60]}")
    except FileNotFoundError:
        leg = st.setdefault("trigger_leg", {})
        now = time.time()
        if now - (leg.get("last_no_reg_log") or 0) > 3600:   # 限频：1 行/h
            leg["last_no_reg_log"] = now
            log(f"触发层注册表不在位（{TRIGGER_REGISTRY_F}）——消费腿 no-op"
                f"（腿未开通；安装=poc-super-agent/registry/ 正本安放运行位）")
        st.setdefault("trigger_consumed", {})
        st.setdefault("trigger_dedup", {})
        return
    except Exception as e:
        log(f"触发层注册表读失败 {type(e).__name__}: {str(e)[:80]}，本轮消费腿跳过")
        return
    # 安灯评估（收件箱空也要报活——先于消费，静默与有货两态都评估）
    try:
        _trigger_liveness_andon(reg, st)
    except Exception as e:  # noqa: BLE001 - 安灯异常不带崩消费腿
        log(f"触发层安灯评估异常（不阻塞消费腿）: {type(e).__name__}: {str(e)[:120]}")
    import glob as _glob
    dids, dkeys, oids = _trigger_consumed_ledger()
    st.setdefault("trigger_consumed", {})
    st.setdefault("trigger_dedup", {})
    recipe_digest = _trigger_recipe_digest(reg, raw_text)
    n_new = n_skip = 0
    for path in sorted(_glob.glob(os.path.join(TRIGGER_INBOX_D, "*", "*.json"))):
        source = os.path.basename(os.path.dirname(path))
        delivery_id = os.path.splitext(os.path.basename(path))[0]
        dk = f"{source}/{delivery_id}"
        if dk in dids or delivery_id in (st["trigger_consumed"] or {}):
            continue
        # 只读已验消息（高危2 修复批）：信封契约头 + payload_sha256 对 body_b64
        # 复算，且派单决策输入（repo/event/delivery/subject/dedup_key）一律从
        # **已验 body_b64 重解析**取——不消费信封冗余 parsed body；信封冗余字段
        # 逐项与重解析核对，任一不符=拒读记原因（防收件箱文件被篡改后按篡改
        # 字段派单：改 parsed body/信封字段而保留合法 body_b64+hash 旧版可过）。
        try:
            env = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            log(f"触发信封不可读（跳过）: {path}: {type(e).__name__}: {str(e)[:80]}")
            continue
        facts, mismatches = _trigger_verify_envelope(env, source, delivery_id, reg)
        if facts is None:
            _trigger_reject(st, dk, path, "; ".join(mismatches) or "未知原因")
            continue
        etype, repo, action = facts["etype"], facts["repo"], facts["action"]
        subject, dedup_key = facts["subject"], facts["dedup_key"]
        suite = _suite_for_event(reg, repo, etype, action)
        rec_common = {"delivery_id": delivery_id, "source": source, "event_type": etype,
                      "thread_key": env.get("thread_key"), "dedup_key": dedup_key,
                      "repo": repo, "consumed_at": datetime.now(timezone.utc).isoformat(
                          timespec="seconds")}
        if suite is None:
            # 收件箱收下（202）但注册表无映射（如 pull_request closed）：记 skip 游标行
            n_skip += 1
            _trigger_append_consumed({**rec_common, "order_id": None, "result": "skip-no-mapping"})
            st["trigger_consumed"][delivery_id] = "skip"
            changelog(f"Trigger 消费：{etype} {repo}"
                      f"{'/' + action if action else ''} 无套件映射（注册表），收下不派单")
            continue
        if dedup_key in dkeys or dedup_key in (st["trigger_dedup"] or {}):
            n_skip += 1
            _trigger_append_consumed({**rec_common, "order_id": None, "result": "skip-dedup"})
            st["trigger_consumed"][delivery_id] = "dedup"
            continue                                    # 同业务内容换 delivery 重放：不重复派单
        order_id = _trigger_order_id(repo, suite, subject, recipe_digest)
        if order_id in oids:
            n_skip += 1
            _trigger_append_consumed({**rec_common, "order_id": order_id, "result": "skip-order-id"})
            st["trigger_consumed"][delivery_id] = "order-id-dup"
            continue
        # 派单记录（只登记，不执行门套件——webhook 只进收件箱，PoC-D 纪律）
        disp = {"order_id": order_id, "suite": suite, "repo": repo, "subject": subject,
                "thread_key": env.get("thread_key"), "dedup_key": dedup_key,
                "source": source, "delivery_id": delivery_id, "event_type": etype,
                "action": action or None, "recipe_digest": recipe_digest,
                "payload_sha256": env.get("payload_sha256"),
                "created_at": rec_common["consumed_at"],
                "status": "dispatch-record-only",
                "note": ("PoC-D 派单记录：webhook 只进收件箱；门套件执行不在本腿"
                         "（F 门单/门套件职责）。order_id=hash(repo+suite+subject+"
                         "recipe_digest) 确定性生成，重放天然幂等。")}
        if not DRY:
            os.makedirs(TRIGGER_DISPATCH_D, exist_ok=True)
            tmp = os.path.join(TRIGGER_DISPATCH_D, order_id + ".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(disp, f, ensure_ascii=False, indent=1)
            os.replace(tmp, os.path.join(TRIGGER_DISPATCH_D, order_id + ".json"))
            _trigger_append_consumed({**rec_common, "order_id": order_id,
                                      "result": "dispatched"})
            changelog(f"Trigger 消费：{etype} {repo}"
                      f"{'/' + action if action else ''}@{str(subject)[:12]} → {suite} "
                      f"派单记录 {order_id}（只登记不执行门套件）")
        else:
            log(f"[DRY] Trigger 消费：{etype} {repo}@{str(subject)[:12]} → {suite} "
                f"派单 {order_id}（只登记）")
        st["trigger_consumed"][delivery_id] = order_id
        st["trigger_dedup"][dedup_key] = order_id
        dids.add(dk)
        dkeys.add(dedup_key)
        oids.add(order_id)
        n_new += 1
    if n_new or n_skip:
        log(f"Trigger 消费腿：新派单 {n_new}、skip {n_skip}（游标 {TRIGGER_CONSUMED_F}）")


def main():
    st = load_state()
    # 版本钉（2026-11-03 在役换码批）：起跑即把「在役载入源码指纹」登记进状态面并落盘
    # ——换码后第一件事就是把「在役跑的是哪一版」变成可核验事实（此前只能靠 ps lstart
    # vs 盘面 mtime 推断，而那正是本次 RT-E157/RT-E160/RT-E169 三批修复整批未在役
    # 30h+ 无人发现的根因面）。
    st["daemon_src"] = daemon_src_stamp()
    save_state(st)
    # 启动行带取帽快照（自适应帽值 / 源 verified 规模）：帽在模块导入时取值（DEB-5a），
    # 在役帽值自此可直接从日志对账——2026-11-02 前只能靠 ps lstart vs 盘面 mtime 推断，
    # E68 旧帽形态在役延续 9.5h 未被察觉。「event-router 起」前缀不变（全仓 grep 亲证：
    # 该行无下游内容解析者，仅历史报告 md 引用），下游 mtime 判活不受影响。
    log(f"event-router 起（周期 {INTERVAL}s，DRY={DRY}，"
        f"kb帽={KB_INGEST_TIMEOUT}s/源verified={KB_INGEST_TIMEOUT_SRC_VERIFIED}"
        f"，在役载入版本 sha256={str((st.get('daemon_src') or {}).get('sha256'))[:12]}…）")
    # 跨卡裁决时序消费腿·存量回灌（RT-E32）：启动即对账留档卡，把修复前遗留的 verified
    # 违规原子双库降级（自愈腿：净化批只清存量一轮，实测 2.5h 即复现本类）。
    try:
        crosscard_startup_reconcile()
    except Exception as e:  # noqa: BLE001 - 回灌腿异常不许带崩主循环（下一轮/下次重启再收口）
        log(f"跨卡分歧消费（存量回灌腿）异常（不阻塞主循环）: {type(e).__name__}: {str(e)[:160]}")
    # 拒发残目录误判在飞·存量重武装（2026-11-02 RT，一次性）：修复前 skipped_newer 是按
    # 本地目录名误判的终态、verify_reflows 防重放把错判永久冻结。启动摘除（一次性旗标
    # verify_reflows_rearmed 防逐轮重武装——逐轮重评估 = 每轮 ssh×N，不可接受）。
    try:
        if not st.get("verify_reflows_rearmed"):
            n_stuck = rearm_skipped_newer(st)
            if n_stuck:
                changelog(f"拒发残目录误判在飞·存量重武装：摘除 {n_stuck} 条 skipped_newer 冻结账，"
                          "按「真上板才在飞」新口径重评估（重发上限照旧累计，总量有界）")
            st["verify_reflows_rearmed"] = True
            save_state(st)
    except Exception as e:  # noqa: BLE001 - 重武装异常不许带崩主循环
        log(f"skipped_newer 存量重武装异常（不阻塞主循环）: {type(e).__name__}: {str(e)[:160]}")
    while True:
        if os.path.exists(STOP):
            log("STOP 熔断在位")
            time.sleep(INTERVAL)
            continue
        try:
            for kind, order, task in poll_orders(st):
                if kind == "report_ok":
                    d = make_portal_seed(task)
                    changelog(f"report 判定通过自动派生门户种子：{order}/{task} → {d}")
                else:
                    if f"rr55-{task}" not in st.get("rr55", []):
                        st.setdefault("rr55", []).append(f"rr55-{task}")
                        enqueue_rr55(task)
                        changelog(f"swev max_turns 自动排 rr55 复跑：{order}/{task}")
            poll_harvest(st)
            poll_verify_reports(st)
            poll_arbitrate_reports(st)
            # 零终裁台账消费腿（2026-11-03 RT·只登记不重派滞留面）：重派账逐轮推进，
            # 滞留/预算耗尽告警+点名——登记不再是终点（异常不带崩主循环，同全线护栏）。
            try:
                arb_reissue_accounting(st)
            except Exception as e:  # noqa: BLE001 - 消费腿异常不许带崩主循环
                log(f"零终裁重派账消费腿异常（不阻塞主循环）: {type(e).__name__}: {str(e)[:160]}")
            # ⑥ Trigger 收件箱消费腿（PoC-D，af.trigger.v1）：在既有 60s 主循环内、
            # 同一 STOP 熔断/异常护栏之下（上方 if os.path.exists(STOP) 在位即 continue，
            # 本腿与 ①②③⑤ 同进退）；只产派单记录，不执行门套件。
            try:
                poll_triggers(st)
            except Exception as e:  # noqa: BLE001 - 消费腿异常不许带崩主循环
                log(f"Trigger 消费腿异常（不阻塞主循环）: {type(e).__name__}: {str(e)[:160]}")
            save_state(st)
        except Exception as e:
            log(f"循环异常（不退出）: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
