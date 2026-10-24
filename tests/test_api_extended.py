import time
from fastapi.testclient import TestClient
from app.server import app,jobs

CFG={'start':'2024-01-01','end':'2024-01-02','cash':10000,'fee':.0005,'slippage':.0002}
def test_full_session_api_and_batch_cancel():
    with TestClient(app) as c:
        response=c.post('/api/sessions',json={**CFG,'end':'2024-02-01','random_asset':True,'category':'etf','seed':42,'blind':True})
        assert response.status_code==200,response.text
        s=response.json();sid=s['id']
        assert s['asset']['id']=='隐藏资产'
        r=c.post(f'/api/sessions/{sid}/command',json={'action':'step','count':1});assert r.status_code==200
        settings={'sma20':7,'rsi':9}
        r=c.post(f'/api/sessions/{sid}/command',json={'action':'indicators','parameters':settings,'layout':{'rsi':{'enabled':True,'placement':'main'}}})
        assert r.status_code==200,r.text
        current=c.get(f'/api/sessions/{sid}').json()
        assert current['indicators']['sma20']==7
        news=[{'title':'event','known_at':'2024-01-01T12:00:00Z','published_at':'2024-01-01T11:00:00Z'}]
        assert c.post(f'/api/sessions/{sid}/news',json=news).status_code==200
        assert c.post(f'/api/sessions/{sid}/news',json=[{'title':'bad'}]).status_code==400
        exported=c.get(f'/api/sessions/{sid}/export?format=csv').json();assert exported['text'].startswith('\ufefftype,')
        c.delete(f'/api/sessions/{sid}')
        s=c.post('/api/sessions',json=CFG).json();sid=s['id']
        j=c.post(f'/api/sessions/{sid}/batch',json={}).json()['id']
        assert c.post(f'/api/jobs/{j}/cancel',json={}).status_code==200
        for _ in range(200):
            snap=c.get(f'/api/jobs/{j}').json()
            if snap['status']!='running':break
            time.sleep(.01)
        assert snap['status'] in ('cancelled','completed')

def test_short_period_strategy_has_no_future_context():
    with TestClient(app) as c:
        s=c.post('/api/sessions',json=CFG).json();sid=s['id']
        assert c.post(f'/api/sessions/{sid}/command',json={'action':'strategy','name':'01_sma_cross.py','timeframe':'5m','contexts':['1h'],'parameters':{'fast':5,'slow':20}}).status_code==200
        assert c.post(f'/api/sessions/{sid}/command',json={'action':'step','count':12}).status_code==200
        out=c.get(f'/api/sessions/{sid}').json();assert out['error'] is None
        assert out['strategy_settings']['timeframe']=='5m'
        result=c.post(f'/api/sessions/{sid}/command',json={'action':'save'}).json()
        restore=c.post('/api/restore/'+result['file'],json={})
        assert restore.status_code==200,restore.text
        assert restore.json()['strategy']=='01_sma_cross.py'
