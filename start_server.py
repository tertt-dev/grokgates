#!/usr/bin/env python3
"""
Clean startup script for Grokgates v6 server
Handles initialization and suppresses unnecessary warnings
"""
import os
import sys
import signal
import warnings
import logging

# Suppress ONNX runtime warnings on macOS
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['ONNXRUNTIME_DISABLE_COREML'] = '1'
warnings.filterwarnings('ignore', category=UserWarning, module='onnxruntime')

# Disable ChromaDB telemetry completely
os.environ['ANONYMIZED_TELEMETRY'] = 'False'
os.environ['CHROMA_TELEMETRY_IMPL'] = 'none'

# Configure logging before imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Suppress noisy loggers
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('chromadb').setLevel(logging.WARNING)
logging.getLogger('chromadb.telemetry.product.posthog').setLevel(logging.CRITICAL)
logging.getLogger('onnxruntime').setLevel(logging.ERROR)

def check_dependencies():
    """Check if all required services are available"""
    import subprocess
    
    # Check Redis
    try:
        result = subprocess.run(['redis-cli', 'ping'], capture_output=True, text=True)
        if result.stdout.strip() != 'PONG':
            logging.error("Redis is not running. Please start Redis first.")
            logging.info("Run: redis-server")
            return False
    except FileNotFoundError:
        logging.error("Redis is not installed. Please install Redis first.")
        return False
    
    logging.info("All dependencies checked successfully")
    return True

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    logging.info(f"🛑 Received signal {sig}, shutting down gracefully...")
    sys.exit(0)

def main():
    """Main startup function"""
    logging.info("=== Grokgates v6 Server Starting ===")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if not check_dependencies():
        sys.exit(1)
    
    try:
        # Import after environment setup
        from web_server import run_web_server
        
        # Start the web server with proper initialization
        run_web_server(host='0.0.0.0', port=8888, debug=False)
        
    except ImportError as e:
        logging.error(f"Failed to import required modules: {e}")
        logging.info("Please run: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Server startup failed: {e}")
        logging.exception("Full traceback:")
        sys.exit(1)

if __name__ == "__main__":
    main()