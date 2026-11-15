#!/usr/bin/env python3
"""Short written recaps of each game, by Claude, stored in data/recaps.json.

The build writes a recap for every decoded game that does not have one yet, or whose facts changed since
its recap was written, and saves them to data/recaps.json. That file is committed, so the deployed build
(which has no API key) only reads it. A game whose recap is missing or out of date simply shows the page
without the written paragraph.

    python scripts/build.py                 # writes any missing recaps when credentials are set
    python scripts/build.py --no-recaps     # never calls the API
    python scripts/recaps.py                # only the recaps: write what is missing, then stop
    python scripts/recaps.py --game 2026-11-14-d --force     # rewrite one
    python scripts/recaps.py --dry-run --game 2026-11-14-d   # print the facts the model would see

Two ways to reach Claude, tried in this order (force one with --via or RECAPS_VIA):
  cli  the Claude Code command line (`claude -p`), which uses whatever Claude Code is logged in with, so a
       Claude subscription covers it and no API key is needed. Any ANTHROPIC_* variables are hidden from it
       so it cannot quietly bill an API key instead.
  api  the Anthropic API through the `anthropic` package (pip install anthropic; not in requirements.txt,
       because the deployed build never calls it), with ANTHROPIC_API_KEY in the environment or in .env.

What the model sees is story.facts(): the same numbers the game page shows, with players named as the site
names them. Every recap is checked before it is kept: any number in it must appear in the facts, and it
must not contain a dash the site does not use. A recap that fails twice is dropped, not stored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "recaps.json"

MODEL = "claude-opus-5-5"
PROMPT_VERSION = 1      # bump to rewrite every recap after changing SYSTEM
WORKERS = 4

SYSTEM = """You write the short recap that opens a game page on a private stats site for a group of friends who play Catan online, usually with the Seafarers expansion. The readers were at the table, or know everyone who was, and they open the page to remember what happened in that game. Every number is already shown in tables and charts below your recap, so your job is the story: how the game was won, and what made it different from an ordinary game.

You get one JSON object of facts about the game. Everything you write has to come from it. If something is not in the facts (the board layout, who traded with whom, what anyone was thinking or feeling), leave it out: the people reading were there and will notice a wrong detail, and the site's whole appeal is that it is accurate. Use only numbers that appear in the facts, exactly as they appear, without doing arithmetic on them.

How to read the facts:
- Players are named by their initials. Use each name exactly as given. A player named "a guest" is someone from outside the group. If has_bot_seat is true, one seat was a bot that the site never mentions, so do not mention it either.
- turns counts every dice roll by anyone, and a turning point's turn is on the same count. lead_changes counts how often a new player took the sole lead on the points everyone could see.
- label is the site's one-word read of the game: comeback, close, blowout or solid. winner_biggest_deficit_vp is how far behind the winner was at their worst, after the first quarter of the game.
- ending says how it finished. Hidden VP cards are development cards worth a point that nobody else can see until the game ends.
- play_of_the_game is the winner's best single turn: what it scored, and how many VP it swung against their best opponent.
- most_dangerous_looking_player_before_the_last_turn is who a model rated most likely to win from what the table could see. When winner_was_a_hidden_threat is true, the winner was not that player.
- closeness ranks this game among all the group's games, rank 1 being the closest.
- For each player: opening_dots is the strength of their two starting settlements (more is better); cards_from_dice against cards_expected_from_dice is their dice luck; notes are the things the site already flags about them.

Write two things.

headline: a newspaper-style headline for this game. At most 9 words, no period at the end, and it names the winner.

recap: 3 to 5 sentences of plain past-tense prose. Open with how it was won. Then give the one or two things that shaped the game, such as a lead that kept changing hands, the play of the game, hot or cold dice, the robber, a comeback, or a hidden VP card. End on something specific to this game, not a general remark about Catan. Most facts do not belong in the recap: pick what a player would retell afterwards.

Style: plain and specific, like a good sports brief. Dry humor is welcome when the facts earn it. No exclamation marks. Do not use em dashes or en dashes, because the site never does: use commas, colons or separate sentences. Write numbers as digits. Do not address the reader, and do not mention the facts, the data or yourself."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "At most 9 words, names the winner, no closing period."},
        "recap": {"type": "string", "description": "3 to 5 sentences of plain past-tense prose."},
    },
    "required": ["headline", "recap"],
    "additionalProperties": False,
}

NUM = re.compile(r"\d+(?:\.\d+)?")


class Skip(Exception):
    """This game gets no recap (the model declined, or its text failed the checks twice)."""


class NoCredentials(Exception):
    pass


def load_env(path=ROOT / ".env"):
    """Minimal .env reader: KEY=value lines, # comments. Only fills ANTHROPIC_* names that are not set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k.startswith("ANTHROPIC_") and v and not os.environ.get(k):
            os.environ[k] = v


def has_credentials():
    load_env()
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()   # an `ant auth login` profile


def facts_hash(facts):
    blob = json.dumps([PROMPT_VERSION, facts], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load(path=PATH):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": 1, "games": {}}


def save(doc, path=PATH):
    doc["games"] = dict(sorted(doc["games"].items()))
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def check(out, facts):
    """Problems with a recap, as sentences the model can act on. Empty means keep it."""
    problems = []
    text = f"{out.get('headline', '')} {out.get('recap', '')}"
    if not out.get("headline", "").strip() or not out.get("recap", "").strip():
        problems.append("The headline or the recap is empty.")
    allowed = set(NUM.findall(json.dumps(facts, ensure_ascii=False)))
    extra = sorted({n for n in NUM.findall(text) if n not in allowed})
    if extra:
        problems.append(f"These numbers are not in the facts: {', '.join(extra)}. Use only numbers that appear in the facts, without arithmetic.")
    if "—" in text or "–" in text:
        problems.append("It contains an em dash or en dash. Use commas, colons or separate sentences.")
    if len(out.get("headline", "").split()) > 9:
        problems.append("The headline is longer than 9 words.")
    if "!" in text:
        problems.append("It contains an exclamation mark.")
    return problems


def ask_cli(messages):
    """One request through Claude Code's print mode, on its own login. Returns ({"headline", "recap"}, model)."""
    prompt = messages[0]["content"]
    if len(messages) > 1:   # the retry: print mode takes one prompt, so the earlier draft goes inline
        prompt += "\n\nYour earlier draft:\n\n" + messages[1]["content"] + "\n\n" + messages[2]["content"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_") and k != "CLAUDECODE"}
    try:
        r = subprocess.run(
            ["claude", "-p", "--system-prompt", SYSTEM, "--tools", "", "--json-schema", json.dumps(SCHEMA),
             "--output-format", "json", "--model", MODEL, "--no-session-persistence", "--strict-mcp-config",
             "--disable-slash-commands"],
            input=prompt, capture_output=True, text=True, env=env, timeout=600,
            cwd=tempfile.gettempdir())      # away from the repo, so no project instructions are loaded
    except subprocess.TimeoutExpired:
        raise Skip("the claude command timed out")
    try:
        res = json.loads(r.stdout)
    except ValueError:
        tail = (r.stderr or r.stdout).strip()[-200:]
        if "log in" in tail.lower() or "login" in tail.lower():
            raise NoCredentials("Claude Code is not logged in (run `claude` once and sign in)")
        raise Skip(f"the claude command failed: {tail}")
    if res.get("is_error") or not isinstance(res.get("structured_output"), dict):
        msg = str(res.get("result") or res.get("subtype") or "no structured output")[:200]
        if "login" in msg.lower() or "api key" in msg.lower():
            raise NoCredentials(f"Claude Code could not authenticate: {msg}")
        raise Skip(f"the claude command returned an error: {msg}")
    return res["structured_output"], next(iter(res.get("modelUsage") or {}), MODEL)


def ask(client, messages):
    """One request through the API. Returns the parsed {"headline", "recap"} and the model that wrote it."""
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a safety classifier declines the request, the API reruns it on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise Skip("the model declined")
    if resp.stop_reason == "max_tokens":
        raise Skip("the reply was cut off")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text), resp.model


def write_one(client, facts):
    """A checked recap for one game. One retry with the problems spelled out, then Skip.
    client is an API client, or None to go through the Claude Code command line."""
    send = (lambda m: ask(client, m)) if client is not None else ask_cli
    user = "Facts for this game:\n\n" + json.dumps(facts, indent=1, ensure_ascii=False)
    messages = [{"role": "user", "content": user}]
    out, model = send(messages)
    problems = check(out, facts)
    if problems:
        messages += [{"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
                     {"role": "user", "content": "That draft can't be published as it is:\n- " + "\n- ".join(problems)
                      + "\n\nPlease write it again with those fixed."}]
        out, model = send(messages)
        problems = check(out, facts)
        if problems:
            raise Skip("; ".join(problems))
    return {"headline": out["headline"].strip().rstrip("."), "recap": out["recap"].strip(), "model": model}


def current(doc, facts_by_gid):
    """The stored recaps that still match their game's facts: what the site shows."""
    out = {}
    for gid, f in facts_by_gid.items():
        r = doc["games"].get(gid)
        if r and r.get("hash") == facts_hash(f):
            out[gid] = {"headline": r["headline"], "recap": r["recap"]}
    return out


def missing(doc, facts_by_gid):
    have = current(doc, facts_by_gid)
    return [gid for gid in facts_by_gid if gid not in have]


def pick_backend(via=None):
    """"cli" or "api": the one asked for, else the Claude Code login when there is one, else an API key."""
    via = via or os.environ.get("RECAPS_VIA") or "auto"
    if via not in ("auto", "cli", "api"):
        raise NoCredentials(f"unknown backend {via!r} (use cli or api)")
    if via in ("auto", "cli") and shutil.which("claude"):
        return "cli"
    if via == "cli":
        raise NoCredentials("the claude command is not installed (Claude Code)")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise NoCredentials("no way to reach Claude: install Claude Code and log in, or pip install anthropic and set ANTHROPIC_API_KEY")
    if not has_credentials():
        raise NoCredentials("no way to reach Claude: install Claude Code and log in, or set ANTHROPIC_API_KEY in .env")
    return "api"


def ensure(doc, facts_by_gid, client=None, only=None, force=False, limit=None, log=print, via=None, on_write=None):
    """Write the recaps that are missing or out of date into doc. Returns (written, skipped).
    on_write(doc) is called after each one, so a long run can save as it goes."""
    todo = [g for g in (only or facts_by_gid) if g in facts_by_gid and (force or g in missing(doc, facts_by_gid))]
    if limit:
        todo = sorted(todo)[-limit:]      # game ids start with the date, so these are the newest
    if not todo:
        return 0, {}
    anthropic = None
    if client is None and pick_backend(via) == "api":
        import anthropic
        client = anthropic.Anthropic()
    lock = threading.Lock()
    written, skipped = 0, {}

    def keep(gid, rec, err):
        nonlocal written
        with lock:
            if rec:
                doc["games"][gid] = {"hash": facts_hash(facts_by_gid[gid]), **rec}
                written += 1
                log(f"  recap {gid}: {rec['headline']}")
                if on_write:
                    on_write(doc)
            else:
                skipped[gid] = str(err)
                log(f"  recap {gid}: skipped ({err})")

    def job(gid):
        out = attempt(gid)
        if not isinstance(out[2], NoCredentials):
            keep(*out)
        return out

    def attempt(gid):
        try:
            return gid, write_one(client, facts_by_gid[gid]), None
        except Skip as e:
            return gid, None, str(e)
        except NoCredentials as e:
            return gid, None, e
        except TypeError as e:          # the SDK's "Could not resolve authentication method"
            if "authentication" in str(e).lower():
                return gid, None, NoCredentials("no Anthropic credentials (set ANTHROPIC_API_KEY in .env or the environment)")
            return gid, None, f"TypeError: {e}"
        except Exception as e:          # typed below when the SDK is loaded
            if anthropic is not None and isinstance(e, anthropic.AuthenticationError):
                return gid, None, NoCredentials("the API rejected the credentials")
            if anthropic is not None and isinstance(e, (anthropic.RateLimitError, anthropic.APIConnectionError)):
                return gid, None, f"{type(e).__name__}: try again later"
            if anthropic is not None and isinstance(e, anthropic.APIStatusError):
                return gid, None, f"API error {e.status_code}: {e.message}"
            return gid, None, f"{type(e).__name__}: {e}"     # one bad game must not lose the others

    # The first game goes alone, so a missing or rejected login stops the run after one request.
    first = job(todo[0])
    if isinstance(first[2], NoCredentials):
        raise first[2]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for out in pool.map(job, todo[1:]):
            if isinstance(out[2], NoCredentials):
                skipped[out[0]] = str(out[2])
    return written, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", action="append", help="only this game id (repeatable)")
    ap.add_argument("--force", action="store_true", help="rewrite even when a current recap is stored")
    ap.add_argument("--limit", type=int, help="write at most this many, newest games first")
    ap.add_argument("--dry-run", action="store_true", help="print the facts the model would see and stop")
    ap.add_argument("--via", choices=["auto", "cli", "api"], default=None,
                    help="cli: Claude Code's login (a subscription covers it); api: an API key; default: cli when installed")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    import build
    facts_by_gid = build.recap_facts(build.load_stats())
    if args.dry_run:
        for gid in args.game or list(facts_by_gid)[-1:]:
            print(json.dumps(facts_by_gid[gid], indent=1, ensure_ascii=False))
        return 0
    doc = load()
    try:
        written, skipped = ensure(doc, facts_by_gid, only=args.game, force=args.force, limit=args.limit, via=args.via,
                                  on_write=save)
    except NoCredentials as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    left = len(missing(doc, facts_by_gid))
    print(f"recaps: {written} written, {len(skipped)} skipped, {left} of {len(facts_by_gid)} games still without one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
