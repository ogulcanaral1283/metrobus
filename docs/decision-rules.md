# Karar Motoru Kuralları

Bu döküman, metrobüs akıllı trafik yönetim sisteminin karar motoru kurallarını detaylı olarak açıklar.

## Kural Öncelik Sırası

Kurallar aşağıdaki öncelik sırasına göre değerlendirilir. İlk eşleşen kural komutu üretir.

| Öncelik | Kural | Açıklama |
|---------|-------|----------|
| 100 | Kritik Yakınlık | Öndeki araçla < 100m |
| 80 | Yığılma Yavaşlatma | Öndeki araçla < 200m |
| 70 | Durak Atlama | Durak yoğunluğu > 80 ve gecikme > 5dk |
| 60 | Durakta Bekleme | Durağa < 50m ve öndeki araç yakın |
| 50 | Boşluk Hızlandırma | Arkadaki araçtan > 6dk uzakta |
| 45 | Dikkat Durağı | Durak yoğunluğu > 60 |
| 40 | Gecikme Hızlandırma | Seferden > 5dk gecikme |
| 30 | Rush Hour Dikkati | Yoğun saatte düşük eşikli dikkat |
| 0 | Normal | Hiçbir kural eşleşmezse |

## Kural Detayları

### 1. Kritik Yakınlık (Öncelik: 100)
- **Koşul:** Öndeki araçla mesafe < 100 metre
- **Komut:** 🐢 YAVAŞLA (Kritik)
- **Hız Ayarı:** Mevcut hız × 0.55
- **Açıklama:** Çarpışma riski. Acil hız düşürme gerekir.

### 2. Yığılma Yavaşlatma (Öncelik: 80)
- **Koşul:** Öndeki araçla mesafe < 200 metre
- **Komut:** 🐢 YAVAŞLA (Yüksek)
- **Hız Ayarı:** Mevcut hız × 0.70
- **Açıklama:** Araçlar birbirine yaklaşıyor. Arayı açmak gerekir.

### 3. Durak Atlama (Öncelik: 70)
- **Koşul:** Sonraki durak yoğunluk skoru ≥ 80 VE seferden ≥ 5dk gecikme
- **Komut:** 🚀 DURMA, DEVAM ET (Yüksek)
- **Açıklama:** Durakta çok fazla araç birikmiş ve zaten gecikmede.

### 4. Durakta Bekleme (Öncelik: 60)
- **Koşul:** Durağa mesafe < 50m VE öndeki araçla mesafe < 300m
- **Komut:** ⏸️ DURAKTA BEKLE (Orta)
- **Bekleme Süresi:** Headway süresinin 1/3'ü
- **Açıklama:** Durakta kısa süre bekleyerek araçlar arası mesafeyi aç.

### 5. Boşluk Hızlandırma (Öncelik: 50)
- **Koşul:** Arkadaki araçla mesafe > 360 saniye
- **Komut:** ⏩ HIZLAN (Orta)
- **Hız Ayarı:** Mevcut hız × 1.20
- **Açıklama:** Arkadaki araç çok geride, aramızda boşluk oluşmuş.

### 6. Gecikme Hızlandırma (Öncelik: 40)
- **Koşul:** Sefer planından > 5 dakika gecikme
- **Komut:** ⏩ HIZLAN (Orta/Yüksek)
- **Hız Ayarı:** Mevcut hız × 1.20

### 7. Rush Hour Dikkati (Öncelik: 30)
- **Koşul:** Rush hour (07-09 veya 17-19) VE durak yoğunluğu > 48
- **Komut:** ⚠️ DİKKAT (Düşük)
- **Açıklama:** Yoğun saatlerde eşikler %20 düşürülür.

## Parametre Tablosu

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| BUNCHING_THRESHOLD | 200m | Yığılma eşiği |
| GAPPING_THRESHOLD | 360sn | Boşluk eşiği |
| IDEAL_HEADWAY | 180sn | İdeal araç arası süre |
| COMMAND_TTL | 120sn | Komut geçerlilik süresi |
| DECISION_INTERVAL | 5000ms | Karar yenileme aralığı |
| SLOW_DOWN_FACTOR | 0.30 | Hız düşürme oranı |
| SPEED_UP_FACTOR | 0.20 | Hız artırma oranı |
