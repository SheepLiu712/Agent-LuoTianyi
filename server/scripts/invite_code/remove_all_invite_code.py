import sys
import os

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, InviteCode

session = get_sql_session()

def delete_all_invite_codes():
    try:
        deleted_count = session.query(InviteCode).delete()
        session.commit()
        print(f"Deleted {deleted_count} invite codes.")
    except Exception as e:
        session.rollback()
        print(f"Error deleting invite codes: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    delete_all_invite_codes()