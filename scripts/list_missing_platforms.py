import re, json

with open(r'c:\Users\ogulcan\Desktop\metrobus\packages\shared\src\constants\station-slots.ts', 'r', encoding='utf-8') as f:
    text = f.read()

m = re.search(r'STATION_SLOTS.*?=\s*(\[.*\]);', text, re.DOTALL)
data = json.loads(m.group(1))

print("Stations needing measurement (0m or <=7m):")
print()
for s in data:
    if s['platformLengthMeters'] <= 7:
        lat = s['stopPositions'][0]['lat']
        lon = s['stopPositions'][0]['lon']
        print(f"  {s['name']}")
        print(f"    Coordinate: {lat},{lon}")
        print(f"    Google Maps: https://www.google.com/maps/@{lat},{lon},19z/data=!3m1!1e1")
        print(f"    Platform: {s['platformLengthMeters']}m  Slots: {s['slotCount']}")
        print()
