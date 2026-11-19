"""Data access for the competition schema: plain functions over an open connection.

Each function runs inside the caller's transaction (see
:func:`diski9.backend.db.transaction`); none commits. Business rules belong to the
service layer added in later Phase 6C stages.
"""
