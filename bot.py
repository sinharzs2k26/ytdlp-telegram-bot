import os
import asyncio
import logging
import tempfile
import shutil
import json
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv
import yt_dlp
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("Please set TELEGRAM_BOT_TOKEN environment variable")

# Store user sessions
user_sessions: Dict[int, Dict] = {}

# User agent rotation to avoid bot detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def get_user_session(user_id: int) -> Optional[Dict]:
    """Get user session or create if not exists"""
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    return user_sessions[user_id]

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}!\n\n"
        "🎬 I can download audio/video from various platforms.\n\n"
        "📝 **How to use:**\n"
        "1. Send me a link (YouTube, Instagram, TikTok, etc.)\n"
        "2. I'll show available formats\n"
        "3. Choose your preferred quality\n\n"
        "⚠️ **Note about YouTube:**\n"
        "• Some YouTube videos may require login\n"
        "• Use /cookies command if you have login issues\n\n"
        "⚙️ Commands:\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/cookies - Info about YouTube login issues\n"
        "/cancel - Cancel current operation"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

# Cookies info command
async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookies_info = (
        "🍪 **YouTube Login/Cookies Issue**\n\n"
        "Some YouTube videos require login or show 'Sign in to confirm you're not a bot'.\n\n"
        "**Solutions:**\n"
        "1. **Try again later** - Sometimes it's temporary\n"
        "2. **Use different quality** - Lower qualities often work\n"
        "3. **Try another video** - Not all videos have this issue\n"
        "4. **Use alternative sites** - Many videos are on multiple platforms\n\n"
        "**For developers:**\n"
        "You can use cookies with yt-dlp using:\n"
        "`--cookies-from-browser chrome`\n\n"
        "**Note:** This bot runs on a server and cannot use browser cookies."
    )
    await update.message.reply_text(cookies_info, parse_mode='Markdown')

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 **Help Guide**\n\n"
        "1. **Send a URL**: Just paste any supported video/audio link\n"
        "2. **Choose Format**: I'll show available formats\n"
        "3. **Select Quality**: Choose from the buttons\n\n"
        "⚠️ **Important Notes:**\n"
        "• Large files may take time to upload\n"
        "• Some sites have download restrictions\n"
        "• Maximum file size: 50MB (Telegram free limit)\n"
        "• YouTube may block some videos (use /cookies for info)\n\n"
        "❓ **Having issues?**\n"
        "• Make sure the link is accessible\n"
        "• Try different quality options\n"
        "• Some videos may be age-restricted\n"
        "• Try the 'Fastest (Lowest Quality)' option"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await update.message.reply_text("✅ Operation cancelled.")

async def extract_info(url: str) -> Optional[Dict]:
    """Extract video/audio information using yt-dlp with anti-bot measures"""
    try:
        import random
        user_agent = random.choice(USER_AGENTS)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'user_agent': user_agent,
            'referer': 'https://www.google.com/',
            # Try to avoid bot detection
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls', 'dash'],
                }
            },
            # Retry on failure
            'retries': 3,
            'fragment_retries': 3,
            'skip_unavailable_fragments': True,
            # Throttle to appear more human-like
            'sleep_interval_requests': 1,
            'sleep_interval': 5,
            'max_sleep_interval': 10,
            # Avoid age-restricted content issues
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # If extraction failed, try with simpler options
            if not info:
                logger.info("First extraction failed, trying simpler options...")
                simpler_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': True,
                }
                with yt_dlp.YoutubeDL(simpler_opts) as ydl_simple:
                    info = ydl_simple.extract_info(url, download=False)
            
            return info
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"YouTube download error: {e}")
        # Check if it's a bot detection error
        error_msg = str(e)
        if "Sign in to confirm" in error_msg or "confirm you're not a bot" in error_msg:
            raise Exception("youtube_bot_detection")
        elif "Private video" in error_msg:
            raise Exception("youtube_private")
        elif "Members only" in error_msg:
            raise Exception("youtube_members_only")
        elif "age restricted" in error_msg.lower():
            raise Exception("youtube_age_restricted")
        else:
            raise
    except Exception as e:
        logger.error(f"Error extracting info: {e}")
        raise

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Please send a valid URL starting with http:// or https://")
        return
    
    # Check if URL is from blocked sites
    blacklisted_domains = ['porn', 'xxx', 'adult']
    if any(domain in url.lower() for domain in blacklisted_domains):
        await update.message.reply_text("❌ This content is not supported.")
        return
    
    # Check if it's YouTube
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    
    # Show processing message
    processing_msg = await update.message.reply_text("🔍 Analyzing link...")
    
    try:
        # Extract video info
        info = await extract_info(url)
        
        if not info:
            await processing_msg.edit_text("❌ Could not extract information from this link.")
            return
        
        # Store info in user session
        user_session = get_user_session(user_id)
        user_session.update({
            'url': url,
            'info': info,
            'is_youtube': is_youtube
        })
        
        # Get available formats
        formats = info.get('formats', [])
        
        if not formats:
            await show_audio_options(update, info, processing_msg)
            return
        
        # Prepare format options
        video_formats = []
        audio_formats = []
        
        for f in formats:
            format_id = f.get('format_id')
            ext = f.get('ext', 'unknown')
            filesize = f.get('filesize') or f.get('filesize_approx')
            
            if not format_id:
                continue
            
            # Video formats
            if f.get('vcodec') != 'none':
                height = f.get('height', 0)
                fps = f.get('fps', 0)
                quality = f"{height}p" if height else "Unknown"
                if fps and fps > 30:
                    quality += f"@{int(fps)}fps"
                
                # Get size in MB
                size_mb = round(filesize / (1024 * 1024), 1) if filesize else '?'
                
                video_formats.append({
                    'id': format_id,
                    'quality': quality,
                    'ext': ext,
                    'size': size_mb,
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec')
                })
            
            # Audio only formats
            elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                abr = f.get('abr', 0)
                audio_quality = f"{abr}kbps" if abr else "audio"
                size_mb = round(filesize / (1024 * 1024), 1) if filesize else '?'
                
                audio_formats.append({
                    'id': format_id,
                    'quality': audio_quality,
                    'ext': ext,
                    'size': size_mb,
                    'acodec': f.get('acodec')
                })
        
        # Create keyboard
        keyboard = []
        
        # Add video options (limit to avoid too many buttons)
        if video_formats:
            keyboard.append([InlineKeyboardButton("📹 Video Formats", callback_data='header_video')])
            
            # Group similar qualities
            quality_groups = {}
            for fmt in video_formats:
                quality = fmt['quality']
                if quality not in quality_groups or fmt['size'] > quality_groups[quality].get('size', 0):
                    quality_groups[quality] = fmt
            
            # Show a selection of qualities (low, medium, high)
            selected_formats = []
            for quality in ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']:
                if quality in quality_groups:
                    selected_formats.append(quality_groups[quality])
            
            # If no standard qualities found, take first few
            if not selected_formats:
                selected_formats = list(quality_groups.values())[:4]
            
            for fmt in selected_formats[:6]:  # Limit to 6 formats
                text = f"🎬 {fmt['quality']} ({fmt['ext'].upper()})"
                if fmt['size'] != '?':
                    try:
                        size = float(fmt['size'])
                        text += f" [{size:.1f}MB]"  # .1f for one decimal
                    except:
                        text += f" [{fmt['size']}MB]"
                keyboard.append([InlineKeyboardButton(text, callback_data=f"v_{fmt['id']}")])
        
        # Add audio options
        if audio_formats:
            keyboard.append([InlineKeyboardButton("🎵 Audio Only", callback_data='header_audio')])
            for fmt in audio_formats[:3]:  # Limit to 3 audio formats
                text = f"🎵 {fmt['quality']} ({fmt['ext'].upper()})"
                if fmt['size'] != '?':
                    try:
                        size = float(fmt['size'])
                        text += f" [{size:.1f}MB]"  # .1f for one decimal
                    except:
                         text += f" [{fmt['size']}MB]"
                keyboard.append([InlineKeyboardButton(text, callback_data=f"a_{fmt['id']}")])
        
        # Add best quality options with warning for YouTube
        if is_youtube:
            keyboard.append([InlineKeyboardButton("🏆 Try Best Quality (May Fail)", callback_data='best')])
            keyboard.append([InlineKeyboardButton("⚡ Safe: Low Quality (Usually Works)", callback_data='worst')])
        else:
            keyboard.append([InlineKeyboardButton("🏆 Best Quality", callback_data='best')])
            keyboard.append([InlineKeyboardButton("⚡ Fastest (Lowest Quality)", callback_data='worst')])
        
        # Add YouTube-specific help button
        if is_youtube:
            keyboard.append([InlineKeyboardButton("❓ YouTube Help", callback_data='youtube_help')])
        
        # Add cancel button
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Prepare message with YouTube warning if needed
        title = info.get('title', 'Unknown Title')[:100]
        def format_duration(seconds):
            if not seconds:
                return "Unknown"
            try:
                secs = float(seconds)
                return f"{int(secs // 60)}:{int(secs % 60):02d}"
            except:
                return "Unknown"

        duration_str = format_duration(info.get('duration'))
        
        message = f"🎬 **{title}**\n⏱ Duration: {duration_str}\n\n"
        
        if is_youtube:
            message += "⚠️ **YouTube Note:** Some videos may require login. If download fails, try 'Low Quality' option.\n\n"
        
        message += "👇 **Select a format:**"
        
        await processing_msg.edit_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        error_type = str(e)
        
        if error_type == "youtube_bot_detection":
            error_message = (
                "❌ **YouTube Bot Detection**\n\n"
                "YouTube is asking to 'Sign in to confirm you're not a bot'.\n\n"
                "**Solutions:**\n"
                "1. Try the 'Low Quality' option (often works)\n"
                "2. Try again later\n"
                "3. Use /cookies command for more info\n"
                "4. Try downloading from another site if available"
            )
            keyboard = [
                [InlineKeyboardButton("⚡ Try Low Quality Anyway", callback_data='worst')],
                [InlineKeyboardButton("📚 YouTube Help", callback_data='youtube_help')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_msg.edit_text(error_message, reply_markup=reply_markup, parse_mode='Markdown')
        
        elif error_type == "youtube_private":
            await processing_msg.edit_text("❌ This YouTube video is private.")
        
        elif error_type == "youtube_members_only":
            await processing_msg.edit_text("❌ This YouTube video is for members only.")
        
        elif error_type == "youtube_age_restricted":
            await processing_msg.edit_text("❌ This YouTube video is age-restricted. Please login on YouTube to watch.")
        
        else:
            logger.error(f"Error processing URL: {e}")
            await processing_msg.edit_text(f"❌ Error: {str(e)[:100]}")

async def show_audio_options(update: Update, info: Dict, message):
    """Show audio format options"""
    keyboard = [
        [InlineKeyboardButton("🎵 MP3 (Best Quality)", callback_data="audio_mp3_best")],
        [InlineKeyboardButton("🎵 MP3 (128kbps)", callback_data="audio_mp3_128")],
        [InlineKeyboardButton("🎵 M4A/AAC", callback_data="audio_m4a")],
        [InlineKeyboardButton("🎵 Opus", callback_data="audio_opus")],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    title = info.get('title', 'Audio Content')[:100]
    message_text = f"🎵 **{title}**\n\nSelect audio format:"
    
    await message.edit_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

async def download_file(url: str, format_spec: str, temp_dir: str, is_youtube: bool = False) -> List[str]:
    """Download file using yt-dlp with anti-bot measures"""
    import random
    
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [],
        'user_agent': random.choice(USER_AGENTS),
        'retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
    }
    
    # For YouTube, use conservative settings to avoid bot detection
    if is_youtube:
        ydl_opts.update({
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'skip': ['hls', 'dash'],
                }
            },
            'throttled_rate': '100K',  # Limit download speed
        })
    
    if format_spec == 'best':
        if is_youtube:
            # For YouTube, don't use 'best' as it often triggers bot detection
            ydl_opts['format'] = 'bv[height<=720]+ba/b[height<=720]'
        else:
            ydl_opts['format'] = 'best'
    elif format_spec == 'worst':
        ydl_opts['format'] = 'worst'
    elif format_spec == 'youtube_help':
        raise Exception("youtube_help_clicked")
    elif format_spec.startswith('v_'):
        ydl_opts['format'] = format_spec[2:]
    elif format_spec.startswith('a_'):
        ydl_opts['format'] = format_spec[2:]
    elif format_spec == 'audio_mp3_best':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    elif format_spec == 'audio_mp3_128':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
        })
    elif format_spec == 'audio_m4a':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
            }],
        })
    elif format_spec == 'audio_opus':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
            }],
        })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Sign in to confirm" in error_msg:
            raise Exception("youtube_bot_detection_download")
        else:
            raise
    
    # Find downloaded files
    downloaded_files = []
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(('.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.opus', '.aac', '.flac', '.wav')):
                downloaded_files.append(os.path.join(root, file))
    
    return downloaded_files

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == 'cancel':
        if user_id in user_sessions:
            del user_sessions[user_id]
        await query.edit_message_text("✅ Operation cancelled.")
        return
    
    if data == 'youtube_help':
        help_text = (
            "🆘 **YouTube Download Help**\n\n"
            "**Common Issues:**\n"
            "1. **'Sign in to confirm you're not a bot'** - YouTube bot detection\n"
            "2. **Age-restricted content** - Requires YouTube login\n"
            "3. **Private/Members-only videos** - Cannot be downloaded\n\n"
            "**Solutions:**\n"
            "✅ Try 'Low Quality' option (often bypasses detection)\n"
            "✅ Try again in a few hours\n"
            "✅ Use alternative video sites if available\n"
            "❌ Browser cookies cannot be used on server\n\n"
            "**Why this happens:**\n"
            "YouTube detects automated downloads and may block them.\n"
            "This is a limitation of server-based downloaders."
        )
        await query.edit_message_text(help_text, parse_mode='Markdown')
        return
    
    user_session = get_user_session(user_id)
    url = user_session['url']
    info = user_session.get('info', {})
    is_youtube = user_session.get('is_youtube', False)
    
    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Update message to show downloading
        await query.edit_message_text("⏬ Downloading... Please wait.")
        
        # Download the file
        downloaded_files = await download_file(url, data, temp_dir, is_youtube)
        
        if not downloaded_files:
            await query.edit_message_text("❌ No file was downloaded.")
            return
        
        # Send files to user
        for file_path in downloaded_files:
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            # Check file size (Telegram limit: 50MB for free users)
            if file_size > 50 * 1024 * 1024:
                size_mb = file_size / (1024 * 1024)
                await query.edit_message_text(
                    f"⚠️ File too large ({size_mb:.1f}MB). "
                    f"Telegram limit is 50MB for free users.\n"
                    f"Try selecting a lower quality format."
                )
                continue
            
            # Determine file type and send
            ext = os.path.splitext(file_path)[1].lower()
            
            with open(file_path, 'rb') as file:
                if ext in ['.mp3', '.m4a', '.opus', '.aac', '.flac', '.wav']:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=file,
                        caption=f"🎵 {file_name}",
                        title=info.get('title', 'Downloaded Audio')[:64],
                        performer=info.get('uploader', 'Unknown')[:64],
                    )
                else:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=file,
                        caption=f"🎬 {file_name}",
                        supports_streaming=True,
                    )
        
        await query.edit_message_text("✅ Download complete! 🎉")
        
    except Exception as e:
        error_type = str(e)
        
        if error_type == "youtube_bot_detection_download":
            error_message = (
                "❌ **YouTube Bot Detection During Download**\n\n"
                "YouTube blocked the download.\n\n"
                "**Try this:**\n"
                "1. Select 'Low Quality' option (most likely to work)\n"
                "2. Wait a few hours and try again\n"
                "3. The video might be temporarily blocked\n\n"
                "**Note:** This is a YouTube limitation, not a bot issue."
            )
            keyboard = [
                [InlineKeyboardButton("⚡ Try Low Quality", callback_data='worst')],
                [InlineKeyboardButton("🔄 Send Link Again", callback_data='retry')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(error_message, reply_markup=reply_markup, parse_mode='Markdown')
        
        elif error_type == "youtube_help_clicked":
            # Already handled above
            pass
        
        else:
            logger.error(f"Download error: {e}")
            error_msg = str(e)[:200]
            await query.edit_message_text(f"❌ Download failed: {error_msg}")
    
    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Error cleaning temp dir: {e}")
        
        # Clear user session (unless we're showing retry options)
        if user_id in user_sessions and data not in ['youtube_help', 'retry']:
            del user_sessions[user_id]

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred. Please try again."
        )

def main():
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cookies", cookies_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("🤖 Bot is starting...")
    logger.info("📡 Press Ctrl+C to stop")
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is alive!')
        
        def log_message(self, format, *args):
            pass  # Silence logs

    def run_health_server():
        port = int(os.environ.get("PORT", 10000))
        httpd = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"✅ Health server on port {port}")
        httpd.serve_forever()
    
    # Start health server
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
       )

if __name__ == '__main__':
    main()