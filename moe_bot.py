import discord
from discord.ext import commands
import os
import requests
import json
import asyncio
import re # Import regular expression module
import random # Import random module for probability
import time # Import time module for cooldown
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL") # e.g., http://localhost:11434
OLLAMA_MODEL = "hf.co/mradermacher/DialoGPT-large-gavin-GGUF:F16"
REPLY_TRIGGERS = ["moe", "evilmoe", "meow"]
WORD_REPLACEMENTS_STR = os.getenv("WORD_REPLACEMENTS", "gaven:moe") # Default if not set

# --- Parse Word Replacements ---
replacement_pairs = {}
try:
    if WORD_REPLACEMENTS_STR:
        pairs = WORD_REPLACEMENTS_STR.split(',')
        for pair in pairs:
            if ':' in pair:
                find_word, replace_word = pair.split(':', 1)
                # Store the find_word (lowercase for matching) and the replacement
                # We compile the regex here for efficiency
                replacement_pairs[find_word.strip()] = (
                    re.compile(re.escape(find_word.strip()), re.IGNORECASE), # Compiled regex for case-insensitive find
                    replace_word.strip() # Replacement word
                )
            else:
                print(f"Warning: Skipping invalid replacement pair format: {pair}")
except Exception as e:
    print(f"Error parsing WORD_REPLACEMENTS: {e}. Using default 'gaven:moe'.")
    replacement_pairs = {
         "gaven": (re.compile(re.escape("gaven"), re.IGNORECASE), "moe")
    }

# --- Parse Probabilistic Replacements ---
PROBABILISTIC_REPLACEMENTS_STR = os.getenv("PROBABILISTIC_REPLACEMENTS", "")
probabilistic_rules = []
try:
    if PROBABILISTIC_REPLACEMENTS_STR:
        rules = PROBABILISTIC_REPLACEMENTS_STR.split(';')
        for rule in rules:
            rule = rule.strip() # Remove leading/trailing whitespace from the rule itself
            if rule.count('|') == 2:
                target, prob_str, options_str = rule.split('|', 2)
                target = target.strip()
                options = [opt.strip() for opt in options_str.split(',') if opt.strip()] # Ensure options are stripped and not empty
                try:
                    probability = float(prob_str.strip())
                    if 0.0 <= probability <= 1.0 and target and options:
                        compiled_regex = re.compile(re.escape(target), re.IGNORECASE)
                        probabilistic_rules.append((compiled_regex, probability, options))
                        print(f"Loaded probabilistic rule: Target='{target}', Prob={probability}, Options={options}")
                    else:
                        print(f"Warning: Invalid probability ({probability}) or empty target/options in rule: {rule}")
                except ValueError:
                    print(f"Warning: Invalid probability format ('{prob_str.strip()}') in rule: {rule}")
            elif rule: # Only warn if the rule string is not empty
                 print(f"Warning: Skipping invalid probabilistic rule format (needs 2 '|'): {rule}")
except Exception as e:
    print(f"Error parsing PROBABILISTIC_REPLACEMENTS: {e}")


# --- Configuration Files ---
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bot_config.json") # Path relative to script
LOG_FILE = "chat_log.jsonl"
MAX_HISTORY_PROMPTS = 5 # Number of user/assistant pairs to keep in history

# --- Globals ---
guild_configs = {} # Stores config per guild ID {guild_id: {"dedicated_channels": [id1, id2]}}
user_last_response_time = {} # Stores the last response timestamp for each user ID
conversation_history = {} # Stores message history per channel {channel_id: [{"role": "user/assistant", "content": "..."}, ...]}
COOLDOWN_SECONDS = 5 # Cooldown period in seconds
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True # Keep for potential future use or guild-specific info
# Use commands.Bot instead of discord.Client for prefix commands
bot = commands.Bot(command_prefix="emoe ", intents=intents) # Set prefix here


# --- Config Persistence ---
def load_config():
    """Loads configuration from the JSON file."""
    global guild_configs
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                guild_configs = json.load(f)
                # Ensure keys are integers if loaded from JSON as strings
                guild_configs = {int(k): v for k, v in guild_configs.items()}
                print(f"Loaded config: {len(guild_configs)} guild(s) configured.")
        else:
            print("Config file not found. Initializing empty config.")
            guild_configs = {}
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading config file: {e}")
        guild_configs = {} # Default to empty dict on error

def save_config():
    """Saves the current configuration to the JSON file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(guild_configs, f, indent=4)
        print(f"Saved config for {len(guild_configs)} guild(s).")
    except IOError as e:
        print(f"Error saving config file: {e}")

# --- Chat Logging ---
def log_chat(instruction, output):
    """Logs the instruction and output to the JSONL file."""
    log_entry = {"instruction": instruction, "output": output}
    try:
        with open(LOG_FILE, 'a') as f: # Append mode
            f.write(json.dumps(log_entry) + '\n')
    except IOError as e:
        print(f"Error writing to log file: {e}")


# --- Ollama Interaction ---
async def get_ollama_response(messages):
    """Sends message history to Ollama chat endpoint and returns the generated response."""
    if not OLLAMA_API_URL:
        print("Error: OLLAMA_API_URL environment variable not set.")
        return "Sorry, my connection to the language model is not configured."

    # Use the /api/chat endpoint for conversational context
    api_endpoint = f"{OLLAMA_API_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages, # Send the list of message objects
        "stream": True
    }

    try:
        response_text = ""
        # Use asyncio.to_thread to run the blocking requests call in a separate thread
        response = await asyncio.to_thread(
            requests.post, api_endpoint, json=payload, stream=True
        )
        response.raise_for_status() # Raise an exception for bad status codes

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    # For /api/chat, the response content is in message.content
                    if 'message' in data and 'content' in data['message'] and not data.get('done', False):
                        response_text += data['message']['content']
                    elif data.get('done', False):
                        break # Exit loop when generation is done
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON line: {line}")
                    continue # Skip malformed lines

        modified_response = response_text.strip() # Strip leading/trailing whitespace from the combined response

        # Apply probabilistic replacements first
        if probabilistic_rules:
            for compiled_regex, probability, options in probabilistic_rules:
                # Define the replacement function inside the loop to capture the correct probability and options
                def probabilistic_replace(match):
                    # This function is called for each match found by re.sub
                    if random.random() < probability:
                        chosen_option = random.choice(options)
                        # print(f"Probabilistic replace: '{match.group(0)}' -> '{chosen_option}' (Prob: {probability})") # Debug print
                        return chosen_option
                    else:
                        # print(f"Probabilistic skip: '{match.group(0)}' (Prob: {probability})") # Debug print
                        return match.group(0) # Return the original match if probability check fails

                modified_response = compiled_regex.sub(probabilistic_replace, modified_response)


        # Apply standard case-insensitive replacements from .env
        if replacement_pairs:
            for find_word, (compiled_regex, replace_word) in replacement_pairs.items():
                 modified_response = compiled_regex.sub(replace_word, modified_response)

        return modified_response.strip()

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Ollama: {e}")
        return f"Sorry, I encountered an error trying to reach the language model: {e}"
    except Exception as e:
        print(f"An unexpected error occurred during Ollama interaction: {e}")
        return "Sorry, an unexpected error occurred."


# --- Discord Event Handlers ---
@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    load_config() # Load the config on startup
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    # No need to sync slash commands anymore
    print("Emoe Bot is ready.")


@bot.event
async def on_message(message):
    """Called when a message is sent in a channel the bot can see."""
    global guild_configs, user_last_response_time, conversation_history

    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Ignore messages from DMs (commands should handle this if needed)
    if not message.guild:
        return

    # Check if the message starts with the command prefix, if so, let the command handler process it
    if message.content.startswith(bot.command_prefix):
        await bot.process_commands(message) # Process potential commands
        return # Stop further processing for this message

    # --- Cooldown Check ---
    user_id = message.author.id
    current_time = time.time()
    last_response_time = user_last_response_time.get(user_id, 0)

    if current_time - last_response_time < COOLDOWN_SECONDS:
        # print(f"User {user_id} is on cooldown. Ignoring message.") # Optional debug print
        return # Ignore message if user is on cooldown


    # --- Regular Message Handling (Not a command) ---

    # --- Regular Message Handling (Not a command) ---
    guild_id = message.guild.id
    channel_id = message.channel.id
    dedicated_channels = guild_configs.get(guild_id, {}).get("dedicated_channels", [])

    # Determine if the bot should respond (in dedicated channel or triggered)
    should_respond = False
    if channel_id in dedicated_channels:
        should_respond = True
    else:
        message_lower = message.content.lower()
        if any(trigger in message_lower for trigger in REPLY_TRIGGERS):
            should_respond = True

    if should_respond:
        async with message.channel.typing():
            user_last_response_time[user_id] = current_time # Update last response time immediately
            user_input = message.content

            # --- History Management ---
            # Get or initialize history for this channel
            channel_history = conversation_history.setdefault(channel_id, [])

            # Create the message list for Ollama
            current_message = {"role": "user", "content": user_input}
            messages_to_send = channel_history + [current_message]

            # Call Ollama with the history
            bot_output = await get_ollama_response(messages_to_send)

            if bot_output: # Only send, log, and update history if Ollama returned something
                await message.reply(bot_output)
                log_chat(user_input, bot_output) # Log the interaction

                # Add user message and bot response to history
                channel_history.append(current_message)
                channel_history.append({"role": "assistant", "content": bot_output})

                # Trim history if it exceeds the limit (MAX_HISTORY_PROMPTS pairs = * 2 messages)
                max_len = MAX_HISTORY_PROMPTS * 2
                if len(channel_history) > max_len:
                    # Keep only the last max_len messages
                    conversation_history[channel_id] = channel_history[-max_len:]
                    # print(f"Trimmed history for channel {channel_id} to {max_len} messages.") # Optional debug print

        return # Stop processing after handling the response

# --- Discord Prefix Commands ---
# Helper function to get guild-specific dedicated channels
def get_guild_dedicated_channels(guild_id):
    return guild_configs.setdefault(guild_id, {}).setdefault("dedicated_channels", [])

@bot.command(name="add", help="Adds a channel to the list of dedicated channels for this server. Usage: emoe add #channel-name")
@commands.has_permissions(administrator=True) # Check for administrator permissions
@commands.guild_only() # Ensure command is run in a server
async def add_command(ctx: commands.Context, channel: discord.TextChannel):
    """Command to add a dedicated channel for the current server."""
    global guild_configs
    guild_id = ctx.guild.id
    dedicated_channels = get_guild_dedicated_channels(guild_id)

    if channel.id not in dedicated_channels:
        dedicated_channels.append(channel.id)
        save_config() # Save the updated config
        await ctx.send(f"Channel {channel.mention} added to the dedicated channels list for this server.", delete_after=10)
    else:
        await ctx.send(f"Channel {channel.mention} is already in the dedicated channels list for this server.", delete_after=10)
    try:
        await ctx.message.delete() # Try to delete the command message
    except discord.Forbidden:
        pass # Ignore if bot doesn't have permission to delete messages

@add_command.error
async def add_command_error(ctx: commands.Context, error):
    """Error handler for the add command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
         await ctx.send(f"You need to specify a channel. Usage: `{bot.command_prefix}add #channel-name`", delete_after=10)
    elif isinstance(error, commands.ChannelNotFound):
         await ctx.send(f"Could not find the channel '{error.argument}'. Please mention the channel correctly (`#channel-name`).", delete_after=10)
    elif isinstance(error, commands.NoPrivateMessage):
         await ctx.send("This command can only be used in a server.", delete_after=10)
    else:
        await ctx.send(f"An unexpected error occurred: {error}", delete_after=10)
        print(f"Error in add command: {error}")
    try:
        await ctx.message.delete() # Try to delete the command message
    except discord.Forbidden:
        pass # Ignore if bot doesn't have permission to delete messages

@bot.command(name="remove", help="Removes a channel from the list of dedicated channels for this server. Usage: emoe remove #channel-name")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def remove_command(ctx: commands.Context, channel: discord.TextChannel):
    """Command to remove a dedicated channel for the current server."""
    global guild_configs
    guild_id = ctx.guild.id
    dedicated_channels = get_guild_dedicated_channels(guild_id)

    if channel.id in dedicated_channels:
        dedicated_channels.remove(channel.id)
        save_config()
        await ctx.send(f"Channel {channel.mention} removed from the dedicated channels list for this server.", delete_after=10)
    else:
        await ctx.send(f"Channel {channel.mention} is not in the dedicated channels list for this server.", delete_after=10)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

@remove_command.error
async def remove_command_error(ctx: commands.Context, error):
    """Error handler for the remove command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
         await ctx.send(f"You need to specify a channel. Usage: `{bot.command_prefix}remove #channel-name`", delete_after=10)
    elif isinstance(error, commands.ChannelNotFound):
         await ctx.send(f"Could not find the channel '{error.argument}'. Please mention the channel correctly (`#channel-name`).", delete_after=10)
    elif isinstance(error, commands.NoPrivateMessage):
         await ctx.send("This command can only be used in a server.", delete_after=10)
    else:
        await ctx.send(f"An unexpected error occurred: {error}", delete_after=10)
        print(f"Error in remove command: {error}")
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

@bot.command(name="list", help="Lists the dedicated channels for this server.")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def list_command(ctx: commands.Context):
    """Command to list dedicated channels for the current server."""
    guild_id = ctx.guild.id
    dedicated_channels = get_guild_dedicated_channels(guild_id)

    if not dedicated_channels:
        await ctx.send("No dedicated channels are currently set for this server.", delete_after=10)
    else:
        channel_mentions = []
        for channel_id in dedicated_channels:
            channel = bot.get_channel(channel_id) # Use bot.get_channel
            if channel:
                channel_mentions.append(channel.mention)
            else:
                channel_mentions.append(f"Unknown Channel (ID: {channel_id})") # Handle case where channel might not be accessible
        await ctx.send(f"Dedicated channels for this server: {', '.join(channel_mentions)}", delete_after=10)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

@list_command.error
async def list_command_error(ctx: commands.Context, error):
    """Error handler for the list command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.", delete_after=10)
    elif isinstance(error, commands.NoPrivateMessage):
         await ctx.send("This command can only be used in a server.", delete_after=10)
    else:
        await ctx.send(f"An unexpected error occurred: {error}", delete_after=10)
        print(f"Error in list command: {error}")
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


# --- Run the Bot ---
if __name__ == "__main__":
    # No need to add command groups like before

    if DISCORD_BOT_TOKEN is None:
        print("Error: DISCORD_BOT_TOKEN environment variable not set or found in .env file.")
    elif OLLAMA_API_URL is None:
         print("Warning: OLLAMA_API_URL environment variable not set or found in .env file. Bot will run but cannot contact Ollama.")
         bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Starting Emoe Bot...")
        bot.run(DISCORD_BOT_TOKEN)
