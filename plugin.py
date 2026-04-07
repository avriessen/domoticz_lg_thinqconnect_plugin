#!/usr/bin/python3

"""
<plugin key="LG_ThinQ_Connect" name="LG ThinQ Connect" author="avriessen" version="1.0.0" externallink="https://github.com/avriessen/domoticz_lg_thinqconnect_plugin">
    <description>
        <h2>LG ThinQ domoticz plugin</h2><br/>
        Plugin uses LG ThinQ Connect via the <a href="https://github.com/lgtvwebostv/pythinqconnect">pythinqconnect</a> library.<br/><br/>
        Based on the domoticz_lg_thinq_plugin from
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Read unit parameters from LG ThinQ Connect</li>
            <li>Control supported units with LG ThinQ Connect</li>
        </ul>
        <h3>Authentication</h3>
        Configure a country code and a Personal Access Token (PAT). The PAT can be entered directly in the hardware configuration or stored in an <b>LGThinq_PAT.txt</b> file in the plugin directory.
    </description>
    <params>
        <param field="Mode1" label="Device type" width="270px">
            <options>
                <option label="Air Conditioning (AC)" value="type_ac" default="true" />
                <option label="Air to Water Heat Pump (AWHP)" value="type_awhp" default="false" />
            </options>
        </param>
        <param field="Mode2" label="Device ID" width="270px"/>
        <param field="Mode3" label="Country" width="60px" />
        <param field="Mode4" label="Client ID (optional)" width="300px" />
        <param field="Mode5" label="Personal Access Token" width="600px" />
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal" default="true" />
            </options>
        </param>
    </params>
</plugin>
"""

import asyncio
import os
import socket
import sys
import uuid

import Domoticz
from aiohttp import ClientSession

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_PYTHINQCONNECT = os.path.abspath(os.path.join(PLUGIN_DIR, ".", "pythinqconnect"))
if os.path.isdir(LOCAL_PYTHINQCONNECT) and LOCAL_PYTHINQCONNECT not in sys.path:
    sys.path.insert(0, LOCAL_PYTHINQCONNECT)

from thinqconnect.const import DeviceType
from thinqconnect.devices.air_conditioner import AirConditionerDevice
from thinqconnect.devices.const import Property
from thinqconnect.devices.system_boiler import SystemBoilerDevice
from thinqconnect.thinq_api import ThinQApi, ThinQAPIException


class ThinQConfigError(Exception):
    pass


class ThinQDeviceError(Exception):
    pass


class ThinQConnectAdapter:
    PAT_FILE_NAME = "LGThinq_PAT.txt"

    def __init__(self, device_type, device_id, country, client_id, access_token):
        self.device_type = device_type
        self.device_id = device_id
        self.country = (country or "").strip().upper()
        self.client_id = self._build_client_id(client_id)
        self.access_token = self._load_access_token(access_token)
        self.device_info = None
        self.device_profile = None

    def _build_client_id(self, client_id):
        if client_id:
            return client_id.strip()
        else:
            return str(uuid.uuid4())

        hostname = socket.gethostname()
        seed = f"domoticz-lg-thinq:{hostname}:{self.country}:{self.device_id}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))

    def _load_access_token(self, access_token):
        if access_token and access_token.strip():
            return access_token.strip()

        for path in self._candidate_pat_paths():
            if not os.path.isfile(path):
                continue
            with open(path, "r") as handle:
                token = handle.read().strip()
            if token:
                Domoticz.Log(f"LG ThinQ PAT loaded from '{path}'")
                return token

        raise ThinQConfigError(
            "No LG ThinQ Personal Access Token configured. Set 'Personal Access Token' in hardware configuration or create LGThinq_PAT.txt in the plugin directory."
        )

    def _candidate_pat_paths(self):
        return [
            os.path.join(PLUGIN_DIR, self.PAT_FILE_NAME),
            os.path.join(os.getcwd(), self.PAT_FILE_NAME),
            os.path.abspath(os.path.join(PLUGIN_DIR, "..", "pythinqconnect", self.PAT_FILE_NAME)),
        ]

    def _expected_device_type(self):
        if self.device_type == "type_ac":
            return DeviceType.AIR_CONDITIONER
        if self.device_type == "type_awhp":
            return DeviceType.SYSTEM_BOILER
        raise ThinQConfigError(f"Unsupported plugin device type: {self.device_type}")

    def _device_class(self):
        if self.device_type == "type_ac":
            return AirConditionerDevice
        return SystemBoilerDevice

    async def _async_init_metadata(self):
        async with ClientSession() as session:
            api = ThinQApi(
                session=session,
                access_token=self.access_token,
                country_code=self.country,
                client_id=self.client_id,
            )
            device_list = await api.async_get_device_list()
            self.device_info = self._find_device_info(device_list)
            self.device_profile = await api.async_get_device_profile(self.device_id)
            if not self.device_profile:
                raise ThinQDeviceError(f"Could not retrieve profile for device '{self.device_id}'")

    async def _async_ensure_initialized(self):
        if self.device_info is None or self.device_profile is None:
            await self._async_init_metadata()

    def ensure_initialized(self):
        self.run(self._async_ensure_initialized())

    def _find_device_info(self, device_list):
        if not device_list:
            raise ThinQDeviceError("LG ThinQ Connect returned an empty device list.")

        for device in device_list:
            if device.get("deviceId") != self.device_id:
                continue

            info = device.get("deviceInfo", {})
            expected_type = self._expected_device_type()
            actual_type = info.get("deviceType")
            if actual_type != expected_type:
                raise ThinQDeviceError(
                    f"Device '{self.device_id}' has type '{actual_type}', but plugin expects '{expected_type}'."
                )
            return device

        raise ThinQDeviceError("Device not found on your LG ThinQ account. Check the configured device ID.")

    def _create_device(self, api, status=None):
        info = self.device_info.get("deviceInfo", {})
        device_class = self._device_class()
        device = device_class(
            thinq_api=api,
            device_id=self.device_id,
            device_type=info.get("deviceType", ""),
            model_name=info.get("modelName", ""),
            alias=info.get("alias", self.device_id),
            reportable=info.get("reportable", True),
            group_id=self.device_info.get("groupId", ""),
            profile=self.device_profile,
        )
        if status is not None:
            device.set_status(status)
        return device

    async def _async_fetch_device_with_api(self, api):
        status = await api.async_get_device_status(self.device_id)
        if not status:
            raise ThinQDeviceError(f"Could not retrieve status for device '{self.device_id}'")
        return self._create_device(api, status=status)

    async def _async_fetch_device(self):
        await self._async_ensure_initialized()
        async with ClientSession() as session:
            api = ThinQApi(
                session=session,
                access_token=self.access_token,
                country_code=self.country,
                client_id=self.client_id,
            )
            return await self._async_fetch_device_with_api(api)

    async def _async_execute(self, callback):
        await self._async_ensure_initialized()
        async with ClientSession() as session:
            api = ThinQApi(
                session=session,
                access_token=self.access_token,
                country_code=self.country,
                client_id=self.client_id,
            )
            device = await self._async_fetch_device_with_api(api)
            await callback(device)
            return await self._async_fetch_device_with_api(api)

    def fetch_device(self):
        return self.run(self._async_fetch_device())

    def execute(self, callback):
        return self.run(self._async_execute(callback))

    @staticmethod
    def run(coro):
        try:
            return asyncio.run(coro)
        except ThinQAPIException:
            raise
        except Exception:
            raise


class BasePlugin:
    heartbeat_counter = 0

    def __init__(self):
        self.DEVICE_TYPE = ""
        self.DEVICE_ID = ""
        self.COUNTRY = ""
        self.CLIENT_ID = ""
        self.ACCESS_TOKEN = ""
        self.DEBUG = ""

        self.operation = 0
        self.op_mode = ""
        self.target_temp = ""
        self.hot_water_temp = ""
        self.room_temp = ""
        self.in_water_temp = ""
        self.out_water_temp = ""
        self.DHW_water_temp = ""
        self.wind_strength = ""
        self.h_step = False
        self.v_step = False
        self.power_save = 0
        self.on_timer_minutes = "0"
        self.off_timer_minutes = "0"
        self.sleep_timer_minutes = "0"

        self.adapter = None

    def onStart(self):
        self.DEVICE_TYPE = Parameters["Mode1"]
        self.DEVICE_ID = Parameters["Mode2"]
        self.COUNTRY = Parameters["Mode3"]
        self.CLIENT_ID = Parameters["Mode4"]
        self.ACCESS_TOKEN = Parameters["Mode5"]
        self.DEBUG = Parameters["Mode6"]

        if self.DEBUG == "Debug":
            Domoticz.Debugging(1)

        try:
            self.adapter = ThinQConnectAdapter(
                device_type=self.DEVICE_TYPE,
                device_id=self.DEVICE_ID,
                country=self.COUNTRY,
                client_id=self.CLIENT_ID,
                access_token=self.ACCESS_TOKEN,
            )
            device = self.adapter.fetch_device()
        except (ThinQConfigError, ThinQDeviceError, ThinQAPIException) as err:
            Domoticz.Error(str(err))
            return False
        except Exception as err:
            Domoticz.Error(f"Unexpected LG ThinQ Connect initialization error: {err}")
            return False

        if self.DEVICE_TYPE == "type_ac":
            Domoticz.Log("Getting AC status successful.")
            if len(Devices) == 0:
                Domoticz.Device(Name="Operation", Unit=1, Image=23, TypeName="Switch", Used=1).Create()

                mode_options = {
                    "LevelActions": "|||||",
                    "LevelNames": "|Auto|Cool|Heat|Fan|Dry",
                    "LevelOffHidden": "true",
                    "SelectorStyle": "0",
                }
                Domoticz.Device(Name="Mode", Unit=2, TypeName="Selector Switch", Image=16, Options=mode_options, Used=1).Create()
                Domoticz.Device(Name="Target temp", Unit=3, Type=242, Subtype=1, Image=15, Used=1).Create()
                Domoticz.Device(Name="Room temp", Unit=4, TypeName="Temperature", Used=1).Create()

                fan_options = {
                    "LevelActions": "||||",
                    "LevelNames": "|Auto|Low|Medium|High",
                    "LevelOffHidden": "true",
                    "SelectorStyle": "0",
                }
                Domoticz.Device(Name="Fan speed", Unit=5, TypeName="Selector Switch", Image=7, Options=fan_options, Used=1).Create()
                Domoticz.Device(Name="Swing Horizontal", Unit=6, Image=7, TypeName="Switch", Used=1).Create()
                Domoticz.Device(Name="Swing Vertical", Unit=7, Image=7, TypeName="Switch", Used=1).Create()
                Domoticz.Device(Name="Power save", Unit=8, Image=0, TypeName="Switch", Used=1).Create()
                Domoticz.Device(Name="Timer", Unit=9, Image=21, Type=112, SubType=1, Used=1).Create()
                Domoticz.Device(Name="Sleep timer", Unit=10, Image=21, Type=112, SubType=1, Used=1).Create()
                Domoticz.Log("LG ThinQ Connect AC device created.")
            if len(Devices) == 8:
                time_options = {
                    "LevelActions": "|||||||||||||",
                    "LevelNames": "|Off|1 Hour|2 Hours|3 Hours|4 Hours|5 Hours|6 Hours|7 Hours|8 Hours|9 Hours|10 Hours|11 Hours|12 Hours",
                    "LevelOffHidden": "false",
                    "SelectorStyle": "1"
                }
                sleep_options = {
                    "LevelActions": "||||||||",
                    "LevelNames": "|Off|1 Hour|2 Hours|3 Hours|4 Hours|5 Hours|6 Hours|7 Hours",
                    "LevelOffHidden": "false",
                    "SelectorStyle": "1"
                }
                Domoticz.Device(Name="On timer", Unit=9, Image=21, TypeName="Selector Switch", Options=time_options, Used=1).Create()
                Domoticz.Device(Name="Off timer", Unit=10, Image=21, TypeName="Selector Switch", Options=time_options, Used=1).Create()
                Domoticz.Device(Name="Sleep timer", Unit=11, Image=21, TypeName="Selector Switch", Options=sleep_options, Used=1).Create()

        elif self.DEVICE_TYPE == "type_awhp":
            Domoticz.Log("Getting AWHP status successful.")
            if len(Devices) == 0:
                Domoticz.Device(Name="Operation", Unit=1, Image=16, TypeName="Switch", Used=1).Create()

                mode_options = {
                    "LevelActions": "||||",
                    "LevelNames": "|Cool|AI|Heat",
                    "LevelOffHidden": "true",
                    "SelectorStyle": "0",
                }
                Domoticz.Device(Name="Mode", Unit=2, TypeName="Selector Switch", Image=16, Options=mode_options, Used=1).Create()
                Domoticz.Device(Name="Target temp", Unit=3, Type=242, Subtype=1, Image=15, Used=1).Create()
                Domoticz.Device(Name="Hot water temp", Unit=4, Type=242, Subtype=1, Image=15, Used=1).Create()
                Domoticz.Device(Name="Input water temp", Unit=5, TypeName="Temperature", Used=1).Create()
                Domoticz.Device(Name="Output water temp", Unit=6, TypeName="Temperature", Used=1).Create()
                Domoticz.Device(Name="DHW water temp", Unit=7, TypeName="Temperature", Used=1).Create()
                Domoticz.Log("LG ThinQ Connect AWHP device created.")
        else:
            Domoticz.Error("Getting LG device status failed.")
            return False

        self._update_from_device(device)
        self.update_domoticz()
        DumpConfigToLog()
        return True

    def onStop(self):
        Domoticz.Log("onStop called")

    def onConnect(self, Connection, Status, Description):
        pass

    def onMessage(self, Connection, Data):
        pass

    def _run_device_command(self, callback):
        try:
            device = self.adapter.execute(callback)
            self._update_from_device(device)
            self.update_domoticz()
        except (ThinQDeviceError, ThinQAPIException, ValueError) as err:
            Domoticz.Error(str(err))
        except Exception as err:
            Domoticz.Error(f"LG ThinQ Connect command failed: {err}")

    @staticmethod
    def _pick_supported_value(device, property_name, candidates):
        writable_values = device.profiles.get_property(property_name).get("w", [])
        for candidate in candidates:
            if candidate in writable_values:
                return candidate
        for candidate in candidates:
            if device.get_status(property_name) == candidate:
                return candidate
        raise ValueError(f"None of {candidates} are supported for {property_name}")

    @staticmethod
    def _supports_write(device, property_name):
        try:
            return bool(device.profiles.get_property(property_name).get("w"))
        except Exception:
            return False

    def _set_ac_target_temperature(self, device, level):
        temperature = int(level)
        mode = (device.get_status(Property.CURRENT_JOB_MODE) or "").upper()

        if mode == "HEAT" and self._supports_write(device, Property.HEAT_TARGET_TEMPERATURE_C):
            return device.set_heat_target_temperature_c(temperature)
        if mode == "COOL" and self._supports_write(device, Property.COOL_TARGET_TEMPERATURE_C):
            return device.set_cool_target_temperature_c(temperature)
        if mode in ("AI", "ACO", "AUTO") and self._supports_write(device, Property.AUTO_TARGET_TEMPERATURE_C):
            return device.set_auto_target_temperature_c(temperature)
        if self._supports_write(device, Property.TARGET_TEMPERATURE_C):
            return device._set_target_temperature(temperature, "C")

        raise ValueError(f"Target temperature is not writable in mode '{mode or 'UNKNOWN'}'")

    def _get_ac_target_temperature(self, device):
        mode = (device.get_status(Property.CURRENT_JOB_MODE) or "").upper()
        values = []

        if mode == "HEAT":
            values.extend(
                [
                    device.get_status(Property.HEAT_TARGET_TEMPERATURE_C),
                    device.get_status(Property.TWO_SET_HEAT_TARGET_TEMPERATURE_C),
                ]
            )
        elif mode == "COOL":
            values.extend(
                [
                    device.get_status(Property.COOL_TARGET_TEMPERATURE_C),
                    device.get_status(Property.TWO_SET_COOL_TARGET_TEMPERATURE_C),
                ]
            )
        elif mode in ("AI", "ACO", "AUTO"):
            values.append(device.get_status(Property.AUTO_TARGET_TEMPERATURE_C))

        values.append(device.get_status(Property.TARGET_TEMPERATURE_C))

        for value in values:
            if value is not None:
                return value
        return None

    @staticmethod
    def _parse_counter_value(command, level):
        if isinstance(level, int) and level > 0:
            return level
        if isinstance(command, str):
            stripped = command.strip()
            if stripped.isdigit():
                return int(stripped)
        if isinstance(level, int) and level == 0:
            return 0
        raise ValueError(f"Unsupported counter command '{command}' with level '{level}'")

    @staticmethod
    def _minutes_to_hours_minutes(total_minutes):
        total_minutes = max(0, int(total_minutes))
        return total_minutes // 60, total_minutes % 60

    @staticmethod
    def _timer_to_minutes(hours, minutes):
        if hours is None and minutes is None:
            return ""
        return str((hours or 0) * 60 + (minutes or 0))

    def onCommand(self, Unit, Command, Level, Hue):
        if self.adapter is None:
            Domoticz.Error("LG ThinQ Connect adapter is not initialized.")
            return

        if self.DEVICE_TYPE == "type_ac":
            if Unit == 1:
                if Command == "On":
                    self._run_device_command(lambda device: device.set_air_con_operation_mode("POWER_ON"))
                else:
                    self._run_device_command(lambda device: device.set_air_con_operation_mode("POWER_OFF"))

            elif Unit == 2:
                mode_map = {
                    10: ["AI", "ACO", "AUTO"],
                    20: ["COOL"],
                    30: ["HEAT"],
                    40: ["FAN"],
                    50: ["DRY"],
                }
                if Level in mode_map:
                    self._run_device_command(
                        lambda device: device.set_current_job_mode(
                            self._pick_supported_value(device, Property.CURRENT_JOB_MODE, mode_map[Level])
                        )
                    )

            elif Unit == 3:
                self._run_device_command(lambda device: self._set_ac_target_temperature(device, Level))

            elif Unit == 5:
                fan_map = {
                    10: ["AUTO", "NATURE"],
                    20: ["LOW", "LOW_MID", "MID_LOW", "LOWEST"],
                    30: ["MEDIUM", "MID", "MED", "MIDDLE"],
                    40: ["HIGH", "MID_HIGH", "HIGH_MID", "MAX", "POWER"],
                }
                if Level in fan_map:
                    self._run_device_command(
                        lambda device: device.set_wind_strength(
                            self._pick_supported_value(device, Property.WIND_STRENGTH, fan_map[Level])
                        )
                    )

            elif Unit == 6:
                rotate = Command == "On"
                self._run_device_command(lambda device: device.set_wind_rotate_left_right(rotate))

            elif Unit == 7:
                rotate = Command == "On"
                self._run_device_command(lambda device: device.set_wind_rotate_up_down(rotate))

            elif Unit == 8:
                enabled = Command == "On"
                self._run_device_command(lambda device: device.set_power_save_enabled(enabled))

            elif Unit == 9:
                total_minutes = self._selector_to_timer(Level)
                hours, minutes = self._minutes_to_hours_minutes(total_minutes)
                self._run_device_command(lambda device: device.set_relative_time_to_start(hours, minutes))

            elif Unit == 10:
                total_minutes = self._selector_to_timer(Level)
                hours, minutes = self._minutes_to_hours_minutes(total_minutes)
                self._run_device_command(lambda device: device.set_relative_time_to_stop(hours, minutes))

            elif Unit == 11:
                total_minutes = self._selector_to_timer(Level)
                hours, minutes = self._minutes_to_hours_minutes(total_minutes)
                Domoticz.Log(f"Set Sleep timer: {hours}, {minutes} - {Command}, {Level}")
                self._run_device_command(lambda device: device.set_sleep_timer_relative_time_to_stop(hours, minutes))

        elif self.DEVICE_TYPE == "type_awhp":
            if Unit == 1:
                if Command == "On":
                    self._run_device_command(lambda device: device.set_boiler_operation_mode("POWER_ON"))
                else:
                    self._run_device_command(lambda device: device.set_boiler_operation_mode("POWER_OFF"))

            elif Unit == 2:
                mode_map = {
                    10: ["COOL"],
                    20: ["AI", "AUTO"],
                    30: ["HEAT"],
                }
                if Level in mode_map:
                    self._run_device_command(
                        lambda device: device.set_current_job_mode(
                            self._pick_supported_value(device, Property.CURRENT_JOB_MODE, mode_map[Level])
                        )
                    )

            elif Unit == 3:
                def set_target(device):
                    mode = (device.get_status(Property.CURRENT_JOB_MODE) or "").upper()
                    if mode == "COOL":
                        return device.set_room_water_cool_target_temperature_c(int(Level))
                    return device.set_room_water_heat_target_temperature_c(int(Level))

                self._run_device_command(set_target)

            elif Unit == 4:
                self._run_device_command(lambda device: device.set_hot_water_target_temperature_c(int(Level)))

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")

    def onHeartbeat(self):
        if self.adapter is None:
            return

        if self.heartbeat_counter == 0:
            try:
                device = self.adapter.fetch_device()
                self._update_from_device(device)
                self.update_domoticz()
            except (ThinQDeviceError, ThinQAPIException, ValueError) as err:
                Domoticz.Error(str(err))
            except Exception as err:
                Domoticz.Error(f"LG ThinQ Connect heartbeat failed: {err}")

        self.heartbeat_counter += 1
        if self.heartbeat_counter > 5:
            self.heartbeat_counter = 0

    def _update_from_device(self, device):
        if self.DEVICE_TYPE == "type_ac":
            operation = (device.get_status(Property.AIR_CON_OPERATION_MODE) or "").upper()
            self.operation = 0 if operation == "POWER_OFF" else 1
            self.op_mode = (device.get_status(Property.CURRENT_JOB_MODE) or "").upper()
            self.target_temp = self._stringify_temperature(self._get_ac_target_temperature(device))
            self.room_temp = self._stringify_temperature(device.get_status(Property.CURRENT_TEMPERATURE_C))
            self.wind_strength = (device.get_status(Property.WIND_STRENGTH) or "").upper()
            self.h_step = bool(device.get_status(Property.WIND_ROTATE_LEFT_RIGHT))
            self.v_step = bool(device.get_status(Property.WIND_ROTATE_UP_DOWN))
            self.power_save = 1 if device.get_status(Property.POWER_SAVE_ENABLED) else 0
            self.timer_on_minutes = self._timer_to_minutes(
                device.get_status(Property.RELATIVE_HOUR_TO_START),
                device.get_status(Property.RELATIVE_MINUTE_TO_START),
            )
            self.timer_off_minutes = self._timer_to_minutes(
                device.get_status(Property.RELATIVE_HOUR_TO_STOP),
                device.get_status(Property.RELATIVE_MINUTE_TO_STOP),
            )
            self.sleep_timer_minutes = self._timer_to_minutes(
                device.get_status(Property.SLEEP_TIMER_RELATIVE_HOUR_TO_STOP),
                device.get_status(Property.SLEEP_TIMER_RELATIVE_MINUTE_TO_STOP),
            )

        elif self.DEVICE_TYPE == "type_awhp":
            operation = (device.get_status(Property.BOILER_OPERATION_MODE) or "").upper()
            self.operation = 0 if operation == "POWER_OFF" else 1
            self.op_mode = (device.get_status(Property.CURRENT_JOB_MODE) or "").upper()
            self.target_temp = self._stringify_temperature(
                device.get_status(Property.ROOM_TARGET_TEMPERATURE_C)
                or device.get_status(Property.ROOM_WATER_HEAT_TARGET_TEMPERATURE_C)
                or device.get_status(Property.ROOM_WATER_COOL_TARGET_TEMPERATURE_C)
            )
            self.hot_water_temp = self._stringify_temperature(device.get_status(Property.HOT_WATER_TARGET_TEMPERATURE_C))
            self.in_water_temp = self._stringify_temperature(device.get_status(Property.ROOM_IN_WATER_CURRENT_TEMPERATURE_C))
            self.out_water_temp = self._stringify_temperature(device.get_status(Property.ROOM_OUT_WATER_CURRENT_TEMPERATURE_C))
            self.DHW_water_temp = self._stringify_temperature(device.get_status(Property.HOT_WATER_CURRENT_TEMPERATURE_C))

    @staticmethod
    def _stringify_temperature(value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def update_domoticz(self):
        if self.DEVICE_TYPE == "type_ac":
            self._update_switch(1, self.operation)

            mode_level, mode_image = self._ac_mode_to_selector()
            if mode_level is not None and (Devices[2].nValue != self.operation or Devices[2].sValue != mode_level):
                Devices[2].Update(nValue=self.operation, sValue=mode_level, Image=mode_image)

            self._update_setpoint(3, self.target_temp)
            self._update_temperature(4, self.room_temp)

            fan_level = self._fan_speed_to_selector()
            if fan_level is not None and (Devices[5].nValue != self.operation or Devices[5].sValue != fan_level):
                Devices[5].Update(nValue=self.operation, sValue=fan_level)

            self._update_switch(6, 1 if self.h_step else 0)
            self._update_switch(7, 1 if self.v_step else 0)
            self._update_switch(8, self.power_save)
            time_level = self._timer_to_selector(self.on_timer_minutes)
            if time_level is not None and (Devices[9].nValue != self.operation or Devices[9].sValue != fan_level):
                Devices[9].Update(nValue=self.operation, sValue=time_level)
            time_level = self._timer_to_selector(self.off_timer_minutes)
            if time_level is not None and (Devices[10].nValue != self.operation or Devices[10].sValue != fan_level):
                Devices[10].Update(nValue=self.operation, sValue=time_level)
            time_level = self._timer_to_selector(self.sleep_timer_minutes)
            if time_level is not None and (Devices[11].nValue != self.operation or Devices[11].sValue != fan_level):
                Devices[11].Update(nValue=self.operation, sValue=time_level)

        elif self.DEVICE_TYPE == "type_awhp":
            self._update_switch(1, self.operation)

            mode_level, mode_image = self._awhp_mode_to_selector()
            if mode_level is not None and (Devices[2].nValue != self.operation or Devices[2].sValue != mode_level):
                Devices[2].Update(nValue=self.operation, sValue=mode_level, Image=mode_image)

            self._update_setpoint(3, self.target_temp)
            self._update_setpoint(4, self.hot_water_temp)
            self._update_temperature(5, self.in_water_temp)
            self._update_temperature(6, self.out_water_temp)
            self._update_temperature(7, self.DHW_water_temp)

    def _update_switch(self, unit, state):
        s_value = "100" if state else "0"
        if Devices[unit].nValue != state or Devices[unit].sValue != s_value:
            Devices[unit].Update(nValue=state, sValue=s_value)

    def _update_setpoint(self, unit, value):
        if value == "":
            return
        if Devices[unit].nValue != self.operation or Devices[unit].sValue != value:
            Devices[unit].Update(nValue=self.operation, sValue=value)

    def _update_temperature(self, unit, value):
        if value == "":
            return
        if Devices[unit].sValue != value:
            Devices[unit].Update(nValue=0, sValue=value)

    def _update_counter(self, unit, value):
        if value == "":
            return
        if Devices[unit].sValue != value:
            Devices[unit].Update(nValue=0, sValue=value)

    def _ac_mode_to_selector(self):
        mode_map = {
            "AI": ("10", 16),
            "ACO": ("10", 16),
            "AUTO": ("10", 16),
            "COOL": ("20", 16),
            "HEAT": ("30", 15),
            "FAN": ("40", 7),
            "DRY": ("50", 16),
        }
        return mode_map.get(self.op_mode, (None, 16))

    def _awhp_mode_to_selector(self):
        mode_map = {
            "COOL": ("10", 16),
            "AI": ("20", 16),
            "AUTO": ("20", 16),
            "HEAT": ("30", 15),
        }
        return mode_map.get(self.op_mode, (None, 16))

    def _fan_speed_to_selector(self):
        speed_map = {
            "NATURE": "10",
            "AUTO": "10",
            "LOW": "20",
            "LOW_MID": "20",
            "MID_LOW": "20",
            "LOWEST": "20",
            "MID": "30",
            "MED": "30",
            "MIDDLE": "30",
            "MID_HIGH": "40",
            "HIGH_MID": "40",
            "HIGH": "40",
            "MAX": "40",
            "POWER": "40",
        }
        return speed_map.get(self.wind_strength)

    def _timer_to_selector(self, dev_time ):
        if dev_time == '' or dev_time == None:
            return "10"
        time_in_min = int(dev_time)
        if time_in_min == 0:
            return "10"
        if time_in_min <= 60:
            return "20"
        if time_in_min <= 2*60:
            return "30"
        if time_in_min <= 3*60:
            return "40"
        if time_in_min <= 4*60:
            return "50"
        if time_in_min <= 5*60:
            return "60"
        if time_in_min <= 6*60:
            return "70"
        if time_in_min <= 7*60:
            return "80"
        if time_in_min <= 8*60:
            return "90"

    def _selector_to_timer(self, Level):
        selectLevel = int(Level)
        if selectLevel == 10:
            return 0
        newLevel = ((selectLevel/10)-1) * 60
        Domoticz.Log(f"Selector: {Level}, {selectLevel} => {newLevel}")
        return newLevel


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)


def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)


def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)


def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


def DumpConfigToLog():
    for x in Parameters:
        if x == "Mode5" and Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'***'")
        elif Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
