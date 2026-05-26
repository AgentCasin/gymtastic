#!/usr/bin/env python3
"""Quick test to verify app runs without errors."""

import os
import sys

# Remove old database for fresh start
if os.path.exists("gymtastic.db"):
    os.remove("gymtastic.db")
    print("✓ Cleaned old database")

try:
    # Test imports
    from main import app
    from db import init_db
    from models import User
    print("✓ All imports successful")
    
    # Test database initialization
    init_db()
    print("✓ Database initialized successfully")
    
    # Quick test: verify seeded data
    from sqlmodel import Session
    from db import engine
    
    with Session(engine) as session:
        admin = session.query(User).filter(User.role == "admin").first()
        if admin:
            print(f"✓ Seeded data verified - Admin: {admin.email}")
        else:
            print("✗ No admin found in database")
            sys.exit(1)
    
    print("\n✅ App startup test PASSED - Ready to run!")
    print("Start the server with: uv run main.py")
    print("Then visit: http://localhost:5001")
    
except Exception as e:
    print(f"\n❌ Error during startup: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
