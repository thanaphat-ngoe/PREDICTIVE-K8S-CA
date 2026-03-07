import subprocess
import json
import time

# --- CONFIG ---
# ชื่อ Node จริงใน Cluster (ต้องตรงกับ kubectl get nodes)
NODES = {
    'master': 'aj-aung-k8s-master',
    'worker1': 'aj-aung-k8s-worker1',
    'worker2': 'aj-aung-k8s-worker2'
}

# --- HELPER FUNCTIONS ---
def parse_k8s_value(value_str):
    """
    แปลงค่าจาก K8s ให้เป็นหน่วยมาตรฐานเดียวกับ Prometheus
    - CPU: Cores (e.g., 100m -> 0.1)
    - Memory: Bytes (e.g., 512Mi -> 536870912)
    """
    if not value_str: return 0.0
    value_str = str(value_str).strip()
    
    try:
        # --- จัดการ CPU (ต้องการหน่วย Core) ---
        if value_str.endswith('m'): # millicores
            return float(value_str.replace('m', '')) / 1000.0
        
        # --- จัดการ Memory (ต้องการหน่วย Bytes) ---
        if value_str.endswith('Ki'):
            return float(value_str.replace('Ki', '')) * 1024
        if value_str.endswith('Mi'):
            return float(value_str.replace('Mi', '')) * 1024 * 1024
        if value_str.endswith('Gi'):
            return float(value_str.replace('Gi', '')) * 1024 * 1024 * 1024
        if value_str.endswith('Ti'):
            return float(value_str.replace('Ti', '')) * 1024 * 1024 * 1024 * 1024
            
        # กรณีเป็นตัวเลขโดดๆ (มักจะเป็น Bytes อยู่แล้ว หรือ Cores อยู่แล้ว)
        return float(value_str)
    except:
        return 0.0

def run_cmd(cmd):
    """รันคำสั่ง Shell และคืนค่า Output"""
    try:
        # redirect stderr to stdout เพื่อดักจับ Error "No resources found"
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8')
        return result.strip()
    except subprocess.CalledProcessError as e:
        # กรณี Error (เช่น No resources found)
        return e.output.decode('utf-8').strip()

# --- MAIN LOGIC ---
print("🔍 เริ่มตรวจสอบการดึงข้อมูลจาก Kubernetes...")
print("-" * 60)

data = {}

# 1. เช็ค USAGE (kubectl top)
print("\n[1/3] Checking Usage (kubectl top nodes)...")
output_top = run_cmd("kubectl top nodes --no-headers")
print(f"   📋 Output:\n{output_top}")

if "No resources found" in output_top or not output_top:
    print("   ⚠️ WARNING: ดึง Usage ไม่ได้ (Metrics Server อาจมีปัญหา)")
else:
    for line in output_top.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            node_name = parts[0]
            data[f"usage_{node_name}_cpu"] = parse_k8s_value(parts[1])
            data[f"usage_{node_name}_mem"] = parse_k8s_value(parts[3])

# 2. เช็ค CAPACITY & REQUEST (kubectl describe)
print("\n[2/3] Checking Capacity & Requests...")
for key, node_name in NODES.items():
    print(f"   Testing Node: {node_name}...")
    
    # Cap
    cmd_cap = f"kubectl get node {node_name} -o jsonpath='{{.status.capacity.cpu}} {{.status.capacity.memory}}'"
    out_cap = run_cmd(cmd_cap)
    if "Error" not in out_cap:
        parts = out_cap.split()
        data[f"cap_{node_name}_cpu"] = parse_k8s_value(parts[0])
        data[f"cap_{node_name}_mem"] = parse_k8s_value(parts[1])
    
    # Req (ดึงจาก describe)
    cmd_req = f"kubectl describe node {node_name} | grep -A 5 'Allocated resources' | tail -n 2"
    out_req = run_cmd(cmd_req)
    # output ปกติ:
    #   cpu    250m (6%)
    #   memory 500Mi (10%)
    lines = out_req.splitlines()
    if len(lines) >= 2:
        try:
            req_cpu_str = lines[0].strip().split()[1]
            req_mem_str = lines[1].strip().split()[1]
            data[f"req_{node_name}_cpu"] = parse_k8s_value(req_cpu_str)
            data[f"req_{node_name}_mem"] = parse_k8s_value(req_mem_str)
        except:
            print(f"      ❌ Parse Error: {lines}")

# 3. เช็ค PENDING PODS
print("\n[3/3] Checking Pending Pods...")
cmd_pend = "kubectl get pods -A --field-selector=status.phase=Pending --no-headers 2>&1" 
# 2>&1 เพื่อดัก Error message
raw_output = run_cmd(cmd_pend)

if "No resources found" in raw_output:
    print("   ✅ Status: ไม่มี Pod ค้างอยู่เลย (Count = 0)")
    pending_count = 0
else:
    # ถ้ามี output ให้นับบรรทัด
    pending_count = len(raw_output.splitlines())
    print(f"   ⚠️ Status: เจอ Pod Pending จำนวน {pending_count} ตัว")

# --- สรุปผลลัพธ์ (Feature Vector) ---
print("\n" + "="*60)
print("📊 สรุปข้อมูลที่จะส่งเข้า Model (22 Features)")
print("="*60)

# สร้าง list features ตามลำดับ (ต้องเช็คกับ CSV ของคุณว่าลำดับนี้ถูกไหม)
features = []

# helper เพื่อดึงค่า
def get_val(metric_type, node_key, resource):
    full_name = NODES[node_key]
    if metric_type == 'usage': key = f"usage_{full_name}_{resource}"
    elif metric_type == 'req': key = f"req_{full_name}_{resource}"
    elif metric_type == 'cap': key = f"cap_{full_name}_{resource}"
    
    val = data.get(key, 0.0)
    return val

# --- ลำดับการเรียง (แก้ตรงนี้ถ้า CSV เรียงแบบอื่น) ---
# 1. CPU Usage
features.extend([get_val('usage', 'master', 'cpu'), get_val('usage', 'worker1', 'cpu'), get_val('usage', 'worker2', 'cpu')])
# 2. Mem Usage
features.extend([get_val('usage', 'master', 'mem'), get_val('usage', 'worker1', 'mem'), get_val('usage', 'worker2', 'mem')])
# 3. Req Unknown (Dummy)
features.append(0.0)
# 4. CPU Req
features.extend([get_val('req', 'master', 'cpu'), get_val('req', 'worker1', 'cpu'), get_val('req', 'worker2', 'cpu')])
# 5. Mem Req Unknown (Dummy)
features.append(0.0)
# 6. Mem Req
features.extend([get_val('req', 'master', 'mem'), get_val('req', 'worker1', 'mem'), get_val('req', 'worker2', 'mem')])
# 7. CPU Cap
features.extend([get_val('cap', 'master', 'cpu'), get_val('cap', 'worker1', 'cpu'), get_val('cap', 'worker2', 'cpu')])
# 8. Mem Cap
features.extend([get_val('cap', 'master', 'mem'), get_val('cap', 'worker1', 'mem'), get_val('cap', 'worker2', 'mem')])
# 9. Pending
features.append(float(pending_count))

# 10. Target (Calculated Total CPU)
total_cpu = features[0] + features[1] + features[2]
features.append(total_cpu)

# Print ตาราง
print(f"{'INDEX':<6} | {'DESCRIPTION':<30} | {'VALUE'}")
print("-" * 55)
labels = [
    "CPU Usage (Master)", "CPU Usage (Worker1)", "CPU Usage (Worker2)",
    "Mem Usage (Master)", "Mem Usage (Worker1)", "Mem Usage (Worker2)",
    "Req CPU Unknown",
    "Req CPU (Master)", "Req CPU (Worker1)", "Req CPU (Worker2)",
    "Req Mem Unknown",
    "Req Mem (Master)", "Req Mem (Worker1)", "Req Mem (Worker2)",
    "Cap CPU (Master)", "Cap CPU (Worker1)", "Cap CPU (Worker2)",
    "Cap Mem (Master)", "Cap Mem (Worker1)", "Cap Mem (Worker2)",
    "Pending Pods",
    "Total CPU (Target)"
]

for i, (val, label) in enumerate(zip(features, labels)):
    print(f"{i:<6} | {label:<30} | {val:.4f}")

print("-" * 55)
