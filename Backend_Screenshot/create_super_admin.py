"""
Run once to create the first super_admin account.

Usage:
    python create_super_admin.py
    python create_super_admin.py --username admin --password MyPass123
"""
import argparse
import sys
import os

# Make sure Backend_Screenshot is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import engine, SessionLocal, Base
import models.user  # registers User with Base
from models.user import User
from core.security import hash_password

Base.metadata.create_all(bind=engine)   # creates users table

def create_super_admin(username: str, password: str, email: str = ""):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"✅ User '{username}' already exists (role: {existing.role})")
            return

        user = User(
            username=username,
            email=email or None,
            hashed_password=hash_password(password),
            role="super_admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ Super admin created — id={user.id} username='{user.username}'")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create first super_admin user")
    parser.add_argument("--username", default="admin",    help="Username (default: admin)")
    parser.add_argument("--password", default="Admin@123", help="Password (default: Admin@123)")
    parser.add_argument("--email",    default="",         help="Email (optional)")
    args = parser.parse_args()
    create_super_admin(args.username, args.password, args.email)
