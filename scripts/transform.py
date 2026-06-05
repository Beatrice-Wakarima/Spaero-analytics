import os
import sys
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
load_dotenv()

# 2. Environment Validation
REQUIRED_ENV_VARS = ["DB_USER", "DB_PASSWORD", "DB_NAME"]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    logging.critical(f"Missing environment variables: {missing_vars}")
    sys.exit(1)

DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "postgres_warehouse")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 3. Transformation Blocks
#    Order: Schema → Staging → Dims → Marts → Presentation
TRANSFORMATION_BLOCKS = [

        # BLOCK 1 – Extensions & Schemas
    {
        "name": "Extensions & Schema Initialisation",
        "sql": """
            CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
            CREATE SCHEMA IF NOT EXISTS int;
            CREATE SCHEMA IF NOT EXISTS analytics;
            CREATE SCHEMA IF NOT EXISTS presentation;
        """
    },

        # BLOCK 2 – Staging Views (int.*)
    
    {
    "name": "Staging: Customers – Drop (int.stg_customers)",
    "sql": "DROP VIEW IF EXISTS int.stg_customers CASCADE;"
    },
    {
        "name": "Staging: Customers – Create (int.stg_customers)",
        "sql": """
            CREATE VIEW int.stg_customers AS
            SELECT
                customer_id::VARCHAR(50)             AS customer_id,
                UPPER(TRIM(segment))                 AS customer_segment,
                TRIM(country)                        AS country,
                discount_premium_band::NUMERIC(10,4) AS discount_premium_band
            FROM raw.spaero_sales_customer_dim
            WHERE customer_id IS NOT NULL;
        """
    },
    {
        "name": "Staging: Sales – Drop (int.stg_sales)",
        "sql": "DROP VIEW IF EXISTS int.stg_sales CASCADE;"
    },
    {
        "name": "Staging: Sales – Create (int.stg_sales)",
        "sql": """
            CREATE VIEW int.stg_sales AS
            SELECT
                order_id::VARCHAR(50)                          AS order_id,
                order_date::DATE                               AS order_date,
                EXTRACT(YEAR  FROM order_date::DATE)::INT      AS order_year,
                EXTRACT(MONTH FROM order_date::DATE)::INT      AS order_month,
                EXTRACT(QUARTER FROM order_date::DATE)::INT    AS order_quarter,
                TO_CHAR(order_date::DATE, 'Month')             AS order_month_name,
                customer_id::VARCHAR(50)                       AS customer_id,
                product_id::VARCHAR(50)                        AS product_id,
                units_sold::INT                                AS units_sold,
                manufacturing_price::NUMERIC(12,2)             AS manufacturing_price,
                target_sale_price::NUMERIC(12,2)               AS target_sale_price,
                gross_sales::NUMERIC(15,2)                     AS gross_sales,
                discount_premium::NUMERIC(15,2)                AS discount_premium,
                revenue::NUMERIC(15,2)                         AS revenue,
                cogs::NUMERIC(15,2)                            AS cogs,
                profit::NUMERIC(15,2)                          AS reported_profit,
                (revenue::NUMERIC(15,2) - cogs::NUMERIC(15,2)) AS calculated_profit
            FROM raw.spaero_sales_sales_fact
            WHERE order_id IS NOT NULL;
        """
    },
    {
        "name": "Staging: Revenue Targets – Drop (int.stg_revenue_targets)",
        "sql": "DROP VIEW IF EXISTS int.stg_revenue_targets CASCADE;"
    },
    {
        "name": "Staging: Revenue Targets – Create (int.stg_revenue_targets)",
        "sql": """
            CREATE VIEW int.stg_revenue_targets AS
            SELECT
                revenue_target::NUMERIC(15,2)             AS targeted_revenue,
                target_date::DATE                          AS target_date,
                EXTRACT(YEAR FROM target_date::DATE)::INT  AS target_year
            FROM raw.revenue_targets_revenue_targets;
        """
    },
    {
        "name": "Staging: Cash Flow – Drop (int.stg_cash_flow)",
        "sql": "DROP VIEW IF EXISTS int.stg_cash_flow CASCADE;"
    },
    {
        "name": "Staging: Cash Flow – Create (int.stg_cash_flow)",
        "sql": """
            CREATE VIEW int.stg_cash_flow AS
            SELECT
                date::DATE                                AS cashflow_date,
                EXTRACT(YEAR FROM date::DATE)::INT        AS cashflow_year,
                TRIM(product)::VARCHAR(50)                AS product_id,
                discount_rate::NUMERIC(5,4)               AS assigned_discount_rate,
                cashflow::NUMERIC(15,2)                   AS operational_cashflow
            FROM raw.capital_budgeting_cash_flow;
        """
    },
    {
        "name": "Staging: Employees – Drop (int.stg_employees)",
        "sql": "DROP VIEW IF EXISTS int.stg_employees CASCADE;"
    },
    {
        "name": "Staging: Employees – Create (int.stg_employees)",
        "sql": """
            CREATE VIEW int.stg_employees AS
            SELECT
                employee_id::VARCHAR(50)               AS employee_id,
                TRIM(name)                             AS employee_name,
                start_date::DATE                       AS start_date,
                "tenure_(years)"::NUMERIC(5,2)         AS tenure_years,
                TRIM(department)                       AS department
            FROM raw.employee_fact_sheet1
            WHERE employee_id IS NOT NULL;
        """
    },

        # BLOCK 3 – Dimension Tables (analytics.dim_*)
    {
        "name": "Dimension: Customers (analytics.dim_customers)",
        "sql": """
            DROP TABLE IF EXISTS analytics.dim_customers CASCADE;
            CREATE TABLE analytics.dim_customers AS
            WITH deduped AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY customer_id) AS rn
                FROM int.stg_customers
            )
            SELECT
                uuid_generate_v5(uuid_ns_dns(), customer_id) AS customer_key,
                customer_id,
                customer_segment,
                country,
                discount_premium_band
            FROM deduped WHERE rn = 1;
            CREATE UNIQUE INDEX idx_dim_cust_key ON analytics.dim_customers (customer_key);
            CREATE UNIQUE INDEX idx_dim_cust_id  ON analytics.dim_customers (customer_id);
        """
    },
    {
        "name": "Dimension: Products (analytics.dim_products)",
        "sql": """
            DROP TABLE IF EXISTS analytics.dim_products CASCADE;
            CREATE TABLE analytics.dim_products AS
            WITH deduped AS (
                SELECT DISTINCT product_id,
                    AVG(manufacturing_price) OVER (PARTITION BY product_id) AS avg_mfg_price,
                    MAX(target_sale_price)   OVER (PARTITION BY product_id) AS target_sale_price
                FROM int.stg_sales
            )
            SELECT DISTINCT
                uuid_generate_v5(uuid_ns_dns(), product_id) AS product_key,
                product_id,
                ROUND(avg_mfg_price, 4) AS avg_mfg_price,
                target_sale_price
            FROM deduped;
            CREATE UNIQUE INDEX idx_dim_prod_key ON analytics.dim_products (product_key);
            CREATE UNIQUE INDEX idx_dim_prod_id  ON analytics.dim_products (product_id);
        """
    },
    {
        "name": "Dimension: Date (analytics.dim_date)",
        "sql": """
            DROP TABLE IF EXISTS analytics.dim_date CASCADE;
            CREATE TABLE analytics.dim_date AS
            SELECT
                TO_CHAR(d, 'YYYYMMDD')::INT                 AS date_key,
                d::DATE                                     AS calendar_date,
                EXTRACT(YEAR    FROM d)::INT                AS calendar_year,
                EXTRACT(QUARTER FROM d)::INT                AS calendar_quarter,
                'Q' || EXTRACT(QUARTER FROM d)::TEXT        AS quarter_name,
                EXTRACT(MONTH   FROM d)::INT                AS month_number,
                TRIM(TO_CHAR(d, 'Month'))                   AS month_name,
                TRIM(TO_CHAR(d, 'Mon'))                     AS month_abbr,
                TRIM(TO_CHAR(d, 'Month')) || ' ' ||
                    EXTRACT(YEAR FROM d)::TEXT              AS month_year_label,
                TO_CHAR(d, 'Dy')                            AS day_of_week_short,
                EXTRACT(ISODOW FROM d)::INT                 AS day_of_week_number,
                DATE_TRUNC('week',    d)::DATE              AS week_start_date,
                DATE_TRUNC('month',   d)::DATE              AS month_start_date,
                DATE_TRUNC('quarter', d)::DATE              AS quarter_start_date,
                CASE
                    WHEN EXTRACT(MONTH FROM d) >= 7
                    THEN EXTRACT(YEAR FROM d)::INT + 1
                    ELSE EXTRACT(YEAR FROM d)::INT
                END                                         AS fiscal_year
            FROM generate_series('2015-01-01'::DATE,'2035-12-31'::DATE,'1 day'::INTERVAL) AS d;
            CREATE UNIQUE INDEX idx_dim_date_key  ON analytics.dim_date (date_key);
            CREATE UNIQUE INDEX idx_dim_date_date ON analytics.dim_date (calendar_date);
        """
    },

        # BLOCK 4 – Mart Tables (analytics.mart_*)
    {
        "name": "Mart: Annual Performance (analytics.mart_annual_performance)",
        "sql": """
            DROP TABLE IF EXISTS analytics.mart_annual_performance CASCADE;
            CREATE TABLE analytics.mart_annual_performance AS
            SELECT
                uuid_generate_v5(uuid_ns_dns(), s.order_year::TEXT) AS annual_performance_key,
                s.order_year                                         AS performance_year,
                SUM(s.revenue)::NUMERIC(15,2)                        AS actual_revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2)              AS actual_profit,
                SUM(s.cogs)::NUMERIC(15,2)                           AS actual_cogs,
                SUM(s.units_sold)                                    AS units_sold,
                COUNT(DISTINCT s.order_id)                           AS total_orders,
                COUNT(DISTINCT s.customer_id)                        AS unique_customers,
                COALESCE(MAX(t.targeted_revenue), 0)::NUMERIC(15,2)  AS targeted_revenue,
                (SUM(s.revenue) - COALESCE(MAX(t.targeted_revenue), 0))::NUMERIC(15,2) AS target_variance,
                -- Stored as percentage (e.g. 107.27) for direct display in Power BI
                ROUND(
                    SUM(s.revenue) / NULLIF(MAX(t.targeted_revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                      AS target_achievement_pct,
                -- Stored as percentage (e.g. 38.01) for direct display in Power BI
                ROUND(
                    SUM(s.calculated_profit) / NULLIF(SUM(s.revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                      AS gross_margin_pct
            FROM int.stg_sales s
            LEFT JOIN int.stg_revenue_targets t ON s.order_year = t.target_year
            GROUP BY s.order_year;
            CREATE UNIQUE INDEX idx_mart_ann_key ON analytics.mart_annual_performance (annual_performance_key);
        """
    },
    {
        "name": "Mart: Monthly Sales (analytics.mart_monthly_sales)",
        "sql": """
            DROP TABLE IF EXISTS analytics.mart_monthly_sales CASCADE;
            CREATE TABLE analytics.mart_monthly_sales AS
            SELECT
                uuid_generate_v5(
                    uuid_ns_dns(),
                    CONCAT(order_year::TEXT, '-', LPAD(order_month::TEXT, 2, '0'))
                )                                                    AS monthly_sales_key,
                DATE_TRUNC('month', order_date)::DATE                AS month_start,
                order_year,
                order_month,
                EXTRACT(QUARTER FROM order_date)::INT                AS order_quarter,
                TRIM(TO_CHAR(order_date, 'Mon'))                     AS month_abbr,
                SUM(revenue)::NUMERIC(15,2)                          AS monthly_revenue,
                SUM(calculated_profit)::NUMERIC(15,2)                AS monthly_profit,
                SUM(cogs)::NUMERIC(15,2)                             AS monthly_cogs,
                SUM(units_sold)                                      AS monthly_units,
                COUNT(DISTINCT order_id)                             AS order_count,
                ROUND(
                    SUM(calculated_profit) / NULLIF(SUM(revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                      AS margin_pct,
                SUM(SUM(revenue)) OVER (
                    PARTITION BY order_year
                    ORDER BY DATE_TRUNC('month', order_date)
                )::NUMERIC(15,2)                                     AS ytd_revenue
            FROM int.stg_sales
            GROUP BY
                DATE_TRUNC('month', order_date),
                order_year, order_month,
                EXTRACT(QUARTER FROM order_date),
                TRIM(TO_CHAR(order_date, 'Mon'));
            CREATE UNIQUE INDEX idx_mart_monthly_key ON analytics.mart_monthly_sales (monthly_sales_key);
        """
    },
    {
        "name": "Mart: Customer Sales (analytics.mart_customer_sales)",
        "sql": """
            DROP TABLE IF EXISTS analytics.mart_customer_sales CASCADE;
            CREATE TABLE analytics.mart_customer_sales AS
            SELECT
                uuid_generate_v5(uuid_ns_dns(), s.customer_id) AS customer_sales_key,
                s.customer_id,
                c.customer_segment,
                c.country,
                c.discount_premium_band,
                COUNT(DISTINCT s.order_id)                     AS total_orders,
                SUM(s.units_sold)                              AS total_units,
                SUM(s.revenue)::NUMERIC(15,2)                  AS total_revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2)        AS total_profit,
                ROUND(
                    SUM(s.calculated_profit) / NULLIF(SUM(s.revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                AS profit_margin_pct,
                MIN(s.order_date)                              AS first_order_date,
                MAX(s.order_date)                              AS last_order_date,
                COUNT(DISTINCT s.order_year)                   AS active_years,
                ROUND(
                    SUM(s.revenue) / NULLIF(COUNT(DISTINCT s.order_id), 0), 2
                )::NUMERIC(15,2)                               AS avg_order_value,
                SUM(s.discount_premium)::NUMERIC(15,2)         AS total_discount_premium
            FROM int.stg_sales     s
            JOIN int.stg_customers c USING (customer_id)
            GROUP BY s.customer_id, c.customer_segment, c.country, c.discount_premium_band;
            CREATE UNIQUE INDEX idx_mart_cust_sales_key ON analytics.mart_customer_sales (customer_sales_key);
        """
    },
    {
        "name": "Mart: Product Sales (analytics.mart_product_sales)",
        "sql": """
            DROP TABLE IF EXISTS analytics.mart_product_sales CASCADE;
            CREATE TABLE analytics.mart_product_sales AS
            SELECT
                uuid_generate_v5(uuid_ns_dns(), product_id)    AS product_sales_key,
                product_id,
                SUM(units_sold)                                AS total_units_sold,
                SUM(revenue)::NUMERIC(15,2)                    AS total_revenue,
                SUM(cogs)::NUMERIC(15,2)                       AS total_cogs,
                SUM(calculated_profit)::NUMERIC(15,2)          AS total_profit,
                ROUND(
                    SUM(calculated_profit) / NULLIF(SUM(revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                AS gross_margin_pct,
                ROUND(SUM(cogs)    / NULLIF(SUM(units_sold),0), 4)::NUMERIC(12,4) AS avg_unit_mfg_cost,
                ROUND(SUM(revenue) / NULLIF(SUM(units_sold),0), 4)::NUMERIC(12,4) AS avg_unit_revenue,
                ROUND(SUM(calculated_profit) / NULLIF(SUM(units_sold),0), 4)::NUMERIC(12,4) AS avg_unit_profit,
                COUNT(DISTINCT order_id)                       AS total_orders,
                COUNT(DISTINCT customer_id)                    AS customer_reach,
                MIN(order_date)                                AS first_sale_date,
                MAX(order_date)                                AS last_sale_date
            FROM int.stg_sales
            GROUP BY product_id;
            CREATE UNIQUE INDEX idx_mart_prod_sales_key ON analytics.mart_product_sales (product_sales_key);
        """
    },
    {
        "name": "Mart: Capital Budgeting (analytics.mart_product_cashflow)",
        "sql": """
            DROP TABLE IF EXISTS analytics.mart_product_cashflow CASCADE;
            CREATE TABLE analytics.mart_product_cashflow AS
            WITH schedule AS (
                SELECT
                    cashflow_date, cashflow_year, product_id,
                    MAX(assigned_discount_rate) AS assigned_discount_rate,
                    SUM(operational_cashflow)   AS operational_cashflow
                FROM int.stg_cash_flow
                GROUP BY cashflow_date, cashflow_year, product_id
            ),
            numbered AS (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY cashflow_date) - 1 AS period_t
                FROM schedule
            )
            SELECT
                uuid_generate_v5(
                    uuid_ns_dns(),
                    CONCAT(product_id, '_', cashflow_date::TEXT)
                )                                              AS product_cashflow_key,
                cashflow_date,
                cashflow_year,
                product_id,
                assigned_discount_rate,
                operational_cashflow,
                period_t,
                CASE WHEN operational_cashflow < 0 THEN 'Outflow' ELSE 'Inflow' END AS flow_type,
                ROUND(
                    operational_cashflow / POWER(1 + assigned_discount_rate, period_t), 2
                )::NUMERIC(15,2)                               AS discounted_cashflow,
                SUM(operational_cashflow) OVER (
                    PARTITION BY product_id
                    ORDER BY cashflow_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )::NUMERIC(15,2)                               AS cumulative_cashflow
            FROM numbered
            ORDER BY product_id, cashflow_date;
            CREATE UNIQUE INDEX idx_mart_prod_cf_key ON analytics.mart_product_cashflow (product_cashflow_key);
        """
    },

        # BLOCK 5 – Presentation Views (presentation.*)
    # PAGE 1: EXECUTIVE OVERVIEW
    {
        "name": "Presentation: Executive KPI Scorecard (presentation.vw_exec_kpi_scorecard)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_exec_kpi_scorecard AS
            SELECT
                m.performance_year,
                m.actual_revenue,
                m.actual_cogs,
                m.actual_profit,
                m.gross_margin_pct,
                m.units_sold,
                m.total_orders,
                m.unique_customers,
                m.targeted_revenue,
                m.target_variance,
                m.target_achievement_pct,
                LAG(m.actual_revenue) OVER (ORDER BY m.performance_year) AS prior_year_revenue,
                ROUND(
                    (m.actual_revenue - LAG(m.actual_revenue) OVER (ORDER BY m.performance_year))
                    / NULLIF(LAG(m.actual_revenue) OVER (ORDER BY m.performance_year), 0) * 100, 2
                )::NUMERIC(7,2)                                           AS yoy_revenue_growth_pct,
                CASE
                    WHEN m.targeted_revenue = 0                      THEN 'No Target'
                    WHEN m.actual_revenue >= m.targeted_revenue       THEN 'On Target'
                    ELSE 'Below Target'
                END                                                       AS target_status
            FROM analytics.mart_annual_performance m
            ORDER BY m.performance_year;
        """
    },
    {
        "name": "Presentation: Executive Monthly Trend (presentation.vw_exec_monthly_trend)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_exec_monthly_trend AS
            SELECT
                month_start,
                order_year,
                order_month,
                order_quarter,
                month_abbr,
                monthly_revenue,
                monthly_profit,
                monthly_cogs,
                monthly_units,
                order_count,
                margin_pct,
                ytd_revenue,
                LAG(monthly_revenue) OVER (
                    PARTITION BY order_month ORDER BY order_year
                )                                                         AS prior_year_same_month_revenue,
                ROUND(
                    (monthly_revenue
                        - LAG(monthly_revenue) OVER (PARTITION BY order_month ORDER BY order_year))
                    / NULLIF(LAG(monthly_revenue) OVER (PARTITION BY order_month ORDER BY order_year), 0)
                    * 100, 2
                )::NUMERIC(7,2)                                           AS mom_yoy_growth_pct
            FROM analytics.mart_monthly_sales
            ORDER BY month_start;
        """
    },
    {
        "name": "Presentation: Executive Segment Summary (presentation.vw_exec_segment_summary)",
        "sql": """
            -- Includes order_year so Power BI year slicer cross-filters the segment donut
            CREATE OR REPLACE VIEW presentation.vw_exec_segment_summary AS
            SELECT
                s.order_year                                              AS year,
                c.customer_segment                                        AS segment,
                COUNT(DISTINCT s.customer_id)                             AS customer_count,
                SUM(s.revenue)::NUMERIC(15,2)                             AS total_revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2)                   AS total_profit,
                ROUND(
                    SUM(s.calculated_profit) / NULLIF(SUM(s.revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                           AS margin_pct,
                ROUND(
                    SUM(s.revenue)
                    / NULLIF(SUM(SUM(s.revenue)) OVER (PARTITION BY s.order_year), 0) * 100, 2
                )::NUMERIC(7,2)                                           AS revenue_share_pct
            FROM int.stg_sales     s
            JOIN int.stg_customers c USING (customer_id)
            GROUP BY s.order_year, c.customer_segment
            ORDER BY s.order_year, total_revenue DESC;
        """
    },

    # PAGE 2: CUSTOMER ANALYTICS
    {
        "name": "Presentation: Customer Performance (presentation.vw_customer_performance)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_customer_performance AS
            SELECT
                customer_id,
                customer_segment,
                country,
                discount_premium_band,
                total_orders,
                total_units,
                total_revenue,
                total_profit,
                profit_margin_pct,
                first_order_date,
                last_order_date,
                active_years,
                avg_order_value,
                total_discount_premium
            FROM analytics.mart_customer_sales
            ORDER BY total_revenue DESC;
        """
    },
    {
        "name": "Presentation: Customer Yearly Revenue (presentation.vw_customer_yearly_revenue)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_customer_yearly_revenue AS
            SELECT
                s.customer_id,
                c.customer_segment,
                c.country,
                s.order_year                          AS year,
                SUM(s.revenue)::NUMERIC(15,2)         AS revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2) AS profit,
                SUM(s.units_sold)                     AS units_sold,
                COUNT(DISTINCT s.order_id)            AS orders
            FROM int.stg_sales     s
            JOIN int.stg_customers c USING (customer_id)
            GROUP BY s.customer_id, c.customer_segment, c.country, s.order_year
            ORDER BY s.customer_id, year;
        """
    },
    {
        "name": "Presentation: Customer Country Summary (presentation.vw_customer_country_summary)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_customer_country_summary AS
            SELECT
                c.country,
                c.customer_segment,
                s.order_year                                              AS year,
                COUNT(DISTINCT s.customer_id)                             AS customer_count,
                SUM(s.revenue)::NUMERIC(15,2)                             AS total_revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2)                   AS total_profit,
                ROUND(
                    SUM(s.calculated_profit) / NULLIF(SUM(s.revenue), 0) * 100, 2
                )::NUMERIC(7,2)                                           AS margin_pct,
                SUM(s.units_sold)                                         AS total_units,
                COUNT(DISTINCT s.order_id)                                AS total_orders
            FROM int.stg_sales     s
            JOIN int.stg_customers c USING (customer_id)
            GROUP BY c.country, c.customer_segment, s.order_year
            ORDER BY total_revenue DESC;
        """
    },
    {
        "name": "Presentation: Customer RFM (presentation.vw_customer_rfm)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_customer_rfm AS
            WITH rfm_raw AS (
                SELECT
                    customer_id,
                    MAX(order_date)                        AS last_order_date,
                    COUNT(DISTINCT order_id)               AS frequency,
                    SUM(revenue)::NUMERIC(15,2)            AS monetary,
                    (CURRENT_DATE - MAX(order_date))::INT  AS recency_days
                FROM int.stg_sales
                GROUP BY customer_id
            ),
            rfm_scored AS (
                SELECT *,
                    NTILE(5) OVER (ORDER BY recency_days ASC) AS r_score,
                    NTILE(5) OVER (ORDER BY frequency    ASC) AS f_score,
                    NTILE(5) OVER (ORDER BY monetary     ASC) AS m_score
                FROM rfm_raw
            )
            SELECT
                r.customer_id,
                c.customer_segment,
                c.country,
                r.last_order_date,
                r.recency_days,
                r.frequency,
                r.monetary,
                r.r_score,
                r.f_score,
                r.m_score,
                (r.r_score + r.f_score + r.m_score)        AS rfm_total,
                CASE
                    WHEN r.r_score >= 4 AND r.f_score >= 4 AND r.m_score >= 4 THEN 'Champions'
                    WHEN r.r_score >= 3 AND r.f_score >= 3                    THEN 'Loyal Customers'
                    WHEN r.r_score >= 4                                       THEN 'Recent Customers'
                    WHEN r.f_score >= 4 AND r.m_score >= 4                    THEN 'Potential Loyalists'
                    WHEN r.r_score <= 2 AND r.f_score >= 3                    THEN 'At Risk'
                    WHEN r.r_score <= 2 AND r.f_score <= 2                    THEN 'Lost'
                    ELSE 'Need Attention'
                END                                        AS rfm_segment
            FROM rfm_scored    r
            JOIN int.stg_customers c USING (customer_id)
            ORDER BY rfm_total DESC;
        """
    },

    # PAGE 3: PRODUCT ANALYTICS
    {
        "name": "Presentation: Product Performance (presentation.vw_product_performance)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_product_performance AS
            SELECT
                product_id,
                total_units_sold,
                total_revenue,
                total_cogs,
                total_profit,
                gross_margin_pct,
                avg_unit_mfg_cost,
                avg_unit_revenue,
                avg_unit_profit,
                total_orders,
                customer_reach,
                first_sale_date,
                last_sale_date
            FROM analytics.mart_product_sales
            ORDER BY total_revenue DESC;
        """
    },
    {
        "name": "Presentation: Product Monthly Trend (presentation.vw_product_monthly_trend)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_product_monthly_trend AS
            SELECT
                product_id,
                DATE_TRUNC('month', order_date)::DATE  AS month_start,
                order_year,
                order_month,
                order_quarter,
                SUM(units_sold)                        AS units_sold,
                SUM(revenue)::NUMERIC(15,2)            AS revenue,
                SUM(calculated_profit)::NUMERIC(15,2)  AS profit,
                ROUND(
                    SUM(calculated_profit) / NULLIF(SUM(revenue), 0) * 100, 2
                )::NUMERIC(7,2)                        AS margin_pct
            FROM int.stg_sales
            GROUP BY product_id, DATE_TRUNC('month', order_date), order_year, order_month, order_quarter
            ORDER BY product_id, month_start;
        """
    },
    {
        "name": "Presentation: Product Segment Matrix (presentation.vw_product_segment_matrix)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_product_segment_matrix AS
            SELECT
                s.product_id,
                c.customer_segment                     AS segment,
                s.order_year                           AS year,
                SUM(s.units_sold)                      AS units_sold,
                SUM(s.revenue)::NUMERIC(15,2)          AS revenue,
                SUM(s.calculated_profit)::NUMERIC(15,2) AS profit,
                ROUND(
                    SUM(s.calculated_profit) / NULLIF(SUM(s.revenue), 0) * 100, 2
                )::NUMERIC(7,2)                        AS margin_pct,
                COUNT(DISTINCT s.customer_id)          AS customers,
                ROUND(
                    SUM(s.revenue) / NULLIF(SUM(s.units_sold), 0), 2
                )::NUMERIC(12,2)                       AS avg_unit_price
            FROM int.stg_sales     s
            JOIN int.stg_customers c USING (customer_id)
            GROUP BY s.product_id, c.customer_segment, s.order_year
            ORDER BY s.product_id, revenue DESC;
        """
    },
    {
        "name": "Presentation: Product Pricing (presentation.vw_product_pricing)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_product_pricing AS
            SELECT
                product_id,
                order_year                                                AS year,
                ROUND(AVG(manufacturing_price),  4)::NUMERIC(12,4)        AS avg_mfg_price,
                ROUND(AVG(target_sale_price),    4)::NUMERIC(12,4)        AS avg_target_price,
                ROUND(
                    SUM(revenue) / NULLIF(SUM(units_sold), 0), 4
                )::NUMERIC(12,4)                                          AS avg_actual_unit_price,
                ROUND(
                    AVG((revenue - gross_sales) / NULLIF(gross_sales, 0)) * 100, 2
                )::NUMERIC(7,2)                                           AS avg_discount_premium_pct,
                SUM(discount_premium)::NUMERIC(15,2)                      AS total_discount_premium,
                SUM(gross_sales)::NUMERIC(15,2)                           AS total_gross_sales,
                SUM(revenue)::NUMERIC(15,2)                               AS total_net_revenue
            FROM int.stg_sales
            GROUP BY product_id, order_year
            ORDER BY product_id, year;
        """
    },

    # PAGE 4: REVENUE FORECAST
    {
        "name": "Presentation: Revenue Actual vs Target (presentation.vw_revenue_actual_vs_target)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_revenue_actual_vs_target AS
            SELECT
                performance_year,
                targeted_revenue,
                actual_revenue,
                actual_profit,
                target_variance,
                target_achievement_pct,
                target_status
            FROM presentation.vw_exec_kpi_scorecard
            ORDER BY performance_year;
        """
    },
    {
        "name": "Presentation: Revenue Growth (presentation.vw_revenue_growth)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_revenue_growth AS
            WITH base AS (
                SELECT
                    performance_year                                              AS year,
                    actual_revenue,
                    actual_profit,
                    actual_cogs,
                    gross_margin_pct,
                    prior_year_revenue,
                    yoy_revenue_growth_pct,
                    FIRST_VALUE(actual_revenue)   OVER (ORDER BY performance_year) AS base_revenue,
                    FIRST_VALUE(performance_year) OVER (ORDER BY performance_year) AS base_year
                FROM presentation.vw_exec_kpi_scorecard
            )
            SELECT
                year,
                actual_revenue,
                actual_profit,
                actual_cogs,
                gross_margin_pct,
                prior_year_revenue,
                yoy_revenue_growth_pct,
                CASE
                    WHEN year = base_year OR base_revenue IS NULL OR base_revenue = 0 THEN NULL
                    ELSE ROUND(
                        (EXP(
                            LN(actual_revenue::NUMERIC / base_revenue::NUMERIC)
                            / NULLIF((year - base_year)::NUMERIC, 0)
                        ) - 1) * 100, 2
                    )
                END                                                               AS cagr_from_base_pct
            FROM base
            ORDER BY year;
        """
    },
    {
        "name": "Presentation: Revenue Linear Forecast (presentation.vw_revenue_forecast_linear)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_revenue_forecast_linear AS
            WITH actuals AS (
                SELECT performance_year AS year, actual_revenue
                FROM analytics.mart_annual_performance
            ),
            regression AS (
                SELECT
                    REGR_SLOPE(actual_revenue::FLOAT, year::FLOAT)     AS slope,
                    REGR_INTERCEPT(actual_revenue::FLOAT, year::FLOAT) AS intercept,
                    MAX(year)                                          AS last_actual_year
                FROM actuals
            ),
            forecast_years AS (
                SELECT generate_series(
                    (SELECT last_actual_year + 1 FROM regression),
                    (SELECT last_actual_year + 3 FROM regression)
                ) AS year
            )
            SELECT
                fy.year,
                'Forecast'                                                        AS record_type,
                ROUND((r.slope * fy.year + r.intercept)::NUMERIC, 0)::NUMERIC(15,2) AS projected_revenue,
                NULL::NUMERIC                                                     AS actual_revenue
            FROM forecast_years fy
            CROSS JOIN regression r
            UNION ALL
            SELECT
                year,
                'Actual'       AS record_type,
                NULL::NUMERIC  AS projected_revenue,
                actual_revenue
            FROM actuals
            ORDER BY year;
        """
    },
    {
        "name": "Presentation: Revenue Seasonality (presentation.vw_revenue_seasonality)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_revenue_seasonality AS
            WITH monthly AS (
                SELECT
                    order_year                                                       AS year,
                    order_month                                                      AS month_num,
                    TRIM(TO_CHAR(TO_DATE(order_month::TEXT, 'MM'), 'Mon'))           AS month_abbr,
                    SUM(revenue)                                                     AS monthly_revenue
                FROM int.stg_sales
                GROUP BY order_year, order_month
            ),
            yearly AS (
                SELECT year, SUM(monthly_revenue) AS annual_revenue
                FROM monthly GROUP BY year
            )
            SELECT
                m.month_num,
                m.month_abbr,
                ROUND(
                    AVG(m.monthly_revenue / NULLIF(y.annual_revenue, 0)) * 100, 2
                )::NUMERIC(7,2)                AS avg_month_share_pct,
                ROUND(AVG(m.monthly_revenue), 0)::NUMERIC(15,2) AS avg_monthly_revenue,
                MAX(m.monthly_revenue)::NUMERIC(15,2)           AS max_monthly_revenue,
                MIN(m.monthly_revenue)::NUMERIC(15,2)           AS min_monthly_revenue
            FROM monthly m
            JOIN yearly  y USING (year)
            GROUP BY m.month_num, m.month_abbr
            ORDER BY m.month_num;
        """
    },

    # PAGE 5: CAPITAL BUDGETING
    {
        "name": "Presentation: CapEx Cash Flow Schedule (presentation.vw_capex_cashflow_schedule)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_capex_cashflow_schedule AS
            SELECT
                product_id,
                cashflow_year                AS year,
                cashflow_date,
                operational_cashflow,
                assigned_discount_rate,
                flow_type,
                period_t,
                discounted_cashflow,
                cumulative_cashflow
            FROM analytics.mart_product_cashflow
            ORDER BY product_id, cashflow_date;
        """
    },
    {
        "name": "Presentation: CapEx Project Summary (presentation.vw_capex_project_summary)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_capex_project_summary AS
            WITH npv AS (
                SELECT
                    product_id,
                    MAX(assigned_discount_rate)                              AS discount_rate,
                    SUM(operational_cashflow)::NUMERIC(15,2)                 AS total_undiscounted_cf,
                    SUM(discounted_cashflow)::NUMERIC(15,2)                  AS npv,
                    MIN(operational_cashflow)::NUMERIC(15,2)                 AS initial_investment,
                    SUM(CASE WHEN operational_cashflow > 0
                        THEN operational_cashflow ELSE 0 END)::NUMERIC(15,2) AS total_inflows,
                    SUM(CASE WHEN operational_cashflow < 0
                        THEN operational_cashflow ELSE 0 END)::NUMERIC(15,2) AS total_outflows,
                    COUNT(*)                                                 AS num_periods,
                    MIN(cashflow_date)                                       AS project_start,
                    MAX(cashflow_date)                                       AS project_end
                FROM analytics.mart_product_cashflow
                GROUP BY product_id
            ),
            payback AS (
                SELECT DISTINCT ON (product_id)
                    product_id,
                    period_t AS payback_period
                FROM analytics.mart_product_cashflow
                WHERE cumulative_cashflow >= 0
                ORDER BY product_id, period_t
            )
            SELECT
                n.product_id,
                n.project_start,
                n.project_end,
                n.discount_rate,
                n.initial_investment,
                n.total_inflows,
                n.total_outflows,
                n.total_undiscounted_cf,
                n.npv,
                CASE WHEN n.npv > 0 THEN 'Viable' ELSE 'Not Viable' END      AS viability,
                p.payback_period,
                ROUND(
                    (n.npv + ABS(n.initial_investment))
                    / NULLIF(ABS(n.initial_investment), 0), 3
                )::NUMERIC(8,3)                                               AS profitability_index,
                n.num_periods
            FROM npv n
            LEFT JOIN payback p USING (product_id)
            ORDER BY n.npv DESC;
        """
    },
    {
        "name": "Presentation: CapEx Sensitivity (presentation.vw_capex_sensitivity)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_capex_sensitivity AS
            WITH rates(test_rate) AS (
                SELECT unnest(ARRAY[0.03, 0.05, 0.07, 0.08, 0.10, 0.12, 0.15])
            ),
            schedule AS (
                SELECT product_id, operational_cashflow, period_t
                FROM analytics.mart_product_cashflow
            )
            SELECT
                s.product_id,
                r.test_rate                                                   AS discount_rate,
                ROUND(
                    SUM(s.operational_cashflow / POWER(1 + r.test_rate, s.period_t)), 2
                )::NUMERIC(15,2)                                              AS npv,
                CASE
                    WHEN SUM(s.operational_cashflow / POWER(1 + r.test_rate, s.period_t)) > 0
                    THEN 'Positive' ELSE 'Negative'
                END                                                           AS npv_sign
            FROM schedule s
            CROSS JOIN rates r
            GROUP BY s.product_id, r.test_rate
            ORDER BY s.product_id, r.test_rate;
        """
    },

    # PAGE 6: EMPLOYEE ANALYTICS
    {
        "name": "Presentation: Employee Dept Summary (presentation.vw_employee_dept_summary)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_employee_dept_summary AS
            SELECT
                department,
                COUNT(employee_id)                                            AS headcount,
                ROUND(AVG(tenure_years), 2)::NUMERIC(5,2)                     AS avg_tenure_years,
                MIN(tenure_years)::NUMERIC(5,2)                               AS min_tenure_years,
                MAX(tenure_years)::NUMERIC(5,2)                               AS max_tenure_years,
                COUNT(CASE WHEN tenure_years >= 6 THEN 1 END)                 AS senior_count,
                COUNT(CASE WHEN tenure_years < 6  THEN 1 END)                 AS junior_count,
                ROUND(
                    COUNT(CASE WHEN tenure_years >= 6 THEN 1 END)::NUMERIC
                    / NULLIF(COUNT(employee_id), 0) * 100, 1
                )::NUMERIC(5,1)                                               AS senior_pct,
                ROUND(
                    COUNT(employee_id)::NUMERIC
                    / SUM(COUNT(employee_id)) OVER () * 100, 1
                )::NUMERIC(5,1)                                               AS dept_headcount_share_pct
            FROM int.stg_employees
            GROUP BY department
            ORDER BY headcount DESC;
        """
    },
    {
        "name": "Presentation: Employee Tenure Distribution (presentation.vw_employee_tenure_distribution)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_employee_tenure_distribution AS
            SELECT
                department,
                tenure_years,
                CASE
                    WHEN tenure_years <= 1 THEN '0-1 Year'
                    WHEN tenure_years <= 2 THEN '1-2 Years'
                    WHEN tenure_years <= 3 THEN '2-3 Years'
                    WHEN tenure_years <= 4 THEN '3-4 Years'
                    WHEN tenure_years <= 5 THEN '4-5 Years'
                    ELSE '5+ Years'
                END                                                           AS tenure_band,
                COUNT(employee_id)                                            AS headcount
            FROM int.stg_employees
            GROUP BY department, tenure_years, 3
            ORDER BY department, tenure_years;
        """
    },
    {
        "name": "Presentation: Employee Hiring Cohort (presentation.vw_employee_hiring_cohort)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_employee_hiring_cohort AS
            SELECT
                EXTRACT(YEAR FROM start_date)::INT         AS hire_year,
                department,
                COUNT(employee_id)                         AS hires,
                ROUND(AVG(tenure_years), 2)::NUMERIC(5,2)  AS avg_current_tenure
            FROM int.stg_employees
            GROUP BY 1, department
            ORDER BY hire_year, department;
        """
    },
    {
        "name": "Presentation: Employee Roster (presentation.vw_employee_roster)",
        "sql": """
            CREATE OR REPLACE VIEW presentation.vw_employee_roster AS
            SELECT
                employee_id,
                employee_name,
                department,
                start_date,
                tenure_years,
                CASE
                    WHEN tenure_years >= 6 THEN 'Senior'
                    WHEN tenure_years >= 4 THEN 'Mid-Level'
                    ELSE 'Junior'
                END                                        AS seniority_level
            FROM int.stg_employees
            ORDER BY department, employee_name;
        """
    },
]

# 4. Pipeline Execution Engine
#    Each block runs in its own transaction so a failure stops cleanly
#    without rolling back already-deployed blocks.
def run_pipeline():
    logging.info("SPAERO ELT – Transformation Pipeline Starting")

    engine = create_engine(DATABASE_URL)
    total   = len(TRANSFORMATION_BLOCKS)
    success = 0

    for idx, block in enumerate(TRANSFORMATION_BLOCKS, start=1):
        logging.info(f"  [{idx:02d}/{total}] ➔ {block['name']}")
        try:
            with engine.begin() as conn:
                conn.execute(text(block["sql"]))
            logging.info(f"Deployed successfully.")
            success += 1
        except Exception as e:
            logging.error(f"FAILED: {e}")
            logging.info("Transaction auto-rolled back. Halting pipeline.")
            sys.exit(1)

    logging.info(f"Pipeline complete. {success}/{total} blocks deployed.")

if __name__ == "__main__":
    run_pipeline()