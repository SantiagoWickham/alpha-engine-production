from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine_v12.portfolio_policy import (
    EnsembleSpec, build_ensemble_surface, event_target, should_schedule,
    simulate_policy, select_policy, _select_score_frame,
)


def test_ensemble_weighted_rank_requires_components():
    rows=[]
    for h in [20,60]:
        for t,s in [('A',0.9 if h==20 else 0.8),('B',0.4 if h==20 else 0.6)]:
            rows.append({'signal_date':pd.Timestamp('2020-01-02'),'ticker':t,'horizon_sessions':h,'score_rank_pct':s,'partition':'F'})
    x=pd.DataFrame(rows)
    e=EnsembleSpec('E',{20:0.5,60:0.5,120:0.0,252:0.0})
    out=build_ensemble_surface(x,e,'F')
    a=out.loc[out.ticker.eq('A'),'ensemble_score'].iloc[0]
    b=out.loc[out.ticker.eq('B'),'ensemble_score'].iloc[0]
    assert a>b


def test_monthly_and_weekly_schedule_only_first_observation():
    yes,k=should_schedule(pd.Timestamp('2024-01-02'),'MONTHLY',None)
    assert yes
    yes2,k2=should_schedule(pd.Timestamp('2024-01-03'),'MONTHLY',k)
    assert not yes2 and k2==k
    w1,wk=should_schedule(pd.Timestamp('2024-01-02'),'WEEKLY',None)
    w2,_=should_schedule(pd.Timestamp('2024-01-03'),'WEEKLY',wk)
    assert w1 and not w2


def test_event_hysteresis_keeps_when_no_material_challenger():
    cur={'A':0.5,'B':0.5}
    scores={'A':0.82,'B':0.78,'C':0.81}
    out=event_target(cur,0.0,scores,2,0.8,0.8,0.05,2)
    assert set(out)=={'A','B'}


def test_event_hysteresis_replaces_weak_holding_on_material_edge():
    cur={'A':0.5,'B':0.5}
    scores={'A':0.92,'B':0.60,'C':0.91}
    out=event_target(cur,0.0,scores,2,0.8,0.8,0.05,2)
    assert set(out)=={'A','C'}
    assert np.isclose(out['C'],0.5)


def test_simulation_obeys_next_close_execution_no_same_day_capture():
    dates=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-06'])
    # A doubles from Jan2 to Jan3, then flat. Signal Jan2 must execute Jan3 close and not capture the doubling.
    prices=pd.DataFrame({'date':dates,'ticker':['A']*3,'target_total_return_price':[100.0,200.0,200.0]})
    scores=pd.DataFrame({'signal_date':[pd.Timestamp('2020-01-02')],'ticker':['A'],'ensemble_score':[1.0]})
    met, daily=simulate_policy(scores,prices,{},dates[0],pd.Timestamp('2020-01-07'),1,'DAILY',20.0)
    assert np.isclose(daily.iloc[1]['gross_return'],0.0)
    assert met['total_return'] < 0.001  # only entry cost, no look-ahead profit


def test_full_switch_round_trip_cost_math():
    dates=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-06','2020-01-07'])
    prices=pd.DataFrame({
        'date':list(dates)*2,
        'ticker':['A']*4+['B']*4,
        'target_total_return_price':[100,100,100,100,100,100,100,100],
    })
    scores=pd.DataFrame({
        'signal_date':[dates[0],dates[0],dates[1],dates[1]],
        'ticker':['A','B','A','B'],
        'ensemble_score':[1.0,0.5,0.1,1.0],
    })
    _, daily=simulate_policy(scores,prices,{},dates[0],pd.Timestamp('2020-01-08'),1,'DAILY',20.0)
    # Initial buy costs 10 bps; full A->B switch costs 20 bps at next close.
    costs=daily.loc[daily.cost_fraction>0,'cost_fraction'].tolist()
    assert len(costs)>=2
    assert np.isclose(costs[0],0.001)
    assert np.isclose(costs[1],0.002)


def test_terminal_overlay_converts_holding_to_cash_after_terminal_close():
    dates=pd.to_datetime(['2020-01-02','2020-01-03','2020-01-06'])
    prices=pd.DataFrame({'date':dates,'ticker':['A']*3,'target_total_return_price':[100,100,100]})
    scores=pd.DataFrame({'signal_date':[dates[0]],'ticker':['A'],'ensemble_score':[1.0]})
    _, daily=simulate_policy(scores,prices,{'A':pd.Timestamp('2020-01-03')},dates[0],pd.Timestamp('2020-01-07'),1,'DAILY',20.0)
    assert daily.loc[daily.date.eq(pd.Timestamp('2020-01-03')),'cash_weight'].iloc[0] > 0.99


def test_return_first_selection_prefers_higher_cagr_not_lower_turnover():
    x=pd.DataFrame([
        {'ensemble':'A','top_n':10,'policy':'EVENT_A','qualified':True,'oof_cagr_20bps':0.30,'worst_fold_cagr_20bps':0.10,'oof_cagr_40bps':0.25,'worst_fold_max_drawdown_20bps':-0.30,'mean_annual_turnover_20bps':8.0},
        {'ensemble':'B','top_n':10,'policy':'MONTHLY','qualified':True,'oof_cagr_20bps':0.20,'worst_fold_cagr_20bps':0.15,'oof_cagr_40bps':0.18,'worst_fold_max_drawdown_20bps':-0.10,'mean_annual_turnover_20bps':1.0},
    ])
    out=select_policy(x)
    assert out.iloc[0]['ensemble']=='A'


def test_policy_selection_table_contains_no_sharpe_requirement():
    import inspect
    src=inspect.getsource(select_policy).lower()
    assert 'sharpe' not in src


def test_final_oos_boundary_is_not_needed_for_synthetic_simulation():
    # Guard against accidental future-date dependency in the policy simulator itself.
    dates=pd.to_datetime(['2024-12-27','2024-12-30'])
    prices=pd.DataFrame({'date':dates,'ticker':['A','A'],'target_total_return_price':[100,101]})
    scores=pd.DataFrame({'signal_date':[dates[0]],'ticker':['A'],'ensemble_score':[1.0]})
    met,_=simulate_policy(scores,prices,{},dates[0],pd.Timestamp('2025-01-01'),1,'DAILY',20.0)
    assert met['days']==2


def test_score_frame_selection_uses_boolean_rows_and_explicit_columns():
    ranked = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
        "ticker": ["A", "B", "C"],
        "f1": [0.1, 0.2, 0.3],
        "f2": [1.0, 2.0, 3.0],
    })
    out = _select_score_frame(ranked, pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-04"), ["f1", "f2"])
    assert list(out.columns) == ["signal_date", "ticker", "f1", "f2"]
    assert out["ticker"].tolist() == ["B", "C"]
    assert out["signal_date"].min() == pd.Timestamp("2020-01-02")
