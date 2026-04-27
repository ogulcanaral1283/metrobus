# 6. GERÇEK ZAMANLI İZLEME SİSTEMİ (Real-Time Monitoring)

## 6.1 WebSocket Bridge Mimarisi

Eğitim sırasında GPU tensörlerinden canlı görselleştirme verisi üretilir ve WebSocket üzerinden dashboard'a aktarılır:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  GPU Env     │────→│ CPU Snapshot  │────→│ WS Server   │────→│ Dashboard    │
│  (CUDA)      │     │ (env[0])     │     │ (port 8765) │     │ (port 3001)  │
│              │     │              │     │              │     │              │
│ positions    │     │ 200 araç     │     │ JSON         │     │ Leaflet Map  │
│ speeds       │     │ lat/lng      │     │ ~50KB/frame  │     │ Metrik Panel │
│ phases       │     │ heading      │     │ 10 fps       │     │ Bunching UI  │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
        │                    │                   │
     Her 16 step       meter_to_latlng()    Broadcast
     (~1.6ms)          binary search       tüm client'lara
```

### 6.1.1 GPU → CPU Snapshot

```python
# Sadece env[0]'ın verisi CPU'ya kopyalanır (diğer 511 env dokunulmaz)
positions = env.positions[0].cpu().numpy()   # (200,)
speeds    = env.speeds[0].cpu().numpy()      # (200,)
phases    = env.phases[0].cpu().numpy()      # (200,)
```

### 6.1.2 Metre → LatLng Dönüşümü

Linear metre pozisyonları harita koordinatlarına dönüştürülür:

```python
def meter_to_latlng(meter):
    # Binary search ile doğru segmenti bul
    segment = binary_search(segments, meter)
    
    # Segment içinde interpolasyon
    t = (meter - segment.start_meter) / segment.length
    lat = segment.lat1 + t * (segment.lat2 - segment.lat1)
    lng = segment.lng1 + t * (segment.lng2 - segment.lng1)
    heading = bearing(segment.lat1, segment.lng1, segment.lat2, segment.lng2)
    
    return lat, lng, heading
```

### 6.1.3 JSON Payload Yapısı

```json
{
  "mode": "training",
  "time": 1250.3,
  "vehicles": [
    {
      "id": 0,
      "code": "M00",
      "positionMeters": 4521.3,
      "speed": 8.234,
      "phase": "cruising",
      "latitude": 41.0098,
      "longitude": 28.6561,
      "heading": 112.5,
      "forwardGap": 234.5,
      "backwardGap": 189.2,
      "isBunched": false,
      "action": "NORMAL",
      "nextStopIndex": 5
    }
  ],
  "metrics": {
    "iteration": 235,
    "step": 48,
    "reward": -3.254,
    "totalReward": -1520.3,
    "avgSpeed": 10.8,
    "minGap": 45.2,
    "bunching": 3
  },
  "bunchingPairs": [
    {"id1": 12, "id2": 15, "gap": 43.2, "severity": "critical"}
  ]
}
```

## 6.2 Dashboard Bileşenleri

### 6.2.1 Leaflet Harita

- **Araç ikonları**: 200 otobüs emojisi (🚌) gerçek koordinatlarla
- **Faz renklendirme**: Cruising (yeşil), Stopped (kırmızı), Approaching (sarı)
- **Bunching çizgileri**: Yakın araç çiftleri kırmızı çizgiyle bağlanır
- **Durak işaretleri**: Platform uzunlukları ve kapasiteleri

### 6.2.2 Metrik Paneli

```
┌─────────────────────────────────┐
│  📊 Eğitim Metrikleri            │
│  ───────────────────────────── │
│  İterasyon: 235      Step: 48   │
│  Reward: -3.254      Toplam R: -1520 │
│  Hız: 38.9 km/h      Min Gap: 45m   │
│  Duran: 23           Bunching: 3    │
│  ───────────────────────────── │
│  🧠 Predictive Engine            │
│  Speed Filter: 8     Kabul: 2   │
└─────────────────────────────────┘
```

### 6.2.3 Eğitim İzle Toggle

Dashboard iki modda çalışır:
1. **Simülasyon modu**: TypeScript motoru çalışır, kullanıcı hız/duraklat kontrol eder
2. **Eğitim modu**: Python eğitimi WS üzerinden izlenir, simülasyon motoru durur

## 6.3 TensorBoard Entegrasyonu

Eğitim sırasında şu metrikler TensorBoard'a yazılır:

| Grup | Metrikler |
|------|-----------|
| **reward/** | mean, min, max, std |
| **loss/** | policy_loss, value_loss |
| **training/** | entropy, learning_rate, fps |
| **environment/** | avg_speed, min_gap, bunching_count |

Erişim: `http://localhost:6006`
