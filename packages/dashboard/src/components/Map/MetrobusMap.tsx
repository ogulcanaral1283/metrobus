import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet';
import L from 'leaflet';
import { ALL_STATIONS } from '@metrobus/shared';
import type { VehicleState } from '@metrobus/shared';

import 'leaflet/dist/leaflet.css';

// İstanbul merkez koordinatları
const ISTANBUL_CENTER: [number, number] = [41.0370, 28.9850];
const DEFAULT_ZOOM = 12;

// Metrobüs güzergahı (durak koordinatları)
const routePositions: [number, number][] = ALL_STATIONS
    .filter((s) => !s.code.endsWith('W'))
    .sort((a, b) => a.sequenceOrder - b.sequenceOrder)
    .map((s) => [s.latitude, s.longitude]);

// Araç ikonu
const vehicleIcon = (color: string = '#2196F3') =>
    L.divIcon({
        className: 'vehicle-marker',
        html: `<div style="
      background: ${color};
      width: 24px;
      height: 24px;
      border-radius: 50%;
      border: 3px solid white;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
    ">🚍</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });

// Durak ikonu
const stationIcon = L.divIcon({
    className: 'station-marker',
    html: `<div style="
    background: #FF9800;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
  "></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
});

interface MetrobusMapProps {
    vehicles: VehicleState[];
}

/**
 * Metrobüs Harita Bileşeni
 * Araçları ve durakları harita üzerinde gösterir.
 */
const MetrobusMap: React.FC<MetrobusMapProps> = ({ vehicles }) => {
    const getVehicleColor = (vehicle: VehicleState): string => {
        if (!vehicle.currentCommand) return '#4CAF50';
        switch (vehicle.currentCommand.commandType) {
            case 'SLOW_DOWN':
                return '#FF9800';
            case 'SPEED_UP':
                return '#2196F3';
            case 'SKIP_STOP':
                return '#9C27B0';
            case 'HOLD':
                return '#F44336';
            case 'CAUTION':
                return '#FF5722';
            default:
                return '#4CAF50';
        }
    };

    return (
        <MapContainer
            center={ISTANBUL_CENTER}
            zoom={DEFAULT_ZOOM}
            style={{ width: '100%', height: '100%', borderRadius: '12px' }}
        >
            <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {/* Güzergah çizgisi */}
            <Polyline
                positions={routePositions}
                pathOptions={{
                    color: '#2196F3',
                    weight: 4,
                    opacity: 0.7,
                    dashArray: '10, 5',
                }}
            />

            {/* Durak işaretçileri */}
            {ALL_STATIONS
                .filter((s) => !s.code.endsWith('W'))
                .map((station) => (
                    <Marker
                        key={station.code}
                        position={[station.latitude, station.longitude]}
                        icon={stationIcon}
                    >
                        <Popup>
                            <strong>{station.name}</strong>
                            <br />
                            Kod: {station.code} | Sıra: {station.sequenceOrder}
                        </Popup>
                    </Marker>
                ))}

            {/* Araç işaretçileri */}
            {vehicles.map((vehicle) => (
                <Marker
                    key={vehicle.vehicleId}
                    position={[vehicle.position.latitude, vehicle.position.longitude]}
                    icon={vehicleIcon(getVehicleColor(vehicle))}
                >
                    <Popup>
                        <strong>🚍 {vehicle.vehicleCode}</strong>
                        <br />
                        Hız: {vehicle.speedKmh.toFixed(0)} km/s
                        <br />
                        Durak: {vehicle.nearestStation?.name || '—'}
                        <br />
                        Komut: {vehicle.currentCommand?.commandType || 'NORMAL'}
                    </Popup>
                </Marker>
            ))}
        </MapContainer>
    );
};

export default MetrobusMap;
