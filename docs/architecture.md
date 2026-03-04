# Sistem Mimarisi

## Genel Bakış

Metrobüs Akıllı Trafik Yönetim Sistemi, mikro servis mimarisi üzerine kurulmuş bir event-driven (olay güdümlü) sistemdir.

## Veri Akışı

```
GPS Modülleri ──→ Data Ingestion ──→ Kafka ──→ Realtime Engine ──→ Decision Engine ──→ API Gateway ──→ Driver HUD
İETT API ──────→                                                                                   ──→ Dashboard
İBB Trafik API ─→                              ↕                      ↕
                                           TimescaleDB             ML Service
                                             Redis
```

## Servisler

### 1. Data Ingestion Service
- GPS modüllerinden araç konumlarını toplar
- İETT/İBB API'den gerçek zamanlı veri çeker
- Toplanan verileri Kafka topic'lerine yayınlar

### 2. Realtime Engine
- Kafka'dan gelen verileri tüketir
- Headway (araç arası mesafe) hesaplar
- Bunching (yığılma) tespiti yapar
- Durak yoğunluk analizi yapar

### 3. Decision Engine
- 8 kural tabanlı karar motoru
- Öncelik sırasına göre kural değerlendirmesi
- Şoför komutu üretimi (YAVAŞLA, HIZLAN, DURMA, vb.)

### 4. ML Service (Python)
- Yolcu talep tahmini
- Seyahat süresi tahmini
- Tıkanıklık tahmini (15dk ilerisi)

### 5. API Gateway
- REST API endpoint'leri
- WebSocket (Socket.IO) gerçek zamanlı iletişim
- Araç HUD ve Dashboard için veri dağıtımı

### 6. Driver HUD
- React tabanlı araç içi ekran
- Büyük, okunabilir komut göstergesi
- Sonraki durak bilgisi, headway göstergesi

### 7. Dashboard
- Leaflet harita üzerinde araç takibi
- Yoğunluk ısı haritası
- Analitik grafikler (Recharts)

## Teknoloji Kararları

| Teknoloji | Gerekçe |
|-----------|---------|
| **Kafka** | Yüksek hacimli (saniyede binlerce GPS kaydı) event streaming |
| **TimescaleDB** | Zaman serisi verileri için optimize, hypertable + continuous aggregates |
| **Redis** | Anlık araç durumu cache, <1ms okuma |
| **Socket.IO** | Bidirectional WebSocket, otomatik reconnect |
| **PostGIS** | Coğrafi sorgular (en yakın durak, mesafe hesabı) |
