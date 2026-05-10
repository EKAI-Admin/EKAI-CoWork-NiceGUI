"""Shared layout: left sidebar with navigation, dark/light toggle, avatar at bottom."""

from nicegui import ui, app

from db import count_active_runs
from theme import avatar_gradient


# --- Global design-system CSS: injected once per page load ---
_GLOBAL_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --font-sans: "Inter", ui-sans-serif, system-ui, -apple-system, sans-serif;
    --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
  }

  /* Light-mode tokens */
  :root {
    --bg-page: #f7f7f8;
    --bg-surface: #ffffff;
    --bg-surface-muted: #f3f4f6;
    --border-subtle: rgba(0,0,0,0.06);
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --accent: #3b82f6;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
  }

  /* Dark-mode overrides */
  body.body--dark {
    --bg-page: #0a0a0c;
    --bg-surface: #15151a;
    --bg-surface-muted: #1e1e24;
    --border-subtle: rgba(255,255,255,0.06);
    --text-primary: #f1f5f9;
    --text-secondary: #cbd5e1;
    --text-muted: #64748b;
  }

  /* Global typography */
  body, html {
    font-family: var(--font-sans);
    font-feature-settings: "cv11", "ss01", "ss03";
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    color: var(--text-primary);
  }
  body.body--dark { background: var(--bg-page) !important; }
  body:not(.body--dark) { background: var(--bg-page) !important; }

  /* Ensure page-level headings use the theme's primary text color */
  .text-3xl, .text-2xl, .text-xl, .text-lg {
    color: var(--text-primary);
  }

  /* Tabular numerals + mono helpers — for IDs, times, amounts, dates */
  .mono, .font-mono { font-family: var(--font-mono) !important; font-feature-settings: "zero" 0; }
  .tnum { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }

  /* Pill badges (consistent across app) */
  .pill {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 10px;
    font-family: var(--font-sans);
    font-size: 11px; font-weight: 600;
    border-radius: 9999px;
    letter-spacing: 0.01em;
    line-height: 1.3;
  }
  .pill-blue   { background: rgba(59,130,246,.14); color: #60a5fa; }
  .pill-green  { background: rgba(16,185,129,.14); color: #34d399; }
  .pill-amber  { background: rgba(245,158,11,.14); color: #fbbf24; }
  .pill-red    { background: rgba(239,68,68,.14); color: #f87171; }
  .pill-gray   { background: rgba(148,163,184,.14); color: #94a3b8; }
  .pill-purple { background: rgba(139,92,246,.14); color: #a78bfa; }
  body.body--dark .pill-purple { color: #c4b5fd; }  /* higher contrast on dark */

  /* Card surfaces */
  body.body--dark .q-card,
  body.body--dark .nicegui-card {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border-subtle) !important;
    box-shadow: none !important;
  }
  body.body--dark .q-expansion-item {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
  }

  /* Larger headline/metric number style */
  .metric-value {
    font-family: var(--font-sans);
    font-weight: 700;
    font-size: 2rem;
    letter-spacing: -0.025em;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .metric-label {
    font-family: var(--font-sans);
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-muted);
    text-transform: none;
    letter-spacing: 0.01em;
  }

  /* Quasar tabs — modern underline style */
  .q-tab { font-family: var(--font-sans); font-weight: 500; text-transform: none; letter-spacing: 0; }
  body.body--dark .q-tabs__content { border-bottom: 1px solid var(--border-subtle); }

  /* Smoother separators */
  body.body--dark .q-separator { background: var(--border-subtle) !important; }

  /* Input elements */
  body.body--dark .q-field__control { background: var(--bg-surface-muted); }

  /* Purple / deep-purple tweaks for readability.
     NOTE: Quasar ships !important color rules in the `quasar_importants`
     CSS layer. Per the CSS spec, !important declarations in EARLIER layers
     WIN over later layers and unlayered — so we put our overrides in the
     `overrides` layer (declared right before quasar_importants by NiceGUI). */
  @layer overrides {
    body.body--dark .text-purple,
    body.body--dark .q-btn--flat.text-purple,
    body.body--dark .q-btn--round.text-purple { color: #c4b5fd !important; }
    body.body--dark .text-deep-purple,
    body.body--dark .q-btn--flat.text-deep-purple,
    body.body--dark .q-btn--outline.text-deep-purple { color: #c4b5fd !important; }
    body.body--dark .q-btn--outline.text-purple,
    body.body--dark .q-btn--outline.text-deep-purple {
      border-color: rgba(196,181,253,0.32) !important;
    }
    body.body--dark .bg-purple { background: rgba(139,92,246,0.80) !important; }
    body.body--dark .bg-deep-purple { background: rgba(109,40,217,0.85) !important; }

    body.body--dark .text-purple-500 { color: #c4b5fd !important; }
    body.body--dark .text-purple-400 { color: #c4b5fd !important; }

    body:not(.body--dark) .q-btn--flat.text-purple,
    body:not(.body--dark) .q-btn--round.text-purple,
    body:not(.body--dark) .q-btn--flat.text-deep-purple { color: #7c3aed !important; }
  }
</style>
"""


def build_layout(user: dict | None = None, active: str = "dashboard"):
    """Build the shared left-sidebar layout.

    Args:
        user: current user dict with 'username', or None for auth pages.
        active: 'dashboard' or 'settings' to highlight the active nav item.

    Returns the main content column element to place page content in.
    """
    # Read persisted theme first so we can prevent the "white flash" on navigation
    is_dark = app.storage.user.get("dark_mode", False)

    # Theme-aware flash-prevention + page transition.
    # The <html> background is set synchronously in <head> so the very first
    # paint matches the user's theme — no white frame before the app mounts.
    ui.add_head_html(f"""
    <meta name="color-scheme" content="{'dark' if is_dark else 'light'}">
    <meta name="theme-color" content="{'#0a0a0c' if is_dark else '#f7f7f8'}">
    <style>
      :root {{
        color-scheme: {'dark' if is_dark else 'light'};
      }}
      html, body {{
        background: {'#0a0a0c' if is_dark else '#f7f7f8'} !important;
        transition: background-color 0.2s ease;
      }}
      /* Subtle fade-in on page content so navigation feels smooth */
      .nicegui-content,
      .q-layout {{
        animation: cw-page-fade 0.22s ease-out;
      }}
      @keyframes cw-page-fade {{
        from {{ opacity: 0; transform: translateY(3px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
      }}
    </style>
    <script>
      // Apply dark class BEFORE first paint so Quasar's dark styles are
      // active immediately — eliminates any flash of unstyled content.
      (function() {{
        if ({str(is_dark).lower()}) {{
          document.documentElement.classList.add('body--dark');
          // body isn't in the DOM yet during head parsing — schedule for DOMContentLoaded
          document.addEventListener('DOMContentLoaded', () => {{
            document.body.classList.add('body--dark');
          }}, {{ once: true }});
        }}
      }})();
    </script>
    """)

    # Inject global design-system CSS (fonts, tokens, pills, card surfaces)
    ui.add_head_html(_GLOBAL_CSS)

    dark = ui.dark_mode()
    dark.value = is_dark

    if user:
        # Quasar requires a header for drawer to push content properly
        with ui.header(elevated=False).style("height: 0; min-height: 0; padding: 0; overflow: hidden"):
            pass

        # Persisted sidebar collapse state
        sidebar_mini = app.storage.user.get("sidebar_mini", False)

        drawer = ui.left_drawer(value=True, fixed=True, bordered=True).classes(
            "flex flex-col justify-between py-4 px-2"
        ).props(
            f"width=220 mini-width=64 :breakpoint=0"
            + (" mini" if sidebar_mini else "")
        ).style("transition: width 0.2s ease")

        with drawer:
            # Top section: logo + nav
            with ui.column().classes("gap-1 w-full"):
                with ui.row().classes("items-center gap-2 px-3 mb-4"):
                    ui.icon("hub", size="28px").classes("text-blue-500")
                    logo_label = ui.label("EKAI CoWork").classes("text-lg font-bold")
                    if sidebar_mini:
                        logo_label.style("display: none")

                ui.separator().classes("mb-2")

                _nav_item("dashboard", "Dashboard", "dashboard", "/", active, mini=sidebar_mini)
                cw_badge = _nav_item("coworkers", "CoWorkers", "group", "/coworkers", active, with_badge=True, mini=sidebar_mini)
                _nav_item("departments", "Departments", "apartment", "/departments", active, mini=sidebar_mini)
                _nav_item("connectors", "Connectors", "extension", "/connectors", active, mini=sidebar_mini)
                runs_badge = _nav_item("runs", "Runs", "play_circle", "/runs", active, with_badge=True, mini=sidebar_mini)
                _nav_item("settings", "Settings", "settings", "/settings", active, mini=sidebar_mini)

                def _refresh_nav_badges():
                    n = count_active_runs(user["id"])
                    for badge in (cw_badge, runs_badge):
                        if badge is None:
                            continue
                        if n > 0:
                            badge.text = str(n)
                            badge.style("display: inline-flex")
                        else:
                            badge.text = ""
                            badge.style("display: none")

                _refresh_nav_badges()
                ui.timer(3.0, _refresh_nav_badges)

            # Bottom section: collapse toggle + theme + avatar
            with ui.column().classes("gap-2 w-full"):
                ui.separator()

                # Sidebar collapse toggle
                def _toggle_mini():
                    is_mini = not app.storage.user.get("sidebar_mini", False)
                    app.storage.user["sidebar_mini"] = is_mini
                    # Full reload to re-render layout with new mini state
                    ui.navigate.to(ui.context.client.page.path)

                with ui.row().classes("items-center justify-center px-1 py-1"):
                    ui.button(
                        icon="chevron_left" if not sidebar_mini else "chevron_right",
                        on_click=_toggle_mini,
                    ).props("flat round dense size=sm").tooltip(
                        "Collapse sidebar" if not sidebar_mini else "Expand sidebar"
                    )

                ui.separator()

                # Dark / Light toggle
                with ui.row().classes("items-center justify-between px-3 py-1"):
                    theme_label = ui.label("Theme").classes("text-sm text-gray-600 dark:text-gray-400")
                    if sidebar_mini:
                        theme_label.style("display: none")
                    theme_switch = ui.switch(
                        value=is_dark,
                        on_change=lambda e: _toggle_theme(e.value, dark),
                    ).props("dense")
                    theme_icon = ui.icon("dark_mode" if is_dark else "light_mode", size="20px").bind_name_from(
                        theme_switch, "value", lambda v: "dark_mode" if v else "light_mode"
                    )

                ui.separator()

                # User avatar + logout
                with ui.row().classes("items-center gap-3 px-3 py-2"):
                    initials = user["username"][:2].upper()
                    with ui.avatar(text_color="white", size="36px").style(
                        f"background: {avatar_gradient(0)}"
                    ):
                        ui.label(initials).classes("text-sm font-bold")
                    if not sidebar_mini:
                        with ui.column().classes("gap-0"):
                            ui.label(user["username"]).classes("text-sm font-semibold leading-tight text-gray-700 dark:text-gray-200")
                            ui.link("Logout", target="").classes(
                                "text-xs text-red-400 cursor-pointer no-underline"
                            ).on("click", lambda: _logout())

    # Main content area
    content = ui.column().classes("w-full p-6")
    return content


def _smooth_navigate(target: str) -> None:
    """Fade the page out to the theme background before navigating, so the
    browser's between-pages frame doesn't flash white in dark mode."""
    # No-op if already on this page
    ui.run_javascript(f"""
        (function() {{
            try {{
                if (window.location.pathname === {target!r}) return;
                const overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;inset:0;background:' +
                    (document.body.classList.contains('body--dark') ? '#0a0a0c' : '#f7f7f8') +
                    ';z-index:99999;opacity:0;transition:opacity 0.15s ease;pointer-events:none';
                document.body.appendChild(overlay);
                requestAnimationFrame(() => {{ overlay.style.opacity = '1'; }});
                setTimeout(() => {{ window.location.href = {target!r}; }}, 160);
            }} catch (e) {{
                window.location.href = {target!r};
            }}
        }})();
    """)


def _nav_item(key: str, label: str, icon: str, target: str, active: str,
              with_badge: bool = False, mini: bool = False):
    """Render a sidebar nav button. Returns the badge element if with_badge=True."""
    is_active = key == active
    if is_active:
        color_cls = "bg-blue-50 text-blue-700 dark:bg-blue-900 dark:text-blue-200"
    else:
        color_cls = "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"

    badge_el = None
    with ui.button(on_click=lambda: _smooth_navigate(target)).props(
        "flat no-caps align=left"
    ).classes(f"w-full justify-start rounded-lg px-3 py-2 {color_cls}"):
        ui.icon(icon, size="20px").classes("mr-3" if not mini else "mr-0")
        if not mini:
            ui.label(label).classes("text-sm font-medium flex-1 text-left")
        if with_badge:
            badge_el = ui.label("").classes(
                "inline-flex items-center justify-center text-[10px] font-bold "
                "bg-blue-500 text-white rounded-full px-2 py-0.5 min-w-[20px] ml-auto"
            ).style("display: none")
    return badge_el


def _toggle_theme(is_dark: bool, dark_mode):
    """Toggle dark/light theme and persist to storage."""
    dark_mode.value = is_dark
    app.storage.user["dark_mode"] = is_dark


def _logout():
    from auth import logout
    logout()
    ui.navigate.to("/login")
