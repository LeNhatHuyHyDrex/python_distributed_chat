# client/client_main.py

import socket
import threading
import json

from common.config import SERVER_HOST, SERVER_PORT
from client.protocol import make_packet, parse_packet


def listen_thread(sock: socket.socket):
    file = sock.makefile("r", encoding="utf-8")
    try:
        while True:
            line = file.readline()
            if not line:
                break
            msg = json.loads(line)
            action = msg.get("action")
            data = msg.get("data") or {}

            if action == "register_result":
                if data.get("ok"):
                    print("[+] Đăng ký thành công")
                else:
                    print("[!] Đăng ký thất bại:", data.get("error"))

            elif action == "login_result":
                if data.get("ok"):
                    print("[+] Đăng nhập thành công. Xin chào",
                          data.get("display_name"))
                else:
                    print("[!] Đăng nhập thất bại:", data.get("error"))

            elif action == "incoming_text":
                print(f"\n💬 Tin nhắn từ {data.get('from')}: {data.get('content')}")
            elif action == "server_broadcast":
                print(f"\n[THÔNG BÁO SERVER]: {data.get('message')}")
            elif action == "send_text_result":
                if data.get("ok"):
                    print(f"[Me -> {data.get('to')}] {data.get('content')}")
    except Exception as e:
        print("Lỗi listener:", e)
    finally:
        sock.close()


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_HOST, SERVER_PORT))
    print("[CLIENT] Kết nối server thành công")

    t = threading.Thread(target=listen_thread, args=(sock,), daemon=True)
    t.start()

    username = None

    # Menu đơn giản
    while True:
        if not username:
            print("\n1) Đăng ký")
            print("2) Đăng nhập")
            print("0) Thoát")
            choice = input("Chọn: ").strip()
            if choice == "1":
                u = input("Username: ")
                p = input("Password: ")
                d = input("Display name: ")
                pkt = make_packet("register", {
                    "username": u,
                    "password": p,
                    "display_name": d
                })
                sock.sendall(pkt)
            elif choice == "2":
                u = input("Username: ")
                p = input("Password: ")
                username = u
                pkt = make_packet("login", {
                    "username": u,
                    "password": p
                })
                sock.sendall(pkt)
            elif choice == "0":
                break
            else:
                continue
        else:
            print("\n3) Gửi tin nhắn tới user khác")
            print("4) Nhận thông báo broadcast từ server (server sẽ tự gửi)")
            print("9) Đăng xuất")
            print("0) Thoát")
            choice = input("Chọn: ").strip()
            if choice == "3":
                to_user = input("Gửi tới (username): ")
                content = input("Nội dung: ")
                pkt = make_packet("send_text", {
                    "from": username,
                    "to": to_user,
                    "content": content
                })
                sock.sendall(pkt)
            elif choice == "9":
                username = None
            elif choice == "0":
                break

    sock.close()


if __name__ == "__main__":
    main()
