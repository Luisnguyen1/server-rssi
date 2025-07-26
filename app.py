from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Constants from basic.py
CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"

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

class WebBeaconDelegate(DefaultDelegate):
    def __init__(self, mac):
        super().__init__()
        self.mac = mac

    def handleNotification(self, cHandle, data):
        try:
            data_str = data.decode('utf-8')
            print(f"[{self.mac}] Raw received: {data_str}")
            
            # Parse data - format could be "user_id:rssi" or just "rssi"
            if ':' in data_str:
                # Format: user_id:rssi - take only rssi part for fingerprinting
                parts = data_str.strip().split(':')
                if len(parts) >= 2:
                    rssi = int(parts[1])
                else:
                    print(f"[{self.mac}] Invalid format with colon: {data_str}")
                    return
            else:
                # Format: just rssi
                try:
                    rssi = int(data_str.strip())
                except ValueError:
                    print(f"[{self.mac}] Cannot parse RSSI from: {data_str}")
                    return

            with data_lock:
                # Update current RSSI value for this beacon
                current_rssi[self.mac] = {
                    'rssi': rssi,
                    'timestamp': time.time()
                }
                
                # Get beacon info for the UI
                beacon_info = next((b for b in config['beacons'] if b['mac'] == self.mac), None)
                beacon_location = beacon_info.get('toado', 'unknown') if beacon_info else 'unknown'
                beacon_name = get_beacon_name(self.mac)

                print(f"[{beacon_name}] ✅ RSSI: {rssi} dBm (location: {beacon_location})")

                # Emit update to connected clients via SocketIO
                socketio.emit('rssi_update', {
                    'beacon_mac': self.mac,
                    'beacon_name': beacon_name,
                    'rssi': rssi,
                    'location': beacon_location,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })

        except Exception as e:
            print(f"[{self.mac}] ❌ Error in notification handler: {e}")
            import traceback
            traceback.print_exc()

class BeaconConnection:
    def __init__(self, beacon_info):
        self.mac = beacon_info['mac']
        self.peripheral = None
        self.thread = None
        self.running = True

    def connect_and_listen(self):
        while self.running:
            try:
                print(f"[{self.mac}] Connecting...")
                self.peripheral = Peripheral(self.mac)
                self.peripheral.setDelegate(WebBeaconDelegate(self.mac))

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
                if self.running:
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

@app.route('/')
def index():
    return render_template('index.html', 
                         beacons=config['beacons'],
                         fingerprints=fingerprints)

@app.route('/test')
def test():
    """Simple test endpoint"""
    return jsonify({
        'status': 'Server is running',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'beacons_configured': len(config['beacons'])
    })

@app.route('/api/current_rssi')
def get_current_rssi():
    """Get current RSSI values for all beacons"""
    with data_lock:
        formatted_rssi = {}
        current_time = time.time()
        for mac, data in current_rssi.items():
            beacon_name = get_beacon_name(mac)
            age = current_time - data['timestamp']
            formatted_rssi[beacon_name] = {
                'mac': mac,
                'rssi': data['rssi'],
                'timestamp': data['timestamp'],
                'age_seconds': round(age, 1)
            }
        return jsonify(formatted_rssi)

@app.route('/api/debug')
def debug_info():
    """Debug endpoint to check server status"""
    with data_lock:
        return jsonify({
            'beacons_configured': len(config['beacons']),
            'beacons_with_data': len(current_rssi),
            'current_rssi': current_rssi,
            'fingerprints_count': len(fingerprints),
            'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

@app.route('/api/save_fingerprint', methods=['POST'])
def save_fingerprint():
    """Save a new fingerprint with location and current RSSI values"""
    try:
        data = request.json
        print(f"Received fingerprint request: {data}")
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        x = float(data.get('x', 0))
        y = float(data.get('y', 0))
        
        with data_lock:
            print(f"Current RSSI data: {current_rssi}")
            
            if not current_rssi:
                return jsonify({'error': 'No RSSI data available. Make sure beacons are connected and sending data.'}), 400
            
            # Create fingerprint with timestamp, location and RSSI values
            fingerprint = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'location': {'x': x, 'y': y},
                'readings': {}
            }
            
            # Add RSSI readings for each beacon that has recent data
            current_time = time.time()
            for mac, rssi_data in current_rssi.items():
                age = current_time - rssi_data['timestamp']
                print(f"Beacon {mac}: age = {age:.1f}s")
                
                # Increase timeout to 30 seconds for more flexibility
                if age <= 30:
                    beacon_name = get_beacon_name(mac)
                    fingerprint['readings'][beacon_name] = {
                        'mac': mac,
                        'rssi': rssi_data['rssi']
                    }
                else:
                    print(f"Beacon {mac} data too old: {age:.1f}s")
            
            if not fingerprint['readings']:
                return jsonify({'error': f'No recent RSSI data available. All data older than 30 seconds. Current beacons: {list(current_rssi.keys())}'}), 400
            
            fingerprints.append(fingerprint)
            save_fingerprints()
            
            print(f"✅ Saved fingerprint at ({x}, {y}) with {len(fingerprint['readings'])} beacon readings")
            
            return jsonify({
                'status': 'success',
                'fingerprint': fingerprint
            })
            
    except Exception as e:
        print(f"❌ Error in save_fingerprint: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/fingerprints')
def get_fingerprints():
    """Get all saved fingerprints"""
    return jsonify(fingerprints)

@app.route('/api/fingerprints/export')
def export_fingerprints():
    """Export fingerprints as JSON file download"""
    from flask import make_response
    import json
    from datetime import datetime
    
    # Create export data with metadata
    export_data = {
        'export_info': {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_fingerprints': len(fingerprints),
            'beacon_configuration': config['beacons']
        },
        'fingerprints': fingerprints
    }
    
    # Create JSON response
    json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
    
    # Create response with proper headers for file download
    response = make_response(json_str)
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename=fingerprints_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    return response

@app.route('/api/fingerprints/clear', methods=['POST'])
def clear_fingerprints():
    """Clear all fingerprints"""
    global fingerprints
    fingerprints = []
    save_fingerprints()
    return jsonify({'status': 'success', 'message': 'All fingerprints cleared'})

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('status', {'message': 'Connected to server'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

def start_beacon_connections():
    """Start connections to all beacons using threading approach from basic.py"""
    connections = []
    
    print(f"🚀 Starting connections to {len(config['beacons'])} beacons...")
    print("Beacon configuration:")
    for i, beacon in enumerate(config['beacons']):
        print(f"  beacon{i+1}: {beacon['mac']} at {beacon['toado']}")
    print("=" * 60)
    
    # Create and start connections for all beacons
    for beacon in config['beacons']:
        conn = BeaconConnection(beacon)
        conn.start()
        connections.append(conn)
        time.sleep(0.5)  # Small delay between connections
    
    print(f"✅ Started {len(connections)} beacon connections")
    return connections

if __name__ == '__main__':
    # Start beacon connections in background
    connections = start_beacon_connections()
    
    try:
        print("\n🌐 Starting web server on http://localhost:5000")
        print("📱 Open the web interface to collect fingerprints")
        print("Press Ctrl+C to stop\n")
        
        # Run Flask app with SocketIO
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Stopping server...")
    finally:
        print("Disconnecting beacons...")
        for conn in connections:
            conn.disconnect()
        print("👋 All beacons disconnected. Goodbye!")
