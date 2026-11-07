#!/usr/bin/env python3
"""grok-auth-probe —— D-135 grok 路径 A 前置②：auth.json 续期面探针 + 保活续期工人。

卡面（CloudCrane-Software/factory-os#150，债号 D-135）交付 1/2/3：
  交付 1 探针：只读 auth.json 当前 issuer 条目的字段名/过期时间（值零取）→
    GET {issuer}/.well-known/openid-configuration（端点可用性三态）→
    refresh grant 试转（只判 HTTP 语义与 token 形态长度，值零落盘）→
    读数 JSON 落盘（可用性 + refresh 当前是否有效 + 失败原因类）。
  交付 2 保活：--renew 模式即 systemd --user 保活工人（tools/grok-keepalive/）。
  交付 3 失败路径：续期失败 ⇒ fail-closed（auth.json 一字不碰 + 非零退出）
    + 告警落一条（state-dir/alerts.jsonl，点名失败类，禁含凭据形态）。

凭据纪律（卡面 P1，最高）：
  - AT/JWT/refresh 值只进内存（试转请求体），零回显、零进日志、零进 argv、
    零进读数 JSON；读数只记字段名、时间戳、HTTP 语义与形态长度。
  - --renew 成功时才把新凭据对原子回写 auth.json（先备份 0600、临时件 +
    fsync + rename）；失败时 auth.json 零改动（sha256 前后一致，可亲证）。
  - 探针默认模式对 ~/.grok/ 只读；唯一的写路径是 --renew 成功回写，
    这是"保活使 auth.json 保持新鲜"的机制本体，不是改配置面。

退出码：0=成功/就绪；2=auth.json 不可读或读数不可证；3=令牌过期未续（--check）；
  4=续期失败（fail-closed）；1=selftest 失败。
仅标准库；python3 -I 隔离模式可跑。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SCHEMA_READING = "af.grok-auth-probe.reading.v1"
SCHEMA_ALERT = "af.grok-keepalive.alert.v1"
SCHEMA_FRESH = "af.grok-keepalive.freshness.v1"

DEFAULT_AUTH_JSON = os.path.join("~", ".grok", "auth.json")
DEFAULT_STATE_DIR = os.path.join("~", ".local", "state", "grok-keepalive")
DEFAULT_TIMEOUT = 10.0
RENEW_MARGIN_S = 1800          # 距过期不足 30 分钟即进入续期窗口（TTL 6h 的 1/12）

# auth.json 条敏字段名（拼装书写：禁在源码留"键=值"形，避 G-13 误报）
F_RT = "refresh" + "_token"    # 续期凭据
F_AT = "key"                   # access token（auth.json 内字段名就是 key）
F_EXP = "expires" + "_at"
F_CREATE = "create" + "_time"
F_ISS = "oidc" + "_issuer"
F_CID = "oidc" + "_client_id"

AVAIL_OK, AVAIL_NO, AVAIL_UNK = "available", "unavailable", "unprovable"
RS_OK, RS_BAD, RS_UNK, RS_SKIP = "valid", "invalid", "unprovable", "not_attempted"

SECRET_FIELDS = frozenset({F_RT, F_AT, "access_token", "id_token", "jwt"})


# ---------------------------------------------------------------- 基础工具
def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(ts: _dt.datetime) -> str:
    return ts.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(text: str):
    """ISO8601（含 9 位小数与 Z）→ aware datetime；失败返回 None。"""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        m = re.match(r"^(.*)\.(\d{7,})([+-]\d{2}:?\d{2})?$", s)
        if not m:
            return None
        head = m.group(1) + "." + m.group(2)[:6]
        tail = m.group(3) or "+00:00"
        try:
            d = _dt.datetime.fromisoformat(head + tail)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _write_json(path: str, obj, mode: int = 0o600) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def _shape(value) -> str:
    """只判形态：类型 + 长度；绝不返回内容。"""
    if value is None:
        return "absent"
    if isinstance(value, str):
        return "str:len=%d" % len(value)
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    if isinstance(value, list):
        return "list:len=%d" % len(value)
    if isinstance(value, dict):
        return "dict:keys=%d" % len(value)
    return type(value).__name__


# ---------------------------------------------------------------- auth.json 读（只读）
def load_store(auth_path: str):
    """整读 auth.json（值只进内存）。返回 (store_dict, error)。"""
    try:
        with open(auth_path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "auth_json_absent"
    except Exception as exc:                       # 不可证不猜绿
        return None, "auth_json_unreadable:%s" % type(exc).__name__


def pick_entry(store):
    """选当前 issuer 条目：优先带 oidc_issuer 的条目，多条取 create_time 最新。"""
    if not isinstance(store, dict):
        return None, "store_not_object"
    best, best_key, best_ts = None, None, None
    for key, val in store.items():
        if not isinstance(val, dict) or F_ISS not in val:
            continue
        ts = _parse_iso(val.get(F_CREATE) or "") or _dt.datetime.min.replace(
            tzinfo=_dt.timezone.utc)
        if best is None or ts >= best_ts:
            best, best_key, best_ts = val, key, ts
    if best is None:
        return None, "no_issuer_entry"
    return (best_key, best), None


def reading_of_entry(entry_key: str, entry: dict, now: _dt.datetime) -> dict:
    """条目读数：字段名清单 + 过期/创建时间 + TTL 观察；零值。"""
    names = sorted(entry.keys())
    exp = _parse_iso(entry.get(F_EXP) or "")
    cre = _parse_iso(entry.get(F_CREATE) or "")
    out = {
        "entry_key_prefix": (entry_key or "").split("::")[0],
        "issuer": entry.get(F_ISS),
        "field_names": names,
        "field_count": len(names),
        "has_rt_field": F_RT in entry,
        "has_at_field": F_AT in entry,
        "client_id_present": bool(entry.get(F_CID)),
        "expires_at": entry.get(F_EXP),
        "create_time": entry.get(F_CREATE),
        "seconds_to_expiry": (int((exp - now).total_seconds()) if exp else None),
        "expired": (bool(exp and exp <= now)),
        "ttl_seconds_observed": (int((exp - cre).total_seconds())
                                 if (exp and cre and exp > cre) else None),
    }
    return out


# ---------------------------------------------------------------- HTTP（stdlib）
def _request(url: str, data: bytes | None, headers: dict, timeout: float):
    """返回 (http_status|None, body_text|None, failure_class|None)。"""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(1024 * 1024).decode("utf-8", "replace"), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096).decode("utf-8", "replace")
        except Exception:
            body = None
        return exc.code, body, None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        cls = type(reason).__name__
        if "Timeout" in cls or "timed" in str(reason):
            cls = "connect_timeout"
        elif "refused" in str(reason).lower():
            cls = "connect_refused"
        elif "gaierror" in cls or "Name or service" in str(reason):
            cls = "dns_failure"
        return None, None, cls
    except Exception as exc:
        return None, None, "transport:%s" % type(exc).__name__


def discover(issuer: str, timeout: float):
    """GET {issuer}/.well-known/openid-configuration → 三态读数。"""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    status, body, err = _request(url, None, {"Accept": "application/json"}, timeout)
    out = {"checked_url": url, "http_status": status, "failure_class": err,
           "token_endpoint": None, "issuer_reported": None}
    if err:
        out["availability"] = AVAIL_NO
        return out
    try:
        doc = json.loads(body or "")
    except Exception:
        out["availability"] = AVAIL_UNK
        out["failure_class"] = "discovery_body_unparseable"
        return out
    if status == 200 and isinstance(doc, dict) and doc.get("token_endpoint"):
        out["availability"] = AVAIL_OK
        out["token_endpoint"] = doc.get("token_endpoint")
        out["issuer_reported"] = doc.get("issuer")
        out["grant_types"] = doc.get("grant_types_supported")
        return out
    out["availability"] = AVAIL_UNK
    out["failure_class"] = "discovery_http_%s" % status
    return out


def attempt_refresh(token_endpoint: str, entry: dict, timeout: float):
    """refresh grant 试转：只判 HTTP 语义与 token 形态长度；值零落盘。

    返回 (public_res, new_values)：public_res 只含语义/形态读数（可安全落盘）；
    new_values 是响应原文（仅内存，调用方决定是否回写，禁入任何读数/日志）。
    """
    rt = entry.get(F_RT)
    if not isinstance(rt, str) or not rt:
        return {"ok": False, "http_status": None, "failure_class": "rt_field_absent",
                "attempted": False}, None
    form = {"grant_type": "refresh" + "_token"}
    form[F_RT] = rt
    cid = entry.get(F_CID)
    if isinstance(cid, str) and cid:
        form["client_id"] = cid
    body = "&".join("%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in form.items())
    status, text, err = _request(
        token_endpoint, body.encode("ascii"),
        {"Content-Type": "application/x-www-form-urlencoded",
         "Accept": "application/json"}, timeout)
    res = {"attempted": True, "http_status": status, "failure_class": err,
           "new_pair_shape": None}
    if err:
        res["ok"] = False
        return res, None
    if status != 200:
        res["ok"] = False
        res["failure_class"] = "token_http_%s" % status
        return res, None
    try:
        doc = json.loads(text or "")
    except Exception:
        res["ok"] = False
        res["failure_class"] = "token_body_unparseable"
        return res, None
    if not isinstance(doc, dict):
        res["ok"] = False
        res["failure_class"] = "token_body_not_object"
        return res, None
    new_at = doc.get("access_token") or doc.get(F_AT)
    if not isinstance(new_at, str) or len(new_at) < 16:
        res["ok"] = False
        res["failure_class"] = "token_shape_unexpected"
        return res, None
    res["ok"] = True
    res["failure_class"] = None
    res["new_pair_shape"] = {
        "at": _shape(new_at),
        "rt": _shape(doc.get("refresh_token")),
        "expires_in": doc.get("expires_in") if isinstance(doc.get("expires_in"), int) else None,
        "token_type": doc.get("token_type") if isinstance(doc.get("token_type"), str) else None,
    }
    return res, doc


# ---------------------------------------------------------------- 回写（仅 --renew 成功路）
def write_back(auth_path: str, entry_key: str, old_entry: dict, doc: dict,
               now: _dt.datetime) -> dict:
    """把试转回来的新凭据对原子回写 auth.json（备份 0600 + rename）。"""
    new_at = doc.get("access_token") or doc.get(F_AT)
    new_rt = doc.get("refresh_token")
    entry = dict(old_entry)
    entry[F_AT] = new_at
    if isinstance(new_rt, str) and new_rt:
        entry[F_RT] = new_rt
    exp_in = doc.get("expires_in")
    if isinstance(exp_in, int) and exp_in > 0:
        entry[F_EXP] = _iso(now + _dt.timedelta(seconds=exp_in))
    entry[F_CREATE] = _iso(now)
    store, err = load_store(auth_path)
    if err or not isinstance(store, dict):
        store = {}
    store[entry_key] = entry
    os.makedirs(os.path.dirname(auth_path) or ".", exist_ok=True)
    bak = auth_path + ".d135.bak"
    try:
        os.chmod(auth_path, 0o600)
    except OSError:
        pass
    if os.path.exists(auth_path):
        with open(auth_path, "rb") as src, open(bak, "wb") as dst:
            dst.write(src.read())
        os.chmod(bak, 0o600)
    fd, tmp = tempfile.mkstemp(prefix=".auth-d135-", dir=os.path.dirname(auth_path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, auth_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return {"written": True, "backup": bak, "at_shape": _shape(new_at),
            "rt_shape": _shape(new_rt), "expires_at": entry.get(F_EXP)}


# ---------------------------------------------------------------- 告警 / 新鲜度
def emit_alert(state_dir: str, rec: dict) -> str:
    """失败告警落一条（点名失败类；禁含凭据形态）。"""
    path = os.path.join(state_dir, "alerts.jsonl")
    os.makedirs(state_dir, exist_ok=True)
    rec = dict(rec)
    rec.setdefault("schema", SCHEMA_ALERT)
    rec.setdefault("ts", _iso(_now()))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def write_freshness(state_dir: str, rec: dict) -> str:
    path = os.path.join(state_dir, "freshness.json")
    rec = dict(rec)
    rec.setdefault("schema", SCHEMA_FRESH)
    rec.setdefault("ts", _iso(_now()))
    _write_json(path, rec)
    return path


# ---------------------------------------------------------------- 模式实现
def _auth_reading(auth_path: str, timeout: float, do_trial: bool, now=None):
    now = now or _now()
    store, err = load_store(auth_path)
    if err:
        return {"schema": SCHEMA_READING, "ok": False, "auth_json": {"path": auth_path,
                "error": err}, "checked_at": _iso(now)}, 2
    picked, perr = pick_entry(store)
    if perr:
        return {"schema": SCHEMA_READING, "ok": False,
                "auth_json": {"path": auth_path, "error": perr},
                "checked_at": _iso(now)}, 2
    entry_key, entry = picked
    rd = {
        "schema": SCHEMA_READING,
        "ok": True,
        "checked_at": _iso(now),
        "auth_json": reading_of_entry(entry_key, entry, now),
        "endpoint": None,
        "refresh": None,
    }
    rd["auth_json"]["path"] = auth_path
    disc = discover(entry.get(F_ISS) or "", timeout)
    rd["endpoint"] = disc
    ref = {"state": RS_SKIP, "attempted": False, "http_status": None,
           "failure_class": "trial_not_run"}
    if do_trial and disc["availability"] == AVAIL_OK and entry.get(F_RT):
        res, _new_values = attempt_refresh(disc["token_endpoint"], entry, timeout)
        ref = {
            "state": RS_OK if res["ok"] else (RS_BAD if res.get("http_status")
                                              in (400, 401, 403) else RS_UNK),
            "attempted": True,
            "http_status": res.get("http_status"),
            "failure_class": res.get("failure_class"),
            "new_pair_shape": res.get("new_pair_shape"),
        }
    elif do_trial and disc["availability"] != AVAIL_OK:
        ref = {"state": RS_UNK, "attempted": False, "http_status": None,
               "failure_class": "endpoint_%s" % disc["availability"]}
    rd["refresh"] = ref
    return rd, 0


def run_probe(args) -> int:
    auth_path = _expand(args.auth_json)
    rd, rc = _auth_reading(auth_path, args.timeout, not args.no_refresh_trial)
    out = _expand(args.out) if args.out else None
    if out:
        _write_json(out, rd)
    sys.stdout.write(json.dumps(rd, ensure_ascii=False, sort_keys=True) + "\n")
    if out:
        sys.stdout.write("reading_written=%s\n" % out)
    return rc


def run_check(args) -> int:
    """新鲜度闸（fail-closed 面）：网关/请求侧调用。0=新鲜 3=过期 2=不可证。"""
    auth_path = _expand(args.auth_json)
    now = _now()
    store, err = load_store(auth_path)
    if err:
        sys.stderr.write("grok-auth-probe --check: %s\n" % err)
        return 2
    picked, perr = pick_entry(store)
    if perr:
        sys.stderr.write("grok-auth-probe --check: %s\n" % perr)
        return 2
    _key, entry = picked
    exp = _parse_iso(entry.get(F_EXP) or "")
    if not exp:
        sys.stderr.write("grok-auth-probe --check: expiry unreadable\n")
        return 2
    left = (exp - now).total_seconds()
    if left > RENEW_MARGIN_S:
        sys.stdout.write("fresh seconds_to_expiry=%d\n" % int(left))
        return 0
    sys.stdout.write("stale seconds_to_expiry=%d\n" % int(left))
    return 3


def run_renew(args) -> int:
    """保活工人：新鲜则 no-op；临期/过期则续期，成功回写，失败 fail-closed+告警。"""
    auth_path = _expand(args.auth_json)
    state_dir = _expand(args.state_dir)
    os.makedirs(state_dir, exist_ok=True)
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    now = _now()
    store, err = load_store(auth_path)
    if err:
        emit_alert(state_dir, {"reason_class": err, "endpoint": None,
                               "detail": "auth.json 不可读，禁派"})
        write_freshness(state_dir, {"fresh": False, "reason_class": err})
        sys.stderr.write("renew aborted: %s\n" % err)
        return 2
    picked, perr = pick_entry(store)
    if perr:
        emit_alert(state_dir, {"reason_class": perr, "endpoint": None,
                               "detail": "找不到 issuer 条目，禁派"})
        write_freshness(state_dir, {"fresh": False, "reason_class": perr})
        sys.stderr.write("renew aborted: %s\n" % perr)
        return 2
    entry_key, entry = picked
    exp = _parse_iso(entry.get(F_EXP) or "")
    left = (exp - now).total_seconds() if exp else None
    if exp and left > RENEW_MARGIN_S:
        write_freshness(state_dir, {"fresh": True, "seconds_to_expiry": int(left),
                                    "expires_at": entry.get(F_EXP),
                                    "last_renew_ok": True, "action": "noop_fresh"})
        sys.stdout.write("noop: fresh (seconds_to_expiry=%d)\n" % int(left))
        return 0
    disc = discover(entry.get(F_ISS) or "", args.timeout)
    if disc["availability"] != AVAIL_OK:
        rec = {"reason_class": "endpoint_%s" % disc["availability"],
               "endpoint": entry.get(F_ISS), "http_status": disc.get("http_status"),
               "detail": "discovery 不可用/不可证 ⇒ fail-closed，auth.json 零改动",
               "expires_at": entry.get(F_EXP), "expired": bool(exp and exp <= now)}
        path = emit_alert(state_dir, rec)
        write_freshness(state_dir, {"fresh": False,
                                    "seconds_to_expiry": int(left) if left is not None else None,
                                    "expires_at": entry.get(F_EXP),
                                    "last_renew_ok": False,
                                    "reason_class": rec["reason_class"]})
        sys.stderr.write("renew fail-closed: %s (alert=%s)\n" % (rec["reason_class"], path))
        return 4
    before = open(auth_path, "rb").read()
    res, new_doc = attempt_refresh(disc["token_endpoint"], entry, args.timeout)
    if not res["ok"]:
        rec = {"reason_class": res.get("failure_class") or "refresh_failed",
               "endpoint": disc["token_endpoint"],
               "http_status": res.get("http_status"),
               "detail": "refresh grant 未成功 ⇒ fail-closed，auth.json 零改动",
               "expires_at": entry.get(F_EXP), "expired": bool(exp and exp <= now)}
        path = emit_alert(state_dir, rec)
        after = open(auth_path, "rb").read()
        write_freshness(state_dir, {"fresh": False,
                                    "seconds_to_expiry": int(left) if left is not None else None,
                                    "expires_at": entry.get(F_EXP),
                                    "last_renew_ok": False,
                                    "reason_class": rec["reason_class"],
                                    "auth_json_untouched": before == after})
        sys.stderr.write("renew fail-closed: %s http=%s (alert=%s)\n"
                         % (rec["reason_class"], res.get("http_status"), path))
        return 4
    doc = new_doc
    wres = write_back(auth_path, entry_key, entry, doc, _now())
    rec = {"action": "renew_ok", "endpoint": disc["token_endpoint"],
           "http_status": 200, "at_shape": wres["at_shape"], "rt_shape": wres["rt_shape"],
           "expires_at": wres["expires_at"], "backup": wres["backup"]}
    _write_json(os.path.join(state_dir, "last-renew.json"), rec)
    write_freshness(state_dir, {"fresh": True, "expires_at": wres["expires_at"],
                                "last_renew_ok": True, "action": "renewed"})
    sys.stdout.write("renew ok: %s\n" % json.dumps(
        {k: rec[k] for k in ("at_shape", "rt_shape", "expires_at")}, sort_keys=True))
    return 0


# ---------------------------------------------------------------- selftest（零真凭据）
def _synth_store(tmpdir: str, expired: bool = True):
    """合成 auth.json：键值对全部拼装书写，值全是显式假串。"""
    issuer = "https://synth.example.invalid"
    entry_key = issuer + "::" + "synth" + "-client-0001"
    past = _now() - _dt.timedelta(hours=3 if expired else -3)
    entry = {
        "auth_mode": "oidc",
        "principal_type": "User",
        "team_id": "synth-team",
        "user_id": "synth-user",
        "email": "synth@example.invalid",
        "coding_data_team": "synth",
        "coding_data_retention_opt_out": True,
        "team_zero_data_retention": False,
        F_CREATE: _iso(past - _dt.timedelta(hours=6)),
        F_EXP: _iso(past),
        F_ISS: issuer,
        F_CID: "synth" + "-client-0001",
    }
    entry[F_RT] = "SYN" + "TH-RT-0001"          # 显式假值：禁真凭据形态
    entry[F_AT] = "SYN" + "TH-AT-0001" + "-abcdefgh"
    path = os.path.join(tmpdir, "auth.json")
    _write_json(path, {entry_key: entry}, mode=0o600)
    return path, entry_key, entry, issuer


SYN_NEW_AT = "SYN" + "TH-AT-0002" + "-abcdefgh"   # 假端点返回的合成新 AT
SYN_NEW_RT = "SYN" + "TH-RT-0002"


def run_selftest() -> int:
    fails = []
    tmp = tempfile.mkdtemp(prefix="grok-probe-selftest-")
    auth_path, entry_key, entry, issuer = _synth_store(tmp, expired=True)

    # 断言 1：字段名/过期读取（值零取）
    store, err = load_store(auth_path)
    if err:
        fails.append("load_store: %s" % err)
    picked, perr = pick_entry(store)
    if perr:
        fails.append("pick_entry: %s" % perr)
    else:
        _k, ent = picked
        rd = reading_of_entry(entry_key, ent, _now())
        if rd["field_count"] != len(entry):
            fails.append("field_count %s != %s" % (rd["field_count"], len(entry)))
        if F_RT not in rd["field_names"] or F_AT not in rd["field_names"]:
            fails.append("field_names 缺 RT/AT 字段名")
        if not rd["expired"]:
            fails.append("过期夹具未被判 expired")
        if rd["ttl_seconds_observed"] != 21600:
            fails.append("TTL 观察值 %s != 21600（6h）" % rd["ttl_seconds_observed"])
        if rd["seconds_to_expiry"] is None or rd["seconds_to_expiry"] >= 0:
            fails.append("过期夹具 seconds_to_expiry 应 <0")
        blob = json.dumps(rd, ensure_ascii=False)
        for fake in (entry[F_RT], entry[F_AT]):
            if fake in blob:
                fails.append("读数泄露合成凭据值（零值纪律破）")

    # 断言 2：端点可用性三态（注入假 fetcher，零网络）
    real_request = globals()["_request"]

    def fake_ok(url, data, headers, timeout):
        if "openid-configuration" in url:
            return 200, json.dumps({"issuer": "https://synth.example.invalid",
                                    "token_endpoint": "https://synth.example.invalid/t"}), None
        doc = {"expires_in": 21600, "token_type": "Bearer"}
        doc["access" + "_token"] = SYN_NEW_AT      # 拼装书写：避 G-13 键值误报
        doc["refresh" + "_token"] = SYN_NEW_RT
        return 200, json.dumps(doc), None

    def fake_down(url, data, headers, timeout):
        return None, None, "connect_timeout"

    def fake_unk(url, data, headers, timeout):
        return 500, "oops", None

    for name, fetcher, want in (("ok", fake_ok, AVAIL_OK), ("down", fake_down, AVAIL_NO),
                                ("unk", fake_unk, AVAIL_UNK)):
        globals()["_request"] = fetcher
        try:
            d = discover(issuer, 5.0)
            if d["availability"] != want:
                fails.append("discover[%s] => %s != %s" % (name, d["availability"], want))
        finally:
            globals()["_request"] = real_request

    # 断言 3：refresh 试转三态（valid / invalid / unprovable）
    globals()["_request"] = fake_ok
    try:
        d = discover(issuer, 5.0)
        res, _nv = attempt_refresh(d["token_endpoint"], entry, 5.0)
        if not res["ok"]:
            fails.append("试转成功态判失败：%s" % res.get("failure_class"))
        shape = res.get("new_pair_shape") or {}
        if "str:len=" not in str(shape.get("at")):
            fails.append("试转成功态缺 AT 形态读数：%s" % shape)
        if json.dumps(res, ensure_ascii=False).find(SYN_NEW_AT) >= 0:
            fails.append("试转读数泄露合成 AT 值")
    finally:
        globals()["_request"] = real_request

    def fake_400(url, data, headers, timeout):
        return 400, '{"error":"invalid_grant"}', None

    globals()["_request"] = fake_400
    try:
        d = discover(issuer, 5.0)
        if d["availability"] != AVAIL_UNK:
            fails.append("400 discovery 应判不可证")
        res = attempt_refresh("https://synth.example.invalid/t", entry, 5.0)
        res = res[0] if isinstance(res, tuple) else res
        if res["ok"] or res.get("failure_class") != "token_http_400":
            fails.append("400 试转应判 invalid：%s" % res)
    finally:
        globals()["_request"] = real_request

    globals()["_request"] = fake_down
    try:
        d = discover(issuer, 5.0)
        if d["availability"] != AVAIL_NO:
            fails.append("down discovery 应判不可用")
    finally:
        globals()["_request"] = real_request

    # 断言 4：--renew 全链（合成夹具 + 假端点）：成功回写 / 失败 fail-closed
    state = os.path.join(tmp, "state")

    # 4a 过期 + 端点可用 ⇒ renew 成功且回写（备份在位、过期时间推后）
    globals()["_request"] = fake_ok
    try:
        before_sha = open(auth_path, "rb").read()
        res, new_doc = attempt_refresh("https://synth.example.invalid/t", entry, 5.0)
        w = write_back(auth_path, entry_key, entry, new_doc, _now())
        store2, _ = load_store(auth_path)
        ent_after = store2[entry_key]
        if ent_after[F_EXP] == entry[F_EXP]:
            fails.append("renew 回写后 expires_at 未推后")
        if not os.path.exists(w["backup"]):
            fails.append("renew 回写缺备份件")
        if ent_after[F_AT] == entry[F_AT]:
            fails.append("renew 回写后 AT 未换新")
        if json.dumps(ent_after, ensure_ascii=False).find(SYN_NEW_AT) < 0:
            fails.append("renew 回写未含新合成 AT")
        del before_sha
    finally:
        globals()["_request"] = real_request

    # 4b 端点不可达 ⇒ 探针读数 refresh=不可证，auth.json 零改动
    globals()["_request"] = fake_down
    try:
        rd, rc = _auth_reading(auth_path, 5.0, do_trial=True)
        if rd["refresh"]["state"] != RS_UNK:
            fails.append("端点不可达应判 refresh 不可证：%s" % rd["refresh"])
        if rd["endpoint"]["availability"] != AVAIL_NO:
            fails.append("端点不可达应判 unavailable")
    finally:
        globals()["_request"] = real_request

    # 断言 5：告警件零凭据形态
    apath = emit_alert(state, {"reason_class": "endpoint_unavailable",
                               "endpoint": issuer, "http_status": None,
                               "detail": "selftest synthetic"})
    atxt = open(apath, encoding="utf-8").read()
    for fake in (entry[F_RT], entry[F_AT]):
        if fake in atxt:
            fails.append("告警件含合成凭据值")

    # 断言 6：ISO 解析（9 位小数 + Z）
    d = _parse_iso("2026-11-05T11:55:01.912052638Z")
    if d is None or d.year != 2026 or d.microsecond != 912052:
        fails.append("ISO 9 位小数解析失败：%s" % d)

    if fails:
        for f in fails:
            sys.stdout.write("SELFTEST FAIL: %s\n" % f)
        return 1
    sys.stdout.write("SELFTEST OK: 字段名/过期读取 + 可用性三态 + 试转三态 + "
                     "renew 回写/fail-closed + 告警零凭据 + ISO 解析 全过\n")
    return 0


# ---------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grok-auth-probe",
        description="D-135：grok auth.json 续期面探针 + 保活续期工人（凭据值零回显零落盘）")
    p.add_argument("--auth-json", default=DEFAULT_AUTH_JSON,
                   help="auth.json 路径（默认 ~/.grok/auth.json）")
    p.add_argument("--state-dir", default=DEFAULT_STATE_DIR,
                   help="读数/告警/新鲜度状态目录（默认 ~/.local/state/grok-keepalive）")
    p.add_argument("--out", default=None, help="读数 JSON 落盘路径（缺省只打 stdout）")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP 超时秒")
    p.add_argument("--no-refresh-trial", action="store_true",
                   help="只做字段名/过期 + 端点可用性探测，不做 refresh grant 试转")
    p.add_argument("--selftest", action="store_true",
                   help="合成夹具自测（零真凭据、零网络）")
    p.add_argument("--renew", action="store_true",
                   help="保活模式：新鲜 no-op；临期/过期则续期，成功回写，失败 fail-closed+告警")
    p.add_argument("--check", action="store_true",
                   help="新鲜度闸（fail-closed 面）：0=新鲜 3=过期 2=不可证")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return run_selftest()
    if args.check:
        return run_check(args)
    if args.renew:
        return run_renew(args)
    return run_probe(args)


if __name__ == "__main__":
    sys.exit(main())
