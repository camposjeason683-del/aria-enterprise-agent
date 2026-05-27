import os, httpx, asyncio
from dotenv import load_dotenv
load_dotenv('../.env')

async def test():
    wc_url = os.environ.get('WOOCOMMERCE_API_URL')
    wc_key = os.environ.get('WOOCOMMERCE_API_KEY')
    wc_secret = os.environ.get('WOOCOMMERCE_API_SECRET')
    print(f'Fetching {wc_url}')
    try:
        resp = await httpx.AsyncClient().get(f'{wc_url}/wp-json/wc/v3/orders', auth=(wc_key, wc_secret))
        print('STATUS:', resp.status_code)
        print('BODY:', resp.text[:200])
    except Exception as e:
        print('EXCEPTION:', repr(e))

asyncio.run(test())
