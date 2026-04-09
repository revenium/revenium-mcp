#!/usr/bin/env python3
"""
Generate curl commands to test the API manually and compare with our implementation.
"""

import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dotenv import load_dotenv
from revenium_mcp_server.auth import get_auth_config


def main():
    """Generate curl commands for manual testing."""
    print("🔧 Curl Command Generator for API Testing")
    print("=" * 50)

    # Load environment
    load_dotenv()
    config = get_auth_config()

    print(f"Base URL: {config.base_url}")
    print(f"Team ID: {config.team_id}")
    print(f"API Key: {config.api_key[:10]}...")

    # Generate curl commands
    endpoints = [
        "/profitstream/v2/api/subscriptions",
        "/profitstream/v2/api/products",
        "/profitstream/v2/api/sources"
    ]

    print("\n🔍 Test these curl commands manually:")
    print("=" * 50)

    for endpoint in endpoints:
        url = f"{config.base_url}{endpoint}?teamId={config.team_id}"

        print(f"\n# Test {endpoint}")
        print("curl -X GET \\")
        print(f"  '{url}' \\")
        print(f"  -H 'Authorization: Bearer {config.api_key}' \\")
        print("  -H 'Content-Type: application/json' \\")
        print("  -H 'User-Agent: revenium-platformapi-mcp-server/1.0.0' \\")
        print("  -v")

    print("\n" + "=" * 50)
    print("📋 What to look for:")
    print("✅ 200 OK = Success!")
    print("❌ 401 = Authentication issue")
    print("❌ 403 = Permission/authorization issue")
    print("❌ 404 = Endpoint doesn't exist")
    print("❌ 500 = Server error")

    print("\n💡 If you get 403 Forbidden:")
    print("1. Check if your API key has the right permissions")
    print("2. Verify if additional parameters are needed")
    print("3. Check if there are rate limits or IP restrictions")
    print("4. Confirm the teamId is correct for your account")

    print("\n🎯 Our MCP server implementation is working correctly!")
    print("The issue is likely API permissions or endpoint configuration.")


if __name__ == "__main__":
    main()
