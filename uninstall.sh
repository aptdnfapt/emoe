#!/bin/bash

# Uninstallation script for Moe Discord Bot Docker Compose setup

# --- Configuration ---
BOT_IMAGE_NAME="emoe_bot" # Default image name is <directory>_<service>, e.g., emoe_bot
# Volume name is usually <directory>_<volume_name_in_compose_file>
OLLAMA_VOLUME_NAME="emoe_ollama_data"
CONFIG_FILE="bot_config.json"
LOG_FILE="chat_log.jsonl"

# --- Helper Functions ---
check_command() {
  if ! command -v "$1" &>/dev/null; then
    echo "Warning: Command '$1' not found. Cannot guarantee complete cleanup."
    # Continue script execution if possible
  fi
}

# --- Main Script ---
echo "Starting Moe Discord Bot Docker Cleanup..."

# Check Prerequisites
check_command docker
check_command docker-compose

# Check if running from the correct directory (basic check)
if [ ! -f "docker-compose.yml" ]; then
  echo "Error: Please run this script from the main project directory (e.g., '~/emoe') where 'docker-compose.yml' exists."
  exit 1
fi

# 1. Stop and Remove Containers
echo "Stopping and removing Docker Compose services (ollama, bot)..."
docker-compose down
if [ $? -ne 0 ]; then
  echo "Warning: 'docker-compose down' failed. Containers might still be running."
fi
echo "Services stopped and containers removed."

# 2. Remove Bot Docker Image
echo "Attempting to remove bot Docker image ('$BOT_IMAGE_NAME')..."
# Use docker images -q to find the image ID if the name lookup fails sometimes
IMAGE_ID=$(docker images -q $BOT_IMAGE_NAME)
if [ -n "$IMAGE_ID" ]; then
  docker rmi "$BOT_IMAGE_NAME"
  if [ $? -ne 0 ]; then
    echo "Warning: Failed to remove image '$BOT_IMAGE_NAME' by name, trying by ID ($IMAGE_ID)..."
    docker rmi "$IMAGE_ID" || echo "Warning: Failed to remove image '$BOT_IMAGE_NAME' (ID: $IMAGE_ID) even by ID."
  fi
else
  echo "Warning: Image '$BOT_IMAGE_NAME' not found."
fi
echo "Bot image removal attempted."

# 3. Remove Ollama Data Volume
echo "Attempting to remove Ollama data volume ('$OLLAMA_VOLUME_NAME')..."
docker volume rm "$OLLAMA_VOLUME_NAME"
if [ $? -ne 0 ]; then
  echo "Warning: Failed to remove volume '$OLLAMA_VOLUME_NAME'. It might not exist or be in use."
fi
echo "Ollama data volume removal attempted."

# 4. Remove Ollama Base Image
echo "Attempting to remove base Ollama image ('ollama/ollama')..."
docker rmi ollama/ollama
if [ $? -ne 0 ]; then
  echo "Warning: Failed to remove image 'ollama/ollama'. It might not exist or be in use by other containers."
fi
echo "Base Ollama image removal attempted."

# 5. Remove Host Files
echo "Removing host configuration and log files..."
if [ -f "$CONFIG_FILE" ]; then
  rm "$CONFIG_FILE"
  echo "Removed $CONFIG_FILE."
fi
if [ -f "$LOG_FILE" ]; then
  rm "$LOG_FILE"
  echo "Removed $LOG_FILE."
fi
# Also remove directories if they were created incorrectly before
if [ -d "$CONFIG_FILE" ]; then
  rm -rf "$CONFIG_FILE"
  echo "Removed directory $CONFIG_FILE/."
fi
if [ -d "$LOG_FILE" ]; then
  rm -rf "$LOG_FILE"
  echo "Removed directory $LOG_FILE/."
fi

# 6. Confirmation
echo ""
echo "----------------------------------------"
echo "Moe Discord Bot Docker cleanup complete."
echo "Containers, the bot image, and the Ollama data volume have been removed (if they existed)."
echo "Your source code files remain untouched."
echo "----------------------------------------"

exit 0
