// =============================================
// Route Network — Directed Graph Model
// Gidiş/Dönüş ayrı edge'ler, shared geometry tespiti
// =============================================

/** Yön tipi (simülasyon seviyesi) */
export type EdgeDirection = 'gidis' | 'donus';

/**
 * Bir OSM way'inden türetilmiş yönlü kenar.
 * Aynı way iki yönde kullanılsa bile iki ayrı RouteEdge kaydı oluşur.
 */
export interface RouteEdge {
    /** Benzersiz kenar ID'si — örn. "G_1305577742" veya "D_1305577742" */
    id: string;
    /** Kaynak OSM way ID'si */
    osmWayId: number;
    /** Hangi yöne ait */
    direction: EdgeDirection;
    /** Koordinat dizisi — seyahat yönünde sıralı [lat, lon][] */
    geometry: [number, number][];
    /** Relation içindeki sıra numarası (0-based) */
    sequenceIndex: number;
    /** Bu way her iki yön tarafından da kullanılıyor mu? */
    isSharedGeometry: boolean;
    /** Kenar uzunluğu (metre) */
    lengthMeters: number;
}

/**
 * Yönlü durak — bir edge üzerindeki konum.
 */
export interface NetworkStop {
    /** Benzersiz durak ID'si */
    id: string;
    /** OSM node ID'si */
    osmId: number;
    /** Durak adı */
    name: string;
    /** Hangi yöne ait */
    direction: EdgeDirection;
    /** Enlem */
    latitude: number;
    /** Boylam */
    longitude: number;
    /** Hangi edge üzerinde */
    edgeId: string;
    /** Edge üzerindeki normalize pozisyon (0.0 = başı, 1.0 = sonu) */
    positionAlongEdge: number;
}

/**
 * Tam rota ağı — gidiş ve dönüş ayrı ayrı.
 */
export interface RouteNetwork {
    /** Kenarlar — yöne göre ayrılmış */
    edges: {
        gidis: RouteEdge[];
        donus: RouteEdge[];
    };
    /** Duraklar — yöne göre ayrılmış */
    stops: {
        gidis: NetworkStop[];
        donus: NetworkStop[];
    };
    /** Her iki yön tarafından kullanılan OSM way ID'leri */
    sharedWayIds: number[];
    /** İstatistikler */
    stats: {
        totalEdgesGidis: number;
        totalEdgesDonus: number;
        totalStopsGidis: number;
        totalStopsDonus: number;
        sharedWayCount: number;
        totalLengthGidisMeters: number;
        totalLengthDonusMeters: number;
    };
}

/**
 * Simülasyonda araç pozisyonu — edge tabanlı
 */
export interface EdgePosition {
    /** Mevcut edge'in index'i (edges dizisindeki) */
    edgeIndex: number;
    /** Edge üzerindeki ilerleme (0.0 = başı, 1.0 = sonu) */
    progress: number;
    /** Yön */
    direction: EdgeDirection;
}
