// =============================================
// Route Linearizer
// Edge geometrisini düz metre bazlı çizgiye dönüştürür.
// Simülasyonda araç pozisyonu metre cinsinden tutulur,
// bu modül metre ↔ lat/lng dönüşümünü sağlar.
// =============================================

import type { RouteEdge, NetworkStop } from '../types/route-network';
import type { LinearStop } from './sim-types';
import { STATION_SLOTS } from '../constants/station-slots';
import type { StationSlotInfo } from '../constants/station-slots';
import { PLATFORM_ENTRIES } from '../constants/platform-entries';

/** Haversine mesafe (metre) */
function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
        Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Bearing hesapla (derece) */
function bearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const y = Math.sin(dLon) * Math.cos(lat2 * Math.PI / 180);
    const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180) -
        Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos(dLon);
    return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}

/** Linearize edilmiş rota segment'i */
interface LinearSegment {
    /** Bu segmentin başlangıç metresi (hat üzerinde) */
    startMeter: number;
    /** Bu segmentin bitiş metresi */
    endMeter: number;
    /** Başlangıç lat/lng */
    startLat: number;
    startLng: number;
    /** Bitiş lat/lng */
    endLat: number;
    endLng: number;
    /** Segment uzunluğu (metre) */
    length: number;
    /** Bu segment'in geldiği edge index'i */
    edgeIndex: number;
    /** Bearing (derece) */
    bearing: number;
}

/** Linearize edilmiş rota */
export interface LinearRoute {
    /** Toplam hat uzunluğu (metre) */
    totalLength: number;
    /** Tüm segmentler (sıralı) */
    segments: LinearSegment[];
    /** Duraklar (metre pozisyonu ile) */
    stops: LinearStop[];
    /** Yön */
    direction: 'gidis' | 'donus';
}

/**
 * Edge dizisini linearize eder.
 * Her edge'in geometry noktaları arasındaki mesafeler toplanarak
 * tek bir metre bazlı çizgiye dönüştürülür.
 */
export function linearizeRoute(
    edges: RouteEdge[],
    stops: NetworkStop[],
    direction: 'gidis' | 'donus',
): LinearRoute {
    const segments: LinearSegment[] = [];
    let cumulativeMeter = 0;

    for (let ei = 0; ei < edges.length; ei++) {
        const geom = edges[ei].geometry;
        for (let pi = 0; pi < geom.length - 1; pi++) {
            const [lat1, lng1] = geom[pi];
            const [lat2, lng2] = geom[pi + 1];
            const dist = haversine(lat1, lng1, lat2, lng2);
            if (dist < 0.1) continue; // degenerate segment skip

            segments.push({
                startMeter: cumulativeMeter,
                endMeter: cumulativeMeter + dist,
                startLat: lat1,
                startLng: lng1,
                endLat: lat2,
                endLng: lng2,
                length: dist,
                edgeIndex: ei,
                bearing: bearing(lat1, lng1, lat2, lng2),
            });

            cumulativeMeter += dist;
        }
    }

    // Durakları metre pozisyonuna eşle
    const linearStops: LinearStop[] = [];
    for (let si = 0; si < stops.length; si++) {
        const stop = stops[si];
        const meterPos = findClosestMeter(segments, stop.latitude, stop.longitude);

        // STATION_SLOTS'tan slot bilgisi bul
        const slotInfo = findSlotInfo(stop.name);

        linearStops.push({
            index: si,
            name: stop.name,
            meterPosition: meterPos,
            latitude: stop.latitude,
            longitude: stop.longitude,
            passengerLoad: 0,
            slotCount: slotInfo?.slotCount ?? 1,
            platformLengthMeters: slotInfo?.platformLengthMeters ?? 0,
        });
    }

    // Metre pozisyonuna göre sırala
    linearStops.sort((a, b) => a.meterPosition - b.meterPosition);

    // ── Platform HEAD alignment ──────────────────────────────
    // stop.meterPosition = peron HEAD'i (ilk aracın duracağı yer) olmalı.
    // Gidiş: araçlar batıdan gelir → peron HEAD'i = en doğu ucu = dönüş giriş noktası
    // Dönüş: araçlar doğudan gelir → peron HEAD'i = en batı ucu = gidiş giriş noktası
    // Karşı yönün giriş koordinatını rota üzerine project ederek HEAD pozisyonunu buluyoruz.
    const oppositeKey = direction === 'gidis' ? 'donus' : 'gidis';
    const norm = (s: string) => s.toLowerCase().replace(/[^a-zA-ZçğıöşüÇĞİÖŞÜ0-9]/g, '');

    for (const stop of linearStops) {
        const stopNorm = norm(stop.name);
        // Platform entry bul (tam veya kısmi eşleşme)
        const pe = PLATFORM_ENTRIES.find(e => {
            const eNorm = norm(e.name);
            return eNorm === stopNorm || eNorm.includes(stopNorm) || stopNorm.includes(eNorm);
        });
        if (!pe) continue;

        const headLat = pe[`${oppositeKey}_lat` as keyof typeof pe] as number;
        const headLon = pe[`${oppositeKey}_lon` as keyof typeof pe] as number;
        if (!headLat || !headLon) continue;

        const headMeter = findClosestMeter(segments, headLat, headLon);

        // Makul aralıkta mı? (±300m kayma — platform uzunluğu kadar olabilir)
        if (Math.abs(headMeter - stop.meterPosition) < 300) {
            stop.meterPosition = headMeter;
        }
    }

    return {
        totalLength: cumulativeMeter,
        segments,
        stops: linearStops,
        direction,
    };
}

/**
 * Metre pozisyonundan lat/lng ve heading hesapla.
 * Binary search ile doğru segmenti bulur.
 */
export function meterToPosition(route: LinearRoute, meter: number): {
    latitude: number;
    longitude: number;
    heading: number;
} {
    // Clamp
    const m = Math.max(0, Math.min(meter, route.totalLength));
    if (route.segments.length === 0) {
        return { latitude: 0, longitude: 0, heading: 0 };
    }

    // Binary search
    let lo = 0, hi = route.segments.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (route.segments[mid].endMeter < m) lo = mid + 1;
        else hi = mid;
    }

    const seg = route.segments[lo];
    const t = seg.length > 0 ? (m - seg.startMeter) / seg.length : 0;

    return {
        latitude: seg.startLat + t * (seg.endLat - seg.startLat),
        longitude: seg.startLng + t * (seg.endLng - seg.startLng),
        heading: seg.bearing,
    };
}

/**
 * Lat/lng'den en yakın metre pozisyonunu bul.
 */
function findClosestMeter(segments: LinearSegment[], lat: number, lng: number): number {
    let bestDist = Infinity;
    let bestMeter = 0;

    // Her 10. segment'i kontrol et (hız için)
    const step = Math.max(1, Math.floor(segments.length / 200));
    let bestIdx = 0;

    for (let i = 0; i < segments.length; i += step) {
        const seg = segments[i];
        const d = haversine(lat, lng, seg.startLat, seg.startLng);
        if (d < bestDist) {
            bestDist = d;
            bestIdx = i;
        }
    }

    // Çevre segmentleri detaylı kontrol et
    const searchStart = Math.max(0, bestIdx - step * 2);
    const searchEnd = Math.min(segments.length, bestIdx + step * 2);

    for (let i = searchStart; i < searchEnd; i++) {
        const seg = segments[i];

        // Noktayı segment üzerine project et
        const t = projectPointOnSegment(
            lat, lng,
            seg.startLat, seg.startLng,
            seg.endLat, seg.endLng,
        );

        const projLat = seg.startLat + t * (seg.endLat - seg.startLat);
        const projLng = seg.startLng + t * (seg.endLng - seg.startLng);
        const d = haversine(lat, lng, projLat, projLng);

        if (d < bestDist) {
            bestDist = d;
            bestMeter = seg.startMeter + t * seg.length;
        }
    }

    return bestMeter;
}

/**
 * Punkt'ı doğru parçası üzerine project et (0-1 arası t değeri).
 * Basit düzlemsel projeksiyon (kısa mesafelerde yeterli).
 */
function projectPointOnSegment(
    lat: number, lng: number,
    lat1: number, lng1: number,
    lat2: number, lng2: number,
): number {
    const dx = lat2 - lat1;
    const dy = lng2 - lng1;
    const lenSq = dx * dx + dy * dy;
    if (lenSq < 1e-12) return 0;
    const t = ((lat - lat1) * dx + (lng - lng1) * dy) / lenSq;
    return Math.max(0, Math.min(1, t));
}

/**
 * Durak adını STATION_SLOTS ile eşleştir.
 * OSM isimleri farklı olabilir, fuzzy match yapar.
 */
function findSlotInfo(stopName: string): StationSlotInfo | undefined {
    const norm = (s: string) => s.toLowerCase().replace(/[^a-zA-ZçğıöşüÇĞİÖŞÜ0-9]/g, '');
    const target = norm(stopName);

    // Exact match
    for (const slot of STATION_SLOTS) {
        if (norm(slot.name) === target) return slot;
    }

    // Substring match
    for (const slot of STATION_SLOTS) {
        const slotNorm = norm(slot.name);
        if (slotNorm.includes(target) || target.includes(slotNorm)) return slot;
    }

    return undefined;
}
