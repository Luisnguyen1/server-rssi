from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import time
import threading
import json
from datetime import datetime
from triangulation import Triangulation

CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"

# Load beacon configuration
with open('bencons.json', 'r') as f:
    config = json.load(f)

# Initialize triangulation system
triangulation = Triangulation()

# Create a delegate class to handle notifications
class BeaconDelegate(DefaultDelegate):
    def __init__(self, beacon_mac):
        super().__init__()
        self.beacon_mac = beacon_mac

    def handleNotification(self, cHandle, data):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        data_str = data.decode('utf-8')
        print(f"[{timestamp}] Beacon {self.beacon_mac} - Handle: {cHandle}, Data: {data_str}, Hex: {data.hex()}")
        
        # Parse beacon data and update triangulation
        try:
            user_id, rssi = triangulation.parse_beacon_data(data_str)
            
            # Update RSSI and get position if there's significant change
            position_info = triangulation.update_rssi(user_id, self.beacon_mac, rssi)
            
            # Always try to get current position for display
            current_position = triangulation.force_calculate_position(user_id)
            
            if current_position:
                if position_info:
                    # Position was updated due to significant change
                    print(f"[{timestamp}] 🎯 User {user_id} NEW POSITION: X={current_position['x']}, Y={current_position['y']}")
                else:
                    # Position calculated but no significant change - show simplified version
                    print(f"[{timestamp}] 📍 User {user_id}: X={current_position['x']}, Y={current_position['y']}")
            else:
                # Debug: show why position can't be calculated
                debug_info = triangulation.get_debug_info(user_id)
                if debug_info['exists']:
                    print(f"[{timestamp}] User {user_id}: {debug_info['total_beacons_detected']}/3 beacons detected")
                else:
                    print(f"[{timestamp}] User {user_id}: First detection")
                
        except ValueError as e:
            print(f"[{timestamp}] Error parsing data: {e}")

class BeaconConnection:
    def __init__(self, beacon_info):
        self.mac = beacon_info['mac']
        self.notify_handle = beacon_info['notify_handle']
        self.peripheral = None
        self.is_connected = False
        self.thread = None
        
    def connect_and_listen(self):
        """Connect to beacon and listen for notifications. Auto reconnect if disconnected."""
        while True:
            try:
                self.disconnect()
                print(f"[{self.mac}] Waiting 1s before connecting...")
                time.sleep(1)
                print(f"[{self.mac}] Connecting...")
                self.peripheral = Peripheral(self.mac)
                self.peripheral.setDelegate(BeaconDelegate(self.mac))
                print(f"[{self.mac}] Searching for characteristic...")
                char = self.peripheral.getCharacteristics(uuid=CHAR_UUID)[0]
                if not char.supportsRead():
                    print(f"[{self.mac}] This characteristic does not support reading, only notifications.")
                print(f"[{self.mac}] Enabling notifications...")
                self.peripheral.writeCharacteristic(char.getHandle() + 1, b'\x01\x00', withResponse=True)
                print(f"[{self.mac}] Connected successfully. Listening for notifications...")
                self.is_connected = True
                while self.is_connected:
                    try:
                        notified = self.peripheral.waitForNotifications(1.0)
                        if notified:
                            continue
                        # else: pass
                    except BTLEException as e:
                        print(f"[{self.mac}] Bluetooth error or disconnect: {e}. Will scan and reconnect...")
                        break
                    except Exception as e:
                        print(f"[{self.mac}] Unexpected error in loop: {e}")
                        time.sleep(0.5)
                print(f"[{self.mac}] Lost connection, will scan and reconnect in 2s...")
                time.sleep(2)
            except BTLEException as e:
                print(f"[{self.mac}] Bluetooth error: {e}. Will scan and reconnect in 2s...")
                time.sleep(2)
            except Exception as e:
                print(f"[{self.mac}] Error: {e}. Will scan and reconnect in 2s...")
                time.sleep(2)
            finally:
                self.disconnect()
                self.peripheral = None
    
    def disconnect(self):
        """Disconnect from beacon"""
        self.is_connected = False
        if self.peripheral:
            try:
                self.peripheral.disconnect()
                print(f"[{self.mac}] Disconnected.")
            except:
                pass
    
    def start_thread(self):
        """Start connection in a separate thread"""
        self.thread = threading.Thread(target=self.connect_and_listen, daemon=True)
        self.thread.start()
        return self.thread

def print_positions_periodically():
    """Print positions of all users every 2 seconds"""
    while True:
        time.sleep(2)
        try:
            all_users = triangulation.get_all_users_status()
            if all_users:
                print("\n" + "="*50)
                print(f"📊 CURRENT POSITIONS [{datetime.now().strftime('%H:%M:%S')}]")
                print("="*50)
                
                for user_id, status in all_users.items():
                    if status['can_calculate']:
                        position = triangulation.force_calculate_position(user_id)
                        if position:
                            print(f"👤 User {user_id}: X={position['x']}, Y={position['y']} ({position['beacons_used']} beacons)")
                            # Show closest beacons
                            for beacon in position['closest_beacons'][:3]:
                                print(f"   └─ {beacon['mac']}: {beacon['distance']}m (RSSI: {beacon['rssi']})")
                        else:
                            print(f"👤 User {user_id}: Position calculation failed")
                    else:
                        print(f"👤 User {user_id}: Collecting data... ({status['beacon_count']}/3 beacons)")
                print("="*50 + "\n")
            
        except Exception as e:
            print(f"Error in position monitoring: {e}")

def main():
    """Main function to handle multiple beacon connections"""
    beacon_connections = []
    
    print(f"Starting connections to {len(config['beacons'])} beacons...")
    print("Beacon positions:")
    for beacon in config['beacons']:
        print(f"  {beacon['mac']}: {beacon['toado']}")
    print("=" * 60)
    
    # Create and start connections for all beacons
    for beacon_info in config['beacons']:
        beacon_conn = BeaconConnection(beacon_info)
        beacon_connections.append(beacon_conn)
        beacon_conn.start_thread()
        time.sleep(0.5)  # Small delay between connections
    
    # Start position monitoring thread
    position_thread = threading.Thread(target=print_positions_periodically, daemon=True)
    position_thread.start()
    print("📍 Position monitoring thread started (every 2 seconds)")
    
    try:
        print("\nAll beacons connected. Press Ctrl+C to stop...")
        print("🔍 Monitoring users... Position will be calculated when:")
        print("   • User detected by at least 3 beacons")
        print("   • Significant movement detected (>0.5m distance change)")
        print("=" * 60)
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nProgram interrupted by user.")
    finally:
        print("Disconnecting all beacons...")
        for beacon_conn in beacon_connections:
            beacon_conn.disconnect()
        
        # Wait for all threads to finish
        for beacon_conn in beacon_connections:
            if beacon_conn.thread:
                beacon_conn.thread.join(timeout=2)
        
        print("All beacons disconnected.")

if __name__ == "__main__":
    main()