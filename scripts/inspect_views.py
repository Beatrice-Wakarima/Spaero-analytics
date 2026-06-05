import os
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Logging & Config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
load_dotenv()

DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "postgres_warehouse")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)


# View registry
# Groups map 1-to-1 to dashboard pages
VIEW_GROUPS = {
    "INT STAGING LAYER  (int.*)": [
        "int.stg_customers",
        "int.stg_sales",
        "int.stg_revenue_targets",
        "int.stg_cash_flow",
        "int.stg_employees",
    ],

    "ANALYTICS DIMS & MARTS  (analytics.*)": [
        "analytics.dim_customers",
        "analytics.dim_products",
        "analytics.dim_date",
        "analytics.mart_annual_performance",
        "analytics.mart_monthly_sales",
        "analytics.mart_customer_sales",
        "analytics.mart_product_sales",
        "analytics.mart_product_cashflow",
    ],

    "PAGE 1 · Executive Overview  (presentation.*)": [
        "presentation.vw_exec_kpi_scorecard",
        "presentation.vw_exec_monthly_trend",
        "presentation.vw_exec_segment_summary",
    ],

    "PAGE 2 · Customer Analytics  (presentation.*)": [
        "presentation.vw_customer_performance",
        "presentation.vw_customer_yearly_revenue",
        "presentation.vw_customer_country_summary",
        "presentation.vw_customer_rfm",
    ],

    "PAGE 3 · Product Analytics  (presentation.*)": [
        "presentation.vw_product_performance",
        "presentation.vw_product_monthly_trend",
        "presentation.vw_product_segment_matrix",
        "presentation.vw_product_pricing",
    ],

    "PAGE 4 · Revenue Forecast  (presentation.*)": [
        "presentation.vw_revenue_actual_vs_target",
        "presentation.vw_revenue_growth",
        "presentation.vw_revenue_forecast_linear",
        "presentation.vw_revenue_seasonality",
    ],

    "PAGE 5 · Capital Budgeting  (presentation.*)": [
        "presentation.vw_capex_cashflow_schedule",
        "presentation.vw_capex_project_summary",
        "presentation.vw_capex_sensitivity",
    ],

    "PAGE 6 · Employee Analytics  (presentation.*)": [
        "presentation.vw_employee_dept_summary",
        "presentation.vw_employee_tenure_distribution",
        "presentation.vw_employee_hiring_cohort",
        "presentation.vw_employee_roster",
    ],
}

PREVIEW_ROWS = 5   # rows to show per view
SHOW_DTYPES  = False  # set True for column type detail


# Helpers
def row_count(view: str) -> int:
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {view}"))
            return result.scalar()
    except Exception:
        return -1


def preview_view(view: str) -> None:
    print(f"\n  ➔  {view}")
    print("  " + "-" * 74)
    try:
        df = pd.read_sql_query(
            f"SELECT * FROM {view} LIMIT {PREVIEW_ROWS};",
            con=engine
        )
        n = row_count(view)
        print(f"  Rows: {n}   |   Columns: {len(df.columns)}")
        print(f"  Columns: {list(df.columns)}")

        if SHOW_DTYPES:
            print(f"  Dtypes:\n{df.dtypes.to_string()}")

        if df.empty:
            print("  View returned an empty recordset.")
        else:
            # Indent each data row for readability
            formatted = df.to_string(index=False)
            for line in formatted.splitlines():
                print("  " + line)

    except Exception as e:
        print(f"  ✘  Failed to query {view}: {e}")

    print("  " + "-" * 74)


# Main inspection runner
def inspect_all_views() -> None:
    print("\n" + "=" * 78)
    print("   SPAERO DATA WAREHOUSE – FULL LAYER INSPECTION")
    print("=" * 78)

    for group_name, views in VIEW_GROUPS.items():
        print(f"\n{'━' * 78}")
        print(f"  {group_name}")
        print(f"{'━' * 78}")
        for view in views:
            preview_view(view)

    print("\n" + "=" * 78)
    print("  Inspection complete.")
    print("=" * 78 + "\n")


def inspect_group(group_key: str) -> None:
    """Inspect a single dashboard page group by partial name match."""
    matched = {
        k: v for k, v in VIEW_GROUPS.items()
        if group_key.lower() in k.lower()
    }
    if not matched:
        print(f"No group matching '{group_key}'. Available groups:")
        for k in VIEW_GROUPS:
            print(f"  • {k}")
        return
    for group_name, views in matched.items():
        print(f"\n{'━' * 78}\n  {group_name}\n{'━' * 78}")
        for view in views:
            preview_view(view)


def inspect_single_view(view: str) -> None:
    """Inspect one specific view by full schema.view_name."""
    preview_view(view)


# CLI Entry Point
if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        inspect_all_views()

    elif sys.argv[1] == "--group":
        if len(sys.argv) < 3:
            print("Usage: python inspect_views.py --group <partial_group_name>")
            sys.exit(1)
        inspect_group(sys.argv[2])

    elif sys.argv[1] == "--view":
        
        if len(sys.argv) < 3:
            print("Usage: python inspect_views.py --view <schema.view_name>")
            sys.exit(1)
        inspect_single_view(sys.argv[2])

    else:
        print("Unknown argument. Usage:")
        print("  python inspect_views.py                          # inspect all")
        print("  python inspect_views.py --group <name>           # one group")
        print("  python inspect_views.py --view  <schema.view>   # one view")
        sys.exit(1)