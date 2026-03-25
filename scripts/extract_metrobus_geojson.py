"""Extract metrobus 34G route geometry from IETT GeoJSON."""
import json
import os

geojson_path = os.path.join(os.path.dirname(__file__), "..", "data", "iett_hat_guzergahlari.geojson")
with open(geojson_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total features: {len(data['features'])}")

# Find all unique HAT_KODU values
all_hat = set()
for feat in data["features"]:
    props = feat.get("properties", {})
    hat = props.get("HAT_KODU", "")
    all_hat.add(hat)

# Find hat kodlari that contain "34" (but not "134", "234", etc.)
metrobus_hats = sorted([h for h in all_hat if h.startswith("34")])
print(f"\nHat kodları starting with '34': {metrobus_hats}")

# Also check for METROBÜS in names
for feat in data["features"]:
    props = feat.get("properties", {})
    hat = props.get("HAT_KODU", "")
    hat_adi = props.get("HAT_ADI", "")
    guz_adi = props.get("GUZERGAH_ADI", "")
    if hat in metrobus_hats:
        geom = feat.get("geometry", {})
        coord_count = 0
        if geom.get("coordinates"):
            coords = geom["coordinates"]
            if isinstance(coords[0], list) and isinstance(coords[0][0], (int, float)):
                coord_count = len(coords)
            elif isinstance(coords[0], list):
                coord_count = sum(len(seg) for seg in coords)

        yon = props.get("YON", "?")
        uzunluk = props.get("UZUNLUK", "?")
        guz_kodu = props.get("GUZERGAH_KODU", "?")
        print(f"\n  HAT: {hat} | YÖN: {yon} | Güzergah: {guz_kodu}")
        print(f"  Ad: {hat_adi}")
        print(f"  Güzergah Adı: {guz_adi}")
        print(f"  Uzunluk: {uzunluk}m | Koordinat: {coord_count} nokta")
        print(f"  Geometry type: {geom.get('type', '?')}")
        if coord_count > 0:
            coords = geom["coordinates"]
            if isinstance(coords[0], list) and isinstance(coords[0][0], (int, float)):
                print(f"  First coord: {coords[0]}")
                print(f"  Last coord: {coords[-1]}")
            elif isinstance(coords[0], list):
                print(f"  First coord: {coords[0][0]}")
                print(f"  Last coord: {coords[-1][-1]}")

# Save metrobus features separately
metrobus_features = [f for f in data["features"] if f.get("properties", {}).get("HAT_KODU", "") in metrobus_hats]
if metrobus_features:
    out = {"type": "FeatureCollection", "features": metrobus_features}
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "metrobus_routes.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\n💾 Saved {len(metrobus_features)} metrobus features to {out_path}")
else:
    print("\n❌ No metrobus features found!")
    # Look for similar patterns
    print("\nSearching for METROBÜS in HAT_ADI...")
    for feat in data["features"]:
        props = feat.get("properties", {})
        hat_adi = str(props.get("HAT_ADI", "")).upper()
        if "METROBÜS" in hat_adi or "METROBUS" in hat_adi or "BRT" in hat_adi:
            print(f"  Found: {props.get('HAT_KODU')} - {props.get('HAT_ADI')}")
