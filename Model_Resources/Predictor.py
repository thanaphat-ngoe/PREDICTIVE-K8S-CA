import time
import datetime
import subprocess
import numpy as np
import joblib
import warnings  
from tensorflow.keras.models import load_model

warnings.filterwarnings("ignore", category=UserWarning, module='sklearn')

# ==========================================
# 1. ⚙️ CONFIGURATION
# ==========================================
MODEL_PATH = 'My_LSTM_Model.h5'    # Model เดิม (22 features)
SCALER_PATH = 'scaler.pkl'         # Scaler เดิม
WINDOW_SIZE = 60                   # ต้องตรงกับตอนเทรน
MAX_CPU_CORES = 12.0               # ใช้ตอนแปลงค่ากลับ

NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}

# ==========================================
# 2. 🛠️ HELPER FUNCTIONS (แปลงหน่วยให้ตรง CSV)
# ==========================================
def parse_k8s_value(value_str):
    """
    แปลงค่าจาก K8s เป็นหน่วยมาตรฐานเดียวกับ Prometheus
    - CPU: Cores
    - Memory: Bytes 
    """
    if not value_str: return 0.0
    value_str = str(value_str).strip()
    
    try:
        # --- CPU (Cores) ---
        if value_str.endswith('m'):
            return float(value_str.replace('m', '')) / 1000.0
        
        # --- Memory (Bytes) ---
        if value_str.endswith('Ki'):
            return float(value_str.replace('Ki', '')) * 1024
        if value_str.endswith('Mi'):
            return float(value_str.replace('Mi', '')) * 1024 * 1024
        if value_str.endswith('Gi'):
            return float(value_str.replace('Gi', '')) * 1024 * 1024 * 1024
        if value_str.endswith('Ti'):
            return float(value_str.replace('Ti', '')) * 1024 * 1024 * 1024 * 1024
            
        return float(value_str)
    except:
        return 0.0

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
    except:
        return ""

def get_real_k8s_metrics_22():
    data = {}
    
    # 1. USAGE (kubectl top)
    output_top = run_cmd("kubectl top nodes --no-headers")
    for line in output_top.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            node = parts[0]
            data[f"usage_{node}_cpu"] = parse_k8s_value(parts[1])
            data[f"usage_{node}_mem"] = parse_k8s_value(parts[3])

    # 2. CAP & REQ (kubectl get/describe)
    for key, node in NODES.items():
        # Cap
        out_cap = run_cmd(f"kubectl get node {node} -o jsonpath='{{.status.capacity.cpu}} {{.status.capacity.memory}}'").split()
        if len(out_cap) >= 2:
            data[f"cap_{node}_cpu"] = parse_k8s_value(out_cap[0])
            data[f"cap_{node}_mem"] = parse_k8s_value(out_cap[1])

        # Req
        out_req = run_cmd(f"kubectl describe node {node} | grep -A 5 'Allocated resources' | tail -n 2").splitlines()
        if len(out_req) >= 2:
            try:
                data[f"req_{node}_cpu"] = parse_k8s_value(out_req[0].split()[1])
                data[f"req_{node}_mem"] = parse_k8s_value(out_req[1].split()[1])
            except: pass

    # 3. PENDING (kubectl get pods)
    pending_count = 0.0
    try:
        pending_cmd = "kubectl get pods -A --field-selector=status.phase=Pending --no-headers | wc -l"
        pending_count = float(run_cmd(pending_cmd))
    except: pass

    # 4. ASSEMBLE FEATURES (22 ตัว)
    features = []
    def get(m, n, r): 
        return data.get(f"{m}_{NODES[n]}_{r}", 0.0)

    # --- เรียงตามลำดับเดิมเป๊ะๆ (22 ช่อง) ---
    
    # [0-2] Usage CPU (Master, W1, W2)
    features.extend([get('usage','master','cpu'), get('usage','worker1','cpu'), get('usage','worker2','cpu')])
    
    # [3-5] Usage Mem (Master, W1, W2)
    features.extend([get('usage','master','mem'), get('usage','worker1','mem'), get('usage','worker2','mem')])
    
    # [6] Req CPU Unknown
    features.append(0.0)
    
    # [7-9] Req CPU (Master, W1, W2)
    features.extend([get('req','master','cpu'), get('req','worker1','cpu'), get('req','worker2','cpu')])
    
    # [10] Req Mem Unknown (เติม 0.0)
    features.append(0.0)
    
    # [11-13] Req Mem (Master, W1, W2)
    features.extend([get('req','master','mem'), get('req','worker1','mem'), get('req','worker2','mem')])
    
    # [14-16] Cap CPU (Master, W1, W2)
    features.extend([get('cap','master','cpu'), get('cap','worker1','cpu'), get('cap','worker2','cpu')])
    
    # [17-19] Cap Mem (Master, W1, W2)
    features.extend([get('cap','master','mem'), get('cap','worker1','mem'), get('cap','worker2','mem')])
    
    # [20] Pending Pods
    features.append(pending_count)

    # [21] Target: Total CPU Usag
    features.append(features[0] + features[1] + features[2])

    return features

# ==========================================
# 3. 🚀 MAIN SYSTEM
# ==========================================
print("⏳ Loading Model & Scaler...")
try:
    model = load_model(MODEL_PATH, compile=False)
    scaler = joblib.load(SCALER_PATH)
    print("✅ System Ready (Mode: 22 Features)!")
except Exception as e:
    print(f"❌ Error: {e}")
    exit()

history = []
print(f"🚀 Starting Monitor (Window={WINDOW_SIZE})...")

while True:
    try:
        # 1. Fetch Real Data
        real_features = get_real_k8s_metrics_22()
        
        # 2. Scale Data
        # scaler คาดหวัง 22 features
        scaled_features = scaler.transform([real_features])[0]
        
        # 3. Update Buffer
        history.append(scaled_features)
        if len(history) > WINDOW_SIZE:
            history.pop(0)

        # 4. Process & Predict
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        if len(history) < WINDOW_SIZE:
            print(f"[{timestamp}] สะสมข้อมูล... ({len(history)}/{WINDOW_SIZE})", end='\r')
        else:
            # Prepare Input (1, 60, 22)
            input_np = np.array([history])
            
            # Predict
            pred_scaled = model.predict(input_np, verbose=0)[0][0]
            
            # Inverse Scale (แปลงกลับเป็น Cores)
            # สร้าง Dummy array 22 ช่อง เพื่อหลอก scaler
            dummy = np.zeros((1, 22))
            dummy[0, -1] = pred_scaled # ใส่ค่าที่ทำนายได้ในช่องสุดท้าย (Total CPU)
            pred_cores = scaler.inverse_transform(dummy)[0, -1]
            
            # คำนวณค่าจริงปัจจุบันเพื่อเปรียบเทียบ
            current_cores_scaled = history[-1][-1]
            dummy[0, -1] = current_cores_scaled
            current_cores = scaler.inverse_transform(dummy)[0, -1]

            # Print Result
            print(f"                                                              ", end='\r')
            print(f"[{timestamp}] 📉 จริง: {current_cores:.2f} | 🔮 ทำนาย: {pred_cores:.2f} Cores")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 หยุดการทำงาน")
        break
    except Exception as e:
        print(f"\n❌ Error: {e}")
        time.sleep(5)
