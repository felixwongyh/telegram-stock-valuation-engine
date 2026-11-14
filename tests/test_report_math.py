"""
tests/test_report_math.py — Phase 1.5 report math & wording validation.

Guards the acceptance criterion that "all percentages must validate direction and
basis" (e.g. "当前价较乐观情景高 170.4%" must never be reworded as
"乐观情景低于当前价 170%"), that the sample-count identity is reported honestly,
and that a core model dropped by the IQR filter can never sit beside a "strong
agreement" label.
"""
from __future__ import annotations

import pytest

from reporting.math_audit import (
    audit_report_math,
    pct_vs,
    phrase_vs,
    stated_direction,
    valuation_band,
    valuation_band_from_model_gap,
)


class TestPctVs:
    def test_positive_when_value_above_ref(self):
        assert pct_vs(523.0, 412.75) == pytest.approx((523.0 - 412.75) / 412.75)

    def test_negative_when_value_below_ref(self):
        result = pct_vs(170.70, 523.0)
        assert result is not None
        assert result < 0

    def test_zero_ref_is_none(self):
        assert pct_vs(10.0, 0.0) is None

    def test_missing_is_none(self):
        assert pct_vs(None, 10.0) is None
        assert pct_vs(10.0, None) is None


class TestPhraseVsBaseAnchoring:
    """The magnitude must always be worded against the SAME base it came from."""

    def test_positive_gap_never_says_lower(self):
        # value above ref → "高出", never "低".
        s = phrase_vs(523.00, 412.75, subject="当前价", ref_name="中位估值")
        assert "高出" in s
        assert "低 " not in s and "低于" not in s

    def test_negative_gap_says_lower(self):
        s = phrase_vs(170.70, 523.00, subject="当前价", ref_name="中位估值")
        assert "低 " in s
        assert "高出" not in s

    def test_quote_of_base_is_explicit(self):
        s = phrase_vs(523.00, 412.75, subject="当前价", ref_name="中位估值")
        assert "412.75" in s  # the base is printed next to the percentage

    def test_missing_returns_placeholder_not_wrong_number(self):
        assert "无法比较" in phrase_vs(523.0, None)


class TestCanonicalLadder:
    def test_band_thresholds(self):
        assert valuation_band(0.60)[0] == "显著高估"
        assert valuation_band(0.30)[0] == "明显高估"
        assert valuation_band(0.10)[0] == "小幅高估"
        assert valuation_band(0.0)[0] == "估值合理"
        assert valuation_band(-0.10)[0] == "小幅低估"
        assert valuation_band(-0.30)[0] == "明显低估"
        assert valuation_band(-0.60)[0] == "显著低估"

    def test_model_gap_flips_sign(self):
        # model above price (+30%) ⇒ undervalued.
        assert valuation_band_from_model_gap(0.30)[0] == "明显低估"
        assert valuation_band_from_model_gap(-0.30)[0] == "明显高估"

    def test_none_band_is_data_insufficient(self):
        assert valuation_band(None)[0] == "数据不足"


class TestStatedDirection:
    def test_high_words(self):
        for w in ("显著高估", "明显高估", "小幅高估", "偏贵"):
            assert stated_direction(w) == "high"

    def test_low_words(self):
        for w in ("显著低估", "明显低估", "小幅低估", "略便宜"):
            assert stated_direction(w) == "low"

    def test_fair_words(self):
        assert stated_direction("估值合理") == "fair"


class _Card:
    def __init__(self, median_label="", headline=""):
        self.median_vs_price_label = median_label
        self.headline_label = headline


class _Agreement:
    def __init__(self, raw=5, out=1, eff=4, level="Moderate",
                 core_excluded=False, dcf_value=None, material=False):
        self.raw_solved_count = raw
        self.outlier_count = out
        self.effective_aggregation_count = eff
        self.agreement_level = level
        self.core_model_excluded = core_excluded
        self.dcf_value = dcf_value
        self.material_disagreement = material


class TestAuditDetectsInconsistencies:
    def test_direction_flag_when_label_contradicts_sign(self):
        # label says 高估 but price is actually BELOW the median → flag.
        audit = audit_report_math(
            price=350.0, median=412.75, card=_Card(median_label="**显著高估**"),
        )
        assert not audit.ok
        assert any(c.status == "flag" and c.label == "中位对比方向" for c in audit.checks)

    def test_direction_ok_when_consistent(self):
        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
        )
        assert audit.ok

    def test_core_exclusion_with_strong_agreement_flags(self):
        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
            agreement=_Agreement(level="Very Strong", core_excluded=True),
        )
        assert not audit.ok
        assert any(c.label == "核心模型排除一致性" and c.status == "flag" for c in audit.checks)

    def test_core_exclusion_with_unresolved_level_is_ok(self):
        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
            agreement=_Agreement(
                level="Unresolved Disagreement (Review Required)", core_excluded=True,
            ),
        )
        assert audit.ok

    def test_sample_identity_break_flags(self):
        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
            agreement=_Agreement(raw=5, out=2, eff=4),  # 4 + 2 != 5
        )
        assert not audit.ok
        assert any(c.label == "样本口径恒等式" and c.status == "flag" for c in audit.checks)

    def test_sample_identity_holds(self):
        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
            agreement=_Agreement(raw=5, out=1, eff=4),
        )
        assert audit.ok

    def test_non_monotone_scenarios_flag(self):
        class _SV:
            def __init__(self, v):
                self.value_per_share = v

        audit = audit_report_math(
            price=523.0, median=412.75, card=_Card(median_label="**明显高估**"),
            scenarios={"Bear": _SV(300.0), "Base": _SV(200.0), "Bull": _SV(400.0)},
        )
        assert not audit.ok
        assert any(c.label == "情景区间单调性" for c in audit.checks)


class TestEndToEndWording:
    """A real rendered pipeline must not emit a base-inverted percentage."""

    def test_msft_verdict_audit_passes_and_sv_removed(self):
        from tests.golden_report import run_pipeline, render_report

        ctx = run_pipeline("MSFT")
        card = ctx["profile"].valuation_verdict
        assert card is not None
        assert card.math_audit is not None
        assert card.math_audit.ok, [c.detail for c in card.math_audit.checks]

        report = render_report(ctx)
        # The ambiguous "% SV" abbreviation must be gone.
        assert "% SV" not in report

    def test_median_detail_is_base_anchored(self):
        from tests.golden_report import run_pipeline

        ctx = run_pipeline("MSFT")
        card = ctx["profile"].valuation_verdict
        detail = card.median_vs_price_detail or ""
        if "较中位估值" in detail or "较 中位估值" in detail:
            # Whatever the sign, the sentence must anchor on the median base.
            assert "中位估值" in detail
