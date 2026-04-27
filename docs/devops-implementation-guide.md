# 🎓 Metrobüs AI — Bitirme Projesi Araştırma Görevleri

> **Proje:** İstanbul Metrobüs Hattı için MAPPO Tabanlı Akıllı Filo Yönetimi
> 
> Bu döküman, projenin farklı alt sistemlerini araştırmanız, anlamanız ve iyileştirme önerileri sunmanız için hazırlanmıştır. Her görev bağımsızdır — kendi alanınızı derinlemesine araştırın ve bulgularınızı takıma sunun.

---

## Projeyi Anlamak İçin Önce Bunları Okuyun

```
docs/paper/00_abstract.md        ← Projenin genel özeti
docs/paper/01_introduction.md    ← Bus bunching problemi nedir
docs/paper/04_ai_models.md       ← AI modeli nasıl çalışıyor
docs/ai-decision-engine.md       ← Bir simülasyon adımının anatomisi (detaylı)
```

Projeyi lokalde çalıştırmak için:
```bash
# Dashboard (harita + simülasyon)
npm install && npm run dev:dashboard    # → localhost:3001

# Eğitim
cd rl_env && python train.py            # → GPU'da eğitim başlar

# Eğitim grafikleri
python -m tensorboard.main --logdir logs  # → localhost:6006
```

---

## GÖREV 1: Reward Fonksiyonu Araştırması ve Optimizasyonu

**Dosya:** `rl_env/gpu_env.py` → `_vectorized_reward()` metodu (satır ~750-790)

### Mevcut Durum
Sistemimiz 4 bileşenli bir reward fonksiyonu kullanıyor:

```
R = R_headway(w=10) + R_bunching(w=5) + R_dwell(w=0.5) + R_speed(w=2)
```

### Araştırma Soruları

1. **Ağırlık dengeleri**: Mevcut ağırlıklar (10, 5, 0.5, 2) deneme-yanılmayla belirlenmiş. Bu ağırlıkların optimum değerlerini nasıl bulabiliriz?
   - Araştır: **Bayesian Hyperparameter Optimization** (Optuna, Ray Tune)
   - Araştır: **Population Based Training (PBT)** — eğitim sırasında otomatik ağırlık ayarlama
   - Makale: Jaderberg et al. (2017) - "Population Based Training of Neural Networks"

2. **Headway metrigi**: Biz Coefficient of Variation (CV) kullanıyoruz. Alternatifler ne?
   - Araştır: **Gini katsayısı** headway eşitliği için daha iyi olabilir mi?
   - Araştır: **Squared headway deviation** — Cats et al. (2011) kullanmış
   - Araştır: **Excess wait time** — yolcu perspektifinden metrik

3. **Reward shaping**: Mevcut reward sadece o anki duruma bakıyor. Gelecek bilgisini eklemeli miyiz?
   - Araştır: **Potential-based reward shaping** (Ng et al., 1999)
   - Soru: "500m sonra durak var" bilgisini reward'a eklemek öğrenmeyi hızlandırır mı?

4. **Deneysel çalışma**: `hyperparams.yaml`'daki ağırlıkları değiştirerek 5 farklı konfigürasyon dene:
   ```yaml
   # Deney A: Headway dominant
   headway_weight: 15.0, bunching_penalty: 3.0
   
   # Deney B: Bunching dominant  
   headway_weight: 5.0, bunching_penalty: 10.0
   
   # Deney C: Speed focused
   speed_bonus_weight: 5.0, headway_weight: 5.0
   
   # Deney D: Minimal reward (sadece headway)
   headway_weight: 10.0, diğerleri: 0
   
   # Deney E: Eşit ağırlık
   headway_weight: 5.0, bunching: 5.0, dwell: 5.0, speed: 5.0
   ```
   Her birini 500 iterasyon çalıştırıp TensorBoard'da karşılaştır.

### Çıktı Beklentisi
- Hangi ağırlık kombinasyonu en hızlı converge ediyor?
- Reward bileşenlerinin birbiriyle çeliştiği durumlar var mı?
- En az 2 akademik makale referansıyla karşılaştırmalı analiz

---

## GÖREV 2: Gözlem Uzayı (Observation Space) Araştırması

**Dosya:** `rl_env/gpu_env.py` → `_vectorized_obs()` metodu (satır ~700-750)

### Mevcut Durum
Her araç 24 boyutlu gözlem alıyor (hız, mesafe, faz, headway, kuyruk, vb.)

### Araştırma Soruları

1. **Feature importance**: 24 boyutun hepsi gerçekten gerekli mi?
   - Araştır: Eğitilmiş model üzerinde **feature ablation study** nasıl yapılır
   - Her bir gözlem boyutunu sıfırlayarak (mask) reward'a etkisini ölç
   - Hangi boyutlar çıkarılınca performans düşüyor?

2. **Eksik bilgiler**: Hangi bilgiler gözlemde yok ama olması faydalı olur?
   - Araştır: **Yolcu yoğunluk bilgisi** (duraktaki bekleyen yolcu sayısı)
   - Araştır: **Trafik tahmini** (sonraki 5dk'nın trafik tahmini)
   - Araştır: **İletişim/mesajlaşma** — ajanlar arası bilgi paylaşımı (CommNet, TarMAC)

3. **Temporal bilgi**: Şu an tek bir anlık snapshot veriyoruz. Geçmiş bilgi faydalı olur mu?
   - Araştır: **Frame stacking** — son 3-5 step'in gözlemini birleştirme
   - Araştır: **LSTM/GRU tabanlı actor** — sıralı bilgiyi öğrenme
   - Makale: Hausknecht & Stone (2015) - "Deep Recurrent Q-Learning for POMDPs"

4. **Normalizasyon**: Gözlemler [0,1]'e normalize ediliyor. Farklı yöntemler daha iyi olabilir mi?
   - Araştır: **Running mean/std normalization** (observations'ı eğitim boyunca normalize et)
   - Araştır: **Observation clipping** vs **scaling** etkileri

### Deneysel Çalışma
```python
# Öneri: 3 deney tasarla
# A. Minimal obs (sadece hız + gap + faz = 6 boyut)
# B. Mevcut obs (24 boyut)  
# C. Genişletilmiş obs (24 + son 3 step geçmişi = 72 boyut)
# Her birini 500 iter çalıştır, karşılaştır
```

### Çıktı Beklentisi
- Feature importance sıralaması (en önemliden en azına)
- Eklenmesi önerilen yeni gözlem boyutları ve gerekçeleri
- En az 2 akademik makale referansı

---

## GÖREV 3: Ağ Mimarisi Araştırması

**Dosyalar:** `rl_env/agents/actor.py`, `rl_env/agents/critic.py`

### Mevcut Durum
```
Actor:  Linear(24→64) → ReLU → Linear(64→64) → ReLU → Linear(64→4)   [5,828 param]
Critic: Linear(4800→128) → ReLU → Linear(128→128) → ReLU → Linear(128→1) [631K param]
```

### Araştırma Soruları

1. **Daha derin ağlar**: 2 katman yeterli mi? 3-4 katmana çıkmak performansı artırır mı?
   - Araştır: RL'de ağ derinliği ve genişliğinin convergence'a etkisi
   - Makale: Andrychowicz et al. (2020) - "What Matters In On-Policy Reinforcement Learning?"
   - Bu makale PPO için sistematik ablation yapmış — çok faydalı

2. **Attention mekanizması**: Actor'da self-attention kullanmak ajanlar arası ilişkileri öğrenir mi?
   - Araştır: **Multi-Head Attention** ile komşu araçlara dikkat
   - Araştır: **Graph Neural Network (GNN)** — araçlar arası ilişkiyi graf olarak modelleme
   - Makale: Jiang & Lu (2018) - "Learning Attentional Communication for Multi-Agent Cooperation"

3. **Critic mimarisi**: Merkezi critic tüm ajanların obs'unu concat ediyor (4800 dim). Daha iyi yollar var mı?
   - Araştır: **Attention-based critic** — her ajana farklı ağırlık ver
   - Araştır: **Mean-field approximation** — tüm ajanların ortalamasını al (daha ölçeklenebilir)
   - Makale: Yang et al. (2018) - "Mean Field Multi-Agent Reinforcement Learning"

4. **Parameter sharing vs bağımsız ağlar**: Tüm ajanlar aynı ağı paylaşıyor. Bu her zaman en iyisi mi?
   - Araştır: Ajanları gruplara ayırmak (örn: hat başı / hat sonu) ve grup bazlı ağ
   - Araştır: **Agent ID embedding** — ajan kimliğini gözleme ekle

### Deneysel Çalışma
```
A. Mevcut (2×64 actor, 2×128 critic)
B. Daha geniş (2×128 actor, 2×256 critic)  
C. Daha derin (3×64 actor, 3×128 critic)
D. Agent ID ekle (obs boyutu 24→25, one-hot agent index)
```

### Çıktı Beklentisi
- Mimariler arası convergence hızı ve final reward karşılaştırması
- Parametre sayısı vs performans analizi
- Öneri: Proje için en uygun mimari hangisi ve neden

---

## GÖREV 4: Simülasyon Gerçekçiliği Araştırması

**Dosyalar:** `rl_env/gpu_env.py`, `rl_env/physics.py`, `rl_env/station_fsm.py`

### Mevcut Durum
Simülasyonumuz IDM fizik modeli, 8-fazlı durak FSM ve sabit dwell süresi kullanıyor.

### Araştırma Soruları

1. **Dwell süresi modeli**: Şu an `Uniform(15, 35)` saniye. Gerçekte dwell süresi neye bağlıdır?
   - Araştır: `τ = α + β₁·boarding + β₂·alighting + β₃·standees` (Dueker et al., 2004)
   - Araştır: İETT açık veri setinde gerçek dwell süreleri var mı?
   - Platform uzunluğu, kapı sayısı, yolcu yoğunluğu nasıl etkiler?

2. **Yolcu talep modeli**: Şu an talep uniform/rastgele. Gerçekçi alternatifler?
   - Araştır: İstanbulKart verisi — durak bazlı yolcu sayıları
   - Araştır: **Poisson process** ile yolcu geliş modeli
   - Araştır: **OD matrisi** (Origin-Destination) — nereden nereye gidiliyor?

3. **Trafik etkisi**: Metrobüs ayrı şeritte ama bazı noktalarda trafik etkisi var mı?
   - Araştır: Haramidere, Avcılar kavşakları — Google Maps trafik verisi
   - Araştır: İBB trafik yoğunluk API'si — segment bazlı hız verisi

4. **Hava durumu etkisi**: Yağmurda dwell süreleri artar, hızlar düşer
   - Araştır: OpenWeatherMap API ile geçmiş hava verisi → dwell/hız korelasyonu

5. **Sim-to-Real gap**: Simülasyondan gerçeğe geçişte ne tür farklar olur?
   - Araştır: **Domain Randomization** — parametreleri rastgeleleştirerek robustness artırma
   - Makale: Tobin et al. (2017) - "Domain Randomization for Transferring Deep Neural Networks"

### Deneysel Çalışma
```
1. İETT/İBB açık veri portalını araştır (data.ibb.gov.tr)
2. Gerçek dwell süreleri bulabilirsen, simülasyondaki dağılımla karşılaştır
3. En az bir parametreyi gerçek veriye dayalı olarak güncelle
```

### Çıktı Beklentisi
- Simülasyonun gerçeklikten sapma noktalarının listesi
- Her sapma için "ne kadar önemli" derecelendirmesi (düşük/orta/yüksek)
- En az 1 parametreyi gerçek veriye dayandırma önerisi

---

## GÖREV 5: Deployment ve Sistem Mühendisliği Araştırması

### Mevcut Durum
Model eğitilince `exports/metrobus_mappo_actor.onnx` (23KB) dosyası çıkıyor. Bu modeli gerçek dünyada nasıl çalıştırırız?

### Araştırma Soruları

1. **ONNX Runtime**: Eğitilmiş modeli browser'da nasıl çalıştırırız?
   - Araştır: `onnxruntime-web` kütüphanesi — WebAssembly ile browser'da inference
   - Dene: Model dosyasını yükle, 24 boyutlu input ver, 4 aksiyonlu output al
   - Latency ne kadar? 200 araç için kaç ms?

2. **Edge deployment**: Model araç-içi tablette çalışabilir mi?
   - Araştır: `onnxruntime-react-native` veya `onnxruntime-android`
   - Model boyutu 23KB — bu bir avantaj mı dezavantaj mı?
   - Offline çalışabilir mi (internet olmadan)?

3. **Veri pipeline**: Gerçek GPS verisi nereden gelir ve nasıl işlenir?
   - Araştır: İETT'nin mevcut araç takip sistemi (AVL — Automatic Vehicle Location)
   - Araştır: GTFS-Realtime standardı — transit verisi için açık format
   - Nasıl bir veri akışı gerekir: GPS → ? → AI → ? → Şoför Ekranı

4. **Konteynerizasyon**: Sistemi Docker ile nasıl paketleriz?
   - Araştır: Docker multi-stage build
   - Dashboard + AI inference ayrı container'lar mı olmalı?
   - `docker-compose` ile lokal geliştirme ortamı nasıl kurulur?

5. **CI/CD**: Kod değişikliği yapınca otomatik test ve deploy nasıl olur?
   - Araştır: GitHub Actions ile basit bir pipeline
   - Minimum: lint → test → docker build → push

### Deneysel Çalışma
```
1. onnxruntime-web ile browser'da model inference dene
2. docker-compose.yml yaz: dashboard + redis + ai-inference
3. Basit bir GitHub Actions workflow oluştur
```

### Çıktı Beklentisi
- ONNX browser inference latency ölçümü (200 araç batch)
- Çalışan bir docker-compose.yml
- Deployment mimarisi şeması (hangi bileşen nerede çalışır)

---

## GÖREV 6: Karşılaştırmalı Algoritma Araştırması

### Mevcut Durum
MAPPO kullanıyoruz. Alternatif algoritmalar ne kadar iyi/kötü?

### Araştırma Soruları

1. **Basit baseline'lar**: AI olmadan sadece kuralla kontrol etsek ne olur?
   - Uygula: Basit "headway < 2dk ise yavaşla" kuralı
   - Simülasyonu 36,000 step çalıştır, bunching say
   - Bu baseline'ı AI ile karşılaştır

2. **Alternatif RL algoritmaları**: MAPPO yerine başka ne kullanılabilir?
   - Araştır: **QMIX** — value decomposition, monotonicity kısıtlaması
   - Araştır: **MADDPG** — sürekli aksiyon uzayı, actor-critic
   - Araştır: **Independent PPO (IPPO)** — merkezi critic OLMADAN
   - Makale: Yu et al. (2022) - "The Surprising Effectiveness of PPO" — karşılaştırma tabloları

3. **IPPO vs MAPPO**: Merkezi critic'in etkisi ne kadar?
   - Dene: `agents/critic.py`'de critic input'unu sadece kendi obs'u yap (24 dim, 4800 değil)
   - 500 iter çalıştır, MAPPO ile karşılaştır
   - Merkezi bilgi ne kadar fark yaratıyor?

4. **Klasik optimizasyon**: RL yerine lineer programlama veya MPC kullansak?
   - Araştır: **Model Predictive Control (MPC)** — 30s ileriye optimum hız hesapla
   - Araştır: RL vs MPC karşılaştırması transit sistemlerde
   - RL'nin avantajı: Öğrenme. Dezavantajı: Eğitim süresi. MPC'nin avantajı: Garanti. Dezavantajı: Model doğruluğu.

### Deneysel Çalışma
```
En az 3 yaklaşımı aynı senaryoda çalıştır:
1. Kontrol yok (baseline)
2. Kural tabanlı (if/else headway control)  
3. MAPPO (mevcut)
4. (Bonus) IPPO (merkezi critic olmadan)

Karşılaştırma metrikleri:
- Bunching çifti sayısı
- Headway CV
- Ortalama hız
- Convergence süresi (RL için)
```

### Çıktı Beklentisi
- 4 yaklaşımın karşılaştırma tablosu
- Her yaklaşımın güçlü/zayıf yönleri
- "Bu problem için MAPPO neden uygun?" sorusuna kanıtlı cevap

---

## 📅 Zaman Planı Önerisi

```
Hafta 1-2:  Görevinizle ilgili dosyaları okuyun, kodu anlayın
            Literatür taraması yapın (Google Scholar, 3-5 makale)

Hafta 3-4:  Deneysel çalışma tasarlayın
            Deneyleri çalıştırın (her deney ~1-2 saat eğitim)

Hafta 5:    Sonuçları TensorBoard'dan toplayın
            Karşılaştırma tabloları ve grafikleri hazırlayın

Hafta 6:    Bulgularını 10 dakikalık sunum olarak hazırla
            Makale bölümüne katkını yaz (docs/paper/ altında)
```

---

## 🔧 Deneylerini Çalıştırma Rehberi

```bash
# 1. Parametreleri değiştir
#    rl_env/config/hyperparams.yaml dosyasını düzenle

# 2. Eğitimi başlat
cd rl_env
python train.py
#    → TensorBoard logları: rl_env/logs/ altında

# 3. Grafikleri izle
python -m tensorboard.main --logdir logs --port 6006
#    → Tarayıcıda: http://localhost:6006

# 4. Dashboard'da canlı izle
cd .. && npm run dev:dashboard
#    → Tarayıcıda: http://localhost:3001
#    → "🧠 Eğitim İzle" butonuna bas

# 5. Farklı deneyleri karşılaştırmak için
#    logs/ klasörüne farklı isimlerle kaydet:
#    hyperparams.yaml → log_dir: "logs/deney_A"
```

---

> **Herkes kendi görevini bağımsız yürütebilir.** Sonuçları birleştirince makale bölümlerimiz hazır olacak. Sorunuz olursa WhatsApp grubuna yazın.
