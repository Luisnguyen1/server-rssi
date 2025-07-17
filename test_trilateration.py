#!/usr/bin/env python3
"""
Test script cho hệ thống trilateration
"""
import json
import math
import numpy as np

# Load beacon config
with open("bencons.json", "r") as f:
    config = json.load(f)
beacons = config["beacons"]

# Tọa độ beacon từ "toado": "x,y"
beacon_coords = {}
for b in beacons:
    if "toado" in b:
        try:
            x_str, y_str = b["toado"].split(",")
            beacon_coords[b["mac"]] = (float(x_str), float(y_str))
        except:
            print(f"⚠️ Lỗi tọa độ beacon {b['mac']}, giá trị: {b['toado']}")

def trilaterate(positions, distances):
    """
    Tính toán vị trí bằng phương pháp trilateration
    """
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
    
    # Tính độ chính xác
    accuracy = calculate_position_accuracy(positions[:3], distances[:3], (x, y))
    
    return (x, y), accuracy

def calculate_position_accuracy(positions, distances, calculated_pos):
    """Tính độ chính xác của vị trí được tính toán"""
    if not calculated_pos:
        return 0
    
    x, y = calculated_pos
    errors = []
    
    for (bx, by), expected_dist in zip(positions, distances):
        actual_dist = math.sqrt((x - bx)**2 + (y - by)**2)
        error = abs(actual_dist - expected_dist)
        errors.append(error)
    
    avg_error = sum(errors) / len(errors)
    # Chuyển đổi thành % độ chính xác
    accuracy = max(0, 100 - (avg_error * 10))
    return round(accuracy, 1)

def test_trilateration():
    """Test với dữ liệu mẫu"""
    print("🧪 TESTING TRILATERATION SYSTEM")
    print("="*50)
    
    # In thông tin beacon
    print("🛰️ Beacon positions:")
    for i, (mac, coord) in enumerate(beacon_coords.items()):
        print(f"   beacon{i+1}: {coord} (MAC: {mac})")
    
    # Test case 1: User ở giữa
    print(f"\n📍 Test Case 1: User at center (1.5, 3.5)")
    test_positions = list(beacon_coords.values())
    # Tính khoảng cách thực tế đến user ở (1.5, 3.5)
    user_pos = (1.5, 3.5)
    test_distances = []
    for bx, by in test_positions:
        dist = math.sqrt((user_pos[0] - bx)**2 + (user_pos[1] - by)**2)
        test_distances.append(dist)
    
    print(f"   Expected distances: {[round(d, 2) for d in test_distances]}")
    
    calculated_pos, accuracy = trilaterate(test_positions, test_distances)
    if calculated_pos:
        print(f"   Calculated position: ({calculated_pos[0]:.2f}, {calculated_pos[1]:.2f})")
        print(f"   Accuracy: {accuracy}%")
        error = math.sqrt((calculated_pos[0] - user_pos[0])**2 + (calculated_pos[1] - user_pos[1])**2)
        print(f"   Position error: {error:.3f}m")
    else:
        print("   ❌ Calculation failed")
    
    # Test case 2: User với một số nhiễu trong khoảng cách
    print(f"\n📍 Test Case 2: User at (2, 5) with measurement noise")
    user_pos = (2, 5)
    test_distances = []
    for bx, by in test_positions:
        dist = math.sqrt((user_pos[0] - bx)**2 + (user_pos[1] - by)**2)
        # Thêm nhiễu ±0.5m
        dist += 0.3  # Giả lập sai số đo
        test_distances.append(dist)
    
    print(f"   Measured distances: {[round(d, 2) for d in test_distances]}")
    
    calculated_pos, accuracy = trilaterate(test_positions, test_distances)
    if calculated_pos:
        print(f"   Calculated position: ({calculated_pos[0]:.2f}, {calculated_pos[1]:.2f})")
        print(f"   Accuracy: {accuracy}%")
        error = math.sqrt((calculated_pos[0] - user_pos[0])**2 + (calculated_pos[1] - user_pos[1])**2)
        print(f"   Position error: {error:.3f}m")
    else:
        print("   ❌ Calculation failed")

def simulate_user_data():
    """Mô phỏng dữ liệu user như hệ thống thực"""
    print(f"\n📱 SIMULATED USER DATA")
    print("="*50)
    
    # Mô phỏng user data
    simulated_users = {
        "User123": {
            beacons[0]["mac"]: 3.2,  # beacon1
            beacons[1]["mac"]: 2.8,  # beacon2  
            beacons[2]["mac"]: 5.1   # beacon3
        },
        "UserABC": {
            beacons[0]["mac"]: 1.5,  # beacon1
            beacons[1]["mac"]: 4.2,  # beacon2
            beacons[2]["mac"]: 2.9   # beacon3
        }
    }
    
    for user_id, distances in simulated_users.items():
        print(f"\n👤 User: {user_id}")
        
        # Thu thập tọa độ và khoảng cách
        coords = []
        dists = []
        for mac, distance in distances.items():
            if mac in beacon_coords:
                coords.append(beacon_coords[mac])
                dists.append(distance)
                beacon_name = f"beacon{list(beacon_coords.keys()).index(mac) + 1}"
                print(f"   🛰️ {beacon_name} {beacon_coords[mac]} ➤ {distance}m")
        
        # Tính vị trí
        if len(coords) >= 3:
            position, accuracy = trilaterate(coords, dists)
            if position:
                x, y = position
                print(f"   📍 Calculated position: ({x:.2f}, {y:.2f})")
                print(f"   🎯 Accuracy: {accuracy}%")
            else:
                print("   ❌ Position calculation failed")

if __name__ == "__main__":
    test_trilateration()
    simulate_user_data()
