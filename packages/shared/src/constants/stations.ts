// =============================================
// Metrobüs Durak Listesi — Gerçek Koordinatlar
// TÜYAP → Söğütlüçeşme (45 durak)
// =============================================

import type { Station } from '../types/station';

/**
 * Doğu yönü durakları — batıdan doğuya
 * Tüm koordinatlar D-100/E-5 üzerinde doğrulanmıştır.
 */
export const STATIONS_EAST: Omit<Station, 'id' | 'isActive'>[] = [
    { code: 'TYP', name: 'Tüyap', latitude: 41.022058, longitude: 28.623512, direction: 'east', sequenceOrder: 1 },
    { code: 'HDM', name: 'Hadımköy', latitude: 41.019286, longitude: 28.631496, direction: 'east', sequenceOrder: 2 },
    { code: 'CMH', name: 'Cumhuriyet Mahallesi', latitude: 41.015463, longitude: 28.641471, direction: 'east', sequenceOrder: 3 },
    { code: 'BLB', name: 'Beylikdüzü Belediye', latitude: 41.012418, longitude: 28.649437, direction: 'east', sequenceOrder: 4 },
    { code: 'BYL', name: 'Beylikdüzü', latitude: 41.009508, longitude: 28.657147, direction: 'east', sequenceOrder: 5 },
    { code: 'GZY', name: 'Güzelyurt', latitude: 41.006637, longitude: 28.665256, direction: 'east', sequenceOrder: 6 },
    { code: 'HRM', name: 'Haramidere', latitude: 41.005981, longitude: 28.673016, direction: 'east', sequenceOrder: 7 },
    { code: 'HRS', name: 'Haramidere Sanayi', latitude: 41.004230, longitude: 28.685371, direction: 'east', sequenceOrder: 8 },
    { code: 'SDD', name: 'Saadetdere Mah.', latitude: 40.999715, longitude: 28.693001, direction: 'east', sequenceOrder: 9 },
    { code: 'MKP', name: 'Mustafa Kemal Paşa', latitude: 40.994998, longitude: 28.706146, direction: 'east', sequenceOrder: 10 },
    { code: 'CHN', name: 'Cihangir Üniversite Mah.', latitude: 40.990706, longitude: 28.713657, direction: 'east', sequenceOrder: 11 },
    { code: 'AVC', name: 'Avcılar Merk. Ünv. Kamp.', latitude: 40.983601, longitude: 28.725913, direction: 'east', sequenceOrder: 12 },
    { code: 'SKB', name: 'Şükrübey', latitude: 40.980358, longitude: 28.731326, direction: 'east', sequenceOrder: 13 },
    { code: 'IBB', name: 'İBB Sosyal Tesisleri', latitude: 40.978088, longitude: 28.745463, direction: 'east', sequenceOrder: 14 },
    { code: 'KCK', name: 'Küçükçekmece', latitude: 40.986372, longitude: 28.769420, direction: 'east', sequenceOrder: 15 },
    { code: 'CEN', name: 'Cennet Mahallesi', latitude: 40.985346, longitude: 28.782645, direction: 'east', sequenceOrder: 16 },
    { code: 'FLR', name: 'Florya-Bağlar', latitude: 40.987586, longitude: 28.790428, direction: 'east', sequenceOrder: 17 },
    { code: 'BES', name: 'Beşyol', latitude: 40.994992, longitude: 28.795078, direction: 'east', sequenceOrder: 18 },
    { code: 'SKY', name: 'Sefaköy', latitude: 40.998818, longitude: 28.798906, direction: 'east', sequenceOrder: 19 },
    { code: 'YNB', name: 'Yenibosna', latitude: 40.992316, longitude: 28.834746, direction: 'east', sequenceOrder: 20 },
    { code: 'ASR', name: 'Ataköy-Şirinevler', latitude: 40.991741, longitude: 28.845778, direction: 'east', sequenceOrder: 21 },
    { code: 'BHC', name: 'Bahçelievler', latitude: 40.995186, longitude: 28.863941, direction: 'east', sequenceOrder: 22 },
    { code: 'INC', name: 'İncirli', latitude: 40.997877, longitude: 28.872609, direction: 'east', sequenceOrder: 23 },
    { code: 'ZYT', name: 'Zeytinburnu', latitude: 41.003521, longitude: 28.891227, direction: 'east', sequenceOrder: 24 },
    { code: 'MER', name: 'Merter', latitude: 41.007522, longitude: 28.897266, direction: 'east', sequenceOrder: 25 },
    { code: 'CVZ', name: 'Cevizlibağ', latitude: 41.016555, longitude: 28.911123, direction: 'east', sequenceOrder: 26 },
    { code: 'TPK', name: 'Topkapı', latitude: 41.020432, longitude: 28.917463, direction: 'east', sequenceOrder: 27 },
    { code: 'BYM', name: 'Bayrampaşa-Maltepe', latitude: 41.023933, longitude: 28.921484, direction: 'east', sequenceOrder: 28 },
    { code: 'AMB', name: 'Adnan Menderes Bulvarı', latitude: 41.030035, longitude: 28.924704, direction: 'east', sequenceOrder: 29 },
    { code: 'EDK', name: 'Edirnekapı', latitude: 41.032933, longitude: 28.928614, direction: 'east', sequenceOrder: 30 },
    { code: 'AYV', name: 'Ayvansaray-Eyüp', latitude: 41.038476, longitude: 28.937238, direction: 'east', sequenceOrder: 31 },
    { code: 'HLC', name: 'Halıcıoğlu', latitude: 41.048658, longitude: 28.946185, direction: 'east', sequenceOrder: 32 },
    { code: 'OKM2', name: 'Okmeydanı', latitude: 41.056704, longitude: 28.961473, direction: 'east', sequenceOrder: 33 },
    { code: 'PRP', name: 'Darülaceze-Perpa', latitude: 41.063086, longitude: 28.968340, direction: 'east', sequenceOrder: 34 },
    { code: 'OKH', name: 'Okmeydanı Hastane', latitude: 41.067358, longitude: 28.975802, direction: 'east', sequenceOrder: 35 },
    { code: 'CGL', name: 'Çağlayan', latitude: 41.067320, longitude: 28.981552, direction: 'east', sequenceOrder: 36 },
    { code: 'MEC', name: 'Mecidiyeköy', latitude: 41.066822, longitude: 28.992503, direction: 'east', sequenceOrder: 37 },
    { code: 'ZNK', name: 'Zincirlikuyu', latitude: 41.067505, longitude: 29.013945, direction: 'east', sequenceOrder: 38 },
    { code: 'BGZ', name: 'Boğaziçi Köprüsü', latitude: 41.036750, longitude: 29.043541, direction: 'east', sequenceOrder: 39 },
    { code: 'BRH', name: 'Burhaniye', latitude: 41.031934, longitude: 29.046852, direction: 'east', sequenceOrder: 40 },
    { code: 'ALT', name: 'Altunizade', latitude: 41.021126, longitude: 29.048928, direction: 'east', sequenceOrder: 41 },
    { code: 'ACB', name: 'Acıbadem', latitude: 41.015031, longitude: 29.056570, direction: 'east', sequenceOrder: 42 },
    { code: 'UZN', name: 'Uzunçayır', latitude: 40.998883, longitude: 29.056412, direction: 'east', sequenceOrder: 43 },
    { code: 'FKT', name: 'Fikirtepe', latitude: 40.993656, longitude: 29.047085, direction: 'east', sequenceOrder: 44 },
    { code: 'SGC', name: 'Söğütlüçeşme', latitude: 40.991442, longitude: 29.037863, direction: 'east', sequenceOrder: 45 },
];

/** Batı yönü durakları (Söğütlüçeşme → Tüyap) */
export const STATIONS_WEST: Omit<Station, 'id' | 'isActive'>[] = STATIONS_EAST
    .slice()
    .reverse()
    .map((s, i) => ({
        ...s,
        code: s.code + 'W',
        direction: 'west' as const,
        sequenceOrder: i + 1,
    }));

/** Tüm duraklar */
export const ALL_STATIONS = [...STATIONS_EAST, ...STATIONS_WEST];

/** Durak koduna göre hızlı erişim */
export const STATION_BY_CODE = new Map(
    ALL_STATIONS.map((s) => [s.code, s])
);
