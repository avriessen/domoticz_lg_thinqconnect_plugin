Domoticz LG ThinQ Connect plugin
=====

![alt text](https://raw.githubusercontent.com/avriessen/domoticz_lg_thinqconnect_plugin/main/domoticz.png "LG ThinQ connect plugin in domoticz")

This project is a copy of the original `domoticz_lg_thinq_plugin`, rewritten to use `pythinqconnect` instead of the bundled `wideq` client.  

Supported devices:
	- Air Conditioner
	- System Boiler (Air to Water Heat Pump)

What changed
------------

- Authentication now uses an LG ThinQ Connect Personal Access Token (PAT).
- The plugin talks to the official ThinQ Connect API through `pythinqconnect`.

Requirements
------------

Install the Python dependencies in the Domoticz Python environment:

```commandline
pip install aiohttp awscrt thinqconnect
```

In this repository, the plugin also tries to import `pythinqconnect` from the local sibling directory at `./pythinqconnect`, but the package dependencies still need to be installed in the Domoticz Python environment.

Configuration
-------------

Create the hardware entry in Domoticz with:

- `Device type`: `Air Conditioning (AC)` or `Air to Water Heat Pump (AWHP)`
- `Device ID`: the ThinQ device ID
- `Country`: two-letter country code such as `NL`
- `Client ID (optional)`: leave empty to let the plugin generate a stable UUID
- `Personal Access Token`: PAT from the LG ThinQ Developer portal

Instead of entering the PAT in Domoticz, you can store it in:

```text
domoticz_lg_thinqconnect_plugin/LGThinq_PAT.txt
```

The plugin will also look for the same file in the current working directory and in the sibling `pythinqconnect` directory.

Getting a PAT
-------------

Use the LG ThinQ Developer portal and generate a ThinQ Connect Personal Access Token. The local example under [thinq-api-test/src/main.py](/home/arnoud/Public/LG-dom-plugin/thinq-api-test/src/main.py) shows the same authentication flow this plugin now uses.

Notes
-----

- The plugin keeps the original AC and AWHP device model as close as possible.
- ThinQ Connect exposes horizontal and vertical swing as rotate on/off flags. This plugin therefore uses simple switches for swing control instead of the old multi-position selectors.
- Polling still happens on the Domoticz heartbeat cycle, every 60 seconds.
- The Domoticz runtime plugin in `plugin.py` was migrated.
- The other devices supported by pythinqconnect are not implemented (yet):
	- Air Purifier
	- Ceiling Fan
	- Cook Top
	- De Humidifier
	- Dish Washer
	- Dryer
	- Home Brew
	- Hood
	- Humidifier
	- Kimchi Refrigerator
	- Microwave Oven
	- Oven
	- Plant Cultivator
	- Refrigerator
	- Robot Cleaner
	- Stick Cleaner
	- Styler
	- Ventilator
	- Wash Combo
	- Washer
	- Wash Tower
	- Water Heater
	- Water Purifier
	- Wine Cellar
