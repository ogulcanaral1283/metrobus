import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Tooltip, Polyline, CircleMarker, useMap } from 'react-leaflet';
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
        @keyframes queuedPulse {
            0%, 100% { box-shadow: 0 0 8px 5px rgba(255,235,59,0.6); transform: scale(1); }
            50% { box-shadow: 0 0 22px 12px rgba(255,235,59,1); transform: scale(1.15); }
        }
        .queued-pulse { animation: queuedPulse 0.7s ease-in-out infinite; }
        @keyframes blockedPulse {
            0%, 100% { box-shadow: 0 0 8px 4px rgba(233,30,99,0.5); transform: scale(1); }
            50% { box-shadow: 0 0 20px 10px rgba(233,30,99,0.95); transform: scale(1.12); }
        }
        .blocked-pulse { animation: blockedPulse 0.6s ease-in-out infinite; }
        @keyframes speedFilterPulse {
            0%, 100% { box-shadow: 0 0 4px 2px rgba(0,188,212,0.3); }
            50% { box-shadow: 0 0 10px 5px rgba(0,188,212,0.7); }
        }
        .speed-filter-pulse { animation: speedFilterPulse 1.2s ease-in-out infinite; }
        @keyframes stationQueuedPulse {
            0%, 100% { box-shadow: 0 0 8px 4px rgba(255,235,59,0.5); transform: scale(1); }
            50% { box-shadow: 0 0 20px 10px rgba(255,235,59,1); transform: scale(1.4); }
        }
        .station-queued-pulse { animation: stationQueuedPulse 0.8s ease-in-out infinite; }
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
    const v = vehicle as any;
    const c = phaseColor(vehicle);
    const isBunched = v.isBunched || false;
    const predictive = v.predictiveDecision;

    const isQueued = vehicle.phase === 'queued'
        || (vehicle.phase === 'approaching' && vehicle.speed * 3.6 < 5 && !v._analytic?.isInsidePlatform);
    const isBlocked = vehicle.phase === 'blocked';
    const speedFactor = v._analytic?.speedFactor ?? 1.0;
    const isSpeedAdjusted = speedFactor < 0.95 && !isQueued && !isBlocked && !isBunched;

    // Pulse class önceliği: queued/blocked > bunching > speedAdjust
    // Queued ve blocked DAIMA kendi animasyonlarını gösterir — bunching override edemez
    // Çünkü perona giremeyen araç fiziksel durumunu açıkça göstermeli
    let pulseClass = '';
    let border = '#fff';
    if (isQueued) {
        pulseClass = 'queued-pulse';
        border = '#CCFF00';  // Fosforlu sarı — perona giremedi, dışarıda bekliyor
    } else if (isBlocked) {
        pulseClass = 'blocked-pulse';
        border = '#E91E63';  // Pembe — peronda sıkışmış
    } else if (isBunched) {
        pulseClass = 'bunch-pulse';
        border = '#F44336';  // Kırmızı — yığılma
    } else if (isSpeedAdjusted) {
        pulseClass = 'speed-filter-pulse';
        border = '#00BCD4';  // Cyan mavi — hız ayarı
    }

    // Araç boyutları (harita üzerinde piksel)
    const vt = vehicle.vehicleType;
    const busW = vt?.code === 'AK' ? 36 : 30;
    const busH = 12;
    const rot = (vehicle.heading || 0) - 90;
    const typeCode = vt?.code || 'MB';
    const dirColor = vehicle.direction === 'gidis' ? '#42A5F5' : '#FFA726';

    // Durum gösterge ikonu (köşe badge)
    const statusIndicator = isQueued
        ? `<circle cx="${busW - 3}" cy="3" r="3.5" fill="#CCFF00" stroke="#333" stroke-width="0.5"/>
           <text x="${busW - 3}" y="5.5" text-anchor="middle" font-size="5" fill="#333" font-weight="900">Q</text>`
        : isBlocked
        ? `<circle cx="${busW - 3}" cy="3" r="3.5" fill="#E91E63" stroke="#fff" stroke-width="0.5"/>
           <text x="${busW - 3}" y="5.5" text-anchor="middle" font-size="5" fill="#fff" font-weight="900">X</text>`
        : isBunched
        ? `<circle cx="${busW - 3}" cy="3" r="3.5" fill="#F44336" stroke="#fff" stroke-width="0.5"/>
           <text x="${busW - 3}" y="5.5" text-anchor="middle" font-size="5" fill="#fff" font-weight="900">B</text>`
        : isSpeedAdjusted
        ? `<circle cx="${busW - 3}" cy="3" r="3.5" fill="#00BCD4" stroke="#fff" stroke-width="0.5"/>
           <text x="${busW - 3}" y="5.5" text-anchor="middle" font-size="5" fill="#fff" font-weight="900">S</text>`
        : '';

    const hasStatus = isBunched || isBlocked || isQueued || isSpeedAdjusted;

    // Özel durum ise stroke kalınlaştır
    const strokeWidth = hasStatus ? '2.5' : '1.5';

    // Hit area büyütme
    const padX = 8;
    const padY = 8;
    const hitW = busW + padX * 2;
    const hitH = busH + padY * 2;

    return L.divIcon({
        className: '',
        html: `<div class="vehicle-marker-root ${pulseClass}" data-vid="${vehicle.id}" data-vdir="${vehicle.direction}" style="
            width:${hitW}px;height:${hitH}px;
            transform:rotate(${rot}deg);
            transform-origin:center center;
            cursor:pointer;
        ">
            <div class="${pulseClass}" style="
                position:absolute;top:${padY}px;left:${padX}px;
                width:${busW}px;height:${busH}px;
                border-radius:4px;
            ">
                <svg width="${busW}" height="${busH}" viewBox="0 0 ${busW} ${busH}">
                    <rect x="1" y="1" width="${busW - 2}" height="${busH - 2}" rx="3" ry="3"
                        fill="${c}" stroke="${border}" stroke-width="${strokeWidth}"/>
                    <rect x="2" y="2" width="3" height="${busH - 4}" rx="1" fill="${dirColor}" opacity="0.8"/>
                    <rect x="${busW - 5}" y="2" width="3" height="${busH - 4}" rx="1" fill="#fff" opacity="0.4"/>
                    <line x1="8" y1="1.5" x2="8" y1="1.5" y2="${busH - 1.5}" stroke="#fff" stroke-width="0.5" opacity="0.3"/>
                    <text x="${busW / 2}" y="${busH / 2 + 1}" text-anchor="middle" dominant-baseline="middle"
                        font-size="6" fill="#fff" font-weight="700" font-family="Inter,sans-serif">${typeCode}</text>
                    ${statusIndicator}
                </svg>
                ${isQueued ? `<div style="
                    position:absolute;top:-4px;left:50%;transform:translateX(-50%);
                    width:20px;height:3px;border-radius:2px;
                    background:#FFEB3B;pointer-events:none;
                    box-shadow:0 0 8px 2px rgba(255,235,59,0.7);
                "></div>` : ''}
                ${isBlocked ? `<div style="
                    position:absolute;top:-18px;left:50%;transform:translateX(-50%);
                    background:#E91E63;color:#fff;font-size:8px;font-weight:900;
                    padding:2px 6px;border-radius:4px;white-space:nowrap;
                    font-family:Inter,sans-serif;pointer-events:none;
                    box-shadow:0 2px 6px rgba(0,0,0,0.5);
                    letter-spacing:0.5px;
                ">🚫 BLOKE</div>` : ''}
                ${isSpeedAdjusted ? `<div style="
                    position:absolute;top:-16px;left:50%;transform:translateX(-50%);
                    background:#00BCD4;color:#fff;font-size:7px;font-weight:700;
                    padding:1px 4px;border-radius:3px;white-space:nowrap;
                    font-family:Inter,sans-serif;pointer-events:none;
                    box-shadow:0 1px 3px rgba(0,0,0,0.4);
                ">Hız Ayarı (x${speedFactor.toFixed(2)})</div>` : ''}
            </div>
        </div>`,
        iconSize: [hitW, hitH],
        iconAnchor: [hitW / 2, hitH / 2],
    });
}

function stationIcon(name: string, seq: number, isHighlight: boolean = false, slotInfo?: { occupied: number; total: number; approaching: number; queued: number; platformLen: number; rearFree: number }) {
    const dotSize = isHighlight ? 14 : 10;
    const color = isHighlight ? '#FF5722' : '#FF9800';
    const fontSize = isHighlight ? '11px' : '10px';
    const fontWeight = isHighlight ? '700' : '600';
    const hasQueued = slotInfo && slotInfo.queued > 0;

    let badgeHtml = '';
    if (slotInfo && slotInfo.total > 0) {
        const { occupied, total, approaching, queued, platformLen, rearFree } = slotInfo;
        // Doluluk rengi: fiziksel erişilebilir kapasiteye göre
        // rearFree = arkadan girilebilir boş slot sayısı
        const badgeColor = rearFree === 0 && occupied > 0 ? '#F44336' : occupied > 0 ? '#FF9800' : '#4CAF50';
        const approachHtml = approaching > 0 ? `<span style="color:#64B5F6;margin-left:3px;">+${approaching}</span>` : '';
        // Doluluk: dolu/toplam + arkadan erişilebilir boş slot
        const rearInfo = occupied > 0 ? `<span style="color:#aaa;margin-left:2px;">(↙${rearFree})</span>` : '';
        badgeHtml = `<div style="
            margin-top:1px;padding:1px 5px;border-radius:3px;
            background:rgba(0,0,0,0.85);
            font-size:9px;font-family:Inter,sans-serif;
            white-space:nowrap;line-height:1.3;
            display:flex;align-items:center;gap:4px;
        ">
            <span style="color:#aaa;">${platformLen}m</span>
            <span style="color:${badgeColor};font-weight:bold;">${occupied}/${total}</span>${rearInfo}${approachHtml}
        </div>`;
    }

    const queuedPulseClass = hasQueued ? 'station-queued-pulse' : '';
    const dotBorder = hasQueued ? '#FFEB3B' : '#fff';
    const dotShadow = hasQueued
        ? '0 0 12px 6px rgba(255,235,59,0.8)'
        : '0 2px 6px rgba(0,0,0,0.5)';

    return L.divIcon({
        className: '',
        html: `<div style="display:flex;flex-direction:column;align-items:center;pointer-events:auto;">
      <div class="${queuedPulseClass}" style="
        width:${dotSize}px;height:${dotSize}px;border-radius:50%;
        background:${hasQueued ? '#FFEB3B' : color};border:2px solid ${dotBorder};
        box-shadow:${dotShadow};
      "></div>
      <div style="
        margin-top:2px;padding:1px 4px;border-radius:3px;
        background:rgba(0,0,0,0.75);color:#fff;
        font-size:${fontSize};font-weight:${fontWeight};
        font-family:Inter,sans-serif;
        white-space:nowrap;line-height:1.3;
        text-shadow:0 1px 2px rgba(0,0,0,0.8);
      ">${seq}. ${name}</div>${badgeHtml}
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
        return '🟠 Kuyrukta';
    }
    return phaseLabel[vehicle.phase] || vehicle.phase;
}

// ==========================================
// HAREKET EDEN MARKER — imperative Leaflet güncelleme
// ==========================================
// İkon durumunu belirleyen anahtar — sadece bu değişince ikon yeniden oluşturulur
function vehicleIconKey(vehicle: SimVehicle): string {
    const v = vehicle as any;
    const bunched = v.isBunched ? 1 : 0;
    const sf = Math.round((v._analytic?.speedFactor ?? 1.0) * 20);
    return `${vehicle.phase}_${bunched}_${sf}_${vehicle.direction}`;
}

// Başlangıç ikonu — tek bir basit placeholder, gerçek ikon useEffect'te atanır
const PLACEHOLDER_ICON = L.divIcon({ className: '', html: '<div style="width:8px;height:8px;background:#666;border-radius:50%"></div>', iconSize: [8, 8], iconAnchor: [4, 4] });

const VehicleMarker: React.FC<{ vehicle: SimVehicle }> = React.memo(({ vehicle }) => {
    const markerRef = useRef<L.Marker | null>(null);
    const lastIconKey = useRef<string>('');

    useEffect(() => {
        const m = markerRef.current;
        if (!m) return;
        m.setLatLng([vehicle.latitude, vehicle.longitude]);
        // İkonu sadece durum değişince yeniden oluştur
        const key = vehicleIconKey(vehicle);
        if (key !== lastIconKey.current) {
            lastIconKey.current = key;
            m.setIcon(vehicleIcon(vehicle));
        }
        // Heading — CSS transform ile güncelle
        const el = m.getElement();
        if (el) {
            const root = el.querySelector('.vehicle-marker-root') as HTMLElement;
            if (root) {
                root.style.transform = `rotate(${(vehicle.heading || 0) - 90}deg)`;
            }
        }
        // Tooltip — bind once, update content (DOM overhead yok)
        const tip = `<b>${vehicle.code}</b> | ${(vehicle.speed * 3.6).toFixed(0)} km/h | ${vehicle.phase}`;
        if (!m.getTooltip()) {
            m.bindTooltip(tip, { direction: 'top', offset: [0, -10], opacity: 0.95 });
        } else {
            m.setTooltipContent(tip);
        }
    });

    return (
        <Marker
            ref={markerRef}
            position={[vehicle.latitude, vehicle.longitude]}
            icon={PLACEHOLDER_ICON}
            eventHandlers={{}}
        />
    );
}, (prev, next) => {
    // Sadece pozisyon veya durum değişince re-render
    return prev.vehicle.latitude === next.vehicle.latitude
        && prev.vehicle.longitude === next.vehicle.longitude
        && prev.vehicle.phase === next.vehicle.phase
        && (prev.vehicle as any).isBunched === (next.vehicle as any).isBunched
        && (prev.vehicle as any)._analytic?.speedFactor === (next.vehicle as any)._analytic?.speedFactor;
});

// ==========================================
// MAP CONTROLLER — harita referansını yakala
// ==========================================
const MapController: React.FC<{ mapRef: React.MutableRefObject<L.Map | null> }> = ({ mapRef }) => {
    const map = useMap();
    React.useEffect(() => {
        mapRef.current = map;
    }, [map, mapRef]);
    return null;
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
    const mapInstanceRef = useRef<L.Map | null>(null);

    // === TRAINING MODE ===
    const [trainingMode, setTrainingMode] = useState(false);
    const [trainingData, setTrainingData] = useState<any>(null);
    const [wsConnected, setWsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);

    // === ROUTE SEGMENT ===
    const [segStart, setSegStart] = useState(0);
    const [segEnd, setSegEnd] = useState(0);

    // === STOP PANEL ===
    const [stopPanelOpen, setStopPanelOpen] = useState(false);
    const [selectedStopIdx, setSelectedStopIdx] = useState<number | null>(null);
    const [stopSortBy, setStopSortBy] = useState<'congestion' | 'zone' | 'overflow' | 'name'>('congestion');

    // === MOTOR INCELEME ===
    const [motorInspectOpen, setMotorInspectOpen] = useState(false);

    // Bunching pair'e tıklayınca haritayı o bölgeye fly et
    const flyToBunchingPair = useCallback((pair: any) => {
        const map = mapInstanceRef.current;
        if (!map) return;
        // Training modda araçlar trainingData'dan, normal modda simState'den
        const allVehicles = trainingData?.vehicles ?? [
            ...(simState.gidis?.vehicles ?? []),
            ...(simState.donus?.vehicles ?? []),
        ];
        const v1 = allVehicles.find((v: any) => v.id === pair.id1);
        const v2 = allVehicles.find((v: any) => v.id === pair.id2);
        if (!v1 || !v2) return;
        const bounds = L.latLngBounds(
            [v1.latitude, v1.longitude],
            [v2.latitude, v2.longitude],
        );
        map.flyToBounds(bounds.pad(0.5), { maxZoom: 17, duration: 0.8 });
    }, [trainingData, simState]);

    // Araç ID'sine göre haritayı o araca fly et
    const flyToVehicle = useCallback((vehicleId: number) => {
        const map = mapInstanceRef.current;
        if (!map) return;
        const allVehicles = trainingData?.vehicles ?? [
            ...(simState.gidis?.vehicles ?? []),
            ...(simState.donus?.vehicles ?? []),
        ];
        const v = allVehicles.find((v: any) => v.id === vehicleId);
        if (!v) return;
        map.flyTo([v.latitude, v.longitude], 17, { duration: 0.8 });
        setSelectedVehicleKey({ id: v.id, direction: v.direction });
    }, [trainingData, simState]);

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
            const wsHost = window.location.hostname || 'localhost';
            const ws = new WebSocket(`ws://${wsHost}:8765`);
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

    // Segment seçicileri: segEnd başlangıçta son durağa ayarla (STATION_LIST her zaman var)
    const segEndInitRef = useRef(false);
    useEffect(() => {
        if (!segEndInitRef.current && STATION_LIST.length >= 2) {
            setSegEnd(STATION_LIST.length - 1);
            segEndInitRef.current = true;
        }
    }, []);

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

    // DOM Event Delegation — harita marker tıklamalarını yakala
    // React-Leaflet event sorunlarından tamamen bağımsız
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            const target = (e.target as HTMLElement).closest('.vehicle-marker-root') as HTMLElement;
            if (target) {
                const vid = Number(target.dataset.vid);
                const vdir = target.dataset.vdir || '';
                if (!isNaN(vid)) {
                    setSelectedVehicleKey({ id: vid, direction: vdir });
                }
            }
        };
        document.addEventListener('click', handler);
        return () => document.removeEventListener('click', handler);
    }, []);



    return (
        <div className="dashboard">
            {/* SOL PANEL */}
            <aside className="sidebar">
                <div className="sidebar-header">
                    <h1>🚍 Metrobüs</h1>
                    <span className="badge" style={{
                        background: 'linear-gradient(135deg,#00BCD4,#0097A7)',
                    }}>ANALITIK</span>
                </div>

                {/* İstatistikler */}
                <div className="stats-grid">
                    <div className="stat-card">
                        <div className="stat-value">{vehicles.length}</div>
                        <div className="stat-label">Aktif Araç</div>
                    </div>
                    <div className="stat-card" onClick={() => { setStopPanelOpen(p => !p); setSelectedStopIdx(null); }}
                        style={{ cursor: 'pointer', transition: 'all 0.15s', ...(stopPanelOpen ? { background: 'rgba(0,229,255,0.15)', border: '1px solid rgba(0,229,255,0.4)' } : {}) }}>
                        <div className="stat-value" style={{ color: stopPanelOpen ? '#00E5FF' : undefined }}>
                            {trainingData?.activeSegment ? trainingData.activeSegment.stopCount : (trainingData?.stops?.length ?? STATION_LIST.length)}
                        </div>
                        <div className="stat-label" style={{ color: stopPanelOpen ? '#00E5FF' : undefined }}>
                            Durak {trainingData?.activeSegment ? `/ ${trainingData.activeSegment.totalStops}` : ''} {stopPanelOpen ? '▲' : '▼'}
                        </div>
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

                {/* ===== ANALITIK MOTOR TOGGLE ===== */}
                <div style={{ padding: '0 16px 8px' }}>
                    <button
                        className={`btn ${trainingMode ? 'btn-green' : ''}`}
                        style={{ width: '100%', fontSize: '12px', padding: '8px', background: trainingMode ? '#00BCD4' : '#37474F' }}
                        onClick={() => setTrainingMode(prev => !prev)}
                    >
                        {trainingMode ? '⚙ Analitik Motor AKTIF' : '⚙ Analitik Motor'}
                    </button>
                    {trainingMode && (
                        <div style={{ marginTop: '4px', fontSize: '10px', color: wsConnected ? '#4CAF50' : '#F44336', textAlign: 'center' }}>
                            {wsConnected ? '● Baglandi (sim_server.py)' : '○ Baglanıyor... (python sim_server.py calistirin)'}
                        </div>
                    )}
                </div>

                {/* ===== ROTA SEGMENT SECICI ===== */}
                {trainingMode && (() => {
                    // Sunucudan allStops gelmediyse STATION_LIST'i fallback olarak kullan
                    const allStops: { index: number; name: string }[] =
                        trainingData?.allStops?.length >= 2
                            ? trainingData.allStops
                            : STATION_LIST.map((s, i) => ({ index: i, name: s.name }));
                    const activeSegment = trainingData?.activeSegment ?? null;
                    return (
                        <div style={{ padding: '0 16px 8px' }}>
                            <div style={{
                                background: activeSegment ? 'rgba(0,188,212,0.1)' : 'rgba(255,255,255,0.04)',
                                border: `1px solid ${activeSegment ? 'rgba(0,188,212,0.35)' : 'rgba(255,255,255,0.08)'}`,
                                borderRadius: '8px',
                                padding: '10px',
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                    <span style={{ fontSize: '11px', color: activeSegment ? '#00BCD4' : '#888', fontWeight: 600 }}>
                                        {activeSegment ? `Segment: ${activeSegment.stopCount}/${activeSegment.totalStops} durak` : 'Durak Segmenti'}
                                    </span>
                                    {activeSegment && wsConnected && (
                                        <button
                                            onClick={() => wsRef.current?.send(JSON.stringify({ action: 'reset_route_segment' }))}
                                            style={{ fontSize: '10px', padding: '2px 7px', background: 'rgba(244,67,54,0.15)', border: '1px solid rgba(244,67,54,0.4)', borderRadius: '4px', color: '#EF9A9A', cursor: 'pointer' }}
                                        >
                                            Tüm Rota
                                        </button>
                                    )}
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                                    <select
                                        value={segStart}
                                        onChange={e => {
                                            const v = Number(e.target.value);
                                            setSegStart(v);
                                            if (v >= segEnd) setSegEnd(Math.min(v + 1, allStops.length - 1));
                                        }}
                                        style={{ fontSize: '11px', padding: '4px 6px', background: '#1a2035', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '5px', color: '#ccc', width: '100%' }}
                                    >
                                        {allStops.map(s => (
                                            <option key={s.index} value={s.index}>{s.index + 1}. {s.name}</option>
                                        ))}
                                    </select>
                                    <div style={{ textAlign: 'center', fontSize: '9px', color: '#555' }}>→</div>
                                    <select
                                        value={segEnd}
                                        onChange={e => setSegEnd(Number(e.target.value))}
                                        style={{ fontSize: '11px', padding: '4px 6px', background: '#1a2035', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '5px', color: '#ccc', width: '100%' }}
                                    >
                                        {allStops.filter(s => s.index > segStart).map(s => (
                                            <option key={s.index} value={s.index}>{s.index + 1}. {s.name}</option>
                                        ))}
                                    </select>
                                </div>
                                <button
                                    onClick={() => {
                                        const msg = JSON.stringify({ action: 'set_route_segment', start: segStart, end: segEnd });
                                        console.log('[Segment] Gönderiliyor:', msg, 'WS state:', wsRef.current?.readyState);
                                        wsRef.current?.send(msg);
                                    }}
                                    disabled={segEnd <= segStart || !wsConnected}
                                    style={{ marginTop: '8px', width: '100%', fontSize: '11px', padding: '5px', background: (segEnd > segStart && wsConnected) ? '#00BCD4' : '#37474F', color: (segEnd > segStart && wsConnected) ? '#000' : '#555', border: 'none', borderRadius: '5px', cursor: (segEnd > segStart && wsConnected) ? 'pointer' : 'default', fontWeight: 600 }}
                                >
                                    {wsConnected ? `Uygula (${segEnd > segStart ? segEnd - segStart + 1 : 0} durak)` : 'Bağlantı bekleniyor...'}
                                </button>
                                {activeSegment && (
                                    <div style={{ marginTop: '5px', fontSize: '10px', color: '#00BCD4', textAlign: 'center' }}>
                                        {activeSegment.startName} → {activeSegment.endName}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })()}

                {/* Analitik Motor Metrikleri */}
                {trainingMode && trainingData?.analytics && (
                    <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(0,188,212,0.3)' }}>
                        <h3 style={{ color: '#00BCD4', fontSize: '12px', margin: '0 0 6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            Analitik Motor
                            <span style={{ fontSize: '9px', color: '#666', fontWeight: 400 }}>
                                {trainingData.time ? `${Math.floor(trainingData.time / 60)}dk` : ''}
                            </span>
                        </h3>

                        {/* === Filo Kontrol: Arac Sayisi Input === */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', padding: '6px 8px', background: 'rgba(0,188,212,0.08)', borderRadius: '6px' }}>
                            <span style={{ fontSize: '11px', color: '#aaa' }}>Arac Sayisi:</span>
                            <input
                                type="number"
                                min={1}
                                defaultValue={15}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        const val = parseInt((e.target as HTMLInputElement).value);
                                        if (val >= 1) {
                                            wsRef.current?.send(JSON.stringify({ action: 'set_vehicle_count', value: val }));
                                        }
                                    }
                                }}
                                onBlur={(e) => {
                                    const val = parseInt(e.target.value);
                                    if (val >= 1) {
                                        wsRef.current?.send(JSON.stringify({ action: 'set_vehicle_count', value: val }));
                                    }
                                }}
                                style={{
                                    width: '60px', padding: '4px 6px', border: '1px solid rgba(0,188,212,0.3)',
                                    borderRadius: '6px', background: '#1a2332', color: '#fff', fontSize: '14px',
                                    fontWeight: 700, textAlign: 'center', outline: 'none',
                                }}
                            />
                            <span style={{ fontSize: '10px', color: '#666' }}>({vehicles.length} aktif)</span>
                        </div>

                        {/* === Metrikler (Tooltip aciklamali) === */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', fontSize: '11px', color: '#ccc' }}>
                            <div title="Headway CV (Coefficient of Variation) = standart sapma / ortalama. Araclar arasi zaman araliginin ne kadar duzensiz oldugunu olcer. 0 = mukemmel esit dagilim, <0.3 iyi, >1.0 kotu.">
                                Headway CV: <b style={{ color: trainingData.analytics.headwayCV < 0.3 ? '#4CAF50' : trainingData.analytics.headwayCV < 1.0 ? '#FF9800' : '#F44336' }}>{trainingData.analytics.headwayCV?.toFixed(3)}</b>
                            </div>
                            <div title="Bunching = birbirine 60 saniyeden yakin olan arac cifti sayisi. Yolcular icin uzun bekleme + bos otobusler demektir.">
                                Bunching: <b style={{ color: trainingData.analytics.bunchingPairs > 0 ? '#FF9800' : '#4CAF50' }}>{trainingData.analytics.bunchingPairs}</b>
                            </div>
                            <div title="Filodaki araclar arasindaki ortalama zaman araligi (saniye). Yolcunun duraga geldigi anda ortalama bekleme suresi bunun yarisina esittir.">
                                Ort. Headway: <b style={{ color: '#fff' }}>{trainingData.analytics.meanHeadway?.toFixed(0)}s</b>
                            </div>
                            <div title="Kontrolcunun hedefledigi ideal zaman araligi. Hat uzunlugu / (arac sayisi x seyir hizi) formulu ile hesaplanir. Arac eklenince duser.">
                                Hedef: <b style={{ color: '#00BCD4' }}>{trainingData.analytics.targetHeadway?.toFixed(0)}s</b>
                            </div>
                            <div title="Aktif Hold = su anda durakta ek sure bekletilen arac sayisi. PID kontrolcu onetki araca cok yakin olan araci durakta tutar.">
                                Hold: <b style={{ color: '#fff' }}>{trainingData.analytics.activeHolds}</b>
                            </div>
                            <div title="Hiz Filtresi = hizi dusurulerek yavaslatilan arac sayisi. Kontrolcu araclarin birbirine yaklasmasini engellemek icin kullanir.">
                                Filtre: <b style={{ color: '#fff' }}>{trainingData.analytics.activeFilters}</b>
                            </div>
                        </div>

                        {/* === PID Kazanclari === */}
                        {trainingData.analytics.pidGains && (
                            <div style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '4px' }}>
                                <div style={{ fontSize: '10px', color: '#888', marginBottom: '2px' }} title="PID = Proportional-Integral-Derivative kontrolcu. Kp = anlik hataya tepki, Ki = birikimis hatanin duzeltilmesi, Kd = hata degisim hizina tepki.">PID Kazanclari:</div>
                                <div style={{ display: 'flex', gap: '8px', fontSize: '10px', color: '#aaa' }}>
                                    <span title="Proportional (Oransal): headway hatasina anlik tepki gucunu belirler. Buyuk Kp = agresif duzeltme.">Kp=<b style={{ color: '#fff' }}>{trainingData.analytics.pidGains.kp?.toFixed(3)}</b></span>
                                    <span title="Integral (Toplam): uzun sureli birikimis hatayi duzeltir. Buyuk Ki = yavasa yakinsama ama karisiz durum.">Ki=<b style={{ color: '#fff' }}>{trainingData.analytics.pidGains.ki?.toFixed(3)}</b></span>
                                    <span title="Derivative (Turev): headway degisim hizina gore onceden mudahale eder. Buyuk Kd = salinimlari bastirip kararlilik saglar.">Kd=<b style={{ color: '#fff' }}>{trainingData.analytics.pidGains.kd?.toFixed(3)}</b></span>
                                </div>
                            </div>
                        )}

                        {/* === Parametre Rehberi === */}
                        <details style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '4px' }}>
                            <summary style={{ fontSize: '10px', color: '#666', cursor: 'pointer', userSelect: 'none' }}>Parametreler ne anlama geliyor?</summary>
                            <div style={{ fontSize: '9px', color: '#888', lineHeight: '1.6', marginTop: '4px' }}>
                                <b style={{ color: '#4CAF50' }}>Headway CV</b> — Araclar arasi zaman duzensizligi. 0 = esit dagilim, {'<'}0.3 iyi.<br/>
                                <b style={{ color: '#FF9800' }}>Bunching</b> — 60sn'den yakin arac cifti. Fazlaysa filo kumelenmis.<br/>
                                <b style={{ color: '#00BCD4' }}>Hedef Headway</b> — Hat / (N x hiz). Arac eklendikce duser.<br/>
                                <b style={{ color: '#fff' }}>Hold</b> — Durakta ek tutma yapilan arac (PID karari).<br/>
                                <b style={{ color: '#fff' }}>Filtre</b> — Hizi dusurulerek yavaslatan arac sayisi.<br/>
                                <b style={{ color: '#fff' }}>Kp/Ki/Kd</b> — PID kazanclari: Oransal / Integral / Turev.<br/>
                            </div>
                        </details>
                    </div>
                )}
                {/* ===== MOTOR INCELEME ===== */}
                {trainingMode && wsConnected && (
                    <div style={{ padding: '0 16px 8px', borderTop: '1px solid rgba(0,229,255,0.15)' }}>
                        <button
                            onClick={() => setMotorInspectOpen(p => !p)}
                            style={{
                                width: '100%', textAlign: 'left', padding: '8px 10px',
                                background: motorInspectOpen ? 'rgba(0,229,255,0.1)' : 'rgba(255,255,255,0.04)',
                                border: `1px solid ${motorInspectOpen ? 'rgba(0,229,255,0.35)' : 'rgba(255,255,255,0.08)'}`,
                                borderRadius: '8px', color: motorInspectOpen ? '#00E5FF' : '#94a3b8',
                                fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex',
                                alignItems: 'center', justifyContent: 'space-between',
                                marginTop: '6px',
                            }}
                        >
                            <span>🔬 Motor İnceleme</span>
                            <span style={{ fontSize: '10px' }}>{motorInspectOpen ? '▲' : '▼'}</span>
                        </button>

                        {motorInspectOpen && (() => {
                            const ssStates: Record<string, any> = trainingData?.analytics?.smartStopStates ?? {};
                            // Tüm durak -> interventions topla
                            const allInterventions: { stopIdx: number; stopName: string; intervention: any }[] = [];
                            Object.entries(ssStates).forEach(([idxStr, state]: [string, any]) => {
                                const interventions: any[] = state?.interventions ?? [];
                                interventions.forEach(iv => {
                                    allInterventions.push({
                                        stopIdx: Number(idxStr),
                                        stopName: state?.stop_name ?? `#${idxStr}`,
                                        intervention: iv,
                                    });
                                });
                            });

                            const reasonColor: Record<string, string> = {
                                cascade: '#FF9800',
                                overflow: '#F44336',
                                downstream: '#00BCD4',
                                queue_cheaper: '#78909C',
                            };

                            if (allInterventions.length === 0) {
                                return (
                                    <div style={{ padding: '10px 4px', fontSize: '11px', color: '#475569', textAlign: 'center' }}>
                                        Aktif müdahale yok
                                    </div>
                                );
                            }

                            return (
                                <div style={{ marginTop: '8px', maxHeight: '220px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                                    {allInterventions.map((item, i) => {
                                        const iv = item.intervention;
                                        const color = reasonColor[iv.reason] ?? '#94a3b8';
                                        const vCode = `AM-${String(iv.vehicleId).padStart(2, '0')}`;
                                        return (
                                            <div key={i}
                                                onClick={() => flyToVehicle(iv.vehicleId)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '6px',
                                                    padding: '5px 8px', borderRadius: '6px', cursor: 'pointer',
                                                    background: 'rgba(255,255,255,0.03)',
                                                    border: `1px solid ${color}33`,
                                                    fontSize: '10px',
                                                    transition: 'all 0.12s',
                                                }}
                                                onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = `${color}15`; }}
                                                onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.03)'; }}
                                            >
                                                <span style={{ color: '#64748b', minWidth: '36px', fontFamily: 'monospace', fontSize: '9px' }}>{vCode}</span>
                                                <span style={{ color: '#e2e8f0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '10px' }}>{item.stopName}</span>
                                                <span style={{ color, fontWeight: 700, minWidth: '52px', fontSize: '9px' }}>{iv.reason}</span>
                                                <span style={{ color: '#f59e0b', fontWeight: 700, fontSize: '10px' }}>×{iv.speedFactor.toFixed(2)}</span>
                                                <span style={{ color: '#94a3b8', fontSize: '9px', whiteSpace: 'nowrap' }}>ETA:{iv.etaToStop}s→{iv.idealArrival}s</span>
                                                <span style={{ color: iv.queueTimeSaved > 0 ? '#4CAF50' : '#94a3b8', fontWeight: 600, fontSize: '9px', whiteSpace: 'nowrap' }}>+{iv.queueTimeSaved}s</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            );
                        })()}
                    </div>
                )}

                {/* Legacy Training Metrikleri */}
                {trainingMode && trainingData?.metrics && !trainingData?.analytics && (
                    <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                        <h3 style={{ color: '#E91E63', fontSize: '12px', margin: '0 0 6px' }}>Egitim Metrikleri</h3>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', fontSize: '11px', color: '#ccc' }}>
                            <div>Iterasyon: <b style={{ color: '#fff' }}>{trainingData.metrics.iteration}</b></div>
                            <div>Step: <b style={{ color: '#fff' }}>{trainingData.metrics.step}</b></div>
                            <div>Reward: <b style={{ color: trainingData.metrics.reward > 0 ? '#4CAF50' : '#F44336' }}>{trainingData.metrics.reward?.toFixed(3)}</b></div>
                            <div>Toplam R: <b style={{ color: '#fff' }}>{trainingData.metrics.totalReward?.toFixed(1)}</b></div>
                            <div>Hiz: <b style={{ color: '#fff' }}>{trainingData.metrics.avgSpeed?.toFixed(1)} km/h</b></div>
                            <div>Min Gap: <b style={{ color: trainingData.metrics.minGap < 100 ? '#F44336' : '#fff' }}>{trainingData.metrics.minGap?.toFixed(0)}m</b></div>
                            <div>Duran: <b style={{ color: '#fff' }}>{trainingData.metrics.numStopped}</b></div>
                            <div>Bunching: <b style={{ color: trainingData.metrics.bunching > 0 ? '#FF9800' : '#fff' }}>{trainingData.metrics.bunching}</b></div>
                        </div>
                        {trainingData.rewardComponents && Object.keys(trainingData.rewardComponents).length > 0 && (
                            <div style={{ marginTop: '6px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '4px' }}>
                                <div style={{ fontSize: '10px', color: '#888', marginBottom: '2px' }}>Reward Bilesenleri:</div>
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
                                <div key={idx}
                                    onClick={() => flyToBunchingPair(p)}
                                    style={{
                                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                        padding: '4px 8px', borderRadius: '4px', marginBottom: '2px',
                                        background: p.severity === 'critical' ? 'rgba(244,67,54,0.1)' : 'rgba(255,152,0,0.08)',
                                        cursor: 'pointer',
                                        transition: 'all 0.15s ease',
                                        border: '1px solid transparent',
                                    }}
                                    onMouseEnter={e => {
                                        (e.currentTarget as HTMLDivElement).style.background = p.severity === 'critical' ? 'rgba(244,67,54,0.25)' : 'rgba(255,152,0,0.2)';
                                        (e.currentTarget as HTMLDivElement).style.borderColor = p.severity === 'critical' ? '#F44336' : '#FF9800';
                                    }}
                                    onMouseLeave={e => {
                                        (e.currentTarget as HTMLDivElement).style.background = p.severity === 'critical' ? 'rgba(244,67,54,0.1)' : 'rgba(255,152,0,0.08)';
                                        (e.currentTarget as HTMLDivElement).style.borderColor = 'transparent';
                                    }}
                                >
                                    <span style={{ color: '#ccc', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                        <span style={{ fontSize: '13px' }}>🚍</span>
                                        M{String(p.id1).padStart(2, '0')} ↔ M{String(p.id2).padStart(2, '0')}
                                    </span>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <span style={{
                                            color: p.severity === 'critical' ? '#F44336' : '#FF9800',
                                            fontWeight: 700,
                                        }}>{p.gap}m</span>
                                        <span style={{ color: '#666', fontSize: '10px' }}>📍</span>
                                    </div>
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
                    {vehicles.slice(0, 30).map(v => (
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
                                {v.phase === 'queued' && <div style={{
                                    background: '#FFEB3B', height: '3px', borderRadius: '2px',
                                    marginTop: '3px',
                                    animation: 'queuedPulse 0.7s ease-in-out infinite',
                                }}/>}
                                {v.phase === 'blocked' && <div style={{
                                    background: '#E91E63', color: '#fff', fontSize: '10px',
                                    fontWeight: 900, padding: '2px 6px', borderRadius: '3px',
                                    marginTop: '3px', textAlign: 'center',
                                }}>🚫 ÖNÜ KAPALI — BLOKE</div>}
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
                    <MapController mapRef={mapInstanceRef} />
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

                    {/* Araç → NextStop çizgileri + araç üzeri yuvarlak */}
                    {trainingMode && vehicles
                        .filter(v =>
                            (v.phase === 'cruising' || v.phase === 'approaching') &&
                            (v as any).nextStopIndex != null &&
                            (v as any).nextStopIndex < STATION_LIST.length
                        )
                        .map(v => {
                            const a = (v as any)._analytic;
                            const targetStop = STATION_LIST[(v as any).nextStopIndex];
                            const isIntervened = a?.source === 'smart_stop';
                            const color = isIntervened ? '#00E5FF' : 'rgba(255,255,255,0.55)';
                            return (
                                <React.Fragment key={`v2s-${v.direction}-${v.id}`}>
                                    {/* Otobüsten durağa çizgi */}
                                    <Polyline
                                        positions={[[v.latitude, v.longitude], [targetStop.latitude, targetStop.longitude]]}
                                        pathOptions={{
                                            color,
                                            weight: isIntervened ? 3 : 2,
                                            opacity: isIntervened ? 0.9 : 0.5,
                                            dashArray: '8 6',
                                        }}
                                    />
                                    {/* Otobüs üzeri yuvarlak */}
                                    <CircleMarker
                                        center={[v.latitude, v.longitude]}
                                        radius={isIntervened ? 10 : 8}
                                        pathOptions={{
                                            color,
                                            weight: isIntervened ? 2.5 : 1.5,
                                            fill: false,
                                            opacity: isIntervened ? 0.9 : 0.5,
                                        }}
                                    />
                                </React.Fragment>
                            );
                        })
                    }

                    {/* Durak işaretçileri */}
                    {STATION_LIST.map((s, i) => (
                        <Marker
                            key={s.code}
                            position={[s.latitude, s.longitude]}
                            icon={stationIcon(s.name, s.sequenceOrder, i % 5 === 0, (() => {
                                const ws = trainingData?.stops?.[i];
                                if (!ws) return undefined;
                                return { occupied: ws.occupiedSlots ?? 0, total: ws.slotCount ?? 0, approaching: ws.approachingCount ?? 0, queued: ws.queuedCount ?? 0, platformLen: ws.platformLengthMeters ?? 0, rearFree: ws.rearFreeSlots ?? 0 };
                            })())}
                        >
                            <Popup>
                                <div style={{ fontFamily: 'Inter,sans-serif', minWidth: '180px' }}>
                                    <strong style={{ fontSize: '14px' }}>{s.name}</strong>
                                    <div style={{ color: '#888', fontSize: '12px', marginTop: '4px' }}>
                                        Kod: {s.code} | Sıra: {s.sequenceOrder}
                                    </div>
                                    {(() => {
                                        // Analitik modda WS'den gelen canlı veri (index = sıra numarası)
                                        const wsStop = trainingData?.stops?.[i];
                                        const slot = STATION_SLOTS.find(ss => ss.name.includes(s.name.split(' ')[0]) || s.name.includes(ss.name.split(' ')[0]));
                                        const platformLen = wsStop?.platformLengthMeters ?? slot?.platformLengthMeters;
                                        const slotCount = wsStop?.slotCount ?? slot?.slotCount;
                                        const occupied = wsStop?.occupiedSlots ?? 0;
                                        const approaching = wsStop?.approachingCount ?? 0;
                                        const rearFree = wsStop?.rearFreeSlots ?? 0;
                                        const stoppedHere = vehicles.filter(v => v.phase === 'stopped' && Math.abs(v.latitude - s.latitude) < 0.001 && Math.abs(v.longitude - s.longitude) < 0.003);
                                        const queuingHere = vehicles.filter(v => (v as any).isQueuing && Math.abs(v.latitude - s.latitude) < 0.002 && Math.abs(v.longitude - s.longitude) < 0.005);
                                        const occupancyColor = rearFree === 0 && occupied > 0 ? '#F44336' : occupied > 0 ? '#FF9800' : '#4CAF50';
                                        return (
                                            <>
                                                {platformLen != null && <div style={{ fontSize: '11px', marginTop: '4px', color: '#76FF03' }}>
                                                    Platform: {platformLen}m | Slot: {slotCount}
                                                </div>}
                                                {slotCount != null && <div style={{ fontSize: '11px', marginTop: '2px' }}>
                                                    <span style={{ color: occupancyColor, fontWeight: 'bold' }}>
                                                        Doluluk: {occupied}/{slotCount}
                                                    </span>
                                                    <span style={{ color: '#aaa', marginLeft: '6px', fontSize: '10px' }}>
                                                        (girilebilir: {rearFree})
                                                    </span>
                                                                    {approaching > 0 && <span style={{ color: '#2196F3', marginLeft: '6px' }}>
                                                        +{approaching} yaklaşan
                                                    </span>}
                                                </div>}
                                                {(wsStop?.queuedCount ?? 0) > 0 && <div style={{
                                                    marginTop: '4px', height: '3px', borderRadius: '2px',
                                                    background: '#FFEB3B',
                                                    animation: 'queuedPulse 0.7s ease-in-out infinite',
                                                }}/>}
                                                {stoppedHere.length > 0 && !wsStop && <div style={{ fontSize: '11px', marginTop: '2px', color: '#2196F3' }}>
                                                    Durakta: {stoppedHere.length} arac
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
                        <VehicleMarker key={`${v.direction}-${v.id}`} vehicle={v} />
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

                            {/* === SEFER SÜRESİ === */}
                            <div style={{
                                marginTop: '8px', padding: '8px 10px', borderRadius: '8px',
                                background: 'rgba(156,39,176,0.1)',
                                border: '1px solid rgba(156,39,176,0.25)',
                            }}>
                                <div style={{ fontSize: '11px', fontWeight: 700, color: '#CE93D8', marginBottom: '6px' }}>
                                    Sefer Süresi
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '11px' }}>
                                    <div style={{ color: '#aaa' }}>Geçen Süre
                                        <div style={{ color: '#fff', fontWeight: 700, fontSize: '14px', marginTop: '2px' }}>
                                            {Math.floor(((activeVehicle as any)._trip?.elapsed ?? 0) / 60)}:{String(Math.floor(((activeVehicle as any)._trip?.elapsed ?? 0) % 60)).padStart(2, '0')}
                                        </div>
                                    </div>
                                    <div style={{ color: '#aaa' }}>Tamamlanan
                                        <div style={{ color: '#fff', fontWeight: 700, fontSize: '14px', marginTop: '2px' }}>
                                            {(activeVehicle as any)._trip?.completedTrips ?? 0} sefer
                                        </div>
                                    </div>
                                    <div style={{ color: '#aaa' }}>Kuyruk Bekleme
                                        <div style={{ color: ((activeVehicle as any)._trip?.queueTime ?? 0) > 60 ? '#F44336' : '#FF9800', fontWeight: 600, marginTop: '2px' }}>
                                            {((activeVehicle as any)._trip?.queueTime ?? 0).toFixed(0)}s
                                        </div>
                                    </div>
                                    <div style={{ color: '#aaa' }}>Durak Bekleme
                                        <div style={{ color: '#64B5F6', fontWeight: 600, marginTop: '2px' }}>
                                            {((activeVehicle as any)._trip?.dwellTime ?? 0).toFixed(0)}s
                                        </div>
                                    </div>
                                </div>
                                {((activeVehicle as any)._trip?.lastDuration ?? 0) > 0 && (
                                    <div style={{ marginTop: '6px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                                        <span style={{ color: '#aaa' }}>Son Sefer Süresi</span>
                                        <span style={{ color: '#CE93D8', fontWeight: 700 }}>
                                            {Math.floor(((activeVehicle as any)._trip?.lastDuration ?? 0) / 60)}:{String(Math.floor(((activeVehicle as any)._trip?.lastDuration ?? 0) % 60)).padStart(2, '0')}
                                        </span>
                                    </div>
                                )}
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
                                            marginTop: '4px', height: '3px', borderRadius: '2px',
                                            background: '#FFEB3B',
                                            animation: 'queuedPulse 0.7s ease-in-out infinite',
                                        }}/>
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

                        </div>
                    </div>
                )}
            </main>

            {/* ===== DURAK DRAWER — haritanın sağından kayar ===== */}
            {(() => {
                const ssStates: Record<string, any> = trainingData?.analytics?.smartStopStates ?? {};
                const wsStops: any[] = trainingData?.stops ?? [];

                const allStops = STATION_LIST.map((s, i) => {
                    const ss = ssStates[String(i)] ?? ssStates[String(i + 1)] ?? null;
                    const ws = wsStops[i] ?? null;
                    return {
                        idx: i,
                        name: s.name,
                        congestion: ss?.congestion_level ?? 0,
                        zone: ss?.vehicles_in_zone ?? 0,
                        overflow: ss?.overflow_count ?? 0,
                        occupied: ss?.occupied_slots ?? ws?.occupiedSlots ?? 0,
                        capacity: ss?.slot_capacity ?? ws?.slotCount ?? 1,
                        rearFree: ws?.rearFreeSlots ?? 0,
                        queued: ws?.queuedCount ?? 0,
                        approaching: ws?.approachingCount ?? ss?.vehicles_in_zone ?? 0,
                        incomingEtas: (ss?.incoming_etas ?? []) as number[],
                        platformLen: ws?.platformLengthMeters ?? 0,
                        slotTimeline: (ss?.slotTimeline ?? []) as any[],
                        interventions: (ss?.interventions ?? []) as any[],
                        downstreamPressure: (ss?.downstreamPressure ?? 0) as number,
                        upstreamDensity: (ss?.upstreamDensity ?? 0) as number,
                    };
                });

                const sorted = [...allStops].sort((a, b) => {
                    if (stopSortBy === 'congestion') return b.congestion - a.congestion;
                    if (stopSortBy === 'zone') return b.zone - a.zone;
                    if (stopSortBy === 'overflow') return b.overflow - a.overflow;
                    return a.name.localeCompare(b.name, 'tr');
                });

                const sel = selectedStopIdx !== null ? allStops[selectedStopIdx] : null;

                return (
                    <div style={{
                        position: 'fixed', top: 0, right: 0, bottom: 0,
                        width: '360px',
                        background: 'rgba(13,17,28,0.97)',
                        backdropFilter: 'blur(12px)',
                        borderLeft: '1px solid rgba(0,229,255,0.2)',
                        display: 'flex', flexDirection: 'column',
                        zIndex: 2000,
                        transform: stopPanelOpen ? 'translateX(0)' : 'translateX(100%)',
                        transition: 'transform 0.28s cubic-bezier(0.4,0,0.2,1)',
                        boxShadow: stopPanelOpen ? '-8px 0 32px rgba(0,0,0,0.6)' : 'none',
                    }}>

                        {/* ── Drawer Header ── */}
                        <div style={{
                            padding: '18px 20px 14px',
                            borderBottom: '1px solid rgba(0,229,255,0.15)',
                            display: 'flex', alignItems: 'center', gap: '10px',
                            background: 'rgba(0,229,255,0.04)',
                        }}>
                            <div style={{ flex: 1 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <span style={{ fontSize: '16px', fontWeight: 800, color: '#00E5FF', letterSpacing: '-0.3px' }}>
                                        SmartStop
                                    </span>
                                    <span style={{
                                        fontSize: '10px', fontWeight: 600, padding: '2px 8px',
                                        background: 'rgba(0,229,255,0.15)', color: '#00E5FF',
                                        borderRadius: '10px', border: '1px solid rgba(0,229,255,0.25)',
                                    }}>
                                        {STATION_LIST.length} DURAK
                                    </span>
                                </div>
                                <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                                    Durak Bölgesi Arayüzü
                                </div>
                            </div>
                            {selectedStopIdx !== null && (
                                <button onClick={() => setSelectedStopIdx(null)} style={{
                                    background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                                    color: '#94a3b8', borderRadius: '8px', padding: '6px 12px',
                                    fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px',
                                }}>
                                    ← Tümü
                                </button>
                            )}
                            <button onClick={() => { setStopPanelOpen(false); setSelectedStopIdx(null); }} style={{
                                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                                color: '#64748b', borderRadius: '8px', width: '32px', height: '32px',
                                fontSize: '16px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            }}>
                                ✕
                            </button>
                        </div>

                        {/* ── Sıralama toolbar (liste görünümünde) ── */}
                        {selectedStopIdx === null && (
                            <div style={{
                                padding: '10px 16px',
                                borderBottom: '1px solid rgba(255,255,255,0.05)',
                                display: 'flex', gap: '6px', alignItems: 'center',
                            }}>
                                <span style={{ fontSize: '10px', color: '#475569', marginRight: '2px' }}>Sırala:</span>
                                {([
                                    { key: 'congestion', label: 'Yoğunluk' },
                                    { key: 'zone', label: 'Zone' },
                                    { key: 'overflow', label: 'Overflow' },
                                    { key: 'name', label: 'İsim' },
                                ] as { key: typeof stopSortBy; label: string }[]).map(({ key, label }) => (
                                    <button key={key} onClick={() => setStopSortBy(key)} style={{
                                        padding: '4px 10px', fontSize: '11px', borderRadius: '20px', cursor: 'pointer',
                                        border: stopSortBy === key ? '1px solid #00E5FF' : '1px solid rgba(255,255,255,0.08)',
                                        background: stopSortBy === key ? 'rgba(0,229,255,0.15)' : 'rgba(255,255,255,0.04)',
                                        color: stopSortBy === key ? '#00E5FF' : '#64748b',
                                        fontWeight: stopSortBy === key ? 700 : 400, transition: 'all 0.15s',
                                    }}>
                                        {label}
                                    </button>
                                ))}
                            </div>
                        )}

                        {/* ── İçerik alanı ── */}
                        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }}>

                            {/* LISTE GÖRÜNÜMÜ */}
                            {selectedStopIdx === null && sorted.map(stop => {
                                const fillPct = Math.min(100, Math.round((stop.occupied / Math.max(stop.capacity, 1)) * 100));
                                const cColor = stop.congestion > 0.75 ? '#ef4444' : stop.congestion > 0.4 ? '#f59e0b' : '#22c55e';
                                const hasActivity = stop.zone > 0 || stop.queued > 0 || stop.occupied > 0;
                                return (
                                    <div key={stop.idx} onClick={() => setSelectedStopIdx(stop.idx)} style={{
                                        display: 'flex', alignItems: 'center', gap: '10px',
                                        padding: '10px 12px', borderRadius: '10px', cursor: 'pointer',
                                        marginBottom: '4px',
                                        background: hasActivity ? 'rgba(255,255,255,0.04)' : 'transparent',
                                        border: hasActivity ? '1px solid rgba(255,255,255,0.06)' : '1px solid transparent',
                                        transition: 'all 0.15s',
                                    }}
                                        onMouseEnter={e => {
                                            (e.currentTarget as HTMLDivElement).style.background = 'rgba(0,229,255,0.07)';
                                            (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(0,229,255,0.2)';
                                        }}
                                        onMouseLeave={e => {
                                            (e.currentTarget as HTMLDivElement).style.background = hasActivity ? 'rgba(255,255,255,0.04)' : 'transparent';
                                            (e.currentTarget as HTMLDivElement).style.borderColor = hasActivity ? 'rgba(255,255,255,0.06)' : 'transparent';
                                        }}
                                    >
                                        {/* Congestion dot */}
                                        <div style={{
                                            width: '8px', height: '8px', borderRadius: '50%',
                                            background: cColor, flexShrink: 0,
                                            boxShadow: stop.congestion > 0.4 ? `0 0 6px ${cColor}88` : 'none',
                                        }} />

                                        {/* Stop name + badges */}
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontSize: '12px', color: '#e2e8f0', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {stop.name}
                                            </div>
                                            <div style={{ display: 'flex', gap: '6px', marginTop: '3px' }}>
                                                {stop.zone > 0 && (
                                                    <span style={{ fontSize: '10px', color: '#00BCD4', fontWeight: 600 }}>{stop.zone} zone</span>
                                                )}
                                                {stop.queued > 0 && (
                                                    <span style={{ fontSize: '10px', color: '#FFEB3B', fontWeight: 600 }}>{stop.queued} kuyruk</span>
                                                )}
                                                {stop.approaching > 0 && (
                                                    <span style={{ fontSize: '10px', color: '#64748b' }}>{stop.approaching} yaklaşan</span>
                                                )}
                                            </div>
                                        </div>

                                        {/* Slot fill + sayısı */}
                                        <div style={{ flexShrink: 0, textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                                            <span style={{ fontSize: '11px', fontWeight: 700, color: fillPct >= 100 ? '#ef4444' : fillPct > 60 ? '#f59e0b' : '#94a3b8' }}>
                                                {stop.occupied}/{stop.capacity}
                                            </span>
                                            <div style={{ width: '48px', height: '4px', background: 'rgba(255,255,255,0.08)', borderRadius: '2px', overflow: 'hidden' }}>
                                                <div style={{ width: `${fillPct}%`, height: '100%', background: cColor, borderRadius: '2px', transition: 'width 0.3s' }} />
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}

                            {/* DETAY GÖRÜNÜMÜ */}
                            {selectedStopIdx !== null && sel && (
                                <div>
                                    {/* Stop başlığı */}
                                    <div style={{
                                        padding: '16px', borderRadius: '12px', marginBottom: '12px',
                                        background: 'rgba(0,229,255,0.06)', border: '1px solid rgba(0,229,255,0.15)',
                                    }}>
                                        <div style={{ fontSize: '15px', fontWeight: 700, color: '#f0f4f8', marginBottom: '4px' }}>{sel.name}</div>
                                        <div style={{ display: 'flex', gap: '12px', fontSize: '11px', color: '#64748b' }}>
                                            <span>Platform {sel.platformLen}m</span>
                                            <span>{sel.capacity} slot kapasitesi</span>
                                            <span style={{ color: '#00E5FF' }}>#{sel.idx}</span>
                                        </div>
                                    </div>

                                    {/* 4 KPI kartı */}
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '14px' }}>
                                        {([
                                            { label: 'Zone Araç', value: sel.zone, color: '#00BCD4', sub: 'bölgede yaklaşan' },
                                            { label: 'Kuyruk', value: sel.queued, color: sel.queued > 0 ? '#FFEB3B' : '#334155', sub: 'peron girişinde' },
                                            { label: 'Yaklaşan', value: sel.approaching, color: '#60a5fa', sub: 'approaching fazında' },
                                            { label: 'Overflow', value: sel.overflow, color: sel.overflow > 0 ? '#ef4444' : '#334155', sub: 'toplam taşma' },
                                        ] as { label: string; value: number; color: string; sub: string }[]).map(({ label, value, color, sub }) => (
                                            <div key={label} style={{
                                                padding: '12px', borderRadius: '10px',
                                                background: value > 0 ? `${color}12` : 'rgba(255,255,255,0.03)',
                                                border: `1px solid ${value > 0 ? color + '33' : 'rgba(255,255,255,0.06)'}`,
                                            }}>
                                                <div style={{ fontSize: '22px', fontWeight: 800, color: value > 0 ? color : '#475569', lineHeight: 1 }}>{value}</div>
                                                <div style={{ fontSize: '11px', color: '#e2e8f0', fontWeight: 600, marginTop: '4px' }}>{label}</div>
                                                <div style={{ fontSize: '10px', color: '#475569', marginTop: '1px' }}>{sub}</div>
                                            </div>
                                        ))}
                                    </div>

                                    {/* Slot doluluk */}
                                    <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', marginBottom: '10px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8' }}>Slot Doluluk</span>
                                            <span style={{ fontSize: '13px', fontWeight: 700, color: sel.occupied >= sel.capacity ? '#ef4444' : '#f0f4f8' }}>
                                                {sel.occupied}/{sel.capacity}
                                                <span style={{ fontSize: '10px', color: '#475569', fontWeight: 400, marginLeft: '5px' }}>({sel.rearFree} girilebilir)</span>
                                            </span>
                                        </div>
                                        {/* Büyük progress bar */}
                                        <div style={{ height: '10px', background: 'rgba(255,255,255,0.07)', borderRadius: '5px', overflow: 'hidden', marginBottom: '8px' }}>
                                            <div style={{
                                                height: '100%', borderRadius: '5px', transition: 'width 0.4s',
                                                width: `${Math.min(100, Math.round((sel.occupied / Math.max(sel.capacity, 1)) * 100))}%`,
                                                background: sel.occupied >= sel.capacity
                                                    ? 'linear-gradient(90deg,#f59e0b,#ef4444)'
                                                    : sel.occupied > sel.capacity * 0.6
                                                        ? 'linear-gradient(90deg,#22c55e,#f59e0b)'
                                                        : '#22c55e',
                                            }} />
                                        </div>
                                        {/* Slot kutuları */}
                                        <div style={{ display: 'flex', gap: '4px' }}>
                                            {Array.from({ length: sel.capacity }).map((_, si) => {
                                                const isOccupied = si < sel.occupied;
                                                const isFull = sel.rearFree === 0 && isOccupied;
                                                return (
                                                    <div key={si} style={{
                                                        flex: 1, height: '20px', borderRadius: '4px',
                                                        background: isOccupied ? (isFull ? 'rgba(239,68,68,0.6)' : 'rgba(245,158,11,0.5)') : 'rgba(255,255,255,0.07)',
                                                        border: `1px solid ${isOccupied ? (isFull ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.3)') : 'rgba(255,255,255,0.05)'}`,
                                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                        fontSize: '8px', color: isOccupied ? '#fff' : '#1e293b', fontWeight: 700,
                                                    }}>
                                                        {isOccupied ? '🚌' : ''}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* Yoğunluk */}
                                    <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', marginBottom: '10px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8' }}>Yoğunluk Seviyesi</span>
                                            <span style={{ fontSize: '16px', fontWeight: 800, color: sel.congestion > 0.75 ? '#ef4444' : sel.congestion > 0.4 ? '#f59e0b' : '#22c55e' }}>
                                                {Math.round(sel.congestion * 100)}%
                                            </span>
                                        </div>
                                        <div style={{ height: '8px', background: 'rgba(255,255,255,0.07)', borderRadius: '4px', overflow: 'hidden' }}>
                                            <div style={{
                                                height: '100%', borderRadius: '4px', transition: 'width 0.4s',
                                                width: `${Math.round(sel.congestion * 100)}%`,
                                                background: sel.congestion > 0.75
                                                    ? 'linear-gradient(90deg,#f59e0b,#ef4444)'
                                                    : sel.congestion > 0.4 ? '#f59e0b' : '#22c55e',
                                            }} />
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px', fontSize: '9px', color: '#334155' }}>
                                            <span>Düşük</span><span>Orta</span><span>Yüksek</span>
                                        </div>
                                    </div>

                                    {/* Gelen ETA'lar */}
                                    {sel.incomingEtas.length > 0 && (
                                        <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', marginBottom: '10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '10px' }}>
                                                Gelen ETA&apos;lar
                                                <span style={{ fontSize: '10px', color: '#475569', fontWeight: 400, marginLeft: '6px' }}>
                                                    ({sel.incomingEtas.length} araç)
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                {sel.incomingEtas.slice(0, 6).map((eta: number, ei: number) => {
                                                    const urgency = eta < 15 ? { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: 'Kritik' }
                                                        : eta < 30 ? { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)', label: 'Yakın' }
                                                            : { color: '#00BCD4', bg: 'rgba(0,188,212,0.08)', label: 'Normal' };
                                                    const barPct = Math.max(4, Math.min(100, ((60 - Math.min(eta, 60)) / 60) * 100));
                                                    return (
                                                        <div key={ei} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                                            <div style={{
                                                                minWidth: '36px', textAlign: 'center', padding: '3px 0',
                                                                fontSize: '11px', fontWeight: 700, color: urgency.color,
                                                            }}>
                                                                {eta.toFixed(0)}s
                                                            </div>
                                                            <div style={{ flex: 1, height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                                                                <div style={{ width: `${barPct}%`, height: '100%', background: urgency.color, borderRadius: '3px', opacity: 0.7 }} />
                                                            </div>
                                                            <span style={{
                                                                fontSize: '9px', padding: '2px 7px', borderRadius: '8px',
                                                                background: urgency.bg, color: urgency.color, fontWeight: 600,
                                                            }}>
                                                                {urgency.label}
                                                            </span>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    )}

                                    {/* === SLOT TIMELINE (Motor İnceleme) === */}
                                    {sel.slotTimeline.length > 0 && (
                                        <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.12)', marginBottom: '10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: '#00E5FF', marginBottom: '10px' }}>
                                                Slot Zaman Çizelgesi
                                            </div>
                                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                                {sel.slotTimeline.map((slot: any, si: number) => {
                                                    const isEmpty = slot.busId === null || slot.busId === undefined;
                                                    const freeTime: number = slot.freeTime ?? 0;
                                                    // Renk: boş=yeşil, dolu ve freeTime'a göre sarı→kırmızı
                                                    let bg = '#22c55e33';
                                                    let border = '#22c55e55';
                                                    let textColor = '#22c55e';
                                                    if (!isEmpty) {
                                                        if (freeTime > 20) { bg = '#ef444433'; border = '#ef444455'; textColor = '#ef4444'; }
                                                        else if (freeTime > 8) { bg = '#f59e0b33'; border = '#f59e0b55'; textColor = '#f59e0b'; }
                                                        else { bg = '#fbbf2433'; border = '#fbbf2455'; textColor = '#fbbf24'; }
                                                    }
                                                    return (
                                                        <div key={si} style={{
                                                            width: '52px', height: '40px', borderRadius: '6px',
                                                            background: bg, border: `1px solid ${border}`,
                                                            display: 'flex', flexDirection: 'column',
                                                            alignItems: 'center', justifyContent: 'center',
                                                            fontSize: '9px', color: textColor, fontWeight: 700,
                                                        }}>
                                                            <span style={{ fontSize: '8px', color: '#64748b' }}>#{slot.slotId}</span>
                                                            {isEmpty ? <span>boş</span> : <span>{freeTime.toFixed(0)}s</span>}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    )}

                                    {/* === MÜDAHALELEr (Motor İnceleme) === */}
                                    {sel.interventions.length > 0 && (
                                        <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(255,152,0,0.04)', border: '1px solid rgba(255,152,0,0.15)', marginBottom: '10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: '#FF9800', marginBottom: '10px' }}>
                                                Aktif Müdahaleler
                                                <span style={{ fontSize: '10px', color: '#475569', fontWeight: 400, marginLeft: '6px' }}>
                                                    ({sel.interventions.length} araç)
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                {sel.interventions.map((iv: any, ii: number) => {
                                                    const reasonColorMap: Record<string, string> = {
                                                        cascade: '#FF9800',
                                                        overflow: '#ef4444',
                                                        downstream: '#00BCD4',
                                                        queue_cheaper: '#78909C',
                                                    };
                                                    const rc = reasonColorMap[iv.reason] ?? '#94a3b8';
                                                    const sfPct = Math.round((1 - iv.speedFactor) * 100);
                                                    const vCode = `AM-${String(iv.vehicleId).padStart(2, '0')}`;
                                                    return (
                                                        <div key={ii}
                                                            onClick={() => flyToVehicle(iv.vehicleId)}
                                                            style={{
                                                                padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                                                                background: `${rc}0d`, border: `1px solid ${rc}33`,
                                                                transition: 'all 0.12s',
                                                            }}
                                                            onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = `${rc}20`; }}
                                                            onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = `${rc}0d`; }}
                                                        >
                                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                                                <span style={{ fontSize: '11px', fontWeight: 700, color: '#e2e8f0', fontFamily: 'monospace' }}>{vCode}</span>
                                                                <span style={{ fontSize: '9px', fontWeight: 700, padding: '2px 7px', borderRadius: '8px', background: `${rc}22`, color: rc }}>{iv.reason}</span>
                                                            </div>
                                                            {/* Speed factor bar */}
                                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                                                                <span style={{ fontSize: '10px', color: '#f59e0b', fontWeight: 700 }}>×{iv.speedFactor.toFixed(2)}</span>
                                                                <div style={{ flex: 1, height: '5px', background: 'rgba(255,255,255,0.07)', borderRadius: '3px', overflow: 'hidden' }}>
                                                                    <div style={{ width: `${sfPct}%`, height: '100%', background: '#f59e0b', borderRadius: '3px' }} />
                                                                </div>
                                                                <span style={{ fontSize: '9px', color: '#64748b' }}>{sfPct}% yavaş</span>
                                                            </div>
                                                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#64748b' }}>
                                                                <span>ETA <b style={{ color: '#94a3b8' }}>{iv.etaToStop}s</b> → İdeal <b style={{ color: '#00BCD4' }}>{iv.idealArrival}s</b></span>
                                                                <span style={{ color: iv.netBenefit > 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                                                                    {iv.netBenefit > 0 ? '+' : ''}{iv.netBenefit.toFixed(1)} fayda
                                                                </span>
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    )}

                                    {/* === DOWNSTREAM / UPSTREAM BASINC (Motor İnceleme) === */}
                                    {(sel.downstreamPressure > 0 || sel.upstreamDensity > 0) && (
                                        <div style={{ padding: '14px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', marginBottom: '10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '10px' }}>
                                                Komşu Baskı
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                {/* Downstream */}
                                                <div>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '3px' }}>
                                                        <span style={{ color: '#ef4444' }}>Downstream Baskı</span>
                                                        <span style={{ color: '#ef4444', fontWeight: 700 }}>{sel.downstreamPressure.toFixed(2)}</span>
                                                    </div>
                                                    <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                                                        <div style={{
                                                            width: `${Math.min(100, sel.downstreamPressure * 60)}%`,
                                                            height: '100%', background: '#ef4444', borderRadius: '3px', opacity: 0.8,
                                                        }} />
                                                    </div>
                                                </div>
                                                {/* Upstream */}
                                                <div>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '3px' }}>
                                                        <span style={{ color: '#60a5fa' }}>Upstream Yoğunluk</span>
                                                        <span style={{ color: '#60a5fa', fontWeight: 700 }}>{sel.upstreamDensity.toFixed(2)}</span>
                                                    </div>
                                                    <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                                                        <div style={{
                                                            width: `${Math.min(100, sel.upstreamDensity * 80)}%`,
                                                            height: '100%', background: '#60a5fa', borderRadius: '3px', opacity: 0.8,
                                                        }} />
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                );
            })()}
        </div>
    );
};

export default App;
