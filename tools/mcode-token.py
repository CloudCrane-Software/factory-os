#!/usr/bin/env python3
"""mcode-token.py — MiniMax mcode OAuth token 刷新/取用工具（af-harness 专用）

机制（抓包实证 2026-10-20）：
  POST https://account.minimax.cn/oauth2/token
  Content-Type: application/x-www-form-urlencoded
  body: grant_type=refresh_token&refresh_token=<RT>&client_id=mcode-public
  响应: {"access_token":"mmoat_...","expires_in":3600,"refresh_token":"mmort_...",
        "scope":"agent.default","token_type":"Bearer"}
  注意：每次刷新双 token 一起轮换，必须立即写回 auth.json。

并发纪律（2026-10-20 双臂并发事故后新增）：
  刷新是轮换式的——同一个 refresh token 只能用一次。多个进程同时刷新会互相
  把对方的令牌打死（后到者 invalid_grant，先到者若丢响应则新旧 RT 全部作废）。
  因此全部读写走 auth.json 同目录的排他锁；拿到锁后先看令牌是否已被别人刷新
  过（新鲜则直接用），invalid_grant 时重读磁盘上的新 RT 重试一次，网络抖动
  也重试一次。verify 子命令用 1 token 探活，供 af-bench 预检。

用法:
  mcode-token.py get            # 输出当前有效 accessToken（必要时先刷新）——仅供管道消费
  mcode-token.py refresh        # 强制刷新并写回 auth.json
  mcode-token.py expiry         # 打印过期时间（调试用）
  mcode-token.py verify         # 用 1 token 探活 mavis，打印 ok / invalid / expired
密钥纪律: 明文只进管道，绝不写入日志/文档。
"""
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_PATH = os.path.expanduser("~/.minimax/auth/prod/cn/mcode-public/auth.json")
LOCK_PATH = AUTH_PATH + ".lock"
TOKEN_URL = "https://account.minimax.cn/oauth2/token"
MAVIS_URL = "https://agent.minimaxi.com/mavis/api/v1/llm/v1/messages"
CLIENT_ID = "mcode-public"
REFRESH_AHEAD_SEC = 600  # 剩余不足 10 分钟即刷新


def now_ms() -> int:
    return int(time.time() * 1000)


def load_record():
    with open(AUTH_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    key, rec = next(iter(data["records"].items()))
    return data, key, rec


def save(data):
    tmp = AUTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, AUTH_PATH)


def do_refresh(refresh_token: str) -> dict:
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "MiniMaxCode",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"oauth2 refresh HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"oauth2 refresh 网络错误: {e.reason}") from e


def apply_token(data, rec, tok):
    rec["accessToken"] = tok["access_token"]
    if tok.get("refresh_token"):
        rec["refreshToken"] = tok["refresh_token"]
    rec["expiresAtMs"] = now_ms() + int(tok.get("expires_in", 3600)) * 1000
    rec["generation"] = int(rec.get("generation", 0)) + 1
    save(data)


def refresh_locked(data, key, rec) -> dict:
    """持锁刷新；invalid_grant（疑似被并发轮换）与网络错误各重试一次。"""
    for attempt in range(2):
        try:
            tok = do_refresh(rec["refreshToken"].strip())
            apply_token(data, rec, tok)
            return rec
        except RuntimeError as err:
            msg = str(err)
            if attempt == 0 and ("invalid_grant" in msg or "网络错误" in msg):
                if "invalid_grant" in msg:
                    # 可能已被并发进程轮换：重读磁盘，用新 RT 再试
                    data, key, rec = load_record()
                else:
                    time.sleep(2)
                continue
            raise
    raise RuntimeError("oauth2 refresh 重试后仍失败")


def with_lock(fn):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def current_token() -> str:
    def resolve():
        data, key, rec = load_record()
        if int(rec.get("expiresAtMs", 0)) - REFRESH_AHEAD_SEC * 1000 <= now_ms():
            rec = refresh_locked(data, key, rec)
        return rec["accessToken"].strip()
    return with_lock(resolve)


def verify() -> int:
    """1 token 探活 mavis。返回 0=ok，1=invalid，2=expired/其他。"""
    data, key, rec = load_record()
    expired = int(rec.get("expiresAtMs", 0)) <= now_ms()
    token = current_token()
    body = json.dumps({
        "model": "MiniMax-M3.1-Flash-Preview",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    req = urllib.request.Request(MAVIS_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "User-Agent": "MiniMaxCode",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.load(resp)
        print("ok")
        return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:120]
        if "invalid access token" in detail:
            print("expired" if expired else "invalid")
            return 2 if expired else 1
        print(f"http {e.code}: {detail}")
        return 2
    except urllib.error.URLError as e:
        print(f"网络错误: {e.reason}")
        return 2


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"
    try:
        if cmd == "get":
            sys.stdout.write(current_token())
        elif cmd == "refresh":
            rec = with_lock(lambda: refresh_locked(*load_record()))
            print("refreshed, expiry:", time.strftime("%F %T", time.localtime(rec["expiresAtMs"] / 1000)))
        elif cmd == "expiry":
            _, _, rec = load_record()
            print(time.strftime("%F %T", time.localtime(int(rec["expiresAtMs"]) / 1000)))
        elif cmd == "verify":
            sys.exit(verify())
        else:
            sys.exit(f"未知命令 {cmd}")
    except RuntimeError as err:
        # 刷新彻底失败（如 RT 已死）：一行结论 + 退出码 3，供探活脚本判别
        print(f"token 不可用: {err}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
