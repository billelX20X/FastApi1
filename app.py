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





##################################################################################################

@app.route('/check_plant_status', methods=['POST'])
def check_plant_status():
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
        mime_type = image_file.mimetype
    except Exception as e:
        return jsonify({"error": f"Failed to process image file: {str(e)}"}), 500

    # 2. Pass the base64 image data to the Gemini API
    try:
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

        prompt_text = """
        Analyze this image of a plant and assess its current health status
        based on visible signs such as leaf color, wilting, spotting, pests,
        or drooping. Return ONLY a valid JSON object matching this exact
        structure, with no other text.

        {
          "status": "Healthy or Needs Attention"
        }
        """

        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
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
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "enum": ["Healthy", "Needs Attention"]
                        }
                    },
                    "required": ["status"]
                }
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

        # 3. Extract and validate the status from Gemini's response
        try:
            raw_text = gemini_data['candidates'][0]['content']['parts'][0]['text']

            raw_text = raw_text.strip()
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            elif raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]

            status_data = json.loads(raw_text.strip())
            status = status_data.get('status', '').strip()

            # Hard safety net in case the model still drifts off-list
            if status not in ('Healthy', 'Needs Attention'):
                status = 'Needs Attention'

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return jsonify({
                "error": "Failed to parse the status from Gemini",
                "details": str(e),
                "raw_gemini_output": gemini_data
            }), 500

        # 4. Return the final response
        return jsonify({
            "status": "success",
            "plant_status": status
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502


###########################################################################################################
##################################################################################################

@app.route('/generate_recovery_plan', methods=['POST'])
def generate_recovery_plan():
    # 1. Get the uploaded image from the incoming form-data request
    if 'image' not in request.files:
        return jsonify({"error": "Please provide an 'image' file in the form data"}), 400

    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    # Optional: Passing the plant name helps the AI give more accurate advice
    plant_name = request.form.get('plant_name', 'this plant')

    # Read the file and encode it to base64 for Gemini
    try:
        image_bytes = image_file.read()
        encoded_image = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = image_file.mimetype
    except Exception as e:
        return jsonify({"error": f"Failed to process image file: {str(e)}"}), 500

    # 2. Pass the base64 image data to the Gemini API
    try:
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

        prompt_text = f"""
        You are an expert botanist. Analyze this image of a sick {plant_name}.
        Identify the likely disease or care issue (e.g., Root Rot, Sunburn, Underwatering).
        Create a 7-day step-by-step intensive recovery plan to save the plant.
        
        Generate exactly 4 to 6 steps. 
        Space them out over the 7 days (e.g., Day 1, Day 2, Days 4-6).
        Make sure the first step requires a photo (requires_photo: true) to establish a baseline.
        Make sure at least one other step requires a photo.
        
        Return ONLY a valid JSON object matching the requested schema.
        """

        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
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
                "responseMimeType": "application/json",
                # We use responseSchema to FORCE Gemini to output the exact structure needed for your DB
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "diagnosis_reason": {
                            "type": "STRING",
                            "description": "Short summary of the issue, e.g., 'Root Rot and Low Humidity'"
                        },
                        "total_days": {
                            "type": "INTEGER",
                            "description": "Always 7"
                        },
                        "steps": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "day_number": { "type": "INTEGER", "description": "Chronological order, e.g., 1, 2, 3, 4" },
                                    "day_label": { "type": "STRING", "description": "e.g., 'SCHEDULED: DAY 1' or 'SCHEDULED: DAYS 4-6'" },
                                    "title": { "type": "STRING", "description": "Short action title, e.g., 'Root Surgery'" },
                                    "description": { "type": "STRING", "description": "1-2 sentences explaining what to do" },
                                    "info_note": { "type": "STRING", "description": "A short tip or comparison note" },
                                    "requires_photo": { "type": "BOOLEAN", "description": "True if the user should take a picture at this step" }
                                },
                                "required": ["day_number", "day_label", "title", "description", "info_note", "requires_photo"]
                            }
                        }
                    },
                    "required": ["diagnosis_reason", "total_days", "steps"]
                }
            }
        }

        gemini_response = requests.post(
            gemini_endpoint,
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=45
        )
        gemini_response.raise_for_status()
        gemini_data = gemini_response.json()

        # 3. Extract and parse the generated JSON
        try:
            raw_text = gemini_data['candidates'][0]['content']['parts'][0]['text']

            # Clean markdown wrappers if Gemini included them
            raw_text = raw_text.strip()
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            elif raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]

            recovery_plan_data = json.loads(raw_text.strip())

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return jsonify({
                "error": "Failed to parse the recovery plan from Gemini",
                "details": str(e),
                "raw_gemini_output": gemini_data
            }), 500

        # 4. Return the perfect JSON object to the frontend
        return jsonify({
            "status": "success",
            "recovery_plan": recovery_plan_data
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502

        
###########################################################################################################

@app.route('/create_diy_project_from_social_media_url', methods=['POST'])
def create_diy_project():
    # 1. Get the original social media URL from request body
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Please provide a 'url' in the JSON body"}), 400
    
    original_url = data['url']

    # 2. Call SocialFetch API to get the video link and thumbnail
    try:
        socialfetch_url = f"https://api.socialfetch.dev/v1/tiktok/videos?url={original_url}"
        sf_response = requests.get(
            socialfetch_url,
            headers={"x-api-key": SOCIALFETCH_API_KEY},
            timeout=10
        )
        sf_response.raise_for_status()
        sf_data = sf_response.json()
        
        media_info = sf_data.get('data', {}).get('media', {})
        thumbnail_url = media_info.get('thumbnailUrl', '') 
        direct_video_link = media_info.get('downloadWithoutWatermarkUrl') or media_info.get('downloadUrl')
        
        if not direct_video_link:
            return jsonify({
                "error": "Could not extract direct video link from SocialFetch response", 
                "socialfetch_raw": sf_data
            }), 500

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to fetch data from SocialFetch: {str(e)}"}), 502

    # 3. Pass video link to Gemini to extract DIY Project structure
    try:
        gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
        
        prompt_text = """
        Watch this DIY / step-by-step project video carefully. 
        Extract all the required materials and the step-by-step instructions shown or described in the video.
        
        For each material, choose a valid, standard Feather icon string that best represents it 
        (e.g., 'scissors', 'droplet', 'square', 'box', 'tool', 'coffee', 'layers', 'package', 'sun', 'disc').
        
        Return ONLY a valid JSON object matching the enforced schema.
        """

        gemini_payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
                        {
                            "file_data": {
                                "file_uri": direct_video_link
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "title": { "type": "STRING", "description": "Catchy title for the DIY project" },
                        "description": { "type": "STRING", "description": "2-3 sentence overview of the project" },
                        "difficulty": { "type": "STRING", "description": "e.g. BEGINNER, INTERMEDIATE, or ADVANCED" },
                        "estimatedTime": { "type": "STRING", "description": "e.g. 45 MINS, 2 HOURS, 1 DAY" },
                        "materials": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "id": { "type": "STRING" },
                                    "name": { "type": "STRING", "description": "Short name of material, e.g., Glass jar" },
                                    "icon": { "type": "STRING", "description": "Feather icon name" }
                                },
                                "required": ["id", "name", "icon"]
                            }
                        },
                        "steps": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "id": { "type": "STRING" },
                                    "title": { "type": "STRING", "description": "Short step title, e.g. Make the Cut" },
                                    "description": { "type": "STRING", "description": "Detailed explanation for this step" }
                                },
                                "required": ["id", "title", "description"]
                            }
                        }
                    },
                    "required": ["title", "description", "difficulty", "estimatedTime", "materials", "steps"]
                }
            }
        }

        gemini_response = requests.post(
            gemini_endpoint,
            headers={"Content-Type": "application/json"},
            json=gemini_payload,
            timeout=45
        )
        gemini_response.raise_for_status()
        gemini_data = gemini_response.json()
        
        # 4. Extract and parse response
        try:
            raw_text = gemini_data['candidates'][0]['content']['parts'][0]['text'].strip()
            
            if raw_text.startswith('```json'):
                raw_text = raw_text[7:]
            elif raw_text.startswith('```'):
                raw_text = raw_text[3:]
            if raw_text.endswith('```'):
                raw_text = raw_text[:-3]
                
            project_data = json.loads(raw_text.strip())
            
            # Inject thumbnail from SocialFetch as heroImageUrl
            project_data['heroImageUrl'] = thumbnail_url
            
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return jsonify({
                "error": "Failed to parse the DIY project data from Gemini",
                "details": str(e),
                "raw_gemini_output": gemini_data
            }), 500

        # 5. Return payload directly ready for React Native screen
        return jsonify({
            "status": "success",
            "project": project_data
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": f"Failed to generate content from Gemini: {str(e)}",
            "gemini_raw_error": gemini_response.text if 'gemini_response' in locals() else None
        }), 502
