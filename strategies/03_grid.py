"""限价网格：首次建立下方 levels 个买入价位，持仓有间隔 spacing 的卖出条件单。
参数 spacing=.003, levels=5, quantity=.002, leverage=1。成交采用 OHLC 模拟。
"""
def on_bar(ctx,state):
    p=ctx.get('parameters',{});price=ctx['bars'][-1]['close'];spacing=float(p.get('spacing',.003));levels=int(p.get('levels',5))
    if not .0001<=spacing<=.2 or not 1<=levels<=10:raise ValueError('spacing 须为 .0001–.2，levels 为 1–10')
    state.setdefault('anchor',price);orders=[]
    qty=p.get('quantity',max(.002,ctx['asset']['lot']));lev=p.get('leverage',1)
    pending=ctx.get('pending',[])
    for pos in ctx['positions']:
        if not any(o.get('position_id')==pos['id'] for o in pending):
            orders.append({'action':'close','position_id':pos['id'],'quantity':pos['quantity'],'order_type':'limit','price':pos['entry']*(1+spacing)})
    if not ctx['positions'] and not pending:
        state['anchor']=price
        for i in range(1,levels+1):orders.append({'action':'long','quantity':qty,'leverage':lev,'order_type':'limit','price':price*(1-spacing*i)})
    return orders
