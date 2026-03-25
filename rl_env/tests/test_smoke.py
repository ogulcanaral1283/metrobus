"""
Smoke test — MetrobusEnv'i rastgele aksiyonlarla calistir.
"""

import sys
import os
import numpy as np

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rl_env.metrobus_env import MetrobusEnv


def test_smoke():
    """1000 adim rastgele aksiyon ile calistir."""
    env = MetrobusEnv(direction="gidis", vehicle_count=10)
    obs, info = env.reset(seed=42)

    print(f"Route length: {env.route.total_length:.0f}m")
    print(f"Stop count: {len(env.route.stops)}")
    print(f"Observation shape: {obs.shape}")
    print(f"Action space: {env.action_space}")
    print()

    total_reward = 0.0
    n_steps = 1000

    for step_i in range(n_steps):
        actions = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(actions)

        total_reward += reward

        # Dogrulama
        assert obs.shape == (10, 24), f"Bad obs shape: {obs.shape}"
        assert np.all(np.isfinite(obs)), f"Non-finite obs at step {step_i}"
        assert np.isfinite(reward), f"Non-finite reward at step {step_i}"

        if step_i % 200 == 0:
            print(
                f"Step {step_i:4d} | "
                f"time={info['sim_time']:.1f}s | "
                f"avg_speed={info['avg_speed_kmh']:.1f}km/h | "
                f"min_gap={info['min_gap_m']:.0f}m | "
                f"stopped={info['num_stopped']} | "
                f"reward={reward:.4f}"
            )

        if terminated or truncated:
            print(f"Episode ended at step {step_i}")
            break

    print(f"\n[OK] Smoke test passed! {n_steps} steps, total reward: {total_reward:.2f}")


def test_reset_determinism():
    """Ayni seed ile reset, ayni gozlem uretmeli."""
    env = MetrobusEnv(direction="gidis", vehicle_count=5)
    obs1, _ = env.reset(seed=123)
    obs2, _ = env.reset(seed=123)
    assert np.allclose(obs1, obs2), "Reset determinism failed!"
    print("[OK] Reset determinism test passed!")


def test_both_directions():
    """Gidis ve donus yonleri calismali."""
    for direction in ["gidis", "donus"]:
        env = MetrobusEnv(direction=direction, vehicle_count=5)
        obs, info = env.reset(seed=42)
        print(f"  {direction}: route={env.route.total_length:.0f}m, stops={len(env.route.stops)}")

        for _ in range(100):
            actions = env.action_space.sample()
            obs, reward, _, _, _ = env.step(actions)
            assert np.all(np.isfinite(obs))

    print("[OK] Both directions test passed!")


def test_physics_idm():
    """IDM formulu basit dogrulama."""
    from rl_env.physics import compute_idm
    from rl_env.config import SimConfig

    config = SimConfig()

    # Serbest surusu: ondeki arac cok uzakta -> pozitif ivme
    accel = compute_idm(v=5.0, v0=14.0, s=1000.0, delta_v=0.0, config=config)
    assert accel > 0, f"Free flow should accelerate, got {accel}"

    # Yakin takip: kucuk gap -> negatif ivme (fren)
    accel = compute_idm(v=10.0, v0=14.0, s=5.0, delta_v=5.0, config=config)
    assert accel < 0, f"Close follow should brake, got {accel}"

    # Hedef hizda ve buyuk gap -> ivme ~0
    accel = compute_idm(v=12.5, v0=12.5, s=500.0, delta_v=0.0, config=config)
    assert abs(accel) < 0.5, f"At target speed, idle, got {accel}"

    print("[OK] IDM physics test passed!")


def test_route_length():
    """Hat uzunlugu TypeScript ile tutarli mi? (~50.5km gidis, ~50.7km donus)"""
    from rl_env.route_data import load_route

    route_g = load_route("gidis")
    route_d = load_route("donus")

    print(f"  Gidis: {route_g.total_length:.0f}m ({len(route_g.stops)} durak)")
    print(f"  Donus: {route_d.total_length:.0f}m ({len(route_d.stops)} durak)")

    # TypeScript'te ~50488m gidis, ~50727m donus
    assert abs(route_g.total_length - 50488) < 500, f"Gidis length mismatch: {route_g.total_length}"
    assert abs(route_d.total_length - 50727) < 500, f"Donus length mismatch: {route_d.total_length}"
    assert len(route_g.stops) == 44, f"Gidis stops: {len(route_g.stops)}"
    assert len(route_d.stops) == 43, f"Donus stops: {len(route_d.stops)}"

    print("[OK] Route length test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("MetrobusEnv Test Suite")
    print("=" * 60)

    print("\n--- Route Length Test ---")
    test_route_length()

    print("\n--- IDM Physics Test ---")
    test_physics_idm()

    print("\n--- Both Directions Test ---")
    test_both_directions()

    print("\n--- Reset Determinism Test ---")
    test_reset_determinism()

    print("\n--- Smoke Test ---")
    test_smoke()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
