"""Create demo accounts from environment variables without exposing a public admin endpoint."""
import os
from sqlalchemy import select
from app.main import SessionLocal, User, password_hash

with SessionLocal() as db:
    for role in ('admin', 'user'):
        email = os.environ[f'DEMO_{role.upper()}_EMAIL'].strip().lower()
        password = os.environ[f'DEMO_{role.upper()}_PASSWORD']
        if len(password) < 8:
            raise SystemExit('Demo passwords must contain at least 8 characters')
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit(f'{email} already exists; refusing to overwrite an account')
        db.add(User(email=email, password=password_hash.hash(password), role=role))
    db.commit()
print('Demo accounts created')
