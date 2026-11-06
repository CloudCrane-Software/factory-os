#!/usr/bin/env python3
"""rate-limit-symmetry-probe.py — af-jobs 公网入口安全巡检（限速对称 + 穿越无泄露）

背景（红队确证发现，2026-11-02，修复员-54）：逃逸台账 RT-E46②「巡检门：对每个
公网入口并发探针断言 429 出现（限速在役证明）」此前零施工——grep '429|rate_limit'
tools/all-gates.sh=0。RT-E46 的病根是「限速按入口块配置」：jobs. 块 120/min 在役，
ai.hkmingdajiaoyu.com/af-jobs/* 经 Higress 的镜像入口一度零限速——同一后端
（af-jobs:8090）的无限速镜像入口使 jobs. 侧限速形同虚设。行为面巡检（打 /healthz
断言 429）不依赖反代拓扑（Caddy/Higress 配置各自不可见/会漂移），是唯一与
「对称性」本体对齐的机检面。

判定（每入口两腿，全部入口两腿过才 exit 0；任一不过=红，不静默 SKIP）：
  A 穿越无泄露腿：--path-as-is 等价原样路径（http.client 不做客户端归一化）打
    12 个穿越变体（/task/ 与 /static/ 路由 × ../ 深浅/%2e%2e/..%2f/%2e%2e%2f）——
    契约口径按登记册条目 contract_mode 分三种（公网五入口口径统一，判据源=
    tools/public_entry_registry.py）：
      content（门户面 jobs./factory./ai./af-jobs + zhihui. 演示站）：任何 200 响应体
        必须逐字节等于本入口公开契约参照件（门户={base}/AGENTS.md；zhihui.=
        {base}/health）——2026-11-02 窗实测：jobs./factory. 全 404；ai. 经 Higress
        归一化后 200=公开契约件，非泄露）；契约参照件取不到（非 200）=不可证=
        fail-closed（红）。读出公开契约之外的任何内容即红（RT-E47 部署侧腿）。
      auth（otlp. 公网 OTLP 摄入口：静态 bearer 认证，无公开内容面）：未认证基线
        {base}/ 必须 401/403（fail-closed 认证在役；非 401/403 = 认证失效/未认证
        公开暴露 = 红）；穿越变体出现 200 = 未认证面读出内容 = 泄露 = 红。
      none（--entry 临时指定、且不在登记册的入口）：穿越变体不得出现 200。
    非 200（404/429/401/403，按契约口径白名单）一律可。
  B 限速对称腿：并发探针 131×GET {probe_path}（8 路并发，恰超 120/min 帽）——
    每入口必须出现 ≥1×429（限速在役证明）。零 429 = 该入口无限速/限速失效，
    与其他入口不对称（RT-E46 复发形态）。
  C 服务本体限速腿（2026-11-03 安全面批新增）：**直连服务本体**打压 131×GET
    /healthz（经 ssh 端口转发从 gov 回环发起，源＝127.0.0.1，与 tailnet 消费方
    的限速桶隔离）→ 必须出现 ≥1×429。**为什么加这条腿**：本门此前只测反代入口，
    结构上测不出「限速是否护住了服务」——门户本体在 tailnet/caddy docker 网段可
    直连（写路由 /claim /report 在役）且零限速 ⇒ 前门 120/min 帽可被绕过
    （RT-E166「4MB 体帽 × 无速率」余留面）。本体自带闸（门户 _RateLimiter，
    客户键滑动窗口 120/min）落地后，本腿把该性质变成**常驻机检**：本体闸被摘/
    帽被放大 → 本腿红。隧道/本体不可达 → fail-closed（不可证不猜绿）。
  fail-closed：入口 {probe_path} 或契约参照件不可达（含 5xx/超时/TLS 错）
    → exit 2——「在役面失去可对账性本身就是异常」（与 L5 部署一致性门同口径），
    不可证不猜绿。

口径与纪律（打生产面 self-limit）：
  · 只打 GET {probe_path} 与穿越变体，零写端点；每入口每轮 ≤145 请求、总 ≤725
    （五入口 × 144=契约参照 1 + 穿越变体 12 + 限速打压 131），限速帽内自伤面=
    约 11×429/入口/轮；all-gates 每轮一次的频率下可接受（同量级为 RT-E46/E47
    红队确证时已用过的 140×3 打压）。
  · 入口清单=登记册正本 tools/public_entry_registry.py（配置面↔运行时面共用唯一
    副本；RT-E46③「新增反代入口必填 rate_limit 字段」的机检替身——未登记的入口
    本探针测不到，登记遗漏=巡检盲区）。修复前本探针内嵌 3 条手抄清单（且与配置面
    五限速 zone 无对账），otlp./zhihui. 两个**已限速**公网口运行时行为零覆盖；
    现登记册五条，「配置面新增公网限速口未登记」由 tools/public-entry-registry-
    check.py 对账门判红（缺登记=巡检盲区=红）。
  · 本探针只测反代/入口行为面 + **C 腿的服务本体限速面**（本体自带闸在役证明）；
    门户本体三面（穿越/token 一次性/竞态）与本体限速闸的本地隔离回归见
    tools/test-portal-attack-surface.py（本地隔离实例，L2 常驻）；在役=本地的
    版本一致性由 L5 部署一致性门（deploy-consistency-probe.sh，md5+进程钉桩）兜底。
  · C 腿请求量：每轮 131 次 GET /healthz（打 gov 回环，经 ssh 转发；零写端点），
    与 B 腿同量级；源身份与 tailnet 消费方隔离（不得连带 429 掉在役巡检）。

用法：python3 -I tools/rate-limit-symmetry-probe.py [--selftest] [--entry URL]...
退出码：0 全绿；1 红（零 429 / 穿越读出非公开内容）；2 环境错误（入口不可达、
判据执行异常、登记册缺件/不合规）。
--selftest：本地桩反代判别力自证——无限制桩 → B 腿必红；限速桩（121 后 429）
→ B 腿绿；穿越放行桩 → A 腿必红；合规桩 → A 腿绿；未认证面 401 桩 → auth 腿绿；
未认证面 200 桩 → auth 腿必红；**本体零限速桩 → C 腿必红；本体限速桩 → C 腿绿**
（新增两例，证明本门对「服务本体无闸」有判别力）。零网络。
"""
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)          # 登记册正本同目录导入（-I 隔离模式下也要显式加）
import public_entry_registry as _reg      # noqa: E402 —— 公网入口登记册正本

# 入口登记册（RT-E46③ 机检替身）：新公网反代入口 → 在 tools/public_entry_registry.py
# 追加一条，缺登记=巡检盲区=红（对账门 public-entry-registry-check.py 判红）。
# 登记册坏件/不合规 → fail-closed（exit 2，不可证不猜绿），不得退回内置清单。
try:
    REGISTRY_ENTRIES = _reg.load_entries()
except _reg.RegistryError as _e:
    print(f"[RED rc=2] 登记册不合规：{_e}——不可证不猜绿（fail-closed）", file=sys.stderr)
    sys.exit(2)

# 兼容旧引用（入口 URL 列表）；条目元数据（契约口径/打压路径）在 REGISTRY_ENTRIES。
ENTRIES = [e["base"] for e in REGISTRY_ENTRIES]

TRAVERSAL_VARIANTS = [
    "task/../AGENTS.md",
    "task/../../etc/passwd",
    "task/../..%2fAGENTS.md",
    "task/%2e%2e/AGENTS.md",
    "task/..%2fAGENTS.md",
    "task/%2e%2e%2fAGENTS.md",
    "static/../AGENTS.md",
    "static/../..%2fAGENTS.md",
    "static/%2e%2e/AGENTS.md",
    "static/..%2fAGENTS.md",
    "static/%2e%2e%2fAGENTS.md",
    "task/../../factory.json",
]

BURST_N = 131        # 恰超 120/min 帽（帽+11，≥1×429 判据的最小充分打压）
BURST_PAR = 8        # 并发度（「并发探针」口径；8 路 TLS 连接，秒级打完）

# ---- C 腿（服务本体限速腿）：「限速是否护住了服务」的可测面 -------------------
# 背景（2026-11-03 安全面确证发现，修复员批）：本门此前**只测反代入口**（A 穿越 +
# B 限速），结构上测不出「限速是否护住了服务」——门户本体（gov gov-host.invalid:8090）
# 在 tailnet（gov iptables `-i tailscale0 -j ACCEPT`）与 caddy docker 网段
# （`-i br-… --dport 8090 -j ACCEPT`）可直连、写路由 /claim /report 在役，而本体
# 零限速 ⇒ 前门 120/min 帽可被绕过（RT-E166「4MB 体帽 × 无速率」面仍在）。
# C 腿＝**直连本体**打压同口径路径，必须出现 429：本体自带闸在役才算「限速护住了
# 服务本体」。本体零限速 → 本腿红（门不再对「本体无闸」失明）。
#
# 打压**经 ssh 端口转发**从 gov 侧发起，且**目标取 docker 网桥网关 172.18.0.1:8090**
# （非 127.0.0.1）——门户看这批请求的对端身份因此是宿主 LAN 地址 10.1.0.6，
# 与 tailnet 消费方（factory-watch 每分钟 /healthz 巡检＝pandev-host.invalid、keepalive 的
# gov 回环验活＝127.0.0.1）**限速桶互不相干**：本体腿的 131 次打压不得连带 429 掉
# 在役巡检（A8 红灯 → keepalive 误重启门户＝自伤）；早先取 127.0.0.1 的版本实测
# 确会连带（keepalive 的 gov 回环 /healthz 得 429「rate limit exceeded」）。
# 隧道不可用（ssh 不可达等）→ fail-closed（不可证不猜绿），不静默 SKIP。
ORIGIN_SSH = os.environ.get("AF_JOBS_ORIGIN_SSH", "root@gov-host.invalid")
ORIGIN_TARGET = os.environ.get("AF_JOBS_ORIGIN_TARGET", "172.18.0.1:8090")
TUNNEL_READY_S = 20


def _conn(base, timeout=15):
    kind = "https"
    rest = base
    if "://" in base:
        kind, rest = base.split("://", 1)
    host = rest.split("/", 1)[0]
    prefix = rest[len(host):]
    if kind == "https":
        c = HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())
    else:
        c = HTTPConnection(host, timeout=timeout)
    return c, prefix


def raw_get(base, path, timeout=15):
    """原样路径 GET：路径逐字上送（无客户端归一化）≡ curl --path-as-is。"""
    c, prefix = _conn(base, timeout)
    try:
        c.request("GET", prefix + path)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def check_entry_traversal(entry):
    """A 腿：12 变体原样路径打入口；契约口径按登记册 contract_mode 分档。

    content：契约参照件必须 200（取不到=不可证=fail-closed）；任何 200 变体体必须
             逐字节等于参照件（caddy 归一化别名体=公开契约，非泄露）。
    auth   ：未认证基线必须 401/403（fail-closed 认证）；任何 200 变体=未认证泄露=红。
    none   ：任何 200 变体=红（无参照可比时只能断言「不得读出内容」）。
    """
    base = entry["base"]
    mode = entry.get("contract_mode", "none")
    cpath = entry.get("contract_path") or "/"
    ref = None
    if mode == "content":
        st, ref = raw_get(base, cpath)
        if st != 200:
            return False, f"前置不可证：{base}{cpath} → {st}（公开契约参照取不到，fail-closed）", True
    elif mode == "auth":
        st, _b = raw_get(base, cpath)
        if st not in (401, 403):
            return False, (f"认证腿红（{base}）：未认证基线 {base}{cpath} → {st}"
                          f"（应 401/403 fail-closed；非 401/403 = 认证失效/未认证公开暴露）"), False
    bad, nonref200 = [], []
    for v in TRAVERSAL_VARIANTS:
        st2, body = raw_get(base, "/" + v)
        if st2 == 200:
            if mode == "content" and ref is not None and body == ref:
                continue                       # 与公开契约逐字一致=caddy 归一化别名，非泄露
            nonref200.append(v)
        elif st2 in ((404, 429) if mode == "content" else (404, 429, 401, 403)):
            continue
        else:
            bad.append(f"/{v}→{st2}")
    if nonref200:
        detail = "；".join(f"/{p} → 200 读出非公开契约内容（md5={__import__('hashlib').md5(body).hexdigest()[:8]}，公开契约 md5={__import__('hashlib').md5(ref).hexdigest()[:8] if ref else 'N/A'}）"
                           for p in nonref200[:4])
        return False, f"穿越腿红（{base}）：{len(nonref200)} 变体 200 且内容≠公开契约——{detail}", False
    if bad:
        return False, f"穿越腿异常（{base}）：非白名单形态 {bad[:6]}（fail-closed，不可判绿）", True
    return True, f"穿越腿绿（{base}，口径={mode}）：{len(TRAVERSAL_VARIANTS)} 变体无 200≠契约形态", False


def check_entry_ratelimit(entry, label="限速腿"):
    """B 腿：并发探针 131×{probe_path} → 必须 ≥1×429。

    label：输出用腿名（B 腿＝「限速腿」，C 腿＝「本体限速腿」——同一判定逻辑，
    不同被打点面：反代入口 vs 服务本体）。
    """
    base = entry["base"]
    ppath = entry.get("probe_path") or "/healthz"
    dist = {}
    lock = threading.Lock()

    def one(_):
        try:
            st, _b = raw_get(base, ppath, timeout=20)
        except Exception:
            st = "ERR"
        with lock:
            dist[st] = dist.get(st, 0) + 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=BURST_PAR) as ex:
        list(ex.map(one, range(BURST_N)))
    dt = time.time() - t0
    n429 = dist.get(429, 0)
    n200 = dist.get(200, 0)
    if n429 >= 1:
        return True, f"{label}绿（{base}）：{BURST_N} 并发 {ppath} → 429×{n429} 200×{n200} 其余{ {k: v for k, v in dist.items() if k not in (429, 200)} }（{dt:.1f}s）", False
    if n200 == 0:
        return False, f"{label}不可证（{base}）：{BURST_N} 并发 {ppath} 零 200 且零 429（分布 {dist}）——入口可对账性丧失，fail-closed", True
    return False, f"{label}红（{base}）：{BURST_N} 并发 {ppath} → 零 429（分布 {dist}）——该入口无限速/限速失效，RT-E46 复发形态", False


# ---- C 腿：服务本体限速腿（直连本体打压，验「限速是否护住了服务」）------------
def _free_local_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class _OriginTunnel:
    """ssh 端口转发（本地 127.0.0.1:<临时端口> → gov ORIGIN_TARGET）。

    用途：让本体限速腿的请求源在门户看来是**独立对端身份**（目标取 docker 网桥
    网关 172.18.0.1 时，对端＝宿主 LAN 地址 10.1.0.6），与 tailnet 消费方
    （factory-watch 巡检 pandev-host.invalid、keepalive gov 回环验活 127.0.0.1）的限速桶
    隔离——本体腿的 131 次打压不得连带 429 掉在役巡检。隧道不可用 → 调用方按
    fail-closed 处理。
    """

    def __enter__(self):
        last = "ssh 转发不可用"
        for _attempt in (1, 2):
            port = _free_local_port()
            proc = subprocess.Popen(
                ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                 "-o", "ExitOnForwardFailure=yes",
                 "-L", f"127.0.0.1:{port}:{ORIGIN_TARGET}", ORIGIN_SSH],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f"http://127.0.0.1:{port}"
            deadline = time.time() + TUNNEL_READY_S
            ready = False
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    c = HTTPConnection("127.0.0.1", port, timeout=3)
                    c.request("GET", "/healthz")
                    r = c.getresponse()
                    r.read()
                    c.close()
                    ready = True
                    break
                except Exception:
                    time.sleep(0.3)
            if ready:
                self.proc = proc
                self.base = base
                return self
            last = f"ssh 转发不可用（{ORIGIN_SSH} → {ORIGIN_TARGET}）"
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        self.proc = None
        self.base = None
        self.err = last
        return self

    def __exit__(self, *exc):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        return False


def check_origin_ratelimit():
    """C 腿：直连服务本体打压 → 必须 ≥1×429（本体自带闸在役＝限速护住了服务）。

    不可证（隧道不可用 / 本体不可达）→ fail-closed（不可证不猜绿）。
    """
    with _OriginTunnel() as tun:
        if not tun.base:
            return False, f"本体限速腿不可证：{tun.err}——本体面无法对账，fail-closed", True
        ok, detail, is_fatal = check_entry_ratelimit(
            {"base": tun.base, "probe_path": "/healthz"}, label="本体限速腿")
        if not ok and "红" in detail:
            detail += "——服务本体零限速：前门 120/min 帽可被直连绕过（RT-E166 余留面）"
        return ok, detail, is_fatal


def run_entries(entries):
    fails, greens, fatal = [], [], False
    for entry in entries:
        for name, fn in (("A穿越", check_entry_traversal), ("B限速", check_entry_ratelimit)):
            try:
                ok, detail, is_fatal = fn(entry)
            except Exception as e:  # noqa: BLE001 —— 网络/判据异常按 fail-closed 计
                ok, detail, is_fatal = False, f"{name}腿执行异常（{entry['base']}）：{e!r}", True
            (greens if ok else fails).append(detail)
            fatal = fatal or (not ok and is_fatal)
    return fails, greens, fatal


# ---------------------------------------------------------------- 判别力自证
class _StubOrigin(BaseHTTPRequestHandler):
    """桩源站（真限速语义在反代层，桩直接以同语义实现供探针判别力自证）。"""
    allow_reuse_address = True
    n_req = 0
    limit_at = None      # None=无限制桩；=121 时第 121 个起 429（限速桩）
    leak = False         # True=穿越放行桩
    auth_gated = False   # True=未认证面恒 401（auth 口径入口桩）
    auth_leak = False    # True=auth 口径下穿越变体 200（未认证泄露桩）
    no_contract = False  # True=契约参照件取不到（不可证桩）

    def _send(self, code, body=b""):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        type(self).n_req += 1
        if type(self).limit_at is not None and type(self).n_req > type(self).limit_at:
            return self._send(429, "stub 429")
        is_trav = (".." in self.path or "%2e" in self.path)
        if type(self).auth_gated:
            if is_trav and type(self).auth_leak:
                return self._send(200, "STUB-CANARY-绝密")
            return self._send(401, "")
        if is_trav:
            if type(self).leak:
                return self._send(200, "STUB-CANARY-绝密")
            return self._send(404, "")
        if self.path == "/healthz":
            return self._send(200, '{"ok":true}')
        if self.path == "/AGENTS.md":
            if type(self).no_contract:
                return self._send(404, "")
            return self._send(200, "# stub 公开契约")
        return self._send(404, "")

    def log_message(self, *a):
        pass


def _spawn_stub(**attrs):
    cls = type("Stub_" + str(uuid.uuid4().hex[:6]), (_StubOrigin,), attrs)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _stub_entry(base, **over):
    """桩入口条目（登记册同构字段，kind 不参与校验）。"""
    e = {"slug": "stub", "base": base, "caddy_site": "stub.{$DOMAIN}", "kind": "demo",
         "contract_mode": "content", "contract_path": "/AGENTS.md", "probe_path": "/healthz"}
    e.update(over)
    return e


def selftest():
    results = []
    # 红路①：无限制桩 → B 腿必红（零 429）
    srv = _spawn_stub(limit_at=None)
    try:
        ok, detail, _f = check_entry_ratelimit(_stub_entry(_stub_base(srv)))
        results.append(("R1 判别力·无限制桩 B 腿必红", not ok, detail))
    finally:
        srv.shutdown()
    # 绿路①：限速桩（121 起 429）→ B 腿绿
    srv = _spawn_stub(limit_at=120)
    try:
        ok, detail, _f = check_entry_ratelimit(_stub_entry(_stub_base(srv)))
        results.append(("R2 判别力·限速桩 B 腿绿", ok, detail))
    finally:
        srv.shutdown()
    # 红路②：穿越放行桩 → A 腿必红（200 体≠契约）
    srv = _spawn_stub(leak=True)
    try:
        ok, detail, _f = check_entry_traversal(_stub_entry(_stub_base(srv)))
        results.append(("R3 判别力·穿越桩 A 腿必红", not ok, detail))
    finally:
        srv.shutdown()
    # 绿路②：合规桩 → A 腿绿
    srv = _spawn_stub(leak=False)
    try:
        ok, detail, _f = check_entry_traversal(_stub_entry(_stub_base(srv)))
        results.append(("R4 判别力·合规桩 A 腿绿", ok, detail))
    finally:
        srv.shutdown()
    # 红路③：契约参照件取不到（不可证）→ A 腿 fail-closed 必红
    srv = _spawn_stub(leak=False, no_contract=True)
    try:
        ok, detail, _f = check_entry_traversal(_stub_entry(_stub_base(srv)))
        results.append(("R5 判别力·契约参照不可证 A 腿必红(fail-closed)", not ok, detail))
    finally:
        srv.shutdown()
    # 绿路③：auth 口径未认证桩（401 面）→ A 腿绿
    srv = _spawn_stub(auth_gated=True)
    try:
        ok, detail, _f = check_entry_traversal(
            _stub_entry(_stub_base(srv), contract_mode="auth", contract_path="/"))
        results.append(("R6 判别力·auth 口径未认证面 A 腿绿", ok, detail))
    finally:
        srv.shutdown()
    # 红路④：auth 口径下穿越变体 200（未认证泄露）→ A 腿必红
    srv = _spawn_stub(auth_gated=True, auth_leak=True)
    try:
        ok, detail, _f = check_entry_traversal(
            _stub_entry(_stub_base(srv), contract_mode="auth", contract_path="/"))
        results.append(("R7 判别力·auth 口径未认证泄露 A 腿必红", not ok, detail))
    finally:
        srv.shutdown()
    # 红路⑤：auth 口径基线非 401（未认证公开暴露）→ A 腿必红
    srv = _spawn_stub(leak=False)
    try:
        ok, detail, _f = check_entry_traversal(
            _stub_entry(_stub_base(srv), contract_mode="auth", contract_path="/"))
        results.append(("R8 判别力·auth 口径基线非 401 A 腿必红", not ok, detail))
    finally:
        srv.shutdown()
    # 红路⑥：C 腿判别力——**本体零限速桩** → C 腿必红（本门对「服务本体无闸」不盲）
    srv = _spawn_stub(limit_at=None)
    try:
        ok, detail, _f = check_entry_ratelimit(
            {"base": _stub_base(srv), "probe_path": "/healthz"}, label="本体限速腿")
        results.append(("R9 判别力·本体零限速桩 C 腿必红", not ok, detail))
    finally:
        srv.shutdown()
    # 绿路③：C 腿判别力——本体限速桩 → C 腿绿
    srv = _spawn_stub(limit_at=120)
    try:
        ok, detail, _f = check_entry_ratelimit(
            {"base": _stub_base(srv), "probe_path": "/healthz"}, label="本体限速腿")
        results.append(("R10 判别力·本体限速桩 C 腿绿", ok, detail))
    finally:
        srv.shutdown()
    npass = sum(1 for _, ok, _ in results if ok)
    for n, ok, d in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {n} —— {d}")
    print(f"小计：PASS={npass} FAIL={len(results) - npass}")
    return 0 if npass == len(results) else 1


def _stub_base(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}"


def _entry_for(base):
    """base URL → 登记册条目；不在登记册 → 临时条目（契约口径 none，仅断言「不得 200」）。"""
    for e in REGISTRY_ENTRIES:
        if e["base"] == base:
            return e
    return {"slug": "adhoc", "base": base, "caddy_site": "", "kind": "demo",
            "contract_mode": "none", "contract_path": "/", "probe_path": "/healthz",
            "note": "临时指定（不在登记册——无契约参照可比）"}


# ---------------------------------------------------------------- 主流程
def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    if "--entry" in argv:
        bases = [v for i, v in enumerate(argv) if argv[i - 1:i] == ["--entry"]]
        entries = [_entry_for(b) for b in bases]
    else:
        entries = REGISTRY_ENTRIES
    t0 = time.time()
    fails, greens, fatal = run_entries(entries)
    # C 腿：服务本体限速腿（直连本体打压 → 必须 429；不可证 fail-closed）
    try:
        ok, detail, is_fatal = check_origin_ratelimit()
    except Exception as e:  # noqa: BLE001 —— 判据执行异常按 fail-closed 计
        ok, detail, is_fatal = False, f"本体限速腿执行异常：{e!r}", True
    (greens if ok else fails).append(detail)
    fatal = fatal or (not ok and is_fatal)
    for d in greens:
        print(f"[PASS] {d}")
    for d in fails:
        print(f"[FAIL] {d}")
    print(f"小计：入口={len(entries)} 绿={len(greens)} 红={len(fails)}（总耗时 {time.time() - t0:.1f}s）")
    if fails:
        return 2 if fatal else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
