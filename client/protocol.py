# client/protocol.py

import json


def make_packet(action: str, data: dict) -> bytes:
    """
    Đóng gói message: {"action": "...", "data": {...}}
    -> JSON + '\n'
    """
    obj = {
        "action": action,
        "data": data or {}
    }
    text = json.dumps(obj, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def parse_packet(line: str) -> dict:
    """
    Parse 1 dòng JSON từ server.
    """
    return json.loads(line)
