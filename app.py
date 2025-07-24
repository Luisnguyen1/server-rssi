from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import threading
from bencons import BeaconConnection, BeaconDelegate
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Global dictionary to store current RSSI values for all beacons
current_rssi = {}

# Load beacon configuration
with open('bencons.json', 'r') as f:
    config = json.load(f)

# Load existing fingerprints if file exists
try:
    with open('fingerprints.json', 'r') as f:
        fingerprints = json.load(f)
except FileNotFoundError:
    fingerprints = []

def save_fingerprints():
    """Save fingerprints to JSON file"""
    with open('fingerprints.json', 'w') as f:
        json.dump(fingerprints, f, indent=2)

class WebBeaconDelegate(BeaconDelegate):
    def handleNotification(self, cHandle, data):
        data_str = data.decode('utf-8')
        try:
            # Chỉ lấy giá trị RSSI từ dữ liệu
            rssi = int(data_str)
            
            # Update current RSSI value for this beacon
            current_rssi[self.beacon_mac] = rssi
            
            # Emit update to connected clients
            socketio.emit('rssi_update', {
                'beacon_mac': self.beacon_mac,
                'rssi': rssi
            })
            
        except ValueError as e:
            print(f"Error parsing data: {e}")

@app.route('/')
def index():
    return render_template('index.html', 
                         beacons=config['beacons'],
                         fingerprints=fingerprints)

@app.route('/api/current_rssi')
def get_current_rssi():
    return jsonify(current_rssi)

@app.route('/api/save_fingerprint', methods=['POST'])
def save_fingerprint():
    data = request.json
    x = float(data['x'])
    y = float(data['y'])
    
    if not current_rssi:
        return jsonify({'error': 'No RSSI data available'}), 400
    
    # Create simple fingerprint record with only coordinates and RSSI values
    fingerprint = {
        'x': x,
        'y': y,
        'rssi': current_rssi.copy()
    }
    
    fingerprints.append(fingerprint)
    save_fingerprints()
    
    return jsonify({'status': 'success', 'fingerprint': fingerprint})

def start_beacon_connections():
    """Start connections to all beacons"""
    beacon_connections = []
    
    print(f"Starting connections to {len(config['beacons'])} beacons...")
    
    # Create and start connections for all beacons
    for beacon_info in config['beacons']:
        try:
            beacon_conn = BeaconConnection(beacon_info)
            # Tạo một class mới kế thừa WebBeaconDelegate
            class CustomBeaconDelegate(WebBeaconDelegate):
                def __init__(self, beacon_mac):
                    super().__init__(beacon_mac)
            
            # Override the delegate class
            beacon_conn.delegate_class = CustomBeaconDelegate
            beacon_connections.append(beacon_conn)
            beacon_conn.start_thread()
            time.sleep(1)  # Tăng delay giữa các kết nối
            
        except Exception as e:
            print(f"Error connecting to beacon {beacon_info['mac']}: {e}")
            continue
    
    return beacon_connections

if __name__ == '__main__':
    # Start beacon connections in background
    beacon_connections = start_beacon_connections()
    
    try:
        # Run Flask app with SocketIO
        socketio.run(app, host='0.0.0.0', port=5000, debug=True)
    finally:
        print("Disconnecting beacons...")
        for beacon_conn in beacon_connections:
            beacon_conn.disconnect()
