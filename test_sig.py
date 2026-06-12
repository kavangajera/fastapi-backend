from fastapi import FastAPI, File, UploadFile

app = FastAPI()


@app.post("/test")
async def test(images: list[UploadFile | str] | None = File(None)):
    return {"images": images}
