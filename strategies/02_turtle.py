"""双向海龟规则基线：20/10 或 55/20 通道、N 风险仓位、0.5N 加仓、2N 止损。
所有周期以选择的策略 bar 为单位；未复刻原始系统的假想交易跳过过滤器。
参数：entry=20, exit=10, atr=20, risk=.01, units=4, leverage=2。
"""
def on_bar(ctx,state):
    import math
    p=ctx.get('parameters',{});entry=int(p.get('entry',20));exit=int(p.get('exit',10));n=int(p.get('atr',20))
    if not 2<=exit<entry<=400 or not 2<=n<=400:raise ValueError('海龟周期须满足 2 <= exit < entry <= 400，ATR 2–400')
    bars=ctx['bars'];ps=ctx['positions']
    if len(bars)<max(entry,n)+2 or ctx.get('pending'):return []
    price=bars[-1]['close'];prev=bars[-entry-1:-1]
    atr=sum(max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])) for a,b in zip(bars[-n-1:-1],bars[-n:]))/n
    if atr<=0:return []
    low_exit=min(b['low'] for b in bars[-exit-1:-1]);high_exit=max(b['high'] for b in bars[-exit-1:-1])
    exits=[x for x in ps if (x['side']=='long' and price<low_exit) or (x['side']=='short' and price>high_exit)]
    if exits:return [{'action':'close','position_id':x['id'],'quantity':x['quantity']} for x in exits]
    side=('long' if price>max(b['high'] for b in prev) else 'short' if price<min(b['low'] for b in prev) else None)
    if ps:
        side=ps[-1]['side'];last=ps[-1]['entry']
        if len(ps)>=int(p.get('units',4)) or (price-last)*(1 if side=='long' else -1)<.5*atr:return []
    if not side:return []
    lev=float(p.get('leverage',2));lot=ctx['asset']['lot'];mult=ctx['asset'].get('multiplier',1)
    risk=float(p.get('risk',.01))
    if not 0<risk<=.05:raise ValueError('risk 须为 0–0.05')
    qty=min(ctx['account']['equity']*risk/(atr*mult),max(0,ctx['account']['available'])*.2*lev/(price*mult))
    qty=round(math.floor(qty/lot)*lot,ctx['asset']['size_precision'])
    if qty<lot:return []
    return [{'action':side,'quantity':qty,'leverage':lev,'stop':max(10**-ctx['asset']['price_precision'],price+(-2 if side=='long' else 2)*atr)}]
