"""Reproducible local month loading / short execution benchmark."""
from pathlib import Path
import json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.session import Session
t=time.perf_counter();s=Session({'start':'2024-01-01','end':'2024-02-01','cash':10000,'fee':.0005,'slippage':.0002})
load=time.perf_counter()-t
try:
    t=time.perf_counter();s.step(2000);execution=time.perf_counter()-t
    t=time.perf_counter();view=s.view('1m');render=time.perf_counter()-t
    result={'load_31_days_seconds':load,'source_rows':len(s.data),'execution_2000_bars_seconds':execution,
            'view_seconds':render,'returned_candles':len(view['chart']['candles']),'payload_bytes':len(json.dumps(view)),
            'description':'No strategy benchmark; native fills and Python strategy add workload.'}
    path=Path(__file__).resolve().parents[1]/'reports'/'benchmark.json';path.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
finally:s.close()
