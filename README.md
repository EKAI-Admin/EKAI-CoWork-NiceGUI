# EKAI CoWork

A CoWorker management dashboard built with [NiceGUI](https://nicegui.io) and SQLite3. Manage AI CoWorkers, each responsible for a single workflow, with support for Claude and Ollama models.

## Features

- **Authentication** - User registration and login with bcrypt password hashing
- **Dashboard** - Card-based view of all CoWorkers showing name, job description, workflow, status, model info, and join date
- **CoWorker Management** - Add, edit, and delete CoWorkers with configurable AI model assignment
- **Model Selection** - Choose between Claude (Opus, Sonnet, Haiku) and Ollama (Llama3, Mistral, etc.) models
- **Settings** - Configure default model provider and Ollama server URL
- **Per-user Data** - Each user manages their own set of CoWorkers

## Architecture

```
main.py          Entry point, page routing
db.py            SQLite3 database layer (init, CRUD operations)
models.py        Data classes and constants
auth.py          Password hashing, session management
pages/
  login.py       Login page
  register.py    Registration page
  dashboard.py   CoWorker cards dashboard
  settings.py    Model configuration settings
```

### Database Schema

- **users** - id, username, email, password_hash, created_at
- **coworkers** - id, name, job_description, workflow, status, model_provider, model_name, join_date, created_by
- **settings** - id, user_id, default_provider, default_model, ollama_base_url

## Setup

### Prerequisites

- Python 3.10+

### Installation

```bash
# Clone the repository
git clone https://github.com/EKAI-Admin/EKAI-CoWork-NiceGUI.git
cd EKAI-CoWork-NiceGUI

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Running

```bash
source venv/bin/activate
python main.py
```

The app starts at **http://localhost:8080**.

## Usage

1. **Register** - Create a new account at `/register`
2. **Login** - Sign in at `/login`
3. **Add CoWorkers** - Click "Add CoWorker" on the dashboard to create a new AI worker
4. **Configure Settings** - Go to Settings to set your default model provider (Claude or Ollama)
5. **Manage CoWorkers** - Edit or delete CoWorkers from their cards on the dashboard

## CoWorker Status

| Status | Description |
|--------|-------------|
| Active | CoWorker is currently operational |
| Paused | CoWorker is temporarily suspended |
| Inactive | CoWorker is disabled |

## Available Workflows

Code Review, Documentation, Testing, Deployment, Data Analysis, Customer Support, Content Creation, Security Audit, Performance Monitoring, Bug Triage

## License

MIT
