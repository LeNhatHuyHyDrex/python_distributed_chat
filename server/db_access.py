# server/db_access.py

import pymysql
from common.config import DB_NODES, select_node_for_conversation


def get_connection(node_config):
    return pymysql.connect(
        host=node_config["host"],
        port=node_config["port"],
        user=node_config["user"],
        password=node_config["password"],
        database=node_config["database"],
        cursorclass=pymysql.cursors.DictCursor,
    )


# ========== USER FUNCTIONS ==========


def create_user(username: str, password_hash: str, display_name: str | None = None):
    """
    Tạo user mới.
    Bảng users: id, username, password_hash, display_name, avatar_url, created_at...
    avatar_url để NULL nên không cần set ở đây.
    """
    for node in DB_NODES:
        conn = get_connection(node)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, display_name)
                    VALUES (%s, %s, %s)
                    """,
                    (username, password_hash, display_name or username),
                )
            conn.commit()
        finally:
            conn.close()


def get_user_by_username(username: str):
    """
    Lấy thông tin user theo username.
    """
    for node in DB_NODES:
        conn = get_connection(node)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                if row:
                    return row
        finally:
            conn.close()
    return None


def search_users(keyword: str, limit: int = 20):
    """
    Tìm user theo username hoặc display_name có chứa keyword (LIKE %keyword%).
    Dùng cho thanh search ở sidebar.
    Tạm thời chỉ search trên node đầu tiên (giả định đã replicate).
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    node = DB_NODES[0]
    conn = get_connection(node)
    try:
        like = f"%{keyword}%"
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, display_name
                FROM users
                WHERE username LIKE %s OR display_name LIKE %s
                ORDER BY username ASC
                LIMIT %s
                """,
                (like, like, limit),
            )
            rows = cur.fetchall()
            return rows
    finally:
        conn.close()


def update_user_avatar(user_id: int, avatar_b64: str):
    """
    Cập nhật avatar_url = chuỗi base64 cho user.
    Ghi lên tất cả node trong cụm.
    """
    for node in DB_NODES:
        conn = get_connection(node)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET avatar_url = %s WHERE id = %s",
                    (avatar_b64, user_id),
                )
            conn.commit()
        finally:
            conn.close()


# ========== CONVERSATION & MESSAGE FUNCTIONS ==========


def _find_private_conversation(user1_id: int, user2_id: int):
    """
    Tìm conversation 1-1 giữa 2 user, KHÔNG tự tạo nếu chưa có.
    Trả về conversation_id hoặc None.
    """
    if user1_id > user2_id:
        user1_id, user2_id = user2_id, user1_id

    node = DB_NODES[0]
    conn = get_connection(node)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id
                FROM conversations c
                JOIN conversation_members m1
                    ON m1.conversation_id = c.id AND m1.user_id = %s
                JOIN conversation_members m2
                    ON m2.conversation_id = c.id AND m2.user_id = %s
                WHERE c.is_group = 0
                LIMIT 1
                """,
                (user1_id, user2_id),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    finally:
        conn.close()


def get_or_create_private_conversation(user1_id: int, user2_id: int) -> int:
    """
    Tìm hoặc tạo mới conversation 1-1 giữa 2 user.
    Lưu conversations & members ở node đầu tiên.
    """
    existing = _find_private_conversation(user1_id, user2_id)
    if existing:
        return existing

    if user1_id > user2_id:
        user1_id, user2_id = user2_id, user1_id

    node = DB_NODES[0]
    conn = get_connection(node)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (is_group, name) VALUES (0, NULL)"
            )
            conv_id = cur.lastrowid
            cur.execute(
                "INSERT INTO conversation_members (conversation_id, user_id) VALUES (%s, %s)",
                (conv_id, user1_id),
            )
            cur.execute(
                "INSERT INTO conversation_members (conversation_id, user_id) VALUES (%s, %s)",
                (conv_id, user2_id),
            )
        conn.commit()
        return conv_id
    finally:
        conn.close()


def get_messages_for_conversation(conversation_id: int, limit: int = 200):
    """
    Lấy lịch sử tin nhắn cho một conversation, kèm username người gửi.
    """
    node_cfg = select_node_for_conversation(conversation_id)
    conn = get_connection(node_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id,
                       m.sender_id,
                       u.username AS sender_username,
                       m.msg_type,
                       m.content,
                       m.created_at
                FROM messages m
                JOIN users u ON u.id = m.sender_id
                WHERE m.conversation_id = %s
                ORDER BY m.id ASC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            rows = cur.fetchall()
            return rows
    finally:
        conn.close()


def insert_message(conversation_id: int, sender_id: int, msg_type: str, content: str) -> int:
    """
    Lưu tin nhắn vào node được chọn theo conversation_id.
    Trả về message_id.
    """
    node_cfg = select_node_for_conversation(conversation_id)
    conn = get_connection(node_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (conversation_id, sender_id, msg_type, content)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, sender_id, msg_type, content),
            )
            msg_id = cur.lastrowid
        conn.commit()
        return msg_id
    finally:
        conn.close()


def delete_message_for_user(conversation_id: int, message_id: int, sender_id: int) -> bool:
    """
    Xóa tin nhắn theo id, chỉ khi đúng người gửi và đúng conversation_id.
    """
    node_cfg = select_node_for_conversation(conversation_id)
    conn = get_connection(node_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM messages
                WHERE id = %s AND conversation_id = %s AND sender_id = %s
                """,
                (message_id, conversation_id, sender_id),
            )
            affected = cur.rowcount
        conn.commit()
        return affected > 0
    finally:
        conn.close()
def get_message_by_id(conversation_id: int, message_id: int):
    """
    Lấy 1 bản ghi tin nhắn theo id + conversation_id.
    Dùng để biết msg_type, content trước khi xóa.
    """
    node_cfg = select_node_for_conversation(conversation_id)
    conn = get_connection(node_cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sender_id, msg_type, content
                FROM messages
                WHERE id = %s AND conversation_id = %s
                """,
                (message_id, conversation_id),
            )
            row = cur.fetchone()
            return row
    finally:
        conn.close()



def get_conversations_for_user(user_id: int):
    """
    Lấy danh sách các cuộc trò chuyện 1-1 của user,
    kèm username + display_name của người còn lại,
    thời gian tin nhắn mới nhất (để sort giống Messenger)
    và avatar của partner.
    """
    node = DB_NODES[0]
    conn = get_connection(node)
    try:
        with conn.cursor() as cur:
            # Lấy danh sách conversation + last_time
            cur.execute(
                """
                SELECT c.id,
                       MAX(m.created_at) AS last_time
                FROM conversations c
                JOIN conversation_members cm_self
                    ON cm_self.conversation_id = c.id
                   AND cm_self.user_id = %s
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.is_group = 0
                GROUP BY c.id
                ORDER BY last_time IS NULL, last_time DESC, c.id DESC
                """,
                (user_id,),
            )
            conv_rows = cur.fetchall()
            result = []

            for row in conv_rows:
                conv_id = row["id"]
                last_time = row["last_time"]

                # Tìm người còn lại trong đoạn chat 1-1
                cur.execute(
                    """
                    SELECT u.username,
                           u.display_name,
                           u.avatar_url
                    FROM conversation_members cm
                    JOIN users u ON u.id = cm.user_id
                    WHERE cm.conversation_id = %s
                      AND cm.user_id <> %s
                    LIMIT 1
                    """,
                    (conv_id, user_id),
                )
                partner = cur.fetchone()
                if not partner:
                    continue

                if hasattr(last_time, "isoformat"):
                    last_str = last_time.isoformat(sep=" ", timespec="seconds")
                else:
                    last_str = str(last_time) if last_time is not None else None

                result.append({
                    "conversation_id": conv_id,
                    "partner_username": partner["username"],
                    "partner_display_name": partner["display_name"],
                    "last_time": last_str,
                    # thêm avatar gửi sang client
                    "partner_avatar_url": partner.get("avatar_url"),
                })

            return result
    finally:
        conn.close()


def delete_conversation_for_users(user1_id: int, user2_id: int) -> bool:
    """
    Xóa toàn bộ conversation 1-1 giữa 2 user (tin nhắn + conversation + members).
    Ảnh hưởng tới cả hai phía (cả 2 user đều mất lịch sử).
    Trả về True nếu có conversation và đã xóa, False nếu không tìm thấy.
    """
    conv_id = _find_private_conversation(user1_id, user2_id)
    if not conv_id:
        return False

    # Xóa messages trên node chứa messages
    node_msg = select_node_for_conversation(conv_id)
    conn_msg = get_connection(node_msg)
    try:
        with conn_msg.cursor() as cur:
            cur.execute(
                "DELETE FROM messages WHERE conversation_id = %s",
                (conv_id,),
            )
        conn_msg.commit()
    finally:
        conn_msg.close()

    # Xóa conversation + members ở node trung tâm
    node0 = DB_NODES[0]
    conn0 = get_connection(node0)
    try:
        with conn0.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_members WHERE conversation_id = %s",
                (conv_id,),
            )
            cur.execute(
                "DELETE FROM conversations WHERE id = %s",
                (conv_id,),
            )
        conn0.commit()
    finally:
        conn0.close()

    return True
# ====== Avatar ======
