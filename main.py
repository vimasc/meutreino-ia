import requests
import google.generativeai as genai
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============ CONFIGURAÇÕES (via variáveis de ambiente) ============
STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_strava_token():
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "refresh_token": STRAVA_REFRESH_TOKEN,
        "grant_type": "refresh_token"
    })
    return r.json()["access_token"]

def get_activity(activity_id, token):
    r = requests.get(f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()

def analyze_with_gemini(activity):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    prompt = f"""
    Analise esse treino de forma detalhada e motivacional em português:
    - Tipo: {activity.get('type')}
    - Nome: {activity.get('name')}
    - Distância: {round(activity.get('distance', 0)/1000, 2)} km
    - Tempo: {round(activity.get('moving_time', 0)/60)} minutos
    - Velocidade média: {round(activity.get('average_speed', 0)*3.6, 1)} km/h
    - Frequência cardíaca média: {activity.get('average_heartrate', 'N/A')} bpm
    - Frequência cardíaca máxima: {activity.get('max_heartrate', 'N/A')} bpm
    - Elevação: {activity.get('total_elevation_gain', 0)} m
    - Calorias: {activity.get('calories', 'N/A')}
    Dê um feedback completo: pontos positivos, o que melhorar e uma dica para o próximo treino.
    """
    response = model.generate_content(prompt)
    return response.text

def send_telegram(message):
    message = message[:4000]
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    })

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.verify_token") == "meutreino123":
        return request.args.get("hub.challenge")
    return "Token inválido", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if data.get("aspect_type") == "create" and data.get("object_type") == "activity":
        activity_id = data.get("object_id")
        token = get_strava_token()
        activity = get_activity(activity_id, token)
        analysis = analyze_with_gemini(activity)
        send_telegram(f"🏃 Análise do seu treino:\n\n{analysis}")
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
