"""Quick action differentiation test."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from rl_env.metrobus_env import MetrobusEnv

names = ["SLOW ", "NORM ", "FAST ", "HOLD "]
for a in range(4):
    env = MetrobusEnv(
        direction="gidis", vehicle_count=15,
        use_fixed_dwell=True, fixed_dwell_seconds=15.0,
        max_stops=15,
    )
    obs, _ = env.reset(seed=42)
    total_r = 0
    for step in range(500):
        actions = np.full(15, a, dtype=np.int64)
        obs, r, _, _, info = env.step(actions)
        total_r += r
    q = sum(1 for v in env.vehicles if v.is_queuing)
    print(
        f"{names[a]} r={total_r:+.1f}"
        f" spd={info['avg_speed_kmh']:.1f}"
        f" gap={info['min_gap_m']:.0f}"
        f" bunch={info['episode_bunching']}"
        f" q={q}"
    )
