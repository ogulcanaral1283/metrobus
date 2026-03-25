"""
Fetch metrobus route geometry (edges) from IETT API.
Tests GetHatGuzergah_json and other geometry-related endpoints.
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
    print(f"  💾 Saved: {path}")


print("=" * 60)
print(f"  IETT Route Geometry Fetcher")
print(f"  Time: {datetime.now().isoformat()}")
print("=" * 60)

url_hat = f"{BASE}/UlasimAnaVeri/HatDurakGuzergah.asmx"
url_ibb = f"{BASE}/ibb/ibb.asmx"

# ─── 1. GetHatGuzergah_json for 34G ───
print("\n🗺️  1. GetHatGuzergah_json (34G Route Geometry)")
s, t = soap_call(
    url_hat,
    '<GetHatGuzergah_json xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetHatGuzergah_json>',
    "http://tempuri.org/GetHatGuzergah_json"
)
print(f"  Status: {s}")
data = extract_json(t, "GetHatGuzergah_jsonResult")
if data:
    if isinstance(data, list):
        print(f"  📊 Total route points: {len(data)}")
        if data:
            print(f"  Fields: {list(data[0].keys())}")
            for p in data[:5]:
                print(f"  {json.dumps(p, ensure_ascii=False)[:300]}")
            if len(data) > 5:
                print(f"  ... +{len(data)-5} more")
            save_json(data, "metrobus_34G_route_geometry.json")
    else:
        print(f"  {json.dumps(data, ensure_ascii=False)[:500]}")
else:
    # Check XML table format
    tables = extract_tables(t)
    if tables:
        print(f"  📊 Found {len(tables)} rows (table format)")
        print(f"  Fields: {list(tables[0].keys())}")
        for row in tables[:5]:
            print(f"  {json.dumps(row, ensure_ascii=False)[:300]}")
        save_json(tables, "metrobus_34G_route_geometry.json")
    else:
        print(f"  ❌ No data")
        if "Fault" in t:
            print(f"  Policy blocked")
        else:
            print(f"  Response: {t[:500]}")

# ─── 2. GetHatGuzergah_XML for 34G ───
print("\n🗺️  2. GetHatGuzergah_XML (34G Route XML)")
s, t = soap_call(
    url_hat,
    '<GetHatGuzergah_XML xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetHatGuzergah_XML>',
    "http://tempuri.org/GetHatGuzergah_XML"
)
print(f"  Status: {s}")
tables = extract_tables(t)
if tables:
    print(f"  📊 Found {len(tables)} rows")
    print(f"  Fields: {list(tables[0].keys())}")
    for row in tables[:5]:
        print(f"  {json.dumps(row, ensure_ascii=False)[:300]}")
    save_json(tables, "metrobus_34G_route_geometry_xml.json")
else:
    if "Fault" in t:
        print(f"  ❌ Policy blocked")
    else:
        print(f"  Response: {t[:500]}")

# ─── 3. GetDurakGuzergah_json for 34G ───
print("\n🗺️  3. GetDurakGuzergah_json (34G Stop-Route)")
s, t = soap_call(
    url_hat,
    '<GetDurakGuzergah_json xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetDurakGuzergah_json>',
    "http://tempuri.org/GetDurakGuzergah_json"
)
print(f"  Status: {s}")
data = extract_json(t, "GetDurakGuzergah_jsonResult")
if data:
    if isinstance(data, list):
        print(f"  📊 Total items: {len(data)}")
        if data:
            print(f"  Fields: {list(data[0].keys())}")
            for p in data[:5]:
                print(f"  {json.dumps(p, ensure_ascii=False)[:300]}")
            save_json(data, "metrobus_34G_stop_route.json")
    else:
        print(f"  {json.dumps(data, ensure_ascii=False)[:500]}")
else:
    tables = extract_tables(t)
    if tables:
        print(f"  📊 Found {len(tables)} rows")
        print(f"  Fields: {list(tables[0].keys())}")
        for row in tables[:3]:
            print(f"  {json.dumps(row, ensure_ascii=False)[:300]}")
    else:
        print(f"  ❌ No data. Response: {t[:300]}")

# ─── 4. Try all hat codes ───
print("\n🗺️  4. Trying different hat codes for route geometry")
for hat in ["34G", "34", "34A", "34BZ"]:
    s, t = soap_call(
        url_hat,
        f'<GetHatGuzergah_json xmlns="http://tempuri.org/"><HatKodu>{hat}</HatKodu></GetHatGuzergah_json>',
        "http://tempuri.org/GetHatGuzergah_json"
    )
    data = extract_json(t, "GetHatGuzergah_jsonResult")
    tables = extract_tables(t)
    if data:
        count = len(data) if isinstance(data, list) else "dict"
        print(f"  {hat}: ✅ JSON — {count} items")
    elif tables:
        print(f"  {hat}: ✅ XML — {len(tables)} rows")
    elif "Fault" in t:
        print(f"  {hat}: ❌ Policy blocked")
    else:
        print(f"  {hat}: ❌ No data ({s})")

# ─── 5. Try to get GTFS data from IBB ───
print("\n📦 5. Checking data.ibb.gov.tr for GTFS/route data")
try:
    r = requests.get("https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi", timeout=15)
    if r.status_code == 200:
        pkg = r.json()["result"]
        print(f"  Dataset: {pkg['title']}")
        print(f"  Resources: {pkg['num_resources']}")
        for res in pkg.get("resources", []):
            print(f"    📎 {res['name']} ({res['format']}) — {res['url'][:100]}")
except Exception as e:
    print(f"  Error: {e}")

# ─── 6. Check for hat guzergahlari dataset ───
print("\n📦 6. Checking iett-hat-guzergahlari")
try:
    r = requests.get("https://data.ibb.gov.tr/api/3/action/package_show?id=iett-hat-guzergahlari", timeout=15)
    if r.status_code == 200:
        pkg = r.json()["result"]
        print(f"  Dataset: {pkg['title']}")
        print(f"  Resources: {pkg['num_resources']}")
        for res in pkg.get("resources", []):
            print(f"    📎 {res['name']} ({res['format']}) — {res['url'][:100]}")
except Exception as e:
    print(f"  Error: {e}")

print(f"\n{'='*60}")
print("  DONE")
print(f"{'='*60}")
