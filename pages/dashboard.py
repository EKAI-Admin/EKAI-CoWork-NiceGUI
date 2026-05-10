"""Dashboard page — overview with CoWorkers grouped by department (workflow)."""

from collections import defaultdict
from nicegui import ui
from auth import get_current_user
from db import get_coworkers, get_coworker_dir, get_all_runs, get_user_by_username, get_departments
from theme import (
    avatar_gradient, CW_STATUS_COLORS,
    status_tw, status_icon, status_label,
)


def _load_dept_meta():
    """Fresh lookup of icon + color per department from DB."""
    icons, colors = {}, {}
    for d in get_departments():
        icons[d["name"]] = d.get("icon") or "work"
        colors[d["name"]] = d.get("color") or "blue"
    return icons, colors


def dashboard_page():
    user = get_current_user()
    if not user:
        ui.navigate.to("/login")
        return

    db_user = get_user_by_username(user["username"])
    if not db_user:
        from auth import logout
        logout()
        ui.navigate.to("/login")
        return

    user_id = user["id"]

    from pages.layout import build_layout
    content = build_layout(user=user, active="dashboard")

    with content:
        # Greeting row — matches the mock's "Good morning, X · date"
        from datetime import datetime
        greet_hour = datetime.now().hour
        greeting = "Good morning" if greet_hour < 12 else ("Good afternoon" if greet_hour < 18 else "Good evening")
        today_str = datetime.now().strftime("%d %b %Y").upper()

        with ui.row().classes("w-full items-start justify-between mb-6"):
            with ui.column().classes("gap-0"):
                ui.label(f"EKAI CoWork · {user['username']}").classes("text-xs").style(
                    "color: var(--text-muted); letter-spacing: 0.02em"
                )
                ui.label(f"{greeting}, {user['username'].capitalize()}").classes("text-3xl font-bold mt-1").style(
                    "letter-spacing: -0.02em; color: var(--text-primary)"
                )
            ui.label(today_str).classes("mono text-xs mt-2").style("color: var(--text-muted)")

        # --- Load real data ---
        coworkers = get_coworkers(user_id)
        all_runs = get_all_runs(user_id)

        # Compute stats
        from datetime import datetime as _dt, timedelta as _td

        total_cw = len(coworkers)
        active_cw = sum(1 for c in coworkers if c["status"] == "active")
        total_runs = len(all_runs)
        reports_count = sum(1 for r in all_runs if r["has_report"])
        completed_runs = sum(1 for r in all_runs if r.get("status") == "completed")
        failed_runs = sum(1 for r in all_runs if r.get("status") == "failed")
        active_now = sum(1 for r in all_runs if r.get("status") in ("pending", "running", "cancelling"))
        success_rate = int(completed_runs / max(completed_runs + failed_runs, 1) * 100)

        # Today's runs
        today_str = _dt.now().strftime("%Y-%m-%d")
        runs_today = sum(1 for r in all_runs if (r.get("started_at", "") or "").startswith(today_str))

        # Group by workflow
        by_dept = defaultdict(list)
        for cw in coworkers:
            by_dept[cw["workflow"]].append(cw)

        # Runs per coworker
        runs_per_cw = defaultdict(int)
        for r in all_runs:
            runs_per_cw[r["coworker_name"]] += 1

        # --- Summary cards: single row of 4 (live refreshed) ---
        summary_cards = ui.element("div").classes("w-full grid grid-cols-4 gap-4 mb-6")

        def _render_summary_cards():
            fresh_runs = get_all_runs(user_id)
            fresh_cw = get_coworkers(user_id)
            _total_cw = len(fresh_cw)
            _active_cw = sum(1 for c in fresh_cw if c["status"] == "active")
            _total_runs = len(fresh_runs)
            _reports_count = sum(1 for r in fresh_runs if r["has_report"])
            _completed = sum(1 for r in fresh_runs if r.get("status") == "completed")
            _failed = sum(1 for r in fresh_runs if r.get("status") == "failed")
            _active_now = sum(1 for r in fresh_runs if r.get("status") in ("pending", "running", "cancelling"))
            _success_rate = int(_completed / max(_completed + _failed, 1) * 100)
            _today_str = _dt.now().strftime("%Y-%m-%d")
            _runs_today = sum(1 for r in fresh_runs if (r.get("started_at", "") or "").startswith(_today_str))
            _by_dept = defaultdict(list)
            for cw in fresh_cw:
                _by_dept[cw["workflow"]].append(cw)
            summary_cards.clear()
            with summary_cards:
                _stat_card(
                    "group", "Active CoWorkers", str(_active_cw),
                    f"{_total_cw} total · {len(_by_dept)} departments",
                    "blue", link="/coworkers",
                )
                _stat_card(
                    "play_circle", "Runs today", str(_runs_today),
                    (f"{_active_now} running now" if _active_now else f"{_total_runs} total"),
                    "teal", link="/runs",
                )
                _stat_card(
                    "trending_up", "Success rate", f"{_success_rate}%",
                    f"{_completed} ok · {_failed} failed",
                    "green", link="/runs",
                )
                _stat_card(
                    "description", "Reports", str(_reports_count),
                    f"{_reports_count} analysis documents",
                    "purple", link="/runs",
                )

        _render_summary_cards()
        ui.timer(3.0, _render_summary_cards)

        # --- Row 2: Runs over time + Status donut + Top CoWorkers (live refreshed) ---
        charts_container = ui.element("div").classes("w-full grid grid-cols-3 gap-4 mb-6")

        def _render_charts():
            fresh_runs = get_all_runs(user_id)
            _completed = sum(1 for r in fresh_runs if r.get("status") == "completed")
            _failed = sum(1 for r in fresh_runs if r.get("status") == "failed")
            _active_now = sum(1 for r in fresh_runs if r.get("status") in ("pending", "running", "cancelling"))
            _runs_per_cw = defaultdict(int)
            for r in fresh_runs:
                _runs_per_cw[r["coworker_name"]] += 1
            charts_container.clear()
            with charts_container:
                with ui.card().classes("col-span-2 p-5 rounded-2xl border-0"):
                    with ui.row().classes("w-full items-start justify-between mb-3"):
                        with ui.column().classes("gap-0"):
                            ui.label("Runs over time").classes("metric-label")
                            ui.label("Last 7 days").classes("text-xs mt-1").style("color: var(--text-muted)")
                        ui.icon("bar_chart", size="16px").style("color: #3b82f6; opacity: 0.8")
                    ui.html(_build_runs_bar_chart(fresh_runs, days=7))
                with ui.column().classes("gap-4"):
                    with ui.card().classes("p-5 rounded-2xl border-0"):
                        with ui.row().classes("w-full items-start justify-between mb-2"):
                            ui.label("Run status").classes("metric-label")
                            ui.icon("donut_large", size="16px").style("color: #22c55e; opacity: 0.8")
                        ui.html(_build_status_donut(_completed, _failed, _active_now))
                    with ui.card().classes("p-5 rounded-2xl border-0"):
                        with ui.row().classes("w-full items-start justify-between mb-3"):
                            ui.label("Top CoWorkers").classes("metric-label")
                            ui.icon("leaderboard", size="16px").style("color: #8b5cf6; opacity: 0.8")
                        ui.html(_build_top_coworkers_bars(_runs_per_cw, limit=5))

        _render_charts()
        ui.timer(3.0, _render_charts)

        # --- Recent feedback panel ---
        feedback_container = ui.element("div").classes("w-full mb-6")

        def _render_feedback_panel():
            from db import get_recent_feedback_all
            feedback_container.clear()
            entries = get_recent_feedback_all(user_id, limit=8)
            with feedback_container:
                with ui.card().classes("w-full p-5 rounded-2xl border-0"):
                    with ui.row().classes("w-full items-center justify-between mb-3"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("forum", size="20px").style("color: #3b82f6")
                            ui.label("Recent feedback").classes("text-base font-semibold")
                        if entries:
                            ui.label(f"Last {len(entries)}").classes("text-xs").style(
                                "color: var(--text-muted)"
                            )
                    if not entries:
                        ui.label(
                            "No feedback yet — Reward, Penalise, or Suspend a CoWorker to see entries here."
                        ).classes("text-xs italic py-2").style("color: var(--text-muted)")
                        return
                    for fb in entries:
                        _render_feedback_row(fb)

        _render_feedback_panel()
        # Refresh the panel every 10 seconds
        ui.timer(10.0, _render_feedback_panel)

        # --- Search bar for filtering CoWorkers ---
        search_input = ui.input(
            placeholder="Search CoWorkers by name, job, workflow, model...",
            on_change=lambda: _refresh_dept_cards(),
        ).classes("w-full mb-4").props("outlined dense clearable").style("max-width: 500px")
        search_input.props('prepend-icon="search"')

        dept_container = ui.column().classes("w-full gap-0")

        def _refresh_dept_cards():
            dept_container.clear()
            q = (search_input.value or "").strip().lower()
            # Filter coworkers by search query
            if q:
                filtered = [
                    cw for cw in coworkers
                    if q in cw["name"].lower()
                    or q in cw["job_description"].lower()
                    or q in cw["workflow"].lower()
                    or q in cw["model_name"].lower()
                    or q in cw["model_provider"].lower()
                ]
            else:
                filtered = coworkers

            # Re-group by workflow
            filtered_by_dept = defaultdict(list)
            for cw in filtered:
                filtered_by_dept[cw["workflow"]].append(cw)

            with dept_container:
                if not coworkers:
                    with ui.card().classes("w-full p-8 rounded-xl"):
                        with ui.column().classes("w-full items-center py-8"):
                            ui.icon("group_off", size="64px").classes("text-gray-300 dark:text-gray-600")
                            ui.label("No CoWorkers yet").classes("text-gray-400 dark:text-gray-500 text-lg mt-4")
                            ui.button("Add your first CoWorker", icon="add", on_click=lambda: ui.navigate.to("/coworkers")).props("color=primary outline")
                elif not filtered:
                    with ui.column().classes("w-full items-center py-8"):
                        ui.icon("search_off", size="48px").classes("text-gray-300 dark:text-gray-600")
                        ui.label(f'No CoWorkers match "{search_input.value}"').classes("text-gray-400 dark:text-gray-500 mt-2")
                        ui.button("Clear search", icon="clear", on_click=lambda: (setattr(search_input, "value", ""), _refresh_dept_cards())).props("flat dense color=primary")
                else:
                    dept_icons, dept_colors = _load_dept_meta()
                    for dept_name in sorted(filtered_by_dept.keys()):
                        dept_coworkers = filtered_by_dept[dept_name]
                        dept_icon = dept_icons.get(dept_name, "work")
                        dept_color = dept_colors.get(dept_name, "blue")

                        with ui.card().classes("w-full p-5 rounded-xl mb-4"):
                            # Department header
                            with ui.row().classes("w-full items-center gap-3 mb-4"):
                                ui.icon(dept_icon, size="28px").classes(f"text-{dept_color}-500")
                                ui.label(dept_name).classes("text-lg font-bold")
                                ui.badge(f"{len(dept_coworkers)} member{'s' if len(dept_coworkers) != 1 else ''}", color=dept_color).props("outline")
                                ui.space()
                                total_dept_runs = sum(runs_per_cw.get(c["name"], 0) for c in dept_coworkers)
                                if total_dept_runs:
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon("play_circle", size="16px").classes("text-gray-400 dark:text-gray-500")
                                        ui.label(f"{total_dept_runs} run{'s' if total_dept_runs != 1 else ''}").classes("text-sm text-gray-500 dark:text-gray-400")

                            # CoWorker chips/cards in this department
                            with ui.row().classes("w-full gap-3 flex-wrap"):
                                for idx, cw in enumerate(dept_coworkers):
                                    global_idx = coworkers.index(cw)
                                    grad = avatar_gradient(global_idx)
                                    initials = "".join(w[0] for w in cw["name"].split() if w)[:2].upper() or "CW"
                                    cw_runs = runs_per_cw.get(cw["name"], 0)

                                    # Check for outputs
                                    cw_outputs = get_coworker_dir(cw["name"]) / "outputs"
                                    has_report = (cw_outputs / "result.md").exists()

                                    with ui.card().classes("p-4 rounded-xl min-w-[260px] flex-1 max-w-[380px] cursor-pointer hover:shadow-md transition-shadow overflow-hidden").on(
                                        "click", lambda c=cw: ui.navigate.to("/coworkers")
                                    ):
                                        with ui.row().classes("items-center gap-3").style("overflow: hidden"):
                                            with ui.avatar(text_color="white", size="40px").style(
                                                f"background: {grad}; flex-shrink: 0"
                                            ):
                                                ui.label(initials).classes("text-sm font-bold")
                                            with ui.column().classes("gap-0 flex-1 min-w-0 overflow-hidden"):
                                                with ui.row().classes("items-center gap-2"):
                                                    ui.label(cw["name"]).classes("text-sm font-semibold truncate")
                                                    ui.badge(
                                                        cw["status"].upper(),
                                                        color=CW_STATUS_COLORS.get(cw["status"], "gray"),
                                                    ).props("outline").classes("text-[10px]")
                                                ui.label(cw["job_description"]).classes("text-xs text-gray-500 dark:text-gray-400").style(
                                                    "overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; width: 100%"
                                                )

                                        with ui.row().classes("items-center gap-4 mt-3"):
                                            with ui.row().classes("items-center gap-1"):
                                                ui.icon("smart_toy", size="14px").classes("text-gray-400 dark:text-gray-500")
                                                ui.label(f'{cw["model_provider"]}:{cw["model_name"]}').classes("text-[11px] text-gray-500 dark:text-gray-400 truncate")
                                            ui.space()
                                            if cw_runs:
                                                with ui.row().classes("items-center gap-1"):
                                                    ui.icon("play_circle", size="14px").classes("text-gray-400 dark:text-gray-500")
                                                    ui.label(f"{cw_runs}").classes("text-xs text-gray-500 dark:text-gray-400")
                                            if has_report:
                                                ui.icon("description", size="14px").classes("text-emerald-500").tooltip("Has report")

        _refresh_dept_cards()

        # --- Recent Runs (live refreshed) ---
        recent_runs_container = ui.column().classes("w-full")

        def _render_recent_runs():
            recent_runs_container.clear()
            fresh_runs = get_all_runs(user_id)[:5]
            if not fresh_runs:
                return
            with recent_runs_container:
                with ui.card().classes("w-full p-5 rounded-xl mt-2"):
                    with ui.row().classes("w-full items-center justify-between mb-4"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("history", size="24px").classes("text-blue-500")
                            ui.label("Recent Runs").classes("text-lg font-bold")
                        ui.button("View All", icon="arrow_forward", on_click=lambda: ui.navigate.to("/runs")).props("flat dense color=primary")

                    for r in fresh_runs:
                        cw_grad = avatar_gradient(0)
                        for i, cw in enumerate(coworkers):
                            if cw["name"] == r["coworker_name"]:
                                cw_grad = avatar_gradient(i)
                                break
                        initials = "".join(w[0] for w in r["coworker_name"].split() if w)[:2].upper() or "CW"

                        status = r.get("status", "completed")
                        is_active = status in ("pending", "running", "cancelling")
                        ft = r.get("files_total", 0) or 0
                        fp = r.get("files_processed", 0) or 0

                        with ui.column().classes("w-full gap-1 py-2 px-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"):
                            with ui.row().classes("w-full items-center gap-3"):
                                with ui.avatar(text_color="white", size="32px").style(
                                    f"background: {cw_grad}"
                                ):
                                    ui.label(initials).classes("text-[10px] font-bold")
                                ui.label(r["coworker_name"]).classes("text-sm font-medium min-w-[140px]")
                                ui.badge(r.get("workflow", ""), color="blue").props("outline").classes("text-xs")
                                ui.space()
                                if is_active:
                                    ui.spinner("dots", size="xs").classes("text-blue-400")
                                    msg = r.get("progress_message", "Running...") or "Running..."
                                    if ft:
                                        msg = f"{msg}  ({fp}/{ft})"
                                    ui.label(msg[:60]).classes("text-xs text-blue-400 truncate")
                                else:
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon("input", size="14px").classes("text-gray-400 dark:text-gray-500")
                                        ui.label(f"{ft}").classes("text-xs text-gray-500 dark:text-gray-400")
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon("output", size="14px").classes("text-gray-400 dark:text-gray-500")
                                        ui.label(f"{r.get('output_count', 0)}").classes("text-xs text-gray-500 dark:text-gray-400")
                                    if r.get("has_report"):
                                        ui.icon("description", size="16px").classes("text-emerald-500")
                                    if r.get("pdf_files"):
                                        ui.icon("picture_as_pdf", size="16px").classes("text-purple-500")
                                    if status == "failed":
                                        ui.icon(status_icon("failed"), size="16px").classes(status_tw("failed"))
                                ts = _format_ts(r.get("started_at", ""))
                                ui.label(ts).classes("text-xs text-gray-500 dark:text-gray-400 font-mono min-w-[130px] text-right")

                            # Live progress bar for running rows
                            if is_active and ft:
                                pct = fp / ft if ft else 0
                                ui.linear_progress(value=pct, show_value=False).props("rounded color=blue size=4px").classes("ml-12 mr-2")

                        ui.separator().classes("my-0")

        _render_recent_runs()
        # Auto-refresh — fast when active runs exist, slower otherwise
        ui.timer(3.0, _render_recent_runs)


_STAT_ACCENT = {
    "blue":   "#3b82f6",
    "teal":   "#14b8a6",
    "purple": "#8b5cf6",
    "green":  "#22c55e",
}


def _stat_card(icon: str, title: str, value: str, subtitle: str, color: str, link: str = ""):
    """Minimal stat card — Linear/Vercel style. Label on top, huge number below."""
    accent = _STAT_ACCENT.get(color, "#3b82f6")
    classes = "p-5 rounded-2xl flex-1 min-w-[200px] border-0"
    if link:
        classes += " cursor-pointer transition-all hover:translate-y-[-1px]"
    card = ui.card().classes(classes)
    if link:
        card.on("click", lambda: ui.navigate.to(link))
    with card:
        # Top row: label + optional icon accent dot
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(title).classes("metric-label")
            ui.icon(icon, size="16px").style(f"color: {accent}; opacity: 0.8")
        # Big number
        ui.label(value).classes("metric-value mt-2").style("color: var(--text-primary)")
        # Subtitle
        if subtitle:
            ui.label(subtitle).classes("text-xs mt-2").style(
                "color: var(--text-muted); font-variant-numeric: tabular-nums"
            )


def _format_ts(ts: str) -> str:
    """Format a DB or folder timestamp for display."""
    if not ts:
        return ""
    # DB format already readable: '2026-04-09 22:11:47'
    if "-" in ts[:5]:
        return ts[:19].replace("T", " ")
    # Folder format: 20260409_221147
    try:
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
    except (IndexError, ValueError):
        return ts


# ============================================================
# Dashboard charts — inline SVG (no chart library dependency)
# ============================================================

def _build_runs_bar_chart(all_runs: list, days: int = 7) -> str:
    """Vertical bar chart: runs per day for last N days, stacked by status."""
    from datetime import datetime as _dt, timedelta as _td
    from collections import defaultdict as _dd

    today = _dt.now().date()
    # Buckets keyed by date string
    buckets = {(today - _td(days=days - 1 - i)): {"completed": 0, "failed": 0, "other": 0}
               for i in range(days)}

    for r in all_runs:
        ts = r.get("started_at", "") or ""
        if len(ts) < 10:
            continue
        try:
            d = _dt.strptime(ts[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d not in buckets:
            continue
        s = r.get("status", "completed")
        if s == "completed":
            buckets[d]["completed"] += 1
        elif s == "failed":
            buckets[d]["failed"] += 1
        else:
            buckets[d]["other"] += 1

    totals = [sum(v.values()) for v in buckets.values()]
    max_val = max(totals) if any(totals) else 1

    # Dimensions
    W, H = 620, 140
    pad_l, pad_r, pad_t, pad_b = 24, 12, 12, 28
    chart_w = W - pad_l - pad_r
    chart_h = H - pad_t - pad_b
    n = len(buckets)
    col_w = chart_w / n
    bar_w = min(44, col_w - 8)

    COL_OK = "#22c55e"
    COL_FAIL = "#ef4444"
    COL_OTH = "#94a3b8"
    GRID = "rgba(148,163,184,0.15)"
    TXT = "var(--text-muted)"

    parts = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:{H}px;overflow:visible">']

    # Horizontal gridlines (3 lines: 33%, 66%, 100%)
    for frac in (0.33, 0.66, 1.0):
        y = pad_t + chart_h * (1 - frac)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 4}" y="{y + 3:.1f}" text-anchor="end" '
            f'font-family="var(--font-mono)" font-size="9" fill="{TXT}">'
            f'{int(max_val * frac)}</text>'
        )

    # Bars
    for i, (d, counts) in enumerate(buckets.items()):
        x = pad_l + col_w * i + (col_w - bar_w) / 2
        total = sum(counts.values())
        if total == 0:
            # Empty-day indicator dot
            y = pad_t + chart_h - 2
            parts.append(
                f'<circle cx="{x + bar_w / 2:.1f}" cy="{y:.1f}" r="1.5" fill="{TXT}" opacity="0.4"/>'
            )
        else:
            bottom = pad_t + chart_h
            # Stacked: other (bottom gray) → failed (red) → completed (green on top)
            for key, color in (("other", COL_OTH), ("failed", COL_FAIL), ("completed", COL_OK)):
                v = counts[key]
                if not v:
                    continue
                h = (v / max_val) * chart_h
                top = bottom - h
                parts.append(
                    f'<rect x="{x:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
                    f'fill="{color}" rx="3" ry="3"/>'
                )
                bottom = top
            # Total label above the bar
            label_y = pad_t + chart_h - (total / max_val) * chart_h - 4
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                f'font-family="var(--font-mono)" font-size="10" fill="var(--text-primary)" '
                f'font-weight="600">{total}</text>'
            )

        # Day label (DOW)
        dow = d.strftime("%a").upper()
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{H - 8}" text-anchor="middle" '
            f'font-family="var(--font-sans)" font-size="10" fill="{TXT}">'
            f'{dow}</text>'
        )

    # Legend (bottom right)
    legend_x = W - pad_r - 140
    legend_y = H - 4
    parts.append(
        f'<g font-family="var(--font-sans)" font-size="9" fill="{TXT}">'
        f'<rect x="{legend_x}" y="{legend_y - 8}" width="8" height="8" fill="{COL_OK}" rx="1"/>'
        f'<text x="{legend_x + 12}" y="{legend_y - 1}">Done</text>'
        f'<rect x="{legend_x + 48}" y="{legend_y - 8}" width="8" height="8" fill="{COL_FAIL}" rx="1"/>'
        f'<text x="{legend_x + 60}" y="{legend_y - 1}">Failed</text>'
        f'</g>'
    )

    parts.append("</svg>")
    return "".join(parts)


def _build_status_donut(completed: int, failed: int, running: int) -> str:
    """Donut chart for run status split."""
    total = completed + failed + running
    if total == 0:
        return (
            '<div style="display:flex;align-items:center;justify-content:center;'
            'height:150px;color:var(--text-muted);font-size:12px">No runs yet</div>'
        )

    segs = [
        (completed, "#22c55e"),
        (failed, "#ef4444"),
        (running, "#3b82f6"),
    ]

    # Donut geometry
    size = 150
    cx = size / 2
    cy = size / 2
    r = 52
    stroke_w = 16
    circumference = 2 * 3.14159265 * r

    parts = [
        f'<div style="display:flex;gap:16px;align-items:center">',
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="flex-shrink:0">',
        # Background ring
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="rgba(148,163,184,0.15)" stroke-width="{stroke_w}"/>',
    ]
    # Segments
    offset = 0
    for value, color in segs:
        if value == 0:
            continue
        frac = value / total
        length = circumference * frac
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="{stroke_w}" stroke-linecap="butt" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += length

    # Center total
    parts.append(
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-family="var(--font-sans)" '
        f'font-weight="700" font-size="22" fill="var(--text-primary)">{total}</text>'
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-family="var(--font-sans)" '
        f'font-size="9" fill="var(--text-muted)">TOTAL RUNS</text>'
    )
    parts.append("</svg>")

    # Legend
    parts.append('<div style="display:flex;flex-direction:column;gap:8px;font-size:11px">')
    for label, value, color in (
        ("Completed", completed, "#22c55e"),
        ("Failed", failed, "#ef4444"),
        ("Running", running, "#3b82f6"),
    ):
        pct = int(value / total * 100) if total else 0
        parts.append(
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="width:8px;height:8px;border-radius:2px;background:{color};flex-shrink:0"></span>'
            f'<span style="color:var(--text-secondary);min-width:70px">{label}</span>'
            f'<span style="font-family:var(--font-mono);font-weight:600;color:var(--text-primary)">{value}</span>'
            f'<span style="color:var(--text-muted);font-size:10px">{pct}%</span>'
            f'</div>'
        )
    parts.append('</div></div>')
    return "".join(parts)


_FEEDBACK_STYLES = {
    "reward":   {"icon": "star",         "color": "#f59e0b", "bg": "rgba(245,158,11,0.14)",  "label": "Reward"},
    "penalise": {"icon": "report",       "color": "#f97316", "bg": "rgba(249,115,22,0.14)",  "label": "Improve"},
    "suspend":  {"icon": "pause_circle", "color": "#ef4444", "bg": "rgba(239,68,68,0.14)",   "label": "Suspended"},
}


def _render_feedback_row(fb: dict):
    """One row in the Recent Feedback panel."""
    style = _FEEDBACK_STYLES.get(fb["feedback_type"], _FEEDBACK_STYLES["reward"])
    ts = (fb.get("created_at") or "")[:19].replace("T", " ")
    content = (fb.get("content") or "").strip()
    # Truncate long content
    snippet = content if len(content) <= 160 else content[:155] + "…"

    with ui.row().classes("w-full items-start gap-3 py-2").style(
        "border-bottom: 1px solid var(--border-subtle)"
    ):
        # Icon bubble
        with ui.element("div").classes("rounded-xl p-2").style(
            f"background: {style['bg']}; flex-shrink: 0"
        ):
            ui.icon(style["icon"], size="18px").style(f"color: {style['color']}")
        # Main content
        with ui.column().classes("flex-1 gap-0 min-w-0"):
            with ui.row().classes("items-center gap-2"):
                ui.label(fb["coworker_name"]).classes("text-sm font-semibold").style(
                    "color: var(--text-primary)"
                )
                ui.label(style["label"]).classes("text-[10px] uppercase font-semibold").style(
                    f"color: {style['color']}; letter-spacing: 0.04em"
                )
                if fb.get("reason"):
                    ui.html(
                        f'<span class="pill pill-gray" style="font-size:10px">{fb["reason"]}</span>'
                    )
            ui.label(snippet).classes("text-xs mt-1 whitespace-pre-wrap").style(
                "color: var(--text-secondary); line-height: 1.5"
            )
        # Timestamp on the right
        ui.label(ts).classes("mono text-[10px] tnum").style(
            "color: var(--text-muted); flex-shrink: 0; min-width: 130px; text-align: right; padding-top: 2px"
        )


def _build_top_coworkers_bars(runs_per_cw: dict, limit: int = 5) -> str:
    """Horizontal bar list of top N CoWorkers by run count."""
    if not runs_per_cw:
        return (
            '<div style="color:var(--text-muted);font-size:12px;padding:8px 0">'
            'No activity yet'
            '</div>'
        )

    items = sorted(runs_per_cw.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    max_v = items[0][1] if items else 1

    parts = ['<div style="display:flex;flex-direction:column;gap:10px">']
    for name, count in items:
        pct = (count / max_v) * 100 if max_v else 0
        display_name = name if len(name) <= 20 else name[:18] + "…"
        parts.append(
            f'<div>'
            f'<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">'
            f'<span style="color:var(--text-secondary)">{display_name}</span>'
            f'<span style="font-family:var(--font-mono);color:var(--text-primary);font-weight:600">{count}</span>'
            f'</div>'
            f'<div style="height:6px;background:rgba(148,163,184,0.12);border-radius:3px;overflow:hidden">'
            f'<div style="height:100%;width:{pct:.1f}%;background:linear-gradient(90deg,#8b5cf6,#a78bfa);border-radius:3px"></div>'
            f'</div>'
            f'</div>'
        )
    parts.append('</div>')
    return "".join(parts)
