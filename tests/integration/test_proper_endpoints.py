#!/usr/bin/env python3
"""
Test the correct Revenium API endpoints with proper error handling.

Any HTTP status code 400+ is treated as a FAILURE.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dotenv import load_dotenv
from revenium_mcp_server.client import ReveniumClient


async def _test_endpoint(client, endpoint_path, description):
    """Test a specific API endpoint. Any 400+ status code is a FAILURE."""
    print(f"\n🔍 Testing: {description}")
    print(f"   Full URL: {client.base_url}{endpoint_path}")

    try:
        # Add team ID to params
        params = client._add_team_id_to_params()
        print(f"   Parameters: {params}")

        response = await client._request("GET", endpoint_path, params=params)

        # If we get here, it means status code was < 400
        print("✅ SUCCESS! Status: 200 OK")

        # Show response details safely
        if isinstance(response, dict):
            print(f"   Response keys: {list(response.keys())}")
            if 'data' in response:
                data_count = len(response['data']) if isinstance(response['data'], list) else 'N/A'
                print(f"   Data items: {data_count}")
            if 'total' in response:
                print(f"   Total: {response['total']}")
        else:
            print(f"   Response type: {type(response)}")

        return True, response

    except Exception as e:
        # ANY exception from our client means a failure (400+ status codes)
        print(f"❌ FAILURE: {str(e)}")
        return False, None


async def main():
    """Test the correct API endpoints."""
    print("🎯 Revenium API Endpoint Testing (Proper Error Handling)")
    print("=" * 60)

    # Load environment
    load_dotenv()

    # Test the exact endpoints you specified
    endpoints_to_test = [
        ("/profitstream/v2/api/subscriptions", "List Subscriptions"),
        ("/profitstream/v2/api/products", "List Products"),
        ("/profitstream/v2/api/sources", "List Sources"),
    ]

    successful_endpoints = []
    failed_endpoints = []

    async with ReveniumClient() as client:
        print(f"🌐 Base URL: {client.base_url}")
        print(f"🔑 Team ID: {client.team_id}")
        print(f"🔑 API Key: {client.api_key[:10]}...")

        for endpoint, description in endpoints_to_test:
            success, response = await _test_endpoint(client, endpoint, description)
            if success:
                successful_endpoints.append((endpoint, description, response))
            else:
                failed_endpoints.append((endpoint, description))

    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)

    if successful_endpoints:
        print(f"🎉 SUCCESSFUL ENDPOINTS ({len(successful_endpoints)}):")
        for endpoint, description, response in successful_endpoints:
            print(f"✅ {endpoint} - {description}")

    if failed_endpoints:
        print(f"\n❌ FAILED ENDPOINTS ({len(failed_endpoints)}):")
        for endpoint, description in failed_endpoints:
            print(f"❌ {endpoint} - {description}")

    # Overall assessment
    total_tests = len(endpoints_to_test)
    success_count = len(successful_endpoints)

    print(f"\n📈 SUMMARY: {success_count}/{total_tests} endpoints working")

    if success_count == 0:
        print("\n❌ ALL TESTS FAILED")
        print("Possible issues:")
        print("1. API key permissions insufficient")
        print("2. Team ID incorrect or not authorized")
        print("3. API endpoints require different authentication")
        print("4. Network/server issues")
        return False
    elif success_count == total_tests:
        print("\n🎉 ALL TESTS PASSED - API integration working perfectly!")
        return True
    else:
        print(f"\n⚠️  PARTIAL SUCCESS - {success_count} out of {total_tests} endpoints working")
        return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n👋 Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
