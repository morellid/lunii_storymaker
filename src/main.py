"""Main entry point for the script generation functionality."""

import argparse
import os
from script_generator import ScriptGenerator

def main():
    """Main entry point for the script generation."""
    parser = argparse.ArgumentParser(description='Generate voice scripts from text input.')
    parser.add_argument('input_file', help='Path to the input text file')
    parser.add_argument(
        '--output', '-o',
        default='output/scripts/script.json',
        help='Path where to save the generated script (default: output/scripts/script.json)'
    )
    
    args = parser.parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.input_file):
        print(f"Error: Input file '{args.input_file}' not found.")
        return 1
        
    # Read input text
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            input_text = f.read()
    except Exception as e:
        print(f"Error reading input file: {e}")
        return 1
        
    # Generate script
    try:
        generator = ScriptGenerator()
        generator.generate_script(input_text, args.output)
        
        # Verify the generated script
        if generator.verify_script(args.output):
            print(f"Script successfully generated and saved to {args.output}")
            return 0
        else:
            print("Error: Generated script failed verification")
            return 1
            
    except Exception as e:
        print(f"Error generating script: {e}")
        return 1

if __name__ == '__main__':
    exit(main()) 