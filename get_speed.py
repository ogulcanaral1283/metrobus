"""
METROBÜS SERVİS TEST SCRIPTI
Üç farklı metodu test eder, hangisi gerçek Metrobüs verisi dönüyor görür.

Toplam 9 API çağrısı harcar (kotandan 9/100).
"""

import requests
import json
import xml.etree.ElementTree as ET
from html import unescape

API_KEY = "4f36be25-be2e-45be-add0-76ddcafe97ae"
URL_SEFER = "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx"


def soap_call(soap_action, body_inner, with_auth=True):
    """Tek SOAP çağrısı yap, JSON string döndür."""
    auth_header = ""
    if with_auth:
        auth_header = f"""<soap:Header>
    <tem:AuthHeader>
      <tem:Username>{API_KEY}</tem:Username>
      <tem:Password>{API_KEY}</tem:Password>
    </tem:AuthHeader>
  </soap:Header>"""
    
    soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tem="http://tempuri.org/">
  {auth_header}
  <soap:Body>
    {body_inner}
  </soap:Body>
</soap:Envelope>"""
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{soap_action}"',
    }
    
    r = requests.post(URL_SEFER, data=soap_body.encode("utf-8"), headers=headers, timeout=30)
    r.raise_for_status()
    
    root = ET.fromstring(r.content)
    ns = {"tns": "http://tempuri.org/"}
    
    # Sonuç node'u — metoda göre tag adı değişir
    for child in root.iter():
        if child.tag.endswith("Result") and child.text:
            return unescape(child.text)
    return None


def parse_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(json.loads(raw))
        except:
            return raw


def test_metot(isim, soap_action, body_inner):
    print(f"\n{'='*60}")
    print(f"TEST: {isim}")
    print(f"{'='*60}")
    try:
        raw = soap_call(soap_action, body_inner)
        data = parse_json(raw)
        
        if data is None:
            print("  → Cevap boş")
            return
        
        if isinstance(data, list):
            print(f"  → {len(data)} kayıt geldi")
            if data:
                print(f"\n  İlk kayıt:")
                print(f"  {json.dumps(data[0], indent=2, ensure_ascii=False)}")
                if len(data) > 1:
                    print(f"\n  İkinci kayıt:")
                    print(f"  {json.dumps(data[1], indent=2, ensure_ascii=False)}")
        else:
            print(f"  → Tip: {type(data).__name__}")
            print(f"  {str(data)[:500]}")
    except requests.HTTPError as e:
        print(f"  → HTTP HATA: {e}")
    except Exception as e:
        print(f"  → HATA: {type(e).__name__}: {e}")


# ============================================================
# TESTLER
# ============================================================

# Test 1-7: GetHatOtoKonum_json — Metrobüs hat kodlarıyla
metrobus_hatlari = ["34", "34A", "34AS", "34BZ", "34C", "34G", "34Z"]
for hat in metrobus_hatlari:
    test_metot(
        f"GetHatOtoKonum_json (HatKodu={hat})",
        "http://tempuri.org/GetHatOtoKonum_json",
        f"<tem:GetHatOtoKonum_json><tem:HatKodu>{hat}</tem:HatKodu></tem:GetHatOtoKonum_json>"
    )

# Test 8: Servise hazır Metrobüs araçları (parametresiz, dokümandaki Metrobüs özel metodu)
test_metot(
    "GetKaraKutu_ServiseHazirAracMetrobus_json",
    "http://tempuri.org/GetKaraKutu_ServiseHazirAracMetrobus_json",
    "<tem:GetKaraKutu_ServiseHazirAracMetrobus_json/>"
)

print("\n\n" + "="*60)
print("ÖZET")
print("="*60)
print("Hangi metot gerçek Metrobüs araç verisi (kapı no, konum, hız) döndü?")
print("Çıktıyı paylaş, ona göre toplama scriptini yazalım.")