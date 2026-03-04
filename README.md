# 🚍 Istanbul Metrobus Smart Traffic Management System

A real-time intelligent traffic management system for Istanbul's Metrobus rapid transit line. The system monitors vehicle positions, headway distances, and station congestion levels, providing live driver guidance commands to optimize fleet performance and reduce bus bunching.

## 🎯 Problem

Bus bunching — where vehicles cluster together leaving large gaps in service — is a chronic issue on Istanbul's 52 km Metrobus corridor serving 800,000+ daily passengers. This system provides real-time driver instructions via in-vehicle HUD displays to maintain optimal headway spacing.

## 🏗️ Architecture

```
Data Sources → Ingestion Layer → Real-Time Engine → Decision Engine → Driver HUD
    GPS           Kafka           Headway Calc        Rule Engine      WebSocket
    IETT API                      Bunching Detection   ML Prediction    React UI
    Traffic API                   Congestion Analysis  Command Gen
```

## 📦 Packages

| Package | Description |
|---------|-------------|
| `shared` | Common types, constants, utilities, station & route data |
| `data-ingestion` | GPS, IETT API, and traffic data collectors |
| `realtime-engine` | Vehicle tracking, headway calculation, congestion analysis |
| `decision-engine` | Rule-based decision engine with approach optimization |
| `ml-service` | Machine learning prediction service (Python) |
| `api-gateway` | REST API + WebSocket server |
| `driver-hud` | In-vehicle driver heads-up display |
| `dashboard` | Management & monitoring dashboard with live map |

## 🗺️ Route Data

The route geometry and station positions are sourced directly from **OpenStreetMap** via the Overpass API:

- **45 stations** from Beylikdüzü (TÜYAP) to Söğütlüçeşme
- **Eastbound route** (34G Beylikdüzü → Söğütlüçeşme): 1,065 coordinate points
- **Westbound route** (34G Söğütlüçeşme → Beylikdüzü): 1,047 coordinate points
- **99 verified stop positions** from OSM bus stop nodes

## ⚡ Quick Start

### Prerequisites

- Node.js >= 20.0.0
- Docker & Docker Compose (for full stack)
- Python >= 3.10 (for ML service)

### Installation

```bash
# Clone the repo
git clone https://github.com/ogulcanaral1283/metrobus.git
cd metrobus

# Install dependencies
npm install

# Set up environment
cp .env.example .env
# Edit .env with your configuration

# Start infrastructure services
docker-compose up -d

# Start all dev servers
npm run dev
```

### Dashboard Only

```bash
# Run just the dashboard with live map
npm run dev:dashboard
```

### Vehicle Simulation

```bash
# Simulate vehicles on the route
npm run dev:simulate
```

### Refresh Route Data from OSM

```bash
# Fetch latest route geometry from OpenStreetMap
npx tsx scripts/fetch-route-osrm.ts
```

## 📊 Decision Engine Commands

| Command | Trigger | Action |
|---------|---------|--------|
| 🐢 SLOW DOWN | Leading vehicle < 200m ahead | Reduce speed by 30% |
| 🚀 EXPRESS | Following vehicle > 3min behind | Skip station stop |
| ⚠️ CAUTION | Station congestion score > 80 | Approach with caution |
| ⏩ SPEED UP | > 5min behind schedule | Increase speed to catch up |
| ✅ NORMAL | All metrics within range | Standard operation |

## 🛠️ Tech Stack

- **Backend:** Node.js + TypeScript (monorepo with npm workspaces)
- **Messaging:** Apache Kafka
- **Database:** TimescaleDB (PostgreSQL)
- **Cache:** Redis
- **ML:** Python + scikit-learn
- **Frontend:** React 18 + Vite
- **Maps:** OpenStreetMap + Leaflet + react-leaflet
- **Real-time:** Socket.IO (WebSocket)
- **Infrastructure:** Docker + Docker Compose

## 📁 Project Structure

```
metrobus/
├── packages/
│   ├── shared/             # Common types, station data, route geometry
│   ├── data-ingestion/     # Data collection service
│   ├── realtime-engine/    # Real-time processing engine
│   ├── decision-engine/    # Rule-based decision engine
│   ├── ml-service/         # ML prediction service (Python)
│   ├── api-gateway/        # API server
│   ├── driver-hud/         # Driver HUD interface
│   └── dashboard/          # Management & monitoring dashboard
├── infrastructure/         # Docker & database configs
├── scripts/                # Route data fetch & vehicle simulation
├── docs/                   # Architecture & decision rule docs
└── tsconfig.json           # Root TypeScript config
```

## 🚀 Deployment

### Production Build

```bash
npm -w packages/dashboard run build
```

### Serve with Nginx

```bash
sudo cp -r packages/dashboard/dist/* /var/www/html/
sudo systemctl restart nginx
```

### Serve with Vite Preview

```bash
npm -w packages/dashboard run preview -- --host 0.0.0.0
```

## 📄 License

MIT
