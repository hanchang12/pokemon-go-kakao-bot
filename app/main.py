from fastapi import FastAPI

app = FastAPI(
    title="Pokemon GO Kakao Bot",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "name": "Pokemon GO Kakao Bot",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }
