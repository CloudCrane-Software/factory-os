#!/usr/bin/env python3
"""publish-scrub-gate.py — 公网 v2 流式视图发布前脱敏闸（阶段三 V 线收尾件）

对"待发布树"（v2 流文件：orders.json / data.json / quota.json / index.html /
stream/*.json、stream-demo/*.json、normal.jsonl 导出）做密钥形态与观测面内部
拓扑扫描：命中即阻断（exit 1 列文件与形态，不发布），人工处置后重跑；
--redact 模式就地保守打码（命中段替换 ▉▉▉，保留键名与可读性）。

用法:
  publish-scrub-gate.py <tree>                 # 扫描；0=全绿可发, 1=命中拒发, 2=结构失败(同拦)
  publish-scrub-gate.py <tree> --json          # 机器可读裁决
  publish-scrub-gate.py <tree> --redact        # 就地打码后自动复扫（仅过了复扫才 exit 0）
  publish-scrub-gate.py --selftest             # 内置正/反例夹具自检（tamper 探针必须红）
  publish-scrub-gate.py <tree> --freeze-keys   # 追加 quota/data 键集冻结检查（超集即拦）
                                                # （发布路径 tools/factory-status-push.py:_gate_ok
                                                #  自 2026-11-03 起在役挂此旗标——此前旗标只存在于
                                                #  本闸自身、发布路径不带 ⇒ 键集冻结=死开关）

纪律（照抄 计划/研究组/密钥终扫-20261024.md:4 与 publish-gate.md §1.5）:
  * fail-closed：宁可误红不可漏报；解析失败/白名单外文件一律视为红（exit 2）。
  * 命中输出只给 文件:行 + 模式名 + 值前 4 字符 + 长度 —— 匹配原文永不进输出。
  * 误报走 tools/publish-allowlist.json 单点豁免（人工理由+批准人+到期日，过期自动失效）。

正则族真源声明（audit-S4-publish-gate-20261028.md §四-5/P1-5：双真源必分叉，须声明基准）:
  * K/O 族基准 = tools/stream-tailer.py:75-110 SCRUB_RULES（2026-10-28 主代理补齐的实装版）。
  * 本闸相对该实装版的差异（逐条有出处）:
    + O-04 内网主机别名族（publish-gate.md §1.2；tailer 版无对应——audit §四-5 点名）
    + O-08 数据库连接串（publish-gate.md §1.2；tailer 版无对应；设计原文的 ".pem 引用"
      从句含义含糊，未实现，差异登记在报告）
    - O-02 去掉 159.75.21.149（publish-gate.md §1.2 裁决：factory. 自身解析地址不算泄露；
      tailer 版含它属过宽，板面合法引用会被误红）
    + O-02 补 36.139.118.235 / 223.198.167.65（publish-gate.md §1.2；audit §四-5 点名
      tailer 版缺失）
    + K-06/07/08/11 赋值对的值侧命名分组 (?P<v>)：--redact 只打码值、保留键名（可读性）。
  * X 族 = 本工单新增（任务书"长 hex/base64 陪上下文关键词"；stream-tailer 实装版与
    publish-gate.md 草案均无此族）。上下文关键词刻意不含 digest/hash/fingerprint——
    计划 §4 V1 指纹卡字段（如 dsl_digest 64-hex）是允许发布的，不拦。

--redact 安全警告：就地改写 대상树。只许对副本/暂存树运行，严禁对
状态观测/quota.json、状态/看板/data.json 等在线源文件直接 --redact。
"""
import argparse
import json
import os
import re
import sys
import time

VERSION = "vgate-1.0 (2026-10-28)"

# --------------------------------------------------------------------------- #
# 模式族：(ID 描述, 正则, 是否只打码值侧)
#   value=True 时正则须含命名组 (?P<v>...) —— redact 只替换值段，保留键名。
# --------------------------------------------------------------------------- #
PATTERNS = [
    # —— K 族：密钥形状（stream-tailer.py:75-99 实装版照抄，值侧加命名分组）——
    ("K-01 JWT 三段式", re.compile(
        r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}"), False),
    ("K-02 sk- 前缀", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), False),
    ("K-03 GitHub PAT", re.compile(
        r"\b(ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), False),
    ("K-04 AWS AK", re.compile(r"\bAKIA[0-9A-Z]{14,22}\b"), False),
    # K-05：整段 PEM（头到 END）；无 END（截断件）时至少遮头行（红队R4-P1-5 同款）
    ("K-05 PEM 私钥块", re.compile(
        r"-----BEGIN [A-Za-z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Za-z ]*PRIVATE KEY-----"
        r"|-----BEGIN [A-Za-z ]*PRIVATE KEY-----", re.IGNORECASE), False),
    # K-06/07/08/11 赋值对（红队R4-P1-1/3/4 定版）：键两侧容忍引号、键前容忍前缀族；
    # 值侧负向排除 null/<none>/纯数字（防观测计数误报）
    ("K-06/07/08/11 赋值对", re.compile(
        r"['\"]?[A-Za-z0-9_-]*(?:api[-_]?key|access[-_]?token|token|password|passwd|secret|credential)s?['\"]?\s*[:=]\s*['\"]?"
        r"(?P<v>(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,})",
        re.IGNORECASE), True),
    ("K-09 Bearer 头", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/-]{8,}"), False),
    ("K-10 SSH 公钥", re.compile(
        r"\b(?:ssh-(?:rsa|ed25519)|ecdsa-sha2-[a-z0-9-]+)\s+AAAA[A-Za-z0-9+/]{20,}"), False),
    ("K-12 openBao hvs.", re.compile(r"\bhvs\.[A-Za-z0-9_-]{10,}"), False),
    ("K-13 其余厂商前缀", re.compile(
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bglpat-[A-Za-z0-9_-]{15,}|\bhf_[A-Za-z0-9]{20,}"
        r"|\bAIza[0-9A-Za-z_-]{30,}|\bxai-[A-Za-z0-9]{20,}"), False),
    # —— O 族：观测面内部拓扑（stream-tailer.py:100-109 + gate 侧补强）——
    # O-01：CGNAT 100.64-100.127，八位组容忍前导零（红队R4：100.064 形态）
    ("O-01 tailnet CGNAT", re.compile(
        r"\b100\.0*(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.(\d{1,3})\.(\d{1,3})\b"), False),
    # O-02：publish-gate.md §1.2 版（gov 自身 159.75.21.149 不算泄露，有意不含）
    ("O-02 本厂公网 IP", re.compile(
        r"\b(?:42\.194\.143\.17|36\.139\.118\.235|223\.198\.167\.65)\b"), False),
    # O-03：容忍双斜杠与非 ASCII 用户名（红队R4-P2）
    ("O-03 home 路径", re.compile(r"/home/+[^\s\"',;}/]{1,40}"), False),
    # O-04：内网主机别名（publish-gate.md §1.2；tailer 实装版无——gate 侧补强）
    ("O-04 内网主机别名", re.compile(
        r"\b(?:mingda-bench|anolis-gpu-01|pandev-comp|governance-machine|VM-0-6-[a-z]+)\b"), False),
    # O-05：回环服务端口（补 localhost:port 形态，红队R4-P2）
    ("O-05 回环端口", re.compile(r"\b(?:127\.0\.0\.1|localhost):(\d{2,5})\b"), False),
    # O-06：内网用户@主机
    ("O-06 内网用户@主机", re.compile(
        r"\b[A-Za-z0-9._-]+@(?:gov|pandev[0-9-]*|anolis|mingda[a-z-]*)(?:\.[a-z]+)?\b",
        re.IGNORECASE), False),
    # O-08：数据库连接串（publish-gate.md §1.2；设计原文 .pem 从句含义含糊未实现）
    ("O-08 数据库连接串", re.compile(
        r"(?i)\b(?:postgres|postgresql|mysql|redis|mongodb)://[^\s\"'<>]+"), False),
    # —— X 族：本工单新增（任务书"长 hex/base64 陪上下文关键词"）——
    ("X-01 长 base64 赋值", re.compile(
        r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token"
        r"|client[_-]?secret|secret[_-]?key|signing[_-]?key|private[_-]?key"
        r"|encryption[_-]?key)\b[\"']?\s*[:=]\s*[\"']?(?P<v>[A-Za-z0-9+/]{32,}={0,2})"), True),
    ("X-02 长 hex 赋值", re.compile(
        r"(?i)\b(?:key|token|secret|nonce|salt|signature)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?P<v>[0-9a-fA-F]{32,})"), True),
]

REDACT_MARK = "▉▉▉"

# --------------------------------------------------------------------------- #
# 路径白名单（按 gov 在役发布树实测形状 + push_board 暂存布局；多一类即拒发）
#   static/{index.html,quota.json,data.json}
#   static/v2/{index.html,orders.json,stages.json,otel-sidecar.json,stream/*.json,stream-demo/*.json}
#   *.jsonl = normal.jsonl 导出类（任务书点名；当前在役树无此类文件）
#   点开头组件（.tailer-state.json / *.tmp）= 显式黑名单双保险（G-5）
# otel-sidecar.json（DEB-2d 2026-10-29）：OTel 观测边车快照（emit-sidecar.py 每周期
# 原子落 状态观测/otel-sidecar.json），经 factory-status-push 入暂存树推 gov
# static/v2/otel-sidecar.json，供看板 v2 指标区拉取。
# 内容面实测口径（2026-10-29 义务收口批，**推翻** otlp-report.md §四"内容模式不会拦"
# 的预检结论）：原样快照入树跑真闸 → O-01 tailnet CGNAT 红（collector_endpoint=
# http://pandev-host.invalid:4318，100.64/24 段）→ verdict=block。故推送侧入树的是**删
# collector_endpoint 的发布面脱敏副本**（factory-status-push._stage_otel_sidecar；
# 本地全保真副本仍在 状态观测/otel-sidecar.json），删键后复跑 verdict=ok 0 命中。
# 本白名单只放行文件名；删键义务在推送侧，闸的内容模式保持原强度（不为放行数据
# 削弱安全控制）。
# --------------------------------------------------------------------------- #
PATH_OK = [
    re.compile(r"^(?:v2/)?(?:orders|data|quota|stages|otel-sidecar)\.json$"),
    re.compile(r"^(?:v2/)?index\.html$"),
    re.compile(r"^(?:v2/)?(?:stream|stream-demo)/[A-Za-z0-9_-][A-Za-z0-9._-]*\.json$"),
    re.compile(r"^(?:v2/)?(?:stream|stream-demo)/[A-Za-z0-9_-][A-Za-z0-9._-]*\.jsonl$"),
]

# --------------------------------------------------------------------------- #
# 键集冻结（publish-gate.md §1.3/§1.5，A-4 实测口径；--freeze-keys 时启用）
#
# 2026-11-03（RT 收尾批 publish-sc）修两处，根因=「死开关」：
#   事实：冻结检查此前只挂在 --freeze-keys 旗标上，而①发布路径
#   （tools/factory-status-push.py:_gate_ok 调闸）②all-gates 唯一门项
#   （publish-scrub-gate.py --selftest 夹具自测）**都不带该旗标** ⇒ 键集冻结在
#   在役发布链上结构性不可达：治理器（quota-governor）新加字段直接上公网，无人拦。
#   修①【冻结集对齐已审发布面形状】：step/minimax 死态键 "error" 纳入冻结集。
#     原 6/5 键集是 A-4 在**成功态** quota.json 上的实测（成功态 step 无 error 键），
#     死态从未被覆盖 ⇒ 冻结集与在役发布面实形长期不一致（治理器死态写
#     {"go": false, "error": "<一句>"}，见 tools/quota-governor.py:110-112/126；
#     "error" 键本身改动前既有——tools/quota-governor.py.20261031-pre-DEB57.bak:73/85
#     即 {"error": ...}）。纳入依据=设计正本 §1.3 的处置流程「拦下后人工审：确认新键
#     无敏感性→更新 gate 常量+变更日志，再放行」：error 值=一句截断的失败原因
#     （ERR_MAX=120 字符），无凭据面，且整文件文本仍逐模式过本闸 K/O/X 族内容扫描。
#   修②【发布路径挂上 --freeze-keys】：见 tools/factory-status-push.py:_gate_ok
#     （漂移即拒发整轮，fail-closed：停更不停线，gov 保留上一版）。
# --------------------------------------------------------------------------- #
QUOTA_TOP = {"ts", "step", "minimax"}
QUOTA_STEP = {"remaining", "total", "used_percent", "expires_at_ms",
              "seconds_to_expiry", "go", "error"}
QUOTA_MINI = {"window_end_ms", "seconds_to_window_end", "five_hour_remaining_pct",
              "weekly_remaining_pct", "go", "error"}
DATA_TOP = {"ts", "epoch", "generated_by", "mode", "interval_s", "plan", "scheduler",
            "extra_schedulers", "arms", "anolis", "relay", "totals", "cost",
            "archived_arms", "alarms",
            # "portal"（RT 收口批 2026-11-02）：watch 快照新增 gov 公网门户巡检面
            # （factory-watch.py scan_portal 三签名；值域=布尔/int/短状态串，无敏感面）
            "portal"}
KEYSPECS = {"quota.json": (QUOTA_TOP, {"step": QUOTA_STEP, "minimax": QUOTA_MINI}),
            "data.json": (DATA_TOP, {})}

MAX_HITS_DEFAULT = 500


def _pid(name):
    """模式 ID = 名称首个空白分隔 token（allowlist 按 ID 匹配）。"""
    return name.split(" ", 1)[0]


def load_allowlist(path):
    """误报白名单：默认拒绝。无文件=空白名单。过期条目自动失效（重新拦）。"""
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except OSError:
        return []
    except json.JSONDecodeError as e:
        print(f"ALLOWLIST PARSE FAIL: {path}: {e} —— 视为空白名单（fail-closed）",
              file=sys.stderr)
        return []
    out = []
    today = time.strftime("%Y-%m-%d")
    for e in entries if isinstance(entries, list) else []:
        try:
            if e["expires"] >= today and e["pattern"] and e.get("reason"):
                out.append(e)
        except (KeyError, TypeError):
            continue
    return out


def hit_allowed(al, pattern, relpath):
    for e in al:
        if _pid(pattern) != e["pattern"]:
            continue
        if e["file"] not in (relpath, "*", os.path.basename(relpath)):
            continue
        return True
    return False


def scan_text(rel, text):
    """对单文件文本跑全模式族。返回 (hits, errs)；hits 只带前4字符+长度。"""
    hits, errs = [], []
    if rel.endswith(".json"):
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            errs.append(f"{rel}: JSON 解析失败: {e}")
    for name, rx, _value_only in PATTERNS:
        for m in rx.finditer(text):
            v = m.group("v") if "v" in (m.groupdict() or {}) and m.group("v") else m.group(0)
            ln = text.count("\n", 0, m.start()) + 1
            hits.append({"file": rel, "line": ln, "pattern": name,
                         "preview": v[:4], "len": len(v)})
    return hits, errs


def check_keys(rel, obj, top, subs):
    errs = []
    extra = set(obj) - top
    if extra:
        errs.append(f"{rel}: 键集漂移(超集): {sorted(extra)} —— 人工审定后再冻结放行")
    for k, frozen in subs.items():
        v = obj.get(k)
        if isinstance(v, dict):
            extra = set(v) - frozen
            if extra:
                errs.append(f"{rel}:{k} 键集漂移(超集): {sorted(extra)}")
    return errs


def iter_tree(root):
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            yield os.path.relpath(os.path.join(dirpath, fn), root)


def scan_tree(root, al, freeze_keys=False):
    hits, errs, scanned, allowed_n = [], [], 0, 0
    for rel in iter_tree(root):
        if any(part.startswith(".") for part in rel.split(os.sep)):
            errs.append(f"黑名单文件(点开头): {rel} —— tailer 游标/临时件不得上公网")
            continue
        if not any(rx.match(rel) for rx in PATH_OK):
            errs.append(f"白名单外文件: {rel}")
            continue
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            errs.append(f"{rel}: 读取失败: {e}")
            continue
        scanned += 1
        if freeze_keys and os.path.basename(rel) in KEYSPECS and rel.count(os.sep) <= 1:
            try:
                obj = json.loads(text)
                top, subs = KEYSPECS[os.path.basename(rel)]
                errs += check_keys(rel, obj, top, subs)
            except json.JSONDecodeError:
                pass  # 解析失败已由 scan_text 记
        h, e = scan_text(rel, text)
        for hit in h:
            if hit_allowed(al, hit["pattern"], rel):
                allowed_n += 1
                continue
            hits.append(hit)
        errs += e
    return hits, errs, scanned, allowed_n


def redact_tree(root, al):
    """就地保守打码：命中段（或值段）替换 ▉▉▉，其余字节不动；原子写回。"""
    actions = []
    for rel in iter_tree(root):
        if any(part.startswith(".") for part in rel.split(os.sep)):
            continue
        if not any(rx.match(rel) for rx in PATH_OK):
            continue
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        orig, per_file = text, []
        for name, rx, _vo in PATTERNS:
            def _sub(m, _n=name):
                if hit_allowed(al, _n, rel):
                    return m.group(0)
                if "v" in (m.groupdict() or {}) and m.group("v"):
                    return m.group(0)[:m.start("v") - m.start()] + REDACT_MARK + \
                        m.group(0)[m.end("v") - m.start():]
                return REDACT_MARK
            new = rx.sub(_sub, text)
            if new != text:
                per_file.append(name)
                text = new
        if text != orig:
            tmp = path + ".vgate-tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            actions.append({"file": rel, "patterns": sorted(set(per_file))})
    return actions


def render_hits(hits, limit):
    out = []
    for h in hits[:limit]:
        out.append(f"HIT {h['file']}:{h['line']} {h['pattern']} "
                   f"值特征={h['preview']}***[len={h['len']}]")
    return out


def tally(hits):
    t = {}
    for h in hits:
        t[h["pattern"]] = t.get(h["pattern"], 0) + 1
    return dict(sorted(t.items()))


def selftest():
    """内置正/反例夹具：破坏输入必须让门变红（三道门 tamper 探针口径）。

    夹具全部使用显式占位符（PLACEHOLDER/TEST/EXAMPLE 字样），零真实凭据；
    落在 $HOME/vgate-work/selftest-<pid>/（/tmp 配额有限，硬纪律 5），跑完即清。
    """
    # 非密闭修复（2026-11-01 RT）：原为固定共享路径 selftest/，并发自检一方开跑的
    # rmtree(base) 会拆掉另一方在测的夹具（假红实证：2026-10-31 RT 轮 item-17
    # FileNotFoundError …/selftest/stream/.tailer-state.json，姊妹跑同位 SELFTEST PASS）。
    # 加 pid 后缀：每次自检独占夹具根；allowlist 夹具同名带 pid（见 _write_allowlist），
    # 仍落 $HOME/vgate-work（/tmp 配额有限，硬纪律 5）。
    base = os.path.join(os.path.expanduser("~"), "vgate-work",
                        "selftest-%d" % os.getpid())
    import shutil
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(os.path.join(base, "stream"), exist_ok=True)

    def w(rel, content):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    clean_stream = json.dumps({
        "identity": {"order_id": "demo__demo-1-a1", "model": "test-model",
                     "strategy_id": None, "dsl_digest": "ab12" * 16, "node": None},
        "updated_ms": 1793197898900,
        "terminal": {"stop_state": {"v": 0, "streak": None, "normal_errors": 0},
                     "turn_index": 2, "model_calls": 2},
        "turns": [{"turn": 0, "role": "assistant", "model": "test-model",
                   "finish": "stop", "usage": {"input_tokens": 16434, "output_tokens": 44,
                                               "cache_read_tokens": 15616},
                   "preview": "模型说：token 已刷新，usage 正常", "ts_ms": 1}],
        "events": [{"seq": 0, "kind": "harness.model", "ts_ms": 1,
                    "payload_head": "{\"run_id\": \"demo__demo-1-a1\"}"}],
        "counts": {"events_total": 1, "turns_total": 1,
                   "usage_sum": {"input_tokens": 1, "output_tokens": 1,
                                 "cache_read_tokens": 0}},
    }, ensure_ascii=False)
    w("orders.json", json.dumps({"ts": 1, "source": "selftest", "orders": [
        {"order_id": "demo__demo-1-a1", "unit": "swev", "last_activity": 1,
         "runs": [{"run_id": "demo__demo-1-a1", "stream_key": "demo__demo-1-a1",
                   "profile": "p", "model": "test-model", "stop": 0,
                   "updated_ms": 1}]}]}, ensure_ascii=False))
    w("stream/demo__demo-1-a1.json", clean_stream)
    w("quota.json", json.dumps({"ts": 1, "step": {"remaining": 1, "total": 2,
                                                  "used_percent": 50, "expires_at_ms": 1,
                                                  "seconds_to_expiry": 99, "go": True},
                                "minimax": {"go": True}}))
    w("data.json", json.dumps({"ts": 1, "plan": {"file": "计划/rel/path.json"},
                               "alarms": [{"level": "amber", "code": "A7",
                                           "message": "password: <none>；token=null",
                                           "key": "A7"}]}))

    # —— 反例（必须全绿：null/纯数字/<none>/digest 指纹均已内嵌进上面的干净夹具）——
    bad = []
    h, e, n, _ = scan_tree(base, [])
    if h or e or n != 4:
        bad.append(f"clean tree 不绿: hits={len(h)} errs={len(e)} scanned={n}")
        for x in (h + e)[:5]:
            bad.append(f"  {x}")

    # —— 键集冻结夹具（--freeze-keys）——
    # 机制自证（2026-11-03 publish-sc 批）：冻结检查此前是死开关（发布路径不带旗标），
    # 故本块必须自证「能红」：正例两形（成功态 / 死态 error 键）绿，未审新键红。
    q_orig = open(os.path.join(base, "quota.json"), encoding="utf-8").read()
    d_orig = open(os.path.join(base, "data.json"), encoding="utf-8").read()

    def _drift(errs):
        return [x for x in errs if "键集漂移" in x]

    # 正例①：成功态（上面 clean 夹具的实形）——冻结检查须零漂移
    _h, e, _n, _a = scan_tree(base, [], True)
    if _drift(e):
        bad.append(f"键集冻结误红（成功态 quota/data 形状应属冻结集）: {_drift(e)[:3]}")
    # 正例②：死态形状 {"go": false, "error": "<一句>"}（quota-governor DEB-7② 已审形状）
    w("quota.json", json.dumps({"ts": 1, "step": {"go": False, "error": "读取失败：占位"},
                                "minimax": {"go": False, "error": "读取失败：占位"}},
                               ensure_ascii=False))
    _h, e, _n, _a = scan_tree(base, [], True)
    if _drift(e):
        bad.append(f"键集冻结误红（死态 error 键属已审形状）: {_drift(e)[:3]}")
    # 反例①：治理器新加未审字段（step 段多一个 per-key 明细键）——必须红
    w("quota.json", json.dumps({"ts": 1, "step": {"remaining": 1, "total": 2,
                                                  "used_percent": 50, "expires_at_ms": 1,
                                                  "seconds_to_expiry": 99, "go": True,
                                                  "per_key_detail": {"k": 1}},
                                "minimax": {"go": True}}, ensure_ascii=False))
    _h, e, _n, _a = scan_tree(base, [], True)
    if not _drift(e):
        bad.append("键集冻结失灵：quota.json 多出未审键未拦（--freeze-keys 死开关复现）")
    # 反例②：data.json 顶层多一个未审键——必须红
    w("quota.json", q_orig)
    w("data.json", json.dumps({"ts": 1, "plan": {"file": "占位/路径.json"},
                               "alarms": [], "extra_unreviewed_key": 1},
                              ensure_ascii=False))
    _h, e, _n, _a = scan_tree(base, [], True)
    if not _drift(e):
        bad.append("键集冻结失灵：data.json 多出未审顶层键未拦")
    w("data.json", d_orig)

    # —— 正例/tamper（必须红）。载体 = stream/probe.json（白名单内路径，
    #    非 JSON 内容只附加 STRUCT err，不影响命中判定）——
    probes = {
        "K-09 Bearer 头": 'Authorization: Bearer PLACEHOLDER1234567890',
        "K-02 sk- 前缀": "key = sk-PLACEHOLDER0000000000000000",
        "K-06/07/08/11 赋值对": '"access_token": "PLACEHOLDER-TOKEN-VALUE-000000"',
        "K-01 JWT 三段式": "eyJTESTTESTTEST.eyJTESTTESTTEST.SIGNATURETEST1234",
        "K-05 PEM 私钥块": "-----BEGIN OPENSSH PRIVATE KEY-----\nPLACEHOLDERKEYBODY\n-----END OPENSSH PRIVATE KEY-----",
        "X-02 长 hex 赋值": "nonce = 0123456789abcdef0123456789abcdef",
        "X-01 长 base64 赋值": 'client_secret = cGxhY2Vob2xkZXJzZWNyZXR2YWx1ZTAwMDAwMDAwMDA=',
        "O-01 tailnet CGNAT": "endpoint http://100.64.0.6:8300/api",
        "O-03 home 路径": "path /home/testuser/workspace/x",
        "O-04 内网主机别名": "host mingda-bench:15221",
        "K-03 GitHub PAT": "ghp_PLACEHOLDER1234567890abcdef",
        "K-04 AWS AK": "AKIAIOSFODNN7EXAMPLE",
    }
    for pid, content in probes.items():
        with open(os.path.join(base, "stream", "probe.json"), "w", encoding="utf-8") as f:
            f.write(content)
        h, e, _n, _a = scan_tree(base, [])
        fired = any(x["pattern"].split(" ", 1)[0] == pid.split(" ", 1)[0] for x in h)
        if not fired:
            bad.append(f"tamper 探针未红: {pid}")
    os.unlink(os.path.join(base, "stream", "probe.json"))

    # —— 结构类 tamper（点开头/白名单外 → exit 2 口径）——
    w("stream/.tailer-state.json", '{"version": 1}')
    h, e, _n, _a = scan_tree(base, [])
    if not any("黑名单" in x for x in e):
        bad.append("点开头文件未被拦")
    os.unlink(os.path.join(base, "stream", ".tailer-state.json"))
    w("random.txt", "hello")
    h, e, _n, _a = scan_tree(base, [])
    if not any("白名单外" in x for x in e):
        bad.append("白名单外文件未被拦")
    os.unlink(os.path.join(base, "random.txt"))

    # —— allowlist 豁免 + 过期失效 ——
    w("data.json", json.dumps({"ts": 1, "plan": {"file": "/home/testuser/x"},
                               "alarms": []}))
    alfx = _write_allowlist(base, expires="2099-12-31")
    al = load_allowlist(alfx)
    h, e, _n, allowed_n = scan_tree(base, al)
    if h or allowed_n != 1:
        bad.append(f"allowlist 未按预期豁免: hits={len(h)} allowed={allowed_n}")
    al = load_allowlist(_write_allowlist(base, expires="2020-01-01"))
    h, e, _n, allowed_n = scan_tree(base, al)
    if not h:
        bad.append("过期 allowlist 未失效（应重新拦）")

    # —— --redact 闭环：打码后复扫必须全绿；值侧打码须保留键名（可读性）——
    w("data.json", json.dumps({"ts": 1, "plan": {"file": "/home/testuser/x"},
                               "alarms": [{"message": "access_token=PLACEHOLDER-TOKEN-VALUE-000000",
                                           "code": "A0"}]}))
    acts = redact_tree(base, [])
    h, e, _n, _a = scan_tree(base, [])
    after = json.load(open(os.path.join(base, "data.json")))
    msg = after["alarms"][0]["message"]
    if h or e:
        bad.append(f"--redact 后仍不绿: hits={len(h)} errs={len(e)}")
    if "▉▉▉" not in json.dumps(after, ensure_ascii=False):
        bad.append("--redact 未见打码标记")
    if "access_token=" not in msg or "PLACEHOLDER-TOKEN-VALUE-000000" in msg:
        bad.append(f"--redact 可读性回归（值侧应打码、键名应保留）: {msg}")
    if not acts:
        bad.append("--redact 无动作记录")

    shutil.rmtree(base, ignore_errors=True)
    try:
        os.unlink(alfx)  # allowlist 夹具在树外（~/vgate-work/），须单独清（原实现漏删）
    except OSError:
        pass
    if bad:
        print("SELFTEST FAIL:")
        for b in bad:
            print(f"  {b}")
        return 1
    print(f"SELFTEST PASS ({VERSION})：clean 绿 / 12 tamper 红 / 结构拦 2 / "
          f"allowlist 豁免+过期失效 / --redact 闭环 / 键集冻结正反例（成功态+死态绿、"
          f"未审新键红）")
    return 0


def _write_allowlist(base, expires):
    # 注意：夹具必须落在被扫树之外（树内非白名单文件会触发 STRUCT，污染断言）
    # 带 pid：base 已按运行隔离，但 dirname(base)=~/vgate-work 仍共享——固定名会让
    # 并发自检互写对方的过期/豁免夹具（同一非密闭竞态），故夹具名同随 pid。
    p = os.path.join(os.path.dirname(base),
                     "allowlist-fixture-%d.json" % os.getpid())
    with open(p, "w", encoding="utf-8") as f:
        json.dump([{"pattern": "O-03", "file": "data.json",
                    "reason": "selftest fixture", "approved_by": "selftest",
                    "expires": expires}], f)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公网 v2 流式视图发布前脱敏闸：命中即阻断（fail-closed）")
    ap.add_argument("tree", nargs="?", help="待发布树目录")
    ap.add_argument("--json", action="store_true", help="机器可读裁决")
    ap.add_argument("--redact", action="store_true",
                    help="就地保守打码（仅许对副本/暂存树用！）后自动复扫")
    ap.add_argument("--allowlist", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "publish-allowlist.json"),
        help="误报白名单（默认 tools/publish-allowlist.json；无文件=空白名单）")
    ap.add_argument("--freeze-keys", action="store_true",
                    help="追加 quota/data 键集冻结检查（超集即拦）")
    ap.add_argument("--max-hits", type=int, default=MAX_HITS_DEFAULT,
                    help=f"命中明细输出上限（默认 {MAX_HITS_DEFAULT}，计数不受限）")
    ap.add_argument("--selftest", action="store_true", help="内置夹具自检后退出")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.tree:
        ap.error("缺少待发布树目录（或用 --selftest）")
    if not os.path.isdir(args.tree):
        print(f"STRUCT 目录不存在: {args.tree}", file=sys.stderr)
        return 2

    al = load_allowlist(args.allowlist)
    redacted = []
    if args.redact:
        redacted = redact_tree(args.tree, al)

    hits, errs, scanned, allowed_n = scan_tree(args.tree, al, args.freeze_keys)
    verdict = "block" if (hits or errs) else "ok"

    if args.json:
        print(json.dumps({"verdict": verdict, "version": VERSION, "scanned": scanned,
                          "allowlisted": allowed_n, "hits": hits, "errors": errs,
                          "redacted": redacted, "tally": tally(hits)},
                         ensure_ascii=False))
        # --json 模式 stdout 只出 JSON；人读明细走 stderr（日志仍可见）
        for a in redacted:
            print(f"REDACTED {a['file']} 模式={a['patterns']}", file=sys.stderr)
        for line in render_hits(hits, args.max_hits):
            print(line, file=sys.stderr)
        if len(hits) > args.max_hits:
            print(f"... 其余 {len(hits) - args.max_hits} 条命中从略（tally 见 --json）",
                  file=sys.stderr)
        if hits or errs:
            print(f"SCRUB GATE: FAIL —— {len(hits)} 命中 / {len(errs)} 结构问题"
                  f"（allowlist 豁免 {allowed_n}）→ 拒发", file=sys.stderr)
            return 1 if hits else 2
        return 0

    for a in redacted:
        print(f"REDACTED {a['file']} 模式={a['patterns']}")
    for line in render_hits(hits, args.max_hits):
        print(line)
    for e in errs:
        print(f"STRUCT {e}", file=sys.stderr)
    if len(hits) > args.max_hits:
        print(f"... 其余 {len(hits) - args.max_hits} 条命中从略（tally 见 --json）",
              file=sys.stderr)

    if hits or errs:
        print(f"SCRUB GATE: FAIL —— {len(hits)} 命中 / {len(errs)} 结构问题"
              f"（allowlist 豁免 {allowed_n}）→ 拒发", file=sys.stderr)
        return 1 if hits else 2
    if args.redact and redacted:
        print("SCRUB GATE: PASS（--redact 打码后复扫全绿）")
    else:
        print("SCRUB GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
