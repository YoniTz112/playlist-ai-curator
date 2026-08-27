import os
import json
import streamlit as st
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import google.generativeai as genai

load_dotenv()

st.set_page_config(page_title="AI Spotify Playlist Curator", page_icon="🎧", layout="centered")

# Pega das variáveis de ambiente (local .env ou Secrets na nuvem)
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")

SCOPE = "playlist-modify-public playlist-modify-private user-top-read playlist-read-private"

# Cria o gerenciador sem salvar cache em arquivo fixo
auth_manager = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=SCOPE,
    show_dialog=True
)

# Trata o retorno do login (código na URL)
code = st.query_params.get("code")
if code and "token_info" not in st.session_state:
    token_info = auth_manager.get_access_token(code, as_dict=True)
    st.session_state["token_info"] = token_info
    st.query_params.clear()
    st.rerun()

# Se não estiver logado, exibe o botão de login
if "token_info" not in st.session_state:
    st.title("🎧 Curador de Playlists com IA")
    st.write("Crie playlists personalizadas no seu Spotify usando inteligência artificial!")
    auth_url = auth_manager.get_authorize_url()
    st.link_button("👉 Conectar com o Spotify", auth_url, type="primary")
    st.stop()

# Conecta no Spotify com o token do usuário atual
token_info = st.session_state["token_info"]
sp = spotipy.Spotify(auth=token_info["access_token"])

try:
    user_info = sp.current_user()
    st.sidebar.success(f"Logado como: **{user_info['display_name']}**")
    if st.sidebar.button("Sair"):
        del st.session_state["token_info"]
        st.rerun()
except Exception:
    st.error("Sessão expirada. Faça login novamente.")
    del st.session_state["token_info"]
    st.rerun()

# --- Funções Auxiliares ---
def get_user_taste():
    try:
        top_artists = sp.current_user_top_artists(limit=8, time_range="short_term")
        top_tracks = sp.current_user_top_tracks(limit=8, time_range="short_term")
        artists = [a["name"] for a in top_artists.get("items", [])]
        tracks = [f"{t['name']} ({t['artists'][0]['name']})" for t in top_tracks.get("items", [])]
        return f"Artistas favoritos: {', '.join(artists)}. Faixas favoritas: {', '.join(tracks)}."
    except Exception:
        return ""

def extract_playlist_tracks(playlist_url):
    try:
        playlist_id = playlist_url.split("/")[-1].split("?")[0]
        results = sp.playlist_items(playlist_id, limit=15)
        tracks = [f"{i['track']['name']} - {i['track']['artists'][0]['name']}" for i in results.get("items", []) if i.get("track")]
        return ", ".join(tracks)
    except Exception:
        return ""

def generate_playlist_with_ai(prompt_user, context_taste, base_playlist_tracks, num_tracks=15):
    system_instruction = f"""
    Você é um curador musical profissional e especialista no catálogo do Spotify.
    Contexto do usuário: {context_taste}
    Playlist base: {base_playlist_tracks}
    Pedido/Vibe: {prompt_user}
    
    Retorne EXCLUSIVAMENTE um JSON:
    {{
      "playlist_name": "Nome criativo e estiloso",
      "description": "Descrição envolvente com emojis",
      "tracks": [
        {{"title": "Nome Exato da Música", "artist": "Nome do Artista"}},
        ... ({num_tracks} faixas)
      ]
    }}
    Sugira apenas faixas reais do catálogo global do Spotify.
    """
    res = model.generate_content(system_instruction, generation_config={"response_mime_type": "application/json"})
    return json.loads(res.text)

# --- Interface Principal ---
st.title("🎧 Curador de Playlists com IA")

with st.form("playlist_form"):
    user_prompt = st.text_area("O que você quer ouvir hoje?", placeholder="Ex: Synthwave noturno para focar na programação...")
    use_taste = st.checkbox("Considerar meu histórico recente de músicas", value=True)
    base_playlist = st.text_input("Link de playlist de referência (opcional)")
    num_tracks = st.slider("Quantidade de músicas", 5, 30, 15)
    submitted = st.form_submit_button("Gerar Playlist")

if submitted:
    if not user_prompt and not base_playlist:
        st.warning("Escreva o estilo ou envie um link de referência!")
    else:
        with st.spinner("Criando sua playlist com o Gemini..."):
            context_taste = get_user_taste() if use_taste else ""
            base_tracks = extract_playlist_tracks(base_playlist) if base_playlist else ""
            ai_data = generate_playlist_with_ai(user_prompt, context_taste, base_tracks, num_tracks)
            
            st.subheader(f"✨ {ai_data['playlist_name']}")
            st.caption(ai_data['description'])
            
            track_uris = []
            for item in ai_data["tracks"]:
                query = f"track:{item['title']} artist:{item['artist']}"
                res = sp.search(q=query, type="track", limit=1)
                items = res.get("tracks", {}).get("items", [])
                if not items:
                    res = sp.search(q=f"{item['title']} {item['artist']}", type="track", limit=1)
                    items = res.get("tracks", {}).get("items", [])
                
                if items:
                    track_uris.append(items[0]["uri"])
                    st.write(f"✅ **{items[0]['name']}** - {items[0]['artists'][0]['name']}")
            
            if track_uris:
                new_pl = sp.current_user_playlist_create(name=ai_data["playlist_name"], public=False, description=ai_data["description"])
                sp.playlist_add_items(playlist_id=new_pl["id"], items=track_uris)
                st.balloons()
                st.success(f"[👉 Abrir no Spotify]({new_pl['external_urls']['spotify']})")