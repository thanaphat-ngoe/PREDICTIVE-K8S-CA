import subprocess
import time
import random
import datetime

# --- CONFIGURATION ---
DEPLOYMENT = "cpu-stressor-ds"
NAMESPACE = "default"
LOGFILE = "./human_workload.log"

# Config ตามที่คุณระบุ
BASE_REPLICAS = 10          # เริ่มต้นที่ 10
ADD_MIN, ADD_MAX = 5, 10    # สุ่มเพิ่มทีละ 5-10
SLEEP_MIN, SLEEP_MAX = 300, 600 # หน่วงเวลา 5-10 นาที (หน่วยวินาที)

# Config การลดลง
DROP_CHANCE = 0.6           # โอกาสลดลง 60%
STAY_CHANCE = 0.4           # โอกาสเท่าเดิม 40%
DROP_MIN, DROP_MAX = 5, 10  # เวลาลด ก็ลดทีละ 5-10 เหมือนตอนเพิ่ม

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
        log(f"✅ Scaled to {replicas} replicas")
    except subprocess.CalledProcessError as e:
        log(f"❌ Error scaling: {e}")

def get_sleep_time():
    """สุ่มเวลาหน่วง 5-10 นาที"""
    return random.randint(SLEEP_MIN, SLEEP_MAX)

def main():
    current_replicas = BASE_REPLICAS
    log("==== Human-Like Workload Generator Started ====")
    
    # เริ่มต้น Reset ไปที่ค่าต่ำสุดก่อน
    scale_deployment(current_replicas)

    while True:
        # -------------------------------------------------
        # PHASE 1: RAMP UP (ไต่ขึ้นเขา)
        # "สุ่มจำนวนเพิ่มตั้งแต่ 5-10 pod เป็นจำนวน 3 ครั้ง"
        # -------------------------------------------------
        log("--- 📈 Phase 1: Ramp Up (Traffic Coming) ---")
        
        for i in range(1, 4): # วนลูป 3 ครั้ง (รอบที่ 1, 2, 3)
            sleep_sec = get_sleep_time()
            log(f"[Step {i}/3] Sleeping for {sleep_sec//60} mins {sleep_sec%60}s...")
            time.sleep(sleep_sec)
            
            # สุ่มเพิ่ม Pod
            add_amount = random.randint(ADD_MIN, ADD_MAX)
            current_replicas += add_amount
            
            log(f"🚀 Increasing load by {add_amount} pods.")
            scale_deployment(current_replicas)

        # -------------------------------------------------
        # PHASE 2: DECISION & COOL DOWN (ขาลง / ทรงตัว)
        # "ครั้งที่ 4 ให้สุ่มว่าจะลดลงหรือ scale เท่าเดิม... จนกว่าจะต่ำกว่า 10"
        # -------------------------------------------------
        log("--- 📉 Phase 2: User Leaving or Staying (Cooldown) ---")
        
        while current_replicas >= BASE_REPLICAS:
            sleep_sec = get_sleep_time()
            log(f"[Cooldown] Sleeping for {sleep_sec//60} mins {sleep_sec%60}s...")
            time.sleep(sleep_sec)
            
            # ทอยลูกเต๋าตัดสินใจ (0.0 ถึง 1.0)
            dice = random.random()
            
            if dice < DROP_CHANCE: # 60% chance to DROP
                drop_amount = random.randint(DROP_MIN, DROP_MAX)
                current_replicas -= drop_amount
                log(f"🔻 User traffic dropping... (Removing {drop_amount} pods)")
                
            else: # 40% chance to STAY
                log(f"⏸️ User traffic stable... (Holding at {current_replicas} pods)")
                # ไม่ต้องทำอะไรกับ current_replicas
            
            # ป้องกันไม่ให้ค่าติดลบ (Safety check)
            if current_replicas < 0:
                current_replicas = 0
                
            scale_deployment(current_replicas)
            
            # เช็คเงื่อนไขจบ Loop: "จนกว่า pod จะลงมาต่ำกว่า 10"
            if current_replicas < BASE_REPLICAS:
                log("📉 Traffic is low (Below baseline). Resetting loop.")
                current_replicas = BASE_REPLICAS # Reset กลับมาที่ 10 ให้เป๊ะๆ ก่อนเริ่มรอบใหม่
                scale_deployment(current_replicas)
                break # ออกจาก While loop เพื่อกลับไป Phase 1

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("🛑 Script stopped by user.")
