import cv2
import serial
import time
import threading
import math
import mediapipe as mp
from flask import Flask, Response, render_template_string, jsonify, request

COM_PORT = "COM3" 
BAUD_RATE = 9600
EAR_THRESHOLD = 0.22  
camera_source = 0 # Using laptop webcam

app = Flask(__name__)

global_state = {
    "eye_status": "AI OFFLINE", "eye_measurement": "--", "mcu_connected": False,
    "steering": "CENTER", "speed": "0",
    "prox_c": "CLEAR", "prox_l": "CLEAR", "prox_r": "CLEAR", 
    "mode": "OFF", "pending_gui_cmd": None 
}

latest_frame = None
raw_frame = None  
frame_lock = threading.Lock()

LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ADAS Responsive Cockpit</title>
    <style>
        :root { --bg: #0b0c10; --panel: #1f2833; --accent: #45a29e; --text: #c5c6c7; --danger: #ef4444; --success: #22c55e; --warning: #f59e0b; }
        body { background-color: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 0; display: flex; flex-direction: column; height: 100vh; overflow-x: hidden; user-select: none; }
        
        .windshield { position: relative; width: 100%; height: 45vh; background: #000; border-bottom: 4px solid var(--accent); display: flex; justify-content: center; align-items: center; overflow: hidden; }
        .windshield img { width: 100%; height: 100%; object-fit: contain; }
        
        .hud-container { position: absolute; bottom: 10px; display: flex; gap: 5px; }
        .hud-zone { background: rgba(0, 0, 0, 0.7); padding: 5px 15px; border-radius: 10px; border: 2px solid var(--success); color: var(--success); font-weight: bold; font-size: 1rem; text-align: center; text-shadow: 0 0 5px black; }
        .hud-zone.danger { border-color: var(--danger); color: var(--danger); background: rgba(239, 68, 68, 0.2); }

        .master-controls { display: flex; gap: 10px; padding: 10px; background: #111; }
        .btn-master { flex: 1; padding: 15px; font-size: 1.2rem; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; color: white; text-transform: uppercase; transition: 0.2s;}
        .btn-power { background: #333; }
        .btn-power.on { background: var(--success); box-shadow: 0 0 10px var(--success); }
        .btn-manual { background: #333; }
        .btn-manual.on { background: var(--warning); color: black; box-shadow: 0 0 10px var(--warning); }

        .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 10px; padding: 10px; flex: 1; background: var(--bg); overflow-y: auto; }
        .panel { background: var(--panel); border-radius: 10px; padding: 15px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid #333; }
        .panel h3 { margin: 0 0 10px 0; color: var(--accent); font-size: 1rem; letter-spacing: 1px; }
        .val-display { font-size: 2rem; font-family: monospace; font-weight: bold; margin-bottom: 5px; }

        .steer-row { display: flex; gap: 5px; width: 100%; }
        .btn-steer { flex: 1; background: #333; color: white; border: none; padding: 15px 0; border-radius: 5px; font-size: 1.2rem; cursor: pointer; }
        .btn-steer:active { background: var(--accent); }

        .pedal-row { display: flex; gap: 10px; width: 100%; height: 80px; }
        .pedal { flex: 1; border: none; border-radius: 8px; font-size: 1.5rem; font-weight: bold; color: white; cursor: pointer; box-shadow: 0 5px 0 #111; transition: 0.1s; }
        .pedal:active { transform: translateY(5px); box-shadow: 0 0 0 #111; }
        .pedal-brake { background: linear-gradient(#555, #7f1d1d); border-bottom: 5px solid var(--danger); }
        .pedal-gas { background: linear-gradient(#555, #14532d); border-bottom: 5px solid var(--success); }
        
        .status-good { color: var(--success); }
        .status-bad { color: var(--danger); }
        .status-warn { color: var(--warning); }
        
        .takeover-alert { background: rgba(245, 158, 11, 0.9); color: black; padding: 15px; border-radius: 8px; font-weight: bold; text-align: center; margin: 10px; cursor: pointer; display: none; font-size: 1.1rem; }
    </style>
</head>
<body>

    <div class="windshield">
        <img src="{{ url_for('video_feed') }}" alt="Camera Feed">
        <div class="hud-container">
            <div class="hud-zone" id="rad-l">LEFT: CLR</div>
            <div class="hud-zone" id="rad-c" style="font-size:1.2rem;">CTR: CLR</div>
            <div class="hud-zone" id="rad-r">RIGHT: CLR</div>
        </div>
    </div>

    <div class="takeover-alert" id="takeover-alert" onclick="sendCmd('T')">
        ⚠ DRIVER AWAKE: PRESS HERE TO RESUME CONTROL
    </div>

    <div class="master-controls">
        <button class="btn-master btn-power" id="btn-pwr" onclick="sendCmd('P')">▶ START SYSTEM</button>
        <button class="btn-master btn-manual" id="btn-man" onclick="sendCmd('M')">FULLY MANUAL</button>
    </div>

    <div class="dashboard">
        <div class="panel">
            <h3>DRIVER AI STATUS</h3>
            <div class="val-display" id="eye-state">...</div>
            <div>EAR: <span id="ear-val" style="color:var(--accent);">0.00</span></div>
            <div id="mcu-state" style="margin-top:10px; font-size:0.8rem;">MCU OFFLINE</div>
        </div>

        <div class="panel">
            <h3>STEERING WHEEL</h3>
            <div class="val-display" id="steer-val" style="color:var(--text);">CENTER</div>
            <div class="steer-row">
                <button class="btn-steer" onclick="sendCmd('<')">◀ LEFT</button>
                <button class="btn-steer" onclick="sendCmd('^')">CENTER</button>
                <button class="btn-steer" onclick="sendCmd('>')">RIGHT ▶</button>
            </div>
        </div>

        <div class="panel">
            <h3>DC MOTOR (WHEELS)</h3>
            <div class="val-display" id="speed-val">PWM: 0</div>
            <div class="pedal-row">
                <button class="pedal pedal-brake" onclick="sendCmd('B')">BRAKE</button>
                <button class="pedal pedal-gas" onclick="sendCmd('+')">GAS</button>
            </div>
        </div>
    </div>

    <script>
        function sendCmd(c) { 
            fetch('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cmd: c }) }); 
        }
        
        setInterval(() => {
            fetch('/api/status').then(r => r.json()).then(d => {
                
                const eyeEl = document.getElementById('eye-state');
                eyeEl.innerText = d.eye_status;
                if(d.eye_status === 'EYES CLOSED') eyeEl.className = "val-display status-bad";
                else if(d.eye_status === 'AI DISABLED') eyeEl.className = "val-display status-warn";
                else eyeEl.className = "val-display status-good";
                
                document.getElementById('ear-val').innerText = d.eye_measurement;
                
                const mcuEl = document.getElementById('mcu-state');
                mcuEl.innerText = d.mcu_connected ? "✅ MCU LINKED" : "❌ MCU OFFLINE";
                mcuEl.style.color = d.mcu_connected ? "var(--success)" : "var(--danger)";

                const radL = document.getElementById('rad-l');
                const radC = document.getElementById('rad-c');
                const radR = document.getElementById('rad-r');
                
                radL.innerText = "L: " + d.prox_l;
                radL.className = "hud-zone " + (d.prox_l === "OBST" ? "danger" : "");
                
                radC.innerText = "C: " + d.prox_c;
                radC.className = "hud-zone " + (d.prox_c === "OBST" ? "danger" : "");
                
                radR.innerText = "R: " + d.prox_r;
                radR.className = "hud-zone " + (d.prox_r === "OBST" ? "danger" : "");

                document.getElementById('speed-val').innerText = "PWM: " + d.speed;
                document.getElementById('steer-val').innerText = d.steering;

                const pwrBtn = document.getElementById('btn-pwr');
                const manBtn = document.getElementById('btn-man');
                const alertBar = document.getElementById('takeover-alert');
                
                if(d.mode === "OFF") {
                    pwrBtn.className = "btn-master btn-power"; pwrBtn.innerText = "▶ START SYSTEM";
                    manBtn.className = "btn-master btn-manual"; manBtn.innerText = "FULLY MANUAL";
                    alertBar.style.display = "none";
                } else if(d.mode === "FULL_MANUAL") {
                    pwrBtn.className = "btn-master btn-power on"; pwrBtn.innerText = "SYSTEM RUNNING";
                    manBtn.className = "btn-master btn-manual on"; manBtn.innerText = "EXIT MANUAL (AUTO)"; 
                    alertBar.style.display = "none";
                } else {
                    pwrBtn.className = "btn-master btn-power on"; 
                    manBtn.className = "btn-master btn-manual"; manBtn.innerText = "GO MANUAL";
                    
                    if (d.mode === "ADAS_ACTIVE") pwrBtn.innerText = "ADAS: DRIVER CONTROLLING";
                    else if (d.mode === "AI_TAKEOVER") pwrBtn.innerText = "⚠ AI AUTOPILOT ACTIVE";
                    
                    if(d.mode === "AWAIT_STOPPED") {
                        alertBar.style.display = "block";
                        alertBar.innerText = "⚠ DRIVER AWAKE (TRAFFIC CLEARED) - PRESS TO START CAR MANUALLY";
                    } else if(d.mode === "AWAIT_RUNNING") {
                        alertBar.style.display = "block";
                        alertBar.innerText = "⚠ DRIVER AWAKE (CAR MOVING) - PRESS TO SHIFT TO MANUAL MODE";
                    } else {
                        alertBar.style.display = "none";
                    }
                }
            });
        }, 100);
    </script>
</body>
</html>
"""

def camera_capture_loop():
    global raw_frame
    cap = cv2.VideoCapture(camera_source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 
    while True:
        ret, frame = cap.read()
        if ret: raw_frame = cv2.resize(frame, (640, 480))
        else:
            time.sleep(0.5)
            cap.release()
            cap = cv2.VideoCapture(camera_source)

def ai_detection_loop():
    global latest_frame, global_state, raw_frame
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True)
    
    while True:
        if raw_frame is None: 
            time.sleep(0.05)
            continue
            
        frame = raw_frame.copy()

        if global_state["mode"] == "FULL_MANUAL" or global_state["mode"] == "OFF":
            global_state["eye_status"] = "AI DISABLED"
            global_state["eye_measurement"] = "--"
            cv2.putText(frame, "AI OFFLINE (MANUAL MODE)", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            with frame_lock: latest_frame = frame
            time.sleep(0.1) 
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = face_mesh.process(rgb)
        
        eyes_closed = False
        avg_ear = 0.0
        
        if res.multi_face_landmarks:
            for landmarks in res.multi_face_landmarks:
                pts = [(int(landmarks.landmark[i].x * 640), int(landmarks.landmark[i].y * 480)) for i in LEFT_EYE + RIGHT_EYE]
                for p in pts: cv2.circle(frame, p, 1, (0, 255, 0), -1)
                
                left_v = math.dist(pts[1], pts[5]) + math.dist(pts[2], pts[4])
                left_h = math.dist(pts[0], pts[3]) * 2
                left_ear = left_v / left_h if left_h > 0 else 0
                
                right_v = math.dist(pts[7], pts[11]) + math.dist(pts[8], pts[10])
                right_h = math.dist(pts[6], pts[9]) * 2
                right_ear = right_v / right_h if right_h > 0 else 0
                
                avg_ear = (left_ear + right_ear) / 2.0
                if avg_ear < EAR_THRESHOLD: eyes_closed = True

        global_state["eye_measurement"] = f"{avg_ear:.3f}"
        if eyes_closed:
            global_state["eye_status"] = "EYES CLOSED"
            cv2.putText(frame, "VISUAL: CLOSED", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        else:
            global_state["eye_status"] = "AWAKE"
            cv2.putText(frame, "VISUAL: AWAKE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        with frame_lock: latest_frame = frame

def mcu_serial_loop():
    global global_state
    ser = None
    last_status = None
    last_heartbeat = 0 # Track connection health
    
    while True:
        if ser is None:
            try:
                ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
                last_heartbeat = time.time() # Give 2 seconds to establish connection
            except: 
                global_state["mcu_connected"] = False
                time.sleep(1)
                continue
        try:
            curr = b'C' if global_state["eye_status"] == "EYES CLOSED" else b'O'
            if curr != last_status: 
                ser.write(curr)
                last_status = curr
            
            if global_state["pending_gui_cmd"]:
                ser.write(global_state["pending_gui_cmd"].encode())
                global_state["pending_gui_cmd"] = None
            
            if ser.in_waiting:
                line = ser.readline().decode(errors='ignore').strip()
                if "STATE:" in line:
                    last_heartbeat = time.time() # Data received, MCU is alive!
                    global_state["mcu_connected"] = True 
                    for p in line.split(','):
                        if ':' in p:
                            k, v = p.split(':')
                            if k == 'STATE': global_state['mode'] = v
                            elif k == 'PROX_C': global_state['prox_c'] = v
                            elif k == 'PROX_L': global_state['prox_l'] = v
                            elif k == 'PROX_R': global_state['prox_r'] = v
                            elif k == 'SPEED': global_state['speed'] = v
                            elif k == 'STEER': global_state['steering'] = v
            
            # If ATmega stops sending data for 2 seconds, declare it dead
            if time.time() - last_heartbeat > 2.0:
                global_state["mcu_connected"] = False

            time.sleep(0.02)
        except: 
            if ser: ser.close()
            ser = None
            global_state["mcu_connected"] = False

@app.route('/')
def index(): return render_template_string(HTML_PAGE)
@app.route('/api/status')
def status(): return jsonify(global_state)
@app.route('/api/control', methods=['POST'])
def control():
    global_state["pending_gui_cmd"] = request.json.get('cmd')
    return jsonify({"s": "ok"})
def gen():
    while True:
        with frame_lock:
            if latest_frame is None: 
                time.sleep(0.01)
                continue
            _, b = cv2.imencode('.jpg', latest_frame)
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + b.tobytes() + b'\r\n')
        time.sleep(0.03)
@app.route('/video_feed')
def video_feed(): return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    threading.Thread(target=camera_capture_loop, daemon=True).start()
    threading.Thread(target=ai_detection_loop, daemon=True).start()
    threading.Thread(target=mcu_serial_loop, daemon=True).start()
    print("\n[+] Final System Live! Open http://127.0.0.1:5000 \n")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
