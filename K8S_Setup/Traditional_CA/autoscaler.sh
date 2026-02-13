#!/usr/bin/env bash
# autoscaler.sh
# ตัดสินใจ join/kick node ตาม Pending Pod + CPU AVG

# เอา -e ออกเพื่อไม่ให้ตายทันทีเวลาเจอคำสั่ง error
set -uo pipefail

CHECK_INTERVAL=30
PENDING_THRESHOLD=2
LOW_CPU_THRESHOLD=25
LOW_CPU_STABLE=3

STANDBY_LIST=( "10.35.29.110" )

PROTECT_NODES=(
  "aj-aung-k8s-master"
  "aj-aung-k8s-worker1"
)

LOGFILE="./autoscaler.log"
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" | tee -a "$LOGFILE"; }

low_cpu_count=0

log "==== AUTOSCALER STARTED (PENDING>${PENDING_THRESHOLD}, CPU<${LOW_CPU_THRESHOLD}% for ${LOW_CPU_STABLE} rounds) ===="

while true; do
  log "== New check =="

  # 1) Pending pods (ไม่เอา kube-system) — ถ้า kubectl error ก็ให้ PENDING=0 ไปก่อน
  PENDING=$(kubectl get pods -A --field-selector=status.phase=Pending 2>/dev/null \
             | awk 'NR>1 && $1!="kube-system"{c++} END{print c+0}') || PENDING=0

  # 2) CPU AVG — ถ้า kubectl top error ให้ CPU_AVG=0
  CPU_AVG=$(kubectl top nodes --no-headers 2>/dev/null \
            | awk '{gsub("%","",$3); if($3!=""){sum+=$3; n++}} END{if(n>0) print int(sum/n); else print 0}') || CPU_AVG=0

  NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo 0)

  log "cluster_state pending=${PENDING}, cpu_avg=${CPU_AVG}%, nodes=${NODE_COUNT}"

  ################ SCALE-OUT: มี pending เกิน threshold ################
  if (( PENDING > PENDING_THRESHOLD )); then
    if ((${#STANDBY_LIST[@]} > 0)); then
      NEXT="${STANDBY_LIST[0]}"
      log "[SCALE-OUT] pending=${PENDING} > ${PENDING_THRESHOLD}, join standby host ${NEXT}"
      ./join-node.sh "${NEXT}" || log "[ERROR] join-node.sh failed for ${NEXT}"
      STANDBY_LIST=("${STANDBY_LIST[@]:1}")
    else
      log "[WARN] SCALE-OUT requested but no standby host left"
    fi
    low_cpu_count=0

  ################ SCALE-IN: ไม่มี pending -> ดู CPU ต่ำต่อเนื่อง ################
  else
    if (( CPU_AVG > 0 && CPU_AVG < LOW_CPU_THRESHOLD )); then
      ((low_cpu_count++))
      log "CPU low round ${low_cpu_count}/${LOW_CPU_STABLE} (CPU_AVG=${CPU_AVG}%)"

      if (( low_cpu_count >= LOW_CPU_STABLE )); then
        # หา node ที่ kick ได้ (ไม่ใช่ PROTECT_NODES)
        PROTECT_REGEX="$(IFS='|'; echo "${PROTECT_NODES[*]}")"
        TARGET=$(kubectl get nodes --no-headers 2>/dev/null \
                   | awk '{print $1}' \
                   | grep -v -E "${PROTECT_REGEX}" 2>/dev/null \
                   | tail -n1) || TARGET=""

        if [[ -n "$TARGET" ]]; then
          log "[SCALE-IN] CPU_AVG=${CPU_AVG}% low for ${LOW_CPU_STABLE} rounds, kick node ${TARGET}"
          ./kick-node.sh "${TARGET}" || log "[ERROR] kick-node.sh failed for ${TARGET}"

          # สมมติ node ที่ถอดคือ VM 10.35.29.110 -> ใส่กลับเข้า STANDBY_LIST
          if [[ ! " ${STANDBY_LIST[*]} " =~ " 10.35.29.110 " ]]; then
            STANDBY_LIST+=( "10.35.29.110" )
            log "[INFO] Return 10.35.29.110 back to STANDBY_LIST"
          fi
        else
          log "[WARN] No non-protected node available to scale-in"
        fi

        low_cpu_count=0
      fi
    else
      low_cpu_count=0
    fi
  fi

  sleep "${CHECK_INTERVAL}"
done
