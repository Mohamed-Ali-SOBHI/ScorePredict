# Result collection and GitHub execution

## Sources

ESPN daily scoreboards are the primary source for EPL, La Liga, Bundesliga,
Serie A and Ligue 1. Each request is restricted to one league and one date,
with `limit=100`. Only dates with overdue published bets are requested.
The public endpoint needs no account key. It has no published availability
or latency guarantee: this is not a claim of unlimited API service.

Understat finished match histories remain a fallback when ESPN fails or does
not confirm every due match. TheSportsDB's truncated free season/day lists
are no longer used for result settlement. Existing fixture-time code is unchanged.

ESPN settlement requires `STATUS_FULL_TIME`, `state=post`, `completed=true`,
valid nonnegative integer scores, the correct date, league and both normalized
team names. Home/away roles are explicit. No fuzzy name matching is used.
Extra-time, shoot-out, abandoned and postponed statuses are not accepted by
this league-only adapter. Contradictory final scores leave the bet unresolved.
Already settled bets remain immutable in the normal refresh path.

## Execution

`results-monitor.yml` keeps its ten-minute requested schedule and its manual
trigger. GitHub can delay or skip cron launches; it is not a live-score SLA.

`results-watch.yml` additionally starts after successful daily publication,
on an hourly requested schedule, or manually. It uses a separate concurrency
group and never holds the Pages publication lock. Its GitHub-hosted runner
checks the public pending bets every five minutes and dispatches the result
monitor when a kickoff is at least 105 minutes old. It does not dispatch if
another monitor is running or queued. Score collection and publication still
run under the existing shared Pages concurrency lock.

The watch stops when no nearby unresolved published bet remains or after
350 minutes. Matches more than six hours past kickoff are left to the normal
monitor schedule. A watch may arm up to five hours before kickoff. This uses
GitHub runner time; there is no local background process or additional paid
service. The watcher refuses to run outside GitHub Actions.

The dashboard client polls every five minutes, so visible latency also includes
deployment and browser refresh time. Instant updates cannot be guaranteed.

Both public JSON files are preserved during result publication. A diagnostic
artifact records new settlements, ESPN event IDs, source names and failures
for 90 days. The permanent scores remain in the existing Supabase ledger;
no schema, model, filter, odds or stake change is needed.

## Validation on 17 October 2026

- Live ESPN scoreboard requests succeeded for all five leagues.
- All 96 current ESPN club names matched the project's current-season registry
  after explicit provider-specific aliases.
- Bundesliga returned all six fixtures for the date, including final scores
  Hamburger SV 1–0 VfB Stuttgart and Werder Bremen 2–2 Paderborn.
- A local settlement dry run matched both published bets and retained their
  original odds and stakes. Deployment validation is performed by the GitHub
  monitor against the persistent ledger.
- Unit tests cover provider failures, fallback, incomplete coverage, reversed
  competitor order, timezone conversion, invalid scores, non-final statuses,
  conflicting finals, immutable settled results and bounded watch activation.

Source endpoint example:
https://site.api.espn.com/apis/site/v2/sports/soccer/ger.1/scoreboard?dates=20261017&limit=100

GitHub schedule limitations:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
