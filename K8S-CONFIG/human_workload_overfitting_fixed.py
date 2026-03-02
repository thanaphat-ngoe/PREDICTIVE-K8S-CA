import subprocess
import time
import random
import datetime
import math

# --- CONFIGURATION ---
DEPLOYMENT = "cpu-stressor-ds"
NAMESPACE = "default"
LOGFILE = "organic_workload.log"

# --- PARAMETERS เพื่อลด Overfitting ---
# ช่วงจำนวน Pod ต่ำสุด - สูงสุด
MIN_REPLICAS = 10
MAX_REPLICAS = 40

# ความถี่ในการปรับ (Update Interval)
# ปรับทุกๆ 30-60 วินาที (เพื่อให้กราฟมีความต่อเนื่อง ไม่นิ่งยาวๆ)
SLEEP_MIN_SEC = 30
SLEEP_MAX_SEC = 60

def log(message):
    """ฟังก์ชันสำหรับเขียน Log ลงไฟล์และหน้าจอ"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{timestamp} | {message}"
    print(text)
    with open(LOGFILE, "a") as f:
        f.write(text + "\n")

def scale_deployment(replicas):
    """สั่ง kubectl scale"""
    cmd = f"kubectl scale deploy/{DEPLOYMENT} -n {NAMESPACE} --replicas={replicas}"
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL)
        # log(f"✅ Scaled to {replicas} replicas") # ปิด log ถี่ๆ เพื่อไม่ให้รกหน้าจอ
    except subprocess.CalledProcessError as e:
        log(f"❌ Error scaling: {e}")

def get_next_step(current, trend):
    """
    คำนวณจำนวน Pod ถัดไป โดยใส่ Noise เข้าไปเพื่อให้กราฟดูสมจริง
    trend: 'UP' หรือ 'DOWN'
    """
    change = 0
    
    # ทอยลูกเต๋า (0-100)
    dice = random.randint(0, 100)

    if trend == 'UP':
        # ขาขึ้น: เน้นบวก แต่มีโอกาสลบเล็กน้อย (Noise)
        if dice < 70:   change = random.randint(1, 3)   # 70% ขึ้น 1-3
        elif dice < 90: change = 0                      # 20% เท่าเดิม
        else:           change = -1                     # 10% แอบลด (Noise)
        
    elif trend == 'DOWN':
        # ขาลง: เน้นลบ แต่มีโอกาสเด้งขึ้นเล็กน้อย (Noise)
        if dice < 70:   change = random.randint(-3, -1) # 70% ลด 1-3
        elif dice < 90: change = 0                      # 20% เท่าเดิม
        else:           change = 1                      # 10% แอบขึ้น (Noise)

    # คำนวณค่าใหม่
    new_replicas = current + change

    # บังคับให้อยู่ในกรอบ MIN - MAX
    if new_replicas < MIN_REPLICAS: new_replicas = MIN_REPLICAS
    if new_replicas > MAX_REPLICAS: new_replicas = MAX_REPLICAS
    
    return new_replicas

def main():
    current_replicas = MIN_REPLICAS
    scale_deployment(current_replicas)
    log(f"==== Organic Workload Generator Started (Base: {MIN_REPLICAS}) ====")

    while True:
        # ==========================================
        # PHASE 1: DAY TIME (Trending UP) ☀️
        # ==========================================
        log(f"📈 Starting RAMP UP Phase (Target: approx {MAX_REPLICAS})")
        
        # วนลูปจนกว่าจะถึงยอดดอย (หรือใกล้เคียง)
        while current_replicas < MAX_REPLICAS:
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)

            current_replicas = get_next_step(current_replicas, trend='UP')
            scale_deployment(current_replicas)
            
            # Log ทุกๆ ครั้งที่มีการเปลี่ยนค่า
            print(f"🔼 Ramp Up: {current_replicas} pods (next update in {sleep_sec}s)")

        # ==========================================
        # PHASE 2: PEAK HOUR (Hold High) ⛰️
        # ==========================================
        log("⛰️ Reached PEAK. Holding high traffic for a while...")
        hold_time_cycles = random.randint(10, 20) # ถือค้างไว้สัก 10-20 รอบ (ประมาณ 10-15 นาที)
        
        for _ in range(hold_time_cycles):
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)
            
            # ช่วง Peak ให้สวิงขึ้นๆ ลงๆ แถวๆ ยอดดอย
            noise = random.randint(-2, 2)
            current_replicas += noise
            # Limit check
            current_replicas = max(MIN_REPLICAS, min(current_replicas, MAX_REPLICAS + 5))
            
            scale_deployment(current_replicas)
            print(f"↔️ Peak Hold: {current_replicas} pods")

        # ==========================================
        # PHASE 3: NIGHT TIME (Trending DOWN) 🌙
        # ==========================================
        log(f"📉 Starting RAMP DOWN Phase (Target: {MIN_REPLICAS})")

        while current_replicas > MIN_REPLICAS:
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)

            current_replicas = get_next_step(current_replicas, trend='DOWN')
            scale_deployment(current_replicas)
            
            print(f"🔽 Ramp Down: {current_replicas} pods (next update in {sleep_sec}s)")

        # พักแป๊บนึงก่อนเริ่มวันใหม่
        log("💤 Cycle Finished. Sleeping briefly before next day...")
        time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Script stopped by user.")
