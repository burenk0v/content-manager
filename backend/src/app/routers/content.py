from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def get_content():
    return [
        {"id": 1, "title": "AI Post 1", "body": "Generated content example"},
        {"id": 2, "title": "AI Post 2", "body": "Another content example"}
    ]
