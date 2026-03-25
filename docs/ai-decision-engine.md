# 🧠 AI Decision Engine — Arka Planda Nasıl Çalışır?

> Bu belge, metrobüs simülasyonundaki AI karar motorunun her bir adımını, kaynak koduna referanslarla birlikte detaylı olarak açıklar.

---

## Genel Bakış: Bir Simülasyon Adımının Anatomisi

Her `step()` çağrısında sırayla 9 aşama çalışır. Tek bir adımın toplam süresi **~0.1ms** (GPU) + **~1ms** (Predictive CPU).

```
gpu_env.py → step(actions)
│
├─ [1] RL Aksiyonları Uygula ─────── MAPPO'dan gelen kararlar
├─ [1.5] Predictive Engine ───────── Bunching taraması + hız filtresi
├─ [2] Stokastik Perturbasyonlar ─── Gerçekçilik (rastgele yavaşlama)
├─ [3] Araç Sıralama ────────────── Pozisyona göre sıralama
├─ [4] Station FSM ───────────────── 8 fazlı durak yönetimi
├─ [5] Pozisyon Kilidi ───────────── Durmuş araçları yerinde tut
├─ [6] Hedef Hız Hesaplama ───────── Hız limiti × speed_factor
├─ [7] IDM Fiziği ────────────────── Araç takip modeli
├─ [8] Hat Sonu Wrapping ─────────── Hattı bitiren araçları başa al
└─ [9] Observation + Reward ──────── RL için state ve ödül hesapla
```

---

## Adım 1: RL Aksiyonları Uygula

**Dosya:** `gpu_env.py` satır 253-263  
**Girdi:** `actions` tensörü — (B, N) boyutunda, her araç için 0-3 arası tam sayı  
**B** = 512 paralel ortam, **N** = 80 araç

```
Aksiyon 0: NORMAL   → speed_factor = 1.0 (müdahale yok)
Aksiyon 1: HOLD     → Sonraki durakta ekstra bekleme süresi ekle (10s)
Aksiyon 2: SKIP     → (şu an devre dışı)
Aksiyon 3: SPEED    → speed_factor = 0.7 (yavaşla)
```

### İşlem akışı:

```
actions tensor (B=512, N=80) — her hücre 0..3 arası
    │
    ▼
SPEED_FACTOR_MAP tablosu: [1.0, 1.0, 1.0, 0.7]
    │
    ▼
speed_factor = SPEED_FACTOR_MAP[actions]  → (512, 80) float tensor
    │
    ▼
HOLD aksiyonları: holding_extra = max(mevcut, 10.0 sn)
```

**Önemli:** Bu aşamada hız henüz değişmez. `speed_factor` sadece kaydedilir, Adım 6'da hedef hıza uygulanır.

---

## Adım 1.5: Predictive Lookahead Engine

**Dosya:** `gpu_env.py` satır 265-268, `predictive_engine.py` (911 satır)  
**Çalışma koşulu:** `_in_graph_mode == False` (CUDA Graph capture sırasında devre dışı)  
**Kapsam:** Sadece env[0] üzerinde çalışır (dashboard görselleştirme için)

### 1.5.1 GPU → CPU Snapshot

```
GPU Tensörleri (VRAM)              CPU NumPy (RAM)
┌─────────────────────┐            ┌─────────────────────┐
│ positions[0] (80,)  │ ──.cpu()─→ │ positions (80,)     │
│ speeds[0]    (80,)  │ ──.cpu()─→ │ speeds    (80,)     │
│ phases[0]    (80,)  │ ──.cpu()─→ │ phases    (80,)     │
│ dwell_rem[0] (80,)  │ ──.cpu()─→ │ dwell_rem (80,)     │
│ next_si[0]   (80,)  │ ──.cpu()─→ │ next_si   (80,)     │
│ holding[0]   (80,)  │ ──.cpu()─→ │ holding   (80,)     │
└─────────────────────┘            └─────────────────────┘
```

### 1.5.2 BusSnapshot Oluşturma

Her araç için Python dataclass'ı oluşturulur:

```python
BusSnapshot(
    bus_id    = 42,
    position  = 15230.5,    # metre
    speed     = 11.2,       # m/s
    phase     = "cruising", # 8 faz string
    next_stop = 12,         # sonraki durak indexi
    dwell_rem = 0.0,        # kalan bekleme süresi
    holding   = 0.0,        # RL'den ek bekleme
)
```

### 1.5.3 Her Otobüs İçin Değerlendirme

`evaluate_all_buses()` fonksiyonu tüm otobüsleri tek tek değerlendirir:

```
Otobüs #42 değerlendiriliyor:
│
├─ 1. Hedef durağı belirle: stops[next_stop_index]
│     → Cevizlibağ (pozisyon: 16200m, kapasite: 3 slot)
│
├─ 2. Tüm otobüslerin ETA'sını hesapla (IDM mini-sim)
│     ┌──────────────────────────────────────────────┐
│     │ compute_all_etas()                            │
│     │                                               │
│     │  Otobüs #40: pos=14500m → ETA=120s            │
│     │  Otobüs #41: pos=15100m → ETA= 85s            │
│     │  Otobüs #42: pos=15230m → ETA= 70s  ← bizim   │
│     │  Otobüs #43: pos=15800m → ETA= 30s            │
│     │  (hepsi Cevizlibağ'a doğru gidiyor)           │
│     └──────────────────────────────────────────────┘
│
├─ 3. Bunching riski tespit et
│     ┌──────────────────────────────────────────────┐
│     │ detect_bunching_risk()                        │
│     │                                               │
│     │ ETA sıralama: #43(30s) > #42(70s) > #41(85s)  │
│     │ Rank #42 = 2 (2. sırada varacak)              │
│     │ Durak kapasitesi: 3 slot                      │
│     │ rank(2) ≤ capacity(3) → ❌ RİSK YOK           │
│     │                                               │
│     │ VEYA 4 otobüs, 3 slot:                        │
│     │ rank(4) > capacity(3) → ⚠️ RİSK VAR           │
│     └──────────────────────────────────────────────┘
│
├─ 4. Risk varsa → İki senaryo simüle et
│     │
│     ├─ Senaryo A: "Müdahale etme, ne olur?"
│     │   ┌─────────────────────────────────────┐
│     │   │ T_A = ETA + W (kuyruk bekleme) + τ  │
│     │   │     = 70s + 15s (slot bekleme) + 21s│
│     │   │     = 106s                          │
│     │   │                                     │
│     │   │ Score_A = α·T_A + β·passenger +     │
│     │   │          γ·headway_impact + δ·energy │
│     │   │        = 1.0·106 + 0.5·5 + 0.3·10   │
│     │   │        = 111.5                      │
│     │   └─────────────────────────────────────┘
│     │
│     └─ Senaryo B: "Yavaşlatırsak ne olur?"
│         ┌─────────────────────────────────────┐
│         │ v_filtered hesapla:                 │
│         │   Önündeki araç çıkana kadar yavaşla │
│         │   v_target = distance / time_needed │
│         │            = 970m / 130s = 7.46 m/s │
│         │                                     │
│         │ T_B = ETA_slow + 0 (bekleme yok) +τ │
│         │     = 130s + 0s + 21s = 151s       │
│         │                                     │
│         │ Score_B = 1.0·151 + 0.5·0 + 0.3·2  │
│         │        = 151.6                     │
│         │                                     │
│         │ ⚠️ T_B > T_A → yavaşlamak daha uzun │
│         │    AMA kuyruk bekleme yok           │
│         └─────────────────────────────────────┘
│
├─ 5. Karar ver
│     ┌─────────────────────────────────────────┐
│     │ Score_A(111.5) < Score_B(151.6)         │
│     │ → BUNCHING_ACCEPT (yavaşlamaya değmez)  │
│     │                                         │
│     │ VEYA Score_B < Score_A:                  │
│     │ → SPEED_FILTER (yavaşla, v=7.46 m/s)   │
│     │                                         │
│     │ VEYA risk yok:                          │
│     │ → NO_RISK (müdahale gereksiz)           │
│     └─────────────────────────────────────────┘
│
└─ 6. GPU'ya geri yaz
      SPEED_FILTER kararı varsa:
        speed_factor[0, 42] = v_target / current_speed
                            = 7.46 / 11.2 = 0.666
```

---

## Adım 2: Stokastik Perturbasyonlar

**Dosya:** `gpu_env.py` satır 269-273

Gerçek trafikte ani yavaşlamalar (yolcu düşmesi, engel, vs.) olur. Bunu simüle etmek için:

```
Her step'te her araç için %0.3 olasılıkla:
  speed *= 0.3     (aniden yavaşla)
  acceleration = -2.0  (sert fren)
```

---

## Adım 3: Araç Sıralama

**Dosya:** `gpu_env.py` satır 276

```python
sorted_idx = torch.argsort(positions, dim=1)  # (512, 80)
```

IDM fiziği "öndeki araç" kavramını gerektirir. Bunun için araçlar pozisyona göre sıralanır. Bu sıralama Adım 7'de kullanılır.

---

## Adım 4: Station FSM (Finite State Machine)

**Dosya:** `gpu_env.py` satır 373-550  
**8 faz, tümü paralel tensor operasyonlarıyla işlenir:**

```
┌──────────────────────────────────────────────────────────────────┐
│                     DURAK YAŞAM DÖNGÜSÜ                         │
│                                                                  │
│  CRUISING ──dist<150m──→ APPROACHING ──slow+inzone──→ STOPPED   │
│                                                        │         │
│          slot var mı?                                  │         │
│          ├─ evet → direkt STOPPED                      │         │
│          └─ hayır → QUEUED ──slot açıldı──→ DOCKING    │         │
│                                              │         │         │
│                                   yaklaş → STOPPED     │         │
│                                                        │         │
│  STOPPED ──dwell=0──→ DOORS_CLOSED ──1s──→ DEPARTING   │         │
│                                              │         │         │
│                          önde araç var mı?   │         │         │
│                          ├─ evet → BLOCKED   │         │         │
│                          └─ hayır → çık      │         │         │
│                                              │         │         │
│  DEPARTING ──speed>2──→ CRUISING (next_stop_idx += 1)  │         │
└──────────────────────────────────────────────────────────────────┘
```

**Kritik:** STOPPED'a geçişte pozisyon durak noktasına **snap** edilir:
```python
snap_pos = stop_positions[safe_nsi]
positions = where(enter_stopped, snap_pos, positions)
```

---

## Adım 5: Pozisyon Kilidi

**Dosya:** `gpu_env.py` satır 282

```python
pos_lock = (phase == STOPPED) | (phase == DOORS_CLOSED) | 
           (phase == BLOCKED) | (phase == DOCKING) | (phase == QUEUED)
```

Durakta olan araçlar Adım 7'de fizik güncellemesinden muaf tutulur.

---

## Adım 6: Hedef Hız Hesaplama

**Dosya:** `gpu_env.py` satır 284-286

```
target_speed = base_speed_limit           # 12.5 m/s (sabit)
             × speed_factor               # RL (0.7-1.0) veya Predictive (0.2-1.0)
             
target_speed = clamp(target_speed, max=14.0 m/s)
```

**Burası RL ve Predictive'in birleştiği nokta:**
```
RL diyor:          speed_factor = 0.7  (SPEED aksiyonu)
Predictive diyor:  speed_factor = 0.5  (SPEED_FILTER, bunching riski)

Son geçerli: Predictive (Adım 1.5'te override ediyor)
→ target_speed = 12.5 × 0.5 = 6.25 m/s
```

---

## Adım 7: IDM Fiziği

**Dosya:** `gpu_env.py` satır 311-368  
**Intelligent Driver Model** — her araç öndeki aracı takip eder.

```
IDM Formülü:

                    ┌         ⎛  v  ⎞⁴     ⎛ s*(v,Δv) ⎞²  ┐
  a = a_max × ⎢ 1 - ⎜────⎟   -  ⎜─────────⎟   ⎥
                    ⎣         ⎝ v₀  ⎠      ⎝    s     ⎠   ⎦

  s* = s₀ + v·T + v·Δv / (2·√(a·b))

  Parametreler:
    a_max = 1.0 m/s²     (max ivme)
    b     = 2.0 m/s²     (rahat frenleme)
    s₀    = 2.0 m        (minimum boşluk)
    T     = 1.5 s        (takip mesafesi zamanı)
    v₀    = target_speed (Adım 6'dan)
    δ     = 4            (IDM üssü)
```

### Hesaplama akışı:

```
80 araç pozisyona göre sıralı
    │
    ▼
Gap hesapla: gap[i] = pos[i+1] - 20m (araç boyu) - pos[i]
    │
    ▼
ΔV hesapla:  deltaV[i] = speed[i] - speed[i+1]
    │
    ▼
IDM ivme hesapla: accel[i] = f(speed, target, gap, deltaV)
    │
    ▼
Sınırla: clamp(accel, -4.5, +1.0)  # acil fren ↔ max ivme
    │
    ▼
Hız güncelle: speed = max(0, speed + accel × dt)
    │
    ▼
Pozisyon güncelle: pos += speed × dt + 0.5 × accel × dt²
    │
    ▼
Kilili araçları sıfırla: if pos_lock → speed=0, ds=0
    │
    ▼
Unsort: sıralı sonuçları orijinal araç indexlerine geri yaz
```

---

## Adım 8: Hat Sonu Wrapping

**Dosya:** `gpu_env.py` satır 291-297

```
if position >= route_length (50.49 km):
    position = 0            (başa dön)
    next_stop_idx = 0       (ilk durak)
    phase = CRUISING        (sürüşe devam)
```

---

## Adım 9: Observation + Reward

### 9.1 Observation Vektörü (24 boyut)

**Dosya:** `gpu_env.py` satır 630-655

```
obs[0]  = position / route_length        # Normalize pozisyon [0,1]
obs[1]  = speed / max_speed              # Normalize hız [0,1]
obs[2]  = forward_gap / route_length     # Öndeki araçla mesafe
obs[3]  = backward_gap / route_length    # Arkadaki araçla mesafe
obs[4]  = dwell_remaining / max_dwell    # Kalan bekleme süresi
obs[5]  = sin(2π·hour/24)               # Saat — sinüsoidal kodlama
obs[6]  = cos(2π·hour/24)               # Saat — kosinüs kodlama
obs[7]  = is_rush_hour                   # Rush saati mi? (0/1)
obs[8]  = phase == CRUISING              # Sürüş fazında mı?
obs[9]  = phase ∈ {APPROACHING,QUEUED,DOCKING}  # Yaklaşma grubu
obs[10] = phase ∈ {STOPPED,CLOSED,BLOCKED}      # Durakta grubu
obs[11] = phase == DEPARTING             # Kalkış fazında mı?
obs[12] = next_stop_dist (normalize)     # Durağa mesafe
obs[13] = acceleration / b_emergency     # Normalize ivme
obs[14] = leader_speed / max_speed       # Öndekinin hızı
obs[15] = follower_speed / max_speed     # Arkadakinin hızı
obs[16] = leader_is_stopped              # Öndeki durmuş mu?
obs[17] = follower_is_stopped            # Arkadaki durmuş mu?
obs[18] = next_stop_queue (normalize)    # Duraktaki araç sayısı
obs[19] = prev_stop_distance             # Önceki durağa mesafe
obs[20] = second_next_distance           # 2. durağa mesafe
obs[21] = episode_progress               # Bölüm ilerlemesi [0,1]
obs[22] = slot_capacity / 6.0            # Durak slot kapasitesi
obs[23] = slot_occupancy                 # Doluluk oranı
```

### 9.2 Reward Fonksiyonu

**Dosya:** `gpu_env.py` satır 662-697

```
Reward = R_headway + R_bunching + R_dwell + R_speed

R_headway = (1 - CoV) × 10.0
  CoV = headway_std / headway_mean
  İyi: CoV düşük → yüksek ödül (araçlar eşit aralıklı)
  Kötü: CoV yüksek → düşük/negatif ödül

R_bunching = -(bunching_ratio) × 5.0
  Gap < 100m → kritik bunching (tam ceza)
  Gap < 200m → uyarı (yarım ceza)

R_dwell = -(long_dwell_count / N) × 0.5
  Durakta 90s'den fazla kalan araçlar cezalandırılır

R_speed = 2.0 × exp(-2 × (avg_speed/target - 1)²)
  Ortalama hız hedefe (40 km/h) yakınsa bonus
  Gaussian şeklinde: tam hedefse max, sapma artınca düşer
```

---

## Büyük Resim: Bir Eğitim Döngüsü

**Dosya:** `train.py`

```
1. Actor ağı: obs(24) → softmax → aksiyon(0-3)     ~29 KB
2. Critic ağı: global_obs(1920) → value             ~1 MB

Döngü (3000 iterasyon):
┌──────────────────────────────────────────────────────┐
│ Iterasyon #1000                                      │
│                                                      │
│ 1. ROLLOUT: 128 adım × 512 env = 65,536 deneyim     │
│    ┌────────────────────────────────────┐             │
│    │ for t in range(128):              │             │
│    │   action = Actor(obs)             │ ← GPU      │
│    │   obs, reward, ... = env.step(action)│ ← GPU   │
│    │   buffer.store(obs, action, reward)│            │
│    └────────────────────────────────────┘             │
│                                                      │
│ 2. GAE HESAPLA: Advantage = R - V(s) + γλ(...)      │
│                                                      │
│ 3. PPO GÜNCELLEMESİ: 10 epoch × 8 mini-batch        │
│    ┌────────────────────────────────────┐             │
│    │ for epoch in range(10):           │             │
│    │   for batch in mini_batches(8):   │             │
│    │     ratio = π_new / π_old         │             │
│    │     L_clip = min(ratio·A,         │             │
│    │               clip(ratio)·A)      │             │
│    │     actor_loss = -L_clip          │             │
│    │     critic_loss = (V-R)²          │             │
│    │     loss = actor + 0.5·critic     │             │
│    │           - 0.01·entropy          │             │
│    │     optimizer.step()              │             │
│    └────────────────────────────────────┘             │
│                                                      │
│ 4. LOG: TensorBoard + WS Bridge → Dashboard          │
│    reward=-0.55, p_loss=-0.005, entropy=1.35          │
│    fps=16,000                                        │
└──────────────────────────────────────────────────────┘
```

---

## Özet: Tek Bir Step'in Zaman Çizelgesi

```
t=0.000ms  RL aksiyonları uygula (GPU tensor lookup)
t=0.005ms  speed_factor tensörü güncellendi
t=0.010ms  Predictive Engine başla (CPU'ya kopyala)
t=0.100ms  80 otobüs için ETA hesapla (IDM mini-sim)
t=0.800ms  Bunching risk + Senaryo A/B simülasyonu
t=1.000ms  SPEED_FILTER kararları → GPU'ya geri yaz
t=1.001ms  Stokastik perturbasyonlar
t=1.005ms  Araç sıralama (argsort)
t=1.010ms  Station FSM (8 faz, tensor mask)
t=1.020ms  Pozisyon kilidi hesapla
t=1.025ms  Hedef hız = speed_limit × speed_factor
t=1.030ms  IDM fiziği (gap, deltaV, ivme, hız, pozisyon)
t=1.050ms  Hat sonu wrapping
t=1.055ms  Observation vektörü (24 dim × 80 araç)
t=1.060ms  Reward hesapla (headway + bunching + dwell + speed)
t=1.065ms  → return (obs, reward, terminated, truncated)
─────────────────────────────────────────────────────────
TOPLAM: ~1.1ms per step (GPU + CPU hibrit)
```
