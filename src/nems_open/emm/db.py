"""Read-only access to EMM's input database (NEMS_INPUT.db)."""

import sqlite3
from functools import lru_cache

import numpy as np

from nems_open.paths import INPUT

DB_PATH = INPUT / "emm" / "emm_db" / "NEMS_INPUT.db"


@lru_cache(maxsize=1)
def connection() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)


@lru_cache(maxsize=None)
def table(name: str) -> dict[str, np.ndarray]:
    """A whole table as {column: array}. Text columns stay str, numbers become float64/int64."""
    cur = connection().execute(f'SELECT * FROM "{name}"')
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    out = {}
    for i, col in enumerate(cols):
        values = [r[i] for r in rows]
        if all(isinstance(v, int) for v in values):
            out[col] = np.array(values, dtype=np.int64)
        elif all(isinstance(v, (int, float)) for v in values):
            out[col] = np.array(values, dtype=np.float64)
        else:
            out[col] = np.array([("" if v is None else str(v)) for v in values], dtype=object)
    return out
