from dotenv import load_dotenv
load_dotenv(override=True)

from nicegui import ui, app
from db import init_db
from pages.login import login_page
from pages.register import register_page
from pages.dashboard import dashboard_page
from pages.coworkers import coworkers_page
from pages.departments import departments_page
from pages.connectors import connectors_page
from pages.runs import runs_page
from pages.settings import settings_page

init_db()


@ui.page("/login")
def login():
    login_page()


@ui.page("/register")
def register():
    register_page()


@ui.page("/")
def dashboard():
    dashboard_page()


@ui.page("/coworkers")
def coworkers():
    coworkers_page()


@ui.page("/departments")
def departments():
    departments_page()


@ui.page("/connectors")
def connectors():
    connectors_page()


@ui.page("/runs")
def runs():
    runs_page()


@ui.page("/settings")
def settings():
    settings_page()


@ui.page("/runs/{run_id}/report")
def run_report(run_id: int):
    from pages.report import report_page
    report_page(run_id)


ui.run(
    title="EKAI CoWork",
    port=8080,
    storage_secret="ekai-cowork-secret-key-change-in-production",
    dark=False,
    reload=False,
)
