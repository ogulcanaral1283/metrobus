"""Quick test of IETT SOAP endpoints that worked in the probe."""
import requests
import json
import xml.etree.ElementTree as ET

BASE = "https://api.ibb.gov.tr/iett"
SOAP = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
    '<soap12:Body>{body}</soap12:Body>'
    '</soap12:Envelope>'
)
HEADERS = {"Content-Type": "application/soap+xml; charset=utf-8"}


def soap_call(url, body):
    r = requests.post(url, data=SOAP.format(body=body).encode("utf-8"),
                      headers=HEADERS, timeout=30)
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


# ─── Test 1: GetHat_json for all metrobus lines ───
print("=" * 60)
print("TEST 1: GetHat_json — All Metrobus Lines")
print("=" * 60)
url = f"{BASE}/UlasimAnaVeri/HatDurakGuzergah.asmx"
for hat in ["34", "34A", "34AS", "34BZ", "34G", "34U", "34Z", "34C"]:
    body = f'<GetHat_json xmlns="http://tempuri.org/"><HatKodu>{hat}</HatKodu></GetHat_json>'
    status, text = soap_call(url, body)
    data = extract_json(text, "GetHat_jsonResult")
    if data:
        for item in data:
            print(f"  {hat}: {json.dumps(item, ensure_ascii=False)}")
    else:
        print(f"  {hat}: No data (status={status})")

# ─── Test 2: DurakDetay_GYY for 34G ───
print("\n" + "=" * 60)
print("TEST 2: DurakDetay_GYY — Metrobus 34G Stop Details")
print("=" * 60)
url2 = f"{BASE}/ibb/ibb.asmx"
body2 = '<DurakDetay_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></DurakDetay_GYY>'
status, text = soap_call(url2, body2)
tables = extract_tables(text)
if tables:
    print(f"  Found {len(tables)} stops/rows")
    for t in tables[:8]:
        print(f"  {json.dumps(t, ensure_ascii=False)[:300]}")
    if len(tables) > 8:
        print(f"  ... and {len(tables) - 8} more")
else:
    print(f"  No tables found (status={status})")
    print(f"  Response snippet: {text[:500]}")

# ─── Test 3: GetHatGuzergah_json for 34G ───
print("\n" + "=" * 60)
print("TEST 3: GetHatGuzergah_json — 34G Route Geometry")
print("=" * 60)
body3 = '<GetHatGuzergah_json xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetHatGuzergah_json>'
status, text = soap_call(url, body3)
data = extract_json(text, "GetHatGuzergah_jsonResult")
if data:
    print(f"  Total route points: {len(data)}")
    for p in data[:3]:
        print(f"  {json.dumps(p, ensure_ascii=False)[:300]}")
else:
    print(f"  No data (status={status})")
    print(f"  Response snippet: {text[:500]}")

# ─── Test 4: GetDurak_json for all stops ───
print("\n" + "=" * 60)
print("TEST 4: GetDurak_json — All Stops")
print("=" * 60)
body4 = '<GetDurak_json xmlns="http://tempuri.org/"><DurakKodu></DurakKodu></GetDurak_json>'
status, text = soap_call(url, body4)
data = extract_json(text, "GetDurak_jsonResult")
if data:
    print(f"  Total stops: {len(data)}")
    for s in data[:3]:
        print(f"  {json.dumps(s, ensure_ascii=False)[:200]}")
else:
    print(f"  No data (status={status})")
    print(f"  Response snippet: {text[:500]}")

# ─── Test 5: ibb360 YolculukHat ───
print("\n" + "=" * 60)
print("TEST 5: ibb360.asmx — GetIettYolculukHat_json")
print("=" * 60)
url5 = f"{BASE}/ibb/ibb360.asmx"
body5 = '<GetIettYolculukHat_json xmlns="http://tempuri.org/"><Tarih>2026-03-19</Tarih></GetIettYolculukHat_json>'
status, text = soap_call(url5, body5)
data = extract_json(text, "GetIettYolculukHat_jsonResult")
if data:
    print(f"  Total items: {len(data) if isinstance(data, list) else 'N/A'}")
    if isinstance(data, list):
        for item in data[:5]:
            print(f"  {json.dumps(item, ensure_ascii=False)[:300]}")
    else:
        print(f"  {json.dumps(data, ensure_ascii=False)[:500]}")
else:
    print(f"  No data (status={status})")
    print(f"  Response snippet: {text[:500]}")

# ─── Test 6: HatServisi_GYY for 34G ───
print("\n" + "=" * 60)
print("TEST 6: HatServisi_GYY — 34G Service Info")
print("=" * 60)
body6 = '<HatServisi_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></HatServisi_GYY>'
status, text = soap_call(url2, body6)
tables = extract_tables(text)
if tables:
    print(f"  Found {len(tables)} rows")
    for t in tables[:5]:
        print(f"  {json.dumps(t, ensure_ascii=False)[:300]}")
else:
    print(f"  No tables (status={status})")
    print(f"  Response snippet: {text[:500]}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
