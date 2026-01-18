# GANZA AI

A React-based voice AI application featuring real-time audio/video streaming and a WebSocket proxy for secure authentication.

## Quick Start

### 1. Backend Setup

Install Python dependencies and start the proxy server:

```bash
# Install dependencies
pip install -r requirements.txt

# Configure your API credentials in .env file
# See .env.example for required variables

# Start the proxy server
python server.py
```

### 2. Frontend Setup

In a new terminal, start the React application:

Ensure you have Node.js and npm installed. If not, download and install them from [nodejs.org](https://nodejs.org/en/download/).

```bash
# Install Node modules
npm install

# Start development server
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) to view the app.

## Features

- **Real-time Streaming**: Audio and video streaming capabilities
- **React Components**: Modular UI with `LiveAPIDemo.jsx`
- **Secure Proxy**: Python backend handles authentication
- **Custom Tools**: Support for defining client-side tools
- **Media Handling**: Dedicated audio capture and playback processors

## Project Structure

```
/
├── server.py           # WebSocket proxy & auth handler
├── src/
│   ├── components/
│   │   └── LiveAPIDemo.jsx  # Main application logic
│   ├── utils/
│   │   ├── gemini-api.js    # WebSocket client
│   │   └── media-utils.js   # Audio/Video processing
│   └── App.jsx              # Root component
└── public/
    └── audio-processors/    # Audio worklets
```

## Core APIs

### LiveAPI Client

Located in `src/utils/gemini-api.js`, this class manages the WebSocket connection.

```javascript
import { GeminiLiveAPI } from "./utils/gemini-api";

const client = new GeminiLiveAPI(
  "ws://localhost:8080",
  "your-project-id",
  "model-name"
);

client.connect();
client.sendText("Hello GANZA AI");
```

### Media Integration

The app uses AudioWorklets for low-latency audio processing:

- `capture.worklet.js`: Handles microphone input
- `playback.worklet.js`: Handles PCM audio output

## Configuration

- **Model**: Configure in `LiveAPIDemo.jsx` or via environment variables
- **Voice**: Configurable in `LiveAPIDemo.jsx`
- **Proxy Port**: Default `8080` (set in `server.py`)

## Environment Variables

Create a `.env` file with the following variables:

```
GCP_PROJECT_ID=your-project-id
GCP_REGION=us-central1
DEFAULT_MODEL=your-model-name
WS_PORT=8080
DEBUG=false
```

## License

Copyright (c) 2025 GANZA AI

All rights reserved.
