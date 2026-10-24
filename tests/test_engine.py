import pandas as pd
import pytest
from app.engine import Broker

def bar(b,minute,price=100.,low=None,high=None,observed=True):
    b.bar(pd.Timestamp('2024-01-01',tz='UTC')+pd.Timedelta(minutes=minute),
          pd.Series({'open':price,'high':high or price,'low':low or price,'close':price,'is_binance_observed':observed}))

@pytest.fixture
def broker():
    b=Broker(cash=10000,fee=.001,slippage=0)
    yield b
    b.dispose()

def test_orders_only_fill_at_next_bar_and_native_pnl(broker):
    b=broker;bar(b,0);b.queue('long',1,2)
    assert not b.positions()
    bar(b,1,110)
    p=b.positions()[0];assert p['entry']==110 and p['margin']==55
    bar(b,2,120);assert b.account()['unrealized']==10
    b.queue('close',1,position_id=p['id']);bar(b,3,130)
    assert not b.positions();assert b.balance()==pytest.approx(10019.76)

def test_hedge_and_dynamic_leverage(broker):
    b=broker;bar(b,0);b.queue('long',1,2);b.queue('short',1,4);bar(b,1)
    assert len(b.positions())==2
    assert b.account()['reserved']==75
    p=b.positions()[0];before=b.account()['equity'];b.change_leverage(p['id'],5)
    assert b.account()['reserved']==45 and b.account()['equity']==before

def test_imputed_prices_do_not_fill(broker):
    b=broker;bar(b,0);b.queue('long',1,2);bar(b,1,observed=False)
    assert not b.positions() and len(b.pending)==1
    bar(b,2);assert len(b.positions())==1

def test_stop_precedes_take_when_both_touched(broker):
    b=broker;bar(b,0);b.queue('long',1,2,stop=95,take=105);bar(b,1,low=90,high=110)
    assert not b.positions()
    assert b.events[-1]['reason']=='stop' and b.events[-1]['price']==95

def test_insufficient_collateral_rejected(broker):
    b=broker;bar(b,0);b.queue('long',200,1);bar(b,1)
    assert not b.positions() and b.events[-1]['type']=='rejected'

def test_margin_change_rejects_without_mutation(broker):
    b=broker;bar(b,0);b.queue('long',150,2);bar(b,1)
    p=b.positions()[0]
    with pytest.raises(ValueError):b.change_leverage(p['id'],1)
    assert b.positions()[0]['margin']==p['margin']

def test_netting_uses_native_reductions():
    b=Broker(fee=0,slippage=0,hedging=False)
    try:
        bar(b,0);b.queue('long',2);bar(b,1);b.queue('short',1);bar(b,2)
        assert len(b.positions())==1 and b.positions()[0]['quantity']==1
    finally:b.dispose()
