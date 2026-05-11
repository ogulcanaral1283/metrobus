import { useState, useEffect, useRef, useCallback } from 'react';
import type { SimVehicle } from '@metrobus/shared';

/** IETT API'den gelen ham otobüs verisi */
interface IETTBus {
    kapino: string;
    enlem: string;
    boylam: string;
    hatkodu: string;
    guzergahkodu: string;
    hatad: string;
    yon: string;
    son_konum_zamani: string;
    yakinDurakKodu?: string;
}

/** API yanıt formatı */
interface FiloResponse {
    buses: IETTBus[];
    count: number;
    cached: boolean;
    api_calls: number;
    timestamp: number;
}

/** Hat koduna göre renk */
export const HAT_COLORS: Record<string, string> = {
    '34': '#E91E63',
    '34A': '#9C27B0',
    '34AS': '#2196F3',
    '34BZ': '#FF9800',
    '34C': '#4CAF50',
    '34G': '#00BCD4',
    '34Z': '#FF5722',
};

/** Haversine mesafe (metre) */
function haversineDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6_371_000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
        Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** İki nokta arası bearing (derece, 0=kuzey, saat yönü) */
function calculateBearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const y = Math.sin(dLon) * Math.cos(lat2 * Math.PI / 180);
    const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180) -
        Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos(dLon);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

/** Yön string'inden gidiş/dönüş çıkar */
function parseDirection(yon: string, guzergahkodu: string): 'gidis' | 'donus' {
    const y = yon.toUpperCase();
    if (y.includes('SÖĞÜTLÜÇEŞME') || y.includes('SÖ') || y.includes('ZİNCİRLİKUYU') || y.includes('ZINCIRLIKU')) {
        return 'gidis';
    }
    if (y.includes('B.SONDURAK') || y.includes('BEYLİKDÜZÜ') || y.includes('AVCILAR') || y.includes('CEVİZLİBAĞ')) {
        return 'donus';
    }
    if (guzergahkodu.includes('_G_')) return 'gidis';
    if (guzergahkodu.includes('_D_')) return 'donus';
    return 'gidis';
}

/** Önceki pozisyon takibi */
interface PrevState {
    lat: number;
    lon: number;
    heading: number;
    speed: number;
    time: number;
}

/** Araç geçmiş haritası (kapino → prev state) */
const prevStateMap = new Map<string, PrevState>();

/** IETT verisini SimVehicle-uyumlu formata çevir (heading + speed hesaplı) */
function toSimVehicle(bus: IETTBus, index: number): SimVehicle {
    const lat = parseFloat(bus.enlem);
    const lon = parseFloat(bus.boylam);
    const dir = parseDirection(bus.yon || '', bus.guzergahkodu || '');
    const now = Date.now();
    const kapino = bus.kapino || `BUS-${index}`;

    // Önceki konumdan heading ve speed hesapla
    let heading = 0;
    let speed = 0;
    let phase: string = 'cruising';

    const prev = prevStateMap.get(kapino);
    if (prev) {
        const dist = haversineDistance(prev.lat, prev.lon, lat, lon);
        const dt = (now - prev.time) / 1000; // saniye

        if (dist > 2 && dt > 0) {
            // Hareket var → heading ve speed güncelle
            heading = calculateBearing(prev.lat, prev.lon, lat, lon);
            speed = dist / dt; // m/s
            phase = speed < 1 ? 'stopped' : 'cruising';
        } else {
            // Hareket yok veya çok az → önceki heading'i koru
            heading = prev.heading;
            speed = 0;
            phase = 'stopped';
        }
    }

    // State güncelle
    prevStateMap.set(kapino, { lat, lon, heading, speed, time: now });

    return {
        id: index,
        code: kapino,
        vehicleType: { brand: 'IETT', model: bus.hatkodu || '34G', lengthMeters: 20, code: bus.hatkodu || 'MB' },
        positionMeters: 0,
        speed,
        acceleration: 0,
        phase,
        heading,
        latitude: lat,
        longitude: lon,
        direction: dir,
        dwellRemaining: 0,
        nextStopIndex: 0,
        totalStops: 0,
        totalDistance: 0,
        manualOverride: null,
        isQueuing: false,
        queueWaitTime: 0,
        lastDwellTime: 0,
        assignedSlotIndex: -1,
        slotMeterPosition: 0,
        // IETT-specific ek alanlar (as any)
        _iett: {
            hatkodu: bus.hatkodu,
            hatad: bus.hatad,
            yon: bus.yon,
            guzergahkodu: bus.guzergahkodu,
            son_konum_zamani: bus.son_konum_zamani,
            yakinDurakKodu: bus.yakinDurakKodu,
        },
    } as SimVehicle;
}

export interface IETTLiveState {
    vehicles: SimVehicle[];
    count: number;
    apiCalls: number;
    cached: boolean;
    lastUpdate: string;
    connected: boolean;
    error: string | null;
}

/**
 * IETT canlı otobüs verisi hook'u.
 * - Heading ve speed önceki konumlardan hesaplanır
 * - Araçlar arası smooth interpolation yapılır
 * @param enabled - true ise periyodik fetch yapar
 * @param intervalMs - fetch aralığı (ms)
 */
export function useIETTLive(enabled: boolean, intervalMs: number = 2000): IETTLiveState {
    const [state, setState] = useState<IETTLiveState>({
        vehicles: [],
        count: 0,
        apiCalls: 0,
        cached: false,
        lastUpdate: '',
        connected: false,
        error: null,
    });

    // Interpolation için önceki ve hedef pozisyonlar
    const targetRef = useRef<SimVehicle[]>([]);
    const displayRef = useRef<SimVehicle[]>([]);
    const lastFetchRef = useRef<number>(0);
    const animFrameRef = useRef<number>(0);

    const timerRef = useRef<number | null>(null);

    const fetchData = useCallback(async () => {
        try {
            const resp = await fetch('/api/filo');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data: FiloResponse = await resp.json();

            const vehicles = data.buses
                .filter(b => {
                    const lat = parseFloat(b.enlem);
                    const lon = parseFloat(b.boylam);
                    return lat > 0 && lon > 0;
                })
                .map((b, i) => toSimVehicle(b, i));

            targetRef.current = vehicles;
            lastFetchRef.current = Date.now();

            setState({
                vehicles,
                count: data.count,
                apiCalls: data.api_calls,
                cached: data.cached,
                lastUpdate: new Date(data.timestamp * 1000).toLocaleTimeString('tr-TR'),
                connected: true,
                error: null,
            });
        } catch (err: any) {
            setState(prev => ({
                ...prev,
                connected: false,
                error: err.message || 'Bağlantı hatası',
            }));
        }
    }, []);

    // Smooth interpolation döngüsü (20fps)
    useEffect(() => {
        if (!enabled) return;

        let running = true;
        const INTERP_MS = intervalMs; // fetch aralığı = interpolation süresi

        function interpolate() {
            if (!running) return;

            const targets = targetRef.current;
            const display = displayRef.current;
            const elapsed = Date.now() - lastFetchRef.current;
            const t = Math.min(elapsed / INTERP_MS, 1.0); // 0→1 arası

            if (targets.length > 0) {
                const interpolated = targets.map((target, i) => {
                    const prev = display[i];
                    if (!prev || t >= 0.95) return target;

                    // Pozisyon interpolasyonu
                    const lat = prev.latitude + (target.latitude - prev.latitude) * t;
                    const lon = prev.longitude + (target.longitude - prev.longitude) * t;

                    return {
                        ...target,
                        latitude: lat,
                        longitude: lon,
                    };
                });

                if (t >= 0.95) {
                    displayRef.current = targets;
                }

                setState(prev => ({
                    ...prev,
                    vehicles: interpolated,
                }));
            }

            animFrameRef.current = requestAnimationFrame(interpolate);
        }

        animFrameRef.current = requestAnimationFrame(interpolate);

        return () => {
            running = false;
            cancelAnimationFrame(animFrameRef.current);
        };
    }, [enabled, intervalMs]);

    useEffect(() => {
        if (!enabled) {
            if (timerRef.current) clearInterval(timerRef.current);
            timerRef.current = null;
            prevStateMap.clear();
            return;
        }

        // İlk fetch
        fetchData();

        // Periyodik fetch
        timerRef.current = window.setInterval(fetchData, intervalMs);

        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [enabled, intervalMs, fetchData]);

    return state;
}
