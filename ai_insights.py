"""
AI / analytics features:
- Anomaly detection (statistical, no external AI needed)
- Idle & over-provisioned resource detection (via Azure Advisor, with demo fallback)
- Reserved Instance recommendations (via Azure Advisor, with demo fallback)
- Spend forecasting (simple trend projection)
- Executive summary (optional: uses Claude via Anthropic API if a key is provided)
"""
import os
import numpy as np
import pandas as pd
from modules.auth import get_credential, get_subscription_ids, is_configured

try:
    from azure.mgmt.advisor import AdvisorManagementClient
except ImportError:
    AdvisorManagementClient = None


def detect_anomalies(daily_df, z_threshold=2.5):
    """
    Flags days where cost deviates more than z_threshold standard deviations
    from the trailing 14-day average. Simple, explainable, no external AI needed.
    """
    df = daily_df.copy().sort_values("date").reset_index(drop=True)
    df["rolling_mean"] = df["cost"].rolling(window=14, min_periods=5).mean()
    df["rolling_std"] = df["cost"].rolling(window=14, min_periods=5).std()
    df["z_score"] = (df["cost"] - df["rolling_mean"]) / df["rolling_std"].replace(0, np.nan)
    anomalies = df[df["z_score"].abs() > z_threshold].copy()
    anomalies["deviation_pct"] = ((anomalies["cost"] - anomalies["rolling_mean"])
                                  / anomalies["rolling_mean"] * 100).round(1)
    return anomalies[["date", "cost", "rolling_mean", "deviation_pct"]]


def get_idle_and_oversized_resources():
    """
    Pulls Azure Advisor cost recommendations (idle VMs, unattached disks,
    over-provisioned VMs). Falls back to realistic sample recommendations
    in demo mode.
    """
    if not is_configured() or AdvisorManagementClient is None:
        return _sample_advisor_recommendations()

    credential = get_credential()
    sub_ids = get_subscription_ids()
    recs = []
    for sub_id in sub_ids:
        try:
            client = AdvisorManagementClient(credential, sub_id)
            for rec in client.recommendations.list(filter="Category eq 'Cost'"):
                recs.append({
                    "subscription": sub_id,
                    "resource": getattr(rec.impacted_value, "resource_name", rec.impacted_value) if hasattr(rec, "impacted_value") else "Unknown",
                    "recommendation": rec.short_description.problem if rec.short_description else "N/A",
                    "action": rec.short_description.solution if rec.short_description else "N/A",
                    "potential_savings": _extract_savings(rec),
                })
        except Exception:
            continue
    return pd.DataFrame(recs) if recs else _sample_advisor_recommendations()


def _extract_savings(rec):
    try:
        return rec.extended_properties.get("savingsAmount", "N/A")
    except Exception:
        return "N/A"


def _sample_advisor_recommendations():
    return pd.DataFrame([
        {"subscription": "Demo Subscription 1", "resource": "vm-analytics-dev-03",
         "recommendation": "VM idle for 14+ days (CPU < 5%)", "action": "Deallocate or resize to B-series",
         "potential_savings": "Rs 17,500/month"},
        {"subscription": "Demo Subscription 1", "resource": "disk-unattached-old-backup",
         "recommendation": "Unattached managed disk", "action": "Delete or archive to cold storage",
         "potential_savings": "Rs 3,750/month"},
        {"subscription": "Demo Subscription 1", "resource": "vm-web-prod-02",
         "recommendation": "Over-provisioned (avg CPU 8%, D8s_v5 size)", "action": "Downsize to D2s_v5",
         "potential_savings": "Rs 25,800/month"},
        {"subscription": "Demo Subscription 1", "resource": "sql-db-staging",
         "recommendation": "Reserved Instance opportunity (steady 24/7 usage for 90+ days)",
         "action": "Purchase 1-year Reserved Instance", "potential_savings": "Rs 45,000/year"},
    ])


def forecast_next_month(monthly_df, months_ahead=1):
    """
    Simple linear trend forecast on monthly totals. Good enough for a
    beginner-friendly dashboard; can be swapped for Prophet/ARIMA later.
    """
    df = monthly_df.copy().reset_index(drop=True)
    if len(df) < 3:
        return None  # not enough history yet

    df["period_index"] = range(len(df))
    coeffs = np.polyfit(df["period_index"], df["cost"], 1)
    slope, intercept = coeffs[0], coeffs[1]

    next_index = len(df) + months_ahead - 1
    forecast_value = slope * next_index + intercept
    return max(forecast_value, 0)


def generate_executive_summary(total_cost, top_services, anomalies_count, savings_opportunities):
    """
    Generates a plain-English executive summary. Uses Claude via the Anthropic
    API if ANTHROPIC_API_KEY is set in .env; otherwise builds a simple
    templated summary so the feature still works out of the box.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                f"Write a concise 4-5 sentence executive summary for a cloud cost "
                f"report. Total spend: Rs {total_cost:,.2f}. Top services by cost: "
                f"{', '.join(top_services)}. Number of cost anomalies detected: "
                f"{anomalies_count}. Potential savings identified: {savings_opportunities}. "
                f"Write it for a non-technical manager, plain language, action-oriented."
            )
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            return _template_summary(total_cost, top_services, anomalies_count, savings_opportunities) + \
                   f"\n\n(Note: AI summary generation failed, showing template summary instead: {e})"

    return _template_summary(total_cost, top_services, anomalies_count, savings_opportunities)


def build_data_context(filtered_df, anomalies_df, advisor_df, forecast_value):
    """
    Builds a compact, token-efficient text summary of the current filtered
    dashboard data. This is passed to Claude as context for the Q&A chatbot
    instead of the raw dataframe (which could be large and slow/expensive).
    """
    total_cost = filtered_df["cost"].sum()
    date_min = pd.to_datetime(filtered_df["date"]).min().date()
    date_max = pd.to_datetime(filtered_df["date"]).max().date()

    by_service = filtered_df.groupby("service")["cost"].sum().sort_values(ascending=False)
    by_env = filtered_df.groupby("environment")["cost"].sum().sort_values(ascending=False)
    by_rg = filtered_df.groupby("resource_group")["cost"].sum().sort_values(ascending=False)
    by_month = pd.to_datetime(filtered_df["date"]).dt.to_period("M")
    monthly_totals = filtered_df.groupby(by_month)["cost"].sum()

    lines = [
        f"Date range: {date_min} to {date_max}",
        f"Total cost (all filters applied): Rs {total_cost:,.2f}",
        "",
        "Cost by service:",
        *[f"  - {svc}: Rs {amt:,.2f}" for svc, amt in by_service.items()],
        "",
        "Cost by environment:",
        *[f"  - {env}: Rs {amt:,.2f}" for env, amt in by_env.items()],
        "",
        "Cost by resource group:",
        *[f"  - {rg}: Rs {amt:,.2f}" for rg, amt in by_rg.items()],
        "",
        "Monthly totals:",
        *[f"  - {month}: Rs {amt:,.2f}" for month, amt in monthly_totals.items()],
        "",
    ]

    if not anomalies_df.empty:
        lines.append("Detected cost anomalies (unusual spend days):")
        for _, row in anomalies_df.iterrows():
            lines.append(
                f"  - {row['date'].date() if hasattr(row['date'], 'date') else row['date']}: "
                f"Rs {row['cost']:,.2f} ({row['deviation_pct']:+.1f}% vs trailing average)"
            )
        lines.append("")
    else:
        lines.append("No cost anomalies detected in this range.\n")

    if not advisor_df.empty:
        lines.append("Cost optimization recommendations (from Azure Advisor):")
        for _, row in advisor_df.iterrows():
            lines.append(
                f"  - Resource: {row['resource']} | Issue: {row['recommendation']} | "
                f"Suggested action: {row['action']} | Potential savings: {row['potential_savings']}"
            )
        lines.append("")

    if forecast_value is not None:
        lines.append(f"Forecasted next month's spend: Rs {forecast_value:,.2f}")

    return "\n".join(lines)


def answer_question_free(question, filtered_df, anomalies_df, advisor_df, forecast_value):
    """
    Answers common cost questions using pure pandas/statistics - no external
    API, no cost, works instantly. Less flexible than the Claude-powered
    chat_with_data(), but covers the most common questions people ask.
    Matches keywords in the question and returns a computed answer.
    """
    q = question.lower().strip()

    by_service = filtered_df.groupby("service")["cost"].sum().sort_values(ascending=False)
    by_env = filtered_df.groupby("environment")["cost"].sum().sort_values(ascending=False)
    by_rg = filtered_df.groupby("resource_group")["cost"].sum().sort_values(ascending=False)
    total_cost = filtered_df["cost"].sum()

    by_month = pd.to_datetime(filtered_df["date"]).dt.to_period("M")
    monthly_totals = filtered_df.groupby(by_month)["cost"].sum().sort_index()

    # --- Total cost ---
    if any(kw in q for kw in ["total cost", "total spend", "how much", "overall cost"]):
        return f"Total cost for the currently filtered data is **Rs {total_cost:,.2f}**."

    # --- Most/least expensive service ---
    if "service" in q and any(kw in q for kw in ["most", "highest", "expensive", "top"]):
        top = by_service.index[0]
        return (
            f"**{top}** is the most expensive service, costing **Rs {by_service.iloc[0]:,.2f}** "
            f"({by_service.iloc[0] / total_cost * 100:.1f}% of total). "
            f"Next highest: {by_service.index[1]} at Rs {by_service.iloc[1]:,.2f}."
        )
    if "service" in q and any(kw in q for kw in ["least", "lowest", "cheapest", "smallest"]):
        bottom = by_service.index[-1]
        return f"**{bottom}** is the cheapest service, costing **Rs {by_service.iloc[-1]:,.2f}**."

    # --- Environment breakdown ---
    if "environment" in q or "prod" in q or "dev" in q:
        lines = [f"- {env}: Rs {amt:,.2f} ({amt/total_cost*100:.1f}%)" for env, amt in by_env.items()]
        return "Cost by environment:\n" + "\n".join(lines)

    # --- Resource group breakdown ---
    if "resource group" in q:
        lines = [f"- {rg}: Rs {amt:,.2f} ({amt/total_cost*100:.1f}%)" for rg, amt in by_rg.items()]
        return "Cost by resource group:\n" + "\n".join(lines)

    # --- Why did cost increase / spike / anomalies ---
    if any(kw in q for kw in ["spike", "increase", "increased", "jump", "why", "anomal", "unusual"]):
        if anomalies_df.empty:
            return "No unusual cost spikes were detected in the currently filtered date range."
        lines = []
        for _, row in anomalies_df.iterrows():
            d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            lines.append(f"- {d}: cost was Rs {row['cost']:,.2f}, {row['deviation_pct']:+.1f}% vs the trailing 14-day average")
        return "Here are the detected cost anomalies:\n" + "\n".join(lines) + \
               "\n\nCheck the AI Insights tab for related idle/over-provisioned resources that may explain these."

    # --- Trend: going up or down ---
    if any(kw in q for kw in ["trend", "going up", "going down", "increasing", "decreasing"]):
        if len(monthly_totals) < 2:
            return "Not enough monthly data yet to determine a trend."
        change = monthly_totals.iloc[-1] - monthly_totals.iloc[-2]
        pct = (change / monthly_totals.iloc[-2] * 100) if monthly_totals.iloc[-2] else 0
        direction = "increased" if change > 0 else "decreased"
        return (
            f"Cost {direction} by Rs {abs(change):,.2f} ({pct:+.1f}%) from "
            f"{monthly_totals.index[-2]} (Rs {monthly_totals.iloc[-2]:,.2f}) to "
            f"{monthly_totals.index[-1]} (Rs {monthly_totals.iloc[-1]:,.2f})."
        )

    # --- Forecast / next month ---
    if any(kw in q for kw in ["forecast", "next month", "predict", "projected"]):
        if forecast_value is None:
            return "Not enough monthly history yet to forecast (need at least 3 months of data)."
        return f"Forecasted spend for next month is **Rs {forecast_value:,.2f}**, based on the recent trend."

    # --- Savings / recommendations / idle / RI ---
    if any(kw in q for kw in ["save", "saving", "cut", "reduce", "recommend", "idle", "unused", "reserved instance", "optimi"]):
        if advisor_df.empty:
            return "No cost optimization recommendations found for the current filters."
        lines = [
            f"- {row['resource']}: {row['recommendation']} -> {row['action']} (potential savings: {row['potential_savings']})"
            for _, row in advisor_df.iterrows()
        ]
        return "Here's what you can act on to save money:\n" + "\n".join(lines)

    # --- Fallback: didn't match anything ---
    return (
        "I couldn't match that to a question I know how to answer with the free (no-API) mode. "
        "Try asking things like:\n"
        "- \"What's the total cost?\"\n"
        "- \"Which service costs the most?\"\n"
        "- \"Why did cost spike?\"\n"
        "- \"What's the forecast for next month?\"\n"
        "- \"How can I save money?\"\n"
        "- \"Cost by environment\" or \"Cost by resource group\"\n\n"
        "For open-ended, free-form questions, add an `ANTHROPIC_API_KEY` to your `.env` "
        "to unlock the smarter AI chat mode."
    )


def chat_with_data(question, data_context, chat_history=None):
    """
    Answers a natural-language question about the cost data using Claude.
    chat_history: list of {"role": "user"/"assistant", "content": str} from
    previous turns in this session, so follow-up questions work naturally.
    Requires ANTHROPIC_API_KEY in .env - returns a clear message if missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return (
            "This feature needs an Anthropic API key. Get one at "
            "https://console.anthropic.com/ and add it to your `.env` file as "
            "`ANTHROPIC_API_KEY=your-key-here`, then restart the dashboard."
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = (
            "You are a cloud cost analyst assistant embedded in an Azure cost "
            "dashboard. Answer questions using ONLY the data summary provided below. "
            "Be concise, specific, and use exact numbers from the data. If the data "
            "doesn't contain what's needed to answer, say so clearly instead of guessing.\n\n"
            f"CURRENT DASHBOARD DATA:\n{data_context}"
        )

        messages = list(chat_history) if chat_history else []
        messages.append({"role": "user", "content": question})

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    except Exception as e:
        return f"Sorry, something went wrong answering that: {e}"


def _template_summary(total_cost, top_services, anomalies_count, savings_opportunities):
    services_text = ", ".join(top_services[:3]) if top_services else "various services"
    return (
        f"Total Azure spend for the selected period was Rs {total_cost:,.2f}, driven mainly by "
        f"{services_text}. {anomalies_count} unusual spending day(s) were detected and should be "
        f"reviewed. Cost optimization analysis identified {savings_opportunities} in potential "
        f"monthly/annual savings through resizing, deallocating idle resources, and Reserved "
        f"Instance purchases. Recommend reviewing the AI Insights tab for specific action items "
        f"and assigning owners for each recommendation this week."
    )
