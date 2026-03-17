"""
Simplified HANK (Heterogeneous Agent New Keynesian) model calibrated to the UK economy.

All parameters are empirically grounded -- see CITATIONS.md for full justifications.
"""

import numpy as np
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class EconomyState:
    """State of the UK economy at a given quarter."""
    i: float = 3.0          # Bank Rate (%)
    pi: float = 2.0         # CPI inflation (%, annualized)
    y: float = 0.0          # Output gap (%)
    u: float = 4.25         # Unemployment rate (%)
    hp: float = 3.0         # House price growth (%, annualized)
    er: float = 100.0       # Exchange rate index (100 = baseline)
    w: float = 3.0          # Wage growth (%, annualized)
    conf: float = 0.0       # Consumer confidence (0 = neutral)
    gini: float = 0.34      # Gini coefficient
    r_long: float = 3.5     # Long-term interest rate (%)
    cum_qe: float = 0.0     # Cumulative QE (% of GDP)

    def to_dict(self) -> Dict[str, float]:
        return {
            "bank_rate": self.i,
            "inflation": self.pi,
            "output_gap": self.y,
            "unemployment": self.u,
            "house_price_growth": self.hp,
            "exchange_rate": self.er,
            "wage_growth": self.w,
            "consumer_confidence": self.conf,
            "gini_coefficient": self.gini,
            "long_term_rate": self.r_long,
            "cumulative_qe": self.cum_qe,
        }


@dataclass
class QuarterShocks:
    """Exogenous shocks for a single quarter."""
    eps_supply: float = 0.0      # Supply shock (pp added to inflation)
    eps_demand: float = 0.0      # Demand shock (pp added to output gap)
    eps_conf: float = 0.0        # Confidence shock (index points)
    risk_premium: float = 0.0    # Risk premium shock (for exchange rate)
    i_foreign: float = 3.5       # Foreign interest rate (%)


@dataclass
class ScenarioDefinition:
    """Full scenario specification."""
    name: str
    description: str
    initial_conditions: EconomyState
    shocks: List[QuarterShocks]  # Length 20 (one per quarter)


class HANKModel:
    """
    Simplified HANK model of the UK economy.

    Three household types with heterogeneous monetary policy transmission:
    - Unconstrained (65%): respond to interest rates via intertemporal substitution
    - Wealthy hand-to-mouth (25%): respond to asset prices (housing wealth)
    - Poor hand-to-mouth (10%): respond to employment and wages only

    See CITATIONS.md for empirical justification of all parameters.
    """

    # ── Household shares (Kaplan, Violante & Weidner 2014, UK WAS data) ──
    OMEGA_U = 0.65       # Unconstrained
    OMEGA_WHTM = 0.25    # Wealthy hand-to-mouth
    OMEGA_PHTM = 0.10    # Poor hand-to-mouth

    # ── Steady state values ──
    R_STAR = 1.0         # Real neutral rate (Holston, Laubach, Williams 2017)
    U_STAR = 4.25        # NAIRU (BoE MPR 2024-25)
    PI_STAR = 2.0        # Inflation target (BoE mandate)
    HP_BAR = 3.0         # Steady-state house price growth
    GINI_BAR = 0.34      # Steady-state Gini (ONS FYE 2024)
    I_FOREIGN_BAR = 3.5  # Steady-state foreign rate

    # ── IS Curve: Unconstrained households ──
    SIGMA_U = 0.25       # Interest rate elasticity (calibrated to Cloyne & Hurtgen 2016)
    PHI_Y = 0.65         # Output persistence
    PHI_QE = 0.15        # QE portfolio rebalancing (Joyce et al. 2011)

    # ── IS Curve: Poor hand-to-mouth ──
    GAMMA_EMP = 1.5      # Employment sensitivity (Kaplan, Moll, Violante 2018)
    GAMMA_W = 0.4        # Real wage sensitivity

    # ── IS Curve: Wealthy hand-to-mouth ──
    DELTA_HP = 0.5       # Housing wealth effect
    DELTA_CONF = 0.25    # Confidence channel

    # ── Phillips Curve (BoE SWP 1107, 2025) ──
    ALPHA_PI = 0.85      # Inflation persistence
    PI_E = 2.0           # Anchored inflation expectations
    KAPPA_Y = 0.10       # Output gap -> inflation
    KAPPA_U = 0.15       # Unemployment gap -> inflation
    KAPPA_ER = 0.30      # Exchange rate pass-through (Forbes et al. 2018)

    # ── Okun's Law (Ball, Leigh & Loungani 2017) ──
    KAPPA_OKUN = 0.30    # Okun coefficient
    KAPPA_REVERT = 0.08  # Mean reversion toward NAIRU

    # ── House Prices (Miles & Monro 2019) ──
    RHO_HP = 0.70        # Persistence
    ETA_R = 1.2          # Real rate sensitivity
    ETA_QE = 0.8         # QE effect (Haldane et al. 2016)
    ETA_Y = 0.5          # Output gap effect

    # ── Exchange Rate ──
    LAMBDA_ER = 4.0      # Interest differential sensitivity
    LAMBDA_RISK = 3.0    # Risk premium sensitivity

    # ── Wage Phillips Curve (Phillips 1958; Hendry et al.) ──
    RHO_W = 0.65         # Wage stickiness
    PROD_GROWTH = 1.0    # UK trend productivity growth (%)
    MU_U = 0.35          # Unemployment gap -> wages

    # ── Consumer Confidence ──
    RHO_CONF = 0.70      # Persistence
    CHI_Y = 3.0          # Output gap effect
    CHI_U = 2.5          # Unemployment effect
    CHI_PI = 1.5         # Inflation deviation effect

    # ── Gini Coefficient (Gornemann et al. 2016; Haldane et al. 2016) ──
    THETA_U = 0.5        # Unemployment -> inequality
    THETA_HP = 0.3       # House prices -> inequality
    THETA_QE = 0.2       # QE -> inequality

    # ── Long-term Rate (Malik & Meldrum 2016) ──
    ALPHA_LONG = 0.80    # Persistence
    TERM_PREMIUM = 0.50  # Normal term premium (bps -> %)
    ZETA_QE = 0.03       # QE -> long rate compression (Joyce et al. 2011)

    # ── Taylor Rule Baseline (Nelson 2000) ──
    RHO_TAYLOR = 0.82    # Interest rate smoothing
    ALPHA_TAYLOR_PI = 1.5  # Inflation coefficient (Taylor principle)
    ALPHA_TAYLOR_Y = 0.5   # Output gap coefficient

    # ── Loss Function Weights ──
    W_PI = 1.0           # Inflation (BoE primary mandate)
    W_Y = 1.0            # Output gap (Debortoli et al. 2019)
    W_U = 0.5            # Unemployment (Svensson 1997)
    W_DI = 0.25          # Rate smoothing (Rudebusch & Svensson 1999)
    W_GINI = 0.1         # Inequality (Acharya, Challe, Dogra 2023)

    # ── Bounds ──
    I_MIN = 0.1
    I_MAX = 15.0
    QE_MIN = -5.0
    QE_MAX = 5.0

    def __init__(self):
        pass

    def _get_effective_shares(self, gini: float) -> tuple:
        """
        Dynamically adjust household shares based on Gini coefficient.

        Higher inequality -> more households behave as hand-to-mouth
        (Kaplan, Moll & Violante 2018).
        """
        gini_deviation = gini - self.GINI_BAR
        # Shift unconstrained -> PHtM as inequality rises
        shift = 0.3 * gini_deviation
        omega_u = max(0.40, self.OMEGA_U - shift)
        omega_phtm = min(0.30, self.OMEGA_PHTM + shift * 0.6)
        omega_whtm = 1.0 - omega_u - omega_phtm
        # Ensure all positive
        omega_whtm = max(0.10, omega_whtm)
        total = omega_u + omega_phtm + omega_whtm
        return omega_u / total, omega_whtm / total, omega_phtm / total

    def step(
        self,
        state: EconomyState,
        bank_rate: float,
        qe: float,
        shocks: QuarterShocks,
        prev_i_foreign: float = 3.5,
    ) -> EconomyState:
        """
        Advance the economy by one quarter given policy decisions and shocks.

        Args:
            state: Current economic state
            bank_rate: Bank Rate set by agent (%)
            qe: QE flow this quarter (% of GDP, positive = purchases)
            shocks: Exogenous shocks for this quarter
            prev_i_foreign: Previous quarter's foreign interest rate

        Returns:
            New economic state after one quarter
        """
        s = state
        new = EconomyState()

        # Policy instrument
        new.i = np.clip(bank_rate, self.I_MIN, self.I_MAX)
        qe = np.clip(qe, self.QE_MIN, self.QE_MAX)

        # Cumulative QE
        new.cum_qe = s.cum_qe + qe

        # Get effective household shares
        omega_u, omega_whtm, omega_phtm = self._get_effective_shares(s.gini)

        # ── Eq 1: HANK IS Curve ──
        real_rate = new.i - s.pi
        y_u = (
            -self.SIGMA_U * (real_rate - self.R_STAR)
            + self.PHI_Y * s.y
            + self.PHI_QE * qe
        )
        y_phtm = (
            self.GAMMA_EMP * (self.U_STAR - s.u)
            + self.GAMMA_W * ((s.w - s.pi) - self.PROD_GROWTH)
        )
        y_whtm = (
            self.DELTA_HP * (s.hp - self.HP_BAR) / 10.0
            + self.DELTA_CONF * s.conf / 100.0
        )
        new.y = (
            omega_u * y_u
            + omega_phtm * y_phtm
            + omega_whtm * y_whtm
            + shocks.eps_demand
        )

        # ── Eq 3: Okun's Law ──
        # (Computed before Phillips curve since unemployment feeds into it)
        delta_y = s.y - new.y  # Output decline raises unemployment
        new.u = (
            s.u
            + self.KAPPA_OKUN * delta_y
            - self.KAPPA_REVERT * (s.u - self.U_STAR)
        )
        new.u = np.clip(new.u, 2.0, 12.0)

        # ── Eq 5: Exchange Rate ──
        rate_diff_change = (
            (new.i - shocks.i_foreign) - (s.i - prev_i_foreign)
        )
        new.er = (
            s.er
            + self.LAMBDA_ER * rate_diff_change
            - self.LAMBDA_RISK * shocks.risk_premium
        )
        new.er = np.clip(new.er, 70.0, 140.0)

        # ── Eq 2: Phillips Curve ──
        er_depreciation = max(0.0, -(new.er - s.er))  # Positive when sterling falls
        new.pi = (
            self.ALPHA_PI * s.pi
            + (1.0 - self.ALPHA_PI) * self.PI_E
            + self.KAPPA_Y * s.y
            + self.KAPPA_U * (self.U_STAR - new.u)
            + self.KAPPA_ER * er_depreciation / 10.0
            + shocks.eps_supply
        )

        # ── Eq 4: House Prices ──
        # Anchored so hp -> HP_BAR at steady state when real rate = r*
        new.hp = (
            self.RHO_HP * s.hp
            + (1.0 - self.RHO_HP) * self.HP_BAR
            + self.ETA_R * (self.R_STAR - (new.i - new.pi))
            + self.ETA_QE * qe
            + self.ETA_Y * new.y
        )
        new.hp = np.clip(new.hp, -20.0, 30.0)

        # ── Eq 6: Wage Growth ──
        new.w = (
            self.RHO_W * s.w
            + (1.0 - self.RHO_W) * (new.pi + self.PROD_GROWTH)
            + self.MU_U * (self.U_STAR - new.u)
        )

        # ── Eq 7: Consumer Confidence ──
        # Deviations from target/steady state affect confidence
        # At steady state (pi=2, u=u*, y=0): conf -> 0
        pi_deviation = abs(new.pi - self.PI_STAR)
        new.conf = (
            self.RHO_CONF * s.conf
            + self.CHI_Y * new.y
            + self.CHI_U * (self.U_STAR - new.u)
            - self.CHI_PI * pi_deviation
            + shocks.eps_conf
        )
        new.conf = np.clip(new.conf, -50.0, 50.0)

        # ── Eq 8: Gini Coefficient ──
        new.gini = (
            s.gini
            + self.THETA_U * (new.u - self.U_STAR) / 100.0
            + self.THETA_HP * (new.hp - self.HP_BAR) / 1000.0
            + self.THETA_QE * qe / 100.0
        )
        new.gini = np.clip(new.gini, 0.25, 0.50)

        # ── Eq 9: Long-term Rate ──
        new.r_long = (
            self.ALPHA_LONG * s.r_long
            + (1.0 - self.ALPHA_LONG) * (new.i + self.TERM_PREMIUM)
            - self.ZETA_QE * new.cum_qe
        )

        return new

    def taylor_rule(self, state: EconomyState) -> float:
        """
        Compute Taylor Rule prescribed Bank Rate.

        i_taylor = rho * i_{t-1} + (1-rho) * (r* + pi* + a_pi*(pi-pi*) + a_y*y)

        Nelson (2000), BoE WP; Clarida, Gali, Gertler (1998).
        """
        target_rate = (
            self.R_STAR + self.PI_STAR
            + self.ALPHA_TAYLOR_PI * (state.pi - self.PI_STAR)
            + self.ALPHA_TAYLOR_Y * state.y
        )
        smoothed = (
            self.RHO_TAYLOR * state.i
            + (1.0 - self.RHO_TAYLOR) * target_rate
        )
        return np.clip(smoothed, self.I_MIN, self.I_MAX)

    def compute_loss(
        self,
        state: EconomyState,
        prev_rate: float,
    ) -> float:
        """
        Central bank loss function for a single quarter.

        L = w_pi*(pi-2)^2 + w_y*y^2 + w_u*(u-u*)^2 + w_di*(i-i_prev)^2 + w_gini*(gini-0.34)^2

        Based on Debortoli et al. (2019), Svensson (1997), Rudebusch & Svensson (1999),
        Acharya, Challe & Dogra (2023).
        """
        loss = (
            self.W_PI * (state.pi - self.PI_STAR) ** 2
            + self.W_Y * state.y ** 2
            + self.W_U * (state.u - self.U_STAR) ** 2
            + self.W_DI * (state.i - prev_rate) ** 2
            + self.W_GINI * (state.gini - self.GINI_BAR) ** 2
        )
        return loss


# ════════════════════════════════════════════════════════════════
# Scenario Definitions
# ════════════════════════════════════════════════════════════════

def _pad_shocks(shocks: List[QuarterShocks], total: int = 20) -> List[QuarterShocks]:
    """Pad shock sequence to 20 quarters with zero shocks."""
    while len(shocks) < total:
        shocks.append(QuarterShocks())
    return shocks[:total]


def _make_supply_shock() -> ScenarioDefinition:
    """
    2021-2023 UK Energy Crisis.

    CPI peaked at 11.1% (Oct 2022). Bank Rate rose from 0.1% to 5.25%.
    GfK consumer confidence hit -49 (all-time record).
    """
    initial = EconomyState(
        i=0.50, pi=2.0, y=0.0, u=4.5, hp=5.0, er=100.0,
        w=3.0, conf=0.0, gini=0.34, r_long=1.0, cum_qe=0.0,
    )
    shocks = [
        QuarterShocks(eps_supply=1.5, eps_demand=0.0, eps_conf=-5.0),   # Q1: shock begins
        QuarterShocks(eps_supply=2.5, eps_demand=-0.3, eps_conf=-10.0), # Q2: escalating
        QuarterShocks(eps_supply=3.0, eps_demand=-0.5, eps_conf=-15.0), # Q3: peak
        QuarterShocks(eps_supply=2.5, eps_demand=-0.3, eps_conf=-12.0), # Q4: still severe
        QuarterShocks(eps_supply=2.0, eps_demand=-0.2, eps_conf=-8.0),  # Q5: easing
        QuarterShocks(eps_supply=1.5, eps_demand=-0.1, eps_conf=-5.0),  # Q6: fading
        QuarterShocks(eps_supply=1.0, eps_demand=0.0, eps_conf=-3.0),   # Q7: tail
        QuarterShocks(eps_supply=0.5, eps_demand=0.0, eps_conf=-1.0),   # Q8: near end
    ]
    return ScenarioDefinition(
        name="supply_shock",
        description=(
            "Energy price crisis (modelled on 2021-2023 UK experience). "
            "A sustained supply shock drives cost-push inflation while dampening demand. "
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


def _make_demand_shock() -> ScenarioDefinition:
    """
    COVID-19 UK (2020).

    GDP fell -18.8% in Q2 2020. Unemployment peaked ~5.3%.
    Bank of England deployed £450bn QE (~19% of GDP).
    Bank Rate cut from 0.75% to 0.10% in 8 days.
    """
    initial = EconomyState(
        i=0.75, pi=1.8, y=0.0, u=3.9, hp=2.0, er=100.0,
        w=3.5, conf=0.0, gini=0.34, r_long=1.2, cum_qe=0.0,
    )
    shocks = [
        QuarterShocks(eps_demand=-6.0, eps_conf=-30.0, risk_premium=1.5),  # Q1: lockdown
        QuarterShocks(eps_demand=-4.0, eps_conf=-20.0, risk_premium=0.8),  # Q2: continued
        QuarterShocks(eps_demand=3.0, eps_conf=10.0, risk_premium=0.2),    # Q3: reopening
        QuarterShocks(eps_demand=1.5, eps_conf=5.0),                       # Q4: recovery
        QuarterShocks(eps_demand=0.5, eps_conf=2.0),                       # Q5: normalizing
    ]
    return ScenarioDefinition(
        name="demand_shock",
        description=(
            "Pandemic-style demand collapse (modelled on COVID-19 UK, 2020). "
            "A sudden, severe demand shock with rapid partial recovery. "
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


def _make_financial_crisis() -> ScenarioDefinition:
    """
    2007-2009 Global Financial Crisis (UK).

    GDP contracted ~6.3% peak-to-trough. House prices fell ~20%.
    Sterling depreciated ~25% trade-weighted.
    Bank Rate cut from 5.75% to 0.50%. £200bn QE deployed.
    """
    initial = EconomyState(
        i=5.75, pi=2.5, y=1.0, u=5.0, hp=8.0, er=105.0,
        w=4.0, conf=5.0, gini=0.35, r_long=5.5, cum_qe=0.0,
    )
    shocks = [
        QuarterShocks(eps_demand=-1.5, eps_conf=-10.0, risk_premium=1.5),  # Q1: credit crunch
        QuarterShocks(eps_demand=-2.5, eps_conf=-15.0, risk_premium=2.5),  # Q2: deepening
        QuarterShocks(eps_demand=-3.0, eps_conf=-20.0, risk_premium=3.0),  # Q3: peak stress
        QuarterShocks(eps_demand=-2.5, eps_conf=-18.0, risk_premium=2.5),  # Q4: Lehman
        QuarterShocks(eps_demand=-2.0, eps_conf=-15.0, risk_premium=2.0),  # Q5: continued
        QuarterShocks(eps_demand=-1.5, eps_conf=-10.0, risk_premium=1.5),  # Q6: stabilizing
        QuarterShocks(eps_demand=-1.0, eps_conf=-5.0, risk_premium=1.0),   # Q7: slow recovery
        QuarterShocks(eps_demand=-0.5, eps_conf=-3.0, risk_premium=0.5),   # Q8: tail
    ]
    return ScenarioDefinition(
        name="financial_crisis",
        description=(
            "Financial crisis (modelled on 2007-2009 GFC in the UK). "
            "A credit crunch collapses demand, house prices, and confidence. "
            "Sterling depreciates sharply."
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


def _make_overheating() -> ScenarioDefinition:
    """
    Economy running hot -- inflation above target, low unemployment,
    rapid house price growth. No exogenous shocks; the challenge is
    to cool the economy without causing a recession.
    """
    initial = EconomyState(
        i=3.0, pi=3.5, y=2.0, u=3.5, hp=10.0, er=100.0,
        w=5.0, conf=10.0, gini=0.36, r_long=4.0, cum_qe=0.0,
    )
    # No exogenous shocks -- the economy is already overheating
    shocks: List[QuarterShocks] = []
    return ScenarioDefinition(
        name="overheating",
        description=(
            "Overheating economy with inflation above target, tight labour market, "
            "and rapid house price growth. No external shocks -- the challenge is to "
            "tighten policy gradually to bring inflation back to the 2% target without "
            "triggering a recession."
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


def _make_stagflation() -> ScenarioDefinition:
    """
    Stagflation: simultaneous supply and demand shocks.
    Modelled loosely on the 1970s UK experience.

    CPI peaked at 22.6% (1975). MLR peaked at 17% (1979).
    The classic central banker's dilemma.
    """
    initial = EconomyState(
        i=3.0, pi=2.0, y=0.0, u=4.25, hp=3.0, er=100.0,
        w=3.0, conf=0.0, gini=0.34, r_long=3.5, cum_qe=0.0,
    )
    shocks = [
        QuarterShocks(eps_supply=2.0, eps_demand=-2.0, eps_conf=-15.0, risk_premium=0.5),
        QuarterShocks(eps_supply=2.5, eps_demand=-2.5, eps_conf=-20.0, risk_premium=0.5),
        QuarterShocks(eps_supply=2.5, eps_demand=-2.0, eps_conf=-18.0, risk_premium=0.3),
        QuarterShocks(eps_supply=2.0, eps_demand=-1.5, eps_conf=-12.0, risk_premium=0.2),
        QuarterShocks(eps_supply=1.5, eps_demand=-0.5, eps_conf=-8.0),
        QuarterShocks(eps_supply=1.0, eps_demand=0.0, eps_conf=-5.0),
        QuarterShocks(eps_supply=0.5, eps_demand=0.0, eps_conf=-2.0),
    ]
    return ScenarioDefinition(
        name="stagflation",
        description=(
            "Stagflation: simultaneous cost-push inflation and demand weakness "
            "(inspired by 1970s UK). Rising inflation and falling output create "
            "the classic central banker's dilemma -- rate hikes fight inflation "
            "but deepen the recession."
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


def _make_global_tightening() -> ScenarioDefinition:
    """
    Global tightening: foreign central banks raise rates sharply.
    Modelled on 2022-23 when Fed hiked +525bp and ECB +450bp.
    GBP/USD fell from $1.35 to $1.03 at the trough.
    """
    initial = EconomyState(
        i=3.0, pi=2.0, y=0.0, u=4.25, hp=3.0, er=100.0,
        w=3.0, conf=0.0, gini=0.34, r_long=3.5, cum_qe=0.0,
    )
    shocks = [
        QuarterShocks(eps_conf=-3.0, risk_premium=0.3, i_foreign=4.0),
        QuarterShocks(eps_conf=-5.0, risk_premium=0.5, i_foreign=4.5),
        QuarterShocks(eps_demand=-0.5, eps_conf=-5.0, risk_premium=0.5, i_foreign=5.0),
        QuarterShocks(eps_demand=-0.5, eps_conf=-5.0, risk_premium=0.3, i_foreign=5.5),
        QuarterShocks(eps_demand=-0.3, eps_conf=-3.0, i_foreign=5.5),
        QuarterShocks(eps_conf=-2.0, i_foreign=5.5),
        QuarterShocks(i_foreign=5.0),
        QuarterShocks(i_foreign=4.5),
        QuarterShocks(i_foreign=4.0),
    ]
    return ScenarioDefinition(
        name="global_tightening",
        description=(
            "Global monetary tightening (modelled on 2022-23 Fed/ECB hikes). "
            "Foreign central banks raise rates sharply, causing sterling to depreciate "
            "and importing inflation via the exchange rate channel."
        ),
        initial_conditions=initial,
        shocks=_pad_shocks(shocks),
    )


# ── Scenario Registry ──

SCENARIOS: Dict[str, ScenarioDefinition] = {
    "supply_shock": _make_supply_shock(),
    "demand_shock": _make_demand_shock(),
    "financial_crisis": _make_financial_crisis(),
    "overheating": _make_overheating(),
    "stagflation": _make_stagflation(),
    "global_tightening": _make_global_tightening(),
}

TRAIN_SCENARIOS = ["supply_shock", "demand_shock", "financial_crisis", "overheating"]
TEST_SCENARIOS = ["stagflation", "global_tightening"]
