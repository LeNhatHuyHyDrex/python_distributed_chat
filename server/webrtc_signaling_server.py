import asyncio
import json
import websockets
from websockets.server import WebSocketServerProtocol

# room_id -> { ws: user_id }
ROOMS: dict[str, dict[WebSocketServerProtocol, str]] = {}


async def broadcast(room_id: str, message: dict, exclude: WebSocketServerProtocol | None = None):
    """Gửi message JSON tới tất cả client trong room (trừ exclude nếu có)."""
    if room_id not in ROOMS:
        return
    dead: list[WebSocketServerProtocol] = []
    data = json.dumps(message)
    for ws in ROOMS[room_id].keys():
        if exclude is not None and ws is exclude:
            continue
        try:
            await ws.send(data)
        except Exception:
            dead.append(ws)

    # dọn kết nối chết
    for ws in dead:
        ROOMS[room_id].pop(ws, None)
    if not ROOMS[room_id]:
        ROOMS.pop(room_id, None)


async def handler(ws: WebSocketServerProtocol):
    """
    Mỗi client WebRTC sẽ:
      1) Gửi: {"type":"join", "room":"room_id", "userId":"..."}
      2) Sau đó gửi các message:
         - offer / answer / candidate / leave ...
         Server sẽ forward cho các client khác trong cùng room.
    """
    room_id = None
    user_id = None
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print("⚠️  Received non-JSON message, ignore")
                continue

            mtype = msg.get("type")
            if mtype == "join":
                room_id = str(msg.get("room") or "")
                user_id = str(msg.get("userId") or "")

                if not room_id or not user_id:
                    await ws.send(json.dumps({
                        "type": "error",
                        "reason": "Missing room or userId"
                    }))
                    continue

                print(f"[JOIN] user={user_id} joined room={room_id}")
                ROOMS.setdefault(room_id, {})[ws] = user_id

                # Gửi danh sách user hiện có trong room cho client mới
                peers = [
                    uid for w, uid in ROOMS[room_id].items()
                    if w is not ws
                ]
                await ws.send(json.dumps({
                    "type": "peers",
                    "peers": peers
                }))

                # Thông báo cho các peer khác có user mới join
                await broadcast(room_id, {
                    "type": "peer-joined",
                    "userId": user_id
                }, exclude=ws)

            elif mtype in ("offer", "answer", "candidate", "leave"):
                # Đây là các message signaling WebRTC.
                # Server chỉ forward trong cùng room cho các client khác.
                if not room_id or room_id not in ROOMS:
                    continue

                payload = {
                    "type": mtype,
                    "from": user_id,
                }

                # copy toàn bộ thông tin còn lại (sdp, candidate, target...)
                for k, v in msg.items():
                    if k not in ("type",):
                        payload[k] = v

                await broadcast(room_id, payload, exclude=ws)

            else:
                # Unknown
                await ws.send(json.dumps({
                    "type": "error",
                    "reason": f"Unknown message type: {mtype}"
                }))

    except websockets.ConnectionClosed:
        pass
    finally:
        if room_id and room_id in ROOMS and ws in ROOMS[room_id]:
            print(f"[LEAVE] user={ROOMS[room_id][ws]} left room={room_id}")
            left_user = ROOMS[room_id].pop(ws)
            if not ROOMS[room_id]:
                ROOMS.pop(room_id, None)
            else:
                # báo cho các peer còn lại
                await broadcast(room_id, {
                    "type": "peer-left",
                    "userId": left_user
                })


async def main():
    host = "0.0.0.0"
    port = 8765  # em có thể đổi nếu muốn
    print(f"[SIGNAL] WebRTC signaling server running on ws://{host}:{port}")
    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SIGNAL] Stopped.")
