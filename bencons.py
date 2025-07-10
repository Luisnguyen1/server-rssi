from bluepy.btle import DefaultDelegate, Peripheral, BTLEException
import time
import threading
import json
from datetime import datetime

CHAR_UUID = "e8e0f616-ff20-48d1-8f60-18f495a44385"

# Load beacon configuration
with open('bencons.json', 'r') as f:
    config = json.load(f)

# Create a delegate class to handle notifications
class BeaconDelegate(DefaultDelegate):
    def __init__(self, beacon_mac):
        super().__init__()
        self.beacon_mac = beacon_mac

    def handleNotification(self, cHandle, data):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] Beacon {self.beacon_mac} - Handle: {cHandle}, Data: {data}, Hex: {data.hex()}")

class BeaconConnection:
    def __init__(self, beacon_info):
        self.mac = beacon_info['mac']
        self.notify_handle = beacon_info['notify_handle']
        self.peripheral = None
        self.is_connected = False
        self.thread = None
        
    def connect_and_listen(self):
        """Connect to beacon and listen for notifications"""
        try:
            print(f"[{self.mac}] Connecting...")
            self.peripheral = Peripheral(self.mac)
            self.peripheral.setDelegate(BeaconDelegate(self.mac))
            
            # Find the characteristic
            print(f"[{self.mac}] Searching for characteristic...")
            char = self.peripheral.getCharacteristics(uuid=CHAR_UUID)[0]
            
            if not char.supportsRead():
                print(f"[{self.mac}] This characteristic does not support reading, only notifications.")
            
            # Enable notifications
            print(f"[{self.mac}] Enabling notifications...")
            self.peripheral.writeCharacteristic(char.getHandle() + 1, b'\x01\x00', withResponse=True)
            
            print(f"[{self.mac}] Connected successfully. Listening for notifications...")
            self.is_connected = True
            
            # Listen for notifications
            while self.is_connected:
                if self.peripheral.waitForNotifications(1.0):
                    continue
                else:
                    # Optional: uncomment the line below if you want to see "no notification" messages
                    # print(f"[{self.mac}] No notification in the last second.")
                    pass
                    
        except BTLEException as e:
            print(f"[{self.mac}] Bluetooth error: {e}")
        except Exception as e:
            print(f"[{self.mac}] Error: {e}")
        finally:
            self.disconnect()
    
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

def main():
    """Main function to handle multiple beacon connections"""
    beacon_connections = []
    
    print(f"Starting connections to {len(config['beacons'])} beacons...")
    
    # Create and start connections for all beacons
    for beacon_info in config['beacons']:
        beacon_conn = BeaconConnection(beacon_info)
        beacon_connections.append(beacon_conn)
        beacon_conn.start_thread()
        time.sleep(0.5)  # Small delay between connections
    
    try:
        print("\nAll beacons connected. Press Ctrl+C to stop...")
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