# Nova

![Tests](https://github.com/abhilashyaragal570-del/nova/actions/workflows/tests.yml/badge.svg)

Nova is a password-protected AI assistant built with Python and the Google Gemini API. It started as a command-line chat and now includes a web interface, a tool-using agent, and a workflow engine.

## Features

- Password-protected web interface built with Flask, with saved conversations and an editable system prompt
- Streaming responses, printed as they are generated
- Tool-using agent: Gemini decides when to call a built-in tool
- Built-in tools: calculator, file tools, web search and an API request tool
- Safety layer around tools: read-only flags, confirmation before writes, timeouts and unsafe-URL blocking
- Workflow engine: plans a goal, shows the plan, asks for approval, runs it with retries and saves progress so it can be resumed
- Token usage shown after every reply, plus a session total
- Conversation history saved to `history.json` and loaded on the next run
- Terminal commands: `/clear`, `/history` and `/model`
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

   - `GEMINI_API_KEY` is required. Get a key from Google AI Studio.
   - `NOVA_PASSWORD` protects the web app. Leave it empty to run without a login.
   - `TAVILY_API_KEY` is only needed for the web search tool.
   - Never commit your `.env` file.

## Run

### Terminal chat

        python -m app.chat

Type `exit` to quit, `/clear` to forget the conversation, `/history` to see recent messages, or `/model` to see the model in use.

### Web app

        flask --app web.server run

Open http://127.0.0.1:5000 in your browser. If `NOVA_PASSWORD` is set, the browser asks for a login. Use any username and your password.

## Tools

Nova can call these tools when a request needs them:

- Calculator
- File tools: list, read and write files
- Web search
- API request tool

Tools are checked before they run. Read-only tools run freely, tools that change things ask for confirmation first, every call has a timeout, and the web and API tools refuse unsafe URLs.

## Workflows

Give Nova a goal in plain words. It plans the steps, shows you the plan, and runs nothing until you answer `y`.

        python -m workflows "list the files in my workspace folder"
        python -m workflows --list
        python -m workflows --resume WORKFLOW_ID

Options:

- `--write-tools` lets plans use tools that change things (each write still asks first)
- `--no-critic` skips the extra model review of the plan

Runs are saved in `workflow_data/`, so an interrupted workflow can be resumed.

## Deploy to Render

1. Push the repo to GitHub and create a **Web Service** on Render from it.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn web.server:app --workers 1 --threads 4 --timeout 120`
4. Add the variables from `.env` under **Environment**: at least `GEMINI_API_KEY`, `GEMINI_MODEL` and `NOVA_PASSWORD`. Optionally add `PYTHON_VERSION=3.12.3`.

Note: on Render's free plan the disk is wiped on every restart, so saved conversations are not permanent. The service also sleeps after about 15 minutes without traffic.

## Notes

`.env`, `history.json`, `personality.json` and `workflow_data/` are listed in `.gitignore`, so your keys and conversations are never pushed to GitHub.

## Tests

Install the dev requirements and run the tests:

        pip install -r requirements-dev.txt
        python -m pytest

Tests run on every push with GitHub Actions. They use fake models, so they never call Gemini.

## Roadmap

Planned next: a proper memory layer on PostgreSQL, document search (RAG), and specialized agents.

## License

Apache License 2.0. See [LICENSE](LICENSE).