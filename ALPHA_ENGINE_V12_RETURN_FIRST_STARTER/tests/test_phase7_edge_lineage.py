import numpy as np
import pandas as pd

from alpha_engine_v12.edge_lineage import (
    EdgeSpec,
    fit_edge_calibration,
    expected_return_and_se,
    net_edge_target,
    _cap_weights,
    build_lineage_layers,
    lineage_metrics,
    select_edge_policy,
)


def synthetic_scores_targets():
    dates = pd.bdate_range('2019-01-02', periods=80)
    rows=[]; targets=[]
    for d in dates:
        for i in range(20):
            s=(i+0.5)/20
            t=f'T{i:02d}'
            rows.append({'signal_date':d,'ticker':t,'partition':'WF_2019_2020','alpha_score':s})
            targets.append({'signal_date':d,'ticker':t,'target_end_date_20d':d+pd.Timedelta(days=25),'target_resolved_20d':True,'fwd_return_20d':-0.05+0.20*s})
    return pd.DataFrame(rows), pd.DataFrame(targets)


def test_isotonic_expected_return_is_monotone():
    s,t=synthetic_scores_targets()
    c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2021-01-01'),20,5)
    y=c['isotonic_expected_return_20d'].to_numpy(float)
    assert np.all(np.diff(y)>=-1e-12)
    assert y[-1]>y[0]


def test_expected_return_lookup_respects_score_order():
    s,t=synthetic_scores_targets(); c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2021-01-01'),20,5)
    lo,_=expected_return_and_se(0.2,c); hi,_=expected_return_and_se(0.9,c)
    assert hi>lo


def test_net_edge_refuses_small_improvement_after_cost_and_uncertainty():
    s,t=synthetic_scores_targets(); c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2021-01-01'),20,5)
    cur={'A':1.0}
    sm={'A':0.80,'B':0.81}
    spec=EdgeSpec(0.75,1.5,100.0,1)
    out,diag=net_edge_target(cur,0.0,sm,c,spec,1,40.0)
    assert set(out)=={'A'}
    assert diag and not diag[0]['trade']


def test_net_edge_replaces_on_large_improvement():
    s,t=synthetic_scores_targets(); c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2021-01-01'),20,5)
    cur={'A':1.0}; sm={'A':0.10,'B':0.99}
    spec=EdgeSpec(0.75,0.0,0.0,1)
    out,diag=net_edge_target(cur,0.0,sm,c,spec,1,20.0)
    assert set(out)=={'B'}
    assert diag[0]['trade']
    assert diag[0]['net_edge']>0


def test_cap_weights_sums_to_one_and_respects_cap_when_feasible():
    w={'A':0.8,'B':0.1,'C':0.1,'D':0.1,'E':0.1,'F':0.1,'G':0.1,'H':0.1,'I':0.1,'J':0.1}
    out=_cap_weights(w,0.20)
    assert np.isclose(sum(out.values()),1.0)
    assert max(out.values())<=0.2000001


def test_lineage_layers_reference_top15_and_theoretical_top20():
    s,t=synthetic_scores_targets(); c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2021-01-01'),20,5)
    class C:
        lineage_candidate_count=20; lineage_reference_top_n=15; optimizer_max_weight=0.12
    sm={f'T{i:02d}':(i+1)/20 for i in range(20)}
    layer,opt=build_lineage_layers(sm,c,C(),0.5)
    assert len(layer)==20
    assert np.isclose(layer['reference_weight'].sum(),1.0)
    assert (layer['reference_weight']>0).sum()==15
    assert np.isclose(layer['theoretical_weight'].sum(),1.0)
    assert np.isclose(sum(opt.values()),1.0)


def test_lineage_metrics_detects_full_top10_capture_for_monotone_weights():
    tick=[f'T{i:02d}' for i in range(20)]
    alpha=np.linspace(1,0.05,20)
    ref=np.array([1/15]*15+[0]*5)
    theory=np.linspace(20,1,20); theory=theory/theory.sum()
    opt=theory.copy()
    layer=pd.DataFrame({'ticker':tick,'alpha_score':alpha,'reference_weight':ref,'theoretical_weight':theory,'optimizer_weight':opt})
    milp={t:1/15 for t in tick[:15]}
    m=lineage_metrics(layer,milp)
    assert m['top10_capture']==1.0
    assert m['alpha_capture']>0.9


def test_select_edge_policy_is_return_first():
    x=pd.DataFrame([
        {'entry_floor':.8,'uncertainty_z':1,'minimum_extra_edge_bps':50,'max_replacements':1,'qualified':True,'selection_cagr_20bps':.30,'selection_cagr_40bps':.25,'selection_max_drawdown_20bps':-.3,'selection_annual_turnover_20bps':8},
        {'entry_floor':.8,'uncertainty_z':1,'minimum_extra_edge_bps':100,'max_replacements':1,'qualified':True,'selection_cagr_20bps':.20,'selection_cagr_40bps':.19,'selection_max_drawdown_20bps':-.1,'selection_annual_turnover_20bps':1},
    ])
    out=select_edge_policy(x)
    assert np.isclose(out.iloc[0]['selection_cagr_20bps'],.30)


def test_calibration_respects_target_end_boundary():
    s,t=synthetic_scores_targets()
    # Make the last half mature only after boundary. Calibration must still work using the causal half.
    t.loc[t['signal_date']>=t['signal_date'].median(),'target_end_date_20d']=pd.Timestamp('2022-01-01')
    c=fit_edge_calibration(s,t,['WF_2019_2020'],pd.Timestamp('2020-01-01'),20,5)
    assert (c['target_end_before']=='2020-01-01').all()


def test_milp_discretization_preserves_sum_cardinality_and_top_alpha():
    from alpha_engine_v12.edge_lineage import solve_weight_milp
    tick=[f'T{i:02d}' for i in range(20)]
    alpha=np.linspace(1.0,0.05,20)
    theory=np.exp(np.linspace(2,-2,20)); theory=theory/theory.sum()
    opt=theory.copy()
    # pre-cap to a feasible research optimizer surface
    opt=np.minimum(opt,.12); opt=opt/opt.sum()
    layer=pd.DataFrame({'ticker':tick,'alpha_score':alpha,'reference_weight':[1/15]*15+[0]*5,'theoretical_weight':theory,'optimizer_weight':opt})
    class C:
        milp_weight_step=.005; milp_min_weight=.03; milp_max_weight=.12; milp_holdings=15
    w,info=solve_weight_milp(layer,{},C())
    assert info['success']
    assert np.isclose(sum(w.values()),1.0)
    assert len(w)==15
    assert all(v>=.03-1e-9 and v<=.12+1e-9 for v in w.values())
    assert set(tick[:10]).issubset(w)
