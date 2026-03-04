// =============================================
// Decision Engine — Ana Giriş Noktası
// =============================================

import dotenv from 'dotenv';

dotenv.config();

export { RuleEngine } from './rules/rule-engine';
export type { RuleContext, RuleResult, Rule } from './rules/rule-engine';
export { CommandGenerator } from './commands/command-generator';
export { ApproachSpeedOptimizer } from './strategies/approach-optimizer';
export {
    criticalProximityRule,
    bunchingSlowDownRule,
    gappingSpeedUpRule,
    delaySpeedUpRule,
} from './rules/speed-rules';
export {
    skipStopRule,
    cautionStopRule,
    holdAtStopRule,
    rushHourCautionRule,
} from './rules/stop-rules';
export {
    approachSpeedOptimizeRule,
    approachQueueWarningRule,
} from './rules/approach-rules';

async function main() {
    console.log('=== Metrobüs Karar Motoru ===');
    console.log('Başlatılıyor...\n');

    const { CommandGenerator } = await import('./commands/command-generator');
    const generator = new CommandGenerator();

    console.log('✅ Karar motoru çalışıyor');
    console.log('  - 10 kural kayıtlı (çift durma önleme dahil)');
    console.log('  - Komut üretici aktif');

    process.on('SIGINT', () => {
        console.log('\nKapatılıyor...');
        process.exit(0);
    });
}

main().catch(console.error);
