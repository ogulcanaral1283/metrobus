"""
Focused test: Extract metrobus data from WORKING IETT endpoints.
Auth method: SOAP 1.1 + apikey query param
"""
import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import os

API_KEY = "4f36be25-be2e-45be-add0-76ddcafe97ae"
BASE = "https://api.ibb.gov.tr/iett"

SOAP11 = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body>{body}</soap:Body>'
    '</soap:Envelope>'
)


def soap_call(url, body, action):
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": action
    }
    r = requests.post(
        f"{url}?apikey={API_KEY}",
        data=SOAP11.format(body=body).encode("utf-8"),
        headers=headers, timeout=60
    )
    return r.status_code, r.text


def extract_json(xml_text, result_tag):
    try:
        root = ET.fromstring(xml_text)
        for e in root.iter():
            tag = e.tag.split("}")[-1] if "}" in e.tag else e.tag
            if tag == result_tag and e.text:
                return json.loads(e.text)
    except Exception:
        pass
    return None


def extract_tables(xml_text):
    tables = []
    try:
        root = ET.fromstring(xml_text)
        for e in root.iter():
            tag = e.tag.split("}")[-1] if "}" in e.tag else e.tag
            if tag == "Table":
                row = {}
                for child in e:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    row[ctag] = child.text
                tables.append(row)
    except Exception:
        pass
    return tables


def save_json(data, filename):
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  💾 Saved to {path}")
    return path


print("=" * 60)
print(f"  IETT Metrobus Data Extraction")
print(f"  Time: {datetime.now().isoformat()}")
print("=" * 60)

# ─── 1. DurakDetay_GYY for 34G (Stop details with live vehicle times) ───
print("\n📍 1. DurakDetay_GYY for 34G")
s, t = soap_call(
    f"{BASE}/ibb/ibb.asmx",
    '<DurakDetay_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></DurakDetay_GYY>',
    "http://tempuri.org/DurakDetay_GYY"
)
print(f"  Status: {s}")
tables = extract_tables(t)
if tables:
    print(f"  Found {len(tables)} stops")
    print(f"  Fields: {list(tables[0].keys())}")
    for row in tables[:5]:
        print(f"  {json.dumps(row, ensure_ascii=False)}")
    if len(tables) > 5:
        print(f"  ... +{len(tables)-5} more")
    save_json(tables, "metrobus_34G_stops.json")
else:
    print(f"  No data. Response: {t[:300]}")

# ─── 2. HatServisi_GYY for 34G (Schedule/service info) ───
print("\n🚍 2. HatServisi_GYY for 34G")
s, t = soap_call(
    f"{BASE}/ibb/ibb.asmx",
    '<HatServisi_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></HatServisi_GYY>',
    "http://tempuri.org/HatServisi_GYY"
)
print(f"  Status: {s}")
tables = extract_tables(t)
if tables:
    print(f"  Found {len(tables)} service entries")
    print(f"  Fields: {list(tables[0].keys())}")
    for row in tables[:5]:
        print(f"  {json.dumps(row, ensure_ascii=False)}")
    if len(tables) > 5:
        print(f"  ... +{len(tables)-5} more")
    save_json(tables, "metrobus_34G_service.json")
else:
    print(f"  No data. Response: {t[:300]}")

# ─── 3. GetFiloDurum_json (Fleet GPS Status - THE KEY ONE!) ───
print("\n🛰️ 3. GetFiloDurum_json (Fleet GPS Status)")
s, t = soap_call(
    f"{BASE}/FiloDurum/SeferGerceklesme.asmx",
    '<GetFiloDurum_json xmlns="http://tempuri.org/" />',
    "http://tempuri.org/GetFiloDurum_json"
)
print(f"  Status: {s}")
data = extract_json(t, "GetFiloDurum_jsonResult")
if data:
    if isinstance(data, list):
        print(f"  📊 Total fleet vehicles: {len(data)}")
        if data:
            print(f"  Fields: {list(data[0].keys())}")
            # Filter for metrobus
            metrobus = [v for v in data if "34G" in str(v.get("HATKODU", ""))
                        or "34G" in str(v.get("HAT_KODU", ""))
                        or "METROBÜS" in str(v.get("TARIFE", "")).upper()
                        or "metrobüs" in str(v).lower()
                        or "metrobus" in str(v).lower()]
            print(f"  🚍 Metrobus vehicles found: {len(metrobus)}")
            for v in (metrobus or data)[:5]:
                print(f"  {json.dumps(v, ensure_ascii=False)[:300]}")
            if metrobus:
                save_json(metrobus, "metrobus_fleet_gps.json")
            save_json(data[:20], "filo_durum_sample.json")
    else:
        print(f"  Data type: {type(data)}")
        print(f"  {json.dumps(data, ensure_ascii=False)[:500]}")
else:
    print(f"  ❌ No data extracted")
    if "Fault" in t:
        print(f"  API Gateway blocked this endpoint")
    print(f"  Response: {t[:500]}")

# ─── 4. GetPlanaUyum_json (Schedule adherence) ───
print("\n📋 4. GetPlanaUyum_json (Schedule Adherence)")
s, t = soap_call(
    f"{BASE}/FiloDurum/SeferGerceklesme.asmx",
    '<GetPlanaUyum_json xmlns="http://tempuri.org/" />',
    "http://tempuri.org/GetPlanaUyum_json"
)
print(f"  Status: {s}")
data = extract_json(t, "GetPlanaUyum_jsonResult")
if data:
    if isinstance(data, list):
        print(f"  📊 Total entries: {len(data)}")
        if data:
            print(f"  Fields: {list(data[0].keys())}")
            for d in data[:3]:
                print(f"  {json.dumps(d, ensure_ascii=False)[:300]}")
            save_json(data[:20], "plana_uyum_sample.json")
    else:
        print(f"  {json.dumps(data, ensure_ascii=False)[:500]}")
else:
    print(f"  ❌ No data. Response: {t[:300]}")

# ─── 5. DurakDetay_GYY_wYonAdi for 34G ───
print("\n📍 5. DurakDetay_GYY_wYonAdi for 34G (with direction)")
s, t = soap_call(
    f"{BASE}/ibb/ibb.asmx",
    '<DurakDetay_GYY_wYonAdi xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></DurakDetay_GYY_wYonAdi>',
    "http://tempuri.org/DurakDetay_GYY_wYonAdi"
)
print(f"  Status: {s}")
tables = extract_tables(t)
if tables:
    print(f"  Found {len(tables)} stops with direction")
    print(f"  Fields: {list(tables[0].keys())}")
    for row in tables[:5]:
        print(f"  {json.dumps(row, ensure_ascii=False)}")
    save_json(tables, "metrobus_34G_stops_with_direction.json")
else:
    print(f"  No data. Response: {t[:300]}")

print(f"\n{'='*60}")
print("  DONE")
print(f"{'='*60}")
