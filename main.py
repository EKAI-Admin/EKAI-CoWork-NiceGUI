from dotenv import load_dotenv
load_dotenv(override=True)

from nicegui import ui, app
from db import init_db
from pages.login import login_page
from pages.register import register_page
from pages.dashboard import dashboard_page
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


@ui.page("/settings")
def settings():
    settings_page()


ui.run(
    title="EKAI CoWork",
    port=8080,
    storage_secret="ekai-cowork-secret-key-change-in-production",
    dark=False,
)
