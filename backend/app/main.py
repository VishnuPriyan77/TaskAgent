import json
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, MetaData, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./taskpilot.db').replace('postgres://', 'postgresql+psycopg://', 1).replace('postgresql://', 'postgresql+psycopg://', 1)
SECRET = os.getenv('JWT_SECRET', '')
if not SECRET or len(SECRET) < 32:
    raise RuntimeError('Set JWT_SECRET to a random value of at least 32 characters')
is_sqlite = DATABASE_URL.startswith('sqlite')
engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if is_sqlite else {}, **({} if is_sqlite else {'pool_size': 1, 'max_overflow': 1, 'pool_pre_ping': True}))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
password_hash = PasswordHash.recommended()
security = HTTPBearer()

class Base(DeclarativeBase):
    metadata = MetaData(schema=None if is_sqlite else 'taskpilot')
class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(10), default='user')
class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

app = FastAPI(title='TaskPilot API')
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')], allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
with engine.begin() as connection:
    if not is_sqlite:
        connection.execute(text('CREATE SCHEMA IF NOT EXISTS taskpilot'))
        connection.execute(text('REVOKE ALL ON SCHEMA taskpilot FROM PUBLIC'))
    Base.metadata.create_all(connection)
    if not is_sqlite:
        for table in ('users', 'tasks'):
            connection.execute(text(f'ALTER TABLE taskpilot.{table} ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'REVOKE ALL ON TABLE taskpilot.{table} FROM PUBLIC'))

def db_session():
    with SessionLocal() as db: yield db

def current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(db_session)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=['HS256'])
        user = db.get(User, int(payload['sub']))
        if not user: raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, 'Session expired or invalid. Please log in again.')

def admin(user: User = Depends(current_user)):
    if user.role != 'admin': raise HTTPException(403, 'Admin access required')
    return user

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

def user_data(u): return {'id': u.id, 'email': u.email, 'role': u.role}
def task_data(t): return {'id': t.id, 'title': t.title, 'done': t.done, 'due_date': t.due_date, 'owner_id': t.owner_id}
@app.get('/health')
def health(): return {'status': 'ok'}
@app.post('/auth/signup', status_code=201)
def signup(body: Credentials, db: Session = Depends(db_session)):
    email = body.email.strip().lower()
    if '@' not in email: raise HTTPException(400, 'Enter a valid email address')
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, 'An account with this email already exists')
    u = User(email=email, password=password_hash.hash(body.password), role='user')
    db.add(u); db.commit(); db.refresh(u)
    return user_data(u)
@app.post('/auth/login')
def login(body: Credentials, db: Session = Depends(db_session)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not u or not password_hash.verify(body.password, u.password): raise HTTPException(401, 'Invalid email or password')
    token = jwt.encode({'sub': str(u.id), 'exp': datetime.now(timezone.utc) + timedelta(hours=12)}, SECRET, algorithm='HS256')
    return {'token': token, 'user': user_data(u)}
@app.get('/auth/me')
def me(user: User = Depends(current_user)): return user_data(user)
@app.get('/tasks')
def tasks(user: User = Depends(current_user), db: Session = Depends(db_session)):
    return [task_data(t) for t in db.scalars(select(Task).where(Task.owner_id == user.id).order_by(Task.id.desc()))]
@app.get('/admin/overview')
def overview(_: User = Depends(admin), db: Session = Depends(db_session)):
    return {'users': [user_data(u) for u in db.scalars(select(User).order_by(User.id))], 'tasks': [task_data(t) for t in db.scalars(select(Task).order_by(Task.id.desc()))]}

TOOLS = [
 {'type':'function','function':{'name':'list_tasks','description':'List the current user’s tasks; use to find IDs before updating or deleting.','parameters':{'type':'object','properties':{},'additionalProperties':False}}},
 {'type':'function','function':{'name':'add_task','description':'Create a task for the current user.','parameters':{'type':'object','properties':{'title':{'type':'string'},'due_date':{'type':['string','null'],'description':'Due date YYYY-MM-DD, or null'}},'required':['title'],'additionalProperties':False}}},
 {'type':'function','function':{'name':'update_task','description':'Update an existing task by ID. Only provide fields to change.','parameters':{'type':'object','properties':{'task_id':{'type':'integer'},'title':{'type':'string'},'done':{'type':'boolean'},'due_date':{'type':['string','null']}},'required':['task_id'],'additionalProperties':False}}},
 {'type':'function','function':{'name':'delete_task','description':'Delete a task by ID. Only call after the user explicitly requests deletion.','parameters':{'type':'object','properties':{'task_id':{'type':'integer'}},'required':['task_id'],'additionalProperties':False}}},
]
def run_tool(name, args, user, db):
    if not isinstance(args, dict): return {'error':'Invalid arguments'}
    if name == 'list_tasks': return {'tasks':[task_data(t) for t in db.scalars(select(Task).where(Task.owner_id == user.id).order_by(Task.id))]}
    if name == 'add_task':
        title = args.get('title')
        if not isinstance(title, str) or not title.strip() or len(title) > 200: return {'error':'A title of 1–200 characters is required'}
        due = args.get('due_date')
        if due is not None:
            try: datetime.strptime(due, '%Y-%m-%d')
            except (ValueError, TypeError): return {'error':'Due date must be YYYY-MM-DD'}
        task = Task(owner_id=user.id, title=title.strip(), due_date=due); db.add(task); db.commit(); db.refresh(task)
        return {'task': task_data(task)}
    if name not in ('update_task', 'delete_task'): return {'error':'Unknown tool'}
    task_id = args.get('task_id')
    if type(task_id) is not int: return {'error':'Invalid task ID'}
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id))
    if not task: return {'error':'Task not found'}
    if name == 'delete_task':
        result = task_data(task); db.delete(task); db.commit(); return {'deleted':result}
    if 'title' in args:
        if not isinstance(args['title'], str) or not args['title'].strip() or len(args['title']) > 200: return {'error':'Invalid title'}
    if 'done' in args and type(args['done']) is not bool: return {'error':'Invalid status'}
    if 'due_date' in args and args['due_date'] is not None:
        try: datetime.strptime(args['due_date'], '%Y-%m-%d')
        except (ValueError, TypeError): return {'error':'Due date must be YYYY-MM-DD'}
    for key in ('title','done','due_date'):
        if key in args: setattr(task, key, args[key].strip() if key == 'title' else args[key])
    db.commit(); return {'task':task_data(task)}

@app.post('/chat')
def chat(body: ChatInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    key = os.getenv('GEMINI_API_KEY')
    if not key: raise HTTPException(503, 'The AI service is not configured yet. Ask the administrator to add its API key.')
    messages = [{'role':'system','content':f"You are TaskPilot, a task assistant. Today is {datetime.now(timezone.utc).date()} UTC. Use tools to manage tasks. List tasks to resolve names to IDs. Never claim an action succeeded if a tool returned an error. Ask for clarification when ambiguous. Only delete if explicitly asked. Respond concisely."}, {'role':'user','content':body.message}]
    calls = []
    try:
        with httpx.Client(timeout=30) as client:
            for _ in range(8):
                response = client.post('https://generativelanguage.googleapis.com/v1beta/openai/chat/completions', headers={'Authorization':f'Bearer {key}'}, json={'model':os.getenv('GEMINI_MODEL','gemini-2.5-flash'),'messages':messages,'tools':TOOLS,'tool_choice':'auto','temperature':0})
                response.raise_for_status()
                msg = response.json()['choices'][0]['message']; messages.append(msg)
                tool_calls = msg.get('tool_calls') or []
                if not tool_calls: return {'reply':msg.get('content') or 'Done.', 'tool_calls':calls}
                for call in tool_calls:
                    name = call['function']['name']
                    try: args = json.loads(call['function']['arguments']); result = run_tool(name, args, user, db)
                    except (ValueError, TypeError, KeyError): result = {'error':'Invalid tool arguments'}
                    calls.append({'name':name, 'result':result})
                    messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result)})
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        raise HTTPException(502, 'The AI service could not complete this request. Some task changes may already have been saved; check your task list before retrying.')
    raise HTTPException(502, 'The AI reached its action limit. Some changes may have been saved; check your task list before retrying.')
