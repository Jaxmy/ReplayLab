from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock,Event,Thread
from typing import Literal
import csv,io,json,time,uuid,base64,struct,re
from app import indicators as ind
from app import market_data
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from app.data import catalog,indicator_config,utc
from app.session import Session,ROOT,VERSION,migrate_records

sessions={};jobs={};lock=RLock()
@asynccontextmanager
async def lifespan(app):
    migrate_records()
    market_data.start()
    yield
    for j in jobs.values():j['cancel'].set()
    with lock:
        for s in sessions.values():
            if not s.broker.stopped:s.save();s.close()
        sessions.clear()
app=FastAPI(title='Local Replay Lab',lifespan=lifespan)
@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','').split(':')[0];origin=request.headers.get('origin')
    if host not in ('127.0.0.1','localhost','testserver'):return JSONResponse({'detail':'只允许本机访问'},status_code=403)
    if request.method not in ('GET','HEAD') and origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
        return JSONResponse({'detail':'拒绝跨站修改请求'},status_code=403)
    return await call_next(request)
@app.exception_handler(ValueError)
async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)
@app.exception_handler(FileNotFoundError)
async def missing(request,exc):return JSONResponse({'detail':'文件不存在'},status_code=404)

class Config(BaseModel):
    model_config=ConfigDict(extra='forbid')
    symbol:str='BTCUSDT';category:str='crypto';random_asset:bool=False;seed:int=0;blind:bool=False
    start:str='2024-01-01';end:str='2024-01-03'
    cash:float=Field(default=10000,gt=0,le=1e9,allow_inf_nan=False)
    fee:float|None=Field(default=None,ge=0,le=.1,allow_inf_nan=False)
    slippage:float|None=Field(default=None,ge=0,le=.1,allow_inf_nan=False)
    hedging:bool=True
    liquidation_fee:float=Field(default=.001,ge=0,le=.1,allow_inf_nan=False)
    maintenance:float=Field(default=.005,gt=0,le=.2,allow_inf_nan=False)
    funding_rate:float=Field(default=0,ge=-.1,le=.1,allow_inf_nan=False)
    funding_hours:int=Field(default=8,ge=1,le=24)
    borrow_apr:float=Field(default=0,ge=0,le=10,allow_inf_nan=False)
    risk_free:float=Field(default=0,ge=-.2,le=1,allow_inf_nan=False)
    strategy_timeframe:str|None=None
    indicators:dict|None=None
    record_timeframe:str|None=None
    warmup_bars:int=Field(default=300,ge=1,le=5000)
    indicator_instances:list[dict]|None=None
    replace_session_id:str|None=None
class DeleteRecords(BaseModel):
    model_config=ConfigDict(extra='forbid')
    files:list[str]=Field(min_length=1,max_length=1000)
class Order(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:Literal['long','short','close']
    amount:float|None=Field(default=None,gt=0,le=1e12,allow_inf_nan=False)
    amount_mode:Literal['margin','notional']='margin'
    quantity:float=Field(default=.01,gt=0,le=100000,allow_inf_nan=False)
    leverage:float=Field(default=1,ge=1,le=100,allow_inf_nan=False)
    position_id:str|None=None
    stop:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    take:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    order_type:Literal['market','limit','stop']='market'
    price:float|None=Field(default=None,gt=0,allow_inf_nan=False)
class Command(BaseModel):
    action:Literal['step','leverage','strategy','save','clear_pending','indicators','finish','rename','record_timeframe']
    count:int=Field(default=1,ge=1,le=500)
    position_id:str|None=None;order_id:str|None=None
    leverage:float=Field(default=1,ge=1,le=100,allow_inf_nan=False)
    name:str|None=None;parameters:dict|None=None;timeframe:str|None=None;contexts:list[str]|None=None
    layout:dict|None=None
    instances:list[dict]|None=None
    force_close:bool=False
class Code(BaseModel):
    name:str;code:str=Field(max_length=100000)
class Artifact(BaseModel):
    format:Literal['png','html']
    data:str=Field(max_length=30000000)
def get(sid):
    if sid not in sessions:raise HTTPException(404,'记录不存在')
    return sessions[sid]
def idle(sid):
    if any(j['sid']==sid and j['status']=='running' for j in jobs.values()):raise ValueError('批量回测运行中，请先取消任务')
def hold(s):s.save()

@app.get('/api/health')
def health():return {'ok':True,'engine':'NautilusTrader 1.231.0','version':VERSION,'stage':'local simulation'}
@app.get('/api/indicators')
def indicator_catalog():return ind.catalog()
@app.get('/api/indicators/defaults')
def indicator_defaults():return ind.defaults()
@app.get('/api/data/status')
def data_status():
    path=market_data.ROOT/'data'/'update-status.json'
    try:return json.loads(path.read_text('utf-8')) if path.exists() else market_data.STATE
    except (OSError,ValueError):return market_data.STATE
@app.post('/api/data/update')
def update_data():market_data.start();return {'ok':True}
@app.get('/api/catalog')
def assets():return catalog()
@app.get('/api/sessions')
def session_list():
    with lock:return [{'id':s.id,'cursor':s.cursor-s.initial_cursor} for s in sessions.values()]
@app.post('/api/sessions')
def create(c:Config):
    with lock:
        previous=sessions.get(c.replace_session_id)
        if c.replace_session_id and previous is None:raise ValueError('当前记录已关闭，请刷新后重新开始')
        if previous:idle(previous.id)
        if len(sessions)>=5 and previous is None:raise ValueError('最多 5 个记录，请先关闭旧记录')
        config=c.model_dump(exclude_none=True);config.pop('replace_session_id',None)
        s=Session(config)
        try:
            result=s.view();hold(s)
            if previous:
                hold(previous);previous.close();del sessions[previous.id]
            sessions[s.id]=s
            return result
        except Exception:s.close();raise
@app.get('/api/sessions/{sid}')
def state(sid:str,timeframe:str|None=None):
    with lock:return get(sid).view(timeframe)
@app.get('/api/sessions/{sid}/history')
def history(sid:str,timeframe:str,before:int,limit:int=2000):
    if not 50<=limit<=5000:raise ValueError('每页 50–5000 根')
    with lock:return get(sid).chart(timeframe,before=before,limit=limit)
@app.delete('/api/sessions/{sid}')
def close(sid:str):
    with lock:idle(sid);s=get(sid);hold(s);s.close();del sessions[sid];return {'ok':True}
@app.post('/api/sessions/{sid}/orders')
def order(sid:str,o:Order):
    with lock:idle(sid);s=get(sid);s.order(o.model_dump());hold(s);return {'ok':True}
@app.post('/api/sessions/{sid}/command')
def command(sid:str,c:Command):
    with lock:
        idle(sid);s=get(sid)
        if c.action=='step':s.step(c.count)
        elif c.action=='leverage':s.leverage(c.position_id,c.leverage)
        elif c.action=='strategy':s.strategy(c.name,c.parameters,c.timeframe,c.contexts)
        elif c.action=='save':return {'file':s.save()}
        elif c.action=='clear_pending':s.cancel(c.order_id)
        elif c.action=='rename':
            name=(c.name or '').strip()
            if not name or len(name)>120 or any(ord(x)<32 for x in name):raise ValueError('记录名称须为 1–120 个可见字符')
            s.record_name=name;s.custom_name=True
        elif c.action=='record_timeframe':
            from app.data import validate_timeframe
            validate_timeframe(c.timeframe,s.meta['base']);s.record_timeframe=c.timeframe
            if not s.custom_name:s.record_name=f'{s.meta["name"]}_{s.record_timeframe}_{s.sequence:03}'
        elif c.action=='indicators' and c.instances is not None:
            s.indicator_instances=ind.normalize(c.instances);s.timeframe_cache.clear()
        elif c.action=='indicators':
            conf=indicator_config(c.parameters)
            if c.layout and any(k not in ('sma20','sma60','ema20','rsi','bb','macd','atr','volume') or not isinstance(v,dict) or v.get('placement') not in ('main','separate') or not isinstance(v.get('enabled'),bool) for k,v in c.layout.items()):raise ValueError('指标位置配置无效')
            s.chart_params=conf;s.chart_layout=c.layout or {};s.timeframe_cache.clear()
        elif c.action=='finish':s.finish(c.force_close)
        hold(s);return {'ok':True,'error':s.error}
@app.get('/api/saved')
def saved():
    records=[]
    for p in sorted((ROOT/'sessions').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            d=json.loads(p.read_text('utf-8'));m=d.get('meta',{});tf=d.get('record_timeframe',m.get('base','1m'))
            records.append({'file':p.name,'name':d.get('name',f'{m.get("name","历史记录")}_{tf}_{p.stem}'),'asset':m.get('id'),'timeframe':tf,'updated_at':p.stat().st_mtime})
        except (ValueError,OSError):continue
    return records
@app.delete('/api/saved')
def delete_records(value:DeleteRecords):
    """Delete selected records, close live copies, and reclaim unused code snapshots."""
    with lock:
        names=list(dict.fromkeys(value.files));directory=ROOT/'sessions'
        if directory.is_symlink() or (directory/'legacy-backup').is_symlink():raise ValueError('拒绝删除符号链接目录中的记录')
        for name in names:
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.json',name):raise ValueError('无效记录文件名')
            for p in (directory/name,directory/'legacy-backup'/name):
                if p.is_symlink():raise ValueError('拒绝删除符号链接记录')
            idle(Path(name).stem)
        deleted=[];closed=[];missing=[];freed=0
        for name in names:
            ident=Path(name).stem
            if ident in sessions:
                sessions[ident].close();del sessions[ident];closed.append(ident)
            path=directory/name
            (deleted if path.exists() else missing).append(name)
            for p in (path,directory/'legacy-backup'/name):
                if p.is_file():freed+=p.stat().st_size;p.unlink()
        # Strategy code is shared by hash. Only collect when every remaining record is readable.
        references=set();safe=True
        for p in list(directory.glob('*.json'))+list((directory/'legacy-backup').glob('*.json')):
            try:
                strategy=json.loads(p.read_text('utf-8')).get('strategy') or {}
                references.add(strategy.get('sha256'))
            except (OSError,ValueError,AttributeError):safe=False
        if safe and not (directory/'code').is_symlink():
            for p in (directory/'code').glob('*.py'):
                if not p.is_symlink() and re.fullmatch(r'[a-f0-9]{64}',p.stem) and p.stem not in references:
                    freed+=p.stat().st_size;p.unlink()
        return {'deleted':deleted,'missing':missing,'closed':closed,'freed_bytes':freed}
@app.post('/api/restore/{name}')
def restore(name:str):
    with lock:
        if len(sessions)>=5 and Path(name).stem not in sessions:raise ValueError('请先关闭旧记录')
        s=Session.restore(name)
        if s.id in sessions:sessions[s.id].close()
        sessions[s.id]=s;return s.view()
@app.post('/api/sessions/{sid}/branch')
def branch(sid:str):
    with lock:
        idle(sid)
        if len(sessions)>=5:raise ValueError('请先关闭旧记录')
        s=Session.restore(get(sid).save());s.id=uuid.uuid4().hex[:12];s.record_name+=' · 分支 '+s.id[:4];s.custom_name=True
        sessions[s.id]=s;hold(s);return s.view()
@app.get('/api/strategies')
def strategies():return sorted(p.name for p in (ROOT/'strategies').glob('*.py'))
@app.get('/api/strategies/{name}')
def code(name:str):
    if Path(name).name!=name or not name.endswith('.py'):raise ValueError('无效文件名')
    return {'code':(ROOT/'strategies'/name).read_text(encoding='utf-8')}
@app.post('/api/strategies')
def save_code(c:Code):
    if Path(c.name).name!=c.name or not c.name.endswith('.py'):raise ValueError('只允许策略目录下的 .py 文件')
    try:compile(c.code,c.name,'exec')
    except SyntaxError as e:raise ValueError(f'代码语法错误 {e}')
    (ROOT/'strategies'/c.name).write_text(c.code,encoding='utf-8');return {'ok':True}
@app.get('/api/sessions/{sid}/export')
def export(sid:str,format:str='json'):
    with lock:
        s=get(sid);report=s.report(full=True)
        if format=='csv':
            f=io.StringIO(newline='');columns=['type','time','action','position_id','quantity','price','reason','amount','leverage','order_id']
            writer=csv.DictWriter(f,columns,extrasaction='ignore');writer.writeheader();writer.writerows(s.broker.events)
            return {'format':'csv','filename':'replay-events.csv','text':'\ufeff'+f.getvalue()}
        return {'version':VERSION,'name':s.record_name,'config':{k:v for k,v in s.config.items() if not k.startswith('_')},'asset':s.meta,'data_hashes':s.fingerprints,'strategy':s.strategy_info,
          'account':s.broker.account(),'report':report,'events':s.broker.events,'equity':s.curve}
@app.post('/api/sessions/{sid}/artifacts')
def save_artifact(sid:str,value:Artifact):
    with lock:
        s=get(sid)
        if value.format=='png':
            if not value.data.startswith('data:image/png;base64,'):raise ValueError('无效图片格式')
            try:content=base64.b64decode(value.data.split(',',1)[1],validate=True)
            except Exception:raise ValueError('无效图片编码')
            if not content.startswith(b'\x89PNG\r\n\x1a\n') or len(content)<32:raise ValueError('无效 PNG 图片')
            w,h=struct.unpack('>II',content[16:24])
            if not 1<=w<=20000 or not 1<=h<=20000:raise ValueError('图片尺寸无效')
        else:
            if not value.data.startswith('<!doctype html>'):raise ValueError('无效 HTML 报告')
            content=value.data.encode('utf-8')
        directory=ROOT/'reports';directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'{s.id}-report.{value.format}'
        temp=path.with_suffix('.tmp');temp.write_bytes(content);temp.replace(path)
        return {'file':str(path),'bytes':len(content)}
@app.post('/api/sessions/{sid}/news')
def news(sid:str,events:list[dict]):
    if len(events)>5000:raise ValueError('事件包最多 5000 条')
    clean=[];seen=set()
    for e in events:
        if not str(e.get('title','')).strip() or 'known_at' not in e:raise ValueError('新闻须包含 title 和 known_at')
        import pandas as pd
        t=pd.Timestamp(e['known_at'])
        if pd.isna(t) or t.tzinfo is None:raise ValueError('known_at 必须为有效带时区时间')
        if e.get('published_at') and utc(e['published_at'])>t:raise ValueError('可知时间不能早于发布时间')
        key=(str(e['title']).strip(),int(t.timestamp()))
        if key in seen:continue
        seen.add(key);clean.append({'title':key[0][:300],'known_at':key[1],'source':str(e.get('source',''))[:300],
          'precision':e.get('precision','timestamp'),'asset':e.get('asset')})
    with lock:
        idle(sid);s=get(sid);s.news=sorted([e for e in clean if not e['asset'] or e['asset']==s.meta['id']],key=lambda e:e['known_at']);hold(s)
    return {'count':len(clean)}

def run_job(j):
    started=time.perf_counter()
    try:
        while not j['cancel'].is_set():
            with lock:
                s=get(j['sid'])
                if s.finished_explicit or s.cursor>=len(s.data)-1:break
                s.step(5)
                j['completed']=s.cursor-s.initial_cursor;j['total']=len(s.data)-s.initial_cursor-1
                if s.error:raise ValueError(s.error)
            time.sleep(0)
        with lock:hold(get(j['sid']))
        j['status']='cancelled' if j['cancel'].is_set() else 'completed'
    except Exception as e:j['status']='failed';j['error']=str(e)
    finally:j['seconds']=time.perf_counter()-started
@app.post('/api/sessions/{sid}/batch')
def batch(sid:str):
    with lock:
        idle(sid);s=get(sid);jid=uuid.uuid4().hex[:12]
        j={'id':jid,'sid':sid,'status':'running','completed':s.cursor-s.initial_cursor,'total':len(s.data)-s.initial_cursor-1,'cancel':Event()}
        jobs[jid]=j;Thread(target=run_job,args=(j,),daemon=True).start();return {'id':jid}
@app.get('/api/jobs/{jid}')
def job(jid:str):
    if jid not in jobs:raise HTTPException(404,'任务不存在')
    return {k:v for k,v in jobs[jid].items() if k!='cancel'}
@app.post('/api/jobs/{jid}/cancel')
def cancel_job(jid:str):
    if jid not in jobs:raise HTTPException(404,'任务不存在')
    jobs[jid]['cancel'].set();return {'ok':True}

app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
@app.get('/')
def index():return FileResponse(ROOT/'web'/'index.html',headers={'Cache-Control':'no-store'})
