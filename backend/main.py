APP_TITLE = 'UptimePilot'
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any
import sqlite3, os
from contextlib import contextmanager
from pathlib import Path

DB = Path(os.environ.get("APP_DB", str(Path(__file__).parent / "app.db")))
app = FastAPI(title=APP_TITLE, version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_methods=["*"], allow_headers=["*"])

@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]

def setup(sql):
    with db() as con:
        con.executescript(sql)

@app.get("/api/health")
def health():
    return {"ok": True, "service": APP_TITLE}


from urllib.parse import urlparse
import ipaddress,socket,httpx,time
setup("""CREATE TABLE IF NOT EXISTS monitors(id INTEGER PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,expected_status INTEGER NOT NULL DEFAULT 200);CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY,monitor_id INTEGER NOT NULL,status INTEGER,latency_ms INTEGER,ok INTEGER NOT NULL,checked_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(monitor_id) REFERENCES monitors(id));""")
class Monitor(BaseModel):
    name:str
    url:str
    expected_status:int=Field(default=200,ge=100,le=599)

def valid_public_url(url: str, *, require_allowlist: bool = False):
    """Reject unapproved outbound URLs and non-global DNS results.

    An exact hostname allowlist is required for outgoing checks. Operations
    should also restrict network egress against DNS rebinding.
    """
    from urllib.parse import urlsplit
    if not isinstance(url, str) or len(url) > 2048 or any(ord(ch) < 32 for ch in url):
        raise HTTPException(422, 'Invalid monitoring URL')
    try:
        p = urlsplit(url)
        host = (p.hostname or '').rstrip('.').lower()
        port = p.port
    except ValueError:
        raise HTTPException(422, 'Invalid monitoring URL')
    if (p.scheme not in ('http', 'https') or not host or not p.netloc
            or p.username is not None or p.password is not None
            or p.fragment or port not in (None, 80, 443)):
        raise HTTPException(422, 'Use a public HTTP(S) URL on a standard port')
    if host in ('localhost', 'localhost.localdomain') or host.endswith('.localhost'):
        raise HTTPException(422, 'Local hosts are not allowed')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise HTTPException(422, 'IP literal targets are not allowed')
    if require_allowlist:
        allowed = {h.strip().rstrip('.').lower() for h in os.getenv('ALLOWED_MONITOR_HOSTS', '').split(',') if h.strip()}
        if not allowed or host not in allowed:
            raise HTTPException(403, 'Target host is not in ALLOWED_MONITOR_HOSTS')
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        raise HTTPException(422, 'Cannot resolve monitoring hostname')
    if not infos or any(not ipaddress.ip_address(info[4][0]).is_global for info in infos):
        raise HTTPException(422, 'Private, reserved or local addresses are not allowed')
    return host

@app.get('/api/items')
def items():
    with db() as c:return rows(c.execute('SELECT * FROM monitors ORDER BY id DESC'))
@app.post('/api/items',status_code=201)
def create_item(d:Monitor):
    valid_public_url(d.url)
    with db() as c:
        cur=c.execute('INSERT INTO monitors(name,url,expected_status) VALUES(?,?,?)',(d.name,d.url,d.expected_status))
        return dict(c.execute('SELECT * FROM monitors WHERE id=?',(cur.lastrowid,)).fetchone())
@app.post('/api/check/{id}')
async def check(id:int):
    with db() as c:m=c.execute('SELECT * FROM monitors WHERE id=?',(id,)).fetchone()
    if not m:raise HTTPException(404,'Monitor not found')
    valid_public_url(m['url'],require_allowlist=True)
    start=time.monotonic();status=None
    try:
        async with httpx.AsyncClient(timeout=5,follow_redirects=False,trust_env=False) as client:
            res=await client.get(m['url']);status=res.status_code
    except httpx.RequestError:pass
    latency=round((time.monotonic()-start)*1000)
    ok=int(status==m['expected_status'])
    with db() as c:c.execute('INSERT INTO checks(monitor_id,status,latency_ms,ok) VALUES(?,?,?,?)',(id,status,latency,ok))
    return {'status':status,'latency_ms':latency,'ok':bool(ok)}
@app.get('/api/history')
def history():
    with db() as c:return rows(c.execute('SELECT c.*,m.name FROM checks c JOIN monitors m ON c.monitor_id=m.id ORDER BY c.id DESC LIMIT 100'))
@app.get('/api/summary')
def summary():
    with db() as c:return [{'label':'Monitors','value':c.execute('SELECT COUNT(*) FROM monitors').fetchone()[0]},{'label':'Checks','value':c.execute('SELECT COUNT(*) FROM checks').fetchone()[0]},{'label':'Successful checks','value':c.execute('SELECT COUNT(*) FROM checks WHERE ok=1').fetchone()[0]}]


# v0.3: per-monitor uptime reports
@app.get('/api/monitors/{monitor_id}/metrics')
def monitor_metrics(monitor_id: int):
    with db() as con:
        monitor=con.execute('SELECT * FROM monitors WHERE id=?',(monitor_id,)).fetchone()
        if not monitor:
            raise HTTPException(404,'Monitor not found')
        result=con.execute("""SELECT COUNT(*) AS checks,
            COALESCE(SUM(ok),0) AS successful,
            ROUND(AVG(latency_ms),1) AS avg_latency_ms
            FROM checks WHERE monitor_id=?""",(monitor_id,)).fetchone()
        data=dict(result)
        data['uptime_percent']=round(100*data['successful']/data['checks'],1) if data['checks'] else None
        return {'monitor':dict(monitor),**data}

@app.get('/api/monitors/{monitor_id}/history')
def monitor_history(monitor_id: int, limit: int = 50):
    if limit < 1 or limit > 200:
        raise HTTPException(422,'Limit must be between 1 and 200')
    with db() as con:
        if not con.execute('SELECT 1 FROM monitors WHERE id=?',(monitor_id,)).fetchone():
            raise HTTPException(404,'Monitor not found')
        return rows(con.execute('SELECT * FROM checks WHERE monitor_id=? ORDER BY id DESC LIMIT ?',(monitor_id,limit)))


@app.get('/api/reliability')
def reliability():
    with db() as con:
        return rows(con.execute("""SELECT m.id,m.name,COUNT(c.id) AS checks,
            COALESCE(SUM(c.ok),0) AS successful,
            ROUND(100.0*SUM(c.ok)/NULLIF(COUNT(c.id),0),2) AS uptime_percent,
            ROUND(AVG(c.latency_ms),1) AS avg_latency_ms
            FROM monitors m LEFT JOIN checks c ON c.monitor_id=m.id
            GROUP BY m.id ORDER BY uptime_percent ASC,m.name"""))

from security import install_auth
install_auth(app,DB)
