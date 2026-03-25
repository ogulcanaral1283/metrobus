# Metrobüs MAPPO Eğitim Rehberi — Kapsamlı Yol Haritası

## Büyük Resim

Eğitim süreci 6 ana aşamadan oluşuyor. Her birini sırayla yapacaksın.

```
┌────────────┐   ┌────────────┐   ┌────────────┐
│ AŞAMA 1    │   │ AŞAMA 2    │   │ AŞAMA 3    │
│ Ortam Kur  │──▶│ Environment│──▶│ Sinir Ağı  │
│ (pip, venv)│   │ Yaz        │   │ Tasarla    │
└────────────┘   └────────────┘   └────────────┘
                                        │
┌────────────┐   ┌────────────┐   ┌─────▼──────┐
│ AŞAMA 6    │   │ AŞAMA 5    │   │ AŞAMA 4    │
│ Görsel-    │◀──│ Değerlendir│◀──│ Eğitimi    │
│ leştir     │   │ ve Ayarla  │   │ Çalıştır   │
└────────────┘   └────────────┘   └────────────┘
```

---

## AŞAMA 1: Python Ortamını Kur

### 1.1 Virtual Environment (Sanal Ortam) Oluştur

Sanal ortam, projenin kütüphanelerini sistemden izole eder.
Böylece farklı projeler birbirini etkilemez.

```bash
# training klasörüne git
cd metrobus-project/training

# Sanal ortam oluştur
python -m venv venv

# Aktif et
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Aktif olduğunu anlarsın çünkü terminalde (venv) yazar
```

### 1.2 Gerekli Kütüphaneleri Kur

```bash
pip install torch              # Sinir ağı kütüphanesi (PyTorch)
pip install gymnasium          # RL ortam standardı (eski adı OpenAI Gym)
pip install numpy              # Sayısal hesaplamalar
pip install tensorboard        # Eğitim grafiklerini izlemek için
pip install pyyaml             # Ayar dosyalarını okumak için
pip install matplotlib         # Grafik çizmek için
pip install onnx onnxruntime   # Modeli dışa aktarmak için (TS tarafına)
```

### 1.3 PyTorch GPU Kontrolü

RTX 5070 Ti'ın var, eğitimi GPU'da çalıştırmak büyük hız farkı yaratır.

```python
import torch
print(torch.cuda.is_available())       # True olmalı
print(torch.cuda.get_device_name(0))   # RTX 5070 Ti yazmalı
```

Eğer False dönerse, PyTorch'u CUDA destekli olarak yeniden kurman gerekir:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

---

## AŞAMA 2: Gymnasium Environment Yaz

Bu en kritik aşama. Simülasyonunu Python'da yeniden oluşturup
Gymnasium'un beklediği formata sokacaksın.

### 2.1 Gymnasium Nedir?

Gymnasium (eski adı OpenAI Gym), RL algoritmalarının ortamla
konuşması için bir standart. Her ortam şu 4 fonksiyonu sağlar:

```
__init__()    → Ortamı oluştur, parametreleri ayarla
reset()       → Her şeyi başa al, ilk gözlemi döndür
step(action)  → Aksiyonu uygula, bir adım ilerle, sonucu döndür
_get_obs()    → Mevcut durumdan gözlem vektörü oluştur
```

### 2.2 Dosya Yapısı

```
training/
└── env/
    ├── __init__.py            ← Boş dosya (Python paketi yapmak için)
    ├── metrobus_env.py        ← Ana ortam sınıfı
    ├── bus.py                 ← Otobüs sınıfı + IDM fizik
    ├── stop.py                ← Durak sınıfı
    ├── route.py               ← Hat geometrisi yönetimi
    └── demand.py              ← Yolcu talep profili üretici
```

### 2.3 bus.py — Otobüs Sınıfı

Bu sınıf TS tarafındaki otobüs sınıfının Python karşılığı.
Görsel kısımları (render, canvas, animasyon) tamamen at.
Sadece fizik ve durum bilgisi kalsın.

İçermesi gerekenler:

```
Bus sınıfı:
├── Özellikler (properties):
│   ├── position        → Hattaki konum (metre cinsinden)
│   ├── speed           → Anlık hız (m/s)
│   ├── acceleration    → Anlık ivme (m/s²)
│   ├── direction       → Yön (0: ileri, 1: geri)
│   ├── current_stop    → Şu an hangi durakta (None ise yolda)
│   ├── dwell_timer     → Durakta ne kadar bekledi (saniye)
│   ├── last_dwell_time → Son durakta toplam bekleme süresi
│   └── passengers      → Tahmini yolcu sayısı (opsiyonel)
│
├── Metodlar:
│   ├── update(dt, lead_bus)
│   │   → IDM formülüyle hız ve konum güncelle
│   │   → dt: zaman adımı (sabit, mesela 0.5 saniye)
│   │   → lead_bus: öndeki otobüs (mesafe hesabı için)
│   │
│   ├── idm_acceleration(lead_distance, lead_speed)
│   │   → IDM formülü:
│   │   → a_idm = a_max * [1 - (v/v0)^4 - (s*/s)^2]
│   │   → s* = s0 + v*T + (v*dv)/(2*sqrt(a_max*b))
│   │   → Bu formül TS kodunda zaten var, aynen al
│   │
│   ├── arrive_at_stop(stop)
│   │   → Durağa vardığında çağrılır
│   │   → Hızı sıfırla, dwell_timer başlat
│   │
│   └── depart_from_stop()
│       → Duraktan kalkış
│       → last_dwell_time'ı kaydet
│       → dwell_timer'ı sıfırla

IDM Parametreleri (TS'den aynen al):
├── v0      → İstenen hız (desired speed), muhtemelen 70-80 km/s
├── s0      → Minimum mesafe (minimum gap), muhtemelen 2-5 metre
├── T       → Güvenli takip süresi (time headway), muhtemelen 1.5 sn
├── a_max   → Maksimum ivme, muhtemelen 1.0-2.0 m/s²
└── b       → Rahat frenleme ivmesi, muhtemelen 2.0-3.0 m/s²
```

### 2.4 stop.py — Durak Sınıfı

```
Stop sınıfı:
├── Özellikler:
│   ├── name            → Durak adı ("Cevizlibağ", "Merter" vb.)
│   ├── position        → Hattaki konum (metre)
│   ├── latitude        → Enlem (GPS)
│   ├── longitude       → Boylam (GPS)
│   ├── base_dwell_time → Temel bekleme süresi (saniye)
│   ├── demand_level    → Yoğunluk seviyesi (talep profilinden gelir)
│   └── stop_radius     → Durağın etki alanı (metre, geofence için)
│
├── Metodlar:
│   ├── get_dwell_time(hour, day_of_week)
│   │   → Saate ve güne göre bekleme süresi hesapla
│   │   → Talep profilinden yoğunluk çarpanını al
│   │   → base_dwell_time * çarpan + rastgele gürültü
│   │
│   └── is_bus_in_range(bus_position)
│       → Otobüs durağın etki alanında mı?
```

### 2.5 route.py — Hat Geometrisi

```
Route sınıfı:
├── Özellikler:
│   ├── stops           → Durak listesi (sıralı)
│   ├── total_length    → Hattın toplam uzunluğu (metre)
│   └── geometry_points → Hat geometrisi noktaları (OSM'den)
│
├── Metodlar:
│   ├── load_from_json(filepath)
│   │   → data/route_geometry.json dosyasını oku
│   │
│   ├── get_next_stop(bus)
│   │   → Otobüsün bir sonraki durağı hangisi
│   │
│   └── get_distance_between(pos1, pos2)
│       → İki nokta arası hat üzerindeki mesafe
```

### 2.6 demand.py — Yolcu Talep Profili

Bu TS tarafında yok, yeni yazacaksın. Amacı:
her durak için saate göre ne kadar yolcu geldiğini belirlemek.

```
DemandProfile sınıfı:
├── Her durak için saatlik yoğunluk çarpanları:
│
│   Örnek — Cevizlibağ:
│   saat_06: 0.3   (düşük)
│   saat_07: 0.7   (artıyor)
│   saat_08: 1.0   (pik)
│   saat_09: 0.6   (düşüyor)
│   ...
│
│   Örnek — Söğütlüçeşme (uç durak):
│   saat_08: 0.4   (sabah düşük, insanlar buradan binmiyor)
│   saat_18: 1.0   (akşam pik, insanlar eve dönüyor)
│
├── Metodlar:
│   ├── get_demand_multiplier(stop_name, hour, day_of_week)
│   │   → O durak için o saatteki yoğunluk çarpanını döndür
│   │   → Hafta sonu ise çarpanı %40 azalt
│   │
│   └── get_dwell_time(stop_name, hour, day_of_week)
│       → base_dwell_time * multiplier + random_noise
│       → random_noise: gerçekçilik için ±%15 rastgele sapma
│
│   Yolcu talep profillerini kendi metrobüs deneyiminden oluştur.
│   Hangi durak ne zaman kalabalık biliyorsun.
│   Bunu bir JSON dosyasına yazıp oradan oku.
```

### 2.7 metrobus_env.py — Ana Environment

Bu tüm parçaları birleştiren dosya. En önemli dosya.

```python
# Dosyanın genel yapısı (pseudocode — tam kod değil, mantığı gösteriyor):

import gymnasium as gym
import numpy as np

class MetrobusEnv(gym.Env):

    def __init__(self, config):
        """
        Ortamı oluştur.

        config içeriği:
          - num_buses: Kaç otobüs (mesela 20)
          - dt: Zaman adımı (mesela 0.5 saniye)
          - episode_length: Bir bölüm kaç adım (mesela 3600 = 30dk)
          - hour: Simülasyonun başladığı saat
          - day: Haftanın günü
        """
        self.num_buses = config['num_buses']
        self.dt = config['dt']
        self.max_steps = config['episode_length']

        # Hat ve durakları yükle
        self.route = Route.load_from_json('data/route_geometry.json')
        self.demand = DemandProfile.load_from_json('data/demand_profiles.json')

        # Observation space tanımla
        # Her otobüs için 7 değer:
        obs_size = 7
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0,
            shape=(self.num_buses, obs_size),
            dtype=np.float32
        )

        # Action space tanımla
        # Her otobüs 4 aksiyondan birini seçer
        self.action_space = gym.spaces.MultiDiscrete(
            [4] * self.num_buses
        )

    def reset(self):
        """
        Simülasyonu başa al.

        - Otobüsleri hatta eşit aralıklarla yerleştir
        - Saati ayarla
        - Adım sayacını sıfırla
        - İlk gözlemi döndür
        """
        self.current_step = 0
        self.current_time = self.config['hour'] * 3600  # saniyeye çevir

        # Otobüsleri eşit aralıklarla yerleştir
        spacing = self.route.total_length / self.num_buses
        self.buses = []
        for i in range(self.num_buses):
            bus = Bus(
                bus_id=i,
                position=i * spacing,
                speed=0.0,
                direction=0  # hepsi aynı yönde başlasın
            )
            self.buses.append(bus)

        return self._get_obs(), {}  # gözlem ve boş info dict

    def step(self, actions):
        """
        Bir adım ilerle. Bu fonksiyon eğitimin kalbi.

        Parametre:
          actions: her otobüs için bir aksiyon listesi
                   [2, 0, 1, 3, ...] gibi

        Döndürür:
          obs:        yeni gözlem
          reward:     ödül değeri
          terminated: bölüm bitti mi
          truncated:  zaman aşımı mı oldu
          info:       ekstra bilgiler (loglama için)
        """

        # 1. Aksiyonları uygula
        for i, bus in enumerate(self.buses):
            action = actions[i]

            if action == 0:     # Normal dur
                pass            # Bir şey yapma, normal davran
            elif action == 1:   # Durağı atla
                bus.skip_next_stop = True
            elif action == 2:   # Yavaşla (holding)
                bus.holding = True
                bus.holding_time = 10  # 10 saniye ekstra bekle
            elif action == 3:   # Hızlan
                bus.speed_multiplier = 1.2

        # 2. Simülasyonu dt kadar ilerlet
        self._simulate_step()

        # 3. Reward hesapla
        reward = self._calculate_reward()

        # 4. Zamanı güncelle
        self.current_step += 1
        self.current_time += self.dt

        # 5. Bölüm bitti mi kontrol et
        terminated = False
        truncated = self.current_step >= self.max_steps

        # 6. Yeni gözlemi al
        obs = self._get_obs()

        # 7. Loglama için ekstra bilgi
        info = {
            'headway_std': self._calculate_headway_std(),
            'avg_speed': np.mean([b.speed for b in self.buses]),
            'skipped_stops': sum(1 for b in self.buses if b.skip_next_stop)
        }

        return obs, reward, terminated, truncated, info

    def _simulate_step(self):
        """
        Fizik motorunu bir adım çalıştır.
        TS tarafındaki update döngüsünün Python karşılığı.
        """
        for i, bus in enumerate(self.buses):
            # Öndeki otobüsü bul
            lead_bus = self._get_lead_bus(i)

            # IDM ile hız ve konum güncelle
            bus.update(self.dt, lead_bus)

            # Durağa yaklaşma kontrolü
            next_stop = self.route.get_next_stop(bus)
            if next_stop and next_stop.is_bus_in_range(bus.position):
                if bus.skip_next_stop:
                    bus.skip_next_stop = False  # Atla ve devam et
                elif bus.current_stop is None:
                    # Durağa var, beklemeye başla
                    dwell = self.demand.get_dwell_time(
                        next_stop.name,
                        self.current_time / 3600,  # saate çevir
                        self.config['day']
                    )
                    bus.arrive_at_stop(next_stop, dwell)

            # Durakta bekleme süresini kontrol et
            if bus.current_stop is not None:
                bus.dwell_timer += self.dt
                if bus.dwell_timer >= bus.target_dwell_time:
                    bus.depart_from_stop()

    def _get_obs(self):
        """
        Her otobüs için gözlem vektörü oluştur.
        Tüm değerler 0-1 arasında normalize edilmeli.

        Neden normalize? Sinir ağları 0-1 arasındaki değerlerle
        çok daha iyi öğrenir. Büyük sayılar (800 metre gibi)
        gradientleri bozar.
        """
        obs = np.zeros((self.num_buses, 7), dtype=np.float32)

        for i, bus in enumerate(self.buses):
            lead_bus = self._get_lead_bus(i)
            follow_bus = self._get_follow_bus(i)

            obs[i] = [
                # 1. Hattaki pozisyon (0-1 arası)
                bus.position / self.route.total_length,

                # 2. Hız (0-1 arası, max hıza böl)
                bus.speed / bus.v0,

                # 3. Öndeki otobüse mesafe (0-1 arası)
                # Mesafeyi max olası mesafeye böl
                self._distance_to(bus, lead_bus) / self.route.total_length
                    if lead_bus else 1.0,

                # 4. Arkadaki otobüse mesafe (0-1 arası)
                self._distance_to(follow_bus, bus) / self.route.total_length
                    if follow_bus else 1.0,

                # 5. Son durakta bekleme süresi (0-1 arası)
                # Max bekleme süresine böl (mesela 120 saniye)
                min(bus.last_dwell_time / 120.0, 1.0),

                # 6. Günün saati — sin encoding
                # Neden sin/cos? Çünkü saat 23:59 ve 00:01 birbirine
                # yakın olmalı. Normal sayı olarak 23 ve 0 çok uzak görünür.
                # sin/cos ile dairesel yapıyı koruruz.
                np.sin(2 * np.pi * (self.current_time / 86400)),

                # 7. Günün saati — cos encoding
                np.cos(2 * np.pi * (self.current_time / 86400)),
            ]

        return obs

    def _calculate_reward(self):
        """
        Reward (ödül) fonksiyonu. Eğitimin yönünü belirler.
        Yanlış reward = yanlış öğrenme. Bu yüzden dikkatli tasarla.
        """
        reward = 0.0

        # --- BÖLÜM 1: Headway Düzgünlüğü (ana ödül) ---
        # Headway: ardışık iki otobüs arasındaki zaman farkı
        # İdeal: tüm otobüsler eşit aralıklı
        # Ölçüm: headway'lerin standart sapması
        # Düşük standart sapma = düzgün aralık = iyi

        headways = []
        for i in range(len(self.buses) - 1):
            dist = self._distance_to(self.buses[i], self.buses[i+1])
            avg_speed = max((self.buses[i].speed + self.buses[i+1].speed) / 2, 0.1)
            headway = dist / avg_speed
            headways.append(headway)

        if headways:
            headway_std = np.std(headways)
            ideal_headway = np.mean(headways)

            # Standart sapma düşükse ödül yüksek
            # cv = coefficient of variation (değişim katsayısı)
            # Standart sapmayı ortalamaya bölerek normalize ediyoruz
            if ideal_headway > 0:
                cv = headway_std / ideal_headway
                reward += max(1.0 - cv, -1.0) * 10.0
                # cv = 0 ise (mükemmel): +10
                # cv = 0.5 ise: +5
                # cv = 1.0 ise: 0
                # cv > 1.0 ise: negatif (ceza)

        # --- BÖLÜM 2: Bus Bunching Cezası ---
        # İki otobüs birbirine çok yaklaşmışsa büyük ceza
        for i in range(len(self.buses) - 1):
            dist = self._distance_to(self.buses[i], self.buses[i+1])
            if dist < 100:  # 100 metreden yakınsa
                reward -= 5.0  # Ağır ceza
            elif dist < 200:
                reward -= 2.0  # Uyarı cezası

        # --- BÖLÜM 3: Durak Atlama Cezası ---
        # Her atlanan durak için küçük ceza
        # Çok atlarsa yolcular mağdur olur
        for bus in self.buses:
            if bus.skip_next_stop:
                reward -= 1.0

        # --- BÖLÜM 4: Aşırı Bekleme Cezası ---
        # Bir durakta 90 saniyeden fazla beklemek kötü
        for bus in self.buses:
            if bus.current_stop and bus.dwell_timer > 90:
                reward -= 0.5

        # --- BÖLÜM 5: Ortalama Hız Bonusu ---
        # Otobüslerin makul hızda gitmesi iyi
        avg_speed = np.mean([b.speed for b in self.buses])
        target_speed = 40 / 3.6  # 40 km/s hedef, m/s'ye çevir
        speed_diff = abs(avg_speed - target_speed) / target_speed
        reward += max(1.0 - speed_diff, 0) * 2.0

        return reward

    def _get_lead_bus(self, bus_index):
        """Verilen otobüsün önündeki otobüsü bul."""
        # Aynı yöndeki bir sonraki otobüs
        # Dairesel hat ise modüler aritmetik kullan
        pass  # TS'deki mantığı buraya çevir

    def _get_follow_bus(self, bus_index):
        """Verilen otobüsün arkasındaki otobüsü bul."""
        pass  # TS'deki mantığı buraya çevir

    def _distance_to(self, bus1, bus2):
        """İki otobüs arasındaki hat üzerindeki mesafe."""
        pass  # TS'deki mantığı buraya çevir

    def _calculate_headway_std(self):
        """Loglama için headway standart sapması."""
        pass
```

### 2.8 Environment'ı Test Et

Eğitime başlamadan önce ortamın düzgün çalıştığından emin ol.

```python
# test_env.py

from env.metrobus_env import MetrobusEnv

config = {
    'num_buses': 10,
    'dt': 0.5,
    'episode_length': 7200,  # 7200 adım × 0.5sn = 1 saat
    'hour': 8,               # Sabah 8'de başla
    'day': 0                 # Pazartesi
}

env = MetrobusEnv(config)
obs, info = env.reset()

print(f"Gözlem şekli: {obs.shape}")        # (10, 7) olmalı
print(f"İlk gözlem:\n{obs}")

# 100 adım rastgele aksiyonla çalıştır
total_reward = 0
for step in range(100):
    # Rastgele aksiyonlar üret
    actions = [np.random.randint(0, 4) for _ in range(10)]
    obs, reward, terminated, truncated, info = env.step(actions)
    total_reward += reward

    if step % 20 == 0:
        print(f"Adım {step}: reward={reward:.2f}, "
              f"headway_std={info['headway_std']:.2f}, "
              f"avg_speed={info['avg_speed']:.1f} m/s")

print(f"\nToplam reward: {total_reward:.2f}")

# Bu test şunları doğrular:
# ✓ Environment hata vermeden çalışıyor
# ✓ Gözlem boyutu doğru
# ✓ Reward değerleri makul aralıkta
# ✓ Otobüsler hareket ediyor (avg_speed > 0)
```

---

## AŞAMA 3: MAPPO Sinir Ağlarını Tasarla

### 3.1 Actor Ağı (Karar Veren)

```
Girdi: Gözlem vektörü (7 değer — tek bir otobüsün gördükleri)
Çıktı: 4 aksiyonun olasılıkları

Yapı:
┌─────────────────────────────────────────────────┐
│                  ACTOR AĞI                      │
│                                                 │
│  Girdi (7)                                      │
│    │                                            │
│    ▼                                            │
│  Gizli Katman 1 (64 nöron) + ReLU               │
│    │                                            │
│    ▼                                            │
│  Gizli Katman 2 (64 nöron) + ReLU               │
│    │                                            │
│    ▼                                            │
│  Çıktı Katmanı (4 nöron) + Softmax              │
│    │                                            │
│    ▼                                            │
│  [Dur: 0.15, Atla: 0.55, Yavaşla: 0.25,        │
│   Hızlan: 0.05]                                 │
└─────────────────────────────────────────────────┘

Neden 64 nöron?
  Çok küçük (16) → yeterince öğrenemez
  Çok büyük (512) → gereksiz yavaş, overfitting riski
  64 bu problem için iyi bir başlangıç

Neden ReLU?
  ReLU = max(0, x) — en yaygın aktivasyon fonksiyonu
  Basit, hızlı, iyi çalışıyor

Neden Softmax?
  Çıktıları olasılığa çevirir (toplamı 1 yapar)
  [2.1, 3.5, 1.8, 0.3] → [0.15, 0.55, 0.25, 0.05]
```

### 3.2 Critic Ağı (Değerlendiren)

```
Girdi: Global durum (TÜM otobüslerin gözlemleri birleşik)
       7 değer × 20 otobüs = 140 değer
Çıktı: Tek bir sayı — "bu durum ne kadar iyi"

Yapı:
┌─────────────────────────────────────────────────┐
│                 CRITIC AĞI                      │
│                                                 │
│  Girdi (140 — tüm otobüslerin gözlemleri)       │
│    │                                            │
│    ▼                                            │
│  Gizli Katman 1 (128 nöron) + ReLU              │
│    │                                            │
│    ▼                                            │
│  Gizli Katman 2 (128 nöron) + ReLU              │
│    │                                            │
│    ▼                                            │
│  Çıktı Katmanı (1 nöron) — aktivasyon yok       │
│    │                                            │
│    ▼                                            │
│  Değer: 42.7 (bu durum 42.7 puan değerinde)     │
└─────────────────────────────────────────────────┘

Neden 128 nöron?
  Critic daha fazla bilgi işliyor (140 girdi vs 7)
  Bu yüzden daha geniş bir ağ gerekli

Neden aktivasyon yok (çıktıda)?
  Değer herhangi bir sayı olabilir (-100, 0, +500...)
  Softmax veya sigmoid bunu sınırlar, istemiyoruz
```

### 3.3 Parameter Sharing (Parametre Paylaşımı)

Tüm otobüsler AYNI actor ağını paylaşır.

```
                    ┌──────────────────┐
                    │   TEK BİR ACTOR  │
                    │   SİNİR AĞI     │
                    └──────┬───────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     Otobüs #1'in   Otobüs #2'nin  Otobüs #20'nin
     gözlemi girir   gözlemi girir  gözlemi girir
            │              │              │
            ▼              ▼              ▼
     Otobüs #1'in   Otobüs #2'nin  Otobüs #20'nin
     aksiyonu çıkar  aksiyonu çıkar aksiyonu çıkar

Neden paylaşımlı?
  1. Tüm otobüsler aynı işi yapıyor (aynı hatta gidip gelme)
  2. Birinin öğrendiği diğerleri için de geçerli
  3. 20 ayrı ağ yerine 1 ağ eğitmek çok daha hızlı
  4. Daha az parametre = daha az veri ile öğrenme (sample efficient)
```

### 3.4 PyTorch Kodu — Ağ Yapıları

```python
# agents/networks.py

import torch
import torch.nn as nn
from torch.distributions import Categorical

class Actor(nn.Module):
    """
    Karar veren ağ.
    Bir otobüsün gözlemini alır, aksiyon olasılıklarını döndürür.
    """
    def __init__(self, obs_dim=7, action_dim=4, hidden_dim=64):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(obs_dim, hidden_dim),     # 7 → 64
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),  # 64 → 64
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim),  # 64 → 4
        )

    def forward(self, obs):
        logits = self.network(obs)              # Ham çıktılar
        dist = Categorical(logits=logits)       # Olasılık dağılımı
        return dist

    def get_action(self, obs):
        dist = self.forward(obs)
        action = dist.sample()            # Olasılıklara göre seç
        log_prob = dist.log_prob(action)   # Seçilen aksiyonun log olasılığı
        return action, log_prob

    def evaluate(self, obs, action):
        dist = self.forward(obs)
        log_prob = dist.log_prob(action)
        entropy = dist.entropy()           # Keşif ölçüsü
        return log_prob, entropy


class Critic(nn.Module):
    """
    Değerlendiren ağ.
    Global durumu alır, tek bir değer döndürür.
    """
    def __init__(self, global_obs_dim=140, hidden_dim=128):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(global_obs_dim, hidden_dim),   # 140 → 128
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),       # 128 → 128
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),                # 128 → 1
        )

    def forward(self, global_obs):
        return self.network(global_obs).squeeze(-1)
        # squeeze: [batch, 1] → [batch] boyutuna düşürür
```

---

## AŞAMA 4: MAPPO Eğitim Döngüsü

### 4.1 Rollout Buffer (Deneyim Deposu)

Eğitim sırasında simülasyondan toplanan verileri saklar.

```
RolloutBuffer ne saklar?

Her adım için:
┌─────────────────────────────────────────────────────────┐
│  observations     → Her otobüsün gözlemi               │
│  global_states    → Tüm otobüslerin birleşik gözlemi   │
│  actions          → Her otobüsün aldığı aksiyon         │
│  log_probs        → Her aksiyonun log olasılığı         │
│  rewards          → O adımdaki ödül                     │
│  values           → Critic'in o adım için tahmini       │
│  dones            → Bölüm bitti mi bilgisi              │
└─────────────────────────────────────────────────────────┘

Toplam boyut: adım_sayısı × otobüs_sayısı × değerler

Örnek: 2048 adım × 20 otobüs
  observations:  2048 × 20 × 7 = 286.720 değer
  actions:       2048 × 20     = 40.960 değer
  rewards:       2048           = 2.048 değer
  ...
```

### 4.2 GAE Hesabı (Generalized Advantage Estimation)

```
GAE, avantaj değerini hesaplar.
Geriye doğru çalışır (son adımdan ilk adıma).

Basit açıklama:
  Her adım için:
  δ = reward + γ × V(sonraki_durum) - V(şimdiki_durum)

  δ (delta): Temporal Difference error
  "Gerçekte olan ile beklenen arasındaki fark"

  Avantaj:
  A_t = δ_t + (γ × λ) × δ_{t+1} + (γ × λ)² × δ_{t+2} + ...

  γ (gamma) = 0.99: Gelecekteki ödüllere ne kadar değer veriyoruz
  λ (lambda) = 0.95: Avantaj tahmininin varyans-yanlılık dengesi

  λ = 0 → Sadece bir adım ileriye bak (yüksek yanlılık, düşük varyans)
  λ = 1 → Bölüm sonuna kadar bak (düşük yanlılık, yüksek varyans)
  λ = 0.95 → İyi bir denge

Python'da:
──────────
  advantages = []
  gae = 0
  for t in reversed(range(num_steps)):
      if t == num_steps - 1:
          next_value = 0
      else:
          next_value = values[t + 1]

      delta = rewards[t] + gamma * next_value - values[t]
      gae = delta + gamma * lam * gae
      advantages.insert(0, gae)

  # Returns = Advantages + Values
  # Critic'i eğitmek için kullanılır
  returns = advantages + values
```

### 4.3 PPO Güncelleme Adımı

```
Her güncelleme döngüsünde şu olur:

1. Rollout buffer'daki veriyi K epoch boyunca kullan
2. Her epoch'ta veriyi mini-batch'lere böl
3. Her mini-batch için:

   a) Actor'dan yeni log_prob ve entropy al:
      new_log_prob, entropy = actor.evaluate(obs, action)

   b) Oranı hesapla:
      ratio = exp(new_log_prob - old_log_prob)

      Neden exp? Log olasılıklar negatif sayılar.
      exp ile gerçek orana çeviriyoruz.
      log(0.3) = -1.2, log(0.36) = -1.02
      exp(-1.02 - (-1.2)) = exp(0.18) = 1.2 → oran 1.2

   c) Kırpılmış oranı hesapla:
      clipped_ratio = clamp(ratio, 1-ε, 1+ε)

   d) Policy kaybı:
      loss1 = ratio × advantage
      loss2 = clipped_ratio × advantage
      policy_loss = -min(loss1, loss2).mean()

      Neden negatif? PyTorch minimize eder.
      Biz maximize etmek istiyoruz.
      Negatifini minimize etmek = kendisini maximize etmek.

   e) Value kaybı:
      value_loss = (critic(global_state) - returns)².mean()

   f) Entropy kaybı:
      entropy_loss = -entropy.mean()

   g) Toplam kayıp:
      total_loss = policy_loss + 0.5 × value_loss + 0.01 × entropy_loss

   h) Gradientleri hesapla ve ağırlıkları güncelle:
      optimizer.zero_grad()
      total_loss.backward()
      # Gradient clipping — gradientlerin çok büyümesini engeller
      nn.utils.clip_grad_norm_(parameters, max_norm=0.5)
      optimizer.step()
```

### 4.4 Tam Eğitim Akışı

```
train.py — Ana eğitim scripti

AŞAMA 1: Hazırlık
  - Config dosyasını oku (hyperparams.yaml)
  - Environment oluştur
  - Actor ve Critic ağlarını oluştur
  - Optimizer oluştur (Adam)
  - TensorBoard logger başlat

AŞAMA 2: Ana Döngü (N iterasyon tekrarla)
  │
  ├── 2a. Veri Topla (Rollout)
  │   │   Mevcut policy ile simülasyonu çalıştır
  │   │   Her adımda kaydet: obs, action, reward, value, log_prob
  │   │   2048 adım topla (veya 1 bölüm bitene kadar)
  │   │
  │   │   for step in range(2048):
  │   │       actions, log_probs = actor.get_action(obs)
  │   │       values = critic(global_obs)
  │   │       obs, reward, done, truncated, info = env.step(actions)
  │   │       buffer.store(obs, actions, reward, values, log_probs, done)
  │   │       if done or truncated:
  │   │           obs = env.reset()
  │   │
  ├── 2b. Avantaj Hesapla (GAE)
  │   │   Buffer'daki verilerle avantajları hesapla
  │   │   advantages = compute_gae(rewards, values, dones, gamma, lambda)
  │   │   returns = advantages + values
  │   │
  ├── 2c. Ağları Güncelle (PPO Update)
  │   │   K epoch boyunca:
  │   │     Mini-batch'lere böl
  │   │     Her mini-batch için:
  │   │       Oran hesapla, kırp, kayıp hesapla, güncelle
  │   │     (Detaylar yukarıdaki 4.3'te)
  │   │
  ├── 2d. Logla
  │   │   TensorBoard'a yaz:
  │   │     - Ortalama reward
  │   │     - Policy loss, value loss, entropy
  │   │     - Ortalama headway std
  │   │     - Ortalama hız
  │   │     - Durak atlama sayısı
  │   │
  └── 2e. Checkpoint Kaydet
      │   Her 50 iterasyonda bir modeli kaydet
      │   torch.save(actor.state_dict(), 'checkpoints/actor_iter_50.pt')
      │   torch.save(critic.state_dict(), 'checkpoints/critic_iter_50.pt')

AŞAMA 3: Eğitim Bitti
  - En iyi modeli seç (en yüksek ortalama reward)
  - ONNX formatına çevir (TS tarafı için)
  - Son değerlendirme çalıştır
```

### 4.5 Hiperparametreler

```yaml
# config/hyperparams.yaml

# --- Ortam ---
num_buses: 20              # Otobüs sayısı
dt: 0.5                    # Zaman adımı (saniye)
episode_length: 7200       # Bölüm uzunluğu (7200 × 0.5sn = 1 saat)

# --- PPO ---
learning_rate: 0.0003      # Öğrenme hızı (3e-4)
gamma: 0.99                # İndirim faktörü (gelecek ödül ağırlığı)
gae_lambda: 0.95           # GAE lambda
epsilon: 0.2               # Kırpma aralığı
epochs: 10                 # Her güncelleme için epoch sayısı (K)
batch_size: 2048           # Rollout uzunluğu
mini_batch_size: 64        # Mini-batch boyutu
entropy_coef: 0.01         # Entropi katsayısı (keşif teşviki)
value_coef: 0.5            # Value loss katsayısı
max_grad_norm: 0.5         # Gradient kırpma normu

# --- Ağ ---
actor_hidden: 64           # Actor gizli katman boyutu
critic_hidden: 128         # Critic gizli katman boyutu

# --- Eğitim ---
total_iterations: 5000     # Toplam iterasyon sayısı
checkpoint_interval: 50    # Her 50 iterasyonda kaydet
eval_interval: 100         # Her 100 iterasyonda değerlendir

# --- Reward ağırlıkları ---
headway_weight: 10.0       # Headway düzgünlüğü ödülü
bunching_penalty: -5.0     # Yapışma cezası
skip_penalty: -1.0         # Durak atlama cezası
long_dwell_penalty: -0.5   # Uzun bekleme cezası
speed_bonus_weight: 2.0    # Hız bonusu ağırlığı
```

---

## AŞAMA 5: Değerlendir ve Ayarla

### 5.1 TensorBoard ile İzleme

```bash
# Terminalde çalıştır
tensorboard --logdir=logs/

# Tarayıcıda aç: http://localhost:6006
```

TensorBoard'da şu grafikleri izle:

```
İzlemen gereken grafikler:

1. Reward Grafiği
   ────────────────
   İyi eğitim: Zamanla yukarı gider, sonra düzleşir
   Kötü eğitim: Düz kalır veya aşağı gider

   reward
    │              _______________
    │         ___─╱
    │      __╱
    │   __╱
    │  ╱
    │_╱
    └──────────────────────────▶ iterasyon
    İYİ ✅

    reward
    │
    │  ╲    ╱╲      ╱╲
    │   ╲  ╱  ╲    ╱  ╲    ╱
    │    ╲╱    ╲  ╱    ╲  ╱
    │          ╲╱      ╲╱
    └──────────────────────────▶ iterasyon
    KÖTÜ ❌ (kararsız, öğrenemiyor)


2. Headway Standart Sapması
   ─────────────────────────
   Aşağı gitmeli (otobüsler eşit aralığa yaklaşıyor)

3. Policy Loss
   ────────────
   Çok büyük dalgalanma → learning rate'i düşür
   Sıfıra yakın sabit → epsilon'u artır veya ağı büyüt

4. Entropy
   ────────
   Yavaşça düşmeli. Çok hızlı düşerse agent keşfi bıraktı,
   entropy_coef'i artır.
   Hiç düşmezse agent öğrenemiyor, ağ yapısını kontrol et.
```

### 5.2 Yaygın Sorunlar ve Çözümleri

```
SORUN: Reward hiç artmıyor
  ├── Reward fonksiyonunu kontrol et — scale'ler makul mü?
  ├── Environment'ta bug var mı? Test et.
  ├── Learning rate çok yüksek olabilir → 1e-4'e düşür
  └── Gözlemler düzgün normalize ediliyor mu?

SORUN: Reward artıyor ama sonra çöküyor
  ├── Epsilon'u düşür (0.2 → 0.1) — daha küçük adımlar
  ├── Learning rate'i düşür
  └── Gradient clipping'i kontrol et (max_norm=0.5)

SORUN: Agent hep aynı aksiyonu seçiyor
  ├── Entropy çok hızlı düşüyor → entropy_coef artır (0.01 → 0.05)
  ├── Reward fonksiyonu bir aksiyonu çok mu ödüllendiriyor?
  └── Action space doğru mu tanımlı?

SORUN: Eğitim çok yavaş
  ├── GPU kullanıldığından emin ol (torch.cuda.is_available())
  ├── Batch size artır (2048 → 4096)
  ├── Environment'ı hızlandır (gereksiz hesapları kaldır)
  └── Num_workers ile paralel ortam çalıştır (ileri seviye)
```

### 5.3 Reward Shaping İpuçları

```
Reward fonksiyonu eğitimin en çok deneme-yanılma gerektiren kısmı.
İlk seferde mükemmel olmaz, iteratif olarak geliştirirsin.

İpucu 1: Sparse vs Dense Reward
  Sparse (seyrek): Sadece bölüm sonunda ödül ver
    → Kötü! Agent neyin iyi olduğunu anlamakta zorlanır
  Dense (yoğun): Her adımda ödül ver
    → İyi! Agent her adımda geri bildirim alır
    → Senin reward fonksiyonun zaten dense, doğru yoldasın

İpucu 2: Reward Scale (Ölçeği)
  Reward değerleri çok büyükse (±1000) → ağ kararsızlaşır
  Çok küçükse (±0.001) → agent öğrenemez
  ±10 civarı iyi bir aralık

İpucu 3: Kademeli Zorluk
  İlk eğitimi 5 otobüsle yap (kolay)
  Öğrendikten sonra 10, 15, 20'ye çıkar
  Transfer learning — önceki modelden devam et
```

---

## AŞAMA 6: Modeli Dışa Aktar ve Görselleştir

### 6.1 ONNX'e Çevir

```python
# scripts/export_policy.py

import torch
from agents.networks import Actor

# Eğitilmiş modeli yükle
actor = Actor(obs_dim=7, action_dim=4)
actor.load_state_dict(torch.load('checkpoints/best_actor.pt'))
actor.eval()

# ONNX'e çevir
dummy_input = torch.randn(1, 7)  # Örnek girdi
torch.onnx.export(
    actor.network,          # Sadece network kısmı (Categorical hariç)
    dummy_input,
    'exports/actor_model.onnx',
    input_names=['observation'],
    output_names=['action_logits'],
    dynamic_axes={'observation': {0: 'batch_size'}}
)

print("Model ONNX olarak kaydedildi!")
```

### 6.2 TypeScript Tarafında Kullanma

```
TS tarafında ONNX Runtime Web kullan:
  npm install onnxruntime-web

Akış:
  1. actor_model.onnx dosyasını frontend'e koy
  2. Her simülasyon adımında:
     a. Otobüsün gözlemini al (7 değer)
     b. ONNX modeline ver
     c. Çıktıdaki en yüksek olasılıklı aksiyonu seç
     d. O aksiyonu uygula
  3. Harita üzerinde sonucu göster

Böylece eğitilmiş modelin kararlarını
canlı olarak harita üzerinde izleyebilirsin.
```

---

## EKSTRA: Eğitim Zaman Çizelgesi

```
Tahmini süre (tek başına çalışarak):

Hafta 1-2:  Environment'ı Python'a taşı ve test et
Hafta 3:    Actor/Critic ağlarını yaz
Hafta 4:    MAPPO eğitim döngüsünü yaz
Hafta 5-6:  İlk eğitimleri çalıştır, debug et
Hafta 7-8:  Reward fonksiyonunu ve hiperparametreleri ayarla
Hafta 9:    En iyi modeli seç, değerlendir
Hafta 10:   ONNX'e çevir, TS tarafında görselleştir

Not: Eğitimin kendisi (5000 iterasyon) RTX 5070 Ti'da
muhtemelen birkaç saat sürer. Asıl zaman
kodu yazmak ve debug etmekte geçer.
```

## EKSTRA: Kontrol Listesi

```
□ Python sanal ortam kuruldu
□ PyTorch GPU ile çalışıyor
□ bus.py — IDM fizik motoru Python'da çalışıyor
□ stop.py — Durak mekanizması çalışıyor
□ route.py — Hat geometrisi yükleniyor
□ demand.py — Talep profilleri oluşturuldu
□ metrobus_env.py — reset() çalışıyor
□ metrobus_env.py — step() çalışıyor
□ metrobus_env.py — _get_obs() normalize değerler veriyor
□ metrobus_env.py — reward fonksiyonu makul değerler veriyor
□ test_env.py — 1000 adım hatasız çalışıyor
□ Actor ağı tanımlı ve çalışıyor
□ Critic ağı tanımlı ve çalışıyor
□ GAE hesabı çalışıyor
□ PPO güncelleme adımı çalışıyor
□ TensorBoard logları yazılıyor
□ İlk eğitim başarıyla çalıştı
□ Reward grafiği artış gösteriyor
□ Headway std düşüş gösteriyor
□ Hiperparametre ayarlaması yapıldı
□ En iyi model checkpoint olarak kaydedildi
□ ONNX'e çevrildi
□ TS tarafında çalışıyor
```
