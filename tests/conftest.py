"""Reproducible synthetic markets and isolated records; no user data required."""
import shutil,json
import pandas as pd
import numpy as np
import pytest

@pytest.fixture(scope='session')
def synthetic_market(tmp_path_factory):
    root=tmp_path_factory.mktemp('market');source=root/'data'/'legacy-btc'
    idx=pd.date_range('2023-12-29','2024-02-02',freq='min',tz='UTC',inclusive='left')
    close=100+np.sin(np.arange(len(idx))/20)
    bars=pd.DataFrame({'open_time':idx,'open':close,'high':close+.5,'low':close-.5,'close':close,'volume':10.,'is_binance_observed':True})
    for month,group in bars.groupby(idx.strftime('%Y-%m')):
        year,number=month.split('-');folder=source/'1m'/f'year={year}'/f'month={number}';folder.mkdir(parents=True)
        group.to_parquet(folder/'bars.parquet',index=False)
    legacy=root/'data'/'legacy';legacy.mkdir();items=[]
    daily=pd.DataFrame({'date':pd.date_range('2023-01-01','2024-02-03',freq='D'),'open':10.,'high':11.,'low':9.,'close':10.,'volume':100.})
    for symbol in ('ETF1','ETF2'):
        daily.to_csv(legacy/f'{symbol}.csv',index=False)
        items.append({'category':'etf','symbol':symbol,'name':symbol,'file':f'{symbol}.csv','first':'2023-01-01','last':'2024-02-03'})
    (root/'data'/'legacy-manifest.json').write_text(json.dumps(items),'utf-8')
    return root

@pytest.fixture(autouse=True)
def separate_test_sessions(monkeypatch,tmp_path,synthetic_market):
    from app import session,server,data,market_data
    shutil.copytree(session.MODULE_ROOT/'strategies',tmp_path/'strategies')
    monkeypatch.setattr(session,'ROOT',tmp_path)
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(data,'ROOT',synthetic_market)
    monkeypatch.setattr(data,'SOURCE',synthetic_market/'data'/'legacy-btc')
    monkeypatch.setattr(data,'LEGACY_ROOT',synthetic_market/'data'/'legacy')
    monkeypatch.setattr(data,'LEGACY_MANIFEST',synthetic_market/'data'/'legacy-manifest.json')
    monkeypatch.setattr(data.BinanceParquet,'meta',{**data.BinanceParquet.meta,'source':str(data.SOURCE)})
    monkeypatch.setattr(market_data,'start',lambda:None)
