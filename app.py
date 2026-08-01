from flask import Flask, request, jsonify
import requests
import os
import json
from dotenv import load_dotenv
import base64

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)

# Configure your API keys here or use environment variables
SOCIALFETCH_API_KEY = os.environ.get("SOCIAL_FEACH_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
#################################################################################################
@app.route("/", methods=["GET"])
def test():
    return jsonify({"message": "API is working"}), 200

##################################################################################################
@app.route('/create_lib_card_from_social_media_url', methods=['POST'])
def create_lib_card():
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
        
        # Extract the thumbnail URL here!
        thumbnail_url = media_info.get('thumbnailUrl', '') 
        
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
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
        
        # We use an f-string to inject the thumbnail_url. 
        # The JSON curly brackets are doubled {{ }} so Python ignores them.
        prompt_text = f"""
        Watch this video about a plant and extract the information discussed. 
        Return ONLY a valid JSON object matching this exact structure.
        
        For the hero imageUrl, use EXACTLY this link: {thumbnail_url}

        {{
          "hero": {{
            "imageUrl": "{thumbnail_url}",
            "badgeText": "Short 2-3 word catchy trait (e.g., Tender & Gorgeous)",
            "commonName": "Common name of the plant",
            "scientificName": "Botanical name"
          }},
          "careRequirements": {{
            "light": "Short text (e.g., Bright Indirect)",
            "water": "Short text (should be like this form: Every 7 - 10 days)",
            "soil": "Short text (e.g., Well-Draining)",
            "fertilizer": "Short text (e.g., Once monthly)",
            "growingZone": "Short text (e.g., Zone 9b)"
          }},
          "contextualAlert": {{
            "temperature": "Mock temperature string (e.g., 94° today.)",
            "message": "1 sentence explaining how to adjust care for this temp."
          }},
          "about": {{
            "description": "A 2-3 sentence engaging description of the plant.",
            "expertTip": "One highly actionable, specific tip for this plant."
          }}
        }}
        """

        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt_text
                        },
                        {
                            "file_data": {
                                "file_uri": direct_video_link
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        gemini_response = requests.post(
            gemini_endpoint,
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=30
        )
        gemini_response.raise_for_status()
        gemini_data = gemini_response.json()
        
        # 4. Extract and clean the plant JSON string from Gemini's response
        try:
            raw_text = gemini_data['candidates'][0]['content']['parts'][0]['text']
            
            # Gemini sometimes wraps JSON in markdown code blocks. Strip them if they exist.
            raw_text = raw_text.strip()
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            elif raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]
                
            # Parse the string back into a Python dictionary
            plant_data = json.loads(raw_text.strip())
            
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return jsonify({
                "error": "Failed to parse the plant data from Gemini",
                "details": str(e),
                "raw_gemini_output": gemini_data
            }), 500

        # 5. Return the final, clean response back to the client
        video_metadata = sf_data.get('data', {}).get('video', {})
        
        return jsonify({
            "status": "success",
            "video_id": video_metadata.get('id'),
            "caption": video_metadata.get('caption'),
            "plant_data": plant_data
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502


##################################################################################################


@app.route('/create_lib_card_from_image_file', methods=['POST'])
def create_lib_card_image():
    # 1. Get the uploaded image from the incoming form-data request
    if 'image' not in request.files:
        return jsonify({"error": "Please provide an 'image' file in the form data"}), 400
    
    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # Read the file and encode it to base64 for Gemini
    try:
        image_bytes = image_file.read()
        encoded_image = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = image_file.mimetype # e.g., 'image/jpeg', 'image/png'
    except Exception as e:
        return jsonify({"error": f"Failed to process image file: {str(e)}"}), 500

    # 2. Pass the base64 image data to the Gemini API
    try:
        # Using the same model string from your previous endpoint
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
        
        prompt_text = """
        Analyze this image of a plant and extract the following information. 
        Return ONLY a valid JSON object matching this exact structure.
        
        For the hero imageUrl, use the string "uploaded_image" (since the image is local).

        {
          "hero": {
            "imageUrl": "uploaded_image",
            "badgeText": "Short 2-3 word catchy trait (e.g., Tender & Gorgeous)",
            "commonName": "Common name of the plant",
            "scientificName": "Botanical name"
          },
          "careRequirements": {
            "light": "Short text (e.g., Bright Indirect)",
            "water": "Short text (should be like this form: Every 7 - 10 days)",
            "soil": "Short text (e.g., Well-Draining)",
            "fertilizer": "Short text (e.g., Once monthly)",
            "growingZone": "Short text (e.g., Zone 9b)"
          },
          "contextualAlert": {
            "temperature": "Mock temperature string (e.g., 94° today.)",
            "message": "1 sentence explaining how to adjust care for this temp."
          },
          "about": {
            "description": "A 2-3 sentence engaging description of the plant.",
            "expertTip": "One highly actionable, specific tip for this plant."
          }
        }
        """

        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt_text
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        gemini_response = requests.post(
            gemini_endpoint,
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=30
        )
        gemini_response.raise_for_status()
        gemini_data = gemini_response.json()
        
        # 3. Extract and clean the plant JSON string from Gemini's response
        try:
            raw_text = gemini_data['candidates'][0]['content']['parts'][0]['text']
            
            # Gemini sometimes wraps JSON in markdown code blocks. Strip them if they exist.
            raw_text = raw_text.strip()
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            elif raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]
                
            # Parse the string back into a Python dictionary
            plant_data = json.loads(raw_text.strip())
            
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return jsonify({
                "error": "Failed to parse the plant data from Gemini",
                "details": str(e),
                "raw_gemini_output": gemini_data
            }), 500

        # 4. Return the final response
        return jsonify({
            "status": "success",
            "plant_data": plant_data
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502
