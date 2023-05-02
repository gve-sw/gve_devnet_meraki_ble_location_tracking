""" Copyright (c) 2022 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
           https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. 
"""

import datetime
import json
import logging
import os
import sys
import threading
from datetime import datetime
from time import sleep

import meraki
import requests
from dotenv import load_dotenv
from flask import Flask, Response, redirect, render_template, request, url_for
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

# Load all environment variables
load_dotenv()

# REQUIRED CONFIG VALUES:
MERAKI_DASHBOARD_API_KEY = os.getenv("MERAKI_DASHBOARD_API_KEY")
MERAKI_VALIDATION_KEY = os.getenv("MERAKI_VALIDATION_KEY")
MERAKI_LOCATION_DATA_SECRET = os.getenv("MERAKI_LOCATION_DATA_SECRET")
MERAKI_ORG_NAME = os.getenv("MERAKI_ORGANIZATION_NAME")


if (
    not MERAKI_DASHBOARD_API_KEY
    or not MERAKI_VALIDATION_KEY
    or not MERAKI_LOCATION_DATA_SECRET
    or not MERAKI_ORG_NAME
):
    print(
        "Error: Missing one or more env vars: MERAKI_DASHBOARD_API_KEY, MERAKI_LOCATION_DATA_SECRET, MERAKI_ORG_NAME, and/or MERAKI_VALIDATION_KEY."
    )
    print("Please configure these variables & try again.")
    sys.exit(1)

# OPTIONAL CONFIG VALUES
FILTER_BLE_TAGS = os.getenv("MERAKI_FILTER_BLE_TAGS", False)

# If FILTER_BLE_TAGS is True, then BLE_UUID_FILTER must be set
BLE_UUID_FILTER = os.getenv("MERAKI_BLE_UUID_FILTER", "")

SUPPRESS_MERAKI_LOGGING = True
FONT_SIZE = os.getenv("MERAKI_DASHBOARD_FONT_SIZE", 10)

app = Flask(__name__)
dashboard = meraki.DashboardAPI(
    MERAKI_DASHBOARD_API_KEY, suppress_logging=SUPPRESS_MERAKI_LOGGING
)

# Global variables
meraki_networks = {}
network_floorplans = {}
last_meraki_update = "Never"



# Index Page with links to each Meraki Network
@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        hiddenLinks=False,
        networks=meraki_networks,
        last_update=last_meraki_update,
    )


# Display Network Map for specified Meraki network ID
@app.route("/<network_id>", methods=["GET"])
def floorplan(network_id):
    floorplan_list = network_floorplans[network_id]
    return render_template(
        "floorplan.html",
        hiddenLinks=False,
        networks=meraki_networks,
        floorplans=floorplan_list,
    )


# Meraki Scanning API Listener
@app.route("/location_info", methods=["GET", "POST"])
def location_info():
    global last_meraki_update
    # Meraki Dashboard will send location payloads via POST request
    if request.method == "POST":
        # Store Location JSON payload
        location_data = request.json

        print(location_data)
        try:
            # Validate that API Secret configured in Meraki Dashboard
            # matches what is being sent to us.
            if location_data["secret"] == MERAKI_LOCATION_DATA_SECRET:
                # This application was written for version 3.x of the Meraki Scanning API
                # schema, and will not work with prior versions
                if not "3" in location_data["version"]:
                    log.error("Please set API Version to 3.0 in Meraki Dashboard")
                    return Response(
                        '{"error": "API version not 3.x"}',
                        status=400,
                        mimetype="application/json",
                    )
                # Count number of unique BLE tags that were sent in the location payload
                ble_count = len(location_data["data"]["observations"])
                log.info(
                    f"Received location payload from Meraki Dashboard, containing {ble_count} BLE devices"
                )
                # Meraki Dashboard will track the responsiveness of our Scanning API listener
                # If responses take too long, Meraki may assume our listener is dead.
                # So we'll spin off the map updating function to it's own thread &
                # continue on to respond quickly to the POST from Meraki with a 202
                thread = threading.Thread(
                    target=updateMaps, args=(location_data["data"],)
                )
                thread.start()
                # Update 'Last Updated' on main page
                last_meraki_update = datetime.now().strftime(f"%a %b %d %Y, %I:%M%p")
                return Response(status=202)
            else:
                # If API Secret does not match, return 401 & error message
                log.warning("Received bad payload secret from Meraki Dashboard")
                return Response(
                    '{"error": "Incorrect payload secret"}',
                    status=401,
                    mimetype="application/json",
                )
        except TypeError:
            # If we're not able to parse the data payload, return a 400 error
            return Response(
                '{"error": "Wrong data format"}',
                status=400,
                mimetype="application/json",
            )
    else:
        # On first creation of Scanning API POST target, Meraki Cloud will send a GET
        # to validate the correct destination. We must reply with the validation key
        # that Meraki Dashboard provides
        log.info("Got validation request from Meraki Dashboard.")
        return MERAKI_VALIDATION_KEY


# Pre-launch setup
def setup():
    """
    Prep local data prior to spinning up flask web UI
    """
    log.warning("Performing initial setup. Web UI may not be available yet...")
    # Pull down list of Meraki networks & store to build web UI links
    getMerakiNetworks()
    # Pull down original copies of floor plans for each network
    downloadFloorPlans()
    log.warning("Setup Complete! Starting Web UI...")


def updateMaps(ble_data):
    """
    This function takes in a data payload from Meraki Dashboard, which
    contains JSON list of BLE tags, location info, and AP/floorplan info

    In this function, we will open each network floorplan image, then
    update the image with text/icons to show where each AP/BLE tag
    is located. Afterwards, the modified image is saved & sent to the web UI
    """
    # Pull in globals, which contain our dict of Meraki networks & floorplans
    global network_floorplans
    # Since some BLE tags may not have accurate location info, we can still
    # place tags next to nearest AP. So we will store the location info for
    # each AP on the map
    ap_locations = {}
    log.info("Beginning map update...")
    font = ImageFont.truetype("./static/fonts/Roboto-Regular.ttf", FONT_SIZE)
    # Each network ID may contain multiple floormaps, so here we will iterate
    # through each floormap for a given network ID
    for map in network_floorplans[ble_data["networkId"]]:
        log.info(f"Updating {map}")
        # Pull current file name from our floorplan dictionary
        filename = f"{network_floorplans[ble_data['networkId']][map]['filename']}"
        # We will always copy the original, unmodified image to edit.
        # If not, we would be overwriting on top of an already modified image.
        # Modified images start with "ble-", so we can easily strip that here to
        # get the original image name
        source_image = f"./static/floorplans/{filename.split('ble-')[-1]}"
        # Open image file for editing
        with Image.open(source_image) as floorplan:
            # Due to the way Meraki handles x,y coordinates (explained below),
            # We need to pull out the image resolution & floorplan dimensions
            image_w, image_h = floorplan.size
            floorplan_w = network_floorplans[ble_data["networkId"]][map]["width"]
            floorplan_h = network_floorplans[ble_data["networkId"]][map]["height"]
            floorplan = floorplan.convert("RGB")
            draw = ImageDraw.Draw(floorplan)
            # Add APs to map - this will be any AP that has reported a BLE location
            for ap in ble_data["reportingAps"]:
                # Store MAC for if we need to tie a BLE tag to it's nearest AP later
                ap_locations[ap["mac"]] = {}
                # Reporting APs will list ALL APs in the network, so filter out which
                # are not located on the floor we are working on right now
                if ap["floorPlan"]["name"] == map:
                    # Meraki location data x,y values are in meters, but image
                    # is in pixel resolution.
                    # So we divide AP location (meters) by floorplan width/height (meters)
                    # and apply that ratio to image resolution height/width
                    # to get a rough estimate of where the AP is placed on the map
                    width_ratio = ap["floorPlan"]["x"] / floorplan_w
                    height_ratio = ap["floorPlan"]["y"] / floorplan_h
                    ap_x = image_w * width_ratio
                    ap_y = image_h * height_ratio
                    # Store AP x,y for any BLE tags that only report nearest AP
                    ap_locations[ap["mac"]]["x"] = ap_x
                    ap_locations[ap["mac"]]["y"] = ap_y
                    log.info(f"Adding APs to {map}")
                    # We will draw a small square at the exact coordinates, with AP name
                    # written next to it
                    draw.rectangle((ap_x, ap_y, ap_x + 5, ap_y + 5), fill=(35, 58, 235))
                    draw.text(
                        (ap_x + 7, ap_y), str(ap["name"]), (35, 58, 235), font=font
                    )
            # Add BLE tags to map
            # last_offset stores where the last text was placed.
            # So by default, we would move the text 12px underneath
            # the AP name so they don't overlap. Then continue
            # incrementing by 12 for each additional device near that AP
            last_offset = 12
            for device in ble_data["observations"]:
                try:
                    # Not all BLE tag types will advertise a UUID
                    # But if the tag does then we will store it to display
                    device_uuid = device["bleBeacons"][0]["uuid"]
                except KeyError:
                    device_uuid = ""
                except IndexError:
                    device_uuid = ""
                try:
                    bleType = device["bleBeacons"][0]["bleType"]
                except IndexError:
                    bleType = "Unknown"
                # We can optionally filter out tags that don't match a certain UUID
                # So if filtering is enabled, we will check that here
                if FILTER_BLE_TAGS == True and not BLE_UUID_FILTER in device_uuid:
                    log.info("Skipping tag due to UUID filter.")
                    continue
                # Construct text label to be displayed on map image
                ble_label = f"{device['name']} - {bleType}\n{device_uuid}"
                if len(device["locations"]) > 0:
                    # If devices cannot be triangulated, no location info is provided
                    # With Meraki API v3, accurate location info is only provided if the
                    # tag is heard by 3 or more APs.
                    # Otherwise, we will only be told the single nearest AP
                    if device["locations"][0]["floorPlan"]["name"] == map:
                        ble_color = (212, 134, 44)
                        width_ratio = (
                            device["locations"][0]["floorPlan"]["x"] / floorplan_w
                        )
                        height_ratio = (
                            device["locations"][0]["floorPlan"]["y"] / floorplan_h
                        )
                        ble_x = image_w * width_ratio
                        ble_y = image_h * height_ratio
                else:
                    # If no exact location info, place device near closest AP
                    try:
                        # This will only work if the BLE beacon is near an AP on the current floor map
                        # being edited.
                        # We have no way of knowing which map the BLE device is on - since that info is
                        # only provided if accurate location info is known.
                        ble_color = (35, 179, 30)
                        ble_x = (
                            ap_locations[device["latestRecord"]["nearestApMac"]]["x"]
                            + 5
                        )
                        ble_y = (
                            ap_locations[device["latestRecord"]["nearestApMac"]]["y"]
                            + last_offset
                        )
                        last_offset += 12
                    except KeyError:
                        # If we have no x,y then just continue to next device. This may occur if
                        # tag does not have any precise location info (we don't know which map it's on)
                        # but it's also not near any AP on this map
                        continue
                    log.info(
                        f"Adding BLE Device to map: {ble_label} at {ble_x}, {ble_y}"
                    )
                try:
                    # Similar to AP, draw small square at precise location detected (or by nearest AP)
                    # then add label to the right of the square
                    draw.rectangle((ble_x, ble_y, ble_x + 5, ble_y + 5), fill=ble_color)
                    draw.text((ble_x + 7, ble_y), ble_label, ble_color, font=font)
                except UnboundLocalError:
                    # BLE device can only be tied to a map if it contains precise location info
                    # If it doesn't, we use nearest AP MAC.
                    # However, we could be editing a map that doesn't match any of the info
                    # for the device we are trying to place - and therefore the ble_x / ble_y
                    # will never be set. So we catch that here & continue to next device
                    continue
            # Update floorplan dictionary - which will adjust which image gets displayed in web UI
            # If there is already a modified image (one starting with "ble-" prefix), then we
            # will just overwrite & replace it here.
            # Otherwise, use the new prefix for the filename & update our map dictionary
            if not "ble" in filename:
                destination_image = f"./static/floorplans/ble-{filename}"
                network_floorplans[ble_data["networkId"]][map][
                    "filename"
                ] = f"ble-{filename}"
            else:
                destination_image = f"./static/floorplans/{filename}"
            # Save the edited image
            floorplan.save(destination_image)
        # Finally, update the last updated time for all the map images
        now = datetime.now().strftime(f"%a %b %d %Y, %I:%M%p")
        network_floorplans[ble_data["networkId"]][map]["lastupdate"] = now


def getMerakiNetworks():
    """
    This function will just query the Meraki dashboard for all networks
    and store each network ID & name in a global variable
    """
    global meraki_networks
    log.info("Querying list of all Meraki Networks....")
    # Query list of organizations
    orgs = dashboard.organizations.getOrganizations()
    org_id = None
    # Find org by name
    for org in orgs:
        if org["name"] == MERAKI_ORG_NAME:
            org_id = org["id"]
    if not org_id:
        print(f"Error: No Organization found matching name: {MERAKI_ORG_NAME}")
        print(
            "Please check that dashboard matches name specified by env var: MERAKI_ORGANIZATION_NAME"
        )
        sys.exit(1)
    # Query all networks under the first organization we have access to
    networks = dashboard.organizations.getOrganizationNetworks(org_id)
    # Build dictionary of Meraki network ID & name
    meraki_networks = {network["id"]: network["name"] for network in networks}
    log.info(f"Found {len(meraki_networks.keys())} networks!")


def downloadFloorPlans():
    """
    Function to download all Meraki floorplan images for each network in
    the organization.

    All files will be stored to the web-accessible directory:
    ./static/floorplans/
    """
    global network_floorplans
    log.info("Querying & downloading floorplans...")
    # Iterate through each Meraki network to download floorplans
    for network in meraki_networks:
        # We will create a dictionary for each network ID
        # that will contain info we need about that floorplan
        network_floorplans[network] = {}
        # Retrieve floorplan info
        floorplans = dashboard.networks.getNetworkFloorPlans(network)
        for floorplan in floorplans:
            network_name = meraki_networks[network]
            floorplan_url = floorplan["imageUrl"]
            floorplan_name = floorplan["name"]
            img_ext = floorplan["imageExtension"]
            height = floorplan["height"]
            width = floorplan["width"]
            # Build image name for when it is stored locallyt
            download_name = f"{network_name} - {floorplan_name}.{img_ext}"
            # Download image file
            image_file = requests.get(floorplan_url)
            # Write image to floorplan web directory
            with open(f"./static/floorplans/{download_name}", "wb") as img:
                img.write(image_file.content)
            # Assemble dictionary of necessary attributes we will need later
            network_floorplans[network][floorplan_name] = {}
            network_floorplans[network][floorplan_name]["filename"] = download_name
            network_floorplans[network][floorplan_name]["height"] = height
            network_floorplans[network][floorplan_name]["width"] = width
            network_floorplans[network][floorplan_name]["lastupdate"] = "Never"
    log.info("Floorplans downloaded!")



if __name__ == "__main__":
    setup()
    app.run(debug=False, host="0.0.0.0", port=8080)
