from nicegui import ui
from auth import get_current_user
from db import get_coworkers, create_coworker, update_coworker, delete_coworker, get_settings, get_coworker_config, upsert_coworker_config
from models import STATUS_OPTIONS, WORKFLOW_OPTIONS, CLAUDE_MODELS, OLLAMA_MODELS


STATUS_COLORS = {
    "active": "green",
    "inactive": "red",
    "paused": "orange",
}


def _get_model_options(provider: str) -> list[str]:
    return CLAUDE_MODELS if provider == "claude" else OLLAMA_MODELS


def _show_coworker_dialog(on_save, coworker=None, user_id=None):
    settings = get_settings(user_id) if user_id else None
    default_provider = settings["default_provider"] if settings else "claude"
    default_model = settings["default_model"] if settings else "claude-sonnet-4-20250514"

    with ui.dialog() as dialog, ui.card().classes("w-[500px] p-6"):
        ui.label("Edit CoWorker" if coworker else "Add CoWorker").classes("text-xl font-bold mb-4")

        name = ui.input("Name", value=coworker["name"] if coworker else "").classes("w-full").props("outlined")
        job_desc = ui.textarea("Job Description", value=coworker["job_description"] if coworker else "").classes("w-full").props("outlined")
        workflow = ui.select(
            WORKFLOW_OPTIONS,
            label="Workflow",
            value=coworker["workflow"] if coworker else WORKFLOW_OPTIONS[0],
        ).classes("w-full").props("outlined")
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
        model = ui.select(
            _get_model_options(provider_val),
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


def _show_workflow_config_dialog(coworker):
    config = get_coworker_config(coworker["id"])
    existing_paths = config["input_paths"] if config else []
    existing_prompt = config["processing_prompt"] if config else ""
    existing_output = config["output_path"] if config else ""

    path_inputs = []

    with ui.dialog() as dialog, ui.card().classes("w-[600px] p-6"):
        ui.label(f"Workflow Config — {coworker['name']}").classes("text-xl font-bold mb-2")
        ui.label(coworker["workflow"]).classes("text-gray-500 mb-4")

        with ui.tabs().classes("w-full") as tabs:
            input_tab = ui.tab("Inputs", icon="folder_open")
            processing_tab = ui.tab("Processing", icon="psychology")
            output_tab = ui.tab("Output", icon="description")

        with ui.tab_panels(tabs, value=input_tab).classes("w-full"):
            # --- Inputs Tab ---
            with ui.tab_panel(input_tab):
                ui.label("Input Sources").classes("text-sm font-semibold mb-1")
                ui.label("Point to files or folders this CoWorker reads from.").classes("text-xs text-gray-400 mb-3")

                paths_container = ui.column().classes("w-full gap-2")

                def add_path_row(value=""):
                    with paths_container:
                        with ui.row().classes("w-full items-center gap-2") as row:
                            inp = ui.input(
                                placeholder="/path/to/folder/or/file",
                                value=value,
                            ).classes("flex-grow").props("outlined dense")
                            path_inputs.append(inp)

                            def remove(r=row, i=inp):
                                if i in path_inputs:
                                    path_inputs.remove(i)
                                r.delete()

                            ui.button(icon="close", on_click=remove).props("flat dense round size=sm color=red")

                for p in existing_paths:
                    add_path_row(p)

                ui.button("Add Path", icon="add", on_click=lambda: add_path_row()).props("flat dense color=primary").classes("mt-2")

            # --- Processing Tab ---
            with ui.tab_panel(processing_tab):
                ui.label("Processing Prompt").classes("text-sm font-semibold mb-1")
                ui.label("The prompt this CoWorker uses to process inputs.").classes("text-xs text-gray-400 mb-3")
                prompt_input = ui.textarea(
                    value=existing_prompt,
                    placeholder="Enter the processing instructions for this CoWorker...",
                ).classes("w-full").props("outlined rows=10")

            # --- Output Tab ---
            with ui.tab_panel(output_tab):
                ui.label("Output Configuration").classes("text-sm font-semibold mb-1")
                ui.label("Path for the markdown output file.").classes("text-xs text-gray-400 mb-3")
                output_input = ui.input(
                    "Output File Path",
                    value=existing_output,
                    placeholder="/path/to/output/report.md",
                ).classes("w-full").props("outlined")

                ui.label("Output Structure Preview").classes("text-sm font-semibold mt-4 mb-2")
                preview_md = f"""```
{existing_output or '/path/to/output/report.md'}
├── # Header (CoWorker Name)
├── ## Summary
├── ## Findings
│   ├── ### Item 1
│   └── ### Item 2
└── ## Metadata
    ├── Model: {coworker['model_provider']}:{coworker['model_name']}
    ├── Workflow: {coworker['workflow']}
    └── Generated: <timestamp>
```"""
                ui.markdown(preview_md).classes("text-sm bg-gray-50 p-3 rounded")

        success_label = ui.label("").classes("text-green-500 text-sm mt-2")
        success_label.visible = False

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            def save_config():
                paths = [inp.value.strip() for inp in path_inputs if inp.value.strip()]
                upsert_coworker_config(
                    coworker["id"],
                    paths,
                    prompt_input.value,
                    output_input.value.strip(),
                )
                success_label.text = "Configuration saved!"
                success_label.visible = True
                ui.timer(1.5, dialog.close, once=True)

            ui.button("Save", on_click=save_config).props("color=primary")

    dialog.open()


def dashboard_page():
    user = get_current_user()
    if not user:
        ui.navigate.to("/login")
        return

    user_id = user["id"]

    def refresh_cards():
        cards_container.clear()
        coworkers = get_coworkers(user_id)
        with cards_container:
            if not coworkers:
                with ui.column().classes("w-full items-center py-16"):
                    ui.icon("group_off", size="64px").classes("text-gray-300")
                    ui.label("No CoWorkers yet").classes("text-gray-400 text-lg mt-4")
                    ui.label("Click the + button to add your first CoWorker").classes("text-gray-300")
                return

            for cw in coworkers:
                with ui.card().classes("w-80 hover:shadow-lg transition-shadow"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(cw["name"]).classes("text-lg font-semibold")
                        ui.badge(cw["status"].upper(), color=STATUS_COLORS.get(cw["status"], "gray")).props("outline")

                    ui.separator()

                    ui.label(cw["job_description"]).classes("text-gray-600 text-sm line-clamp-2")

                    with ui.row().classes("w-full items-center gap-2 mt-2"):
                        ui.icon("work", size="16px").classes("text-gray-400")
                        ui.label(cw["workflow"]).classes("text-sm text-gray-500")

                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("smart_toy", size="16px").classes("text-gray-400")
                        ui.label(f'{cw["model_provider"]}: {cw["model_name"]}').classes("text-sm text-gray-500")

                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("calendar_today", size="16px").classes("text-gray-400")
                        join_display = cw["join_date"][:10] if cw["join_date"] else "N/A"
                        ui.label(f"Joined {join_display}").classes("text-sm text-gray-500")

                    with ui.row().classes("w-full justify-end gap-1 mt-2"):
                        def make_config(c=cw):
                            _show_workflow_config_dialog(c)

                        def make_edit(c=cw):
                            def on_save(name, job_description, workflow, status, model_provider, model_name):
                                update_coworker(c["id"], name, job_description, workflow, status, model_provider, model_name)
                                refresh_cards()
                            _show_coworker_dialog(on_save, coworker=c, user_id=user_id)

                        def make_delete(c=cw):
                            delete_coworker(c["id"])
                            refresh_cards()

                        ui.button(icon="settings", on_click=make_config).props("flat dense round size=sm color=blue")
                        ui.button(icon="edit", on_click=make_edit).props("flat dense round size=sm")
                        ui.button(icon="delete", on_click=make_delete).props("flat dense round size=sm color=red")

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

    # Main content
    with ui.column().classes("w-full p-6"):
        with ui.row().classes("w-full items-center justify-between mb-6"):
            ui.label("CoWorkers Dashboard").classes("text-2xl font-bold")

            def add_coworker():
                def on_save(name, job_description, workflow, status, model_provider, model_name):
                    create_coworker(name, job_description, workflow, status, model_provider, model_name, user_id)
                    refresh_cards()
                _show_coworker_dialog(on_save, user_id=user_id)

            ui.button("Add CoWorker", icon="add", on_click=add_coworker).props("color=primary")

        cards_container = ui.row().classes("w-full flex-wrap gap-4")
        refresh_cards()
