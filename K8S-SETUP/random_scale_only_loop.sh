#!/bin/bash
# Random scale replicas 5–20 every 3–5 minutes (no CPU patch)
# Stop with Ctrl+C

set -euo pipefail

DEPLOYMENT="cpu-stressor-ds"
NAMESPACE="default"
MIN_REPLICAS=10
MAX_REPLICAS=35
MIN_SLEEP=300    # 5 นาที
MAX_SLEEP=600    # 10 นาที
LOGFILE="./random_scale.log"

log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" | tee -a "$LOGFILE"; }

apply_replicas(){
  kubectl scale deploy/"$DEPLOYMENT" -n "$NAMESPACE" --replicas="$1" \
    2>&1 | tee -a "$LOGFILE"
}

log "==== Random Scale-Only Loop Started (replicas ${MIN_REPLICAS}-${MAX_REPLICAS}) ===="

first_round=true
while true; do
  replicas=$((RANDOM % (MAX_REPLICAS - MIN_REPLICAS + 1) + MIN_REPLICAS))
  log "Set replicas=${replicas}"
  apply_replicas "$replicas"

  if [ "$first_round" = true ]; then
    first_round=false     # รอบแรกไม่หน่วง เพื่อเห็นผลทันที
  else
    sleep_time=$((RANDOM % (MAX_SLEEP - MIN_SLEEP + 1) + MIN_SLEEP))
    log "Sleeping ${sleep_time}s..."
    sleep "$sleep_time"
  fi
done
