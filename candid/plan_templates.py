"""Role-family templates for the 30-60-90 day plan generator.

Each template is plain data (no PII, no network calls): three phases with
concrete goals, learning objectives with resources, stakeholder archetypes
with first-meeting questions, and draft success metrics. ``candid/plan.py``
turns a template into a personalized, trackable plan.
"""

from __future__ import annotations

import copy

# ---------------------------------------------------------------------------
# shared building blocks
# ---------------------------------------------------------------------------

PHASE_DEFS = [
    {"key": "p30", "days": "1-30", "title": "Days 1-30: Learn",
     "theme": "Absorb context. Meet the team, learn the systems and rituals, "
              "and ship something small to prove the loop works end to end."},
    {"key": "p60", "days": "31-60", "title": "Days 31-60: Contribute",
     "theme": "Become a net contributor. Take on scoped work independently, "
              "build relationships across the team, and start improving "
              "things you touch."},
    {"key": "p90", "days": "61-90", "title": "Days 61-90: Own",
     "theme": "Own outcomes. Drive a meaningful piece of work, influence "
              "team direction, and set yourself up for the next 90 days."},
]

WEEK_RANGES = {"p30": (1, 4), "p60": (5, 8), "p90": (9, 12)}

REFLECTION_PROMPTS = [
    "What did you ship or learn this week that moved the plan forward?",
    "Which stakeholder relationship got stronger, and what is the next step?",
    "What is the biggest blocker or open question right now?",
    "What would you do differently next week?",
]

# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------

ROLE_TEMPLATES: dict[str, dict] = {}


def _t(label: str, match: list[str], phases: list[dict], learning: list[dict],
       stakeholders: list[dict], metrics: list[dict]) -> dict:
    return {"label": label, "match": match, "phases": phases,
            "learning": learning, "stakeholders": stakeholders,
            "metrics": metrics}


def _g(text: str, week: int, kind: str) -> dict:
    return {"text": text, "week": week, "kind": kind}


def _l(topic: str, why: str, resources: list[str], priority: str = "high") -> dict:
    return {"topic": topic, "why": why, "resources": resources,
            "priority": priority}


def _s(role: str, cadence: str, first_meeting: list[str],
       notes: str = "") -> dict:
    return {"role": role, "cadence": cadence,
            "first_meeting": first_meeting, "notes": notes}


def _m(phase: str, metric: str, how_measured: str) -> dict:
    return {"phase": phase, "metric": metric, "how_measured": how_measured}


# --- backend ---------------------------------------------------------------
ROLE_TEMPLATES["backend"] = _t(
    "Backend / Server Engineer",
    ["backend", "back-end", "server", "api", "platform engineer",
     "software engineer", "swe"],
    [
        {"key": "p30", "goals": [
            _g("Set up local dev environment and ship a first PR (docs, test, or small bug) by end of week 2", 2, "delivery"),
            _g("Map the core services you will touch: owners, data flows, and deploy pipelines", 3, "learning"),
            _g("Read the team's architecture docs and recent ADRs/design docs", 3, "learning"),
            _g("Shadow oncall for one rotation; learn the incident process and runbooks", 4, "learning"),
            _g("Hold intro 1:1s with every teammate and your manager", 2, "relationship"),
        ]},
        {"key": "p60", "goals": [
            _g("Own a scoped feature end to end: design, implement, test, deploy", 6, "delivery"),
            _g("Add or improve observability (metrics, tracing, or structured logging) on one service", 6, "delivery"),
            _g("Take a supervised oncall shift and resolve at least one alert independently", 7, "delivery"),
            _g("Review at least 10 pull requests; leave substantive, kind feedback", 8, "relationship"),
            _g("Write a short design doc or RFC for upcoming work and get it reviewed", 8, "delivery"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a service area or component: be the person others ask about it", 10, "delivery"),
            _g("Drive one reliability or performance improvement with before/after numbers", 11, "delivery"),
            _g("Help onboard or mentor the next new hire, intern, or a junior teammate", 11, "relationship"),
            _g("Give a lunch-and-learn or write a wiki post on something you learned", 12, "relationship"),
            _g("Agree SLOs / error budgets for your area with your manager and SRE", 12, "delivery"),
        ]},
    ],
    [
        _l("System architecture and data flows",
           "You cannot debug or design what you cannot draw from memory.",
           ["Internal architecture docs and ADRs", "Service dependency graph / service catalog"],
           "high"),
        _l("CI/CD and deployment pipeline",
           "Shipping confidently requires knowing exactly how code reaches production.",
           ["Team runbook: build, test, deploy, rollback", "Pair with a teammate on a deploy"],
           "high"),
        _l("Observability stack (metrics, tracing, logs)",
           "Production literacy: find and explain any request's path through the system.",
           ["Dashboards for your services", "Trace one real user request end to end"],
           "high"),
        _l("Codebase idioms and testing strategy",
           "Match house style before innovating; know what 'good' looks like here.",
           ["Recent exemplary PRs", "Testing pyramid doc / coverage standards"],
           "medium"),
        _l("Oncall and incident management",
           "Calm, fast incident response is a core backend skill.",
           ["Incident postmortems from the last quarter", "Shadow rotation, then supervised shift"],
           "medium"),
    ],
    [
        _s("Engineering manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "How do you prefer status updates: async notes or live walkthrough?",
            "What is the biggest risk to the team's roadmap right now?"]),
        _s("Onboarding buddy", "daily for first 2 weeks, then as needed",
           ["What do you wish someone had told you in your first month?",
            "Which docs are stale and which are actually trustworthy?",
            "Who is the expert on each service I will touch?"]),
        _s("Tech lead / staff engineer", "biweekly",
           ["What is the long-term technical direction of our stack?",
            "Where is the tech debt that hurts the most?",
            "How do design reviews work here?"]),
        _s("Product manager", "biweekly",
           ["What customer problems are we solving this quarter?",
            "How are priorities decided when everything is urgent?"]),
        _s("SRE / oncall rotation", "during shadow weeks",
           ["Walk me through the last sev: timeline, what helped, what did not",
            "Which alerts are noisy vs. which ones always mean real trouble?"]),
        _s("Skip-level manager", "once in first 60 days",
           ["What does the org need most from our team this half?",
            "What distinguishes strong performers at my level here?"]),
    ],
    [
        _m("30", "First PR merged within 10 working days", "PR merge date vs start date"),
        _m("30", "Intro 1:1s completed with all teammates", "Calendar invites done"),
        _m("60", "One scoped feature shipped to production", "Deploy record / changelog"),
        _m("60", "At least 10 PRs reviewed", "Code review tool history"),
        _m("90", "Own a component: documented runbook or README exists", "Repo/wiki link"),
        _m("90", "One measurable reliability or performance win (e.g. p99 down X%, error rate down Y%)",
           "Before/after dashboard screenshots"),
    ],
)

# --- frontend --------------------------------------------------------------
ROLE_TEMPLATES["frontend"] = _t(
    "Frontend / Web Engineer",
    ["frontend", "front-end", "web", "react", "ui engineer", "client"],
    [
        {"key": "p30", "goals": [
            _g("Set up the app locally and ship a first UI PR (copy fix, small component, or story) by week 2", 2, "delivery"),
            _g("Learn the component library / design system: when to reuse vs build", 3, "learning"),
            _g("Understand the build, bundling, and release process for web", 3, "learning"),
            _g("Hold intro 1:1s with engineers, a designer, and your PM", 2, "relationship"),
            _g("Read the accessibility and performance guidelines the team follows", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Own a user-facing feature slice: from design handoff to production", 6, "delivery"),
            _g("Fix or prevent one class of UI bug (flaky visual test, a11y issue, or perf regression)", 6, "delivery"),
            _g("Add tests (unit/integration/visual) for the areas you touch", 7, "delivery"),
            _g("Pair with design on one feature to tighten the design-engineering handoff", 7, "relationship"),
            _g("Review 10+ PRs with attention to UX details and code quality", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a product surface or component area end to end", 10, "delivery"),
            _g("Drive a measurable web-performance improvement (e.g. LCP/INP) or accessibility pass", 11, "delivery"),
            _g("Contribute a reusable component or pattern back to the design system", 11, "delivery"),
            _g("Present a frontend talk or write-up: something the wider org can reuse", 12, "relationship"),
            _g("Define frontend quality bars (perf budgets, a11y checks) with the team", 12, "process"),
        ]},
    ],
    [
        _l("Component library and design system",
           "Consistency and speed come from reuse, not reinvention.",
           ["Design system docs and Storybook", "Figma libraries the team uses"], "high"),
        _l("Build, bundling, and deploy pipeline",
           "Know how your code ships to users and how to roll back.",
           ["Frontend deploy runbook", "Bundle analyzer output for the main app"], "high"),
        _l("Web performance fundamentals (Core Web Vitals)",
           "Performance is a feature users feel on every page.",
           ["Lighthouse / WebPageTest baselines", "Team perf budget doc"], "high"),
        _l("Accessibility (a11y) standards",
           "Shipping inaccessible UI excludes users and creates rework.",
           ["WCAG checklist the team follows", "Screen-reader smoke test of your feature"], "medium"),
        _l("Testing strategy (unit, integration, visual)",
           "Confidence to refactor comes from test coverage in the right places.",
           ["Existing test suites for your area", "Visual regression tooling"], "medium"),
    ],
    [
        _s("Engineering manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "Which product surfaces are highest priority this quarter?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["Which parts of the codebase are safe to change vs fragile?",
            "How does design handoff actually work here?"]),
        _s("Product designer(s)", "biweekly",
           ["How do you like to collaborate during build: async comments or pairing?",
            "What is the source of truth when Figma and code disagree?"]),
        _s("Product manager", "biweekly",
           ["What user problems are we solving this quarter?",
            "How do we measure whether a UI change worked?"]),
        _s("Tech lead / staff engineer", "biweekly",
           ["What is the frontend architecture direction (e.g. RSC, islands, micro-frontends)?",
            "Where is the frontend tech debt that hurts most?"]),
    ],
    [
        _m("30", "First UI PR merged within 10 working days", "PR merge date vs start date"),
        _m("60", "One user-facing feature shipped to production", "Release notes / changelog"),
        _m("60", "Tests added for all new UI code you wrote", "Coverage / PR checklist"),
        _m("90", "One measurable perf or a11y improvement with before/after numbers",
           "Lighthouse / axe reports"),
        _m("90", "Reusable component or pattern contributed to the design system",
           "Design system changelog entry"),
    ],
)

# --- mobile ----------------------------------------------------------------
ROLE_TEMPLATES["mobile"] = _t(
    "Mobile Engineer (iOS / Android)",
    ["mobile", "ios", "android", "react native", "flutter"],
    [
        {"key": "p30", "goals": [
            _g("Build and run the app on device/simulator; ship a first PR by week 2", 2, "delivery"),
            _g("Learn the release train: branches, beta distribution, store submission", 3, "learning"),
            _g("Understand the app architecture (navigation, state, networking, persistence layers)", 3, "learning"),
            _g("Hold intro 1:1s with mobile teammates, QA, and your PM", 2, "relationship"),
            _g("Read crash-reporting and analytics dashboards for the current release", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Own a feature through a full release cycle, including store submission notes", 6, "delivery"),
            _g("Fix a top crash or ANR from the crash reporter", 6, "delivery"),
            _g("Add UI and unit tests for your feature area", 7, "delivery"),
            _g("Pair with QA on device-matrix testing for one release", 7, "relationship"),
            _g("Review 10+ PRs; learn the team's platform conventions", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a product area of the app (e.g. onboarding, checkout, settings)", 10, "delivery"),
            _g("Drive an app-health improvement: crash-free rate, startup time, or app size", 11, "delivery"),
            _g("Contribute to shared mobile infrastructure (CI, design system, or tooling)", 11, "delivery"),
            _g("Write the release retrospective or onboarding guide update for your area", 12, "process"),
            _g("Propose the next quarter's mobile quality goals with data", 12, "delivery"),
        ]},
    ],
    [
        _l("App architecture and platform idioms",
           "Platform conventions keep the app maintainable and reviewable.",
           ["Architecture doc (MVVM/MVI/Clean)", "Platform Human Interface / Material guidelines"], "high"),
        _l("Release process and store policies",
           "A missed review guideline can delay a launch by days.",
           ["Release runbook and train calendar", "App Store / Play review guidelines"], "high"),
        _l("Crash reporting and performance tooling",
           "Real-user health metrics are the mobile quality bar.",
           ["Crash reporter dashboards", "Startup-time and ANR monitors"], "high"),
        _l("CI for mobile (builds, signing, distribution)",
           "Fast, reliable builds unblock the whole team.",
           ["Mobile CI pipeline docs", "Beta distribution tool (TestFlight / Firebase)"], "medium"),
        _l("Accessibility on mobile (VoiceOver / TalkBack)",
           "Platform accessibility APIs are table stakes for quality apps.",
           ["Platform a11y checklist", "Manual screen-reader pass of your feature"], "medium"),
    ],
    [
        _s("Engineering manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "Which app areas are the highest priority this quarter?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["How do I get a build onto a real device fastest?",
            "Which modules are safe to change vs fragile?"]),
        _s("QA engineer(s)", "weekly during release weeks",
           ["What is the device matrix for testing?",
            "How do you like bugs filed: what makes a great bug report here?"]),
        _s("Product manager", "biweekly",
           ["What does the mobile roadmap look like vs web?",
            "How do we decide what is mobile-only vs shared?"]),
        _s("Designer(s)", "biweekly",
           ["How do you spec mobile interactions and edge cases?",
            "What is the source of truth for design tokens?"]),
    ],
    [
        _m("30", "App builds and runs on device; first PR merged within 10 working days",
           "PR merge date vs start date"),
        _m("60", "One feature shipped through a full release cycle", "Release notes"),
        _m("60", "One top crash or ANR fixed", "Crash reporter trend"),
        _m("90", "Measurable app-health win (crash-free users, cold start, or size)",
           "Before/after dashboards"),
        _m("90", "Own a product area: release notes and known-issues doc exist",
           "Wiki / release checklist"),
    ],
)

# --- ml --------------------------------------------------------------------
ROLE_TEMPLATES["ml"] = _t(
    "Machine Learning / AI Engineer",
    ["machine learning", "ml engineer", "ai engineer", "ml ", " applied scientist",
     "deep learning", "llm", "genai"],
    [
        {"key": "p30", "goals": [
            _g("Reproduce a baseline: train or run an existing model end to end by week 3", 3, "delivery"),
            _g("Map the ML lifecycle here: data sources, labeling, training, eval, deployment", 3, "learning"),
            _g("Learn the experiment tracking and model registry tooling", 2, "learning"),
            _g("Hold intro 1:1s with ML engineers, data engineers, and the PM", 2, "relationship"),
            _g("Read recent experiment reports and eval dashboards for your problem area", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Run a well-scoped experiment with a clear hypothesis and write it up", 6, "delivery"),
            _g("Improve an offline evaluation harness, dataset, or metric", 6, "delivery"),
            _g("Ship a model or feature improvement behind a flag / to a shadow deployment", 7, "delivery"),
            _g("Present one experiment review to the team", 8, "relationship"),
            _g("Document data quirks and failure modes you discover", 8, "learning"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a model or ML component: training, eval, and serving health", 10, "delivery"),
            _g("Drive a measurable model-quality win tied to a product or business metric", 11, "delivery"),
            _g("Harden the path to production: monitoring, rollback, and retraining triggers", 11, "delivery"),
            _g("Publish an internal tech note or give a talk on your approach", 12, "relationship"),
            _g("Propose the next modeling bets for your area with expected impact", 12, "delivery"),
        ]},
    ],
    [
        _l("Data: sources, labeling, and quality",
           "Model quality is bounded by data quality; know every quirk.",
           ["Data catalog / warehouse docs", "Labeling guidelines and agreement metrics"], "high"),
        _l("Experiment tracking and model registry",
           "Reproducibility is what separates research from production ML.",
           ["Experiment platform docs", "Model registry and lineage"], "high"),
        _l("Evaluation: offline metrics and online guardrails",
           "You need to know what 'better' means before chasing it.",
           ["Eval harness README", "Online experiment / A/B platform"], "high"),
        _l("Serving infrastructure and latency budgets",
           "A great model that is too slow or too expensive does not ship.",
           ["Serving architecture doc", "Latency and cost dashboards"], "medium"),
        _l("Responsible AI / safety review process",
           "Know the review gates before you need them.",
           ["Model risk review checklist", "Recent review outcomes"], "medium"),
    ],
    [
        _s("Engineering manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "Which models or problem areas need the most help?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["How do I run the standard training pipeline end to end?",
            "Which datasets are trusted vs which need cleaning?"]),
        _s("Data engineer(s)", "biweekly",
           ["How do training datasets get built and refreshed?",
            "What data quality issues should I know about?"]),
        _s("Product manager", "biweekly",
           ["What product metric does my model actually move?",
            "How are model tradeoffs (quality vs latency vs cost) decided?"]),
        _s("Senior / staff ML engineer", "biweekly",
           ["What modeling approaches have been tried and abandoned, and why?",
            "How do experiment reviews work here?"]),
    ],
    [
        _m("30", "Baseline model reproduced end to end", "Experiment report link"),
        _m("60", "One hypothesis-driven experiment completed and written up",
           "Experiment doc with results"),
        _m("60", "Improvement shipped behind flag or to shadow", "Deploy / flag record"),
        _m("90", "Measurable model-quality win tied to a product metric",
           "Offline + online metric deltas"),
        _m("90", "Production monitoring and rollback plan documented for owned model",
           "Runbook / dashboard links"),
    ],
)

# --- data ------------------------------------------------------------------
ROLE_TEMPLATES["data"] = _t(
    "Data Engineer / Data Scientist / Analytics",
    ["data engineer", "data scientist", "analytics", "bi ", "data analyst"],
    [
        {"key": "p30", "goals": [
            _g("Get data access and run your first query/notebook against the warehouse by week 2", 2, "delivery"),
            _g("Map the key datasets, owners, and refresh cadences for your domain", 3, "learning"),
            _g("Understand the orchestration and dbt (or equivalent) project structure", 3, "learning"),
            _g("Hold intro 1:1s with data engineers, analysts, and stakeholder teams", 2, "relationship"),
            _g("Read data quality monitors and recent incident write-ups", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Ship a data model, pipeline, or analysis that a stakeholder actually uses", 6, "delivery"),
            _g("Add data quality tests or monitors to a pipeline you touched", 6, "delivery"),
            _g("Document a dataset or metric definition that was previously tribal knowledge", 7, "learning"),
            _g("Present one analysis or pipeline walkthrough to the team", 8, "relationship"),
            _g("Review 10+ PRs / merge requests for data changes", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a data domain: models, pipelines, SLAs, and stakeholder relationships", 10, "delivery"),
            _g("Drive a measurable data-quality or cost improvement", 11, "delivery"),
            _g("Establish or improve a metric definition with stakeholder sign-off", 11, "delivery"),
            _g("Automate a manual reporting or backfill process", 12, "delivery"),
            _g("Propose the next quarter's data roadmap for your domain", 12, "delivery"),
        ]},
    ],
    [
        _l("Warehouse, dbt project, and modeling conventions",
           "Consistent modeling is what makes data trustworthy and discoverable.",
           ["dbt project docs and style guide", "Data catalog"], "high"),
        _l("Orchestration and SLAs",
           "Know how pipelines run, fail, and get fixed.",
           ["Orchestrator DAG docs", "SLA definitions and alerting"], "high"),
        _l("Data quality tooling",
           "Tests on data are how you sleep at night.",
           ["Data quality framework docs", "Recent data incident postmortems"], "high"),
        _l("BI / experimentation stack",
           "Know how stakeholders consume data and make decisions.",
           ["Dashboard best practices", "Experimentation platform guide"], "medium"),
        _l("Cost and performance of the data platform",
           "Warehouse spend and slow queries are team-level concerns.",
           ["Cost attribution dashboards", "Query performance guide"], "medium"),
    ],
    [
        _s("Engineering / analytics manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "Which data domains are the messiest right now?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["How do I get access to everything I need?",
            "Which datasets are canonical vs deprecated?"]),
        _s("Key stakeholder (PM / ops / finance)", "biweekly",
           ["What decisions do you make with our data?",
            "Which numbers do you not trust today, and why?"]),
        _s("Senior data engineer / scientist", "biweekly",
           ["What is the long-term architecture direction?",
            "What would you rebuild if you had a month?"]),
        _s("Data platform / infra team", "monthly",
           ["How do I request new sources or compute?",
            "What are the guardrails on cost and access?"]),
    ],
    [
        _m("30", "First query / pipeline run completed against production data",
           "Query history / pipeline run"),
        _m("60", "One stakeholder-used deliverable shipped (model, pipeline, or analysis)",
           "Stakeholder confirmation"),
        _m("60", "Data quality tests added to touched pipelines", "Test coverage in repo"),
        _m("90", "Own a data domain with documented SLAs", "Domain README / SLA doc"),
        _m("90", "One measurable quality or cost improvement", "Before/after metrics"),
    ],
)

# --- devops ----------------------------------------------------------------
ROLE_TEMPLATES["devops"] = _t(
    "DevOps / SRE / Platform Engineer",
    ["devops", "sre", "site reliability", "platform", "infrastructure"],
    [
        {"key": "p30", "goals": [
            _g("Get access to cloud accounts, clusters, and CI; deploy a no-op change by week 2", 2, "delivery"),
            _g("Map the infrastructure: IaC repos, environments, networking, and secrets management", 3, "learning"),
            _g("Shadow oncall and learn the incident response process and escalation paths", 3, "learning"),
            _g("Hold intro 1:1s with platform teammates and 2-3 service owners you will support", 2, "relationship"),
            _g("Read recent incident postmortems and the current reliability roadmap", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Ship an infrastructure improvement: IaC module, CI speedup, or dashboard", 6, "delivery"),
            _g("Take supervised oncall shifts and lead one incident to resolution", 7, "delivery"),
            _g("Reduce toil: automate one manual operational task", 6, "delivery"),
            _g("Write or update a runbook for a service you supported", 8, "learning"),
            _g("Review infra PRs with attention to blast radius and rollback plans", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a platform area (e.g. CI, observability, or a cluster fleet)", 10, "delivery"),
            _g("Drive a reliability win: fewer pages, faster recovery, or SLO improvement", 11, "delivery"),
            _g("Lead a game day or disaster-recovery exercise", 11, "delivery"),
            _g("Publish platform guidance that service teams adopt", 12, "relationship"),
            _g("Propose next quarter's reliability and cost goals with data", 12, "delivery"),
        ]},
    ],
    [
        _l("Infrastructure as code and environments",
           "Everything important should be in code and reproducible.",
           ["IaC repo README", "Environment promotion flow"], "high"),
        _l("Incident response and oncall",
           "Calm, practiced response is the core SRE skill.",
           ["Incident process doc", "Recent postmortems"], "high"),
        _l("Observability: metrics, logs, traces, alerting",
           "You cannot improve reliability you cannot see.",
           ["Monitoring stack docs", "Alert tuning guide"], "high"),
        _l("CI/CD internals",
           "Developer velocity lives or dies on the pipeline.",
           ["CI pipeline architecture", "Build time / flake dashboards"], "medium"),
        _l("Cloud cost and security baselines",
           "Reliability includes not getting breached or over-billed.",
           ["Cost attribution dashboards", "Security baseline checklist"], "medium"),
    ],
    [
        _s("Engineering manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "What is the biggest reliability or velocity pain right now?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["How do I safely make my first infra change?",
            "Which systems are fragile or undocumented?"]),
        _s("Service owners / team leads", "biweekly",
           ["What slows your team down most: deploys, environments, or observability?",
            "What do you wish the platform team did differently?"]),
        _s("Security team", "once in first 60 days",
           ["What are the security baselines I must follow?",
            "How do secret rotation and access reviews work?"]),
        _s("Skip-level manager", "once in first 60 days",
           ["What does the org need most from platform this half?",
            "How is platform success measured here?"]),
    ],
    [
        _m("30", "First infra change deployed safely (no-op or low-risk)", "Deploy record"),
        _m("30", "Oncall shadow completed; can describe the incident process",
           "Shadow sign-off"),
        _m("60", "One toil-reduction automation shipped", "Before/after toil estimate"),
        _m("60", "Supervised oncall shift completed", "Oncall calendar"),
        _m("90", "Measurable reliability win (MTTR, page volume, or SLO)",
           "Before/after dashboards"),
        _m("90", "Own a platform area with documented runbooks", "Runbook links"),
    ],
)

# --- em --------------------------------------------------------------------
ROLE_TEMPLATES["em"] = _t(
    "Engineering Manager",
    ["engineering manager", "eng manager", "tech lead manager", "em "],
    [
        {"key": "p30", "goals": [
            _g("Hold 1:1s with every direct report; learn their goals, concerns, and working styles", 2, "relationship"),
            _g("Meet key partners: product, design, and peer managers", 3, "relationship"),
            _g("Learn the team's rituals: standups, planning, retros, oncall, and how decisions get made", 3, "learning"),
            _g("Read the roadmap, recent retros, and perf/engagement history", 4, "learning"),
            _g("Establish your operating cadence: 1:1 schedule, team meeting format, status updates", 4, "process"),
        ]},
        {"key": "p60", "goals": [
            _g("Run one full planning cycle and one retro; act on the top retro item", 6, "process"),
            _g("Deliver honest, specific feedback to each report at least once", 7, "relationship"),
            _g("Unblock the team's top delivery risk or dependency", 6, "delivery"),
            _g("Build a staffing / hiring plan sketch for the next two quarters", 8, "delivery"),
            _g("Establish skip-level or peer feedback loops you will keep", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own the team's roadmap narrative: priorities, tradeoffs, and staffing", 10, "delivery"),
            _g("Drive one meaningful team-health or process improvement with measurable effect", 11, "process"),
            _g("Complete growth conversations: career goals documented for each report", 11, "relationship"),
            _g("Deliver a visible win the team can point to (launch, reliability, or velocity)", 12, "delivery"),
            _g("Write your own 90-day retro: what worked, what you will change", 12, "process"),
        ]},
    ],
    [
        _l("Team context: roadmap, tech, and history",
           "You cannot lead a team whose context you do not deeply understand.",
           ["Roadmap and recent retros", "Architecture overview from the tech lead"], "high"),
        _l("Management systems: perf, compensation, hiring",
           "Know the machinery before you need it.",
           ["Perf review process and timeline", "Hiring and leveling guides"], "high"),
        _l("Stakeholder landscape",
           "Map who needs what from your team before conflicts arise.",
           ["Partner team roadmaps", "Escalation paths"], "high"),
        _l("Delivery health metrics",
           "Lead with data: velocity, quality, and predictability.",
           ["Team dashboards", "Incident and bug trends"], "medium"),
        _l("Your manager's expectations",
           "Clarity up front prevents painful corrections later.",
           ["Explicit 90-day expectations doc", "How your manager likes to be updated"], "high"),
    ],
    [
        _s("Your manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "What should I absolutely not change in my first 90 days?",
            "How do you want bad news delivered?"]),
        _s("Each direct report", "weekly or biweekly 1:1",
           ["What is working well and what is frustrating right now?",
            "What are your career goals for the next year?",
            "What do you need from me that you are not getting?"]),
        _s("Tech lead / senior ICs", "biweekly",
           ["What is the technical state of the team, honestly?",
            "Where do you need air cover or unblocking?"]),
        _s("Product partner", "weekly",
           ["How do we make prioritization calls together?",
            "What does the team not understand about the roadmap?"]),
        _s("Peer managers", "biweekly",
           ["How do our teams depend on each other?",
            "What cross-team friction should I know about?"]),
        _s("Skip-level leader", "once in first 60 days",
           ["What does the org need most from my team this half?",
            "What distinguishes strong managers here?"]),
    ],
    [
        _m("30", "1:1s established with 100% of reports; notes captured", "Calendar + notes"),
        _m("60", "One planning cycle and retro run; top retro action shipped",
           "Retro doc and follow-through"),
        _m("60", "Feedback delivered to each report at least once", "Your 1:1 notes"),
        _m("90", "Team roadmap narrative written and shared", "Roadmap doc"),
        _m("90", "Career goals documented for each report", "Growth docs"),
        _m("90", "One measurable team-health or delivery improvement",
           "Before/after survey or metric"),
    ],
)

# --- pm --------------------------------------------------------------------
ROLE_TEMPLATES["pm"] = _t(
    "Product Manager",
    ["product manager", "pm ", "product owner"],
    [
        {"key": "p30", "goals": [
            _g("Talk to 5+ customers or read 20+ support tickets / call recordings", 3, "learning"),
            _g("Map the product: key flows, metrics, tech constraints, and competitive landscape", 3, "learning"),
            _g("Hold intro 1:1s with engineering, design, data, and stakeholder teams", 2, "relationship"),
            _g("Learn the metrics stack: what is tracked, what is trusted, what is missing", 4, "learning"),
            _g("Shadow user research sessions or sales calls if available", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Write your first PRD / one-pager and get it through review", 6, "delivery"),
            _g("Define or refresh the metrics tree for your product area", 6, "delivery"),
            _g("Ship a first improvement with the team and measure the result", 7, "delivery"),
            _g("Establish your rituals: roadmap reviews, stakeholder updates, team syncs", 8, "process"),
            _g("Build a competitive / market teardown for your area", 8, "learning"),
        ]},
        {"key": "p90", "goals": [
            _g("Own the roadmap narrative: 1-2 quarter plan with tradeoffs explicit", 10, "delivery"),
            _g("Drive a measurable product outcome (activation, retention, revenue, or efficiency)", 11, "delivery"),
            _g("Establish a repeatable discovery cadence with customers", 11, "process"),
            _g("Align stakeholders on priorities: documented, socialized, and agreed", 12, "relationship"),
            _g("Write your 90-day retro: what you learned about the customer and the business", 12, "process"),
        ]},
    ],
    [
        _l("Customers and their jobs-to-be-done",
           "Every good product decision starts from real user understanding.",
           ["User research repository", "Support ticket themes"], "high"),
        _l("Product metrics and instrumentation",
           "You cannot manage what you cannot measure (or do not trust).",
           ["Metrics dictionary", "Funnel dashboards for your area"], "high"),
        _l("Technical constraints and architecture",
           "Credibility with engineering requires understanding what is hard and why.",
           ["Architecture overview", "Tech debt list affecting your roadmap"], "high"),
        _l("Business model and competitive landscape",
           "Know how the company makes money and who wants to take it.",
           ["Business metrics review", "Competitive teardown"], "medium"),
        _l("Stakeholder map and decision rights",
           "Know who decides what before you need a decision fast.",
           ["RACI / decision log", "Stakeholder 1:1 notes"], "medium"),
    ],
    [
        _s("Engineering manager / tech lead", "weekly",
           ["What is the technical reality behind the roadmap?",
            "How do you like to receive product specs: detail level and format?"]),
        _s("Designer(s)", "weekly",
           ["How do you like to partner during discovery vs delivery?",
            "What research already exists that I should read first?"]),
        _s("Data / analytics partner", "biweekly",
           ["Which metrics are trustworthy and which are suspect?",
            "How do I get an analysis done: process and turnaround?"]),
        _s("Customers (5+ in first 30 days)", "ongoing",
           ["Walk me through the last time you hit this problem",
            "What have you tried, and what did you wish existed?"]),
        _s("Key stakeholders (sales, support, exec)", "biweekly/monthly",
           ["What do you need from product that you are not getting?",
            "How should we handle urgent escalations?"]),
        _s("Your manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "What product bets are already decided vs open?"]),
    ],
    [
        _m("30", "5+ customer conversations completed; notes shared", "Research notes"),
        _m("30", "Product and metrics map written up", "Onboarding doc"),
        _m("60", "First PRD through review; first shipped improvement measured",
           "PRD link and metric delta"),
        _m("90", "Roadmap narrative published and socialized", "Roadmap doc"),
        _m("90", "One measurable product outcome", "Before/after metric"),
    ],
)

# --- design ----------------------------------------------------------------
ROLE_TEMPLATES["design"] = _t(
    "Product Designer (UX / UI)",
    ["designer", "ux", "ui ", "product design", "interaction"],
    [
        {"key": "p30", "goals": [
            _g("Learn the design system: components, tokens, and contribution process", 2, "learning"),
            _g("Audit the product area you will own: flows, inconsistencies, and quick wins", 3, "learning"),
            _g("Hold intro 1:1s with PMs, engineers, researchers, and fellow designers", 2, "relationship"),
            _g("Join design critique; understand how feedback works here", 3, "relationship"),
            _g("Read existing research and personas for your area", 4, "learning"),
        ]},
        {"key": "p60", "goals": [
            _g("Ship your first design end to end: from exploration to dev handoff", 6, "delivery"),
            _g("Run or observe 3+ usability sessions for your area", 6, "learning"),
            _g("Fix a set of UI inconsistencies or a11y issues you found in the audit", 7, "delivery"),
            _g("Establish your design-dev handoff rhythm with engineering", 7, "process"),
            _g("Present work in critique twice; incorporate feedback visibly", 8, "relationship"),
        ]},
        {"key": "p90", "goals": [
            _g("Own a product surface's experience: vision, flows, and details", 10, "delivery"),
            _g("Drive a measurable UX improvement (task success, satisfaction, or conversion)", 11, "delivery"),
            _g("Contribute components or patterns back to the design system", 11, "delivery"),
            _g("Lead a design sprint or workshop for an upcoming initiative", 12, "delivery"),
            _g("Publish a UX quality bar or heuristic checklist for your area", 12, "process"),
        ]},
    ],
    [
        _l("Design system and contribution model",
           "Consistency at scale comes from the system, not heroics.",
           ["Design system docs and Figma libraries", "Contribution / review process"], "high"),
        _l("Product area: flows, edge cases, and tech constraints",
           "Great design respects what is feasible.",
           ["Flow audit of your area", "Engineering constraints doc"], "high"),
        _l("Research repository and personas",
           "Do not re-learn what the team already knows about users.",
           ["Research repo", "Personas and journey maps"], "high"),
        _l("Critique culture and feedback norms",
           "Feedback is the fastest way to level up here.",
           ["Critique schedule and norms", "Recent exemplary critique threads"], "medium"),
        _l("Accessibility and inclusive design",
           "Inclusive defaults prevent expensive rework.",
           ["A11y checklist", "Contrast / screen-reader basics"], "medium"),
    ],
    [
        _s("Design manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "What is the design quality bar I should aim for?"]),
        _s("Onboarding buddy / fellow designer", "daily first 2 weeks",
           ["How do files get organized here?",
            "Which past projects should I study?"]),
        _s("Product manager(s)", "weekly",
           ["How do you like to partner: how early do you want design involved?",
            "What is the decision process when we disagree?"]),
        _s("Engineers on your team", "biweekly",
           ["What makes a great handoff for you: specs, prototypes, or pairing?",
            "What design debt hurts the build most?"]),
        _s("User researcher (if any)", "biweekly",
           ["What research exists for my area?",
            "How do I request a study?"]),
    ],
    [
        _m("30", "Product-area audit completed and shared", "Audit doc"),
        _m("60", "First design shipped end to end", "Shipped feature"),
        _m("60", "3+ usability sessions run or observed", "Session notes"),
        _m("90", "Measurable UX improvement with before/after data",
           "Usability or analytics delta"),
        _m("90", "Design-system contribution merged", "System changelog"),
    ],
)

# --- general ---------------------------------------------------------------
ROLE_TEMPLATES["general"] = _t(
    "General / Other Role",
    [],
    [
        {"key": "p30", "goals": [
            _g("Complete onboarding tasks and get your tools/access fully working by week 2", 2, "learning"),
            _g("Hold intro 1:1s with teammates, your manager, and key partners", 2, "relationship"),
            _g("Learn the team's rituals, communication norms, and decision-making process", 3, "learning"),
            _g("Read the essential docs: team charter, roadmap, recent retros", 3, "learning"),
            _g("Deliver one small, visible win to learn the end-to-end workflow", 4, "delivery"),
        ]},
        {"key": "p60", "goals": [
            _g("Take independent ownership of a scoped piece of work", 6, "delivery"),
            _g("Build working relationships with 2-3 cross-functional partners", 6, "relationship"),
            _g("Document something that was previously tribal knowledge", 7, "learning"),
            _g("Ask for feedback explicitly and act on it visibly", 8, "relationship"),
            _g("Improve one team process or artifact you use daily", 8, "process"),
        ]},
        {"key": "p90", "goals": [
            _g("Own an area of responsibility others recognize as yours", 10, "delivery"),
            _g("Deliver a result with measurable impact", 11, "delivery"),
            _g("Help onboard or support a teammate", 11, "relationship"),
            _g("Share something you learned: write-up, talk, or demo", 12, "relationship"),
            _g("Agree on next-90-day goals with your manager", 12, "process"),
        ]},
    ],
    [
        _l("Team context: mission, roadmap, and rituals",
           "Context is what turns tasks into judgment.",
           ["Team charter and roadmap", "Recent retros and planning docs"], "high"),
        _l("Tools and workflows",
           "Fluency with the toolchain removes daily friction.",
           ["Tooling guides", "Pair with a teammate on real work"], "high"),
        _l("Stakeholder landscape",
           "Know who depends on your work and who you depend on.",
           ["Org chart and partner teams", "Intro 1:1 notes"], "medium"),
        _l("Domain fundamentals",
           "Ramp on the domain, not just the job description.",
           ["Domain primers and glossaries", "Customer / user exposure"], "medium"),
    ],
    [
        _s("Manager", "weekly 1:1",
           ["What does success look like for me at 30/60/90 days?",
            "What should I prioritize learning first?",
            "How do you prefer updates: async or live?"]),
        _s("Onboarding buddy", "daily for first 2 weeks",
           ["What do you wish you had known in week one?",
            "Who should I meet that is not on the obvious list?"]),
        _s("Teammates", "as scheduled",
           ["What are you working on and how does it connect to mine?",
            "What is the best way to collaborate with you?"]),
        _s("Key cross-functional partners", "biweekly",
           ["What do you need from someone in my role?",
            "How should we handle disagreements on priorities?"]),
    ],
    [
        _m("30", "Onboarding complete; first small win delivered", "Onboarding checklist"),
        _m("60", "Independent ownership of scoped work", "Deliverable link"),
        _m("60", "Feedback explicitly requested and acted on", "Your notes"),
        _m("90", "Recognized area of ownership", "Peer / manager confirmation"),
        _m("90", "Measurable impact delivered", "Before/after evidence"),
    ],
)

# ---------------------------------------------------------------------------
# level modifiers: extra expectations layered on top of the base template
# ---------------------------------------------------------------------------

LEVEL_TIERS = {
    "intern": "junior",
    "new grad": "junior",
    "junior": "junior",
    "associate": "junior",
    "mid": "mid",
    "senior": "senior",
    "sr": "senior",
    "lead": "senior",
    "staff": "staff",
    "principal": "staff",
    "distinguished": "staff",
    "director": "staff",
}

LEVEL_MODIFIERS: dict[str, dict] = {
    "junior": {
        "label": "Junior",
        "note": "Expectations are calibrated for ramp-up: smaller scope, more "
                "guidance, and fundamentals first.",
        "add_goals": {
            "p30": [_g("Pair with your buddy or a senior teammate at least twice a week", 2, "learning"),
                    _g("Complete the team's fundamentals learning path (or equivalent courses)", 4, "learning")],
            "p60": [_g("Ask for code/design review feedback explicitly on every piece of work", 6, "learning")],
            "p90": [_g("Demo your work to the team and write up what you learned", 12, "relationship")],
        },
        "add_stakeholders": [
            _s("Mentor (if assigned)", "biweekly",
               ["What should I be learning that I am not?",
                "Can you review my growth areas monthly?"]),
        ],
    },
    "mid": {
        "label": "Mid-level",
        "note": "Standard expectations: independent delivery on scoped work by day 60.",
        "add_goals": {},
        "add_stakeholders": [],
    },
    "senior": {
        "label": "Senior",
        "note": "Senior expectations: broader scope, technical leadership, and "
                "raising the bar for others.",
        "add_goals": {
            "p30": [_g("Publish your 30-60-90 expectations doc and align it with your manager", 2, "process"),
                    _g("Identify the top 3 tech-debt / process pain points in your area", 4, "learning")],
            "p60": [_g("Lead the design or planning for a multi-week initiative", 7, "delivery"),
                    _g("Mentor a junior teammate or intern on a real workstream", 8, "relationship")],
            "p90": [_g("Drive a cross-team or cross-functional initiative to a decision or launch", 11, "delivery"),
                    _g("Raise the bar: improve a team standard (review quality, testing, docs)", 12, "process")],
        },
        "add_stakeholders": [
            _s("Partner team lead(s)", "monthly",
               ["Where do our roadmaps intersect or conflict?",
                "How should we coordinate on shared dependencies?"]),
        ],
    },
    "staff": {
        "label": "Staff / Principal",
        "note": "Staff expectations: org-level impact, technical strategy, and "
                "multiplication of others.",
        "add_goals": {
            "p30": [_g("Publish your 30-60-90 expectations doc and align it with your manager and skip", 2, "process"),
                    _g("Map the org's technical strategy: where it is strong, where it is missing", 4, "learning")],
            "p60": [_g("Author or co-author a technical strategy / vision doc for your area", 7, "delivery"),
                    _g("Influence 2+ teams: reviews, RFCs, or shared initiatives", 8, "relationship")],
            "p90": [_g("Land an org-level initiative: adopted RFC, migrated system, or new capability", 12, "delivery"),
                    _g("Sponsor the growth of 1-2 engineers (mentorship with outcomes)", 12, "relationship")],
        },
        "add_stakeholders": [
            _s("Skip-level / org leadership", "monthly",
               ["What are the org's biggest technical bets and risks?",
                "Where can a staff-level engineer create the most leverage?"]),
            _s("Partner org leads", "monthly",
               ["What cross-org initiatives need technical leadership?",
                "How do we avoid duplicated or divergent efforts?"]),
        ],
    },
}


# ---------------------------------------------------------------------------
# selection helpers
# ---------------------------------------------------------------------------

def detect_family(role: str) -> str:
    """Best-match role family key for a free-text role title."""
    text = (role or "").lower()
    best, best_hits = "general", 0
    for key, tmpl in ROLE_TEMPLATES.items():
        if key == "general":
            continue
        hits = sum(1 for kw in tmpl["match"] if kw in text)
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def detect_tier(level: str) -> str:
    """Map a free-text level (e.g. 'Sr.', 'L5', 'senior') to a tier key."""
    text = (level or "").lower()
    for keyword, tier in LEVEL_TIERS.items():
        if keyword in text:
            return tier
    return "mid"


def get_template(family: str) -> dict:
    """Deep copy of the template for ``family`` (falls back to general)."""
    tmpl = ROLE_TEMPLATES.get(family, ROLE_TEMPLATES["general"])
    return copy.deepcopy(tmpl)


def list_families() -> list[dict]:
    """Family keys with human labels, for CLI help / docs."""
    return [{"key": k, "label": v["label"]}
            for k, v in ROLE_TEMPLATES.items()]
