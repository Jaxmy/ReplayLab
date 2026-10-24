"""Resumable free market downloads. Never purchases data or stores API keys."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib, io, json, threading, time, zipfile, uuid, shutil, subprocess, re, sys
import httpx
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
STATE={'running':False,'updated_at':None,'items':{},'message':'尚未更新'}
_lock=threading.Lock()
INDICES={
 'index_cn:000001':('000001.SS','上证指数','index_cn'),
 'index_cn:399001':('399001.SZ','深证成指','index_cn'),
 'index_cn:399006':('399006.SZ','创业板指','index_cn'),
 'index_cn:000300':('000300.SS','沪深300','index_cn'),
 'index_cn:000905':('000905.SS','中证500','index_cn'),
 'index_cn:000016':('000016.SS','上证50','index_cn'),
 'index_us:INX':('^GSPC','标普500','index_us'),
 'index_us:IXIC':('^IXIC','纳斯达克综合','index_us'),
 'index_us:DJI':('^DJI','道琼斯工业','index_us'),
 'index_us:RUT':('^RUT','罗素2000','index_us'),
 'index_global:N225':('^N225','日经225','index_jp'),
 'index_global:KOSPI':('^KS11','韩国综合指数','index_kr'),
 'index_kr:KOSDAQ':('^KQ11','韩国科斯达克','index_kr')}

def request(url,params=None,binary=False):
    last=None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=60,follow_redirects=True,headers={'User-Agent':'ReplayLab/0.3 (local historical research)'}) as c:
                r=c.get(url,params=params);r.raise_for_status()
                return r.content if binary else r.json()
        except Exception as e:
            last=e;time.sleep(min(2**attempt,8))
    raise RuntimeError(f'{url.split("?")[0]}: {type(last).__name__}')

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def register(meta):
    with _lock:
        path=ROOT/'data'/'downloaded-assets.json'
        old=json.loads(path.read_text('utf-8')) if path.exists() else []
        byid={x['id']:x for x in old};byid[meta['id']]=meta
        atomic_json(path,list(byid.values()))
        STATE['items'][meta['id']]={'status':'ready','rows':meta['rows'],'start':meta['start'],'end':meta['end'],'path':meta['source']}
        atomic_json(ROOT/'data'/'update-status.json',STATE)

def frame(rows,unit='ms'):
    d=pd.DataFrame(rows)
    if d.empty:return pd.DataFrame()
    d=d.iloc[:,:6];d.columns=['time','open','high','low','close','volume']
    d['time']=pd.to_datetime(pd.to_numeric(d.time),unit=unit,utc=True)
    d=d.set_index('time').astype(float).sort_index();return d[~d.index.duplicated(keep='last')]

def save_partition(path,d):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    d.to_parquet(tmp);tmp.replace(path)

def metadata(asset,name,category,base,folder,provider,urls):
    files=sorted(folder.glob('*.parquet'))
    if not files:raise ValueError('数据源没有可下载的有效行情')
    import pyarrow.parquet as pq
    first=pd.read_parquet(files[0]);last=pd.read_parquet(files[-1]);rows=sum(pq.ParquetFile(p).metadata.num_rows for p in files)
    cn=category=='index_cn';crypto=category=='crypto'
    result={'id':asset,'name':name,'category':category,'adapter':'market_parquet','source':str(folder),
      'start':first.index.min().isoformat(),'end':last.index.max().isoformat(),'base':base,
      'currency':'CNY' if cn else 'USD','price_precision':4 if crypto else 2,'size_precision':6 if crypto else 3,
      'multiplier':1,'lot':.000001 if crypto else .001,'year_days':365 if crypto else 252,
      'calendar':'24/7 UTC' if crypto else '交易所交易时段','allow_gaps':True,'research_only':not crypto,
      'default_fee':.0005 if crypto else .0003,'default_slippage':.0002,'rows':rows,'provider':provider,
      'note':('USDT 按 1 USD 模拟计价' if crypto else ('指数合成练习：1 点 = 1 CNY' if cn else '指数合成练习：1 点 = 1 USD')),
      'source_urls':urls,'updated_at':datetime.now(timezone.utc).isoformat()}
    register(result);return result

def binance_month(symbol,month,now):
    folder=ROOT/'data'/'market'/symbol/'1m';out=folder/f'{month}.parquet'
    if month==now.strftime('%Y-%m'):return None
    if out.exists():return out
    url=f'https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip'
    raw=ROOT/'data'/'raw'/symbol/f'{symbol}-1m-{month}.zip'
    content=raw.read_bytes() if raw.exists() else request(url,binary=True)
    checksum=request(url+'.CHECKSUM',binary=True).decode().split()[0]
    if hashlib.sha256(content).hexdigest()!=checksum:raise ValueError('Binance 历史包校验和不一致')
    raw.parent.mkdir(parents=True,exist_ok=True)
    if not raw.exists():raw.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        d=pd.read_csv(z.open(z.namelist()[0]),header=None)
    result=frame(d.values.tolist(),unit='us' if int(d.iloc[0,0])>10**14 else 'ms')
    save_partition(out,result);return out

def binance(symbol):
    api='https://api.binance.com/api/v3/klines';now=datetime.now(timezone.utc)
    first=request(api,{'symbol':symbol,'interval':'1m','startTime':0,'limit':1})[0][0]
    months=pd.period_range(pd.Timestamp(first,unit='ms'),pd.Timestamp(now).tz_localize(None),freq='M')
    with ThreadPoolExecutor(max_workers=5) as pool:
        errors=[]
        completed=0
        for f in as_completed([pool.submit(binance_month,symbol,str(m),now) for m in months[:-1]]):
            try:
                f.result();completed+=1
                STATE['items'][symbol]={'status':'downloading','completed_months':completed,'total_months':len(months),'path':str(ROOT/'data'/'market'/symbol)}
                atomic_json(ROOT/'data'/'update-status.json',STATE)
            except Exception as e:errors.append(str(e))
    # Current month is incrementally extended using the official REST API.
    folder=ROOT/'data'/'market'/symbol/'1m';out=folder/f'{now:%Y-%m}.parquet'
    old=pd.read_parquet(out) if out.exists() else pd.DataFrame()
    start=int(old.index.max().timestamp()*1000)+60000 if len(old) else int(pd.Timestamp(f'{now:%Y-%m}-01',tz='UTC').timestamp()*1000)
    end=int(pd.Timestamp(now).floor('min').timestamp()*1000)-1;parts=[old] if len(old) else []
    while start<end:
        rows=request(api,{'symbol':symbol,'interval':'1m','startTime':start,'endTime':end,'limit':1000})
        if not rows:break
        parts.append(frame(rows));start=int(rows[-1][0])+60000
    if parts:save_partition(out,pd.concat(parts).sort_index().loc[lambda d:~d.index.duplicated(keep='last')])
    meta=metadata(symbol,symbol.replace('USDT',' / USDT'),'crypto','1m',folder,'Binance spot',[api,'https://data.binance.vision/?prefix=data/spot/monthly/klines/'+symbol+'/1m/'])
    if errors:raise RuntimeError(f'已保存 {meta["rows"]} 根；{len(errors)} 个月待重试：{errors[0]}')

def bybit_month(month,now):
    folder=ROOT/'data'/'market'/'HYPEUSDT'/'1m';out=folder/f'{month}.parquet'
    current=str(month)==now.strftime('%Y-%m')
    if out.exists() and not current:return
    old=pd.read_parquet(out) if out.exists() else pd.DataFrame()
    lo=pd.Timestamp(str(month),tz='UTC');hi=min((lo+pd.offsets.MonthBegin(1)),pd.Timestamp(now).floor('min'))
    start=int(lo.timestamp()*1000) if old.empty else int(old.index.max().timestamp()*1000)+60000
    end=int(hi.timestamp()*1000)-1;parts=[old] if len(old) else []
    while end>=start:
        data=request('https://api.bybit.com/v5/market/kline',{'category':'linear','symbol':'HYPEUSDT','interval':'1','start':start,'end':end,'limit':1000})
        if data.get('retCode')!=0:raise ValueError(data.get('retMsg','Bybit 下载失败'))
        rows=data['result']['list']
        if not rows:break
        parts.append(frame(rows));end=min(int(r[0]) for r in rows)-1;time.sleep(.08)
    if parts:save_partition(out,pd.concat(parts).sort_index().loc[lambda d:~d.index.duplicated(keep='last')])

def bybit():
    now=datetime.now(timezone.utc)
    months=pd.period_range('2024-12',pd.Timestamp(now).tz_localize(None),freq='M')
    errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(bybit_month,m,now) for m in months]):
            try:f.result()
            except Exception as e:errors.append(str(e))
    meta=metadata('HYPEUSDT','HYPE / USDT · 永续','crypto','1m',ROOT/'data'/'market'/'HYPEUSDT'/'1m','Bybit linear perpetual',['https://api.bybit.com/v5/market/kline'])
    if errors:raise RuntimeError(f'已保存 {meta["rows"]} 根；{len(errors)} 个月待重试')

def yahoo(asset,ticker,name,category,interval='1d'):
    if category=='index_cn' and interval=='1d':return sina_daily(asset,name)
    now=int(time.time());window={'1m':6*86400,'1h':729*86400,'1d':now}
    from urllib.parse import quote
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe='')
    data=request(url,{'period1':-2208988800 if interval=='1d' else max(0,now-window[interval]),'period2':now,'interval':interval})
    result=data['chart']['result']
    if not result:raise ValueError(str(data['chart'].get('error')))
    r=result[0];q=r['indicators']['quote'][0]
    d=pd.DataFrame({k:q[k] for k in ('open','high','low','close','volume')},index=pd.to_datetime(r['timestamp'],unit='s',utc=True))
    d=d.dropna(subset=['open','high','low','close']);d['volume']=d.volume.fillna(0)
    # Daily records use UTC dates. Intraday retains actual exchange timestamps.
    if interval=='1d':d.index=d.index.normalize()
    d=d[d.index+pd.Timedelta({'1d':'1D','1h':'1h','1m':'1min'}[interval])<=pd.Timestamp.now(tz='UTC')]
    if d.empty:raise ValueError('无已收盘数据')
    folder=ROOT/'data'/'market'/asset.replace(':','_')/interval;folder.mkdir(parents=True,exist_ok=True)
    for m,part in d.groupby(d.index.strftime('%Y-%m')):
        path=folder/f'{m}.parquet'
        if path.exists():part=pd.concat([pd.read_parquet(path),part]).sort_index().loc[lambda x:~x.index.duplicated(keep='last')]
        save_partition(path,part)
    ident=asset if interval=='1d' else asset+':'+interval
    metadata(ident,name+(' · '+interval if interval!='1d' else ''),category,interval,folder,'Yahoo public chart (best effort)',[url])

def sina_daily(asset,name):
    code=asset.split(':')[-1];symbol=('sz' if code.startswith('399') else 'sh')+code
    url=f'https://finance.sina.com.cn/realstock/company/{symbol}/hisdata/klc_kl.js'
    content=request(url,binary=True);text=content.decode('utf-8')
    match=re.search(r'=\s*"([A-Za-z0-9+/=]+)"',text)
    if not match:raise ValueError('新浪日线格式已变更，保留原本地数据')
    node=shutil.which('node')
    if not node:raise ValueError('新浪历史解码需要已安装的 Node.js')
    result=subprocess.run([node,str(ROOT/'vendor'/'akshare-decoder'/'decode.cjs')],input=match[1],text=True,encoding='utf-8',capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('新浪历史解码失败')
    d=pd.DataFrame(json.loads(result.stdout));d['date']=pd.to_datetime(d['date'],utc=True).dt.normalize()
    d=d.set_index('date')[['open','high','low','close','volume']].astype(float).sort_index().dropna()
    d=d[d.index+pd.Timedelta('1D')<=pd.Timestamp.now(tz='UTC')]
    if len(d)<100:raise ValueError('新浪返回异常短历史，保留已有数据')
    raw=ROOT/'data'/'raw'/symbol/'klc_kl.js';raw.parent.mkdir(parents=True,exist_ok=True);raw.write_bytes(content)
    folder=ROOT/'data'/'market'/asset.replace(':','_')/'1d';folder.mkdir(parents=True,exist_ok=True)
    for month,part in d.groupby(d.index.strftime('%Y-%m')):save_partition(folder/f'{month}.parquet',part)
    metadata(asset,name,'index_cn','1d',folder,'Sina index history (AKShare decoder)',[url])

def paid_download(ticker,start,end,token,interval='1m'):
    """Explicitly configured paid adapter. Not used by automatic free updates."""
    if not token:raise ValueError('需要先确认供应商费用、指数权限并输入访问令牌')
    # Keep token out of exception text and provenance manifests.
    with httpx.Client(timeout=60) as c:
        r=c.get('https://eodhd.com/api/intraday/'+ticker,params={'api_token':token,'fmt':'json','interval':interval,'from':int(pd.Timestamp(start).timestamp()),'to':int(pd.Timestamp(end).timestamp())})
        if r.status_code!=200:raise ValueError(f'付费数据接口返回 {r.status_code}，请核验订阅权限')
        return r.json()

def run():
    if STATE['running']:return
    STATE.update(running=True,message='正在更新免费历史数据')
    atomic_json(ROOT/'data'/'update-status.json',STATE)
    tasks=[('ETHUSDT',lambda:binance('ETHUSDT')),('BNBUSDT',lambda:binance('BNBUSDT')),('HYPEUSDT',bybit),('BTCUSDT',lambda:binance('BTCUSDT'))]
    for asset,(ticker,name,cat) in INDICES.items():
        for interval in ('1d','1h','1m'):
            tasks.append((asset+':'+interval,lambda a=asset,t=ticker,n=name,c=cat,i=interval:yahoo(a,t,n,c,i)))
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            future={pool.submit(fn):key for key,fn in tasks}
            for f in as_completed(future):
                key=future[f]
                try:f.result();print(key,'ready',flush=True)
                except Exception as e:
                    STATE['items'][key]={'status':'retry','error':str(e)};print(key,str(e),flush=True)
                atomic_json(ROOT/'data'/'update-status.json',STATE)
    finally:
        STATE.update(running=False,updated_at=datetime.now(timezone.utc).isoformat(),message='更新结束；失败源下次启动重试')
        atomic_json(ROOT/'data'/'update-status.json',STATE)

def start():
    if 'pytest' in sys.modules:return
    # A file lock prevents CLI and app startup from downloading simultaneously.
    def guarded():
        import msvcrt
        path=ROOT/'data'/'update.lock';path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as f:
            f.seek(0);f.write(b'0');f.flush();f.seek(0)
            try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:return
            try:run()
            finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    threading.Thread(target=guarded,daemon=True).start()

if __name__=='__main__':
    start()
    for t in threading.enumerate():
        if t is not threading.current_thread() and not t.daemon:t.join()
    # CLI keeps its daemon downloader alive.
    while any(t.name!='MainThread' for t in threading.enumerate()):time.sleep(1)
