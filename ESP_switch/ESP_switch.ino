const int swPin = 3;
bool lastState = LOW;

void setup() {
  pinMode(swPin, INPUT);
  Serial.begin(115200);
}

void loop() {
  bool currentState = digitalRead(swPin);
  if (lastState == LOW && currentState == HIGH) {
    Serial.println("ENTER");
  }
  lastState = currentState;
  delay(10);
}