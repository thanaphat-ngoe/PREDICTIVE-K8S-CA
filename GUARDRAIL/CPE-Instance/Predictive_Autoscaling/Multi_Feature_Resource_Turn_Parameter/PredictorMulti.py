import time
import datetime
import subprocess
import numpy as np
import joblib
import warnings  
import csv  
import os   
from tensorflow.keras.models import load_model

# นำเข้าคลาสสมองกลและระบบจัดการ Node 
from DecisionEngineV2 import DecisionEngine
from node_manager import NodeManager

warnings.filterwarnings("ignore", category=UserWarning, module='sklearn')

# =====================================================================
# 1. CONFIGURATION (MULTI-VARIABLE & AUTO-TUNING)
# =====================================================================

MODEL_PATH = 'Multi-Variable_LSTM_Model.keras'
SCALER_INPUTS_PATH = 'Multi-Var_Scaler_Inputs.pkl'
SCALER_TARGET_PATH = 'Multi-Var_Scaler_Target.pkl'

WINDOW_SIZE = 30
LOOP_INTERVAL = 60 

NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}
AVAILABLE_WORKERS = ["10.35.29.109", "10.35.29.110"]

# 🚨 ระบบ Auto-Tuner Parameters
TEST_PARAMS = [0.85, 0.90, 0.95, 1.00]
current_param_idx = 0

# 🌟 ตั้งสถานะ "ช่วงอุ่นเครื่อง" (Warm-up)
is_warmup = True
current_scale_out = 0.80 # ค่าชั่วคราวสำหรับพยุงคลัสเตอร์ตอนอุ่นเครื่อง
current_log_file = 'autoscaler_log_warmup.csv'

# =====================================================================
# 2. HELPER FUNCTIONS
# =====================================================================

def parse_k8s_value(value_str):
    if not value_str: return 0.0
    value_str = str(value_str).strip()
    try:
        if value_str.endswith('m'):
            return float(value_str.replace('m', '')) / 1000.0
        elif value_str.endswith('Ki'):
            return float(value_str.replace('Ki', '')) / (1024.0 * 1024.0) 
        elif value_str.endswith('Mi'):
            return float(value_str.replace('Mi', '')) / 1024.0 
        elif value_str.endswith('Gi'):
            return float(value_str.replace('Gi', ''))
        return float(value_str)
    except:
        return 0.0

def run_cmd(cmd):
    try: return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except: return ""

def fetch_realtime_data_multivar():
    cluster_cpu_req = 0.0
    cluster_cpu_cap = 0.0
    cluster_mem_req = 0.0
    cluster_mem_cap = 0.0
    
    active_workers = 0
    worker_cpu_usage = 0.0 
    
    for key, node in NODES.items():
        status_out = run_cmd(f"kubectl get node {node} --no-headers | awk '{{print $2}}'")
        if "Ready" in status_out and "NotReady" not in status_out:
            
            # 🚨 กรองเฉพาะ Worker ตัด Master ทิ้ง 100%
            if key.startswith('worker'):
                active_workers += 1
                
                # 1. ดึง CPU & Mem Request
                out_req = run_cmd(f"kubectl describe node {node} | grep -A 6 'Allocated resources'")
                for line in out_req.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        if parts[0] == 'cpu':
                            cluster_cpu_req += parse_k8s_value(parts[1])
                        elif parts[0] == 'memory':
                            cluster_mem_req += parse_k8s_value(parts[1])
                
                # 2. ดึง CPU & Mem Capacity
                out_cap_cpu = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.cpu}}'")
                out_cap_mem = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.memory}}'")
                cluster_cpu_cap += parse_k8s_value(out_cap_cpu)
                cluster_mem_cap += parse_k8s_value(out_cap_mem)
                
                # 3. ดึง CPU Usage จริง
                out_usage = run_cmd(f"kubectl top node {node} --no-headers | awk '{{print $2}}'")
                worker_cpu_usage += parse_k8s_value(out_usage)

    current_cpu_percent = 0.0
    if cluster_cpu_cap > 0:
        current_cpu_percent = (worker_cpu_usage / cluster_cpu_cap) * 100

    # 4. ดึง Pending Pods & Running Pods
    pending_count = 0
    try:
        pending_cmd = "kubectl get pods -n default --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = int(run_cmd(pending_cmd))
    except: pass

    running_count = 0
    try:
        running_cmd = "kubectl get pods -n default --field-selector=status.phase=Running --no-headers | wc -l"
        running_count = int(run_cmd(running_cmd))
    except: pass

    ai_features = (cluster_cpu_req, cluster_cpu_cap, cluster_mem_req, cluster_mem_cap, pending_count)
    return ai_features, active_workers, current_cpu_percent, running_count

def init_logger(filename):
    if not os.path.exists(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Workers", "CPU_Usage_%", "Running_Pods", "Pending_Pods", 
                "CPU_Req", "CPU_Cap", "Mem_Req", "Mem_Cap",
                "Predicted_CPU_Req", "Action", "Reason"
            ])

# =====================================================================
# 3. MAIN SYSTEM LOOP
# =====================================================================

print("\n" + "="*60)
print(" 🧠 AUTO-TUNING PREDICTIVE AUTOSCALER (PROD) ")
print("="*60)

try:
    model = load_model(MODEL_PATH, compile=False)
    scaler_inputs = joblib.load(SCALER_INPUTS_PATH)
    scaler_target = joblib.load(SCALER_TARGET_PATH)
    
    # โหลด DecisionEngine พร้อมค่าเริ่มต้นสำหรับ Warm-up
    decision_engine = DecisionEngine(cores_per_node=4.0, max_workers=2, min_workers=1, scale_out_percent=current_scale_out)
    node_bot = NodeManager()
    
    init_logger(current_log_file) 
    print(f"✅ โหลดระบบสำเร็จ! พร้อมเข้าสู่โหมด WARM-UP...")
except Exception as e:
    print(f"❌ Error ตอนโหลดไฟล์: {e}")
    exit()

history_buffer = [] 
print(f"🚀 เริ่มต้น Monitor... (หน่วงเวลา {LOOP_INTERVAL} วิ)\n")

while True:
    try:
        # ==========================================
        # 🚨 ตรวจสอบสัญญาณรอบ (CYCLE_DONE.txt)
        # ==========================================
        if os.path.exists("CYCLE_DONE.txt"):
            os.remove("CYCLE_DONE.txt") # ลบสัญญาณทิ้งทันที
            
            if is_warmup:
                # 🏁 จบ Warm-up -> เริ่มทดลองจริงค่าแรก (0.85)
                is_warmup = False
                current_scale_out = TEST_PARAMS[0]
                current_log_file = f'autoscaler_log_out_{int(current_scale_out*100)}.csv'
                
                decision_engine.scale_out_percent = current_scale_out
                init_logger(current_log_file)
                
                print("\n" + "🔥"*20)
                print(f"🏁 จบช่วง WARM-UP! ประวัติ AI สมบูรณ์แล้ว!")
                print(f"🚀 เริ่มการทดลองจริงที่ scale_out = {current_scale_out}")
                print(f"📁 บันทึกผลลงไฟล์: {current_log_file}")
                print("🔥"*20 + "\n")
                
            else:
                # 🔄 จบรอบทดลองจริง -> เปลี่ยนค่า Parameter ถัดไป
                current_param_idx += 1
                if current_param_idx >= len(TEST_PARAMS):
                    print("\n🎉 ทดสอบครบทุก Parameter แล้ว! ปิดระบบอัตโนมัติ")
                    break # จบโปรแกรมทั้งหมด!
                
                current_scale_out = TEST_PARAMS[current_param_idx]
                current_log_file = f'autoscaler_log_out_{int(current_scale_out*100)}.csv'
                
                decision_engine.scale_out_percent = current_scale_out
                init_logger(current_log_file)
                
                print("\n" + "🚀"*20)
                print(f"🔄 [AUTO-TUNE] เปลี่ยน Parameter เป็น: {current_scale_out}")
                print(f"📁 สร้างไฟล์ Log ใหม่: {current_log_file}")
                print("🚀"*20 + "\n")

        # ==========================================
        # ⚙️ ดำเนินการทำนายและตัดสินใจ
        # ==========================================
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
            mode_text = "WARM-UP" if is_warmup else "TESTING"
            print(f"[{timestamp_short}] ⏳ สะสมประวัติให้ AI ({mode_text})... ({len(history_buffer)}/{WINDOW_SIZE})", end='\r')
            time.sleep(LOOP_INTERVAL) 
            continue

        print(f"\n[{timestamp_short}] " + "━"*50)
        mode_text = "[WARM-UP]" if is_warmup else f"[TEST: {current_scale_out}]"
        print(f"📊 {mode_text} Workers: {current_workers} | CPU Use: {cpu_usage_pct:.1f}% | Run: {running_pods} | Pend: {pending_pods}")
        print(f"    [Metrics] CPU Req/Cap: {cpu_req:.2f}/{cpu_cap:.2f} | Mem Req/Cap: {mem_req:.2f}/{mem_cap:.2f} GB")

        # 3. เตรียมข้อมูลเข้า AI 
        raw_array = np.array(history_buffer) 
        scaled_array = scaler_inputs.transform(raw_array) 
        X_input = scaled_array.reshape(1, WINDOW_SIZE, 5) 
        
        # 4. ทำนายผล
        pred_scaled = model.predict(X_input, verbose=0)
        predicted_cores = scaler_target.inverse_transform(pred_scaled)[0][0]
        print(f"🔮 [AI Predict] อนาคต 5 นาที ➡️ CPU Req จะอยู่ที่: {predicted_cores:.2f} Cores")

        # 5. ตัดสินใจ (Decision Engine)
        action, reason = decision_engine.decide(
            predicted_cores=predicted_cores,
            current_workers=current_workers,
            pending_pods=pending_pods,
            current_cpu_usage=cpu_usage_pct,
            current_cpu_req=cpu_req
        )
        print(f"🤖 [Decision] : {action}\n     [Reason] : {reason}")
        
        # 6. บันทึก Log
        try:
            with open(current_log_file, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_full, current_workers, round(cpu_usage_pct, 2), running_pods, pending_pods,
                    round(cpu_req, 2), round(cpu_cap, 2), round(mem_req, 2), round(mem_cap, 2),
                    round(predicted_cores, 2), action, reason
                ])
        except Exception: pass

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