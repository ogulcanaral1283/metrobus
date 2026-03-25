"""
IETT API Test with IBB API Key
================================
Tests all IETT SOAP endpoints using the IBB Open Data API key.
"""
import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime

API_KEY = "4f36be25-be2e-45be-add0-76ddcafe97ae"
BASE = "https://api.ibb.gov.tr/iett"

# SOAP 1.2 envelope
SOAP12 = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
    '<soap12:Body>{body}</soap12:Body>'
    '</soap12:Envelope>'
)

# SOAP 1.1 envelope
SOAP11 = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body>{body}</soap:Body>'
    '</soap:Envelope>'
)


def try_all_auth_methods(url, body, action=None):
    """Try multiple auth methods to find what works."""
    results = []

    # Method 1: SOAP 1.2 + apikey query param
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    try:
        r = requests.post(f"{url}?apikey={API_KEY}", 
                          data=SOAP12.format(body=body).encode("utf-8"),
                          headers=headers, timeout=30)
        results.append(("SOAP1.2+queryParam", r.status_code, r.text))
        if r.status_code == 200 and "Fault" not in r.text:
            return results  # found working method
    except Exception as e:
        results.append(("SOAP1.2+queryParam", None, str(e)))

    # Method 2: SOAP 1.2 + Authorization Bearer header
    headers2 = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "Authorization": f"Bearer {API_KEY}"
    }
    try:
        r = requests.post(url, data=SOAP12.format(body=body).encode("utf-8"),
                          headers=headers2, timeout=30)
        results.append(("SOAP1.2+Bearer", r.status_code, r.text))
        if r.status_code == 200 and "Fault" not in r.text:
            return results
    except Exception as e:
        results.append(("SOAP1.2+Bearer", None, str(e)))

    # Method 3: SOAP 1.2 + IBBApikeyv2 header (common IBB pattern)
    headers3 = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "IBBApikeyv2": API_KEY
    }
    try:
        r = requests.post(url, data=SOAP12.format(body=body).encode("utf-8"),
                          headers=headers3, timeout=30)
        results.append(("SOAP1.2+IBBApikeyv2", r.status_code, r.text))
        if r.status_code == 200 and "Fault" not in r.text:
            return results
    except Exception as e:
        results.append(("SOAP1.2+IBBApikeyv2", None, str(e)))

    # Method 4: SOAP 1.1 + apikey query param
    headers4 = {"Content-Type": "text/xml; charset=utf-8"}
    if action:
        headers4["SOAPAction"] = action
    try:
        r = requests.post(f"{url}?apikey={API_KEY}",
                          data=SOAP11.format(body=body).encode("utf-8"),
                          headers=headers4, timeout=30)
        results.append(("SOAP1.1+queryParam", r.status_code, r.text))
        if r.status_code == 200 and "Fault" not in r.text:
            return results
    except Exception as e:
        results.append(("SOAP1.1+queryParam", None, str(e)))

    # Method 5: HTTP GET + apikey query param
    method_name = body.split('xmlns')[0].split('<')[-1].strip()
    params = {}
    # Extract params from body XML
    import re
    for m in re.finditer(r'<(\w+)>([^<]*)</\1>', body):
        params[m.group(1)] = m.group(2)
    params["apikey"] = API_KEY
    try:
        r = requests.get(f"{url}/{method_name}", params=params, timeout=15)
        results.append(("HTTP_GET+queryParam", r.status_code, r.text))
        if r.status_code == 200 and "Fault" not in r.text:
            return results
    except Exception as e:
        results.append(("HTTP_GET+queryParam", None, str(e)))

    # Method 6: HTTP POST + apikey query param
    try:
        r = requests.post(f"{url}/{method_name}",
                          data=params, timeout=15)
        results.append(("HTTP_POST+formData", r.status_code, r.text))
    except Exception as e:
        results.append(("HTTP_POST+formData", None, str(e)))

    # Method 7: SOAP 1.2 + Ocp-Apim-Subscription-Key header (Azure APIM pattern)
    headers7 = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "Ocp-Apim-Subscription-Key": API_KEY
    }
    try:
        r = requests.post(url, data=SOAP12.format(body=body).encode("utf-8"),
                          headers=headers7, timeout=30)
        results.append(("SOAP1.2+OcpApim", r.status_code, r.text))
    except Exception as e:
        results.append(("SOAP1.2+OcpApim", None, str(e)))

    return results


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


def test_endpoint(name, url, body, action=None, json_tag=None):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    results = try_all_auth_methods(url, body, action)
    
    found_data = False
    for method, status, text in results:
        has_fault = text and "Fault" in text if isinstance(text, str) else False
        has_data = status == 200 and not has_fault
        marker = "✅" if has_data else "❌"
        
        print(f"  {marker} {method}: status={status}")
        
        if has_data and text:
            # Try JSON extraction
            if json_tag:
                data = extract_json(text, json_tag)
                if data:
                    found_data = True
                    if isinstance(data, list):
                        print(f"     📊 {len(data)} items")
                        for item in data[:3]:
                            print(f"     {json.dumps(item, ensure_ascii=False)[:250]}")
                        if len(data) > 3:
                            print(f"     ... +{len(data)-3} more")
                    else:
                        print(f"     {json.dumps(data, ensure_ascii=False)[:500]}")
            
            # Try table extraction
            tables = extract_tables(text)
            if tables:
                found_data = True
                print(f"     📊 {len(tables)} rows")
                for t in tables[:3]:
                    print(f"     {json.dumps(t, ensure_ascii=False)[:250]}")
                if len(tables) > 3:
                    print(f"     ... +{len(tables)-3} more")
            
            if not found_data:
                # Show raw response
                clean = text[:400].replace("\n", " ").replace("\r", "")
                print(f"     Raw: {clean}")
    
    if not found_data:
        # Show error detail from last attempt
        if results:
            _, _, last_text = results[-1]
            if last_text and "Policy" in str(last_text):
                print(f"     ⚠️  API Gateway blocking (Policy Falsified)")
    
    return found_data


def main():
    print("=" * 60)
    print(f"  IETT API Test with IBB API Key")
    print(f"  Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 60)

    url_hat = f"{BASE}/UlasimAnaVeri/HatDurakGuzergah.asmx"
    url_ibb = f"{BASE}/ibb/ibb.asmx"
    url_filo = f"{BASE}/FiloDurum/SeferGerceklesme.asmx"
    url_360 = f"{BASE}/ibb/ibb360.asmx"

    working = []

    # 1. GetHat_json - Line info (previously worked)
    if test_endpoint(
        "GetHat_json (34G Line Info)",
        url_hat,
        '<GetHat_json xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetHat_json>',
        action="http://tempuri.org/GetHat_json",
        json_tag="GetHat_jsonResult"
    ):
        working.append("GetHat_json")

    # 2. GetDurak_json - Stop info
    if test_endpoint(
        "GetDurak_json (All Stops)",
        url_hat,
        '<GetDurak_json xmlns="http://tempuri.org/"><DurakKodu></DurakKodu></GetDurak_json>',
        action="http://tempuri.org/GetDurak_json",
        json_tag="GetDurak_jsonResult"
    ):
        working.append("GetDurak_json")

    # 3. GetHatGuzergah_json - Route geometry
    if test_endpoint(
        "GetHatGuzergah_json (34G Route)",
        url_hat,
        '<GetHatGuzergah_json xmlns="http://tempuri.org/"><HatKodu>34G</HatKodu></GetHatGuzergah_json>',
        action="http://tempuri.org/GetHatGuzergah_json",
        json_tag="GetHatGuzergah_jsonResult"
    ):
        working.append("GetHatGuzergah_json")

    # 4. DurakDetay_GYY - Stop details with live vehicle info
    if test_endpoint(
        "DurakDetay_GYY (34G Live Stop Data)",
        url_ibb,
        '<DurakDetay_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></DurakDetay_GYY>',
        action="http://tempuri.org/DurakDetay_GYY"
    ):
        working.append("DurakDetay_GYY")

    # 5. HatServisi_GYY - Line service data
    if test_endpoint(
        "HatServisi_GYY (34G Service Info)",
        url_ibb,
        '<HatServisi_GYY xmlns="http://tempuri.org/"><hat_kodu>34G</hat_kodu></HatServisi_GYY>',
        action="http://tempuri.org/HatServisi_GYY"
    ):
        working.append("HatServisi_GYY")

    # 6. GetFiloDurum_json - FLEET STATUS (THE BIG ONE!)
    if test_endpoint(
        "GetFiloDurum_json (Fleet Status - GPS!)",
        url_filo,
        '<GetFiloDurum_json xmlns="http://tempuri.org/" />',
        action="http://tempuri.org/GetFiloDurum_json",
        json_tag="GetFiloDurum_jsonResult"
    ):
        working.append("GetFiloDurum_json")

    # 7. GetPlanaUyum_json - Schedule adherence
    if test_endpoint(
        "GetPlanaUyum_json (Schedule Adherence)",
        url_filo,
        '<GetPlanaUyum_json xmlns="http://tempuri.org/" />',
        action="http://tempuri.org/GetPlanaUyum_json",
        json_tag="GetPlanaUyum_jsonResult"
    ):
        working.append("GetPlanaUyum_json")

    # 8. GetSeferZayi_json - Missed trips
    if test_endpoint(
        "GetSeferZayi_json (Missed Trips)",
        url_filo,
        '<GetSeferZayi_json xmlns="http://tempuri.org/" />',
        action="http://tempuri.org/GetSeferZayi_json",
        json_tag="GetSeferZayi_jsonResult"
    ):
        working.append("GetSeferZayi_json")

    # 9. ibb360 - Trip data
    if test_endpoint(
        "GetIettYolculukHat_json (Trip Data)",
        url_360,
        '<GetIettYolculukHat_json xmlns="http://tempuri.org/"><Tarih>2026-03-19</Tarih></GetIettYolculukHat_json>',
        action="http://tempuri.org/GetIettYolculukHat_json",
        json_tag="GetIettYolculukHat_jsonResult"
    ):
        working.append("GetIettYolculukHat_json")

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Working endpoints: {len(working)}")
    for w in working:
        print(f"    ✅ {w}")
    if not working:
        print("  ❌ No endpoints responded with data")
        print("  The API key might need to be passed differently.")
        print("  Check the IBB developer portal for auth documentation.")


if __name__ == "__main__":
    main()
