import time
import datetime
import subprocess
import numpy as np
import joblib
import warnings  
import csv  
import os   
from tensorflow.keras.models import load_model

# นำเข้าคลาสสมองกลและระบบจัดการ Node ของคุณ
from DecisionEngineV2 import DecisionEngine
from node_manager import NodeManager

warnings.filterwarnings("ignore", category=UserWarning, module='sklearn')


# 1.  CONFIGURATION (MULTI-VARIABLE VERSION)

# ใส่ Path ของ Model และ Scaler ตัวใหม่ของคุณตรงนี้
MODEL_PATH = 'Multi_Feature_Resource/Best_Multi_Var_Model.keras'
SCALER_INPUTS_PATH = 'Multi_Feature_Resource/Multi-Var_Scaler_Inputs.pkl'
SCALER_TARGET_PATH = 'Multi_Feature_Resource/Multi-Var_Scaler_Target.pkl'

WINDOW_SIZE = 30
LOG_FILE = 'autoscaler_multi_log.csv' 
LOOP_INTERVAL = 60 

NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}
AVAILABLE_WORKERS = ["10.35.29.109", "10.35.29.110"]

# 2.  HELPER FUNCTIONS

def parse_k8s_value(value_str):
    if not value_str: return 0.0
    value_str = str(value_str).strip()
    try:
        if value_str.endswith('m'):
            return float(value_str.replace('m', '')) / 1000.0
        elif value_str.endswith('Ki'):
            return float(value_str.replace('Ki', '')) / (1024.0 * 1024.0) # แปลง KiB เป็น GB
        elif value_str.endswith('Mi'):
            return float(value_str.replace('Mi', '')) / 1024.0 # แปลง MiB เป็น GB
        elif value_str.endswith('Gi'):
            return float(value_str.replace('Gi', ''))
        return float(value_str)
    except:
        return 0.0

def run_cmd(cmd):
    try: return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except: return ""

# 🌟 ฟังก์ชันดึงข้อมูลดัดแปลงใหม่ให้ดึง Memory และดึงเฉพาะ Worker รวมกัน
def fetch_realtime_data_multivar():
    cluster_cpu_req = 0.0
    cluster_cpu_cap = 0.0
    cluster_mem_req = 0.0
    cluster_mem_cap = 0.0
    
    active_workers = 0
    worker_cpu_usage = 0.0 # ไว้ใช้คำนวณ % ป้อนให้ Decision Engine
    
    for key, node in NODES.items():
        # กรองเฉพาะ Worker (ตามที่เทรนโมเดลมา)
        if key.startswith('worker'):
            status_out = run_cmd(f"kubectl get node {node} --no-headers | awk '{{print $2}}'")
            if "Ready" in status_out and "NotReady" not in status_out:
                active_workers += 1
                
                # 1. ดึง CPU & Mem Request
                out_req = run_cmd(f"kubectl describe node {node} | grep -A 5 'Allocated resources'")
                lines = out_req.splitlines()
                if len(lines) >= 3:
                    try:
                        # สมมติบรรทัดแรกหลัง header คือ CPU, บรรทัดที่สองคือ Memory
                        cpu_req_str = lines[1].split()[1]
                        mem_req_str = lines[2].split()[1]
                        cluster_cpu_req += parse_k8s_value(cpu_req_str)
                        cluster_mem_req += parse_k8s_value(mem_req_str)
                    except: pass
                
                # 2. ดึง CPU & Mem Capacity
                out_cap_cpu = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.cpu}}'")
                out_cap_mem = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.memory}}'")
                cluster_cpu_cap += parse_k8s_value(out_cap_cpu)
                cluster_mem_cap += parse_k8s_value(out_cap_mem)
                
                # ดึง CPU Usage จริง (สำหรับ Guardrail)
                out_usage = run_cmd(f"kubectl top node {node} --no-headers | awk '{{print $2}}'")
                worker_cpu_usage += parse_k8s_value(out_usage)

    # คำนวณ % CPU รวมของ Worker ทั้งหมด
    current_cpu_percent = 0.0
    if cluster_cpu_cap > 0:
        current_cpu_percent = (worker_cpu_usage / cluster_cpu_cap) * 100

    # 3. ดึง Pending Pods
    pending_count = 0
    try:
        pending_cmd = "kubectl get pods -A --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = int(run_cmd(pending_cmd))
    except: pass

    # ดึง Running Pods (ไว้ดู Log)
    running_count = 0
    try:
        running_cmd = "kubectl get pods -A --field-selector=status.phase=Running --no-headers | wc -l"
        running_count = int(run_cmd(running_cmd))
    except: pass

    # คืนค่า 5 ตัวแปรสำหรับ AI + ตัวแปรสำหรับ Decision Engine
    return (cluster_cpu_req, cluster_cpu_cap, cluster_mem_req, cluster_mem_cap, pending_count), \
           active_workers, current_cpu_percent, running_count

#  2.5 ระบบจัดการ LOG

def init_logger():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Workers", "CPU_Usage_%", "Running_Pods", "Pending_Pods", 
                "CPU_Req", "CPU_Cap", "Mem_Req", "Mem_Cap",
                "Predicted_CPU_Req", "Action", "Reason"
            ])


# 3.  MAIN SYSTEM LOOP

print("\n" + "="*55)
print(" 🧠 MULTI-VARIABLE PREDICTIVE AUTOSCALER (PROD) ")
print("="*55)

print("⏳ กำลังโหลดโมเดล Multi-Var AI และ Scalers...")
try:
    model = load_model(MODEL_PATH, compile=False)
    scaler_inputs = joblib.load(SCALER_INPUTS_PATH)
    scaler_target = joblib.load(SCALER_TARGET_PATH)
    
    decision_engine = DecisionEngine(cores_per_node=4.0, max_workers=2, min_workers=1)
    node_bot = NodeManager()
    
    init_logger() 
    print("✅ โหลดระบบ 5-Dimension AI สำเร็จ!")
except Exception as e:
    print(f"❌ Error ตอนโหลดไฟล์: {e}")
    exit()

history_buffer = [] # จะเก็บ List ของ 5 ตัวแปร
print(f"🚀 เริ่มต้น Monitor... (หน่วงเวลา {LOOP_INTERVAL} วิ)\n")

while True:
    try:
        current_dt = datetime.datetime.now()
        timestamp_full = current_dt.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_short = current_dt.strftime("%H:%M:%S")
        
        # 1. ดึงข้อมูล 5 มิติ
        ai_features, current_workers, cpu_usage_pct, running_pods = fetch_realtime_data_multivar()
        cpu_req, cpu_cap, mem_req, mem_cap, pending_pods = ai_features
        
        # 2. เก็บเข้าประวัติ
        history_buffer.append(list(ai_features))
        if len(history_buffer) > WINDOW_SIZE:
            history_buffer.pop(0)

        if len(history_buffer) < WINDOW_SIZE:
            print(f"[{timestamp_short}] ⏳ สะสมประวัติให้ AI... ({len(history_buffer)}/{WINDOW_SIZE}) | CPU Req: {cpu_req:.2f}, Mem Req: {mem_req:.2f}GB", end='\r')
            time.sleep(LOOP_INTERVAL) 
            continue

        print(f"\n[{timestamp_short}] " + "━"*50)
        print(f"📊 [Status] Workers: {current_workers} | CPU Use: {cpu_usage_pct:.1f}% | Run: {running_pods} | Pend: {pending_pods}")
        print(f"    [Metrics] CPU Req/Cap: {cpu_req:.2f}/{cpu_cap:.2f} | Mem Req/Cap: {mem_req:.2f}/{mem_cap:.2f} GB")

        # 3. เตรียมข้อมูลเข้า AI แบบ Multi-Variable
        raw_array = np.array(history_buffer) # Shape: (30, 5)
        scaled_array = scaler_inputs.transform(raw_array) # Scale ด้วย scaler_inputs
        X_input = scaled_array.reshape(1, WINDOW_SIZE, 5) # Reshape เป็น (1, 30, 5)
        
        # 4. ทำนายผลและแปลงกลับ
        pred_scaled = model.predict(X_input, verbose=0)
        # 🚨 จุดสำคัญ: แปลงค่าเป้าหมายกลับด้วย scaler_target
        predicted_cores = scaler_target.inverse_transform(pred_scaled)[0][0]
        
        print(f"🔮 [AI Predict] อนาคต 5 นาที ➡️ CPU Req จะอยู่ที่: {predicted_cores:.2f} Cores")

        # 5. ส่งให้ DecisionEngine ตัดสินใจ (ใช้ Logic เดิมได้เลย!)
        action, reason = decision_engine.decide(
            predicted_cores=predicted_cores,
            current_workers=current_workers,
            pending_pods=pending_pods,
            current_cpu_usage=cpu_usage_pct,
            current_cpu_req=cpu_req
        )
        
        print(f"🤖 [Decision] : {action}")
        print(f"     [Reason] : {reason}")
        
        # 6. บันทึก Log 
        try:
            with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_full, current_workers, round(cpu_usage_pct, 2), running_pods, pending_pods,
                    round(cpu_req, 2), round(cpu_cap, 2), round(mem_req, 2), round(mem_cap, 2),
                    round(predicted_cores, 2), action, reason
                ])
        except Exception as log_err: pass

        # 7. ลงมือทำ
        if action == "SCALE_OUT":
            if current_workers < len(AVAILABLE_WORKERS):
                target_ip = AVAILABLE_WORKERS[current_workers]
                print(f"🚀 [ACTUATOR] กำลังเรียกเครื่อง {target_ip}...")
                node_bot.scale_up(target_ip)
        elif action == "SCALE_IN":
            if current_workers > 0:
                target_ip = AVAILABLE_WORKERS[current_workers - 1]
                print(f"🔻 [ACTUATOR] กำลังปิดเครื่อง {target_ip}...")
                node_bot.scale_down(target_ip)

        print("━"*56)
        time.sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n🛑 ปิดระบบ (Ctrl+C)")
        break
    except Exception as e:
        print(f"\n❌ Error: {e}")
        time.sleep(5)
