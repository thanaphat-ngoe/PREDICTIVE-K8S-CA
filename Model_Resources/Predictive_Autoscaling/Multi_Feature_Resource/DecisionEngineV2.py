import time

class DecisionEngine:
    def __init__(self, cores_per_node=4.0, max_workers=2, min_workers=1):
        # Configuration
        self.cores_per_node = cores_per_node
        self.max_workers = max_workers
        self.min_workers = min_workers

        # Cooldown Timers (Seconds)
        self.cooldown_out = 300  # 5 Mins
        self.cooldown_in = 300   # 5 Mins

        # State tracking
        self.last_scale_out_time = 0
        self.last_scale_in_time = 0

        # Thresholds
        self.scale_out_percent = 0.80  # Scale Out when predicting > 80% of current capacity
        self.scale_in_percent = 0.75   # Scale In when predicting < 75% of capacity (after removing 1 node) 
        self.safe_cpu_percent = 80.0   # Block scale-in if current cluster CPU > 80%

    #  จุดที่ 1: เติม current_cpu_req เข้ามาในวงเล็บ
    def decide(self, predicted_cores, current_workers, pending_pods, current_cpu_usage, current_cpu_req):
        current_time = time.time()
        current_total_cores = current_workers * self.cores_per_node
        
        intent = "DO_NOTHING"
        reason = "System is stable"

        # 1. LOGIC PHASE (ตัดสินใจว่าจะทำอะไร)

        # Guardrail 1: Sanity Check
        if predicted_cores < 0 or predicted_cores > (self.max_workers * self.cores_per_node * 2):
            return "DO_NOTHING", f"Sanity Check Failed: Abnormal prediction ({predicted_cores:.2f} cores)"

        # Guardrail 2: Reactive Emergency
        if pending_pods > 0:
            intent = "SCALE_OUT"
            reason = f"[Emergency] Detected {pending_pods} Pending Pods"
        else:
            # Predictive Logic
            scale_out_threshold = current_total_cores * self.scale_out_percent
            cores_after_scale_in = (current_workers - 1) * self.cores_per_node
            scale_in_threshold = cores_after_scale_in * self.scale_in_percent

            # ขาขึ้น: เชื่อ AI อย่างเดียว รีบเปิดเครื่องดักไว้เลย
            if predicted_cores > scale_out_threshold:
                intent = "SCALE_OUT"
                reason = f"[AI] Need {predicted_cores:.2f} Cores (> {scale_out_threshold:.2f} limit)"
            
            # จุดที่ 2: ขาลง (เพิ่ม Asymmetric Logic เช็คโลกความเป็นจริง)
            elif predicted_cores < scale_in_threshold:
                
                # ถ้าโลกความจริงปัจจุบัน คิวยังแน่นอยู่ (มากกว่า Threshold ที่จะลดเครื่อง)
                if current_cpu_req >= scale_in_threshold:
                    intent = "DO_NOTHING"
                    reason = f"[Wait] AI Predicts {predicted_cores:.2f}, but Current Req is still high ({current_cpu_req:.2f} >= {scale_in_threshold:.2f})"
                
                # ถ้าปลอดภัยทั้ง AI (อนาคต) และ โลกจริง (ปัจจุบัน)
                else:
                    intent = "SCALE_IN"
                    reason = f"[Safe Scale-In] Predict ({predicted_cores:.2f}) & Current ({current_cpu_req:.2f}) are safe for {current_workers-1} nodes"

        # 2. EXECUTION PHASE (ตรวจสอบว่าทำได้จริงไหม)
        
        if intent == "SCALE_OUT":
            if current_workers >= self.max_workers:
                return "DO_NOTHING", f"Blocked: Max Workers ({self.max_workers}) Reached"
            if (current_time - self.last_scale_out_time) < self.cooldown_out:
                return "DO_NOTHING", f"Wait: Scale-Out Cooldown Active"
            
            self.last_scale_out_time = current_time
            return "SCALE_OUT", reason

        elif intent == "SCALE_IN":
            if current_workers <= self.min_workers:
                return "DO_NOTHING", f"Blocked: Min Workers ({self.min_workers}) Reached"
            if current_cpu_usage > self.safe_cpu_percent:
                return "DO_NOTHING", f"Guardrail: Current CPU too high ({current_cpu_usage:.1f}%)"
            if (current_time - self.last_scale_in_time) < self.cooldown_in:
                return "DO_NOTHING", f"Wait: Scale-In Cooldown Active"
            if (current_time - self.last_scale_out_time) < self.cooldown_in:
                return "DO_NOTHING", f"Anti-Flapping: Too soon after scaling out"

            self.last_scale_in_time = current_time
            return "SCALE_IN", reason

        return intent, reason