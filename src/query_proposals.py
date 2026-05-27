import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.abspath('.'))
load_dotenv('.env')

async def main():
    from src.infra.db import get_supabase
    client = await get_supabase()
    
    # Query aria_proposals
    try:
        res = await client.table("aria_proposals").select("*").order("created_at", desc=True).limit(10).execute()
        print(f"Found {len(res.data)} proposals:")
        for idx, prop in enumerate(res.data):
            print(f"--- Proposal {idx+1} ---")
            print(f"ID: {prop.get('id')}")
            print(f"Created At: {prop.get('created_at')}")
            print(f"Product ID: {prop.get('product_id')}")
            print(f"Product Name: {prop.get('product_name')}")
            print(f"Quantity: {prop.get('quantity')}")
            print(f"Supplier ID: {prop.get('supplier_id')}")
            print(f"Status: {prop.get('status')}")
            print(f"Justification: {prop.get('justification')}")
    except Exception as e:
        print("Error querying aria_proposals:", e)

if __name__ == "__main__":
    asyncio.run(main())
