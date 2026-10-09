# Nova

![Tests](https://github.com/abhilashyaragal570-del/nova/actions/workflows/tests.yml/badge.svg)

Nova is a password-protected AI assistant built with Python and the Google Gemini API. It started as a command-line chat and now includes a web interface, a tool-using agent, a workflow engine, and optional PostgreSQL storage.

## Features

- Password-protected web interface built with Flask, with saved conversations and an editable system prompt
- Streaming responses, printed as they are generated
- Tool-using agent: Gemini decides when to call a built-in tool
- Built-in tools: calculator, file tools, web search and an API request tool
- Safety layer around tools: read-only flags, confirmation before anything that changes things, timeouts and unsafe-URL blocking
- Browser approval: in the web app, a tool that needs approval shows an Approve / Deny card
- Workflow engine: plans a goal, shows the plan, asks for approval, runs it with retries and saves progress so it can be resumed
- Conversation storage behind one interface: local files by default, PostgreSQL when `DATABASE_URL` is set
- Token usage shown after every reply
- Terminal commands: `/clear`, `/history`, `/model` and `/system`
- API keys, model name and password kept in a `.env` file

## Setup

1. Clone the repo and open the folder.

2. Create and activate a virtual environment.

   Windows:

        python -m venv venv
        venv\Scripts\activate

   macOS / Linux:

        python -m venv venv
        source venv/bin/activate

3. Install the dependencies:

        pip install -r requirements.txt

4. Copy `.env.example` to `.env` and put your real values in it. The file looks like this:

        GEMINI_API_KEY=your_key_here
        GEMINI_MODEL=gemini-flash-lite-latest
        NOVA_PASSWORD=choose-a-password
        NOVA_SYSTEM_PROMPT=You are Nova, a friendly and precise AI assistant. Keep answers clear and concise.
        TAVILY_API_KEY=
        DATABASE_URL=

   - `GEMINI_API_KEY` is required. Get a key from Google AI Studio.
   - `NOVA_PASSWORD` is required for the web app. If it is empty, the server refuses every request.
   - `TAVILY_API_KEY` is only needed for the web search tool.
   - `DATABASE_URL` is optional. Leave it empty to save chats as local files. Set it to a PostgreSQL connection string to save them in a database.
   - Never commit your `.env` file.

## Run

### Terminal chat

        python -m app.chat

Type `exit` to quit, `/clear` to forget the conversation, `/history` to see recent messages, `/model` to see the model in use, or `/system` to see or change the personality. A tool that changes things asks you `[y/N]` in the terminal first.

### Web app

        flask --app web.server run

Open http://127.0.0.1:5000 in your browser. The browser asks for a login. Use any username and your `NOVA_PASSWORD`.

When Nova wants to run a tool that changes things, such as writing a file or calling an API, a card appears above the message box. Nothing runs until you click **Approve**, and **Deny** cancels it.

## Tools

Nova can call these tools when a request needs them:

- Calculator
- File tools: list, read and write files in the `workspace/` folder
- Web search (needs `TAVILY_API_KEY`)
- API request tool

Tools are checked before they run. Read-only tools run freely, tools that change things need your approval, every call has a timeout, and the web and API tools refuse unsafe URLs.

## Workflows

Give Nova a goal in plain words. It plans the steps, shows you the plan, and runs nothing until you answer `y`.

        python -m workflows "list the files in my workspace folder"
        python -m workflows --list
        python -m workflows --resume WORKFLOW_ID

Options:

- `--write-tools` lets plans use tools that change things (each write still asks first)
- `--no-critic` skips the extra model review of the plan

Runs are saved in `workflow_data/`, so an interrupted workflow can be resumed.

## Storage

Conversations are saved through one interface, so the storage can change without touching the rest of the app:

- **Files (default):** the main chat in `history.json`, other chats in `conversations/`.
- **PostgreSQL:** set `DATABASE_URL`. Nova creates its table on first use.

Workflow runs are still saved as files in `workflow_data/`.

## Deploy to Render

1. Push the repo to GitHub and create a **Web Service** on Render from it.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn web.server:app --workers 1 --threads 4 --timeout 120`
4. Add the variables from `.env` under **Environment**: at least `GEMINI_API_KEY`, `GEMINI_MODEL` and `NOVA_PASSWORD`. Optionally add `PYTHON_VERSION=3.12.3`.
5. To keep chats across restarts, create a **Postgres** database on Render in the same region, and add its **Internal Database URL** as `DATABASE_URL`.

Notes for the free plan:

- The service sleeps after about 15 minutes without traffic, so the first request can take up to a minute.
- The disk is wiped on every restart, so without `DATABASE_URL`, saved chats are lost.
- Free Render databases expire after 30 days. To renew: create a new free database, replace `DATABASE_URL` in **Environment** with its new Internal Database URL, then delete the old database. Chats saved in the old one are not carried over.

## Notes

`.env`, `history.json`, `personality.json`, `conversations/`, `workflow_data/` and `workspace/` are listed in `.gitignore`, so your keys and conversations are never pushed to GitHub.

## Tests

Install the dev requirements and run the tests:

        pip install -r requirements-dev.txt
        python -m pytest

Tests run on every push with GitHub Actions. They use fake models, so they never call Gemini.

## Roadmap

Done: tools, workflows, conversation storage on PostgreSQL, browser approval for tool calls.

Planned next: PostgreSQL storage and browser approval for workflows, document search (RAG), and specialized agents.

## License

Apache License 2.0. See [LICENSE](LICENSE).