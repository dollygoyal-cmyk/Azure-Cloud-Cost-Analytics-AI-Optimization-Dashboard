# Azure Cloud Cost Analytics & AI Optimization Dashboard
### Prompts Used, Issues Faced, and Features Added

---

## Phase 1 — Initial Build

**Prompt 1:**
> "Build me a Streamlit dashboard for Azure cloud cost analytics. It should pull
> cost data from Azure Cost Management, let me filter by subscription, resource
> group, service, and environment (dev/prod), and show trend charts (daily,
> weekly, monthly, quarterly, yearly). Include an AI Insights tab with anomaly
> detection, idle resource recommendations, and a cost forecast. Also add
> export to Excel and PDF. I don't have my Azure credentials set up yet, so
> make sure it still works and shows something useful with demo/sample data
> until I configure real credentials."

**Result:** Initial `app.py`, `modules/cost_data.py`, `modules/auth.py` scaffold,
with sample data generation as a fallback so the dashboard is usable on first
run without any Azure setup.

---

## Phase 2 — Issue: Azure SDK datetime bug

**Issue faced:**
> "I'm using `azure-mgmt-costmanagement` and getting `Invalid datetime string`
> errors when the SDK tries to deserialize the `UsageDate` field returned by
> the Cost Management API. This happens even on the latest SDK version."

**Prompt 2 (fix requested):**
> "Instead of fighting the SDK's deserialization bug, can you rewrite the cost
> data fetch to call the Cost Management REST API directly with `requests`
> and parse the JSON ourselves? I need to handle `UsageDate` coming back as
> either an integer like `20260121` or as a string date."

**Result:** Cost data fetch now calls the Cost Management REST endpoint
directly and parses dates safely, bypassing the SDK bug entirely.

---

## Phase 3 — Feature: Authentication & demo/live mode switch

**Prompt 3:**
> "Set up authentication using a Service Principal (App Registration) with a
> tenant ID, client ID, and client secret from a `.env` file. If those aren't
> filled in yet, the app should silently fall back to demo mode instead of
> crashing — I want to be able to hand this to someone before they've done any
> Azure setup."

**Result:** Authentication module with graceful fallbacks, and a demo/live
mode banner on the dashboard so it's always clear which one is active.

**Issue faced:**
> "When Azure auth fails partway through (bad token, one subscription with no
> Cost Management Reader role assigned yet), the whole dashboard crashes
> instead of just skipping that subscription."

**Prompt 4 (fix requested):**
> "Wrap each subscription's fetch in its own try/except so one bad
> subscription (403, wrong role, etc.) shows a warning banner but doesn't take
> down the whole dashboard — and fall back to demo data only if *every*
> subscription fails."

**Result:** Per-subscription error handling with clear warning messages
instead of a full crash.

---

## Phase 4 — Feature: Period filters & cost comparison

**Prompt 5:**
> "Add preset date range filters — Weekly (this week to date), Monthly (this
> month to date), Yearly (this year to date), and a Custom range picker."

**Prompt 6 (feature add — cost comparison):**
> "Add a Cost Comparison feature where I can pick any two periods — day vs day,
> week vs week, month vs month, or year vs year — and see them side-by-side:
> total cost for each, the percentage change between them, and a per-service
> breakdown table showing exactly which services went up or down and by how
> much. This should work off whatever data is currently loaded, not just
> preset periods."

**Result:** A dedicated Compare tab with period-selection dropdowns, a
total-cost delta summary, and a per-service comparison table sorted by the
biggest swings.

**Issue faced:**
> "I'm getting a `FutureWarning` from pandas about deprecated resample
> aliases when I aggregate by month/quarter/year — 'M', 'Q', 'Y' are
> deprecated."

**Prompt 7 (fix requested):**
> "Update the aggregation function to use the new pandas offset aliases
> (`ME`, `QE`, `YE`) instead of the deprecated `M`, `Q`, `Y`, without changing
> how I call it from the rest of the app."

**Result:** Aggregation updated to use the non-deprecated pandas offset
aliases internally.

---

## Phase 5 — Feature: AI Insights tab

**Prompt 8:**
> "Add an AI Insights tab with:
> 1. Statistical anomaly detection on daily spend (no external AI needed —
>    just flag days that deviate significantly from a trailing average)
> 2. Idle / over-provisioned resource detection and Reserved Instance
>    recommendations, pulled from Azure Advisor, with realistic sample data
>    as a fallback if Advisor isn't configured
> 3. A simple next-month spend forecast based on the recent trend
> 4. An auto-generated plain-English executive summary of the top findings"

**Result:** Anomaly detection, idle/over-provisioned resource flags, RI
recommendations, a trend-based forecast, and an executive summary, each with
a demo-data fallback so the tab never shows empty.

**Prompt 9 (feature add — AI-written summary):**
> "For the executive summary, if I add an Anthropic API key to `.env`, use
> Claude to write a proper 4-5 sentence summary aimed at a non-technical
> manager — plain language, action-oriented. If the key isn't set, or the
> API call fails for any reason, fall back to a templated summary so the
> feature never just breaks."

**Result:** Executive summary uses Claude when a key is present, with a
template fallback on any failure.

---

## Phase 6 — Feature: Natural-language Q&A / chat with data

**Prompt 10:**
> "Add a chat-style tab where I can ask questions about the currently filtered
> data in plain English — things like 'what's the total cost', 'which service
> is most expensive', 'why did cost spike', 'what's the forecast for next
> month', 'how can I save money'. I want this to work even without an API
> key, using pure pandas/keyword matching, but also support a smarter mode
> using Claude if I've added an API key, including follow-up questions using
> chat history."

**Result:** A free (no-API) keyword-based Q&A mode plus an optional
Claude-powered chat mode that uses the filtered dashboard data as context.

---

## Phase 7 — Feature: Export to Excel & PDF

**Prompt 11:**
> "Add export buttons for the current filtered view — one for Excel, one for
> PDF. The PDF should have a title, the executive summary text, and a data
> table of the top rows, styled with a proper header and alternating row
> colors, not just a plain dump."

**Result:** Excel export via `openpyxl` and a formatted PDF export via
`reportlab`, both driven off the currently filtered view.

---

## Phase 8 — Feature: Dashboard styling / color theme

**Prompt 12:**
> "Change the overall look of the dashboard — right now the default Streamlit
> theme feels plain. Can you give it a proper color scheme: a consistent
> accent color for headers and buttons, styled chart colors that match across
> all tabs, and better-looking metric cards instead of the default ones? Make
> it feel like a proper enterprise dashboard rather than a demo."

**Result:** A consistent color palette applied across chart styling (via a
shared `style_fig()` helper), sidebar and header accents, and formatted
metric displays so all tabs feel visually consistent.

**Prompt 13 (follow-up):**
> "The chart colors don't match the rest of the dashboard's theme — can you
> pull them from the same palette we're using for the headers instead of the
> default Plotly colors?"

**Result:** Chart color palette centralized so trend charts, comparison
charts, and AI Insights visuals all draw from the same theme.

---

## Phase 9 — Polish & packaging

**Prompt 14:**
> "Write me a complete, beginner-friendly setup guide assuming I know nothing
> about Azure App Registrations — from installing Python, to creating the
> Service Principal and assigning it 'Cost Management Reader', to filling in
> `.env`, to running it locally, to deploying it (Streamlit Community Cloud
> or Azure App Service). Include a troubleshooting table for common first-run
> errors."

**Result:** Full setup guide covering installation, Azure App Registration,
project setup, running locally, deployment options, and a troubleshooting
table for common first-run errors.

**Prompt 15:**
> "Pin all the dependency versions in `requirements.txt` so this doesn't
> break on a fresh install six months from now."

**Result:** All dependencies pinned to specific tested versions.

---

## Summary of Issues Faced During the Build

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | `Invalid datetime string` from Azure SDK | Known deserialization bug in `azure-mgmt-costmanagement` for certain `UsageDate` formats | Bypassed the SDK; call the Cost Management REST API directly and parse dates manually |
| 2 | Dashboard crashed with no Azure credentials | No fallback path on first run | Added a configuration check and full demo/sample data mode |
| 3 | One bad subscription (403 / wrong role) crashed the whole app | No per-subscription error isolation | Wrapped each subscription fetch in its own try/except with a warning banner |
| 4 | `FutureWarning` on `.resample("M"/"Q"/"Y")` | Pandas deprecated those offset aliases | Mapped to `ME`/`QE`/`YE` internally |
| 5 | Azure Advisor not configured / no recommendations yet | Advisor needs time to generate recommendations, or isn't enabled | Added realistic sample Advisor recommendations as a fallback |
| 6 | AI executive summary breaking the whole tab if the Anthropic API call failed | No error handling around the API call | Wrapped in try/except, falls back to a templated summary with a note |
| 7 | Chart colors inconsistent with dashboard theme | Default Plotly color palette used per-chart | Centralized theme/color palette applied via a shared styling helper |
| 8 | Client secret expiry (12-month default) | Azure App Registration secrets expire | Documented rotation reminder in setup guide |
