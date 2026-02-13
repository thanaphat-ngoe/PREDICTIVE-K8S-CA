import time

class ScalingMagager:

    def __init__(self, max_nodes=2, cooldown=300, sanity_threshold=2):

        self.max_nodes = max_nodes
        self.cooldown = cooldown
        self.sanity_threshold = sanity_threshold
        
        self.last_scale_time = 0

    def decide(self, pred_cpu, cap, nodes, pending):

        now = time.time()

        limit = cap * self.sanity_threshold

        if pred_cpu > limit:
            return "REJECT"
        
        if (now - self.last_scale_time) < self.cooldown:
            return "WAIT"
        
        safe_zone = 0.8 * cap

        if (pred_cpu < safe_zone) and (pending == 0):
            return "DO_NOTHING"
        
        if nodes >= self.max_nodes:
            return "BLOCKED"
        
        self.last_scale_time = now

        return "SCALE_UP"
        
