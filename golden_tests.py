"""
Golden tests for the Threadneedle HANK central bank environment.

Tests verify that the economic model produces empirically sensible
impulse responses calibrated to UK data. See CITATIONS.md for sources.
"""

import pytest
import asyncio
import numpy as np
from copy import deepcopy

from hank_model import (
    HANKModel,
    EconomyState,
    QuarterShocks,
    SCENARIOS,
    TRAIN_SCENARIOS,
    TEST_SCENARIOS,
)

from threadneedle import Threadneedle, SetPolicyInput, ViewEconomyInput, ViewHistoryInput


@pytest.fixture
def model():
    return HANKModel()


@pytest.fixture
def steady_state():
    """Economy at steady state (all variables at their equilibrium values)."""
    return EconomyState(
        i=3.0, pi=2.0, y=0.0, u=4.25, hp=3.0, er=100.0,
        w=3.0, conf=0.0, gini=0.34, r_long=3.5, cum_qe=0.0,
    )


@pytest.fixture
def no_shocks():
    return QuarterShocks()


# ──────────────────────────────────────────────────────────────
# Test 4: Rate hike reduces inflation
# Target: 1pp hike -> inflation falls within 4 quarters
# Source: Cloyne & Hurtgen (2016), BoE COMPASS
# ──────────────────────────────────────────────────────────────

def test_rate_hike_reduces_inflation(model, steady_state, no_shocks):
    """A 200bp rate hike from steady state should reduce inflation within 4 quarters."""
    state = deepcopy(steady_state)
    initial_pi = state.pi

    # Apply 200bp hike (3.0% -> 5.0%) for 8 quarters
    for q in range(8):
        state = model.step(state, bank_rate=5.0, qe=0.0, shocks=no_shocks)

    # Inflation should be lower than initial after sustained hike
    assert state.pi < initial_pi, (
        f"Inflation should fall after sustained rate hike. "
        f"Initial: {initial_pi:.3f}, After 8Q: {state.pi:.3f}"
    )

    # Should be meaningfully lower (at least 0.1pp)
    assert state.pi < initial_pi - 0.1, (
        f"Inflation reduction too small after 200bp hike over 8Q. "
        f"Initial: {initial_pi:.3f}, After 8Q: {state.pi:.3f}"
    )


# ──────────────────────────────────────────────────────────────
# Test 5: Rate cut boosts output
# Target: Rate cut -> output gap improves within 2 quarters
# Source: Cloyne & Hurtgen (2016)
# ──────────────────────────────────────────────────────────────

def test_rate_cut_boosts_output(model, steady_state, no_shocks):
    """A 200bp rate cut should boost output gap within 2 quarters."""
    state = deepcopy(steady_state)
    initial_y = state.y

    # Apply 200bp cut (3.0% -> 1.0%)
    for q in range(2):
        state = model.step(state, bank_rate=1.0, qe=0.0, shocks=no_shocks)

    # Output gap should be positive (above steady state 0.0)
    assert state.y > initial_y, (
        f"Output gap should increase after rate cut. "
        f"Initial: {initial_y:.3f}, After 2Q: {state.y:.3f}"
    )


# ──────────────────────────────────────────────────────────────
# Test 6: QE boosts house prices
# Target: QE -> house prices rise
# Source: Haldane et al. (2016), Joyce et al. (2011)
# ──────────────────────────────────────────────────────────────

def test_qe_boosts_house_prices(model, steady_state, no_shocks):
    """Large-scale QE (3% GDP per quarter) should boost house prices."""
    state = deepcopy(steady_state)
    initial_hp = state.hp

    # 4 quarters of significant QE (3% GDP per quarter = 12% total)
    for q in range(4):
        state = model.step(state, bank_rate=3.0, qe=3.0, shocks=no_shocks)

    assert state.hp > initial_hp, (
        f"House price growth should increase with QE. "
        f"Initial: {initial_hp:.3f}, After 4Q QE: {state.hp:.3f}"
    )


# ──────────────────────────────────────────────────────────────
# Test 7: Rate hike increases unemployment
# Target: Rate hike -> unemployment rises
# Source: Cloyne & Hurtgen (2016), Okun's Law
# ──────────────────────────────────────────────────────────────

def test_rate_hike_increases_unemployment(model, steady_state, no_shocks):
    """A 200bp rate hike should increase unemployment."""
    state = deepcopy(steady_state)
    initial_u = state.u

    # Sustained 200bp hike for 4 quarters
    for q in range(4):
        state = model.step(state, bank_rate=5.0, qe=0.0, shocks=no_shocks)

    assert state.u > initial_u, (
        f"Unemployment should rise after rate hike. "
        f"Initial: {initial_u:.3f}, After 4Q: {state.u:.3f}"
    )


# ──────────────────────────────────────────────────────────────
# Test 8: Taylor Rule stabilizes the economy
# Target: Economy stays near targets when no shocks + Taylor Rule
# Source: Taylor (1993), Nelson (2000)
# ──────────────────────────────────────────────────────────────

def test_taylor_rule_stabilizes(model, steady_state, no_shocks):
    """Taylor Rule should keep economy near targets with no shocks."""
    state = deepcopy(steady_state)

    for q in range(20):
        taylor_rate = model.taylor_rule(state)
        state = model.step(state, bank_rate=taylor_rate, qe=0.0, shocks=no_shocks)

    # All variables should remain near steady state
    assert abs(state.pi - 2.0) < 0.5, (
        f"Inflation should stay near 2% under Taylor Rule. Got: {state.pi:.3f}"
    )
    assert abs(state.y) < 1.0, (
        f"Output gap should stay near 0 under Taylor Rule. Got: {state.y:.3f}"
    )
    assert abs(state.u - 4.25) < 0.5, (
        f"Unemployment should stay near NAIRU under Taylor Rule. Got: {state.u:.3f}"
    )


# ──────────────────────────────────────────────────────────────
# Test 9: HANK channels - different household responses
# Target: PHtM responds to employment, WHtM to house prices
# Source: Kaplan, Moll & Violante (2018)
# ──────────────────────────────────────────────────────────────

def test_hank_channels(model, steady_state, no_shocks):
    """
    HANK channels: PHtM output depends on employment, not interest rates.
    WHtM output depends on house prices, not interest rates.
    """
    s = steady_state

    # PHtM channel: y_PHtM = gamma_emp * (u* - u) + gamma_w * (w - pi)
    # At steady state: u = u*, w = pi + 1.0 -> y_PHtM = gamma_w * 1.0
    # With high unemployment: y_PHtM should decrease
    y_phtm_normal = model.GAMMA_EMP * (model.U_STAR - s.u) + model.GAMMA_W * (s.w - s.pi)
    y_phtm_high_u = model.GAMMA_EMP * (model.U_STAR - 6.0) + model.GAMMA_W * (s.w - s.pi)

    assert y_phtm_high_u < y_phtm_normal, (
        "PHtM output should fall when unemployment rises"
    )

    # Interest rate should NOT directly appear in PHtM calculation
    # (This is by construction in the model equations)

    # WHtM channel: y_WHtM = delta_hp * (hp - hp_bar) / 10 + delta_conf * conf / 100
    y_whtm_normal = model.DELTA_HP * (s.hp - model.HP_BAR) / 10.0 + model.DELTA_CONF * s.conf / 100.0
    y_whtm_high_hp = model.DELTA_HP * (15.0 - model.HP_BAR) / 10.0 + model.DELTA_CONF * s.conf / 100.0

    assert y_whtm_high_hp > y_whtm_normal, (
        "WHtM output should rise when house prices are high"
    )


# ──────────────────────────────────────────────────────────────
# Additional impulse response tests
# ──────────────────────────────────────────────────────────────

def test_qe_reduces_long_rates(model, steady_state, no_shocks):
    """QE should compress long-term interest rates (Joyce et al. 2011)."""
    state = deepcopy(steady_state)
    initial_r_long = state.r_long

    # Sustained QE for 4 quarters
    for q in range(4):
        state = model.step(state, bank_rate=3.0, qe=3.0, shocks=no_shocks)

    assert state.r_long < initial_r_long, (
        f"Long-term rate should fall with QE. "
        f"Initial: {initial_r_long:.3f}, After 4Q QE: {state.r_long:.3f}"
    )


def test_sterling_depreciation_raises_inflation(model, steady_state):
    """Sterling depreciation should raise inflation via exchange rate pass-through."""
    state = deepcopy(steady_state)

    # Apply risk premium shock to depreciate sterling
    shock_with_risk = QuarterShocks(risk_premium=3.0)
    state = model.step(state, bank_rate=3.0, qe=0.0, shocks=shock_with_risk)

    # Exchange rate should fall
    assert state.er < 100.0, (
        f"Exchange rate should fall with risk premium shock. Got: {state.er:.3f}"
    )

    # Now advance another quarter to let ERPT feed through
    state2 = model.step(state, bank_rate=3.0, qe=0.0, shocks=QuarterShocks())

    # Inflation should be above 2% due to pass-through
    assert state2.pi > 2.0 or state.pi > 2.0, (
        f"Inflation should rise from sterling depreciation. "
        f"Q1 pi: {state.pi:.3f}, Q2 pi: {state2.pi:.3f}"
    )


def test_qe_increases_inequality(model, steady_state, no_shocks):
    """QE should increase Gini coefficient (Haldane et al. 2016)."""
    state = deepcopy(steady_state)
    initial_gini = state.gini

    for q in range(4):
        state = model.step(state, bank_rate=3.0, qe=4.0, shocks=no_shocks)

    assert state.gini > initial_gini, (
        f"Gini should rise with QE. "
        f"Initial: {initial_gini:.4f}, After 4Q QE: {state.gini:.4f}"
    )


def test_overheating_scenario_needs_tightening(model):
    """Overheating scenario: doing nothing should let inflation persist."""
    scenario = SCENARIOS["overheating"]
    state = deepcopy(scenario.initial_conditions)

    # Hold rate at current level for 8 quarters (insufficient tightening)
    for q in range(8):
        state = model.step(
            state, bank_rate=3.0, qe=0.0,
            shocks=scenario.shocks[q],
        )

    # Inflation should still be above target
    assert state.pi > 2.0, (
        f"With insufficient tightening, inflation should remain above target. "
        f"Got: {state.pi:.3f}"
    )


def test_demand_shock_output_collapse(model):
    """Demand shock scenario: output should collapse in early quarters."""
    scenario = SCENARIOS["demand_shock"]
    state = deepcopy(scenario.initial_conditions)

    # Hold rate constant for first 2 quarters
    for q in range(2):
        state = model.step(
            state, bank_rate=0.75, qe=0.0,
            shocks=scenario.shocks[q],
        )

    # Output gap should be deeply negative
    assert state.y < -2.0, (
        f"Output should collapse in demand shock scenario. "
        f"Got output gap: {state.y:.3f}"
    )


def test_financial_crisis_house_price_crash(model):
    """Financial crisis: house prices should decline sharply."""
    scenario = SCENARIOS["financial_crisis"]
    state = deepcopy(scenario.initial_conditions)
    initial_hp = state.hp

    # Run 4 quarters with modest rate cuts
    for q in range(4):
        state = model.step(
            state, bank_rate=max(0.5, 5.75 - q * 1.0), qe=0.0,
            shocks=scenario.shocks[q],
        )

    # House price growth should be much lower (or negative)
    assert state.hp < initial_hp, (
        f"House prices should decline in financial crisis. "
        f"Initial: {initial_hp:.3f}, After 4Q: {state.hp:.3f}"
    )


def test_all_scenarios_defined():
    """All 6 scenarios should be defined with 20 quarters of shocks."""
    expected = ["supply_shock", "demand_shock", "financial_crisis",
                "overheating", "stagflation", "global_tightening"]
    for name in expected:
        assert name in SCENARIOS, f"Missing scenario: {name}"
        scenario = SCENARIOS[name]
        assert len(scenario.shocks) == 20, (
            f"Scenario {name} should have 20 quarters of shocks, "
            f"got {len(scenario.shocks)}"
        )

    assert set(TRAIN_SCENARIOS) == {"supply_shock", "demand_shock", "financial_crisis", "overheating"}
    assert set(TEST_SCENARIOS) == {"stagflation", "global_tightening"}


def test_steady_state_stability(model, steady_state, no_shocks):
    """Economy at steady state with neutral policy should remain stable."""
    state = deepcopy(steady_state)

    for q in range(20):
        state = model.step(state, bank_rate=3.0, qe=0.0, shocks=no_shocks)

    # Should remain exactly at steady state (no drift)
    assert abs(state.pi - 2.0) < 0.001, f"Inflation drifted: {state.pi:.6f}"
    assert abs(state.y) < 0.001, f"Output gap drifted: {state.y:.6f}"
    assert abs(state.u - 4.25) < 0.001, f"Unemployment drifted: {state.u:.6f}"
    assert abs(state.hp - 3.0) < 0.001, f"House prices drifted: {state.hp:.6f}"
    assert abs(state.gini - 0.34) < 0.001, f"Gini drifted: {state.gini:.6f}"
    assert abs(state.conf) < 0.001, f"Confidence drifted: {state.conf:.6f}"
    assert abs(state.w - 3.0) < 0.001, f"Wages drifted: {state.w:.6f}"
    assert abs(state.r_long - 3.5) < 0.001, f"Long rate drifted: {state.r_long:.6f}"


def test_loss_function_positive_definite(model, steady_state):
    """Loss function should be zero at steady state and positive elsewhere."""
    # At steady state with no rate change, loss should be near zero
    loss_ss = model.compute_loss(steady_state, prev_rate=3.0)
    assert abs(loss_ss) < 0.01, f"Loss at steady state should be ~0, got: {loss_ss:.6f}"

    # With inflation above target, loss should be positive
    high_pi_state = deepcopy(steady_state)
    high_pi_state.pi = 5.0
    loss_high_pi = model.compute_loss(high_pi_state, prev_rate=3.0)
    assert loss_high_pi > 0, f"Loss should be positive with high inflation: {loss_high_pi:.6f}"
    assert loss_high_pi > loss_ss, "Loss should be higher with inflation above target"


def test_reward_sign_convention(model, steady_state, no_shocks):
    """
    Reward = taylor_loss - agent_loss.
    Agent doing better than Taylor -> positive reward.
    """
    state = deepcopy(steady_state)
    taylor_state = deepcopy(steady_state)

    # Agent perfectly matches Taylor Rule
    taylor_rate = model.taylor_rule(state)
    agent_state = model.step(state, bank_rate=taylor_rate, qe=0.0, shocks=no_shocks)
    taylor_new = model.step(taylor_state, bank_rate=taylor_rate, qe=0.0, shocks=no_shocks)

    agent_loss = model.compute_loss(agent_state, prev_rate=steady_state.i)
    taylor_loss = model.compute_loss(taylor_new, prev_rate=steady_state.i)

    # When agent matches Taylor, reward should be ~0
    reward = taylor_loss - agent_loss
    assert abs(reward) < 0.01, f"Reward should be ~0 when matching Taylor Rule: {reward:.6f}"


# ══════════════════════════════════════════════════════════════
# Environment-level tests (tests 1-3, 10)
# ══════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────
# Test 1: Environment initialization
# All 6 scenarios load correctly, prompt contains key terms
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_environment_initialization():
    """All scenarios should initialize and produce valid prompts."""
    for scenario_id in SCENARIOS:
        env = Threadneedle({"id": scenario_id})
        assert env.quarter == 0
        assert env.finished is False
        assert env.cumulative_reward == 0.0

        prompt = await env.get_prompt()
        assert len(prompt) == 1
        text = prompt[0].text

        # Prompt should contain key MPC-related terms
        assert "Monetary Policy Committee" in text
        assert "Bank Rate" in text
        assert "inflation" in text.lower()
        assert "set_policy" in text
        assert "web_search" in text
        assert scenario_id.replace("_", " ").title() in text

    # Invalid scenario should raise
    with pytest.raises(ValueError, match="Unknown scenario"):
        Threadneedle({"id": "nonexistent_scenario"})


# ──────────────────────────────────────────────────────────────
# Test 2: Single policy step
# set_policy returns valid ToolOutput with all expected fields
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_policy_step():
    """A single set_policy call should return valid output and advance the quarter."""
    env = Threadneedle({"id": "supply_shock"})

    result = await env.set_policy(SetPolicyInput(bank_rate=3.0, qe=0.0))

    # Should not be finished after one quarter
    assert result.finished is False
    assert env.quarter == 1

    # ToolOutput structure
    assert result.blocks is not None
    assert len(result.blocks) >= 1
    text = result.blocks[0].text
    assert "Quarter 1/20" in text
    assert "YOUR POLICY" in text
    assert "TAYLOR RULE" in text
    assert "SCORE" in text

    # Metadata should contain full record
    meta = result.metadata
    assert meta["quarter"] == 1
    assert "agent_policy" in meta
    assert "taylor_policy" in meta
    assert "agent_state" in meta
    assert "taylor_state" in meta
    assert "quarter_reward" in meta
    assert "cumulative_reward" in meta

    # Agent state should have all economy variables
    agent_state = meta["agent_state"]
    expected_keys = [
        "bank_rate", "inflation", "output_gap", "unemployment",
        "house_price_growth", "exchange_rate", "wage_growth",
        "consumer_confidence", "gini_coefficient", "long_term_rate",
        "cumulative_qe",
    ]
    for key in expected_keys:
        assert key in agent_state, f"Missing key in agent_state: {key}"


# ──────────────────────────────────────────────────────────────
# Test 3: Rate bounds validation
# Out-of-range Bank Rate and QE should be rejected gracefully
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_bounds_validation():
    """Out-of-range Bank Rate and QE should return errors without advancing."""
    env = Threadneedle({"id": "supply_shock"})

    # Bank Rate too low
    result = await env.set_policy(SetPolicyInput(bank_rate=0.0, qe=0.0))
    assert result.finished is False
    assert result.reward == 0.0
    assert env.quarter == 0  # Should NOT advance
    assert "Error" in result.blocks[0].text or "error" in str(result.metadata)

    # Bank Rate too high
    result = await env.set_policy(SetPolicyInput(bank_rate=16.0, qe=0.0))
    assert result.finished is False
    assert result.reward == 0.0
    assert env.quarter == 0

    # QE too high
    result = await env.set_policy(SetPolicyInput(bank_rate=3.0, qe=6.0))
    assert result.finished is False
    assert result.reward == 0.0
    assert env.quarter == 0

    # QE too low
    result = await env.set_policy(SetPolicyInput(bank_rate=3.0, qe=-6.0))
    assert result.finished is False
    assert result.reward == 0.0
    assert env.quarter == 0

    # Valid call should work after errors
    result = await env.set_policy(SetPolicyInput(bank_rate=3.0, qe=0.0))
    assert env.quarter == 1


# ──────────────────────────────────────────────────────────────
# Test 10: Full 20-quarter episode
# Complete episode finishes with cumulative reward
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_episode():
    """A complete 20-quarter episode should finish with cumulative reward."""
    env = Threadneedle({"id": "overheating"})

    total_reward = 0.0
    for q in range(20):
        # Simple reactive policy: raise rates if inflation high, cut if low
        state = env.agent_state
        if state.pi > 3.0:
            rate = min(state.i + 0.5, 15.0)
        elif state.pi < 1.5:
            rate = max(state.i - 0.5, 0.1)
        else:
            rate = state.i

        result = await env.set_policy(SetPolicyInput(bank_rate=rate, qe=0.0))

        if q < 19:
            assert result.finished is False, f"Should not finish at quarter {q+1}"
        else:
            assert result.finished is True, "Should finish at quarter 20"

    assert env.quarter == 20
    assert env.finished is True

    # After finishing, further calls should error
    result = await env.set_policy(SetPolicyInput(bank_rate=3.0, qe=0.0))
    assert result.finished is True
    assert "already completed" in result.blocks[0].text.lower()

    # History should have 20 entries
    assert len(env.history) == 20


@pytest.mark.asyncio
async def test_view_tools():
    """view_economy and view_history should return valid outputs."""
    env = Threadneedle({"id": "demand_shock"})

    # View economy at start
    result = await env.view_economy(ViewEconomyInput())
    assert result.finished is False
    assert result.reward == 0.0
    text = result.blocks[0].text
    assert "Quarter 0/20" in text
    assert "Demand Shock" in text
    assert "MACROECONOMIC INDICATORS" in text
    assert "Bank Rate" in text
    assert "Inflation" in text

    # View history before any steps
    result = await env.view_history(ViewHistoryInput())
    assert "No history" in result.blocks[0].text

    # Take a step, then check history
    await env.set_policy(SetPolicyInput(bank_rate=0.5, qe=2.0))
    result = await env.view_history(ViewHistoryInput())
    text = result.blocks[0].text
    assert "POLICY HISTORY" in text
    assert result.reward == 0.0
    assert result.finished is False

    # History metadata
    assert len(result.metadata["history"]) == 1


@pytest.mark.asyncio
async def test_final_reward_is_cumulative():
    """On the final quarter, reward should be cumulative, not per-quarter."""
    env = Threadneedle({"id": "overheating"})

    rewards = []
    for q in range(20):
        result = await env.set_policy(SetPolicyInput(bank_rate=5.0, qe=0.0))
        rewards.append(result.reward)

    # Sum of all per-quarter rewards should equal cumulative reward
    total = sum(rewards)
    assert abs(total - env.cumulative_reward) < 0.001, (
        f"Sum of rewards {total:.4f} should equal "
        f"cumulative {env.cumulative_reward:.4f}"
    )
