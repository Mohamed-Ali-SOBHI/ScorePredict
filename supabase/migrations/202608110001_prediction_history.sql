create table if not exists public.prediction_history (
  snapshot_key text primary key,
  prediction_generated_at_utc timestamptz not null,
  portfolio_name text,
  date timestamptz not null,
  league text not null,
  team_name text not null,
  opponent_name text not null,
  selected_outcome text not null check (selected_outcome in ('home_win', 'draw', 'away_win')),
  selected_odds double precision,
  predicted_probability double precision,
  raw_model_probability double precision,
  market_probability double precision,
  edge double precision,
  value_score double precision,
  expected_value double precision,
  raw_expected_value double precision,
  probability_note text,
  train_max_season integer,
  strategy_names text,
  stake_eur double precision,
  recommended boolean not null default false,
  result_status text not null default 'pending'
    check (result_status in ('pending', 'pending_data_refresh', 'won', 'lost', 'void', 'unmatched')),
  closing_selected_odds double precision,
  realized_profit double precision,
  actual_result text,
  actual_outcome text,
  actual_home_score integer,
  actual_away_score integer,
  match_found boolean,
  realized_profit_units double precision,
  updated_at timestamptz not null default now()
);

create index if not exists prediction_history_date_idx
  on public.prediction_history (date desc);

create index if not exists prediction_history_status_idx
  on public.prediction_history (result_status, date);

alter table public.prediction_history enable row level security;
revoke all on table public.prediction_history from anon, authenticated;
grant select, insert, update on table public.prediction_history to service_role;

comment on table public.prediction_history is
  'Mémoire des prévisions publiées et de leur résultat vérifié après le match.';
