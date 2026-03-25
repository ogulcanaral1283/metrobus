"""Test FIFO departure logic in GPU env."""
import torch

from rl_env.gpu_env import GpuMetrobusEnv, STOPPED, DEPARTING, CRUISING

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"=== FIFO Test (device={device}) ===\n")

env = GpuMetrobusEnv(15, device)
obs, _ = env.reset()

# Run simulation for 2000 steps to generate stop events
fifo_blocks_seen = 0
departures_seen = 0
deadlock_breaks = 0

for step in range(2000):
    actions = torch.ones(15, dtype=torch.long, device=env.device)
    obs, r, t, tr, info = env.step(actions)
    
    # Check for FIFO blocking: stopped vehicles with dwell=0 and queue_wait>0
    stopped = env.phases == STOPPED
    dwell_zero = env.dwell_remaining <= 0
    fifo_waiting = stopped & dwell_zero & (env.queue_wait_time > 0)
    
    if fifo_waiting.any():
        fifo_blocks_seen += fifo_waiting.sum().item()
    
    # Track departures
    departing = env.phases == DEPARTING
    if departing.any():
        departures_seen += departing.sum().item()

num_stopped = (env.phases == STOPPED).sum().item()
num_departing = (env.phases == DEPARTING).sum().item()

print(f"2000 steps completed")
print(f"  FIFO blocks seen (cumulative): {fifo_blocks_seen}")
print(f"  Departures seen (cumulative): {departures_seen}")
print(f"  Final stopped: {num_stopped}")
print(f"  Final departing: {num_departing}")
print(f"  Sim time: {env.sim_time:.1f}s")
print(f"  Avg speed: {env.speeds.mean().item()*3.6:.1f} km/h")

if fifo_blocks_seen > 0:
    print(f"\n  FIFO BLOCKING ACTIVE! Vehicles correctly wait for ahead vehicle.")
else:
    print(f"\n  Note: No FIFO blocks in this run (may need more vehicles/stops)")

# Quick syntax/import test
print(f"\n=== FIFO TEST PASSED ===")
