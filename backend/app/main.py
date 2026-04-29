# main.py
import uvicorn
import os

# Assicurati che l'import rispecchi la posizione di api_server.py
# Se api_server è dentro app/api/ usiamo app.api.api_server
from app.api.api_server import create_app

app = create_app()

if __name__ == "__main__":
    # Leggiamo porta e host da env per flessibilità (opzionale)
    port = int(os.getenv("GATEWAY_PORT", 8000))
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=True
    )