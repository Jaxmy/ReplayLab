"""Read-only local providers; UTC bar OPEN timestamps."""
from pathlib import Path
from typing import Protocol
from functools import lru_cache
import hashlib,json,re,random
import pandas as pd
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data'/'legacy-btc'
LEGACY_MANIFEST=ROOT/'data'/'legacy-manifest.json'
LEGACY_ROOT=ROOT/'data'/'legacy'
PERIODS={'1m':'1min','3m':'3min','5m':'5min','15m':'15min','30m':'30min','1h':'1h','4h':'4h','1d':'1D','1w':'W-MON','1M':'MS'}
DEFAULT_INDICATORS={'sma20':20,'sma60':60,'ema20':20,'rsi':14,'bb':20,'bb_std':2.,'atr':14,'macd_fast':12,'macd_slow':26,'macd_signal':9}
def utc(v):
    t=pd.Timestamp(v)
    if pd.isna(t):raise ValueError('无效时间')
    return t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')
def duration(base):return pd.Timedelta({'1m':'1min','1h':'1h','1d':'1D'}[base])
def rule(tf):
    if tf in PERIODS:return PERIODS[tf]
    m=re.fullmatch(r'([1-9]\d{0,4})(m|h)',tf)
    if not m or int(m[1])>10080:raise ValueError('周期须为预设周期或 1–10080 的分钟/小时数')
    return m[1]+('min' if m[2]=='m' else 'h')
def validate_timeframe(tf,base):
    r=rule(tf)
    if base=='1d' and tf not in ('1d','1w','1M'):raise ValueError('日线资产只能使用日/周/月周期')
    if base=='1h' and (tf.endswith('m') or (tf.endswith('h') and int(tf[:-1])<1)):raise ValueError('小时线资产支持小时及以上周期')
    return r
class DataAdapter(Protocol):
    meta:dict
    def read(self,start,end,warmup):...
    def fingerprint(self):...
def source_path(value):
    path=Path(value)
    return path if path.is_absolute() else ROOT/path
@lru_cache(maxsize=512)
def file_digest(path,size,mtime):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def hash_files(files):return {str(p):file_digest(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files}
def validate_frame(d):
    import numpy as np
    if not d.index.is_unique or not d.index.is_monotonic_increasing:raise ValueError('时间未排序或重复')
    c=d[['open','high','low','close','volume']]
    if c.isna().any().any() or not all(pd.api.types.is_numeric_dtype(t) for t in c.dtypes) or not np.isfinite(c.to_numpy()).all():raise ValueError('OHLCV 存在无效值')
    if ((d.low<=0)|(d.low>d.high)|(d.open<d.low)|(d.open>d.high)|(d.close<d.low)|(d.close>d.high)|(d.volume<0)).any():raise ValueError('OHLCV 不合法')
    return d
class BinanceParquet:
    meta={'id':'BTCUSDT','category':'crypto','name':'Bitcoin / USDT','source':str(SOURCE),'start':'2020-01-01','end':'2026-09-21',
      'base':'1m','currency':'USDT','price_precision':2,'size_precision':6,'multiplier':1,'lot':.000001,'year_days':365,
      'note':'现货价格 · 通用模拟 · 补值分钟不成交','research_only':False,'default_fee':.0005,'default_slippage':.0002,'calendar':'24/7 UTC'}
    def read(self,start,end,warmup):
        lo=start-duration('1m')*warmup;frames=[];self.files=[]
        for month in pd.period_range(lo.tz_localize(None),end.tz_localize(None),freq='M'):
            for p in sorted((SOURCE/'1m'/f'year={month.year}'/f'month={month.month:02}').glob('*.parquet')):
                f=pq.ParquetFile(p).read(columns=['open_time','open','high','low','close','volume','is_binance_observed']).to_pandas()
                frames.append(f[(f.open_time>=lo)&(f.open_time<end)]);self.files.append(p)
        if not frames:raise ValueError('所选区间无数据')
        return pd.concat(frames,ignore_index=True).set_index('open_time').sort_index()
    def fingerprint(self):return hash_files(self.files)
class CSVAdapter:
    def __init__(self,meta):
        self.meta=dict(meta);self.files=[source_path(meta['source'])]
        self.meta['source']=str(self.files[0])
    def read(self,start,end,warmup):
        d=pd.read_csv(self.files[0]);raw=pd.to_datetime(d.pop(self.meta.get('time_column','date')),errors='raise')
        if raw.dt.tz is None:raw=raw.dt.tz_localize(self.meta.get('timezone','UTC'),ambiguous='raise',nonexistent='raise')
        d.index=pd.DatetimeIndex(raw.dt.tz_convert('UTC'));d['is_binance_observed']=d.get('is_binance_observed',True);d=d.sort_index()
        return pd.concat([d[d.index<start].tail(warmup),d[(d.index>=start)&(d.index<end)]])
    def fingerprint(self):return hash_files(self.files)
class MarketParquet:
    def __init__(self,meta):
        self.meta=dict(meta);self.source=source_path(meta['source']);self.meta['source']=str(self.source);self.files=[]
    def read(self,start,end,warmup):
        lo=start-duration(self.meta['base'])*warmup;parts=[];self.files=[]
        # Trading-calendar gaps need extra warmup days for indicators.
        if self.meta['base']=='1d':lo=start-pd.Timedelta(days=warmup*2)
        for m in pd.period_range(lo.tz_localize(None),end.tz_localize(None),freq='M'):
            p=self.source/f'{m}.parquet'
            if p.exists():
                d=pd.read_parquet(p);parts.append(d[(d.index>=lo)&(d.index<end)]);self.files.append(p)
        if not parts:raise ValueError('区间没有本地行情，下载可能尚未完成')
        d=pd.concat(parts).sort_index();d=d[~d.index.duplicated(keep='last')]
        d['is_binance_observed']=True
        return pd.concat([d[d.index<start].tail(warmup),d[d.index>=start]])
    def fingerprint(self):return hash_files(self.files)
PROVIDERS={'binance_parquet':BinanceParquet,'csv':CSVAdapter,'market_parquet':MarketParquet}
def register_provider(name,provider):PROVIDERS[name]=provider
def adapters():
    result={'BTCUSDT':BinanceParquet()} if SOURCE.exists() else {};legacy=LEGACY_MANIFEST
    if legacy.exists():
        for m in json.loads(legacy.read_text(encoding='utf-8-sig')):
            cat=m['category'];asset=f'{cat}:{m["symbol"]}';cn=cat in ('index_cn','etf','futures')
            meta={'id':asset,'name':m['name'],'category':cat,'source':str(LEGACY_ROOT/m['file']),
              'start':m['first'],'end':m['last'],'base':'1d','currency':'CNY' if cn else ('JPY' if m['symbol']=='N225' else 'KRW' if m['symbol']=='KOSPI' else 'USD'),
              'price_precision':3 if cat=='etf' else 2,'size_precision':0,'multiplier':1,'lot':100 if cat=='etf' else 1,
              'year_days':252,'calendar':'源数据交易日；日线结束于次日 00:00 UTC','research_only':cat!='etf',
              'note':'合成练习；未复现真实证券规则/复权/期货换月','default_fee':.0003,'default_slippage':.0002}
            result[asset]=CSVAdapter(meta)
    downloaded=ROOT/'data'/'downloaded-assets.json'
    if downloaded.exists():
        for m in json.loads(downloaded.read_text(encoding='utf-8')):result[m['id']]=MarketParquet(m)
    conf=ROOT/'config'/'assets.json'
    if conf.exists():
        for m in json.loads(conf.read_text(encoding='utf-8')):
            if m['adapter'] not in PROVIDERS:raise ValueError('未注册的数据适配器')
            result[m['id']]=PROVIDERS[m['adapter']](m)
    return result
def timeframes(base):return list(PERIODS) if base=='1m' else ['1h','4h','1d','1w','1M'] if base=='1h' else ['1d','1w','1M']
def trading_meta(meta):
    m=dict(meta);m['native_currency']=m['currency'];m['currency']='CNY' if m['category'] in ('index_cn','etf','futures') else 'USD'
    if m['category'].startswith('index'):
        m.update(size_precision=3,lot=.001,note='指数合成练习：1 点 = 1 '+m['currency'])
    return m
def catalog():return [{**trading_meta(a.meta),'timeframes':timeframes(a.meta['base'])} for a in adapters().values()]
def get_adapter(symbol):
    a=adapters().get(symbol)
    if a is None:raise ValueError('未知资产，请检查 config/assets.json')
    if a.meta.get('base') not in ('1m','1h','1d'):raise ValueError('当前执行时钟支持 1m/1d 基础数据；其他粒度须扩展适配器和时钟')
    return a

def coverage(meta):
    lo,hi=utc(meta['start']),utc(meta['end'])+duration(meta['base'])
    if meta.get('allow_gaps') and meta['category']!='crypto':lo=lo.normalize();hi=utc(meta['end']).normalize()+pd.Timedelta('1D')
    return lo,hi
def select_asset(category,start,end,seed):
    lo,hi=utc(start),utc(end)
    pool=[m for m in catalog() if m['category']==category and coverage(m)[0]<=lo and coverage(m)[1]>=hi]
    random.Random(seed).shuffle(pool)
    for m in pool:
        try:read_bars(start,end,m['id']);return m['id'],len(pool)
        except ValueError:continue
    raise ValueError('该类别无覆盖指定区间的本地资产')
def read_bars(start,end,symbol='BTCUSDT',warmup=300,with_meta=False,meta_override=None):
    start,end=utc(start),utc(end)
    a=(BinanceParquet() if meta_override and meta_override.get('source')==str(SOURCE) else PROVIDERS.get(meta_override.get('adapter','csv'),CSVAdapter)(meta_override) if meta_override else get_adapter(symbol))
    base=a.meta['base']
    if end<=start or end-start>pd.Timedelta(days=93 if base=='1m' else 36525):raise ValueError('分钟记录最多 93 天，日线最多 100 年')
    lo,hi=coverage(a.meta)
    if start<lo or end>hi:raise ValueError('超出数据覆盖范围')
    d=validate_frame(a.read(start,end,warmup))
    if d.empty or not (d.index>=start).any():raise ValueError('区间没有交易数据')
    if base=='1m' and not a.meta.get('allow_gaps') and (d.index.max()<end-duration(base) or d.index[d.index>=start].min()>start):raise ValueError('分钟数据未完整覆盖指定区间')
    d['bar_end']=d.index+duration(base)
    # A base candle straddling the decision time is neither known history nor
    # an executable opening after that time. Exclude it from both sides.
    if ((d.index<start)&(d.bar_end>start)).any():
        d=validate_frame(a.read(start,end,warmup+1));d['bar_end']=d.index+duration(base)
    d=pd.concat([d[d.bar_end<=start].tail(warmup),d[d.index>=start]])
    d.attrs['base']=base
    if base=='1m' and not a.meta.get('allow_gaps') and (d.index.to_series().diff().dropna()!=duration(base)).any():raise ValueError('分钟源存在未标记缺口')
    cursor=int((d.bar_end<=start).sum())-1
    return (d,cursor,dict(a.meta),a.fingerprint()) if with_meta else (d,cursor)
def aggregate(known,timeframe):
    if timeframe==known.attrs.get('base','1m'):return known.copy()
    rules={'open':'first','high':'max','low':'min','close':'last','volume':'sum','is_binance_observed':'all'}
    if 'bar_end' in known:rules['bar_end']='max'
    return known.resample(rule(timeframe),closed='left',label='left').agg(rules).dropna(subset=['open'])
def indicator_config(params=None):
    conf={**DEFAULT_INDICATORS,**(params or {})}
    if set(conf)!=set(DEFAULT_INDICATORS):raise ValueError('未知指标参数')
    for k,v in conf.items():
        if k=='bb_std':
            if not isinstance(v,(int,float)) or not .1<=v<=10:raise ValueError('布林倍数须为 0.1–10')
        elif not isinstance(v,int) or not 2<=v<=500:raise ValueError('指标周期须为 2–500 的整数')
    if conf['macd_fast']>=conf['macd_slow']:raise ValueError('MACD 快周期须小于慢周期')
    return conf
def chart_data(known,timeframe,params=None,before=None,limit=2000):
    frame=aggregate(known,timeframe);p=indicator_config(params);c=frame.close
    delta=c.diff();gain=delta.clip(lower=0).ewm(alpha=1/p['rsi'],adjust=False,min_periods=p['rsi']).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/p['rsi'],adjust=False,min_periods=p['rsi']).mean()
    rsi=(100-100/(1+gain/loss.replace(0,float('nan')))).mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
    ma=c.rolling(p['bb']).mean();std=c.rolling(p['bb']).std(ddof=0)
    macd=c.ewm(span=p['macd_fast'],adjust=False).mean()-c.ewm(span=p['macd_slow'],adjust=False).mean()
    tr=pd.concat([frame.high-frame.low,(frame.high-c.shift()).abs(),(frame.low-c.shift()).abs()],axis=1).max(axis=1)
    lines={'sma20':c.rolling(p['sma20']).mean(),'sma60':c.rolling(p['sma60']).mean(),'ema20':c.ewm(span=p['ema20'],adjust=False).mean(),
           'bb_upper':ma+p['bb_std']*std,'bb_lower':ma-p['bb_std']*std,'rsi':rsi,'macd':macd,
           'signal':macd.ewm(span=p['macd_signal'],adjust=False).mean(),'atr':tr.ewm(alpha=1/p['atr'],adjust=False).mean()}
    available=frame if before is None else frame[frame.index<pd.Timestamp(before,unit='s',tz='UTC')]
    view=available.tail(limit);idx=view.index;times=(idx.as_unit('ns').asi8//1000000000).tolist()
    result={'candles':[{'time':t,**{k:float(r[k]) for k in ['open','high','low','close']}} for t,r in zip(times,view.to_dict('records'))],
      'volume':[{'time':t,'value':float(v),'color':'#1f9d8a88' if up else '#e9677788'} for t,v,up in zip(times,view.volume,view.close>=view.open)],
      'quality':[t for t,ok in zip(times,view.is_binance_observed) if not ok],
      'has_more':len(available)>len(view),'earliest':times[0] if times else None}
    for key,s in lines.items():result[key]=[{'time':int(t.timestamp()),'value':float(v)} for t,v in s.reindex(idx).dropna().items()]
    return result
