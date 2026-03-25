"""
Metrobus Eğitilmiş Policy Canlı Demo
=====================================
Eğitilmiş actor modelini yükleyip dashboard'da canlı simülasyon çalıştırır.
80 otobüs eğitilmiş policy ile hareket eder.

Kullanım:
    python live_demo.py
    → Dashboard: http://localhost:3000
"""

import torch
import time
import yaml
from pathlib import Path

from rl_env.gpu_env import GpuMetrobusEnv
from rl_env.agents.networks import Actor
from rl_env.ws_bridge import TrainingBridge


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Config yükle
    config_path = Path("rl_env/config/hyperparams.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    num_buses = config.get("num_vehicles", 80)
    obs_dim = config.get("obs_dim", 24)
    action_dim = config.get("action_dim", 4)

    # Tek env (görselleştirme için)
    print(f"Ortam oluşturuluyor: {num_buses} otobüs...")
    env = GpuMetrobusEnv(num_buses, device, max_stops=10, num_envs=1)
    obs, _ = env.reset()
    print(f"  obs shape: {obs.shape}")

    # Eğitilmiş Actor yükle
    actor = Actor(obs_dim=obs_dim, action_dim=action_dim, hidden_dim=64).to(device)
    checkpoint_path = Path("checkpoints/best_actor.pt")
    
    if not checkpoint_path.exists():
        print(f"HATA: {checkpoint_path} bulunamadı!")
        return
    
    state_dict = torch.load(checkpoint_path, map_location=device, weights_only=True)
    actor.load_state_dict(state_dict)
    actor.eval()
    print(f"  Model yüklendi: {checkpoint_path}")
    print(f"  Parametreler: {sum(p.numel() for p in actor.parameters()):,}")

    # WS Bridge
    bridge = TrainingBridge(direction="gidis", port=8765, broadcast_every=1)
    bridge.start()
    print("WS Bridge başlatıldı — Dashboard'u aç: http://localhost:3000")
    time.sleep(2)

    # Simülasyon döngüsü
    print("\n" + "=" * 60)
    print("CANLI SİMÜLASYON BAŞLADI")
    print("  80 otobüs × eğitilmiş policy")
    print("  Ctrl+C ile durdur")
    print("=" * 60)

    step = 0
    total_reward = 0.0
    episode_reward = 0.0
    episode_count = 0
    dt_sim = env.dt  # 0.1 saniye

    # Gerçek zamanlı hız kontrolü
    real_time_factor = 5.0  # 5x hız (0.1s sim = 0.02s gerçek)
    sleep_time = dt_sim / real_time_factor

    try:
        while True:
            with torch.no_grad():
                # obs: (1, 80, 24) → actor: (80, 24) → actions: (80,) → (1, 80)
                flat_obs = obs.reshape(-1, obs_dim)  # (80, 24)
                dist = actor(flat_obs)
                
                # Greedy (en iyi aksiyon) — eğitimden farklı: rastgele değil
                actions = dist.probs.argmax(dim=-1)  # (80,)
                actions_bn = actions.reshape(1, num_buses)  # (1, 80)

            # Step
            obs, reward, terminated, truncated, _ = env.step(actions_bn)
            
            r = reward[0].item()
            episode_reward += r
            total_reward += r
            step += 1

            # Aksiyon dağılımı
            action_counts = [(actions == i).sum().item() for i in range(action_dim)]

            # WS Bridge'e gönder
            info = env._get_info(env_idx=0)
            bridge.update(
                env, step=step, reward=r, info=info,
                iteration=episode_count,
                total_reward=episode_reward,
                actions=actions.cpu().tolist(),
            )

            # Episode bitti mi?
            done = (terminated[0] | truncated[0]).item()
            if done:
                episode_count += 1
                print(f"\n  Episode {episode_count} bitti | reward={episode_reward:.3f} | "
                      f"sim_time={env.sim_time[0].item():.0f}s")
                episode_reward = 0.0
                env.reset()
                obs = env._vectorized_obs()

            # Her 100 step bilgi
            if step % 100 == 0:
                sim_time = env.sim_time[0].item()
                avg_speed = env.speeds[0].mean().item() * 3.6  # m/s → km/h
                action_names = ["NORMAL", "SLOW", "FAST", "HOLD"]
                action_str = " | ".join(f"{action_names[i]}:{action_counts[i]}" for i in range(4))
                print(f"  Step {step:>6} | sim={sim_time:>6.1f}s | reward={r:+.3f} | "
                      f"speed={avg_speed:.1f}km/h | {action_str}")

            # Gerçek zamanlı hız
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\nSimülasyon durduruldu.")
        print(f"  Toplam step: {step}")
        print(f"  Episode sayısı: {episode_count}")
        print(f"  Ortalama reward: {total_reward / max(step, 1):.4f}")


if __name__ == "__main__":
    main()
