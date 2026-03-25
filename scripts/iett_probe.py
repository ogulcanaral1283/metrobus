"""
IETT SOAP Service Probe — Metrobus GPS Data Explorer
=====================================================
Tests IBB/IETT SOAP web services to find real-time metrobus vehicle GPS data.

Probed endpoints:
  1. FiloDurum/SeferGerceklesme.asmx → GetFiloDurum_json
  2. ibb/ibb.asmx → DurakDetay_GYY (hat_kodu filter)
  3. UlasimAnaVeri/HatDurakGuzergah.asmx → GetHat_json

Metrobus hat kodlari: 34, 34A, 34AS, 34BZ, 34G, 34U, 34Z
"""

import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import time
import sys

BASE = "https://api.ibb.gov.tr/iett"

# ──────────────────────────────────────────────
# SOAP helpers
# ──────────────────────────────────────────────

SOAP_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                 xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    {body}
  </soap12:Body>
</soap12:Envelope>"""

SOAP_ENVELOPE_11 = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    {body}
  </soap:Body>
</soap:Envelope>"""

HEADERS_SOAP12 = {
    "Content-Type": "application/soap+xml; charset=utf-8",
}

HEADERS_SOAP11 = {
    "Content-Type": "text/xml; charset=utf-8",
}


def soap_call(url, body_xml, action=None, soap_version=12):
    """Make a SOAP call and return the response text."""
    if soap_version == 12:
        envelope = SOAP_ENVELOPE.format(body=body_xml)
        headers = {**HEADERS_SOAP12}
    else:
        envelope = SOAP_ENVELOPE_11.format(body=body_xml)
        headers = {**HEADERS_SOAP11}
        if action:
            headers["SOAPAction"] = action

    try:
        resp = requests.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=30)
        return resp.status_code, resp.text
    except requests.exceptions.RequestException as e:
        return None, str(e)


def try_json_extract(xml_text, result_tag):
    """Try to extract JSON result from SOAP response XML."""
    try:
        # Remove namespace prefixes for easier parsing
        clean = xml_text
        for ns in ["soap:", "soap12:", "xmlns:", "xsi:", "xsd:"]:
            clean = clean.replace(ns, "")
        root = ET.fromstring(clean)
        # Search for the result element
        for elem in root.iter():
            if result_tag in (elem.tag or ""):
                text = elem.text
                if text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
        return None
    except ET.ParseError:
        return None


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_result(label, status, data, max_items=3):
    print(f"\n  [{label}]")
    print(f"  HTTP Status: {status}")
    if data is None:
        print("  Result: No data extracted")
    elif isinstance(data, list):
        print(f"  Total items: {len(data)}")
        for i, item in enumerate(data[:max_items]):
            print(f"  Item {i}: {json.dumps(item, ensure_ascii=False, indent=4)[:500]}")
        if len(data) > max_items:
            print(f"  ... and {len(data) - max_items} more items")
    elif isinstance(data, dict):
        print(f"  {json.dumps(data, ensure_ascii=False, indent=4)[:1000]}")
    else:
        print(f"  {str(data)[:1000]}")


# ──────────────────────────────────────────────
# Probe 1: GetFiloDurum_json
# ──────────────────────────────────────────────

def probe_filo_durum():
    print_section("PROBE 1: GetFiloDurum_json (Fleet Status)")
    url = f"{BASE}/FiloDurum/SeferGerceklesme.asmx"

    body = '<GetFiloDurum_json xmlns="http://tempuri.org/" />'
    status, text = soap_call(url, body)
    data = try_json_extract(text, "GetFiloDurum_jsonResult")
    print_result("GetFiloDurum_json (SOAP 1.2)", status, data)

    if data is None:
        # Try SOAP 1.1
        status, text = soap_call(url, body, action="http://tempuri.org/GetFiloDurum_json", soap_version=11)
        data = try_json_extract(text, "GetFiloDurum_jsonResult")
        print_result("GetFiloDurum_json (SOAP 1.1)", status, data)

    if data is None:
        # Try HTTP GET/POST
        for method in ["GET", "POST"]:
            try:
                if method == "GET":
                    resp = requests.get(f"{url}/GetFiloDurum_json", timeout=15)
                else:
                    resp = requests.post(f"{url}/GetFiloDurum_json", data={}, timeout=15)
                status = resp.status_code
                try:
                    data = resp.json()
                except:
                    data = resp.text[:500]
                print_result(f"GetFiloDurum_json (HTTP {method})", status, data)
                if status == 200:
                    break
            except Exception as e:
                print(f"  HTTP {method} error: {e}")

    return data


# ──────────────────────────────────────────────
# Probe 2: GetPlanaUyum_json
# ──────────────────────────────────────────────

def probe_plana_uyum():
    print_section("PROBE 2: GetPlanaUyum_json (Schedule Adherence)")
    url = f"{BASE}/FiloDurum/SeferGerceklesme.asmx"

    body = '<GetPlanaUyum_json xmlns="http://tempuri.org/" />'
    status, text = soap_call(url, body)
    data = try_json_extract(text, "GetPlanaUyum_jsonResult")
    print_result("GetPlanaUyum_json (SOAP 1.2)", status, data)

    if data is None:
        status, text = soap_call(url, body, action="http://tempuri.org/GetPlanaUyum_json", soap_version=11)
        data = try_json_extract(text, "GetPlanaUyum_jsonResult")
        print_result("GetPlanaUyum_json (SOAP 1.1)", status, data)

    return data


# ──────────────────────────────────────────────
# Probe 3: DurakDetay_GYY with metrobus hat kodu
# ──────────────────────────────────────────────

def probe_durak_detay(hat_kodu="34G"):
    print_section(f"PROBE 3: DurakDetay_GYY (hat_kodu={hat_kodu})")
    url = f"{BASE}/ibb/ibb.asmx"

    body = f'''<DurakDetay_GYY xmlns="http://tempuri.org/">
      <hat_kodu>{hat_kodu}</hat_kodu>
    </DurakDetay_GYY>'''
    status, text = soap_call(url, body)
    data = try_json_extract(text, "DurakDetay_GYYResult")

    # If SOAP 1.2 fails, try XML parsing of full response
    if data is None and text:
        # Maybe the result is inside XML, not JSON
        try:
            root = ET.fromstring(text)
            # Print all element tags for debugging
            tags = set()
            for elem in root.iter():
                tags.add(elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag)
                if elem.text and elem.text.strip() and len(elem.text.strip()) > 5:
                    data = elem.text[:500]
            print(f"  XML tags found: {tags}")
        except:
            pass

    print_result(f"DurakDetay_GYY hat={hat_kodu} (SOAP 1.2)", status, data)

    if data is None:
        body_11 = f'''<DurakDetay_GYY xmlns="http://tempuri.org/">
          <hat_kodu>{hat_kodu}</hat_kodu>
        </DurakDetay_GYY>'''
        status, text = soap_call(url, body_11, action="http://tempuri.org/DurakDetay_GYY", soap_version=11)
        data = try_json_extract(text, "DurakDetay_GYYResult")
        print_result(f"DurakDetay_GYY hat={hat_kodu} (SOAP 1.1)", status, data)

    # Also try HTTP POST
    if data is None:
        try:
            resp = requests.post(f"{url}/DurakDetay_GYY", data={"hat_kodu": hat_kodu}, timeout=15)
            print_result(f"DurakDetay_GYY hat={hat_kodu} (HTTP POST)", resp.status_code,
                         resp.text[:500] if resp.status_code == 200 else f"Error: {resp.status_code}")
        except Exception as e:
            print(f"  HTTP POST error: {e}")

    return data


# ──────────────────────────────────────────────
# Probe 4: GetHat_json with metrobus hat kodu
# ──────────────────────────────────────────────

def probe_hat_bilgi(hat_kodu="34G"):
    print_section(f"PROBE 4: GetHat_json (hat_kodu={hat_kodu})")
    url = f"{BASE}/UlasimAnaVeri/HatDurakGuzergah.asmx"

    body = f'''<GetHat_json xmlns="http://tempuri.org/">
      <HatKodu>{hat_kodu}</HatKodu>
    </GetHat_json>'''
    status, text = soap_call(url, body)
    data = try_json_extract(text, "GetHat_jsonResult")
    print_result(f"GetHat_json hat={hat_kodu} (SOAP 1.2)", status, data)

    if data is None:
        status, text = soap_call(url, body, action="http://tempuri.org/GetHat_json", soap_version=11)
        data = try_json_extract(text, "GetHat_jsonResult")
        print_result(f"GetHat_json hat={hat_kodu} (SOAP 1.1)", status, data)

    # HTTP fallback
    if data is None:
        try:
            resp = requests.get(f"{url}/GetHat_json?HatKodu={hat_kodu}", timeout=15)
            try:
                data = resp.json()
            except:
                data = resp.text[:500]
            print_result(f"GetHat_json hat={hat_kodu} (HTTP GET)", resp.status_code, data)
        except Exception as e:
            print(f"  HTTP GET error: {e}")

    return data


# ──────────────────────────────────────────────
# Probe 5: HatServisi_GYY with metrobus hat kodu
# ──────────────────────────────────────────────

def probe_hat_servisi(hat_kodu="34G"):
    print_section(f"PROBE 5: HatServisi_GYY (hat_kodu={hat_kodu})")
    url = f"{BASE}/ibb/ibb.asmx"

    body = f'''<HatServisi_GYY xmlns="http://tempuri.org/">
      <hat_kodu>{hat_kodu}</hat_kodu>
    </HatServisi_GYY>'''
    status, text = soap_call(url, body)

    # Try to parse XML result
    data = None
    if text:
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if "Result" in tag and elem.text and len(elem.text.strip()) > 5:
                    try:
                        data = json.loads(elem.text)
                    except:
                        data = elem.text[:500]
                # Also check for nested XML data
                if tag == "Table" or tag == "NewDataSet":
                    data = ET.tostring(elem, encoding="unicode")[:1000]
        except:
            pass

    print_result(f"HatServisi_GYY hat={hat_kodu} (SOAP 1.2)", status, data)

    # Try to extract raw XML response for debugging
    if text and status == 200:
        print(f"\n  Raw response (first 800 chars):")
        print(f"  {text[:800]}")

    return data


# ──────────────────────────────────────────────
# Probe 6: GetSeferZayi_json (missed trips)
# ──────────────────────────────────────────────

def probe_sefer_zayi():
    print_section("PROBE 6: GetSeferZayi_json (Missed Trips)")
    url = f"{BASE}/FiloDurum/SeferGerceklesme.asmx"

    body = '<GetSeferZayi_json xmlns="http://tempuri.org/" />'
    status, text = soap_call(url, body)
    data = try_json_extract(text, "GetSeferZayi_jsonResult")
    print_result("GetSeferZayi_json (SOAP 1.2)", status, data)

    return data


# ──────────────────────────────────────────────
# Probe 7: Direct HTTP GET attempts on common patterns
# ──────────────────────────────────────────────

def probe_http_direct():
    print_section("PROBE 7: Direct HTTP GET on common API patterns")

    urls_to_try = [
        f"{BASE}/ibb/ibb.asmx/DurakDetay_GYY?hat_kodu=34G",
        f"{BASE}/ibb/ibb.asmx/HatServisi_GYY?hat_kodu=34G",
        f"{BASE}/ibb/ibb.asmx/IETTPlakaServisi_Json?KapiNo=",
        f"{BASE}/FiloDurum/SeferGerceklesme.asmx/GetFiloDurum_json",
        f"{BASE}/FiloDurum/SeferGerceklesme.asmx/GetPlanaUyum_json",
        f"{BASE}/FiloDurum/SeferGerceklesme.asmx/GetSeferZayi_json",
        "https://data.ibb.gov.tr/api/3/action/package_list",
        "https://data.ibb.gov.tr/api/3/action/package_search?q=metrobus",
        "https://data.ibb.gov.tr/api/3/action/package_search?q=otobus+konum",
    ]

    results = {}
    for url in urls_to_try:
        try:
            resp = requests.get(url, timeout=15)
            short_url = url.replace(BASE, "...").replace("https://data.ibb.gov.tr", "data.ibb")
            status = resp.status_code
            if status == 200:
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        preview = f"List[{len(data)}]: {str(data[:2])[:200]}"
                    elif isinstance(data, dict):
                        preview = json.dumps(data, ensure_ascii=False)[:300]
                    else:
                        preview = str(data)[:300]
                except:
                    preview = resp.text[:300]
                print(f"\n  ✅ {status} {short_url}")
                print(f"     {preview}")
                results[url] = data
            else:
                print(f"  ❌ {status} {short_url}")
        except Exception as e:
            short_url = url.replace(BASE, "...").replace("https://data.ibb.gov.tr", "data.ibb")
            print(f"  ⚠️  ERR {short_url}: {e}")

    return results


# ──────────────────────────────────────────────
# Main execution
# ──────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  IETT SOAP Service Probe — Metrobus GPS Data Explorer")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 70)

    # Save results for analysis
    all_results = {}

    # Probe 1: Fleet status (most likely to have GPS data)
    all_results["filo_durum"] = probe_filo_durum()

    # Probe 2: Schedule adherence
    all_results["plana_uyum"] = probe_plana_uyum()

    # Probe 3: Stop details for metrobus lines
    for hat in ["34G", "34"]:
        all_results[f"durak_{hat}"] = probe_durak_detay(hat)

    # Probe 4: Line info
    all_results["hat_34G"] = probe_hat_bilgi("34G")

    # Probe 5: Hat service (may contain vehicle positions)
    all_results["hat_servisi_34G"] = probe_hat_servisi("34G")

    # Probe 6: Missed trips
    all_results["sefer_zayi"] = probe_sefer_zayi()

    # Probe 7: Direct HTTP
    all_results["http_direct"] = probe_http_direct()

    # Save raw results
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"iett_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    serializable = {}
    for k, v in all_results.items():
        try:
            json.dumps(v)
            serializable[k] = v
        except (TypeError, ValueError):
            serializable[k] = str(v)[:1000] if v else None

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'='*70}")
    print(f"  Results saved to: {output_file}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
