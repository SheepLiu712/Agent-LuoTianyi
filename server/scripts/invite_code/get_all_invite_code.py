import sys
import os

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, InviteCode

session = get_sql_session()

def get_all_invite_codes():
    try:
        codes = session.query(InviteCode).all()
        for code in codes:
            status = "Used" if code.is_used else "Unused"
            used_at = code.used_at.strftime("%Y-%m-%d %H:%M:%S") if code.used_at else "N/A"
            user_id = code.user_id if code.user_id else "N/A"
            print(f"Code: {code.code}, Status: {status}, Used At: {used_at}, User ID: {user_id}")
    except Exception as e:
        print(f"Error retrieving invite codes: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    get_all_invite_codes()