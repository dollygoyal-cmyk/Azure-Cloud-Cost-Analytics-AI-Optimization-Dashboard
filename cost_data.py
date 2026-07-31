"""
Fetches cost data from the Azure Cost Management API.
Falls back to realistic sample data when Azure isn't configured yet,
so the dashboard is usable from the very first run.

NOTE: This calls the Cost Management REST API directly (via `requests`)
instead of using the azure-mgmt-costmanagement SDK. The SDK has a known
bug where it fails to deserialize certain date formats returned by the
API ("Invalid datetime string" errors), even on the latest version.
Calling the REST endpoint directly and parsing the JSON ourselves avoids
that bug completely.
"""
import datetime
import numpy as np
import pandas as pd
import requests
from modules.auth import get_credential, get_subscription_ids, is_configured


SAMPLE_SERVICES = ["Virtual Machines", "Storage", "SQL Database", "App Service",
                    "Networking", "Kubernetes Service", "Backup", "Monitor"]
SAMPLE_RESOURCE_GROUPS = ["rsg-prod-web", "rsg-prod-db", "rsg-dev-shared", "rsg-analytics"]
SAMPLE_ENVIRONMENTS = ["Production", "Development", "Staging"]

COST_MANAGEMENT_API_VERSION = "2023-11-01"


def _generate_sample_data(days=180):
    """Creates realistic-looking fake daily cost data for demo mode."""
    rng = np.random.default_rng(42)
    start = datetime.date.today() - datetime.timedelta(days=days)
    rows = []
    for i in range(days):
        day = start + datetime.timedelta(days=i)
        for svc in SAMPLE_SERVICES:
            base = {
                "Virtual Machines": 120, "Storage": 40, "SQL Database": 90,
                "App Service": 55, "Networking": 25, "Kubernetes Service": 150,
                "Backup": 15, "Monitor": 10,
            }[svc]
            noise = rng.normal(0, base * 0.12)
            # inject a couple of anomaly spikes for the AI insights demo
            spike = base * 2.5 if i in (40, 41, 120) and svc == "Virtual Machines" else 0
            cost = max(base + noise + spike, 0)
            rows.append({
                "date": day,
                "subscription": "Demo Subscription 1",
                "resource_group": rng.choice(SAMPLE_RESOURCE_GROUPS),
                "service": svc,
                "environment": rng.choice(SAMPLE_ENVIRONMENTS, p=[0.6, 0.3, 0.1]),
                "tag_costcenter": rng.choice(["CC-100", "CC-200", "CC-300"]),
                "cost": round(cost, 2),
            })
    return pd.DataFrame(rows)


def _parse_usage_date(raw_value):
    """
    The Cost Management API returns UsageDate as an integer like 20260121
    (YYYYMMDD) OR occasionally as a string date - handle both safely
    without relying on the buggy SDK deserializer.
    """
    s = str(raw_value).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.datetime.strptime(s, "%Y%m%d").date()
    return pd.to_datetime(s).date()


def _fetch_subscription_cost(sub_id, token, start, end):
    """
    Calls the Cost Management REST API directly for one subscription and
    returns a list of row dicts. Raises on HTTP errors so the caller can
    show a clear message per subscription.
    """
    url = (
        f"https://management.azure.com/subscriptions/{sub_id}"
        f"/providers/Microsoft.CostManagement/query"
        f"?api-version={COST_MANAGEMENT_API_VERSION}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": start.isoformat(), "to": end.isoformat()},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ResourceGroupName"},
                {"type": "Dimension", "name": "ServiceName"},
            ],
        },
    }

    response = requests.post(url, headers=headers, json=body, timeout=60)
    response.raise_for_status()
    data = response.json()

    columns = [c["name"] for c in data["properties"]["columns"]]
    rows = data["properties"]["rows"]

    parsed = []
    for row in rows:
        row_dict = dict(zip(columns, row))
        parsed.append({
            "date": _parse_usage_date(row_dict.get("UsageDate")),
            "subscription": sub_id,
            "resource_group": row_dict.get("ResourceGroupName", "Unknown"),
            "service": row_dict.get("ServiceName", "Unknown"),
            "environment": "Unknown",  # requires tag-based mapping, see README Phase 5 notes
            "tag_costcenter": "Unknown",
            "cost": float(row_dict.get("Cost", 0)),
        })
    return parsed


def fetch_cost_data(days=180):
    """
    Main entry point. Returns a DataFrame with columns:
    date, subscription, resource_group, service, environment, tag_costcenter, cost
    """
    if not is_configured():
        return _generate_sample_data(days), False  # False = demo mode

    credential = get_credential()
    sub_ids = get_subscription_ids()

    try:
        token = credential.get_token("https://management.azure.com/.default").token
    except Exception as e:
        import streamlit as st
        st.warning(f"Could not authenticate to Azure: {e}")
        return _generate_sample_data(days), False

    all_rows = []
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)

    for sub_id in sub_ids:
        try:
            all_rows.extend(_fetch_subscription_cost(sub_id, token, start, end))
        except requests.exceptions.HTTPError as e:
            import streamlit as st
            st.warning(f"Could not fetch data for subscription {sub_id}: {e.response.status_code} - {e.response.text[:300]}")
        except Exception as e:
            import streamlit as st
            st.warning(f"Could not fetch data for subscription {sub_id}: {e}")

    if not all_rows:
        return _generate_sample_data(days), False

    return pd.DataFrame(all_rows), True  # True = real data


def filter_by_range_option(df, option, custom_start=None, custom_end=None):
    """
    Filters a cost dataframe down to a date range based on a simple preset:
      - "Weekly"  -> current week to date (Monday -> today)
      - "Monthly" -> current calendar month to date (1st -> today)
      - "Yearly"  -> current calendar year to date (Jan 1 -> today)
      - "Custom"  -> the given custom_start / custom_end dates (inclusive)
      - anything else (e.g. "All (180 days)") -> no filtering, returns df as-is
    Used by the Cost Trends and Export Reports tabs.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    today = datetime.date.today()

    if option == "Weekly":
        start = today - datetime.timedelta(days=today.weekday())  # Monday this week
        end = today
    elif option == "Monthly":
        start = today.replace(day=1)
        end = today
    elif option == "Yearly":
        start = today.replace(month=1, day=1)
        end = today
    elif option == "Custom":
        if custom_start is None or custom_end is None:
            return df
        start, end = custom_start, custom_end
    else:
        return df

    return df[(df["date"] >= start) & (df["date"] <= end)]


def aggregate_by_period(df, period="D"):
    """
    Resamples the cost dataframe to daily/weekly/monthly/quarterly/yearly.
    period: 'D', 'W', 'M', 'Q', 'Y'
    """
    # Map to non-deprecated pandas offset aliases (M/Q/Y -> ME/QE/YE)
    period_alias_map = {"M": "ME", "Q": "QE", "Y": "YE"}
    resample_period = period_alias_map.get(period, period)

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    grouped = df.set_index("date").resample(resample_period)["cost"].sum().reset_index()
    return grouped


def get_available_periods(df, granularity):
    """
    Returns a sorted list of (label, start_date, end_date) tuples for the
    given granularity ('Day', 'Week', 'Month'), based on what data is
    actually available in df. Used to populate the comparison dropdowns.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    if granularity == "Day":
        days = sorted(df["date"].dt.date.unique(), reverse=True)
        return [(d.strftime("%d %b %Y"), d, d) for d in days]

    if granularity == "Week":
        df["period"] = df["date"].dt.to_period("W")
        periods = sorted(df["period"].unique(), reverse=True)
        result = []
        for p in periods:
            start, end = p.start_time.date(), p.end_time.date()
            label = f"{start.strftime('%d %b')} - {end.strftime('%d %b %Y')} (Week {p.week})"
            result.append((label, start, end))
        return result

    if granularity == "Month":
        df["period"] = df["date"].dt.to_period("M")
        periods = sorted(df["period"].unique(), reverse=True)
        result = []
        for p in periods:
            start, end = p.start_time.date(), p.end_time.date()
            label = p.strftime("%B %Y")
            result.append((label, start, end))
        return result

    if granularity == "Year":
        df["period"] = df["date"].dt.to_period("Y")
        periods = sorted(df["period"].unique(), reverse=True)
        result = []
        for p in periods:
            start, end = p.start_time.date(), p.end_time.date()
            label = p.strftime("%Y")
            result.append((label, start, end))
        return result

    return []


def compare_periods(df, start_a, end_a, start_b, end_b):
    """
    Compares total cost and per-service breakdown between two date ranges
    (each inclusive of start and end date). Returns a dict with totals,
    per-service breakdowns, and the difference.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    period_a_df = df[(df["date"] >= start_a) & (df["date"] <= end_a)]
    period_b_df = df[(df["date"] >= start_b) & (df["date"] <= end_b)]

    total_a = period_a_df["cost"].sum()
    total_b = period_b_df["cost"].sum()
    diff = total_b - total_a
    pct_change = (diff / total_a * 100) if total_a else None

    by_service_a = period_a_df.groupby("service")["cost"].sum()
    by_service_b = period_b_df.groupby("service")["cost"].sum()
    all_services = sorted(set(by_service_a.index) | set(by_service_b.index))

    service_comparison = pd.DataFrame({
        "service": all_services,
        "Period A": [round(by_service_a.get(s, 0), 2) for s in all_services],
        "Period B": [round(by_service_b.get(s, 0), 2) for s in all_services],
    })
    service_comparison["Difference"] = (service_comparison["Period B"] - service_comparison["Period A"]).round(2)

    return {
        "total_a": total_a,
        "total_b": total_b,
        "diff": diff,
        "pct_change": pct_change,
        "service_comparison": service_comparison,
        "period_a_days": (end_a - start_a).days + 1,
        "period_b_days": (end_b - start_b).days + 1,
    }
