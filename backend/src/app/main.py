from src.app.routers import auth
from fastapi import FastAPI
from src.app.routers import content

app = FastAPI()

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(content.router, prefix="/content", tags=["content"])

@app.get("/")
def root():
    return {"status": "Backend running"}
