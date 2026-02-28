import sys
import os
import random
import string
import argparse

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, User, init_sql_db

if __name__ == "__main__":
    init_sql_db("data\\database", "luotianyi.db")
    session = get_sql_session()

    user = session.query(User).all()
    print(f"Found {len(user)} users with username 'DuanYouxi'. Updating to 'image'...")
    for u in user:
        print(u.username, u.password)
