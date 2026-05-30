// =============================================
// Simülasyon Tip Tanımları ve Config
// =============================================

/** Araç tipi tanımı */
export interface VehicleType {
    /** Marka */
    brand: string;
    /** Model */
    model: string;
    /** Araç uzunluğu (metre) */
    lengthMeters: number;
    /** Kısa kod */
    code: string;
}

/** Mevcut araç tipleri */
export const VEHICLE_TYPES: VehicleType[] = [
    { brand: 'Mercedes-Benz', model: 'Citaro', lengthMeters: 20, code: 'MB' },
    { brand: 'Akia', model: 'Ultra High Capacity', lengthMeters: 25, code: 'AK' },
];

/** Peron içindeki araçlar arası boşluk (metre) */
export const VEHICLE_GAP = 0.4;

/** Araç fazı — durak state machine (Kuyruk Teorisi Modeli) */
export type VehiclePhase =
    | 'cruising'      // Serbest seyir
    | 'approaching'   // Durağa yaklaşım (frenleme eğrisi)
    | 'queued'        // Peron girişinde bekleme (semaphore — slot yok)
    | 'docking'       // Slot'a yavaş ilerleme (~2 m/s creep)
    | 'stopped'       // Durakta (kapı açık, yolcu operasyonu)
    | 'doorsClosed'   // Kapılar kapanıyor (2sn)
    | 'blocked'       // İşlem bitti ama öndeki araç engel (FIFO)
    | 'departing';    // Kalkış (yumuşak ivme)

/** Simüle edilen araç */
export interface SimVehicle {
    id: number;
    code: string;
    /** Araç tipi (marka, model, uzunluk) */
    vehicleType: VehicleType;
    /** Hat üzerindeki pozisyon (metre, 0 = hat başı) */
    positionMeters: number;
    /** Anlık hız (m/s) */
    speed: number;
    /** Anlık ivme (m/s²) — pozitif hızlanma, negatif fren */
    acceleration: number;
    /** Araç fazı */
    phase: VehiclePhase;
    /** Heading (derece, 0=kuzey, saat yönü) */
    heading: number;
    /** Lat/Lng (render için) */
    latitude: number;
    longitude: number;
    /** Yön */
    direction: 'gidis' | 'donus';
    /** Durakta kalan süre (sn) */
    dwellRemaining: number;
    /** Sonraki durak indexi */
    nextStopIndex: number;
    /** Toplam durma sayısı */
    totalStops: number;
    /** Toplam kat edilen mesafe (metre) */
    totalDistance: number;
    /** Manuel override: null = yok, number = zorlanan max hız (m/s), 0 = tam dur */
    manualOverride: number | null;
    /** Durak dışında kuyrukta mı? */
    isQueuing: boolean;
    /** Kuyrukta bekleme süresi (sn) */
    queueWaitTime: number;
    /** Son dwell süresi (gösterim için) */
    lastDwellTime: number;
    /** Durakta atanmış slot indexi (0 = ön/çıkış tarafı, slotCount-1 = arka/giriş tarafı) */
    assignedSlotIndex: number;
    /** Slot'un hat üzerindeki metre pozisyonu */
    slotMeterPosition: number;
}
/** Trafik tıkanıklık bölgesi */
export interface TrafficZone {
    /** Başlangıç metrik pozisyon */
    startMeter: number;
    /** Bitiş metrik pozisyon */
    endMeter: number;
    /** Bu bölgedeki max hız (m/s) */
    maxSpeedMs: number;
    /** Kalan süre (sn) */
    remainingSeconds: number;
    /** Tıkanıklık seviyesi */
    severity: 'light' | 'moderate' | 'heavy';
}

/** Linearize edilmiş rota üzerindeki durak */
export interface LinearStop {
    /** Durak indexi */
    index: number;
    /** Durak adı */
    name: string;
    /** Hat üzerindeki metre pozisyonu */
    meterPosition: number;
    /** Lat/Lng */
    latitude: number;
    longitude: number;
    /** Tahmini yolcu sayısı (rush hour'a göre değişir) */
    passengerLoad: number;
    /** Kaç otobüs aynı anda durabilir */
    slotCount: number;
    /** Platform uzunluğu (metre) */
    platformLengthMeters: number;
}

/** Simülasyon konfigürasyonu */
export interface SimConfig {
    // === Fizik ===
    /** Maksimum ivme (m/s²) */
    maxAcceleration: number;
    /** Konforlu fren (m/s²) */
    comfortBraking: number;
    /** Acil fren (m/s²) */
    emergencyBraking: number;
    /** Maksimum hız (m/s) */
    maxSpeed: number;

    // === IDM ===
    /** Minimum boşluk (metre) */
    idmMinGap: number;
    /** Güvenli takip süresi (sn) */
    idmTimeHeadway: number;
    /** IDM delta exponent */
    idmDelta: number;

    // === Durak ===
    /** Kapı açma/kapama süresi (sn) */
    doorTime: number;
    /** Yolcu başına bekleme (sn) */
    perPassengerTime: number;
    /** Min dwell time (sn) */
    minDwellTime: number;
    /** Max dwell time (sn) */
    maxDwellTime: number;
    /** Durak yaklaşım mesafesi (metre) — frenleme başlangıcı */
    approachDistance: number;

    // === Trafik ===
    /** Trafik bölgesi oluşma olasılığı (per tick) */
    trafficSpawnRate: number;
    /** Ortalama trafik bölgesi süresi (sn) */
    trafficDuration: number;

    // === Segment hız limitleri (m/s) ===
    defaultSpeedLimit: number;

    // === Genel ===
    /** Araç sayısı */
    vehicleCount: number;
    /** Simülasyon hız çarpanı */
    timeScale: number;
}

/** Varsayılan simülasyon konfigürasyonu */
export const DEFAULT_SIM_CONFIG: SimConfig = {
    // Fizik
    maxAcceleration: 1.0,
    comfortBraking: 2.0,
    emergencyBraking: 4.5,
    maxSpeed: 14.0,        // ~50 km/h (metrobüs gerçekçi hız)

    // IDM
    idmMinGap: 2.0,
    idmTimeHeadway: 1.5,
    idmDelta: 4,

    // Durak
    doorTime: 5.0,
    perPassengerTime: 1.5,
    minDwellTime: 15.0,
    maxDwellTime: 30.0,
    approachDistance: 150.0,

    // Trafik
    trafficSpawnRate: 0.002,
    trafficDuration: 120.0,

    // Segment
    defaultSpeedLimit: 12.5,   // ~45 km/h

    // Genel
    vehicleCount: 15,
    timeScale: 5.0,
};

/** Tüm simülasyonun anlık durumu */
export interface SimState {
    /** Simülasyon zamanı (sn) */
    time: number;
    /** Tüm araçlar */
    vehicles: SimVehicle[];
    /** Aktif trafik bölgeleri */
    trafficZones: TrafficZone[];
    /** Rush hour mı? */
    isRushHour: boolean;
    /** Simülasyon çalışıyor mu? */
    running: boolean;
    /** Hız çarpanı */
    timeScale: number;
}
