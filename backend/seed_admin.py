"""Promote an existing account using trusted server-side access only."""
import sys
from sqlalchemy import select
from app.main import SessionLocal, User
if len(sys.argv) != 2:
    raise SystemExit('Usage: python seed_admin.py EMAIL')
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.email == sys.argv[1].strip().lower()))
    if not user: raise SystemExit('Sign up this account first')
    user.role = 'admin'; db.commit()
    print('Admin role assigned')
