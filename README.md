# 🚍 İstanbul Metrobüs Akıllı Trafik Yönetim Sistemi

Metrobüs hattındaki araçların konumlarını, araç arası mesafeleri ve durak yoğunluklarını gerçek zamanlı izleyerek şoförlere yönlendirme komutları veren akıllı trafik yönetim sistemi.

## 🎯 Problem

İstanbul metrobüs hattında araçların birbirine yığılması (bus bunching) veya aralarında aşırı boşluk oluşması, yolcu deneyimini ciddi şekilde olumsuz etkiler. Bu sistem, şoförlere araç içi ekranlar aracılığıyla gerçek zamanlı yönlendirme sağlayarak bu sorunu çözer.

## 🏗️ Mimari

```
Veri Kaynakları → Veri Toplama → Gerçek Zamanlı İşlem → Karar Motoru → Şoför HUD
     GPS              Kafka          Headway Hesabı       Kural Motoru     WebSocket
     İETT API                        Bunching Tespiti     ML Tahmini       React
     Trafik API                      Yoğunluk Analizi     Komut Üretimi
```

## 📦 Paketler

| Paket | Açıklama |
|-------|----------|
| `shared` | Ortak tipler, sabitler ve yardımcı fonksiyonlar |
| `data-ingestion` | GPS, İETT API, trafik verisi toplama |
| `realtime-engine` | Araç takibi, headway hesabı, yoğunluk analizi |
| `decision-engine` | Kural tabanlı karar motoru |
| `ml-service` | Makine öğrenmesi tahmin servisi (Python) |
| `api-gateway` | REST API + WebSocket sunucusu |
| `driver-hud` | Şoför araç içi ekran arayüzü |
| `dashboard` | Yönetim ve izleme paneli |

## ⚡ Hızlı Başlangıç

### Gereksinimler

- Node.js >= 20.0.0
- Docker & Docker Compose
- Python >= 3.10 (ML servisi için)

### Kurulum

```bash
# Repo'yu klonla
git clone <repo-url>
cd metrobus

# Bağımlılıkları kur
npm install

# Ortam değişkenlerini ayarla
cp .env.example .env
# .env dosyasını düzenle

# Altyapı servislerini başlat
docker-compose up -d

# Geliştirme sunucularını başlat
npm run dev
```

### Simülasyon

```bash
# Araç simülasyonu ile test
npm run dev:simulate
```

## 📊 Karar Motoru Komutları

| Komut | Tetikleyici | Aksiyon |
|-------|-------------|---------|
| 🐢 YAVAŞLA | Öndeki araçla mesafe < 200m | Hızı %30 düşür |
| 🚀 DURMA | Arkadaki araç > 3dk geride | Durakta durmadan devam |
| ⚠️ DİKKAT | Durak yoğunluk skoru > 80 | Durakta dikkatli ol |
| ⏩ HIZLAN | Sefer planından > 5dk gecikme | Hızlanarak plana uy |
| ✅ NORMAL | Tüm metrikler normal | Standart seyir |

## 🛠️ Teknoloji Yığını

- **Backend:** Node.js + TypeScript
- **Mesajlaşma:** Apache Kafka
- **Veritabanı:** TimescaleDB (PostgreSQL)
- **Cache:** Redis
- **ML:** Python + scikit-learn
- **Frontend:** React + Vite
- **Harita:** OpenStreetMap + Leaflet
- **WebSocket:** Socket.IO
- **Container:** Docker + Docker Compose

## 📁 Proje Yapısı

```
metrobus/
├── packages/
│   ├── shared/           # Ortak tipler ve yardımcılar
│   ├── data-ingestion/   # Veri toplama servisi
│   ├── realtime-engine/  # Gerçek zamanlı işlem motoru
│   ├── decision-engine/  # Karar motoru
│   ├── ml-service/       # ML tahmin servisi
│   ├── api-gateway/      # API sunucusu
│   ├── driver-hud/       # Şoför HUD arayüzü
│   └── dashboard/        # Yönetim paneli
├── infrastructure/       # Docker ve DB konfigürasyonları
├── scripts/              # Yardımcı scriptler
├── docs/                 # Dökümanlar
└── tests/                # Entegrasyon testleri
```

## 📄 Lisans

MIT
