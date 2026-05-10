"""Full-page report viewer with TOC sidebar and copy-to-clipboard."""

import re
from pathlib import Path
from nicegui import ui
from auth import get_current_user
from db import get_run_record, get_user_by_username


def _extract_headings(md_text: str) -> list[tuple[int, str, str]]:
    """Extract markdown headings. Returns [(level, text, anchor_id), ...]."""
    headings = []
    for line in md_text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            anchor = re.sub(r"[^\w\- ]", "", text).strip().lower().replace(" ", "-")
            headings.append((level, text, anchor))
    return headings


def report_page(run_id: int):
    user = get_current_user()
    if not user:
        ui.navigate.to("/login")
        return

    db_user = get_user_by_username(user["username"])
    if not db_user:
        ui.navigate.to("/login")
        return

    rec = get_run_record(run_id)
    if not rec or rec["user_id"] != db_user["id"]:
        ui.label("Report not found").classes("text-xl text-red-500 p-8")
        return

    run_dir = Path(rec.get("run_dir", ""))
    report_path = run_dir / "outputs" / "result.md"
    if not report_path.exists():
        ui.label("No report file found for this run").classes("text-xl text-gray-500 p-8")
        return

    md_text = report_path.read_text(errors="replace")
    headings = _extract_headings(md_text)

    from pages.layout import build_layout
    content = build_layout(user=user, active="runs")

    with content:
        # Header bar
        with ui.row().classes("w-full items-center justify-between mb-4"):
            with ui.row().classes("items-center gap-3"):
                ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/runs")).props("flat round dense")
                ui.label(f"Report — {rec['coworker_name']}").classes("text-2xl font-bold")
                ui.badge(rec.get("workflow", ""), color="blue").props("outline")
            with ui.row().classes("items-center gap-2"):
                ui.button("Copy to Clipboard", icon="content_copy",
                          on_click=lambda: _copy_to_clipboard(md_text)).props("outline dense")
                ui.button("Back to Runs", icon="list", on_click=lambda: ui.navigate.to("/runs")).props("flat dense")

        # Two-column layout: TOC sidebar + report content
        with ui.row().classes("w-full gap-6 items-start"):
            # TOC sidebar
            if headings:
                with ui.card().classes("p-4 rounded-xl min-w-[200px] max-w-[260px] sticky top-4"):
                    ui.label("Contents").classes("text-sm font-bold mb-2 text-gray-600 dark:text-gray-400")
                    for level, text, anchor in headings:
                        indent = (level - 1) * 12
                        ui.link(
                            text,
                            target=f"#{anchor}",
                        ).classes(
                            f"block text-xs py-0.5 text-gray-600 dark:text-gray-400 "
                            f"hover:text-blue-600 dark:hover:text-blue-400 no-underline truncate"
                        ).style(f"padding-left: {indent}px; max-width: 220px")

            # Report body
            with ui.card().classes("flex-1 p-6 rounded-xl min-w-0"):
                with ui.row().classes("w-full items-center gap-2 mb-3"):
                    ui.icon("schedule", size="16px").classes("text-gray-400 dark:text-gray-500")
                    ui.label(rec.get("started_at", "")[:19]).classes("text-xs text-gray-500 dark:text-gray-400 font-mono")
                    ui.icon("smart_toy", size="16px").classes("text-gray-400 dark:text-gray-500")
                    ui.label(f'{rec["model_provider"]}:{rec["model_name"]}').classes("text-xs text-gray-500 dark:text-gray-400")
                    ft = rec.get("files_total", 0) or 0
                    ui.icon("input", size="16px").classes("text-gray-400 dark:text-gray-500")
                    ui.label(f"{ft} file{'s' if ft != 1 else ''}").classes("text-xs text-gray-500 dark:text-gray-400")

                ui.separator().classes("mb-4")

                # Inject anchor ids into headings for TOC navigation
                anchored_md = md_text
                for level, text, anchor in headings:
                    hashes = "#" * level
                    # Replace first occurrence of this heading with an anchor-tagged version
                    original = f"{hashes} {text}"
                    replacement = f'<a id="{anchor}"></a>\n\n{original}'
                    anchored_md = anchored_md.replace(original, replacement, 1)

                with ui.scroll_area().classes("w-full").style("max-height: 80vh"):
                    ui.markdown(anchored_md).classes("w-full prose dark:prose-invert max-w-none")


def _copy_to_clipboard(text: str):
    """Copy text to clipboard via JS."""
    # Escape for JS string
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    ui.run_javascript(f"navigator.clipboard.writeText(`{escaped}`)")
    ui.notify("Report copied to clipboard", type="positive", icon="content_copy")
