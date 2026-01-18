#!/usr/bin/env python3
"""
WebSocket Proxy Server for GANZA AI - API Key Authentication
Uses API key authentication for direct API access

This is a SEPARATE server file. If this fails, use server.py for alternative authentication.
"""

import asyncio
import websockets
import json
import ssl
import certifi
import os
from pathlib import Path
from websockets.legacy.server import WebSocketServerProtocol
from websockets.legacy.protocol import WebSocketCommonProtocol
from websockets.exceptions import ConnectionClosed

# Load environment variables
from dotenv import load_dotenv

# Load .env file from the same directory as this script
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configuration from environment variables
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
WS_PORT = int(os.getenv('WS_PORT', '8080'))
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'gemini-2.5-flash-native-audio-preview-12-2025')


def map_vertex_ai_to_gemini_api_model(vertex_model_name):
    """
    Map Vertex AI model names to Gemini API model names.
    
    Vertex AI uses different model names than Gemini API.
    This function converts Vertex AI model names to Gemini API equivalents.
    """
    # Model name mapping: Vertex AI -> Gemini API
    model_mapping = {
        # Native Audio Models
        "gemini-live-2.5-flash-native-audio": "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-live-2.5-flash-preview-native-audio-09-2025": "gemini-2.5-flash-native-audio-preview-12-2025",
        
        # Standard Models
        "gemini-2.0-flash-exp": "gemini-2.0-flash-exp",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-1.5-flash": "gemini-1.5-flash",
    }
    
    # Check if we have a mapping
    if vertex_model_name in model_mapping:
        mapped_name = model_mapping[vertex_model_name]
        if DEBUG:
            print(f"Mapped Vertex AI model: {vertex_model_name} -> {mapped_name}")
        return mapped_name
    
    # If no mapping found, check if it's already a Gemini API model name
    # (doesn't start with "gemini-live-")
    if not vertex_model_name.startswith("gemini-live-"):
        # Might already be a Gemini API model name
        return vertex_model_name
    
    # Unknown Vertex AI model - use default
    if DEBUG:
        print(f"Unknown Vertex AI model: {vertex_model_name}, using default: {DEFAULT_MODEL}")
    return DEFAULT_MODEL


def extract_model_name(model_uri):
    """
    Extract model name from Vertex AI format and convert to Gemini API format.
    
    Vertex AI format: "projects/{project}/locations/{region}/publishers/google/models/{model}"
    Gemini API format: "models/{model}" (REQUIRED - Gemini API demands "models/" prefix)
    """
    if not model_uri:
        return f"models/{DEFAULT_MODEL}"
    
    # Extract model name from Vertex AI format
    model_name = model_uri
    if "/models/" in model_uri:
        # Extract model name after "/models/"
        parts = model_uri.split("/models/")
        if len(parts) > 1:
            model_name = parts[-1]
    
    # Map Vertex AI model name to Gemini API model name
    gemini_api_model = map_vertex_ai_to_gemini_api_model(model_name)
    
    # CRITICAL FIX: Gemini API requires "models/" prefix in the model field
    # Don't send raw model name - must be "models/{model_name}"
    if not gemini_api_model.startswith("models/"):
        gemini_api_model = f"models/{gemini_api_model}"
    
    return gemini_api_model


async def proxy_task(
    source_websocket: WebSocketCommonProtocol,
    destination_websocket: WebSocketCommonProtocol,
    is_server: bool,
    transform_setup_message: bool = False,
) -> None:
    """
    Forwards messages from source_websocket to destination_websocket.
    Can transform setup messages for Gemini API compatibility.

    Args:
        source_websocket: The WebSocket connection to receive messages from.
        destination_websocket: The WebSocket connection to send messages to.
        is_server: True if source is server side, False otherwise.
        transform_setup_message: If True, transform setup messages for Gemini API.
    """
    try:
        async for message in source_websocket:
            try:
                data = json.loads(message)
                
                # Transform setup message if needed (client -> server)
                if transform_setup_message and not is_server and "setup" in data:
                    setup = data["setup"]
                    
                    # Extract just model name from Vertex AI format and convert to Gemini API
                    if "model" in setup:
                        original_model = setup["model"]
                        model_name = extract_model_name(original_model)
                        setup["model"] = model_name
                        print(f"🔄 Model transformation: {original_model} -> {model_name}")
                        print(f"✅ Sending to Gemini API with 'models/' prefix (required format)")
                        if DEBUG:
                            print(f"   Full setup message: {json.dumps(setup, indent=2)}")
                    
                    # Remove unsupported fields for Gemini API
                    # These fields are Vertex AI-specific and not supported by Gemini API
                    unsupported_setup_fields = [
                        "proactivity",  # Not supported by Gemini API
                    ]
                    
                    for field in unsupported_setup_fields:
                        if field in setup:
                            del setup[field]
                            if DEBUG:
                                print(f"Removed unsupported setup field: {field}")
                    
                    # Remove unsupported fields from generation_config
                    if "generation_config" in setup:
                        gen_config = setup["generation_config"]
                        unsupported_gen_config_fields = [
                            "enable_affective_dialog",  # Not supported by Gemini API
                        ]
                        
                        for field in unsupported_gen_config_fields:
                            if field in gen_config:
                                del gen_config[field]
                                if DEBUG:
                                    print(f"Removed unsupported generation_config field: {field}")
                
                if DEBUG:
                    print(f"Proxying from {'server' if is_server else 'client'}: {data}")
                await destination_websocket.send(json.dumps(data))
            except Exception as e:
                print(f"Error processing message: {e}")
    except ConnectionClosed as e:
        print(
            f"{'Server' if is_server else 'Client'} connection closed: {e.code} - {e.reason}"
        )
    except Exception as e:
        print(f"Unexpected error in proxy_task: {e}")
    finally:
        await destination_websocket.close()


async def create_proxy(
    client_websocket: WebSocketCommonProtocol, service_url: str
) -> None:
    """
    Establishes a WebSocket connection to Gemini API and creates bidirectional proxy.

    Args:
        client_websocket: The WebSocket connection of the client.
        service_url: The url of the service to connect to (includes API key in URL).
    """
    # Gemini API uses API key in URL, no bearer token needed
    headers = {
        "Content-Type": "application/json",
    }

    # Create SSL context with certifi certificates
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    print(f"Connecting to Gemini API...")
    if DEBUG:
        print(f"Service URL: {service_url[:80]}...")  # Don't print full URL with API key

    try:
        async with websockets.connect(
            service_url,
            additional_headers=headers,
            ssl=ssl_context
        ) as server_websocket:
            print(f"✅ Connected to Gemini API")

            # Create bidirectional proxy tasks
            # Transform setup messages from client (extract model name)
            client_to_server_task = asyncio.create_task(
                proxy_task(client_websocket, server_websocket, is_server=False, transform_setup_message=True)
            )
            server_to_client_task = asyncio.create_task(
                proxy_task(server_websocket, client_websocket, is_server=True, transform_setup_message=False)
            )

            # Wait for either task to complete
            done, pending = await asyncio.wait(
                [client_to_server_task, server_to_client_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the remaining task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Close connections
            try:
                await server_websocket.close()
            except:
                pass

            try:
                await client_websocket.close()
            except:
                pass

    except ConnectionClosed as e:
        print(f"Server connection closed unexpectedly: {e.code} - {e.reason}")
        try:
            await client_websocket.close(code=e.code, reason=e.reason)
        except:
            pass
    except Exception as e:
        print(f"Failed to connect to Gemini API: {e}")
        try:
            await client_websocket.close(code=1008, reason="Upstream connection failed")
        except:
            pass


async def handle_websocket_client(client_websocket: WebSocketServerProtocol) -> None:
    """
    Handles a new WebSocket client connection.

    Args:
        client_websocket: The WebSocket connection of the client.
    """
    print("🔌 New WebSocket client connection...")
    try:
        # Wait for the first message from the client
        service_setup_message = await asyncio.wait_for(
            client_websocket.recv(), timeout=10.0
        )
        service_setup_message_data = json.loads(service_setup_message)

        # ALWAYS use Gemini API URL (ignore frontend's service_url)
        if not GEMINI_API_KEY:
            print("❌ Error: GEMINI_API_KEY not set in .env file")
            await client_websocket.close(
                code=1008, reason="API key required"
            )
            return
        
        # Always build Gemini API endpoint (ignore what frontend sends)
        # Correct endpoint format: v1beta with dot notation (not slash)
        service_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
        print(f"✅ Using Gemini API endpoint (ignoring frontend's service_url)")
        if DEBUG:
            print(f"   Endpoint: {service_url[:100]}...")  # Print partial URL for debugging

        await create_proxy(client_websocket, service_url)

    except asyncio.TimeoutError:
        print("⏱️ Timeout waiting for the first message from the client")
        await client_websocket.close(code=1008, reason="Timeout")
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in first message: {e}")
        await client_websocket.close(code=1008, reason="Invalid JSON")
    except Exception as e:
        print(f"❌ Error handling client: {e}")
        import traceback
        traceback.print_exc()
        try:
            await client_websocket.close(code=1011, reason="Internal error")
        except:
            pass


async def start_websocket_server():
    """Start the WebSocket proxy server."""
    async with websockets.serve(handle_websocket_client, "0.0.0.0", WS_PORT):
        print(f"🔌 WebSocket proxy running on ws://localhost:{WS_PORT}")
        # Run forever
        await asyncio.Future()


async def main():
    """
    Starts the WebSocket server.
    """
    # Validate configuration
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY not set in .env file")
        print("   Get your API key from: https://aistudio.google.com/app/apikey")
        print("   Add to .env: GEMINI_API_KEY=your-api-key-here")
        return
    
    print(f"""
╔════════════════════════════════════════════════════════════╗
║     Gemini API Proxy Server (NOT Vertex AI)               ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  🔌 WebSocket Proxy: ws://localhost:{WS_PORT:<5}                   ║
║  🔑 API Key: {'✅ Set' if GEMINI_API_KEY else '❌ Missing':<45} ║
║  🤖 Default Model: {DEFAULT_MODEL:<32} ║
║                                                            ║
║  ⚠️  If this fails, use server.py (Vertex AI) instead     ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
""")

    await start_websocket_server()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
