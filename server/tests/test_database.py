import unittest
import os
import sys
from datetime import datetime

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.database.sql_database import get_sql_session, User, InviteCode, Conversation, init_sql_db, Base

class TestDatabaseCRUD(unittest.TestCase):
    def setUp(self):
        # Patch the database file for testing
        import src.database.sql_database as db_module
        db_module.init_sql_db(db_folder=os.path.join(current_dir, "data","database"), db_file="test_luotianyi.db")
        
        self.session = db_module.get_sql_session()
        # Clean slate: drop all and recreate
        Base.metadata.drop_all(bind=self.session.get_bind())
        Base.metadata.create_all(bind=self.session.get_bind())

    def tearDown(self):
        self.session.close()
        # Clean up the test database file might be tricky due to file locks, 
        # so specific file deletion is skipped for this simple script or could be added with retry.

    def test_user_crud(self):
        # Create
        new_user = User(username="testuser", password="password123")
        self.session.add(new_user)
        self.session.commit()
        
        # Read
        user = self.session.query(User).filter_by(username="testuser").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.nickname, "你") # Default
        
        # Update
        user.nickname = "Master"
        self.session.commit()
        updated_user = self.session.query(User).filter_by(username="testuser").first()
        self.assertEqual(updated_user.nickname, "Master")
        
        # Delete
        self.session.delete(updated_user)
        self.session.commit()
        deleted_user = self.session.query(User).filter_by(username="testuser").first()
        self.assertIsNone(deleted_user)

    def test_invite_code_crud(self):
        # Create
        code = InviteCode(code="TESTCODE123")
        self.session.add(code)
        self.session.commit()
        
        # Read
        fetched_code = self.session.query(InviteCode).filter_by(code="TESTCODE123").first()
        self.assertIsNotNone(fetched_code)
        self.assertFalse(fetched_code.is_used)
        
        # Update
        fetched_code.is_used = True
        self.session.commit()
        updated_code = self.session.query(InviteCode).filter_by(code="TESTCODE123").first()
        self.assertTrue(updated_code.is_used)
        
        # Delete
        self.session.delete(updated_code)
        self.session.commit()
        deleted_code = self.session.query(InviteCode).filter_by(code="TESTCODE123").first()
        self.assertIsNone(deleted_code)

    def test_conversation_crud(self):
        # Need a user first because of foreign key
        user = User(username="chatuser", password="pwd")
        self.session.add(user)
        self.session.commit()
        
        # Create
        conv = Conversation(
            user_id=user.uuid,
            source="user",
            type="text",
            content="Hello LuoTianyi"
        )
        self.session.add(conv)
        self.session.commit()
        
        # Read
        fetched_conv = self.session.query(Conversation).filter_by(user_id=user.uuid).first()
        self.assertIsNotNone(fetched_conv)
        self.assertEqual(fetched_conv.content, "Hello LuoTianyi")
        
        # Update
        fetched_conv.content = "Edited Message"
        self.session.commit()
        updated_conv = self.session.query(Conversation).filter_by(uuid=fetched_conv.uuid).first()
        self.assertEqual(updated_conv.content, "Edited Message")
        
        # Delete
        self.session.delete(updated_conv)
        self.session.commit()
        self.assertIsNone(self.session.query(Conversation).filter_by(uuid=fetched_conv.uuid).first())

if __name__ == "__main__":
    unittest.main()
