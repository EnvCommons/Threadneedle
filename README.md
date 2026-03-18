# Threadneedle

[![OpenReward Environment](https://img.shields.io/badge/%E2%AD%90%20OpenReward-Environment-f7e6cc)](https://openreward.ai/GeneralReasoning/Threadneedle)

## Description

Threadneedle is a monetary policy environment where an AI agent plays the role of the Bank of England's Monetary Policy Committee (MPC), setting Bank Rate and quantitative easing (QE) each quarter over 20 quarters. The economy evolves according to a macro model calibrated to UK empirical evidence. The underlying economic structure is not revealed to the agent -- it must be discovered through experimentation, research, and modelling.

Agents have access to web search for researching monetary policy literature and a compute sandbox for building quantitative models to inform their decisions.

Named after Threadneedle Street, London - the historic home of the Bank of England.

## Capabilities

- Setting monetary policy (Bank Rate + QE) in response to macroeconomic conditions
- Researching monetary policy theory, central bank strategy, and macroeconomic literature via web search
- Building quantitative economic models in a compute sandbox to inform policy decisions
- Managing inflation-output trade-offs under a dual mandate
- Responding to supply shocks, demand shocks, financial crises, and global tightening
- Optimizing a multi-objective loss function (inflation, output, unemployment, rate smoothing, inequality)

## Compute Requirements

Agents in Threadneedle are given a sandbox with a Python data science environment.

## Tasks

There are four training tasks and two test tasks, each representing a distinct macroeconomic scenario calibrated to UK historical episodes:

### Train

- **Supply Shock**: Energy price crisis modelled on the 2021-2023 UK experience (CPI peaked at 11.1%).
- **Demand Shock**: Pandemic-style demand collapse modelled on COVID-19 UK (GDP fell -18.8% in Q2 2020).
- **Financial Crisis**: Credit crunch modelled on the 2007-2009 GFC (GDP -6.3%, house prices -20%, sterling -25%).
- **Overheating**: Economy running hot with inflation above target, tight labour market, and rapid house price growth.

### Test

- **Stagflation**: Simultaneous supply and demand shocks, inspired by the 1970s UK experience.
- **Global Tightening**: Foreign central banks raise rates sharply, modelled on the 2022-23 Fed/ECB hike cycle.

Each task runs for 20 quarters (5 years).

## Reward Structure

This is a dense, verifiable reward environment. Rewards are computed each quarter as the difference between the Taylor Rule baseline's loss and the agent's loss:

$$ R_t = L^{Taylor}_t - L^{Agent}_t $$

Positive reward means the agent outperformed the Taylor Rule.

No LLM graders are used.

## Data

No external data files are required. The economic model and all scenarios are defined in code with parameters calibrated to UK empirical evidence. See `CITATIONS.md` for full justification of every parameter with academic references.

## Tools

Agents have access to three categories of tools:

### Policy Tools (3)
1. **`set_policy(bank_rate, qe)`** -- Set Bank Rate (0.1-15.0%) and QE flow (-5.0 to +5.0% GDP) for the current quarter. This is the main action tool; each call advances the economy by one quarter and returns the new economic state, Taylor Rule baseline comparison, and reward.
2. **`view_economy()`** -- View the current macroeconomic state and scenario description.
3. **`view_history()`** -- View all past quarters' policy decisions and economic outcomes.

### Research Tools (2)
4. **`web_search(query)`** -- Search the web for monetary policy research, macroeconomic theory, and central bank publications.
5. **`fetch_url(url, page)`** -- Fetch content from a URL with pagination support.

### CLI Tools (9)
6. **`bash(command)`** -- Execute shell commands in the compute sandbox.
7. **`read(file_path)`**, **`write(file_path, content)`**, **`edit(file_path, ...)`**, **`multi_edit(file_path, ...)`** -- File management tools.
8. **`glob(pattern)`**, **`grep(pattern)`**, **`ls(path)`** -- File search tools.
9. **`todo_write(todos)`** -- Task tracking.

## Time Horizon

Each task runs for 20 quarters. The agent can research and build models between policy decisions, making this an open-ended environment where the number of tool calls depends on the agent's strategy.

## Environment Difficulty

The environment requires:
- Understanding macroeconomic relationships and monetary policy transmission
- Discovering how different economic variables respond to policy changes
- Managing policy trade-offs (inflation vs output, short-run vs long-run)
- Using multiple instruments (Bank Rate + QE) with different transmission channels

The Taylor Rule baseline provides a competitive benchmark. The underlying economic structure includes heterogeneous household responses that are not directly revealed to the agent, making research and experimentation valuable.

## Other Environment Requirements

Threadneedle requires a `tavily_api_key` secret for web search and URL fetching capabilities.

## Safety

Threadneedle simulates monetary policy decisions in a stylized macroeconomic model. Agents interact only with the model through setting interest rates and QE -- there are no real-world consequences. The environment does not involve interaction with other agents, real financial markets, or actual policy implementation.

## Citations

```bibtex
@dataset{GRThreadneedle,
  author    = {General Reasoning Inc. Team},
  title     = {Threadneedle},
  year      = {2026},
  publisher = {OpenReward},
  url       = {https://openreward.ai/GeneralReasoning/Threadneedle}
}
```
