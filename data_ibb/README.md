# İBB Açık Veri — Metrobüs Talep Hattı

Kaynak: [İBB Açık Veri Portalı — Saatlik Toplu Ulaşım Veri Seti (BELBİM)](https://data.ibb.gov.tr/dataset/hourly-public-transport-data-set)

| Dosya | Açıklama |
|---|---|
| `metrobus_202410.csv` | Ham aylık dosyadan süzülmüş metrobüs kayıtları (Ekim 2024) |
| `metrobus_station_hourly_202410.csv` | Durak × saat matrisi — hafta içi ort. yolcu/saat |
| `metrobus_yogunluk_ekim2024.png` | Durak-saat yoğunluk ısı haritası |
| `export_demand.py` | Matrisi rota sırasına çevirip `rl_env/data/station_demand_hourly.csv` üretir |
| `make_viz.py` | Isı haritasını üretir |
| `make_segment_fig.py`, `make_slide_charts.py` | Rapor/sunum grafikleri (girdi: `results/segment_*.csv`) |

Ham aylık dosya (`hourly_transportation_202410.csv`, ~262 MB) depo boyutu
için silindi; portaldan yeniden indirilebilir (CKAN API:
`package_show?id=hourly-public-transport-data-set`). Metrobüs kayıtları
`station_poi_desc_cd` alanı üzerinden durak bazında gelir (istasyonlar
turnikeli olduğu için).
