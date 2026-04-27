# Akıllı Metrobüs Filo Yönetimi: MAPPO Tabanlı Çok-Ajanlı Pekiştirmeli Öğrenme Yaklaşımı

## Abstract

Bus bunching — the tendency of transit vehicles to cluster together and deviate from planned headways — represents one of the most persistent challenges in high-capacity Bus Rapid Transit (BRT) systems. Istanbul's Metrobus corridor, serving over 1 million daily passengers across 52 km with 44 stations, experiences severe bunching during peak hours, leading to dramatically uneven passenger loads, extended wait times, and cascading service degradation.

This paper presents a Multi-Agent Proximal Policy Optimization (MAPPO) framework for real-time, decentralized fleet speed management on the Istanbul Metrobus line. Each vehicle operates as an independent reinforcement learning agent that observes local traffic conditions — including gap distances, speeds, station queue states, and time-of-day features — and selects discrete speed modulation actions (SLOW, NORMAL, FAST, HOLD) to maintain uniform headways.

The system is built on a high-fidelity GPU-accelerated simulation environment that faithfully reproduces real-world Metrobus operations: route geometry derived from OpenStreetMap, Intelligent Driver Model (IDM) car-following physics, an 8-phase station Finite State Machine (FSM) with parallel platform docking, and stochastic demand perturbations. A Predictive Lookahead Decision Engine operates alongside MAPPO, analytically evaluating bunching risk through dual-scenario simulation (intervene vs. no-intervene) at each time step.

Training is performed on an NVIDIA RTX 5070 Ti GPU using CUDA Graph-captured vectorized environments (512 parallel instances × 200 vehicles), achieving approximately 20,000 simulation steps per second. A real-time WebSocket bridge streams training state to a Leaflet-based monitoring dashboard for live observation.

Preliminary results on a 31-station segment (Beylikdüzü–Halıcıoğlu, ~35 km) demonstrate the agent's ability to learn headway-regulating policies that significantly reduce bunching incidents compared to uncontrolled baselines. The trained policy is exportable as an ONNX model for browser-based or edge deployment.

**Keywords:** Multi-Agent Reinforcement Learning, MAPPO, Bus Bunching, Fleet Management, GPU-Accelerated Simulation, Intelligent Transportation Systems, Bus Rapid Transit

---

## Makale Bölümleri

| Dosya | Bölüm | İçerik |
|-------|-------|--------|
| `01_introduction.md` | Giriş | Problem tanımı, motivasyon, katkılar |
| `02_related_work.md` | İlgili Çalışmalar | Literatür taraması |
| `03_simulation.md` | Simülasyon Ortamı | Rota, fizik, FSM, platform |
| `04_ai_models.md` | AI Modelleri | MAPPO, Predictive Engine, hibrit karar |
| `05_gpu_optimization.md` | GPU Optimizasyonu | CUDA Graph, vectorized env |
| `06_monitoring.md` | Gerçek Zamanlı İzleme | WebSocket, dashboard |
| `07_experiments.md` | Deneysel Kurulum & Sonuçlar | Rota, parametreler, metrikler |
| `08_conclusion.md` | Sonuç ve Gelecek Çalışma | Özet, potansiyel uygulamalar |
