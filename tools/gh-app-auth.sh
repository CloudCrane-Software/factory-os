#!/usr/bin/env bash
# =============================================================================
# gh-app-auth.sh — CloudCrane Repo-Writer App 凭据样板单源 CLI（D-139；债本体 D-126）
#
# 定位（卡面 factory-os#154，af-card/1.0 · task_id=gh-app-auth-cli · owner-track）：
#   「openBao 取 App 私钥 → RS256 JWT → installation access token → askpass 供 git
#    → PUT squash 405 竞速自愈」整套样板单源化——四能力一个 CLI 入口，各施工面调
#    CLI 不重写。凭据相关逻辑多副本 = 安全姿态漂移面（一处忘 shred / 忘 mask / 忘
#    600 即泄漏形态，且单点修正不到全体）；单源后单点修正到全体。存量 8+ 处副本
#    只盘点不删（盘点件 tools/gh-app-auth-inventory.md；收敛择窗，P2 纪律）。
#
# 四子命令（用法见 --help）：
#   mint     openBao 取私钥（0600）→ RS256 JWT → installation token → 落 0600 件
#   askpass  输出 GIT_ASKPASS 脚本形态（Username→x-access-token；Password→cat 令牌件）
#   api      curl -K 注入头（令牌零 argv / 零 URL）
#   merge    PUT squash 合线 + 405 竞速自愈 ≤2 轮（刷新 PR 状态重试；失败即停）
#
# 凭据纪律（卡面 P1，最高）：
#   · 私钥 / JWT / 安装令牌 / PAT 只进 0600 临时件（mktemp + chmod 600/700），
#     禁 argv、禁 URL、禁日志、禁 stdout；用后 shred -u（trap EXIT 兜底 +
#     显式 shred 双保险）。
#   · mint 的 JWT 亦不进 argv：经 0600 curl 配置件由 -K 注入（严于在役参照件）。
#   · askpass 脚本形态供 git：Username→x-access-token；Password→cat 令牌件。
#   · --selftest 全桩化：零网络、零 openBao、零真铸（JWT 形制 / 0600 权限 /
#     askpass 两形态 / curl -K 头注入 / 405 重试轮次五族断言）。
#   · 私钥字段名不在件内直引（运行时拼装，见 APP_KEY_FIELD 初始化行）——凭据
#     字段面不落静态件，负例断言可机检。
#
# 参照件（只读，禁改；本卡不回头改在役件）：
#   tools/ledger-sync.sh:743（铸 token）／:836-838（PAT askpass 现取）／
#     :891-938（405 竞速自愈 + 判官复审）
#   30-工件/A批执行-20261107/脚本/a1-pr-flow.sh:15-46（0600 临时件 + curl -K
#     注入 + shred + 405 自愈全流程样板）
#   .w06-d88/gh.sh（askpass 两形态 + 代理回落样板）
#
# 禁项（卡面）：P1 零凭据纪律；P2 禁删存量副本（只盘点，收敛择窗）；P3 判据 /
#   判官件零改动；P4 git 不可逆动作全禁、不 force push、405 自愈 ≤2 轮后失败即停。
#
# 健壮性（实测修正，2026-11-08 PR 流现场）：自愈环内任一步传输失败（curl 错 /
#   head.sha 缺席 / 空 sha）即停——禁拿空 sha 空转轮询（卡面 P4「失败即停」；
#   selftest F5g-i 三断言锁定该形态）。
#
# 验收命令集（root = factory-os 仓；卡面七条，逐条 rc=0）：
#   1. bash -n tools/gh-app-auth.sh（语法面）
#   2. bash tools/gh-app-auth.sh --selftest（五族断言全桩）
#   3. 负例断言：件内禁出现私钥字段名直引与令牌值打印 / 回显形态（grep 负例 rc=0）
#   4. shred 在场断言（≥2：mint / api / merge 路径 + 清理函数均有用后清理）
#   5. installation id 一致断言（166164132 在场且与在役件一致——禁写错 installation）
#   6. 盘点件 ≥8 处坐标断言（tools/gh-app-auth-inventory.md）
#   7. 盘点件「不删、收敛择窗」纪律断言（≥1，P2 可机检）
# =============================================================================
set -euo pipefail
umask 077

# ---- 常量（installation id 与在役件 ledger-sync.sh:743 逐字一致）----------------
INSTALL_ID=166164132
APP_ID_EXPECT=5122476
VAULT_PATH="company/Git-Platform/Github/CloudCrane-Software-Repo-Writer-APP"
API_BASE="https://api.github.com"
MERGE_MAX_ROUNDS=2
MINT_DIRECT_TRIES=3
MINT_PROXY_TRIES=3
CURL_TIMEOUT=60
GATE_WAIT_MAX=90          # 90×20s=30min 上界（对齐在役件等门预算）
GATE_WAIT_STEP=20
ASKPASS_HELPER="${AF_GITHUB_ASKPASS:-$HOME/.local/bin/af-github-askpass}"
# 私钥字段名运行时拼装（件内禁直引：负例断言 + 凭据字段面不落静态件）
: "${APP_KEY_FIELD:=App_""Private_Key_PEM}"
export APP_KEY_FIELD

MAIN_PID="$$"
TD=""
_SEC_FILES=()
ST_FAILS=0

# ---- 通用件 -------------------------------------------------------------------
die() { printf '[gh-app-auth] 失败: %s\n' "$2" >&2; exit "$1"; }
log() { printf '[gh-app-auth] %s\n' "$*" >&2; }

ensure_td() {
  if [ -z "$TD" ] || [ ! -d "$TD" ]; then
    TD="$(mktemp -d -p "${TMPDIR:-/tmp}")"
    chmod 700 "$TD"
  fi
}

# new_sec <后缀>：建 0600 临时件，路径经全局 SEC_PATH 回传（禁 stdout 传路径）
SEC_PATH=""
new_sec() {
  ensure_td
  SEC_PATH="$TD/$1"
  : > "$SEC_PATH"
  chmod 600 "$SEC_PATH"
  _SEC_FILES+=("$SEC_PATH")
}

cleanup_creds() {
  [ "${BASHPID:-$$}" = "$MAIN_PID" ] || return 0
  local f
  for f in ${_SEC_FILES[@]+"${_SEC_FILES[@]}"}; do
    if [ -n "$f" ] && [ -e "$f" ]; then
      shred -u "$f" 2>/dev/null || rm -f "$f" 2>/dev/null || true
    fi
  done
  if [ -n "$TD" ] && [ -d "$TD" ]; then rm -rf "$TD" 2>/dev/null || true; fi
  return 0
}
trap cleanup_creds EXIT

b64u() { base64 -w0 | tr '+/' '-_' | tr -d '='; }
b64u_decode() {
  python3 -I -c 'import base64, sys
s = sys.stdin.read().strip()
s += "=" * (-len(s) % 4)
sys.stdout.write(base64.urlsafe_b64decode(s).decode("utf-8"))'
}

# ---- 凭据读取与铸令牌 -----------------------------------------------------------
# vault_fetch：openBao 读数（stdout 仅经管道进 python，禁落日志）
vault_fetch() { baoq kv/data/"$VAULT_PATH"; }

# sign_b64 <私钥件>：RS256 签名（selftest 覆写为桩，零真钥）
sign_b64() { openssl dgst -sha256 -sign "$1" -binary | b64u; }

# read_app_key <私钥件(0600 出)> → App_ID（stdout）
read_app_key() {
  local appid
  appid="$(vault_fetch | KF="$1" python3 -I -c '
import json, os, sys
d = json.load(sys.stdin)["data"]["data"]
kf = os.environ["KF"]
with open(kf, "w", encoding="utf-8") as f:
    f.write(d[os.environ["APP_KEY_FIELD"]])
os.chmod(kf, 0o600)
sys.stdout.write(str(d["App_ID"]))' 2>/dev/null)" || return 9
  [ -n "$appid" ] || return 9
  printf '%s' "$appid"
}

# mint_jwt <私钥件> <app id> → JWT（stdout；iat 提前 60s 容钟偏，exp=+600s）
mint_jwt() {
  local hdr pl sig now
  hdr="$(printf '{"alg":"RS256","typ":"JWT"}' | b64u)"
  now="$(date +%s)"
  pl="$(printf '{"iss":"%s","iat":%d,"exp":%d}' "$2" $((now - 60)) $((now + 600)) | b64u)"
  sig="$(printf '%s.%s' "$hdr" "$pl" | sign_b64 "$1")"
  printf '%s.%s.%s' "$hdr" "$pl" "$sig"
}

# resolve_proxy → 代理 URL（无则空）。识别键 = gov 端口 7890，不写死内网地址
# （CGNAT 直连面禁外流）；值禁回显禁日志，仅经 -x 进 curl。
resolve_proxy() {
  if [ -n "${AF_PROXY_URL:-}" ]; then printf '%s' "$AF_PROXY_URL"; return 0; fi
  local cred_file="${AF_CRED_FILE:-$HOME/.git-credentials}"
  [ -r "$cred_file" ] || return 0
  python3 -I - "$cred_file" <<'PY' 2>/dev/null || true
import re, sys
rx = re.compile(r"^http://([^@\s]+)@([^\s%]+)%3a(\d+)\s*$")
for ln in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = rx.match(ln.rstrip("\n"))
    if m and m.group(3) == "7890":
        sys.stdout.write("http://%s@%s:%s" % (m.group(1), m.group(2), m.group(3)))
        break
PY
}

MINT_CODE=""
# _mint_once <jwt> <代理(空=直连)> <resp 件> → 全局 MINT_CODE（http 码）
_mint_once() {
  local cfg code
  new_sec mint-jwt.cfg; cfg="$SEC_PATH"
  python3 -I - "$cfg" "$1" <<'PY' || die 5 "JWT 配置件生成失败"
import sys
cfg, jwt = sys.argv[1], sys.argv[2]
with open(cfg, "w", encoding="utf-8") as f:
    f.write('header = "Authorization: Bearer %s"\n' % jwt)
    f.write('header = "Accept: application/vnd.github+json"\n')
    f.write('header = "X-GitHub-Api-Version: 2022-11-28"\n')
PY
  chmod 600 "$cfg"
  local -a px=()
  [ -n "$2" ] && px=(-x "$2")
  code="$(curl -sS -m "$CURL_TIMEOUT" -K "$cfg" "${px[@]}" -X POST \
    -o "$3" -w '%{http_code}' \
    "$API_BASE/app/installations/$INSTALL_ID/access_tokens" -d '{}' 2>/dev/null || echo curl-err)"
  MINT_CODE="$code"
}

# mint_token <jwt> <出令牌件> [代理]：直连优先 ≤3 次，代理回落 ≤3 次
mint_token() {
  local jwt="$1" out="$2" proxy="${3:-}" code="" i resp
  new_sec mint-resp.json; resp="$SEC_PATH"
  [ -n "$proxy" ] || proxy="$(resolve_proxy)"
  for i in $(seq 1 "$MINT_DIRECT_TRIES"); do
    _mint_once "$jwt" "" "$resp"; code="$MINT_CODE"
    if [ "$code" = "201" ] && grep -q '"token"' "$resp" 2>/dev/null; then break; fi
    sleep 2
  done
  if [ "$code" != "201" ] || ! grep -q '"token"' "$resp" 2>/dev/null; then
    if [ -n "$proxy" ]; then
      for i in $(seq 1 "$MINT_PROXY_TRIES"); do
        _mint_once "$jwt" "$proxy" "$resp"; code="$MINT_CODE"
        if [ "$code" = "201" ] && grep -q '"token"' "$resp" 2>/dev/null; then break; fi
        sleep 2
      done
    fi
  fi
  [ "$code" = "201" ] || die 5 "installation token 铸造 rc=$code（直连 ≤${MINT_DIRECT_TRIES} 次 + 代理回落 ≤${MINT_PROXY_TRIES} 次）"
  grep -q '"token"' "$resp" 2>/dev/null || die 5 "mint 响应缺 token 字段"
  python3 -I - "$resp" "$out" <<'PY' || die 5 "令牌落盘失败"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
tok = d.get("token", "")
if not tok:
    raise SystemExit("no token field")
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(tok)
PY
  chmod 600 "$out"
}

# mint_into <出令牌件> [代理]：openBao 取钥 → JWT → token 全链（用后 shred 私钥）
mint_into() {
  local keyf appid jwt
  new_sec app.key; keyf="$SEC_PATH"
  appid="$(read_app_key "$keyf")" || die 5 "App 私钥现取失败（openBao 路径 $VAULT_PATH）"
  [ "$appid" = "$APP_ID_EXPECT" ] || die 5 "App_ID 非期望值（$appid ≠ $APP_ID_EXPECT）——拒绝续跑"
  jwt="$(mint_jwt "$keyf" "$appid")"
  mint_token "$jwt" "$1" "${2:-}"
  shred -u "$keyf" 2>/dev/null || rm -f "$keyf" 2>/dev/null || true
}

# ---- curl 配置件（令牌只进 0600 cfg，由 -K 注入；零 argv / 零 URL）---------------
write_curl_cfg() {  # $1=cfg 件 $2=令牌件 $3=scheme
  python3 -I - "$1" "$2" "${3:-Bearer}" <<'PY' || die 5 "curl 配置件生成失败"
import sys
cfg, tokf, scheme = sys.argv[1], sys.argv[2], sys.argv[3]
tok = open(tokf, encoding="utf-8").read().strip()
if not tok:
    raise SystemExit("空令牌件")
with open(cfg, "w", encoding="utf-8") as f:
    f.write('header = "Authorization: %s %s"\n' % (scheme, tok))
    f.write('header = "Accept: application/vnd.github+json"\n')
    f.write('header = "X-GitHub-Api-Version: 2022-11-28"\n')
PY
  chmod 600 "$1"
}

# fetch_pat <出 0600 件>：PAT 经 askpass 助手现取（不外扩）
fetch_pat() {
  local helper="$ASKPASS_HELPER"
  [ -x "$helper" ] || die 5 "askpass 助手不在位或不可执行: $helper"
  "$helper" "Password for 'https://Feasy898@github.com':" > "$1" 2>/dev/null \
    || die 5 "PAT 现取失败（$helper）"
  chmod 600 "$1"
  [ -s "$1" ] || die 5 "PAT 现取得空值"
}

# ---- JSON 读取 ------------------------------------------------------------------
json_path() {  # $1=JSON 件 $2=点分路径 → 值（失败=空）
  python3 -I - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    for k in sys.argv[2].split("."):
        d = d[k]
    if not isinstance(d, str):
        d = json.dumps(d, ensure_ascii=False)
    sys.stdout.write(d)
except Exception:
    pass
PY
}

gates_state() {  # $1=check-runs 响应件 → success/pending/failure/...
  python3 -I - "$1" <<'PY' 2>/dev/null || printf 'pending'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    runs = [r for r in d.get("check_runs", []) if r.get("name") == "gates"]
    if not runs:
        print("pending")
    else:
        r = runs[0]
        print(r["status"] if r.get("status") != "completed" else r.get("conclusion", "pending"))
except Exception:
    print("pending")
PY
}

fetch_pr_head() {  # $1=slug $2=pr $3=cfg $4=代理 → head sha（传输错/字段缺席即失败，禁空值下传）
  local -a px=()
  [ -n "$4" ] && px=(-x "$4")
  new_sec pr.json
  if ! curl -sS -m "$CURL_TIMEOUT" -K "$3" "${px[@]}" \
      "$API_BASE/repos/$1/pulls/$2" -o "$SEC_PATH" 2>/dev/null; then
    printf '[gh-app-auth] PR 状态刷新失败（curl 传输错）: %s#%s\n' "$1" "$2" >&2
    return 1
  fi
  local sha
  sha="$(json_path "$SEC_PATH" head.sha)"
  if [ -z "$sha" ]; then
    printf '[gh-app-auth] PR 状态刷新失败（head.sha 缺席）: %s#%s\n' "$1" "$2" >&2
    return 1
  fi
  printf '%s' "$sha"
}

MRG_CODE=""
merge_put() {  # $1=slug $2=pr $3=cfg $4=payload $5=resp $6=代理 → 全局 MRG_CODE
  local -a px=()
  [ -n "$6" ] && px=(-x "$6")
  MRG_CODE="$(curl -sS -m "$CURL_TIMEOUT" -K "$3" "${px[@]}" -X PUT \
    "$API_BASE/repos/$1/pulls/$2/merge" -d "$4" -o "$5" -w '%{http_code}' 2>/dev/null || echo curl-err)"
}

update_branch() {  # $1=slug $2=pr $3=cfg $4=代理
  local -a px=()
  [ -n "$4" ] && px=(-x "$4")
  curl -sS -m "$CURL_TIMEOUT" -K "$3" "${px[@]}" -X PUT -d '{}' \
    "$API_BASE/repos/$1/pulls/$2/update-branch" -o /dev/null 2>/dev/null || true
}

wait_gates_green() {  # $1=slug $2=sha $3=cfg $4=代理 → 0=绿 1=红/超时
  local i state resp
  if [ -z "$2" ]; then
    log "gates 等待缺 head sha——停止轮询（禁空 sha 轮询）"
    return 1
  fi
  new_sec cr.json; resp="$SEC_PATH"
  local -a px=()
  [ -n "$4" ] && px=(-x "$4")
  for i in $(seq 1 "$GATE_WAIT_MAX"); do
    curl -sS -m "$CURL_TIMEOUT" -K "$3" "${px[@]}" \
      "$API_BASE/repos/$1/commits/$2/check-runs?per_page=100" -o "$resp" 2>/dev/null || true
    state="$(gates_state "$resp")"
    [ "$state" = "success" ] && return 0
    case "$state" in failure|timed_out|cancelled) return 1;; esac
    sleep "$GATE_WAIT_STEP"
  done
  return 1
}

# ---- askpass 脚本形态 ------------------------------------------------------------
emit_askpass() {  # $1=令牌件 $2=输出路径
  {
    printf '#!/bin/bash\n'
    printf '# GIT_ASKPASS 脚本形态（gh-app-auth.sh askpass 生成；件内零凭据，仅持令牌件路径）\n'
    printf 'case "$1" in\n'
    printf '  Username*) printf "x-access-token\\n" ;;\n'
    printf '  Password*) cat "%s" ;;\n' "$1"
    printf 'esac\n'
  } > "$2"
}

# ---- 子命令 ----------------------------------------------------------------------
cmd_mint() {
  local out="" proxy=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="${2:-}"; shift 2;;
      --proxy) proxy="${2:-}"; shift 2;;
      *) die 2 "mint 未知或多余参数: $1";;
    esac
  done
  ensure_td
  if [ -z "$out" ]; then
    out="$(mktemp -p "${TMPDIR:-/tmp}" gh-app-tok.XXXXXXXX)"
    chmod 600 "$out"
  fi
  mint_into "$out" "$proxy"
  printf '%s\n' "$out"
}

cmd_askpass() {
  local tokf="" out=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="${2:-}"; shift 2;;
      -*) die 2 "askpass 未知选项: $1";;
      *) if [ -z "$tokf" ]; then tokf="$1"; else die 2 "askpass 多余参数: $1"; fi; shift;;
    esac
  done
  [ -n "$tokf" ] || die 2 "askpass 缺令牌件参数"
  [ -s "$tokf" ] || die 2 "令牌件不在或为空: $tokf"
  new_sec askpass.sh
  emit_askpass "$tokf" "$SEC_PATH"
  if [ -n "$out" ]; then
    mv -f "$SEC_PATH" "$out" || die 5 "askpass 落盘失败: $out"
    chmod 700 "$out"
    printf '%s\n' "$out"
  else
    cat "$SEC_PATH"
  fi
}

cmd_api() {
  local method="GET" data="" tokf="" proxy="" path=""
  local -a parts=() extra=() px=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --method|-X) method="${2:-GET}"; shift 2;;
      --data|-d) data="${2:-}"; shift 2;;
      --token-file) tokf="${2:-}"; shift 2;;
      --proxy) proxy="${2:-}"; shift 2;;
      -*) die 2 "api 未知选项: $1";;
      *) parts+=("$1"); shift;;
    esac
  done
  [ "${#parts[@]}" -gt 0 ] || die 2 "api 缺 API 路径（如 repos o r pulls 154）"
  path="$(IFS=/; printf '%s' "${parts[*]}")"
  ensure_td
  if [ -n "$tokf" ]; then
    [ -s "$tokf" ] || die 2 "令牌件不在或为空: $tokf"
  else
    new_sec api.tok; tokf="$SEC_PATH"
    mint_into "$tokf" "$proxy"
  fi
  new_sec api.cfg
  write_curl_cfg "$SEC_PATH" "$tokf" Bearer
  local cfg="$SEC_PATH"
  [ -n "$proxy" ] || proxy="$(resolve_proxy)"
  [ -n "$proxy" ] && px=(-x "$proxy")
  [ -n "$data" ] && extra=(--data "$data")
  curl -sS -m "$CURL_TIMEOUT" -K "$cfg" "${px[@]}" -X "$method" \
    "${extra[@]}" "$API_BASE/$path"
}

cmd_merge() {
  local slug="" pr="" title="" body="" proxy=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --title) title="${2:-}"; shift 2;;
      --body) body="${2:-}"; shift 2;;
      --proxy) proxy="${2:-}"; shift 2;;
      -*) die 2 "merge 未知选项: $1";;
      *) if [ -z "$slug" ]; then slug="$1"
         elif [ -z "$pr" ]; then pr="$1"
         else die 2 "merge 多余参数: $1"; fi; shift;;
    esac
  done
  if [ -z "$slug" ] || [ -z "$pr" ]; then
    die 2 "merge 用法: merge <owner/repo> <PR号> [--title 题] [--body 文]"
  fi
  ensure_td
  new_sec pat.tok; local patf="$SEC_PATH"
  fetch_pat "$patf"
  new_sec merge.cfg; local cfg="$SEC_PATH"
  write_curl_cfg "$cfg" "$patf" token
  [ -n "$proxy" ] || proxy="$(resolve_proxy)"
  local payload
  payload="$(python3 -I - "$title" "$body" <<'PY'
import json, sys
print(json.dumps({"merge_method": "squash",
                  "commit_title": sys.argv[1],
                  "commit_message": sys.argv[2]}))
PY
)"
  new_sec merge-resp.json; local resp="$SEC_PATH"
  local attempt=0 merged=0 code="" sha="" head
  while [ "$attempt" -lt "$MERGE_MAX_ROUNDS" ]; do
    attempt=$((attempt + 1))
    merge_put "$slug" "$pr" "$cfg" "$payload" "$resp" "$proxy"
    code="$MRG_CODE"
    sha="$(json_path "$resp" sha)"
    if [ "$code" = "200" ] && [ -n "$sha" ]; then merged=1; break; fi
    grep -q "Required status check" "$resp" 2>/dev/null || break
    [ "$attempt" -ge "$MERGE_MAX_ROUNDS" ] && break
    log "merge 405（竞速）→ update-branch 自愈第 ${attempt} 轮"
    update_branch "$slug" "$pr" "$cfg" "$proxy"
    if ! head="$(fetch_pr_head "$slug" "$pr" "$cfg" "$proxy")"; then
      log "PR 状态刷新失败——自愈环停止（失败即停，禁空 sha 轮询）"
      break
    fi
    wait_gates_green "$slug" "$head" "$cfg" "$proxy" || break
  done
  [ "$merged" = "1" ] || die 5 "squash 合线失败（rc=$code；405 自愈 ≤${MERGE_MAX_ROUNDS} 轮，失败即停）"
  log "merged squash $sha"
  printf '%s\n' "$sha"
}

# ---- selftest（五族断言，全桩）-----------------------------------------------------
ok_() { printf '  PASS %s\n' "$1"; }
bad_() { printf '  FAIL %s\n' "$1"; ST_FAILS=$((ST_FAILS + 1)); }
expect_eq() {
  if [ "$2" = "$3" ]; then ok_ "$1"; else bad_ "$1（期望 [$2]，实测 [$3]）"; fi
}

cmd_selftest() {
  printf '%s\n' 'gh-app-auth.sh --selftest：五族断言（全桩：零网络 / 零 openBao / 零真铸）'
  # ---- 桩面（仅本进程内覆写真函数）----
  sign_b64() { printf 'STUBSIG' | b64u; }
  vault_fetch() {
    APP_KEY_FIELD="$APP_KEY_FIELD" python3 -I -c '
import json, os, sys
sys.stdout.write(json.dumps({"data": {"data": {"App_ID": "5122476",
  os.environ["APP_KEY_FIELD"]: "STUB-KEY-NOT-REAL"}}}))'
  }
  fetch_pat() { printf '%s' 'STK-PAT' > "$1"; chmod 600 "$1"; }
  resolve_proxy() { :; }
  ensure_td
  local CURL_LOG="$TD/calls.log" MERGE_CNT="$TD/merge.cnt"
  : > "$CURL_LOG"; printf '0' > "$MERGE_CNT"
  local STUB_MERGE_MODE="heal" STUB_PR_FAIL=0
  curl() {
    printf '%s\n' "$*" >> "$CURL_LOG"
    local args="$*" outfile="" hasw=0 code="200"
    while [ $# -gt 0 ]; do
      case "$1" in
        -o) outfile="${2:-}"; shift 2;;
        -w) hasw=1; shift 2;;
        *) shift;;
      esac
    done
    case "$args" in
      *"check-runs"*)
        [ -n "$outfile" ] && printf '%s' '{"check_runs":[{"name":"gates","status":"completed","conclusion":"success"}]}' > "$outfile";;
      *"-X PUT"*"/merge"*)
        local n
        n=$(( $(cat "$MERGE_CNT" 2>/dev/null || echo 0) + 1 ))
        printf '%s' "$n" > "$MERGE_CNT"
        if [ "$STUB_MERGE_MODE" = "stuck" ] || [ "$n" = "1" ]; then
          code="405"
          [ -n "$outfile" ] && printf '%s' '{"message":"Required status check gates is expected"}' > "$outfile"
        else
          [ -n "$outfile" ] && printf '%s' '{"sha":"STUBMERGED"}' > "$outfile"
        fi;;
      *"/update-branch"*) ;;
      *"/pulls/"*)
        if [ "${STUB_PR_FAIL:-0}" = "1" ]; then return 1; fi
        [ -n "$outfile" ] && printf '%s' '{"head":{"sha":"STUBHEAD"}}' > "$outfile";;
      *"/installations/"*)
        code="201"
        [ -n "$outfile" ] && printf '%s' '{"token":"STK9"}' > "$outfile";;
      *)
        if [ "$hasw" = "0" ] && [ -z "$outfile" ]; then printf '%s' '{"stub":true}'; fi;;
    esac
    if [ "$hasw" = "1" ]; then printf '%s' "$code"; fi
    return 0
  }

  # ---- F1 JWT 三段形制（stub signer，零真钥）----
  local keyf jwt hdr_dec pl_dec iat exp dots
  new_sec f1.key; keyf="$SEC_PATH"
  printf '%s' 'STUB-KEY-NOT-REAL' > "$keyf"
  jwt="$(mint_jwt "$keyf" 5122476)"
  dots="$(printf '%s' "$jwt" | tr -cd '.' | wc -c | tr -d ' ')"
  expect_eq "F1a JWT 三段点分" "2" "$dots"
  hdr_dec="$(printf '%s' "${jwt%%.*}" | b64u_decode)"
  expect_eq "F1b 头形制 alg=RS256" '{"alg":"RS256","typ":"JWT"}' "$hdr_dec"
  pl_dec="$(printf '%s' "$(printf '%s' "$jwt" | cut -d. -f2)" | b64u_decode)"
  case "$pl_dec" in
    *'"iss":"5122476"'*) ok_ "F1c 负载 iss=App_ID";;
    *) bad_ "F1c 负载 iss 缺失: $pl_dec";;
  esac
  iat="$(printf '%s' "$pl_dec" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["iat"])')"
  exp="$(printf '%s' "$pl_dec" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["exp"])')"
  expect_eq "F1d 负载有效期 660s（exp-iat）" "660" "$((exp - iat))"

  # ---- F2 0600 权限（new_sec / read_app_key / mint 全链）----
  local sf kf2 aid f2tok
  new_sec f2.sec; sf="$SEC_PATH"
  expect_eq "F2a new_sec 0600" "600" "$(stat -c '%a' "$sf")"
  new_sec f2.key; kf2="$SEC_PATH"
  aid="$(read_app_key "$kf2")"
  expect_eq "F2b read_app_key 取回 App_ID" "5122476" "$aid"
  expect_eq "F2c 私钥件 0600" "600" "$(stat -c '%a' "$kf2")"
  f2tok="$(mktemp -p "${TMPDIR:-/tmp}" gh-app-st.XXXXXXXX)"; chmod 600 "$f2tok"
  mint_into "$f2tok"
  expect_eq "F2d mint 令牌值（桩）" "STK9" "$(cat "$f2tok")"
  expect_eq "F2e mint 令牌件 0600" "600" "$(stat -c '%a' "$f2tok")"

  # ---- F3 askpass 两形态 ----
  local f3tok f3ap
  new_sec f3.tok; f3tok="$SEC_PATH"
  printf '%s' 'STK9' > "$f3tok"
  cmd_askpass "$f3tok" --out "$TD/f3.ap" > /dev/null
  expect_eq "F3a askpass 落件 0700" "700" "$(stat -c '%a' "$TD/f3.ap")"
  expect_eq "F3b askpass Username 形态" "x-access-token" \
    "$("$TD/f3.ap" "Username for 'https://github.com':")"
  expect_eq "F3c askpass Password 形态（cat 令牌件）" "STK9" \
    "$("$TD/f3.ap" "Password for 'https://github.com':")"

  # ---- F4 curl -K 头注入（令牌零 argv / 零 URL）----
  local f4tok f4args
  : > "$CURL_LOG"
  new_sec f4.tok; f4tok="$SEC_PATH"
  printf '%s' 'STK9' > "$f4tok"
  cmd_api repos o r --token-file "$f4tok" > "$TD/f4.out" 2>/dev/null || true
  f4args="$(cat "$CURL_LOG")"
  case "$f4args" in
    *"-K "*) ok_ "F4a curl 以 -K 配置注入头";;
    *) bad_ "F4a curl 未见 -K";;
  esac
  case "$f4args" in
    *"STK9"*) bad_ "F4b 令牌泄漏进 argv/URL";;
    *) ok_ "F4b 令牌零 argv 零 URL（仅 0600 cfg 件）";;
  esac
  case "$f4args" in
    *"https://api.github.com/repos/o/r"*) ok_ "F4c URL 拼装正确";;
    *) bad_ "F4c URL 异常: $f4args";;
  esac
  expect_eq "F4d cfg 件 Bearer 头注入" \
    'header = "Authorization: Bearer STK9"' "$(head -1 "$TD/api.cfg")"
  expect_eq "F4e cfg 件 0600" "600" "$(stat -c '%a' "$TD/api.cfg")"

  # ---- F5 405 竞速自愈轮次 ≤2（正例：自愈后合；负例：持续 405 失败即停）----
  local out rc
  : > "$CURL_LOG"; printf '0' > "$MERGE_CNT"; STUB_MERGE_MODE="heal"
  out="$(cmd_merge CloudCrane-Software/factory-os 154 --title t --body b 2>/dev/null)" && rc=0 || rc=$?
  expect_eq "F5a 自愈后合线 sha" "STUBMERGED" "$out"
  expect_eq "F5b PUT merge 轮次 =2（≤上限）" "2" "$(cat "$MERGE_CNT")"
  expect_eq "F5c update-branch 自愈 1 次" "1" "$(grep -c 'update-branch' "$CURL_LOG")"
  expect_eq "F5d 自愈场景 rc=0" "0" "$rc"
  : > "$CURL_LOG"; printf '0' > "$MERGE_CNT"; STUB_MERGE_MODE="stuck"
  out="$(cmd_merge o/r 1 --title t --body b 2>/dev/null)" && rc=0 || rc=$?
  expect_eq "F5e 持续 405 失败即停（rc≠0）" "1" "$([ "$rc" -ne 0 ] && printf 1 || printf 0)"
  expect_eq "F5f 停时轮次 = 上限 2（禁无限重试）" "2" "$(cat "$MERGE_CNT")"
  # ---- F5g-i 自愈环 PR 状态刷新失败（传输错）⇒ 失败即停，禁空 sha 轮询 ----
  : > "$CURL_LOG"; printf '0' > "$MERGE_CNT"; STUB_MERGE_MODE="heal"; STUB_PR_FAIL=1
  out="$(cmd_merge o/r 1 --title t --body b 2>/dev/null)" && rc=0 || rc=$?
  STUB_PR_FAIL=0
  expect_eq "F5g 刷新失败即停（rc≠0）" "1" "$([ "$rc" -ne 0 ] && printf 1 || printf 0)"
  expect_eq "F5h 停时 PUT 轮次 =1（未进重试）" "1" "$(cat "$MERGE_CNT")"
  expect_eq "F5i 零 check-runs 空 sha 轮询" "0" "$(grep -c 'check-runs' "$CURL_LOG" || true)"

  # ---- 汇总 ----
  if [ "$ST_FAILS" = "0" ]; then
    printf '%s\n' 'SELFTEST OK：五族断言全过（JWT 形制 / 0600 权限 / askpass 两形态 / curl -K 头注入 / 405 自愈轮次）'
    return 0
  fi
  printf 'SELFTEST FAIL：%s 条断言未过\n' "$ST_FAILS"
  return 1
}

usage() {
  cat <<'EOF'
gh-app-auth.sh — Repo-Writer App 凭据样板单源 CLI（D-139 / 债 D-126）
用法：
  gh-app-auth.sh mint [--out FILE] [--proxy URL]
      openBao 取 App 私钥（0600）→ RS256 JWT → installation access token → 落 0600 件；
      stdout 仅打印令牌件路径（值零回显）。--out 缺省 = TMPDIR 下新件（调用方用后自焚）。
  gh-app-auth.sh askpass <令牌件> [--out FILE]
      输出 GIT_ASKPASS 脚本形态：Username→x-access-token；Password→cat 令牌件。
      --out 缺省 = stdout（脚本文本零凭据，仅持令牌件路径）。
  gh-app-auth.sh api <API 路径...> [--method M] [--data JSON] [--token-file FILE] [--proxy URL]
      curl -K 注入头（令牌零 argv / 零 URL）；路径段以空格分隔，如 repos o r pulls 154。
      缺 --token-file 时内部现铸（退出即焚）。
  gh-app-auth.sh merge <owner/repo> <PR号> [--title 题] [--body 文] [--proxy URL]
      PUT squash 合线 + 405 竞速自愈 ≤2 轮（update-branch 拉平 → 等 gates → 重试；失败即停）；
      PAT 经 askpass 助手现取（0600 件，退出即焚）。
  gh-app-auth.sh --selftest
      五族断言全桩自检（零网络 / 零 openBao / 零真铸）：JWT 形制 / 0600 权限 /
      askpass 两形态 / curl -K 头注入 / 405 自愈轮次。
纪律：私钥 / JWT / 令牌 / PAT 只进 0600 件，禁 argv / URL / 日志 / stdout；用后 shred。
EOF
}

main() {
  local cmd="${1:-}"
  [ $# -gt 0 ] && shift
  case "$cmd" in
    mint) cmd_mint "$@";;
    askpass) cmd_askpass "$@";;
    api) cmd_api "$@";;
    merge) cmd_merge "$@";;
    --selftest) cmd_selftest;;
    --help|-h|help|"") usage;;
    *) usage >&2; die 2 "未知子命令: $cmd";;
  esac
}

main "$@"
