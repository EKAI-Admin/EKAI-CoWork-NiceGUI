"""Departments management page — CRUD for department metadata."""

from nicegui import ui

from auth import get_current_user, logout
from db import (
    get_departments, create_department, update_department, delete_department,
    get_user_by_username,
)


# Palette that plays nicely with our design tokens in both light & dark mode.
DEPT_COLOR_SWATCHES = [
    ("blue",    "#3b82f6"),
    ("teal",    "#14b8a6"),
    ("purple",  "#8b5cf6"),
    ("orange",  "#f97316"),
    ("indigo",  "#6366f1"),
    ("green",   "#22c55e"),
    ("pink",    "#ec4899"),
    ("red",     "#ef4444"),
    ("cyan",    "#06b6d4"),
    ("amber",   "#f59e0b"),
]

DEPT_COLOR_HEX = dict(DEPT_COLOR_SWATCHES)


# Curated set of Material Icons that make sense for departments.
DEPT_ICON_PALETTE = [
    "work", "group", "hub", "campaign",
    "code", "bug_report", "science", "terminal",
    "menu_book", "description", "receipt_long", "forum",
    "rocket_launch", "build", "handyman", "construction",
    "analytics", "insights", "query_stats", "trending_up",
    "support_agent", "headset_mic", "contact_support", "record_voice_over",
    "draw", "brush", "design_services", "palette",
    "security", "shield", "lock", "vpn_key",
    "speed", "monitor_heart", "dns", "memory",
    "school", "psychology", "auto_awesome", "spa",
    "translate", "travel_explore", "language", "public",
    "inventory", "local_shipping", "store", "shopping_cart",
    "payments", "savings", "currency_exchange", "point_of_sale",
]


def departments_page():
    user = get_current_user()
    if not user:
        ui.navigate.to("/login")
        return

    db_user = get_user_by_username(user["username"])
    if not db_user:
        logout()
        ui.navigate.to("/login")
        return

    from pages.layout import build_layout
    content = build_layout(user=user, active="departments")

    with content:
        ui.add_head_html("""<style>
          .dept-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
          @media (max-width: 1100px) { .dept-grid { grid-template-columns: repeat(2, 1fr) } }
          @media (max-width: 700px)  { .dept-grid { grid-template-columns: 1fr } }

          .dept-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 16px;
            padding: 18px;
            transition: border-color .15s ease, transform .15s ease;
          }
          .dept-card:hover { border-color: rgba(59,130,246,.35); }

          .icon-tile {
            display: inline-flex; align-items: center; justify-content: center;
            width: 44px; height: 44px; border-radius: 12px;
          }

          /* Icon palette grid used by the picker dialog */
          .icon-palette {
            display: grid; grid-template-columns: repeat(8, 1fr); gap: 6px;
            max-height: 220px; overflow-y: auto;
          }
          .icon-palette__cell {
            display: inline-flex; align-items: center; justify-content: center;
            width: 100%; aspect-ratio: 1; border-radius: 8px;
            cursor: pointer; border: 1px solid var(--border-subtle);
            transition: all .12s ease;
          }
          .icon-palette__cell:hover { background: var(--bg-surface-muted); }
          .icon-palette__cell.selected {
            background: rgba(59,130,246,.15); border-color: #3b82f6;
          }

          /* Color swatch picker */
          .color-palette { display: flex; flex-wrap: wrap; gap: 8px; }
          .color-palette__dot {
            width: 32px; height: 32px; border-radius: 10px;
            cursor: pointer; position: relative;
            border: 2px solid transparent;
            transition: transform .1s ease;
          }
          .color-palette__dot:hover { transform: scale(1.08); }
          .color-palette__dot.selected {
            border-color: var(--text-primary);
            box-shadow: 0 0 0 2px var(--bg-page), 0 0 0 4px var(--text-primary);
          }
        </style>""")

        # Header
        with ui.row().classes("w-full items-center justify-between mb-6"):
            with ui.column().classes("gap-0"):
                ui.label("Organisation").classes("text-xs").style(
                    "color: var(--text-muted); letter-spacing: 0.02em"
                )
                ui.label("Departments").classes("text-2xl font-bold").style(
                    "letter-spacing: -0.02em"
                )

            def add_dept():
                _show_dept_dialog(on_done=refresh)

            ui.button("Add Department", icon="add", on_click=add_dept).props("color=primary")

        grid_container = ui.element("div").classes("w-full dept-grid")

        def refresh():
            grid_container.clear()
            depts = get_departments()
            with grid_container:
                if not depts:
                    with ui.column().classes("w-full col-span-full items-center py-16"):
                        ui.icon("domain_disabled", size="56px").style("color: var(--text-muted)")
                        ui.label("No departments").classes("text-lg mt-3").style(
                            "color: var(--text-secondary)"
                        )
                    return

                for d in depts:
                    _render_dept_card(d, on_refresh=refresh, all_depts=depts)

        refresh()


def _render_dept_card(dept: dict, on_refresh, all_depts: list[dict]):
    """One department card in the grid."""
    color_hex = DEPT_COLOR_HEX.get(dept.get("color") or "blue", "#3b82f6")
    members = dept.get("member_count", 0) or 0

    with ui.element("div").classes("dept-card").style(
        f"border-left: 4px solid {color_hex}"
    ):
        # Top: icon + name
        with ui.row().classes("w-full items-start gap-3"):
            with ui.element("div").classes("icon-tile").style(
                f"background: {color_hex}22"
            ):
                ui.icon(dept.get("icon") or "work", size="22px").style(f"color: {color_hex}")
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                ui.label(dept["name"]).classes("font-bold truncate").style(
                    "font-size: 16px; letter-spacing: -0.01em; color: var(--text-primary)"
                )
                # Description or placeholder
                desc = (dept.get("description") or "").strip() or "No description"
                ui.label(desc).classes("truncate").style(
                    "font-size: 12px; color: var(--text-muted); margin-top: 2px"
                )

        # Stats row
        with ui.row().classes("w-full items-center mt-4").style("gap: 16px"):
            with ui.column().classes("gap-0"):
                ui.label("Members").classes("metric-label").style("font-size: 10px")
                ui.label(str(members)).classes("mono font-bold tnum").style(
                    "font-size: 18px; color: var(--text-primary); margin-top: 2px"
                )
            ui.space()
            # Actions
            def _edit(d=dept):
                _show_dept_dialog(dept=d, on_done=on_refresh)

            def _delete(d=dept):
                _show_delete_dialog(d, all_depts, on_done=on_refresh)

            ui.button(icon="edit", on_click=_edit).props(
                "flat dense round size=sm"
            ).tooltip("Edit")
            ui.button(icon="delete", on_click=_delete).props(
                "flat dense round size=sm color=red"
            ).tooltip("Delete")


def _show_dept_dialog(dept: dict | None = None, on_done=None):
    """Add / edit department dialog with icon + color picker."""
    is_edit = dept is not None
    title = f"Edit {dept['name']}" if is_edit else "Add Department"

    # State refs (we render swatches as HTML so we track selection client-side via a
    # classList toggle; Python side uses a mutable dict so submit can read current values).
    selected = {
        "icon":  dept.get("icon") if dept else "work",
        "color": dept.get("color") if dept else "blue",
    }

    with ui.dialog() as dialog, ui.card().classes("w-[560px] p-6 rounded-2xl"):
        ui.label(title).classes("text-xl font-bold mb-1").style("letter-spacing: -0.01em")
        ui.label(
            "Departments group CoWorkers on the dashboard and give each card its accent border."
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        name_input = ui.input(
            "Department name",
            value=dept["name"] if is_edit else "",
        ).classes("w-full mb-3").props("outlined autofocus")

        desc_input = ui.textarea(
            "Description (optional)",
            value=dept.get("description", "") if is_edit else "",
        ).classes("w-full mb-3").props("outlined autogrow")

        # Color picker
        ui.label("Accent color").classes("metric-label mt-2").style("font-size: 10px")
        color_row = ui.element("div").classes("color-palette mt-1 mb-4")
        with color_row:
            for color_name, color_hex in DEPT_COLOR_SWATCHES:
                sel = " selected" if selected["color"] == color_name else ""
                ui.html(
                    f'<div class="color-palette__dot{sel}" '
                    f'data-color="{color_name}" '
                    f'style="background: {color_hex}"></div>'
                )

        # Icon picker
        ui.label("Icon").classes("metric-label").style("font-size: 10px")
        ui.html(f'''<div class="icon-palette mt-1" id="dept-icon-palette">{
            "".join(
                f'<div class="icon-palette__cell{" selected" if selected["icon"] == ic else ""}" '
                f'data-icon="{ic}" title="{ic}">'
                f'<i class="material-icons" style="font-size:18px;color:var(--text-secondary)">{ic}</i>'
                f'</div>'
                for ic in DEPT_ICON_PALETTE
            )
        }</div>''')

        # JS: wire selection + sync to Python via a hidden input
        hidden_icon = ui.input().classes("hidden").props("value=''")
        hidden_color = ui.input().classes("hidden").props("value=''")
        hidden_icon.value = selected["icon"]
        hidden_color.value = selected["color"]

        ui.run_javascript(f"""
          (function() {{
            const dialog = document.querySelector('.q-dialog:not(.q-dialog--hidden) .q-card');
            if (!dialog) return;
            // Color picker
            dialog.querySelectorAll('.color-palette__dot').forEach(el => {{
              el.addEventListener('click', () => {{
                dialog.querySelectorAll('.color-palette__dot').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                const hidden = [...document.querySelectorAll('input')].find(i => i.id === '{hidden_color.id}' || i.value === '{hidden_color.value}');
                if (hidden) {{ hidden.value = el.dataset.color; hidden.dispatchEvent(new Event('input')); }}
                // Also set via setter for NiceGUI binding
                const nicehidden = dialog.querySelector('[data-testid="hidden-color"]') || null;
              }});
            }});
            // Icon picker
            dialog.querySelectorAll('.icon-palette__cell').forEach(el => {{
              el.addEventListener('click', () => {{
                dialog.querySelectorAll('.icon-palette__cell').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                const hidden = [...document.querySelectorAll('input')].find(i => i.id === '{hidden_icon.id}');
                if (hidden) {{ hidden.value = el.dataset.icon; hidden.dispatchEvent(new Event('input')); }}
              }});
            }});
          }})();
        """)

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                name = (name_input.value or "").strip()
                if not name:
                    error_label.text = "Name is required."
                    error_label.visible = True
                    return

                # Pull current selection via JS evaluation (the hidden inputs may not
                # round-trip through NiceGUI's client→server bridge in all setups).
                icon = selected["icon"]
                color = selected["color"]

                # If hidden inputs got updated, use those
                if hidden_icon.value:
                    icon = hidden_icon.value
                if hidden_color.value:
                    color = hidden_color.value

                try:
                    if is_edit:
                        update_department(dept["id"], name, icon, color, desc_input.value or "")
                        ui.notify(f"Updated {name}", type="positive", icon="check", timeout=2000)
                    else:
                        create_department(name, icon, color, desc_input.value or "")
                        ui.notify(f"Created {name}", type="positive", icon="add", timeout=2000)
                    dialog.close()
                    if on_done:
                        on_done()
                except Exception as e:
                    error_label.text = str(e)
                    error_label.visible = True

            btn_label = "Save changes" if is_edit else "Create department"
            ui.button(btn_label, icon="check", on_click=submit).props("color=primary")

    dialog.open()


def _show_delete_dialog(dept: dict, all_depts: list[dict], on_done=None):
    """Delete confirmation with optional reassignment."""
    member_count = dept.get("member_count", 0) or 0
    other_depts = [d for d in all_depts if d["id"] != dept["id"]]

    with ui.dialog() as dialog, ui.card().classes("w-[480px] p-6 rounded-2xl"):
        with ui.row().classes("items-center gap-3 mb-2"):
            with ui.element("div").classes("rounded-xl p-2").style(
                "background: rgba(239,68,68,0.14)"
            ):
                ui.icon("delete", size="20px").style("color: #ef4444")
            ui.label(f"Delete {dept['name']}?").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )

        if member_count > 0:
            ui.label(
                f'This department has {member_count} CoWorker(s). Choose a department '
                f'to reassign them to before deleting.'
            ).classes("text-sm mb-3").style("color: var(--text-secondary)")

            options = [d["name"] for d in other_depts]
            if not options:
                ui.label("⚠ No other departments exist to reassign to. Create one first.").classes(
                    "text-sm text-red-500 mb-3"
                )
                reassign_select = None
            else:
                reassign_select = ui.select(
                    options, label="Reassign CoWorkers to", value=options[0],
                ).classes("w-full mb-3").props("outlined")
        else:
            ui.label(
                "This department has no CoWorkers. Safe to delete."
            ).classes("text-sm mb-3").style("color: var(--text-secondary)")
            reassign_select = None

        error_label = ui.label("").classes("text-red-500 text-sm mt-1")
        error_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def submit():
                try:
                    reassign = reassign_select.value if reassign_select else None
                    if member_count > 0 and not reassign:
                        error_label.text = "Create another department first so we can reassign."
                        error_label.visible = True
                        return
                    delete_department(dept["id"], reassign_to_name=reassign)
                    ui.notify(f"Deleted {dept['name']}", type="info", icon="delete", timeout=2000)
                    dialog.close()
                    if on_done:
                        on_done()
                except Exception as e:
                    error_label.text = str(e)
                    error_label.visible = True

            disabled = member_count > 0 and not other_depts
            btn = ui.button("Delete", icon="delete", on_click=submit).props("color=red")
            if disabled:
                btn.props("disable")

    dialog.open()
