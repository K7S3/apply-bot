# Competing-offer leverage playbook (`leverage`)

Turns the offers in `candid offer` into usable negotiation leverage. Ten
features, one command group:

```
python -m candid leverage --help
```

## The ten features

1. **Register** — attach leverage metadata to an offer: status
   (`verbal`/`written`/`signed`/`declined`/`expired`), decision deadline,
   recruiter contact.
   ```
   python -m candid offer add --company Acme --role "Data Scientist" --base 180000 --equity 200000
   python -m candid leverage add --offer-id 1 --status written --deadline 2026-10-15 --contact Jane
   python -m candid leverage list
   ```
   Only `verbal` and `written` offers count as leverage. A verbal offer is
   weak leverage — it can evaporate, and the tooling says so everywhere.

2. **Ethical playbook** — ten rules for using competing offers without
   bluffing, lying, or burning bridges (`leverage playbook`). The short
   version: only cite offers that exist, share proof when asked, name real
   numbers, never invent a deadline.

3. **Timeline coordination** — `leverage timeline` sorts every deadline and
   emits a *sequenced* action plan: defuse the earliest deadline first
   (extend or decide), use it to accelerate slower processes, and flag
   deadlines that land within a week of each other as overlaps to exploit.

4. **Scenario scripts** — eight scripts, one per situation
   (`leverage script --which KEY --set k=v`; `--which index` lists them):

   | Key | When to use it |
   |---|---|
   | `first_disclosure` | First mention of a competing offer, with proof offered |
   | `accelerate_process` | Ask a slow company to compress remaining steps |
   | `extension_request` | Ask for a later decision date (call version) |
   | `share_offer_letter` | How to share the letter as proof, safely |
   | `match_ask` | Ask company B to match/beat company A's written number |
   | `best_and_final` | One-shot best-and-final ask against a real deadline |
   | `exploding_response` | Calm pushback on an exploding offer |
   | `decline_graceful` | Decline well; keep the door and your reputation open |

   Scripts are templates — adapt them, never send verbatim without reading.

5. **BATNA integration** — `leverage batna` computes your BATNA from your
   best *written* offer (normalized $/yr from `candid offer`), derives a
   walk-away number (the BATNA value) and an opening target (BATNA + ~7%),
   and warns loudly when the BATNA is verbal-only.

6. **Extension drafts** — `leverage extend --offer-id 1 --days 7 --reason
   final-rounds` drafts the deadline-extension email, computing the new
   date from the registered deadline. Reasons: `final-rounds`,
   `family-decision`, `logistics`, or free text.

7. **Deadline tracker** — `leverage deadlines` shows every active deadline
   with days-left and urgency, plus warnings: overdue, due within 3 days,
   verbal-only, or missing deadline.

8. **Disclosure log** — the honesty feature. After every call/email where
   you mention a competing offer, log what you actually said:
   ```
   python -m candid leverage log --company Acme --person Jane --channel call \
     --said "told her about the $250k Beta offer, deadline Oct 1"
   python -m candid leverage log --list
   ```
   Re-read it before every negotiation call. If two entries disagree, fix
   the record with the recruiter before it spreads.

9. **Leverage score** — `leverage score` gives 0–100 from written offers
   (40), deadline runway (25), breadth of alternatives (20), minus
   penalties for verbal-only and exploding deadlines — plus which levers
   to pull next.

10. **Decision plan** — `leverage decide` recommends accept / negotiate /
    hold / decline per offer and prints if-then branches ("If Acme reaches
    $X → accept; if Beta beats Acme by >5% → switch; else take the BATNA").

Plus one glue command: `leverage brief --offer-id 1` — a one-page
negotiation brief (offer comp, deadline, BATNA, walk-away, target, score,
suggested script) to read before the call.

## How it fits together

```
offer add → leverage add (deadline, status) → leverage timeline
                                                → leverage score
                                                → leverage batna
  per company:  leverage brief --offer-id N
                leverage script --which ...   (during the negotiation)
                leverage log ...              (after every disclosure)
                leverage decide               (when deadlines near)
```

## Storage

`candid_data/leverage.json` (git-ignored): per-offer leverage metadata and
the disclosure log. Comp math is never duplicated here — it always comes
from `candid offer`.

## Testing

`python3 -m pytest tests/test_leverage.py -q` — 45 tests covering all ten
features, the brief, and CLI wiring.
