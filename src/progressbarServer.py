from flask import Flask, jsonify
from flask_cors import CORS  # Import CORS
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Retrieve BASE_DIR from environment variables
BASE_DIR = os.getenv('BASE_DIR', 'data')  # Provide a default value if not found

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Assuming server.py is located at the root and 'assets' is a subdirectory of the root
# Update the path according to your directory structure if necessary
PROGRESS_FILE_PATH = os.path.join(BASE_DIR, 'progress.txt')

@app.route('/progress')
def get_progress():
    # Try to read the progress value from the file
    try:
        # Check if the progress file exists
        if os.path.exists(PROGRESS_FILE_PATH):
            with open(PROGRESS_FILE_PATH, 'r') as file:
                progress = file.read().strip()  # Read and strip any leading/trailing whitespace
                # Attempt to convert progress to an integer or float as appropriate
                try:
                    progress = float(progress) if '.' in progress else int(progress)
                except ValueError:
                    # If conversion fails, return the raw string
                    pass
                return jsonify({'progress': progress})
        else:
            return jsonify({'progress': "progress.txt not found"})  # Default if no file is found
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Run the Flask app
    # You can specify host='0.0.0.0' if you want your server to be reachable externally
    # Be cautious about security implications of making your server externally accessible
    app.run(debug=True, port=5000)