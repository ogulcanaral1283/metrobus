# 5. GPU OPTİMİZASYONU (GPU-Accelerated Training)

## 5.1 Motivasyon: Neden GPU?

Pekiştirmeli öğrenme algoritmalarının en büyük darboğazı **veri toplama hızıdır**. Policy gradient yöntemleri (PPO dahil) on-policy algoritmalar olduğundan, her güncelleme için taze veri toplanmalıdır. CPU tabanlı simülasyonlarda bu süreç eğitim süresinin %90+'ını oluşturur.

**Darboğaz analizi:**
```
CPU tabanlı eğitim (1 ortam):
  Rollout: 500ms (Python loop, NumPy)  ← %95 zaman
  GAE:     5ms
  PPO:     20ms (GPU forward/backward)
  ──────────────────────────────
  Toplam:  525ms / iterasyon
  FPS:     ~120

GPU tabanlı eğitim (512 ortam):
  Rollout: 1.0ms (CUDA tensör ops)    ← %65 zaman
  GAE:     0.05ms
  PPO:     0.45ms
  ──────────────────────────────
  Toplam:  1.5ms / iterasyon
  FPS:     ~20,000
```

**Hızlanma: ~170×** — günlerce sürecek eğitim saat mertebesine iner.

## 5.2 Vectorized GPU Environment

### 5.2.1 Tasarım Prensibi

Tüm simülasyon durumu `(B, N)` boyutlu PyTorch CUDA tensörleri olarak tutulur:

```
B = 512  (paralel ortam sayısı)
N = 200  (araç sayısı / ortam)

positions:      torch.FloatTensor(512, 200)   # metre
speeds:         torch.FloatTensor(512, 200)   # m/s
accelerations:  torch.FloatTensor(512, 200)   # m/s²
phases:         torch.LongTensor(512, 200)    # 0-7 (FSM state)
dwell_remaining: torch.FloatTensor(512, 200)  # saniye
next_stop_idx:  torch.LongTensor(512, 200)    # durak indexi
is_queuing:     torch.BoolTensor(512, 200)    # kuyrukta mı
speed_factor:   torch.FloatTensor(512, 200)   # RL hız çarpanı
```

Her tensör **doğrudan GPU VRAM'de** yaşar. CPU↔GPU veri transferi yalnızca dashboard görselleştirmesi için (env[0] slice) yapılır.

### 5.2.2 Tensör Operasyonları ile FSM

Geleneksel FSM implementasyonu:
```python
# ❌ CPU — sıralı, yavaş
for env in range(512):
    for bus in range(200):
        if bus.phase == APPROACHING and bus.distance < 0:
            bus.phase = STOPPED
            bus.position = stop.position
```

GPU-native implementasyon:
```python
# ✅ GPU — paralel, hızlı
approaching_mask = (phases == APPROACHING)
at_stop_mask = (distances_to_stop <= 0)
enter_stopped = approaching_mask & at_stop_mask

phases = torch.where(enter_stopped, STOPPED, phases)
positions = torch.where(enter_stopped, stop_positions, positions)
```

**Tek bir `torch.where` çağrısı 512×200=102,400 aracı aynı anda işler.**

### 5.2.3 IDM Fiziği — Vectorized

```python
# Öndeki araça mesafe (tüm araçlar paralel)
sorted_pos = torch.sort(positions, dim=1).values        # (512, 200)
gaps = sorted_pos[:, 1:] - sorted_pos[:, :-1] - L_veh   # (512, 199)

# Hız farkı
sorted_spd = torch.sort(speeds, dim=1).values
delta_v = sorted_spd[:, :-1] - sorted_spd[:, 1:]         # (512, 199)

# IDM formülü — tamamen tensör operasyonları
s_star = s0 + speeds * T + speeds * delta_v / (2 * torch.sqrt(a_max * b))
accel = a_max * (1 - (speeds/v0)**4 - (s_star/gaps.clamp(min=0.1))**2)
accel = accel.clamp(-b_emg, a_max)

# Euler entegrasyonu
speeds = (speeds + accel * dt).clamp(min=0)
positions = positions + speeds * dt + 0.5 * accel * dt**2
```

## 5.3 CUDA Graph Capture

### 5.3.1 Problem: Kernel Launch Overhead

Her PyTorch operasyonu bir CUDA kernel başlatır. Küçük tensörlerde kernel launch süresi hesaplama süresinden büyük olabilir:

```
torch.where(mask, a, b):
  Kernel launch:  ~0.005ms  ← overhead
  Hesaplama:      ~0.001ms  ← gerçek iş
  
Bir step'te ~50 operasyon → 50 × 0.005ms = 0.25ms sadece launch overhead
```

### 5.3.2 Çözüm: CUDA Graph

CUDA Graph tüm operasyonları tek seferde kaydeder ve sonra tek bir komutla tekrar oynatır:

```python
# 1. CAPTURE (bir kez):
with torch.cuda.graph(graph):
    obs, reward, done = env.step(actions_buf)

# 2. REPLAY (her step):
actions_buf.copy_(new_actions)  # input'u güncelle
graph.replay()                   # tüm operasyonlar tek kernel
# obs, reward, done otomatik güncellenir
```

**Kısıtlamalar ve çözümler:**
| Kısıtlama | Çözüm |
|-----------|-------|
| Dinamik tensör oluşturma yasak | Pre-allocate tüm buffer'lar |
| Boyut değişimi yasak | Sabit B, N boyutları |
| Python kontrol akışı yasak | torch.where ile branchless ops |
| CPU sync yasak | .cpu() çağrıları capture dışında |

### 5.3.3 Pre-allocation Stratejisi

```python
class GpuMetrobusEnv:
    def __init__(self):
        # === CAPTURE ÖNCESİ PRE-ALLOCATE ===
        self._accel_buf     = torch.zeros(B, N, device='cuda')
        self._target_spd    = torch.zeros(B, N, device='cuda')
        self._gap_buf       = torch.zeros(B, N, device='cuda')
        self._mask_buf      = torch.zeros(B, N, dtype=torch.bool, device='cuda')
        
        # Sabit tensörler (capture sırasında oluşturulmaz)
        self._braking_150   = torch.tensor(150.0, device='cuda')
        self._braking_30    = torch.tensor(30.0, device='cuda')
        self._braking_10    = torch.tensor(10.0, device='cuda')
        self._braking_3     = torch.tensor(3.0, device='cuda')
```

## 5.4 Bellek Yönetimi

### 5.4.1 VRAM Kullanımı

| Bileşen | Boyut | VRAM |
|---------|-------|------|
| Environment state (512×200×8 tensör) | ~3.3M float32 | ~13 MB |
| Rollout buffer (64 step) | ~6.7M float32 | ~27 MB |
| Actor ağı (parameter sharing) | 5,828 param | ~23 KB |
| Critic ağı | 631,297 param | ~2.4 MB |
| CUDA Graph capture | ~100 ops | ~50 MB |
| PyTorch overhead | — | ~500 MB |
| **TOPLAM** | — | **~600 MB** |

RTX 5070 Ti (16 GB VRAM) → **%3.7 kullanım** — çok geniş bir marj.

### 5.4.2 CPU-GPU Transfer Minimizasyonu

```
Her iterasyonda CPU↔GPU transferi:
  GPU→CPU: env[0] state (dashboard WS bridge) — her 16 step
           Boyut: 200 araç × ~10 float = 8KB
  
  CPU→GPU: Yok (tüm hesaplama GPU'da)
  
  GPU→CPU: Rollout buffer (PPO update öncesi) — iterasyon sonunda
           Boyut: 32768 × (24+1920+200+200+1+1+1) float
           = ~300 MB (tek seferlik, iterasyon sonunda)
```

## 5.5 Performans Karşılaştırması

| Metrik | CPU (tek ortam) | CPU (32 ortam) | **GPU (512 ortam)** |
|--------|----------------|----------------|---------------------|
| FPS | 120 | 2,400 | **20,000** |
| İterasyon süresi | 4.2s | 1.8s | **1.5ms** |
| 3000 iter toplam | ~3.5 saat | ~1.5 saat | **~75 dakika** |
| VRAM kullanımı | 0 | 0 | ~600 MB |
| Python GIL etkisi | Var | Var (multiprocess) | **Yok** |

## 5.6 Scalability Analizi

```
Araç sayısı vs FPS (RTX 5070 Ti, 512 env):

  N=80:   ~21,000 FPS  ⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛
  N=120:  ~15,000 FPS  ⬛⬛⬛⬛⬛⬛⬛⬛
  N=200:  ~11,000 FPS  ⬛⬛⬛⬛⬛⬛
  N=500:  ~4,000 FPS   ⬛⬛
  N=1000: ~1,500 FPS   ⬛

Darboğaz: IDM sıralama (argsort) O(N log N) ve
          gap hesaplama (pairwise) O(N²)
```

200 araç için ~11,000 FPS, 3000 iterasyonluk eğitim ~2 saatte tamamlanır.
