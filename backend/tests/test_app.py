import os
os.environ['JWT_SECRET'] = 'test-secret-that-is-long-enough-for-hs256'
os.environ['DATABASE_URL'] = 'sqlite://'
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from fastapi.testclient import TestClient
from app import main

engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
main.Base.metadata.create_all(engine)
main.SessionLocal.configure(bind=engine)
client = TestClient(main.app)

def register(email):
    assert client.post('/auth/signup', json={'email':email,'password':'password123','role':'admin'}).status_code == 201
    result = client.post('/auth/login', json={'email':email,'password':'password123'}).json()
    assert result['user']['role'] == 'user'
    return {'Authorization':'Bearer '+result['token']}

def test_roles_and_tool_ownership():
    a=register('a@example.com'); b=register('b@example.com')
    assert client.get('/admin/overview', headers=a).status_code == 403
    with main.SessionLocal() as db:
        ua=db.get(main.User,1); ub=db.get(main.User,2)
        task=main.run_tool('add_task',{'title':'Private task'},ua,db)['task']
        assert main.run_tool('update_task',{'task_id':task['id'],'done':True},ub,db)=={'error':'Task not found'}
        assert main.run_tool('delete_task',{'task_id':task['id']},ub,db)=={'error':'Task not found'}
        assert main.run_tool('list_tasks',{},ub,db)['tasks']==[]
        assert main.run_tool('update_task',{'task_id':task['id'],'done':True},ua,db)['task']['done'] is True
        ua.role='admin'; db.commit()
    assert len(client.get('/admin/overview',headers=a).json()['users']) == 2
    assert client.get('/tasks',headers=b).json() == []

def test_agent_chains_tool_calls(monkeypatch):
    headers={'Authorization':'Bearer '+main.jwt.encode({'sub':'1'},main.SECRET,algorithm='HS256')}
    responses=[{'choices':[{'message':{'role':'assistant','tool_calls':[{'id':'1','type':'function','function':{'name':'list_tasks','arguments':'{}'}}]}}]}, {'choices':[{'message':{'role':'assistant','tool_calls':[{'id':'2','type':'function','function':{'name':'update_task','arguments':'{"task_id":1,"done":true}'}},{'id':'3','type':'function','function':{'name':'add_task','arguments':'{"title":"Next report"}'}}]}}]}, {'choices':[{'message':{'role':'assistant','content':'Done and added the next report.'}}]}]
    class Response:
        def __init__(self, payload): self.payload=payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs): return Response(responses.pop(0))
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(main.httpx,'Client',FakeClient)
    result=client.post('/chat',headers=headers,json={'message':'Mark the report done and add the next report'})
    assert result.status_code == 200
    assert [x['name'] for x in result.json()['tool_calls']] == ['list_tasks','update_task','add_task']
    assert any(t['title']=='Next report' for t in client.get('/tasks',headers=headers).json())
