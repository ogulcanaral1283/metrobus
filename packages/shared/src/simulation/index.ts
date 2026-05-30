// =============================================
// Simulation Module — Barrel Export
// =============================================

export type {
    SimVehicle,
    VehiclePhase,
    VehicleType,
    SimConfig,
    SimState,
    TrafficZone,
    LinearStop,
} from './sim-types';

export { DEFAULT_SIM_CONFIG, VEHICLE_TYPES, VEHICLE_GAP } from './sim-types';

export { SimEngine } from './sim-engine';

export type { LinearRoute } from './route-linearizer';
export { linearizeRoute, meterToPosition } from './route-linearizer';
