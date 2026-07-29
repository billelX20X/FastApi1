from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv  # Add this import

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)

# Configure your API keys here or use environment variables
SOCIALFETCH_API_KEY = os.environ.get("SOCIAL_FEACH_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

@app.route('/analyze-video', methods=['POST'])
def analyze_video():
    # 1. Get the original URL from the incoming request
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Please provide a 'url' in the JSON body"}), 400
    
    original_url = data['url']

    # 2. Call SocialFetch API to get the direct video link
    try:
        socialfetch_url = f"https://api.socialfetch.dev/v1/tiktok/videos?url={original_url}"
        sf_response = requests.get(
            socialfetch_url,
            headers={"x-api-key": SOCIALFETCH_API_KEY},
            timeout=10
        )
        sf_response.raise_for_status()
        sf_data = sf_response.json()
        
        # Parse based on the provided SocialFetch structure
        media_info = sf_data.get('data', {}).get('media', {})
        
        # Try unwatermarked first, fallback to standard downloadUrl
        direct_video_link = media_info.get('downloadWithoutWatermarkUrl') or media_info.get('downloadUrl')
        
        if not direct_video_link:
            return jsonify({
                "error": "Could not extract direct video link from SocialFetch response", 
                "socialfetch_raw": sf_data
            }), 500

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to fetch data from SocialFetch: {str(e)}"}), 502

    # 3. Pass the direct video link to the Gemini API
    try:
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
        
        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": "Watch this video and tell me the main topic, summarize it in 5 bullet points, and mention any important people, places, or products discussed."
                        },
                        {
                            "file_data": {
                                "file_uri": direct_video_link
                            }
                        }
                    ]
                }
            ]
        }

        gemini_response = requests.post(
            gemini_endpoint,
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=30 # Increased timeout since Gemini might take time to process video
        )
        gemini_response.raise_for_status()
        gemini_data = gemini_response.json()

        # 4. Return the Gemini response and some basic video info back to the client
        video_metadata = sf_data.get('data', {}).get('video', {})
        
        return jsonify({
            "status": "success",
            "video_id": video_metadata.get('id'),
            "caption": video_metadata.get('caption'),
            "gemini_analysis": gemini_data
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502

