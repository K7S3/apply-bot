# Staff packet (staff/principal track)

`candid/staff_impact.py` turns the user's own experience into **STAR+I**
stories and a Markdown promo packet for staff/principal interviews.

## STAR+I

Staff+ interviews evaluate org impact, not just output. STAR+I extends
the usual STAR with **Influence**: scope of impact, what changed for
other people and teams, and what persisted after the work shipped.

- `upgrade_star(story_or_bullet) -> dict`
  - Accepts a story dict (from `stories.list_stories()`, when that
    workstream lands) or a raw resume bullet string.
  - Reframes into situation / task / action / result / influence.
  - A raw bullet maps to **action** by default; the other four fields
    become explicit `[add detail]` placeholders.
  - Idempotent: re-running on its own output is a no-op.
  - Output also carries `missing` (fields still empty) and
    `completeness` (0.0-1.0).
- `format_star_plus(story) -> str`: renders Markdown STAR+I, with a
  "still needed" note when fields are placeholders.
- `influence_score(story) -> float`: heuristic ranking signal.

## Promo packet

- `build_packet(profile, stories, tracker_records) -> str`: Markdown
  packet with: impact summary (stories ranked by influence score),
  scope trajectory (roles with scope language from the profile,
  e.g. "team of 5", or "scope not stated in resume" when unstated),
  technical leadership evidence, mentorship evidence, selected metrics,
  active interview pipeline, and open gaps.
- `save_packet(markdown, out_path) -> Path`: writes the file, creating
  parents.
- `main(argv) -> int`, `StaffError(Exception)`.

## Honesty rules

- Missing fields are `[add detail]` placeholders. Nothing is invented.
- Selected metrics are **only** numbers already present in the inputs
  (story fields, resume bullets), each printed with its source, e.g.
  `(story: Rebuilt ranking cache)`.
- The influence score is transparent keyword counting over the user's
  own words (org-wide, cross-team, adopted-by, mentored, ...), plus
  credit for a quantified result and a filled Influence section. It
  orders stories; it never creates impact.
- No em dashes anywhere (user style rule).

## CLI

```
staff story [--story ID | --bullet "..."] [--save [FILE]]
staff packet [--out FILE] [--json]
```

- `staff story --bullet "..."`: scaffold a STAR+I from one bullet,
  print to stdout. `--save` writes it under
  `candid_data/staff_packet/stories/` (or the given FILE).
- `staff story --story ID`: look up a story by id (needs
  `candid.stories`); friendly error otherwise.
- `staff packet`: builds the packet from the stored profile, stories
  (or, until the stories workstream lands, raw bullets from the
  profile's experience entries), and tracker records. Default output:
  `candid_data/staff_packet/staff-packet.md`. `--json` prints the
  packet's structured data instead.

## Notes

- `candid/stories.py` does not exist in this checkout yet. Story
  loading falls back to raw profile bullets, so the packet works
  standalone today and picks up real stories once that module lands.
- `tracker.py` is used read-only (`list_apps()`); nothing writes to it.
