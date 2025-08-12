import os
import uuid
import requests
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse
from gtts import gTTS
import time

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HOST_URL = os.getenv("HOST_URL", "http://localhost:8000")
PORT = int(os.getenv("PORT", 8000))

# make static folder
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Helpers for OpenAI ---
OPENAI_TRANSCRIPT_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {OPENAI_API_KEY}"}


def transcribe_audio_from_url(file_url: str, filename: str) -> str:
    """Download remote audio and send to OpenAI Whisper transcription endpoint (returns text)."""
    # download file
    resp = requests.get(file_url)
    resp.raise_for_status()
    audio_path = STATIC_DIR / filename
    with open(audio_path, "wb") as f:
        f.write(resp.content)

   
    files = {"file": open(audio_path, "rb")}
  
    data = {"model": "whisper-1"}
    r = requests.post(OPENAI_TRANSCRIPT_URL, headers=HEADERS, files=files, data=data)
    if r.status_code != 200:
        raise Exception(f"Transcription error: {r.status_code} {r.text}")
    j = r.json()
    return j.get("text", "")


def ask_chatgpt(prompt_text: str) -> str:
    """Send prompt_text to OpenAI ChatCompletion and return assistant reply."""
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant answering callers briefly."},
            {"role": "user", "content": prompt_text},
        ],
        "max_tokens": 250,
    }
    r = requests.post(OPENAI_CHAT_URL, headers={**HEADERS, "Content-Type": "application/json"}, json=payload)
    if r.status_code != 200:
        raise Exception(f"Chat error: {r.status_code} {r.text}")
    j = r.json()
    return j["choices"][0]["message"]["content"].strip()


def tts_save_mp3(text: str, out_name: str) -> str:
    """Generate mp3 with gTTS and return public URL path."""
    mp3_path = STATIC_DIR / out_name
    tts = gTTS(text=text, lang="en")
    tts.save(mp3_path.as_posix())
    return f"{HOST_URL}/static/{out_name}"


# --- Twilio webhook endpoints ---

@app.post("/voice", response_class=PlainTextResponse)
async def voice_handler(request: Request):
    """
    Incoming call webhook.
    Twilio will request this on an incoming call.
    We return TwiML that prompts user then records their question and posts to /process_recording.
    """
    resp = VoiceResponse()
    # Prompt
    resp.say("Hello. Ask your question after the beep. When you are done, please hang up or press the pound key.")
    # Record - specify maxLength (seconds) and action (where Twilio posts the recording details)
    action_url = f"{HOST_URL}/process_recording"
    resp.record(max_length=30, play_beep=True, trim="trim-silence", action=action_url, finish_on_key="#")
    # If no recording, say goodbye
    resp.say("No recording received. Goodbye.")
    return PlainTextResponse(resp.to_xml(), media_type="application/xml")


@app.post("/process_recording", response_class=PlainTextResponse)
async def process_recording(RecordingUrl: str = Form(None), RecordingDuration: str = Form(None), RecordingSid: str = Form(None)):
    """
    Twilio posts recording info (RecordingUrl).
    We download the recording, transcribe, ask OpenAI, TTS the answer, and respond with TwiML to play the mp3.
    """
    # RecordingUrl example: https://api.twilio.com/2010-04-01/Accounts/AC.../Recordings/RE... 
    if not RecordingUrl:
        resp = VoiceResponse()
        resp.say("Sorry, I couldn't find your recording. Goodbye.")
        return PlainTextResponse(resp.to_xml(), media_type="application/xml")

    try:
        # Twilio's recording URL can be used as-is; add format extension? Twilio serves content-type audio/wav or audio/mp3.
        # We'll download it and feed to OpenAI
        unique = uuid.uuid4().hex
        download_filename = f"recording_{unique}.mp3"  # saved locally
        # Twilio's recording URL might require no auth if publicly accessible from Twilio
        transcription = transcribe_audio_from_url(RecordingUrl + ".mp3", download_filename)  # try .mp3 variant
        # if transcription empty, try without .mp3
        if not transcription.strip():
            transcription = transcribe_audio_from_url(RecordingUrl, download_filename)
    except Exception as e:
        # fallback: ask user to try again
        resp = VoiceResponse()
        resp.say("Sorry, there was an error processing your audio. Please try again later. Goodbye.")
        print("Error in transcription:", e)
        return PlainTextResponse(resp.to_xml(), media_type="application/xml")

    # Ask the AI
    try:
        answer = ask_chatgpt(transcription)
    except Exception as e:
        resp = VoiceResponse()
        resp.say("Sorry, I couldn't generate an answer at the moment. Goodbye.")
        print("Error in chat:", e)
        return PlainTextResponse(resp.to_xml(), media_type="application/xml")

    # Convert to speech
    out_mp3_name = f"response_{unique}.mp3"
    try:
        mp3_public_url = tts_save_mp3(answer, out_mp3_name)
    except Exception as e:
        resp = VoiceResponse()
        resp.say("Sorry, an error occurred preparing my reply. Goodbye.")
        print("Error in TTS:", e)
        return PlainTextResponse(resp.to_xml(), media_type="application/xml")

    # Respond to Twilio with TwiML to play the MP3
    resp = VoiceResponse()
    # Small pause to ensure Twilio can access the file
    resp.pause(length=1)
    resp.play(mp3_public_url)
    # Optionally loop or say goodbye
    resp.say("If you have another question, please call again. Goodbye.")
    return PlainTextResponse(resp.to_xml(), media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    print(f"Starting app on port {PORT} with HOST_URL={HOST_URL}")
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)
