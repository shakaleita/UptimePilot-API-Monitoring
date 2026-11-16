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


def test_monitor_allowlist_enforced_before_network(monkeypatch):
    from main import valid_public_url
    from fastapi import HTTPException
    import pytest
    monkeypatch.delenv('ALLOWED_MONITOR_HOSTS', raising=False)
    with pytest.raises(HTTPException) as error:
        valid_public_url('https://example.com', require_allowlist=True)
    assert error.value.status_code == 403
    monkeypatch.setenv('ALLOWED_MONITOR_HOSTS','example.org')
    with pytest.raises(HTTPException) as error:
        valid_public_url('https://example.com', require_allowlist=True)
    assert error.value.status_code == 403


def test_monitor_rejects_local_hosts_and_bad_ports_without_network(monkeypatch):
    from main import valid_public_url
    from fastapi import HTTPException
    import pytest
    for url in ['http://localhost/', 'https://127.0.0.1/', 'http://169.254.169.254/',
                'https://example.com:444/', 'file:///etc/passwd', 'https://[::1]/']:
        with pytest.raises(HTTPException) as error:
            valid_public_url(url)
        assert error.value.status_code == 422


def test_monitor_rejects_private_resolution(monkeypatch):
    import socket
    from main import valid_public_url
    from fastapi import HTTPException
    import pytest
    monkeypatch.setenv('ALLOWED_MONITOR_HOSTS','example.com')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',0))])
    with pytest.raises(HTTPException) as error:
        valid_public_url('https://example.com', require_allowlist=True)
    assert error.value.status_code == 422


def test_monitor_connects_only_to_validated_public_ip(monkeypatch):
    import asyncio,socket
    from main import db
    from main import status_from_pinned_address
    monkeypatch.setenv('ALLOWED_MONITOR_HOSTS','example.com')
    monkeypatch.setattr(socket,'getaddrinfo',
        lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.215.14',0))])
    observed=[]
    class Writer:
        def write(self, data): observed.append(data)
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass
    async def open_pinned(**options):
        observed.append(options)
        reader=asyncio.StreamReader()
        reader.feed_data(b'HTTP/1.1 204 No Content\r\n')
        reader.feed_eof()
        return reader,Writer()
    monkeypatch.setattr(asyncio,'open_connection',open_pinned)
    with db() as con:
        monitor_id=con.execute('INSERT INTO monitors(name,url,expected_status) VALUES(?,?,?)',
                               ('Pinned QA','https://example.com/health?full=1',204)).lastrowid
    response=client.post(f'/api/check/{monitor_id}')
    assert response.status_code==200
    assert response.json()['status']==204
    assert response.json()['ok'] is True
    assert observed[0]['host']=='93.184.215.14'
    assert observed[0]['server_hostname']=='example.com'
    assert b'Host: example.com' in observed[1]
    assert b'GET /health?full=1 HTTP/1.1' in observed[1]


def test_status_probe_does_not_follow_redirects(monkeypatch):
    import asyncio
    from main import status_from_pinned_address
    class Writer:
        def write(self, data): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass
    count=[0]
    async def mocked_connect(**_options):
        count[0]+=1
        reader=asyncio.StreamReader()
        reader.feed_data(b'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/private\r\n\r\n')
        reader.feed_eof()
        return reader,Writer()
    monkeypatch.setattr(asyncio,'open_connection',mocked_connect)
    status=asyncio.run(status_from_pinned_address('http://example.com/status','example.com','93.184.215.14'))
    assert status==302
    assert count[0]==1
