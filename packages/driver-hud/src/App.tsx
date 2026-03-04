import React, { useState, useEffect } from 'react';
import CommandDisplay from './components/CommandDisplay';
import NextStopInfo from './components/NextStopInfo';
import HeadwayGauge from './components/HeadwayGauge';
import type { HUDCommand } from '@metrobus/shared';
import './styles/hud.css';

/**
 * Şoför HUD Ana Uygulaması
 * 
 * Araç içi ekranda gösterilecek ana uygulama.
 * WebSocket üzerinden gerçek zamanlı komut ve durum güncellemeleri alır.
 */
const App: React.FC = () => {
    const [currentCommand, setCurrentCommand] = useState<HUDCommand | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const [currentTime, setCurrentTime] = useState(new Date());

    // Saat güncelleme
    useEffect(() => {
        const timer = setInterval(() => setCurrentTime(new Date()), 1000);
        return () => clearInterval(timer);
    }, []);

    // TODO: WebSocket bağlantısı
    // useEffect(() => {
    //   const socket = io(WS_URL);
    //   socket.on('connect', () => setIsConnected(true));
    //   socket.on('driver:command', (cmd) => setCurrentCommand(cmd));
    //   return () => socket.disconnect();
    // }, []);

    return (
        <>
            {/* Üst: Ana Komut */}
            <CommandDisplay command={currentCommand} />

            {/* Orta: Bilgi Panelleri */}
            <div className="hud-main">
                <NextStopInfo
                    stationName="Zincirlikuyu"
                    stationCode="ZNK"
                    etaSeconds={120}
                    congestionScore={45}
                    distanceMeters={850}
                />
                <div className="hud-sidebar">
                    <HeadwayGauge
                        leadingDistance={650}
                        followingDistance={1200}
                        leadingVehicleCode="MB003"
                        followingVehicleCode="MB005"
                    />
                </div>
            </div>

            {/* Alt: Durum Çubuğu */}
            <div className="status-bar">
                <div className="status-item">
                    <div className={`status-dot ${isConnected ? '' : 'error'}`} />
                    {isConnected ? 'Bağlı' : 'Bağlantı Bekleniyor...'}
                </div>
                <div className="status-item">
                    🚍 MB004 | Doğu Yönü
                </div>
                <div className="status-item">
                    {currentTime.toLocaleTimeString('tr-TR')}
                </div>
            </div>
        </>
    );
};

export default App;
