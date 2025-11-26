import numpy as np

ANGLE_DEG = 45.0
COS_TH = np.cos(np.deg2rad(ANGLE_DEG))
SAMPLE_INTERVAL = 0.005
MIN_STRENGTH = 35
MIN_DEC_SEQ = 3
MAX_BURST_TIME = 0.25
MIN_CHANGE = 0.5
SPEED_RANGE = (0.1, 60.0)

test_readings = car_50_km = [
    (2.5700,80),(0.7100,80),(0.2400,80),(0.2300,80),(0.2400,80),(0.2600,80),(0.2600,80),(0.2800,80),(0.2900,80),(0.3100,80),(0.4400,80),(0.4800,80)
]

timestamps = np.arange(len(test_readings)) * SAMPLE_INTERVAL

def fit_line(t, r):
    t = np.array(t) - np.mean(t)
    r = np.array(r)
    m, b = np.polyfit(t, r, 1)
    err = np.sqrt(np.mean((r - (m*t + b))**2))
    return m, err

state = "idle"
buffer_t, buffer_r = [], []
dec_streak = 0
last_r = None
t0 = 0
printed_once = False

for i, (t, (r, s)) in enumerate(zip(timestamps, test_readings)):
    if s < MIN_STRENGTH or r <= 0:
        state = "idle"; buffer_t.clear(); buffer_r.clear()
        dec_streak = 0; last_r = None
        continue

    if last_r is not None and r < last_r:
        dec_streak += 1
    else:
        dec_streak = 0
    last_r = r

    if state == "idle" and dec_streak >= MIN_DEC_SEQ:
        state="burst"; t0 = t
        buffer_t = [t]; buffer_r = [r]
        printed_once = False
        continue

    if state == "burst":
        buffer_t.append(t); buffer_r.append(r)
        elapsed = t - t0
        should_stop = False
        if len(buffer_r) >= 6:
            recent = buffer_r[-6:]
            if (recent[0] - recent[-1]) < MIN_CHANGE:
                should_stop = True
        if elapsed >= MAX_BURST_TIME:
            should_stop = True
        if should_stop and not printed_once:
            if len(buffer_r) >= 6:
                slope, err = fit_line(buffer_t, buffer_r)
                radial_speed = abs(slope)
                true_speed = radial_speed / COS_TH
                if SPEED_RANGE[0] <= true_speed <= SPEED_RANGE[1]:
                    print(f"Detected speed: {true_speed*3.6:.1f} km/h "
                          f"(fit error {err*100:.1f} cm)")
            printed_once = True
            state = "idle"; buffer_t.clear(); buffer_r.clear()
            dec_streak = 0; last_r = None

if state == "burst" and len(buffer_r) >= 6 and not printed_once:
    slope, err = fit_line(buffer_t, buffer_r)
    radial_speed = abs(slope)
    true_speed = radial_speed / COS_TH
    if SPEED_RANGE[0] <= true_speed <= SPEED_RANGE[1]:
        print(f"Detected speed: {true_speed*3.6:.1f} km/h (fit error {err*100:.1f} cm)")
