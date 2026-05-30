// =============================================
// Coğrafi Hesaplama Yardımcı Fonksiyonları
// =============================================

const EARTH_RADIUS_KM = 6371;

/** Derece → Radyan */
function toRadians(degrees: number): number {
    return degrees * (Math.PI / 180);
}

/**
 * Haversine formülü ile iki nokta arası mesafe hesaplama
 * @returns mesafe (metre)
 */
export function haversineDistance(
    lat1: number,
    lon1: number,
    lat2: number,
    lon2: number
): number {
    const dLat = toRadians(lat2 - lat1);
    const dLon = toRadians(lon2 - lon1);

    const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRadians(lat1)) *
        Math.cos(toRadians(lat2)) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);

    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

    return EARTH_RADIUS_KM * c * 1000; // metre
}

/**
 * İki nokta arası bearing (yön) hesaplama
 * @returns açı (derece, 0-360)
 */
export function calculateBearing(
    lat1: number,
    lon1: number,
    lat2: number,
    lon2: number
): number {
    const dLon = toRadians(lon2 - lon1);
    const y = Math.sin(dLon) * Math.cos(toRadians(lat2));
    const x =
        Math.cos(toRadians(lat1)) * Math.sin(toRadians(lat2)) -
        Math.sin(toRadians(lat1)) *
        Math.cos(toRadians(lat2)) *
        Math.cos(dLon);

    let bearing = Math.atan2(y, x) * (180 / Math.PI);
    bearing = (bearing + 360) % 360;
    return bearing;
}

/**
 * Bir noktaya en yakın durağı bul
 * @returns { stationIndex, distance }
 */
export function findNearestStation(
    lat: number,
    lon: number,
    stations: Array<{ latitude: number; longitude: number }>
): { index: number; distance: number } {
    let minDistance = Infinity;
    let nearestIndex = 0;

    for (let i = 0; i < stations.length; i++) {
        const dist = haversineDistance(
            lat,
            lon,
            stations[i].latitude,
            stations[i].longitude
        );
        if (dist < minDistance) {
            minDistance = dist;
            nearestIndex = i;
        }
    }

    return { index: nearestIndex, distance: minDistance };
}

/**
 * Verilen başlangıç noktasından hedef mesafe kadar ilerle
 * @returns { latitude, longitude }
 */
export function moveAlongBearing(
    lat: number,
    lon: number,
    bearingDeg: number,
    distanceMeters: number
): { latitude: number; longitude: number } {
    const d = distanceMeters / (EARTH_RADIUS_KM * 1000);
    const bearing = toRadians(bearingDeg);

    const lat1 = toRadians(lat);
    const lon1 = toRadians(lon);

    const lat2 = Math.asin(
        Math.sin(lat1) * Math.cos(d) +
        Math.cos(lat1) * Math.sin(d) * Math.cos(bearing)
    );

    const lon2 =
        lon1 +
        Math.atan2(
            Math.sin(bearing) * Math.sin(d) * Math.cos(lat1),
            Math.cos(d) - Math.sin(lat1) * Math.sin(lat2)
        );

    return {
        latitude: lat2 * (180 / Math.PI),
        longitude: lon2 * (180 / Math.PI),
    };
}

/**
 * İki araç arası tahmini seyahat süresi (saniye)
 * @param distanceMeters mesafe (metre)
 * @param avgSpeedKmh ortalama hız (km/s)
 */
export function estimateTravelTime(
    distanceMeters: number,
    avgSpeedKmh: number
): number {
    if (avgSpeedKmh <= 0) return Infinity;
    return (distanceMeters / 1000 / avgSpeedKmh) * 3600;
}
