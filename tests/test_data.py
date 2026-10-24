import pandas as pd
from app.data import aggregate, chart_data, read_bars

def fixture():
    t=pd.date_range('2024-01-01',periods=90,freq='min',tz='UTC')
    return pd.DataFrame({'open':range(100,190),'high':range(102,192),'low':range(99,189),
                         'close':range(101,191),'volume':1.,'is_binance_observed':True},index=t)

def test_aggregation_uses_known_prefix():
    d=fixture()
    a=aggregate(d.iloc[:17],'1h')
    assert a.iloc[0].high==118 and a.iloc[0].close==117 and a.iloc[0].volume==17
    assert chart_data(d.iloc[:17],'1h')['candles'][0]['high']==118

def test_week_and_month_boundaries():
    d=fixture()
    assert aggregate(d,'1w').index[0]==pd.Timestamp('2024-01-01',tz='UTC')
    assert aggregate(d,'1M').index[0]==pd.Timestamp('2024-01-01',tz='UTC')

def test_real_data_read_only_window():
    d,c=read_bars('2024-01-01','2024-01-02')
    assert len(d)==1740 and c==299
    assert d.index[c+1]==pd.Timestamp('2024-01-01',tz='UTC')
    assert d.index[-1]==pd.Timestamp('2024-01-01 23:59',tz='UTC')
