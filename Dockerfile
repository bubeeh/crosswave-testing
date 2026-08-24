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

# Cartella di output e permessi
RUN mkdir -p downloads

ENV PORT=5002
ENV FLASK_DEBUG=0
EXPOSE 5002

CMD ["python", "app.py"]
