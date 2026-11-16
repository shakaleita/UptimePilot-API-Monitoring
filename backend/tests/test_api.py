import importlib,os,sys,tempfile
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
temp = tempfile.mkdtemp(prefix='portfolio-test-')
os.environ['APP_DB']=str(Path(temp)/'test.db')
if 'main' in sys.modules: del sys.modules['main']
from main import app
client=TestClient(app)

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

