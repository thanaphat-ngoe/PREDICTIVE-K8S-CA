import requests
import pandas as pd
from datetime import datetime
import time
import pytz

# URL ของ Prometheus (เช่น แบบ Port-forward หรือ NodePort)
PROMETHEUS_URL = "http://10.35.29.108:31102" 

# ตั้งเวลา
bkk_tz = pytz.timezone('Asia/Bangkok')
# สร้างเวลา 28 ก.พ. 2026 ตอน 13:00:00
start_dt_naive = datetime(2026, 2, 28, 14, 0, 0)
start_time = bkk_tz.localize(start_dt_naive).timestamp()
# เวลาสิ้นสุดเอาเป็น "วินาทีปัจจุบัน" ได้เลย (timestamp เป็นค่ากลางทั่วโลกอยู่แล้ว)
end_time = time.time()
step = "60s" # ความถี่ 1 นาที

queries = {
    "cluster_cpu_req": 'sum(kube_pod_container_resource_requests{node=~"aj-aung-k8s-worker1|aj-aung-k8s-worker2", resource="cpu"})',
    "cluster_cpu_cap": 'sum(kube_node_status_capacity{node=~"aj-aung-k8s-worker1|aj-aung-k8s-worker2", resource="cpu"})',
    "cluster_mem_req": 'sum(kube_pod_container_resource_requests{node=~"aj-aung-k8s-worker1|aj-aung-k8s-worker2", resource="memory"}) / (1024*1024*1024)',
    "cluster_mem_cap": 'sum(kube_node_status_capacity{node=~"aj-aung-k8s-worker1|aj-aung-k8s-worker2", resource="memory"}) / (1024*1024*1024)',
    "cluster_pods_pending": 'sum(kube_pod_status_phase{namespace="default", phase="Pending"}) or vector(0)'
}

df_final = pd.DataFrame()

print("⏳ กำลังดูดข้อมูลจาก Prometheus...")
for name, query in queries.items():
    response = requests.get(f"{PROMETHEUS_URL}/api/v1/query_range", params={
        'query': query,
        'start': start_time,
        'end': end_time,
        'step': step
    })
    
    results = response.json()['data']['result']
    if results:
        values = results[0]['values']
        # สร้าง DataFrame ชั่วคราว
        df_temp = pd.DataFrame(values, columns=['Timestamp', name])
        df_temp['Timestamp'] = pd.to_datetime(df_temp['Timestamp'], unit='s')
        df_temp[name] = df_temp[name].astype(float)
        
        # Merge เข้าตารางหลัก
        if df_final.empty:
            df_final = df_temp
        else:
            df_final = pd.merge(df_final, df_temp, on='Timestamp', how='outer')

df_final.fillna(0, inplace=True)
df_final.to_csv("training_data_prometheus.csv", index=False)
print("✅ ดูดข้อมูลเสร็จสิ้น! ได้ไฟล์ training_data_prometheus.csv แล้ว")