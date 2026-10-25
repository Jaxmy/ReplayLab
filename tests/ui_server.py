"""Disposable HTTP backend for UI event regression tests; never uses user data."""
import sys,shutil,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
import uvicorn
from app import data,session,server,market_data

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='replay-ui-') as temp:
        root=Path(temp);(root/'data').mkdir();(root/'market').mkdir()
        shutil.copytree(session.MODULE_ROOT/'strategies',root/'strategies')
        idx=pd.date_range('2023-12-30',periods=6*1440,freq='min',tz='UTC')
        frame=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=idx)
        for month,group in frame.groupby(frame.index.strftime('%Y-%m')):group.to_parquet(root/'market'/f'{month}.parquet')
        meta={'id':'TESTUSD','name':'测试资产','category':'crypto','adapter':'market_parquet','base':'1m','currency':'USD','source':'market','start':idx[0].isoformat(),'end':idx[-1].isoformat(),'lot':.001,'size_precision':3,'price_precision':2,'multiplier':1,'year_days':365,'default_fee':.0005,'default_slippage':.0002,'allow_gaps':True,'note':'合成测试行情'}
        (root/'data/downloaded-assets.json').write_text(json.dumps([meta]),'utf-8')
        data.ROOT=session.ROOT=server.ROOT=root
        market_data.start=lambda:None
        uvicorn.run(server.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
