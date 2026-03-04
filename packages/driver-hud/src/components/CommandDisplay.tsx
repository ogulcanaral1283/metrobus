import React, { useState, useEffect } from 'react';
import type { HUDCommand, CommandType } from '@metrobus/shared';
import { COMMAND_DISPLAY_MAP } from '@metrobus/shared';

interface CommandDisplayProps {
    command: HUDCommand | null;
}

/**
 * Ana Komut Göstergesi
 * 
 * Şoförün göreceği en büyük ekran bileşeni.
 * Büyük ikon, net renk kodlaması ve okunabilir mesaj.
 */
const CommandDisplay: React.FC<CommandDisplayProps> = ({ command }) => {
    const [isFlashing, setIsFlashing] = useState(false);

    useEffect(() => {
        if (command && (command.severity === 'critical' || command.severity === 'high')) {
            setIsFlashing(true);
            const timer = setTimeout(() => setIsFlashing(false), 3000);
            return () => clearTimeout(timer);
        }
    }, [command]);

    if (!command) {
        return (
            <div className="command-display command-normal">
                <div className="command-icon">✅</div>
                <div className="command-title">NORMAL SEYİR</div>
                <div className="command-message">Akış normal. Güvenli sürüş.</div>
            </div>
        );
    }

    const display = COMMAND_DISPLAY_MAP[command.commandType];
    const severityClass = `command-${command.severity}`;
    const flashClass = isFlashing ? 'flashing' : '';

    return (
        <div
            className={`command-display ${severityClass} ${flashClass}`}
            style={{
                '--command-color': display.color,
                '--command-bg': display.bgColor,
            } as React.CSSProperties}
        >
            <div className="command-icon">{display.icon}</div>
            <div className="command-title">{display.title}</div>
            <div className="command-message">{command.message}</div>

            {command.targetSpeed && (
                <div className="command-speed">
                    <span className="speed-label">Hedef Hız:</span>
                    <span className="speed-value">{Math.round(command.targetSpeed)}</span>
                    <span className="speed-unit">km/s</span>
                </div>
            )}

            <div className="command-timer">
                Kalan: {command.expiresIn > 0 ? `${command.expiresIn}sn` : 'Süresi doldu'}
            </div>
        </div>
    );
};

export default CommandDisplay;
