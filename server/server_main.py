# server/server_main.py
import socket
import threading
import json
import hashlib
import os
import base64
from pathlib import Path  
from common.config import SERVER_HOST, SERVER_PORT, select_node_for_conversation
from server.db_access import (
    create_user,
    get_user_by_username,
    get_or_create_private_conversation,
    insert_message,
    get_messages_for_conversation,
    delete_message_for_user,
    get_message_by_id,
    get_conversations_for_user,
    search_users,
    delete_conversation_for_users,
    update_user_avatar,
    create_group_conversation,
    get_groups_for_user,
    is_user_in_conversation,
    get_members_of_conversation,
    add_user_to_conversation,
    remove_user_from_conversation,
    find_group_by_name,
    update_group_avatar,
    # thêm hai hàm dưới đây để xóa nhóm & lấy thành viên trước khi thông báo
    delete_group,
    get_conversation_owner,
)



# ====== STORAGE FOLDERS ======
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
IMAGES_DIR = STORAGE_DIR / "images"
VIDEOS_DIR = STORAGE_DIR / "videos"
FILES_DIR = STORAGE_DIR / "files"
GROUP_AVATAR_DIR = STORAGE_DIR / "group_avatars"
GROUP_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
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

            elif action == "load_group_history":
                conv_id = int(data.get("conversation_id") or 0)
                username_req = (data.get("username") or "").strip()

                user = get_user_by_username(username_req)
                if not user:
                    send_to_conn(conn, "group_history_result", {
                        "ok": False,
                        "error": "User not found",
                        "conversation_id": conv_id,
                        "messages": [],
                    })
                    continue

                # kiểm tra user có trong group không
                if not is_user_in_conversation(conv_id, user["id"]):
                    send_to_conn(conn, "group_history_result", {
                        "ok": False,
                        "error": "Bạn không thuộc nhóm này",
                        "conversation_id": conv_id,
                        "messages": [],
                    })
                    continue

                rows = get_messages_for_conversation(conv_id, limit=200)
                msgs = []
                for r in rows:
                    created_at = r.get("created_at")
                    if hasattr(created_at, "isoformat"):
                        created_at = created_at.isoformat(
                            sep=" ", timespec="seconds"
                        )
                    else:
                        created_at = str(created_at)
                    msgs.append({
                        "id": r["id"],
                        "sender_username": r["sender_username"],
                        "msg_type": r.get("msg_type") or "text",
                        "content": r["content"],
                        "created_at": created_at,
                    })

                # --- xác định owner của nhóm để trả về cho client ---
                try:
                    owner_id = get_conversation_owner(conv_id)
                except Exception:
                    owner_id = None
                is_owner = (owner_id is not None and owner_id == user["id"])

                send_to_conn(conn, "group_history_result", {
                    "ok": True,
                    "conversation_id": conv_id,
                    "messages": msgs,
                    "is_owner": is_owner,
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

                raw_privates = get_conversations_for_user(user["id"])
                raw_groups = get_groups_for_user(user["id"])

                items: list[dict] = []

                # --- Các đoạn 1-1 ---
                for it in raw_privates:
                    avatar_b64 = it.get("partner_avatar_url")
                    items.append(
                        {
                            "conversation_id": it["conversation_id"],
                            "is_group": 0,
                            "partner_username": it["partner_username"],
                            "title": it.get("partner_display_name") or it["partner_username"],
                            "last_time": it.get("last_time"),
                            "avatar_b64": avatar_b64,
                        }
                    )

                # --- Các group ---
                # groups
                for g in raw_groups:
                    avatar_b64 = g.get("group_avatar")
                    items.append(
                        {
                            "conversation_id": g["conversation_id"],
                            "is_group": 1,
                            "partner_username": None,
                            "title": f"[Group] {g['group_name']}",
                            "last_time": g.get("last_time"),
                            "avatar_b64": avatar_b64,
                        }
                    )


                # sort theo last_time (mới nhất đưa lên trên)
                items.sort(
                    key=lambda x: (x["last_time"] is None, x["last_time"]),
                    reverse=True,
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
            elif action == "update_group_avatar":
                conv_id = int(data.get("conversation_id") or 0)
                img_b64 = (data.get("image_b64") or "").strip()

                if not conv_id or not img_b64:
                    send_to_conn(conn, "update_group_avatar_result", {
                        "ok": False,
                        "error": "Thiếu dữ liệu",
                    })
                    continue

                try:
                    update_group_avatar(conv_id, img_b64)
                except Exception as e:
                    print("update_group_avatar error:", e)
                    send_to_conn(conn, "update_group_avatar_result", {
                        "ok": False,
                        "error": str(e),
                    })
                    continue

                send_to_conn(conn, "update_group_avatar_result", {
                    "ok": True,
                    "conversation_id": conv_id,
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
            elif action == "create_group":
                owner_username = (data.get("owner") or "").strip()
                group_name = (data.get("name") or "").strip()
                member_usernames = data.get("members") or []  # list[str]

                owner = get_user_by_username(owner_username)
                if not owner:
                    send_to_conn(conn, "create_group_result", {
                        "ok": False,
                        "error": "Owner not found",
                    })
                    continue

                # đảm bảo owner luôn trong nhóm
                all_usernames = set(member_usernames)
                all_usernames.add(owner_username)

                member_ids = []
                for uname in all_usernames:
                    u = get_user_by_username(uname)
                    if not u:
                        send_to_conn(conn, "create_group_result", {
                            "ok": False,
                            "error": f"User not found: {uname}",
                        })
                        break
                    member_ids.append(u["id"])
                else:
                    # nếu không break
                    conv_id = create_group_conversation(group_name, owner["id"], member_ids)


                    # thông báo cho tất cả member đang online
                    for uname in all_usernames:
                        if uname in clients:
                            send_to_conn(clients[uname], "group_created", {
                                "ok": True,
                                "conversation_id": conv_id,
                                "group_name": group_name,
                            })

                    # trả về cho thằng tạo
                    send_to_conn(conn, "create_group_result", {
                        "ok": True,
                        "conversation_id": conv_id,
                        "group_name": group_name,
                    })
            elif action == "send_group_text":
                from_username = data.get("from")
                conv_id = int(data.get("conversation_id") or 0)
                content = data.get("content") or ""

                user_from = get_user_by_username(from_username)
                if not user_from:
                    send_to_conn(conn, "send_group_text_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                # check có trong group không
                if not is_user_in_conversation(conv_id, user_from["id"]):
                    send_to_conn(conn, "send_group_text_result", {
                        "ok": False,
                        "error": "You are not in this group",
                    })
                    continue

                msg_id = insert_message(conv_id, user_from["id"], "text", content)

                members = get_members_of_conversation(conv_id)
                for m in members:
                    uname = m["username"]
                    # không gửi lại cho chính mình
                    if uname in clients and uname != from_username:
                        send_to_conn(clients[uname], "incoming_group_text", {
                            "conversation_id": conv_id,
                            "from": from_username,
                            "content": content,
                            "message_id": msg_id,
                        })

                send_to_conn(conn, "send_group_text_result", {
                    "ok": True,
                    "conversation_id": conv_id,
                    "content": content,
                    "message_id": msg_id,
                })
            elif action == "add_group_member":
                by_username = (data.get("by") or "").strip()
                conv_id = int(data.get("conversation_id") or 0)
                target_username = (data.get("username") or "").strip()

                requester = get_user_by_username(by_username)
                target = get_user_by_username(target_username)

                if not requester or not target:
                    send_to_conn(conn, "add_group_member_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                if not is_user_in_conversation(conv_id, requester["id"]):
                    send_to_conn(conn, "add_group_member_result", {
                        "ok": False,
                        "error": "Bạn không thuộc nhóm này",
                    })
                    continue

                if is_user_in_conversation(conv_id, target["id"]):
                    send_to_conn(conn, "add_group_member_result", {
                        "ok": False,
                        "error": "User đã ở trong nhóm",
                    })
                    continue

                added = add_user_to_conversation(conv_id, target["id"])
                if added:
                    # thông báo cho người được thêm nếu đang online
                    if target_username in clients:
                        send_to_conn(clients[target_username], "group_created", {
                            "ok": True,
                            "conversation_id": conv_id,
                            "group_name": f"{conv_id}",
                        })
                    send_to_conn(conn, "add_group_member_result", {
                        "ok": True,
                        "conversation_id": conv_id,
                        "username": target_username,
                    })
                else:
                    send_to_conn(conn, "add_group_member_result", {
                        "ok": False,
                        "error": "Không thêm được user vào nhóm",
                    })

            elif action == "leave_group":
                by_username = (data.get("by") or "").strip()
                conv_id = int(data.get("conversation_id") or 0)

                user_by = get_user_by_username(by_username)
                if not user_by:
                    send_to_conn(conn, "leave_group_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                if not is_user_in_conversation(conv_id, user_by["id"]):
                    send_to_conn(conn, "leave_group_result", {
                        "ok": False,
                        "error": "Bạn không thuộc nhóm này",
                    })
                    continue

                members = get_members_of_conversation(conv_id) or []
                if members:
                    owner_id = members[0]["id"]   # tạm coi member có id nhỏ nhất là chủ nhóm
                    if user_by["id"] == owner_id:
                        send_to_conn(conn, "leave_group_result", {
                            "ok": False,
                            "error": "Người tạo nhóm không được rời nhóm.",
                        })
                        continue

                removed = remove_user_from_conversation(conv_id, user_by["id"])
                if removed:
                    send_to_conn(conn, "leave_group_result", {
                        "ok": True,
                        "conversation_id": conv_id,
                    })
                else:
                    send_to_conn(conn, "leave_group_result", {
                        "ok": False,
                        "error": "Không rời nhóm được",
                    })

            elif action == "join_group_by_name":
                username_req = (data.get("username") or "").strip()
                group_name = (data.get("name") or "").strip()

                user = get_user_by_username(username_req)
                if not user:
                    send_to_conn(conn, "join_group_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                group = find_group_by_name(group_name)
                if not group:
                    send_to_conn(conn, "join_group_result", {
                        "ok": False,
                        "error": "Không tìm thấy nhóm",
                    })
                    continue

                conv_id = group["id"]
                if not is_user_in_conversation(conv_id, user["id"]):
                    add_user_to_conversation(conv_id, user["id"])

                send_to_conn(conn, "join_group_result", {
                    "ok": True,
                    "conversation_id": conv_id,
                    "group_name": group["name"],
                })

            # ----- Xóa nhóm (chỉ owner được phép) -----
            elif action == "delete_group":
                conv_id_raw = data.get("conversation_id")
                by_username = (data.get("by") or "").strip()

                try:
                    conv_id = int(conv_id_raw)
                except (TypeError, ValueError):
                    send_to_conn(conn, "delete_group_result", {
                        "ok": False,
                        "error": "Invalid conversation id",
                    })
                    continue

                user_by = get_user_by_username(by_username)
                if not user_by:
                    send_to_conn(conn, "delete_group_result", {
                        "ok": False,
                        "error": "User not found",
                    })
                    continue

                # Lấy danh sách members (username) trước khi xóa để gửi thông báo
                try:
                    members = get_members_of_conversation(conv_id) or []
                except Exception:
                    members = []

                try:
                    deleted = delete_group(conv_id, user_by["id"])
                except Exception as e:
                    print(f"[SERVER] delete_group error: {e}")
                    deleted = False

                if deleted:
                    # Trả kết quả cho requester
                    send_to_conn(conn, "delete_group_result", {
                        "ok": True,
                        "conversation_id": conv_id,
                    })

                    # Thông báo tới tất cả thành viên online để họ refresh sidebar / clear UI
                    for m in members:
                        uname = m.get("username") or m.get("user_id")  # đảm bảo lấy username nếu có
                        if not isinstance(uname, str):
                            continue
                        if uname in clients:
                            try:
                                send_to_conn(clients[uname], "group_deleted", {
                                    "conversation_id": conv_id,
                                })
                            except Exception:
                                pass
                else:
                    send_to_conn(conn, "delete_group_result", {
                        "ok": False,
                        "error": "Group not found or not owner",
                    })

            # sau này thêm: gửi file, hình ảnh, nhóm, voice, video...

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
