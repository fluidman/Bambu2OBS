from flask import Flask, jsonify, Response, send_from_directory, render_template_string
from werkzeug.utils import secure_filename, safe_join
from flask_cors import CORS
import os
import time
from dotenv import load_dotenv
from threading import Thread
import datetime

# Load environment variables
load_dotenv()

BASE_DIR = os.getenv('BASE_DIR', 'data')
SVG_FILES = ['Filaments.svg', 'ActiveFilament.svg']

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

PROGRESS_FILE_PATH = os.path.join(BASE_DIR, 'progress.txt')
SVG_DIR = os.path.join(BASE_DIR)  # Assuming SVG files are stored in the BASE_DIR

def file_watcher(filename, last_known_stamp=0):
    """
    Generator function to watch for file changes.
    """
    while True:
        try:
            stat = os.stat(os.path.join(SVG_DIR, filename))
            if stat.st_mtime != last_known_stamp:
                last_known_stamp = stat.st_mtime
                yield f"data: update\n\n"
        except FileNotFoundError:
            pass
        time.sleep(1)

@app.route('/progress')
def get_progress():
    try:
        if os.path.exists(PROGRESS_FILE_PATH):
            with open(PROGRESS_FILE_PATH, 'r') as file:
                progress = file.read().strip()
                try:
                    progress = float(progress) if '.' in progress else int(progress)
                except ValueError:
                    pass
                return jsonify({'progress': progress})
        else:
            return jsonify({'progress': "progress.txt not found"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/updates/<filename>')
def updates(filename):
    if filename in SVG_FILES:
        return Response(file_watcher(filename), content_type='text/event-stream')
    return "File not found", 404

@app.route('/svg/<filename>')
def serve_svg(filename):
    filename = secure_filename(filename)
    filepath = safe_join(SVG_DIR, filename)
    print(f"Attempting to serve: {filepath}")  # Debug print
    if os.path.exists(filepath):
        print("File found, serving...")  # Debug print
        return send_from_directory(SVG_DIR, filename)
    else:
        app.logger.error(f"File not found: {filepath}")
        return "File not found", 404
    
@app.route('/view/<filename>')
def view_svg(filename):
    if filename in SVG_FILES:
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>SVG Viewer - {filename}</title>
        </head>
        <body>
            <img src="/svg/{filename}" id="svgImage">
            <script>
                const evtSource = new EventSource("/updates/{filename}");
                evtSource.onmessage = function(event) {{
                    const img = document.getElementById('svgImage');
                    const src = img.src.split('?')[0];
                    img.src = `${{src}}?t=${{new Date().getTime()}}`;
                }};
            </script>
        </body>
        </html>
        """
        return render_template_string(html)
    return "File not found", 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
