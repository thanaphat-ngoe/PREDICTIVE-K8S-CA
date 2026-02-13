import subprocess

class NodeManager:

    def __init__(self):
        self.script_path = "." #เดี๋ยวต้องแก้ใส่pathที่จะเข้าถึง join และ kick
    
    def _run_script(self, script_name, arg):
        
        cmd = f"{self.script_path}/{script_name} {arg}"
        print(f"Executing: {cmd}")

        try:
            subprocess.run(cmd, shell=True, check=True)
            print("✅ Success")
            return True
        except subprocess.CalledProcessError:
            print("❌ Something wrong (Script Error)")
            return False
        
    def scale_up(self, node_ip):

        print(f"\n[Manager] order scale out for machine IP: {node_ip}")

        return self._run_script("join-node.sh", node_ip)
    
    def scale_down(self, node_ip):
        
        print(f"\n[Manager] order the scale in for machine IP: {node_ip}")

        name = self.get_node_name(node_ip)

        if name:
            print(f"    (Machine name: {name})")
            return self._run_script("kick-node.sh", name)
        else:
            print("⚠️ Can't find the machine name")
            return False

    def get_node_name(self, ip_address):
        
        cmd = "kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type==\"InternalIP\")].address} {.metadata.name}{\"\\n\"}{end}'"
        
        try:

            output = subprocess.check_output(cmd, shell=True, text=True)

            for line in output.splitlines():
                if ip_address in line:
                    return line.split()[1]

        except:
            return None


