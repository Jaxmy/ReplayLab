from pathlib import Path
from collections import deque
import hashlib,json,math,queue,subprocess,sys,threading,uuid,bisect
import pandas as pd
from app.data import read_bars,read_preview,chart_data,duration,aggregate,rule,validate_timeframe,indicator_config,select_asset,utc,trading_meta,timeframes
from app.engine import Broker
ROOT=Path(__file__).resolve().parents[1]
MODULE_ROOT=ROOT
from app import indicators as ind
VERSION='0.3.2'


def migrate_records():
    """Add display metadata to legacy records; preserve an untouched backup."""
    import shutil
    directory=ROOT/'sessions';directory.mkdir(parents=True,exist_ok=True);counts={};used={}
    files=sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime)
    for file in files:
        try:
            old=json.loads(file.read_text('utf-8'));m=old.get('meta',{});tf=old.get('record_timeframe',m.get('base','1m'))
            key=old.get('config',{}).get('symbol','BTCUSDT')
            sequence=old.get('sequence',counts.get(key,0)+1)
            conflict=sequence in used.setdefault(key,set())
            if conflict:sequence=counts.get(key,0)+1
            counts[key]=max(sequence,counts.get(key,0));used[key].add(sequence)
            if 'name' in old and not conflict:continue
            backup=directory/'legacy-backup';backup.mkdir(exist_ok=True)
            if not (backup/file.name).exists():shutil.copy2(file,backup/file.name)
            if not old.get('custom_name'):old['name']=f'{m.get("name",key)}_{tf}_{sequence:03}'
            old.update(sequence=sequence,record_timeframe=tf,custom_name=old.get('custom_name',False))
            stat=file.stat();temp=file.with_suffix('.tmp');temp.write_text(json.dumps(old,ensure_ascii=False),encoding='utf-8');temp.replace(file)
            import os
            os.utime(file,(stat.st_atime,stat.st_mtime))
        except (ValueError,OSError):continue

class StrategyProcess:
    def __init__(self,path,state=None):
        self.p=subprocess.Popen([sys.executable,'-u',str(MODULE_ROOT/'app'/'strategy_worker.py'),str(path)],
          stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.responses=queue.Queue();self.errors=deque(maxlen=20)
        threading.Thread(target=self.read,args=(self.p.stdout,self.responses.put),daemon=True).start()
        threading.Thread(target=self.read,args=(self.p.stderr,self.errors.append),daemon=True).start()
        if state is not None:self.exchange({'_op':'restore','state':state})
    @staticmethod
    def read(pipe,callback):
        for line in pipe:callback(line)
    def exchange(self,context):
        try:
            self.p.stdin.write(json.dumps(context,allow_nan=False)+'\n');self.p.stdin.flush()
            msg=json.loads(self.responses.get(timeout=3))
            if 'error' in msg:raise ValueError(msg['error'])
            return msg
        except Exception as exc:
            self.close();raise ValueError(f'策略失败/超时: {exc}; {"".join(self.errors)[-500:]}')
    def ask(self,context):
        orders=self.exchange(context).get('orders',[])
        if not isinstance(orders,list) or len(orders)>20:raise ValueError('每根最多返回 20 条订单')
        return orders
    def snapshot(self):return self.exchange({'_op':'snapshot'})['state']
    def close(self):
        if self.p.poll() is None:self.p.kill()
        self.p.wait(timeout=5)

class Session:
    def __init__(self,config):
        self.id=uuid.uuid4().hex[:12];self.config=dict(config)
        instances=ind.normalize(config.get('indicator_instances',ind.defaults()))
        if config.get('random_asset'):
            self.config['symbol'],self.config['pool_size']=select_asset(config['category'],config['start'],config['end'],config.get('seed',0),config.get('record_timeframe'))
        self.data,self.cursor,self.meta,self.fingerprints=read_bars(config['start'],config['end'],self.config.get('symbol','BTCUSDT'),warmup=config.get('warmup_bars',300),with_meta=True,meta_override=config.get('_snapshot_meta'))
        self.window_hash=hashlib.sha256(pd.util.hash_pandas_object(self.data,index=True).values.tobytes()).hexdigest()
        if config.get('_snapshot_meta'):self.meta=config['_snapshot_meta']
        else:self.meta=trading_meta(self.meta)
        self.record_timeframe=config.get('record_timeframe') or self.meta['base']
        validate_timeframe(self.record_timeframe,self.meta['base'])
        self.preview_timeframe=config.get('warmup_timeframe')
        self.preview=None;self.preview_hash=None
        if self.preview_timeframe:
            validate_timeframe(self.preview_timeframe,self.meta['base'])
            if self.preview_timeframe==self.meta['base']:
                self.preview=self.data.iloc[:self.cursor+1].copy()
            else:
                self.preview=read_preview(config['start'],self.config.get('symbol','BTCUSDT'),self.preview_timeframe,config.get('warmup_bars',300),meta_override=config.get('_snapshot_meta'))
            self.preview_hash=hashlib.sha256(pd.util.hash_pandas_object(self.preview,index=True).values.tobytes()).hexdigest()
        migrate_records()
        directory=ROOT/'sessions';directory.mkdir(parents=True,exist_ok=True)
        # Monotonically allocate a human-readable default name within this asset/timeframe.
        numbers=[]
        for file in directory.glob('*.json'):
            try:
                old=json.loads(file.read_text('utf-8'))
                if old.get('config',{}).get('symbol','BTCUSDT')==self.config.get('symbol','BTCUSDT'):numbers.append(old.get('sequence',0))
            except (ValueError,OSError):continue
        self.sequence=max(numbers,default=0)+1
        self.record_name=f'{self.meta["name"]}_{self.record_timeframe}_{self.sequence:03}'
        self.custom_name=False
        self.initial_cursor=self.cursor
        for key in ('fee','slippage'):
            if self.config.get(key) is None:self.config[key]=self.meta['default_'+key]
        config=self.config
        validate_timeframe(self.config.get('strategy_timeframe',self.meta['base']),self.meta['base'])
        self.broker=Broker(config.get('cash',10000),config.get('fee',self.meta['default_fee']),config.get('slippage',self.meta['default_slippage']),
          config.get('hedging',True),spec=self.meta,liquidation_fee=config.get('liquidation_fee',.001),funding_rate=config.get('funding_rate',0.),
          funding_hours=config.get('funding_hours',8),borrow_apr=config.get('borrow_apr',0.),maintenance=config.get('maintenance',.005))
        self.actions=[];self.curve=[];self.worker=None;self.strategy_name=None;self.strategy_info=None;self.error=None
        self.news=[];self.chart_params=indicator_config(config.get('indicators'));self.timeframe_cache={};self.context_cache={}
        self.chart_layout={};self.indicator_instances=instances
        self.event_cursor=0;self.last_trigger=None;self.finished_explicit=False;self.last_saved_step=0
        if self.cursor>=0:self.broker.tick(self.data.iloc[self.cursor].close,int(self.data.iloc[self.cursor].bar_end.value)-1)

    def order(self,command,record=True):
        if self.cursor>=len(self.data)-1 or self.finished_explicit:raise ValueError('回放已结束，不能再下单')
        self.broker.queue(**command)
        if record:self.actions.append({'kind':'order','value':command})
    def cancel(self,order_id=None,record=True):
        self.broker.cancel(order_id)
        if record:self.actions.append({'kind':'cancel','value':order_id})
    def leverage(self,pid,value,record=True):
        self.broker.change_leverage(pid,value)
        if record:self.actions.append({'kind':'leverage','id':pid,'value':value})

    def context_frame(self,tf):
        if tf not in self.context_cache:
            validate_timeframe(tf,self.meta['base']);f=self.merge_preview(aggregate(self.data,tf),tf)
            ends=f.index+pd.tseries.frequencies.to_offset(rule(tf)) if tf!=self.meta['base'] else f.bar_end
            # Offset exchange hourly candles may close after a UTC bucket boundary.
            # A higher-timeframe strategy cannot see that candle before its real close.
            ends=pd.DatetimeIndex([max(boundary,actual) for boundary,actual in zip(ends,f.bar_end)])
            # Precomputed complete bars are released only after their close boundary.
            self.context_cache[tf]=(f,list(pd.DatetimeIndex(ends).as_unit('ns').asi8))
        f,ends=self.context_cache[tf]
        now=self.data.iloc[self.cursor].bar_end.value if self.cursor>=0 else utc(self.config['start']).value
        count=bisect.bisect_right(ends,now)
        return f.iloc[max(0,count-500):count]

    @staticmethod
    def rows(frame):
        records=frame[['open','high','low','close','volume']].astype(float).to_dict('records')
        for r,t in zip(records,frame.index.as_unit('ns').asi8):r['time']=int(t//1000000000)
        return records

    def strategy(self,name,params=None,timeframe=None,contexts=None,resume=None):
        if self.worker:self.worker.close()
        self.worker=None;self.strategy_name=None;self.strategy_info=None;self.error=None
        if not name:return
        path=MODULE_ROOT/'strategies'/name
        if Path(name).name!=name or path.suffix!='.py' or (not resume and not path.is_file()):raise ValueError('无效策略文件')
        tf=timeframe or self.config.get('strategy_timeframe',self.meta['base']);validate_timeframe(tf,self.meta['base'])
        ctxs=list(dict.fromkeys([tf]+(contexts or [])))
        if len(ctxs)>5:raise ValueError('最多 5 个策略上下文周期')
        for ctx in ctxs:validate_timeframe(ctx,self.meta['base'])
        code=resume['code'] if resume else path.read_text(encoding='utf-8')
        digest=hashlib.sha256(code.encode()).hexdigest();directory=ROOT/'sessions'/'code';directory.mkdir(parents=True,exist_ok=True)
        snapshot=directory/f'{digest}.py';snapshot.write_text(code,encoding='utf-8')
        self.worker=StrategyProcess(snapshot,resume.get('state') if resume else None);self.strategy_name=name
        self.strategy_info={'name':name,'code':code,'sha256':digest,'params':params or {},'timeframe':tf,'contexts':ctxs}
        f=self.context_frame(tf);self.last_trigger=int(f.index[-1].value) if len(f) else None
        self.event_cursor=len(self.broker.events)

    def step(self,count=1,record=True,use_strategy=True):
        for _ in range(count):
            if self.cursor+1>=len(self.data) or self.finished_explicit:break
            self.cursor+=1;self.broker.bar(self.data.index[self.cursor],self.data.iloc[self.cursor])
            if record:self.actions.append({'kind':'step'})
            self.curve.append({'time':int(self.data.iloc[self.cursor].bar_end.timestamp())-1,'value':self.broker.account()['equity']})
            self.timeframe_cache.clear()
            if self.worker and use_strategy and self.cursor<len(self.data)-1:
                tf=self.strategy_info['timeframe'];frame=self.context_frame(tf)
                trigger=int(frame.index[-1].value) if len(frame) else None
                if trigger is not None and trigger!=self.last_trigger:
                    self.last_trigger=trigger
                    try:
                        events=self.broker.events[self.event_cursor:];self.event_cursor=len(self.broker.events)
                        context={'bars':self.rows(frame),'timeframes':{t:self.rows(self.context_frame(t)) for t in self.strategy_info['contexts']},
                          'account':self.broker.account(),'positions':self.broker.positions(),'pending':self.broker.pending,'events':events,
                          'parameters':self.strategy_info['params'],'asset':self.meta,'timeframe':tf}
                        for cmd in self.worker.ask(context):self.order(cmd,record=record)
                    except Exception as exc:
                        self.strategy(None);self.error=str(exc);break
        if record and len(self.actions)-self.last_saved_step>=250:
            self.save();self.last_saved_step=len(self.actions)

    def finish(self,force_close=False,record=True):
        if self.cursor<self.initial_cursor+1:raise ValueError('请先推进至练习时段')
        if force_close:
            if not bool(self.data.iloc[self.cursor].is_binance_observed):raise ValueError('补值分钟不能强制成交')
            for p in self.broker.positions():self.broker._close(p['id'],reason='end_of_session')
        self.cancel(record=False);self.finished_explicit=True
        if self.worker:self.worker.close();self.worker=None
        if self.curve:self.curve[-1]['value']=self.broker.account()['equity']
        if record:self.actions.append({'kind':'finish','value':force_close})

    def report(self,full=False):
        eq=[self.broker.initial]+[x['value'] for x in self.curve];peak=eq[0];dd=0.;drawdowns=[]
        for point,v in zip(self.curve,eq[1:]):
            peak=max(peak,v);drop=(peak-v)/peak if peak>0 else 0;dd=max(dd,drop);drawdowns.append({'time':point['time'],'value':-drop*100})
        sharpe=None;annual=None;volatility=None;days=0
        if len(self.curve)>1:
            points=[{'time':int(utc(self.config['start']).timestamp())-1,'value':self.broker.initial}]+self.curve
            s=pd.Series([x['value'] for x in points],index=pd.to_datetime([x['time'] for x in points],unit='s',utc=True))
            days=(self.curve[-1]['time']-utc(self.config['start']).timestamp()+1)/86400
            daily=s.resample('1D').last()
            daily=daily.ffill() if self.meta['year_days']==365 else daily.dropna()
            returns=daily.pct_change().dropna();rf=self.config.get('risk_free',0.)/self.meta['year_days']
            if len(returns)>=20 and returns.std()>0:
                sharpe=float((returns.mean()-rf)/returns.std()*math.sqrt(self.meta['year_days']));volatility=float(returns.std()*math.sqrt(self.meta['year_days'])*100)
            if days>=30 and eq[-1]>0:
                exponent=math.log(eq[-1]/eq[0])*365.25/days
                annual=math.expm1(exponent)*100 if exponent<50 else None
        trades=self.broker.trade_records();pnls=[p['net_pnl'] for p in trades];wins=[p for p in pnls if p>0];losses=[p for p in pnls if p<0]
        fees=sum(m.as_double() for p in self.broker.engine.cache.positions() for m in p.commissions())
        flow={k:sum(f['amount'] for f in self.broker.cashflows if f['type']==k) for k in ('funding','borrow_interest','liquidation_fee','insurance')}
        fills=[e for e in self.broker.events if e['type']=='fill'];turnover=sum(e['quantity']*e['price']*self.broker.multiplier for e in fills)
        return {'max_drawdown_pct':dd*100,'sharpe':sharpe,'annual_return_pct':annual,'annual_volatility_pct':volatility,
          'total_return_pct':self.broker.account()['return_pct'],'closed_trades':len(pnls),'win_rate':len(wins)/len(pnls)*100 if pnls else None,
          'profit_factor':sum(wins)/-sum(losses) if losses else None,'payoff_ratio':(sum(wins)/len(wins))/(-sum(losses)/len(losses)) if wins and losses else None,
          'average_trade':sum(pnls)/len(pnls) if pnls else None,'average_holding_seconds':sum((p['closed_ns']-p['opened_ns'])/1e9 for p in trades)/len(trades) if trades else None,
          'turnover':turnover,'commissions':fees,'cashflows':flow,'trades':trades,'drawdown':drawdowns if full else drawdowns[-10000:],
          'sharpe_note':f'日频净值；{self.meta["year_days"]} 天年化；至少 20 个日收益样本；年化收益至少 30 天',
          'ending':'已强制平仓' if self.finished_explicit and not self.broker.positions() else '未平仓按当前价格盯市',
          'limitations':['通用合成账户，实际交易所规则与标记价格未复现','OHLC 采用保守触发；无订单簿排队/容量约束',
            '资金费/借贷费为用户设定固定模型；保险赔付为模拟记账，不代表真实赔付','证券日线为价格练习，不包含 T+1、税费、分红或换月校正']}

    def merge_preview(self,frame,timeframe,initial=False):
        if self.preview is not None and timeframe==self.preview_timeframe:
            frame=pd.concat([self.preview,frame[~frame.index.isin(self.preview.index)]]).sort_index()
            frame.index=pd.to_datetime(frame.index,utc=True)
            if initial and self.cursor==self.initial_cursor:
                offset=pd.tseries.frequencies.to_offset(rule(timeframe))
                frame=frame[frame.index+offset<=utc(self.config['start'])]
            frame.attrs['base']=timeframe
        return frame

    def chart(self,timeframe,params=None,before=None,limit=2000):
        validate_timeframe(timeframe,self.meta['base']);conf=indicator_config(params or self.chart_params)
        key=(timeframe,json.dumps(conf,sort_keys=True),json.dumps(self.indicator_instances,sort_keys=True),before,limit)
        if key not in self.timeframe_cache:
            known=self.data.iloc[:self.cursor+1];frame=self.merge_preview(aggregate(known,timeframe),timeframe,initial=True)
            frame.attrs['base']=timeframe
            result=chart_data(frame,timeframe,conf,before,limit)
            idx=pd.to_datetime([x['time'] for x in result['candles']],unit='s',utc=True)
            result['indicator_series']=ind.render(frame,self.indicator_instances,idx)
            self.timeframe_cache[key]=result
        return self.timeframe_cache[key]

    def view(self,timeframe=None):
        tf=timeframe or self.record_timeframe or self.meta['base'];done=self.cursor>=len(self.data)-1 or self.finished_explicit
        blind=self.config.get('blind',False) and not done
        config={k:v for k,v in self.config.items() if not k.startswith('_')};meta=dict(self.meta)
        meta['timeframes']=timeframes(self.meta['base'])
        if blind:config['symbol']='隐藏资产';meta.update(id='隐藏资产',name='盲测练习',source='隐藏')
        now=int(self.data.iloc[self.cursor].bar_end.timestamp())-1 if self.cursor>=0 else int(utc(self.config['start']).timestamp())-1
        preview=self.preview if self.preview is not None else self.data.iloc[:self.initial_cursor+1]
        return {'id':self.id,'name':'盲测记录' if blind else self.record_name,'record_timeframe':self.record_timeframe,'custom_name':self.custom_name,'indicator_instances':self.indicator_instances,'config':config,'asset':meta,'blind':blind,'cursor':self.cursor-self.initial_cursor,
          'total':len(self.data)-self.initial_cursor-1,'finished':done,'time':now,'timeframe':tf,'chart':self.chart(tf,limit=max(2000,self.config.get('warmup_bars',300)) if self.cursor==self.initial_cursor else 2000),
          'warmup':{'requested':self.config.get('warmup_bars',300),'available':len(preview),'timeframe':self.preview_timeframe or self.meta['base'],'start':int(preview.index[0].timestamp()) if len(preview) else None,'end':int(preview.iloc[-1].bar_end.timestamp()) if len(preview) else None},
          'account':self.broker.account(),'positions':self.broker.positions(),'pending':self.broker.pending,
          'events':self.broker.events[-100:],'equity':self.curve[-10000:],'report':self.report(),'strategy':self.strategy_name,
          'strategy_settings':{k:v for k,v in (self.strategy_info or {}).items() if k not in ('code',)},'error':self.error,
          'news':[e for e in self.news if e['known_at']<=now],'indicators':self.chart_params,'indicator_layout':self.chart_layout,'version':VERSION}

    def save(self):
        directory=ROOT/'sessions';directory.mkdir(exist_ok=True);path=directory/f'{self.id}.json'
        strategy=None
        if self.worker:strategy={**self.strategy_info,'state':self.worker.snapshot(),'last_trigger':self.last_trigger,'event_cursor':self.event_cursor}
        payload={'version':2,'platform':VERSION,'engine':'nautilus_trader 1.231.0','config':self.config,'meta':self.meta,
          'fingerprints':self.fingerprints,'actions':self.actions,'news':self.news,'strategy':strategy,'indicators':self.chart_params,'indicator_layout':self.chart_layout,'indicator_instances':self.indicator_instances,'window_hash':self.window_hash,'fingerprints_signature':hashlib.sha256(json.dumps(self.fingerprints,sort_keys=True).encode()).hexdigest(),'name':self.record_name,'record_timeframe':self.record_timeframe,'custom_name':self.custom_name,'sequence':self.sequence}
        if self.preview_hash:payload['preview_hash']=self.preview_hash
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(path)
        return path.name

    @classmethod
    def restore(cls,name):
        if Path(name).name!=name or not name.endswith('.json'):raise ValueError('无效记录名称')
        p=json.loads((ROOT/'sessions'/name).read_text(encoding='utf-8'))
        if p.get('version')!=2 or p.get('platform') not in ('0.2.0','0.3.0','0.3.1',VERSION):raise ValueError('旧版记录不兼容新逐仓模型；保留原文件，请新建练习')
        config={**p['config'],'random_asset':False,'_snapshot_meta':p['meta']};s=cls(config)
        try:
            if p.get('preview_hash') and p['preview_hash']!=s.preview_hash:raise ValueError('练习前历史数据内容已变化，拒绝恢复')
            if p.get('window_hash'):
                signature=hashlib.sha256(json.dumps(p['fingerprints'],sort_keys=True).encode()).hexdigest()
                if p['window_hash']!=s.window_hash or signature!=p.get('fingerprints_signature'):raise ValueError('数据内容或记录校验不一致，拒绝恢复')
            elif p['fingerprints']!=s.fingerprints:raise ValueError('数据内容已变化，拒绝不一致恢复')
            for a in p['actions']:
                if a['kind']=='step':s.step(record=False,use_strategy=False)
                elif a['kind']=='order':s.order(a['value'],record=False)
                elif a['kind']=='leverage':s.leverage(a['id'],a['value'],record=False)
                elif a['kind']=='cancel':s.cancel(a['value'],record=False)
                elif a['kind']=='finish':s.finish(a['value'],record=False)
            s.config=p['config'];s.actions=p['actions'];s.news=p.get('news',[]);s.chart_params=p['indicators']
            s.chart_layout=p.get('indicator_layout',{});s.indicator_instances=ind.normalize(p.get('indicator_instances',ind.defaults()))
            s.record_name=p.get('name',s.record_name);s.record_timeframe=p.get('record_timeframe',s.meta['base']);s.sequence=p.get('sequence',s.sequence);s.custom_name=p.get('custom_name',False)
            s.id=Path(name).stem
            s.config['_snapshot_meta']=s.meta
            info=p.get('strategy')
            if info and not s.finished_explicit:
                if hashlib.sha256(info['code'].encode()).hexdigest()!=info['sha256']:raise ValueError('策略快照哈希不一致')
                s.strategy(info['name'],info['params'],info['timeframe'],info['contexts'],resume=info)
                s.last_trigger=info['last_trigger'];s.event_cursor=info['event_cursor']
            return s
        except Exception:s.close();raise
    def close(self):
        if self.worker:self.worker.close()
        self.broker.dispose()
