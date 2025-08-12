# Voice Q&A Bot (Twilio + OpenAI + gTTS)

Simple Q&A voice bot:
- Twilio records caller question → server
- Server transcribes with OpenAI Whisper
- Server queries ChatGPT (gpt-3.5-turbo)
- Reply is converted to speech via gTTS and played back to caller

## Setup
1. Add the API keys in the env file.

2. Install deps:
   pip install -r requirements.txt

3. Run server:
   python app.py

4. Run ngrok:
   ngrok http 8000

5. Configure Twilio phone number voice webhook to:
   https://<ngrok-url>/voice (HTTP POST)

6. Call the Twilio number and speak after the beep.

