"""
Azure Cloud Cost Analytics & AI Optimization Dashboard
Run with: streamlit run app.py

See README.md for full setup instructions.
"""
import os
import time
import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

from modules.auth import is_configured
from modules.cost_data import (
    fetch_cost_data, aggregate_by_period, get_available_periods, compare_periods,
    filter_by_range_option,
)
from modules.ai_insights import (
    detect_anomalies, get_idle_and_oversized_resources,
    forecast_next_month, generate_executive_summary,
    build_data_context, chat_with_data, answer_question_free,
)
from modules.export_utils import to_excel_bytes, to_pdf_bytes

load_dotenv()

st.set_page_config(page_title="Azure Cost Analytics Dashboard", layout="wide")

# ---------- Currency helper (INR) ----------
def fmt_inr(value, signed=False):
    """Formats a number as Indian Rupees, e.g. Rs 12,345.67"""
    sign = "+" if signed else ""
    return f"Rs {value:{sign},.2f}"


# ---------- Dark professional theme (injected CSS) ----------
ACCENT = "#22D3EE"       # teal accent
ACCENT_DIM = "#0E7490"   # darker teal for gradients/hover
BG_DARK = "#0B0F19"      # app background
CARD_BG = "#151B29"      # card / panel background
BORDER = "#232B3D"       # subtle border
TEXT_MAIN = "#F1F5F9"    # near-white
TEXT_MUTED = "#94A3B8"   # muted gray

st.markdown(f"""
<style>
.stApp {{
    background-color: {BG_DARK};
    color: {TEXT_MAIN};
}}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background-color: #0E1421;
    border-right: 1px solid {BORDER};
}}
section[data-testid="stSidebar"] * {{
    color: {TEXT_MAIN} !important;
}}
section[data-testid="stSidebar"] div[data-baseweb="select"] {{
    border: 1px solid {BORDER} !important;
    border-radius: 8px;
}}
section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
    background-color: #1B2333 !important;
}}
section[data-testid="stSidebar"] div[data-baseweb="select"] * {{
    color: {TEXT_MAIN} !important;
}}

/* Headings */
h1, h2, h3, h4 {{
    color: {TEXT_MAIN} !important;
    font-weight: 700 !important;
}}
p, span, label, .stCaption {{
    color: {TEXT_MUTED};
}}

/* Metric cards */
div[data-testid="stMetric"] {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-left: 4px solid {ACCENT};
    padding: 16px 20px;
    border-radius: 10px;
}}
div[data-testid="stMetric"] label {{
    color: {TEXT_MUTED} !important;
}}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
    color: {ACCENT} !important;
    font-weight: 700;
}}

/* Tabs */
button[data-baseweb="tab"] {{
    font-weight: 600;
    color: {TEXT_MUTED} !important;
}}
button[data-baseweb="tab"][aria-selected="true"] p {{
    color: {ACCENT} !important;
}}
div[data-baseweb="tab-highlight"] {{
    background-color: {ACCENT} !important;
}}
div[data-baseweb="tab-border"] {{
    background-color: {BORDER} !important;
}}

/* Buttons */
.stButton > button, .stDownloadButton > button {{
    background-color: {ACCENT};
    color: #06202A;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background-color: {ACCENT_DIM};
    color: {TEXT_MAIN};
}}

/* Dataframes / tables */
div[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

/* Info / warning / success boxes */
div[data-testid="stAlert"] {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

/* Chat input and messages */
div[data-testid="stChatMessage"] {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
</style>
""", unsafe_allow_html=True)


# ---------- Shared Plotly dark styling ----------
PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor=CARD_BG,
    plot_bgcolor=CARD_BG,
    font=dict(color=TEXT_MAIN, family="Segoe UI, sans-serif"),
    margin=dict(l=10, r=10, t=30, b=10),
    hoverlabel=dict(bgcolor="#1B2333", font_size=13, font_color=TEXT_MAIN),
)


def style_fig(fig):
    fig.update_layout(**PLOTLY_LAYOUT)
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    return fig


def render_compare_result(result, label_a, label_b):
    """Renders the metrics, breakdown table, and chart for a period comparison.
    Shared by both the preset (Day/Week/Month/Year) and Custom modes in the
    Compare Periods tab."""
    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric(f"Period A total ({label_a})", fmt_inr(result["total_a"]))
    m2.metric(f"Period B total ({label_b})", fmt_inr(result["total_b"]))

    if result["pct_change"] is not None:
        m3.metric(
            "Change",
            fmt_inr(result["diff"], signed=True),
            delta=f"{result['pct_change']:+.1f}%",
            delta_color="inverse",  # cost going up = red, going down = green
        )
    else:
        m3.metric("Change", fmt_inr(result["diff"], signed=True))

    st.subheader("Breakdown by Service")
    st.dataframe(
        result["service_comparison"].sort_values("Period B", ascending=False),
        use_container_width=True, hide_index=True,
    )

    chart_df = result["service_comparison"].sort_values("Period B", ascending=False)
    fig_compare = go.Figure()
    fig_compare.add_trace(go.Bar(
        x=chart_df["service"], y=chart_df["Period A"], name=f"Period A ({label_a})",
        marker_color="#0E7490",
        hovertemplate="<b>%{x}</b><br>Rs %{y:,.2f}<extra></extra>",
    ))
    fig_compare.add_trace(go.Bar(
        x=chart_df["service"], y=chart_df["Period B"], name=f"Period B ({label_b})",
        marker_color="#22D3EE",
        hovertemplate="<b>%{x}</b><br>Rs %{y:,.2f}<extra></extra>",
    ))
    fig_compare.update_layout(barmode="group", xaxis_title="", yaxis_title="Cost (Rs)", legend_title="")
    st.plotly_chart(style_fig(fig_compare), use_container_width=True)

    if result["period_a_days"] != result["period_b_days"]:
        st.caption(
            f"Note: Period A spans {result['period_a_days']} day(s) and Period B spans "
            f"{result['period_b_days']} day(s) - totals aren't length-normalized, keep this "
            f"in mind when comparing periods of different lengths (e.g., Feb vs March, "
            f"or a partial year vs a full year)."
        )


# ---------- Splash screen (shown once per session) ----------
if "splash_done" not in st.session_state:
    st.session_state.splash_done = False

if not st.session_state.splash_done:
    splash = st.empty()
    with splash.container():
        st.markdown(f"""
        <style>
        @keyframes flyIn {{
            0%   {{ transform: translateX(-120%) rotate(-8deg); opacity: 0; }}
            55%  {{ transform: translateX(6%) rotate(2deg); opacity: 1; }}
            75%  {{ transform: translateX(-2%) rotate(-1deg); }}
            100% {{ transform: translateX(0) rotate(0deg); }}
        }}
        @keyframes fadeInUp {{
            0%   {{ transform: translateY(30px); opacity: 0; }}
            100% {{ transform: translateY(0); opacity: 1; }}
        }}
        .splash-wrap {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 80vh;
            background: linear-gradient(135deg, #0B0F19 0%, #101827 50%, #0E2A33 100%);
            border: 1px solid {BORDER};
            border-radius: 20px;
            text-align: center;
            padding: 40px;
        }}
        .splash-title {{
            animation: flyIn 1.6s cubic-bezier(0.17, 0.67, 0.53, 0.99) forwards;
            font-size: 44px;
            font-weight: 800;
            color: {TEXT_MAIN};
            line-height: 1.3;
        }}
        .splash-subtitle {{
            animation: fadeInUp 1.2s ease-out 1.4s both;
            font-size: 20px;
            font-weight: 500;
            color: {ACCENT};
            margin-top: 18px;
            letter-spacing: 0.5px;
        }}
        </style>
        <div class="splash-wrap">
            <div class="splash-title">Azure Cloud Cost Analytics<br>&amp; AI Optimization Dashboard</div>
            <div class="splash-subtitle">FROM TO THE NEW (INDIA POD)</div>
        </div>
        """, unsafe_allow_html=True)
    time.sleep(3)
    splash.empty()
    st.session_state.splash_done = True

# ---------- Load data ----------
if "raw_df" not in st.session_state:
    with st.spinner("Loading cost data..."):
        st.session_state.raw_df, st.session_state.is_real_data = fetch_cost_data(days=180)

raw_df = st.session_state.raw_df
is_real_data = st.session_state.is_real_data

# ---------- Header ----------
st.title("Azure Cloud Cost Analytics & AI Optimization Dashboard")
st.caption("From To The New (India Pod)")

if not is_real_data:
    st.info(
        "**Demo Mode** - showing sample data. Fill in your `.env` file with real Azure "
        "credentials (see README.md Phase 2 & 3) to see your actual cost data."
    )

# ---------- Sidebar filters (dropdowns) ----------
st.sidebar.header("Filters")

subscriptions = sorted(raw_df["subscription"].unique())
resource_groups = sorted(raw_df["resource_group"].unique())
services = sorted(raw_df["service"].unique())
environments = sorted(raw_df["environment"].unique())

sel_sub = st.sidebar.selectbox("Subscription", ["All"] + subscriptions)
sel_rg = st.sidebar.selectbox("Resource Group", ["All"] + resource_groups)
sel_service = st.sidebar.selectbox("Service", ["All"] + services)
sel_env = st.sidebar.selectbox("Environment", ["All"] + environments)

filtered_df = raw_df.copy()
if sel_sub != "All":
    filtered_df = filtered_df[filtered_df["subscription"] == sel_sub]
if sel_rg != "All":
    filtered_df = filtered_df[filtered_df["resource_group"] == sel_rg]
if sel_service != "All":
    filtered_df = filtered_df[filtered_df["service"] == sel_service]
if sel_env != "All":
    filtered_df = filtered_df[filtered_df["environment"] == sel_env]

if filtered_df.empty:
    st.warning("No data matches the selected filters. Try choosing 'All' on one or more filters.")
    st.stop()

# ---------- Tabs ----------
tab_trends, tab_compare, tab_ai, tab_chat, tab_export = st.tabs(
    ["Cost Trends", "Compare Periods", "AI Insights", "Ask AI", "Export Reports"]
)

# ================= TAB 1: TRENDS =================
with tab_trends:
    st.markdown("##### Date Range")
    trend_range_option = st.radio(
        "Show data for:", ["Weekly", "Monthly", "Yearly", "Custom", "All (180 days)"],
        horizontal=True, index=4, key="trend_range_option",
    )

    trend_custom_start, trend_custom_end = None, None
    if trend_range_option == "Custom":
        min_date = pd.to_datetime(filtered_df["date"]).min().date()
        max_date = pd.to_datetime(filtered_df["date"]).max().date()
        c1, c2 = st.columns(2)
        with c1:
            trend_custom_start = st.date_input(
                "Start date", value=max(min_date, max_date - datetime.timedelta(days=30)),
                min_value=min_date, max_value=max_date, key="trend_custom_start",
            )
        with c2:
            trend_custom_end = st.date_input(
                "End date", value=max_date, min_value=min_date, max_value=max_date,
                key="trend_custom_end",
            )
        if trend_custom_start > trend_custom_end:
            st.error("Start date must be before end date.")
            st.stop()

    scope_df = filter_by_range_option(filtered_df, trend_range_option, trend_custom_start, trend_custom_end)
    if scope_df.empty:
        st.warning("No data in this date range. Try a different range.")
        st.stop()

    total_cost = scope_df["cost"].sum()
    st.metric(f"Total Cost ({trend_range_option})", fmt_inr(total_cost))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Cost by Service")
        by_service = scope_df.groupby("service")["cost"].sum().sort_values(ascending=False).reset_index()
        fig_service = px.bar(
            by_service, x="service", y="cost", color="cost",
            color_continuous_scale=["#0E7490", "#22D3EE", "#A5F3FC"],
        )
        fig_service.update_traces(
            hovertemplate="<b>%{x}</b><br>Rs %{y:,.2f}<extra></extra>",
            marker_line_width=0,
        )
        fig_service.update_layout(coloraxis_showscale=False, xaxis_title="", yaxis_title="Cost (Rs)")
        st.plotly_chart(style_fig(fig_service), use_container_width=True)
    with col2:
        st.subheader("Cost by Environment")
        by_env = scope_df.groupby("environment")["cost"].sum().reset_index()
        fig_env = px.pie(
            by_env, names="environment", values="cost", hole=0.55,
            color_discrete_sequence=["#22D3EE", "#0E7490", "#7DD3FC", "#164E63"],
        )
        fig_env.update_traces(
            hovertemplate="<b>%{label}</b><br>Rs %{value:,.2f}<extra></extra>",
            textfont_color=TEXT_MAIN,
        )
        st.plotly_chart(style_fig(fig_env), use_container_width=True)

    st.subheader("Cost Trend Over Time")
    period_choice = st.radio(
        "View by:", ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly"],
        horizontal=True, index=2, key="trend_granularity",
    )
    period_map = {"Daily": "D", "Weekly": "W", "Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}
    trend_df = aggregate_by_period(scope_df, period_map[period_choice])

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(
        x=trend_df["date"], y=trend_df["cost"],
        mode="lines+markers",
        line=dict(color=ACCENT, width=3, shape="spline"),
        marker=dict(size=6, color=ACCENT, line=dict(width=1, color=BG_DARK)),
        fill="tozeroy",
        fillcolor="rgba(34, 211, 238, 0.12)",
        hovertemplate="<b>%{x}</b><br>Rs %{y:,.2f}<extra></extra>",
    ))
    fig_trend.update_layout(xaxis_title="", yaxis_title="Cost (Rs)", showlegend=False)
    st.plotly_chart(style_fig(fig_trend), use_container_width=True)

    st.subheader("Raw Cost Data (filtered)")
    st.dataframe(scope_df.sort_values("date", ascending=False), use_container_width=True, height=300)

# ================= TAB: COMPARE PERIODS =================
with tab_compare:
    st.subheader("Compare Cost Across Two Periods")
    st.caption(
        "Pick a granularity (Day, Week, Month, or Year), then choose any two periods to "
        "compare - e.g., this month vs last month, this year vs last year - or pick "
        "Custom to compare any two date ranges you choose yourself."
    )

    granularity = st.radio(
        "Compare by:", ["Day", "Week", "Month", "Year", "Custom"], horizontal=True, index=2,
    )

    if granularity == "Custom":
        min_date = pd.to_datetime(filtered_df["date"]).min().date()
        max_date = pd.to_datetime(filtered_df["date"]).max().date()

        st.markdown("**Period A**")
        ca1, ca2 = st.columns(2)
        with ca1:
            start_a = st.date_input(
                "Period A start", value=min_date, min_value=min_date, max_value=max_date,
                key="cmp_start_a",
            )
        with ca2:
            end_a = st.date_input(
                "Period A end", value=min(min_date + datetime.timedelta(days=29), max_date),
                min_value=min_date, max_value=max_date, key="cmp_end_a",
            )

        st.markdown("**Period B**")
        cb1, cb2 = st.columns(2)
        with cb1:
            start_b = st.date_input(
                "Period B start", value=max(min_date, max_date - datetime.timedelta(days=29)),
                min_value=min_date, max_value=max_date, key="cmp_start_b",
            )
        with cb2:
            end_b = st.date_input(
                "Period B end", value=max_date, min_value=min_date, max_value=max_date,
                key="cmp_end_b",
            )

        if start_a > end_a or start_b > end_b:
            st.error("Each period's start date must be before its end date.")
            st.stop()

        label_a = f"{start_a.strftime('%d %b %Y')} - {end_a.strftime('%d %b %Y')}"
        label_b = f"{start_b.strftime('%d %b %Y')} - {end_b.strftime('%d %b %Y')}"

        result = compare_periods(filtered_df, start_a, end_a, start_b, end_b)
        render_compare_result(result, label_a, label_b)

    else:
        available_periods = get_available_periods(filtered_df, granularity)

        if len(available_periods) < 2:
            st.warning(f"Not enough {granularity.lower()} data yet to compare. Try a different granularity.")
        else:
            labels = [p[0] for p in available_periods]

            col1, col2 = st.columns(2)
            with col1:
                idx_a = st.selectbox(
                    f"Period A (older {granularity.lower()})", range(len(labels)),
                    format_func=lambda i: labels[i], index=min(1, len(labels) - 1),
                )
            with col2:
                idx_b = st.selectbox(
                    f"Period B (newer {granularity.lower()})", range(len(labels)),
                    format_func=lambda i: labels[i], index=0,
                )

            _, start_a, end_a = available_periods[idx_a]
            _, start_b, end_b = available_periods[idx_b]

            result = compare_periods(filtered_df, start_a, end_a, start_b, end_b)
            render_compare_result(result, labels[idx_a], labels[idx_b])

# ================= TAB 2: AI INSIGHTS =================
with tab_ai:
    daily_df = aggregate_by_period(filtered_df, "D")
    monthly_df = aggregate_by_period(filtered_df, "M")

    st.subheader("Cost Anomalies")
    anomalies = detect_anomalies(daily_df)
    if anomalies.empty:
        st.success("No significant cost anomalies detected in the selected range.")
    else:
        st.warning(f"{len(anomalies)} anomaly day(s) detected:")
        st.dataframe(anomalies, use_container_width=True)

    st.subheader("Idle, Over-Provisioned & Unattached Resources")
    advisor_df = get_idle_and_oversized_resources()
    st.dataframe(advisor_df, use_container_width=True)

    st.subheader("Reserved Instance Recommendations")
    ri_recs = advisor_df[advisor_df["recommendation"].str.contains("Reserved", case=False, na=False)]
    if ri_recs.empty:
        st.info("No Reserved Instance recommendations found for the current filters.")
    else:
        st.dataframe(ri_recs, use_container_width=True)

    st.subheader("Next Month Spend Forecast")
    forecast = forecast_next_month(monthly_df)
    if forecast is not None:
        st.metric("Forecasted spend (next month)", fmt_inr(forecast))
    else:
        st.info("Not enough monthly history yet to forecast (need at least 3 months of data).")

    st.subheader("Executive Summary")
    top_services = list(by_service["service"].head(3)) if "by_service" in dir() else []
    savings_text = f"{len(advisor_df)} optimization opportunities (see table above)"
    summary = generate_executive_summary(
        total_cost=filtered_df["cost"].sum(),
        top_services=list(filtered_df.groupby("service")["cost"].sum().sort_values(ascending=False).head(3).index),
        anomalies_count=len(anomalies),
        savings_opportunities=savings_text,
    )
    st.write(summary)

# ================= TAB 3: ASK AI (chatbot) =================
with tab_chat:
    st.subheader("Ask questions about your cost data")

    has_api_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    if has_api_key:
        st.caption(
            "AI mode (Claude) - ask anything in your own words. Answers are based "
            "only on your currently filtered data (see sidebar)."
        )
    else:
        st.caption(
            "Free mode (no API key, no cost) - matches your question to common patterns "
            "like totals, top services, spikes, trends, forecast, and savings. Answers are "
            "based only on your currently filtered data (see sidebar)."
        )
        st.info(
            "Want free-form, natural-language answers instead? Add an `ANTHROPIC_API_KEY` "
            "to your `.env` file (get one at https://console.anthropic.com/) to unlock full "
            "AI chat mode. Not required - the free mode below works out of the box."
        )

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []  # list of {"role", "content"} for Claude
        st.session_state.chat_display = []   # same, but for rendering in the UI

    # Render existing conversation
    for msg in st.session_state.chat_display:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Rebuild data context fresh each time (reflects current sidebar filters)
    anomalies_for_chat = detect_anomalies(aggregate_by_period(filtered_df, "D"))
    advisor_for_chat = get_idle_and_oversized_resources()
    forecast_for_chat = forecast_next_month(aggregate_by_period(filtered_df, "M"))

    user_question = st.chat_input("Ask a question about your cost data...")
    if user_question:
        st.session_state.chat_display.append({"role": "user", "content": user_question})
        with st.chat_message("user"):
            st.write(user_question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                if has_api_key:
                    data_context = build_data_context(
                        filtered_df, anomalies_for_chat, advisor_for_chat, forecast_for_chat
                    )
                    answer = chat_with_data(
                        user_question, data_context, chat_history=st.session_state.chat_messages
                    )
                else:
                    answer = answer_question_free(
                        user_question, filtered_df, anomalies_for_chat, advisor_for_chat, forecast_for_chat
                    )
            st.write(answer)

        st.session_state.chat_messages.append({"role": "user", "content": user_question})
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})
        st.session_state.chat_display.append({"role": "assistant", "content": answer})

    if st.session_state.chat_display:
        if st.button("Clear conversation"):
            st.session_state.chat_messages = []
            st.session_state.chat_display = []
            st.rerun()

# ================= TAB 4: EXPORT =================
with tab_export:
    st.subheader("Download Reports")
    st.write("Exports use your current filter selections from the sidebar, plus the date range below.")

    st.markdown("##### Date Range")
    export_range_option = st.radio(
        "Report period:", ["Weekly", "Monthly", "Yearly", "Custom", "All (180 days)"],
        horizontal=True, index=4, key="export_range_option",
    )

    export_custom_start, export_custom_end = None, None
    if export_range_option == "Custom":
        min_date = pd.to_datetime(filtered_df["date"]).min().date()
        max_date = pd.to_datetime(filtered_df["date"]).max().date()
        e1, e2 = st.columns(2)
        with e1:
            export_custom_start = st.date_input(
                "Start date", value=max(min_date, max_date - datetime.timedelta(days=30)),
                min_value=min_date, max_value=max_date, key="export_custom_start",
            )
        with e2:
            export_custom_end = st.date_input(
                "End date", value=max_date, min_value=min_date, max_value=max_date,
                key="export_custom_end",
            )
        if export_custom_start > export_custom_end:
            st.error("Start date must be before end date.")
            st.stop()

    export_df = filter_by_range_option(filtered_df, export_range_option, export_custom_start, export_custom_end)

    if export_df.empty:
        st.warning("No data in this date range to export. Try a different range.")
    else:
        st.caption(f"Report covers {len(export_df):,} row(s) of cost data for the selected range.")

        excel_bytes = to_excel_bytes(export_df, sheet_name="Cost Data")
        st.download_button(
            "Download Excel Report",
            data=excel_bytes,
            file_name="azure_cost_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        pdf_summary = generate_executive_summary(
            total_cost=export_df["cost"].sum(),
            top_services=list(export_df.groupby("service")["cost"].sum().sort_values(ascending=False).head(3).index),
            anomalies_count=len(detect_anomalies(aggregate_by_period(export_df, "D"))),
            savings_opportunities="see AI Insights tab",
        )
        pdf_bytes = to_pdf_bytes("Azure Cost Report", pdf_summary, export_df)
        st.download_button(
            "Download PDF Report",
            data=pdf_bytes,
            file_name="azure_cost_report.pdf",
            mime="application/pdf",
        )

st.sidebar.markdown("---")
st.sidebar.caption(
    "Data source: " + ("Live Azure Cost Management API" if is_real_data else "Sample demo data")
)
