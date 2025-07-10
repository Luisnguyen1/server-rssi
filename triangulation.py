import math
import json
from typing import Dict, List, Tuple, Optional

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
        
        # Store recent RSSI readings for each beacon
        self.rssi_readings = {}
    
    def rssi_to_distance(self, rssi: int, tx_power: int = -59) -> float:
        """
        Convert RSSI to distance estimate using logarithmic path loss model
        
        Args:
            rssi: Received Signal Strength Indicator
            tx_power: Transmit power at 1 meter (default -59 dBm)
            
        Returns:
            Estimated distance in meters
        """
        if rssi == 0:
            return -1.0
        
        ratio = tx_power * 1.0 / rssi
        if ratio < 1.0:
            return math.pow(ratio, 10)
        else:
            accuracy = (0.89976) * math.pow(ratio, 7.7095) + 0.111
            return accuracy
    
    def update_rssi(self, mac: str, rssi: int):
        """
        Update RSSI reading for a beacon
        
        Args:
            mac: MAC address of the beacon
            rssi: RSSI value
        """
        if mac not in self.rssi_readings:
            self.rssi_readings[mac] = []
        
        # Keep only last 5 readings for smoothing
        self.rssi_readings[mac].append(rssi)
        if len(self.rssi_readings[mac]) > 5:
            self.rssi_readings[mac].pop(0)
    
    def get_average_rssi(self, mac: str) -> Optional[int]:
        """
        Get averaged RSSI for more stable distance calculation
        
        Args:
            mac: MAC address of the beacon
            
        Returns:
            Average RSSI or None if no readings available
        """
        if mac not in self.rssi_readings or not self.rssi_readings[mac]:
            return None
        
        return sum(self.rssi_readings[mac]) / len(self.rssi_readings[mac])
    
    def trilaterate(self) -> Optional[Tuple[float, float]]:
        """
        Calculate user position using trilateration
        
        Returns:
            Tuple of (x, y) coordinates or None if insufficient data
        """
        # Check if we have RSSI data for all 3 beacons
        beacon_macs = list(self.beacons.keys())
        if len(beacon_macs) < 3:
            return None
        
        distances = {}
        positions = {}
        
        # Calculate distances for all beacons with RSSI data
        for mac in beacon_macs:
            avg_rssi = self.get_average_rssi(mac)
            if avg_rssi is not None:
                distances[mac] = self.rssi_to_distance(avg_rssi)
                positions[mac] = (self.beacons[mac]['x'], self.beacons[mac]['y'])
        
        # Need at least 3 beacons for trilateration
        if len(distances) < 3:
            return None
        
        # Use first 3 beacons with valid data
        beacon_list = list(distances.keys())[:3]
        
        # Extract coordinates and distances
        x1, y1 = positions[beacon_list[0]]
        x2, y2 = positions[beacon_list[1]]
        x3, y3 = positions[beacon_list[2]]
        
        r1 = distances[beacon_list[0]]
        r2 = distances[beacon_list[1]]
        r3 = distances[beacon_list[2]]
        
        # Trilateration calculation
        A = 2 * (x2 - x1)
        B = 2 * (y2 - y1)
        C = r1**2 - r2**2 - x1**2 + x2**2 - y1**2 + y2**2
        D = 2 * (x3 - x2)
        E = 2 * (y3 - y2)
        F = r2**2 - r3**2 - x2**2 + x3**2 - y2**2 + y3**2
        
        # Solve the system of equations
        denominator = A * E - B * D
        if abs(denominator) < 1e-10:  # Avoid division by zero
            return None
        
        x = (C * E - F * B) / denominator
        y = (A * F - D * C) / denominator
        
        return (x, y)
    
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
    
    def get_user_position(self, user_id: str = None) -> Optional[Dict]:
        """
        Get current position for a user
        
        Args:
            user_id: User ID to get position for (optional)
            
        Returns:
            Dictionary with position info or None
        """
        position = self.trilaterate()
        if position is None:
            return None
        
        x, y = position
        
        # Calculate confidence based on number of available beacons
        available_beacons = len([mac for mac in self.beacons.keys() 
                               if self.get_average_rssi(mac) is not None])
        confidence = min(available_beacons / 3.0 * 100, 100)
        
        return {
            'user_id': user_id,
            'x': round(x, 2),
            'y': round(y, 2),
            'confidence': round(confidence, 1),
            'beacons_used': available_beacons
        }
