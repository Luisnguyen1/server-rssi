from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import threading
from bencons import BeaconConnection, BeaconDelegate
import time
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Global variables
current_rssi = {}  # Store current RSSI values for beacons
data_lock = threading.Lock()

# Load beacon configuration
with open('bencons.json', 'r') as f:
    config = json.load(f)

# Load existing fingerprints if file exists
try:
    with open('fingerprints.json', 'r') as f:
        fingerprints = json.load(f)
except FileNotFoundError:
    fingerprints = []

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

def get_beacon_name(mac):
    """Get beacon name/number from MAC address"""
    for i, beacon in enumerate(config['beacons']):
        if beacon['mac'] == mac:
            return f'beacon{i+1}'
    return mac

class WebBeaconDelegate(BeaconDelegate):
    def handleNotification(self, cHandle, data):
        try:
            data_str = data.decode('utf-8')
            # Parse RSSI value from data
            try:
                rssi = int(data_str.strip().split(':')[1])
            except:
                rssi = int(data_str)

            with data_lock:
                # Update current RSSI value for this beacon
                current_rssi[self.beacon_mac] = {
                    'rssi': rssi,
                    'timestamp': time.time()
                }
                
                # Get beacon info for the UI
                beacon_info = next((b for b in config['beacons'] if b['mac'] == self.beacon_mac), None)
                beacon_location = beacon_info.get('toado', 'unknown') if beacon_info else 'unknown'

                # Emit update to connected clients
                socketio.emit('rssi_update', {
                    'beacon_mac': self.beacon_mac,
                    'rssi': rssi,
                    'location': beacon_location,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })

        except Exception as e:
            print(f"Error in notification handler: {e}")

@app.route('/')
def index():
    return render_template('index.html', 
                         beacons=config['beacons'],
                         fingerprints=fingerprints)

@app.route('/api/current_rssi')
def get_current_rssi():
    """Get current RSSI values for all beacons"""
    with data_lock:
        formatted_rssi = {}
        for mac, data in current_rssi.items():
            beacon_name = get_beacon_name(mac)
            formatted_rssi[beacon_name] = {
                'mac': mac,
                'rssi': data['rssi'],
                'timestamp': data['timestamp']
            }
        return jsonify(formatted_rssi)

@app.route('/api/save_fingerprint', methods=['POST'])
def save_fingerprint():
    """Save a new fingerprint with location and current RSSI values"""
    data = request.json
    x = float(data['x'])
    y = float(data['y'])
    
    with data_lock:
        if not current_rssi:
            return jsonify({'error': 'No RSSI data available'}), 400
        
        # Create fingerprint with timestamp, location and RSSI values
        fingerprint = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'location': {'x': x, 'y': y},
            'readings': {}
        }
        
        # Add RSSI readings for each beacon
        for mac, data in current_rssi.items():
            beacon_name = get_beacon_name(mac)
            fingerprint['readings'][beacon_name] = {
                'mac': mac,
                'rssi': data['rssi']
            }
        
        fingerprints.append(fingerprint)
        save_fingerprints()
        
        return jsonify({
            'status': 'success',
            'fingerprint': fingerprint
        })

def start_beacon_connections():
    """Start connections to all beacons"""
    beacon_connections = []
    
    print(f"Starting connections to {len(config['beacons'])} beacons...")
    
    # Create and start connections for all beacons
    for beacon_info in config['beacons']:
        beacon_conn = BeaconConnection(beacon_info)
        # Override the delegate class
        beacon_conn.delegate_class = WebBeaconDelegate
        beacon_connections.append(beacon_conn)
        beacon_conn.start_thread()
        time.sleep(0.5)  # Small delay between connections
    
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
