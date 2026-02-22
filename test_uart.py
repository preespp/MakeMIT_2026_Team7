import serial
import time
import json

# UART port on Jetson (check with `ls /dev/ttyUSB*` or `dmesg`)
UART_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

# Open serial port (timeout=None blocks until a full line is received)
ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=None)

def send_pill_command(pill_counts):
    """
    pill_counts: dict like {"pill1": 2, "pill2": 1, "pill3":0, "pill4":3}
    """
    # Drop any delayed/stale responses before sending a new command.
    ser.reset_input_buffer()

    json_cmd = json.dumps(pill_counts)
    # Send JSON with newline as ESP32 expects
    ser.write((json_cmd + "\n").encode('utf-8'))
    print(f"Sent: {json_cmd}")

    # Wait forever for confirmation (Ctrl+C to stop the script)
    while True:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if line:
            print(f"Received: {line}")
            return line

if __name__ == "__main__":
    # Example command: actuate servos 1-4
    pill_cmd = {"pill1": 2, "pill2": 1, "pill3": 0, "pill4": 3}
    response = send_pill_command(pill_cmd)
    print("Final response:", response)

    # You can loop and test multiple times
    time.sleep(10)
    pill_cmd = {"pill1": 1, "pill2": 0, "pill3": 2, "pill4": 1}
    response = send_pill_command(pill_cmd)
    print("Final response:", response)
