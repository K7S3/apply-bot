# Narrative, References & Networking (batch 7)

Three modules for resume and profile mastery. All grounded in the
onboarded profile — nothing is ever invented. Missing information
becomes explicit `[fill in]` placeholders.

## Career narrative (`candid/narrative.py`)

Builds a spoken "tell me about yourself" script from experience entries.

```python
from candid import narrative, profile

p = profile.load_profile()

# 60s (~160 words) or 2min (~330 words) script:
# present -> past (oldest to newest) -> future
print(narrative.build_narrative(p, length="60s"))

# One-paragraph career thesis: the through-line across roles
print(narrative.story_arc(p))

# Tailored elevator pitches
print(narrative.elevator_pitch(p, audience="recruiter"))
print(narrative.elevator_pitch(p, audience="hiring-manager"))
print(narrative.elevator_pitch(p, audience="networking"))
```

**Groundedness rules.** Transitions use neutral phrasing ("I then moved to
X"). A "to focus on Y" clause is added only when Y is a profile skill that
literally appears in the next role's title or bullets — no invented
reasons for leaving, ever. Set `profile["target_roles"]` before calling
`build_narrative` to shape the "future" section; otherwise it asks you to
fill it in.

## Reference sheet (`candid/references.py`)

Referees are **user-supplied only** — this module stores and renders them,
never invents anyone. Data lives in `<DATA_DIR>/references.json`
(`CANDID_DATA_DIR` override honored).

```python
from candid import references

references.add_reference("Jane Doe", "Former manager",
                         contact="jane@example.com", notes="Managed me at Acme")
print(references.list_references())
references.remove_reference("Jane Doe")

# One-page sheet (markdown or text). Refuses to render when empty:
sheet = references.render_sheet("Keshavan Seshadri", output="markdown")
# Short alternative for resumes:
print(references.render_sheet("Keshavan Seshadri", on_request=True))
# -> "References available upon request."
```

Rendering with zero referees raises `ReferencesError` with a next-step
message telling you to `add_reference()` first.

## Networking brief (`candid/networking.py`)

One-page markdown brief: who you are (2 lines), top-3 career highlights
(ranked by a local impact heuristic — metrics, impact verbs, skill
matches), what you're looking for, your ask, and conversation starters
drawn from your domain tags.

```python
from candid import networking, profile

p = profile.load_profile()
brief = networking.build_brief(
    p,
    target_roles=["Senior ML Engineer"],   # optional
    ask="An intro to the hiring manager",  # optional
)
print(brief)

# Save to <DATA_DIR>/networking_brief.md (or pass path=...)
path = networking.save_brief(p, target_roles=["Senior ML Engineer"])
```

If you omit `target_roles` and the profile has none, a cautious guess from
seniority + domain is offered and **labeled "(inferred)"**. If you omit
`ask`, template prompts with `[fill in]` markers are used — never an
invented ask.

## Tests

```bash
python3 -m pytest tests/test_narrative.py tests/test_references.py \
    tests/test_networking.py -q
```
