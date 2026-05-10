import requests
import google.generativeai as genai
import os
from flask import Flask, request, jsonify
from supabase import create_client
import threading
import time

app = Flask(__name__)

# ============ CONFIGURAÇÕES ============
STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ STRAVA ============
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
        headers={"Authorization": f"Bearer {token}"})
    return r.json()

# ============ GEMINI ============
def analyze_with_gemini(activity):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("models/gemini-2.5-flash")

    distancia = round(activity.get('distance', 0) / 1000, 2)
    tempo_min = round(activity.get('moving_time', 0) / 60, 1)
    velocidade = round(activity.get('average_speed', 0) * 3.6, 2)
    pace_seg = (activity.get('moving_time', 0) / (activity.get('distance', 0) / 1000)) if activity.get('distance') else 0
    pace_min = int(pace_seg // 60)
    pace_sec = int(pace_seg % 60)

    prompt = f"""
Você é um coach de corrida de elite para atletas avançados focados em melhorar velocidade e pace.

Analise o treino e gere relatório completo em português:

- Nome: {activity.get('name', 'Treino')}
- Tipo: {activity.get('type', 'Run')}
- Distância: {distancia} km
- Tempo: {tempo_min} min
- Pace: {pace_min}:{pace_sec:02d} min/km
- Velocidade: {velocidade} km/h
- FC média: {activity.get('average_heartrate', 'N/A')} bpm
- FC máxima: {activity.get('max_heartrate', 'N/A')} bpm
- Elevação: {activity.get('total_elevation_gain', 0)} m
- Calorias: {activity.get('calories', 'N/A')}
- Cadência: {activity.get('average_cadence', 'N/A')} ppm

Estruture com: Resumo, Pontos Fortes, Pontos de Melhoria, Análise de Performance, Sugestão de Próximo Treino e Dica do Coach.
"""
    return model.generate_content(prompt).text

def chat_with_gemini(user_message, activity_id=None):
    """Chat com a IA usando contexto de todos os treinos"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    
    # Buscar histórico de treinos
    treinos = supabase_client.table('analyses').select('*').order('created_at', desc=True).limit(20).execute()
    treinos_data = treinos.data
    
    # Buscar histórico de mensagens (últimas 10)
    msgs = supabase_client.table('messages').select('*').order('created_at', desc=True).limit(10).execute()
    historico = list(reversed(msgs.data))
    
    contexto_treinos = "\n\n".join([
        f"Treino {i+1}: {t.get('activity_name')} ({t.get('activity_type')}) - "
        f"{t.get('distance_km')}km em {t.get('duration_min')}min - "
        f"Pace: {t.get('pace')} - FC: {t.get('heart_rate_avg')}bpm\n"
        f"Análise: {(t.get('analysis') or '')[:500]}..."
        for i, t in enumerate(treinos_data)
    ])
    
    contexto_msgs = "\n".join([
        f"{m['role']}: {m['content']}" for m in historico
    ])
    
    treino_atual = ""
    if activity_id:
        atual = next((t for t in treinos_data if str(t.get('activity_id')) == str(activity_id)), None)
        if atual:
            treino_atual = f"\n\n=== TREINO QUE O USUÁRIO ESTÁ PERGUNTANDO ===\n{atual.get('activity_name')} - Análise: {atual.get('analysis')}"
    
    prompt = f"""Você é um coach de corrida de elite que está conversando com seu atleta avançado focado em melhorar velocidade e pace.

=== HISTÓRICO DE TREINOS DO ATLETA (mais recentes primeiro) ===
{contexto_treinos}
{treino_atual}

=== CONVERSA RECENTE ===
{contexto_msgs}

=== PERGUNTA ATUAL DO ATLETA ===
{user_message}

Responda de forma direta, técnica e motivadora. Use os dados dos treinos para embasar respostas. Seja conciso (máximo 1500 caracteres)."""
    
    return model.generate_content(prompt).text

# ============ SUPABASE ============
def save_analysis(activity, analysis):
    distancia = round(activity.get('distance', 0) / 1000, 2)
    tempo_min = round(activity.get('moving_time', 0) / 60, 1)
    pace_seg = (activity.get('moving_time', 0) / (activity.get('distance', 0) / 1000)) if activity.get('distance') else 0
    pace_str = f"{int(pace_seg // 60)}:{int(pace_seg % 60):02d}"

    supabase_client.table('analyses').insert({
        "activity_id": str(activity.get('id')),
        "activity_name": activity.get('name'),
        "activity_type": activity.get('type'),
        "distance_km": distancia,
        "duration_min": tempo_min,
        "pace": pace_str,
        "heart_rate_avg": activity.get('average_heartrate'),
        "analysis": analysis
    }).execute()

def save_message(role, content, source, activity_id=None):
    supabase_client.table('messages').insert({
        "role": role,
        "content": content,
        "source": source,
        "activity_id": str(activity_id) if activity_id else None
    }).execute()

# ============ TELEGRAM ============
def send_telegram(message):
    message = message[:4000]
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    })

def telegram_listener():
    """Roda em thread separada, ouvindo mensagens do Telegram"""
    last_update_id = 0
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30}
            )
            updates = r.json().get("result", [])
            
            for update in updates:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                
                # Só responde mensagens do usuário autorizado e que não sejam comandos
                if chat_id == TELEGRAM_CHAT_ID and text and not text.startswith("/"):
                    save_message("user", text, "telegram")
                    resposta = chat_with_gemini(text)
                    save_message("assistant", resposta, "telegram")
                    send_telegram(f"🤖 {resposta}")
        except Exception as e:
            print(f"Erro no listener Telegram: {e}")
            time.sleep(5)

# ============ ROTAS ============
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
        save_analysis(activity, analysis)
        send_telegram(f"🏃 Análise do seu treino:\n\n{analysis}")
    return jsonify({"status": "ok"})

@app.route("/chat", methods=["POST"])
def chat():
    """Endpoint usado pelo app web"""
    data = request.json
    user_message = data.get("message", "")
    activity_id = data.get("activity_id")
    
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400
    
    save_message("user", user_message, "web", activity_id)
    resposta = chat_with_gemini(user_message, activity_id)
    save_message("assistant", resposta, "web", activity_id)
    
    return jsonify({"response": resposta})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "online"})

# Iniciar listener do Telegram em thread separada
threading.Thread(target=telegram_listener, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
