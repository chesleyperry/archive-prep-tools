"""Generates the Markdown README and the column data dictionary."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import ColumnProfile, DuplicateGroup, Issue, Severity


def _issue_counts(issues: list[Issue]) -> dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for issue in issues:
        counts[issue.severity.value] += 1
    return counts


def build_data_dictionary(profiles: list[ColumnProfile]) -> str:
    """A Markdown table: one row per column."""
    lines = [
        "| Column | Type | Fill rate | Unique | Min | Max | Sample values |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in profiles:
        samples = ", ".join(str(v) for v in p.sample_values)
        if len(samples) > 60:
            samples = samples[:57] + "…"
        minimum = "" if p.minimum is None else f"{p.minimum:g}"
        maximum = "" if p.maximum is None else f"{p.maximum:g}"
        lines.append(
            f"| `{p.name}` | {p.inferred_type} | {p.fill_rate:.0%} | "
            f"{p.unique_count} | {minimum} | {maximum} | {samples} |"
        )
    return "\n".join(lines)


def build_readme(
    *,
    source_name: str,
    row_count: int,
    profiles: list[ColumnProfile],
    issues: list[Issue],
    duplicate_groups: list[DuplicateGroup],
) -> str:
    """Assemble the full README.md describing the dataset and its quality."""
    counts = _issue_counts(issues)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    dup_destructive = sum(1 for g in duplicate_groups if g.discards_data)

    out: list[str] = []
    out.append(f"# Data documentation — {source_name}\n")
    out.append(f"_Generated {generated} by the data-prep tool._\n")

    out.append("## Overview\n")
    out.append(f"- **Rows:** {row_count}")
    out.append(f"- **Columns:** {len(profiles)}")
    out.append(
        f"- **Quality findings:** {counts['error']} error(s), "
        f"{counts['warning']} warning(s), {counts['info']} info."
    )
    out.append(
        f"- **Duplicate groups:** {len(duplicate_groups)} "
        f"({dup_destructive} would discard data and need review).\n"
    )

    out.append("## Column data dictionary\n")
    out.append(build_data_dictionary(profiles) + "\n")

    out.append("## Data-quality findings\n")
    if not issues:
        out.append("No issues detected. 🎉\n")
    else:
        # group issues by check for readability
        by_check: dict[str, list[Issue]] = {}
        for issue in issues:
            by_check.setdefault(issue.check, []).append(issue)
        for check in sorted(by_check):
            group = by_check[check]
            out.append(f"### {check} ({len(group)})\n")
            for issue in group[:25]:  # cap per-check noise in the README
                loc = f" (row {issue.row})" if issue.row is not None else ""
                out.append(f"- **{issue.severity.value}**{loc}: {issue.message}")
            if len(group) > 25:
                out.append(f"- …and {len(group) - 25} more.")
            out.append("")

    out.append("## Duplicates & merge plan\n")
    if not duplicate_groups:
        out.append("No duplicate rows detected.\n")
    else:
        out.append(
            "Policy: the most complete row in each group is kept. Groups marked "
            "**review** would discard a conflicting non-empty value and require "
            "your confirmation before merging.\n"
        )
        for i, g in enumerate(duplicate_groups, 1):
            tag = " — **review**" if g.discards_data else ""
            out.append(
                f"- Group {i}{tag}: rows {g.row_indices}, keep row "
                f"{g.winner_index}. Key: {g.key}."
            )
            for c in g.conflicts[:5]:
                out.append(
                    f"  - conflict in `{c['column']}`: keep "
                    f"'{c['winner_value']}', drop '{c['losing_value']}' "
                    f"(row {c['losing_row']})."
                )
        out.append("")

    return "\n".join(out)
