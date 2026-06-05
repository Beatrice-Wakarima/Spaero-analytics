
import os
import sys
import glob
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 2. Load Environment Variables
load_dotenv()

DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "postgres_warehouse")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME")

DATA_DIR = "data"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:5432/{DB_NAME}"

# 3. Connection Probe
def test_connection(engine):
    logging.info("Running connection probe...")
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1;"))
            logging.info(f"Connection successful, probe returned: {result.scalar()}")
    except Exception as e:
        logging.error(f"Connection failed: {e}")
        sys.exit(1)

# 4. Metadata Tracking
def ensure_metadata_table(engine):
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE SCHEMA IF NOT EXISTS raw;
            CREATE TABLE IF NOT EXISTS raw.ingestion_log (
                id          SERIAL PRIMARY KEY,
                file_name   TEXT,
                sheet_name  TEXT,
                table_name  TEXT,
                row_count   INT,
                run_mode    TEXT,
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

def log_ingestion(engine, file_name, sheet_name, table_name, row_count, run_mode):
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO raw.ingestion_log
                    (file_name, sheet_name, table_name, row_count, run_mode)
                VALUES
                    (:file_name, :sheet_name, :table_name, :row_count, :run_mode)
            """),
            {
                "file_name":  file_name,
                "sheet_name": sheet_name,
                "table_name": table_name,
                "row_count":  row_count,
                "run_mode":   run_mode,
            }
        )

# 5. String / Column Sanitization Helper
def clean_string(s):
    """Sanitizes strings to database-friendly table and column names."""
    return (
        str(s).strip().lower()
        .replace(' ', '_')
        .replace('-', '_')
        .replace('.', '_')
        .replace('/', '_')
        .replace('$', '')
    )

def sanitize_columns(df):
    df.columns = [clean_string(col) for col in df.columns]
    return df

# 6. Validation Layer
def validate_dataframe(df, table_name):
    if df.empty:
        logging.warning(f"Validation failed: {table_name} is empty.")
        return False
    if df.isnull().all().any():
        logging.warning(f"Validation warning: {table_name} has entirely null columns.")
    return True

def table_exists(engine, table_name: str) -> bool:
    sql = text("""
        SELECT EXISTS (
            SELECT 1
            FROM   information_schema.tables
            WHERE  table_schema = 'raw'
            AND    table_name   = :tname
        );
    """)
    with engine.connect() as conn:
        return conn.execute(sql, {"tname": table_name}).scalar()


def load_dataframe(engine, df, clean_table_name: str) -> str:
    """
    Load df into raw.<clean_table_name> idempotently.
    Returns the run_mode string used ('full_refresh' or 'initial_load').
    """
    if table_exists(engine, clean_table_name):
        with engine.begin() as conn:
            conn.execute(text(f'TRUNCATE TABLE raw."{clean_table_name}";'))
        logging.info(f"Truncated raw.{clean_table_name} (full refresh).")
        run_mode = "full_refresh"
    else:
        run_mode = "initial_load"

    df.to_sql(
        name=clean_table_name,
        con=engine,
        schema="raw",
        if_exists="append",   
        index=False,
        chunksize=1000,
    )
    return run_mode

# 8. Workbook Processing
def process_workbook(engine, file_path):
    file_name           = os.path.basename(file_path)
    base_workbook_name  = os.path.splitext(file_name)[0]

    logging.info(f"Opening workbook: {file_name}")

    try:
        excel_file = pd.ExcelFile(file_path, engine="openpyxl")

        for sheet_name in excel_file.sheet_names:
            raw_table_name  = f"{base_workbook_name}_{sheet_name}"
            clean_table_name = clean_string(raw_table_name)

            logging.info(
                f"   ➔  Sheet: '{sheet_name}'  →  raw.{clean_table_name}"
            )

            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl")
                df = sanitize_columns(df)

                if not validate_dataframe(df, clean_table_name):
                    continue

                run_mode = load_dataframe(engine, df, clean_table_name)

                logging.info(
                    f" raw.{clean_table_name}  ({len(df):,} rows)  [{run_mode}]"
                )
                log_ingestion(
                    engine, file_name, sheet_name,
                    clean_table_name, len(df), run_mode
                )

            except Exception as e:
                logging.error(
                    f"Failed to process sheet '{sheet_name}' in {file_name}: {e}"
                )

        logging.info(f"Completed workbook: {file_name}")

    except Exception as e:
        logging.error(f"Failed to open workbook {file_name}: {e}")

# 9. Main Ingestion Pipeline
def ingest_all_excel_files():
    logging.info("  SPAERO ELT – Extract & Load Pipeline Starting")

    engine = create_engine(DATABASE_URL)
    test_connection(engine)
    ensure_metadata_table(engine)

    excel_files = glob.glob(os.path.join(DATA_DIR, "*.xlsx"))
    if not excel_files:
        logging.warning(f"No Excel (.xlsx) files found in: {DATA_DIR}")
        return

    logging.info(f"Found {len(excel_files)} source workbook(s) for ingestion.")

    for file_path in sorted(excel_files):
        process_workbook(engine, file_path)

    logging.info("  Extract & Load pipeline complete.")

# 10. Entry Point
if __name__ == "__main__":
    ingest_all_excel_files()