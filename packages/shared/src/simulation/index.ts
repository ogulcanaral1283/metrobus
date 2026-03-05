// =============================================
// Simulation Module — Barrel Export
// =============================================

export type {
    SimVehicle,
    VehiclePhase,
    SimConfig,
    SimState,
    TrafficZone,
    LinearStop,
} from './sim-types';

export { DEFAULT_SIM_CONFIG } from './sim-types';

export { SimEngine } from './sim-engine';

export type { LinearRoute } from './route-linearizer';
export { linearizeRoute, meterToPosition } from './route-linearizer';
