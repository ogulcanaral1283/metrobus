// =============================================
// @metrobus/shared — Ana Giriş Noktası
// =============================================

// Types
export type { Vehicle, VehiclePosition, VehicleState, VehicleStatus, RouteDirection } from './types/vehicle';
export type { Station, StationCongestion, CongestionLevel, StationSlot, SlotOccupancy, ApproachOptimization } from './types/station';
export type { TrafficSegment, TrafficLevel, RouteTrafficSummary, HeadwayRecord, HeadwayStatus } from './types/traffic';
export type { CommandType, CommandSeverity, DriverCommand, HUDCommand } from './types/command';

// Functions
export { getCongestionLevel } from './types/station';
export { getHeadwayStatus } from './types/traffic';
export { toHUDCommand, COMMAND_DISPLAY_MAP } from './types/command';

// Constants
export { STATIONS_EAST, STATIONS_WEST, ALL_STATIONS, STATION_BY_CODE } from './constants/stations';
export { METROBUS_ROUTE_GEOMETRY, METROBUS_ROUTE_EAST, METROBUS_ROUTE_WEST } from './constants/route-geometry';
export {
    HEADWAY_CONFIG,
    CONGESTION_CONFIG,
    SPEED_CONFIG,
    DECISION_CONFIG,
    APPROACH_CONFIG,
    STATION_SLOT_CONFIG,
    INGESTION_CONFIG,
    WS_CHANNELS,
    KAFKA_TOPICS,
} from './constants/config';

// Utils
export {
    haversineDistance,
    calculateBearing,
    findNearestStation,
    moveAlongBearing,
    estimateTravelTime,
} from './utils/geo';

export {
    nowIstanbul,
    formatDuration,
    diffSeconds,
    isRushHour,
    isMorningRush,
    isEveningRush,
    formatTimestamp,
    ISTANBUL_TIMEZONE,
} from './utils/time';
