import os, httpx, asyncio
from dotenv import load_dotenv
load_dotenv('../.env')

async def test():
    wc_url = os.environ.get('WOOCOMMERCE_API_URL')
    wc_key = os.environ.get('WOOCOMMERCE_API_KEY')
    wc_secret = os.environ.get('WOOCOMMERCE_API_SECRET')
    resp = await httpx.AsyncClient().get(
        f'{wc_url}/wp-json/wc/v3/orders',
        auth=(wc_key, wc_secret),
        params={"per_page": 100, "orderby": "date", "order": "desc"}
    )
    orders = resp.json()

    upserts = []
    for o in orders:
        upserts.append({
            "id": o["id"],
            "status": o["status"],
            "total": float(o["total"]),
            "currency": o["currency"],
            "customer_name": f"{o['billing']['first_name']} {o['billing']['last_name']}".strip(),
            "date_created": o["date_created"],
            "line_items": o["line_items"]
        })

    import sys
    sys.path.append(os.path.abspath('..'))
    from src.infra.db import get_supabase
    
    try:
        client = await get_supabase()
        res = await client.table("wc_orders_cache").upsert(upserts).execute()
        print("UPSERT SUCCESS:", len(res.data))
    except Exception as e:
        print("UPSERT EXCEPTION:", repr(e))
        import traceback
        traceback.print_exc()

asyncio.run(test())
