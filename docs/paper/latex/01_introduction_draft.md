# Intelligent Metrobus Fleet Management: A Hybrid Analytical-RL Approach Using MAPPO with GPU-Accelerated Simulation

---

## 1. Introduction

### 1.1 Problem Statement: Bus Bunching

Istanbul's Metrobus corridor is one of the world's busiest Bus Rapid Transit (BRT) systems, spanning 52 km with 44 stations and serving over 1 million daily passengers. During peak hours, vehicles operate at headways as low as 30 seconds on the Beylikdüzü–Söğütlüçeşme segment, making it one of the most intensively utilized transit corridors globally.

The most critical operational challenge in such high-frequency systems is **bus bunching** — the tendency of transit vehicles to cluster together rather than maintaining uniform headways. Bunching arises from a *positive feedback loop*: when a vehicle is delayed (e.g., due to a surge in boarding passengers), it encounters even more passengers at subsequent stops, further increasing its dwell time and delay. Meanwhile, the following vehicle encounters fewer waiting passengers, speeds up, and eventually catches the delayed vehicle, forming a cluster (Daganzo, 2009).

```
t=0:  BUS----BUS----BUS----BUS----BUS       Equal headway (ideal)
t=1:  BUS--BUS------BUS--BUS------BUS       A delayed, B approaching
t=2:  BUS-BUSBUS-----------BUSBUS-BUS       Two bunching clusters formed
t=3:  BUSBUSBUS-----------------BUSBUS      Cascade failure
```

Daganzo (2009) formally proved that bus bunching represents an *unstable equilibrium*: without active intervention, even infinitesimally small perturbations grow exponentially over time, making bunching an inevitable phenomenon in uncontrolled high-frequency transit systems.

#### 1.1.1 Consequences of Bunching

The impacts of bus bunching extend across multiple dimensions of transit performance:

- **Passenger wait time:** Under uniform headways, the expected wait time is E[W] = H/2, where H is the headway. Bunching introduces variance, increasing the expected wait to E[W] = (H/2)(1 + CV²), where CV is the coefficient of variation of headways (Osuna & Newell, 1972). For CV values commonly observed in bunched systems (1.0–2.0), wait times can increase by 100–300%.

- **Capacity waste:** Bunched vehicles arrive nearly empty at stops, while isolated vehicles are overcrowded, leading to 30–40% effective capacity loss.

- **Operational cost:** Service irregularity necessitates additional vehicles and overtime, increasing annual operating costs.

- **Energy consumption:** The stop-and-go traffic pattern induced by bunching increases fuel consumption by 15–20% compared to smooth-flow operations.

- **Platform congestion and double-stopping:** Perhaps the most operationally devastating consequence in high-capacity BRT systems is *platform overflow*. When bunched vehicles arrive at a station simultaneously, they exceed the platform's docking capacity. Vehicles that cannot physically access the platform are forced into a *queuing cascade*: they wait behind the docked vehicles, and upon finally reaching the platform, they must perform a *double-stop* — stopping once in the queue and then again at the docking position. This phenomenon creates a compounding delay cycle:

  1. A cluster of k vehicles arrives at a platform with capacity c < k.
  2. The first c vehicles dock; the remaining k − c vehicles idle behind.
  3. Queued vehicles block the corridor, preventing *all* following traffic from passing — even vehicles destined for other stations.
  4. When a slot opens, the queued vehicle advances and re-stops, adding a secondary dwell time of 15–30 seconds.
  5. Meanwhile, more vehicles arrive from behind, extending the queue further.

  On the Istanbul Metrobus corridor, where 30-second headways are common, a single double-stop event at a 2-slot platform can trigger a queue of 4–6 vehicles, each accumulating 30–60 seconds of additional delay. During morning peak hours at bottleneck stations such as Cevizlibağ and Merter, queues of 8–10 vehicles are routinely observed, with total accumulated delay per vehicle reaching 3–5 minutes — comparable to the entire scheduled travel time between two adjacent stations.

```
Platform capacity: 3 slots
Arriving cluster:  7 vehicles

  [IN PLATFORM]     [QUEUING]      [BLOCKED]
  BUS BUS BUS    |  BUS BUS    |  BUS BUS ...
  (docked)       |  (waiting)  |  (cannot pass)
                 |             |
  Double-stop    |  +30s each  |  +60s cascade
  penalty        |             |
```

#### 1.1.2 Istanbul Metrobus: Specific Challenges

The Istanbul Metrobus system presents unique challenges that exacerbate bunching:

1. **Extreme demand:** Peak-hour ridership exceeds the practical capacity of 30-second headways, creating boarding delays at major stations.

2. **Variable platform capacity:** Platform lengths range from 55 m (2 vehicle slots) to 232 m (9 slots). Short platforms create bottlenecks where vehicles queue for docking space. The distribution is heavily biased: over 60% of stations have ≤4 slots, making platform overflow a systemic rather than exceptional event.

3. **Platform congestion as a primary bunching amplifier:** Unlike conventional bus systems where bunching is primarily a headway management problem, the Metrobus corridor exhibits a second-order bunching mechanism driven by platform capacity constraints. When vehicle clusters arrive at a short-platform station, queuing delays *synchronize* trailing vehicles into an even tighter cluster, creating a self-reinforcing cycle: bunching → platform overflow → queuing delays → tighter bunching. Breaking this cycle requires not only headway regulation but also *predictive slot management* — adjusting approach speeds so that vehicles arrive at stations precisely when docking slots become available.

4. **Topographic variation:** The corridor traverses significant elevation changes (Büyükçekmece bridge, Haliç crossing), affecting vehicle speeds.

5. **Asymmetric demand:** Morning peak flows are predominantly toward the city center (east), while evening peaks reverse, creating directional bunching patterns.

---

### 1.2 Limitations of Existing Approaches

Several control strategies have been proposed to mitigate bus bunching, each with significant limitations:

#### Schedule-Based Control
The most common approach relies on predetermined timetables and departure times. While simple to implement and predictable for passengers, schedule-based control cannot adapt to real-time disturbances such as traffic incidents, demand surges, or weather-related delays. When a vehicle deviates from schedule, there is no self-correcting mechanism.

#### Rule-Based Holding Strategies
Threshold-based rules (e.g., "if headway < 2 min, hold at current stop") provide reactive control. Cats et al. (2011) demonstrated that simple holding strategies can reduce bunching by 30–40%. However, rule-based systems cannot model complex multi-vehicle interactions: slowing vehicle A affects vehicles B, C, and D in ways that simple rules cannot anticipate. Furthermore, rule conflicts arise as the number of rules increases.

#### Centralized Optimization
Formulating fleet control as a centralized optimization problem:

> min Σ(hᵢ − h_target)²   subject to   v_min ≤ vᵢ ≤ v_max

faces scalability challenges. For N = 200 vehicles with continuous speed controls, the decision space is high-dimensional. Communication latency (1–5 seconds) between the control center and vehicles introduces delays that degrade control quality. Additionally, centralized systems present a single point of failure.

#### Single-Agent Reinforcement Learning
Training a single RL agent to control all vehicles simultaneously leads to an exponential explosion of the action space: N vehicles with K discrete actions produce K^N possible joint actions. For our system (N = 200, K = 4), this yields 4^200 ≈ 10^120 combinations — astronomically intractable. The *credit assignment problem* (determining which vehicle's action contributed to the global reward) further impedes learning.

---

### 1.3 Proposed Approach

This paper presents **a hybrid analytical-RL fleet management system** for the Istanbul Metrobus corridor, combining two complementary decision-making mechanisms:

#### Multi-Agent PPO (MAPPO)
We adopt the Centralized Training, Decentralized Execution (CTDE) paradigm (Lowe et al., 2017), where:

- During **training**: A centralized Critic network observes the joint state of all N agents (s_global ∈ R^(N×24)), providing stable value estimates.
- During **execution**: Each vehicle runs an independent, lightweight Actor network (π(aᵢ|oᵢ), oᵢ ∈ R^24) requiring no inter-vehicle communication.

Following Yu et al. (2022), who demonstrated that MAPPO consistently outperforms more complex multi-agent algorithms (QMIX, MADDPG) across cooperative benchmarks, we employ parameter sharing across all agents, enabling scalability to 200 vehicles.

#### Analytical Fleet Controller
Alongside MAPPO, we develop a deterministic analytical controller based on:

- **PID headway regulation:** Proportional-Integral-Derivative control that maintains uniform vehicle spacing by modulating speed factors based on gap errors.
- **Slot lookahead optimization:** Each vehicle computes the optimal approach speed to arrive at its target station precisely when a docking slot becomes available, eliminating queue waiting time.
- **Forward safety:** A minimum-gap enforcement layer prevents rear-end collisions.

The analytical controller requires no training and provides immediate, deterministic, and explainable decisions. Our comparative evaluation demonstrates that this mathematical approach achieves competitive performance with MAPPO, offering a complementary perspective on the bunching problem.

---

### 1.4 Contributions

The main contributions of this paper are:

1. **High-fidelity simulation environment:** A GPU-accelerated digital twin of the Istanbul Metrobus corridor, featuring real-world route geometry derived from OpenStreetMap, Intelligent Driver Model (IDM) car-following physics, an 8-phase station Finite State Machine (FSM) with parallel platform docking, and stochastic demand perturbations.

2. **Hybrid decision architecture:** A novel combination of MAPPO (for long-horizon strategy learning) and an analytical PID-lookahead controller (for instantaneous risk management), with comparative benchmarking against uncontrolled and random baselines.

3. **GPU-accelerated parallel training:** CUDA Graph-captured vectorized environments running 512 parallel instances with 200 vehicles each (~20,000 simulation steps per second on an NVIDIA RTX 5070 Ti), reducing training time from days to approximately 75 minutes.

4. **Real-time monitoring system:** A WebSocket-based live dashboard streaming training state to a Leaflet map interface, enabling real-time observation of fleet behavior during the learning process.

5. **Portable model output:** The trained MAPPO policy is exportable as an ONNX model (23 KB) for deployment in browser-based dashboards (via onnxruntime-web) or edge devices.

---

### 1.5 Paper Organization

The remainder of this paper is organized as follows: Section 2 reviews related work on bus bunching control and multi-agent reinforcement learning. Section 3 describes the simulation environment in detail. Section 4 presents the MAPPO and analytical controller architectures. Section 5 discusses GPU optimization strategies. Section 6 presents experimental results and comparative analysis. Section 7 concludes with a discussion of limitations and future work.

---

## References (Introduction'da kullanılanlar)

- Daganzo, C.F. (2009). "A headway-based approach to eliminate bus bunching." *Transportation Research Part B*, 43(10), 913–921.
- Osuna, E.E. & Newell, G.F. (1972). "Control strategies for an idealized public transportation system." *Transportation Science*, 6(1), 52–72.
- Cats, O. et al. (2011). "Impacts of holding control strategies on transit performance." *Transportation Research Record*, 2216, 51–58.
- Lowe, R. et al. (2017). "Multi-agent actor-critic for mixed cooperative-competitive environments." *NeurIPS*.
- Yu, C. et al. (2022). "The surprising effectiveness of PPO in cooperative multi-agent games." *NeurIPS*.
