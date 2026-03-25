"""Prove actions have different effects on environment."""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
try:
    from .metrobus_env import MetrobusEnv
except ImportError:
    import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from metrobus_env import MetrobusEnv

LABELS = {0: "SLOW(0.6x)", 1: "NORMAL(1.0x)", 2: "FAST(1.2x)", 3: "HOLD(30s)"}

for fixed_action in range(4):
    env = MetrobusEnv(direction="gidis", vehicle_count=30, use_fixed_dwell=True,
                      fixed_dwell_seconds=15.0, max_stops=15)
    obs, _ = env.reset()
    total_r = 0
    for step in range(500):
        actions = np.full(30, fixed_action, dtype=np.int64)
        obs, r, _, _, info = env.step(actions)
        total_r += r
    spd = info["avg_speed_kmh"]
    gap = info["min_gap_m"]
    bunch = info["episode_bunching"]
    print(f"  {LABELS[fixed_action]:14s}  reward={total_r:+8.2f}  speed={spd:5.1f}km/h  "
          f"min_gap={gap:.0f}m  bunching={bunch}")
