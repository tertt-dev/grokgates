"""
Web server for Grokgates - Flask + WebSocket interface
"""
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import asyncio
import threading
import json
import os
import sys
import signal
from datetime import datetime
from redis_manager import RedisManager
from conversation_manager import ConversationManager
from beacon_v2 import BeaconV2
from agents import ObserverAgent, EgoAgent
from agents.planner import PlannerAgent
from superego import Superego
import config
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'grokgates-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global instances
redis_mgr = None
orchestrator = None
background_thread = None

class WebOrchestrator:
    def __init__(self, socketio_instance, redis_instance=None):
        self.socketio = socketio_instance
        # Use provided redis instance or create new one
        self.redis = redis_instance if redis_instance else RedisManager()
        # Use existing conversation manager if available
        if hasattr(self.redis, 'conversation_manager') and self.redis.conversation_manager:
            self.conversation_mgr = self.redis.conversation_manager
        else:
            self.conversation_mgr = ConversationManager(self.redis)
            self.redis.conversation_manager = self.conversation_mgr
        self.beacon = BeaconV2(self.redis)
        self.observer = ObserverAgent(self.redis)
        self.ego = EgoAgent(self.redis)
        self.planner = PlannerAgent(self.redis)
        self.superego = Superego(self.redis)
        self.running = False
        self.loop = None
        self.conversation_lock = None  # Will be created in event loop
        
    async def graceful_shutdown(self):
        """Gracefully shutdown the orchestrator and complete current conversation"""
        logger.info("🛑 GRACEFUL SHUTDOWN INITIATED")
        
        # Stop the main loop
        self.running = False
        
        # Complete current conversation if active
        try:
            if self.conversation_mgr.current_conversation_id:
                logger.info(f"📝 Completing active conversation: {self.conversation_mgr.current_conversation_id}")
                await self.conversation_mgr.add_message("SYSTEM", "◈ SERVER SHUTDOWN - CONVERSATION COMPLETED ◈")
                await self.conversation_mgr.end_current_conversation()
                logger.info("✅ Active conversation marked as completed")
            else:
                logger.info("ℹ️  No active conversation to complete")
        except Exception as e:
            logger.error(f"❌ Error completing conversation on shutdown: {e}")
        
        logger.info("✅ GRACEFUL SHUTDOWN COMPLETE")
        
    def start_background_tasks(self):
        """Start the async event loop in a background thread"""
        self.running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Create conversation lock for ensuring only one agent speaks at a time
        self.conversation_lock = asyncio.Lock()
        self.last_message_time = 0  # Track when last message was sent
        
        # Start all components
        beacon_task = self.loop.create_task(self._run_beacon())
        observer_task = self.loop.create_task(self._run_observer())
        ego_task = self.loop.create_task(self._run_ego())
        planner_task = self.loop.create_task(self._run_planner())
        superego_task = self.loop.create_task(self._run_superego())
        emit_task = self.loop.create_task(self._emit_updates())
        
        # Log task creation
        logger.info("Background tasks created")
        
        # Run the event loop
        try:
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Event loop error: {e}")
        finally:
            logger.info("Event loop stopped")
    
    async def _run_beacon(self):
        """Run the Beacon v1.5 with two-phase system"""
        while self.running:
            try:
                await self.beacon.run_beacon_cycle()
            except Exception as e:
                logger.error(f"Beacon v1.5 error: {e}", exc_info=True)
                await asyncio.sleep(30)  # Wait before retry
    
    async def _run_observer(self):
        """Run the Observer agent"""
        await asyncio.sleep(5)  # Initial delay
        while self.running:
            try:
                # Check if frontend is typing
                typing_status = self.redis.client.get('frontend_typing')
                if typing_status:
                    # Handle both bytes and string
                    if isinstance(typing_status, bytes):
                        typing_status = typing_status.decode()
                    if typing_status == '1':
                        # Frontend is typing, wait
                        await asyncio.sleep(2)
                        continue
                
                # Check if conversation is active
                if not self.conversation_mgr.current_conversation_id:
                    # Start a new conversation if none active
                    await self.conversation_mgr.start_new_conversation()
                
                # Only process if we can acquire the conversation lock
                async with self.conversation_lock:
                    # Check if conversation is still active (might have ended)
                    if self.conversation_mgr.current_conversation_id:
                        # Ensure minimum time between messages
                        current_time = asyncio.get_event_loop().time()
                        time_since_last = current_time - self.last_message_time
                        if time_since_last < 3:  # Minimum 3 seconds between messages
                            await asyncio.sleep(3 - time_since_last)
                        
                        result = await self.observer.process_beacon()
                        if result:  # If a message was sent
                            self.last_message_time = asyncio.get_event_loop().time()
                        else:
                            # Even if no message, wait before retrying
                            await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Observer error: {e}")
            
            # Dynamic delay based on conversation state (doubled cadence)
            if self.conversation_mgr.current_conversation_id:
                await asyncio.sleep(70)  # 70 seconds between Observer messages
            else:
                await asyncio.sleep(90)  # 90 seconds when waiting for new conversation
    
    async def _run_ego(self):
        """Run the Ego agent"""
        await asyncio.sleep(10)  # Initial delay
        while self.running:
            try:
                # Check if frontend is typing
                typing_status = self.redis.client.get('frontend_typing')
                if typing_status:
                    # Handle both bytes and string
                    if isinstance(typing_status, bytes):
                        typing_status = typing_status.decode()
                    if typing_status == '1':
                        # Frontend is typing, wait
                        await asyncio.sleep(2)
                        continue
                
                # Only respond if there's an active conversation
                if self.conversation_mgr.current_conversation_id:
                    # Only process if we can acquire the conversation lock
                    async with self.conversation_lock:
                        # Check again after acquiring lock
                        if self.conversation_mgr.current_conversation_id:
                            # Ensure minimum time between messages
                            current_time = asyncio.get_event_loop().time()
                            time_since_last = current_time - self.last_message_time
                            if time_since_last < 3:  # Minimum 3 seconds between messages
                                await asyncio.sleep(3 - time_since_last)
                            
                            result = await self.ego.generate_chaos()
                            if result:  # If a message was sent
                                self.last_message_time = asyncio.get_event_loop().time()
                            else:
                                # Even if no message, wait before retrying
                                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Ego error: {e}")
            
            # Dynamic delay based on conversation state (doubled cadence)
            if self.conversation_mgr.current_conversation_id:
                await asyncio.sleep(80)  # 80 seconds between Ego messages
            else:
                await asyncio.sleep(120)  # 120 seconds when waiting
    
    async def _run_planner(self):
        """Run the Planner agent - let it handle its own timing"""
        await self.planner.run_continuous()
    
    async def _run_superego(self):
        """Run the Superego meta-controller"""
        await asyncio.sleep(60)  # Initial delay
        while self.running:
            try:
                await self.superego.analyze_and_adjust()
            except Exception as e:
                logger.error(f"Superego error: {e}")
            await asyncio.sleep(300)  # Run every 5 minutes
    
    async def _emit_updates(self):
        """Emit updates to connected clients"""
        while self.running:
            try:
                # Get latest data
                board_data = self.redis.get_board_history(20)
                beacon_data = self.redis.get_beacon_feed(15)
                
                # Debug beacon data
                if beacon_data:
                    logger.debug(f"Emitting {len(beacon_data)} beacon entries")
                    for i, entry in enumerate(beacon_data[:1]):  # Log first entry
                        logger.debug(f"Beacon entry {i}: phase={entry.get('phase')}, tweets={len(entry.get('tweets', []))}, posts={len(entry.get('posts', []))}")
                
                # Format for frontend
                board_entries = []
                for entry in board_data:
                    parts = entry.split("|", 2)
                    if len(parts) >= 3:
                        board_entries.append({
                            "timestamp": parts[0],
                            "agent": parts[1],
                            "content": parts[2]
                        })
                
                # Get current dominance plan (prefer new Dominance_Protocol format)
                current_plan = None
                try:
                    # Prefer the explicitly tracked latest dominance protocol plan if present
                    latest_pid = self.redis.client.get('latest_dominance_protocol')
                    if latest_pid:
                        pdata = self.redis.client.hget("plans", latest_pid)
                        if pdata:
                            current_plan = json.loads(pdata)
                            logger.debug(f"🔍 Found dominance plan via latest_dominance_protocol: {latest_pid}")
                    if current_plan is None:
                        plan_ids = self.redis.client.lrange("plan_list", 0, 10)
                        for pid in plan_ids:
                            pdata = self.redis.client.hget("plans", pid)
                            if pdata:
                                pobj = json.loads(pdata)
                                if pobj.get("protocol") == "dominance_protocol" or pobj.get("mission"):
                                    current_plan = pobj
                                    logger.debug(f"🔍 Found dominance plan via plan_list: {pid}")
                                    break
                except Exception:
                    pass
                if current_plan is None:
                    # Fallback to legacy list
                    plan_data = self.redis.client.lindex("dominance_plans", 0)
                    if plan_data:
                        current_plan = json.loads(plan_data)
                        logger.debug("🔍 Found dominance plan via legacy dominance_plans list")
                
                # Get system status
                system_status = {
                    'phase': self.beacon.current_phase if hasattr(self.beacon, 'current_phase') else 'INITIALIZING',
                    'urge': None
                }
                
                # Get urge metrics
                try:
                    from urge_engine import UrgeEngine
                    urge = UrgeEngine(self.redis)
                    system_status['urge'] = urge.get_metrics()
                except:
                    pass
                
                # Get conversation data (disable typing simulation; always send full messages)
                conversation_data = self.conversation_mgr.get_conversation_for_display()
                
                # Emit to all connected clients
                self.socketio.emit('update', {
                    'board': board_entries,
                    'beacon': beacon_data,
                    'dominance_plan': current_plan,
                    'conversations': conversation_data,
                    'stats': {
                        'board_count': len(self.redis.get_board_history(100)),
                        'beacon_count': len(self.redis.get_beacon_feed(50)),
                        'timestamp': datetime.now().isoformat()
                    },
                    'system_status': system_status
                })
                
            except Exception as e:
                logger.error(f"Emit error: {e}")
            
            await asyncio.sleep(1)  # Update every second
    
    def stop(self):
        """Stop all background tasks"""
        self.running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

@app.route('/')
def index():
    """Serve the main web interface"""
    return render_template('index.html')

@app.route('/about')
def about():
    """Serve the About page"""
    return render_template('about.html')

@app.route('/api/status')
def get_status():
    """Get current system status"""
    return jsonify({
        'status': 'running' if orchestrator and orchestrator.running else 'stopped',
        'api_key_set': config.GROK_API_ENABLED,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/board')
def get_board():
    """Get current board state"""
    if not redis_mgr:
        return jsonify({'error': 'System not initialized'}), 503
    
    board_data = redis_mgr.get_board_history(50)
    board_entries = []
    
    for entry in board_data:
        parts = entry.split("|", 2)
        if len(parts) >= 3:
            board_entries.append({
                "timestamp": parts[0],
                "agent": parts[1],
                "content": parts[2]
            })
    
    return jsonify({'board': board_entries})

@app.route('/api/beacon')
def get_beacon():
    """Get current beacon feed"""
    if not redis_mgr:
        return jsonify({'error': 'System not initialized'}), 503
    
    beacon_data = redis_mgr.get_beacon_feed(10)
    return jsonify({'beacon': beacon_data})

@app.route('/api/conversations')
def get_conversations():
    """Get conversation threads"""
    if not orchestrator:
        return jsonify({'error': 'System not initialized'}), 503
    
    conv_data = orchestrator.conversation_mgr.get_conversation_for_display()
    return jsonify(conv_data)

@app.route('/api/ascii-art')
def get_ascii_art():
    """Get ASCII art data"""
    try:
        # Read ASCII art from file
        ascii_path = os.path.join(app.static_folder, 'ascii_art.txt')
        if os.path.exists(ascii_path):
            with open(ascii_path, 'r') as f:
                ascii_art = f.read()
            return jsonify({'ascii_art': ascii_art})
        else:
            return jsonify({'error': 'ASCII art not found'}), 404
    except Exception as e:
        logger.error(f"API ASCII art error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/conversation/<conversation_id>')
def view_conversation(conversation_id):
    """View a specific conversation"""
    if not redis_mgr or not redis_mgr.conversation_manager:
        return "System not initialized", 503
    
    # Get the conversation data
    conversation = redis_mgr.conversation_manager.get_conversation_by_id(conversation_id)
    
    if not conversation:
        return "Conversation not found", 404
    
    # Format timestamps for display
    from datetime import datetime
    if conversation.get('started_at'):
        conversation['started_at'] = datetime.fromisoformat(conversation['started_at']).strftime('%Y-%m-%d %H:%M:%S')
    if conversation.get('ended_at'):
        conversation['ended_at'] = datetime.fromisoformat(conversation['ended_at']).strftime('%Y-%m-%d %H:%M:%S')
    
    # Format message timestamps
    for msg in conversation.get('messages', []):
        if msg.get('timestamp'):
            msg['timestamp'] = datetime.fromisoformat(msg['timestamp']).strftime('%H:%M:%S')
    
    return render_template('conversation.html', conversation=conversation)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('connected', {'message': 'Connected to Grokgates'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')

@socketio.on('typing_status')
def handle_typing_status(data):
    """Handle typing status from client"""
    is_typing = data.get('isTyping', False)
    if redis_mgr:
        # Store typing status in Redis
        redis_mgr.client.set('frontend_typing', '1' if is_typing else '0')
        logger.debug(f"Frontend typing status: {is_typing}")

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    global orchestrator
    logger.info(f"🛑 Received signal {sig}, initiating graceful shutdown...")
    
    if orchestrator:
        # Run the shutdown in the orchestrator's event loop
        if orchestrator.loop and orchestrator.loop.is_running():
            # Schedule the shutdown coroutine
            asyncio.run_coroutine_threadsafe(orchestrator.graceful_shutdown(), orchestrator.loop)
            # Give it time to complete
            import time
            time.sleep(2)
        else:
            logger.warning("Orchestrator loop not running, cannot complete conversation gracefully")
    
    logger.info("🚪 Exiting...")
    sys.exit(0)

def start_orchestrator():
    """Start the orchestrator in a background thread"""
    global orchestrator, background_thread, redis_mgr
    
    # Stop any existing orchestrator first
    if orchestrator:
        orchestrator.stop()
        if background_thread and background_thread.is_alive():
            background_thread.join(timeout=5)
    
    # Create new orchestrator with shared redis instance
    orchestrator = WebOrchestrator(socketio, redis_mgr)
    background_thread = threading.Thread(target=orchestrator.start_background_tasks)
    background_thread.daemon = True
    background_thread.start()
    logger.info("Orchestrator started")

def _complete_active_conversations(redis_mgr: RedisManager):
    """Complete any active conversations from previous sessions"""
    try:
        # Get all conversation metadata
        conv_data = redis_mgr.client.hgetall('conversations')
        completed_count = 0
        
        for conv_id, metadata_str in conv_data.items():
            if isinstance(conv_id, bytes):
                conv_id = conv_id.decode()
            if isinstance(metadata_str, bytes):
                metadata_str = metadata_str.decode()
                
            metadata = json.loads(metadata_str)
            
            # If conversation is still active, mark it as completed
            if metadata.get('status') == 'active':
                metadata['status'] = 'completed'
                metadata['ended_at'] = datetime.now().isoformat()
                
                # Update in Redis
                redis_mgr.client.hset('conversations', conv_id, json.dumps(metadata))
                completed_count += 1
                
        if completed_count > 0:
            logger.info(f"🔄 Completed {completed_count} active conversations from previous session")
        else:
            logger.info("ℹ️  No active conversations found to complete")
            
    except Exception as e:
        logger.error(f"❌ Error completing active conversations: {e}")

def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """Run the web server"""
    global redis_mgr
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("🔧 Signal handlers registered for graceful shutdown")
    
    # Initialize Redis manager
    redis_mgr = RedisManager()
    # Don't clear beacon feed - we want to preserve it
    redis_mgr.client.delete("shared_board")  # Only clear board messages
    
    # Complete any active conversations from previous sessions
    _complete_active_conversations(redis_mgr)
    
    # Clear dominance plans so they don't show immediately at startup
    cleared_count = 0
    if redis_mgr.client.delete("dominance_plans"):
        cleared_count += 1
    if redis_mgr.client.delete("plan_list"):
        cleared_count += 1
    if redis_mgr.client.delete("plans"):
        cleared_count += 1
    if redis_mgr.client.delete("latest_dominance_protocol"):
        cleared_count += 1
    logger.info(f"🧹 Cleared {cleared_count} dominance plan storage locations - new plan will be created after 2 hours")
    
    # Verify clearing worked
    remaining_plans = redis_mgr.client.llen("dominance_plans")
    remaining_plan_ids = redis_mgr.client.llen("plan_list")
    remaining_plan_hash = len(redis_mgr.client.hkeys("plans"))
    latest_protocol = redis_mgr.client.get("latest_dominance_protocol")
    
    if any([remaining_plans, remaining_plan_ids, remaining_plan_hash, latest_protocol]):
        logger.warning(f"⚠️  Some dominance plan data still exists: plans={remaining_plans}, ids={remaining_plan_ids}, hash={remaining_plan_hash}, latest={latest_protocol}")
    else:
        logger.info("✅ Verified: All dominance plan data successfully cleared")
    
    # Initialize conversation manager and attach it to redis_mgr
    conversation_mgr = ConversationManager(redis_mgr)
    redis_mgr.conversation_manager = conversation_mgr
    
    # Write initial system message only
    redis_mgr.write_board("SYSTEM", "◈ GROKGATES v2 INITIALIZED ◈")
    
    # Start the orchestrator
    start_orchestrator()
    
    # Run the Flask app
    logger.info(f"Starting web server on http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    import sys
    
    # Allow port configuration via command line
    port = 8888
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}, using default 8888")
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║
║  ▓ GROKGATES.EXE - WEB SERVER STARTING                                       ▓  ║
║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
    
    Server Configuration:
    - Host: 0.0.0.0 (accessible from any network interface)
    - Port: {port}
    - Local URL: http://localhost:{port}
    - Network URL: http://<your-ip>:{port}
    
    To find your IP address:
    - macOS/Linux: ifconfig | grep inet
    - Windows: ipconfig
    
    For web sharing:
    - Make sure port {port} is open in your firewall
    - Consider using ngrok for secure tunneling: ngrok http {port}
    - Or use cloudflared: cloudflared tunnel --url http://localhost:{port}
    """)
    
    run_web_server(host='0.0.0.0', port=port, debug=False)