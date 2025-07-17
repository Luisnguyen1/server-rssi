import math
import json
from typing import Dict, List, Tuple, Optional
from filterpy.kalman import KalmanFilter

class User:
    def __init__(self, user_id: str):
        """
        Initialize a user with their ID
        
        Args:
            user_id: Unique identifier for the user
        """
        self.user_id = user_id
        self.beacon_data = {}  # {beacon_mac: {'rssi': rssi, 'distance': distance}}
        self.last_position = None  # Last calculated position
        self.position_history = []  # History of positions
        self.kalman_filters = {}  # {beacon_mac: KalmanFilter object}
        
    def update_beacon_rssi(self, beacon_mac: str, rssi: int, beacon_position: Tuple[float, float]) -> bool:
        """
        Update RSSI for a beacon and check if position should be recalculated
        
        Args:
            beacon_mac: MAC address of the beacon
            rssi: New RSSI value
            beacon_position: (x, y) position of the beacon
            
        Returns:
            True if there's a significant change requiring position update
        """
        # Kalman filter for RSSI
        import numpy as np
        if beacon_mac not in self.kalman_filters:
            kf = KalmanFilter(dim_x=1, dim_z=1)
            kf.x = np.array([[rssi]], dtype=float)  # initial state
            kf.F = np.array([[1]], dtype=float)     # state transition matrix
            kf.H = np.array([[1]], dtype=float)     # measurement function
            kf.P *= 2        # initial uncertainty
            kf.R *= 4        # measurement noise
            kf.Q *= 0.01     # process noise
            self.kalman_filters[beacon_mac] = kf
        else:
            kf = self.kalman_filters[beacon_mac]
        kf.predict()
        kf.update(np.array([[rssi]], dtype=float))
        filtered_rssi = float(kf.x[0, 0])
        # Lưu lại lịch sử RSSI nếu muốn debug hoặc so sánh
        rssi_history = []
        if beacon_mac in self.beacon_data and 'rssi_history' in self.beacon_data[beacon_mac]:
            rssi_history = self.beacon_data[beacon_mac]['rssi_history']
        rssi_history.append(rssi)
        if len(rssi_history) > 5:
            rssi_history.pop(0)
        avg_rssi = sum(rssi_history) / len(rssi_history)
        distance = self._rssi_to_distance(filtered_rssi)
        # Check if this is a new beacon or if there's significant change
        is_new_beacon = beacon_mac not in self.beacon_data
        significant_change = False
        
        if not is_new_beacon:
            old_distance = self.beacon_data[beacon_mac]['distance']
            # Consider significant if distance changes by more than 0.5 meters
            significant_change = abs(distance - old_distance) > 0.5
        
        # Update beacon data
        self.beacon_data[beacon_mac] = {
            'rssi': rssi,
            'filtered_rssi': filtered_rssi,
            'rssi_history': rssi_history,
            'distance': distance,
            'position': beacon_position
        }
        # Debug info
        print(f"Debug: User {self.user_id} - Beacon {beacon_mac}: RSSI={rssi}, AVG_RSSI={avg_rssi:.2f}, Kalman_RSSI={filtered_rssi:.2f}, Distance={distance:.2f}m, New={is_new_beacon}, Change={significant_change}")
        return is_new_beacon or significant_change
    
    def _rssi_to_distance(self, rssi: int, tx_power: int = -55) -> float:
        """
        Convert RSSI to distance estimate using logarithmic path loss model
        
        Args:
            rssi: Received Signal Strength Indicator
            tx_power: Transmit power at 1 meter (default -55 dBm)
            
        Returns:
            Estimated distance in meters
        """
        if rssi == 0:
            return -1.0
        
        # For negative RSSI values (which is normal), use absolute value in calculation
        if rssi > 0:
            print(f"Warning: Positive RSSI value {rssi} for user {self.user_id}")
            return -1.0
        
        # Use a simpler and more reliable distance calculation
        # Based on free space path loss model
        if rssi >= tx_power:
            return 0.1  # Very close, minimum distance
        
        # Calculate distance using path loss formula
        # Distance = 10^((TxPower - RSSI) / (10 * n)) where n = 2 for free space
        distance = math.pow(10, (tx_power - rssi) / 30 )
        
        # Limit distance to reasonable range (0.1m to 100m)
        distance = max(0.1, min(distance, 100.0))
        
        return distance
    
    def get_closest_beacons(self, count: int = 3) -> List[Tuple[str, Dict]]:
        """
        Get the closest beacons sorted by distance
        
        Args:
            count: Number of closest beacons to return
            
        Returns:
            List of (beacon_mac, beacon_data) tuples sorted by distance
        """
        if not self.beacon_data:
            return []
        
        # Sort beacons by distance
        sorted_beacons = sorted(
            self.beacon_data.items(),
            key=lambda x: x[1]['distance']
        )
        
        return sorted_beacons[:count]
    
    def can_calculate_position(self) -> bool:
        """
        Check if we have enough beacons to calculate position
        
        Returns:
            True if we have at least 3 beacons
        """
        return len(self.beacon_data) >= 3
    
    def calculate_position(self) -> Optional[Tuple[float, float]]:
        """
        Calculate user position using trilateration with 3 closest beacons
        
        Returns:
            Tuple of (x, y) coordinates or None if insufficient data
        """
        if not self.can_calculate_position():
            return None
        
        # Get 3 closest beacons
        closest_beacons = self.get_closest_beacons(3)
        
        # Extract coordinates and distances
        beacon1_mac, beacon1_data = closest_beacons[0]
        beacon2_mac, beacon2_data = closest_beacons[1]
        beacon3_mac, beacon3_data = closest_beacons[2]
        
        x1, y1 = beacon1_data['position']
        x2, y2 = beacon2_data['position']
        x3, y3 = beacon3_data['position']
        
        r1 = beacon1_data['distance']
        r2 = beacon2_data['distance']
        r3 = beacon3_data['distance']
        
        # Debug: Check if distances are reasonable
        if r1 <= 0 or r2 <= 0 or r3 <= 0:
            print(f"Debug: Invalid distances for user {self.user_id}: r1={r1}, r2={r2}, r3={r3}")
            return None
        
        # Trilateration calculation
        try:
            A = 2 * (x2 - x1)
            B = 2 * (y2 - y1)
            C = r1**2 - r2**2 - x1**2 + x2**2 - y1**2 + y2**2
            D = 2 * (x3 - x2)
            E = 2 * (y3 - y2)
            F = r2**2 - r3**2 - x2**2 + x3**2 - y2**2 + y3**2
            
            # Solve the system of equations
            denominator = A * E - B * D
            if abs(denominator) < 1e-10:  # Avoid division by zero
                print(f"Debug: Denominator too small for user {self.user_id}: {denominator}")
                return None
            
            x = (C * E - F * B) / denominator
            y = (A * F - D * C) / denominator
            
            return (x, y)
            
        except Exception as e:
            print(f"Debug: Trilateration error for user {self.user_id}: {e}")
            return None
    
    def update_position(self) -> Optional[Dict]:
        """
        Calculate new position and update if changed
        
        Returns:
            Position info dictionary if position was updated, None otherwise
        """
        new_position = self.calculate_position()
        if new_position is None:
            return None
        
        x, y = new_position
        
        # Check if position has changed significantly (more than 0.1 meters)
        position_changed = True
        if self.last_position:
            last_x, last_y = self.last_position
            distance_moved = math.sqrt((x - last_x)**2 + (y - last_y)**2)
            position_changed = distance_moved > 0.1
        
        if position_changed:
            self.last_position = (x, y)
            self.position_history.append((x, y))
            
            # Keep only last 10 positions
            if len(self.position_history) > 10:
                self.position_history.pop(0)
            
            # Get info about beacons used
            closest_beacons = self.get_closest_beacons(3)
            
            return {
                'user_id': self.user_id,
                'x': round(x, 2),
                'y': round(y, 2),
                'beacons_used': len(self.beacon_data),
                'closest_beacons': [
                    {
                        'mac': mac,
                        'distance': round(data['distance'], 2),
                        'rssi': data['rssi']
                    }
                    for mac, data in closest_beacons
                ]
            }
        
        return None
    
    def get_status(self) -> Dict:
        """
        Get current status of the user
        
        Returns:
            Dictionary with user status information
        """
        return {
            'user_id': self.user_id,
            'total_beacons': len(self.beacon_data),
            'can_calculate': self.can_calculate_position(),
            'last_position': self.last_position,
            'beacon_count': len(self.beacon_data)
        }

class Triangulation:
    def __init__(self, config_file: str = 'bencons.json'):
        """
        Initialize triangulation with beacon configuration
        
        Args:
            config_file: Path to JSON file containing beacon configuration
        """
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        self.beacons = {}
        # Parse beacon coordinates from config
        for beacon in self.config['beacons']:
            mac = beacon['mac']
            coords = beacon['toado'].split(',')
            self.beacons[mac] = {
                'x': float(coords[0]),
                'y': float(coords[1])
            }
        
        # Store users
        self.users = {}  # {user_id: User object}
    
    def update_rssi(self, user_id: str, mac: str, rssi: int) -> Optional[Dict]:
        """
        Update RSSI reading for a specific user and beacon
        
        Args:
            user_id: User ID
            mac: MAC address of the beacon
            rssi: RSSI value
            
        Returns:
            Position info if position was updated, None otherwise
        """
        # Create user if doesn't exist
        if user_id not in self.users:
            self.users[user_id] = User(user_id)
        
        # Check if beacon exists in our configuration
        if mac not in self.beacons:
            print(f"Warning: Unknown beacon {mac}")
            return None
        
        user = self.users[user_id]
        beacon_position = (self.beacons[mac]['x'], self.beacons[mac]['y'])
        
        # Update beacon RSSI and check if significant change occurred
        has_significant_change = user.update_beacon_rssi(mac, rssi, beacon_position)
        
        # Only calculate position if there's significant change and we have enough beacons
        if has_significant_change and user.can_calculate_position():
            return user.update_position()
        
        return None
    
    def get_user_status(self, user_id: str) -> Optional[Dict]:
        """
        Get status of a specific user
        
        Args:
            user_id: User ID to get status for
            
        Returns:
            Dictionary with user status or None if user doesn't exist
        """
        if user_id not in self.users:
            return None
        
        return self.users[user_id].get_status()
    
    def get_all_users_status(self) -> Dict:
        """
        Get status of all users
        
        Returns:
            Dictionary with all users' status
        """
        return {
            user_id: user.get_status() 
            for user_id, user in self.users.items()
        }
    
    def force_calculate_position(self, user_id: str) -> Optional[Dict]:
        """
        Force calculate position for a user (bypass change detection)
        
        Args:
            user_id: User ID to calculate position for
            
        Returns:
            Position info or None if calculation failed
        """
        if user_id not in self.users:
            return None
        
        user = self.users[user_id]
        if not user.can_calculate_position():
            return None
        
        position = user.calculate_position()
        if position is None:
            return None
        
        x, y = position
        closest_beacons = user.get_closest_beacons(3)
        
        return {
            'user_id': user_id,
            'x': round(x, 2),
            'y': round(y, 2),
            'beacons_used': len(user.beacon_data),
            'closest_beacons': [
                {
                    'mac': mac,
                    'distance': round(data['distance'], 2),
                    'rssi': data['rssi']
                }
                for mac, data in closest_beacons
            ]
        }
    
    def parse_beacon_data(self, data: str) -> Tuple[str, int]:
        """
        Parse beacon data string to extract user_id and RSSI
        
        Args:
            data: Data string in format "user_id:rssi"
            
        Returns:
            Tuple of (user_id, rssi)
        """
        try:
            parts = data.split(':')
            user_id = parts[0]
            rssi = int(parts[1])
            return user_id, rssi
        except (ValueError, IndexError):
            raise ValueError(f"Invalid data format: {data}")
    
    def get_debug_info(self, user_id: str) -> Dict:
        """
        Get debug information for a user
        
        Args:
            user_id: User ID to get debug info for
            
        Returns:
            Dictionary with debug information
        """
        if user_id not in self.users:
            return {
                'user_id': user_id,
                'exists': False,
                'message': 'User not found'
            }
        
        user = self.users[user_id]
        closest_beacons = user.get_closest_beacons(3)
        
        return {
            'user_id': user_id,
            'exists': True,
            'total_beacons_detected': len(user.beacon_data),
            'can_calculate_position': user.can_calculate_position(),
            'last_position': user.last_position,
            'closest_beacons': [
                {
                    'mac': mac,
                    'position': data['position'],
                    'distance': round(data['distance'], 2),
                    'rssi': data['rssi']
                }
                for mac, data in closest_beacons
            ]
        }
