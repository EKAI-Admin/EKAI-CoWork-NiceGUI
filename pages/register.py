from nicegui import ui
from auth import hash_password
from db import create_user, get_user_by_username
import sqlite3


def register_page():
    with ui.column().classes("w-full items-center justify-center min-h-screen bg-gray-50"):
        with ui.card().classes("w-96 p-8"):
            ui.label("EKAI CoWork").classes("text-2xl font-bold text-center w-full mb-2")
            ui.label("Create a new account").classes("text-gray-500 text-center w-full mb-6")

            username = ui.input("Username").classes("w-full").props("outlined")
            email = ui.input("Email").classes("w-full").props("outlined")
            password = ui.input("Password", password=True, password_toggle_button=True).classes("w-full").props("outlined")
            confirm = ui.input("Confirm Password", password=True, password_toggle_button=True).classes("w-full").props("outlined")
            error_label = ui.label("").classes("text-red-500 text-sm")
            error_label.visible = False
            success_label = ui.label("").classes("text-green-500 text-sm")
            success_label.visible = False

            def handle_register():
                error_label.visible = False
                success_label.visible = False

                if not all([username.value, email.value, password.value, confirm.value]):
                    error_label.text = "Please fill in all fields"
                    error_label.visible = True
                    return

                if password.value != confirm.value:
                    error_label.text = "Passwords do not match"
                    error_label.visible = True
                    return

                if len(password.value) < 6:
                    error_label.text = "Password must be at least 6 characters"
                    error_label.visible = True
                    return

                try:
                    pw_hash = hash_password(password.value)
                    create_user(username.value, email.value, pw_hash)
                    success_label.text = "Account created! Redirecting to login..."
                    success_label.visible = True
                    ui.timer(1.5, lambda: ui.navigate.to("/login"), once=True)
                except sqlite3.IntegrityError:
                    error_label.text = "Username or email already exists"
                    error_label.visible = True

            ui.button("Create Account", on_click=handle_register).classes("w-full mt-4").props("color=primary")

            with ui.row().classes("w-full justify-center mt-4"):
                ui.label("Already have an account?").classes("text-gray-500")
                ui.link("Sign In", "/login").classes("text-blue-500")
