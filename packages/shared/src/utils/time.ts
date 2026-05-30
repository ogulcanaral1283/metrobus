// =============================================
// Zaman Yardımcı Fonksiyonları
// =============================================

/** İstanbul saat dilimi */
export const ISTANBUL_TIMEZONE = 'Europe/Istanbul';

/** Şimdiki zamanı İstanbul saatiyle döndür */
export function nowIstanbul(): Date {
    return new Date(
        new Date().toLocaleString('en-US', { timeZone: ISTANBUL_TIMEZONE })
    );
}

/** Saniyeyi okunabilir formata çevir (örn: "2dk 30sn") */
export function formatDuration(totalSeconds: number): string {
    if (totalSeconds < 0) return '0sn';
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = Math.floor(totalSeconds % 60);

    if (minutes === 0) return `${seconds}sn`;
    if (seconds === 0) return `${minutes}dk`;
    return `${minutes}dk ${seconds}sn`;
}

/** İki tarih arası fark (saniye) */
export function diffSeconds(a: Date, b: Date): number {
    return Math.abs(a.getTime() - b.getTime()) / 1000;
}

/** Saatin sabah rush hour olup olmadığını kontrol et */
export function isMorningRush(date: Date = new Date()): boolean {
    const hours = date.getHours();
    return hours >= 7 && hours <= 9;
}

/** Saatin akşam rush hour olup olmadığını kontrol et */
export function isEveningRush(date: Date = new Date()): boolean {
    const hours = date.getHours();
    return hours >= 17 && hours <= 19;
}

/** Rush hour'da mı? */
export function isRushHour(date: Date = new Date()): boolean {
    return isMorningRush(date) || isEveningRush(date);
}

/** Tarihi ISO formatında döndür (YYYY-MM-DD HH:mm:ss) */
export function formatTimestamp(date: Date): string {
    return date.toISOString().replace('T', ' ').substring(0, 19);
}
