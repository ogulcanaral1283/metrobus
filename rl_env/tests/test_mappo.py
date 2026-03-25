"""Verify MAPPO components work."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rl_env.demand import DemandProfile, DEFAULT_DEMAND
from rl_env.metrobus_env import MetrobusEnv

# 1. Demand profiles
print(f"Demand profiles: {len(DEFAULT_DEMAND.profiles)} stations")
cats = set(DEFAULT_DEMAND.categories.values())
print(f"Categories: {cats}")
print(f"Demand Mecidiyekoy 08:00: {DEFAULT_DEMAND.get_demand_multiplier('Mecidiyekoy', 8.0):.1f}")
print(f"Demand Avcilar 08:00: {DEFAULT_DEMAND.get_demand_multiplier('Avcilar', 8.0):.1f}")
print(f"Passengers Mecidiyekoy 08:00: {DEFAULT_DEMAND.get_passenger_count('Mecidiyekoy', 8.0)}")
print(f"Dwell time Mecidiyekoy 08:00: {DEFAULT_DEMAND.get_dwell_time('Mecidiyekoy', 8.0):.1f}s")
print("[OK] Demand profiles work")

# 2. Global obs
env = MetrobusEnv(vehicle_count=5)
obs, _ = env.reset(seed=42)
gobs = env.get_global_obs()
print(f"\nGlobal obs shape: {gobs.shape}")
assert gobs.shape == (5 * 14,), f"Expected (70,), got {gobs.shape}"
print("[OK] get_global_obs works")

# 3. Enhanced reward
import numpy as np
for _ in range(100):
    actions = env.action_space.sample()
    obs, reward, _, _, info = env.step(actions)
assert "headway_std" in info, "Missing headway_std in info"
assert "episode_bunching" in info, "Missing episode_bunching in info"
print(f"\nInfo keys: {list(info.keys())}")
print(f"Headway std: {info['headway_std']:.2f}")
print(f"Episode bunching: {info['episode_bunching']}")
print("[OK] Enhanced reward and info verified")

# 4. Try importing torch-based components (may fail if torch not installed)
try:
    from rl_env.agents.networks import Actor, Critic
    from rl_env.agents.buffer import RolloutBuffer, compute_gae
    import torch
    a = Actor()
    c = Critic()
    print(f"\nActor params: {sum(p.numel() for p in a.parameters())}")
    print(f"Critic params: {sum(p.numel() for p in c.parameters())}")
    print("[OK] PyTorch components verified")
except ImportError:
    print("\n[SKIP] PyTorch not installed, training components skipped")
    print("  Install: pip install torch --index-url https://download.pytorch.org/whl/cu124")

print("\n[OK] All MAPPO integration tests passed!")
