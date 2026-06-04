#!/usr/bin/env python3
"""
Clear Python cache files to ensure code changes take effect.

This script removes all __pycache__ directories and .pyc files
to force Python to reload modules from source.
"""

import os
import shutil
import sys
from pathlib import Path


def clear_python_cache(root_dir: str = ".") -> None:
    """Clear all Python cache files and directories.
    
    Args:
        root_dir: Root directory to start clearing from
    """
    root_path = Path(root_dir)
    
    # Track what we're removing
    removed_dirs = []
    removed_files = []
    
    # Remove __pycache__ directories
    for pycache_dir in root_path.rglob("__pycache__"):
        if pycache_dir.is_dir():
            try:
                shutil.rmtree(pycache_dir)
                removed_dirs.append(str(pycache_dir))
                print(f"✅ Removed cache directory: {pycache_dir}")
            except Exception as e:
                print(f"❌ Failed to remove {pycache_dir}: {e}")
    
    # Remove .pyc files
    for pyc_file in root_path.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            removed_files.append(str(pyc_file))
            print(f"✅ Removed cache file: {pyc_file}")
        except Exception as e:
            print(f"❌ Failed to remove {pyc_file}: {e}")
    
    # Remove .pyo files (optimized bytecode)
    for pyo_file in root_path.rglob("*.pyo"):
        try:
            pyo_file.unlink()
            removed_files.append(str(pyo_file))
            print(f"✅ Removed optimized cache file: {pyo_file}")
        except Exception as e:
            print(f"❌ Failed to remove {pyo_file}: {e}")
    
    # Summary
    print("\n🧹 **Cache Clearing Summary**")
    print(f"   📁 Directories removed: {len(removed_dirs)}")
    print(f"   📄 Files removed: {len(removed_files)}")
    
    if removed_dirs or removed_files:
        print("\n✅ **Cache cleared successfully!**")
        print("   🔄 **Next step**: Restart your MCP server to load fresh modules")
    else:
        print("\n✨ **No cache files found** - your environment is already clean!")


if __name__ == "__main__":
    # Allow specifying a different root directory
    root_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    
    print(f"🧹 **Clearing Python cache in: {os.path.abspath(root_dir)}**\n")
    clear_python_cache(root_dir)
