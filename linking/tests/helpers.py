"""Build synthetic session rows for the linking tests (documentation IP ranges only)."""

import pandas as pd

from linking.sessions import SESSION_COLUMNS, SIGNATURE_COLUMNS


def session(key: str, user: str, signature: str = "sig", **overrides) -> dict:
    row = {column: None for column in SESSION_COLUMNS}
    row.update(
        {
            "session_key": key,
            "run_id": key,
            "label_user": user,
            "label_agent": "claude-code",
            "site": "site1",
            "is_browser": False,
            "ip": "192.0.2.1",
            "ip_prefix": "192.0.2.0/24",
            "tools": "curl",
            "t_start": 0.0,
            "max_gap_s": 3.0,
            "submit_wait_s": 3.0,
            **{column: (signature,) for column in SIGNATURE_COLUMNS},
        }
    )
    row.update(overrides)
    return row


def sessions(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=SESSION_COLUMNS)
