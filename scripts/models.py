"""Core data model for job listings."""

import re
from dataclasses import dataclass
from typing import Optional

# Suffixes to strip when normalizing titles for dedup
_TITLE_CLEANUP_RE = re.compile(
    r"\s*[-–|]\s*(remote|remote,?\s*(us|usa)?|hybrid|onsite|on-site"
    r"|united states?|us|usa|\w{2,3},\s*\w{2})\s*$",
    re.IGNORECASE,
)


@dataclass
class Job:
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    url: str = ""
    posted: str = ""
    source: str = ""
    tier: str = ""
    reason: str = ""
    salary_text: str = ""

    def dedup_key(self) -> str:
        normalized = _TITLE_CLEANUP_RE.sub("", self.title).lower().strip()
        if self.company:
            return f"{normalized}|{self.company.lower().strip()}"
        return self.url

    def salary_str(self) -> str:
        sal_min = self.salary_min if (self.salary_min and self.salary_min > 30_000) else None
        sal_max = self.salary_max if (self.salary_max and self.salary_max > 30_000) else None
        if sal_min and sal_max:
            return f"${sal_min:,.0f}–${sal_max:,.0f}"
        if sal_min:
            return f"${sal_min:,.0f}+"
        if self.salary_text:
            return self.salary_text
        return "Not listed"
