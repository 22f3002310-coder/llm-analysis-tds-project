from google import genai
from google.genai import types
from langchain_core.tools import tool
from dotenv import load_dotenv
import os

load_dotenv()
client = genai.Client()

@tool
def transcribe_audio(audio_path: str) -> str:
    """
    Transcribes an audio file using Google Gemini API.
    
    Parameters
    ----------
    audio_path : str
        The local path to the audio file to transcribe.
        
    Returns
    -------
    str
        The transcription text or error message.
    """
    if not os.path.exists(audio_path):
        # Try looking in LLMFiles
        alt_path = os.path.join("LLMFiles", os.path.basename(audio_path))
        if os.path.exists(alt_path):
            audio_path = alt_path
        else:
            return f"Error: File {audio_path} does not exist."
    
    try:
        with open(audio_path, "rb") as f:
            audio_data = f.read()
            
        # Guess mime type based on extension
        mime_type = "audio/mp3"
        if audio_path.endswith(".wav"):
            mime_type = "audio/wav"
        elif audio_path.endswith(".ogg"):
            mime_type = "audio/ogg"
            
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(
                            data=audio_data,
                            mime_type=mime_type
                        ),
                        types.Part.from_text(text="Please transcribe this audio file exactly as it is spoken. If there are codes or secrets, make sure to include them.")
                    ]
                )
            ]
        )
        return response.text
    except Exception as e:
        return f"Error transcribing audio: {str(e)}"
