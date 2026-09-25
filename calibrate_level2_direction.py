"""Read-only source calibration; exports evidence, never changes raw parquet files."""
import argparse
import json
from pathlib import Path
import duckdb


def audit(root, days):
    con=duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=4')
    result=[]
    try:
        for day in days:
            deal=root/f'deal_{day}.parquet'
            snapshot=root/f'snapshot_{day}.parquet'
            # Full-day scalar aggregation, not a full-market dataframe.
            groups=con.execute('''SELECT CASE WHEN SecuCode>=600000 THEN 'SH' ELSE 'SZ' END exchange,
              count(*) n, count(*) FILTER (WHERE Side IN (0,1)) known,
              count(*) FILTER (WHERE BuyID>0 AND SellID>0 AND BuyID<>SellID) comparable,
              count(*) FILTER (WHERE (Side=0 AND BuyID>SellID) OR (Side=1 AND SellID>BuyID)) agree,
              sum(Price::DOUBLE*Volume/100) amount
              FROM read_parquet(?) WHERE TradingDay=? AND Price>0 AND Volume>0
              AND Side NOT IN (-1,-11) AND
              regexp_matches(lpad(SecuCode::VARCHAR,6,'0'),'^(000|001|002|003|300|301|302|600|601|603|605|688|689)[0-9]{3}$')
              GROUP BY 1 ORDER BY 1''',[str(deal),int(day)]).fetchall()
            evidence={'day':day,'file':str(deal),'size':deal.stat().st_size,'mtime_ns':deal.stat().st_mtime_ns,
                      'groups':[dict(zip(['exchange','rows','known','comparable','agreement','amount'],g)) for g in groups]}
            # Independent noisy quote check: preceding unlocked BBO, strictly earlier,
            # no same timestamp lookahead, within 1 second, continuous session only.
            quotes=con.execute('''WITH d AS (
              SELECT SecuCode,DealTime,Price,Side,
              ((DealTime//10000000)*3600000+((DealTime//100000)%100)*60000+
               ((DealTime//1000)%100)*1000+DealTime%1000) AS ms
              FROM read_parquet(?) WHERE TradingDay=? AND SecuCode IN (1,977,600519,688008)
              AND Price>0 AND Volume>0 AND Side IN (0,1)
              AND ((DealTime>=93000000 AND DealTime<113000000) OR (DealTime>=130000000 AND DealTime<145700000))
            ), s AS (
              SELECT SecuCode,TickTime,BidPrice1,AskPrice1,
              ((TickTime//10000000)*3600000+((TickTime//100000)%100)*60000+
               ((TickTime//1000)%100)*1000+TickTime%1000) AS ms
              FROM read_parquet(?) WHERE TradingDay=? AND SecuCode IN (1,977,600519,688008)
            ), j AS (
              SELECT d.*,s.ms quote_ms,s.BidPrice1,s.AskPrice1 FROM d ASOF LEFT JOIN s
              ON d.SecuCode=s.SecuCode AND d.ms>s.ms
            ) SELECT SecuCode,Side,count(*),
              count(*) FILTER (WHERE (Side=0 AND Price>=AskPrice1) OR (Side=1 AND Price<=BidPrice1))
              FROM j WHERE ms-quote_ms<=1000 AND BidPrice1>0 AND AskPrice1>BidPrice1
              AND (Price>=AskPrice1 OR Price<=BidPrice1) GROUP BY 1,2 ORDER BY 1,2''',
              [str(deal),int(day),str(snapshot),int(day)]).fetchall()
            evidence['quoteChecks']=[dict(zip(['code','side','eligible','agreement'],q)) for q in quotes]
            result.append(evidence)
            print(json.dumps(evidence,ensure_ascii=False),flush=True)
    finally:con.close()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('/Volumes/990pro/data/level2'))
    parser.add_argument('--days',nargs='+',default=['20260331','20260630','20260827','20260831'])
    parser.add_argument('--out',type=Path,default=Path('.level2_direction_audit.json'))
    args=parser.parse_args()
    args.out.write_text(json.dumps(audit(args.root,args.days),ensure_ascii=False,indent=2))
