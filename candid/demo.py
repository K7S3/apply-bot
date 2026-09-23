"""One-command narrated tour of candid on fictional sample data.

``python -m candid demo`` runs the core loop - onboard, match, tailor,
track, prep - against the fictional samples in ``samples/candid/``
(Alex Rivera's sample resume and a sample JD), printing a friendly
narrated tour of the key outputs.

Data isolation: the tour runs in a fresh temporary data directory (or
``--keep DIR``), by rebinding ``candid.config`` paths in-process, so the
user's real candid data is never touched.

Non-interactive, local-only, completes in seconds, exits 0.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path

#: config attributes that point inside the data dir; rebound for the demo.
_DATA_ATTRS = (
    "DATA_DIR",
    "PROFILE_PATH",
    "TRACKER_PATH",
    "OFFERS_PATH",
    "SALARY_DB",
    "PREP_PACKS_DIR",
    "TAILOR_DIR",
    "GMAIL_PROPOSALS_PATH",
)

#: fictional demo job, matching samples/candid/sample_jd.txt
_DEMO_COMPANY = "Acme Analytics"
_DEMO_ROLE = "Senior Data Scientist"


def _redirect_data_dir(path: Path):
    """Point all candid data paths at ``path``; returns a restore function."""
    from candid import config as C

    saved = {name: getattr(C, name) for name in _DATA_ATTRS}
    saved_env = os.environ.get("CANDID_DATA_DIR")

    os.environ["CANDID_DATA_DIR"] = str(path)
    path = Path(path)
    C.DATA_DIR = path
    C.PROFILE_PATH = path / "profile.json"
    C.TRACKER_PATH = path / "tracker.json"
    C.OFFERS_PATH = path / "offers.json"
    C.SALARY_DB = path / "salary.db"
    C.PREP_PACKS_DIR = path / "prep_packs"
    C.TAILOR_DIR = path / "tailored"
    C.GMAIL_PROPOSALS_PATH = path / "gmail_proposals.json"
    C.ensure_data_dirs()

    def restore():
        for name, value in saved.items():
            setattr(C, name, value)
        if saved_env is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = saved_env

    return restore


def _banner(char: str, text: str) -> str:
    bar = char * 64
    return f"{bar}\n{text}\n{bar}"


def _step(n: int, total: int, title: str, command: str) -> str:
    return (f"\n[{n}/{total}] {title}\n"
            f"$ {command}\n")


def _head(text: str, n: int) -> str:
    lines = text.splitlines()
    out = lines[:n]
    if len(lines) > n:
        out.append(f"... ({len(lines) - n} more lines)")
    return "\n".join(out)


def _run_tour(data_dir: Path) -> None:
    from candid import config as C
    from candid import match as M
    from candid import prep as PR
    from candid import profile as P
    from candid import tailor as T
    from candid import tracker as TR

    samples = C.SAMPLES_DIR
    resume_path = samples / "sample_resume.md"
    jd = (samples / "sample_jd.txt").read_text(encoding="utf-8")
    company, role = _DEMO_COMPANY, _DEMO_ROLE

    print(_banner("=", " candid demo - a 60-second tour (fictional sample data)"))
    print("Alex Rivera is a fictional sample candidate; Acme Analytics is a\n"
          "fictional company. Nothing here is real.")
    print(f"\nEverything below runs in a throwaway data dir:\n  {data_dir}\n"
          "Your real candid data is untouched.")

    # 1. onboard -----------------------------------------------------------
    print(_step(1, 5, "onboard - parse the sample resume into a profile",
                "python -m candid onboard --resume samples/candid/sample_resume.md"))
    prof = P.onboard(resume_path=resume_path)
    print(P.profile_card(prof))
    print(f"\nProfile stored at {C.PROFILE_PATH} - inspectable JSON, yours to keep.")

    # 2. match -------------------------------------------------------------
    print(_step(2, 5, "match - score the sample JD against the profile",
                "python -m candid match --jd samples/candid/sample_jd.txt "
                f'--company "{company}" --role "{role}"'))
    result = M.score_match(prof, jd, title=role, company=company)
    print(_head(M.render_report(result, company=company, title=role), 40))

    # 3. tailor ------------------------------------------------------------
    print(_step(3, 5, "tailor - build a resume tailored to this JD",
                "python -m candid tailor resume --jd samples/candid/sample_jd.txt "
                f'--company "{company}" --role "{role}"'))
    tailored = T.build_resume(prof, jd, company=company, role=role)
    out_path = C.TAILOR_DIR / "demo_acme_analytics_resume.md"
    out_path.write_text(tailored, encoding="utf-8")
    print(_head(tailored, 26))
    print(f"\nFull tailored resume saved to {out_path}")
    print("(Grounded in the profile - tailor reorders your bullets, "
          "never invents experience.)")

    # 4. track -------------------------------------------------------------
    print(_step(4, 5, "track - save the job to the application tracker",
                f'python -m candid track add --company "{company}" '
                f'--role "{role}"'))
    rec = TR.add(company, role, status="saved",
                 notes="Added by `candid demo` (fictional sample job).")
    print(f"Added application #{rec['id']}: {rec['role']} @ {rec['company']} "
          f"[{rec['status']}]")
    print(TR.render_list(TR.list_apps()))

    # 5. prep --------------------------------------------------------------
    print(_step(5, 5, "prep - build an interview prep pack",
                f'python -m candid prep --company "{company}" --role "{role}" '
                "--app-id 1"))
    markdown, pack_path = PR.build_pack(prof, company, role, jd=jd,
                                        app_id=rec["id"])
    print(f"Prep pack saved to {pack_path} "
          f"({len(markdown.splitlines())} lines)")
    print("Preview:")
    print(_head(markdown, 18))


def cmd_demo(args) -> None:
    """Run the narrated demo tour in an isolated data dir. Exits 0."""
    started = time.perf_counter()

    if args.keep:
        data_dir = Path(args.keep).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        temp = None
    else:
        temp = tempfile.TemporaryDirectory(prefix="candid-demo-")
        data_dir = Path(temp.name)

    restore = _redirect_data_dir(data_dir)
    try:
        _run_tour(data_dir)
    finally:
        restore()
        if temp is not None:
            temp.cleanup()

    elapsed = time.perf_counter() - started
    print("\n" + _banner("-", " demo complete"))
    print(f"Done in {elapsed:.1f}s.")
    if args.keep:
        print(f"Demo data kept at {data_dir} - poke around, delete it whenever.")
    else:
        print("The throwaway data dir was removed. Re-run with "
              "`--keep DIR` to inspect the data.")
    print("Try it for real: `python -m candid onboard --resume <your-resume>`")


def register(subparsers) -> None:
    """Add the `demo` command to the CLI parser."""
    s = subparsers.add_parser(
        "demo",
        help="Run a narrated end-to-end tour on fictional sample data "
             "(uses a throwaway data dir; your data is untouched).",
        description="A 60-second narrated tour: onboard, match, tailor, track "
                    "and prep, run against the fictional samples in "
                    "samples/candid/. Everything happens in a temporary data "
                    "directory so your real candid data is never touched.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python -m candid demo\n"
               "  python -m candid demo --keep /tmp/candid-demo  # inspect the data",
    )
    s.add_argument("--keep", metavar="DIR", default=None,
                   help="Persist the demo data in DIR for inspection instead "
                        "of using (and deleting) a temporary directory")
    s.set_defaults(func=cmd_demo)
