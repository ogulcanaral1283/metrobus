# Istanbul Metrobus — Akıllı Durak-Slot Kontrol Sistemi

İstanbul metrobüs hattı (52 km, 44 durak/yön) için gerçek zamanlı simülasyon ve analitik hız kontrol sistemi.

## Problem

Metrobüs hattında *bus bunching* — araçların kümelenerek büyük boşluklar oluşturması — kronik bir sorundur. Geleneksel headway düzeltme yaklaşımları semptoma odaklanır. Bu sistem problemi kaynağında çözer: **durak slot taşmasını önleyerek yığılmayı engeller**.

## Mimari

```
sim_server.py (Python WebSocket :8765)
    │
    ├── Fizik Motoru (10 Hz)
    │       StationFSM  — araç faz geçişleri + peron giriş kuralları
    │       ForwardSafety — çarpışma önleme
    │
    └── Analitik Kontrol Motoru (1 Hz karar, zero-order hold)
            HeadwayModel    — ODE tabanlı headway dinamiği (metrik)
            SmartStop × 44  — durak bölgesi yöneticisi + skip-stop
            StopInterface   — duraklar arası koordinasyon
            DemandModel     — İBB turnike verisinden durak×saat talebi

packages/dashboard (React + Nginx :3000)
    WebSocket ile sim_server'a bağlanır
    Leaflet harita, araç izleme, motor inceleme, durak kuyruk paneli,
    A/B karşılaştırma ekranı, canlı saat seçici
```

## Kontrol Motoru — Matematiksel Özet

Her durak kendi bölgesindeki araçlar (~1-2) için bağımsız karar alır.

**Kinematik ETA** (iki fazlı):
```
d > d_approach:  ETA = (d - d_approach)/v  +  d_approach / (v_entry/2)
d ≤ d_approach:  ETA = d / (v_entry/2)
v_entry = min(v, sqrt(2 · a_c · d_approach))
```

**Kuyruk pozisyonu** — ETA sabit peron önüne değil, aracın kenetlenme noktasına ölçülür:
```
d = (zone_end − n·20.5) − pos      n = varışta hâlâ dolu/rezerve slot sayısı
```
n ile ETA karşılıklı bağımlı → sabit-nokta iterasyonu (n monoton artar, salınımsız yakınsar).

**Gecikme bütçesi:**
```
d_eff = d - v · 3.0          (hesaplama + iletişim + sürücü + araç tepkisi)
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

**Talep-farkındalı skip-stop** — kuyruk öngörülen ve o saatte düşük talepli
duraklar atlanabilir. Altı kapının hepsi geçilmeli:
```
1. talep verisi mevcut + durak terminal değil
2. araç cruising fazında
3. öngörülen kuyruk ≥ 8 sn                (congestion gerçek)
4. λ_s(saat) ≤ koridorun %30 yüzdeliği    (İBB turnike verisi — Mecidiyeköy asla geçemez)
5. aynı durak 120 sn içinde atlanmadı
6. arkadan ≤ 180 sn içinde başka araç var (yolcu güvencesi)
```
Atlayan araç slot rezerve etmez → boşalan slot arkadakilere kalır.

## Hesaplama Karmaşıklığı

Her simülasyon tick'inde:

| Katman | İşlem |
|--------|-------|
| Headway metrikleri | O(N log N) — pozisyon sıralama |
| SmartStop filtreleme | O(S × N) — hafif pozisyon karşılaştırması |
| Kost-fayda analizi | O(S × 2) — bölge başına ~2 araç |

S = durak sayısı (44), N = araç sayısı. N arttıkça ağır hesap sabit kalır.

## Paketler

| Paket | Açıklama |
|-------|----------|
| `sim_server.py` | Simülasyon ve kontrol motoru (Python WebSocket) |
| `ab_test.py` | Eşleştirilmiş A/B çerçevesi — bit-özdeş trafik, motor AÇIK/KAPALI |
| `segment_trip_test.py` | Araç-bazlı sefer süresi deneyi (Beylikdüzü→Mecidiyeköy) |
| `rl_env/controller/` | SmartStop, DockProjection, HeadwayModel, StopInterface, ControlMerger |
| `rl_env/station_fsm.py` | Araç faz makinesi (cruising → approaching → docking → ...) |
| `rl_env/demand.py` | İBB turnike verisinden durak×saat talep modeli |
| `data_ibb/` | İBB açık veri hattı: indirme/süzme/görselleştirme script'leri |
| `results/` | Tüm A/B ve segment koşularının logları/CSV'leri |
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
├── ab_test.py                  # Eşleştirilmiş A/B test çerçevesi (motor AÇIK/KAPALI)
├── segment_trip_test.py        # Segment sefer süresi deneyi (Beylikdüzü→Mecidiyeköy)
├── rl_env/
│   ├── config.py               # SimVehicle, sabitler
│   ├── route_data.py           # LinearStop, rota yapıları
│   ├── station_fsm.py          # Araç faz makinesi (peron giriş kuralları dahil)
│   ├── demand.py               # İBB turnike verisinden durak talep modeli
│   ├── data/                   # Rota + platform + talep verileri
│   └── controller/
│       ├── smart_stop.py       # Durak bölgesi kontrol motoru + skip-stop
│       ├── dock_projection.py  # Uzay-zaman kuyruk projeksiyonu
│       ├── stop_interface.py   # Duraklar arası iletişim
│       ├── control_merger.py   # Komut birleştirici + hız bandları
│       ├── headway_model.py    # Headway ODE modeli (metrik)
│       └── station_arrival_scheduler.py  # ETA / dwell yardımcıları
├── packages/
│   ├── shared/                 # Rota geometrisi, durak verileri
│   └── dashboard/              # React dashboard (kuyruk paneli, A/B ekranı)
├── data_ibb/                   # İBB açık veri hattı (talep matrisi + görseller)
├── results/                    # A/B ve segment test logları/CSV'leri
├── Dockerfile                  # Dashboard image (Node → Nginx)
├── Dockerfile.python           # sim_server image
└── docker-compose.yml          # sim-server :8765 + dashboard :3000
```

## Rota Verisi

OpenStreetMap Overpass API'den alınmış:

- **44 durak** (yön başına) — Beylikdüzü (TÜYAP) → Söğütlüçeşme
- **Hat uzunluğu** ~52 km (çift yön, lineerleştirilmiş)
- Gidiş + dönüş yönleri; platform poligonlarından slot sayıları

## Talep Verisi

İBB Açık Veri Portalı — Saatlik Toplu Ulaşım Veri Seti (BELBİM):
durak × saat yolcu matrisi (`rl_env/data/station_demand_hourly.csv`).
Ayrıntı ve yeniden üretim adımları: `data_ibb/README.md`.

## Tech Stack

- **Simülasyon:** Python 3.11, asyncio, websockets, numpy
- **Frontend:** React 18, Vite, Leaflet, recharts
- **Servis:** Nginx (Docker)
- **Altyapı:** Docker Compose

