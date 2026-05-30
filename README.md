# Istanbul Metrobus — Akıllı Durak-Slot Kontrol Sistemi

İstanbul metrobüs hattı (52 km, 45 durak) için gerçek zamanlı simülasyon ve analitik hız kontrol sistemi.

## Problem

Metrobüs hattında *bus bunching* — araçların kümelenerek büyük boşluklar oluşturması — kronik bir sorundur. Geleneksel headway düzeltme yaklaşımları semptoma odaklanır. Bu sistem problemi kaynağında çözer: **durak slot taşmasını önleyerek yığılmayı engeller**.

## Mimari

```
sim_server.py (Python WebSocket :8765)
    │
    ├── Fizik Motoru (20 Hz)
    │       StationFSM  — araç faz geçişleri
    │       ForwardSafety — çarpışma önleme
    │
    └── Analitik Kontrol Motoru
            HeadwayModel    — ODE tabanlı headway dinamiği (metrik)
            SmartStop × 45  — durak bölgesi yöneticisi
            StopInterface   — duraklar arası koordinasyon

packages/dashboard (React + Nginx :3000)
    WebSocket ile sim_server'a bağlanır
    Leaflet harita, araç izleme, motor inceleme paneli
```

## Kontrol Motoru — Matematiksel Özet

Her durak kendi bölgesindeki araçlar (~1-2) için bağımsız karar alır.

**Kinematik ETA** (iki fazlı):
```
d > d_approach:  ETA = (d - d_approach)/v  +  d_approach / (v_entry/2)
d ≤ d_approach:  ETA = d / (v_entry/2)
v_entry = min(v, sqrt(2 · a_c · d_approach))
```

**Gecikme bütçesi:**
```
d_eff = d - v · 7.5          (hesaplama + iletişim + sürücü + araç tepkisi)
```

**Kost-Fayda Analizi:**
```
queue_time     = t_ideal - ETA
cascade_cost   = queue_time × N_follow × 0.7
downstream_cost = P_down × 8.0
intervention_cost = queue_time

net_benefit > 0  →  YAVAŞLA
```

**Hız çarpanı:**
```
λ = clamp(v_needed / v_max, 0.3, 1.0)
```

**Downstream lookahead:**
```
P_down(s) = congestion(s+1)·1.0 + congestion(s+2)·0.6
```

## Hesaplama Karmaşıklığı

Her simülasyon tick'inde:

| Katman | İşlem |
|--------|-------|
| Headway metrikleri | O(N log N) — pozisyon sıralama |
| SmartStop filtreleme | O(S × N) — hafif pozisyon karşılaştırması |
| Kost-fayda analizi | O(S × 2) — bölge başına ~2 araç |

S = durak sayısı (45), N = araç sayısı. N arttıkça ağır hesap sabit kalır.

## Paketler

| Paket | Açıklama |
|-------|----------|
| `sim_server.py` | Simülasyon ve kontrol motoru (Python WebSocket) |
| `rl_env/controller/` | SmartStop, HeadwayModel, StopInterface, ControlMerger |
| `rl_env/station_fsm.py` | Araç faz makinesi (cruising → approaching → docking → ...) |
| `packages/shared/` | Rota geometrisi, durak koordinatları, OSM verileri |
| `packages/dashboard/` | React izleme paneli |

## Hızlı Başlangıç

### Docker (önerilen)

```bash
git clone https://github.com/ogulcanaral1283/metrobus.git
cd metrobus
docker compose up
```

- Dashboard: http://localhost:3000
- WebSocket: ws://localhost:8765

### Geliştirme

```bash
# Simülasyon sunucusu
python sim_server.py

# Dashboard (ayrı terminalde)
cd packages/dashboard
npm install
npm run dev
```

## Proje Yapısı

```
metrobus/
├── sim_server.py               # Ana simülasyon + WS sunucusu
├── rl_env/
│   ├── config.py               # SimVehicle, sabitler
│   ├── route_data.py           # LinearStop, rota yapıları
│   ├── station_fsm.py          # Araç faz makinesi
│   └── controller/
│       ├── smart_stop.py       # Durak bölgesi kontrol motoru
│       ├── stop_interface.py   # Duraklar arası iletişim
│       ├── control_merger.py   # Komut birleştirici
│       ├── headway_model.py    # Headway ODE modeli
│       ├── pid_controller.py   # Stub (aktif değil)
│       └── station_arrival_scheduler.py  # ETA / dwell yardımcıları
├── packages/
│   ├── shared/                 # Rota geometrisi, durak verileri
│   └── dashboard/              # React dashboard
├── Dockerfile                  # Dashboard image (Node → Nginx)
├── Dockerfile.python           # sim_server image
└── docker-compose.yml          # sim-server :8765 + dashboard :3000
```

## Rota Verisi

OpenStreetMap Overpass API'den alınmış:

- **45 durak** — Beylikdüzü (TÜYAP) → Söğütlüçeşme
- **Hat uzunluğu** ~25 km (lineerleştirilmiş)
- Gidiş + dönüş yönleri

## Tech Stack

- **Simülasyon:** Python 3.11, asyncio, websockets, numpy
- **Frontend:** React 18, Vite, Leaflet, recharts
- **Servis:** Nginx (Docker)
- **Altyapı:** Docker Compose

