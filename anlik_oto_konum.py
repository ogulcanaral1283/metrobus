import requests
import json
import xml.etree.ElementTree as ET
from html import unescape

API_KEY = "4f36be25-be2e-45be-add0-76ddcafe97ae"
URL = "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx"

# Metrobüs koridorunda çalışan tüm hat kodları
METROBUS_HATLARI = ["34", "34A", "34AS", "34BZ", "34C", "34G", "34Z"]


def get_hat_konumlari(hat_kodu: str) -> list[dict]:
    """Bir Metrobüs hat kodu için anlık araç konumlarını döndür."""
    
    soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tem="http://tempuri.org/">
  <soap:Header>
    <tem:AuthHeader>
      <tem:Username>{API_KEY}</tem:Username>
      <tem:Password>{API_KEY}</tem:Password>
    </tem:AuthHeader>
  </soap:Header>
  <soap:Body>
    <tem:GetHatOtoKonum_json>
      <tem:HatKodu>{hat_kodu}</tem:HatKodu>
    </tem:GetHatOtoKonum_json>
  </soap:Body>
</soap:Envelope>"""
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"http://tempuri.org/GetHatOtoKonum_json"',
    }
    
    response = requests.post(URL, data=soap_body.encode("utf-8"), headers=headers, timeout=15)
    response.raise_for_status()
    
    # SOAP zarfından JSON string'i çek
    root = ET.fromstring(response.content)
    ns = {
        "soap": "http://schemas.xmlsoap.org/soap/envelope/",
        "tns": "http://tempuri.org/"
    }
    result_node = root.find(".//tns:GetHatOtoKonum_jsonResult", ns)
    
    if result_node is None or not result_node.text:
        return []
    
    # ASP.NET bazen JSON'u HTML-encode ediyor (&quot; vs.) — unescape gerekebilir
    raw_json = unescape(result_node.text)
    return json.loads(raw_json)


def metrobus_anlik_filo() -> list[dict]:
    """Tüm Metrobüs hatlarındaki araçları topla, duplicate'leri temizle."""
    tum_araclar = {}  # kapino → en son veri
    
    for hat in METROBUS_HATLARI:
        try:
            araclar = get_hat_konumlari(hat)
            print(f"  {hat}: {len(araclar)} araç")
            for arac in araclar:
                kapino = arac.get("kapino")
                if kapino:
                    tum_araclar[kapino] = arac
        except Exception as e:
            print(f"  {hat}: HATA — {e}")
    
    return list(tum_araclar.values())


if __name__ == "__main__":
    print("Metrobüs filosu çekiliyor...")
    filo = metrobus_anlik_filo()
    print(f"\nToplam tekil araç: {len(filo)}")
    
    if filo:
        print("\nÖrnek araç:")
        print(json.dumps(filo[0], indent=2, ensure_ascii=False))
        
        print("\nİlk 5 aracın özeti:")
        for arac in filo[:5]:
            print(f"  Kapı: {arac.get('kapino')} | "
                  f"Hat: {arac.get('hatkodu')} | "
                  f"Yön: {arac.get('yon')} | "
                  f"Konum: ({arac.get('enlem')}, {arac.get('boylam')}) | "
                  f"Son güncelleme: {arac.get('son_konum_zamani')}")