"""
Egitilmis modeli ONNX'e cevir.
Rehber Asama 6.1: TypeScript tarafinda kullanmak icin.

Kullanim:
  cd metrobus/rl_env
  python scripts/export_onnx.py --checkpoint checkpoints/best_actor.pt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.networks import Actor


def export_to_onnx(
    checkpoint_path: str,
    output_path: str = "exports/actor_model.onnx",
    obs_dim: int = 14,
    action_dim: int = 4,
    hidden_dim: int = 64,
) -> None:
    """
    Actor modelini ONNX formatina cevir.

    ONNX modeli:
      Girdi:  observation (batch_size, 14) - tek aracin gozlemi
      Cikti:  action_logits (batch_size, 4) - aksiyon skorlari

    TS tarafinda kullanim:
      1. onnxruntime-web ile yukle
      2. Her arac icin gozlem vektorunu olustur (14 deger)
      3. Modele ver -> 4 logit
      4. argmax ile en iyi aksiyonu sec
      5. Uygula
    """
    # Modeli yukle
    actor = Actor(obs_dim, action_dim, hidden_dim)
    actor.load_state_dict(torch.load(checkpoint_path, map_location="cpu"))
    actor.eval()

    # Cikti dizini olustur
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ornek girdi
    dummy_input = torch.randn(1, obs_dim)

    # ONNX export — sadece network kismi (Categorical haric)
    torch.onnx.export(
        actor.network,
        dummy_input,
        output_path,
        input_names=["observation"],
        output_names=["action_logits"],
        dynamic_axes={
            "observation": {0: "batch_size"},
            "action_logits": {0: "batch_size"},
        },
        opset_version=13,
    )

    # Dogrulama
    try:
        import onnx
        model = onnx.load(output_path)
        onnx.checker.check_model(model)
        print(f"[OK] ONNX model dogrulandi: {output_path}")
    except ImportError:
        print(f"[OK] ONNX model kaydedildi: {output_path}")
        print("    (onnx paketi yuklu degil, dogrulama atlanidi)")

    # Boyut bilgisi
    file_size = os.path.getsize(output_path) / 1024
    print(f"    Dosya boyutu: {file_size:.1f} KB")

    # Ornek cikti
    with torch.no_grad():
        logits = actor.network(dummy_input)
        probs = torch.softmax(logits, dim=-1)
        print(f"    Ornek cikti (olasılıklar): {probs.numpy().round(3)}")


def main():
    parser = argparse.ArgumentParser(description="Actor modelini ONNX'e cevir")
    parser.add_argument(
        "--checkpoint", type=str, default="checkpoints/best_actor.pt",
        help="Actor checkpoint dosyasi",
    )
    parser.add_argument(
        "--output", type=str, default="exports/actor_model.onnx",
        help="ONNX cikti dosyasi",
    )
    parser.add_argument("--obs-dim", type=int, default=14)
    parser.add_argument("--action-dim", type=int, default=4)
    parser.add_argument("--hidden-dim", type=int, default=64)
    args = parser.parse_args()

    export_to_onnx(
        args.checkpoint, args.output,
        args.obs_dim, args.action_dim, args.hidden_dim,
    )


if __name__ == "__main__":
    main()
