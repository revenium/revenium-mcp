#!/usr/bin/env python3
"""
Test actual Revenium API endpoints to find the correct paths.

Based on the image showing: https://api.revenium.ai/profitstream/v2/api/subscriptions
"""

import asyncio
import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dotenv import load_dotenv
from revenium_mcp_server.client import ReveniumClient


async def test_endpoint(client, endpoint_path, description):
    """Test a specific API endpoint."""
    print(f"\n🔍 Testing: {description}")
    print(f"   Endpoint: {endpoint_path}")
    
    try:
        # Add team ID to params
        params = client._add_team_id_to_params()
        
        response = await client._request("GET", endpoint_path, params=params)
        print(f"✅ SUCCESS! Response keys: {list(response.keys()) if isinstance(response, dict) else 'Non-dict response'}")
        
        # Show a sample of the response (safely)
        if isinstance(response, dict):
            if 'data' in response:
                data_count = len(response['data']) if isinstance(response['data'], list) else 'N/A'
                print(f"   Data items: {data_count}")
            if 'total' in response:
                print(f"   Total: {response['total']}")
        
        return True, response
        
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            print(f"❌ 404 Not Found - endpoint doesn't exist")
        elif "401" in error_msg:
            print(f"❌ 401 Unauthorized - authentication issue")
        elif "403" in error_msg:
            print(f"❌ 403 Forbidden - permission issue")
        elif "500" in error_msg:
            print(f"❌ 500 Server Error - API server issue")
        else:
            print(f"❌ Error: {error_msg}")
        
        return False, None


async def main():
    """Test various API endpoint patterns."""
    print("🔍 Revenium API Endpoint Discovery")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    
    # Test endpoints based on the image you showed
    endpoints_to_test = [
        # Based on your image: https://api.revenium.ai/profitstream/v2/api/subscriptions
        ("/profitstream/v2/api/subscriptions", "Subscriptions (from image)"),
        ("/profitstream/v2/api/products", "Products (profitstream v2)"),
        ("/profitstream/v2/api/sources", "Sources (profitstream v2)"),
        
        # Alternative patterns
        ("/api/v2/subscriptions", "Subscriptions (v2)"),
        ("/api/v2/products", "Products (v2)"),
        ("/api/v2/sources", "Sources (v2)"),
        
        ("/profitstream/v2/api/subscriptions", "Subscriptions (v1)"),
        ("/profitstream/v2/api/products", "Products (v1)"),
        ("/profitstream/v2/api/sources", "Sources (v1)"),
        
        # Root level
        ("/subscriptions", "Subscriptions (root)"),
        ("/products", "Products (root)"),
        ("/sources", "Sources (root)"),
        
        # Health/status endpoints
        ("/health", "Health check"),
        ("/status", "Status check"),
        ("/api/health", "API Health check"),
        ("/profitstream/v2/health", "Profitstream Health"),
    ]
    
    successful_endpoints = []
    
    async with ReveniumClient() as client:
        print(f"🌐 Connected to: {client.base_url}")
        print(f"🔑 Team ID: {client.team_id}")
        
        for endpoint, description in endpoints_to_test:
            success, response = await test_endpoint(client, endpoint, description)
            if success:
                successful_endpoints.append((endpoint, description, response))
    
    print("\n" + "=" * 50)
    print("📊 RESULTS SUMMARY")
    print("=" * 50)
    
    if successful_endpoints:
        print(f"🎉 Found {len(successful_endpoints)} working endpoints:")
        for endpoint, description, response in successful_endpoints:
            print(f"✅ {endpoint} - {description}")
    else:
        print("❌ No working endpoints found.")
        print("\nPossible reasons:")
        print("1. API endpoints use different paths than tested")
        print("2. Authentication method needs adjustment")
        print("3. Additional headers or parameters required")
        print("4. API server configuration issue")
        
        print("\n💡 Suggestions:")
        print("1. Check API documentation for exact endpoint paths")
        print("2. Verify if additional authentication is needed")
        print("3. Test with curl to compare working requests")
    
    return len(successful_endpoints) > 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
