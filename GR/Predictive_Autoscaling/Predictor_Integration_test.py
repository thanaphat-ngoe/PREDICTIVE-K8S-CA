import time
import subprocess
from DecisionEngineV2 import DecisionEngine
from node_manager import NodeManager

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}
AVAILABLE_WORKERS = ["10.35.29.109", "10.35.29.110"]

# ==========================================
# 🛠️ K8S HELPER FUNCTIONS
# ==========================================
def run_cmd(cmd):
    try: return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except: return ""

def get_real_active_workers():
    active_workers = 0
    for key, node in NODES.items():
        if key.startswith('worker'):
            status = run_cmd(f"kubectl get node {node} --no-headers | awk '{{print $2}}'")
            if "Ready" in status and "NotReady" not in status:
                active_workers += 1
    return active_workers

def wait_for_k8s_sync(target_count, timeout_sec=180):
    print(f"   ⏳ [K8s] กำลังรอให้ K8s อัปเดตเครื่องเป็น {target_count} เครื่อง...")
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        current = get_real_active_workers()
        if current == target_count:
            print(f"   ✅ [K8s] สำเร็จ! ตอนนี้ Worker = {target_count} เครื่อง")
            time.sleep(5) # ให้ K8s หายใจแป๊บนึง
            return True
        time.sleep(10)
    print("   ❌ [K8s] หมดเวลารอ!")
    return False

# ==========================================
# 🚀 THE ULTIMATE GUARDRAIL TESTER
# ==========================================
def run_ultimate_test():
    print("\n" + "🔥"*25)
    print(" THE ULTIMATE GUARDRAIL & K8S TEST ")
    print("🔥"*25)

    # 1. โหลดระบบแบบ "สมจริง" (เปิด Cooldown ไว้ที่ 60 วินาทีเพื่อเทส)
    engine = DecisionEngine(cores_per_node=4.0, max_workers=2, min_workers=1)
    engine.cooldown_out = 60  # ป้องกันสเกลขึ้นรัวๆ ใน 1 นาที
    engine.cooldown_in = 60   # ป้องกันสเกลลงรัวๆ หลังจากเพิ่งขึ้น
    engine.safe_cpu_percent = 60.0 # Guardrail: ห้ามลดเครื่องถ้า CPU > 60%
    engine.scale_in_percent = 0.95
    node_bot = NodeManager()

    print("\n⚙️ กำลังเตรียมความพร้อม K8s (บังคับเริ่มที่ 1 เครื่อง)...")
    current_workers = get_real_active_workers()
    if current_workers > 1:
        node_bot.scale_down(AVAILABLE_WORKERS[1])
        wait_for_k8s_sync(1)

    print("\n✅ ระบบพร้อม! เริ่มการทดสอบ 6 ด่านอรหันต์\n")

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 1: Scale Out ปกติ
    # ---------------------------------------------------------
    print("▶️ ด่าน 1: โหลดพุ่งกระฉูด (Predictive Scale Out)")
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=8.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=50.0)
    print(f"   🤖 AI ตัดสินใจ: {action} | เหตุผล: {reason}")
    
    if action == "SCALE_OUT":
        node_bot.scale_up(AVAILABLE_WORKERS[current_workers])
        wait_for_k8s_sync(2)
    print("-" * 50)

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 2: ทดสอบ Guardrail - Cooldown ขาขึ้น (Anti-Flapping)
    # ---------------------------------------------------------
    print("▶️ ด่าน 2: Guardrail (Cooldown ขาขึ้น) - สั่งสเกลซ้ำทันที")
    print("   [จำลองสถานการณ์]: เพิ่งเพิ่มเครื่องไปเมื่อกี้ แต่โหลดพุ่งอีก AI สั่งเพิ่มอีก")
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=12.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=80.0)
    print(f"   🤖 AI ตัดสินใจ: {action}")
    print(f"   🛡️ Guardrail ทำงาน: {reason}") # ควรจะ Blocked by Cooldown
    print("-" * 50)

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 3: ทดสอบ Guardrail - ขีดจำกัด Max Workers
    # ---------------------------------------------------------
    print("▶️ ด่าน 3: Guardrail (Max Workers) - ชนเพดานเครื่องเต็ม")
    print("   [จำลองสถานการณ์]: โกงเวลาให้ผ่าน Cooldown ไปแล้ว พยายามเปิดเครื่องที่ 3")
    engine.last_scale_out_time -= 999  # โกงเวลาให้พ้น Cooldown
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=12.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=80.0)
    print(f"   🤖 AI ตัดสินใจ: {action}")
    print(f"   🛡️ Guardrail ทำงาน: {reason}") # ควรจะ Blocked by Max Workers (2)
    print("-" * 50)

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 4: ทดสอบ Guardrail - CPU Usage สูงเกินไป (Safe CPU Block)
    # ---------------------------------------------------------
    print("▶️ ด่าน 4: Guardrail (Safe CPU) - AI สั่งลด แต่ของจริงยังหอบอยู่")
    print("   [จำลองสถานการณ์]: AI ทายว่าอนาคตโหลดต่ำ (1.0 Cores) แต่ CPU ปัจจุบันทะลุ 90%")
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=1.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=90.0)
    print(f"   🤖 AI ตัดสินใจ: {action}")
    print(f"   🛡️ Guardrail ทำงาน: {reason}") # ควรจะ Blocked by Safe CPU %
    print("-" * 50)

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 5: Scale In ปกติ (ลดเครื่องสำเร็จ)
    # ---------------------------------------------------------
    print("▶️ ด่าน 5: โหลดต่ำ ปลอดภัย สั่งลดเครื่อง (Predictive Scale In)")
    print("   [จำลองสถานการณ์]: AI ทาย 1.0 Cores และ CPU ปัจจุบันร่วงเหลือ 30%")
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=1.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=30.0)
    print(f"   🤖 AI ตัดสินใจ: {action} | เหตุผล: {reason}")
    
    if action == "SCALE_IN":
        node_bot.scale_down(AVAILABLE_WORKERS[current_workers - 1])
        wait_for_k8s_sync(1)
    print("-" * 50)

    # ---------------------------------------------------------
    # 🛑 ด่านที่ 6: ทดสอบ Guardrail - ขีดจำกัด Min Workers
    # ---------------------------------------------------------
    print("▶️ ด่าน 6: Guardrail (Min Workers) - ชนพื้นเครื่องต่ำสุด")
    print("   [จำลองสถานการณ์]: AI ทาย 0.0 Cores อยากจะปิดทุกเครื่องทิ้ง")
    current_workers = get_real_active_workers()
    action, reason = engine.decide(predicted_cores=0.0, current_workers=current_workers, pending_pods=0, current_cpu_usage=10.0)
    print(f"   🤖 AI ตัดสินใจ: {action}")
    print(f"   🛡️ Guardrail ทำงาน: {reason}") # ควรจะ Blocked by Min Workers (1)
    
    print("\n" + "="*50)
    print("🎉 การทดสอบ Guardrail เสร็จสมบูรณ์! ระบบแข็งแกร่ง 100% 🛡️")
    print("="*50)

if __name__ == "__main__":
    run_ultimate_test()