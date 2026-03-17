"""
Threadneedle: Bank of England Central Bank Environment.

An AI agent plays the role of the Bank of England's Monetary Policy Committee,
setting Bank Rate and QE each quarter over 20 quarters. The economy evolves
according to a macro model calibrated to UK empirical evidence.

The agent has access to a sandbox for building economic models, and web
search/fetch for researching monetary policy literature. The underlying
economic structure is NOT revealed -- the agent must discover it through
experimentation and research.

Named after Threadneedle Street, London -- the historic home of the Bank of England.
"""

from typing import Dict, List, Any
from copy import deepcopy
from pydantic import BaseModel, Field

from cli_environment import CLIEnvironment
from openreward.environments import JSONObject, ToolOutput, tool, TextBlock
from openreward import AsyncOpenReward, SandboxSettings
from tavily import AsyncTavilyClient

from hank_model import (
    HANKModel,
    EconomyState,
    QuarterShocks,
    SCENARIOS,
    TRAIN_SCENARIOS,
    TEST_SCENARIOS,
)


class TaskSpec(BaseModel):
    id: str


class SetPolicyInput(BaseModel, extra="forbid"):
    """Set monetary policy for the current quarter."""
    bank_rate: float   # Bank Rate in %, must be in [0.1, 15.0]
    qe: float = 0.0   # QE flow as % of GDP, in [-5.0, 5.0] (negative = QT)


class ViewEconomyInput(BaseModel, extra="forbid"):
    """View the current state of the economy."""
    pass


class ViewHistoryInput(BaseModel, extra="forbid"):
    """View the full history of economic outcomes and policy decisions."""
    pass


class WebSearchInput(BaseModel, extra="forbid"):
    """Search the web for information."""
    query: str = Field(..., description="Search query")


class FetchUrlInput(BaseModel, extra="forbid"):
    """Fetch content from a URL."""
    url: str = Field(..., description="URL to fetch content from")
    page: int = Field(default=1, description="Page number (1-indexed). Each page ~10,000 chars.")


TOTAL_QUARTERS = 20


class Threadneedle(CLIEnvironment):
    """
    Bank of England Monetary Policy Committee simulation.

    The agent sets Bank Rate and QE each quarter. The economy evolves
    according to a macro model calibrated to UK empirical evidence.

    The agent has access to:
    - CLI tools (bash, read, write, edit, etc.) for building models
    - Web search and fetch for researching economic literature
    - Policy tools (set_policy, view_economy, view_history)

    Performance is measured against a Taylor Rule baseline.
    """

    def __init__(self, task_spec: JSONObject, secrets: dict[str, str] = {}) -> None:
        super().__init__(task_spec, secrets=secrets)
        self.validated = TaskSpec.model_validate(task_spec)

        scenario_id = self.validated.id
        if scenario_id not in SCENARIOS:
            raise ValueError(
                f"Unknown scenario: {scenario_id}. "
                f"Available: {list(SCENARIOS.keys())}"
            )

        self.scenario = SCENARIOS[scenario_id]
        self.model = HANKModel()

        # Agent state
        self.agent_state = deepcopy(self.scenario.initial_conditions)
        self.agent_prev_rate = self.agent_state.i

        # Taylor Rule baseline (runs in parallel)
        self.taylor_state = deepcopy(self.scenario.initial_conditions)
        self.taylor_prev_rate = self.taylor_state.i

        # Tracking
        self.quarter = 0
        self.history: List[Dict[str, Any]] = []
        self.cumulative_reward = 0.0
        self.finished = False

        # Track previous foreign rate for exchange rate equation
        # Use steady-state foreign rate so the initial shock's foreign rate change is captured
        self.prev_i_foreign = self.model.I_FOREIGN_BAR

        # Sandbox setup
        api_key = secrets.get("api_key")
        if api_key:
            self.sandbox_settings = SandboxSettings(
                environment="GeneralReasoning/Threadneedle",
                image="generalreasoning/python-ds:3.12-tools",
                machine_size="0.5:1",
                block_network=False,
            )
            or_client = AsyncOpenReward(api_key=api_key)
            self.sandbox = or_client.sandbox(self.sandbox_settings)

        # Tavily client for web search
        tavily_api_key = secrets.get("tavily_api_key")
        if tavily_api_key:
            self.tavily_client = AsyncTavilyClient(api_key=tavily_api_key)
        else:
            self.tavily_client = None

    async def setup(self) -> None:
        if hasattr(self, 'sandbox') and self.sandbox is not None:
            await self.sandbox.start()

    async def teardown(self) -> None:
        if hasattr(self, 'sandbox') and self.sandbox is not None:
            await self.sandbox.stop()

    # ── Web tools ─────────────────────────────────────────────

    @tool
    async def web_search(self, params: WebSearchInput) -> ToolOutput:
        """
        Search the web for information. Useful for researching monetary policy,
        macroeconomic theory, central bank strategy, and economic modelling approaches.
        """
        if self.tavily_client is None:
            raise ValueError(
                "Tavily API key not provided. Pass 'tavily_api_key' in secrets."
            )

        try:
            response = await self.tavily_client.search(
                query=params.query,
                search_depth="basic",
                max_results=5,
            )

            results = response.get("results", [])
            if not results:
                return ToolOutput(
                    blocks=[TextBlock(text="No search results found.")],
                    metadata={"query": params.query, "results": []},
                    reward=0.0,
                    finished=False,
                )

            display_parts = [f"Search results for: {params.query}\n"]
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                snippet = result.get("content", "")
                display_parts.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")

            display_text = "\n".join(display_parts)

            return ToolOutput(
                blocks=[TextBlock(text=display_text)],
                metadata={
                    "query": params.query,
                    "results": results,
                    "count": len(results),
                },
                reward=0.0,
                finished=False,
            )
        except Exception as e:
            return ToolOutput(
                blocks=[TextBlock(text=f"Web search failed: {str(e)}")],
                metadata={"query": params.query, "error": str(e)},
                reward=0.0,
                finished=False,
            )

    @tool
    async def fetch_url(self, params: FetchUrlInput) -> ToolOutput:
        """
        Fetch and return the text content from a specific URL.
        Content is paginated -- use the page parameter to retrieve additional pages.
        """
        if self.tavily_client is None:
            raise ValueError(
                "Tavily API key not provided. Pass 'tavily_api_key' in secrets."
            )

        PAGE_SIZE = 10000

        try:
            response = await self.tavily_client.extract(urls=[params.url])

            results = response.get("results", [])
            if not results:
                return ToolOutput(
                    blocks=[TextBlock(text=f"No content extracted from {params.url}")],
                    metadata={"url": params.url, "results": []},
                    reward=0.0,
                    finished=False,
                )

            result = results[0]
            raw_content = result.get("raw_content", "")
            total_length = len(raw_content)

            total_pages = max(1, (total_length + PAGE_SIZE - 1) // PAGE_SIZE)
            page = max(1, min(params.page, total_pages))

            start_idx = (page - 1) * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_length)
            page_content = raw_content[start_idx:end_idx]

            if total_pages == 1:
                display_text = f"Content from {params.url}:\n\n{page_content}"
            else:
                display_text = f"Content from {params.url} (Page {page}/{total_pages}):\n\n{page_content}"
                if page < total_pages:
                    display_text += f"\n\n[Use fetch_url with page={page + 1} to see more content]"

            return ToolOutput(
                blocks=[TextBlock(text=display_text)],
                metadata={
                    "url": params.url,
                    "page": page,
                    "total_pages": total_pages,
                    "total_length": total_length,
                },
                reward=0.0,
                finished=False,
            )
        except Exception as e:
            return ToolOutput(
                blocks=[TextBlock(text=f"Failed to fetch URL: {str(e)}")],
                metadata={"url": params.url, "error": str(e)},
                reward=0.0,
                finished=False,
            )

    # ── Policy tools ──────────────────────────────────────────

    @tool
    async def set_policy(self, params: SetPolicyInput) -> ToolOutput:
        """
        Set monetary policy for the current quarter and advance the economy.

        Args:
            bank_rate: Bank Rate (%), must be between 0.1 and 15.0
            qe: QE flow (% of GDP), positive = purchases, negative = QT.
                Must be between -5.0 and 5.0. Default 0.0.

        Returns the new economic state, comparison with Taylor Rule baseline,
        and the reward for this quarter.
        """
        if self.finished:
            return ToolOutput(
                metadata={"error": "Episode already finished"},
                blocks=[TextBlock(text="Error: All 20 quarters already completed.")],
                finished=True,
                reward=0.0,
            )

        # Validate inputs
        bank_rate = params.bank_rate
        qe = params.qe

        if bank_rate < 0.1 or bank_rate > 15.0:
            return ToolOutput(
                metadata={"error": f"Bank Rate must be between 0.1% and 15.0%, got {bank_rate}%"},
                blocks=[TextBlock(text=f"Error: Bank Rate {bank_rate}% is out of bounds [0.1, 15.0].")],
                finished=False,
                reward=0.0,
            )

        if qe < -5.0 or qe > 5.0:
            return ToolOutput(
                metadata={"error": f"QE must be between -5.0 and 5.0 (% GDP), got {qe}"},
                blocks=[TextBlock(text=f"Error: QE {qe}% GDP is out of bounds [-5.0, 5.0].")],
                finished=False,
                reward=0.0,
            )

        # Get shocks for this quarter
        shocks = self.scenario.shocks[self.quarter]

        # Get previous foreign rate
        prev_i_foreign = self.prev_i_foreign

        # Step agent's economy
        new_agent_state = self.model.step(
            self.agent_state, bank_rate, qe, shocks, prev_i_foreign
        )

        # Step Taylor baseline
        taylor_rate = self.model.taylor_rule(self.taylor_state)
        new_taylor_state = self.model.step(
            self.taylor_state, taylor_rate, 0.0, shocks, prev_i_foreign
        )

        # Compute losses
        agent_loss = self.model.compute_loss(new_agent_state, self.agent_prev_rate)
        taylor_loss = self.model.compute_loss(new_taylor_state, self.taylor_prev_rate)

        # Reward: positive means agent outperformed Taylor Rule
        quarter_reward = taylor_loss - agent_loss
        self.cumulative_reward += quarter_reward

        # Record history
        record = {
            "quarter": self.quarter + 1,
            "agent_policy": {"bank_rate": bank_rate, "qe": qe},
            "taylor_policy": {"bank_rate": round(taylor_rate, 3), "qe": 0.0},
            "agent_state": new_agent_state.to_dict(),
            "taylor_state": new_taylor_state.to_dict(),
            "agent_loss": round(agent_loss, 4),
            "taylor_loss": round(taylor_loss, 4),
            "quarter_reward": round(quarter_reward, 4),
            "cumulative_reward": round(self.cumulative_reward, 4),
        }
        self.history.append(record)

        # Update state
        self.agent_prev_rate = bank_rate
        self.taylor_prev_rate = taylor_rate
        self.agent_state = new_agent_state
        self.taylor_state = new_taylor_state
        self.prev_i_foreign = shocks.i_foreign
        self.quarter += 1

        # Check if finished
        is_final = self.quarter >= TOTAL_QUARTERS
        if is_final:
            self.finished = True

        # Format output
        s = new_agent_state
        ts = new_taylor_state
        result = f"Quarter {self.quarter}/{TOTAL_QUARTERS} Results\n"
        result += f"{'='*50}\n\n"

        result += f"YOUR POLICY: Bank Rate = {bank_rate:.2f}%"
        if qe != 0:
            result += f", QE = {qe:+.1f}% GDP"
        result += "\n"
        result += f"TAYLOR RULE: Bank Rate = {taylor_rate:.2f}%, QE = 0.0% GDP\n\n"

        result += "ECONOMY (Your Policy):\n"
        result += f"  Inflation:       {s.pi:6.2f}%  (target: 2.00%)\n"
        result += f"  Output Gap:      {s.y:+6.2f}%\n"
        result += f"  Unemployment:    {s.u:6.2f}%  (NAIRU: 4.25%)\n"
        result += f"  House Prices:    {s.hp:+6.2f}% growth\n"
        result += f"  Exchange Rate:   {s.er:6.1f}  (100 = baseline)\n"
        result += f"  Wage Growth:     {s.w:6.2f}%\n"
        result += f"  Confidence:      {s.conf:+6.1f}\n"
        result += f"  Gini:            {s.gini:.4f}\n"
        result += f"  Long-term Rate:  {s.r_long:6.2f}%\n"
        result += f"  Cumulative QE:   {s.cum_qe:+6.1f}% GDP\n\n"

        result += "BASELINE (Taylor Rule):\n"
        result += f"  Inflation: {ts.pi:.2f}%  |  Output Gap: {ts.y:+.2f}%  |  Unemployment: {ts.u:.2f}%\n\n"

        result += f"SCORE:\n"
        result += f"  Your Loss:      {agent_loss:.4f}\n"
        result += f"  Taylor Loss:    {taylor_loss:.4f}\n"
        result += f"  Quarter Reward: {quarter_reward:+.4f}  ({'better' if quarter_reward > 0 else 'worse'} than Taylor)\n"
        result += f"  Cumulative:     {self.cumulative_reward:+.4f}\n"

        if is_final:
            result += f"\n{'='*50}\n"
            result += f"EPISODE COMPLETE\n"
            result += f"Final Cumulative Reward: {self.cumulative_reward:+.4f}\n"
            result += f"{'='*50}\n"

        return ToolOutput(
            metadata=record,
            blocks=[TextBlock(text=result)],
            reward=quarter_reward,
            finished=is_final,
        )

    @tool
    async def view_economy(self, params: ViewEconomyInput) -> ToolOutput:
        """
        View the current state of the UK economy.

        Shows all macroeconomic variables and the current scenario.
        """
        s = self.agent_state
        scenario = self.scenario

        result = f"UK Economy -- Quarter {self.quarter}/{TOTAL_QUARTERS}\n"
        result += f"Scenario: {scenario.name.replace('_', ' ').title()}\n"
        result += f"{'='*50}\n\n"

        result += "MACROECONOMIC INDICATORS:\n"
        result += f"  Bank Rate:        {s.i:6.2f}%\n"
        result += f"  CPI Inflation:    {s.pi:6.2f}%  (target: 2.00%)\n"
        result += f"  Output Gap:       {s.y:+6.2f}%\n"
        result += f"  Unemployment:     {s.u:6.2f}%  (NAIRU: 4.25%)\n"
        result += f"  House Prices:     {s.hp:+6.2f}% growth\n"
        result += f"  Exchange Rate:    {s.er:6.1f}\n"
        result += f"  Wage Growth:      {s.w:6.2f}%\n"
        result += f"  Confidence:       {s.conf:+6.1f}\n"
        result += f"  Gini Coefficient: {s.gini:.4f}\n"
        result += f"  Long-term Rate:   {s.r_long:6.2f}%\n"
        result += f"  Cumulative QE:    {s.cum_qe:+6.1f}% GDP\n\n"

        result += f"Cumulative Reward: {self.cumulative_reward:+.4f}\n"

        return ToolOutput(
            metadata=s.to_dict(),
            blocks=[TextBlock(text=result)],
            reward=0.0,
            finished=False,
        )

    @tool
    async def view_history(self, params: ViewHistoryInput) -> ToolOutput:
        """
        View the full history of policy decisions and economic outcomes.

        Shows quarter-by-quarter data for both the agent's policy
        and the Taylor Rule baseline.
        """
        if not self.history:
            return ToolOutput(
                metadata={"history": []},
                blocks=[TextBlock(text="No history yet. Set policy for the first quarter.")],
                reward=0.0,
                finished=False,
            )

        result = "POLICY HISTORY\n"
        result += f"{'='*80}\n"
        result += f"{'Q':>3} | {'Rate':>5} {'QE':>5} | {'Pi':>5} {'Y':>6} {'U':>5} {'HP':>6} | {'Taylor':>6} | {'Reward':>7}\n"
        result += f"{'-'*80}\n"

        for rec in self.history:
            ap = rec["agent_policy"]
            ast = rec["agent_state"]
            tp = rec["taylor_policy"]
            result += (
                f"{rec['quarter']:3d} | "
                f"{ap['bank_rate']:5.2f} {ap['qe']:+5.1f} | "
                f"{ast['inflation']:5.2f} {ast['output_gap']:+6.2f} {ast['unemployment']:5.2f} {ast['house_price_growth']:+6.2f} | "
                f"{tp['bank_rate']:6.2f} | "
                f"{rec['quarter_reward']:+7.4f}\n"
            )

        result += f"{'-'*80}\n"
        result += f"Cumulative Reward: {self.cumulative_reward:+.4f}\n"

        return ToolOutput(
            metadata={"history": self.history},
            blocks=[TextBlock(text=result)],
            reward=0.0,
            finished=False,
        )

    async def get_prompt(self) -> list:
        """Return the initial prompt for the agent."""
        scenario = self.scenario
        s = self.agent_state

        prompt = f"""You are the Monetary Policy Committee (MPC) of the Bank of England.

YOUR MANDATE (HM Treasury Remit):
- Primary: Maintain CPI inflation at the 2% target (symmetric)
- Secondary: Support strong, sustainable and balanced growth
- If inflation deviates by more than 1pp from target, you must explain why

SCENARIO: {scenario.name.replace('_', ' ').title()}
{scenario.description}

CURRENT ECONOMIC STATE (Quarter 0/{TOTAL_QUARTERS}):
  Bank Rate:        {s.i:.2f}%
  CPI Inflation:    {s.pi:.2f}%  (target: 2.00%)
  Output Gap:       {s.y:+.2f}%
  Unemployment:     {s.u:.2f}%  (NAIRU: 4.25%)
  House Prices:     {s.hp:+.2f}% growth
  Exchange Rate:    {s.er:.1f}  (100 = baseline)
  Wage Growth:      {s.w:.2f}%
  Confidence:       {s.conf:+.1f}
  Gini Coefficient: {s.gini:.4f}
  Long-term Rate:   {s.r_long:.2f}%

POLICY INSTRUMENTS:
1. Bank Rate: 0.1% to 15.0% (the overnight interest rate)
2. QE: -5.0 to +5.0 (% of GDP per quarter; positive = asset purchases, negative = QT)

POLICY TOOLS:
1. set_policy(bank_rate, qe) -- Set policy for the current quarter.
   This is the MAIN tool. Each call advances the economy by one quarter.
2. view_economy() -- View current economic state
3. view_history() -- View all past quarters' data

RESEARCH AND MODELLING:
You have access to web search and a compute sandbox. You are encouraged to:
- Use web_search() to research monetary policy transmission, central bank strategy,
  and macroeconomic theory relevant to the current scenario
- Use fetch_url() to read academic papers, BoE publications, and policy analysis
- Use the sandbox (bash, read, write, etc.) to build quantitative models --
  for example, implementing reaction functions, forecasting models, or
  scenario analysis tools to inform your policy decisions
- Study how different types of households respond to monetary policy
- Research how QE affects asset prices, long-term rates, and inequality

Your performance is measured against a Taylor Rule baseline each quarter.
Positive reward means you outperformed the rule-based policy.

You have {TOTAL_QUARTERS} quarters. Begin by analysing the economic situation
and researching relevant literature and strategies, then set your policy for
each quarter. You may continue researching and refining your approach between
quarters.
"""
        return [TextBlock(text=prompt)]

    @classmethod
    def list_tasks(cls, split: str) -> list[JSONObject]:
        if split == "train":
            return [{"id": s} for s in TRAIN_SCENARIOS]
        elif split == "test":
            return [{"id": s} for s in TEST_SCENARIOS]
        else:
            raise ValueError(f"Unknown split: {split}. Available: ['train', 'test']")

    @classmethod
    def list_splits(cls) -> list[str]:
        return ["train", "test"]
