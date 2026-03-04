# Metrobüs ML Tahmin Servisi

Makine öğrenmesi ile yolcu talebi, seyahat süresi ve tıkanıklık tahmini.

## Kurulum

```bash
cd packages/ml-service
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Modeller

### 1. Talep Tahmini (`demand-predictor.py`)
- Saat/gün/mevsime göre durak bazlı yolcu tahmini
- Prophet veya ARIMA zaman serisi modeli

### 2. Seyahat Süresi Tahmini (`travel-time-predictor.py`)
- İki durak arası seyahat süresi tahmini
- Gradient Boosting (XGBoost/LightGBM)

### 3. Tıkanıklık Tahmini (`congestion-predictor.py`)
- 15 dakika sonrası tıkanıklık tahmini
- LSTM veya Transformer tabanlı model

## API

```bash
uvicorn serving.prediction_api:app --host 0.0.0.0 --port 8000
```
