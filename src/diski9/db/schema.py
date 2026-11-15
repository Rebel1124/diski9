"""SQLite schema (SQLAlchemy Core). Alembic migrations mirror this metadata.

Conventions
-----------
* Provider identifiers (league, team, fixture, venue, bookmaker) are used as
  primary keys: they are stable in API-Football and make provenance obvious.
* All timestamps are timezone-aware UTC, stored as ISO-8601 text (``UTCDateTime``).
* Decimal odds are stored exactly as text (``DecimalText``), never as floats.
* Odds quotes are *price episodes*: one row per continuous period during which
  a bookmaker offered one price for one outcome. Rows are never deleted, so the
  price in effect at any past moment can be reconstructed (snapshots,
  point-in-time analysis).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from .types import DecimalText, UTCDateTime

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING)

# --------------------------------------------------------------------- reference
competitions = Table(
    "competitions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False, comment="API league id"),
    Column("name", String(120), nullable=False),
    Column("country", String(80), nullable=False),
    Column("type", String(20), nullable=False, comment="API type: League | Cup"),
    Column("tier", Integer, nullable=True, comment="1 = top flight, 2 = second tier"),
    Column("parent_competition_id", Integer, ForeignKey("competitions.id"), nullable=True),
    Column("odds_enabled", Boolean, nullable=False, server_default=text("0")),
    Column("updated_at", UTCDateTime, nullable=False),
)

seasons = Table(
    "seasons",
    metadata,
    Column("competition_id", Integer, ForeignKey("competitions.id"), primary_key=True),
    Column("year", Integer, primary_key=True, autoincrement=False),
    Column("start_date", String(10), nullable=True),
    Column("end_date", String(10), nullable=True),
    Column("is_current", Boolean, nullable=False),
    Column("coverage_odds", Boolean, nullable=False, comment="API coverage flag (informational)"),
    Column("updated_at", UTCDateTime, nullable=False),
)

venues = Table(
    "venues",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False, comment="API venue id"),
    Column("name", String(160), nullable=True),
    Column("city", String(120), nullable=True),
    Column("updated_at", UTCDateTime, nullable=False),
)

teams = Table(
    "teams",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False, comment="API team id"),
    Column("name", String(120), nullable=False),
    Column("code", String(10), nullable=True),
    Column("country", String(80), nullable=True),
    Column(
        "home_venue_id",
        Integer,
        ForeignKey("venues.id"),
        nullable=True,
        comment="Registered home ground from /teams (provider's current value)",
    ),
    Column("updated_at", UTCDateTime, nullable=False),
)

team_seasons = Table(
    "team_seasons",
    metadata,
    Column("team_id", Integer, ForeignKey("teams.id"), primary_key=True),
    Column("competition_id", Integer, primary_key=True),
    Column("season", Integer, primary_key=True),
    Column(
        "registered_venue_id",
        Integer,
        ForeignKey("venues.id"),
        nullable=True,
        comment="Home ground listed by /teams?league&season",
    ),
    Column(
        "modal_home_venue_id",
        Integer,
        ForeignKey("venues.id"),
        nullable=True,
        comment="Most frequent venue of the team's regular-season home fixtures",
    ),
    Column("regular_season_fixtures", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", UTCDateTime, nullable=False),
    ForeignKeyConstraint(
        ["competition_id", "season"],
        ["seasons.competition_id", "seasons.year"],
        name="fk_team_seasons_season_seasons",
    ),
)

# ---------------------------------------------------------------------- fixtures
fixtures = Table(
    "fixtures",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False, comment="API fixture id"),
    Column("competition_id", Integer, nullable=False),
    Column("season", Integer, nullable=False),
    Column("round_name", String(80), nullable=True),
    Column(
        "round_type",
        String(20),
        nullable=False,
        comment="regular | playoff | relegation | promotion | other",
    ),
    Column("kickoff_utc", UTCDateTime, nullable=False),
    Column("status_short", String(6), nullable=False),
    Column("status_long", String(40), nullable=True),
    Column("home_team_id", Integer, ForeignKey("teams.id"), nullable=False),
    Column("away_team_id", Integer, ForeignKey("teams.id"), nullable=False),
    Column("venue_id", Integer, ForeignKey("venues.id"), nullable=True),
    Column("venue_name", String(160), nullable=True),
    Column("venue_city", String(120), nullable=True),
    # 90-minute score (API score.fulltime: stoppage time included, extra time excluded)
    Column("ft_home", Integer, nullable=True),
    Column("ft_away", Integer, nullable=True),
    Column("ht_home", Integer, nullable=True),
    Column("ht_away", Integer, nullable=True),
    Column("et_home", Integer, nullable=True),
    Column("et_away", Integer, nullable=True),
    Column("pen_home", Integer, nullable=True),
    Column("pen_away", Integer, nullable=True),
    Column(
        "is_final",
        Boolean,
        nullable=False,
        comment="Match completed with a 90-minute result (FT/AET/PEN)",
    ),
    Column(
        "stats_exclusion_reason",
        String(30),
        nullable=True,
        comment="NULL = eligible for default statistical windows",
    ),
    Column(
        "venue_classification",
        String(20),
        nullable=False,
        server_default=text("'unknown'"),
        comment="home_ground | unverified_venue | neutral | unknown",
    ),
    Column("venue_classification_reason", String(80), nullable=True),
    Column("content_hash", String(64), nullable=False),
    Column("first_seen_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    Column(
        "result_recorded_at",
        UTCDateTime,
        nullable=True,
        comment="When we first observed a final result",
    ),
    ForeignKeyConstraint(
        ["competition_id", "season"],
        ["seasons.competition_id", "seasons.year"],
        name="fk_fixtures_season_seasons",
    ),
    CheckConstraint("home_team_id <> away_team_id", name="distinct_teams"),
)
Index(
    "ix_fixtures_comp_season_kickoff",
    fixtures.c.competition_id,
    fixtures.c.season,
    fixtures.c.kickoff_utc,
)
Index("ix_fixtures_home_kickoff", fixtures.c.home_team_id, fixtures.c.kickoff_utc)
Index("ix_fixtures_away_kickoff", fixtures.c.away_team_id, fixtures.c.kickoff_utc)
Index("ix_fixtures_status_kickoff", fixtures.c.status_short, fixtures.c.kickoff_utc)

neutral_venue_overrides = Table(
    "neutral_venue_overrides",
    metadata,
    Column("fixture_id", Integer, primary_key=True, autoincrement=False),
    Column("classification", String(20), nullable=False),
    Column("note", Text, nullable=True),
    Column("updated_at", UTCDateTime, nullable=False),
    CheckConstraint(
        "classification IN ('home_ground','neutral','unknown')", name="valid_classification"
    ),
)

approved_home_grounds = Table(
    "approved_home_grounds",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("team_id", Integer, nullable=False, comment="API team id"),
    Column("venue_id", Integer, nullable=False, comment="API venue id"),
    Column("valid_from", String(10), nullable=False, comment="YYYY-MM-DD inclusive"),
    Column("valid_to", String(10), nullable=True, comment="YYYY-MM-DD inclusive; NULL = open"),
    Column("evidence", Text, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    UniqueConstraint("team_id", "venue_id", "valid_from", name="uq_approved_home_grounds_key"),
)

# ------------------------------------------------------------------------- odds
bookmakers = Table(
    "bookmakers",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False, comment="API bookmaker id"),
    Column("name", String(80), nullable=True),
    Column("is_exchange", Boolean, nullable=False, server_default=text("0")),
    Column(
        "affiliation_group",
        String(60),
        nullable=True,
        comment="Brands under common ownership share one group; NULL = treated as independent",
    ),
    Column("eligible", Boolean, nullable=False, server_default=text("1")),
    Column("notes", Text, nullable=True),
    Column("updated_at", UTCDateTime, nullable=False),
)

odds_fetches = Table(
    "odds_fetches",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("competition_id", Integer, nullable=False),
    Column("season", Integer, nullable=False),
    Column("retrieved_at", UTCDateTime, nullable=False),
    Column("finished_at", UTCDateTime, nullable=True),
    Column("status", String(20), nullable=False, comment="running | complete | failed"),
    Column("requests", Integer, nullable=False, server_default=text("0")),
    Column("pages", Integer, nullable=False, server_default=text("0")),
    Column("fixtures_in_response", Integer, nullable=False, server_default=text("0")),
    Column("fixtures_collected", Integer, nullable=False, server_default=text("0")),
    Column("quotes_seen", Integer, nullable=False, server_default=text("0")),
    Column("quotes_inserted", Integer, nullable=False, server_default=text("0")),
    Column("quotes_unchanged", Integer, nullable=False, server_default=text("0")),
    Column("quotes_price_changed", Integer, nullable=False, server_default=text("0")),
    Column("quotes_disappeared", Integer, nullable=False, server_default=text("0")),
    Column("quotes_closed_at_kickoff", Integer, nullable=False, server_default=text("0")),
    Column("warnings", Text, nullable=True),
    Column("error", Text, nullable=True),
)

odds_fixture_observations = Table(
    "odds_fixture_observations",
    metadata,
    Column("fetch_id", Integer, ForeignKey("odds_fetches.id"), primary_key=True),
    Column("fixture_id", Integer, ForeignKey("fixtures.id"), primary_key=True),
    Column("retrieved_at", UTCDateTime, nullable=False),
    Column(
        "provider_updated_at",
        UTCDateTime,
        nullable=True,
        comment="API 'update': fixture-level, shared by all bookmakers",
    ),
    Column("bookmakers_listed", Integer, nullable=False),
    Column("quotes_parsed", Integer, nullable=False),
)

odds_quotes = Table(
    "odds_quotes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fixture_id", Integer, ForeignKey("fixtures.id"), nullable=False),
    Column("bookmaker_id", Integer, ForeignKey("bookmakers.id"), nullable=False),
    Column("market", String(8), nullable=False),
    Column("outcome", String(12), nullable=False),
    Column("decimal_odds", DecimalText, nullable=False),
    Column("first_seen_at", UTCDateTime, nullable=False, comment="Retrieval time first observed"),
    Column(
        "last_seen_at", UTCDateTime, nullable=False, comment="Latest retrieval still offering it"
    ),
    Column("first_provider_updated_at", UTCDateTime, nullable=True),
    Column("last_provider_updated_at", UTCDateTime, nullable=True),
    Column("times_seen", Integer, nullable=False, server_default=text("1")),
    Column("first_fetch_id", Integer, ForeignKey("odds_fetches.id"), nullable=False),
    Column("last_fetch_id", Integer, ForeignKey("odds_fetches.id"), nullable=False),
    Column("ended_at", UTCDateTime, nullable=True, comment="NULL = currently offered"),
    Column(
        "end_reason",
        String(20),
        nullable=True,
        comment="price_changed | disappeared | kickoff",
    ),
    CheckConstraint("market IN ('1X2','BTTS','OU25')", name="valid_market"),
    CheckConstraint(
        "outcome IN ('HOME','DRAW','AWAY','BTTS_YES','BTTS_NO','OVER_2_5','UNDER_2_5')",
        name="valid_outcome",
    ),
    CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="end_consistent"),
)
# At most one *active* episode per (fixture, bookmaker, market, outcome).
Index(
    "uq_odds_quotes_active",
    odds_quotes.c.fixture_id,
    odds_quotes.c.bookmaker_id,
    odds_quotes.c.market,
    odds_quotes.c.outcome,
    unique=True,
    sqlite_where=odds_quotes.c.ended_at.is_(None),
)
Index("ix_odds_quotes_fixture_market", odds_quotes.c.fixture_id, odds_quotes.c.market)

# -------------------------------------------------------------------- screener
screener_results = Table(
    "screener_results",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fixture_id", Integer, ForeignKey("fixtures.id"), nullable=False),
    Column("basis", String(10), nullable=False, comment="venue | overall"),
    Column("engine_version", String(20), nullable=False),
    Column("as_of", UTCDateTime, nullable=False, comment="Reference time requested"),
    Column(
        "cutoff",
        UTCDateTime,
        nullable=False,
        comment="Only matches kicking off before this were used (min(as_of, kickoff))",
    ),
    Column("calculated_at", UTCDateTime, nullable=False),
    Column(
        "verified_at", UTCDateTime, nullable=False, comment="Last refresh confirming the result"
    ),
    Column("superseded_at", UTCDateTime, nullable=True, comment="NULL = current cached result"),
    Column("inputs_hash", String(64), nullable=False),
    Column("home_form", Float, nullable=True),
    Column("away_form", Float, nullable=True),
    Column("raw_difference", Float, nullable=True),
    Column("venue_adjusted_difference", Float, nullable=True),
    Column("benchmark_season", Integer, nullable=True),
    Column("benchmark_source", String(20), nullable=True),
    Column("benchmark_matches", Integer, nullable=True),
    Column("btts_yes_indicator", Float, nullable=True),
    Column("over25_indicator", Float, nullable=True),
    Column("limited_data", Boolean, nullable=False),
    Column("payload", Text, nullable=False, comment="Full calculation breakdown (JSON)"),
)
Index(
    "uq_screener_results_active",
    screener_results.c.fixture_id,
    screener_results.c.basis,
    screener_results.c.engine_version,
    unique=True,
    sqlite_where=screener_results.c.superseded_at.is_(None),
)

# -------------------------------------------------------------------- run log
ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job", String(40), nullable=False),
    Column("competition_id", Integer, nullable=True),
    Column("season", Integer, nullable=True),
    Column("started_at", UTCDateTime, nullable=False),
    Column("finished_at", UTCDateTime, nullable=True),
    Column("status", String(20), nullable=False),
    Column("requests", Integer, nullable=False, server_default=text("0")),
    Column("inserted", Integer, nullable=False, server_default=text("0")),
    Column("updated", Integer, nullable=False, server_default=text("0")),
    Column("unchanged", Integer, nullable=False, server_default=text("0")),
    Column("error", Text, nullable=True),
)
