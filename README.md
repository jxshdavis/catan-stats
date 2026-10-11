# Catan Night

A static stats site for our Catan group: leaderboard, Plackett-Luce ratings, player pages, head-to-head records, and per-game dice and production. The data lives in this repo as JSON. A Python script computes every stat, and GitHub Pages serves the result.

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
python scripts/fetch_twosheep.py              # local only: saves new game summaries to raw/twosheep/
python scripts/import_twosheep.py             # dry run: shows new games, links and conflicts
python scripts/import_twosheep.py --write     # adds them to data/games.json
python scripts/build.py
```

The fetch script is kept out of this repo on purpose and lives only on the maintainer's computer. It pulls our own games' summaries from TwoSheep with the developer's permission (given 2026-10-11), one request a second at most, and saves them to `raw/twosheep/`, which is also not committed.

A summary has the date, start time, seats, colors, final VP, winner, VP target and map, but no dice, VP breakdown, dev cards or production. Games typed in from the end screen keep those, and the site says how many games each detail stat is based on.

The importer:

- only takes finished games with 3 or more players;
- matches people by TwoSheep account, not username, since names change all the time. Each player's accounts are listed in `players.json` as hashes (see below). Anyone else becomes a guest;
- imports each game once, keyed on `twosheep_id`, so re-running is safe;
- links a hand-entered game to its replay when the players and VP match within a day, then fills only empty fields (seats, colors, VP target, scenario). Anything that disagrees is listed as a conflict and left alone;
- adds any new TwoSheep names to each player's `aliases`;
- lists TwoSheep map numbers it can't name yet. Add them to `TWOSHEEP_MAPS` in `scripts/import_twosheep.py` and re-run to fill in scenarios.

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
| `color_slot` | 1 to 8. Picks the player's color from a colorblind-checked palette. Give everyone a different slot. |
| `twosheep_accounts` | The person's TwoSheep accounts, each as the first 16 hex digits of the SHA-256 of the account id. Raw ids stay out of the repo because anyone holding one can pull that person's whole game history. `import_twosheep.py --accounts` prints the hashes. |

### `data/games.json`

| Field | Meaning |
|---|---|
| `id` | Unique game id. Date plus a letter works well. |
| `date` | `YYYY-MM-DD`. Games are ordered by date, then id, for ratings, so letter same-day games in the order they were played. |
| `twosheep_id` | The replay id from `twosheep.io/replay/<id>`. Set by the importer; the game page links to the replay. |
| `settings.expansion` | `"seafarers"` or `"base"`. Drives the game type filter. Add new types to `EXPANSIONS` in `scripts/build.py`. |
| `settings.scenario` | For Seafarers: `"new_shores"`, `"four_islands"` or `"through_the_desert"`. Leave `null` if you don't remember; the game still counts under Seafarers. Add scenarios to `SCENARIOS` in `scripts/build.py`. |
| `settings.vp_to_win` | Target VP, which varies by scenario. When missing, the winner's VP is used instead. |
| `turns` | Turn count from the end screen. |
| `winner` | Player id of the winner. Must have the highest VP. |
| `players[].player` | A player id from `players.json`, or `guest-1`, `guest-2`, ... for someone outside the group. |
| `players[].seat` | Turn order, 1 to n. Record it for everyone or for no one in a game. The end screen sorts by score, so note the order during the game. |
| `players[].vp_breakdown` | VP from each source (not piece counts), so cities add 2 each. Must add up to `vp`. Keys: `settlements`, `cities`, `vp_cards`, `largest_army`, `longest_road`, `islands` (the flag column on TwoSheep's summary, Seafarers only), and `other` for anything else. |
| `players[].dev_cards_bought` | Counts by card type, from the Dev Cards tab. |
| `players[].resources_from_dice` | Production total from the Resources tab: resources from rolls only, ignoring trades, steals and cards. |
| `dice.counts` | Roll counts for 2 through 12, from the Dice tab. |
| `events` | Reserved for turn-by-turn logs if a proper import becomes possible. |

The build stops with a clear message if, for example, a breakdown doesn't add up, the winner doesn't have the most VP, or a player id is unknown.

## How the stats work

- **Game type filter.** The build computes a complete set of stats for all games, for each expansion, and for each Seafarers scenario with at least one game. Each set is computed from scratch on its own games, ratings included. The site keeps the choice in the URL (`#/?view=seafarers/four_islands`), so a filtered page can be shared as a link.

- **Rating.** A Plackett-Luce model over each game's full finishing order, updated game by game with the Weng-Lin Bayesian approximation ([openskill](https://github.com/vivekjoshy/openskill.py)). Everyone starts at μ = 25, σ = 8.33. The leaderboard ranks by μ − 3σ, and ratings are marked provisional below 5 games.
- **Finishing order.** The winner is first. Others are ordered by VP, with equal VP sharing a place.
- **Guests** are in the finishing order, so they move everyone else's ratings, but each guest enters every game at the prior (μ = 25, σ = 8.33) and nothing carries over. They get no stats and no head-to-head entries; they do count as opponents for beat rate.
- **Win rate** has a 95% Wilson interval. **Expected wins** sums 1/n over games played. **Beat rate** is the share of opponents finished ahead of, so 3, 4 and 5 player games compare fairly.
- **Dice** are compared to the 2d6 distribution with a chi-square test (10 degrees of freedom).
- **Production index** is a player's resources from dice divided by the table average for that game.

All of it is computed in `scripts/build.py` and written to `dist/data/stats.json`. The front end in `site/` only renders that file.

## Project layout

```
data/            players.json, games.json, site.json (title, subtitle, and player_names: "initials" or "usernames")
scripts/build.py validation, stats, ratings; builds dist/
scripts/fetch_twosheep.py   (local only, not in the repo) pulls game summaries into raw/
scripts/import_twosheep.py  turns them into games.json entries
tests/           unittest suite and synthetic fixtures
site/            index.html, styles.css, app.js, charts.js (no build step, no dependencies)
.github/         workflow that builds and deploys to Pages
```

## About the data source

All games are played on [TwoSheep.io](https://twosheep.io). The developer (Odd Stone Studios) gave permission on 2026-10-11 to collect this data and asked for a link back to twosheep.io, which the site footer and How it works page carry. Keep that message somewhere safe, since TwoSheep's terms require written permission for compiling data from the service. Only include friends who are happy to appear on a public page.
