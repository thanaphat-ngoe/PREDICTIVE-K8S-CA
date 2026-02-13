#!/bin/bash
# Scale-only (replicas 5–20) with MAX CPU pinned
# Interval: 3–5 min, Reset every 1h -> replicas=2 (CPU stays MAX)

set -euo pipefail

DEPLOYMENT="cpu-stressor-ds"
NAMESPACE="default"
CONTAINER_NAME="stressor"
LOGFILE="./random_load.log"

# === CONFIG ===
MIN_SLEEP=180        # 3 นาที
MAX_SLEEP=300        # 5 นาที
CYCLE_SECONDS=3600   # 1 ชั่วโมง
MIN_REPLICAS=5
MAX_REPLICAS=20

MAX_CPU_M=1000       # "ซัด max" เป็น 1000m (1 core). ปรับได้ตามที่ต้องการ

# หาก image รองรับ flag -cpu=... และอยากให้ตัวโปรเซสในคอนเทนเนอร์ "วิ่งสุด"
# ให้ตั้ง ENABLE_ARG_PATCH=true จะสุ่ม/หรือบังคับเป็น -cpu=1.0 ได้
ENABLE_ARG_PATCH=false
CPU_ARG_VALUE="1.0"  # ถ้าเปิด option ด้านบน จะตั้ง args เป็น -cpu=1.0

log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" | tee -a "$LOGFILE"; }

apply_replicas(){
  kubectl scale deploy/"$DEPLOYMENT" -n "$NAMESPACE" --replicas="$1" \
    2>&1 | tee -a "$LOGFILE"
}

get_image(){
  kubectl get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath="{.spec.template.spec.containers[?(@.name=='$CONTAINER_NAME')].image}"
}

# ตั้ง CPU request/limit = MAX_CPU_M (ทำครั้งแรก และตอน reset เท่านั้น)
pin_max_cpu(){
  local img; img="$(get_image)"
  if [[ -z "$img" ]]; then
    log "ERROR: ไม่พบ image ของคอนเทนเนอร์ '$CONTAINER_NAME'"; exit 1
  fi
  local tmpfile; tmpfile=$(mktemp /tmp/cpu-patch-XXXX.yaml)
  cat > "$tmpfile" <<EOF
spec:
  template:
    spec:
      containers:
      - name: ${CONTAINER_NAME}
        image: ${img}
        resources:
          requests:
            cpu: ${MAX_CPU_M}m
          limits:
            cpu: ${MAX_CPU_M}m
EOF
  kubectl patch deploy/"$DEPLOYMENT" -n "$NAMESPACE" \
    --type=strategic --patch-file "$tmpfile" 2>&1 | tee -a "$LOGFILE"
  rm -f "$tmpfile"
}

# (ทางเลือก) บังคับ args เป็น -cpu=<CPU_ARG_VALUE> เพื่อให้โปรแกรมในคอนเทนเนอร์เร่งสุด
pin_container_arg_cpu(){
  [[ "$ENABLE_ARG_PATCH" != true ]] && return 0
  local img; img="$(get_image)"
  if [[ -z "$img" ]]; then
    log "ERROR: ไม่พบ image ของคอนเทนเนอร์ '$CONTAINER_NAME'"; exit 1
  fi
  local tmpfile; tmpfile=$(mktemp /tmp/args-patch-XXXX.yaml)
  cat > "$tmpfile" <<EOF
spec:
  template:
    spec:
      containers:
      - name: ${CONTAINER_NAME}
        image: ${img}
        args:
          - "-cpu=${CPU_ARG_VALUE}"
          - "-forever"
EOF
  kubectl patch deploy/"$DEPLOYMENT" -n "$NAMESPACE" \
    --type=strategic --patch-file "$tmpfile" 2>&1 | tee -a "$LOGFILE"
  rm -f "$tmpfile"
}

reset_baseline(){
  log "---- Reset hour-cycle: replicas=2, cpu=${MAX_CPU_M}m (pinned) ----"
  apply_replicas 2
  pin_max_cpu
  pin_container_arg_cpu
}

# ===== Start =====
log "==== Random Scale-Only (MAX CPU pinned) Started ===="
reset_baseline

cycle_start=$(date +%s)
first_round=true

while true; do
  now=$(date +%s)
  (( now - cycle_start >= CYCLE_SECONDS )) && { reset_baseline; cycle_start=$(date +%s); }

  replicas=$((RANDOM % (MAX_REPLICAS - MIN_REPLICAS + 1) + MIN_REPLICAS))
  log "Set replicas=${replicas}"
  apply_replicas "$replicas"

  if [ "${first_round}" = true ]; then
    first_round=false
  else
    sleep_time=$((RANDOM % (MAX_SLEEP - MIN_SLEEP + 1) + MIN_SLEEP))
    log "Sleeping ${sleep_time}s..."
    sleep "$sleep_time"
  fi
done
