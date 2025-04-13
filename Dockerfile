# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot script
COPY moe_bot.py .
# Note: .env, bot_config.json and chat_log.jsonl are handled via env-file and volumes

# Define the command to run the bot when the container launches
CMD ["python", "moe_bot.py"]
