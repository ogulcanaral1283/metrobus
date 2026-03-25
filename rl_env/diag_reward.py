"""Step-by-step reward change diagnostic."""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
try:
    from .metrobus_env import MetrobusEnv
except ImportError:
    import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from metrobus_env import MetrobusEnv

env = MetrobusEnv(direction="gidis", vehicle_count=30, use_fixed_dwell=True,
                  fixed_dwell_seconds=15.0, max_stops=15)
obs, _ = env.reset()

# Fixed NORMAL actions to isolate: does reward change over time?
actions = np.ones(30, dtype=np.int64)  # all NORMAL

rewards = []
for step in range(5000):
    obs, r, _, _, info = env.step(actions)
    rewards.append(r)
    if step % 500 == 0:
        rc = info.get("reward_components", {})
        print(f"  Step {step:5d} | t={env.sim_time:.0f}s | reward={r:.4f} | "
              f"r_headway={rc.get('r_headway',0):.4f} | "
              f"r_bunching={rc.get('r_bunching',0):.4f} | "
              f"r_speed={rc.get('r_speed',0):.4f} | "
              f"speed={info.get('avg_speed_kmh',0):.1f}km/h | "
              f"min_gap={rc.get('min_gap',0):.0f}m")

rewards = np.array(rewards)
print(f"\n  Reward std:  {rewards.std():.6f}")
print(f"  Reward min:  {rewards.min():.4f}")
print(f"  Reward max:  {rewards.max():.4f}")
print(f"  Unique vals: {len(np.unique(np.round(rewards, 4)))}")
