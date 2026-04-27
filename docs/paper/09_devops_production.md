# 🏗️ DevOps Perspektifi: Metrobüs AI Sisteminin Gerçek Hayata Dönüşümü

> Bu döküman, bir DevOps mühendisinin bu projeyi production'a taşırken düşünmesi gereken her şeyi kapsar.

---

## 1. BÜYÜK RESİM: Sistemin Production Mimarisi

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          METROBÜS AI — PRODUCTION MİMARİSİ                       │
│                                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────────┐   │
│  │  VERİ KAYNAK│     │  VERİ İŞLEME│     │  AI MOTOR   │     │  TÜKETİCİLER │   │
│  │             │     │             │     │             │     │              │   │
│  │ • GPS Modül │────▶│ • Kafka     │────▶│ • ONNX Srv  │────▶│ • Şoför HUD  │   │
│  │ • İETT API  │     │ • Flink     │     │ • PE Engine │     │ • Kontrol Odası│  │
│  │ • Kart Basım│     │ • Redis     │     │ • Retrain   │     │ • Mobil App  │   │
│  │ • Hava API  │     │ • TimescaleDB│    │             │     │ • API        │   │
│  └─────────────┘     └─────────────┘     └─────────────┘     └──────────────┘   │
│         │                    │                   │                    │           │
│         └────────────────────┴───────────────────┴────────────────────┘           │
│                                      │                                           │
│                         ┌────────────┴────────────┐                              │
│                         │    ALTYAPI KATMANI       │                              │
│                         │                          │                              │
│                         │  Kubernetes (EKS/AKS)    │                              │
│                         │  GPU Node Pool (eğitim)  │                              │
│                         │  Prometheus + Grafana     │                              │
│                         │  ArgoCD (GitOps)          │                              │
│                         │  Vault (secrets)          │                              │
│                         └──────────────────────────┘                              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. VERİ PIPELINE'I — Gerçek Zamanlı GPS Akışı

### 2.1 Veri Kaynakları

| Kaynak | Veri | Frekans | Format | Volume |
|--------|------|---------|--------|--------|
| **GPS Modülleri** | Konum, hız, heading | 1-5 Hz / araç | MQTT/gRPC | ~200 msg/s (200 araç) |
| **İETT Open API** | Sefer bilgisi, planlı kalkış | 30s | REST JSON | ~10 req/min |
| **İstanbulKart** | Kart basım (durak, zaman) | Event-driven | Kafka | ~500-2000 msg/s (pik) |
| **Hava durumu** | Sıcaklık, yağış | 15 dk | REST | 4 req/saat |
| **Trafik (İBB)** | Segment hız | 5 dk | REST | ~20 req/dk |

### 2.2 DevOps Kararı: Neden Kafka?

```
GPS Modülü (200 araç × 5 Hz = 1000 msg/s)
     │
     ▼
  ┌──────────────────────────────────┐
  │ Apache Kafka Cluster              │
  │                                   │
  │ Topic: metrobus.gps.raw           │  ← Ham GPS verisi
  │   Partitions: 8                   │
  │   Replication: 3                  │
  │   Retention: 7 gün                │
  │                                   │
  │ Topic: metrobus.gps.enriched      │  ← İşlenmiş veri
  │ Topic: metrobus.decisions         │  ← AI kararları
  │ Topic: metrobus.alerts            │  ← Bunching uyarıları
  └──────────────────────────────────┘
```

**Neden Kafka, neden MQTT değil?**
- MQTT: IoT cihazlar için iyi ama replay/consumer-group desteği zayıf
- Kafka: Replay (geçmişe dönük analiz), exactly-once, multi-consumer
- **Karar:** GPS cihaz → MQTT Broker → Kafka Connect → Kafka

### 2.3 Stream Processing: Apache Flink

```python
# Flink Job: GPS → Enriched Event
class GPSEnrichmentJob:
    """
    1. GPS mesajını al
    2. En yakın durağı hesapla (PostGIS spatial query cache)
    3. Headway hesapla (öndeki/arkadaki araç)
    4. Bunching tespiti yap
    5. metrobus.gps.enriched topic'ine yaz
    """
    
    window = TumblingWindow(5_seconds)
    
    # Her 5 saniyede bir headway snapshot
    def process(gps_events):
        positions = sort_by_position(gps_events)
        headways = compute_headways(positions)
        bunching = detect_bunching(headways, threshold=100m)
        
        emit(EnrichedEvent(
            vehicles=positions,
            headways=headways,
            bunching_pairs=bunching,
            timestamp=now()
        ))
```

---

## 3. AI SERVİS MİMARİSİ

### 3.1 ONNX Inference Service

```yaml
# Kubernetes Deployment — AI Inference
apiVersion: apps/v1
kind: Deployment
metadata:
  name: metrobus-ai-inference
spec:
  replicas: 3    # HA — 3 pod
  template:
    spec:
      containers:
      - name: onnx-server
        image: metrobus/ai-inference:v1.2.0
        resources:
          requests:
            cpu: "500m"
            memory: "256Mi"
          limits:
            cpu: "1000m"
            memory: "512Mi"
        ports:
        - containerPort: 8080   # gRPC inference
        - containerPort: 9090   # Prometheus metrics
        env:
        - name: MODEL_PATH
          value: "/models/metrobus_mappo_actor.onnx"
        - name: BATCH_SIZE
          value: "200"  # 200 araç tek batch
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
```

**Neden GPU gerekmez?**
- Actor modeli sadece **23 KB** (5,828 parametre)
- CPU'da inference: **<2ms** — 200 araç tek shot
- GPU inference gereksiz overhead (kernel launch > hesaplama)

### 3.2 Inference Akışı

```
GPS Event (Kafka)
     │
     ▼
┌──────────────────────────────────────┐
│ Inference Service                     │
│                                       │
│ 1. Kafka'dan enriched event oku       │  ← 100ms
│ 2. 200 araç için observation oluştur  │  ← <1ms
│    [hız, mesafe, faz, headway, ...]   │
│ 3. ONNX model inference              │  ← <2ms
│    obs(200,24) → actions(200,4)       │
│ 4. Predictive Engine (paralel)       │  ← ~5ms
│ 5. Kararları birleştir               │  ← <1ms
│ 6. Kafka decisions topic'ine yaz     │  ← <5ms
│                                       │
│ TOPLAM LATENCY: ~15ms                 │
└──────────────────────────────────────┘
     │
     ▼
Şoför HUD / Kontrol Odası
```

### 3.3 Model Versiyonlama

```
┌──────────────────────────────────────────────────────┐
│ Model Registry (MLflow / DVC)                         │
│                                                       │
│ v1.0.0  2026-03-01  10 durak, 80 araç   (baseline)  │
│ v1.1.0  2026-03-15  31 durak, 120 araç  (expanded)  │
│ v1.2.0  2026-03-29  31 durak, 200 araç  (current)   │
│ v2.0.0  2026-04-??  44 durak, 250 araç  (full line) │
│                                                       │
│ Her versiyon:                                         │
│   ├── model.onnx           (23 KB)                   │
│   ├── hyperparams.yaml     (training config)          │
│   ├── metrics.json         (test sonuçları)          │
│   ├── tensorboard/         (training logs)            │
│   └── validation_report.md (A/B test sonuçları)      │
└──────────────────────────────────────────────────────┘
```

---

## 4. KUBERNETES ALTYAPISI

### 4.1 Cluster Topolojisi

```
┌──────────────────────────────────────────────────────────────┐
│ Kubernetes Cluster (AKS / EKS)                                │
│                                                               │
│ ┌─────────────────────┐  ┌─────────────────────────────────┐ │
│ │ System Node Pool     │  │ GPU Node Pool (eğitim için)     │ │
│ │ (3× Standard_D4s)   │  │ (1× Standard_NC6s — T4 GPU)     │ │
│ │                      │  │                                  │ │
│ │ • Kafka (3 broker)   │  │ • Training Job (CronJob)        │ │
│ │ • Redis              │  │   Her hafta yeni model eğit     │ │
│ │ • TimescaleDB        │  │                                  │ │
│ │ • API Gateway        │  │ • TensorBoard (geçici)          │ │
│ │ • AI Inference (3)   │  │                                  │ │
│ │ • Dashboard (2)      │  │ ⚡ Spot instance — maliyet ↓%70  │ │
│ │ • Monitoring          │  │                                  │ │
│ └─────────────────────┘  └─────────────────────────────────┘ │
│                                                               │
│ ┌─────────────────────┐                                      │
│ │ Edge Node Pool       │                                      │
│ │ (IoT gateway)        │                                      │
│ │                      │                                      │
│ │ • MQTT Broker         │                                      │
│ │ • GPS data ingestion │                                      │
│ └─────────────────────┘                                      │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Namespace Organizasyonu

```
kubectl get namespaces:
  metrobus-prod        ← Üretim servisleri
  metrobus-staging     ← Test ortamı (aynı yapı, düşük replica)
  metrobus-training    ← GPU eğitim job'ları
  metrobus-monitoring  ← Prometheus, Grafana, alerting
  metrobus-data        ← Kafka, Redis, TimescaleDB
```

### 4.3 CI/CD Pipeline (GitOps — ArgoCD)

```
Developer Push → GitHub
     │
     ▼
┌──────────────────────────────────────┐
│ GitHub Actions CI                     │
│                                       │
│ 1. Lint + Type Check (TS + Python)   │
│ 2. Unit Tests                         │
│ 3. Simülasyon Regression Test        │
│    → 100 step çalıştır               │
│    → Reward > threshold?              │
│ 4. Docker Build + Push (GHCR)        │
│ 5. Helm Chart güncelle               │
│ 6. ArgoCD sync trigger               │
└──────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────┐
│ ArgoCD (GitOps)                       │
│                                       │
│ Git repo (helm charts)               │
│   ├── staging/     → auto-sync       │
│   └── production/  → manual approve  │
│                                       │
│ Canary deployment:                    │
│   1. %10 trafik yeni modele          │
│   2. 1 saat izle (bunching metrik)   │
│   3. OK → %100'e yükselt            │
│   4. FAIL → otomatik rollback        │
└──────────────────────────────────────┘
```

---

## 5. İZLEME VE ALERTING

### 5.1 Prometheus Metrikleri

```yaml
# Custom metrikler — AI Inference Service
metrobus_inference_latency_ms:
  type: histogram
  help: "ONNX model inference süresi"
  buckets: [1, 2, 5, 10, 20, 50]

metrobus_bunching_count:
  type: gauge
  help: "Anlık bunching çifti sayısı"

metrobus_headway_cv:
  type: gauge
  help: "Headway coefficient of variation"

metrobus_avg_speed_kmh:
  type: gauge
  help: "Filo ortalama hız"

metrobus_model_version:
  type: info
  help: "Aktif ONNX model versiyonu"
```

### 5.2 Grafana Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 METROBÜS AI — OPS DASHBOARD                              │
│                                                              │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐│
│ │ Bunching │ │ Headway  │ │ Avg Speed│ │ Inference Lat.   ││
│ │    3     │ │ CV: 0.35 │ │ 38 km/h  │ │  1.8 ms (p99)   ││
│ │  🟢 OK   │ │  🟢 OK   │ │  🟢 OK   │ │    🟢 OK        ││
│ └──────────┘ └──────────┘ └──────────┘ └──────────────────┘│
│                                                              │
│ ┌──────────────────────────────────────────────────────────┐│
│ │ 📈 Son 24 Saat — Bunching Timeline                       ││
│ │    ▃▃▇▇▅▃▃▂▂▁▁▁▂▂▃▃▅▇▇▅▃▃▂▂                           ││
│ │    06:00  08:00  10:00  12:00  14:00  16:00  18:00      ││
│ │    ←rush→              ←off-peak→     ←rush→            ││
│ └──────────────────────────────────────────────────────────┘│
│                                                              │
│ ┌──────────────────────────────────────────────────────────┐│
│ │ 🚌 Araç Durumu: 200 aktif | 23 durakta | 3 bunched     ││
│ └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 5.3 Alert Kuralları

```yaml
# Prometheus Alert Rules
groups:
- name: metrobus-ai
  rules:
  - alert: HighBunchingRate
    expr: metrobus_bunching_count > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Bunching oranı yüksek: {{ $value }} çift"

  - alert: InferenceLatencyHigh
    expr: histogram_quantile(0.99, metrobus_inference_latency_ms) > 50
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "AI inference latency p99 > 50ms"

  - alert: ModelStale
    expr: time() - metrobus_model_last_update > 604800  # 7 gün
    labels:
      severity: warning
    annotations:
      summary: "Model 7 gündür güncellenmedi"

  - alert: GPSDataGap
    expr: rate(metrobus_gps_events_total[5m]) < 50
    for: 3m
    labels:
      severity: critical
    annotations:
      summary: "GPS veri akışı düştü"
```

---

## 6. VERİTABANI STRATEJİSİ

### 6.1 TimescaleDB (Zaman Serisi)

```sql
-- Hypertable: GPS logları (sıkıştırılmış, 30 gün retention)
CREATE TABLE gps_logs (
    time        TIMESTAMPTZ NOT NULL,
    vehicle_id  INT,
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    speed       REAL,
    heading     REAL,
    headway_s   REAL,
    ai_action   SMALLINT
);
SELECT create_hypertable('gps_logs', 'time');

-- Continuous Aggregate: Saatlik KPI
CREATE MATERIALIZED VIEW hourly_kpi
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) as hour,
    avg(speed) as avg_speed,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY headway_s) as p95_headway,
    count(*) FILTER (WHERE headway_s < 30) as bunching_events
FROM gps_logs
GROUP BY time_bucket('1 hour', time);
```

### 6.2 Redis (Anlık State)

```
# Son bilinen araç konumları (TTL: 60s)
SET vehicle:M042 '{"lat":41.0098,"lng":28.656,"speed":11.2,"phase":"cruising"}' EX 60

# Headway cache (TTL: 10s)  
SET headway:current '{"cv":0.35,"min_gap":45,"bunching":3}' EX 10

# AI karar geçmişi (son 100)
LPUSH decisions:M042 '{"action":"SLOW","reason":"bunching_risk","ts":1711700000}'
LTRIM decisions:M042 0 99
```

---

## 7. GÜVENLİK

### 7.1 Ağ Güvenliği

```
Internet ──→ WAF ──→ Load Balancer ──→ API Gateway ──→ Internal Services
                                           │
                                     JWT Auth
                                     Rate Limiting
                                     CORS Policy
```

### 7.2 Kimlik ve Erişim

| Rol | Erişim | Yetki |
|-----|--------|-------|
| **Şoför** | HUD App | Kendi aracının AI komutlarını görür |
| **Denetçi** | Dashboard | Tüm filoyı izler, override yapabilir |
| **ML Engineer** | Training + MLflow | Model eğitir, deploy eder |
| **DevOps** | K8s + monitoring | Altyapı yönetimi |
| **Yönetici** | Raporlama | Günlük/haftalık KPI |

### 7.3 Secrets Management

```yaml
# HashiCorp Vault veya K8s Secrets
vault kv put secret/metrobus \
  kafka_password="..." \
  timescale_conn="..." \
  iett_api_key="..." \
  onnx_model_key="..."
```

---

## 8. MALİYET TAHMİNİ (Azure/AWS)

### 8.1 Aylık Altyapı Maliyeti

| Bileşen | Spec | Aylık ($) |
|---------|------|-----------|
| K8s System Pool (3 node) | D4s v5 (4 CPU, 16GB) | ~$400 |
| GPU Node (spot, eğitim) | NC6s v3 (T4 GPU) × 20 saat/hafta | ~$80 |
| Kafka (managed) | 3 broker, 100GB | ~$300 |
| TimescaleDB (managed) | 4 CPU, 16GB, 500GB SSD | ~$250 |
| Redis (managed) | 2GB | ~$50 |
| Load Balancer + DNS | — | ~$30 |
| Container Registry | 50GB | ~$10 |
| Monitoring (Grafana Cloud) | — | ~$50 |
| **TOPLAM** | | **~$1,170/ay** |

### 8.2 Self-hosted Alternatif

On-premise sunucu: 1× Dell PowerEdge R750 (~$8,000)
- 2× Xeon, 128GB RAM, 1× T4 GPU
- 3 yıl amortisman: ~$220/ay
- Elektrik + bakım: ~$50/ay
- **Toplam: ~$270/ay** (ama HA/DR sorunu)

---

## 9. ROLLOUT PLANI

### Faz 1: Shadow Mode (1. ay)
```
GPS verisi → AI model → karar üret → KAYDET (ama uygulama)
                                         │
                                    Gerçek operasyonla karşılaştır
                                    "AI şunu diyordu, gerçekte ne oldu?"
```

### Faz 2: Pilot (2-3. ay)
```
10 araçta AI önerileri şoför HUD'a göster
Şoför isteğe bağlı uygular
Bunching metrikleri karşılaştır:
  AI takip eden araçlar vs kontrol grubu
```

### Faz 3: Yarı-otonom (4-6. ay)
```
AI kararları otomatik uygulanır:
  SLOW/FAST → hız önerisi HUD'da gösterilir + sesli uyarı
  HOLD → durakta "X saniye bekle" komutu
  
Şoför override edebilir (her override loglanır)
```

### Faz 4: Tam Otonom (6+ ay)
```
AI kararları doğrudan araç kontrol sistemine
(Sadece elektrikli/otonom araçlarda mümkün)
```

---

## 10. RİSK YÖNETİMİ

| Risk | Olasılık | Etki | Mitigasyon |
|------|----------|------|-----------|
| GPS sinyal kaybı | Orta | Yüksek | Son bilinen konum + dead reckoning |
| AI yanlış karar | Düşük | Orta | Şoför override + anomaly detection |
| Kafka downtime | Düşük | Kritik | 3-broker HA + cross-DC replication |
| Model degradation | Orta | Orta | Haftalık retrain + A/B monitoring |
| Siber saldırı | Düşük | Kritik | WAF + mTLS + network policy |
| Şoför direnci | Yüksek | Orta | Eğitim + pilot program + bonus sistemi |

---

## 11. CHECKLIST: Production'a Çıkmadan Önce

```
□ Infrastructure
  □ K8s cluster provisioned (IaC — Terraform)
  □ Kafka cluster running (3 broker, replication=3)
  □ TimescaleDB + retention policy
  □ Redis cluster
  □ DNS + TLS sertifikası
  □ Network policies + firewall

□ CI/CD
  □ GitHub Actions pipeline (test → build → deploy)
  □ ArgoCD GitOps sync
  □ Canary deployment strategy
  □ Rollback procedure documented

□ Monitoring
  □ Prometheus metrics exposed
  □ Grafana dashboards created
  □ Alert rules configured (PagerDuty/Opsgenie)
  □ Log aggregation (Loki/ELK)
  □ Distributed tracing (Jaeger)

□ AI/ML
  □ Model registry (MLflow/DVC)
  □ A/B test framework
  □ Retrain CronJob
  □ Model validation gate (auto)
  □ Shadow mode pipeline

□ Security
  □ Secrets in Vault/K8s secrets
  □ RBAC configured
  □ Network policies
  □ API rate limiting
  □ Audit logging

□ Data
  □ GPS ingestion pipeline tested
  □ Data retention policy (GDPR?)
  □ Backup strategy (TimescaleDB)
  □ Disaster recovery plan

□ Operations
  □ Runbook documentation
  □ On-call rotation
  □ Incident response plan
  □ Capacity planning (yolcu artışı)
  □ SLA tanımı (uptime: %99.9)
```
