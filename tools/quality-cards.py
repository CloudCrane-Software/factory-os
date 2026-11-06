#!/usr/bin/env python3
"""quality-cards.py — KB 存量质量工序卡生成器（三类一次性卡，2026-10-29 供给扩容批 S2）

把 KB 存量变成可持续的任务源：每张卡都是一道真实的质量工序，不是凑数。
数据源全部只读：kb/kb.db（mode=ro）+ kb-seed/registry.db（mode=ro）+ 事件路由器
在 计划/变更日志.md 的「分歧检测」登记 + kb-seed/sandbox/verify/ 的复核回报留档。

三类卡（同走 cross-verify/card-lint 同款卡形态：problem.md + AGENTS.md + meta.json，
全过 tools/card-lint.py 八条硬指标 fail-closed，过闸才 scp 上板 gov）：

  ① k=3 追加复核卡（kind=kb-verify，id 后缀 r3）
     对 kb/kb.db 里 verified 原子数 top 20 的论文，各生成一张第三重复核卡。
     复用 tools/cross-verify.py 的生成机制（build_problem_md / build_agents_md /
     next_attempt / perspective_for / ensure_cache / 同一套 lint 闸），atom 集改从
     KB 当前 verified 原子取（库里是什么就复核什么，比追旧候选 JSONL 更真）。
     id 方案（详细读现有 id 规则后设计，续接不冲突）：
       现有卡 = kb-verify-<base>-<attempt>[r<replica>]，replica 血线各自独立计轮次
       （cross-verify.py:115-131 next_attempt 按「同 task_id 同副本血线」取最大+1）。
       r3 是新血线：attempt 取该 base 既有全部副本的最大轮次（=最新一批），replica=3，
       得 kb-verify-<base>-<A>r3。它与 r1/r2 同批同 atom 域、编号不撞（该 base 下
       不存在任何 r3 卡），且未来 cross-verify 对 r1/r2 的 attempt+1 派单取的是
       r1/r2 血线最大值，不会被 r3 顶掉。种子口径照抄 cross-verify.py:456-462
       （sha256("<base_seed>|r3")），重跑可复现。

  ② 分歧仲裁卡（kind=kb-arbitrate，模板新立）
     从 计划/变更日志.md 的「分歧检测（不阻塞 admit）」登记提取分歧 atom 集（每例一张），
     两个复核员的结论（verdict + quote_check + reason）都附上，要求第三方逐字重验
     并给出终裁 final + 理由 rationale。一次性卡：payload 不带 "verify": true，
     卡 id 不以 kb-verify- 开头，事件路由器不会把它当验证卡消费（event-router.py:918）。

  ③ 蒸馏复核卡（kind=kb-distill-review，模板新立）
     对 kb/kb.db provenance 里已 apply 的 21 对 merge 事件，各生成一张合并正确性
     复核卡：内嵌赢家/输家原子全文 + score + 合并理由 + provenance 摘要，第三方复核
     是否丢失信息。一次性卡（同上不走回流线）。这类合并的证据源是 KB 本身（主源多为
     博客/文档，无 arXiv 可抓），故 card-lint 为其配等强度「KB 内部证据」门 L3′/L4′
     （见 tools/card-lint.py kind 维度）；运营者 2026-10-29 裁决方案 B。

纪律：
  · STOP 熔断：kb-seed/sandbox/.router-STOP 或 .quality-cards-STOP 在位即拒发
    （--force 才覆盖），与 cross-verify.py:405-407 同口径。
  · 去重四腿（evidence-cache / task-seeds / gov tasks + gov 已回报 submitted），
    既有口径神圣不可破：本批的语义是对同一批论文/同一批原子追加复核，arXiv id 腿
    用于证据缓存复用与展示，幂等由「卡目录精确名 + gov 已回报 task id」两条腿保证
    （卡 id 不同就不是重种）。
  · 幂等可重跑：卡目录已存在（本地或 gov）即跳过，不覆盖不重发；抽样种子由
    arxiv|base|attempt 派生，重跑得同一批原子。
  · arXiv 访问只读；只在证据缓存缺失时才抓，且沿用 cross-verify.ensure_cache 的
    既有口径（本批 32 个 arXiv id 全部已缓存，实跑零请求）。
  · 不改 router/cross-verify 既有行为；日志追加落 kb-seed/sandbox/quality-cards.log。

轮换选源（2026-10-30 工单①「质量工序卡常态化」）：
  · --top N = **选源窗口深度**：考察「verified 原子数降序」的排名区间 [start, start+N)，
    N 可任意大（支持 --top 200；默认仍 20，向后兼容）。
  · 状态文件（QUALITY_CARDS_STATE，默认 kb-seed/sandbox/quality-cards-state.json）记
    **已出卡论文集合**（done_papers）与「已考察但不可出卡」集合（depleted_papers）；
    窗口内命中集合的论文**跳过**（轮换）→ 有效选源自然下探到排名更深处。
  · 幂等腿（卡目录精确名 + gov 已回报 task id）仍然神圣：已存在的卡不重发，且该论文
    同时登记进 done_papers（已做过）。
  · 窗口推进：只有显式 --advance-window（scheduler 排期轮次用）且当前窗口已耗尽
    （窗口内论文全部已做过/不可出卡）时，窗口下移一段（start += len(window)），
    保证常态化持续产卡；**手工重跑不推进窗口 → 重复跑 0 新增**。
  · 状态文件原子写（tmp + os.replace）；--dry-run 一律不写状态文件。
用法：
  python3 tools/quality-cards.py [--kind all|verify|arbitrate|distill] [--top 20]
          [--n 12] [--dry-run] [--no-scp] [--force] [--quiet] [--selfcheck]
          [--advance-window] [--window-start N]
  --dry-run  只算候选与卡 id，不建卡不抓证据不 scp 不落日志（stdout 出计划）
  --selfcheck 对 task-seeds 上本批生成的卡重跑 lint + 对 kb.db 独立复校（只读）
  --advance-window  允许选源窗口在耗尽后下移（排期轮次用；手工重跑不加此参=不推进）
  --window-start N  显式指定选源窗口起点（调试/DRY 用；默认取状态文件记录）
退出码（调用方以退出码判成败——口径同 report-feeder，2026-11-03 RT 收口）：
  0  本轮各腿无失败项（stdout 恒有 JSON 摘要：顶层 ok + summary 各腿计数）
  1  --selfcheck 复校不通过
  2  STOP 熔断在位 / --top 非法
  3  本轮有失败项（过闸挂/推送挂等）——stdout JSON 仍照旧输出（ok=false、failed 计数）
回滚：删 task-seeds/kb-{verify-*r3,arbitrate-*,distill-*} 目录 + gov 同名任务目录；
      轮换状态回滚：删 QUALITY_CARDS_STATE 状态文件（下次从窗口起点重跑）。"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SB = WS + "/kb-seed/sandbox"
# 副本/DRY 验证用环境变量（口径同 tools/portal-seeder.py 的 SEEDER_SB/SEEDER_GOV）：
# 只改「落盘的板子与推送目标」，evidence-cache / kb.db / registry / 变更日志恒指生产真源
# （它们是只读证据，DRY 验证要用真证据才算验证）。
SEEDS = os.environ.get("QUALITY_CARDS_SEEDS") or SB + "/task-seeds"
CACHE = SB + "/evidence-cache"
CAND_DIR = SB
VERIFY_DIR = SB + "/verify"
KB_DB = WS + "/kb/kb.db"
REGISTRY = WS + "/kb-seed/registry.db"
CHANGELOG = WS + "/计划/变更日志.md"
LOG = os.environ.get("QUALITY_CARDS_LOG") or SB + "/quality-cards.log"
# 路由器状态面（零终裁台账只读源，2026-11-03 RT·零终裁重派解堵）：只读不写；
# 副本/DRY 验证可用 QUALITY_CARDS_ROUTER_STATE 改道（不动生产面，口径同 SEEDS/STATE）。
ROUTER_STATE = os.environ.get("QUALITY_CARDS_ROUTER_STATE") or SB + "/.router-state.json"
# 轮换状态文件（2026-10-30 工单①）：记「已出卡论文集合」+ 选源窗口起点。
# 副本/DRY 验证可用 QUALITY_CARDS_STATE 改道（不动生产面）。
STATE = os.environ.get("QUALITY_CARDS_STATE") or SB + "/quality-cards-state.json"
TEMPLATE = SEEDS + "/_AGENTS_template.md"
STOPS = (SB + "/.router-STOP", SB + "/.quality-cards-STOP")
GOV = os.environ.get("QUALITY_CARDS_GOV") or "root@gov-host.invalid"
GOV_TASKS = os.environ.get("QUALITY_CARDS_GOV_TASKS") or "/opt/company/af-jobs/data/tasks/"

DEFAULT_TOP = 20
DEFAULT_N = 12
ADVANCE_GAP_S = 7200              # 窗口推进最小间隔（2h，与 scheduler 调用节流同口径）
REPLICA = 3                       # 本批追加的副本号（k=3 的第三张）
REPLICAS = 3
DIVERGENCE_MIN = 10               # 工单要求「分歧检测登记 ≥10 例」
# 零终裁重发帽（2026-11-03 RT·零终裁「只登记不重派」滞留面）：同一分歧
# （divergence_key）的零终裁卡达到该数 = 该分歧自动重发预算耗尽，_arbitrate_existing
# 恢复幂等遮蔽（不再重发、等运营者），耗尽由 event-router 零终裁台账消费腿
# （arb_reissue_accounting）告警+点名。帽=2 ⇒ 每分歧自动重发 1 次，总量有界。
ARB_REISSUE_CAP = 2
ARX_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")
ATOM_ID_RE = re.compile(r"^sbx-(?P<base>.+)-\d+$")
TS_SUFFIX_RE = re.compile(r"^(?P<tid>.+?)-\d{8}-\d{6}\.jsonl$")
CARD_ATTEMPT_RE = re.compile(r"^(?P<attempt>\d+)(?:r(?P<replica>\d+))?$")
# 事件路由器「分歧检测」登记行（event-router.py 写入口径，逐字对齐；两代格式双认：
#   旧＝「分歧检测（不阻塞 admit）：…（各卡 admit/reject 仍按 uphold 率阈值与幂等规则独立执行）」
#   新＝「分歧检测（跨卡裁决时序消费腿已接管）：…（裁决时序最新者为准：…待独立复核）」
# （2026-11-02 RT-E32 修复：跨卡分歧不再纯观测，event-router 的括注文案随之更换；变更日志
#   append-only，历史行仍是旧格式——本正则必须两代都命中，否则分歧仲裁卡喂料断流）
DIV_LINE_RE = re.compile(
    r"^\|\s*(?P<date>[^|]+?)\s*\|\s*事件路由器\(自动\)\s*\|\s*"
    r"分歧检测（(?:不阻塞 admit|跨卡裁决时序消费腿已接管)）：同一 atom 集 `(?P<gkey>[^`]+)` 跨卡一致率 "
    r"(?P<agree>\d+)/(?P<cmp>\d+)=(?P<rate>[\d.]+)<1；卡 "
    r"(?P<cards>`[^`]+`(?:、`[^`]+`)*)；分歧原子：(?P<detail>.+?)"
    r"（(?:各卡 admit/reject 仍按 uphold 率阈值与幂等规则独立执行"
    r"|裁决时序最新者为准[^）]*)）")
ARBITRATE_FINALS = ["uphold", "refute", "unverifiable"]
DISTILL_FINALS = ["no_loss", "info_loss", "wrong_winner", "unverifiable"]


# --------------------------------------------------------------- 基础件（复用既有）
def _load(mod_name, path):
    """按路径加载既有工具模块（复用其生成机制，不在本文件复制一份）。"""
    loader = SourceFileLoader(mod_name, path)
    spec = importlib.util.spec_from_loader(mod_name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def log(msg, quiet=False, to_file=True):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    if not quiet:
        print(line, flush=True)
    if to_file:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def sh(cmd, timeout=90):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def scp_push(card_dir):
    """推送一张卡到 gov，返回 (是否送达, 失败原因)。

    2026-11-01 RT 修复：旧码 `r = sh("scp …"); scp_done=True; if r:`——sh 只回
    stdout，而 scp 失败走 stderr、stdout 恒空 → 失败判据永不触发，gov 不可达也
    记 scp=True/失败 0（轮换账本随之把论文记 done 永不再试，供给中毒）。此处以
    退出码为准（BatchMode + ConnectTimeout=10 + 60s 双超时，口径同
    event-router.py:149 sh_rc 的 DEB-1 修复）。"""
    cmd = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           "-r", card_dir, f"{GOV}:{GOV_TASKS}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, f"scp 超时（>60s）: {card_dir}"
    except OSError as e:
        return False, f"scp 异常 {type(e).__name__}: {str(e)[:80]}"
    if p.returncode != 0:
        return False, (p.stderr or "").strip()[:120] or f"scp 退出码 {p.returncode}"
    return True, ""


def discard_undelivered(card_dir, tag, card_id, why, quiet=True):
    """推送失败的卡撤下本地（没上门户就不算发过，口径同 event-router.py:646）。

    三类卡的幂等腿都认「本地卡目录精确名」（:384/:764/:1044）——残卡不撤，下一轮
    会被当成「已存在」跳过并把论文记进轮换 done / 分歧幂等键，推送失败被永久遮蔽。
    卡由本脚本确定性可复现（同库同 seed 同 atom 集），撤下即下一轮原样重出重推。"""
    try:
        shutil.rmtree(card_dir)
    except OSError as e:
        log(f"[{tag}] {card_id} 未送达且本地残卡清理失败（{type(e).__name__}: {e}）——"
            f"下轮将被幂等腿跳过、不再重试，需人工处理: {card_dir}", quiet)
        return
    log(f"[{tag}] {card_id} 推送失败未上门户，已撤下本地残卡（下轮自动重出重推）: {why}",
        quiet)


def ro_connect(path):
    return __import__("sqlite3").connect(f"file:{path}?mode=ro", uri=True)


def lint_gate(card_dir):
    """card-lint 质量闸（fail-closed：闸自身异常也视为不过；口径同 cross-verify.py:203-213）。"""
    try:
        cl = _load("cardlint", WS + "/tools/card-lint.py")
        errs, notes = cl.lint_card(card_dir, cache=CACHE, kb_db=KB_DB)
        return errs, notes
    except Exception as e:
        return [f"质量闸自身异常（fail-closed）: {e}"], []


def scrub_foreign_arxiv(text, primary):
    """把卡内非主证据源的 arXiv id 抹成占位串（card-lint L3 要求证据源唯一）。
    只动「引用到别篇论文」的 id，不影响本卡主证据源。"""
    def rep(m):
        return m.group(0) if m.group(0) == primary else "〔引用 id 已脱敏〕"
    return ARX_RE.sub(rep, text or "")


def only_arxiv_ids(text):
    return sorted(set(ARX_RE.findall(text or "")))


# --------------------------------------------------------------- 去重四腿（既有口径）
def dedup_legs():
    """四腿：evidence-cache 目录名 + task-seeds 目录名内嵌 arXiv id + gov tasks 目录名
    （三重并集，口径同 tools/portal-seeder.py:146-172）+ gov 已回报 task id（submitted，
    口径同 tools/af-jobs-portal.py:122-135 的 reports/ 单一真源）。
    另返两份「精确名」集：本地卡目录名 与 gov 卡目录名——本批幂等由这两条腿保证
    （卡 id 不同就不是重种；arXiv id 腿用于证据缓存复用与展示）。"""
    legs = {"evidence-cache": set(), "task-seeds": set(), "gov": set(), "submitted": set()}
    names_local, names_gov = set(), set()
    if os.path.isdir(CACHE):
        legs["evidence-cache"] |= set(os.listdir(CACHE))
    if os.path.isdir(SEEDS):
        for d in os.listdir(SEEDS):
            names_local.add(d)
            m = re.search(r"(\d{4}\.\d{4,5})", d)
            if m:
                legs["task-seeds"].add(m.group(1))
    gov_tasks = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=10 {GOV} "
                   f"'ls {GOV_TASKS}'", 60)
    for d in gov_tasks.split():
        names_gov.add(d)
        m = re.search(r"(\d{4})[.-](\d{4,5})(?:-r\d+)*(?:-\d+)*$", d)
        if m:
            legs["gov"].add(f"{m.group(1)}.{m.group(2)}")
    gov_reports = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=10 {GOV} "
                     f"'ls /opt/company/af-jobs/data/reports/'", 90)
    for fn in gov_reports.split():
        if fn.endswith(".json"):
            legs["submitted"].add(fn.rsplit("-", 1)[0])
    used = set().union(*legs.values())
    return {"legs": legs, "used": used, "names_local": names_local,
            "names_gov": names_gov, "gov_reachable": bool(gov_tasks.strip())}


# --------------------------------------------------------------- KB 只读取数
def kb_verified_by_paper(con):
    return dict(con.execute(
        "SELECT paper, COUNT(*) FROM atoms WHERE status='verified' "
        "GROUP BY paper ORDER BY COUNT(*) DESC, paper ASC").fetchall())


def base_of(atom_id):
    m = ATOM_ID_RE.match(atom_id or "")
    return m.group("base") if m else None


def kb_atoms_for_base(con, base):
    """该抽取线（base）下 KB 当前 verified 原子 → cross-verify 同款 atom dict。"""
    pat = re.compile(r"^sbx-" + re.escape(base) + r"-\d+$")
    out = []
    for aid, content, attrs in con.execute(
            "SELECT id, content, attrs FROM atoms WHERE status='verified'"):
        if not pat.match(aid):
            continue
        a = json.loads(attrs or "{}")
        text = (content or "").split("\n", 1)[0].strip()
        out.append({"atom_id": aid, "kind": a.get("kind"), "text": text,
                    "source": a.get("source") or {}})
    out.sort(key=lambda x: x["atom_id"])
    return out


def max_attempt(seeds_dir, base):
    """该 base 既有全部副本的最大轮次（跨 replica 血线取 max，=最新一批）。"""
    prefix = f"kb-verify-{base}-"
    best = 0
    for d in glob.glob(os.path.join(seeds_dir, prefix + "*")):
        m = CARD_ATTEMPT_RE.match(os.path.basename(d)[len(prefix):])
        if m:
            best = max(best, int(m.group("attempt")))
    return best


def latest_candidate_file(base):
    """该 base 最新的候选 JSONL 文件名（收割方 <task_id>-YYYYMMDD-HHMMSS.jsonl）。"""
    files = []
    for f in glob.glob(os.path.join(CAND_DIR, "kb-atoms-*.jsonl")):
        m = TS_SUFFIX_RE.match(os.path.basename(f))
        if m and m.group("tid") == base:
            files.append(f)
    return os.path.basename(sorted(files)[-1]) if files else ""


# ------------------------------------------- 轮换状态（2026-10-30 工单① 选源轮换）
def load_state():
    """读轮换状态文件（不存在即空状态）。损坏文件不静默吞：退回空状态并记日志。"""
    st = {"version": 1, "window_start": 0, "window_depth": 0,
          "done_papers": [], "depleted_papers": [],
          "rounds": 0, "last_run_ts": 0, "last_advance_ts": 0, "updated": ""}
    if not os.path.isfile(STATE):
        return st
    try:
        j = json.load(open(STATE, encoding="utf-8"))
        if isinstance(j, dict):
            for k in st:
                if k in j:
                    st[k] = j[k]
    except Exception as e:  # noqa: BLE001 —— 状态文件坏了要看得见，不静默
        log(f"轮换状态文件读取失败（{STATE}: {type(e).__name__}: {str(e)[:80]}），"
            f"本轮按空状态起步（不丢已出卡幂等：卡目录精确名腿仍在）")
    st["done_papers"] = sorted(set(st.get("done_papers") or []))
    st["depleted_papers"] = sorted(set(st.get("depleted_papers") or []))
    return st


def save_state(st):
    """原子写轮换状态文件（tmp + os.replace）；失败不静默（幂等由卡目录腿兜底）。"""
    st["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        d = os.path.dirname(STATE)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
        return True
    except OSError as e:
        log(f"轮换状态文件写入失败（{STATE}: {e}）——本轮幂等仍由卡目录精确名腿保证")
        return False


# --------------------------------------------------------------- ① k=3 追加复核卡
def gen_verify_r3(con, cv, dd, top, n, dry_run, no_scp, force, quiet,
                  advance=False, window_start=None):
    """对 verified 原子数排名窗口内的论文各发一张 r3 追加复核卡（kind=kb-verify）。

    轮换选源（2026-10-30 工单①）：--top N = 选源窗口深度（排名区间 [start, start+N)）。
    窗口内「已做过」的论文（状态文件已出卡集合 ∪ 幂等腿已存在的卡）跳过 → 有效选源
    自然下探到排名更深处；窗口推进只由 --advance-window（排期轮次）触发且需窗口耗尽，
    手工重跑不推进 → 重复跑 0 新增。
    """
    counts = kb_verified_by_paper(con)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    st = load_state()
    done = set(st["done_papers"])
    depleted = set(st["depleted_papers"])
    start = int(st["window_start"]) if window_start is None else int(window_start)
    win = ranked[start:start + top]
    # 窗口推进：--advance-window 且窗口已耗尽（窗口内论文全部已做过/不可出卡）
    # 且距上次推进 ≥ ADVANCE_GAP_S（2h，与 scheduler 调用节流同口径——排期轮次才推进，
    # 手工重跑（含带 --advance-window 的重复跑）不推进 → 重复跑 0 新增）
    exhausted = bool(win) and all(p in done or p in depleted for p, _ in win)
    adv_gap = time.time() - float(st.get("last_advance_ts") or 0)
    old_start = start
    if advance and exhausted and adv_gap < ADVANCE_GAP_S:
        log(f"[①] 选源窗口未推进：已耗尽但距上次推进 {int(adv_gap)}s<{ADVANCE_GAP_S}s"
            f"（排期轮次节流）", quiet, to_file=not dry_run)
    elif advance and exhausted:
        start += len(win)
        if start >= len(ranked):
            # 回卷：论文池已扫完（KB 新增论文随原子增长排名靠后，轮换继续覆盖全池，
            # 不会因索引越界让这条供给线静默死掉）
            log(f"[①] 选源窗口回卷：起点 {start} 已越出论文池（{len(ranked)} 篇）→ 回到 0",
                quiet, to_file=not dry_run)
            start = 0
        st["window_start"] = start
        st["last_advance_ts"] = time.time()
        win = ranked[start:start + top]
        log(f"[①] 选源窗口推进：上一窗口（排名 {old_start} 起）已耗尽 → "
            f"新窗口排名 [{start}, {start + len(win)})（共 {len(win)} 篇候选论文）",
            quiet, to_file=not dry_run)
    st["window_depth"] = len(win)
    papers = [p for p, _ in win]
    skipped_done = [p for p in papers if p in done or p in depleted]
    log(f"[①] 选源窗口：排名 [{start}, {start + len(win)}) 共 {len(win)} 篇候选论文"
        f"（verified 原子数降序，同分按 arXiv id 升序）；已做过跳过 {len(skipped_done)} 篇"
        f"（轮换）", quiet, to_file=not dry_run)
    if len(ranked) > start + top and len(win) == top and ranked[start + top - 1][1] == ranked[start + top][1]:
        c = ranked[start + top - 1][1]
        tied = [p for p, n in ranked if n == c]
        inb = [p for p, n in win if n == c]
        out = [p for p in tied if p not in inb]
        log(f"[①] top{top} 边界落在 {c} verified 原子的 {len(tied)} 篇并列上"
            f"（{'、'.join(tied)}）；确定性规则 = arXiv id 升序 → 入列 {'、'.join(inb)}，"
            f"未入列 {'、'.join(out)}（同分并列，规则可复现）", quiet, to_file=not dry_run)
    res = []
    for paper in papers:
        # 轮换跳过（2026-10-30 工单①）：状态文件已出卡/已考察的论文不再出卡
        if paper in done or paper in depleted:
            log(f"[①] {paper} 已做过（轮换状态文件），跳过", quiet)
            res.append({"ok": True, "card_id": None, "skipped": True, "arxiv": paper,
                        "reason": "rotation-done"})
            continue
        # 选 base：该论文下 verified 原子最多的抽取线（并列取 id 更小者，确定性）
        per = {}
        for aid, in con.execute(
                "SELECT id FROM atoms WHERE status='verified' AND paper=?", (paper,)):
            b = base_of(aid)
            if b:
                per[b] = per.get(b, 0) + 1
        if not per:
            log(f"[①] {paper} 无 sbx verified 原子，跳过", quiet)
            depleted.add(paper)
            continue
        base = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        rows = kb_atoms_for_base(con, base)
        if len(rows) < 2:
            log(f"[①] {base} 仅 {len(rows)} 条 verified 原子，跳过（不足最低复核量）", quiet)
            depleted.add(paper)
            continue
        attempt = max_attempt(SEEDS, base) or 1
        card_id = f"kb-verify-{base}-{attempt}r{REPLICA}"
        if card_id in dd["names_local"] or card_id in dd["names_gov"] \
                or card_id in dd["legs"]["submitted"]:
            log(f"[①] {card_id} 已存在（本地/gov/已回报），跳过（幂等）", quiet)
            done.add(paper)   # 已出过卡 = 已做过（登记进轮换状态，后续轮次直接跳过）
            res.append({"ok": True, "card_id": card_id, "skipped": True, "arxiv": paper})
            continue
        # 种子口径照抄 cross-verify.py:456-462（base_seed|r{J}），重跑可复现
        base_seed = hashlib.sha256(f"{paper}|{base}|{attempt}".encode()).hexdigest()[:12]
        seed = hashlib.sha256(f"{base_seed}|r{REPLICA}".encode()).hexdigest()[:12]
        rng = random.Random(seed)
        k = max(1, min(n, len(rows)))
        picked = rng.sample(rows, k)
        cand_file = latest_candidate_file(base)
        if dry_run:
            log(f"[①][dry-run] {card_id}：{paper} base={base} verified={len(rows)} "
                f"抽 {k} 条 seed={seed} 候选文件={cand_file or '无'}", quiet, to_file=False)
            res.append({"ok": True, "card_id": card_id, "arxiv": paper, "sampled": k,
                        "seed": seed, "dry_run": True})
            continue
        abs_f, full_f, only_abs = cv.ensure_cache(paper, fetch=not no_scp)
        if not os.path.isfile(abs_f) or os.path.getsize(abs_f) < 5000:
            log(f"[①] {card_id} 拒发：证据缓存缺摘要 {paper}/abs.md（card-lint L4 必挂）", quiet)
            res.append({"ok": False, "card_id": card_id, "gate": ["L4 证据缓存缺摘要"],
                        "arxiv": paper})
            continue
        card_dir = os.path.join(SEEDS, card_id)
        os.makedirs(card_dir, exist_ok=True)
        persp = cv.perspective_for(REPLICA, REPLICAS)
        open(os.path.join(card_dir, "problem.md"), "w", encoding="utf-8").write(
            cv.build_problem_md(paper, base, card_id, picked, len(rows), only_abs,
                                cv.UPHOLD_THRESHOLD, persp))
        open(os.path.join(card_dir, "AGENTS.md"), "w", encoding="utf-8").write(
            cv.build_agents_md(card_id, paper, k, persp))
        json.dump({"title": f"{paper} 知识原子交叉验证（{k} 条裁决，第 {REPLICA} 副本）",
                   "type": "kb-verify",
                   "est_load": "~15-30min CPU+web",
                   "reward": "工厂积分记账（sandbox_report 入 MES）",
                   "verify": {"card_id": card_id, "task_id": base, "arxiv": paper,
                              "candidates_file": cand_file,
                              "atoms_total": len(rows), "sampled": k, "seed": seed,
                              "uphold_threshold": cv.UPHOLD_THRESHOLD,
                              "atom_ids": [x["atom_id"] for x in picked],
                              "replica": REPLICA, "replicas": REPLICAS,
                              "perspective": persp[0], "attempt": attempt,
                              "verify_group": f"kb-verify-{base}-{attempt}",
                              "atom_source": "kb",
                              "atom_source_note": "atom 集取自 kb/kb.db 当前 verified 原子"
                                                  "（追加复核：库里是什么就复核什么）"}},
                  open(os.path.join(card_dir, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        errs, notes = lint_gate(card_dir)
        scp_done = False
        if errs:
            log(f"[①] {card_id} 未过质量闸，拒发: {'; '.join(errs)}", quiet)
            res.append({"ok": False, "card_id": card_id, "gate": errs, "arxiv": paper})
            continue
        if not dry_run and not no_scp:
            scp_done, scp_why = scp_push(card_dir)
            if not scp_done:
                # 2026-11-01 RT 修复：推送失败如实记失败（不记 done，卡撤下本地），
                # 论文留给下一轮重试——不再谎报已上门户（DEB-1 同款纪律）。
                log(f"[①] {card_id} scp 推送失败（卡已在本地，未上门户）: {scp_why}", quiet)
                discard_undelivered(card_dir, "①", card_id, scp_why, quiet)
                res.append({"ok": False, "card_id": card_id, "arxiv": paper,
                            "sampled": k, "scp": False, "push_failed": scp_why})
                continue
        log(f"[①] 生成追加复核卡 {card_id}（第 {REPLICA}/{REPLICAS} 副本，视角 {persp[0]}）："
            f"{paper} base={base} verified={len(rows)} 抽 {k} 条，证据源 arXiv:{paper}，"
            f"闸 {'/'.join(notes) or 'green'}，scp={scp_done}", quiet)
        done.add(paper)   # 已出卡 → 登记进轮换状态（后续轮次跳过，天然下探）
        res.append({"ok": True, "card_id": card_id, "arxiv": paper, "sampled": k,
                    "seed": seed, "scp": scp_done, "notes": notes})
    # 轮换状态落盘（--dry-run 一律不写：干跑不改变生产面）
    if not dry_run:
        st["done_papers"] = sorted(done)
        st["depleted_papers"] = sorted(depleted)
        st["rounds"] = int(st.get("rounds") or 0) + 1
        st["last_run_ts"] = time.time()
        save_state(st)
        log(f"[①] 轮换状态已存：已出卡论文 {len(st['done_papers'])} 篇 / "
            f"已考察不可出卡 {len(st['depleted_papers'])} 篇 / 窗口起点 {st['window_start']}",
            quiet)
    return res


# --------------------------------------------------------------- ② 分歧仲裁卡
def parse_divergences():
    """从 计划/变更日志.md 解析事件路由器的「分歧检测」登记 → 案例清单。"""
    cases = []
    if not os.path.isfile(CHANGELOG):
        return cases
    for ln, line in enumerate(open(CHANGELOG, encoding="utf-8"), 1):
        m = DIV_LINE_RE.match(line.strip())
        if not m:
            continue
        cards = re.findall(r"`([^`]+)`", m.group("cards"))
        atoms = []
        for part in m.group("detail").split("；"):
            part = part.strip()
            am = re.match(r"^(\S+?)\((.+)\)$", part)
            if not am:
                continue
            vd = {}
            for kv in am.group(2).split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    vd[k.strip()] = v.strip()
            atoms.append({"atom_id": am.group(1), "verdicts": vd})
        cases.append({"changelog_line": ln, "gkey": m.group("gkey"),
                      "agree": int(m.group("agree")), "compared": int(m.group("cmp")),
                      "rate": m.group("rate"), "cards": cards, "atoms": atoms})
    return cases


def lineage_of(card_id):
    """kb-verify-<base>-<attempt>[r<replica>] → 副本血线名（r1/r2/…；老格式单卡 = single）。
    正则与 tools/cross-verify.py:84 CARD_ATTEMPT_RE 同口径。"""
    m = re.match(r"^kb-verify-(?P<base>.+)-(?P<att>\d+)(?:r(?P<rep>\d+))?$", card_id or "")
    if not m:
        return "single"
    return f"r{m.group('rep')}" if m.group("rep") else "single"


def all_report_files(card_id):
    """该卡全部回报文件（按文件名里的 epochms 升序；路由器的消费顺序同此序）。"""
    files = glob.glob(os.path.join(VERIFY_DIR, card_id + "-*.json"))
    def key(p):
        m = re.search(r"-(\d+)\.json$", os.path.basename(p))
        return int(m.group(1)) if m else 0
    return sorted(files, key=key)


def pick_report(card_id, want):
    """挑一份对 want 里各 atom 的裁决与「分歧检测」登记一致的回报（一致者取最新）；
    找不到一致的就退回最新一份并标记 matched=False（登记时点 vs 现时点的差异要如实呈现）。"""
    best = None
    for p in all_report_files(card_id):
        try:
            rep = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        vs = {v.get("atom_id"): v.get("verdict")
              for v in (rep.get("payload") or {}).get("verdicts", [])}
        if all(vs.get(a) == w for a, w in want.items()):
            best = (rep, True)
    if best:
        return best
    fs = all_report_files(card_id)
    if fs:
        try:
            return json.load(open(fs[-1], encoding="utf-8")), False
        except Exception:
            pass
    return None, False


def _arb_zero_verdict_cards():
    """零终裁台账在册的仲裁卡 id 集（路由器 st['arb_zero_verdict']，只读快照）。
    状态面读不到/坏 → 空集：幂等照旧（绝不因读不到台账而多发卡）。"""
    try:
        st = json.load(open(ROUTER_STATE, encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 读不到=按无零终裁处理（幂等语义不回退）
        return set()
    return {v.get("card") for v in (st.get("arb_zero_verdict") or {}).values()
            if isinstance(v, dict) and v.get("card")}


def _arbitrate_existing(prefix, div_key, dd):
    """同一分歧（gkey + 分歧 atom 集 + 双方卡号）是否已有仲裁卡承载 → 返回卡 id 或 None。
    看本地 task-seeds 与 gov tasks 两处的 meta.json.arbitrate.divergence_key（一次 ssh 批量取）。

    2026-11-03 RT 修复（零终裁「只登记不重派」滞留面·重发解堵）：承载卡进了路由器零终裁
    台账（终裁未落库=该分歧从未被真正仲裁）时，旧码仍按 divergence_key 判「已承载，跳过
    （幂等）」→ 分歧被零终裁卡永久遮蔽（实测 55 卡/64 原子仲裁链滞留、在役轮换
    arbitrate 生成0/跳过175——重发被本幂等腿阻断，且种子不删=永不再发）。现口径
    （仅当承载者**全是**零终裁卡时才改判）：
      · 同分歧零终裁卡数 < ARB_REISSUE_CAP → 判未承载（返回 None，gen_arbitrate 顺延
        新号自动重发——重发预算内自愈，重派不再只靠人工）；
      · ≥ ARB_REISSUE_CAP → 恢复幂等遮蔽（返回承载卡；重发预算耗尽=转运营者，耗尽
        告警在 event-router 零终裁台账消费腿 arb_reissue_accounting）。
    承载者里有健康卡（未零终裁）照旧返回承载卡——正常幂等语义一字不改。"""
    keys, carriers = {}, {}
    for d in sorted(glob.glob(os.path.join(SEEDS, prefix + "*"))):
        try:
            v = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8")).get("arbitrate") or {}
            if v.get("divergence_key"):
                keys[v["divergence_key"]] = os.path.basename(d)
                carriers.setdefault(v["divergence_key"], []).append(os.path.basename(d))
        except Exception:
            continue
    gov_names = sorted(d for d in dd["names_gov"] if d.startswith(prefix))
    if gov_names:
        raw = sh(f"ssh -o BatchMode=yes -o ConnectTimeout=10 {GOV} "
                 f"'for d in {GOV_TASKS}{prefix}*; do echo \"===$$d\"; cat $$d/meta.json 2>/dev/null; done'",
                 120)
        for blk in raw.split("==="):
            if not blk.strip():
                continue
            name, _, body = blk.partition("\n")
            try:
                v = json.loads(body).get("arbitrate") or {}
                if v.get("divergence_key"):
                    keys[v["divergence_key"]] = os.path.basename(name.strip())
                    carriers.setdefault(v["divergence_key"], []).append(os.path.basename(name.strip()))
            except Exception:
                continue
    carriers_now = carriers.get(div_key) or []
    if carriers_now and not any(c not in _arb_zero_verdict_cards() for c in carriers_now):
        zvc = [c for c in carriers_now if c in _arb_zero_verdict_cards()]
        if len(zvc) < ARB_REISSUE_CAP:
            log(f"[②] 同分歧已由 {','.join(zvc)} 承载但全部零终裁登记（终裁未落库，分歧从未"
                f"被仲裁）→ 不判已承载，释放重派（预算 {len(zvc)}/{ARB_REISSUE_CAP}）")
            return None
    return keys.get(div_key)


def atom_record(con, atom_id, cand_index):
    """分歧原子的完整信息：优先 KB，回落候选 JSONL，再附 registry 状态。"""
    rec = {"atom_id": atom_id, "kind": "", "text": "", "locator": "", "quote": "",
           "status": "", "source": "kb"}
    row = con.execute("SELECT content, status, attrs FROM atoms WHERE id=?", (atom_id,)).fetchone()
    if row:
        a = json.loads(row[2] or "{}")
        src = a.get("source") or {}
        rec.update({"kind": a.get("kind") or "", "text": (row[0] or "").split("\n", 1)[0].strip(),
                    "locator": src.get("locator") or "", "quote": src.get("quote") or "",
                    "status": row[1] or ""})
    elif atom_id in cand_index:
        c = cand_index[atom_id]
        src = c.get("source") or {}
        rec.update({"kind": c.get("kind") or "", "text": (c.get("text") or "").strip(),
                    "locator": src.get("locator") or "", "quote": src.get("quote") or "",
                    "status": c.get("status") or "", "source": "candidate-jsonl"})
    try:
        rcon = ro_connect(REGISTRY)
        r = rcon.execute("SELECT status FROM candidates WHERE id=?", (atom_id,)).fetchone()
        if r:
            rec["registry_status"] = r[0]
        rcon.close()
    except Exception:
        pass
    return rec


def load_cand_index(gkey):
    idx = {}
    p = os.path.join(CAND_DIR, gkey)
    if not os.path.isfile(p):
        return idx
    for line in open(p, encoding="utf-8"):
        try:
            j = json.loads(line)
        except Exception:
            continue
        cid = j.get("candidate_id") or j.get("atom_id")
        if cid:
            idx[cid] = j
    return idx


def build_arbitrate_md(cv, arx, base, card_id, case, atoms):
    n = len(atoms)
    c1, c2 = (case["cards"] + ["", ""])[:2]
    rows_a, rows_v, rows_r = [], [], []
    for i, a in enumerate(atoms, 1):
        rows_a.append(f"| {i} | `{cv._cell(a['atom_id'], 80)}` | {cv._cell(a['kind'], 40)} | "
                      f"{cv._cell(a['text'], 120)} | {cv._cell(a['locator'], 60)} | "
                      f"{cv._cell(a['quote'], 300)} |")
        reg = a.get("registered") or {}
        b1 = a["reviewers"].get(c1) or {}
        b2 = a["reviewers"].get(c2) or {}
        rows_v.append(
            f"| {i} | `{cv._cell(a['atom_id'], 80)}` | "
            f"{cv._cell(reg.get('r1'), 16)} | {cv._cell(reg.get('r2'), 16)} | "
            f"{cv._cell(b1.get('verdict'), 20)} | {cv._cell(str(b1.get('quote_check')), 12)} | "
            f"{cv._cell(b2.get('verdict'), 20)} | {cv._cell(str(b2.get('quote_check')), 12)} |")
        m1 = "" if b1.get("matched_registration", True) else "（现时点结论，与登记时点不同）"
        m2 = "" if b2.get("matched_registration", True) else "（现时点结论，与登记时点不同）"
        rows_r.append(
            f"| {i} | `{cv._cell(a['atom_id'], 80)}` | "
            f"{cv._cell((b1.get('reason') or '') + m1, 200)} | "
            f"{cv._cell((b2.get('reason') or '') + m2, 200)} |")
    tab_a, tab_v, tab_r = "\n".join(rows_a), "\n".join(rows_v), "\n".join(rows_r)
    src_desc = ("1. 摘要页：https://arxiv.org/abs/" + arx + " —— **该文 arXiv 未提供 HTML 全文**，"
                "全部 quote 只能取自摘要页原文\n"
                if case.get("only_abs") else
                "1. 摘要页：https://arxiv.org/abs/" + arx + "\n"
                "2. 全文 HTML（优先）：https://arxiv.org/html/" + arx + "\n")
    return f"""# {arx} 分歧仲裁（A 报 → B1/B2 分歧 → C 终裁）

## 你是谁、为谁工作
你是 **C**：与 A（抽取沙箱）以及两位复核员 B1/B2 都独立的第三方沙箱 agent。
厂内路由器在同一 atom 集上检出两位复核员结论不一致，运营者裁决：
**分歧不就地抹平，交第三方逐字重验并终裁**。你的职责是仲裁——不是重新抽取、
不是润色、不是补全，也不是在 B1/B2 之间和稀泥。

## 证据源（唯一，必须由你独立抓取）
{src_desc}把抓到的内容存为本地文件 wikiskill 同款证据：abs.md 与 full.md（若可得），
并计算 sha256 写进回报的 evidence.sources。**只信任你自己抓到的文本**：A 的引文、
B1 的结论、B2 的结论与理由，全部只是待检对象，不得当作证据。

## 分歧背景（厂内路由器登记，原文照录）
- atom 集（候选文件）：`{case['gkey']}`
- 跨卡一致率：{case['agree']}/{case['compared']}={case['rate']}（<1，故触发仲裁）
- 复核员 B1（视角 r1，逐字核验）：卡 `{c1}`
- 复核员 B2（视角 r2，语义核对）：卡 `{c2}`
- 登记出处：`计划/变更日志.md` 第 {case['changelog_line']} 行（事件路由器自动写入）
- **登记时点 ≠ 现时点**：路由器按「消费到回报的先后」留各副本血线的最新裁决，某位复核员
  若在登记之后又交了修订回报，其现时点结论可能与登记时点不同。下面「登记时点」两列是
  权威的分歧事实；若某位复核员的理由取自现时点回报，会当场标注。**你依据证据终裁，
  不必迁就任何一份回报。**

## 待仲裁原子与 A 的引文（共 {n} 条，一条不漏、一条不多）
A 报的 kind 取自词表 {"|".join(cv.KIND_VOCAB)}，你不必也不应改判 kind。

| # | atom_id | kind | text | A 记的 locator | A 的 source.quote（≤120字逐字引） |
|---|---------|------|------|----------------|-----------------------------------|
{tab_a}

## 两位复核员的裁决（登记时点为权威；理由原文照录）
| # | atom_id | 登记时点 r1 | 登记时点 r2 | B1 verdict | B1 quote_check | B2 verdict | B2 quote_check |
|---|---------|-------------|-------------|------------|----------------|------------|----------------|
{tab_v}

## 两位复核员的理由（原文照录；你只终裁，不转抄）
| # | atom_id | B1 reason | B2 reason |
|---|---------|-----------|-----------|
{tab_r}

## 仲裁规程（按序执行）
1. **独立取证**：自己抓 abs.md / full.md 并算 sha256；抓不到的章节如实进
   `evidence.sections_missing`，**绝不凭训练记忆编造论文内容**。
2. **逐字重验**：A 的 source.quote 是否在你抓到的证据文本里作为**连续子串**逐字出现
   （缩略、改写、翻译、凭记忆补写，一律 quote_check=false 并在 rationale 里指出差异）。
3. **命题层核对**：quote 逐字出现但命题被夸大、数字口径不一致、因果写反、单点实验
   写成普适规律、别节/别对象的结果张冠李戴——同样判 refute。
4. **终裁**：对每条原子给出 `final`，只用 `uphold` / `refute` / `unverifiable` 三个词，
   并给 `rationale`（≤120 字，写「证据位置（节名/段落）+ 依据 + 为何采纳/否决 B1、B2」）。
5. **站队要留痕**：`agree_with` 填 `b1` / `b2` / `neither`，让厂内能统计两位复核员
   各自的可信度；填 `neither` 时 rationale 必须说明两条都不成立的理由。

## 聚合规则（告知在先，不阻塞）
厂内按你的终裁统计 uphold 率与 agree_with 分布；本卡是一次性仲裁卡，
不走验证卡的回流重派线。

## 产出（POST /report 的 payload.schema，固定，不得增删字段）
终裁清单放 **payload.rulings**（数组）。本卡 type=kb-arbitrate，
**payload 不得带 `"verify": true`**（带了会被厂内路由器误当成 kb-verify 验证卡消费）。

| 字段 | 类型 | 必填 | 合法值 / 写法 | 典型错法（写了就被拒） |
|------|------|------|---------------|------------------------|
| atom_id | string | 是 | 上表出现过的 atom_id，原文照抄 | 自编短 id、漏前缀、拼错一位 |
| final | string | 是 | 小写 `uphold` / `refute` / `unverifiable` 三词之一 | 写中文"成立"、大写、写 "likely true" |
| quote_check | boolean | 是 | JSON 布尔 `true` / `false` | 字符串 `"true"`、`1`/`0`、`yes`/`no` |
| rationale | string | 是 | ≤120 字，指向你自己抓到的证据位置 | 空串、只写"同上"、不指向证据 |
| agree_with | string | 是 | `b1` / `b2` / `neither` 之一 | 写复核员卡号、写中文 |

### 完整合法回报 JSON 示例（照这个结构把上表 {n} 条写满，顺序不限）
```json
{{"arbitrate": true, "card_id": "{card_id}", "arxiv": "{arx}",
 "rulings": [
   {{"atom_id": "{cv._cell(atoms[0]['atom_id'], 80) if atoms else '<上表atom_id>'}",
    "final": "uphold", "quote_check": true,
    "rationale": "§3.1: 原文 …，逐字引命中且命题无夸大；B2 的质疑在该节不成立",
    "agree_with": "b1"}}
 ],
 "evidence": {{"sources": [{{"name": "abs.md", "sha256": "你自己抓取的abs.md的sha256"}},
                           {{"name": "full.md", "sha256": "你自己抓取的full.md的sha256"}}],
              "sections_missing": []}}}}
```

## 回报前自检清单（逐条打勾再 POST；任一不过 = 白跑一轮算力）
- [ ] `payload.rulings` 是非空数组，条数正好等于上表的 {n} 条（一条不漏、一条不多）
- [ ] 每条都含 `atom_id` / `final` / `quote_check` / `rationale` / `agree_with` 五个字段
- [ ] 每个 `final` 都是 `uphold` / `refute` / `unverifiable` 之一（小写英文原词）
- [ ] 每个 `quote_check` 都是 JSON 布尔 `true`/`false`（不是字符串、不是 1/0）
- [ ] 每个 `atom_id` 都能在上表里原文找到（拼错一位 → 厂内不认识 → 整份忽略）
- [ ] 每个 `rationale` 非空且指向我自己抓到的证据位置（节名/段落）
- [ ] `unverifiable` 不超过 2 条；`quote_check` 没有全为 false
- [ ] 抓不到的章节如实进 `evidence.sections_missing`，**绝不凭训练记忆编造论文内容**
"""


def gen_arbitrate(con, cv, dd, dry_run, no_scp, quiet):
    cases = parse_divergences()
    if len(cases) < DIVERGENCE_MIN:
        log(f"[②] 分歧检测登记仅 {len(cases)} 例（<{DIVERGENCE_MIN}），不满足工单门槛，跳过",
            quiet)
        return []
    # 稳定编号：同一 base 的多例分歧按 changelog 行号排序取 1..k（变更日志只追加不改写，
    # 故重跑得同一套 id → 幂等由既有「卡目录精确名」去重腿直接接管）。
    by_base = {}
    for c in cases:
        m = TS_SUFFIX_RE.match(c["gkey"])
        b = m.group("tid") if m else c["gkey"][:-len(".jsonl")]
        by_base.setdefault(b, []).append(c)
    for b in by_base:
        by_base[b].sort(key=lambda c: c["changelog_line"])
    res = []
    for base, bcases in sorted(by_base.items()):
        for idx, case in enumerate(bcases, 1):
            am = ARX_RE.search(base)
            if not am:
                log(f"[②] 跳过：无法从 `{case['gkey']}` 解析 arXiv id", quiet)
                continue
            arx = am.group(1)
            pref = f"kb-arbitrate-{base}-"
            div_key = (f"{case['gkey']}|{','.join(sorted(a['atom_id'] for a in case['atoms']))}"
                       f"|{','.join(sorted(case['cards']))}")
            card_id = f"{pref}{idx}"
            existing = _arbitrate_existing(pref, div_key, dd)
            if existing:
                log(f"[②] {card_id} 的同一分歧（{div_key[:60]}…）已由 `{existing}` 承载，"
                    f"跳过（幂等）", quiet)
                res.append({"ok": True, "card_id": existing, "skipped": True, "arxiv": arx})
                continue
            if card_id in dd["names_local"] or card_id in dd["names_gov"] \
                    or card_id in dd["legs"]["submitted"]:
                # 同名但分歧键不同：顺延到下一个空号（防与历史卡撞名）
                n = idx
                while f"{pref}{n}" in dd["names_local"] or f"{pref}{n}" in dd["names_gov"] \
                        or f"{pref}{n}" in dd["legs"]["submitted"]:
                    n += 1
                log(f"[②] {card_id} 已被他卡占用且分歧键不同，顺延为 {pref}{n}", quiet)
                card_id = f"{pref}{n}"
            cand_index = load_cand_index(case["gkey"])
            # 每张复核员卡的「登记时点」期望裁决（取自变更日志登记行，权威）
            want = {}
            for cid in case["cards"]:
                want[cid] = {a["atom_id"]: a["verdicts"].get(lineage_of(cid))
                             for a in case["atoms"]}
            atoms = []
            for a in case["atoms"]:
                rec = atom_record(con, a["atom_id"], cand_index)
                reviewers = {}
                for cid in case["cards"]:
                    rep, matched = pick_report(cid, want[cid])
                    if not rep:
                        continue
                    pay = rep.get("payload") or {}
                    vs = pay.get("verdicts") or pay.get("verifications") or []
                    for v in vs:
                        if v.get("atom_id") == a["atom_id"]:
                            reviewers[cid] = {"verdict": v.get("verdict"),
                                              "quote_check": v.get("quote_check"),
                                              "reason": v.get("reason"),
                                              "matched_registration": matched}
                            break
                rec["reviewers"] = reviewers
                rec["registered"] = dict(a["verdicts"])
                if not reviewers:
                    log(f"[②] 警告：{a['atom_id']} 找不到任一复核员回报，仍按登记行出卡", quiet)
                elif not all(r.get("matched_registration") for r in reviewers.values()):
                    log(f"[②] 提示：{a['atom_id']} 有复核员现时点结论与登记时点不同，"
                        f"卡内以登记时点为准并如实标注", quiet)
                atoms.append(rec)
            if not atoms:
                log(f"[②] 跳过 {card_id}：无分歧原子可仲裁", quiet)
                continue
            if dry_run:
                log(f"[②][dry-run] {card_id}：{arx} 分歧 {len(atoms)} 条，"
                    f"一致率 {case['agree']}/{case['compared']}={case['rate']}，"
                    f"登记行 变更日志.md:{case['changelog_line']}", quiet, to_file=False)
                res.append({"ok": True, "card_id": card_id, "arxiv": arx,
                            "sampled": len(atoms), "dry_run": True})
                continue
            abs_f, full_f, only_abs = cv.ensure_cache(arx, fetch=not no_scp)
            if not os.path.isfile(abs_f) or os.path.getsize(abs_f) < 5000:
                log(f"[②] {card_id} 拒发：证据缓存缺摘要 {arx}/abs.md（card-lint L4 必挂）", quiet)
                res.append({"ok": False, "card_id": card_id, "gate": ["L4 证据缓存缺摘要"],
                            "arxiv": arx})
                continue
            case = dict(case, only_abs=only_abs)
            prob = build_arbitrate_md(cv, arx, base, card_id, case, atoms)
            ids = only_arxiv_ids(prob)
            if ids != [arx]:
                prob = scrub_foreign_arxiv(prob, arx)
                ids = only_arxiv_ids(prob)
            if ids != [arx]:
                log(f"[②] {card_id} 拒发：证据源 arXiv id 不唯一 {ids}（card-lint L3 必挂）", quiet)
                res.append({"ok": False, "card_id": card_id, "gate": ["L3 证据源不唯一"],
                            "arxiv": arx})
                continue
            card_dir = os.path.join(SEEDS, card_id)
            os.makedirs(card_dir, exist_ok=True)
            open(os.path.join(card_dir, "problem.md"), "w", encoding="utf-8").write(prob)
            open(os.path.join(card_dir, "AGENTS.md"), "w", encoding="utf-8").write(
                build_kind_agents_md(card_id, "kb-arbitrate",
                                     f"arXiv:{arx}（摘要页 + HTML 全文，由你独立抓取）",
                                     len(atoms), extra=[
                    "- 本卡 type=**kb-arbitrate**：上面模板里的「验证任务」节（仅 type=kb-verify 适用）"
                    "**不适用**；你也**不是** B1/B2 中的任何一位。",
                    "- 分歧背景与两位复核员的结论已全文列在 problem.md；你的活是逐字重验后给终裁 "
                    "`final` + `rationale`，并用 `agree_with` 表态站哪边。",
                    "- **payload 不得带 `\"verify\": true`**，也不要以 kb-verify- 开头自称——"
                    "带了/写错会被厂内事件路由器当成验证卡消费并触发回流重派，违背本卡一次性设计。",
                    "- 回报键名：`payload.rulings`（数组），每条五字段 "
                    "`atom_id` / `final` / `quote_check` / `rationale` / `agree_with`，"
                    "缺一即整份被结构性拒收。",
                ]))
            json.dump({"title": f"{arx} 分歧仲裁（{len(atoms)} 条第三方终裁）",
                       "type": "kb-arbitrate", "est_load": "~20-40min CPU+web",
                       "reward": "工厂积分记账（sandbox_report 入 MES）",
                       "arbitrate": {"card_id": card_id, "task_id": base, "arxiv": arx,
                                     "candidates_file": case["gkey"],
                                     "atom_ids": [a["atom_id"] for a in atoms],
                                     "reviewer_cards": case["cards"],
                                     "agreement": f"{case['agree']}/{case['compared']}={case['rate']}",
                                     "changelog_line": case["changelog_line"],
                                     "divergence_key": div_key,
                                     "sampled": len(atoms)}},
                      open(os.path.join(card_dir, "meta.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            errs, notes = lint_gate(card_dir)
            scp_done = False
            if errs:
                log(f"[②] {card_id} 未过质量闸，拒发: {'; '.join(errs)}", quiet)
                res.append({"ok": False, "card_id": card_id, "gate": errs, "arxiv": arx})
                continue
            if not dry_run and not no_scp:
                scp_done, scp_why = scp_push(card_dir)
                if not scp_done:
                    # 2026-11-01 RT 修复：同①，推送失败如实记失败（分歧幂等键靠
                    # 本地 meta.json，残卡撤下才不会把该例永久遮蔽成「已承载」）。
                    log(f"[②] {card_id} scp 推送失败（卡已在本地，未上门户）: {scp_why}", quiet)
                    discard_undelivered(card_dir, "②", card_id, scp_why, quiet)
                    res.append({"ok": False, "card_id": card_id, "arxiv": arx,
                                "sampled": len(atoms), "scp": False, "push_failed": scp_why})
                    continue
            log(f"[②] 生成分歧仲裁卡 {card_id}：{arx} 分歧 {len(atoms)} 条，一致率 "
                f"{case['agree']}/{case['compared']}={case['rate']}，登记行 变更日志.md:"
                f"{case['changelog_line']}，闸 {'/'.join(notes) or 'green'}，scp={scp_done}", quiet)
            res.append({"ok": True, "card_id": card_id, "arxiv": arx, "sampled": len(atoms),
                        "scp": scp_done, "notes": notes})
    return res


def build_kind_agents_md(card_id, kind, evidence_desc, n, extra):
    """模板副本 + 卡专属契约节（插在自验清单之前，清单保持收尾；口径同
    cross-verify.build_agents_md 的插入位）。"""
    txt = ""
    if os.path.exists(TEMPLATE):
        txt = open(TEMPLATE, encoding="utf-8").read()
    block = (f"## 本卡专属：{card_id}\n"
             f"- 本卡 type=**{kind}**，证据源：{evidence_desc}；待处理 {n} 条，明细全部列在 "
             f"problem.md，以那张为准。\n")
    for line in extra:
        block += f"- {line}\n"
    block += "\n"
    marker = "## 自验清单"
    if marker in txt:
        head, tail = txt.split(marker, 1)
        return head + block + marker + tail
    return txt + "\n" + block


# --------------------------------------------------------------- ③ 蒸馏复核卡
def merge_pairs(con):
    """provenance 里已 apply 的 merge 对 → [{winner, loser, score, threshold, note, prov}]。"""
    rows = con.execute("SELECT seq, atom_id, event_type, detail, created_at FROM provenance "
                       "WHERE event_type IN ('merge','merged_from') ORDER BY seq").fetchall()
    pairs, seen = {}, set()
    for seq, aid, et, det, ca in rows:
        try:
            d = json.loads(det)
        except Exception:
            continue
        if et == "merge" and d.get("role") == "winner":
            loser = d.get("counterpart")
            key = (aid, loser)
            if key in seen:
                continue
            seen.add(key)
            pairs[key] = {"winner": aid, "loser": loser, "score": d.get("score"),
                          "threshold": d.get("threshold"), "note": "", "prov": []}
    # 补 merged_from 的人类可读理由与完整 provenance 摘要
    for seq, aid, et, det, ca in rows:
        try:
            d = json.loads(det)
        except Exception:
            continue
        for key, p in pairs.items():
            w, l = key
            if aid == w and et == "merged_from" and d.get("absorbed") == l:
                p["note"] = d.get("note") or ""
            if aid in (w, l) and et in ("merge", "merged_from"):
                p["prov"].append(f"seq={seq} {et} on {aid}: {json.dumps(d, ensure_ascii=False, sort_keys=True)}")
    out = []
    for key in sorted(pairs):
        p = pairs[key]
        p["prov"] = " | ".join(p["prov"])
        p["pair_id"] = f"{p['winner']}|{p['loser']}"
        out.append(p)
    return out


def build_distill_md(card_id, pair, wc, lc):
    score = pair.get("score")
    thr = pair.get("threshold")
    return f"""# 合并正确性蒸馏复核：`{pair['winner']}` ← `{pair['loser']}`

## 你是谁、为谁工作
你是 **D**：第三方沙箱 agent，与做合并的厂内管线无关。厂内知识库在 2026-10-28 的
重叠原子合并蒸馏里，把 `{pair['loser']}` 并入了 `{pair['winner']}`
（token 集合 Jaccard 相似度 {score} ≥ 阈值 {thr}）。运营者裁决：
**合并是否丢失信息，交第三方逐条复核**。你只做这一件事——比对赢家与输家的完整记录，
判断输家里有哪些信息在赢家身上找不到对应。你不是重新抽取、不是润色、不是补全。

## 证据源（KB 内部记录，本卡自含，无需联网）
本卡的证据就是知识库本身：两份原子的完整正文 + 这次合并的 provenance，已全文内嵌在
下面两个定界块里（`<!--KB-DISTILL:role:atom_id-->` … `<!--KB-DISTILL-END:role:atom_id-->`）。
块内的 text 就是该原子在 kb/kb.db `atoms.content` 字段的**逐字节原文**（含正文首行与
body 各行的序列化），一个字符都没改动。你**不需要**抓任何外部页面，也**不得**凭训练记忆
补充库里没有的内容；厂内 card-lint 的 L4′ 已对内嵌正文与 kb/kb.db 逐字节交叉验证过
（对不上即这张卡不会被发布）。

## 合并事实（provenance 摘要，机器可校）
<!--KB-DISTILL-META-->
atom_id: {pair['pair_id']}
winner: {pair['winner']}
loser: {pair['loser']}
score: {score}
reason: {pair.get('note') or '（provenance 未留 note）'}
provenance: {pair.get('prov') or '（无）'}
<!--KB-DISTILL-META-END-->

## 赢家原子（winner）全文
<!--KB-DISTILL:winner:{pair['winner']}-->
{wc}
<!--KB-DISTILL-END:winner:{pair['winner']}-->

## 输家原子（loser）全文
<!--KB-DISTILL:loser:{pair['loser']}-->
{lc}
<!--KB-DISTILL-END:loser:{pair['loser']}-->

## 合并理由（厂内 kb/merge.py 的判定口径，照录）
- 检出：FTS 召回候选 + token 集合 Jaccard 复核，score ≥ 阈值才留（同 source_corpus 的对优先）。
- 赢家判定：content 更长者赢；并列取引用更全者（attrs 里 links/urls/sources/citations/
  refs/relations/evidence 列表长度和 + paper 字段）；再并列取 id 更小者——**纯确定性规则，
  不判断哪条更真**。这正是要你复核的原因：赢家可能只是更长，不一定更全或更对。
- 输家处置：status→retired，赢家 attrs.merged_from 记入输家 id，双方各留一条 merge provenance。

## 复核规程（按序执行）
1. **逐字段比对**：把赢家与输家的正文、body 各键、relations、source（file/locator/quote）、
   kind、status 摆在一起看，列出输家有而赢家没有的每一项；比对 source.quote 时按
   **连续子串**口径逐字核对（改写、缩略、翻译都不算一致）。
2. **判信息丢失**：`no_loss`（输家信息在赢家身上全有对应，含被更长表述覆盖）/
   `info_loss`（输家有实质信息在赢家身上找不到：数字、条件、限定、反例、关系边、
   引用出处、测试设计等）/ `wrong_winner`（赢家判定本身错了——输家才该留）/
   `unverifiable`（卡内材料不足以判断）。
3. **列清单**：`lost_items` 逐条写丢失的具体内容（没有就空数组，不要写"无"占位）。
4. **给理由**：`rationale` ≤200 字，指向卡内正文/字段名，不指向外部记忆。

## 聚合规则（告知在先，不阻塞）
厂内按你的终裁统计 info_loss / wrong_winner 比例，作为合并蒸馏规则的回归信号；
本卡是一次性复核卡，不走回流重派线。

## 产出（POST /report 的 payload.schema，固定，不得增删字段）
复核结论放 **payload.findings**（数组）。本卡 type=kb-distill-review，
**payload 不得带 `"verify": true`**（带了会被厂内路由器误当成 kb-verify 验证卡消费）。

| 字段 | 类型 | 必填 | 合法值 / 写法 | 典型错法（写了就被拒） |
|------|------|------|---------------|------------------------|
| atom_id | string | 是 | 上面 META 块里的 winner 或 loser，原文照抄 | 自编短 id、只写编号 |
| role | string | 是 | `winner` / `loser` 之一 | 写"赢家"/"输家"中文 |
| final | string | 是 | `no_loss` / `info_loss` / `wrong_winner` / `unverifiable` 之一 | 大写、写 "ok"/"bad" |
| rationale | string | 是 | ≤200 字，指向卡内正文或字段名 | 空串、只写"同上" |
| lost_items | array | 是 | 字符串数组；确无丢失就给 `[]` | 给 `["无"]`、给对象 |

### 完整合法回报 JSON 示例（照这个结构写，winner/loser 各一条，顺序不限）
```json
{{"distill_review": true, "card_id": "{card_id}",
 "pair_id": "{pair['pair_id']}",
 "findings": [
   {{"atom_id": "{pair['winner']}", "role": "winner", "final": "no_loss",
    "rationale": "赢家正文覆盖输家全部 body 键与 relations，source.quote 同一句",
    "lost_items": []}},
   {{"atom_id": "{pair['loser']}", "role": "loser", "final": "info_loss",
    "rationale": "输家 relations 有一条 supportedBy 边在赢家 attrs 里找不到对应",
    "lost_items": ["relations: supportedBy → S009"]}}
 ],
 "evidence": {{"sources": [{{"name": "kb/kb.db", "sha256": "你复校时读到的库文件 sha256"}}]}}}}
```

## 回报前自检清单（逐条打勾再 POST；任一不过 = 白跑一轮算力）
- [ ] `payload.findings` 非空，winner 与 loser **各有一条**（共 2 条）
- [ ] 每条都含 `atom_id` / `role` / `final` / `rationale` / `lost_items` 五个字段
- [ ] 每个 `atom_id` 都能在上面 META 块里原文找到
- [ ] 每个 `final` 都是 `no_loss` / `info_loss` / `wrong_winner` / `unverifiable` 之一
- [ ] `lost_items` 是字符串数组；确无丢失就给 `[]`，不给 `["无"]`
- [ ] 每个 `rationale` 非空且指向卡内正文或字段名（不指向外部记忆）
- [ ] payload **没有** `"verify": true`（本卡不是验证卡）
"""


def gen_distill(con, cv, dd, dry_run, no_scp, quiet):
    pairs = merge_pairs(con)
    res = []
    for p in pairs:
        card_id = f"kb-distill-{p['winner']}-{p['loser']}"
        if card_id in dd["names_local"] or card_id in dd["names_gov"] \
                or card_id in dd["legs"]["submitted"]:
            log(f"[③] {card_id} 已存在（本地/gov/已回报），跳过（幂等）", quiet)
            res.append({"ok": True, "card_id": card_id, "skipped": True})
            continue
        wc = con.execute("SELECT content FROM atoms WHERE id=?", (p["winner"],)).fetchone()
        lc = con.execute("SELECT content FROM atoms WHERE id=?", (p["loser"],)).fetchone()
        if not wc or not lc:
            log(f"[③] 跳过 {card_id}：库内缺原子（winner={bool(wc)} loser={bool(lc)}）", quiet)
            res.append({"ok": False, "card_id": card_id,
                        "gate": ["L4′ 库内缺原子"], "note": "winner/loser 不在 kb.db"})
            continue
        wc, lc = wc[0] or "", lc[0] or ""
        if "```" in wc or "```" in lc or "<!--KB-DISTILL" in wc or "<!--KB-DISTILL" in lc:
            log(f"[③] 跳过 {card_id}：原子正文含定界符冲突，无法安全内嵌", quiet)
            res.append({"ok": False, "card_id": card_id,
                        "gate": ["L3′ 定界符冲突"], "note": "content 含 ``` 或 KB-DISTILL 标记"})
            continue
        prob = build_distill_md(card_id, p, wc, lc)
        if dry_run:
            log(f"[③][dry-run] {card_id}：score={p['score']} winner {len(wc)}B / "
                f"loser {len(lc)}B，provenance {len(p['prov'])}B", quiet, to_file=False)
            res.append({"ok": True, "card_id": card_id, "dry_run": True,
                        "score": p["score"]})
            continue
        card_dir = os.path.join(SEEDS, card_id)
        os.makedirs(card_dir, exist_ok=True)
        open(os.path.join(card_dir, "problem.md"), "w", encoding="utf-8").write(prob)
        open(os.path.join(card_dir, "AGENTS.md"), "w", encoding="utf-8").write(
            build_kind_agents_md(
                card_id, "kb-distill-review",
                "kb/kb.db 内部记录（problem.md 内嵌的赢家/输家原子全文 + merge provenance，"
                "无需联网）", 2, extra=[
                "- 本卡 type=**kb-distill-review**：上面模板里的「验证任务」节"
                "（仅 type=kb-verify 适用）与「证据唯一：只从 problem.md 指定的证据源抽取」"
                "的抽取条款**都不适用**——本卡不抽原子、不联网。",
                "- 证据就是 problem.md 里内嵌的两份原子全文 + merge provenance（定界块 "
                "`<!--KB-DISTILL:…-->`）；只依据卡内材料判断，不得凭训练记忆补充。",
                "- **payload 不得带 `\"verify\": true`**，也不要以 kb-verify- 开头自称——"
                "带了/写错会被厂内事件路由器当成验证卡消费并触发回流重派，违背本卡一次性设计。",
                "- 回报键名：`payload.findings`（数组），winner 与 loser 各一条，每条五字段 "
                "`atom_id` / `role` / `final` / `rationale` / `lost_items`，缺一即整份被结构性拒收。",
            ]))
        json.dump({"title": f"合并正确性蒸馏复核：{p['winner']} ← {p['loser']}",
                   "type": "kb-distill-review", "est_load": "~10-20min CPU only",
                   "reward": "工厂积分记账（sandbox_report 入 MES）",
                   "distill_review": {"card_id": card_id, "pair_id": p["pair_id"],
                                      "winner": p["winner"], "loser": p["loser"],
                                      "score": p["score"], "threshold": p["threshold"],
                                      "merge_note": p.get("note") or "",
                                      "provenance": p.get("prov") or "",
                                      "sampled": 2}},
                  open(os.path.join(card_dir, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        errs, notes = lint_gate(card_dir)
        scp_done = False
        if errs:
            log(f"[③] {card_id} 未过质量闸，拒发: {'; '.join(errs)}", quiet)
            res.append({"ok": False, "card_id": card_id, "gate": errs})
            continue
        if not dry_run and not no_scp:
            scp_done, scp_why = scp_push(card_dir)
            if not scp_done:
                # 2026-11-01 RT 修复：同①②，推送失败如实记失败，残卡撤下留待重推。
                log(f"[③] {card_id} scp 推送失败（卡已在本地，未上门户）: {scp_why}", quiet)
                discard_undelivered(card_dir, "③", card_id, scp_why, quiet)
                res.append({"ok": False, "card_id": card_id,
                            "scp": False, "push_failed": scp_why})
                continue
        log(f"[③] 生成蒸馏复核卡 {card_id}：score={p['score']} winner {len(wc)}B / "
            f"loser {len(lc)}B，闸 {'/'.join(notes) or 'green'}，scp={scp_done}", quiet)
        res.append({"ok": True, "card_id": card_id, "scp": scp_done, "notes": notes,
                    "score": p["score"]})
    return res


# --------------------------------------------------------------- selfcheck
def selfcheck():
    """对 task-seeds 上本批三类卡重跑 lint，并对蒸馏卡做一次独立于 lint 的库复校。"""
    cl = _load("cardlint", WS + "/tools/card-lint.py")
    con = ro_connect(KB_DB)
    pats = {"kb-verify-*r3": "kb-verify-", "kb-arbitrate-": "kb-arbitrate-",
            "kb-distill-": "kb-distill-"}
    total = bad = 0
    for label, pref in pats.items():
        if pref == "kb-verify-":
            dirs = [d for d in sorted(glob.glob(os.path.join(SEEDS, "kb-verify-*")))
                    if re.search(r"-\d+r3$", os.path.basename(d))]
        else:
            dirs = sorted(glob.glob(os.path.join(SEEDS, pref + "*")))
        for d in dirs:
            total += 1
            errs, notes = cl.lint_card(d, cache=CACHE, kb_db=KB_DB)
            if errs:
                bad += 1
                print(f"✗ {os.path.basename(d)}: {'; '.join(errs)}")
                continue
            # 蒸馏卡：独立复校（不依赖 lint 的正则，重解析一次）
            if os.path.basename(d).startswith("kb-distill-"):
                prob = open(os.path.join(d, "problem.md"), encoding="utf-8").read()
                mm = re.search(r"<!--KB-DISTILL-META-->(.*?)<!--KB-DISTILL-META-END-->",
                               prob, re.S)
                meta = dict(l.split(":", 1) for l in mm.group(1).strip().splitlines()
                            if ":" in l)
                meta = {k.strip(): v.strip() for k, v in meta.items()}
                for role in ("winner", "loser"):
                    aid = meta.get(role)
                    row = con.execute("SELECT content FROM atoms WHERE id=?",
                                      (aid,)).fetchone()
                    blk = re.search(
                        r"<!--KB-DISTILL:" + role + ":" + re.escape(aid) + r"-->\n(.*?)"
                        r"\n<!--KB-DISTILL-END:" + role + ":" + re.escape(aid) + r"-->",
                        prob, re.S)
                    if not row or not blk or blk.group(1) != (row[0] or ""):
                        bad += 1
                        print(f"✗ {os.path.basename(d)}: 独立复校失败 role={role} aid={aid}")
                        break
                else:
                    ev = con.execute("SELECT COUNT(*) FROM provenance WHERE event_type='merge' "
                                     "AND atom_id IN (?,?)",
                                     (meta.get("winner"), meta.get("loser"))).fetchone()[0]
                    print(f"✓ {os.path.basename(d)}  {' / '.join(notes)}"
                          f"（独立复校通过，merge provenance {ev} 行）")
                    continue
            else:
                print(f"✓ {os.path.basename(d)}  {' / '.join(notes)}")
    print(f"\nselfcheck: 共 {total} 卡，硬伤 {bad}")
    return bad


# --------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="KB 存量质量工序卡生成器（三类一次性卡）")
    ap.add_argument("--kind", default="all", choices=["all", "verify", "arbitrate", "distill"],
                    help="生成哪一类（默认 all）")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP,
                    help=f"① 选源窗口深度：verified 原子数排名区间 [start, start+N) "
                         f"的论文数（默认 {DEFAULT_TOP}；支持 --top 200）")
    ap.add_argument("--n", type=int, default=DEFAULT_N,
                    help=f"① 每张复核卡裁决条数（默认 {DEFAULT_N}）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只算候选与卡 id，不建卡不抓证据不 scp 不落日志")
    ap.add_argument("--no-scp", action="store_true", help="只落本地卡，不推 gov")
    ap.add_argument("--force", action="store_true", help="无视 STOP 熔断（慎用）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--advance-window", action="store_true",
                    help="允许选源窗口在耗尽后下移一段（排期轮次用；手工重跑不加=不推进）")
    ap.add_argument("--window-start", type=int, default=None,
                    help="显式指定选源窗口起点（调试/DRY 用；默认取状态文件记录）")
    ap.add_argument("--selfcheck", action="store_true",
                    help="对 task-seeds 上本批卡重跑 lint + 独立库复校（只读）")
    a = ap.parse_args()

    if a.selfcheck:
        return 1 if selfcheck() else 0

    for s in STOPS:
        if os.path.exists(s) and not a.force:
            print(f"STOP 熔断在位（{s}），拒发质量工序卡（--force 才覆盖）", file=sys.stderr)
            return 2

    cv = _load("crossverify", WS + "/tools/cross-verify.py")
    con = ro_connect(KB_DB)
    dd = dedup_legs()
    if a.top < 1:
        print("--top 需 ≥1", file=sys.stderr)
        return 2
    log(f"quality-cards 起（kind={a.kind} top={a.top} n={a.n} dry_run={a.dry_run} "
        f"no_scp={a.no_scp} advance_window={a.advance_window} "
        f"window_start={'auto' if a.window_start is None else a.window_start} "
        f"gov_reachable={dd['gov_reachable']}）", a.quiet,
        to_file=not a.dry_run)
    log("去重四腿：evidence-cache {e} + task-seeds {t} + gov {g} + submitted {s} = {u} 个 id；"
        "本地卡目录 {nl} 个 / gov 卡目录 {ng} 个".format(
            e=len(dd["legs"]["evidence-cache"]), t=len(dd["legs"]["task-seeds"]),
            g=len(dd["legs"]["gov"]), s=len(dd["legs"]["submitted"]), u=len(dd["used"]),
            nl=len(dd["names_local"]), ng=len(dd["names_gov"])), a.quiet,
        to_file=not a.dry_run)

    out = {}
    if a.kind in ("all", "verify"):
        out["verify"] = gen_verify_r3(con, cv, dd, a.top, a.n, a.dry_run, a.no_scp,
                                      a.force, a.quiet, advance=a.advance_window,
                                      window_start=a.window_start)
    if a.kind in ("all", "arbitrate"):
        out["arbitrate"] = gen_arbitrate(con, cv, dd, a.dry_run, a.no_scp, a.quiet)
    if a.kind in ("all", "distill"):
        out["distill"] = gen_distill(con, cv, dd, a.dry_run, a.no_scp, a.quiet)

    summary = {}
    for k, v in out.items():
        made = [x for x in v if x.get("ok") and not x.get("skipped") and not x.get("dry_run")]
        skipped = [x for x in v if x.get("skipped")]
        dry = [x for x in v if x.get("dry_run")]
        failed = [x for x in v if not x.get("ok")]
        summary[k] = {"generated": len(made), "skipped_existing": len(skipped),
                      "dry_run_planned": len(dry), "failed": len(failed),
                      "cards": [x.get("card_id") for x in made]}
    # 2026-11-01 RT 修复：旧判据 `not x.get("failed")` 查的是结果项里不存在的键，
    # 恒真 → 任何失败（过闸挂/推送失败）顶层 ok 都谎报 true。改为如实反映各项 ok。
    ok_all = all(x.get("ok") for k in out for x in out[k])
    print(json.dumps({"ok": ok_all,
                      "dry_run": a.dry_run, "summary": summary}, ensure_ascii=False, indent=1))
    # 2026-11-03 RT 修复（质量卡轮换腿的成败判据）：退出码此前恒 0——逐项失败只进
    # JSON 的 ok/summary.failed，进程却「成功」返回；唯一在役调用者
    # factory-scheduler.py:_quality_cards_supply 以 returncode 判成败 → 腿全败也不红
    # （acts 恒 qc:+、变更日志恒记「已触发：}」）。口径同 report-feeder 顶层失败
    # exit=3（report-feeder.py:679）、STOP 熔断/参数非法 exit=2（本文件 :1256/:1263）：
    # 有失败项即非 0 退出（3），stdout 的 JSON 照旧输出（调用方仍可解析逐项计数）。
    if not ok_all:
        n_failed = sum((summary.get(k) or {}).get("failed", 0) for k in summary)
        print(f"质量卡工序失败 {n_failed} 项（逐项见上 JSON summary.failed）", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
