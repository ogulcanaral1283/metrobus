// =============================================
// Sistem Konfigürasyon Sabitleri
// =============================================

/** Headway (araç arası mesafe) parametreleri */
export const HEADWAY_CONFIG = {
    /** Minimum güvenli headway (saniye) */
    MIN_HEADWAY_SECONDS: 60,
    /** Maksimum kabul edilebilir headway (saniye) */
    MAX_HEADWAY_SECONDS: 300,
    /** İdeal headway (saniye) */
    IDEAL_HEADWAY_SECONDS: 180,
    /** Bunching eşiği (metre) — önde araçla bu mesafeden yakınsa "yığılma" */
    BUNCHING_THRESHOLD_METERS: 200,
    /** Gapping eşiği (saniye) — arkadaki araçtan bu kadar uzaksa "boşluk" */
    GAPPING_THRESHOLD_SECONDS: 360,
} as const;

/** Yoğunluk parametreleri */
export const CONGESTION_CONFIG = {
    /** Uyarı tetiklenme eşiği (0-100) */
    WARNING_THRESHOLD: 60,
    /** Kritik eşik */
    CRITICAL_THRESHOLD: 80,
    /** Hesaplama penceresi (saniye) */
    CALCULATION_WINDOW_SECONDS: 300,
} as const;

/** Hız ayarlama parametreleri */
export const SPEED_CONFIG = {
    /** Maksimum metrobüs hızı (km/s) */
    MAX_SPEED_KMH: 70,
    /** Minimum metrobüs hızı (km/s) */
    MIN_SPEED_KMH: 10,
    /** Yavaşlama faktörü (0-1 arası) */
    SLOW_DOWN_FACTOR: 0.30,
    /** Hızlanma faktörü */
    SPEED_UP_FACTOR: 0.20,
} as const;

/** Karar motoru parametreleri */
export const DECISION_CONFIG = {
    /** Komut geçerlilik süresi (saniye) */
    COMMAND_TTL_SECONDS: 120,
    /** Karar yenileme aralığı (ms) */
    DECISION_INTERVAL_MS: 5000,
    /** Minimum sefer gecikmesi (dk) — altında aksiyon alınmaz */
    MIN_DELAY_MINUTES: 2,
    /** Durak atlama kararı gecikme eşiği (dk) */
    SKIP_STOP_DELAY_MINUTES: 5,
} as const;

/** Yaklaşım hızı optimizasyon parametreleri (Çift Durma Önleme) */
export const APPROACH_CONFIG = {
    /** Karar bölgesi — durağa kaç metre kala optimize başlasın */
    APPROACH_ZONE_METERS: 500,
    /** Minimum yaklaşım hızı (km/s) — bunun altına düşmez */
    MIN_APPROACH_SPEED_KMH: 15,
    /** Maksimum yaklaşım hızı (km/s) */
    MAX_APPROACH_SPEED_KMH: 50,
    /** Güvenlik tamponu — slot boşaldıktan sonra ek bekleme (sn) */
    SLOT_CLEARANCE_BUFFER_SECONDS: 5,
    /** Yaklaşım toleransı — hedefe ±bu kadar kayma kabul edilir (sn) */
    ARRIVAL_TOLERANCE_SECONDS: 3,
} as const;

/** Durak slot parametreleri */
export const STATION_SLOT_CONFIG = {
    /** Varsayılan slot sayısı (durak başına) */
    DEFAULT_SLOT_COUNT: 1,
    /** Ortalama dwell time — araç durağa girdikten sonra kalış süresi (sn) */
    AVG_DWELL_TIME_SECONDS: 30,
    /** Minimum dwell time */
    MIN_DWELL_TIME_SECONDS: 15,
    /** Maksimum dwell time */
    MAX_DWELL_TIME_SECONDS: 60,
    /** Slot boşalma zaman aşımı — bu süreden sonra slot boşalmış kabul et (sn) */
    SLOT_TIMEOUT_SECONDS: 90,
} as const;

/** Veri toplama frekansları */
export const INGESTION_CONFIG = {
    /** GPS veri toplama aralığı (ms) */
    GPS_POLL_INTERVAL_MS: 2000,
    /** İETT API sorgulama aralığı (ms) */
    IETT_POLL_INTERVAL_MS: 5000,
    /** Trafik verisi sorgulama aralığı (ms) */
    TRAFFIC_POLL_INTERVAL_MS: 30000,
    /** Durak sensör verisi aralığı (ms) */
    STATION_SENSOR_INTERVAL_MS: 5000,
} as const;

/** WebSocket kanalları */
export const WS_CHANNELS = {
    VEHICLE_POSITION: 'vehicle:position',
    VEHICLE_STATE: 'vehicle:state',
    DRIVER_COMMAND: 'driver:command',
    STATION_CONGESTION: 'station:congestion',
    SYSTEM_ALERT: 'system:alert',
    HEADWAY_UPDATE: 'headway:update',
} as const;

/** Kafka topic isimleri */
export const KAFKA_TOPICS = {
    VEHICLE_POSITION: 'metrobus.vehicle.position',
    STATION_CONGESTION: 'metrobus.station.congestion',
    TRAFFIC_FLOW: 'metrobus.traffic.flow',
    HEADWAY_CALCULATED: 'metrobus.headway.calculated',
    DECISION_COMMAND: 'metrobus.decision.command',
    ALERT_BUNCHING: 'metrobus.alert.bunching',
} as const;
