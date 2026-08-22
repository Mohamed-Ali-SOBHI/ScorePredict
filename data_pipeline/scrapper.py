import argparse
import gzip
import json
import os
import sys
from urllib.request import Request, urlopen

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover - used by lightweight runtimes
    requests = None

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - progress bar is optional
    def tqdm(values):
        return values


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from data_pipeline.market_data import (
    MarketDataUnavailableError,
    enrich_team_rows_with_market_data,
    normalize_team_name,
)
from data_pipeline.team_registry import read_registry, write_registry


DEFAULT_LEAGUES = ["La_liga", "Bundesliga", "EPL", "Serie_A", "Ligue_1"]
DEFAULT_SEASONS = ["2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016", "2015", "2014"]


def _fixture_team_titles(payload):
    """Return the reliable team id/title pairs exposed in fixture metadata."""
    fixtures = payload.get("dates") or []
    if isinstance(fixtures, dict):
        fixtures = fixtures.values()

    titles = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        for side in ("h", "a"):
            team = fixture.get(side)
            if not isinstance(team, dict):
                continue
            team_id = team.get("id") or team.get("team_id")
            title = str(team.get("title") or "").strip()
            if team_id is not None and title:
                titles[str(team_id)] = title
    return titles


def normalize_understat_teams(payload, fallback_titles=None):
    """Normalize partial Understat team payloads without inventing club names.

    Understat occasionally omits ``id`` or ``title`` from a team row after a
    match while keeping the same metadata in ``dates``. The current-season
    registry is also used to preserve clubs that have not played yet.
    """
    if not isinstance(payload, dict):
        raise ValueError("Understat league payload must be an object")

    raw_teams = payload.get("teams")
    if not isinstance(raw_teams, (dict, list)):
        raise ValueError("Understat league payload has no usable teams collection")

    fixture_titles = _fixture_team_titles(payload)
    registered_titles = {
        str(team_id): str(title).strip()
        for team_id, title in (fallback_titles or {}).items()
        if team_id is not None and str(title).strip()
    }
    known_titles = {**registered_titles, **fixture_titles}
    entries = raw_teams.items() if isinstance(raw_teams, dict) else ((None, team) for team in raw_teams)
    normalized = {}

    for key, raw_team in entries:
        if not isinstance(raw_team, dict):
            raise ValueError(f"Understat team payload is not an object: {raw_team!r}")
        team = dict(raw_team)
        team_id = team.get("id") or team.get("team_id") or key
        if team_id is None:
            raise ValueError(f"Understat team payload has no id: {raw_team}")
        team_id = str(team_id)
        title = str(team.get("title") or known_titles.get(team_id) or "").strip()
        if not title:
            raise ValueError(f"Understat team {team_id} has no title in teams, dates, or the current registry")
        history = team.get("history")
        if history is None:
            history = []
        if not isinstance(history, list):
            raise ValueError(f"Understat team {team_id} has an invalid history collection")
        team.update({"id": team_id, "title": title, "history": history})
        normalized[team_id] = team

    # Early in a season Understat may expose only teams that already played.
    # Keep fixture and registered clubs with empty histories so the registry
    # remains complete without creating synthetic match rows.
    normalized_names = {normalize_team_name(team["title"]) for team in normalized.values()}
    for team_id, title in known_titles.items():
        normalized_title = normalize_team_name(title)
        if team_id in normalized or normalized_title in normalized_names:
            continue
        normalized[team_id] = {"id": team_id, "title": title, "history": []}
        normalized_names.add(normalized_title)

    return normalized


def _current_registry_titles(league, season):
    registry = read_registry(os.path.join(REPO_ROOT, "Data"))
    return {
        str(row.get("team_id")): str(row.get("team_name") or "").strip()
        for row in registry.get("teams", [])
        if str(row.get("league")) == str(league)
        and str(row.get("season")) == str(season)
        and row.get("team_id") is not None
        and str(row.get("team_name") or "").strip()
    }


def get_league_data(league, season, base_url="https://understat.com"):
    """Fetch Understat JSON for a league/season.

    Understat now loads the heavy league payload via XHR (`getLeagueData`).
    The endpoint returns 404 unless it's requested as an XMLHttpRequest.
    """
    url = f"{base_url}/getLeagueData/{league}/{season}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/league/{league}/{season}",
    }
    if requests is not None:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
    else:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            payload = json.loads(body.decode("utf-8"))
    return normalize_understat_teams(
        payload,
        fallback_titles=_current_registry_titles(league, season),
    )


def get_all_league_data(seasons, leagues, base_url):
    """Fetch Understat league-season JSON for all requested inputs."""
    data = {}

    for league_name in tqdm(leagues):
        for season_name in seasons:
            try:
                data[f"{league_name} {season_name}"] = get_league_data(
                    league_name,
                    season_name,
                    base_url=base_url,
                )
            except Exception as exc:
                url = f"{base_url}/getLeagueData/{league_name}/{season_name}"
                raise RuntimeError(f"Failed to fetch Understat data for {league_name} {season_name} ({url})") from exc

    return data



def extract_stats_from_data(data):
    """
    Extract the stats from the data including opponent stats for each match
    :param data: data to extract the stats from
    :return: stats dictionary with home and away team stats for each match
    """
    stats = {}
    
    for season_key in data.keys():
        season_data = data[season_key]
        
        # Collect all matches first to be able to identify opponents
        match_pairs = {}
        for team_id, team_data in season_data.items():
            for match in team_data['history']:
                date = match['date']
                # Use date as temporary key to group matches
                if date not in match_pairs:
                    match_pairs[date] = []
                match_pairs[date].append({
                    'team_id': team_id,
                    'match': match
                })

        # Process matches and create records with proper IDs
        for team_id, team_data in season_data.items():
            team_name = team_data['title']
            team_matches = []
            
            for match in team_data['history']:
                date = match['date']
                
                # Find opponent ID
                opponent_id = None
                if date in match_pairs:
                    for pair in match_pairs[date]:
                        if pair['team_id'] != team_id:
                            # Verify this is really the opponent by checking stats
                            pair_match = pair['match']
                            if (match['h_a'] != pair_match['h_a'] and  # One home, one away
                                abs(float(match['xG']) - float(pair_match['xGA'])) < 0.01 and  # xG matches
                                abs(float(match['xGA']) - float(pair_match['xG'])) < 0.01 and  # xGA matches
                                match['scored'] == pair_match['missed'] and  # Goals match
                                match['missed'] == pair_match['scored']):  # Goals match
                                opponent_id = pair['team_id']
                                break

                # Create a consistent match ID regardless of which team we're processing
                match_teams = sorted([team_id, opponent_id if opponent_id else 'unknown'])
                match_id = f"{season_key}_{match_teams[0]}_{match_teams[1]}_{match['date']}"
                
                # Create a new match record with both team stats
                combined_match = {                    
                    'match_id': match_id,
                    'date': match['date'],
                    'is_home': match['h_a'] == 'h',
                    'team_id': team_id,
                    'team_name': team_name,
                    'result': match['result'],
                    'opponent_id': 'Unknown',  # We'll need to update this with actual opponent data
                    'opponent_name': 'Unknown',  # We'll need to update this with actual opponent data
                    
                    # Own team stats
                    'team_xG': match['xG'],
                    'team_goals': match['scored'],
                    'team_ppda_att': match['ppda']['att'],
                    'team_ppda_def': match['ppda']['def'],
                    'team_deep': match['deep'],
                    'team_xpts': match['xpts'],
                    'team_npxG': match['npxG'],
                    
                    # Opponent stats 
                    'opponent_xG': match['xGA'],
                    'opponent_goals': match['missed'],
                    'opponent_ppda_att': match['ppda_allowed']['att'],
                    'opponent_ppda_def': match['ppda_allowed']['def'],
                    'opponent_deep': match['deep_allowed'],
                    'opponent_npxG': match['npxGA'],
                }
                
                team_matches.append(combined_match)
            
            season = season_key.split(' ')[1]  # Extract season from the key
            stats[season_key.split(' ')[0] + ' ' + season + ' ' + team_name] = team_matches
    
    return stats


def save_data(stats, *, include_closing_market_data=False, include_consensus_market_data=False):
    """
    Save the stats to a csv file
    :param stats: stats to save
    """
    frames = []

    for team_key, matches in stats.items():
        league = team_key.split(' ')[0]
        season = int(team_key.split(' ')[1])
        team_name = team_key.split(' ')[2:]

        base_dir = os.path.join('.', 'Data', league)
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        output_file = os.path.join(base_dir, f"{season} {' '.join(team_name)}.csv")

        df = pd.DataFrame(matches)
        if df.empty:
            continue
        df['league'] = league
        df['season'] = season
        df['_output_file'] = output_file
        df['_row_order'] = range(len(df))
        frames.append(df)

    if not frames:
        return

    all_rows = pd.concat(frames, ignore_index=True)
    enriched_groups = []
    for (league, season), group in all_rows.groupby(['league', 'season'], sort=False):
        try:
            enriched, _ = enrich_team_rows_with_market_data(
                group,
                include_closing=include_closing_market_data,
                include_consensus=include_consensus_market_data,
            )
        except MarketDataUnavailableError as exc:
            print(
                f"Skipping {league} {season} until its official market CSV is available: {exc}",
                file=sys.stderr,
            )
            continue
        enriched_groups.append(enriched)

    if not enriched_groups:
        return
    all_rows = pd.concat(enriched_groups, ignore_index=True)

    for output_file, group in all_rows.groupby('_output_file', sort=False):
        group = group.sort_values('_row_order')
        group = group.drop(columns=['league', 'season', '_output_file', '_row_order'])
        group.to_csv(output_file, index=False)


def find_matching_matches(data):
    """
    Post-process the data to find matching matches and update opponent information
    :param data: Dictionary containing all match data
    :return: Updated match data with opponent information
    """
    matched_games = {}
    
    # First, create a dictionary of all matches by date for each league/season
    for season_key, season_data in data.items():
        matches_by_date = {}
        
        for team_id, team_data in season_data.items():
            team_name = team_data['title']
            for match in team_data['history']:
                match_date = match['date']
                if match_date not in matches_by_date:
                    matches_by_date[match_date] = []
                
                matches_by_date[match_date].append({
                    'team_id': team_id,
                    'team_name': team_name,
                    'match': match
                })
        
        # For each date, find matching pairs of matches
        for date, matches in matches_by_date.items():
            for i in range(len(matches)):
                for j in range(i + 1, len(matches)):
                    match1 = matches[i]['match']
                    match2 = matches[j]['match']
                    
                    # Compare multiple parameters to ensure it's the same match
                    is_same_match = (
                        match1['h_a'] != match2['h_a']  # One home, one away
                        and abs(float(match1['xG']) - float(match2['xGA'])) < 0.01  # xG matches
                        and abs(float(match1['xGA']) - float(match2['xG'])) < 0.01  # xGA matches
                        and match1['scored'] == match2['missed']  # Goals scored/conceded match
                        and match1['missed'] == match2['scored']  # Goals scored/conceded match
                        and match1['deep'] == match2['deep_allowed']  # Deep passes match
                        and match1['deep_allowed'] == match2['deep']  # Deep passes allowed match
                    )
                    
                    if is_same_match:
                        match_key = f"{season_key}_{date}_{matches[i]['team_id']}_{matches[j]['team_id']}"
                        
                        # Store the match information
                        if match1['h_a'] == 'h':
                            home_team, away_team = matches[i], matches[j]
                        else:
                            home_team, away_team = matches[j], matches[i]
                            
                        matched_games[match_key] = {
                            'date': date,
                            'home_team_id': home_team['team_id'],
                            'home_team_name': home_team['team_name'],
                            'away_team_id': away_team['team_id'],
                            'away_team_name': away_team['team_name']
                        }
    
    return matched_games


def update_stats_with_opponents(stats, data):
    """
    Update the stats dictionary with opponent information
    """
    # First get all matched games
    matched_games = find_matching_matches(data)
    
    # Update each team's matches with opponent information
    for team_key in stats.keys():
        for match in stats[team_key]:
            date = match['date']
            team_id = match['team_id']
            
            # Search for this match in matched_games
            for match_key, game_info in matched_games.items():
                if game_info['date'] == date:
                    if game_info['home_team_id'] == team_id:
                        match['opponent_id'] = game_info['away_team_id']
                        match['opponent_name'] = game_info['away_team_name']
                        break
                    elif game_info['away_team_id'] == team_id:
                        match['opponent_id'] = game_info['home_team_id']
                        match['opponent_name'] = game_info['home_team_name']
                        break
    
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://understat.com")
    parser.add_argument(
        "--leagues",
        default=",".join(DEFAULT_LEAGUES),
        help="Comma-separated league ids understood by Understat",
    )
    parser.add_argument(
        "--seasons",
        default=",".join(DEFAULT_SEASONS),
        help="Comma-separated season start years, e.g. 2025,2024",
    )
    parser.add_argument("--include-closing-market-data", action="store_true")
    parser.add_argument("--include-consensus-market-data", action="store_true")
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    base_url = args.base_url
    leagues = [league.strip() for league in args.leagues.split(",") if league.strip()]
    seasons = [season.strip() for season in args.seasons.split(",") if season.strip()]

    data = get_all_league_data(seasons, leagues, base_url)
    registry = write_registry(data, os.path.join(REPO_ROOT, "Data"))
    print(f"Team registry written: {registry}")

    stats = extract_stats_from_data(data)
    stats = update_stats_with_opponents(stats, data)  # Update with opponent information
    save_data(
        stats,
        include_closing_market_data=args.include_closing_market_data,
        include_consensus_market_data=args.include_consensus_market_data,
    )
