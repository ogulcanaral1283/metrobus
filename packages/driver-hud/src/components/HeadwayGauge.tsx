import React from 'react';

interface HeadwayGaugeProps {
    leadingDistance: number | null;     // metre
    followingDistance: number | null;   // metre
    leadingVehicleCode: string | null;
    followingVehicleCode: string | null;
}

/**
 * Araç Mesafe Göstergesi
 * Önde ve arkadaki araçla mesafeyi görsel olarak gösterir.
 */
const HeadwayGauge: React.FC<HeadwayGaugeProps> = ({
    leadingDistance,
    followingDistance,
    leadingVehicleCode,
    followingVehicleCode,
}) => {
    const getDistanceColor = (meters: number | null): string => {
        if (meters === null) return '#9E9E9E';
        if (meters < 200) return '#F44336';
        if (meters < 500) return '#FF9800';
        if (meters < 1000) return '#4CAF50';
        return '#2196F3';
    };

    const formatDistance = (meters: number | null): string => {
        if (meters === null) return '—';
        if (meters > 1000) return `${(meters / 1000).toFixed(1)}km`;
        return `${Math.round(meters)}m`;
    };

    return (
        <div className="headway-gauge">
            <div className="headway-title">ARAÇ MESAFELERİ</div>

            <div className="headway-bar">
                {/* Öndeki araç */}
                <div className="headway-section leading">
                    <div className="vehicle-label">
                        {leadingVehicleCode ? `🚌 ${leadingVehicleCode}` : '—'}
                    </div>
                    <div className="distance-bar">
                        <div
                            className="distance-fill"
                            style={{
                                width: leadingDistance
                                    ? `${Math.min(100, (leadingDistance / 2000) * 100)}%`
                                    : '0%',
                                backgroundColor: getDistanceColor(leadingDistance),
                            }}
                        />
                    </div>
                    <div
                        className="distance-value"
                        style={{ color: getDistanceColor(leadingDistance) }}
                    >
                        ↑ {formatDistance(leadingDistance)}
                    </div>
                </div>

                {/* Bu araç */}
                <div className="headway-section current">
                    <div className="current-vehicle">🚍 SİZ</div>
                </div>

                {/* Arkadaki araç */}
                <div className="headway-section following">
                    <div
                        className="distance-value"
                        style={{ color: getDistanceColor(followingDistance) }}
                    >
                        ↓ {formatDistance(followingDistance)}
                    </div>
                    <div className="distance-bar">
                        <div
                            className="distance-fill"
                            style={{
                                width: followingDistance
                                    ? `${Math.min(100, (followingDistance / 2000) * 100)}%`
                                    : '0%',
                                backgroundColor: getDistanceColor(followingDistance),
                            }}
                        />
                    </div>
                    <div className="vehicle-label">
                        {followingVehicleCode ? `🚌 ${followingVehicleCode}` : '—'}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default HeadwayGauge;
