"""
MAPPO Actor/Critic Sinir Aglari
Rehber Asama 3: Parameter sharing ile multi-agent MAPPO.

Actor: obs(22) -> action_probs(4)
Critic: global_obs(22*N) -> value(1)
"""

from __future__ import annotations

import torch
import torch.nn as nn
from torch.distributions import Categorical


class Actor(nn.Module):
    """
    Karar veren ag.
    Bir aracin gozlemini alir, aksiyon olasilikalarini dondurur.
    Parameter sharing: tum araclar ayni actor'u kullanir.
    LayerNorm ile stabil ogrenme.
    """

    def __init__(self, obs_dim: int = 22, action_dim: int = 4, hidden_dim: int = 128):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim),
        )

    def forward(self, obs: torch.Tensor) -> Categorical:
        """obs: (..., obs_dim) -> Categorical distribution."""
        logits = self.network(obs)
        return Categorical(logits=logits)

    def get_action(self, obs: torch.Tensor):
        """
        Gozlemden aksiyon ornekle.
        Returns: (action, log_prob)
        """
        dist = self.forward(obs)
        action = dist.sample()
        log_prob = dist.log_prob(action)
        return action, log_prob

    def evaluate(self, obs: torch.Tensor, action: torch.Tensor):
        """
        Onceki aksiyon icin log_prob ve entropy hesapla.
        PPO guncelleme adiminda kullanilir.
        """
        dist = self.forward(obs)
        log_prob = dist.log_prob(action)
        entropy = dist.entropy()
        return log_prob, entropy


class Critic(nn.Module):
    """
    Deger tahmini yapan ag.
    Global gozlemi alir (tum araclarin gozlemleri birlestik),
    tek bir deger dondurur.

    CTDE: Centralized Training, Decentralized Execution.
    Critic tum bilgiyi gorur, actor sadece kendi gozlemini.
    LayerNorm ile stabil ogrenme.
    """

    def __init__(self, global_obs_dim: int = 660, hidden_dim: int = 256):
        """
        Args:
            global_obs_dim: 22 * vehicle_count (varsayilan: 22 * 30 = 660)
            hidden_dim: Gizli katman boyutu
        """
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(global_obs_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, global_obs: torch.Tensor) -> torch.Tensor:
        """global_obs: (batch, global_obs_dim) -> (batch,)."""
        return self.network(global_obs).squeeze(-1)
