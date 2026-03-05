import React, { useState, useEffect, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { STATIONS_EAST, ROUTE_NETWORK, GIDIS_LANE, DONUS_LANE, PLATFORM_GEOMETRIES, haversineDistance, calculateBearing, moveAlongBearing, isRushHour, formatDuration } from '@metrobus/shared';

import 'leaflet/dist/leaflet.css';

// Offset polyline — shared geometry segmentlerde gidiş/dönüşü ayırmak için
function offsetPolyline(coords: [number, number][], offset: number): [number, number][] {
    if (coords.length < 2) return coords;
    const result: [number, number][] = [];
    for (let i = 0; i < coords.length; i++) {
        let dx: number, dy: number;
        if (i === 0) {
            dy = coords[1][0] - coords[0][0];
            dx = coords[1][1] - coords[0][1];
        } else if (i === coords.length - 1) {
            dy = coords[i][0] - coords[i - 1][0];
            dx = coords[i][1] - coords[i - 1][1];
        } else {
            dy = coords[i + 1][0] - coords[i - 1][0];
            dx = coords[i + 1][1] - coords[i - 1][1];
        }
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len === 0) { result.push(coords[i]); continue; }
        // Perpendicular: rotate 90° → (-dy, dx)
        const nx = -dy / len;
        const ny = dx / len;
        result.push([coords[i][0] + nx * offset, coords[i][1] + ny * offset]);
    }
    return result;
}

// ==========================================
// VERİ — Duraklar ve simüle araçlar
// ==========================================

const STATION_LIST = STATIONS_EAST;
const ISTANBUL_CENTER: [number, number] = [41.0270, 28.8850];
const DEFAULT_ZOOM = 11;

// Harita modları
const MAP_TILES = {
    dark: {
        url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> | &copy; <a href="https://carto.com/">CARTO</a>',
        label: '🌙 Dark',
    },
    satellite: {
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attribution: '&copy; <a href="https://www.esri.com/">Esri</a> | Maxar, Earthstar Geographics',
        label: '🛰️ Uydu',
    },
    street: {
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        label: '🗺️ Sokak',
    },
} as const;

type MapTileMode = keyof typeof MAP_TILES;

const NUM_VEHICLES = 10;
const UPDATE_INTERVAL = 2000;

interface SimVehicle {
    id: number;
    code: string;
    stationIndex: number;
    progress: number;
    speed: number;
    lat: number;
    lng: number;
    status: 'normal' | 'approaching' | 'at_station' | 'slow' | 'fast';
    nextStation: string;
    slotWait: boolean;
}

function initVehicles(): SimVehicle[] {
    const vehicles: SimVehicle[] = [];
    for (let i = 0; i < NUM_VEHICLES; i++) {
        const idx = Math.floor((i / NUM_VEHICLES) * STATION_LIST.length);
        const s = STATION_LIST[idx];
        vehicles.push({
            id: i + 1,
            code: `MB${String(i + 1).padStart(3, '0')}`,
            stationIndex: idx,
            progress: 0,
            speed: 30 + Math.random() * 20,
            lat: s.latitude + (Math.random() - 0.5) * 0.001,
            lng: s.longitude + (Math.random() - 0.5) * 0.001,
            status: 'normal',
            nextStation: STATION_LIST[Math.min(idx + 1, STATION_LIST.length - 1)].name,
            slotWait: false,
        });
    }
    return vehicles;
}

function updateVehicle(v: SimVehicle): SimVehicle {
    const cur = STATION_LIST[v.stationIndex];
    let nextIdx = v.stationIndex + 1;
    if (nextIdx >= STATION_LIST.length) nextIdx = 0;
    const next = STATION_LIST[nextIdx];
    const dist = haversineDistance(cur.latitude, cur.longitude, next.latitude, next.longitude);
    const rushFactor = isRushHour() ? 0.6 : 1.0;
    const newSpeed = (30 + Math.random() * 25) * rushFactor;
    const metersPerTick = (newSpeed * 1000 / 3600) * (UPDATE_INTERVAL / 1000);
    const newProgress = v.progress + metersPerTick / dist;

    if (newProgress >= 1) {
        // Durağa ulaştı, kısa bekleme sonra ilerle
        const distToNext = haversineDistance(next.latitude, next.longitude,
            STATION_LIST[Math.min(nextIdx + 1, STATION_LIST.length - 1)].latitude,
            STATION_LIST[Math.min(nextIdx + 1, STATION_LIST.length - 1)].longitude);
        return {
            ...v,
            stationIndex: nextIdx,
            progress: 0,
            speed: newSpeed,
            lat: next.latitude,
            lng: next.longitude,
            status: 'at_station',
            nextStation: STATION_LIST[Math.min(nextIdx + 1, STATION_LIST.length - 1)].name,
            slotWait: Math.random() > 0.6,
        };
    }

    const bearing = calculateBearing(cur.latitude, cur.longitude, next.latitude, next.longitude);
    const pos = moveAlongBearing(cur.latitude, cur.longitude, bearing, dist * newProgress);
    const distToStation = dist * (1 - newProgress);

    let status: SimVehicle['status'] = 'normal';
    if (distToStation < 500) status = 'approaching';
    if (newSpeed < 25) status = 'slow';
    if (newSpeed > 50) status = 'fast';

    return {
        ...v,
        progress: newProgress,
        speed: newSpeed,
        lat: pos.latitude,
        lng: pos.longitude,
        status,
        nextStation: next.name,
        slotWait: false,
    };
}

// ==========================================
// Harita içi araç ikonları
// ==========================================

function vehicleIcon(status: string) {
    const colors: Record<string, string> = {
        normal: '#4CAF50',
        approaching: '#FF9800',
        at_station: '#2196F3',
        slow: '#F44336',
        fast: '#9C27B0',
    };
    const c = colors[status] || '#4CAF50';
    return L.divIcon({
        className: '',
        html: `<div style="
      width:28px;height:28px;border-radius:50%;
      background:${c};border:3px solid #fff;
      box-shadow:0 2px 8px rgba(0,0,0,0.4);
      display:flex;align-items:center;justify-content:center;
      font-size:14px;color:#fff;font-weight:700;
      transition:all 0.5s ease;
    ">🚍</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
    });
}

function stationIcon(name: string, seq: number, isHighlight: boolean = false) {
    const dotSize = isHighlight ? 14 : 10;
    const color = isHighlight ? '#FF5722' : '#FF9800';
    const fontSize = isHighlight ? '11px' : '10px';
    const fontWeight = isHighlight ? '700' : '600';
    return L.divIcon({
        className: '',
        html: `<div style="display:flex;flex-direction:column;align-items:center;pointer-events:auto;">
      <div style="
        width:${dotSize}px;height:${dotSize}px;border-radius:50%;
        background:${color};border:2px solid #fff;
        box-shadow:0 2px 6px rgba(0,0,0,0.5);
      "></div>
      <div style="
        margin-top:2px;padding:1px 4px;border-radius:3px;
        background:rgba(0,0,0,0.75);color:#fff;
        font-size:${fontSize};font-weight:${fontWeight};
        font-family:Inter,sans-serif;
        white-space:nowrap;line-height:1.3;
        text-shadow:0 1px 2px rgba(0,0,0,0.8);
      ">${seq}. ${name}</div>
    </div>`,
        iconSize: [0, 0],
        iconAnchor: [0, dotSize / 2],
    });
}

// ==========================================
// ANA UYGULAMA
// ==========================================

const App: React.FC = () => {
    const [vehicles, setVehicles] = useState<SimVehicle[]>(initVehicles);
    const [selectedVehicle, setSelectedVehicle] = useState<SimVehicle | null>(null);
    const [tick, setTick] = useState(0);
    const [isPaused, setIsPaused] = useState(false);
    const [stats, setStats] = useState({ totalSaved: 0, optimizations: 0 });
    const [mapTile, setMapTile] = useState<MapTileMode>('dark');

    // Araçları güncelle
    useEffect(() => {
        if (isPaused) return;
        const timer = setInterval(() => {
            setVehicles(prev => {
                const updated = prev.map(updateVehicle);
                // Çift durma tasarrufu simülasyonu
                const atStation = updated.filter(v => v.status === 'at_station' && v.slotWait);
                if (atStation.length > 0) {
                    setStats(s => ({
                        totalSaved: s.totalSaved + atStation.length * 18,
                        optimizations: s.optimizations + atStation.length,
                    }));
                }
                return updated;
            });
            setTick(t => t + 1);
        }, UPDATE_INTERVAL);
        return () => clearInterval(timer);
    }, [isPaused]);

    // Güzergah — artık edge-based offset rendering kullanılıyor (aşağıda)

    const statusLabel: Record<string, string> = {
        normal: '🟢 Normal',
        approaching: '🟡 Durağa yaklaşıyor',
        at_station: '🔵 Durakta',
        slow: '🔴 Yavaş',
        fast: '🟣 Hızlı',
    };

    return (
        <div className="dashboard">
            {/* SOL PANEL */}
            <aside className="sidebar">
                <div className="sidebar-header">
                    <h1>🚍 Metrobüs</h1>
                    <span className="badge">CANLI</span>
                </div>

                {/* İstatistikler */}
                <div className="stats-grid">
                    <div className="stat-card">
                        <div className="stat-value">{vehicles.length}</div>
                        <div className="stat-label">Aktif Araç</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">{STATION_LIST.length}</div>
                        <div className="stat-label">Durak</div>
                    </div>
                    <div className="stat-card accent">
                        <div className="stat-value">{Math.round(stats.totalSaved / 60)}dk</div>
                        <div className="stat-label">Tasarruf</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">{stats.optimizations}</div>
                        <div className="stat-label">Optimizasyon</div>
                    </div>
                </div>

                {/* Rush Hour durumu */}
                <div className={`rush-indicator ${isRushHour() ? 'active' : ''}`}>
                    {isRushHour() ? '🔴 PİK SAAT — Yoğun trafik' : '🟢 Normal trafik akışı'}
                </div>

                {/* Kontroller */}
                <div className="controls">
                    <button className={`btn ${isPaused ? 'btn-green' : 'btn-red'}`} onClick={() => setIsPaused(!isPaused)}>
                        {isPaused ? '▶️ Başlat' : '⏸️ Duraklat'}
                    </button>
                </div>

                {/* Araç listesi */}
                <div className="vehicle-list-header">
                    <h2>Araçlar</h2>
                </div>
                <div className="vehicle-list">
                    {vehicles.map(v => (
                        <div
                            key={v.id}
                            className={`vehicle-card ${selectedVehicle?.id === v.id ? 'selected' : ''}`}
                            onClick={() => setSelectedVehicle(v)}
                        >
                            <div className="vehicle-card-header">
                                <span className="vehicle-code">{v.code}</span>
                                <span className={`vehicle-status status-${v.status}`}>
                                    {statusLabel[v.status]}
                                </span>
                            </div>
                            <div className="vehicle-card-body">
                                <div className="vehicle-info">
                                    <span>📍 {v.nextStation}</span>
                                </div>
                                <div className="vehicle-info">
                                    <span>🏎️ {v.speed.toFixed(0)} km/s</span>
                                    {v.slotWait && <span className="slot-badge">🎯 Optimized</span>}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </aside>

            {/* HARİTA */}
            <main className="map-container">
                <MapContainer
                    center={ISTANBUL_CENTER}
                    zoom={DEFAULT_ZOOM}
                    style={{ width: '100%', height: '100%' }}
                    zoomControl={false}
                >
                    <TileLayer
                        key={mapTile}
                        attribution={MAP_TILES[mapTile].attribution}
                        url={MAP_TILES[mapTile].url}
                    />

                    {/* Harita mod değiştirici */}
                    <div style={{
                        position: 'absolute', top: 12, right: 12, zIndex: 1000,
                        display: 'flex', gap: 4, background: 'rgba(0,0,0,0.7)',
                        borderRadius: 8, padding: 4,
                    }}>
                        {(Object.keys(MAP_TILES) as MapTileMode[]).map(mode => (
                            <button
                                key={mode}
                                onClick={() => setMapTile(mode)}
                                style={{
                                    padding: '6px 12px', border: 'none', borderRadius: 6,
                                    background: mapTile === mode ? '#4FC3F7' : 'transparent',
                                    color: mapTile === mode ? '#000' : '#fff',
                                    fontWeight: mapTile === mode ? 700 : 400,
                                    cursor: 'pointer', fontSize: 13, transition: 'all 0.2s',
                                }}
                            >
                                {MAP_TILES[mode].label}
                            </button>
                        ))}
                    </div>

                    {/* Gidiş — shared segmentlerde mikro-offset (+1.5m) */}
                    {ROUTE_NETWORK.edges.gidis.map((edge) => (
                        <Polyline
                            key={edge.id}
                            positions={edge.isSharedGeometry
                                ? offsetPolyline(edge.geometry, 0.000015)
                                : edge.geometry}
                            pathOptions={{ color: '#4FC3F7', weight: 4, opacity: 0.85 }}
                        />
                    ))}

                    {/* Dönüş — shared segmentlerde mikro-offset (-1.5m) */}
                    {ROUTE_NETWORK.edges.donus.map((edge) => (
                        <Polyline
                            key={edge.id}
                            positions={edge.isSharedGeometry
                                ? offsetPolyline(edge.geometry, -0.000015)
                                : edge.geometry}
                            pathOptions={{ color: '#FF9800', weight: 4, opacity: 0.85 }}
                        />
                    ))}
                    {/* Durak platform şeritleri — OSM platform way geometrileri */}
                    {PLATFORM_GEOMETRIES.map((p) => (
                        <Polyline
                            key={`platform-${p.id}`}
                            positions={p.geometry}
                            pathOptions={{
                                color: '#76FF03',
                                weight: 5,
                                opacity: 0.95,
                                dashArray: undefined,
                            }}
                        >
                            <Popup>{p.name}</Popup>
                        </Polyline>
                    ))}

                    {/* Durak işaretçileri */}
                    {STATION_LIST.map((s, i) => (
                        <Marker
                            key={s.code}
                            position={[s.latitude, s.longitude]}
                            icon={stationIcon(s.name, s.sequenceOrder, i % 5 === 0)}
                        >
                            <Popup>
                                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '160px' }}>
                                    <strong style={{ fontSize: '14px' }}>{s.name}</strong>
                                    <div style={{ color: '#888', fontSize: '12px', marginTop: '4px' }}>
                                        Kod: {s.code} | Sıra: {s.sequenceOrder}
                                    </div>
                                    <div style={{ color: '#888', fontSize: '11px', marginTop: '2px' }}>
                                        📍 {s.latitude.toFixed(4)}, {s.longitude.toFixed(4)}
                                    </div>
                                </div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Araç işaretçileri */}
                    {vehicles.map(v => (
                        <Marker
                            key={v.id}
                            position={[v.lat, v.lng]}
                            icon={vehicleIcon(v.status)}
                            eventHandlers={{ click: () => setSelectedVehicle(v) }}
                        >
                            <Popup>
                                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '180px' }}>
                                    <strong style={{ fontSize: '15px' }}>🚍 {v.code}</strong>
                                    <div style={{ marginTop: '6px', fontSize: '12px' }}>
                                        <div>Hız: <b>{v.speed.toFixed(0)} km/s</b></div>
                                        <div>Sonraki: <b>{v.nextStation}</b></div>
                                        <div>Durum: {statusLabel[v.status]}</div>
                                        {v.slotWait && <div style={{ color: '#FF9800', marginTop: '4px' }}>🎯 Çift durma optimize edildi</div>}
                                    </div>
                                </div>
                            </Popup>
                        </Marker>
                    ))}
                </MapContainer>

                {/* Seçili araç detay paneli */}
                {selectedVehicle && (
                    <div className="detail-panel">
                        <div className="detail-header">
                            <h3>🚍 {selectedVehicle.code}</h3>
                            <button className="close-btn" onClick={() => setSelectedVehicle(null)}>✕</button>
                        </div>
                        <div className="detail-body">
                            <div className="detail-row">
                                <span className="detail-label">Durum</span>
                                <span className={`vehicle-status status-${selectedVehicle.status}`}>
                                    {statusLabel[selectedVehicle.status]}
                                </span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Hız</span>
                                <span className="detail-value">{selectedVehicle.speed.toFixed(0)} km/s</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Sonraki Durak</span>
                                <span className="detail-value">{selectedVehicle.nextStation}</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Konum</span>
                                <span className="detail-value" style={{ fontSize: '11px' }}>
                                    {selectedVehicle.lat.toFixed(4)}, {selectedVehicle.lng.toFixed(4)}
                                </span>
                            </div>
                            {selectedVehicle.slotWait && (
                                <div className="detail-alert">
                                    🎯 Çift durma önleme aktif — slot boşalması bekleniyor
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
};

export default App;
