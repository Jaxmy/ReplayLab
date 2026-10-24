import copy,json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app import indicators as ind
from app.engine import Broker
from app.session import Session
from app.server import app
from app.data import read_bars
from tests.test_engine import bar

CFG={'start':'2024-01-01','end':'2024-01-02','cash':10000,'fee':.0005,'slippage':.0002}

def test_amount_is_converted_at_execution_price_and_supports_notional():
    b=Broker(fee=0,slippage=0)
    try:
        bar(b,0,100);b.queue('long',amount=100,leverage=2,amount_mode='margin')
        bar(b,1,200,low=200,high=200)
        assert b.positions()[0]['quantity']==1 and b.positions()[0]['margin']==100
        b.queue('short',amount=100,leverage=2,amount_mode='notional');bar(b,2,200,low=200,high=200)
        assert b.positions()[1]['quantity']==.5 and b.positions()[1]['margin']==50
        with pytest.raises(ValueError):b.queue('long',amount=float('nan'))
    finally:b.dispose()

def test_all_indicators_are_finite_and_causal_with_distinct_duplicates():
    rng=np.random.default_rng(42);close=100+np.cumsum(rng.normal(0,.3,800))
    d=pd.DataFrame({'open':close,'high':close+.5,'low':close-.5,'close':close,'volume':rng.integers(1,100,800)},index=pd.date_range('2024-01-01',periods=800,freq='min',tz='UTC'))
    for typ,(_,params,_) in ind.CATALOG.items():
        full=ind.compute(d,typ,params);prefix=ind.compute(d.iloc[:650],typ,params)
        for key in full:
            np.testing.assert_allclose(full[key].iloc[:650],prefix[key],equal_nan=True,err_msg=typ)
        inst=ind.normalize([{'id':'one','type':typ}]);render=ind.render(d,inst,d.index)
        assert render and all(np.isfinite(x['value']) for line in render for x in line['values'])
    instances=ind.normalize([{'id':'a','type':'sma','params':{'period':5}}, {'id':'b','type':'sma','params':{'period':60}}])
    rendered=ind.render(d,instances,d.index)
    assert rendered[0]['key']!=rendered[1]['key'] and rendered[0]['values'][-1]!=rendered[1]['values'][-1]
    with pytest.raises(ValueError):ind.normalize([{'id':'a','type':'rsi','params':{'period':0}}])

def test_record_names_restore_identity_and_branch():
    with TestClient(app) as c:
        a=c.post('/api/sessions',json=CFG).json();sid=a['id']
        assert a['name'].endswith('_1m_001')
        assert c.post(f'/api/sessions/{sid}/command',json={'action':'record_timeframe','timeframe':'5m'}).status_code==200
        assert c.get(f'/api/sessions/{sid}').json()['name'].endswith('_5m_001')
        assert c.post(f'/api/sessions/{sid}/command',json={'action':'rename','name':'我的练习'}).status_code==200
        records=c.get('/api/saved').json();assert records[0]['name']=='我的练习'
        restored=c.post('/api/restore/'+sid+'.json',json={}).json();assert restored['id']==sid and restored['name']=='我的练习' and restored['timeframe']=='5m'
        c.post(f'/api/sessions/{sid}/command',json={'action':'record_timeframe','timeframe':'7m'})
        assert c.post('/api/restore/'+sid+'.json',json={}).json()['timeframe']=='7m'
        b=c.post(f'/api/sessions/{sid}/branch',json={}).json();assert b['id']!=sid and '分支' in b['name']
        ins=ind.defaults();ins.append({**ins[0],'id':'second','params':{'period':7}})
        assert c.post(f'/api/sessions/{sid}/command',json={'action':'indicators','instances':ins}).status_code==200
        out=c.get(f'/api/sessions/{sid}').json()
        assert len(out['indicator_instances'])==5 and len(out['chart']['indicator_series'])==5
        c.post(f'/api/sessions/{sid}/orders',json={'action':'long','amount':1000,'amount_mode':'margin','leverage':2})
        c.post(f'/api/sessions/{sid}/command',json={'action':'step','count':2})
        out=c.get(f'/api/sessions/{sid}').json();assert out['positions'][0]['margin']<=1000.01
        assert c.get(f'/api/sessions/{sid}/export').json()['name']=='我的练习'

def test_updated_partition_append_does_not_break_old_record(monkeypatch,tmp_path):
    from app import data
    monkeypatch.setattr(data,'ROOT',tmp_path)
    folder=tmp_path/'market';folder.mkdir()
    d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=pd.date_range('2024-01-01',periods=1500,freq='min',tz='UTC'))
    path=folder/'2024-01.parquet';d.iloc[:1440].to_parquet(path)
    meta={'id':'TESTUSD','name':'test','category':'crypto','adapter':'market_parquet','base':'1m','currency':'USD','source':'market','start':'2024-01-01','end':'2024-01-01T23:59Z','lot':.000001,'size_precision':6,'price_precision':2,'multiplier':1,'year_days':365,'default_fee':.0005,'default_slippage':.0002,'allow_gaps':True}
    manifest=tmp_path/'data';manifest.mkdir();(manifest/'downloaded-assets.json').write_text(json.dumps([meta]),'utf-8')
    s=Session({**CFG,'symbol':'TESTUSD'});r=None
    try:
        s.step(2);name=s.save();d.to_parquet(path)
        r=Session.restore(name);assert r.broker.account()==s.broker.account() and r.window_hash==s.window_hash
        r.close();r=None
        d.iloc[1,d.columns.get_loc('close')]=100.5;d.to_parquet(path)
        with pytest.raises(ValueError,match='数据内容'):Session.restore(name)
    finally:
        s.close()
        if r:r.close()

def test_hourly_exchange_offset_never_exposes_future_close(monkeypatch,tmp_path):
    from app import data
    monkeypatch.setattr(data,'ROOT',tmp_path)
    folder=tmp_path/'market';folder.mkdir()
    d=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=pd.date_range('2024-01-01T13:30Z',periods=8,freq='h'))
    d.to_parquet(folder/'2024-01.parquet')
    meta={'id':'OFFSET','name':'offset','category':'index_us','adapter':'market_parquet','base':'1h','currency':'USD','source':str(folder),'start':d.index[0].isoformat(),'end':d.index[-1].isoformat(),'lot':.001,'size_precision':3,'price_precision':2,'multiplier':1,'year_days':252,'default_fee':.0003,'default_slippage':.0002,'allow_gaps':True}
    manifest=tmp_path/'data';manifest.mkdir();(manifest/'downloaded-assets.json').write_text(json.dumps([meta]),'utf-8')
    s=Session({**CFG,'symbol':'OFFSET','start':'2024-01-01T14:30Z','end':'2024-01-01T21:30Z'})
    try:
        assert s.context_frame('1h').index[-1]==d.index[0]
        # 12:00–16:00 UTC bucket contains the 15:30–16:30 source candle.
        s.step(1,use_strategy=False);assert s.context_frame('4h').empty
        s.step(1,use_strategy=False);assert not s.context_frame('4h').empty
    finally:s.close()

def test_archive_microseconds_and_checksum(monkeypatch,tmp_path):
    import hashlib,io,zipfile
    from datetime import datetime,timezone
    from app import market_data as m
    monkeypatch.setattr(m,'ROOT',tmp_path)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('x.csv','1735689600000000,100,101,99,100,10,0,0,0,0,0,0\n')
    content=buf.getvalue()
    monkeypatch.setattr(m,'request',lambda u,binary:hashlib.sha256(content).hexdigest().encode() if u.endswith('CHECKSUM') else content)
    path=m.binance_month('ETHUSDT','2025-01',datetime(2026,1,1,tzinfo=timezone.utc))
    assert pd.read_parquet(path).index[0]==pd.Timestamp('2025-01-01',tz='UTC')
    monkeypatch.setattr(m,'request',lambda u,binary:b'bad' if u.endswith('CHECKSUM') else content)
    with pytest.raises(ValueError,match='校验和'):m.binance_month('BNBUSDT','2025-01',datetime(2026,1,1,tzinfo=timezone.utc))
    with pytest.raises(ValueError,match='令牌'):m.paid_download('SPX.INDX','2024-01-01','2024-01-02',token='')

def test_report_artifact_is_saved_and_rejects_invalid_image(tmp_path):
    import base64
    png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII='
    with TestClient(app) as c:
        sid=c.post('/api/sessions',json=CFG).json()['id']
        r=c.post(f'/api/sessions/{sid}/artifacts',json={'format':'png','data':'data:image/png;base64,'+png})
        assert r.status_code==200,r.text
        assert Path(r.json()['file']).read_bytes()==base64.b64decode(png)
        r=c.post(f'/api/sessions/{sid}/artifacts',json={'format':'png','data':'data:image/png;base64,bad'})
        assert r.status_code==400
        r=c.post(f'/api/sessions/{sid}/artifacts',json={'format':'html','data':'<!doctype html><title>测试</title>'})
        assert r.status_code==200 and Path(r.json()['file']).read_text('utf-8').endswith('</title>')

def test_v02_record_keeps_original_btc_source_after_catalog_update(tmp_path):
    from app.data import BinanceParquet
    s=Session({**CFG,'_snapshot_meta':dict(BinanceParquet.meta)});r=None
    try:
        s.order({'action':'long','quantity':.01,'leverage':2});s.step(3)
        filename=s.save();path=tmp_path/'sessions'/filename;payload=json.loads(path.read_text('utf-8'))
        payload['platform']='0.2.0';payload['config'].pop('_snapshot_meta',None)
        for k in ('window_hash','fingerprints_signature','indicator_instances'):payload.pop(k,None)
        path.write_text(json.dumps(payload),'utf-8')
        r=Session.restore(filename)
        assert r.meta['source']==str(BinanceParquet.meta['source']) and r.broker.currency.code=='USDT'
        assert r.broker.positions()==s.broker.positions() and r.broker.account()==s.broker.account()
    finally:
        s.close()
        if r:r.close()
