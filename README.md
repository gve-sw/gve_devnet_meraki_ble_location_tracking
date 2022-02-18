# Meraki - BLE Location Tracking Dashboard

This code repository contains a proof-of-concept BLE location-tracking dashboard which leverages Meraki's Scanning API.
This dashboard allows for a quick, at-a-glance view of BLE tagged assets across all Meraki networks. This allows for quick, at-a-glance asset tracking without requiring access to Meraki Dashboard.

## Contacts
* Matt Schmitz (mattsc@cisco.com)

## Solution Components
* Meraki MR Access Points with Bluetooth radios
* Meraki Dashboard APIs
* Flask

## Installation/Configuration

**Clone repo:**
```bash
git clone <repo_url>
```

**Install required dependancies:**
```bash
pip install -r requirements.txt
```

**Configure Meraki Dashboard**

1. Log into the Meraki Dashboard & select the desired network.
2. Navigate to **Network Wide > Configure > General > Location and scanning**.
3. Ensure that `Scanning API` is enabled. 
4. Click `Add a POST URL`
5. Add the publicly-reachable URL for this app, with the URL PATH `/location_info` (example: https://\<your domain\>/location_info)
6. Ensure `API Version` is set to `V3` & `Radio Type` is set to `Bluetooth`
7. Optionally: Configure a secret. This will be used by this app to validate incoming POST requests from Meraki Dashboard.


**Configure required variables:**

In the primary application file, `app.py`, there are a few required & optional parameters to configure:
```python
# REQUIRED CONFIG VALUES:
MERAKI_VALIDATION_KEY = ""
MERAKI_LOCATION_DATA_SECRET = ""

# OPTIONAL CONFIG VALUES
FILTER_BLE_TAGS = False
# If FILTER_BLE_TAGS is True, then BLE_UUID_FILTER must be set
BLE_UUID_FILTER = ""
SUPPRESS_MERAKI_LOGGING = True
FONT_SIZE = 10
```

At a minimum, `MERAKI_VALIDATION_KEY` & `MERAKI_LOCATION_DATA_SECRET` must be configured. The validation key is provided by Meraki at the following Dashboard location: **Network Wide > Configure > General > Location and scanning**. The location data secret was optionally configured in `Step 7` of `Configure Meraki Dashboard` above.
 - `MERAKI_VALIDATION_KEY` is used by Meraki cloud to validate the receiver (this app). The first request sent by Meraki Scanning API will be a `GET` & this app must return the same Validation key provided by Meraki Dashboard.
 - `MERAKI_LOCATION_DATA_SECRET` is an optional parameter to validate incoming location data payloads from the Meraki cloud. Each POST from Meraki must contain this value to be considered valid.
 
If you wish to filter out BLE tags by a specific UUID, set `FILTER_BLE_TAGS` to `True`, then add a partial or entire UUID string for `BLE_UUID_FILTER`


## Usage

After all required configuration items are in place, run the application with the following command:

```
python app.py
```

If running the app locally, browse to `http://127.0.0.1:5000`. 

### **Notes on usage**

When Flask recieves the first incoming HTTP request to this URL (whether user generated or from Meraki), it will initiate the setup process. This process queries the Meraki Cloud for all current networks & downloads any floorplan images. These images are all stored locally to be served via the local web UI & are edited to display BLE tags. If you need to refresh map information from Meraki Dashboard, just restart this application & it will complete the setup process again.

Starting with Scanning API v3, Meraki requires a minimum of 3 access points to detect a BLE tag in order to provide accurate location information. If less than 3 access points detect a tag, then the only information provided is the nearest AP. If this occurs, this app will place the BLE tag label by the nearest AP.


# Screenshots

**Example of updated floorplan map with BLE tags:**

![/IMAGES/example_floorplan.png](/IMAGES/example_floorplan.png)



### LICENSE

Provided under Cisco Sample Code License, for details see [LICENSE](LICENSE.md)

### CODE_OF_CONDUCT

Our code of conduct is available [here](CODE_OF_CONDUCT.md)

### CONTRIBUTING

See our contributing guidelines [here](CONTRIBUTING.md)

#### DISCLAIMER:
<b>Please note:</b> This script is meant for demo purposes only. All tools/ scripts in this repo are released for use "AS IS" without any warranties of any kind, including, but not limited to their installation, use, or performance. Any use of these scripts and tools is at your own risk. There is no guarantee that they have been through thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.
You are responsible for reviewing and testing any scripts you run thoroughly before use in any non-testing environment.