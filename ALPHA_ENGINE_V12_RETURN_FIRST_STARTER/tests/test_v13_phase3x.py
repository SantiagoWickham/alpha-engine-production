import numpy as np, pandas as pd
from alpha_engine_v13.alpha_attribution_audit import _ols,_capture,_annual_returns,_holding_stats,_benchmark_integrity

def test_ols_beta_identity():
    x=pd.Series(np.linspace(-.02,.02,1000)); y=.0001+1.2*x
    r=_ols(y,x); assert abs(r['beta']-1.2)<1e-10 and r['r2']>.999999

def test_capture_has_up_down():
    b=pd.Series([.01,-.01,.02,-.02]*30); s=.5*b
    r=_capture(s,b); assert r['up_days']>0 and r['down_days']>0

def test_annual_returns():
    d=pd.DataFrame({'date':pd.to_datetime(['2020-01-02','2020-01-03','2021-01-04']),'net_return':[.1,0,.2]})
    b={'SPY':pd.Series([0,0,0],index=d.date)}
    a=_annual_returns(d,b); assert len(a)==2 and abs(a.iloc[0].strategy_return-.1)<1e-12

def test_holding_stats_nonempty():
    w=pd.DataFrame({'date':pd.to_datetime(['2020-01-02','2020-01-03','2020-01-06']),'ticker':['A']*3,'weight':[.1,.1,.1]})
    h,c=_holding_stats(w,pd.DataFrame()); assert len(h)>0 and len(c)==3

def test_benchmark_integrity_missing_detected():
    idx=pd.date_range('2019-01-02',periods=10,freq='B'); ret=pd.DataFrame({'A':[.01]*10,'B':[.01]*5+[np.nan]*5},index=idx); elig=pd.DataFrame(True,index=idx,columns=['A','B'])
    m={'research_eligible':elig,'returns':ret}; b={}
    out=_benchmark_integrity(m,b); assert 'mean_missing_share' in out.columns

def test_simulate_weight_rebalance_reduces_trade_frequency():
    from alpha_engine_v13.alpha_attribution_audit import _simulate_with_weights
    idx=pd.date_range('2020-01-02',periods=30,freq='B')
    ret=pd.DataFrame({'A':0.0,'B':0.0},index=idx)
    pres=pd.DataFrame(True,index=idx,columns=['A','B'])
    market={'calendar':idx,'returns':ret,'execution_presence':pres}
    targets={d:({'A':1.0} if i%2==0 else {'B':1.0}) for i,d in enumerate(idx)}
    d1,_=_simulate_with_weights(targets,market,{},idx[0],idx[-1]+pd.Timedelta(days=1),20,1)
    d5,_=_simulate_with_weights(targets,market,{},idx[0],idx[-1]+pd.Timedelta(days=1),20,5)
    assert d5.turnover.sum() < d1.turnover.sum()

def test_simulate_weights_sum_at_most_one():
    from alpha_engine_v13.alpha_attribution_audit import _simulate_with_weights
    idx=pd.date_range('2020-01-02',periods=5,freq='B'); ret=pd.DataFrame({'A':0.0,'B':0.0},index=idx); pres=ret.notna()
    market={'calendar':idx,'returns':ret,'execution_presence':pres}; targets={idx[0]:{'A':.7,'B':.3}}
    _,w=_simulate_with_weights(targets,market,{},idx[0],idx[-1]+pd.Timedelta(days=1),20,1)
    sums=w.groupby('date').weight.sum(); assert (sums<=1+1e-12).all()

def test_conviction_curve_deciles():
    from alpha_engine_v13.alpha_attribution_audit import _conviction_curve
    dates=pd.to_datetime(['2020-01-02']*20); ticks=[f'T{i}' for i in range(20)]
    a=pd.DataFrame({'signal_date':dates,'ticker':ticks,'expected_abs_per_session':np.arange(20)/1000,'expected_alpha_per_session':0.0,'uncertainty_per_session':.01})
    t=pd.DataFrame({'signal_date':dates,'ticker':ticks,'target_resolved_20d':True,'target_end_date_20d':pd.Timestamp('2020-02-01'),'fwd_return_20d':np.arange(20)/100,'excess_spy_20d':np.arange(20)/100,'excess_uew_20d':np.arange(20)/100})
    o=_conviction_curve(a,t); assert o.decile.min()==1 and o.decile.max()==10
