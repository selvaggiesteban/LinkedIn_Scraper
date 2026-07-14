"""
linkedin_job_search.py — Legacy entry-point; now a thin wrapper to linkedin_tools.py
"""
import sys
from linkedin_tools import main as _tools_main


def main(argv: list[str] | None = None) -> int:
    """Run the legacy 8-keyword-group job search via linkedin_tools."""
    keyword_groups = [
        "ingeniero en informatica",
        "ingeniero en software",
        "ingeniero en sistemas",
        "analista de sistemas",
        "programador",
        "desarrollador web full stack",
        "disenador web",
        "posicionamiento web seo",
    ]
    keywords = ",".join(keyword_groups)
    args = ["jobs", "--keywords", keywords, "--location", "Buenos Aires",
            "--date-posted", "past_week", "--sort-by", "date"]
    if argv:
        # Allow overriding by passing e.g. ['--output', 'custom.json']
        args.extend(argv)
    return _tools_main(args)


if __name__ == "__main__":
    sys.exit(main())
