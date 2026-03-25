"""Benchmark: 80 vehicles on GPU as specified in implementation plan."""
import torch
import time

from rl_env.gpu_env import GpuMetrobusEnv

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}")
print(f"GPU: {torch.cuda.get_device_name(0)}" if device == "cuda" else "CPU mode")

for n_vehicles in [15, 30, 60, 80]:
    env = GpuMetrobusEnv(n_vehicles, device)
    obs, _ = env.reset()
    actions = torch.ones(n_vehicles, dtype=torch.long, device=env.device)

    # Warmup
    for _ in range(100):
        env.step(actions)

    # Benchmark
    N = 5000
    torch.cuda.synchronize() if device == "cuda" else None
    t0 = time.time()
    for _ in range(N):
        obs, r, t_, tr, i_ = env.step(actions)
    torch.cuda.synchronize() if device == "cuda" else None
    elapsed = time.time() - t0
    fps = N / elapsed

    print(f"  {n_vehicles:3d} vehicles | {fps:7.0f} steps/sec | {elapsed:.3f}s for {N} steps")

print("\nDone!")
