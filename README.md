# Script to Podcast Generator

A Python tool that converts text scripts into podcast-ready audio files using OpenAI's text-to-speech API.

## Features

- Convert text scripts to high-quality audio using OpenAI's TTS
- Support for multiple voice options
- Automatic text chunking and processing
- WAV file output format
- Progress tracking and error handling
- Configurable audio parameters

## Project Structure

```
script_to_podcast/
├── requirements.txt    # Project dependencies
├── README.md          # Project documentation
├── .env              # Environment variables (create from .env.example)
├── src/              # Source code
├── tests/            # Test files
├── input/            # Input script files
└── output/           # Generated audio files
```

## Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd script_to_podcast
   ```

2. Create and activate virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env with your OpenAI API key and preferences
   ```

## Development Guidelines

- Follow PEP 8 style guide
- Use type hints
- Write docstrings in Google style
- Maintain test coverage above 80%
- Run tests before committing:
  ```bash
  pytest
  ```

## Code Style

The project uses:
- Black for code formatting
- isort for import sorting
- flake8 for linting

Configure your editor to use these tools or run them manually:
```bash
black .
isort .
flake8
```

## Security

- Never commit API keys or sensitive data
- Always use environment variables for credentials
- Validate all input data
- Implement rate limiting for API calls

