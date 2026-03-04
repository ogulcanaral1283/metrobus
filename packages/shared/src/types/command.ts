// =============================================
// Şoför Komut Modelleri
// =============================================

/** Komut tipi */
export type CommandType =
    | 'SLOW_DOWN'     // 🐢 Yavaşla
    | 'SPEED_UP'      // ⏩ Hızlan
    | 'SKIP_STOP'     // 🚀 Durakta durma
    | 'HOLD'          // ⏸️  Durakta bekle
    | 'NORMAL'        // ✅ Normal seyir
    | 'CAUTION';      // ⚠️  Dikkat

/** Komut öncelik seviyesi */
export type CommandSeverity = 'low' | 'medium' | 'high' | 'critical';

/** Şoför komutu */
export interface DriverCommand {
    id: string;
    time: Date;
    vehicleId: number;
    commandType: CommandType;
    severity: CommandSeverity;
    messageTr: string;
    reason: string;
    targetSpeedKmh: number | null;
    targetStationId: number | null;
    acknowledged: boolean;
    acknowledgedAt: Date | null;
    expiresAt: Date;
}

/** HUD'da gösterilecek komut bilgisi */
export interface HUDCommand {
    commandType: CommandType;
    severity: CommandSeverity;
    icon: string;
    title: string;
    message: string;
    color: string;
    targetSpeed: number | null;
    expiresIn: number; // saniye
}

/** Komut tipi → görsel eşlemeleri */
export const COMMAND_DISPLAY_MAP: Record<CommandType, {
    icon: string;
    title: string;
    color: string;
    bgColor: string;
}> = {
    SLOW_DOWN: {
        icon: '🐢',
        title: 'YAVAŞLA',
        color: '#FF9800',
        bgColor: '#FFF3E0',
    },
    SPEED_UP: {
        icon: '⏩',
        title: 'HIZLAN',
        color: '#2196F3',
        bgColor: '#E3F2FD',
    },
    SKIP_STOP: {
        icon: '🚀',
        title: 'DURMA, DEVAM ET',
        color: '#9C27B0',
        bgColor: '#F3E5F5',
    },
    HOLD: {
        icon: '⏸️',
        title: 'DURAKTA BEKLE',
        color: '#F44336',
        bgColor: '#FFEBEE',
    },
    NORMAL: {
        icon: '✅',
        title: 'NORMAL SEYİR',
        color: '#4CAF50',
        bgColor: '#E8F5E9',
    },
    CAUTION: {
        icon: '⚠️',
        title: 'DİKKAT',
        color: '#FF5722',
        bgColor: '#FBE9E7',
    },
};

/** Komutu HUD formatına dönüştür */
export function toHUDCommand(command: DriverCommand): HUDCommand {
    const display = COMMAND_DISPLAY_MAP[command.commandType];
    const expiresIn = Math.max(
        0,
        Math.floor((command.expiresAt.getTime() - Date.now()) / 1000)
    );

    return {
        commandType: command.commandType,
        severity: command.severity,
        icon: display.icon,
        title: display.title,
        message: command.messageTr,
        color: display.color,
        targetSpeed: command.targetSpeedKmh,
        expiresIn,
    };
}
