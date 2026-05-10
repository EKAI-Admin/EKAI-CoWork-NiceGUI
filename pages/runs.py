"""Runs page — chronological view of all coworker runs with search and filter."""

from datetime import datetime, date, timedelta
from pathlib import Path
from nicegui import ui, app
from auth import get_current_user
from db import get_all_runs, get_user_by_username, get_coworkers, delete_runs, get_coworker_by_id
from run_manager import launch_run
from theme import (
    avatar_gradient, status_tw, status_icon, status_label, status_badge_color,
)


def _show_pdf_dialog(pdf_path):
    import subprocess
    path = Path(pdf_path)
    if not path.exists():
        ui.notify("PDF report not found", type="negative")
        return
    with ui.dialog() as dialog, ui.card().classes("w-[500px]"):
        with ui.row().classes("w-full justify-between items-center mb-2"):
            ui.label("PDF Report").classes("text-xl font-bold")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")
        ui.label(f"📄 {path.name}").classes("text-lg")
        ui.label(f"Location: {path}").classes("text-sm text-gray-500 dark:text-gray-400 break-all")
        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            def open_file(p=path):
                subprocess.Popen(["open", str(p)])
            ui.button("Open PDF", icon="open_in_new", on_click=open_file).props("color=deep-purple")
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def _show_report_dialog(report_path):
    import re as _re
    path = Path(report_path)
    if not path.exists():
        ui.notify("Report file not found", type="negative")
        return
    content = path.read_text(errors="replace")

    # Extract headings for mini-TOC
    headings = []
    for line in content.splitlines():
        m = _re.match(r"^(#{1,4})\s+(.+)", line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))

    with ui.dialog() as dialog, ui.card().classes("w-[900px] max-h-[85vh]"):
        with ui.row().classes("w-full justify-between items-center mb-2"):
            ui.label("Run Report").classes("text-xl font-bold")
            with ui.row().classes("items-center gap-2"):
                def _copy():
                    escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
                    ui.run_javascript(f"navigator.clipboard.writeText(`{escaped}`)")
                    ui.notify("Report copied to clipboard", type="positive", icon="content_copy")
                ui.button(icon="content_copy", on_click=_copy).props("flat round dense").tooltip("Copy to clipboard")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        with ui.row().classes("w-full gap-4 items-start"):
            # Mini-TOC sidebar
            if headings:
                with ui.column().classes("min-w-[160px] max-w-[200px] gap-0"):
                    ui.label("Contents").classes("text-xs font-bold text-gray-500 dark:text-gray-400 mb-1")
                    for level, text in headings:
                        indent = (level - 1) * 8
                        ui.label(text).classes(
                            "text-[11px] text-gray-500 dark:text-gray-400 truncate cursor-default py-0.5"
                        ).style(f"padding-left: {indent}px; max-width: 190px")

            with ui.scroll_area().classes("flex-1").style("max-height: 70vh"):
                ui.markdown(content).classes("w-full")
    dialog.open()


def _show_script_log_dialog(log_text: str, coworker_name: str = ""):
    """Show captured stdout/stderr from pipeline script execution."""
    title = f"Script Log — {coworker_name}" if coworker_name else "Script Log"
    with ui.dialog() as dialog, ui.card().classes("w-[700px] max-h-[85vh]"):
        with ui.row().classes("w-full justify-between items-center mb-2"):
            ui.label(title).classes("text-lg font-bold")
            with ui.row().classes("items-center gap-2"):
                def _copy():
                    escaped = log_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
                    ui.run_javascript(f"navigator.clipboard.writeText(`{escaped}`)")
                    ui.notify("Log copied to clipboard", type="positive", icon="content_copy")
                ui.button(icon="content_copy", on_click=_copy).props("flat round dense").tooltip("Copy to clipboard")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        with ui.scroll_area().classes("w-full").style("max-height: 70vh"):
            # Render as pre-formatted monospace text with subtle styling
            ui.html(
                f'<pre style="font-size: 12px; line-height: 1.6; white-space: pre-wrap; '
                f'word-break: break-all; font-family: ui-monospace, monospace; '
                f'padding: 12px; border-radius: 8px; '
                f'background: #1e293b; color: #e2e8f0;">'
                + log_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    .replace("[stdout]", '<span style="color: #34d399">[stdout]</span>')
                    .replace("[stderr]", '<span style="color: #f87171">[stderr]</span>')
                    .replace("⚠ TIMEOUT", '<span style="color: #fbbf24">⚠ TIMEOUT</span>')
                    .replace("exit code: 0", '<span style="color: #34d399">exit code: 0</span>')
                + "</pre>"
            )
    dialog.open()


def _format_timestamp(ts: str) -> str:
    """Format a DB timestamp or folder-name timestamp for display."""
    if not ts:
        return ""
    # DB format: 2026-04-09 22:11:47 or ISO
    if "T" in ts or len(ts) > 15 and "-" in ts:
        return ts[:19].replace("T", " ")
    # Folder format: 20260409_221147
    try:
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
    except (IndexError, ValueError):
        return ts


def _parse_run_date(ts: str) -> date | None:
    """Parse a run started_at into a date for grouping. Handles both DB and folder formats."""
    if not ts:
        return None
    try:
        # DB format: '2026-04-09 22:11:47' or ISO
        if "-" in ts[:10]:
            return date.fromisoformat(ts[:10])
        # Folder format: '20260409_221147'
        return date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    except (ValueError, TypeError, IndexError):
        return None


def _day_group_label(d: date | None) -> str:
    """Return 'Today', 'Yesterday', or formatted date for a group header."""
    if d is None:
        return "Unknown date"
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    if (today - d).days < 7:
        return d.strftime("%A")  # weekday name
    return d.strftime("%a, %b %-d, %Y")


def runs_page():
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

    # Build coworker name->gradient map
    coworkers = get_coworkers(user_id)
    cw_grad_map = {}
    for idx, cw in enumerate(coworkers):
        cw_grad_map[cw["name"]] = avatar_gradient(idx)

    cw_workflows = sorted(set(cw["workflow"] for cw in coworkers))
    cw_names = sorted(cw["name"] for cw in coworkers)

    # Persisted compact mode
    compact_mode = {"value": app.storage.user.get("runs_compact", False)}

    # Bulk selection state
    selected_ids: set[int] = set()
    # Map coworker name -> coworker dict for re-run
    cw_by_name = {cw["name"]: cw for cw in coworkers}

    def _render_run_card(r, compact: bool):
        grad = cw_grad_map.get(r["coworker_name"], avatar_gradient(0))
        initials = "".join(w[0] for w in r["coworker_name"].split() if w)[:2].upper() or "CW"
        run_dir = Path(r.get("run_dir", "")) if r.get("run_dir") else None
        run_status = r.get("status", "completed")
        st_icon = status_icon(run_status)
        st_tw = status_tw(run_status)
        st_label = status_label(run_status)
        ft = r.get("files_total", 0) or 0
        fp = r.get("files_processed", 0) or 0
        oc = r.get("output_count", 0) or 0
        rid = r.get("id")

        if compact:
            # Single-line compact row
            with ui.row().classes(
                "w-full items-center gap-3 px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors border border-gray-100 dark:border-gray-800"
            ):
                if rid is not None:
                    def _toggle_sel(e, run_id=rid):
                        if e.value:
                            selected_ids.add(run_id)
                        else:
                            selected_ids.discard(run_id)
                        _refresh_bulk_bar()
                    ui.checkbox("", value=rid in selected_ids, on_change=_toggle_sel).props("dense")
                with ui.avatar(text_color="white", size="24px").style(
                    f"background: {grad}"
                ):
                    ui.label(initials).classes("text-[9px] font-bold")
                ui.label(r["coworker_name"]).classes("text-xs font-semibold min-w-[140px] truncate")
                ui.badge(r.get("workflow", ""), color="blue").props("outline").classes("text-[10px]")
                if run_status in ("pending", "running", "cancelling"):
                    ui.spinner("dots", size="xs").classes(st_tw)
                else:
                    ui.icon(st_icon, size="14px").classes(st_tw)
                ui.label(st_label).classes(f"text-[10px] {st_tw} font-medium")
                ui.space()
                with ui.row().classes("items-center gap-2"):
                    ui.icon("input", size="12px").classes("text-gray-400 dark:text-gray-500")
                    ui.label(f"{ft}").classes("text-[10px] text-gray-500 dark:text-gray-400")
                    ui.icon("output", size="12px").classes("text-gray-400 dark:text-gray-500")
                    ui.label(f"{oc}").classes("text-[10px] text-gray-500 dark:text-gray-400")
                if r.get("has_report"):
                    ui.icon("description", size="14px").classes("text-emerald-500")
                if r.get("pdf_files"):
                    ui.icon("picture_as_pdf", size="14px").classes("text-purple-500")
                ui.label(_format_timestamp(r.get("started_at", ""))[11:16]).classes("text-[10px] text-gray-500 dark:text-gray-400 font-mono min-w-[40px] text-right")
            return

        # Comfortable mode (existing card layout)
        with ui.card().classes("w-full p-4 rounded-xl"):
            with ui.row().classes("w-full items-center gap-4"):
                if rid is not None:
                    def _toggle_sel_c(e, run_id=rid):
                        if e.value:
                            selected_ids.add(run_id)
                        else:
                            selected_ids.discard(run_id)
                        _refresh_bulk_bar()
                    ui.checkbox("", value=rid in selected_ids, on_change=_toggle_sel_c).props("dense")
                with ui.avatar(text_color="white", size="38px").style(
                    f"background: {grad}"
                ):
                    ui.label(initials).classes("text-xs font-bold")

                with ui.column().classes("flex-1 gap-0 min-w-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(r["coworker_name"]).classes("text-base font-semibold truncate")
                        ui.badge(r.get("workflow", ""), color="blue").props("outline").classes("text-xs")
                    with ui.row().classes("items-center gap-3 mt-1"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("smart_toy", size="14px").classes("text-gray-400 dark:text-gray-500")
                            ui.label(f'{r["model_provider"]}:{r["model_name"]}').classes("text-xs text-gray-500 dark:text-gray-400")

                with ui.row().classes("items-center gap-1").style("flex-shrink: 0"):
                    if run_status in ("pending", "running", "cancelling"):
                        ui.spinner("dots", size="xs").classes(st_tw)
                    else:
                        ui.icon(st_icon, size="16px").classes(st_tw)
                    ui.label(st_label).classes(f"text-xs {st_tw} font-medium")

                with ui.column().classes("items-end gap-1").style("flex-shrink: 0"):
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("schedule", size="16px").classes("text-gray-400 dark:text-gray-500")
                        ui.label(_format_timestamp(r.get("started_at", ""))).classes("text-sm text-gray-500 dark:text-gray-400 font-mono")
                    with ui.row().classes("items-center gap-3"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("input", size="14px").classes("text-gray-400 dark:text-gray-500")
                            ui.label(f"{ft} in").classes("text-xs text-gray-500 dark:text-gray-400")
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("output", size="14px").classes("text-gray-400 dark:text-gray-500")
                            ui.label(f"{oc} out").classes("text-xs text-gray-500 dark:text-gray-400")

            if run_status in ("pending", "running", "cancelling"):
                msg = r.get("progress_message", "")
                if msg:
                    with ui.row().classes("w-full items-center gap-2 mt-2 ml-12"):
                        ui.spinner("dots", size="xs").classes("text-blue-400")
                        ui.label(msg).classes("text-sm text-blue-400")
                if ft > 0:
                    pct = int(fp / ft * 100) if ft else 0
                    ui.linear_progress(value=pct / 100).classes("mt-1 ml-12").props("rounded color=blue")

            if run_status == "failed" and r.get("error"):
                with ui.row().classes("w-full mt-2 ml-12"):
                    ui.label(r["error"]).classes(f"text-sm {status_tw('failed')} break-all")

            if run_dir and (r.get("has_report") or r.get("pdf_files")):
                with ui.row().classes("w-full gap-2 flex-wrap mt-3 ml-12"):
                    if r.get("has_report"):
                        report_path = run_dir / "outputs" / "result.md"
                        def show_report(path=report_path):
                            _show_report_dialog(path)
                        ui.button("View Report", icon="description", on_click=show_report).props("color=primary outline dense size=sm")
                        if rid is not None:
                            ui.button("Open Full", icon="open_in_new",
                                      on_click=lambda run_id=rid: ui.navigate.to(f"/runs/{run_id}/report")).props("flat dense size=sm color=primary").tooltip("Open full-page report with TOC")

                    for pdf_str in r.get("pdf_files", []):
                        pdf_path = Path(pdf_str)
                        def show_pdf(path=pdf_path):
                            _show_pdf_dialog(path)
                        ui.button(f"View {pdf_path.stem}", icon="picture_as_pdf", on_click=show_pdf).props("color=deep-purple outline dense size=sm")

            # Script log button (shown for any run that has captured logs)
            slog = r.get("script_log", "")
            if slog:
                def show_script_log(log_text=slog, cw_name=r["coworker_name"]):
                    _show_script_log_dialog(log_text, cw_name)
                with ui.row().classes("w-full mt-2 ml-12"):
                    ui.button("Script Log", icon="terminal", on_click=show_script_log).props("flat dense size=sm color=grey-8").tooltip("View pipeline script stdout/stderr")

    def refresh_runs():
        runs_container.clear()
        all_runs = get_all_runs(user_id)

        # Apply filters
        search_val = search_input.value.strip().lower() if search_input.value else ""
        workflow_val = workflow_filter.value
        coworker_val = coworker_filter.value
        status_val = status_filter.value

        filtered = []
        for r in all_runs:
            if search_val:
                searchable = f"{r['coworker_name']} {r.get('workflow', '')} {r['model_provider']} {r['model_name']} {r.get('started_at', '')}".lower()
                if search_val not in searchable:
                    continue
            if workflow_val and r.get("workflow", "") != workflow_val:
                continue
            if coworker_val and r["coworker_name"] != coworker_val:
                continue
            if status_val and r.get("status", "completed") != status_val:
                continue
            filtered.append(r)

        compact = compact_mode["value"]

        with runs_container:
            # Filter chips: show active filters with remove buttons
            active_filters = []
            if search_val:
                active_filters.append(("search", f'"{search_val}"', lambda: (setattr(search_input, "value", ""), refresh_runs())))
            if workflow_val:
                active_filters.append(("workflow", workflow_val, lambda: (setattr(workflow_filter, "value", ""), refresh_runs())))
            if coworker_val:
                active_filters.append(("coworker", coworker_val, lambda: (setattr(coworker_filter, "value", ""), refresh_runs())))
            if status_val:
                active_filters.append(("status", status_val, lambda: (setattr(status_filter, "value", ""), refresh_runs())))

            if active_filters:
                with ui.row().classes("w-full items-center gap-2 flex-wrap mb-2"):
                    ui.label("Filters:").classes("text-xs text-gray-500 dark:text-gray-400 font-medium")
                    for kind, label, on_clear in active_filters:
                        chip = ui.chip(f"{kind}: {label}", icon="filter_alt", removable=True).props("color=primary outline")
                        chip.on("remove", lambda c=on_clear: c())
                    def clear_all():
                        search_input.value = ""
                        workflow_filter.value = ""
                        coworker_filter.value = ""
                        status_filter.value = ""
                        refresh_runs()
                    ui.button("Clear all", icon="clear", on_click=clear_all).props("flat dense size=sm color=red")

            if not filtered:
                with ui.column().classes("w-full items-center py-16"):
                    ui.icon("inbox", size="64px").classes("text-gray-300 dark:text-gray-600")
                    if all_runs:
                        ui.label("No runs match your filters").classes("text-gray-400 dark:text-gray-500 text-lg mt-4")
                        ui.label("Try adjusting search or filter criteria").classes("text-gray-300 dark:text-gray-500 mb-4")
                        def clear_all():
                            search_input.value = ""
                            workflow_filter.value = ""
                            coworker_filter.value = ""
                            status_filter.value = ""
                            refresh_runs()
                        ui.button("Clear filters", icon="clear", on_click=clear_all).props("color=primary outline")
                    else:
                        ui.label("No runs yet").classes("text-gray-400 dark:text-gray-500 text-lg mt-4")
                        ui.label("Configure a CoWorker and kick off your first run").classes("text-gray-300 dark:text-gray-500 mb-4")
                        ui.button("Go to CoWorkers", icon="group", on_click=lambda: ui.navigate.to("/coworkers")).props("color=primary")
                return

            # Summary banner
            with ui.row().classes("w-full gap-4 mb-2"):
                with ui.card().classes("p-3 flex-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("play_circle", size="24px").classes("text-blue-500")
                        ui.label(f"{len(filtered)} run{'s' if len(filtered) != 1 else ''}").classes("text-lg font-semibold")
                        ui.label("shown").classes("text-sm text-gray-500 dark:text-gray-400")
                active_count = sum(1 for r in filtered if r.get("status") in ("pending", "running", "cancelling"))
                if active_count:
                    with ui.card().classes("p-3 flex-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.spinner("dots", size="sm").classes("text-blue-500")
                            ui.label(f"{active_count} running").classes("text-lg font-semibold")
                            ui.label("now").classes("text-sm text-gray-500 dark:text-gray-400")
                reports_count = sum(1 for r in filtered if r.get("has_report"))
                with ui.card().classes("p-3 flex-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("description", size="24px").classes("text-emerald-500")
                        ui.label(f"{reports_count} report{'s' if reports_count != 1 else ''}").classes("text-lg font-semibold")
                        ui.label("available").classes("text-sm text-gray-500 dark:text-gray-400")
                pdfs_count = sum(len(r.get("pdf_files", [])) for r in filtered)
                with ui.card().classes("p-3 flex-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("picture_as_pdf", size="24px").classes("text-purple-500")
                        ui.label(f"{pdfs_count} PDF{'s' if pdfs_count != 1 else ''}").classes("text-lg font-semibold")
                        ui.label("generated").classes("text-sm text-gray-500 dark:text-gray-400")

            # Group runs by day
            current_day = object()  # sentinel
            for r in filtered:
                day = _parse_run_date(r.get("started_at", ""))
                if day != current_day:
                    current_day = day
                    label = _day_group_label(day)
                    with ui.row().classes("w-full items-center gap-2 mt-3 mb-1 sticky top-0 z-10 bg-gray-50 dark:bg-gray-900 py-1 rounded"):
                        ui.icon("event", size="14px").classes("text-gray-400 dark:text-gray-500")
                        ui.label(label).classes("text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400")
                        ui.separator().classes("flex-1")
                _render_run_card(r, compact)

    # Auto-refresh polls DB every few seconds — light query
    has_active = True

    from pages.layout import build_layout
    content = build_layout(user=user, active="runs")

    with content:
        ui.label("Runs").classes("text-2xl font-bold mb-4")

        # Search and filter bar
        with ui.card().classes("w-full p-4 rounded-xl mb-4"):
            with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                search_input = ui.input(
                    "Search",
                    placeholder="Search by name, workflow, model...",
                    on_change=lambda: refresh_runs(),
                ).classes("flex-1 min-w-[200px]").props("outlined dense clearable")

                workflow_filter = ui.select(
                    [""] + cw_workflows,
                    label="Workflow",
                    value="",
                    on_change=lambda: refresh_runs(),
                ).classes("min-w-[160px]").props("outlined dense clearable emit-value map-options")

                coworker_filter = ui.select(
                    [""] + cw_names,
                    label="CoWorker",
                    value="",
                    on_change=lambda: refresh_runs(),
                ).classes("min-w-[160px]").props("outlined dense clearable emit-value map-options")

                status_filter = ui.select(
                    ["", "pending", "running", "completed", "failed"],
                    label="Status",
                    value="",
                    on_change=lambda: refresh_runs(),
                ).classes("min-w-[120px]").props("outlined dense clearable emit-value map-options")

                def _toggle_density(e):
                    compact_mode["value"] = (e.value == "Compact")
                    app.storage.user["runs_compact"] = compact_mode["value"]
                    refresh_runs()

                ui.toggle(
                    ["Comfortable", "Compact"],
                    value="Compact" if compact_mode["value"] else "Comfortable",
                    on_change=_toggle_density,
                ).props("dense").classes("text-xs").tooltip("Row density")

                ui.button(icon="refresh", on_click=refresh_runs).props("flat round dense").tooltip("Refresh")

        # Bulk action bar — hidden when no selection
        bulk_bar = ui.row().classes(
            "w-full items-center gap-3 px-4 py-2 rounded-xl bg-blue-50 dark:bg-blue-900/30 "
            "border border-blue-200 dark:border-blue-800 mb-2"
        )
        bulk_bar.visible = False
        bulk_count_label = None
        with bulk_bar:
            ui.icon("check_box", size="20px").classes("text-blue-600")
            bulk_count_label = ui.label("0 selected").classes("text-sm font-medium text-blue-700 dark:text-blue-300")
            ui.space()

            def _do_bulk_delete():
                if not selected_ids:
                    return
                ids_to_delete = list(selected_ids)
                delete_runs(ids_to_delete)
                selected_ids.clear()
                ui.notify(f"Deleted {len(ids_to_delete)} run(s)", type="info")
                refresh_runs()

            def _do_bulk_rerun():
                if not selected_ids:
                    return
                all_runs = get_all_runs(user_id)
                runs_map = {r["id"]: r for r in all_runs}
                launched = 0
                for rid in list(selected_ids):
                    r = runs_map.get(rid)
                    if not r:
                        continue
                    cw = cw_by_name.get(r["coworker_name"])
                    if not cw:
                        continue
                    result = launch_run(cw, user_id)
                    if result is not None:
                        launched += 1
                selected_ids.clear()
                if launched:
                    ui.notify(f"Re-launched {launched} run(s)", type="positive")
                else:
                    ui.notify("No runs could be re-launched (already running?)", type="warning")
                refresh_runs()

            def _clear_selection():
                selected_ids.clear()
                refresh_runs()

            ui.button("Re-run selected", icon="replay", on_click=_do_bulk_rerun).props("outline dense color=primary size=sm")
            ui.button("Delete selected", icon="delete", on_click=_do_bulk_delete).props("outline dense color=red size=sm")
            ui.button("Clear", icon="clear", on_click=_clear_selection).props("flat dense size=sm")

        def _refresh_bulk_bar():
            n = len(selected_ids)
            bulk_bar.visible = n > 0
            if bulk_count_label:
                bulk_count_label.text = f"{n} selected"

        runs_container = ui.column().classes("w-full gap-3")
        refresh_runs()

        # Auto-refresh every 3s if there are active runs
        if has_active:
            ui.timer(3.0, refresh_runs)
