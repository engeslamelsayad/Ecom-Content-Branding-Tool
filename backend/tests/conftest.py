import os
import uuid
from pathlib import Path

import httpx
import pytest_asyncio

runtime = Path(__file__).parent / '.runtime' / uuid.uuid4().hex
runtime.mkdir(parents=True)
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + str(runtime / 'test.db')
os.environ['STORAGE_DIR'] = str(runtime / 'storage')
os.environ['FAL_KEY'] = 'test-key-never-sent'
os.environ['ANTHROPIC_API_KEY'] = ''

from app.main import app
from app.db import engine, Base, SessionLocal
from app.models import Brand, Client, Membership, User
from app.security import create_session, COOKIE_NAME
from app import runner


@pytest_asyncio.fixture
async def env(monkeypatch):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(runner, 'start', lambda *args, **kwargs: None)
    async with SessionLocal() as db:
        a, b = Client(name='A'), Client(name='B')
        db.add_all([a, b]); await db.flush()
        ba, bb = Brand(client_id=a.id, name='براند A'), Brand(client_id=b.id, name='Brand B')
        db.add_all([ba, bb]); await db.flush()
        tokens, ids = {}, {}
        for role in ('owner', 'admin', 'editor', 'viewer', 'other'):
            u = User(email=f'{role}@example.com', name=role, password_hash='unused', role='owner' if role == 'owner' else 'member')
            db.add(u); await db.flush()
            if role != 'owner':
                db.add(Membership(user_id=u.id, client_id=b.id if role == 'other' else a.id,
                                  role='editor' if role == 'other' else role))
            tokens[role] = (await create_session(db, u)).token
            ids[role] = u.id
        await db.commit()
        result = {'brand': ba.id, 'other_brand': bb.id, 'client': a.id, 'users': ids, 'tokens': tokens}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result['api'] = client
        result['as_user'] = lambda role: client.cookies.set(COOKIE_NAME, tokens[role])
        result['as_user']('owner')
        yield result
    await engine.dispose()
