#!/bin/bash
# Revenium Platform API MCP Server - Development Setup Script
# This script ensures all dependencies are installed and the server can start

set -e  # Exit on any error

echo "🚀 Setting up Revenium Platform API MCP Server development environment..."

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ Error: requirements.txt not found. Please run this script from the project root."
    exit 1
fi

# Check Python version
python_version=$(python --version 2>&1 | cut -d' ' -f2)
echo "🐍 Python version: $python_version"

# Install/upgrade pip
echo "📦 Upgrading pip..."
python -m pip install --upgrade pip

# Install all dependencies
echo "📦 Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Verify critical dependencies
echo "🔍 Verifying critical dependencies..."

critical_deps=("fastmcp" "loguru" "httpx" "pydantic" "python-dotenv")
missing_deps=()

for dep in "${critical_deps[@]}"; do
    if ! python -c "import $dep" 2>/dev/null; then
        missing_deps+=("$dep")
    else
        echo "  ✅ $dep - OK"
    fi
done

if [ ${#missing_deps[@]} -ne 0 ]; then
    echo "❌ Missing critical dependencies: ${missing_deps[*]}"
    echo "🔧 Attempting to install missing dependencies..."
    for dep in "${missing_deps[@]}"; do
        pip install "$dep"
    done
fi

# Test server import
echo "🧪 Testing server import..."
if python -c "from src.revenium_platformapi_mcp_server.enhanced_server import main" 2>/dev/null; then
    echo "  ✅ Server import - OK"
else
    echo "  ❌ Server import failed - checking for missing dependencies..."
    # Try to run and capture the specific error
    python -c "from src.revenium_platformapi_mcp_server.enhanced_server import main" 2>&1 | head -5
fi

# Check environment variables
echo "🔧 Checking environment configuration..."
if [ -f ".env" ]; then
    echo "  ✅ .env file found"
else
    echo "  ⚠️  .env file not found - creating template..."
    cat > .env << EOF
# Revenium Platform API Configuration
REVENIUM_API_KEY=your_api_key_here
REVENIUM_TEAM_ID=your_team_id_here
REVENIUM_OWNER_ID=your_owner_id_here
LOG_LEVEL=INFO

# Optional: Default email for alerts
REVENIUM_DEFAULT_EMAIL=your_email@company.com
EOF
    echo "  📝 Created .env template - please update with your credentials"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 To start the server:"
echo "   python run_server.py              # Production server"
echo "   python run_server_dev.py          # Development (with cache clearing)"
echo "   python -m revenium_mcp_server     # Module execution"
echo ""
echo "🔧 To install dependencies manually:"
echo "   pip install -r requirements.txt"
echo ""
echo "📚 Remember to update .env with your Revenium API credentials!"
