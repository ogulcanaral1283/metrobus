"""Quick: fetch IETT hat guzergahlari GeoJSON and GTFS package info."""
import requests
import json
import os

out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(out_dir, exist_ok=True)

# 1. İETT Hat Güzergahları (GeoJSON)
print("=== İETT Hat Güzergahları ===")
r = requests.get("https://data.ibb.gov.tr/api/3/action/package_show?id=iett-hat-guzergahlari", timeout=15)
pkg = r.json()["result"]
print(f"Title: {pkg['title']}")
print(f"Notes: {pkg.get('notes', '')[:200]}")
for res in pkg["resources"]:
    print(f"  {res['name']} ({res['format']}) -> {res['url']}")

# Download GeoJSON if available
for res in pkg["resources"]:
    if res["format"].upper() in ("GEOJSON", "JSON"):
        print(f"\n  Downloading {res['name']}...")
        r2 = requests.get(res["url"], timeout=60)
        if r2.status_code == 200:
            try:
                geojson = r2.json()
                path = os.path.join(out_dir, "iett_hat_guzergahlari.geojson")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(geojson, f, ensure_ascii=False)
                print(f"  Saved: {path}")
                if "features" in geojson:
                    print(f"  Total features: {len(geojson['features'])}")
                    # Find metrobus features
                    for feat in geojson["features"]:
                        props = feat.get("properties", {})
                        name = str(props.get("HAT_KODU", "")) + " " + str(props.get("SHAT_KODU", "")) + " " + str(props.get("name", ""))
                        if "34G" in name or "34g" in name or "metrobüs" in name.lower() or "metrobus" in name.lower():
                            print(f"  🚍 METROBUS: {json.dumps(props, ensure_ascii=False)[:300]}")
                    # Show all unique hat kodlari that start with 34
                    hat_kodlari = set()
                    for feat in geojson["features"]:
                        props = feat.get("properties", {})
                        for key in props:
                            val = str(props[key])
                            if val.startswith("34") and len(val) <= 5:
                                hat_kodlari.add(val)
                    if hat_kodlari:
                        print(f"  Hat kodları starting with 34: {sorted(hat_kodlari)}")
                    # Show first feature's properties 
                    print(f"\n  Sample feature properties: {list(geojson['features'][0].get('properties', {}).keys())}")
                    print(f"  Sample: {json.dumps(geojson['features'][0]['properties'], ensure_ascii=False)[:300]}")
                    geom = geojson['features'][0].get('geometry', {})
                    print(f"  Geometry type: {geom.get('type', 'N/A')}")
                    if geom.get("coordinates"):
                        coords = geom["coordinates"]
                        if isinstance(coords[0], list) and isinstance(coords[0][0], (int,float)):
                            print(f"  Coordinates: {len(coords)} points")
                        elif isinstance(coords[0], list):
                            print(f"  Coordinates: {len(coords)} segments, first has {len(coords[0])} points")
            except Exception as e:
                print(f"  Parse error: {e}")
                print(f"  Raw: {r2.text[:500]}")
        else:
            print(f"  Download failed: {r2.status_code}")

# 2. IETT GTFS
print("\n\n=== İETT GTFS Verisi ===")
r = requests.get("https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi", timeout=15)
pkg = r.json()["result"]
print(f"Title: {pkg['title']}")
print(f"Notes: {pkg.get('notes', '')[:200]}")
for res in pkg["resources"]:
    print(f"  {res['name']} ({res['format']}) -> {res['url'][:120]}")
