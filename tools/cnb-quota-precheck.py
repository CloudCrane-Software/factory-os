#!/usr/bin/env python3
"""cnb-quota-precheck.py — CNB 双账号池派发前余量预检（D-131，task_id=cnb-quota-precheck）。

卡面：factory-os#146（[真锚][D-131]；来源：夜轨A2 建议清单 S5——
      30-工件/夜轨A2-20261107/cnb真沙箱bench环-读数-20261107.md:195）。

做什么（派发前程序化查余量，禁「额度不足任务立即终止」式闷死）：
  · 双账号现读：CNB-1=Cloudbird-Software、CNB-2=zhuzhu-team（两账号分属两组织，
    各 1600 核时/月、合计 3200，已实证；org slug 可配，禁单账号硬编码）。
  · 端点（只读，零写）：GET /{slug}/-/charge/quota（月度额度 total/free）
    ＋ GET /{slug}/-/charge/volume（本月消耗 dev_in_sec/ci_in_sec）。
  · 余量：free_dev_core_hours = (quota.dev_in_sec.total − volume.dev_in_sec)/3600。
  · 判定：ok（≥阈值）／reroute（低于阈值 ⇒ 输出建议账号+理由）／
    unknown（端点不可读 ⇒ fail-closed 禁派；禁把「没采到」当 0）。
  · JSON 读数落盘（--out）；模式：--check（判定+退出码）／--plan（只读渲染
    零写）／--selftest（三态桩夹具，零网络）。

退出码（--check）：
  0 = ok：全部账号 dev 余量 ≥ 阈值 ⇒ 放行派发。
  3 = reroute：存在账号低于阈值 ⇒ fail-closed 禁派（建议账号随读数输出；
      D-130 派发器 --execute 前置闸按建议改路由，或保持禁派）。
  2 = unknown：存在账号端点不可读（404/400/网络错/字段缺失/坏形态/token 不可得）
      ⇒ fail-closed 禁派。优先级高于 reroute——不可证不猜绿。
  · --plan 渲染成功恒 0（预览不是闸）；仅输入不可读（夹具坏/账户规格坏）才非零。
  · 用法错（模式缺/多选、--plan 带 --out 等）恒 64（EX_USAGE）。

总体裁决口径（fail-closed 优先）：unknown > reroute > ok——任一账号不可证即整体
unknown（rc=2）；否则任一账号低于阈值即整体 reroute（rc=3）；全账号达标才 ok
（rc=0）。逐账号明细仍在读数 JSON 的 accounts[] 内，调用方可做更细路由。

阈值：默认 50 核时（--threshold 可调）。**默认值只是缺省，不是运营者裁定值；
      调阈值归运营者**（卡面 P4）。

凭据纪律（P2）：CNB token 只经本地 0600 escrow 件现取
  （~/.config/cnb/relay-tokens.json，键 = token_key；权限过宽不收），缺失时回退
  openBao KV（http://gov-host.invalid:8200/v1/kv/data/company/Git-Platform/CNB/
  {token_key} 字段 Token，escrow root token 现读、不落盘）。禁 argv、禁 URL 带
  凭据、禁日志、禁落盘第二份；读数 JSON 只记 token_key 名与来源，不记任何令牌
  材料。本件对 charge 端点**零写操作**（只读 GET）。

个人命名空间口径：额度挂组织不挂个人——个人 slug（cnb.*）调 quota ⇒ 404 ⇒
  如实记 unknown（不可证），禁当 0、禁派（卡面 P3；同族实测 :143-144）。

依赖：纯 stdlib（python3 -I 直跑；夹具 YAML 用内嵌子集解析器——块映射+标量，
      禁第三方依赖；仓内 160 件工具仅 2 件用 yaml，本件守零依赖惯例）。

用法：
  cnb-quota-precheck.py --check [--fixture P] [--account 名=org[:token_key]]...
                        [--threshold 核时] [--out P] [--timeout S]
  cnb-quota-precheck.py --plan  同上（除 --out：零写拒收）
  cnb-quota-precheck.py --selftest
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

CNB_API = "https://api.cnb.cool"
CNB_ACCEPT = "application/vnd.cnb.api+json"
TOKEN_FILE = os.path.expanduser("~/.config/cnb/relay-tokens.json")
BAO = "http://gov-host.invalid:8200"
BAO_RT = os.path.expanduser("~/.local/share/openbao-escrow/.root-token")

DEFAULT_THRESHOLD_CORE_HOURS = 50.0
EXIT_OK, EXIT_UNKNOWN, EXIT_REROUTE, EXIT_USAGE, EXIT_SELFTEST_FAIL = 0, 2, 3, 64, 1
V_OK, V_REROUTE, V_UNKNOWN = "ok", "reroute", "unknown"
VERDICT_EXIT = {V_OK: EXIT_OK, V_REROUTE: EXIT_REROUTE, V_UNKNOWN: EXIT_UNKNOWN}

# 双账号池默认面（卡面核实证：两账号分属两组织，各 1600 核时/月）。
# 第二道须用 zhuzhu-team/cb-npc-poc（cb-npc-poc 在两侧各有一个）。
DEFAULT_ACCOUNTS = (
    ("CNB-1", "Cloudbird-Software", "CNB-1-all-privilege"),
    ("CNB-2", "zhuzhu-team", "CNB-2-all-privilege"),
)


class FixtureError(Exception):
    """夹具不可读/坏形态（selftest 与 --fixture 共用）。"""


# ---------------------------------------------------------------- 凭据（P2）
def _token_from_escrow_file(key):
    """本地 0600 escrow 件现取；权限过宽/缺件/坏 JSON 一律视为不可得。"""
    try:
        if os.stat(TOKEN_FILE).st_mode & 0o077:
            return None
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return json.load(f).get(key)
    except (OSError, ValueError):
        return None


def _token_from_openbao(key):
    """openBao KV 现取（escrow root token 只进内存，不落盘不打印）。"""
    try:
        with open(BAO_RT, encoding="utf-8") as f:
            rt = f.read().strip()
    except OSError:
        return None
    req = urllib.request.Request(
        "%s/v1/kv/data/company/Git-Platform/CNB/%s" % (BAO, key),
        headers={"X-Vault-Token": rt})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["data"]["data"]["Token"]
    except Exception:
        return None


def acquire_token(key):
    """返回 (token, source)；不可得返回 (None, None)。令牌绝不打印/落盘。"""
    t = _token_from_escrow_file(key)
    if t:
        return t, "relay-tokens-0600"
    t = _token_from_openbao(key)
    if t:
        return t, "openbao"
    return None, None


# ---------------------------------------------------------------- 端点只读
def _get_json(url, token, timeout):
    """只读 GET。返回 (http_status, body|None)。凭据只进 Authorization 头。"""
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": CNB_ACCEPT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- 判定
def evaluate_account(name, org, token_key, token_source,
                     quota_status, quota_body, volume_status, volume_body,
                     threshold):
    """单账号读数+裁决。端点不可读/字段坏 ⇒ unknown（禁把没采到当 0）。"""
    acct = {
        "name": name, "org": org, "token_key": token_key,
        "token_source": token_source,
        "quota_http": quota_status, "volume_http": volume_status,
        "dev_quota_total_core_seconds": None,
        "dev_quota_free_core_seconds": None,
        "dev_consumed_core_seconds": None,
        "ci_consumed_core_seconds": None,
        "free_dev_core_hours": None,
        "verdict": V_UNKNOWN, "reason": "",
    }
    if quota_status != 200 or volume_status != 200:
        acct["reason"] = ("端点不可读：quota http=%s volume http=%s——不可证，"
                          "fail-closed 禁派（没采到不当 0）"
                          % (quota_status, volume_status))
        return acct
    qdev = quota_body.get("dev_in_sec") if isinstance(quota_body, dict) else None
    vdev = volume_body.get("dev_in_sec") if isinstance(volume_body, dict) else None
    if not isinstance(qdev, dict) or not _is_num(qdev.get("total")):
        acct["reason"] = ("quota.dev_in_sec.total 缺失或非数值——不可证，"
                          "fail-closed 禁派")
        return acct
    if not _is_num(vdev):
        acct["reason"] = ("volume.dev_in_sec 缺失或非数值——不可证，"
                          "fail-closed 禁派")
        return acct
    total, consumed = qdev["total"], vdev
    free_hours = (total - consumed) / 3600.0
    acct["dev_quota_total_core_seconds"] = total
    if _is_num(qdev.get("free")):
        acct["dev_quota_free_core_seconds"] = qdev["free"]
    acct["dev_consumed_core_seconds"] = consumed
    acct["free_dev_core_hours"] = round(free_hours, 2)
    vci = volume_body.get("ci_in_sec") if isinstance(volume_body, dict) else None
    if _is_num(vci):
        acct["ci_consumed_core_seconds"] = vci
    if free_hours < threshold:
        acct["verdict"] = V_REROUTE
        acct["reason"] = ("dev 余量 %.2f 核时 < 阈值 %g 核时——低于阈值改路由"
                          "（fail-closed 禁派本账号）" % (free_hours, threshold))
    else:
        acct["verdict"] = V_OK
        acct["reason"] = ("dev 余量 %.2f 核时 ≥ 阈值 %g 核时"
                          % (free_hours, threshold))
    return acct


def read_account_live(name, org, token_key, threshold, timeout):
    """真跑：现取 token → 只读两端点 → 裁决。token 不可得 ⇒ unknown。"""
    token, tsrc = acquire_token(token_key)
    if not token:
        acct = evaluate_account(name, org, token_key, None, None, None,
                                None, None, threshold)
        acct["reason"] = ("token 不可得（0600 escrow 件与 openBao 均无 %s）——"
                          "不可证，fail-closed 禁派" % token_key)
        return acct
    qs, qb = _get_json("%s/%s/-/charge/quota" % (CNB_API, org), token, timeout)
    vs, vb = _get_json("%s/%s/-/charge/volume" % (CNB_API, org), token, timeout)
    return evaluate_account(name, org, token_key, tsrc, qs, qb, vs, vb,
                            threshold)


def adjudicate(accounts, threshold):
    """总体裁决（fail-closed 优先：unknown > reroute > ok）+ 改路由建议。"""
    verdicts = [a["verdict"] for a in accounts]
    if V_UNKNOWN in verdicts:
        bad = [a["name"] for a in accounts if a["verdict"] == V_UNKNOWN]
        return {
            "verdict": V_UNKNOWN,
            "exit_code": VERDICT_EXIT[V_UNKNOWN],
            "dispatch_allowed": False,
            "reroute_suggestion": None,
            "reason": ("存在账号不可证（%s）——不可证不猜绿，fail-closed 禁派；"
                       "逐账号明细见 accounts[]" % ", ".join(bad)),
        }
    if V_REROUTE in verdicts:
        low = [a["name"] for a in accounts if a["verdict"] == V_REROUTE]
        ok_accts = [a for a in accounts if a["verdict"] == V_OK]
        if ok_accts:
            t = ok_accts[0]
            sug = {
                "account": t["name"], "org": t["org"],
                "free_dev_core_hours": t["free_dev_core_hours"],
                "reason": ("%s 低于阈值，改路由 %s（%s，dev 余量 %g 核时 ≥ 阈值 %g）"
                           % ("/".join(low), t["name"], t["org"],
                              t["free_dev_core_hours"], threshold)),
            }
            reason = ("%s 低于阈值——fail-closed 禁派原账号；建议改路由 %s"
                      "（禁「额度不足任务立即终止」式闷死）"
                      % ("/".join(low), t["name"]))
        else:
            sug = None
            reason = ("全部账号低于阈值且无可用第二道——保持禁派；"
                      "降规格/择窗归运营者裁")
        return {
            "verdict": V_REROUTE,
            "exit_code": VERDICT_EXIT[V_REROUTE],
            "dispatch_allowed": False,
            "reroute_suggestion": sug,
            "reason": reason,
        }
    return {
        "verdict": V_OK,
        "exit_code": VERDICT_EXIT[V_OK],
        "dispatch_allowed": True,
        "reroute_suggestion": None,
        "reason": ("全部账号 dev 余量 ≥ 阈值 %g 核时——放行派发" % threshold),
    }


# ---------------------------------------------------------------- 夹具 YAML
def _fixture_lines(text):
    """去空行去整行注释；返回 [(indent, content)]。Tab 缩进=坏形态。"""
    out = []
    for ln in text.splitlines():
        if "\t" in ln[:len(ln) - len(ln.lstrip())]:
            raise FixtureError("Tab 缩进（YAML 子集禁 Tab）: %r" % ln)
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append((len(ln) - len(ln.lstrip(" ")), s))
    return out


def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s in ("null", "~", ""):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_block(lines, i, indent):
    """块映射递归下降（内嵌 YAML 子集：仅嵌套映射+标量，无序列/无流式）。"""
    out = {}
    while i < len(lines):
        ind, text = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise FixtureError("坏缩进（期望 %d 实得 %d）: %r" % (indent, ind, text))
        if ":" not in text:
            raise FixtureError("非 key: value 行: %r" % text)
        key, _, rest = text.partition(":")
        key, rest = key.strip(), rest.strip()
        if not key:
            raise FixtureError("空键: %r" % text)
        if key in out:
            raise FixtureError("重复键: %r" % key)
        if rest:
            out[key] = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1][0] > indent:
            out[key], i = _parse_block(lines, i + 1, lines[i + 1][0])
        else:
            out[key] = None
            i += 1
    return out, i


def load_fixture(path):
    """读三态夹具。返回 {state, accounts:[{name,org,token_key,quota:{http,body},
    volume:{http,body}}]}；坏形态/缺字段 ⇒ FixtureError（调用方记 unknown 或
    selftest 红）。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise FixtureError("夹具不可读: %s" % e)
    lines = _fixture_lines(text)
    if not lines:
        raise FixtureError("空夹具")
    doc, _ = _parse_block(lines, 0, 0)
    state = doc.get("state")
    accs_raw = doc.get("accounts")
    if state not in (V_OK, V_REROUTE, V_UNKNOWN):
        raise FixtureError("夹具 state 缺场或非法: %r" % state)
    if not isinstance(accs_raw, dict) or not accs_raw:
        raise FixtureError("夹具 accounts 缺场或空")
    accounts = []
    for name, a in accs_raw.items():
        if not isinstance(a, dict):
            raise FixtureError("账号 %r 非映射" % name)
        org = a.get("org")
        if not org:
            raise FixtureError("账号 %r 缺 org" % name)
        quota, volume = a.get("quota"), a.get("volume")
        for tag, ep in (("quota", quota), ("volume", volume)):
            if not isinstance(ep, dict) or not _is_num(ep.get("http")):
                raise FixtureError("账号 %r 的 %s.http 缺失或非数值" % (name, tag))
        accounts.append({
            "name": name, "org": org,
            "token_key": a.get("token_key"),
            "quota": {"http": quota["http"], "body": quota.get("body")},
            "volume": {"http": volume["http"], "body": volume.get("body")},
        })
    return {"state": state, "accounts": accounts}


def run_fixture(path, threshold):
    """夹具模式（零网络零 token）：逐账号裁决 + 总体裁决。"""
    fx = load_fixture(path)
    accounts = [
        evaluate_account(a["name"], a["org"], a["token_key"], "fixture",
                         a["quota"]["http"], a["quota"]["body"],
                         a["volume"]["http"], a["volume"]["body"], threshold)
        for a in fx["accounts"]
    ]
    return accounts, adjudicate(accounts, threshold)


# ---------------------------------------------------------------- 读数落盘
def build_reading(mode, source, accounts, overall, threshold):
    return {
        "schema": "cnb-quota-precheck.reading/1",
        "task_id": "cnb-quota-precheck",
        "debt": "D-131",
        "mode": mode,
        "source": source,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "threshold_core_hours": threshold,
        "threshold_note": ("默认缺省值（<50 核时改路由），非运营者裁定值；"
                           "调阈值归运营者（卡面 P4）"),
        "accounts": accounts,
        "overall": overall,
    }


def emit(reading, out_path, plan_mode):
    """stdout 恒出 JSON；--out 追加落盘（--plan 零写：调用方已拒收 --out）。"""
    text = json.dumps(reading, ensure_ascii=False, indent=1)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    ov = reading["overall"]
    sug = ov.get("reroute_suggestion")
    line = ("PRECHECK %s rc=%d dispatch_allowed=%s :: %s"
            % (ov["verdict"], ov["exit_code"], ov["dispatch_allowed"],
               ov["reason"]))
    if sug:
        line += " | 建议: %s（%s）" % (sug["account"], sug["org"])
    print(line, file=sys.stderr)
    if plan_mode:
        print("PLAN 模式：只读渲染零写（未落盘任何文件）", file=sys.stderr)


# ---------------------------------------------------------------- selftest
def _approx(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def selftest():
    """三态桩夹具自测（零网络）：ok⇒ok/rc0、low⇒reroute/rc3+建议第二道、
    unknown⇒unknown/rc2 且没采到不当 0。夹具件 = 脚本旁 fixtures/ 真件。"""
    fx_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "cnb-quota-precheck")
    cases = [
        ("ok.yml", V_OK, EXIT_OK),
        ("low.yml", V_REROUTE, EXIT_REROUTE),
        ("unknown.yml", V_UNKNOWN, EXIT_UNKNOWN),
    ]
    passed, failed = 0, []

    def check(cond, label):
        nonlocal passed
        if cond:
            passed += 1
            print("PASS %s" % label)
        else:
            failed.append(label)
            print("FAIL %s" % label)

    for fn, want_v, want_rc in cases:
        path = os.path.join(fx_dir, fn)
        try:
            accounts, overall = run_fixture(path, DEFAULT_THRESHOLD_CORE_HOURS)
        except FixtureError as e:
            check(False, "%s 可读（%s）" % (fn, e))
            continue
        check(True, "%s 可读" % fn)
        by = {a["name"]: a for a in accounts}
        check(overall["verdict"] == want_v and overall["exit_code"] == want_rc,
              "%s ⇒ 总体 %s/rc=%d（实得 %s/rc=%d）"
              % (fn, want_v, want_rc, overall["verdict"], overall["exit_code"]))
        check(overall["dispatch_allowed"] == (want_v == V_OK),
              "%s ⇒ dispatch_allowed=%s" % (fn, want_v == V_OK))
        check(all(a["token_source"] == "fixture" for a in accounts),
              "%s ⇒ 夹具模式零 token（token_source 全 fixture）" % fn)
        if fn == "ok.yml":
            check(_approx(by["CNB-1"]["free_dev_core_hours"], 1543.91)
                  and _approx(by["CNB-2"]["free_dev_core_hours"], 1600.0),
                  "ok.yml ⇒ CNB-1 余 1543.91 / CNB-2 余 1600.00 核时")
            check(by["CNB-1"]["verdict"] == V_OK
                  and by["CNB-2"]["verdict"] == V_OK,
                  "ok.yml ⇒ 两账号均 ok")
        if fn == "low.yml":
            check(_approx(by["CNB-1"]["free_dev_core_hours"], 8.33)
                  and by["CNB-1"]["verdict"] == V_REROUTE,
                  "low.yml ⇒ CNB-1 余 8.33 核时 < 50 ⇒ reroute")
            sug = overall["reroute_suggestion"]
            check(bool(sug) and sug["account"] == "CNB-2"
                  and sug["org"] == "zhuzhu-team",
                  "low.yml ⇒ 建议改路由 CNB-2（zhuzhu-team）")
        if fn == "unknown.yml":
            u = by["CNB-1"]
            check(u["verdict"] == V_UNKNOWN and u["quota_http"] == 404,
                  "unknown.yml ⇒ CNB-1 quota http=404 ⇒ unknown")
            check(u["free_dev_core_hours"] is None
                  and u["dev_consumed_core_seconds"] is None,
                  "unknown.yml ⇒ 没采到不当 0（free/consumed 恒 None）")
            check(by["CNB-2"]["verdict"] == V_OK,
                  "unknown.yml ⇒ CNB-2 可读仍判 ok（明细不丢）")
            check(overall["reroute_suggestion"] is None,
                  "unknown.yml ⇒ 不可证不猜绿（无改路由建议）")
    check(VERDICT_EXIT == {V_OK: 0, V_REROUTE: 3, V_UNKNOWN: 2},
          "退出码映射 ok=0 / reroute=3 / unknown=2")
    total = passed + len(failed)
    print("SELFTEST %s %d/%d" % ("PASS" if not failed else "FAIL",
                                 passed, total))
    return 0 if not failed else EXIT_SELFTEST_FAIL


# ---------------------------------------------------------------- CLI
def parse_account_spec(spec):
    """name=org[:token_key]；token_key 缺省按 {name}-all-privilege 惯例。"""
    if "=" not in spec:
        raise ValueError("账户规格缺 '=': %r" % spec)
    name, rest = spec.split("=", 1)
    name, rest = name.strip(), rest.strip()
    if not name or not rest:
        raise ValueError("账户规格空段: %r" % spec)
    if ":" in rest:
        org, key = rest.split(":", 1)
    else:
        org, key = rest, "%s-all-privilege" % name
    org, key = org.strip(), key.strip()
    if not org or not key:
        raise ValueError("账户规格空段: %r" % spec)
    return name, org, key


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="判定模式：计算+裁决+退出码（0/2/3）")
    mode.add_argument("--plan", action="store_true",
                      help="预览模式：只读渲染零写")
    mode.add_argument("--selftest", action="store_true",
                      help="三态桩夹具自测（零网络）")
    ap.add_argument("--fixture", help="夹具 YAML 路径（零网络零 token）")
    ap.add_argument("--account", action="append", default=[],
                    help="账户规格 name=org[:token_key]（可重复；默认双账号）")
    ap.add_argument("--threshold", type=float,
                    default=DEFAULT_THRESHOLD_CORE_HOURS,
                    help="dev 余量阈值（核时，默认 %g；缺省值非运营者裁定值）"
                    % DEFAULT_THRESHOLD_CORE_HOURS)
    ap.add_argument("--out", help="读数 JSON 落盘路径（--check 可用）")
    ap.add_argument("--timeout", type=int, default=60, help="单端点超时秒")
    args = ap.parse_args(argv)

    if args.selftest:
        if args.fixture or args.account or args.out:
            print("selftest 不接受 --fixture/--account/--out", file=sys.stderr)
            return EXIT_USAGE
        return selftest()
    if args.plan and args.out:
        print("--plan 只读渲染零写：拒收 --out", file=sys.stderr)
        return EXIT_USAGE
    if args.threshold < 0:
        print("--threshold 禁负值", file=sys.stderr)
        return EXIT_USAGE
    try:
        accounts_spec = [parse_account_spec(s) for s in args.account] \
            if args.account else list(DEFAULT_ACCOUNTS)
    except ValueError as e:
        print("账户规格坏: %s" % e, file=sys.stderr)
        return EXIT_USAGE

    threshold = args.threshold
    if args.fixture:
        try:
            accounts, overall = run_fixture(args.fixture, threshold)
        except FixtureError as e:
            print("夹具不可读: %s" % e, file=sys.stderr)
            return EXIT_UNKNOWN
        source = "fixture:%s" % args.fixture
    else:
        accounts = [read_account_live(n, o, k, threshold, args.timeout)
                    for n, o, k in accounts_spec]
        overall = adjudicate(accounts, threshold)
        source = "live:%s" % CNB_API
    reading = build_reading("plan" if args.plan else "check", source,
                            accounts, overall, threshold)
    emit(reading, args.out, args.plan)
    return 0 if args.plan else overall["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
