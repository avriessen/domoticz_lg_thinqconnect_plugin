import asyncio
import uuid
import json
from aiohttp import ClientSession
from thinqconnect.thinq_api import ThinQApi

client_id = str(uuid.uuid4())
token = ""
country = ""

with open("LGThinq_PAT.txt", "r") as handle:
    lines = handle.read().split("\n")
    token = lines[0].strip()
    country = lines[1].strip()

async def test_devices_list():
    async with ClientSession() as session:
        thinq_api = ThinQApi(session=session, access_token=token, country_code=country, client_id=client_id)
        response = await thinq_api.async_get_device_list()
        print("Device List:")
        jsonStr = json.dumps(response, indent=2, ensure_ascii=False, sort_keys=True)
        printStr = jsonStr.replace('\"', '').replace('[\n','').replace(']','').replace('{','').replace('}\n','').replace(',','').replace('}','')
        print(printStr)

asyncio.run(test_devices_list())
