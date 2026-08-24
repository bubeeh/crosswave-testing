FROM python:3.11-slim

# Dipendenze di sistema (ffmpeg è fondamentale per yt-dlp e per la normalizzazione audio loudnorm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dei requisiti e installazione pacchetti Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia del codice sorgente
COPY . .

# Cartella di output e file di DB per la prima inizializzazione
RUN mkdir -p downloads && touch crosswave.db resolver_cache.db

ENV PORT=5002
ENV FLASK_DEBUG=0
ENV PYTHONUNBUFFERED=1
EXPOSE 5002

CMD ["python", "app.py"]
