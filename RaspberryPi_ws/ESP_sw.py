import serial
import subprocess

ser = serial.Serial('/dev/ttyACM1', 115200)

while True:
    line = ser.readline().decode().strip()
    if line == "ENTER":
        # アクティブウィンドウにEnterキーを送信
        subprocess.run(["xdotool", "key", "Return"])