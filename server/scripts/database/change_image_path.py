import sys
import os
import json

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, Conversation, init_sql_db

if __name__ == "__main__":
    init_sql_db("data\\database", "luotianyi.db")
    session = get_sql_session()

    picture_conversations = session.query(Conversation).filter(Conversation.type == "image").all()
    for conv in picture_conversations:
        meta_data = json.loads(conv.meta_data) if conv.meta_data else {}
        server_path = meta_data["image_server_path"]
        if not server_path.startswith("data\\images\\"):
            final_path = "data\\images\\" + server_path[6:]
            meta_data["image_server_path"] = final_path
            conv.meta_data = json.dumps(meta_data)
    session.commit()
    # print("Update completed.")