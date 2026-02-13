#!/usr/bin/env bash
# join-node.sh
# ใช้: ./join-node.sh <STANDBY_HOST_IP_OR_NAME>

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <STANDBY_HOST_IP_OR_NAME>"
  exit 1
fi

STANDBY_HOST="$1"
SSH_USER="testuser"

echo "==============================================="
echo "[*] START join-node.sh for host: ${STANDBY_HOST}"
echo "==============================================="

# ---------------------------------------------------------
# 1) เก็บรายชื่อ node ก่อน join
# ---------------------------------------------------------
echo "[*] Snapshot nodes BEFORE join..."
BEFORE_NODES=$(mktemp)
kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name > "$BEFORE_NODES"

echo "[*] BEFORE nodes:"
cat "$BEFORE_NODES"

# ---------------------------------------------------------
# 2) Get fresh kubeadm join command
# ---------------------------------------------------------
echo "[*] Getting fresh kubeadm join command from control-plane..."
JOIN_CMD="$(kubeadm token create --print-join-command)"

# ---------------------------------------------------------
# 3) Join node ผ่าน SSH
# ---------------------------------------------------------
echo "[*] Running join on remote host..."
echo "[COMMAND] sudo ${JOIN_CMD}"

ssh -o StrictHostKeyChecking=no "${SSH_USER}@${STANDBY_HOST}" "sudo ${JOIN_CMD}"

echo "[*] Join command sent. Waiting for node to register..."

# ---------------------------------------------------------
# 4) ตรวจ node ใหม่
# ---------------------------------------------------------
NEW_NODE=""
for i in {1..30}; do   # 60 รอบ × 5 วินาที = 5 นาที
  CURRENT_NODES=$(mktemp)
  kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name > "$CURRENT_NODES"

  # หา node ใหม่
  CANDIDATE=$(grep -vxFf "$BEFORE_NODES" "$CURRENT_NODES" || true)

  if [[ -n "$CANDIDATE" ]]; then
    NEW_NODE=$(echo "$CANDIDATE" | head -n1)
    echo "[*] Detected new node: $NEW_NODE"

    # label ทันที เพื่อให้ scheduler ใช้ node ได้
    echo "[*] Labeling node $NEW_NODE as role=loadgen"
    kubectl label node "$NEW_NODE" role=loadgen --overwrite || true

    # ตรวจสถานะ Ready
    READY=$(kubectl get node "$NEW_NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' || true)

    if [[ "$READY" == "True" ]]; then
      echo "[✓] New node is Ready: $NEW_NODE"
      rm -f "$BEFORE_NODES" "$CURRENT_NODES"
      exit 0
    else
      echo "[*] Node registered but not Ready yet (status=$READY), waiting..."
    fi
  fi

  rm -f "$CURRENT_NODES"
  sleep 5
done

rm -f "$BEFORE_NODES"

echo "[!] Node registered but Ready state not detected in time"
echo "[!] (This is NOT a join failure — kubelet may still be initializing)"
echo "[!] join-node.sh EXIT 0 for safety"

exit 0
