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

/** Yön string'inden gidiş/dönüş çıkar */
function parseDirection(yon: string, guzergahkodu: string): 'gidis' | 'donus' {
    const y = yon.toUpperCase();
    // Söğütlüçeşme / Zincirlikuyu yönü → gidiş (doğu)
    if (y.includes('SÖĞÜTLÜÇEŞME') || y.includes('SÖ') || y.includes('ZİNCİRLİKUYU') || y.includes('ZINCIRLIKU')) {
        return 'gidis';
    }
    // Beylikdüzü / Avcılar yönü → dönüş (batı)
    if (y.includes('B.SONDURAK') || y.includes('BEYLİKDÜZÜ') || y.includes('AVCILAR') || y.includes('CEVİZLİBAĞ')) {
        return 'donus';
    }
    // Güzergah kodundan tahmin
    if (guzergahkodu.includes('_G_')) return 'gidis';
    if (guzergahkodu.includes('_D_')) return 'donus';
    return 'gidis';
}

/** IETT verisini SimVehicle-uyumlu formata çevir */
function toSimVehicle(bus: IETTBus, index: number): SimVehicle {
    const lat = parseFloat(bus.enlem);
    const lon = parseFloat(bus.boylam);
    const dir = parseDirection(bus.yon || '', bus.guzergahkodu || '');

    return {
        id: index,
        code: bus.kapino || `BUS-${index}`,
        vehicleType: { brand: 'IETT', model: bus.hatkodu || '34G', lengthMeters: 20, code: bus.hatkodu || 'MB' },
        positionMeters: 0,
        speed: 0,
        acceleration: 0,
        phase: 'cruising',
        heading: 0,
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

    useEffect(() => {
        if (!enabled) {
            if (timerRef.current) clearInterval(timerRef.current);
            timerRef.current = null;
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
