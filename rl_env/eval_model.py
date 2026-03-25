"""
Eval — Egitilmis modeli test et, WS bridge ile dashboard'da izle.

Kullanim:
  python -m rl_env.eval_model
"""

from __future__ import annotations

import time
import torch

from .gpu_env import GpuMetrobusEnv, OBS_DIM, NUM_ACTIONS
from .agents.networks import Actor
from .ws_bridge import TrainingBridge

PHASE_NAMES = {0: "CR", 1: "AP", 2: "QU", 3: "DK", 4: "ST", 5: "DC", 6: "BL", 7: "DP"}


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Environment
    env = GpuMetrobusEnv(vehicle_count=80, device=str(device), num_envs=1)
    obs, _ = env.reset(seed=123)
    print(f"Env: {env.N} arac, {env.num_stops} durak, {env.route_length:.0f}m")

    # Model yukle
    actor = Actor(OBS_DIM, NUM_ACTIONS, hidden_dim=64).to(device)
    ckpt = torch.load("checkpoints/best_actor.pt", map_location=device, weights_only=True)
    actor.load_state_dict(ckpt)
    actor.eval()
    print("Model yuklendi: best_actor.pt")

    # WS Bridge
    bridge = TrainingBridge(direction="gidis", port=8765, broadcast_every=1)
    bridge.start()
    print("WS Bridge basladi - Dashboard'da 'Egitim Izleme' butonuna tikla!")
    time.sleep(2)

    total_steps = 10_000
    total_reward = 0.0
    episode_count = 0

    for step in range(total_steps):
        with torch.no_grad():
            flat_obs = obs.reshape(-1, OBS_DIM)
            dist = actor(flat_obs)
            actions = dist.probs.argmax(dim=-1).reshape(1, env.N)

        obs, reward, term, trunc, _ = env.step(actions)
        total_reward += reward[0].item()

        info = env._get_info(0)
        bridge.update(
            env, step=step, reward=reward[0].item(), info=info,
            iteration=step, total_reward=total_reward,
            actions=actions[0].cpu().tolist(),
        )

        if step % 1000 == 0:
            phases = env.phases[0].cpu().tolist()
            pc = {}
            for p in phases:
                name = PHASE_NAMES.get(p, str(p))
                pc[name] = pc.get(name, 0) + 1
            sim_t = env.sim_time[0].item()
            spd = info["avg_speed_kmh"]
            stopped = info["num_stopped"]
            rew = reward[0].item()
            print(
                f"Step {step:5d} | sim={sim_t:.0f}s | "
                f"reward={rew:+.3f} | spd={spd:.1f}km/h | "
                f"stopped={stopped} | {pc}"
            )

        if (term[0] | trunc[0]).item():
            episode_count += 1
            print(f"  >> Episode {episode_count} bitti (step {step})")
            obs, _ = env.reset()

    avg_rew = total_reward / total_steps
    print("\n" + "=" * 60)
    print("EVAL TAMAMLANDI")
    print(f"  Total reward: {total_reward:.2f}")
    print(f"  Avg reward/step: {avg_rew:.4f}")
    print(f"  Episodes: {episode_count}")
    print("=" * 60)

    bridge.stop()


if __name__ == "__main__":
    main()
