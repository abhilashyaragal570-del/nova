# Nova

Nova is a small command-line AI chat assistant built with Python and the Google Gemini API.

## Features

- Streaming responses, printed as they are generated
- Token usage shown after every reply, plus a session total
- Conversation history saved to `history.json` and loaded on the next run
- `/clear` command to wipe the saved memory
- API key and model name kept in a `.env` file

## Setup

1. Clone the repo and open the folder.

2. Create and activate a virtual environment:

        python -m venv venv
        venv\Scripts\activate

3. Install the dependencies:

        pip install -r requirements.txt

4. Create a `.env` file in the project root with these two lines:

        GEMINI_API_KEY=your_key_here
        GEMINI_MODEL=gemini-flash-lite-latest

   You can get a key at https://aistudio.google.com/apikey.

## Run

    python -m app.chat

Type `exit` to quit, or `/clear` to forget the conversation.

## Notes

`.env` and `history.json` are listed in `.gitignore`, so your key and conversations are never pushed to GitHub.
