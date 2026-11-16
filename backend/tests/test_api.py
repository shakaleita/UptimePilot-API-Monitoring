import importlib,os,sys,tempfile
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temp = tempfile.mkdtemp(prefix='portfolio-test-')
os.environ['APP_DB']=str(Path(temp)/'test.db')
os.environ['OWNER_SETUP_TOKEN']='test-only-setup-token-1234567890123'
if 'main' in sys.modules: del sys.modules['main']
from main import app
client=TestClient(app)
assert client.post('/api/auth/register',json={'username':'qaowner','password':'DemoPassword123!','setup_token':'test-only-setup-token-1234567890123'}).status_code==201
assert client.post('/api/auth/login',json={'username':'qaowner','password':'DemoPassword123!'}).status_code==200

def test_health():
    r=client.get('/api/health')
    assert r.status_code==200 and r.json()['ok']

def test_initial_list():
    r=client.get('/api/items')
    assert r.status_code==200 and isinstance(r.json(),list)

def test_summary():
    r=client.get('/api/summary')
    assert r.status_code==200 and isinstance(r.json(),list)


# v0.3 regression tests
def test_monitor_metrics_without_external_network():
    # Directly insert a synthetic monitor to avoid hitting or resolving public websites.
    from main import db
    with db() as con:
        pid=con.execute("INSERT INTO monitors(name,url,expected_status) VALUES('Synthetic QA','https://example.com',200)").lastrowid
        con.executemany('INSERT INTO checks(monitor_id,status,latency_ms,ok) VALUES(?,?,?,?)',[(pid,200,120,1),(pid,503,240,0)])
    metrics=client.get(f'/api/monitors/{pid}/metrics')
    assert metrics.status_code==200 and metrics.json()['uptime_percent']==50.0
    assert metrics.json()['avg_latency_ms']==180
    assert len(client.get(f'/api/monitors/{pid}/history').json())==2
    assert client.get('/api/monitors/987654/metrics').status_code==404



def test_v05_reliability_without_network():
    result=client.get('/api/reliability')
    assert result.status_code==200 and isinstance(result.json(),list)

def test_v05_authentication():
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/items').status_code==401
        assert anonymous.post('/api/auth/register',json={'username':'intruder','password':'DemoPassword123!','setup_token':'bad'}).status_code==403

# v0.6 request-origin and owner audit regression
def test_v06_audit_record_and_cross_site_guard():
    attempted=client.post('/api/__audit_probe_404')
    assert attempted.status_code==404
    audit=client.get('/api/auth/audit')
    assert audit.status_code==200
    assert any(row['method']=='POST' and row['path']=='/api/__audit_probe_404'
               and row['status_code']==404 for row in audit.json())
    assert client.get('/api/auth/audit',params={'limit':201}).status_code==422
    blocked=client.post('/api/__audit_probe_404',headers={'sec-fetch-site':'cross-site'})
    assert blocked.status_code==403
