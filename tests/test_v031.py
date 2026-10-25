import hashlib,json
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app import data,server,session

@pytest.fixture
def sample(monkeypatch,tmp_path):
    monkeypatch.setattr(data,'ROOT',tmp_path)
    folder=tmp_path/'market';folder.mkdir()
    idx=pd.date_range('2024-01-01',periods=3*1440,freq='min',tz='UTC')
    frame=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=idx)
    frame.to_parquet(folder/'2024-01.parquet')
    meta={'id':'TESTUSD','name':'测试资产','category':'crypto','adapter':'market_parquet','base':'1m','currency':'USD','source':'market','start':idx[0].isoformat(),'end':idx[-1].isoformat(),'lot':.001,'size_precision':3,'price_precision':2,'multiplier':1,'year_days':365,'default_fee':.0005,'default_slippage':.0002,'allow_gaps':True}
    (tmp_path/'data').mkdir();(tmp_path/'data/downloaded-assets.json').write_text(json.dumps([meta]),'utf-8')
    return {'symbol':'TESTUSD','start':'2024-01-02','end':'2024-01-03'}

def test_start_history_is_visible_causal_and_not_traded(sample):
    with TestClient(server.app) as c:
        for count in (1,300,2000):
            r=c.post('/api/sessions',json={**sample,'warmup_bars':count});assert r.status_code==200,r.text
            out=r.json();sid=out['id'];available=min(count,1440)
            assert out['warmup']['available']==available
            assert len(out['chart']['candles'])==available
            assert all(x['time']<1704153600 for x in out['chart']['candles'])
            assert out['cursor']==0 and out['total']==1440 and out['equity']==[] and out['positions']==[]
            assert out['account']['equity']==10000
            c.post(f'/api/sessions/{sid}/orders',json={'action':'long','amount':100})
            c.post(f'/api/sessions/{sid}/command',json={'action':'step'})
            out=c.get(f'/api/sessions/{sid}').json()
            assert out['cursor']==1 and len(out['positions'])==1 and out['chart']['candles'][-1]['time']==1704153600
            name=c.post(f'/api/sessions/{sid}/command',json={'action':'save'}).json()['file']
            assert c.post('/api/restore/'+name,json={}).json()['warmup']['available']==available
            c.delete(f'/api/sessions/{sid}')
        out=c.post('/api/sessions',json={**sample,'start':'2024-01-01','end':'2024-01-02'}).json()
        assert out['warmup']['available']==0 and out['chart']['candles']==[]
        assert c.post('/api/sessions',json={**sample,'warmup_bars':0}).status_code==422

def test_failed_replacement_preserves_current_record_and_indicator_presets(sample,tmp_path):
    with TestClient(server.app) as c:
        preset=[{'id':'custom','type':'sma','params':{'period':7}}]
        out=c.post('/api/sessions',json={**sample,'indicator_instances':preset}).json();sid=out['id']
        assert out['indicator_instances'][0]['params']=={'period':7}
        bad=c.post('/api/sessions',json={**sample,'replace_session_id':sid,'end':'2023-01-01'})
        assert bad.status_code==400 and c.get(f'/api/sessions/{sid}').status_code==200
        bad=c.post('/api/sessions',json={**sample,'replace_session_id':sid,'indicator_instances':[{'id':'bad','type':'sma','params':{'period':0}}]})
        assert bad.status_code==400 and len(server.sessions)==1
        replacement=c.post('/api/sessions',json={**sample,'replace_session_id':sid})
        assert replacement.status_code==200 and c.get(f'/api/sessions/{sid}').status_code==404
        assert (tmp_path/'sessions'/f'{sid}.json').exists()
        filename=replacement.json()['id']+'.json';path=tmp_path/'sessions'/filename
        payload=json.loads(path.read_text('utf-8'));payload['platform']='0.3.0';path.write_text(json.dumps(payload),'utf-8')
        assert c.post('/api/restore/'+filename,json={}).status_code==200

@pytest.mark.parametrize('base,freq',[('1h','h'),('1d','D')])
def test_nonminute_asset_history_and_midbar_start_are_causal(sample,tmp_path,base,freq):
    path=tmp_path/'data/downloaded-assets.json';meta=json.loads(path.read_text('utf-8'))[0]
    idx=pd.date_range('2023-10-01',end='2024-01-04',freq=freq,tz='UTC')
    frame=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=idx)
    for month,group in frame.groupby(frame.index.strftime('%Y-%m')):group.to_parquet(tmp_path/'market'/f'{month}.parquet')
    meta.update(base=base,start=idx[0].isoformat(),end=idx[-1].isoformat());path.write_text(json.dumps([meta]),'utf-8')
    with TestClient(server.app) as c:
        out=c.post('/api/sessions',json={**sample,'start':'2024-01-01T00:30Z','warmup_bars':50}).json()
        assert out['warmup']['available']==50
        assert out['warmup']['end']<=int(pd.Timestamp('2024-01-01T00:30Z').timestamp())
        s=server.sessions[out['id']]
        assert s.data.index[s.cursor+1]>=pd.Timestamp('2024-01-01T00:30Z')

def test_bulk_delete_validates_entire_batch_closes_live_record_and_reclaims_code(sample,tmp_path):
    with TestClient(server.app) as c:
        ids=[c.post('/api/sessions',json=sample).json()['id'] for _ in range(2)]
        files=[x+'.json' for x in ids];directory=tmp_path/'sessions'
        digest=hashlib.sha256(b'pass').hexdigest();code=directory/'code';code.mkdir()
        (code/(digest+'.py')).write_text('pass','utf-8')
        for name in files:
            path=directory/name;payload=json.loads(path.read_text('utf-8'));payload['strategy']={'sha256':digest};path.write_text(json.dumps(payload),'utf-8')
        backups=directory/'legacy-backup';backups.mkdir();(backups/files[0]).write_bytes((directory/files[0]).read_bytes())
        reports=tmp_path/'reports';reports.mkdir();(reports/(ids[0]+'-report.html')).write_text('saved report')
        bad=c.request('DELETE','/api/saved',json={'files':[files[0],'../outside.json']})
        assert bad.status_code==400 and (directory/files[0]).exists()
        job={'sid':ids[0],'status':'running'};server.jobs['delete-test']=job
        try:assert c.request('DELETE','/api/saved',json={'files':files}).status_code==400
        finally:del server.jobs['delete-test']
        out=c.request('DELETE','/api/saved',json={'files':[files[0],files[0]]}).json()
        assert out['deleted']==[files[0]] and out['closed']==[ids[0]] and out['freed_bytes']>0
        assert not (directory/files[0]).exists() and not (backups/files[0]).exists()
        assert (code/(digest+'.py')).exists() and (reports/(ids[0]+'-report.html')).exists()
        assert c.post('/api/restore/'+files[0],json={}).status_code==404
        c.request('DELETE','/api/saved',json={'files':[files[1]]})
        assert not (code/(digest+'.py')).exists() and c.get('/api/saved').json()==[]
        assert c.request('DELETE','/api/saved',json={'files':files}).json()['missing']==files
    assert not list(directory.glob('*.json'))  # shutdown must not recreate deleted records
