"""Integration test: GPU env + WS Bridge + train.py imports."""
import torch
import time
import sys

print("=== Integration Test: GPU Env + WS Bridge ===\n")

# 1. Import chain
print("1. Import chain...")
from rl_env.gpu_env import GpuMetrobusEnv, OBS_DIM, NUM_ACTIONS
from rl_env.agents.networks import Actor, Critic
from rl_env.ws_bridge import TrainingBridge
print(f"   OK | OBS_DIM={OBS_DIM}, NUM_ACTIONS={NUM_ACTIONS}")

# 2. GPU env
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"\n2. GPU env (device={device})...")
env = GpuMetrobusEnv(15, device)
obs, info = env.reset()
print(f"   OK | obs={obs.shape} on {obs.device}")

# 3. Actor/Critic
print("\n3. Actor/Critic...")
actor = Actor(OBS_DIM, NUM_ACTIONS, 64).to(device)
critic = Critic(OBS_DIM * 15, 128).to(device)
print(f"   OK | Actor params={sum(p.numel() for p in actor.parameters())}")

# 4. WS Bridge (GPU mode)
print("\n4. WS Bridge (GPU tensor mode)...")
bridge = TrainingBridge(direction="gidis", port=8765, broadcast_every=3)
# Test GPU state extraction WITHOUT starting server
bridge._extract_gpu_state(env)
print("   OK | _extract_gpu_state works with GPU tensors")

# 5. Simulate rollout (3 steps)
print("\n5. Simulated rollout (3 steps on GPU)...")
for step in range(3):
    with torch.no_grad():
        dist = actor(obs)
        actions = dist.sample()
    
    obs, reward, term, trunc, info = env.step(actions)
    
    # Simulate bridge update
    bridge.update(env, step=step, reward=reward, info=info)

print(f"   OK | final reward={reward:.4f}, obs still on {obs.device}")
print(f"   sim_time={env.sim_time:.2f}s")

# 6. Bridge server start/stop
print("\n6. WS Bridge server start/stop...")
bridge.start()
time.sleep(0.5)
bridge.stop()
print("   OK | Server started and stopped cleanly")

print("\n=== ALL INTEGRATION TESTS PASSED ===")
print(f"\nSistem egitim icin HAZIR.")
print(f"  Dashboard: http://localhost:3000")
print(f"  WS Bridge: ws://localhost:8765")
print(f"  GPU: {torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'}")
