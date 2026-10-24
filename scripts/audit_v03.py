"""Audit downloaded coverage and actual engine/chart reads without user records."""
import json
from pathlib import Path
import pandas as pd
from app.data import catalog,read_bars,chart_data
from app.indicators import defaults,render

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    results=[]
    for meta in catalog():
        if meta.get('adapter')!='market_parquet':continue
        try:
            end=pd.Timestamp(meta['end']).normalize()
            start=max(pd.Timestamp(meta['start']),end-pd.Timedelta(days=7 if meta['base']=='1m' else 30))
            if start>=end:end=pd.Timestamp(meta['end'])+pd.Timedelta(minutes=1 if meta['base']=='1m' else 60 if meta['base']=='1h' else 1440)
            d,c,loaded,hashes=read_bars(start,end,meta['id'],with_meta=True)
            chart=chart_data(d,meta['base'])
            assert chart['candles'] and hashes
            results.append({'id':meta['id'],'ok':True,'rows':meta['rows'],'start':meta['start'],'end':meta['end'],'base':meta['base'],'currency':meta['currency'],'source':meta['source'],'sample_rows':len(d)})
        except Exception as e:results.append({'id':meta['id'],'ok':False,'error':str(e)})
    (ROOT/'reports'/'data-v03.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    if not all(x['ok'] for x in results):raise SystemExit(1)
