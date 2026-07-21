import os
import tempfile
import uuid
import time
import requests
import json
from flask import Flask, request, jsonify
import yt_dlp

app = Flask(__name__)

# This will be securely set in your hosting provider's dashboard
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@app.route('/api/analyze-social-video', methods=['POST'])
def analyze_social_video():
    data = request.json
    url = data.get('url')

    if not url:
        return jsonify({"error": "URL is required"}), 400

    # 1. MODIFIED PROMPT: Updated to match the React Native PlantDetailScreen structure
    prompt = """Analyze this video and return a strictly formatted JSON object summarizing the plant featured in it.
    The JSON must match this exact structure:
    {
        "title": "The common name of the plant (e.g., 'Fiddle Leaf Fig')",
        "subtitle": "The scientific name of the plant (e.g., 'Ficus lyrata')",
        "badgeText": "A short category description (e.g., 'Tropical Evergreen', 'Succulent', 'Air Plant')",
        "description": "A detailed, engaging paragraph about this plant, its characteristics, and why it's popular.",
        "care": {
            "light": "Light requirement (e.g., 'Bright Indirect')",
            "water": "Water requirement (e.g., 'Every 7-10 days')",
            "soil": "Soil type (e.g., 'Well-Draining')",
            "fertilizer": "Fertilizer frequency (e.g., 'Once monthly')"
        },
        "expertTip": "One useful, actionable expert tip for taking care of this specific plant."
    }"""

    # Create a safe base path in the system's temp directory
    base_path = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
    actual_file_path = None
    thumbnail_url = "" # Initialize empty thumbnail URL

    try:
        # Download video and let yt-dlp determine the correct file extension
        ydl_opts = {
            'quiet': True,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True,
            'outtmpl': f"{base_path}.%(ext)s" 
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            actual_file_path = ydl.prepare_filename(info)
            
            # 2. GRAB THE THUMBNAIL: Get the official thumbnail URL from the social platform
            thumbnail_url = info.get('thumbnail', '')

        if not actual_file_path or not os.path.exists(actual_file_path):
            return jsonify({"error": "Failed to download video file locally."}), 500

        if os.path.getsize(actual_file_path) == 0:
            return jsonify({"error": "Downloaded video is empty."}), 500

        ext = actual_file_path.split('.')[-1].lower()
        mime_type = 'video/webm' if ext == 'webm' else 'video/mp4'

        # Upload the file to Gemini
        upload_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={GEMINI_API_KEY}"
        headers = {
            'X-Goog-Upload-Protocol': 'raw',
            'X-Goog-Upload-Header-Content-Type': mime_type
        }

        with open(actual_file_path, 'rb') as f:
            upload_res = requests.post(upload_url, headers=headers, data=f)
            
        upload_data = upload_res.json()

        if 'file' not in upload_data:
            return jsonify({'error': 'Upload to Gemini failed', 'details': upload_data}), 500

        file_uri = upload_data['file']['uri']
        file_name = upload_data['file']['name']

        # Wait for Gemini to process the video
        file_state = upload_data['file']['state']
        while file_state == 'PROCESSING':
            time.sleep(3)
            check_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GEMINI_API_KEY}"
            check_res = requests.get(check_url).json()
            file_state = check_res.get('state')
            if file_state == 'FAILED':
                return jsonify({'error': 'Video processing failed on Gemini servers.'}), 500

        # Generate the actual content using your specified model
        gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [
                    {"fileData": {"mimeType": mime_type, "fileUri": file_uri}},
                    {"text": prompt}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        gen_res = requests.post(gen_url, headers={'Content-Type': 'application/json'}, json=payload).json()

        if 'error' in gen_res:
            return jsonify({'error': 'Gemini API Error', 'details': gen_res}), 400

        text = gen_res['candidates'][0]['content']['parts'][0]['text']
        
        # Parse the JSON returned by Gemini
        parsed_result = json.loads(text)
        
        # 3. INJECT THE IMAGE: Add the thumbnail URL to the final output expected by your app
        parsed_result['image'] = thumbnail_url
        
        return jsonify(parsed_result)

    except Exception as e:
        return jsonify({"error": f"Failed to process video: {str(e)}"}), 500
        
    finally:
        # CRITICAL: Cleanup the actual file that was downloaded
        if actual_file_path and os.path.exists(actual_file_path):
            os.remove(actual_file_path)
