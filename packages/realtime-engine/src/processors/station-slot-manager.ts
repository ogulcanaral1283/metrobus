// =============================================
// Durak Slot Yöneticisi (Station Slot Manager)
// Çift Durma Problemi Çözümü — Slot Takibi
// =============================================

import {
    STATION_SLOT_CONFIG,
    type StationSlot,
    type SlotOccupancy,
    type VehicleState,
} from '@metrobus/shared';

/**
 * Durak Slot Yöneticisi
 * 
 * Her duraktaki slot doluluk durumunu gerçek zamanlı takip eder.
 * Yaklaşan araçlara "slotun ne zaman boşalacağını" tahmin eder.
 * 
 * Temel mantık:
 * - Araç durağa < 30m yaklaştığında → slot'a girdi kabul et
 * - Araç duraktan > 50m uzaklaştığında → slot'tan çıktı kabul et
 * - Slot boşalma tahmini = aracın giriş zamanı + ortalama dwell time
 */
export class StationSlotManager {
    /** Her durak için slot durumu */
    private slots: Map<number, StationSlot> = new Map();
    /** Her duraktaki aktif slot doluluk detayları */
    private occupancies: Map<number, SlotOccupancy[]> = new Map();
    /** Geçmiş dwell time'lar (durak bazlı, ortalama hesabı için) */
    private dwellTimeHistory: Map<number, number[]> = new Map();

    private readonly maxDwellHistory = 20;
    private readonly entryThresholdMeters = 30;
    private readonly exitThresholdMeters = 50;

    constructor(stationIds: number[], slotsPerStation: number = STATION_SLOT_CONFIG.DEFAULT_SLOT_COUNT) {
        for (const stationId of stationIds) {
            this.slots.set(stationId, {
                stationId,
                totalSlots: slotsPerStation,
                occupiedSlots: 0,
                queueLength: 0,
            });
            this.occupancies.set(stationId, []);
            this.dwellTimeHistory.set(stationId, []);
        }
    }

    /**
     * Araç pozisyon güncellemesiyle slot durumunu güncelle
     * - Durağa yakın → slot'a giriş
     * - Duraktan uzaklaştı → slot'tan çıkış
     */
    updateVehiclePosition(vehicle: VehicleState): void {
        if (!vehicle.nearestStation) return;

        const stationId = vehicle.nearestStation.id;
        const distance = vehicle.nearestStation.distanceMeters;

        const occupancyList = this.occupancies.get(stationId);
        if (!occupancyList) return;

        const isInSlot = occupancyList.some((o) => o.vehicleId === vehicle.vehicleId);

        // Durağa yakın ve henüz slotta değil → giriş
        if (distance <= this.entryThresholdMeters && !isInSlot) {
            this.enterSlot(stationId, vehicle);
        }
        // Duraktan uzaklaştı ve slotta → çıkış
        else if (distance > this.exitThresholdMeters && isInSlot) {
            this.exitSlot(stationId, vehicle.vehicleId);
        }

        // Timeout kontrolü — çok uzun süredir slotta olanları temizle
        this.cleanupStaleOccupancies(stationId);
    }

    /**
     * Araç slota giriş
     */
    private enterSlot(stationId: number, vehicle: VehicleState): void {
        const slot = this.slots.get(stationId);
        const occupancyList = this.occupancies.get(stationId);
        if (!slot || !occupancyList) return;

        const avgDwell = this.getAverageDwellTime(stationId);
        const now = new Date();

        const occupancy: SlotOccupancy = {
            stationId,
            slotIndex: slot.occupiedSlots,
            vehicleId: vehicle.vehicleId,
            vehicleCode: vehicle.vehicleCode,
            enteredAt: now,
            estimatedDwellSec: avgDwell,
            estimatedDepartureAt: new Date(now.getTime() + avgDwell * 1000),
        };

        occupancyList.push(occupancy);
        slot.occupiedSlots = Math.min(occupancyList.length, slot.totalSlots);
        slot.queueLength = Math.max(0, occupancyList.length - slot.totalSlots);

        console.log(
            `[SlotManager] 🅿️ ${vehicle.vehicleCode} → Durak ${stationId} slotuna girdi ` +
            `(${slot.occupiedSlots}/${slot.totalSlots} dolu, kuyruk: ${slot.queueLength})`
        );
    }

    /**
     * Araç slottan çıkış
     */
    private exitSlot(stationId: number, vehicleId: number): void {
        const slot = this.slots.get(stationId);
        const occupancyList = this.occupancies.get(stationId);
        if (!slot || !occupancyList) return;

        const index = occupancyList.findIndex((o) => o.vehicleId === vehicleId);
        if (index === -1) return;

        const occupancy = occupancyList[index];
        const actualDwellSec = (Date.now() - occupancy.enteredAt.getTime()) / 1000;

        // Gerçek dwell time'ı geçmişe kaydet (gelecek tahminler için)
        this.recordDwellTime(stationId, actualDwellSec);

        occupancyList.splice(index, 1);
        slot.occupiedSlots = Math.min(occupancyList.length, slot.totalSlots);
        slot.queueLength = Math.max(0, occupancyList.length - slot.totalSlots);

        console.log(
            `[SlotManager] 🚀 Araç ${vehicleId} → Durak ${stationId} slotundan çıktı ` +
            `(gerçek süre: ${actualDwellSec.toFixed(0)}sn, ` +
            `${slot.occupiedSlots}/${slot.totalSlots} dolu)`
        );
    }

    /**
     * Stale (zaman aşımına uğramış) slot girişlerini temizle
     */
    private cleanupStaleOccupancies(stationId: number): void {
        const occupancyList = this.occupancies.get(stationId);
        const slot = this.slots.get(stationId);
        if (!occupancyList || !slot) return;

        const now = Date.now();
        const timeout = STATION_SLOT_CONFIG.SLOT_TIMEOUT_SECONDS * 1000;

        const stale = occupancyList.filter(
            (o) => now - o.enteredAt.getTime() > timeout
        );

        for (const s of stale) {
            const idx = occupancyList.indexOf(s);
            if (idx >= 0) {
                occupancyList.splice(idx, 1);
                console.log(
                    `[SlotManager] ⏰ Araç ${s.vehicleId} timeout — Durak ${stationId} slotundan silindi`
                );
            }
        }

        slot.occupiedSlots = Math.min(occupancyList.length, slot.totalSlots);
        slot.queueLength = Math.max(0, occupancyList.length - slot.totalSlots);
    }

    // ==========================================
    // SORGULAMA METODLARİ
    // ==========================================

    /**
     * Durak slot durumunu sorgula
     */
    getSlotStatus(stationId: number): StationSlot | null {
        return this.slots.get(stationId) || null;
    }

    /**
     * Slot'un dolu olup olmadığını kontrol et
     */
    isSlotOccupied(stationId: number): boolean {
        const slot = this.slots.get(stationId);
        if (!slot) return false;
        return slot.occupiedSlots >= slot.totalSlots;
    }

    /**
     * 🎯 ANA FONKSIYON: Tahmini slot boşalma süresi (saniye)
     * 
     * Yaklaşan araç bu fonksiyonu çağırarak
     * "slot ne zaman boşalacak?" sorusunun yanıtını alır.
     * 
     * @returns Tahmini boşalma süresi (sn), slot boşsa 0
     */
    estimateSlotClearanceTime(stationId: number): number {
        const slot = this.slots.get(stationId);
        const occupancyList = this.occupancies.get(stationId);
        if (!slot || !occupancyList) return 0;

        // Slot boşsa → 0
        if (slot.occupiedSlots < slot.totalSlots) return 0;

        // En erken ayrılacak araç
        let earliestDeparture = Infinity;
        const now = Date.now();

        for (const occ of occupancyList) {
            const departureTime = occ.estimatedDepartureAt.getTime();
            const remaining = Math.max(0, (departureTime - now) / 1000);
            if (remaining < earliestDeparture) {
                earliestDeparture = remaining;
            }
        }

        // Kuyrukta da araç varsa, her birinin dwell time'ını ekle
        if (slot.queueLength > 0) {
            const avgDwell = this.getAverageDwellTime(stationId);
            earliestDeparture += slot.queueLength * avgDwell;
        }

        return earliestDeparture === Infinity ? 0 : Math.ceil(earliestDeparture);
    }

    /**
     * Slot doluluk detaylarını getir
     */
    getOccupancies(stationId: number): SlotOccupancy[] {
        return this.occupancies.get(stationId) || [];
    }

    /**
     * Tüm dolu durakları listele
     */
    getOccupiedStations(): StationSlot[] {
        const result: StationSlot[] = [];
        for (const slot of this.slots.values()) {
            if (slot.occupiedSlots > 0) {
                result.push(slot);
            }
        }
        return result;
    }

    // ==========================================
    // DWELL TIME TAHMİNİ
    // ==========================================

    /**
     * Geçmiş dwell time'ları kaydet
     */
    private recordDwellTime(stationId: number, dwellSec: number): void {
        // Aşırı kısa veya uzun değerleri filtrele
        if (
            dwellSec < STATION_SLOT_CONFIG.MIN_DWELL_TIME_SECONDS ||
            dwellSec > STATION_SLOT_CONFIG.MAX_DWELL_TIME_SECONDS * 2
        ) {
            return;
        }

        const history = this.dwellTimeHistory.get(stationId) || [];
        history.push(dwellSec);
        if (history.length > this.maxDwellHistory) {
            history.shift();
        }
        this.dwellTimeHistory.set(stationId, history);
    }

    /**
     * Durak bazlı ortalama dwell time
     * Geçmiş yoksa varsayılan değeri kullan
     */
    getAverageDwellTime(stationId: number): number {
        const history = this.dwellTimeHistory.get(stationId);
        if (!history || history.length < 3) {
            return STATION_SLOT_CONFIG.AVG_DWELL_TIME_SECONDS;
        }

        const sum = history.reduce((a, b) => a + b, 0);
        return sum / history.length;
    }
}
