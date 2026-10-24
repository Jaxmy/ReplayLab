"""Causal indicator instances: independent parameters, panes and duplicates."""
import copy, re
import numpy as np
import pandas as pd

# type: (label, default parameters, default placement)
CATALOG={
 'sma':('SMA 简单移动平均',{'period':20},'main'),
 'ema':('EMA 指数移动平均',{'period':20},'main'),
 'wma':('WMA 加权移动平均',{'period':20},'main'),
 'dema':('DEMA 双指数均线',{'period':20},'main'),
 'tema':('TEMA 三指数均线',{'period':20},'main'),
 'hma':('HMA 赫尔均线',{'period':20},'main'),
 'bb':('BOLL 布林带',{'period':20,'std':2.},'main'),
 'donchian':('Donchian 唐奇安通道',{'period':20},'main'),
 'keltner':('Keltner 肯特纳通道',{'period':20,'atr_period':14,'multiplier':2.},'main'),
 'vwap':('VWAP 日内成交量加权均价',{},'main'),
 'vwma':('VWMA 成交量加权均线',{'period':20},'main'),
 'rsi':('RSI 相对强弱',{'period':14},'separate'),
 'macd':('MACD',{'fast':12,'slow':26,'signal':9},'separate'),
 'stoch':('KDJ 随机指标',{'period':9,'smooth':3,'signal':3},'separate'),
 'stochrsi':('Stochastic RSI',{'period':14,'stoch_period':14,'smooth':3,'signal':3},'separate'),
 'atr':('ATR 平均真实波幅',{'period':14},'separate'),
 'adx':('ADX / DI 趋势强度',{'period':14},'separate'),
 'cci':('CCI 顺势指标',{'period':20},'separate'),
 'williams':('Williams %R 威廉指标',{'period':14},'separate'),
 'roc':('ROC 变动率',{'period':12},'separate'),
 'momentum':('Momentum 动量',{'period':10},'separate'),
 'obv':('OBV 能量潮',{},'separate'),
 'mfi':('MFI 资金流量',{'period':14},'separate'),
 'cmf':('CMF 蔡金资金流',{'period':20},'separate'),
 'ad':('A/D 累积派发线',{},'separate'),
 'volume':('成交量',{},'separate'),
 'volma':('成交量均线',{'period':20},'separate'),
 'trix':('TRIX 三重指数动量',{'period':15,'signal':9},'separate'),
 'ppo':('PPO 价格振荡器',{'fast':12,'slow':26,'signal':9},'separate'),
 'dpo':('DPO 去趋势振荡器（因果）',{'period':20},'separate'),
 'stddev':('标准差',{'period':20},'separate'),
 'bbwidth':('布林带宽度 %',{'period':20,'std':2.},'separate'),
 'percentb':('布林 %B',{'period':20,'std':2.},'separate'),
 'aroon':('Aroon 阿隆',{'period':25},'separate'),
 'choppiness':('CHOP 震荡指数',{'period':14},'separate'),
 'supertrend':('Supertrend 超级趋势',{'period':10,'multiplier':3.},'main'),
 'psar':('Parabolic SAR 抛物转向',{'step':0.02,'maximum':0.2},'main'),
 'ichimoku':('Ichimoku 一目均衡（当前可知）',{'conversion':9,'base':26,'span':52},'main'),
}
PALETTE=['#d6b767','#8da6ff','#59c6e3','#c49afa','#50d4b1','#f18291','#e2b37a']

def catalog():
    return [{'type':k,'name':v[0],'params':v[1],'placement':v[2]} for k,v in CATALOG.items()]

def defaults():
    return normalize([{'id':'ma20','type':'sma','params':{'period':20}},
      {'id':'ma60','type':'sma','params':{'period':60}},
      {'id':'rsi14','type':'rsi'},{'id':'vol','type':'volume'}])

def normalize(instances):
    if not isinstance(instances,list) or len(instances)>30:raise ValueError('最多 30 个指标实例')
    out=[];ids=set()
    for i,raw in enumerate(instances):
        typ=raw.get('type');ident=raw.get('id','')
        if typ not in CATALOG or not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in ids:raise ValueError('指标类型或实例 ID 无效/重复')
        ids.add(ident);name,base,placement=CATALOG[typ];params={**base,**raw.get('params',{})}
        if params.keys()!=base.keys():raise ValueError('未知指标参数')
        for k,v in params.items():
            if not isinstance(v,(int,float)) or isinstance(v,bool) or not np.isfinite(v):raise ValueError('指标参数必须为有效数值')
            if k in ('step','maximum'):
                if not .001<=v<=1:raise ValueError('SAR 加速系数须在 0.001–1 之间')
            elif k in ('std','multiplier'):
                if not .1<=v<=10:raise ValueError('指标倍数须在 0.1–10 之间')
            elif not isinstance(v,int) or not 2<=v<=500:raise ValueError('指标周期须为 2–500 的整数')
        if 'fast' in params and params['fast']>=params['slow']:raise ValueError('快周期须小于慢周期')
        if typ=='psar' and params['step']>params['maximum']:raise ValueError('SAR 步长不能大于最大加速系数')
        placement=raw.get('placement',placement);pane=raw.get('pane',ident)
        if placement not in ('main','separate') or not isinstance(pane,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',pane):raise ValueError('指标位置无效')
        color=raw.get('color',PALETTE[i%len(PALETTE)])
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('指标颜色无效')
        if not isinstance(raw.get('enabled',True),bool):raise ValueError('指标开关无效')
        out.append({'id':ident,'type':typ,'params':params,'enabled':raw.get('enabled',True),'placement':placement,'pane':pane,'color':color})
    return out

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def ema(s,n):return s.ewm(span=n,adjust=False,min_periods=n).mean()
def wma(s,n):
    w=np.arange(1,n+1);return s.rolling(n).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)
def rsi(c,n):
    delta=c.diff();gain=rma(delta.clip(lower=0),n);loss=rma(-delta.clip(upper=0),n)
    return (100-100/(1+gain/loss.replace(0,np.nan))).mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
def safe(a,b):return a/b.replace(0,np.nan)

def compute(d,typ,p):
    c,h,l,v=d.close,d.high,d.low,d.volume;n=p.get('period',20)
    tp=(h+l+c)/3;tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    ma=lambda s:s.rolling(n).mean();high=h.rolling(n).max();low=l.rolling(n).min()
    if typ=='sma':return {'':ma(c)}
    if typ=='ema':return {'':ema(c,n)}
    if typ=='wma':return {'':wma(c,n)}
    if typ in ('dema','tema'):
        a=ema(c,n);b=ema(a,n)
        return {'':2*a-b if typ=='dema' else 3*a-3*b+ema(b,n)}
    if typ=='hma':return {'':wma(2*wma(c,max(2,n//2))-wma(c,n),max(2,int(n**.5)))}
    if typ in ('bb','bbwidth','percentb'):
        m=ma(c);s=c.rolling(n).std(ddof=0)*p['std']
        if typ=='bbwidth':return {'':safe(2*s,m)*100}
        if typ=='percentb':return {'':safe(c-(m-s),2*s)}
        return {'上轨':m+s,'中轨':m,'下轨':m-s}
    if typ=='donchian':return {'上轨':high,'中轨':(high+low)/2,'下轨':low}
    if typ=='keltner':
        m=ema(c,n);a=rma(tr,p['atr_period'])*p['multiplier'];return {'上轨':m+a,'中轨':m,'下轨':m-a}
    if typ=='vwap':
        g=d.index.normalize();return {'':safe((tp*v).groupby(g).cumsum(),v.groupby(g).cumsum())}
    if typ=='vwma':return {'':safe((c*v).rolling(n).sum(),v.rolling(n).sum())}
    if typ=='rsi':return {'':rsi(c,n)}
    if typ in ('macd','ppo'):
        fast=ema(c,p['fast']);slow=ema(c,p['slow']);m=fast-slow
        if typ=='ppo':m=safe(m,slow)*100
        s=ema(m,p['signal']);return {'DIF':m,'DEA':s,'柱':m-s}
    if typ in ('stoch','stochrsi'):
        x=c if typ=='stoch' else rsi(c,n)
        hi=high if typ=='stoch' else x.rolling(p['stoch_period']).max();lo=low if typ=='stoch' else x.rolling(p['stoch_period']).min()
        k=safe(x-lo,hi-lo)*100;k=k.rolling(p['smooth']).mean();a=k.rolling(p['signal']).mean()
        return {'K':k,'D':a,**({'J':3*k-2*a} if typ=='stoch' else {})}
    if typ=='atr':return {'':rma(tr,n)}
    if typ=='adx':
        up=h.diff();down=-l.diff();plus=up.where((up>down)&(up>0),0);minus=down.where((down>up)&(down>0),0)
        a=rma(tr,n);pos=safe(rma(plus,n),a)*100;neg=safe(rma(minus,n),a)*100
        return {'ADX':rma(safe((pos-neg).abs(),pos+neg)*100,n),'+DI':pos,'-DI':neg}
    if typ=='cci':return {'':safe(tp-ma(tp),.015*tp.rolling(n).apply(lambda x:np.mean(np.abs(x-x.mean())),raw=True))}
    if typ=='williams':return {'':-100*safe(high-c,high-low)}
    if typ=='roc':return {'':c.pct_change(n)*100}
    if typ=='momentum':return {'':c-c.shift(n)}
    if typ=='obv':return {'':(np.sign(c.diff()).fillna(0)*v).cumsum()}
    if typ=='mfi':
        flow=tp*v;pos=flow.where(tp.diff()>0,0).rolling(n).sum();neg=flow.where(tp.diff()<0,0).rolling(n).sum()
        return {'':(100-100/(1+safe(pos,neg))).mask((neg==0)&(pos>0),100).mask((neg==0)&(pos==0),50)}
    if typ in ('cmf','ad'):
        flow=safe((c-l)-(h-c),h-l).fillna(0)*v
        return {'':flow.cumsum() if typ=='ad' else safe(flow.rolling(n).sum(),v.rolling(n).sum())}
    if typ=='volume':return {'':v}
    if typ=='volma':return {'':ma(v)}
    if typ=='trix':
        t=ema(ema(ema(c,n),n),n).pct_change(fill_method=None)*100;return {'TRIX':t,'信号':ema(t,p['signal'])}
    if typ=='dpo':return {'':c.shift(n//2+1)-ma(c)}
    if typ=='stddev':return {'':c.rolling(n).std(ddof=0)}
    if typ=='aroon':return {'上行':h.rolling(n+1).apply(lambda x:np.argmax(x)/n*100,raw=True),'下行':l.rolling(n+1).apply(lambda x:np.argmin(x)/n*100,raw=True)}
    if typ=='choppiness':return {'':100*np.log10(safe(tr.rolling(n).sum(),high-low))/np.log10(n)}
    if typ=='ichimoku':
        mid=lambda n:(h.rolling(n).max()+l.rolling(n).min())/2
        a=mid(p['conversion']);b=mid(p['base'])
        # Leading cloud is shifted from past values; no future candles or lagging close lookahead.
        return {'转换线':a,'基准线':b,'云 A':((a+b)/2).shift(p['base']),'云 B':mid(p['span']).shift(p['base'])}
    if typ=='psar':
        result=np.full(len(d),np.nan)
        if len(d)<2:return {'':pd.Series(result,index=d.index)}
        hv,lv,cv=h.to_numpy(),l.to_numpy(),c.to_numpy();up=True;ext=hv[0];value=lv[0];af=p['step']
        for i in range(1,len(d)):
            value+=af*(ext-value)
            if up:
                value=min(value,lv[i-1],lv[max(0,i-2)])
                if lv[i]<value:up=False;value=ext;ext=lv[i];af=p['step']
                elif hv[i]>ext:ext=hv[i];af=min(p['maximum'],af+p['step'])
            else:
                value=max(value,hv[i-1],hv[max(0,i-2)])
                if hv[i]>value:up=True;value=ext;ext=hv[i];af=p['step']
                elif lv[i]<ext:ext=lv[i];af=min(p['maximum'],af+p['step'])
            result[i]=value
        return {'':pd.Series(result,index=d.index)}
    if typ=='supertrend':
        a=rma(tr,n).to_numpy()*p['multiplier'];mid=((h+l)/2).to_numpy();cv=c.to_numpy();up=mid+a;lo=mid-a;res=np.full(len(d),np.nan);bull=True
        for i in range(1,len(d)):
            if np.isnan(a[i]):continue
            if not np.isnan(a[i-1]):
                up[i]=up[i] if up[i]<up[i-1] or cv[i-1]>up[i-1] else up[i-1]
                lo[i]=lo[i] if lo[i]>lo[i-1] or cv[i-1]<lo[i-1] else lo[i-1]
                if bull and cv[i]<lo[i-1]:bull=False
                elif not bull and cv[i]>up[i-1]:bull=True
            res[i]=lo[i] if bull else up[i]
        return {'':pd.Series(res,index=d.index)}
    raise ValueError('未知指标')

def render(frame,instances,index):
    out=[]
    for instance in instances:
        if not instance['enabled']:continue
        for j,(component,line) in enumerate(compute(frame,instance['type'],instance['params']).items()):
            s=line.reindex(index).replace([np.inf,-np.inf],np.nan).dropna()
            hist=instance['type']=='volume' or component=='柱'
            values=[{'time':int(t.timestamp()),'value':float(v),**({'color':'#50d4b188' if v>=0 else '#f1829188'} if component=='柱' else {})} for t,v in s.items()]
            out.append({'key':instance['id']+'_'+str(j),'instance':instance['id'],'label':CATALOG[instance['type']][0].split()[0]+' '+str(instance['params'])+' '+component,
              'color':instance['color'] if j==0 else PALETTE[(j+2)%len(PALETTE)],'kind':'histogram' if hist else 'line',
              'pane':instance['pane'] if instance['placement']=='separate' else 'main','scale':instance['type'] if instance['placement']=='main' and CATALOG[instance['type']][2]=='separate' else None,'values':values})
    return out
