#include <Arduino.h>
#include <Servo.h>
#include <ArduinoJson.h> // https://arduinojson.org/

// UART pins
#define UART_RX 16
#define UART_TX 17

// Servo pins
#define SERVO_PIN_1 18
#define SERVO_PIN_2 19
#define SERVO_PIN_3 21
#define SERVO_PIN_4 22

// Movement timing
unsigned long moveDuration = 1000; // 0 -> 180 -> 0 in 1 second

Servo servo1, servo2, servo3, servo4;

// Fallback mechanism timing
unsigned long lastCommandTime = 0;
const unsigned long fallbackDelay = 5000; // 5 seconds no command triggers fallback

// Actuate servo once: 0 -> 180 -> 0
void moveServo(Servo &servo, unsigned long duration) {
  int steps = 20;
  int stepDelay = duration / (2 * steps);

  // 0 -> 180
  for (int i = 0; i <= steps; i++) {
    int pos = map(i, 0, steps, 0, 180);
    servo.write(pos);
    delay(stepDelay);
  }

  // 180 -> 0
  for (int i = 0; i <= steps; i++) {
    int pos = map(i, 0, steps, 180, 0);
    servo.write(pos);
    delay(stepDelay);
  }

  // After each move, perform a short shake
  fallbackShake(servo);
}

// Rapid back-and-forth shake
void fallbackShake(Servo &servo, int shakeCount = 3, int shakeSpeed = 50) {
  for (int i = 0; i < shakeCount; i++) {
    servo.write(0);
    delay(shakeSpeed);
    servo.write(20);
    delay(shakeSpeed);
  }
  servo.write(0);
}

// Map pill key to servo reference
Servo* getServo(String key) {
  if (key == "pill1") return &servo1;
  if (key == "pill2") return &servo2;
  if (key == "pill3") return &servo3;
  if (key == "pill4") return &servo4;
  return nullptr;
}

void setup() {
  Serial1.begin(115200, SERIAL_8N1, UART_RX, UART_TX);

  servo1.attach(SERVO_PIN_1);
  servo2.attach(SERVO_PIN_2);
  servo3.attach(SERVO_PIN_3);
  servo4.attach(SERVO_PIN_4);
}

void loop() {
  static String inputBuffer = "";

  while (Serial1.available()) {
    char c = Serial1.read();
    if (c == '\n') {
      // End of JSON command
      DynamicJsonDocument doc(256);
      DeserializationError error = deserializeJson(doc, inputBuffer);
      inputBuffer = ""; // clear buffer for next command

      if (!error) {
        lastCommandTime = millis();
        // Iterate through pills
        for (JsonPair kv : doc.as<JsonObject>()) {
          String pillKey = kv.key().c_str();
          int count = kv.value().as<int>();
          Servo* servo = getServo(pillKey);
          if (servo != nullptr && count > 0) {
            for (int i = 0; i < count; i++) {
              moveServo(*servo, moveDuration); // move + shake happens inside
              delay(200); // optional pause between actuations
            }
          }
        }
        // Send confirmation back to Jetson
        Serial1.println("{\"status\": \"done\"}");
      }
    } else {
      inputBuffer += c;
    }
  }

//   // Fallback: shake all servos if no command received for fallbackDelay
//   if (millis() - lastCommandTime > fallbackDelay) {
//     fallbackShake(servo1);
//     fallbackShake(servo2);
//     fallbackShake(servo3);
//     fallbackShake(servo4);
//     lastCommandTime = millis();
//   }
}
