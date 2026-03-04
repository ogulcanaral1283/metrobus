import React from 'react';
import { formatDuration } from '@metrobus/shared';

interface NextStopInfoProps {
    stationName: string;
    stationCode: string;
    etaSeconds: number;
    congestionScore: number;
    distanceMeters: number;
}

/**
 * Sonraki Durak Bilgisi
 * Şoföre sonraki durağın adını, tahmini varış süresini
 * ve yoğunluk durumunu gösterir.
 */
const NextStopInfo: React.FC<NextStopInfoProps> = ({
    stationName,
    stationCode,
    etaSeconds,
    congestionScore,
    distanceMeters,
}) => {
    const getCongestionColor = (score: number): string => {
        if (score < 30) return '#4CAF50';
        if (score < 60) return '#FF9800';
        if (score < 80) return '#FF5722';
        return '#F44336';
    };

    const getCongestionText = (score: number): string => {
        if (score < 30) return 'Düşük';
        if (score < 60) return 'Orta';
        if (score < 80) return 'Yüksek';
        return 'Kritik';
    };

    return (
        <div className="next-stop-info">
            <div className="next-stop-header">
                <span className="next-stop-label">SONRAKİ DURAK</span>
                <span className="next-stop-eta">{formatDuration(etaSeconds)}</span>
            </div>

            <div className="next-stop-name">
                <span className="station-code">{stationCode}</span>
                <span className="station-name">{stationName}</span>
            </div>

            <div className="next-stop-details">
                <div className="detail-item">
                    <span className="detail-label">Mesafe</span>
                    <span className="detail-value">
                        {distanceMeters > 1000
                            ? `${(distanceMeters / 1000).toFixed(1)} km`
                            : `${Math.round(distanceMeters)} m`}
                    </span>
                </div>

                <div className="detail-item">
                    <span className="detail-label">Yoğunluk</span>
                    <span
                        className="detail-value congestion-badge"
                        style={{ color: getCongestionColor(congestionScore) }}
                    >
                        {getCongestionText(congestionScore)} ({congestionScore})
                    </span>
                </div>
            </div>
        </div>
    );
};

export default NextStopInfo;
