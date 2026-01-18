#!/usr/bin/env python3
"""
WebSocket Proxy Server for GANZA AI Live API
Handles authentication and proxies WebSocket connections.

This server acts as a bridge between the browser client and the AI API,
handling authentication automatically using default credentials.
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

# Authentication imports
import google.auth
from google.auth.transport.requests import Request

# Configuration from environment variables
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
WS_PORT = int(os.getenv('WS_PORT', '8080'))
GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', '')
GCP_REGION = os.getenv('GCP_REGION', 'us-central1')
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'gemini-live-2.5-flash-native-audio')
# Get credentials path, strip whitespace, use None if empty
_creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
GOOGLE_APPLICATION_CREDENTIALS = _creds_path if _creds_path else None


def generate_access_token():
    """Retrieves an access token using credentials from environment."""
    try:
        # Use service account if path provided, otherwise use ADC
        if GOOGLE_APPLICATION_CREDENTIALS:
            # Verify the file exists
            if not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
                raise FileNotFoundError(f"Service account file not found: {GOOGLE_APPLICATION_CREDENTIALS}")
            # Set environment variable for google.auth to use
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_APPLICATION_CREDENTIALS
            print(f"🔑 Using service account: {GOOGLE_APPLICATION_CREDENTIALS}")
        else:
            # Ensure GOOGLE_APPLICATION_CREDENTIALS is not set to empty string (use ADC)
            # If it's set to empty string in .env, it will be in os.environ as empty string
            # We need to remove it so google.auth.default() uses ADC instead
            if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
                env_creds = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
                if not env_creds:
                    # It's empty, remove it to use ADC
                    del os.environ['GOOGLE_APPLICATION_CREDENTIALS']
            print("🔑 Using Application Default Credentials (ADC)")
        
        # Get credentials - this will use ADC if GOOGLE_APPLICATION_CREDENTIALS is not set
        creds, project = google.auth.default()
        
        # Verify project matches if specified
        if GCP_PROJECT_ID and project and project != GCP_PROJECT_ID:
            print(f"⚠️ Warning: Credentials project ({project}) doesn't match GCP_PROJECT_ID ({GCP_PROJECT_ID})")
        
        if not creds.valid:
            print("🔄 Refreshing access token...")
            creds.refresh(Request())
        
        print(f"✅ Access token generated for project: {project or GCP_PROJECT_ID or 'default'}")
        return creds.token
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print(f"   Make sure the service account file path is correct in .env")
        return None
    except Exception as e:
        print(f"❌ Error generating access token: {e}")
        if GOOGLE_APPLICATION_CREDENTIALS:
            print(f"   Check if service account file exists: {GOOGLE_APPLICATION_CREDENTIALS}")
            print(f"   Make sure the file path is correct and the service account has roles/aiplatform.user role")
        else:
            print("   Make sure you're logged in with: gcloud auth application-default login")
            print("   Run: gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform")
        return None


async def proxy_task(
    source_websocket: WebSocketCommonProtocol,
    destination_websocket: WebSocketCommonProtocol,
    is_server: bool,
) -> None:
    """
    Forwards messages from source_websocket to destination_websocket.

    Args:
        source_websocket: The WebSocket connection to receive messages from.
        destination_websocket: The WebSocket connection to send messages to.
        is_server: True if source is server side, False otherwise.
    """
    try:
        async for message in source_websocket:
            try:
                data = json.loads(message)
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
    client_websocket: WebSocketCommonProtocol, bearer_token: str, service_url: str
) -> None:
    """
    Establishes a WebSocket connection to the Gemini server and creates bidirectional proxy.

    Args:
        client_websocket: The WebSocket connection of the client.
        bearer_token: The bearer token for authentication with the server.
        service_url: The url of the service to connect to.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer_token}",
    }

    # Create SSL context with certifi certificates
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    print(f"Connecting to Gemini API...")
    if DEBUG:
        print(f"Service URL: {service_url}")

    try:
        async with websockets.connect(
            service_url,
            additional_headers=headers,
            ssl=ssl_context
        ) as server_websocket:
            print(f"✅ Connected to Gemini API")

            # Create bidirectional proxy tasks
            client_to_server_task = asyncio.create_task(
                proxy_task(client_websocket, server_websocket, is_server=False)
            )
            server_to_client_task = asyncio.create_task(
                proxy_task(server_websocket, client_websocket, is_server=True)
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
        if not client_websocket.closed:
            await client_websocket.close(code=e.code, reason=e.reason)
    except Exception as e:
        print(f"Failed to connect to Gemini API: {e}")
        if not client_websocket.closed:
            await client_websocket.close(code=1008, reason="Upstream connection failed")


async def handle_websocket_client(client_websocket: WebSocketServerProtocol) -> None:
    """
    Handles a new WebSocket client connection.

    Expects first message with optional bearer_token and service_url.
    If no bearer_token provided, generates one using Google default credentials.

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

        bearer_token = service_setup_message_data.get("bearer_token")
        service_url = service_setup_message_data.get("service_url")

        # If no bearer token provided, generate one using default credentials
        if not bearer_token:
            print("🔑 Generating access token using default credentials...")
            bearer_token = generate_access_token()
            if not bearer_token:
                print("❌ Failed to generate access token")
                await client_websocket.close(
                    code=1008, reason="Authentication failed"
                )
                return
            print("✅ Access token generated")

        if not service_url:
            print("❌ Error: Service URL is missing")
            await client_websocket.close(
                code=1008, reason="Service URL is required"
            )
            return

        await create_proxy(client_websocket, bearer_token, service_url)

    except asyncio.TimeoutError:
        print("⏱️ Timeout waiting for the first message from the client")
        await client_websocket.close(code=1008, reason="Timeout")
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in first message: {e}")
        await client_websocket.close(code=1008, reason="Invalid JSON")
    except Exception as e:
        print(f"❌ Error handling client: {e}")
        if not client_websocket.closed:
            await client_websocket.close(code=1011, reason="Internal error")


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
    if not GCP_PROJECT_ID:
        print("⚠️ Warning: GCP_PROJECT_ID not set in .env file")
        print("   The frontend will need to provide project ID in the connection message")
    
    # Test authentication on startup
    print("🔍 Testing authentication...")
    token = generate_access_token()
    if not token:
        print("❌ Authentication test failed. Please check your credentials.")
        print("   See .env.example for configuration options")
        return
    
    print(f"""
╔════════════════════════════════════════════════════════════╗
║     Gemini Live API Proxy Server (Vertex AI)              ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  🔌 WebSocket Proxy: ws://localhost:{WS_PORT:<5}                   ║
║  📁 Project ID: {GCP_PROJECT_ID or '(from client)':<35} ║
║  🌍 Region: {GCP_REGION:<43} ║
║  🤖 Default Model: {DEFAULT_MODEL:<32} ║
║                                                            ║
║  Authentication:                                           ║
║  {'• Service Account: ' + GOOGLE_APPLICATION_CREDENTIALS if GOOGLE_APPLICATION_CREDENTIALS else '• Using Application Default Credentials (ADC)':<54} ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
""")

    await start_websocket_server()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Servers stopped")