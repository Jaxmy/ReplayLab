"""Optional paid-source import; requires an existing, user-approved subscription.

No automatic call, purchase, signup or API-token persistence is performed.
"""
import argparse
import getpass
import pandas as pd
from app import market_data as m

if __name__=='__main__':
    p=argparse.ArgumentParser(description='导入已获授权的 EODHD 分时数据（需先自行确认费用和指数权限）')
    p.add_argument('--ticker',required=True);p.add_argument('--asset-id',required=True)
    p.add_argument('--name',required=True);p.add_argument('--category',choices=['index_cn','index_us','index_jp','index_kr','crypto'],required=True)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--interval',choices=['1m','5m','1h'],default='1m')
    a=p.parse_args()
    if a.interval=='5m':p.error('当前执行时钟接收 1m 或 1h；请为付费数据选择相应粒度')
    if not a.asset_id.replace('_','').replace(':','').replace('-','').isalnum():p.error('asset-id 只允许字母数字、下划线、连字符、冒号')
    token=getpass.getpass('EODHD access token (输入不会显示，也不会保存): ')
    rows=m.paid_download(a.ticker,a.start,a.end,token,a.interval)
    d=pd.DataFrame(rows)
    if d.empty:raise ValueError('订阅没有返回该资产/区间的数据')
    d.index=pd.to_datetime(d['timestamp'],unit='s',utc=True)
    d=d[['open','high','low','close','volume']].astype(float).sort_index()
    from app.data import validate_frame
    validate_frame(d)
    folder=m.ROOT/'data'/'market'/a.asset_id.replace(':','_')/a.interval
    for month,part in d.groupby(d.index.strftime('%Y-%m')):m.save_partition(folder/f'{month}.parquet',part)
    print(m.metadata(a.asset_id,a.name,a.category,a.interval,folder,'EODHD (existing subscription)',['https://eodhd.com/api/intraday/'+a.ticker]))
