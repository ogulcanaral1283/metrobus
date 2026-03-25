/**
 * Export route network data to JSON for Python consumption.
 * Run: node rl_env/scripts/export_route_data.js
 */
const fs = require('fs');
const path = require('path');

// Read the TS file and extract the JSON object
const tsFile = fs.readFileSync(
    path.join(__dirname, '../../packages/shared/src/constants/route-network-data.ts'),
    'utf8'
);

// Extract the JSON object from the TS file
const match = tsFile.match(/export const ROUTE_NETWORK:\s*RouteNetwork\s*=\s*({[\s\S]*});/);
if (!match) {
    console.error('Could not find ROUTE_NETWORK in source file');
    process.exit(1);
}

const data = JSON.parse(match[1]);

// Write to JSON
const outDir = path.join(__dirname, '..', 'data');
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(
    path.join(outDir, 'route_network.json'),
    JSON.stringify(data, null, 2),
    'utf8'
);

console.log('Exported route_network.json');
console.log(`  Gidis edges: ${data.edges.gidis.length}`);
console.log(`  Donus edges: ${data.edges.donus.length}`);
console.log(`  Gidis stops: ${data.stops.gidis.length}`);
console.log(`  Donus stops: ${data.stops.donus.length}`);
