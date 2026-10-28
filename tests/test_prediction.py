"""Regression tests for probability accounting, cutoff integrity, and API shape."""
import csv
import datetime as dt
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from model_core import Params, SimResult, simulate, blend_logodds, _adjust_offsets
from exchange_calendar import exchange_holidays
from analyze_term_structure import build_term_structure, build_jumps, isotonic_probabilities
from calibrate_model import market_cdf_fn, conditional_probability
from project_config import AS_OF, cutoff_utc, market_deadline
from polymarket_client import yes_token, get_history_v2


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.p = Params()
        self.t0 = self.p.investor_day
        # Boundary paths on 11/30, 12/01, 12/15, 12/16, and one absorbing No.
        days = [dt.date(2026,11,30), dt.date(2026,12,1), dt.date(2026,12,15), dt.date(2026,12,16), dt.date(2026,11,20)]
        self.res = SimResult(self.p, 5, 0, np.array([(d-self.t0).days for d in days]), np.array([False]*4+[True]))

    def test_inclusive_contract_deadline(self):
        self.assertEqual(self.res.cdf(dt.date(2026,12,15)), .6)
        self.assertEqual(market_deadline({"deadline":"December 15, 2026", "end_date":"2026-12-16T04:59:00Z"}), dt.date(2026,12,15))

    def test_buckets_partition_every_path_once(self):
        bounds = [self.t0, dt.date(2026,12,1), dt.date(2026,12,16), dt.date(2027,1,1)]
        probs = [self.res.bucket(a,b) for a,b in zip(bounds,bounds[1:])] + [self.res.bucket(bounds[-1])]
        np.testing.assert_allclose(probs, [.2,.4,.2,.2])
        self.assertAlmostEqual(sum(probs), 1)

    def test_failure_never_becomes_listing(self):
        self.assertEqual(self.res.cdf(dt.date(2099,1,1)), .8)
        failed = simulate(Params(stall_prob=1), 50)
        self.assertEqual(failed.cdf(dt.date(2099,1,1)), 0)
        self.assertIsNone(failed.date_at(.5))

    def test_all_failure_quantiles(self):
        self.assertTrue(all(v is None for v in simulate(Params(stall_prob=1), 5).quantiles().values()))

    def test_calendar_christmas_and_weekend(self):
        dates = [dt.date(2026,12,25),dt.date(2026,12,26),dt.date(2026,11,26),dt.date(2026,11,27)]
        offsets = np.array([(d-self.t0).days for d in dates])
        actual = [self.t0+dt.timedelta(days=int(i)) for i in _adjust_offsets(offsets,self.t0,self.p.thanksgiving)]
        self.assertEqual(actual,[dt.date(2026,12,28),dt.date(2026,12,28),dt.date(2026,11,27),dt.date(2026,11,27)])

    def test_regular_calendar_reference(self):
        self.assertIn(dt.date(2026,4,3), exchange_holidays(2026))
        self.assertIn(dt.date(2027,3,26), exchange_holidays(2027))
        self.assertNotIn(dt.date(2027,12,31), exchange_holidays(2027))

    def test_invalid_inputs(self):
        for kw in ({"stall_prob":1.1}, {"gap":(26,20,40)}, {"slip_share":float("nan")}):
            with self.assertRaises(ValueError): Params(**kw)
        with self.assertRaises(ValueError): simulate(Params(),0)
        with self.assertRaises(ValueError): blend_logodds(.5,.5,1.5)
        with self.assertRaises(ValueError): blend_logodds(float("nan"),.5,.5)

    def test_pool_endpoints_and_no_overflow(self):
        self.assertEqual(blend_logodds(.2,.8,0),.8)
        self.assertEqual(blend_logodds(.2,.8,1),.2)
        self.assertAlmostEqual(blend_logodds(.2,.8,.5),.5)

    def test_common_random_numbers_and_evidence_gate(self):
        a = simulate(Params(),2000,123)
        b = simulate(Params(slip_share=.5),2000,123)
        np.testing.assert_array_equal(a.stall,b.stall)
        self.assertTrue(np.all(b.offset>=a.offset))
        self.assertEqual(a.cdf(dt.date(2026,11,15)),0)
        np.testing.assert_array_equal(a.offset,simulate(Params(),2000,123).offset)

    def test_conditional_event_impossible_returns_null(self):
        self.assertIsNone(conditional_probability(1,1))
        self.assertAlmostEqual(conditional_probability(.8,.5),.6)


class DataTests(unittest.TestCase):
    def test_monotonic_repair(self):
        np.testing.assert_allclose(isotonic_probabilities([.1,.4,.3,.8]),[.1,.35,.35,.8])
        with self.assertRaises(ValueError): isotonic_probabilities([float("nan")])

    def test_hazard_uses_survival_and_percentage_units(self):
        snap = {}
        for slug,label,p in [("november-15-2026","November 15, 2026",.2),("november-30-2026","November 30, 2026",.5)]:
            snap[slug] = dict(slug=slug,deadline=label,yes_price=p,end_date="2026-12-01T04:59:00Z",volume="",liquidity="",spread="",closed="False")
        rows = build_term_structure(snap,{})
        self.assertAlmostEqual(rows[-1]["annualized_hazard_pct"], -math.log(.5/.8)/15*365*100, places=4)
        self.assertEqual(rows[-1]["liquidity_usd"],"")

    def test_no_fake_daily_jump_across_missing_day(self):
        z = dt.timezone.utc
        hist = {"x":[(dt.datetime(2026,10,1,tzinfo=z),.1),(dt.datetime(2026,10,3,tzinfo=z),.4)]}
        self.assertEqual(build_jumps(hist),[])

    def test_market_cdf_has_zero_anchor(self):
        today = dt.date(2026,10,14)
        f,_ = market_cdf_fn({"x":today+dt.timedelta(days=10)},{"x":.5},today)
        self.assertEqual(f(today),0)
        self.assertEqual(f(today+dt.timedelta(days=5)),.25)

    def test_yes_outcome_order(self):
        self.assertEqual(yes_token({"outcomes":json.dumps(["No","Yes"]),"clobTokenIds":json.dumps(["n","y"])}),"y")

    def test_v2_history_cursor_dedup_and_window_filter(self):
        pages = [{"data":[{"timestamp":99,"price":.1},{"timestamp":100,"price":.2}],"pagination":{"next_cursor":"next"}},
                 {"data":[{"timestamp":100,"price":.2},{"timestamp":101,"price":.3},{"timestamp":200,"price":.5}],"pagination":{"next_cursor":None}}]
        with patch("polymarket_client.get_json",side_effect=pages) as get:
            result = get_history_v2("token",100,200)
        self.assertEqual(result,[{"t":100,"p":.2},{"t":101,"p":.3}])
        self.assertIn("cursor=next",get.call_args[0][0])

    def test_asof_during_dst(self):
        self.assertEqual(cutoff_utc(dt.date(2026,10,14)).isoformat(),"2026-10-15T04:00:00+00:00")
        self.assertEqual(cutoff_utc(dt.date(2026,11,9)).hour,5)

    def test_generated_forecast_integrity(self):
        fc = json.loads((ROOT/"data/processed/forecast.json").read_text(encoding="utf-8"))
        self.assertEqual(fc["as_of"],"2026-10-14")
        self.assertNotIn("band_80pct",fc["final"])
        self.assertNotIn("December 15, 2026",fc["model"]["fit_targets"])
        expected = blend_logodds(fc["evidence_model"]["p_by_target"],fc["market"]["yes_price"],fc["final"]["model_weight"])
        self.assertAlmostEqual(expected,fc["final"]["p_final"])
        self.assertLess(dt.datetime.fromisoformat(fc["market"]["quote_utc"]),cutoff_utc())
        with (ROOT/"data/processed/bucket_implied.csv").open(encoding="utf-8") as fh:
            buckets = list(csv.DictReader(fh))
        for name in ("market_prob","model_prob"):
            self.assertAlmostEqual(sum(float(b[name]) for b in buckets),1)


if __name__ == "__main__":
    unittest.main()
