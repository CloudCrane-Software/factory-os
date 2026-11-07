#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cnb-verdict-reply.py — verdict 落定后的回卡与板面翻格件（D-133 · factory-os#148）。

定位（卡面 [真锚][D-133] factory-os#148 · task_id=cnb-verdict-reply · owner-track）
----
判分腿（tools/swev-judge-v2.py，判据面零改动）吐出 judge.json 之后，「回卡」与
「板面翻格」目前仍是运营者人工逐条做：读 judge.json → 手写回卡评论 → 手翻
state:* 标签 → 手抄台账行。D-117 全环实证（30-工件/夜轨A2-20261107/判分读数.md
§八，:111-120）把这条链走通了，但每一步都是人工。本件把它固化为一个 CLI：

  输入  judge.json（verdict / diff_valid / log_state / F2P·P2P 计数 / diff_sha256）
        ＋ 卡号（GitHub issue 号）＋ 债号 ＋ 失配归因结构级摘要（可缺省，见
        derive_attribution）＋ patch sha256（缺省取 judge.json 的 diff_sha256）

  输出① 回卡评论渲染——D-117 回卡实证**六要素**形制（判分读数.md:120 六要素表）：
        ① verdict 原值 ② patch sha256[:12] 指纹 ③ F2P/P2P **计数**（只给计数）
        ④ 失配归因（**结构级**）⑤ 零凭据形态 ⑥ 测试清单只给计数。
        公开面纪律（卡面 P2）**内置**在渲染路径上：judge.json 只读计数字段
        （结构性不碰任何用例 ID 列），渲染后过 scrub 预检（fail-closed）才准贴板。

  输出② `PUT /issues/{n}/labels` 翻 `state:*`（S8 建议原文点名的 API 形制）：
        resolved ⇒ state:merged；非 resolved ⇒ state:rejected（P5 禁假绿：
        verdict=not_resolved 也如实回卡，禁把失败卷渲染成成功）。
        **只翻 state:* 族**（卡面 P4）：既有 label（wave 等）原样保留；
        quality:* 归回评器 tools/planner-quality-score.py，本件不碰。
        --post 才真写；缺省 --render 干跑只渲染（零网络零板写）。

  输出③ 台账行回填**人读草案**（占用闸 / 时间轴 / 人工现身计数三字段文案）。
        卡面 P3：**禁自动写账本**——本件零账本写入路径，草案只作文本；
        登记落账本走正路（PR 流 + owner 批；双正本格局 D-123 在册）。

模式（三态互斥；缺省 --render）
----
  --render（干跑，零板写零网络）  渲染三输出到 stdout（或 --out 落盘）。
  --post（真写板）                POST 评论 + PUT state:* 标签。
                                  硬闸：--issue 必须 >0、token 必须经环境量现取、
                                  评论必须过 scrub 预检——缺一即拒（fail-closed）。
  --selftest（夹具，零网络零板写） tools/fixtures/cnb-verdict-reply/ 驱动：
                                  resolved⇒state:merged、not_resolved⇒state:rejected
                                  两态断言 + 六要素在场断言 + scrub 预检断言
                                  （正例 clean / 反例必红）+ 零板写断言。

凭据纪律（卡面 P1/P2）
----
本件零凭据读取路径的**默认态**：--render / --selftest 全程零网络，结构上不存在
任何密钥动作。--post 的令牌只从环境量现取（GH_TOKEN / GITHUB_TOKEN，禁 argv 直
传、禁落盘、禁回显），本件不写任何凭据文件。贴板前 scrub 预检见 scrub_precheck()。

同族参考件（只读，禁改）：tools/cnb-card-dispatch.py:99-114（labels 读板形制）、
tools/planner-quality-score.py:793-794（quality:* 归回评器，本件禁混刷）、
tools/cb-bench-dispatch.py（--execute 恒拒 fail-closed 形制同款）。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
GH_API = "https://api.github.com"
DEFAULT_REPO = "CloudCrane-Software/factory-os"
STATE_PREFIX = "state:"
STATE_MERGED = "state:merged"
STATE_REJECTED = "state:rejected"
# 非 resolved 一律翻 rejected（P5 禁假绿）；评论里 verdict 给原值，不美化。
STATE_BY_VERDICT = {"resolved": STATE_MERGED}
FIXTURE_DIR = os.path.join("tools", "fixtures", "cnb-verdict-reply")

# ─────────────────────────────────────────────────────────────────────────── #
# 公开面纪律：禁入公开面的形态（卡面 P2）                                        #
#   逐字用例 ID 禁入公开面；测试清单只给计数。渲染路径只读 judge.json 的**计数**   #
#   字段（结构保证），此处再对渲染产物做一次负例断言（双保险）。                  #
# ─────────────────────────────────────────────────────────────────────────── #
FORBIDDEN_IN_COMMENT = [
    (r"\[unit0\]", "pytest 空串参数化自动索引名（D-117 实证形态）"),
    (r"test_x\[", "逐字参数化用例 ID 方括号形态"),
    (r"FAIL_TO_PASS\s*[:=]\s*\[", "F2P 清单字面展开"),
    (r"PASS_TO_PASS\s*[:=]\s*\[", "P2P 清单字面展开"),
    (r"PASS_TO_PASS.{0,24}清单", "P2P 清单形态表述"),
    (r"FAIL_TO_PASS.{0,24}清单", "F2P 清单形态表述"),
    (r"::", "逐字测试节点 ID（模块::用例）"),
    (r"\bunit\d+\b", "镜像内自动索引名"),
]

# ─────────────────────────────────────────────────────────────────────────── #
# scrub 预检形态子集（贴板前 clean 形制照 D-118 结果评论五条先例）               #
#   本件内置的是**凭据形态子集**（K 族 + 通用赋值对），全量 18 模式树扫由 gates   #
#   剖面② bot-scrub 承担（tools/mirror-disclose.sh 内嵌 scan_text）。             #
#   纪律同 publish-scrub-gate.py：fail-closed，命中输出只给 形态名+行号，         #
#   **匹配原文永不进输出**。探测串一律运行时拼装（件内禁落字面量，防树扫自命中）。 #
# ─────────────────────────────────────────────────────────────────────────── #
SCRUB_PATTERNS = [
    ("SCRUB-JWT", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}")),
    ("SCRUB-SK", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")),
    ("SCRUB-GHPAT", re.compile(r"\b(?:ghp|gho|ghu|github_pat_)[A-Za-z0-9_]{20,}")),
    ("SCRUB-AWS", re.compile(r"\bAKIA[0-9A-Z]{14,22}\b")),
    ("SCRUB-PEM", re.compile(
        r"-----BEGIN [A-Za-z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Za-z ]*PRIVATE KEY-----"
        r"|-----BEGIN [A-Za-z ]*PRIVATE KEY-----")),
    ("SCRUB-BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}")),
    ("SCRUB-URLUSERINFO", re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://[^\s/:@]+:[^\s/@]{4,}@")),
    ("SCRUB-ASSIGN", re.compile(
        r"(?i)['\"]?[A-Za-z0-9_-]{0,64}?(?:password|passwd|pwd|secret|token|api_key|apikey"
        r"|access_key|auth_key|auth_token|credential|cred)s?['\"]?\s{0,16}[:=]\s{0,16}['\"]?"
        r"(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,4096}")),
]

# 零板写计数器：gh_api() 每次真网络调用追加一行。--render / --selftest 断言其为
# 空（结构上证明干跑路径零板写——不是靠"我以为没调"）。
_NET_CALLS = []


def scrub_precheck(text):
    """贴板前 scrub 预检。返回 [(形态名, 行号)]；空表 = clean。fail-closed：
    命中即拒贴（禁放宽度），且匹配原文永不进返回结构/输出。"""
    hits = []
    nl = [m.start() for m in re.finditer("\n", text)]

    def ln_of(pos):
        lo, hi = 0, len(nl)
        while lo < hi:
            mid = (lo + hi) // 2
            if nl[mid] < pos:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    for pid, rx in SCRUB_PATTERNS:
        for m in rx.finditer(text):
            hits.append((pid, ln_of(m.start())))
    return hits


def check_public_surface(text):
    """公开面负例断言：禁逐字用例 ID / 测试清单形态。返回 [(形态描述, 命中串)]。"""
    bad = []
    for rx, desc in FORBIDDEN_IN_COMMENT:
        m = re.search(rx, text)
        if m:
            bad.append((desc, m.group(0)[:40]))
    return bad


# ─────────────────────────────────────────────────────────────────────────── #
# judge.json 读数（只读计数字段——结构性不碰用例 ID 列）                          #
# ─────────────────────────────────────────────────────────────────────────── #
def _norm_count(value):
    """计数字段归一化：judge.json 真件的 p2p_id_normalized 是 ID 对数组（本件只取
    长度，禁读 ID 列）；脱敏夹具件给的是整数计数。两态都如实归一，缺席 None。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def read_judge(path):
    """读 judge.json 并归一化为回卡记录。零猜：缺字段如实 None，禁编造计数。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("judge.json 顶层非对象：%s" % type(raw).__name__)
    verdict = raw.get("verdict")
    if not isinstance(verdict, str) or not verdict:
        raise ValueError("judge.json 缺 verdict 字段——无从回卡（fail-closed 不猜绿）")
    resolved = raw.get("resolved")
    rec = {
        "judge": raw.get("judge"),
        "verdict": verdict,
        "resolved": bool(resolved) if resolved is not None else None,
        "diff_valid": raw.get("diff_valid"),
        "log_state": raw.get("log_state"),
        "f2p_success": raw.get("f2p_success"),
        "f2p_failure": raw.get("f2p_failure"),
        "p2p_success": raw.get("p2p_success"),
        "p2p_failure": raw.get("p2p_failure"),
        "tests_collected": raw.get("tests_collected"),
        "p2p_id_normalized": _norm_count(raw.get("p2p_id_normalized")),
        "diff_sha256": raw.get("diff_sha256"),
        "source": path,
    }
    rec["state_label"] = STATE_BY_VERDICT.get(verdict, STATE_REJECTED)
    return rec


def patch_sha12(rec, override=None):
    """patch 指纹 sha256[:12]。override 优先；缺省取 judge.json 的 diff_sha256。
    全值不入公开面——只给前 12 位（P2 指纹形态）。"""
    sha = override or rec.get("diff_sha256") or ""
    sha = str(sha).strip()
    if not sha:
        return None
    return sha[:12]


def count_pair(ok, fail):
    """渲染「成功/应过」计数对。缺侧如实 na（禁把缺席当 0 冒充全过）。"""
    if ok is None and fail is None:
        return "na（judge.json 未给该侧计数）"
    o = "na" if ok is None else str(ok)
    f = "na" if fail is None else str(fail)
    if ok is None or fail is None:
        return "%s/%s（一侧计数缺席，禁推应过总数）" % (o, f)
    return "%s/%s" % (o, str(int(ok) + int(fail)))


def derive_attribution(rec):
    """失配归因**结构级**摘要（judge.json 可缺省时按计数结构推导）。

    纪律：只给结构级分类，不指定未经 judge.json 支撑的根因；逐字用例 ID 禁入。
    调用方可用 --attribution 覆盖为人工判读后的结构级摘要（D-117 实证口径）。"""
    v = rec["verdict"]
    if v == "resolved":
        return "零失配项（F2P/P2P 全过）"
    parts = []
    if rec.get("f2p_failure"):
        parts.append("F2P 失配 %d 项（题目本体未过）" % int(rec["f2p_failure"]))
    if rec.get("p2p_failure"):
        parts.append("P2P 失配 %d 项（结构级：判分对账基准与镜像内 pytest 日志的 ID "
                     "形态差，或真实回归——二属一须人工判读 judge.json 与 judged_log；"
                     "本件只给结构级分类，不指定根因）" % int(rec["p2p_failure"]))
    if not parts:
        parts.append("verdict=%s 非 resolved，零可导失配计数（log_state=%s）"
                     % (v, rec.get("log_state") if rec.get("log_state") is not None else "na"))
    if rec.get("p2p_id_normalized"):
        parts.append("P2P ID 归一化 %d 对（判官件 A6 留痕字段）" % int(rec["p2p_id_normalized"]))
    return "；".join(parts)


# ─────────────────────────────────────────────────────────────────────────── #
# 输出①：回卡评论渲染（六要素形制）                                             #
# ─────────────────────────────────────────────────────────────────────────── #
COMMENT_TMPL = """## 判分回卡 · {debt}（{task} ｜ tools/cnb-verdict-reply.py 渲染）

- **verdict**：`{verdict}`（judge.json `verdict` 字段原值。跑得通≠做对题——D-107/D-117 同口径： verdict=not_resolved 也如实回卡，禁把失败卷渲染成成功）
- **judge.json 关键字段**：`diff_valid={diff_valid}` ｜ `log_state={log_state}` ｜ `tests_collected={collected}`
- **patch 指纹**：`sha256[:12]={sha12}`（全值不入公开面，只给前 12 位）
- **F2P 计数**：**{f2p}**（只给计数）
- **P2P 计数**：**{p2p}**（只给计数）
- **失配归因（结构级）**：{attribution}
- **测试清单**：只给计数（F2P {f2p}、P2P {p2p}）——零逐字用例 ID、零清单形态
- **凭据形态**：零（本评论经 scrub 预检 clean 后方可贴板；匹配原文永不进输出）

**板面翻格**：`{state_label}`（卡面 P4：只翻 state:* 族；wave 等既有 label 原样保留，quality:* 归回评器 tools/planner-quality-score.py，本件不碰）
"""


def render_comment(rec, debt=None, task=None, attribution=None, sha12=None):
    """渲染回卡评论（六要素形制）。纯函数——零网络零板写。"""
    if sha12 is None:
        sha12 = patch_sha12(rec)
    body = COMMENT_TMPL.format(
        debt=debt or "〈债号缺场〉",
        task=task or "cnb-verdict-reply",
        verdict=rec["verdict"],
        diff_valid="na" if rec.get("diff_valid") is None else str(rec["diff_valid"]).lower(),
        log_state="na" if rec.get("log_state") is None else rec["log_state"],
        collected="na" if rec.get("tests_collected") is None else rec["tests_collected"],
        sha12=sha12 or "na（judge.json 与命令行均未给 diff_sha256）",
        f2p=count_pair(rec.get("f2p_success"), rec.get("f2p_failure")),
        p2p=count_pair(rec.get("p2p_success"), rec.get("p2p_failure")),
        attribution=attribution or derive_attribution(rec),
        state_label=rec["state_label"],
    )
    return body


# ─────────────────────────────────────────────────────────────────────────── #
# 输出②：标签翻转计划（只翻 state:*；PUT /issues/{n}/labels 全量替换形制）        #
# ─────────────────────────────────────────────────────────────────────────── #
def plan_labels(current, state_label):
    """既有 label 集 → 翻转后 label 集。

    只动 state:* 族：摘掉全部既有 state:*，挂上目标档；其余 label（wave 等）
    原样保序保留（卡面 P4）。返回 (新 label 列表, 被摘掉的 state:* 列表)。"""
    cur = [str(x).strip() for x in (current or []) if str(x).strip()]
    kept = [l for l in cur if not l.startswith(STATE_PREFIX)]
    dropped = [l for l in cur if l.startswith(STATE_PREFIX)]
    new = kept + [state_label]
    return new, dropped


# ─────────────────────────────────────────────────────────────────────────── #
# 输出③：台账行回填人读草案（P3：禁自动写账本）                                  #
# ─────────────────────────────────────────────────────────────────────────── #
LEDGER_TMPL = """## 台账行回填草案（**人读草案** · 禁自动写账本 · 卡面 P3）

> 本段只作人读草案文本：本件**零账本写入路径**（--render / --selftest 零板写零账本写）。
> 登记落账本走正路（PR 流 + owner 批；双正本格局 D-123 在册），禁本卡绕开。

| 字段 | 草案值 |
|---|---|
| 债号 | {debt} |
| 卡号 | factory-os#{issue} |
| verdict | `{verdict}` → 翻格 `{state_label}` |
| patch 指纹 | `sha256[:12]={sha12}` |
| 占用闸 | {occupancy} |
| 时间轴 | {timeline} |
| 人工现身计数 | {manual} |
| 依据句 | tools/cnb-verdict-reply.py --render --judge {judge} --issue {issue}（rc=0；本件只渲染草案，禁代登记） |

> 五段计时采集归 D-121 卡范围（bench-watch 已留 --dispatched-at 口）——本卡**不做计时采集**，
> 时间轴字段只承接调用方显式给值，缺省留待填占位（禁编造时刻）。
"""


def render_ledger_draft(rec, debt, issue, sha12=None, occupancy=None, timeline=None,
                        manual=None):
    if sha12 is None:
        sha12 = patch_sha12(rec)
    return LEDGER_TMPL.format(
        debt=debt or "〈债号缺场〉",
        issue=issue if issue is not None else "na",
        verdict=rec["verdict"],
        state_label=rec["state_label"],
        sha12=sha12 or "na",
        occupancy=occupancy or "〈待填：tools/dispatch-occupancy-check.py rc〉",
        timeline=timeline or "〈待填：五段计时归 D-121，本卡不采集〉",
        manual=manual or "〈待填：本环人工输入/确认/救场次数（运营者声明值，非机器度量）〉",
        judge=rec.get("source") or "na",
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 板面 IO（仅 --post 走；--render / --selftest 结构上零调用）                    #
# ─────────────────────────────────────────────────────────────────────────── #
def gh_api(path, bearer, method="GET", payload=None):
    """GitHub API 调用。每次调用登记到 _NET_CALLS（零板写断言用）。"""
    import urllib.request
    _NET_CALLS.append({"path": path, "method": method})
    data = None
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if bearer:
        headers["Authorization"] = "Bearer %s" % bearer
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(GH_API + path, headers=headers, data=data, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def board_labels(repo, issue, bearer):
    """读板面既有 label（读板形制参考 tools/cnb-card-dispatch.py:99-114）。只读。"""
    _, obj = gh_api("/repos/%s/issues/%d" % (repo, issue), bearer)
    return [l["name"] for l in (obj.get("labels") or [])]


# ─────────────────────────────────────────────────────────────────────────── #
# 模式实现                                                                     #
# ─────────────────────────────────────────────────────────────────────────── #
def _emit(text, out_path, as_json=False):
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        print("rendered -> %s（%d 字节）" % (out_path, len(text.encode("utf-8"))))
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _guard_public_surface(comment):
    """贴板前双闸：scrub 预检 + 公开面负例断言。任一命中即拒（fail-closed）。"""
    hits = scrub_precheck(comment)
    if hits:
        for pid, ln in hits:
            print("SCRUB-HIT %s at line %d（匹配原文不进输出）" % (pid, ln), file=sys.stderr)
        print("拒贴：回卡评论 scrub 预检命中 %d 处——零凭据形态纪律 fail-closed" % len(hits),
              file=sys.stderr)
        return False
    bad = check_public_surface(comment)
    if bad:
        for desc, frag in bad:
            print("PUBLIC-SURFACE-HIT %s（片段 %r）" % (desc, frag), file=sys.stderr)
        print("拒贴：回卡评论含禁入公开面形态 %d 处——P2 纪律 fail-closed" % len(bad),
              file=sys.stderr)
        return False
    return True


def cmd_render(args):
    if not args.judge:
        print("--render 需 --judge <judge.json 路径>（缺省不读板、不猜 verdict）",
              file=sys.stderr)
        return 2
    try:
        rec = read_judge(args.judge)
    except Exception as exc:
        print("judge.json 读数失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    sha12 = patch_sha12(rec, args.patch_sha)
    comment = render_comment(rec, debt=args.debt, task=args.task,
                             attribution=args.attribution, sha12=sha12)
    if not _guard_public_surface(comment):
        return 2
    if args.labels:
        current = [x.strip() for x in args.labels.split(",") if x.strip()]
    else:
        current = None
    if current is None:
        new_labels, dropped = plan_labels([], rec["state_label"])
        kept_note = ("（--render 不读板：既有 label 保留面以 --post 时 GET /issues/{n} "
                     "实读为准；此处只标目标 state:* 档）")
    else:
        new_labels, dropped = plan_labels(current, rec["state_label"])
        kept_note = ""
    ledger = render_ledger_draft(rec, args.debt, args.issue, sha12=sha12,
                                 occupancy=args.occupancy, timeline=args.timeline,
                                 manual=args.manual)
    lines = []
    lines.append("=== 回卡评论（--render 干跑渲染，零板写零网络）===")
    lines.append(comment.rstrip())
    lines.append("")
    lines.append("=== 标签翻转计划（--render 干跑，零板写；真写形态 PUT /issues/{n}/labels）===")
    lines.append("目标 state:* 档：%s" % rec["state_label"])
    lines.append("摘除既有 state:*：%s" % (", ".join(dropped) if dropped else "（干跑未读板，无实读值）"))
    lines.append("PUT /repos/%s/issues/%s/labels → %s%s"
                 % (args.repo, args.issue if args.issue is not None else "<卡号>",
                    json.dumps(new_labels, ensure_ascii=False), kept_note))
    lines.append("")
    lines.append(ledger.rstrip())
    lines.append("")
    lines.append("=== 干跑读数 ===")
    lines.append("verdict=%s → state:*=%s；patch sha256[:12]=%s；F2P=%s；P2P=%s；"
                 "网络调用=%d（零板写断言：--render 路径不得发起任何 API 调用）"
                 % (rec["verdict"], rec["state_label"], sha12 or "na",
                    count_pair(rec.get("f2p_success"), rec.get("f2p_failure")),
                    count_pair(rec.get("p2p_success"), rec.get("p2p_failure")),
                    len(_NET_CALLS)))
    return _emit("\n".join(lines), args.out)


def cmd_post(args):
    if not args.judge:
        print("--post 需 --judge <judge.json 路径>", file=sys.stderr)
        return 2
    if not args.issue or args.issue <= 0:
        print("拒写板：--post 需 --issue <正整数卡号>（卡号 0/缺席禁写板）", file=sys.stderr)
        return 2
    bearer = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not bearer:
        print("拒写板：环境量 GH_TOKEN / GITHUB_TOKEN 缺席——禁无令牌写板（fail-closed）",
              file=sys.stderr)
        return 2
    try:
        rec = read_judge(args.judge)
    except Exception as exc:
        print("judge.json 读数失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    sha12 = patch_sha12(rec, args.patch_sha)
    comment = render_comment(rec, debt=args.debt, task=args.task,
                             attribution=args.attribution, sha12=sha12)
    if not _guard_public_surface(comment):
        return 2
    ledger = render_ledger_draft(rec, args.debt, args.issue, sha12=sha12,
                                 occupancy=args.occupancy, timeline=args.timeline,
                                 manual=args.manual)
    # ① 读板面既有 label（只读；禁猜——保留面以实读为准）
    try:
        current = board_labels(args.repo, args.issue, bearer)
    except Exception as exc:
        print("读板面 labels 失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    new_labels, dropped = plan_labels(current, rec["state_label"])
    lines = []
    lines.append("=== 回卡评论（--post 真写板）===")
    lines.append(comment.rstrip())
    lines.append("")
    lines.append("=== 标签翻转（真写板）===")
    lines.append("读板既有 label：%s" % json.dumps(current, ensure_ascii=False))
    lines.append("摘除 state:*：%s" % (", ".join(dropped) if dropped else "（无）"))
    lines.append("PUT /repos/%s/issues/%d/labels → %s"
                 % (args.repo, args.issue, json.dumps(new_labels, ensure_ascii=False)))
    lines.append("")
    lines.append(ledger.rstrip())
    # ② POST 评论
    try:
        st_c, obj_c = gh_api("/repos/%s/issues/%d/comments" % (args.repo, args.issue),
                             bearer, method="POST", payload={"body": comment})
    except Exception as exc:
        print("POST 评论失败：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    lines.append("")
    lines.append("=== 真写读数 ===")
    lines.append("POST /issues/%d/comments → http=%s comment id=%s"
                 % (args.issue, st_c, obj_c.get("id")))
    # ③ PUT labels
    try:
        st_l, obj_l = gh_api("/repos/%s/issues/%d/labels" % (args.repo, args.issue),
                             bearer, method="PUT", payload={"labels": new_labels})
    except Exception as exc:
        print("PUT labels 失败：%s: %s（评论已发，标签未翻——人工补翻）"
              % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    lines.append("PUT /issues/%d/labels → http=%s labels now=%s"
                 % (args.issue, st_l,
                    json.dumps([l["name"] for l in (obj_l if isinstance(obj_l, list) else [])],
                               ensure_ascii=False)))
    lines.append("verdict=%s → state:*=%s（P4：只翻 state:* 族；quality:* 未碰）"
                 % (rec["verdict"], rec["state_label"]))
    lines.append("台账草案：人读文本已随本输出给出，**未写账本**（P3）")
    return _emit("\n".join(lines), args.out)


# ─────────────────────────────────────────────────────────────────────────── #
# selftest（夹具驱动，零网络零板写）                                             #
# ─────────────────────────────────────────────────────────────────────────── #
def selftest():
    """夹具断言：两态翻转 + 六要素在场 + scrub 预检 + 零板写。零网络零凭据。"""
    n = 0
    base = os.path.dirname(os.path.abspath(__file__))
    fx = os.path.join(base, "fixtures", "cnb-verdict-reply")

    def fxpath(name):
        return os.path.join(fx, name)

    # ── 夹具两态读数 ──
    rec_res = read_judge(fxpath("judge-resolved.json"))
    rec_not = read_judge(fxpath("judge-not-resolved.json"))
    n += 1
    assert rec_res["verdict"] == "resolved", rec_res["verdict"]
    assert rec_not["verdict"] == "not_resolved", rec_not["verdict"]
    # 翻转映射两态断言（卡面：resolved⇒state:merged、not_resolved⇒state:rejected）
    n += 1
    assert rec_res["state_label"] == STATE_MERGED, rec_res["state_label"]
    assert rec_not["state_label"] == STATE_REJECTED, rec_not["state_label"]
    # 非 resolved 的其它 verdict 态也翻 rejected，且评论给 verdict 原值（P5 禁假绿）
    n += 1
    rec_err = dict(rec_not, verdict="judge_error")
    rec_err["state_label"] = STATE_BY_VERDICT.get(rec_err["verdict"], STATE_REJECTED)
    assert rec_err["state_label"] == STATE_REJECTED
    c_err = render_comment(rec_err)
    assert "judge_error" in c_err, "verdict 原值必须如实进评论（禁美化）"

    # ── 六要素在场断言（D-117 回卡实证六要素形制）──
    c_not = render_comment(rec_not, debt="D-133", task="cnb-verdict-reply")
    # resolved 态按夹具件记录的渲染命令取债号 D-117（A6 翻正态对拍 factory-os#90）
    c_res = render_comment(rec_res, debt="D-117", task="cnb-verdict-reply")
    n += 1
    six_not = ["verdict", "patch 指纹", "F2P 计数", "P2P 计数", "失配归因（结构级）", "凭据形态"]
    for el in six_not:
        assert el in c_not, "not_resolved 评论缺六要素：%s" % el
    six_res = ["verdict", "patch 指纹", "F2P 计数", "P2P 计数", "失配归因（结构级）", "凭据形态"]
    for el in six_res:
        assert el in c_res, "resolved 评论缺六要素：%s" % el
    # judge.json 关键字段 diff_valid / log_state 在场
    n += 1
    assert "diff_valid=" in c_not and "log_state=" in c_not
    # patch 指纹形态：sha256[:12]，且全值（64 位）不得进评论
    n += 1
    assert "sha256[:12]=5c040ce9bffd" in c_not, c_not
    assert rec_not["diff_sha256"] not in c_not, "patch 全值禁入公开面"
    assert "5c040ce9bffd" in c_res, c_res
    # 只给计数：计数对在场，且零逐字用例 ID / 零清单形态
    n += 1
    assert "**1/1**" in c_not and "**240/241**" in c_not, c_not
    assert not check_public_surface(c_not), check_public_surface(c_not)
    assert not check_public_surface(c_res), check_public_surface(c_res)

    # ── scrub 预检断言：正例 clean / 反例必红 ──
    n += 1
    assert scrub_precheck(c_not) == [], scrub_precheck(c_not)
    assert scrub_precheck(c_res) == []
    probes = {
        "SCRUB-JWT": "eyJ" + "A" * 24 + "." + "B" * 12 + "." + "C" * 24,
        "SCRUB-SK": "sk-" + "A" * 30,
        "SCRUB-GHPAT": "gh" + "p_" + "A" * 30,
        "SCRUB-AWS": "AKIA" + "A" * 16,
        "SCRUB-PEM": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "SCRUB-BEARER": "Bearer " + "A" * 30,
        "SCRUB-URLUSERINFO": "http://" + "u" * 4 + ":" + "p" * 8 + "@h.example",
        "SCRUB-ASSIGN": "access_" + "token" + ": " + "A" * 30,
    }
    for pid, probe in probes.items():
        n += 1
        got = scrub_precheck("前缀行\n" + probe + "\n尾行")
        assert any(p == pid for p, _ in got), "scrub 探针 %s 未被检出：%s" % (pid, got)
    # 反例：探针串本身必须被拒贴（fail-closed，非恒绿）
    n += 1
    poisoned = c_not + "\n附注：" + probes["SCRUB-JWT"]
    import io as _io0
    import contextlib as _ctx0
    with _ctx0.redirect_stderr(_io0.StringIO()):
        refused = not _guard_public_surface(poisoned)
    assert refused, "投毒评论必须被 scrub 预检拒贴（fail-closed 非恒绿）"

    # ── 标签翻转断言：只翻 state:*，其余原样保序保留 ──
    n += 1
    new, dropped = plan_labels(["wave", "state:queued", "quality:B"], STATE_MERGED)
    assert new == ["wave", "quality:B", "state:merged"], new
    assert dropped == ["state:queued"], dropped
    n += 1
    new2, dropped2 = plan_labels(["wave", "state:running"], STATE_REJECTED)
    assert new2 == ["wave", "state:rejected"] and dropped2 == ["state:running"], (new2, dropped2)
    # 无 state:* 在场也照翻（不因缺席而跳过）
    n += 1
    new3, dropped3 = plan_labels(["wave"], STATE_REJECTED)
    assert new3 == ["wave", "state:rejected"] and dropped3 == [], (new3, dropped3)
    # 多 state:* 同场只留一档（禁双档并存）
    n += 1
    new4, dropped4 = plan_labels(["wave", "state:queued", "state:running"], STATE_MERGED)
    assert new4 == ["wave", "state:merged"] and len(dropped4) == 2, (new4, dropped4)

    # ── 期望评论夹具逐项对拍 ──
    n += 1
    with open(fxpath("expected-comment.md"), encoding="utf-8") as f:
        exp_md = f.read()
    for el in parse_expected_elements(exp_md):
        n += 1
        assert el in c_not, "期望评论件断言缺场：%r" % el
    n += 1
    with open(fxpath("expected-comment-resolved.md"), encoding="utf-8") as f:
        exp_res = f.read()
    for el in parse_expected_elements(exp_res):
        n += 1
        assert el in c_res, "期望评论件（resolved）断言缺场：%r" % el

    # ── 夹具件自身公开面干净（与验收命令 3 负例断言同口径）──
    n += 1
    for name in ("expected-comment.md", "expected-comment-resolved.md",
                 "judge-resolved.json", "judge-not-resolved.json"):
        n += 1
        with open(fxpath(name), encoding="utf-8") as f:
            txt = f.read()
        bad = check_public_surface(txt)
        assert not bad, "夹具 %s 含禁入公开面形态：%s" % (name, bad)

    # ── 零板写断言：--render 路径零网络调用 ──
    n += 1
    before = len(_NET_CALLS)
    assert before == 0, "selftest 起点即有网络调用登记：%s" % _NET_CALLS
    argv = ["--render", "--judge", fxpath("judge-not-resolved.json"),
            "--issue", "0", "--debt", "D-133", "--repo", DEFAULT_REPO]
    import io as _io
    import contextlib as _ctx
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = main_argv(argv)
    render_out = buf.getvalue()
    n += 1
    assert rc == 0, "--render rc=%d" % rc
    assert len(_NET_CALLS) == 0, "--render 路径发起了网络调用：%s" % _NET_CALLS
    # 干跑产物三输出在场 + PUT /issues/{n}/labels 形制点名 + verdict/计数/指纹/归因四必含
    n += 1
    for seg in ("=== 回卡评论", "=== 标签翻转计划", "台账行回填草案", "=== 干跑读数 ==="):
        assert seg in render_out, "干跑产物缺段：%s" % seg
    n += 1
    assert "PUT /repos/%s/issues/0/labels" % DEFAULT_REPO in render_out, render_out
    n += 1
    for must in ("verdict=not_resolved", "F2P", "P2P", "sha256[:12]=5c040ce9bffd",
                 "失配归因（结构级）"):
        assert must in render_out, "干跑评论缺必含要素：%s" % must
    # 干跑禁出现逐字用例 ID / 测试清单形态（验收命令 2 同口径）
    n += 1
    assert not check_public_surface(render_out), check_public_surface(render_out)
    # 干跑产物明示零板写
    n += 1
    assert "零板写" in render_out and "网络调用=0" in render_out, render_out

    # ── --render --issue 0 负例：缺 --judge 即拒（fail-closed 不猜 verdict）──
    n += 1
    with _ctx.redirect_stdout(_io.StringIO()):
        rc2 = main_argv(["--render", "--issue", "0"])
    assert rc2 == 2, "缺 --judge 应 rc=2，实得 %d" % rc2
    assert len(_NET_CALLS) == 0

    print("selftest: %d/%d 断言全过（两态翻转/六要素在场/scrub 预检正反例/标签只翻 "
          "state:*/期望评论夹具对拍/夹具公开面干净/零板写）" % (n, n))
    return 0


def parse_expected_elements(md_text):
    """从期望评论件抽「期望要素断言清单」小节下的逐行断言子串。

    约定：`## 期望要素断言清单` 小节内，以 `- ` 开头的行即一条必须出现在渲染
    评论里的子串（到下一个 `##` 标题或文末为止）。空行/非 `- ` 行忽略。"""
    out = []
    in_sec = False
    for ln in md_text.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            in_sec = (s == "## 期望要素断言清单")
            continue
        if in_sec and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def main_argv(argv):
    """供 selftest 复用的入口（不读 sys.argv）。"""
    old = sys.argv[:]
    try:
        sys.argv = ["cnb-verdict-reply.py"] + list(argv)
        return main()
    finally:
        sys.argv = old


def main():
    ap = argparse.ArgumentParser(
        description="verdict 落定后的回卡评论渲染 + state:* 标签翻转 + 台账人读草案（D-133）")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="目标板 owner/name")
    ap.add_argument("--issue", type=int, default=None, help="卡号（GitHub issue 号）")
    ap.add_argument("--judge", default=None, help="judge.json 路径（--render/--post 必填）")
    ap.add_argument("--debt", default=None, help="债号（如 D-133；仅渲染用）")
    ap.add_argument("--task", default=None, help="task_id（仅渲染用，缺省 cnb-verdict-reply）")
    ap.add_argument("--patch-sha", dest="patch_sha", default=None,
                    help="patch sha256（缺省取 judge.json 的 diff_sha256；公开面只给前 12 位）")
    ap.add_argument("--attribution", default=None,
                    help="失配归因结构级摘要（缺省按 judge.json 计数结构推导）")
    ap.add_argument("--labels", default=None,
                    help="既有 label（逗号分隔；--render 干跑只读输入，缺省不猜保留面）")
    ap.add_argument("--occupancy", default=None, help="占用闸读数（台账草案用，缺省留待填）")
    ap.add_argument("--timeline", default=None, help="时间轴读数（台账草案用，缺省留待填）")
    ap.add_argument("--manual", default=None,
                    help="人工现身计数（运营者声明值；缺省留待填，非机器度量）")
    ap.add_argument("--out", default=None, help="渲染产物落盘路径（缺省 stdout）")
    sub = ap.add_mutually_exclusive_group()
    sub.add_argument("--render", action="store_true",
                     help="干跑：渲染三输出，零板写零网络（缺省模式）")
    sub.add_argument("--post", action="store_true",
                     help="真写板：POST 评论 + PUT state:* 标签（硬闸见 docstring）")
    sub.add_argument("--selftest", action="store_true",
                     help="夹具自测（零网络零板写零凭据）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.post:
        return cmd_post(args)
    return cmd_render(args)


if __name__ == "__main__":
    sys.exit(main())
