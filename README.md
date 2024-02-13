# Bambu2OBS

This project aims to integrate Bambu 3D printers with OBS Studio, allowing real-time monitoring and display of printing progress within OBS. It leverages the `pybambu` library for interfacing with Bambu 3D printers and Flask for serving dynamic content.

## Setup and Installation

### Prerequisites

- Python 3.x installed on your system
- OBS Studio for display integration
- InkScape for SVG manipulation

### Setting up a Virtual Environment

It's recommended to use a virtual environment for Python projects to manage dependencies efficiently. Follow these steps to set up and activate a virtual environment:

1. Open a terminal or command prompt.
2. Navigate to your project directory:

    ```bash
    cd path/to/Bambu2OBS
    ```

3. Create a virtual environment named `venv` (or any other name you prefer):

    ```bash
    python -m venv b2obsvenv
    ```

4. Activate the virtual environment:

    - On Windows:

        ```bash
        .\b2obsvenv\Scripts\activate
        ```

    - On macOS and Linux:

        ```bash
        source b2obsvenv/bin/activate
        ```

### Installing Dependencies

With the virtual environment activated, install the required Python packages using:

```bash
pip install -r requirements.txt
```

### Configuration
Copy .env.example to .env and adjust the configuration parameters according to your environment and Bambu 3D printer settings.

### Running the Application
1. Start the Flask server:

    ```bash
    python .\src\bambu2obs.py
    ```

2. Configure OBS Studio to display the progress bar and SVGs by adding browser sources pointing to the Flask server's URLs.
(I will share a OBS Scene dump shortly that you can import to your OWB instance)

### Credits
Greg Hesp for the pybambu library, which facilitates communication with Bambu 3D printers. GitHub repository: pybambu
