from __future__ import annotations

import gzip
from io import StringIO
import re
import unicodedata
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


LEAGUE_TO_FOOTBALL_DATA_CODE = {
    "Bundesliga": "D1",
    "EPL": "E0",
    "La_liga": "SP1",
    "Ligue_1": "F1",
    "Serie_A": "I1",
}

TEAM_NAME_ALIASES = {
    "newcastle": "newcastle united",
    "west brom": "west bromwich albion",
    "qpr": "queens park rangers",
    "wolves": "wolverhampton wanderers",
    "man city": "manchester city",
    "man united": "manchester united",
    "nott m forest": "nottingham forest",
    "ajaccio gfco": "gfc ajaccio",
    "bastia": "sc bastia",
    "clermont": "clermont foot",
    "paris sg": "paris saint germain",
    "st etienne": "saint etienne",
    "saint etienne": "saint etienne",
    "bielefeld": "arminia bielefeld",
    "dortmund": "borussia dortmund",
    "ein frankfurt": "eintracht frankfurt",
    "fc koln": "fc cologne",
    "koln": "fc cologne",
    "kaln": "fc cologne",
    "m gladbach": "borussia m gladbach",
    "manchengladbach": "borussia m gladbach",
    "monchengladbach": "borussia m gladbach",
    "fortuna dusseldorf": "fortuna duesseldorf",
    "greuther furth": "greuther fuerth",
    "hamburg": "hamburger sv",
    "hannover": "hannover 96",
    "hertha": "hertha berlin",
    "leverkusen": "bayer leverkusen",
    "mainz": "mainz 05",
    "nurnberg": "nuernberg",
    "rb leipzig": "rasenballsport leipzig",
    "leipzig": "rasenballsport leipzig",
    "st pauli": "st pauli",
    "stuttgart": "vfb stuttgart",
    "heidenheim": "fc heidenheim",
    "milan": "ac milan",
    "inter milan": "inter",
    "torino fc": "torino",
    "como 1907": "como",
    "hellas verona": "verona",
    "pisa sc": "pisa",
    "1 fsv mainz 05": "mainz 05",
    "spal": "spal 2013",
    "parma calcio 1913": "parma",
    "ath bilbao": "athletic club",
    "athletic bilbao": "athletic club",
    "atl madrid": "atletico madrid",
    "ath madrid": "atletico madrid",
    "alavas": "alaves",
    "betis": "real betis",
    "celta": "celta vigo",
    "espanol": "espanyol",
    "real oviedo": "oviedo",
    "dep a coruna": "deportivo la coruna",
    "la coruna": "deportivo la coruna",
    "sociedad": "real sociedad",
    "sp gijon": "sporting gijon",
    "valladolid": "real valladolid",
    "vallecano": "rayo vallecano",
    "huesca": "sd huesca",
    "santander": "racing santander",
    "r racing club": "racing santander",
    "racing club de santander": "racing santander",
    "rc deportivo": "deportivo la coruna",
    "deportivo": "deportivo la coruna",
    "malaga cf": "malaga",
    "coventry city": "coventry",
    "hull city": "hull",
    "ipswich town": "ipswich",
    "sv elversberg": "elversberg",
    "fc schalke 04": "schalke 04",
    "schalke": "schalke 04",
    "sc paderborn 07": "paderborn",
    "ac monza": "monza",
    "venezia fc": "venezia",
    "frosinone calcio": "frosinone",
}

MATCH_MARKET_COLS = [
    "match_id",
    "market_match_date",
    "market_date_diff_days",
    "home_shots",
    "away_shots",
    "home_win_odds_open",
    "draw_odds_open",
    "away_win_odds_open",
]

CLOSING_MARKET_COLS = [
    "home_win_odds_close",
    "draw_odds_close",
    "away_win_odds_close",
]

CONSENSUS_MARKET_COLS = [
    "home_win_consensus_odds_open",
    "draw_consensus_odds_open",
    "away_win_consensus_odds_open",
    "home_win_consensus_odds_close",
    "draw_consensus_odds_close",
    "away_win_consensus_odds_close",
]


def is_home_mask(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    return values.astype(str).str.lower().isin({"true", "1", "t", "yes"})


def normalize_team_name(name: object) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", "and").replace("'", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_NAME_ALIASES.get(text, text)


def season_to_code(season: int) -> str:
    return f"{str(season)[-2:]}{str(season + 1)[-2:]}"


def add_league_and_season(team_rows: pd.DataFrame) -> pd.DataFrame:
    result = team_rows.copy()
    if "league" in result.columns and "season" in result.columns:
        result["season"] = pd.to_numeric(result["season"], errors="raise").astype(int)
        return result

    season_key = result["match_id"].astype(str).str.rsplit("_", n=3).str[0]
    result["league"] = season_key.str.rsplit(" ", n=1).str[0]
    result["season"] = season_key.str.rsplit(" ", n=1).str[1].astype(int)
    return result


def _pick_first_available(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype="float64")
    for column in columns:
        if column in frame.columns:
            result = result.fillna(pd.to_numeric(frame[column], errors="coerce"))
    return result


def parse_market_dates(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, format="%d/%m/%Y", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(values[missing], format="%d/%m/%y", errors="coerce")
    missing = parsed.isna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(values[missing], dayfirst=True, errors="coerce")
    return parsed.dt.normalize()


def load_market_data(
    leagues: set[str],
    seasons: set[int],
    *,
    include_closing: bool = False,
    include_consensus: bool = False,
) -> pd.DataFrame:
    try:
        import requests
    except ImportError:  # pragma: no cover - used by lightweight runtimes
        requests = None

    session = None
    if requests is not None:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})

    frames: list[pd.DataFrame] = []
    for league in sorted(leagues):
        league_code = LEAGUE_TO_FOOTBALL_DATA_CODE[league]
        for season in sorted(seasons):
            url = f"https://www.football-data.co.uk/mmz4281/{season_to_code(season)}/{league_code}.csv"
            if session is not None:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                csv_text = response.text
            else:
                request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=30) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                        body = gzip.decompress(body)
                    csv_text = body.decode("utf-8")

            raw_frame = pd.read_csv(StringIO(csv_text))
            derived_columns = {
                "league": league,
                "season": int(season),
                "market_match_date": parse_market_dates(raw_frame["Date"]),
                "home_team_norm": raw_frame["HomeTeam"].map(normalize_team_name),
                "away_team_norm": raw_frame["AwayTeam"].map(normalize_team_name),
                "home_shots": pd.to_numeric(raw_frame["HS"], errors="coerce"),
                "away_shots": pd.to_numeric(raw_frame["AS"], errors="coerce"),
                "home_win_odds_open": _pick_first_available(
                    raw_frame,
                    ["PSH", "B365H", "AvgH"],
                ),
                "draw_odds_open": _pick_first_available(
                    raw_frame,
                    ["PSD", "B365D", "AvgD"],
                ),
                "away_win_odds_open": _pick_first_available(
                    raw_frame,
                    ["PSA", "B365A", "AvgA"],
                ),
            }
            if include_closing:
                derived_columns["home_win_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["PSCH", "B365CH", "AvgCH"],
                )
                derived_columns["draw_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["PSCD", "B365CD", "AvgCD"],
                )
                derived_columns["away_win_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["PSCA", "B365CA", "AvgCA"],
                )
            if include_consensus:
                derived_columns["home_win_consensus_odds_open"] = _pick_first_available(
                    raw_frame,
                    ["AvgH", "BbAvH"],
                )
                derived_columns["draw_consensus_odds_open"] = _pick_first_available(
                    raw_frame,
                    ["AvgD", "BbAvD"],
                )
                derived_columns["away_win_consensus_odds_open"] = _pick_first_available(
                    raw_frame,
                    ["AvgA", "BbAvA"],
                )
                derived_columns["home_win_consensus_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["AvgCH"],
                )
                derived_columns["draw_consensus_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["AvgCD"],
                )
                derived_columns["away_win_consensus_odds_close"] = _pick_first_available(
                    raw_frame,
                    ["AvgCA"],
                )
            frame = pd.concat([raw_frame, pd.DataFrame(derived_columns, index=raw_frame.index)], axis=1)

            selected_columns = [
                "league",
                "season",
                "market_match_date",
                "home_team_norm",
                "away_team_norm",
                "home_shots",
                "away_shots",
                "home_win_odds_open",
                "draw_odds_open",
                "away_win_odds_open",
            ]
            if include_closing:
                selected_columns += CLOSING_MARKET_COLS
            if include_consensus:
                selected_columns += CONSENSUS_MARKET_COLS

            frames.append(
                frame[selected_columns].copy()
            )

    market = pd.concat(frames, ignore_index=True)
    market = market.dropna(subset=["market_match_date", "home_team_norm", "away_team_norm"])
    return market


def build_match_market_table(
    team_rows: pd.DataFrame,
    max_date_diff_days: int = 14,
    *,
    include_closing: bool = False,
    include_consensus: bool = False,
) -> pd.DataFrame:
    rows = add_league_and_season(team_rows)
    home_rows = rows.loc[
        is_home_mask(rows["is_home"]),
        ["match_id", "date", "league", "season", "team_name", "opponent_name"],
    ].copy()
    home_rows["match_date"] = pd.to_datetime(home_rows["date"]).dt.normalize()
    home_rows["home_team_norm"] = home_rows["team_name"].map(normalize_team_name)
    home_rows["away_team_norm"] = home_rows["opponent_name"].map(normalize_team_name)
    home_rows = home_rows.drop_duplicates(subset=["match_id"]).reset_index(drop=True)
    home_rows["_match_row_id"] = np.arange(len(home_rows))

    market = load_market_data(
        set(home_rows["league"]),
        set(home_rows["season"]),
        include_closing=include_closing,
        include_consensus=include_consensus,
    )

    exact = home_rows.merge(
        market,
        on=["league", "season", "home_team_norm", "away_team_norm"],
        how="left",
        suffixes=("", "_market"),
    )
    exact = exact[exact["match_date"] == exact["market_match_date"]].copy()
    exact["market_date_diff_days"] = 0

    exact_match_ids = set(exact["_match_row_id"].tolist())
    unmatched = home_rows[~home_rows["_match_row_id"].isin(exact_match_ids)].copy()

    fallback = unmatched.merge(
        market,
        on=["league", "season", "home_team_norm", "away_team_norm"],
        how="left",
        suffixes=("", "_market"),
    )
    fallback["market_date_diff_days"] = (
        fallback["market_match_date"] - fallback["match_date"]
    ).dt.days.abs()
    fallback = fallback[fallback["market_date_diff_days"] <= max_date_diff_days].copy()
    fallback = fallback.sort_values(["_match_row_id", "market_date_diff_days", "market_match_date"])
    fallback = fallback.drop_duplicates(subset=["_match_row_id"], keep="first")

    matched = pd.concat([exact, fallback], ignore_index=True, sort=False)
    matched = matched.drop_duplicates(subset=["match_id"], keep="first")

    missing = sorted(set(home_rows["match_id"]) - set(matched["match_id"]))
    if missing:
        sample = ", ".join(missing[:5])
        raise ValueError(f"Failed to match market data for {len(missing)} matches. Sample: {sample}")

    output_cols = MATCH_MARKET_COLS
    if include_closing:
        output_cols += CLOSING_MARKET_COLS
    if include_consensus:
        output_cols += CONSENSUS_MARKET_COLS
    return matched[output_cols].copy()


def enrich_team_rows_with_market_data(
    team_rows: pd.DataFrame,
    max_date_diff_days: int = 14,
    *,
    include_closing: bool = False,
    include_consensus: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    original_cols = list(team_rows.columns)
    rows = team_rows.copy()
    match_market = build_match_market_table(
        rows,
        max_date_diff_days=max_date_diff_days,
        include_closing=include_closing,
        include_consensus=include_consensus,
    )

    replaceable_cols = [
        column
        for column in MATCH_MARKET_COLS[1:]
        + CLOSING_MARKET_COLS
        + CONSENSUS_MARKET_COLS
        + [
            "team_shots",
            "opponent_shots",
            "team_win_odds_open",
            "draw_odds_open",
            "opponent_win_odds_open",
            "team_win_odds_close",
            "draw_odds_close",
            "opponent_win_odds_close",
            "team_win_consensus_odds_open",
            "draw_consensus_odds_open",
            "opponent_win_consensus_odds_open",
            "team_win_consensus_odds_close",
            "draw_consensus_odds_close",
            "opponent_win_consensus_odds_close",
            "team_win_odds",
            "draw_odds",
            "opponent_win_odds",
        ]
        if column in rows.columns
    ]
    if replaceable_cols:
        rows = rows.drop(columns=replaceable_cols)

    rows = rows.merge(match_market, on="match_id", how="left", validate="many_to_one")
    home_mask = is_home_mask(rows["is_home"])
    rows["team_shots"] = np.where(home_mask, rows["home_shots"], rows["away_shots"])
    rows["opponent_shots"] = np.where(home_mask, rows["away_shots"], rows["home_shots"])
    rows["team_win_odds_open"] = np.where(home_mask, rows["home_win_odds_open"], rows["away_win_odds_open"])
    rows["draw_odds_open"] = rows["draw_odds_open"]
    rows["opponent_win_odds_open"] = np.where(home_mask, rows["away_win_odds_open"], rows["home_win_odds_open"])

    new_cols = [
        "team_shots",
        "opponent_shots",
        "team_win_odds_open",
        "draw_odds_open",
        "opponent_win_odds_open",
    ]
    if include_closing:
        rows["team_win_odds_close"] = np.where(home_mask, rows["home_win_odds_close"], rows["away_win_odds_close"])
        rows["draw_odds_close"] = rows["draw_odds_close"]
        rows["opponent_win_odds_close"] = np.where(
            home_mask,
            rows["away_win_odds_close"],
            rows["home_win_odds_close"],
        )
        new_cols += [
            "team_win_odds_close",
            "draw_odds_close",
            "opponent_win_odds_close",
        ]
    if include_consensus:
        rows["team_win_consensus_odds_open"] = np.where(
            home_mask,
            rows["home_win_consensus_odds_open"],
            rows["away_win_consensus_odds_open"],
        )
        rows["draw_consensus_odds_open"] = rows["draw_consensus_odds_open"]
        rows["opponent_win_consensus_odds_open"] = np.where(
            home_mask,
            rows["away_win_consensus_odds_open"],
            rows["home_win_consensus_odds_open"],
        )
        rows["team_win_consensus_odds_close"] = np.where(
            home_mask,
            rows["home_win_consensus_odds_close"],
            rows["away_win_consensus_odds_close"],
        )
        rows["draw_consensus_odds_close"] = rows["draw_consensus_odds_close"]
        rows["opponent_win_consensus_odds_close"] = np.where(
            home_mask,
            rows["away_win_consensus_odds_close"],
            rows["home_win_consensus_odds_close"],
        )
        new_cols += [
            "team_win_consensus_odds_open",
            "draw_consensus_odds_open",
            "opponent_win_consensus_odds_open",
            "team_win_consensus_odds_close",
            "draw_consensus_odds_close",
            "opponent_win_consensus_odds_close",
        ]

    keep_cols = [column for column in original_cols if column in rows.columns]
    keep_cols += [column for column in new_cols if column not in keep_cols]
    return rows[keep_cols].copy(), match_market
