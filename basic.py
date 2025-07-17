from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import threading
import time
import json
import numpy as np
from filterpy.kalman import KalmanFilter
from collections import defaultdict

# === Config ===
CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"
TX_POWER = -59           # RSSI tại khoảng cách 1m (điều chỉnh tùy loại beacon)
ENV_FACTOR = 2.0         # Hệ số suy giảm môi trường

# === Load danh sách beacon từ file JSON ===
with open("bencons.json", "r") as f:
    config = json.load(f)
beacons = config["beacons"]

# === Kalman filter cho mỗi beacon MAC ===
kalman_filters = {}

# === Bảng lưu khoảng cách theo user & beacon ===
user_distances = defaultdict(dict)
user_lock = threading.Lock()

def create_kalman_filter():
    kf = KalmanFilter(dim_x=2, dim_z=1)
    kf.x = np.array([[0.0], [0.0]])
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

class BeaconDelegate(DefaultDelegate):
    def __init__(self, mac):
        super().__init__()
        self.mac = mac
        if mac not in kalman_filters:
            kalman_filters[mac] = create_kalman_filter()

    def handleNotification(self, cHandle, data):
        try:
            data_str = data.decode("utf-8")
            parts = data_str.strip().split(":")
            if len(parts) == 2:
                user_id, rssi = parts
                rssi = int(rssi)

                raw_distance = estimate_distance(rssi)
                if raw_distance is None:
                    return

                # Kalman filtering
                kf = kalman_filters[self.mac]
                kf.predict()
                kf.update(np.array([[raw_distance]]))
                filtered = round(kf.x[0, 0], 2)

                # Cập nhật bảng user → beacon → khoảng cách
                with user_lock:
                    user_distances[user_id][self.mac] = filtered

                    # In ra nếu đã có 3 beacon
                    if len(user_distances[user_id]) == 3:
                        print(f"\n👤 User: {user_id}\n📍 Distances:")
                        for beacon_mac, dist in user_distances[user_id].items():
                            print(f"  • {beacon_mac} → {dist} m")

                        # Nếu muốn reset sau mỗi lần in:
                        # user_distances[user_id].clear()

        except Exception as e:
            print(f"[{self.mac}] Notification error: {e}")

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
                print(f"[{self.mac}] Bluetooth error: {e}")
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
    print("📡 Starting connection to all beacons...\n")
    for beacon in beacons:
        conn = BeaconConnection(beacon["mac"])
        conn.start()
        connections.append(conn)
        time.sleep(0.5)  # avoid overloading bluetooth

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
        for conn in connections:
            conn.disconnect()

if __name__ == "__main__":
    main()
