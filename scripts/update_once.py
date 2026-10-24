"""Run explicitly selected, free providers; app startup runs the same providers."""
from app import market_data as m
from concurrent.futures import ThreadPoolExecutor,as_completed
import json

if __name__=='__main__':
    # Keep this one-off repair small; normal startup also updates hourly/minute tiers.
    tasks=[('BTCUSDT',lambda:m.binance('BTCUSDT'))]
    tasks += [(asset,lambda a=asset,t=t,n=n,c=c:m.yahoo(a,t,n,c,'1d')) for asset,(t,n,c) in m.INDICES.items()]
    with ThreadPoolExecutor(max_workers=3) as p:
        jobs={p.submit(fn):key for key,fn in tasks}
        for job in as_completed(jobs):
            try:job.result();print(jobs[job],'ready',flush=True)
            except Exception as e:print(jobs[job],type(e).__name__,str(e),flush=True)
