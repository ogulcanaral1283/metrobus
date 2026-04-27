# 7. DENEYSEL KURULUM VE SONUÇLAR (Experiments & Results)

## 7.1 Deneysel Kurulum

### 7.1.1 Donanım

| Bileşen | Özellik |
|---------|---------|
| GPU | NVIDIA GeForce RTX 5070 Ti (16 GB GDDR7, Ada Lovelace) |
| CPU | Intel/AMD (Python Predictive Engine için) |
| RAM | 32+ GB DDR5 |
| OS | Windows 11 |
| CUDA | 12.x |
| PyTorch | 2.5+ (CUDA 12 desteği) |

### 7.1.2 Rota Segmenti

**Beylikdüzü → Halıcıoğlu** — 31 durak, ~35 km

| # | Durak | Pozisyon (km) | Platform (m) | Slot |
|---|-------|-------------|-------------|------|
| 1 | Beylikdüzü Sondurak | 0.0 | 94 | 3 |
| 2 | Beykent | 1.2 | 128 | 5 |
| 3 | Cumhuriyet Mahallesi | 2.5 | 117 | 4 |
| 4 | Beylikdüzü Belediye | 3.6 | 132 | 5 |
| 5 | Beylikdüzü | 4.8 | 117 | 4 |
| 6 | Güzelyurt | 6.5 | 123 | 4 |
| 7 | Haramidere | 7.8 | 117 | 4 |
| 8 | Haramidere Sanayi | 9.5 | 151 | 6 |
| 9 | Saadetdere Mahallesi | 10.8 | 118 | 4 |
| 10 | Mustafa Kemalpaşa | 13.0 | 143 | 6 |
| 11 | Avcılar Merkez | 15.5 | 127 | 5 |
| 12 | Şükrübey | 16.6 | 135 | 5 |
| 13 | Büyükşehir Belediyesi | 18.5 | 84 | 3 |
| 14 | Küçükçekmece | 21.8 | 83 | 3 |
| 15 | Cennet Mahallesi | 23.4 | 131 | 5 |
| 16 | Florya | 24.2 | 86 | 3 |
| 17 | Beşyol | 25.0 | 115 | 4 |
| 18 | Sefaköy | 25.6 | 109 | 4 |
| 19 | 15 Temmuz Mahallesi | 27.0 | 232 | 9 |
| 20 | Yenibosna | 28.5 | 206 | 8 |
| 21 | Şirinevler | 30.0 | 125 | 5 |
| 22 | Bahçelievler | 31.5 | 104 | 4 |
| 23 | İncirli | 32.5 | 187 | 7 |
| 24 | Zeytinburnu | 34.0 | 117 | 4 |
| 25 | Merter | 34.8 | 118 | 4 |
| 26 | Cevizlibağ | 35.8 | 210 | 8 |
| 27 | Topkapı | 36.6 | 55 | 2 |
| 28 | Bayrampaşa | 37.2 | 99 | 4 |
| 29 | Edirnekapı | 38.5 | 112 | 4 |
| 30 | Ayvansaray | 39.6 | 121 | 5 |
| 31 | Halıcıoğlu | 41.0 | 121 | 5 |

### 7.1.3 Eğitim Hiperparametreleri

| Parametre | Değer | Gerekçe |
|-----------|-------|---------|
| Araç sayısı (N) | 200 | Gerçekçi yoğunluk (~6.5 araç/durak) |
| Paralel ortam (B) | 512 | GPU doyurma |
| Zaman adımı (dt) | 0.1 s | Hassas fizik simülasyonu |
| Episode uzunluğu | 36,000 step (1 saat) | Tam bir operasyon döngüsü |
| Öğrenme hızı | 3×10⁻⁴ | Standart PPO değeri |
| Discount (γ) | 0.99 | Uzun vadeli strateji |
| GAE-λ | 0.95 | Bias-variance dengesi |
| PPO clip (ε) | 0.2 | Standart PPO değeri |
| Epochs (K) | 10 | Veri verimliliği |
| Batch size | 32,768 | 512 × 64 step |
| Mini-batch | 4,096 | 8 gradient adımı/epoch |
| Entropy katsayısı | 0.01 | Keşif teşviki |
| Value katsayısı | 0.5 | Critic ağırlığı |
| Gradient norm | 0.5 | Gradient clipping |
| Toplam iterasyon | 3,000 | Convergence süresi |

### 7.1.4 Reward Ağırlıkları

| Bileşen | Ağırlık | Gerekçe |
|---------|---------|---------|
| Headway düzgünlüğü | 10.0 | Ana hedef — eşit aralık |
| Bunching cezası | 5.0 | Kritik kısıtlama — yapışma engelleme |
| Uzun bekleme | 0.5 | İkincil — durakta bekleme maliyeti |
| Hız bonusu | 2.0 | Teşvik — hedef hıza yakınlık |
| Hedef hız | 40 km/h | İBB operasyonel hedef |

## 7.2 Eğitim Sonuçları

### 7.2.1 Reward Evrimi

Eğitim boyunca reward metriklerinin evrimi (TensorBoard verileri):

| Aşama | İterasyon | Reward (mean) | Entropy | v_loss | Yorum |
|-------|-----------|---------------|---------|--------|-------|
| Kaos | 0-50 | -8 ~ -5 | 1.35 | >1000 | Rastgele aksiyonlar |
| Erken öğrenme | 50-200 | -5 ~ -2 | 1.25 | 50-100 | "Yavaşlamak bazen iyi" |
| İyileşme | 200-800 | -2 ~ +1 | 1.0-1.2 | 1-10 | Bunching azalmaya başlar |
| Stabilizasyon | 800-1500 | +1 ~ +3 | 0.6-0.8 | <1 | Politika olgunlaşır |
| Olgunluk | 1500-3000 | +3 ~ +5 | 0.3-0.5 | <0.5 | Optimal politika |

### 7.2.2 Beklenen Performans Karşılaştırması

| Metrik | Baseline (kontrol yok) | Holding stratejisi | **MAPPO (önerilen)** |
|--------|----------------------|-------------------|---------------------|
| Bunching oranı | %25-35 | %15-20 | **%3-8** |
| Headway CV | 1.5-2.0 | 0.8-1.0 | **0.2-0.4** |
| Ortalama yolcu bekleme | 8-12 dk | 5-7 dk | **3-5 dk** |
| Ortalama araç hızı | 25 km/h | 30 km/h | **36-40 km/h** |
| Enerji verimliliği | Baseline | +%5 | **+%10-15** |

### 7.2.3 Ablation Study Planı

| Deney | Değişiklik | Amaç |
|-------|-----------|------|
| A1 | MAPPO yalnız (PE yok) | Predictive Engine'in katkısı |
| A2 | PE yalnız (MAPPO yok) | RL'nin katkısı |
| A3 | IQL (bağımsız Q-learning) vs MAPPO | CTDE'nin avantajı |
| A4 | 80 vs 200 araç | Ölçeklenebilirlik |
| A5 | 10 vs 31 vs 44 durak | Rota uzunluğu etkisi |
| A6 | GPU vs CPU eğitim hızı | GPU hızlanma faktörü |

## 7.3 Model Export ve Deployment

### 7.3.1 ONNX Export

Eğitilmiş Actor ağı ONNX formatına dönüştürülür:

```python
torch.onnx.export(
    actor_model,
    dummy_input=torch.randn(1, 24),  # tek ajan gözlemi
    f="metrobus_mappo_actor.onnx",
    input_names=["observation"],
    output_names=["action_probabilities"],
    dynamic_axes={"observation": {0: "batch"}}
)
```

**Model boyutu**: ~23 KB (5,828 parametre × 4 byte)

### 7.3.2 Deployment Senaryoları

| Senaryo | Platform | Teknoloji | Gecikme |
|---------|----------|-----------|---------|
| Browser dashboard | Chrome/Firefox | onnxruntime-web | <5ms |
| Araç-içi HUD | Android tablet | onnxruntime-mobile | <3ms |
| Edge server | Raspberry Pi | onnxruntime-arm | <10ms |
| Bulut API | AWS/GCP | onnxruntime-gpu | <1ms |

### 7.3.3 Canlı Demo

```bash
python live_demo.py
```

Bu script eğitilmiş modeli yükler ve gerçek zamanlı simülasyonu dashboard üzerinde çalıştırır:
- Model kararlarını her step'te uygular
- Bunching, headway, hız metriklerini canlı gösterir
- Baseline (kontrol yok) ile A/B karşılaştırma yapılabilir
