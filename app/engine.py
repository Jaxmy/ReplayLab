"""Nautilus-backed fills/PnL with a local isolated-collateral policy.

Prices are spot-derived simulation quotes; not exchange perp/mark prices.
The policy reserves collateral per position. Native engine owns fills and PnL.
"""
from decimal import Decimal
import math
import warnings
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.currencies import BTC, USDT
from nautilus_trader.model.objects import Price, Quantity, Money
from nautilus_trader.model.enums import OmsType, AccountType, OrderSide
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.backtest.modules import SimulationModule
from nautilus_trader.config import SimulationModuleConfig
from nautilus_trader.model.objects import Currency
import re

warnings.filterwarnings('ignore', message='Timestamp.utcnow is deprecated.*')

class CashflowModule(SimulationModule):
    """Public native exchange API for explicit, auditable non-trade settlements."""
    def __init__(self):super().__init__(SimulationModuleConfig())
    def process(self,ts_now):pass
    def reset(self):pass
    def log_diagnostics(self,logger):pass
    def settle(self,amount,currency):self.exchange.adjust_account(Money(amount,currency))

class Broker:
    def __init__(self, cash=10000., fee=.0005, slippage=.0002, hedging=True, spec=None,
                 liquidation_fee=.001, funding_rate=0., funding_hours=8, borrow_apr=0., maintenance=.005):
        self.initial=cash; self.fee=fee; self.slippage=slippage; self.hedging=hedging
        self.spec=spec or {};self.precision=self.spec.get('price_precision',2);self.size_precision=self.spec.get('size_precision',6)
        self.multiplier=self.spec.get('multiplier',1);self.lot=self.spec.get('lot',.000001)
        self.currency=Currency.from_str(self.spec.get('currency','USDT'))
        self.liquidation_fee=liquidation_fee;self.funding_rate=funding_rate;self.funding_ns=int(funding_hours*3600*1e9)
        self.borrow_apr=borrow_apr;self.cashflows=[];self.counter=0
        self.engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(log_level='ERROR')))
        self.venue=Venue('SIM')
        self.settlements=CashflowModule()
        self.engine.add_venue(venue=self.venue,oms_type=OmsType.HEDGING,account_type=AccountType.MARGIN,
                             starting_balances=[Money(cash,self.currency)],default_leverage=Decimal(100),
                             modules=[self.settlements],use_message_queue=False)
        name=re.sub('[^A-Za-z0-9_-]','_',self.spec.get('id','BTCUSDT'))
        self.instrument=CryptoPerpetual(InstrumentId.from_str(name+'.SIM'),Symbol(name),
            BTC,self.currency,self.currency,False,self.precision,self.size_precision,
            Price(10**-self.precision,self.precision),Quantity(10**-self.size_precision,self.size_precision),0,0,
            multiplier=Quantity(self.multiplier,6),
            margin_init=Decimal(1),margin_maint=Decimal('0.005'),taker_fee=Decimal(str(fee)))
        self.engine.add_instrument(self.instrument)
        self.strategy=Strategy(); self.engine.add_strategy(self.strategy)
        self.policy={}; self.pending=[]; self.events=[]; self.last_price=0.; self.clock=0
        self.started=False; self.stopped=False; self.maintenance=maintenance

    def px(self,p):return Price(max(10**-self.precision,float(p)),self.precision)

    def tick(self, price, ts):
        self.last_price=float(price); self.clock=max(int(ts),self.clock+1)
        p=self.last_price
        q=QuoteTick(self.instrument.id,self.px(p*(1-self.slippage)),self.px(p*(1+self.slippage)),
                    Quantity(1000000000,self.size_precision),Quantity(1000000000,self.size_precision),self.clock,self.clock)
        self.engine.add_data([q]);self.engine.run(streaming=True);self.engine.clear_data();self.started=True

    def balance(self):
        if not self.started:return self.initial
        return self.engine.cache.account_for_venue(self.venue).balance_total(self.currency).as_double()

    def cashflow(self,pid,amount,kind,event_time=None):
        amount=Money(amount,self.currency).as_double()
        if amount==0:return 0.
        self.settlements.settle(amount,self.currency)
        entry={'type':kind,'position_id':pid,'amount':amount,'time':self.clock if event_time is None else event_time}
        self.cashflows.append(entry);self.events.append(entry)
        return amount

    def positions(self):
        result=[]
        for p in self.engine.cache.positions_open():
            meta=self.policy.get(str(p.id),{})
            result.append({'id':str(p.id),'side':'long' if p.is_long else 'short',
              'quantity':p.quantity.as_double(),'entry':p.avg_px_open,
              'pnl':max(-meta.get('margin',float('inf')),p.unrealized_pnl(self.px(self.last_price)).as_double()) if self.last_price else 0.,
              'margin':meta.get('margin',0.),'leverage':meta.get('leverage',1.),
              'stop':meta.get('stop'),'take':meta.get('take'),
              'liquidation':self.liquidation_price(p,meta)})
        return result

    def account(self):
        ps=self.positions();balance=self.balance();upnl=sum(p['pnl'] for p in ps)
        reserved=sum(p['margin'] for p in ps)
        return {'balance':balance,'equity':balance+upnl,'unrealized':upnl,'reserved':reserved,
                'available':balance-reserved,'return_pct':(balance+upnl-self.initial)/self.initial*100}

    def queue(self, action, quantity=.01, leverage=1., position_id=None, stop=None, take=None,
              order_type='market',price=None,amount=None,amount_mode='margin'):
        if action not in ('long','short','close'):raise ValueError('未知订单方向')
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (quantity,leverage)):
            raise ValueError('数量与杠杆必须为有限数字')
        if any(v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0) for v in (stop,take)):
            raise ValueError('止盈止损必须为正数')
        if len(self.pending)>=100:raise ValueError('最多排队 100 笔订单')
        if order_type not in ('market','limit','stop'):raise ValueError('订单类型须为 market/limit/stop')
        if order_type!='market' and (not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0):raise ValueError('条件订单必须有有效价格')
        if amount is not None:
            if action=='close' or not isinstance(amount,(int,float)) or not math.isfinite(amount) or not 0<amount<=1e12 or amount_mode not in ('margin','notional'):raise ValueError('交易金额或金额类型无效')
            quantity=self.lot
        units=round(quantity/self.lot)
        if units<1 or abs(quantity-units*self.lot)>max(1e-9,self.lot*1e-6):raise ValueError(f'数量必须为 {self.lot} 的整数倍')
        if not .000001<=quantity<=100000 or not 1<=leverage<=100:raise ValueError('数量须大于 0，杠杆须为 1–100')
        if action=='close' and not any(p['id']==position_id for p in self.positions()):raise ValueError('持仓不存在')
        if order_type=='limit':
            buy=action=='long'
            if action=='close':buy=next(p for p in self.positions() if p['id']==position_id)['side']=='short'
            scale=10**self.precision
            price=(math.floor(price*scale+1e-9) if buy else math.ceil(price*scale-1e-9))/scale
            if price<=0:raise ValueError('限价低于最小价格精度')
        self.counter+=1
        self.pending.append(dict(action=action,quantity=quantity,leverage=leverage,position_id=position_id,stop=stop,take=take,
                                 order_type=order_type,price=price,amount=amount,amount_mode=amount_mode,order_id=f'Q{self.counter}'))
        self.events.append({'type':'queued','time':self.clock,**self.pending[-1]})
        return f'Q{self.counter}'

    def cancel(self,order_id=None):
        self.pending=[c for c in self.pending if order_id is not None and c['order_id']!=order_id]
        self.events.append({'type':'cancel','order_id':order_id,'time':self.clock})

    def liquidation_price(self,p,meta):
        if not meta or p.quantity.as_double()==0:return None
        sign=1 if p.is_long else -1;n=p.quantity.as_double()*self.multiplier
        return max(0,(sign*p.avg_px_open-meta['margin']/n)/(sign-self.maintenance-self.fee-self.liquidation_fee))

    def _close(self, pid, quantity=None, reason='manual'):
        pos=next((p for p in self.engine.cache.positions_open() if str(p.id)==pid),None)
        if pos is None:return
        qty=pos.quantity.as_double() if quantity is None else min(quantity,pos.quantity.as_double())
        before_qty=pos.quantity.as_double()
        meta=self.policy[pid];remaining_margin=Money(meta['margin']*max(0,1-qty/before_qty),self.currency).as_double()
        allocated=meta['margin']-remaining_margin
        fill=self.px(self.last_price*(1-self.slippage if pos.is_long else 1+self.slippage)).as_double()
        raw_pnl=Money((fill-pos.avg_px_open)*(1 if pos.is_long else -1)*qty*self.multiplier,self.currency).as_double()
        fee=Money(qty*self.multiplier*fill*self.fee,self.currency).as_double()
        extra=Money(qty*self.multiplier*fill*self.liquidation_fee,self.currency).as_double() if reason=='liquidation' else 0.
        # Credit a modeled insurance contribution BEFORE a potentially bankrupt native fill.
        # The user loses at most this lot's remaining collateral (entry fees paid separately).
        insurance=max(0.,-allocated-raw_pnl+fee+extra)
        if insurance:insurance=self.cashflow(pid,insurance,'insurance')
        order=self.strategy.order_factory.market(self.instrument.id,OrderSide.SELL if pos.is_long else OrderSide.BUY,
                                                 Quantity(qty,self.size_precision),reduce_only=True)
        self.strategy.submit_order(order,position_id=pos.id)
        if order.filled_qty.as_double()>0:
            self.events.append({'type':'fill','action':'close','reason':reason,'time':self.clock,'position_id':pid,
                                'quantity':order.filled_qty.as_double(),'price':order.avg_px})
            if pid in self.policy:self.policy[pid]['margin']=remaining_margin
            if extra:self.cashflow(pid,-extra,'liquidation_fee')
        else:
            if insurance:self.cashflow(pid,-insurance,'insurance_reversal')
            self.events.append({'type':'rejected','time':self.clock,'reason':str(order.status)})

    def _open(self, cmd):
        side=cmd['action'];qty=round(cmd['quantity'],self.size_precision);lev=cmd['leverage']
        if cmd.get('amount') is not None:
            fill=self.px(self.last_price*(1+self.slippage if side=='long' else 1-self.slippage)).as_double()
            notional=cmd['amount']*(lev if cmd.get('amount_mode')=='margin' else 1)
            qty=round(math.floor(notional/(fill*self.multiplier*self.lot)+1e-9)*self.lot,self.size_precision)
            if qty<self.lot or qty>100000:
                self.events.append({'type':'rejected','time':self.clock,'reason':'金额对应的数量低于最小交易单位或超过模拟上限'});return
        if not self.hedging:
            remaining=qty
            for p in self.positions():
                if p['side']!=side and remaining>0:
                    closed=min(p['quantity'],remaining);self._close(p['id'],closed,'netting');remaining-=closed
            qty=round(remaining,self.size_precision)
            if qty<=0:return
        price=self.px(self.last_price*(1+self.slippage if side=='long' else 1-self.slippage)).as_double()
        margin=Money(qty*self.multiplier*price/lev,self.currency).as_double()
        if margin<=qty*self.multiplier*price*(self.maintenance+self.fee+self.liquidation_fee):
            self.events.append({'type':'rejected','time':self.clock,'reason':'杠杆过高，保证金不足以覆盖维持保证金及退出成本'});return
        if margin+qty*self.multiplier*price*self.fee>self.account()['available']:
            self.events.append({'type':'rejected','time':self.clock,'reason':'可用资金不足以覆盖逐仓保证金及手续费'});return
        if cmd['stop'] is not None and ((side=='long' and cmd['stop']>=price) or (side=='short' and cmd['stop']<=price)):
            self.events.append({'type':'rejected','time':self.clock,'reason':'止损方向错误（或开盘跳空穿过止损）'});return
        if cmd['take'] is not None and ((side=='long' and cmd['take']<=price) or (side=='short' and cmd['take']>=price)):
            self.events.append({'type':'rejected','time':self.clock,'reason':'止盈方向错误（或开盘跳空穿过止盈）'});return
        before={str(p.id) for p in self.engine.cache.positions_open()}
        args=(self.instrument.id,OrderSide.BUY if side=='long' else OrderSide.SELL,Quantity(qty,self.size_precision))
        order=self.strategy.order_factory.limit(*args,price=self.px(cmd['price'])) if cmd.get('order_type')=='limit' else self.strategy.order_factory.market(*args)
        self.strategy.submit_order(order)
        new=[p for p in self.engine.cache.positions_open() if str(p.id) not in before]
        for p in new:
            self.policy[str(p.id)]={'margin':Money(p.quantity.as_double()*self.multiplier*p.avg_px_open/lev,self.currency).as_double(),'leverage':lev,
                                   'stop':cmd['stop'],'take':cmd['take']}
            self.events.append({'type':'fill','action':side,'time':self.clock,'position_id':str(p.id),
                                'quantity':p.quantity.as_double(),'price':p.avg_px_open})
        if not new:self.events.append({'type':'rejected','time':self.clock,'reason':str(order.status)})

    def change_leverage(self,pid,leverage):
        if not math.isfinite(leverage) or not 1<=leverage<=100:raise ValueError('杠杆须为 1–100')
        p=next((p for p in self.positions() if p['id']==pid),None)
        if p is None:raise ValueError('持仓不存在')
        new=Money(p['entry']*p['quantity']*self.multiplier/leverage,self.currency).as_double()
        if new-p['margin']>self.account()['available']:raise ValueError('降低杠杆所需追加保证金超过可用余额')
        if new+p['pnl']<=p['quantity']*self.last_price*self.multiplier*(self.maintenance+self.fee+self.liquidation_fee):raise ValueError('调整后保证金不足以满足维持保证金及退出成本')
        self.policy[pid].update(margin=new,leverage=leverage)
        self.events.append({'type':'leverage','position_id':pid,'leverage':leverage,'time':self.clock})

    def financing(self,target,reference_price=None):
        if not self.started or target<=self.clock:return
        prior=self.clock
        boundaries=(target//self.funding_ns)-(prior//self.funding_ns)
        seconds=(target-prior)/1e9
        for p in self.positions():
            pid=p['id'];meta=self.policy[pid];n=p['quantity']*self.multiplier*(reference_price or self.last_price)
            funding=-(1 if p['side']=='long' else -1)*n*self.funding_rate*boundaries
            borrowing=-max(0,n-meta['margin'])*self.borrow_apr*seconds/(365*86400)
            for amount,kind in ((funding,'funding'),(borrowing,'borrow_interest')):
                if amount:
                    amount=max(amount,-meta['margin']);actual=self.cashflow(pid,amount,kind,event_time=target);meta['margin']=max(0,meta['margin']+actual)

    def bar(self,timestamp,row):
        ts=int(timestamp.value);end=int(row.bar_end.value)-1 if 'bar_end' in row else ts+59_000_000_000
        self.financing(ts,row.open)
        if not bool(row.is_binance_observed):
            # Mark equity but do not submit/close orders on imputed prices.
            self.financing(end,row.open);self.tick(row.close,end)
            return
        self.tick(row.open,ts)
        # Gap liquidation/exit is evaluated before queued discretionary orders.
        self.risk(row,opening_only=True)
        pending,self.pending=self.pending,[]
        for cmd in pending:
            if cmd['order_type']!='market':
                buy=cmd['action']=='long'
                if cmd['action']=='close':
                    p=next((p for p in self.positions() if p['id']==cmd['position_id']),None)
                    if p is None:continue
                    buy=p['side']=='short'
                limit=cmd['order_type']=='limit';level=cmd['price']
                touched=(row.low<=level if buy else row.high>=level) if limit else (row.high>=level if buy else row.low<=level)
                if not touched:self.pending.append(cmd);continue
                fill=(min(row.open,level) if buy else max(row.open,level)) if limit else (max(row.open,level) if buy else min(row.open,level))
                # Limit prices include all simulated spread/slippage; never exceed the limit.
                slip=self.slippage
                if limit:self.slippage=0.
                self.tick(fill,self.clock+1)
            if cmd['action']=='close':self._close(cmd['position_id'],cmd['quantity'])
            else:self._open(cmd)
            if cmd['order_type']!='market':self.slippage=slip;self.tick(row.open,self.clock+1)
        self.risk(row)
        self.financing(end,row.open);self.tick(row.close,end)

    def risk(self,row,opening_only=False):
        # Explicit conservative OHLC policy: for each lot, adverse trigger before favorable trigger.
        # Quotes here are synthetic execution prices, not observed intrabar ticks.
        for p in self.positions():
            long=p['side']=='long';liq=p['liquidation']
            adverse=float(row.open if opening_only else row.low if long else row.high)
            reason=None;trigger=None
            if (long and adverse<=liq) or (not long and adverse>=liq):reason='liquidation';trigger=liq
            stop=p['stop']
            if stop is not None and ((long and adverse<=stop) or (not long and adverse>=stop)):
                if trigger is None or (long and stop>trigger) or (not long and stop<trigger):reason='stop';trigger=stop
            take=p['take']
            favorable=row.open if opening_only else row.high if long else row.low
            if trigger is None and take is not None and ((long and favorable>=take) or (not long and favorable<=take)):
                reason='take';trigger=take
            if trigger is not None:
                if reason=='take':fill=max(trigger,row.open) if long else min(trigger,row.open)
                else:fill=min(trigger,row.open) if long else max(trigger,row.open)
                self.tick(fill,self.clock+1);self._close(p['id'],reason=reason)

    def trade_records(self):
        closed=self.engine.cache.positions_closed()
        result=[]
        for p in closed:
            pid=str(p.id);flows=[f for f in self.cashflows if f['position_id']==pid]
            result.append({'id':pid,'side':'long' if p.entry==OrderSide.BUY else 'short',
              'entry':p.avg_px_open,'exit':p.avg_px_close,'quantity':p.peak_qty.as_double(),
              'opened_ns':p.ts_opened,'closed_ns':p.ts_closed,
              'native_pnl':p.realized_pnl.as_double(),'net_pnl':p.realized_pnl.as_double()+sum(f['amount'] for f in flows),
              'commissions':sum(m.as_double() for m in p.commissions()),'cashflows':flows})
        return result

    def dispose(self):
        if self.stopped:return
        if self.started:self.engine.end()
        self.engine.dispose();self.stopped=True
