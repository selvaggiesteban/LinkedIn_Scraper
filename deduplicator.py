"""
deduplicator.py — Cross-Source Deduplication
URL dedup, name fuzzy matching, cross-source entity resolution.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .config import NAME_FUZZY_THRESHOLD


def _normalize_url(url: str) -> str:
    return url.rstrip("/").split("?")[0].split("#")[0].lower()


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def _name_similarity(a: str, b: str) -> float:
    na, nb = _normalize_name(a), _normalize_name(b)
    return SequenceMatcher(None, na, nb).ratio()


def dedup_urls(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicates by URL."""
    seen: set[str] = set()
    unique = []
    for r in results:
        url = r.get("job_url") or r.get("profile_url") or r.get("post_url") or ""
        if not url:
            unique.append(r)
            continue
        norm = _normalize_url(url)
        if norm not in seen:
            seen.add(norm)
            unique.append(r)
    return unique


def dedup_names(results: list[dict[str, Any]], threshold: float = NAME_FUZZY_THRESHOLD) -> list[dict[str, Any]]:
    """Remove duplicates by name similarity (people only)."""
    people = [r for r in results if r.get("type") == "person"]
    non_people = [r for r in results if r.get("type") != "person"]

    seen_names: list[str] = []
    unique_people = []
    for p in people:
        name = p.get("name", "")
        if not name:
            unique_people.append(p)
            continue
        is_dup = False
        for seen in seen_names:
            if _name_similarity(name, seen) >= threshold:
                is_dup = True
                break
        if not is_dup:
            seen_names.append(name)
            unique_people.append(p)

    return unique_people + non_people


def merge_cross_source(
    people: list[dict[str, Any]],
    company_employees: list[dict[str, Any]],
    threshold: float = NAME_FUZZY_THRESHOLD,
) -> list[dict[str, Any]]:
    """Merge people from search_people and get_company_employees."""
    all_people = people + company_employees
    return dedup_names(all_people, threshold)


def dedup_all(categories: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Run full dedup pipeline across all categories."""
    result = {}

    # People dedup (merge across sources)
    people = categories.get("people", [])
    company_emp = categories.get("company_employees", [])
    merged = merge_cross_source(people, company_emp)
    result["people"] = dedup_urls(merged)

    # Jobs dedup
    result["jobs"] = dedup_urls(categories.get("jobs", []))

    # Posts dedup (feed + companies merged)
    all_posts = categories.get("posts_feed", []) + categories.get("posts_companies", [])
    result["posts"] = dedup_urls(all_posts)

    # Authors dedup
    result["authors"] = dedup_urls(categories.get("authors", []))

    # Company profiles
    result["company_profiles"] = categories.get("company_profiles", [])

    return result


def print_dedup_stats(before: dict[str, list], after: dict[str, list]):
    """Print dedup statistics."""
    print(f"\n{'=' * 60}")
    print("DEDUP STATISTICS")
    print(f"{'=' * 60}")
    total_before = 0
    total_after = 0
    for cat in before:
        b = len(before[cat])
        a = len(after[cat])
        total_before += b
        total_after += a
        removed = b - a
        pct = f"({removed/b*100:.0f}%)" if b > 0 else ""
        print(f"  {cat}: {b} → {a} (removed {removed} {pct})")
    print(f"  TOTAL: {total_before} → {total_after} (removed {total_before - total_after})")
    print(f"{'=' * 60}")
