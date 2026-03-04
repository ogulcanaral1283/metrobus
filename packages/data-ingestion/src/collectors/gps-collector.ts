// =============================================
// GPS Veri Toplama Modülü
// =============================================

import { INGESTION_CONFIG, KAFKA_TOPICS } from '@metrobus/shared';
import type { VehiclePosition } from '@metrobus/shared';
import { EventEmitter } from 'events';

/**
 * GPS verisi toplama sınıfı
 * 
 * Gerçek ortamda: Araçlardaki GPS modülleri TCP/MQTT üzerinden veri gönderir.
 * Geliştirme ortamında: Simüle edilmiş GPS verileri kullanılır.
 */
export class GPSCollector extends EventEmitter {
    private intervalId: ReturnType<typeof setInterval> | null = null;
    private isRunning = false;

    constructor(
        private readonly pollIntervalMs: number = INGESTION_CONFIG.GPS_POLL_INTERVAL_MS
    ) {
        super();
    }

    /** GPS veri toplamayı başlat */
    async start(): Promise<void> {
        if (this.isRunning) return;
        this.isRunning = true;

        console.log(`[GPSCollector] Başlatıldı (her ${this.pollIntervalMs}ms)`);

        this.intervalId = setInterval(() => {
            this.collectPositions();
        }, this.pollIntervalMs);
    }

    /** GPS veri toplamayı durdur */
    async stop(): Promise<void> {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.isRunning = false;
        console.log('[GPSCollector] Durduruldu');
    }

    /** Araç pozisyonlarını topla ve yayınla */
    private async collectPositions(): Promise<void> {
        try {
            // TODO: Gerçek GPS veri kaynağına bağlan
            // Şu an için bu fonksiyon harici bir veri kaynağından
            // pozisyonları çekecek şekilde implement edilecek

            // GPS verileri geldiğinde:
            // this.emit('position', position);
        } catch (error) {
            console.error('[GPSCollector] Veri toplama hatası:', error);
            this.emit('error', error);
        }
    }

    /** Tek bir konum verisini manuel olarak işle */
    processPosition(position: VehiclePosition): void {
        this.emit('position', {
            topic: KAFKA_TOPICS.VEHICLE_POSITION,
            data: position,
        });
    }
}
