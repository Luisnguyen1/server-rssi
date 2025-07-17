from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import threading
import time
import json
import numpy as np
from filterpy.kalman import KalmanFilter

# === Cấu hình ===
CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"
TX_POWER = -52
ENV_FACTOR = 2.7  # Hệ số môi trường

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
    if len(positions) < 3:
        return None
    (x1, y1), (x2, y2), (x3, y3) = positions[:3]
    r1, r2, r3 = distances[:3]

    A = 2*(x2 - x1)
    B = 2*(y2 - y1)
    C = r1**2 - r2**2 - x1**2 + x2**2 - y1**2 + y2**2

    D = 2*(x3 - x2)
    E = 2*(y3 - y2)
    F = r2**2 - r3**2 - x2**2 + x3**2 - y2**2 + y3**2

    denominator = A*E - B*D
    if denominator == 0:
        return None

    x = (C*E - F*B) / denominator
    y = (A*F - C*D) / denominator
    return (x, y)

class BeaconDelegate(DefaultDelegate):
    def __init__(self, mac):
        super().__init__()
        self.mac = mac
        if mac not in kalman_filters:
            kalman_filters[mac] = create_kalman_filter()

    def handleNotification(self, cHandle, data):
        global user_data
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

                # Lưu theo user
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id][self.mac] = filtered

                # In tất cả khoảng cách cho user
                print(f"\n📍 USER: {user_id}")
                for beacon_mac, dist in user_data[user_id].items():
                    print(f"  🛰️ Beacon {beacon_mac} ➤ {dist:.2f}m")

                # Tính vị trí nếu có >= 3 beacon
                coords = []
                dists = []
                for mac, dist in user_data[user_id].items():
                    if mac in beacon_coords:
                        coords.append(beacon_coords[mac])
                        dists.append(dist)

                if len(coords) >= 3:
                    pos = trilaterate(coords, dists)
                    if pos:
                        x, y = pos
                        print(f"📌 Vị trí ước tính: x = {x:.2f} m, y = {y:.2f} m")

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

def main():
    connections = []
    print("🚀 Starting connection to all beacons...\n")
    for beacon in beacons:
        conn = BeaconConnection(beacon["mac"])
        conn.start()
        connections.append(conn)
        time.sleep(0.5)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        for conn in connections:
            conn.disconnect()

if __name__ == "__main__":
    main()
