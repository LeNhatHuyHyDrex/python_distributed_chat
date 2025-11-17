# server/server_main.py
import socket
import threading
import json
import hashlib
import os
import base64
from pathlib import Path  
from common.config import SERVER_HOST, SERVER_PORT
from server.db_access import (
    create_user,
    get_user_by_username,
    get_or_create_private_conversation,
    insert_message,
    get_messages_for_conversation,
    delete_message_for_user,
    get_message_by_id,              # 👈 THÊM DÒNG NÀY
    get_conversations_for_user,
    search_users,
    delete_conversation_for_users,
    update_user_avatar,
)

# ====== STORAGE FOLDERS ======
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
IMAGES_DIR = STORAGE_DIR / "images"
VIDEOS_DIR = STORAGE_DIR / "videos"
FILES_DIR = STORAGE_DIR / "files"

for d in (IMAGES_DIR, VIDEOS_DIR, FILES_DIR):
    d.mkdir(parents=True, exist_ok=True)


# mapping: username -> socket
clients: dict[str, socket.socket] = {}

MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2MB sau khi decode


def hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_to_conn(conn: socket.socket, action: str, data: dict):
    """Gửi 1 gói JSON + xuống dòng để client readline() được."""
    try:
        text = json.dumps({"action": action, "data": data}, ensure_ascii=False)
        conn.sendall((text + "\n").encode("utf-8"))
    except Exception as e:
        print(f"[SERVER] Không gửi được tới client (socket chết): {e}")
        # Không raise, tránh làm hỏng thread server


def handle_client(conn: socket.socket, addr):
    print(f"[+] New connection from {addr}")
    file = conn.makefile("r", encoding="utf-8")

    username: str | None = None  # username đã login trên connection này

    try:
        while True:
            line = file.readline()
            if not line:
                break

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            data = msg.get("data") or {}

            # ========== AUTH ==========

            if action == "register":
                username_try = data.get("username")
                password = data.get("password")
                display_name = data.get("display_name") or username_try

                if get_user_by_username(username_try):
                    send_to_conn(conn, "register_result", {
                        "ok": False,
                        "error": "Username already exists",
                    })
                    continue

                pw_hash = hash_password(password)
                create_user(username_try, pw_hash, display_name)
                send_to_conn(conn, "register_result", {"ok": True})

            elif action == "login":
                username_try = data.get("username")
                password = data.get("password")
                user = get_user_by_username(username_try)
                if not user:
                    send_to_conn(conn, "login_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                pw_hash = hash_password(password)
                if user["password_hash"] != pw_hash:
                    send_to_conn(conn, "login_result", {
                        "ok": False,
                        "error": "Wrong password",
                    })
                    continue

                username = user["username"]
                clients[username] = conn

                avatar_b64 = user.get("avatar_url")

                send_to_conn(conn, "login_result", {
                    "ok": True,
                    "user_id": user["id"],
                    "display_name": user["display_name"],
                    "avatar_b64": avatar_b64,
                })
                print(f"[+] {username} logged in")

            elif action == "logout":
                by_username = data.get("username")
                if by_username in clients and clients[by_username] is conn:
                    del clients[by_username]
                if username == by_username:
                    username = None
                send_to_conn(conn, "logout_result", {"ok": True})
                print(f"[+] {by_username} logged out")

            # ========== CHAT TEXT & HISTORY ==========

            elif action == "send_text":
                from_username = data.get("from")
                to_username = data.get("to")
                content = data.get("content")

                user_from = get_user_by_username(from_username)
                user_to = get_user_by_username(to_username)
                if not user_from or not user_to:
                    send_to_conn(conn, "send_text_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                conv_id = get_or_create_private_conversation(
                    user_from["id"], user_to["id"]
                )
                msg_id = insert_message(conv_id, user_from["id"], "text", content)

                # Gửi cho người nhận nếu đang online
                if to_username in clients:
                    send_to_conn(clients[to_username], "incoming_text", {
                        "from": from_username,
                        "content": content,
                        "message_id": msg_id,
                    })

                # Xác nhận cho người gửi
                send_to_conn(conn, "send_text_result", {
                    "ok": True,
                    "to": to_username,
                    "content": content,
                    "message_id": msg_id,
                })

            elif action == "send_image":
                sender = data.get("from")
                receiver = data.get("to")
                filename = data.get("filename")
                b64data = data.get("data")

                user = get_user_by_username(sender)
                partner = get_user_by_username(receiver)

                if not user or not partner:
                    send_to_conn(conn, "send_image_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                # Giải mã base64 thành bytes
                try:
                    raw = base64.b64decode(b64data)
                except Exception:
                    send_to_conn(conn, "send_image_result", {
                        "ok": False,
                        "error": "Sai base64",
                    })
                    continue

                # Lưu file vào server/storage/images
                safe_name = f"{user['id']}_{partner['id']}_{filename}"
                full_path = IMAGES_DIR / safe_name

                try:
                    with open(full_path, "wb") as f:
                        f.write(raw)
                except Exception as e:
                    send_to_conn(conn, "send_image_result", {
                        "ok": False,
                        "error": str(e),
                    })
                    continue

                # Lưu vào bảng messages: CHỈ LƯU TÊN FILE, KHÔNG LƯU BASE64
                conv_id = get_or_create_private_conversation(user["id"], partner["id"])
                msg_id = insert_message(
                    conversation_id=conv_id,
                    sender_id=user["id"],
                    msg_type="image",
                    content=safe_name,   # 👈 chỉ tên file
                )

                # Phản hồi cho người gửi
                send_to_conn(conn, "send_image_result", {
                    "ok": True,
                    "message_id": msg_id,
                    "to": receiver,
                    "filename": safe_name,
                })

                # Gửi realtime cho người nhận
                if receiver in clients:
                    send_to_conn(clients[receiver], "incoming_image", {
                        "from": sender,
                        "filename": safe_name,
                        "message_id": msg_id,
                    })
            elif action == "send_file_result":
                if data.get("ok"):
                    to_user = data.get("to")
                    filename = data.get("filename")
                    file_type = (data.get("file_type") or "file").lower()
                    msg_id = data.get("message_id")

                    base = Path(__file__).resolve().parents[1] / "server" / "storage"

                    if file_type == "video":
                        fpath = base / "videos" / filename
                        self.chat_list.add_video_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )
                    elif file_type == "image":
                        fpath = base / "images" / filename
                        self.chat_list.add_image_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )
                    else:
                        fpath = base / "files" / filename
                        self.chat_list.add_file_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )

                    self.request_conversations()
                else:
                    self.lbl_chat_status.setText(
                        "❌ Gửi file thất bại: " + str(data.get("error"))
                    )

            elif action == "incoming_file":
                sender = data.get("from")
                filename = data.get("filename")
                file_type = data.get("file_type")
                msg_id = data.get("message_id")

                base = Path(__file__).resolve().parents[1] / "server" / "storage"

                if file_type == "image":
                    fpath = base / "images" / filename
                    self.chat_list.add_image_bubble(
                        msg_id, sender, self.current_username, str(fpath)
                    )

                elif file_type == "video":
                    fpath = base / "videos" / filename
                    self.chat_list.add_video_bubble(
                        msg_id, sender, self.current_username, str(fpath)
                    )

                else:
                    fpath = base / "files" / filename
                    self.chat_list.add_file_bubble(
                        msg_id, sender, self.current_username, str(fpath)
                    )


            elif action == "broadcast":
                msg_text = data.get("message", "")
                for uname, c in list(clients.items()):
                    send_to_conn(c, "server_broadcast", {
                        "message": msg_text,
                    })
            elif action == "send_file":
                from_username = data.get("from")
                to_username = data.get("to")
                filename = data.get("filename")
                b64data = data.get("data")
                file_type = (data.get("file_type") or "file").lower()

                user_from = get_user_by_username(from_username)
                user_to = get_user_by_username(to_username)
                if not user_from or not user_to:
                    send_to_conn(conn, "send_file_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                # Giải mã base64
                try:
                    raw = base64.b64decode(b64data)
                except Exception:
                    send_to_conn(conn, "send_file_result", {
                        "ok": False,
                        "error": "Invalid base64 data",
                    })
                    continue

                # Chọn thư mục & msg_type
                if file_type == "video":
                    folder = VIDEOS_DIR
                    msg_type = "video"
                elif file_type == "image":
                    folder = IMAGES_DIR
                    msg_type = "image"
                else:
                    folder = FILES_DIR
                    msg_type = "file"

                safe_name = f"{user_from['id']}_{user_to['id']}_{filename}"
                full_path = folder / safe_name

                try:
                    with open(full_path, "wb") as f:
                        f.write(raw)
                except Exception as e:
                    send_to_conn(conn, "send_file_result", {
                        "ok": False,
                        "error": str(e),
                    })
                    continue

                conv_id = get_or_create_private_conversation(
                    user_from["id"], user_to["id"]
                )
                msg_id = insert_message(conv_id, user_from["id"], msg_type, safe_name)

                # Gửi confirm cho người gửi
                send_to_conn(conn, "send_file_result", {
                    "ok": True,
                    "to": to_username,
                    "filename": safe_name,
                    "file_type": file_type,
                    "message_id": msg_id,
                })

                # Gửi realtime cho người nhận (nếu online)
                if to_username in clients:
                    send_to_conn(clients[to_username], "incoming_file", {
                        "from": from_username,
                        "filename": safe_name,
                        "file_type": file_type,
                        "message_id": msg_id,
                    })

            elif action == "load_history":
                from_username = data.get("from")
                to_username = data.get("to")

                user_from = get_user_by_username(from_username)
                user_to = get_user_by_username(to_username)
                if not user_from or not user_to:
                    send_to_conn(conn, "history_result", {
                        "ok": False,
                        "error": "User not found",
                        "messages": [],
                    })
                    continue

                conv_id = get_or_create_private_conversation(
                    user_from["id"], user_to["id"]
                )
                rows = get_messages_for_conversation(conv_id, limit=200)
                msgs = []
                for r in rows:
                    created_at = r.get("created_at")
                    if hasattr(created_at, "isoformat"):
                        created_at = created_at.isoformat(sep=" ", timespec="seconds")
                    else:
                        created_at = str(created_at)
                    msgs.append({
                        "id": r["id"],
                        "sender_username": r["sender_username"],
                        "msg_type": r.get("msg_type") or "text",
                        "content": r["content"],
                        "created_at": created_at,
                    })

                send_to_conn(conn, "history_result", {
                    "ok": True,
                    "with": to_username,
                    "messages": msgs,
                })


            elif action == "delete_message":
                by_username = data.get("by")
                partner_username = data.get("partner")
                message_id = data.get("message_id")

                user_by = get_user_by_username(by_username)
                user_partner = (
                    get_user_by_username(partner_username)
                    if partner_username
                    else None
                )

                if not user_by or not user_partner:
                    send_to_conn(conn, "delete_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                try:
                    message_id_int = int(message_id)
                except (TypeError, ValueError):
                    send_to_conn(conn, "delete_result", {
                        "ok": False,
                        "error": "Invalid message id",
                    })
                    continue

                # Tìm conversation + lấy thông tin tin nhắn trước khi xóa
                conv_id = get_or_create_private_conversation(
                    user_by["id"], user_partner["id"]
                )
                msg_row = get_message_by_id(conv_id, message_id_int)

                deleted = delete_message_for_user(
                    conv_id, message_id_int, user_by["id"]
                )

                if deleted:
                    # Nếu là image/video/file thì xóa luôn file trên ổ
                    if msg_row:
                        msg_type = (msg_row.get("msg_type") or "").lower()
                        content = msg_row.get("content") or ""

                        dir_path = None
                        if msg_type == "image":
                            dir_path = IMAGES_DIR
                        elif msg_type == "video":
                            dir_path = VIDEOS_DIR
                        elif msg_type in ("file", "document"):
                            dir_path = FILES_DIR

                        if dir_path and content:
                            file_path = dir_path / content
                            try:
                                import os
                                os.remove(file_path)
                                print(f"[SERVER] Đã xóa file: {file_path}")
                            except FileNotFoundError:
                                # File không còn cũng không sao
                                pass
                            except Exception as e:
                                print(f"[SERVER] Không xóa được file {file_path}: {e}")

                    send_to_conn(conn, "delete_result", {
                        "ok": True,
                        "message_id": message_id_int,
                    })
                else:
                    send_to_conn(conn, "delete_result", {
                        "ok": False,
                        "error": "Message not found or not owner",
                    })

            # ========== CONVERSATION LIST & SEARCH ==========

            elif action == "list_conversations":
                username_req = data.get("username")
                user = get_user_by_username(username_req)
                if not user:
                    send_to_conn(conn, "conversations_result", {
                        "ok": False,
                        "error": "User not found",
                        "items": [],
                    })
                    continue

                raw_items = get_conversations_for_user(user["id"])
                items: list[dict] = []
                for it in raw_items:
                    avatar_b64 = it.get("partner_avatar_url")
                    items.append(
                        {
                            "conversation_id": it["conversation_id"],
                            "partner_username": it["partner_username"],
                            "partner_display_name": it.get("partner_display_name"),
                            "last_time": it.get("last_time"),
                            "avatar_b64": avatar_b64,
                        }
                    )

                send_to_conn(conn, "conversations_result", {
                    "ok": True,
                    "items": items,
                })

            elif action == "search_users":
                q = (data.get("query") or "").strip()
                exclude = (data.get("exclude_username") or "").strip()
                if not q:
                    send_to_conn(conn, "search_users_result", {
                        "ok": True,
                        "items": [],
                    })
                    continue

                rows = search_users(q, limit=20)
                items: list[dict] = []
                for r in rows:
                    uname = r.get("username")
                    if not uname:
                        continue
                    if exclude and uname == exclude:
                        continue
                    items.append({
                        "username": uname,
                        "display_name": r.get("display_name"),
                    })

                send_to_conn(conn, "search_users_result", {
                    "ok": True,
                    "items": items,
                })

            elif action == "delete_conversation":
                by_username = (data.get("by") or "").strip()
                partner_username = (data.get("partner") or "").strip()

                user_by = get_user_by_username(by_username)
                user_partner = get_user_by_username(partner_username)

                if not user_by or not user_partner:
                    send_to_conn(conn, "delete_conversation_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                deleted = delete_conversation_for_users(
                    user_by["id"], user_partner["id"]
                )
                if deleted:
                    send_to_conn(conn, "delete_conversation_result", {
                        "ok": True,
                        "partner": partner_username,
                    })
                else:
                    send_to_conn(conn, "delete_conversation_result", {
                        "ok": False,
                        "error": "Conversation not found",
                    })

            # ========== AVATAR (avatar_url = base64) ==========

            elif action == "update_avatar":
                uname = (data.get("username") or "").strip()
                img_b64 = data.get("image_b64") or ""

                user = get_user_by_username(uname)
                if not user:
                    send_to_conn(conn, "update_avatar_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                try:
                    raw = base64.b64decode(img_b64)
                except Exception:
                    send_to_conn(conn, "update_avatar_result", {
                        "ok": False,
                        "error": "Invalid image data",
                    })
                    continue

                if len(raw) > MAX_AVATAR_BYTES:
                    send_to_conn(conn, "update_avatar_result", {
                        "ok": False,
                        "error": "Image too large (>2MB)",
                    })
                    continue

                update_user_avatar(user["id"], img_b64)

                send_to_conn(conn, "update_avatar_result", {
                    "ok": True,
                    "avatar_b64": img_b64,
                })

                for uname_online, c_online in list(clients.items()):
                    send_to_conn(c_online, "avatar_changed", {
                        "username": user["username"],
                        "avatar_b64": img_b64,
                    })

            elif action == "list_attachments":
                username_req = data.get("username")
                partner_username = data.get("partner")
                filter_kind = (data.get("filter") or "media").lower()

                user = get_user_by_username(username_req)
                partner = get_user_by_username(partner_username)

                if not user or not partner:
                    send_to_conn(conn, "attachments_result", {
                        "ok": False,
                        "error": "User not found"
                    })
                    continue

                conv_id = get_or_create_private_conversation(
                    user["id"], partner["id"]
                )

                msgs = get_messages_for_conversation(conv_id, limit=1000) or []

                def is_match(m):
                    t = (m.get("msg_type") or "text").lower()
                    c = (m.get("content") or "")
                    if filter_kind == "media":
                        return t in ("image", "photo", "video", "audio")
                    elif filter_kind == "files":
                        return t in ("file", "document")
                    elif filter_kind == "links":
                        if t == "link":
                            return True
                        cl = c.lower()
                        return "http://" in cl or "https://" in cl
                    return False

                items = []
                for m in msgs:
                    if not is_match(m):
                        continue
                    created_at = m.get("created_at")
                    if hasattr(created_at, "isoformat"):
                        created_str = created_at.isoformat(
                            sep=" ", timespec="seconds"
                        )
                    else:
                        created_str = str(created_at) if created_at is not None else ""
                    items.append({
                        "id": m.get("id"),
                        "msg_type": m.get("msg_type"),
                        "content": m.get("content"),
                        "created_at": created_str,
                    })

                send_to_conn(conn, "attachments_result", {
                    "ok": True,
                    "filter": filter_kind,
                    "partner": partner_username,
                    "items": items,
                })

    except Exception as e:
        print("Error while handling client:", e)
    finally:
        if username and username in clients and clients[username] is conn:
            del clients[username]
        try:
            conn.close()
        except OSError:
            pass
        print(f"[-] Connection closed: {addr}")


def main():
    print(f"[SERVER] Listening on {SERVER_HOST}:{SERVER_PORT}")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((SERVER_HOST, SERVER_PORT))
    srv.listen(10)

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            )
            t.start()
    finally:
        srv.close()


if __name__ == "__main__":
    main()
