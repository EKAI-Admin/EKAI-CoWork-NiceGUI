from nicegui import ui, app
from auth import verify_password, set_current_user
from db import get_user_by_username


def login_page():
    with ui.column().classes("w-full items-center justify-center min-h-screen bg-gray-50"):
        with ui.card().classes("w-96 p-8"):
            ui.label("EKAI CoWork").classes("text-2xl font-bold text-center w-full mb-2")
            ui.label("Sign in to your account").classes("text-gray-500 text-center w-full mb-6")

            username = ui.input("Username").classes("w-full").props("outlined")
            password = ui.input("Password", password=True, password_toggle_button=True).classes("w-full").props("outlined")
            error_label = ui.label("").classes("text-red-500 text-sm")
            error_label.visible = False

            def handle_login():
                error_label.visible = False
                if not username.value or not password.value:
                    error_label.text = "Please fill in all fields"
                    error_label.visible = True
                    return

                user = get_user_by_username(username.value)
                if not user or not verify_password(password.value, user["password_hash"]):
                    error_label.text = "Invalid username or password"
                    error_label.visible = True
                    return

                set_current_user({"id": user["id"], "username": user["username"], "email": user["email"]})
                ui.navigate.to("/")

            ui.button("Sign In", on_click=handle_login).classes("w-full mt-4").props("color=primary")

            with ui.row().classes("w-full justify-center mt-4"):
                ui.label("Don't have an account?").classes("text-gray-500")
                ui.link("Register", "/register").classes("text-blue-500")
