"""
Metrobüs Tıkanıklık Tahmin Modeli

15 dakika sonrası durak bazlı tıkanıklık tahmini.
Feature'lar:
- Saat, gün, mevsim
- Mevcut tıkanıklık skoru
- Son 30dk trend
- Hava durumu
- Rush hour flag
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import joblib
from datetime import datetime
from pathlib import Path


class CongestionPredictor:
    """Durak bazlı tıkanıklık tahmin modeli"""

    def __init__(self):
        self.model = GradientBoostingRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42,
        )
        self.is_trained = False

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ham veriden feature extraction"""
        features = pd.DataFrame()
        
        features['hour'] = df['time'].dt.hour
        features['day_of_week'] = df['time'].dt.dayofweek
        features['is_weekend'] = (features['day_of_week'] >= 5).astype(int)
        features['is_morning_rush'] = ((features['hour'] >= 7) & (features['hour'] <= 9)).astype(int)
        features['is_evening_rush'] = ((features['hour'] >= 17) & (features['hour'] <= 19)).astype(int)
        features['month'] = df['time'].dt.month
        features['current_score'] = df['congestion_score']
        features['station_id'] = df['station_id']
        
        # Eğer varsa trend bilgisi
        if 'score_trend' in df.columns:
            features['score_trend'] = df['score_trend']
        
        return features

    def train(self, df: pd.DataFrame, target_col: str = 'target_score'):
        """Modeli eğit"""
        features = self.prepare_features(df)
        target = df[target_col]

        X_train, X_test, y_train, y_test = train_test_split(
            features, target, test_size=0.2, random_state=42
        )

        self.model.fit(X_train, y_train)
        self.is_trained = True

        # Değerlendirme
        y_pred = self.model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)

        print(f"Model eğitildi:")
        print(f"  MAE: {mae:.2f}")
        print(f"  R²:  {r2:.4f}")

        return {"mae": mae, "r2": r2}

    def predict(
        self,
        station_id: int,
        current_score: float,
        timestamp: datetime = None,
        score_trend: float = 0.0,
    ) -> dict:
        """15 dakika sonrası tıkanıklık tahmini"""
        if not self.is_trained:
            raise ValueError("Model henüz eğitilmedi")

        if timestamp is None:
            timestamp = datetime.now()

        features = pd.DataFrame([{
            'hour': timestamp.hour,
            'day_of_week': timestamp.weekday(),
            'is_weekend': 1 if timestamp.weekday() >= 5 else 0,
            'is_morning_rush': 1 if 7 <= timestamp.hour <= 9 else 0,
            'is_evening_rush': 1 if 17 <= timestamp.hour <= 19 else 0,
            'month': timestamp.month,
            'current_score': current_score,
            'station_id': station_id,
            'score_trend': score_trend,
        }])

        predicted_score = float(self.model.predict(features)[0])
        predicted_score = max(0, min(100, predicted_score))

        return {
            "station_id": station_id,
            "current_score": current_score,
            "predicted_score": round(predicted_score, 1),
            "prediction_horizon_min": 15,
            "timestamp": timestamp.isoformat(),
        }

    def save(self, path: str = "congestion_model.pkl"):
        """Modeli kaydet"""
        joblib.dump(self.model, path)
        print(f"Model kaydedildi: {path}")

    def load(self, path: str = "congestion_model.pkl"):
        """Modeli yükle"""
        self.model = joblib.load(path)
        self.is_trained = True
        print(f"Model yüklendi: {path}")


if __name__ == "__main__":
    print("Tıkanıklık Tahmin Modeli")
    print("Eğitim verisi gerekli. 'train()' metodunu kullanın.")
