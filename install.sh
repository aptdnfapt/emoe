#!/bin/bash

# Simple installation script for Moe Discord Bot using Docker Compose

# --- Configuration ---
OLLAMA_MODEL_NAME="hf.co/mradermacher/DialoGPT-large-gavin-GGUF:F16"
ENV_FILE=".env"
CONFIG_FILE="bot_config.json"
LOG_FILE="chat_log.jsonl"            # Even if logging is off in code, create file to prevent dir creation
OLLAMA_SERVICE_NAME="ollama_service" # Must match container_name in docker-compose.yml

# --- Helper Functions ---
check_command() {
  if ! command -v "$1" &>/dev/null; then
    echo "Error: Required command '$1' not found. Please install it and try again."
    exit 1
  fi
}

# --- Main Script ---
echo "Starting Moe Discord Bot Docker Setup..."

# 1. Check Prerequisites
echo "Checking for Docker and Docker Compose..."
check_command docker
check_command docker-compose
echo "Prerequisites found."

# 2. Check if running from the correct directory (basic check)
if [ ! -f "$ENV_FILE" ] || [ ! -f "docker-compose.yml" ]; then
  echo "Error: Please run this script from the main project directory (e.g., '~/emoe') where '$ENV_FILE' and 'docker-compose.yml' exist."
  exit 1
fi

# 3. Update .env file
echo "Configuring Discord Bot Token..."
TOKEN_LINE_EXISTS=$(grep -c "^DISCORD_BOT_TOKEN=" "$ENV_FILE")
CURRENT_TOKEN=$(grep "^DISCORD_BOT_TOKEN=" "$ENV_FILE" | cut -d '=' -f2-)

# Check if token line exists and has a non-empty, non-placeholder value
if [ "$TOKEN_LINE_EXISTS" -eq 1 ] && [ -n "$CURRENT_TOKEN" ] && [ "$CURRENT_TOKEN" != "YOUR_DISCORD_BOT_TOKEN_HERE" ]; then
  echo "Discord Bot Token seems to be already set in $ENV_FILE. Skipping prompt."
else
  # Prompt for token if line is missing, empty, or has placeholder
  read -p "Please enter your Discord Bot Token: " DISCORD_TOKEN
  if [ -z "$DISCORD_TOKEN" ]; then
    echo "Error: Discord Bot Token cannot be empty."
    exit 1
  fi

  # Check again if the line exists to decide whether to replace or append
  if grep -q "^DISCORD_BOT_TOKEN=" "$ENV_FILE"; then
    # Line exists, replace it using sed
    echo "Updating existing DISCORD_BOT_TOKEN line..."
    # Using a different delimiter (#) for sed in case token has slashes or other special chars
    sed -i.bak "s#^DISCORD_BOT_TOKEN=.*#DISCORD_BOT_TOKEN=$DISCORD_TOKEN#" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak" # Remove backup file created by sed -i
  else
    # Line doesn't exist, append it
    echo "Adding DISCORD_BOT_TOKEN line..."
    echo "" >>"$ENV_FILE" # Add a newline just in case file doesn't end with one
    echo "DISCORD_BOT_TOKEN=$DISCORD_TOKEN" >>"$ENV_FILE"
  fi
  echo ".env file updated with your token."
fi

# Verify OLLAMA_API_URL is set for compose (keep this check)
if ! grep -q "OLLAMA_API_URL=http://ollama:11434" "$ENV_FILE"; then
  echo "Warning: OLLAMA_API_URL in $ENV_FILE might not be set correctly for docker-compose."
  echo "It should usually be 'http://ollama:11434'."
  read -p "Press Enter to continue anyway, or Ctrl+C to abort and fix $ENV_FILE..."
fi

# 4. Prepare Host Files
echo "Creating placeholder files for Docker volumes..."
touch "$CONFIG_FILE"
touch "$LOG_FILE"
echo "Placeholder files created."

# 5. Download Ollama Model
echo "Starting Ollama service to download the model..."
docker-compose up -d ollama
echo "Waiting a few seconds for Ollama service to initialize..."
sleep 10 # Give Ollama some time to start

echo "Pulling Ollama model ($OLLAMA_MODEL_NAME)... This might take a while."
# Check if ollama service is running before exec
if docker ps --filter "name=$OLLAMA_SERVICE_NAME" --filter "status=running" | grep -q $OLLAMA_SERVICE_NAME; then
  docker exec "$OLLAMA_SERVICE_NAME" ollama pull "$OLLAMA_MODEL_NAME"
  if [ $? -ne 0 ]; then
    echo "Error: Failed to pull Ollama model. Please check Ollama logs ('docker logs $OLLAMA_SERVICE_NAME') and network connection."
    # Optionally stop ollama here? Or let user handle it.
    # docker-compose down
    # exit 1
    echo "Continuing setup, but the bot might not work until the model is pulled successfully."
  else
    echo "Ollama model pulled successfully."
  fi
else
  echo "Error: Ollama service ($OLLAMA_SERVICE_NAME) failed to start. Cannot pull model."
  echo "Please check Docker Compose logs ('docker-compose logs ollama') and try again."
  # Optionally stop here
  # docker-compose down
  # exit 1
  echo "Continuing setup, but the bot will likely fail."
fi

# 6. Launch All Services
echo "Starting all services (Ollama and Bot)..."
docker-compose up -d
if [ $? -ne 0 ]; then
  echo "Error: Failed to start services with docker-compose. Check logs ('docker-compose logs')."
  exit 1
fi

# 7. Confirmation
echo ""
echo "----------------------------------------"
echo "Moe Discord Bot setup complete!"
echo "Both Ollama and the Bot should be running in Docker containers."
echo "Use 'docker ps' to check running containers."
echo "Use 'docker-compose logs -f bot' to view bot logs."
echo "Use 'docker-compose down' in this directory to stop the services."
echo "----------------------------------------"

exit 0
