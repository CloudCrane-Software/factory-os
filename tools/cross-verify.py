#!/usr/bin/env python3
"""cross-verify.py — 沙箱交叉验证任务卡生成器（运营者裁决：A 的工作交给 B 验证）

背景：A（抽取沙箱）回报的知识原子已过厂内机械验谎（sandbox-harvester 三级校验），
但机械验谎只能证明「quote 是证据文本的连续子串」，不能证明「这条原子本身成立」。
运营者裁决：A 的工作交给 B 验证——另派一位独立沙箱 agent 逐条裁决。

2026-10-29 验证放大（战役优化批①）：一张抽取的产出由 k 个沙箱独立复核（token 不
值钱，质量值钱）。同一份候选（同一 atom 集）生成 k 张卡，各用不同抽样种子与不同
复核员视角提示语（r1 偏逐字核验、r2 偏语义核对），提示语差异化提高独立性；
event-router 聚合侧对同一 atom 集记录跨卡一致率并检测分歧（见该文件聚合处）。

输入：一份候选 JSONL（默认 kb-seed/sandbox/sbx-*.jsonl；sandbox-harvester.py
      实际产出的是 <task_id>-<ts>.jsonl，同样接受）+ 该文的 arXiv id。
输出：门户验证任务卡 kb-seed/sandbox/task-seeds/kb-verify-<原taskid>-<attempt>[r<j>]/
        problem.md（含 12 条待裁决原子 + 固定 payload schema）
        AGENTS.md（_AGENTS_template.md 副本，含「验证任务」契约节）
        meta.json（type=kb-verify）
      过 tools/card-lint.py 质量闸后 scp 到 gov（root@gov-host.invalid:/opt/company/af-jobs/data/tasks/）。
      未过闸的拒发卡目录就地删除（2026-11-02 RT：不得残留 task-seeds/——会被
      card-lint --all 扫成硬伤、并占住副本血线的 attempt 位误触发回流的在飞判定）。

卡 id 方案（不得与回流 attempt 计数冲突）：
  · kb-verify-<base>-<attempt>r<j> —— <base> 为原 task_id（可含 -r2/-r3 抽取线
    重派基名），<attempt> 为验证卡轮次，r<j> 为副本号（r1/r2/…，无横线，故 attempt
    计数不会被副本号顶掉；两段都可被消费方正则无歧义拆出）。
  · <attempt> 按「同 task_id 同副本血线」取最大轮次 +1：k 张副本各自独立计轮次与
    重发上限，互不挤占序号；同一批原子重发时 attempt+1（回流语义不变）。
  · --replicas 1（无 --replica）走既有单卡路径：id 无 r 后缀、种子口径、meta 字段、
    problem/AGENTS 内容与 stdout 末行 JSON 均与改动前逐字节一致（对照验证用）。

用法：
  python3 tools/cross-verify.py <candidates.jsonl> <arxiv_id> [--n 12] [--seed S]
          [--replicas K] [--replica J] [--seeds-dir DIR] [--no-fetch] [--no-scp]
          [--dry-run] [--quiet]
  --n        每张卡裁决的原子条数（默认 12；候选不足则全上并在结果里标注）
  --seed     随机抽样基础种子（默认由 arxiv id + 卡轮次派生，重跑可复现；换种子换抽样）
  --replicas 复制份数 k（默认 2）：同一 atom 集生成 k 张卡，各用不同抽样种子与不同
            复核员视角提示语；k=1 为既有单卡路径（字节级不变）
  --replica  只生成第 J 号副本（id 带 r{J}，回流重发用；与 --replicas>1 互斥）。
            显式 --seed 时该种子直接用于本副本（与上游同 seed = 同一批原子）
  --no-fetch 不补抓 evidence-cache（离线/干跑用）
  --no-scp   只生成本地卡，不推 gov
  --dry-run  同 --no-scp，且不写 .cross-verify-state.json / 不落日志
stdout 末行：JSON —— event-router.py 直接解析这行。
  · 单卡路径（--replicas 1 且无 --replica）：{ok, card_id, card_dir, task_id, arxiv,
    atoms_total, sampled, seed, atom_ids, gate, scp, note}（与改动前同形）
  · 多副本路径：{ok, replicas, cards: [{card_id, card_dir, replica, perspective,
    sampled, seed, atom_ids, gate, scp, note, ok}, …], task_id, arxiv, atoms_total, note,
    card_id/card_dir/sampled/seed/atom_ids/gate/scp（首张卡的兼容键：在役老版
    event-router 重启前按单卡口径消费，缺键会 KeyError；新码走 cards 数组）}

纪律：gov 只读+推送任务卡（不改 af 仓）；STOP 熔断（kb-seed/sandbox/.router-STOP
      在位即拒发，--force 才覆盖）；日志落盘 kb-seed/sandbox/cross-verify.log。
回滚：删 task-seeds/kb-verify-* 目录 + gov 上同名任务目录。"""
import argparse
import glob
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

WS = "/home/pan-ding/workspace/agent黑灯工厂"
SEEDS = WS + "/kb-seed/sandbox/task-seeds"
CACHE = WS + "/kb-seed/sandbox/evidence-cache"
LOG = WS + "/kb-seed/sandbox/cross-verify.log"
STOP = WS + "/kb-seed/sandbox/.router-STOP"
GOV = "root@gov-host.invalid"
GOV_TASKS = "/opt/company/af-jobs/data/tasks/"
TEMPLATE = SEEDS + "/_AGENTS_template.md"

VERDICTS = ["uphold", "refute", "unverifiable"]
KIND_VOCAB = ["claim", "concept", "procedure", "evidence_record", "failure_pattern", "evaluator"]
DEFAULT_N = 12
DEFAULT_REPLICAS = 2
UPHOLD_THRESHOLD = 0.8

# 收割方产出 <task_id>-YYYYMMDD-HHMMSS.jsonl；剥掉时间戳即原 task_id
TS_SUFFIX_RE = re.compile(r"^(?P<tid>.+?)-\d{8}-\d{6}\.jsonl$")
ARX_RE = re.compile(r"(\d{4}\.\d{4,5})")
# 既有卡目录名的轮次/副本段：<attempt> 或 <attempt>r<replica>（老格式无 r 后缀）
CARD_ATTEMPT_RE = re.compile(r"^(?P<attempt>\d+)(?:r(?P<replica>\d+))?$")

# 副本视角提示语（差异化提高独立性）：r1 偏逐字核验、r2 偏语义核对；k>2 兜底均衡。
# 文案刻意不含 arXiv id 形态（card-lint L3 证据源唯一）与任何密钥/内网串（L8）。
PERSPECTIVES = {
    1: ("逐字核验",
       "你是同一批候选的第 {j}/{k} 张独立复核副本，本卡视角：**逐字核验**。"
       "你把每条原子当作「引文声明」逐字符核对：A 的 source.quote 是否在你独立抓到的"
       "证据文本里作为连续子串逐字出现（缩略、改写、翻译、凭记忆补写，一律 "
       "quote_check=false 并在 reason 里指出差异）；A 记的 locator 指的节/段是否真的"
       "包含该句；数字、单位、比较级、时态逐个字符比对，一个字符不同就是不同。"
       "你的强项是把「引文层」的瑕疵抓出来。"),
    2: ("语义核对",
       "你是同一批候选的第 {j}/{k} 张独立复核副本，本卡视角：**语义核对**。"
       "quote_check 仍要如实填，但你把火力集中在「命题层」：原子说的这件事，你抓到的"
       "证据是否真的支持——数字口径是否一致、因果方向有没有被写反、相关性有没有被写成"
       "因果、单点实验有没有被写成普适规律、别的节/别的对象的结果有没有被张冠李戴。"
       "quote 逐字出现但命题被夸大或写反，同样判 refute。你的强项是把「断言层」的"
       "瑕疵抓出来。"),
}


def perspective_for(j, k):
    """第 j 号副本（共 k 张）的视角提示语：(label, text)；无副本概念时返回 None。"""
    label, text = PERSPECTIVES.get(
        j, ("独立复核",
            "你是同一批候选的第 {j}/{k} 张独立复核副本，本卡视角：**独立复核**。"
            "逐条独立裁决，quote_check 与命题层并重，一条不漏、一条不多。"))
    return label, text.format(j=j, k=k)


def next_attempt(seeds_dir, task_id, replica):
    """同 task_id 同副本血线的下一轮次 = 既有卡最大 attempt + 1（无则 1）。

    血线 = r<j> 后缀相同的卡（老格式无后缀 = 单卡血线，replica=None）。k 张副本
    各自独立计轮次与重发上限，故互不挤占序号；重发时 attempt+1（回流语义不变）。
    """
    best = 0
    prefix = f"kb-verify-{task_id}-"
    for d in glob.glob(os.path.join(seeds_dir, prefix + "*")):
        m = CARD_ATTEMPT_RE.match(os.path.basename(d)[len(prefix):])
        if not m:
            continue
        r = int(m.group("replica")) if m.group("replica") else None
        if r != replica:
            continue
        best = max(best, int(m.group("attempt")))
    return best + 1


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sh(cmd, timeout=90):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


def scp_push(card_dir):
    """推送一张验证卡到 gov，返回 (是否送达, 失败原因)。

    2026-11-01 RT 修复：旧码 `r = sh("scp …"); scp_done=True; if r:`——sh 只回
    stdout，而 scp 失败走 stderr、stdout 恒空 → 失败判据永不触发，gov 不可达也记
    scp=true（event-router 消费侧随之把卡标 status=open，B 永无回报、A→B 静默
    停摆）。此处以退出码为准（BatchMode + ConnectTimeout=10 + 60s 双超时，口径同
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


def parse_task_id(path):
    """候选文件名 → 原 task_id（剥掉收割方打的时间戳）。"""
    base = os.path.basename(path)
    m = TS_SUFFIX_RE.match(base)
    return m.group("tid") if m else base[:-len(".jsonl")] if base.endswith(".jsonl") else base


def arx_from_task_id(task_id):
    m = ARX_RE.search(task_id)
    return m.group(1) if m else ""


def load_candidates(path):
    """读候选 JSONL，返回 (rows, skipped)。缺 candidate_id 的行跳过并计数。"""
    rows, skipped = [], 0
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                skipped += 1
                continue
            cid = j.get("candidate_id") or j.get("atom_id")
            if not cid or not (j.get("text") or "").strip():
                skipped += 1
                continue
            rows.append(j)
    return rows, skipped


def ensure_cache(arx, fetch=True):
    """保证 evidence-cache/<arx>/abs.md 存在（card-lint L4 要 >5KB）。
    返回 (abs_path, full_path, only_abs)。fetch=False 时不联网。"""
    d = os.path.join(CACHE, arx)
    os.makedirs(d, exist_ok=True)
    abs_f, full_f = os.path.join(d, "abs.md"), os.path.join(d, "full.md")
    if fetch:
        if not os.path.exists(abs_f):
            sh(f"curl -sL --max-time 60 https://arxiv.org/abs/{arx} -o {abs_f}", timeout=90)
        if not os.path.exists(full_f):
            sh(f"curl -sL --max-time 90 https://arxiv.org/html/{arx} -o {full_f}", timeout=120)
    only_abs = False
    try:
        if not os.path.exists(full_f) or os.path.getsize(full_f) < 2000:
            only_abs = True
            if os.path.exists(full_f):
                os.rename(full_f, os.path.join(d, "full.unavailable.html"))
    except OSError:
        only_abs = True
    return abs_f, full_f, only_abs


def lint(card_dir):
    """card-lint 质量闸（fail-closed：闸自身异常也视为不过）。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cardlint", WS + "/tools/card-lint.py")
        cl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cl)
        errs, notes = cl.lint_card(card_dir)
        return errs, notes
    except Exception as e:
        return [f"质量闸自身异常（fail-closed）: {e}"], []


def _cell(s, limit=300):
    """markdown 表格单元格净化：去换行、转义竖线、超长截断。"""
    s = (s or "").replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()
    if len(s) > limit:
        s = s[:limit] + " …(截断)"
    return s


def _example_verdicts(atoms, limit=3):
    """完整合法回报示例的 3 条 verdict：三种裁决各一条，quote_check 的 true/false 各出现一次。

    取本卡真实 atom_id（前 limit 条），让示例可以照抄；候选不足时用占位串兜底。
    """
    picks = [("uphold", True, "§3.1: 原文 …，与原子表述一致，无过度断言"),
             ("refute", True, "§4.2: 原文数字为 …，与原子不符"),
             ("unverifiable", False, "抓到的全文无该节，摘要亦未提及，无法判断")]
    out = []
    for i, (vd, qc, rs) in enumerate(picks[:limit]):
        aid = atoms[i]["atom_id"] if i < len(atoms) else "<上表atom_id>"
        out.append(f'   {{"atom_id": "{aid}", "verdict": "{vd}", '
                   f'"quote_check": {"true" if qc else "false"},\n'
                   f'    "reason": "{rs}"}}')
    return ",\n".join(out)


def build_problem_md(arx, task_id, card_id, atoms, atoms_total, only_abs, threshold,
                     perspective=None):
    n = len(atoms)
    src_desc = (
        "1. 摘要页：https://arxiv.org/abs/" + arx + " —— **该文 arXiv 未提供 HTML 全文**，"
        "全部 quote 只能取自摘要页原文\n"
        if only_abs else
        "1. 摘要页：https://arxiv.org/abs/" + arx + "\n"
        "2. 全文 HTML（优先）：https://arxiv.org/html/" + arx + "\n")
    rows = []
    for i, a in enumerate(atoms, 1):
        src = a.get("source") or {}
        rows.append(
            f"| {i} | `{_cell(a['atom_id'], 80)}` | {_cell(a.get('kind'), 40)} | "
            f"{_cell(a.get('text'), 120)} | {_cell(src.get('locator'), 60)} | "
            f"{_cell(src.get('quote'), 300)} |")
    table = "\n".join(rows)
    ex_block = _example_verdicts(atoms)
    # 多副本卡的视角段（差异化提示语，提高 k 张卡之间的独立性）；单卡路径不注入，
    # 保持与改动前逐字节一致。
    persp_block = ""
    if perspective:
        label, text = perspective
        persp_block = f"## 本卡视角：{label}\n{text}\n\n"
    return f"""# {arx} 知识原子交叉验证（A 报 → B 验）

## 你是谁、为谁工作
你是 **B**：另一位独立沙箱 agent。A 已经抽取并上报了这批知识原子，厂内机械验谎
（quote 逐字回查）已过；运营者裁决：**A 的工作交给 B 验证**。你的职责是逐条裁决，
不是重新抽取、不是润色、不是补全。

## 证据源（唯一，必须由你独立抓取）
{src_desc}把抓到的内容存为本地文件 wikiskill 同款证据：abs.md 与 full.md（若可得），
并计算 sha256 写进回报的 evidence.sources。**只信任你自己抓到的文本**：A 的结论、
A 的引文、A 的 locator 都只是待检对象，不得当作证据。

{persp_block}## 待裁决原子（共 {n} 条，逐条裁决，一条不漏、一条不多）
A 报共 {atoms_total} 条原子，机器随机指定下列 {n} 条给你（kind 取自词表
{"|".join(KIND_VOCAB)}，你不必也不应改判 kind；原子的 source/relations 字段本次不裁决）。

| # | atom_id | kind | text | A 记的 locator | A 的 source.quote（≤120字逐字引） |
|---|---------|------|------|----------------|-----------------------------------|
{table}

## 裁决词表（verdict，只用这三个词）
- **uphold**：该原子在你独立抓到的证据中成立，且表述与证据不矛盾、无过度断言。
- **refute**：该原子与你抓到的证据矛盾——含数字不符、张冠李戴、把可能性写成结论、
  把单点实验写成普适规律。
- **unverifiable**：证据不可得或不足以判断（例：该节在你抓到的全文里不存在）。
  unverifiable 不是免责通道：整份回报 unverifiable 超过 2 条即按未通过处理。

**quote_check**：A 的 source.quote 是否在你抓到的证据文本中作为**连续子串**逐字出现
（true/false）。A 的 quote 已过厂内机械回查，但你仍要独立复核——引文被改写、缩略、
翻译或凭记忆补写，一律 false，并在 reason 里指出差异。

## 聚合规则（厂内路由器自动执行，告知在先）
uphold 率 = uphold 条数 / 本次裁决条数（unverifiable 计入分母，从严）。
≥ {threshold:.2f} → 该批候选入登记库 verified；否则整批 rejected 并自动重派第 3 轮。
你的 quote_check 全为 false 时，该验证卡作废不计（防摆烂），请勿故意全 false。

## 产出（POST /report 的 payload.schema，固定，不得增删字段）
裁决清单放 **payload.verdicts**（数组）。`verdicts` 与 `verifications` 是同义别名，
厂内收割方与路由器两个校验口都认这两种写法——**任选其一，不要同时写两个键**
（万一同时写，以 verdicts 为准）。

### verdicts 逐字段说明（数组里每个元素四个字段，缺任何一个即整份被结构性拒收）
| 字段 | 类型 | 必填 | 合法值 / 写法 | 典型错法（写了就被拒） |
|------|------|------|---------------|------------------------|
| atom_id | string | 是 | 上表出现过的 atom_id，原文照抄（含 `sbx-` 前缀） | 自编短 id、漏前缀、拼错一位 |
| verdict | string | 是 | 小写 `uphold` / `refute` / `unverifiable` 三词之一 | 写中文"成立"、大写、带句点、写 "likely true" |
| quote_check | boolean | 是 | JSON 布尔 `true` / `false` | 字符串 `"true"`、`1`/`0`、`yes`/`no` |
| reason | string | 是 | ≤80 字，写「证据位置（节名/段落）+ 依据」 | 空串、只写"同上"、不指向证据 |

### 完整合法回报 JSON 示例（3 条 verdict；照这个结构把上表 {n} 条写满，顺序不限）
```json
{{"verify": true, "card_id": "{card_id}", "arxiv": "{arx}",
 "verdicts": [
{ex_block}
 ],
 "evidence": {{"sources": [{{"name": "abs.md", "sha256": "你自己抓取的abs.md的sha256"}},
                           {{"name": "full.md", "sha256": "你自己抓取的full.md的sha256"}}],
              "sections_missing": []}}}}
```
（示例里的 atom_id 就是本卡待裁决原子；实际回报必须逐一覆盖上表全部 {n} 条，
`evidence.sources` 只记你自己抓到的文件及其 sha256，不是抄 A 的。）

## 回报前自检清单（逐条打勾再 POST；任一不过 = 白跑一轮算力）
- [ ] `payload.verdicts` 是非空数组，条数正好等于上表的 {n} 条（一条不漏、一条不多）
- [ ] 每一条都含 `atom_id` / `verdict` / `quote_check` / `reason` 四个字段
- [ ] 每个 `verdict` 都是 `uphold` / `refute` / `unverifiable` 之一（小写英文原词）
- [ ] 每个 `quote_check` 都是 JSON 布尔 `true`/`false`（不是字符串、不是 1/0）
- [ ] 每个 `atom_id` 都能在上表里原文找到（拼错一位 → 路由器不认识 → 整份忽略）
- [ ] 每个 `reason` 非空且指向我自己抓到的证据位置（节名/段落）
- [ ] `unverifiable` 不超过 2 条；`quote_check` 没有全为 false
- [ ] 抓不到的章节如实进 `evidence.sections_missing`，**绝不凭训练记忆编造论文内容**
"""


def build_agents_md(card_id, arx, n, perspective=None):
    """模板副本 + 卡专属的验证任务节（插在自验清单之前，清单保持收尾）。"""
    txt = ""
    if os.path.exists(TEMPLATE):
        txt = open(TEMPLATE, encoding="utf-8").read()
    block = (f"## 本卡专属：{card_id}\n"
             f"- 待裁决 {n} 条原子的 atom_id、kind、text、locator、A 的 quote 全部列在 problem.md 的表里，以那张表为准。\n"
             f"- 证据源唯一：https://arxiv.org/abs/{arx}（该文无 HTML 全文时仅此一源）。\n"
             f"- 回报 payload 必须带 \"verify\": true 与 card_id=\"{card_id}\"，否则厂内路由器不认。\n"
             f"- 裁决只写 uphold / refute / unverifiable 三个词；quote_check 只写 true/false。\n"
             f"- **裁决清单键名**：放 `payload.verdicts`（数组，首选）；`verdicts` 与 `verifications` 是同义别名，"
             f"厂内收割方与路由器两个校验口都认，任选其一，**不要同时写两个键**。\n"
             f"- **verdicts 每条四个字段全部必填**：`atom_id`（上表 atom_id 原文照抄）/ "
             f"`verdict`（uphold|refute|unverifiable 小写原词）/ `quote_check`（JSON 布尔 true/false）/ "
             f"`reason`（≤80字，指向你抓到的证据位置）。缺任何一个字段 = 整份被结构性拒收。\n"
             f"- **POST 前必做**：先过 problem.md 的「回报前自检清单」，并照其中的「完整合法回报 JSON 示例"
             f"（3 条 verdict）」结构写满全部 {n} 条。\n\n")
    if perspective:
        label, _text = perspective
        block += (f"- 本卡是同一批候选的独立复核副本（视角：{label}）；同批另有其他副本由不同沙箱"
                  f"独立复核，厂内路由器会聚合同一 atom 集的跨卡一致率并检测分歧——你只管按本卡"
                  f"视角独立裁决，不必猜测别的副本会怎么判。\n\n")
    marker = "## 自验清单"
    if marker in txt:
        head, tail = txt.split(marker, 1)
        return head + block + marker + tail
    return txt + "\n" + block


def main():
    ap = argparse.ArgumentParser(description="生成沙箱交叉验证任务卡（A 报 → B 验）")
    ap.add_argument("jsonl", help="已过机械验谎的候选 JSONL（sbx-*.jsonl 或 <task>-<ts>.jsonl）")
    ap.add_argument("arxiv", nargs="?", default="", help="arXiv id（NNNN.NNNNN）；缺省从 task_id 推")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help=f"每卡裁决条数（默认 {DEFAULT_N}）")
    ap.add_argument("--seed", default="", help="随机抽样基础种子（默认由 arxiv+卡轮次派生）")
    ap.add_argument("--replicas", type=int, default=None,
                    help=f"复制份数 k（默认 {DEFAULT_REPLICAS}）：同一 atom 集生成 k 张卡，"
                         f"各用不同抽样种子与不同复核员视角；1=既有单卡路径（字节级不变）")
    ap.add_argument("--replica", type=int, default=0,
                    help="只生成第 J 号副本（id 带 r{J}；回流重发用，与 --replicas>1 互斥）")
    ap.add_argument("--seeds-dir", default=SEEDS)
    ap.add_argument("--no-fetch", action="store_true", help="不补抓 evidence-cache")
    ap.add_argument("--no-scp", action="store_true", help="只生成本地卡，不推 gov")
    ap.add_argument("--dry-run", action="store_true", help="等价 --no-scp 且不落日志/状态")
    ap.add_argument("--force", action="store_true", help="无视 STOP 熔断（慎用）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    k = DEFAULT_REPLICAS if a.replicas is None else a.replicas
    if a.replica:
        if a.replicas not in (None, 1):
            out(ok=False, error=f"--replica {a.replica} 与 --replicas {a.replicas} 互斥"
                                f"（回流只重发单张副本）")
            return 2
        if a.replica < 1:
            out(ok=False, error=f"--replica 必须 ≥1：{a.replica}")
            return 2
        k = 1
    elif k < 1:
        out(ok=False, error=f"--replicas 必须 ≥1：{k}")
        return 2

    def out(**kw):
        if not a.quiet:
            print(json.dumps(kw, ensure_ascii=False))

    if os.path.exists(STOP) and not a.force:
        out(ok=False, error=f"STOP 熔断在位（{STOP}），拒发验证卡")
        return 2
    if not os.path.isfile(a.jsonl):
        out(ok=False, error=f"候选文件不存在: {a.jsonl}")
        return 2

    task_id = parse_task_id(a.jsonl)
    arx = a.arxiv or arx_from_task_id(task_id)
    if not ARX_RE.fullmatch(arx or ""):
        out(ok=False, error=f"arXiv id 无法解析: {arx!r}（用法: cross-verify.py <jsonl> <NNNN.NNNNN>）")
        return 2

    rows, skipped = load_candidates(a.jsonl)
    if not rows:
        out(ok=False, error=f"候选 JSONL 无有效行: {a.jsonl}（跳过 {skipped} 行）")
        return 2

    # 生成前守卫（2026-10-29）：只对 registry 仍是 candidate 的原子发卡——已全部 admit 的
    # atom 集不再出新验证卡（防空转浪费沙箱 token）。候选不足 n 的 1/3 时整集跳过。
    try:
        import sqlite3 as _sq
        _reg = os.path.join(os.path.dirname(os.path.abspath(a.jsonl)), "..", "registry.db")
        _reg = os.path.normpath(_reg)
        if os.path.isfile(_reg):
            _ids = [r.get("candidate_id") or r.get("atom_id") for r in rows]
            _q = ",".join("?" * len(_ids))
            _known = {x[0] for x in _sq.connect(_reg).execute(
                f"SELECT id FROM candidates WHERE status='candidate' AND id IN ({_q})", _ids)}
            _before = len(rows)
            rows = [r for r in rows if (r.get("candidate_id") or r.get("atom_id")) in _known]
            if len(rows) < max(2, a.n // 3):
                out(ok=True, skipped_verify=True, note=(
                    f"守卫跳过：registry 候选仅 {len(rows)}/{_before}（其余已 admit/非 candidate），"
                    "不再发验证卡"), task_id=task_id)
                return 0
    except Exception as _e:
        log(f"候选状态守卫异常（放行走旧逻辑）: {_e}")

    n = max(1, min(a.n, len(rows)))
    _, _, only_abs = ensure_cache(arx, fetch=not a.no_fetch)
    # 副本清单：--replica J → 只发 J；否则 1..k。血线（replica）为 None 表示老格式单卡。
    single_legacy = (not a.replica and k == 1)  # 既有单卡路径：id/种子/meta/stdout 全不变
    replica_idx = [a.replica] if a.replica else list(range(1, k + 1))
    results = []
    for j in replica_idx:
        lineage = j if (k > 1 or a.replica) else None
        attempt = next_attempt(a.seeds_dir, task_id, lineage)
        card_id = f"kb-verify-{task_id}-{attempt}" + (f"r{j}" if lineage is not None else "")
        # 种子口径：单卡路径与改动前一致（sha256(arx|task_id|attempt)）；多副本按 base 派生
        # 不同种子（独立性）；--replica J 显式带 --seed 时直接用（同 seed = 同一批原子）。
        base_seed = a.seed or hashlib.sha256(f"{arx}|{task_id}|{attempt}".encode()).hexdigest()[:12]
        if a.replica:
            seed = a.seed or hashlib.sha256(f"{base_seed}|r{j}".encode()).hexdigest()[:12]
        elif k == 1:
            seed = base_seed
        else:
            seed = hashlib.sha256(f"{base_seed}|r{j}".encode()).hexdigest()[:12]
        rng = random.Random(seed)
        picked = rng.sample(rows, n)
        atoms = []
        for r in picked:
            cid = r.get("candidate_id") or r.get("atom_id")
            atoms.append({"atom_id": cid, "kind": r.get("kind"), "text": r.get("text"),
                          "source": r.get("source") or {}})

        card_dir = os.path.join(a.seeds_dir, card_id)
        os.makedirs(card_dir, exist_ok=True)
        persp = perspective_for(j, len(replica_idx)) if lineage is not None else None
        open(os.path.join(card_dir, "problem.md"), "w", encoding="utf-8").write(
            build_problem_md(arx, task_id, card_id, atoms, len(rows), only_abs, UPHOLD_THRESHOLD, persp))
        open(os.path.join(card_dir, "AGENTS.md"), "w", encoding="utf-8").write(
            build_agents_md(card_id, arx, n, persp))
        verify_block = {"card_id": card_id, "task_id": task_id, "arxiv": arx,
                        "candidates_file": os.path.basename(a.jsonl),
                        "atoms_total": len(rows), "sampled": n, "seed": seed,
                        "uphold_threshold": UPHOLD_THRESHOLD,
                        "atom_ids": [x["atom_id"] for x in atoms]}
        if lineage is not None:  # 多副本/回流单副本卡才带 replica 元数据（k=1 保持旧字节）
            verify_block.update({"replica": j, "replicas": len(replica_idx),
                                 "perspective": persp[0], "attempt": attempt,
                                 "verify_group": f"kb-verify-{task_id}-{attempt}"})
        json.dump({"title": f"{arx} 知识原子交叉验证（{n} 条裁决）", "type": "kb-verify",
                   "est_load": "~15-30min CPU+web", "reward": "工厂积分记账（sandbox_report 入 MES）",
                   "verify": verify_block},
                  open(os.path.join(card_dir, "meta.json"), "w", encoding="utf-8", ), ensure_ascii=False, indent=1)

        errs, notes = lint(card_dir)
        scp_done = False
        note = ""
        if errs:
            note = "未过质量闸，拒发: " + "; ".join(errs)
            log(f"{card_id} {note}")
            # 2026-11-02 RT 修复（拒发残目录清场）：拒发的卡就地 rmtree——旧码把刚生成、
            # 永不上板的卡目录留在 task-seeds/：①被 card-lint --all 永久扫成硬伤（实测
            # 39295-1r1/1r2/2r1 三张残目录把 L3 门打成 rc=1，08:54 起 item 恒 FAIL）；
            # ②同副本血线占住更高 attempt，event-router 回流「已有更新轮次在飞」按本地
            # 目录名匹配，把真卡的重发永久误判成 skipped_newer。拒发 = 该卡从未存在过
            # （--dry-run 同口径：dry 展示的应是「会派出去的卡」，拒发卡不会被派）。
            shutil.rmtree(card_dir, ignore_errors=True)
            results.append({"ok": False, "card_id": card_id, "card_dir": card_dir,
                            "replica": j, "perspective": persp[0] if persp else "",
                            "sampled": n, "seed": seed,
                            "atom_ids": [x["atom_id"] for x in atoms],
                            "gate": errs, "scp": False, "note": note})
            continue
        if not a.dry_run and not a.no_scp:
            scp_done, scp_why = scp_push(card_dir)
            if not scp_done:
                # 2026-11-01 RT 修复：推送失败如实回报（结果 JSON scp=false、note 带
                # 原因），ok 仍表「卡已过闸生成」——event-router 消费侧凭 scp=false
                # 不注册 open（DEB-1 同款纪律：没上门户就不算发过）。
                note = "scp 推送失败（卡已在本地，未上门户）: " + scp_why
                log(f"{card_id} {note}")
        if lineage is None:
            log(f"生成验证卡 {card_id}：候选 {os.path.basename(a.jsonl)} 抽 {n}/{len(rows)} 条，"
                f"证据源 arXiv:{arx}，闸 {'/'.join(notes) or 'green'}，scp={scp_done}")
        elif a.replica:
            log(f"生成验证卡 {card_id}（副本 r{j} 回流重发，视角 "
                f"{persp[0]}）：候选 {os.path.basename(a.jsonl)} 抽 {n}/{len(rows)} 条，"
                f"证据源 arXiv:{arx}，闸 {'/'.join(notes) or 'green'}，scp={scp_done}")
        else:
            log(f"生成验证卡 {card_id}（副本 r{j}/{len(replica_idx)}，视角 "
                f"{persp[0]}）：候选 {os.path.basename(a.jsonl)} 抽 {n}/{len(rows)} 条，"
                f"证据源 arXiv:{arx}，闸 {'/'.join(notes) or 'green'}，scp={scp_done}")
        results.append({"ok": True, "card_id": card_id, "card_dir": card_dir,
                        "replica": j, "perspective": persp[0] if persp else "",
                        "sampled": n, "seed": seed,
                        "atom_ids": [x["atom_id"] for x in atoms],
                        "gate": [], "scp": scp_done, "note": note})

    all_ok = all(r["ok"] for r in results)
    if single_legacy:
        # 既有单卡路径：stdout 末行 JSON 与改动前同形同序（老消费者照旧）
        r0 = results[0]
        if r0["ok"]:
            out(ok=True, card_id=r0["card_id"], card_dir=r0["card_dir"], task_id=task_id,
                arxiv=arx, atoms_total=len(rows), sampled=r0["sampled"], seed=r0["seed"],
                atom_ids=r0["atom_ids"], gate=[], scp=r0["scp"], note=r0["note"])
        else:
            out(ok=False, card_id=r0["card_id"], card_dir=r0["card_dir"], task_id=task_id,
                arxiv=arx, atoms_total=len(rows), sampled=r0["sampled"],
                atom_ids=r0["atom_ids"], gate=r0["gate"], scp=False, note=r0["note"])
    else:
        note = "；".join(
            f"{r['card_id']} {'过闸' if r['ok'] else '未过质量闸: ' + '; '.join(r['gate'])}"
            for r in results)
        # 兼容键（首张卡）：在役老版 event-router 重启前仍按 j["card_id"] 单卡口径消费，
        # 缺这些键会 KeyError 崩掉 poll_harvest（连带 poll_verify_reports 停摆、状态文件
        # 停写）。新码走 cards 数组，兼容键不影响；重启后老码下线，此键仅作保险。
        f0 = results[0]
        out(ok=all_ok, replicas=len(results), cards=results, task_id=task_id,
            arxiv=arx, atoms_total=len(rows), note=note,
            card_id=f0["card_id"], card_dir=f0["card_dir"], sampled=f0["sampled"],
            seed=f0["seed"], atom_ids=f0["atom_ids"], gate=f0["gate"], scp=f0["scp"])
    return 0 if all_ok else 3


if __name__ == "__main__":
    sys.exit(main())
