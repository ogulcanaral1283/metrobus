"""
Analitik Controller Benchmark — Hızlı versiyon

Predictive Engine'i devre dışı bırakarak sadece GPU tensör
operasyonlarıyla 3 modu karşılaştırır:
  1. NO_CONTROL: Tüm araçlar Normal (müdahale yok)
  2. ANALYTIC: PID + Lookahead (deterministik matematik)
  3. RANDOM: Rastgele aksiyonlar (worst-case baseline)
"""

import time
import torch
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from gpu_env import GpuMetrobusEnv
from analytic_controller import create_controller_from_env


def run_single(mode: str, num_steps: int = 2000, num_envs: int = 4):
    device = "cuda" if torch.cuda.is_available() else "cpu"

    env = GpuMetrobusEnv(
        vehicle_count=200,
        num_envs=num_envs,
        max_stops=31,
        direction="gidis",
        device=device,
    )
    # Predictive Engine'i devre dışı bırak (çok yavaş)
    env._in_graph_mode = True

    obs, _ = env.reset()
    B, N = env.B, env.N

    controller = None
    if mode == "analytic":
        controller = create_controller_from_env(env)
        controller.reset(B, N)

    rewards = []
    bunching_list = []
    speed_list = []
    cv_list = []

    t0 = time.time()

    for step in range(num_steps):
        if mode == "no_control":
            actions = torch.ones(B, N, dtype=torch.long, device=device)
        elif mode == "random":
            actions = torch.randint(0, 4, (B, N), device=device)
        elif mode == "analytic":
            sf = controller.compute(
                positions=env.positions,
                speeds=env.speeds,
                phases=env.phases,
                next_stop_idx=env.next_stop_idx,
                dwell_remaining=env.dwell_remaining,
                is_queuing=env.is_queuing,
                dt=env.dt,
            )
            # Analitik controller speed_factor'ü doğrudan override eder
            env.speed_factor.copy_(sf)
            actions = torch.ones(B, N, dtype=torch.long, device=device)

        obs, reward, terminated, truncated, info = env.step(actions)
        rewards.append(reward.mean().item())

        # Her 200 step'te detaylı metrik
        if step % 200 == 0:
            with torch.no_grad():
                pos = env.positions[0]
                sp = env.speeds[0]
                sorted_pos = torch.sort(pos).values
                gaps = sorted_pos[1:] - sorted_pos[:-1] - 20.0
                gaps = torch.clamp(gaps, min=0)

                n_bunch = (gaps < 50.0).sum().item()
                bunching_list.append(n_bunch)

                valid = gaps[gaps > 5.0]
                if len(valid) > 2:
                    cv_list.append((valid.std() / (valid.mean() + 1e-6)).item())

                cruising = (env.phases[0] == 0) | (env.phases[0] == 1) | (env.phases[0] == 7)
                if cruising.sum() > 5:
                    speed_list.append(sp[cruising].mean().item() * 3.6)

            elapsed = time.time() - t0
            fps = (step + 1) * num_envs / elapsed
            print(f"  [{mode:>10}] Step {step:4d}/{num_steps} | "
                  f"r={reward.mean():+.3f} | "
                  f"bunch={n_bunch:3d} | "
                  f"spd={speed_list[-1] if speed_list else 0:.1f}km/h | "
                  f"fps={fps:.0f}")

    elapsed = time.time() - t0

    # İlk yarı vs son yarı reward trendi
    mid = len(rewards) // 2
    r_first = sum(rewards[:mid]) / max(mid, 1)
    r_last = sum(rewards[mid:]) / max(len(rewards) - mid, 1)

    return {
        "mode": mode,
        "avg_reward": sum(rewards) / len(rewards),
        "avg_bunching": sum(bunching_list) / max(len(bunching_list), 1),
        "avg_cv": sum(cv_list) / max(len(cv_list), 1),
        "avg_speed": sum(speed_list) / max(len(speed_list), 1),
        "reward_first_half": r_first,
        "reward_last_half": r_last,
        "fps": num_steps * num_envs / elapsed,
        "elapsed": elapsed,
    }


def main():
    print("🚌 Metrobüs — Analitik vs Kontrolsüz Benchmark")
    print("=" * 70)
    print(f"  GPU: {torch.cuda.get_device_name() if torch.cuda.is_available() else 'CPU'}")
    print(f"  200 araç × 31 durak × 2000 step × 4 env")
    print(f"  (Predictive Engine OFF — saf GPU tensör ops)")
    print()

    results = []
    for mode in ["no_control", "analytic", "random"]:
        try:
            r = run_single(mode, num_steps=2000, num_envs=4)
            results.append(r)
        except Exception as e:
            print(f"  ❌ {mode}: {e}")
            import traceback; traceback.print_exc()

    # ─── Sonuç Tablosu ───
    print("\n")
    print("=" * 70)
    print("📊 KARŞILAŞTIRMA SONUÇLARI")
    print("=" * 70)

    header = f"{'Metrik':<25}"
    for r in results:
        header += f"│ {r['mode'].upper():<18}"
    print(header)
    print("─" * 70)

    rows = [
        ("Ort. Reward/step", "avg_reward", ".4f"),
        ("Ort. Bunching (<50m)", "avg_bunching", ".1f"),
        ("Headway CV", "avg_cv", ".3f"),
        ("Ort. Hız (km/h)", "avg_speed", ".1f"),
        ("Reward (ilk yarı)", "reward_first_half", ".4f"),
        ("Reward (son yarı)", "reward_last_half", ".4f"),
        ("FPS", "fps", ".0f"),
    ]

    for label, key, fmt in rows:
        line = f"{label:<25}"
        for r in results:
            val = r.get(key, 0)
            formatted = f"{val:{fmt}}"
            line += f"│ {formatted:<18}"
        print(line)

    print("=" * 70)

    # En iyi
    best_r = max(results, key=lambda x: x["avg_reward"])
    best_b = min(results, key=lambda x: x["avg_bunching"])
    print(f"\n🏆 En yüksek reward: {best_r['mode'].upper()} ({best_r['avg_reward']:.4f})")
    print(f"🏆 En az bunching:   {best_b['mode'].upper()} ({best_b['avg_bunching']:.1f} çift)")


if __name__ == "__main__":
    main()
