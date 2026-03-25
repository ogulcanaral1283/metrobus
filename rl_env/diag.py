"""Quick diagnostic of best trained model."""
import torch
import numpy as np
try:
    from .metrobus_env import MetrobusEnv
    from .agents.networks import Actor
except ImportError:
    import sys
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from metrobus_env import MetrobusEnv
    from agents.networks import Actor

import os

# En iyi modeli yukle
actor = Actor(14, 4, 64)
ckpt_path = os.path.join(os.path.dirname(__file__), "..", "checkpoints", "phase1", "best_actor.pt")
actor.load_state_dict(torch.load(ckpt_path, map_location="cpu", weights_only=True))
actor.eval()

# 500 adim test
env = MetrobusEnv(direction="gidis", vehicle_count=10, use_fixed_dwell=True, fixed_dwell_seconds=15.0)
obs, _ = env.reset()

rewards = []
action_counts = {0: 0, 1: 0, 2: 0, 3: 0}

for step in range(500):
    obs_t = torch.tensor(obs, dtype=torch.float32)
    with torch.no_grad():
        dist = actor(obs_t)
        actions = dist.probs.argmax(dim=-1).numpy()

    for a in actions:
        action_counts[int(a)] += 1

    obs, reward, term, trunc, info = env.step(actions)
    rewards.append(reward)

    if term or trunc:
        obs, _ = env.reset()

print("=== BEST MODEL DIAGNOSTIC (500 adim) ===")
print(f"Ort. reward/step: {np.mean(rewards):.4f}")
print(f"Min reward/step:  {np.min(rewards):.4f}")
print(f"Max reward/step:  {np.max(rewards):.4f}")
print(f"Std reward/step:  {np.std(rewards):.4f}")
print()
print("Aksiyon dagilimi:")
total = sum(action_counts.values())
labels = {0: "NORMAL", 1: "SKIP_STOP", 2: "HOLDING", 3: "SPEED_UP"}
for k, v in action_counts.items():
    pct = 100 * v / total
    print(f"  {labels[k]:12s}: {v:5d} ({pct:.1f}%)")
print()
avg_spd = info["avg_speed_kmh"]
min_g = info["min_gap_m"]
bunch = info["episode_bunching"]
print(f"Son info: speed={avg_spd:.1f}km/h, min_gap={min_g:.0f}m, bunching={bunch}")
