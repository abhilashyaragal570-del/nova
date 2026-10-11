"""Web routes for the tool usage report.

/usage serves the page and /api/usage returns the same summary as
`python -m app.usage_report`, as JSON. It never returns message text,
because the log doesn't contain any. Like the terminal report, it includes
the older rotated log (<name>.1) when there is one.
"""
from flask import jsonify, send_from_directory

from app.usage_log import get_log_path
from app.usage_report import read_all_entries, summarize


def register_usage_routes(app, web_dir):
    @app.get("/usage")
    def usage_page():
        return send_from_directory(web_dir, "usage.html")

    @app.get("/api/usage")
    def api_usage():
        entries, skipped = read_all_entries(get_log_path())
        summary = summarize(entries)
        summary["skipped"] = skipped
        return jsonify(summary)