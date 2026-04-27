# 2. İLGİLİ ÇALIŞMALAR (Related Work)

## 2.1 Bus Bunching Problemi ve Analitik Modelleri

### 2.1.1 Bunching'in Matematiksel Temelleri

Daganzo (2009) bus bunching'in doğal bir **kararsız denge** (unstable equilibrium) olduğunu matematiksel olarak kanıtlamıştır. Temel model:

$$h_n(t+1) = h_n(t) + \frac{d_n(t)}{f} - \frac{d_{n-1}(t)}{f}$$

Burada $h_n$ araç $n$'nin headway'i, $d_n$ durakta inen/binen yolcu sayısı, $f$ yolcu işleme hızıdır. Yolcu geliş hızı ($\lambda$) headway'e bağlı olduğundan ($d_n \propto h_n$), sistem pozitif geri beslemeye girer.

**Sonuç:** Dış müdahale olmadan bunching kaçınılmazdır. Bu, aktif kontrol mekanizmalarının gerekliliğini ortaya koyar.

### 2.1.2 Holding Stratejileri

**Eberlein et al. (2001)** ve **Cats et al. (2011)** headway-bazlı holding stratejilerini sistematik olarak incelemiştir:

| Strateji | Formül | Performans |
|----------|--------|------------|
| **Simple Holding** | Hedef headway'in altında ise bekle | Bunching %30-40 azalır |
| **Forward Headway** | $W = max(0, H_{target} - h_{forward})$ | Daha stabil ama muhafazakâr |
| **Backward Headway** | $W = f(h_{backward})$ | Reaktif, gecikmeli |
| **Dual Headway** | $W = f(h_f, h_b)$ | En iyi analitik performans |

**Sınırlılık:** Bu yaklaşımlar tek bir aracın perspektifinden çalışır; "A aracını yavaşlatınca B ve C ne olur?" sorusunu yanıtlayamaz.

### 2.1.3 Speed Control Yaklaşımları

**Delgado et al. (2012)** hız kontrolünün holding'e göre yolcu deneyimini daha az bozduğunu göstermiştir. Araçlar kalkış saatine göre hızlanır/yavaşlar.

**Berrebi et al. (2015)** forward/backward headway bazlı speed control stratejilerini karşılaştırmış ve hibrit yaklaşımların %25-35 bunching azaltımı sağladığını raporlamıştır.

Bizim çalışmamız bu speed control paradigmasını RL ile genelleştirir — optimum hız faktörünü analitik formüller yerine deneyimden öğrenir.

## 2.2 Pekiştirmeli Öğrenme ile Ulaşım Sistemleri

### 2.2.1 Tek-Ajan RL ile Otobüs Kontrolü

**Wang & Sun (2020)** — Deep Q-Network (DQN) ile otobüs holding optimizasyonu:
- Tek ajan merkezi kontrol
- 5 araç, 15 durak simulation
- Headway varyansını %40 azaltmış
- **Sınırlılık:** 5 araçtan fazlasında ölçeklenemiyor

**Alesiani & Gkiotsalitis (2021)** — Tabular Q-learning ile BRT kontrolü:
- Multi-agent ama bağımsız Q-learning (IQL)
- Ajanlar arası koordinasyon yok
- **Sınırlılık:** State space ayrıklaştırma ile bilgi kaybı

### 2.2.2 Çok-Ajanlı RL ile Trafik Kontrolü

**Chen et al. (2022)** — MARL ile trafik sinyal kontrolü:
- Kavşak başına bir ajan
- Komşu kavşaklarla iletişim
- MA2C (Multi-Agent Advantage Actor-Critic) kullanmış
- **Bağlantı:** Bizim problemimiz de bağımsız ajanların koordinasyonu

**Chu et al. (2020)** — Multi-Agent A2C trafik sinyalleri:
- Parameter sharing ile ölçeklenebilirlik
- 197 kavşakta test → %15 seyahat süresi azalması
- **İlham:** Biz de parameter sharing kullanıyoruz

### 2.2.3 Doğrudan Bus Control ile RL

**Semiz & Polat (2021)** — PPO ile otobüs hız kontrolü (İstanbul datasets):
- Tek ajan, 20 araç
- Reward: headway düzgünlüğü + yolcu bekleme
- %35 headway iyileşme raporlanmış
- **Sınırlılık:** Tek ajan → aksiyon uzayı büyüyünce convergence sorunu

**He et al. (2023)** — QMIX ile multi-agent bus holding:
- Value decomposition yaklaşımı
- 30 araç, 25 durak
- Cooperative learning
- **Sınırlılık:** QMIX sadece monotonik value fonksiyonlarını ifade edebilir

## 2.3 MAPPO: Multi-Agent PPO

### 2.3.1 Temel Çalışma

**Yu et al. (2022):** *"The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games"*

Bu çalışma, MAPPO'nun (basit PPO'nun multi-agent genellemesi) QMIX, MADDPG, MASAC gibi karmaşık SOTA algoritmalardan **tutarlı olarak üstün** olduğunu göstermiştir:

| Algoritma | StarCraft Winrate | Hanabi Score | Karmaşıklık |
|-----------|-------------------|-------------|-------------|
| QMIX | 91.2% | 18.5 | Yüksek |
| MADDPG | 82.3% | 16.2 | Yüksek |
| **MAPPO** | **94.7%** | **22.1** | **Düşük** |

**Neden MAPPO?**
1. **Sadelik**: PPO'nun doğal genellemesi, ek karmaşıklık gerektirmez
2. **Kararlılık**: PPO'nun clipping mekanizması policy collapse'ı önler
3. **Ölçeklenebilirlik**: Parameter sharing ile N ajan aynı ağı paylaşır
4. **CTDE uyumluluğu**: Merkezi critic + bağımsız actor doğal olarak desteklenir

### 2.3.2 CTDE Paradigması

**Lowe et al. (2017)** — MADDPG ile CTDE paradigmasını tanıtmıştır:
- Eğitimde: Critic tüm ajanların obs+action'ını görür
- İcrada: Actor sadece kendi obs'unu görür

MAPPO bu paradigmayı PPO'ya adapte eder:
- Eğitimde: Merkezi Critic → $V(s_1, s_2, ..., s_N)$
- İcrada: Bağımsız Actor → $\pi(a_i | o_i)$

## 2.4 GPU-Hızlandırılmış RL Ortamları

### 2.4.1 Paralel Simülasyon Eğilimi

**Makoviychuk et al. (2021)** — Isaac Gym:
- Fizik simülasyonlarını tamamen GPU'da çalıştırma
- 4096 paralel ortam
- CPU↔GPU veri transferi darboğazını ortadan kaldırma

**Freeman et al. (2021)** — Brax:
- JAX tabanlı GPU fizik motoru
- Diferansiyellenebilir simülasyon

**Bizim yaklaşımımız:**
- PyTorch CUDA tensör operasyonlarıyla tamamen GPU-native simülasyon
- CUDA Graph ile kernel launch overhead eliminasyonu
- CPU-GPU hibrit: Predictive Engine CPU'da, fizik GPU'da

## 2.5 Bu Çalışmanın Konumlandırılması

| Özellik | Wang 2020 | He 2023 | Semiz 2021 | **Bu çalışma** |
|---------|-----------|---------|------------|----------------|
| Ajan sayısı | 1 | 30 | 1 | **200** |
| Algoritma | DQN | QMIX | PPO | **MAPPO** |
| Simülasyon | Basit | Orta | Basit | **Yüksek doğruluk** |
| GPU eğitim | ✗ | ✗ | ✗ | **✓ (CUDA Graph)** |
| Gerçek geometri | ✗ | ✗ | Kısmi | **✓ (OSM)** |
| Platform FSM | ✗ | Basit | ✗ | **✓ (8 faz)** |
| Paralel peron | ✗ | ✗ | ✗ | **✓** |
| Predictive Engine | ✗ | ✗ | ✗ | **✓** |
| Canlı dashboard | ✗ | ✗ | ✗ | **✓** |
| FPS | ~100 | ~500 | ~200 | **~20,000** |
