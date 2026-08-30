create table if not exists public.fixture_registry (
  fixture_id text primary key,
  league text not null,
  season integer not null,
  home_team text not null,
  away_team text not null,
  kickoff_utc timestamptz not null,
  status text not null default 'scheduled'
    check (status in ('scheduled', 'live', 'finished', 'postponed', 'cancelled')),
  home_score integer,
  away_score integer,
  home_win_odds_open double precision,
  draw_odds_open double precision,
  away_win_odds_open double precision,
  schedule_source text not null,
  odds_source text,
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists fixture_registry_kickoff_idx
  on public.fixture_registry (kickoff_utc);

create index if not exists fixture_registry_status_idx
  on public.fixture_registry (status, kickoff_utc);

alter table public.fixture_registry enable row level security;
revoke all on table public.fixture_registry from anon, authenticated;
grant select, insert, update on table public.fixture_registry to service_role;

alter table public.prediction_history
  add column if not exists fixture_id text,
  add column if not exists kickoff_utc timestamptz;

create index if not exists prediction_history_fixture_idx
  on public.prediction_history (fixture_id);

comment on table public.fixture_registry is
  'Registre canonique des rencontres : identifiant stable, coup d''envoi UTC, cotes et verdict.';
