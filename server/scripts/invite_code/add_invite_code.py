import sys
import os
import random
import string
import argparse

# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import get_sql_session, InviteCode, init_sql_db

def generate_invite_code(length=10):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def add_invite_codes(count=1):
    session = get_sql_session()
    added_codes = []
    try:
        for _ in range(count):
            code_str = generate_invite_code()
            # Ensure uniqueness check
            while session.query(InviteCode).filter(InviteCode.code == code_str).first():
                code_str = generate_invite_code()
            
            new_code = InviteCode(code=code_str)
            session.add(new_code)
            added_codes.append(code_str)
        
        session.commit()
        print(f"Successfully added {count} invite codes:")
        for code in added_codes:
            print(f"- {code}")
    except Exception as e:
        session.rollback()
        print(f"Error adding invite codes: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add invite codes to database.")
    parser.add_argument("--count", type=int, default=1, help="Number of codes to generate")
    parser.add_argument("--code", type=str, help="Specific code to add (optional)")
    
    args = parser.parse_args()
    
    if args.code:
        init_sql_db("data\\database", "luotianyi.db")
        session = get_sql_session()
        try:
            if session.query(InviteCode).filter(InviteCode.code == args.code).first():
                print(f"Code '{args.code}' already exists.")
            else:
                new_code = InviteCode(code=args.code)
                session.add(new_code)
                session.commit()
                print(f"Successfully added code: {args.code}")
        except Exception as e:
            session.rollback()
            print(f"Error: {e}")
        finally:
            session.close()
    else:
        print(f"Adding {args.count} invite codes...")
        init_sql_db("data\\database", "luotianyi.db")
        add_invite_codes(args.count)
