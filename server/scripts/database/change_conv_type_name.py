import sys
import os
import random
import string
import argparse

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, Conversation, init_sql_db

if __name__ == "__main__":
    init_sql_db("data\\database", "luotianyi.db")
    session = get_sql_session()

    picture_conversations = session.query(Conversation).filter(Conversation.type == "picture").all()
    print(f"Found {len(picture_conversations)} conversations with type 'picture'. Updating to 'image'...")
    for conv in picture_conversations:
        conv.type = "image"
    session.commit()
    print("Update completed.")