#!/usr/bin/env bash
# =============================================================================
# mirror-disclose.sh — GitHub 披露镜像生产闸（v0.3 T7 终裁③：节拍快照人工化）
#
# 裁决背景（v0.3 T7 终裁第③条，2026-11-04）：
#   镜像 PAT 短期无归位 ⇒ 凭证模型未接前，GitHub 披露镜像 = 运营者手动 + 脚本辅助。
#   本脚本只把"脏活"做完：filter-repo 历史裁剪（路径级 allowlist/denylist）→
#   重写后全历史密钥终扫（13 通用 + 5 项目自有模式）→ 本地快照落盘
#   （普通仓目录 + git bundle）。**披露/上传这一步是人做的，脚本不含任何
#   上传动作**——产出物只在本地 RUNDIR，人拿去按自己的常规通道发布。
#
# 为什么镜像不是备份（本件存在的第一条理由）：
#   filter-repo 重写历史 ⇒ 全部提交哈希断裂 ⇒ 镜像与任何既有远端（gitea/github）
#   的共同历史被切断。若误把 GitHub 当备份、从它回拉，得到的是断裂哈希链，
#   与 gitea 对不上账、无法合并，等于把唯一真源搞脏。**镜像纯披露非备份，
#   回源唯一 = gitea（http://gov-host.invalid:3300/opchadmin/af.git）**。
#
# 2026-11-04 下午修复批（v2.0；改前现场存档 tools/mirror-disclose.sh.20261104-pre-scanfix.bak）：
#   改前实测（主代理 2026-11-04 17:40，af 真仓 1.6G .git 全量终扫）：终扫进程 CPU 1h45m+
#   且不增长；120 秒采样 rchar 增量 0、CPU 增量 119s；cat-file --batch 已写 904,113,133 字节
#   而扫描端只读 90,782 字节 ⇒ 扫描端阻塞在病态 blob（000b8141…，8,449,280 B，
#   poc-temporal rust-sdk 编译产物 .so）的正则回溯上。本批三修复：
#   ① 二进制识别与跳过：对象体含 NUL 字节 ⇒ 判二进制，不喂正则；逐件登记进
#      scan-binary.txt（kind=binary 另走「高信度前缀定点探针」字节字面量路；
#      kind=compressed（压缩魔数）= 明文探针与模式扫描均不适用 ⇒ 如实登记为未覆盖面，
#      manifest 带计数，绝不静默跳过、绝不装作扫过）。
#   ② G-13 去灾难性回溯：改「关键词预筛（纯字面量轮转，线性）+ 锚点有界回看（≤64 词字符）」，
#      键名表扩充（pwd/passwd/apikey/access_key/cred/auth_*）+ 大小写不敏感；
#      改前能检出的改后一处不少（自检含改前/改后样本集合对拍与病态样本对照）。
#   ③ 单 blob 护栏：每对象扫描有独立时间预算（缺省 max(30s, 30s/MB)，上限 600s；
#      MIRROR_DISC_BUDGET_SECS 可覆盖）；超预算重投一次仍超 ⇒ RED-TIMEOUT 记红报出、
#      整跑非零退出（进程池硬杀重建，工具不得被输入挂死）；>256MB 对象不进扫描器
#      ⇒ RED-OVERSIZE 记红。红 = 覆盖不完整，披露前必须人工复核。
#
# 2026-11-04 傍晚修补批（v2.1；改前现场存档 tools/mirror-disclose.sh.20261104-pre-p03fix.bak）：
#   P-03 字符类修补（复核意见必修项）：改前 P-03 第 1 段字符类 [A-Za-z0-9_-] 与真实
#   依据面不符——~/.zcode/v2/credentials.json 8 键第 1 段（23 字符）各含 2 个内部
#   ASCII 冒号（U+003A，Unicode 类别 Po，非边界位），改前式对 8/8 真实值 0 命中
#   （纯形状探针实测，零值进输出）；另实测尾段最小 11 字符（oauth:active_provider），
#   改前式尾段下限 {30,} 同样漏该键。修补：第 1 段字符类并入实测冒号与 base64 标准字母
#   +/ 及填充 =（检出集只增不减：改前能抓的合成形态逐一复抓），尾段下限 {30,}→{11,}
#   （取实测最小段长）。改后对 8 键重跑形状验证：8/8 命中、逐段零出类（零值进输出）。
#   段长/字符集窗外形态仍漏（如实登记，见 --patterns 与 mirror-03 漏检边界）。
#
# 用法：
#   mirror-disclose.sh <源仓路径>                    # 默认干跑：只打印计划，不产快照
#   mirror-disclose.sh <源仓路径> --emit             # 真产出：RUNDIR 落本地快照（终扫全绿才落）
#   mirror-disclose.sh <源仓路径> --scan-only        # 只跑到终扫并落扫描证据，不产快照
#   mirror-disclose.sh --patterns                    # 打印 13+5 模式表（ID/名/归属/正则）
#   mirror-disclose.sh --selftest                    # 内置夹具自检（假密钥占位符，零真实凭据）
#   mirror-disclose.sh --g13 FILE                    # 自检面：对指定文件只跑 G-13 新机制（报行号）
#
# 选项：
#   --allowlist FILE     路径白名单（缺省 = 脚本旁 mirror-allowlist.paths；
#                        文件不存在 = 不启用白名单；存在但有效行=0 = 配置错误 exit 2。
#                        语义：启用后【只】保留名单内路径进镜像）
#   --denylist FILE      路径黑名单（缺省 = 脚本旁 mirror-denylist.paths；
#                        文件缺失或有效行=0 = 配置错误 exit 2。
#                        语义：名单内路径一律不得进镜像，【优先级高于白名单】）
#   --scan-allowlist F   终扫误报豁免清单（缺省 = 脚本旁 mirror-scan-allowlist.json，
#                        publish-allowlist.json 同形：pattern/file/reason/approved_by/expires，
#                        过期自动失效；解析失败 = 按无豁免处理 fail-closed。
#                        ⚠ 豁免 ≠ 打码：被豁免的命中仍会随镜像披露，豁免只许用于误报；
#                        真凭据请改用 denylist 移除路径）
#   --rundir DIR         产出目录覆盖（缺省 = $MIRROR_RUN_BASE/<输入指纹>；
#                        MIRROR_RUN_BASE 缺省 = ~/mirror-disclose-runs）
#   --run-base DIR       产出根目录覆盖
#   -h | --help          本说明
#
# 环境旋钮（终扫护栏；不设 = 缺省值）：
#   MIRROR_DISC_WORKERS       扫描进程池大小（缺省 4；worker 另加 nice 降优先级让位在役服务）
#   MIRROR_DISC_BUDGET_SECS   单对象扫描预算覆盖（缺省 max(30, 30s/MB)、上限 600s；
#                             自检用它演示护栏红。超预算 → RED-TIMEOUT，整跑非零退出）
#   MIRROR_DISC_MAXBLOB       不进扫描器的对象体积上限字节（缺省 268435456 = 256MB；
#                             超限 → RED-OVERSIZE，如实报出不静默）
#   TMPDIR                    历史重写的临时目录（af 级大仓须指到大盘，见磁盘预检）
#
# 产出（--emit 且终扫全绿时；--scan-only 只落扫描证据；缺省 = 无任何产出）：
#   <rundir>/mirror-repo.git/     裁剪+终扫后的裸仓（全部分支/标签；origin 已删）
#   <rundir>/<repo>-disclose.bundle  同历史的 git bundle（人拿去发布的一种形态）
#   <rundir>/scan-report.txt      终扫读数（HIT/PROBE-HIT/EXEMPT/RED；零原文零值）
#   <rundir>/scan-binary.txt      二进制面逐件登记（BIN-SKIP；非静默跳过的台账）
#   <rundir>/manifest.json        机器可读清单（指纹/计数/裁决，无时间戳，幂等）
#   <rundir>/DISCLOSE-NOTE.md     给披露执行人的一页纸（非备份警告/回源=gitea/人工步骤）
#   <rundir>/config/              本次生效的三份清单副本（审计留痕）
#
# 终扫（在【重写后的全部历史】上跑，不是只扫工作树）：
#   13 条通用凭据模式（JWT/sk-/GitHub PAT/AKIA/Slack 等/G-13 赋值对…）
#   + 5 条项目自有模式（P-01 URL 直嵌凭据 / P-02 openBao hvs.+s. 双形 /
#     P-03 模型厂商三段点分键 / P-04 内网 CGNAT 直连面 / P-05 af 门户 claim_token）
#   模式表逐条出处见 30-工件/镜像披露-20261104/mirror-disclose-report.md；
#   项目自有 5 条的事实依据见 mirror-01-凭据面盘点.md。
#   命中或护栏红即红：exit 1，RUNDIR 只落扫描证据 + manifest(verdict=blocked)，不落快照。
#
# 幂等：同一源仓状态 + 同三份清单 ⇒ RUNDIR 同名、内容字节一致（无时间戳/无 pid）。
# 失败响亮：退出码 0=绿 / 1=红（命中、护栏红或结构校验败，原因逐条打印）/
#           2=用法或环境错误（缺工具、清单缺失或歧义、磁盘预检不过）。
# 纪律：本文件（含注释与生成文本）刻意不含英文推送/上传动词词根——
#       `grep -nwiE 'pu[s]h|upl[o]ad|cu[r]l|wg[e]t|sc[p]|rs[y]n[c]|s[s]h|\b[n]c\b' 本件`
#       必须零命中（括号断字让模式串互不匹配自身，含 rs[y]n[c] 尾部）——
#       这是「脚本无推送路径」的机检锚，任何第三方跑同一条 grep 都应得零。
#       远端配置操作仅限 remove（删 origin 指针），零 add / set-url。
#       git 写操作仅限本地：bundle create / clone / filter-repo / gc。
# =============================================================================
set -euo pipefail

VERSION="mirror-disclose-2.1 (2026-11-04 修补批)"
SELF="$(readlink -f "$0")"
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"

ALLOWLIST_DEF="$SCRIPT_DIR/mirror-allowlist.paths"
DENYLIST_DEF="$SCRIPT_DIR/mirror-denylist.paths"
SCANAL_DEF="$SCRIPT_DIR/mirror-scan-allowlist.json"

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
ok()  { printf '  ✓ %s\n' "$*" >&2; }
die()  { printf '[RED] %s\n' "$*" >&2; exit 1; }   # 红：命中/护栏红/校验败
die2() { printf '[FATAL] %s\n' "$*" >&2; exit 2; } # 用法/环境错误
CLEANUP_DIR=""   # EXIT trap 清理目标（全局，函数内赋值——局部变量出栈后 trap 仍可见）

f12()  { sha256sum "$1" 2>/dev/null | cut -c1-12; }        # 文件指纹 12 位
s12()  { sha256sum | cut -c1-12; }                          # stdin 指纹 12 位

need_cmd() { command -v "$1" >/dev/null 2>&1 || die2 "缺 $1，本闸不可执行（不可证不猜绿；禁临时装系统包，如实登记）"; }

usage() { sed -n '2,74p' "$SELF" | sed 's/^# \{0,1\}//'; }

# ---- 清单语法工具 ----------------------------------------------------------
list_valid() {  # 有效行数（非空、非 # 开头）
  sed 's/^[[:space:]]*//' "$1" | awk '/^(#|$)/{next} {n++} END{print n+0}'
}
list_has_rename() {  # '==>' 是 filter-repo 的重命名语法，纯允许/拒绝语义不允许
  # 只查有效行（注释/空行 filter-repo 本就忽略；注释里提到该记号不构成配置）
  sed 's/^[[:space:]]*//' "$1" | grep -vE '^(#|$)' | grep -Fq -- '==>'
}

# ---- 内嵌 python：模式表 / 结构校验 / 终扫（单一真源，五个模式共用）--------
run_py() { # $1=MD_MODE 其余经环境变量传入；python 代码经 stdin
  MD_MODE="$1" MD_VERSION="$VERSION" python3 -I - <<'PYEOF'
import os, re, sys, json, time, fnmatch, subprocess, bisect, signal

MODE = os.environ.get("MD_MODE", "")

# ---------------------------------------------------------------------------
# G-13 线性化重写（2026-11-04 下午修复批，②号修复）：
#   改前式（骨架逐字取自现场残片，键名表按 mirror-disclose-report.md §模式表复原）：
#     ['"]?[A-Za-z0-9_-]*(?:password|secret|token|api_key|credential)s?['"]?\s*[:=]\s*
#     ['"]?(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s"',;}]{6,}
#   病灶：无界前缀字符类 [A-Za-z0-9_-]* 在「长词字符串」（.so 符号表、base64 块等）
#     上逐步回溯 × 词表逐个试 ⇒ 每个起点 O(前缀长)，对 8.4MB 编译产物整段爆炸
#     （主代理 2026-11-04 17:40 实测：单 blob 7.5s 起直至 1h45m 不完成；
#     cat-file 已写 904,113,133 字节而扫描端只读走 90,782 字节）。
#   改法：关键词预筛（纯字面量轮转，整段线性）→ 每个关键词锚点做【有界】回看
#     （前缀至多回看 64 个词字符）→ 总代价 O(n·|词表|) + O(候选数·64)，无嵌套量词。
#   语义：键名表扩充 + 大小写不敏感（检出差集只增不减）；改前能检出的改后一处不少
#     （自检含改前/改后同批样本检出集合对拍 + 病态样本对照，证据见 30-工件/镜像披露-20261104/）。
# ---------------------------------------------------------------------------
_G13_WORDS = ("password|passwd|pwd|secret|token|api_key|apikey|access_key|"
              "auth_key|auth_token|credential|cred")
G13_DISPLAY = ("(?i)(?:[a-z0-9_-]{0,64})?(?:" + _G13_WORDS +
               r")s?['\"]?\s{0,16}[:=]\s{0,16}['\"]?"
               r"(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,4096}")
G13_FULL = re.compile(G13_DISPLAY)
G13_KW = re.compile("(?i)(?:" + _G13_WORDS + ")")
G13_WC = re.compile(r"[A-Za-z0-9_-]")
G13_LOOKBACK = 64

def scan_g13(text, ln_of):
    """G-13 新机制：预筛锚点 + 有界回看匹配。返回 [( "G-13", 行号 )]。"""
    out = []
    last_end = -1
    for kw in G13_KW.finditer(text):
        p = kw.start()
        if p < last_end:
            continue
        lo = p
        floor_ = p - G13_LOOKBACK
        if floor_ < 0:
            floor_ = 0
        while lo > floor_ and G13_WC.match(text, lo - 1):
            lo -= 1
        m = G13_FULL.match(text, lo)
        if m is None or m.start() < last_end:
            continue
        last_end = m.end()
        out.append(("G-13", ln_of(m.start())))
    return out

# ---------------------------------------------------------------------------
# 模式表：13 通用 + 5 项目自有。
# 通用 13 条与 tools/publish-scrub-gate.py K 族（密钥终扫-20261024.md:15 的
# 任务书 13 项实装版）同源同形；项目自有 5 条来自 mirror-01-凭据面盘点.md 的
# 实盘事实（形态实测：gitea 40-hex URL 口令 / openBao s.+24 与 hvs. 双形 /
# bigmodel 三段点分 23.22.N【段长与字符集均实测：seg1 含内部 ASCII 冒号 ×2，
# 20261104 v2.1 修补批据此拓宽第 1 段字符类并降尾段下限至实测最小 11】 /
# CGNAT 100.64/10 / af 门户 claim_token=uuid4().hex，
# af-jobs-portal.py:932）。所有量词均有界或锚定在字面量上，全表无嵌套量词。
# ---------------------------------------------------------------------------
PATTERNS = [
    ("G-01", "JWT 三段式", "通用",
     r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}"),
    ("G-02", "sk- 前缀（OpenAI/Anthropic/MiniMax 系）", "通用",
     r"\bsk-[A-Za-z0-9_-]{8,}"),
    ("G-03", "GitHub PAT 前缀族（ghp/gho/ghu/ghs/github_pat_）", "通用",
     r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    ("G-04", "AWS 访问键（AKIA…）", "通用",
     r"\bAKIA[0-9A-Z]{14,22}\b"),
    ("G-05", "Slack 及其余厂商前缀（xox*/glpat-/hf_/xai-）", "通用",
     r"\bxox[baprs]-[A-Za-z0-9-]{10,}|\bglpat-[A-Za-z0-9_-]{15,}|\bhf_[A-Za-z0-9]{20,}|\bxai-[A-Za-z0-9]{20,}"),
    ("G-06", "Google API 键（AIza…）", "通用",
     r"\bAIza[0-9A-Za-z_-]{30,}"),
    ("G-07", "Stripe 密钥（sk/rk_test|live_…）", "通用",
     r"\b[sr]k_(?:test|live)_[0-9a-zA-Z]{16,}"),
    ("G-08", "SendGrid API 键（SG.x.y）", "通用",
     r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{27,}"),
    ("G-09", "npm 令牌（npm_ + 36）", "通用",
     r"\bnpm_[A-Za-z0-9]{36}"),
    ("G-10", "PyPI 令牌（pypi-…）", "通用",
     r"\bpypi-[A-Za-z0-9_-]{40,}"),
    ("G-11", "Bearer 头", "通用",
     r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}"),
    ("G-12", "PEM 私钥块", "通用",
     r"-----BEGIN [A-Za-z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Za-z ]*PRIVATE KEY-----|-----BEGIN [A-Za-z ]*PRIVATE KEY-----"),
    ("G-13", "通用凭据赋值对（password/pwd/passwd/secret/token/api_key/access_key/credential/cred…= 值侧；20261104 线性化重写）", "通用",
     G13_DISPLAY),
    ("P-01", "URL 直嵌凭据（scheme://user:pass@，gitea PAT 的常见落点形态）", "项目自有",
     r"\b[a-z][a-z0-9+.-]{1,15}://[^\s/:@]+:[^\s/@]{4,}@"),
    ("P-02", "openBao 令牌（hvs. / s. 双形，本地 root 实存 s.+24）", "项目自有",
     r"\bhvs\.[A-Za-z0-9_-]{10,}|\bs\.[A-Za-z0-9]{20,40}\b"),
    ("P-03", "模型厂商三段点分长键（23.22.N，非 eyJ 开头；seg1 含实测内部标点 :，20261104 v2.1 字符类修补）", "项目自有",
     r"\b[A-Za-z0-9_+/=:-]{20,30}\.[A-Za-z0-9_-]{18,26}\.[A-Za-z0-9_-]{11,}"),
    ("P-04", "内网 CGNAT 直连面（100.64/10 地址本身不得外流）", "项目自有",
     r"\b100\.0*(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    ("P-05", "af 门户 claim_token（键名伴随 uuid4 hex32）", "项目自有",
     r"[\"']?claim_token[\"']?\s*[:=]\s*[\"']?[0-9a-f]{32}"),
]
COMPILED = [(pid, name, re.compile(rx)) for pid, name, fam, rx in PATTERNS
            if pid != "G-13"]          # G-13 走预筛机制（见上），其余 17 条直编译
NAMES = {pid: name for pid, name, fam, rx in PATTERNS}

# ---------------------------------------------------------------------------
# 二进制面处置（2026-11-04 下午修复批，①号修复）：
#   判据（可解释、确定性）：对象体任意位置含 NUL 字节 ⇒ 二进制，不喂正则。
#   kind=binary      → 另走「高信度前缀定点探针」：只查厂商前缀/私钥块头的字节
#                      字面量（bytes.find，零正则零回溯）。这些前缀几乎不出现在
#                      编译产物里，一旦出现即强信号 ⇒ 计红。
#   kind=compressed  → 压缩魔数（gzip/bzip2/xz/zstd/zip/7z/lz4）：明文探针与模式
#                      扫描均不适用 ⇒ 如实登记为未覆盖面（台账+计数），不装作扫过。
#   两类都逐件写进 scan-binary.txt（非静默跳过），manifest 带计数。
# ---------------------------------------------------------------------------
COMPRESSED_MAGICS = (b"\x1f\x8b", b"BZh", b"\xfd7zXZ", b"\x28\xb5\x2f\xfd",
                     b"PK\x03\x04", b"PK\x05\x06", b"7z\xbc\xaf\x27\x1c",
                     b"\x04\x22\x4d\x18")
PROBES = (
    (b"AKIA", "G-04"),
    (b"ghp_", "G-03"), (b"gho_", "G-03"), (b"ghu_", "G-03"), (b"ghs_", "G-03"),
    (b"github_pat_", "G-03"),
    (b"xoxb-", "G-05"), (b"xoxp-", "G-05"), (b"xoxa-", "G-05"),
    (b"xoxr-", "G-05"), (b"xoxs-", "G-05"),
    (b"sk-ant-", "G-02"), (b"sk-proj-", "G-02"),
    (b"AIza", "G-06"), (b"npm_", "G-09"), (b"pypi-", "G-10"),
    (b"glpat-", "G-05"), (b"hf_", "G-05"), (b"hvs.", "P-02"),
    (b"-----BEGIN OPENSSH PRIVATE KEY-----", "G-12"),
    (b"-----BEGIN RSA PRIVATE KEY-----", "G-12"),
    (b"-----BEGIN EC PRIVATE KEY-----", "G-12"),
    (b"-----BEGIN PRIVATE KEY-----", "G-12"),
    (b"-----BEGIN PGP PRIVATE KEY BLOCK-----", "G-12"),
)

def scan_text(text):
    """全 18 模式扫一段文本。返回去重后的 [(pid, 行号)]（不含原文）。"""
    recs = []
    seen = set()
    nl = None
    def ln_of(pos):
        nonlocal nl
        if nl is None:
            nl = [m.start() for m in re.finditer("\n", text)]
        return bisect.bisect_right(nl, pos) + 1
    for pid, name, rx in COMPILED:
        for m in rx.finditer(text):
            key = (pid, ln_of(m.start()))
            if key not in seen:
                seen.add(key)
                recs.append(key)
    for key in scan_g13(text, ln_of):
        if key not in seen:
            seen.add(key)
            recs.append(key)
    return recs

def git(args, cwd, data=None):
    p = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, input=data)
    if p.returncode != 0:
        sys.stderr.write("ENV-FAIL git %s: %s\n" % (" ".join(args[:2]),
                        p.stderr.decode("utf-8", "replace")[:500]))
        sys.exit(2)
    return p.stdout

# ---- 模式：--patterns ------------------------------------------------------
if MODE == "patterns":
    print("mirror-disclose 终扫模式表（13 通用 + 5 项目自有 = %d 条）" % len(PATTERNS))
    print("%-5s %-4s %-46s %s" % ("ID", "归属", "模式名", "正则"))
    for pid, name, fam, rx in PATTERNS:
        print("%-5s %-4s %-46s %s" % (pid, fam, name, rx))
    print("# 注：G-13 实现走「关键词预筛 + 锚点有界回看」（语义同上式；代价线性——")
    print("#      改前无界前缀逐步回溯在长词字符串上爆炸，2026-11-04 下午修复批重写）。")
    sys.exit(0)

# ---- 清单解析（与 git-filter-repo --paths-from-file 同口径）-----------------
def parse_list(path):
    """返回 [(type, pattern)]；type ∈ literal/glob/regex。注释/空行忽略。
    literal 匹配 = filter-repo filename_matches：前缀相等且（以 / 结尾 或
    全等 或 路径下一字符是 /）。"""
    out = []
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", "replace")
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("literal:"):
            out.append(("literal", ln[8:]))
        elif ln.startswith("glob:"):
            out.append(("glob", ln[5:]))
        elif ln.startswith("regex:"):
            out.append(("regex", ln[6:]))
        else:
            out.append(("literal", ln))
    return out

REGEXES = {}
def entry_match(entry, path):
    t, pat = entry
    if t == "literal":
        n = len(pat)
        return path.startswith(pat) and (pat.endswith("/") or len(path) == n
                                         or path[n:n+1] == "/")
    if t == "glob":
        return fnmatch.fnmatch(path, pat)
    rx = REGEXES.get(pat)
    if rx is None:
        rx = REGEXES[pat] = re.compile(pat)
    return rx.search(path) is not None

def all_history_paths(repo):
    out = git(["rev-list", "--all", "--objects"], repo).decode("utf-8", "replace")
    return sorted({ln.partition(" ")[2] for ln in out.splitlines() if ln.strip()
                   and ln.partition(" ")[2]})

# ---- 模式：verify（裁剪结构校验：deny 零残留 + allow 全覆盖）----------------
if MODE == "verify":
    repo = os.environ["MD_REPO"]
    deny = parse_list(os.environ["MD_DENYLIST"])
    al_path = os.environ.get("MD_ALLOWLIST", "")
    allow = parse_list(al_path) if al_path and os.path.isfile(al_path) else []
    paths = all_history_paths(repo)
    leaks = [p for p in paths if any(entry_match(e, p) for e in deny)]
    bad_allow = []
    if allow:
        bad_allow = [p for p in paths if not any(entry_match(e, p) for e in allow)]
    for p in leaks:
        print("VERIFY-DENY-LEAK %s" % p)
    for p in bad_allow:
        print("VERIFY-ALLOW-VIOLATION %s" % p)
    sys.stderr.write("VERIFY paths=%d deny_rules=%d allow_rules=%d "
                     "deny_leaks=%d allow_violations=%d\n"
                     % (len(paths), len(deny), len(allow), len(leaks), len(bad_allow)))
    sys.exit(1 if (leaks or bad_allow) else 0)

# ---- 模式：--g13（自检面：只对指定文件跑 G-13 新机制，报行号，零原文）--------
if MODE == "g13file":
    path = os.environ["MD_FILE"]
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", "replace")
    nl = [m.start() for m in re.finditer("\n", text)]
    t0 = time.monotonic()
    out = scan_g13(text, lambda pos: bisect.bisect_right(nl, pos) + 1)
    for pid, ln in sorted(set(out)):
        print("G13HIT %s:%d" % (path, ln))
    sys.stderr.write("G13 elapsed=%.3fs hits=%d bytes=%d\n"
                     % (time.monotonic() - t0, len(set(out)), len(text)))
    sys.exit(0)

# ---- 模式：scan（重写后全部历史的密钥终扫；二进制面处置 + 单对象护栏）--------
def load_exempt(path):
    """publish-allowlist.json 同形豁免；解析失败=无豁免（fail-closed）；
    过期条目自动失效。返回 (有效条目, 登记串)。"""
    if not path or not os.path.isfile(path):
        return [], "missing"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        sys.stderr.write("WARN scan-allowlist 解析失败(%s) → 按无豁免处理（fail-closed）\n" % e)
        return [], "parse-fail"
    today = time.strftime("%Y-%m-%d")
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        if not e.get("pattern") or not e.get("file") or not e.get("reason"):
            continue
        if str(e.get("expires", "")) < today:
            continue
        out.append(e)
    return out, "ok"

if MODE == "scan":
    import multiprocessing as mp
    repo = os.environ["MD_REPO"]
    sal_path = os.environ.get("MD_SCANAL", "")
    binreg_path = os.environ.get("MD_BINREG", "")
    stats_path = os.environ.get("MD_STATS", "")
    exempt, sal_state = load_exempt(sal_path)

    def env_int(name, default):
        v = os.environ.get(name, "")
        if not v:
            return default
        try:
            return max(1, int(v))
        except ValueError:
            return default

    W = env_int("MIRROR_DISC_WORKERS", 4)
    if (os.cpu_count() or 1) < W:
        W = os.cpu_count() or 1
    MAXBLOB = env_int("MIRROR_DISC_MAXBLOB", 268435456)   # 256MB
    BUDGET_ENV = os.environ.get("MIRROR_DISC_BUDGET_SECS", "")
    def budget_for(size):
        if BUDGET_ENV:
            try:
                return max(1, int(BUDGET_ENV))
            except ValueError:
                pass
        mb = size / 1048576.0
        return int(min(max(30, 30 * mb), 600))

    lines = git(["rev-list", "--all", "--objects"], repo).decode(
        "utf-8", "replace").splitlines()
    sha_paths = {}
    shas = set()
    for ln in lines:
        if not ln.strip():
            continue
        s, _, pth = ln.partition(" ")
        shas.add(s)
        if pth:
            sha_paths.setdefault(s, set()).add(pth)
    chk = git(["cat-file", "--batch-check"], repo,
              ("\n".join(sorted(shas)) + "\n").encode())
    kind = {}
    for ln in chk.decode("utf-8", "replace").splitlines():
        parts = ln.split()
        if len(parts) >= 2:
            kind[parts[0]] = parts[1]
    n_commits = sum(1 for v in kind.values() if v == "commit")
    want = sorted(s for s in shas if kind.get(s) in ("blob", "commit", "tag"))

    # ── 单对象护栏（③号修复）：fork 进程池 + 每对象时间预算 + 看门狗硬杀重建。
    # worker 内 signal.alarm 是软闸（纯 python 段可被打断）；C 层正则若吞掉软闸，
    # 看门狗按单调钟超时 → terminate + kill 整池硬杀 → 记红 → 重建池续扫，
    # 在途未超时对象原样重投（重投一次仍超 ⇒ 放弃记红）。绝不允许被输入挂死。
    ctx = mp.get_context("fork")
    # 2026-11-04 af 真仓实测教训（两连坑，均已修）：
    #   ① Pool 的 fork 必须发生在 _scan_task 等 worker 函数定义【之后】——先建池后定义，
    #     首批 worker 的 fork 快照里没有任务函数 ⇒ 反序列化即崩（AttributeError）⇒
    #     在途任务丢失，只能靠 30s 看板兜底重投（慢且绕）。
    #   ② worker 继承了 cat-file 的 stdin 写端 ⇒ 喂入线程关闭自己那份后，EOF 仍到不了
    #     git ⇒ cat-file 永远等请求行、父进程永远等输出 ⇒ 三方死锁。
    #     修复 = worker initializer 在启动时关闭继承到的源流管道 fd（对重建池同样生效）。
    _CLOSE_FDS = []        # Popen(cat-file) 后填入；worker 启动时关闭这些继承 fd
    def _worker_init():
        for fd in _CLOSE_FDS:
            try:
                os.close(fd)
            except OSError:
                pass
    inflight = {}          # AsyncResult -> [oid12, labels, size, tbytes, t0, budget, attempts, text]
    qbytes = [0]
    MAXQ_TASKS = 24
    MAXQ_BYTES = 201326592

    def _scan_task(payload):
        t, b = payload
        try:
            os.nice(4)
        except Exception:
            pass
        signal.alarm(max(2, b + 5))
        try:
            return scan_text(t)
        finally:
            signal.alarm(0)

    def _submit(text, size, labels, oid12, budget):
        res = pool[0].apply_async(_scan_task, ((text, budget),))
        inflight[res] = [oid12, labels, size, len(text), time.monotonic(),
                         budget, 1, text]
        qbytes[0] += len(text)

    def _expire_and_rebuild():
        now = time.monotonic()
        stale = [r for r, v in inflight.items()
                 if not r.ready() and now - v[4] > v[5]]
        if not stale:
            return False
        giveup = [inflight[r] for r in stale if inflight[r][6] >= 2]
        requeue = [v for r, v in inflight.items()
                   if not (r in stale and v[6] >= 2)]
        for v in giveup:
            reds.append(("RED-TIMEOUT", v[1][0], v[2],
                         "budget=%ds 重投一次仍超限 → 放弃并记红（覆盖不完整）" % v[5]))
        for r in list(inflight):
            qbytes[0] -= inflight[r][3]
            del inflight[r]
        try:
            pool[0].terminate()
        except Exception:
            pass
        for p in getattr(pool[0], "_pool", []) or []:
            try:
                p.kill()
            except Exception:
                pass
        try:
            pool[0].join()
        except Exception:
            pass
        pool[0] = ctx.Pool(W)
        for v in requeue:
            res = pool[0].apply_async(_scan_task, ((v[7], v[5]),))
            inflight[res] = [v[0], v[1], v[2], v[3], time.monotonic(),
                             v[5], v[6] + 1, v[7]]
            qbytes[0] += v[3]
        return True

    # 建池必须在全部 worker 函数定义之后（见上方 2026-11-04 教训①）
    pool = [ctx.Pool(W, initializer=_worker_init)]

    # 流式读对象（一次一个，全量 slurp 会把 af 级仓库的历史内容整段灌进内存——
    # 2026-11-04 首版实测 RSS 8.4G，威胁同机在役服务；此为修复版）。
    # 喂入走 daemon 线程：git 边吃 stdin 边写 stdout，若主线程先写后读，
    # stdout 管道一满 git 停止收 stdin，主线程的 write 会死锁。
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    _CLOSE_FDS[:] = [proc.stdin.fileno(), proc.stdout.fileno(),
                     proc.stderr.fileno()]   # 后续 fork 的 worker 启动即关，保 EOF 可达
    import threading
    def _feed():
        try:
            proc.stdin.write(("\n".join(want) + "\n").encode())
            proc.stdin.close()
        except Exception:
            pass
    threading.Thread(target=_feed, daemon=True).start()
    def _read_exact(n):
        b = proc.stdout.read(n)
        if len(b) != n:
            proc.kill()
            sys.stderr.write("ENV-FAIL cat-file 流截断\n")
            sys.exit(2)
        return b

    hits = []            # (label, ln, pid)；ln=0 表示二进制定点探针命中
    exempt_recs = []     # (label, ln, pid)；统一在收尾排序后输出（并行池下保幂等）
    reds = []            # (kind, label, size, detail)
    binlines = []
    stat = {"blobs": 0, "commitmsg": 0, "binary_skipped": 0, "binary_compressed": 0,
            "binary_probe_hits": 0, "text_bytes": 0, "binary_bytes": 0,
            "exempt": 0, "oversize": 0}
    t_start = time.monotonic()

    def exempt_hit(pid, label):
        base = os.path.basename(label)
        for e in exempt:
            if e["pattern"] == pid and e["file"] in (label, "*", base):
                return True
        return False

    def _drain():
        for r in [r for r in inflight if r.ready()]:
            v = inflight.pop(r)
            qbytes[0] -= v[3]
            try:
                recs = r.get()
            except Exception as e:
                reds.append(("RED-WORKER", v[1][0], v[2], "err=%s" % repr(e)[:160]))
                continue
            for pid, lnn in recs:
                for label in v[1]:
                    if exempt_hit(pid, label):
                        stat["exempt"] += 1
                        exempt_recs.append((label, lnn, pid))
                    else:
                        hits.append((label, lnn, pid))

    while True:
        hdr = proc.stdout.readline()
        if not hdr:
            break
        parts = hdr.decode("utf-8", "replace").split()
        if len(parts) < 3:
            continue  # "missing"/残行防御
        sha, typ, size = parts[0], parts[1], int(parts[2])
        body = _read_exact(size)
        proc.stdout.read(1)  # 跳过对象体后的分隔换行
        oid12 = sha[:12]
        if typ == "blob":
            labels = sorted(sha_paths.get(sha, {"<unreferenced-blob>"}))
            stat["blobs"] += 1
        else:  # commit / tag：扫提交（或标签）消息，标签位换成消息标记
            sep = body.find(b"\n\n")
            body = body[sep+2:] if sep >= 0 else body
            labels = [oid12 + "@commitmsg"]
            stat["commitmsg"] += 1
        # ── 二进制判定与跳过（①号修复；判据可解释：体含 NUL ⇒ 二进制）──
        if b"\x00" in body:
            head = body[:32]
            is_cmp = any(head.startswith(mg) for mg in COMPRESSED_MAGICS)
            stat["binary_skipped"] += 1
            stat["binary_bytes"] += size
            probe_found = []
            if is_cmp:
                stat["binary_compressed"] += 1
            else:
                for lit, pid in PROBES:
                    off = body.find(lit)
                    if off >= 0:
                        probe_found.append((off, lit, pid))
            for off, lit, pid in probe_found:
                stat["binary_probe_hits"] += 1
                label = "%s@byte%d" % (labels[0], off)
                if exempt_hit(pid, labels[0]):
                    stat["exempt"] += 1
                    exempt_recs.append((label, 0, pid))
                else:
                    hits.append((label, 0, pid))
            binlines.append("BIN-SKIP %s oid=%s size=%d kind=%s probe_hits=%d"
                            % (labels[0], oid12, size,
                               "compressed" if is_cmp else "binary",
                               len(probe_found)))
            continue
        # ── 体积护栏：超大对象不进扫描器，记红报出（不静默）──
        if size > MAXBLOB:
            stat["oversize"] += 1
            reds.append(("RED-OVERSIZE", labels[0], size,
                         "max=%dB 不进扫描器（覆盖不完整）" % MAXBLOB))
            continue
        text = body.decode("utf-8", "replace")
        stat["text_bytes"] += size
        _submit(text, size, labels, oid12, budget_for(size))
        while inflight and (len(inflight) >= MAXQ_TASKS or qbytes[0] >= MAXQ_BYTES):
            _drain()
            if not _expire_and_rebuild():
                time.sleep(0.02)
    while inflight:   # 收尾：排空在途（超限走同一护栏）
        _drain()
        _expire_and_rebuild()
        time.sleep(0.05)

    proc.wait()
    if proc.returncode != 0:
        sys.stderr.write("ENV-FAIL cat-file --batch rc=%s: %s\n" % (
            proc.returncode,
            proc.stderr.read().decode("utf-8", "replace")[:500]))
        sys.exit(2)
    hits = sorted(set(hits))
    for label, lnn, pid in hits:
        if lnn == 0:
            print("PROBE-HIT %s %s %s" % (label, pid, NAMES[pid]))
        else:
            print("HIT %s:%d %s %s" % (label, lnn, pid, NAMES[pid]))
    for label, lnn, pid in sorted(set(exempt_recs)):
        if lnn == 0:
            print("EXEMPT %s %s" % (label, pid))
        else:
            print("EXEMPT %s:%d %s" % (label, lnn, pid))
    for rkind, label, size, detail in sorted(reds):
        print("%s %s size=%d %s" % (rkind, label, size, detail))
    elapsed = time.monotonic() - t_start
    if binreg_path:
        with open(binreg_path, "w", encoding="utf-8") as f:
            f.write("# 二进制面逐件登记（非静默跳过台账；2026-11-04 下午修复批①号修复）\n"
                    "# kind=binary     → 不喂正则，已另走高信度前缀定点探针（probe_hits>0 即有命中）\n"
                    "# kind=compressed → 压缩容器，明文探针与模式扫描均不适用 = 如实登记的未覆盖面\n")
            for bl in binlines:
                f.write(bl + "\n")
    if stats_path:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(dict(stat, commits=n_commits, hits=len(hits), reds=len(reds),
                           workers=W, elapsed_sec=round(elapsed, 3),
                           budget_floor_sec=(int(BUDGET_ENV) if BUDGET_ENV.isdigit()
                                             else 30),
                           budget_env=BUDGET_ENV or "default", patterns=18),
                      f, ensure_ascii=False, indent=2)
    sys.stderr.write(
        "SCAN commits=%d blobs=%d commitmsg=%d binary_skipped=%d"
        "(compressed=%d probe_hits=%d oversize=%d) text_mb=%.1f binary_mb=%.1f "
        "hits=%d exempt=%d reds=%d patterns=18 workers=%d elapsed=%.1fs "
        "budget=%s scanallow=%s\n"
        % (n_commits, stat["blobs"], stat["commitmsg"], stat["binary_skipped"],
           stat["binary_compressed"], stat["binary_probe_hits"], stat["oversize"],
           stat["text_bytes"] / 1048576.0, stat["binary_bytes"] / 1048576.0,
           len(hits), stat["exempt"], len(reds), W, elapsed,
           BUDGET_ENV or "default", sal_state))
    sys.exit(1 if (hits or reds) else 0)

sys.stderr.write("ENV-FAIL 未知模式 %r\n" % MODE)
sys.exit(2)
PYEOF
}

# ---- 事件流水（--selftest 夹具自检）----------------------------------------
selftest() {
  log "SELFTEST 开始（夹具全用 PLACEHOLDER 假密钥，零真实凭据；/tmp 用完即删）"
  local T; T="$(mktemp -d "${TMPDIR:-/tmp}/mirror-selftest.XXXXXX")"
  CLEANUP_DIR="$T"   # 全局：EXIT trap 在函数返回后才走，局部变量已出栈（set -u）
  trap 'rm -rf "$CLEANUP_DIR"' EXIT
  local R="$T/r" RB="$T/run-base"
  git init -q -b main "$R"
  local GC="git -C $R -c user.name=fx -c user.email=fx@example.invalid"
  mkdir -p "$R/src" "$R/docs" "$R/poc/secrets" "$R/evil"
  printf 'fn main() {}\n'                                  > "$R/src/keep.rs"
  printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nPLACEHOLDERKEYBODY0000000000\n-----END OPENSSH PRIVATE KEY-----\n' > "$R/poc/secrets/old.key"
  printf 'bao-token: hvs.PLACEHOLDER0000000000\n'          > "$R/evil/token.txt"
  # —— 修复批新夹具：二进制 / 压缩 / 探针 / 大文本 / 病态无 NUL 随机串 ——
  printf '\x00asm\x01\x00\x00\x00PLACEHOLDERWASMJUNK\x00\x00tail' > "$R/src/libsample.so"
  printf 'PLACEHOLDER-inside-compressed' | gzip -q > "$R/docs/payload.gz"
  printf '\x01\x02\x00AKIAPLACEHOLDER0000AB\x00end' > "$R/src/fake-vendor.bin"
  { head -c 9437184 /dev/urandom | base64 | tr -d '\n' \
      | sed -E 's/token/t0ken/gI; s/secret/s3cr3t/gI; s/password/pwrd/gI; s/apikey/ap1k/gI; s/api_key/ap1ky/gI; s/credential/creD-T/gI; s/cred/cre-D/gI; s/passwd/psw-d/gI; s/pwd/pWd/gI; s/access_key/acc-K/gI; s/auth_key/aut-K/gI; s/auth_token/aut-T/gI; s/AKIA/AK1A/g; s/AIza/A1Za/g; s/Bearer/Bear2/g; s/eyJ/eJy/g'; } > "$R/src/big-soup.txt"
  head -c 1048576 /dev/urandom | tr -dc 'A-Za-z0-9' > "$R/src/rand-nonul.bin"
  $GC add -A && $GC commit -qm seed
  printf '# 夹具\napi_key = "sk-PLACEHOLDER1234567890"\n'  > "$R/src/creds.txt"
  printf '内部端点见 http://opchadmin:0123456789abcdef0123456789abcdef01234567@100.64.0.6:3300/opchadmin/af.git\n' > "$R/docs/public.md"
  $GC rm -q evil/token.txt && $GC add -A && $GC commit -qm cleanup
  printf 'src\ndocs\npoc/secrets\nevil\n'  > "$T/al.paths"
  printf '# 只排私钥夹具\npoc/secrets\n' > "$T/dl.paths"
  printf '[]'                        > "$T/sal.json"

  local FAIL=0
  chk() { # $1=说明 $2=期望(0/非0) 之后执行命令
    local desc="$1" want="$2"; shift 2
    local rc=0; "$@" >/dev/null 2>&1 || rc=$?
    if { [ "$want" = 0 ] && [ "$rc" = 0 ]; } || { [ "$want" != 0 ] && [ "$rc" != 0 ]; }; then
      ok "selftest: $desc (rc=$rc)"
    else
      printf '  ✗ selftest: %s (期望 rc=%s, 实得 rc=%s)\n' "$desc" "$want" "$rc" >&2
      FAIL=$((FAIL+1))
    fi
  }
  has() { # $1=说明 $2=被检文件 $3=期望有无(1/0) 其余=grep 参数
    local desc="$1" f="$2" want="$3"; shift 3
    if grep -q "$@" "$f" 2>/dev/null; then
      if [ "$want" = 1 ]; then ok "selftest: $desc"; else printf '  ✗ selftest: %s（不该出现却出现）\n' "$desc" >&2; FAIL=$((FAIL+1)); fi
    else
      if [ "$want" = 0 ]; then ok "selftest: $desc"; else printf '  ✗ selftest: %s（该出现却没出现）\n' "$desc" >&2; FAIL=$((FAIL+1)); fi
    fi
  }

  # ── ① 默认干跑：不产任何快照 ──
  chk "干跑（无 --emit）退出 0" 0 bash "$SELF" "$R" --allowlist "$T/al.paths" --denylist "$T/dl.paths" --scan-allowlist "$T/sal.json" --run-base "$RB"
  [ ! -d "$RB" ] && ok "selftest: 干跑未产生 RUNDIR" || { printf '  ✗ selftest: 干跑竟产生 RUNDIR\n' >&2; FAIL=$((FAIL+1)); }

  # ── ② 红路：假密钥被扫出（历史 blob：evil/token.txt 已在 HEAD 删除仍命中）
  #        + 二进制探针命中 + 二进制/压缩台账（修复批①号修复实证）──
  chk "红路（假密钥+探针命中）exit 1" 1 bash "$SELF" "$R" --emit --allowlist "$T/al.paths" --denylist "$T/dl.paths" --scan-allowlist "$T/sal.json" --run-base "$T/rb-red"
  local RDIR; RDIR="$(find "$T/rb-red" -maxdepth 1 -mindepth 1 -type d | head -1)"
  has "命中含 src/creds.txt:2 G-02（假 sk- 键，报路径+行+模式名）" "$RDIR/scan-report.txt" 1 -F "HIT src/creds.txt:2 G-02"
  has "命中含 evil/token.txt:1 P-02（已删文件的历史 blob，证明扫的是历史）" "$RDIR/scan-report.txt" 1 -F "HIT evil/token.txt:1 P-02"
  has "命中含 docs/public.md:1 P-01（URL 直嵌凭据）" "$RDIR/scan-report.txt" 1 -F "HIT docs/public.md:1 P-01"
  has "命中含 docs/public.md:1 P-04（内网 CGNAT 地址）" "$RDIR/scan-report.txt" 1 -F "HIT docs/public.md:1 P-04"
  has "二进制内嵌 AKIA 前缀被定点探针扫出（PROBE-HIT src/fake-vendor.bin G-04）" "$RDIR/scan-report.txt" 1 -F "PROBE-HIT src/fake-vendor.bin@byte"
  has "病态二进制被跳过且逐件登记（BIN-SKIP src/libsample.so kind=binary）" "$RDIR/scan-binary.txt" 1 -F "BIN-SKIP src/libsample.so"
  has "压缩容器如实登记为未覆盖面（kind=compressed）" "$RDIR/scan-binary.txt" 1 -F "kind=compressed"
  has "报告零值泄露（scan-report 全文无 PLACEHOLDER 字样）" "$RDIR/scan-report.txt" 0 -F "PLACEHOLDER"
  has "台账零值泄露（scan-binary 全文无 PLACEHOLDER 字样）" "$RDIR/scan-binary.txt" 0 -F "PLACEHOLDER"
  if [ -e "$RDIR/mirror-repo.git" ]; then printf '  ✗ selftest: 红路竟落了 mirror-repo.git\n' >&2; FAIL=$((FAIL+1)); else ok "selftest: 红路不落快照（无 mirror-repo.git）"; fi
  if ls "$RDIR"/*.bundle >/dev/null 2>&1; then printf '  ✗ selftest: 红路竟落了 bundle\n' >&2; FAIL=$((FAIL+1)); else ok "selftest: 红路不落快照（无 bundle）"; fi

  # ── ③ 护栏红：预算压到 1s，大文本对象超限 → RED-TIMEOUT；跑完不挂、续扫不受影响 ──
  local T0S T1S
  T0S="$(date +%s)"
  chk "护栏红（预算=1s 大文本超限）exit 1 且跑完" 1 env MIRROR_DISC_BUDGET_SECS=1 bash "$SELF" "$R" --emit --allowlist "$T/al.paths" --denylist "$T/dl.paths" --scan-allowlist "$T/sal.json" --run-base "$T/rb-red2"
  T1S="$(date +%s)"
  if [ $((T1S - T0S)) -le 60 ]; then ok "selftest: 护栏红总耗时 $((T1S - T0S))s ≤60s（工具未被输入挂死）"
  else printf '  ✗ selftest: 护栏红耗时 %ss > 60s\n' "$((T1S - T0S))" >&2; FAIL=$((FAIL+1)); fi
  local RDIR2; RDIR2="$(find "$T/rb-red2" -maxdepth 1 -mindepth 1 -type d | head -1)"
  has "超限对象记红（RED-TIMEOUT src/big-soup.txt）" "$RDIR2/scan-report.txt" 1 -F "RED-TIMEOUT src/big-soup.txt"
  has "护栏红不拦其他对象（假密钥仍被扫出）" "$RDIR2/scan-report.txt" 1 -F "HIT src/creds.txt:2 G-02"
  has "正常预算的病态随机串不误红（rand-nonul 无 RED-TIMEOUT）" "$RDIR2/scan-report.txt" 0 -F "RED-TIMEOUT src/rand-nonul.bin"

  # ── ④ 豁免后绿路：产出快照；allowlist 生效；denylist 优先级生效 ──
  cat > "$T/sal2.json" <<'JSON'
[
 {"pattern":"G-02","file":"src/creds.txt","reason":"selftest 假密钥夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"G-13","file":"src/creds.txt","reason":"selftest 假密钥夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"P-02","file":"evil/token.txt","reason":"selftest 假令牌夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"G-13","file":"evil/token.txt","reason":"selftest 假令牌夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"P-01","file":"docs/public.md","reason":"selftest 假 URL 夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"P-04","file":"docs/public.md","reason":"selftest 内网地址夹具","approved_by":"selftest","expires":"2099-12-31"},
 {"pattern":"G-04","file":"src/fake-vendor.bin","reason":"selftest 假探针夹具","approved_by":"selftest","expires":"2099-12-31"}
]
JSON
  local G0S G1S
  G0S="$(date +%s)"
  chk "豁免后绿路 exit 0 并产出" 0 bash "$SELF" "$R" --emit --allowlist "$T/al.paths" --denylist "$T/dl.paths" --scan-allowlist "$T/sal2.json" --run-base "$T/rb-green"
  G1S="$(date +%s)"
  if [ $((G1S - G0S)) -le 90 ]; then ok "selftest: 绿路（含 12MB 病态文本全模式扫）耗时 $((G1S - G0S))s ≤90s"
  else printf '  ✗ selftest: 绿路耗时 %ss > 90s（疑似病态回溯回潮）\n' "$((G1S - G0S))" >&2; FAIL=$((FAIL+1)); fi
  RDIR="$(find "$T/rb-green" -maxdepth 1 -mindepth 1 -type d | head -1)"
  [ -d "$RDIR/mirror-repo.git" ] && ok "selftest: 绿路落 mirror-repo.git" || { printf '  ✗ selftest: 绿路缺 mirror-repo.git\n' >&2; FAIL=$((FAIL+1)); }
  local FILES; FILES="$(git -C "$RDIR/mirror-repo.git" ls-tree -r --name-only HEAD)"
  echo "$FILES" | grep -qx 'src/keep.rs'    && ok "selftest: allowlist 生效（src/keep.rs 在）"   || { printf '  ✗ selftest: src/keep.rs 不在镜像\n' >&2; FAIL=$((FAIL+1)); }
  echo "$FILES" | grep -qx 'docs/public.md' && ok "selftest: allowlist 生效（docs/public.md 在）" || { printf '  ✗ selftest: docs/public.md 不在镜像\n' >&2; FAIL=$((FAIL+1)); }
  echo "$FILES" | grep -qx 'poc/secrets/old.key' && { printf '  ✗ selftest: denylist 优先级失灵（poc 进了镜像）\n' >&2; FAIL=$((FAIL+1)); } || ok "selftest: denylist 优先级生效（poc/secrets 虽在 allowlist 仍被排）"
  echo "$FILES" | grep -qx 'evil/token.txt' && { printf '  ✗ selftest: evil 路径不该在工作树\n' >&2; FAIL=$((FAIL+1)); } || ok "selftest: evil/ 不在 HEAD 工作树（源本就删了）"
  local PICKAXE; PICKAXE="$(git -C "$RDIR/mirror-repo.git" log --all -S'PRIVATE KEY' --oneline | wc -l)"
  [ "$PICKAXE" = 0 ] && ok "selftest: 被拒路径的对象历史中零残留（pickaxe）" || { printf '  ✗ selftest: poc 私钥历史残留 %s\n' "$PICKAXE" >&2; FAIL=$((FAIL+1)); }
  [ -f "$RDIR/scan-binary.txt" ] && ok "selftest: 绿路产物带二进制台账 scan-binary.txt" || { printf '  ✗ selftest: 绿路缺 scan-binary.txt\n' >&2; FAIL=$((FAIL+1)); }
  grep -q '"reds": 0' "$RDIR/manifest.json" && ok "selftest: 正常预算下零护栏红（manifest reds=0）" || { printf '  ✗ selftest: 绿路 manifest reds≠0\n' >&2; FAIL=$((FAIL+1)); }

  # ── ⑤ 幂等：重跑一次，逐字节一致 ──
  cp -a "$RDIR" "$T/run1"
  chk "幂等重跑 exit 0" 0 bash "$SELF" "$R" --emit --allowlist "$T/al.paths" --denylist "$T/dl.paths" --scan-allowlist "$T/sal2.json" --run-base "$T/rb-green"
  RDIR="$(find "$T/rb-green" -maxdepth 1 -mindepth 1 -type d | head -1)"
  if diff -r "$T/run1" "$RDIR" >/dev/null 2>&1; then ok "selftest: 两次产出逐字节一致（diff -r）"
  else printf '  ✗ selftest: 两次产出不一致\n' >&2; diff -r "$T/run1" "$RDIR" 2>&1 | head -5 >&2; FAIL=$((FAIL+1)); fi

  # ── ⑥ 配置错误响亮：allowlist 0 有效行 / denylist 缺失 ──
  printf '# 只有注释\n' > "$T/al-empty.paths"
  chk "allowlist 存在但 0 有效行 → exit 2" 2 bash "$SELF" "$R" --emit --allowlist "$T/al-empty.paths" --denylist "$T/dl.paths" --run-base "$RB"
  chk "denylist 缺失 → exit 2" 2 bash "$SELF" "$R" --emit --allowlist "$T/al.paths" --denylist "$T/nope.paths" --run-base "$RB"

  # ── ⑦ 脚本本体无推送/上传/网络传输词根（机检锚，见文头纪律；括号断字防自匹配）──
  local NOPUSH_RX='pu[s]h|upl[o]ad|cu[r]l|wg[e]t|sc[p]|rs[y]n[c]|s[s]h|\b[n]c\b'
  if grep -nwiE "$NOPUSH_RX" "$SELF" >/dev/null 2>&1; then
    printf '  ✗ selftest: 脚本本体出现推送/上传/网络传输词根\n' >&2
    grep -nwiE "$NOPUSH_RX" "$SELF" >&2; FAIL=$((FAIL+1))
  else ok "selftest: 脚本本体零推送/上传/网络传输词根（grep -nwiE 零命中）"; fi
  if grep -nE 'remote[[:space:]]+(ad[d]|set[-]url)' "$SELF" >/dev/null 2>&1; then
    printf '  ✗ selftest: 脚本本体出现远端挂接/改址操作词\n' >&2; FAIL=$((FAIL+1))
  else ok "selftest: 远端配置操作仅限 remove（零 add / set-url）"; fi

  # ── ⑧ G-13 改前/改后检出集合对拍（②号修复的「检出能力不减」实证）──
  log "SELFTEST ⑧ G-13 等价对拍开始"
  { printf '%s\n' \
      'password=hunter2secret' 'password = "hunter2secret"' '"password": "hunter2secret"' \
      'password: hunter2secret' 'my_token=abcdefgh123' 'db_password = supersecret123' \
      'client_secret: "cs_live_abcdefgh"' 'api_key=PLACEHOLDER123456' 'token="abcdef123456"' \
      'credentials=abcdefgh12' 'passwords: abcd12345678' 'credential: '"'"'abcdef123456'"'" \
      'token: null' 'password: 123456' 'password = 12.34, x' 'api_key=short' 'token="abc"'; } > "$T/g13-corpus.txt"
  { printf '%s\n' \
      'PASSWORD=hunter2secret' 'pwd: hunter2secret' 'passwd=hunter2secret' \
      'access_key=AKIAPLACEHOLDER00' 'auth_token=abcdef123456' 'creds=abcdefgh123'; } > "$T/g13-extra.txt"
  python3 -I - "$T/g13-corpus.txt" "$T/g13-extra.txt" > "$T/g13-old.txt" 2> "$T/g13-old.err" <<'OLDPY'
import re, sys
OLD = re.compile(r"['\"]?[A-Za-z0-9_-]*(?:password|secret|token|api_key|credential)s?['\"]?\s*[:=]\s*['\"]?(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,}")
def lines_of(path):
    with open(path, "rb") as f:
        t = f.read().decode("utf-8", "replace")
    return sorted({t.count("\n", 0, m.start()) + 1 for m in OLD.finditer(t)})
old_main = lines_of(sys.argv[1])
old_extra = lines_of(sys.argv[2])
sys.stderr.write("OLD main=%s extra=%s\n" % (old_main, old_extra))
for n in old_main: print("MAIN %d" % n)
for n in old_extra: print("EXTRA %d" % n)
OLDPY
  bash "$SELF" --g13 "$T/g13-corpus.txt" > "$T/g13-new-main.txt" 2>/dev/null
  bash "$SELF" --g13 "$T/g13-extra.txt" > "$T/g13-new-extra.txt" 2>/dev/null
  python3 -I - "$T/g13-old.txt" "$T/g13-new-main.txt" "$T/g13-new-extra.txt" > "$T/g13-verdict.txt" <<'CMPPY'
import sys
def readlines_set(path, tag):
    out = set()
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith(tag + " "):
            out.add(int(ln.split(":")[1]))
    return out
old_main = {int(x.split()[1]) for x in open(sys.argv[1], encoding="utf-8") if x.startswith("MAIN ")}
old_extra = {int(x.split()[1]) for x in open(sys.argv[1], encoding="utf-8") if x.startswith("EXTRA ")}
new_main = readlines_set(sys.argv[2], "G13HIT")
new_extra = readlines_set(sys.argv[3], "G13HIT")
NEG = {13, 14, 15, 16, 17}      # null / 纯数字 / 数字点 / 短值 —— 改前改后都该不命中
OLD_COVER = set(range(1, 13))   # 改前可检出的样本行
lost = old_main - new_main
verdicts = []
verdicts.append(("改前能检出的改后一处不少（old⊆new）", not lost, "lost=%s" % sorted(lost)))
verdicts.append(("负样本改前改后都不命中", not (old_main & NEG) and not (new_main & NEG),
                 "old&neg=%s new&neg=%s" % (sorted(old_main & NEG), sorted(new_main & NEG))))
gain = new_extra - old_extra
# 注：extra 第 5 行 auth_token= 改前式也能命中（无界前缀 auth_+token），
# 故它不算「新增」；真正的新增 = pwd/passwd/大小写/access_key/creds（1,2,3,4,6）。
verdicts.append(("新式检出只增（新增=pwd/passwd/大小写/access_key/creds；auth_token 两式皆中）",
                 gain == {1, 2, 3, 4, 6}, "gain=%s old_extra=%s" % (sorted(gain), sorted(old_extra))))
for name, okk, detail in verdicts:
    print("%s %s %s" % ("PASS" if okk else "FAIL", name, detail))
sys.exit(0)   # 裁决由 bash 侧 wc/grep 读 verdict 文本判定；避免 set -e 在 FAIL 时无声死
CMPPY
  if [ "$(wc -l < "$T/g13-verdict.txt")" = 3 ] && ! grep -q FAIL "$T/g13-verdict.txt"; then
    ok "selftest: G-13 等价对拍 3/3（old⊆new / 负样本双不命中 / 新增=键名表扩充）"
    sed 's/^/    /' "$T/g13-verdict.txt" >&2
  else
    printf '  ✗ selftest: G-13 等价对拍失败\n' >&2
    cat "$T/g13-verdict.txt" >&2; FAIL=$((FAIL+1))
  fi

  # ── ⑨ 病态样本护栏：改前式在「长词字符串」上爆炸（外层 timeout 掐死为证），
  #      改后式同一样本秒级完成 —— ②号修复的机理对照 ──
  log "SELFTEST ⑨ 病态样本对照开始"
  head -c 4194304 /dev/urandom | tr -dc 'A-Za-z0-9' > "$T/patho.txt"
  local ORC=0
  timeout 20 python3 -I - "$T/patho.txt" > /dev/null 2>&1 <<'OLDP' || ORC=$?
import re, sys
OLD = re.compile(r"['\"]?[A-Za-z0-9_-]*(?:password|secret|token|api_key|credential)s?['\"]?\s*[:=]\s*['\"]?(?!null\b|<none>)(?![\d.]+(?:[,}\]\s]|$))[^\s\"',;}]{6,}")
t = open(sys.argv[1], "rb").read().decode("utf-8", "replace")
n = sum(1 for _ in OLD.finditer(t))
sys.stderr.write("OLD completed hits=%d\n" % n)
OLDP
  if [ "$ORC" = 124 ] || [ "$ORC" = 9 ] || [ "$ORC" = 137 ]; then
    ok "selftest: 改前 G-13 在 1MB 长词字符串上 20s 仍不完成（rc=$ORC 被外层掐死=爆炸实证）"
  else
    printf '  ✗ selftest: 改前 G-13 病态样本意外完成（rc=%s，爆炸机理未复现，对照失效）\n' "$ORC" >&2
    FAIL=$((FAIL+1))
  fi
  local P0 P1
  P0="$(date +%s)"
  chk "改后 G-13 同一病态样本秒级完成（--g13 rc=0）" 0 bash "$SELF" --g13 "$T/patho.txt"
  P1="$(date +%s)"
  if [ $((P1 - P0)) -le 15 ]; then ok "selftest: 改后病态样本耗时 $((P1 - P0))s ≤15s"
  else printf '  ✗ selftest: 改后病态样本耗时 %ss > 15s\n' "$((P1 - P0))" >&2; FAIL=$((FAIL+1)); fi

  if [ "$FAIL" = 0 ]; then
    log "SELFTEST PASS（$VERSION）：干跑不产/红路命中+探针+台账零值泄露/护栏红跑完不挂/豁免绿路产出/allowlist+denylist 优先级/历史 blob 命中/幂等逐字节一致/配置错响亮/无推送词根/G-13 等价 3/3/病态样本改前爆炸改后秒级"
    return 0
  fi
  log "SELFTEST FAIL：$FAIL 项"
  return 1
}

# ---- 事件流水（主产线）------------------------------------------------------
main_emit() { # $1=源仓；其余选项已解析为全局
  local SRC="$1"
  need_cmd git; need_cmd python3; need_cmd sha256sum; need_cmd timeout
  git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1 || die2 "源仓不是 git 仓: $SRC"
  git filter-repo --version >/dev/null 2>&1 \
    || die2 "git-filter-repo 不在位——如实登记：等效实现未实装，禁临时装系统包（本机实测在位：/home/pan-ding/.local/bin/git-filter-repo，登记见 30-工件/镜像披露-20261104/mirror-disclose-report.md）"

  # 清单定形（absolutize：filter-repo 子进程的 cwd 是镜像仓，相对路径会在那里解析而失败）
  local DENYLIST="${DENYLIST_OPT:-$DENYLIST_DEF}"
  local ALLOWLIST="${ALLOWLIST_OPT:-$ALLOWLIST_DEF}"
  local SCANAL="${SCANAL_OPT:-$SCANAL_DEF}"
  [ -e "$DENYLIST" ] && DENYLIST="$(realpath -m "$DENYLIST")"
  [ -e "$ALLOWLIST" ] && ALLOWLIST="$(realpath -m "$ALLOWLIST")"
  [ -e "$SCANAL" ] && SCANAL="$(realpath -m "$SCANAL")"
  [ -f "$DENYLIST" ] || die2 "denylist 缺失（$DENYLIST）——一律禁止清单是安全底线，缺了不跑"
  [ "$(list_valid "$DENYLIST")" -gt 0 ] || die2 "denylist 有效行=0（$DENYLIST）——空黑名单是歧义配置"
  list_has_rename "$DENYLIST" && die2 "denylist 含 '==>' 重命名语法，本闸只许纯允许/拒绝"
  local AL_ENABLED=0
  if [ -f "$ALLOWLIST" ]; then
    list_has_rename "$ALLOWLIST" && die2 "allowlist 含 '==>' 重命名语法，本闸只许纯允许/拒绝"
    if [ "$(list_valid "$ALLOWLIST")" -gt 0 ]; then AL_ENABLED=1
    else die2 "allowlist 存在但有效行=0（$ALLOWLIST）——歧义配置：想禁用请改名加 .off 后缀或删除本文件"
    fi
  else
    log "WARN 白名单未启用（无 $ALLOWLIST）——全仓按 denylist 裁剪"
  fi

  # 源仓指纹（只读）
  local SRC_NAME SRC_HEAD SRC_REFS SRC_COMMITS AL12 DL12 SAL12 IDENT RUNDIR
  SRC_NAME="$(basename "$SRC" | tr -d '"\\')"
  SRC_HEAD="$(git -C "$SRC" rev-parse --verify HEAD 2>/dev/null)" \
    || die2 "源仓无提交（HEAD 不可解析）: $SRC"
  SRC_REFS="$(git -C "$SRC" for-each-ref --format='%(refname) %(objectname)')"
  SRC_COMMITS="$(git -C "$SRC" rev-list --all --count)"
  DL12="$(f12 "$DENYLIST")"
  AL12="noallow"; [ "$AL_ENABLED" = 1 ] && AL12="$(f12 "$ALLOWLIST")"
  SAL12="none";   [ -f "$SCANAL" ] && SAL12="$(f12 "$SCANAL")"
  IDENT="$SRC_NAME-src$(printf %s "$SRC_HEAD" | cut -c1-12)-refs$(printf %s "$SRC_REFS" | sha256sum | cut -c1-12)-al$AL12-dl$DL12-sal$SAL12"

  local RUN_BASE="${RUN_BASE_OPT:-${MIRROR_RUN_BASE:-${HOME:-}/mirror-disclose-runs}}"
  [ -n "$RUN_BASE" ] || die2 "RUN 根目录为空（HOME 未设且未给 --run-base）"
  if [ -n "${RUNDIR_OPT:-}" ]; then RUNDIR="$RUNDIR_OPT"; else RUNDIR="$RUN_BASE/$IDENT"; fi
  RUNDIR="$(realpath -m "$RUNDIR")"
  local SRC_ABS; SRC_ABS="$(realpath -m "$SRC")"
  case "$RUNDIR/" in "$SRC_ABS"/*) die2 "RUNDIR 不得在源仓内";; esac
  case "$SRC_ABS/" in "$RUNDIR"/*) die2 "源仓不得在 RUNDIR 内（防 rm -rf 误伤）";; esac

  # ── 干跑（默认）：打印计划，零写入 ──
  if [ "${EMIT:-0}" != 1 ] && [ "${SCANONLY:-0}" != 1 ]; then
    log "DRY-RUN（缺省干跑，不产任何快照；真产出请显式加 --emit，只扫描不产快照用 --scan-only）"
    echo "  源仓           : $SRC_ABS"
    echo "  源 HEAD        : $SRC_HEAD"
    echo "  分支/标签引用数: $(printf '%s\n' "$SRC_REFS" | wc -l)"
    echo "  白名单         : $([ "$AL_ENABLED" = 1 ] && echo "启用（$ALLOWLIST，$(list_valid "$ALLOWLIST") 条）" || echo '未启用（文件不存在）')"
    echo "  黑名单         : $DENYLIST（$(list_valid "$DENYLIST") 条，优先级高于白名单）"
    echo "  终扫豁免       : $([ -f "$SCANAL" ] && echo "$SCANAL（$(python3 -I -c 'import json,sys;print(len(json.load(open(sys.argv[1]))))' "$SCANAL" 2>/dev/null || echo '?') 条）" || echo '无（fail-closed：零豁免）')"
    echo "  终扫模式       : 13 通用 + 5 项目自有 = 18 条（--patterns 看全表）"
    echo "  终扫护栏       : 二进制（体含 NUL）不喂正则+定点探针+台账；单对象预算 max(30s,30s/MB)≤600s；>256MB 记红"
    echo "  产出目录(将)   : $RUNDIR"
    echo "  产出物(将)     : mirror-repo.git/ + ${SRC_NAME}-disclose.bundle + scan-report.txt + scan-binary.txt + manifest.json + DISCLOSE-NOTE.md + config/"
    echo "  纪律           : 上传披露由运营者人工执行，本脚本无任何上传动作"
    return 0
  fi

  # ── 磁盘预检：历史重写要同时放得下「bundle + 克隆 + 重写后」三份全量 pack ──
  local TMPROOT GITDIR NEED AVAIL
  TMPROOT="${TMPDIR:-/tmp}"
  [ -d "$TMPROOT" ] || die2 "TMPDIR（$TMPROOT）不存在——历史重写的临时目录要先建好或换盘"
  GITDIR="$(git -C "$SRC" rev-parse --absolute-git-dir 2>/dev/null || echo "$SRC_ABS/.git")"
  NEED="$(du -sb "$GITDIR" 2>/dev/null | cut -f1 || echo 0)"
  NEED=$(( NEED * 5 / 2 + 209715200 ))
  AVAIL="$(df -B1 "$TMPROOT" 2>/dev/null | awk 'NR==2{print $4}' || echo 0)"
  if [ "${AVAIL:-0}" -lt "$NEED" ]; then
    die2 "磁盘预检不过：$TMPROOT 可用 ${AVAIL:-0} 字节 < 预期需求 $NEED 字节（源 .git 的 2.5 倍 + 200MB 余量）。历史重写要同时放 bundle+克隆+重写后三份 pack——请把 TMPDIR 指到大盘再跑（本机实测 $HOME 所在盘余 131G）。失败要响亮：不闷头跑到半途 ENOSPC。"
  fi
  ok "磁盘预检过：$TMPROOT 可用 $AVAIL 字节 ≥ 预期 $NEED 字节"

  # ── 真产出 ──
  local TMP; TMP="$(mktemp -d "${TMPDIR:-/tmp}/mirror-disclose.XXXXXX")"
  CLEANUP_DIR="$TMP"  # 全局：EXIT trap 在 main_emit 返回后才走，局部变量已出栈
  trap 'rm -rf "$CLEANUP_DIR"' EXIT
  local MIRROR="$TMP/mirror-repo.git"
  log "① 从源仓只读产 bundle（源仓零改动）"
  git -C "$SRC" bundle create "$TMP/in.bundle" --branches --tags HEAD >/dev/null \
    || die "源仓 bundle 产制失败"
  log "② 从 bundle 克隆出独立镜像仓（与源仓零对象共享）"
  git clone --mirror --quiet "$TMP/in.bundle" "$MIRROR" || die "镜像克隆失败"
  git -C "$MIRROR" remote remove origin 2>/dev/null || true
  log "③ filter-repo 历史裁剪"
  if [ "$AL_ENABLED" = 1 ]; then
    git -C "$MIRROR" filter-repo --force --quiet --paths-from-file "$ALLOWLIST" >/dev/null \
      || die "白名单裁剪失败（filter-repo 非零）"
    [ "$(git -C "$MIRROR" rev-list --all --count)" -gt 0 ] || die "白名单把历史裁空了——检查 $ALLOWLIST"
    ok "白名单裁剪后提交数: $(git -C "$MIRROR" rev-list --all --count)"
  fi
  git -C "$MIRROR" filter-repo --force --quiet --invert-paths --paths-from-file "$DENYLIST" >/dev/null \
    || die "黑名单裁剪失败（filter-repo 非零）"
  [ "$(git -C "$MIRROR" rev-list --all --count)" -gt 0 ] || die "黑名单把历史裁空了——检查 $DENYLIST"
  rm -rf "$MIRROR/filter-repo" 2>/dev/null || true
  git -C "$MIRROR" reflog expire --expire=now --all >/dev/null 2>&1 || true
  git -C "$MIRROR" gc --prune=now --quiet >/dev/null 2>&1 || true
  ok "黑名单裁剪后提交数: $(git -C "$MIRROR" rev-list --all --count)；filter-repo 元数据与 reflog 已清"

  log "④ 结构校验（deny 零残留 / allow 全覆盖，与 filter-repo 同口径）"
  local VERIFY_RC=0
  MD_MODE=verify MD_REPO="$MIRROR" MD_DENYLIST="$DENYLIST" \
    MD_ALLOWLIST="$([ "$AL_ENABLED" = 1 ] && echo "$ALLOWLIST" || echo "")" \
    run_py verify > "$TMP/verify.txt" 2> "$TMP/verify.summary" || VERIFY_RC=$?
  cat "$TMP/verify.summary" >&2
  [ "$VERIFY_RC" = 0 ] || { cat "$TMP/verify.txt" >&2; die "结构校验红：黑名单路径仍有残留或白名单外路径混入（明细见上行）"; }
  ok "结构校验绿"

  log "⑤ 密钥终扫（重写后全部历史：blob + 提交/标签消息；二进制面台账+定点探针；单对象护栏）"
  local SCAN_RC=0
  MD_MODE=scan MD_REPO="$MIRROR" \
    MD_SCANAL="$([ -f "$SCANAL" ] && echo "$SCANAL" || echo "")" \
    MD_BINREG="$TMP/scan-binary.txt" MD_STATS="$TMP/scan-stats.json" \
    run_py scan > "$TMP/scan.txt" 2> "$TMP/scan.summary" || SCAN_RC=$?
  cat "$TMP/scan.summary" >&2
  [ -f "$TMP/scan-binary.txt" ] || { cat "$TMP/scan.txt" >&2; die2 "终扫异常：scan-binary 台账缺失（ENV-FAIL 见上）"; }

  # 落扫描证据的公共步骤（红路 / scan-only 都走这里）
  local RUNNEW="$RUNDIR.new"
  rm -rf "$RUNNEW"; mkdir -p "$RUNNEW/config"
  cp -f "$DENYLIST" "$RUNNEW/config/mirror-denylist.paths"
  [ "$AL_ENABLED" = 1 ] && cp -f "$ALLOWLIST" "$RUNNEW/config/mirror-allowlist.paths"
  [ -f "$SCANAL" ] && cp -f "$SCANAL" "$RUNNEW/config/mirror-scan-allowlist.json"
  { echo "# mirror-disclose 终扫报告（只报 路径:行 模式名 与护栏红；零原文零值）"
    echo "# 台账：scan-binary.txt（二进制面逐件登记）；计数与裁决：manifest.json"
    cat "$TMP/scan.txt"; } > "$RUNNEW/scan-report.txt"
  cp -f "$TMP/scan-binary.txt" "$RUNNEW/scan-binary.txt"

  if [ "$SCAN_RC" = 1 ]; then
    local WHY="命中未豁免项"; grep -q '^RED-' "$RUNNEW/scan-report.txt" && WHY="命中/护栏红（覆盖不完整项见 RED 行）"
    log "终扫红：$WHY → 只落扫描证据与 manifest(verdict=blocked)，不产快照"
    emit_manifest blocked "$RUNNEW" "$SRC_NAME" "$SRC_HEAD" "$SRC_COMMITS" "$AL_ENABLED" "$ALLOWLIST" "$DENYLIST" "$SCANAL" "$MIRROR" "" "$AL12" "$DL12" "$SAL12" "$TMP/scan-stats.json"
    rm -rf "$RUNDIR"; mv "$RUNNEW" "$RUNDIR"
    log "红路证据已落 $RUNDIR（scan-report.txt / scan-binary.txt / manifest.json）——处置：真凭据用 denylist 移除；确认误报才进 scan-allowlist 豁免；护栏红=覆盖不完整，披露前必须人工复核"
    exit 1
  fi
  [ "$SCAN_RC" = 0 ] || die2 "终扫环境错误（rc=$SCAN_RC，见上方 ENV-FAIL）"
  ok "终扫绿（0 未豁免命中，0 护栏红）"

  if [ "${SCANONLY:-0}" = 1 ]; then
    log "⑥ scan-only：按题意只落扫描证据，不产快照"
    emit_manifest ok "$RUNNEW" "$SRC_NAME" "$SRC_HEAD" "$SRC_COMMITS" "$AL_ENABLED" "$ALLOWLIST" "$DENYLIST" "$SCANAL" "$MIRROR" "" "$AL12" "$DL12" "$SAL12" "$TMP/scan-stats.json"
    rm -rf "$RUNDIR" && mv "$RUNNEW" "$RUNDIR"
    ok "扫描证据落盘: $RUNDIR（scan-report.txt / scan-binary.txt / manifest.json / config/）"
    return 0
  fi

  log "⑥ 落本地快照（上传披露由人执行）"
  mv "$MIRROR" "$RUNNEW/mirror-repo.git"
  git -C "$RUNNEW/mirror-repo.git" bundle create "$RUNNEW/$SRC_NAME-disclose.bundle" --branches --tags HEAD >/dev/null \
    || die "快照 bundle 产制失败"
  { echo "# mirror-disclose 终扫报告（verdict=ok）"; echo "# 只报 路径:行 模式名；零原文零值"; cat "$TMP/scan.txt"; } > "$RUNNEW/scan-report.txt"
  emit_manifest ok "$RUNNEW" "$SRC_NAME" "$SRC_HEAD" "$SRC_COMMITS" "$AL_ENABLED" "$ALLOWLIST" "$DENYLIST" "$SCANAL" "$RUNNEW/mirror-repo.git" "$RUNNEW/$SRC_NAME-disclose.bundle" "$AL12" "$DL12" "$SAL12" "$TMP/scan-stats.json"
  emit_note "$RUNNEW" "$SRC_NAME" "$SRC_HEAD" "$AL_ENABLED" "$ALLOWLIST" "$DENYLIST" "$SCANAL" "$TMP"

  rm -rf "$RUNDIR" && mv "$RUNNEW" "$RUNDIR"
  ok "快照落盘: $RUNDIR"
  ok "人工后续：复核 scan-report/manifest → 按你自己的常规通道把 mirror-repo.git（或 bundle）发布到目标平台 → 披露后回源只认 gitea（镜像非备份，哈希已断裂不可回拉）"
}

# ---- manifest（无时间戳；同输入同内容 ⇒ 幂等）-------------------------------
emit_manifest() { # $1=verdict $2=outdir $3=srcname $4=src_head $5=src_commits $6=al_enabled $7=al $8=dl $9=sal ${10}=mirror ${11}=bundle ${12}=al12 ${13}=dl12 ${14}=sal12 ${15}=stats_json
  local verdict="$1" out="$2" name="$3" head="$4" src_commits="$5" alen="$6" al="$7" dl="$8" sal="$9" mirror="${10}" bundle="${11}" al12="${12}" dl12="${13}" sal12="${14}" statsf="${15}"
  local MH="" BH=""
  [ -n "$mirror" ] && MH="$(git -C "$mirror" rev-parse --verify HEAD)"
  [ -n "$bundle" ] && [ -f "$bundle" ] && BH="$(f12 "$bundle")"
  local M_COMMITS M_BLOBS
  M_COMMITS="$(git -C "$mirror" rev-list --all --count 2>/dev/null || echo 0)"
  M_BLOBS="$(git -C "$mirror" rev-list --all --objects 2>/dev/null | wc -l)"
  python3 -I - "$out/manifest.json" "$statsf" <<PYMAN
import json, sys
try:
    st = json.load(open(sys.argv[2], encoding="utf-8"))
except Exception:
    st = {}
scan = {"patterns": 18, "note": "13 通用 + 5 项目自有；只报 路径:行 模式名，零值"}
for k in ("commits", "blobs", "commitmsg", "binary_skipped", "binary_compressed",
          "binary_probe_hits", "text_bytes", "binary_bytes", "hits", "exempt",
          "reds", "oversize", "workers", "budget_floor_sec", "budget_env"):
    if k in st:
        scan[k] = st[k]
m = {
  "generator": "tools/mirror-disclose.sh",
  "version": "$VERSION",
  "verdict": "$verdict",
  "source": {"name": "$name", "head_sha12": "${head:0:12}", "commits": $src_commits},
  "lists": {
    "allowlist": {"enabled": $([ "$alen" = 1 ] && echo True || echo False), "sha12": "$al12", "file": "$(basename "$al")"},
    "denylist":  {"enabled": True, "sha12": "$dl12", "file": "$(basename "$dl")"},
    "scan_allowlist": {"sha12": "$sal12", "file": "$(basename "$sal")"}
  },
  "mirror": {"head_sha12": "${MH:0:12}", "commits": $M_COMMITS, "objects": $M_BLOBS,
             "bundle_sha12": "$BH"},
  "scan": scan,
  "discipline": "快照仅本地；披露由运营者人工执行；回源唯一 = gitea"
}
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
PYMAN
}

# ---- DISCLOSE-NOTE（给披露执行人的一页纸；刻意不含上传命令名）---------------
emit_note() { # $1=outdir $2=srcname $3=src_head $4=al_enabled $5=al $6=dl $7=sal $8=TMP
  cat > "$1/DISCLOSE-NOTE.md" <<NOTE
# 披露快照交接单（$2）

- 生成器：tools/mirror-disclose.sh（$VERSION）；历史重写：git filter-repo
- 源仓 HEAD：$3（重写前指纹；重写后哈希已全部断裂，见下）
- 白名单：$([ "$4" = 1 ] && echo "启用（$(basename "$5")）" || echo "未启用")
- 黑名单：$(basename "$6")；终扫豁免：$(basename "$7")

## 本快照是什么
$2 仓经路径裁剪与 13+5 密钥终扫（0 未豁免命中、0 护栏红）后的**披露专用**历史快照，
含全部分支与标签。形态：mirror-repo.git/（裸仓）与 $2-disclose.bundle（同一历史的打包）。

## ⚠ 镜像不是备份（这是裁决，不是提醒）
filter-repo 重写历史 ⇒ 全部提交哈希断裂 ⇒ 本快照与任何既有远端的共同历史已被切断。
**严禁把目标平台当备份、严禁事后从目标平台回拉**——回拉得到的是断裂哈希链，
与真源对不上账。**回源唯一 = gitea（http://gov-host.invalid:3300/opchadmin/af.git）**。

## 终扫覆盖面与护栏（2026-11-04 下午修复批）
- 文本面：18 模式全量扫（G-13 已线性化重写，见 manifest.json 的 scan 段计数）。
- 二进制面（对象体含 NUL 字节 ⇒ 判二进制，不喂正则）：
  - kind=binary：另走「高信度前缀定点探针」（厂商前缀/私钥块头的字节字面量查找，
    零正则零回溯），探针命中计红；逐件台账见 scan-binary.txt；
  - kind=compressed（gzip/zip/xz/zstd/7z/bzip2/lz4 魔数）：明文探针与模式扫描均
    不适用，**如实登记为未覆盖面**（台账逐件列出、manifest 带计数），不装作扫过。
- 单对象护栏：每对象扫描有独立时间预算（缺省 30s 起步、30s/MB、上限 600s）；
  超预算重投一次仍超 ⇒ RED-TIMEOUT 记红、整跑非零退出——工具不得被输入挂死；
  >256MB 对象不进扫描器 ⇒ RED-OVERSIZE 记红。红 = 覆盖不完整，披露前必须人工复核。

## 披露执行人要做的事（本脚本不代劳）
1. 人工复核本目录：scan-report.txt（终扫读数）、scan-binary.txt（二进制面台账）、
   manifest.json（指纹与计数）、config/（生效清单）。
2. 用你自己的常规通道与账号，把 mirror-repo.git 或 bundle 的内容发布到披露目标。
   具体用哪条通道、哪个账号，是运营者的决定，不在本脚本职责内。
3. 披露后的一切同步/回源，只以 gitea 为准；目标平台侧只出不进。

## 豁免 ≠ 打码
scan-allowlist 里被豁免的命中**仍会随本快照披露**。豁免只许用于确认过的误报；
若命中是真凭据，正确动作是 denylist 移除路径后重新出快照。
NOTE
}

# ---- 参数解析 ---------------------------------------------------------------
SRC="" EMIT=0 SCANONLY=0 RUNDIR_OPT="" RUN_BASE_OPT="" ALLOWLIST_OPT="" DENYLIST_OPT="" SCANAL_OPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --emit) EMIT=1;;
    --scan-only) SCANONLY=1;;
    --allowlist) ALLOWLIST_OPT="${2:-}"; shift;;
    --denylist) DENYLIST_OPT="${2:-}"; shift;;
    --scan-allowlist) SCANAL_OPT="${2:-}"; shift;;
    --rundir) RUNDIR_OPT="${2:-}"; shift;;
    --run-base) RUN_BASE_OPT="${2:-}"; shift;;
    --patterns) run_py patterns; exit 0;;
    --selftest) selftest; exit $?;;
    --g13) [ -n "${2:-}" ] || die2 "--g13 需要文件参数"; MD_FILE="$(readlink -f "$2")" run_py g13file; exit $?;;
    -h|--help) usage; exit 0;;
    --*) die2 "未知选项: $1";;
    *) if [ -z "$SRC" ]; then SRC="$1"; else die2 "多余参数: $1"; fi;;
  esac
  shift
done
[ "$EMIT" = 1 ] && [ "$SCANONLY" = 1 ] && die2 "--emit 与 --scan-only 互斥"
[ -n "$SRC" ] || { usage; echo; die2 "缺源仓路径（或用 --selftest / --patterns / --g13）"; }
[ -d "$SRC" ] || die2 "源仓目录不存在: $SRC"

main_emit "$SRC"
