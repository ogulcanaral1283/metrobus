# 3. SİMÜLASYON ORTAMI (Simulation Environment)

## 3.1 Genel Bakış

Eğitim ortamı, İstanbul metrobüs hattının yüksek doğruluklu bir dijital ikizi (digital twin) olarak tasarlanmıştır. Gerçek dünya verilerinden türetilmiş rota geometrisi, fizik tabanlı araç dinamikleri ve stokastik yolcu talep modeli içerir.

```
┌────────────────────────────────────────────────────────────────┐
│                   SİMÜLASYON KATMANLARİ                        │
│                                                                │
│  [1] Rota Katmanı        OSM → Lineer metre bazlı hat         │
│  [2] Fizik Katmanı       IDM car-following + piecewise braking │
│  [3] Durak Katmanı       8-fazlı FSM + paralel peron          │
│  [4] Talep Katmanı       Stokastik yolcu geliş modeli         │
│  [5] Trafik Katmanı      Rastgele trafik bölgeleri             │
│  [6] Pertürbasyon        %0.3 olasılıkla ani yavaşlama        │
└────────────────────────────────────────────────────────────────┘
```

## 3.2 Rota Linearizasyonu

### 3.2.1 Veri Kaynağı: OpenStreetMap

Metrobüs hattının geometrisi OpenStreetMap Overpass API'den çekilmiştir:

```
Overpass Query:
  relation[name="Metrobüs"][type=route][route=bus];
  way(r); → ~3000 geometri noktası
  node[public_transport=stop_position]; → 44 durak noktası
  way[public_transport=platform]; → 44 platform geometrisi
```

**Elde edilen veriler:**
- **Edge geometrileri**: Hat boyunca [lat, lng] koordinat dizileri
- **Durak noktaları**: Her durağın GPS konumu (stop_position)
- **Platform geometrileri**: Her platformun başlangıç-bitiş noktaları ve uzunluğu

### 3.2.2 Haversine Linearizasyon

3D küresel koordinatlar (lat/lng) tek boyutlu metre bazlı doğrusal koordinat sistemine dönüştürülür:

$$d = 2R \cdot \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos\phi_1 \cdot \cos\phi_2 \cdot \sin^2\left(\frac{\Delta\lambda}{2}\right)}\right)$$

Burada $R = 6{,}371{,}000$ m (Dünya yarıçapı).

**İşlem:**
```
Segment 1:  (41.0219, 28.6249) → (41.0219, 28.6251)  →  d₁ = 15.2m
Segment 2:  (41.0219, 28.6251) → (41.0218, 28.6255)  →  d₂ = 32.1m
...
Segment N:  cumulative = Σdᵢ = 50,490m (toplam hat uzunluğu)
```

Her nokta için `(startMeter, endMeter, startLat, startLng, endLat, endLng, bearing)` kaydedilir.

### 3.2.3 Platform HEAD Alignment

Kritik bir detay: `stop.meterPosition` peronun **başını** (HEAD) göstermelidir — ilk aracın duracağı nokta.

**Problem:** OSM stop_position noktaları peronun ortasını veya girişini gösterebilir.

**Çözüm:** Platform entry koordinatları kullanılarak HEAD pozisyonu hesaplanır:

```
Gidiş yönü: Araçlar batıdan gelir → HEAD = peronun EN DOĞU ucu
  → Dönüş giriş noktas (donus_lat/lon) = Gidiş platform HEAD'i

Dönüş yönü: Araçlar doğudan gelir → HEAD = peronun EN BATI ucu
  → Gidiş giriş noktası (gidis_lat/lon) = Dönüş platform HEAD'i
```

Bu "karşı yön swap" mantığı hem TypeScript dashboard'da hem Python eğitim ortamında uygulanmıştır.

## 3.3 Araç Fiziği: Intelligent Driver Model (IDM)

### 3.3.1 Model Formülasyonu

Trafim (1995) ve Kesting et al. (2010) tarafından geliştirilen IDM, her aracın öndeki aracı takip etme davranışını modelleyen bir araç-takip modelidir:

$$a = a_{max} \left[ 1 - \left(\frac{v}{v_0}\right)^{\delta} - \left(\frac{s^*(v, \Delta v)}{s}\right)^2 \right]$$

**İstenen minimum takip mesafesi:**

$$s^*(v, \Delta v) = s_0 + v \cdot T + \frac{v \cdot \Delta v}{2\sqrt{a_{max} \cdot b}}$$

### 3.3.2 Parametre Kalibrasyonu

| Parametre | Sembol | Değer | Kaynak / Gerekçe |
|-----------|--------|-------|-------------------|
| Maks. ivmelenme | $a_{max}$ | 1.0 m/s² | Şehir içi otobüs konfor standardı |
| Konforlu frenleme | $b$ | 2.0 m/s² | Mercedes-Benz Citaro spec |
| Minimum boşluk | $s_0$ | 2.0 m | BRT güvenlik standardı |
| Zaman aralığı | $T$ | 1.5 s | AASHTO önerisi |
| IDM üssü | $\delta$ | 4 | Standart değer (Treiber, 2000) |
| Araç boyu | $L$ | 20.0 m | Mercedes-Benz Citaro G Ø articulated |
| Maks. hız | $v_{max}$ | 14.0 m/s | ~50 km/h (BRT limit) |
| Acil fren | $b_{emg}$ | 4.5 m/s² | Güvenlik sınırı |

### 3.3.3 Piecewise Frenleme Eğrisi

Durağa yaklaşma fiziği 4-fazlı parçalı doğrusal frenleme ile modellenmiştir (TypeScript simulasyondan reverse-engineered):

```
Mesafe (m)    Hız Çarpanı     Açıklama
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
150 → 30      1.0 → 0.5       Yumuşak yavaşlama (fase 1)
 30 → 10      0.5 → 0.2       Güçlü frenleme (faz 2)
 10 →  3      0.2 → 0.05      Sürünme (creep, faz 3)
  3 →  0      0.05 → 0        Tam durma (faz 4)
```

Bu eğri, gerçek metrobüs sürücü davranışını yansıtır — erken yavaşlama, peronun son 10 metresinde hassas pozisyonlama.

## 3.4 Durak Yönetimi: 8-Fazlı Sonlu Durum Makinesi (FSM)

### 3.4.1 Durum Diyagramı

```
CRUISING ──[dist < 150m]──→ APPROACHING
    ↑                            │
    │                     ┌──────┴──────┐
    │                     │             │
    │              [slot var]    [slot yok]
    │                     │             │
    │                  DOCKING        QUEUED
    │                     │             │
    │              [konuma ulaştı] [slot açıldı]
    │                     │             │
    │                     └──────┬──────┘
    │                            │
    │                         STOPPED
    │                 (yolcu operasyonu — dwell süresi)
    │                            │
    │                     [dwell = 0]
    │                            │
    │                      DOORS_CLOSED
    │                            │
    │                   ┌────────┴────────┐
    │                   │                 │
    │             [önde araç var]   [yol açık]
    │                   │                 │
    │                BLOCKED          DEPARTING
    │                   │                 │
    │             [önü açıldı]      [hız > 2 m/s]
    │                   │                 │
    │               DEPARTING        CRUISING
    │                   │                 ↗
    │             [hız > 2 m/s]──────────┘
    └──────────────────────────────────────┘
```

### 3.4.2 Paralel Peron Operasyonu

Gerçek metrobüs durakları birden fazla aracın **aynı anda** yolcu operasyonu yapmasına izin verir:

```
Platform (Cevizlibağ, 210m):
┌──────────────────────────────────────────────────────┐
│ SLOT 1         │ SLOT 2         │ SLOT 3             │
│ 🚌 M07        │ 🚌 M12        │ 🚌 M18            │
│ dwell: 15s    │ dwell: 8s     │ dwell: 22s         │
│ kapılar açık  │ kapılar açık  │ kapılar açık       │
└──────────────────────────────────────────────────────┘
│← 20m →│← gap →│← 20m →│← gap →│← 20m →│
         0.5m           0.5m
```

- **İlk araç** → platform HEAD'ine snap edilir
- **Sonraki araçlar** → öndeki aracın arkasına dizilir
- **Kapasite**: `slotCount = floor(platformLength / (vehicleLength + gap))`
- **Taşma**: Kapasite doluysa yeni araç **QUEUED** fazına geçer

### 3.4.3 Dwell Süresi Modeli

Durakta bekleme süresi stokastik olarak belirlenir:

$$\tau_{dwell} = \begin{cases}
\mathcal{U}(15, 35) \text{ sn} & \text{normal saat} \\
\mathcal{U}(20, 45) \text{ sn} & \text{rush hour}
\end{cases}$$

Rush hour tespiti: 07:00-09:30 veya 17:00-19:30 (simülasyon saati).

## 3.5 Stokastik Pertürbasyonlar

### 3.5.1 Rastgele Yavaşlama

Gerçek trafikte beklenmedik olayların (yolcu düşmesi, engel, vs.) etkisini simüle eder:

```
Her step, her araç için:
  P(ani yavaşlama) = 0.003  (%0.3)
  
  Eğer tetiklendi:
    speed *= 0.3     (hız %70 düşer)
    acceleration = -2.0 m/s²  (sert fren)
```

### 3.5.2 Trafik Bölgeleri

Hat üzerinde rastgele trafik yoğunluğu bölgeleri oluşturulur:

| Şiddet | Hız Limiti | Süre | Açıklama |
|--------|-----------|------|----------|
| Hafif | 8-10 m/s | 60-180s | Normal yoğunluk |
| Orta | 4-6 m/s | 120-300s | Trafik sıkışıklığı |
| Ağır | 1-2.5 m/s | 180-600s | Kaza/olay |

## 3.6 Simülasyon Doğrulama

Simülasyon ortamının gerçekçiliği şu yöntemlerle doğrulanmıştır:

1. **Geometrik doğrulama**: Lineerize edilmiş durak pozisyonları ← → Google Maps mesafe ölçümü karşılaştırması (±%2 hata)
2. **Fizik doğrulama**: IDM parametreleri ile üretilen hız profili ← → gerçek GPS verisi karşılaştırması
3. **FSM doğrulama**: TypeScript dashboard simülasyonu ile Python eğitim ortamının birebir senkronizasyonu
4. **Platform doğrulama**: Overpass API platform uzunlukları ← → Google Earth ölçümleri (±%5 hata)
