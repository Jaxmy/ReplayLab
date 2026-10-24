"""双均线示例；在每根 1m 收盘后调用，订单在下一可交易分钟成交。"""
def on_bar(ctx, state):
    p=ctx.get('parameters',{});fast_n=int(p.get('fast',20));slow_n=int(p.get('slow',60))
    if not 2<=fast_n<slow_n<=500:raise ValueError('要求 2 <= fast < slow <= 500')
    closes=[b['close'] for b in ctx['bars']]
    if len(closes)<slow_n or ctx.get('pending'):return []
    fast=sum(closes[-fast_n:])/fast_n;slow=sum(closes[-slow_n:])/slow_n
    quantity=p.get('quantity',max(.01,ctx['asset']['lot']));leverage=p.get('leverage',2)
    state['bars_seen']=state.get('bars_seen',0)+1
    if fast>slow and not ctx['positions']:
        return [{'action':'long','quantity':quantity,'leverage':leverage}]
    if fast<slow:
        return [{'action':'close','position_id':p['id'],'quantity':p['quantity']} for p in ctx['positions']]
    return []
