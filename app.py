import os
import tempfile
import uuid
import time
import requests
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

    # Hardcoded prompt to enforce the specific JSON structure for your Expo app
    prompt = """Analyze this video and return a strictly formatted JSON object summarizing its content.
    The JSON must match this exact structure:
    {
        "title": "A short, catchy title for the video",
        "description": "A concise, engaging description of what happens in the video.",
        "image": "Return a generic placeholder image URL, or leave blank if none applies.",
        "badgeText": "A single word categorizing the video (e.g., 'Experiment', 'Tutorial', 'Review', 'DIY')",
        "tags": ["Tag1", "Tag2"] 
    }"""

    # Create a safe base path in the system's temp directory
    base_path = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
    actual_file_path = None

    try:
        # 1. Download video and let yt-dlp determine the correct file extension
        ydl_opts = {
            'quiet': True,
            # Force mp4 if possible, fallback to best available
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True,
            'outtmpl': f"{base_path}.%(ext)s" # yt-dlp will replace %(ext)s with mp4 or webm
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # This is the magic key: get the EXACT filename yt-dlp saved it as
            actual_file_path = ydl.prepare_filename(info)

        if not actual_file_path or not os.path.exists(actual_file_path):
            return jsonify({"error": "Failed to download video file locally."}), 500

        # Check if the file is empty (prevents the INVALID_ARGUMENT error)
        if os.path.getsize(actual_file_path) == 0:
            return jsonify({"error": "Downloaded video is empty."}), 500

        # Determine the correct MIME type based on the actual downloaded file
        ext = actual_file_path.split('.')[-1].lower()
        mime_type = 'video/webm' if ext == 'webm' else 'video/mp4'

        # 2. Upload the file to Gemini
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

        # 3. Wait for Gemini to process the video
        file_state = upload_data['file']['state']
        while file_state == 'PROCESSING':
            time.sleep(3)
            check_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={GEMINI_API_KEY}"
            check_res = requests.get(check_url).json()
            file_state = check_res.get('state')
            if file_state == 'FAILED':
                return jsonify({'error': 'Video processing failed on Gemini servers.'}), 500

        # 4. Generate the actual content using your specified model
        gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [
                    {"fileData": {"mimeType": mime_type, "fileUri": file_uri}},
                    {"text": prompt}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json" # Forces Gemini to output raw JSON
            }
        }

        gen_res = requests.post(gen_url, headers={'Content-Type': 'application/json'}, json=payload).json()

        # 5. Return the result safely
        if 'error' in gen_res:
            return jsonify({'error': 'Gemini API Error', 'details': gen_res}), 400

        text = gen_res['candidates'][0]['content']['parts'][0]['text']
        
        # We can parse it and return it as a proper JSON response rather than a stringified JSON
        import json
        parsed_result = json.loads(text)
        
        return jsonify(parsed_result)

    except Exception as e:
        return jsonify({"error": f"Failed to process video: {str(e)}"}), 500
        
    finally:
        # 6. CRITICAL: Cleanup the actual file that was downloaded
        if actual_file_path and os.path.exists(actual_file_path):
            os.remove(actual_file_path)

