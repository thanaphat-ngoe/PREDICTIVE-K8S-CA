import time
import datetime
import subprocess
import numpy as np
import joblib
import warnings  
from tensorflow.keras.models import load_model

# นำเข้าคลาสที่เราเขียนไว้
from DecisionEngineV2 import DecisionEngine
from node_manager import NodeManager

warnings.filterwarnings("ignore", category=UserWarning, module='sklearn')

# ==========================================
# 1. ⚙️ CONFIGURATION
# ==========================================
MODEL_PATH = 'best_single_var_model.keras'  # โมเดลตัวใหม่ (1 Feature)
SCALER_PATH = 'scaler.pkl'                  # Scaler ตัวใหม่
WINDOW_SIZE = 30                            # ต้องตรงกับตอนเทรน (ถ้าเทรน 30 ให้ใส่ 30)

NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}

AVAILABLE_WORKERS = ["10.35.29.109", "10.35.29.110"] # IP ของ Worker1, Worker2

# ==========================================
# 2. 🛠️ HELPER FUNCTIONS (ดึงข้อมูล K8s)
# ==========================================
def parse_k8s_value(value_str):
    """ แปลงค่าจาก K8s เป็นหน่วย Cores """
    if not value_str: return 0.0
    value_str = str(value_str).strip()
    try:
        if value_str.endswith('m'):
            return float(value_str.replace('m', '')) / 1000.0
        return float(value_str)
    except:
        return 0.0

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except:
        return ""

def fetch_realtime_data():
    total_cpu_req = 0.0
    
    # --- ตัวแปรใหม่ เอาไว้คิด % เฉพาะฝั่ง Worker ---
    worker_cpu_usage = 0.0
    worker_cpu_cap = 0.0
    active_workers = 0

    for key, node in NODES.items():
        status_out = run_cmd(f"kubectl get node {node} --no-headers | awk '{{print $2}}'")
        if "Ready" in status_out:
            
            # 1. ดึง CPU Request รวมทั้งหมด (เอาไว้ส่งให้ AI)
            out_req = run_cmd(f"kubectl describe node {node} | grep -A 5 'Allocated resources' | tail -n 2")
            try:
                cpu_req = parse_k8s_value(out_req.splitlines()[0].split()[1])
                total_cpu_req += cpu_req
            except: pass

            # 2. กรองเอาเฉพาะ Worker มาคิด % การใช้งานจริง
            if key.startswith('worker'):
                active_workers += 1
                
                # เก็บ Capacity ของ Worker
                out_cap = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.cpu}}'")
                worker_cpu_cap += parse_k8s_value(out_cap)

                # เก็บ Usage ของ Worker
                out_usage = run_cmd(f"kubectl top node {node} --no-headers | awk '{{print $2}}'")
                worker_cpu_usage += parse_k8s_value(out_usage)

    # 3. คำนวณ % CPU Usage ปัจจุบัน (Guardrail ขาลง) จาก Worker ล้วนๆ!
    current_cpu_percent = 0.0
    if worker_cpu_cap > 0:
        current_cpu_percent = (worker_cpu_usage / worker_cpu_cap) * 100

    # 4. นับจำนวน Pending Pods
    pending_count = 0
    try:
        pending_cmd = "kubectl get pods -A --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = int(run_cmd(pending_cmd))
    except: pass

    return total_cpu_req, active_workers, pending_count, current_cpu_percent
    """ 
    ดึงข้อมูล 4 อย่างที่ระบบต้องการ:
    1. total_cpu_req (ส่งให้ AI)
    2. current_workers (ส่งให้ DecisionEngine)
    3. pending_pods (ส่งให้ DecisionEngine)
    4. current_cpu_usage (ส่งให้ DecisionEngine)
    """
    total_cpu_req = 0.0
    total_cpu_usage = 0.0
    total_cpu_cap = 0.0
    active_workers = 0

    # 1. วนลูปเช็คทีละ Node
    for key, node in NODES.items():
        # เช็คว่า Node นี้เปิดอยู่ไหม? (ดูจาก Status Ready)
        status_out = run_cmd(f"kubectl get node {node} --no-headers | awk '{{print $2}}'")
        if "Ready" in status_out:
            if key.startswith('worker'):
                active_workers += 1

            # ดึง Cap (Capacity)
            out_cap = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.cpu}}'")
            total_cpu_cap += parse_k8s_value(out_cap)

            # ดึง Req (CPU Requests) - ตัวแปรสำคัญสำหรับ AI !
            out_req = run_cmd(f"kubectl describe node {node} | grep -A 5 'Allocated resources' | tail -n 2")
            try:
                cpu_req = parse_k8s_value(out_req.splitlines()[0].split()[1])
                total_cpu_req += cpu_req
            except: pass

            # ดึง Usage (CPU ที่ใช้จริงตอนนี้)
            out_usage = run_cmd(f"kubectl top node {node} --no-headers | awk '{{print $2}}'")
            total_cpu_usage += parse_k8s_value(out_usage)

    # 2. คำนวณ % CPU Usage ปัจจุบัน (Guardrail ขาลง)
    current_cpu_percent = 0.0
    if total_cpu_cap > 0:
        current_cpu_percent = (total_cpu_usage / total_cpu_cap) * 100

    # 3. นับจำนวน Pending Pods
    pending_count = 0
    try:
        pending_cmd = "kubectl get pods -A --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = int(run_cmd(pending_cmd))
    except: pass

    return total_cpu_req, active_workers, pending_count, current_cpu_percent

# ==========================================
# 3. 🚀 MAIN SYSTEM LOOP
# ==========================================
print("⏳ กำลังโหลดระบบ Predictive Autoscaling (v2.0)...")
try:
    model = load_model(MODEL_PATH, compile=False)
    scaler = joblib.load(SCALER_PATH)
    
    # สร้างสมอง และ มือ
    decision_engine = DecisionEngine(cores_per_node=4.0, max_workers=2, min_workers=1)
    node_bot = NodeManager()
    
    print("✅ โหลด AI และสมองกลสำเร็จ! ระบบพร้อมทำงาน")
except Exception as e:
    print(f"❌ Error ตอนโหลดไฟล์: {e}")
    exit()

# สร้างกล่องเก็บประวัติ CPU Request 30 นาที (เพื่อส่งให้ AI)
history_buffer = []

print(f"🚀 เริ่มการ Monitor Cluster (สะสมข้อมูลให้ครบ {WINDOW_SIZE} ครั้ง)...\n")

while True:
    try:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        # 1. ดึงข้อมูลสดๆ จาก Cluster
        cpu_req, current_workers, pending_pods, cpu_usage_pct = fetch_realtime_data()
        
        # 2. เก็บประวัติลง Buffer
        history_buffer.append([cpu_req]) # ใส่เป็น List ซ้อน List เพื่อให้ตรงกับโครงสร้าง 2D
        if len(history_buffer) > WINDOW_SIZE:
            history_buffer.pop(0)

        # 3. ถ้าข้อมูลยังสะสมไม่ครบ ให้รอไปก่อน
        if len(history_buffer) < WINDOW_SIZE:
            print(f"[{timestamp}] กำลังสะสมประวัติ CPU Request... ({len(history_buffer)}/{WINDOW_SIZE}) | Req ตอนนี้: {cpu_req:.2f} Cores", end='\r')
            time.sleep(1) # ดึงข้อมูลทุกๆ 1 นาที 
            continue

        print(f"\n[{timestamp}] " + "="*45)
        print(f"📊 [Status] Workers: {current_workers} | CPU Usage: {cpu_usage_pct:.1f}% | Pending Pods: {pending_pods}")

        # 4. แปลงข้อมูลและส่งให้ AI ทำนาย
        # แปลงเป็น Array 2D แล้วเข้า Scaler
        raw_array = np.array(history_buffer) 
        scaled_array = scaler.transform(raw_array)
        
        # ปรับทรงเป็น 3D (1 batch, 30 timesteps, 1 feature) ให้ LSTM
        X_input = scaled_array.reshape(1, WINDOW_SIZE, 1)
        
        # ทำนายผล
        pred_scaled = model.predict(X_input, verbose=0)
        predicted_cores = scaler.inverse_transform(pred_scaled)[0][0]
        
        print(f"🔮 [AI Predict] CPU Request ปัจจุบัน: {cpu_req:.2f} ➡️ แนวโน้ม: {predicted_cores:.2f} Cores")

        # 5. ส่งให้ Decision Engine ตัดสินใจ!
        action, reason = decision_engine.decide(
            predicted_cores=predicted_cores,
            current_workers=current_workers,
            pending_pods=pending_pods,
            current_cpu_usage=cpu_usage_pct
        )
        
        print(f"🤖 [Decision]: {action}")
        print(f"ℹ️ [Reason]  : {reason}")
        
        # 6. สั่งลงมือทำ (Actuator)
        if action == "SCALE_OUT":
            # หา IP ที่ยังไม่ได้เปิด (สมมติว่าถ้า current_workers = 1 แปลว่าเปิด W1 ไปแล้ว, ให้เปิด W2)
            if current_workers < len(AVAILABLE_WORKERS):
                target_ip = AVAILABLE_WORKERS[current_workers]
                print(f"🚀 ACTION: กำลังเรียกเครื่อง {target_ip} เข้ามาช่วยงาน...")
                node_bot.scale_up(target_ip)
            
        elif action == "SCALE_IN":
            # เตะเครื่องตัวล่าสุดออก
            if current_workers > 0:
                target_ip = AVAILABLE_WORKERS[current_workers - 1]
                print(f"🔻 ACTION: โหลดน้อยแล้ว กำลังปิดเครื่อง {target_ip}...")
                node_bot.scale_down(target_ip)

        print("="*58)
        
        # พักรอ 1 นาทีก่อนเช็ครอบถัดไป (หรือจะหน่วง 1 วินาทีตอนเทสก็ได้ครับ)
        time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 ผู้ใช้สั่งหยุดการทำงาน (Ctrl+C)")
        break
    except Exception as e:
        print(f"\n❌ Error ระหว่างรันลูป: {e}")
        time.sleep(5)
