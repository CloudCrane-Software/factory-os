#!/usr/bin/env python3
"""factory-status-push.py — 工厂快况推送器（P3 补丁台账 P3-6）

每 60 秒聚合：quota（governor 状态文件）+ anolis 订单汇总 + 烧量账 + 沙箱任务板计数
→ /data/factory.json 物化推送 gov（af-jobs 门户 /factory.json 消费；看板 10s 轮询，
推送 60s 保证数据新鲜度）。只读采集；单次运行后退出（由 daemon 循环调用）。回滚：停进程+删 gov 文件。

V 线收尾（2026-10-28）：push_board（v2 看板数据面）推送前增加发布脱敏闸
tools/publish-scrub-gate.py——待发布树（orders/quota/data/stream）先过闸，闸红
（命中密钥形态/白名单外文件）即跳过本轮不推送（gov 保留上一版=停更不停线），
人读明细进 status-push.log、公开面只写固定短语 alarms.log（H3 纪律）。

订单可见性（2026-10-29 工单②）：push_board 每轮先跑 tools/order-stages.py 刷新
状态观测/stages.json（每订单 阶段/轮次/Token/最近动作），入暂存树一并过闸后推
gov static/v2/stages.json，供看板"进行中订单"区 30s 轮询；采集失败=本轮不带
stages（gov 保留上一版）。回滚：停进程 + 删 gov static/v2/stages.json。

OTel 指标接线（2026-10-29 DEB-2d）：OTel 观测边车快照 状态观测/otel-sidecar.json
随暂存树入面并推 gov static/v2/otel-sidecar.json（沿 stages.json 同款路径），供看板
v2"OTel 指标"区 30s 拉取；发布面为脱敏副本（collector_endpoint 带 tailnet IP，脱敏闸
O-01 必拦，见 _stage_otel_sidecar）；快照缺失=本轮不带（gov 保留上一版）。配套：
publish-scrub-gate.py PATH_OK 增补 otel-sidecar.json + 看板 v2 指标区。

MES 记账队列补投（红队 C5 收口，2026-10-29 义务收口批）：门户在 gov 不可直达 MES
（mes-host.invalid:15221 连接超时+无凭据），/claim 与 /report 各记一笔进 gov 本地
mes-events.jsonl；本机有 MES 凭据链，每轮拉回批量补投 af_mes.mes_event。闭环语义：
event_id 预查去重（幂等）+ 补投失败不截断队列（至少一次）+ 坏行进隔离件（不静默
丢弃）。回滚=停进程 + 删本函数与 main() 调用（恢复 .bak-*-pre-C5mesqueue）。"""
import datetime, glob, importlib.util, json, os, shutil, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
GOV = "root@gov-host.invalid"
TMP = "/tmp/factory.json"
# v2 看板数据面：待发布暂存树（镜像 gov static/ 布局；点开头文件不入树——G-5）
STAGE = os.path.join(WS, "工具状态备份/factory-view/staging")
GATE = os.path.join(WS, "tools/publish-scrub-gate.py")
STAGES = os.path.join(WS, "状态观测/stages.json")           # 订单阶段观测（order-stages.py 产出）
OTEL_SIDECAR = os.path.join(WS, "状态观测/otel-sidecar.json")  # OTel 边车快照（emit-sidecar.py 产出；DEB-2d）
ORDER_STAGES = os.path.join(WS, "tools/order-stages.py")
# ssh 加固：禁交互、连接超时、保活探测——防单次采集挂死拖垮推送循环（验收 H2）
SSH_OPTS = "-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2"

# MES 凭据解析单一真源（tools/otel/ch_client.py；本件不接触任何口令）。缺失只关
# MES 队列补投一路，不影响看板推送主职。
sys.path.insert(0, os.path.join(WS, "tools", "otel"))
try:
    import ch_client
except Exception:  # noqa: BLE001
    ch_client = None


def sh(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


# ---------------------------------------------------------------- 配额闸判据（单一事实源）
# 2026-11-03 修复（配额闸两侧对账，RT 确证发现）：执行侧 mm_ok 的阈值此前就地硬编码
# 15%/20%，与派发侧 quota-governor.py 的 8%/8% 各判各的 → 同一份 quota.json 在分歧带
# （5h∈(8,15] ∪ wk∈(8,20]）得出相反裁决：调度器按 go=true 写 mm 条目、burn-runner 按
# mm_ok=false 逐条拒收且条目留队（burn-runner.py:205「留队待闸开」）→ 队列积压不可执行
# 条目（结构性，非推演）。
# 修法（最小、不弱化）：阈值不再就地硬编码，改为从派发侧同一件（quota-governor.py）
# 取同一组常量——**唯一事实源**；两侧判据恒等（mm_ok ≡ minimax.go）。
def _mm_gate_floors():
    """取派发侧 quota-governor.py 的同一组 mavis 闸阈（唯一事实源）。

    取不到即 (None, None) → mm_gate_ok 恒 False（fail-closed：宁可不烧，
    也不让两侧再次各判各的——绝不静默回落到任何就地阈值）。"""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quota-governor.py")
    try:
        spec = importlib.util.spec_from_file_location("quota_governor_criteria", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return float(mod.HOLD_FLOOR_PCT), float(mod.WEEKLY_HOLD_FLOOR_PCT)
    except Exception:  # noqa: BLE001
        return None, None


MM_HOLD_FLOOR_PCT, MM_WEEKLY_HOLD_FLOOR_PCT = _mm_gate_floors()


def mm_gate_ok(mq):
    """mavis 系执行闸判据（与派发侧 quota-governor.mm_go 同一口径、同一阈值）。

    fail-closed：闸阈取不到 / go 缺或假 / 两窗读数缺失（→0）或低于阈值 → 一律不放行。"""
    if MM_HOLD_FLOOR_PCT is None or MM_WEEKLY_HOLD_FLOOR_PCT is None:
        return False
    try:
        p5 = float(mq.get("five_hour_remaining_pct") or 0)
        pwk = float(mq.get("weekly_remaining_pct") or 0)
    except (TypeError, ValueError):
        return False
    return bool(mq.get("go")) and p5 > MM_HOLD_FLOOR_PCT and pwk > MM_WEEKLY_HOLD_FLOOR_PCT


# ---------------------------------------------------------------- 源读数新鲜度（2026-11-03 OBS 回头·派生闸）
# 缺陷（确证）：源读数新鲜度纪律只在派发侧落地（tools/factory-scheduler.py:read_quota()
# —— ts = st.get("ts") or 0; age_ms = time.time()*1000 - ts; q["stale"] = age_ms > QUOTA_STALE*1000，
# QUOTA_STALE=600）。派生闸此前只带「自身写入时刻」(updated)，**不携带源读数 ts**：
# 执行侧 burn-runner 的 10min 新鲜度门只看闸文件自身 mtime（burn-runner.py:58-60），
# 而本推送器每 60s 覆写一次闸文件 → 源 quota.json 停写时闸恒新鲜、mm_ok/step_ok 恒为
# 停写前的旧裁决 → 执行侧照旧按旧配额下单（撞限流形态），且与派发侧（源陈旧即停派）
# 对同一源读数给出相反行为。
# 修法（最小、不弱化任何既有判据）：
#   ①派生闸携带源读数 ts/年龄/是否陈旧（src_ts/src_age_s/src_stale）——消费侧据此
#     **独立**判断源新鲜度，不再只能信「闸自身新鲜」；
#   ②源读数陈旧（或无 ts）即闸自身 fail-closed（step_ok=mm_ok=false）——不再下发
#     停写前的旧裁决（既有 step_ok/mm_ok 判据一字未改，仅在源陈旧时叠加落闸）。
def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# 源读数陈旧阈——与 factory-scheduler QUOTA_STALE（默认 600s）、burn-runner
# GATE_STALE_S 同值（keepalive 判活阈亦同值）；同一环境变量 FS_QUOTA_STALE_S 可统一调。
QUOTA_SRC_STALE_S = _env_int("FS_QUOTA_STALE_S", 600)


def derive_gate(q, now_ms=None):
    """由 quota.json 源读数派生执行闸（burn-runner fail-closed 消费）。

    返回闸 dict：step_ok / mm_ok（既有判据）+ src_ts / src_age_s / src_stale
    （源读数新鲜度证据）。源读数陈旧（age > QUOTA_SRC_STALE_S）或缺 ts → 闸自身
    fail-closed（两通道皆闭），reason 记真因。纯函数（无 IO、无副作用）。"""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    q = q or {}
    sq = q.get("step") or {}
    mq = q.get("minimax") or {}
    src_ts = q.get("ts") or 0
    src_age_s = max(0, (now_ms - src_ts) // 1000) if src_ts else None
    src_stale = (not src_ts) or (src_age_s > QUOTA_SRC_STALE_S)
    gate = {"step_ok": (sq.get("seconds_to_expiry") or 0) > 3600 and (sq.get("remaining") or 0) > 200_000_000,
            "mm_ok": mm_gate_ok(mq),
            "mm_floor_pct": MM_HOLD_FLOOR_PCT, "mm_weekly_floor_pct": MM_WEEKLY_HOLD_FLOOR_PCT,
            "remaining": sq.get("remaining"), "seconds_to_expiry": sq.get("seconds_to_expiry"),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "src_ts": src_ts or None, "src_age_s": src_age_s, "src_stale": src_stale}
    if src_stale:
        gate["step_ok"] = False
        gate["mm_ok"] = False
        gate["reason"] = (f"源读数过期（age={src_age_s}s>{QUOTA_SRC_STALE_S}s）——闸 fail-closed"
                          if src_ts else "源读数无 ts——闸 fail-closed")
    return gate


def shb(cmd, timeout=30):
    """sh 的字节精确版：不 strip、不按文本解码（MES 队列读要求逐字节对齐）。

    2026-11-02 收口（strip 撕裂环）：队列 cat 此前走 sh().strip()，消费边界=
    去白长度恒短于真实前缘 → tail -c +(consumed+1) 每轮留尾字节（每事件漏一个
    "}" 进隔离件、空白残渣轮永不截断=gov 队列永不清零）。"""
    return subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout).stdout


def build():
    out = {"ts": int(time.time() * 1000), "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        out["quota"] = json.load(open(os.path.join(WS, "状态观测/quota.json")))
    except Exception:
        out["quota"] = {"error": "no snapshot"}
    try:
        q = out["quota"].get("step", {})
        out["step_burn"] = {"remaining": q.get("remaining"), "hours_to_expiry": (q.get("seconds_to_expiry") or 0) // 3600}
    except Exception:
        pass
    try:
        raw = sh(f"ssh {SSH_OPTS} anolis 'for f in /data/bench/af-p3-state/orders/R0-*/results.jsonl; do [ -f $f ] && tail -1 $f; done'")
        st = {}
        tin = 0
        for line in raw.splitlines():
            try:
                j = json.loads(line)
            except Exception:
                continue
            st[j.get("status", "?")] = st.get(j.get("status", "?"), 0) + 1
            tin += (j.get("tokens") or {}).get("input") or 0
        raw2 = sh(f"ssh {SSH_OPTS} anolis 'pgrep -c af-order 2>/dev/null; true'")
        procs = 0
        for ln in raw2.splitlines():
            ln = ln.strip()
            if ln.isdigit():
                procs = int(ln); break
        out["factory"] = {"orders_total": sum(st.values()), "by_status": st,
                          "burn_input_tokens_sum": tin, "af_order_procs": procs}
    except Exception as e:
        # 公开 error 只写固定短语（验收 H3：不泄露主机别名/内网路径/命令原文），原文留本地日志
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] factory 采集失败: {e}", flush=True)
        out["factory"] = {"error": "anolis 订单采集失败"}
    try:
        raw = sh(f"ssh {SSH_OPTS} {GOV} 'cat /opt/company/af-jobs/data/claims.json 2>/dev/null'")
        claims = json.loads(raw or "{}")
        counts = {}
        now = time.time()
        for tid, c in claims.items():
            if c.get("reported"):
                k = "reported"
            elif c.get("expires_at", 0) < now:
                k = "open"
            elif now - c.get("last_heartbeat", c.get("claimed_at", now)) > 900:
                k = "stalled"
            else:
                k = "claimed"
            counts[k] = counts.get(k, 0) + 1
        out["sandbox_tasks"] = counts
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] sandbox_tasks 采集失败: {e}", flush=True)
        out["sandbox_tasks"] = {"error": "claims 读取失败"}
    return out


def build_orders_json(stream_dirs, stages_src=None):
    """v2 看板订单列表：从 stream-tailer 的 <order>__<run>[__node].json 聚合。
    stream_key = 文件名去扩展名（tailer leaf.run_key 真实口径；S4 文档的 -- 口径作废）。

    订单级 terminal 补齐（2026-11-02，RT-E112 数据面腿）：页面订单区读 ord.terminal
    （状态/看板/v2/index.html :923 fmtStopState(t.stop_state)、:961 termBadge(ord.terminal)、
    :965-966 terminal.reward），此前本函数只发 runs[].stop 标量、订单级无 terminal 键 →
    公网 1027 单终态列全 '?'、reward 列全 '—'（页面/数据两套键名体制，键名断裂的
    原始登记只存在于设计批文档，两账零登记）。现在：
      · terminal.stop_state = updated_ms 最新 run 的 stream terminal.stop_state 对象原样
        （{v,streak,normal_errors}，S3 规格钉死形态；页面 fmtStopState R2 勘误明载
        对象/短串两种形态统一格式化）；
      · terminal.reward / terminal.stage = order-stages.py 判官与终态分类真值
        （stages_src 按 order_id 精确合流；实测 stream 单 100% 命中 stages 名册；
        stages 文件缺席/该单缺席 → null，页面 reward 列显示 '—'，不阻塞订单面）。
    runs[].stop 标量保留（向后兼容既有消费端）。"""
    rewards = {}
    if stages_src and os.path.isfile(stages_src):
        try:
            with open(stages_src, encoding="utf-8") as f:
                for so in (json.load(f).get("orders") or []):
                    oid = so.get("order_id")
                    if oid:
                        rewards[oid] = (so.get("reward"), so.get("stage"))
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 合流失败（reward/stage 置空，不影响订单面）: "
                  f"{type(e).__name__}: {str(e)[:80]}", flush=True)
    orders = {}
    for sd in stream_dirs:
        for f in glob.glob(os.path.join(sd, "*.json")):
            stem = os.path.splitext(os.path.basename(f))[0]
            if not stem or stem.startswith("."):
                continue
            try:
                d = json.load(open(f))
            except Exception:
                continue
            ident = d.get("identity") or {}
            stop = (((d.get("terminal") or {}).get("stop_state") or {}).get("v"))
            stop_obj = ((d.get("terminal") or {}).get("stop_state"))
            up = d.get("updated_ms") or 0
            parts = stem.split("__")
            oid = parts[0]
            run_id = "__".join(parts[1:]) or stem
            o = orders.setdefault(oid, {"order_id": oid, "unit": ident.get("layout") or "?",
                                        "runs": [], "last_activity": up})
            o["runs"].append({"run_id": run_id, "stream_key": stem,
                              "profile": ident.get("profile"), "model": ident.get("model"),
                              "stop": stop, "updated_ms": up})
            o["last_activity"] = max(o["last_activity"], up)
            # 订单级 terminal.stop_state：取 updated_ms 最新 run 的对象原样（>= 同 ms 后写覆盖）
            if stop_obj is not None and up >= o.get("_term_up", -1):
                o["_term_up"] = up
                o["terminal"] = {"stop_state": stop_obj}
    for o in orders.values():
        o.pop("_term_up", None)
        rw, stg = rewards.get(o["order_id"], (None, None))
        term = o.get("terminal") or {}
        term["reward"] = rw
        term["stage"] = stg
        o["terminal"] = term
    return {"ts": int(time.time() * 1000),
            "source": "factory-status-push（stream-tailer 键名口径；terminal=stream stop_state+order-stages 判官/终态合流，RT-E112 数据面 2026-11-02）",
            "stream_key_rule": "<order>__<run>[__node]（tailer leaf.run_key）",
            "stream_locations": ["stream/", "stream-demo/"],
            "orders": sorted(orders.values(), key=lambda x: -(x["last_activity"] or 0))}


ALARMS_LOG = os.path.join(WS, "状态观测/alarms.log")   # 告警面路径提为常量（DEB57：selftest 可指沙箱）


def _alarm(level, code, message):
    """alarms.log 行（A-6 实测格式）。公开面只写固定短语（H3）；细节只进 status-push.log。"""
    try:
        line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "level": level, "code": code,
                "message": message, "since": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(ALARMS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _stage_otel_sidecar():
    """DEB-2d（2026-10-29）：OTel 观测边车快照入暂存树（发布面脱敏副本）。

    源=状态观测/otel-sidecar.json（emit-sidecar.py 每周期原子刷新；本地全保真）。
    发布面删 collector_endpoint：其值形如 http://pandev-host.invalid:4318=tailnet CGNAT 段，
    脱敏闸 O-01 必拦（实测：不带删减直接入树跑闸 → {"verdict":"block","hits":["O-01"]}，
    整块看板会被闸红拖住=停更不停线；otlp-report.md §四"内容模式不会拦"的预检结论
    由此被推翻，已如实登记）。看板指标区只消费 metrics/sources/emit/errors，不需要
    端点真值；本地全保真副本仍在 状态观测/otel-sidecar.json。
    快照缺失/不可解析=本轮不入树（gov 保留上一版，与 stages 同款语义）。"""
    try:
        with open(OTEL_SIDECAR, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] otel-sidecar 快照不可用（本轮不带）: "
              f"{type(e).__name__}: {str(e)[:80]}", flush=True)
        return
    if not isinstance(snap, dict):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] otel-sidecar 快照形状异常（本轮不带）", flush=True)
        return
    snap.pop("collector_endpoint", None)   # 发布面脱敏（tailnet IP；O-01）
    try:
        with open(os.path.join(STAGE, "otel-sidecar.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] otel-sidecar 入暂存树失败: {e}", flush=True)
    # 账本一致批（2026-11-02）：本地看板 v2/ 同步一份同款脱敏副本（原子落位）。背景：
    # 8790 http.server 文档根=状态/看板，v2/index.html fetch("./otel-sidecar.json")
    # 此前只能吃到 10-29 手工孤件（round=650 vs 真值滚动）——本地可达路径与真值源
    # 脱节。不能直接链真值：状态观测/otel-sidecar.json 为全保真快照含 collector_endpoint
    # （tailnet IP），v2/ 在役断言（verify_static.py O-01）要求本地副本保持发布面脱敏
    # 形，而脱敏形唯一产地就是本函数——故每轮物化。失败不致命，不影响推送主职。
    try:
        local = os.path.join(WS, "状态/看板/v2/otel-sidecar.json")
        tmp = local + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp, local)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] otel-sidecar 本地镜像失败（不影响推送）: {e}",
              flush=True)


def _stage_board(stream_dirs, stages_src=None):
    """物化待发布树（精确镜像 gov static/ 布局；点开头文件/非 json 不入树——G-5 修复：
    .tailer-state.json 等 tailer 游标件不得上公网）。返回 stage 目录。

    stages_src：订单阶段观测 stages.json 的源路径（订单可见性工单②）。None=不入树
    （gov 保留上一版=停更不停线，与闸红同款语义）。"""
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(os.path.join(STAGE, "stream"), exist_ok=True)
    for rel, src in (("orders.json", "/tmp/orders.json"),
                     ("quota.json", os.path.join(WS, "状态观测/quota.json")),
                     ("data.json", os.path.join(WS, "状态/看板/data.json")),
                     ("stages.json", stages_src)):
        if src and os.path.isfile(src):
            shutil.copy2(src, os.path.join(STAGE, rel))
    _stage_otel_sidecar()   # DEB-2d：OTel 边车快照（发布面脱敏副本）入树
    for d in stream_dirs:   # 顺序与原双 rsync 一致：local 后拷=同名列覆盖 anolis
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.startswith(".") or not fn.endswith(".json"):
                continue
            shutil.copy2(os.path.join(d, fn), os.path.join(STAGE, "stream", fn))
    return STAGE


def build_stages():
    """订单阶段观测（工单②）：跑 order-stages.py 刷新 状态观测/stages.json（本机 ssh 只读采集
    anolis），返回源路径；采集失败返回 None——本轮 stages 不入暂存树，gov 保留上一版。"""
    if not os.path.isfile(ORDER_STAGES):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 采集跳过：{ORDER_STAGES} 不在位", flush=True)
        return None
    try:
        r = subprocess.run([sys.executable, ORDER_STAGES], capture_output=True, text=True, timeout=180)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 采集失败: {e}", flush=True)
        return None
    if r.returncode != 0:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 采集非零退出 rc={r.returncode}: "
              f"{(r.stderr or '').strip()[:200]}", flush=True)
        return None
    if not os.path.isfile(STAGES):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 采集后未见 {STAGES}", flush=True)
        return None
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stages 采集 ok: "
          f"{(r.stdout or '').strip().splitlines()[0][:160] if r.stdout else ''}", flush=True)
    return STAGES


# ---------- MES 记账队列补投（红队 C5 收口，2026-10-29 义务收口批）----------
# 门户（gov）实测不可直达 MES（mes-host.invalid:15221 连接超时 + 无凭据件），故 /claim 与
# /report 成功路径各记一笔进 gov 本地 mes-events.jsonl；本机有 MES 凭据链（0600 文件），
# 每轮拉回批量补投 af_mes.mes_event。闭环语义（C5：写入不得无闭环、不得静默丢弃）：
#   · 幂等：补投前按 event_id 预查已存在集，跳过重复（bench-mes.py 同口径）
#   · 至少一次：补投失败（含部分失败）不截断 gov 队列，下轮重试
#   · 不丢弃：坏行（JSON 解析失败/缺字段）原样入本地隔离件 状态观测/mes-queue-bad.jsonl
#     （2026-11-01 收口：隔离写在本轮消费成功定局、截断前——失败轮不再重写，防无界增长；
#       2026-11-02 E33③ 收口：隔离件带大小上限——超限轮转 .rot 归档+amber 告警，
#       归档保 MES_QUEUE_BAD_MAX_ARCHIVES 份。此前 62h+ 死循环把同一批 73 条粘连坏行
#       每轮重写，无上限无告警涨到 ~203MB/22.5 万行）
#   · 前缀消费：成功后取未消费后缀原子换名（带尺寸守卫，防门户并发追加被误删；
#     stat 与换名间的残余竞态由 event_id 去重兜底=至多一次重复投递。2026-11-01 修复：
#     原 truncate -s 保留前缀方向反了，队列只进不出+丢并发追加，见 _mes_truncate_gov。
#     2026-11-02 strip 撕裂环收口：拉回改字节精确（shb 不 strip），consumed=实读字节，
#     空白残渣轮也推进边界——此前 strip() 使边界恒短于真实前缘，每事件漏一个尾部 "}"
#     入隔离件、gov 队列残留 1B "\n" 种子永不清零（11-01 方向修复不彻底处））
# 凭据解析复用 tools/otel/ch_client（单一真源；本件不接触任何口令）。
MES_QUEUE_GOV = "/opt/company/af-jobs/data/mes-events.jsonl"
MES_QUEUE_MAX_BYTES = 32 * 1024 * 1024   # 单轮拉回上限（门户长期掉线也不爆内存）
MES_QUEUE_BAD = os.path.join(WS, "状态观测/mes-queue-bad.jsonl")
MES_QUEUE_BAD_MAX_BYTES = 32 * 1024 * 1024   # 隔离件活件大小上限（E33 拦截③，2026-11-02）
MES_QUEUE_BAD_MAX_ARCHIVES = 2               # 超限轮转 .rot 归档保留份数（盘面硬上限≈(1+份数)×上限）
_MES_ALARM_DEDUP_S = 1800                # 补投失败告警去重窗（同 keepalive CHMES_DEDUP_S）
_last_mes_replay_alarm = 0.0


def _mes_occ_str(ms):
    """epoch 毫秒 → UTC 时刻串（毫秒精度）。不用本地墙钟串：pandev 本地时间写 UTC 列
    会有 +8h 漂移（keepalive/sched 现网即此口径；order-cli/af-mes 写的是真 UTC 即时），
    队列行自带 occurred_at_ms 权威时刻，回投以它为准。"""
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%F %T.%f")[:23]


def _mes_insert(events):
    """INSERT af_mes.mes_event 七列显式清单 JSONEachRow（keepalive/sched 同口径）。
    失败抛异常由调用方处置（不截断队列）。"""
    body = "".join(json.dumps({
        "work_order_id": e["work_order_id"],
        "occurred_at": _mes_occ_str(int(e["occurred_at_ms"])),
        "event_id": e["event_id"],
        "line_id": e.get("line_id", "af-jobs"),
        "station_id": e.get("station_id", "portal"),
        "kind": e["kind"],
        "quantity": int(e.get("quantity", 1)),
    }, ensure_ascii=False) + "\n" for e in events)
    base, auth = ch_client.resolve()
    req = urllib.request.Request(
        base + "/?query=" + urllib.parse.quote(
            "INSERT INTO af_mes.mes_event (work_order_id, occurred_at, event_id, "
            "line_id, station_id, kind, quantity) FORMAT JSONEachRow"),
        data=body.encode(), method="POST")
    if auth:
        req.add_header("Authorization", auth)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def _mes_quarantine_rotate(cur_bytes):
    """隔离件超限轮转（E33 拦截③，2026-11-02 收口）：活件改名时间戳 .rot 归档 +
    amber 告警（公开面只报字节数/份数，H3 细节进 status-push.log）；归档超
    MES_QUEUE_BAD_MAX_ARCHIVES 份删最旧（最旧让位以告警在案为前提，非静默丢弃）。
    归档名定宽 ms 尾（字典序=时间序），同毫秒轮转 while 兜底不覆盖前份。"""
    ms = int(time.time() * 1000) % 1000
    arch = f"{MES_QUEUE_BAD}.{time.strftime('%Y%m%d-%H%M%S')}-{ms:03d}.rot"
    while os.path.exists(arch):
        ms = (ms + 1) % 1000
        arch = f"{MES_QUEUE_BAD}.{time.strftime('%Y%m%d-%H%M%S')}-{ms:03d}.rot"
    try:
        os.replace(MES_QUEUE_BAD, arch)
        _alarm("amber", "mes-quarantine",
               f"MES 坏行隔离件超限轮转：{cur_bytes}B 活件已归档（隔离继续，"
               f"上限 {MES_QUEUE_BAD_MAX_BYTES}B，归档保 {MES_QUEUE_BAD_MAX_ARCHIVES} 份）")
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 隔离件超限轮转："
              f"{cur_bytes}B → {arch}（amber 已告警）", flush=True)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 隔离件轮转失败（原地继续追加）: {e}",
              flush=True)
    try:
        rots = sorted(glob.glob(MES_QUEUE_BAD + ".*.rot"))
        if MES_QUEUE_BAD_MAX_ARCHIVES > 0:
            for old in rots[:-MES_QUEUE_BAD_MAX_ARCHIVES]:
                os.remove(old)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 隔离件归档清理失败: {e}", flush=True)


def _mes_quarantine(raw_lines):
    """坏行原样入本地隔离件（不静默丢弃；供人工补录/诊断）。

    E33 拦截③（2026-11-02 收口）：写入前做大小上限检查——活件将超
    MES_QUEUE_BAD_MAX_BYTES 即先轮转（_mes_quarantine_rotate：改名 .rot 归档 +
    amber 告警），活件恒有界。原实现无上限：73 条坏行 ×每轮重写 62h+ 涨到
    ~203MB/22.5 万行（99.9%+ 为同一批粘连行重复），无任何告警钩子。"""
    try:
        os.makedirs(os.path.dirname(MES_QUEUE_BAD), exist_ok=True)
        body = "".join(ln.rstrip("\n") + "\n" for ln in raw_lines)
        try:
            cur = os.path.getsize(MES_QUEUE_BAD)
        except OSError:
            cur = 0
        if cur + len(body.encode()) > MES_QUEUE_BAD_MAX_BYTES:
            _mes_quarantine_rotate(cur)
        with open(MES_QUEUE_BAD, "a", encoding="utf-8") as f:
            f.write(body)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 坏行隔离件写入失败: {e}", flush=True)


def replay_mes_queue():
    """拉取 gov 门户 mes-events.jsonl 并批量补投 MES。返回本投递事件数（0=无待投/跳过）。

    失败一律抛异常（调用方记日志+告警，队列不截断=下轮重试=至少一次）。
    坏行隔离写在消费成功定局、截断前（失败轮不重写，防隔离件无界增长）。"""
    if ch_client is None:
        raise RuntimeError("ch_client 不在位（tools/otel/）——MES 队列补投跳过（队列保留）")

    size_s = sh(f"ssh {SSH_OPTS} {GOV} 'stat -c %s {MES_QUEUE_GOV} 2>/dev/null || true'", timeout=30)
    try:
        size = int(size_s.strip() or 0)
    except ValueError:
        size = 0
    if size <= 0:
        return 0
    if size > MES_QUEUE_MAX_BYTES:
        raise RuntimeError(f"门户 MES 队列过大（{size} B > {MES_QUEUE_MAX_BYTES} B）——本轮跳过，待人工处置")
    # 字节精确读（2026-11-02 strip 撕裂环收口）：不得走 sh().strip()——strip 后长度
    # 作消费边界恒短于真实前缘（尾 \n 与头部残渣被漏算），tail -c +(consumed+1)
    # 每轮留尾字节。
    raw = shb(f"ssh {SSH_OPTS} {GOV} 'cat {MES_QUEUE_GOV} 2>/dev/null || true'", timeout=60)
    if not raw.strip():
        # 空白轮（含历史撕裂轮遗留的孤立 "\n" 种子）也推进消费边界再退出：
        # 可投事件为零，但残渣不清则队列永不清零、每轮白跑 stat+cat。
        _mes_truncate_gov(len(raw))
        return 0
    nl = raw.rfind(b"\n")
    if nl != -1:
        # 消费边界对齐到行尾：cat 末尾截到的半行整体留给下轮（写入中的行不拆不粘）
        raw = raw[:nl + 1]
    lines = [l for l in raw.decode("utf-8", errors="replace").splitlines() if l.strip()]
    events, bad = [], []
    for l in lines:
        try:
            e = json.loads(l)
            if not isinstance(e, dict) or not e.get("event_id") or not e.get("kind") \
                    or not e.get("work_order_id") or "occurred_at_ms" not in e:
                raise ValueError("缺必填字段")
            events.append(e)
        except Exception:
            bad.append(l)
    if events:
        # 幂等预查走 POST 体分批（ch_client.query_post，2026-11-01 收口）。单条 SQL 两道
        # 闸，实测（全队列 6,577 个 id、SQL 528,616B）：
        #   · GET 通道：查询串超 HTTP 表单字段上限 → HTTP 500 Poco "HTML Form Exception:
        #     Field value too long"——失败轮=队列保留=下轮原样重投，在此是永久死循环
        #     （2026-10-31 18:52 起 62h+：队列只进不出，CH af-jobs 行停在 10-29）。
        #   · POST 体：仍受服务端 max_query_size=262,144 解析上限 → HTTP 400 "Max query
        #     size exceeded"。故按字节预算切 ~200KB/条（上限内留裕量），批间合并去重集。
        prefix = "SELECT event_id FROM af_mes.mes_event WHERE event_id IN ("
        quoted = ["'" + e["event_id"].replace("'", "''") + "'" for e in events]
        batches, cur, curlen = [], [], len(prefix) + 1
        for q in quoted:
            if cur and curlen + len(q) + 1 > 200_000:
                batches.append(",".join(cur))
                cur, curlen = [], len(prefix) + 1
            cur.append(q)
            curlen += len(q) + 1
        if cur:
            batches.append(",".join(cur))
        existing = set()
        for b in batches:
            existing |= {r.get("event_id") for r in ch_client.query_post(prefix + b + ")")}
        fresh = [e for e in events if e["event_id"] not in existing]
        if fresh:
            _mes_insert(fresh)
        n = len(fresh)
    else:
        # 全是坏行：也已消费（隔离在案），照常走截断
        n = 0
    if bad:
        # 隔离写挪到「本轮消费成功定局、截断前」：失败轮（补投异常→队列保留重试）不再
        # 反复重写同一批坏行——原「解析即隔离」在死循环期每轮 +73 行，隔离件 62h+
        # 无界涨到 ~196MB/22 万行（同一 73 条 ×~3k 轮）。截断前落盘=不静默丢弃语义不变。
        _mes_quarantine(bad)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 队列坏行 {len(bad)} 条已隔离"
              f"（不静默丢弃）→ {MES_QUEUE_BAD}", flush=True)
    _mes_truncate_gov(len(raw))   # raw 已是字节串：len 即消费字节数（撕裂环收口）
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 队列补投 {n} 笔"
          f"（拉回 {len(events)} 条，去重跳过 {len(events) - n}，坏行隔离 {len(bad)}）", flush=True)
    return n


def _mes_truncate_gov(consumed_bytes):
    """按消费字节数消费 gov 队列前缀（2026-11-01 修复版）。

    原实现 `truncate -s consumed` 方向反了：truncate 保留的是前缀 [0,consumed)=已消费
    的旧行，丢的是尾部=轮内新追加的未消费行——队列只进不出（62h 死循环的第二根因，
    且每"成功"轮还在静默丢弃并发追加）。改为：tail 取未消费后缀入临时件 + 原子 mv 换名
    （门户 mes_event 每笔独立 open("a") 追加，无长持 fd，换名安全——af-jobs-portal.py
    mes_event()）。尺寸守卫保留：当前尺寸 < 消费量说明文件被外部重置，不换名。"""
    sh(f"ssh {SSH_OPTS} {GOV} 'test -f {MES_QUEUE_GOV} && "
       f"[ $(stat -c %s {MES_QUEUE_GOV}) -ge {consumed_bytes} ] && "
       f"tail -c +$(( {consumed_bytes} + 1 )) {MES_QUEUE_GOV} > {MES_QUEUE_GOV}.tmp && "
       f"mv {MES_QUEUE_GOV}.tmp {MES_QUEUE_GOV} || true'", timeout=30)


def _gate_ok(stage):
    """发布前脱敏闸（V 线收尾）。fail-closed：非零退出/超时/异常一律视为红。
    命中明细（文件:行+模式+值前4字符+长度）只进本地 status-push.log。

    键集冻结旗标 --freeze-keys（2026-11-03 publish-sc 批接入）：此前本调用只带
    --json，键集冻结（quota/data 顶层+子段键集，超集即拦）只存在于闸自身的
    --freeze-keys 旗标上 ⇒ 该控制在在役发布链上结构性不可达＝死开关（治理器
    quota-governor 新加字段直上公网，无人拦；设计正本 publish-gate.md §1.3 明定
    键集冻结是「未审字段漂移进公网」的唯一控制）。现挂上旗标：漂移即拦→本轮不推
    （fail-closed 停更不停线，gov 保留上一版），人工审后更新闸常量放行。"""
    try:
        r = subprocess.run([sys.executable, GATE, stage, "--json", "--freeze-keys"],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] vgate 闸执行失败（按红处置）: {e}",
              flush=True)
        _alarm("red", "publish-gate", "脱敏闸执行失败——本轮看板不推送（gov 保留上一版）")
        return False
    if r.returncode == 0:
        return True
    detail = ""
    try:
        d = json.loads(r.stdout)
        detail = (f"命中 {len(d.get('hits', []))} 项 {d.get('tally', {})}；"
                  f"结构 {len(d.get('errors', []))} 项；豁免 {d.get('allowlisted', 0)} 项")
        for h in d.get("hits", [])[:20]:
            detail += f"\n  HIT {h['file']}:{h['line']} {h['pattern']} 值特征={h['preview']}***[len={h['len']}]"
        for e in d.get("errors", [])[:10]:
            detail += f"\n  STRUCT {e}"
    except Exception:
        detail = f"闸输出解析失败 rc={r.returncode}"
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] vgate 闸红，跳过本轮推送（不发布）:\n{detail}",
          flush=True)
    _alarm("red", "publish-gate", "脱敏闸拦下看板推送——本轮不发布（gov 保留上一版）")
    return False


def push_board():
    """v2 数据面：anolis 流式 json 拉回本机与本地 F 系列合流 → orders.json/quota/data/stream 推 gov。
    推送前过脱敏闸（_gate_ok）：闸红返回 None（本轮不推送，gov 保留上一版）。

    订单可见性工单②（2026-10-29）：先跑 order-stages.py 刷新 stages.json（每单阶段/轮次/
    当前动作），随暂存树一并过闸并推 gov static/v2/stages.json；采集失败则本轮不带 stages
    （gov 保留上一版，停更不停线）。"""
    anolis_stream = "/tmp/af-board-stream"
    local_stream = os.path.join(WS, "状态/看板/stream")
    subprocess.run(f"rsync -a --timeout=40 -e 'ssh {SSH_OPTS}' anolis:/data/bench/af-board/stream/ {anolis_stream}/",
                   shell=True, capture_output=True, timeout=60)
    dirs = [d for d in (anolis_stream, local_stream) if os.path.isdir(d)]
    # RT-E112 数据面腿（2026-11-02）：stages 先采集再建 orders——terminal.reward/stage
    # 合流吃本轮新鲜判官真值（原先 orders 先建、stages 后采，合流会落后一轮）。
    stages_src = build_stages()
    json.dump(build_orders_json(dirs, STAGES), open("/tmp/orders.json", "w"), ensure_ascii=False)
    stage = _stage_board(dirs, stages_src)
    if not _gate_ok(stage):
        return None
    sh(f"ssh {SSH_OPTS} {GOV} 'mkdir -p /opt/company/af-jobs/data/static/v2/stream /opt/company/af-jobs/data/static/v2/stream-demo'", timeout=30)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                    os.path.join(stage, "orders.json"),
                    f"{GOV}:/opt/company/af-jobs/data/static/v2/orders.json"], timeout=30)
    # 账本一致批·RT-E112 数据面附带腿（2026-11-02）：本地看板 v2/orders.json 每轮镜像
    # 发布面正本（gate 过闸后的 staging 件，原子落位）。背景：该位此前是 10-28
    # build-orders.py 手工孤件（15 单、S4 手采 terminal 富字段，写者零调度），与公网
    # 现生管线两套键名体制——本地 8790 板（文档根=状态/看板，v2/index.html fetch
    # ("./orders.json")）与公网板呈现两套订单面（otel-sidecar.json 同批先例：
    # 本地可达路径必须与真值源同源，且本地副本保持过闸后发布面形）。镜像失败不致命，
    # 不影响推送主职。回滚：删本块 + 还原 orders.json.20261102-pre-RT-E112orders.bak。
    try:
        local_orders = os.path.join(WS, "状态/看板/v2/orders.json")
        tmp_orders = local_orders + ".tmp"
        shutil.copy2(os.path.join(stage, "orders.json"), tmp_orders)
        os.replace(tmp_orders, local_orders)
    except OSError as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] orders.json 本地镜像失败（不影响推送）: {e}",
              flush=True)
    for rel in ("quota.json", "data.json"):
        src = os.path.join(stage, rel)
        if os.path.isfile(src):
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            src, f"{GOV}:/opt/company/af-jobs/data/static/{rel}"], timeout=30)
    # 订单可见性工单②：stages.json → gov static/v2/stages.json（看板"进行中订单"区 30s 拉取）
    if os.path.isfile(os.path.join(stage, "stages.json")):
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        os.path.join(stage, "stages.json"),
                        f"{GOV}:/opt/company/af-jobs/data/static/v2/stages.json"], timeout=30)
    # DEB-2d：otel-sidecar.json → gov static/v2/otel-sidecar.json（看板 v2"OTel 指标"区
    # 30s 拉取；沿 stages.json 同款路径；暂存树里是发布面脱敏副本，见 _stage_otel_sidecar）
    if os.path.isfile(os.path.join(stage, "otel-sidecar.json")):
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        os.path.join(stage, "otel-sidecar.json"),
                        f"{GOV}:/opt/company/af-jobs/data/static/v2/otel-sidecar.json"], timeout=30)
    # P0-3（2026-10-28）：stream rsync 加 --delete——退役 run 的 json 在 gov 侧清理
    # （staging 已排除点开头文件，.tailer-state.json 等游标件不再上公网；删除面=镜像
    # staging/stream 的精确内容，gov static/v2/stream/ 只可能是当前 json）
    subprocess.run(f"rsync -a --timeout=50 --delete -e 'ssh {SSH_OPTS}' {stage}/stream/ "
                   f"{GOV}:/opt/company/af-jobs/data/static/v2/stream/",
                   shell=True, capture_output=True, timeout=90)
    return sum(1 for _ in glob.glob(os.path.join(dirs[0], "*.json"))) if dirs else 0


def main():
    global _last_mes_replay_alarm
    while True:
        try:
            snap = build()
            json.dump(snap, open(TMP, "w"), ensure_ascii=False, indent=1)
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", TMP,
                            f"{GOV}:/opt/company/af-jobs/data/factory.json"], timeout=30)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] pushed ts={snap.get('ts')} "
                  f"factory={'ok' if 'error' not in snap.get('factory', {}) else 'error'}", flush=True)
        except Exception as e:
            print("push error:", e, flush=True)
        try:
            # 配额闸下发（burn-runner fail-closed 消费）：step 过期或剩量触底即 step_ok=false
            # 2026-10-30 通道化：step_ok 只管 step 系订单；mm_ok 管 mavis 系订单——
            # burn-runner 按条目 profile 前缀选闸（step 已退役后 mavis 道不连坐）。
            # 2026-11-03（配额闸两侧对账修复）：mm_ok 判据/阈值不再就地硬编码，改为
            # mm_gate_ok(mq)——阈值取自派发侧唯一事实源 tools/quota-governor.py
            # （MM_HOLD_FLOOR_PCT / MM_WEEKLY_HOLD_FLOOR_PCT），判据与派发侧 minimax.go
            # 恒等。此前两套阈值（派发 8/8 vs 执行 15/20）各判各的 → 同一份 quota.json
            # 在分歧带内得出相反裁决（派发写单 / 执行拒单留队 → 队列积压不可执行条目）。
            # 2026-11-03（OBS 回头·派生闸新鲜度）：闸改由 derive_gate(q) 派生——除既有
            # step_ok/mm_ok 判据外，携带源读数 ts/年龄/是否陈旧（src_ts/src_age_s/src_stale），
            # 源读数陈旧（或无 ts）即闸自身 fail-closed：不再把停写前的旧裁决下发到执行侧
            # （burn-runner 的 10min 门此前只看闸自身年龄，对源停写完全失明）。
            q = json.load(open(os.path.join(WS, "状态观测/quota.json")))
            gate = derive_gate(q)
            json.dump(gate, open("/tmp/gate.json", "w"), ensure_ascii=False)
            subprocess.run(f"ssh {SSH_OPTS} anolis 'mkdir -p /data/bench/queue/pending /data/bench/queue/done /data/bench/queue/failed' && scp -q -o BatchMode=yes -o ConnectTimeout=10 /tmp/gate.json anolis:/data/bench/queue/gate.json",
                           shell=True, capture_output=True, timeout=30)
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] gate 下发失败: {e}", flush=True)
        try:
            nstreams = push_board()
            if nstreams is None:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] board 本轮被脱敏闸拦下（gov 保留上一版，停更不停线）", flush=True)
            else:
                stg = "有" if os.path.isfile(STAGES) else "无"
                otl = "有" if os.path.isfile(OTEL_SIDECAR) else "无"
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] board pushed "
                      f"(anolis streams={nstreams}, stages={stg}, otel={otl})", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] board push 失败: {e}", flush=True)
        try:
            # MES 记账队列补投（C5 收口）：失败不截断 gov 队列=下轮重试（至少一次）
            n = replay_mes_queue()
            if n:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] mes-queue: 补投 {n} 笔", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MES 队列补投失败（队列保留，下轮重试）: {e}",
                  flush=True)
            now = time.time()
            if now - _last_mes_replay_alarm > _MES_ALARM_DEDUP_S:
                _last_mes_replay_alarm = now
                _alarm("red", "mes-queue-replay", "MES 队列补投失败——门户记账事件未入 MES（队列保留待重试）")
        time.sleep(60)


if __name__ == "__main__":
    main()
