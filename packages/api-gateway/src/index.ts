// =============================================
// API Gateway — Ana Giriş Noktası
// =============================================

import express from 'express';
import { createServer } from 'http';
import { Server as SocketIOServer } from 'socket.io';
import cors from 'cors';
import dotenv from 'dotenv';
import { WS_CHANNELS } from '@metrobus/shared';

dotenv.config();

const PORT = Number(process.env.API_PORT) || 3000;
const WS_PORT = Number(process.env.WS_PORT) || 3001;

// Express app
const app = express();
app.use(cors());
app.use(express.json());

// ==================
// REST Endpoints
// ==================

/** Sağlık kontrolü */
app.get('/health', (_req, res) => {
    res.json({
        status: 'ok',
        service: 'metrobus-api-gateway',
        timestamp: new Date().toISOString(),
    });
});

/** Tüm araçların anlık durumu */
app.get('/api/vehicles', (_req, res) => {
    // TODO: Redis'ten araç durumlarını çek
    res.json({ vehicles: [], message: 'Araç verisi henüz bağlanmadı' });
});

/** Tek araç durumu */
app.get('/api/vehicles/:id', (req, res) => {
    const vehicleId = Number(req.params.id);
    // TODO: Redis'ten araç durumunu çek
    res.json({ vehicleId, message: 'Araç verisi henüz bağlanmadı' });
});

/** Durak listesi */
app.get('/api/stations', (_req, res) => {
    const { ALL_STATIONS } = require('@metrobus/shared');
    res.json({ stations: ALL_STATIONS });
});

/** Durak yoğunluk verisi */
app.get('/api/stations/:id/congestion', (req, res) => {
    const stationId = Number(req.params.id);
    // TODO: Veritabanından yoğunluk verisini çek
    res.json({ stationId, congestion: null, message: 'Yoğunluk verisi henüz bağlanmadı' });
});

/** Aktif komutlar */
app.get('/api/commands/active', (_req, res) => {
    // TODO: Decision engine'den aktif komutları çek
    res.json({ commands: [] });
});

/** Araç için aktif komut */
app.get('/api/commands/vehicle/:id', (req, res) => {
    const vehicleId = Number(req.params.id);
    // TODO: Araç komutunu çek
    res.json({ vehicleId, command: null });
});

/** Komut onayla (şoför) */
app.post('/api/commands/:commandId/acknowledge', (req, res) => {
    const { commandId } = req.params;
    // TODO: Komutu onayla
    res.json({ commandId, acknowledged: true });
});

// ==================
// WebSocket Server
// ==================

const httpServer = createServer(app);
const io = new SocketIOServer(httpServer, {
    cors: {
        origin: process.env.API_CORS_ORIGIN || '*',
        methods: ['GET', 'POST'],
    },
});

io.on('connection', (socket) => {
    console.log(`[WebSocket] Yeni bağlantı: ${socket.id}`);

    // Araç HUD bağlantısı
    socket.on('join:vehicle', (vehicleId: number) => {
        socket.join(`vehicle:${vehicleId}`);
        console.log(`[WebSocket] ${socket.id} araç ${vehicleId} kanalına katıldı`);
    });

    // Dashboard bağlantısı
    socket.on('join:dashboard', () => {
        socket.join('dashboard');
        console.log(`[WebSocket] ${socket.id} dashboard kanalına katıldı`);
    });

    socket.on('disconnect', () => {
        console.log(`[WebSocket] Bağlantı koptu: ${socket.id}`);
    });
});

/** Belirli bir araca komut gönder */
export function sendCommandToVehicle(vehicleId: number, command: unknown): void {
    io.to(`vehicle:${vehicleId}`).emit(WS_CHANNELS.DRIVER_COMMAND, command);
}

/** Dashboard'a güncelleme gönder */
export function broadcastToDashboard(event: string, data: unknown): void {
    io.to('dashboard').emit(event, data);
}

/** Tüm bağlı istemcilere gönder */
export function broadcastAll(event: string, data: unknown): void {
    io.emit(event, data);
}

// ==================
// Sunucuyu Başlat
// ==================

httpServer.listen(PORT, () => {
    console.log('=== Metrobüs API Gateway ===');
    console.log(`✅ REST API: http://localhost:${PORT}`);
    console.log(`✅ WebSocket: ws://localhost:${PORT}`);
    console.log(`\nEndpoints:`);
    console.log(`  GET  /health`);
    console.log(`  GET  /api/vehicles`);
    console.log(`  GET  /api/vehicles/:id`);
    console.log(`  GET  /api/stations`);
    console.log(`  GET  /api/stations/:id/congestion`);
    console.log(`  GET  /api/commands/active`);
    console.log(`  GET  /api/commands/vehicle/:id`);
    console.log(`  POST /api/commands/:commandId/acknowledge`);
});
