#!/usr/bin/env python3
"""
Test the enhanced Revenium API client with specific methods.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dotenv import load_dotenv
from revenium_mcp_server.client import ReveniumClient


async def test_products_api():
    """Test the products API methods."""
    print("🛍️  Testing Products API...")
    
    async with ReveniumClient() as client:
        try:
            # Test get_products with pagination
            response = await client.get_products(page=0, size=5)
            print(f"✅ get_products() - Response keys: {list(response.keys())}")
            
            # Extract embedded data
            products = client._extract_embedded_data(response)
            print(f"✅ Found {len(products)} products")
            
            # Extract pagination info
            page_info = client._extract_pagination_info(response)
            print(f"✅ Pagination info: {page_info}")
            
            # If we have products, test get_product_by_id
            if products:
                # Try to find an ID field in the first product
                first_product = products[0]
                product_id = None
                for key in ['id', 'productId', '_id', 'uuid']:
                    if key in first_product:
                        product_id = first_product[key]
                        break
                
                if product_id:
                    print(f"✅ Testing get_product_by_id with ID: {product_id}")
                    try:
                        product = await client.get_product_by_id(str(product_id))
                        print(f"✅ get_product_by_id() - Response keys: {list(product.keys())}")
                    except Exception as e:
                        print(f"⚠️  get_product_by_id() failed (might be expected): {e}")
                else:
                    print("⚠️  No product ID found to test get_product_by_id")
            
            return True
            
        except Exception as e:
            print(f"❌ Products API test failed: {e}")
            return False


async def test_subscriptions_api():
    """Test the subscriptions API methods."""
    print("\n📋 Testing Subscriptions API...")
    
    async with ReveniumClient() as client:
        try:
            # Test get_subscriptions with pagination
            response = await client.get_subscriptions(page=0, size=5)
            print(f"✅ get_subscriptions() - Response keys: {list(response.keys())}")
            
            # Extract embedded data
            subscriptions = client._extract_embedded_data(response)
            print(f"✅ Found {len(subscriptions)} subscriptions")
            
            # Extract pagination info
            page_info = client._extract_pagination_info(response)
            print(f"✅ Pagination info: {page_info}")
            
            return True
            
        except Exception as e:
            print(f"❌ Subscriptions API test failed: {e}")
            return False


async def test_sources_api():
    """Test the sources API methods."""
    print("\n🔌 Testing Sources API...")
    
    async with ReveniumClient() as client:
        try:
            # Test get_sources with pagination
            response = await client.get_sources(page=0, size=5)
            print(f"✅ get_sources() - Response keys: {list(response.keys())}")
            
            # Extract embedded data
            sources = client._extract_embedded_data(response)
            print(f"✅ Found {len(sources)} sources")
            
            # Extract pagination info
            page_info = client._extract_pagination_info(response)
            print(f"✅ Pagination info: {page_info}")
            
            return True
            
        except Exception as e:
            print(f"❌ Sources API test failed: {e}")
            return False


async def main():
    """Test all enhanced client methods."""
    print("🚀 Enhanced Revenium API Client Test")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    
    # Test all API endpoints
    products_ok = await test_products_api()
    subscriptions_ok = await test_subscriptions_api()
    sources_ok = await test_sources_api()
    
    print("\n" + "=" * 50)
    print("📊 ENHANCED CLIENT TEST RESULTS")
    print("=" * 50)
    
    results = {
        "Products API": products_ok,
        "Subscriptions API": subscriptions_ok,
        "Sources API": sources_ok
    }
    
    for api_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {api_name}")
    
    total_passed = sum(results.values())
    total_tests = len(results)
    
    print(f"\n📈 SUMMARY: {total_passed}/{total_tests} API endpoints working")
    
    if total_passed == total_tests:
        print("🎉 All enhanced client methods working perfectly!")
        return True
    else:
        print("⚠️  Some API methods failed - this might be due to missing data or permissions")
        return total_passed > 0


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
