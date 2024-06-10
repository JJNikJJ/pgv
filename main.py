import os
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import speech_recognition as sr
from translate import Translator  # Используем translate вместо googletrans
from gtts import gTTS
import logging
import urllib.parse
from pathlib import Path
from uuid import uuid4
from database import SessionLocal, engine, Base
from models import User, Message
from session import get_session_data, UserSession

from fastapi import FastAPI

app = FastAPI()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключение статики
app.mount("/static", StaticFiles(directory="static"), name="static")

# Обслуживание manifest.json и service-worker.js без использования app.mount
@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse("manifest.json")

@app.get("/service-worker.js", include_in_schema=False)
async def service_worker():
    return FileResponse("service-worker.js")

# Подключение шаблонов
templates = Jinja2Templates(directory="templates")

# Контекст шифрования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Создание всех таблиц
Base.metadata.create_all(bind=engine)
logger.info("All tables created successfully.")


# Зависимость для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_password_hash(password):
    return pwd_context.hash(password)



@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def read_about(request: Request, session_data: UserSession = Depends(get_session_data)):
    return templates.TemplateResponse("about.html", {"request": request, "user": session_data})


@app.get("/record", response_class=HTMLResponse)
async def read_record(request: Request, session_data: UserSession = Depends(get_session_data),
                      db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == session_data.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    messages = db.query(Message).filter(Message.user_id == user.id, Message.translated == False).all()

    return templates.TemplateResponse("record.html", {
        "request": request,
        "user": user,
        "messages": messages
    })


@app.get("/translate", response_class=HTMLResponse)
async def read_translate(request: Request, session_data: UserSession = Depends(get_session_data),
                         db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == session_data.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    untranslated_messages = db.query(Message).filter(Message.user_id == user.id, Message.message_type == 'voice',
                                                     Message.translated == False).all()
    translated_messages = db.query(Message).filter(Message.user_id == user.id, Message.message_type == 'voice',
                                                   Message.translated == True).all()

    return templates.TemplateResponse("translate.html", {
        "request": request,
        "user": user,
        "untranslated_messages": untranslated_messages,
        "translated_messages": translated_messages
    })


@app.get("/profile", response_class=HTMLResponse)
async def read_profile(request: Request, session_data: UserSession = Depends(get_session_data),
                       db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == session_data.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})


@app.get("/register", response_class=HTMLResponse)
async def read_register(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register", response_class=HTMLResponse)
async def handle_register(request: Request,
                          nickname: str = Form(...),
                          firstName: str = Form(...),
                          lastName: str = Form(...),
                          email: str = Form(...),
                          phone: str = Form(...),
                          password: str = Form(...),
                          confirmPassword: str = Form(...),
                          db: Session = Depends(get_db)):
    if password != confirmPassword:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Пароли не совпадают"})
    user = db.query(User).filter(User.email == email).first()
    if user:
        return templates.TemplateResponse("register.html",
                                          {"request": request, "error": "Пользователь с таким email уже существует"})
    hashed_password = get_password_hash(password)
    new_user = User(
        nickname=nickname,
        first_name=firstName,
        last_name=lastName,
        email=email,
        phone=phone,
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    response = RedirectResponse(url="/record", status_code=303)
    response.set_cookie(key="session_id", value=str(uuid4()))
    response.set_cookie(key="user_id", value=str(new_user.id))
    response.set_cookie(key="nickname", value=urllib.parse.quote(new_user.nickname))
    return response


@app.get("/login", response_class=HTMLResponse)
async def read_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
async def handle_login(request: Request, phone: str = Form(...), password: str = Form(...),
                       db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == phone).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный телефон или пароль"})

    response = RedirectResponse(url="/record", status_code=303)
    response.set_cookie(key="session_id", value=str(uuid4()))
    response.set_cookie(key="user_id", value=str(user.id))
    response.set_cookie(key="nickname", value=urllib.parse.quote(user.nickname))

    return response


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = RedirectResponse(url="/")
    response.delete_cookie("session_id")
    response.delete_cookie("user_id")
    response.delete_cookie("nickname")
    return response


@app.post("/save_text_message", response_class=HTMLResponse)
async def save_text_message(request: Request, message: str = Form(...), db: Session = Depends(get_db),
                            session_data: UserSession = Depends(get_session_data)):
    new_message = Message(
        user_id=session_data.user_id,
        message_type="text",
        content=message
    )
    db.add(new_message)
    db.commit()
    return {"message": "Text message saved successfully"}


@app.post("/save_voice_message", response_class=JSONResponse)
async def save_voice_message(request: Request, file: UploadFile = File(...), language: str = Form(...),
                             db: Session = Depends(get_db),
                             session_data: UserSession = Depends(get_session_data)):
    try:
        logger.info(f"Received file: {file.filename}")
        logger.info(f"Received language: {language}")
        directory = Path("static/voice_messages")
        if not directory.exists():
            directory.mkdir(parents=True)
            logger.info(f"Created directory: {directory}")
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"{uuid4()}.{file_extension}"
        file_location = directory / unique_filename
        logger.info(f"File will be saved to: {file_location}")
        with open(file_location, "wb+") as file_object:
            file_object.write(file.file.read())
            logger.info(f"File saved successfully at: {file_location}")
        new_message = Message(
            user_id=session_data.user_id,
            message_type="voice",
            content=str(file_location).replace("\\", "/"),
            language=language)
        db.add(new_message)
        db.commit()
        logger.info(f"Voice message saved successfully for user_id: {session_data.user_id}")
        return {"message": "Voice message saved successfully"}
    except Exception as e:
        logger.error(f"Error saving voice message: {e}")
        return JSONResponse(content={"error": f"Failed to save voice message: {str(e)}"}, status_code=500)


@app.post("/translate_message", response_class=JSONResponse)
async def translate_message(request: Request, message_id: int = Form(...), target_language: str = Form(...),
                            db: Session = Depends(get_db),
                            session_data: UserSession = Depends(get_session_data)):
    try:
        message = db.query(Message).filter(Message.id == message_id, Message.user_id == session_data.user_id).first()
        if not message:
            return JSONResponse(content={"error": "Message not found"}, status_code=404)

        # Определите исходный язык на основе вашего контекста или используйте язык, сохраненный с сообщением
        input_language = message.language
        # Путь к wav файлу
        wav_path = Path(message.content)
        # Распознавание речи
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as source:
            audio = recognizer.record(source)
        recognized_text = recognizer.recognize_google(audio, language=input_language)
        # Перевод текста
        translator = Translator(to_lang=target_language)
        translated_text = translator.translate(recognized_text)
        # Синтез речи
        tts = gTTS(translated_text, lang=target_language)
        translated_audio_path = f"static/voice_messages/{uuid4()}.mp3"
        tts.save(translated_audio_path)
        # Сохранение переведенного сообщения в базу данных
        new_message = Message(
            user_id=session_data.user_id,
            message_type="voice",
            content=translated_audio_path,
            translated=True
        )
        db.add(new_message)
        db.commit()
        return {"translated_text": translated_text, "audio_file": translated_audio_path}
    except Exception as e:
        logger.error(f"Error translating message: {e}")
        return JSONResponse(content={"error": f"Failed to translate message: {str(e)}"}, status_code=500)


@app.delete("/delete_message/{message_id}", response_class=JSONResponse)
async def delete_message(message_id: int, db: Session = Depends(get_db),
                         session_data: UserSession = Depends(get_session_data)):
    message = db.query(Message).filter(Message.id == message_id, Message.user_id == session_data.user_id).first()
    if not message:
        return JSONResponse(content={"error": "Message not found"}, status_code=404)

    db.delete(message)
    db.commit()
    if os.path.exists(message.content):
        os.remove(message.content)

    return {"message": "Message deleted successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", log_level="info", reload=True)
