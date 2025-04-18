# Lunii Story Maker - Script Generation

This tool helps transform text stories into structured scripts that can be used for text-to-voice generation.

## Features

- Automatically identifies different voices/characters in the text
- Splits text into appropriate fragments for each voice
- Adds emotional instructions where needed
- Generates a structured JSON output that can be used by text-to-voice functionality
- Verifies the generated script for correctness

## Prerequisites

- Python 3.8 or higher
- OpenAI API key

## Installation

1. Clone this repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and add your OpenAI API key:
   ```
   OPENAI_API_KEY=your_api_key_here
   ```

## Usage

1. Create a text file with your story (e.g., `story.txt`)

2. Run the script generator:
   ```bash
   python src/main.py story.txt
   ```
   
   By default, the script will be saved to `output/scripts/script.json`. You can specify a different output path using the `-o` option:
   ```bash
   python src/main.py story.txt -o my_script.json
   ```

## Output Format

The generated script will be a JSON file with the following structure:

```json
{
    "voices": {
        "voice_name": {
            "voice": "name of the openai voice",
            "instructions": "instructions for the openai TTS endpoint"
        }
    },
    "fragments": [
        {
            "voice_name": "voice",
            "text": "text",
            "instructions": "optional additional instructions"
        }
    ]
}
```

- `voices`: Defines the available voices and their default instructions
- `fragments`: Contains the text fragments to be spoken, with their assigned voices and optional specific instructions

## OpenAI Voices

The script generator will automatically assign appropriate OpenAI voices to characters. Available voices are:
- alloy
- echo
- fable
- onyx
- nova
- shimmer

## Error Handling

The script includes various error checks:
- Validates input file existence and readability
- Verifies the generated script structure
- Handles OpenAI API errors gracefully

If any errors occur, they will be printed to the console with appropriate error messages.

## Contributing

Feel free to open issues or submit pull requests for any improvements or bug fixes.

## License

[Your chosen license]

