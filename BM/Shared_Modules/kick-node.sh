#!/usr/bin/env bash
# kick-node.sh
# ใช้: ./kick-node.sh <NODE_NAME>

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <NODE_NAME>"
  exit 1
fi

TARGET_NODE="$1"
SSH_USER="testuser"

echo "[*] Kicking node: ${TARGET_NODE}"

# 1) ดึง IP ก่อนลบ node
HOST_IP="$(kubectl get node "${TARGET_NODE}" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)"
if [[ -n "$HOST_IP" ]]; then
  echo "[*] Node IP = ${HOST_IP}"
else
  echo "[!] Cannot detect IP (still continue but remote reset skipped)"
fi

# 2) cordon + drain 
echo "[*] Cordon & drain node: ${TARGET_NODE}"
kubectl cordon "${TARGET_NODE}" || true

kubectl drain "${TARGET_NODE}" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=30 \
  --timeout=3m || true

# 3) delete node 
echo "[*] Deleting node from cluster..."
kubectl delete node "${TARGET_NODE}" || true

# 4) Remote reset
if [[ -n "$HOST_IP" ]]; then
  echo "[*] Resetting worker $TARGET_NODE on $HOST_IP..."

  ssh -o StrictHostKeyChecking=no "${SSH_USER}@${HOST_IP}" "
    echo '[*] kubeadm reset -f';
    sudo kubeadm reset -f || true;

    echo '[*] Stop kubelet';
    sudo systemctl stop kubelet || true;

    echo '[*] Cleaning kubelet, cni cache AND CONFIG';
    sudo rm -rf /var/lib/kubelet /var/lib/cni /etc/cni/net.d || true;

    echo '[*] Removing leftover CNI interfaces';
    sudo ip link delete cni0 2>/dev/null || true;
    sudo ip link delete flannel.1 2>/dev/null || true;
    sudo ip link delete tunl0 2>/dev/null || true; 

    echo '[*] Restart containerd';
    sudo systemctl restart containerd || true;

    echo '[✓] Worker cleaned and ready for next join';
  "
else
  echo "[!] Skipped remote clean (unknown IP)"
fi

echo "[✓] Finished kick-node for ${TARGET_NODE}"
