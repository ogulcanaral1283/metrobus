# 1. GİRİŞ (Introduction)

## 1.1 Problem Tanımı: Otobüs Yığılması (Bus Bunching)

İstanbul metrobüs hattı, 52 km uzunluğunda, 44 durak ve günlük 1 milyon yolcuyla dünyanın en yoğun BRT (Bus Rapid Transit) sistemlerinden biridir. Beylikdüzü–Söğütlüçeşme arasında günde yaklaşık **2400 sefer** yapılmakta, pik saatlerde araç sefer aralığı **30 saniyeye** kadar düşmektedir.

Bu denli yoğun bir sistemin en kritik operasyonel sorunu **bus bunching** (otobüs yığılması) fenomenidir. Bunching, araçların eşit aralıklarla (headway) dağılması yerine gruplar halinde birbirine yapışarak seyretmesidir.

### Bunching Mekanizması

Bunching, pozitif geri besleme döngüsünden kaynaklanan bir **kararsız denge** problemidir (Daganzo, 2009):

```
1. İlk bozulma: Araç A trafik/yolcu yoğunluğu nedeniyle yavaşlar
                          ↓
2. Yolcu birikimi: A'nın arkasındaki duraklarda yolcular birikir
                          ↓
3. Gecikme kaskadı: Daha fazla yolcu = daha uzun durak süresi = daha fazla gecikme
                          ↓
4. Arkadaki araç yaklaşır: B arabası daha az yolcuyla karşılaşır → hızlanır
                          ↓
5. Yapışma (Bunching): A ve B birbirine yapışır → headway bozulur
                          ↓
6. Zincir reaksiyonu: Tüm hatta domino etkisi
```

**Görsel:**
```
t=0:  🚌────────🚌────────🚌────────🚌────────🚌
      Eşit headway (ideal)

t=1:  🚌──────🚌────────────🚌──────🚌────────🚌
      A yavaşladı, B yaklaştı

t=2:  🚌────🚌🚌──────────────────🚌🚌────────🚌
      İki bunching kümesi oluştu

t=3:  🚌🚌🚌🚌───────────────────────────🚌🚌🚌🚌
      Tam kaos — yolcular bazı duraklarda 15+ dk bekler
```

### Bunching'in Gerçek Dünya Etkileri

| Etki | Açıklama | Büyüklük |
|------|----------|----------|
| **Yolcu bekleme süresi** | Eşit headway'de ortalama bekleme = H/2. Bunching'de varyans artar → bazı yolcular çok daha uzun bekler | +%100-300 artış |
| **Kapasite israfı** | Ardışık gelen araçlar boş, arası açılanlar tıka basa dolu | %30-40 kapasite kaybı |
| **Operasyonel maliyet** | Düzensiz sefer → ek sefer ekleme ihtiyacı | Yıllık milyon TL |
| **Yolcu memnuniyeti** | Belirsiz bekleme → güven kaybı → alternatif ulaşıma geçiş | NPS düşüşü |
| **Enerji tüketimi** | Dur-kalk trafiği → yakıt israfı | +%15-20 yakıt |

### İstanbul Metrobüs Özelinde Sorun

İstanbul metrobüsünde bunching'i şiddetlendiren spesifik faktörler:

1. **Aşırı yolcu yoğunluğu**: Pik saatlerde 30 saniye aralıkla gelen araçlar bile dolup taşıyor
2. **Değişken platform kapasitesi**: Bazı duraklar 55m (2 araç), bazıları 232m (8 araç). Kısa peronlar darboğaz oluşturur
3. **Trafik etkileşimi**: Metrobüs hattı bazı bölgelerde otoyol yan şeridinde, trafik akışından etkileniyor
4. **Topografya**: Yükseklik farkları araç hızını etkiliyor (Büyükçekmece köprüsü, Haliç geçişi)
5. **Asimetrik talep**: Sabah Beylikdüzü→Şişli yoğun, akşam tersi — tek yönlü bunching

## 1.2 Mevcut Çözüm Yaklaşımlarının Sınırlılıkları

### 1.2.1 Sabit Tarifeli Sefer Yönetimi

En yaygın yöntem: önceden belirlenmiş kalkış saatleri ve sefer aralıkları.

**Avantajları:**
- Basit, uygulaması kolay
- Yolculara öngörülebilir takvim sunar

**Sınırlılıkları:**
- Gerçek zamanlı koşullara (kaza, hava durumu, etkinlik) uyum sağlayamaz
- Talep dalgalanmalarını yansıtmaz
- Bir araç geciktiğinde tüm takvim bozulur
- "Kendi kendini düzeltme" mekanizması yoktur

### 1.2.2 Kural Tabanlı Müdahale Sistemleri

Headway eşik değerlerine göre otomatik komutlar üretilir:
```
IF headway < 2dk THEN yavaşla
IF headway > 5dk THEN hızlan
IF durakta > 3 araç THEN bekle
```

**Avantajları:**
- Anlaşılabilir ve hata ayıklanabilir
- Deterministik davranış

**Sınırlılıkları:**
- Karmaşık etkileşimleri modelleyemez (A'yı yavaşlatman B ve C'yi de etkiler)
- Kural sayısı arttıkça çelişkiler ortaya çıkar
- Yerel optimum → global optimal değil
- Rush hour / off-peak farklılıkları el ile ayarlanmalı

### 1.2.3 Merkezi Optimizasyon

Tüm filoyu tek bir optimizasyon problemi olarak formüle etme:
```
min Σ (headway_i - target_headway)²
s.t. speed_min ≤ v_i ≤ speed_max
```

**Sınırlılıkları:**
- **Ölçeklenebilirlik**: 200 araç × sürekli hız = devasa karar uzayı
- **İletişim gecikmesi**: Merkez→araç komut gecikmesi (1-5 saniye)
- **Tek nokta arızası**: Merkez çökerse tüm sistem durur
- **Hesaplama maliyeti**: Her saniye NP-hard optimizasyon

### 1.2.4 Klasik Pekiştirmeli Öğrenme (Tek Ajan)

Tek bir merkezi ajan tüm araçları kontrol eder:

**Sınırlılıkları:**
- **Aksiyon uzayı patlaması**: N araç × K aksiyon = K^N kombinasyon. 200 araç × 4 aksiyon = 4^200 ≈ 10^120 — astronomik!
- **Credit assignment**: Hangi aracın aksiyonu genel ödüle katkı sağladı?
- **Eğitim kararlılığı**: Devasa aksiyon uzayında convergence zorlaşır

## 1.3 Önerilen Çözüm: MAPPO Tabanlı Dağıtık Filo Yönetimi

Bu çalışmada, **Multi-Agent Proximal Policy Optimization (MAPPO)** algoritması ile her metrobüsün bağımsız bir ajan olarak kendi hız/bekleme kararlarını verdiği dağıtık bir akıllı filo yönetim sistemi önerilmektedir.

### Temel Paradigma: CTDE

**Centralized Training, Decentralized Execution (CTDE):**

```
EĞİTİM AŞAMASI (Merkezi):              UYGULAMA AŞAMASI (Dağıtık):
┌──────────────────────┐                ┌──────────────────┐
│ Critic: Tüm araçların│                │ Araç #42:        │
│ bilgisini görür      │                │ Sadece kendi     │
│ (N×24 = 4800 dim)    │                │ gözlemini görür  │
│                      │                │ (24 dim)         │
│ "Bu durumda toplam   │                │                  │
│ reward ne olacak?"   │                │ "SLOW seçeyim"   │
└──────────────────────┘                └──────────────────┘
```

- **Eğitimde**: Merkezi Critic ağı tüm ajanların birleştirilmiş gözlemini kullanarak daha kararlı değer tahmini yapar
- **İcrada**: Her ajan sadece kendi yerel gözlemini kullanan hafif Actor ağı ile kararını verir — internet bağlantısı bile gerekmez

### Temel Katkılar

1. **Yüksek doğruluklu simülasyon**: OSM verilerinden gerçek hat geometrisi, IDM fizik motoru, 8-fazlı durak FSM, paralel peron operasyonu
2. **GPU-hızlandırılmış paralel eğitim**: CUDA Graph ile 512 paralel ortam, ~20,000 FPS, RTX 5070 Ti
3. **Hibrit karar mekanizması**: MAPPO (uzun vadeli strateji) + Predictive Lookahead Engine (anlık risk yönetimi)
4. **Gerçek zamanlı izleme**: WebSocket tabanlı canlı dashboard, Leaflet harita üzerinde 200 araç takibi
5. **Taşınabilir model çıktısı**: ONNX formatında export → browser (onnxruntime-web) veya edge cihazda çalıştırılabilir
