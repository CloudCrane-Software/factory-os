#!/bin/bash
# setup-8b-anolis.sh — 把 qwen3:8b 装上 anolis（GGUF 经 CNB 制品库中继而来）。
# 前提：docker.cnb.cool/zhuzhu-team/swev-relay:qwen3-8b-gguf 已存在（CNB 构建 cnb-2sm-1k5bn5laq）。
set -e
WS=/home/pan-ding/workspace/agent黑灯工厂
TOK=$(curl -sS -m 15 -H "X-Vault-Token: $(cat ~/.local/share/openbao-escrow/.root-token)" \
  http://gov-host.invalid:8200/v1/kv/data/company/Git-Platform/CNB/CNB-2-all-privilege | jq -r .data.data.Token)
mkdir -p /home/pan-ding/.cache/s1pull
echo "== 1) 本机 fast-pull 中继镜像 =="
TMPDIR=/home/pan-ding/.cache/s1pull python3 "$WS/tools/fast-pull.py" \
  zhuzhu-team/swev-relay:qwen3-8b-gguf /home/pan-ding/.cache/s1pull/8b.tar \
  --registry docker.cnb.cool --token "$TOK" --jobs 12 --split 8 | tail -2
echo "== 2) ssh docker load 上 anolis =="
ssh -o ConnectTimeout=10 anolis "docker load" < /home/pan-ding/.cache/s1pull/8b.tar | tail -1
echo "== 3) 从镜像里取出 GGUF =="
ssh -o ConnectTimeout=10 anolis 'bash -s' <<'REMOTE'
set -e
cid=$(docker create docker.cnb.cool/zhuzhu-team/swev-relay:qwen3-8b-gguf)
# 找 gguf 在层里的路径
inner=$(docker export "$cid" | tar -t | grep -m1 '\.gguf$' || true)
echo "gguf in layer: $inner"
docker cp "$cid:/$inner" /data/models/qwen3-8b.Q4_K_M.gguf
docker rm "$cid" >/dev/null
docker rmi docker.cnb.cool/zhuzhu-team/swev-relay:qwen3-8b-gguf >/dev/null 2>&1 || true
cat > /tmp/Modelfile-8b <<'EOF'
FROM /data/models/qwen3-8b.Q4_K_M.gguf
PARAMETER num_ctx 32768
PARAMETER temperature 0.7
EOF
ollama create qwen3:8b -f /tmp/Modelfile-8b
curl -s -m 120 http://127.0.0.1:11434/api/generate -d '{"model":"qwen3:8b","prompt":"say hi","stream":false,"options":{"num_predict":4}}' | head -c 200
echo
echo "8B_MODEL_READY"
REMOTE
rm -f /home/pan-ding/.cache/s1pull/8b.tar
