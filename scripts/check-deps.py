#!/usr/bin/env python3
"""Quick dependency checker for Revenium Platform API MCP Server.

This script checks if all required dependencies are installed and provides
quick fixes for missing dependencies.
"""

import sys
import subprocess
import importlib.util

# Critical dependencies that must be present for the server to start
CRITICAL_DEPS = {
    'fastmcp': 'fastmcp>=2.8.0',
    'loguru': 'loguru>=0.7.0', 
    'httpx': 'httpx>=0.28.1',
    'pydantic': 'pydantic>=2.7.2',
    'dotenv': 'python-dotenv>=1.0.0',
    'mcp': 'mcp>=1.9.2'
}

def check_dependency(module_name):
    """Check if a module can be imported."""
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except ImportError:
        return False

def install_dependency(package_name):
    """Install a dependency using pip."""
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package_name])
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    """Check dependencies and install missing ones."""
    print("🔍 Checking Revenium MCP Server dependencies...")
    
    missing_deps = []
    
    # Check each critical dependency
    for module_name, package_name in CRITICAL_DEPS.items():
        if check_dependency(module_name):
            print(f"  ✅ {module_name} - OK")
        else:
            print(f"  ❌ {module_name} - MISSING")
            missing_deps.append((module_name, package_name))
    
    if not missing_deps:
        print("\n✅ All dependencies are installed!")
        
        # Test server import
        print("\n🧪 Testing server import...")
        try:
            from src.revenium_mcp_server.enhanced_server import main as server_main
            print("  ✅ Server import successful!")
            return True
        except Exception as e:
            print(f"  ❌ Server import failed: {e}")
            return False
    
    # Install missing dependencies
    print(f"\n🔧 Installing {len(missing_deps)} missing dependencies...")
    
    failed_installs = []
    for module_name, package_name in missing_deps:
        print(f"  📦 Installing {package_name}...")
        if install_dependency(package_name):
            print(f"    ✅ {package_name} installed successfully")
        else:
            print(f"    ❌ Failed to install {package_name}")
            failed_installs.append(package_name)
    
    if failed_installs:
        print(f"\n❌ Failed to install: {', '.join(failed_installs)}")
        print("\n🔧 Manual installation commands:")
        for package in failed_installs:
            print(f"  pip install {package}")
        return False
    
    print("\n✅ All dependencies installed successfully!")
    
    # Test server import after installation
    print("\n🧪 Testing server import...")
    try:
        from src.revenium_mcp_server.enhanced_server import main as server_main
        print("  ✅ Server import successful!")
        print("\n🚀 Server is ready to start!")
        print("   Run: python run_server.py")
        return True
    except Exception as e:
        print(f"  ❌ Server import still failing: {e}")
        print("\n🔧 Additional troubleshooting may be needed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
