# Unified Executive Dashboard — API & ETL Pipeline

A FastAPI backend service combined with a three-zone ETL pipeline that ingests data from Salesforce (REST API) and internal Excel exports, transforms it with dbt, and serves it to an executive dashboard.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Running the ETL Pipeline](#running-the-etl-pipeline)
- [Landing Zone — File-Based Datasets](#landing-zone--file-based-datasets)
- [Data Masking](#data-masking)
- [dbt Transforms](#dbt-transforms)
- [Database Migrations](#database-migrations)
- [Running Tests](#running-tests)
- [Adding a New Data Source](#adding-a-new-data-source)
- [API Layer](#api-layer)

---

## Architecture Overview

```
 ┌─────────────────────────────────────────────────────────────────┐
 │  Sources                                                        │
 │  ┌──────────────────┐   ┌──────────────────────────────────┐   │
 │  │  Salesforce REST │   │  Excel Exports (PSA / HR / RM)   │   │
 │  │  (4 datasets)    │   │  (3 datasets)                    │   │
 │  └────────┬─────────┘   └───────────────┬──────────────────┘   │
 └───────────┼─────────────────────────────┼─────────────────────-┘
             │  Python Collectors                │
             ▼                                   ▼
 ┌───────────────────────────────────────────────────────────────┐
 │  raw_zone  (PostgreSQL)  — append-only, bi-temporal upsert    │
 │  sf_accounts_raw  │  sf_contacts_raw  │  sf_opportunities_raw │
 │  sf_activity_history_raw  │  project_extract_raw              │
 │  resource_allocation_raw  │  user_skills_raw                  │
 └───────────────────────────┬───────────────────────────────────┘
                             │  dbt (incremental delete+insert)
                             ▼
 ┌───────────────────────────────────────────────────────────────┐
 │  refined_zone — cleansed, typed, deduplicated                 │
 │  accounts │ contacts │ opportunities │ activity_history       │
 │  projects │ project_allocations │ employees │ employee_skills │
 │  account_name_aliases                                         │
 └───────────────────────────┬───────────────────────────────────┘
                             │  dbt (full table rebuild)
                             ▼
 ┌───────────────────────────────────────────────────────────────┐
 │  trusted_zone — aggregated KPIs for the dashboard             │
 │  account_kpis │ pipeline_summary │ renewal_schedule           │
 │  delivery_status │ team_allocation_summary │ service_line_summary │
 └───────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    FastAPI  (serves trusted_zone)
```

### Key design choices

| Concern | Decision |
|---|---|
| Collector pattern | Template Method (`AbstractCollector`) — subclasses override only `extract()` |
| Dataset config | YAML files under `configs/datasets/` — no Python code change to add a source |
| Bi-temporal storage | Every raw row carries `TT_IN_Z / TT_OUT_Z` (transaction time) + `VT_IN_Z / VT_OUT_Z` (valid time) |
| Incremental detection | Watermark cursor stored in `raw_zone.collector_watermark`; `--full-load` resets it |
| dbt transforms | `dbt-core` (free, Apache 2.0) — refined = incremental, trusted = full table |
| Data masking | Deterministic HMAC-SHA256 pseudonymisation at collection time; opt-in via `--mask-data` |

---

## Project Structure

```
unified-executive-dashboard-api/
│
├── app/
│   ├── main.py                    # FastAPI app, CORS, router registration
│   ├── config.py                  # Pydantic Settings (loads .env)
│   ├── database.py                # SQLAlchemy engine + SessionLocal
│   ├── dependencies.py            # get_db() FastAPI dependency
│   ├── models/base.py             # DeclarativeBase + AuditMixin
│   ├── schemas/common.py          # AuditSchema, PaginatedResponse[T]
│   ├── repositories/base.py       # BaseRepository[M] — CRUD + soft_delete
│   ├── services/base.py           # BaseService[R] — business logic wrapper
│   ├── routers/health.py          # GET /api/v1/health
│   └── collectors/
│       ├── config.py              # Pydantic DataSetConfig (YAML root model)
│       ├── base.py                # AbstractCollector — Template Method
│       ├── file_collector.py      # Reads Excel / CSV / JSON from landing dir
│       ├── rest_collector.py      # OAuth2 / API-key REST with pagination + watermark
│       └── runner.py              # CollectorRunner — orchestrates all datasets
│
├── configs/
│   └── datasets/                  # One YAML file per dataset
│       ├── salesforce_accounts.yaml
│       ├── salesforce_contacts.yaml
│       ├── salesforce_opportunities.yaml
│       ├── salesforce_activity.yaml
│       ├── project_extract.yaml
│       ├── resource_allocation.yaml
│       └── user_skills.yaml
│
├── db/
│   ├── flyway.conf                # Flyway config (points at PostgreSQL)
│   └── migrations/
│       ├── V1__initial_schema.sql
│       ├── ...
│       ├── V8__collector_watermark.sql   # ingestion_batch + collector_watermark tables
│       └── V9__salesforce_schema_update.sql
│
├── dbt/
│   ├── dbt_project.yml            # dbt project config
│   ├── profiles.yml               # Reads PG* env vars
│   ├── macros/
│   │   └── bitemporal_upsert.sql  # supersede_stale_rows macro
│   └── models/
│       ├── sources.yml            # raw_zone tables declared as dbt sources
│       ├── refined_zone/          # 9 incremental models
│       └── trusted_zone/          # 6 full-table KPI models
│
├── tests/
│   ├── conftest.py                # mock_db, mock_sf_api, SF config fixtures, integration DB fixtures
│   ├── fixtures/
│   │   ├── salesforce_fixtures.py # SF REST API response factories (7 scenarios × 4 datasets)
│   │   └── file_fixtures.py       # openpyxl Excel generators (project-extract + resource-allocation)
│   ├── unit/
│   │   ├── test_rest_collector.py # 47 tests — field resolution, delta batches, landing file
│   │   ├── test_watermark.py      # 9 tests  — load/save/reset watermark, full-load flag
│   │   ├── test_file_collector.py # 15 tests — initial load, delta, archive, pre-load checks
│   │   └── test_masking.py        # 34 tests — HMAC format, determinism, join preservation
│   └── integration/
│       └── test_salesforce_pipeline.py  # 11 tests — real DB, skipped when TEST_DATABASE_URL unset
│
├── scripts/
│   └── generate_lineage.py        # Generates dbt lineage HTML
│
├── run_pipeline.py                # Unified ETL entry point (collectors + dbt)
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Getting Started

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | |
| PostgreSQL | 14+ | Local or Docker |
| Flyway CLI | any | For running DB migrations |
| dbt-postgres | 1.8+ | `pip install dbt-postgres` (dev only) |

### Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd unified-executive-dashboard-api
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

**2. Install dependencies**

```bash
pip install -r requirements-dev.txt
pip install dbt-postgres          # required for dbt transform step
```

**3. Configure environment variables**

```bash
cp .env.example .env
# Edit .env — minimum required vars are DATABASE_URL and Salesforce credentials
```

**4. Run database migrations**

```bash
flyway -configFiles=db/flyway.conf migrate
```

**5. Create landing directories** (file-based datasets)

```bash
mkdir -p ~/data/landing/project-extract
mkdir -p ~/data/landing/resource-allocation
mkdir -p ~/data/landing/user-skills
```

**6. Verify setup**

```bash
uvicorn app.main:app --reload
# API health check:  http://localhost:8000/api/v1/health
```

---

## Environment Variables

Copy `.env.example` to `.env` and populate the values below.

### API / Database

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | — | Yes | PostgreSQL connection string, e.g. `postgresql://user:pass@localhost:5432/dashboard` |
| `APP_NAME` | `Unified Executive Dashboard API` | No | Application display name |
| `APP_VERSION` | `0.1.0` | No | Application version |
| `DEBUG` | `false` | No | Enable FastAPI debug mode |
| `API_V1_PREFIX` | `/api/v1` | No | URL prefix for all API routes |
| `ALLOWED_ORIGINS` | `["*"]` | No | CORS allowed origins (JSON array) |

### Salesforce

| Variable | Required | Description |
|---|---|---|
| `SALESFORCE_INSTANCE_URL` | Yes | Salesforce instance base URL, e.g. `https://myorg.my.salesforce.com` |
| `SALESFORCE_TOKEN_URL` | Yes | OAuth2 token endpoint, e.g. `https://login.salesforce.com/services/oauth2/token` |
| `SALESFORCE_CLIENT_ID` | Yes | Connected App consumer key |
| `SALESFORCE_CLIENT_SECRET` | Yes | Connected App consumer secret |

### Pipeline

| Variable | Default | Description |
|---|---|---|
| `LANDING_BASE_PATH` | `~/data/landing` | Root directory for file-based dataset drops. Overrides the `--base-path` CLI default. |
| `MASKING_SECRET_KEY` | — | HMAC secret for data masking. Required when running with `--mask-data`. Use a long random string — never commit to source control. |

### dbt (PostgreSQL connection for transforms)

These are read by `dbt/profiles.yml` — they can be the same as `DATABASE_URL` components.

| Variable | Description |
|---|---|
| `PGHOST` | PostgreSQL host |
| `PGPORT` | PostgreSQL port (default `5432`) |
| `PGDATABASE` | Database name |
| `PGUSER` | Database user |
| `PGPASSWORD` | Database password |

### Integration tests

| Variable | Description |
|---|---|
| `TEST_DATABASE_URL` | PostgreSQL URL for integration tests. Tests are auto-skipped when not set. |

---

## Running the ETL Pipeline

The unified entry point is `run_pipeline.py`. It runs two sequential steps:

1. **Step 1 — Collectors**: Python collectors write raw data into `raw_zone` tables.
2. **Step 2 — dbt**: dbt builds `refined_zone` (incremental) and `trusted_zone` (full rebuild).

### Common invocations

```bash
# Full pipeline — all datasets, then dbt
python run_pipeline.py

# Collectors only (skip dbt)
python run_pipeline.py --skip-dbt

# dbt only (skip collectors)
python run_pipeline.py --skip-collectors

# Specific datasets only
python run_pipeline.py --skip-dbt --datasets project-extract,resource-allocation

# Full historical reload (reset watermarks, re-ingest from scratch)
python run_pipeline.py --full-load

# Full reload of one dataset only
python run_pipeline.py --full-load --datasets salesforce-accounts

# Run with data masking enabled
python run_pipeline.py --mask-data

# Target a specific dbt profile (default: dev)
python run_pipeline.py --dbt-target prod
```

### All CLI flags

| Flag | Default | Description |
|---|---|---|
| `--datasets` | all enabled | Comma-separated dataset names to run. E.g. `project-extract,user-skills`. |
| `--base-path` | `~/data/landing` | Root directory prepended to each file dataset's `landing_dir`. |
| `--skip-collectors` | false | Skip Step 1 (raw ingestion). |
| `--skip-dbt` | false | Skip Step 2 (dbt transforms). |
| `--dbt-target` | `dev` | dbt profile target to use. |
| `--full-load` | false | Delete stored watermarks before run — forces a full historical reload of all REST datasets. |
| `--mask-data` | false | Apply HMAC pseudonymisation to PII columns annotated with `mask_type` in their YAML config. Requires `MASKING_SECRET_KEY` env var. |

### Dataset names

| Name | Type | Source |
|---|---|---|
| `salesforce-accounts` | REST | Salesforce Account object |
| `salesforce-contacts` | REST | Salesforce Contact object |
| `salesforce-opportunities` | REST | Salesforce Opportunity object |
| `salesforce-activity` | REST | Salesforce Task object |
| `project-extract` | File | `Project_Extract_*.xlsx` |
| `resource-allocation` | File | `Resource_Allocation_*.xlsx` |
| `user-skills` | File | `User_Skill_Data_*.xlsx` |

---

## Landing Zone — File-Based Datasets

File-based collectors look for Excel files in subdirectories of `--base-path` (default: `~/data/landing`).

### Directory layout

```
~/data/landing/
├── project-extract/
│   └── Project_Extract_<anything>.xlsx      ← drop file here
├── resource-allocation/
│   └── Resource_Allocation_<anything>.xlsx  ← drop file here
└── user-skills/
    └── User_Skill_Data_<anything>.xlsx       ← drop file here
```

### File naming rules

| Dataset | Pattern | Example |
|---|---|---|
| `project-extract` | `Project_Extract_*.xlsx` | `Project_Extract_2024-04-17.xlsx` |
| `resource-allocation` | `Resource_Allocation_*.xlsx` | `Resource_Allocation_Apr2026.xlsx` |
| `user-skills` | `User_Skill_Data_*.xlsx` | `User_Skill_Data_3rdApr26.xlsx` |

- The `*` wildcard matches any suffix — date stamps, version numbers, etc.
- When multiple files match, the **most recently modified** file is picked.
- After a successful load, files are **moved to an archive directory** (unless the landing dir is inside the project root, which suppresses archiving to protect checked-in test fixtures).

### Archive directories

| Dataset | Archive path |
|---|---|
| `project-extract` | `<project_root>/data/archive/project-extract/` |
| `resource-allocation` | `<project_root>/data/archive/resource-allocation/` |
| `user-skills` | `<project_root>/data/archive/user-skills/` |

### Override base path

```bash
# Use a different root for all file datasets
python run_pipeline.py --base-path /mnt/shared/drop-zone

# Or set permanently via env var
export LANDING_BASE_PATH=/mnt/shared/drop-zone
```

---

## Data Masking

The pipeline supports **deterministic HMAC-SHA256 pseudonymisation** of PII columns at collection time, before data is written to the database. This is Approach A — masking at the collector layer.

### How it works

- Columns annotated with `mask_type` in their YAML config are pseudonymised when `--mask-data` is active.
- The same input value + same secret key always produces the same output token, preserving cross-dataset joins.
- SF IDs, watermark columns, status enums, and date fields are **never masked**.

### Enabling masking

```bash
export MASKING_SECRET_KEY="<long-random-string>"   # required; never commit this
python run_pipeline.py --mask-data
```

The pipeline aborts with exit code 1 if `--mask-data` is set but `MASKING_SECRET_KEY` is absent.

### Mask types and output format

| `mask_type` | Output format | Example output |
|---|---|---|
| `person_name` | `Person-<10 hex chars>` | `Person-3f8a1c02d7` |
| `company_name` | `Company-<10 hex chars>` | `Company-7b2e9af013` |
| `email` | `<8 hex chars>@masked.invalid` | `a1b2c3d4@masked.invalid` |
| `phone` | `+1-555-<4 digits>` | `+1-555-3821` |
| `employee_id` | `EMP-<10 hex chars>` | `EMP-9c4d1e22f8` |
| `amount` | Rounded to nearest 100 000 | `800000` |
| `free_text` | `[REDACTED]` | `[REDACTED]` |

### Join-critical fields — consistent mask_type across datasets

The following fields use the **same `mask_type`** so that joins still work after masking:

| Join | Fields | `mask_type` |
|---|---|---|
| Account name | `accounts.name`, `contacts.account_name`, `opportunities.account_name`, `project_extract.customer_name`, `resource_allocation.customer_name` | `company_name` |
| Employee ID | `resource_allocation.employee_number`, `user_skills.employee_id` | `employee_id` |
| Email | `contacts.email`, `user_skills.email_id` | `email` |

---

## dbt Transforms

dbt builds two zones on top of `raw_zone`:

### refined_zone (incremental delete+insert)

Cleansed, typed, and deduplicated views of each raw source.

| Model | Source |
|---|---|
| `accounts` | `sf_accounts_raw` |
| `contacts` | `sf_contacts_raw` |
| `opportunities` | `sf_opportunities_raw` |
| `activity_history` | `sf_activity_history_raw` |
| `projects` | `project_extract_raw` |
| `project_allocations` | `resource_allocation_raw` |
| `employees` | `user_skills_raw` |
| `employee_skills` | `user_skills_raw` |
| `account_name_aliases` | cross-source name normalisation |

### trusted_zone (full table rebuild each run)

Aggregated KPI tables consumed by the dashboard API.

| Model | Description |
|---|---|
| `account_kpis` | Revenue, NPS, open opportunities per account |
| `pipeline_summary` | Opportunity pipeline by stage and vertical |
| `renewal_schedule` | Upcoming renewals from opportunity close dates |
| `delivery_status` | Project delivery health from project extract |
| `team_allocation_summary` | Headcount and allocation % by project/account |
| `service_line_summary` | Revenue and headcount by service line |

### dbt commands

```bash
# Build all models
dbt run --profiles-dir dbt --project-dir dbt

# Run dbt tests
dbt test --profiles-dir dbt --project-dir dbt

# Generate and serve data lineage docs
dbt docs generate --profiles-dir dbt --project-dir dbt
dbt docs serve    --profiles-dir dbt --project-dir dbt --port 8080

# Or use run_pipeline.py (runs collectors first, then dbt)
python run_pipeline.py --dbt-target prod
```

### Generate lineage diagram

```bash
python scripts/generate_lineage.py
# Output: docs/lineage.html
```

---

## Database Migrations

SQL-first migrations managed by Flyway. Migration files live in `db/migrations/` and follow the naming convention `V{n}__description.sql`.

```bash
# Apply all pending migrations
flyway -configFiles=db/flyway.conf migrate

# Check migration status
flyway -configFiles=db/flyway.conf info
```

### Migration history

| Version | Description |
|---|---|
| V1 | Initial schema — `set_updated_at()` trigger function |
| V2–V7 | Domain model tables |
| V8 | `ingestion_batch` + `collector_watermark` tables; drops hardcoded source_system CHECK |
| V9 | Salesforce schema update — adds columns to all 4 SF raw + refined tables |

---

## Running Tests

### Unit tests (no database required)

```bash
pytest tests/ --ignore=tests/integration
```

### Integration tests (requires a live PostgreSQL instance)

```bash
TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/test_db" pytest tests/integration/ -v
```

Integration tests are automatically skipped when `TEST_DATABASE_URL` is not set.

### Test coverage summary

| File | Tests | What it covers |
|---|---|---|
| `tests/test_health.py` | 1 | FastAPI health endpoint |
| `tests/unit/test_rest_collector.py` | 47 | Field resolution, dot-notation, pagination, 5 delta batches, landing file JSON/CSV/error |
| `tests/unit/test_watermark.py` | 9 | Load/save/reset watermark, full-load flag |
| `tests/unit/test_file_collector.py` | 15 | Initial load, delta scenarios, archive behaviour, pre-load quality checks |
| `tests/unit/test_masking.py` | 35 | HMAC format per type, determinism, join preservation, missing key guard |
| `tests/integration/test_salesforce_pipeline.py` | 10 | Full pipeline with real DB — bi-temporal upsert, version chains, watermark persistence |
| **Total** | **117** | |

---

## Adding a New Data Source

### File-based source (Excel / CSV)

1. **Add a YAML config** — `configs/datasets/my_source.yaml`

   ```yaml
   name: my-source
   type: file
   enabled: true
   source_system: my-source
   target:
     schema: raw_zone
     table: my_source_raw
   natural_key:
     columns: [record_id]
   file:
     landing_dir: my-source/
     pattern: "My_Source_Export_*.xlsx"
     format: excel
     archive_after_load: true
     archive_dir: data/archive/my-source/
   load:
     strategy: upsert_bitemporal
   columns:
     - source: "Record ID"
       target: record_id
     - source: "Name"
       target: name
       mask_type: company_name   # optional — annotate PII columns
   ```

2. **Add a Flyway migration** — `db/migrations/V{n}__add_my_source_table.sql`

3. **Create landing directory**

   ```bash
   mkdir -p ~/data/landing/my-source
   ```

4. **Add a dbt refined_zone model** — `dbt/models/refined_zone/my_source.sql`

No Python code changes are needed.

### REST-based source

Same steps as above, but use `type: rest` and add a `rest:` block with `base_url`, `auth`, `endpoint`, `pagination`, and `watermark` settings. See `configs/datasets/salesforce_accounts.yaml` as a reference.

---

## API Layer

The FastAPI service runs on top of the `trusted_zone` tables and exposes dashboard KPIs.

```bash
uvicorn app.main:app --reload
```

| URL | Description |
|---|---|
| `http://localhost:8000/api/v1/health` | Health check |
| `http://localhost:8000/api/v1/docs` | Interactive Swagger UI |
| `http://localhost:8000/api/v1/redoc` | ReDoc documentation |

### Adding a new API endpoint

| Step | File | Purpose |
|---|---|---|
| 1 | `app/models/your_entity.py` | SQLAlchemy model — mix in `AuditMixin` |
| 2 | `app/schemas/your_entity.py` | Pydantic request/response schemas |
| 3 | `app/repositories/your_entity.py` | Extend `BaseRepository` |
| 4 | `app/services/your_entity.py` | Extend `BaseService` — add domain logic here |
| 5 | `app/routers/your_entity.py` | FastAPI router — inject DB via `Depends(get_db)` |
| 6 | Register in `app/main.py` | `app.include_router(your_entity.router, prefix=settings.api_v1_prefix)` |
