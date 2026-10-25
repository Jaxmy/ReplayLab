import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app import data,session,server

def test_initial_period_without_earlier_history_is_empty_and_tradeable():
    s=session.Session({'start':'2023-12-29','end':'2023-12-30','record_timeframe':'5m','warmup_timeframe':'5m','warmup_bars':300})
    try:
        out=s.view();assert out['warmup']['available']==0 and out['chart']['candles']==[]
        s.step(1);assert len(s.view()['chart']['candles'])==1
    finally:s.close()

@pytest.mark.parametrize('tf',['3m','5m','15m','30m','1h','2h','4h','1d'])
def test_initial_period_loads_same_period_closed_history(tf):
    with TestClient(server.app) as c:
        r=c.post('/api/sessions',json={'start':'2024-01-20','end':'2024-01-21','record_timeframe':tf,'warmup_bars':10})
        assert r.status_code==200,r.text
        out=r.json();assert out['timeframe']==tf and out['warmup']['timeframe']==tf
        assert out['warmup']['available']==10 and len(out['chart']['candles'])==10
        end=pd.Timestamp('2024-01-20',tz='UTC');offset=pd.tseries.frequencies.to_offset(data.rule(tf))
        assert all(pd.Timestamp(x['time'],unit='s',tz='UTC')+offset<=end for x in out['chart']['candles'])
        assert out['cursor']==0 and out['account']['equity']==10000
        s=server.sessions[out['id']];assert len(s.data)==1450  # base history remains bounded
        if tf=='5m':
            s.strategy('01_sma_cross.py',timeframe='5m');s.step(5)
            assert s.error is None and s.context_frame('5m').index[-1]==end
        name=c.post(f'/api/sessions/{out["id"]}/command',json={'action':'save'}).json()['file']
        restored=c.post('/api/restore/'+name,json={}).json()
        assert restored['warmup']==out['warmup']

def test_300_daily_preview_streams_hourly_source_and_checks_history_hash(monkeypatch,tmp_path):
    monkeypatch.setattr(data,'ROOT',tmp_path)
    (tmp_path/'data').mkdir();market=tmp_path/'market';market.mkdir()
    idx=pd.date_range('2022-11-01','2024-01-05',freq='h',tz='UTC')
    frame=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=idx)
    for month,group in frame.groupby(frame.index.strftime('%Y-%m')):group.to_parquet(market/f'{month}.parquet')
    meta={'id':'HOUR','name':'hour','category':'crypto','adapter':'market_parquet','source':'market','base':'1h','start':idx[0].isoformat(),'end':idx[-1].isoformat(),'currency':'USD','lot':.001,'size_precision':3,'price_precision':2,'multiplier':1,'default_fee':.0005,'default_slippage':.0002,'year_days':365,'allow_gaps':True}
    (tmp_path/'data/downloaded-assets.json').write_text(json.dumps([meta]),'utf-8')
    reads=[];original=data.MarketParquet.read
    def record_read(self,start,end,warmup):
        reads.append((end-start).days);return original(self,start,end,warmup)
    monkeypatch.setattr(data.MarketParquet,'read',record_read)
    s=session.Session({'symbol':'HOUR','start':'2024-01-02','end':'2024-01-03','record_timeframe':'1d','warmup_timeframe':'1d','warmup_bars':300})
    try:
        view=s.view();assert view['warmup']['available']==300 and len(view['chart']['candles'])==300
        assert len(s.data)==324 and max(reads)<=31
        assert view['chart']['candles'][-1]['time']==int(pd.Timestamp('2024-01-01',tz='UTC').timestamp())
        file=s.save();path=market/'2023-06.parquet';old=pd.read_parquet(path);old.iloc[23,old.columns.get_loc('close')]=100.25;old.to_parquet(path)
        with pytest.raises(ValueError,match='练习前历史'):session.Session.restore(file)
    finally:s.close()

def test_weekly_history_does_not_expose_current_unclosed_week():
    symbol=data.select_asset('etf','2024-01-20','2024-02-01',1)[0]
    s=session.Session({'symbol':symbol,'start':'2024-01-20','end':'2024-02-01','record_timeframe':'1w','warmup_timeframe':'1w','warmup_bars':10})
    try:
        assert len(s.view()['chart']['candles'])==10
        assert s.preview.index[-1]==pd.Timestamp('2024-01-08',tz='UTC')
        s.step(1);assert s.chart('1w')['candles'][-1]['time']==int(pd.Timestamp('2024-01-15',tz='UTC').timestamp())
    finally:s.close()
