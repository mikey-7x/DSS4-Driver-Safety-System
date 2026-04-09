#include <Servo.h>

// ==========================================
// NEW CUSTOM ATMEGA32A PINOUT (D-PORT GROUPED)
// ==========================================
#define MOTOR_PIN 15     // PD7 (TRUE PWM PIN for Speed Control)
#define SERVO_PIN 3      // PB3 (Steering)
#define PROX_CENTER 10   // PD2 (Controls Braking/Speed)
#define BUZZER_PIN 11    // PD3 (Wake-up Alarm)
#define PROX_RIGHT 12    // PD4 (Detects Right Traffic)
#define PROX_LEFT 13     // PD5 (Detects Left Traffic)
#define BUTTON_PIN 14    // PD6 (Takeover Button)

enum SystemState { SYSTEM_OFF, FULL_MANUAL, ADAS_MONITORING, AUTO_DRIVING, AWAIT_STOPPED, AWAIT_RUNNING };
SystemState currentState = SYSTEM_OFF;

char driverEyeStatus = 'O'; 
int currentSpeed = 0;       
int currentSteering = 90;   
bool guiTakeover = false;   

Servo steeringServo;

void setup() {
  Serial.begin(9600);
  pinMode(MOTOR_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(PROX_CENTER, INPUT); 
  pinMode(PROX_LEFT, INPUT); 
  pinMode(PROX_RIGHT, INPUT); 
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  steeringServo.attach(SERVO_PIN);
  steeringServo.write(90); 
}

// 🔥 CRITICAL FIX: The Soft-Start Function
// Ramps up speed gradually to prevent ATmega32A from crashing due to power spikes
void softStartMotor(int targetSpeed) {
  if (currentSpeed >= targetSpeed) return; // Already going fast enough
  
  for (int i = currentSpeed; i <= targetSpeed; i += 5) {
    analogWrite(MOTOR_PIN, i);
    delay(15); // 15ms delay * 30 steps = ~450ms smooth acceleration
  }
  currentSpeed = targetSpeed;
}

void loop() {
  // 1. Process GUI Commands
  while (Serial.available() > 0) {
    char incoming = Serial.read();
    
    if (incoming == 'O' || incoming == 'C') driverEyeStatus = incoming;
    else if (incoming == 'P') {
      if (currentState == SYSTEM_OFF) {
        currentState = ADAS_MONITORING;
        softStartMotor(150); // 🔥 Smoothly start the engine
      } else {
        currentState = SYSTEM_OFF;
        currentSpeed = 0;
        analogWrite(MOTOR_PIN, 0);
      }
    }
    else if (incoming == 'M') {
      if (currentState == FULL_MANUAL) {
        currentState = ADAS_MONITORING; 
        softStartMotor(150); // 🔥 Smoothly return to Auto speed
      } else {
        currentState = FULL_MANUAL;
      }
    }
    else if (incoming == '+') { currentSpeed += 50; if (currentSpeed > 255) currentSpeed = 255; } 
    else if (incoming == '-') { currentSpeed -= 50; if (currentSpeed < 0) currentSpeed = 0; }     
    else if (incoming == 'B') currentSpeed = 0; 
    else if (incoming == '<') currentSteering = 45;      
    else if (incoming == '>') currentSteering = 135;     
    else if (incoming == '^') currentSteering = 90;      
    else if (incoming == 'T') guiTakeover = true;        
  }

  // Read Sensors 
  bool centerClear = (digitalRead(PROX_CENTER) == HIGH); 
  bool leftClear = (digitalRead(PROX_LEFT) == HIGH); 
  bool rightClear = (digitalRead(PROX_RIGHT) == HIGH); 
  
  bool physicalButtonPressed = (digitalRead(BUTTON_PIN) == LOW); 
  bool triggerTakeover = physicalButtonPressed || guiTakeover;
  guiTakeover = false; 

  // ==========================================
  // AUTONOMOUS STATE MACHINE
  // ==========================================
  
  if (currentState == SYSTEM_OFF) {
    analogWrite(MOTOR_PIN, 0);
    digitalWrite(BUZZER_PIN, LOW);
    steeringServo.write(90);
  }
  else if (currentState == FULL_MANUAL) {
    analogWrite(MOTOR_PIN, currentSpeed); 
    digitalWrite(BUZZER_PIN, LOW);
    steeringServo.write(currentSteering);
  }
  else if (currentState == ADAS_MONITORING) {
    if (driverEyeStatus == 'C') {
      currentState = AUTO_DRIVING; // Driver asleep! AI Takes control.
    } else {
      analogWrite(MOTOR_PIN, currentSpeed);
      digitalWrite(BUZZER_PIN, LOW);
      steeringServo.write(currentSteering);
    }
  } 
  else if (currentState == AUTO_DRIVING) {
    if (driverEyeStatus == 'O') {
      if (centerClear) currentState = AWAIT_RUNNING;
      else currentState = AWAIT_STOPPED; 
    } else {
      
      // 1. SPEED CONTROL (Center Sensor)
      if (centerClear) {
        softStartMotor(150); // 🔥 Smooth acceleration if path clears
        digitalWrite(BUZZER_PIN, HIGH); 
      } else {
        currentSpeed = 0;
        analogWrite(MOTOR_PIN, 0);  // Obstacle ahead! Emergency Stop.
        digitalWrite(BUZZER_PIN, HIGH); 
      }

      // 2. EVASIVE STEERING (Left/Right Sensors)
      if (!leftClear && rightClear) {
        steeringServo.write(135); // Traffic left, steer right
      } else if (!rightClear && leftClear) {
        steeringServo.write(45);  // Traffic right, steer left
      } else {
        steeringServo.write(90);  // Keep straight
      }
    }
  } 
  else if (currentState == AWAIT_STOPPED) {
    currentSpeed = 0;
    analogWrite(MOTOR_PIN, 0); 
    digitalWrite(BUZZER_PIN, LOW);
    if (triggerTakeover) currentState = ADAS_MONITORING; 
  }
  else if (currentState == AWAIT_RUNNING) {
    steeringServo.write(90);
    softStartMotor(150); // 🔥 Keep driving safely
    digitalWrite(BUZZER_PIN, LOW);
    if (triggerTakeover) currentState = ADAS_MONITORING; 
  }

  // Send Telemetry
  Serial.print("STATE:");
  if (currentState == SYSTEM_OFF) Serial.print("OFF");
  else if (currentState == FULL_MANUAL) Serial.print("FULL_MANUAL");
  else if (currentState == ADAS_MONITORING) Serial.print("ADAS_ACTIVE");
  else if (currentState == AUTO_DRIVING) Serial.print("AI_TAKEOVER");
  else if (currentState == AWAIT_STOPPED) Serial.print("AWAIT_STOPPED");
  else if (currentState == AWAIT_RUNNING) Serial.print("AWAIT_RUNNING");

  Serial.print(",PROX_C:"); Serial.print(centerClear ? "CLEAR" : "OBST");
  Serial.print(",PROX_L:"); Serial.print(leftClear ? "CLEAR" : "OBST");
  Serial.print(",PROX_R:"); Serial.print(rightClear ? "CLEAR" : "OBST");

  Serial.print(",SPEED:"); Serial.print(currentSpeed);

  Serial.print(",STEER:");
  int actualSteer = steeringServo.read();
  if (actualSteer < 80) Serial.println("LEFT");
  else if (actualSteer > 100) Serial.println("RIGHT");
  else Serial.println("CENTER");

  delay(50); 
}
