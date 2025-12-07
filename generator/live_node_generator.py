import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta
import signal
import threading
import sys

np.random.seed(42)

# -------------------------------
# CITY → NODE MAPPING
# -------------------------------
cities = {
    "Hyderabad": [
        {"cell_id": "HYD_C1", "lat": 17.3850, "lon": 78.4867},
        {"cell_id": "HYD_C2", "lat": 17.4500, "lon": 78.3800},
        {"cell_id": "HYD_C3", "lat": 17.3000, "lon": 78.5500},
    ],
    "Bangalore": [
        {"cell_id": "BLR_C1", "lat": 12.9716, "lon": 77.5946},
        {"cell_id": "BLR_C2", "lat": 13.0200, "lon": 77.6400},
        {"cell_id": "BLR_C3", "lat": 12.9000, "lon": 77.5000},
    ],
    "Chennai": [
        {"cell_id": "CHE_C1", "lat": 13.0827, "lon": 80.2707},
        {"cell_id": "CHE_C2", "lat": 13.1500, "lon": 80.3000},
        {"cell_id": "CHE_C3", "lat": 13.0000, "lon": 80.2000},
    ]
}

# ✅ ABSOLUTE SAFE DATA PATH
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

# -------------------------------
# FAILURE WINDOWS (DAILY)
# -------------------------------
PEAK_START = "18:00"
PEAK_END = "21:00"

BACKHAUL_FAILURE_NODE = "BLR_C2"
BACKHAUL_START = "11:15"
BACKHAUL_END = "11:45"

INTERFERENCE_NODE = "CHE_C3"
INTERFERENCE_START = "14:00"
INTERFERENCE_END = "16:00"


# -------------------------------
# TIME ALIGNMENT (FIXED)
# -------------------------------

# Cooperative stop event used by signal handler and loops
STOP_EVENT = threading.Event()

def _handle_sigint(signum, frame):
    print("\n⏹️ Shutdown requested (SIGINT). Stopping generator gracefully...")
    STOP_EVENT.set()

# Register SIGINT handler (Ctrl+C)
signal.signal(signal.SIGINT, _handle_sigint)


def align_to_next_minute():
    now = datetime.now()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    sleep_seconds = (next_minute - now).total_seconds()
    print(f"⏳ Aligning start to {next_minute.strftime('%H:%M:%S')} ... (press Ctrl+C to cancel)")
    # Sleep in small increments so we can abort quickly on SIGINT
    interval = 0.5
    end_time = time.time() + sleep_seconds
    while time.time() < end_time:
        if STOP_EVENT.is_set():
            print("Alignment aborted due to shutdown request.")
            return False
        time.sleep(min(interval, end_time - time.time()))
    return True


def in_time_range(now, start, end):
    t = now.strftime("%H:%M")
    return start <= t <= end


# -------------------------------
# METRIC GENERATION
# -------------------------------

def generate_metrics(cell_id):
    throughput = np.random.normal(160, 12)
    latency = np.random.normal(22, 4)
    packet_loss = np.random.normal(0.25, 0.07)
    rsrp = np.random.normal(-85, 4)
    users = np.random.randint(40, 110)

    now = datetime.now()

    # (A) PEAK CONGESTION
    if in_time_range(now, PEAK_START, PEAK_END):
        users += 80
        latency += 60
        throughput -= 70
        packet_loss += 1.2

    # (B) BACKHAUL FAILURE
    if cell_id == BACKHAUL_FAILURE_NODE and in_time_range(now, BACKHAUL_START, BACKHAUL_END):
        throughput = 10
        latency = 250
        packet_loss = 4.5

    # (C) RF INTERFERENCE
    if cell_id == INTERFERENCE_NODE and in_time_range(now, INTERFERENCE_START, INTERFERENCE_END):
        rsrp -= 15
        latency += 40
        throughput -= 50

    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "throughput_mbps": round(max(throughput, 5), 2),
        "latency_ms": round(max(latency, 5), 2),
        "packet_loss_pct": round(max(packet_loss, 0), 3),
        "rsrp_dbm": round(rsrp, 1),
        "users_connected": int(users)
    }


# -------------------------------
# CSV WRITER (AUTO CREATION SAFE)
# -------------------------------

def write_to_csv(city, cell):
    folder = os.path.join(BASE_DIR, city)
    os.makedirs(folder, exist_ok=True)  # ✅ auto-create city folders

    filepath = os.path.join(folder, f"{cell['cell_id']}.csv")

    metrics = generate_metrics(cell["cell_id"])

    row = {
        "timestamp": metrics["timestamp"],
        "city": city,
        "cell_id": cell["cell_id"],
        "latitude": cell["lat"],
        "longitude": cell["lon"],
        **metrics
    }

    df = pd.DataFrame([row])

    file_exists = os.path.exists(filepath)

    df.to_csv(filepath, mode="a", header=not file_exists, index=False)

    if not file_exists:
        print(f"📁 Created new file: {filepath}")


# -------------------------------
# ✅ MAIN REAL-TIME LOOP (30s)
# -------------------------------

print("✅ Live 5G Node Generators Booting...")

# ✅ FORCE START AT CLEAN TIME (11:13:00 STYLE)
if not align_to_next_minute():
    sys.exit(0)

print("✅ Live data generation started...")

try:
    while not STOP_EVENT.is_set():
        start_cycle = datetime.now()

        for city, cells in cities.items():
            for cell in cells:
                # stop quickly if requested
                if STOP_EVENT.is_set():
                    break
                write_to_csv(city, cell)
            if STOP_EVENT.is_set():
                break

        # ✅ EXACT 30-SECOND INTERVAL MAINTAINED
        elapsed = (datetime.now() - start_cycle).total_seconds()
        sleep_time = max(0, 30 - elapsed)
        # sleep in short slices to remain responsive to shutdown
        end_time = time.time() + sleep_time
        while time.time() < end_time and not STOP_EVENT.is_set():
            time.sleep(min(0.5, end_time - time.time()))
except KeyboardInterrupt:
    # Fallback if something triggers KeyboardInterrupt directly
    print("\n⏹️ Shutdown requested (KeyboardInterrupt). Stopping generator...")
    STOP_EVENT.set()

print("✅ Generator stopped. Goodbye.")
