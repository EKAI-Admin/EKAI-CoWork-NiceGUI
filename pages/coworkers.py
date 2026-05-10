"""CoWorkers list page — accordion cards with run, config, edit, delete actions."""

from datetime import datetime
from pathlib import Path
from nicegui import ui
from auth import get_current_user
from db import (
    get_coworkers, create_coworker, update_coworker, delete_coworker,
    get_settings, get_coworker_dir, get_prompt, save_prompt,
    get_user_by_username,
    list_skills, save_skill_bundle, delete_skill, get_skill_files, SkillValidationError,
    load_coworker_skill_manifest,
    get_active_run_for_coworker, get_run_record,
    get_last_run_for_coworker, get_recent_runs_for_coworker,
    request_cancel_run,
    clone_coworker,
    get_run_stats_for_coworker,
    create_feedback, get_feedback_for_coworker, set_coworker_status,
    get_departments,
)
import shutil
import re as _re
import asyncio
from run_manager import launch_run
from models import STATUS_OPTIONS, WORKFLOW_OPTIONS, CLAUDE_MODELS, get_ollama_models
from theme import avatar_gradient, CW_STATUS_COLORS, status_tw
from ai_runner import chat_with_coworker, load_coworker_skills_content


# Per-coworker chat history, keyed by coworker id. Survives dialog reopens.
_CHAT_HISTORIES: dict[int, list[dict]] = {}


# Status → fill color for sparkline bars
SPARK_COLORS = {
    "completed": "#10b981",   # emerald
    "failed": "#ef4444",      # red/rose
    "running": "#3b82f6",     # blue
    "pending": "#f59e0b",     # amber
    "cancelling": "#f59e0b",
}

# Color-name → hex for department left-border + accent usage across the app.
DEPT_COLOR_HEX = {
    "blue":    "#3b82f6",
    "teal":    "#14b8a6",
    "purple":  "#8b5cf6",
    "orange":  "#f97316",
    "indigo":  "#6366f1",
    "green":   "#22c55e",
    "pink":    "#ec4899",
    "red":     "#ef4444",
    "cyan":    "#06b6d4",
    "amber":   "#f59e0b",
}


def _get_dept_border_color(workflow_name: str) -> str:
    """DB-backed lookup of a department's accent color (hex)."""
    for d in get_departments():
        if d["name"] == workflow_name:
            return DEPT_COLOR_HEX.get(d.get("color") or "blue", "#94a3b8")
    return "#94a3b8"


def _format_time_ago(ts: str) -> str:
    """Convert an ISO/sqlite timestamp to '5m ago', '2h ago', '3d ago', etc."""
    if not ts:
        return ""
    try:
        # SQLite default: 'YYYY-MM-DD HH:MM:SS'
        dt = datetime.fromisoformat(ts.replace("T", " ")[:19])
    except (ValueError, TypeError):
        return ts[:10]
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 604800:
        return f"{secs // 86400}d ago"
    return dt.strftime("%Y-%m-%d")


def _build_sparkline_svg(runs: list[dict], width: int = 110, height: int = 22) -> str:
    """Render the recent runs as a tiny SVG sparkline (one bar per run, colored by status)."""
    if not runs:
        return ""
    n = len(runs)
    gap = 2
    bar_w = max(3, (width - gap * (n - 1)) // n)
    chart_w = bar_w * n + gap * (n - 1)
    bars = []
    for i, r in enumerate(runs):
        status = r.get("status", "completed")
        color = SPARK_COLORS.get(status, "#9ca3af")
        # Bar height encodes progress for active runs, full for finished
        ft = r.get("files_total") or 0
        fp = r.get("files_processed") or 0
        if status in ("running", "pending", "cancelling") and ft:
            frac = max(0.15, fp / ft)
        elif status == "failed":
            frac = 0.55
        else:
            frac = 1.0
        bh = max(3, int(height * frac))
        x = i * (bar_w + gap)
        y = height - bh
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" rx="1.5" fill="{color}"/>'
        )
    return (
        f'<svg viewBox="0 0 {chart_w} {height}" width="{chart_w}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(bars)}</svg>'
    )


def _build_timeline_html(
    file_names: list[str],
    files_processed: int,
    current_file: str = "",
    status: str = "running",
) -> str:
    """Render a horizontal file-processing timeline as inline SVG.

    Each file is a circle node connected by a line. Colors:
      - Done    → emerald (#10b981)
      - Current → blue (#3b82f6) with pulsing ring
      - Pending → gray (#d1d5db)
      - Failed  → rose (#ef4444)
      - Cancelled → amber (#f59e0b)
    """
    n = len(file_names)
    if n == 0:
        return ""

    node_r = 8
    gap = max(24, min(44, 520 // n))  # adaptive spacing
    pad_x = 16
    pad_y = 12
    w = pad_x * 2 + gap * (n - 1)
    h = pad_y * 2 + node_r * 2 + 22  # room for label below

    parts = [
        f'<svg viewBox="0 0 {w} {h}" width="{min(w, 600)}" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="overflow:visible">',
        '<style>',
        '  @keyframes tl-pulse { 0%,100%{r:11;opacity:.3} 50%{r:14;opacity:.1} }',
        '  .tl-pulse { animation: tl-pulse 1.2s ease-in-out infinite; }',
        '</style>',
    ]

    is_failed = status == "failed"
    is_cancelling = status == "cancelling"

    for i in range(n):
        cx = pad_x + i * gap
        cy = pad_y + node_r

        # Connector line to next node
        if i < n - 1:
            nx = pad_x + (i + 1) * gap
            line_color = "#10b981" if i < files_processed else "#e5e7eb"
            parts.append(
                f'<line x1="{cx + node_r}" y1="{cy}" x2="{nx - node_r}" y2="{cy}" '
                f'stroke="{line_color}" stroke-width="2" stroke-linecap="round"/>'
            )

        # Node circle
        if i < files_processed:
            fill = "#10b981"  # done
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" fill="{fill}"/>'
            )
            # Checkmark
            parts.append(
                f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" dominant-baseline="middle" '
                f'fill="white" font-size="9" font-weight="bold">✓</text>'
            )
        elif i == files_processed:
            # Current file
            if is_failed:
                fill = "#ef4444"
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node_r}" fill="{fill}"/>')
                parts.append(
                    f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" dominant-baseline="middle" '
                    f'fill="white" font-size="9" font-weight="bold">✗</text>'
                )
            elif is_cancelling:
                fill = "#f59e0b"
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node_r}" fill="{fill}"/>')
                parts.append(
                    f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" dominant-baseline="middle" '
                    f'fill="white" font-size="8" font-weight="bold">⏸</text>'
                )
            else:
                fill = "#3b82f6"
                # Pulse ring
                parts.append(
                    f'<circle cx="{cx}" cy="{cy}" r="11" fill="{fill}" opacity="0.2" class="tl-pulse"/>'
                )
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="{node_r}" fill="{fill}"/>')
                # Processing dot
                parts.append(
                    f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" dominant-baseline="middle" '
                    f'fill="white" font-size="9" font-weight="bold">⟳</text>'
                )
        else:
            fill = "#e5e7eb"  # pending
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{node_r}" fill="{fill}" stroke="#d1d5db" stroke-width="1"/>'
            )

        # File name label (truncated, only show for current and neighbors)
        short = file_names[i]
        if len(short) > 10:
            short = short[:8] + "…"
        show_label = (abs(i - files_processed) <= 1) or n <= 8
        if show_label:
            label_y = cy + node_r + 12
            label_color = "#6b7280" if i != files_processed else "#1d4ed8"
            font_w = "600" if i == files_processed else "400"
            parts.append(
                f'<text x="{cx}" y="{label_y}" text-anchor="middle" '
                f'fill="{label_color}" font-size="8" font-weight="{font_w}">{short}</text>'
            )

    # Tooltip title element
    parts.append(f'<title>{files_processed}/{n} files processed</title>')
    parts.append("</svg>")
    return "\n".join(parts)


def _get_run_file_names(run_dir: str) -> list[str]:
    """Read input file names from a run directory."""
    if not run_dir:
        return []
    inputs_path = Path(run_dir) / "inputs"
    if not inputs_path.exists():
        return []
    return sorted(f.name for f in inputs_path.iterdir() if f.is_file())


STATUS_COLORS = CW_STATUS_COLORS


def _get_model_options(provider: str, ollama_url: str = "http://localhost:11434") -> list[str]:
    return CLAUDE_MODELS if provider == "claude" else get_ollama_models(ollama_url)


def _show_pdf_dialog(pdf_path):
    from pathlib import Path
    import subprocess
    path = Path(pdf_path)
    if not path.exists():
        ui.notify("PDF report not found", type="negative")
        return
    with ui.dialog() as dialog, ui.card().classes("w-[500px]"):
        with ui.row().classes("w-full justify-between items-center mb-2"):
            ui.label("PDF Report Generated").classes("text-xl font-bold")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")
        ui.label(f"📄 {path.name}").classes("text-lg")
        ui.label(f"Location: {path}").classes("text-sm text-gray-500 break-all")
        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            def open_file(p=path):
                subprocess.Popen(["open", str(p)])
            ui.button("Open PDF", icon="open_in_new", on_click=open_file).props("color=deep-purple")
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def _show_report_dialog(report_path):
    import re as _re
    from pathlib import Path
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


def _build_mermaid_chart(manifest: dict) -> str:
    """Build a Mermaid flowchart from a skill manifest + rules."""
    import json
    lines = ["graph TD"]

    skill_name = manifest.get("name", "Skill Pipeline")
    description = manifest.get("description", "")

    # Style classes
    lines.append("    classDef inputCls fill:#4a90d9,stroke:#2c5f8a,color:#fff,rx:12,ry:12")
    lines.append("    classDef aiCls fill:#7c3aed,stroke:#5b21b6,color:#fff,rx:12,ry:12")
    lines.append("    classDef scriptCls fill:#059669,stroke:#047857,color:#fff,rx:8,ry:8")
    lines.append("    classDef outputCls fill:#d97706,stroke:#b45309,color:#fff,rx:12,ry:12")
    lines.append("    classDef rulesCls fill:#6366f1,stroke:#4f46e5,color:#fff,rx:4,ry:4")

    # Input node
    lines.append('    INPUT["fa:fa-file-alt Input Files<br/>Documents uploaded to inputs/"]')
    lines.append("    class INPUT inputCls")

    # Prompt node
    lines.append('    PROMPT["fa:fa-edit Prompt<br/>process/prompt.md"]')
    lines.append("    class PROMPT inputCls")

    # AI Extraction node
    extraction = manifest.get("extraction", {})
    rules_file = extraction.get("rules", "")
    if extraction:
        lines.append(f'    EXTRACT["fa:fa-brain AI Extraction<br/>Analyse each file with AI model"]')
        lines.append("    class EXTRACT aiCls")
        lines.append("    INPUT --> EXTRACT")
        lines.append("    PROMPT --> EXTRACT")

        # Rules node
        if rules_file:
            rules_label = rules_file.split("/")[-1] if "/" in rules_file else rules_file
            lines.append(f'    RULES["fa:fa-list-check Extraction Rules<br/>{rules_label}"]')
            lines.append("    class RULES rulesCls")
            lines.append("    RULES --> EXTRACT")

            # Try to load rules and show document categories
            skill_dir = manifest.get("_skill_dir")
            if skill_dir:
                rules_path = skill_dir / rules_file
                if rules_path.exists():
                    try:
                        rules_data = json.loads(rules_path.read_text())
                        checklist = rules_data.get("document_checklist", [])
                        if checklist:
                            categories = {}
                            for doc in checklist:
                                cat = doc.get("category", "other")
                                categories.setdefault(cat, []).append(doc.get("doc_id", ""))
                            cat_lines = "<br/>".join(
                                f"{cat.replace('_', ' ').title()}: {len(docs)}"
                                for cat, docs in sorted(categories.items())
                            )
                            lines.append(f'    CHECKLIST["fa:fa-clipboard-check Document Checklist<br/>{len(checklist)} documents across {len(categories)} categories<br/>{cat_lines}"]')
                            lines.append("    class CHECKLIST rulesCls")
                            lines.append("    CHECKLIST -.-> RULES")

                        cross_rules = rules_data.get("cross_document_rules", [])
                        if cross_rules:
                            critical = sum(1 for r in cross_rules if r.get("severity") == "critical")
                            warning = sum(1 for r in cross_rules if r.get("severity") == "warning")
                            advisory = sum(1 for r in cross_rules if r.get("severity") == "advisory")
                            sev_parts = []
                            if critical:
                                sev_parts.append(f"Critical: {critical}")
                            if warning:
                                sev_parts.append(f"Warning: {warning}")
                            if advisory:
                                sev_parts.append(f"Advisory: {advisory}")
                            sev_str = "<br/>".join(sev_parts) if sev_parts else ""
                            lines.append(f'    CROSSRULES["fa:fa-link Cross-Document Rules<br/>{len(cross_rules)} validation rules<br/>{sev_str}"]')
                            lines.append("    class CROSSRULES rulesCls")
                            lines.append("    CROSSRULES -.-> RULES")
                    except (json.JSONDecodeError, OSError):
                        pass

        lines.append('    EXTRACTIONS["fa:fa-database extractions.json<br/>Structured data from all files"]')
        lines.append("    class EXTRACTIONS outputCls")
        lines.append("    EXTRACT --> EXTRACTIONS")
        prev_node = "EXTRACTIONS"
    else:
        prev_node = "INPUT"

    # AI-only skill (SKILL.md fallback) — no extraction, no pipeline scripts
    pipeline_steps = manifest.get("pipeline", [])
    if not extraction and not pipeline_steps:
        skill_label = manifest.get("name", "skill")
        lines.append(
            f'    SKILLMD["fa:fa-book SKILL.md<br/>{skill_label}<br/>AI instructions only"]'
        )
        lines.append("    class SKILLMD rulesCls")
        lines.append('    AI["fa:fa-brain AI Analysis<br/>Per-file processing with prompt + skill"]')
        lines.append("    class AI aiCls")
        lines.append("    INPUT --> AI")
        lines.append("    PROMPT --> AI")
        lines.append("    SKILLMD -.-> AI")
        lines.append('    RESULT["fa:fa-file-alt result.md<br/>Combined AI output"]')
        lines.append("    class RESULT outputCls")
        lines.append("    AI --> RESULT")
        prev_node = "RESULT"

    # Pipeline steps
    for i, step in enumerate(pipeline_steps):
        step_name = step.get("step", f"step_{i}")
        script = step.get("script", "")
        script_label = script.split("/")[-1] if "/" in script else script
        node_id = f"STEP_{i}"

        # Determine output type from args
        args = step.get("args", [])
        has_pdf = any("{report_pdf}" in str(a) for a in args)
        has_results = any("{results}" in str(a) for a in args)

        lines.append(f'    {node_id}["fa:fa-code {step_name.title()}<br/>{script_label}"]')
        lines.append(f"    class {node_id} scriptCls")
        lines.append(f"    {prev_node} --> {node_id}")

        # Also connect rules if step uses them
        if any("{rules}" in str(a) for a in args) and rules_file:
            lines.append(f"    RULES -.-> {node_id}")

        # Output node for this step
        if has_results:
            out_id = f"OUT_{i}"
            lines.append(f'    {out_id}["fa:fa-check-circle results.json<br/>Verification results"]')
            lines.append(f"    class {out_id} outputCls")
            lines.append(f"    {node_id} --> {out_id}")
            prev_node = out_id
        elif has_pdf:
            out_id = f"OUT_{i}"
            lines.append(f'    {out_id}["fa:fa-file-pdf PDF Report<br/>outputs/*.pdf"]')
            lines.append(f"    class {out_id} outputCls")
            lines.append(f"    {node_id} --> {out_id}")
            prev_node = out_id
        else:
            prev_node = node_id

    # Final output
    lines.append(f'    FINAL["fa:fa-flag-checkered Complete<br/>Results in outputs/"]')
    lines.append("    class FINAL outputCls")
    lines.append(f"    {prev_node} --> FINAL")

    return "\n".join(lines)


def _show_visualise_dialog(coworker):
    """Show a visual flowchart of the skill bundle pipeline with interactive stats."""
    manifest = load_coworker_skill_manifest(coworker["name"])
    stats = get_run_stats_for_coworker(coworker["id"])

    with ui.dialog() as dialog, ui.card().classes("w-[950px] max-h-[90vh] p-6").style("overflow-y: auto"):
        with ui.row().classes("w-full justify-between items-center mb-2"):
            ui.label(f"Pipeline — {coworker['name']}").classes("text-xl font-bold")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        if not manifest:
            with ui.column().classes("w-full items-center py-12"):
                ui.icon("schema", size="64px").classes("text-gray-300 dark:text-gray-600")
                ui.label("No skill pipeline configured").classes("text-gray-400 dark:text-gray-500 text-lg mt-4")
                ui.label("Upload a skill bundle with a skill.json manifest to see the pipeline graph.").classes("text-gray-300 dark:text-gray-500 text-sm text-center")
        else:
            # Header info
            skill_name = manifest.get("name", "Unknown")
            skill_desc = manifest.get("description", "")
            skill_ver = manifest.get("version", "")
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.badge(skill_name, color="blue").classes("text-sm")
                if skill_ver:
                    ui.badge(f"v{skill_ver}", color="gray").props("outline").classes("text-xs")
            if skill_desc:
                ui.label(skill_desc).classes("text-sm text-gray-500 dark:text-gray-400 mb-3")

            # --- Interactive stats ribbon (clickable stage cards) ---
            if stats["total"] > 0:
                with ui.row().classes("w-full gap-3 mb-3 flex-wrap"):
                    # Overall stats
                    _pipeline_stat_card(
                        "play_circle", "Total Runs", str(stats["total"]),
                        f"{stats['success_rate']}% success rate", "blue",
                    )
                    _pipeline_stat_card(
                        "check_circle", "Completed", str(stats["completed"]),
                        f"avg {stats['avg_duration_s']}s", "green",
                    )
                    _pipeline_stat_card(
                        "error", "Failed", str(stats["failed"]),
                        stats["last_failure_date"] or "none", "red",
                    )
                    _pipeline_stat_card(
                        "description", "Avg Files", str(stats["avg_files"]),
                        f"~{stats['avg_per_file_s']}s per file", "purple",
                    )

            # Mermaid chart with interactive node details below
            chart = _build_mermaid_chart(manifest)

            with ui.scroll_area().classes("w-full").style("min-height: 300px; max-height: 45vh"):
                ui.mermaid(chart).classes("w-full")

            ui.label("Click a stage below for details").classes("text-[10px] text-gray-400 dark:text-gray-500 text-center w-full mt-1")

            # --- Interactive stage detail panels ---
            detail_container = ui.column().classes("w-full gap-0 mt-2")
            with detail_container:
                extraction = manifest.get("extraction", {})
                pipeline = manifest.get("pipeline", [])

                # Input stage
                with ui.expansion("📁 Input Files", icon="input").classes("w-full").props("dense header-class=text-sm"):
                    inputs_dir = get_coworker_dir(coworker["name"]) / "inputs"
                    input_files = sorted(f.name for f in inputs_dir.iterdir() if f.is_file()) if inputs_dir.exists() else []
                    if input_files:
                        with ui.row().classes("gap-2 flex-wrap"):
                            for f in input_files[:20]:
                                ui.chip(f, icon="description").props("dense outline").classes("text-[10px]")
                            if len(input_files) > 20:
                                ui.label(f"... and {len(input_files) - 20} more").classes("text-xs text-gray-400")
                        ui.label(f"{len(input_files)} file(s) in inputs/").classes("text-xs text-gray-500 dark:text-gray-400 mt-2")
                    else:
                        ui.label("No input files").classes("text-xs text-gray-400")

                # AI Extraction stage
                if extraction:
                    with ui.expansion("🧠 AI Extraction", icon="psychology").classes("w-full").props("dense header-class=text-sm"):
                        with ui.element("div").classes("grid grid-cols-2 gap-3"):
                            with ui.column().classes("gap-1"):
                                ui.label("Model").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{coworker['model_provider']}:{coworker['model_name']}").classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Avg per file").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{stats['avg_per_file_s']}s" if stats["total"] else "No data").classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Total runs").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(str(stats["total"])).classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Failures").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                fl = str(stats["failed"])
                                ui.label(fl).classes("text-xs font-medium" + (" text-red-500" if stats["failed"] else ""))
                        if stats.get("last_failure_error"):
                            ui.separator().classes("my-2")
                            ui.label("Last failure:").classes("text-[10px] text-gray-400")
                            ui.label(stats["last_failure_error"][:120]).classes("text-xs text-red-400 break-all")

                # AI-only stage (SKILL.md)
                if not extraction and not pipeline:
                    with ui.expansion("🧠 AI Analysis (SKILL.md)", icon="psychology").classes("w-full").props("dense header-class=text-sm"):
                        with ui.element("div").classes("grid grid-cols-2 gap-3"):
                            with ui.column().classes("gap-1"):
                                ui.label("Model").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{coworker['model_provider']}:{coworker['model_name']}").classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Avg per file").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{stats['avg_per_file_s']}s" if stats["total"] else "No data").classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Success rate").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{stats['success_rate']}%").classes("text-xs font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Avg duration").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(f"{stats['avg_duration_s']}s" if stats["total"] else "—").classes("text-xs font-medium")

                # Pipeline script stages
                for i, step in enumerate(pipeline):
                    step_name = step.get("step", f"step_{i}")
                    script = step.get("script", "")
                    args = step.get("args", [])
                    with ui.expansion(
                        f"⚙️ {step_name.title()} — {script}",
                        icon="code",
                    ).classes("w-full").props("dense header-class=text-sm"):
                        with ui.element("div").classes("grid grid-cols-2 gap-3"):
                            with ui.column().classes("gap-1"):
                                ui.label("Script").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                ui.label(script).classes("text-xs font-mono font-medium")
                            with ui.column().classes("gap-1"):
                                ui.label("Arguments").classes("text-[10px] text-gray-400 uppercase tracking-wider")
                                for a in args:
                                    ui.label(str(a)).classes("text-xs font-mono text-gray-600 dark:text-gray-400")
                        if stats["total"] > 0:
                            ui.separator().classes("my-2")
                            with ui.row().classes("gap-4"):
                                ui.label(f"Executed in {stats['total']} run(s)").classes("text-xs text-gray-500 dark:text-gray-400")
                                ui.label(f"{stats['completed']} succeeded").classes("text-xs text-emerald-600")
                                if stats["failed"]:
                                    ui.label(f"{stats['failed']} failed").classes("text-xs text-red-500")

                # Output stage
                with ui.expansion("🏁 Output", icon="output").classes("w-full").props("dense header-class=text-sm"):
                    outputs_dir = get_coworker_dir(coworker["name"]) / "outputs"
                    output_files = sorted(f.name for f in outputs_dir.iterdir() if f.is_file()) if outputs_dir.exists() else []
                    if output_files:
                        with ui.row().classes("gap-2 flex-wrap"):
                            for f in output_files[:15]:
                                icon_name = "picture_as_pdf" if f.endswith(".pdf") else "description"
                                ui.chip(f, icon=icon_name).props("dense outline").classes("text-[10px]")
                        ui.label(f"{len(output_files)} file(s) in outputs/").classes("text-xs text-gray-500 dark:text-gray-400 mt-2")
                    else:
                        ui.label("No outputs yet — run the pipeline first").classes("text-xs text-gray-400")

    dialog.open()


def _mini_stat(label: str, value: str):
    """Small inline stat used in the collapsed CoWorker card header."""
    with ui.column().classes("gap-0"):
        ui.label(label).classes("metric-label").style("font-size: 10px")
        ui.label(value).classes("mono font-semibold tnum").style(
            "font-size: 14px; color: var(--text-primary)"
        )


def _render_stats_bar(total: int, completed: int, failed: int) -> str:
    """Compact success-rate bar + inline breakdown for the card header."""
    other = max(total - completed - failed, 0)
    if total == 0:
        return (
            '<div style="display:flex;align-items:center;gap:10px;'
            'padding-top:12px;border-top:1px solid var(--border-subtle)">'
            '<span style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);letter-spacing:.02em">'
            'NO RUNS YET</span>'
            '</div>'
        )

    rate = int(completed / total * 100) if total else 0
    done_pct = (completed / total) * 100
    fail_pct = (failed / total) * 100
    other_pct = (other / total) * 100

    # Accent color for the headline number based on success rate
    if rate >= 80: rate_color = "#22c55e"
    elif rate >= 50: rate_color = "#f59e0b"
    else: rate_color = "#ef4444"

    return (
        '<div style="display:flex;flex-direction:column;gap:6px;'
        'padding-top:12px;border-top:1px solid var(--border-subtle)">'
        # Top line: success% (big) + "of N runs" + breakdown
        '<div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap">'
        f'<div style="display:flex;align-items:baseline;gap:6px">'
        f'<span style="font-family:var(--font-sans);font-size:22px;font-weight:700;letter-spacing:-0.02em;color:{rate_color};font-variant-numeric:tabular-nums">{rate}%</span>'
        f'<span style="font-family:var(--font-sans);font-size:11px;color:var(--text-muted);letter-spacing:.01em">success rate</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:10px;font-size:11px;font-family:var(--font-sans)">'
        f'<span style="color:var(--text-muted)">of</span>'
        f'<span style="font-family:var(--font-mono);color:var(--text-primary);font-weight:600">{total}</span>'
        f'<span style="color:var(--text-muted)">runs</span>'
        f'</div>'
        '</div>'
        # Stacked progress bar
        '<div style="display:flex;height:6px;border-radius:3px;overflow:hidden;background:rgba(148,163,184,0.15)">'
        + (f'<div style="width:{done_pct:.1f}%;background:#22c55e" title="{completed} completed"></div>' if completed else '')
        + (f'<div style="width:{fail_pct:.1f}%;background:#ef4444" title="{failed} failed"></div>' if failed else '')
        + (f'<div style="width:{other_pct:.1f}%;background:#3b82f6" title="{other} other"></div>' if other else '')
        + '</div>'
        # Legend with dots
        '<div style="display:flex;align-items:center;gap:14px;font-size:11px;font-family:var(--font-sans)">'
        + (f'<span style="display:inline-flex;align-items:center;gap:5px;color:var(--text-secondary)"><span style="width:6px;height:6px;border-radius:50%;background:#22c55e"></span><span style="font-family:var(--font-mono);font-weight:600;color:var(--text-primary)">{completed}</span> done</span>' if completed else '')
        + (f'<span style="display:inline-flex;align-items:center;gap:5px;color:var(--text-secondary)"><span style="width:6px;height:6px;border-radius:50%;background:#ef4444"></span><span style="font-family:var(--font-mono);font-weight:600;color:var(--text-primary)">{failed}</span> failed</span>' if failed else '')
        + (f'<span style="display:inline-flex;align-items:center;gap:5px;color:var(--text-secondary)"><span style="width:6px;height:6px;border-radius:50%;background:#3b82f6"></span><span style="font-family:var(--font-mono);font-weight:600;color:var(--text-primary)">{other}</span> running</span>' if other else '')
        + '</div>'
        '</div>'
    )


def _overview_stat(title: str, value: str, icon: str, color: str = "gray"):
    """Compact stat card used in the Overview tab. Greyscale icons.

    `color` parameter kept for backward compat but ignored — we always use
    a neutral muted icon tone. The value retains a subtle semantic hue only
    via the title-case accent at the data layer, if desired.
    """
    with ui.column().classes("gap-1 items-start p-3 rounded-xl").style(
        "background: var(--bg-surface-muted); min-width: 120px; flex: 1;"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon, size="14px").style(
                "color: var(--text-muted); opacity: 0.85"
            )
            ui.label(title).classes("metric-label").style("font-size: 10px")
        ui.label(value).classes("font-bold tnum leading-none").style(
            "font-size: 22px; letter-spacing: -0.015em; color: var(--text-primary);"
            "margin-top: 2px"
        )


def _build_dot_trail_svg(runs: list[dict], dot_size: int = 9, gap: int = 6) -> str:
    """Render recent runs as a row of colored dots — completed=green, failed=red,
    running=blue, pending=amber. Most recent on the right. Greyscale container."""
    if not runs:
        return ""
    # Show newest on right — reverse so the latest sits at the end
    ordered = list(reversed(runs))
    w = len(ordered) * (dot_size + gap) - gap
    h = dot_size + 2
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
    COLORS = {
        "completed":  "#22c55e",
        "failed":     "#ef4444",
        "running":    "#3b82f6",
        "pending":    "#f59e0b",
        "cancelling": "#f59e0b",
    }
    for i, r in enumerate(ordered):
        status = r.get("status", "completed")
        color = COLORS.get(status, "#94a3b8")
        cx = i * (dot_size + gap) + dot_size / 2
        cy = h / 2
        # Subtle stroke on the dot for definition
        out.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{dot_size/2:.1f}" '
            f'fill="{color}" stroke="{color}" stroke-opacity="0.25" stroke-width="2"/>'
        )
    out.append("</svg>")
    return "".join(out)


def _pipeline_stat_card(icon: str, title: str, value: str, subtitle: str, color: str):
    """Small stat card for pipeline stats ribbon."""
    with ui.card().classes("p-2 rounded-lg flex-1 min-w-[120px]"):
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon, size="18px").classes(f"text-{color}-500")
            with ui.column().classes("gap-0"):
                ui.label(value).classes("text-lg font-bold leading-tight")
                ui.label(title).classes("text-[10px] text-gray-500 dark:text-gray-400")
        ui.label(subtitle).classes("text-[10px] text-gray-400 dark:text-gray-500 mt-1")


def _show_coworker_dialog(on_save, coworker=None, user_id=None):
    settings = get_settings(user_id) if user_id else None
    default_provider = settings["default_provider"] if settings else "claude"
    default_model = settings["default_model"] if settings else "claude-sonnet-4-20250514"

    with ui.dialog() as dialog, ui.card().classes("w-[500px] p-6"):
        ui.label("Edit CoWorker" if coworker else "Add CoWorker").classes("text-xl font-bold mb-4")

        name = ui.input("Name", value=coworker["name"] if coworker else "").classes("w-full").props("outlined")
        job_desc = ui.textarea("Job Description", value=coworker["job_description"] if coworker else "").classes("w-full").props("outlined")

        # Pull department list from DB (source of truth)
        dept_names = [d["name"] for d in get_departments()]
        if not dept_names:
            # Fallback if no departments exist yet
            dept_names = list(WORKFLOW_OPTIONS)
        default_wf = coworker["workflow"] if coworker and coworker.get("workflow") in dept_names else dept_names[0]
        workflow = ui.select(
            dept_names,
            label="Department",
            value=default_wf,
        ).classes("w-full").props("outlined")
        with ui.row().classes("items-center gap-2 -mt-2"):
            ui.icon("info", size="12px").style("color: var(--text-muted)")
            ui.label("Manage departments in").classes("text-[11px]").style("color: var(--text-muted)")
            ui.link("Departments", "/departments").classes("text-[11px]").style("color: var(--accent)")
        status = ui.select(
            STATUS_OPTIONS,
            label="Status",
            value=coworker["status"] if coworker else "active",
        ).classes("w-full").props("outlined")

        provider_val = coworker["model_provider"] if coworker else default_provider
        provider = ui.select(
            ["claude", "ollama"],
            label="Model Provider",
            value=provider_val,
        ).classes("w-full").props("outlined")

        model_val = coworker["model_name"] if coworker else default_model
        model_opts = _get_model_options(provider_val)
        if model_val and model_val not in model_opts:
            model_opts = [model_val] + model_opts
        model = ui.select(
            model_opts,
            label="Model",
            value=model_val,
        ).classes("w-full").props("outlined")

        def on_provider_change(e):
            opts = _get_model_options(e.value)
            model.options = opts
            model.value = opts[0]
            model.update()

        provider.on_value_change(on_provider_change)

        error_label = ui.label("").classes("text-red-500 text-sm")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def save():
                if not name.value or not job_desc.value:
                    error_label.text = "Name and Job Description are required"
                    error_label.visible = True
                    return
                on_save(
                    name=name.value,
                    job_description=job_desc.value,
                    workflow=workflow.value,
                    status=status.value,
                    model_provider=provider.value,
                    model_name=model.value,
                )
                dialog.close()

            ui.button("Save", on_click=save).props("color=primary")

    dialog.open()


def _show_prompt_dialog(coworker):
    cw_dir = get_coworker_dir(coworker["name"])
    cw_name = coworker["name"]
    existing_prompt = get_prompt(cw_name)

    with ui.dialog() as dialog, ui.card().classes("w-[650px] p-6"):
        ui.label(f"Configure — {cw_name}").classes("text-xl font-bold mb-1")
        ui.label(f"{coworker['workflow']} · {cw_dir.name}/").classes("text-gray-500 text-sm mb-3 font-mono")

        with ui.tabs().classes("w-full") as tabs:
            prompt_tab = ui.tab("Prompt", icon="edit_note")
            skills_tab = ui.tab("Skills", icon="extension")

        with ui.tab_panels(tabs, value=prompt_tab).classes("w-full").style("min-height: 400px;"):
            with ui.tab_panel(prompt_tab):
                ui.label("Processing Prompt").classes("text-sm font-semibold mb-1")
                ui.label("Sent to the AI model along with each input file.").classes("text-xs text-gray-400 mb-3")
                prompt_input = ui.textarea(
                    value=existing_prompt,
                    placeholder="Enter the processing instructions for this CoWorker...",
                ).classes("w-full").props("outlined rows=12")

            with ui.tab_panel(skills_tab):
                ui.label("Skill Bundles").classes("text-sm font-semibold mb-1")
                ui.label(
                    "Upload .skill or .zip bundles. Each is extracted into its own folder under process/skills/."
                ).classes("text-xs text-gray-400 mb-3")

                skills_list_container = ui.column().classes("w-full gap-2")

                def refresh_skills_list():
                    skills_list_container.clear()
                    skills = list_skills(cw_name)
                    with skills_list_container:
                        if not skills:
                            ui.label("No skill bundles uploaded yet.").classes("text-gray-400 text-sm italic")
                            return
                        for sk in skills:
                            files = get_skill_files(cw_name, sk)
                            with ui.card().classes("w-full p-3"):
                                with ui.row().classes("w-full items-center justify-between"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon("extension", size="20px").classes("text-blue-500")
                                        ui.label(sk).classes("text-sm font-semibold font-mono")
                                    def do_delete(s=sk):
                                        delete_skill(cw_name, s)
                                        refresh_skills_list()
                                    ui.button(icon="delete", on_click=do_delete).props("flat dense round size=sm color=red")
                                if files:
                                    with ui.column().classes("ml-7 gap-0"):
                                        for f in files[:10]:
                                            ui.label(f).classes("text-xs text-gray-500 font-mono")
                                        if len(files) > 10:
                                            ui.label(f"... and {len(files) - 10} more").classes("text-xs text-gray-400 italic")

                refresh_skills_list()

                async def handle_upload(e):
                    content = await e.file.read()
                    try:
                        warnings = save_skill_bundle(cw_name, e.file.name, content)
                        refresh_skills_list()
                        if warnings:
                            ui.notify(
                                f"Skill uploaded with warnings:\n• " + "\n• ".join(warnings),
                                type="warning", multi_line=True, timeout=8000,
                            )
                        else:
                            ui.notify(f"Skill '{e.file.name}' uploaded and validated ✓", type="positive", timeout=3000)
                    except SkillValidationError as ve:
                        ui.notify(f"Skill rejected: {ve}", type="negative", multi_line=True, timeout=10000)

                ui.upload(
                    label="Upload Skill Bundle (.skill, .zip)",
                    on_upload=handle_upload,
                    multiple=True,
                    auto_upload=True,
                ).classes("w-full mt-3").props("accept='.skill,.zip'")

        success_label = ui.label("").classes("text-green-500 text-sm mt-2")
        success_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def save():
                save_prompt(cw_name, prompt_input.value)
                success_label.text = "Prompt saved to process/prompt.md"
                success_label.visible = True
                ui.timer(1.5, dialog.close, once=True)

            ui.button("Save", on_click=save).props("color=primary")

    dialog.open()


def _show_clone_dialog(coworker: dict, user_id: int, on_done):
    """Dialog to clone a CoWorker with a new name."""
    with ui.dialog() as dialog, ui.card().classes("w-[400px] p-6"):
        ui.label("Clone CoWorker").classes("text-xl font-bold mb-2")
        ui.label(f'Cloning "{coworker["name"]}" with its prompt, skills, and input files.').classes(
            "text-sm text-gray-500 dark:text-gray-400 mb-4"
        )
        new_name = ui.input(
            "New name",
            value=f'{coworker["name"]} (copy)',
        ).classes("w-full").props("outlined autofocus")

        error_label = ui.label("").classes("text-red-500 text-sm")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def do_clone():
                name = new_name.value.strip()
                if not name:
                    error_label.text = "Name is required"
                    error_label.visible = True
                    return
                try:
                    clone_coworker(coworker["id"], name, user_id)
                    ui.notify(f'Cloned as "{name}"', type="positive", icon="content_copy")
                    dialog.close()
                    on_done()
                except Exception as e:
                    error_label.text = str(e)
                    error_label.visible = True

            ui.button("Clone", icon="content_copy", on_click=do_clone).props("color=teal")

    dialog.open()


# ---------- Feedback dialogs: Reward / Penalise / Suspend ----------

SUSPEND_REASONS = [
    "Poor performance",
    "Inappropriate output",
    "Cost concerns",
    "Scheduled maintenance",
    "No longer needed",
    "Other",
]


def _show_reward_dialog(coworker: dict, user_id: int, on_done=None):
    """Modal for logging positive feedback ('reward')."""
    with ui.dialog() as dialog, ui.card().classes("w-[520px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-1"):
            with ui.element("div").classes("rounded-2xl p-2").style(
                "background: rgba(245,158,11,0.14)"
            ):
                ui.icon("star", size="22px").style("color: #f59e0b")
            ui.label("What did I do right?").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )
        ui.label(
            f'Share what {coworker["name"]} did well. This positive feedback is stored '
            f'and surfaces on the dashboard.'
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        feedback = ui.textarea(placeholder="e.g. Handled complex edge cases perfectly and the report was excellent.").classes(
            "w-full"
        ).props("outlined autofocus autogrow")

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                txt = (feedback.value or "").strip()
                if not txt:
                    error_label.text = "Please share some feedback."
                    error_label.visible = True
                    return
                create_feedback(
                    coworker["id"], coworker["name"], user_id,
                    "reward", txt,
                )
                ui.notify(
                    f"⭐ Reward logged for {coworker['name']}",
                    type="positive", icon="star", timeout=2500,
                )
                dialog.close()
                if on_done:
                    on_done()

            ui.button("Submit", icon="check", on_click=submit).props("color=amber")

    dialog.open()


def _show_penalise_dialog(coworker: dict, user_id: int, on_done=None):
    """Modal for logging constructive feedback ('penalise')."""
    with ui.dialog() as dialog, ui.card().classes("w-[520px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-1"):
            with ui.element("div").classes("rounded-2xl p-2").style(
                "background: rgba(249,115,22,0.14)"
            ):
                ui.icon("report", size="22px").style("color: #f97316")
            ui.label("What do I need to improve?").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )
        ui.label(
            f'Share areas where {coworker["name"]} can improve. The feedback is stored '
            f'and surfaces on the dashboard.'
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        feedback = ui.textarea(placeholder="e.g. Output was too verbose, missed key deadlines, ignored certain rules.").classes(
            "w-full"
        ).props("outlined autofocus autogrow")

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                txt = (feedback.value or "").strip()
                if not txt:
                    error_label.text = "Please share some feedback."
                    error_label.visible = True
                    return
                create_feedback(
                    coworker["id"], coworker["name"], user_id,
                    "penalise", txt,
                )
                ui.notify(
                    f"⚠ Feedback logged for {coworker['name']}",
                    type="warning", icon="report", timeout=2500,
                )
                dialog.close()
                if on_done:
                    on_done()

            ui.button("Submit", icon="check", on_click=submit).props("color=orange")

    dialog.open()


def _show_suspend_dialog(coworker: dict, user_id: int, on_done=None):
    """Modal for suspending a CoWorker. Requires reason + typing 'suspend'."""
    with ui.dialog() as dialog, ui.card().classes("w-[520px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-1"):
            with ui.element("div").classes("rounded-2xl p-2").style(
                "background: rgba(239,68,68,0.14)"
            ):
                ui.icon("pause_circle", size="22px").style("color: #ef4444")
            ui.label(f"Suspend {coworker['name']}?").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )
        ui.label(
            "While suspended, this CoWorker cannot be run and its Run button is disabled. "
            "You can reactivate it at any time."
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        reason_select = ui.select(
            SUSPEND_REASONS,
            label="Reason for suspension",
            value=SUSPEND_REASONS[0],
        ).classes("w-full mb-3").props("outlined")

        notes = ui.textarea(
            placeholder="Optional notes — why is this CoWorker being suspended?"
        ).classes("w-full mb-3").props("outlined autogrow")

        ui.label('Type "suspend" to confirm').classes(
            "text-xs mt-1"
        ).style("color: var(--text-muted); letter-spacing: 0.02em; text-transform: uppercase")
        confirm_input = ui.input(placeholder="suspend").classes(
            "w-full"
        ).props("outlined dense")

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                if (confirm_input.value or "").strip().lower() != "suspend":
                    error_label.text = 'You must type "suspend" to confirm.'
                    error_label.visible = True
                    return
                reason = reason_select.value or SUSPEND_REASONS[-1]
                notes_text = (notes.value or "").strip()
                content = f"Reason: {reason}"
                if notes_text:
                    content += f"\n\n{notes_text}"
                # Log the suspension as feedback
                create_feedback(
                    coworker["id"], coworker["name"], user_id,
                    "suspend", content, reason=reason,
                )
                # Flip the status
                set_coworker_status(coworker["id"], "suspended")
                ui.notify(
                    f"⏸ {coworker['name']} has been suspended",
                    type="negative", icon="pause", timeout=3000,
                )
                dialog.close()
                if on_done:
                    on_done()

            ui.button("Suspend CoWorker", icon="pause_circle", on_click=submit).props(
                "color=red"
            )

    dialog.open()


DELETE_REASONS = [
    "No longer needed",
    "Created by mistake",
    "Poor performance",
    "Consolidating team",
    "Migrated / replaced",
    "Testing — cleanup",
    "Other",
]


def _show_delete_coworker_dialog(coworker: dict, on_done=None):
    """Destructive-action modal. Requires reason + typing 'delete' to confirm.

    Wipes the coworker's DB record AND its filesystem folder (runs, outputs,
    inputs, skills, prompt, feedback — all gone).
    """
    # Pull quick stats so the user sees what they're about to lose
    from db import get_recent_runs_for_coworker, get_feedback_for_coworker
    run_count = len(get_recent_runs_for_coworker(coworker["id"], limit=500) or [])
    fb_count = len(get_feedback_for_coworker(coworker["id"], limit=500) or [])

    with ui.dialog() as dialog, ui.card().classes("w-[540px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-1"):
            with ui.element("div").classes("rounded-2xl p-2").style(
                "background: rgba(239,68,68,0.14)"
            ):
                ui.icon("delete_forever", size="22px").style("color: #ef4444")
            ui.label(f"Delete {coworker['name']}?").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )

        # What will be wiped
        ui.label(
            "This permanently removes the CoWorker and all associated data. "
            "This action cannot be undone."
        ).classes("text-sm mb-3").style("color: var(--text-secondary)")

        # Loss summary card
        with ui.card().classes("w-full p-3 rounded-xl border-0 mb-3").style(
            "background: rgba(239,68,68,0.06); border: 1px solid rgba(239,68,68,0.20) !important"
        ):
            ui.label("You will lose:").classes("text-[10px] uppercase font-semibold mb-1").style(
                "color: #ef4444; letter-spacing: 0.04em"
            )
            ui.html(
                f'<ul style="margin:0;padding-left:18px;font-size:12px;color:var(--text-secondary);line-height:1.7">'
                f'<li><b>{run_count}</b> run record{"s" if run_count != 1 else ""} and their outputs</li>'
                f'<li><b>{fb_count}</b> feedback entr{"ies" if fb_count != 1 else "y"} (rewards, penalties, suspensions)</li>'
                f'<li>All input files, prompt, skills, and analysis reports</li>'
                f'<li>The CoWorker folder <code style="font-family:var(--font-mono);font-size:11px">coworkers/{get_coworker_dir(coworker["name"]).name}/</code></li>'
                f'</ul>'
            )

        reason_select = ui.select(
            DELETE_REASONS,
            label="Reason for deletion",
            value=DELETE_REASONS[0],
        ).classes("w-full mb-3").props("outlined")

        notes = ui.textarea(
            placeholder="Optional notes — why is this CoWorker being deleted?"
        ).classes("w-full mb-3").props("outlined autogrow")

        ui.label('Type "delete" to confirm').classes(
            "text-xs mt-1"
        ).style("color: var(--text-muted); letter-spacing: 0.02em; text-transform: uppercase")
        confirm_input = ui.input(placeholder="delete").classes(
            "w-full"
        ).props("outlined dense")

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                if (confirm_input.value or "").strip().lower() != "delete":
                    error_label.text = 'You must type "delete" to confirm.'
                    error_label.visible = True
                    return
                try:
                    delete_coworker(coworker["id"])
                    ui.notify(
                        f"🗑 {coworker['name']} has been deleted",
                        type="negative", icon="delete_forever", timeout=3000,
                    )
                    dialog.close()
                    if on_done:
                        on_done()
                except Exception as e:
                    error_label.text = str(e)
                    error_label.visible = True

            ui.button("Delete CoWorker", icon="delete_forever", on_click=submit).props(
                "color=red"
            )

    dialog.open()


def _show_chat_dialog(coworker: dict, user_id: int):
    """Full-screen chat modal. Handlers inside ui.dialog() work reliably (unlike
    the earlier tab-panel attempt), so all chat interactions live here."""
    idx_for_color = max(0, coworker["id"] - 1)
    grad = avatar_gradient(idx_for_color)
    initials = "".join(w[0] for w in coworker["name"].split() if w)[:2].upper() or "CW"
    hist = _CHAT_HISTORIES.setdefault(coworker["id"], [])

    # Holders so handlers can reference elements created below
    refs: dict = {"log": None, "input": None}

    def _render_message(role: str, text: str):
        log = refs["log"]
        if log is None:
            return
        with log:
            if role == "user":
                with ui.row().classes("w-full justify-end"):
                    with ui.card().classes("p-2 rounded-xl max-w-[75%]").style(
                        "background: #3b82f6; color: white; border: 0; box-shadow: none"
                    ):
                        ui.label(text).classes("text-sm whitespace-pre-wrap")
            else:
                with ui.row().classes("w-full justify-start items-start gap-2"):
                    with ui.avatar(text_color="white", size="28px").style(f"background: {grad}"):
                        ui.label(initials).classes("text-[10px] font-bold")
                    with ui.card().classes("p-2 rounded-xl max-w-[75%]").style(
                        "background: var(--bg-surface); "
                        "border: 1px solid var(--border-subtle); "
                        "box-shadow: 0 1px 2px rgba(0,0,0,.05)"
                    ):
                        ui.markdown(text).classes("text-sm")
        # Auto-scroll to bottom via JS
        ui.run_javascript(
            f"setTimeout(() => {{ const el = document.getElementById('{log.id}'); "
            f"if (el) el.scrollTop = el.scrollHeight; }}, 50);"
        )

    async def _send_async(msg: str):
        """Actually hit the model and render the reply."""
        log = refs["log"]
        with log:
            typing = ui.row().classes("w-full justify-start items-center gap-2")
            with typing:
                ui.spinner("dots", size="sm").classes("text-gray-400")
                ui.label("thinking…").classes("text-xs text-gray-400 italic")

        try:
            def _call():
                from ai_runner import build_coworker_chat_context
                settings = get_settings(user_id)
                ollama_url = settings["ollama_base_url"] if settings else "http://localhost:11434"
                rich_system = build_coworker_chat_context(coworker, user_id)
                return chat_with_coworker(
                    coworker["model_provider"], coworker["model_name"],
                    rich_system, "",
                    hist[:-1],
                    msg,
                    ollama_base_url=ollama_url,
                )
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(None, _call)
            typing.delete()
            _render_message("assistant", reply)
            hist.append({"role": "assistant", "content": reply})
        except Exception as e:
            typing.delete()
            _render_message("assistant", f"⚠ Error: {e}")

    def send_chat():
        inp = refs["input"]
        if inp is None:
            return
        msg = (inp.value or "").strip()
        if not msg:
            return
        inp.value = ""
        _render_message("user", msg)
        hist.append({"role": "user", "content": msg})
        from nicegui import background_tasks
        background_tasks.create(_send_async(msg))

    with ui.dialog() as dialog, ui.card().classes("p-0 rounded-2xl").style(
        "width: 720px; max-width: 95vw; height: 80vh; display: flex; flex-direction: column"
    ):
        # Header
        with ui.row().classes("w-full items-center gap-3 px-5 py-4").style(
            "border-bottom: 1px solid var(--border-subtle); flex-shrink: 0"
        ):
            with ui.avatar(text_color="white", size="40px").style(f"background: {grad}"):
                ui.label(initials).classes("text-sm font-bold")
            with ui.column().classes("flex-1 gap-0 min-w-0"):
                ui.label(coworker["name"]).classes("text-base font-bold").style(
                    "letter-spacing: -0.01em"
                )
                ui.label(
                    f"{coworker['model_provider']}:{coworker['model_name']}"
                ).classes("text-xs mono").style("color: var(--text-muted)")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        # Chat log (scrollable, takes available height)
        log_container = ui.column().classes("w-full gap-2 px-5 py-4").style(
            "flex: 1; overflow-y: auto; background: var(--bg-surface-muted)"
        )
        refs["log"] = log_container

        # Replay existing history (if this dialog was opened before)
        if hist:
            for msg in hist:
                _render_message(msg["role"], msg["content"])
        else:
            with log_container:
                ui.html(
                    '<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:24px 0">'
                    f'✨ Chat with <b>{coworker["name"]}</b> — it knows its workflow, skills, '
                    'runs, outputs, inputs, and team feedback.</div>'
                )

        # Starter chips
        starters = [
            "How have your recent runs been going?",
            "Summarise your latest analysis.",
            "What input files are queued?",
            "What feedback has the team given you?",
            "Walk me through your skill pipeline.",
        ]
        with ui.row().classes("w-full flex-wrap px-5 py-2").style(
            "gap: 6px; border-top: 1px solid var(--border-subtle); flex-shrink: 0"
        ):
            for sp in starters:
                def _use(prompt=sp):
                    refs["input"].value = prompt
                    send_chat()
                ui.button(sp, on_click=_use).props("flat dense no-caps size=sm").style(
                    "font-size: 11px; border-radius: 999px;"
                    "background: var(--bg-surface-muted);"
                    "padding: 3px 12px; font-weight: 500"
                )

        # Input row
        with ui.row().classes("w-full items-end gap-2 px-5 py-4").style(
            "border-top: 1px solid var(--border-subtle); flex-shrink: 0"
        ):
            chat_input = ui.textarea(placeholder="Ask a question…").props(
                "outlined dense autogrow"
            ).classes("flex-1").style("max-height: 120px")
            refs["input"] = chat_input
            ui.button(icon="send", on_click=send_chat).props("round color=primary")

    dialog.open()


def coworkers_page():
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

    def refresh_cards():
        cards_container.clear()
        coworkers = get_coworkers(user_id)
        # Build a fresh department→color map once per render, so any changes
        # to department colors immediately show up without restart.
        dept_color_map = {
            d["name"]: DEPT_COLOR_HEX.get(d.get("color") or "blue", "#94a3b8")
            for d in get_departments()
        }
        with cards_container:
            if not coworkers:
                with ui.column().classes("w-full items-center py-16"):
                    ui.icon("group_off", size="64px").classes("text-gray-300")
                    ui.label("No CoWorkers yet").classes("text-gray-400 text-lg mt-4")
                    ui.label("Click the + button to add your first CoWorker").classes("text-gray-300")
                return

            for idx, cw in enumerate(coworkers):
                grad = avatar_gradient(idx)
                initials = "".join(w[0] for w in cw["name"].split() if w)[:2].upper() or "CW"
                border_color = dept_color_map.get(cw["workflow"], "#94a3b8")

                with ui.expansion().classes(
                    "cw-card rounded-2xl overflow-hidden transition-all"
                ).props("header-class=p-0").style(
                    f"border-left: 4px solid {border_color}"
                ) as expansion:

                    last_run = get_last_run_for_coworker(cw["id"])
                    recent_runs_quick = get_recent_runs_for_coworker(cw["id"], limit=100) or []
                    run_count = len(recent_runs_quick)
                    completed_count = sum(1 for r in recent_runs_quick if r.get("status") == "completed")
                    failed_count = sum(1 for r in recent_runs_quick if r.get("status") == "failed")

                    with expansion.add_slot("header"):
                        with ui.column().classes("w-full p-5").style("gap: 14px"):
                            # Top row: avatar + name/subtitle + chevron
                            with ui.row().classes("w-full items-center gap-3").style("overflow: hidden"):
                                with ui.avatar(text_color="white", size="52px").style(
                                    f"background: {grad}; flex-shrink: 0"
                                ):
                                    ui.label(initials).classes("text-base font-bold")

                                with ui.column().classes("flex-1 gap-0 min-w-0 overflow-hidden"):
                                    ui.label(cw["name"]).classes("font-bold truncate").style(
                                        "font-size: 18px; letter-spacing: -0.015em; color: var(--text-primary)"
                                    )
                                    ui.label(cw["job_description"]).classes("truncate").style(
                                        "overflow: hidden; text-overflow: ellipsis; white-space: nowrap; "
                                        "display: block; width: 100%; color: var(--text-secondary); "
                                        "font-size: 13px; margin-top: 2px"
                                    )

                                ui.icon("expand_more", size="22px").style(
                                    "color: var(--text-muted); flex-shrink: 0"
                                )

                            # Pills row — status, department, model, last run
                            with ui.row().classes("items-center flex-wrap").style("gap: 6px"):
                                status_pill_class = {
                                    "active": "pill-green",
                                    "inactive": "pill-gray",
                                    "archived": "pill-gray",
                                    "suspended": "pill-red",
                                }.get(cw["status"], "pill-gray")
                                status_icon = "⏸ " if cw["status"] == "suspended" else ""
                                ui.html(
                                    f'<span class="pill {status_pill_class}">{status_icon}{cw["status"].upper()}</span>'
                                )
                                if cw["workflow"]:
                                    ui.html(
                                        f'<span class="pill pill-blue">{cw["workflow"]}</span>'
                                    )
                                ui.html(
                                    f'<span class="pill pill-gray">'
                                    f'<span style="opacity:.6">{cw["model_provider"]}</span>'
                                    f'&nbsp;{cw["model_name"]}</span>'
                                )
                                if last_run:
                                    lr_status = last_run.get("status", "completed")
                                    ago = _format_time_ago(last_run.get("started_at", ""))
                                    if lr_status in ("pending", "running", "cancelling"):
                                        ui.html('<span class="pill pill-blue">● RUNNING</span>')
                                    elif lr_status == "failed":
                                        ui.html(f'<span class="pill pill-red">● FAILED · {ago}</span>')
                                    else:
                                        ui.html(f'<span class="pill pill-green">● {ago}</span>')

                            # Stats: success-rate bar + breakdown
                            ui.html(_render_stats_bar(run_count, completed_count, failed_count))

                            # Quick actions: Chat / Reward / Penalise / Suspend (right-aligned)
                            with ui.row().classes("w-full items-center justify-end").style(
                                "gap: 8px; padding-top: 4px"
                            ):
                                is_suspended = cw["status"] == "suspended"

                                def _do_chat(c=cw):
                                    _show_chat_dialog(c, user_id)

                                def _do_reward(c=cw):
                                    _show_reward_dialog(c, user_id)

                                def _do_penalise(c=cw):
                                    _show_penalise_dialog(c, user_id)

                                def _do_suspend(c=cw):
                                    _show_suspend_dialog(c, user_id, on_done=refresh_cards)

                                def _do_activate(c=cw):
                                    set_coworker_status(c["id"], "active")
                                    ui.notify(
                                        f"▶ {c['name']} has been reactivated",
                                        type="positive", icon="play_arrow", timeout=2500,
                                    )
                                    refresh_cards()

                                chat_count = len(_CHAT_HISTORIES.get(cw["id"], []))
                                chat_label = f"Chat · {chat_count}" if chat_count else "Chat"
                                ui.button(chat_label, icon="forum", on_click=_do_chat).props(
                                    "flat dense no-caps color=primary"
                                ).classes("cw-action-btn")
                                ui.button("Reward", icon="star", on_click=_do_reward).props(
                                    "flat dense no-caps color=amber"
                                ).classes("cw-action-btn")
                                ui.button("Penalise", icon="report", on_click=_do_penalise).props(
                                    "flat dense no-caps color=orange"
                                ).classes("cw-action-btn")

                                if is_suspended:
                                    ui.button(
                                        "Activate", icon="play_arrow", on_click=_do_activate,
                                    ).props(
                                        "flat dense no-caps color=green"
                                    ).classes("cw-action-btn")
                                else:
                                    ui.button(
                                        "Suspend", icon="pause", on_click=_do_suspend,
                                    ).props(
                                        "flat dense no-caps color=red-5"
                                    ).classes("cw-action-btn cw-action-suspend")

                    with ui.column().classes("w-full px-4 pb-4 gap-3"):

                        # Load manifest + skill info once for use across tabs
                        cw_manifest = load_coworker_skill_manifest(cw["name"])
                        inputs_dir = get_coworker_dir(cw["name"]) / "inputs"
                        outputs_dir = get_coworker_dir(cw["name"]) / "outputs"

                        # Placeholders — actual elements are created inside the Runs tab panel
                        # and stored in this dict so the poll function (defined after the tabs)
                        # can close over them.
                        cw_ui = {
                            "progress": None,
                            "status": None,
                            "result": None,
                            "timeline": None,
                            "report": None,
                            "outputs_list": None,
                        }

                        def _refresh_reports(c=cw, ui_refs=cw_ui):
                            rpt = ui_refs.get("report")
                            if rpt is None:
                                return
                            rpt.clear()
                            cw_outputs = get_coworker_dir(c["name"]) / "outputs"
                            existing_report = cw_outputs / "result.md"
                            existing_pdfs = list(cw_outputs.glob("*.pdf")) if cw_outputs.exists() else []
                            if existing_report.exists() or existing_pdfs:
                                rpt.visible = True
                                with rpt:
                                    with ui.row().classes("w-full gap-2 flex-wrap"):
                                        if existing_report.exists():
                                            def show_existing(path=existing_report):
                                                _show_report_dialog(path)
                                            ui.button("View Latest Analysis", icon="description", on_click=show_existing).props("color=primary outline dense size=sm")
                                        for pdf in existing_pdfs:
                                            def show_existing_pdf(path=pdf):
                                                _show_pdf_dialog(path)
                                            ui.button(f"View {pdf.stem}", icon="picture_as_pdf", on_click=show_existing_pdf).props("color=deep-purple outline dense size=sm")
                            else:
                                rpt.visible = False

                        # ============ TABS ============
                        with ui.tabs().classes("w-full").props("dense no-caps align=left inline-label") as tabs:
                            tab_overview = ui.tab("Overview", icon="info")
                            tab_inputs = ui.tab("Inputs", icon="input")
                            tab_processing = ui.tab("Processing", icon="settings")
                            tab_outputs = ui.tab("Outputs", icon="output")
                            tab_runs = ui.tab("Runs", icon="history")
                            tab_chat = ui.tab("Chat", icon="chat")

                        with ui.tab_panels(tabs, value=tab_overview).classes("w-full"):

                            # ========= OVERVIEW =========
                            with ui.tab_panel(tab_overview):
                                with ui.row().classes("w-full gap-4 flex-wrap"):
                                    # Left: metadata
                                    with ui.column().classes("flex-1 min-w-[280px] gap-3"):
                                        ui.label("Job").classes("text-[10px] uppercase text-gray-400 tracking-wider")
                                        ui.label(cw["job_description"]).classes("text-sm")

                                        with ui.row().classes("items-center gap-2 mt-2"):
                                            ui.icon("work", size="16px").classes("text-gray-400")
                                            ui.label(f"Department: {cw['workflow']}").classes("text-sm text-gray-600 dark:text-gray-300")
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("calendar_today", size="16px").classes("text-gray-400")
                                            join_display = cw["join_date"][:10] if cw["join_date"] else "N/A"
                                            ui.label(f"Joined {join_display}").classes("text-sm text-gray-600 dark:text-gray-300")
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("folder", size="16px").classes("text-gray-400")
                                            ui.label(f"coworkers/{get_coworker_dir(cw['name']).name}/").classes("text-xs text-gray-500 font-mono")
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("smart_toy", size="16px").classes("text-gray-400")
                                            ui.label(f"{cw['model_provider']}: {cw['model_name']}").classes("text-sm text-gray-600 dark:text-gray-300")

                                    # Right: stats
                                    with ui.column().classes("flex-1 min-w-[320px]").style("gap: 12px"):
                                        stats = get_run_stats_for_coworker(cw["id"])
                                        # 4-card grid, even widths
                                        with ui.element("div").classes("w-full grid grid-cols-4 gap-2"):
                                            _overview_stat("Total runs", str(stats.get("total", 0)), "play_circle")
                                            _overview_stat("Completed", str(stats.get("completed", 0)), "check_circle")
                                            _overview_stat("Failed", str(stats.get("failed", 0)), "error_outline")
                                            _overview_stat("Success rate", f"{stats.get('success_rate', 0)}%", "trending_up")

                                        # Recent runs — dot trail with legend
                                        recent_for_spark = get_recent_runs_for_coworker(cw["id"], limit=10)
                                        if recent_for_spark:
                                            with ui.column().classes("gap-1 mt-1"):
                                                with ui.row().classes("w-full items-center gap-3"):
                                                    ui.label("Recent runs").classes("metric-label").style("font-size: 10px")
                                                    ui.space()
                                                    # Tiny legend
                                                    ui.html(
                                                        '<div style="display:flex;gap:10px;font-size:10px;color:var(--text-muted)">'
                                                        '<span style="display:inline-flex;align-items:center;gap:4px">'
                                                        '<span style="width:6px;height:6px;border-radius:50%;background:#22c55e"></span>done</span>'
                                                        '<span style="display:inline-flex;align-items:center;gap:4px">'
                                                        '<span style="width:6px;height:6px;border-radius:50%;background:#ef4444"></span>failed</span>'
                                                        '</div>'
                                                    )
                                                ui.html(_build_dot_trail_svg(recent_for_spark))
                                                ui.label("oldest ← → newest").classes("text-[9px]").style(
                                                    "color: var(--text-muted); letter-spacing: 0.04em"
                                                )

                            # ========= INPUTS =========
                            with ui.tab_panel(tab_inputs):
                                ui.label("Input files feed into each run. Drop files here or manage the folder directly.").classes("text-xs text-gray-500 dark:text-gray-400 mb-2")

                                file_count_label = [None]

                                def _refresh_inputs_panel(c=cw, lbl_ref=file_count_label):
                                    idir = get_coworker_dir(c["name"]) / "inputs"
                                    n = len(list(idir.iterdir())) if idir.exists() else 0
                                    if lbl_ref[0]:
                                        lbl_ref[0].text = f"{n} input file{'s' if n != 1 else ''}"

                                async def handle_drop_upload(e, c=cw):
                                    content = await e.content.read()
                                    dst = get_coworker_dir(c["name"]) / "inputs" / e.name
                                    dst.parent.mkdir(parents=True, exist_ok=True)
                                    dst.write_bytes(content)
                                    _refresh_inputs_panel()
                                    _refresh_file_list()
                                    ui.notify(f"Added {e.name}", type="positive", icon="upload_file")

                                ui.upload(
                                    label="Drop input files here",
                                    on_upload=handle_drop_upload,
                                    multiple=True,
                                    auto_upload=True,
                                ).classes("w-full upload-drop-zone").props("flat bordered color=grey-4").style(
                                    "min-height: 72px; "
                                    "border: 2px dashed #cbd5e1; border-radius: 12px; "
                                    "background: #f8fafc;"
                                )

                                file_count_label[0] = ui.label("").classes("text-xs text-gray-500 dark:text-gray-400 mt-2")

                                # File list
                                file_list_container = ui.column().classes("w-full gap-1 mt-2")

                                def _refresh_file_list(c=cw, cont=file_list_container):
                                    cont.clear()
                                    idir = get_coworker_dir(c["name"]) / "inputs"
                                    files = sorted(idir.iterdir()) if idir.exists() else []
                                    if not files:
                                        with cont:
                                            ui.label("No input files").classes("text-xs text-gray-400 italic")
                                        return
                                    with cont:
                                        for f in files:
                                            if not f.is_file():
                                                continue
                                            size_kb = f.stat().st_size / 1024
                                            def del_file(path=f):
                                                path.unlink(missing_ok=True)
                                                _refresh_file_list()
                                                _refresh_inputs_panel()
                                                ui.notify(f"Deleted {path.name}", type="info")
                                            with ui.row().classes("w-full items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-800"):
                                                ui.icon("description", size="14px").classes("text-gray-400")
                                                ui.label(f.name).classes("text-xs font-mono flex-1 truncate")
                                                ui.label(f"{size_kb:.1f} KB").classes("text-[10px] text-gray-400")
                                                ui.button(icon="close", on_click=del_file).props("flat round dense size=xs color=grey-5").tooltip("Delete")

                                _refresh_inputs_panel()
                                _refresh_file_list()

                            # ========= PROCESSING =========
                            with ui.tab_panel(tab_processing):
                                ui.label("How this CoWorker processes inputs").classes("text-xs text-gray-500 dark:text-gray-400 mb-2")

                                # Model card
                                with ui.card().classes("w-full p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border-0"):
                                    with ui.row().classes("items-center gap-3"):
                                        ui.icon("smart_toy", size="24px").classes("text-blue-500")
                                        with ui.column().classes("gap-0"):
                                            ui.label("AI Model").classes("text-[10px] uppercase text-gray-400 tracking-wider")
                                            ui.label(f"{cw['model_provider']}: {cw['model_name']}").classes("text-sm font-semibold")

                                # Prompt preview
                                with ui.card().classes("w-full p-3 rounded-lg border-0"):
                                    with ui.row().classes("items-center justify-between"):
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("description", size="18px").classes("text-gray-500")
                                            ui.label("Prompt").classes("text-sm font-semibold")
                                        def open_prompt(c=cw):
                                            _show_prompt_dialog(c)
                                        ui.button("Edit", icon="edit", on_click=open_prompt).props("flat dense size=xs color=primary")
                                    prompt_text = get_prompt(cw["name"]) or "(no prompt configured)"
                                    ui.label(prompt_text[:300] + ("..." if len(prompt_text) > 300 else "")).classes(
                                        "text-xs text-gray-600 dark:text-gray-300 mt-2 whitespace-pre-wrap font-mono"
                                    )

                                # Skill / pipeline info
                                if cw_manifest:
                                    with ui.card().classes("w-full p-3 rounded-lg border-0"):
                                        with ui.row().classes("items-center justify-between"):
                                            with ui.row().classes("items-center gap-2"):
                                                ui.icon("account_tree", size="18px").classes("text-purple-500")
                                                ui.label(f"Skill: {cw_manifest['name']}").classes("text-sm font-semibold")
                                                source = cw_manifest.get("_source", "")
                                                if source == "claude-skill":
                                                    ui.badge("EKAI Skill", color="deep-purple").props("outline").classes("text-[9px]")
                                                elif source == "SKILL.md":
                                                    ui.badge("AI-only", color="blue").props("outline").classes("text-[9px]")
                                                else:
                                                    ui.badge("Pipeline", color="purple").props("outline").classes("text-[9px]")
                                            def open_viz(c=cw):
                                                _show_visualise_dialog(c)
                                            ui.button("Visualise", icon="schema", on_click=open_viz).props("flat dense size=xs color=purple")
                                        if cw_manifest.get("description"):
                                            ui.label(cw_manifest["description"][:200] + ("..." if len(cw_manifest["description"]) > 200 else "")).classes("text-xs text-gray-500 dark:text-gray-400 mt-2")
                                        pipeline = cw_manifest.get("pipeline", [])
                                        if pipeline:
                                            ui.label(f"{len(pipeline)} pipeline step{'s' if len(pipeline) != 1 else ''}").classes("text-[10px] text-gray-400 mt-2 uppercase tracking-wider")
                                            with ui.row().classes("items-center gap-2 mt-1 flex-wrap"):
                                                for i, step in enumerate(pipeline):
                                                    ui.html(
                                                        f'<span class="pipeline-step">'
                                                        f'<span class="pipeline-step__icon">⚡</span>'
                                                        f'<span class="pipeline-step__name">{step.get("step", f"step_{i}")}</span>'
                                                        f'</span>'
                                                    )
                                                    if i < len(pipeline) - 1:
                                                        ui.icon("arrow_forward", size="14px").style(
                                                            "color: var(--text-muted)"
                                                        )
                                else:
                                    with ui.card().classes("w-full p-3 rounded-lg border-0 border-dashed"):
                                        with ui.row().classes("items-center gap-2"):
                                            ui.icon("info", size="18px").classes("text-gray-400")
                                            ui.label("No skill bundle installed — AI processes inputs using only the prompt.").classes("text-xs text-gray-500")

                            # ========= OUTPUTS =========
                            with ui.tab_panel(tab_outputs):
                                ui.label("Results from the most recent run are delivered here").classes("text-xs text-gray-500 dark:text-gray-400 mb-2")
                                with ui.row().classes("items-center gap-2 mb-2"):
                                    ui.icon("folder_open", size="14px").classes("text-gray-400")
                                    ui.label(f"coworkers/{get_coworker_dir(cw['name']).name}/outputs/").classes("text-xs text-gray-500 font-mono")

                                # Inline report container (same one used by Runs tab refresh)
                                outputs_list_container = ui.column().classes("w-full gap-1 mt-2")

                                def _refresh_outputs_list(c=cw, cont=outputs_list_container):
                                    cont.clear()
                                    odir = get_coworker_dir(c["name"]) / "outputs"
                                    files = sorted(odir.iterdir()) if odir.exists() else []
                                    if not files:
                                        with cont:
                                            ui.label("No outputs yet — trigger a Run to produce results.").classes("text-xs text-gray-400 italic")
                                        return
                                    with cont:
                                        for f in files:
                                            if not f.is_file():
                                                continue
                                            size_kb = f.stat().st_size / 1024
                                            icon_name = "picture_as_pdf" if f.suffix == ".pdf" else (
                                                "code" if f.suffix in (".json", ".py") else "description"
                                            )
                                            icon_color = "text-purple-500" if f.suffix == ".pdf" else (
                                                "text-amber-500" if f.suffix == ".json" else "text-emerald-500"
                                            )
                                            def view_file(path=f):
                                                if path.suffix == ".pdf":
                                                    _show_pdf_dialog(path)
                                                elif path.suffix == ".md":
                                                    _show_report_dialog(path)
                                                else:
                                                    # JSON / other — show as markdown codeblock
                                                    content = path.read_text(errors="replace")
                                                    with ui.dialog() as d, ui.card().classes("w-[800px] max-h-[80vh]"):
                                                        with ui.row().classes("w-full justify-between items-center mb-2"):
                                                            ui.label(path.name).classes("text-lg font-bold")
                                                            ui.button(icon="close", on_click=d.close).props("flat round dense")
                                                        with ui.scroll_area().classes("w-full").style("max-height: 70vh"):
                                                            ui.markdown(f"```\n{content}\n```")
                                                    d.open()
                                            with ui.row().classes("w-full items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer").on("click", view_file):
                                                ui.icon(icon_name, size="16px").classes(icon_color)
                                                ui.label(f.name).classes("text-xs font-mono flex-1 truncate")
                                                ui.label(f"{size_kb:.1f} KB").classes("text-[10px] text-gray-400")
                                                ui.icon("open_in_new", size="12px").classes("text-gray-400")

                                cw_ui["outputs_list"] = outputs_list_container
                                cw_ui["refresh_outputs"] = _refresh_outputs_list
                                _refresh_outputs_list()

                            # ========= RUNS =========
                            with ui.tab_panel(tab_runs):
                                btn_ref = [None]
                                cancel_ref = [None]

                                def do_cancel(hdr=None):
                                    rid = poll_timer_holder.get("run_id")
                                    if rid and request_cancel_run(rid):
                                        ui.notify("Cancellation requested", type="info")

                                with ui.row().classes("w-full items-center gap-2 mb-2"):
                                    run_btn = ui.button("Run Now", icon="play_arrow").props("color=green dense")
                                    btn_ref[0] = run_btn
                                    if cw["status"] == "suspended":
                                        run_btn.props("disable")
                                        run_btn.tooltip("This CoWorker is suspended — activate it to enable runs")
                                    cancel_btn = ui.button("Cancel", icon="stop_circle", on_click=do_cancel).props("color=red outline dense")
                                    cancel_btn.visible = False
                                    cancel_ref[0] = cancel_btn
                                    if cw["status"] == "suspended":
                                        with ui.row().classes("items-center gap-1"):
                                            ui.icon("info", size="14px").style("color: #ef4444")
                                            ui.label("Suspended — runs are disabled").classes("text-xs").style(
                                                "color: var(--text-muted)"
                                            )

                                # Progress + timeline (created inside the Runs tab)
                                rp_container = ui.column().classes("w-full gap-1")
                                rp_container.visible = False
                                with rp_container:
                                    with ui.row().classes("w-full items-center gap-2"):
                                        ui.spinner("dots", size="sm").classes("text-blue-600")
                                        run_status_lbl = ui.label("").classes("text-sm")
                                    timeline_holder_el = ui.html("").classes("w-full")

                                run_result_lbl = ui.label("").classes("text-sm")
                                run_result_lbl.visible = False

                                report_cont = ui.column().classes("w-full gap-1")

                                # Save refs for poll function
                                cw_ui["progress"] = rp_container
                                cw_ui["status"] = run_status_lbl
                                cw_ui["result"] = run_result_lbl
                                cw_ui["timeline"] = timeline_holder_el
                                cw_ui["report"] = report_cont

                                # Backward-compat local aliases
                                run_progress = rp_container
                                run_status = run_status_lbl
                                run_result = run_result_lbl
                                timeline_holder = timeline_holder_el
                                report_container = report_cont

                                _refresh_reports()

                                ui.separator().classes("my-2")

                                # Recent runs list
                                ui.label("Recent runs").classes("text-[10px] uppercase text-gray-400 tracking-wider mb-1")
                                recent = get_recent_runs_for_coworker(cw["id"], limit=10)
                                if not recent:
                                    ui.label("No runs yet").classes("text-xs text-gray-400 italic")
                                else:
                                    for r in reversed(recent):
                                        rstatus = r.get("status", "completed")
                                        st_color = status_tw(rstatus)
                                        st_icon = "check_circle" if rstatus == "completed" else (
                                            "error" if rstatus == "failed" else "sync"
                                        )
                                        with ui.row().classes("w-full items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-800"):
                                            ui.icon(st_icon, size="14px").classes(st_color)
                                            ts = r.get("started_at", "")[:19].replace("T", " ")
                                            ui.label(ts).classes("text-xs font-mono text-gray-600 dark:text-gray-300 min-w-[140px]")
                                            ui.label(rstatus).classes(f"text-[10px] uppercase {st_color} min-w-[60px]")
                                            ft = r.get("files_total", 0)
                                            fp = r.get("files_processed", 0)
                                            ui.label(f"{fp}/{ft} files").classes("text-[10px] text-gray-400")
                                            ui.space()
                                            rid = r.get("id")
                                            if rid and r.get("has_report"):
                                                ui.button("Open", icon="open_in_new",
                                                          on_click=lambda rid=rid: ui.navigate.to(f"/runs/{rid}/report")
                                                ).props("flat dense size=xs color=primary")

                            # ========= CHAT =========
                            with ui.tab_panel(tab_chat):
                                with ui.column().classes("w-full items-center gap-4 py-12"):
                                    ui.icon("forum", size="56px").style(
                                        "color: var(--text-muted); opacity: 0.6"
                                    )
                                    ui.label(f"Chat with {cw['name']}").classes(
                                        "text-lg font-bold"
                                    ).style("letter-spacing: -0.01em")
                                    ui.label(
                                        f"Opens a focused chat window. {cw['name']} knows its "
                                        f"workflow, skills, runs, outputs, inputs, and team feedback."
                                    ).classes("text-sm text-center max-w-md").style(
                                        "color: var(--text-secondary)"
                                    )

                                    def _open_chat(c=cw):
                                        _show_chat_dialog(c, user_id)

                                    ui.button(
                                        "Open Chat Window", icon="forum", on_click=_open_chat,
                                    ).props("color=primary size=md")

                                    # Show a compact preview of the last few messages if any
                                    existing = _CHAT_HISTORIES.get(cw["id"], [])
                                    if existing:
                                        ui.separator().classes("mt-4 mb-2")
                                        ui.label(f"{len(existing)} message(s) in conversation").classes(
                                            "text-xs"
                                        ).style("color: var(--text-muted)")

                        # Polling timer holder (one per card)
                        poll_timer_holder = {"timer": None, "run_id": None}

                        def _poll_run_status(
                            c=cw,
                            ui_refs=cw_ui,
                            holder=poll_timer_holder,
                            btn_ref=btn_ref,
                            cancel_ref=cancel_ref,
                        ):
                            """Called every 2s to check DB run progress."""
                            rid = holder.get("run_id")
                            if not rid:
                                return
                            rec = get_run_record(rid)
                            if not rec:
                                return

                            prog = ui_refs.get("progress")
                            lbl = ui_refs.get("status")
                            res = ui_refs.get("result")
                            tl_ref = ui_refs.get("timeline")

                            if rec["status"] in ("pending", "running", "cancelling"):
                                if prog: prog.visible = True
                                msg = rec["progress_message"] or "Running..."
                                if rec["status"] == "cancelling":
                                    msg = "Cancelling..."
                                ft = rec["files_total"] or 0
                                fp = rec["files_processed"] or 0
                                if ft > 0:
                                    pct = int(fp / ft * 100)
                                    msg = f"{msg}  ({pct}%)"
                                if lbl: lbl.text = msg
                                if res: res.visible = False

                                run_dir = rec.get("run_dir", "")
                                fnames = _get_run_file_names(run_dir)
                                if tl_ref is not None:
                                    if fnames and ft > 0:
                                        current = rec.get("progress_message", "")
                                        tl_ref.content = _build_timeline_html(fnames, fp, current, rec["status"])
                                    elif ft > 0:
                                        generic_names = [f"File {i+1}" for i in range(ft)]
                                        tl_ref.content = _build_timeline_html(generic_names, fp, "", rec["status"])

                                if btn_ref[0]:
                                    btn_ref[0].props("loading disabled")
                                if cancel_ref[0]:
                                    cancel_ref[0].visible = True
                                    if rec["status"] == "cancelling":
                                        cancel_ref[0].props("loading disabled")

                            elif rec["status"] == "completed":
                                run_dir = rec.get("run_dir", "")
                                fnames = _get_run_file_names(run_dir)
                                if tl_ref is not None and fnames:
                                    tl_ref.content = _build_timeline_html(fnames, len(fnames), "", "completed")

                                if prog: prog.visible = False
                                if res:
                                    res.classes(replace="text-sm text-green-600")
                                    res.text = rec["progress_message"] or "Run completed"
                                    res.visible = True
                                _refresh_reports()
                                if ui_refs.get("refresh_outputs"):
                                    ui_refs["refresh_outputs"]()
                                if btn_ref[0]:
                                    btn_ref[0].props(remove="loading disabled")
                                if cancel_ref[0]:
                                    cancel_ref[0].visible = False
                                    cancel_ref[0].props(remove="loading disabled")
                                if holder.get("timer"):
                                    holder["timer"].deactivate()
                                    holder["timer"] = None

                            elif rec["status"] == "failed":
                                run_dir = rec.get("run_dir", "")
                                fnames = _get_run_file_names(run_dir)
                                fp = rec.get("files_processed", 0) or 0
                                if tl_ref is not None and fnames:
                                    tl_ref.content = _build_timeline_html(fnames, fp, "", "failed")

                                if prog: prog.visible = False
                                err_msg = rec.get("error") or "Run failed"
                                if res:
                                    if err_msg == "Cancelled by user":
                                        res.classes(replace="text-sm text-amber-600")
                                    else:
                                        res.classes(replace="text-sm text-red-500")
                                    res.text = err_msg
                                    res.visible = True
                                if btn_ref[0]:
                                    btn_ref[0].props(remove="loading disabled")
                                if cancel_ref[0]:
                                    cancel_ref[0].visible = False
                                    cancel_ref[0].props(remove="loading disabled")
                                if holder.get("timer"):
                                    holder["timer"].deactivate()
                                    holder["timer"] = None

                        def do_run(
                            c=cw,
                            holder=poll_timer_holder,
                            ui_refs=cw_ui,
                            btn_r=btn_ref,
                            cancel_r=cancel_ref,
                        ):
                            try:
                                from run_manager import CoWorkerSuspendedError
                                run_id = launch_run(c, user_id)
                            except CoWorkerSuspendedError as ex:
                                ui.notify(str(ex), type="negative", icon="pause_circle", timeout=3500)
                                return
                            if run_id is None:
                                ui.notify("A run is already in progress for this CoWorker", type="warning")
                                return
                            holder["run_id"] = run_id
                            if ui_refs.get("progress"):
                                ui_refs["progress"].visible = True
                            if ui_refs.get("status"):
                                ui_refs["status"].text = "Starting run..."
                            if ui_refs.get("result"):
                                ui_refs["result"].visible = False
                            if btn_r[0]:
                                btn_r[0].props("loading disabled")
                            if cancel_r[0]:
                                cancel_r[0].visible = True
                            holder["timer"] = ui.timer(2.0, _poll_run_status)

                        # Wire the Run button defined inside the Runs tab
                        if btn_ref[0]:
                            btn_ref[0].on("click", do_run)

                        # Resume polling if a run is already in progress
                        active_run = get_active_run_for_coworker(cw["id"])
                        if active_run:
                            poll_timer_holder["run_id"] = active_run["id"]
                            if cw_ui.get("progress"):
                                cw_ui["progress"].visible = True
                            if cw_ui.get("status"):
                                cw_ui["status"].text = active_run.get("progress_message", "Running...")
                            if btn_ref[0]:
                                btn_ref[0].props("loading disabled")
                            if cancel_ref[0]:
                                cancel_ref[0].visible = True
                                if active_run.get("status") == "cancelling":
                                    cancel_ref[0].props("loading disabled")
                            poll_timer_holder["timer"] = ui.timer(2.0, _poll_run_status)

                        # --- Footer: quick action icon buttons ---
                        ui.separator().classes("my-1")
                        with ui.row().classes("w-full justify-end items-center gap-1"):
                            def make_visualise(c=cw):
                                _show_visualise_dialog(c)

                            def make_config(c=cw):
                                _show_prompt_dialog(c)

                            def make_edit(c=cw):
                                def on_save(name, job_description, workflow, status, model_provider, model_name):
                                    update_coworker(c["id"], name, job_description, workflow, status, model_provider, model_name)
                                    refresh_cards()
                                _show_coworker_dialog(on_save, coworker=c, user_id=user_id)

                            def make_delete(c=cw):
                                _show_delete_coworker_dialog(c, on_done=refresh_cards)

                            def make_clone(c=cw):
                                _show_clone_dialog(c, user_id, refresh_cards)

                            ui.button(icon="schema", on_click=make_visualise).props("flat dense round size=sm color=purple").tooltip("Visualise Pipeline")
                            ui.button(icon="settings", on_click=make_config).props("flat dense round size=sm color=blue").tooltip("Configure Prompt & Skills")
                            ui.button(icon="content_copy", on_click=make_clone).props("flat dense round size=sm color=teal").tooltip("Clone CoWorker")
                            ui.button(icon="edit", on_click=make_edit).props("flat dense round size=sm").tooltip("Edit")
                            ui.button(icon="delete", on_click=make_delete).props("flat dense round size=sm color=red").tooltip("Delete")

    from pages.layout import build_layout
    content = build_layout(user=user, active="coworkers")

    with content:
        ui.add_head_html("""<style>
            /* Drop zone */
            .upload-drop-zone .q-uploader__header { background: transparent !important; color: #94a3b8 !important; }
            .upload-drop-zone:hover { border-color: #3b82f6 !important; background: rgba(59,130,246,0.06) !important; }
            .upload-drop-zone:hover .q-uploader__header { color: #3b82f6 !important; }
            .upload-drop-zone .q-uploader__list { display: none; }

            /* CoWorker card base */
            .cw-card {
              background: var(--bg-surface);
              border: 1px solid var(--border-subtle);
            }
            .cw-card:hover { border-color: rgba(59,130,246,0.35); }

            /* 2-column grid; expanded cards span the full row */
            .cw-grid {
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 16px;
            }
            .cw-grid > .q-expansion-item--expanded { grid-column: 1 / -1; }
            @media (max-width: 900px) { .cw-grid { grid-template-columns: 1fr; } }

            /* Rounded buttons overall */
            .q-btn { border-radius: 10px; }
            .q-btn--round { border-radius: 9999px; }

            /* Hide the default expansion arrow (we render our own chevron) */
            .cw-card .q-expansion-item__toggle-icon { display: none; }

            /* Pipeline step chips — readable in both light & dark mode */
            .pipeline-step {
              display: inline-flex; align-items: center; gap: 6px;
              padding: 4px 10px;
              border-radius: 8px;
              font-family: var(--font-mono);
              font-size: 11px;
              font-weight: 500;
              background: rgba(99,102,241,0.10);
              border: 1px solid rgba(99,102,241,0.28);
              color: #4f46e5;           /* indigo-600 for light mode */
              letter-spacing: 0;
            }
            body.body--dark .pipeline-step {
              background: rgba(129,140,248,0.16);   /* indigo-400/16% */
              border-color: rgba(129,140,248,0.38);
              color: #c7d2fe;                        /* indigo-200 — high contrast on dark */
            }
            .pipeline-step__icon {
              font-size: 10px; opacity: 0.85;
            }
            .pipeline-step__name { font-weight: 500 }

            /* Quick-action buttons inside the card header */
            .cw-action-btn {
              border-radius: 8px !important;
              font-size: 12px !important;
              padding: 4px 10px !important;
              min-height: 28px !important;
              letter-spacing: 0 !important;
            }
            .cw-action-btn .q-btn__content { gap: 4px }
            .cw-action-btn .q-icon { font-size: 14px !important }
            /* Stop header-click propagation so action buttons don't toggle expansion */
            .cw-action-btn { position: relative; z-index: 2 }
        </style>
        <script>
        // Prevent action-button clicks from toggling the expansion.
        // Use bubble phase so the button's own click handler still fires first.
        document.addEventListener('click', function(e) {
          const btn = e.target.closest('.cw-action-btn');
          if (btn) { e.stopPropagation(); }
        }, false);
        </script>
        """)

        with ui.row().classes("w-full items-center justify-between mb-6"):
            with ui.column().classes("gap-0"):
                ui.label("Team").classes("text-xs").style("color: var(--text-muted); letter-spacing: 0.02em")
                ui.label("CoWorkers").classes("text-2xl font-bold").style("letter-spacing: -0.02em")

            def add_coworker():
                def on_save(name, job_description, workflow, status, model_provider, model_name):
                    create_coworker(name, job_description, workflow, status, model_provider, model_name, user_id)
                    refresh_cards()
                _show_coworker_dialog(on_save, user_id=user_id)

            ui.button("Add CoWorker", icon="add", on_click=add_coworker).props("color=primary")

        cards_container = ui.element("div").classes("w-full cw-grid")
        refresh_cards()
