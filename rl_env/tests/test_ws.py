"""Listen to WS bridge and print vehicle data."""
import asyncio
import websockets
import json

async def listen():
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            print("Connected!")
            for i in range(10):
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)
                vehicles = data.get("vehicles", [])
                phases = {}
                for v in vehicles:
                    phases[v["phase"]] = phases.get(v["phase"], 0) + 1
                speeds = [v["speed"] for v in vehicles]
                avg_speed = sum(speeds) / len(speeds) if speeds else 0
                metrics = data.get("metrics", {})
                print(f"Msg {i}: phases={phases} avg_speed={avg_speed:.2f} m/s iter={metrics.get('iteration',0)} step={metrics.get('step',0)}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(listen())
