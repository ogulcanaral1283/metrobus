# 4. AI MODELLERİ (AI Models)

## 4.1 MAPPO (Multi-Agent Proximal Policy Optimization)

### 4.1.1 PPO Temelleri

Proximal Policy Optimization (Schulman et al., 2017) policy gradient ailesinin en kararlı algoritmalarından biridir. Temel fikir: politikayı güncelerken "çok büyük adım atma" — clipping mekanizması ile politika değişimi sınırlandırılır.

**PPO Objective:**

$$L^{CLIP}(\theta) = \hat{\mathbb{E}}_t \left[ \min\left(r_t(\theta) \hat{A}_t, \text{clip}(r_t(\theta), 1-\epsilon, 1+\epsilon) \hat{A}_t \right) \right]$$

Burada:
- $r_t(\theta) = \frac{\pi_\theta(a_t|s_t)}{\pi_{\theta_{old}}(a_t|s_t)}$ — yeni ve eski politika oranı
- $\hat{A}_t$ — Generalized Advantage Estimation (GAE)
- $\epsilon = 0.2$ — clipping parametresi

### 4.1.2 MAPPO: Multi-Agent Genelleme

MAPPO'da her ajan $i$ kendi Actor ağını paylaşır (parameter sharing), merkezi bir Critic ağı tüm ajanların birleştirilmiş gözlemini kullanır:

**Actor Loss (her ajan için):**
$$L^{actor}_i = -\hat{\mathbb{E}}_t \left[ \min\left(r^i_t \hat{A}^i_t, \text{clip}(r^i_t, 1-\epsilon, 1+\epsilon) \hat{A}^i_t \right) \right]$$

**Critic Loss (merkezi):**
$$L^{critic} = \hat{\mathbb{E}}_t \left[ \left(V_\phi(s^{global}_t) - R_t\right)^2 \right]$$

**Entropy Bonus:**
$$L^{entropy}_i = -H[\pi_\theta(\cdot|o^i_t)] = \sum_a \pi_\theta(a|o^i_t) \log \pi_\theta(a|o^i_t)$$

**Toplam Loss:**
$$L = L^{actor} + c_v \cdot L^{critic} - c_e \cdot L^{entropy}$$

### 4.1.3 Ağ Mimarileri

**Actor Ağı** (her ajan için — parameter sharing):
```
Input: o_i ∈ ℝ²⁴ (ajanın yerel gözlemi)
    │
    ▼
Linear(24 → 64) + ReLU
    │
    ▼
Linear(64 → 64) + ReLU
    │
    ▼
Linear(64 → 4) + Softmax
    │
    ▼
Output: π(a|o_i) ∈ Δ³  (4 aksiyon üzerinde olasılık dağılımı)

Parametre sayısı: 24×64 + 64 + 64×64 + 64 + 64×4 + 4 = 5,828
```

**Critic Ağı** (merkezi):
```
Input: s_global = concat(o_1, o_2, ..., o_N) ∈ ℝᴺˣ²⁴
       N=200 araç → 4800 boyut
    │
    ▼
Linear(4800 → 128) + ReLU
    │
    ▼
Linear(128 → 128) + ReLU
    │
    ▼
Linear(128 → 1)
    │
    ▼
Output: V(s) ∈ ℝ  (durum değeri)

Parametre sayısı: 4800×128 + 128 + 128×128 + 128 + 128×1 + 1 = 631,297
```

**Toplam model boyutu**: ~637 KB (Actor: 23 KB, Critic: 2.4 MB)

### 4.1.4 Aksiyon Uzayı

| ID | Aksiyon | speed_factor | Etki | Kullanım Senaryosu |
|----|---------|-------------|------|---------------------|
| 0 | **SLOW** | 0.6× | Hedef hızı %40 düşür | Öndeki araca yaklaştığında, bunching riski |
| 1 | **NORMAL** | 1.0× | Değişiklik yok | Normal seyir devam |
| 2 | **FAST** | 1.2× | Hedef hızı %20 artır | Arkadaki araçtan uzaklaşmak |
| 3 | **HOLD** | 1.0× + 5s bekleme | Durakta ekstra bekleme | Headway dengeleme |

**Tasarım kararları:**
- Ayrık aksiyon uzayı (4 seçenek) sürekli kontrole göre daha kararlı eğitim sağlar
- HOLD aksiyonu sadece durakta etkili — seyir halinde NORMAL'e eşdeğer
- speed_factor çarpımsal olarak uygulanır: $v_{target} = v_{limit} \times f_{RL}$

### 4.1.5 Gözlem Uzayı (24 boyut)

Her ajan her step'te 24 boyutlu normalize edilmiş gözlem vektörü alır:

| Dim | Gözlem | Normalizasyon | Bilgi Türü |
|-----|--------|---------------|------------|
| 0 | Kendi hızı | v / v_max | Ego state |
| 1 | İvme | a / a_emg | Ego state |
| 2 | Pozisyon | pos / route_len | Ego state |
| 3 | Sonraki durağa mesafe | d / route_len | Navigasyon |
| 4 | **Öndeki araç mesafesi** | gap_f / route_len | Komşu bilgisi |
| 5 | **Arkadaki araç mesafesi** | gap_b / route_len | Komşu bilgisi |
| 6 | Öndeki aracın hızı | v_l / v_max | Komşu bilgisi |
| 7 | Arkadaki aracın hızı | v_f / v_max | Komşu bilgisi |
| 8-11 | Phase one-hot encoding | {0,1} | FSM state |
| 12 | Dwell kalan süre | t / 120 | Durak state |
| 13 | Rush hour göstergesi | {0,1} | Kontekst |
| 14 | Trafik hız faktörü | [0,1] | Çevre |
| 15-17 | 2. ve 3. komşu mesafeleri | gap / route_len | Geniş görüş |
| 18 | Durak kuyruk uzunluğu | q / q_max | Platform state |
| 19-20 | Önceki/2. sonraki durak mesafesi | d / route_len | Navigasyon |
| 21 | Episode ilerleme | t / T_max | Kontekst |
| 22-23 | Slot kapasitesi ve doluluk | c/6, occ/2 | Platform state |

**Tasarım gerekçeleri:**
- **Tüm değerler [0,1] aralığına normalize edilmiş** — ağ eğitiminin kararlılığı için kritik
- **Phase one-hot**: Kategorik bilgi kayıpsız temsil
- **2./3. komşu**: Sadece bitişik araç değil, ikinci ve üçüncü komşu da görülür → daha uzun vadeli strateji
- **Platform bilgisi**: Peron kapasitesi ve doluluk → HOLD kararı için önemli

### 4.1.6 Reward Fonksiyonu

$$R = R_{headway} + R_{bunching} + R_{dwell} + R_{speed}$$

#### Bileşen 1: Headway Düzgünlüğü (Ana bileşen)

$$CV_{headway} = \frac{\sigma_h}{\mu_h}$$
$$R_{headway} = \text{clamp}(1 - CV, -1, 1) \times w_{headway}$$

| $CV$ | Anlam | $R_{headway}$ (w=10) |
|------|-------|---------------------|
| 0.0 | Mükemmel eşit aralık | +10.0 |
| 0.5 | Orta düzensizlik | +5.0 |
| 1.0 | Ciddi düzensizlik | 0.0 |
| 2.0+ | Kaotik | -10.0 |

**Neden CV?** Coefficient of Variation ölçeğe bağımsızdır — farklı headway büyüklüklerinde karşılaştırılabilir.

#### Bileşen 2: Bunching Cezası

$$R_{bunching} = -\frac{n_{critical} + 0.5 \cdot n_{warning}}{N-1} \times w_{bunching}$$

- $n_{critical}$: gap < 50m olan araç çifti sayısı
- $n_{warning}$: 50m ≤ gap < 100m olan araç çifti sayısı
- Ağırlık: $w_{bunching} = 5.0$

#### Bileşen 3: Uzun Bekleme Cezası

$$R_{dwell} = -\frac{|\{i : dwell_i > 90s \wedge \neg queuing_i\}|}{N} \times w_{dwell}$$

Kuyrukta bekleyen araçlar cezalandırılmaz (kuyruk bekleme meşru bir nedendir). Ağırlık: $w_{dwell} = 0.5$

#### Bileşen 4: Hız Bonusu

$$R_{speed} = w_{speed} \cdot \exp\left(-2 \left(\frac{\bar{v}}{v_{target}} - 1\right)^2\right)$$

Gaussian şeklinde: hedef hıza ($v_{target} = 40$ km/h) yakınsa yüksek bonus, sapma arttıkça hızla düşer. Ağırlık: $w_{speed} = 2.0$

### 4.1.7 GAE (Generalized Advantage Estimation)

$$\hat{A}_t = \sum_{l=0}^{T-t} (\gamma\lambda)^l \delta_{t+l}$$
$$\delta_t = r_t + \gamma V(s_{t+1}) - V(s_t)$$

Parametreler: $\gamma = 0.99$, $\lambda = 0.95$

## 4.2 Predictive Lookahead Decision Engine

### 4.2.1 Motivasyon

MAPPO uzun vadeli strateji öğrenirken, bazı durumlar **anlık analitik çözüm** gerektirir. Örneğin:

```
Senaryo: Cevizlibağ durağı (3 slot)
  - Slot 1: M07 (dwell: 15s kaldı)
  - Slot 2: M12 (dwell: 8s kaldı)
  - Slot 3: M18 (dwell: 22s kaldı)
  - Yaklaşan: M23 (970m, 11.2 m/s)

Soru: M23 ne yapmalı?
  A) Normal hızla gelsin → slot yok → QUEUED → 15s kuyruk bekleme
  B) 7.46 m/s'ye yavaşlasın → M07 çıkar → direkt slot → 0s bekleme
```

Bu tür kararlar analitik olarak hesaplanabilir ve RL'nin keşfetmesini beklemeye gerek yoktur.

### 4.2.2 Çift Senaryo Simülasyonu

Her otobüs için iki alternatif gelecek simüle edilir:

**Senaryo A — Müdahale Yok:**
$$T_A = ETA_{current} + W_{queue} + \tau_{dwell}$$
$$Score_A = \alpha \cdot T_A + \beta \cdot P_{waiting} + \gamma \cdot H_{impact}$$

**Senaryo B — Hız Filtreleme:**
$$v_{filtered} = \frac{d_{to\_stop}}{t_{slot\_free} + \Delta t_{buffer}}$$
$$T_B = ETA_{slow} + 0 + \tau_{dwell}$$
$$Score_B = \alpha \cdot T_B + \beta \cdot P_{waiting} + \gamma \cdot H_{impact} + \delta \cdot E_{cost}$$

**Karar:**
$$Decision = \begin{cases}
\text{SPEED\_FILTER} & \text{if } Score_B < Score_A \\
\text{BUNCHING\_ACCEPT} & \text{if } Score_A \leq Score_B \\
\text{NO\_RISK} & \text{if risk yok}
\end{cases}$$

### 4.2.3 IDM Mini-Simülasyon ile ETA Hesaplama

ETA tahmini basit $d/v$ yerine IDM tabanlı mini-simülasyon ile yapılır:

```python
def compute_eta(bus, target_stop, all_buses):
    """IDM fiziği ile gerçekçi ETA hesapla."""
    sim_bus = copy(bus)
    t = 0
    while sim_bus.position < target_stop.position:
        # Öndeki araca göre IDM ivme
        leader = find_leader(sim_bus, all_buses)
        accel = idm_acceleration(sim_bus, leader)
        
        # Euler entegrasyonu
        sim_bus.speed += accel * dt
        sim_bus.position += sim_bus.speed * dt
        t += dt
        
        if t > 300:  # 5dk timeout
            break
    return t
```

Bu yaklaşım, öndeki araçların hareketini de hesaba katarak klasik $d/v$ tahmininden çok daha doğru ETA üretir.

### 4.2.4 Skor Ağırlıkları

| Katsayı | Sembol | Değer | Açıklama |
|---------|--------|-------|----------|
| Toplam süre | $\alpha$ | 1.0 | Ana kriter — toplam operasyon süresi |
| Yolcu bekleme | $\beta$ | 0.5 | Kuyruk beklemesi yolcuları etkiler |
| Headway bozulma | $\gamma$ | 0.3 | Yavaşlamak headway'i bozabilir |
| Enerji maliyeti | $\delta$ | 0.1 | Hız değişimi enerji harcar |

## 4.3 Hibrit Karar Mekanizması

MAPPO ve Predictive Engine kararları çarpımsal olarak birleştirilir:

$$v_{target} = v_{limit} \times f_{RL} \times f_{PE}$$

```
Örnek:
  v_limit = 12.5 m/s  (hat hız limiti)
  f_RL = 0.6           (MAPPO: SLOW seçti)
  f_PE = 0.8           (PE: hafif yavaşlama)
  
  v_target = 12.5 × 0.6 × 0.8 = 6.0 m/s
```

**Neden hibrit?**

| Bileşen | Güçlü Yanı | Zayıf Yanı |
|---------|------------|------------|
| **MAPPO** | Uzun vadeli strateji, tüm ajanlar koordineli | Eğitim gerektirir, keşif süresi |
| **Predictive Engine** | Anlık risk tespiti, analitik kesinlik | Sadece bir durağa bakıyor, global strateji yok |
| **Hibrit** | Her ikisinin avantajlarını birleştirir | — |
