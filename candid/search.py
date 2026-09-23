"""Full-text search across candid's job-search data.

Searches tracker applications (company, role, notes, jd_link, jd_text),
interview prep pack markdown files, tailored resume/cover-letter files,
and a ``debriefs`` data dir if one exists (skipped silently if missing).

Multi-term queries use AND semantics (all terms must match) and are
case-insensitive. Quoted phrases (e.g. ``"machine learning"``) count as
a single term.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from candid import config as C

KINDS = ("application", "prep_pack", "tailored", "debrief")
_SNIPPET_LEN = 160


class SearchError(Exception):
    """Raised when the search data cannot be read."""


def _parse_terms(query: str) -> list[str]:
    """Split a query into terms; quoted phrases stay together.

    >>> _parse_terms('python "machine learning"')
    ['python', 'machine learning']
    """
    terms: list[str] = []
    for m in re.finditer(r'"([^"]+)"|(\S+)', query):
        term = m.group(1) if m.group(1) is not None else m.group(2)
        term = term.strip().lower()
        if term:
            terms.append(term)
    return terms


def _count(haystack: str, term: str) -> int:
    return haystack.lower().count(term)


def _snippet(body: str, terms: list[str]) -> str:
    """~160-char context around the first term hit, with ... ellision."""
    lowered = body.lower()
    positions = [(lowered.find(t), t) for t in terms]
    positions = [(p, t) for p, t in positions if p >= 0]
    if not positions:
        text = body.strip()
        return (text[:_SNIPPET_LEN] + "...") if len(text) > _SNIPPET_LEN else text
    pos, _ = min(positions)
    half = _SNIPPET_LEN // 2
    start = max(0, pos - half)
    end = min(len(body), start + _SNIPPET_LEN)
    if end == len(body):
        start = max(0, end - _SNIPPET_LEN)
    chunk = body[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(body) else ""
    return f"{prefix}{chunk}{suffix}"


def _doc(kind: str, ref: str, title: str, body: str,
         terms: list[str]) -> dict | None:
    """Build a result dict if all terms match; None otherwise."""
    title_l = title.lower()
    body_l = body.lower()
    title_freq = sum(_count(title_l, t) for t in terms)
    body_freq = sum(_count(body_l, t) for t in terms)
    if not all(_count(title_l, t) + _count(body_l, t) > 0 for t in terms):
        return None  # AND semantics: every term must match somewhere
    score = (1000.0 if title_freq > 0 else 0.0) + title_freq * 10 + body_freq
    return {
        "kind": kind,
        "ref": ref,
        "title": title,
        "snippet": _snippet(body if body.strip() else title, terms),
        "score": float(score),
    }


def _read_text(path: Path) -> str | None:
    """Read a file as text; None if it can't be read or decoded."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _md_title(path: Path, text: str) -> str:
    """First markdown heading as a human title; else the filename stem."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
    return path.stem


def _read_tracker_apps(path: Path) -> list[dict]:
    """Read tracker records; [] if missing. Raises SearchError on bad JSON."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SearchError(
            f"Tracker file {path} is not valid JSON: {exc}. "
            "Fix or delete it, then run `python -m candid search <query>` again."
        ) from exc
    if not isinstance(data, list):
        raise SearchError(
            f"Tracker file {path} should contain a JSON list. "
            "Fix it, then run `python -m candid search <query>` again."
        )
    return [app for app in data if isinstance(app, dict)]


def _search_applications(terms: list[str], path: Path) -> list[dict]:
    results: list[dict] = []
    for app in _read_tracker_apps(path):
        company = str(app.get("company", "") or "")
        role = str(app.get("role", "") or "")
        title = f"{role} @ {company}".strip(" @")
        body_parts = [
            str(app.get("notes", "") or ""),
            str(app.get("jd_link", "") or ""),
            str(app.get("jd_text", "") or ""),
            str(app.get("status", "") or ""),
        ]
        hit = _doc("application", str(app.get("id", "")), title,
                   "\n".join(body_parts), terms)
        if hit:
            results.append(hit)
    return results


def _iter_files(directory: Path, kind: str):
    """Yield (path, text, title) for each searchable file in a directory.

    Skips missing dirs, dotfiles, non-files, and unreadable files.
    """
    if not directory.exists() or not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        text = _read_text(path)
        if text is None:
            continue
        title = _md_title(path, text) if path.suffix.lower() in (".md", ".txt") else path.stem
        yield path, text, title


def _search_dir(terms: list[str], directory: Path, kind: str) -> list[dict]:
    results: list[dict] = []
    for path, text, title in _iter_files(directory, kind):
        hit = _doc(kind, path.name, title, text, terms)
        if hit:
            results.append(hit)
    return results


def _debriefs_dir(debriefs_dir: Path | str | None) -> Path:
    if debriefs_dir is not None:
        return Path(debriefs_dir)
    # Defensive: a sibling batch may add a debriefs dir later; skip if missing.
    return getattr(C, "DEBRIEFS_DIR", C.DATA_DIR / "debriefs")


def search_all(query: str, *, path: str | Path | None = None,
               prep_dir: str | Path | None = None,
               tailor_dir: str | Path | None = None,
               debriefs_dir: str | Path | None = None) -> list[dict]:
    """Search tracker, prep packs, tailored files, and debriefs.

    All query terms must match (AND), case-insensitively; quoted phrases
    count as one term. Results are ranked title-matches first, then by
    term frequency. Empty query or missing data dirs yield no results.
    """
    terms = _parse_terms(query or "")
    if not terms:
        return []
    results: list[dict] = []
    results += _search_applications(terms, Path(path) if path else C.TRACKER_PATH)
    results += _search_dir(terms, Path(prep_dir) if prep_dir else C.PREP_PACKS_DIR,
                           "prep_pack")
    results += _search_dir(terms, Path(tailor_dir) if tailor_dir else C.TAILOR_DIR,
                           "tailored")
    results += _search_dir(terms, _debriefs_dir(debriefs_dir), "debrief")
    results.sort(key=lambda r: (-r["score"], r["kind"], r["ref"]))
    return results


def render_results(results: list[dict], limit: int = 20) -> str:
    """Plain-text rendering: one header line per hit plus a snippet line."""
    if not results:
        return "No matches found."
    lines = [f"{len(results)} match(es):"]
    for r in results[:limit]:
        lines.append(f"[{r['kind']}] {r['title']} (ref: {r['ref']}, "
                     f"score: {r['score']:.1f})")
        lines.append(f"  {r['snippet']}")
    if len(results) > limit:
        lines.append(f"... and {len(results) - limit} more "
                     f"(use --limit N to see more)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Advanced search: boolean operators, field scoping, regex, fuzzy, date bounds.
#
# The query language lives in candid.query (owned by another batch-69 worker)
# and is imported lazily so that importing candid.search never requires it.
# The contract we implement against:
#   Term(value, field, negated, regex, fuzzy, phrase)
#   Query(groups=tuple of AND-term tuples ORed, after: date|None,
#         before: date|None)
#   parse(query) -> Query; QueryError raised for invalid input;
#   VALID_FIELDS names the fields parse() accepts.
# ---------------------------------------------------------------------------


def _query_api():
    """Lazy handle to candid.query (keeps plain `import candid.search` light)."""
    from candid import query
    return query


def _levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings (classic DP, stdlib only)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _fuzzy_distance(term) -> int:
    """Max Levenshtein distance for a fuzzy term (default 1)."""
    f = term.fuzzy
    if isinstance(f, bool):
        return 1
    if isinstance(f, int):
        return max(0, f)
    return 1  # any other truthy marker (e.g. bare "~")


def _compile_term_regex(term):
    """Compile a regex term; invalid patterns raise QueryError (unwrapped)."""
    try:
        return re.compile(str(term.value), re.IGNORECASE)
    except re.error as exc:
        raise _query_api().QueryError(
            f"Invalid regex {term.value!r}: {exc}") from exc


def _match_term_text(term, text: str) -> bool:
    """Whether one term matches one text block (no field routing)."""
    if term.regex:
        return _compile_term_regex(term).search(text) is not None
    lowered = text.lower()
    value = str(term.value).lower()
    if term.fuzzy:
        n = _fuzzy_distance(term)
        return any(_levenshtein(tok, value) <= n
                   for tok in _WORD_RE.findall(lowered))
    # Plain and phrase terms: case-insensitive substring (phrase keeps space).
    return value in lowered


def _app_doc(app: dict) -> dict:
    """Uniform doc dict for a tracker application record."""
    company = str(app.get("company", "") or "")
    role = str(app.get("role", "") or "")
    jd = (str(app.get("jd_text", "") or "") + " " +
          str(app.get("jd_link", "") or "")).strip()
    title = f"{role} @ {company}".strip(" @")
    fields = {
        "company": company,
        "role": role,
        "status": str(app.get("status", "") or ""),
        "source": str(app.get("source", "") or ""),
        "notes": str(app.get("notes", "") or ""),
        "jd": jd,
        "title": title,
        "kind": "application",
    }
    body = "\n".join(p for p in (company, role, fields["status"],
                                 fields["source"], fields["notes"], jd) if p)
    return {
        "kind": "application",
        "ref": str(app.get("id", "")),
        "title": title,
        "body": body,
        "fields": fields,
        "date": _app_date(app),
    }


def _app_date(app: dict):
    """date_added as a date; None when missing or unparseable (doc is kept)."""
    raw = app.get("date_added")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _file_doc(kind: str, ref: str, title: str, text: str, file_date) -> dict:
    """Uniform doc dict for a prep_pack / tailored / debrief file."""
    fields = {
        "kind": kind,
        "title": title,
        "company": text,
        "role": text,
        "status": text,
        "source": text,
        "notes": text,
        "jd": text,
    }
    return {
        "kind": kind,
        "ref": ref,
        "title": title,
        "body": text,
        "fields": fields,
        "date": file_date,
    }


def _file_date(path: Path):
    """File mtime as a date (best effort); None when it can't be read."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None


def _gather_docs(path, prep_dir, tailor_dir, debriefs_dir) -> list[dict]:
    """All searchable docs as uniform dicts (applications + file kinds)."""
    docs = [_app_doc(app)
            for app in _read_tracker_apps(Path(path) if path else C.TRACKER_PATH)]
    for kind, directory in (
            ("prep_pack", Path(prep_dir) if prep_dir else C.PREP_PACKS_DIR),
            ("tailored", Path(tailor_dir) if tailor_dir else C.TAILOR_DIR),
            ("debrief", _debriefs_dir(debriefs_dir))):
        for fpath, text, title in _iter_files(directory, kind):
            docs.append(_file_doc(kind, fpath.name, title, text,
                                  _file_date(fpath)))
    return docs


def _term_field_text(term, doc: dict) -> str:
    """The text a term is matched against: field text, or title+body."""
    if term.field:
        return doc["fields"].get(term.field, "")
    return doc["title"] + "\n" + doc["body"]


def _group_matches(group, doc: dict) -> bool:
    """An OR-group matches when every positive term hits and no negated one."""
    for term in group:
        hit = _match_term_text(term, _term_field_text(term, doc))
        if term.negated:
            if hit:
                return False
        elif not hit:
            return False
    return True


def _term_title_body(term, doc: dict) -> tuple[bool, bool]:
    """(title_hit, body_hit) for scoring; field terms score in their section."""
    if term.field:
        hit = _match_term_text(term, doc["fields"].get(term.field, ""))
        if term.field == "title":
            return hit, False
        return False, hit
    return (_match_term_text(term, doc["title"]),
            _match_term_text(term, doc["body"]))


def _describe_term(term) -> str:
    """Short label for a matched term, e.g. 'company:stripe',
    'regex:/senior.*eng/', 'fuzzy:pythno~1'."""
    if term.regex:
        core = f"regex:/{term.value}/"
    elif term.fuzzy:
        core = f"fuzzy:{term.value}~{_fuzzy_distance(term)}"
    else:
        core = str(term.value)
    return f"{term.field}:{core}" if term.field else core


def _advanced_hit(doc: dict, group) -> dict:
    """Result dict for a doc matching an OR-group.

    Scoring starts from the classic scheme (title hits outrank: a +1000 title
    bonus, +10 per title hit, +1 per body hit) and extends it: plain/phrase
    terms keep frequency scoring like search_all; regex, fuzzy, and
    field-scoped terms add +10 per title-section hit and +1 per body-section
    hit. Negated terms only filter; they never score.
    """
    title, body = doc["title"], doc["body"]
    title_l, body_l = title.lower(), body.lower()
    title_freq = body_freq = 0
    title_hit = False
    extra = 0
    matched: list[str] = []
    for term in group:
        if term.negated:
            continue
        if not term.regex and not term.fuzzy and not term.field:
            value = str(term.value).lower()
            tf, bf = _count(title_l, value), _count(body_l, value)
            title_freq += tf
            body_freq += bf
            if tf:
                title_hit = True
            matched.append(_describe_term(term))
            continue
        t_hit, b_hit = _term_title_body(term, doc)
        if t_hit or b_hit:
            matched.append(_describe_term(term))
            if t_hit:
                extra += 10
                title_hit = True
            if b_hit:
                extra += 1
    score = title_freq * 10 + body_freq + extra
    if title_hit:
        score += 1000.0
    # Snippet: anchor on the plain/phrase terms of the winning group; when
    # the group has none (regex- or fuzzy-only), _snippet falls back to the
    # first ~160 chars of the body. Using the regex source for positioning
    # would be misleading, so we deliberately do not.
    snippet_terms = [str(t.value).lower() for t in group
                     if not t.negated and not t.regex and not t.fuzzy]
    return {
        "kind": doc["kind"],
        "ref": doc["ref"],
        "title": title,
        "snippet": _snippet(body if body.strip() else title, snippet_terms),
        "score": float(score),
        "matched": matched,
    }


def _coerce_date(value):
    """after:/before: values as dates; invalid strings raise QueryError."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise _query_api().QueryError(
                f"Invalid date {value!r}") from exc
    return None


def _in_date_range(doc_date, after, before) -> bool:
    """Inclusive after <= d <= before; a missing date never excludes a doc."""
    if doc_date is None:
        return True
    if after is not None and doc_date < after:
        return False
    if before is not None and doc_date > before:
        return False
    return True


def search_advanced(query: str, *, path=None, prep_dir=None, tailor_dir=None,
                    debriefs_dir=None, limit: int | None = None) -> list[dict]:
    """Boolean advanced search over tracker applications and file docs.

    The query language is parsed by ``candid.query.parse`` (QueryError
    propagates unchanged): terms combine with AND inside an OR-group,
    groups combine with OR; ``-term``/``NOT`` negate; ``field:value``
    scopes a term to one field; ``/re/`` is a regex term; ``term~N`` is a
    fuzzy term (any word token within Levenshtein distance N); ``"..."``
    is a phrase; ``after:YYYY-MM-DD`` / ``before:YYYY-MM-DD`` bound dates.

    Matching: a doc matches when ANY OR-group matches; a group matches when
    EVERY positive term matches and NO negated term matches. Plain/phrase
    terms are case-insensitive substrings; regex terms run
    ``re.search(pattern, title + "\\n" + body)`` case-insensitively; fuzzy
    terms match when any ``[a-z0-9]+`` token of title+body is within the
    term's edit distance. Field terms match within that field's text only:
    on applications company/role/status/source/notes map to record values,
    jd maps to ``jd_text + " " + jd_link``, title maps to
    ``"<role> @ <company>"``; on file docs kind/title map to the doc kind
    and file title while the other fields search the file body.

    Date bounds: applications are kept only when their ``date_added``
    (ISO YYYY-MM-DD) falls in the inclusive range; a missing or
    unparseable ``date_added`` never excludes a doc. File docs are filtered
    by file mtime date (best effort; unreadable mtime never excludes).

    Results carry the usual keys (kind, ref, title, snippet, score) plus
    ``matched``: short labels for the positive terms that fired, e.g.
    ``"company:stripe"``, ``"regex:/senior.*eng/"``, ``"fuzzy:pythno~1"``.
    Negated terms only filter and never appear in ``matched``. Results sort
    like search_all by ``(-score, kind, ref)``; ``limit`` truncates at the
    end. An empty query (no parsed groups) returns [].
    """
    api = _query_api()
    parsed = api.parse(query or "")
    if not parsed.groups:
        return []
    valid_fields = set(getattr(api, "VALID_FIELDS", ()) or ())
    for group in parsed.groups:
        for term in group:
            if term.field and valid_fields and term.field not in valid_fields:
                raise api.QueryError(f"Unknown field {term.field!r}")
    after = _coerce_date(parsed.after)
    before = _coerce_date(parsed.before)

    results: list[dict] = []
    for doc in _gather_docs(path, prep_dir, tailor_dir, debriefs_dir):
        if not _in_date_range(doc["date"], after, before):
            continue
        for group in parsed.groups:
            if _group_matches(group, doc):
                results.append(_advanced_hit(doc, group))
                break  # first matching OR-group explains the hit
    results.sort(key=lambda r: (-r["score"], r["kind"], r["ref"]))
    if limit is not None:
        results = results[:max(0, limit)]
    return results


def explain_query(query: str) -> str:
    """Human-readable breakdown of a parsed advanced query.

    Shows the OR-groups (each an AND of terms), which terms are negated,
    field scopes, regex/fuzzy markers, and any after:/before: date bounds.
    For the CLI --explain flag. QueryError from parse() propagates.
    """
    api = _query_api()
    parsed = api.parse(query or "")
    lines = [f"Advanced query: {(query or '').strip()!r}"]
    if not parsed.groups:
        lines.append("  (no terms: matches nothing)")
    else:
        for i, group in enumerate(parsed.groups, 1):
            lines.append(f"  OR-group {i}: every term below must hold")
            if not group:
                lines.append("    - (no terms: matches any document in range)")
            for term in group:
                tag = " [excluded]" if term.negated else ""
                lines.append(f"    - {_describe_term(term)}{tag}")
    bounds = []
    if parsed.after is not None:
        bounds.append(f"on/after {parsed.after} (inclusive)")
    if parsed.before is not None:
        bounds.append(f"on/before {parsed.before} (inclusive)")
    lines.append("  Date bounds: " + (", ".join(bounds) if bounds
                                      else "none"))
    lines.append("  A document matches when ANY OR-group matches; a group "
                 "matches when every positive term matches and no excluded "
                 "term does.")
    return "\n".join(lines)
