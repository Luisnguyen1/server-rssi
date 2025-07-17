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

    def connect_and_listen(self):
        while self.running:
            try:
                print(f"[{self.beacon_name}] Connecting to {self.mac}...")
                self.peripheral = Peripheral(self.mac)
                self.peripheral.setDelegate(BeaconDelegate(self.mac))

                char = self.peripheral.getCharacteristics(uuid=CHAR_UUID)[0]
                self.peripheral.writeCharacteristic(char.getHandle() + 1, b"\x01\x00", withResponse=True)
                print(f"[{self.beacon_name}] ✅ Connected and listening independently...")

                while self.running:
                    if self.peripheral.waitForNotifications(2.0):
                        continue
            except BTLEException as e:
                print(f"[{self.beacon_name}] ❌ Bluetooth error: {e}")
            except Exception as e:
                print(f"[{self.beacon_name}] ❌ Error: {e}")
            finally:
                self.disconnect()
                if self.running:
                    print(f"[{self.beacon_name}] 🔄 Reconnecting in 5s...")
                    time.sleep(5)

    def start(self):
        self.thread = threading.Thread(target=self.connect_and_listen, daemon=True)
        self.thread.start()
        print(f"[{self.beacon_name}] 🚀 Started independent thread")

    def disconnect(self):
        self.running = False
        try:
            if self.peripheral:
                self.peripheral.disconnect()
                print(f"[{self.beacon_name}] 🔌 Disconnected")
        except:
            pass

def main():
    connections = []
    print("📡 Starting INDEPENDENT connection to all beacons...\n")
    
    # In ra thông tin beacon mapping
    print("🏷️  Beacon Mapping (Independent Processing):")
    for beacon in beacons:
        beacon_name = beacon_names[beacon["mac"]]
        print(f"  • {beacon_name}: {beacon['mac']} (Position: {beacon['toado']})")
    print()
    
    print("🔧 Key Features:")
    print("  ✅ Each beacon updates data INDEPENDENTLY")
    print("  ✅ Beacon1 update does NOT affect Beacon2/Beacon3 data")
    print("  ✅ Thread-safe concurrent processing")
    print("  ✅ Only changed values trigger notifications\n")
    
    for beacon in beacons:
        conn = BeaconConnection(beacon["mac"])
        conn.start()
        connections.append(conn)
        time.sleep(0.5)  # avoid overloading bluetooth

    try:
        print("💡 Monitoring Commands:")
        print("  - Ctrl+C: Exit and show final data")
        print("  - Real-time updates when beacon data changes")
        print("  - Every 30 seconds: Show complete users summary\n")
        
        last_summary_time = time.time()
        while True:
            time.sleep(1)
            
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

if __name__ == "__main__":
    main()
