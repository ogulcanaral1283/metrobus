// =============================================
// İETT API Veri Toplama Modülü
// =============================================

import axios, { type AxiosInstance } from 'axios';
import { INGESTION_CONFIG, KAFKA_TOPICS } from '@metrobus/shared';
import type { VehiclePosition } from '@metrobus/shared';
import { EventEmitter } from 'events';

/**
 * İETT/İBB Açık Veri API'sinden araç konum verisi toplama
 * 
 * İBB Açık Veri Portalı: https://data.ibb.gov.tr
 * Toplu Ulaşım API: Gerçek zamanlı araç konum verileri
 */
export class IETTApiCollector extends EventEmitter {
    private client: AxiosInstance;
    private intervalId: ReturnType<typeof setInterval> | null = null;
    private isRunning = false;

    constructor(
        private readonly baseUrl: string = process.env.IETT_API_BASE_URL || 'https://api.ibb.gov.tr',
        private readonly apiKey: string = process.env.IETT_API_KEY || '',
        private readonly pollIntervalMs: number = INGESTION_CONFIG.IETT_POLL_INTERVAL_MS
    ) {
        super();
        this.client = axios.create({
            baseURL: this.baseUrl,
            timeout: 10000,
            headers: {
                'Authorization': `Bearer ${this.apiKey}`,
                'Content-Type': 'application/json',
            },
        });
    }

    /** API veri toplamayı başlat */
    async start(): Promise<void> {
        if (this.isRunning) return;
        this.isRunning = true;

        console.log(`[IETTApiCollector] Başlatıldı (her ${this.pollIntervalMs}ms)`);

        // İlk sorguyu hemen yap
        await this.fetchVehiclePositions();

        this.intervalId = setInterval(() => {
            this.fetchVehiclePositions();
        }, this.pollIntervalMs);
    }

    /** API veri toplamayı durdur */
    async stop(): Promise<void> {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.isRunning = false;
        console.log('[IETTApiCollector] Durduruldu');
    }

    /** İETT API'den metrobüs konum verilerini çek */
    private async fetchVehiclePositions(): Promise<void> {
        try {
            // İBB Açık Veri API endpoint'i
            // Gerçek API yanıt formatına göre parse edilecek
            const response = await this.client.get('/iett/hatkonum', {
                params: {
                    hat_kodu: 'MR',  // Metrobüs hat kodu
                },
            });

            if (response.data && Array.isArray(response.data)) {
                const positions: VehiclePosition[] = response.data.map(
                    (item: Record<string, unknown>) => this.parsePosition(item)
                );

                for (const position of positions) {
                    this.emit('position', {
                        topic: KAFKA_TOPICS.VEHICLE_POSITION,
                        data: position,
                    });
                }

                console.log(`[IETTApiCollector] ${positions.length} araç konumu alındı`);
            }
        } catch (error) {
            // API erişim hatası durumunda simülasyona geçilebilir
            console.warn('[IETTApiCollector] API hatası, simülasyon moduna geçiyor:',
                error instanceof Error ? error.message : error
            );
            this.emit('error', error);
        }
    }

    /** API yanıtını VehiclePosition formatına dönüştür */
    private parsePosition(raw: Record<string, unknown>): VehiclePosition {
        return {
            time: new Date(),
            vehicleId: Number(raw.arac_id || raw.vehicle_id || 0),
            latitude: Number(raw.enlem || raw.latitude || 0),
            longitude: Number(raw.boylam || raw.longitude || 0),
            speedKmh: Number(raw.hiz || raw.speed || 0),
            heading: Number(raw.yon || raw.heading || 0),
            nearestStationId: null,
            distanceToStation: null,
        };
    }
}
