import unittest
import os
import sys
from datetime import datetime

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.database.sql_database import get_sql_session, User, InviteCode, Base

class TestRegistration(unittest.TestCase):
    def setUp(self):
        # Patch the database file for testing
        import src.database.sql_database as db_module
        db_module.init_sql_db(db_folder=os.path.join(current_dir, "data","database"), db_file="test_registration.db")
        
        self.session = db_module.get_sql_session()
        Base.metadata.drop_all(bind=self.session.get_bind())
        Base.metadata.create_all(bind=self.session.get_bind())

    def tearDown(self):
        self.session.close()

    def register_user_logic(self, username, password, invite_code_str):
        """
        Mimics the registration logic to be implemented in the service.
        """
        # 1. Check Invite Code
        code = self.session.query(InviteCode).filter_by(code=invite_code_str).first()
        if not code:
            return False, "Invalid invite code"
        if code.is_used:
            return False, "Invite code already used"
            
        # 2. Check Username
        existing_user = self.session.query(User).filter_by(username=username).first()
        if existing_user:
            return False, "Username already exists"
            
        # 3. Create User
        new_user = User(username=username, password=password)
        self.session.add(new_user)
        self.session.flush() # Populate defaults like uuid
        
        # 4. Update Invite Code
        code.is_used = True
        code.used_at = datetime.utcnow()
        code.user_id = new_user.uuid
        
        self.session.commit()
        return True, "Success"

    def test_registration_flow(self):
        # Setup: Create a valid invite code
        valid_code = InviteCode(code="VALID123")
        self.session.add(valid_code)
        self.session.commit()
        
        # 1. Test success
        success, msg = self.register_user_logic("newuser", "pass", "VALID123")
        self.assertTrue(success)
        
        # Verify DB connection
        user = self.session.query(User).filter_by(username="newuser").first()
        self.assertIsNotNone(user)
        code = self.session.query(InviteCode).filter_by(code="VALID123").first()
        self.assertTrue(code.is_used)
        self.assertEqual(code.user_id, user.uuid)
        
        # 2. Test invite code already used
        success, msg = self.register_user_logic("otheruser", "pass", "VALID123")
        self.assertFalse(success)
        self.assertEqual(msg, "Invite code already used")
        
        # 3. Test invalid invite code
        success, msg = self.register_user_logic("otheruser", "pass", "INVALID999")
        self.assertFalse(success)
        self.assertEqual(msg, "Invalid invite code")
        
        # 4. Test username exists (need new code first)
        code2 = InviteCode(code="VALID456")
        self.session.add(code2)
        self.session.commit()
        
        success, msg = self.register_user_logic("newuser", "pass2", "VALID456")
        self.assertFalse(success)
        self.assertEqual(msg, "Username already exists")

if __name__ == "__main__":
    unittest.main()
