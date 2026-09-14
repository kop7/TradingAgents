"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.
"""

from datetime import datetime
from pathlib import Path


def render_reports(final_state: dict, ticker: str) -> dict[str, str]:
    """Render all available Markdown sections without depending on filesystem access."""
    save_path = Path(".")
    reports = {}
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):

        reports[str(analysts_dir / "market.md")] = final_state["market_report"]
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):

        reports[str(analysts_dir / "sentiment.md")] = final_state["sentiment_report"]
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):

        reports[str(analysts_dir / "news.md")] = final_state["news_report"]
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):

        reports[str(analysts_dir / "fundamentals.md")] = final_state["fundamentals_report"]
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):

            reports[str(research_dir / "bull.md")] = debate["bull_history"]
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):

            reports[str(research_dir / "bear.md")] = debate["bear_history"]
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):

            reports[str(research_dir / "manager.md")] = debate["judge_decision"]
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"

        reports[str(trading_dir / "trader.md")] = final_state["trader_investment_plan"]
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state") or final_state.get("final_trade_decision"):
        risk_dir = save_path / "4_risk"
        risk = final_state.get("risk_debate_state") or {}
        risk_parts = []
        if risk.get("aggressive_history"):

            reports[str(risk_dir / "aggressive.md")] = risk["aggressive_history"]
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):

            reports[str(risk_dir / "conservative.md")] = risk["conservative_history"]
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):

            reports[str(risk_dir / "neutral.md")] = risk["neutral_history"]
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if final_state.get("final_trade_decision") or risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"

            decision = final_state.get("final_trade_decision") or risk["judge_decision"]
            reports[str(portfolio_dir / "decision.md")] = decision
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{decision}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    reports["complete_report.md"] = header + "\n\n".join(sections)
    return reports


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Write the same Markdown bundle used by database persistence."""
    save_path = Path(save_path)
    for relative, content in render_reports(final_state, ticker).items():
        target = save_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return save_path / "complete_report.md"
