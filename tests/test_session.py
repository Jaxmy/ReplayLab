import pytest
from fastapi.testclient import TestClient
from app.session import Session
from app.server import app, sessions

CFG={'start':'2024-01-01','end':'2024-01-02','cash':10000,'fee':.0005,'slippage':.0002,'hedging':True}

def test_save_restore_deterministic(monkeypatch,tmp_path):
    monkeypatch.setattr('app.session.ROOT',tmp_path)
    s=Session(CFG);r=None
    try:
        s.order({'action':'long','quantity':.01,'leverage':2});s.step(3)
        pid=s.broker.positions()[0]['id'];s.leverage(pid,4);s.step(2)
        filename=s.save();r=Session.restore(filename)
        assert r.broker.account()==s.broker.account()
        assert r.broker.positions()==s.broker.positions()
        assert r.curve==s.curve
    finally:
        s.close()
        if r:r.close()

def test_api_future_prefix_and_origin_guard():
    with TestClient(app) as client:
        r=client.post('/api/sessions',json=CFG);assert r.status_code==200,r.text
        state=r.json();sid=state['id'];start_time=1704067200
        assert all(c['time']<start_time for c in state['chart']['candles'])
        assert client.post(f'/api/sessions/{sid}/orders',json={'action':'long','quantity':.01,'leverage':2}).status_code==200
        assert client.post(f'/api/sessions/{sid}/command',json={'action':'step','count':2}).status_code==200
        current=client.get(f'/api/sessions/{sid}?timeframe=1h').json()
        assert len(current['positions'])==1
        assert current['chart']['candles'][-1]['time']==start_time
        assert client.post('/api/sessions',json=CFG,headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/sessions',json={**CFG,'cash':-1}).status_code==422
        client.delete(f'/api/sessions/{sid}')

def test_strategy_uses_same_engine():
    s=Session(CFG)
    try:
        s.strategy('01_sma_cross.py');s.step(10)
        assert s.error is None
        assert s.cursor==s.initial_cursor+10
        assert s.actions
    finally:s.close()
