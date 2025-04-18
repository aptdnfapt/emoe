import discord
from discord.ext import commands
import os
import requests
import json
import asyncio
import re # Import regular expression module
import random # Import random module for probability
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
CONFIG_FILE = "bot_config.json"
LOG_FILE = "chat_log.jsonl"

# --- Globals ---
dedicated_channel_id = None # Will be loaded from config
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True # Keep for potential future use or guild-specific info
# Use commands.Bot instead of discord.Client for prefix commands
bot = commands.Bot(command_prefix="emoe ", intents=intents) # Set prefix here


# --- Config Persistence ---
def load_config():
    """Loads configuration from the JSON file."""
    global dedicated_channel_id
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                dedicated_channel_id = config.get('dedicated_channel_id')
                print(f"Loaded config: Dedicated channel ID = {dedicated_channel_id}")
        else:
            print("Config file not found. Will create one if channel is set.")
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading config file: {e}")
        dedicated_channel_id = None

def save_config():
    """Saves the current configuration to the JSON file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'dedicated_channel_id': dedicated_channel_id}, f, indent=4)
        print(f"Saved config: Dedicated channel ID = {dedicated_channel_id}")
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
# (Keep the Ollama function as is)
async def get_ollama_response(prompt):
    """Sends prompt to Ollama and returns the generated response."""
    if not OLLAMA_API_URL:
        print("Error: OLLAMA_API_URL environment variable not set.")
        return "Sorry, my connection to the language model is not configured."

    api_endpoint = f"{OLLAMA_API_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True # Use streaming for potentially long responses
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
                    if 'response' in data and not data.get('done', False):
                        response_text += data['response']
                    elif data.get('done', False):
                        # Optionally process final context if needed
                        # final_context = data.get('context')
                        break # Exit loop when generation is done
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON line: {line}")
                    continue # Skip malformed lines

        modified_response = response_text

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
    global dedicated_channel_id

    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Check if the message starts with the command prefix, if so, let the command handler process it
    if message.content.startswith(bot.command_prefix):
        await bot.process_commands(message) # Process potential commands
        return # Stop further processing for this message

    # --- Regular Message Handling (Not a command) ---

    # Check if it's in the dedicated channel
    if dedicated_channel_id and message.channel.id == dedicated_channel_id:
        async with message.channel.typing():
            user_input = message.content
            bot_output = await get_ollama_response(user_input)
            if bot_output: # Only send and log if Ollama returned something
                await message.reply(bot_output)
                log_chat(user_input, bot_output) # Log the interaction
        return # Don't process further if it was in the dedicated channel

    # Check if the message is in a public channel and contains trigger words
    if not dedicated_channel_id or message.channel.id != dedicated_channel_id:
        message_lower = message.content.lower()
        if any(trigger in message_lower for trigger in REPLY_TRIGGERS):
            async with message.channel.typing():
                user_input = message.content
                bot_output = await get_ollama_response(user_input)
                if bot_output: # Only send and log if Ollama returned something
                    await message.reply(bot_output)
                    log_chat(user_input, bot_output) # Log the interaction
            return

# --- Discord Prefix Commands ---
@bot.command(name="setchannel", help="Sets the dedicated channel for Emoe Bot interactions. Usage: emoe setchannel #channel-name")
@commands.has_permissions(administrator=True) # Check for administrator permissions
async def setchannel_command(ctx: commands.Context, channel: discord.TextChannel):
    """Command to set the dedicated channel."""
    global dedicated_channel_id
    dedicated_channel_id = channel.id
    save_config() # Save the new channel ID to the config file
    await ctx.send(f"Emoe Bot dedicated channel set to {channel.mention}", delete_after=10) # Send confirmation and delete after a bit
    try:
        await ctx.message.delete() # Try to delete the command message
    except discord.Forbidden:
        pass # Ignore if bot doesn't have permission to delete messages

@setchannel_command.error
async def setchannel_command_error(ctx: commands.Context, error):
    """Error handler for the setchannel command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need administrator permissions to use this command.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
         await ctx.send(f"You need to specify a channel. Usage: `{bot.command_prefix}setchannel #channel-name`", delete_after=10)
    elif isinstance(error, commands.ChannelNotFound):
         await ctx.send(f"Could not find the channel '{error.argument}'. Please mention the channel correctly (`#channel-name`).", delete_after=10)
    else:
        await ctx.send(f"An unexpected error occurred: {error}", delete_after=10)
        print(f"Error in setchannel command: {error}")
    try:
        await ctx.message.delete() # Try to delete the command message
    except discord.Forbidden:
        pass # Ignore if bot doesn't have permission to delete messages


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

