"""Diagnostic: 30 vehicles congestion test."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from rl_env.metrobus_env import MetrobusEnv

env = MetrobusEnv(direction="gidis", vehicle_count=30, max_stops=0)
obs, _ = env.reset()

for step in range(500):
    actions = np.array([env.np_random.integers(0, 4) for _ in range(30)])
    obs, reward, done, trunc, info = env.step(actions)
    
    if step % 50 == 0:
        phases = {}
        for v in env.vehicles:
            phases[v.phase] = phases.get(v.phase, 0) + 1
        avg_speed = np.mean([v.speed * 3.6 for v in env.vehicles])
        positions = sorted([v.position_meters for v in env.vehicles])
        gaps = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
        min_gap = min(gaps) if gaps else 0
        bunched = sum(1 for g in gaps if g < 200)
        print(f"Step {step:3d} | r={reward:.3f} | phases={phases}")
        print(f"  avg_speed={avg_speed:.1f} km/h | min_gap={min_gap:.0f}m | bunched_pairs={bunched}/29")
        print()
    
    if done or trunc:
        obs, _ = env.reset()
        print("--- RESET ---")
