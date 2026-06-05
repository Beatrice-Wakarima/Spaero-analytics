# SPAERO Revenue Analysis Pipeline

> End-to-end ELT pipeline and Power BI dashboard for Finance & Sales analytics.  
> Built with Python · PostgreSQL · Docker · Power BI

## Dashboard Preview

| Page | Focus |
|---|---|
| Executive Overview | Revenue vs target, YoY growth, segment split |
| Customer Analytics | Top customers, country map, RFM segmentation |
| Product Analytics | Revenue by product, pricing vs cost, segment matrix |
| Revenue Forecast | Actual vs target, 3-year projection, seasonality |
| Capital Budgeting | NPV, payback period, sensitivity analysis |
| Employee Analytics | Headcount, tenure distribution, hiring cohort |


## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SOURCE LAYER                                  │
│  Capital_Budgeting.xlsx  Employee_Fact.xlsx                          │
│  revenue_targets.xlsx    spaero_sales.xlsx                           │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ extract_load.py
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         RAW LAYER  (raw.*)                           │
│  Exact copy of source data — truncate & reload on every run         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ transform.py
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      STAGING LAYER  (int.*)                          │
│  Typed, sanitised views — snake_case columns, derived date fields   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ANALYTICS LAYER  (analytics.*)                    │
│  Dims: dim_customers  dim_products  dim_date                        │
│  Marts: mart_annual_performance  mart_monthly_sales                 │
│         mart_customer_sales  mart_product_sales                     │
│         mart_product_cashflow                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PRESENTATION LAYER  (presentation.*)                │
│  22 views — one per dashboard page/visual group                     │
│  Power BI connects here only                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                        Power BI Dashboard
```


## Project Structure

```
REVENUE ANALYSIS/
├── data/                        ← Source Excel files (git-ignored)
│   ├── Capital_Budgeting.xlsx
│   ├── Employee_Fact.xlsx
│   ├── revenue_targets.xlsx
│   └── spaero_sales.xlsx
│
├── scripts/
│   ├── extract_load.py          ← Step 1: Excel → raw.*
│   ├── transform.py             ← Step 2: raw.* → int.* → analytics.* → presentation.*
│   └── inspect_views.py        ← Step 3: Validate all 28 objects
│
├── .env                         ← Credentials (never committed)
├── .env.example                 ← Credential template
├── .gitignore
├── docker-compose.yml           ← Two services: warehouse + pipeline
├── Dockerfile                   ← Python 3.11 pipeline image
├── requirements.txt
└── README.md
```

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- Excel source files in `data/`

### 1. Clone the repository

```bash
git clone https://github.com/Beatrice-Wakarima/spaero-analytics.git
cd REVENUE ANALYSIS
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DB_USER=spaero_user
DB_PASSWORD=your_strong_password
DB_HOST=postgres_warehouse
DB_PORT=5432
DB_NAME=spaero_dw
DB_HOST_PORT=5439
```

### 3. Add source data

```bash
mkdir -p data
cp data/
       
```

### 4. Run the pipeline

```bash
docker compose up --build
```

Expected output:

```
spaero_elt | [INFO]  SPAERO ELT – Extract & Load Pipeline Starting
spaero_elt | [INFO]  raw.spaero_sales_sales_fact  (6,320 rows)  [initial_load]
spaero_elt | [INFO]  raw.spaero_sales_customer_dim  (141 rows)  [initial_load]
spaero_elt | [INFO]  Extract & Load pipeline complete.
spaero_elt | [INFO]  SPAERO ELT – Transformation Pipeline Starting
spaero_elt | [INFO]  [01/36] ➔ Extensions & Schema Initialisation 
spaero_elt | [INFO]  ...
spaero_elt | [INFO]  Pipeline complete. 36/36 blocks deployed.
spaero_elt exited with code 0
```

### 5. Connect Power BI

| Setting | Value |
|---|---|
| Server | `localhost` |
| Port | `5439` |
| Database | your `DB_NAME` |
| Schema | `presentation` |
| Mode | Import |

## Refresh Data

Drop updated Excel files into `data/` then:

```bash
docker compose run --rm elt_pipeline
```

Then click **Refresh** in Power BI Desktop.


## Docker Services

| Service | Image | Role | Port |
|---|---|---|---|
| `postgres_warehouse` | `postgres:15-alpine` | Data warehouse | `5439` (host) |
| `elt_pipeline` | Custom Python 3.11 | Runs pipeline, exits | — |

Both services share `spaero_network` (bridge) — `elt_pipeline` resolves `postgres_warehouse` by hostname internally on port `5432`.

> **Note:** If you have a local PostgreSQL instance running on `5432`, the Docker warehouse maps to `5439` on your host to avoid conflict.


## Data Model

### Source Files

| File | Sheet | Rows | Description |
|---|---|---|---|
| `spaero_sales.xlsx` | Sales_Fact | 6,320 | Orders 2015–2021 |
| `spaero_sales.xlsx` | Customer_Dim | 141 | Customer segments + countries |
| `revenue_targets.xlsx` | Revenue Targets | 7 | Annual targets 2015–2021 |
| `Capital_Budgeting.xlsx` | Cash Flow | — | Project cash flows |
| `Employee_Fact.xlsx` | Sheet1 | — | Employee roster + tenure |

### Key Metrics

| Metric | Value |
|---|---|
| Date range | 2015-01-02 → 2021-12-30 |
| Total revenue | ~$757M |
| Total profit | ~$243M |
| Total orders | 6,320 |
| Customers | 130 |
| Products | 4 (AD58008, FB71015, JK95673, LO84601) |
| Segments | Government, Enterprise, Channel Partners, Midmarket |
| Countries | 30+ |
| Capital projects | 2 (TC25147, ZB95486) |

## Presentation Views

### Page 1 — Executive Overview
| View | Description |
|---|---|
| `vw_exec_kpi_scorecard` | Annual KPIs — revenue, profit, margin, target attainment, YoY growth |
| `vw_exec_monthly_trend` | Monthly revenue and profit with YTD cumulative |
| `vw_exec_segment_summary` | Revenue by customer segment with year column for cross-filtering |

### Page 2 — Customer Analytics
| View | Description |
|---|---|
| `vw_customer_performance` | Per-customer revenue, orders, AOV, active years |
| `vw_customer_yearly_revenue` | Customer revenue trend year over year |
| `vw_customer_country_summary` | Revenue and margin by country and segment |
| `vw_customer_rfm` | RFM scoring — Champions, Loyal, At Risk, Lost |

### Page 3 — Product Analytics
| View | Description |
|---|---|
| `vw_product_performance` | Revenue, margin, avg prices per product |
| `vw_product_monthly_trend` | Product revenue over time |
| `vw_product_segment_matrix` | Product × segment cross-tab with year filter |
| `vw_product_pricing` | Actual vs target vs manufacturing price per year |

### Page 4 — Revenue Forecast
| View | Description |
|---|---|
| `vw_revenue_actual_vs_target` | Actual vs target with On/Below Target status |
| `vw_revenue_growth` | YoY growth % and CAGR using LN/EXP |
| `vw_revenue_forecast_linear` | 3-year linear regression projection |
| `vw_revenue_seasonality` | Monthly share of annual revenue |

### Page 5 — Capital Budgeting
| View | Description |
|---|---|
| `vw_capex_cashflow_schedule` | Discounted cash flows per period |
| `vw_capex_project_summary` | NPV, payback period, profitability index |
| `vw_capex_sensitivity` | NPV at 7 discount rates (3%–15%) |

### Page 6 — Employee Analytics
| View | Description |
|---|---|
| `vw_employee_dept_summary` | Headcount, avg tenure, senior % by department |
| `vw_employee_tenure_distribution` | Tenure band histogram by department |
| `vw_employee_hiring_cohort` | Hires by year and department |
| `vw_employee_roster` | Full roster — drill-through target from dept chart |

## Useful Commands

```bash
# Run full pipeline
docker compose run --rm elt_pipeline

# Inspect all views and row counts
docker compose run --rm elt_pipeline python inspect_views.py

# Inspect one dashboard page
docker compose run --rm elt_pipeline python inspect_views.py --group "customer"

# Inspect one specific view
docker compose run --rm elt_pipeline python inspect_views.py --view presentation.vw_capex_project_summary

# View pipeline logs
docker logs spaero_elt

# Connect to database directly
docker exec -it spaero_warehouse psql -U your_user -d your_dbname

# Stop everything
docker compose down

# Stop and wipe database volume
docker compose down -v

# Rebuild after code changes
docker compose down && docker compose up --build

# Fix corrupted Docker cache
docker system prune -af && docker compose up --build
```


## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Connection refused` | DB_PORT set to host port inside Docker | Set `DB_PORT=5432` in `.env` |
| `column does not exist` | Column name has special chars | Use double quotes: `"tenure_(years)"` |
| `ROUND(double precision)` | Postgres ROUND needs NUMERIC | Cast first: `(expr)::NUMERIC` |
| `cannot change name of view column` | CREATE OR REPLACE can't reorder columns | Split into DROP CASCADE + CREATE |
| `relation does not exist` | DROP CASCADE removed dependent views | Split DROP and CREATE into separate blocks |
| `parent snapshot does not exist` | Corrupted Docker build cache | `docker system prune -af` |
| Duplicate rows on re-run | `if_exists="append"` without truncate | Pipeline uses TRUNCATE-then-append ✔ |

## Tech Stack

| Layer | Technology |
|---|---|
| Source data | Microsoft Excel (.xlsx) |
| Orchestration | Python 3.11 |
| Database | PostgreSQL 15 (Docker) |
| ORM / DB connector | SQLAlchemy + psycopg2 |
| Data processing | pandas + openpyxl |
| Containerisation | Docker + Docker Compose |
| Dashboard | Microsoft Power BI Desktop |
| Documentation | Obsidian |
| Version control | Git + GitHub |

## Licence

MIT — free to use, modify and distribute.

## Author

Built by Beatrice — Data Engineer  
[GitHub](https://github.com/Beatrice-Wakarima) · [LinkedIn](https://www.linkedin.com/in/beatricewwanjiru)
