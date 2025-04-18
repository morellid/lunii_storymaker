"""
Script to generate audio files from text using OpenAI's TTS API.
Handles multiple voices, rate limiting, and error handling.
"""

import json
import os
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

import openai
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Constants
MAX_CHARS_PER_REQUEST = 4096  # OpenAI TTS limit
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 1  # seconds between API calls
OUTPUT_AUDIO_DIR = Path("output/fragments")
OUTPUT_DIR = Path("output")
INPUT_DIR = Path("output/scripts")

class Voice(TypedDict):
    voice: str
    instructions: str

class Fragment(TypedDict):
    voice_name: str
    text: str
    instructions: Optional[str]

class Script(TypedDict):
    voices: Dict[str, Voice]
    fragments: List[Fragment]

def setup_directories() -> None:
    """Create necessary output directories if they don't exist."""
    OUTPUT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_script(script_path: Path) -> Script:
    """Load and validate the input script."""
    with open(script_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def split_long_text(text: str, max_length: int = MAX_CHARS_PER_REQUEST) -> List[str]:
    """Split text into chunks that respect the max length limit."""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    words = text.split()
    
    for word in words:
        if len(current_chunk) + len(word) + 1 <= max_length:
            current_chunk += (" " + word if current_chunk else word)
        else:
            chunks.append(current_chunk)
            current_chunk = word
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks

def generate_audio(
    text: str,
    voice: str,
    instructions: str,
    output_path: Path,
    log_file: List[dict]
) -> bool:
    """Generate audio file using OpenAI's TTS API with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            response = openai.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text
            )
            
            # Save the audio file
            response.stream_to_file(str(output_path))
            
            # Log success
            log_file.append({
                "status": "success",
                "file": str(output_path),
                "attempt": attempt + 1,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
            return True
            
        except Exception as e:
            log_file.append({
                "status": "error",
                "file": str(output_path),
                "attempt": attempt + 1,
                "error": str(e),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            
            if attempt < MAX_RETRIES - 1:
                time.sleep(RATE_LIMIT_DELAY * (attempt + 1))  # Exponential backoff
            
    return False

def process_script(script_path: Path) -> None:
    """Process the entire script and generate audio files."""
    setup_directories()
    script = load_script(script_path)
    
    log_file = []
    errors = []
    
    # Process each fragment
    for idx, fragment in enumerate(tqdm(script["fragments"], desc="Processing fragments")):
        voice_name = fragment["voice_name"]
        voice_config = script["voices"][voice_name]
        
        # Use fragment-specific instructions if available, otherwise use default
        instructions = fragment.get("instructions", voice_config["instructions"])
        
        # Split text if necessary
        text_chunks = split_long_text(fragment["text"])
        
        # Generate audio for each chunk
        for chunk_idx, chunk in enumerate(text_chunks):
            # Determine output filename
            if len(text_chunks) > 1:
                output_file = OUTPUT_AUDIO_DIR / f"fragment_{idx:03d}_{chunk_idx:03d}.wav"
            else:
                output_file = OUTPUT_AUDIO_DIR / f"fragment_{idx:03d}.wav"
            
            # Skip if file already exists
            if output_file.exists():
                log_file.append({
                    "status": "skipped",
                    "file": str(output_file),
                    "reason": "file already exists",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })
                continue
            
            # Generate audio with rate limiting
            time.sleep(RATE_LIMIT_DELAY)
            success = generate_audio(
                text=chunk,
                voice=voice_config["voice"],
                instructions=instructions,
                output_path=output_file,
                log_file=log_file
            )
            
            if not success:
                errors.append({
                    "fragment_index": idx,
                    "chunk_index": chunk_idx if len(text_chunks) > 1 else None,
                    "text": chunk,
                    "voice": voice_name
                })
    
    # Save log and errors
    with open(OUTPUT_DIR / "log.json", 'w', encoding='utf-8') as f:
        json.dump(log_file, f, indent=2)
    
    if errors:
        with open(OUTPUT_DIR / "errors.json", 'w', encoding='utf-8') as f:
            json.dump(errors, f, indent=2)

def main():
    """Main entry point."""
    # Find all JSON files in the input/scripts directory
    script_files = list(INPUT_DIR.glob("*.json"))
    
    if not script_files:
        print("No script files found in input/scripts directory")
        return
    
    for script_file in script_files:
        print(f"Processing {script_file}")
        process_script(script_file)
        print(f"Finished processing {script_file}")

if __name__ == "__main__":
    main() 