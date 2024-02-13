from dotenv import load_dotenv
import os
import ssl
from pybambu import BambuClient
from pybambu.const import SPEED_PROFILE, FILAMENT_NAMES, CURRENT_STAGE_IDS
import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta
import time
import socket
import requests
import subprocess
import signal
import sys
import xml.etree.ElementTree as ET

# Load environment variables
load_dotenv()

subprocesses = []  # List to keep track of subprocesses

def launch_progress_server():
    """Launches the progress bar server as a separate process."""
    # Use the current Python interpreter to run progressbarServer.py
    proc = subprocess.Popen([sys.executable, 'src/progressbarServer.py'])
    subprocesses.append(proc)

def cleanup_subprocesses():
    """Terminates all running subprocesses initiated by this script."""
    for proc in subprocesses:
        proc.terminate()  # Terminate the subprocess
        proc.wait()       # Wait for the subprocess to exit

# Define the path for the ConnectionDumps.json file in the data subdirectory
DUMPS_FILE_PATH = os.path.join('data', 'ConnectionDumps.json')

# Retrieve environment variables
REGION = os.getenv('REGION')
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')
USERNAME = os.getenv('USERNAME')
PRINTER_SN = os.getenv('PRINTER_SN')
PRINTER_IP = os.getenv('PRINTER_IP')
ACCESS_CODE = os.getenv('ACCESS_CODE')
BASE_DIR = os.getenv('BASE_DIR')

total_layer_num_global = None

class BambuCloud:
    def __init__(self, region: str, email: str, password: str):
        self.region = region
        self.email = email
        self.password = password
        self.auth_token = None

    def _get_authentication_token(self):
        print("Getting accessToken from Bambu Cloud")
        base_url = 'https://api.bambulab.com/v1/user-service/user/login' if self.region != "China" else 'https://api.bambulab.cn/v1/user-service/user/login'
        data = {'account': self.email, 'password': self.password}
        response = requests.post(base_url, json=data, timeout=10)
        if response.ok:
            self.auth_token = response.json()['accessToken']
            print("Authentication successful")
        else:
            raise ValueError(f"Authentication failed with status code {response.status_code}")

    def login(self):
        self._get_authentication_token()

    def get_device_list(self):
        if not self.auth_token:
            raise ValueError("Not authenticated")
        print("Getting device list from Bambu Cloud")
        base_url = 'https://api.bambulab.com/v1/iot-service/api/user/bind' if self.region != "China" else 'https://api.bambulab.cn/v1/iot-service/api/user/bind'
        headers = {'Authorization': f'Bearer {self.auth_token}'}
        response = requests.get(base_url, headers=headers, timeout=10)
        if response.ok:
            devices = response.json()['devices']
            return devices
        else:
            raise ValueError(f"Failed to fetch device list with status code {response.status_code}")

    def get_tasklist(self):
        print("Fetching task list from Bambu Cloud")
        base_url = 'https://api.bambulab.com/v1/user-service/my/tasks' if self.region != "China" else 'https://api.bambulab.cn/v1/user-service/my/tasks'
        headers = {'Authorization': f'Bearer {self.auth_token}'}
        response = requests.get(base_url, headers=headers, timeout=10)
        if response.ok:
            return response.json()
        else:
            raise ValueError(f"Failed to fetch task list with status code {response.status_code}")

    def get_latest_task_for_printer(self, deviceId: str):
        print(f"Fetching latest task for printer with dev_id: {deviceId}")
        tasklist = self.get_tasklist()
        if 'hits' in tasklist:
            for task in tasklist['hits']:
                if task['deviceId'] == deviceId:
                    return task
        return None
        
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR, exist_ok=True)

def get_auth_token(email, password, region):
    print("Getting accessToken from Bambu Cloud")
    # Corrected: Directly use 'region' parameter instead of 'self.region'
    base_url = 'https://api.bambulab.com/v1/user-service/user/login' if region != "China" else 'https://api.bambulab.cn/v1/user-service/user/login'
    data = {'account': email, 'password': password}  # Corrected: Directly use 'email' and 'password' parameters
    response = requests.post(base_url, json=data, timeout=10)
    if response.ok:
        auth_token = response.json()['accessToken']
        print("Authentication successful")
        return auth_token  # Return the obtained token
    else:
        raise ValueError(f"Authentication failed with status code {response.status_code}")
        
def format_remaining_time(minutes):
    """Formats remaining time from minutes to '-HhMm'."""
    hours, minutes = divmod(minutes, 60)
    return f"-{hours}h{minutes}m"

def write_to_file(filename, content):
    """Writes content to a file within the data directory, ensuring numeric content is formatted correctly."""
    try:
        path = os.path.join(BASE_DIR, f"{filename}.txt")
        with open(path, 'w') as file:
            if isinstance(content, (int, float)):
                file.write(f"{content:.2f}")  # Format as float with 2 decimal places
            else:
                file.write(str(content))  # Ensuring content is always treated as a string
        print(f"Updated {filename}.txt with content: {content}")
    except Exception as e:
        print(f"Failed to write to {filename}.txt: {e}")

def load_from_file(file_name, default=None):
    """Utility function to load data from a file, returning a default value if the file does not exist."""
    file_path = os.path.join(BASE_DIR, file_name + '.txt')
    try:
        with open(file_path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default

def hex_to_rgb_percent(hex_color):
    """Convert hex color to an RGB percentage string."""
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f"rgb({r/255*100}%,{g/255*100}%,{b/255*100}%)"

# Helper function to read filament color from file
def read_filament_color_from_file(tray_idx):
    color_file_path = os.path.join(BASE_DIR, f'ams{tray_idx}FilamentColor.txt')
    try:
        with open(color_file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"File {color_file_path} not found.")
        return None

# Helper function to read active ams tray from file
def read_active_ams_tray_from_file():
    amstray_file_path = os.path.join(BASE_DIR, f'activeAmsTray.txt')
    try:
        with open(amstray_file_path, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"File {amstray_file_path} not found.")
        return None
    
# Function to update the SVG with colors for all trays
def update_svg_with_all_tray_colors():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_svg_path = os.path.join(script_dir, "templates", "Filaments.svg")
    active_input_svg_path = os.path.join(script_dir, "templates", "ActiveFilament.svg")
    output_svg_path = os.path.join(script_dir, os.pardir, "data", "Filaments.svg")
    active_output_svg_path = os.path.join(script_dir, os.pardir, "data", "ActiveFilament.svg")
    
    tree = ET.parse(input_svg_path)
    active_tree = ET.parse(active_input_svg_path)
    root = tree.getroot()
    active_root = active_tree.getroot()
    namespaces = {'svg': 'http://www.w3.org/2000/svg'}
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    
    # Correctly read the active tray value from file
    active_ams_tray = int(read_active_ams_tray_from_file())
    
    for tray_idx in range(1, 5):
        filament_color = read_filament_color_from_file(tray_idx)
        rgb_color = hex_to_rgb_percent(filament_color) if filament_color and filament_color != 'N/A' else None
        
        if rgb_color:
            # Update Filaments.svg
            element_id = f'Color{tray_idx}'
            element = root.find(f".//*[@id='{element_id}']", namespaces)
            if element is not None:
                element.set('fill', rgb_color)
            
            # Update ActiveFilament.svg for lines
            for line_part in ['a', 'b', 'c']:
                line_id = f'Line{tray_idx}{line_part}'
                line_element = active_root.find(f".//*[@id='{line_id}']", namespaces)
                if line_element is not None:
                    line_element.set('fill', rgb_color)
                    # Set opacity based on active tray
                    line_element.set('opacity', '0' if tray_idx != active_ams_tray else '1')

        # Set active filament tray by highlighting the corrected numbered circle
        circle_element_id = f'Circle{tray_idx}'
        circle_element = root.find(f".//*[@id='{circle_element_id}']", namespaces)
        if circle_element is not None:
            if tray_idx == active_ams_tray:
                circle_element.set('fill', 'green')  # Active tray
            else:
                circle_element.set('fill', 'gray')  # Inactive trays

    # Update ActiveFilament.svg for Extruder color
    if active_ams_tray:
        active_tray_color = read_filament_color_from_file(active_ams_tray)
        active_rgb_color = hex_to_rgb_percent(active_tray_color) if active_tray_color and active_tray_color != 'N/A' else None
        if active_rgb_color:
            color_element = active_root.find(".//*[@id='Extruder']/*[@id='Color']", namespaces)
            if color_element is not None:
                color_element.set('fill', active_rgb_color)
                color_element.set('opacity', '1')  # Ensure the active tray color is fully opaque
    
    # Save the modified SVGs
    tree.write(output_svg_path, xml_declaration=True, encoding='utf-8')
    active_tree.write(active_output_svg_path, xml_declaration=True, encoding='utf-8')
    print(f"Modified SVG saved as {output_svg_path}")
    print(f"Modified ActiveFilament SVG saved as {active_output_svg_path}")
    
# Load the persisted total_layer_num at script startup
total_layer_num_global = load_from_file("total_layer_num", None)

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(f"device/{PRINTER_SN}/report")

def on_message(client, userdata, msg):
    global total_layer_num_global
    print(" ")
    print(f"Message received -> Topic: {msg.topic} Message: {msg.payload.decode('utf-8')}")
    try:
        message_data = json.loads(msg.payload.decode('utf-8'))

        # Convert numeric values to strings where necessary
        message_data_str = convert_all_to_str(message_data)

        with open(DUMPS_FILE_PATH, 'a') as dumps_file:
            json.dump({"timestamp": datetime.now().isoformat(), "message": message_data_str}, dumps_file, indent=4)
            dumps_file.write('\n')

        if 'print' in message_data_str:
            handle_print_data(message_data_str['print'])
    except Exception as e:
        print(f"Error processing message: {e}")

def convert_all_to_str(data):
    """Recursively convert all values in the dictionary to strings."""
    if isinstance(data, dict):
        return {k: convert_all_to_str(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_all_to_str(v) for v in data]
    else:
        return str(data)

def handle_print_data(print_data):
    global total_layer_num_global
    # Process print profile name
    if 'subtask_name' in print_data:
        write_to_file('printProfile', print_data['subtask_name'])

    # Process print progress
    if 'mc_percent' in print_data:
        write_to_file('progressPercent', f"{print_data['mc_percent']}%")
        write_to_file('progress', print_data['mc_percent'])

    if 'mc_remaining_time' in print_data:
        formatted_time = format_remaining_time(int(print_data['mc_remaining_time']))
        write_to_file('remaining_time', formatted_time)

    # Process cooling fan speed
    if 'cooling_fan_speed' in print_data:
        cooling_fan_speed = float(print_data['cooling_fan_speed'])
        calculated_speed = (cooling_fan_speed / 15) * 100  # Assuming 15 is the max speed for normalization
        write_to_file('coolingFanSpeed', f"{calculated_speed:.2f}")

    # Process print speed level
    if "spd_lvl" in print_data:
        print(f"Received spd_lvl: {print_data['spd_lvl']}")
        print(f"SPEED_PROFILE keys: {list(SPEED_PROFILE.keys())}")

        spd_lvl_value = int(print_data["spd_lvl"])  # Convert spd_lvl to integer
        speed_level_name = SPEED_PROFILE.get(spd_lvl_value, "Unknown Speed Level")

        # Ensure the first letter is uppercase without altering the case of the rest of the string
        speed_level_name = speed_level_name[0].upper() + speed_level_name[1:]

        print(f"Matched speed level name: {speed_level_name}")  # Debug print
        write_to_file('printSpeed', speed_level_name)

    if "mc_print_stage" in print_data:
        print(f"Received mc_print_stage: {print_data['mc_print_stage']}")
        print(f"CURRENT_STAGE_IDS keys: {list(CURRENT_STAGE_IDS.keys())}")

        mc_print_stage_key = str(print_data['mc_print_stage'])
        mc_print_stage_name = CURRENT_STAGE_IDS.get(mc_print_stage_key, "Unknown Print Stage")
        print(f"Matched print stage name: {mc_print_stage_name}")  # Debug print
        write_to_file('printStage', mc_print_stage_name)
        
    # Process layer number
    if "layer_num" in print_data:
        write_to_file("layer_num", print_data['layer_num'])
        layer_overview_content = f"Layer: {print_data['layer_num']} / {total_layer_num_global}"
        write_to_file("layerOverview", layer_overview_content)

    # Process total layer number
    if "total_layer_num" in print_data:
        total_layer_num_global = print_data['total_layer_num']
        write_to_file("total_layer_num", print_data['total_layer_num'])

    # Process temperatures
    if 'bed_temper' in print_data:
        write_to_file('bedTemperature', f"{float(print_data['bed_temper']):.2f}")
    if 'nozzle_temper' in print_data:
        write_to_file('nozzleTemperature', f"{float(print_data['nozzle_temper']):.2f}")

    # Process AMS trays
    if 'ams' in print_data and 'ams' in print_data['ams']:
        for tray in print_data['ams']['ams'][0]['tray']:
            tray_idx = int(tray['id']) + 1  # Adjusting from 0-based to 1-based indexing
            filament_id = tray.get('tray_info_idx', 'Unknown')
            filament_color = tray.get('tray_color', 'N/A')
            filament_name = FILAMENT_NAMES.get(filament_id, "Unknown Filament")
            write_to_file(f'ams{tray_idx}FilamentId', filament_id)
            write_to_file(f'ams{tray_idx}FilamentColor', filament_color)
            write_to_file(f'ams{tray_idx}FilamentName', filament_name)

    # Process active AMS tray
    if 'ams' in print_data and 'tray_now' in print_data['ams']:
        active_tray = int(print_data['ams']['tray_now']) + 1  # Adjusting from 0-based to 1-based indexing
        write_to_file('activeAmsTray', str(active_tray))
        update_svg_with_all_tray_colors()

def process_latest_task(bambu_cloud, printer_sn, base_dir):
    latest_task = bambu_cloud.get_latest_task_for_printer(printer_sn)
    task_id_file_path = os.path.join(base_dir, 'latest_task_id.txt')

    # Read the last processed task ID if exists
    try:
        with open(task_id_file_path, 'r') as file:
            last_processed_task_id = file.read().strip()
    except FileNotFoundError:
        last_processed_task_id = None

    current_task_id = str(latest_task.get('id'))

    # Check if the latest task is already processed
    if current_task_id == last_processed_task_id:
        print("Latest task already processed. No action taken.")
        return

    # Extract required information from the task
    designTitle = latest_task.get('designTitle', 'N/A')
    printProfile = latest_task.get('title', 'N/A')
    printCover = latest_task.get('cover', 'N/A')
    totalWeight = str(latest_task.get('weight', 'N/A'))
    totalTime = int(latest_task.get('costTime', 0))

    # Convert totalTime to HH:MM:SS format
    totalTimeFormatted = str(timedelta(seconds=totalTime))

    # Use the existing function to write extracted information to files
    write_to_file('designTitle', designTitle)
    write_to_file('printProfile', printProfile)
    write_to_file('printCover', printCover)
    write_to_file('totalWeight', totalWeight)
    write_to_file('totalTime', totalTimeFormatted)

    # Download printCover if it has a valid URL
    if printCover != 'N/A':
        cover_response = requests.get(printCover)
        cover_path = os.path.join(base_dir, 'printCover.png')
        with open(cover_path, 'wb') as cover_file:
            cover_file.write(cover_response.content)
        print(f"Downloaded print cover to {cover_path}")

    # Update the last processed task ID
    with open(task_id_file_path, 'w') as file:
        file.write(current_task_id)

    print("Latest task processed successfully.")

def setup_mqtt_listener():
    client = mqtt.Client()
    client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(username="bblp", password=ACCESS_CODE)
    client.connect(PRINTER_IP, 8883, 60)
    return client

def main():
    """
    Main function to initialize Bambu Cloud connection, start progress bar server,
    and handle MQTT messages for Bambu 3D printer status updates.
    """
    print("Initializing Bambu Cloud connection...")
    bambu_cloud = BambuCloud(REGION, EMAIL, PASSWORD)
    bambu_cloud.login()
    print("Bambu Cloud connection initialized.")
    
    server_proc = launch_progress_server()
    print("Progress bar server started.")

    try:
        # Process the latest task from Bambu Cloud, if any
        process_latest_task(bambu_cloud, PRINTER_SN, BASE_DIR)
        print("Latest task processed.")

        # Setup and start MQTT listener for real-time printer status updates
        print("Connecting to the printer's local MQTT service...")
        mqtt_client = setup_mqtt_listener()
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        print("Interrupt received, stopping...")
    except Exception as e:
        print(f"Unhandled exception: {e}")
    finally:
        stop_progressbar_server(server_proc)
        print("Progress bar server stopped.")

if __name__ == "__main__":
    main()
    