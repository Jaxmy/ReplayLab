"""分钟级短线教学模板（EMA 趋势 + RSI），不能模拟高频订单簿执行。"""
def on_bar(ctx,state):
    p=ctx.get('parameters',{})
    c=[b['close'] for b in ctx['bars']]
    if len(c)<30:return []
    ema=c[0]
    for v in c[1:]:ema+=(v-ema)*2/21
    d=[b-a for a,b in zip(c[-15:-1],c[-14:])]
    gain=sum(max(0,v) for v in d);loss=sum(max(0,-v) for v in d)
    rsi=100-100/(1+gain/loss) if loss else 100
    if not ctx['positions'] and not ctx.get('pending') and c[-1]>ema and 50<rsi<65:
        return [{'action':'long','quantity':p.get('quantity',max(.005,ctx['asset']['lot'])),'leverage':p.get('leverage',2),
                 'stop':c[-1]*(1-float(p.get('stop_pct',.003))),'take':c[-1]*(1+float(p.get('take_pct',.004)))}]
    return []
