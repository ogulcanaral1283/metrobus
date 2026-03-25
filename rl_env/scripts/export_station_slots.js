/**
 * Export station slots data to JSON for Python consumption.
 * Run: node rl_env/scripts/export_station_slots.js
 */
const fs = require('fs');
const path = require('path');

const tsFile = fs.readFileSync(
    path.join(__dirname, '../../packages/shared/src/constants/station-slots.ts'),
    'utf8'
);

// Extract the array from TS
const match = tsFile.match(/export const STATION_SLOTS:\s*StationSlotInfo\[\]\s*=\s*(\[[\s\S]*?\]);/);
if (!match) {
    console.error('Could not find STATION_SLOTS');
    process.exit(1);
}

const data = JSON.parse(match[1]);

// Write to JSON
const outDir = path.join(__dirname, '..', 'data');
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(
    path.join(outDir, 'station_slots.json'),
    JSON.stringify(data, null, 2),
    'utf8'
);

console.log(`Exported station_slots.json: ${data.length} stations`);

// Summary
const multiSlot = data.filter(s => s.slotCount > 1).length;
const singleSlot = data.filter(s => s.slotCount === 1).length;
const avgPlatform = data.filter(s => s.platformLengthMeters > 0)
    .reduce((sum, s) => sum + s.platformLengthMeters, 0) / multiSlot;
console.log(`  Multi-slot (2+): ${multiSlot}`);
console.log(`  Single-slot: ${singleSlot}`);
console.log(`  Avg platform length: ${avgPlatform.toFixed(0)}m`);
