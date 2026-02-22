import json
import serial
import time

# UART port on Jetson (check with `ls /dev/ttyUSB*` or `dmesg`)
UART_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200
DEFAULT_PROTOCOL = "frame"  # "frame" (SAURON_UART_V1) or "json" (legacy compatibility)

# Open serial port (timeout=None blocks until a full line is received)
ser = serial.Serial(UART_PORT, BAUD_RATE, timeout=None)

FRAME_START = 0xAA
FRAME_END = 0x55
FRAME_VERSION = 0x01


def _normalize_pill_counts(pill_counts):
    return [
        max(0, min(20, int(pill_counts.get("pill1", 0) or 0))),
        max(0, min(20, int(pill_counts.get("pill2", 0) or 0))),
        max(0, min(20, int(pill_counts.get("pill3", 0) or 0))),
        max(0, min(20, int(pill_counts.get("pill4", 0) or 0))),
    ]


def build_sauron_uart_v1_frame(pill_counts):
    """
    SAURON_UART_V1 frame (8 bytes):
      [0] 0xAA start
      [1] 0x01 version
      [2] ch1_count
      [3] ch2_count
      [4] ch3_count
      [5] ch4_count
      [6] checksum = sum(bytes[1:6]) & 0xFF
      [7] 0x55 end
    """
    c1, c2, c3, c4 = _normalize_pill_counts(pill_counts)
    body = [FRAME_VERSION, c1, c2, c3, c4]
    checksum = sum(body) & 0xFF
    frame = bytes([FRAME_START, *body, checksum, FRAME_END])
    return frame


def _recv_ack_line():
    # Wait forever for confirmation (Ctrl+C to stop the script)
    while True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            print(f"Received: {line}")
            return line


def send_pill_command(pill_counts, protocol=DEFAULT_PROTOCOL):
    """
    pill_counts: dict like {"pill1": 2, "pill2": 1, "pill3":0, "pill4":3}
    """
    # Drop any delayed/stale responses before sending a new command.
    ser.reset_input_buffer()

    proto = str(protocol or DEFAULT_PROTOCOL).strip().lower()
    if proto == "json":
        json_cmd = json.dumps(pill_counts)
        # Legacy compatibility mode: newline-delimited JSON.
        ser.write((json_cmd + "\n").encode("utf-8"))
        print(f"Sent JSON: {json_cmd}")
        return _recv_ack_line()

    frame = build_sauron_uart_v1_frame(pill_counts)
    print("Sent Frame (SAURON_UART_V1):", " ".join(f"{b:02X}" for b in frame))
    ser.write(frame)
    return _recv_ack_line()

if __name__ == "__main__":
    # Example command: actuate servos 1-4
    pill_cmd = {"pill1": 2, "pill2": 1, "pill3": 0, "pill4": 3}
    response = send_pill_command(pill_cmd, protocol=DEFAULT_PROTOCOL)
    print("Final response:", response)

    # You can loop and test multiple times
    time.sleep(10)
    pill_cmd = {"pill1": 1, "pill2": 0, "pill3": 2, "pill4": 1}
    response = send_pill_command(pill_cmd, protocol=DEFAULT_PROTOCOL)
    print("Final response:", response)
