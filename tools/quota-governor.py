#!/usr/bin/env python3
"""quota-governor.py — 三通道配额治理器（P3-R0 临时补丁件 #1，台账外补丁制度首个登记项）

背景（2026-10-27 R0 实测，计划/研究组/P3-R0-资源刺探-20261027/）：
  - step plan：GET https://api.stepfun.com/step_plan/v1/usage（Bearer=step key）
    Token-Pro 月付，2026-10-30 20:40 到期；**三模型（step-5-preview/step-3.7-flash/
    step-router-v1）共享 key 级 8 并发闸**（429 报错体明示 limit:8）。
  - minimax：GET https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains
    （Bearer=mcode OAuth，anolis ~/.local/bin/mcode-token.py get 现取）；
    mavis m3.1f/m3 双档并发独立（8+8 并发全 200）；瓶颈=general 5 小时窗。
    注意：裸读 anolis auth.json 的 token 会 1004，必须走刷新工具链。

职责（2026-11-03 订正后；v0 原型的 gates/slots 两道输出面已下线，见文末订正段）：
  poll   —— 单轮采集：step 用量/到期倒计时 + minimax 双窗水位 → 状态观测/quota.json
  daemon —— 循环 poll（缺省 60s）
  gates  —— 只读打印本件当前配额裁决姿态（step_go / minimax_go / 两窗读数 / 到期倒计时）
  ——**本件唯一落盘输出面（状态面）= 状态观测/quota.json**（step.go / minimax.go 布尔位）。
    配额闸由该面在两侧落地：派发侧 tools/factory-scheduler.py 的 read_quota()
    （按 minimax.go 写 mm 条目）、执行侧 tools/factory-status-push.py 的 mm_gate_ok
    （burn-runner 按 mm_ok 逐条收/拒）。mavis 闸阈是**派发侧与执行侧的唯一事实源**
    （2026-11-03 对账修复）：执行侧从本件取同一组常量、同一判据（mm_go()），两侧
    裁决恒等——此前两套阈值（8/8 vs 15/20）各判各的，同一份 quota.json 在分歧带内
    得出相反裁决（派发写单 / 执行拒单 → 队列积压）。
  ——**「8 槽占用态」不在本件**：step 订单跑在 anolis，真实占用态由调度器的 anolis
    进程计数探针读出（tools/factory-scheduler.py：pgrep -fc "af-orde[r].*step-5"，
    与 8 槽上限同口径）；本件不持锁、不计数、不代理该状态。

密钥纪律：key 只经子进程管道现取，绝不落盘/打印。回滚：删本文件+删状态观测/quota.json
（+tools/.quota-governor.pid）。
登记：计划/补丁台账-第三阶段.md #1。

DEB-7（2026-10-31 义务批）两处收敛：
  ① 常驻化：daemon 模式入 tools/factory-keepalive.py 的 watch 清单（LOCAL_GUARDS 第 6 项）。
     守护判据=进程在（/proc argv 精确匹配 tools/quota-governor.py 且子命令=daemon）
     + 状态观测/quota.json mtime<600s（AND 模式）。轮询周期默认 60s——远严于
     「≥300s 一轮」的下界，写盘点密度恒满足 600s 新鲜阈，配额闸（10min stale 阈）
     不再因读数老化误判 fail-closed（EXP-2 B2 臂 2026-10-31 00:06 被误跳的根因）。
     单实例纪律：daemon 自带 pidfile 守卫（tools/.quota-governor.pid，活进程即拒双开、
     陈旧 pidfile 自动接管），与 self-improve-loop 同款。
  ② step 段错误形态统一：API 失败一律写 {"go": false, "error": "<一句>"}，
     不再出现 {'error': ...}（无 go 键）的形态——消费方 step.get('go') 恒得 False
     而非 None，死态形态唯一。minimax 段同款收敛。

2026-11-07（D-110 / 红队分诊 H5 确认项）：**模型配额停用令消费腿**。
  根因（H5 复核留证）：本件 mm_go 只判两窗百分比（5h>15% ∧ 周池>20%），全文 0 处读
  运营者停用令（状态/模型配额停用-*.json：banned.providers 含 account:minimax-token-plan、
  banned.model_ids 含 MiniMax-M3.1-Flash，minimax_week_quota=EXHAUSTED「禁用至周重置」）
  ⇒ 周池重置瞬间 weekly_remaining_pct>20 即自动翻 true 恢复写 mm 条目，绕开运营者令。
  停用令的消费面此前只有外派闸（tools/wf-gate.py:170、tools/wf-model-hold-check.py），
  **派发环零消费**。本件补该腿：mm_go 增「banned 命中即 false」判据，与百分比判据 AND；
  解除仍由运营者改令文件（本件只读令，不写令、不自动解禁）。
  目录解析纪律（与 tools/factory-scheduler.py SA_STATE 同款先例）：停用令目录**派生自
  STATE** 而非写死 WS/状态——夹具/回归只重定向 STATE 一处，停用令面即连带改道，不会
  零声读生产停用令（tools/test-quota-gate-criteria-parity.py 的 B/F/G 段只重定向
  STATE；若写死生产路径，该门会把「运营者令在役」误判成「闸面被弱化」而红）。
  显式指向可用 AF_MODEL_HOLD_DIR 覆盖（人工核查/单测用）。
  键集纪律：命中只覆写 minimax 段**既有** error 键，不新增键——quota.json 整本被
  tools/factory-status-push.py:160 推上公网，其 minimax 段键集已被
  tools/publish-scrub-gate.py:167 QUOTA_MINI 冻结（新键即拦、停更不停线）。

2026-11-03 订正（RT 确证发现，修复员-35-常役基设-quota-gove）：
  本件此前另有两道**输出面**，实测确认二者均为零消费者死码，本次一并下线：
    ① /tmp/quota-gate/mavis-hold 闸文件（落闸写 / go=true 时删）——全仓 grep
       零执行面消费者（仅本件自身与计划台账散文命中）；落闸判据本就不经此文件，
       真闸在 状态观测/quota.json 的 minimax.go（两侧真在消费，见上）。
    ② /tmp/quota-gate/step-slots/ 的 8 个 flock 咨询槽位——自 2026-10-29 建槽起
       从未被任何进程 acquire/release（逐槽 flock -n 探针 8/8 FREE）；且真实 step
       生产者跑在 anolis，flock 不跨机，本地槽位在**结构上**也不可能被真实生产者
       持锁。「8 槽占用态」的真实现状是调度器的 anolis 进程计数探针（见上）。
  下线**未弱化任何既有保护**：落闸判据（mm_go 闸 / 源过期闸 / step 不可用或 8 槽
  满）、两侧阈值同源、fail-closed 方向一字未动——被下线的两面本就不参与任何裁决
  （零消费者），删除它们不改变任何一次放行/拒收。
  回归门：tools/test-quota-gate-criteria-parity.py G 段（闸面唯一性 + 负控：
  修前快照在本段必红，防死码复生）。
"""
import json, os, subprocess, sys, time, urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
STATE = os.path.join(WS, "状态观测/quota.json")
# 2026-11-03：/tmp/quota-gate/ 下的 mavis 闸文件面与 step 8 槽 flock 咨询面已下线
# （零消费者死码 + 槽位结构上不可能被 anolis 上的真实 step 生产者持锁）——
# 见文末订正段。本件唯一落盘输出面 = 状态观测/quota.json；「8 槽占用态」归调度器的
# anolis 进程计数探针。故此处不再有闸目录/槽目录常量。
# 2026-11-03 修复（配额闸两侧对账，RT 确证发现）：mavis 闸阈此前是 8.0/8.0，而执行侧
# tools/factory-status-push.py 下发的 mm_ok 用 15%/20%（2026-10-30 运营者令「烧量走
# minimax」时定）——同一份 quota.json 两边各判各的：分歧带 5h∈(8,15] ∪ wk∈(8,20] 内
# 派发侧 go=true（调度器照写 mm 条目）、执行侧 mm_ok=false（burn-runner 逐条拒收、
# 条目留队待闸开）→ 队列积压不可执行条目（结构性，非推演）。
# 修法（单一事实源）：闸阈取运营者令的 15/20，且**唯一事实源就在本件**——执行侧改为
# 从本件取同一组常量（tools/factory-status-push.py:MM_HOLD_FLOOR_PCT），两侧判据恒等。
# 为何取 15/20 而非 8/8：今日真正生效的约束本就是更严的执行侧 15/20（执行侧拒收即不
# 烧），故对齐到 15/20 = **有效配额保护与今日完全一致（不弱化）**，且派发侧不再写执行
# 侧必拒的死条目；若反向对齐到 8/8，等于把有效烧量从 15% 放宽到 8%（弱化保护，不取）。
HOLD_FLOOR_PCT = 15.0     # mavis 5h 窗剩余低于此值 → 落闸停派（= 执行侧 mm_ok 同阈）
# 2026-11-01 修复：周池进闸。此前 go 只看 5h 窗，weekly_remaining_pct 采集进 quota.json
# 却无任何消费点——周池触底后每个新 5h 窗开局即 go=true（实测 5h=65%、wk=1% 仍 go=true），
# 调度器照常写 mm 条目、派发在 API 侧撞周限流。
WEEKLY_HOLD_FLOOR_PCT = 20.0  # mavis 周池剩余低于此值 → 同样落闸（周重置才回升）
STEP_USAGE_URL = "https://api.stepfun.com/step_plan/v1/usage"
MM_REMAINS_URL = "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains"
# DEB-7：单实例锁（活进程即拒双开；陈旧 pidfile 自动接管）
PIDFILE = os.path.join(WS, "tools/.quota-governor.pid")
# DEB-7：daemon 轮询周期（s）——「≥300s 一轮」下界的 1/5，写盘点密度保证 600s 新鲜阈恒满足
DAEMON_INTERVAL_S = 60
ERR_MAX = 120          # error 文案截断（与旧行为同长）

# ---------- 2026-11-07（D-110 / H5）：模型配额停用令消费腿 ----------
# 停用令=运营者意志的机器可读面（schema af.model-quota-hold.v2）：banned.providers /
# banned.model_ids 两个集合 + statement 文案。本闸（minimax/mavis 道）管的通道身份 =
# 调度器头部 profile 考据段那两个 mavis 档案名（mavis-m3 → MiniMax-M3、
# mavis-m31f → MiniMax-M3.1-Flash-Preview）与其 token plan 账户。
HOLD_DIR_ENV = "AF_MODEL_HOLD_DIR"        # 显式指向覆盖（人工核查/单测）
HOLD_NAME_PREFIX = "模型配额停用-"
HOLD_NAME_SUFFIX = ".json"
MM_PROVIDER = "account:minimax-token-plan"   # 本闸管的 minimax 账户（令文件 banned.providers 同值）
MM_MODEL_IDS = ("MiniMax-M3", "MiniMax-M3.1-Flash")   # 本闸管的两档档案模型名


def hold_order_paths():
    """现行模型配额停用令文件列表（按文件名升序；末个=最新令）。

    目录派生自 STATE（dirname(dirname(STATE))/状态）——夹具/回归只改 STATE 一处即
    连带改道，不零声读生产停用令（先例：factory-scheduler.py SA_STATE）。生产态
    STATE=<WS>/状态观测/quota.json ⇒ 令目录=<WS>/状态。无文件=无令。
    """
    d = os.environ.get(HOLD_DIR_ENV) or os.path.join(
        os.path.dirname(os.path.dirname(STATE)), "状态")
    try:
        names = sorted(n for n in os.listdir(d)
                       if n.startswith(HOLD_NAME_PREFIX) and n.endswith(HOLD_NAME_SUFFIX))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names]


def hold_hit(model_ids=None, provider_id=MM_PROVIDER):
    """停用令命中判定 → (hit: bool, reason: str)。只读，不写令。

    命中口径与外派闸同族（tools/wf-model-hold-check.py 的 banned.providers /
    banned.model_ids 集合成员判定）——同一份运营者令，两个消费面不得各立一套口径。
    fail-closed（与 tools/wf-gate.py:180-186 同口径）：令文件在但读不出/解析失败
    ⇒ 按命中处理（运营者意志不可机读 ⇒ 不派发），reason 明写「不可读」。
    令目录空/不存在 ⇒ 不命中（没有令就没有令，不自行加码）。
    多份令按**最新**一份判（文件名日期戳升序取末个；外派闸 wf-gate 取 holds[0]
    的行为不在本件范围，本件不复制那一处）。
    """
    paths = hold_order_paths()
    if not paths:
        return False, ""
    path = paths[-1]
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            hold = json.load(f)
        banned = hold.get("banned") or {}
        b_prov = set(banned.get("providers") or [])
        b_model = set(banned.get("model_ids") or [])
    except Exception as e:   # noqa: BLE001 —— 令不可读≠无令：fail-closed 按命中
        return True, "停用令不可读（fail-closed 按命中处理）：%s %s" % (
            name, _one_sentence(e, "")[:60])
    ids = MM_MODEL_IDS if model_ids is None else tuple(model_ids or ())
    hits = []
    if provider_id and provider_id in b_prov:
        hits.append("provider=%s" % provider_id)
    for m in ids:
        if m in b_model:
            hits.append("model=%s" % m)
    if not hits:
        return False, ""
    return True, "运营者停用令生效（%s 命中 banned；令=%s）" % ("/".join(hits), name)


def mm_go(five_hour_remaining_pct, weekly_remaining_pct, hold=None):
    """mavis 放行判据（**唯一事实源**）：两窗剩余均高于闸阈 **且** 未命中停用令才放行。

    2026-11-03（配额闸两侧对账）：派发侧（本函数 → quota.json 的 minimax.go，
    调度器 factory-scheduler.py 按它写 mm 条目）与执行侧（factory-status-push.py
    下发的 gate.json 的 mm_ok，burn-runner 按它逐条收/拒）此前各判各的（8/8 vs
    15/20）→ 同一份 quota.json 得出相反裁决。现在两侧共用本函数判据与本件常量，
    裁决恒等（分歧带清零）。fail-closed：读数缺失/非法 → 不放行。

    2026-11-07（D-110 / 红队分诊 H5）：增**停用令消费腿**——此前只判百分比，周池
    重置瞬间即自动恢复派发、绕开运营者停用令（停用令消费面仅外派闸，派发环零消费）。
    现在 banned 命中即 false，与百分比判据 AND；hold=None 时本函数自行读令，
    poll 可传预演算的 (hit, reason) 避免同轮重复读。签名向后兼容：既有两侧调用
    （status-push 只取常量、poll 传两窗读数）不受影响。
    """
    try:
        p5 = float(five_hour_remaining_pct or 0)
        pwk = float(weekly_remaining_pct or 0)
    except (TypeError, ValueError):
        return False
    if not (p5 > HOLD_FLOOR_PCT and pwk > WEEKLY_HOLD_FLOOR_PCT):
        return False
    if hold is None:
        hold = hold_hit()
    return not bool(hold[0])


def _one_sentence(msg, prefix=""):
    """错误文案收敛为「一句」：折行合并为单行 + 前缀 + 截断（DEB-7 死态形态统一）。"""
    s = " ".join(str(msg).split())
    if prefix:
        s = prefix + s
    return s if len(s) <= ERR_MAX else s[:ERR_MAX - 1] + "…"


def _curl_json(url, bearer):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def step_key():
    out = subprocess.run(
        ["jq", "-r", '.config.providerConfigRules.providerRules[] | select(.providerId=="new-provider") | .config.access.apiKey',
         os.path.expanduser("~/.zcode/v2/provider_config.json")],
        capture_output=True, text=True, check=True).stdout.strip()
    if not out:
        raise RuntimeError("step key missing")
    return out


def minimax_token():
    out = subprocess.run(["ssh", "anolis", "python3 ~/.local/bin/mcode-token.py get"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    if not out.startswith("mmoat"):
        raise RuntimeError(f"mcode token fetch failed: {out[:40]}")
    return out


def poll():
    now_ms = int(time.time() * 1000)
    st = {"ts": now_ms}
    try:
        u = _curl_json(STEP_USAGE_URL, step_key())
        # DEB-7：credit_buckets 为空（套餐到期/无余量）原本抛 IndexError
        # 「list index out of range」，看不出根因——改为显式一句（仍走同一条错误形状）
        buckets = u.get("quota", {}).get("credit_buckets") or []
        if not buckets:
            raise RuntimeError("credit_buckets 为空（plan.state=%s quota.state=%s reason=%s）" % (
                u.get("plan", {}).get("state"), u.get("quota", {}).get("state"),
                u.get("quota", {}).get("reason")))
        bucket = buckets[0]
        st["step"] = {
            "remaining": int(bucket["remaining"]), "total": int(bucket["total"]),
            "used_percent": round(bucket.get("used_percent", 0), 2),
            "expires_at_ms": u["plan"]["subscription"]["expires_at_ms"],
            "seconds_to_expiry": (u["plan"]["subscription"]["expires_at_ms"] - now_ms) // 1000,
            "go": u["plan"]["subscription"]["expires_at_ms"] > now_ms and int(bucket["remaining"]) > 0,
        }
    except Exception as e:
        # DEB-7：step 死态形状唯一 = {"go": false, "error": "<一句>"}
        # （旧形态 {'error': ...} 无 go 键 → 消费方 step.get('go') 得 None，形态两义）
        st["step"] = {"go": False, "error": _one_sentence(e, "step 配额读取失败：")}
    try:
        r = _curl_json(MM_REMAINS_URL, minimax_token())
        gen = next(m for m in r.get("model_remains", []) if m.get("model_name") == "general")
        st["minimax"] = {
            "window_end_ms": gen["end_time"],
            "seconds_to_window_end": (gen["end_time"] - now_ms) // 1000,
            "five_hour_remaining_pct": gen["current_interval_remaining_percent"],
            "weekly_remaining_pct": gen["current_weekly_remaining_percent"],
        }
        # 2026-11-07（D-110/H5）：停用令腿——先读令（一次），再判 go（AND）。
        # 命中时把真因写进**既有** error 键（不新增键：minimax 段键集已被
        # publish-scrub-gate.py QUOTA_MINI 冻结，且整本 quota.json 上公网）。
        # 读数是真读数，照写——周重置后回不回升由运营者改令决定，不靠藏读数。
        hold = hold_hit()
        st["minimax"]["go"] = mm_go(st["minimax"]["five_hour_remaining_pct"],
                                    st["minimax"]["weekly_remaining_pct"], hold=hold)
        if not st["minimax"]["go"] and hold[0]:
            st["minimax"]["error"] = hold[1]
    except Exception as e:
        # DEB-7：minimax 段同款收敛（读不到即 go=false，fail-closed 方向一致）
        st["minimax"] = {"go": False, "error": _one_sentence(e, "minimax 配额读取失败：")}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)
    return st


# ---------- DEB-7：常驻 daemon 的单实例守卫（对标 self-improve-loop 同款） ----------

def acquire_pidfile():
    """活进程即拒双开；陈旧 pidfile 自动接管。

    判据=pidfile 指向的进程 argv 同时含 quota-governor.py 与子命令 daemon
    （一次性 poll 不是在役 daemon，不参与锁——否则手动 poll 会把常驻位误占）。"""
    try:
        old = open(PIDFILE, encoding="utf-8").read().strip()
    except OSError:
        old = ""
    if old and old.isdigit() and os.path.exists("/proc/%s" % old):
        try:
            argv = open("/proc/%s/cmdline" % old, "rb").read().decode("utf-8", "replace").split("\0")
            if any("quota-governor.py" in a for a in argv) and "daemon" in argv:
                print("quota-governor daemon 已在跑 pid=%s，拒绝双实例" % old, file=sys.stderr)
                sys.exit(3)
        except OSError:
            pass
    os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
    with open(PIDFILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release_pidfile():
    try:
        if open(PIDFILE, encoding="utf-8").read().strip() == str(os.getpid()):
            os.unlink(PIDFILE)
    except OSError:
        pass


def daemon(interval_s=DAEMON_INTERVAL_S):
    """常驻轮询（DEB-7）：单实例锁 + 每轮一行日志。

    日志落 stdout（keepalive 拉起时重定向到 状态观测/quota-governor.log），
    是 keepalive 判据的日志位证据；状态面是 状态观测/quota.json（每轮覆写）。"""
    acquire_pidfile()
    try:
        while True:
            t0 = time.time()
            try:
                st = poll()
                print("[%s] poll ok step.go=%s mm.go=%s cost=%.1fs" % (
                    time.strftime("%H:%M:%S"), st.get("step", {}).get("go"),
                    st.get("minimax", {}).get("go"), time.time() - t0), flush=True)
            except Exception as e:
                print("[%s] poll error: %s" % (
                    time.strftime("%H:%M:%S"), _one_sentence(e, "")), flush=True)
            time.sleep(max(10, interval_s))
    finally:
        release_pidfile()


def _selftest():
    """停用令消费腿内置夹具自测（D-110/H5；`python3 -I tools/quota-governor.py selftest`）。

    零网络、零真令读取：令目录指到临时夹具目录（AF_MODEL_HOLD_DIR），STATE 指到沙箱
    （本函数不改生产状态面、不读生产停用令）。正负例成对：既证「banned 命中即 false」，
    也证「未命中不自行加码」（否则这条腿会把 minimax 道永久焊死，反而制造停派）。
    """
    import tempfile

    global STATE          # 沙箱状态面（函数内改、finally 恢复；不落生产）

    def _order(dirpath, name, doc):
        os.makedirs(dirpath, exist_ok=True)
        with open(os.path.join(dirpath, name), "w", encoding="utf-8") as f:
            if isinstance(doc, str):
                f.write(doc)
            else:
                json.dump(doc, f, ensure_ascii=False)

    def _banned(providers=(), models=()):
        return {"schema": "af.model-quota-hold.v2", "statement": "夹具",
                "banned": {"providers": list(providers), "model_ids": list(models)}}

    results, failures = [], []

    def check(name, got, want):
        ok = got == want
        results.append((ok, name, got, want))
        if not ok:
            failures.append("%s：实得 %r 期望 %r" % (name, got, want))

    with tempfile.TemporaryDirectory(prefix="quota-gov-selftest.") as td:
        hold_dir = os.path.join(td, "状态")
        os.environ[HOLD_DIR_ENV] = hold_dir
        old_state = STATE
        STATE = os.path.join(td, "状态观测", "quota.json")   # 沙箱状态面（不落生产）
        try:
            # ---- 负例①：无令（目录空）⇒ 不命中、不自行加码 ----
            check("无令目录→不命中", hold_hit(), (False, ""))
            check("无令+阈上→放行（旧行为不回归）", mm_go(83, 49), True)
            check("无令+阈下→不放行（百分比闸仍在）", mm_go(7, 3), False)
            # ---- 负例②：令在但本通道未列（只停 GLM/bigmodel）⇒ 不命中 ----
            _order(hold_dir, "模型配额停用-20260101.json",
                   _banned(["account:bigmodel-highspeed-card"], ["GLM-5.3"]))
            hit, why = hold_hit()
            check("令在但本通道未列→不命中", hit, False)
            check("令在但本通道未列→reason 空", why, "")
            check("令在但本通道未列+阈上→放行", mm_go(83, 49), True)
            check("令在但本通道未列+阈下→不放行", mm_go(7, 3), False)
            # ---- 正例①：banned.providers 命中 account:minimax-token-plan ----
            _order(hold_dir, "模型配额停用-20261105.json",
                   _banned(["account:bigmodel-offpeak-idle-plan", "account:minimax-token-plan"],
                           ["GLM-5.3", "MiniMax-M3.1-Flash"]))
            hit, why = hold_hit()
            check("provider 命中→hit", hit, True)
            check("provider 命中→reason 带令名", "模型配额停用-20261105.json" in why, True)
            check("provider 命中→reason 带身份", "account:minimax-token-plan" in why, True)
            check("provider 命中+两窗满→不放行（H5 根因形态）", mm_go(100, 100), False)
            check("provider 命中+阈下→不放行（AND 不反向放行）", mm_go(1, 1), False)
            # ---- 正例②：只禁 model_ids（provider 未列）同样命中 ----
            _order(hold_dir, "模型配额停用-20261106.json", _banned([], ["MiniMax-M3.1-Flash"]))
            check("model 命中→hit", hold_hit()[0], True)
            check("model 命中+两窗满→不放行", mm_go(99, 99), False)
            # ---- 正例③：多令取**最新**一份（旧令禁 minimax、新令不禁 ⇒ 放行）----
            _order(hold_dir, "模型配额停用-20261107.json", _banned(["account:x"], ["GLM-5.3"]))
            check("多令取最新→不命中", hold_hit()[0], False)
            check("多令取最新+阈上→放行", mm_go(83, 49), True)
            # ---- fail-closed：令在但不可读 ⇒ 按命中处理（与 wf-gate 同口径）----
            _order(hold_dir, "模型配额停用-20261108.json", "{ 这不是 JSON")
            hit, why = hold_hit()
            check("令不可读→fail-closed 命中", hit, True)
            check("令不可读→reason 明写不可读", "不可读" in why, True)
            check("令不可读+两窗满→不放行", mm_go(100, 100), False)
            # ---- 预演算 hold 直传（poll 同轮不重复读令）----
            _order(hold_dir, "模型配额停用-20261109.json", _banned([], []))
            check("空 banned→不命中", hold_hit()[0], False)
            check("预演算 hold 直传(命中)→不放行", mm_go(100, 100, hold=(True, "夹具")), False)
            check("预演算 hold 直传(未命中)+阈上→放行", mm_go(100, 100, hold=(False, "")), True)
            # ---- 读数缺/非法 ⇒ fail-closed 不变 ----
            check("读数缺失→不放行", mm_go(None, None), False)
            check("读数非法→不放行", mm_go("abc", 99), False)
        finally:
            STATE = old_state
            del os.environ[HOLD_DIR_ENV]

    for ok, name, got, want in results:
        print("  %s %s（实得 %r）" % ("PASS" if ok else "FAIL", name, got))
    if failures:
        for f in failures:
            print("FAIL %s" % f)
        sys.exit(1)
    print("PASS quota-governor 停用令消费腿夹具 %d 例全过（正例 3 组/负例 2 组/"
          "fail-closed 1 组/多令取最新/预演算直传/读数 fail-closed）" % len(results))
    sys.exit(0)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if cmd == "poll":
        print(json.dumps(poll(), ensure_ascii=False, indent=1))
    elif cmd == "gates":
        # 只读打印本件当前配额裁决姿态（2026-11-03：死面 mavis_hold_file 字段已下线
        # ——该闸文件全仓零消费者，落闸真判据在 quota.json 的 minimax.go）
        # 2026-11-07（D-110/H5）：增停用令腿读数（minimax_hold）——此前「闸为何闭」
        # 只有百分比一个来源，停用令命中在 gates 面不可见（读令文件才知）。
        st = json.load(open(STATE)) if os.path.exists(STATE) else poll()
        hold = hold_hit()
        print(json.dumps({"step_go": st.get("step", {}).get("go"),
                          "minimax_go": st.get("minimax", {}).get("go"),
                          "minimax_hold": {"hit": hold[0], "reason": hold[1],
                                           "order_files": [os.path.basename(p) for p in hold_order_paths()]},
                          "step_seconds_to_expiry": st.get("step", {}).get("seconds_to_expiry"),
                          "minimax_5h_pct": st.get("minimax", {}).get("five_hour_remaining_pct"),
                          "minimax_wk_pct": st.get("minimax", {}).get("weekly_remaining_pct")},
                         ensure_ascii=False, indent=1))
    elif cmd == "selftest":
        # 2026-11-07（D-110/H5）：停用令腿内置夹具自测（零网络、零真令读取——
        # 令目录指到临时夹具目录，STATE 指到沙箱）。正负例各覆盖
        # 「命中即 false」与「未命中不自行加码」两个方向，另覆 fail-closed（令不可读）。
        _selftest()
    elif cmd == "daemon":
        # DEB-7：轮询周期可覆盖（默认 60s；「≥300s 一轮」下界的 1/5）
        iv = int(sys.argv[2]) if len(sys.argv) > 2 else DAEMON_INTERVAL_S
        daemon(iv)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
