from nicegui import ui
from auth import get_current_user
from db import get_settings, upsert_settings
from models import CLAUDE_MODELS, OLLAMA_MODELS


def settings_page():
    user = get_current_user()
    if not user:
        ui.navigate.to("/login")
        return

    user_id = user["id"]
    current = get_settings(user_id)

    # Header
    with ui.header().classes("bg-blue-600 text-white items-center justify-between px-6"):
        ui.label("EKAI CoWork").classes("text-xl font-bold")
        with ui.row().classes("items-center gap-4"):
            ui.button("Dashboard", icon="dashboard", on_click=lambda: ui.navigate.to("/")).props("flat text-color=white")
            ui.button("Settings", icon="settings", on_click=lambda: ui.navigate.to("/settings")).props("flat text-color=white")
            with ui.row().classes("items-center gap-2"):
                ui.icon("person").classes("text-white")
                ui.label(user["username"]).classes("text-white")
            ui.button("Logout", icon="logout", on_click=lambda: (
                __import__("auth").logout(),
                ui.navigate.to("/login"),
            )).props("flat text-color=white")

    with ui.column().classes("w-full p-6 max-w-2xl mx-auto"):
        ui.label("Settings").classes("text-2xl font-bold mb-6")

        with ui.card().classes("w-full p-6"):
            ui.label("Default Model Configuration").classes("text-lg font-semibold mb-4")
            ui.label("Set the default AI model for new CoWorkers").classes("text-gray-500 mb-4")

            provider_val = current["default_provider"] if current else "claude"
            provider = ui.select(
                ["claude", "ollama"],
                label="Default Provider",
                value=provider_val,
            ).classes("w-full").props("outlined")

            model_options = CLAUDE_MODELS if provider_val == "claude" else OLLAMA_MODELS
            model_val = current["default_model"] if current else "claude-sonnet-4-20250514"
            model = ui.select(
                model_options,
                label="Default Model",
                value=model_val,
            ).classes("w-full").props("outlined")

            def on_provider_change(e):
                opts = CLAUDE_MODELS if e.value == "claude" else OLLAMA_MODELS
                model.options = opts
                model.value = opts[0]
                model.update()

            provider.on_value_change(on_provider_change)

        with ui.card().classes("w-full p-6 mt-4"):
            ui.label("Ollama Configuration").classes("text-lg font-semibold mb-4")
            ui.label("Configure the Ollama server connection").classes("text-gray-500 mb-4")

            ollama_url = ui.input(
                "Ollama Base URL",
                value=current["ollama_base_url"] if current else "http://localhost:11434",
            ).classes("w-full").props("outlined")

        success_label = ui.label("Settings saved!").classes("text-green-500 mt-4")
        success_label.visible = False

        def save_settings():
            upsert_settings(user_id, provider.value, model.value, ollama_url.value)
            success_label.visible = True
            ui.timer(2.0, lambda: setattr(success_label, "visible", False), once=True)

        ui.button("Save Settings", icon="save", on_click=save_settings).classes("mt-4").props("color=primary")
