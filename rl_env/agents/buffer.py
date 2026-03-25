"""
Rollout Buffer + GAE (Generalized Advantage Estimation)
Rehber Asama 4.1 & 4.2: Deneyim deposu ve avantaj hesabi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import torch


@dataclass
class RolloutBuffer:
    """
    PPO/MAPPO icin deneyim deposu.
    Simülasyondan toplanan verileri saklar.

    Veri yapisi:
      Her adim icin:
        observations:   (num_agents, obs_dim) per-agent gozlemler
        global_states:  (num_agents * obs_dim,) birlestik gozlem (critic icin)
        actions:        (num_agents,) per-agent aksiyonlar
        log_probs:      (num_agents,) per-agent log olasiliklari
        rewards:        scalar global reward
        values:         scalar critic tahmini
        dones:          bool episode bitti mi
    """

    observations: List[np.ndarray] = field(default_factory=list)
    global_states: List[np.ndarray] = field(default_factory=list)
    actions: List[np.ndarray] = field(default_factory=list)
    log_probs: List[np.ndarray] = field(default_factory=list)
    rewards: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    dones: List[bool] = field(default_factory=list)

    def store(
        self,
        obs: np.ndarray,
        global_state: np.ndarray,
        action: np.ndarray,
        log_prob: np.ndarray,
        reward: float,
        value: float,
        done: bool,
    ) -> None:
        """Bir adimin verisini depola."""
        self.observations.append(obs.copy())
        self.global_states.append(global_state.copy())
        self.actions.append(action.copy())
        self.log_probs.append(log_prob.copy())
        self.rewards.append(reward)
        self.values.append(value)
        self.dones.append(done)

    def clear(self) -> None:
        """Buffer'i temizle."""
        self.observations.clear()
        self.global_states.clear()
        self.actions.clear()
        self.log_probs.clear()
        self.rewards.clear()
        self.values.clear()
        self.dones.clear()

    def __len__(self) -> int:
        return len(self.rewards)


def compute_gae(
    rewards: List[float],
    values: List[float],
    dones: List[bool],
    gamma: float = 0.99,
    lam: float = 0.95,
    last_value: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generalized Advantage Estimation (GAE).
    Rehber Asama 4.2.

    A_t = delta_t + (gamma * lam) * delta_{t+1} + ...
    delta_t = r_t + gamma * V(s_{t+1}) - V(s_t)

    Args:
        rewards:    Her adimin odulu
        values:     Critic'in her adim icin tahmini
        dones:      Episode bitis bayraklari
        gamma:      Indirim faktoru (0.99)
        lam:        GAE lambda (0.95)
        last_value: Son durumun degeri (truncated ise critic tahmini)

    Returns:
        advantages: (T,) avantaj degerleri
        returns:    (T,) hedef deger degerleri (advantages + values)
    """
    num_steps = len(rewards)
    advantages = np.zeros(num_steps, dtype=np.float32)
    gae = 0.0

    for t in reversed(range(num_steps)):
        if t == num_steps - 1:
            next_value = last_value
            next_non_terminal = 1.0 - float(dones[t])
        else:
            next_value = values[t + 1]
            next_non_terminal = 1.0 - float(dones[t])

        delta = rewards[t] + gamma * next_value * next_non_terminal - values[t]
        gae = delta + gamma * lam * next_non_terminal * gae
        advantages[t] = gae

    returns = advantages + np.array(values, dtype=np.float32)
    return advantages, returns


def prepare_batch(
    buffer: RolloutBuffer,
    advantages: np.ndarray,
    returns: np.ndarray,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """
    Buffer verisini PyTorch tensor'larina cevir.
    Mini-batch bolme icin hazirla.

    Returns dict:
        obs:         (T, num_agents, obs_dim)
        global_obs:  (T, global_obs_dim)
        actions:     (T, num_agents)
        log_probs:   (T, num_agents)
        advantages:  (T,)
        returns:     (T,)
    """
    return {
        "obs": torch.tensor(
            np.array(buffer.observations), dtype=torch.float32, device=device
        ),
        "global_obs": torch.tensor(
            np.array(buffer.global_states), dtype=torch.float32, device=device
        ),
        "actions": torch.tensor(
            np.array(buffer.actions), dtype=torch.long, device=device
        ),
        "log_probs": torch.tensor(
            np.array(buffer.log_probs), dtype=torch.float32, device=device
        ),
        "advantages": torch.tensor(advantages, dtype=torch.float32, device=device),
        "returns": torch.tensor(returns, dtype=torch.float32, device=device),
    }
