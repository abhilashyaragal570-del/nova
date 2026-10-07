# Nova
![Tests](https://github.com/abhilashyaragal570-del/nova/actions/workflows/tests.yml/badge.svg)

Nova is a password-protected AI assistant built with Python and the Google Gemini API. It started as a command-line chat and now includes a web interface, a tool-using agent, and a workflow engine.

## Features

- Streaming responses, printed as they are generated
- Token usage shown after every reply, plus a session total
- Conversation history saved to `history.json` and loaded on the next run
- `/clear` command to wipe the saved memory
- `/history` command to show your recent messages
- API key and model name kept in a `.env` file
- `/model` command to show which model Nova is using

## Setup

1. Clone the repo and open the folder.

2. Create and activate a virtual environment:

        python -m venv venv
        venv\Scripts\activate

3. Install the dependencies:

        pip install -r requirements.txt

4. Copy `.env.example` to `.env` and put your real key in it. The file looks like this:

        GEMINI_API_KEY=your-key-here
        GEMINI_MODEL=gemini-flash-lite-latest

   Get a key from Google AI Studio. Never commit your `.env` file.

## Run

    python -m app.chat

Type `exit` to quit, `/clear` to forget the conversation, `/history` to see recent messages, or `/model` to see the model in use.

## Notes

`.env` and `history.json` are listed in `.gitignore`, so your key and conversations are never pushed to GitHub.

## Tests

Install the dev requirements and run the tests:

        pip install -r requirements-dev.txt
        python -m pytest

## License

Apache License 2.0. See [LICENSE](LICENSE).
