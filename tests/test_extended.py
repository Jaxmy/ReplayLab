import json,math,time
from pathlib import Path
import pandas as pd
import pytest
from app.engine import Broker
from app.session import Session
from app.data import read_bars,chart_data,select_asset,catalog,aggregate
from tests.test_engine import bar

CFG={'start':'2024-01-01','end':'2024-01-02','cash':10000,'fee':.0005,'slippage':.0002,'hedging':True}

def test_isolated_gap_cannot_consume_other_collateral():
    b=Broker(cash=1000,fee=.001,slippage=0,liquidation_fee=.01)
    try:
        bar(b,0);b.queue('long',1,10);b.queue('short',1,2);bar(b,1)
        bar(b,2,1)
        assert len(b.positions())==1 and b.positions()[0]['side']=='short'
        assert b.balance()==pytest.approx(989.8)
        assert b.account()['reserved']==50
        assert sum(f['amount'] for f in b.cashflows if f['type']=='insurance')>89
        assert b.trade_records()[0]['net_pnl']==pytest.approx(-10.1)
    finally:b.dispose()

def test_funding_is_zero_sum_between_equal_hedges():
    b=Broker(fee=0,slippage=0,funding_rate=.01,borrow_apr=0)
    try:
        bar(b,0);b.queue('long',1,2);b.queue('short',1,2);bar(b,1)
        bar(b,480)
        flows=[x for x in b.cashflows if x['type']=='funding']
        assert len(flows)==2 and sum(x['amount'] for x in flows)==0
        assert b.balance()==10000
        assert sorted(p['margin'] for p in b.positions())==[49,51]
    finally:b.dispose()

def test_pending_limit_stop_cancel_and_no_fill_at_old_price():
    b=Broker(fee=0,slippage=.001)
    try:
        bar(b,0);b.queue('long',1,2,order_type='limit',price=95)
        bar(b,1,low=98,high=103);assert not b.positions()
        bar(b,2,low=94,high=101);assert b.positions()[0]['entry']<=95
        oid=b.queue('short',1,2,order_type='stop',price=90);b.cancel(oid)
        assert not b.pending
    finally:b.dispose()

def test_csv_daily_and_random_category():
    pool=[m for m in catalog() if m['category']=='etf']
    assert len(pool)>=2
    a,n=select_asset('etf','2024-01-01','2024-02-01',123)
    assert n>=2 and select_asset('etf','2024-01-01','2024-02-01',123)[0]==a
    d,c,meta,hashes=read_bars('2024-01-01','2024-02-01',a,with_meta=True)
    assert meta['base']=='1d' and hashes and d.index[c+1]>=pd.Timestamp('2024-01-01',tz='UTC')
    s=Session({**CFG,'symbol':a,'end':'2024-02-01'})
    try:
        s.order({'action':'long','quantity':100,'leverage':1});s.step(2)
        assert s.broker.positions()[0]['quantity']==100
        assert s.broker.currency.code=='CNY'
        with pytest.raises(ValueError):s.view('1m')
    finally:s.close()

def test_indicator_parameters_and_paging_are_consistent():
    d,_=read_bars('2024-01-01','2024-01-02')
    first=chart_data(d,'7m',{'sma20':7},limit=100)
    older=chart_data(d,'7m',{'sma20':7},before=first['earliest'],limit=100)
    assert first['has_more'] and older['candles'][-1]['time']<first['earliest']
    full=chart_data(d,'7m',{'sma20':7},limit=5000)
    assert older['sma20'][-1] in full['sma20']

def test_context_never_releases_unfinished_higher_bar():
    s=Session(CFG)
    try:
        prev=s.context_frame('1h').index[-1]
        s.step(30,use_strategy=False)
        assert s.context_frame('1h').index[-1]==prev
        s.step(30,use_strategy=False)
        assert s.context_frame('1h').index[-1]==pd.Timestamp('2024-01-01',tz='UTC')
    finally:s.close()

def test_strategy_state_and_code_snapshot_survive_restore(monkeypatch,tmp_path):
    monkeypatch.setattr('app.session.ROOT',tmp_path)
    s=Session(CFG);r=None
    try:
        s.strategy('01_sma_cross.py',{'fast':5,'slow':20},'5m',['15m'])
        s.step(9);r=Session.restore(s.save())
        assert r.worker is not None and r.worker.snapshot()==s.worker.snapshot()
        s.step(10);r.step(10)
        assert r.actions==s.actions and r.broker.account()==s.broker.account()
    finally:
        s.close()
        if r:r.close()

def test_data_hash_change_refuses_restore(monkeypatch,tmp_path):
    monkeypatch.setattr('app.session.ROOT',tmp_path)
    s=Session(CFG)
    try:
        filename=s.save();path=tmp_path/'sessions'/filename;p=json.loads(path.read_text(encoding='utf-8'))
        k=next(iter(p['fingerprints']));p['fingerprints'][k]='corrupt';path.write_text(json.dumps(p),encoding='utf-8')
        with pytest.raises(ValueError,match='数据内容'):Session.restore(filename)
    finally:s.close()
