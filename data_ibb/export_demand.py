# -*- coding: utf-8 -*-
"""
İBB durak-saat matrisini sim rota sırasına çevirip rl_env/data/'ya yazar.

Girdi : data_ibb/metrobus_station_hourly_202410.csv  (İBB durak adları)
Çıktı : rl_env/data/station_demand_hourly.csv
        kolonlar: stop_index, stop_name, h00..h23  (hafta içi ort. yolcu/saat)

Not: Turnike girişleri iki yönün toplamıdır; sim tek yön koştuğu için bu
değerler mutlak talep değil, durak AĞIRLIĞI olarak kullanılır (skip-stop
kararında düşük/yüksek talep ayrımı). make_viz.py ile aynı eşleme mantığı.
"""
import re, sys, unicodedata
import pandas as pd

sys.path.insert(0, ".")
from rl_env.route_data import load_route


def norm(s: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = str(s).translate(tr)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


MANUAL = {
    "AVCILARMRKUNVKAMP": "AvcilarMerkezUniversiteKampusu",
    "IBBSOSYALTESISLER": "BuyuksehirBelediyesiSosyalTesisleri",
    "OKMEYDANIHASTANE": "OkmeydaniHastaneMetrobusduragi",
    "TOPKAPI": "TopkapiSehitMustafaCambaz",
    "BAYRAMPASAMALTEPE": "BayrampasaMaltepeKocUniversitesiHastanesi",
    "BOGAZKOPRUSU": "15TemmuzSehitlerKoprusu",
    "CIHANGIRUNIVERSITEMAH": "CihangirUnivmah",
    "HARAMIDERESANAYISITESI": "HaramidereSanayi",
    "AYVANSARAY": "AyvansarayEyupsultan",
    "BEYLIKDUZUBELEDIYESI": "BeylikduzuBelediye",
    "DARULACEZEPERPA": "DarulacezePerpa",
}
MANUAL = {k: norm(v) for k, v in MANUAL.items()}

pivot = pd.read_csv("data_ibb/metrobus_station_hourly_202410.csv", index_col=0)
pivot.columns = [int(c) for c in pivot.columns]
pivot = pivot.reindex(columns=range(24), fill_value=0)

stops = load_route().stops
route_norm = {norm(s.name): s for s in stops}

by_route = {}
for st in pivot.index:
    key = MANUAL.get(norm(st), norm(st))
    hit = key if key in route_norm else None
    if hit is None:
        for rn in sorted(route_norm, key=len, reverse=True):
            if key and (rn.startswith(key) or key.startswith(rn)):
                hit = rn
                break
    if hit is None:
        print("ESLESMEDI:", st)
        continue
    by_route[hit] = pivot.loc[st].values

rows = []
for s in stops:
    vals = by_route.get(norm(s.name))
    if vals is None:
        print("VERISIZ DURAK (koridor ortalamasi yazilacak):", s.name)
        vals = pivot.mean(axis=0).values
    rows.append([s.index, s.name] + [round(float(v), 1) for v in vals])

out = pd.DataFrame(rows, columns=["stop_index", "stop_name"]
                   + [f"h{h:02d}" for h in range(24)])
out.to_csv("rl_env/data/station_demand_hourly.csv", index=False)
print(f"OK: rl_env/data/station_demand_hourly.csv  ({len(out)} durak)")
