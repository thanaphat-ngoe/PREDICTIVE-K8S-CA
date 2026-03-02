import subprocess
import time
import random
import datetime

# --- CONFIGURATION ---
DEPLOYMENT = "cpu-stressor-ds"
NAMESPACE = "default"
LOGFILE = "organic_workload.log"

# --- PARAMETERS ---
MIN_REPLICAS = 4
MAX_REPLICAS = 40
SLEEP_MIN_SEC = 30
SLEEP_MAX_SEC = 60

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{timestamp} | {message}"
    print(text)
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def scale_deployment(replicas):
    cmd = f"kubectl scale deploy/{DEPLOYMENT} -n {NAMESPACE} --replicas={replicas}"
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        log(f"❌ Error scaling: {e}")

def get_next_step(current, trend):
    change = 0
    dice = random.randint(0, 100)

    if trend == 'UP':
        if dice < 70:   change = random.randint(1, 3)   
        elif dice < 90: change = 0                      
        else:           change = -1                     
    elif trend == 'DOWN':
        if dice < 70:   change = random.randint(-3, -1) 
        elif dice < 90: change = 0                      
        else:           change = 1                      

    new_replicas = current + change
    if new_replicas < MIN_REPLICAS: new_replicas = MIN_REPLICAS
    if new_replicas > MAX_REPLICAS: new_replicas = MAX_REPLICAS
    return new_replicas

def main():
    current_replicas = MIN_REPLICAS
    scale_deployment(current_replicas)
    log(f"==== Organic Workload Generator Started (Base: {MIN_REPLICAS}) ====")

    # 🚨 ตรงนี้แหละครับที่เป็นหัวใจหลัก: ลูป Infinity (หมุนวนไปเรื่อยๆ)
    cycle_count = 1
    while True: 
        log("="*40)
        log(f"🔄 เริ่มรัน Cycle ที่ {cycle_count}")
        log("="*40)

        # ==========================================
        # PHASE 1: DAY TIME (Trending UP) ☀️
        # ==========================================
        log(f"\n📈 Starting RAMP UP Phase (Target: approx {MAX_REPLICAS})")
        while current_replicas < MAX_REPLICAS:
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)
            current_replicas = get_next_step(current_replicas, trend='UP')
            scale_deployment(current_replicas)
            print(f"🔼 Ramp Up: {current_replicas} pods (next update in {sleep_sec}s)")

        # ==========================================
        # PHASE 2: PEAK HOUR (Hold High) ⛰️
        # ==========================================
        log("\n⛰️ Reached PEAK. Holding high traffic for a while...")
        hold_time_cycles = random.randint(10, 20) 
        for _ in range(hold_time_cycles):
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)
            noise = random.randint(-2, 2)
            current_replicas += noise
            current_replicas = max(MIN_REPLICAS, min(current_replicas, MAX_REPLICAS + 5))
            scale_deployment(current_replicas)
            print(f"↔️ Peak Hold: {current_replicas} pods")

        # ==========================================
        # PHASE 3: NIGHT TIME (Trending DOWN) 🌙
        # ==========================================
        log(f"\n📉 Starting RAMP DOWN Phase (Target: {MIN_REPLICAS})")
        while current_replicas > MIN_REPLICAS:
            sleep_sec = random.randint(SLEEP_MIN_SEC, SLEEP_MAX_SEC)
            time.sleep(sleep_sec)
            current_replicas = get_next_step(current_replicas, trend='DOWN')
            scale_deployment(current_replicas)
            print(f"🔽 Ramp Down: {current_replicas} pods (next update in {sleep_sec}s)")

        # ==========================================
        # PHASE 4: COOLDOWN HOLD ❄️ (แช่ 15 นาที + ใส่ Noise เล็กๆ)
        # ==========================================
        log(f"\n❄️ Reached {MIN_REPLICAS} pods. Starting COOLDOWN HOLD for 15 minutes...")
        for i in range(15): 
            # สุ่มมีโอกาส 20% ที่กราฟจะกระเพื่อมไป 5 Pods
            if random.randint(1, 100) <= 20:
                current_replicas = MIN_REPLICAS + 1
            else:
                current_replicas = MIN_REPLICAS
                
            scale_deployment(current_replicas)
            print(f"⏳ แช่ฐานที่ {current_replicas} pods... (เหลือเวลาอีก {15-i} นาที)")
            time.sleep(60)

        log(f"🎉 จบ Cycle ที่ {cycle_count} เรียบร้อย! เตรียมเริ่มรอบใหม่ทันที...")
        cycle_count += 1
        # ไม่มี return หรือ break แล้วครับ มันจะวนกลับไปขึ้นบรรทัด while True ใหม่เลย!

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n🛑 Script stopped by user (Ctrl+C).")