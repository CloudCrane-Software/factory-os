#!/usr/bin/env python3
"""burn-runner — 补货器（P3-8，运营者编排层指令阶段 1）

队列驱动的工厂订单补给守护（anolis 常驻）：在途 af-order 低于槽位且闸门放行时，
从 /data/bench/queue/pending/ 弹出下一条目提交。机械补货，不等主会话。

队列条目 schema（pending/*.json，文件名序=优先级）：
  {unit: "swev"|"report", task, data_root, profile, max_turns, spend_cap, note, dedupe_key}
护栏：
  - STOP 文件（/data/bench/queue/STOP）存在即全局熔断；
  - gate.json（本机推送器 60s 更新）step_ok=false 或缺失/过期>10min 即停（fail-closed）；
    2026-11-03：闸须携带源读数 ts（src_ts）——源 quota.json 停写时闸自身恒新鲜，
    故另判源读数年龄（>600s 即拒单），否则执行侧会对停写前的旧配额裁决照旧下单；
  - 队列深度上限 300；每轮最多补 3 单（防惊群）；
  - dedupe_key 落 submitted.jsonl 防重；提交即死（OR1001 类秒败）移 failed/。
双道预留：条目可带 lane/profile（minimax 溢出道待 provider profile 接线后启用）。
回滚：停进程 + 删 /data/bench/queue/。"""
import json
import os
import subprocess
import time
import glob

Q = "/data/bench/queue"
PENDING = Q + "/pending"
DONE = Q + "/done"
FAILED = Q + "/failed"
STOP = Q + "/STOP"
GATE = Q + "/gate.json"
COUNTER = Q + "/counter"
SUBMITTED = Q + "/submitted.jsonl"
SLOTS = 8
INTERVAL = 25
GATE_STALE_S = 600
# 源读数（状态观测/quota.json 的 ts）陈旧阈——与 factory-scheduler QUOTA_STALE、
# status-push QUOTA_SRC_STALE_S 同值（keepalive 判活阈亦同值）；同一环境变量
# FS_QUOTA_STALE_S 可统一调。
SRC_STALE_S = 600
QUEUE_CAP = 300
PER_CYCLE = 3
AF = "/data/af-factory/target-p3/debug/af-order"
STATE = "/data/bench/af-p3-state"

# ---------- 投放闸（PoC-B 2026-11-03 影子接线）----------
# af-release-gate bin（CONWIP 水位闸，WIP 单位=WorkOrder，权重首版全 1=计件模式）。
# 闸门只管"在制水位"；gate.json 通道闸（供给配额）保留不动——两把尺正交。
# RG_MODE 影子期=shadow（只记不裁：与 SLOTS 判定并行对照，差异写 shadow-compare.jsonl）；
# 对照≥30min 一致后才可切 enforce（AtCapacity→本轮跳过）。切换纪律：.bak+变更日志+可回滚
# （回滚=把 MODE 文件写回 shadow 或删本段）。
RG = "/data/bench/release-gate/release-gate"
RG_DB = "/data/bench/release-gate/gate.db"
RG_CFG = "burn-runner-admit@3/0"   # 与 serve 渐放键一致（机制5：探针封顶+谓词晋升）
RG_MODE_FILE = "/data/bench/release-gate/MODE"
RG_COMPARE = "/data/bench/release-gate/shadow-compare.jsonl"
RG_ORDERS = "/data/bench/af-p3-state/orders"
RG_TRACK = "/data/bench/release-gate/track.json"


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


SRC_STALE_S = _env_int("FS_QUOTA_STALE_S", SRC_STALE_S)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def inflight():
    r = subprocess.run("pgrep -c af-order; true", shell=True, capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if ln.isdigit():
            return int(ln)
    return 0


def rg_mode():
    """shadow（缺省，只记不裁）| enforce（AtCapacity 本轮跳过）。文件读失败按 shadow。"""
    try:
        return open(RG_MODE_FILE).read().strip() or "shadow"
    except Exception:
        return "shadow"


def rg_call(argv, timeout=15):
    """调 release-gate bin。返回 (rc, stdout)。闸不在位/超时 → (None, "")，绝不抛。"""
    try:
        r = subprocess.run([RG, "--db", RG_DB] + argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        log(f"release-gate 调用失败（fail-open 按无闸处理）: {type(e).__name__}")
        return None, ""


def rg_compare(rec):
    """影子对照一行（两套判定是否一致，差异逐条登记在这里）。"""
    rec["ts"] = time.time()
    try:
        with open(RG_COMPARE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def rg_status():
    rc, out = rg_call(["status"])
    if rc != 0:
        return None
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return None


def rg_capacity_leg(n):
    """容量腿对照：SLOTS 判定（n<8 可投）vs 闸判定（wip+1<=upper 可投）。"""
    st = rg_status()
    if st is None:
        return
    slots_allow = n < SLOTS
    gate_allow = st["wip_minutes"] + 1.0 <= st["wip_upper_minutes"] + 1e-9
    rg_compare({"kind": "capacity", "inflight": n, "slots_verdict": "allow" if slots_allow else "full",
                "gate_decision": "would_admit" if gate_allow else "at_capacity",
                "gate_wip": st["wip_minutes"], "gate_upper": st["wip_upper_minutes"],
                "gate_items": st["in_process_count"], "match": slots_allow == gate_allow})


def rg_admit_shadow(spec_oid, n):
    """提交腿对照（影子）：先记 SLOTS 已允许提交的事实，问闸 decision 并照实入账。"""
    rc, out = rg_call(["admit", "--order-id", spec_oid, "--weight", "1",
                       "--config", RG_CFG, "--shadow", "--note", f"slots_allow(n={n})"])
    if rc is None:
        return None
    try:
        rec = json.loads(out.splitlines()[-1]) if out else {}
    except Exception:
        rec = {"decision": "parse_error", "raw": out[:200]}
    dec = rec.get("decision", "unknown")
    rg_compare({"kind": "submit", "order_id": spec_oid, "inflight": n,
                "slots_verdict": "allow", "gate_decision": dec,
                "shadow_forced": bool(rec.get("shadow_forced")), "match": dec == "admit"})
    return rec


def rg_settle(spec_oid, defects=None, cancelled=False):
    """进程退出释容：defects 接 results.jsonl 质量位（reward=false→1）；无结果按取消。"""
    argv = ["complete", "--order-id", spec_oid, "--note", "burn-runner-exit"]
    if cancelled:
        argv.append("--cancelled")
    else:
        argv += ["--defects", str(defects if defects is not None else 1)]
    rg_call(argv, timeout=15)


def rg_quality(spec_oid):
    """读订单 results.jsonl 质量位：末行 reward=true→0 缺陷；false→1；读不到→None。"""
    try:
        lines = [l for l in open(f"{RG_ORDERS}/{spec_oid}/results.jsonl") if l.strip()]
        last = json.loads(lines[-1])
        return 0 if last.get("reward") is True else 1
    except Exception:
        return None


def rg_track_load():
    try:
        return json.load(open(RG_TRACK))
    except Exception:
        return {}


def rg_track_save(t):
    try:
        json.dump(t, open(RG_TRACK, "w"))
    except Exception:
        pass


def rg_sweep(track):
    """扫一遍在跟踪的进程：退出的补 settle（幂等，serve 对账兜底）。"""
    for spec_oid, pid in list(track.items()):
        alive = subprocess.run(f"ps -p {pid} -o pid= | wc -l", shell=True,
                               capture_output=True, text=True).stdout.strip() != "0"
        if alive:
            continue
        del track[spec_oid]
        q = rg_quality(spec_oid)
        if q is None:
            rg_settle(spec_oid, cancelled=True)   # 无结果文件（秒败/被杀）→ 取消账
        else:
            rg_settle(spec_oid, defects=q)
    rg_track_save(track)


def gate_source_age(g):
    """闸携带的**源读数**年龄（秒）。无 src_ts（老闸格式/未携带源读数）→ None。

    2026-11-03（OBS 回头·派生闸新鲜度）：派生闸此前只带「自身写入时刻」(updated)，
    不携带源 quota.json 的 ts——本函数消费 tools/factory-status-push.py:derive_gate()
    新增的 src_ts/src_age_s 字段，使执行侧能独立判断源读数新鲜度（不再只能信
    「闸文件自身 mtime 新鲜」）。"""
    ts = (g or {}).get("src_ts")
    if not ts:
        return None
    return max(0, int((time.time() * 1000 - ts) / 1000))


def gate_ok(profile=""):
    """fail-closed：闸文件缺失/过期一律不放行。
    2026-10-30 通道化（运营者令：烧量走 minimax）：按条目 profile 前缀选闸——
    mavis 系看 mm_ok（5h 窗>15% 且周窗>20%），step 系看 step_ok，未知前缀 fail-closed 全拒。
    老闸文件无 mm_ok 键时：mavis 单不冒险放行（等新闸），step 单按旧规则。
    2026-11-03（OBS 回头·派生闸新鲜度）：闸自身新鲜 ≠ 源读数新鲜——推送器每 60s
    覆写闸文件，源 quota.json 停写时闸恒新鲜而 mm_ok/step_ok 恒为停写前的旧裁决 →
    执行侧照旧按旧配额下单（撞限流形态），且与派发侧（源陈旧即停派）对同一源读数
    给出相反行为。故此处独立判源读数年龄：不可判（老闸无 src_ts）或超阈 → 一律拒单。"""
    try:
        st = os.stat(GATE)
        if time.time() - st.st_mtime > GATE_STALE_S:
            return False, "gate 过期(>10min)"
        g = json.load(open(GATE))
        age = gate_source_age(g)
        if age is None:
            return False, "闸拒: 闸无源读数 ts（老闸格式，等新闸下发）"
        if age > SRC_STALE_S:
            return False, f"闸拒: 源读数过期({age}s>{SRC_STALE_S}s)"
        p = (profile or "").strip()
        if p.startswith("glm"):
            # 2026-10-30 修正：glm-cp/glm-cp-max=智谱 CodingPlan（openBao 现取），
            # 非 step 套餐、无窗位语义——不设窗位闸，仅保留闸文件新鲜度 fail-closed。
            return True, ""
        if p.startswith("mavis"):
            if "mm_ok" not in g:
                return False, "闸拒: 老闸无 mm_ok 键（等新闸下发）"
            if not g.get("mm_ok"):
                return False, "闸拒: mm_ok=false（minimax 窗位不足）"
            return True, ""
        if not g.get("step_ok"):
            return False, f"闸拒: {g.get('reason', 'step_ok=false')}"
        return True, ""
    except FileNotFoundError:
        return False, "gate.json 缺失"
    except Exception as e:
        return False, f"gate 读失败: {e}"


def gate_any_ok():
    """前置粗闸（2026-10-30 通道化）：任一配额通道开放即过；全部关闭才拦。逐条目的
    精确通道匹配在 pop 后由 gate_ok(profile) 做——这里只是避免全队列空转的粗滤。
    2026-11-03（OBS 回头·派生闸新鲜度）：粗闸同样先判**源读数**年龄——源停写时闸
    自身恒新鲜，旧的「step_ok 或 mm_ok 任一开即过」会把停写前的旧裁决当活闸放行。"""
    try:
        st = os.stat(GATE)
        if time.time() - st.st_mtime > GATE_STALE_S:
            return False, "gate 过期(>10min)"
        g = json.load(open(GATE))
        age = gate_source_age(g)
        if age is None:
            return False, "闸拒: 闸无源读数 ts（老闸格式，等新闸下发）"
        if age > SRC_STALE_S:
            return False, f"闸拒: 源读数过期({age}s>{SRC_STALE_S}s)"
        if g.get("step_ok") or g.get("mm_ok"):
            return True, ""
        return False, "闸拒: step_ok 与 mm_ok 均关闭"
    except FileNotFoundError:
        return False, "gate.json 缺失"
    except Exception as e:
        return False, f"gate 读失败: {e}"


def next_order_id():
    n = 0
    try:
        n = int(open(COUNTER).read().strip())
    except Exception:
        pass
    n += 1
    open(COUNTER, "w").write(str(n))
    return f"A{n:04d}"


def known_dedupe_keys():
    keys = set()
    try:
        for line in open(SUBMITTED):
            try:
                keys.add(json.loads(line).get("dedupe_key"))
            except Exception:
                pass
    except FileNotFoundError:
        pass
    return keys


def pop_entries(need, seen_keys):
    """按文件名序弹出合法且未见过的条目，返回 [(path, entry)]。"""
    out = []
    for p in sorted(glob.glob(PENDING + "/*.json")):
        if len(out) >= need:
            break
        try:
            e = json.load(open(p))
        except Exception as ex:
            log(f"队列条目坏 JSON，移 failed/: {p} {ex}")
            os.rename(p, FAILED + "/" + os.path.basename(p))
            continue
        if not all(k in e for k in ("unit", "task", "data_root", "profile")):
            log(f"队列条目缺字段，移 failed/: {p}")
            os.rename(p, FAILED + "/" + os.path.basename(p))
            continue
        if e.get("dedupe_key") in seen_keys:
            os.rename(p, DONE + "/" + os.path.basename(p))
            continue
        out.append((p, e))
    return out


def submit(entry, oid):
    spec = {"order_id": f"{oid}-{entry['unit']}-{entry['profile']}",
            "line": {"line_id": "r0-step5", "line_version": "1"},
            "budget": entry.get("spend_cap", 300), "note": entry.get("note", "burn-runner")}
    spec_path = f"{STATE}/spec-{oid}.json"
    json.dump(spec, open(spec_path, "w"), ensure_ascii=False)
    argv = [AF, "submit", "--spec", spec_path, "--state", STATE,
            "--workspace", "/data/af-factory/af-p3", "--target-dir", "/data/af-factory/target-p3",
            "--task", entry["task"], "--profile", entry["profile"], "--data-root", entry["data_root"],
            "--host", "local", "--unit", entry["unit"], "--mes-ch", "auto"]
    if entry.get("max_turns"):
        argv += ["--max-turns", str(entry["max_turns"])]
    if entry.get("spend_cap"):
        argv += ["--spend-cap-cents", str(entry["spend_cap"])]
    logf = open(f"{STATE}/{oid}.log", "w")
    p = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT)
    time.sleep(4)  # 用法错（OR1001）会在数秒内退出
    if p.poll() not in (None,):
        return False, f"秒败 exit={p.returncode}（见 {oid}.log）", p.pid
    return True, "", p.pid


def main():
    for d in (PENDING, DONE, FAILED):
        os.makedirs(d, exist_ok=True)
    log(f"burn-runner 起：槽位={SLOTS} 周期={INTERVAL}s 队列={PENDING} 闸模式={rg_mode()}")
    idle = 0
    track = rg_track_load()
    while True:
        try:
            if os.path.exists(STOP):
                log("STOP 熔断在位，本轮跳过")
                time.sleep(INTERVAL)
                continue
            n = inflight()
            # PoC-B：退出进程补释容（在容量判定前，让闸账先追平现实）
            rg_sweep(track)
            # PoC-B：容量腿影子对照（SLOTS 判定 vs 闸判定，每轮一行）
            rg_capacity_leg(n)
            if n >= SLOTS:
                idle = 0
                time.sleep(INTERVAL)
                continue
            ok, why = gate_any_ok()
            if not ok:
                log(f"配额闸不放行：{why}（在途 {n} 跑完即止，不补）")
                time.sleep(INTERVAL)
                continue
            qdepth = len(glob.glob(PENDING + "/*.json"))
            if qdepth > QUEUE_CAP:
                log(f"队列深度 {qdepth}>{QUEUE_CAP} 超限熔断")
                time.sleep(INTERVAL)
                continue
            if qdepth == 0:
                idle += 1
                if idle % 20 == 1:
                    log(f"队列空（在途 {n}），等待路由器/种子补货")
                time.sleep(INTERVAL)
                continue
            need = min(SLOTS - n, PER_CYCLE)
            seen = known_dedupe_keys()
            for path, entry in pop_entries(need, seen):
                ok, why = gate_ok(entry.get("profile", ""))
                if not ok:
                    # pop_entries 不挪文件——留在 pending 原位，闸开即自动续（每轮重查）
                    log(f"条目闸拒（{entry.get('profile','?')}）：{why}（留队待闸开）")
                    continue
                oid = next_order_id()
                spec_oid = f"{oid}-{entry['unit']}-{entry['profile']}"
                if rg_mode() == "enforce":
                    # 正式裁权（影子一致后才切）：AtCapacity/未晋升 → 本轮跳过（条目留队）。
                    rc, out = rg_call(["admit", "--order-id", spec_oid, "--weight", "1",
                                       "--config", RG_CFG, "--note", f"enforce(n={n})"])
                    if rc == 3:
                        log(f"闸拒 AtCapacity（wip 满，{out[:120]}）：{spec_oid} 留队待释容")
                        continue
                    if rc == 7:
                        log(f"闸拒 渐放未晋升（{out[:120]}）：{spec_oid} 留队")
                        continue
                    if rc == 4:
                        log(f"闸拒 重复单（{out[:120]}）：{spec_oid} 跳过")
                        continue
                    if rc is None:
                        pass  # 闸不可用 fail-open：维持原行为（影子期已证一致后才切 enforce）
                else:
                    # 影子期：只记不裁，与 SLOTS 判定并行对照。
                    rg_admit_shadow(spec_oid, n)
                ok, err, pid = submit(entry, oid)
                if ok:
                    track[spec_oid] = pid
                    rg_track_save(track)
                else:
                    # 秒败：闸已按提交记账（影子/enforce 同）→ 立即取消释容，防在制虚高。
                    rg_settle(spec_oid, cancelled=True)
                with open(SUBMITTED, "a") as f:
                    f.write(json.dumps({"dedupe_key": entry.get("dedupe_key", path), "order_id": oid,
                                        "task": entry["task"], "unit": entry["unit"], "ts": time.time()},
                                       ensure_ascii=False) + "\n")
                os.rename(path, DONE + "/" + os.path.basename(path))
                log(f"补货 {oid}: unit={entry['unit']} task={entry['task']} "
                    f"turns={entry.get('max_turns')} {'OK' if ok else err}")
        except Exception as e:
            log(f"循环异常（不退出）: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
