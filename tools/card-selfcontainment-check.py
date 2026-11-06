#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审卡闸机检器（人工「六要件核」的机器面）—— P1 新建面。

为什么建（依据 30-工件/沙箱一等公民体系研究-20261106/Q1-上下文供给与规划质量.md
  §3.1 卡面自包含性检查单 + 00-总报告.md C-1/B-3；施工卡 D-97 = factory-os#30）：
  · 人工「自包含六要件核」（staging/sandbox-dispatch-template.md:53，派前三闸第三闸）
    机器化 ⇒ 本件是 bot-bridge 发布前必过的那道机器闸（三闸中唯一没有机检的闸：
    占用闸=tools/dispatch-occupancy-check.py、脱敏闸=bot-scrub 均已机检化）。
  · Q1 §3.1 六项各给机器可判据（本件实现面，判据只许六项——禁扩权改卡面）；
    planner 侧 step 08 已落同族规则（D-84 = factory-os#20：M-1/M-2/M-3/M-4/M-7），
    双端一致性由本件 RULE_TABLE 的 sha256 互钉对账保证（--reconcile 回读），
    禁两处各自演化（Q1 :314 双端一致纪律）。
  · fail-closed：审不过 = 不出闸（rc=1 invalid）；不可证同样不出闸（rc=2 fail-loud，
    不猜绿——「不可证不等于证明在场」，同 dispatch-occupancy-check.py 纪律）。

六项机检（Q1 §3.1 逐项；缺项处置一律 invalid，fail-closed 同 step 08 纪律）：
  ① 验收命令可解析（含 → rc=N）：acceptance 非空；每条含「→ rc=N」期望形制
    （= step 08 M-1）；命令首词 ∈ 允许集（Q1 §3.1 #1）或路径形；命令指向的文件
    路径 ∈ pinned base 仓树清单（git ls-tree 对账）。
  ② pinned base 对仓实读存活：SHA 形制（7-40 位十六进制，= step 08 M-3 形制面）
    ⇒ 远端实读集命中（全等或前缀，= M-3 ls-remote 形态）；分支名 ⇒ ref 存在；
    无 base ⇒ 卡面须带「运营者补钉」显式标记（planner card_face 同族已产）。
  ③ 证据带 path:line：证据段 path:line 坐标 ≥1 次；仓内可核引用路径 ∈
    allowed_paths ∪ 判官面清单；跨仓/厂内工作区引用不可核 ⇒ warning 不假红。
  ④ depends_on 可解析 +「不做什么」非空：每条依赖可解析为三形之一
    （repo#n 板号 = M-7 形制｜task_id 形制｜台账锚号形制）；「本卡不做什么」
    节非空（缺 ⇒ 灰卡，不出闸）。
  ⑤ allowed_paths 仓内存在 + 判官面求交为空：非空；逐条按三形态对账
    （件本体/glob/父目录，= step 08 M-2）；× 判官面双源（CODEOWNERS 实读派生 ∪
    judge-paths.md 静态族，= step 08 M-4）求交非空 ⇒ 硬红（判据邻接物走
    owner 裁决，不出工人闸）。
  ⑥ 环境前置段与命令族一致：acceptance/depends_on 命令族所需的非基线工具
    （rust/docker/gpu/node/jq/make）⊆ 环境前置段点名集（python3/纯文档卡 = 空；
    step 08 侧该一致性留干跑/沙箱自检——#19 禁项明示，故本项为审卡闸独有）。

rc 三态：0=pass（出闸）；1=invalid（审不过，不出闸）；2=fail-loud（不可证，
不出闸）。verdict 留痕：--out 落 JSON（schema af.card.selfcontainment-check.v1），
供 bot-bridge 发布链消费（形态同切片闸 scan-report.json）。

形态照 tools/dispatch-occupancy-check.py：面-证据坐标-判定同构、rc 三态、
--selftest 内嵌夹具自测（零网络、零真树读取，全部注入桩）。零凭据正文；
仓树/ls-remote/API 探针/CODEOWNERS 均为只读面，零写入（--out 由调用方指定）。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PLANNER = os.path.join(ROOT, ".github", "workflows", "planner.yml")
DEFAULT_CODEOWNERS = os.path.join(ROOT, "CODEOWNERS")
CMD_TIMEOUT_S = 60

# ---------------------------------------------------------------- 共享规则常量
# 下列正则/词表与 planner.yml step 08 规则段逐字同族（双端一致；--reconcile 钉值
# 对账回读）。改动任一处必须同批重钉（gate-pins-refresh 同款纪律）。

RC_RE = re.compile(r"→\s*rc\s*=\s*\d+")          # = M-1（step 08 主段）
SHA_RE = re.compile(r"[0-9a-f]{7,40}")           # = M-3 base_sha 形制面
LS_REMOTE_REFSPECS = ("refs/heads/*", "refs/tags/*", "refs/pull/*/head")  # = M-3

# = M-4 判官面双源（逐字同 planner.yml step 08；① CODEOWNERS 派生面运行时实读，
#   ② judge-paths.md 静态派生族）。命中 ⇒ ⑤ 硬红——判官/门/判据件禁入 allowed_paths。
JUDGE_KEYWORD = re.compile(
    r"(all-gates\.sh|gate-pins\.list|gate-pins-refresh|gate_inputs|subgates\.list"
    r"|mirror-scan-allowlist|clippy-baseline|scorechain-manifest|CODEOWNERS"
    r"|judge|判官|判据)")
AF_JUDGE_FAMILY = re.compile(
    r"(?:^|[:/`])(ci/|proofs/|strategies/|packages/reportkit/"
    r"|crates/af-execline/src/judge\.rs|(?:[^\s`]*/)?crates/.*/tests/"
    r"|numbers\.json|deliverables\.yaml|doc-claims\.txt"
    r"|rust-toolchain\.toml|Cargo\.toml|Cargo\.lock)")
JUDGE_STATIC_FACTORYOS = (".github/workflows/gates.yml",)

# = M-2 跨仓/厂内工作区裸前缀（本闸按卡面 repo 与仓树 repo 判定可核面；对不上
#   的裸前缀 ⇒ warning 不假红，不可证不等于证明在场）
CROSS_TREE_BARE = ("af/", "crates/", "ci/", "proofs/", "strategies/",
                   "packages/", "poc/", "kb-seed", "计划/", "30-工件/",
                   "staging/", "外派", "状态/")
WORKSPACE_BARE = ("计划/", "30-工件/", "staging/", "外派", "状态/")  # 厂内工作区（永不在仓树）
AF_BARE = ("af/", "crates/", "ci/", "proofs/", "strategies/",
           "packages/", "poc/", "kb-seed")                            # af 仓原生裸面前缀

# = M-7 depends_on 板号形制（逐字同 planner.yml step 08）
DEP_REPO_FORM = re.compile(r"([A-Za-z0-9._-]+)?#\d+")
# = step 08 task_id 形制（同波引用判据的形制面）
TASK_ID_FORM = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
# 台账锚号形制面（M-7 三形之三的形制近似；指向有效性由 planner 侧持台账锚全集终裁，
# 本闸只判形制——分工记入 RULE_TABLE，禁两处各自演化）
ANCHOR_FORM = re.compile(r"[A-Za-z]{1,6}-[A-Za-z0-9]{1,10}|[A-Za-z]{1,6}\d{1,5}")

# Q1 §3.1 #1 命令首词允许集（…= 可扩；禁塞命令串由 fast_tests 同族纪律把）
CMD_HEADS = {"python3", "python", "cargo", "rustc", "env", "git", "bash", "sh",
             "jq", "sha256sum", "ls", "cat", "grep", "diff", "make", "node",
             "npm", "ruff", "pytest", "curl", "wget", "true", "false", "echo",
             "test"}
# 输出旗（其后令牌是产出路径，不算「命令指向的文件」——不作为 ① 的树上对账项）
OUTPUT_FLAGS = {"--out", "-o", "--output", "--report", "--verdict-out"}
# Q1 §3.1 #6 命令族 → 非基线环境工具（python3/git/bash/sha256sum 等为 runner
# 基线，不入需求集——「python3/纯文档卡 = 空」）
CMD_TOOL_REQ = {"cargo": "rust", "rustc": "rust", "rustup": "rust",
                "docker": "docker", "nvidia-smi": "gpu", "cuda": "gpu",
                "node": "node", "npm": "node", "jq": "jq", "make": "make"}
ENV_TOOL_KEYWORDS = {"rust": ("rust", "cargo", "rustup"),
                     "docker": ("docker",),
                     "gpu": ("gpu", "cuda", "nvidia"),
                     "node": ("node", "npm"),
                     "jq": ("jq",),
                     "make": ("make",)}
# 证据坐标 path:line 形态（Q1 §3.1 #3：\S+\.py:\d+ 或通用 path:line——须带扩展名，
# 防把时间/端口（15:05、port:7890）误当坐标）
PATHLINE_RE = re.compile(
    r"(?<![\w/`])((?:[\w.~-]+/)*[\w.~-]+\.[A-Za-z0-9]{1,12}):(\d+)(?:-(\d+))?(?!\w)")


# ---------------------------------------------------------------- 小工具

def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel(path):
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def entry_repo_path(ent):
    """「repo: 路径（注记）」→ (repo, path)；裸路径 → ("", path)。

    与 planner.yml step 08 entry_repo_path 同形（M-2/M-4 的共用解析件）。
    """
    s = str(ent).strip().strip("`")
    m = re.match(r"^([A-Za-z0-9._-]+)\s*:\s*(.+)$", s)
    repo = ""
    if m:
        repo, s = m.group(1), m.group(2)
    s = s.split("（")[0].split("(")[0].strip().strip("`\"'")
    return repo, (s or None)


def codeowners_patterns_from_text(text):
    """CODEOWNERS 文本 → 锁面模式清单（= step 08 codeowners_patterns 读法：
    跳过空行/#/★ 注释行，只收 parts[1] 以 @ 开头的锁定行）。"""
    pats = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("★"):
            continue
        parts = ln.split()
        if len(parts) >= 2 and parts[1].startswith("@"):
            pats.append(parts[0])
    return pats


def codeowners_hit(relpath, pats):
    """relpath × CODEOWNERS 模式（= step 08 codeowners_hit 同形同语义）。"""
    rn = "/" + relpath.lstrip("/")
    for p in pats:
        pn = p.lstrip("/")
        if pn.endswith("/"):
            if rn.startswith("/" + pn) or rn == "/" + pn.rstrip("/"):
                return p
        elif any(ch in pn for ch in "*?["):
            if fnmatch.fnmatch(rn, "/" + pn) or fnmatch.fnmatch(relpath, pn):
                return p
        elif rn == "/" + pn or rn.startswith("/" + pn + "/"):
            return p
    return None


def judge_hit(ent, co_pats, co_repo="factory-os"):
    """allowed_paths 条目 × 判官面双源；返回命中描述或 None。

    = step 08 judge_hit：关键词族 + af 静态族 + factory-os 派生缺口 + CODEOWNERS
    派生面（CODEOWNERS 只对 repo 为 ""/co_repo 的条目生效——跨仓条目不套别仓锁面）。
    """
    m = JUDGE_KEYWORD.search(str(ent))
    if m:
        return "关键词族[%s]" % m.group(1)
    repo, relp = entry_repo_path(ent)
    if not relp:
        return None
    af = AF_JUDGE_FAMILY.search(relp)
    if af:
        return "judge-paths.md af 族[%s]" % af.group(1)
    for st in JUDGE_STATIC_FACTORYOS:
        if relp == st or relp.startswith(st + "/"):
            return "judge-paths.md factory-os 派生缺口[%s]" % st
    if repo in ("", co_repo):
        p = codeowners_hit(relp, co_pats or [])
        if p:
            return "CODEOWNERS[%s]" % p
    return None


def tree_hit(relpath, files, dirs):
    """三形态对账（= step 08 M-2 语义）：件本体 / glob 命中（fnmatch 对树清单，
    不碰进程 cwd 文件系统——树面以注入清单为唯一真源）/ 父目录在场（新建件合法形态）。"""
    rp = relpath.strip().strip("`\"'")
    if rp in files:
        return True, "件本体"
    for f in files:
        if fnmatch.fnmatch(f, rp):
            return True, "glob"
    parent = os.path.dirname(rp)
    if parent and (parent in dirs or any(f.startswith(parent + "/") for f in files)):
        return True, "父目录"
    return False, "miss"


def path_scope(p, repo, tree_repo):
    """路径可核性分级（= M-2 跨仓纪律的推广）：("verify"|"warn", 原因)。

    verify=可按仓树对账；warn=本闸不可核（跨仓/工作区），warning 不假红。
    """
    if p.startswith(WORKSPACE_BARE):
        return "warn", "厂内工作区件（不在任何仓树）"
    if repo and repo != tree_repo:
        return "warn", "指向 %s（仓树为 %s）" % (repo, tree_repo)
    if not repo:
        if tree_repo.endswith("/af") and p.startswith(AF_BARE):
            return "verify", ""
        if p.startswith(CROSS_TREE_BARE):
            return "warn", "跨仓/他树裸前缀（对不上仓树 repo %s）" % tree_repo
    return "verify", ""


# ---------------------------------------------------------------- 仓树面

def _repo_name_from_url(url):
    u = (url or "").strip()
    if not u:
        return "?"
    if u.endswith(".git"):
        u = u[:-4]
    if u.startswith("git@"):
        u = u.split(":", 1)[-1]
    else:
        u = u.split("://", 1)[-1]
        u = u.split("/", 1)[-1] if "/" in u else u
    return u or "?"


class RepoTree(object):
    """目标仓 pinned base 的文件清单面（只读）。"""

    def __init__(self, repo_name, files, dirs, source, note=""):
        self.repo_name = repo_name
        self.files = set(files)
        self.dirs = set(dirs)
        self.source = source
        self.note = note

    @classmethod
    def derive_dirs(cls, files):
        dirs = set()
        for f in files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        return dirs

    @classmethod
    def from_repo_root(cls, root, ref=None):
        """git ls-tree -r --name-only <ref|HEAD>（本地 clone 只读面）。"""
        def _git(args):
            # core.quotePath=false：CJK 路径（波次清单/ 等）逐字取回，禁 git 默认
            # 八进制转义面（否则仓树清单对中文路径恒 miss ⇒ 假红）。
            return subprocess.run(["git", "-C", root, "-c", "core.quotePath=false"] + args,
                                  capture_output=True, text=True, timeout=CMD_TIMEOUT_S)
        try:
            r = _git(["ls-remote", "--get-url", "origin"])
            name = _repo_name_from_url((r.stdout or "").strip())
            used_ref, note = ref or "HEAD", ""
            t = _git(["ls-tree", "-r", "--name-only", used_ref])
            if t.returncode != 0 and ref:
                t = _git(["ls-tree", "-r", "--name-only", "HEAD"])
                used_ref, note = "HEAD", "ref %s 本地不可析出，回退 HEAD" % ref
            if t.returncode != 0:
                raise RuntimeError("git ls-tree rc=%d：%s" % (t.returncode,
                                                              t.stderr.strip()[:120]))
            files = [ln for ln in t.stdout.splitlines() if ln.strip()]
            return cls(name, files, cls.derive_dirs(files),
                       "git ls-tree -r --name-only %s @ %s" % (used_ref, rel(root)), note)
        except subprocess.TimeoutExpired:
            raise RuntimeError("git ls-tree 超时（%ds）" % CMD_TIMEOUT_S)

    @classmethod
    def from_file(cls, path):
        """清单件：首行可带 '# repo: owner/name'，其余每行一个仓内路径（只读）。"""
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
        name = "factory-os"
        if lines and lines[0].startswith("# repo:"):
            name = lines[0].split(":", 1)[1].strip()
            lines = lines[1:]
        files = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        return cls(name, files, cls.derive_dirs(files), "tree-file %s" % rel(path))

    def hit(self, relpath):
        return tree_hit(relpath, self.files, self.dirs)


# ---------------------------------------------------------------- base 探针

def _git_proxy_args():
    """可选代理注入：AF_GIT_HTTP_PROXY 环境变量（凭据由调用方管，不进本件）。"""
    px = os.environ.get("AF_GIT_HTTP_PROXY") or ""
    if px:
        return ["-c", "http.proxy=" + px]
    return []


def probe_base_lsremote(repo_root, remote, base):
    """M-3 同形态：git ls-remote 实读集命中（全等或前缀）；分支名走 ref 存在性。

    返回 (state, detail)；state ∈ ALIVE / DEAD / UNKNOWN（不可证 ⇒ fail-loud）。
    """
    try:
        if re.fullmatch(r"[0-9a-f]{7,40}", base or ""):
            r = subprocess.run(
                ["git", "-C", repo_root] + _git_proxy_args()
                + ["ls-remote", remote] + list(LS_REMOTE_REFSPECS),
                capture_output=True, text=True, timeout=CMD_TIMEOUT_S)
            if r.returncode != 0:
                return "UNKNOWN", "git ls-remote 实读失败 rc=%d（%s）——存活性不可证" % (
                    r.returncode, (r.stderr or "").strip()[:100])
            shas = {ln.split("\t")[0] for ln in r.stdout.splitlines() if "\t" in ln}
            if any(s == base or s.startswith(base) for s in shas):
                return "ALIVE", "ls-remote 实读集命中（heads/tags/pull refs 共 %d 枚 SHA）" % len(shas)
            return "DEAD", "pinned base %s… 于远端实读集（%d 枚 SHA）零命中——钉桩不存活" % (
                base[:12], len(shas))
        # 分支/ref 名 ⇒ ref 存在性（Q1 §3.1 #2 第二形）
        r = subprocess.run(
            ["git", "-C", repo_root] + _git_proxy_args()
            + ["ls-remote", "--exit-code", remote, base],
            capture_output=True, text=True, timeout=CMD_TIMEOUT_S)
        if r.returncode == 0:
            return "ALIVE", "ref %s 远端存在（ls-remote --exit-code rc=0）" % base
        if r.returncode == 2 and not (r.stdout or "").strip():
            return "DEAD", "ref %s 远端不存在（ls-remote --exit-code rc=2）" % base
        return "UNKNOWN", "ref 实读失败 rc=%d（%s）——存在性不可证" % (
            r.returncode, (r.stderr or "").strip()[:100])
    except subprocess.TimeoutExpired:
        return "UNKNOWN", "git ls-remote 超时（%ds）——存活性不可证" % CMD_TIMEOUT_S
    except Exception as exc:                       # noqa: BLE001
        return "UNKNOWN", "ls-remote 异常：%s——不可证" % exc


def probe_base_api(repo, base):
    """Q1 §3.1 #2 第一形：GET /repos/{repo}/commits/{base} 须 200（fail-closed：
    404=不存在、403=限流/无权、None=网络不可达，一律按红/不可证）。"""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/commits/%s" % (repo, base),
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "factory-os-card-selfcontainment-check"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return "ALIVE", "GET /repos/%s/commits/%s… → HTTP %s" % (repo, base[:12], resp.status)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "DEAD", "GET /repos/%s/commits/%s… → 404（钉桩不存在/不可见）" % (repo, base[:12])
        return "UNKNOWN", "GET /repos/%s/commits/%s… → HTTP %s（限流/无权？不可证）" % (
            repo, base[:12], e.code)
    except Exception as exc:                       # noqa: BLE001
        return "UNKNOWN", "API 探针网络不可达：%s——不可证" % exc


# ---------------------------------------------------------------- 卡面装载

def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)]


SECTION_STOP = re.compile(r"^(?:【|##?\s|#\s)")
ITEM_RE = re.compile(r"^(?:[-*]\s+(?:\[[ xX]\]\s+)?|\d+[.、]\s+)(.+)$")


def _md_section_items(lines, start):
    """从 heading 行后收集列表项（- [ ] x / - x / N. x），到下一个 section 头止。"""
    items = []
    for ln in lines[start + 1:]:
        s = ln.strip()
        if not s:
            continue
        if SECTION_STOP.match(s):
            break
        m = ITEM_RE.match(s)
        if m:
            items.append(m.group(1).strip())
        elif items:
            break                    # 列表已开始，遇到非列表行 ⇒ 本节结束
    return items


def parse_card_md(text):
    """卡面 markdown → 卡 dict（兼容 planner card_face 的【】段式与人工卡面 ## 段式）。"""
    card = {"title": None}
    lines = text.splitlines()

    def field(pat):
        for ln in lines:
            m = re.search(pat, ln)
            if m:
                return m.group(1).strip().strip("`*\"' ")
        return None

    card["task_id"] = (field(r"【任务】\s*`?([^\s`】]+)`?")
                       or field(r"task_id[：:]\s*`?([^\s`】*]+)"))
    card["debt"] = (field(r"【债号】\s*`?([^\s`】]+)`?")
                    or field(r"债号(?:建议)?[：:]\s*\*{0,2}([A-Za-z0-9._-]+)\*{0,2}"))
    card["channel"] = (field(r"【通道】\s*`?([^\s`】]+)`?")
                       or field(r"通道[：:]\s*`?([a-z-]+)"))
    card["merge_policy"] = field(r"【合线策略】\s*(\S+)")

    # pinned base：先 hex，再 ref 名；无 base 时认「补钉」显式标记
    base, base_note = None, ""
    for ln in lines:
        if ("【pinned base】" in ln) or ("pinned base" in ln) or ("钉桩基线" in ln) or ("基线" in ln):
            m = re.search(r"(?<![0-9a-f])[0-9a-f]{7,40}(?![0-9a-f])", ln)
            if m:
                base = m.group(0)
                break
            bt = re.search(r"`([\w./-]{3,})`", ln)
            if bt and "补钉" not in ln:
                base = bt.group(1)
                base_note = "ref 名形制（分支名 ⇒ ref 存在性探针）"
                break
    if base is None:
        for ln in lines:
            if "补钉" in ln:
                base_note = "运营者补钉（卡面无钉桩基线，显式标记在场）"
                break
    card["base"] = base
    card["base_note"] = base_note

    # 段式采集：验收命令集 / 允许路径 / 依赖 / 禁项（不做什么）/ 环境前置
    acceptance, allowed, depends, not_doing, env_text = [], [], [], [], []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if "验收命令集" in s:
            acceptance = _md_section_items(lines, i)
        elif "允许路径" in s or "allowed_paths" in s:
            allowed = _md_section_items(lines, i)
            if not allowed:
                m = re.search(r"【允许路径】\s*(.+)$", s)
                if m:
                    allowed = [x.strip() for x in re.split(r"[；;]", m.group(1)) if x.strip()]
        elif s.startswith("【依赖】") or "depends_on" in s:
            depends = _md_section_items(lines, i)
            if not depends:
                m = re.search(r"【依赖】\s*(.+)$", s)
                if m:
                    depends = [x.strip() for x in re.split(r"[；;、]", m.group(1)) if x.strip()]
        elif ("不做什么" in s) or ("禁项" in s):
            not_doing = _md_section_items(lines, i)
        elif "环境前置" in s:
            env_text = _md_section_items(lines, i)
            if not env_text:
                m = re.search(r"【环境前置】\s*(.+)$", s)
                if m:
                    env_text = [m.group(1)]
    # 行内式（人工卡面的 bullet 字段行）
    if not allowed:
        m = re.search(r"allowed_paths[：:]\s*`?([^`\n]+)`?", text)
        if m:
            allowed = [x.strip() for x in re.split(r"[；;]", m.group(1)) if x.strip()]
    if not depends:
        m = re.search(r"(?:^|\n)\s*依赖[：:]\s*(.+)", text)
        if m and not m.group(1).strip().startswith("无"):
            depends = [x.strip() for x in re.split(r"[；;、]", m.group(1)) if x.strip()]

    card["acceptance"] = acceptance
    card["allowed_paths"] = allowed
    card["depends_on"] = depends
    card["not_doing"] = not_doing
    card["env_precondition"] = "；".join(env_text) if env_text else ""
    # 证据坐标：全文 path:line 形态（Q1 §3.1 #3）
    refs = []
    for m in PATHLINE_RE.finditer(text):
        refs.append("%s:%s" % (m.group(1), m.group(2)))
    card["evidence"] = refs
    return card


def load_card(json_path=None, md_path=None):
    """JSON 卡（manifest 卡/v1.1 可选字段面）与 markdown 卡面合并；JSON 为权威面。"""
    card = {}
    if json_path:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("card-json 顶层必须为对象（实得 %s）" % type(data).__name__)
        card.update(data)
    if md_path:
        with open(md_path, "r", encoding="utf-8") as f:
            md_card = parse_card_md(f.read())
        for k, v in md_card.items():
            if v and not card.get(k):
                card[k] = v
    # 归一化
    for k in ("acceptance", "allowed_paths", "depends_on", "evidence", "not_doing"):
        card[k] = _as_list(card.get(k))
    card["env_precondition"] = str(card.get("env_precondition") or "")
    card["base"] = card.get("base") or card.get("base_sha") or None
    return card


# ---------------------------------------------------------------- 六项机检

def check_acceptance(card, tree):                                # ①
    face = {"check": "① 验收命令可解析（含 → rc=N）",
            "surface": "acceptance（%d 条）" % len(card.get("acceptance") or []),
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    ac = card.get("acceptance") or []
    if not ac:
        face["verdict"] = "INVALID"
        face["detail"] = "验收命令集缺失/为空（Q1 §3.1 #1；契约要件6）"
        return face
    bad_rc, bad_head, bad_path = [], [], []
    for j, a in enumerate(ac):
        tag = "acceptance[%d]" % j
        if not RC_RE.search(a):
            bad_rc.append("%s：%r" % (tag, a[:70]))
            continue
        head_part = RC_RE.split(a)[0].strip()
        try:
            toks = shlex.split(head_part)
        except ValueError:
            toks = head_part.split()
        if not toks:
            bad_head.append("%s：命令段空（%r）" % (tag, a[:70]))
            continue
        head = toks[0]
        if any("\u4e00" <= ch <= "\u9fff" for ch in head):
            bad_head.append("%s：命令首词含 CJK（%r）——不可解析为命令词元" % (tag, head[:40]))
            continue
        if "/" in head or head.endswith((".py", ".sh")):
            if tree is None:
                face["notes"].append("%s：路径形命令首词 %s 待仓树对账（树面缺席）" % (tag, head))
            else:
                ok, how = tree.hit(head)
                if not ok:
                    bad_path.append("%s：命令首词 %s 不在 pinned base 树清单" % (tag, head))
        elif head not in CMD_HEADS:
            bad_head.append("%s：命令首词 %r ∉ 允许集" % (tag, head))
        # 命令指向的文件路径 ∈ 树清单（Q1 §3.1 #1 第三判据）
        if tree is not None:
            skip_next = False
            for t in toks[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if t in OUTPUT_FLAGS:
                    skip_next = True
                    continue
                if t.startswith("-") or "=" in t or t.startswith("http"):
                    continue
                if "/" in t:
                    ok, how = tree.hit(t)
                    if not ok:
                        bad_path.append("%s：命令指向路径 %s 不在 pinned base 树清单（幻指）" % (tag, t))
    if bad_rc:
        face["verdict"] = "INVALID"
        face["detail"] = "缺期望退出码形制「→ rc=N」%d 条（= step 08 M-1，fail-closed）" % len(bad_rc)
        face["evidence"].extend(bad_rc)
    if bad_head:
        face["verdict"] = "INVALID"
        face["detail"] = (face["detail"] + "；" if face["detail"] else "") + \
            "命令首词不可解析/越出允许集 %d 条" % len(bad_head)
        face["evidence"].extend(bad_head)
    if bad_path:
        face["verdict"] = "INVALID"
        face["detail"] = (face["detail"] + "；" if face["detail"] else "") + \
            "命令指向路径树上缺场 %d 条（禁幻指）" % len(bad_path)
        face["evidence"].extend(bad_path)
    if face["verdict"] == "PASS":
        face["detail"] = "%d 条全部含「→ rc=N」；首词 ∈ 允许集；指向路径 ∈ 仓树清单" % len(ac)
        if tree is None:
            face["notes"].append("树面缺席：路径对账未执行（调用方应提供 --repo-root/--tree-file）")
    return face


def check_base(card, base_probe):                                # ②
    face = {"check": "② pinned base 对仓实读存活",
            "surface": "base=%s" % (card.get("base") or "(缺)"),
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    base = card.get("base")
    if not base:
        if "补钉" in (card.get("base_note") or ""):
            face["detail"] = "卡面无钉桩基线，但带「运营者补钉」显式标记（planner card_face 同族已产）⇒ 交人工补钉后开工"
            face["notes"].append("Q1 §3.1 #2：无 base_sha ⇒ 须有补钉显式标记，否则 invalid")
            return face
        face["verdict"] = "INVALID"
        face["detail"] = "pinned base 缺失且无「运营者补钉」显式标记（Q1 §3.1 #2）"
        return face
    if re.fullmatch(r"[0-9a-f]{7,40}", base):
        face["notes"].append("SHA 形制（= step 08 M-3 形制面）：%s…" % base[:12])
    else:
        face["notes"].append("ref 名形制：%s（ref 存在性探针）" % base)
    if base_probe is None:
        face["verdict"] = "UNKNOWN"
        face["detail"] = "未配置 base 探针（--repo-root/--repo）⇒ 存活性不可证（fail-loud，不猜绿）"
        return face
    state, detail = base_probe(base)
    face["detail"] = detail
    if state == "ALIVE":
        face["verdict"] = "PASS"
    elif state == "DEAD":
        face["verdict"] = "INVALID"
        face["evidence"].append("base=%s…：%s" % (base[:12], detail))
    else:
        face["verdict"] = "UNKNOWN"
    return face


def check_evidence(card, co_pats, co_repo, tree_repo):           # ③
    face = {"check": "③ 证据带 path:line",
            "surface": "证据条目 %d 条" % len(card.get("evidence") or []),
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    # 坐标实抽：证据条目是自由文本（可带注记），path:line 坐标从中抽取——
    # 「有条目但抽不出坐标」同样不过（禁把「见上次讨论」当证据，Q1 §3.1 #3）。
    refs = []
    for ev in card.get("evidence") or []:
        for m in PATHLINE_RE.finditer(str(ev)):
            refs.append("%s:%s" % (m.group(1), m.group(2)))
    if not refs:
        face["verdict"] = "INVALID"
        face["detail"] = "证据段无 path:line 坐标（Q1 §3.1 #3：须 ≥1 处 file:line 出处）"
        return face
    face["surface"] = "证据条目 %d 条 ⇒ path:line 坐标 %d 处" % (
        len(card.get("evidence") or []), len(refs))
    allowed_norm = []
    for ent in card.get("allowed_paths") or []:
        _, p = entry_repo_path(ent)
        if p:
            allowed_norm.append(p)
    outside = []
    for ref in refs:
        p = ref.rsplit(":", 1)[0]
        repo, p = entry_repo_path(p)
        scope, why = path_scope(p, repo, tree_repo)
        if scope == "warn":
            face["notes"].append("%s：%s——本闸不可核（warning 不假红）" % (ref, why))
            continue
        if p in allowed_norm or tree_hit(p, set(allowed_norm), set())[0]:
            continue
        if judge_hit(p, co_pats, co_repo):
            face["notes"].append("%s ∈ 判官面（只读参考，合法）" % ref)
            continue
        outside.append(ref)
    if outside:
        face["verdict"] = "INVALID"
        face["detail"] = ("证据引用路径越出 allowed_paths ∪ 判官面 %d 处"
                          "（Q1 §3.1 #3；回炉改卡或补白名单）" % len(outside))
        face["evidence"].extend(outside)
    else:
        face["detail"] = ("path:line 坐标 %d 处；仓内可核引用全部 ∈ allowed_paths ∪ 判官面"
                          % len(refs))
    return face


def check_deps(card):                                            # ④
    face = {"check": "④ depends_on 可解析 +「不做什么」非空",
            "surface": "depends_on %d 条；不做什么 %d 条"
                       % (len(card.get("depends_on") or []), len(card.get("not_doing") or [])),
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    bad_dep = []
    for j, d in enumerate(card.get("depends_on") or []):
        parts = d.split()
        head = parts[0].strip("，。；、") if parts else ""
        if not head:
            bad_dep.append("depends_on[%d]：空条目" % j)
            continue
        if DEP_REPO_FORM.fullmatch(head) or TASK_ID_FORM.fullmatch(head) \
                or ANCHOR_FORM.fullmatch(head):
            continue
        bad_dep.append("depends_on[%d]：%r 不可解析（须 repo#n 板号｜task_id｜台账锚号 三形之一）"
                       % (j, d[:60]))
    nd = [x for x in (card.get("not_doing") or []) if x.strip()]
    if bad_dep:
        face["verdict"] = "INVALID"
        face["detail"] = "depends_on 不可解析 %d 条（= step 08 M-7 形制面；指向有效性由 planner 侧终裁）" % len(bad_dep)
        face["evidence"].extend(bad_dep)
    if not nd:
        face["verdict"] = "INVALID"
        face["detail"] = (face["detail"] + "；" if face["detail"] else "") + \
            "「本卡不做什么」节为空——灰卡，不出闸（Q1 §3.1 #4；派发契约要件6 边界节）"
    if face["verdict"] == "PASS":
        face["detail"] = "depends_on 全部可解析；「不做什么」节非空（%d 条）" % len(nd)
    return face


def check_paths(card, tree, co_pats, co_repo):                   # ⑤
    face = {"check": "⑤ allowed_paths 仓内存在 + 判官面求交为空",
            "surface": "allowed_paths %d 条 × 判官面双源" % len(card.get("allowed_paths") or []),
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    ap = card.get("allowed_paths") or []
    if not ap:
        face["verdict"] = "INVALID"
        face["detail"] = "allowed_paths 为空/缺失（Q1 §3.1 #5：白名单纪律，禁空）"
        return face
    tree_repo = tree.repo_name if tree is not None else co_repo
    miss, judge, cross = [], [], []
    for j, ent in enumerate(ap):
        repo, p = entry_repo_path(ent)
        if not p:
            continue
        scope, why = path_scope(p, repo, tree_repo)
        if scope == "warn":
            cross.append("allowed_paths[%d]：%s——%s（warning，不假红）" % (j, p, why))
        elif tree is None:
            face["notes"].append("allowed_paths[%d]：%s 待仓树对账（树面缺席）" % (j, p))
        else:
            ok, how = tree.hit(p)
            if not ok:
                miss.append("allowed_paths[%d]：%s 在仓树缺场（件/glob/父目录三者皆无——禁幻指，"
                            "= step 08 M-2）" % (j, p))
        hit = judge_hit(ent, co_pats, co_repo)
        if hit:
            judge.append("allowed_paths[%d]：%s 命中判官面（%s）——禁入白名单（= step 08 M-4 硬红；"
                         "判据变更走 owner 裁决）" % (j, p, hit))
    if miss:
        face["verdict"] = "INVALID"
        face["detail"] = "指向仓树缺场 %d 条（禁幻指）" % len(miss)
        face["evidence"].extend(miss)
    if judge:
        face["verdict"] = "INVALID"
        face["detail"] = (face["detail"] + "；" if face["detail"] else "") + \
            "判官面求交非空 %d 条（判据邻接物不出工人闸）" % len(judge)
        face["evidence"].extend(judge)
    face["notes"].extend(cross)
    if tree is None and not miss and not judge:
        face["verdict"] = "UNKNOWN"
        face["detail"] = "树面缺席 ⇒ 存在性不可证（fail-loud，不猜绿；应提供 --repo-root/--tree-file）"
    elif face["verdict"] == "PASS":
        face["detail"] = "%d 条全部树上对账通过（三形态）；判官面双源求交为空" % len(ap)
    return face


def _env_named_tools(env_text):
    low = (env_text or "").lower()
    named = set()
    for tool, kws in ENV_TOOL_KEYWORDS.items():
        if any(k in low for k in kws):
            named.add(tool)
    return named


def _cmd_required_tools(card):
    """acceptance + depends_on 命令族的非基线工具需求（全词元扫，env 前缀不挡）。"""
    need = set()
    for a in card.get("acceptance") or []:
        head_part = RC_RE.split(a)[0] if RC_RE.search(a) else a
        try:
            toks = shlex.split(head_part)
        except ValueError:
            toks = head_part.split()
        for t in toks:
            if t in CMD_TOOL_REQ:
                need.add(CMD_TOOL_REQ[t])
    for d in card.get("depends_on") or []:
        try:
            toks = shlex.split(d)
        except ValueError:
            toks = d.split()
        for t in toks:
            if t in CMD_TOOL_REQ:
                need.add(CMD_TOOL_REQ[t])
    return need


def check_env(card):                                             # ⑥
    face = {"check": "⑥ 环境前置段与命令族一致",
            "surface": "env_precondition=%r" % (card.get("env_precondition") or "")[:60],
            "verdict": "PASS", "detail": "", "evidence": [], "notes": []}
    named = _env_named_tools(card.get("env_precondition"))
    need = _cmd_required_tools(card)
    if not need:
        face["detail"] = "命令族无任何非基线工具需求（python3/纯文档卡 = 空，Q1 §3.1 #6）"
        if named:
            face["notes"].append("环境段另点名了 %s（超出命令族需求，不拦）" % sorted(named))
        return face
    gaps = sorted(need - named)
    if gaps:
        face["verdict"] = "INVALID"
        face["detail"] = ("命令族需 %s，环境前置段未点名（Q1 §3.1 #6：点名集 ⊇ 命令族所需）"
                          % gaps)
        face["evidence"].append("需要 %s｜环境段现点名 %s" % (sorted(need), sorted(named) or "（空）"))
        return face
    face["detail"] = "命令族所需 %s ⊆ 环境段点名 %s" % (sorted(need), sorted(named))
    return face


# ---------------------------------------------------------------- 主判定

def run_check(card, tree=None, base_probe=None, co_pats=None, co_repo="factory-os",
              out=None):
    out = out if out is not None else []
    out.append("CARD-SELFCONTAINMENT-CHECK · 卡=%s（债号=%s）"
               % (card.get("task_id") or card.get("title") or "?", card.get("debt") or "?"))
    out.append("  口径：Q1 §3.1 六要件机检（判据只许六项）；任一面 invalid ⇒ 不出闸；"
               "任一面不可证 ⇒ fail-loud 不出闸（不猜绿）")
    tree_repo = tree.repo_name if tree is not None else co_repo
    faces = [
        check_acceptance(card, tree),
        check_base(card, base_probe),
        check_evidence(card, co_pats or [], co_repo, tree_repo),
        check_deps(card),
        check_paths(card, tree, co_pats or [], co_repo),
        check_env(card),
    ]
    for f in faces:
        out.append("  %s｜%s" % (f["check"], f["verdict"]))
        out.append("      面：%s" % f["surface"])
        if f["detail"]:
            out.append("      判定依据：%s" % f["detail"])
        for e in f["evidence"]:
            out.append("      不过证据：%s" % e)
        for n in f["notes"]:
            out.append("      提示：%s" % n)

    invalid = [f["check"] for f in faces if f["verdict"] == "INVALID"]
    unknown = [f["check"] for f in faces if f["verdict"] == "UNKNOWN"]
    if unknown:
        verdict, rc = "FAIL-LOUD", 2
        out.append("  判定：**FAIL-LOUD**（不可证：%s）——不出闸" % "；".join(unknown))
    elif invalid:
        verdict, rc = "INVALID", 1
        out.append("  判定：**INVALID**（%s）——审不过，不出闸（fail-closed）" % "；".join(invalid))
    else:
        verdict, rc = "PASS", 0
        out.append("  判定：**PASS**（六项全过）——出闸")
    result = {
        "schema": "af.card.selfcontainment-check.v1",
        "card": card.get("task_id") or card.get("title"),
        "debt": card.get("debt"),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verdict": verdict,
        "rc": rc,
        "faces": faces,
        "blocking": {"invalid": invalid, "unprovable": unknown},
        "rule_table_sha256": RULE_TABLE_SHA256,
    }
    return result, rc


# ---------------------------------------------------------------- selftest

def _stub_tree(repo="factory-os", extra=()):
    files = {"tools/card-selfcontainment-check.py", "tools/dispatch-occupancy-check.py",
             "tools/all-gates.sh", "tools/mirror-disclose.sh", "CODEOWNERS", "README.md",
             ".github/workflows/planner.yml", ".github/workflows/gates.yml",
             "波次清单/wave-03.json", "波次清单/wave-03-draft.md"}
    files.update(extra)
    return RepoTree(repo, files, RepoTree.derive_dirs(files), "selftest-stub")


# 桩 CODEOWNERS：逐字镜像 factory-os/CODEOWNERS 的三条锁面模式（2026-11-07 实读），
# 令 selftest 全封闭（零真树读取）又保持判官面真实形态。
STUB_CODEOWNERS = ("# stub\n/tools/                       @feasy898\n"
                   "/账本/                        @feasy898\n"
                   "/波次清单/*.md                 @feasy898\n")
STUB_CO_PATS = codeowners_patterns_from_text(STUB_CODEOWNERS)

BASE_CARD = {
    "task_id": "w07-fixture-selfcontain",
    "debt": "D-97",
    "channel": "bot-lane",
    "repo": "CloudCrane-Software/factory-os",
    "base": "a" * 40,
    "acceptance": [
        "python3 -I tools/card-selfcontainment-check.py --selftest → rc=0",
        "python3 -I tools/card-selfcontainment-check.py --reconcile → rc=0",
        "python3 -I tools/dispatch-occupancy-check.py --selftest → rc=0",
    ],
    "allowed_paths": ["README.md"],
    "depends_on": ["factory-os#20"],
    "evidence": [
        "README.md:12（收录口径段，∈ allowed_paths）",
        "tools/card-selfcontainment-check.py:52（本件 rc 三态面；判官面只读）",
        "tools/dispatch-occupancy-check.py:52（形态参考；判官面只读）",
    ],
    "not_doing": ["禁扩权：判据只许六项（Q1 §3.1），修卡回 planner 不代劳",
                  "不改 planner.yml 判据段（sha256 互钉对账代替直改）"],
    "env_precondition": "python3（runner 基线）",
}


def _copy(card, **kw):
    c = json.loads(json.dumps(card, ensure_ascii=False))
    c.update(kw)
    return c


def run_selftest(out):
    """12 夹具（6 正 6 反，每项机检正反例各一）+ 补充 drills。

    全部注入桩（仓树面/CODEOWNERS/base 探针均为内存桩）⇒ 零网络、零真树读取。
    """
    fails = []
    n = 0
    tree = _stub_tree()
    alive = lambda base: ("ALIVE", "stub：远端实读集命中")          # noqa: E731
    dead = lambda base: ("DEAD", "stub：远端实读集零命中")          # noqa: E731

    def face_of(res, key):
        for f in res["faces"]:
            if f["check"].startswith(key):
                return f
        return {"verdict": "MISSING"}

    def run(card, tp=None):
        res, rc = run_check(card, tree=tree, base_probe=tp or alive,
                            co_pats=STUB_CO_PATS, co_repo="factory-os", out=out)
        return res, rc

    # ── 六正例（每项机检正例各一；其余五项在同卡上保持通过 ⇒ 整体 rc=0）──
    positives = [
        ("P1 ① 验收命令可解析", BASE_CARD, "①", "PASS", 0),
        ("P2 ② pinned base 实读存活", BASE_CARD, "②", "PASS", 0),
        ("P3 ③ 证据带 path:line", BASE_CARD, "③", "PASS", 0),
        ("P4 ④ depends_on+不做什么", BASE_CARD, "④", "PASS", 0),
        ("P5 ⑤ allowed_paths 纪律", BASE_CARD, "⑤", "PASS", 0),
        ("P6 ⑥ 环境前置一致", _copy(BASE_CARD,
                                   acceptance=["cargo test --workspace → rc=0"],
                                   env_precondition="rust（cargo 工具链）+ python3"), "⑥", "PASS", 0),
    ]
    for name, card, key, want, want_rc in positives:
        n += 1
        res, rc = run(card)
        fv = face_of(res, key)["verdict"]
        if fv != want or rc != want_rc:
            fails.append("%s：面 %s 应 %s、rc 应 %d（得 %s rc=%d）"
                         % (name, key, want, want_rc, fv, rc))
        else:
            out.append("  [夹具 %s] %s ⇒ %s（rc=%d）" % (name.split()[0], key, fv, rc))

    # ── 六反例（每项机检反例各一：只动该项，其余保持 ⇒ 整体 rc=1 invalid）──
    negatives = [
        ("N1 ① 反：验收缺 → rc=N", _copy(BASE_CARD, acceptance=[
            "python3 -I tools/card-selfcontainment-check.py --selftest → rc=0",
            "python3 -I tools/dispatch-occupancy-check.py --selftest"]), "①", "INVALID", 1),
        ("N2 ② 反：钉桩远端零命中", BASE_CARD, "②", "INVALID", 1),
        ("N3 ③ 反：证据无 path:line", _copy(BASE_CARD, evidence=[
            "见上次讨论的结论", "证据在运营者脑子里"]), "③", "INVALID", 1),
        ("N4 ④ 反：缺「不做什么」（灰卡形）", _copy(BASE_CARD, not_doing=[]), "④", "INVALID", 1),
        ("N5 ⑤ 反：撞判官面", _copy(BASE_CARD, allowed_paths=["tools/all-gates.sh"]), "⑤", "INVALID", 1),
        ("N6 ⑥ 反：cargo 命令族无环境点名", _copy(BASE_CARD, acceptance=[
            "cargo test --workspace → rc=0"], env_precondition=""), "⑥", "INVALID", 1),
    ]
    for name, card, key, want, want_rc in negatives:
        n += 1
        res, rc = run(card, tp=dead if key == "②" else alive)
        fv = face_of(res, key)["verdict"]
        if fv != want or rc != want_rc:
            fails.append("%s：面 %s 应 %s、rc 应 %d（得 %s rc=%d）"
                         % (name, key, want, want_rc, fv, rc))
        else:
            out.append("  [夹具 %s] %s ⇒ %s（rc=%d）" % (name.split()[0], key, fv, rc))

    # ── 补充 drills（12 之外的判别力补强；不计入 6+6 读数）──
    supp = [
        ("T13 ⑤a 幻指路径（件/glob/父目录皆无）",
         _copy(BASE_CARD, allowed_paths=["nonexistent-dir/foo.py"]), "⑤", "INVALID", 1, alive),
        ("T14 ④a depends_on 不可解析",
         _copy(BASE_CARD, depends_on=["等运营者确认再定"]), "④", "INVALID", 1, alive),
        ("T15 ② 无 base 且无补钉标记", _copy(BASE_CARD, base=None, base_note=""), "②", "INVALID", 1, alive),
        ("T16 ③ 证据引用越出 allowed∪判官面",
         _copy(BASE_CARD, evidence=["docs/other.md:5（仓内非白名册路径）"]), "③", "INVALID", 1, alive),
        ("T17 ⑥ 环境段点名超集（不拦）",
         _copy(BASE_CARD, acceptance=["cargo test → rc=0"],
               env_precondition="rust + docker + gpu（超集声明）"), "⑥", "PASS", 0, alive),
        ("T18 ⑤ 新建件合法形态（父目录在场 ⇒ 过）",
         _copy(BASE_CARD, allowed_paths=["波次清单/wave-07.json"],
               evidence=["波次清单/wave-03.json:1（形制参考，∈ allowed 目录）",
                         "tools/dispatch-occupancy-check.py:52（判官面只读）"]),
         "⑤", "PASS", 0, alive),
    ]
    for name, card, key, want, want_rc, tp in supp:
        n += 1
        res, rc = run(card, tp=tp)
        fv = face_of(res, key)["verdict"]
        if fv != want or rc != want_rc:
            fails.append("%s：面 %s 应 %s、rc 应 %d（得 %s rc=%d）"
                         % (name, key, want, want_rc, fv, rc))
        else:
            out.append("  [夹具 %s] %s ⇒ %s（rc=%d）" % (name.split()[0], key, fv, rc))

    # T19 fail-loud：树面缺席 ⇒ 存在性不可证 ⇒ rc=2（不出闸，不猜绿）
    n += 1
    res, rc = run_check(BASE_CARD, tree=None, base_probe=alive,
                        co_pats=STUB_CO_PATS, co_repo="factory-os", out=out)
    if res["verdict"] != "FAIL-LOUD" or rc != 2:
        fails.append("T19 树面缺席应 FAIL-LOUD rc=2（得 %s rc=%d）" % (res["verdict"], rc))
    else:
        out.append("  [夹具 T19] 树面缺席 ⇒ FAIL-LOUD（rc=2，不可证不出闸）")

    # T20 fail-loud：base 探针不可证（UNKNOWN）⇒ rc=2
    n += 1
    unknown_p = lambda base: ("UNKNOWN", "stub：ls-remote 实读失败")   # noqa: E731
    res, rc = run_check(BASE_CARD, tree=tree, base_probe=unknown_p,
                        co_pats=STUB_CO_PATS, co_repo="factory-os", out=out)
    if res["verdict"] != "FAIL-LOUD" or rc != 2:
        fails.append("T20 base 不可证应 FAIL-LOUD rc=2（得 %s rc=%d）" % (res["verdict"], rc))
    else:
        out.append("  [夹具 T20] base 不可证 ⇒ FAIL-LOUD（rc=2）")

    # T21 markdown 卡面解析回归（planner card_face 段式 + 人工卡面 ## 段式）
    n += 1
    md = ("## 禁项（置顶）\n"
          "- 禁改判官/门禁/判据件\n"
          "- 禁 --force / force-push\n"
          "\n"
          "证据：tools/dispatch-occupancy-check.py:52（形态参考，判官面只读）\n"
          "\n"
          "【任务】`w07-fixture-md`\n"
          "【债号】`D-97`\n"
          "【通道】`bot-lane`\n"
          "【pinned base】aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa（钉桩基线 SHA）\n"
          "【验收命令集】（逐条退出码）\n"
          "- [ ] python3 -I tools/card-selfcontainment-check.py --selftest → rc=0\n"
          "【依赖】factory-os#20\n"
          "【允许路径】README.md\n"
          "## 本卡不做什么\n"
          "- 不动判据段\n")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(md)
        md_path = tf.name
    try:
        card = load_card(md_path=md_path)
        ok = (card.get("task_id") == "w07-fixture-md" and card.get("debt") == "D-97"
              and card.get("base") == "a" * 40
              and len(card.get("acceptance") or []) == 1
              and card.get("allowed_paths") == ["README.md"]
              and card.get("depends_on") == ["factory-os#20"]
              and bool(card.get("not_doing"))
              and card.get("env_precondition") == ""
              and len(card.get("evidence") or []) >= 1)
        res, rc = run_check(card, tree=tree, base_probe=alive,
                            co_pats=STUB_CO_PATS, co_repo="factory-os", out=out)
        if not ok:
            fails.append("T21 markdown 卡面解析回归失败：%s" % json.dumps(
                {k: card.get(k) for k in ("task_id", "debt", "base", "acceptance",
                                          "allowed_paths", "depends_on", "not_doing",
                                          "env_precondition", "evidence")},
                ensure_ascii=False)[:400])
        elif res["verdict"] != "PASS" or rc != 0:
            fails.append("T21 md 卡面应 PASS rc=0（得 %s rc=%d：%s）"
                         % (res["verdict"], rc, res["blocking"]))
        else:
            out.append("  [夹具 T21] markdown 卡面解析+六项全过 ⇒ PASS（rc=0）")
    finally:
        os.unlink(md_path)

    if fails:
        out.append("FAIL selftest %d/%d 过：" % (n - len(fails), n))
        for f in fails:
            out.append("  " + f)
        return 1
    out.append("selftest %d/%d 过（6 正 6 反逐项机检 + 补充 drills T13-T21："
               "幻指/依赖不可解/无 base 无补钉/证据越出/环境超集/新建件合法形态/"
               "树面缺席 fail-loud/base 不可证 fail-loud/md 卡面解析回归）" % (n, n))
    return 0


# ---------------------------------------------------------------- 双端对账

def _pin_mirror_ok(pin, mode, mirror):
    """钉桩片段的语义镜像核对：镜像 = 本件实现的规则常量。

    mode: exact（r 串拼接全等；无 r 串则引号串清单全等）｜paren-insensitive
    （去捕获组后全等——M-1 与 08b 的 (\\d+)/\\d+ 之差即捕获组）｜contains（引号串
    集合超集，ls-remote refspecs）｜verbatim（仅逐字+sha，实现镜像见 rule impl 注）。
    """
    frag = pin["fragment"]
    if mode == "verbatim":
        return True, "verbatim（实现镜像见 impl 注）"
    if mode == "paren-insensitive":
        joined = "".join(re.findall(r'r"((?:[^"\\]|\\.)*)"', frag))
        norm = lambda s: re.sub(r"[()]", "", s)              # noqa: E731
        return (norm(joined) == norm(mirror)), "片段正则=%r" % joined[:80]
    if mode == "exact":
        joined = "".join(re.findall(r'r"((?:[^"\\]|\\.)*)"', frag))
        if joined:
            return (joined == mirror), "片段正则=%r" % joined[:80]
        quoted = re.findall(r'"([^"]*)"', frag)
        return (quoted == list(mirror)), "片段引号串=%s" % (quoted[:3],)
    if mode == "contains":
        quoted = re.findall(r'"([^"]*)"', frag)
        return (set(mirror) <= set(quoted)), "片段引号串=%s" % (quoted[:4],)
    return False, "未知 mirror mode %r" % mode


def run_reconcile(planner_path, out=None):
    """双端一致：RULE_TABLE 共享规则 × planner.yml step 08 规则段 diff/钉值对账。

    零漂移判据：每条 pin 的片段在 step 08 段逐字在场（diff）+ sha256 复核
    （钉值）+ 语义镜像（本件实现的规则常量与片段同形）。任一不过 ⇒ DRIFT。
    返回 (report, rc)：rc=0 零漂移；rc=1 漂移；2=fail-loud（planner 缺场）。
    """
    out = out if out is not None else []
    if not os.path.isfile(planner_path):
        out.append("FAIL planner.yml 不在位：%s（对账无从做起 ⇒ fail-loud）" % rel(planner_path))
        return None, 2
    with open(planner_path, "r", encoding="utf-8") as f:
        text = f.read()
    out.append("RECONCILE · 规则表单源化对账（审卡闸 RULE_TABLE × planner.yml step 08）")
    out.append("  planner：%s（%d 行）" % (rel(planner_path), len(text.splitlines())))
    out.append("  规则表 sha256（本件 RULE_TABLE 钉值）：%s" % RULE_TABLE_SHA256)
    rows, drift = [], []
    for rule in RULE_TABLE["shared"]:
        for pin in rule["pins"]:
            frag = pin["fragment"]
            pos = text.find(frag)
            cnt = text.count(frag)
            sha_ok = (pos >= 0) and (sha256_hex(frag) == pin["sha256"])
            line_no = text[:pos].count("\n") + 1 if pos >= 0 else None
            ok_m, mirror_detail = _pin_mirror_ok(pin, pin.get("mirror_mode")
                                                 or rule.get("mirror_mode", "verbatim"),
                                                 rule.get("mirror"))
            same = (cnt >= 1) and sha_ok and ok_m
            rows.append({"rule": rule["rule"], "pin": pin["label"],
                         "lines": pin["lines"], "found_at_line": line_no,
                         "occurrences": cnt, "sha256_ok": sha_ok,
                         "mirror_ok": ok_m, "mirror": mirror_detail,
                         "verdict": "SAME" if same else "DRIFT"})
            out.append("  [%s] %s · step08:%d-%d → %s（现读行 %s｜出现 %d 次｜sha %s｜镜像 %s）"
                       % (rule["rule"], pin["label"], pin["lines"][0], pin["lines"][1],
                          rows[-1]["verdict"], line_no, cnt,
                          "合" if sha_ok else "异", "合" if ok_m else "异"))
            if not same:
                drift.append("%s %s" % (rule["rule"], pin["label"]))
    out.append("  —— 审卡闸独有项（step 08 未落，不参与双端 diff；出处见 RULE_TABLE）——")
    for g in RULE_TABLE["gate_only"]:
        out.append("  [%s] %s —— %s" % (g["rule"], g["criterion"], g["note"]))
    out.append("  —— planner 侧独有项（不属六要件判据；登记边界，禁扩权）——")
    for p in RULE_TABLE["planner_only"]:
        out.append("  [%s] %s" % (p["rule"], p["criterion"]))
    report = {
        "schema": "af.card.selfcontainment.reconcile.v1",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "planner": rel(planner_path),
        "rule_table_sha256": RULE_TABLE_SHA256,
        "pins_total": len(rows),
        "pins_same": sum(1 for r in rows if r["verdict"] == "SAME"),
        "drift": drift,
        "zero_drift": not drift,
        "rows": rows,
        "gate_only": RULE_TABLE["gate_only"],
        "planner_only": RULE_TABLE["planner_only"],
    }
    if drift:
        out.append("  判定：**DRIFT**（%d/%d 条漂移：%s）——两处各自演化，同批重钉后才许出门"
                   % (len(drift), len(rows), "；".join(drift[:6])))
        return report, 1
    out.append("  判定：**ZERO-DRIFT**（%d/%d 条 pin 逐字+sha256+语义镜像全合）"
               % (len(rows), len(rows)))
    return report, 0


# ---------------------------------------------------------------- RULE_TABLE
# 规则表单源化（施工步 2）：本件即审卡闸侧规则定义件（单一真源）；step 08 侧片段
# 以 sha256 互钉对账（--reconcile 回读零漂移）。shared=双端同款（禁两处各自演化）；
# gate_only=审卡闸独有（step 08 明示未落）；planner_only=planner 侧不属六要件。
# pins 由 gen_pins.py 自 planner.yml 逐字抽取生成（2026-11-07，origin/main）。
RULE_TABLE = {"schema": "af.card.selfcontainment.rules.v1", "shared": [], "gate_only": [], "planner_only": []}
RULE_TABLE["shared"] = [
    {"rule": "R1", "check": "①", "criterion": "验收命令期望退出码形制「→ rc=N」",
     "step08_ref": "planner.yml step 08 M-1 主段 + step 08b ACC_RX 干跑腿",
     "impl": "本件 RC_RE（check_acceptance：每条 acceptance 必含该形制，缺 ⇒ invalid）",
     "mirror_mode": "paren-insensitive", "mirror": RC_RE.pattern, "on_miss": "invalid",
     "pins": []},
    {"rule": "R2", "check": "②", "criterion": "base_sha 十六进制形制（7-40 位）",
     "step08_ref": "planner.yml step 08 M-3 形制面",
     "impl": "本件 SHA_RE（check_base：SHA 形制判定 + ref 名走存在性探针）",
     "mirror_mode": "exact", "mirror": SHA_RE.pattern, "on_miss": "invalid",
     "pins": []},
    {"rule": "R3", "check": "②", "criterion": "pinned base 对仓实读（ls-remote 形态：refspecs + 全等/前缀命中）",
     "step08_ref": "planner.yml step 08 M-3 实读面",
     "impl": "本件 probe_base_lsremote（LS_REMOTE_REFSPECS 同款；分支名走 ref 存在性，Q1 #2 第二形）",
     "mirror_mode": "contains", "mirror": list(LS_REMOTE_REFSPECS), "on_miss": "invalid/不可证 fail-loud",
     "pins": []},
    {"rule": "R4", "check": "⑤", "criterion": "allowed_paths 存在三形态（件本体/glob/父目录）",
     "step08_ref": "planner.yml step 08 M-2",
     "impl": "本件 tree_hit（check_paths：同三形态；父目录在场=新建件合法形态）",
     "mirror_mode": "verbatim", "mirror": None, "on_miss": "invalid（禁幻指）",
     "pins": []},
    {"rule": "R5", "check": "⑤", "criterion": "判官面关键词族",
     "step08_ref": "planner.yml step 08 M-4 JUDGE_KEYWORD",
     "impl": "本件 JUDGE_KEYWORD（judge_hit 第一源，逐字同）",
     "mirror_mode": "exact", "mirror": JUDGE_KEYWORD.pattern, "on_miss": "invalid（硬红）",
     "pins": []},
    {"rule": "R6", "check": "⑤", "criterion": "判官面 af 静态族",
     "step08_ref": "planner.yml step 08 M-4 AF_JUDGE_FAMILY",
     "impl": "本件 AF_JUDGE_FAMILY（judge_hit 第二源，逐字同）",
     "mirror_mode": "exact", "mirror": AF_JUDGE_FAMILY.pattern, "on_miss": "invalid（硬红）",
     "pins": []},
    {"rule": "R7", "check": "⑤", "criterion": "判官面 factory-os 派生缺口",
     "step08_ref": "planner.yml step 08 M-4 JUDGE_STATIC_FACTORYOS",
     "impl": "本件 JUDGE_STATIC_FACTORYOS（逐字同）",
     "mirror_mode": "exact", "mirror": list(JUDGE_STATIC_FACTORYOS), "on_miss": "invalid（硬红）",
     "pins": []},
    {"rule": "R8", "check": "⑤", "criterion": "判官面 CODEOWNERS 派生读法",
     "step08_ref": "planner.yml step 08 M-4 codeowners_patterns",
     "impl": "本件 codeowners_patterns_from_text + codeowners_hit（同读法：跳过 #/★ 行、取 parts[1] @ 开头的锁面）",
     "mirror_mode": "verbatim", "mirror": None, "on_miss": "invalid（硬红）",
     "pins": []},
    {"rule": "R9", "check": "⑤", "criterion": "跨仓/工作区裸前缀警告面",
     "step08_ref": "planner.yml step 08 M-2 CROSS_TREE_BARE",
     "impl": "本件 CROSS_TREE_BARE（path_scope：对不上仓树 repo 的裸前缀 ⇒ warning 不假红）",
     "mirror_mode": "exact", "mirror": list(CROSS_TREE_BARE), "on_miss": "warning（不可核不假红）",
     "pins": []},
    {"rule": "R10", "check": "④", "criterion": "depends_on 板号形制 repo#n",
     "step08_ref": "planner.yml step 08 M-7",
     "impl": "本件 DEP_REPO_FORM（check_deps 三形之一；指向有效性由 planner 侧持同波集/台账锚集终裁——本闸判形制）",
     "mirror_mode": "exact", "mirror": DEP_REPO_FORM.pattern, "on_miss": "invalid",
     "pins": []},
    {"rule": "R11", "check": "④", "criterion": "task_id 形制（同波引用判据的形制面）",
     "step08_ref": "planner.yml step 08 十字段 task_id 校验",
     "impl": "本件 TASK_ID_FORM（check_deps 三形之二）",
     "mirror_mode": "exact", "mirror": TASK_ID_FORM.pattern, "on_miss": "invalid",
     "pins": []},
]
RULE_TABLE["gate_only"] = [
    {"rule": "G1b", "check": "①", "criterion": "命令首词允许集 + 命令指向路径树上对账",
     "note": "Q1 §3.1 #1 第一/第三判据；step 08 侧只有 M-1 形制闸，首词/路径对账在 08b 干跑腿（classify_head 同族思路）——审卡闸按 Q1 判据落地"},
    {"rule": "G3", "check": "③", "criterion": "证据段 path:line 坐标 ≥1 且引用 ∈ allowed_paths ∪ 判官面",
     "note": "Q1 §3.1 #3；planner 自动卡面（十字段）无证据段，故 step 08 未落——审卡闸补面项"},
    {"rule": "G4b", "check": "④", "criterion": "「本卡不做什么」节非空",
     "note": "Q1 §3.1 #4 / 派发契约要件6 边界节；planner card_face 未产该段——审卡闸补面项（灰卡拦截口）"},
    {"rule": "G6", "check": "⑥", "criterion": "环境前置段点名集 ⊇ 命令族非基线工具需求",
     "note": "Q1 §3.1 #6；#19（D-83）禁项明示「env_precondition 与命令族一致性校验留干跑/沙箱自检，本卡不扩权」——step 08 有意未落，审卡闸补面项"},
]
RULE_TABLE["planner_only"] = [
    {"rule": "M-5", "criterion": "mem_budget_g 通道界 + 波次 Σ45G/Σ3G/并发4（十校验既有项）"},
    {"rule": "M-6", "criterion": "防双解占用（板 open 卡/历史非终态/台账锚）"},
    {"rule": "M-8", "criterion": "label 词汇对齐板面正本 BOARD_VOCAB"},
    {"rule": "十校验既有", "criterion": "schema/wave/created/policy/budgets/十字段/async↔bot-lane/merge_policy/ledger/state=queued/凭据形扫/空波 preflight"},
]

# step 08 钉桩片段（gen_pins.py 自 planner.yml 逐字抽取 + sha256；禁手改——
# 改 pins 视同改规则表，必须同批重跑 gen_pins.py 并在变更日志留痕）
PINS_JSON = r"""
[
 {
  "rule": "R1",
  "label": "M-1 acceptance 期望退出码形制（step 08 主段）",
  "lines": [
   1504,
   1504
  ],
  "fragment": "                      if not re.search(r\"→\\s*rc\\s*=\\s*\\d+\", a):",
  "sha256": "5a1c3bfe58087fd8f54dd76f76ad6c32244079db74a24090ebd3e96c722841a3",
  "line_count": 1
 },
 {
  "rule": "R1",
  "label": "M-1 同族正则（step 08b ACC_RX 干跑腿）",
  "lines": [
   1760,
   1760
  ],
  "fragment": "          ACC_RX = re.compile(r\"→\\s*rc\\s*=\\s*(\\d+)\")",
  "sha256": "80e9ebf5f0a657135d86a400e07680db763b438c921c66b926b408b0c99f538a",
  "line_count": 1
 },
 {
  "rule": "R2",
  "label": "M-3 base_sha 十六进制形制",
  "lines": [
   1357,
   1357
  ],
  "fragment": "              if not isinstance(base_sha, str) or not re.fullmatch(r\"[0-9a-f]{7,40}\", base_sha):",
  "sha256": "7722dc1c88688679dfae409862e5ac132e9a4a30f51f37f4fb80f0d062fd7b5e",
  "line_count": 1
 },
 {
  "rule": "R3",
  "label": "M-3 pinned base 对仓实读命令（ls-remote 形态）",
  "lines": [
   1368,
   1369
  ],
  "fragment": "                      [\"git\", \"-C\", \"factory-os\", \"ls-remote\", \"origin\",\n                       \"refs/heads/*\", \"refs/tags/*\", \"refs/pull/*/head\"],",
  "sha256": "9d11a4e593673df3a6b0abbc25a5afb44b7c4792472e38a66e21c67363119677",
  "line_count": 2
 },
 {
  "rule": "R3",
  "label": "M-3 命中判据（全等或前缀）",
  "lines": [
   1378,
   1379
  ],
  "fragment": "                      if not any(s == base_sha or s.startswith(base_sha)\n                                 for s in remote_shas):",
  "sha256": "ea27635718e92ca5f095e508aae7c3411f00ac521e6bcb2a83387e0474f05041",
  "line_count": 2,
  "mirror_mode": "verbatim"
 },
 {
  "rule": "R4",
  "label": "M-2 allowed_paths 存在三形态（件/glob/父目录）",
  "lines": [
   1492,
   1494
  ],
  "fragment": "                      if (glob.glob(p) or os.path.exists(p)\n                              or (parent and os.path.exists(os.path.join(\"factory-os\", parent)))):\n                          continue",
  "sha256": "a50d36fc4e201ee560414938eb51235ac7cea7c0ac62113f7fb66f1760cec5a2",
  "line_count": 3
 },
 {
  "rule": "R5",
  "label": "M-4 判官面关键词族 JUDGE_KEYWORD",
  "lines": [
   1229,
   1232
  ],
  "fragment": "          JUDGE_KEYWORD = re.compile(\n              r\"(all-gates\\.sh|gate-pins\\.list|gate-pins-refresh|gate_inputs|subgates\\.list\"\n              r\"|mirror-scan-allowlist|clippy-baseline|scorechain-manifest|CODEOWNERS\"\n              r\"|judge|判官|判据)\")",
  "sha256": "67b06cd26a0684fc22f9f212c402cc01cd42779b59d35e2a8cc9b11337bc206b",
  "line_count": 4
 },
 {
  "rule": "R6",
  "label": "M-4 判官面 af 静态族 AF_JUDGE_FAMILY",
  "lines": [
   1233,
   1237
  ],
  "fragment": "          AF_JUDGE_FAMILY = re.compile(\n              r\"(?:^|[:/`])(ci/|proofs/|strategies/|packages/reportkit/\"\n              r\"|crates/af-execline/src/judge\\.rs|(?:[^\\s`]*/)?crates/.*/tests/\"\n              r\"|numbers\\.json|deliverables\\.yaml|doc-claims\\.txt\"\n              r\"|rust-toolchain\\.toml|Cargo\\.toml|Cargo\\.lock)\")",
  "sha256": "b6fcab18da2673864d4c65836f9a87eb0c87b89a7b0dc6cf4816d004ff26eabf",
  "line_count": 5
 },
 {
  "rule": "R7",
  "label": "M-4 判官面 factory-os 派生缺口 JUDGE_STATIC_FACTORYOS",
  "lines": [
   1238,
   1238
  ],
  "fragment": "          JUDGE_STATIC_FACTORYOS = (\".github/workflows/gates.yml\",)",
  "sha256": "01ca94d0653e448cb6f1dfb383164fa86246f765fd8c96d9f9fecf551129ee48",
  "line_count": 1
 },
 {
  "rule": "R8",
  "label": "M-4 CODEOWNERS 派生读法 codeowners_patterns",
  "lines": [
   1255,
   1269
  ],
  "fragment": "          def codeowners_patterns():\n              pats = []\n              co = os.path.join(\"factory-os\", \"CODEOWNERS\")\n              if os.path.exists(co):\n                  with open(co, encoding=\"utf-8\") as f:\n                      for ln in f:\n                          ln = ln.strip()\n                          if not ln or ln.startswith(\"#\") or ln.startswith(\"★\"):\n                              continue\n                          parts = ln.split()\n                          if len(parts) >= 2 and parts[1].startswith(\"@\"):\n                              pats.append(parts[0])\n              else:\n                  warnings.append(\"M-4: factory-os/CODEOWNERS 缺场——判官面①源退化，仅余②静态族\")\n              return pats",
  "sha256": "ac7b3de345d61e567c85bf9c28aff8844a3eb00534b5e49b3ec1d26671d449c3",
  "line_count": 15
 },
 {
  "rule": "R9",
  "label": "M-2 跨仓/工作区裸前缀警告面 CROSS_TREE_BARE",
  "lines": [
   1241,
   1243
  ],
  "fragment": "          CROSS_TREE_BARE = (\"af/\", \"crates/\", \"ci/\", \"proofs/\", \"strategies/\",\n                             \"packages/\", \"poc/\", \"kb-seed\", \"计划/\", \"30-工件/\",\n                             \"staging/\", \"外派\", \"状态/\")",
  "sha256": "3867d2c38d718b8830ff477edad06a522389590c3a505862f8ec199357904474",
  "line_count": 3
 },
 {
  "rule": "R10",
  "label": "M-7 depends_on 板号形制 repo#n",
  "lines": [
   1543,
   1543
  ],
  "fragment": "                      if re.fullmatch(r\"([A-Za-z0-9._-]+)?#\\d+\", head):",
  "sha256": "98403c6aac78dea8f6f3597edcdeb7706dae0a2eb07285b735ee7c8642f8970e",
  "line_count": 1
 },
 {
  "rule": "R11",
  "label": "task_id 形制（同波引用判据的形制面）",
  "lines": [
   1424,
   1424
  ],
  "fragment": "              if not re.fullmatch(r\"[a-z0-9][a-z0-9._-]{2,63}\", tid):",
  "sha256": "3556215eabfee5ad5ae0a738d702914d150d25d858fd7682ab9cb67ef646e469",
  "line_count": 1
 }
]
"""


def _load_pins():
    for pin in json.loads(PINS_JSON):
        for rule in RULE_TABLE["shared"]:
            if rule["rule"] == pin["rule"]:
                rec = {"label": pin["label"], "lines": pin["lines"],
                       "fragment": pin["fragment"], "sha256": pin["sha256"]}
                if pin.get("mirror_mode"):
                    rec["mirror_mode"] = pin["mirror_mode"]   # pin 级覆盖（见 gen_pins.py）
                rule["pins"].append(rec)
    got = sum(len(r["pins"]) for r in RULE_TABLE["shared"])
    if got != len(json.loads(PINS_JSON)):
        raise SystemExit("RULE_TABLE pins 装载不全：%d/%d" % (got, len(json.loads(PINS_JSON))))


_load_pins()


# 规则表钉值：RULE_TABLE 规范化 JSON 的 sha256（含 pins 全量——规则表自身漂移可检）
def _rule_table_sha():
    snap = json.loads(json.dumps(RULE_TABLE, ensure_ascii=False))
    return sha256_hex(json.dumps(snap, ensure_ascii=False, sort_keys=True))


RULE_TABLE_SHA256 = _rule_table_sha()


# ---------------------------------------------------------------- CLI

def main(argv):
    out = []
    if "--selftest" in argv:
        rc = run_selftest(out)
        for ln in out:
            print(ln)
        return rc

    import argparse
    p = argparse.ArgumentParser(
        prog="card-selfcontainment-check.py",
        description="审卡闸机检（六要件）：①验收命令 ②pinned base ③证据 path:line "
                    "④依赖+不做什么 ⑤allowed_paths+判官面 ⑥环境前置；rc 0=pass/1=invalid/2=fail-loud")
    p.add_argument("--card-json", help="卡 JSON（manifest 卡/v1.1 可选字段面）")
    p.add_argument("--card-md", help="卡面 markdown（planner card_face 段式或人工卡面 ## 段式）")
    p.add_argument("--tree-file", help="仓树清单件（首行可带 '# repo: owner/name'）")
    p.add_argument("--repo-root", help="目标仓本地 clone（git ls-tree 只读取树）")
    p.add_argument("--tree-ref", help="仓树取哪个 ref（缺省 HEAD；建议 = pinned base）")
    p.add_argument("--remote", default="origin", help="ls-remote 远端名（缺省 origin）")
    p.add_argument("--repo", help="目标仓 owner/name（base API 探针用）")
    p.add_argument("--base-probe", choices=["ls-remote", "api"], default=None,
                   help="base 存活性探针形态（缺省：有 --repo-root 用 ls-remote，否则有 --repo 用 api）")
    p.add_argument("--codeowners-file", default=None,
                   help="判官面 CODEOWNERS（缺省：--repo-root/CODEOWNERS 或仓内 CODEOWNERS）")
    p.add_argument("--planner", default=DEFAULT_PLANNER, help="planner.yml 路径（--reconcile 用）")
    p.add_argument("--reconcile", action="store_true", help="连同双端规则表对账一起跑")
    p.add_argument("--out", help="verdict JSON 落点（留痕，供 bot-bridge 消费）")
    p.add_argument("--json", action="store_true", help="stdout 打 JSON")
    args = p.parse_args(argv)

    reconcile_report = None
    if args.reconcile:
        rep, rcode = run_reconcile(args.planner, out=out)
        if rcode != 0:
            for ln in out:
                print(ln)
            print("FAIL 双端规则表对账未过（rc=%d）——先重钉再审卡" % rcode, file=sys.stderr)
            return rcode if rcode else 2
        reconcile_report = rep

    if not args.card_json and not args.card_md:
        for ln in out:
            print(ln)
        if not args.reconcile:
            p.print_help()
        return 0 if args.reconcile else 2

    try:
        card = load_card(json_path=args.card_json, md_path=args.card_md)
    except Exception as exc:                   # noqa: BLE001
        print("FAIL 卡面不可解析：%s（fail-loud，不出闸）" % exc, file=sys.stderr)
        return 2

    # 仓树面
    tree = None
    try:
        if args.tree_file:
            tree = RepoTree.from_file(args.tree_file)
        elif args.repo_root:
            tree = RepoTree.from_repo_root(args.repo_root, ref=args.tree_ref)
    except Exception as exc:                   # noqa: BLE001
        print("FAIL 仓树面不可读：%s（fail-loud，不出闸）" % exc, file=sys.stderr)
        return 2

    # 判官面 CODEOWNERS（缺场 = ①源退化 warning，仅余静态族——同 step 08 纪律）
    co_path = args.codeowners_file
    if not co_path and args.repo_root:
        co_path = os.path.join(args.repo_root, "CODEOWNERS")
    if not co_path and os.path.isfile(DEFAULT_CODEOWNERS):
        co_path = DEFAULT_CODEOWNERS
    co_pats, co_src = [], None
    if co_path and os.path.isfile(co_path):
        with open(co_path, "r", encoding="utf-8") as f:
            co_pats = codeowners_patterns_from_text(f.read())
        co_src = rel(co_path)
    co_repo = tree.repo_name if tree is not None else "factory-os"
    if not co_pats:
        out.append("  提示：判官面①源（CODEOWNERS）缺场——仅余②静态族（同 step 08 M-4 退化纪律）")

    # base 探针
    mode = args.base_probe
    if mode is None:
        mode = "ls-remote" if args.repo_root else ("api" if args.repo else None)
    base_probe = None
    if mode == "ls-remote" and args.repo_root:
        base_probe = lambda b: probe_base_lsremote(args.repo_root, args.remote, b)  # noqa: E731
    elif mode == "api" and args.repo:
        base_probe = lambda b: probe_base_api(args.repo, b)                         # noqa: E731

    result, rc = run_check(card, tree=tree, base_probe=base_probe,
                           co_pats=co_pats, co_repo=co_repo, out=out)
    if reconcile_report:
        result["reconcile"] = reconcile_report
    if co_src:
        result["judge_face_source"] = {"codeowners": co_src, "patterns": len(co_pats),
                                       "static_factoryos": list(JUDGE_STATIC_FACTORYOS)}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        out.append("  verdict 留痕：%s（schema %s）" % (args.out, result["schema"]))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for ln in out:
            print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
