"""Gap-closing study plans for career switchers.

A career switcher typically has a target role and a list of skill gaps
(e.g. from candid.match comparing their resume against a job description).
This module turns those gaps into an ordered, week-by-week learning plan:
hardest gaps first, each week with concrete free study resources, a
milestone, and a "proof of learning" deliverable (usually a small project)
so the user can demonstrate the skill on their resume.

Everything is deterministic and offline. Only real free resources are named
(no fabricated URLs): official documentation, freeCodeCamp, MIT OCW,
Kaggle Learn, MDN Web Docs, The Odin Project, CS50, and similar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class SwitchPlanError(Exception):
    """Raised when a switch plan cannot be built from the given inputs."""


#: Severity ordering, worst first. Anything not in this table is treated as
#: "medium".
SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

#: Free-resource catalog keyed by skill keyword. Match is a case-insensitive
#: substring hit against the gap's skill name; first matching keyword wins.
RESOURCE_CATALOG: dict[str, list[str]] = {
    "python": ["Official Python tutorial (docs.python.org)", "freeCodeCamp Scientific Computing with Python", "CS50P (Harvard, free audit)"],
    "javascript": ["MDN Web Docs (JavaScript Guide)", "freeCodeCamp JavaScript Algorithms and Data Structures", "The Odin Project (Foundations)"],
    "typescript": ["Official TypeScript Handbook", "freeCodeCamp TypeScript course"],
    "sql": ["Kaggle Learn SQL track", "freeCodeCamp Relational Database course", "PostgreSQL official tutorial"],
    "machine learning": ["Andrew Ng Machine Learning Specialization (free audit)", "Kaggle Learn Intro to Machine Learning", "Stanford CS229 lecture notes (free)"],
    "deep learning": ["Stanford CS231n lecture videos (free)", "Kaggle Learn Intro to Deep Learning", "fast.ai Practical Deep Learning (free)"],
    "data analysis": ["Kaggle Learn Pandas track", "freeCodeCamp Data Analysis with Python"],
    "statistics": ["MIT OCW 18.05 Introduction to Probability and Statistics", "Khan Academy Statistics and Probability"],
    "git": ["Official Git book (git-scm.com)", "freeCodeCamp Git and GitHub course"],
    "docker": ["Official Docker getting-started guide", "freeCodeCamp Docker course"],
    "kubernetes": ["Official Kubernetes tutorials", "freeCodeCamp Kubernetes course"],
    "cloud": ["AWS Skill Builder free tier", "Google Cloud Skills Boost free courses"],
    "aws": ["AWS Skill Builder free tier", "freeCodeCamp AWS courses"],
    "react": ["Official React docs (react.dev)", "freeCodeCamp Front End Development Libraries"],
    "html": ["MDN Web Docs (HTML)", "freeCodeCamp Responsive Web Design"],
    "css": ["MDN Web Docs (CSS)", "freeCodeCamp Responsive Web Design"],
    "linux": ["The Linux Command Line (free book)", "freeCodeCamp Linux course"],
    "networking": ["MIT OCW 6.829 Computer Networks (lecture notes)", "freeCodeCamp networking course"],
    "algorithms": ["MIT OCW 6.006 Introduction to Algorithms", "freeCodeCamp Coding Interview Prep"],
    "data structures": ["MIT OCW 6.006 Introduction to Algorithms", "freeCodeCamp Coding Interview Prep"],
    "system design": ["ByteByteGo free newsletter articles", "MIT OCW distributed systems lectures"],
    "excel": ["Microsoft Excel official support tutorials", "freeCodeCamp Excel course"],
    "tableau": ["Tableau free training videos", "Kaggle Learn data visualization track"],
    "nlp": ["Stanford CS224n lecture videos (free)", "Kaggle Learn Natural Language Processing"],
    "pandas": ["Kaggle Learn Pandas track", "Official pandas user guide"],
    "numpy": ["Official NumPy quickstart tutorial", "Kaggle Learn Intro to Machine Learning"],
}

#: Fallback resources when no keyword matches a gap.
GENERIC_RESOURCES: list[str] = [
    "Official documentation for the tool or language",
    "freeCodeCamp full curriculum (free)",
    "MIT OpenCourseWare (free)",
]

#: Proof-of-learning deliverable templates by skill keyword; first substring
#: match wins. The {skill} placeholder is filled with the gap's skill name.
DELIVERABLE_CATALOG: dict[str, str] = {
    "python": "Build a small CLI tool in Python and publish it on GitHub with a README and tests.",
    "javascript": "Build an interactive single-page web app in JavaScript and deploy it (e.g. GitHub Pages).",
    "typescript": "Convert a small JavaScript project to TypeScript and publish it on GitHub.",
    "sql": "Design a normalized schema for a real dataset, write 10 analytical queries, and share the repo.",
    "machine learning": "Train and evaluate a model on a Kaggle dataset; write up the approach in a README.",
    "deep learning": "Train an image classifier on a public dataset and document training curves and results.",
    "data analysis": "Publish an end-to-end analysis notebook (clean, explore, visualize, conclude) on Kaggle or GitHub.",
    "statistics": "Reproduce a published analysis or A/B test calculation with your own code and writeup.",
    "git": "Maintain a public repo with meaningful commits, branches, and a pull request reviewed by a peer.",
    "docker": "Containerize one of your projects with a multi-stage Dockerfile and publish it.",
    "kubernetes": "Deploy a small app to a local Kubernetes cluster (minikube/kind) with manifests in GitHub.",
    "aws": "Deploy a small project on the AWS free tier with infrastructure described in code.",
    "cloud": "Deploy a small project on a free cloud tier with infrastructure described in code.",
    "react": "Build a multi-page React app with routing and state management; deploy it.",
    "html": "Build a responsive static site from scratch (no frameworks) and publish it.",
    "css": "Recreate a polished landing page design with pure CSS and publish it.",
    "linux": "Write a set of shell scripts automating a real workflow; document usage in a README.",
    "algorithms": "Solve 20 curated problems and write up time/space complexity for each.",
    "data structures": "Implement core data structures from scratch with tests in your target language.",
    "nlp": "Build a text classifier or summarizer on a public dataset and publish the notebook.",
    "pandas": "Publish a data-wrangling notebook cleaning a messy public dataset end to end.",
    "excel": "Build a dashboard workbook with pivot tables and charts on a real dataset.",
    "tableau": "Publish a Tableau Public dashboard telling a story with a public dataset.",
}

GENERIC_DELIVERABLE = "Build a small project using {skill} and publish it on GitHub with a README explaining what you learned."


@dataclass
class Gap:
    """One normalized skill gap."""

    skill: str
    severity: str = "medium"

    @property
    def rank(self) -> int:
        return SEVERITY_RANK.get(self.severity.lower(), SEVERITY_RANK["medium"])


@dataclass
class WeekPlan:
    """One week of the study plan."""

    week: int
    skills: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    milestone: str = ""
    proof_of_learning: str = ""

    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "skills": list(self.skills),
            "resources": list(self.resources),
            "activities": list(self.activities),
            "milestone": self.milestone,
            "proof_of_learning": self.proof_of_learning,
        }


def _resources_for(skill: str) -> list[str]:
    lowered = skill.lower()
    for keyword, resources in RESOURCE_CATALOG.items():
        if keyword in lowered:
            return list(resources)
    return list(GENERIC_RESOURCES)


def _deliverable_for(skill: str) -> str:
    lowered = skill.lower()
    for keyword, template in DELIVERABLE_CATALOG.items():
        if keyword in lowered:
            return template
    return GENERIC_DELIVERABLE.format(skill=skill)


def _normalize_gaps(gaps: list[dict]) -> list[Gap]:
    normalized: list[Gap] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            raise SwitchPlanError(f"Each gap must be a dict, got {type(gap).__name__}")
        skill = str(gap.get("skill", "")).strip()
        if not skill:
            raise SwitchPlanError("Each gap must include a non-empty 'skill'.")
        severity = str(gap.get("severity", "medium")).strip().lower() or "medium"
        if severity not in SEVERITY_RANK:
            severity = "medium"
        normalized.append(Gap(skill=skill, severity=severity))
    return normalized


def build_plan(gaps: list[dict], target_role: str, weeks: int = 8) -> dict:
    """Build an ordered week-by-week study plan for a career switcher.

    Args:
        gaps: list of {"skill": str, "severity": str} dicts. Severity is one
            of critical/high/medium/low (anything else becomes medium).
        target_role: the role the user is switching into (used in headings).
        weeks: number of weeks in the plan; must be >= 1.

    Returns:
        Structured dict with target_role, weeks, total_gaps, ordered gaps,
        and a "schedule" list of week dicts (week, skills, resources,
        activities, milestone, proof_of_learning).

    Gaps are ordered by severity (critical first) and then alphabetically so
    the plan is deterministic. Gaps are dealt round-robin across the weeks,
    one per week per pass, so the hardest gaps land in the earliest weeks.
    """
    if not target_role or not str(target_role).strip():
        raise SwitchPlanError("target_role must be a non-empty string.")
    if not isinstance(weeks, int) or weeks < 1:
        raise SwitchPlanError("weeks must be a positive integer.")
    if not gaps:
        raise SwitchPlanError("gaps must be a non-empty list.")

    ordered = sorted(_normalize_gaps(gaps), key=lambda g: (g.rank, g.skill.lower()))

    schedule: list[WeekPlan] = [WeekPlan(week=i + 1) for i in range(weeks)]
    for idx, gap in enumerate(ordered):
        schedule[idx % weeks].skills.append(gap.skill)

    for week_plan in schedule:
        resources: list[str] = []
        activities: list[str] = []
        deliverables: list[str] = []
        for skill in week_plan.skills:
            for resource in _resources_for(skill):
                if resource not in resources:
                    resources.append(resource)
            activities.append(f"Study {skill} using the listed resources (2-3 focused sessions).")
            deliverables.append(_deliverable_for(skill))
        week_plan.resources = resources
        week_plan.activities = activities
        if week_plan.skills:
            joined = ", ".join(week_plan.skills)
            week_plan.milestone = (
                f"Can explain {joined} fundamentals from memory and answer "
                "common interview questions about them."
            )
            week_plan.proof_of_learning = " | ".join(deliverables)
        else:
            week_plan.milestone = "Buffer week: review prior weeks and polish published projects."
            week_plan.proof_of_learning = "Update project READMEs and add one more example to the portfolio."

    return {
        "target_role": str(target_role).strip(),
        "weeks": weeks,
        "total_gaps": len(ordered),
        "gaps_ordered": [{"skill": g.skill, "severity": g.severity} for g in ordered],
        "schedule": [w.to_dict() for w in schedule],
    }


def plan_markdown(plan: dict) -> str:
    """Render a plan dict from build_plan() as Markdown."""
    if not isinstance(plan, dict) or "schedule" not in plan:
        raise SwitchPlanError("plan must be a dict returned by build_plan().")
    lines = [
        f"# Study Plan: {plan.get('target_role', 'Target Role')}",
        "",
        f"{plan.get('total_gaps', 0)} skill gaps over {plan.get('weeks', 0)} weeks.",
        "",
        "## Gaps (hardest first)",
        "",
    ]
    for gap in plan.get("gaps_ordered", []):
        lines.append(f"- **{gap['skill']}** ({gap['severity']})")
    lines.append("")
    for week in plan["schedule"]:
        lines.append(f"## Week {week['week']}")
        lines.append("")
        if week["skills"]:
            lines.append(f"**Focus:** {', '.join(week['skills'])}")
            lines.append("")
            lines.append("**Resources:**")
            for resource in week["resources"]:
                lines.append(f"- {resource}")
            lines.append("")
            lines.append("**Activities:**")
            for activity in week["activities"]:
                lines.append(f"- {activity}")
            lines.append("")
            lines.append(f"**Milestone:** {week['milestone']}")
            lines.append("")
            lines.append(f"**Proof of learning:** {week['proof_of_learning']}")
        else:
            lines.append(f"*{week['milestone']}*")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
