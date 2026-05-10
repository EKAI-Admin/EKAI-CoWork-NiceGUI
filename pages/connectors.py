"""Connectors page — manage MCP connections to SaaS platforms.

Today this is a static catalog of placeholder integrations. The connect/disconnect
buttons open placeholder modals; when real MCP plumbing is in place, wire them
to the actual MCP server registration + OAuth flow.
"""

from nicegui import ui

from auth import get_current_user, logout
from db import get_user_by_username


# Categories shown as filter pills at the top
CATEGORIES = [
    "All",
    "Communication",
    "Project Mgmt",
    "Code & CI",
    "CRM",
    "Storage",
    "Analytics",
    "Finance",
    "Calendar",
    "AI & Data",
]


# Placeholder MCP connector catalogue.
#   status: "connected" | "available" | "beta" | "coming_soon"
#   auth:   "oauth" | "api_key" | "mcp_url" | "none"
CONNECTORS: list[dict] = [
    # Communication
    {
        "id": "gmail", "name": "Gmail", "short": "GM",
        "category": "Communication",
        "color": "#ea4335", "icon": "mail",
        "description": "Read, search, and draft emails. Summarise threads and auto-triage inboxes.",
        "status": "connected", "auth": "oauth",
        "connected_as": "pvm@studio.co",
    },
    {
        "id": "slack", "name": "Slack", "short": "SL",
        "category": "Communication",
        "color": "#611f69", "icon": "chat",
        "description": "Read channels, post messages, summarise threads, and trigger workflows.",
        "status": "connected", "auth": "oauth",
        "connected_as": "acme-corp",
    },
    {
        "id": "ms-teams", "name": "Microsoft Teams", "short": "MT",
        "category": "Communication",
        "color": "#464eb8", "icon": "groups",
        "description": "Access meetings, channels, and chats in Microsoft 365.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "outlook", "name": "Outlook", "short": "OL",
        "category": "Communication",
        "color": "#0078d4", "icon": "mail",
        "description": "Email + calendar integration for Microsoft 365 users.",
        "status": "available", "auth": "oauth",
    },

    # Project Management
    {
        "id": "jira", "name": "Jira", "short": "JR",
        "category": "Project Mgmt",
        "color": "#0052cc", "icon": "bug_report",
        "description": "Create/update issues, query sprints, automate tickets from AI analysis.",
        "status": "connected", "auth": "oauth",
        "connected_as": "acme.atlassian.net",
    },
    {
        "id": "linear", "name": "Linear", "short": "LN",
        "category": "Project Mgmt",
        "color": "#5e6ad2", "icon": "track_changes",
        "description": "Modern issue tracking — read/write issues, cycles, and projects.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "notion", "name": "Notion", "short": "NT",
        "category": "Project Mgmt",
        "color": "#000000", "icon": "menu_book",
        "description": "Query databases, create pages, and keep docs in sync.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "asana", "name": "Asana", "short": "AS",
        "category": "Project Mgmt",
        "color": "#f06a6a", "icon": "task_alt",
        "description": "Task and project management — read/write across workspaces.",
        "status": "beta", "auth": "oauth",
    },
    {
        "id": "trello", "name": "Trello", "short": "TR",
        "category": "Project Mgmt",
        "color": "#0079bf", "icon": "view_kanban",
        "description": "Board-based task management. Sync cards with CoWorker outputs.",
        "status": "coming_soon", "auth": "oauth",
    },

    # Code & CI
    {
        "id": "github", "name": "GitHub", "short": "GH",
        "category": "Code & CI",
        "color": "#24292e", "icon": "code",
        "description": "Browse repos, review PRs, read issues, trigger actions.",
        "status": "connected", "auth": "oauth",
        "connected_as": "acme-corp (Org)",
    },
    {
        "id": "gitlab", "name": "GitLab", "short": "GL",
        "category": "Code & CI",
        "color": "#fc6d26", "icon": "code",
        "description": "Self-hosted or SaaS GitLab — MRs, pipelines, and issues.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "bitbucket", "name": "Bitbucket", "short": "BB",
        "category": "Code & CI",
        "color": "#2684ff", "icon": "account_tree",
        "description": "Atlassian's Git hosting — read repos, PRs, and pipelines.",
        "status": "available", "auth": "oauth",
    },

    # CRM
    {
        "id": "salesforce", "name": "Salesforce", "short": "SF",
        "category": "CRM",
        "color": "#00a1e0", "icon": "cloud",
        "description": "Query leads, accounts, opportunities, and run reports.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "hubspot", "name": "HubSpot", "short": "HS",
        "category": "CRM",
        "color": "#ff7a59", "icon": "contact_mail",
        "description": "Contacts, companies, deals — full CRM read/write.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "intercom", "name": "Intercom", "short": "IC",
        "category": "CRM",
        "color": "#1f8ded", "icon": "support_agent",
        "description": "Customer conversations, help center articles, and user data.",
        "status": "beta", "auth": "api_key",
    },
    {
        "id": "zendesk", "name": "Zendesk", "short": "ZD",
        "category": "CRM",
        "color": "#03363d", "icon": "headset_mic",
        "description": "Customer support tickets, SLAs, and agent workflows.",
        "status": "available", "auth": "api_key",
    },

    # Storage
    {
        "id": "gdrive", "name": "Google Drive", "short": "GD",
        "category": "Storage",
        "color": "#1f8e3e", "icon": "folder_shared",
        "description": "Read, create, and search files and folders in Drive.",
        "status": "connected", "auth": "oauth",
        "connected_as": "pvm@studio.co",
    },
    {
        "id": "dropbox", "name": "Dropbox", "short": "DB",
        "category": "Storage",
        "color": "#0061ff", "icon": "folder",
        "description": "Cloud storage with file sync and sharing.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "onedrive", "name": "OneDrive", "short": "OD",
        "category": "Storage",
        "color": "#0078d4", "icon": "cloud_circle",
        "description": "Microsoft 365 cloud storage for docs and attachments.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "s3", "name": "Amazon S3", "short": "S3",
        "category": "Storage",
        "color": "#ff9900", "icon": "storage",
        "description": "Object storage — list, read, and upload to buckets.",
        "status": "available", "auth": "api_key",
    },

    # Analytics
    {
        "id": "ga", "name": "Google Analytics", "short": "GA",
        "category": "Analytics",
        "color": "#f57c00", "icon": "analytics",
        "description": "Traffic, events, conversions — query and summarise GA4 data.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "mixpanel", "name": "Mixpanel", "short": "MP",
        "category": "Analytics",
        "color": "#7856ff", "icon": "insights",
        "description": "Product analytics — funnels, retention, cohorts.",
        "status": "coming_soon", "auth": "api_key",
    },

    # Finance
    {
        "id": "stripe", "name": "Stripe", "short": "ST",
        "category": "Finance",
        "color": "#635bff", "icon": "payments",
        "description": "Payments, subscriptions, refunds — ops & reporting.",
        "status": "available", "auth": "api_key",
    },
    {
        "id": "quickbooks", "name": "QuickBooks", "short": "QB",
        "category": "Finance",
        "color": "#2ca01c", "icon": "receipt_long",
        "description": "Accounting — invoices, bills, reports, and reconciliation.",
        "status": "coming_soon", "auth": "oauth",
    },

    # Calendar
    {
        "id": "gcal", "name": "Google Calendar", "short": "GC",
        "category": "Calendar",
        "color": "#4285f4", "icon": "event",
        "description": "Read events, schedule meetings, find free slots.",
        "status": "connected", "auth": "oauth",
        "connected_as": "pvm@studio.co",
    },
    {
        "id": "calendly", "name": "Calendly", "short": "CY",
        "category": "Calendar",
        "color": "#006bff", "icon": "schedule",
        "description": "Meeting scheduling — event types and bookings.",
        "status": "available", "auth": "oauth",
    },

    # AI & Data
    {
        "id": "bigquery", "name": "BigQuery", "short": "BQ",
        "category": "AI & Data",
        "color": "#669df6", "icon": "table_chart",
        "description": "Run SQL against your data warehouse tables and views.",
        "status": "available", "auth": "oauth",
    },
    {
        "id": "snowflake", "name": "Snowflake", "short": "SN",
        "category": "AI & Data",
        "color": "#29b5e8", "icon": "ac_unit",
        "description": "Cloud data warehouse — query and transform tables.",
        "status": "coming_soon", "auth": "api_key",
    },
    {
        "id": "confluence", "name": "Confluence", "short": "CF",
        "category": "AI & Data",
        "color": "#2684ff", "icon": "auto_stories",
        "description": "Atlassian wiki — read spaces and pages for context.",
        "status": "available", "auth": "oauth",
    },
]


_STATUS_META = {
    "connected":   {"label": "CONNECTED",    "pill": "pill-green"},
    "available":   {"label": "AVAILABLE",    "pill": "pill-blue"},
    "beta":        {"label": "BETA",         "pill": "pill-amber"},
    "coming_soon": {"label": "COMING SOON",  "pill": "pill-gray"},
}


def connectors_page():
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
    content = build_layout(user=user, active="connectors")

    with content:
        ui.add_head_html("""<style>
            .cx-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
            @media (max-width: 1100px) { .cx-grid { grid-template-columns: repeat(2, 1fr) } }
            @media (max-width: 700px)  { .cx-grid { grid-template-columns: 1fr } }

            .cx-card {
              background: var(--bg-surface);
              border: 1px solid var(--border-subtle);
              border-radius: 16px;
              padding: 18px;
              display: flex;
              flex-direction: column;
              gap: 12px;
              transition: transform .15s ease, border-color .15s ease;
            }
            .cx-card:hover { border-color: rgba(59,130,246,.35); transform: translateY(-1px); }

            .cx-logo {
              width: 40px; height: 40px; border-radius: 10px;
              display: inline-flex; align-items: center; justify-content: center;
              color: white; font-weight: 700; font-size: 13px;
              flex-shrink: 0; font-family: var(--font-mono);
              letter-spacing: 0.02em;
            }

            .cx-filter {
              display: inline-flex; align-items: center; gap: 4px;
              font-size: 12px; font-weight: 500;
              padding: 6px 12px; border-radius: 999px;
              border: 1px solid var(--border-subtle);
              cursor: pointer;
              background: transparent;
              color: var(--text-secondary);
              transition: all .12s ease;
            }
            .cx-filter:hover { background: var(--bg-surface-muted); }
            .cx-filter.active {
              background: var(--text-primary);
              color: var(--bg-page);
              border-color: var(--text-primary);
            }

            .cx-connected-dot {
              width: 6px; height: 6px; border-radius: 50%;
              background: #22c55e;
              display: inline-block;
              box-shadow: 0 0 0 2px rgba(34,197,94,.25);
              margin-right: 6px;
            }

            .cx-connect-btn { border-radius: 10px !important }
        </style>""")

        # --- Header ---
        with ui.row().classes("w-full items-center justify-between mb-6"):
            with ui.column().classes("gap-0"):
                ui.label("Integrations").classes("text-xs").style(
                    "color: var(--text-muted); letter-spacing: 0.02em"
                )
                ui.label("Connectors").classes("text-2xl font-bold").style(
                    "letter-spacing: -0.02em"
                )
                ui.label(
                    "Manage MCP connections to SaaS platforms. Your CoWorkers can read and write "
                    "across any connected system."
                ).classes("text-xs mt-1").style("color: var(--text-muted); max-width: 640px")

            ui.button("Add Custom MCP", icon="add", on_click=lambda: _show_add_mcp_dialog()).props(
                "color=primary"
            )

        # --- Stats row ---
        connected = sum(1 for c in CONNECTORS if c["status"] == "connected")
        available = sum(1 for c in CONNECTORS if c["status"] == "available")
        beta = sum(1 for c in CONNECTORS if c["status"] == "beta")
        coming = sum(1 for c in CONNECTORS if c["status"] == "coming_soon")

        with ui.element("div").classes("w-full grid grid-cols-4 gap-3 mb-6"):
            for label, value, accent, icon in (
                ("Connected",   str(connected), "#22c55e", "link"),
                ("Available",   str(available), "#3b82f6", "apps"),
                ("Beta",        str(beta),      "#f59e0b", "science"),
                ("Coming soon", str(coming),    "#94a3b8", "schedule"),
            ):
                with ui.card().classes("p-4 rounded-xl border-0").style(
                    "background: var(--bg-surface)"
                ):
                    with ui.row().classes("items-center justify-between"):
                        ui.label(label).classes("metric-label")
                        ui.icon(icon, size="14px").style(f"color: {accent}; opacity: 0.8")
                    ui.label(value).classes("font-bold mt-1").style(
                        f"font-size: 24px; letter-spacing: -0.015em; "
                        f"color: var(--text-primary); font-variant-numeric: tabular-nums"
                    )

        # --- Category filter + search ---
        active_category = {"value": "All"}
        search_text = {"value": ""}

        filter_row = ui.row().classes("w-full items-center flex-wrap mb-3").style("gap: 6px")
        grid_container = ui.element("div").classes("w-full cx-grid")

        def render_filters():
            filter_row.clear()
            with filter_row:
                for cat in CATEGORIES:
                    def _pick(c=cat):
                        active_category["value"] = c
                        render_filters()
                        render_grid()
                    is_active = cat == active_category["value"]
                    cls = "cx-filter active" if is_active else "cx-filter"
                    ui.button(cat, on_click=_pick).props("flat no-caps size=sm dense").classes(cls)

                ui.space()
                # Search input
                def _search(e):
                    search_text["value"] = (e.value or "").strip().lower()
                    render_grid()
                ui.input(placeholder="Search connectors…", on_change=_search).props(
                    "outlined dense clearable prepend-icon=search"
                ).classes("w-64")

        def render_grid():
            grid_container.clear()
            q = search_text["value"]
            cat = active_category["value"]
            filtered = [
                c for c in CONNECTORS
                if (cat == "All" or c["category"] == cat)
                and (
                    not q or
                    q in c["name"].lower() or
                    q in c["description"].lower() or
                    q in c["category"].lower()
                )
            ]
            with grid_container:
                if not filtered:
                    with ui.column().classes("col-span-full items-center py-16"):
                        ui.icon("search_off", size="48px").style("color: var(--text-muted)")
                        ui.label("No connectors match your filter").classes("mt-3").style(
                            "color: var(--text-secondary)"
                        )
                    return
                for cx in filtered:
                    _render_connector_card(cx)

        render_filters()
        render_grid()


def _render_connector_card(cx: dict):
    meta = _STATUS_META.get(cx["status"], _STATUS_META["available"])
    is_connected = cx["status"] == "connected"
    is_coming_soon = cx["status"] == "coming_soon"

    with ui.element("div").classes("cx-card"):
        # Top row: logo + name/category + status pill
        with ui.row().classes("w-full items-start gap-3"):
            with ui.element("div").classes("cx-logo").style(
                f"background: {cx['color']}"
            ):
                ui.html(cx["short"])
            with ui.column().classes("flex-1 gap-0 min-w-0"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(cx["name"]).classes("font-bold truncate").style(
                        "font-size: 16px; letter-spacing: -0.01em; color: var(--text-primary)"
                    )
                ui.label(cx["category"]).classes("text-xs").style(
                    "color: var(--text-muted); margin-top: 2px"
                )
            ui.html(f'<span class="pill {meta["pill"]}">{meta["label"]}</span>')

        # Description
        ui.label(cx["description"]).classes("text-sm").style(
            "color: var(--text-secondary); line-height: 1.5"
        )

        # Footer: connection info + action button
        with ui.row().classes("w-full items-center mt-1").style("gap: 10px"):
            if is_connected and cx.get("connected_as"):
                ui.html(
                    f'<div style="display:flex;align-items:center;font-size:11px;color:var(--text-muted)">'
                    f'<span class="cx-connected-dot"></span>'
                    f'<span style="font-family:var(--font-mono)">{cx["connected_as"]}</span>'
                    f'</div>'
                )
            ui.space()
            if is_coming_soon:
                ui.button("Notify me", icon="notifications", on_click=lambda c=cx: _notify_me(c)).props(
                    "flat dense no-caps color=grey-6"
                ).classes("cx-connect-btn")
            elif is_connected:
                ui.button("Manage", icon="settings", on_click=lambda c=cx: _show_manage_dialog(c)).props(
                    "flat dense no-caps color=primary"
                ).classes("cx-connect-btn")
                ui.button("Disconnect", icon="link_off", on_click=lambda c=cx: _show_disconnect_dialog(c)).props(
                    "flat dense no-caps color=red-5"
                ).classes("cx-connect-btn")
            else:
                ui.button("Connect", icon="link", on_click=lambda c=cx: _show_connect_dialog(c)).props(
                    "color=primary dense no-caps"
                ).classes("cx-connect-btn")


# ---------- Dialogs ----------

def _show_connect_dialog(cx: dict):
    with ui.dialog() as dialog, ui.card().classes("w-[520px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-2"):
            with ui.element("div").classes("cx-logo").style(f"background: {cx['color']}"):
                ui.html(cx["short"])
            with ui.column().classes("gap-0"):
                ui.label(f"Connect {cx['name']}").classes("text-xl font-bold").style(
                    "letter-spacing: -0.01em"
                )
                ui.label(cx["category"]).classes("text-xs").style("color: var(--text-muted)")

        ui.label(cx["description"]).classes("text-sm mb-4").style(
            "color: var(--text-secondary); line-height: 1.5"
        )

        # Auth UI per type
        auth = cx.get("auth", "none")
        if auth == "oauth":
            with ui.card().classes("w-full p-3 rounded-lg border-0 mb-3").style(
                "background: var(--bg-surface-muted)"
            ):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("verified_user", size="16px").style("color: #3b82f6")
                    ui.label("OAuth 2.0").classes("text-sm font-semibold")
                ui.label(
                    f"You'll be redirected to {cx['name']} to approve access. "
                    "No passwords are stored — we only keep the access token."
                ).classes("text-xs mt-1").style("color: var(--text-secondary)")
        elif auth == "api_key":
            ui.label("API Key").classes("metric-label")
            ui.input(placeholder=f"Paste your {cx['name']} API key").classes(
                "w-full mb-3"
            ).props("outlined dense type=password")
        elif auth == "mcp_url":
            ui.label("MCP Server URL").classes("metric-label")
            ui.input(placeholder="https://mcp.example.com/stream").classes(
                "w-full mb-3"
            ).props("outlined dense")

        # Scope/permissions placeholder
        with ui.card().classes("w-full p-3 rounded-lg border-0 mb-3").style(
            "background: rgba(59,130,246,0.06); border: 1px solid rgba(59,130,246,0.20) !important"
        ):
            ui.label("CoWorkers will be able to").classes("metric-label").style(
                "color: #3b82f6"
            )
            ui.html(
                '<ul style="margin:4px 0 0 0;padding-left:18px;font-size:12px;'
                'color:var(--text-secondary);line-height:1.7">'
                '<li>Read data on your behalf</li>'
                '<li>Write back when you explicitly approve an action</li>'
                '<li>Be revoked any time from this page</li>'
                '</ul>'
            )

        with ui.row().classes("w-full justify-end mt-2 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def do_connect():
                ui.notify(
                    f"Placeholder: {cx['name']} connection flow not yet implemented",
                    type="info", icon="info", timeout=3000,
                )
                dialog.close()

            label = "Authorise" if auth == "oauth" else "Connect"
            ui.button(label, icon="link", on_click=do_connect).props("color=primary")

    dialog.open()


def _show_manage_dialog(cx: dict):
    with ui.dialog() as dialog, ui.card().classes("w-[480px] p-6 rounded-2xl"):
        with ui.row().classes("w-full items-center gap-3 mb-2"):
            with ui.element("div").classes("cx-logo").style(f"background: {cx['color']}"):
                ui.html(cx["short"])
            ui.label(f"Manage {cx['name']}").classes("text-xl font-bold")

        with ui.card().classes("w-full p-3 rounded-lg border-0 mb-3").style(
            "background: var(--bg-surface-muted)"
        ):
            ui.label("Connected account").classes("metric-label")
            ui.label(cx.get("connected_as", "—")).classes("text-sm mono mt-1").style(
                "color: var(--text-primary)"
            )

        with ui.card().classes("w-full p-3 rounded-lg border-0 mb-3").style(
            "background: var(--bg-surface-muted)"
        ):
            ui.label("Status").classes("metric-label")
            ui.html(
                f'<div style="display:flex;align-items:center;margin-top:4px">'
                f'<span class="cx-connected-dot"></span>'
                f'<span style="font-size:13px;color:var(--text-primary)">Healthy · last sync 2m ago</span>'
                f'</div>'
            )

        ui.label("Granted permissions").classes("metric-label mt-2")
        ui.html(
            '<ul style="margin:4px 0 16px 0;padding-left:18px;font-size:12px;'
            'color:var(--text-secondary);line-height:1.7">'
            '<li>Read resources</li>'
            '<li>Write resources (with approval)</li>'
            '<li>Read user profile</li>'
            '</ul>'
        )

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Close", on_click=dialog.close).props("flat")
            ui.button("Refresh token", icon="refresh").props("color=primary flat")
    dialog.open()


def _show_disconnect_dialog(cx: dict):
    with ui.dialog() as dialog, ui.card().classes("w-[460px] p-6 rounded-2xl"):
        with ui.row().classes("items-center gap-3 mb-2"):
            with ui.element("div").classes("rounded-xl p-2").style(
                "background: rgba(239,68,68,0.14)"
            ):
                ui.icon("link_off", size="20px").style("color: #ef4444")
            ui.label(f"Disconnect {cx['name']}?").classes("text-xl font-bold")

        ui.label(
            f'This revokes the connection to {cx["name"]}. '
            f'CoWorkers will lose access until reconnected. Your data inside '
            f'{cx["name"]} is not affected.'
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def do_disconnect():
                ui.notify(
                    f"Placeholder: would disconnect {cx['name']} here",
                    type="info", icon="link_off", timeout=2500,
                )
                dialog.close()

            ui.button("Disconnect", icon="link_off", on_click=do_disconnect).props("color=red")
    dialog.open()


def _notify_me(cx: dict):
    ui.notify(
        f"👍 We'll notify you when {cx['name']} is ready",
        type="positive", timeout=2500,
    )


def _show_add_mcp_dialog():
    """Add a custom MCP server by URL + auth."""
    with ui.dialog() as dialog, ui.card().classes("w-[540px] p-6 rounded-2xl"):
        with ui.row().classes("items-center gap-3 mb-1"):
            with ui.element("div").classes("rounded-xl p-2").style(
                "background: rgba(59,130,246,0.14)"
            ):
                ui.icon("dns", size="20px").style("color: #3b82f6")
            ui.label("Add Custom MCP Server").classes("text-xl font-bold").style(
                "letter-spacing: -0.01em"
            )

        ui.label(
            "Point CoWorkers at any MCP-compliant server — your own or a third-party one "
            "that isn't in the built-in catalog."
        ).classes("text-sm mb-4").style("color: var(--text-secondary)")

        ui.input("Display name", placeholder="e.g. Internal KB").classes("w-full mb-3").props("outlined")
        ui.input("MCP server URL", placeholder="https://mcp.example.com/stream").classes(
            "w-full mb-3"
        ).props("outlined")
        ui.select(
            ["None", "Bearer token", "OAuth 2.0", "Custom header"],
            value="None", label="Auth",
        ).classes("w-full mb-3").props("outlined")
        ui.textarea("Description", placeholder="What this server provides (optional)").classes(
            "w-full mb-3"
        ).props("outlined autogrow")

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            def add():
                ui.notify("Placeholder: custom MCP add not yet wired", type="info")
                dialog.close()
            ui.button("Add Server", icon="add", on_click=add).props("color=primary")
    dialog.open()
