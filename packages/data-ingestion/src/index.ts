// =============================================
// Data Ingestion Service — Ana Giriş Noktası
// =============================================

import dotenv from 'dotenv';
import { GPSCollector } from './collectors/gps-collector';
import { IETTApiCollector } from './collectors/iett-api-collector';
import { KafkaPublisher } from './publishers/kafka-publisher';

dotenv.config();

async function main() {
    console.log('=== Metrobüs Veri Toplama Servisi ===');
    console.log('Başlatılıyor...\n');

    // Kafka bağlantısı
    const publisher = new KafkaPublisher();
    await publisher.connect();

    // GPS veri toplayıcı
    const gpsCollector = new GPSCollector();
    gpsCollector.on('position', async ({ topic, data }) => {
        try {
            await publisher.publish(topic, `vehicle-${data.vehicleId}`, data);
        } catch (err) {
            console.error('[Main] GPS verisi yayınlama hatası:', err);
        }
    });

    // İETT API toplayıcı
    const iettCollector = new IETTApiCollector();
    iettCollector.on('position', async ({ topic, data }) => {
        try {
            await publisher.publish(topic, `vehicle-${data.vehicleId}`, data);
        } catch (err) {
            console.error('[Main] İETT verisi yayınlama hatası:', err);
        }
    });

    // Graceful shutdown
    const shutdown = async () => {
        console.log('\nKapatılıyor...');
        await gpsCollector.stop();
        await iettCollector.stop();
        await publisher.disconnect();
        process.exit(0);
    };

    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

    // Servisleri başlat
    await gpsCollector.start();
    await iettCollector.start();

    console.log('\n✅ Veri toplama servisi çalışıyor');
}

main().catch(console.error);
