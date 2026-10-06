"""Runs a connector: first a full sync (and prune), then incremental syncs from a stored cursor."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from clearance.connectors.gdrive import GoogleDriveConnector
from clearance.connectors.sharepoint import SharePointConnector
from clearance.db.models import SyncState
from clearance.db.session import Database
from clearance.index import IndexReport, IndexWriter, SourceDocument

__all__ = ["IndexReport", "get_cursor", "set_cursor", "sync_gdrive", "sync_sharepoint"]


def get_cursor(db: Database, connector: str) -> str | None:
    with db.owner_session() as session:
        return session.scalar(select(SyncState.cursor).where(SyncState.connector == connector))


def set_cursor(db: Database, connector: str, cursor: str) -> None:
    with db.owner_session() as session:
        state = session.get(SyncState, connector)
        if state is None:
            session.add(SyncState(connector=connector, cursor=cursor))
        else:
            state.cursor = cursor
            state.updated_at = datetime.now(UTC)


def _apply(
    writer: IndexWriter, source: str, report: IndexReport, upserts: list[SourceDocument], removed: list[str]
) -> None:
    for document in upserts:
        try:
            report.results.append(writer.upsert(document))
        except ValueError as exc:
            report.errors.append(f"{document.external_id}: {exc}")
    for external_id in removed:
        report.deleted += int(writer.delete_by_external_id(source, external_id))


def sync_gdrive(
    db: Database, writer: IndexWriter, connector: GoogleDriveConnector, *, full: bool = False
) -> IndexReport:
    cursor = None if full else get_cursor(db, connector.source)
    if cursor is None:
        start = connector.start_cursor()  # taken before listing, so changes made during the listing are replayed
        report = writer.sync_full(connector.source, list(connector.documents()), prune=True)
        set_cursor(db, connector.source, start)
        return report
    report = IndexReport()
    batch = connector.changes(cursor, known_ids=writer.external_ids(connector.source))
    _apply(writer, connector.source, report, batch.upserts, batch.removed)
    set_cursor(db, connector.source, batch.cursor)
    return report


def sync_sharepoint(
    db: Database, writer: IndexWriter, connector: SharePointConnector, *, full: bool = False
) -> IndexReport:
    cursor = None if full else get_cursor(db, connector.source)
    batch = connector.delta(cursor)
    if cursor is None:
        report = writer.sync_full(connector.source, batch.upserts, prune=True)
    else:
        report = IndexReport()
        _apply(writer, connector.source, report, batch.upserts, batch.removed)
    if batch.cursor:
        set_cursor(db, connector.source, batch.cursor)
    return report
