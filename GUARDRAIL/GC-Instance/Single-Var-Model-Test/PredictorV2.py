import time
import datetime
import subprocess
import numpy as np
import joblib
import warnings  
import csv  
import os
import zoneinfo

from tensorflow.keras.models import load_model

from DecisionEngineV2 import DecisionEngine
from NodeManager import NodeManager

warnings.filterwarnings("ignore", category = UserWarning, module = 'sklearn')

# ==========================================
# SYSTEM CONFIGURATION
# ==========================================
TEST_PATH    = 'GUARDRAIL/Predictive-CA/GC-Instance/Single-Var-Model-Test/'
MODEL_PATH   = TEST_PATH + 'Latest-Single-Var-Model.keras'
SCALER_PATH  = TEST_PATH + 'Latest-Single-Var-Scaler.pkl'
LOGFILE_PATH = TEST_PATH + 'Predictive-CA-Log.csv'
WINDOW_SIZE  = 30

# ⏱️ เวลาในการหน่วงแต่ละรอบ (วินาที)
# แนะนำ: ตอนพรีเซนต์/เทสระบบ = 1 | รันบนเซิร์ฟเวอร์จริง = 60
LOOP_INTERVAL = 60

NODES = {'master': 'k8s-master-node', 'worker1': 'k8s-worker-node-1', 'worker2': 'k8s-worker-node-2'}

AVAILABLE_WORKERS = ["10.148.0.8", "10.148.0.9"]

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def parse_k8s_value(value_str):
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
    worker_cpu_usage = 0.0
    worker_cpu_cap = 0.0
    active_workers = 0

    for key, value in NODES.items():
        status_out = run_cmd(f"kubectl get node {value} --no-headers | awk '{{print $2}}'")
        if "Ready" in status_out and "NotReady" not in status_out:
            
            # 🚨 จุดที่แก้: กรองเอาเฉพาะ Worker มาคิด "ทุกอย่าง" รวมถึง Req ด้วย!
            if key.startswith('worker'):
                active_workers += 1
                # 1. ดึง Req (ย้ายเข้ามาอยู่ใน if นึ้แล้ว จะได้ไม่รวม Master)
                out_req = run_cmd(f"kubectl describe node {value} | grep -A 5 'Allocated resources' | tail -n 2")
                try:
                    cpu_req = parse_k8s_value(out_req.splitlines()[0].split()[1])
                    total_cpu_req += cpu_req
                except: pass

                # 2. ดึง Cap & Usage
                out_cap = run_cmd(f"kubectl get node {value} -o jsonpath='{{.status.capacity.cpu}}'")
                worker_cpu_cap += parse_k8s_value(out_cap)

                out_usage = run_cmd(f"kubectl top node {value} --no-headers | awk '{{print $2}}'")
                worker_cpu_usage += parse_k8s_value(out_usage)

    # คำนวณ % การใช้งาน (ส่วนนี้เหมือนเดิม)
    current_cpu_percent = 0.0
    if worker_cpu_cap > 0:
        current_cpu_percent = (worker_cpu_usage / worker_cpu_cap) * 100

    # ดึงจำนวน Pod ใน namespace default (ส่วนนี้เหมือนเดิม ถูกต้องแล้ว)
    running_count = 0
    try:
        running_cmd = "kubectl get pods -n default --field-selector=status.phase=Running --no-headers | wc -l"
        running_count = int(run_cmd(running_cmd))
    except: pass

    pending_count = 0
    try:
        pending_cmd = "kubectl get pods -n default --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = int(run_cmd(pending_cmd))
    except: pass

    return total_cpu_req, active_workers, pending_count, current_cpu_percent, running_count

# ==========================================
# 📝 2.5 ระบบจัดการ LOG (สร้างไฟล์และหัวตาราง)
# ==========================================
def init_logger():
    if not os.path.exists(LOGFILE_PATH):
        with open(LOGFILE_PATH, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", 
                "Current_Workers", 
                "CPU_Usage_Percent", 
                "Running_Pods",
                "Pending_Pods", 
                "Current_Req_Cores", 
                "Predicted_Req_Cores", 
                "Action", 
                "Reason"
            ])
        print(f"📁 สร้างไฟล์ Log ใหม่: {LOGFILE_PATH}")

# ==========================================
# Main Fucntion Define
# ==========================================
def main():
    print("\n" + "="*50)
    print(" 🧠 PREDICTIVE AUTOSCALER ENGINE (PROD. VERSION) ")
    print("="*50)

    print("⏳ Model Loading...")
    
    print("Current Working Directory:", os.getcwd())

    try:
        model  = load_model(os.path.abspath(MODEL_PATH), compile = False)
        scaler = joblib.load(os.path.abspath(SCALER_PATH))
        
        # 🌟 เรียกใช้ DecisionEngineV2 ที่เราอัปเกรด Reason มาใหม่
        decision_engine = DecisionEngine(cores_per_node = 4.0, max_workers = 2, min_workers = 1)
        node_bot = NodeManager()
        
        init_logger() 
        
        print("✅ Model Loaded Successfully!")
    except Exception as e:
        print(f"❌ Error Loading File: {e}")
        exit()

    history_buffer = []
    print(f"🚀 Monitoring... (Fetching the data every {LOOP_INTERVAL} seconds)\n")

    thai_timezone = zoneinfo.ZoneInfo("Asia/Bangkok")

    while True:
        try:
            current_datetime = datetime.datetime.now(tz = thai_timezone)

            print("Current Date Time (UTC+07:00):", current_datetime)
            # print(int(current_datetime.timestamp()))
            
            # ==========================================
            # 1.Fetch the data
            # ==========================================
            cpu_req, current_workers, pending_pods, cpu_usage_pct, running_pods = fetch_realtime_data()
                    
            history_buffer.append([cpu_req])
            if len(history_buffer) > WINDOW_SIZE:
                history_buffer.pop(0)

            # ==========================================
            # 2.Accumulate history until we have enough data for AI to analyze (30 minutes of data with 1-minute intervals)
            # ==========================================
            if len(history_buffer) < WINDOW_SIZE:
                print(f"[{current_datetime}] ⏳ Accumulate history... ({len(history_buffer)} / {WINDOW_SIZE}) | CPU Req: {cpu_req:.2f} Cores", end = '\r')
                time.sleep(LOOP_INTERVAL) 
                continue
            
            # ==========================================
            # 3.Dashboard
            # ==========================================
            print(f"\n[{current_datetime}] " + "━"*45)
            print(f"📊 [K8s Status] Worker Active: {current_workers} | CPU Usage: {cpu_usage_pct:.1f}% |Running Pods: {running_pods} |Pending Pods: {pending_pods}")

            # ==========================================
            # 4.Prepare data for the LSTM model
            # ==========================================
            raw_array = np.array(history_buffer) 
            scaled_array = scaler.transform(raw_array)
            X_input = scaled_array.reshape(1, WINDOW_SIZE, 1)
            
            # ==========================================
            # 5.Perform prediction
            # ==========================================
            pred_scaled = model.predict(X_input, verbose=0)
            predicted_cores = scaler.inverse_transform(pred_scaled)[0][0]
            
            print(f"🔮 [AI Predict] CPU Request ปัจจุบัน {cpu_req:.2f} ➡️  แนวโน้มในอนาคต {predicted_cores:.2f} Cores")

            # ==========================================
            # 6.Make a decision based on the prediction and current predictive logic
            # ==========================================
            action, reason = decision_engine.decide(
                predicted_cores=predicted_cores,
                current_workers=current_workers,
                pending_pods=pending_pods,
                current_cpu_usage=cpu_usage_pct,
                current_cpu_req=cpu_req
            )
            
            print(f"🤖 [Decision] : {action}")
            print(f"     [Reason] : {reason}") 
            
            # 5. บันทึกข้อมูลลง CSV
            try:
                with open(LOGFILE_PATH, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        current_datetime,
                        current_workers,
                        round(cpu_usage_pct, 2),
                        running_pods,
                        pending_pods,
                        round(cpu_req, 2),
                        round(predicted_cores, 2),
                        action,
                        reason
                    ])
            except Exception as log_err:
                print(f"⚠️ ไม่สามารถบันทึก Log ลงไฟล์ได้ ({log_err})")

            # 6. สั่งลงมือทำกับ K8s จริง
            if action == "SCALE_OUT":
                if current_workers < len(AVAILABLE_WORKERS):
                    target_ip = AVAILABLE_WORKERS[current_workers]
                    print(f"🚀 [ACTUATOR] กำลังเรียกเครื่อง {target_ip} เข้ามาช่วยงาน...")
                    node_bot.scale_up(target_ip)
                
            elif action == "SCALE_IN":
                if current_workers > 0:
                    target_ip = AVAILABLE_WORKERS[current_workers - 1]
                    print(f"🔻 [ACTUATOR] กำลังปิดเครื่อง {target_ip} เพื่อประหยัดทรัพยากร...")
                    node_bot.scale_down(target_ip)

            print("━"*58)
            
            # พักระบบตามรอบเวลาที่ตั้งไว้
            time.sleep(LOOP_INTERVAL)
        except KeyboardInterrupt:
            print("\n\n🛑 ปิดระบบ Predictive Autoscaler อย่างปลอดภัย (Ctrl+C)")
            break
        except Exception as e:
            print(f"\n❌ Error ระหว่างรันลูป: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
