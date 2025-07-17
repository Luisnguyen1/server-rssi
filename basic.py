from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import threading
import time
import json

# === Config ===
CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"
TX_POWER = -59           # RSSI tại khoảng cách 1m (điều chỉnh tùy loại beacon)
ENV_FACTOR = 2.0         # Hệ số suy giảm môi trường

# === Load danh sách beacon từ file JSON ===
with open("bencons.json", "r") as f:
    config = json.load(f)
beacons = config["beacons"]

# === Bảng lưu dữ liệu user theo format yêu cầu ===
users_data = {}
user_lock = threading.Lock()

# Tạo mapping từ MAC sang tên beacon
beacon_names = {}
for i, beacon in enumerate(beacons):
    beacon_names[beacon["mac"]] = f"beacon{i+1}"

def estimate_distance(rssi):
    if rssi == 0:
        return None
    return 10 ** ((TX_POWER - rssi) / (10 * ENV_FACTOR))

def print_all_users():
    """In ra tất cả dữ liệu user hiện tại"""
    with user_lock:
        if not users_data:
            print("\n📱 No users detected yet")
            return
        
        print(f"\n📱 All Users Data ({len(users_data)} users):")
        print("=" * 50)
        for user_id, user_info in users_data.items():
            print(f"👤 User {user_id}: {user_info}")
        print("=" * 50)

def get_user_data(user_id):
    """Lấy dữ liệu của một user cụ thể"""
    with user_lock:
        return users_data.get(user_id, None)

def update_specific_beacon(user_id, beacon_name, rssi_value):
    """Cập nhật RSSI cho một beacon cụ thể của user (để test)"""
    with user_lock:
        if user_id not in users_data:
            users_data[user_id] = {"id": user_id}
            # Khởi tạo tất cả beacon với giá trị null
            for beacon_mac in beacon_names:
                users_data[user_id][beacon_names[beacon_mac]] = None
        
        old_value = users_data[user_id].get(beacon_name)
        users_data[user_id][beacon_name] = rssi_value
        
        print(f"🔧 Manual update - [{beacon_name}] User {user_id}: {old_value} → {rssi_value}")
        print(f"📱 Updated user data: {users_data[user_id]}")
        return True

def reset_user_data(user_id=None):
    """Reset dữ liệu user (tất cả hoặc một user cụ thể)"""
    with user_lock:
        if user_id:
            if user_id in users_data:
                # Reset về giá trị null cho tất cả beacon
                for beacon_mac in beacon_names:
                    users_data[user_id][beacon_names[beacon_mac]] = None
                print(f"✅ Reset data for user {user_id}")
            else:
                print(f"❌ User {user_id} not found")
        else:
            users_data.clear()
            print("✅ Reset all users data")

class BeaconDelegate(DefaultDelegate):
    def __init__(self, mac):
        super().__init__()
        self.mac = mac

    def handleNotification(self, cHandle, data):
        try:
            data_str = data.decode("utf-8")
            parts = data_str.strip().split(":")
            if len(parts) == 2:
                user_id, rssi = parts
                rssi = int(rssi)

                # Lấy tên beacon từ MAC
                beacon_name = beacon_names.get(self.mac, self.mac)

                # Cập nhật dữ liệu user một cách thread-safe
                with user_lock:
                    # Khởi tạo user nếu chưa có
                    if user_id not in users_data:
                        users_data[user_id] = {"id": user_id}
                        # Khởi tạo tất cả beacon với giá trị null
                        for beacon_mac in beacon_names:
                            users_data[user_id][beacon_names[beacon_mac]] = None
                    
                    # Lưu giá trị cũ để so sánh
                    old_value = users_data[user_id].get(beacon_name)
                    
                    # CHỈ cập nhật RSSI cho beacon hiện tại, không động đến beacon khác
                    users_data[user_id][beacon_name] = rssi
                    
                    # Chỉ in thông báo nếu giá trị thay đổi
                    if old_value != rssi:
                        print(f"\n� [{beacon_name}] User {user_id}: {old_value} → {rssi}")
                        print(f"� Current user data: {users_data[user_id]}")
                        
                        # Đếm số beacon đã có data
                        active_beacons = [key for key, value in users_data[user_id].items() 
                                        if key != "id" and value is not None]
                        print(f"📊 Active beacons: {len(active_beacons)}/{len(beacons)} {active_beacons}")

        except Exception as e:
            print(f"[{self.mac}] Notification error: {e}")

class BeaconConnection:
    def __init__(self, mac):
        self.mac = mac
        self.beacon_name = beacon_names.get(mac, mac)
        self.peripheral = None
        self.thread = None
        self.running = True
        self.connected = False
        self.connection_attempts = 0
        self.max_attempts = 5

    def connect_and_listen(self):
        while self.running and self.connection_attempts < self.max_attempts:
            try:
                self.connection_attempts += 1
                print(f"[{self.beacon_name}] Connecting... (Attempt {self.connection_attempts}/{self.max_attempts})")
                
                self.peripheral = Peripheral(self.mac)
                self.peripheral.setDelegate(BeaconDelegate(self.mac))

                char = self.peripheral.getCharacteristics(uuid=CHAR_UUID)[0]
                self.peripheral.writeCharacteristic(char.getHandle() + 1, b"\x01\x00", withResponse=True)
                
                self.connected = True
                print(f"[{self.beacon_name}] ✅ Connected successfully!")

                while self.running:
                    if self.peripheral.waitForNotifications(2.0):
                        continue
                        
            except BTLEException as e:
                print(f"[{self.beacon_name}] ❌ Bluetooth error: {e}")
                self.connected = False
            except Exception as e:
                print(f"[{self.beacon_name}] ❌ Error: {e}")
                self.connected = False
            finally:
                if not self.running:
                    break
                    
                if not self.connected and self.connection_attempts < self.max_attempts:
                    print(f"[{self.beacon_name}] 🔄 Retrying in 3s...")
                    time.sleep(3)
                elif not self.connected:
                    print(f"[{self.beacon_name}] ❌ Failed to connect after {self.max_attempts} attempts")
                    break
                    
        if not self.connected:
            print(f"[{self.beacon_name}] 🚨 Connection failed permanently")

    def start(self):
        self.thread = threading.Thread(target=self.connect_and_listen, daemon=True)
        self.thread.start()
        print(f"[{self.beacon_name}] 🚀 Started connection thread")

    def is_connected(self):
        return self.connected

    def wait_for_connection(self, timeout=30):
        """Đợi beacon kết nối trong thời gian timeout (giây)"""
        start_time = time.time()
        while not self.connected and (time.time() - start_time) < timeout:
            time.sleep(0.5)
        return self.connected

    def disconnect(self):
        self.running = False
        self.connected = False
        try:
            if self.peripheral:
                self.peripheral.disconnect()
                print(f"[{self.beacon_name}] 🔌 Disconnected")
        except:
            pass

def wait_for_all_beacons(connections, timeout=60):
    """Đợi tất cả beacon kết nối thành công"""
    print(f"\n⏳ Waiting for ALL beacons to connect (timeout: {timeout}s)...")
    start_time = time.time()
    
    while (time.time() - start_time) < timeout:
        connected_beacons = []
        pending_beacons = []
        
        for conn in connections:
            if conn.is_connected():
                connected_beacons.append(conn.beacon_name)
            else:
                pending_beacons.append(conn.beacon_name)
        
        # In trạng thái hiện tại
        print(f"\r✅ Connected: {len(connected_beacons)}/{len(connections)} - " +
              f"Ready: {connected_beacons} | Pending: {pending_beacons}", end="", flush=True)
        
        # Nếu tất cả đã kết nối
        if len(connected_beacons) == len(connections):
            print(f"\n🎉 ALL BEACONS CONNECTED SUCCESSFULLY!")
            return True
            
        time.sleep(1)
    
    # Timeout
    print(f"\n❌ TIMEOUT! Not all beacons connected within {timeout}s")
    connected_count = sum(1 for conn in connections if conn.is_connected())
    print(f"� Final status: {connected_count}/{len(connections)} beacons connected")
    return False

def main():
    connections = []
    print("�📡 Starting CONTROLLED connection to all beacons...\n")
    
    # In ra thông tin beacon mapping
    print("🏷️  Beacon Mapping (Must ALL Connect):")
    for beacon in beacons:
        beacon_name = beacon_names[beacon["mac"]]
        print(f"  • {beacon_name}: {beacon['mac']} (Position: {beacon['toado']})")
    print()
    
    print("🔧 Connection Requirements:")
    print("  🚨 ALL beacons MUST connect before monitoring starts")
    print("  ✅ Each beacon updates data INDEPENDENTLY")
    print("  ✅ Thread-safe concurrent processing")
    print("  ✅ Automatic reconnection on failure\n")
    
    # Bắt đầu kết nối tất cả beacon
    print("🚀 Initiating connections...")
    for beacon in beacons:
        conn = BeaconConnection(beacon["mac"])
        conn.start()
        connections.append(conn)
        time.sleep(1)  # Delay giữa các kết nối
    
    # Đợi tất cả beacon kết nối
    if not wait_for_all_beacons(connections, timeout=60):
        print("\n🚨 CRITICAL: Not all beacons connected!")
        print("❌ System cannot start without ALL beacons online")
        
        # Hiển thị beacon nào chưa kết nối
        failed_beacons = [conn.beacon_name for conn in connections if not conn.is_connected()]
        print(f"🔴 Failed beacons: {failed_beacons}")
        
        # Đóng tất cả kết nối
        for conn in connections:
            conn.disconnect()
        return False

    try:
        print("\n🎯 ALL BEACONS ONLINE - Starting monitoring...")
        print("💡 Monitoring Commands:")
        print("  - Ctrl+C: Exit and show final data")
        print("  - Real-time updates when beacon data changes")
        print("  - Every 30 seconds: Show complete users summary\n")
        
        last_summary_time = time.time()
        while True:
            time.sleep(1)
            
            # Kiểm tra trạng thái kết nối
            disconnected_beacons = [conn.beacon_name for conn in connections if not conn.is_connected()]
            if disconnected_beacons:
                print(f"\n⚠️  WARNING: Lost connection to: {disconnected_beacons}")
            
            # Hiển thị summary mỗi 30 giây
            current_time = time.time()
            if current_time - last_summary_time >= 30:
                print_all_users()
                last_summary_time = current_time
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping all beacon connections...")
        print_all_users()  # In ra dữ liệu cuối cùng trước khi thoát
        for conn in connections:
            conn.disconnect()
        print("✅ All connections closed safely")
        return True

if __name__ == "__main__":
    main()
