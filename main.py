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

    distancia = round(activity.get('distance', 0) / 1000, 2)
    tempo_min = round(activity.get('moving_time', 0) / 60, 1)
    velocidade = round(activity.get('average_speed', 0) * 3.6, 2)
    pace_seg = (activity.get('moving_time', 0) / (activity.get('distance', 0) / 1000)) if activity.get('distance') else 0
    pace_min = int(pace_seg // 60)
    pace_sec = int(pace_seg % 60)
    fc_media = activity.get('average_heartrate', 'N/A')
    fc_max = activity.get('max_heartrate', 'N/A')
    elevacao = activity.get('total_elevation_gain', 0)
    calorias = activity.get('calories', 'N/A')
    cadencia = activity.get('average_cadence', 'N/A')
    nome = activity.get('name', 'Treino')
    tipo = activity.get('type', 'Run')
    sofrimento = activity.get('suffer_score', 'N/A')

    prompt = f"""
Você é um coach de corrida de elite, especialista em análise de performance para atletas avançados com foco em melhorar velocidade e pace.

Analise detalhadamente o seguinte treino e gere um relatório completo em português, claro e objetivo:

=== DADOS DO TREINO ===
- Nome: {nome}
- Tipo: {tipo}
- Distância: {distancia} km
- Tempo em movimento: {tempo_min} min
- Pace médio: {pace_min}:{pace_sec:02d} min/km
- Velocidade média: {velocidade} km/h
- FC média: {fc_media} bpm
- FC máxima: {fc_max} bpm
- Ganho de elevação: {elevacao} m
- Calorias: {calorias} kcal
- Cadência média: {cadencia} ppm
- Índice de sofrimento: {sofrimento}

=== ESTRUTURA DO RELATÓRIO ===

1. RESUMO DO TREINO
   - Classificação geral (Leve / Moderado / Intenso / Muito Intenso)
   - Comparação de pace com zonas de treino (Z1 a Z5)
   - Avaliação da FC em relação ao esforço

2. PONTOS FORTES
   - O que foi bem executado neste treino

3. PONTOS DE MELHORIA
   - O que pode ser otimizado com base nos dados

4. ANÁLISE DE PERFORMANCE
   - Eficiência de corrida (pace vs FC)
   - Análise da cadência (se disponível — ideal: 170-180 ppm)
   - Impacto da elevação no pace

5. SUGESTÃO DE PRÓXIMO TREINO
   - Tipo de treino recomendado (intervalado, tempo run, longo, regenerativo)
   - Pace alvo e duração sugerida
   - Objetivo do próximo treino

6. DICA DO COACH
   - Uma dica técnica personalizada para melhorar velocidade/pace

Use linguagem direta, profissional e motivadora. Seja específico com números e referências técnicas.
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
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == "meutreino123":
        return jsonify({"hub.challenge": challenge})
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
