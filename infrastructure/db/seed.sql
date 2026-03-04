-- ================================================
-- Metrobüs Durak Test Verileri
-- (Beylikdüzü → Söğütlüçeşme yönü - doğu)
-- ================================================

INSERT INTO stations (code, name, latitude, longitude, direction, sequence_order) VALUES
-- Batı → Doğu yönü
('BYL', 'Beylikdüzü Sondurak', 41.0053, 28.6433, 'east', 1),
('YMH', 'Yakuplu Mahallesi', 41.0048, 28.6563, 'east', 2),
('HBY', 'Haramidere Beylikdüzü', 41.0031, 28.6693, 'east', 3),
('HRM', 'Haramidere', 41.0020, 28.6790, 'east', 4),
('TNL', 'Tem-İstanbul Yolu', 41.0010, 28.6940, 'east', 5),
('AVG', 'Avcılar-Gerçekleşenler', 41.0003, 28.7120, 'east', 6),
('AVC', 'Avcılar', 40.9987, 28.7213, 'east', 7),
('MSN', 'Mersin Caddesi', 40.9970, 28.7360, 'east', 8),
('SKS', 'Sefaköy Siteler', 40.9960, 28.7473, 'east', 9),
('SFK', 'Sefaköy', 40.9947, 28.7580, 'east', 10),
('YVZ', 'Yavuz Selim', 40.9940, 28.7710, 'east', 11),
('IKT', 'İkitelli Sanayi', 40.9930, 28.7810, 'east', 12),
('MHM', 'Mahmutbey', 41.0450, 28.8100, 'east', 13),
('IST', 'İSTOÇ', 41.0500, 28.8240, 'east', 14),
('MEH', 'Mehmet Akif', 41.0550, 28.8440, 'east', 15),
('TMY', 'TEM-Atatürk Havalimanı Yolu', 41.0370, 28.8560, 'east', 16),
('CKM', 'Cevizlibağ', 41.0143, 28.9193, 'east', 17),
('AKS', 'Aksaray', 41.0120, 28.9520, 'east', 18),
('UNK', 'Ünkapanı', 41.0190, 28.9617, 'east', 19),
('CPT', 'Cibali-Topkapı', 41.0230, 28.9677, 'east', 20),
('AYV', 'Ayvansaray', 41.0290, 28.9570, 'east', 21),
('EDK', 'Edirnekapı', 41.0370, 28.9393, 'east', 22),
('ATR', 'Atatürk Köprüsü', 41.0443, 28.9720, 'east', 23),
('HLC', 'Halıcıoğlu', 41.0460, 28.9800, 'east', 24),
('KGT', 'Kağıthane', 41.0523, 28.9860, 'east', 25),
('CGL', 'Çağlayan', 41.0590, 28.9893, 'east', 26),
('PST', 'Perpa-Okmeydanı', 41.0560, 29.0003, 'east', 27),
('DRN', 'Darülaceze', 41.0510, 29.0110, 'east', 28),
('MEC', 'Mecidiyeköy', 41.0640, 29.0133, 'east', 29),
('ZNK', 'Zincirlikuyu', 41.0667, 29.0207, 'east', 30),
('BLM', 'Balmumcu', 41.0617, 29.0273, 'east', 31),
('NRK', 'Nispetiye', 41.0570, 29.0347, 'east', 32),
('ETL', 'Etiler', 41.0530, 29.0413, 'east', 33),
('OYK', 'Oyak', 41.0680, 29.0440, 'east', 34),
('BPZ', 'Boğaziçi Köprüsü', 41.0770, 29.0500, 'east', 35),
('AHH', 'Altunizade-Hastane', 41.0240, 29.0480, 'east', 36),
('UZL', 'Uzunçayır', 41.0170, 29.0550, 'east', 37),
('ACS', 'Acıbadem', 41.0090, 29.0500, 'east', 38),
('HYT', 'Hasanpaşa', 41.0013, 29.0440, 'east', 39),
('FKT', 'Fikirtepe', 40.9943, 29.0383, 'east', 40),
('KDK', 'Kadıköy', 40.9893, 29.0333, 'east', 41),
('SGC', 'Söğütlüçeşme', 40.9847, 29.0293, 'east', 42);

-- Batı yönü durakları (aynı duraklar ters sıra)
INSERT INTO stations (code, name, latitude, longitude, direction, sequence_order)
SELECT
    code || 'W',
    name,
    latitude,
    longitude,
    'west',
    43 - sequence_order
FROM stations
WHERE direction = 'east';

-- PostGIS geometri alanlarını güncelle
UPDATE stations SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);

-- Örnek araçlar
INSERT INTO vehicles (plate_number, vehicle_code, capacity, current_status) VALUES
('34 MBX 001', 'MB001', 200, 'active'),
('34 MBX 002', 'MB002', 200, 'active'),
('34 MBX 003', 'MB003', 200, 'active'),
('34 MBX 004', 'MB004', 200, 'active'),
('34 MBX 005', 'MB005', 200, 'active'),
('34 MBX 006', 'MB006', 200, 'active'),
('34 MBX 007', 'MB007', 200, 'active'),
('34 MBX 008', 'MB008', 200, 'active'),
('34 MBX 009', 'MB009', 200, 'active'),
('34 MBX 010', 'MB010', 200, 'active'),
('34 MBX 011', 'MB011', 200, 'inactive'),
('34 MBX 012', 'MB012', 200, 'inactive'),
('34 MBX 013', 'MB013', 200, 'maintenance'),
('34 MBX 014', 'MB014', 200, 'maintenance'),
('34 MBX 015', 'MB015', 200, 'active');
