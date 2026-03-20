// =============================================
// Metrobüs Durak Listesi — İBB/İETT Resmi Koordinatları
// Beylikdüzü Son Durak → Söğütlüçeşme (44 durak)
// Kaynak: İETT DurakDetay_GYY API — api.ibb.gov.tr
// Güncelleme: 2026-03-19
// =============================================

import type { Station } from '../types/station';

/**
 * Doğu yönü durakları — batıdan doğuya
 * Koordinatlar İBB/İETT resmi SOAP servisinden alınmıştır.
 * İETT G-yönü (gidiş): Beylikdüzü → Söğütlüçeşme
 */
export const STATIONS_EAST: Omit<Station, 'id' | 'isActive'>[] = [
    { code: 'TYP', name: 'Beylikdüzü Son Durak', latitude: 41.021588, longitude: 28.626396, direction: 'east', sequenceOrder: 1 },
    { code: 'HDM', name: 'Beykent', latitude: 41.020042, longitude: 28.630195, direction: 'east', sequenceOrder: 2 },
    { code: 'CMH', name: 'Cumhuriyet Mahallesi', latitude: 41.015690, longitude: 28.641287, direction: 'east', sequenceOrder: 3 },
    { code: 'BLB', name: 'Beylikdüzü Belediye', latitude: 41.012857, longitude: 28.648654, direction: 'east', sequenceOrder: 4 },
    { code: 'BYL', name: 'Beylikdüzü', latitude: 41.010105, longitude: 28.655979, direction: 'east', sequenceOrder: 5 },
    { code: 'GZY', name: 'Güzelyurt', latitude: 41.006887, longitude: 28.664558, direction: 'east', sequenceOrder: 6 },
    { code: 'HRM', name: 'Haramidere', latitude: 41.006124, longitude: 28.672149, direction: 'east', sequenceOrder: 7 },
    { code: 'HRS', name: 'Haramidere Sanayi', latitude: 41.004981, longitude: 28.684034, direction: 'east', sequenceOrder: 8 },
    { code: 'SDD', name: 'Saadetdere Mahallesi', latitude: 40.999999, longitude: 28.691828, direction: 'east', sequenceOrder: 9 },
    { code: 'MKP', name: 'Mustafa Kemalpaşa', latitude: 40.995449, longitude: 28.705573, direction: 'east', sequenceOrder: 10 },
    { code: 'CHN', name: 'Cihangir - Üniversite Mah.', latitude: 40.990623, longitude: 28.713823, direction: 'east', sequenceOrder: 11 },
    { code: 'AVC', name: 'Avcılar Mrk. Ünv. Kamp.', latitude: 40.983943, longitude: 28.725630, direction: 'east', sequenceOrder: 12 },
    { code: 'SKB', name: 'Şükrübey', latitude: 40.980334, longitude: 28.731567, direction: 'east', sequenceOrder: 13 },
    { code: 'IBB', name: 'İBB Sosyal Tesisleri', latitude: 40.977879, longitude: 28.744385, direction: 'east', sequenceOrder: 14 },
    { code: 'KCK', name: 'Küçükçekmece', latitude: 40.986318, longitude: 28.769151, direction: 'east', sequenceOrder: 15 },
    { code: 'CEN', name: 'Cennet Mahallesi', latitude: 40.985331, longitude: 28.781809, direction: 'east', sequenceOrder: 16 },
    { code: 'FLR', name: 'Florya', latitude: 40.986225, longitude: 28.787102, direction: 'east', sequenceOrder: 17 },
    { code: 'BES', name: 'Beşyol', latitude: 40.993761, longitude: 28.794694, direction: 'east', sequenceOrder: 18 },
    { code: 'SKY', name: 'Sefaköy', latitude: 40.998206, longitude: 28.797890, direction: 'east', sequenceOrder: 19 },
    { code: 'YNB', name: 'Yenibosna', latitude: 40.992322, longitude: 28.834679, direction: 'east', sequenceOrder: 20 },
    { code: 'ASR', name: 'Şirinevler', latitude: 40.991799, longitude: 28.844667, direction: 'east', sequenceOrder: 21 },
    { code: 'BHC', name: 'Bahçelievler', latitude: 40.995152, longitude: 28.863754, direction: 'east', sequenceOrder: 22 },
    { code: 'INC', name: 'İncirli', latitude: 40.998396, longitude: 28.874530, direction: 'east', sequenceOrder: 23 },
    { code: 'ZYT', name: 'Zeytinburnu', latitude: 41.003137, longitude: 28.890269, direction: 'east', sequenceOrder: 24 },
    { code: 'MER', name: 'Merter', latitude: 41.007601, longitude: 28.897303, direction: 'east', sequenceOrder: 25 },
    { code: 'CVZ', name: 'Cevizlibağ', latitude: 41.015775, longitude: 28.909788, direction: 'east', sequenceOrder: 26 },
    { code: 'TPK', name: 'Topkapı - Şehit M. Cambaz', latitude: 41.019997, longitude: 28.916752, direction: 'east', sequenceOrder: 27 },
    { code: 'BYM', name: 'Bayrampaşa - Maltepe', latitude: 41.023872, longitude: 28.921544, direction: 'east', sequenceOrder: 28 },
    { code: 'EDK', name: 'Edirnekapı', latitude: 41.033730, longitude: 28.930145, direction: 'east', sequenceOrder: 29 },
    { code: 'AYV', name: 'Ayvansaray Eyüpsultan', latitude: 41.038797, longitude: 28.937605, direction: 'east', sequenceOrder: 30 },
    { code: 'HLC', name: 'Halıcıoğlu', latitude: 41.048049, longitude: 28.945498, direction: 'east', sequenceOrder: 31 },
    { code: 'OKM2', name: 'Okmeydanı', latitude: 41.056186, longitude: 28.960613, direction: 'east', sequenceOrder: 32 },
    { code: 'PRP', name: 'Darülaceze Perpa', latitude: 41.061571, longitude: 28.967044, direction: 'east', sequenceOrder: 33 },
    { code: 'OKH', name: 'Okmeydanı Hastane', latitude: 41.067303, longitude: 28.974914, direction: 'east', sequenceOrder: 34 },
    { code: 'CGL', name: 'Çağlayan', latitude: 41.067415, longitude: 28.980225, direction: 'east', sequenceOrder: 35 },
    { code: 'MEC', name: 'Mecidiyeköy', latitude: 41.066987, longitude: 28.990905, direction: 'east', sequenceOrder: 36 },
    { code: 'ZNK', name: 'Zincirlikuyu', latitude: 41.065963, longitude: 29.011905, direction: 'east', sequenceOrder: 37 },
    { code: 'BGZ', name: '15 Temmuz Şehitler Köprüsü', latitude: 41.036205, longitude: 29.043289, direction: 'east', sequenceOrder: 38 },
    { code: 'BRH', name: 'Burhaniye', latitude: 41.032436, longitude: 29.047265, direction: 'east', sequenceOrder: 39 },
    { code: 'ALT', name: 'Altunizade', latitude: 41.022517, longitude: 29.047945, direction: 'east', sequenceOrder: 40 },
    { code: 'ACB', name: 'Acıbadem', latitude: 41.015120, longitude: 29.056474, direction: 'east', sequenceOrder: 41 },
    { code: 'UZN', name: 'Uzunçayır', latitude: 40.999567, longitude: 29.057276, direction: 'east', sequenceOrder: 42 },
    { code: 'FKT', name: 'Fikirtepe', latitude: 40.993955, longitude: 29.048646, direction: 'east', sequenceOrder: 43 },
    { code: 'SGC', name: 'Söğütlüçeşme', latitude: 40.991147, longitude: 29.038218, direction: 'east', sequenceOrder: 44 },
];

/** Batı yönü durakları (Söğütlüçeşme → Beylikdüzü Son Durak) */
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
