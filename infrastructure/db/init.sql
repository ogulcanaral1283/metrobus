-- ================================================
-- Metrobüs Akıllı Trafik Yönetim Sistemi
-- Veritabanı Şeması (TimescaleDB)
-- ================================================

-- TimescaleDB uzantısını etkinleştir
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

-- ================================================
-- 1. DURAK TANIMLARI
-- ================================================
CREATE TABLE stations (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(10) UNIQUE NOT NULL,
    name            VARCHAR(100) NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('east', 'west')),
    sequence_order  INTEGER NOT NULL,
    geom            GEOMETRY(Point, 4326),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stations_direction ON stations(direction);
CREATE INDEX idx_stations_geom ON stations USING GIST(geom);

-- ================================================
-- 2. ARAÇ TANIMLARI
-- ================================================
CREATE TABLE vehicles (
    id              SERIAL PRIMARY KEY,
    plate_number    VARCHAR(20) UNIQUE NOT NULL,
    vehicle_code    VARCHAR(10) UNIQUE NOT NULL,
    capacity        INTEGER DEFAULT 200,
    current_status  VARCHAR(20) DEFAULT 'inactive'
                    CHECK (current_status IN ('active', 'inactive', 'maintenance')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================
-- 3. ARAÇ KONUM VERİLERİ (Zaman Serisi)
-- ================================================
CREATE TABLE vehicle_positions (
    time            TIMESTAMPTZ NOT NULL,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    speed_kmh       DOUBLE PRECISION,
    heading         DOUBLE PRECISION,
    nearest_station_id INTEGER REFERENCES stations(id),
    distance_to_station DOUBLE PRECISION,
    geom            GEOMETRY(Point, 4326)
);

SELECT create_hypertable('vehicle_positions', 'time');
CREATE INDEX idx_vp_vehicle ON vehicle_positions(vehicle_id, time DESC);

-- ================================================
-- 4. HEADWAY VERİLERİ (Zaman Serisi)
-- ================================================
CREATE TABLE headway_records (
    time                TIMESTAMPTZ NOT NULL,
    leading_vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    following_vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    headway_seconds     DOUBLE PRECISION NOT NULL,
    headway_meters      DOUBLE PRECISION NOT NULL,
    station_id          INTEGER REFERENCES stations(id),
    direction           VARCHAR(10) NOT NULL
);

SELECT create_hypertable('headway_records', 'time');

-- ================================================
-- 5. DURAK YOĞUNLUK VERİLERİ (Zaman Serisi)
-- ================================================
CREATE TABLE station_congestion (
    time            TIMESTAMPTZ NOT NULL,
    station_id      INTEGER NOT NULL REFERENCES stations(id),
    congestion_score DOUBLE PRECISION NOT NULL CHECK (congestion_score BETWEEN 0 AND 100),
    passenger_count INTEGER,
    vehicle_count   INTEGER,
    avg_wait_time_sec DOUBLE PRECISION
);

SELECT create_hypertable('station_congestion', 'time');
CREATE INDEX idx_sc_station ON station_congestion(station_id, time DESC);

-- ================================================
-- 6. ŞOFÖR KOMUTLARI (Zaman Serisi)
-- ================================================
CREATE TABLE driver_commands (
    time            TIMESTAMPTZ NOT NULL,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    command_type    VARCHAR(20) NOT NULL
                    CHECK (command_type IN ('SLOW_DOWN', 'SPEED_UP', 'SKIP_STOP', 'HOLD', 'NORMAL', 'CAUTION')),
    severity        VARCHAR(10) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    message_tr      TEXT NOT NULL,
    reason          TEXT,
    target_speed_kmh DOUBLE PRECISION,
    target_station_id INTEGER REFERENCES stations(id),
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ
);

SELECT create_hypertable('driver_commands', 'time');
CREATE INDEX idx_dc_vehicle ON driver_commands(vehicle_id, time DESC);
CREATE INDEX idx_dc_active ON driver_commands(vehicle_id, time DESC) WHERE acknowledged = FALSE;

-- ================================================
-- 7. TRAFİK VERİLERİ (Zaman Serisi)
-- ================================================
CREATE TABLE traffic_data (
    time            TIMESTAMPTZ NOT NULL,
    segment_start_station_id INTEGER NOT NULL REFERENCES stations(id),
    segment_end_station_id   INTEGER NOT NULL REFERENCES stations(id),
    traffic_speed_kmh DOUBLE PRECISION,
    traffic_level   VARCHAR(10) CHECK (traffic_level IN ('free', 'light', 'moderate', 'heavy', 'standstill')),
    travel_time_sec DOUBLE PRECISION
);

SELECT create_hypertable('traffic_data', 'time');

-- ================================================
-- 8. SEFER PLANLARI
-- ================================================
CREATE TABLE trip_schedules (
    id              SERIAL PRIMARY KEY,
    vehicle_id      INTEGER NOT NULL REFERENCES vehicles(id),
    direction       VARCHAR(10) NOT NULL,
    planned_departure TIMESTAMPTZ NOT NULL,
    planned_arrival   TIMESTAMPTZ NOT NULL,
    actual_departure  TIMESTAMPTZ,
    actual_arrival    TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'scheduled'
                    CHECK (status IN ('scheduled', 'active', 'completed', 'cancelled')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================
-- Sürekli Aggregate (Her 5 dakika headway ortalaması)
-- ================================================
CREATE MATERIALIZED VIEW headway_5min_avg
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    direction,
    AVG(headway_seconds) AS avg_headway_sec,
    MIN(headway_seconds) AS min_headway_sec,
    MAX(headway_seconds) AS max_headway_sec,
    COUNT(*) AS record_count
FROM headway_records
GROUP BY bucket, direction;

-- Durak bazlı 15dk yoğunluk ortalaması
CREATE MATERIALIZED VIEW station_congestion_15min_avg
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', time) AS bucket,
    station_id,
    AVG(congestion_score) AS avg_score,
    MAX(congestion_score) AS max_score,
    AVG(passenger_count) AS avg_passengers
FROM station_congestion
GROUP BY bucket, station_id;
