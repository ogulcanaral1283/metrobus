// =============================================
// Kafka Mesaj Yayıncısı
// =============================================

import { Kafka, type Producer, type Message } from 'kafkajs';
import { KAFKA_TOPICS } from '@metrobus/shared';

/**
 * Kafka Producer — Toplanan verileri Kafka topic'lerine yayınlar
 */
export class KafkaPublisher {
    private kafka: Kafka;
    private producer: Producer;
    private isConnected = false;

    constructor(
        brokers: string[] = [process.env.KAFKA_BROKERS || 'localhost:9092'],
        clientId: string = process.env.KAFKA_CLIENT_ID || 'metrobus-ingestion'
    ) {
        this.kafka = new Kafka({
            clientId,
            brokers,
            retry: {
                initialRetryTime: 300,
                retries: 8,
            },
        });
        this.producer = this.kafka.producer();
    }

    /** Kafka'ya bağlan */
    async connect(): Promise<void> {
        if (this.isConnected) return;
        await this.producer.connect();
        this.isConnected = true;
        console.log('[KafkaPublisher] Kafka\'ya bağlandı');
    }

    /** Bağlantıyı kapat */
    async disconnect(): Promise<void> {
        if (!this.isConnected) return;
        await this.producer.disconnect();
        this.isConnected = false;
        console.log('[KafkaPublisher] Kafka bağlantısı kapatıldı');
    }

    /** Tek bir mesaj gönder */
    async publish(topic: string, key: string, value: unknown): Promise<void> {
        if (!this.isConnected) {
            throw new Error('Kafka\'ya bağlı değil');
        }

        await this.producer.send({
            topic,
            messages: [
                {
                    key,
                    value: JSON.stringify(value),
                    timestamp: Date.now().toString(),
                },
            ],
        });
    }

    /** Toplu mesaj gönder */
    async publishBatch(
        topic: string,
        messages: Array<{ key: string; value: unknown }>
    ): Promise<void> {
        if (!this.isConnected) {
            throw new Error('Kafka\'ya bağlı değil');
        }

        const kafkaMessages: Message[] = messages.map((m) => ({
            key: m.key,
            value: JSON.stringify(m.value),
            timestamp: Date.now().toString(),
        }));

        await this.producer.send({
            topic,
            messages: kafkaMessages,
        });
    }

    /** Araç konum verisi yayınla */
    async publishVehiclePosition(
        vehicleId: number,
        position: unknown
    ): Promise<void> {
        await this.publish(
            KAFKA_TOPICS.VEHICLE_POSITION,
            `vehicle-${vehicleId}`,
            position
        );
    }

    /** Durak yoğunluk verisi yayınla */
    async publishStationCongestion(
        stationId: number,
        congestion: unknown
    ): Promise<void> {
        await this.publish(
            KAFKA_TOPICS.STATION_CONGESTION,
            `station-${stationId}`,
            congestion
        );
    }
}
