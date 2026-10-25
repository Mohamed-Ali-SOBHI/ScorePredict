# Public additions, 25 October 2026

The public portfolio keeps its identity and existing ledger. Two frozen rules
are added prospectively from `2026-10-25T19:23:42+00:00`:

| Public ID | Frozen model | Outcome |
| --- | --- | --- |
| `public_bundesliga_xgb_2026_10_25` | `paper_positive15/models/native_Bundesliga_{42,73,2026}.ubj` | Draw |
| `public_epl_home_price_2026_10_25` | `paper_positive15/models/fold_2026_EPL_local_price_only_{42,73,2026}.ubj` | Home win |

Both retain the tested gates: complete B365 triplet, odds from 1.2 to 10
inclusive, and `probability * odds * 0.98 - 1 > 0.02`. Models are averaged over
the three frozen seeds, trained through season 2024. The Bundesliga ensemble
is byte-identical to the old six-strategy XGBoost candidate. The existing
Bundesliga consensus and strict English away rule keep their filters.

Scoring runs in a separate process against the hash-verified frozen adapter and
its registered runtime. Sporting history uses kickoff minus 72 hours, with a
two-hour availability lag. Each live fixture requires a canonical UTC kickoff,
a pending result and a fresh quote, within the existing 5-minute/24-hour window.
Audit inputs and predictions are retained in the production workflow artifact.

The current rules take priority over XGBoost, then England home. A fixture gets
one unit and one attributed strategy. Recalculations cannot add an opposing
outcome or relabel a published match; the existing ledger preserves its original
price, decision and settlement. The recalibrated Bundesliga experiment and all
other private journals remain unchanged. Historical simulations and earlier
observation tickets are not imported as public results.

Checks cover frozen probability parity, strict filter boundaries, activation
dates, private exclusion, same-run and cross-run conflicts, canonical fixture
mapping, abstentions, and separate dashboard attribution for the two Bundesliga
rules. New models do not require retraining in production.
