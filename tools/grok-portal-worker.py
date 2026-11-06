#!/usr/bin/env python3
"""grok-portal-worker.py — grok 经 af-jobs 门户派发的值守工人（2026-11-02 运营者令：
grok 额度过期前烧量；grok 能否放进 af harness 派发——能，就是走 V2 沙箱门户当工人）。

拓扑
----
本机 = 备卡/机械校验/回报（复用 factory-kb-worker.py 全链：claim/heartbeat/card/
finalize/validate/post-report，证据缓存与 verify 正本都在本机 WS）。
anolis = 模型腿：卡面舞台 scp 过去（problem.md + 证据 + 机器复核真值），
`grok -p` headless 在舞台目录里自己 Read/Grep 证据、写 ./payload.json，
payload scp 回本机走 finalize-verify（机器真值覆写 fail-closed）→ validate →
不过就带问题清单回炉（≤2 轮）→ post-report。与改道批工作流同一门户协议、
同一收割校验链，收割方无感知。

启动/停止
--------
  python3 tools/grok-portal-worker.py --slot 1 --types kb-verify,kb-atoms
  触停：touch kb-seed/factory-worker/grok-stop   （每卡之间检查）
  自停：板面空 / MAX_CARDS 到 / grok 未登录（启动 ping 不过即拒开）

日志：kb-seed/factory-worker/grok-worker-<slot>.log（每卡一行 JSONL）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time

WS = os.path.expanduser("~/workspace/agent黑灯工厂")
HELPER = os.path.join(WS, "tools/factory-kb-worker.py")
WORKDIR = os.path.join(WS, "kb-seed/factory-worker")
STOP_FILE = os.path.join(WORKDIR, "grok-stop")
REMOTE_ROOT = "/data/af-factory/grok-portal"          # anolis 舞台根
GROK_BIN = "/home/pan-ding/.grok/bin/grok"
PROXY = "http://pandev-host.invalid:7890"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "anolis"]
SCP = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
MAX_CARDS = int(os.environ.get("GROK_MAX_CARDS", "60"))  # 单守护帽：跑完即收，主控连锁下一程
POLL_S = 90             # 板面空时轮询间隔
GROK_TIMEOUT_S = 1500   # 单卡 grok 硬帽 25min（verify 卡含 grep 活）
HEARTBEAT_S = 210       # 停收线 15min 的 1/4
REPAIR_ROUNDS = 2

KIND_LABEL = {"kb-verify": "kb-verify", "kb-atoms": "kb-atoms"}


def log(slot, obj):
    obj["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(WORKDIR, f"grok-worker-{slot}.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def helper(*args, timeout=300):
    """factory-kb-worker.py 子命令；退出码非 0 且 stdout 无 JSON 才算崩，否则回 stdout JSON。"""
    p = subprocess.run([sys.executable, HELPER, *args], capture_output=True, text=True,
                       timeout=timeout, cwd=WS)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "reason": f"helper 崩: rc={p.returncode} {p.stderr.strip()[:160]}"}


def ssh_run(cmd, timeout):
    p = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout + 30)
    return p.returncode, p.stdout, p.stderr


def extract_json(text):
    """从 grok 回复里抠最外层 {...}（payload.json 缺失时的备份通道）。"""
    start = text.find("{")
    while start != -1:
        depth, instr, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
            elif c == "\\":
                esc = True if instr else esc
            elif c == '"' and not instr:
                instr = True
            elif c == '"':
                instr = False
            elif not instr and c == "{":
                depth += 1
            elif not instr and c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


def grok_ping():
    """登录闸：headless 一次小请求，可判「未登录/代理断/额度死」。"""
    code, o, e = ssh_run(
        f"cd /tmp && HTTPS_PROXY={PROXY} HTTP_PROXY={PROXY} timeout 90 {GROK_BIN} "
        "-p 'Reply with exactly: OK' --output-format plain 2>&1 | tail -3", 100)
    return ("OK" in o), (o + e).strip()[-300:]


def stage_card(slot, card_id, info):
    """舞台落位：problem.md/证据/机器行 → anolis；回 (remote_dir, ev_desc, rows_desc)。"""
    local_dir = os.path.join(WORKDIR, f"stage-{slot}", card_id)
    os.makedirs(local_dir, exist_ok=True)
    ev_desc = []
    for name, v in (info.get("evidence", {}).get("files") or {}).items():
        if not v.get("ok"):
            continue
        with open(v["path"], encoding="utf-8", errors="replace") as f:
            body = f.read()
        with open(os.path.join(local_dir, name), "w", encoding="utf-8") as f:
            f.write(body)
        ev_desc.append({"path": f"./{name}", "len": v["len"], "sha256": v["sha256"]})
    if not ev_desc:
        return None, ev_desc, None
    rows = info.get("rows") or []
    remote_dir = f"{REMOTE_ROOT}/{slot}/{card_id}"
    code, o, e = ssh_run(f"rm -rf {remote_dir} && mkdir -p {remote_dir}", 60)
    if code != 0:
        return None, ev_desc, rows
    p = subprocess.run(SCP + ["-r", local_dir + "/.", f"anolis:{remote_dir}"],
                       capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        return None, ev_desc, rows
    return remote_dir, ev_desc, rows


def build_prompt(kind, card_id, problem_md, ev_desc, rows):
    ev = json.dumps(ev_desc, ensure_ascii=False)
    qc = json.dumps([{ "atom_id": r["atom_id"], "quote_check": r["quote_check"] }
                     for r in (rows or [])], ensure_ascii=False)
    if kind == "kb-verify":
        system = ("你是 agent 工厂知识生产线的独立验证员（B 位）：A 已抽取并上报原子且通过机器逐字验谎；"
                  "你逐条独立裁决，不重新抽取、不润色、不补全。只信你自己读到的证据文本；A 的结论与引文只是待检对象。"
                  "裁决只用 uphold/refute/unverifiable；unverifiable 不是免责通道（整份超过 2 条即整批未通过）；"
                  "quote_check 用任务数据里给出的机器复核真值，如实沿用，绝不全填 false 摆烂。拿不准就如实裁决并给证据理由。")
        task = (f"任务书（problem.md 原文，含待裁决原子表）：\n{problem_md}\n\n"
                f"证据文件（唯一证据源，已放在当前目录）：\n{ev}\n\n"
                f"机器逐字复核（A 的 quote 是否在证据中连续逐字出现，机械真值，照此填写 quote_check）：\n{qc}\n\n"
                "要求：\n"
                "1. 逐条裁决任务书表中的全部原子，一条不漏一条不多。先读 ./abs.md 全文；"
                "./full.md 若在，用搜索定位 A 记的 locator 与引文上下文，只读命中段落。\n"
                "2. verdict：uphold=证据支持且无过度断言；refute=与证据矛盾（数字不符/张冠李戴/把可能性写成结论/把单点写成普适）；"
                "unverifiable=证据不可得或不足（从严，整份 >2 条按未通过）。\n"
                "3. reason ≤80字，指认证据位置与依据；refute 必须点出具体矛盾。\n"
                f"4. 把 payload 写到 ./payload.json，固定 schema 不得增删字段：\n"
                f'{{"verify":true,"card_id":"{card_id}","verdicts":[{{"atom_id":"...","verdict":"uphold|refute|unverifiable",'
                '"quote_check":<机器复核值>,"reason":"..."}]}\n只写这一个文件。\n'
                "5. 最终回复：先一行 uphold/refute/unverifiable 计数，然后完整贴出 payload JSON 全文（备份通道）。")
    else:
        system = ("你是 agent 工厂知识生产线的论文原子抽取员。铁律：(1) 每条原子的 source.quote "
                  "必须是你真实读到的证据文件内容的连续逐字子串——不改写、不缩略、不翻译、不拼接、不凭记忆补写；"
                  "(2) 证据里没有的章节如实记 sections_missing，绝不编造论文内容；(3) 宁可少抽，绝不注水。"
                  "若证据完全不足以完成任务，如实说明并停下，绝不伪造完成。")
        task = (f"任务书（problem.md 原文）：\n{problem_md}\n\n"
                f"证据文件（唯一证据源，已放在当前目录，quote 必须是这些文件内容的连续逐字子串）：\n{ev}\n\n"
                "要求：\n"
                "1. 以固定抽取问题驱动检索：先读 ./abs.md 全文；./full.md 可达数十万字符，绝不整读——"
                "按问题关键词（方法/实验设置/结果数字/失败/局限等）定位章节，只读命中段落；"
                "quote 一律从你真实读到的文本逐字复制。abs.md 能答的优先用 abs.md。\n"
                "2. 抽 15-40 条原子（目标 20-30，宁缺毋滥），kind 只用词表六值，覆盖任务书固定抽取问题各面。\n"
                "3. 每条：text ≤60字一句话；source.file=该条引文所在文件（abs.md 或 full.md）；"
                "source.locator=节名/段落；source.quote=该文件中连续逐字出现的原文（≤120 字符，英文保持原样）；"
                "source.evidence_sha256=该文件 sha256（上面已给）；relations 只引用本报告内 atom_id。\n"
                "4. 把完整 payload JSON（任务书 schema：evidence.sources 列实际用到的文件+sha256、"
                "sections_missing、atoms）写到：./payload.json\n只写这一个文件。\n"
                "5. 最终回复：先一行（原子数、所用证据文件、missing 章节），不要贴整个 payload。")
    return system + "\n\n=== 任务 ===\n" + task


def run_grok(slot, card_id, prompt, remote_dir, round_no):
    """anolis headless 一跳；优先取 ./payload.json，缺则从回复抠 JSON。回 (payload|None, note)。"""
    prompt_remote = f"{remote_dir}/prompt-{round_no}.txt"
    p = subprocess.run(
        SCP + ["/dev/stdin", f"anolis:{prompt_remote}"], input=prompt.encode("utf-8"),
        capture_output=True, timeout=120)
    if p.returncode != 0:  # /dev/stdin 不行就本地中转
        lp = os.path.join(WORKDIR, f"stage-{slot}", card_id, f"prompt-{round_no}.txt")
        with open(lp, "w", encoding="utf-8") as f:
            f.write(prompt)
        p = subprocess.run(SCP + [lp, f"anolis:{prompt_remote}"],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            return None, f"prompt 上传失败: {p.stderr.strip()[:120]}"
    cmd = (f"cd {remote_dir} && HTTPS_PROXY={PROXY} HTTP_PROXY={PROXY} "
           f"timeout {GROK_TIMEOUT_S} {GROK_BIN} -p \"$(cat {prompt_remote})\" "
           f"--always-approve --output-format plain > reply-{round_no}.txt 2>&1; "
           f"echo RC=$?; ls -la payload.json 2>/dev/null")
    code, o, e = ssh_run(cmd, GROK_TIMEOUT_S + 120)
    if code != 0:
        return None, f"ssh 崩: {e.strip()[:120]}"
    _, reply, _ = ssh_run(f"cat {remote_dir}/reply-{round_no}.txt 2>/dev/null | tail -80", 60)
    rc = re.search(r"RC=(\d+)", o)
    if not os.path.isdir(os.path.join(WORKDIR, f"stage-{slot}", card_id)):
        os.makedirs(os.path.join(WORKDIR, f"stage-{slot}", card_id), exist_ok=True)
    lp = os.path.join(WORKDIR, f"stage-{slot}", card_id, "payload.json")
    pr = subprocess.run(SCP + [f"anolis:{remote_dir}/payload.json", lp],
                        capture_output=True, text=True, timeout=120)
    if pr.returncode == 0 and os.path.exists(lp):
        try:
            return json.load(open(lp, encoding="utf-8")), f"file(rc={rc.group(1) if rc else '?'})"
        except Exception as ex:
            return None, f"payload.json 损坏: {ex}"
    payload = extract_json(reply)
    if payload is not None:
        return payload, f"stdout-fallback(rc={rc.group(1) if rc else '?'})"
    return None, f"无 payload（rc={rc.group(1) if rc else '?'}）: {reply.strip()[-200:]}"


def process_card(slot, card, counters):
    card_id, kind = card["id"], card["kind"]
    t0 = time.time()
    c = helper("claim", card_id)
    if not c.get("ok"):
        log(slot, {"card": card_id, "outcome": "claim-denied", "detail": c.get("reason", "")})
        return False
    token = c["claim_token"]
    settled = threading.Event()
    miss = {"hb": 0}

    def hb_loop():
        while not settled.is_set():
            r = helper("heartbeat", token, "grok-portal working")
            if r.get("ok"):
                miss["hb"] = 0
            else:
                miss["hb"] += 1
                if miss["hb"] >= 2:  # 连续两口没续上就收摊（TTL 2h 还有缓冲，不硬等）
                    settled.set()
            settled.wait(HEARTBEAT_S)
    threading.Thread(target=hb_loop, daemon=True).start()

    def finish(outcome, detail):
        settled.set()
        log(slot, {"card": card_id, "kind": kind, "outcome": outcome,
                   "detail": detail[:400], "secs": round(time.time() - t0, 1)})
        counters[outcome] = counters.get(outcome, 0) + 1

    try:
        info = helper("card", card_id, timeout=300)
        if not info.get("ok"):
            finish("no-card", info.get("reason", "?"))
            return True
        remote_dir, ev_desc, rows = stage_card(slot, card_id, info)
        if remote_dir is None:
            finish("stage-failed", "舞台落位失败（scp/证据缺）")
            return True
        stage_local = os.path.join(WORKDIR, f"stage-{slot}", card_id)
        payload_path = os.path.join(stage_local, "payload.json")

        def attempt(round_no, repair_note=""):
            prompt = build_prompt(kind, card_id, info["problem_md"], ev_desc, rows)
            if repair_note:
                prompt += f"\n\n=== 回炉（第 {round_no} 轮）===\n{repair_note}"
            payload, note = run_grok(slot, card_id, prompt, remote_dir, round_no)
            if payload is None:
                return None, note
            with open(payload_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            return payload, note

        payload, note = attempt(1)
        if payload is None:
            finish("grok-empty", note)
            return True
        if kind == "kb-verify":
            fv = helper("finalize-verify", payload_path, card_id, timeout=300)
            if not fv.get("ok"):
                finish("finalize-fail", f"{fv.get('reason', '?')}（未全量覆写，不上门户）")
                return True
        v = helper("validate", kind, payload_path,
                   os.path.join(WS, "kb-seed/sandbox/evidence-cache", info.get("aid", "")),
                   card_id)
        for round_no in range(2, REPAIR_ROUNDS + 2):
            if v.get("ok"):
                break
            qc = json.dumps([{"atom_id": r["atom_id"], "quote_check": r["quote_check"]}
                             for r in (rows or [])], ensure_ascii=False)
            if kind == "kb-atoms":
                repair = (f"上一份 payload 预检未过。问题清单（机械校验输出）：\n{v.get('reason', '')}\n\n"
                          "处理：quote 回查 miss 的原子，优先把 quote 换成证据中真实连续出现的逐字原文，"
                          "否则删掉该原子；结构缺件（kind/locator/file/evidence_sha256/relations 悬空/"
                          "evidence.sources）逐项修复；其余原子不动。就地重写整个 ./payload.json（schema 同任务书）。")
            else:
                repair = (f"上一份裁决 payload 预检未过：{v.get('reason', '')}\n\n"
                          f'按固定 schema 就地重写 ./payload.json：verify:true、card_id="{card_id}"、'
                          f"verdicts 每条四字段齐全、quote_check 用机器复核值：\n{qc}\n裁决条数与任务书表一致。")
            payload, note = attempt(round_no, repair)
            if payload is None:
                finish("grok-empty", f"回炉{round_no}: {note}")
                return True
            if kind == "kb-verify":
                fv = helper("finalize-verify", payload_path, card_id, timeout=300)
                if not fv.get("ok"):
                    finish("finalize-fail", f"回炉{round_no}: {fv.get('reason', '?')}")
                    return True
            v = helper("validate", kind, payload_path,
                       os.path.join(WS, "kb-seed/sandbox/evidence-cache", info.get("aid", "")),
                       card_id)
        if not v.get("ok") and kind == "kb-atoms":
            fa = helper("finalize-atoms", payload_path,
                        os.path.join(WS, "kb-seed/sandbox/evidence-cache", info.get("aid", "")))
            if fa.get("ok") and fa.get("kept", 0) >= 10:
                v = helper("validate", kind, payload_path,
                           os.path.join(WS, "kb-seed/sandbox/evidence-cache", info.get("aid", "")),
                           card_id)
        if not v.get("ok"):
            finish("validate-fail", v.get("reason", "?"))
            return True
        pr = helper("post-report", token, payload_path)
        if pr.get("ok"):
            finish("reported", f"atoms={v.get('stats', {}).get('atoms', 0)} "
                               f"uphold={v.get('stats', {}).get('uphold', 0)} src={note}")
        else:
            finish("report-denied", json.dumps(pr.get("resp", {}), ensure_ascii=False)[:300])
        ssh_run(f"rm -rf {remote_dir}", 60)
        return True
    finally:
        settled.set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", required=True)
    ap.add_argument("--types", default="kb-verify,kb-atoms")
    args = ap.parse_args()
    os.makedirs(WORKDIR, exist_ok=True)
    if os.path.exists(STOP_FILE):
        log(args.slot, {"outcome": "stop-file-at-start"})
        return
    ok, note = grok_ping()
    if not ok:
        log(args.slot, {"outcome": "grok-not-ready", "detail": note})
        print(f"grok 登录闸未过（未授权/代理断）：{note}", file=sys.stderr)
        sys.exit(2)
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    counters, done, empty_since = {}, 0, 0.0
    log(args.slot, {"outcome": "worker-start", "types": types})
    while done < MAX_CARDS:
        if os.path.exists(STOP_FILE):
            log(args.slot, {"outcome": "stopped", **counters, "cards": done})
            return
        b = helper("board")
        if not b.get("ok"):
            time.sleep(POLL_S)
            continue
        pick = None
        for t in types:
            cands = [c for c in b.get("cards", []) if c["kind"] == t]
            if cands:
                pick = cands[0]
                break
        if pick is None:
            # 动态板面：router 会补卡、死 claim 会回池——瞬时空不当终局，
            # 连续 GROK_EMPTY_GRACE_S（默认 600s）真无卡才收（2026-11-02 14:11 事故）
            empty_since = empty_since or time.time()
            if time.time() - empty_since >= int(os.environ.get("GROK_EMPTY_GRACE_S", "600")):
                log(args.slot, {"outcome": "board-empty", **counters, "cards": done})
                return
            time.sleep(POLL_S)
            continue
        empty_since = 0.0
        if process_card(args.slot, pick, counters):
            done += 1
        time.sleep(3)
    log(args.slot, {"outcome": "max-cards-reached", **counters, "cards": done})


if __name__ == "__main__":
    main()
