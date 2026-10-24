"""Full minute-data quality audit; does not mutate source files."""
import json, sys, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
import pyarrow.parquet as pq
from app.data import SOURCE, aggregate

def audit():
    totals=dict(rows=0,imputed=0,duplicates=0,invalid_ohlc=0,missing_values=0,negative_volume=0,time_gaps=0)
    previous=None; partitions=[];derived={'checked_partitions':0,'mismatched_rows':0,'missing_partitions':0}
    for path in sorted((SOURCE/'1m').rglob('*.parquet')):
        d=pq.ParquetFile(path).read().to_pandas()
        t=d.open_time
        bad=(d.low>d.high)|(d.open<d.low)|(d.open>d.high)|(d.close<d.low)|(d.close>d.high)|(d.low<=0)
        stats={'rows':len(d),'imputed':int((~d.is_binance_observed).sum()),'duplicates':int(t.duplicated().sum()),
               'invalid_ohlc':int(bad.sum()),'missing_values':int(d[['open','high','low','close','volume']].isna().sum().sum()),
               'negative_volume':int((d.volume<0).sum()),'time_gaps':int((t.diff().dropna()!=pd.Timedelta(minutes=1)).sum())}
        if previous is not None and t.iloc[0]-previous != pd.Timedelta(minutes=1):stats['time_gaps']+=1
        previous=t.iloc[-1]
        import numpy as np
        minute=d.set_index('open_time')
        for tf in ('3m','5m','15m','30m','1h','4h','1d'):
            part=SOURCE/tf/path.relative_to(SOURCE/'1m')
            if not part.exists():derived['missing_partitions']+=1;continue
            expected=aggregate(minute,tf)[['open','high','low','close','volume']]
            actual=pq.ParquetFile(part).read().to_pandas().set_index('open_time')
            actual=actual.reindex(expected.index)[expected.columns]
            badrows=~np.isclose(actual.to_numpy(),expected.to_numpy(),rtol=1e-10,atol=1e-8).all(axis=1)
            derived['mismatched_rows']+=int(badrows.sum());derived['checked_partitions']+=1
        for k,v in stats.items():totals[k]+=v
        partitions.append({'path':str(path),'first':str(t.iloc[0]),'last':str(t.iloc[-1]),**stats})
    manifest=json.loads((SOURCE/'manifest.json').read_text(encoding='utf-8'))
    raw={'checked':0,'mismatches':[]}
    for item in manifest['raw']['one_minute_archives']:
        p=Path(item['path'])
        if not p.exists():raw['mismatches'].append({'path':str(p),'error':'missing'});continue
        h=hashlib.sha256(p.read_bytes()).hexdigest();raw['checked']+=1
        if h!=item['sha256']:raw['mismatches'].append({'path':str(p),'error':'sha256 mismatch'})
    result={'source':str(SOURCE),'totals':totals,'partitions':partitions,'derived':derived,'raw_1m_archives':raw,
            'scope':'All processed minute OHLCV, derived OHLCV partitions, and original 1m ZIP SHA256 against local manifest. Higher-period audit ZIPs not verified.'}
    out=Path(__file__).resolve().parents[1]/'reports'/'data-audit.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'totals':totals,'derived':derived,'raw':raw}));print(out)

if __name__=='__main__':audit()
