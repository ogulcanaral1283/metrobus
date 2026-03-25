import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { STATIONS_EAST, ROUTE_NETWORK, GIDIS_LANE, DONUS_LANE, PLATFORM_GEOMETRIES, GIDIS_SYNTHETIC_LANES, DONUS_SYNTHETIC_LANES, SHARED_WAY_IDS, PLATFORM_ENTRIES, STATION_SLOTS, haversineDistance, calculateBearing, moveAlongBearing, isRushHour, formatDuration, SimEngine } from '@metrobus/shared';
import type { SimVehicle, SimState } from '@metrobus/shared';

import 'leaflet/dist/leaflet.css';

// Bunching pulse CSS animation (inject once)
const BUNCHING_STYLE_ID = 'bunching-pulse-style';
if (typeof document !== 'undefined' && !document.getElementById(BUNCHING_STYLE_ID)) {
    const style = document.createElement('style');
    style.id = BUNCHING_STYLE_ID;
    style.textContent = `
        @keyframes bunchPulse {
            0%, 100% { box-shadow: 0 0 4px 2px rgba(244,67,54,0.4); }
            50% { box-shadow: 0 0 12px 6px rgba(244,67,54,0.8); }
        }
        .bunch-pulse { animation: bunchPulse 1s ease-in-out infinite; }
        @keyframes bunchPulseWarn {
            0%, 100% { box-shadow: 0 0 4px 2px rgba(255,152,0,0.3); }
            50% { box-shadow: 0 0 10px 5px rgba(255,152,0,0.6); }
        }
        .bunch-pulse-warn { animation: bunchPulseWarn 1.5s ease-in-out infinite; }
        @keyframes speedFilterPulse {
            0%, 100% { box-shadow: 0 0 4px 2px rgba(0,188,212,0.3); }
            50% { box-shadow: 0 0 10px 5px rgba(0,188,212,0.7); }
        }
        .speed-filter-pulse { animation: speedFilterPulse 1.2s ease-in-out infinite; }
        @keyframes bunchAcceptPulse {
            0%, 100% { box-shadow: 0 0 4px 2px rgba(255,87,34,0.3); }
            50% { box-shadow: 0 0 8px 4px rgba(255,87,34,0.6); }
        }
        .bunch-accept-pulse { animation: bunchAcceptPulse 1.5s ease-in-out infinite; }
    `;
    document.head.appendChild(style);
}

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
    if (vehicle.phase === 'approaching') return '#FFD600';   // Sarı — yavaşlıyor
    if (vehicle.phase === 'queued') return '#E91E63';         // Pembe — kuyrukta
    if (vehicle.phase === 'docking') return '#00BCD4';        // Cyan — yanaşıyor
    if (vehicle.phase === 'stopped') {
        // Kapı durumuna göre alt renkler
        const dwell = vehicle.dwellRemaining;
        const total = vehicle.lastDwellTime || 15;
        if (total - dwell < 2) return '#00BCD4';             // Cyan — kapı açılıyor
        if (dwell < 2) return '#FF5722';                      // Kırmızı-turuncu — kapı kapanıyor
        return '#4CAF50';                                     // Yeşil — yolcu operasyonu (kapı açık)
    }
    if (vehicle.phase === 'departing') return '#9C27B0';      // Mor — kalkış
    if (vehicle.phase === 'doorsClosed') return '#FF5722';    // Kırmızı-turuncu — kapı kapandı
    if (vehicle.phase === 'blocked') return '#FF3D00';        // Turuncu-kırmızı — blokeli
    // cruising
    const speedKmh = vehicle.speed * 3.6;
    if (speedKmh < 15) return '#F44336';                      // Kırmızı — yavaş/trafik
    return '#2196F3';                                         // Mavi — seyir
}

// ==========================================
// Harita içi araç ikonları
// ==========================================

function vehicleIcon(vehicle: SimVehicle) {
    const c = phaseColor(vehicle);
    const v = vehicle as any;
    const isBunched = v.isBunched || false;
    const warning = v.bunchingWarning;
    const predictive = v.predictiveDecision;

    // Pulse class önceliği: predictive > bunching
    let pulseClass = '';
    let border = '#fff';
    if (predictive?.decision === 'SPEED_FILTER') {
        pulseClass = 'speed-filter-pulse';
        border = '#00BCD4';  // Cyan
    } else if (predictive?.decision === 'BUNCHING_ACCEPT') {
        pulseClass = 'bunch-accept-pulse';
        border = '#FF5722';  // Turuncu-kırmızı
    } else if (warning === 'critical') {
        pulseClass = 'bunch-pulse';
        border = '#F44336';
    } else if (warning === 'warning') {
        pulseClass = 'bunch-pulse-warn';
        border = isBunched ? '#F44336' : '#fff';
    } else if (isBunched) {
        border = '#F44336';
    }

    // Araç boyutları (harita üzerinde piksel)
    const vt = vehicle.vehicleType;
    const busW = vt?.code === 'AK' ? 36 : 30;
    const busH = 12;
    const rot = (vehicle.heading || 0) - 90;
    const typeCode = vt?.code || 'MB';
    const dirColor = vehicle.direction === 'gidis' ? '#42A5F5' : '#FFA726';

    // Predictive gösterge ikonu
    const peIndicator = predictive?.decision === 'SPEED_FILTER'
        ? `<circle cx="${busW - 3}" cy="3" r="3" fill="#00BCD4" stroke="#fff" stroke-width="0.5"/>`
        : predictive?.decision === 'BUNCHING_ACCEPT'
            ? `<circle cx="${busW - 3}" cy="3" r="3" fill="#FF5722" stroke="#fff" stroke-width="0.5"/>`
            : '';

    // Hit area büyütme: görsel boyut aynı kalır, tıklama alanı daha geniş
    const padX = 8;
    const padY = 8;
    const hitW = busW + padX * 2;
    const hitH = busH + padY * 2;

    return L.divIcon({
        className: '',
        html: `<div style="
            width:${hitW}px;height:${hitH}px;
            transform:rotate(${rot}deg);
            transform-origin:center center;
            cursor:pointer;
        ">
            <div class="${pulseClass}" style="
                position:absolute;top:${padY}px;left:${padX}px;
                width:${busW}px;height:${busH}px;
            ">
                <svg width="${busW}" height="${busH}" viewBox="0 0 ${busW} ${busH}">
                    <rect x="1" y="1" width="${busW - 2}" height="${busH - 2}" rx="3" ry="3"
                        fill="${c}" stroke="${border}" stroke-width="1.5"/>
                    <rect x="2" y="2" width="3" height="${busH - 4}" rx="1" fill="${dirColor}" opacity="0.8"/>
                    <rect x="${busW - 5}" y="2" width="3" height="${busH - 4}" rx="1" fill="#fff" opacity="0.4"/>
                    <line x1="8" y1="1.5" x2="8" y1="1.5" y2="${busH - 1.5}" stroke="#fff" stroke-width="0.5" opacity="0.3"/>
                    <text x="${busW / 2}" y="${busH / 2 + 1}" text-anchor="middle" dominant-baseline="middle"
                        font-size="6" fill="#fff" font-weight="700" font-family="Inter,sans-serif">${typeCode}</text>
                    ${peIndicator}
                </svg>
            </div>
        </div>`,
        iconSize: [hitW, hitH],
        iconAnchor: [hitW / 2, hitH / 2],
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


// Faz etiketleri (VehicleMarker ve App tarafından kullanılır)
const phaseLabel: Record<string, string> = {
    cruising: '🔵 Seyir',
    approaching: '🟡 Yavaşlıyor',
    queued: '🟠 Kuyrukta',
    docking: '🔵 Yanaşıyor',
    stopped: '🟢 Kapı Açık',
    doorsClosed: '🔴 Kapı Kapandı',
    blocked: '⛔ Blokeli',
    departing: '🟣 Kalkış',
};

/** Stopped fazında kapı durumu detaylı etiket */
function getPhaseDetail(vehicle: SimVehicle): string {
    if (vehicle.phase === 'docking') {
        return '🚛 Perona Yanaşıyor';
    }
    if (vehicle.phase === 'stopped') {
        const dwell = vehicle.dwellRemaining;
        const total = (vehicle as any).lastDwellTime || 15;
        if (total - dwell < 2) return '🚪 Kapı Açılıyor';
        return '🚏 Yolcu Operasyonu';
    }
    if (vehicle.phase === 'doorsClosed') {
        return `🚪 Kapı Kapanıyor (${vehicle.dwellRemaining.toFixed(1)}s)`;
    }
    if (vehicle.phase === 'blocked') {
        return '⛔ Önde Araç — Bekliyor';
    }
    if (vehicle.phase === 'queued') {
        return `🕐 Kuyrukta (${(vehicle as any).queueWaitTime?.toFixed(1) || '0'}s)`;
    }
    return phaseLabel[vehicle.phase] || vehicle.phase;
}

// ==========================================
// HAREKET EDEN MARKER — imperative Leaflet güncelleme
// ==========================================
const VehicleMarker: React.FC<{ vehicle: SimVehicle; onClick: () => void }> = ({ vehicle, onClick }) => {
    const markerRef = useRef<L.Marker | null>(null);

    useEffect(() => {
        const m = markerRef.current;
        if (m) {
            m.setLatLng([vehicle.latitude, vehicle.longitude]);
            m.setIcon(vehicleIcon(vehicle));
        }
    }, [vehicle.latitude, vehicle.longitude, vehicle.phase, vehicle.speed, (vehicle as any).isBunched, (vehicle as any).predictiveDecision?.decision]);

    return (
        <Marker
            ref={markerRef}
            position={[vehicle.latitude, vehicle.longitude]}
            icon={vehicleIcon(vehicle)}
            eventHandlers={{ click: onClick }}
        >
            <Popup>
                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '220px', lineHeight: '1.6' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong style={{ fontSize: '15px' }}>🚍 {vehicle.code}</strong>
                        <span style={{ fontSize: '10px', background: '#333', color: '#aaa', padding: '2px 6px', borderRadius: '3px' }}>
                            {vehicle.vehicleType?.brand || 'Mercedes'} {vehicle.vehicleType?.lengthMeters || 20}m
                        </span>
                    </div>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: phaseColor(vehicle), marginTop: '4px' }}>
                        {getPhaseDetail(vehicle)}
                    </div>
                    <hr style={{ border: 'none', borderTop: '1px solid #444', margin: '6px 0' }} />
                    <div style={{ fontSize: '11px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px' }}>
                        <span>🏎️ Hız:</span>
                        <span style={{ fontWeight: 700 }}>{(vehicle.speed * 3.6).toFixed(1)} km/h</span>
                        <span>📈 İvme:</span>
                        <span style={{ fontWeight: 700 }}>{vehicle.acceleration.toFixed(2)} m/s²</span>
                        <span>📍 Pozisyon:</span>
                        <span style={{ fontWeight: 700 }}>{(vehicle.positionMeters / 1000).toFixed(2)} km</span>
                        <span>🧭 Yön:</span>
                        <span style={{ fontWeight: 700, color: vehicle.direction === 'gidis' ? '#42A5F5' : '#FFA726' }}>
                            {vehicle.direction === 'gidis' ? '→ Gidiş' : '← Dönüş'}
                        </span>
                    </div>
                    <hr style={{ border: 'none', borderTop: '1px solid #444', margin: '6px 0' }} />
                    <div style={{ fontSize: '11px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px' }}>
                        <span>🚏 Sonraki Durak:</span>
                        <span style={{ fontWeight: 700 }}>#{vehicle.nextStopIndex}</span>
                        <span>🔢 Toplam Durak:</span>
                        <span style={{ fontWeight: 700 }}>{vehicle.totalStops}</span>
                        {vehicle.phase === 'stopped' && <>
                            <span>⏱️ Kalan Süre:</span>
                            <span style={{ fontWeight: 700, color: '#4CAF50' }}>{vehicle.dwellRemaining.toFixed(1)}s</span>
                        </>}
                        {(vehicle as any).isQueuing && <>
                            <span>⏳ Kuyruk Süresi:</span>
                            <span style={{ fontWeight: 700, color: '#E91E63' }}>{(vehicle as any).queueWaitTime.toFixed(1)}s</span>
                        </>}
                        {vehicle.phase === 'stopped' && <>
                            <span>🚪 Kapı:</span>
                            <span style={{ fontWeight: 700, color: '#4CAF50' }}>AÇIK</span>
                        </>}
                        {vehicle.phase === 'departing' && <>
                            <span>🚪 Kapı:</span>
                            <span style={{ fontWeight: 700, color: '#F44336' }}>KAPALI</span>
                        </>}
                    </div>
                    {vehicle.manualOverride !== null && (
                        <div style={{ marginTop: '4px', fontSize: '10px', color: '#F44336', fontWeight: 700 }}>
                            ⬤ MANUEL KONTROL: {vehicle.manualOverride === 0 ? 'DURDURULDU' : `Max ${vehicle.manualOverride} m/s`}
                        </div>
                    )}
                    {/* Predictive Engine Kararı */}
                    {(vehicle as any).predictiveDecision && (
                        <div style={{
                            marginTop: '4px', padding: '4px 6px', borderRadius: '4px',
                            background: (vehicle as any).predictiveDecision.decision === 'SPEED_FILTER'
                                ? 'rgba(0,188,212,0.15)' : 'rgba(255,87,34,0.15)'
                        }}>
                            <div style={{
                                fontSize: '10px', fontWeight: 700,
                                color: (vehicle as any).predictiveDecision.decision === 'SPEED_FILTER' ? '#00BCD4' : '#FF5722'
                            }}>
                                🧠 {(vehicle as any).predictiveDecision.decision === 'SPEED_FILTER' ? 'Hız Filtreleme' : 'Bunching Kabul'}
                            </div>
                            <div style={{ fontSize: '9px', color: '#aaa', marginTop: '2px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px' }}>
                                <span>Score A: <b style={{ color: '#fff' }}>{(vehicle as any).predictiveDecision.scoreA}</b></span>
                                <span>Score B: <b style={{ color: '#fff' }}>{(vehicle as any).predictiveDecision.scoreB}</b></span>
                                <span>Kazanç: <b style={{ color: (vehicle as any).predictiveDecision.timeSaved > 0 ? '#4CAF50' : '#F44336' }}>{(vehicle as any).predictiveDecision.timeSaved}s</b></span>
                                <span>Hedef: <b style={{ color: '#00BCD4' }}>{((vehicle as any).predictiveDecision.vTarget * 3.6).toFixed(0)} km/h</b></span>
                            </div>
                        </div>
                    )}
                    <div style={{ marginTop: '4px', fontSize: '9px', color: '#666' }}>
                        📐 {vehicle.latitude.toFixed(5)}, {vehicle.longitude.toFixed(5)} | H: {vehicle.heading.toFixed(0)}°
                    </div>
                </div>
            </Popup>
        </Marker>
    );
};

// ==========================================
// ANA UYGULAMA
// ==========================================

const App: React.FC = () => {
    const gidisRef = useRef<SimEngine | null>(null);
    const donusRef = useRef<SimEngine | null>(null);
    const [simState, setSimState] = useState<{ gidis: SimState | null; donus: SimState | null }>({ gidis: null, donus: null });
    const [selectedVehicleKey, setSelectedVehicleKey] = useState<{ id: number; direction: string } | null>(null);
    const [tick, setTick] = useState(0);
    const [isPaused, setIsPaused] = useState(false);
    const [timeScale, setTimeScale] = useState(5);
    const [mapTile, setMapTile] = useState<MapTileMode>('dark');

    // === TRAINING MODE ===
    const [trainingMode, setTrainingMode] = useState(false);
    const [trainingData, setTrainingData] = useState<any>(null);
    const [wsConnected, setWsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

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

    // Simülasyon döngüsü — training modda ÇALIŞMAZ
    useEffect(() => {
        if (isPaused || trainingMode || !gidisRef.current || !donusRef.current) return;
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
    }, [isPaused, timeScale, trainingMode]);

    useEffect(() => {
        gidisRef.current?.setTimeScale(timeScale);
        donusRef.current?.setTimeScale(timeScale);
    }, [timeScale]);

    // === Training WebSocket ===
    useEffect(() => {
        if (!trainingMode) {
            wsRef.current?.close();
            wsRef.current = null;
            setWsConnected(false);
            return;
        }

        let reconnectTimer: number;

        const connect = () => {
            const ws = new WebSocket('ws://localhost:8765');
            wsRef.current = ws;

            ws.onopen = () => {
                setWsConnected(true);
                console.log('[Training] WebSocket connected');
            };

            ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    setTrainingData(data);
                    // Training verisini simState'e çevir
                    if (data.vehicles) {
                        setSimState({
                            gidis: {
                                time: data.time || 0,
                                vehicles: data.vehicles,
                                trafficZones: data.trafficZones || [],
                                isRushHour: data.isRushHour || false,
                                running: true,
                                timeScale: 1,
                            },
                            donus: null,  // Eğitim modunda dönüş yok
                        });
                    }
                } catch { /* skip bad messages */ }
            };

            ws.onclose = () => {
                setWsConnected(false);
                if (trainingMode) {
                    reconnectTimer = window.setTimeout(connect, 2000);
                }
            };

            ws.onerror = () => ws.close();
        };

        connect();

        return () => {
            clearTimeout(reconnectTimer);
            wsRef.current?.close();
        };
    }, [trainingMode]);

    const vehicles = [
        ...(simState.gidis?.vehicles ?? []),
        ...(simState.donus?.vehicles ?? []),
    ];

    const getEngine = (dir: 'gidis' | 'donus') => dir === 'gidis' ? gidisRef.current : donusRef.current;

    // Seçili aracı her tick'te CANLI vehicles dizisinden bul (stale snapshot sorunu yok)
    const activeVehicle = useMemo(() => {
        if (!selectedVehicleKey) return null;
        // Önce id + direction ile tam eşleşme dene
        const exact = vehicles.find(v => v.id === selectedVehicleKey.id && v.direction === selectedVehicleKey.direction);
        if (exact) return exact;
        // Training modda veya fallback: sadece id ile
        return vehicles.find(v => v.id === selectedVehicleKey.id) || null;
    }, [vehicles, selectedVehicleKey]);

    // Araç seçim helper — sadece key'i sakla, snapshot değil
    const selectVehicle = useCallback((v: SimVehicle | null) => {
        if (v) {
            setSelectedVehicleKey({ id: v.id, direction: v.direction });
        } else {
            setSelectedVehicleKey(null);
        }
    }, []);

    // Per-vehicle komutlar
    const cmdStop = (v: SimVehicle) => getEngine(v.direction)?.stopVehicle(v.id);
    const cmdSlow = (v: SimVehicle) => getEngine(v.direction)?.slowVehicle(v.id);
    const cmdRelease = (v: SimVehicle) => getEngine(v.direction)?.releaseVehicle(v.id);
    const cmdAddVehicle = (dir: 'gidis' | 'donus') => getEngine(dir)?.spawnVehicle();
    const cmdRemoveVehicle = (v: SimVehicle) => {
        getEngine(v.direction)?.removeVehicle(v.id);
        if (selectedVehicleKey?.id === v.id) setSelectedVehicleKey(null);
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

                {/* ===== TRAINING MODE TOGGLE ===== */}
                <div style={{ padding: '0 16px 8px' }}>
                    <button
                        className={`btn ${trainingMode ? 'btn-green' : ''}`}
                        style={{ width: '100%', fontSize: '12px', padding: '8px', background: trainingMode ? '#E91E63' : '#37474F' }}
                        onClick={() => setTrainingMode(!trainingMode)}
                    >
                        {trainingMode ? '🧠 Eğitim İzleme AÇIK' : '🧠 Eğitim İzleme'}
                    </button>
                    {trainingMode && (
                        <div style={{ marginTop: '4px', fontSize: '10px', color: wsConnected ? '#4CAF50' : '#F44336', textAlign: 'center' }}>
                            {wsConnected ? '● Bağlandı (ws://localhost:8765)' : '○ Bağlanıyor...'}
                        </div>
                    )}
                </div>

                {/* Training Metrikleri */}
                {trainingMode && trainingData?.metrics && (
                    <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                        <h3 style={{ color: '#E91E63', fontSize: '12px', margin: '0 0 6px' }}>📊 Eğitim Metrikleri</h3>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', fontSize: '11px', color: '#ccc' }}>
                            <div>İterasyon: <b style={{ color: '#fff' }}>{trainingData.metrics.iteration}</b></div>
                            <div>Step: <b style={{ color: '#fff' }}>{trainingData.metrics.step}</b></div>
                            <div>Reward: <b style={{ color: trainingData.metrics.reward > 0 ? '#4CAF50' : '#F44336' }}>{trainingData.metrics.reward?.toFixed(3)}</b></div>
                            <div>Toplam R: <b style={{ color: '#fff' }}>{trainingData.metrics.totalReward?.toFixed(1)}</b></div>
                            <div>Hız: <b style={{ color: '#fff' }}>{trainingData.metrics.avgSpeed?.toFixed(1)} km/h</b></div>
                            <div>Min Gap: <b style={{ color: trainingData.metrics.minGap < 100 ? '#F44336' : '#fff' }}>{trainingData.metrics.minGap?.toFixed(0)}m</b></div>
                            <div>Duran: <b style={{ color: '#fff' }}>{trainingData.metrics.numStopped}</b></div>
                            <div>Bunching: <b style={{ color: trainingData.metrics.bunching > 0 ? '#FF9800' : '#fff' }}>{trainingData.metrics.bunching}</b></div>
                        </div>
                        {trainingData.rewardComponents && Object.keys(trainingData.rewardComponents).length > 0 && (
                            <div style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '4px' }}>
                                <div style={{ fontSize: '10px', color: '#888', marginBottom: '2px' }}>Reward Bileşenleri:</div>
                                {Object.entries(trainingData.rewardComponents).map(([k, v]: [string, any]) =>
                                    typeof v === 'number' && (
                                        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#aaa' }}>
                                            <span>{k}</span>
                                            <span style={{ color: v > 0 ? '#4CAF50' : v < 0 ? '#F44336' : '#fff' }}>{v.toFixed(4)}</span>
                                        </div>
                                    )
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* ===== BUNCHING UYARILARI ===== */}
                {trainingMode && trainingData && (trainingData.bunchingCount > 0 || trainingData.bunchingPairs?.length > 0) && (
                    <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(244,67,54,0.3)' }}>
                        <h3 style={{ color: '#F44336', fontSize: '12px', margin: '0 0 6px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            🚨 Bunching Uyarıları
                            <span style={{
                                background: '#F44336', color: '#fff', borderRadius: '10px',
                                padding: '1px 8px', fontSize: '11px', fontWeight: 700,
                            }}>{trainingData.bunchingCount}</span>
                        </h3>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '4px', fontSize: '11px', marginBottom: '6px' }}>
                            <div style={{ background: 'rgba(244,67,54,0.15)', padding: '4px 6px', borderRadius: '4px', textAlign: 'center' }}>
                                <div style={{ color: '#F44336', fontWeight: 700 }}>
                                    {trainingData.bunchingPairs?.filter((p: any) => p.severity === 'critical').length || 0}
                                </div>
                                <div style={{ color: '#aaa', fontSize: '9px' }}>Kritik (&lt;50m)</div>
                            </div>
                            <div style={{ background: 'rgba(255,152,0,0.15)', padding: '4px 6px', borderRadius: '4px', textAlign: 'center' }}>
                                <div style={{ color: '#FF9800', fontWeight: 700 }}>
                                    {trainingData.bunchingPairs?.filter((p: any) => p.severity === 'warning').length || 0}
                                </div>
                                <div style={{ color: '#aaa', fontSize: '9px' }}>Uyarı (&lt;100m)</div>
                            </div>
                            <div style={{ background: 'rgba(76,175,80,0.15)', padding: '4px 6px', borderRadius: '4px', textAlign: 'center' }}>
                                <div style={{ color: '#4CAF50', fontWeight: 700 }}>
                                    {trainingData.avgGap?.toFixed(0) || 0}m
                                </div>
                                <div style={{ color: '#aaa', fontSize: '9px' }}>Ort. Gap</div>
                            </div>
                        </div>
                        {/* Bunching çiftleri listesi */}
                        <div style={{ maxHeight: '120px', overflowY: 'auto', fontSize: '10px' }}>
                            {trainingData.bunchingPairs?.slice(0, 10).map((p: any, idx: number) => (
                                <div key={idx} style={{
                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                    padding: '3px 6px', borderRadius: '3px', marginBottom: '2px',
                                    background: p.severity === 'critical' ? 'rgba(244,67,54,0.1)' : 'rgba(255,152,0,0.08)',
                                }}>
                                    <span style={{ color: '#ccc' }}>
                                        🚍 M{String(p.id1).padStart(2, '0')} ↔ M{String(p.id2).padStart(2, '0')}
                                    </span>
                                    <span style={{
                                        color: p.severity === 'critical' ? '#F44336' : '#FF9800',
                                        fontWeight: 700,
                                    }}>{p.gap}m</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ===== PREDICTIVE ENGINE ===== */}
                {trainingMode && trainingData?.predictiveEngine && (
                    <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(0,188,212,0.3)' }}>
                        <h3 style={{ color: '#00BCD4', fontSize: '12px', margin: '0 0 6px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            🧠 Predictive Engine
                        </h3>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', fontSize: '11px' }}>
                            <div style={{ background: 'rgba(0,188,212,0.15)', padding: '4px 6px', borderRadius: '4px', textAlign: 'center' }}>
                                <div style={{ color: '#00BCD4', fontWeight: 700 }}>
                                    {trainingData.predictiveEngine.speed_filter_count || 0}
                                </div>
                                <div style={{ color: '#aaa', fontSize: '9px' }}>Hız Filtre</div>
                            </div>
                            <div style={{ background: 'rgba(255,87,34,0.15)', padding: '4px 6px', borderRadius: '4px', textAlign: 'center' }}>
                                <div style={{ color: '#FF5722', fontWeight: 700 }}>
                                    {trainingData.predictiveEngine.bunching_accept_count || 0}
                                </div>
                                <div style={{ color: '#aaa', fontSize: '9px' }}>Bunching Kabul</div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Kontroller (sim mode only) */}
                {!trainingMode && <div className="controls">
                    <button className={`btn ${isPaused ? 'btn-green' : 'btn-red'}`} onClick={() => setIsPaused(!isPaused)}>
                        {isPaused ? '▶️ Başlat' : '⏸️ Duraklat'}
                    </button>
                </div>}

                {/* Hız çarpanı (sim mode only) */}
                {!trainingMode && <div style={{ padding: '8px 16px' }}>
                    <label style={{ color: '#aaa', fontSize: '11px' }}>Sim Hızı: {timeScale}x</label>
                    <input type="range" min={1} max={20} step={1} value={timeScale}
                        onChange={e => setTimeScale(Number(e.target.value))}
                        style={{ width: '100%', accentColor: '#FF9800' }} />
                </div>}

                {/* Araç sayısı kontrolü (sim mode only) */}
                {!trainingMode && <div style={{ padding: '0 16px 8px' }}>
                    <label style={{ color: '#aaa', fontSize: '11px', display: 'block', marginBottom: '4px' }}>Araç Sayısı</label>
                    {(['gidis', 'donus'] as const).map(dir => {
                        const dirVehicles = vehicles.filter(v => v.direction === dir);
                        const label = dir === 'gidis' ? 'Gidiş' : 'Dönüş';
                        const color = dir === 'gidis' ? '#42A5F5' : '#FFA726';
                        return (
                            <div key={dir} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                                <span style={{ color, fontSize: '11px', fontWeight: 600, minWidth: '45px' }}>{label}</span>
                                <span style={{ color: '#fff', fontSize: '12px', fontWeight: 700, minWidth: '24px', textAlign: 'center' }}>{dirVehicles.length}</span>
                                <span style={{ color: '#666', fontSize: '10px' }}>→</span>
                                <input type="number" min={0} max={500} defaultValue={dirVehicles.length}
                                    style={{ width: '56px', padding: '3px 6px', fontSize: '12px', background: '#333', color: '#fff', border: `1px solid ${color}44`, borderRadius: '4px', textAlign: 'center' }}
                                    onKeyDown={e => {
                                        if (e.key !== 'Enter') return;
                                        const target = Number((e.target as HTMLInputElement).value);
                                        if (isNaN(target) || target < 0) return;
                                        const eng = getEngine(dir);
                                        if (!eng) return;
                                        const current = dirVehicles.length;
                                        if (target > current) {
                                            for (let i = 0; i < target - current; i++) eng.spawnVehicle();
                                        } else if (target < current) {
                                            for (let i = 0; i < current - target; i++) {
                                                const last = dirVehicles[dirVehicles.length - 1 - i];
                                                if (last) eng.removeVehicle(last.id);
                                            }
                                        }
                                    }}
                                />
                            </div>
                        );
                    })}
                </div>}

                {/* Araç listesi */}
                <div className="vehicle-list-header">
                    <h2>Araçlar ({vehicles.length})</h2>
                </div>
                <div className="vehicle-list">
                    {vehicles.map(v => (
                        <div
                            key={`${v.direction}-${v.id}`}
                            className={`vehicle-card ${selectedVehicleKey?.id === v.id && selectedVehicleKey?.direction === v.direction ? 'selected' : ''}`}
                            onClick={() => selectVehicle(v)}
                        >
                            <div className="vehicle-card-header">
                                <span className="vehicle-code">
                                    <span style={{ color: v.direction === 'gidis' ? '#42A5F5' : '#FFA726', marginRight: '4px' }}>
                                        {v.direction === 'gidis' ? '→' : '←'}
                                    </span>
                                    {v.code}
                                    <span style={{ fontSize: '9px', color: '#aaa', marginLeft: '4px', background: '#333', padding: '1px 3px', borderRadius: '2px' }}>
                                        {v.vehicleType?.code || 'MB'} {v.vehicleType?.lengthMeters || 20}m
                                    </span>
                                </span>
                                <span className={`vehicle-status status-${v.phase}`}>
                                    {getPhaseDetail(v)}
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

                    {/* Platform giriş noktaları — gidiş (mavi) / dönüş (turuncu) */}
                    {PLATFORM_ENTRIES.map((pe, i) => (
                        <React.Fragment key={`pe-${i}`}>
                            <CircleMarker
                                center={[pe.gidis_lat, pe.gidis_lon]}
                                radius={4}
                                pathOptions={{ color: '#42A5F5', fillColor: '#42A5F5', fillOpacity: 0.9, weight: 2 }}
                            >
                                <Popup>{pe.name} — Gidiş Giriş ({pe.length}m)</Popup>
                            </CircleMarker>
                            <CircleMarker
                                center={[pe.donus_lat, pe.donus_lon]}
                                radius={4}
                                pathOptions={{ color: '#FFA726', fillColor: '#FFA726', fillOpacity: 0.9, weight: 2 }}
                            >
                                <Popup>{pe.name} — Dönüş Giriş ({pe.length}m)</Popup>
                            </CircleMarker>
                        </React.Fragment>
                    ))}

                    {/* Durak işaretçileri */}
                    {STATION_LIST.map((s, i) => (
                        <Marker
                            key={s.code}
                            position={[s.latitude, s.longitude]}
                            icon={stationIcon(s.name, s.sequenceOrder, i % 5 === 0)}
                        >
                            <Popup>
                                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '180px' }}>
                                    <strong style={{ fontSize: '14px' }}>{s.name}</strong>
                                    <div style={{ color: '#888', fontSize: '12px', marginTop: '4px' }}>
                                        Kod: {s.code} | Sıra: {s.sequenceOrder}
                                    </div>
                                    {(() => {
                                        const slot = STATION_SLOTS.find(ss => ss.name.includes(s.name.split(' ')[0]) || s.name.includes(ss.name.split(' ')[0]));
                                        const stoppedHere = vehicles.filter(v => v.phase === 'stopped' && Math.abs(v.latitude - s.latitude) < 0.001 && Math.abs(v.longitude - s.longitude) < 0.003);
                                        const queuingHere = vehicles.filter(v => (v as any).isQueuing && Math.abs(v.latitude - s.latitude) < 0.002 && Math.abs(v.longitude - s.longitude) < 0.005);
                                        return (
                                            <>
                                                {slot && <div style={{ fontSize: '11px', marginTop: '4px', color: '#76FF03' }}>
                                                    📏 Platform: {slot.platformLengthMeters}m | 🚏 Slot: {slot.slotCount}
                                                </div>}
                                                {stoppedHere.length > 0 && <div style={{ fontSize: '11px', marginTop: '2px', color: '#2196F3' }}>
                                                    🚌 Durakta: {stoppedHere.length} araç
                                                </div>}
                                                {queuingHere.length > 0 && <div style={{ fontSize: '11px', marginTop: '2px', color: '#E91E63' }}>
                                                    ⏳ Kuyrukta: {queuingHere.length} araç
                                                </div>}
                                            </>
                                        );
                                    })()}
                                    <div style={{ color: '#666', fontSize: '10px', marginTop: '4px' }}>
                                        📍 {s.latitude.toFixed(5)}, {s.longitude.toFixed(5)}
                                    </div>
                                </div>
                            </Popup>
                        </Marker>
                    ))}

                    {/* Araç işaretçileri — pozisyon imperatively güncellenir */}
                    {vehicles.map(v => (
                        <VehicleMarker key={`${v.direction}-${v.id}`} vehicle={v} onClick={() => selectVehicle(v)} />
                    ))}

                    {/* Bunching çizgileri — bunched araç çiftleri arası kırmızı/turuncu kesikli çizgi */}
                    {trainingMode && trainingData?.bunchingPairs?.map((pair: any, idx: number) => {
                        const v1 = vehicles.find(v => v.id === pair.id1);
                        const v2 = vehicles.find(v => v.id === pair.id2);
                        if (!v1 || !v2) return null;
                        return (
                            <Polyline
                                key={`bunch-${idx}`}
                                positions={[[v1.latitude, v1.longitude], [v2.latitude, v2.longitude]]}
                                pathOptions={{
                                    color: pair.severity === 'critical' ? '#F44336' : '#FF9800',
                                    weight: pair.severity === 'critical' ? 3 : 2,
                                    opacity: 0.8,
                                    dashArray: '6, 8',
                                }}
                            />
                        );
                    })}
                </MapContainer>

                {/* Seçili araç detay paneli */}
                {activeVehicle && (
                    <div className="detail-panel">
                        <div className="detail-header">
                            <h3>🚍 {activeVehicle.code}
                                <span style={{ fontSize: '11px', color: activeVehicle.direction === 'gidis' ? '#42A5F5' : '#FFA726', marginLeft: '8px' }}>
                                    {activeVehicle.direction === 'gidis' ? '→ Gidiş' : '← Dönüş'}
                                </span>
                            </h3>
                            <button className="close-btn" onClick={() => selectVehicle(null)}>✕</button>
                        </div>
                        <div className="detail-body">
                            <div className="detail-row">
                                <span className="detail-label">Durum</span>
                                <span className={`vehicle-status status-${activeVehicle.phase}`}>
                                    {getPhaseDetail(activeVehicle)}
                                </span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Hız</span>
                                <span className="detail-value">{(activeVehicle.speed * 3.6).toFixed(1)} km/h</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">İvme</span>
                                <span className="detail-value">{activeVehicle.acceleration.toFixed(2)} m/s²</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Pozisyon</span>
                                <span className="detail-value">{activeVehicle.positionMeters.toFixed(0)} m</span>
                            </div>
                            <div className="detail-row">
                                <span className="detail-label">Durak</span>
                                <span className="detail-value">{activeVehicle.totalStops} kez</span>
                            </div>

                            {/* === DURAK BEKLEME BİLGİSİ === */}
                            {(activeVehicle.phase === 'stopped' || (activeVehicle as any).lastDwellTime > 0) && (
                                <div style={{
                                    marginTop: '8px', padding: '8px 10px', borderRadius: '8px',
                                    background: activeVehicle.phase === 'stopped'
                                        ? 'rgba(33,150,243,0.15)' : 'rgba(255,255,255,0.05)',
                                    border: activeVehicle.phase === 'stopped'
                                        ? '1px solid rgba(33,150,243,0.3)' : '1px solid rgba(255,255,255,0.1)',
                                }}>
                                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#90CAF9', marginBottom: '6px' }}>
                                        🚏 Durak Bilgisi
                                    </div>

                                    {/* Kapı Durumu */}
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                                        <span style={{
                                            width: '8px', height: '8px', borderRadius: '50%',
                                            background: activeVehicle.phase === 'stopped' ? '#4CAF50' : '#616161',
                                            boxShadow: activeVehicle.phase === 'stopped' ? '0 0 6px #4CAF50' : 'none',
                                            display: 'inline-block',
                                        }} />
                                        <span style={{ fontSize: '11px', color: activeVehicle.phase === 'stopped' ? '#4CAF50' : '#888' }}>
                                            {activeVehicle.phase === 'stopped' ? '🚪 Kapılar AÇIK' : '🚪 Kapılar Kapalı'}
                                        </span>
                                    </div>

                                    {/* Aktif Bekleme — durakta ise */}
                                    {activeVehicle.phase === 'stopped' && activeVehicle.dwellRemaining > 0 && (
                                        <div style={{ marginTop: '4px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#ccc', marginBottom: '3px' }}>
                                                <span>Kalan Süre</span>
                                                <span style={{ color: '#FF9800', fontWeight: 700, fontSize: '13px' }}>
                                                    {activeVehicle.dwellRemaining.toFixed(1)}s
                                                </span>
                                            </div>
                                            {/* Progress bar */}
                                            <div style={{
                                                height: '4px', borderRadius: '2px', background: 'rgba(255,255,255,0.1)',
                                                overflow: 'hidden',
                                            }}>
                                                <div style={{
                                                    height: '100%', borderRadius: '2px',
                                                    background: 'linear-gradient(90deg, #4CAF50, #FF9800)',
                                                    width: `${Math.min(100, (activeVehicle.dwellRemaining / Math.max((activeVehicle as any).lastDwellTime || 30, 1)) * 100)}%`,
                                                    transition: 'width 0.3s ease',
                                                }} />
                                            </div>
                                        </div>
                                    )}

                                    {/* Son Durak Süresi */}
                                    {(activeVehicle as any).lastDwellTime > 0 && (
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#aaa', marginTop: '4px' }}>
                                            <span>Son Durak Süresi</span>
                                            <span style={{ color: '#fff', fontWeight: 600 }}>
                                                {(activeVehicle as any).lastDwellTime.toFixed(1)}s
                                            </span>
                                        </div>
                                    )}

                                    {/* Kuyruk Durumu */}
                                    {(activeVehicle as any).isQueuing && (
                                        <div style={{
                                            marginTop: '4px', padding: '4px 8px', borderRadius: '4px',
                                            background: 'rgba(255,152,0,0.15)', fontSize: '11px', color: '#FF9800',
                                        }}>
                                            ⏳ Kuyrukta bekliyor — {(activeVehicle as any).queueWaitTime?.toFixed(1)}s
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* === GAP & BUNCHING BİLGİSİ === */}
                            <div style={{
                                marginTop: '8px', padding: '8px 10px', borderRadius: '8px',
                                background: (activeVehicle as any).isBunched
                                    ? 'rgba(244,67,54,0.12)' : 'rgba(255,255,255,0.04)',
                                border: (activeVehicle as any).bunchingWarning === 'critical'
                                    ? '1px solid rgba(244,67,54,0.4)'
                                    : (activeVehicle as any).bunchingWarning === 'warning'
                                        ? '1px solid rgba(255,152,0,0.3)'
                                        : '1px solid rgba(255,255,255,0.08)',
                            }}>
                                <div style={{ fontSize: '11px', fontWeight: 700, color: '#90CAF9', marginBottom: '6px' }}>
                                    📏 Araç Arası Mesafe
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', fontSize: '11px' }}>
                                    <div style={{ color: '#aaa' }}>Öndeki:
                                        <b style={{
                                            color: (activeVehicle as any).forwardGap < 50 ? '#F44336'
                                                : (activeVehicle as any).forwardGap < 100 ? '#FF9800' : '#4CAF50',
                                            marginLeft: '4px',
                                        }}>{(activeVehicle as any).forwardGap?.toFixed(0) ?? '—'}m</b>
                                    </div>
                                    <div style={{ color: '#aaa' }}>Arkadaki:
                                        <b style={{
                                            color: (activeVehicle as any).backwardGap < 50 ? '#F44336'
                                                : (activeVehicle as any).backwardGap < 100 ? '#FF9800' : '#4CAF50',
                                            marginLeft: '4px',
                                        }}>{(activeVehicle as any).backwardGap?.toFixed(0) ?? '—'}m</b>
                                    </div>
                                </div>

                                {/* Bunching uyarısı */}
                                {(activeVehicle as any).bunchingWarning && (
                                    <div style={{
                                        marginTop: '6px', padding: '4px 8px', borderRadius: '4px',
                                        background: (activeVehicle as any).bunchingWarning === 'critical'
                                            ? 'rgba(244,67,54,0.2)' : 'rgba(255,152,0,0.15)',
                                        fontSize: '11px', fontWeight: 600,
                                        color: (activeVehicle as any).bunchingWarning === 'critical' ? '#F44336' : '#FF9800',
                                    }}>
                                        {(activeVehicle as any).bunchingWarning === 'critical'
                                            ? '🚨 KRİTİK BUNCHING — Araçlar çok yakın!'
                                            : '⚠️ Bunching riski — Mesafe düşük'}
                                    </div>
                                )}

                                {/* Actor aksiyonu */}
                                {(activeVehicle as any).action && (
                                    <div style={{
                                        marginTop: '6px', display: 'flex', alignItems: 'center', gap: '6px',
                                    }}>
                                        <span style={{ fontSize: '10px', color: '#888' }}>AI Kararı:</span>
                                        <span style={{
                                            padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 700,
                                            background: ({ NORMAL: 'rgba(76,175,80,0.2)', SLOW: 'rgba(255,152,0,0.2)', FAST: 'rgba(156,39,176,0.2)', HOLD: 'rgba(33,150,243,0.2)' } as Record<string, string>)[(activeVehicle as any).action] || 'rgba(255,255,255,0.1)',
                                            color: ({ NORMAL: '#4CAF50', SLOW: '#FF9800', FAST: '#9C27B0', HOLD: '#2196F3' } as Record<string, string>)[(activeVehicle as any).action] || '#fff',
                                        }}>
                                            {({ NORMAL: '🟢 NORMAL', SLOW: '🟡 YAVAŞLA', FAST: '🟣 HIZLAN', HOLD: '🔵 BEKLE' } as Record<string, string>)[(activeVehicle as any).action] || (activeVehicle as any).action}
                                        </span>
                                    </div>
                                )}

                                {/* Yavaşlama nedeni */}
                                {(activeVehicle as any).action === 'SLOW' && (activeVehicle as any).isBunched && (
                                    <div style={{
                                        marginTop: '4px', fontSize: '10px', color: '#FF9800',
                                        fontStyle: 'italic',
                                    }}>
                                        💡 Yavaşlama nedeni: Bunching tespiti — Mesafe koruma
                                    </div>
                                )}
                                {(activeVehicle as any).action === 'HOLD' && (
                                    <div style={{
                                        marginTop: '4px', fontSize: '10px', color: '#2196F3',
                                        fontStyle: 'italic',
                                    }}>
                                        💡 Durakta ekstra bekleme — Araç arası mesafe düzenleme
                                    </div>
                                )}
                            </div>

                            {activeVehicle.manualOverride !== null && (
                                <div style={{ background: 'rgba(244,67,54,0.15)', padding: '6px 10px', borderRadius: '6px', color: '#F44336', fontSize: '12px', marginTop: '4px' }}>
                                    ⚠️ Manuel kontrol aktif — hedef hız: {activeVehicle.manualOverride === 0 ? 'DURDURULDU' : `${(activeVehicle.manualOverride * 3.6).toFixed(0)} km/h`}
                                </div>
                            )}
                        </div>
                        {/* Araç kontrol butonları */}
                        <div style={{ display: 'flex', gap: '4px', padding: '8px 12px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                            <button onClick={() => cmdStop(activeVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#F44336', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                ⏹ Durdur
                            </button>
                            <button onClick={() => cmdSlow(activeVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#FF9800', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                🐌 Yavaşlat
                            </button>
                            <button onClick={() => cmdRelease(activeVehicle)}
                                style={{ flex: 1, padding: '8px 4px', border: 'none', borderRadius: '6px', background: '#4CAF50', color: '#fff', cursor: 'pointer', fontSize: '11px', fontWeight: 600 }}>
                                ▶️ Serbest
                            </button>
                            <button onClick={() => cmdRemoveVehicle(activeVehicle)}
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
