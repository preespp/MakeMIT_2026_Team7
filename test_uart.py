import serial
import time
import json

# UART port on Jetson (check with `ls /dev/ttyUSB*` or `dmesg`)
UART_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

# Open serial port
ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=1)

def send_pill_command(pill_counts):
    """
    pill_counts: dict like {"pill1": 2, "pill2": 1, "pill3":0, "pill4":3}
    """
    json_cmd = json.dumps(pill_counts)
    # Send JSON with newline as ESP32 expects
    ser.write((json_cmd + "\n").encode('utf-8'))
    print(f"Sent: {json_cmd}")

    # Wait for confirmation
    start_time = time.time()
    while True:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            if line:
                print(f"Received: {line}")
                return line
        if time.time() - start_time > 10:  # 10s timeout
            print("Timeout waiting for confirmation")
            return None
        time.sleep(0.01)

if __name__ == "__main__":
    # Example command: actuate servos 1-4
    pill_cmd = {"pill1": 2, "pill2": 1, "pill3": 0, "pill4": 3}
    response = send_pill_command(pill_cmd)
    print("Final response:", response)

    # You can loop and test multiple times
    time.sleep(2)
    pill_cmd = {"pill1": 1, "pill2": 0, "pill3": 2, "pill4": 1}
    response = send_pill_command(pill_cmd)
    print("Final response:", response)
