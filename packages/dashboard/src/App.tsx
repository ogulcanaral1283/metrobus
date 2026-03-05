import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { STATIONS_EAST, ROUTE_NETWORK, GIDIS_LANE, DONUS_LANE, PLATFORM_GEOMETRIES, GIDIS_SYNTHETIC_LANES, DONUS_SYNTHETIC_LANES, SHARED_WAY_IDS, haversineDistance, calculateBearing, moveAlongBearing, isRushHour, formatDuration, SimEngine } from '@metrobus/shared';
import type { SimVehicle, SimState } from '@metrobus/shared';

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

const SIM_TICK_MS = 50; // 20 FPS
const NUM_VEHICLES = 10;

/** Araç fazına göre ikon rengi */
function phaseColor(vehicle: SimVehicle): string {
    const speedKmh = vehicle.speed * 3.6;
    if (vehicle.phase === 'stopped') return '#2196F3';      // Mavi — durakta
    if (vehicle.phase === 'approaching') return '#FF9800';   // Turuncu — yaklaşım
    if (vehicle.phase === 'departing') return '#8BC34A';     // Açık yeşil — kalkış
    if (speedKmh < 15) return '#F44336';                     // Kırmızı — yavaş/trafik
    if (speedKmh > 60) return '#9C27B0';                     // Mor — hızlı
    return '#4CAF50';                                        // Yeşil — normal
}

// ==========================================
// Harita içi araç ikonları
// ==========================================

function vehicleIcon(vehicle: SimVehicle) {
    const c = phaseColor(vehicle);
    const speedKmh = Math.round(vehicle.speed * 3.6);
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
    const gidisRef = useRef<SimEngine | null>(null);
    const donusRef = useRef<SimEngine | null>(null);
    const [simState, setSimState] = useState<{ gidis: SimState | null; donus: SimState | null }>({ gidis: null, donus: null });
    const [selectedVehicle, setSelectedVehicle] = useState<SimVehicle | null>(null);
    const [tick, setTick] = useState(0);
    const [isPaused, setIsPaused] = useState(false);
    const [timeScale, setTimeScale] = useState(5);
    const [mapTile, setMapTile] = useState<MapTileMode>('dark');

    // Çift yönlü engine init
    useEffect(() => {
        const g = new SimEngine(ROUTE_NETWORK.edges.gidis, ROUTE_NETWORK.stops.gidis, 'gidis', { timeScale });
        g.init(8);
        gidisRef.current = g;

        const d = new SimEngine(ROUTE_NETWORK.edges.donus, ROUTE_NETWORK.stops.donus, 'donus', { timeScale });
        d.init(8);
        donusRef.current = d;

        setSimState({ gidis: g.getState(), donus: d.getState() });
    }, []);

    // Simülasyon döngüsü
    useEffect(() => {
        if (isPaused || !gidisRef.current || !donusRef.current) return;
        let lastTime = performance.now();
        let frameId: number;

        const loop = (now: number) => {
            const dt = Math.min((now - lastTime) / 1000, 0.1);
            lastTime = now;
            const gs = gidisRef.current!.tick(dt);
            const ds = donusRef.current!.tick(dt);
            setSimState({ gidis: gs, donus: ds });
            setTick(t => t + 1);
            frameId = requestAnimationFrame(loop);
        };
        frameId = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(frameId);
    }, [isPaused, timeScale]);

    useEffect(() => {
        gidisRef.current?.setTimeScale(timeScale);
        donusRef.current?.setTimeScale(timeScale);
    }, [timeScale]);

    const vehicles = [
        ...(simState.gidis?.vehicles ?? []),
        ...(simState.donus?.vehicles ?? []),
    ];

    const getEngine = (dir: 'gidis' | 'donus') => dir === 'gidis' ? gidisRef.current : donusRef.current;

    // Per-vehicle komutlar
    const cmdStop = (v: SimVehicle) => getEngine(v.direction)?.stopVehicle(v.id);
    const cmdSlow = (v: SimVehicle) => getEngine(v.direction)?.slowVehicle(v.id);
    const cmdRelease = (v: SimVehicle) => getEngine(v.direction)?.releaseVehicle(v.id);
    const cmdAddVehicle = (dir: 'gidis' | 'donus') => getEngine(dir)?.spawnVehicle();
    const cmdRemoveVehicle = (v: SimVehicle) => {
        getEngine(v.direction)?.removeVehicle(v.id);
        if (selectedVehicle?.id === v.id) setSelectedVehicle(null);
    };

    const phaseLabel: Record<string, string> = {
        cruising: '🟢 Seyir',
        approaching: '🟡 Yaklaşıyor',
        stopped: '🔵 Durakta',
        departing: '🟢 Kalkış',
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
                        <div className="stat-value">{vehicles.filter(v => v.direction === 'gidis').length}</div>
                        <div className="stat-label">🔵 Gidiş</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-value">{vehicles.filter(v => v.direction === 'donus').length}</div>
                        <div className="stat-label">🟠 Dönüş</div>
                    </div>
                </div>

                {/* Rush Hour durumu */}
                <div className={`rush-indicator ${simState.gidis?.isRushHour ? 'active' : ''}`}>
                    {simState.gidis?.isRushHour ? '🔴 PİK SAAT — Yoğun trafik' : '🟢 Normal trafik akışı'}
                </div>

                {/* Kontroller */}
                <div className="controls">
                    <button className={`btn ${isPaused ? 'btn-green' : 'btn-red'}`} onClick={() => setIsPaused(!isPaused)}>
                        {isPaused ? '▶️ Başlat' : '⏸️ Duraklat'}
                    </button>
                </div>

                {/* Hız çarpanı */}
                <div style={{ padding: '8px 16px' }}>
                    <label style={{ color: '#aaa', fontSize: '11px' }}>Sim Hızı: {timeScale}x</label>
                    <input type="range" min={1} max={20} step={1} value={timeScale}
                        onChange={e => setTimeScale(Number(e.target.value))}
                        style={{ width: '100%', accentColor: '#FF9800' }} />
                </div>

                {/* Araç ekle */}
                <div style={{ display: 'flex', gap: '6px', padding: '0 16px 8px' }}>
                    <button className="btn" style={{ flex: 1, fontSize: '11px', padding: '6px' }}
                        onClick={() => cmdAddVehicle('gidis')}>✚ Gidiş Araç</button>
                    <button className="btn" style={{ flex: 1, fontSize: '11px', padding: '6px' }}
                        onClick={() => cmdAddVehicle('donus')}>✚ Dönüş Araç</button>
                </div>

                {/* Araç listesi */}
                <div className="vehicle-list-header">
                    <h2>Araçlar ({vehicles.length})</h2>
                </div>
                <div className="vehicle-list">
                    {vehicles.map(v => (
                        <div
                            key={`${v.direction}-${v.id}`}
                            className={`vehicle-card ${selectedVehicle?.id === v.id && selectedVehicle?.direction === v.direction ? 'selected' : ''}`}
                            onClick={() => setSelectedVehicle(v)}
                        >
                            <div className="vehicle-card-header">
                                <span className="vehicle-code">
                                    <span style={{ color: v.direction === 'gidis' ? '#42A5F5' : '#FFA726', marginRight: '4px' }}>
                                        {v.direction === 'gidis' ? '→' : '←'}
                                    </span>
                                    {v.code}
                                </span>
                                <span className={`vehicle-status status-${v.phase}`}>
                                    {phaseLabel[v.phase]}
                                </span>
                            </div>
                            <div className="vehicle-card-body">
                                <div className="vehicle-info">
                                    <span>🏎️ {(v.speed * 3.6).toFixed(0)} km/h</span>
                                    {v.manualOverride !== null && <span style={{ color: '#F44336', fontSize: '10px', marginLeft: '4px' }}>⬤ MANUEL</span>}
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

                    {/* Katman 1: Non-shared gidiş edge'leri (gerçek OSM pozisyonu) */}
                    {ROUTE_NETWORK.edges.gidis
                        .filter((edge) => !SHARED_WAY_IDS.has(edge.osmWayId))
                        .map((edge) => (
                            <Polyline
                                key={edge.id}
                                positions={edge.geometry}
                                pathOptions={{ color: '#4FC3F7', weight: 3, opacity: 0.85 }}
                            />
                        ))}

                    {/* Katman 1: Non-shared dönüş edge'leri (gerçek OSM pozisyonu) */}
                    {ROUTE_NETWORK.edges.donus
                        .filter((edge) => !SHARED_WAY_IDS.has(edge.osmWayId))
                        .map((edge) => (
                            <Polyline
                                key={edge.id}
                                positions={edge.geometry}
                                pathOptions={{ color: '#FF9800', weight: 3, opacity: 0.85 }}
                            />
                        ))}

                    {/* Sentetik gidiş — shared koridorlar +5m sağa */}
                    {GIDIS_SYNTHETIC_LANES.map((lane) => (
                        <Polyline
                            key={`sg-${lane.corridorIndex}`}
                            positions={lane.geometry}
                            pathOptions={{ color: '#4FC3F7', weight: 3, opacity: 0.85 }}
                        />
                    ))}

                    {/* Sentetik dönüş — shared koridorlar -5m sola */}
                    {DONUS_SYNTHETIC_LANES.map((lane) => (
                        <Polyline
                            key={`sd-${lane.corridorIndex}`}
                            positions={lane.geometry}
                            pathOptions={{ color: '#FF9800', weight: 3, opacity: 0.85 }}
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
                            position={[v.latitude, v.longitude]}
                            icon={vehicleIcon(v)}
                            eventHandlers={{ click: () => setSelectedVehicle(v) }}
                        >
                            <Popup>
                                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '180px' }}>
                                    <strong style={{ fontSize: '15px' }}>🚍 {v.code}</strong>
                                    <div style={{ marginTop: '6px', fontSize: '12px' }}>
                                        <div>Hız: <b>{(v.speed * 3.6).toFixed(0)} km/h</b></div>
                                        <div>Faz: {phaseLabel[v.phase]}</div>
                                        <div>Pozisyon: <b>{v.positionMeters.toFixed(0)}m</b></div>
                                        <div>İvme: <b>{v.acceleration.toFixed(2)} m/s²</b></div>
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
                            <h3>🚍 {selectedVehicle.code}
                                <span style={{ fontSize: '11px', color: selectedVehicle.direction === 'gidis' ? '#42A5F5' : '#FFA726', marginLeft: '8px' }}>
                                    {selectedVehicle.direction === 'gidis' ? '→ Gidiş' : '← Dönüş'}
                                </span>
                            </h3>
                            <button className="close-btn" onClick={() => setSelectedVehicle(null)}>✕</button>
                        </div>
                        <div className="detail-body">
                            <div className="detail-row">
                                <span className="detail-label">Durum</span>
                                <span className={`vehicle-status status-${selectedVehicle.phase}`}>
                                    {phaseLabel[selectedVehicle.phase]}
                                </span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Hız</span>
                                <span className="detail-value">{(selectedVehicle.speed * 3.6).toFixed(1)} km/h</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">İvme</span>
                                <span className="detail-value">{selectedVehicle.acceleration.toFixed(2)} m/s²</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Pozisyon</span>
                                <span className="detail-value">{selectedVehicle.positionMeters.toFixed(0)} m</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Durak</span>
                                <span className="detail-value">{selectedVehicle.totalStops} kez</span>
                            </div>
                            {selectedVehicle.manualOverride !== null && (
                                <div style={{ background: 'rgba(244,67,54,0.15)', padding: '6px 10px', borderRadius: '6px', color: '#F44336', fontSize: '12px', marginTop: '4px' }}>
                                    ⚠️ Manuel kontrol aktif — hedef hız: {selectedVehicle.manualOverride === 0 ? 'DURDURULDU' : `${(selectedVehicle.manualOverride * 3.6).toFixed(0)} km/h`}
                                </div>
                            )}
                        </div>
                        {/* Araç kontrol butonları */}
                        <div style={{ display: 'flex', gap: '4px', padding: '8px 12px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                            <button onClick={() => cmdStop(selectedVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#F44336', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                ⏹ Durdur
                            </button>
                            <button onClick={() => cmdSlow(selectedVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#FF9800', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                🐌 Yavaşlat
                            </button>
                            <button onClick={() => cmdRelease(selectedVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#4CAF50', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                ▶️ Serbest
                            </button>
                            <button onClick={() => cmdRemoveVehicle(selectedVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#616161', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                🗑️ Kaldır
                            </button>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
};

export default App;
