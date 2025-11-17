# client/network.py

import socket
import json
from PyQt6.QtCore import QThread, pyqtSignal


class NetworkThread(QThread):
    received = pyqtSignal(dict)

    def __init__(self, sock: socket.socket):
        super().__init__()
        self.sock = sock
        self._running = True

    def run(self):
        try:
            file = self.sock.makefile("r", encoding="utf-8")
            while self._running:
                line = file.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.received.emit(msg)
        except Exception as e:
            print("NetworkThread error:", e)
        finally:
            try:
                self.sock.close()
            except OSError:
                pass

    def stop(self):
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass


def make_packet(action: str, data: dict) -> bytes:
    obj = {
        "action": action,
        "data": data or {}
    }
    text = json.dumps(obj, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
