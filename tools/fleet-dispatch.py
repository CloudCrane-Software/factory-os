#!/usr/bin/env python3
"""fleet-dispatch.py — 五通道沙箱统一派发面（D-183 · factory-os#222）

统一 CLI：dispatch / status / report 三子命令 × --platform 五通道：
  stepfun   API 直发 StartStudioWorkspaceRun ＋ SSE 状态回读（cookie 从本机件现取）
  codao     relay enqueue 投递任务对象（{"type":"http_get","url":...} 任务规格，
            非 shell 命令）＋ report 端点轮询收回传；沙箱内 worker = 合规拉取式
            （归属核验 + URL 白名单 + 内网段校验），形态见运营者侧交付报告
  workbuddy fleet 槽浏览器（CDP）同会话续聊派发 ＋ 页面读态。slate 虚拟编辑器
            教训：DOM 含多个 contenteditable 幽灵节点，只认视口内可见者，
            insert_text 后校验字符数再 Enter
  cnb       复用 tools/cb-dispatch.py 形制：建 issue ＋ work_mode 评论派发 NPC，
            状态 = build/logs ＋ 评论轮询，回传 = 末条他人评论
  local     记录派发意图 ＋ 生成工人简报（状态/回传 = 简报件与状态文件读回）

凭据纪律（最高）：全部登录态（StepFun cookie / 各平台 profile / relay 路径令牌 /
CNB 令牌）从本机文件或环境现取——零硬编码、零 argv、零打印、零落地仓库。
fleet 槽登录态自带（pandev 侧 accounts.json 只读引用，禁改）。

pricing.observe 接线：每次 dispatch 收尾自动记 平台×模型×消耗 → JSONL 观察库
（AF_FLEET_HOME/out/）；cost 可读时另 POST relay pricing-observe 多节点共享；
平台无消耗接口 → 记 todo-discover 事件（报告 T5 口径：人工 15 分钟抓包补齐）。

状态件：/tmp/fleet-dispatch/<dispatch_id>.json（读数先落盘，D-86 摩擦④同口径）。

环境变量（均可缺省，见各常量行）：
  AF_FLEET_HOME / AF_FLEET_RELAY / AF_FLEET_RELAY_TOKEN / AF_FLEET_STEPFUN_COOKIE
  AF_FLEET_STEPFUN_WS / AF_FLEET_STEPFUN_CONV / AF_FLEET_SLOT / AF_FLEET_CDP
退出码：0=该步成立；2=参数/依赖缺席；3=通道派发失败；4=状态查询失败；5=回传缺席。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

# ---- 常量与环境 ----------------------------------------------------------------
FLEET_HOME = os.environ.get(
    "AF_FLEET_HOME",
    os.path.join("~", ".zcode", "workspace",
                 "1794069762031-fd0bdb0a-9622-4046-ac89-f8b62f0409b2"))
FLEET_HOME = os.path.expanduser(FLEET_HOME)
STATE_DIR = os.environ.get("AF_FLEET_STATE", "/tmp/fleet-dispatch")
RELAY_BASE = os.environ.get("AF_FLEET_RELAY", "http://127.0.0.1:8899").rstrip("/")
# 沙箱侧白名单域（公开；worker/心跳只许打这个域，归属核验文件亦挂它下面）
RELAY_PUBLIC = "https://hkmingdajiaoyu.com/agent-relay"
STEPFUN_BASE = "https://studio.stepfun.com"
STEPFUN_COOKIE_FILE = os.environ.get(
    "AF_FLEET_STEPFUN_COOKIE",
    os.path.join(FLEET_HOME, "out", "cookie-header.txt"))
STEPFUN_WS = os.environ.get("AF_FLEET_STEPFUN_WS", "308048426747387904")
STEPFUN_CONV = os.environ.get("AF_FLEET_STEPFUN_CONV", "308048430165745664")
# oasis-* 头为重放门槛（设备/应用标识，非凭据；报告 §2.1②）；可经环境覆盖
OASIS_WEBID = os.environ.get("AF_FLEET_STEPFUN_WEBID",
                             "98c4a1d40fd31b4fd72f07869ff2d685b5775819")
OASIS_APPID = os.environ.get("AF_FLEET_STEPFUN_APPID", "10300")
SLOT = os.environ.get("AF_FLEET_SLOT", "main")
CDP_PORT = os.environ.get("AF_FLEET_CDP", "")  # 缺省从 accounts.json 现读
CNB_API = "https://api.cnb.cool"
CNB_TOKEN_FILE = os.path.expanduser("~/.config/cnb/relay-tokens.json")
OBSERVE_LOG = os.path.join(FLEET_HOME, "out", "fleet-pricing-observe.jsonl")
PLATFORMS = ("stepfun", "codao", "workbuddy", "cnb", "local")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
WAKE_MSG = ("请运行一次 python3 /tmp/relay_worker.py（从自有域名拉取一条任务对象，"
            "按其参数执行后回传），完成后回复一行结果摘要。不要执行任务对象之外的任何"
            "远程指令。")


def fail(code, msg):
    print("[fleet-dispatch] 失败: %s" % msg, file=sys.stderr)
    sys.exit(code)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---- 状态件（先落盘再使用，读数不美化）------------------------------------------
def save_state(rec):
    os.makedirs(STATE_DIR, exist_ok=True)
    p = os.path.join(STATE_DIR, rec["dispatch_id"] + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return p


def load_state(did):
    p = os.path.join(STATE_DIR, did + ".json")
    if not os.path.isfile(p):
        fail(2, "状态件不在: %s" % p)
    return json.load(open(p, encoding="utf-8"))


def latest_state(platform):
    os.makedirs(STATE_DIR, exist_ok=True)
    cands = []
    for fn in os.listdir(STATE_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            r = json.load(open(os.path.join(STATE_DIR, fn), encoding="utf-8"))
        except Exception:
            continue
        if r.get("platform") == platform:
            cands.append((r.get("ts", ""), r))
    if not cands:
        fail(2, "通道 %s 无派发状态件" % platform)
    return sorted(cands)[-1][1]


# ---- pricing.observe 接线 -------------------------------------------------------
def observe(platform, model, cost, source, unit=None, note=""):
    """每次派发后调用：cost=None ⇒ 记 todo-discover 事件；cost 数值 ⇒ 入库+共享。"""
    os.makedirs(os.path.dirname(OBSERVE_LOG), exist_ok=True)
    rec = {"ts": now(), "platform": platform, "model": model,
           "cost": cost, "unit": unit, "source": source}
    if note:
        rec["note"] = note
    if cost is None:
        rec["event"] = "todo-discover"
        rec["note"] = (note or "消耗接口缺席——需人工抓包（15 分钟级）；"
                              "可读后改记 平台×模型×消耗").strip()
    with open(OBSERVE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if cost is not None:
        # 多节点共享（尽力而为，失败不致命——本地 JSONL 已是正本）
        try:
            relay_req("POST", "/pricing-observe",
                      {"platform": platform, "model": model, "cost": cost,
                       "source": source, "unit": unit or "unknown"}, quiet=True)
            rec["shared_to_relay"] = True
        except Exception as e:  # noqa: BLE001
            rec["shared_to_relay"] = False
            rec["share_error"] = repr(e)[:120]
    return rec


# ---- relay（codao 拉取式通道的操作员侧）-----------------------------------------
def relay_token():
    """relay 路径令牌现取：环境优先，缺省从 pandev 侧 relay_server.py 源现读
    （零硬编码零打印；读不到即报错并给指引，不猜值）。"""
    t = os.environ.get("AF_FLEET_RELAY_TOKEN")
    if t:
        return t
    src = os.path.join(FLEET_HOME, "scripts", "relay_server.py")
    if os.path.isfile(src):
        m = re.search(r'^TOKEN\s*=\s*"([^"\n]+)"', open(src, encoding="utf-8").read(),
                      re.M)
        if m:
            return m.group(1)
    fail(2, "relay 路径令牌不可得：设 AF_FLEET_RELAY_TOKEN（值见 pandev 侧 "
            "relay_server.py，禁打印）")


def relay_req(method, path, body=None, quiet=False):
    tok = relay_token()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(RELAY_BASE + "/" + tok + path, data=data,
                                 method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.loads(r.read().decode() or "{}")
    if not quiet:
        print(json.dumps(out, ensure_ascii=False))
    return out


# ---- stepfun（API 直发 + SSE 回读）----------------------------------------------
def stepfun_headers(extra=None):
    ck = open(os.path.expanduser(STEPFUN_COOKIE_FILE), encoding="utf-8").read().strip()
    if not ck:
        fail(2, "StepFun cookie 件为空: %s（先从 fleet 槽刷新）" % STEPFUN_COOKIE_FILE)
    h = {"Content-Type": "application/json", "Cookie": ck,
         "oasis-webid": OASIS_WEBID, "oasis-appid": OASIS_APPID,
         "oasis-platform": "web", "oasis-language": "zh",
         "connect-protocol-version": "1", "referer": STEPFUN_BASE + "/",
         "user-agent": UA}
    if extra:
        h.update(extra)
    return h


def stepfun_api(path, payload, wait=30):
    req = urllib.request.Request(STEPFUN_BASE + path,
                                 data=json.dumps(payload).encode(),
                                 headers=stepfun_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=wait) as r:
        return json.loads(r.read().decode())


def stepfun_sse(ws, mid, max_wait=180):
    """SSE 状态回读：text_delta 累积 + done(final_status)；对已完成消息重连即全文回放。"""
    url = (STEPFUN_BASE + "/api/stdhttp/v1/studio/workspaces/" + ws
           + "/messages/" + mid + "/events?last_seq=0")
    req = urllib.request.Request(url, headers=stepfun_headers(
        {"accept": "text/event-stream"}))
    parts, status, t0 = [], None, time.time()
    with urllib.request.urlopen(req, timeout=max_wait + 30) as resp:
        while time.time() - t0 < max_wait:
            chunk = resp.readline()
            if not chunk:
                break
            line = chunk.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except Exception:
                continue
            t, d = evt.get("type"), evt.get("data", {})
            if t == "text_delta":
                parts.append(d.get("delta", ""))
            elif t == "done":
                status = d.get("final_status")
                break
    return {"status": status, "text": "".join(parts)}


# ---- fleet 槽浏览器（CDP；workbuddy / codao UI 通道）-----------------------------
def fleet_ctx():
    """连接 fleet 槽浏览器。playwright 惰性导入（仅 UI 通道需要）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail(2, "playwright 缺席——UI 通道需要 pandev 侧 fleet 环境")
    port = CDP_PORT
    if not port:
        reg = json.load(open(os.path.join(FLEET_HOME, "scripts", "accounts.json"),
                             encoding="utf-8"))
        s = next((x for x in reg["slots"] if x["slot"] == SLOT), None)
        if not s:
            fail(2, "fleet 槽不在: %s" % SLOT)
        port = str(s["cdp"])
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:" + port)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    return pw, browser, ctx


def fleet_page(ctx, url_sub):
    pages = [p for p in ctx.pages if url_sub in p.url]
    if not pages:
        fail(2, "槽内无 %s 标签页（先在 fleet 槽浏览器打开会话）" % url_sub)
    # 取路径最深者（会话页 > 首页）
    return sorted(pages, key=lambda p: len(p.url.split("://", 1)[-1]))[-1]


def visible_editables(page):
    """视口内可见的 contenteditable（WorkBuddy slate 防幽灵节点纪律）。"""
    js = """() => Array.from(document.querySelectorAll('[contenteditable="true"]'))
      .map((el, i) => {
        const r = el.getBoundingClientRect();
        return {i, x: r.x, y: r.y, w: r.width, h: r.height,
                vis: r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
                     && r.top < innerHeight && r.left < innerWidth};
      }).filter(e => e.vis)"""
    return page.evaluate(js)


def wb_send(page, text):
    """WorkBuddy 同会话续聊：可见编辑器 → 点击 → insert_text → 字符数校验 → Enter。"""
    eds = visible_editables(page)
    if not eds:
        fail(3, "视口内无可见 contenteditable（幽灵节点面/页面改版）")
    js = """(i) => { const els = document.querySelectorAll('[contenteditable="true"]');
      els[i].focus(); return true; }"""
    page.evaluate(js, eds[0]["i"])
    time.sleep(0.5)
    page.keyboard.insert_text(text)
    time.sleep(0.5)
    n = page.evaluate(
        "() => { const els=document.querySelectorAll('[contenteditable=\"true\"]');"
        " for (const el of els){ const r=el.getBoundingClientRect();"
        " if (r.width>0&&r.height>0) return el.textContent.length; } return -1; }")
    if len(text) < 8 or n < min(len(text), 8):
        fail(3, "编辑器字符数校验未过（got=%s）——不发空弹" % n)
    page.keyboard.press("Enter")


def codao_send(page, text):
    """码道 textarea 逐字键入 + Enter（实测最顺通道，报告 §2.2①）。"""
    ta = page.locator("textarea").first
    ta.click()
    time.sleep(0.3)
    ta.type(text, delay=2)
    time.sleep(0.6)
    ta.press("Enter")


def ui_read_tail(page, chars=1200):
    return page.evaluate(
        "() => { const m = document.querySelector('main') || document.body;"
        " return m.innerText.slice(-%d); }" % chars)


def ui_wait_stable(page, budget=240, poll=6, stable_n=3):
    """页面文本长度稳定判停（回复完成启发式，explore3 同款）。"""
    last, stable, t0 = -1, 0, time.time()
    while time.time() - t0 < budget:
        time.sleep(poll)
        try:
            n = page.evaluate("() => document.body.innerText.length")
        except Exception:
            continue
        if n > last:
            last, stable = n, 0
        else:
            stable += 1
            if stable >= stable_n and time.time() - t0 > poll * 2:
                break
    return last


# ---- cnb（复用 cb-dispatch.py 形制）----------------------------------------------
CNB_ORG_KEY = {"zhuzhu-team": "CNB-2-all-privilege",
               "cloudbird-software": "CNB-1-all-privilege"}


def cnb_token(org):
    """CNB 令牌现取：本地 0600 令牌件（cb-dispatch 同款 org→键映射），不落盘不打印。"""
    key = CNB_ORG_KEY.get(org.lower(), org)
    try:
        with open(CNB_TOKEN_FILE, encoding="utf-8") as f:
            t = json.load(f).get(key)
        if t:
            return t
    except FileNotFoundError:
        pass
    fail(2, "CNB 令牌件缺席或缺键: %s（%s）" % (CNB_TOKEN_FILE, key))


def cnb_api(org, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        CNB_API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + cnb_token(org),
                 "Content-Type": "application/json",
                 "Accept": "application/vnd.cnb.api+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read().decode()
            return json.loads(b) if b else {}
    except urllib.error.HTTPError as e:
        return {"__http_error": e.code, "body": e.read().decode()[:300]}


# ---- local（意图登记 + 工人简报）-------------------------------------------------
def local_brief(did, text, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, did + "-简报.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 工人简报 %s\n\n- 派发时刻: %s\n- 通道: local（本机直派）\n\n"
                "## 任务指令（原文）\n\n%s\n\n## 工人须知\n\n"
                "1. 本简报即派发凭据面：按指令施工，判据/判官件零改动；\n"
                "2. 完成后以状态件 %s/%s.json 的 report 段回传留痕；\n"
                "3. 读数如实，禁美化。\n" % (did, now(), text, STATE_DIR, did))
    return p


# ---- dispatch 主体 ---------------------------------------------------------------
def cmd_dispatch(a):
    did = uuid.uuid4().hex[:12]
    rec = {"schema": "af.fleet-dispatch.v1", "dispatch_id": did,
           "platform": a.platform, "model": a.model or "", "ts": now(),
           "text_head": a.text[:80], "ok": False}
    if a.platform == "stepfun":
        pre = stepfun_quota()
        r = stepfun_api("/api/step.openapi.devcenter.AIStudio/StartStudioWorkspaceRun",
                        {"workspaceId": STEPFUN_WS, "conversationId": STEPFUN_CONV,
                         "clientRequestId": str(uuid.uuid4()), "text": a.text,
                         "model": {"modelId": a.model or "step-5-preview"}})
        rec.update({"assistant_message_id": r.get("assistant_message_id"),
                    "workspace": STEPFUN_WS, "conversation": STEPFUN_CONV,
                    "quota_pre": pre,
                    "ok": bool(r.get("assistant_message_id"))})
        if not rec["ok"]:
            save_state(rec)
            fail(3, "stepfun 派发无 assistant_message_id: %s" % json.dumps(r)[:200])
        post = stepfun_quota()
        rec["quota_post"] = post
        cost = None
        note = ""
        if isinstance(pre, (int, float)) and isinstance(post, (int, float)):
            cost = round(pre - post, 2)
        else:
            note = ("额度读数缺席（pre=%r post=%r）——差值不可算，todo-discover"
                    % (pre, post))
        rec["pricing"] = observe("stepfun", a.model or "step-5-preview", cost,
                                 "QueryStudioRateLimit 派发前后差值（双层额度）",
                                 "quota%点", note)
    elif a.platform == "codao":
        # 拉取式合规通道：先 UI 唤醒（保沙箱在温）→ 操作员 enqueue 任务对象
        # → 沙箱 worker 拉取 → report 回传。任务对象=任务规格（http_get 白名单
        # 作业），非 shell 命令——C2 形态必拒（报告 T4）。
        if a.wake:
            pw, browser, ctx = fleet_ctx()
            try:
                page = fleet_page(ctx, "devcloud")
                codao_send(page, WAKE_MSG)
                rec["wake_sent"] = True
            except SystemExit:
                rec["ok"] = False
                save_state(rec)
                raise
            finally:
                pw.stop()
        task = {"type": "http_get", "url": a.url, "dispatch_id": did,
                "ts": now(), "note": a.text[:200]}
        q = relay_req("POST", "/enqueue", {"aid": a.aid, "cmd": task})
        rec.update({"aid": a.aid, "task": task, "queued": q.get("queued"),
                    "ok": q.get("ok") is True})
        if not rec["ok"]:
            save_state(rec)
            fail(3, "codao enqueue 失败: %s" % json.dumps(q)[:200])
        rec["pricing"] = observe("codao", "智速模式", None,
                                 "worker 拉取路径不新建任务页——消耗文案不可读",
                                 "积分/任务")
    elif a.platform == "workbuddy":
        pw, browser, ctx = fleet_ctx()
        try:
            page = fleet_page(ctx, "workbuddy")
            tail0 = ui_read_tail(page, 400)
            wb_send(page, a.text)
            rec.update({"page_url_head": page.url[:120], "ok": True,
                        "sent_chars": len(a.text)})
            save_state(rec)
            tail = ui_read_tail(page, 1200)
            stable = ui_wait_stable(page, budget=a.wait) if a.wait else 0
            rec["reply_tail_head"] = tail[-400:]
            rec["stable_len"] = stable
            rec["reply_changed"] = tail[-400:] != tail0[-400:]
        finally:
            pw.stop()
        rec["pricing"] = observe("workbuddy", a.model or "Hy3", None,
                                 "额度体系待逆向", "未知")
    elif a.platform == "cnb":
        if not (a.org and a.repo and a.title):
            fail(2, "cnb 派发需 --org --repo --title（--text=评论指令）")
        issue = cnb_api(a.org, "POST", "/%s/%s/-/issues" % (a.org, a.repo),
                        {"title": a.title, "body": a.text[:2000]})
        num = issue.get("number")
        try:
            num = int(num)          # API 两种形态都见过：int / str
        except (TypeError, ValueError):
            num = None
        if not num:
            save_state(rec)
            fail(3, "cnb 建 issue 失败: %s" % json.dumps(issue)[:200])
        c = cnb_api(a.org, "POST", "/%s/%s/-/issues/%d/comments" % (a.org, a.repo, num),
                    {"body": a.text, "work_mode": True})
        rec.update({"org": a.org, "repo": a.repo, "issue": num,
                    "comment_id": c.get("id"), "ok": num is not None})
        rec["pricing"] = observe("cnb", a.model or "deepseek-v4.1-flash", 0,
                                 "NPC 口径实测 0 扣费（cb-dispatch 同口径）",
                                 "AI token/NPC")
    else:  # local
        p = local_brief(did, a.text, a.local_dir or STATE_DIR)
        rec.update({"brief": p, "brief_sha256":
                    hashlib.sha256(open(p, "rb").read()).hexdigest(), "ok": True})
        rec["pricing"] = observe("local", a.model or "本机工人", 0,
                                 "本机算力，无平台计费", "无")
    p = save_state(rec)
    rec["state_file"] = p
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if rec["ok"] else 3


def stepfun_quota():
    """StepFun 额度读数（双层解读，credits.py 同口径；不可读 → None ⇒ todo-discover）。"""
    try:
        r = stepfun_api("/api/step.openapi.devcenter.Dashboard/QueryStudioRateLimit",
                        {}, wait=15)
        free = r.get("free_rate")
        sub = r.get("credit_rate_limit", {}).get("subscription_credit_left_rate")
        if free is not None and free > 0:
            return round(100 * free, 1)
        if sub is not None and sub > 0:
            return round(100 * sub, 1)
        return 0.0
    except Exception:  # noqa: BLE001
        return None


# ---- status / report -------------------------------------------------------------
def cmd_status(a):
    rec = load_state(a.dispatch_id) if a.dispatch_id else latest_state(a.platform)
    out = {"dispatch_id": rec["dispatch_id"], "platform": rec["platform"],
           "ts": rec["ts"], "ok": rec.get("ok")}
    pf = rec["platform"]
    if pf == "stepfun":
        if not rec.get("assistant_message_id"):
            fail(4, "状态件缺 assistant_message_id")
        r = stepfun_sse(rec["workspace"], rec["assistant_message_id"], max_wait=15)
        out.update({"message_status": r["status"],
                    "text_bytes": len(r["text"].encode())})
    elif pf == "codao":
        reps = relay_req("GET", "/reports/" + rec["aid"], quiet=True)
        mine = [x for x in reps if str(x.get("output", "")).find(
            rec["dispatch_id"]) >= 0] if isinstance(reps, list) else []
        out.update({"aid": rec["aid"], "reports_total": len(reps),
                    "reports_for_dispatch": len(mine),
                    "latest_report_ts": (reps[-1].get("ts") if reps else None)})
    elif pf == "workbuddy":
        pw, browser, ctx = fleet_ctx()
        try:
            page = fleet_page(ctx, "workbuddy")
            out.update({"page_url_head": page.url[:120],
                        "page_tail_head": ui_read_tail(page, 400)[-300:]})
        finally:
            pw.stop()
    elif pf == "cnb":
        cs = cnb_api(rec["org"], "GET", "/%s/%s/-/issues/%d/comments"
                     % (rec["org"], rec["repo"], rec["issue"]))
        items = cs.get("data", cs) if isinstance(cs, dict) else cs
        items = items if isinstance(items, list) else []
        out.update({"issue": rec["issue"], "comments": len(items),
                    "last_comment_head": (str(items[-1].get("body", ""))[:120]
                                          if items else None)})
    else:  # local
        p = rec.get("brief", "")
        out.update({"brief": p, "brief_exists": os.path.isfile(p),
                    "brief_sha256": (hashlib.sha256(open(p, "rb").read()).hexdigest()
                                     if os.path.isfile(p) else None)})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_report(a):
    rec = load_state(a.dispatch_id) if a.dispatch_id else latest_state(a.platform)
    pf = rec["platform"]
    out = {"dispatch_id": rec["dispatch_id"], "platform": pf, "ts": now()}
    rc = 0
    if pf == "stepfun":
        r = stepfun_sse(rec["workspace"], rec["assistant_message_id"],
                        max_wait=a.wait or 180)
        out.update({"final_status": r["status"], "reply": r["text"][:2000],
                    "reply_bytes": len(r["text"].encode())})
        rc = 0 if r["status"] else 5
    elif pf == "codao":
        deadline = time.time() + (a.wait or 120)
        mine = []
        while time.time() < deadline:
            reps = relay_req("GET", "/reports/" + rec["aid"], quiet=True)
            mine = [x for x in (reps if isinstance(reps, list) else [])
                    if str(x.get("output", "")).find(rec["dispatch_id"]) >= 0]
            if mine:
                break
            time.sleep(10)
        out.update({"reports_for_dispatch": len(mine),
                    "outputs": [x.get("output") for x in mine][-3:]})
        rc = 0 if mine else 5
    elif pf == "workbuddy":
        pw, browser, ctx = fleet_ctx()
        try:
            page = fleet_page(ctx, "workbuddy")
            tail = ui_read_tail(page, 2000)
            out.update({"reply_tail": tail[-1500:]})
            rc = 0
        finally:
            pw.stop()
    elif pf == "cnb":
        cs = cnb_api(rec["org"], "GET", "/%s/%s/-/issues/%d/comments"
                     % (rec["org"], rec["repo"], rec["issue"]))
        items = cs.get("data", cs) if isinstance(cs, dict) else cs
        items = items if isinstance(items, list) else []
        if not items:
            fail(5, "cnb 无评论可读")
        first_author = items[0].get("author")
        if isinstance(first_author, dict):
            first_author = first_author.get("username")
        foreign = [c for c in items[1:]
                   if (c.get("author") if isinstance(c.get("author"), str)
                       else (c.get("author") or {}).get("username")) != first_author]
        body = str(foreign[-1].get("body", ""))[:1500] if foreign else ""
        out.update({"comments_total": len(items), "foreign_replies": len(foreign),
                    "last_foreign_reply_head": body})
        rc = 0 if foreign else 5
    else:  # local
        p = rec.get("brief", "")
        if not os.path.isfile(p):
            fail(5, "简报件缺席: %s" % p)
        head = open(p, encoding="utf-8").read()[:800]
        out.update({"brief": p, "brief_head": head,
                    "brief_sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()})
        rec2 = dict(rec)
        rec2["reported_at"] = now()
        save_state(rec2)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return rc


# ---- CLI -------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 epilog="凭据零打印：登录态/令牌只从本机件与环境现取。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dispatch", help="派发一次任务")
    d.add_argument("--platform", required=True, choices=PLATFORMS)
    d.add_argument("--text", required=True, help="任务指令文本（cnb=issue 评论正文）")
    d.add_argument("--model", default="", help="模型（缺省=各通道低耗默认）")
    d.add_argument("--title", default="", help="cnb: issue 标题")
    d.add_argument("--org", default="", help="cnb: org")
    d.add_argument("--repo", default="", help="cnb: repo")
    d.add_argument("--aid", default="codao-worker-1", help="codao: 沙箱 worker aid")
    d.add_argument("--wake", action="store_true",
                   help="codao: enqueue 后经 fleet UI 同会话续聊唤醒 worker")
    d.add_argument("--url", default=RELAY_PUBLIC + "/ping",
                   help="codao: 任务对象 URL（白名单域内）")
    d.add_argument("--wait", type=int, default=240,
                   help="workbuddy 读态等待秒 / codao 收回传等待秒")
    d.add_argument("--local-dir", default="", help="local: 简报输出目录")

    s = sub.add_parser("status", help="状态查询")
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--dispatch-id", default="")

    r = sub.add_parser("report", help="收回传留痕")
    r.add_argument("--platform", choices=PLATFORMS)
    r.add_argument("--dispatch-id", default="")
    r.add_argument("--wait", type=int, default=0, help="等待回传秒（0=不等待）")

    a = ap.parse_args()
    if a.cmd == "dispatch":
        sys.exit(cmd_dispatch(a))
    if a.cmd == "status":
        if not a.dispatch_id and not a.platform:
            fail(2, "status 需 --dispatch-id 或 --platform")
        sys.exit(cmd_status(a))
    if a.cmd == "report":
        if not a.dispatch_id and not a.platform:
            fail(2, "report 需 --dispatch-id 或 --platform")
        sys.exit(cmd_report(a))


if __name__ == "__main__":
    main()
