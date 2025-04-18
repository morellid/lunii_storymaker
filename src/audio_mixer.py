import os
import re
from pathlib import Path
from typing import List, Tuple
from pydub import AudioSegment
import json
from datetime import datetime

class AudioMixer:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.fragments_dir = self.output_dir / "fragments"
        self.mixdown_dir = self.output_dir / "mixdown"
        self.log_file = self.output_dir / "log.json"
        
        # Create mixdown directory if it doesn't exist
        self.mixdown_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_fragment_files(self) -> List[Path]:
        """Get all fragment files and sort them by their index numbers."""
        fragment_files = []
        for file in self.fragments_dir.glob("fragment_*.wav"):
            # Extract indices from filename
            match = re.match(r"fragment_(\d+)(?:_(\d+))?\.wav", file.name)
            if match:
                main_idx = int(match.group(1))
                sub_idx = int(match.group(2)) if match.group(2) else 0
                fragment_files.append((main_idx, sub_idx, file))
        
        # Sort by main index first, then sub index
        return [f[2] for f in sorted(fragment_files, key=lambda x: (x[0], x[1]))]
    
    def _load_log(self) -> List[dict]:
        """Load existing log or create new one."""
        if self.log_file.exists():
            with open(self.log_file, 'r') as f:
                return json.load(f)
        return []
    
    def _append_log(self, log_entry: dict) -> None:
        """Append a new entry to the log file."""
        logs = self._load_log()
        logs.append(log_entry)
        with open(self.log_file, 'w') as f:
            json.dump(logs, f, indent=2)
    
    def _read_audio_file(self, file_path: Path) -> AudioSegment:
        """Read an audio file using pydub's format detection."""
        try:
            # Try to read the file directly
            return AudioSegment.from_file(str(file_path))
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            raise
    
    def create_mixdown(self, padding_seconds: float = 2.0, normalize_db: float = -3.0) -> None:
        """Create a mixdown of all fragment files."""
        try:
            # Get and sort fragment files
            fragment_files = self._get_fragment_files()
            if not fragment_files:
                raise ValueError("No fragment files found")
            
            # Start with silence for padding
            mixdown = AudioSegment.silent(duration=int(padding_seconds * 1000))
            
            # Concatenate all fragments
            for file in fragment_files:
                try:
                    segment = self._read_audio_file(file)
                    mixdown += segment
                except Exception as e:
                    print(f"Error processing {file}: {e}")
                    raise
            
            # Add ending padding
            mixdown += AudioSegment.silent(duration=int(padding_seconds * 1000))
            
            # Normalize to target dB
            mixdown = mixdown.normalize(headroom=normalize_db)
            
            # Save the mixdown
            output_file = self.mixdown_dir / "mixdown.wav"
            mixdown.export(output_file, format="wav")
            
            # Log success
            self._append_log({
                "timestamp": datetime.now().isoformat(),
                "action": "mixdown_created",
                "status": "success",
                "output_file": str(output_file),
                "fragments_used": len(fragment_files)
            })
            
            print(f"Mixdown created successfully at {output_file}")
            
        except Exception as e:
            # Log error
            self._append_log({
                "timestamp": datetime.now().isoformat(),
                "action": "mixdown_created",
                "status": "error",
                "error": str(e)
            })
            print(f"Error creating mixdown: {e}")
            raise

if __name__ == "__main__":
    mixer = AudioMixer()
    mixer.create_mixdown() 