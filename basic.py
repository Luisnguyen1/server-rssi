from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import threading
import time
import json
import numpy as np
from filterpy.kalman import KalmanFilter
import math

# === Cấu hình ===
CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"
TX_POWER = -55
ENV_FACTOR = 2.8  # Hệ số môi trường

# === Load beacon từ file JSON ===
with open("bencons.json", "r") as f:
    config = json.load(f)
beacons = config["beacons"]

# === Tọa độ beacon từ "toado": "x,y"
beacon_coords = {}
for b in beacons:
    if "toado" in b:
        try:
            x_str, y_str = b["toado"].split(",")
            beacon_coords[b["mac"]] = (float(x_str), float(y_str))
        except:
            print(f"⚠️ Lỗi tọa độ beacon {b['mac']}, giá trị: {b['toado']}")

# === Kalman filter cho từng beacon MAC ===
kalman_filters = {}
user_data = {}  # { user_id: {mac1: distance1, mac2: distance2, ...} }
user_positions = {}  # { user_id: {"x": x, "y": y, "timestamp": time, "accuracy": accuracy} }
data_lock = threading.Lock()

def create_kalman_filter():
    kf = KalmanFilter(dim_x=2, dim_z=1)
    kf.x = np.array([[0.0], [0.0]])  # [distance, velocity]
    kf.F = np.array([[1., 1.], [0., 1.]])
    kf.H = np.array([[1., 0.]])
    kf.P *= 1000.
    kf.R = 0.1
    kf.Q = np.array([[0.01, 0.01], [0.01, 0.1]])
    return kf

def estimate_distance(rssi):
    if rssi == 0:
        return None
    return 10 ** ((TX_POWER - rssi) / (10 * ENV_FACTOR))

def trilaterate(positions, distances):
    """
    Tính toán vị trí bằng phương pháp trilateration
    positions: [(x1,y1), (x2,y2), (x3,y3), ...] - tọa độ beacon
    distances: [d1, d2, d3, ...] - khoảng cách đến từng beacon
    """
    if len(positions) < 3:
        return None, None
    
    (x1, y1), (x2, y2), (x3, y3) = positions[:3]
    r1, r2, r3 = distances[:3]

    A = 2*(x2 - x1)
    B = 2*(y2 - y1)
    C = r1**2 - r2**2 - x1**2 + x2**2 - y1**2 + y2**2

    D = 2*(x3 - x2)
    E = 2*(y3 - y2)
    F = r2**2 - r3**2 - x2**2 + x3**2 - y2**2 + y3**2

    denominator = A*E - B*D
    if abs(denominator) < 1e-10:  # Tránh chia cho 0
        return None, None

    x = (C*E - F*B) / denominator
    y = (A*F - C*D) / denominator
    
    # Tính độ chính xác dựa trên sai số
    accuracy = calculate_position_accuracy(positions[:3], distances[:3], (x, y))
    
    return (x, y), accuracy

def calculate_position_accuracy(positions, distances, calculated_pos):
    """Tính độ chính xác của vị trí được tính toán"""
    if not calculated_pos:
        return 0
    
    x, y = calculated_pos
    errors = []
    
    for (bx, by), expected_dist in zip(positions, distances):
        actual_dist = np.sqrt((x - bx)**2 + (y - by)**2)
        error = abs(actual_dist - expected_dist)
        errors.append(error)
    
    avg_error = np.mean(errors)
    # Chuyển đổi thành % độ chính xác (100% - error%)
    accuracy = max(0, 100 - (avg_error * 10))  # Giả sử 10m error = 100% không chính xác
    return round(accuracy, 1)

def get_beacon_name_from_mac(mac):
    """Lấy tên beacon từ MAC address"""
    for i, beacon in enumerate(beacons):
        if beacon["mac"] == mac:
            return f"beacon{i+1}"
    return mac

def get_user_position(user_id):
    """Lấy vị trí hiện tại của user"""
    with data_lock:
        return user_positions.get(user_id, None)

def get_all_user_positions():
    """Lấy vị trí của tất cả user"""
    with data_lock:
        return dict(user_positions)

def get_user_data_with_position(user_id):
    """Lấy đầy đủ thông tin user bao gồm khoảng cách và vị trí"""
    with data_lock:
        result = {
            "user_id": user_id,
            "distances": {},
            "position": None
        }
        
        # Thêm khoảng cách đến các beacon
        if user_id in user_data:
            for mac, distance in user_data[user_id].items():
                beacon_name = get_beacon_name_from_mac(mac)
                beacon_coord = beacon_coords.get(mac, "Unknown")
                result["distances"][beacon_name] = {
                    "distance": round(distance, 2),
                    "beacon_position": beacon_coord,
                    "mac": mac
                }
        
        # Thêm vị trí tính toán
        if user_id in user_positions:
            result["position"] = user_positions[user_id]
        
        return result

def export_positions_json():
    """Xuất tất cả vị trí user ra định dạng JSON"""
    all_data = {}
    with data_lock:
        for user_id in user_data.keys():
            all_data[user_id] = get_user_data_with_position(user_id)
    
    return json.dumps(all_data, indent=2)

class BeaconDelegate(DefaultDelegate):
    def __init__(self, mac):
        super().__init__()
        self.mac = mac
        if mac not in kalman_filters:
            kalman_filters[mac] = create_kalman_filter()

    def handleNotification(self, cHandle, data):
        global user_data, user_positions
        try:
            data_str = data.decode("utf-8")
            parts = data_str.strip().split(":")
            if len(parts) == 2:
                user_id, rssi = parts
                rssi = int(rssi)

                raw_distance = estimate_distance(rssi)
                if raw_distance is None:
                    return

                kf = kalman_filters[self.mac]
                kf.predict()
                kf.update(np.array([[raw_distance]]))
                filtered = kf.x[0, 0]

                with data_lock:
                    # Lưu khoảng cách theo user
                    if user_id not in user_data:
                        user_data[user_id] = {}
                    user_data[user_id][self.mac] = filtered

                    # Lấy tên beacon
                    beacon_name = get_beacon_name_from_mac(self.mac)
                    
                    # In thông tin cập nhật
                    print(f"\n📡 [{beacon_name}] User {user_id}: RSSI={rssi} → Distance={filtered:.2f}m")
                    
                    # Hiển thị tất cả khoảng cách hiện tại
                    print(f"� All distances for User {user_id}:")
                    for beacon_mac, dist in user_data[user_id].items():
                        b_name = get_beacon_name_from_mac(beacon_mac)
                        b_coord = beacon_coords.get(beacon_mac, "Unknown")
                        print(f"  🛰️ {b_name} ({b_coord}) ➤ {dist:.2f}m")

                    # Tính vị trí nếu có >= 3 beacon
                    coords = []
                    dists = []
                    beacon_names = []
                    
                    for mac, dist in user_data[user_id].items():
                        if mac in beacon_coords:
                            coords.append(beacon_coords[mac])
                            dists.append(dist)
                            beacon_names.append(get_beacon_name_from_mac(mac))

                    if len(coords) >= 3:
                        position, accuracy = trilaterate(coords, dists)
                        if position:
                            x, y = position
                            timestamp = time.time()
                            
                            # Lưu vị trí user
                            user_positions[user_id] = {
                                "x": round(x, 2),
                                "y": round(y, 2),
                                "timestamp": timestamp,
                                "accuracy": accuracy,
                                "beacons_used": beacon_names[:3]
                            }
                            
                            print(f"🎯 CALCULATED POSITION:")
                            print(f"   👤 User: {user_id}")
                            print(f"   📍 Coordinates: ({x:.2f}, {y:.2f})")
                            print(f"   🎯 Accuracy: {accuracy:.1f}%")
                            print(f"   🛰️ Used beacons: {', '.join(beacon_names[:3])}")
                            print(f"   ⏰ Timestamp: {time.strftime('%H:%M:%S', time.localtime(timestamp))}")
                    else:
                        print(f"⚠️ Need at least 3 beacons for position calculation (current: {len(coords)})")

        except Exception as e:
            print(f"[{self.mac}] Error in notification: {e}")

class BeaconConnection:
    def __init__(self, mac):
        self.mac = mac
        self.peripheral = None
        self.thread = None
        self.running = True

    def connect_and_listen(self):
        while self.running:
            try:
                print(f"[{self.mac}] Connecting...")
                self.peripheral = Peripheral(self.mac)
                self.peripheral.setDelegate(BeaconDelegate(self.mac))

                char = self.peripheral.getCharacteristics(uuid=CHAR_UUID)[0]
                self.peripheral.writeCharacteristic(char.getHandle() + 1, b"\x01\x00", withResponse=True)
                print(f"[{self.mac}] Connected and listening...")

                while self.running:
                    if self.peripheral.waitForNotifications(2.0):
                        continue
            except BTLEException as e:
                print(f"[{self.mac}] BTLE Exception: {e}")
            except Exception as e:
                print(f"[{self.mac}] Error: {e}")
            finally:
                self.disconnect()
                print(f"[{self.mac}] Reconnecting in 5s...")
                time.sleep(5)

    def start(self):
        self.thread = threading.Thread(target=self.connect_and_listen, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.running = False
        try:
            if self.peripheral:
                self.peripheral.disconnect()
        except:
            pass

def print_all_positions():
    """In ra tất cả vị trí user hiện tại"""
    with data_lock:
        if not user_positions:
            print("\n📱 No user positions calculated yet")
            return
        
        print(f"\n{'='*60}")
        print(f"📍 ALL USER POSITIONS ({len(user_positions)} users)")
        print(f"{'='*60}")
        
        for user_id, pos_info in user_positions.items():
            age = time.time() - pos_info["timestamp"]
            print(f"👤 User: {user_id}")
            print(f"   📍 Position: ({pos_info['x']}, {pos_info['y']})")
            print(f"   🎯 Accuracy: {pos_info['accuracy']}%")
            print(f"   🛰️ Beacons: {', '.join(pos_info['beacons_used'])}")
            print(f"   ⏰ Age: {age:.1f}s ago")
            print()

def print_beacon_info():
    """In thông tin về các beacon"""
    print("🛰️ BEACON CONFIGURATION:")
    for i, beacon in enumerate(beacons):
        beacon_name = f"beacon{i+1}"
        coord = beacon_coords.get(beacon["mac"], "Unknown")
        print(f"   {beacon_name}: {beacon['mac']} at {coord}")

def main():
    connections = []
    print("🚀 Starting TRILATERATION Server...\n")
    
    print_beacon_info()
    print(f"\n📊 System will calculate user positions using:")
    print(f"   • TX_POWER: {TX_POWER} dBm")
    print(f"   • ENV_FACTOR: {ENV_FACTOR}")
    print(f"   • Kalman filtering for distance smoothing")
    print(f"   • Trilateration with 3+ beacons\n")
    
    for beacon in beacons:
        conn = BeaconConnection(beacon["mac"])
        conn.start()
        connections.append(conn)
        time.sleep(0.5)

    try:
        print("💡 Commands:")
        print("  - Ctrl+C: Exit and show final positions")
        print("  - Every 30 seconds: Show all user positions summary\n")
        
        last_summary = time.time()
        while True:
            time.sleep(1)
            
            # Hiển thị summary mỗi 30 giây
            if time.time() - last_summary >= 30:
                print_all_positions()
                last_summary = time.time()
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        print_all_positions()  # Hiển thị vị trí cuối cùng
        for conn in connections:
            conn.disconnect()
        print("✅ All connections closed")

if __name__ == "__main__":
    main()
