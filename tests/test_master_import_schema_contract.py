from tatemono_map.building_registry.ingest_master_import import (
    MASTER_COLUMNS,
    MASTER_COLUMNS_WITH_FILE,
)
from tatemono_map.cli.pdf_batch_run import FINAL_SCHEMA, MASTER_IMPORT_SCHEMA


def test_final_schema_matches_ingest_master_columns_with_file() -> None:
    assert tuple(FINAL_SCHEMA) == MASTER_COLUMNS_WITH_FILE


def test_master_import_schema_matches_ingest_master_columns() -> None:
    assert tuple(MASTER_IMPORT_SCHEMA) == MASTER_COLUMNS
