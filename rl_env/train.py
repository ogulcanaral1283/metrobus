"""
MAPPO Egitim Dongusu
Rehber Asama 4.4: Tam egitim akisi.

Kullam:
  cd metrobus/rl_env
  python train.py
  python train.py --config config/hyperparams.yaml
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import yaml

try:
    from .gpu_env import GpuMetrobusEnv, OBS_DIM, NUM_ACTIONS
    from .metrobus_env import MetrobusEnv  # fallback for CPU eval
    from .agents.networks import Actor, Critic
    from .agents.buffer import RolloutBuffer, compute_gae, prepare_batch
    from .ws_bridge import TrainingBridge
except ImportError:
    from gpu_env import GpuMetrobusEnv, OBS_DIM, NUM_ACTIONS
    from metrobus_env import MetrobusEnv
    from agents.networks import Actor, Critic
    from agents.buffer import RolloutBuffer, compute_gae, prepare_batch
    from ws_bridge import TrainingBridge


def load_config(config_path: str = "config/hyperparams.yaml") -> dict:
    """YAML config dosyasini yukle."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_device(use_cuda: bool = True) -> torch.device:
    """GPU varsa kullan."""
    if use_cuda and torch.cuda.is_available():
        device = torch.device("cuda")
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = torch.device("cpu")
        print("CPU kullaniliyor")
    return device


def collect_rollout(
    env: GpuMetrobusEnv,
    actor: Actor,
    critic: Critic,
    buffer: RolloutBuffer,
    num_steps: int,
    device: torch.device,
    obs: torch.Tensor,
    bridge: TrainingBridge | None = None,
    iteration: int = 0,
) -> torch.Tensor:
    """
    Vectorized GPU rollout — B paralel ortam, TÜM env'lerin verisi kullanılır.
    T = num_steps // B → 32x daha az Python loop iterasyonu.
    Buffer: T × B entry = num_steps entry.
    """
    actor.eval()
    critic.eval()

    B = obs.shape[0]      # num_envs (32)
    N = obs.shape[1]      # num_agents (80)
    obs_dim = obs.shape[2]
    global_dim = N * obs_dim

    # T = toplam adım / env sayısı → 4096/32 = 128 step
    T = max(num_steps // B, 1)

    # GPU'da pre-allocate — (T, B, ...) şeklinde TÜM env'lerin verisi
    all_obs = torch.zeros(T, B, N, obs_dim, device=device)
    all_global_obs = torch.zeros(T, B, global_dim, device=device)
    all_actions = torch.zeros(T, B, N, dtype=torch.long, device=device)
    all_log_probs = torch.zeros(T, B, N, device=device)
    all_rewards = torch.zeros(T, B, device=device)
    all_values = torch.zeros(T, B, device=device)
    all_dones = torch.zeros(T, B, dtype=torch.bool, device=device)

    use_graph = hasattr(env, '_graph_captured') and env._graph_captured

    with torch.no_grad():
        for t in range(T):
            # Actor: tüm B×N ajanı tek forward pass
            flat_obs = obs.reshape(B * N, obs_dim)
            dist = actor(flat_obs)
            flat_actions = dist.sample()
            flat_log_probs = dist.log_prob(flat_actions)
            actions_bn = flat_actions.reshape(B, N)
            log_probs_bn = flat_log_probs.reshape(B, N)

            # Critic: TÜM env'ler paralel forward
            global_obs_b = obs.reshape(B, global_dim)
            values_b = critic(global_obs_b).squeeze(-1)

            # Kaydet — SIFIR GPU sync
            all_obs[t].copy_(obs)
            all_global_obs[t].copy_(global_obs_b)
            all_actions[t].copy_(actions_bn)
            all_log_probs[t].copy_(log_probs_bn)
            all_values[t].copy_(values_b)

            # Env step — CUDA Graph replay
            if use_graph:
                next_obs, rewards_b, terms_b, truncs_b, _ = env.graph_step(actions_bn)
            else:
                next_obs, rewards_b, terms_b, truncs_b, _ = env.step(actions_bn)

            all_rewards[t].copy_(rewards_b)
            all_dones[t].copy_(terms_b | truncs_b)

            obs = next_obs

            # WS Bridge — her 16 step'te güncelle (donma önleme)
            if bridge and t % 16 == 0:
                info = env._get_info(env_idx=0)
                # Son aksiyonları gönder (env[0] için)
                last_actions = actions_bn[0].cpu().tolist() if actions_bn.dim() == 2 else None
                bridge.update(
                    env, step=t, reward=rewards_b.mean().item(), info=info,
                    iteration=iteration,
                    total_reward=all_rewards[:t+1].sum().item(),
                    actions=last_actions,
                )

    # ─── TOPLU CPU TRANSFER: (T, B, ...) → flatten to T*B entries ───
    # Reshape: (T, B, ...) → (T*B, ...)
    TB = T * B
    obs_flat = all_obs.reshape(TB, N, obs_dim).cpu().numpy()
    global_flat = all_global_obs.reshape(TB, global_dim).cpu().numpy()
    act_flat = all_actions.reshape(TB, N).cpu().numpy()
    lp_flat = all_log_probs.reshape(TB, N).cpu().numpy()
    rew_flat = all_rewards.reshape(TB).cpu().numpy()
    val_flat = all_values.reshape(TB).cpu().numpy()
    done_flat = all_dones.reshape(TB).cpu().numpy()

    for i in range(TB):
        buffer.store(
            obs_flat[i], global_flat[i], act_flat[i],
            lp_flat[i].astype(np.float32),
            float(rew_flat[i]), float(val_flat[i]), bool(done_flat[i]),
        )

    actor.train()
    critic.train()
    return obs


def ppo_update(
    actor: Actor,
    critic: Critic,
    actor_optimizer: torch.optim.Optimizer,
    critic_optimizer: torch.optim.Optimizer,
    buffer: RolloutBuffer,
    config: dict,
    device: torch.device,
) -> dict:
    """
    PPO guncelleme adimi.
    Rehber Asama 4.3.

    Returns:
        Kayip degerleri dict
    """
    gamma = config["gamma"]
    lam = config["gae_lambda"]
    epsilon = config["epsilon"]
    epochs = config["epochs"]
    mini_batch_size = config["mini_batch_size"]
    entropy_coef = config["entropy_coef"]
    value_coef = config["value_coef"]
    max_grad_norm = config["max_grad_norm"]

    # GAE hesapla
    # Son degerim icin critic'ten tahmin al
    with torch.no_grad():
        last_obs = buffer.observations[-1]
        last_global = torch.tensor(
            last_obs.flatten(), dtype=torch.float32, device=device
        ).unsqueeze(0)
        last_value = critic(last_global).item()

    advantages, returns = compute_gae(
        buffer.rewards, buffer.values, buffer.dones, gamma, lam, last_value
    )

    # Advantage normalize
    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    # Batch hazirla
    batch = prepare_batch(buffer, advantages, returns, device)

    T = len(buffer)
    num_agents = batch["obs"].shape[1]

    total_policy_loss = 0.0
    total_value_loss = 0.0
    total_entropy = 0.0
    total_actor_gn = 0.0
    total_critic_gn = 0.0
    update_count = 0

    for epoch in range(epochs):
        # Mini-batch indeksleri
        indices = np.random.permutation(T)

        for start in range(0, T, mini_batch_size):
            end = min(start + mini_batch_size, T)
            mb_idx = indices[start:end]
            mb_size = len(mb_idx)

            mb_obs = batch["obs"][mb_idx]           # (mb, agents, obs_dim)
            mb_global = batch["global_obs"][mb_idx]  # (mb, global_dim)
            mb_actions = batch["actions"][mb_idx]     # (mb, agents)
            mb_old_log_probs = batch["log_probs"][mb_idx]  # (mb, agents)
            mb_advantages = batch["advantages"][mb_idx]    # (mb,)
            mb_returns = batch["returns"][mb_idx]           # (mb,)

            # --- Actor guncelleme ---
            # Tum ajanlari TEK forward pass ile isle (parameter sharing)
            # (mb, agents, obs_dim) -> (mb * agents, obs_dim) -> tek forward
            flat_obs = mb_obs.reshape(-1, mb_obs.shape[-1])       # (mb*agents, obs_dim)
            flat_actions = mb_actions.reshape(-1)                  # (mb*agents,)
            flat_log_probs, flat_entropy = actor.evaluate(flat_obs, flat_actions)

            # (mb*agents,) -> (mb, agents)
            new_log_probs = flat_log_probs.reshape(mb_size, num_agents)
            entropy = flat_entropy.reshape(mb_size, num_agents).mean()

            # Oran hesapla
            old_log_probs_sum = mb_old_log_probs.sum(dim=1)  # (mb,)
            new_log_probs_sum = new_log_probs.sum(dim=1)     # (mb,)
            ratio = torch.exp(new_log_probs_sum - old_log_probs_sum)

            # PPO kirpma
            surr1 = ratio * mb_advantages
            surr2 = torch.clamp(ratio, 1 - epsilon, 1 + epsilon) * mb_advantages
            policy_loss = -torch.min(surr1, surr2).mean()

            # Entropy bonusu
            entropy_loss = -entropy_coef * entropy

            # Actor toplam kayip
            actor_loss = policy_loss + entropy_loss

            actor_optimizer.zero_grad()
            actor_loss.backward()
            actor_gn = nn.utils.clip_grad_norm_(actor.parameters(), max_grad_norm)
            actor_optimizer.step()

            # --- Critic guncelleme ---
            values = critic(mb_global)
            value_loss = value_coef * ((values - mb_returns) ** 2).mean()

            critic_optimizer.zero_grad()
            value_loss.backward()
            critic_gn = nn.utils.clip_grad_norm_(critic.parameters(), max_grad_norm)
            critic_optimizer.step()

            total_policy_loss += policy_loss.item()
            total_value_loss += value_loss.item()
            total_entropy += entropy.item()
            total_actor_gn += actor_gn.item()
            total_critic_gn += critic_gn.item()
            update_count += 1

    uc = max(update_count, 1)
    return {
        "policy_loss": total_policy_loss / uc,
        "value_loss": total_value_loss / uc,
        "entropy": total_entropy / uc,
        "actor_grad_norm": total_actor_gn / uc,
        "critic_grad_norm": total_critic_gn / uc,
    }


def train(config: dict):
    """
    Ana egitim fonksiyonu.
    Rehber Asama 4.4.
    """
    device = get_device(config.get("use_cuda", True))

    # --- Dizinler ---
    checkpoint_dir = Path(config.get("checkpoint_dir", "checkpoints"))
    log_dir = Path(config.get("log_dir", "logs"))
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # --- Environment (Vectorized GPU-native) ---
    num_buses = config["num_buses"]
    num_envs = config.get("num_envs", 32)
    env = GpuMetrobusEnv(
        vehicle_count=num_buses,
        device=str(device),
        direction=config.get("direction", "gidis"),
        max_stops=config.get("max_stops", 0),
        num_envs=num_envs,
        reward_config={
            "headway_weight": config.get("headway_weight", 1.0),
            "bunching_penalty": config.get("bunching_penalty", 0.5),
            "dwell_penalty": config.get("long_dwell_penalty", 0.1),
            "speed_weight": config.get("speed_bonus_weight", 0.3),
            "target_speed_kmh": config.get("target_speed_kmh", 40),
        },
    )

    obs_dim = config.get("obs_dim", OBS_DIM)
    action_dim = config.get("action_dim", NUM_ACTIONS)
    global_obs_dim = obs_dim * num_buses

    # obs_dim dogrulama — config ile env uyumlu mu?
    if obs_dim != OBS_DIM:
        print(f"UYARI: Config obs_dim={obs_dim} != GPU env OBS_DIM={OBS_DIM}!")
        print(f"  GPU env her zaman {OBS_DIM} boyutlu obs uretiyor.")
        print(f"  obs_dim={OBS_DIM} olarak duzeltildi.")
        obs_dim = OBS_DIM
        global_obs_dim = obs_dim * num_buses

    # --- Aglar ---
    actor = Actor(obs_dim, action_dim, config.get("actor_hidden", 64)).to(device)
    critic = Critic(global_obs_dim, config.get("critic_hidden", 128)).to(device)

    # --- Warmstart: Phase 1 -> Phase 2 curriculum transfer ---
    warmstart_path = config.get("warmstart_checkpoint", "")
    if warmstart_path and os.path.exists(warmstart_path):
        print(f"Warmstart: {warmstart_path} yukleniyor...")
        actor_state = torch.load(warmstart_path, map_location=device, weights_only=True)
        actor.load_state_dict(actor_state)
        print(f"  Actor yuklendi ✓")

        # Critic icin de ayni dizinde arayin
        critic_path = warmstart_path.replace("best_actor.pt", "best_critic.pt")
        if not os.path.exists(critic_path):
            critic_path = warmstart_path.replace("actor", "critic")
        if os.path.exists(critic_path):
            critic_state = torch.load(critic_path, map_location=device, weights_only=True)
            # Critic boyut degismisse (farkli num_buses) yukleme atlanir
            try:
                critic.load_state_dict(critic_state)
                print(f"  Critic yuklendi ✓")
            except RuntimeError as e:
                print(f"  Critic boyut uyumsuzlugu, sifirdan baslatiliyor: {e}")
        print(f"  Warmstart tamamlandi.")
    elif warmstart_path:
        print(f"UYARI: Warmstart dosyasi bulunamadi: {warmstart_path}")

    actor_optimizer = torch.optim.Adam(actor.parameters(), lr=config["learning_rate"])
    critic_optimizer = torch.optim.Adam(critic.parameters(), lr=config["learning_rate"])

    # Cosine LR decay
    total_iterations = config["total_iterations"]
    actor_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        actor_optimizer, T_max=total_iterations, eta_min=config["learning_rate"] * 0.1
    )
    critic_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        critic_optimizer, T_max=total_iterations, eta_min=config["learning_rate"] * 0.1
    )

    # --- TensorBoard ---
    try:
        from torch.utils.tensorboard import SummaryWriter
        writer = SummaryWriter(log_dir=str(log_dir))
        use_tb = True
        print(f"TensorBoard: {log_dir}")
    except ImportError:
        writer = None
        use_tb = False
        print("TensorBoard bulunamadi, loglama devre disi")

    # --- Egitim ---
    total_iterations = config["total_iterations"]
    batch_size = config["batch_size"]
    checkpoint_interval = config.get("checkpoint_interval", 50)
    eval_interval = config.get("eval_interval", 100)
    log_interval = config.get("log_interval", 10)

    obs, _ = env.reset()
    best_reward = -float("inf")
    reward_history = []

    # --- CUDA Graph capture (in-place .copy_() ile uyumlu) ---
    print("CUDA Graph: capture başlıyor...")
    env.capture_graph()

    print(f"\nEgitim basliyor: {total_iterations} iterasyon")
    print(f"  Arac sayisi: {num_buses}")
    print(f"  Obs dim: {obs_dim}, Action dim: {action_dim}")
    print(f"  Global obs dim: {global_obs_dim}")
    print(f"  Batch size: {batch_size}")
    print(f"  Device: {device}")
    print("=" * 60)

    # --- WebSocket Bridge ---
    bridge: TrainingBridge | None = None
    if config.get("ws_bridge", True):
        bridge = TrainingBridge(
            direction=config.get("direction", "gidis"),
            port=config.get("ws_port", 8765),
            broadcast_every=config.get("ws_broadcast_every", 10),
        )
        bridge.start()

    start_time = time.time()

    for iteration in range(1, total_iterations + 1):
        # 1. Veri topla (rollout)
        buffer = RolloutBuffer()
        obs = collect_rollout(
            env, actor, critic, buffer, batch_size, device, obs,
            bridge=bridge, iteration=iteration,
        )

        # 2. PPO guncelleme
        losses = ppo_update(
            actor, critic, actor_optimizer, critic_optimizer,
            buffer, config, device,
        )

        # LR schedular step
        actor_scheduler.step()
        critic_scheduler.step()

        # 3. Istatistikler
        reward_arr = np.array(buffer.rewards)
        avg_reward = float(np.mean(reward_arr))
        reward_std = float(np.std(reward_arr))
        reward_min = float(np.min(reward_arr))
        reward_max = float(np.max(reward_arr))
        reward_history.append(avg_reward)

        # 4. Loglama
        if iteration % log_interval == 0:
            elapsed = time.time() - start_time
            fps = (iteration * batch_size) / elapsed

            print(
                f"Iter {iteration:5d}/{total_iterations} | "
                f"reward={avg_reward:+.4f} ({reward_min:+.2f}/{reward_max:+.2f}) | "
                f"p_loss={losses['policy_loss']:.4f} | "
                f"v_loss={losses['value_loss']:.4f} | "
                f"entropy={losses['entropy']:.4f} | "
                f"fps={fps:.0f}"
            )

            if use_tb and writer:
                writer.add_scalar("reward/mean", avg_reward, iteration)
                writer.add_scalar("reward/std", reward_std, iteration)
                writer.add_scalar("reward/min", reward_min, iteration)
                writer.add_scalar("reward/max", reward_max, iteration)
                writer.add_scalar("loss/policy", losses["policy_loss"], iteration)
                writer.add_scalar("loss/value", losses["value_loss"], iteration)
                writer.add_scalar("loss/entropy", losses["entropy"], iteration)
                writer.add_scalar("perf/fps", fps, iteration)
                writer.add_scalar("lr/actor", actor_scheduler.get_last_lr()[0], iteration)

                # Gradient norm logging
                if "actor_grad_norm" in losses:
                    writer.add_scalar("grad/actor_norm", losses["actor_grad_norm"], iteration)
                    writer.add_scalar("grad/critic_norm", losses["critic_grad_norm"], iteration)

                # Action distribution logging
                all_actions = np.concatenate(buffer.actions)  # (steps * agents,)
                for a_idx in range(config.get("action_dim", 4)):
                    freq = float(np.mean(all_actions == a_idx))
                    writer.add_scalar(f"actions/action_{a_idx}_freq", freq, iteration)

        # 5. Checkpoint
        if iteration % checkpoint_interval == 0:
            torch.save(actor.state_dict(), checkpoint_dir / f"actor_iter_{iteration}.pt")
            torch.save(critic.state_dict(), checkpoint_dir / f"critic_iter_{iteration}.pt")

            if avg_reward > best_reward:
                best_reward = avg_reward
                torch.save(actor.state_dict(), checkpoint_dir / "best_actor.pt")
                torch.save(critic.state_dict(), checkpoint_dir / "best_critic.pt")
                print(f"  >> Yeni en iyi model kaydedildi! reward={best_reward:.4f}")

        # 6. Degerlendirme
        if eval_interval > 0 and iteration % eval_interval == 0:
            eval_reward, eval_metrics = evaluate(env, actor, device, num_episodes=3)
            print(f"  >> Eval reward: {eval_reward:.4f} | speed={eval_metrics['avg_speed_kmh']:.1f}km/h | bunching={eval_metrics['bunching_count']:.0f}")
            if use_tb and writer:
                writer.add_scalar("eval/reward", eval_reward, iteration)
                writer.add_scalar("eval/avg_speed_kmh", eval_metrics["avg_speed_kmh"], iteration)
                writer.add_scalar("eval/headway_cv", eval_metrics["headway_cv"], iteration)
                writer.add_scalar("eval/bunching_count", eval_metrics["bunching_count"], iteration)
                writer.add_scalar("eval/min_gap", eval_metrics["min_gap"], iteration)

    # --- Egitim bitti ---
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Egitim tamamlandi! Sure: {elapsed:.0f}sn ({elapsed/3600:.1f} saat)")
    print(f"En iyi reward: {best_reward:.4f}")
    print(f"Son checkpoint: {checkpoint_dir}")

    # Son modeli kaydet
    torch.save(actor.state_dict(), checkpoint_dir / "final_actor.pt")
    torch.save(critic.state_dict(), checkpoint_dir / "final_critic.pt")

    if use_tb and writer:
        writer.close()


def evaluate(
    env: GpuMetrobusEnv,
    actor: Actor,
    device: torch.device,
    num_episodes: int = 3,
) -> tuple:
    """Policy'yi deterministik olarak degerlendir (GPU-native, batched).
    Returns: (avg_reward, metrics_dict)
    """
    actor.eval()
    total_rewards = []
    all_speeds = []
    all_headway_cv = []
    all_bunching = []
    all_min_gap = []

    for _ in range(num_episodes):
        obs, _ = env.reset()
        episode_reward = 0.0
        done = False
        last_info = {}

        while not done:
            with torch.no_grad():
                # VecEnv: obs (B, N, obs_dim) → actor needs (B*N, obs_dim)
                if obs.dim() == 3:
                    flat_obs = obs.reshape(-1, obs.shape[-1])
                    dist = actor(flat_obs)
                    actions = dist.probs.argmax(dim=-1).reshape(obs.shape[0], obs.shape[1])
                else:
                    dist = actor(obs)
                    actions = dist.probs.argmax(dim=-1)

            obs, reward, terminated, truncated, info = env.step(actions)

            # VecEnv: tensors (B,) → env[0] scalar
            if isinstance(reward, torch.Tensor) and reward.dim() > 0:
                episode_reward += reward[0].item()
                done = (terminated[0] | truncated[0]).item()
            else:
                episode_reward += reward
                done = terminated or truncated
            last_info = info

        total_rewards.append(episode_reward)
        all_speeds.append(last_info.get("avg_speed_kmh", 0))

        rc = last_info.get("reward_components", {})
        all_headway_cv.append(rc.get("headway_cv", 0))
        all_bunching.append(rc.get("bunching_count", 0))
        all_min_gap.append(rc.get("min_gap", 0))

    actor.train()

    metrics = {
        "avg_speed_kmh": float(np.mean(all_speeds)),
        "headway_cv": float(np.mean(all_headway_cv)),
        "bunching_count": float(np.mean(all_bunching)),
        "min_gap": float(np.mean(all_min_gap)),
    }
    return float(np.mean(total_rewards)), metrics


def main():
    parser = argparse.ArgumentParser(description="Metrobus MAPPO Egitim")
    parser.add_argument(
        "--config", type=str, default="config/hyperparams.yaml",
        help="Hiperparametre config dosyasi",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    train(config)


if __name__ == "__main__":
    main()
