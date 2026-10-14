# Catan Night

A static stats site for our Catan group: a leaderboard ranked by wins above expected, player pages, head-to-head records, and per-game dice and production. The data lives in this repo as JSON. A Python script computes every stat, and GitHub Pages serves the result.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/build.py              # validates data, writes the site to dist/
```

Then open `dist/index.html` in a browser. Opening `site/index.html` shows a "No stats" message, because `site/` only holds the templates and the data is added by the build. To preview exactly as GitHub Pages will serve it, run `python -m http.server -d dist 8000` and open http://localhost:8000.

`python scripts/build.py --check` validates the data without building. `python -m unittest discover -s tests` runs the tests, which use synthetic data in `tests/fixtures/` and never touch `data/`.

## After game night: importing from TwoSheep

```bash
cd "/Users/joshdavis/Desktop/catan dashboard/catan-stats"   # run everything from this folder (the repo), not its parent
source .venv/bin/activate                     # every step needs the project's Python (openskill and friends)
python scripts/fetch_twosheep.py --files      # local only: saves new group game summaries and replay files to raw/twosheep/,
                                              # including games other members played without the maintainer
python scripts/twosheep_replay.py             # local only: replays each new game, saves its stats to raw/twosheep/
python scripts/import_twosheep.py             # dry run: shows new games, links and conflicts
python scripts/import_twosheep.py --write     # adds them to data/games.json
python scripts/build.py                       # checks the data and builds dist/ locally (about 2 minutes)
git add data/ && git commit -m "Add games from YYYY-MM-DD" && git push   # the live site only updates on push
```

Run the commands one at a time and read each one's output: if a step fails, the later ones still run and can hide the error. The fetch prints `1 saved` (or more) for each new game; `0 saved` means TwoSheep doesn't list the game yet or it isn't finished. The build takes a couple of minutes and prints `built dist/ from N games` when it's done. After the push, GitHub Actions takes about 4 minutes to deploy (`gh run list` shows its progress).

The fetch and replay scripts are kept out of this repo on purpose and live only on the maintainer's computer. They pull our own games from TwoSheep with the developer's permission (given 2026-10-11), one request a second at most, and save everything to `raw/twosheep/`, which is also not committed.

A summary has the date, start time, seats, colors, final VP, winner, VP target and map. The replay script plays each game back move by move and saves what it finds: dice, production, dev cards, VP breakdown, robber, trades, building and a turn-by-turn VP timeline. It checks every game as it goes (no hand goes negative, every 7-discard is half the hand, every final VP matches TwoSheep's) and skips any game that fails.

The importer:

- only takes finished games with 3 or more players, at least 2 of them from the group (a game of one of us with guests is left out, and removed if it was imported before);
- matches people by TwoSheep account, not username, since names change all the time. Each player's accounts are listed in `players.json` as hashes (see below). Anyone else becomes a guest;
- keeps a TwoSheep bot's seat as `bot-1` and records the seat count as `n_seats`. When a summary's seat numbers skip the bot's seat, the seats come from the game's color order;
- imports each game once, keyed on `twosheep_id`, so re-running is safe;
- links a hand-entered game to its replay when the players and VP match within a day, then fills only empty fields (seats, colors, VP target, scenario). Anything that disagrees is listed as a conflict and left alone;
- adds any new TwoSheep names to each player's `aliases`;
- names maps from TwoSheep's game mode list (`TWOSHEEP_MAPS` in `scripts/import_twosheep.py`) and lists any number it doesn't know;
- sets turns, dice, resources from dice, dev cards bought and VP breakdown from the replay stats, replacing anything typed in from the end screen (the replay is checked against TwoSheep's result; screenshots were not), lists each value it replaced, and rewrites `data/replays.json` with the rest.

`python scripts/import_twosheep.py --accounts` lists every account in the fetched games with the usernames it has used and whose it is. To add someone, put their hash in a player's `twosheep_accounts` and re-run the import: their old guest rows become theirs.

## Deploying to GitHub Pages

1. Create a repo on GitHub and push this folder to its `main` branch.
2. In the repo, open **Settings > Pages** and set **Source** to **GitHub Actions**.
3. Every push to `main` now validates the data, builds, and deploys. If the data has an error, the build fails and the live site stays as it was.

## Adding a game

Add an entry to the `games` list in `data/games.json`, then build (or just push). Any new player must first be added to `data/players.json`.

```json
{
  "id": "2026-10-18-a",
  "date": "2026-10-18",
  "platform": "twosheep",
  "source": "manual: end-of-game stats screen",
  "settings": { "vp_to_win": 14, "expansion": "seafarers", "scenario": "new_shores", "notes": "" },
  "turns": 61,
  "duration_seconds": null,
  "winner": "nd",
  "players": [
    {
      "player": "nd",
      "seat": 2,
      "game_color": "green",
      "vp": 14,
      "vp_breakdown": { "settlements": 2, "cities": 6, "vp_cards": 0, "largest_army": 2, "longest_road": 0, "islands": 4 },
      "dev_cards_bought": { "knight": 3, "victory_point": 0, "road_building": 0, "year_of_plenty": 0, "monopoly": 0 },
      "resources_from_dice": 58
    }
  ],
  "dice": { "counts": { "2": 1, "3": 3, "4": 5, "5": 7, "6": 9, "7": 10, "8": 9, "9": 6, "10": 5, "11": 4, "12": 2 } },
  "events": null
}
```

Only `id`, `date`, `winner`, and each player's `player` and `vp` are required. TwoSheep's turn time numbers are unreliable, so they aren't recorded. Everything else can be `null` or left out, and the site shows what's available.

## Data reference

### `data/players.json`

| Field | Meaning |
|---|---|
| `id` | Short permanent id used in `games.json` and URLs. Never change it once games reference it. |
| `name` | Optional. Leave it out and the site shows the person's most used TwoSheep name (the first alias), so the name keeps up as people rename. Set it to pin a fixed name instead. |
| `initials` | Optional, 1 to 4 characters. With `"player_names": "initials"` in `site.json` the site shows only these; with `"usernames"` it shows the name followed by them, as in `SheepLord (AB)`. Usernames always stay listed, collapsed, at the bottom of each player page. |
| `aliases` | Every TwoSheep username this person has played under, most used in the site's games first (then most used overall). The importer keeps this up to date from their accounts, and the site lists it, collapsed, at the bottom of their page. Names you add by hand are kept. Matching uses accounts, not these names, because two accounts can share a name. |
| `color_slot` | 1 to 8. A fallback color from a colorblind-checked palette, used only for a player with no recorded piece colors. Give everyone a different slot. The site normally draws each player in the TwoSheep color they use most (ties go to the most recent; players with more games choose first), from the `--tc-*` colors in `site/styles.css`. |
| `twosheep_accounts` | The person's TwoSheep accounts, each as the first 16 hex digits of the SHA-256 of the account id. Raw ids stay out of the repo because anyone holding one can pull that person's whole game history. `import_twosheep.py --accounts` prints the hashes. |

### `data/games.json`

| Field | Meaning |
|---|---|
| `id` | Unique game id. Date plus a letter works well. |
| `date` | `YYYY-MM-DD`. Games are ordered by date, then id, for the running totals, so letter same-day games in the order they were played. |
| `twosheep_id` | The replay id from `twosheep.io/replay/<id>`. Set by the importer; the game page links to the replay. |
| `settings.expansion` | `"seafarers"` or `"base"`. Drives the game type filter. Add new types to `EXPANSIONS` in `scripts/build.py`. |
| `settings.scenario` | For Seafarers: `"new_shores"`, `"four_islands"`, `"through_the_desert"`, `"fog_islands"`, `"six_islands"` or `"new_world"`. Leave `null` if you don't remember; the game still counts under Seafarers. Add scenarios to `SCENARIOS` in `scripts/build.py`. |
| `settings.vp_to_win` | Target VP, which varies by scenario. TwoSheep leaves the default of 10 out of its summaries, so the importer fills 10 then. When missing, the winner's VP is used instead. |
| `n_seats` | Number of seats in the game, bots included. Set by the importer; must equal the number of rows in `players`. |
| `turns` | Turn count (number of rolls). |
| `winner` | Player id of the winner. Must have the highest VP. |
| `players[].player` | A player id from `players.json`, `guest-1`, `guest-2`, ... for someone outside the group, or `bot-1`, ... for a TwoSheep bot. A bot's `vp` is `null` until its replay is decoded, since TwoSheep's summary only scores humans. |
| `players[].seat` | Turn order, 1 to n. Record it for everyone or for no one in a game. The end screen sorts by score, so note the order during the game. |
| `players[].vp_breakdown` | VP from each source (not piece counts), so cities add 2 each. Must add up to `vp`. Keys: `settlements`, `cities`, `vp_cards`, `largest_army`, `longest_road`, `islands` (the flag column on TwoSheep's summary, Seafarers only), and `other` for anything else. |
| `players[].dev_cards_bought` | Counts by card type, from the Dev Cards tab. |
| `players[].resources_from_dice` | Cards from dice rolls, gold picks included, ignoring trades, steals, dev cards and fog discoveries. Matches the production total on TwoSheep's Resources tab except in Fog Islands games, where that tab also counts cards for revealing fog. |
| `dice.counts` | Roll counts for 2 through 12, from the Dice tab. |
| `events` | Reserved for turn-by-turn logs if a proper import becomes possible. |

### `data/replays.json`

Written by the importer from decoded replays; don't edit it by hand. For each game id: `players` maps player id to that game's numbers (production by resource, expected production, robber, steals by victim, trades by partner, pieces built, dev cards played, opening dots and more), and `timeline` holds each player's VP and cards from dice after every turn that changed something (`turn` lists which).

### `data/replay_events.json`

Also written by the importer, from the version 3 decoder: every game's per-action logs. `seats` maps seat 1, 2, ... to player ids (guests and bots too), and seats inside the logs are those numbers. `states` holds each seat's VP, VP cards held, hand size, production pips (total and under the robber), cards spent by category, trades, steals, robber blocks by placer, monopoly losses, discards, the title holders, each seat's longest route and its reach (the dots on open settlement spots it could get to with at most 2 new roads or ships) after every roll and every turn, change-point encoded (a row lists only what changed; `scripts/series.py` fills rows in). `roll_log` has the cards each roll owed every seat; `robber_events` every robber and pirate move with the legal hexes and who could be robbed; plus `trade_events`, `dev_events`, `discard_events`, `monopoly_events`, `opening_picks` (with every legal corner at each pick) and `vp_events` (every change in board VP or a title, then the final reveal of VP cards). The group agreed to publish all of it, hidden information included.

The build stops with a clear message if, for example, a breakdown doesn't add up, the winner doesn't have the most VP, a player id is unknown, or `replays.json` doesn't match `games.json`.

## How the stats work

The site explains every model where it is shown: each statistic with a modeling choice has a small "i" button with the exact method. The code is split by topic:

| File | What |
|---|---|
| `scripts/statlib.py` | The statistics toolkit, standard library only: conditional logit with Breslow ties and the Firth penalty, profile likelihood intervals, exploded (Plackett-Luce) logit, game-cluster and BCa bootstraps, sup-t bands, permutation tests, REML random effects and shrinkage, Mantel-Haenszel risk differences and rate ratios, Kaplan-Meier with Greenwood intervals, Wilson intervals, and the "vs the table" markers. One interval level (95%) and the guards (10 games for a player row, 15 for a badge, 30 for a model) live here. |
| `scripts/insights.py` | Openings (the tested opening effect, robustness refits, best opener's wins, opening strength by player), seat effect, trade and bank profile, steal share, win recipe, dice calibration, "vs the table" markers, closest games. |
| `scripts/series.py` | Reads the change-point encoded state rows in `replay_events.json`. |
| `scripts/robber.py` | The shared robber model (hex choice and victim choice, 7s and knights fit separately, leave-one-mover-out expected counts, shrunk O/E), the leader tax, targeting beyond board state, cards lost to opponents, the Betrayal index (trade and rob) with its sensitivity rows, the trade partner model, pair robbery balance, roller premium, terms of trade, setup contention and the exploratory early-excess model. Fits are cached in `.cache/`. Front end: `site/network.js` (the Network page). |
| `scripts/classes.py` | Spending and trading profile with the badge rule (REML, Q gate, shrinkage, losses-only check, stability), comebacks, first-to-c conversion, the draft-order grid and pick percentile, Kaplan-Meier timing (first dev card, first city, knight hold), dev draw luck and avoidable discards. Front end: `site/classes.js`. |
| `scripts/threat.py` | The threat index (a conditional logit of the eventual winner on what the table can see at each turn end: board VP, dice income, reach, dev cards and resource cards in hand, closeness to Longest Road and Largest Army; game-cluster sandwich intervals; cross-fitted over 5 folds of games so every game is scored by a model that never saw its winner; an equal-weights version as a check), and the badges built on it: trading with the tyrant (ex ante and hindsight, conditioned on whose turn it is), Coward (robber moves that spare the top threat, against a threat-blind hex model and against the rest of the table) and Groveler (extra cards to the top threat per trade, against the table by role). Front end: `site/threat.js`. |
| `scripts/momentum.py` | The board VP race, production engine, cumulative dice luck, dev card timeline, play of the game, the snowball test and its mechanism, production share by game stage, game-centered luck, luck-adjusted wins and where lucky cards leak. Pooled model fits are cached in `.cache/`. |

Each topic module's front end is a script in `site/` that adds a page or page sections through `window.Pages` and `window.Hooks` (see the top of `site/app.js`); method notes are in `site/methods.js` and each module's script.

- **Game type and table size filters.** The build computes a complete set of stats for all games, for each expansion, and for each Seafarers scenario with at least one game, and then each of those again for 3-seat games and for games with 4 or more seats (bots count as seats). Each set is computed from scratch on its own games, the ranking included. The site keeps the choice in the URL (`#/?view=seafarers/four_islands&players=3p`), so a filtered page can be shared as a link.

- **Ranking.** Wins above expected: wins minus the sum of 1/n over games played, with n counting every seat, so only wins count and a win at a bigger table is worth more. Ties go to the higher average share of the table's VP. The luck band is the central 95% of wins minus expected if every player were equally good: exact quantiles of the Poisson binomial number of wins, each game a 1-in-n draw. (The momentum and robber models still use a chronological openskill Plackett-Luce μ as a skill covariate.)
- **Masthead.** The home page headline labels the latest game from its final score and the VP-by-turn timeline, with thresholds that scale with the VP target: a comeback if the winner trailed the best opponent by at least 35% of the target (3 VP or more) after the first quarter of the game, a close game if won by 1 VP or less, a blowout if won by at least 40% of the target, otherwise a solid win. Timelines show visible VP, so hidden VP cards can make a deficit look bigger than it was. The green number next to the winner is what the game added to their wins above expected.
- **Finishing order.** The winner is first. Others are ordered by VP, with equal VP sharing a place.
- **Guests** count as seats (in n) and as opponents for beat rate, but get no stats, no ranking and no head-to-head entries.
- **Bots** (TwoSheep's computer players) keep their seat. They count in n (expected wins use 1/n with n the number of seats) and as opponents for beat rate, but they are never listed.
- **Win rate** has a 95% Wilson interval. **Expected wins** sums 1/n over games played. **Beat rate** is the share of opponents finished ahead of, so 3, 4 and 5 player games compare fairly.
- **Dice** are compared to the 2d6 distribution with a chi-square test (10 degrees of freedom).
- **Production index** is a player's resources from dice divided by the table average for that game.
- **Dice luck** compares cards from dice with what a player's buildings would produce on average. Before each roll, every settlement adds 1 and every city 2 times the probability of each touching hex's number (dots / 36), skipping the robber's hex; the sum over the game is the expected count. The site shows actual / expected pooled over games, and the per-game difference.
- **Opening dots** add the number dots (6 and 8 are 5, 2 and 12 are 1) under both starting settlements.

All of it is computed in `scripts/build.py` and written to `dist/data/stats.json`. The front end in `site/` only renders that file.

## Project layout

```
data/            players.json, games.json, replays.json, site.json (title, subtitle, and player_names: "initials" or "usernames")
scripts/build.py validation, stats, ranking; builds dist/
scripts/fetch_twosheep.py   (local only, not in the repo) pulls game summaries and replay files into raw/
scripts/twosheep_replay.py  (local only, not in the repo) replays each game into raw/twosheep/replay_stats/
scripts/import_twosheep.py  turns them into games.json and replays.json entries
tests/           unittest suite and synthetic fixtures
site/            index.html, styles.css, app.js, charts.js (no build step, no dependencies)
.github/         workflow that builds and deploys to Pages
```

## About the data source

All games are played on [TwoSheep.io](https://twosheep.io). The developer (Odd Stone Studios) gave permission on 2026-10-11 to collect this data and asked for a link back to twosheep.io, which the site footer and How it works page carry. Keep that message somewhere safe, since TwoSheep's terms require written permission for compiling data from the service. Only include friends who are happy to appear on a public page.
