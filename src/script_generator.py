"""Script generator module for transforming text into voice scripts.

This module handles the transformation of plain text into structured scripts
that can be used by text-to-voice functionality.
"""

import json
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
import openai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class Voice:
    """Represents a voice configuration."""
    voice: str  # OpenAI voice name
    instructions: str  # Default instructions for this voice

@dataclass
class Fragment:
    """Represents a text fragment to be spoken."""
    voice_name: str
    text: str
    instructions: Optional[str] = None

@dataclass
class Script:
    """Represents a complete script with voices and fragments."""
    voices: Dict[str, Voice]
    fragments: List[Fragment]

    def to_dict(self) -> dict:
        """Convert the script to a dictionary format."""
        return {
            "voices": {
                name: {"voice": v.voice, "instructions": v.instructions}
                for name, v in self.voices.items()
            },
            "fragments": [
                {
                    "voice_name": f.voice_name,
                    "text": f.text,
                    **({"instructions": f.instructions} if f.instructions else {})
                }
                for f in self.fragments
            ]
        }

class ScriptGenerator:
    """Handles the generation of scripts from input text."""
    
    def __init__(self):
        """Initialize the script generator."""
        self.client = openai.OpenAI()
        
    def _get_script_structure(self, text: str) -> Script:
        """Use OpenAI to analyze the text and create a structured script.
        
        This method sends the text to OpenAI to:
        1. Identify different voices/characters
        2. Split text into appropriate fragments
        3. Add emotional instructions where needed
        """
        system_prompt = """You are an expert at analyzing text and creating structured scripts for voice narration.
        Your task is to:
        1. Identify the different voices/characters in the text
        2. Split the text into appropriate fragments for each voice
        3. Add emotional instructions where needed to convey the right tone
        
        For each voice, provide:
        - A suitable OpenAI voice name (alloy, echo, fable, onyx, nova, or shimmer)
        - Default instructions for that voice's general character
        
        For each fragment:
        - Assign the appropriate voice
        - Include specific instructions only if they differ from the voice's default
        """
        
        user_prompt = f"""Analyze this text and create a script structure:

{text}

Respond with a JSON object that follows this exact schema:
{{
    "voices": {{
        "voice_name": {{
            "voice": "name of the openai voice",
            "instructions": "instructions for the openai TTS endpoint"
        }}
    }},
    "fragments": [
        {{
            "voice_name": "voice",
            "text": "text",
            "instructions": "optional additional instructions"
        }}
    ]
}}"""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Convert the JSON response to our Script class
        voices = {
            name: Voice(**details)
            for name, details in result["voices"].items()
        }
        
        fragments = [Fragment(**f) for f in result["fragments"]]
        
        return Script(voices=voices, fragments=fragments)

    def generate_script(self, input_text: str, output_path: str) -> None:
        """Generate a script from input text and save it to a file.
        
        Args:
            input_text: The input text to convert into a script
            output_path: Path where to save the generated script
        """
        # Generate the script structure
        script = self._get_script_structure(input_text)
        
        # Convert to dictionary format
        script_dict = script.to_dict()
        
        # Ensure the output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save the script
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(script_dict, f, indent=2, ensure_ascii=False)

    def verify_script(self, script_path: str) -> bool:
        """Verify that a generated script follows the expected schema.
        
        Args:
            script_path: Path to the script file to verify
            
        Returns:
            bool: True if the script is valid, False otherwise
        """
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                script_data = json.load(f)
            
            # Check basic structure
            if not isinstance(script_data, dict):
                return False
            if 'voices' not in script_data or 'fragments' not in script_data:
                return False
                
            # Verify voices
            if not isinstance(script_data['voices'], dict):
                return False
            for voice_name, voice_data in script_data['voices'].items():
                if not isinstance(voice_data, dict):
                    return False
                if 'voice' not in voice_data or 'instructions' not in voice_data:
                    return False
                    
            # Verify fragments
            if not isinstance(script_data['fragments'], list):
                return False
            for fragment in script_data['fragments']:
                if not isinstance(fragment, dict):
                    return False
                if 'voice_name' not in fragment or 'text' not in fragment:
                    return False
                if fragment['voice_name'] not in script_data['voices']:
                    return False
                    
            return True
            
        except (json.JSONDecodeError, FileNotFoundError):
            return False 