"""
Create a restricted admin user with specific page access.

Usage examples:
    # CRM Excel only
    python create_admin_user.py --username crm_user --password Pass@123 --pages crm_excel

    # Multiple pages
    python create_admin_user.py --username ops_user --password Pass@123 --pages crm_excel,final_report

    # All pages
    python create_admin_user.py --username full_user --password Pass@123 --pages scanner,crm_excel,ppt_store,final_report

Valid page keys: scanner, crm_excel, ppt_store, final_report
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import engine, SessionLocal, Base
import models.user
from models.user import User
from core.security import hash_password

Base.metadata.create_all(bind=engine)

VALID_PAGES = ["scanner", "crm_excel", "ppt_store", "final_report"]

PAGE_LABELS = {
    "scanner":      "Ad Scanner",
    "crm_excel":    "CRM Excel Processor",
    "ppt_store":    "PPT Store",
    "final_report": "Final Report",
}

def create_admin(username: str, password: str, pages: list, email: str = ""):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"⚠️  User '{username}' already exists (role: {existing.role}, pages: {existing.allowed_pages})")
            return

        bad = [p for p in pages if p not in VALID_PAGES]
        if bad:
            print(f"❌ Invalid page keys: {bad}")
            print(f"   Valid keys: {VALID_PAGES}")
            return

        user = User(
            username=username,
            email=email or None,
            hashed_password=hash_password(password),
            role="admin",
            allowed_pages=pages,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        page_names = [PAGE_LABELS.get(p, p) for p in pages]
        print(f"✅ Admin user created!")
        print(f"   Username : {user.username}")
        print(f"   Role     : {user.role}")
        print(f"   Access   : {', '.join(page_names)}")
        print(f"   Login at : http://127.0.0.1:8001/ui/login.html")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a restricted admin user")
    parser.add_argument("--username", required=True,          help="Username")
    parser.add_argument("--password", required=True,          help="Password")
    parser.add_argument("--pages",    required=True,          help="Comma-separated page keys e.g. crm_excel or crm_excel,scanner")
    parser.add_argument("--email",    default="",             help="Email (optional)")
    args = parser.parse_args()

    page_list = [p.strip() for p in args.pages.split(",") if p.strip()]
    create_admin(args.username, args.password, page_list, args.email)
