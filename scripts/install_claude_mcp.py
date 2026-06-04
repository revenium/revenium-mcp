#!/usr/bin/env python3
"""
Revenium MCP Server Installer for Claude Desktop
Automatically installs and configures the MCP server for Claude Desktop.
"""

import json
import sys
import subprocess
from pathlib import Path

def get_python_path():
    """Get the full path to the current Python executable."""
    return sys.executable

def get_claude_config_path():
    """Get the Claude Desktop configuration file path."""
    home = Path.home()
    config_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return config_path

def install_dependencies():
    """Install required Python dependencies."""
    print("📦 Installing Python dependencies...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def create_claude_config(server_path, python_path):
    """Create or update Claude Desktop configuration."""
    config_path = get_claude_config_path()
    
    # Create directory if it doesn't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing config or create new one
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)
    else:
        config = {"mcpServers": {}}
    
    # Ensure mcpServers exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    
    # Add our server configuration
    config["mcpServers"]["revenium-platform"] = {
        "command": python_path,
        "args": [str(server_path / "run_server_dev.py")],
        "env": {
            "PYTHONPATH": str(server_path / "src"),
            "UCM_WARNINGS_ENABLED": "false",
            "NO_COLOR": "1"
        }
    }
    
    # Write configuration
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"✅ Claude Desktop configuration updated: {config_path}")
    return True

def prompt_for_api_credentials():
    """Prompt user for API credentials and add them to config."""
    config_path = get_claude_config_path()
    
    print("\n🔑 API Credentials Setup (Optional)")
    print("Enter your Revenium API credentials, or press Enter to skip:")
    
    api_key = input("API Key: ").strip()
    if not api_key:
        print("⏭️  Skipping API credentials - you can add them later")
        return
    
    base_url = input("Base URL (default: https://api.revenium.ai): ").strip()
    if not base_url:
        base_url = "https://api.revenium.ai"
    
    # Update config with credentials
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    config["mcpServers"]["revenium-platform"]["env"].update({
        "REVENIUM_API_KEY": api_key,
        "REVENIUM_BASE_URL": base_url
    })
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print("✅ API credentials added to configuration")

def main():
    """Main installer function."""
    print("🚀 Revenium MCP Server Installer for Claude Desktop")
    print("=" * 60)
    
    # Get current directory (should be the repo root)
    server_path = Path(__file__).parent.absolute()
    python_path = get_python_path()
    
    print(f"📂 Server path: {server_path}")
    print(f"🐍 Python path: {python_path}")
    
    # Check if we're in the right directory
    if not (server_path / "requirements.txt").exists():
        print("❌ Error: requirements.txt not found. Please run this script from the repo root.")
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies():
        sys.exit(1)
    
    # Create Claude configuration
    if not create_claude_config(server_path, python_path):
        sys.exit(1)
    
    # Prompt for API credentials
    prompt_for_api_credentials()
    
    print("\n" + "=" * 60)
    print("🎉 Installation Complete!")
    print("\nNext steps:")
    print("1. Restart Claude Desktop")
    print("2. The 'revenium-platform' MCP server should appear in Claude")
    print("3. You can modify API credentials in:")
    print(f"   {get_claude_config_path()}")
    print("\n💡 Tip: If you see any issues, check the logs at:")
    print("   ~/Library/Logs/Claude/mcp-server-revenium-platform.log")

if __name__ == "__main__":
    main()
