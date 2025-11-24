# common/config.py

SERVER_HOST = "192.168.2.31"
SERVER_PORT = 5555

# Cấu hình 2 node CSDL phân tán (trên cùng MySQL XAMPP)
DB_NODES = [
    {
        "name": "node1",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",          # nếu XAMPP root không có pass
        "database": "chat_node1"
    },
    {
        "name": "node2",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "chat_node2"
    }
]

# Hàm chọn node dựa trên conversation_id (sharding logic)
def select_node_for_conversation(conversation_id: int):
    idx = conversation_id % len(DB_NODES)
    return DB_NODES[idx]
