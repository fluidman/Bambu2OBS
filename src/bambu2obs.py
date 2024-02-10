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

# Load environment variables
load_dotenv()

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
    if 'spd_lvl' in print_data:
        spd_lvl_key = str(print_data['spd_lvl'])  # Ensure it's a string
        speed_level_name = SPEED_PROFILE.get(spd_lvl_key, "Unknown Speed Level")
        write_to_file('printSpeed', speed_level_name)

    # Assuming mc_print_stage and mc_print_sub_stage need to be strings
    if 'mc_print_stage' in print_data:
        mc_print_stage_key = str(print_data['mc_print_stage'])
        mc_print_stage_name = CURRENT_STAGE_IDS.get(mc_print_stage_key, "Unknown Print Stage")
        write_to_file('printStage', mc_print_stage_name)
    
    if 'mc_print_sub_stage' in print_data:
        mc_print_sub_stage_key = str(print_data['mc_print_sub_stage'])
        mc_print_sub_stage_name = CURRENT_STAGE_IDS.get(mc_print_sub_stage_key, "Unknown Print Sub Stage")
        write_to_file('printSubStage', mc_print_sub_stage_name)

        
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
    print("Initializing Bambu Cloud connection...")
    bambu_cloud = BambuCloud(REGION, EMAIL, PASSWORD)
    bambu_cloud.login()
    
    process_latest_task(bambu_cloud, PRINTER_SN, BASE_DIR)

    print("Connecting to the printer's local MQTT service...")
    mqtt_client = setup_mqtt_listener()
    try:
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        print("Interrupt received, stopping...")
    except Exception as e:
        print(f"Unhandled exception: {e}")

if __name__ == "__main__":
    main()
