from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import threading
from bencons import BeaconConnection, BeaconDelegate
import time
import numpy as np
from filterpy.kalman import KalmanFilter

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Constants for RSSI to distance conversion
TX_POWER = -55
ENV_FACTOR = 2.8

# Global dictionaries
current_rssi = {}  # Store current RSSI values
kalman_filters = {}  # Store Kalman filters for each beacon
user_data = {}  # Store user distances to beacons
user_positions = {}  # Store calculated user positions
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

def save_fingerprints():
    """Save fingerprints to JSON file"""
    with open('fingerprints.json', 'w') as f:
        json.dump(fingerprints, f, indent=2)

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
    if abs(denominator) < 1e-10:
        return None, None

    x = (C*E - F*B) / denominator
    y = (A*F - C*D) / denominator
    
    accuracy = calculate_position_accuracy(positions[:3], distances[:3], (x, y))
    
    return (x, y), accuracy

def calculate_position_accuracy(positions, distances, calculated_pos):
    if not calculated_pos:
        return 0
    
    x, y = calculated_pos
    errors = []
    
    for (bx, by), expected_dist in zip(positions, distances):
        actual_dist = np.sqrt((x - bx)**2 + (y - by)**2)
        error = abs(actual_dist - expected_dist)
        errors.append(error)
    
    avg_error = np.mean(errors)
    accuracy = max(0, 100 - (avg_error * 10))
    return round(accuracy, 1)

class WebBeaconDelegate(BeaconDelegate):
    def handleNotification(self, cHandle, data):
        try:
            data_str = data.decode('utf-8')
            parts = data_str.strip().split(':')
            if len(parts) == 2:
                user_id, rssi = parts
                rssi = int(rssi)

                # Create Kalman filter if not exists
                if self.beacon_mac not in kalman_filters:
                    kalman_filters[self.beacon_mac] = create_kalman_filter()

                # Calculate distance using Kalman filter
                raw_distance = estimate_distance(rssi)
                if raw_distance is None:
                    return

                kf = kalman_filters[self.beacon_mac]
                kf.predict()
                kf.update(np.array([[raw_distance]]))
                filtered_distance = kf.x[0, 0]

                with data_lock:
                    # Update current RSSI and distance
                    if user_id not in user_data:
                        user_data[user_id] = {}
                    user_data[user_id][self.beacon_mac] = filtered_distance
                    current_rssi[self.beacon_mac] = rssi

                    # Calculate position if we have enough beacons
                    coords = []
                    dists = []
                    for mac, dist in user_data[user_id].items():
                        beacon_info = next((b for b in config['beacons'] if b['mac'] == mac), None)
                        if beacon_info and 'toado' in beacon_info:
                            try:
                                x, y = map(float, beacon_info['toado'].split(','))
                                coords.append((x, y))
                                dists.append(dist)
                            except:
                                print(f"Invalid coordinates for beacon {mac}")

                    if len(coords) >= 3:
                        position, accuracy = trilaterate(coords, dists)
                        if position:
                            x, y = position
                            timestamp = time.time()
                            user_positions[user_id] = {
                                'x': round(x, 2),
                                'y': round(y, 2),
                                'timestamp': timestamp,
                                'accuracy': accuracy
                            }

                # Emit updates to connected clients
                socketio.emit('position_update', {
                    'user_id': user_id,
                    'position': user_positions.get(user_id),
                    'rssi': {
                        'beacon_mac': self.beacon_mac,
                        'rssi': rssi,
                        'distance': filtered_distance
                    }
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
    return jsonify(current_rssi)

@app.route('/api/positions')
def get_positions():
    """Get all user positions"""
    with data_lock:
        return jsonify(user_positions)

@app.route('/api/user_data/<user_id>')
def get_user_data(user_id):
    """Get detailed data for a specific user"""
    with data_lock:
        if user_id not in user_data:
            return jsonify({'error': 'User not found'}), 404
            
        return jsonify({
            'user_id': user_id,
            'position': user_positions.get(user_id),
            'distances': user_data[user_id],
            'rssi_values': {mac: current_rssi.get(mac) 
                          for mac in user_data[user_id].keys()}
        })

@app.route('/api/save_fingerprint', methods=['POST'])
def save_fingerprint():
    data = request.json
    x = float(data['x'])
    y = float(data['y'])
    
    if not current_rssi:
        return jsonify({'error': 'No RSSI data available'}), 400
    
    # Create fingerprint record with coordinates, RSSI values and calculated distances
    fingerprint = {
        'x': x,
        'y': y,
        'rssi': current_rssi.copy(),
        'distances': {mac: estimate_distance(rssi) 
                     for mac, rssi in current_rssi.items()}
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
