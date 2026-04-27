"""
Metrobüs Canlı Takip Sunucusu
- /api/filo → anlık araç konumları (JSON)
- / → canlı harita sayfası
- Cache ile API hakkını korur
"""
import http.server
import json
import time
import os
from anlik_oto_konum import metrobus_anlik_filo

# Cache
_cache = {"data": [], "timestamp": 0, "call_count": 0}
CACHE_TTL = 60  # saniye — IETT API rate limit'e takılmamak icin

def get_filo():
    now = time.time()
    if now - _cache["timestamp"] < CACHE_TTL and _cache["data"]:
        return _cache["data"], False
    
    _cache["call_count"] += 1
    print(f"\n[API CALL #{_cache['call_count']}] Filo cekiliyor...")
    try:
        filo = metrobus_anlik_filo()
    except Exception as e:
        print(f"  HATA: {e}")
        return _cache["data"], False
    
    if filo:
        _cache["data"] = filo
        _cache["timestamp"] = now
        print(f"  -> {len(filo)} arac bulundu")
    else:
        print("  -> 0 arac! API rate-limit olabilir, cache guncellenmedi")
    
    return _cache["data"], True


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/filo":
            filo, fresh = get_filo()
            resp = json.dumps({
                "buses": filo,
                "count": len(filo),
                "cached": not fresh,
                "api_calls": _cache["call_count"],
                "timestamp": _cache["timestamp"],
            }, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp.encode("utf-8"))

        elif self.path == "/" or self.path == "/index.html":
            html_path = os.path.join(os.path.dirname(__file__), "live_map.html")
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path == "/api/duraklar":
            entries_path = os.path.join(os.path.dirname(__file__), "rl_env", "data", "platform_entries.json")
            with open(entries_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif self.path == "/api/route-geometry":
            rn_path = os.path.join(os.path.dirname(__file__), "rl_env", "data", "route_network.json")
            with open(rn_path, "r", encoding="utf-8") as f:
                rn = json.load(f)
            gidis_coords = []
            for edge in rn["edges"]["gidis"]:
                gidis_coords.extend(edge["geometry"])
            donus_coords = []
            for edge in rn["edges"]["donus"]:
                donus_coords.extend(edge["geometry"])
            resp = json.dumps({"gidis": gidis_coords, "donus": donus_coords})
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp.encode("utf-8"))

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            super().log_message(format, *args)


if __name__ == "__main__":
    PORT = 8888
    server = http.server.HTTPServer(("", PORT), Handler)
    print(f"[METROBUS] Canli Takip: http://localhost:{PORT}")
    print(f"   API endpoint: http://localhost:{PORT}/api/filo")
    print(f"   Cache TTL: {CACHE_TTL}s | Max ~14 yenileme (100 hak / 7 hat)")
    print(f"   Durdurmak icin Ctrl+C\n")
    server.serve_forever()
