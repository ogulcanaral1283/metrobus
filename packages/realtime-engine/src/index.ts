// =============================================
// Realtime Engine — Ana Giriş Noktası
// =============================================

import dotenv from 'dotenv';
import { HeadwayCalculator } from './processors/headway-calculator';
import { BunchingDetector } from './processors/bunching-detector';
import { CongestionAnalyzer } from './processors/congestion-analyzer';

dotenv.config();

export { HeadwayCalculator } from './processors/headway-calculator';
export { BunchingDetector } from './processors/bunching-detector';
export { CongestionAnalyzer } from './processors/congestion-analyzer';

async function main() {
    console.log('=== Metrobüs Gerçek Zamanlı İşlem Motoru ===');
    console.log('Başlatılıyor...\n');

    const headwayCalc = new HeadwayCalculator();
    const bunchingDetector = new BunchingDetector();
    const congestionAnalyzer = new CongestionAnalyzer();

    // TODO: Kafka consumer'dan gelen verileri işle
    // 1. Vehicle position topic'inden pozisyon verilerini oku
    // 2. Her güncelleme için headway hesapla
    // 3. Bunching tespiti yap
    // 4. Durak yoğunluk analizi yap
    // 5. Sonuçları decision-engine'e ilet

    console.log('✅ Gerçek zamanlı işlem motoru çalışıyor');
    console.log('  - HeadwayCalculator: Aktif');
    console.log('  - BunchingDetector: Aktif');
    console.log('  - CongestionAnalyzer: Aktif');

    // Graceful shutdown
    process.on('SIGINT', () => {
        console.log('\nKapatılıyor...');
        process.exit(0);
    });
}

main().catch(console.error);
